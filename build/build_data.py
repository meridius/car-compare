import pandas as pd
import json
import os
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Combustion authoritative matching is re-run at build time so that ALL cars —
# including listings already removed from source providers (frozen rows that the
# scraper never re-processes) — get backed by the current reference list.
sys.path.insert(0, BASE_DIR)
from scrapers.core import matching as comb_utils  # noqa: E402
from scrapers.core.normalize import normalize_model as _normalize_model  # noqa: E402

# Status/promo banners that leak into "Model auta" from autodraft cards and break
# brand parsing (e.g. "domluvená prohlídka Škoda Karoq 2.0 TDI").
_NOISE_PREFIX_RE = re.compile(
    r'^(?:\d+\s*let[áa]\s+z[áa]ruka\s+te[ďd]\s+zdarma'
    r'|domluven[áa]\s+prohl[íi]dka'
    r'|z[áa]lohovan[éoa]'
    r'|zarezervovan[éoa]'
    r'|rezervov[áa]n[oa]'
    r'|prodan[éoa]'
    r'|zamluven[éoa])\s+',
    re.IGNORECASE,
)


def strip_listing_noise(model):
    """Remove leading status/promo banners that leaked into the model name."""
    if not isinstance(model, str):
        return model
    prev = None
    while prev != model:
        prev = model
        model = _NOISE_PREFIX_RE.sub("", model).strip()
    return model


def fix_electric_model(model):
    """Strip noise and heal frozen sauto 'Ostatní' garbage names (mirrors the
    electric sauto scraper's _recover_ostatni_model, for rows scraped before the
    fix landed). Kia EV2 = project code 'QV1' or its unique 42.2 kWh battery."""
    m = strip_listing_noise(model)
    if isinstance(m, str) and m.startswith("Kia ") and (
        "QV1" in m.upper() or re.search(r'42[.,]2', m)
    ):
        return "Kia EV2"
    return m


# --- Body / fuel backfill -------------------------------------------------
# The "Karoserie × Pohon" overview reads scraped Karoserie/Palivo; many cards
# omit them, dumping the car into the "Nezadáno" bucket. Once a row is matched
# to a reference model we can derive body (and combustion fuel) deterministically
# from the model name, falling back to a per-model body map for bodyless names.

_BODY_NAME_RULES = [
    (re.compile(r'\bShooting Brake\b', re.I), "Kombi"),
    (re.compile(r'\b(?:Combi|Kombi|Variant|Avant|Tourer|Touring|Sports Tourer|SW)\b', re.I), "Kombi"),
    (re.compile(r'\b(?:Liftback|Sportback|Fastback)\b', re.I), "Liftback"),
    (re.compile(r'\bHatchback\b', re.I), "Hatchback"),
    (re.compile(r'\b(?:Targa|Coup[ée]|Kabrio|Cabrio)\b', re.I), "Kupé"),
    (re.compile(r'\bSUV\b', re.I), "SUV"),
    (re.compile(r'\bSedan\b', re.I), "Sedan"),
]

