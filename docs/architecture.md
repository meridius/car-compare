# Architecture

## Overview

One fuel-agnostic scraper suite (`scrapers/`) collects Czech car listings and writes one CSV per source. A shared `core/` holds all cross-source logic; each `sources/` adapter knows only how to fetch and parse its site into canonical rows. Every row carries a `Typ` column (`Elektrické` / `Spalovací`).

```text
scrapers/
  core/
    schema.py     CANONICAL_COLS (25), TYP_EV/TYP_ICE, blank_row()
    normalize.py  BRAND_MAP, MODEL_CLEANUP_PATTERNS, normalize_model()
    fields.py     ICE field extraction (engine vol/type, hybrid, body, trim, DCT, GPF, AWD, clean_extra)
    matching.py   load_authoritative_list(), match_to_authoritative() — ICE auth matching
    merge.py      merge_with_previous() — preserves removed listings
    http.py       aiohttp helpers, fetch_all_details(concurrency=20)  (sauto)
    browser.py    Playwright helpers (autodraft, energycars)
    pipeline.py   run_source(): dedup → ICE auth-match → merge → write CSV
  sources/
    sauto.py      EV + ICE, aiohttp REST API     → data/scrapes/sauto.csv
    autodraft.py  EV + ICE, Playwright           → data/scrapes/autodraft.csv
    energycars.py EV only, Playwright listing→detail → data/scrapes/energycars.csv
    mobilede.py   EV + ICE, aiohttp app JSON API → data/scrapes/mobilede.csv
  run.py          CLI: python -m scrapers.run [--source NAME ...]
  data/
    scrapes/      per-source output CSVs
    reference/
      ice_specs.csv   ICE reference — structured cols (Značka,Model,Výbava,Generace,
                      Karoserie,Počet míst,Objem motoru,Typ motoru,Palivo,Hybrid typ,
                      Spotřeba,Objem kufru,Hlučnost,Cd,Cd zdroj); PK = Jednoznačná
                      varianta vozu (clean, paren-free); exact join on "Model auta"
      ev_specs.csv    EV reference (comma-delim; …,Cd,Cd zdroj,…); prefix-match join

bin/run_all.sh    dep check (once) + fan out `python -m scrapers.run --source NAME` per source in parallel
build/build_data.py  concat CSVs + per-fuel reference enrichment → site/data/cars.json
```

Each adapter exposes `SOURCE_NAME`, `SOURCE_SLUG`, `FUELS`, and an async `scrape()` returning canonical rows.

## Data Flow

```text
source.scrape()  → canonical rows (25-col dicts)
pipeline.run_source():
   DataFrame(rows, columns=CANONICAL_COLS)
   → drop_duplicates(subset="Odkaz na auto")
   → match_to_authoritative() on ICE rows only (EV untouched)
   → merge_with_previous()  (mark vanished listings "Odstraněno")
   → write data/scrapes/<slug>.csv
build/build_data.py:
   concat all source CSVs
   → re-match ICE against ice_specs.csv (rewrites "Model auta")
   → per-fuel reference enrichment by Typ (ICE: ice_specs.csv, EV: ev_specs.csv)
   → site/data/cars.json
```

CSVs are **merged incrementally**: listings in the old CSV but absent from the new scrape get `Stav = "Odstraněno"` and are kept. New data always wins (`keep="first"` dedup). See gotchas for `merge_with_previous` behaviour (and a known empty-link bug).

## Source Comparison

| Source     | Fuels    | Tech                  | Concurrency                              | Notes                                  |
| ---------- | -------- | --------------------- | ---------------------------------------- | -------------------------------------- |
| sauto      | EV + ICE | `aiohttp` (REST API)  | `fetch_all_details(concurrency=20)`      | No browser; pre-filtered at API level  |
| autodraft  | EV + ICE | Playwright (Chromium) | single page, sequential                  | EV + benzin + diesel + "na cestě" URLs |
| energycars | EV only  | Playwright (Chromium) | `DETAIL_CONCURRENCY = 5` detail pages     | Listing page → detail page per car     |
| mobilede   | EV + ICE | `aiohttp` (app JSON)  | `CONCURRENCY = 5`, price-band slices      | Keyless app endpoint; EUR→Kč via CNB; EV: CZ/SK/AT/PL/DE, ICE: no DE |

## Column Schema

One canonical 25-column schema (`scrapers/core/schema.py` → `CANONICAL_COLS`):

```text
Typ, Model auta, Cena (Kč), Nájezd (km), Rok výroby,
Palivo, Objem motoru, Typ motoru, Hybrid typ, Výkon (kW),
Převodovka, Dvouspojková převodovka, Filtr pevných částic,
Kola, Náhon 4x4, Karoserie, Výbava, Záruka, Tepelné čerpadlo,
Spárováno, Skóre shody, Extra, Stav, Zdroj, Odkaz na auto
```

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

## sauto API Filters

Hard-coded in `scrapers/sources/sauto.py`. Shared `_BASE_PARAMS`, then per-fuel:

`_BASE_PARAMS`: `price_to` 750 000 Kč · `vehicle_age_from` 2021 · `tachometer_to` 100 000 km · `capacity_from` 4 seats · `door_from` 5 doors · `category_id` 838 (passenger) · `operating_lease` false.

- **EV** (`EV_PARAMS`): `fuel_seo` `elektro` + `equipment_seo` `tepelne-cerpadlo` (heat pump required).
- **ICE** (`ICE_PARAMS`): `fuel_seo` `benzin,nafta,lpg-benzin,cng-benzin` · `engine_power_from` 100 kW · `condition_seo` `nove,ojete,predvadeci` · `typ_seo` `cuv,kombi,suv,hatchback,mpv`.

The result is a **pre-screened subset**, not all listings.

## mobile.de API Filters

Hard-coded in `scrapers/sources/mobilede.py`, mirroring sauto where the app API allows.
Shared `_BASE_PARAMS`: `fr` 2021: · `ml` :100000 km · `sc` 4: seats · `door`
FOUR_OR_FIVE · `dam` false (no damaged cars) · price band `p` 0:⌈750 000 Kč / CNB
rate⌉ EUR. Repeated params are OR (`ft`, `cn`).

- **EV** (`EV_FUELS`): `ft=ELECTRICITY`, countries CZ SK AT PL **DE**.
- **ICE** (`ICE_FUELS`): `ft=PETROL,DIESEL,HYBRID,HYBRID_DIESEL` (include-only — the
  API has no exclude operator, so LPG/CNG/hydrogen simply aren't requested) +
  `pw=100:` kW, countries CZ SK AT PL (**no DE** — ~123k results even at ≥ 100 kW;
  `ICE_COUNTRIES` is the knob).

Any query is capped at 2000 reachable results; `_fetch_banded()` recursively halves
the EUR price band until every slice fits, then pages with `psz=100`/`ps`. Prices are
converted to Kč with the CNB daily fixing (fallback 24.5) and re-checked against the
100 000–750 000 Kč window; only `price.type == "FIXED"` gross prices are accepted.
