"""Merge new scrape with previous CSV, preserving removed listings."""
from pathlib import Path

import pandas as pd


def merge_with_previous(df: pd.DataFrame, csv_path: Path) -> pd.DataFrame:
    """Merge new scrape with previous CSV, preserving row order from previous CSV."""
    if not csv_path.exists():
        return df

    prev = pd.read_csv(csv_path, encoding="utf-8", dtype=str).fillna("")
    if "Odkaz na auto" not in prev.columns:
        return df

    new_by_link = df.set_index("Odkaz na auto")
    result_rows = []
    for _, row in prev.iterrows():
        link = row["Odkaz na auto"]
        if not link:
            continue
        if link in new_by_link.index:
            result_rows.append(new_by_link.loc[link])
        else:
            row = row.copy()
            row["Stav"] = "Odstraněno"
            result_rows.append(row)
    # Add genuinely new listings (not in prev) at the end
    prev_links = set(prev["Odkaz na auto"])
    for _, row in df.iterrows():
        if row["Odkaz na auto"] not in prev_links:
            result_rows.append(row)
    return pd.DataFrame(result_rows).reset_index(drop=True)
