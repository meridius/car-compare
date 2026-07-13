# Listing lifecycle dates (Přidáno / Upraveno) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every scraped listing two ISO `yyyy-mm-dd` lifecycle columns — `Přidáno` (first seen) and `Upraveno` (seller content last changed) — computed in the merge step, mirroring the reference CSVs' date pair but sourced from the scrape lifecycle instead of git.

**Architecture:** Scraped listings aren't in git, so `merge_with_previous()` (the per-run new-vs-previous comparison that already stamps `Odstraněno dne`) is the listing analog of git history. It stamps `Přidáno`/`Upraveno` there. The columns flow through `build_data.py` into the payload and are shown as `agDateColumnFilter` grid columns exactly like `Odstraněno dne`.

**Tech Stack:** Python 3 (pandas, stdlib `unittest`, `hashlib`), plain JS AG Grid (`site/app.js`), headless verifier (`build/verify_ui.py`).

## Global Constraints

- Czech for user-facing strings (grid headers, tooltips); English for code identifiers/comments/docstrings.
- Final DataFrame columns must match `CANONICAL_COLS` order; adapters emit exactly those columns via `blank_row()` — no adapter edits in this feature.
- No new dependencies (`playwright`, `pandas`, `pyarrow`, `beautifulsoup4`, `aiohttp` only).
- State parquet is stringly-typed (every cell a str, blanks `""`); dates are `"YYYY-MM-DD"` strings, never Python `date` objects in state/payload.
- Tests: stdlib `unittest`, offline, no network. `./bin/test.sh` must pass.
- `Upraveno` change detection is **seller-fields-only**: excludes our lifecycle/verdict columns; **price** (`Cena (Kč)`) uses a **1% relative tolerance** so mobile.de's daily EUR→Kč CNB FX jitter never bumps it.
- Existing-state **backfill is blank**: rows already in state (no date to give) stay blank; accuracy begins going forward.
- After any `site/` change: run `build/verify_ui.py` for the affected scenario in **both** themes and **Read** the screenshot before claiming done.

---

### Task 1: Schema — add the two columns

**Files:**
- Modify: `scrapers/core/schema.py` (`CANONICAL_COLS`)
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `CANONICAL_COLS` now ends with `… "Odkaz na auto", "Přidáno", "Upraveno"`. `blank_row()` seeds them `""` automatically (no code change to it).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schema.py` (inside the existing `TestCase`, after the `Odstraněno dne` assertions):

```python
    def test_lifecycle_date_columns_present_and_trailing(self):
        for col in ("Přidáno", "Upraveno"):
            self.assertIn(col, CANONICAL_COLS)
        # They are the final two columns, in this order (mirrors the reference CSVs).
        self.assertEqual(CANONICAL_COLS[-2:], ["Přidáno", "Upraveno"])

    def test_blank_row_seeds_lifecycle_dates(self):
        row = blank_row()
        self.assertEqual(row["Přidáno"], "")
        self.assertEqual(row["Upraveno"], "")
```

Ensure `blank_row` is imported at the top of `tests/test_schema.py` (add it to the existing `from scrapers.core.schema import …` line if absent).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_schema -v`
Expected: FAIL — `Přidáno` not in `CANONICAL_COLS`.

- [ ] **Step 3: Add the columns**

In `scrapers/core/schema.py`, change the tail of `CANONICAL_COLS` from:

```python
    "Spárováno", "Skóre shody", "Extra", "Stav", "Odstraněno dne", "Země", "Zdroj",
    "Odkaz na auto",
]
```

to:

```python
    "Spárováno", "Skóre shody", "Extra", "Stav", "Odstraněno dne", "Země", "Zdroj",
    "Odkaz na auto", "Přidáno", "Upraveno",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_schema -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/core/schema.py tests/test_schema.py
git commit -m "feat(schema): add Přidáno/Upraveno lifecycle columns for listings"
```

---

### Task 2: Merge — stamp Přidáno / Upraveno

