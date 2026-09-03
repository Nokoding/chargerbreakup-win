from __future__ import annotations

from chargerwin.groups import INTENSITIES
from chargerwin.settings import Settings
from chargerwin.tray import TrayActions, build_menu, status_label


def spy_actions(log: list):
    return TrayActions(
        set_intensity=lambda lv: log.append(("intensity", lv)),
        toggle_mute=lambda: log.append(("mute",)),
        say_something=lambda: log.append(("say",)),
        open_state_folder=lambda: log.append(("folder",)),
        quit=lambda: log.append(("quit",)),
    )


def labels(items):
    return [i.label for i in items if not i.is_separator]


def test_status_label_covers_every_power_state():
    assert status_label(None, None) == "Status unknown"
    assert status_label(True, None) == "Plugged in"
    assert status_label(False, "40 minutes") == "Unplugged for 40 minutes"
    assert status_label(False, None) == "Unplugged"


def test_menu_has_the_expected_items():
    menu = build_menu(Settings(), spy_actions([]), plugged=True)
    assert labels(menu) == [
        "Plugged in",
        "Intensity",
        "Mute",
        "Say something",
        "Open data folder",
        "Quit chargerwin",
    ]


def test_status_item_is_not_clickable():
    """The first row is orientation, not a control."""
    status = build_menu(Settings(), spy_actions([]), plugged=True)[0]
    assert status.enabled is False and status.action is None


def test_intensity_submenu_checks_the_current_level():
    menu = build_menu(Settings(intensity="intense"), spy_actions([]))
    submenu = next(i for i in menu if i.label == "Intensity").submenu
    assert [s.label for s in submenu] == [lv.capitalize() for lv in INTENSITIES]
    assert [s.checked for s in submenu] == [False, False, True]
    assert all(s.radio for s in submenu)


def test_each_intensity_item_sets_its_own_level():
    """Late binding in the comprehension: every item must send a different
    level, not all the last one."""
    log: list = []
    menu = build_menu(Settings(), spy_actions(log))
    for item in next(i for i in menu if i.label == "Intensity").submenu:
        item.action()
    assert log == [("intensity", lv) for lv in INTENSITIES]


def test_mute_reflects_settings_and_dispatches():
    log: list = []
    assert next(i for i in build_menu(Settings(muted=True), spy_actions(log)) if i.label == "Mute").checked
    item = next(i for i in build_menu(Settings(muted=False), spy_actions(log)) if i.label == "Mute")
    assert item.checked is False
    item.action()
    assert log == [("mute",)]


def test_plain_items_are_not_checkboxes():
    """checked=None keeps pystray from rendering an empty tick box."""
    menu = build_menu(Settings(), spy_actions([]))
    for label in ("Say something", "Open data folder", "Quit chargerwin"):
        assert next(i for i in menu if i.label == label).checked is None


def test_menu_reports_absence_when_unplugged():
    menu = build_menu(Settings(), spy_actions([]), plugged=False, absence_human="2 hours")
    assert menu[0].label == "Unplugged for 2 hours"
