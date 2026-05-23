# CLAUDE.md

This file gives AI coding assistants (Claude, Copilot, etc.) essential context about this project.

## Project Overview

A trio of Python web scrapers that collect electric-car listings from Czech automotive sites and export the results to CSV files for comparison.

| Site | Script | Output |
|------|--------|--------|
| [autodraft.cz](https://www.autodraft.cz) | `electric/src/scrape_autodraft.py` | `electric/data/scrapes/autodraft.csv` |
| [energycars.cz](https://www.energycars.cz) | `electric/src/scrape_energycars.py` | `electric/data/scrapes/energycars.csv` |
| [sauto.cz](https://www.sauto.cz) | `electric/src/scrape_sauto.py` | `electric/data/scrapes/sauto.csv` |

## Repository Structure

```text
electric/
├── bin/
│   └── run_scraper.sh            # Entry point: checks deps, installs if needed, runs scrapers
├── data/
│   ├── makes-and-models/
│   │   ├── current.txt           # Current tracked makes/models
│   │   └── new.txt               # Newly added makes/models
│   ├── scrapes/
│   │   ├── autodraft.csv         # Generated output – do not edit manually
│   │   ├── energycars.csv        # Generated output – do not edit manually
│   │   └── sauto.csv             # Generated output – do not edit manually
│   ├── new_cars_specs.csv        # Specs for new car models
│   └── scrape-data-cols.txt      # Canonical column order for all output CSVs
└── src/
    ├── scrape_autodraft.py       # Scraper for autodraft.cz (available + on-the-way cars)
    ├── scrape_energycars.py      # Scraper for energycars.cz (with per-listing detail pages)
    ├── scrape_sauto.py           # Scraper for sauto.cz (via API)
    └── utils.py                  # Shared helpers (brand normalisation, BRAND_MAP)
```

## CSV Schema (`electric/data/scrape-data-cols.txt`)

```text
Model auta        # Normalised model name (e.g. "VW ID.4 Pro")
Cena (Kč)         # Price in CZK
Nájezd (km)       # Mileage
Výkon (kW)        # Power output
Rok výroby        # Year of manufacture
Tepelné čerpadlo  # Heat pump: "Ano" / "Ne"
Kola              # Wheel size, e.g. '19"'
Náhon 4x4         # AWD: "Ano" / "Ne"
Extra             # Remaining equipment notes
Stav              # Listing status (see below)
Zdroj             # Source site identifier
Odkaz na auto     # Direct URL to the listing
```

### Status values (`Stav`)

| Value | Meaning |
|-------|---------|
| `Dostupný` | Available now (autodraft) |
| `Chystá se` | Coming soon / on-the-way (autodraft) |
| `Zamluven é` | Reserved / viewing booked (autodraft) |
| `Prodané` | Sold (autodraft) |
| *(blank)* | energycars listings have no status field |

## Running the Scrapers

```bash
./electric/bin/run_scraper.sh          # Recommended: handles dep checks automatically
# or individually (from electric/src/):
cd electric/src
python3 scrape_autodraft.py
python3 scrape_energycars.py
python3 scrape_sauto.py
```

The shell script:

1. Verifies `playwright`, `pandas`, and `beautifulsoup4` are importable.
2. Checks that the Playwright Chromium binary exists; installs it if not.
3. Runs all three scrapers in parallel.

## Dependencies

- Python 3.8+
- `playwright` (async API, Chromium)
- `pandas`
- `beautifulsoup4`

Install manually if needed:

```bash
pip install playwright pandas beautifulsoup4
playwright install chromium
```

## Key Implementation Notes

- Both scrapers use **Playwright** (`async_playwright`) for JavaScript-rendered pages.
- `scrape_energycars.py` opens each listing's detail page concurrently (controlled by `DETAIL_CONCURRENCY = 5`).
- Brand normalisation is centralised in `utils.BRAND_MAP` — add entries there to shorten verbose brand names (e.g. `"Volkswagen" → "VW"`).
- `autodraft.py` parses status keywords from card text via `STATUS_MAP`; the sentinel string `"oceníte na cestách:"` separates model name from spec text.
- Output CSVs are **overwritten** on every run.

## Common Tasks

**Add a brand alias**
Edit `BRAND_MAP` in `electric/src/utils.py`.

**Add a new column**

1. Add extraction logic in the relevant scraper.
2. Add the column name to `electric/data/scrape-data-cols.txt` in the desired position.
3. Ensure the DataFrame construction in that scraper includes the new key.

**Adjust concurrency for energycars detail pages**
Change `DETAIL_CONCURRENCY` at the top of `electric/src/scrape_energycars.py`.
