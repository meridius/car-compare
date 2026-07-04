# Scalable Storage (enable DE ICE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CSV-in-git + cars.json with Parquet state files persisted to GitHub Releases and a Parquet payload on Pages, so mobile.de DE ICE (~133k listings) fits the pipeline, the repo, and the AG Grid dashboard.

**Architecture:** Per-source scrape state moves from `<slug>.csv` (git-tracked) to `<slug>.parquet` (git-ignored, persisted as assets of a rolling GitHub Release `data`, with monthly immutable snapshot releases for history/safety). The site payload moves from `site/data/cars.json` (129 MB at DE scale — exceeds GitHub's 100 MiB push block) to `site/data/cars.parquet` (zstd, ~5.5 MB) + `cars-meta.json` sidecar, shipped only inside the Pages artifact, never committed. `site/app.js` decodes the parquet with hyparquet (pinned ESM from jsDelivr) and feeds the exact same row objects into the untouched AG Grid Community clientSideRowModel (verified rendering 141k rows). A new `Odstraněno dne` column + 60-day removed-row retention in `merge_with_previous()` bounds live data size forever; every row still lands in ≥1 immutable monthly snapshot (retention 60d > snapshot interval 31d).

**Tech Stack:** Python 3.12, pandas + pyarrow (new dep), stdlib unittest, GitHub Actions + `gh` CLI for releases, hyparquet 1.26.2 + hyparquet-compressors 1.1.1 (browser, pinned CDN ESM), AG Grid Community 33.1.1 (unchanged).

## Global Constraints

- Czech for user-facing strings, English for identifiers/comments (docs/conventions.md).
- Adapters emit exactly CANONICAL_COLS; column order never silently reordered.
- `./bin/test.sh` must pass; every logic change adds a test that fails without it.
- After `site/` changes run `build/verify_ui.py` and Read the screenshot.
- New dependency `pyarrow` is the explicit deliverable of this task (approved by task scope: storage decision); no other new libs.
- State parquet is stringly-typed (dtype str, blanks "") — exact semantic parity with today's `pd.read_csv(dtype=str).fillna("")`.
- Payload parquet numeric columns are float64 only (never int64 — hyparquet decodes int64 to BigInt, which breaks the grid).
- Retention: `REMOVED_RETENTION_DAYS = 60`; monthly snapshots ensure no row is ever lost.
- Bootstrap seeds: existing tracked CSVs stay in git, frozen; loaders prefer parquet, fall back to seed CSV, else empty.

## Measured facts anchoring the design (2026-07-04, real DE data)

| artifact | rows | size |
|---|---|---|
| mobilede.csv (DE ICE on) | 133,062 | 38.5 MB |
| cars.json | 140,975 | 129.0 MB |
| cars.parquet zstd | 140,975 | 5.5 MB |
| browser decode (hyparquet, Chromium) | 140,975 | 1.4 s / 198 MB heap |
| browser JSON.parse baseline | 140,975 | 9.0 s / 214 MB heap |
| verify_ui grid/stav-filter/summary at 141k | — | PASS |

---

### Task 1: `scrapers/core/storage.py` — state read/write with seed fallback

**Files:**
- Create: `scrapers/core/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `read_state(base_path: Path) -> pd.DataFrame | None` — `base_path` WITHOUT extension (e.g. `scrapers/data/scrapes/sauto`); tries `.parquet`, then `.csv` seed; returns stringly df (`.fillna("")`, all values str) or None if neither exists.
- Produces: `write_state(df: pd.DataFrame, base_path: Path) -> Path` — writes `<base>.parquet` (zstd), all columns coerced to string with blanks as `""`; returns written path.

Round-trip must preserve `""` (NOT `"nan"`/NaN), Czech diacritics, and column order.

- [x] **Step 1: Write the failing test** — `tests/test_storage.py` with cases: round-trip equality + dtype str + "" preserved; read prefers parquet over csv; csv fallback used when no parquet; returns None when neither; column added to schema after write is filled "" on read via reindex (schema-evolution case); NaN injected pre-write comes back "".
- [x] **Step 2: Run to verify it fails** — `python3 -m unittest tests.test_storage -v` → ImportError.
- [x] **Step 3: Implement `scrapers/core/storage.py`.**
- [x] **Step 4: Run tests — pass.**
- [x] **Step 5: Commit.**

### Task 2: schema — add `Odstraněno dne` column

**Files:**
- Modify: `scrapers/core/schema.py` (CANONICAL_COLS: insert `"Odstraněno dne"` right after `"Stav"`)
- Test: extend `tests/test_storage.py` or new `tests/test_schema.py`

**Interfaces:**
- Produces: `CANONICAL_COLS` length 27; every adapter's `blank_row()` automatically seeds the new col to `""`.

- [x] Steps: failing test (27 cols, position after Stav, blank_row covers it) → implement → pass → commit.

### Task 3: merge — parquet state, removal stamping, retention

**Files:**
- Modify: `scrapers/core/merge.py`
- Test: `tests/test_merge.py` (new)

**Interfaces:**
- Consumes: `storage.read_state`.
- Produces: `merge_with_previous(df, base_path, today: date | None = None) -> pd.DataFrame` — signature gains `today` for testability; callers pass base path without extension now.

Behavior (each a test):
1. previous state missing → df returned unchanged (existing).
2. vanished link → row kept, `Stav="Odstraněno"`, `Odstraněno dne=today.isoformat()` stamped only if blank.
3. row already `Odstraněno` with a date → date preserved.
4. link reappears → new row wins (fresh Stav, `Odstraněno dne` = "" from the new scrape).
5. retention: previous rows with `Odstraněno dne` < today−60d are dropped; exactly-60-days kept.
6. previous rows with empty link skipped (existing gotcha preserved).
7. previous row `Odstraněno` with BLANK date (legacy seed) → stamped today (grace period starts now, one-time migration semantics).

- [x] Steps: failing tests → implement → pass → commit.

### Task 4: pipeline — write parquet state

**Files:**
- Modify: `scrapers/core/pipeline.py` (csv_path → base path; `storage.write_state`; keep reindex on CANONICAL_COLS)
- Test: `tests/test_pipeline_io.py` (new, exercises run_source's write path with a stub source) or fold into test_storage.

- [x] Steps: failing test (run pipeline write helper on fixture rows → parquet exists, 27 cols, dedup by link still applied) → implement → pass → commit.

### Task 5: build_data — parquet payload + meta sidecar + history seed

**Files:**
- Modify: `build/build_data.py`
  - `load_scraper_csvs()` → `load_scraper_data()` using `storage.read_state` per slug.
  - Payload writer: `site/data/cars.parquet` (zstd, numeric cols float64, string cols object w/ None for blanks — same values as today's JSON records) + `site/data/cars-meta.json` (exact `metadata` dict of today).
  - Stop writing `cars.json`.
  - `update_scrape_history()`: if `site/data/scrape_history.json` missing, seed from `scrapers/data/seed/scrape_history.json` (new tracked copy).
- Create: `scrapers/data/seed/scrape_history.json` (copy of current history)
- Test: extend `tests/test_build_data.py` — payload dtype guard (no int64 columns in written parquet — read schema via pyarrow; numeric set matches today's `numeric_cols`), meta sidecar keys (`buildDate,trigger,sources,matching,referenceData,totalCars`), history seeding.

- [x] Steps: failing tests → implement → pass → commit.

### Task 6: consumers — reference_gap, parity_check, verify_ui, serve.sh, test_data_integrity

**Files:**
- Modify: `build/reference_gap.py` (`load_unpaired` reads `site/data/cars.parquet` via pandas; `--rebuild` message unchanged)
- Modify: `tools/parity_check.py` (`_rows_from_json` — add parquet branch on extension)
- Modify: `build/verify_ui.py` (`ensure_data` checks `cars.parquet`)
- Modify: `bin/serve.sh` (build-if-missing check on `cars.parquet`)
- Modify: `tests/test_data_integrity.py` (load rows from parquet + meta sidecar; keep every invariant; add: no `Odstraněno` row older than 60d by `Odstraněno dne`; add: parquet numeric schema has no int64)
- Modify: `tests/test_reference_gap.py` (fixture writes parquet instead of cars.json where shape is pinned)

- [x] Steps: adjust tests first where they pin the old shape → implement → `./bin/test.sh` green → commit.

### Task 7: site — hyparquet loader

**Files:**
- Modify: `site/index.html` (`<script src="app.js">` → `type="module"`; AG Grid/Chart.js tags unchanged)
- Modify: `site/app.js` (top-level ESM imports pinned: `hyparquet@1.26.2/+esm`, `hyparquet-compressors@1.1.1/+esm`; replace the `fetch("data/cars.json")` tail block with: parallel `fetch("data/cars-meta.json")` + `parquetReadObjects({file: await asyncBufferFromUrl({url:"data/cars.parquet"}), compressors})`; map `undefined`→`null` not needed — hyparquet emits null; call existing `init(rows)`; error path renders same Czech message)
- Modify: `site/app.js` COL_CONFIG: add `{ field: "Odstraněno dne", ... }` textish column next to `Stav`.
- Test: `python3 build/verify_ui.py --page index --scenario grid|stav-filter|summary|sparovano|overview-matching` + Read PNGs. reference page untouched (reference.json stays JSON).

- [x] Steps: implement → verify_ui all scenarios PASS at 141k rows → Read screenshots → commit.

### Task 8: workflow — releases as state store, no data commits

**Files:**
- Modify: `.github/workflows/scrape-and-deploy.yml`

Shape:
- scrape leg: after checkout + pip (`playwright pandas pyarrow beautifulsoup4 aiohttp`), `gh release download data --pattern "state-<src>.parquet" -O scrapers/data/scrapes/<src>.parquet || true` (seed CSV from checkout remains the fallback); run scraper; upload artifact `state-<src>` = `scrapers/data/scrapes/<src>.parquet`.
- build job: download release states for ALL slugs first (`|| true`), then overlay fresh artifacts; download `scrape_history.json` from release (`|| true`); pip add `pyarrow`; run build; upload artifact `site-data` (site/data/*); `gh release create data --notes ... || true` then `gh release upload data state-*.parquet cars.parquet cars-meta.json scrape_history.json reference.json --clobber`; monthly snapshot: if day-of-month = 01, `gh release create data-$(date +%Y-%m)` with same assets (immutable history).
- delete the "Commit data if changed" step entirely.
- deploy job: checkout main; download `site-data` artifact into `site/data/`; cache-bust; upload-pages-artifact; deploy.
- `GH_TOKEN: ${{ github.token }}` env for gh steps; `contents: write` already present.

- [x] Steps: rewrite YAML → `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/scrape-and-deploy.yml'))"` parse check (PyYAML present? else `ruby -ryaml` or actionlint if available; at minimum careful review) → commit. Live-run verification happens on push (documented in final report as pending first main run).

### Task 9: git hygiene + docs

**Files:**
- Modify: `.gitignore` (+ `scrapers/data/scrapes/*.parquet`, `site/data/*` with `!site/data/.gitkeep`)
- `git rm --cached site/data/cars.json site/data/reference.json site/data/scrape_history.json` (seed copy of history now under scrapers/data/seed/)
- Keep `scrapers/data/scrapes/*.csv` tracked (frozen seeds; docs say delete after first successful main run).
- Modify: `docs/conventions.md` (Output section: parquet state + payload replaces "CSVs are the sole output format"; dependencies + pyarrow; testing notes)
- Modify: `docs/architecture.md` (data flow, storage layers, release layout, retention, payload)
- Modify: `docs/gotchas.md` (BigInt/float64; Pages gzip+Range Content-Range bug; stringly state parity; seed fallback; retention/snapshot math; hyparquet pinned ESM)
- Modify: `CLAUDE.md` (schema 27 cols, outputs, deps, dashboard data files)
- Modify: `TASKS.md` (check the item, record decision pointer)
- Create: `docs/decisions/001-scalable-storage.md` (decision record — already drafted)

- [x] Steps: edits → `./bin/test.sh` → commit.

### Task 10: end-to-end verification at DE scale

- [x] Re-run `python3 -m scrapers.run --source mobilede` (real scrape, now writing parquet state via CSV-seed merge path).
- [x] `python3 build/build_data.py` → cars.parquet + meta.
- [x] `./bin/test.sh` green (incl. integrity at 141k).
- [x] verify_ui all index scenarios + reference grid; Read PNGs.
- [x] Commit; final report with numbers.
