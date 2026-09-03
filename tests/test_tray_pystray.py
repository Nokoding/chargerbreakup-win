"""Conversion from our menu data to pystray objects.

pystray does not import in the Linux dev environment (it picks a backend at
import time and needs a display), so `_to_pystray` reached real pystray for
the first time on Windows and crashed. These tests stand in for it with a
stub that mirrors the one rule that broke: the callback-arity check in
`pystray._base.MenuItem._assert_action`.

The stub is copied from that method rather than invented:

    argcount = action.__code__.co_argcount - (1 if ismethod(action) else 0)
    0 -> wrapped, 1 -> wrapped, 2 -> used as is, more -> ValueError(action)

`co_argcount` counts parameters that have defaults, which is why binding a
loop variable with `fn=item.action` fails: it reads as a third parameter.
"""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from chargerwin.settings import Settings
from chargerwin.tray import TrayIcon, build_menu
from test_tray import spy_actions


class StubMenuItem:
    SEPARATOR = object()

    def __init__(self, text, action=None, checked=None, radio=False, enabled=True):
        self.text = text
        self.action = self._assert_action(action)
        self.checked = checked
        self.radio = radio
        self.enabled = enabled
        self.submenu = action if isinstance(action, StubMenu) else None

    @staticmethod
    def _assert_action(action):
        if action is None or isinstance(action, StubMenu):
            return action
        if not hasattr(action, "__code__"):
            return action
        argcount = action.__code__.co_argcount - (1 if inspect.ismethod(action) else 0)
        if argcount > 2:
            raise ValueError(action)
        return action


class StubMenu:
    SEPARATOR = StubMenuItem.SEPARATOR

    def __init__(self, *items):
        self.items = items


@pytest.fixture
def stub_pystray(monkeypatch):
    module = types.ModuleType("pystray")
    module.Menu = StubMenu
    module.MenuItem = StubMenuItem
    monkeypatch.setitem(sys.modules, "pystray", module)
    return module


@pytest.fixture
def converted(stub_pystray):
    icon = TrayIcon(lambda: [])
    return icon._to_pystray(build_menu(Settings(), spy_actions([]), plugged=True))


def test_conversion_survives_pystrays_arity_check(converted):
    """The regression. Every callback handed to pystray must declare at most
    two parameters, defaults included."""
    assert converted  # would have raised ValueError before the fix


def test_every_action_takes_exactly_two_parameters(converted):
    for item in converted:
        if isinstance(item, StubMenuItem) and callable(item.action):
            assert item.action.__code__.co_argcount == 2


def test_submenu_actions_are_checked_too(converted):
    """The crash was inside a submenu, which is where the loop variable is."""
    intensity = next(i for i in converted if getattr(i, "text", None) == "Intensity")
    for item in intensity.submenu.items:
        assert item.action.__code__.co_argcount == 2


def test_checked_callback_matches_how_pystray_calls_it(converted):
    """pystray evaluates `checked` as `self._checked(self)`: one argument."""
    for item in converted:
        if isinstance(item, StubMenuItem) and callable(item.checked):
            assert item.checked.__code__.co_argcount == 1
            item.checked(item)  # must not raise


def test_actions_still_dispatch_after_conversion(stub_pystray):
    log: list = []
    icon = TrayIcon(lambda: [])
    converted = icon._to_pystray(build_menu(Settings(), spy_actions(log), plugged=True))
    mute = next(i for i in converted if getattr(i, "text", None) == "Mute")
    mute.action(object(), mute)
    assert log == [("mute",)]


def test_each_submenu_item_keeps_its_own_binding(stub_pystray):
    """Closure binding must not collapse every item onto the last level."""
    from chargerwin.groups import INTENSITIES

    log: list = []
    icon = TrayIcon(lambda: [])
    converted = icon._to_pystray(build_menu(Settings(), spy_actions(log), plugged=True))
    intensity = next(i for i in converted if getattr(i, "text", None) == "Intensity")
    for item in intensity.submenu.items:
        item.action(object(), item)
    assert log == [("intensity", lv) for lv in INTENSITIES]


def test_separators_convert_to_pystray_separators(converted):
    assert StubMenu.SEPARATOR in converted


def test_disabled_status_item_has_no_action(converted):
    assert converted[0].action is None and converted[0].enabled is False
