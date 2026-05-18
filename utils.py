"""Shared utilities for car scrapers."""

# Short aliases for verbose brand names applied to scraped model strings
BRAND_MAP = {
    "Volkswagen": "VW",
}


def normalize_model(model: str) -> str:
    """Replace a verbose brand prefix with its short alias (e.g. Volkswagen → VW)."""
    for full, short in BRAND_MAP.items():
        if model == full or model.startswith(full + " "):
            return short + model[len(full):]
    return model