**Files:**
- Modify: `scrapers/core/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `CANONICAL_COLS` (Task 1).
- Produces: `merge_with_previous(df, base_path, today=None, retention_days=…)` unchanged signature; every returned row now carries `Přidáno`/`Upraveno`. New module-level helpers `_content_hash(row)`, `_price_changed(new_row, prev_row)`, constants `_DATE_HASH_EXCLUDE`, `_CONTENT_COLS`, `_PRICE_COL`, `_PRICE_REL_TOL`.

Stamp rules (what the tests pin):

| Row case | `Přidáno` | `Upraveno` |
|---|---|---|
| genuinely new (in scrape, not prev) | today | today |
| no previous state at all (`prev is None`) | today (all rows) | today (all rows) |
| in both, seller content unchanged | carry prev | carry prev (blank stays blank) |
| in both, seller content changed | carry prev | today |
| removed (in prev, not scrape) | carry prev | carry prev |
| prev lacks the columns (first run vs existing state) | blank | blank |

"Seller content changed" = the content hash differs **or** price moved ≥ 1%.

- [ ] **Step 1: Write the failing tests**

Add a new test class to `tests/test_merge.py` (after the existing `MergeTest`). It uses its own richer fixture (seller price + a match-derived column) so it can exercise the change rules:

```python
# Extended fixture: seller price (Cena) + a match-derived col (Skóre shody) so the
# lifecycle-date rules can be exercised (content change vs match-only change).
LCOLS = ["Model auta", "Cena (Kč)", "Skóre shody", "Stav",
         "Odstraněno dne", "Odkaz na auto", "Přidáno", "Upraveno"]


def _ldf(rows):
    return pd.DataFrame(rows, columns=LCOLS)


