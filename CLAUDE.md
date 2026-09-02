# chargerwin

Windows tray app. Speaks a short line when the AC adapter is plugged or
unplugged, escalating based on how long the machine has been unplugged and
how many times the cable has been toggled today.

Inspired by a macOS app called Charger Breakup. Background, prior-art
teardown, and the reasoning behind everything below is in `RESEARCH.md`.
Read that when a decision here looks arbitrary or when evaluating a TTS or
model option. This file is the operational summary and wins if the two
disagree.

## You cannot test this here

Development happens in a Linux Codespace. No battery, no AC adapter, no
Windows API. `pywin32` will not install. Anything touching
`WM_POWERBROADCAST` is unverifiable in this environment.

- Power detection sits behind a `PowerSource` interface: a real Windows
  implementation and a fake one.
- `--simulate plug|unplug` drives the full pipeline without hardware. This
  is the primary dev loop.
- Everything else must be testable with pytest on Linux, and must have
  tests.
- Hardware testing happens on a Windows laptop via `git pull`. Slow
  feedback loop. Do not write code whose only debugging path is running it
  on Windows.

## Settled decisions

Decided during planning. Do not re-open without being asked.

| Area | Decision |
|---|---|
| Event detection | Hidden message-only window, `WM_POWERBROADCAST` (0x218) + `PBT_APMPOWERSTATUSCHANGE` (0xA), then `GetSystemPowerStatus` for state. Event driven, never poll. |
| State comparison | Always diff against last known AC status. The message also fires on battery-percentage changes, so not every message is a plug event. |
| Windows API binding | `ctypes`, not `pywin32`. `pywin32` cannot install in the Linux dev environment, so depending on it would make the whole module unimportable here rather than just unverifiable. |
| Battery data | `psutil.sensors_battery()` for percent and `power_plugged` |
| Tray | `pystray` |
| Packaging | PyInstaller, single exe |
| TTS at runtime | None. Lines pre-rendered to wav, cached on disk, keyed by line id. |
| Default voice | Windows SAPI via `pyttsx3`. Works with zero config. Better voices are an upgrade path. |
| Line generation | Separate offline batch script. Not part of the running app. |
| State persistence | JSON in `%APPDATA%\chargerwin\`. Path injectable for tests. |
| Network | App runs fully offline. No network call on the event path, ever. |
| Target hardware | MSI GF63 Thin 11SC. GTX 1650 Max-Q 4 GB VRAM, i5-11400H, 32 GB DDR4. Plenty of RAM, weak GPU. |
| Line generation model | API by default (OpenRouter / Claude) for speed. Local 8B abliterated on CPU is a genuine alternative for unattended batch runs, ~4-7 tok/s on this machine. |

## Content rules

- Pack content is written fresh for this project. Never reproduce lines,
  pack names, or audio from any existing app. Schema and structural
  patterns are fine; text is not.
- Hard cap 160 characters per line after variables render. This is
  load-bearing, not cosmetic. Long lines are funny once and irritating by
  the third time.
- Every line needs a stable `id`. The TTS cache keys on it, so editing text
  without changing the id serves stale audio.
- Any sound effects must be self-sourced under a license permitting
  redistribution, with attribution in `THIRD-PARTY-NOTICES.txt`.

## Pack schema

One JSON file per pack. Three intensity levels. Same reaction groups in
each, two lines minimum per group.

**v1 ships 9 groups.** The schema supports the full set below, but only
these are required for a pack to be valid, and only these are populated for
now:

`immediate`, `immediate_late_night`, `escalation_30`, `escalation_60`,
`rapid_3`, `rapid_10`, `reunion_under_5`, `reunion_5_through_60`,
`reunion_over_60`

Planning said 8 and omitted `reunion_5_through_60`. That was an oversight,
not a decision: without it the middle of the three reunion durations falls
back to the under-5-minute pool, so a 40-minute absence gets a line written
for a 40-second one. It is 3 lines per intensity, so the content-wall
argument below does not apply. `groups.py` and `field_notes.json` have
required and populated it since the core was built; this file was corrected
to match on 2026-09-02.

Rationale: 21 groups x 3 intensities x 2 lines is 126 lines before one pack
is even complete. That is a content wall in front of a working app. Ship
the skeleton, expand later. Adding groups must be additive, never a
migration.

Full set the schema must accept and the selector must tolerate as empty:

Disconnect: `immediate`, `immediate_morning`, `immediate_afternoon`,
`immediate_evening`, `immediate_late_night`, `escalation_10`,
`escalation_30`, `escalation_60`, `rapid_2`, `rapid_3`, `rapid_4`,
`rapid_5`, `rapid_6_through_9`, `rapid_10`, `rapid_11_through_19`,
`rapid_20`, `rapid_21_plus`

Reunion: `reunion_under_5`, `reunion_5_through_60`, `reunion_over_60`,
`rapid_reunion`

Battery: `healthy`, `degraded`, `connectedDrain`, `newAdapter`,
`insufficientEvidence`

Variables: `{{battery_percent}}`, `{{absence_seconds}}`,
`{{absence_human}}`, `{{today_count}}`, `{{weekly_count}}`,
`{{total_count}}`, `{{longest_absence_seconds}}`,
`{{average_away_seconds}}`, `{{local_time}}`, `{{toggle_count}}`

Time windows: late night 22:00-04:59, morning 05:00-11:59, afternoon
12:00-16:59, evening 17:00-21:59. Escalations fire while still unplugged at
10, 30, 60 minutes. Rapid groups key off disconnect count today.

## Selector semantics

Decided, implement as specified.

**Empty group fallback.** Walk a defined chain, never crash, never go
silent. Specific to general:

1. Exact group for the current state
2. The base group in that family (`escalation_60` falls back to
   `escalation_30`, then `immediate`; `rapid_10` to `rapid_3`, then
   `immediate`; any `reunion_*` to `reunion_under_5`)
3. Plain `immediate` for disconnects, `reunion_under_5` for reconnects
4. Same group at a lower intensity in the same pack
5. Log a warning and say nothing

Rule 5 matters: silence beats a wrong-tone line. A validator should catch
empty required groups at load time so rule 5 never fires in practice.

**Time of day merges, does not override.** Candidates for a disconnect are
`immediate` plus the matching `immediate_<timeofday>` in one pool, with
time-specific lines weighted roughly 2:1 over generic ones. Overriding
would mean a pack with one late-night line repeats it every night, which is
exactly the repetition the 160-char cap exists to avoid.

**No immediate repeats.** Track the last line id played per group and
exclude it from the next draw when the group has more than one candidate.

## Build order

1. [done] Repo structure, `requirements.txt`, `.gitignore` (must ignore `.env`)
2. [done] Pack schema doc plus one sample pack with original lines
3. [done] State machine and line selector, with tests
4. [done] `--simulate plug|unplug` and CLI entry point
5. Tray icon and audio playback
6. Windows power hook (unverifiable here, keep thin)
7. TTS render script
8. Batch line generation script

Stop after step 4 and report. Do not build 5 through 8 until the core is
confirmed working on Windows hardware.

### Current position (2026-09-02)

Steps 1-4 are built and committed on branch `core-pipeline` (`a0e6733`,
215 tests). The gate above is **not yet cleared**: nothing has run on the
MSI laptop.

What exists: `power/` (interface + fake only), `groups.py`, `state.py`,
`selector.py`, `variables.py`, `validate.py`, `packs.py`, `pipeline.py`,
`cli.py`, `packs/field_notes.json` (81 lines), and a test file per module.

Next action is verification, not code. On the Windows laptop, `git pull`
then:

```
pip install -r requirements-dev.txt
pytest
python -m chargerwin --validate
python -m chargerwin --simulate unplug --state-dir %TEMP%\cw
python -m chargerwin --simulate tick   --state-dir %TEMP%\cw --now <+31min>
python -m chargerwin --simulate plug   --state-dir %TEMP%\cw
```

That confirms the core is sound on the target OS without needing the power
hook to exist yet. Step 5 unlocks once it passes.

Decisions made during the build that are not obvious from the code:

- `--simulate` gained a third mode, `tick`, which fires whatever escalation
  is due. Escalations are timer-driven and so had no other way to be
  exercised from the CLI.
- The 160-character cap is validated against *worst-case* rendered width
  (`variables.WORST_CASE`), not raw source text. A line that fits until
  `{{absence_human}}` expands is a bug that only shows up in front of a
  user.
- Escalation groups never fall back to `immediate`. The general fallback
  chain in this file allows it; in practice a "you just unplugged" line is
  the wrong tone an hour in, so escalations stop at the lowest populated
  escalation. Rapid groups still fall back to `immediate`, which is right,
  because a rapid group is still a disconnect moment.
- A disconnect within 10 minutes of the previous one extends the toggle
  streak (`state.STREAK_WINDOW_SECONDS`); a streak of 3+ routes a reconnect
  to `rapid_reunion`. Planning never fixed these numbers.
- Elapsed time is clamped at zero, so a backward clock step (DST, NTP
  correction, laptop resume) cannot produce a negative absence.

## Secrets

API keys go in `.env`, gitignored, loaded with `python-dotenv`. Never
commit a key, never log one, never hard-code one as a default.

## Maintaining these files

Update this file when a decision changes or a new constraint appears. Edit
sections in place rather than appending notes. Put evidence, comparisons,
and reasoning in `RESEARCH.md`; keep this file short enough that loading it
every session stays cheap. Date-stamp anything depending on an external
free tier.
