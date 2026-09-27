from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .state import Detection, Observation


def crop(frame, roi):
    h, w = frame.shape[:2]
    x, y, rw, rh = roi
    x0, y0 = int(x * w), int(y * h)
    return frame[y0:max(y0 + 1, int((y + rh) * h)), x0:max(x0 + 1, int((x + rw) * w))], x0, y0


def bar_ratio(image, kind: str) -> float | None:
    """Estimate the colored fill in a tightly calibrated bar interior."""
    if image.size == 0:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    hue = ((h < 12) | (h > 170)) if kind == "hp" else ((h >= 90) & (h <= 130))
    columns = ((hue & (s > 100) & (v > 90)).mean(axis=0) >= 0.25)
    indices = np.flatnonzero(columns)
    # A completely invisible fill is ambiguous (empty bar vs wrong ROI); stop.
    if len(indices) == 0:
        return None
    # The fill must start at the left edge, allowing a small calibration margin.
    if indices[0] > max(3, image.shape[1] * 0.06):
        return None
    end = int(indices[-1]) + 1
    if columns[:end].mean() < 0.65:
        return None
    return min(1.0, end / image.shape[1])


def matches(gray, template, threshold: float, limit: int) -> list[Detection]:
    h, w = template.shape[:2]
    if h > gray.shape[0] or w > gray.shape[1] or template.std() < 2:
        return []
    scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    scores = np.nan_to_num(scores, nan=-1, posinf=-1, neginf=-1)
    found = []
    for _ in range(int(limit)):
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < threshold:
            break
        found.append(Detection(x, y, w, h, float(score)))
        scores[max(0, y - h // 2):y + h // 2 + 1, max(0, x - w // 2):x + w // 2 + 1] = -1
    return found


class Vision:
    def __init__(self, config: dict, config_dir: Path):
        self.config = config
        self.v = config["vision"]
        self.player = self._read(config_dir, self.v["player_template"])
        self.player_variants = [(self.player, self.v["player_offset"])] if self.player is not None else []
        self.player_variants += [(self._read(config_dir, p["path"]), p["offset"])
                                 for p in self.v.get("player_variants", [])]
        self.monsters = [self._read(config_dir, p) for p in self.v["monster_templates"]]

    @staticmethod
    def _read(root, name):
        if not name:
            return None
        path = root / name
        if not path.is_file():
            raise ValueError(f"Missing template: {path}")
        data = np.fromfile(str(path), dtype=np.uint8)
        result = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if result is None or result.size == 0 or result.std() < 2:
            raise ValueError(f"Invalid/blank template: {path}")
        return result

    def analyze(self, frame, frame_id: int, timestamp: float):
        frame = cv2.resize(frame, tuple(self.config["reference_size"]))
        obs = Observation(frame_id, timestamp)
        if np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) > 35) < 0.05:
            obs.reason = "black_frame_or_loading"
            return obs, frame
        region, ox, oy = crop(frame, self.v["play_roi"])
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        player_hits = []
        for template, (dx, dy) in self.player_variants:
            for d in matches(gray, template, self.v["player_threshold"], 2):
                cx, cy = d.center
                player_hits.append((d.confidence, (cx + ox, cy + oy), (cx + ox + dx, cy + oy + dy)))
        unique = []
        for score, anchor, point in sorted(player_hits, reverse=True):
            # Merge detections of the same nameplate, not their pose-dependent body offsets.
            if not any(np.hypot(anchor[0]-p[0], anchor[1]-p[1]) < 25 for _, p, _ in unique):
                unique.append((score, anchor, point))
        if len(unique) == 1 or (len(unique) > 1 and unique[0][0] - unique[1][0] > 0.08):
            obs.player = unique[0][2]
        candidates = []
        for template in self.monsters:
            candidates.extend(matches(gray, template, self.v["match_threshold"], self.v["max_matches"]))
        for d in sorted(candidates, key=lambda d: d.confidence, reverse=True):
            d.x += ox
            d.y += oy
            if not any(abs(d.center[0] - p.center[0]) < min(d.w, p.w) * 0.5 and
                       abs(d.center[1] - p.center[1]) < min(d.h, p.h) * 0.5 for p in obs.monsters):
                obs.monsters.append(d)
        for kind in ("hp", "mp"):
            if self.v[kind + "_roi"]:
                bar, _, _ = crop(frame, self.v[kind + "_roi"])
                setattr(obs, kind, bar_ratio(bar, kind))
        if self.v["minimap_roi"]:
            mini, _, _ = crop(frame, self.v["minimap_roi"])
            low, high = self.v["minimap_yellow_hsv"]
            mask = cv2.inRange(cv2.cvtColor(mini, cv2.COLOR_BGR2HSV), np.array(low), np.array(high))
            count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
            dots = [centers[i] for i in range(1, count) if 2 <= stats[i, cv2.CC_STAT_AREA] <= 100]
            if len(dots) == 1:
                x, y = dots[0]
                obs.minimap = float(x / mini.shape[1]), float(y / mini.shape[0])
        obs.valid = obs.player is not None and obs.hp is not None and obs.mp is not None
        obs.reason = "ok" if obs.valid else "player_or_bars_unrecognized"
        return obs, frame


def overlay(frame, obs: Observation, status: str):
    out = frame.copy()
    for d in obs.monsters:
        cv2.rectangle(out, (int(d.x), int(d.y)), (int(d.x + d.w), int(d.y + d.h)), (0, 220, 255), 2)
    if obs.player:
        cv2.circle(out, tuple(map(int, obs.player)), 12, (0, 255, 0), 2)
    lines = [status, f"frame={obs.frame_id} HP={obs.hp} MP={obs.mp}",
             f"monsters={len(obs.monsters)} mini={obs.minimap} valid={obs.valid} {obs.reason}"]
    cv2.rectangle(out, (0, 0), (out.shape[1], 76), (15, 15, 15), -1)
    for i, line in enumerate(lines):
        cv2.putText(out, line[:160], (8, 20 + 23 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)
    return out