class LifecycleDateTest(unittest.TestCase):
    # rows: [Model, Cena, Skóre, Stav, OdstrDne, Odkaz, Přidáno, Upraveno]

    def test_genuinely_new_row_stamped_today(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""],
                    ["B", "600000", "3", "Dostupný", "", "https://x/2", "", ""]])
        out = _merge(new, prev)
        added = out[out["Odkaz na auto"] == "https://x/2"].iloc[0]
        self.assertEqual(added["Přidáno"], "2026-07-04")
        self.assertEqual(added["Upraveno"], "2026-07-04")

    def test_no_previous_state_stamps_all_rows_today(self):
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, None)
        self.assertEqual(out.iloc[0]["Přidáno"], "2026-07-04")
        self.assertEqual(out.iloc[0]["Upraveno"], "2026-07-04")

    def test_unchanged_row_carries_dates_forward(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-10"]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "2026-06-01")
        self.assertEqual(row["Upraveno"], "2026-06-10")  # NOT bumped

    def test_unchanged_row_with_blank_dates_stays_blank(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "")
        self.assertEqual(row["Upraveno"], "")

    def test_mileage_change_bumps_upraveno(self):
        # Nájezd is a seller field IN the hash — the clean "bump" case.
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        # Nájezd (km) is a seller field in the hash — set it different on each side.
        prev["Nájezd (km)"] = "40000"
        new["Nájezd (km)"] = "45000"
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "2026-06-01")   # carried
        self.assertEqual(row["Upraveno"], "2026-07-04")  # bumped

    def test_model_auta_change_alone_does_not_bump(self):
        # Model auta is rewritten by matching (reference edits), so a change to it
        # with identical seller content must NOT bump Upraveno.
        prev = _ldf([["Škoda Octavia", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["Škoda Octavia 1.5 TSI", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # NOT bumped

    def test_match_score_change_alone_does_not_bump(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "500000", "9", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # Skóre shody excluded

    def test_price_jitter_under_one_percent_does_not_bump(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "503000", "3", "Dostupný", "", "https://x/1", "", ""]])  # +0.6%
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # FX jitter absorbed

    def test_real_price_move_bumps_upraveno(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "480000", "3", "Dostupný", "", "https://x/1", "", ""]])  # -4%
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-07-04")  # real drop bumps

    def test_removed_row_carries_dates_and_is_not_bumped(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-05"]])
        new = _ldf([["B", "600000", "3", "Dostupný", "", "https://x/2", "", ""]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Stav"], "Odstraněno")
        self.assertEqual(gone["Odstraněno dne"], "2026-07-04")
        self.assertEqual(gone["Přidáno"], "2026-06-01")   # carried
        self.assertEqual(gone["Upraveno"], "2026-06-05")  # NOT bumped

    def test_prev_without_date_columns_leaves_blank(self):
        # Existing state predates the feature → columns absent → blank backfill.
        legacy_cols = ["Model auta", "Cena (Kč)", "Skóre shody", "Stav",
                       "Odstraněno dne", "Odkaz na auto"]
        prev = pd.DataFrame([["A", "500000", "3", "Dostupný", "", "https://x/1"]],
                            columns=legacy_cols)
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "")
        self.assertEqual(row["Upraveno"], "")
```

Delete the trailing comment lines inside `test_seller_field_change_bumps_upraveno` — keep only the two asserts (the case changes `Model auta` **and** nothing else, so it actually belongs as the "no bump" case). **Correction:** replace `test_seller_field_change_bumps_upraveno` with a version that changes a genuine seller field — use `Stav`? No, `Stav` is excluded. Use price, already covered by `test_real_price_move_bumps_upraveno`. So **drop** `test_seller_field_change_bumps_upraveno` entirely (the model-name and price cases already cover bump / no-bump). Keep the other twelve tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_merge.LifecycleDateTest -v`
Expected: FAIL — `Přidáno`/`Upraveno` not stamped (blank/KeyError).

- [ ] **Step 3: Implement the stamp logic**

Replace the whole of `scrapers/core/merge.py` with:

```python
"""Merge new scrape with previous state, preserving removed listings.

Removed listings are kept with Stav="Odstraněno" and stamped with the date they
were first seen missing ("Odstraněno dne"). By default they are kept forever:
the dashboard splits them into a lazy-loaded archive (decision 001, option C),
so the live payload stays bounded by the market while full history is available
on demand and permanently in the monthly snapshot releases.

`retention_days` is an optional cap — pass an int to drop rows removed longer
ago than that (useful if the archive ever needs bounding). None = keep all.

Lifecycle dates (listing analog of the git-derived reference dates): scraped
listings are not in git, so first-seen ("Přidáno") and last-content-change
("Upraveno") are stamped here from the new-vs-previous comparison. A genuinely
new link gets both = today; a link present in both scrapes carries Přidáno
forward and bumps Upraveno to today only when its SELLER content changed; a
removed link carries both unchanged (removal is Odstraněno dne, not an edit).
Existing state that predates the feature has no date to give → blank, filling
forward. "Seller content" excludes our own lifecycle/match-verdict columns, and
price uses a 1% relative tolerance so mobile.de's daily EUR→Kč FX jitter never
counts as an edit.
"""
import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import storage
from .schema import CANONICAL_COLS

# None = keep every removed row (archive is unbounded, snapshots are permanent).
# Set to an int to cap how long removed listings survive in live state.
REMOVED_RETENTION_DAYS = None

# Columns that do NOT count as seller content for the "Upraveno" decision.
_DATE_HASH_EXCLUDE = {
    "Přidáno", "Upraveno",        # self
    "Odstraněno dne", "Stav",     # lifecycle, not content
    "Spárováno", "Skóre shody",   # our match verdict, not seller content
    "Model auta",                 # rewritten by matching (reference edits ≠ seller edit)
    "Odkaz na auto",              # the join key (equal on a matched pair)
    "Cena (Kč)",                  # handled separately with a tolerance (FX jitter)
}
_CONTENT_COLS = [c for c in CANONICAL_COLS if c not in _DATE_HASH_EXCLUDE]

_PRICE_COL = "Cena (Kč)"
# 1% relative tolerance: mobile.de prices are EUR→Kč via the daily CNB fixing, so
# the stored Kč integer drifts sub-percent day to day with no seller edit. A real
# price move (typically several %) still bumps Upraveno; FX jitter does not.
_PRICE_REL_TOL = 0.01


def _cell(row, col) -> str:
    v = row.get(col, "")
    return "" if v is None else str(v)


def _content_hash(row) -> str:
    """Stable hash of a row's seller-provided content (see _DATE_HASH_EXCLUDE)."""
    payload = "\x1f".join(f"{c}\x1e{_cell(row, c)}" for c in _CONTENT_COLS)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _to_price(row):
    """Parse a stringly Kč price into a float, or None if blank/garbage."""
    raw = _cell(row, _PRICE_COL).replace("\xa0", "").replace(" ", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _price_changed(new_row, prev_row) -> bool:
    """True when price moved beyond the FX-jitter tolerance."""
    b = _to_price(new_row)
    a = _to_price(prev_row)
    if a is None or b is None:
        return a != b           # one side blank, the other not → a real change
    if a == 0:
        return b != 0
    return abs(b - a) / a >= _PRICE_REL_TOL


def _seller_content_changed(new_row, prev_row) -> bool:
    return _content_hash(new_row) != _content_hash(prev_row) or _price_changed(new_row, prev_row)


def _keep_removed(row, cutoff) -> bool:
    """True when a previously-removed row is still within the retention window.

    cutoff is None (keep all) or a date; a blank/garbage stamp is kept (the
    caller re-stamps it).
    """
    if cutoff is None:
        return True
    try:
        removed_on = date.fromisoformat(row.get("Odstraněno dne", ""))
    except ValueError:
        return True
    return removed_on >= cutoff


def merge_with_previous(df: pd.DataFrame, base_path: Path, today: date | None = None,
                        retention_days=REMOVED_RETENTION_DAYS) -> pd.DataFrame:
    """Merge new scrape with previous state, preserving row order from previous state."""
    today = today or date.today()
    today_iso = today.isoformat()
    cutoff = None if retention_days is None else today - timedelta(days=retention_days)

    prev = storage.read_state(base_path)
    if prev is None or "Odkaz na auto" not in prev.columns:
        # No history at all → every row is genuinely first-seen today.
        df = df.copy()
        df["Přidáno"] = today_iso
        df["Upraveno"] = today_iso
        return df
    for col in ("Odstraněno dne", "Přidáno", "Upraveno"):
        if col not in prev.columns:
            prev = prev.assign(**{col: ""})

    result_rows = []
    for _, prev_row in prev.iterrows():
        link = prev_row["Odkaz na auto"]
        if not link:
            continue
        new_rows = df[df["Odkaz na auto"] == link]
        if len(new_rows) > 0:
            prev_dict = prev_row.to_dict()
            new_row = new_rows.iloc[0].to_dict()
            # Present in both: carry Přidáno; bump Upraveno only on a real edit.
            new_row["Přidáno"] = prev_dict.get("Přidáno", "")
            if _seller_content_changed(new_row, prev_dict):
                new_row["Upraveno"] = today_iso
            else:
                new_row["Upraveno"] = prev_dict.get("Upraveno", "")
            result_rows.append(new_row)
            continue
        row = prev_row.copy()
        if row["Stav"] == "Odstraněno" and not _keep_removed(row, cutoff):
            continue
        row["Stav"] = "Odstraněno"
        try:
            date.fromisoformat(row["Odstraněno dne"])
        except ValueError:
            row["Odstraněno dne"] = today_iso
        # Přidáno / Upraveno carried forward untouched (removal is not an edit).
        result_rows.append(row.to_dict())
    # Add genuinely new listings (not in prev) at the end
    prev_links = set(prev["Odkaz na auto"])
    for _, row in df.iterrows():
        if row["Odkaz na auto"] not in prev_links:
            new_row = row.to_dict()
            new_row["Přidáno"] = today_iso
            new_row["Upraveno"] = today_iso
            result_rows.append(new_row)
    return pd.DataFrame(result_rows).reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_merge -v`
Expected: PASS — the new `LifecycleDateTest` **and** the pre-existing `MergeTest` (adding blank date columns to prev must not break removal/retention behaviour).

- [ ] **Step 5: Commit**

```bash
git add scrapers/core/merge.py tests/test_merge.py
git commit -m "feat(merge): stamp Přidáno/Upraveno lifecycle dates on scraped listings"
```

---

### Task 3: Build payload carries the dates + integrity invariant

**Files:**
- Modify: `build/build_data.py` (`main()` — guard-create columns + `ordered_cols`)
- Test: `tests/test_data_integrity.py`

**Interfaces:**
- Consumes: state rows that now carry `Přidáno`/`Upraveno` (Task 2). On a **seed-only** build (seeds predate the feature, merge isn't run) the concatenated frame lacks the columns — `main()` must guard-create them blank so the payload schema is stable.
- Produces: `cars.parquet` / `cars-archived.parquet` carry `Přidáno`/`Upraveno` as date strings (not numeric). No `cars-meta.json` change.

- [ ] **Step 1: Write the failing test**

Add a new test class to `tests/test_data_integrity.py` (after `ReferenceDateColumnsTest`):

```python
class ListingDateColumnsTest(unittest.TestCase):
    """The listing payload carries Přidáno/Upraveno (may be blank per row, unlike
    the reference), and where both are set Přidáno must not be after Upraveno."""

    @classmethod
    def setUpClass(cls):
        cls.rows = _records(CARS_PARQUET)
        cls.assertTrue(cls.rows, "cars.parquet is empty")

    def test_both_date_columns_present(self):
        sample = self.rows[0]
        self.assertIn("Přidáno", sample)
        self.assertIn("Upraveno", sample)

    def test_set_dates_are_iso(self):
        for col in ("Přidáno", "Upraveno"):
            bad = [r for r in self.rows
                   if r.get(col) and not _ISO_DATE_RE.match(str(r[col]))]
            self.assertEqual(bad, [], f"{len(bad)} rows have non-ISO {col}")

    def test_pridano_not_after_upraveno(self):
        bad = [r for r in self.rows
               if r.get("Přidáno") and r.get("Upraveno")
               and str(r["Přidáno"]) > str(r["Upraveno"])]
        self.assertEqual(bad, [], f"{len(bad)} listings have Přidáno after Upraveno")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rm -f site/data/cars.parquet && python -m unittest tests.test_data_integrity.ListingDateColumnsTest -v`
Expected: FAIL — `test_both_date_columns_present` (columns absent from a seed-only payload). (`setUpModule` rebuilds `cars.parquet` first.)

- [ ] **Step 3: Guard-create the columns + add to ordered_cols**

In `build/build_data.py` `main()`, immediately **before** the `ordered_cols = [` assignment (currently around line 1150, right after the PHEV-consumption block), add:

```python
    # Lifecycle dates ride through from state; a seed-only build (merge not run)
    # lacks them, so ensure the payload schema is stable (blank when unknown).
    for col in ("Přidáno", "Upraveno"):
        if col not in df.columns:
            df[col] = ""
```

Then extend the `ordered_cols` list — change:

```python
        "Extra", "Stav", "Odstraněno dne", "Země", "Zdroj", "Odkaz na auto",
```

to:

```python
        "Extra", "Stav", "Odstraněno dne", "Přidáno", "Upraveno", "Země", "Zdroj", "Odkaz na auto",
```

(They are date strings — do **not** add them to `PAYLOAD_NUMERIC_COLS`; `_coerce_payload` leaves non-numeric columns as strings, same as `Odstraněno dne`.)

- [ ] **Step 4: Rebuild and run the integrity suite**

Run: `python build/build_data.py && python -m unittest tests.test_data_integrity.ListingDateColumnsTest -v`
Expected: PASS. On a seed-only local build the columns exist but are blank (dates only populate against real merged state — that's expected and honest).

- [ ] **Step 5: Full offline suite**

Run: `./bin/test.sh`
Expected: all green (no regression in matching / body / other integrity tests).

- [ ] **Step 6: Commit**

```bash
git add build/build_data.py tests/test_data_integrity.py
git commit -m "feat(build): carry Přidáno/Upraveno into the dashboard payload"
```

---

### Task 4: Dashboard grid columns

**Files:**
- Modify: `site/app.js` (`COL_CONFIG`)
- Verify: `build/verify_ui.py` (existing `grid` scenario, both themes)

**Interfaces:**
- Consumes: payload columns `Přidáno`/`Upraveno` (Task 3).
- Produces: two `agDateColumnFilter` grid columns reusing `DATE_FILTER_PARAMS` (the same comparator/mask machinery as `Odstraněno dne`). The capture-phase `.ag-date-filter` digit-mask listener already covers them — no extra wiring.

- [ ] **Step 1: Add the two column configs**

In `site/app.js`, in the `COL_CONFIG` array, replace the final `Zdroj` line (currently line 597):

```js
    { field: "Zdroj", filter: "agSetColumnFilter", w: 100 },
```

with (dates as the trailing columns, matching the reference page's convention):

```js
    { field: "Zdroj", filter: "agSetColumnFilter", w: 100 },
    { field: "Přidáno", filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, w: 100, hdr: "Přidáno", tip: "Datum, kdy byl inzerát poprvé zachycen scraperem. Prázdné = inzerát existoval před zavedením sledování." },
    { field: "Upraveno", filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, w: 100, hdr: "Upraveno", tip: "Datum poslední změny údajů od prodejce (cena, nájezd, výbava…). Cena se počítá s 1% tolerancí kvůli dennímu kurzu EUR→Kč. Prázdné = od zavedení sledování beze změny." },
```

- [ ] **Step 2: Verify the grid renders (dark)**

Run: `python build/verify_ui.py --page index --scenario grid`
Expected: exit 0 (no console errors, grid rendered). Screenshot at `tmp/ui-verify/index-grid-dark.png`.

- [ ] **Step 3: Read the dark screenshot**

Read `tmp/ui-verify/index-grid-dark.png`. Confirm the grid renders with no error overlay. (The new columns sit at the far right; scroll isn't captured, so absence from the frame is fine — Step 5 confirms them directly.)

- [ ] **Step 4: Verify + Read the light theme**

Run: `python build/verify_ui.py --page index --scenario grid --theme light`
Read `tmp/ui-verify/index-grid-light.png`. Expected: exit 0, no visual regression.

- [ ] **Step 5: Confirm the columns exist in the grid**

Run:
```bash
python build/verify_ui.py --page index --scenario grid >/dev/null 2>&1 || true
python - <<'PY'
# Sanity: the two fields are in COL_CONFIG exactly once each.
import re, pathlib
src = pathlib.Path("site/app.js").read_text(encoding="utf-8")
for f in ("Přidáno", "Upraveno"):
    n = len(re.findall(r'field:\s*"%s"' % re.escape(f), src))
    assert n == 1, f"{f}: expected 1 COL_CONFIG entry, found {n}"
print("OK: both lifecycle date columns declared once")
PY
```
Expected: `OK: both lifecycle date columns declared once`.

- [ ] **Step 6: Commit**

```bash
git add site/app.js
git commit -m "feat(site): show Přidáno/Upraveno date columns in the listings grid"
```

---

### Task 5: Docs + full verification + final gate

**Files:**
- Modify: `docs/gotchas.md`, `docs/architecture.md`, `CLAUDE.md`

**Interfaces:** none (documentation + final verification only).

- [ ] **Step 1: Document the mechanism in gotchas**

Add a subsection under `## core — merge_with_previous` in `docs/gotchas.md`:

```markdown
### listing lifecycle dates (Přidáno / Upraveno) are merge-stamped, not git-derived

Unlike the reference CSVs (git-tracked → `build/backfill_ref_dates.py`), scraped
listings are not in git, so `merge_with_previous()` stamps their lifecycle dates
from the new-vs-previous comparison:

- **genuinely new link** → `Přidáno = Upraveno = today` (also the `prev is None`
  path: a brand-new source's first scrape stamps every row today).
- **link in both scrapes** → carry `Přidáno` forward; bump `Upraveno` to today
  only when **seller content** changed (`_seller_content_changed`).
- **removed link** → carry both unchanged (removal is `Odstraněno dne`, not an edit).
- **existing state that predates the feature** (columns absent) → blank, filling
  forward (there is no honest date to backfill ~150k rows).

"Seller content" = a sha1 over `CANONICAL_COLS` minus `_DATE_HASH_EXCLUDE`
(`Přidáno`/`Upraveno`/`Odstraněno dne`/`Stav`/`Spárováno`/`Skóre shody`/`Model auta`/
`Odkaz na auto`/`Cena (Kč)`). The match-verdict trio (`Spárováno`/`Skóre shody`/
`Model auta`) is excluded on purpose: a **reference-list edit re-matches rows and
rewrites those columns but must not bump `Upraveno`**. Price is compared separately
with a **1% relative tolerance** (`_PRICE_REL_TOL`) because mobile.de's Kč is
EUR×CNB-daily-fixing and drifts sub-percent day to day — a real price move still
bumps, FX jitter doesn't. `build_data.main()` guard-creates the two columns blank
on a seed-only build (merge not run) so the payload schema is stable. Shown as
`agDateColumnFilter` grid columns like `Odstraněno dne`. Pinned by
`tests/test_merge.py::LifecycleDateTest` and
`tests/test_data_integrity.py::ListingDateColumnsTest`.
```

- [ ] **Step 2: Update architecture.md data-flow note**

In `docs/architecture.md`, in the `pipeline.run_source():` data-flow block, change the merge line from:

```text
   → merge_with_previous()  (stamp vanished listings "Odstraněno" + "Odstraněno dne",
                             drop removed rows older than 60 days)
```

to:

```text
   → merge_with_previous()  (stamp vanished listings "Odstraněno" + "Odstraněno dne";
                             stamp listing lifecycle dates "Přidáno"/"Upraveno";
                             drop removed rows older than 60 days)
```

- [ ] **Step 3: Update the CLAUDE.md schema block**

In `CLAUDE.md`, under `## Canonical Schema`, append `Přidáno` and `Upraveno` to the schema listing (after `Odkaz na auto`), and add one line to the field descriptions:

```text
`Přidáno` / `Upraveno` (listings) = merge-stamped lifecycle dates — first seen /
seller-content last changed (1% price tolerance for FX jitter); blank for state
that predates the feature. Reference-row equivalents are git-derived
(`build/backfill_ref_dates.py`); listing ones are stamped in `merge_with_previous`.
```

- [ ] **Step 4: Full offline suite + UI gate**

Run:
```bash
./bin/test.sh
python build/verify_ui.py --page index --scenario grid
python build/verify_ui.py --page index --scenario grid --theme light
```
Expected: `./bin/test.sh` all green; both verify runs exit 0. Read both screenshots once more to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add docs/gotchas.md docs/architecture.md CLAUDE.md
git commit -m "docs: document listing lifecycle dates (Přidáno/Upraveno)"
```

---

## Self-Review

**Spec coverage:**
- Merge-layer mechanism → Task 2. ✓
- Schema (trailing cols, blank_row) → Task 1. ✓
- Blank backfill (prev lacks cols) → Task 2 `test_prev_without_date_columns_leaves_blank`. ✓
- Seller-fields-only + match-verdict exclusion → Task 2 `_DATE_HASH_EXCLUDE` + `test_model_auta_change_alone_does_not_bump` / `test_match_score_change_alone_does_not_bump`. ✓
- Price 1% tolerance (FX) → Task 2 `_price_changed` + jitter/real-move tests. ✓
- Build payload + seed-only guard → Task 3. ✓
- Grid display (both shown) → Task 4. ✓
- Tests (merge, schema, data-integrity) → Tasks 1–3. ✓
- Docs → Task 5. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows full, runnable code (the twelve `LifecycleDateTest` cases are complete as written).

**Type consistency:** `_content_hash`, `_price_changed`, `_seller_content_changed`, `_to_price`, `_cell`, `_keep_removed` names consistent across Task 2 code and the docs. `DATE_FILTER_PARAMS` reused verbatim from the existing `Odstraněno dne` column. `_records` / `_ISO_DATE_RE` reused from the existing integrity module. Column names byte-identical (`Přidáno`, `Upraveno`, `Cena (Kč)`) everywhere.
