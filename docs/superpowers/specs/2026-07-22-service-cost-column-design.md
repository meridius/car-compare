# Design — Task #23: average annual service cost over 5 years

**Date:** 2026-07-22
**Branch:** `feat/service-cost`
**Task:** TASKS.md #23 — "average annual service cost over 5 years"

## Decisions (owner-approved)

- **Q1 (nature):** a reference-model spec, enriched from external data. → realised as a **build-time computed column** (see storage below), not a scraped/listing field.
- **Q2 (source):** no free per-model Czech service-cost API exists. Chosen strategy: a **calibrated cost model** — a transparent formula whose constants are anchored to real external data (ADAC, BOVAG-RAI, Czech servis figures). The value is an estimate (`odhad`), stated as such in the UI.
- **Q3 (fuels):** both **EV and ICE**.
- **Storage:** **computed at build time** from each row's own existing columns (like `Spolehlivost` / `reliability_score`), not stored in the reference CSVs. No CSV surgery, no date-column concerns, single source of truth = the formula, 100 % coverage on both grid and reference page.
- **Estimate flag:** no separate `zdroj` column — every value is an estimate by construction, so "odhad" is stated in the column header/tooltip and the dataset-overview methodology card instead of a constant column.
- **Display:** both the main grid (per listing) and the reference page (per model).
- **Out-of-range flag:** a plausibility clamp `[3 000, 60 000]` Kč/rok with a visible badge for any row whose raw estimate hit the bound (mirrors the reference-page price-histogram `›` overflow mark — "never a silent lie"). Honest note: under the CZ price filters the formula is mathematically bounded to ≈ `[3 100, 30 100]` Kč/rok, so the clamp does not fire on current data; the badge exists as a drift / data-quality detector.

## What the number means (scope)

**`Servis (Kč/rok)`** = estimated **average annual workshop cost over a 5-year ownership window**.

- **Includes:** scheduled servicing (oil, filters, fluids, inspections) + routine wear-and-tear repairs (brakes, belts/chains service, minor parts).
- **Excludes:** tyres, fuel/energy, insurance, road tax, depreciation.
- Matches ADAC *Werkstattkosten* / BOVAG "onderhoud" semantics. Applies to EV and ICE.

## The cost model

```
raw  = BASE_petrol × FUEL × TIER × SEGMENT × ENGINE
Servis = clamp(round_to(raw, 500), 3 000, 60 000)
```

`round_to(x, 500)` = nearest 500 Kč. A row where `round_to(raw,500)` fell outside `[3 000, 60 000]` before clamping is flagged out-of-range.

### Factors

Values below are the **calibrated** constants (recalibrated 2026-07-22 against 20
real models — see "Calibration" at the end).

| Factor | Source column(s) | Values |
|---|---|---|
| **BASE_petrol** | — | `12 000` Kč/rok (mainstream petrol compact, calibrated) |
| **FUEL** | `Palivo` + `Hybrid typ` | Benzín `1.00` · Nafta `1.10` · LPG/CNG `1.05` · MHEV `1.05` · HEV `1.00` · PHEV `1.10` · **BEV (Elektrické) `0.35`** |
| **TIER** | `Značka` | budget `0.90` · mainstream `1.00` · premium `1.25` · luxury `1.75` |
| **SEGMENT** | `Karoserie` | SUV `1.10` · everything else `1.00` |
| **ENGINE** | `Objem motoru` (ICE only; EV = `1.00`) | ≤ 1.2 L `0.95` · 1.2–2.0 L `1.00` · > 2.0 L `1.10` |

**FUEL precedence:** `Hybrid typ` wins when present (PHEV/HEV/MHEV), else `Palivo`; `Typ == Elektrické` ⇒ BEV `0.35`. A row with no usable fuel signal (blank Palivo, non-EV, no hybrid token) yields **blank** service cost (like `Spolehlivost` on a missing volume) — not a fabricated number.

**Brand tiers** (explicit sets in a `SERVICE_BRAND_TIER` map; unknown brand ⇒ mainstream `1.00`):
- **budget:** Dacia, MG (extendable).
- **premium:** BMW, Mercedes-Benz, Audi, Volvo, Lexus, Land Rover, Jaguar, Alfa Romeo, Cupra, DS, Mini, Tesla, Genesis, Polestar (extendable).
- **luxury:** Porsche, Maserati, Bentley, … (rare under the ≤ 750k Kč CZ price filter).
- **mainstream:** everything else (Škoda, VW, Kia, Hyundai, Toyota, Ford, Opel, Renault, Peugeot, Citroën, Fiat, Seat, BYD, most others).

