from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .state import Decision


class GatewayError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Authorization to a redirected host.
        return None


def probability(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1


def parse_answer(body: dict, options: dict[str, str]) -> Decision:
    try:
        answer = body["answers"]["action"]
        choice, confidence, probs = answer["choice"], answer["confidence"], answer["probabilities"]
        if answer["type"] != "choice" or choice not in options or not probability(confidence):
            raise ValueError()
        if not isinstance(probs, dict) or set(probs) != set(options) or not all(probability(v) for v in probs.values()):
            raise ValueError()
        if abs(sum(probs.values()) - 1) > 0.02 or probs[choice] < max(probs.values()) - 1e-6:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GatewayError("Invalid native Jev choice response; probabilities are required") from None
    return Decision(choice, "jev_choice", "jev", float(confidence), probs)


class JevClient:
    def __init__(self, config: dict):
        self.config = config
        self.key = os.environ.get(config["api_key_env"], "")
        if not self.key:
            raise GatewayError(f"Set {config['api_key_env']} in this terminal; global Codex config is not used")
        self.opener = urllib.request.build_opener(NoRedirect())

    def ask(self, state: dict, options: dict[str, str]) -> tuple[Decision, dict]:
        payload = {"model": self.config["model"], "state": state, "questions": {"action": {
            "type": "choice",
            "instructions": "Select the next short action from the allowed options. Prioritize survival, then attack nearby targets. If evidence is insufficient, choose wait.",
            "criteria": options,
        }}}
        req = urllib.request.Request(self.config["endpoint"], data=json.dumps(payload).encode(), headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
        }, method="POST")
        start = time.monotonic()
        try:
            with self.opener.open(req, timeout=self.config["timeout_s"]) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise GatewayError("Oversized gateway response")
                body = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise GatewayError(f"HTTP {exc.code}: verify gateway path, permission and upstream setup") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GatewayError("Gateway connection failed or timed out") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GatewayError("Gateway returned non-JSON data") from None
        decision = parse_answer(body, options)
        return decision, {"latency_ms": round((time.monotonic() - start) * 1000, 1),
                          "model": body.get("model"), "usage": body.get("usage", {})}


class AsyncJev:
    """One in-flight request at a time; consume once, never replay a decision."""
    def __init__(self, client: JevClient):
        self.client = client
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.started = 0.0
        self.last_started = -math.inf
        self.signature = None

    def submit(self, state: dict, options: dict, signature: tuple, now: float, observed_at: float):
        if self.future is not None or now - self.last_started < self.client.config["interval_s"]:
            return
        self.started = observed_at
        self.last_started = now
        self.signature = signature
        self.future = self.pool.submit(self.client.ask, state, options)

    def poll(self, signature: tuple, now: float):
        if self.future is None or not self.future.done():
            return None, None
        future, self.future = self.future, None
        try:
            decision, meta = future.result()
        except GatewayError as exc:
            return Decision("pause", str(exc), "jev"), {"error": str(exc)}
        if (now - self.started) * 1000 > self.client.config["max_decision_age_ms"]:
            return Decision("wait", "expired_jev_response", "jev"), meta
        if signature != self.signature:
            return Decision("wait", "scene_changed", "jev"), meta
        if decision.confidence < self.client.config["min_confidence"]:
            return Decision("wait", "low_jev_confidence", "jev", decision.confidence, decision.probabilities), meta
        return decision, meta

    def discard(self):
        # Keep the worker slot occupied until completion, but make its result unusable.
        self.signature = None

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
