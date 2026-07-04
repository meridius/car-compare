# mobile.de Source Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mobilede` as the fourth scraper source (EV + ICE + hybrid, CZ/SK/AT/PL + DE-EV-only) writing canonical `scrapers/data/scrapes/mobilede.csv`.

**Architecture:** aiohttp adapter against the keyless mobile.de app JSON endpoint (`https://www.mobile.de/api/s/`, header `X-Mobile-Client: de.mobile.android.app`), recursive price-band slicing under the 2000-results-per-query cap, EUR→CZK via CNB daily fixing. Standard `pipeline.run_source` handles dedup/match/merge/write.

**Tech Stack:** Python 3.12, aiohttp, pandas (existing pipeline), stdlib unittest.

**Spec:** `docs/superpowers/specs/2026-07-04-mobilede-source-design.md` — mapping table and verified param semantics live there.

## Global Constraints

- Canonical 25-column schema (`scrapers/core/schema.py CANONICAL_COLS`); adapters emit exactly these columns via `blank_row()`.
- Czech user-facing strings, English identifiers/comments.
- Broad `except Exception` → safe defaults (`""`, `"Ne"`) in scraping helpers; never raise from field parsing.
- Brand aliases only in `core/normalize.py BRAND_MAP`.
- No new pip dependencies (aiohttp already allowed).
- Filters: `fr=2021:`, `ml=:100000`, price ≤ 750 000 Kč, `sc=4:`, `door=FOUR_OR_FIVE`, `dam=false`, ICE `pw=100:`; fuels include-only `PETROL DIESEL ELECTRICITY HYBRID HYBRID_DIESEL`.
- `./bin/test.sh` green after every task.

---

### Task 1: BRAND_MAP entries for mobile.de spellings

**Files:**
- Modify: `scrapers/core/normalize.py:4-6`
- Test: `tests/test_mobilede.py` (new file, first test class)

**Interfaces:**
- Produces: `normalize_model("Skoda Scala") == "Škoda Scala"`, `normalize_model("Citroen C4") == "Citroën C4"` — Task 3's `_build_row` relies on this.

- [x] **Step 1: Write the failing test**

Create `tests/test_mobilede.py`:

```python
"""Offline tests for the mobile.de adapter (fixtures captured from live probes 2026-07-04)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.core.normalize import normalize_model


class BrandNormalizationTest(unittest.TestCase):
    def test_mobilede_diacritics_restored(self):
        self.assertEqual(normalize_model("Skoda Scala"), "Škoda Scala")
        self.assertEqual(normalize_model("Citroen C4"), "Citroën C4")

    def test_existing_vw_alias_unaffected(self):
        self.assertEqual(normalize_model("Volkswagen Golf"), "VW Golf")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mobilede -v`
Expected: FAIL — `'Skoda Scala' != 'Škoda Scala'`

- [x] **Step 3: Implement**

In `scrapers/core/normalize.py` extend BRAND_MAP:

```python
BRAND_MAP = {
    "Volkswagen": "VW",
    # mobile.de strips diacritics from make names
    "Skoda": "Škoda",
    "Citroen": "Citroën",
}
```

- [x] **Step 4: Run tests**

Run: `./bin/test.sh`
Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add scrapers/core/normalize.py tests/test_mobilede.py
git commit -m "feat(normalize): map mobile.de diacritic-less brand spellings"
```

---

### Task 2: Adapter skeleton — constants, maps, pure parsers

**Files:**
- Create: `scrapers/sources/mobilede.py`
- Test: `tests/test_mobilede.py` (append)

**Interfaces:**
- Produces: `_parse_number(text) -> int|""`, `_year_from_fr(fr) -> str`, `_price_kc(item, rate) -> int|None`, module constants (`_FUEL_MAP`, `_CATEGORY_MAP`, `_TRANSMISSION_MAP`, `SOURCE_NAME="Mobile.de"`, `SOURCE_SLUG="mobilede"`, `FUELS={"EV","ICE"}`). Tasks 3–4 consume all of these.

- [x] **Step 1: Write failing tests** (append to `tests/test_mobilede.py`)

```python
from scrapers.sources import mobilede


