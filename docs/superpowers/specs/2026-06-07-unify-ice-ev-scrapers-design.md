# Unify ICE and EV Scrapers — Design

- **Date:** 2026-06-07
- **Status:** Approved (design); pending spec review → implementation plan
- **Branch:** `feature/unify-ev-and-ice-scrapers`

## Motivation

We plan to add a `mobile.de` provider, which (like `sauto.cz`) lists **both** combustion (ICE)
and electric (EV) cars from a single source. The current architecture is split into two parallel
suites — `electric/` and `combustion/` — each with its own `utils.py`, scrapers, and CSV schema.
A single-source-multi-fuel provider fits *neither* suite, and writing it naively would duplicate
plumbing a third and fourth time.

Key observation: **the pipeline is already unified downstream.** `build/build_data.py` concatenates
all scraper CSVs into one ~31-column `site/data/cars.json` with a `Typ` field
(`Elektrické` / `Spalovací`); the dashboard already consumes a single schema. The split is
**upstream-only**. So "unify ICE and EV" means unifying the scraper/utils layer to match the
already-unified consumption layer.

This spec covers **only the unification**. The `mobile.de` provider — adapter internals, API vs
HTML, CZ/DE market filters — is **out of scope** and gets its own later spec. The unification is
what unblocks it: post-unification, adding a source is "write one adapter file + register it."

## Decisions (locked during brainstorming)

1. **Investment level:** mobile.de is the *first of several* expected multi-fuel providers →
   invest in a real fuel-agnostic, source-oriented core so each new source is cheap.
2. **Migration aggressiveness:** *Big-bang full unify* — migrate all existing scrapers, schema,
   and utils in one effort (shipped as ordered, individually-verifiable steps), then stop.
   Risk mitigated by a mandatory parity gate (see §7).
