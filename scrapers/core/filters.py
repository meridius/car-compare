"""Single source of truth for the hard search filters each scraper applies.

Two of the four sources pre-filter at the source (sauto's REST API and
mobile.de's app API); the other two scrape a curated dealer inventory whole
(autodraft, energycars) and apply no numeric filter. The shared numeric knobs
below are imported by the adapters that enforce them (so there is exactly one
place to change a threshold) AND surfaced on the dashboard via
``build_data`` → ``cars-meta.json`` → the "Přehled dat" overview, so a site
user can see the selection criteria that shaped the dataset.

Change a value here and the adapter query, the dashboard text, and the
consistency test in ``tests/test_filters.py`` all move together.
"""

# --- Shared numeric knobs (enforced by sauto + mobile.de) -----------------
MIN_YEAR = 2021              # rok výroby od
MAX_MILEAGE_KM = 150000      # nájezd do (raised from 100 000 on family request)
MIN_PRICE_KC = 100000        # spodní cena (operating-lease / deposit backstop)
MAX_PRICE_KC = 750000        # horní cena
MIN_POWER_KW_ICE = 100       # výkon od — spalovací only
MIN_SEATS = 4                # počet míst od


def _km(n):
    """Group thousands with a non-breaking space, Czech style: 150000 -> '150 000'."""
    return f"{n:,}".replace(",", " ")


# --- Human-readable per-source criteria (for the dashboard) ---------------
# Built from the constants above so the advertised numbers can never drift from
# the enforced ones. `common` filters apply to every fuel; `ev`/`ice` are extra.
SOURCE_FILTERS = [
    {
        "source": "Sauto.cz",
        "note": "Předfiltrováno přímo v API sauto.cz — jde o vybranou podmnožinu, ne celou nabídku.",
        "common": [
            f"Cena: {_km(MIN_PRICE_KC)}–{_km(MAX_PRICE_KC)} Kč",
            f"Rok výroby: {MIN_YEAR} a novější",
            f"Nájezd: do {_km(MAX_MILEAGE_KM)} km",
            f"Počet míst: {MIN_SEATS} a více",
            "Počet dveří: 5",
            "Osobní vozy (bez operativního leasingu)",
        ],
        "ev": ["Palivo: elektro", "Tepelné čerpadlo: ano (povinné)"],
        "ice": [
            f"Výkon: {MIN_POWER_KW_ICE} kW a více",
            "Palivo: benzín, nafta, LPG+benzín, CNG+benzín",
            "Stav: nové, ojeté, předváděcí",
            "Karoserie: CUV, kombi, SUV, hatchback, liftback, sedan, MPV",
        ],
    },
    {
        "source": "Mobile.de",
        "note": "Předfiltrováno v API mobile.de; ceny přepočteny z EUR kurzem ČNB.",
        "common": [
            f"Cena: {_km(MIN_PRICE_KC)}–{_km(MAX_PRICE_KC)} Kč",
            f"Rok výroby: {MIN_YEAR} a novější",
            f"Nájezd: do {_km(MAX_MILEAGE_KM)} km",
            f"Počet míst: {MIN_SEATS} a více",
            "Počet dveří: 4 nebo 5",
            "Bez havarovaných vozů",
            "Země: ČR, SK, Německo, Rakousko, Polsko",
        ],
        "ev": ["Palivo: elektro"],
        "ice": [
            f"Výkon: {MIN_POWER_KW_ICE} kW a více",
            "Palivo: benzín, nafta, hybrid (benzín/nafta)",
        ],
    },
    {
        "source": "Autodraft.cz",
        "note": "Kompletní nabídka prodejce — bez číselných filtrů.",
        "common": [],
        "ev": [],
        "ice": [],
    },
    {
        "source": "Energycars.cz",
        "note": "Kompletní nabídka prodejce (pouze elektro) — bez číselných filtrů.",
        "common": [],
        "ev": [],
        "ice": [],
    },
]