class ParserTest(unittest.TestCase):
    def test_parse_number_german_formats(self):
        self.assertEqual(mobilede._parse_number("29.000 km"), 29000)
        self.assertEqual(mobilede._parse_number("110 kW (150 PS)"), 110)
        self.assertEqual(mobilede._parse_number("1.499 cm³"), 1499)
        self.assertEqual(mobilede._parse_number("27 kWh"), 27)
        self.assertEqual(mobilede._parse_number(""), "")
        self.assertEqual(mobilede._parse_number(None), "")

    def test_year_from_fr(self):
        self.assertEqual(mobilede._year_from_fr("02/2022"), "2022")
        self.assertEqual(mobilede._year_from_fr("2021"), "2021")
        self.assertEqual(mobilede._year_from_fr(""), "")

    def test_price_kc_fixed_gross(self):
        item = {"price": {"grs": {"amount": 10000.0}, "type": "FIXED"}}
        self.assertEqual(mobilede._price_kc(item, 25.0), 250000)

    def test_price_kc_rejects_non_fixed_missing_low_high(self):
        self.assertIsNone(mobilede._price_kc({"price": {"type": "LEASING",
                          "grs": {"amount": 10000.0}}}, 25.0))
        self.assertIsNone(mobilede._price_kc({"price": {"type": "FIXED"}}, 25.0))
        self.assertIsNone(mobilede._price_kc({}, 25.0))
        # 3 000 € × 25 = 75 000 Kč < MIN_PRICE_KC backstop
        self.assertIsNone(mobilede._price_kc({"price": {"grs": {"amount": 3000.0},
                          "type": "FIXED"}}, 25.0))
        # 31 000 € × 25 = 775 000 Kč > ceiling
        self.assertIsNone(mobilede._price_kc({"price": {"grs": {"amount": 31000.0},
                          "type": "FIXED"}}, 25.0))
```

- [x] **Step 2: Run** `python3 -m unittest tests.test_mobilede -v` — Expected: FAIL (no module `mobilede`)

- [x] **Step 3: Create `scrapers/sources/mobilede.py`**

```python
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
```

- [x] **Step 4: Run** `./bin/test.sh` — Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add scrapers/sources/mobilede.py tests/test_mobilede.py
git commit -m "feat(mobilede): adapter skeleton — constants, value maps, parsers"
```

---

### Task 3: `_build_row` with captured fixtures

**Files:**
- Modify: `scrapers/sources/mobilede.py` (append)
- Test: `tests/test_mobilede.py` (append)

**Interfaces:**
- Consumes: Task 2 parsers/maps.
- Produces: `_build_row(item: dict, rate: float) -> dict|None` returning a canonical `blank_row()`-based dict. Task 4's `scrape()` consumes it.

- [x] **Step 1: Write failing tests** (append; fixtures are trimmed real API items)

