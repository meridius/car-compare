"""grow-reference: find missing reference models from unpaired listings, research
their specs (agentic), and grow ev_specs.csv / ice_specs.csv behind a review gate.

Deterministic core — offline, unit-tested. Run as a script:
    python3 build/reference_gap.py gaps --fuel ev --rebuild
"""
import csv
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from scrapers.core.normalize import normalize_model  # noqa: E402

FUELS = {"ev": "Elektrické", "ice": "Spalovací"}
REF_FILES = {"ev": "ev_specs.csv", "ice": "ice_specs.csv"}
ID_COL = {"ev": "Model auta", "ice": "Jednoznačná varianta vozu"}
EV_RANGES = {
    "Objem kufru (l)": (50, 900),
    "Hlučnost (dB)": (50, 85),
    "Kapacita baterie (kWh)": (10, 150),
    "Dojezd komb. letní WLTP (km)": (100, 800),
    "Dojezd komb. letní EV-database (km)": (100, 800),
    "Cd": (0.20, 0.45),
}
CARS_JSON = os.path.join(BASE_DIR, "site", "data", "cars.json")
REF_DIR = os.path.join(BASE_DIR, "scrapers", "data", "reference")

# spec tokens stripped when deriving a model grouping key (powertrain/battery/hp noise)
_KEY_STRIP = re.compile(
    r"\b(\d{2,3}\s?(kw|ps|hp|k)|\d{2,3}([.,]\d)?\s?kwh|e-?tech|e-?tec|awd|4wd|"
    r"long\s?range|comfort|design|style|extended)\b",
    re.IGNORECASE,
)


def load_unpaired_from_rows(rows, fuel):
    typ = FUELS[fuel]
    return [r for r in rows if r.get("Typ") == typ and r.get("Spárováno") == "Ne"]


def load_unpaired(cars_json_path, fuel):
    with open(cars_json_path, encoding="utf-8") as f:
        rows = json.load(f)["data"]
    return load_unpaired_from_rows(rows, fuel)


def _canonical_key(name):
    n = normalize_model(name or "").lower()
    n = _KEY_STRIP.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def _shared_prefix(names):
    """Longest word-boundary prefix common to all raw names in a cluster."""
    if not names:
        return ""
    split = [n.split() for n in names]
    out = []
    for i in range(min(len(w) for w in split)):
        tok = split[0][i]
        if all(w[i] == tok for w in split):
            out.append(tok)
        else:
            break
    return " ".join(out) if out else names[0]


def cluster(listings, fuel):
    groups = {}
    for r in listings:
        key = _canonical_key(r.get("Model auta", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(r)
    clusters = []
    for key, members in groups.items():
        names = [m.get("Model auta", "") for m in members]
        clusters.append({
            "key": key,
            "prefix": _shared_prefix(names) or names[0],
            "volume": len(members),
            "sample_names": sorted(set(names))[:5],
            "sample_links": [m.get("Odkaz na auto", "") for m in members[:3]],
        })
    clusters.sort(key=lambda c: c["volume"], reverse=True)
    return clusters
