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
| Event detection | Hidden **top-level** window (never shown), `WM_POWERBROADCAST` (0x218) + `PBT_APMPOWERSTATUSCHANGE` (0xA), plus a targeted `RegisterPowerSettingNotification` on `GUID_ACDC_POWER_SOURCE` (`PBT_POWERSETTINGCHANGE`, 0x8013). Then `GetSystemPowerStatus` for state. Event driven, never poll. **Not a message-only window**: those do not receive broadcast messages, and this one is a broadcast. Corrected 2026-09-03 after it failed on hardware. |
| State comparison | Always diff against last known AC status. The message also fires on battery-percentage changes, so not every message is a plug event. |
| Windows API binding | `ctypes`, not `pywin32`. `pywin32` cannot install in the Linux dev environment, so depending on it would make the whole module unimportable here rather than just unverifiable. |
| Escalation cadence | Fires at **30 and 60 minutes** unplugged. 10 was tried and cut; see `RESEARCH.md` before re-adding it. Any firing threshold must have its group in `REQUIRED_GROUPS`, or the escalation is silent. |
| Battery data | `GetSystemPowerStatus` supplies percent and AC status together, in the call the power message already requires. `psutil.sensors_battery()` is the fallback when it reports unknown. Two reads could disagree; one cannot. |
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
6. [done, verified] Windows power hook (sleep/resume path still untested)
7. TTS render script (partly done: SAPI renders the cache; better engines
   are a new `Renderer` with a different `key`)
8. Batch line generation script

Stop after step 4 and report. Do not build 5 through 8 until the core is
confirmed working on Windows hardware.

### Current position (2026-09-03)

Steps 1-6 built and verified on Windows, 321 tests.

**Step 6 verified on hardware.** Both delivery routes fire: `0x8013`
(`PBT_POWERSETTINGCHANGE`, targeted) lands first, `0x000A`
(`PBT_APMPOWERSTATUSCHANGE`, broadcast) confirms just after. Disconnect and
reconnect both classified correctly, `immediate_late_night` selected off the
real clock, counters and streaks tracked.

Worth recording because it was designed but unproven: after the disconnect,
the second route arrived with `plugged=False` and produced **nothing**.
Duplicate delivery is deduplicated by `State.observe` diffing against the
last known status, exactly as intended. Both routes can fire for one cable
pull at no cost.

**Two things still open in step 6:**

1. **Sleep and resume.** The `RESYNC` path has never run. Suspend the
   machine, pull the cable while it sleeps, wake it: it should adopt
   "unplugged" silently and say nothing.

   Watch for one specific failure. `PBT_APMRESUMEAUTOMATIC` is classified
   as RESYNC, but the power-setting notification for the change that
   happened during sleep may arrive *before* the resume message rather than
   after. If it does, the app announces a disconnect that happened while it
   was asleep, which is precisely what RESYNC exists to prevent. If that
   happens, the fix is to treat `PBT_APMSUSPEND` as a latch: once seen,
   every status change is adoption until resume clears it. Not built yet,
   because it is speculative until the test says otherwise.

2. **`--tray` with the power hook.** Only `--watch` has run against real
   events. The tray and the hook have never run together, and the
   interaction is not covered by the Linux tests: pystray owns the main
   thread while the watcher and ticker own their own, and quitting from the
   tray menu calls `stop_power_watch`, which posts `WM_CLOSE` across
   threads. Worth an unplug, an escalation, and a quit from the menu.

Decisions made during step 6:

- **The pure decisions live in `power/messages.py`, away from ctypes.**
  `ctypes.WINFUNCTYPE` does not exist off Windows, so anything importing it
  cannot even be imported here, let alone tested.
- **Not a message-only window.** Those do not receive broadcast messages;
  `WM_POWERBROADCAST` is one. Cost a full hardware round trip, because the
  window registered, pumped and reported success while receiving nothing.
- **Two delivery routes.** `RegisterPowerSettingNotification` on
  `GUID_ACDC_POWER_SOURCE` is addressed to this window rather than
  broadcast, so it does not depend on broadcast eligibility.
- **Every Win32 function is explicitly prototyped** (`_declare`). An
  unprototyped ctypes function defaults to `restype = c_int`, 32 bits, so
  `CreateWindowExW` and `GetModuleHandleW` would truncate the pointers they
  return on 64-bit Windows.
- **The WNDPROC is kept alive on the instance.** Dropping that reference
  lets ctypes free the trampoline while Windows still holds the pointer.
- **Resume is a resync, not an event.** ACLineStatus 255 is likewise
  ignored rather than guessed at.
- **The watcher runs its own thread with its own message loop**, because
  pystray owns the main thread. `App` takes an `RLock` around every state
  transition.
- **The ticker polls the clock, not the power state.**

Lesson worth keeping: the step 6 failure was silent because every
observable signal said success. A component that cannot be tested here must
log enough to tell "working" from "never invoked", or the first hardware run
produces no information beyond "no". `App.on_reaction` and the
pre-classification `WM_POWERBROADCAST` log exist for that reason.

Next action: finish step 6 (sleep/resume, then `--tray` together), then
step 7. Step 7 is blocked on the Fish Audio probe in `RESEARCH.md` section
7 -- one real request to check whether `s2.1-pro-free` still answers, since
its free window officially ended 31 August 2026. Step 8 is not blocked by
either.

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
