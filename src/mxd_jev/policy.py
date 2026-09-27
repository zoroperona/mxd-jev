from __future__ import annotations

import math

from .state import Decision, Observation

ACTION_KEYS = {
    "wait": (), "pause": (), "move_left": ("left",), "move_right": ("right",),
    "attack_left": ("left", "attack"), "attack_right": ("right", "attack"),
    "heal": ("hp",), "restore_mp": ("mp",),
    "jump_left": ("left", "jump"), "jump_right": ("right", "jump"),
    "climb_up": ("up",), "climb_down": ("down",),
}


class Policy:
    def __init__(self, config: dict):
        self.c = config["control"]
        self.route = config["route"]
        self.reset()

    def reset(self):
        self.last_potion = {"heal": -math.inf, "restore_mp": -math.inf}
        self.potion_attempts = {"heal": 0, "restore_mp": 0}
        self.route_index = 0
        self.anchor = None
        self.move_time = 0.0

    def candidates(self, obs: Observation) -> dict[str, str]:
        options = {"wait": "Hold position without pressing any key."}
        if not obs.valid or not obs.player:
            return options
        px, py = obs.player
        eligible = [m for m in obs.monsters if abs(m.center[1] - py) <= self.c["same_level_tolerance_px"]]
        for side, sign in (("left", -1), ("right", 1)):
            nearby = [m for m in eligible if (m.center[0] - px) * sign >= 0]
            if nearby:
                distance = min(abs(m.center[0] - px) for m in nearby)
                if distance <= self.c["attack_range_px"]:
                    options["attack_" + side] = f"Face {side} and attack visible monsters within the configured reach."
                else:
                    options["move_" + side] = f"Take a short step {side} toward visible monsters."
        if len(options) == 1 and self.route["enabled"] and self.route["waypoints"] and obs.minimap:
            points = self.route["waypoints"]
            target = points[self.route_index]
            if math.dist(obs.minimap, (target["x"], target["y"])) <= self.route["tolerance"]:
                self.route_index = (self.route_index + 1) % len(points)
                target = points[self.route_index]
            options[target["action"]] = "Follow the manually calibrated route toward the next minimap waypoint."
        return options

    def urgent(self, obs: Observation, now: float) -> Decision | None:
        if now - obs.timestamp > self.c["max_observation_age_ms"] / 1000 or now < obs.timestamp:
            return Decision("pause", "stale_observation")
        if not obs.valid:
            return Decision("pause", obs.reason)
        if self.route["enabled"] and (not self.route["waypoints"] or obs.minimap is None):
            return Decision("pause", "route_or_minimap_unavailable")
        for action, value, threshold in (("heal", obs.hp, self.c["hp_threshold"]),
                                         ("restore_mp", obs.mp, self.c["mp_threshold"])):
            if value is None:
                return Decision("pause", "unknown_health")
            if value < threshold:
                if self.potion_attempts[action] >= self.c["max_potion_attempts"]:
                    return Decision("pause", "potion_did_not_restore_bar")
                if now - self.last_potion[action] >= self.c["potion_cooldown_s"]:
                    return Decision(action, "below_configured_threshold")
                return Decision("wait", "potion_cooldown")
            self.potion_attempts[action] = 0
        if self.move_time >= self.c["stuck_seconds"]:
            return Decision("pause", "movement_not_observed")
        return None

    def decide(self, obs: Observation, now: float) -> Decision:
        urgent = self.urgent(obs, now)
        if urgent:
            return urgent
        options = self.candidates(obs)
        # Attack first; choose the side with more nearby targets when both are eligible.
        attacks = [a for a in options if a.startswith("attack_")]
        if attacks:
            px, py = obs.player
            def count(action):
                sign = -1 if action.endswith("left") else 1
                return sum(0 <= (m.center[0] - px) * sign <= self.c["attack_range_px"] and
                           abs(m.center[1] - py) <= self.c["same_level_tolerance_px"] for m in obs.monsters)
            return Decision(max(attacks, key=count), "visible_monsters_in_reach")
        movements = [a for a in options if a != "wait"]
        if movements:
            if len(movements) == 2 and all(a.startswith("move_") for a in movements):
                px, py = obs.player
                target = min((m for m in obs.monsters if abs(m.center[1] - py) <= self.c["same_level_tolerance_px"]),
                             key=lambda m: abs(m.center[0] - px))
                return Decision("move_left" if target.center[0] < px else "move_right", "nearest_visible_monster")
            return Decision(movements[0], "visible_target_or_configured_route")
        return Decision("wait", "no_visible_reachable_target")

    def executed(self, decision: Decision, obs: Observation, now: float, duration_s: float):
        if decision.action in self.last_potion:
            self.last_potion[decision.action] = now
            self.potion_attempts[decision.action] += 1
        moving = decision.action.startswith(("move_", "jump_", "climb_"))
        # Never infer movement from attack animations. Prefer world-relative minimap coordinates.
        pos = obs.minimap if obs.minimap is not None else obs.player
        kind = "minimap" if obs.minimap is not None else "screen"
        threshold = 0.008 if kind == "minimap" else 8
        if not moving:
            self.anchor = None
            self.move_time = 0
        elif pos is not None:
            if self.anchor is None or self.anchor[0] != kind or math.dist(pos, self.anchor[1]) > threshold:
                self.anchor = (kind, pos)
                self.move_time = 0
            self.move_time += duration_s


def decision_state(obs: Observation, candidates: dict[str, str], config: dict) -> dict:
    px, py = obs.player
    reach = config["control"]["attack_range_px"]
    tolerance = config["control"]["same_level_tolerance_px"]
    eligible = [m for m in obs.monsters if abs(m.center[1] - py) <= tolerance]
    return {
        "goal": "Stable single-map farming; prioritize survival and short, reversible actions.",
        "health": "normal", "mana": "normal",
        "left_targets_in_reach": sum(0 <= px - m.center[0] <= reach for m in eligible),
        "right_targets_in_reach": sum(0 <= m.center[0] - px <= reach for m in eligible),
        "allowed_actions": list(candidates),
        "route_available": config["route"]["enabled"],
        "notes": "Target reach and counts are already calculated by local code. Do not invent unseen targets.",
    }


def scene_signature(obs: Observation, options: dict[str, str], config: dict) -> tuple:
    state = decision_state(obs, options, config)
    # Reject responses if targets switch sides or the candidate action set changes.
    return (tuple(sorted(options)), min(state["left_targets_in_reach"], 3),
            min(state["right_targets_in_reach"], 3))
