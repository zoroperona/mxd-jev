import copy
import sys

import cv2
import numpy as np
import pytest

from mxd_jev.config import DEFAULT
from mxd_jev.state import Detection, Observation
from mxd_jev import runtime, windows


@pytest.mark.parametrize("execute,valid,expected_pulses", [(False, True, 0), (True, True, 1), (True, False, 0)])
def test_live_execution_requires_explicit_enable_and_valid_frame(tmp_path, monkeypatch, execute, valid, expected_pulses):
    config = copy.deepcopy(DEFAULT)
    config["vision"].update(player_template="fake", monster_templates=["fake"],
                             hp_roi=[0, 0, .1, .1], mp_roi=[.1, 0, .1, .1])
    instances = []
    class FakeIO:
        def __init__(self, title):
            self.stopped = False
            self.interrupted = False
            self.pulses = []
            self.closed = False
            instances.append(self)
        def edge(self, key):
            return key == "f8"
        def focused(self):
            return True
        def capture(self):
            return np.zeros((810, 1440, 3), np.uint8)
        def release_all(self):
            pass
        def pulse(self, action, keys, duration):
            self.pulses.append(action)
            return True
        def close(self):
            self.closed = True
    class FakeVision:
        def __init__(self, *args):
            pass
        def analyze(self, frame, idx, timestamp):
            return Observation(idx, timestamp, (300, 300), [Detection(320, 280, 40, 40, .9)],
                               .8, .8, (.5, .5), valid, "test"), frame
    monkeypatch.setattr(windows, "WindowsIO", FakeIO)
    monkeypatch.setattr(runtime, "Vision", FakeVision)
    monkeypatch.setattr(cv2, "imshow", lambda *args: None)
    monkeypatch.setattr(cv2, "waitKey", lambda *args: ord("q"))
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    runtime.run_live(config, tmp_path, tmp_path / "events.jsonl", execute, "rules")
    assert len(instances[0].pulses) == expected_pulses
    assert instances[0].closed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ABI check")
def test_windows_input_structure_size():
    import ctypes
    io = windows.WindowsIO.__new__(windows.WindowsIO)
    io.user32 = ctypes.WinDLL("user32", use_last_error=True)
    io._init_input_types()
    assert ctypes.sizeof(io.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
