from __future__ import annotations

from dataclasses import dataclass

from . import PowerStatus


@dataclass
class FakePowerSource:
    """Scriptable power source for tests and --simulate."""

    plugged: bool = True
    battery_percent: int | None = 50

    def status(self) -> PowerStatus:
        return PowerStatus(plugged=self.plugged, battery_percent=self.battery_percent)

    def set(self, plugged: bool, battery_percent: int | None = None) -> None:
        self.plugged = plugged
        if battery_percent is not None:
            self.battery_percent = battery_percent
