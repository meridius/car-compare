"""Authoritative list matching for combustion scrapers."""
import csv
import re

from .fields import ENGINE_TYPE_KEYWORDS, TRIM_KEYWORDS

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
    # SUV absorbs the listing-side synonyms sauto/mobile.de emit (CUV, Czech
    # "Terénní", English "Offroad") so a scraped-body vs auth-body scoring
    # comparison doesn't spuriously penalise an obvious SUV.
    "SUV": {"SUV", "Crossover", "CUV", "Terénní", "Offroad", "OffRoad"},
    "Sedan": {"Sedan", "Sedan/limuzína", "Limuzína"},
    "MPV": {"MPV", "VAN", "Van"},
    "Kupé": {"Kupé", "Coupé", "Coupe"},
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


def load_authoritative_list(csv_path) -> list[dict]:
    """Parse the structured reference CSV into matching records.

    Feature columns (Značka, Model, Karoserie, Objem motoru, Typ motoru, Palivo,
    Hybrid typ, Verze) are read directly — no regex-parsing of the display name.
    The display name ('Jednoznačná varianta vozu') is the entry/PK only."""
    def col(row, name):
        return (row.get(name) or "").strip()

    records = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = col(row, "Jednoznačná varianta vozu")
            if not entry:
                continue
            records.append({
                "entry": entry,
                "brand": col(row, "Značka"),
                "model_base": col(row, "Model"),
                "body": _canonicalize_body(col(row, "Karoserie")),
                # Unfolded reference body — the display value the dashboard shows
                # for matched rows (build_data.apply_reference_body_specs). "body"
                # above is scoring-folded (e.g. Liftback→Hatchback) and must NOT be
                # used for display; "body_raw" keeps Liftback/Sportback/… distinct.
                "body_raw": col(row, "Karoserie"),
                "engine_vol": col(row, "Objem motoru"),
                "engine_type": col(row, "Typ motoru"),
                "hybrid": col(row, "Hybrid typ"),
                "fuel": col(row, "Palivo"),
                "trim": col(row, "Verze"),
                "seats": col(row, "Počet míst"),
            })
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

    # Trim (Verze) disambiguates otherwise-identical variants kept as separate
    # reference rows (e.g. Octavia Style vs Selection). Only scored when both sides
    # carry a trim, so the many trim-less reference rows are unaffected.
    st = scraped.get("trim", "")
    at = auth.get("trim", "")
    if st and at:
        if st == at:
            score += 2
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


# Confidence thresholds for promoting a candidate to a confident "Ano".
# A match is only trusted (Spárováno="Ano") when the winning candidate scores at
# least STRONG_FLOOR *and* beats the runner-up by at least MARGIN_REQ. Otherwise
# the model is still our best guess but flagged "Nejisté" (uncertain) — typically
# thin data (score<=0, contradicts the row's own fields) or a tie between distinct
# variants (e.g. "1.2" vs "1.2 Turbo"). Tune here; tests assert the resulting band.
STRONG_FLOOR = 1
MARGIN_REQ = 1


def find_candidates(scraped: dict, auth_list: list[dict]) -> list[dict]:
    """Auth entries whose brand (incl. alias) and model base match the scraped car."""
    brand_low = scraped["brand"].lower()
    alias = _BRAND_MATCH_ALIASES.get(brand_low)
    return [
        a for a in auth_list
        if (a["brand"].lower() == brand_low or a["brand"].lower() == alias)
        and _model_base_match(scraped["model_base"], a["model_base"])
    ]


def classify_match(scraped: dict, auth_list: list[dict]) -> dict:
    """Classify a scraped car against the auth list. Pure — no DataFrame, unit-testable.

    Returns {"state", "score", "margin", "entry"}:
      - state "Ano"     — confident: best score >= STRONG_FLOOR and clear margin
      - state "Nejisté" — candidate found but weak/ambiguous (thin data or tie)
      - state "Ne"      — no candidate at all (caller reformats the name)
    score/margin/entry are None when state == "Ne".
    """
    candidates = find_candidates(scraped, auth_list)
    if not candidates:
        return {"state": "Ne", "score": None, "margin": None, "entry": None}

    scored = sorted(
        ((_score_match(scraped, a), a) for a in candidates),
        key=lambda x: x[0], reverse=True,
    )
    best_score, best = scored[0]
    margin = (best_score - scored[1][0]) if len(scored) > 1 else None
    confident = best_score >= STRONG_FLOOR and (margin is None or margin >= MARGIN_REQ)
    return {
        "state": "Ano" if confident else "Nejisté",
        "score": best_score,
        "margin": margin,
        "entry": best["entry"],
    }


def match_to_authoritative(df, auth_list: list[dict]):
    """Match each row to closest auth entry. Sets 'Model auta', 'Spárováno' (tri-state
    Ano/Nejisté/Ne) and 'Skóre shody' (match confidence). Returns df."""
    import pandas as pd

    df["Spárováno"] = "Ne"
    if "Skóre shody" not in df.columns:
        df["Skóre shody"] = ""
    # Coerce to object dtype before writing: the column may arrive as strict
    # StringDtype (fresh scrape, seeded "" — pandas 3.x rejects ints) or as
    # float64 (CSV round-trip in build_data — rejects strings). object accepts
    # both the "" sentinel and stringified scores; build_data later coerces
    # "Skóre shody" back to numeric for cars.json.
    df["Skóre shody"] = df["Skóre shody"].astype(object)
    counts = {"Ano": 0, "Nejisté": 0, "Ne": 0}

    for idx in df.index:
        model_auta = str(df.at[idx, "Model auta"])
        brand, remainder = _parse_brand(model_auta)

        body_col = str(df.at[idx, "Karoserie"]) if pd.notna(df.at[idx, "Karoserie"]) else ""
        body = body_col or _extract_body_from_model(remainder)

        engine_vol = str(df.at[idx, "Objem motoru"]) if pd.notna(df.at[idx, "Objem motoru"]) else ""
        engine_type = str(df.at[idx, "Typ motoru"]) if pd.notna(df.at[idx, "Typ motoru"]) else ""
        cleaned_base = _clean_model_for_matching(remainder)

        scraped = {
            "brand": brand,
            "model_base": cleaned_base,
            "body": body,
            "engine_vol": engine_vol,
            "engine_type": engine_type,
            "hybrid": str(df.at[idx, "Hybrid typ"]) if pd.notna(df.at[idx, "Hybrid typ"]) else "",
            "fuel": str(df.at[idx, "Palivo"]) if pd.notna(df.at[idx, "Palivo"]) else "",
            "trim": str(df.at[idx, "Verze"]) if "Verze" in df.columns and pd.notna(df.at[idx, "Verze"]) else "",
        }

        res = classify_match(scraped, auth_list)
        counts[res["state"]] += 1
        if res["state"] == "Ne":
            df.at[idx, "Model auta"] = _format_unmatched(brand, cleaned_base, engine_vol, engine_type)
            df.at[idx, "Spárováno"] = "Ne"
            df.at[idx, "Skóre shody"] = ""
        else:
            df.at[idx, "Model auta"] = res["entry"]
            df.at[idx, "Spárováno"] = res["state"]
            df.at[idx, "Skóre shody"] = str(res["score"])

    print(f"  Párování: {counts['Ano']} Ano, {counts['Nejisté']} Nejisté, "
          f"{counts['Ne']} Ne z {len(df)}")
    return df
