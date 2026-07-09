"""Brand/model normalisation shared by all sources."""
import re

BRAND_MAP = {
    "Volkswagen": "VW",
    # mobile.de strips diacritics from make names
    "Skoda": "Škoda",
    "Citroen": "Citroën",
}

# Union of electric + combustion cleanup patterns. Order: brand-expanded input assumed.
MODEL_CLEANUP_PATTERNS = [
    # electric: "Škoda Enyaq 60" → "Škoda Enyaq iV 60"
    (re.compile(r'(Škoda Enyaq)(?!\s+iV)\s+(\d{2})\b'), r'\1 iV \2'),
    # combustion:
    (re.compile(r'X-Perience', re.IGNORECASE), 'Xperience'),
    (re.compile(r'\bcombi\b'), 'Combi'),
    (re.compile(r'\bScout Combi\b'), 'Combi Scout'),
    (re.compile(r'\bRS Combi\b'), 'Combi RS'),
    # sauto writes Cee´d (acute accent), mobile.de writes cee'd / cee’d
    # (straight/typographic apostrophe) — fold every spelling to "Ceed".
    (re.compile(r"Cee[´'’]d", re.IGNORECASE), 'Ceed'),
    # listings write the ProCeed shooting brake as "Pro_Ceed" / "Pro Ceed";
    # fold to the reference spelling so they match "Kia ProCeed ...".
    (re.compile(r'Pro[_\s]?Ceed'), 'ProCeed'),
    # GWM Ora 03 == ORA Funky Cat == Ora Good Cat: same physical car sold under
    # multiple market names (grow-reference once added both as separate
    # ev_specs.csv rows, purely because listings arrive under two spellings).
    # Collapse every spelling to the one row that survives in ev_specs.csv.
    # Deliberately narrow — this is NOT a general "same platform" rule; distinct
    # badge-engineered cars (e.g. Škoda Citigo-e / VW e-up!) are left alone.
    (re.compile(r'(?:GWM\s+)?ORA\s+(?:Funky|Good)\s*Cat', re.IGNORECASE), 'GWM Ora 03'),
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
