"""Shared utilities for combustion car scrapers."""

import csv
import re
from pathlib import Path

import pandas as pd

BRAND_MAP = {
    "Volkswagen": "VW",
}

MODEL_CLEANUP_PATTERNS = [
    (re.compile(r'X-Perience', re.IGNORECASE), 'Xperience'),
    (re.compile(r'\bcombi\b'), 'Combi'),
    (re.compile(r'\bScout Combi\b'), 'Combi Scout'),
    (re.compile(r'\bRS Combi\b'), 'Combi RS'),
    (re.compile(r'Cee´d', re.IGNORECASE), 'Ceed'),
]


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
    """Merge new scrape with previous CSV, preserving row order from previous CSV."""
    if not csv_path.exists():
        return df

    prev = pd.read_csv(csv_path, encoding="utf-8", dtype=str).fillna("")
    if "Odkaz na auto" not in prev.columns:
        return df

    new_by_link = df.set_index("Odkaz na auto")
    result_rows = []
    for _, row in prev.iterrows():
        link = row["Odkaz na auto"]
        if link in new_by_link.index:
            result_rows.append(new_by_link.loc[link])
        else:
            row = row.copy()
            row["Stav"] = "Odstraněno"
            result_rows.append(row)
    # Add genuinely new listings (not in prev) at the end
    prev_links = set(prev["Odkaz na auto"])
    for _, row in df.iterrows():
        if row["Odkaz na auto"] not in prev_links:
            result_rows.append(row)
    return pd.DataFrame(result_rows).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Field extraction helpers (applied to Extra / suffix / full card text)
# ---------------------------------------------------------------------------

ENGINE_TYPE_KEYWORDS = [
    "EcoBoost", "eTSI", "TSI", "TDI", "TFSI",
    "T-GDI", "T-GDi", "TGDI", "TGDi", "CRDi", "GDI",
    "TCe", "dCi", "CDTi",
    "PureTech", "BlueHDi",
    "SKYACTIV-G", "SKYACTIV-D", "Sky-G",
    "EcoBlue",
    "e-TEC",
    "T-MIVEC", "MIVEC",
    "MTJ",
    "Turbo",
]

HYBRID_KEYWORDS = [
    ("e-Hybrid", "PHEV"),
    ("E-HYBRID", "PHEV"),
    ("iV", "PHEV"),
    ("E-Tech full hybrid", "HEV"),
    ("full hybrid", "HEV"),
    ("e-TEC", "MHEV"),
    ("MHEV", "MHEV"),
    ("mHEV", "MHEV"),
    ("mild hybrid", "MHEV"),
    ("e-CVT", "HEV"),
    ("Hybrid", "HEV"),
]

BODY_KEYWORDS = [
    "Sports Tourer",
    "SW", "Combi", "Variant", "Touring",
    "Fastback", "Allspace", "SUV", "Sportback",
]

TRIM_KEYWORDS = [
    "Laurin & Klement",
    "Monte Carlo",
    "Top Selection",
    "PanAmericana",
    "FR-Line", "R-Line", "RS Line", "R.S.Line", "RS-Line",
    "S-Line", "S Line",
    "GT-Line", "GT Line",
    "N-Line", "N Line",
    "ST-Line", "ST Line",
    "N-Connecta", "N-CONNECTA",
    "Quattro",
    "FR", "Xcellence", "Sportline",
    "Titanium", "Tekna", "Elegance", "Style", "Exclusive",
    "AVANTGARDE", "Alltrack", "Scout",
    "TOP", "SPIN", "Selection",
    "Ambition", "Comfort", "Life", "Highline",
    "Allure", "Active", "Acenta",
    "Premium", "Luxury",
]

DCT_KEYWORDS = [
    "7DCT", "7DSG", "DCT", "DSG", "S-tronic", "S-Tronic", "PDK", "Powershift",
]

