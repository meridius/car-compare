import pandas as pd
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Combustion authoritative matching is re-run at build time so that ALL cars —
# including listings already removed from source providers (frozen rows that the
# scraper never re-processes) — get backed by the current reference list.
sys.path.insert(0, BASE_DIR)
from scrapers.core import matching as comb_utils  # noqa: E402
from scrapers.core.filters import SOURCE_FILTERS  # noqa: E402
from scrapers.core.normalize import normalize_model as _normalize_model  # noqa: E402
from scrapers.core.fields import parse_battery_kwh, parse_ev_edition  # noqa: E402


def _fold_accents(s):
    """Strip diacritics (NFKD decompose + drop combining marks).

    mobile.de scrapes model names with diacritics stripped ("Skoda", "Citroen",
    "e-C3") while every other source preserves them ("Škoda", "Citroën", "ë-C3").
    The EV reference join is a prefix match on raw text, so without folding, one
    spelling pairs with the reference row and the other stays permanently
    unmatched. Comparison-only — never used to rewrite a displayed "Model auta".
    Mirrors build/reference_gap.py::_fold_accents.
    """
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


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
    """Strip noise, heal frozen sauto 'Ostatní' garbage names (mirrors the
    electric sauto scraper's _recover_ostatni_model, for rows scraped before the
    fix landed), and re-apply normalize_model()'s alias collapsing (e.g. ORA
    Funky Cat -> GWM Ora 03). normalize_model() runs at scrape time in every
    adapter, so freshly scraped rows already carry the canonical spelling —
    but rows already sitting in state/seed CSVs from before an alias existed
    still have the old name, so it must be re-applied here at build time too.
    Kia EV2 = project code 'QV1' or its unique 42.2 kWh battery."""
    m = strip_listing_noise(model)
    if isinstance(m, str) and m.startswith("Kia ") and (
        "QV1" in m.upper() or re.search(r'42[.,]2', m)
    ):
        return "Kia EV2"
    if isinstance(m, str):
        m = _normalize_model(m)
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


def canonicalize_body(df):
    """Make Karoserie consistent within each exact-'Model auta' group.

    sauto's per-listing vehicle_body_cb is seller-tagged and noisy — the same
    model gets scattered across bodies (e.g. Škoda Enyaq iV 80: 17 'SUV', one
    'Hatchback', one 'Terénní'), which breaks the body-type filter (a family
    bug report). When one body value is a strict majority of the group's
    non-empty values, override the minority outliers *and* fill blanks with it.
    Groups with no strict majority (genuine variants, or a tie) are untouched,
    and distinct model strings ('Octavia' vs 'Octavia Combi') never mix because
    grouping is on the exact name."""
    if df.empty or "Model auta" not in df.columns or "Karoserie" not in df.columns:
        return df

    def norm(v):
        if v is None or (isinstance(v, float) and v != v):
            return ""
        return str(v)

    body = df["Karoserie"].map(norm)
    for model, idx in df.groupby("Model auta").groups.items():
        vals = [body[i] for i in idx if body[i]]
        if not vals:
            continue
        counts = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        winner = max(counts, key=lambda k: counts[k])
        if counts[winner] * 2 > len(vals):  # strict majority
            df.loc[idx, "Karoserie"] = winner
    return df


# Display body vocabulary: collapse the synonym sprawl the sources emit (CUV /
# Terénní / VAN / Combi / Sedan-limuzína …) onto the clean set the dashboard
# filters on, so one real body = one filter bucket (the root of the family
# "filtering is broken" report).
#
# The liftback family (Liftback / Sportback / Fastback) folds INTO Hatchback —
# not a stylistic choice but a data-forced one: the hand-curated ice_specs.csv
# is itself INCONSISTENT for this body class (Škoda Octavia non-Combi appears as
# both "Hatchback" and "Liftback" across entries; Superb→Hatchback, Arteon→
# Hatchback, A5→Sportback, C5 X→Liftback — all the same 5-door-liftback shape).
# Reference-pairing therefore hands different Octavia listings different bodies;
# the only way to guarantee "same car → one body" without a full manual reference
# re-audit is to fold the whole family to Hatchback. This also aligns the display
# taxonomy with matching._canonicalize_body (which already folds Liftback→
# Hatchback for scoring). Czech buyers filter these as hatchbacks anyway.
_DISPLAY_BODY_CANON = {
    "suv": "SUV", "cuv": "SUV", "terénní": "SUV", "terenni": "SUV",
    "offroad": "SUV", "off-road": "SUV", "crossover": "SUV",
    "kombi": "Kombi", "combi": "Kombi", "variant": "Kombi", "sw": "Kombi",
    "avant": "Kombi", "touring": "Kombi", "sports tourer": "Kombi",
    "sportstourer": "Kombi", "shooting brake": "Kombi",
    "hatchback": "Hatchback",
    "liftback": "Hatchback", "sportback": "Hatchback", "fastback": "Hatchback",
    "sedan": "Sedan", "sedan/limuzína": "Sedan", "limuzína": "Sedan",
    "limuzina": "Sedan",
    "mpv": "MPV", "van": "MPV",
    "kupé": "Kupé", "kupe": "Kupé", "coupé": "Kupé", "coupe": "Kupé",
    "kabriolet": "Kupé", "kabrio": "Kupé", "grand sport": "Kupé",
    "pick-up": "Pick-up", "pickup": "Pick-up",
}