**SEGMENT** reads the already-canonicalised `Karoserie` vocabulary. `Karoserie == "SUV"` → `1.10`; everything else (Hatchback, Sedan, Kombi, MPV, Kupé, blank) → `1.00`. A finer size split is not derivable from `Karoserie` alone, so it is deliberately not attempted.

### Sanity check (calibrated constants)

| Model | Computation | Servis |
|---|---|---|
| VW Golf 1.5 TSI | 12000·1.0·1.0·1.0·1.0 | 12 000 |
| Škoda Octavia 2.0 TDI (Kombi) | 12000·1.10·1.0·1.0·1.0 | 13 000 |
| BMW 320i (sedan, 2.0) | 12000·1.0·1.25·1.0·1.0 | 15 000 |
| Tesla Model 3 (EV, premium) | 12000·0.35·1.25·1.0 | 5 000 |
| Škoda Enyaq (EV, SUV) | 12000·0.35·1.0·1.10 | 4 500 |
| Dacia Duster 1.3 (petrol, SUV) | 12000·1.0·0.90·1.10·1.0 | 12 000 |

Max product ≈ `1.10·1.75·1.10·1.10 = 2.33` → ≈ 28 000; min ≈ `0.35·0.90 = 0.32` → ≈ 3 800. Hence the [3 000, 60 000] clamp is a safety net, not an active clip, on current data.

### Calibration (2026-07-22)

The constants above were fitted, not guessed. Method:
1. Randomly picked 20 models from the built dataset spanning fuel × tier × segment.
2. Researched each model's real annual service+maintenance cost (4 parallel agents) — primarily **ADAC Autokatalog "Werkstattkosten"** (Wartung + Reparatur, DE market), normalised to CZ (÷ EUR rate, ~×0.5 for Czech labour), cross-checked against Czech garage price lists and BOVAG-RAI fuel-level averages.
3. Compared the sourced targets to the computed values and fitted the constants to minimise error, rounding to clean multipliers.

Result: **MAPE ≈ 21 %, mean bias ≈ 1.00** (vs the original guessed constants: MAPE ≈ 26 %, ~14 % systematically low). Key corrections learned from the data:
- ICE base was ~40 % too low — the original 9 000 tracked "service-visit only", the sourced scope is servicing **+ wear/repairs reserve**.
- The real premium-over-mainstream gap is **~1.25×**, far less than the guessed 1.45× (ADAC shows a BMW X3 ≈ a VW Golf; Teslas are cheap to service despite being "premium").
- EVs are ~right in absolute terms, so the BEV factor dropped 0.45 → 0.35 to keep EV output flat while the base rose.
- Diesel/hybrid are ~= petrol in the data (not the guessed +20 %).

**Residual scatter is irreducible and expected.** The sourced targets are themselves bimodal (CZ-grounded figures like Fabia ≈ 8.5k sit well below pure-ADAC-scaled ones like Octavia ≈ 18k), and ADAC per-model data carries real model-specific noise (~2× within a class) that a 4-factor formula cannot and should not chase. Two of the 20 (Volvo XC40, Peugeot 208) came from a lower-scope source (inspection-only) and were excluded from the fit; the calibrated formula's values for them are likely closer to truth than those understated targets. This remains an **estimate** — the honest framing carried by the "odhad" labelling.

## Architecture / components

One pure helper + one applier, both in `build/build_data.py`, mirroring `reliability_score` / `add_reliability_column`:

1. **`service_cost(typ, palivo, hybrid_typ, znacka, karoserie, objem_motoru) -> (value:str, clamped:bool)`**
   Pure. Returns the rounded/clamped Kč value as a string (`""` when no fuel signal) plus a `clamped` boolean. Factor maps are module-level constants (`SERVICE_*`).
2. **`add_service_cost_column(df) -> df`**
   Inserts `Servis (Kč/rok)` into the payload right after `Spolehlivost` (both computed display columns). Computes per-row from the row's own columns → full coverage for EV + ICE listings. Also records the clamped set for the overview count.
   - Called in `write_payload()` alongside `add_reliability_column` / `add_transmission_type_column`.
   - Registered in `PAYLOAD_NUMERIC_COLS` (float64 — hyparquet BigInt gotcha).