_ENGINE_VOL_RE = re.compile(r'(?<!\d)(\d[.,]\d)\s*(?=[TtA-Z]|l\b|$)')
_ENGINE_VOL_START_RE = re.compile(r'^(\d[.,]\d)\b')
_ENGINE_VOL_CLEANUP_RE = re.compile(r'(?<!\d)\d[.,]\d(?!\d)')
_ENGINE_VOL_MODEL_RE = re.compile(r'(?<!\d)(\d[.,]\d)\b')
_AWD_EXTRA_RE = re.compile(r'\b(?:4x4|AWD|4Motion|Quattro|xDrive|4MATIC)\b', re.IGNORECASE)
_PARTICLE_FILTER_RE = re.compile(r'\b[GD]PF\b', re.IGNORECASE)


def extract_engine_volume(text: str) -> str:
    """Extract displacement like '1.5' or '2.0' from text."""
    m = _ENGINE_VOL_RE.search(text)
    if not m:
        m = _ENGINE_VOL_START_RE.search(text)
    return m.group(1).replace(',', '.') if m else ""


def extract_engine_volume_from_model(text: str) -> str:
    """Extract displacement from model name (relaxed — no lookahead requirement)."""
    m = _ENGINE_VOL_MODEL_RE.search(text)
    return m.group(1).replace(',', '.') if m else ""


def extract_engine_type(text: str) -> str:
    """Extract engine technology (TSI, TDI, EcoBoost, etc.)."""
    for kw in ENGINE_TYPE_KEYWORDS:
        if re.search(re.escape(kw), text, re.IGNORECASE):
            return kw
    return ""


def strip_engine_from_model(model: str, engine_vol: str, engine_type: str) -> str:
    """Strip engine volume and type (including prefixed variants like eTSI) from model name."""
    if engine_type:
        model = re.sub(r'\S*' + re.escape(engine_type) + r'\S*', '', model, count=1, flags=re.IGNORECASE)
    if engine_vol:
        model = re.sub(r'(?<!\d)' + re.escape(engine_vol) + r'(?!\d)', '', model, count=1)
    model = re.sub(r'\s{2,}', ' ', model).strip()
    return model


def extract_hybrid_type(text: str) -> str:
    """Classify hybrid: MHEV, HEV, PHEV, or empty."""
    text_lower = text.lower()
    for keyword, classification in HYBRID_KEYWORDS:
        if keyword.lower() in text_lower:
            return classification
    return ""


def extract_body_type(text: str) -> str:
    """Extract body type (SW, Combi, Fastback, etc.)."""
    for kw in BODY_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            return kw
    return ""


def extract_trim(text: str) -> str:
    """Extract trim/equipment level."""
    for kw in TRIM_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            return kw
    return ""


def extract_warranty(text: str) -> str:
    """Detect warranty mention. Returns 'Ano' or ''."""
    return "Ano" if re.search(r'\b[Zz][áa]ruk', text) else ""


def extract_dct(text: str) -> str:
    """Detect dual-clutch transmission. Returns 'Ano' or ''."""
    for kw in DCT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'(?![A-Za-z])', text, re.IGNORECASE):
            return "Ano"
    return ""


def extract_particle_filter(text: str) -> str:
    """Detect particulate filter (GPF/DPF). Returns 'Ano' or ''."""
    return "Ano" if _PARTICLE_FILTER_RE.search(text) else ""


def extract_awd(text: str) -> str:
    """Detect AWD/4x4 from text. Returns 'Ano' or 'Ne'."""
    return "Ano" if _AWD_EXTRA_RE.search(text) else "Ne"


_WARRANTY_RE = re.compile(
    r'\d+\s+(?:rok[yůa]?\s+)?(?:pln[áa]\s+)?z[áa]ruk[ay]?\s+(?:v\s+cen[ěe])?',
    re.IGNORECASE,
)
_TRANSMISSION_EXTRA_RE = re.compile(r'\bMan\.|\bMAN\b')
_SEAT_COUNT_RE = re.compile(r'\b[79]-?\s*[Mm][íi]st\b')

_EXTRA_CLEANUP_RES = [
    _ENGINE_VOL_CLEANUP_RE,
    re.compile(r'\d+\s*kW', re.IGNORECASE),
    _AWD_EXTRA_RE,
    _PARTICLE_FILTER_RE,
]


