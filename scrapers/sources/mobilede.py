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
from scrapers.core import filters
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import (
    extract_body_type, extract_engine_type, extract_hybrid_type, extract_trim,
    extract_warranty, extract_dct, extract_particle_filter, extract_awd,
    clean_extra, sanitize_engine_volume, sanitize_ev_power, clean_ev_suffix,
)

SOURCE_NAME = "Mobile.de"
SOURCE_SLUG = "mobilede"
FUELS = {"EV", "ICE"}

SEARCH_URL = "https://www.mobile.de/api/s/"
CNB_RATE_URL = ("https://www.cnb.cz/cs/financni_trhy/devizovy_trh/"
                "kurzy_devizoveho_trhu/denni_kurz.txt")
EUR_CZK_FALLBACK = 24.5
PRICE_CEILING_KC = filters.MAX_PRICE_KC
MIN_PRICE_KC = filters.MIN_PRICE_KC  # same operating-lease/deposit backstop as sauto

HEADERS = {**http.DEFAULT_HEADERS, "X-Mobile-Client": "de.mobile.android.app"}

# The app API silently caps any query at 2000 reachable results; bigger
# queries are split recursively on price bands (EUR) until each slice fits.
RESULT_CAP = 2000
PAGE_SIZE = 100
# Low on purpose: the endpoint is behind Akamai Bot Manager (see _search). Steady,
# low-concurrency access from the CI (datacenter) IP is far less likely to trip a
# behavioural block than the old bursty fan-out. Every request is sem-bounded.
CONCURRENCY = 3

EV_COUNTRIES = ("CZ", "SK", "AT", "PL", "DE")
ICE_COUNTRIES = ("CZ", "SK", "AT", "PL", "DE")

_BASE_PARAMS = (
    ("s", "Car"), ("vc", "Car"),
    ("fr", f"{filters.MIN_YEAR}:"), ("ml", f":{filters.MAX_MILEAGE_KM}"),
    ("sc", f"{filters.MIN_SEATS}:"), ("door", "FOUR_OR_FIVE"), ("dam", "false"),
)
EV_FUELS = (("ft", "ELECTRICITY"),)
ICE_FUELS = tuple(("ft", f) for f in ("PETROL", "DIESEL", "HYBRID", "HYBRID_DIESEL"))
ICE_EXTRA = (("pw", f"{filters.MIN_POWER_KW_ICE}:"),)

# attr.cn is an ISO-3166 alpha-2 code; the canonical "Země" column carries the
# Czech country name. Unknown codes fall through as-is (never silently dropped).
_COUNTRY_MAP = {
    "CZ": "Česko", "SK": "Slovensko", "DE": "Německo",
    "AT": "Rakousko", "PL": "Polsko",
}

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

# "Andere" (German "Other") is mobile.de's junk model bucket for cars its
# taxonomy doesn't index — like sauto's "Ostatní". The real name hides in
# subTitle (known make) or shortTitle (make itself "Andere"). Never emit an
# "X Andere" reference row — see docs/gotchas.md → mobile.de → "Andere".
_ANDERE = "Andere"

# Known rebadges the generic first-token heuristic would get wrong.
_ANDERE_RECOVERY = [
    # Elaris Beo is the rebadged Skywell ET5 — dealers list the donor name.
    (lambda make, text: make == "Elaris"
     and re.search(r"\b(?:skywell|et5)\b", text, re.IGNORECASE),
     "Elaris Beo"),
]

# subTitle/shortTitle openers that are never a model name (fuel / body /
# German marketing filler seen in live probes).
_ANDERE_JUNK_TOKENS = {
    "andere", "other", "elektro", "electric", "benzin", "diesel", "hybrid",
    "bev", "phev", "suv", "van", "kombi", "limousine", "coupe", "neu", "nur",
    "top", "original", "automatik", "aus", "der", "die", "das", "mit",
    "inkl", "ab",
}
_ANDERE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.'’\-]*$")
# bare 1-2 digit numbers, decimals and years are engine/spec tokens
_ANDERE_NUMERIC_RE = re.compile(r"^(?:\d{1,2}|\d+[.,]\d+|(?:19|20)\d\d)$")