3. **`build_reference_json()`** — compute the same value per reference row from its reference columns (Palivo/Hybrid typ derived, Značka, Karoserie, Objem motoru) and add `Servis (Kč/rok)` to both ICE and EV records; count reference rows that clamp.
4. **`cars-meta.json`** — add a `serviceCost` block: the methodology text (Czech), the factor table, the source links, and the two clamp counts (listings + reference rows out of range). Rendered by the dashboard "Přehled datasetu" overview.

The formula is **not** touched by `matching.py` (it is display-only, like `Cd`).

## Data flow

```
build_data.write_payload():
   add_reliability_column → add_service_cost_column(df)   # per-listing, own columns
   → Servis (Kč/rok) in payload (float64), clamp set recorded
build_data.build_reference_json():
   per ref row → service_cost(...) → "Servis (Kč/rok)" in ICE + EV records
build_data.write_payload()/meta:
   cars-meta.json.serviceCost = {methodology, factors, sources, clampedListings, clampedRefs}
site/app.js:           new numeric column (heat, lower=better) + tooltip
site/reference.js:     new numeric column + tooltip + out-of-range badge on clamped rows
site/app.js overview:  "Servisní náklady (odhad)" methodology card in Přehled datasetu
```

## UI

- **Main grid** (`site/app.js` COL_CONFIG): `{ field:"Servis (Kč/rok)", num:true, hi:false, filter:"agNumberColumnFilter" }` — heat-mapped, **lower = better**, range-slider filter (like `Cd`). Header e.g. `Servis\n(Kč/rok)`. Tooltip: scope + formula summary + "odhad".
- **Reference page** (`site/reference.js` COL_DEFS): same numeric column + tooltip. A small **out-of-range badge** (⚠) on rows whose estimate hit the clamp, styled like the existing missing-spec badge; count also shown in the overview. **Not** added to `ICE_KEY_SPECS`/`EV_KEY_SPECS` (never blank → not a missing-spec case).
- **Přehled datasetu overview** (index): a "Servisní náklady (odhad)" card — one-paragraph methodology, the factor table, the out-of-range counts, and source links:
  - [ADAC Autokosten](https://www.adac.de/rund-ums-fahrzeug/) — per-model Werkstattkosten (relative brand/segment ordering).
  - [ADAC Pannenstatistik (Gelbe Engel / "Yellow Angels")](https://www.adac.de/rund-ums-fahrzeug/unfall-schaden-panne/adac-pannenstatistik-2026/) — breakdown/reliability context.
  - [BOVAG-RAI Aftersales Monitor 2024](https://mijn.bovag.nl/actueel/nieuws/aftersales-monitor-2024-minder-onderhoudsmomenten-hogere-kosten) — fuel-level averages (EV €332, PHEV €598, avg €743/yr; EV ≈ 60 % below ICE) → the FUEL ratios.
  - A Czech servis-cost reference (driveto.cz / autozive) — the Octavia ≈ 8–10k Kč/rok base anchor.

## Error handling

- No fuel signal → blank value, `clamped=False`. Never fabricate.
- Unknown brand → mainstream tier (documented default, not an error).
- Missing/garbage `Objem motoru` → ENGINE `1.00` (binned, so cannot explode magnitude).
- Clamp is defensive; any clamp fire is surfaced (badge + count), never silent.

## Testing (TDD)

- **`tests/test_build_data.py::ServiceCostTest`** — truth table: each FUEL base, TIER/SEGMENT/ENGINE multipliers, EV path, PHEV, rounding to 500, clamp low/high, blank on missing fuel, and the `clamped` flag. Positional-insert test (`Servis (Kč/rok)` immediately after `Spolehlivost`).
- **`tests/test_data_integrity.py`** — range `[3 000, 60 000]` for every non-blank value; EV mean < ICE mean (fuel factor sanity); `Servis (Kč/rok)` is float64 in both payloads (`test_no_int64_columns…` covers it via `PAYLOAD_NUMERIC_COLS`); every EV + ICE row with a known fuel is scored; clamp counts in `cars-meta.json` are ints ≥ 0.
- **`tests/test_data_integrity.py::test_meta_sidecar_keys`** — extend the pinned key-set with `serviceCost`.
- **UI:** `build/verify_ui.py` — grid (column renders, heat colours) dark + light; reference (column + out-of-range badge); overview scenario (methodology card + source links). Read the screenshots.

## Out of scope (YAGNI)

- Per-model real (`reálné`) values via AI research — the deferred Approach B; a later task can add a CSV override column + `reálné` flag that overrides the estimate.
- Mileage-sensitivity of the annual cost (BOVAG shows it) — the column is a per-model figure, not per-listing-mileage.
- Insurance / depreciation / fuel (a full TCO) — different feature.