def clean_extra(text: str, extracted: dict) -> str:
    """Remove substrings already captured in dedicated columns from Extra text."""
    for field in ("Typ motoru", "Výbava", "Karoserie", "Hybrid typ"):
        val = extracted.get(field, "")
        if val:
            text = re.sub(re.escape(val), "", text, count=1, flags=re.IGNORECASE)

    for kw in DCT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'(?![A-Za-z])', text, re.IGNORECASE):
            text = re.sub(r'\b' + re.escape(kw) + r'(?![A-Za-z])', '', text, count=1, flags=re.IGNORECASE)

    for pat in _EXTRA_CLEANUP_RES:
        text = pat.sub("", text)

    for kw in TRIM_KEYWORDS:
        text = re.sub(r'\b' + re.escape(kw) + r'\b', '', text, count=1, flags=re.IGNORECASE)

    text = _WARRANTY_RE.sub("", text)
    text = _TRANSMISSION_EXTRA_RE.sub("", text)
    text = _SEAT_COUNT_RE.sub("", text)

    text = re.sub(r'\s*/\s*', ' / ', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'(^[/\s,]+|[/\s,]+$)', '', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'(?:^|\s)/\s', ' ', text).strip()
    text = re.sub(r'\s/\s*$', '', text).strip()
    return text


# ---------------------------------------------------------------------------
# Authoritative list matching
# ---------------------------------------------------------------------------

MULTI_WORD_BRANDS = [
    "Alfa Romeo", "Land Rover", "Mercedes-Benz", "GWM Haval",
]

_BRAND_MATCH_ALIASES = {
    "ssangyong": "kgm",
    "kgm": "ssangyong",
}

_BODY_GROUPS = {
    "Kombi": {"Kombi", "Combi", "Variant", "SW", "Avant", "Touring",
              "Sports Tourer", "Sportswagon", "Grandtour", "Sportstourer",
              "Wagon", "Grandtour"},
    "Hatchback": {"Hatchback", "Liftback"},
    "Fastback": {"Fastback"},
    "SUV": {"SUV", "Crossover"},
    "Sedan": {"Sedan", "Sedan/limuzína", "Limuzína"},
    "MPV": {"MPV"},
    "Shooting Brake": {"Shooting Brake"},
    "Sportback": {"Sportback", "Coupé-SUV"},
}

_BODY_CANON: dict[str, str] = {}
for _canon, _syns in _BODY_GROUPS.items():
    for _s in _syns:
        _BODY_CANON[_s.lower()] = _canon

_AUTH_BODY_KEYWORDS = [
    "Shooting Brake", "Sports Tourer", "Coupé-SUV",
    "Grand Sport",
    "Hatchback", "Liftback", "Fastback", "Sportback",
    "Sedan", "Kombi", "Combi", "Variant", "SW", "Avant",
    "Touring", "SUV", "Crossover", "MPV",
]

_AUTH_HYBRID_MAP = {
    "plug-in hybrid": "PHEV", "plug-in": "PHEV", "phev": "PHEV",
    "e-hybrid": "PHEV", "ehybrid": "PHEV",
    "full-hybrid": "HEV", "full hybrid": "HEV", "hev": "HEV",
    "e-tech hybrid": "HEV",
    "mhev": "MHEV", "mild hybrid": "MHEV", "mild-hybrid": "MHEV",
    "elektromobil": "EV", "ev": "EV", "čistě elektrický": "EV",
}

_AUTH_FUEL_MAP = {
    "benzín": "Benzín", "diesel": "Nafta", "nafta": "Nafta",
    "lpg": "LPG", "cng": "CNG",
}


def _parse_brand(text: str) -> tuple[str, str]:
    """Split text into (brand, remainder)."""
    for mb in MULTI_WORD_BRANDS:
        if text.startswith(mb + " ") or text == mb:
            return mb, text[len(mb):].strip()
    parts = text.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _canonicalize_body(body: str) -> str:
    if not body:
        return ""
    return _BODY_CANON.get(body.lower(), body)


def _extract_auth_body(text: str) -> str:
    for kw in _AUTH_BODY_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            return kw
    return ""


def _extract_auth_hybrid(text: str) -> str:
    tl = text.lower()
    for kw, cls in _AUTH_HYBRID_MAP.items():
        if kw in tl:
            return cls
    return ""


def _extract_auth_fuel(text: str) -> str:
    paren = re.search(r'\(([^)]+)\)', text)
    if paren:
        for kw, fuel in _AUTH_FUEL_MAP.items():
            if kw in paren.group(1).lower():
                return fuel
    return ""


