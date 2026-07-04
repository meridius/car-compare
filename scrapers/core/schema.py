"""Canonical CSV schema shared by every scraper source."""

TYP_EV = "Elektrické"
TYP_ICE = "Spalovací"

# Canonical column order. Every source emits exactly these columns.
CANONICAL_COLS = [
    "Typ", "Model auta", "Cena (Kč)", "Nájezd (km)", "Rok výroby",
    "Palivo", "Objem motoru", "Typ motoru", "Hybrid typ", "Výkon (kW)",
    "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
    "Kola", "Náhon 4x4", "Karoserie", "Výbava", "Záruka", "Tepelné čerpadlo",
    "Spárováno", "Skóre shody", "Extra", "Stav", "Země", "Zdroj", "Odkaz na auto",
]


def blank_row() -> dict:
    """Return a dict with every canonical column set to ''. Adapters fill what they have."""
    return {c: "" for c in CANONICAL_COLS}
