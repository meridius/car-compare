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
    (re.compile(r'Cee´d', re.IGNORECASE), 'Ceed'),
    # listings write the ProCeed shooting brake as "Pro_Ceed" / "Pro Ceed";
    # fold to the reference spelling so they match "Kia ProCeed ...".
    (re.compile(r'Pro[_\s]?Ceed'), 'ProCeed'),
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
