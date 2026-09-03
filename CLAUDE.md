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
| Escalation cadence | Fires at **30 and 60 minutes** unplugged. 10 was tried and cut; see `RESEARCH.md` before re-adding it. Any firing threshold must have its group in `REQUIRED_GROUPS`, or the escalation is silent. |
| Battery data | `psutil.sensors_battery()` for percent and `power_plugged` |
| Tray | `pystray` |
| Packaging | PyInstaller, single exe |
| TTS at runtime | None. Lines pre-rendered to wav, cached on disk, keyed by line id **and engine**. The engine is in the cache path so replacing the placeholder voice is a cache miss, not stale audio. |
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
30 and 60 minutes. Rapid groups key off disconnect count today.

## Selector semantics

Decided, implement as specified.

**Empty group fallback.** Walk a defined chain, never crash. The whole
chain is tried at the current intensity before dropping an intensity:

1. Every group in the chain for the current state, nearest first
2. The same chain at each lower intensity in turn
3. Log a warning and say nothing

The chains, as implemented in `selector.fallback_chain`:

| Requested | Chain |
|---|---|
| `immediate`, `immediate_<tod>` | the merged immediate pool (see below) |
| `escalation_N` | every lower escalation, descending. **Stops there.** |
| `rapid_N` | every lower rapid, descending, then the immediate pool |
| `reunion_X` | every shorter reunion, descending |
| `rapid_reunion` | itself, then the duration-keyed reunion chain |
| battery groups | itself only |

**Escalations deliberately never reach `immediate`.** Planning specified
that they should; implementing it made the flaw obvious. An "oh, you
unplugged" line is wrong an hour into an absence, and wrong in a way the
user notices, because they know how long it has been. Rapid groups do fall
back to `immediate`, which is correct: a rapid group is still the moment
of a disconnect.

Rule 3 matters: silence beats a wrong-tone line. The validator catches
empty *required* groups at load time, so for those it never fires. It can
still fire for a non-required group whose chain dead-ends, which is a
content bug, not a selector bug. Anything that *fires* must therefore be in
`REQUIRED_GROUPS`; `test_every_firing_escalation_has_guaranteed_content`
enforces that for escalations.

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
5. [done] Tray icon and audio playback
6. Windows power hook (unverifiable here, keep thin)
7. TTS render script (partly done: SAPI renders the cache; better engines
   are a new `Renderer` with a different `key`)
8. Batch line generation script

Stop after step 4 and report. Do not build 5 through 8 until the core is
confirmed working on Windows hardware.

### Current position (2026-09-03)

Steps 1-5 built, 273 tests. **Windows gate cleared 2026-09-03**: all six
verification commands passed on the MSI, including the `escalation_10` fix
and `reunion_5_through_60` routing.

Step 5 shipped tray, audio playback, the wav cache and a SAPI renderer:

| Module | Role |
|---|---|
| `audio.py` | `Player` protocol, `NullPlayer`, `WinsoundPlayer` (async, interrupting) |
| `voice.py` | `VoiceCache` plus `Renderer` protocol, `Pyttsx3Renderer`, `FakeRenderer` |
| `settings.py` | User prefs in `settings.json`, separate from the counters |
| `tray.py` | Menu as plain data (`build_menu`), thin pystray shell |
| `app.py` | `Speaker` and `App`: wires state, pack, cache, player and tray |

New CLI: `--tray`, `--warm [--force]`, `--engine sapi|fake`, `--cache-dir`,
and `--play` on `--simulate`.

Next action: **step 6, the Windows power hook.** `App.on_power_status` and
`App.resync` are the only entry points it needs; it should call them and
own nothing else. `App.on_tick` needs a timer while unplugged for the 30
and 60 minute escalations.

Decisions made during step 5:

- **SAPI renders the cache; it does not speak at event time.** Asked for
  during step 5 as a placeholder voice so there is something to hear before
  a better engine exists. Live synthesis was not built: it contradicts the
  settled pre-rendered decision, and a delay after yanking the cable is the
  one thing that kills the joke. Renders go through the same cache a Fish
  or Kokoro backend will use, so step 7 swaps a class rather than a design.
