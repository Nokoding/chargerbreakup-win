# Research notes

Reference material from the planning phase, September 2026. Read when you
need the reasoning behind a decision, when evaluating a TTS or model
option, or when something in `CLAUDE.md` looks arbitrary.

`CLAUDE.md` is the operational summary. This file is the evidence behind
it. If the two disagree, `CLAUDE.md` wins and this file needs updating.

Anything depending on an external free tier is date-stamped. Those move
fast; re-verify before relying on them.

---

## 1. Where this came from

**Charger Breakup**, a macOS menu bar app by Douro Digital. Went viral on
Instagram. Site is a Railway deployment; releases live in the GitHub org
`R3LAMP4GO/charger-releases`; bundle id `com.dourodigital.ChargerBreakup`.

Closed source. Swift, macOS 14+, `LSUIElement` (menu bar only, no dock
icon), ad-hoc signed without Apple notarization, so users have to
right-click-Open past Gatekeeper. Auto-updates via Sparkle pointing at an
`appcast.xml` in the releases repo. Version 1.0.34 shipped 30 Aug 2026, so
the project is actively maintained. Solo developer, minimal web presence
outside the site and GitHub.

An Instagram reel is reportedly the main marketing and reportedly has
around a million views. It could not be located during research: Meta
blocks search engine indexing of reels, and searching the creator's name
returns unrelated results. If the reel matters later, the URL or handle has
to come from the user directly.

### Why we inspected it

To understand how a viral app in this exact niche is actually built, before
guessing. The distribution `.dmg` is public, so this was reading a shipped
artifact, not obtaining anything private.

### What the teardown found

The single most useful finding: **there is no LLM anywhere in the app.**
Every spoken line is hand-written and shipped inside the bundle. Roughly
200 KB of JSON across 14 personality packs, on the order of 250 lines in
each of the larger ones.

This reframes the whole project. What made it go viral is writing quality
plus event logic that knows the difference between "you unplugged at 2am"
and "you have now toggled this cable eight times in two minutes." Live
generation is not required to reproduce the appeal. It is an optional
upgrade, not the foundation.

Other findings:

- Packs are paid in-app purchases (`isFree: false`, product ids under
  `com.dourodigital.ChargerBreakup.pack.*`). One battery pack is free.
- Roughly 14 packs spanning clingy, confrontational, theatrical, stoic,
  motivational, noir, fantasy, corporate, meditative and explicit
  archetypes.
- Voice: the OS text-to-speech voice by default, with optional cloud TTS
  (Fish Audio) if the user pastes an API key. Each pack specifies a speech
  rate, a volume, and optionally a preferred voice identifier.
- The explicit pack does its work with three Creative-Commons vocal sound
  effects sourced from freesound.org, played around otherwise unremarkable
  spoken lines, with attribution in a `THIRD-PARTY-NOTICES.txt`. The text
  itself is suggestive rather than graphic. Worth noting: the effect comes
  from audio and timing, not from explicit writing.
- Some packs gate the nagging behind typing an apology, with a small list
  of accepted phrases and a graded response depending on how long you were
  gone.
- Pack copy is authored in Markdown files and synced into Swift source
  before shipping, per an internal authoring README in the bundle. Their
  own build process treats content as data that gets compiled in.

### Their schema, which we reuse

Per pack: an id, display name, summary, voice settings, a battery-insight
group set, and three intensity levels. Each intensity carries the full set
of ~21 reaction groups plus its own apology prompt.

Reaction groups key off three independent axes:

1. **Time of day** at the moment of disconnect
2. **Elapsed time** still unplugged (10, 30, 60 minute escalations; we ship 30 and 60, see section 6)
3. **Repeat count** of disconnects that day (2, 3, 4, 5, 6-9, 10, 11-19,
   20, 21+)

Plus reunion groups keyed off how long you were gone.

Template variables are interpolated at playback: battery percent, absence
duration, counts for today, week and total, longest absence, average away
time, local time, toggle count, and an apology grade.

Lines are capped at 160 characters after rendering. This constraint is
load-bearing. A fifteen-second monologue is funny once and irritating by
the third time.

### The line we do not cross