# Substring (lowercased) -> body, for model names that carry no body keyword.
# Order matters: more specific tokens first (e.g. "c40" before "c4").
_BODY_MODEL_MAP = [
    ("stelvio", "SUV"), ("e-tron", "SUV"), ("bmw ix", "SUV"), ("x1", "SUV"),
    ("baic x3", "SUV"), ("baic x5", "SUV"), ("c3 aircross", "SUV"), ("formentor", "SUV"),
    ("ds 7", "SUV"), ("bigster", "SUV"), ("duster", "SUV"), ("kuga", "SUV"),
    ("kona", "SUV"), ("santa fe", "SUV"), ("tucson", "SUV"), ("korando", "SUV"),
    ("torres", "SUV"), ("sportage", "SUV"), ("mg hs", "SUV"), ("mg zs", "SUV"),
    ("glb", "SUV"), ("mokka", "SUV"), ("arkana", "SUV"), ("captur", "SUV"),
    ("symbioz", "SUV"), ("arona", "SUV"), ("ateca", "SUV"), ("tarraco", "SUV"),
    ("t-roc", "SUV"), ("taigo", "SUV"), ("tiguan", "SUV"), ("xc60", "SUV"),
    ("xc40", "SUV"), ("kamiq", "SUV"), ("karoq", "SUV"), ("kodiaq", "SUV"),
    ("eqa", "SUV"), ("eqb", "SUV"), ("id.4", "SUV"), ("id.5", "SUV"),
    ("niro", "SUV"), ("kia ev3", "SUV"), ("tavascan", "SUV"), ("model x", "SUV"),
    ("model y", "SUV"), ("c40", "SUV"), ("leapmotor b10", "SUV"), ("iev7s", "SUV"),
    ("q4", "SUV"), ("enyaq", "SUV"),
    ("tourneo", "MPV"), ("staria", "MPV"), ("caddy", "MPV"), ("sharan", "MPV"),
    ("multivan", "MPV"), ("touran", "MPV"), ("transporter", "MPV"), ("crafter", "MPV"),
    ("bmw 2", "MPV"),
    ("a6", "Sedan"), ("a8", "Sedan"), ("bmw 3", "Sedan"), ("c 220", "Sedan"),
    ("k4", "Sedan"), ("byd seal", "Sedan"), ("eqe", "Sedan"), ("model 3", "Sedan"),
    ("c5 x", "Liftback"), ("octavia", "Liftback"),
    ("i20", "Hatchback"), ("scala", "Hatchback"), ("c4", "Hatchback"),
    ("bmw i3", "Hatchback"), ("cupra born", "Hatchback"), ("fiat 500", "Hatchback"),
    ("honda e", "Hatchback"), ("mini cooper", "Hatchback"), ("corsa", "Hatchback"),
    ("zoe", "Hatchback"), ("id.3", "Hatchback"),
    ("v90", "Kombi"), ("proceed", "Kombi"),
]


def derive_body(model):
    """Infer canonical body type from a matched model name, or '' if unknown."""
    if not isinstance(model, str) or not model:
        return ""
    for rx, body in _BODY_NAME_RULES:
        if rx.search(model):
            return body
    low = model.lower()
    for token, body in _BODY_MODEL_MAP:
        if token in low:
            return body
    return ""


_FUEL_DIESEL_RE = re.compile(
    r'\b(?:TDI|dCi|CRDi|BlueHDi|HDi|CDTi|EcoBlue|SKYACTIV-D|BiTDI)\b|\b\d{3}d\b', re.I)
_FUEL_PETROL_RE = re.compile(
    r'\b(?:e?TSI|TFSI|T-GDI|GDI|MPI|EcoBoost|PureTech|TCe|MIVEC|SKYACTIV-G|VTi|e-TEC|GME|Turbo)\b'
    r'|\b\d[.,]\dT\b', re.I)


def derive_fuel(model, engine_type, hybrid):
    """Infer combustion fuel from model name / engine type. Defaults to Benzín
    (petrol is the unmarked-combustion majority); diesel/LPG/CNG need a marker."""
    text = f"{model} {engine_type}"
    low = text.lower()
    if "eco-g" in low or re.search(r'\bLPG\b', text, re.I):
        return "LPG + benzín"
    if re.search(r'\bCNG\b', text, re.I):
        return "CNG + benzín"
    paren = re.search(r'\(([^)]*)\)', model)
    if paren:
        pl = paren.group(1).lower()
        if "nafta" in pl or "diesel" in pl:
            return "Nafta"
        if "benzín" in pl or "benzin" in pl:
            return "Benzín"
    if _FUEL_DIESEL_RE.search(text):
        return "Nafta"
    if _FUEL_PETROL_RE.search(text) or "hybrid" in low:
        return "Benzín"
    if str(hybrid).upper() in ("HEV", "PHEV", "MHEV"):
        return "Benzín"
    return "Benzín"


def backfill_body_fuel(df):
    """Fill empty Karoserie (both suites) and Palivo (combustion) from the
    matched model name so cars stop landing in the 'Nezadáno' overview bucket."""
    def cell(idx, col):
        if col not in df.columns:
            return ""
        v = df.at[idx, col]
        return "" if (v is None or (isinstance(v, float) and v != v)) else str(v)

    for idx in df.index:
        model = cell(idx, "Model auta")
        if not cell(idx, "Karoserie").strip():
            body = derive_body(model)
            if body:
                df.at[idx, "Karoserie"] = body
        if cell(idx, "Typ") == "Spalovací" and not cell(idx, "Palivo").strip():
            fuel = derive_fuel(model, cell(idx, "Typ motoru"), cell(idx, "Hybrid typ"))
            if fuel:
                df.at[idx, "Palivo"] = fuel
    return df


