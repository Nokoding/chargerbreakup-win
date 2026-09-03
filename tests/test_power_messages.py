"""The decisions the Windows power hook makes.

`chargerwin.power.windows` cannot be imported here (it needs
ctypes.WINFUNCTYPE), which is exactly why these live in `messages.py`.
"""

from __future__ import annotations

import pytest

from chargerwin.power import PowerStatus
from chargerwin.power.messages import (
    PBT_APMPOWERSTATUSCHANGE,
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    PBT_APMSUSPEND,
    WM_POWERBROADCAST,
    WM_TIMER,
    PowerAction,
    classify_message,
    decode_power_status,
    psutil_status,
)


@pytest.mark.parametrize(
    "ac,expected",
    [(1, True), (0, False), (255, None)],
)
def test_ac_line_status_decodes(ac, expected):
    assert decode_power_status(ac, 50).plugged is expected


def test_unknown_ac_status_is_not_guessed_at():
    """255 means Windows does not know. Treating it as unplugged would
    announce a disconnect that never happened."""
    assert decode_power_status(255, 50).plugged is None


@pytest.mark.parametrize(
    "raw,expected",
    [(0, 0), (50, 50), (100, 100), (255, None), (120, 100)],
)
def test_battery_percent_decodes_and_clamps(raw, expected):
    """255 is 'unknown'; some machines report over 100, which is clamped
    rather than passed through into a line saying 120 percent."""
    assert decode_power_status(1, raw).battery_percent == expected


def test_status_change_means_read_the_status():
    """The message carries no state, so it is a prompt to go and look."""
    assert classify_message(WM_POWERBROADCAST, PBT_APMPOWERSTATUSCHANGE) is PowerAction.READ_STATUS


@pytest.mark.parametrize("wparam", [PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND])
def test_resume_resyncs_rather_than_announcing(wparam):
    """The cable may have moved while the machine slept. Announcing a
    disconnect whose timing we cannot know is worse than adopting silently."""
    assert classify_message(WM_POWERBROADCAST, wparam) is PowerAction.RESYNC


@pytest.mark.parametrize(
    "message,wparam",
    [(WM_TIMER, 0), (0x0005, 0), (WM_POWERBROADCAST, PBT_APMSUSPEND), (WM_POWERBROADCAST, 0xFF)],
)
def test_everything_else_is_ignored(message, wparam):
    assert classify_message(message, wparam) is PowerAction.IGNORE


def test_psutil_status_on_a_machine_with_no_battery():
    """Every CI box and this Codespace. Must not raise."""
    status = psutil_status()
    assert isinstance(status, PowerStatus)


def test_psutil_status_survives_a_raising_psutil(monkeypatch):
    import chargerwin.power.messages as messages

    class Boom:
        @staticmethod
        def sensors_battery():
            raise OSError("nope")

    monkeypatch.setitem(__import__("sys").modules, "psutil", Boom)
    assert messages.psutil_status().plugged is None


def test_power_setting_change_also_reads_the_status():
    """The second delivery route. RegisterPowerSettingNotification sends
    PBT_POWERSETTINGCHANGE to one specific window, which does not depend on
    broadcast eligibility the way PBT_APMPOWERSTATUSCHANGE does."""
    from chargerwin.power.messages import PBT_POWERSETTINGCHANGE

    assert classify_message(WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE) is PowerAction.READ_STATUS


def test_the_window_is_not_message_only():
    """Regression for the step 6 failure. A message-only window (HWND_MESSAGE
    as parent) registers and pumps happily but never receives a broadcast, and
    WM_POWERBROADCAST is a broadcast, so the app sat silent through every
    cable pull. The window must be an ordinary hidden top-level one.

    Read as text, not imported: windows.py needs ctypes.WINFUNCTYPE and cannot
    be imported off Windows. A source assertion is weak, but the alternative
    here is no check at all until someone is standing at the laptop.
    """
    from pathlib import Path

    import chargerwin.power as power

    source = (Path(power.__file__).parent / "windows.py").read_text(encoding="utf-8")
    creation = source[source.index("CreateWindowExW("):]
    assert "HWND_MESSAGE" not in creation
    assert "WS_EX_TOOLWINDOW" in creation
    assert "RegisterPowerSettingNotification" in source


def test_duplicate_delivery_is_harmless_by_design():
    """Both routes can fire for one cable pull. They both mean READ_STATUS,
    and State.observe turns the second reading into no change."""
    from chargerwin.power.messages import PBT_POWERSETTINGCHANGE

    actions = {
        classify_message(WM_POWERBROADCAST, PBT_APMPOWERSTATUSCHANGE),
        classify_message(WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE),
    }
    assert actions == {PowerAction.READ_STATUS}