Structure, schema, and design reasoning are fair to reuse; every Windows
port of a Mac app does exactly that. The written lines, pack names, and
audio files are the creator's actual product, sold as in-app purchases, and
copyrighted whether or not the `.dmg` is publicly downloadable.

Their line texts were deliberately excluded from every project file,
including this one. A model that has never seen them cannot accidentally
echo them. Write fresh content.

---

## 2. Windows event detection

Settled quickly, well-documented territory.

Windows broadcasts `WM_POWERBROADCAST` (0x218) with the event identifier
`PBT_APMPOWERSTATUSCHANGE` (0xA) whenever the machine switches between
battery and AC. Microsoft's documentation is explicit that an application
should respond to this by calling `GetSystemPowerStatus`, because the
message itself carries no state; `lParam` is reserved and zero.

The message also fires when remaining battery drops below a user-defined
threshold or changes by a set percentage, so the handler must compare
against the previously known AC status rather than assuming every message
is a plug event. This is the classic bug in every naive implementation of
this and there are forum posts going back over a decade making exactly that
mistake.

Implementation shape: register a hidden message-only window and pump
messages. Event driven, no polling. In Python that is `pywin32` or raw
`ctypes`. `psutil.sensors_battery()` supplies percent and `power_plugged`
for the template variables.

Windows has no built-in system sound for charger connect or disconnect and
no registry setting to enable one. Multiple Microsoft support threads
confirm this. Any beep users may have heard on specific laptops comes from
an OEM audio utility, not the OS. So this app has no native equivalent to
compete with.

### Existing Windows prior art

`jamestut/WindowsChargeAudio` on GitHub: a .NET service that plays a
user-defined sound when a Windows 10 device is plugged in. Configuration
lives in registry keys; installed via `InstallUtil.exe`. Plug-in only, no
unplug detection, no personality layer, no timing logic.

Not worth forking. It covers a small fraction of the scope and the install
story is worse than a PyInstaller exe.

Nothing else exists that combines charger events with a personality or
voice layer on Windows. This niche is genuinely open.

### A Windows advantage worth using

Windows cleanly exposes plugged-in-but-not-charging, which enables a
"you're right here and I'm still losing charge" reaction. The macOS
original has related groups for unstable connection and reduced wattage
that lean on macOS adapter telemetry; equivalents on Windows would need a
WMI source that may not exist consistently across OEMs. Drop those unless
one is found.

---

## 3. Text-to-speech options

Only relevant at build step 7. Because audio is pre-rendered and cached,
quality matters and latency does not. This inverts the usual priorities.

| Option | Cost | Verdict |
|---|---|---|
| Fish Audio S2.1 Pro | $15 / M UTF-8 bytes paid | What the original uses. ~70-90ms time-to-first-audio, 83 languages, voice cloning from a ~10s reference, inline emotion tags like `[whisper]` and `[excited]`. Best quality per dollar found. |
| Kokoro-82M | free | Apache 2.0, 82M params, ~2-3 GB, near real-time on CPU, 54 preset voices, no cloning. The honest answer for something that runs on any laptop. Offline fallback. |
| Chatterbox Turbo | free | MIT, 350M params, 4-8 GB VRAM, voice cloning from 5-10s. Best option for a custom voice with no commercial restrictions. |
| ElevenLabs | free tier ~10k credits/mo | Best English quality. Free tier is roughly 6-10 minutes of audio, effectively a trial. Not enough for a full pool render. |
| Windows SAPI via `pyttsx3` | free | Instant, offline, sounds like 2009. Direct equivalent of the original's OS-voice default. Ship as the zero-config default so the app works before any key is configured. |

### The Fish Audio free tier caveat

Fish published a free model string, `s2.1-pro-free`, same model as the paid
tier, no hard character cap, subject to fair use. The free window was
extended twice and their announcement states it runs **through 31 August
2026**.

As of **2 September 2026** their pricing documentation still listed
`s2.1-pro-free` at $0.00 per million UTF-8 bytes. So it was likely still
live but past its stated end date.

Treat it as a bonus, not a foundation. Verify before depending on it, and
make sure the app degrades to SAPI or Kokoro if it disappears.