```python
EV_ITEM = {
    "id": 430897181,
    "url": "https://suchen.mobile.de/auto-inserat/dacia-spring-comfort-plus-electric-27kwh-beroun/430897181.html",
    "shortTitle": "Dacia Spring", "subTitle": "Comfort Plus Electric 27kWh 12/21",
    "make": {"id": "6600", "localized": "Dacia"}, "model": {"id": "25", "localized": "Spring"},
    "price": {"grs": {"amount": 9600.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "CZ", "loc": "Beroun", "fr": "12/2021", "pw": "33 kW (45 PS)",
             "ft": "Elektro", "ml": "52.610 km", "door": "4/5", "sc": "4",
             "bc": "27 kWh", "c": "SmallCar"},
}

ICE_ITEM = {
    "id": 457900286,
    "url": "https://suchen.mobile.de/auto-inserat/skoda-scala-1-5tsi-110kw-dsg-clever-1-2022-beroun/457900286.html",
    "shortTitle": "Skoda Scala", "subTitle": "1.5TSI 110KW DSG Clever 1/2022",
    "make": {"id": "22900", "localized": "Skoda"}, "model": {"id": "9", "localized": "Scala"},
    "price": {"grs": {"amount": 18200.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "CZ", "loc": "Beroun", "fr": "01/2022", "pw": "110 kW (150 PS)",
             "ft": "Benzin", "ml": "90.067 km", "cc": "1.498 cm³",
             "tr": "Automatik", "door": "4/5", "sc": "5", "c": "EstateCar"},
}

HYBRID_ITEM = {
    "id": 12345,
    "url": "https://suchen.mobile.de/auto-inserat/hyundai-tucson/12345.html",
    "shortTitle": "Hyundai TUCSON", "subTitle": "Tucson 1.6 T-GDi HEV 48V Hybrid 4x4",
    "make": {"id": "11600", "localized": "Hyundai"}, "model": {"id": "5", "localized": "Tucson"},
    "price": {"grs": {"amount": 10800.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "CZ", "loc": "Praha", "fr": "03/2022", "pw": "132 kW (180 PS)",
             "ft": "Hybrid (Benzin/Elektro)", "ml": "40.000 km", "cc": "1.598 cm³",
             "tr": "Automatik", "c": "OffRoad", "gi": "03/2027"},
}


class BuildRowTest(unittest.TestCase):
    def test_ev_row(self):
        row = mobilede._build_row(EV_ITEM, 25.0)
        self.assertEqual(row["Typ"], "Elektrické")
        self.assertEqual(row["Palivo"], "Elektro")
        self.assertEqual(row["Model auta"], "Dacia Spring")
        self.assertEqual(row["Cena (Kč)"], 240000)
        self.assertEqual(row["Nájezd (km)"], 52610)
        self.assertEqual(row["Rok výroby"], "2021")
        self.assertEqual(row["Výkon (kW)"], 33)
        self.assertEqual(row["Karoserie"], "Hatchback")
        self.assertIn("Baterie 27 kWh", row["Extra"])
        self.assertIn("CZ Beroun", row["Extra"])
        self.assertEqual(row["Zdroj"], "Mobile.de")
        self.assertEqual(row["Odkaz na auto"], EV_ITEM["url"])
        self.assertEqual(row["Tepelné čerpadlo"], "")
        self.assertEqual(row["Stav"], "")

    def test_ice_row(self):
        row = mobilede._build_row(ICE_ITEM, 25.0)
        self.assertEqual(row["Typ"], "Spalovací")
        self.assertEqual(row["Model auta"], "Škoda Scala")
        self.assertEqual(row["Palivo"], "Benzín")
        self.assertEqual(row["Cena (Kč)"], 455000)
        self.assertEqual(row["Objem motoru"], "1.5")
        self.assertEqual(row["Typ motoru"], "TSI")
        self.assertEqual(row["Převodovka"], "Automatická")
        self.assertEqual(row["Dvouspojková převodovka"], "Ano")
        self.assertEqual(row["Karoserie"], "Kombi")

    def test_hybrid_row(self):
        row = mobilede._build_row(HYBRID_ITEM, 25.0)
        self.assertEqual(row["Typ"], "Spalovací")
        self.assertEqual(row["Palivo"], "Benzín")
        self.assertEqual(row["Hybrid typ"], "HEV")
        self.assertEqual(row["Náhon 4x4"], "Ano")
        self.assertEqual(row["Záruka"], "Ano")

    def test_gas_and_unknown_fuels_rejected(self):
        for ft in ("Autogas (LPG)", "Erdgas (CNG)", "Wasserstoff", "Andere", ""):
            item = {**ICE_ITEM, "attr": {**ICE_ITEM["attr"], "ft": ft}}
            self.assertIsNone(mobilede._build_row(item, 25.0), ft)

    def test_missing_link_or_bad_price_rejected(self):
        self.assertIsNone(mobilede._build_row({**ICE_ITEM, "url": ""}, 25.0))
        self.assertIsNone(mobilede._build_row(
            {**ICE_ITEM, "price": {"type": "LEASING"}}, 25.0))

    def test_row_has_canonical_columns_only(self):
        from scrapers.core.schema import CANONICAL_COLS
        row = mobilede._build_row(EV_ITEM, 25.0)
        self.assertEqual(sorted(row.keys()), sorted(CANONICAL_COLS))
```

