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
| Objem motoru | — | yes |
| Typ motoru | — | yes |
| Hybrid typ | — | yes |
| Karoserie | — | yes |
| Výbava | — | yes |
| Záruka | — | yes |

| Dvouspojková převodovka | — | yes |
| Filtr pevných částic | — | yes |

Electric: 12 columns. Combustion: 21 columns.

## Column Order (combustion)

```text
Model auta, Cena (Kč), Nájezd (km), Výkon (kW), Rok výroby,
Palivo, Převodovka, Kola, Náhon 4x4,
Objem motoru, Typ motoru, Hybrid typ, Karoserie, Výbava, Záruka,
Dvouspojková převodovka, Filtr pevných částic,
Stav, Extra, Zdroj, Odkaz na auto
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
