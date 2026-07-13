# Reference date columns: `Přidáno` / `Upraveno`

## Goal

Add two ISO `yyyy-mm-dd` columns to both reference CSVs so reviewers can see when a
reference row was first added and last changed:

- **`Přidáno`** — date the row (by PK) first appeared in git history.
- **`Upraveno`** — date the row's content last changed (excluding these two date cols).

Surfaced as the last two columns of the reference grid, raw `yyyy-mm-dd`, each with an
`agDateColumnFilter` mirroring `Odstraněno dne` on the main grid.

## Files

- `scrapers/data/reference/ice_specs.csv` — PK `Jednoznačná varianta vozu`
- `scrapers/data/reference/ev_specs.csv` — PK `Model auta`

Both comma-delimited. Loaders are name-based (`csv.DictReader` in `matching.py`,
`pd.read_csv` in `build_data.py`) → appending trailing columns is safe.

## Components

### 1. Backfill script — `build/backfill_ref_dates.py`

One-shot seeder + re-runnable reconciler. For each CSV:

1. `git log --follow --reverse --format=%H|%ad --date=short -- <path>` → ordered commits
   (--follow crosses the electric/combustion → unified rename; PK is stable across it,
   verified back to `0e39b01`).
2. At each commit read the blob, parse rows by PK, hash each row's content **excluding**
   `Přidáno`/`Upraveno`. Track:
   - `Přidáno` = first commit date the PK appears.
   - `Upraveno` = last commit date the content-hash changed.
   Excluding the date cols from the hash makes re-runs **idempotent** (no self-bump).
3. Working-tree reconcile: PK absent from last commit → `Přidáno=Upraveno=today`;
   content differs from last commit → `Upraveno=today`.
4. Write back: `pd.read_csv(dtype=str, keep_default_na=False)` → add/update the two cols →
   `to_csv(quoting=QUOTE_MINIMAL)`. Verify the diff touches only the two new columns; if
   pandas reformats other cells, fall back to byte-preserving line-append surgery.

Caveat: the schema-restructure commit counts as an update, so rows untouched since collapse
to that date. Truthful; recent edits still surface later dates.

### 2. Write paths stamp today — `build/diagnose_unpaired.py`

- Add `"Přidáno"`, `"Upraveno"` to `REF_COLUMNS` (last, matching CSV header order).
- `cmd_apply` sets `cand["Přidáno"] = cand["Upraveno"] = date.today().isoformat()` for the
  new row. This is the committed write path grow-reference / `ai-match-one.sh` drive, so
  covering it covers them. Manual CSV edits reconcile on the next backfill run.

### 3. build_data — `build/build_data.py`

`load_combustion_reference` / `load_electric_reference` already carry the new columns
through `read_csv`. In `build_reference_json`, add `"Přidáno"` / `"Upraveno"` to each ICE
and EV `rec` from `row.get(...)`. Not added to `cars.json` (reference grid only).

### 4. reference.js — `site/reference.js`

- Port `maskDateEntry` document listener + `DATE_FILTER_PARAMS` (local-midnight comparator,
  `browserDatePicker:false`, `inRangeInclusive:true`) from `app.js`.
- Append two `COL_DEFS` entries at the end: `Přidáno`, `Upraveno`, `filter:
  "agDateColumnFilter"`, `filterParams: DATE_FILTER_PARAMS`, raw string display.

## Tests

- `tests/test_backfill_ref_dates.py` — hash excludes date cols (idempotent re-run);
  new-vs-last-commit PK → today; content-change → `Upraveno` bump.
- `tests/test_diagnose_unpaired.py` — `apply` stamps both dates on the appended row.
- `tests/test_data_integrity.py` — every reference row has a valid `yyyy-mm-dd` in both cols
  (in `reference.json`).
- `build/verify_ui.py --page reference --scenario grid` (dark + light) — Read the PNG.

## Non-goals

- No `cars.json` date columns (reference page only).
- No git pre-commit hook (writers stamp; backfill reconciles committed manual edits).
