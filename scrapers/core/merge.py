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

    result_rows = []
    for _, row in prev.iterrows():
        link = row["Odkaz na auto"]
        if not link:
            continue
        # Find the row in the new DataFrame by link, preserving all columns
        new_rows = df[df["Odkaz na auto"] == link]
        if len(new_rows) > 0:
            result_rows.append(new_rows.iloc[0].to_dict())
        else:
            row = row.copy()
            row["Stav"] = "Odstraněno"
            result_rows.append(row)
    # Add genuinely new listings (not in prev) at the end
    prev_links = set(prev["Odkaz na auto"])
    for _, row in df.iterrows():
        if row["Odkaz na auto"] not in prev_links:
            result_rows.append(row.to_dict())
    return pd.DataFrame(result_rows).reset_index(drop=True)
