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

HWND_MESSAGE = -3          # a message-only window: no UI, still gets messages
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
    if wparam == PBT_APMPOWERSTATUSCHANGE:
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

