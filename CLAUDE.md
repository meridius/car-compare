# CLAUDE.md

This file gives AI coding assistants (Claude, Copilot, etc.) essential context about this project.

## Project Overview

Three Python web scrapers collecting Czech electric-car listings, exported to CSV.

| Site | Script | Output |
|------|--------|--------|
| [autodraft.cz](https://www.autodraft.cz) | `electric/src/scrape_autodraft.py` | `electric/data/scrapes/autodraft.csv` |
| [energycars.cz](https://www.energycars.cz) | `electric/src/scrape_energycars.py` | `electric/data/scrapes/energycars.csv` |
| [sauto.cz](https://www.sauto.cz) | `electric/src/scrape_sauto.py` | `electric/data/scrapes/sauto.csv` |

## Documentation

Read these before making changes:

- @docs/architecture.md — system design, data flow, scraper comparison
- @docs/conventions.md — code style, async patterns, rules
- @docs/gotchas.md — non-obvious behaviors; **update this file whenever you discover something surprising**

## Running the Scrapers

```bash
./electric/bin/run_scraper.sh          # Recommended: dep check + parallel run
# Debug single scraper:
cd electric/src && python3 scrape_autodraft.py
```

## Quick Reference

**Add brand alias** → `BRAND_MAP` in `electric/src/utils.py`

**Add column** → extraction logic in scraper + `electric/data/scrape-data-cols.txt` + DataFrame key

**Adjust energycars concurrency** → `DETAIL_CONCURRENCY` in `electric/src/scrape_energycars.py`

## CSV Schema

Canonical column order defined in `electric/data/scrape-data-cols.txt`.

```
Model auta | Cena (Kč) | Nájezd (km) | Výkon (kW) | Rok výroby
Tepelné čerpadlo | Kola | Náhon 4x4 | Extra | Stav | Zdroj | Odkaz na auto
```

Status values (`Stav`): `Dostupný` · `Chystá se` · `Zamluvené` · `Prodané` · *(blank for energycars)*

## Dependencies

```bash
pip install playwright pandas beautifulsoup4 aiohttp
playwright install chromium
```
