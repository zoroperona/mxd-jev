from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time

import cv2

from .config import require_calibration
from .jev import AsyncJev, JevClient
from .policy import Policy, decision_state, scene_signature
from .state import Decision
from .vision import Vision, overlay, crop


class EventLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("w", encoding="utf-8")

    def write(self, **event):
        self.file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        self.file.flush()

    def close(self):
        self.file.close()


def replay(config: dict, config_dir: Path, video: Path, output: Path, sample_hz: float,
           seconds: float | None, show: bool):
    if not 0 < sample_hz <= 30:
        raise ValueError("sample-hz must be between 0 and 30")
    require_calibration(config)
    vision, policy = Vision(config, config_dir), Policy(config)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video}")
    output.mkdir(parents=True, exist_ok=True)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise ValueError("Video has no valid frame rate")
    writer = None
    artifact = None
    for codec, extension in (("mp4v", "mp4"), ("avc1", "mp4"), ("MJPG", "avi")):
        artifact = output / ("annotated." + extension)
        candidate = cv2.VideoWriter(str(artifact), cv2.VideoWriter_fourcc(*codec),
                                    min(sample_hz, fps), tuple(config["reference_size"]))
        if candidate.isOpened():
            writer = candidate
            break
        candidate.release()
    if writer is None:
        cap.release()
        raise ValueError("Cannot create output video")
    log = EventLog(output / "events.jsonl")
    counts = {"frames": 0, "valid_frames": 0, "frames_with_monsters": 0}
    idx, next_sample = 0, 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = idx / fps
            idx += 1
            if seconds is not None and timestamp >= seconds:
                break
            if timestamp + 1e-6 < next_sample:
                continue
            next_sample += 1 / sample_hz
            if config["video_client_roi"]:
                frame, _, _ = crop(frame, config["video_client_roi"])
            obs, normalized = vision.analyze(frame, idx, timestamp)
            decision = policy.decide(obs, timestamp)
            # Read-only replay: never advance potion attempts or pretend actions happened.
            annotated = overlay(normalized, obs, f"REPLAY / PROPOSED ONLY: {decision.action} {decision.reason}")
            writer.write(annotated)
            log.write(mode="replay", video_seconds=timestamp, observation=obs.to_dict(), decision=asdict(decision), executed=False)
            counts["frames"] += 1
            counts["valid_frames"] += int(obs.valid)
            counts["frames_with_monsters"] += int(bool(obs.monsters))
            if show:
                cv2.imshow("Replay (Q to quit)", annotated)
                if cv2.waitKey(1) & 0xff == ord("q"):
                    break
    finally:
        writer.release()
        cap.release()
        log.close()
        cv2.destroyAllWindows()
    summary = {**counts, "video_artifact": artifact.name,
               "valid_fraction": counts["valid_frames"] / max(1, counts["frames"]),
               "note": "Recognition coverage, not measured detection accuracy or live gameplay success."}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def run_live(config: dict, config_dir: Path, output: Path, execute: bool, mode: str):
    from .windows import WindowsIO
    require_calibration(config)
    vision, policy = Vision(config, config_dir), Policy(config)
    worker = AsyncJev(JevClient(config["jev"])) if mode == "jev" else None
    io = None
    log = None
    active, session_start, frame_id = False, None, 0
    status = "PAUSED" if execute else "OBSERVE ONLY"
    last_shape = None
    try:
        io = WindowsIO(config["window_title"])
        log = EventLog(output)
        print("F8: start/pause (game must be foreground). F9: stop. Q: close preview.")
        print("Mode:", mode, "EXECUTION ENABLED" if execute else "OBSERVE ONLY - no game input")
        while not io.stopped:
            begin = time.monotonic()
            if io.edge("f9"):
                break
            if io.edge("f8") and execute:
                active = not active and io.focused()
                io.interrupted = False
                policy.reset()
                if active:
                    session_start = begin
                if worker:
                    worker.discard()
                status = "ACTIVE" if active else "PAUSED"
                io.release_all()
            if not io.focused():
                active = False
                status = "PAUSED: game lost focus"
                io.release_all()
                if worker:
                    worker.discard()
                if cv2.waitKey(1) & 0xff == ord("q"):
                    break
                time.sleep(0.05)
                continue
            if active and session_start is not None and begin - session_start >= config["control"]["max_session_minutes"] * 60:
                active = False
                status = "PAUSED: session time limit"
                io.release_all()
            captured_at = time.monotonic()
            frame = io.capture()
            shape = frame.shape[:2]
            if last_shape is not None and shape != last_shape:
                active = False
                status = "PAUSED: client size changed; check calibration"
                io.release_all()
                if worker:
                    worker.discard()
            last_shape = shape
            frame_id += 1
            obs, normalized = vision.analyze(frame, frame_id, captured_at)
            now = time.monotonic()
            decision = policy.decide(obs, now)
            meta = None
            # Never spend API calls while paused or merely observing.
            if active and worker:
                urgent = policy.urgent(obs, now)
                if urgent is not None:
                    worker.discard()
                    decision = urgent
                else:
                    options = policy.candidates(obs)
                    if len(options) == 1:
                        worker.discard()
                        decision = Decision("wait", "no_actionable_target", "rules")
                    else:
                        signature = scene_signature(obs, options, config)
                        result, meta = worker.poll(signature, now)
                        decision = result or Decision("wait", "awaiting_jev", "jev")
                        if decision.action != "pause":
                            worker.submit(decision_state(obs, options, config), options, signature, now, obs.timestamp)
            executed = False
            if active:
                if decision.action == "pause":
                    active = False
                    status = "PAUSED: " + decision.reason
                    io.release_all()
                elif decision.action != "wait":
                    # Recheck age and focus immediately before dispatch, after all decision work.
                    if (time.monotonic() - obs.timestamp) * 1000 > config["control"]["max_observation_age_ms"]:
                        active = False
                        status = "PAUSED: observation expired before input"
                    else:
                        duration = config["control"]["pulse_ms"] / 1000
                        executed = io.pulse(decision.action, config["keys"], duration)
                        if executed:
                            policy.executed(decision, obs, time.monotonic(), duration)
                        else:
                            active = False
                            status = "PAUSED: interrupted or focus changed"
                if active:
                    status = "ACTIVE: " + decision.action + " / " + decision.reason
            log.write(mode=mode, active=active, status=status, observation=obs.to_dict(),
                      decision=asdict(decision), executed=executed, gateway=meta)
            cv2.imshow("MXD - F8 start/pause / F9 stop", overlay(normalized, obs, f"{mode.upper()} {status}"))
            if cv2.waitKey(1) & 0xff == ord("q"):
                break
            remaining = 1 / config["control"]["tick_hz"] - (time.monotonic() - begin)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        try:
            if io:
                io.close()
        finally:
            if worker:
                worker.close()
            if log:
                log.close()
            cv2.destroyAllWindows()