def canonicalize_body_vocab(df):
    """Fold every Karoserie cell onto the canonical display vocabulary
    (_DISPLAY_BODY_CANON) so synonyms stop splitting one body across several
    grid-filter buckets. Runs on the whole column — reference-driven,
    listing-derived, and majority-voted values alike — so the source of a value
    never leaks a stray label. Unknown values pass through unchanged."""
    if "Karoserie" not in df.columns:
        return df

    def fold(v):
        if v is None or (isinstance(v, float) and v != v):
            return v
        s = str(v).strip()
        return _DISPLAY_BODY_CANON.get(s.lower(), s)

    df["Karoserie"] = df["Karoserie"].map(fold)
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


def apply_verze_display(df):
    """Payload-time 'Verze' semantics (Verze column plumbing task): the display
    value is sourced from the matched reference row's trim, never from the
    scrape-extracted value carried in state. Only ICE rows confidently matched
    (Spárováno == "Ano") get a value — at that confidence "Model auta" has
    already been rewritten to the auth entry string, so it's also the lookup
    key into the auth list's trim column. Nejisté/Ne ICE rows and every EV row
    (the EV reference has no trim concept) are blanked — we'd otherwise be
    showing a guess dressed up as a fact.

    This only overwrites the in-memory/payload column; the canonical state
    parquet keeps whatever extract_trim() found (still needed for matching's
    trim-disambiguation scoring)."""
    df["Verze"] = ""
    if df.empty or "Model auta" not in df.columns:
        return df
    ice_path = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")
    auth_by_entry = {r["entry"]: r["trim"] for r in comb_utils.load_authoritative_list(ice_path)}
    typ = df.get("Typ", pd.Series("", index=df.index))
    sparovano = df.get("Spárováno", pd.Series("", index=df.index)).astype(str)
    matched_ice = (typ == "Spalovací") & (sparovano == "Ano")
    df.loc[matched_ice, "Verze"] = (
        df.loc[matched_ice, "Model auta"].map(auth_by_entry).fillna("")
    )
    return df


def extract_ev_extra_specs(df):
    """Parse the EV listing's free-text Extra into dedicated columns
    (2026-07-09 Extra-extraction task). EV-only; ICE rows untouched.

    - 'Kapacita baterie (kWh)': the per-listing battery from Extra
      ('Baterie 43 kWh') WINS over the reference-join nominal (which is one value
      per nameplate and wrong for multi-battery variants). Reference is the
      fallback when Extra carries no plausible value.
    - 'Verze': the edition token from Extra (allow-list) — display-only, does not
      drive matching. Blank when no known edition is present.

    MUST run after apply_verze_display() (which blanks Verze then fills ICE) and
    after join_electric_reference() (which sets the nominal battery)."""
    if df.empty or "Typ" not in df.columns:
        return df
    is_ev = df["Typ"] == "Elektrické"
    if not is_ev.any():
        return df
    # fillna before astype: on an arrow-backed column .astype(str) preserves
    # nulls, so .map would feed float NaN to the parse helpers (they guard
    # against non-str too, but coercing here keeps the mapped values clean).
    extra = df.loc[is_ev, "Extra"].fillna("").astype(str)

    bat = extra.map(parse_battery_kwh)
    has_bat = bat != ""
    if "Kapacita baterie (kWh)" not in df.columns:
        df["Kapacita baterie (kWh)"] = ""
    idx = extra.index[has_bat.values]
    df.loc[idx, "Kapacita baterie (kWh)"] = bat[has_bat].astype(float).values

    df.loc[is_ev, "Verze"] = extra.map(parse_ev_edition).values
    return df


