"""Wav playback.

Playback is the last thing on the event path, so it must not block: a
speaking line should never delay the next event or freeze the tray. Every
player here is fire-and-forget.

Nothing in this module imports a Windows library at import time. `winsound`
is stdlib but Windows only, so it is imported inside the player that needs
it and `select_player` picks a no-op elsewhere. That keeps the module
importable, and the pipeline testable, in the Linux dev environment.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class Player(Protocol):
    def play(self, path: Path) -> None: ...


class NullPlayer:
    """Records what it was asked to play and makes no sound.

    The default off-Windows, and what tests assert against. Keeping the
    calls rather than dropping them means a test can check that the right
    line reached playback without any audio stack involved.
    """

    def __init__(self) -> None:
        self.played: list[Path] = []

    def play(self, path: Path) -> None:
        self.played.append(path)
        log.debug("null player: would play %s", path)


class WinsoundPlayer:
    """Plays a wav via winsound, asynchronously.

    SND_ASYNC returns immediately; a second call interrupts the first, which
    is the behaviour we want. Yanking the cable twice in three seconds should
    say the second line, not queue both.
    """

    def __init__(self) -> None:
        import winsound  # noqa: F401  (Windows only; fail loudly here, not at play time)

        self._winsound = winsound

    def play(self, path: Path) -> None:
        if not path.exists():
            log.warning("no audio at %s; staying silent", path)
            return
        flags = self._winsound.SND_FILENAME | self._winsound.SND_ASYNC
        try:
            self._winsound.PlaySound(str(path), flags)
        except RuntimeError:
            # A missing device or a wav winsound cannot decode. Never let
            # playback take the app down over a sound effect.
            log.warning("could not play %s", path, exc_info=True)


def select_player(platform: str | None = None) -> Player:
    """WinsoundPlayer on Windows, NullPlayer everywhere else."""
    if (platform or sys.platform) == "win32":
        try:
            return WinsoundPlayer()
        except Exception:  # pragma: no cover - only reachable on a broken Windows
            log.warning("winsound unavailable; running silent", exc_info=True)
    return NullPlayer()
