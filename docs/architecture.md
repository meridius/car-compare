# Architecture

## Overview

Two scraper suites — **electric** and **combustion** — collect Czech car listings and write CSVs. Each suite has its own `utils.py` (brand normalisation).

```text
electric/
  src/
    scrape_autodraft.py   → data/scrapes/autodraft.csv
    scrape_energycars.py  → data/scrapes/energycars.csv
    scrape_sauto.py       → data/scrapes/sauto.csv
    utils.py              (shared: BRAND_MAP, MODEL_CLEANUP_PATTERNS, normalize_model, merge_with_previous)
  data/
    makes-and-models/current.txt   tracked models
    makes-and-models/new.txt       newly added models
    new_cars_specs.csv             specs for new models
    scrape-data-cols.txt           canonical CSV column order (12 cols)
  bin/run_scraper.sh               entry point (dep check + parallel run)

combustion/
  src/
    scrape_autodraft.py   → data/scrapes/autodraft.csv
    scrape_sauto.py       → data/scrapes/sauto.csv
    utils.py              (shared: BRAND_MAP, normalize_model — no cleanup patterns)
  data/
    scrape-data-cols.txt           canonical CSV column order (13 cols)
  bin/run_scraper.sh               entry point (dep check + parallel run)

bin/run_all.sh                     global runner (--electric, --combustion, --all)
```

## Data Flow

```text
HTTP/browser → raw HTML/JSON → BeautifulSoup/JSON parse → normalize_model() → DataFrame → merge_with_previous() → CSV
```

CSVs are **merged incrementally**: new scraped data is combined with the previous CSV. Listings present in the old CSV but absent from the new scrape get their `Stav` set to `"Odstraněno"`. New listings always take priority (via `keep="first"` dedup).

## Scraper Comparison

| Scraper    | Suite                 | Tech                  | Concurrency                           | Notes                                 |
| ---------- | --------------------- | --------------------- | ------------------------------------- | ------------------------------------- |
| autodraft  | electric + combustion | Playwright (Chromium) | single page, sequential               | Two/three URLs depending on suite     |
| energycars | electric only         | Playwright (Chromium) | `DETAIL_CONCURRENCY = 5` detail pages | Listing page → detail page per car    |
| sauto      | electric + combustion | `aiohttp` (REST API)  | `DETAIL_CONCURRENCY = 20`             | No browser; pre-filtered at API level |

## Column Differences

| Column                  | Electric | Combustion |
| ----------------------- | -------- | ---------- |
| Tepelné čerpadlo        | yes      | —          |
| Palivo                  | —        | yes        |
| Převodovka              | —        | yes        |
| Objem motoru            | —        | yes        |
| Typ motoru              | —        | yes        |
| Hybrid typ              | —        | yes        |
| Karoserie               | —        | yes        |
| Karoserie               | yes      | yes        |
| Výbava                  | —        | yes        |
| Záruka                  | —        | yes        |
| Dvouspojková převodovka | —        | yes        |
| Filtr pevných částic    | —        | yes        |

Electric: 13 columns. Combustion: 21 columns.

## Column Order (combustion)

```text
Model auta, Cena (Kč), Nájezd (km), Rok výroby,
Palivo, Objem motoru, Typ motoru, Hybrid typ,
Výkon (kW), Převodovka, Dvouspojková převodovka, Filtr pevných částic,
Kola, Náhon 4x4, Karoserie, Výbava, Záruka,
Extra, Stav, Zdroj, Odkaz na auto
```

## Normalisation Pipeline

Applied in `utils.normalize_model()`, in order:

1. `BRAND_MAP` — brand aliases (e.g. `"Volkswagen" → "VW"`)
2. `MODEL_CLEANUP_PATTERNS` — regex fixups (electric: Enyaq bare variant → `iV NN`; combustion: X-Perience, Combi ordering)

## Field Extraction Pipeline (combustion only)

After the base scrape, `utils.py` extraction helpers parse Extra/suffix text into dedicated columns:

1. `extract_engine_volume()` — displacement (1.5, 2.0)
2. `extract_engine_type()` — engine tech (TSI, TDI, EcoBoost, …)
3. `extract_hybrid_type()` — MHEV/HEV/PHEV classification
4. `extract_body_type()` — body style (Combi, SUV, Fastback, …)
5. `extract_trim()` — trim level (Style, R-Line, Monte Carlo, …)
6. `extract_warranty()` — warranty mention (Ano / blank)
7. `extract_dct()` — dual-clutch transmission (DSG, DCT, S-tronic, PDK, …)
8. `extract_particle_filter()` — GPF/DPF detection (Ano / blank)
9. `extract_awd()` — 4x4/AWD from Extra text (supplements API-level detection)
10. `clean_extra()` — strips extracted substrings from Extra text

## Authoritative Model Matching (combustion only)

After field extraction, each scraped car is matched against `combustion/data/makes-and-models.csv`:

1. `load_authoritative_list(csv_path)` — parses auth CSV into structured records (brand, model_base, body, engine_vol, engine_type, hybrid, fuel)
2. `match_to_authoritative(df, auth_list)` — for each row:
    - Parse brand + model_base from "Model auta"
    - Find candidates: brand must match (with `_BRAND_MATCH_ALIASES` for SsangYong↔KGM) AND model_base must match
    - Score candidates using weighted multi-field matching: body(3), engine_vol(2), engine_type(2), hybrid(3), fuel(1)
    - **Matched** → "Model auta" set to full auth string (e.g. "Škoda Karoq 1.5 TSI")
    - **Unmatched** → reformatted as "Brand Model EngVol EngType"

Body types use synonym groups (`_BODY_GROUPS`): Kombi↔Combi↔Variant↔SW↔Avant↔Touring.

## sauto API Filters

### Electric

Hard-coded in `SEARCH_PARAMS` (electric/src/scrape_sauto.py):

- `price_to`: 750 000 Kč
- `vehicle_age_from`: 2021
- `tachometer_to`: 100 000 km
- `capacity_from`: 4 seats, `door_from`: 5 doors
- `equipment_seo`: `tepelne-cerpadlo` (heat pump required)
- `category_id`: 838 (passenger cars)

### Combustion

Hard-coded in `SEARCH_PARAMS` (combustion/src/scrape_sauto.py):

- `price_to`: 750 000 Kč
- `vehicle_age_from`: 2021
- `fuel_seo`: `benzin,nafta,lpg-benzin,cng-benzin`
- `tachometer_to`: 100 000 km
- `capacity_from`: 4 seats, `door_from`: 5 doors
- `condition_seo`: `nove,ojete,predvadeci`
- `category_id`: 838 (passenger cars)

Both produce a **pre-screened subset**, not all listings.
