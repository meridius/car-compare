"""Field extraction helpers (applied to Extra / suffix / full card text)."""
import re

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


# Plausible passenger-car displacement (litres) and EV power floor. Source data
# is occasionally garbage (sauto reports 14.9 l for a Kia XCeed, 11 kW for a BYD
# Dolphin Surf); these bounds reject it.
MIN_ENGINE_VOL = 0.6
MAX_ENGINE_VOL = 8.0
MIN_EV_POWER_KW = 20

# hp/PS shorthand that leaks into Extra text (e.g. "156k", "145k") — duplicates
# the power column and is just noise. 2–3 digits + 'k' as a standalone token.
_HP_SHORTHAND_RE = re.compile(r'\b\d{2,3}\s*k\b', re.IGNORECASE)


def _to_float(v):
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def sanitize_engine_volume(vol, fallback_text: str = "") -> str:
    """Return a plausible displacement string (one decimal), recover it from
    fallback_text (the model name), or ''.

    Guards against bad source data such as sauto's 14.9 l for a Kia XCeed (real
    1.5) or 14 l for a KGM Korando. Values inside [MIN_ENGINE_VOL, MAX_ENGINE_VOL]
    pass through; anything else is recovered from the model name when possible.
    """
    f = _to_float(vol)
    if f is not None and MIN_ENGINE_VOL <= f <= MAX_ENGINE_VOL:
        return f"{f:.1f}"
    rec = _to_float(extract_engine_volume_from_model(fallback_text))
    if rec is not None and MIN_ENGINE_VOL <= rec <= MAX_ENGINE_VOL:
        return f"{rec:.1f}"
    return ""


def sanitize_ev_power(power) -> str:
    """Blank implausibly-low EV power (e.g. sauto's 11 kW for a BYD Dolphin Surf).
    No modern EV is below ~20 kW; below the floor we'd rather show blank than wrong.
    """
    f = _to_float(power)
    if f is not None and f >= MIN_EV_POWER_KW:
        return str(int(f)) if f == int(f) else str(f)
    return ""


def _year_of(date_str) -> int | None:
    """First-4-chars-as-year from a detail API date string ('2022-05-01' -> 2022)."""
    if date_str and len(str(date_str)) >= 4 and str(date_str)[:4].isdigit():
        return int(str(date_str)[:4])
    return None


# A "Rok výroby" outside this window (relative to the scrape's current year) is
# never a real value — e.g. sauto returning the 1900-01-01 sentinel for a Dacia
# Bigster whose manufacturing_date says 2026. #17.
MIN_VALID_YEAR = 2000


def repair_year(year_str, in_operation_date, manufacturing_date, current_year) -> str | None:
    """Reconcile a scraped 'Rok výroby' against the detail API's own date fields.

    sauto's search-index year can drift from the freshly-fetched per-listing
    detail (a dealer correction lands in the detail endpoint before the search
    index catches up) — e.g. a listing shows year "2002" while its own
    in_operation_date says "2022-01-01" (this also naturally covers 19XX/20XX
    century mixups: whatever the detail fields say wins). The detail fields are
    fetched live at scrape time and are authoritative; year_str may come from a
    stale cached search-index snapshot.

    Years outside [MIN_VALID_YEAR, current_year + 1] are also invalid on their
    face (sauto sometimes returns an in_operation_date of "1900-01-01" — a
    sentinel, not a real registration date). In that case in_operation_date is
    skipped in favour of manufacturing_date even though it's normally preferred.

    Returns the repaired 4-digit year string; "" when there was never any year
    data to begin with (nothing to repair, leave the field blank); or None when
    year_str held an explicit but invalid value that neither detail field can
    repair — the caller should drop the row rather than publish a bogus year.
    """
    max_year = current_year + 1

    def in_range(y):
        return y is not None and MIN_VALID_YEAR <= y <= max_year

    op_year = _year_of(in_operation_date)
    mfg_year = _year_of(manufacturing_date)
    candidate = op_year if in_range(op_year) else mfg_year if in_range(mfg_year) else None

    y = int(year_str) if year_str and str(year_str).isdigit() else None

    if candidate is not None and y != candidate:
        reason = "neplatný" if not in_range(y) else "neshodující se"
        print(f"Sauto: opraven {reason} rok výroby {year_str!r} -> {candidate} "
              f"(dle in_operation_date/manufacturing_date)")
        return str(candidate)

    if in_range(y):
        return str(y)

    if y is None:
        return ""  # no year data at all — legitimately blank, not a defect

    print(f"Sauto: neplatný rok výroby {year_str!r} nelze opravit "
          f"(in_operation_date/manufacturing_date chybí nebo jsou také neplatné) — řádek zahozen")
    return None


def clean_ev_suffix(suffix: str, model_base: str) -> str:
    """Strip a leading duplicate of the model name and hp shorthand from an EV
    listing suffix before it becomes Extra text (e.g.
    "BYD Dolphin Surf 156k COMFORT" + "BYD Dolphin Surf" -> "COMFORT")."""
    s = suffix or ""
    if model_base:
        s = re.sub(r'^\s*' + re.escape(model_base) + r'\s*', '', s, count=1, flags=re.IGNORECASE)
    s = _HP_SHORTHAND_RE.sub('', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(' /,')
    return s


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
    _HP_SHORTHAND_RE,
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
