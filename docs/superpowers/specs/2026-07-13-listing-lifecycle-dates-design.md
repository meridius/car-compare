# Listing lifecycle dates (Přidáno / Upraveno)

**Date:** 2026-07-13
**Branch:** `feature/listing-lifecycle-dates`

## Goal

Give every scraped listing two ISO `yyyy-mm-dd` lifecycle columns, mirroring what
`build/backfill_ref_dates.py` already adds to the reference CSVs:

- **`Přidáno`** — date the listing was first seen by the scraper.
- **`Upraveno`** — date the listing's seller-provided content last changed.

## Why the mechanism differs from the reference CSVs

Reference dates are **git-derived**: the reference CSVs are tracked in git, so
`backfill_ref_dates.py` walks `git log --follow` to find first-appearance and
last-content-change per PK. **Scraped listings are not in git** — per-source state
parquet is git-ignored, and canonical data lives in the rolling GitHub Release
`data` (+ monthly snapshots). There is no git history to mine.

The listing analog of git history is the **merge step**: `merge_with_previous()`
(`scrapers/core/merge.py`) already runs every scrape, comparing the new scrape
against the previous state by `Odkaz na auto`, and already stamps a lifecycle date
(`Odstraněno dne`) into rows. The two new dates are computed in exactly that place,
per run, from the new-vs-previous comparison.

## Schema (`scrapers/core/schema.py`)

Append two columns to the **end** of `CANONICAL_COLS`, after `Odkaz na auto`
(mirrors the reference CSVs' trailing `Přidáno`,`Upraveno` pair):

```
… "Odstraněno dne", "Země", "Zdroj", "Odkaz na auto", "Přidáno", "Upraveno"
```

`blank_row()` seeds every canonical column to `""`, so all four adapters emit the
new columns blank automatically — **no adapter changes**. They are date strings,
not booleans, so `ANO_NE_COLS` is untouched.

## Stamp rules (`scrapers/core/merge.py`)

`merge_with_previous(df, base_path, today=…)` already threads `today` and reads the
previous state. Extend it:

1. If `prev` lacks the columns (first run after deploy), `prev.assign(**{"Přidáno":
   "", "Upraveno": ""})` — same guard as the existing `Odstraněno dne` handling.
   This realises the **blank backfill** decision: the ~150k rows already in state
   get blank dates (there is no honest date to give them), and accuracy begins
   going forward.
2. Per row:

| Row case | `Přidáno` | `Upraveno` |
|---|---|---|
| genuinely new (in scrape, not in prev) | `today` | `today` |
| in both, seller content **unchanged** | carry prev | carry prev (blank stays blank) |
| in both, seller content **changed** | carry prev | **`today`** |
| removed (in prev, not in scrape) | carry prev | carry prev — removal is captured by `Odstraněno dne`, not a content edit |

For rows present in both scrapes, `merge` currently takes the **new** scraped row
wholesale (`new_rows.iloc[0]`) — which has blank `Přidáno`/`Upraveno`. So the merge
must **carry `Přidáno` forward from the prev row**, and set `Upraveno` to the prev
value or `today` depending on the content comparison.

A pre-tracking row (blank `Přidáno`) that changes gets `Upraveno = today` while
`Přidáno` stays blank — truthful ("added date unknown, but it changed today"). We
never fabricate a `Přidáno`.

## Content-change definition (seller-fields-only)

`Upraveno` bumps only when a **seller-provided** field changes. Computed as a
stable hash over `CANONICAL_COLS` **minus** an exclude set, reusing the
`sorted (k,v) → "\x1f"/"\x1e" join → sha1` idiom from
`backfill_ref_dates.row_content_hash`:

```python
_DATE_HASH_EXCLUDE = {
    "Přidáno", "Upraveno",        # self
    "Odstraněno dne", "Stav",     # lifecycle, not seller content
    "Spárováno", "Skóre shody",   # our match verdict, not seller content
    "Model auta",                 # rewritten by matching (reference edits ≠ seller edit)
    "Odkaz na auto",              # the join key (always equal on a matched pair)
}
```

Excluding the match-derived trio (`Spárováno`, `Skóre shody`, `Model auta`) is the
point of the "seller-fields-only" choice: a **reference-list change re-matches rows
and rewrites those columns, but must not bump `Upraveno`** — only genuine seller
edits (price, mileage, year, power, Extra, engine specs, body…) do. `Stav` is
excluded so a listing going `Odstraněno` (or reappearing) is not counted as a
content edit; that transition already has `Odstraněno dne`.

Values are compared as `str(v)` with `.get(col, "")` fallback so a prev row missing
a column (schema evolution) hashes consistently against a new row that has it.

## Build payload (`build/build_data.py`)

Add `"Přidáno"`, `"Upraveno"` to the `ordered_cols` list (right after
`"Odstraněno dne"`). They are **date strings, not numeric** — they stay out of
`write_payload`'s `numeric_cols` (same treatment as `Odstraněno dne`). They ride
through the concat / enrichment / archive-split unchanged (per-row values, carried
verbatim). No `cars-meta.json` change.

## Dashboard grid (`site/app.js`)

Add two `COL_CONFIG` entries next to `Odstraněno dne`, mirroring it exactly:

```js
{ field: "Přidáno",  filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, w: 100, hdr: "Přidáno",  tip: "Datum, kdy byl inzerát poprvé zachycen scraperem. Prázdné = inzerát existoval před zavedením sledování." },
{ field: "Upraveno", filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, w: 100, hdr: "Upraveno", tip: "Datum poslední změny údajů od prodejce (cena, nájezd, výbava…). Prázdné = od zavedení sledování beze změny." },
```

The capture-phase digit-mask listener is scoped to all `.ag-date-filter` inputs, so
it covers the new columns with no extra wiring. The reference page (`reference.js`)
already renders `Přidáno`/`Upraveno` with the identical machinery — this brings the
index page to parity.

## Tests

- **`tests/test_merge.py`** — one case per stamp-rule row: new row → both `today`;
  unchanged row → carries prev (blank stays blank); changed **seller** field →
  `Upraveno` bumps, `Přidáno` carried; changed **match-derived only** field
  (`Skóre shody`/`Model auta`) → `Upraveno` **not** bumped; removed row → dates
  carried, not bumped; prev without the columns → blank.
- **`tests/test_schema.py`** — assert both columns present in `CANONICAL_COLS`.
- **`tests/test_data_integrity.py`** — `Přidáno ≤ Upraveno` on rows where both are
  set (mirror the existing `ReferenceDateColumnsTest`).

## UI verification

Run after the `site/` change and Read the screenshots (mandatory, no build step):

```
python build/verify_ui.py --page index --scenario grid
python build/verify_ui.py --page index --scenario grid --theme light
```

Confirm the two new date columns render. The existing `date-filter` scenario
already exercises the `agDateColumnFilter` machinery these columns reuse.

## Out of scope (YAGNI)

- Reconstructing true first-seen dates from monthly snapshot releases — heavy,
  bounded by snapshot history; the blank-backfill decision supersedes it.
- Any adapter-level change — the columns are populated purely in the merge step.
