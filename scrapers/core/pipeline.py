"""Shared post-scrape pipeline: dedup → ICE auth-match → merge-with-previous → write CSV."""
from pathlib import Path
import pandas as pd

from .schema import CANONICAL_COLS, TYP_ICE
from .merge import merge_with_previous
from . import matching

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCRAPES_DIR = DATA_DIR / "scrapes"
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


def run_source(source_module):
    """Execute a source adapter and persist its CSV via the shared pipeline."""
    import asyncio
    rows = asyncio.run(source_module.scrape())
    df = pd.DataFrame(rows, columns=CANONICAL_COLS)
    df.drop_duplicates(subset="Odkaz na auto", inplace=True)
    df.sort_values("Odkaz na auto", inplace=True)

    auth = matching.load_authoritative_list(AUTH_CSV)
    df = _match_ice(df, auth)

    SCRAPES_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = SCRAPES_DIR / f"{source_module.SOURCE_SLUG}.csv"
    df = merge_with_previous(df, csv_path)
    # Reindex to the canonical schema so column order is stable and any column added
    # since the previous CSV (e.g. "Skóre shody") is present/blank on preserved rows.
    df = df.reindex(columns=CANONICAL_COLS)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"Hotovo – uloženo {len(df)} aut do {source_module.SOURCE_SLUG}.csv")
    return csv_path
