"""Shared utilities for combustion car scrapers."""

import re

BRAND_MAP = {
    "Volkswagen": "VW",
}

MODEL_CLEANUP_PATTERNS = [
    (re.compile(r'X-Perience', re.IGNORECASE), 'Xperience'),
    (re.compile(r'\bcombi\b'), 'Combi'),
    (re.compile(r'\bScout Combi\b'), 'Combi Scout'),
    (re.compile(r'\bRS Combi\b'), 'Combi RS'),
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
    "Monte Carlo",
    "Top Selection",
    "R-Line", "RS Line", "R.S.Line", "RS-Line",
    "GT-Line", "GT Line",
    "N-Line", "N Line",
    "ST-Line", "ST Line",
    "N-Connecta", "N-CONNECTA",
    "FR", "Xcellence", "Sportline",
    "Titanium", "Tekna", "Elegance", "Style", "Exclusive",
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
_AWD_EXTRA_RE = re.compile(r'\b(?:4x4|AWD)\b', re.IGNORECASE)
_PARTICLE_FILTER_RE = re.compile(r'\b[GD]PF\b', re.IGNORECASE)


def extract_engine_volume(text: str) -> str:
    """Extract displacement like '1.5' or '2.0' from text."""
    m = _ENGINE_VOL_RE.search(text)
    if not m:
        m = _ENGINE_VOL_START_RE.search(text)
    return m.group(1).replace(',', '.') if m else ""


def extract_engine_type(text: str) -> str:
    """Extract engine technology (TSI, TDI, EcoBoost, etc.)."""
    for kw in ENGINE_TYPE_KEYWORDS:
        if re.search(re.escape(kw), text, re.IGNORECASE):
            return kw
    return ""


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

    text = re.sub(r'\s*/\s*', ' / ', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'(^[/\s,]+|[/\s,]+$)', '', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'(?:^|\s)/\s', ' ', text).strip()
    text = re.sub(r'\s/\s*$', '', text).strip()
    return text
