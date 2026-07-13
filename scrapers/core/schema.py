"""Canonical CSV schema shared by every scraper source."""

TYP_EV = "Elektrické"
TYP_ICE = "Spalovací"

# Canonical column order. Every source emits exactly these columns.
CANONICAL_COLS = [
    "Typ", "Model auta", "Cena (Kč)", "Nájezd (km)", "Rok výroby",
    "Palivo", "Objem motoru", "Typ motoru", "Počet válců", "Hybrid typ", "Výkon (kW)",
    "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
    "Kola", "Náhon 4x4", "Karoserie", "Verze", "Záruka", "Tepelné čerpadlo",
    "Spárováno", "Skóre shody", "Extra", "Stav", "Odstraněno dne", "Země", "Zdroj",
    "Odkaz na auto", "Přidáno", "Upraveno",
]

# Boolean columns that should be normalized to proper case: "Ano" or "Ne".
# These columns hold yes/no or tri-state (Ano/Nejisté/Ne) values; normalize_ano_ne()
# normalizes "ano"/"ANO" → "Ano" and "ne"/"NE" → "Ne", leaves others unchanged.
ANO_NE_COLS = [
    "Dvouspojková převodovka",
    "Filtr pevných částic",
    "Náhon 4x4",
    "Záruka",
    "Tepelné čerpadlo",
    "Spárováno",
]


def blank_row() -> dict:
    """Return a dict with every canonical column set to ''. Adapters fill what they have."""
    return {c: "" for c in CANONICAL_COLS}
