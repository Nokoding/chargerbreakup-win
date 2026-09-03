"""Windows power detection: a message-only window and GetSystemPowerStatus.

Windows only. Importing this module off Windows fails, by design: it needs
`ctypes.WINFUNCTYPE`. The decisions it makes live in `messages.py`, which
imports anywhere and carries the tests.

The message-only window is created on its own thread with its own message
loop, because pystray owns the main thread and window messages are
delivered per thread.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable

from . import PowerStatus
from .messages import (
    HWND_MESSAGE,
    WM_CLOSE,
    WM_DESTROY,
    PowerAction,
    classify_message,
    decode_power_status,
    psutil_status,
)

log = logging.getLogger(__name__)

# --- ctypes plumbing --------------------------------------------------------


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class WindowsPowerSource:
    """Reads the AC line via GetSystemPowerStatus.

    The percent comes from the same struct as the AC status rather than from
    a separate psutil call: one syscall, and the two values cannot disagree
    because they were read together. psutil is the fallback for when the
    struct reports unknown.
    """

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
        self._kernel32.GetSystemPowerStatus.restype = wintypes.BOOL

    def status(self) -> PowerStatus:
        raw = SYSTEM_POWER_STATUS()
        if not self._kernel32.GetSystemPowerStatus(ctypes.byref(raw)):
            err = ctypes.get_last_error()
            log.warning("GetSystemPowerStatus failed (error %s); falling back to psutil", err)
            return psutil_status()
        status = decode_power_status(
            int(raw.ACLineStatus) & 0xFF, int(raw.BatteryLifePercent) & 0xFF
        )
        if status.battery_percent is None:
            fallback = psutil_status()
            return PowerStatus(plugged=status.plugged, battery_percent=fallback.battery_percent)
        return status


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _declare(user32, kernel32) -> None:
    """Set argtypes and restypes on every Win32 function used here.

    Not optional on 64-bit. An unprototyped ctypes function defaults to
    `restype = c_int`, which is 32 bits, so CreateWindowExW and
    GetModuleHandleW would silently truncate the pointers they return. That
    is the classic ctypes-on-x64 bug and it cannot be caught by testing on
    Linux, so the prototypes are declared explicitly rather than left to
    default.
    """
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class PowerWatcher:
    """Message-only window that reports power changes to a callback.

    Runs its own thread with its own message loop, because pystray owns the
    main thread. Window messages are delivered per thread, so the loop must
    live wherever the window was created.

    `on_action` receives a PowerAction. It is called on the watcher thread,
    so whatever it touches must be safe to touch from there.
    """

    CLASS_NAME = "chargerwin_power_listener"

    def __init__(self, on_action: Callable[[PowerAction], None]):
        self.on_action = on_action
        self._thread: threading.Thread | None = None
        self._hwnd: int | None = None
        self._ready = threading.Event()
        # The WNDPROC must outlive the window. If this reference is dropped,
        # ctypes frees the trampoline and Windows calls into freed memory the
        # next time a message arrives.
        self._wndproc: WNDPROC | None = None
        self._user32 = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="chargerwin-power", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            log.warning("power watcher did not start within 10s")

    def stop(self) -> None:
        """Ask the message loop to quit. Safe to call from another thread:
        PostMessageW is the documented way to reach a loop you do not own."""
        if self._hwnd and self._user32 is not None:
            self._user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    def _handle(self, hwnd, message, wparam, lparam, user32):
        action = classify_message(message, wparam)
        if action is not PowerAction.IGNORE:
            try:
                self.on_action(action)
            except Exception:
                # A failure in the app must not kill the message loop; the
                # next plug event should still be heard.
                log.warning("power callback failed", exc_info=True)
            return 1  # TRUE: we handled the broadcast
        if message in (WM_CLOSE, WM_DESTROY):
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _run(self) -> None:  # pragma: no cover - needs Windows
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _declare(user32, kernel32)
        self._user32 = user32

        self._wndproc = WNDPROC(
            lambda hwnd, msg, wparam, lparam: self._handle(hwnd, msg, wparam, lparam, user32)
        )
        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc = self._wndproc
        wndclass.hInstance = kernel32.GetModuleHandleW(None)
        wndclass.lpszClassName = self.CLASS_NAME

        if not user32.RegisterClassW(ctypes.byref(wndclass)):
            err = ctypes.get_last_error()
            # 1410 is ERROR_CLASS_ALREADY_EXISTS, which is fine on a restart
            # within the same process.
            if err != 1410:
                log.error("RegisterClassW failed (error %s); no power events", err)
                self._ready.set()
                return

        self._hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, self.CLASS_NAME, 0, 0, 0, 0, 0,
            wintypes.HWND(HWND_MESSAGE), None, wndclass.hInstance, None,
        )
        if not self._hwnd:
            log.error("CreateWindowExW failed (error %s); no power events", ctypes.get_last_error())
            self._ready.set()
            return

        log.debug("power watcher listening on hwnd %s", self._hwnd)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        log.debug("power watcher stopped")
