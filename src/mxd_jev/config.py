from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from urllib.parse import urlparse

DEFAULT = {
    "window_title": "冒险岛",
    "reference_size": [1440, 810],
    "video_client_roi": None,
    "keys": {"left": "left", "right": "right", "up": "up", "down": "down",
             "attack": "ctrl", "jump": "alt", "teleport": "shift",
             "hp": "delete", "mp": "end"},
    "vision": {
        "player_template": "", "player_offset": [0, -35],
        "player_variants": [],
        "monster_templates": [], "match_threshold": 0.80,
        "player_threshold": 0.85, "max_matches": 25,
        "hp_roi": None, "mp_roi": None, "minimap_roi": None,
        "play_roi": [0.09, 0.04, 0.91, 0.84],
        "minimap_yellow_hsv": [[18, 130, 150], [38, 255, 255]],
    },
    "control": {
        "tick_hz": 10, "pulse_ms": 90, "attack_range_px": 190,
        "same_level_tolerance_px": 65, "hp_threshold": 0.45,
        "mp_threshold": 0.25, "potion_cooldown_s": 1.5,
        "max_potion_attempts": 3, "stuck_seconds": 4.0,
        "max_observation_age_ms": 400, "max_session_minutes": 10,
    },
    "route": {"enabled": False, "tolerance": 0.025, "waypoints": []},
    "jev": {
        "endpoint": "https://llm-proxy.tapsvc.com/typesafe/v1/systemone",
        "model": "typesafe/jev-1.13", "api_key_env": "MXD_JEV_API_KEY",
        "timeout_s": 2.0, "interval_s": 0.5, "max_decision_age_ms": 700,
        "min_confidence": 0.75,
    },
}

KEY_NAMES = set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "left", "right", "up", "down", "ctrl", "alt", "shift", "space",
    "insert", "delete", "home", "end", "pageup", "pagedown", "tab",
} | {f"f{i}" for i in range(1, 13)}


def write_default(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"Config already exists: {path}")
    save(path, copy.deepcopy(DEFAULT))


def save(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def number(value, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid number: {label}")
    if not low <= value <= high:
        raise ValueError(f"Out of range: {label} ({low}..{high})")
    return value


def load(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    for section in DEFAULT:
        if section not in config:
            raise ValueError(f"Missing configuration section: {section}")
    if not config["window_title"].strip():
        raise ValueError("window_title must not be empty")
    width, height = config["reference_size"]
    number(width, "width", 320, 7680)
    number(height, "height", 200, 4320)
    if int(width) != width or int(height) != height:
        raise ValueError("reference_size must use integers")
    for name in DEFAULT["keys"]:
        key = config["keys"][name]
        if key not in KEY_NAMES or key in {"f8", "f9"}:
            raise ValueError(f"Invalid/reserved key for {name}: {key}. F8/F9 are reserved.")
    if len(set(config["keys"].values())) != len(config["keys"]):
        raise ValueError("Each action must use a different key")
    for name in ("hp_roi", "mp_roi", "minimap_roi", "play_roi"):
        roi = config["vision"][name]
        if roi is not None:
            if len(roi) != 4:
                raise ValueError(f"Invalid ROI: {name}")
            x, y, w, h = [number(n, name, 0, 1) for n in roi]
            if w <= 0 or h <= 0 or x + w > 1.00001 or y + h > 1.00001:
                raise ValueError(f"ROI outside image: {name}")
    if config["video_client_roi"] is not None:
        x, y, w, h = [number(n, "video_client_roi", 0, 1) for n in config["video_client_roi"]]
        if w <= 0 or h <= 0 or x + w > 1.00001 or y + h > 1.00001:
            raise ValueError("Invalid video_client_roi")
    for name in ("match_threshold", "player_threshold"):
        number(config["vision"][name], name, 0.5, 1)
    offsets = [config["vision"]["player_offset"]] + [v["offset"] for v in config["vision"].get("player_variants", [])]
    for offset in offsets:
        if len(offset) != 2:
            raise ValueError("Player offset must contain x and y")
        for value in offset:
            number(value, "player_offset", -max(width, height), max(width, height))
    number(config["vision"]["max_matches"], "max_matches", 1, 100)
    c = config["control"]
    for name, bounds in {
        "tick_hz": (1, 30), "pulse_ms": (10, 150), "attack_range_px": (1, width),
        "same_level_tolerance_px": (1, height), "hp_threshold": (0.05, 0.95),
        "mp_threshold": (0.05, 0.95), "potion_cooldown_s": (0.3, 10),
        "max_potion_attempts": (1, 10), "stuck_seconds": (1, 30),
        "max_observation_age_ms": (50, 1000), "max_session_minutes": (1, 120),
    }.items():
        number(c[name], name, *bounds)
    j = config["jev"]
    url = urlparse(j["endpoint"])
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.query:
        raise ValueError("Jev endpoint must be an HTTPS URL without credentials/query")
    for name, bounds in {"timeout_s": (0.1, 15), "interval_s": (0.2, 30),
                         "max_decision_age_ms": (50, 2000), "min_confidence": (0, 1)}.items():
        number(j[name], name, *bounds)
    number(config["route"]["tolerance"], "route.tolerance", 0.005, 0.1)
    for point in config["route"]["waypoints"]:
        number(point["x"], "waypoint.x", 0, 1)
        number(point["y"], "waypoint.y", 0, 1)
        if point["action"] not in {"move_left", "move_right", "jump_left", "jump_right", "climb_up", "climb_down"}:
            raise ValueError("Unsupported waypoint action")
    return config


def require_calibration(config: dict) -> None:
    v = config["vision"]
    if not v["player_template"] or not v["monster_templates"] or not v["hp_roi"] or not v["mp_roi"]:
        raise ValueError("Calibration required: player, monster, HP and MP")