- [x] **Step 2: Run** `python3 -m unittest tests.test_mobilede.BuildRowTest -v` — Expected: FAIL (`_build_row` missing)

- [x] **Step 3: Implement** (append to `scrapers/sources/mobilede.py`)

```python
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
```

Note: `extract_hybrid_type(sub)` may legitimately return MHEV for `ft="Benzin"` mild hybrids — keep whatever it returns for non-hybrid fts too.

- [x] **Step 4: Run** `./bin/test.sh` — Expected: all PASS. If `test_hybrid_row` fails on `Hybrid typ` (extraction quirk), inspect `extract_hybrid_type("Tucson 1.6 T-GDi HEV 48V Hybrid 4x4")` output and fix the *expected value only if the extractor's answer is defensible* (e.g. MHEV due to "48V") — never weaken the extractor.

- [x] **Step 5: Commit**

```bash
git add scrapers/sources/mobilede.py tests/test_mobilede.py
git commit -m "feat(mobilede): canonical row builder with fixture golden tests"
```

---

### Task 4: Fetching — search, pagination, price-band splitter, CNB rate, scrape()

**Files:**
- Modify: `scrapers/sources/mobilede.py` (append)
- Test: `tests/test_mobilede.py` (append)

**Interfaces:**
- Consumes: `_build_row`, constants from Tasks 2–3.
- Produces: async `scrape() -> list[dict]` (pipeline contract), internals `_search(session, params, offset, page_size)`, `_count(session, params)`, `_fetch_slice(session, params, total, sem)`, `_fetch_banded(session, params, lo, hi, sem)`, `_get_eur_czk_rate(session)`.

- [x] **Step 1: Write failing tests** (append; splitter + CNB parser tested with mocks, no network)

```python
class FetchBandedTest(unittest.TestCase):
    """Price-band splitter: split while >= RESULT_CAP, fetch when under."""

    def _run(self, counts):
        """counts: {(lo, hi): total}. Fake _count/_fetch_slice; items = one dict per result."""
        fetched = []

        async def fake_count(session, params):
            band = dict(params)["p"]
            lo, hi = (int(x) for x in band.split(":"))
            return counts.get((lo, hi), 0)

        async def fake_fetch_slice(session, params, total, sem):
            band = dict(params)["p"]
            fetched.append(band)
            return [{"band": band, "i": i} for i in range(min(total, mobilede.RESULT_CAP))]

        with mock.patch.object(mobilede, "_count", fake_count), \
             mock.patch.object(mobilede, "_fetch_slice", fake_fetch_slice):
            items = asyncio.run(mobilede._fetch_banded(None, (), 0, 30000, None))
        return items, fetched

    def test_small_result_no_split(self):
        items, fetched = self._run({(0, 30000): 150})
        self.assertEqual(len(items), 150)
        self.assertEqual(fetched, ["0:30000"])

    def test_split_over_cap(self):
        counts = {(0, 30000): 3000, (0, 15000): 1800, (15001, 30000): 1200}
        items, fetched = self._run(counts)
        self.assertEqual(len(items), 3000)
        self.assertEqual(sorted(fetched), ["0:15000", "15001:30000"])

    def test_empty_band_skipped(self):
        items, fetched = self._run({(0, 30000): 0})
        self.assertEqual(items, [])
        self.assertEqual(fetched, [])


class CnbRateTest(unittest.TestCase):
    def test_parse_cnb_line(self):
        text = ("04.07.2026 #128\nzemě|měna|množství|kód|kurz\n"
                "Austrálie|dolar|1|AUD|14,505\nEMU|euro|1|EUR|24,745\n")
        self.assertEqual(mobilede._rate_from_cnb_text(text), 24.745)

    def test_parse_cnb_garbage_returns_none(self):
        self.assertIsNone(mobilede._rate_from_cnb_text("<html>outage</html>"))
```

