"""Pack validation. Collects every problem instead of stopping at the first,
so an author fixes a pack in one pass.

Hard failures (any one makes the pack unloadable):
- missing or malformed top-level fields, unknown intensities, unknown groups
- a required group missing or under-populated at any intensity
- any present group with fewer than MIN_LINES_PER_GROUP lines
- duplicate line ids, duplicate line text
- unknown variables or malformed braces
- rendered length over MAX_LINE_CHARS using worst-case variable widths
"""

from __future__ import annotations

from typing import Any

from .groups import ALL_GROUPS, INTENSITIES, MAX_LINE_CHARS, MIN_LINES_PER_GROUP, REQUIRED_GROUPS
from .variables import WORST_CASE, brace_errors, render


class PackError(ValueError):
    def __init__(self, pack_id: str, errors: list[str]):
        self.pack_id = pack_id
        self.errors = list(errors)
        joined = "\n".join(f"  - {e}" for e in self.errors)
        super().__init__(f"pack {pack_id!r} is invalid ({len(self.errors)} problem(s)):\n{joined}")


def validate_pack_dict(data: Any) -> list[str]:
    """Return a list of human-readable problems. Empty means valid."""
    if not isinstance(data, dict):
        return ["pack must be a JSON object"]
    errors: list[str] = []

    for key in ("id", "name"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"'{key}' must be a non-empty string")
    if "summary" in data and not isinstance(data["summary"], str):
        errors.append("'summary' must be a string")
    version = data.get("schema_version", 1)
    if version != 1:
        errors.append(f"unsupported schema_version {version!r} (expected 1)")
    errors.extend(_voice_errors(data.get("voice")))

    intensities = data.get("intensities")
    if not isinstance(intensities, dict):
        errors.append("'intensities' must be an object keyed by intensity")
        return errors

    for name in intensities:
        if name not in INTENSITIES:
            errors.append(f"unknown intensity {name!r}; expected one of {', '.join(INTENSITIES)}")
    for name in INTENSITIES:
        if name not in intensities:
            errors.append(f"missing intensity {name!r}")

    seen_ids: dict[str, str] = {}
    seen_text: dict[str, str] = {}
    for intensity, groups in intensities.items():
        where = f"{intensity}"
        if not isinstance(groups, dict):
            errors.append(f"{where}: must be an object keyed by group")
            continue
        for group in groups:
            if group not in ALL_GROUPS:
                errors.append(f"{where}: unknown group {group!r}")
        for group in REQUIRED_GROUPS:
            lines = groups.get(group)
            if not isinstance(lines, list) or len(lines) < MIN_LINES_PER_GROUP:
                errors.append(
                    f"{where}: required group {group!r} needs at least {MIN_LINES_PER_GROUP} lines"
                    f" (has {len(lines) if isinstance(lines, list) else 0})"
                )
        for group, lines in groups.items():
            gwhere = f"{where}/{group}"
            if not isinstance(lines, list):
                errors.append(f"{gwhere}: must be a list of lines")
                continue
            if 0 < len(lines) < MIN_LINES_PER_GROUP and group not in REQUIRED_GROUPS:
                errors.append(f"{gwhere}: a present group needs at least {MIN_LINES_PER_GROUP} lines (has {len(lines)})")
            for index, line in enumerate(lines):
                errors.extend(_line_errors(f"{gwhere}[{index}]", line, seen_ids, seen_text))
    return errors


def _voice_errors(voice: Any) -> list[str]:
    if voice is None:
        return []
    if not isinstance(voice, dict):
        return ["'voice' must be an object"]
    errors = []
    rate = voice.get("rate", 1.0)
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not (0.25 <= rate <= 3.0):
        errors.append("voice.rate must be a number between 0.25 and 3.0")
    volume = voice.get("volume", 1.0)
    if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not (0.0 <= volume <= 1.0):
        errors.append("voice.volume must be a number between 0.0 and 1.0")
    preferred = voice.get("preferred_voice")
    if preferred is not None and not isinstance(preferred, str):
        errors.append("voice.preferred_voice must be a string or null")
    return errors


def _line_errors(where: str, line: Any, seen_ids: dict[str, str], seen_text: dict[str, str]) -> list[str]:
    if not isinstance(line, dict):
        return [f"{where}: must be an object with 'id' and 'text'"]
    errors = []
    line_id = line.get("id")
    text = line.get("text")
    if not isinstance(line_id, str) or not line_id.strip():
        errors.append(f"{where}: 'id' must be a non-empty string")
    else:
        if line_id in seen_ids:
            errors.append(f"{where}: duplicate id {line_id!r} (also at {seen_ids[line_id]})")
        else:
            seen_ids[line_id] = where
        where = f"{where} ({line_id})"
    if not isinstance(text, str) or not text.strip():
        errors.append(f"{where}: 'text' must be a non-empty string")
        return errors
    normalized = " ".join(text.split()).casefold()
    if normalized in seen_text:
        errors.append(f"{where}: duplicate text (also at {seen_text[normalized]})")
    else:
        seen_text[normalized] = where
    braces = brace_errors(text)
    errors.extend(f"{where}: {problem}" for problem in braces)
    if not braces:
        rendered = render(text, WORST_CASE)
        if len(rendered) > MAX_LINE_CHARS:
            errors.append(
                f"{where}: {len(rendered)} chars after rendering, cap is {MAX_LINE_CHARS}: {rendered!r}"
            )
    return errors
