"""Shared post-scrape pipeline: dedup → ICE auth-match → merge-with-previous → write parquet state."""
from pathlib import Path
import pandas as pd

from .schema import CANONICAL_COLS, ANO_NE_COLS, TYP_ICE
from .merge import merge_with_previous
from . import matching, storage, fields

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# None = storage.state_dir() at run time (honours CAR_COMPARE_STATE_DIR); tests patch it.
SCRAPES_DIR = None
AUTH_CSV = DATA_DIR / "reference" / "ice_specs.csv"


def _match_ice(df, auth_list):
    """Run authoritative matching on ICE rows only; leave EV rows untouched."""
    if "Spárováno" not in df.columns:
        df["Spárováno"] = ""
    ice_mask = df["Typ"] == TYP_ICE
    if ice_mask.any():
        ice = df[ice_mask].copy()
        ice = matching.match_to_authoritative(ice, auth_list)
        df.loc[ice_mask, ice.columns] = ice.values
    return df


def _normalize_ano_ne_columns(df):
    """Normalize all boolean Ano/Ne columns to proper case (case-insensitive + trim)."""
    for col in ANO_NE_COLS:
        if col in df.columns:
            df[col] = df[col].apply(fields.normalize_ano_ne)
    return df


def run_source(source_module):
    """Execute a source adapter and persist its parquet state via the shared pipeline."""
    import asyncio
    rows = asyncio.run(source_module.scrape())
    df = pd.DataFrame(rows, columns=CANONICAL_COLS)
    del rows   # ~150k row dicts for mobile.de; the frame holds the same cells
    df.drop_duplicates(subset="Odkaz na auto", inplace=True)
    df.sort_values("Odkaz na auto", inplace=True)

    auth = matching.load_authoritative_list(AUTH_CSV)
    df = _match_ice(df, auth)

    scrapes_dir = SCRAPES_DIR or storage.state_dir()
    scrapes_dir.mkdir(parents=True, exist_ok=True)
    base_path = scrapes_dir / source_module.SOURCE_SLUG
    df = merge_with_previous(df, base_path)
    # Reindex to the canonical schema so column order is stable and any column added
    # since the previous state (e.g. "Odstraněno dne") is present/blank on preserved rows.
    df = df.reindex(columns=CANONICAL_COLS)
    # Normalize all boolean Ano/Ne columns to proper case
    df = _normalize_ano_ne_columns(df)
    out_path = storage.write_state(df, base_path)
    print(f"Hotovo – uloženo {len(df)} aut do {out_path.name}")
    return out_path
