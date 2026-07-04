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


def _build_row(item, rate):
    """One canonical row from a search item, or None when the listing is dropped."""
    attr = item.get("attr") or {}
    ft = attr.get("ft", "")
    if ft not in _FUEL_MAP:
        return None  # LPG/CNG/hydrogen/other — excluded fuels (belt-and-suspenders)
    kc = _price_kc(item, rate)
    if kc is None:
        return None
    link = item.get("url") or ""
    if not link:
        return None

    make = (item.get("make") or {}).get("localized", "")
    model = (item.get("model") or {}).get("localized", "")
    model_base = normalize_model(f"{make} {model}".strip())
    sub = item.get("subTitle") or ""
    title_text = f"{item.get('shortTitle') or ''} {sub}".strip()
    body = _CATEGORY_MAP.get(attr.get("c", ""), "") or extract_body_type(title_text)
    loc_token = " ".join(p for p in (attr.get("cn"), attr.get("loc")) if p)
    awd = "Ano" if extract_awd(title_text) == "Ano" else "Ne"

    row = schema.blank_row()
    row.update({
        "Model auta": model_base, "Cena (Kč)": kc,
        "Nájezd (km)": _parse_number(attr.get("ml")),
        "Rok výroby": _year_from_fr(attr.get("fr")),
        "Výkon (kW)": _parse_number(attr.get("pw")),
        "Karoserie": body, "Náhon 4x4": awd,
        "Zdroj": SOURCE_NAME, "Odkaz na auto": link,
    })

    if ft == "Elektro":
        extra_parts = [loc_token]
        if attr.get("bc"):
            extra_parts.append(f"Baterie {_parse_number(attr['bc'])} kWh")
        sub_clean = clean_ev_suffix(sub, model_base)
        if sub_clean:
            extra_parts.append(sub_clean)
        row.update({
            "Typ": schema.TYP_EV, "Palivo": "Elektro",
            "Extra": " / ".join(p for p in extra_parts if p),
        })
        return row

    cc = _parse_number(attr.get("cc"))
    volume = f"{cc / 1000:.1f}" if cc else ""
    volume = sanitize_engine_volume(volume, f"{model_base} {sub}")
    gearbox = _TRANSMISSION_MAP.get(attr.get("tr", ""), "")
    hybrid = extract_hybrid_type(sub)
    if not hybrid and ft in _HYBRID_FTS:
        hybrid = "HEV"
    extracted = {
        "Objem motoru": volume,
        "Typ motoru": extract_engine_type(sub),
        "Hybrid typ": hybrid,
        "Karoserie": body,
        "Výbava": extract_trim(sub),
        "Záruka": "Ano" if attr.get("gi") else extract_warranty(sub),
        "Dvouspojková převodovka": extract_dct(f"{gearbox} {sub}"),
        "Filtr pevných částic": extract_particle_filter(sub),
    }
    extra_text = clean_extra(sub, extracted)
    row.update({
        "Typ": schema.TYP_ICE, "Palivo": _FUEL_MAP[ft],
        "Převodovka": gearbox,
        "Extra": " / ".join(p for p in (loc_token, extra_text) if p),
        **extracted,
    })
    return row


def _rate_from_cnb_text(text):
    """EUR row from the CNB daily-fixing text, or None when unparsable."""
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) == 5 and parts[3] == "EUR":
            try:
                return float(parts[4].replace(",", ".")) / float(parts[2])
            except ValueError:
                return None
    return None


async def _get_eur_czk_rate(session):
    """CNB daily EUR/CZK fixing; falls back to a constant so a CNB outage never kills the scrape."""
    try:
        async with session.get(CNB_RATE_URL) as resp:
            resp.raise_for_status()
            rate = _rate_from_cnb_text(await resp.text())
            if rate:
                return rate
    except Exception:
        pass
    print(f"  Varování: kurz ČNB nedostupný, používám {EUR_CZK_FALLBACK}")
    return EUR_CZK_FALLBACK


async def _search(session, params, offset, page_size=PAGE_SIZE):
    """One search GET; retries once, then propagates (a dead endpoint must abort
    the source before pipeline writes the CSV, keeping yesterday's file intact)."""
    query = [(k, str(v)) for k, v in params] + [("ps", str(offset)), ("psz", str(page_size))]
    for attempt in (1, 2):
        try:
            await asyncio.sleep(random.uniform(0.05, 0.2))  # politeness jitter
            async with session.get(SEARCH_URL, params=query) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(1 + random.random())


async def _count(session, params):
    data = await _search(session, params, 0, page_size=1)
    return data.get("numResultsTotal") or 0


async def _fetch_slice(session, params, total, sem):
    """Page one sub-cap query to its end. Pages are serial inside the slice;
    the semaphore bounds cross-slice concurrency."""
    items = []
    for offset in range(0, min(total, RESULT_CAP), PAGE_SIZE):
        async with sem:
            data = await _search(session, params, offset)
        batch = data.get("items") or []
        if not batch:
            break
        items.extend(batch)
    return items


async def _fetch_banded(session, params, price_lo, price_hi, sem):
    """Fetch every result by recursively halving the EUR price band while a
    band would hit the 2000-result cap. Boundary duplicates are deduped by
    link in pipeline.run_source."""
    banded = tuple(params) + (("p", f"{price_lo}:{price_hi}"),)
    total = await _count(session, banded)
    if total == 0:
        return []
    if total < RESULT_CAP or price_hi - price_lo <= 1:
        return await _fetch_slice(session, banded, total, sem)
    mid = (price_lo + price_hi) // 2
    halves = await asyncio.gather(
        _fetch_banded(session, params, price_lo, mid, sem),
        _fetch_banded(session, params, mid + 1, price_hi, sem),
    )
    return halves[0] + halves[1]


async def _scrape_config(session, fuels, countries, extra, rate, sem, label):
    params = _BASE_PARAMS + tuple(fuels) + tuple(("cn", c) for c in countries) + tuple(extra)
    eur_ceiling = round(PRICE_CEILING_KC / rate)
    items = await _fetch_banded(session, params, 0, eur_ceiling, sem)
    print(f"  {label}: staženo {len(items)} položek")
    return [r for r in (_build_row(it, rate) for it in items) if r is not None]


async def scrape():
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        rate = await _get_eur_czk_rate(session)
        print(f"  Kurz EUR/CZK: {rate}")
        print("Načítám EV inzeráty z Mobile.de API...")
        ev = await _scrape_config(session, EV_FUELS, EV_COUNTRIES, (), rate, sem, "EV")
        print("Načítám ICE inzeráty z Mobile.de API...")
        ice = await _scrape_config(session, ICE_FUELS, ICE_COUNTRIES, ICE_EXTRA,
                                   rate, sem, "ICE")
    return ev + ice