- [x] **Step 2: Run** `python3 -m unittest tests.test_mobilede.FetchBandedTest tests.test_mobilede.CnbRateTest -v` — Expected: FAIL (functions missing)

- [x] **Step 3: Implement** (append to `scrapers/sources/mobilede.py`)

```python
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
```

- [x] **Step 4: Run** `./bin/test.sh` — Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add scrapers/sources/mobilede.py tests/test_mobilede.py
git commit -m "feat(mobilede): paged fetching with 2000-cap price-band splitting + CNB rate"
```

---

### Task 5: Wire the source into runner, build, CI

**Files:**
- Modify: `scrapers/run.py:7` (`SOURCES` list)
- Modify: `bin/run_all.sh:10` (`ALL_SOURCES` array)
- Modify: `build/build_data.py:195` (source name list in `load_scraper_csvs`)
- Modify: `.github/workflows/scrape-and-deploy.yml` (matrix, chromium condition, continue-on-error)

**Interfaces:**
- Consumes: `scrapers/sources/mobilede.py` module contract (`SOURCE_NAME`, `SOURCE_SLUG`, `scrape`).
- Produces: `python -m scrapers.run --source mobilede` runnable; CI leg tolerated on failure.

- [x] **Step 1: Edits**

`scrapers/run.py`: `SOURCES = ["sauto", "autodraft", "energycars", "mobilede"]`

`bin/run_all.sh`: `ALL_SOURCES=(sauto autodraft energycars mobilede)`

`build/build_data.py` `load_scraper_csvs`: `for name in ["sauto", "autodraft", "energycars", "mobilede"]:`

Workflow:
- matrix: `source: [sauto, autodraft, energycars, mobilede]`
- scrape job gains: `continue-on-error: ${{ matrix.source == 'mobilede' }}` (undocumented endpoint must not block the daily build; build then reuses the committed mobilede.csv from checkout because the artifact is simply absent)
- chromium condition `if: matrix.source != 'sauto'` → `if: matrix.source != 'sauto' && matrix.source != 'mobilede'` (both aiohttp-only)

- [x] **Step 2: Verify wiring offline**

Run: `python3 -c "import importlib; m=importlib.import_module('scrapers.sources.mobilede'); print(m.SOURCE_SLUG)"` → `mobilede`
Run: `python3 -m scrapers.run --source nonsense` → argparse error listing mobilede as a choice
Run: `bash -n bin/run_all.sh` → exit 0

- [x] **Step 3: Run** `./bin/test.sh` — Expected: PASS

- [x] **Step 4: Commit**

```bash
git add scrapers/run.py bin/run_all.sh build/build_data.py .github/workflows/scrape-and-deploy.yml
git commit -m "feat(mobilede): wire source into runner, build and CI matrix"
```

---

### Task 6: Env plumbing for the future Search-API key

**Files:**
- Create: `.envrc`
- Create: `var/.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `direnv` loads `var/.env` when present; documented variable names `MOBILEDE_SEARCH_API_USER` / `MOBILEDE_SEARCH_API_PASSWORD` (consumed by nothing yet — the sanctioned Search-API transport is a documented future upgrade, not implemented without credentials).

- [x] **Step 1: Create files**

`.envrc`:
```bash
# Local secrets (gitignored). Loaded by direnv; create var/.env from var/.env.example.
dotenv_if_exists var/.env
```

`var/.env.example`:
```bash
# mobile.de official Search-API credentials (HTTP Basic).
# Granted manually by mobile.de customer support — no self-service signup:
#   https://services.mobile.de/docs/search-api.html
#   contact form: https://www.mobile.de/service/contactForm?subject=API+support+request+GERMANY
# When granted: copy this file to var/.env, fill in, and mirror to GitHub repo
# secrets (gh secret set MOBILEDE_SEARCH_API_USER / MOBILEDE_SEARCH_API_PASSWORD).
# The scraper currently uses the keyless app endpoint and does NOT read these yet.
MOBILEDE_SEARCH_API_USER=
MOBILEDE_SEARCH_API_PASSWORD=
```

