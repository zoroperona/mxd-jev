import pytest

from mxd_jev.windows import WindowsIO


def fake_io():
    io = WindowsIO.__new__(WindowsIO)
    io.held = set()
    io.stopped = False
    io.interrupted = False
    io.edge = lambda key: False
    io.focused = lambda: True
    class User:
        def GetAsyncKeyState(self, key):
            return 0
    io.user32 = User()
    io.events = []
    io._send = lambda key, up: io.events.append((key, up))
    return io


def test_input_releases_every_key_after_normal_pulse():
    io = fake_io()
    assert io.pulse("attack_right", {"right": "right", "attack": "ctrl"}, .001)
    assert ("right", False) in io.events and ("ctrl", False) in io.events
    assert ("right", True) in io.events and ("ctrl", True) in io.events
    assert not io.held


def test_focus_loss_during_pulse_releases_keys():
    io = fake_io()
    states = iter([True, True, False])
    io.focused = lambda: next(states, False)
    assert not io.pulse("move_right", {"right": "right"}, .01)
    assert io.events == [("right", False), ("right", True)]
    assert not io.held


def test_send_failure_still_releases_pressed_keys():
    io = fake_io()
    def send(key, up):
        io.events.append((key, up))
        if key == "ctrl" and not up:
            raise RuntimeError("injected failure")
    io._send = send
    with pytest.raises(RuntimeError, match="injected failure"):
        io.pulse("attack_right", {"right": "right", "attack": "ctrl"}, .01)
    assert ("right", True) in io.events and ("ctrl", True) in io.events
    assert not io.held


def test_stop_hotkey_interrupts_pulse_and_releases_keys():
    io = fake_io()
    io.edge = lambda key: key == "f9"
    assert not io.pulse("move_right", {"right": "right"}, .01)
    assert io.stopped and not io.held


def test_physical_key_prevents_injected_input():
    io = fake_io()
    io.user32.GetAsyncKeyState = lambda key: 0x8000
    assert not io.pulse("move_right", {"right": "right"}, .01)
    assert io.interrupted and io.events == []
