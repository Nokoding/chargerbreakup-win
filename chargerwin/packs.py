"""Pack model and loading. Validation lives in validate.py."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .validate import PackError, validate_pack_dict


@dataclass(frozen=True)
class Line:
    id: str
    text: str


@dataclass(frozen=True)
class VoiceSettings:
    rate: float = 1.0
    volume: float = 1.0
    preferred_voice: str | None = None


@dataclass
class Pack:
    id: str
    name: str
    summary: str = ""
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    # intensity -> group -> lines
    intensities: dict[str, dict[str, list[Line]]] = field(default_factory=dict)

    def lines(self, intensity: str, group: str) -> list[Line]:
        """Lines for a group at an intensity; empty list if absent."""
        return self.intensities.get(intensity, {}).get(group, [])

    def line_count(self) -> int:
        return sum(len(lines) for groups in self.intensities.values() for lines in groups.values())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pack":
        """Build a Pack from validated JSON data. Raises PackError otherwise."""
        errors = validate_pack_dict(data)
        if errors:
            raise PackError(str(data.get("id", "<unknown>")), errors)
        voice_data = data.get("voice") or {}
        voice = VoiceSettings(
            rate=float(voice_data.get("rate", 1.0)),
            volume=float(voice_data.get("volume", 1.0)),
            preferred_voice=voice_data.get("preferred_voice"),
        )
        intensities = {
            intensity: {
                group: [Line(id=line["id"], text=line["text"]) for line in lines]
                for group, lines in groups.items()
            }
            for intensity, groups in data["intensities"].items()
        }
        return cls(
            id=data["id"],
            name=data["name"],
            summary=data.get("summary", ""),
            voice=voice,
            intensities=intensities,
        )


def packs_dir() -> Path:
    """The bundled packs directory: `packs/` beside the package in a checkout,
    or under the PyInstaller extraction dir when frozen."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "packs"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent / "packs"


def load_pack(path: Path) -> Pack:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise PackError(path.stem, [f"not valid JSON: {exc}"]) from exc
    return Pack.from_dict(data)


def find_pack(name_or_path: str, directory: Path | None = None) -> Pack:
    """Load a pack by file path, or by id looked up as `<directory>/<id>.json`."""
    candidate = Path(name_or_path)
    if candidate.suffix == ".json" and candidate.exists():
        return load_pack(candidate)
    directory = directory if directory is not None else packs_dir()
    path = directory / f"{name_or_path}.json"
    if not path.exists():
        available = sorted(p.stem for p in directory.glob("*.json")) if directory.exists() else []
        raise PackError(name_or_path, [f"no pack file at {path}; available: {', '.join(available) or 'none'}"])
    return load_pack(path)


def list_packs(directory: Path | None = None) -> list[Path]:
    directory = directory if directory is not None else packs_dir()
    return sorted(directory.glob("*.json"))
