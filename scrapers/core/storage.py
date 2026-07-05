"""Parquet state files with frozen-CSV seed fallback.

One state file per source: `scrapers/data/scrapes/<slug>.parquet`. Paths are
passed WITHOUT extension; `read_state` prefers the parquet, falls back to the
git-tracked seed CSV (bootstrap / offline dev), and returns None when neither
exists.

State is stringly-typed: every column str, blanks "" — exact parity with the
old `pd.read_csv(dtype=str).fillna("")` contract that merge/matching rely on.
"""
from pathlib import Path

import pandas as pd

PARQUET_COMPRESSION = "zstd"


def _stringly(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce every cell to str with blanks as "" (never NaN/"nan")."""
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].astype(object).where(out[col].notna(), "").astype(str)
    return out


# Column renames applied to state read from disk, oldest first. Old parquet/CSV
# state files (and the frozen seed CSVs) still carry the pre-rename header; this
# is the single choke point every reader (pipeline merge, build_data) goes
# through, so callers never need to know a column was ever named differently.
_COLUMN_RENAMES = {
    "Výbava": "Verze",  # Verze column plumbing (2026-07-05)
}


def _apply_column_renames(df: pd.DataFrame) -> pd.DataFrame:
    renames = {old: new for old, new in _COLUMN_RENAMES.items()
               if old in df.columns and new not in df.columns}
    return df.rename(columns=renames) if renames else df


def write_state(df: pd.DataFrame, base_path: Path) -> Path:
    path = Path(base_path).with_suffix(".parquet")
    _stringly(df).to_parquet(path, compression=PARQUET_COMPRESSION, index=False)
    return path


def read_state(base_path: Path) -> pd.DataFrame | None:
    base_path = Path(base_path)
    parquet = base_path.with_suffix(".parquet")
    if parquet.exists():
        return _apply_column_renames(_stringly(pd.read_parquet(parquet)))
    csv = base_path.with_suffix(".csv")
    if csv.exists():
        return _apply_column_renames(pd.read_csv(csv, dtype=str).fillna(""))
    return None
