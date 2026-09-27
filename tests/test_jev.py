from concurrent.futures import Future
import copy

import pytest

from mxd_jev.config import DEFAULT
from mxd_jev.jev import AsyncJev, GatewayError, JevClient, parse_answer
from mxd_jev.state import Decision


OPTIONS = {"wait": "Wait", "attack_right": "Attack"}


def body(**kwargs):
    answer = {"type": "choice", "choice": "wait", "confidence": .8,
              "probabilities": {"wait": .9, "attack_right": .1}}
    answer.update(kwargs)
    return {"answers": {"action": answer}}


@pytest.mark.parametrize("value", [
    body(choice="invented"), body(confidence=float("nan")), body(confidence=True),
    body(probabilities={"wait": .9}), body(probabilities={"wait": .4, "attack_right": .1}),
    body(choice="attack_right"), {"choices": [{"message": {"content": "wait"}}]},
])
def test_rejects_malformed_or_non_native_response(value):
    with pytest.raises(GatewayError):
        parse_answer(value, OPTIONS)


def test_preserves_native_probabilities():
    d = parse_answer(body(), OPTIONS)
    assert d.action == "wait" and d.probabilities["wait"] == .9


def test_does_not_read_global_openai_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    monkeypatch.delenv("MXD_JEV_API_KEY", raising=False)
    with pytest.raises(GatewayError, match="MXD_JEV_API_KEY"):
        JevClient(DEFAULT["jev"])


@pytest.mark.parametrize("now,signature,confidence,reason", [
    (11, ("a",), .9, "expired_jev_response"),
    (10.1, ("b",), .9, "scene_changed"),
    (10.1, ("a",), .2, "low_jev_confidence"),
    (10.1, ("a",), .9, "jev_choice"),
])
def test_async_freshness_and_confidence_gate(now, signature, confidence, reason):
    class Client:
        config = copy.deepcopy(DEFAULT["jev"])
    worker = AsyncJev(Client())
    try:
        worker.started, worker.signature = 10, ("a",)
        worker.future = Future()
        worker.future.set_result((Decision("attack_right", "jev_choice", "jev", confidence), {}))
        result, _ = worker.poll(signature, now)
        assert result.reason == reason
        assert worker.poll(signature, now) == (None, None)
    finally:
        worker.close()