def apply_reference_body_specs(df):
    """Reference-drive body type (and, for confident matches, engine specs) from
    the matched ICE reference row, so every listing sharing an auth entry shows
    the identical curated value — the invariant the "same model, different
    Karoserie" bug (family report) needs. Modeled on apply_verze_display.

    Body: written for any Spalovací row whose "Model auta" is an entry that ALSO
    appears as a confident (Ano) match — the entry is corroborated, so its body
    is trustworthy even for a Nejisté sibling (matching writes the same entry
    string for both Ano and Nejisté). Uses the UNFOLDED reference body
    (`body_raw`) so Liftback/Sportback survive; the whole-column display fold
    (canonicalize_body_vocab) runs after. Only overwrites when the reference
    body is non-blank (6 ICE ref rows have none) so a correct listing body is
    never blanked. Uncorroborated Nejisté-only groups and Ne rows fall through
    to canonicalize_body's majority vote / derive_body.

    Engine (Objem motoru / Typ motoru / Hybrid typ): overwritten on Ano only —
    these disambiguate variants, so are never trusted on an uncertain match.
    Per-listing extraction is documented-noisy (a car matched to "Formentor 1.5
    TSI" can carry Objem motoru 2.0); the structured reference column is the
    single source of truth (build_reference_json already uses it on the
    reference page — this makes the grid consistent with it). EV is untouched
    here (handled in join_electric_reference)."""
    if df.empty or "Model auta" not in df.columns:
        return df
    ice_path = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")
    auth = {r["entry"]: r for r in comb_utils.load_authoritative_list(ice_path)}
    typ = df.get("Typ", pd.Series("", index=df.index))
    sparovano = df.get("Spárováno", pd.Series("", index=df.index)).astype(str)
    model = df["Model auta"]

    is_ice = (typ == "Spalovací")
    ano_entries = set(model[is_ice & (sparovano == "Ano")])

    # Body: any ICE row keyed on a corroborated (Ano-seen) entry, non-blank ref body.
    body_map = {e: auth[e]["body_raw"] for e in ano_entries
                if e in auth and auth[e]["body_raw"]}
    if body_map:
        m = is_ice & model.isin(body_map)
        df.loc[m, "Karoserie"] = model[m].map(body_map)

    # Engine specs: Ano rows only (their Model auta is exactly an ano_entry).
    ano_mask = is_ice & (sparovano == "Ano")
    for col, key in (("Objem motoru", "engine_vol"),
                     ("Typ motoru", "engine_type"),
                     ("Hybrid typ", "hybrid")):
        if col not in df.columns:
            continue
        spec_map = {e: auth[e][key] for e in ano_entries
                    if e in auth and auth[e][key]}
        if spec_map:
            m = ano_mask & model.isin(spec_map)
            df.loc[m, col] = model[m].map(spec_map)
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

def load_scraper_data(scrapes_dir=None):
    """Concat per-source state (parquet, seed-CSV fallback — see core/storage.py).

    State files are stringly with "" blanks; mask those back to NaN so the
    frame is indistinguishable from the old pd.read_csv() one downstream.
    """
    from pathlib import Path

    from scrapers.core import storage

    dfs = []
    scrapes = Path(scrapes_dir or os.path.join(BASE_DIR, "scrapers", "data", "scrapes"))
    for name in ["sauto", "autodraft", "energycars", "mobilede"]:
        df = storage.read_state(scrapes / name)
        if df is not None:
            dfs.append(df)
            print(f"  {name}: {len(df)} rows")
    if not dfs:
        return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)
    return combined.mask(combined == "")

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

def _sorted_ref_pairs(ref_models, fold):
    """(comparison-key, original) pairs, longest comparison-key first.

    `fold` is identity for an exact comparison or _fold_accents for a folded one."""
    return sorted(
        ((fold(rm).lower(), rm) for rm in ref_models),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )


