"""User preferences, kept separate from the counters in state.json.

Two files rather than one because they have different owners and different
failure modes. state.json is written by the app on every event and is
worthless if lost but easy to regenerate; settings.json is written only when
the user changes something and losing it means their choices vanish. A
corrupt counter file should not cost the user their voice and intensity.

Unreadable or missing settings fall back to defaults rather than raising:
the app must still start and still talk.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .groups import DEFAULT_INTENSITY, INTENSITIES

log = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"
DEFAULT_PACK = "field_notes"


@dataclass
class Settings:
    pack_id: str = DEFAULT_PACK
    intensity: str = DEFAULT_INTENSITY
    muted: bool = False
    tts_engine: str = "sapi"

    def normalized(self) -> "Settings":
        """Clamp anything unrecognised back to a default.

        Settings are user-editable JSON on disk, so an unknown intensity is a
        thing that happens; it must not crash the tray at startup.
        """
        intensity = self.intensity if self.intensity in INTENSITIES else DEFAULT_INTENSITY
        if intensity != self.intensity:
            log.warning("unknown intensity %r in settings; using %r", self.intensity, intensity)
        return Settings(
            pack_id=self.pack_id or DEFAULT_PACK,
            intensity=intensity,
            muted=bool(self.muted),
            tts_engine=self.tts_engine or "sapi",
        )


class SettingsStore:
    def __init__(self, directory: Path):
        self.path = Path(directory) / SETTINGS_FILENAME

    def load(self) -> Settings:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return Settings()
        except (json.JSONDecodeError, OSError):
            log.warning("could not read %s; using defaults", self.path, exc_info=True)
            return Settings()
        known = {f for f in Settings().__dict__}
        return Settings(**{k: v for k, v in data.items() if k in known}).normalized()

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(asdict(settings.normalized()), fh, indent=2)
        tmp.replace(self.path)
