# Extra → dedicated columns (EV battery + edition)

Date: 2026-07-09
Status: approved
Branch: `feature/reference-versioning`

## Context

Reference versioning (TASKS.md) needs a way to tell one version of an EV
nameplate from another. The listing *name* almost never carries the variant
token — sampled real data: 0/68 "BYD Dolphin Surf" listings, 409/431 bare
"Škoda Enyaq", 1302/1330 bare "VW ID.3". EV matching is a name **prefix-join**,
so it cannot assign a version from the name.

But the `Extra` free-text column **does** carry the discriminators, across
sources:

- `Baterie 56 kWh` / `43 kWh` / `30 kWh` — mobile.de and sauto, slash-delimited.
- Edition words — `Essence`, `Selection`, `Active`, `Boost`, `Comfort`, `Pro`, …
- (also range/power, not used here)

Battery capacity is the real matchable axis (Dolphin Surf 30 kWh → Active,
43 kWh → Boost/Comfort). Editions at the *same* battery (Epiq Essence/Selection,
both 55 kWh) are not spec-distinguishable.

Separately: `Kapacita baterie (kWh)` is a **build-time enrichment** column
(filled from the `ev_specs` join), not canonical. Today a matched multi-battery
nameplate shows one *nominal* battery for all its listings regardless of the
real variant. The listing's Extra has the true per-car value.

## Scope

**In:** a build-time extractor that parses `Extra` into two dedicated columns
for EV rows — battery kWh and an edition token. Foundation only.

**Out (deferred):** reference row-splitting, EV version *matching*, listing
range/power extraction, ICE edition-from-Extra (ICE `Verze` stays
reference-trim-driven). No adapter/scrape changes.

## Design

### 1. Pure parsers — `scrapers/core/fields.py`

Pure, no network, unit-tested.

- `parse_battery_kwh(extra: str) -> str` — regex `Baterie\s*(\d+)\s*kWh`
  (case-insensitive). Returns the integer as a string, or `""` when absent or
  outside a plausibility guard of **20–120 kWh** (mirrors existing
  `sanitize_*` guards). No decimals observed in the data.
- `parse_ev_edition(extra: str) -> str` — matches `Extra` against a curated
  `EV_EDITION_KEYWORDS` allow-list (word-boundary, longest/multiword first,
  case-insensitive), returns the first hit in canonical casing or `""`. Never
  guesses from free text — feature abbreviations (LED, ACC, SHZ, Navi, …) and
  unknown tokens yield `""`. The list is seeded from observed data
  (First Edition, Essence, Selection, Active, Boost, Comfort, Pro, Pure,
  Techno, Trend, Essential, Ultimate, Evolution, Premium, Performance, Urban,
  Sportline, Allure, Elegance, Style, …) and is growable.

### 2. Build orchestration — `build/build_data.py`

`extract_ev_extra_specs(df)`, gated to `Typ == "Elektrické"`:

- **Battery**: `parse_battery_kwh(Extra)`. When present+plausible →
  **overwrite** `Kapacita baterie (kWh)` (listing wins). When absent → keep the
  reference-join value (fallback). Column is already in
  `PAYLOAD_NUMERIC_COLS`, so it is cast to float64 (hyparquet BigInt gotcha).
- **Edition → `Verze`**: `parse_ev_edition(Extra)` sets EV `Verze`
  (display-only; does not drive matching).

**Ordering (critical).** `apply_verze_display()` does `df["Verze"] = ""` then
fills ICE-`Ano` from reference trim — it would wipe EV editions. So
`extract_ev_extra_specs()` runs **after** `apply_verze_display()` (and after
`join_electric_reference()`, which sets the nominal battery). Insertion point in
`main()`: right after the `apply_verze_display(df)` call (currently line ~1086).
Net: ICE `Verze` semantics unchanged; EV battery = listing-or-reference;
EV `Verze` = extracted edition.

### 3. Display

No column-def changes. `Kapacita baterie (kWh)` already renders on both pages
(values just get more accurate). `Verze` already exists in `app.js` /
`reference.js` (Part A) and was always blank for EV — it now shows the edition
where found.

### 4. Tests

- `tests/test_fields.py` — `parse_battery_kwh` (mobile.de + sauto formats,
  implausible→blank, absent→blank), `parse_ev_edition` (each keyword class,
  feature-noise→blank, case-insensitive, multiword-first).
- `tests/test_build_data.py` — `extract_ev_extra_specs` (listing battery
  overrides reference, absent→reference kept, ICE rows untouched,
  edition→`Verze`, unknown→blank `Verze`).
- `tests/test_data_integrity.py` — EV battery within plausibility band; ICE
  `Verze` semantics unchanged.

## Verification

`./bin/test.sh` green; `python build/build_data.py` clean with a sane
battery/edition value distribution (spot-check via `value_counts`);
`verify_ui.py --page {index,reference} --scenario grid` PASS + screenshots read.
