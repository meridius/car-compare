# Architecture

## Overview

One fuel-agnostic scraper suite (`scrapers/`) collects Czech car listings and writes one CSV per source. A shared `core/` holds all cross-source logic; each `sources/` adapter knows only how to fetch and parse its site into canonical rows. Every row carries a `Typ` column (`Elektrické` / `Spalovací`).

```text
scrapers/
  core/
    schema.py     CANONICAL_COLS (26), TYP_EV/TYP_ICE, blank_row()
    normalize.py  BRAND_MAP, MODEL_CLEANUP_PATTERNS, normalize_model()
    fields.py     ICE field extraction (engine vol/type, hybrid, body, trim, DCT, GPF, AWD, clean_extra)
    matching.py   load_authoritative_list(), match_to_authoritative() — ICE auth matching
    merge.py      merge_with_previous() — preserves removed listings, stamps
                  "Odstraněno dne", drops removed rows past 60-day retention
    storage.py    read_state()/write_state() — parquet state, seed-CSV fallback
    http.py       aiohttp helpers, fetch_all_details(concurrency=20)  (sauto)
    browser.py    Playwright helpers (autodraft, energycars)
    pipeline.py   run_source(): dedup → ICE auth-match → merge → write parquet state
  sources/
    sauto.py      EV + ICE, aiohttp REST API     → data/scrapes/sauto.parquet
    autodraft.py  EV + ICE, Playwright           → data/scrapes/autodraft.parquet
    energycars.py EV only, Playwright listing→detail → data/scrapes/energycars.parquet
    mobilede.py   EV + ICE (incl. DE), aiohttp app JSON API → data/scrapes/mobilede.parquet
  run.py          CLI: python -m scrapers.run [--source NAME ...]
  data/
    scrapes/      per-source parquet state (git-ignored; frozen seed CSVs tracked)
    seed/         scrape_history.json bootstrap copy
    reference/
      ice_specs.csv   ICE reference — structured cols (Značka,Model,Výbava,Generace,
                      Karoserie,Počet míst,Objem motoru,Typ motoru,Palivo,Hybrid typ,
                      Spotřeba,Objem kufru,Hlučnost,Cd,Cd zdroj); PK = Jednoznačná
                      varianta vozu (clean, paren-free); exact join on "Model auta"
      ev_specs.csv    EV reference (comma-delim; Model auta,Karoserie,…,Cd,Cd zdroj,
                      Tepelné čerpadlo možné); prefix-match join. Karoserie is the
                      curated per-nameplate body driven onto matched EV rows.

bin/run_all.sh    dep check (once) + fan out `python -m scrapers.run --source NAME` per source in parallel
build/build_data.py  concat states + per-fuel reference enrichment → site/data/cars.parquet (+ cars-meta.json)
```

Each adapter exposes `SOURCE_NAME`, `SOURCE_SLUG`, `FUELS`, and an async `scrape()` returning canonical rows.

## Data Flow

```text
source.scrape()  → canonical rows (27-col dicts)
pipeline.run_source():
   DataFrame(rows, columns=CANONICAL_COLS)
   → drop_duplicates(subset="Odkaz na auto")
   → match_to_authoritative() on ICE rows only (EV untouched)
   → merge_with_previous()  (stamp vanished listings "Odstraněno" + "Odstraněno dne",
                             drop removed rows older than 60 days)
   → storage.write_state() → data/scrapes/<slug>.parquet
build/build_data.py:
   storage.read_state() per source (parquet, seed-CSV fallback) + concat
   → re-match ICE against ice_specs.csv (rewrites "Model auta")
   → per-fuel reference enrichment by Typ (ICE: ice_specs.csv, EV: ev_specs.csv)
   → site/data/cars.parquet (snappy, numeric cols float64) + cars-meta.json
```

State is **merged incrementally**: listings in the old state but absent from the
new scrape get `Stav = "Odstraněno"` + a date stamp and are kept for 60 days
(`REMOVED_RETENTION_DAYS`); monthly snapshot releases keep them forever. New data
always wins. See gotchas for `merge_with_previous` behaviour.

## Storage & Delivery (decision 001)

- **State layer**: `scrapers/data/scrapes/<slug>.parquet`, stringly-typed (every
  column str, blanks "") for exact parity with the old CSV semantics. Git-ignored.
- **Canonical store**: rolling GitHub Release `data` (assets clobbered daily) +
  immutable monthly `data-YYYY-MM` snapshots. Bootstrap falls back to the frozen
  seed CSVs tracked in git.
- **Payload**: `site/data/cars.parquet` (snappy — hyparquet decodes it natively)
  + `cars-meta.json` sidecar; shipped only inside the Pages deploy artifact.
  At 141k rows: 129 MB JSON → ~8 MB parquet, browser decode 9 s → ~1.5 s.
- **Dashboard**: AG Grid Community clientSideRowModel unchanged; `app.js` decodes
  the parquet with hyparquet (pinned jsDelivr ESM) and feeds the same row objects.