def _match_electric_ref(model, ref_models_exact, ref_models_folded):
    """Longest-prefix match a scraped EV model against reference 'Model auta' names.

    Tries an exact (case-insensitive) prefix match first, and only falls back to an
    accent-folded comparison when nothing matches exactly. This is deliberate, not
    just an optimisation: the reference list can carry two distinct rows that differ
    only by diacritics (e.g. "Renault Megane" vs "Renault Mégane" are different
    trims with different specs), so folding both sides unconditionally would
    silently redirect an already-correct exact match to the wrong row. Falling back
    only when no exact candidate exists is what pairs mobile.de's diacritic-stripped
    names ("Citroen e-C3") with sources that keep them ("Citroën ë-C3") without
    disturbing any listing that already matches exactly.
    """
    low = model.lower()
    for rm_key, rm in ref_models_exact:
        if low.startswith(rm_key):
            return rm
    folded = _fold_accents(model).lower()
    for rm_key, rm in ref_models_folded:
        if folded.startswith(rm_key):
            return rm
    return None


def join_electric_reference(df, ref):
    """Prefix match: find longest ref 'Model auta' that is prefix of scraped model
    (accent-folded fallback — see _match_electric_ref)."""
    electric_mask = df["Typ"] == "Elektrické"
    electric = df[electric_mask].copy()
    other = df[~electric_mask].copy()

    ref_models = ref["Model auta"].tolist()
    ref_models_exact = _sorted_ref_pairs(ref_models, lambda s: s)
    ref_models_folded = _sorted_ref_pairs(ref_models, _fold_accents)

    add_cols_map = {
        "Karoserie": "Karoserie",
        "Objem kufru (l)": "Objem kufru (l)",
        "Hlučnost (dB)": "Hlučnost (dB)",
        "Kapacita baterie (kWh)": "Kapacita baterie (kWh)",
        "Dojezd komb. letní WLTP (km)": "Dojezd WLTP (km)",
        "Dojezd komb. letní EV-database (km)": "Dojezd EV-database (km)",
        "Cd": "Cd",
        "Cd zdroj": "Cd zdroj",
        "Tepelné čerpadlo možné (ano/ne)": "Tepelné čerpadlo možné",
    }
    # Karoserie is OVERWRITTEN from the reference (the curated body wins over the
    # noisy per-listing value — every listing of one EV nameplate then shows the
    # same body); the other spec cols use fillna-only (don't clobber scraped
    # values). Requires the Karoserie column in ev_specs.csv; absent it, the
    # src_col guard below makes this a no-op.
    OVERWRITE_COLS = {"Karoserie"}

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
        model = str(row.get("Model auta", ""))
        ref_model = _match_electric_ref(model, ref_models_exact, ref_models_folded)
        if ref_model is not None:
            ref_row = ref_lookup[ref_model]
            for src_col, dst_col in add_cols_map.items():
                if src_col in ref_row.index:
                    val = ref_row[src_col]
                    if pd.notna(val) and val != "":
                        if dst_col in OVERWRITE_COLS:
                            electric.at[idx, dst_col] = val  # reference body wins
                        elif pd.isna(electric.at[idx, dst_col]) if dst_col in electric.columns else True:
                            electric.at[idx, dst_col] = val
            electric.at[idx, "Spárováno"] = "Ano"
            matched += 1

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
    listings whose scraped model starts with that reference name (longest prefix,
    accent-folded fallback — same bucketing as join_electric_reference)."""
    ev = df[df["Typ"] == "Elektrické"]
    ref_models = elec_ref["Model auta"].tolist()
    ref_models_exact = _sorted_ref_pairs(ref_models, lambda s: s)
    ref_models_folded = _sorted_ref_pairs(ref_models, _fold_accents)
    buckets = {}
    for _, row in ev.iterrows():
        model = str(row.get("Model auta", ""))
        rm = _match_electric_ref(model, ref_models_exact, ref_models_folded)
        if rm is not None:
            b = buckets.setdefault(rm, {"Karoserie": [], "Výkon (kW)": []})
            b["Karoserie"].append(row.get("Karoserie"))
            b["Výkon (kW)"].append(row.get("Výkon (kW)"))
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
            "Verze": auth.get("trim", "") or "",
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
            "Přidáno": row.get("Přidáno", ""),
            "Upraveno": row.get("Upraveno", ""),
        }
        records.append(rec)

    for _, row in elec_ref.iterrows():
        model = row.get("Model auta", "")
        listing = ev_specs.get(model, {})
        rec = {
            "Model auta": model,
            "Verze": "",  # EV reference carries no trim concept
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
            "Přidáno": row.get("Přidáno", ""),
            "Upraveno": row.get("Upraveno", ""),
        }
        records.append(rec)

    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (v != v):
                rec[k] = None
            if pd.notna(v) is False:
                rec[k] = None

    # Sort records by "Model auta" for deterministic output
    records.sort(key=lambda r: r.get("Model auta", ""))

    out_path = os.path.join(BASE_DIR, "site", "data", "reference.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  Reference: {len(records)} entries → {out_path}")
    return records

def split_brand_model(model_auta):
    """Split a canonical 'Model auta' string into (Značka, Model) for the
    payload display columns (task #3: payload/display split — the canonical
    scrape/state schema and all matching/merge/join logic keep keying on the
    single 'Model auta' column untouched).

    Reuses the scraped-side brand parser (core.matching._parse_brand /
    MULTI_WORD_BRANDS) instead of inventing a new splitter, so multi-word
    brands (Alfa Romeo, Land Rover, Mercedes-Benz, GWM Haval) split correctly;
    an unrecognised brand falls back to the first token, same as matching.
    """
    if not isinstance(model_auta, str) or not model_auta.strip():
        return "", ""
    return comb_utils._parse_brand(model_auta.strip())


def strip_ice_engine_tokens(model):
    """Strip Objem motoru / Typ motoru tokens from a display 'Model' string
    (task #4). ICE auth strings and `_format_unmatched()` output both append
    displacement + engine tech to the tail (e.g. "Karoq 1.5 TSI",
    "Mokka 1.2 Turbo") — those columns exist separately in the payload, so the
    'Model' column showing them too is a duplicate/leak.

    Reuses the existing core.fields extraction/strip helpers rather than a
    parallel keyword list: `extract_engine_type` / `extract_engine_volume_from_model`
    detect what's present, `strip_engine_from_model` removes it (also handles
    prefixed variants like "eTSI").

    Never returns an empty string — if stripping would blank the model
    entirely (e.g. a bare "1.5 TSI" with no name left), the original is kept.
    Call only for ICE rows: EV model names never carry engine vol/type by
    construction (e.g. Enyaq's "iV 80" is a battery-tier variant number, not
    displacement, and must not be touched).
    """
    if not model:
        return model
    from scrapers.core import fields as _fields
    engine_type = _fields.extract_engine_type(model)
    engine_vol = _fields.extract_engine_volume_from_model(model)
    if not engine_type and not engine_vol:
        return model
    stripped = _fields.strip_engine_from_model(model, engine_vol, engine_type)
    return stripped if stripped.strip() else model


def derive_transmission_type(typ, prevodovka, dvouspojkova):
    """Task #26: pure classifier for the derived 'Typ převodovky' display
    column — a finer breakdown than the existing 'Převodovka'
    (Automat/Manual) + 'Dvouspojková převodovka' (Ano/blank) pair, built
    entirely from data already in the canonical schema (no new scrape-time
    field). Mirrors the classification `site/transmissions.js` already does
    client-side for its live per-type counts (`computeCounts()`), so the two
    stay conceptually in sync.

    - EV (`Typ == "Elektrické"`) → always "Redukční (EV)": every EV in this
      dataset uses a fixed single-speed reduction gear, regardless of
      whatever 'Převodovka'/'Dvouspojková převodovka' happen to carry.
    - ICE 'Převodovka' is a manual value → "Manuální".
    - ICE 'Převodovka' is an automatic value and 'Dvouspojková převodovka'
      == "Ano" → "Dvouspojková (DSG/DCT)".
    - ICE 'Převodovka' is an automatic value otherwise → "Automatická"
      (hydraulic torque-converter vs. CVT aren't distinguishable in the
      source data — do not guess).
    - Anything else (blank/unrecognised 'Převodovka') → "" (blank).

    'Převodovka' itself is not spelled consistently across sources — sauto's
    API and mobile.de's German→Czech map both write out "Automatická" /
    "Manuální" natively, while autodraft's own extractor writes the shorter
    "Automat" / "Manual" — so both spellings must be accepted here. Mirrors
    `AUTOMAT_VALUES` / `MANUAL_VALUES` in `site/transmissions.js`, which faced
    the exact same inconsistency for its client-side live counts.
    """
    from scrapers.core.schema import TYP_EV
    if typ == TYP_EV:
        return "Redukční (EV)"
    if prevodovka in ("Manual", "Manuální"):
        return "Manuální"
    if prevodovka in ("Automat", "Automatická"):
        return "Dvouspojková (DSG/DCT)" if dvouspojkova == "Ano" else "Automatická"
    return ""


def add_transmission_type_column(df):
    """Payload-only transform (task #26): derive 'Typ převodovky' from
    'Typ' + 'Převodovka' + 'Dvouspojková převodovka' and insert it right
    after 'Dvouspojková převodovka'. No-op if those source columns are
    absent (e.g. a minimal test frame) — never invents the column from
    nothing.
    """
    required = {"Typ", "Převodovka", "Dvouspojková převodovka"}
    if not required.issubset(df.columns):
        return df
    df = df.copy()
    pos = list(df.columns).index("Dvouspojková převodovka") + 1
    values = [
        derive_transmission_type(typ, prevodovka, dvouspojkova)
        for typ, prevodovka, dvouspojkova in zip(
            df["Typ"], df["Převodovka"], df["Dvouspojková převodovka"])
    ]
    df.insert(pos, "Typ převodovky", values)
    return df


def add_brand_model_columns(df):
    """Payload-only transform (task #3): derive 'Značka' + 'Model' from
    'Model auta' and drop 'Model auta' from the frame. Called once, right
    before the payload is written — every upstream step (matching, merge,
    reference joins) still reads/writes the single 'Model auta' column.

    Task #4: on ICE rows (Typ == "Spalovací"), also strips engine
    volume/type tokens from the derived 'Model' (see strip_ice_engine_tokens)
    so the display column never duplicates the dedicated 'Objem motoru' /
    'Typ motoru' columns. EV rows are left untouched — a 'Typ' column is
    required to gate this safely; if it's absent, no stripping happens.
    """
    df = df.copy()
    if "Model auta" not in df.columns:
        return df
    pos = list(df.columns).index("Model auta")
    split = df["Model auta"].map(split_brand_model)
    znacka = split.map(lambda t: t[0])
    model = split.map(lambda t: t[1])
    if "Typ" in df.columns:
        from scrapers.core.schema import TYP_ICE
        is_ice = df["Typ"] == TYP_ICE
        model = pd.Series(
            [strip_ice_engine_tokens(m) if ice else m for m, ice in zip(model, is_ice)],
            index=df.index,
        )
    df = df.drop(columns=["Model auta"])
    df.insert(pos, "Model", model)
    df.insert(pos, "Značka", znacka)
    return df


# --- Reliability score (task #30, payload-derived display column) --------
# Owner's rule of thumb: "more cylinders and bigger displacement = more
# reliable". This is a coarse heuristic, NOT empirical reliability data —
# there is no dataset backing it, just a monotonic mapping from engine size
# to a 1-5 score. Cylinder count (#24) is populated for only a slice of sauto
# ICE rows today (sauto's detail API has no confirmed cylinder field, and no
# other source carries one at all), so the score must degrade gracefully to a
# volume-only estimate whenever cylinders are blank — which is most rows.
_RELIABILITY_VOLUME_BINS = [
    (1.0, 1),
    (1.3, 2),
    (1.6, 3),
    (2.0, 4),
]  # (inclusive upper bound in litres, score); above the last bound -> 5

_RELIABILITY_CYLINDER_MAP = {4: 3, 5: 4}  # 3 (or fewer) -> 1; 6+ -> 5 (see _cylinder_component)


def _volume_component(volume_l):
    for upper, score in _RELIABILITY_VOLUME_BINS:
        if volume_l <= upper:
            return score
    return 5


def _cylinder_component(cylinders):
    if cylinders <= 3:
        return 1
    if cylinders in _RELIABILITY_CYLINDER_MAP:
        return _RELIABILITY_CYLINDER_MAP[cylinders]
    return 5  # >= 6 cylinders


def reliability_score(engine_volume, cylinder_count):
    """Derived "Spolehlivost" score (1-5, as a string) from displacement, blended
    with cylinder count when known. Pure helper — the ICE-only gating (EV rows
    never get a score) lives in the caller, `add_reliability_column`, which has
    access to 'Typ'.

    Returns "" when engine_volume is missing/blank/NaN — the rule needs an
    engine to reason about. When cylinder_count is also missing/blank, the
    score is volume-only; when present, it's round(mean(volume component,
    cylinder component)), clamped to [1, 5].
    """
    try:
        vol = float(engine_volume)
    except (TypeError, ValueError):
        return ""
    if vol != vol:  # NaN
        return ""
    vol_score = _volume_component(vol)

    cyl = None
    if cylinder_count not in (None, ""):
        try:
            cyl_f = float(cylinder_count)
            if cyl_f == cyl_f:  # not NaN
                cyl = cyl_f
        except (TypeError, ValueError):
            cyl = None

    score = vol_score if cyl is None else round((vol_score + _cylinder_component(cyl)) / 2)
    return str(int(max(1, min(5, score))))


def add_reliability_column(df):
    """Insert the payload-only 'Spolehlivost' column (task #30) right after
    'Počet válců', derived from 'Objem motoru' (+ 'Počet válců' when present).
    ICE only — EV rows have no combustion engine, so the rule doesn't apply
    and the column stays blank. Not part of CANONICAL_COLS: this is a display
    column computed at build time, same treatment as 'Značka'/'Model'."""
    df = df.copy()
    if "Typ" not in df.columns or "Objem motoru" not in df.columns:
        return df
    from scrapers.core.schema import TYP_ICE
    cyl_col = df["Počet válců"] if "Počet válců" in df.columns else pd.Series("", index=df.index)
    scores = [
        reliability_score(vol, cyl) if typ == TYP_ICE else ""
        for typ, vol, cyl in zip(df["Typ"], df["Objem motoru"], cyl_col)
    ]
    pos_col = "Počet válců" if "Počet válců" in df.columns else "Objem motoru"
    pos = list(df.columns).index(pos_col) + 1
    df.insert(pos, "Spolehlivost", scores)
    return df


PAYLOAD_NUMERIC_COLS = [
    "Cena (Kč)", "Nájezd (km)", "Výkon (kW)", "Rok výroby", "Objem motoru",
    "Počet válců", "Spolehlivost",
    "Objem kufru (l)", "Hlučnost (dB)", "Spotřeba (l/100 km)",
    "Kapacita baterie (kWh)", "Dojezd WLTP (km)", "Dojezd EV-database (km)",
    "Skóre shody", "Cd",
]


def _coerce_payload(df):
    """Type a frame for the browser: numeric cols → float64, blanks → null.

    Snappy (in write_payload) + float64: hyparquet decodes snappy natively (no
    extra browser dep) and int64 would decode to BigInt and break grid
    formatters (pinned by test_no_int64_columns).
    """
    df = df.copy()
    for col in PAYLOAD_NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in df.columns:
        if col not in PAYLOAD_NUMERIC_COLS:
            df[col] = df[col].astype(object).mask(df[col].isna() | (df[col] == ""), None)
    return df


def write_payload(df, metadata, out_dir):
    """Write the split payload (decision 001, option C): cars.parquet = live
    listings, cars-archived.parquet = removed ones (Stav="Odstraněno"), plus the
    cars-meta.json sidecar. The archive is lazy-loaded on demand in the dashboard,
    so the always-loaded payload stays bounded by the live market.

    Task #3: also splits 'Model auta' into the payload-only 'Značka' + 'Model'
    display columns and drops 'Model auta' — the canonical schema keeps the
    single column; only the browser-facing payload is split.

    Task #30: also derives the payload-only 'Spolehlivost' column (see
    add_reliability_column) — likewise not part of the canonical schema.

    Task #26: also derives the payload-only 'Typ převodovky' column from
    'Typ' + 'Převodovka' + 'Dvouspojková převodovka' (see
    add_transmission_type_column) — no new canonical column.
    """
    os.makedirs(out_dir, exist_ok=True)
    df = add_brand_model_columns(df)
    df = add_reliability_column(df)
    df = add_transmission_type_column(df)
    removed = df["Stav"].astype(str) == "Odstraněno" if "Stav" in df.columns else pd.Series(False, index=df.index)

    live_path = os.path.join(out_dir, "cars.parquet")
    _coerce_payload(df[~removed]).to_parquet(live_path, compression="snappy", index=False)

    archived_path = os.path.join(out_dir, "cars-archived.parquet")
    # Always write it (empty frame keeps its schema) so the browser fetch never 404s.
    _coerce_payload(df[removed]).to_parquet(archived_path, compression="snappy", index=False)

    meta_path = os.path.join(out_dir, "cars-meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, sort_keys=True)
    return live_path, archived_path, meta_path


def update_scrape_history(metadata, history_path=None, seed_path=None):
    """Append entry to scrape_history.json (rolling 365 entries).

    The file is no longer git-tracked; when absent (fresh checkout, no release
    downloaded) it is seeded from the frozen copy in scrapers/data/seed/.
    """
    history_path = history_path or os.path.join(BASE_DIR, "site", "data", "scrape_history.json")
    seed_path = seed_path or os.path.join(BASE_DIR, "scrapers", "data", "seed", "scrape_history.json")
    history = []
    for candidate in (history_path, seed_path):
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    history = json.load(f)
                break
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
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"  History: {len(history)} entries → {history_path}")

def main():
    print("Loading scraper state...")
    df = load_scraper_data()
    print(f"  Combined: {len(df)} rows, {len(df.columns)} columns")

    print("Normalizing Ano/Ne boolean columns...")
    from scrapers.core.fields import normalize_ano_ne
    from scrapers.core.schema import ANO_NE_COLS
    for col in ANO_NE_COLS:
        if col in df.columns:
            df[col] = df[col].apply(normalize_ano_ne)

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

    print("Deriving display 'Verze' (confidently-matched reference trim only)...")
    df = apply_verze_display(df)

    print("Extracting EV battery + edition from Extra...")
    df = extract_ev_extra_specs(df)

    print("Reference-driving body/engine specs for confident matches...")
    df = apply_reference_body_specs(df)

    print("Folding body type onto the canonical display vocabulary...")
    df = canonicalize_body_vocab(df)

    print("Canonicalizing body type within each model (majority-vote fallback)...")
    df = canonicalize_body(df)

    print("Backfilling body/fuel for overview...")
    df = backfill_body_fuel(df)
    df = backfill_country(df)

    # PHEV combined consumption is the misleading official WLTP weighted figure
    # (~1 l/100 km, assumes a charged battery). Blank it on every PHEV-tagged row
    # — this also covers listings mismatched to a non-PHEV reference (whose
    # Spotřeba the reference-side blank in load_combustion_reference wouldn't catch).
    if "Hybrid typ" in df.columns and "Spotřeba (l/100 km)" in df.columns:
        df.loc[df["Hybrid typ"].astype(str).str.upper() == "PHEV", "Spotřeba (l/100 km)"] = None

    ordered_cols = [
        "Typ", "Model auta", "Verze", "Cena (Kč)", "Nájezd (km)", "Rok výroby", "Výkon (kW)",
        "Palivo", "Objem motoru", "Typ motoru", "Počet válců", "Hybrid typ",
        "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
        "Kola", "Náhon 4x4", "Karoserie", "Záruka", "Spárováno",
        "Skóre shody", "Tepelné čerpadlo",
        "Extra", "Stav", "Odstraněno dne", "Země", "Zdroj", "Odkaz na auto",
        "Spotřeba (l/100 km)", "Objem kufru (l)", "Hlučnost (dB)",
        "Kapacita baterie (kWh)", "Dojezd WLTP (km)", "Dojezd EV-database (km)",
        "Cd", "Cd zdroj", "Tepelné čerpadlo možné",
    ]
    final_cols = [c for c in ordered_cols if c in df.columns]
    for c in df.columns:
        if c not in final_cols:
            final_cols.append(c)
    df = df[final_cols]

    trigger = os.environ.get("BUILD_TRIGGER", "manual")
    build_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    removed_mask = (df["Stav"].astype(str) == "Odstraněno") if "Stav" in df.columns else pd.Series(False, index=df.index)
    df_live = df[~removed_mask]
    archived_count = int(removed_mask.sum())

    # Metadata describes the always-loaded live payload; the archive is separate
    # and lazy-loaded, so its rows are surfaced only by archivedCars.
    metadata = {
        "buildDate": build_date,
        "trigger": trigger,
        "sources": count_sources(df_live),
        "matching": count_matching(df_live),
        "referenceData": {
            "combustion": {"file": "ice_specs.csv", "count": len(comb_ref)},
            "electric": {"file": "ev_specs.csv", "count": len(elec_ref)},
        },
        "totalCars": len(df_live),       # rows in the always-loaded cars.parquet
        "archivedCars": archived_count,  # rows in the lazy-loaded cars-archived.parquet
        # Hard search filters each scraper applies (scrapers/core/filters.py),
        # surfaced in the dashboard "Přehled dat" overview so users see the
        # selection criteria that shaped the dataset.
        "filters": SOURCE_FILTERS,
    }
    live_count = len(df_live)

    out_dir = os.path.join(BASE_DIR, "site", "data")
    live_path, _, _ = write_payload(df, metadata, out_dir)

    print(f"\nDone: {live_count} live + {archived_count} archived cars → {live_path}")
    print(f"Final columns ({len(final_cols)}): {final_cols}")

    print("Building reference JSON...")
    build_reference_json(comb_ref, elec_ref, df)

    print("Updating scrape history...")
    update_scrape_history(metadata)

if __name__ == "__main__":
    main()
