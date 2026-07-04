"""Merge new scrape with previous state, preserving removed listings.

Removed listings are kept with Stav="Odstraněno" and stamped with the date they
were first seen missing ("Odstraněno dne"). Rows removed more than
REMOVED_RETENTION_DAYS ago are dropped from the state file — the live dataset
plateaus instead of growing forever, and full history survives in the monthly
snapshot releases (retention 60 d > snapshot interval 31 d, so every row lands
in at least one immutable snapshot). See docs/decisions/001-scalable-storage.md.
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import storage

REMOVED_RETENTION_DAYS = 60


def _keep_removed(row, cutoff: date) -> bool:
    """True when a previously-removed row is still within the retention window."""
    try:
        removed_on = date.fromisoformat(row.get("Odstraněno dne", ""))
    except ValueError:
        return True  # blank/garbage stamp — keep, caller re-stamps
    return removed_on >= cutoff


def merge_with_previous(df: pd.DataFrame, base_path: Path, today: date | None = None) -> pd.DataFrame:
    """Merge new scrape with previous state, preserving row order from previous state."""
    today = today or date.today()
    cutoff = today - timedelta(days=REMOVED_RETENTION_DAYS)

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
