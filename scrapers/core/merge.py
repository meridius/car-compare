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

import numpy as np
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

    return _merge_frames(df, prev, today_iso, cutoff)


def _cells(series: pd.Series) -> list:
    """Per-cell `_cell()` for a whole column: None -> "", everything else str()."""
    return ["" if v is None else str(v) for v in series.tolist()]


def _content_keys(frame: pd.DataFrame, cols) -> list:
    """The `_content_hash()` payload per row, unhashed (equality is all we need)."""
    columns = [[f"{c}\x1e{v}" for v in _cells(frame[c])] for c in cols]
    return ["\x1f".join(parts) for parts in zip(*columns)] if columns else [""] * len(frame)


def _column_or_blank(frame: pd.DataFrame, col: str) -> pd.Series:
    """frame[col], or "" per row when the column is absent (dict .get(col, ""))."""
    return frame[col] if col in frame.columns else pd.Series([""] * len(frame), index=frame.index)


def _price_changed_many(new_prices: pd.Series, prev_prices: pd.Series) -> list:
    return [_price_changed({_PRICE_COL: b}, {_PRICE_COL: a})
            for b, a in zip(new_prices.tolist(), prev_prices.tolist())]


def _valid_iso(values) -> list:
    out = []
    for v in values:
        try:
            date.fromisoformat(v)
            out.append(True)
        except (TypeError, ValueError):
            out.append(False)
    return out


def _merge_frames(df: pd.DataFrame, prev: pd.DataFrame, today_iso: str, cutoff) -> pd.DataFrame:
    """Column-wise merge — the same result as walking prev row by row.

    Row order: every previous row with a link, in previous order, becomes either
    its (first) new-scrape row or a kept removed row; genuinely new links follow
    in scrape order. It used to build one dict per output row (~360k for
    mobile.de) and a DataFrame from them, which doubled the merge's memory and
    OOM-killed the scrape on a 2 GB host; frames slice and concat instead, and
    only share the cell objects.
    """
    link = "Odkaz na auto"
    new_cols = list(df.columns) + [c for c in ("Přidáno", "Upraveno") if c not in df.columns]
    prev_links = set(prev[link].tolist())

    live = prev[prev[link].map(bool)]
    first = df.drop_duplicates(subset=link, keep="first")
    at = pd.Index(first[link]).get_indexer(live[link])
    in_new = at >= 0
    order = np.arange(len(live))

    # Present in both: the new row; carry Přidáno, bump Upraveno on a real edit.
    pm = live[in_new]
    matched = first.iloc[at[in_new]].reindex(columns=new_cols)
    shared = [c for c in _CONTENT_COLS if c in df.columns and c in prev.columns]
    changed = [a != b or p for a, b, p in zip(
        _content_keys(matched, shared), _content_keys(pm, shared),
        _price_changed_many(_column_or_blank(first, _PRICE_COL).iloc[at[in_new]],
                            _column_or_blank(pm, _PRICE_COL)))]
    matched["Přidáno"] = pm["Přidáno"].tolist()
    matched["Upraveno"] = np.where(changed, today_iso, pm["Upraveno"].to_numpy(dtype=object))
    matched.index = order[in_new]

    # Gone from the scrape: marked removed (and dropped past retention).
    removed = live[~in_new].copy()
    removed.index = order[~in_new]
    if cutoff is not None:
        was_removed = (removed["Stav"] == "Odstraněno").to_numpy()
        stamps = removed["Odstraněno dne"].tolist()
        within = [not ok or date.fromisoformat(v) >= cutoff
                  for v, ok in zip(stamps, _valid_iso(stamps))]
        removed = removed[~was_removed | np.array(within, dtype=bool)]
    removed["Stav"] = "Odstraněno"
    stamped = np.array(_valid_iso(removed["Odstraněno dne"].tolist()), dtype=bool)
    removed.loc[~stamped, "Odstraněno dne"] = today_iso

    fresh = df[~df[link].isin(prev_links)].reindex(columns=new_cols)
    fresh["Přidáno"] = today_iso
    fresh["Upraveno"] = today_iso

    # Columns in first-appearance order over the rows actually emitted, as a
    # frame built from the rows would have them; dtypes re-inferred likewise.
    kept = matched.index.union(removed.index)
    kinds = []
    if len(kept):
        kinds = [removed, matched] if kept[0] in removed.index else [matched, removed]
    kinds.append(fresh)
    columns = []
    for part in kinds:
        if len(part):
            columns += [c for c in part.columns if c not in columns]
    body = pd.concat([matched, removed]).sort_index(kind="stable")
    out = pd.concat([body, fresh], ignore_index=True)
    if not len(out):
        return pd.DataFrame()
    return out.reindex(columns=columns).infer_objects()
