from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .config import load, save


def load_frame(source: Path, seconds: float = 0):
    if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
        frame = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR)
    else:
        cap = cv2.VideoCapture(str(source))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
            ok, frame = cap.read()
            if not ok:
                frame = None
        finally:
            cap.release()
    if frame is None:
        raise ValueError(f"Cannot read image/video at {seconds}s: {source}")
    return frame


def select(frame, title, optional=False):
    print(title + (" (Esc to skip)" if optional else " (Enter to confirm; Esc cancels)"))
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, min(frame.shape[1], 1280), min(frame.shape[0], 800))
    try:
        rect = tuple(map(int, cv2.selectROI(title, frame, showCrosshair=True, fromCenter=False)))
    finally:
        cv2.destroyWindow(title)
    if rect[2] == 0 or rect[3] == 0:
        if optional:
            return None
        raise ValueError("Calibration cancelled; config was not changed")
    return rect


def calibrate(config_path: Path, source: Path, seconds: float, client_crop: bool):
    config = load(config_path)
    frame = load_frame(source, seconds)
    if client_crop:
        original_h, original_w = frame.shape[:2]
        x, y, w, h = select(frame, "0. Select GAME CLIENT AREA excluding title bar and borders")
        config["video_client_roi"] = [x/original_w, y/original_h, w/original_w, h/original_h]
        frame = frame[y:y+h, x:x+w].copy()
    else:
        config["video_client_roi"] = None
    # Keep a consistent coordinate system for templates from subsequent sessions.
    frame = cv2.resize(frame, tuple(config["reference_size"]))
    h, w = frame.shape[:2]
    root = config_path.parent
    assets = root / "templates"
    assets.mkdir(parents=True, exist_ok=True)
    selected = {}
    player = select(frame, "1. Select your UNIQUE character nameplate (not pet or effects)")
    selected["player"] = player
    foot = select(frame, "2. Select a SMALL box around your CHARACTER CENTER")
    config["vision"]["player_offset"] = [
        foot[0] + foot[2]/2 - player[0] - player[2]/2,
        foot[1] + foot[3]/2 - player[1] - player[3]/2,
    ]
    selected["monster"] = select(frame, "3. Select one unobscured MONSTER body")
    for name, title, optional in [
        ("hp_roi", "4. Select full HP BAR INTERIOR including empty space; exclude text and border", False),
        ("mp_roi", "5. Select full MP BAR INTERIOR including empty space; exclude text and border", False),
        ("minimap_roi", "6. Select MINIMAP INTERIOR; exclude its title and border", True),
        ("play_roi", "7. Select GAMEPLAY AREA excluding HUD and minimap", False),
    ]:
        rect = select(frame, title, optional)
        config["vision"][name] = [rect[0]/w, rect[1]/h, rect[2]/w, rect[3]/h] if rect else None
    for name, (x, y, rw, rh) in selected.items():
        sample = frame[y:y+rh, x:x+rw]
        if cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY).std() < 2:
            raise ValueError(f"Blank {name} template")
    # Write templates only after every mandatory selection is complete.
    for name, (x, y, rw, rh) in selected.items():
        ok, encoded = cv2.imencode(".png", frame[y:y+rh, x:x+rw])
        if not ok:
            raise ValueError("Template encoding failed")
        encoded.tofile(str(assets / f"{name}.png"))
    config["vision"]["player_template"] = "templates/player.png"
    config["vision"]["player_variants"] = []
    config["vision"]["monster_templates"] = ["templates/monster.png"]
    save(config_path, config)
    print(f"Saved calibration to {config_path}. Review key bindings before live input.")


def add_template(config_path: Path, source: Path, seconds: float, kind: str, use_video_crop: bool):
    import uuid
    from .vision import crop
    config = load(config_path)
    frame = load_frame(source, seconds)
    if use_video_crop and config["video_client_roi"]:
        frame, _, _ = crop(frame, config["video_client_roi"])
    frame = cv2.resize(frame, tuple(config["reference_size"]))
    x, y, w, h = select(frame, f"Select additional {kind.upper()} sample; avoid effects/background")
    sample = frame[y:y+h, x:x+w]
    if cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY).std() < 2:
        raise ValueError("Blank template")
    offset = None
    if kind == "player":
        fx, fy, fw, fh = select(frame, "Select a SMALL box around your CHARACTER CENTER")
        offset = [fx+fw/2-x-w/2, fy+fh/2-y-h/2]
    name = f"templates/{kind}-{uuid.uuid4().hex[:8]}.png"
    path = config_path.parent / name
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", sample)
    if not ok:
        raise ValueError("Template encoding failed")
    encoded.tofile(str(path))
    if kind == "player":
        config["vision"].setdefault("player_variants", []).append({"path": name, "offset": offset})
    else:
        config["vision"]["monster_templates"].append(name)
    save(config_path, config)
    print(f"Added {name}")
