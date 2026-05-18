# CLAUDE.md

This file gives AI coding assistants (Claude, Copilot, etc.) essential context about this project.

## Project Overview

A pair of Python web scrapers that collect electric-car listings from two Czech automotive sites and export the results to CSV files for comparison.

| Site | Script | Output |
|------|--------|--------|
| [autodraft.cz](https://www.autodraft.cz) | `scrape_autodraft.py` | `autodraft.csv` |
| [energycars.cz](https://www.energycars.cz) | `scrape_energycars.py` | `energycars.csv` |

## Repository Structure

```text
.
├── scrape_autodraft.py   # Scraper for autodraft.cz (available + on-the-way cars)
├── scrape_energycars.py  # Scraper for energycars.cz (with per-listing detail pages)
├── utils.py              # Shared helpers (brand normalisation, BRAND_MAP)
├── run_scraper.sh        # Entry point: checks deps, installs if needed, runs both scrapers
├── cols.txt              # Canonical column order for both output CSVs
├── autodraft.csv         # Generated output – do not edit manually
└── energycars.csv        # Generated output – do not edit manually
```

## CSV Schema (`cols.txt`)

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
./run_scraper.sh          # Recommended: handles dep checks automatically
# or individually:
python3 scrape_autodraft.py
python3 scrape_energycars.py
```

The shell script:

1. Verifies `playwright`, `pandas`, and `beautifulsoup4` are importable.
2. Checks that the Playwright Chromium binary exists; installs it if not.
3. Runs both scrapers sequentially.

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
Edit `BRAND_MAP` in `utils.py`.

**Add a new column**

1. Add extraction logic in the relevant scraper.
2. Add the column name to `cols.txt` in the desired position.
3. Ensure the DataFrame construction in that scraper includes the new key.

**Adjust concurrency for energycars detail pages**
Change `DETAIL_CONCURRENCY` at the top of `scrape_energycars.py`.
