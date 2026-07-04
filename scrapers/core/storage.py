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


def write_state(df: pd.DataFrame, base_path: Path) -> Path:
    path = Path(base_path).with_suffix(".parquet")
    _stringly(df).to_parquet(path, compression=PARQUET_COMPRESSION, index=False)
    return path


def read_state(base_path: Path) -> pd.DataFrame | None:
    base_path = Path(base_path)
    parquet = base_path.with_suffix(".parquet")
    if parquet.exists():
        return _stringly(pd.read_parquet(parquet))
    csv = base_path.with_suffix(".csv")
    if csv.exists():
        return pd.read_csv(csv, dtype=str).fillna("")
    return None