def backfill_country(df):
    """Populate a blank 'Země' for the Czech-only sources whose CSVs predate the
    column (sauto/autodraft/energycars are all CZ). mobile.de rows already carry
    their per-listing country from the scrape; leave anything else untouched."""
    if "Země" not in df.columns:
        df["Země"] = ""
    zeme = df["Země"].astype("string").fillna("").str.strip()
    src = df.get("Zdroj", pd.Series("", index=df.index)).astype("string").fillna("")
    df.loc[(zeme == "") & (src != "Mobile.de"), "Země"] = "Česko"
    return df


def rematch_combustion(combustion):
    """Strip noise prefixes and re-run authoritative matching over every row."""
    if combustion.empty or "Model auta" not in combustion.columns:
        return combustion
    combustion["Model auta"] = (
        combustion["Model auta"].map(strip_listing_noise).map(_normalize_model)
    )
    auth_path = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")
    auth_list = comb_utils.load_authoritative_list(auth_path)
    return comb_utils.match_to_authoritative(combustion, auth_list)

def parse_czech_decimal(val):
    """Parse Czech decimal format: '7,4' -> 7.4, '1,6 (13,8 kWh)' -> 1.6"""
    if pd.isna(val) or val == "":
        return None
    s = str(val).strip().strip('"')
    if "(" in s:
        s = s[:s.index("(")].strip()
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def load_scraper_csvs():
    dfs = []
    scrapes = os.path.join(BASE_DIR, "scrapers", "data", "scrapes")
    for name in ["sauto", "autodraft", "energycars", "mobilede"]:
        path = os.path.join(scrapes, f"{name}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            dfs.append(df)
            print(f"  {name}: {len(df)} rows")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def load_combustion_reference():
    path = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")
    df = pd.read_csv(path)
    df["Spotřeba (l/100 km)"] = df["Spotřeba (l/100 km)"].apply(parse_czech_decimal)
    # PHEV combined consumption is the official WLTP weighted figure (~1 l/100 km,
    # assumes a charged battery) — misleading as a real-world number, so blank it.
    # Blanking here propagates to both cars.json (join) and reference.json.
    if "Hybrid typ" in df.columns:
        df.loc[df["Hybrid typ"].astype(str).str.upper() == "PHEV", "Spotřeba (l/100 km)"] = None
    return df

def load_electric_reference():
    path = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ev_specs.csv")
    df = pd.read_csv(path)  # comma-delimited, decimal cells quoted (standardized w/ ICE)
    for col in ["Kapacita baterie (kWh)"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_czech_decimal)
    return df

def join_combustion_reference(df, ref):
    """Exact join: scraped 'Model auta' = ref 'Jednoznačná varianta vozu'"""
    ref_cols = {
        "Jednoznačná varianta vozu": "Model auta",
        "Spotřeba (l/100 km)": "Spotřeba (l/100 km)",
        "Objem kufru (l)": "Objem kufru (l)",
        "Hlučnost (dB)": "Hlučnost (dB)",
        "Cd": "Cd",
        "Cd zdroj": "Cd zdroj",
    }
    ref_renamed = ref.rename(columns=ref_cols)
    add_cols = ["Spotřeba (l/100 km)", "Objem kufru (l)", "Hlučnost (dB)", "Cd", "Cd zdroj"]
    combustion_mask = df["Typ"] == "Spalovací"
    combustion = df[combustion_mask].copy()
    other = df[~combustion_mask].copy()

    merged = combustion.merge(
        ref_renamed[["Model auta"] + add_cols],
        on="Model auta",
        how="left",
        suffixes=("", "_ref")
    )
    for col in add_cols:
        ref_col = f"{col}_ref"
        if ref_col in merged.columns:
            merged[col] = merged[col].fillna(merged[ref_col])
            merged.drop(columns=[ref_col], inplace=True)

    return pd.concat([merged, other], ignore_index=True)

def join_electric_reference(df, ref):
    """Prefix match: find longest ref 'Model auta' that is prefix of scraped model."""
    electric_mask = df["Typ"] == "Elektrické"
    electric = df[electric_mask].copy()
    other = df[~electric_mask].copy()

    ref_models = ref["Model auta"].tolist()
    ref_models_sorted = sorted(ref_models, key=len, reverse=True)

    add_cols_map = {
        "Objem kufru (l)": "Objem kufru (l)",
        "Hlučnost (dB)": "Hlučnost (dB)",
        "Kapacita baterie (kWh)": "Kapacita baterie (kWh)",
        "Dojezd komb. letní WLTP (km)": "Dojezd WLTP (km)",
        "Dojezd komb. letní EV-database (km)": "Dojezd EV-database (km)",
        "Cd": "Cd",
        "Cd zdroj": "Cd zdroj",
        "Tepelné čerpadlo možné (ano/ne)": "Tepelné čerpadlo možné",
    }

    for dst_col in add_cols_map.values():
        if dst_col not in electric.columns:
            electric[dst_col] = None
        electric[dst_col] = electric[dst_col].astype(object)

    # EV is matched here by prefix join. Default every EV row to "Ne" (explicit, not
    # null) so unmatched EVs render consistently with the tri-state coloring; matched
    # rows are overwritten with "Ano" in the loop below. (Fixes EV null vs ICE "Ne".)
    if "Spárováno" not in electric.columns:
        electric["Spárováno"] = "Ne"
    electric["Spárováno"] = electric["Spárováno"].replace("", "Ne").fillna("Ne")

    ref_lookup = {}
    for _, row in ref.iterrows():
        ref_lookup[row["Model auta"]] = row

    matched = 0
    for idx, row in electric.iterrows():
        model = str(row.get("Model auta", "")).lower()
        for ref_model in ref_models_sorted:
            if model.startswith(ref_model.lower()):
                ref_row = ref_lookup[ref_model]
                for src_col, dst_col in add_cols_map.items():
                    if src_col in ref_row.index:
                        val = ref_row[src_col]
                        if pd.notna(val) and val != "":
                            if pd.isna(electric.at[idx, dst_col]) if dst_col in electric.columns else True:
                                electric.at[idx, dst_col] = val
                electric.at[idx, "Spárováno"] = "Ano"
                matched += 1
                break

    print(f"  Electric reference: {matched}/{len(electric)} matched")
    return pd.concat([other, electric], ignore_index=True)

def count_sources(df):
    """Count cars per source × type."""
    sources = {}
    for _, row in df.iterrows():
        src = str(row.get("Zdroj", ""))
        typ = str(row.get("Typ", ""))
        if src not in sources:
            sources[src] = {"electric": 0, "combustion": 0, "total": 0}
        if typ == "Elektrické":
            sources[src]["electric"] += 1
        else:
            sources[src]["combustion"] += 1
        sources[src]["total"] += 1
    return sources

def count_matching(df):
    """Count matched (Ano) / uncertain (Nejisté) / unmatched (Ne) per type.

    'uncertain' is the tri-state middle bucket: a candidate was found but the match
    is weak or ambiguous (see matching.classify_match). EV has no Nejisté state so
    its uncertain count is always 0."""
    result = {}
    for typ in ["Spalovací", "Elektrické"]:
        mask = df["Typ"] == typ
        subset = df[mask]
        col = subset.get("Spárováno", pd.Series(dtype=str))
        matched = int((col == "Ano").sum())
        uncertain = int((col == "Nejisté").sum())
        total = len(subset)
        key = "combustion" if typ == "Spalovací" else "electric"
        result[key] = {
            "matched": matched,
            "uncertain": uncertain,
            "unmatched": int(total - matched - uncertain),
            "total": int(total),
        }
    return result

# Per-listing spec columns whose value is fixed for a given car configuration and
# so make sense on the reference page. Engine vol/type/hybrid for combustion come
# from the authoritative model string (deterministic, immune to per-listing
# extraction noise); Karoserie/Výkon are aggregated from matched listings by mode
# (most-common value) — listings are the only source and mode smooths noise.

def _mode_nonempty(values):
    """Most-common non-empty / non-null value across an iterable, or None.

    Ties resolve to the first value encountered (deterministic for stable input)."""
    counts = {}
    for v in values:
        if v is None or v == "":
            continue
        if isinstance(v, float) and v != v:  # NaN
            continue
        counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def build_ice_listing_specs(df):
    """Map exact combustion 'Model auta' (authoritative string) → mode of
    Karoserie / Palivo / Výkon (kW) across its matched listings."""
    ice = df[df["Typ"] == "Spalovací"]
    out = {}
    for model, grp in ice.groupby("Model auta"):
        out[model] = {
            "Karoserie": _mode_nonempty(grp["Karoserie"]),
            "Palivo": _mode_nonempty(grp["Palivo"]),
            "Výkon (kW)": _mode_nonempty(grp["Výkon (kW)"]),
        }
    return out


def build_ev_listing_specs(df, elec_ref):
    """Map electric reference 'Model auta' → mode of Karoserie / Výkon (kW) across
    listings whose scraped model starts with that reference name (longest prefix —
    same bucketing as join_electric_reference)."""
    ev = df[df["Typ"] == "Elektrické"]
    ref_models = sorted(elec_ref["Model auta"].tolist(), key=len, reverse=True)
    buckets = {}
    for _, row in ev.iterrows():
        model = str(row.get("Model auta", "")).lower()
        for rm in ref_models:
            if model.startswith(rm.lower()):
                b = buckets.setdefault(rm, {"Karoserie": [], "Výkon (kW)": []})
                b["Karoserie"].append(row.get("Karoserie"))
                b["Výkon (kW)"].append(row.get("Výkon (kW)"))
                break
    return {
        rm: {"Karoserie": _mode_nonempty(b["Karoserie"]),
             "Výkon (kW)": _mode_nonempty(b["Výkon (kW)"])}
        for rm, b in buckets.items()
    }


def build_reference_json(comb_ref, elec_ref, df):
    """Build combined reference data JSON for the reference page."""
    records = []

    ice_path = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")
    auth_by_entry = {r["entry"]: r for r in comb_utils.load_authoritative_list(ice_path)}
    ice_specs = build_ice_listing_specs(df)
    ev_specs = build_ev_listing_specs(df, elec_ref)

    for _, row in comb_ref.iterrows():
        model = row.get("Jednoznačná varianta vozu", "")
        auth = auth_by_entry.get(model, {})
        listing = ice_specs.get(model, {})
        engine_type = auth.get("engine_type", "") or ""
        hybrid = auth.get("hybrid", "") or ""
        vol = auth.get("engine_vol", "") or ""
        palivo = listing.get("Palivo") or derive_fuel(model, engine_type, hybrid)
        karoserie = listing.get("Karoserie") or auth.get("body", "") or ""
        rec = {
            "Model auta": model,
            "Typ": "Spalovací",
            "Palivo": palivo,
            "Karoserie": karoserie,
            "Výkon (kW)": listing.get("Výkon (kW)"),
            "Objem motoru": float(vol) if vol else None,
            "Typ motoru": engine_type,
            "Hybrid typ": hybrid,
            "Spotřeba (l/100 km)": parse_czech_decimal(row.get("Spotřeba (l/100 km)", "")),
            "Objem kufru (l)": row.get("Objem kufru (l)", None),
            "Hlučnost (dB)": row.get("Hlučnost (dB)", None),
            "Cd": parse_czech_decimal(row.get("Cd", "")),
            "Cd zdroj": row.get("Cd zdroj", ""),
        }
        records.append(rec)

    for _, row in elec_ref.iterrows():
        model = row.get("Model auta", "")
        listing = ev_specs.get(model, {})
        rec = {
            "Model auta": model,
            "Typ": "Elektrické",
            "Palivo": "Elektro",
            "Karoserie": listing.get("Karoserie") or "",
            "Výkon (kW)": listing.get("Výkon (kW)"),
            "Objem motoru": None,
            "Typ motoru": "",
            "Hybrid typ": "",
            "Objem kufru (l)": row.get("Objem kufru (l)", None),
            "Hlučnost (dB)": row.get("Hlučnost (dB)", None),
            "Kapacita baterie (kWh)": parse_czech_decimal(row.get("Kapacita baterie (kWh)", "")),
            "Dojezd WLTP (km)": row.get("Dojezd komb. letní WLTP (km)", None),
            "Dojezd EV-database (km)": row.get("Dojezd komb. letní EV-database (km)", None),
            "Cd": parse_czech_decimal(row.get("Cd", "")),
            "Cd zdroj": row.get("Cd zdroj", ""),
            "Tepelné čerpadlo možné": row.get("Tepelné čerpadlo možné (ano/ne)", ""),
        }
        records.append(rec)

    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (v != v):
                rec[k] = None
            if pd.notna(v) is False:
                rec[k] = None

    out_path = os.path.join(BASE_DIR, "site", "data", "reference.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Reference: {len(records)} entries → {out_path}")
    return records

def update_scrape_history(metadata):
    """Append entry to scrape_history.json (rolling 365 entries)."""
    history_path = os.path.join(BASE_DIR, "site", "data", "scrape_history.json")
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []

    entry = {
        "date": metadata["buildDate"],
        "trigger": metadata["trigger"],
        "sources": metadata["sources"],
        "matching": metadata["matching"],
        "total": metadata["totalCars"],
    }
    history.append(entry)
    history = history[-365:]

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    print(f"  History: {len(history)} entries → {history_path}")

def main():
    print("Loading scraper CSVs...")
    df = load_scraper_csvs()
    print(f"  Combined: {len(df)} rows, {len(df.columns)} columns")

    print("Re-matching combustion against authoritative list...")
    combustion_mask = df["Typ"] == "Spalovací"
    electric_mask = df["Typ"] == "Elektrické"
    combustion_part = df[combustion_mask].copy()
    electric_part = df[electric_mask].copy()
    combustion_part = rematch_combustion(combustion_part)
    if not electric_part.empty and "Model auta" in electric_part.columns:
        electric_part["Model auta"] = electric_part["Model auta"].map(fix_electric_model)
    df = pd.concat([electric_part, combustion_part], ignore_index=True)

    print("Loading reference data...")
    comb_ref = load_combustion_reference()
    elec_ref = load_electric_reference()

    print("Joining combustion reference...")
    df = join_combustion_reference(df, comb_ref)

    print("Joining electric reference...")
    df = join_electric_reference(df, elec_ref)

    print("Backfilling body/fuel for overview...")
    df = backfill_body_fuel(df)
    df = backfill_country(df)

    # PHEV combined consumption is the misleading official WLTP weighted figure
    # (~1 l/100 km, assumes a charged battery). Blank it on every PHEV-tagged row
    # — this also covers listings mismatched to a non-PHEV reference (whose
    # Spotřeba the reference-side blank in load_combustion_reference wouldn't catch).
    if "Hybrid typ" in df.columns and "Spotřeba (l/100 km)" in df.columns:
        df.loc[df["Hybrid typ"].astype(str).str.upper() == "PHEV", "Spotřeba (l/100 km)"] = None

    numeric_cols = [
        "Cena (Kč)", "Nájezd (km)", "Výkon (kW)", "Rok výroby",
        "Objem kufru (l)", "Hlučnost (dB)", "Spotřeba (l/100 km)",
        "Kapacita baterie (kWh)", "Dojezd WLTP (km)", "Dojezd EV-database (km)",
        "Skóre shody", "Cd",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.where(df.notna(), None)

    ordered_cols = [
        "Typ", "Model auta", "Cena (Kč)", "Nájezd (km)", "Rok výroby", "Výkon (kW)",
        "Palivo", "Objem motoru", "Typ motoru", "Hybrid typ",
        "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
        "Kola", "Náhon 4x4", "Karoserie", "Výbava", "Záruka", "Spárováno",
        "Skóre shody", "Tepelné čerpadlo",
        "Extra", "Stav", "Země", "Zdroj", "Odkaz na auto",
        "Spotřeba (l/100 km)", "Objem kufru (l)", "Hlučnost (dB)",
        "Kapacita baterie (kWh)", "Dojezd WLTP (km)", "Dojezd EV-database (km)",
        "Cd", "Cd zdroj", "Tepelné čerpadlo možné",
    ]
    final_cols = [c for c in ordered_cols if c in df.columns]
    for c in df.columns:
        if c not in final_cols:
            final_cols.append(c)
    df = df[final_cols]

    out_path = os.path.join(BASE_DIR, "site", "data", "cars.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    records = df.to_dict(orient="records")
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (v != v):
                rec[k] = None

    trigger = os.environ.get("BUILD_TRIGGER", "manual")
    build_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata = {
        "buildDate": build_date,
        "trigger": trigger,
        "sources": count_sources(df),
        "matching": count_matching(df),
        "referenceData": {
            "combustion": {"file": "ice_specs.csv", "count": len(comb_ref)},
            "electric": {"file": "ev_specs.csv", "count": len(elec_ref)},
        },
        "totalCars": len(records),
    }

    output = {"metadata": metadata, "data": records}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nDone: {len(records)} cars → {out_path}")
    print(f"Final columns ({len(final_cols)}): {final_cols}")

    print("Building reference JSON...")
    build_reference_json(comb_ref, elec_ref, df)

    print("Updating scrape history...")
    update_scrape_history(metadata)

if __name__ == "__main__":
    main()