def _extract_auth_engine_vol(text: str) -> str:
    m = re.search(r'(?<!\d)(\d[.,]\d)\s*(?=[TtA-Z]|l\b|$)', text)
    if not m:
        m = re.search(r'(?<!\d)(\d[.,]\d)\b', text)
    return m.group(1).replace(',', '.') if m else ""


def _extract_auth_engine_type(text: str) -> str:
    for kw in ENGINE_TYPE_KEYWORDS:
        if re.search(re.escape(kw), text, re.IGNORECASE):
            return kw
    return ""


def _strip_known_parts(text: str, brand: str) -> str:
    """Strip brand, body keywords, engine specs, parenthetical, trim from auth entry to get model base."""
    rest = text
    if rest.startswith(brand + " "):
        rest = rest[len(brand):].strip()
    rest = re.sub(r'\([^)]*\)', '', rest).strip()
    for kw in _AUTH_BODY_KEYWORDS:
        rest = re.sub(r'\b' + re.escape(kw) + r'\b', '', rest, flags=re.IGNORECASE)
    for kw in ENGINE_TYPE_KEYWORDS:
        rest = re.sub(r'\S*' + re.escape(kw) + r'\S*', '', rest, count=1, flags=re.IGNORECASE)
    rest = re.sub(r'(?<!\d)\d[.,]\d(?!\d)', '', rest)
    for kw_label in ("PHEV", "MHEV", "HEV", "Hybrid", "Plug-In", "EV"):
        rest = re.sub(r'\b' + re.escape(kw_label) + r'\b', '', rest, flags=re.IGNORECASE)
    rest = re.sub(r'\s{2,}', ' ', rest).strip()
    return rest


def load_authoritative_list(csv_path) -> list[dict]:
    """Parse authoritative makes-and-models CSV into structured records."""
    records = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            entry = row[0].strip()
            brand, remainder = _parse_brand(entry)
            rec = {
                "entry": entry,
                "brand": brand,
                "model_base": _strip_known_parts(entry, brand),
                "body": _canonicalize_body(_extract_auth_body(entry)),
                "engine_vol": _extract_auth_engine_vol(entry),
                "engine_type": _extract_auth_engine_type(entry),
                "hybrid": _extract_auth_hybrid(entry),
                "fuel": _extract_auth_fuel(entry),
            }
            records.append(rec)
    return records


_GEN_RE = re.compile(r'\b(?:Gen\s*\d+|[Gg]olf\s*)\d+\b')
_TRIM_IN_MODEL_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(k) for k in TRIM_KEYWORDS) + r')\b', re.IGNORECASE
)
_ENGINE_IN_MODEL_RE = re.compile(
    r'\b(?:\d+[.,]\d\s*)?(?:' + '|'.join(re.escape(k) for k in ENGINE_TYPE_KEYWORDS) + r')\S*\b',
    re.IGNORECASE,
)
_NUM_SUFFIX_RE = re.compile(r'\s+\d{2,3}$')


