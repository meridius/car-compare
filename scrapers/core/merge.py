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


def _content_hash(row, cols) -> str:
    """Stable hash of a row over the given content columns (see _DATE_HASH_EXCLUDE)."""
    payload = "\x1f".join(f"{c}\x1e{_cell(row, c)}" for c in cols)
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
    # Compare only content columns present in BOTH rows. Introducing a new
    # canonical column (absent from state written by an older code version) then
    # never counts as a seller edit — mirrors backfill_ref_dates' schema-migration
    # idempotency. A real edit to a shared column still bumps.
    cols = [c for c in _CONTENT_COLS if c in new_row and c in prev_row]
    if _content_hash(new_row, cols) != _content_hash(prev_row, cols):
        return True
    return _price_changed(new_row, prev_row)


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