## Source Comparison

| Source     | Fuels    | Tech                  | Concurrency                              | Notes                                  |
| ---------- | -------- | --------------------- | ---------------------------------------- | -------------------------------------- |
| sauto      | EV + ICE | `aiohttp` (REST API)  | `fetch_all_details(concurrency=20)`      | No browser; pre-filtered at API level  |
| autodraft  | EV + ICE | Playwright (Chromium) | single page, sequential                  | EV + benzin + diesel + "na cestě" URLs |
| energycars | EV only  | Playwright (Chromium) | `DETAIL_CONCURRENCY = 5` detail pages     | Listing page → detail page per car     |
| mobilede   | EV + ICE | `aiohttp` (app JSON)  | `CONCURRENCY = 3`, price-band slices      | Keyless app endpoint; EUR→Kč via CNB; EV + ICE: CZ/SK/AT/PL/DE (decision 001 enabled DE ICE) |

## Column Schema

One canonical 26-column schema (`scrapers/core/schema.py` → `CANONICAL_COLS`):

```text
Typ, Model auta, Cena (Kč), Nájezd (km), Rok výroby,
Palivo, Objem motoru, Typ motoru, Hybrid typ, Výkon (kW),
Převodovka, Dvouspojková převodovka, Filtr pevných částic,
Kola, Náhon 4x4, Karoserie, Výbava, Záruka, Tepelné čerpadlo,
Spárováno, Skóre shody, Extra, Stav, Země, Zdroj, Odkaz na auto
```

`Země` (country of the seller) is the only column that varies by country: the three
CZ-only sources always emit `Česko`; mobile.de maps `attr.cn` (ISO code) to the Czech
country name. `build_data.backfill_country()` fills any blank `Země` on a non-mobile.de
row with `Česko`, so CSVs written before the column existed still display correctly.

EV rows leave the ICE-only columns blank (Palivo, Objem motoru, Typ motoru, Hybrid typ, Převodovka, Dvouspojková převodovka, Filtr pevných částic, Výbava, Záruka). ICE rows leave `Tepelné čerpadlo` blank. `blank_row()` seeds every column to `""`.

## Normalisation Pipeline

Applied in `core/normalize.normalize_model()`, in order:

1. `BRAND_MAP` — brand aliases (e.g. `"Volkswagen" → "VW"`)
2. `MODEL_CLEANUP_PATTERNS` — regex fixups (Enyaq bare variant → `iV NN`; Cee´d → Ceed; X-Perience / Combi ordering)

Order matters: a pattern expecting a short brand name (`"VW"`) fails if run before BRAND_MAP expansion.

## Field Extraction Pipeline (ICE)

After base parsing, `core/fields.py` helpers parse Extra/suffix text into dedicated columns:

1. `extract_engine_volume()` / `extract_engine_volume_from_model()` — displacement (1.5, 2.0)
2. `extract_engine_type()` — engine tech (TSI, TDI, EcoBoost, …); `strip_engine_from_model()` removes it from the model name
3. `extract_hybrid_type()` — MHEV/HEV/PHEV classification
4. `extract_body_type()` — body style (Combi, SUV, Fastback, …)
5. `extract_trim()` — trim level (Style, R-Line, Monte Carlo, …)
6. `extract_warranty()` — warranty mention (Ano / blank)
7. `extract_dct()` — dual-clutch transmission (DSG, DCT, S-tronic, PDK, …)
8. `extract_particle_filter()` — GPF/DPF detection (Ano / blank)
9. `extract_awd()` — 4x4/AWD from Extra text
10. `clean_extra()` — strips extracted substrings from Extra text

Extraction must run **before** `clean_extra()`.

## Authoritative Model Matching (ICE)

Each ICE car is matched against `scrapers/data/reference/ice_specs.csv` (`core/matching.py`):

1. `load_authoritative_list(csv_path)` — reads the **structured feature columns** directly (Značka, Model, Karoserie, Objem motoru, Typ motoru, Palivo, Hybrid typ, Výbava). It does **not** parse the display name — the name (`Jednoznačná varianta vozu`) is the entry/PK only. (Reference CSV is now column-structured; the old name-parsing auth helpers were deleted.)
2. `match_to_authoritative(df, auth_list)` — for each row:
    - Parse brand + model_base from the **scraped** "Model auta" (listings still arrive as messy strings; only the auth side is pre-structured)
    - Find candidates: brand must match (with `_BRAND_MATCH_ALIASES` for SsangYong↔KGM) AND model_base must match
    - Score candidates by weighted multi-field matching: body(3), hybrid(3), engine_vol(2), engine_type(2), trim/Výbava(2), fuel(1) — trim disambiguates kept trim variants (Octavia Style vs Selection)
    - Classify via `classify_match()` into tri-state `Spárováno` + numeric `Skóre shody`:
        - **Ano** (confident: best score ≥ `STRONG_FLOOR` and beats runner-up by ≥ `MARGIN_REQ`) → "Model auta" set to full auth string (e.g. "Škoda Karoq 1.5 TSI")
        - **Nejisté** (candidate found but weak/contradictory/tie) → best-guess auth string written, flagged uncertain
        - **Ne** (no candidate) → reformatted as "Brand Model EngVol EngType" via `_format_unmatched()`

