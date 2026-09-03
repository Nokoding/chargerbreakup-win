"""Power source abstraction.

The app never asks "did a plug event happen"; it asks "what is the AC status
right now" and lets State.observe() diff it against the last known status.
That is what WM_POWERBROADCAST requires (the message carries no state) and
it makes the fake trivially equivalent to the real thing.

`windows.py` holds the real implementation: a message-only window listening
for WM_POWERBROADCAST, and GetSystemPowerStatus via ctypes for the state the
message does not carry. It is imported lazily, because it cannot even be
imported off Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PowerStatus:
    """A reading of the AC line.

    `plugged` is None when Windows reports ACLineStatus 255, "unknown". That
    is a real answer from the API, not an error, and it must not be guessed
    at: treating unknown as unplugged would announce a disconnect that never
    happened. Callers skip the reading instead.
    """

    plugged: bool | None
    battery_percent: int | None = None


class PowerSource(Protocol):
    def status(self) -> PowerStatus: ...


from .fake import FakePowerSource  # noqa: E402  (re-export)

__all__ = ["PowerStatus", "PowerSource", "FakePowerSource"]