Scale check: the entire line pool across all packs is well under 200 KB of
text. A full render at the paid rate is a few dollars, one time, and only
new or edited lines need re-rendering after that. The economics are
trivial either way, which is another argument for not over-optimising here.

---

## 4. Line generation options

Batch, offline, run occasionally. Same inversion: quality per batch
matters, latency is irrelevant.

**Target hardware: MSI GF63 Thin 11SC.** GTX 1650 Max-Q with **4 GB
VRAM**, i5-11400H (6c/12t), **32 GB DDR4**. Confirmed Sept 2026.

The 4 GB card is too small to hold an 8B model at Q4_K_M (~4.9 GB), but
32 GB of system RAM makes CPU inference with partial GPU offload entirely
workable. Expect roughly 4-7 tok/s for an 8B on this CPU, and 1-2 tok/s for
a 24B at Q4 (~14 GB, fits in RAM comfortably).

Those numbers are unusable interactively and perfectly acceptable for batch
generation that runs unattended. Since generation is batch by design, local
is a real option here, not a compromise.

| Option | Runs on this machine | Cost | Notes |
|---|---|---|---|
| OpenRouter `cognitivecomputations/dolphin-mistral-24b-venice-edition` | hosted | $0.20/M in, $0.90/M out | **Default.** 24B quality, no local wait. Cents per run at this volume. |
| Claude / GPT / Gemini APIs | hosted | cheap at this volume | Best writing quality. Use where wit carries the joke. Declines explicitly vulgar content. |
| Ollama `huihui_ai/dolphin3-abliterated:8b` | yes, CPU + partial offload, ~4-7 tok/s | free | Most-pulled abliterated Dolphin. The local default. Fine for overnight batches. |
| Ollama `mannix/llama3.1-8b-abliterated` | yes, ~5.7 GB at Q5, similar speed | free | Slightly better prose than Dolphin. |
| Ollama `huihui_ai/mistral-small-abliterated` (24B) | yes, ~14 GB in RAM, ~1-2 tok/s | free | Noticeably funnier. Genuinely slow. Viable if left running overnight. |
| Ollama 3-4B abliterated (`jan-nano`, `Hermes-3-Llama-3.2`) | yes, fits in VRAM, fast | free | Only worth it if you want GPU speed. Weaker writing, heavy curation. |

### The OpenRouter free tier correction

Widely-cited 2025 guides describe the Venice model as free on OpenRouter,
offered at no cost through a partnership, and it was the standard
recommendation for a free uncensored API.

**That is no longer true.** Checked against OpenRouter's live model list on
2 September 2026: $0.20 per million input tokens, $0.90 per million output.
None of the 18 models then carrying a `:free` suffix were uncensored
variants. Any tutorial claiming otherwise is stale.

### Recommended approach

API by default because it is faster and effectively free at this volume.
Local as a genuine alternative, not a fallback: an 8B abliterated model on
CPU handles a full pack generation run overnight with no cost and no
network.

Split by pack: a high-quality general model where writing quality carries
the joke, an uncensored model (hosted or local) for anything a mainstream
model declines.

Treat generation as curation, not automation: over-generate candidates,
keep the best third, hand-edit freely. The model choice matters less than
the filtering.

## 5. Hosting, considered and rejected

Hosting a model on a free cloud VM was considered, Oracle's Always Free
tier specifically.

Rejected. Reasons, as of mid-2026:

- Oracle halved the Always Free Ampere A1 allocation from 4 OCPU / 24 GB to
  2 OCPU / 12 GB, without a formal announcement. Free-tier accounts
  exceeding the new limit have instances shut down until manually resized.
- There are no GPUs in the free tier at all. An 8B model on 2 ARM cores
  runs at single-digit tokens per second.
- Regional capacity is unreliable; "out of capacity" errors on A1 shapes
  are widely reported and Oracle does not guarantee you can claim the
  advertised shape.

Since generation is batch work, a local machine running overnight does the
same job with no VM to secure, no capacity lottery, and no policy risk.

The general lesson: this project has no always-on server component and
should not acquire one. Every runtime dependency added is a way for the app
to break on a plane.

---

