"""Power source abstraction.

The app never asks "did a plug event happen"; it asks "what is the AC status
right now" and lets State.observe() diff it against the last known status.
That is what WM_POWERBROADCAST requires (the message carries no state) and
it makes the fake trivially equivalent to the real thing.

Only the fake exists for now. The Windows implementation (message-only
window + GetSystemPowerStatus via ctypes, psutil for battery percent) is
build step 6 and must stay thin: it should only call `status()` and hand
the result to the same code path the fake uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PowerStatus:
    plugged: bool
    battery_percent: int | None = None


class PowerSource(Protocol):
    def status(self) -> PowerStatus: ...


from .fake import FakePowerSource  # noqa: E402  (re-export)

__all__ = ["PowerStatus", "PowerSource", "FakePowerSource"]
