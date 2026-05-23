# CLAUDE.md

This file gives AI coding assistants (Claude, Copilot, etc.) essential context about this project.

## Project Overview

Python web scrapers collecting Czech car listings, exported to CSV. Two suites: **electric** and **combustion**.

### Electric (3 scrapers)

| Site | Script | Output |
|------|--------|--------|
| [autodraft.cz](https://www.autodraft.cz) | `electric/src/scrape_autodraft.py` | `electric/data/scrapes/autodraft.csv` |
| [energycars.cz](https://www.energycars.cz) | `electric/src/scrape_energycars.py` | `electric/data/scrapes/energycars.csv` |
| [sauto.cz](https://www.sauto.cz) | `electric/src/scrape_sauto.py` | `electric/data/scrapes/sauto.csv` |

### Combustion (2 scrapers)

| Site | Script | Output |
|------|--------|--------|
| [autodraft.cz](https://www.autodraft.cz) | `combustion/src/scrape_autodraft.py` | `combustion/data/scrapes/autodraft.csv` |
| [sauto.cz](https://www.sauto.cz) | `combustion/src/scrape_sauto.py` | `combustion/data/scrapes/sauto.csv` |

## Documentation

Read these before making changes:

- @docs/architecture.md — system design, data flow, scraper comparison
- @docs/conventions.md — code style, async patterns, rules
- @docs/gotchas.md — non-obvious behaviors; **update this file whenever you discover something surprising**

## Running the Scrapers

```bash
./bin/run_all.sh                       # Both suites (default --all)
./bin/run_all.sh --electric            # Electric only
./bin/run_all.sh --combustion          # Combustion only
./electric/bin/run_scraper.sh          # Electric suite directly
./combustion/bin/run_scraper.sh        # Combustion suite directly
# Debug single scraper:
cd electric/src && python3 scrape_autodraft.py
cd combustion/src && python3 scrape_sauto.py
```

## Quick Reference

**Add brand alias** → `BRAND_MAP` in `electric/src/utils.py` and `combustion/src/utils.py`

**Add column** → extraction logic in scraper + `{suite}/data/scrape-data-cols.txt` + DataFrame key

**Adjust energycars concurrency** → `DETAIL_CONCURRENCY` in `electric/src/scrape_energycars.py`

## CSV Schema

### Electric (12 columns)

Defined in `electric/data/scrape-data-cols.txt`.

```text
Model auta | Cena (Kč) | Nájezd (km) | Výkon (kW) | Rok výroby
Tepelné čerpadlo | Kola | Náhon 4x4 | Extra | Stav | Zdroj | Odkaz na auto
```

### Combustion (19 columns)

Defined in `combustion/data/scrape-data-cols.txt`.

```text
Model auta | Cena (Kč) | Nájezd (km) | Výkon (kW) | Rok výroby
Palivo | Převodovka | Kola | Náhon 4x4 | Extra
Objem motoru | Typ motoru | Hybrid typ | Karoserie | Výbava | Záruka
Stav | Zdroj | Odkaz na auto
```

Status values (`Stav`): `Dostupný` · `Chystá se` · `Zamluvené` · `Prodané` · *(blank for energycars)*

## Dependencies

```bash
pip install playwright pandas beautifulsoup4 aiohttp
playwright install chromium
```