def _andere_token_ok(tok):
    return (len(tok) >= 2
            and bool(_ANDERE_TOKEN_RE.match(tok))
            and not _ANDERE_NUMERIC_RE.match(tok)
            and tok.lower() not in _ANDERE_JUNK_TOKENS)


def _recover_andere_model(make, model, short_title, sub):
    """Real "Make Model" behind mobile.de's Andere bucket, or ("", sub).

    Returns (recovered_name, sub_rest); sub_rest has the consumed model token
    stripped so downstream extraction/Extra don't duplicate it. Unrecoverable
    or non-Andere rows return ("", sub) unchanged — mirror of sauto's
    _recover_ostatni_model, with a generic title-token fallback on top of the
    curated list because Andere spans ~20 open-ended clusters.
    """
    if _ANDERE not in (make, model):
        return "", sub
    for predicate, name in _ANDERE_RECOVERY:
        if predicate(make, f"{short_title} {sub}"):
            return name, sub
    if make == _ANDERE:
        # real "Make Model" leads the shortTitle after the "Andere " prefix
        text = re.split(r"[/*|,(+]", short_title or "", 1)[0].strip()
        toks = text.split()
        if toks and toks[0] == _ANDERE:
            toks = toks[1:]
        if len(toks) >= 2 and all(_andere_token_ok(t) for t in toks[:2]):
            # "CITROEN" → "Citroen" so BRAND_MAP can restore diacritics;
            # short all-caps brands (BMW, GWM, JAC) stay untouched
            return " ".join(t.title() if t.isalpha() and t.isupper()
                            and len(t) > 3 else t for t in toks[:2]), sub
        return "", sub
    # known make, model "Andere": subTitle opens with the real model token
    text = re.split(r"[/*|,(+]", sub or "", 1)[0].strip()
    toks = text.split()
    if not toks or not _andere_token_ok(toks[0]):
        return "", sub
    tok = toks[0]
    if tok.isalpha() and tok.isupper() and len(tok) > 2:
        tok = tok.title()  # "PIO" → "Pio"; "JS8"/"ZS" stay as-is
    rest = re.sub(re.escape(toks[0]), "", sub, count=1).strip(" -/")
    return f"{make} {tok}", rest


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
    sub = item.get("subTitle") or ""
    recovered, sub = _recover_andere_model(
        make, model, item.get("shortTitle") or "", sub)
    model_base = normalize_model(recovered or f"{make} {model}".strip())
    title_text = f"{item.get('shortTitle') or ''} {sub}".strip()
    body = _CATEGORY_MAP.get(attr.get("c", ""), "") or extract_body_type(title_text)
    # Country goes to its own "Země" column now; Extra keeps only the city.
    zeme = _COUNTRY_MAP.get(attr.get("cn", ""), attr.get("cn", ""))
    loc_token = attr.get("loc") or ""
    awd = "Ano" if extract_awd(title_text) == "Ano" else "Ne"

    row = schema.blank_row()
    row.update({
        "Model auta": model_base, "Cena (Kč)": kc,
        "Nájezd (km)": _parse_number(attr.get("ml")),
        "Rok výroby": _year_from_fr(attr.get("fr")),
        "Výkon (kW)": _parse_number(attr.get("pw")),
        "Karoserie": body, "Náhon 4x4": awd, "Země": zeme,
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
            # Some EV listings (Dacia Spring, Hyundai Kona Elektro, Opel
            # Mokka/-e) carry an explicit 'pw': '0 kW' — same implausible-power
            # guard sauto applies (sanitize_ev_power, core/fields.py).
            "Výkon (kW)": sanitize_ev_power(row["Výkon (kW)"]),
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
        "Verze": extract_trim(sub),
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


# The endpoint sits behind Akamai Bot Manager, which returns a bare 403 (no
# Retry-After / rate-limit headers) once a datacenter IP crosses a cumulative,
# behavioural threshold — it doesn't trip on instantaneous concurrency (probed
# 120 concurrent = all 200) but on sustained volume from a flagged (cloud) IP.
# So: bound EVERY request through the semaphore (incl. counts — see below) and,
# on a block, back off progressively to let the (windowed) block clear before
# giving up. 503/429 are treated the same way.
_RATE_LIMIT_STATUSES = {403, 429, 503}
_SEARCH_ATTEMPTS = 5
_RATE_LIMIT_BACKOFF = (5, 15, 45, 90)  # seconds; index by attempt, last repeats


class _RateLimited(Exception):
    def __init__(self, retry_after=None):
        self.retry_after = retry_after


class _AsyncNull:
    """Async no-op context — lets _search run without a semaphore (tests)."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _parse_retry_after(headers):
    """Seconds from a Retry-After header, if present and numeric (Akamai sends
    none, but honour it if the endpoint ever grows one). HTTP-date form → None."""
    val = headers.get("Retry-After") if headers else None
    try:
        return float(val) if val else None
    except (TypeError, ValueError):
        return None


async def _search(session, params, offset, sem, page_size=PAGE_SIZE):
    """One semaphore-bounded search GET. Retries with progressive backoff on an
    Akamai rate-limit response (403/429/503); the backoff sleep happens OUTSIDE
    the semaphore so a throttled worker never holds a slot. Propagates after
    _SEARCH_ATTEMPTS so a hard block aborts the source before the pipeline
    overwrites good state (the leg is continue-on-error in CI)."""
    query = [(k, str(v)) for k, v in params] + [("ps", str(offset)), ("psz", str(page_size))]
    guard = sem if sem is not None else _AsyncNull()
    for attempt in range(_SEARCH_ATTEMPTS):
        try:
            async with guard:
                await asyncio.sleep(random.uniform(0.1, 0.35))  # politeness jitter
                async with session.get(SEARCH_URL, params=query) as resp:
                    if resp.status in _RATE_LIMIT_STATUSES:
                        raise _RateLimited(_parse_retry_after(resp.headers))
                    resp.raise_for_status()
                    return await resp.json()
        except _RateLimited as rl:
            if attempt == _SEARCH_ATTEMPTS - 1:
                raise
            wait = rl.retry_after
            if wait is None:
                wait = _RATE_LIMIT_BACKOFF[min(attempt, len(_RATE_LIMIT_BACKOFF) - 1)]
            await asyncio.sleep(wait + random.random())
        except Exception:
            if attempt == _SEARCH_ATTEMPTS - 1:
                raise
            await asyncio.sleep(1 + random.random())


async def _count(session, params, sem):
    data = await _search(session, params, 0, sem, page_size=1)
    return data.get("numResultsTotal") or 0


async def _fetch_slice(session, params, total, sem):
    """Page one sub-cap query to its end. Pages are serial inside the slice;
    the semaphore (applied per request in _search) bounds cross-slice concurrency."""
    items = []
    for offset in range(0, min(total, RESULT_CAP), PAGE_SIZE):
        data = await _search(session, params, offset, sem)
        batch = data.get("items") or []
        if not batch:
            break
        items.extend(batch)
    return items


async def _fetch_banded(session, params, price_lo, price_hi, sem):
    """Fetch every result by recursively halving the EUR price band while a
    band would hit the 2000-result cap. Boundary duplicates are deduped by
    link in pipeline.run_source. Every request (counts included) goes through
    the semaphore, so the recursive gather fan-out can't burst the endpoint."""
    banded = tuple(params) + (("p", f"{price_lo}:{price_hi}"),)
    total = await _count(session, banded, sem)
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