def _clean_model_for_matching(model_remainder: str) -> str:
    """Strip generation numbers, trim keywords, engine specs from model remainder for base matching."""
    text = model_remainder
    text = re.sub(r'\b[Řř]ada\s+', '', text)
    text = re.sub(r'\brad\s+', '', text, flags=re.IGNORECASE)
    for kw in _AUTH_BODY_KEYWORDS:
        text = re.sub(r'\b' + re.escape(kw) + r'\b', '', text, flags=re.IGNORECASE)
    text = _TRIM_IN_MODEL_RE.sub('', text)
    text = _ENGINE_IN_MODEL_RE.sub('', text)
    text = re.sub(r'(?<!\d)\d[.,]\d(?!\d)', '', text)
    text = re.sub(r'\b\d+kW\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b4MATIC\b|\b4x4\b|\bQuattro\b|\bxDrive\b|\b4Motion\b|\b4Drive\b',
                  '', text, flags=re.IGNORECASE)
    text = _NUM_SUFFIX_RE.sub('', text)
    text = re.sub(r'\s+[BbGg]\d+$', '', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def _extract_body_from_model(model: str) -> str:
    for kw in _AUTH_BODY_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', model, re.IGNORECASE):
            return kw
    return ""


def _model_base_match(scraped_base: str, auth_base: str) -> bool:
    """Check if scraped model base matches auth model base."""
    if not scraped_base or not auth_base:
        return False
    sb = scraped_base.lower().split()
    ab = auth_base.lower().split()
    if not sb or not ab:
        return False
    if sb[0] == ab[0]:
        return True
    if ab[0] in sb or sb[0] in ab:
        return True
    return False


def _score_match(scraped: dict, auth: dict) -> int:
    """Score how well a scraped car matches an auth entry. Higher = better."""
    score = 0

    sb = _canonicalize_body(scraped.get("body", ""))
    ab = auth["body"]
    if sb and ab:
        if sb == ab:
            score += 3
        else:
            score -= 2

    sv = scraped.get("engine_vol", "")
    av = auth["engine_vol"]
    if sv and av:
        try:
            if abs(float(sv) - float(av)) <= 0.15:
                score += 2
            else:
                score -= 1
        except ValueError:
            pass

    se = scraped.get("engine_type", "").lower()
    ae = auth["engine_type"].lower()
    if se and ae:
        if se == ae:
            score += 2
        else:
            score -= 1

    sh = scraped.get("hybrid", "")
    ah = auth["hybrid"]
    if sh and ah:
        if sh == ah:
            score += 3
        else:
            score -= 2
    elif sh and not ah:
        score -= 1
    elif ah and not sh:
        score -= 1

    sf = scraped.get("fuel", "")
    af = auth["fuel"]
    if sf and af:
        if sf == af:
            score += 1
        else:
            score -= 1

    return score


def _format_unmatched(brand: str, model_base: str, engine_vol: str, engine_type: str) -> str:
    parts = [brand, model_base]
    if engine_vol:
        parts.append(engine_vol)
    if engine_type:
        parts.append(engine_type)
    return " ".join(p for p in parts if p)


def match_to_authoritative(df, auth_list: list[dict]):
    """Match each row to closest auth entry. Updates 'Model auta' in-place. Returns df."""
    import pandas as pd

    df["Spárováno"] = "Ne"
    matched_count = 0
    unmatched_count = 0

    for idx in df.index:
        model_auta = str(df.at[idx, "Model auta"])
        brand, remainder = _parse_brand(model_auta)

        body_col = str(df.at[idx, "Karoserie"]) if pd.notna(df.at[idx, "Karoserie"]) else ""
        body_from_model = _extract_body_from_model(remainder)
        body = body_col or body_from_model

        engine_vol = str(df.at[idx, "Objem motoru"]) if pd.notna(df.at[idx, "Objem motoru"]) else ""
        engine_type = str(df.at[idx, "Typ motoru"]) if pd.notna(df.at[idx, "Typ motoru"]) else ""
        hybrid = str(df.at[idx, "Hybrid typ"]) if pd.notna(df.at[idx, "Hybrid typ"]) else ""
        fuel = str(df.at[idx, "Palivo"]) if pd.notna(df.at[idx, "Palivo"]) else ""

        cleaned_base = _clean_model_for_matching(remainder)

        scraped = {
            "brand": brand,
            "model_base": cleaned_base,
            "body": body,
            "engine_vol": engine_vol,
            "engine_type": engine_type,
            "hybrid": hybrid,
            "fuel": fuel,
        }

        brand_low = brand.lower()
        alias = _BRAND_MATCH_ALIASES.get(brand_low)
        candidates = [
            a for a in auth_list
            if (a["brand"].lower() == brand_low or a["brand"].lower() == alias)
            and _model_base_match(cleaned_base, a["model_base"])
        ]

        if candidates:
            best = max(candidates, key=lambda a: _score_match(scraped, a))
            df.at[idx, "Model auta"] = best["entry"]
            df.at[idx, "Spárováno"] = "Ano"
            matched_count += 1
        else:
            df.at[idx, "Model auta"] = _format_unmatched(brand, cleaned_base, engine_vol, engine_type)
            unmatched_count += 1

    print(f"  Párování: {matched_count} spárováno, {unmatched_count} nespárováno z {len(df)}")
    return df
