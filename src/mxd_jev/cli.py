from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .config import load, write_default
from .jev import GatewayError, JevClient


def parser():
    p = argparse.ArgumentParser(description="MXD visual control prototype")
    p.add_argument("--config", type=Path, default=Path("local/config.json"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create local configuration (never overwrites)")
    sub.add_parser("check", help="Validate configuration")
    sub.add_parser("probe", help="One minimal native Jev request; never sends game images")
    capture = sub.add_parser("capture", help="Capture the Windows game client after a countdown")
    capture.add_argument("--output", type=Path, default=Path("local/capture.png"))
    capture.add_argument("--delay", type=float, default=5)
    cal = sub.add_parser("calibrate", help="Select visual templates and UI regions")
    cal.add_argument("source", type=Path)
    cal.add_argument("--seconds", type=float, default=0)
    cal.add_argument("--crop-client", action="store_true", help="Select client area when source includes window borders")
    extra = sub.add_parser("add-template", help="Add a player/monster appearance without replacing calibration")
    extra.add_argument("kind", choices=["player", "monster"])
    extra.add_argument("source", type=Path)
    extra.add_argument("--seconds", type=float, default=0)
    extra.add_argument("--video-crop", action="store_true", help="Use the saved video client crop")
    replay = sub.add_parser("replay", help="Read-only video analysis; never sends input or API calls")
    replay.add_argument("video", type=Path)
    replay.add_argument("--output", type=Path, default=Path("outputs/replay"))
    replay.add_argument("--sample-hz", type=float, default=5)
    replay.add_argument("--seconds", type=float)
    replay.add_argument("--show", action="store_true")
    live = sub.add_parser("run", help="Observe by default; --execute enables F8 arming")
    live.add_argument("--execute", action="store_true")
    live.add_argument("--mode", choices=["rules", "jev"], default="rules")
    live.add_argument("--log", type=Path, default=None)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            write_default(args.config)
            print(f"Created {args.config}. Configure keys and run calibration.")
            return 0
        config = load(args.config)
        if args.command == "check":
            print("Configuration syntax and ranges OK (not a live calibration check).")
        elif args.command == "probe":
            client = JevClient(config["jev"])
            decision, meta = client.ask({"health": "normal", "visible_targets": "none"}, {
                "wait": "No target is visible: hold position.",
                "attack": "Attack only if a target is visible.",
            })
            print(json.dumps({"choice": decision.action, "confidence": decision.confidence,
                              "probabilities": decision.probabilities, **meta}, ensure_ascii=False, indent=2))
        elif args.command == "calibrate":
            from .calibrate import calibrate
            calibrate(args.config, args.source, args.seconds, args.crop_client)
        elif args.command == "add-template":
            from .calibrate import add_template
            add_template(args.config, args.source, args.seconds, args.kind, args.video_crop)
        elif args.command == "capture":
            import cv2
            from .windows import WindowsIO
            if not 0 <= args.delay <= 30:
                raise ValueError("delay must be 0..30 seconds")
            print(f"Focus the game window. Capturing in {args.delay} seconds...")
            time.sleep(args.delay)
            io = WindowsIO(config["window_title"])
            try:
                frame = io.capture()
                args.output.parent.mkdir(parents=True, exist_ok=True)
                ok, encoded = cv2.imencode(".png", frame)
                if not ok:
                    raise ValueError("Failed to encode screenshot")
                encoded.tofile(str(args.output))
                print(f"Saved game client screenshot: {args.output}")
            finally:
                io.close()
        elif args.command == "replay":
            from .runtime import replay
            replay(config, args.config.parent, args.video, args.output, args.sample_hz, args.seconds, args.show)
        elif args.command == "run":
            from .runtime import run_live
            log = args.log or Path("outputs") / (time.strftime("live-%Y%m%d-%H%M%S") + ".jsonl")
            run_live(config, args.config.parent, log, args.execute, args.mode)
        return 0
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    except (ValueError, OSError, RuntimeError, GatewayError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
