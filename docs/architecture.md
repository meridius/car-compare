# Architecture

## Overview

Three independent scrapers collect Czech electric-car listings and each writes one CSV. They share only `utils.py` (brand normalisation).

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
    scrape-data-cols.txt           canonical CSV column order
  bin/run_scraper.sh               entry point (dep check + parallel run)
```

## Data Flow

```text
HTTP/browser → raw HTML/JSON → BeautifulSoup/JSON parse → normalize_model() → DataFrame → CSV (overwrite)
```

All CSVs are **overwritten on every run**. No incremental/append mode.

## Scraper Comparison

| Scraper | Tech | Concurrency | Notes |
|---------|------|-------------|-------|
| autodraft | Playwright (Chromium) | single page, sequential | Two URLs: available + on-the-way |
| energycars | Playwright (Chromium) | `DETAIL_CONCURRENCY = 5` detail pages | Listing page → detail page per car |
| sauto | `aiohttp` (REST API) | `DETAIL_CONCURRENCY = 20` | No browser; pre-filtered at API level |

## Normalisation Pipeline

Applied in `utils.normalize_model()`, in order:

1. `BRAND_MAP` — brand aliases (e.g. `"Volkswagen" → "VW"`)
2. `MODEL_CLEANUP_PATTERNS` — regex fixups (e.g. Enyaq bare variant → `iV NN`)

## sauto API Filters

Hard-coded in `SEARCH_PARAMS` (scrape_sauto.py):

- `price_to`: 750 000 Kč
- `vehicle_age_from`: 2021
- `tachometer_to`: 100 000 km
- `capacity_from`: 4 seats, `door_from`: 5 doors
- `equipment_seo`: `tepelne-cerpadlo` (heat pump required)
- `category_id`: 838 (passenger cars)

These filters mean sauto results are a **pre-screened subset**, not all electric listings.
