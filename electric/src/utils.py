"""Shared utilities for car scrapers."""

import re
from pathlib import Path

import pandas as pd

# Short aliases for verbose brand names applied to scraped model strings
BRAND_MAP = {
    "Volkswagen": "VW",
}

# Regex substitutions applied after brand normalisation to fix common naming errors.
# Each entry is (compiled_pattern, replacement_string).
MODEL_CLEANUP_PATTERNS = [
    # "Škoda Enyaq 50/60/80" → "Škoda Enyaq iV 50/60/80"  (variant number without "iV")
    (re.compile(r'(Škoda Enyaq)(?!\s+iV)\s+(\d{2})\b'), r'\1 iV \2'),
]

BODY_KEYWORDS = [
    "Sports Tourer",
    "SW", "Combi", "Variant", "Touring",
    "Fastback", "Allspace", "SUV", "Sportback",
]


def extract_body_type(text: str) -> str:
    """Extract body type (SW, Combi, Fastback, etc.)."""
    for kw in BODY_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            return kw
    return ""


def normalize_model(model: str) -> str:
    """Replace a verbose brand prefix with its short alias and apply cleanup rules."""
    for full, short in BRAND_MAP.items():
        if model == full or model.startswith(full + " "):
            model = short + model[len(full):]
            break
    for pattern, replacement in MODEL_CLEANUP_PATTERNS:
        model = pattern.sub(replacement, model)
    return model


def merge_with_previous(df: pd.DataFrame, csv_path: Path) -> pd.DataFrame:
    """Merge new scrape with previous CSV, marking removed listings as 'Odstraněno'."""
    if not csv_path.exists():
        return df

    prev = pd.read_csv(csv_path, encoding="utf-8", dtype=str).fillna("")
    if "Odkaz na auto" not in prev.columns:
        return df

    new_links = set(df["Odkaz na auto"])
    removed = prev[~prev["Odkaz na auto"].isin(new_links)].copy()
    removed["Stav"] = "Odstraněno"

    merged = pd.concat([df, removed], ignore_index=True)
    merged.drop_duplicates(subset="Odkaz na auto", keep="first", inplace=True)
    return merged
