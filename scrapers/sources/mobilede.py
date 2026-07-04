"""Mobile.de adapter — EV + ICE listings via the mobile-app JSON endpoint.

Keyless: only the X-Mobile-Client header is required. The endpoint is
undocumented and robots-disallowed — see docs/gotchas.md → mobile.de for the
caveats and the sanctioned Search-API upgrade path.
"""
import asyncio
import random
import re

import aiohttp

from scrapers.core import http, schema
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import (
    extract_body_type, extract_engine_type, extract_hybrid_type, extract_trim,
    extract_warranty, extract_dct, extract_particle_filter, extract_awd,
    clean_extra, sanitize_engine_volume, clean_ev_suffix,
)

SOURCE_NAME = "Mobile.de"
SOURCE_SLUG = "mobilede"
FUELS = {"EV", "ICE"}

SEARCH_URL = "https://www.mobile.de/api/s/"
CNB_RATE_URL = ("https://www.cnb.cz/cs/financni_trhy/devizovy_trh/"
                "kurzy_devizoveho_trhu/denni_kurz.txt")
EUR_CZK_FALLBACK = 24.5
PRICE_CEILING_KC = 750000
MIN_PRICE_KC = 100000  # same operating-lease/deposit backstop as sauto

HEADERS = {**http.DEFAULT_HEADERS, "X-Mobile-Client": "de.mobile.android.app"}

# The app API silently caps any query at 2000 reachable results; bigger
# queries are split recursively on price bands (EUR) until each slice fits.
RESULT_CAP = 2000
PAGE_SIZE = 100
CONCURRENCY = 5

EV_COUNTRIES = ("CZ", "SK", "AT", "PL", "DE")
# DE deliberately excluded for ICE: ~123k results even at >=100 kW.
ICE_COUNTRIES = ("CZ", "SK", "AT", "PL")

_BASE_PARAMS = (
    ("s", "Car"), ("vc", "Car"),
    ("fr", "2021:"), ("ml", ":100000"),
    ("sc", "4:"), ("door", "FOUR_OR_FIVE"), ("dam", "false"),
)
EV_FUELS = (("ft", "ELECTRICITY"),)
ICE_FUELS = tuple(("ft", f) for f in ("PETROL", "DIESEL", "HYBRID", "HYBRID_DIESEL"))
ICE_EXTRA = (("pw", "100:"),)

_HYBRID_FTS = {"Hybrid (Benzin/Elektro)", "Hybrid (Diesel/Elektro)"}
_FUEL_MAP = {
    "Benzin": "Benzín",
    "Diesel": "Nafta",
    "Elektro": "Elektro",
    "Hybrid (Benzin/Elektro)": "Benzín",
    "Hybrid (Diesel/Elektro)": "Nafta",
}
_TRANSMISSION_MAP = {
    "Automatik": "Automatická",
    "Halbautomatik": "Automatická",
    "Schaltgetriebe": "Manuální",
}
_CATEGORY_MAP = {
    "OffRoad": "SUV", "EstateCar": "Kombi", "Limousine": "Sedan/limuzína",
    "SmallCar": "Hatchback", "Van": "VAN", "SportsCar": "Kupé",
    "Cabrio": "Kabriolet", "OtherCar": "",
}

_NUM_RE = re.compile(r'\d[\d.]*')


def _parse_number(text):
    """First integer in a German attr string: '29.000 km' -> 29000, '110 kW (150 PS)' -> 110."""
    m = _NUM_RE.search(str(text or ""))
    return int(m.group().rstrip(".").replace(".", "")) if m else ""


def _year_from_fr(fr):
    """First-registration attr '02/2022' -> '2022'."""
    m = re.search(r'(\d{4})', str(fr or ""))
    return m.group(1) if m else ""


def _price_kc(item, rate):
    """Gross fixed price converted to Kč, or None when the row must be dropped."""
    price = item.get("price") or {}
    if price.get("type") != "FIXED":
        return None
    amount = (price.get("grs") or {}).get("amount")
    if not amount:
        return None
    kc = round(float(amount) * rate)
    if not MIN_PRICE_KC <= kc <= PRICE_CEILING_KC:
        return None
    return kc