3. **Architecture shape:** *Shape A — functional source-adapters + shared `core/`*. Plain modules
   matching the existing functional style (per `docs/conventions.md`: "each helper does one thing").
   Rejected: class hierarchy (ceremony the codebase doesn't use) and config-driven single engine
   (sites differ too much — HTML sentinel parsing vs JSON — for declarative config).

## Current duplication (the problem, measured)

Three upstream duplication layers:

1. **`utils.py`** — `normalize_model`, `merge_with_previous`, `extract_body_type` + `BODY_KEYWORDS`,
   and `BRAND_MAP` are **verbatim identical** between `electric/src/utils.py` (72 lines) and
   `combustion/src/utils.py` (572 lines). Combustion adds ~500 lines of field extraction +
   authoritative matching that electric lacks.
2. **sauto scrapers** — `electric/src/scrape_sauto.py` and `combustion/src/scrape_sauto.py` are
   ~60% identical: `fetch_all_items` (paging), `fetch_detail` (semaphore), `HEADERS`, `AWD_RE`,
   and the `scrape_sauto` skeleton. They differ only in `SEARCH_PARAMS`, `build_record`, and `COLS`.
3. **autodraft scrapers** — same story: shared `load_all`, `extract_model_and_status`,
   `split_model`, `split_extra`; fork only on fuel/transmission extraction (combustion) vs heat-pump
   + Enyaq-URL handling (electric).

`sauto` and `autodraft` are *already* artificially split per-fuel and are direct analogs of
mobile.de's single-source-multi-fuel shape.

## Architecture

### §1 Target layout

Collapse `electric/` + `combustion/` into one `scrapers/` package. `bin/ build/ site/ docs/`
remain at the repo root.

```
scrapers/
  core/
    schema.py      # CANONICAL_COLS (one superset; replaces both scrape-data-cols.txt) + fuel consts
    normalize.py   # BRAND_MAP + merged MODEL_CLEANUP_PATTERNS + normalize_model
    fields.py      # all extraction (engine/hybrid/body/trim/warranty/dct/particle/awd/clean_extra)
    matching.py    # load_authoritative_list + match_to_authoritative (ICE rows only)
    merge.py       # merge_with_previous
    http.py        # aiohttp: paged search + concurrent detail fetch   (sauto, later mobile.de)
    browser.py     # Playwright: launch + load_all + cookie-accept     (autodraft, energycars)
    pipeline.py    # run_source(): DataFrame → dedup → ICE-match → merge → write CSV
  sources/
    sauto.py  autodraft.py  energycars.py
  data/
    scrapes/{sauto,autodraft,energycars}.csv     # one CSV per source
    reference/ice_specs.csv    # was combustion/data/makes-and-models.csv (auth list + ICE specs)
    reference/ev_specs.csv     # was electric/data/new_cars_specs.csv     (match list + EV specs)
  run.py           # CLI: run all sources (or --source X)
```

One CSV **per source** (not per suite×source) — keeps `merge_with_previous` removed-listing
detection correct (a link absent from a scrape means the listing is gone, not "the other suite
didn't run").

### §2 Canonical schema (the "data unification")

One superset column set, the union of both current schemas. Single source of truth in
`core/schema.py`; both `scrape-data-cols.txt` files are deleted.

```
Typ | Model auta | Cena (Kč) | Nájezd (km) | Rok výroby
Palivo | Objem motoru | Typ motoru | Hybrid typ | Výkon (kW)
Převodovka | Dvouspojková převodovka | Filtr pevných částic
Kola | Náhon 4x4 | Karoserie | Výbava | Záruka | Tepelné čerpadlo
Spárováno | Extra | Stav | Zdroj | Odkaz na auto
```

- `Typ` is set **per row by the adapter** (it knows whether it queried/parsed an EV or ICE listing).
  Replaces `build_data.py`'s current folder-based `df["Typ"]=` assignment.
- An **EV row**: ICE columns (`Objem motoru`, `Typ motoru`, `Převodovka`, …) blank;
  `Tepelné čerpadlo` set; `Palivo` = `Elektro`; `Typ` = `Elektrické`.
- An **ICE row**: `Tepelné čerpadlo` blank; engine columns set; `Typ` = `Spalovací`.
- `Spárováno` is a uniform column but populated by each fuel's **existing** matching stage
  (see §5): ICE at scrape time, EV at build time. `build_data.py` already tolerates its
  presence/absence, so no behavior change.

### §3 `core/` module responsibilities

- **normalize.py** — `normalize_model`, `BRAND_MAP` (already identical), and the **union** of both
  `MODEL_CLEANUP_PATTERNS` (Enyaq `iV` + X-Perience + Combi ordering + Ceed).
- **fields.py** — combustion's full extraction suite, unchanged. Fuel-agnostic by nature (EV
  listings simply don't match TSI/TDI patterns). `extract_body_type` (previously duplicated) lives
  here once.
- **matching.py** — combustion authoritative matching, unchanged; runs on ICE rows only.
- **merge.py** — `merge_with_previous`, verbatim (identical today).
- **http.py** — generalize sauto's `fetch_all_items` (paged) + `fetch_detail` (semaphore-capped).
  Parameters: search url, detail url, search params, page size, concurrency.
- **browser.py** — generalize the Playwright helpers from autodraft/energycars: `launch`,
  `load_all(labels=[…])` (click "load more" until gone), `accept_cookies(texts=[…])`.

### §4 Source-adapter contract + shared pipeline

Thin sources, fat core. Each `sources/X.py` exposes:

```python
SOURCE_NAME = "Sauto.cz"
FUELS = {"ICE", "EV"}          # energycars = {"EV"} only
async def scrape() -> list[dict]   # rows in CANONICAL_COLS, with Typ set per row
```

`core/pipeline.run_source(module)` performs the **fuel-agnostic** post-scrape steps once, for
every source:

```
rows → DataFrame(columns=CANONICAL_COLS) → drop_duplicates("Odkaz na auto") → sort
     → matching.match_ice(df, auth_list)   # rewrites ICE Model auta + Spárováno; EV passthrough
     → merge_with_previous(df, csv_path)
     → write scrapers/data/scrapes/{source}.csv
```

Source-**specific** parsing (card text vs JSON suffix → canonical fields) stays inside each
`scrape()`. Generic steps (match/merge/write) are never duplicated again. Adding a source =
write its `scrape()` + register it in `run.py`; it inherits the pipeline.

### §5 Fuel matching — both fuels matched, asymmetric, mechanisms unchanged

Two **asymmetric** concerns kept distinct (do not force-merge them):

| | ICE | EV |
|---|---|---|
| match list | `ice_specs.csv` (makes-and-models) | `ev_specs.csv` (new_cars_specs) |
| mechanism | weighted-score auth match → **rewrites `Model auta`** + sets `Spárováno` | prefix join → attaches spec columns + sets `Spárováno` (**no name rewrite**) |
| where (unchanged) | scrape-time, `core/matching.py` (was the combustion scraper) | build-time, `build_data.py` `join_electric_reference` |

Both reference files double as match-list + spec source. Neither mechanism changes location or
behavior — only their *code* is relocated into the unified tree. EV model names are **not**
auth-rewritten, so the build-time prefix match still works exactly as today.

For a future multi-fuel source, routing is on `Typ`: ICE listings → pipeline auth match;
EV listings → build prefix match. No new logic.

### §6 build_data.py / bin / workflow changes

- **build_data.py** — read source CSVs from `scrapers/data/scrapes/` (drop the
  electric/combustion directory walk). Remove the hardcoded `df["Typ"]=` assignment (`Typ` now
  comes from the CSV). Keep both per-fuel reference joins, routing on `Typ` instead of suite origin.
  `ordered_cols` already approximates the canonical schema, so changes are minimal. Reference paths
  point at `scrapers/data/reference/`.
- **bin/** — delete both `electric/bin/run_scraper.sh` and `combustion/bin/run_scraper.sh`.
  `bin/run_all.sh` calls `python scrapers/run.py` (with an optional `--source` filter).
  `bin/serve.sh` unchanged.
- **.github/workflows/scrape-and-deploy.yml** — update paths to the single runner and new data dir.

### §7 Parity gate (big-bang risk control) — mandatory

Big-bang is a one-shot regression risk to live daily data; cutover is gated on output parity,
per source:

1. **Baseline:** run the **current** scrapers now → save the CSVs + `cars.json` as a frozen baseline.
2. **Compare:** run the **new** code in the same window and diff:
   - the column set equals `CANONICAL_COLS` (allowing the new `Typ` / `Spárováno` / `Tepelné čerpadlo`
     columns);
   - join old ∪ new rows on `Odkaz na auto`; for shared columns, assert per-row equality;
   - every mismatch must be an *intended* difference (schema addition, EV rows now carrying blank ICE
     columns), never a parsing regression.
3. **Product check:** diff `cars.json` (record count + per-field). Near-identical (modulo new
   columns / ordering) ⇒ safe cutover. Run `build/verify_ui.py` and **read** the screenshot.

Live data shifts between runs, so diffs keyed on link must tolerate listings that genuinely appeared
or vanished; tolerance is **zero** for transformation differences on links present in both runs.

### §8 Migration order (ordered, individually-verifiable commits)

The end state is big-bang, but it ships as ordered steps, each verifiable against live data:

1. Scaffold `scrapers/core/` + canonical schema; merge both `utils.py` (dedup
   normalize/fields/matching/merge). Import smoke-test.
2. Port **sauto** → one multi-fuel adapter on the core. Parity-diff against the old
   electric+combustion sauto CSVs. *(Pilot — proves the architecture, kills the biggest dup.)*
3. Port **autodraft** → one multi-fuel adapter. Parity-diff.
4. Port **energycars** → EV-only adapter. Parity-diff.
5. Rewire **build_data.py** to the new paths/schema. Parity-diff `cars.json`; run `verify_ui.py`,
   read screenshot.
6. Update **bin/** + **workflow**. End-to-end run green.
7. **Cutover:** delete `electric/` and `combustion/` trees; rewrite docs (§9).

`mobile.de` is intentionally **not** a step here — it is a separate spec after this lands.

### §9 Documentation updates

Rewrite `CLAUDE.md`, `docs/architecture.md`, `docs/conventions.md`, `docs/gotchas.md` for a single
suite / schema / core. Most gotchas survive verbatim (parsing quirks are unchanged) — re-home them
under per-source headings.

## Goals

- One fuel-agnostic, source-oriented scraper core; adding a source is one adapter file + a registry entry.
- One canonical CSV schema across all sources.
- Zero behavior change to scraped/published data (enforced by the §7 parity gate).
- No new third-party dependencies (per `docs/conventions.md`).

## Non-goals

- The `mobile.de` provider (adapter internals, market/API decisions) — separate later spec.
- Merging the two reference *spec* files (ICE consumption/trunk vs EV battery/range are disjoint
  domains; they stay two files).
- Changing either matching mechanism's behavior or output.
- Database/alternate output formats (CSV remains the sole scraper output).

## Risks / open questions

- **Import style for the package** (`python -m scrapers.run` vs `sys.path` tweak in `bin/`). Decide
  during planning; favor running via the `bin/` entrypoints.
- **Playwright generalization** (`core/browser.py`) must not regress autodraft's `load_all` button
  labels or energycars' listing→detail concurrency — covered by the §7 parity gate.
- **Parity baseline drift:** live listings change between the baseline and verification runs; the
  gate keys on link identity to isolate genuine transformation diffs.
