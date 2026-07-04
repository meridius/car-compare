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
import unicodedata

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


def _fold_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _canonical_key(name):
    n = _fold_accents(normalize_model(name or "")).lower()
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


def load_reference_models(fuel):
    path = os.path.join(REF_DIR, REF_FILES[fuel])
    with open(path, newline="", encoding="utf-8") as f:
        return [row[ID_COL[fuel]] for row in csv.DictReader(f) if row.get(ID_COL[fuel])]


def _prefix_matches(name, ref_low):
    nl = name.lower()
    return any(nl.startswith(r) for r in ref_low)


def classify(cluster, ref_models):
    ref_low = [r.lower() for r in ref_models]
    raws = cluster.get("sample_names") or [cluster["prefix"]]
    if any(_prefix_matches(n, ref_low) for n in raws):
        return "covered"  # sanity: raw already matches a ref prefix (should have been Ano)
    if any(_prefix_matches(normalize_model(n), ref_low) for n in raws):
        return "normalization_gap"  # a BRAND_MAP/cleanup fix would pair it — not a new row
    return "missing_ref"


def _ev_header():
    path = os.path.join(REF_DIR, REF_FILES["ev"])
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def ev_columns():
    return _ev_header()


def project_newly_paired(prefixes, unpaired):
    names = [str(r.get("Model auta", "")).lower() for r in unpaired]
    out = {}
    for p in prefixes:
        pl = p.lower()
        out[p] = sum(1 for n in names if n.startswith(pl))
    return out


def stub_row(cluster, fuel):
    if fuel != "ev":
        raise NotImplementedError("ICE stub handled in ICE mode task")
    row = {col: "" for col in ev_columns()}
    row["Model auta"] = cluster["prefix"]
    return row


def _num(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def validate_rows(rows, fuel, ref_models, unpaired):
    cols = ev_columns()  # EV only for now
    ref_low = [r.lower() for r in ref_models]
    unpaired_low = [str(r.get("Model auta", "")).lower() for r in unpaired]
    ok, errs = [], []
    seen = set()
    for i, raw in enumerate(rows):
        clean = {c: raw.get(c, "") for c in cols}
        model = str(clean.get("Model auta", "")).strip()
        problems = []
        if not model:
            problems.append(f"row {i}: prázdné 'Model auta'")
        # numeric ranges
        for col, (lo, hi) in EV_RANGES.items():
            rawv = str(clean.get(col, "")).strip()
            if rawv == "":
                continue
            val = _num(rawv)
            if val is None:
                problems.append(f"row {i} ({model}): {col}='{rawv}' není číslo")
            elif not (lo <= val <= hi):
                label = "baterie" if "baterie" in col else col
                problems.append(f"row {i} ({model}): {label}={val} mimo rozsah {lo}-{hi}")
        # Cd zdroj enum (only when Cd present)
        if str(clean.get("Cd", "")).strip():
            if clean.get("Cd zdroj") not in ("reálné", "odhad"):
                problems.append(f"row {i} ({model}): 'Cd zdroj' musí být reálné/odhad")
        # heat pump enum
        hp = str(clean.get("Tepelné čerpadlo možné (ano/ne)", "")).strip()
        if hp and hp not in ("ano", "ne"):
            problems.append(f"row {i} ({model}): tepelné čerpadlo musí být ano/ne")
        # duplicate vs existing + within-batch
        ml = model.lower()
        if ml in ref_low or ml in seen:
            problems.append(f"row {i} ({model}): duplicitní 'Model auta'")
        # over-broad prefix: a reference prefix must be at least brand+model (2 tokens);
        # a bare brand ("Renault") would pair unrelated cars.
        if model and len(model.split()) < 2 and any(n.startswith(ml) for n in unpaired_low):
            problems.append(f"row {i} ({model}): příliš obecný prefix (jen značka)")
        if problems:
            errs.extend(problems)
        else:
            seen.add(ml)
            ok.append(clean)
    return ok, errs