`.gitignore` — append:
```text
var/.env
```

- [x] **Step 2: Verify**

Run: `direnv allow && direnv exec . env | grep -c MOBILEDE || true` (no var/.env yet → 0, no error)
Run: `git status --short` must NOT list `var/.env` after `cp var/.env.example var/.env`; then `rm var/.env`.

- [x] **Step 3: Commit**

```bash
git add .envrc var/.env.example .gitignore
git commit -m "chore: env plumbing for future mobile.de Search-API credentials"
```

---

### Task 7: Live verification (network)

**Files:** none (verification only; may adjust constants if live behavior differs)

- [x] **Step 1: Confirm `psz=100` returns 100 items on a big slice**

Run a one-off probe (scratchpad script) against a DE EV band with >100 results; if pages return only 20 items, set `PAGE_SIZE = 20` in `mobilede.py` and note it in gotchas.

- [x] **Step 2: Full scrape**

Run: `python3 -m scrapers.run --source mobilede` (expect ~15k rows, several minutes)
Expected: `Hotovo – uloženo N aut do mobilede.csv`, no traceback.

- [x] **Step 3: Spot-check CSV**

```bash
python3 - <<'EOF'
import pandas as pd
df = pd.read_csv("scrapers/data/scrapes/mobilede.csv")
assert len(df.columns) == 25, df.columns
print(len(df), "rows")
print(df["Typ"].value_counts().to_dict())
print(df["Palivo"].value_counts().to_dict())
print(df["Cena (Kč)"].describe()[["min", "max"]])
print(df["Rok výroby"].value_counts().to_dict())
print(df["Spárováno"].value_counts(dropna=False).to_dict())
print(df.sample(5)[["Model auta", "Cena (Kč)", "Karoserie", "Extra", "Odkaz na auto"]])
EOF
```
Check: prices within [100000, 750000], years ≥ 2021, no LPG/CNG in Palivo, model names diacritics-fixed, Extra carries country tokens.

- [x] **Step 4: Rebuild + tests + UI**

Run: `python3 build/build_data.py && ./bin/test.sh`
Expected: mobilede row count in build output; all tests PASS (match-rate band must hold).
Run: `python3 build/verify_ui.py --page index --scenario grid` then **Read the screenshot** — grid renders with Mobile.de rows present.

- [x] **Step 5: Commit scraped data**

```bash
git add scrapers/data/scrapes/mobilede.csv
git commit -m "data: initial mobile.de scrape"
```

---

### Task 8: Documentation + task bookkeeping

**Files:**
- Modify: `CLAUDE.md` (sources table, run examples source list)
- Modify: `docs/architecture.md` (tree, source-comparison table, filters section)
- Modify: `docs/gotchas.md` (new mobile.de section)
- Modify: `docs/conventions.md` (source name lists in "Running Scrapers")
- Modify: `TASKS.md` (#1 → Done with outcome note)

- [x] **Step 1: Write docs**

gotchas.md mobile.de section must cover: `X-Mobile-Client` header requirement; 2000-result cap + price-band splitting; EUR→CZK CNB conversion (+fallback); DE is EV-only (`ICE_COUNTRIES` constant); robots-disallowed endpoint caveat + official Search-API upgrade path (credentials via support, env vars prepared in `var/.env.example`); German attr-string parsing; `price.type == "FIXED"` guard; Stav always blank (energycars precedent).

- [x] **Step 2: Run** `./bin/test.sh` — PASS (docs only)

- [x] **Step 3: Commit**

```bash
git add CLAUDE.md docs/ TASKS.md
git commit -m "docs: mobile.de source — architecture, gotchas, task #1 done"
```