Body types use synonym groups (`_BODY_GROUPS`): Kombi↔Combi↔Variant↔SW↔Avant↔Touring.

## EV vs ICE Matching Asymmetry

- **ICE**: matched twice. At scrape time (`pipeline.run_source` → `match_to_authoritative` against `ice_specs.csv`) and again in `build_data.py` (re-match the concatenated dataset). Matching **rewrites "Model auta"** to the canonical reference string.
- **EV**: not matched at scrape time. Enriched only in `build_data.py` via a **prefix join** against `ev_specs.csv` (adds spec columns; does not rewrite the model name).

### Reference-driven body / specs (not per-listing)

Both fuels take **`Karoserie`** from the matched reference, not the noisy
per-listing value: confidently-matched ICE (`apply_reference_body_specs`, from
the auth entry's raw body; also `Objem motoru`/`Typ motoru`/`Hybrid typ` on Ano
rows) and matched EV (`join_electric_reference`, from `ev_specs.csv`'s hand-kept
`Karoserie` column, overwriting). The whole column is then folded onto a
canonical display vocabulary (`canonicalize_body_vocab` — the liftback family
collapses into Hatchback because the reference labels it inconsistently), and a
majority-vote (`canonicalize_body`) + `derive_body` fill whatever the reference
can't reach (unmatched/uncertain rows). See gotchas → build for the full order
and the "same car → one body" invariant.

## Hard Filters (single source of truth)

The shared numeric thresholds both API scrapers enforce live in
`scrapers/core/filters.py` (`MIN_YEAR`, `MAX_MILEAGE_KM`, `MIN_PRICE_KC`,
`MAX_PRICE_KC`, `MIN_POWER_KW_ICE`, `MIN_SEATS`). The adapters import them (no
literals), and `filters.SOURCE_FILTERS` — a human-readable per-source
description built *from* those constants — is emitted into
`cars-meta.json.filters` by `build_data` and rendered in the dashboard's
"Přehled dat" overview ("Kritéria výběru dat" card). Change a threshold once;
adapter query, dashboard text, and `tests/test_filters.py` move together.
autodraft/energycars scrape a curated dealer inventory whole — no numeric filter.

## sauto API Filters

Hard-coded in `scrapers/sources/sauto.py`, thresholds from `core/filters.py`.
Shared `_BASE_PARAMS`, then per-fuel:

`_BASE_PARAMS`: `price_to` 750 000 Kč · `vehicle_age_from` 2021 · `tachometer_to` 150 000 km · `capacity_from` 4 seats · `door_from` 5 doors · `category_id` 838 (passenger) · `operating_lease` false.

- **EV** (`EV_PARAMS`): `fuel_seo` `elektro` + `equipment_seo` `tepelne-cerpadlo` (heat pump required).
- **ICE** (`ICE_PARAMS`): `fuel_seo` `benzin,nafta,lpg-benzin,cng-benzin` · `engine_power_from` 100 kW · `condition_seo` `nove,ojete,predvadeci` · `typ_seo` `cuv,kombi,suv,hatchback,mpv`.

The result is a **pre-screened subset**, not all listings.

## mobile.de API Filters

Hard-coded in `scrapers/sources/mobilede.py`, mirroring sauto where the app API allows.
Shared `_BASE_PARAMS`: `fr` 2021: · `ml` :150000 km · `sc` 4: seats · `door`
FOUR_OR_FIVE · `dam` false (no damaged cars) · price band `p` 0:⌈750 000 Kč / CNB
rate⌉ EUR. Repeated params are OR (`ft`, `cn`).

- **EV** (`EV_FUELS`): `ft=ELECTRICITY`, countries CZ SK AT PL **DE**.
- **ICE** (`ICE_FUELS`): `ft=PETROL,DIESEL,HYBRID,HYBRID_DIESEL` (include-only — the
  API has no exclude operator, so LPG/CNG/hydrogen simply aren't requested) +
  `pw=100:` kW, countries CZ SK AT PL **DE** (decision 001 enabled DE ICE — ~123k
  DE results at ≥ 100 kW, the bulk of the dataset; `ICE_COUNTRIES` is the knob).

Any query is capped at 2000 reachable results; `_fetch_banded()` recursively halves
the EUR price band until every slice fits, then pages with `psz=100`/`ps`. Prices are
converted to Kč with the CNB daily fixing (fallback 24.5) and re-checked against the
100 000–750 000 Kč window; only `price.type == "FIXED"` gross prices are accepted.
