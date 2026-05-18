"""Shared utilities for car scrapers."""

import re

# Short aliases for verbose brand names applied to scraped model strings
BRAND_MAP = {
    "Volkswagen": "VW",
}

# Regex substitutions applied after brand normalisation to fix common naming errors.
# Each entry is (compiled_pattern, replacement_string).
MODEL_CLEANUP_PATTERNS = [
    # "Škoda Enyaq 50/60/80" → "Škoda Enyaq iV 50/60/80"  (variant number without "iV")
    (re.compile(r'(Škoda Enyaq)(?!\s+iV)\s+(\d{2})\b'), r'\1 iV \2'),
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
