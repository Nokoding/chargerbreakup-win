"""Tray icon.

`pystray` needs a display and does not install in the Linux dev
environment, so the menu is built as plain data by `build_menu` and only
converted to pystray objects inside `TrayIcon.run`. Everything worth
testing -- which items appear, what is checked, what each one does -- is
testable here without an display server or the dependency.

The icon image is drawn with Pillow rather than shipped as a file, so
PyInstaller has one less data file to bundle at step 5's packaging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .groups import INTENSITIES
from .settings import Settings

log = logging.getLogger(__name__)

APP_NAME = "chargerwin"


@dataclass
class MenuItem:
    label: str
    action: Callable[[], None] | None = None
    checked: bool | None = None      # None renders as a plain item, not a checkbox
    enabled: bool = True
    radio: bool = False
    submenu: list["MenuItem"] = field(default_factory=list)

    @property
    def is_separator(self) -> bool:
        return self.label == "-"


SEPARATOR = MenuItem(label="-", enabled=False)


@dataclass
class TrayActions:
    """What the menu can do. Supplied by the app, stubbed in tests."""

    set_intensity: Callable[[str], None]
    toggle_mute: Callable[[], None]
    say_something: Callable[[], None]
    open_state_folder: Callable[[], None]
    quit: Callable[[], None]


def status_label(plugged: bool | None, absence_human: str | None) -> str:
    """First line of the menu. Never a control, just orientation."""
    if plugged is None:
        return "Status unknown"
    if plugged:
        return "Plugged in"
    return f"Unplugged for {absence_human}" if absence_human else "Unplugged"


def build_menu(
    settings: Settings,
    actions: TrayActions,
    plugged: bool | None = None,
    absence_human: str | None = None,
) -> list[MenuItem]:
    """The whole menu, as data."""
    return [
        MenuItem(label=status_label(plugged, absence_human), enabled=False),
        SEPARATOR,
        MenuItem(
            label="Intensity",
            submenu=[
                MenuItem(
                    label=level.capitalize(),
                    checked=(level == settings.intensity),
                    radio=True,
                    action=(lambda lv=level: actions.set_intensity(lv)),
                )
                for level in INTENSITIES
            ],
        ),
        MenuItem(label="Mute", checked=settings.muted, action=actions.toggle_mute),
        SEPARATOR,
        MenuItem(label="Say something", action=actions.say_something),
        MenuItem(label="Open data folder", action=actions.open_state_folder),
        SEPARATOR,
        MenuItem(label=f"Quit {APP_NAME}", action=actions.quit),
    ]


def make_image(size: int = 64):
    """Tray icon: a plug on a dark rounded square. Drawn, not shipped."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = size // 12
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad], radius=size // 6, fill=(28, 28, 32, 255)
    )
    body_w, body_h = size // 3, size // 4
    left = (size - body_w) // 2
    top = size // 2
    draw.rounded_rectangle(
        [left, top, left + body_w, top + body_h], radius=size // 24, fill=(236, 236, 240, 255)
    )
    prong_w = max(2, size // 16)
    prong_top = top - size // 5
    for x in (left + body_w // 4 - prong_w // 2, left + 3 * body_w // 4 - prong_w // 2):
        draw.rectangle([x, prong_top, x + prong_w, top], fill=(236, 236, 240, 255))
    return image


class TrayIcon:
    """Thin pystray shell. Holds no logic worth testing."""

    def __init__(self, menu_factory: Callable[[], list[MenuItem]], title: str = APP_NAME):
        self.menu_factory = menu_factory
        self.title = title
        self._icon = None

    def _to_pystray(self, items: list[MenuItem]):
        import pystray

        converted = []
        for item in items:
            if item.is_separator:
                converted.append(pystray.Menu.SEPARATOR)
                continue
            if item.submenu:
                converted.append(
                    pystray.MenuItem(item.label, pystray.Menu(*self._to_pystray(item.submenu)))
                )
                continue
            converted.append(
                pystray.MenuItem(
                    item.label,
                    (lambda _icon, _item, fn=item.action: fn()) if item.action else None,
                    checked=(lambda _item, value=item.checked: value) if item.checked is not None else None,
                    radio=item.radio,
                    enabled=item.enabled,
                )
            )
        return converted

    def run(self) -> None:  # pragma: no cover - needs a tray and a display
        import pystray

        self._icon = pystray.Icon(
            APP_NAME,
            icon=make_image(),
            title=self.title,
            menu=pystray.Menu(lambda: self._to_pystray(self.menu_factory())),
        )
        self._icon.run()

    def stop(self) -> None:  # pragma: no cover - paired with run
        if self._icon is not None:
            self._icon.stop()

    def notify(self, message: str) -> None:  # pragma: no cover - needs a tray
        if self._icon is not None:
            try:
                self._icon.notify(message, APP_NAME)
            except Exception:
                log.debug("tray notification failed", exc_info=True)
