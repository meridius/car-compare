# CLAUDE.md

This file gives AI coding assistants (Claude, Copilot, etc.) essential context about this project.

## Project Overview

One fuel-agnostic Python scraper suite collecting Czech car listings, exported to CSV. A single unified package (`scrapers/`) with a shared `core/` and one adapter per source. Each row carries a `Typ` column (`Elektrické` / `Spalovací`) — there are no separate electric/combustion trees.

### Sources

| Site                                       | Adapter                          | Fuels    | Output                                    |
| ------------------------------------------ | -------------------------------- | -------- | ----------------------------------------- |
| [sauto.cz](https://www.sauto.cz)           | `scrapers/sources/sauto.py`      | EV + ICE | `scrapers/data/scrapes/sauto.parquet`     |
| [autodraft.cz](https://www.autodraft.cz)   | `scrapers/sources/autodraft.py`  | EV + ICE | `scrapers/data/scrapes/autodraft.parquet` |
| [energycars.cz](https://www.energycars.cz) | `scrapers/sources/energycars.py` | EV       | `scrapers/data/scrapes/energycars.parquet`|
| [mobile.de](https://www.mobile.de)         | `scrapers/sources/mobilede.py`   | EV + ICE | `scrapers/data/scrapes/mobilede.parquet`  |

State parquets are git-ignored; canonical data lives in the rolling GitHub Release
`data` (+ immutable monthly `data-YYYY-MM` snapshots). The tracked CSVs are frozen
bootstrap seeds. mobile.de ICE includes Germany (~133k listings). See
`docs/decisions/001-scalable-storage.md`.

## Documentation

Read these before making changes:

- @docs/architecture.md — system design, data flow, source comparison
- @docs/conventions.md — code style, async patterns, rules
- @docs/gotchas.md — non-obvious behaviors; **update this file whenever you discover something surprising**

## Workflow

- **Feature work goes in a throwaway git worktree.** When asked to work on a feature, create a
  disposable worktree on its own branch (isolated from the main checkout) and work there — do not
  branch in place. Tear it down when the work has landed.
- **Do not create pull requests unless explicitly asked.** Default to committing on the local
  feature branch. Never push or open a PR on your own initiative — only when the user requests it.
- **Merging the current branch = squash + rebase + fast-forward (no PR).** When asked to merge the
  current branch into `main`, run exactly this sequence:
  1. **Squash** the whole branch into one commit and **write the commit message yourself** from the
     branch's diff (Conventional Commits, summarise the actual change):
     `git reset --soft "$(git merge-base HEAD origin/main)" && git commit` (interactive rebase is
     unavailable in this environment — use `reset --soft` to the fork point).
  2. **Rebase the branch** onto the latest remote: `git fetch origin && git rebase origin/main`.
  3. **Rebase local `main` onto `origin/main`** (fast-forward it to the remote):
     `git checkout main && git rebase origin/main`.
  4. **Fast-forward `main` to the branch**: `git merge --ff-only <feature-branch>`.

  The result is a linear `main` with a single squashed commit on top of `origin/main`. Pushing
  `main` afterwards is still gated on an explicit request.

## Running the Scrapers

```bash
./bin/run_all.sh                       # All sources (dep check + run)
./bin/run_all.sh --source sauto        # One source (repeat --source to add more)
python -m scrapers.run                 # All sources, no dep check
python -m scrapers.run --source sauto  # Debug a single source
```

Sources: `sauto`, `autodraft`, `energycars`, `mobilede`.

`./bin/bootstrap-data.sh` pulls the current state + payload from the `data` release
(needs `gh` auth; without it the frozen seed CSVs cover local dev).

## Testing

```bash
./bin/test.sh            # offline: matching golden tests + data-integrity invariants (<1s)
```

Every feature is **test-driven / test-verified** — `./bin/test.sh` must pass, and any logic change adds a test that fails without it. Fast offline loop for logic/build/UI work: `python build/build_data.py` (~9s) + `./bin/test.sh`; only `scrapers/sources/*.py` changes need a real scrape. See @docs/conventions.md → Testing.

## Quick Reference

**Add brand alias** → `BRAND_MAP` in `scrapers/core/normalize.py`

**Add column** → `CANONICAL_COLS` in `scrapers/core/schema.py` + populate it in the relevant adapter (`scrapers/sources/*.py`)

**Field extraction** (engine vol/type, hybrid, body, trim, DCT, GPF, AWD, clean_extra) → `scrapers/core/fields.py`

**Authoritative model matching** (ICE) → `scrapers/core/matching.py`

**Concurrency knobs** → `DETAIL_CONCURRENCY` in `scrapers/sources/energycars.py`; `fetch_all_details(session, urls, concurrency=20)` in `scrapers/core/http.py` (sauto)

## Canonical Schema

One canonical 27-column schema for every source, defined in `scrapers/core/schema.py` (`CANONICAL_COLS`). Adapters fill the columns they have; the rest stay blank (`blank_row()`).

```text
Typ | Model auta | Cena (Kč) | Nájezd (km) | Rok výroby
Palivo | Objem motoru | Typ motoru | Hybrid typ | Výkon (kW)
Převodovka | Dvouspojková převodovka | Filtr pevných částic
Kola | Náhon 4x4 | Karoserie | Výbava | Záruka | Tepelné čerpadlo
Spárováno | Skóre shody | Extra | Stav | Odstraněno dne | Země | Zdroj | Odkaz na auto
```

`Odstraněno dne` = ISO date a listing was first seen missing; removed rows older
than 60 days are dropped from live state (full history survives in the monthly
snapshot releases).

`Typ` values: `Elektrické` · `Spalovací`.
`Země` (country of the seller): `Česko` for the CZ-only sources (sauto/autodraft/energycars); mobile.de carries `Česko` · `Slovensko` · `Německo` · `Rakousko` · `Polsko`. Blank CZ-source rows are backfilled to `Česko` in `build_data.py`.
Status values (`Stav`): `Dostupný` · `Chystá se` · `Zamluvené` · `Prodané` · `Odstraněno` · *(blank for energycars + mobilede)*.

`Spárováno` (ICE): `Ano` · `Nejisté` · `Ne` — tri-state match confidence (EV: `Ano` · `Ne` only). `Skóre shody` = numeric match score (higher = more reliable; blank for EV and `Ne` rows). See `classify_match()` in `scrapers/core/matching.py`.

## Dashboard (GitHub Pages)

Static AG Grid site at `site/`. No build step — plain HTML/JS/CSS.

- `site/index.html` — layout, AG Grid CDN imports
- `site/app.js` — column defs, filter persistence (URL + localStorage), conditional formatting
- `site/style.css` — dark theme
- `site/data/cars.parquet` + `cars-meta.json` — generated by build script (gitignored); decoded in-browser by hyparquet (pinned CDN ESM)

### Build Script

`build/build_data.py` concatenates the 4 per-source states (parquet, seed-CSV fallback) + 2 reference files → `site/data/cars.parquet` + `cars-meta.json`. It imports `scrapers.core.matching` to re-match ICE rows against the reference list.

```bash
python build/build_data.py
```

Reference data (per fuel, joined by `Typ`):

- `scrapers/data/reference/ice_specs.csv` — exact join on "Model auta" (ICE). **Column-structured**: matching features live in dedicated columns (Značka, Model, Karoserie, Objem motoru, Typ motoru, Palivo, Hybrid typ, Výbava, …), not parsed from the name. PK = `Jednoznačná varianta vozu` (clean, paren-free, unique). `matching.load_authoritative_list()` reads the columns directly.
- `scrapers/data/reference/ev_specs.csv` — prefix-match join (EV); comma-delimited (decimal cells quoted).

Both carry `Cd` (drag coefficient) + `Cd zdroj` flag (`reálné` measured / `odhad` body-shape estimate). To add a reference model, add a row with its structured columns — don't bake specs into the name.

### Verifying UI changes

**Mandatory after any `site/` change.** No build step / type check / tests exist, so run the headless-browser verifier and **Read the screenshot** before reporting done:

```bash
python build/verify_ui.py --page index --scenario grid          # grid view
python build/verify_ui.py --page index --scenario stav-filter   # opens a filter popup
python build/verify_ui.py --page reference --scenario grid       # reference page
```

Exit 0 = no console errors + grid rendered; screenshot lands in `tmp/ui-verify/`. Exit 0 alone isn't enough — Read the PNG to confirm the change looks right. See `docs/conventions.md` → "UI Verification After Changes" for adding new scenarios.

### GitHub Actions

`.github/workflows/scrape-and-deploy.yml` — daily 6am UTC + manual trigger. Runs `python -m scrapers.run` per source (previous state pulled from the rolling `data` release), builds the parquet payload, publishes state+payload back to the release (immutable `data-YYYY-MM` snapshot on the 1st), deploys Pages from artifacts. **No data is committed to git.**

## Dependencies

```bash
pip install playwright pandas pyarrow beautifulsoup4 aiohttp
playwright install chromium
```
