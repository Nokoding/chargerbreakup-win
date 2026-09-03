"""Pre-rendered speech: the disk cache and the engines that fill it.

The event path never synthesizes. It looks a wav up by line id and plays it,
or stays silent. Rendering happens ahead of time, from `warm()`, which is
safe to call from a background thread at startup but never from an event.

Cache layout:

    <cache_dir>/<pack_id>/<engine_key>/<line_id>.wav

The engine key is in the path on purpose. Line ids are stable, so a cache
keyed on id alone would keep serving today's SAPI audio after a switch to a
better engine; the whole point of `sapi` being the placeholder is that it
gets replaced. Separate directories mean switching engines is a cache miss,
not stale audio, and switching back does not re-render.

Line ids are used as filenames, so they are validated rather than trusted:
a pack is data, and `../../` in an id must not write outside the cache.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Protocol

from .groups import INTENSITIES
from .packs import Pack

log = logging.getLogger(__name__)

# Line ids appear in filesystem paths. Pack authors get a clear rule instead
# of a sanitizer that quietly collapses two ids onto one file.
SAFE_LINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UnsafeLineId(ValueError):
    pass


class Renderer(Protocol):
    key: str

    def render(self, text: str, out_path: Path) -> None: ...


class FakeRenderer:
    """Writes a tiny valid wav. For tests and for --warm on Linux."""

    key = "fake"

    def __init__(self) -> None:
        self.rendered: list[tuple[str, Path]] = []

    def render(self, text: str, out_path: Path) -> None:
        import struct
        import wave

        self.rendered.append((text, out_path))
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(struct.pack("<h", 0) * 8000)


class Pyttsx3Renderer:
    """Windows SAPI via pyttsx3, rendered to wav ahead of time.

    The placeholder voice. It sounds like 2009 and it is offline, free and
    already a dependency, which is exactly what a placeholder should be.
    Replacing it means writing another Renderer with a different `key`.

    pyttsx3 is imported lazily and a fresh engine is built per batch:
    re-using one across many runAndWait() calls is a well-known way to get a
    hung engine, and a batch render is not hot enough for that to matter.
    """

    key = "sapi"

    def __init__(self, rate: float = 1.0, volume: float = 1.0, voice_id: str | None = None):
        self.rate = rate
        self.volume = volume
        self.voice_id = voice_id

    def _engine(self):
        import pyttsx3

        engine = pyttsx3.init()
        # pyttsx3 rate is words per minute, packs express a multiplier.
        engine.setProperty("rate", int(engine.getProperty("rate") * self.rate))
        engine.setProperty("volume", max(0.0, min(1.0, self.volume)))
        if self.voice_id:
            engine.setProperty("voice", self.voice_id)
        return engine

    def render(self, text: str, out_path: Path) -> None:
        engine = self._engine()
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        engine.stop()


def renderer_for(pack: Pack, engine: str = "sapi") -> Renderer:
    """Build the named renderer, configured from the pack's voice block."""
    if engine == "fake":
        return FakeRenderer()
    if engine == "sapi":
        voice = pack.voice
        return Pyttsx3Renderer(
            rate=voice.rate,
            volume=voice.volume,
            voice_id=voice.preferred_voice,
        )
    raise ValueError(f"unknown tts engine {engine!r}")


class VoiceCache:
    """Maps line ids to wav paths and renders the ones that are missing."""

    def __init__(self, directory: Path, pack_id: str, renderer: Renderer):
        self.directory = Path(directory)
        self.pack_id = pack_id
        self.renderer = renderer

    @property
    def root(self) -> Path:
        return self.directory / self.pack_id / self.renderer.key

    def path_for(self, line_id: str) -> Path:
        if not SAFE_LINE_ID.match(line_id):
            raise UnsafeLineId(
                f"line id {line_id!r} is not usable as a filename; ids must match "
                "[A-Za-z0-9][A-Za-z0-9._-]* (leading dots would make hidden files)"
            )
        return self.root / f"{line_id}.wav"

    def lookup(self, line_id: str) -> Path | None:
        """Cached wav for a line, or None. Never renders: this is the event path."""
        try:
            path = self.path_for(line_id)
        except UnsafeLineId:
            log.warning("refusing to look up unsafe line id %r", line_id)
            return None
        if path.exists():
            return path
        log.warning("no cached audio for line %r at %s", line_id, path)
        return None

    def warm(self, pack: Pack, intensities: Iterable[str] | None = None, force: bool = False) -> int:
        """Render every missing line. Returns how many were rendered.

        Off the event path by construction: call it from startup or a CLI
        command, never from a plug event.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        rendered = 0
        for intensity in intensities or INTENSITIES:
            for group in pack.intensities.get(intensity, {}):
                for line in pack.lines(intensity, group):
                    try:
                        path = self.path_for(line.id)
                    except UnsafeLineId:
                        log.warning("skipping line %r: unusable id", line.id)
                        continue
                    if path.exists() and not force:
                        continue
                    try:
                        self.renderer.render(line.text, path)
                    except ImportError:
                        # The engine itself is missing. That is not a bad line,
                        # it is a broken setup, and swallowing it would report a
                        # successful render of nothing.
                        raise
                    except Exception:
                        log.warning("failed to render line %r", line.id, exc_info=True)
                        continue
                    rendered += 1
        return rendered
