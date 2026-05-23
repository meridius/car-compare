# Architecture

## Overview

Two scraper suites — **electric** and **combustion** — collect Czech car listings and write CSVs. Each suite has its own `utils.py` (brand normalisation).

```text
electric/
  src/
    scrape_autodraft.py   → data/scrapes/autodraft.csv
    scrape_energycars.py  → data/scrapes/energycars.csv
    scrape_sauto.py       → data/scrapes/sauto.csv
    utils.py              (shared: BRAND_MAP, MODEL_CLEANUP_PATTERNS, normalize_model)
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
HTTP/browser → raw HTML/JSON → BeautifulSoup/JSON parse → normalize_model() → DataFrame → CSV (overwrite)
```

All CSVs are **overwritten on every run**. No incremental/append mode.

## Scraper Comparison

| Scraper | Suite | Tech | Concurrency | Notes |
|---------|-------|------|-------------|-------|
| autodraft | electric + combustion | Playwright (Chromium) | single page, sequential | Two/three URLs depending on suite |
| energycars | electric only | Playwright (Chromium) | `DETAIL_CONCURRENCY = 5` detail pages | Listing page → detail page per car |
| sauto | electric + combustion | `aiohttp` (REST API) | `DETAIL_CONCURRENCY = 20` | No browser; pre-filtered at API level |

## Column Differences

| Column | Electric | Combustion |
|--------|----------|------------|
| Tepelné čerpadlo | yes | — |
| Palivo | — | yes |
| Převodovka | — | yes |

Electric: 12 columns. Combustion: 13 columns.

## Normalisation Pipeline

Applied in `utils.normalize_model()`, in order:

1. `BRAND_MAP` — brand aliases (e.g. `"Volkswagen" → "VW"`)
2. `MODEL_CLEANUP_PATTERNS` — regex fixups (electric only: Enyaq bare variant → `iV NN`; combustion: empty list)

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
