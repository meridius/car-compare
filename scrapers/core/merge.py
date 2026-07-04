"""Merge new scrape with previous state, preserving removed listings.

Removed listings are kept with Stav="Odstraněno" and stamped with the date they
were first seen missing ("Odstraněno dne"). By default they are kept forever:
the dashboard splits them into a lazy-loaded archive (decision 001, option C),
so the live payload stays bounded by the market while full history is available
on demand and permanently in the monthly snapshot releases.

`retention_days` is an optional cap — pass an int to drop rows removed longer
ago than that (useful if the archive ever needs bounding). None = keep all.
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import storage

# None = keep every removed row (archive is unbounded, snapshots are permanent).
# Set to an int to cap how long removed listings survive in live state.
REMOVED_RETENTION_DAYS = None


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
    cutoff = None if retention_days is None else today - timedelta(days=retention_days)

    prev = storage.read_state(base_path)
    if prev is None or "Odkaz na auto" not in prev.columns:
        return df
    if "Odstraněno dne" not in prev.columns:
        prev = prev.assign(**{"Odstraněno dne": ""})

    result_rows = []
    for _, row in prev.iterrows():
        link = row["Odkaz na auto"]
        if not link:
            continue
        # Find the row in the new DataFrame by link, preserving all columns
        new_rows = df[df["Odkaz na auto"] == link]
        if len(new_rows) > 0:
            result_rows.append(new_rows.iloc[0].to_dict())
            continue
        row = row.copy()
        if row["Stav"] == "Odstraněno" and not _keep_removed(row, cutoff):
            continue
        row["Stav"] = "Odstraněno"
        try:
            date.fromisoformat(row["Odstraněno dne"])
        except ValueError:
            row["Odstraněno dne"] = today.isoformat()
        result_rows.append(row.to_dict())
    # Add genuinely new listings (not in prev) at the end
    prev_links = set(prev["Odkaz na auto"])
    for _, row in df.iterrows():
        if row["Odkaz na auto"] not in prev_links:
            result_rows.append(row.to_dict())
    return pd.DataFrame(result_rows).reset_index(drop=True)
