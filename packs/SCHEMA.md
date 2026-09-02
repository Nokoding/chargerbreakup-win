# Pack schema

One JSON file per pack in this directory. The file name is the pack id
(`field_notes.json` has `"id": "field_notes"`). Everything in a pack is
original writing for this project; see the content rules in `CLAUDE.md`.

Validate with `python -m chargerwin --validate`. The validator reports every
problem at once and the app refuses to load a pack with any of them.

## Top level

```json
{
  "schema_version": 1,
  "id": "field_notes",
  "name": "Field Notes",
  "summary": "One sentence shown in the pack picker.",
  "voice": { "rate": 0.9, "volume": 1.0, "preferred_voice": null },
  "intensities": {
    "mild":    { "<group>": [ { "id": "...", "text": "..." } ] },
    "medium":  { ... },
    "intense": { ... }
  }
}
```

| Field | Rules |
|---|---|
| `schema_version` | `1`. Optional; defaults to 1. |
| `id` | Non-empty string. Must match the file name stem. |
| `name` | Non-empty display name. |
| `summary` | Optional string. |
| `voice.rate` | Speech rate multiplier, 0.25 to 3.0. Default 1.0. |
| `voice.volume` | 0.0 to 1.0. Default 1.0. |
| `voice.preferred_voice` | Voice name hint for the TTS engine, or `null`. |
| `intensities` | All three of `mild`, `medium`, `intense`, each an object keyed by group. |

Intensity is a user setting. The selector only ever falls *down* in
intensity (intense to medium to mild), never up, so a user on `mild` never
hears an `intense` line.

## Groups

Group names are the keys inside each intensity. The full vocabulary the
validator accepts is defined once, in `chargerwin/groups.py`:

- Disconnect, by moment: `immediate`, `immediate_late_night`,
  `immediate_morning`, `immediate_afternoon`, `immediate_evening`
- Disconnect, still unplugged: `escalation_10`, `escalation_30`,
  `escalation_60`
- Disconnect, Nth of the day: `rapid_2`, `rapid_3`, `rapid_4`, `rapid_5`,
  `rapid_6_through_9`, `rapid_10`, `rapid_11_through_19`, `rapid_20`,
  `rapid_21_plus`
- Reconnect, by absence: `reunion_under_5`, `reunion_5_through_60`,
  `reunion_over_60`, and `rapid_reunion` (reconnect during a toggle streak)
- Battery insight (no trigger defined yet): `healthy`, `degraded`,
  `connected_drain`, `new_adapter`, `insufficient_evidence`

**Required in v1**, at every intensity, at least two lines each:
`immediate`, `immediate_late_night`, `escalation_30`, `escalation_60`,
`rapid_3`, `rapid_10`, `reunion_under_5`, `reunion_5_through_60`,
`reunion_over_60`.

Any other group may be omitted or left as `[]`. A group that is present
with lines must have at least two; one line would repeat every time.
Three or more is strongly recommended: with two, the no-repeat rule turns
the group into strict alternation.

When a group is empty the selector falls back along a fixed chain (see
`CLAUDE.md`, selector semantics). Two consequences for authors:

- `rapid_4` through `rapid_21_plus` fall back to the nearest lower rapid
  group, so a `rapid_3` line can play on the seventh disconnect. Do not
  hard-code the count in rapid lines unless the group above it is also
  populated; use `{{today_count}}` instead, or write around the number.
- `escalation_10` never falls back to `immediate` (wrong tone). Leave it
  empty and nothing plays at ten minutes.

Time of day merges rather than overrides: a first disconnect draws from
`immediate` and `immediate_<time>` together, with each time-specific line
weighted 2:1 against each generic line. So a single late-night line is
heard often but not every night.

Windows: late night 22:00-04:59, morning 05:00-11:59, afternoon
12:00-16:59, evening 17:00-21:59. Reunion boundaries: under 5 minutes,
5 minutes to under 60, 60 and over.

## Lines

```json
{ "id": "medium.rapid_3.2", "text": "Three detachments today. ..." }
```

- `id`: unique across the whole pack. The convention is
  `<intensity>.<group>.<n>` but any unique string works. Ids are used for
  no-repeat tracking and for humans; the audio cache does **not** key on
  them (it keys on voice plus rendered text), so editing text does not
  require a new id. Keep ids stable anyway so state files and future stats
  survive edits.
- `text`: the line. Hard cap of **160 characters after variables render**,
  checked with the worst-case widths below. Spoken by TTS, so write for the
  ear: short sentences, ordinary punctuation, no emoji, no markup.
- Duplicate text (ignoring case and whitespace) anywhere in a pack is an
  error; it is always a copy-paste mistake.

### Variables

Written as `{{name}}`. Unknown names and stray braces are validation
errors. Values are as of just after the event was applied, so on the third
disconnect `{{today_count}}` is 3.

| Variable | Meaning | Worst-case width used by the validator |
|---|---|---|
| `{{battery_percent}}` | 0-100, or `unknown` | `100` |
| `{{absence_seconds}}` | 0 on a disconnect; elapsed so far on an escalation; the completed absence on a reunion | `999999` |
| `{{absence_human}}` | Same duration, spoken form: `45 seconds`, `1 minute`, `12 minutes`, `1 hour 5 minutes`, `3 hours`, `2 days 4 hours` | `23 hours 59 minutes` |
| `{{today_count}}` | Disconnects since local midnight, including this one | `99` |
| `{{weekly_count}}` | Disconnects this ISO week (Monday start) | `999` |
| `{{total_count}}` | Disconnects ever | `99999` |
| `{{longest_absence_seconds}}` | Longest completed absence ever | `999999` |
| `{{average_away_seconds}}` | Mean completed absence, 0 if none yet | `999999` |
| `{{local_time}}` | 12-hour clock, no leading zero: `2:14 AM` | `12:59 PM` |
| `{{toggle_count}}` | Current toggle streak: consecutive disconnects each within 10 minutes of the last | `99` |

## Sample pack

`field_notes.json`: a wildlife documentary narrator who has been assigned
to observe you. Mild is gentle wonder, medium is dry judgment, intense is a
narrator who has lost patience with this particular specimen. Three lines
per group, 81 lines total.
