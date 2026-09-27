from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

import numpy as np

from .policy import ACTION_KEYS


VK = {**{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
      **{f"f{i}": 0x6F + i for i in range(1, 13)},
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
      "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "space": 0x20,
      "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
      "pageup": 0x21, "pagedown": 0x22, "tab": 0x09}
EXTENDED = {"left", "right", "up", "down", "insert", "delete", "home", "end", "pageup", "pagedown"}


class WindowsIO:
    def __init__(self, title: str):
        if sys.platform != "win32":
            raise RuntimeError("Live capture and key input require Windows 11")
        import mss
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u = self.user32
        # Configure pointer-size-sensitive functions explicitly for 64-bit Windows.
        u.GetForegroundWindow.restype = wintypes.HWND
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        try:
            u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            u.SetProcessDPIAware()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        windows = []
        @callback_type
        def callback(hwnd, _):
            size = u.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(size + 1)
            u.GetWindowTextW(hwnd, buffer, size + 1)
            if title.casefold() in buffer.value.casefold():
                windows.append((hwnd, buffer.value))
            return True
        u.EnumWindows(callback, 0)
        if len(windows) != 1:
            raise RuntimeError(f"Expected one game window matching {title!r}; found {len(windows)}. Use a more specific title.")
        self.hwnd, self.title = windows[0]
        self.sct = mss.mss()
        self.held = set()
        self.key_states = {}
        self.stopped = False
        self.interrupted = False
        self._init_input_types()

    def _init_input_types(self):
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]
        class UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _anonymous_ = ("data",)
            _fields_ = [("type", wintypes.DWORD), ("data", UNION)]
        self.INPUT, self.KEYBDINPUT = INPUT, KEYBDINPUT
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT

    def focused(self) -> bool:
        return bool(self.user32.IsWindow(self.hwnd) and not self.user32.IsIconic(self.hwnd)
                    and self.user32.GetForegroundWindow() == self.hwnd)

    def edge(self, key: str) -> bool:
        down = bool(self.user32.GetAsyncKeyState(VK[key]) & 0x8000)
        old = self.key_states.get(key, False)
        self.key_states[key] = down
        return down and not old

    def capture(self):
        if not self.focused():
            raise RuntimeError("Game window is not in the foreground")
        rect, point = wintypes.RECT(), wintypes.POINT(0, 0)
        if not self.user32.GetClientRect(self.hwnd, ctypes.byref(rect)) or not self.user32.ClientToScreen(self.hwnd, ctypes.byref(point)):
            raise RuntimeError("Cannot locate the game client area")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 320 or height < 200:
            raise RuntimeError("Game client area is too small")
        shot = self.sct.grab({"left": point.x, "top": point.y, "width": width, "height": height})
        return np.asarray(shot)[:, :, :3].copy()

    def _send(self, key: str, up: bool):
        scan = self.user32.MapVirtualKeyW(VK[key], 0)
        if scan == 0:
            raise RuntimeError(f"No scan code for key: {key}")
        flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if key in EXTENDED else 0)
        item = self.INPUT(type=1)
        item.ki = self.KEYBDINPUT(0, scan, flags, 0, 0)
        if self.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
            raise RuntimeError("Windows rejected keyboard input; check game/app privilege levels")

    def release_all(self):
        errors = []
        for key in list(self.held):
            try:
                self._send(key, True)
                self.held.discard(key)
            except RuntimeError as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("Unable to release keys: " + "; ".join(errors))

    def pulse(self, action: str, keys: dict, duration_s: float) -> bool:
        if action not in ACTION_KEYS:
            raise ValueError("Unknown action")
        if not self.focused():
            self.release_all()
            return False
        # Avoid mixing injected modifiers with keys a user is physically holding.
        if any(self.user32.GetAsyncKeyState(VK[k]) & 0x8000 for k in set(keys.values())):
            self.interrupted = True
            return False
        try:
            for name in ACTION_KEYS[action]:
                if not self.focused():
                    return False
                key = keys[name]
                self.held.add(key)
                self._send(key, False)
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline:
                if self.edge("f9"):
                    self.stopped = True
                if self.edge("f8"):
                    self.interrupted = True
                if self.stopped or self.interrupted or not self.focused():
                    return False
                time.sleep(0.005)
            return True
        finally:
            self.release_all()

    def close(self):
        try:
            self.release_all()
        finally:
            self.sct.close()