## 6. Design decisions and their reasoning

Collected rationale for things that look arbitrary in `CLAUDE.md`.

**Pre-rendered audio, never synthesize at event time.** A two-second delay
after yanking a cable kills the joke, because the joke is the immediacy.
Caching also makes the app work offline and removes runtime cost and API
dependency. Cache is keyed on line id, which is why ids must be stable.

**Batch generation, never generate at event time.** Same latency argument,
plus it puts a human between the model and the user.

**160 character cap.** Inherited from the original because it is correct.
Replayability depends on brevity.

**Fully offline runtime.** Follows from the two above. If nothing on the
event path touches the network, there is nothing to fail.

**Free, no paid packs.** The original monetises packs. No reason to here.

**Optional fresh line on long reunions.** After a 60+ minute absence,
optionally fire an async generation using real stats and play it a few
seconds after the cached line. The original has no live generation
whatsoever, so this is the one visible capability it lacks. Strictly
optional, strictly off the critical path, app must be fully functional with
it disabled.

**Reduced reaction groups for v1.** The original's 21 groups per intensity
is right for a mature app and wrong for a first release. 21 groups x 3
intensities x 2 lines minimum is 126 lines before a single pack is even
valid, which is a content wall standing between the project and a working
app. v1 ships 9 groups, the schema supports all 21, and the selector falls
back gracefully so adding groups later is additive rather than a migration.
Ship the skeleton, fill it in over time.

**Escalation cadence is 30 and 60 minutes, not 10, 30 and 60.** The
original escalates at ten minutes and we copied that. Cut on 2026-09-03
after running it: ten minutes off the charger is ordinary laptop use, not
an absence. Somebody carries the machine to the kitchen table, or reads
something on the sofa, and gets nagged for it. The joke depends on the app
being right that you have been gone a while, and at ten minutes it is not
right. Thirty is the first point where a comment lands.

Cutting it also removed a bug rather than papering over one. `escalation_10`
fired but was never a required group, and escalations deliberately do not
fall back to `immediate`, so the first escalation a user heard was silence
plus a log warning. The alternative fix was writing nine lines for a
threshold that should not fire anyway.

If you are considering re-adding it: this was tried and cut deliberately,
not overlooked. Re-adding means adding `escalation_10` to `REQUIRED_GROUPS`
and populating it in every pack, which
`test_every_firing_escalation_has_guaranteed_content` will insist on. The
group name is still valid in the schema precisely so that stays additive.

**Ship the OS voice as default.** Matches the original's approach and means
the app works immediately with zero configuration or API keys. Better
voices are an upgrade path, not a requirement.

---

## 7. Open questions

**Blocking, must be done before the relevant build step:**

- [ ] **Test whether `s2.1-pro-free` still works.** Its free window
      officially ended 31 August 2026; Fish's pricing page still listed it
      at $0.00 on 2 September 2026. Send one real TTS request and check for
      a 200 and audio bytes back before step 7 builds anything around it.
      If it fails, the render script targets SAPI and Kokoro, and Fish
      becomes a paid opt-in.

**Non-blocking:**

- Whether a reliable WMI source exists for adapter wattage across Windows
  OEMs. Investigate only if the `lowWattage` reaction group is wanted.
  Default is to drop it.

**Resolved / closed:**

- Target hardware: MSI GF63 Thin 11SC, GTX 1650 Max-Q 4 GB VRAM,
  i5-11400H, 32 GB DDR4. Local generation is viable on CPU for batch work;
  API remains the default for speed. See section 4.
- Reaction group count for v1: reduced to 9. Rationale in section 6.
  Planning wrote 8; `reunion_5_through_60` was added during the step 3
  build (2026-09-02) because omitting it sends every 5-to-60-minute
  absence to the under-5-minute lines. Three lines per intensity, so it
  does not reopen the content-wall argument.
- Escalation cadence: 10-minute escalation tried and cut 2026-09-03,
  leaving 30 and 60. Fires during normal laptop use rather than an actual
  absence, and it shipped silent because nothing required its lines.
  Rationale in section 6. Do not re-add without reading it.
- The Instagram reel is out of scope. Marketing reach is not a build input.