- **The cache path includes the engine key**, `<pack>/<engine>/<id>.wav`.
  Line ids are stable by design, so an id-only key would serve SAPI audio
  forever after switching engines. Switching is now a miss, and switching
  back reuses what is there.
- **Line ids are validated before becoming filenames**
  (`[A-Za-z0-9][A-Za-z0-9._-]*`). Packs are data; an id must not write
  outside the cache or create a hidden file. Not yet enforced by the pack
  validator, only by the cache -- worth moving earlier if a third consumer
  of ids appears.
- **`settings.json` is separate from `state.json`.** Counters are written
  on every event and are cheap to lose; preferences are written rarely and
  annoying to lose. A corrupt counter file should not cost the user their
  intensity and mute.
- **A missing TTS engine raises instead of reporting a successful render of
  nothing.** `warm()` swallows per-line failures but re-raises `ImportError`,
  because that is a broken setup rather than a bad line. This is the same
  silent-failure shape as the `escalation_10` bug.
- **`Say something` does not touch the counters**, but does record the line
  as last played, so a demo cannot immediately repeat what a real event just
  said.
- **Playback never raises.** A cache miss, a missing device or a wav
  winsound cannot decode all degrade to a logged warning. Nothing about a
  sound effect should take the tray down.

**Windows run 2026-09-03.** `--warm` rendered 27 lines through real SAPI and
`--simulate --play` played one through `WinsoundPlayer`, both correct on the
first try. `--tray` crashed, now fixed:

- *pystray rejects a callback with more than two parameters.* It reads
  `action.__code__.co_argcount`, which **counts parameters that have
  defaults**. The standard late-binding idiom, `lambda icon, item,
  fn=item.action: fn()`, therefore reads as three parameters and raises
  `ValueError(action)` while building the Intensity submenu. Callbacks are
  now bound with closure factories (`_action_callback`,
  `_checked_callback`) so the visible arity stays at two. The same idiom is
  still used inside `build_menu`, where it is correct: those callables are
  ours and are called with no arguments. Only the ones crossing into
  pystray are constrained.
- *The tray failure path caught only `ImportError`.* pystray selects a
  backend at import, so where it is installed without a display it raises
  the backend's own error instead. `run_tray` now catches `Exception` and
  prints a legible message.

`_to_pystray` was written off as "thin, holds no logic worth testing"; it
held the arity contract, which is precisely the sort of thing that cannot
be seen from the data model. `tests/test_tray_pystray.py` now converts a
real menu against a stub that mirrors `_assert_action`, so this class of
bug fails in the Codespace instead of on the laptop.

Still unverified on Windows: the tray itself running to a visible icon, and
menu interaction. `pystray` installs in the Codespace but cannot start
without a display, so conversion is tested and the running icon is not.

## Secrets

API keys go in `.env`, gitignored, loaded with `python-dotenv`. Never
commit a key, never log one, never hard-code one as a default.

## Maintaining these files

**Update this file in the same change that makes the update true.** Never
finish a piece of work and leave the docs describing the state before it.
Not a follow-up task, not a later cleanup pass: the doc edit and the code
edit belong in one commit. This file is the first thing loaded each
session, so a stale line here misinforms every future session until someone
notices.

Update after any change that makes one of these false:

- **Build order.** Mark steps done as they land; keep `Current position`
  saying what exists, what the next action is, and which gates are still
  closed.
- **Settled decisions.** A new row when something gets fixed in code that a
  future session would otherwise re-litigate. If code and this file
  disagree, resolve it explicitly and say which won and why.
- **Pack schema / selector semantics.** Any change to group names, required
  groups, thresholds, fallback order, or the character cap.
- **Non-obvious build decisions.** Constants and behaviours chosen while
  implementing that planning never specified. Record the reasoning, not
  just the value.

Edit sections in place rather than appending notes. Put evidence,
comparisons, and reasoning in `RESEARCH.md`, and keep the two consistent:
when a decision here changes, fix the corresponding passage there in the
same commit. Keep this file short enough that loading it every session
stays cheap. Date-stamp anything depending on an external free tier, and
anything that corrects an earlier decision.
