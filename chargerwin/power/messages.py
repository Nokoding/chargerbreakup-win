"""Win32 power constants and the decisions made from them.

Deliberately free of ctypes. `ctypes.WINFUNCTYPE` and much of
`ctypes.wintypes` only exist on Windows, so anything importing them cannot
be imported -- let alone tested -- in the Linux dev environment. Keeping the
decisions here and the plumbing in `windows.py` means the part with
branching is testable everywhere, and the part that cannot be tested has no
branching worth testing.

Reference: WM_POWERBROADCAST carries no state. Microsoft's guidance is to
respond to PBT_APMPOWERSTATUSCHANGE by calling GetSystemPowerStatus, and
the message also fires on battery-percentage changes, so the caller must
diff against the last known AC status rather than assume a plug event.
State.observe already does exactly that.
"""

from __future__ import annotations

import logging
from enum import Enum

from . import PowerStatus

log = logging.getLogger(__name__)

# --- Win32 constants ---------------------------------------------------------

WM_POWERBROADCAST = 0x0218
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010

PBT_APMPOWERSTATUSCHANGE = 0x000A
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMSUSPEND = 0x0004
PBT_POWERSETTINGCHANGE = 0x8013

# Window creation. NOT HWND_MESSAGE: a message-only window "does not receive
# broadcast messages" (Microsoft's own wording), and WM_POWERBROADCAST is
# broadcast to top-level windows. A message-only window registers fine, pumps
# fine, and silently never receives a single power event. The window is
# therefore an ordinary top-level window that is simply never shown.
WS_OVERLAPPED = 0x00000000
WS_EX_TOOLWINDOW = 0x00000080  # keeps it out of the taskbar and alt-tab

# Targeted power notification, used alongside the broadcast. Delivery is to
# this specific window rather than to every top-level window, so it does not
# depend on broadcast eligibility at all.
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000
# GUID_ACDC_POWER_SOURCE {5D3E9A59-E9D5-4B00-A6BD-FF34FF516548}: the system is
# now running on AC, or on battery.
GUID_ACDC_POWER_SOURCE = (0x5D3E9A59, 0xE9D5, 0x4B00, (0xA6, 0xBD, 0xFF, 0x34, 0xFF, 0x51, 0x65, 0x48))
AC_OFFLINE, AC_ONLINE, AC_UNKNOWN = 0, 1, 255
BATTERY_PERCENT_UNKNOWN = 255


class PowerAction(Enum):
    """What the app should do about a message."""

    IGNORE = "ignore"
    READ_STATUS = "read_status"  # diff a fresh reading; may or may not be a plug event
    RESYNC = "resync"            # adopt silently: the change happened while asleep


# --- the decisions, testable anywhere ---------------------------------------


def decode_power_status(ac_line_status: int, battery_life_percent: int) -> PowerStatus:
    """SYSTEM_POWER_STATUS bytes -> PowerStatus.

    ACLineStatus is 0 offline, 1 online, 255 unknown. BatteryLifePercent is
    0-100 or 255 unknown; some machines also report values above 100, which
    are clamped rather than trusted.
    """
    if ac_line_status == AC_ONLINE:
        plugged: bool | None = True
    elif ac_line_status == AC_OFFLINE:
        plugged = False
    else:
        plugged = None

    percent: int | None
    if battery_life_percent == BATTERY_PERCENT_UNKNOWN or battery_life_percent < 0:
        percent = None
    else:
        percent = min(100, battery_life_percent)
    return PowerStatus(plugged=plugged, battery_percent=percent)


def classify_message(message: int, wparam: int) -> PowerAction:
    """Decide what a window message means for us.

    Resume is a RESYNC, not a READ_STATUS: the cable may have moved while the
    machine was asleep, and announcing a disconnect whose timing we cannot
    know is worse than silently adopting the new state. That is what
    State.resync is for.
    """
    if message != WM_POWERBROADCAST:
        return PowerAction.IGNORE
    if wparam in (PBT_APMPOWERSTATUSCHANGE, PBT_POWERSETTINGCHANGE):
        # Two independent delivery routes to the same conclusion: go and read
        # the status. Receiving both for one cable pull is harmless, because
        # State.observe diffs against the last known status and the second
        # reading is simply no change.
        return PowerAction.READ_STATUS
    if wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
        return PowerAction.RESYNC
    return PowerAction.IGNORE


def psutil_status() -> PowerStatus:
    """Battery reading via psutil, the fallback when GetSystemPowerStatus
    reports unknown. Returns an all-unknown status on a machine with no
    battery at all, which is every CI box and this Codespace."""
    try:
        import psutil

        battery = psutil.sensors_battery()
    except Exception:
        log.debug("psutil battery read failed", exc_info=True)
        return PowerStatus(plugged=None)
    if battery is None:
        return PowerStatus(plugged=None)
    return PowerStatus(plugged=bool(battery.power_plugged), battery_percent=int(battery.percent))

