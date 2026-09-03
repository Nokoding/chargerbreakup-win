"""Wiring: state + pack + cache + player + tray.

`Speaker` is the whole event path after a line has been chosen: look the
wav up by line id, play it, done. It never renders and never blocks, so a
cache miss is silence plus a warning rather than a stall while SAPI warms
up. That is the pre-rendered-audio decision made concrete.

`App` owns the objects and the menu actions. It deliberately does not own a
power source: step 6 supplies the real one and calls `on_power_status`,
which is the same entry point `--simulate` uses.
"""

from __future__ import annotations

import logging
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .audio import Player, select_player
from .packs import Pack, find_pack
from .pipeline import Reaction, react
from .settings import Settings, SettingsStore
from .state import State, StateStore, default_state_dir
from .tray import TrayActions, TrayIcon, build_menu
from .variables import humanize_seconds
from .voice import VoiceCache, renderer_for

log = logging.getLogger(__name__)


class Speaker:
    """Plays the wav for a reaction. The end of the event path."""

    def __init__(self, cache: VoiceCache, player: Player, muted: bool = False):
        self.cache = cache
        self.player = player
        self.muted = muted

    def speak(self, reaction: Reaction | None) -> Path | None:
        if reaction is None:
            return None
        if self.muted:
            log.debug("muted; not playing %s", reaction.selection.line.id)
            return None
        path = self.cache.lookup(reaction.selection.line.id)
        if path is None:
            return None
        self.player.play(path)
        return path


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


class App:
    def __init__(
        self,
        state_dir: Path | None = None,
        cache_dir: Path | None = None,
        pack: Pack | None = None,
        player: Player | None = None,
        rng: random.Random | None = None,
    ):
        self.state_dir = Path(state_dir) if state_dir else default_state_dir()
        self.settings_store = SettingsStore(self.state_dir)
        self.settings: Settings = self.settings_store.load()
        self.state_store = StateStore(self.state_dir)
        self.state: State = self.state_store.load()
        self.pack = pack or find_pack(self.settings.pack_id)
        self.cache_dir = Path(cache_dir) if cache_dir else self.state_dir / "audio-cache"
        self.rng = rng or random.Random()
        self.speaker = Speaker(
            cache=VoiceCache(
                self.cache_dir, self.pack.id, renderer_for(self.pack, self.settings.tts_engine)
            ),
            player=player or select_player(),
            muted=self.settings.muted,
        )
        self.tray = TrayIcon(self.menu)

    # ----- event path ----------------------------------------------------

    def resync(self, plugged: bool) -> None:
        """Adopt the real AC status at startup without speaking or counting.

        `observe` would swallow the first reading anyway, but step 6 should
        not have to rely on that: the intent at startup is explicitly to
        adopt, not to diff.
        """
        self.state.resync(plugged, now_local())
        self.state_store.save(self.state)

    def on_power_status(self, plugged: bool, battery_percent: int | None = None) -> Reaction | None:
        """A fresh AC reading. The only entry point step 6 needs."""
        now = now_local()
        event = self.state.observe(plugged, now)
        return self._react_and_save(event, now, battery_percent)

    def on_tick(self, battery_percent: int | None = None) -> Reaction | None:
        """Called by a timer while unplugged, for escalations."""
        now = now_local()
        event = self.state.due_escalation(now)
        return self._react_and_save(event, now, battery_percent)

    def _react_and_save(self, event, now: datetime, battery_percent: int | None) -> Reaction | None:
        if event is None:
            return None
        reaction = react(event, self.state, self.pack, self.settings.intensity, now, self.rng, battery_percent)
        self.state_store.save(self.state)
        self.speaker.speak(reaction)
        return reaction

    # ----- menu ----------------------------------------------------------

    def menu(self):
        absence = None
        if self.state.connected is False and self.state.disconnected_at is not None:
            absence = humanize_seconds(self.state.absence_seconds(now_local()))
        return build_menu(
            self.settings,
            TrayActions(
                set_intensity=self.set_intensity,
                toggle_mute=self.toggle_mute,
                say_something=self.say_something,
                open_state_folder=self.open_state_folder,
                quit=self.quit,
            ),
            plugged=self.state.connected,
            absence_human=absence,
        )

    def set_intensity(self, intensity: str) -> None:
        self.settings.intensity = intensity
        self.settings_store.save(self.settings)

    def toggle_mute(self) -> None:
        self.settings.muted = not self.settings.muted
        self.speaker.muted = self.settings.muted
        self.settings_store.save(self.settings)

    def say_something(self) -> Reaction | None:
        """Menu item: play a line on demand without faking a power event.

        Uses the current state so the line fits the situation, but never
        mutates counters -- asking for a demo is not a disconnect.
        """
        from .events import Disconnected, Reconnected

        now = now_local()
        event = Reconnected(absence_seconds=0.0) if self.state.connected else Disconnected()
        reaction = react(event, self.state, self.pack, self.settings.intensity, now, self.rng)
        self.speaker.speak(reaction)
        return reaction

    def open_state_folder(self) -> None:  # pragma: no cover - shells out
        path = str(self.state_dir)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            log.warning("could not open %s", path, exc_info=True)

    def quit(self) -> None:
        self.state_store.save(self.state)
        self.tray.stop()

    # ----- startup -------------------------------------------------------

    def warm_cache(self, force: bool = False) -> int:
        """Render missing audio. Off the event path; call before or beside the tray."""
        return self.speaker.cache.warm(self.pack, [self.settings.intensity], force=force)
