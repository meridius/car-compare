"""Offline tests for the mobile.de adapter (fixtures captured from live probes 2026-07-04)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.core.normalize import normalize_model


class BrandNormalizationTest(unittest.TestCase):
    def test_mobilede_diacritics_restored(self):
        self.assertEqual(normalize_model("Skoda Scala"), "Škoda Scala")
        self.assertEqual(normalize_model("Citroen C4"), "Citroën C4")

    def test_existing_vw_alias_unaffected(self):
        self.assertEqual(normalize_model("Volkswagen Golf"), "VW Golf")


from scrapers.sources import mobilede


class ParserTest(unittest.TestCase):
    def test_parse_number_german_formats(self):
        self.assertEqual(mobilede._parse_number("29.000 km"), 29000)
        self.assertEqual(mobilede._parse_number("110 kW (150 PS)"), 110)
        self.assertEqual(mobilede._parse_number("1.499 cm³"), 1499)
        self.assertEqual(mobilede._parse_number("27 kWh"), 27)
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


EV_ITEM = {
    "id": 430897181,
    "url": "https://suchen.mobile.de/auto-inserat/dacia-spring-comfort-plus-electric-27kwh-beroun/430897181.html",
    "shortTitle": "Dacia Spring", "subTitle": "Comfort Plus Electric 27kWh 12/21",
    "make": {"id": "6600", "localized": "Dacia"}, "model": {"id": "25", "localized": "Spring"},
    "price": {"grs": {"amount": 9600.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "CZ", "loc": "Beroun", "fr": "12/2021", "pw": "33 kW (45 PS)",
             "ft": "Elektro", "ml": "52.610 km", "door": "4/5", "sc": "4",
             "bc": "27 kWh", "c": "SmallCar"},
}

ICE_ITEM = {
    "id": 457900286,
    "url": "https://suchen.mobile.de/auto-inserat/skoda-scala-1-5tsi-110kw-dsg-clever-1-2022-beroun/457900286.html",
    "shortTitle": "Skoda Scala", "subTitle": "1.5TSI 110KW DSG Clever 1/2022",
    "make": {"id": "22900", "localized": "Skoda"}, "model": {"id": "9", "localized": "Scala"},
    "price": {"grs": {"amount": 18200.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "CZ", "loc": "Beroun", "fr": "01/2022", "pw": "110 kW (150 PS)",
             "ft": "Benzin", "ml": "90.067 km", "cc": "1.498 cm³",
             "tr": "Automatik", "door": "4/5", "sc": "5", "c": "EstateCar"},
}

HYBRID_ITEM = {
    "id": 12345,
    "url": "https://suchen.mobile.de/auto-inserat/hyundai-tucson/12345.html",
    "shortTitle": "Hyundai TUCSON", "subTitle": "Tucson 1.6 T-GDi HEV 48V Hybrid 4x4",
    "make": {"id": "11600", "localized": "Hyundai"}, "model": {"id": "5", "localized": "Tucson"},
    "price": {"grs": {"amount": 10800.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "CZ", "loc": "Praha", "fr": "03/2022", "pw": "132 kW (180 PS)",
             "ft": "Hybrid (Benzin/Elektro)", "ml": "40.000 km", "cc": "1.598 cm³",
             "tr": "Automatik", "c": "OffRoad", "gi": "03/2027"},
}


# mobile.de returns "Limousine" (attr.c) for hatchbacks and EVs too, not just
# sedans — an ambiguous, frequently-wrong body. It must map to blank so the
# reference / majority-vote / derive_body downstream fills it (see design doc).
LIMOUSINE_ITEM = {
    "id": 458546443,
    "url": "https://suchen.mobile.de/auto-inserat/bmw-118i-sport-line-krakow/458546443.html",
    "shortTitle": "BMW 118", "subTitle": "118i Sport Line 1/2022",
    "make": {"id": "3500", "localized": "BMW"}, "model": {"id": "1", "localized": "118"},
    "price": {"grs": {"amount": 18000.0, "currency": "EUR"}, "type": "FIXED"},
    "attr": {"cn": "PL", "loc": "Kraków", "fr": "01/2022", "pw": "100 kW (136 PS)",
             "ft": "Benzin", "ml": "42.000 km", "cc": "1.499 cm³",
             "tr": "Automatik", "door": "4/5", "sc": "5", "c": "Limousine"},
}


class BuildRowTest(unittest.TestCase):
    def test_limousine_category_maps_to_blank(self):
        # "Limousine" is ambiguous on mobile.de (sedan/hatch/EV) — blank it so
        # downstream reference/majority-vote fills the body, not a wrong "Sedan".
        row = mobilede._build_row(LIMOUSINE_ITEM, 25.0)
        self.assertEqual(row["Karoserie"], "")

    def test_limousine_title_body_token_still_recovered(self):
        # blank map falls through to extract_body_type — a real token in the
        # title (Sportback/Combi/…) is still recovered, only "Limousine" is dropped.
        item = {**LIMOUSINE_ITEM, "subTitle": "Sportback 118i Sport Line 1/2022"}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Karoserie"], "Sportback")

    def test_ev_row(self):
        row = mobilede._build_row(EV_ITEM, 25.0)
        self.assertEqual(row["Typ"], "Elektrické")
        self.assertEqual(row["Palivo"], "Elektro")
        self.assertEqual(row["Model auta"], "Dacia Spring")
        self.assertEqual(row["Cena (Kč)"], 240000)
        self.assertEqual(row["Nájezd (km)"], 52610)
        self.assertEqual(row["Rok výroby"], "2021")
        # sanitize_ev_power (same guard sauto's build_ev applies) returns a
        # string, same contract as everywhere else it's used.
        self.assertEqual(row["Výkon (kW)"], "33")
        self.assertEqual(row["Karoserie"], "Hatchback")
        self.assertIn("Baterie 27 kWh", row["Extra"])
        self.assertIn("Beroun", row["Extra"])
        self.assertNotIn("CZ", row["Extra"])  # country moved to its own column
        self.assertEqual(row["Země"], "Česko")
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
        # subtitle carries "48V" → 48V mild-hybrid architecture (MHEV), which
        # wins over the loose dealer "HEV"/"Hybrid" wording in the same string.
        self.assertEqual(row["Hybrid typ"], "MHEV")
        self.assertEqual(row["Náhon 4x4"], "Ano")
        self.assertEqual(row["Záruka"], "Ano")

    def test_tokenless_hybrid_gets_blank_type(self):
        # Hybrid fuel type but NO hybrid token in the subtitle: we can't tell
        # MHEV/HEV/PHEV apart, so Hybrid typ stays blank (was a wrong HEV
        # default that fabricated full-hybrid variants). Palivo still reflects
        # the hybrid's combustion side. See gotchas → German "Hybrid" fabricate.
        item = {**HYBRID_ITEM, "subTitle": "200 d Progressive Automatik 1/2022"}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Palivo"], "Benzín")
        self.assertEqual(row["Hybrid typ"], "")

    def test_diesel_hybrid_tokenless_blank(self):
        item = {**HYBRID_ITEM,
                "attr": {**HYBRID_ITEM["attr"], "ft": "Hybrid (Diesel/Elektro)"},
                "subTitle": "220 d 4MATIC AMG Line 1/2022"}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Palivo"], "Nafta")
        self.assertEqual(row["Hybrid typ"], "")

    def test_country_mapped_from_cn(self):
        de = {**ICE_ITEM, "attr": {**ICE_ITEM["attr"], "cn": "DE", "loc": "Köln"}}
        self.assertEqual(mobilede._build_row(de, 25.0)["Země"], "Německo")
        for code, name in [("SK", "Slovensko"), ("AT", "Rakousko"), ("PL", "Polsko")]:
            item = {**ICE_ITEM, "attr": {**ICE_ITEM["attr"], "cn": code}}
            self.assertEqual(mobilede._build_row(item, 25.0)["Země"], name)
        # unknown code falls through as-is, never silently dropped
        unk = {**ICE_ITEM, "attr": {**ICE_ITEM["attr"], "cn": "XX"}}
        self.assertEqual(mobilede._build_row(unk, 25.0)["Země"], "XX")

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

    def test_ev_implausible_zero_power_blanked(self):
        """Real data: ~10 Mobile.de EV rows (Dacia Spring, Hyundai Kona Elektro,
        Opel Mokka/-e) carry an explicit 'pw': '0 kW' — sauto has an equivalent
        guard (sanitize_ev_power) that build_row never applied here. Blank beats
        a wrong number."""
        item = {**EV_ITEM, "attr": {**EV_ITEM["attr"], "pw": "0 kW"}}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Výkon (kW)"], "")

    def test_ice_power_untouched_by_ev_sanitizer(self):
        """The EV power floor must not blank a legitimate low-but-real ICE
        value — sanitize_ev_power only applies to the EV branch."""
        item = {**ICE_ITEM, "attr": {**ICE_ITEM["attr"], "pw": "0 kW"}}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Výkon (kW)"], 0)


class AndereRecoveryTest(unittest.TestCase):
    """mobile.de "Andere" junk-model bucket → real name recovered from
    subTitle / shortTitle (fixtures captured from live probes 2026-07-12).
    Never emit an "X Andere" reference row — see docs/gotchas.md."""

    def rec(self, make, model, short, sub):
        return mobilede._recover_andere_model(make, model, short, sub)[0]

    def test_known_make_model_from_subtitle_first_token(self):
        self.assertEqual(
            self.rec("JAC", "Andere", "JAC Andere",
                     "JS8 PRO UNFALL NUR 157 KM TÜV 11.2028 7 SITZE"),
            "JAC JS8")
        self.assertEqual(
            self.rec("Seat", "Andere", "Seat Andere",
                     "Tarraco *LED*Virtual*Erstbesitz"),
            "Seat Tarraco")
        self.assertEqual(
            self.rec("Opel", "Andere", "Opel Andere",
                     "Crossland 1.2 Edition s&s 83cv"),
            "Opel Crossland")
        self.assertEqual(
            self.rec("Smart", "Andere", "Smart Andere", "ForTwo Coupé Passion"),
            "Smart ForTwo")

    def test_all_caps_model_token_titlecased(self):
        self.assertEqual(
            self.rec("Elaris", "Andere", "Elaris Andere", "PIO Other BEV"),
            "Elaris Pio")

    def test_make_andere_recovered_from_short_title(self):
        self.assertEqual(
            self.rec("Andere", "Andere",
                     "Andere BMW iX xdrive40 Edition Signature", ""),
            "BMW iX")
        self.assertEqual(
            self.rec("Andere", "Andere",
                     "Andere Elaris Beo / Vollelektrisch / sofort Verfügbar", ""),
            "Elaris Beo")

    def test_make_andere_all_caps_brand_titlecased(self):
        # "CITROEN" must fold to "Citroen" so BRAND_MAP can restore "Citroën";
        # short all-caps brands (BMW, GWM) stay untouched.
        self.assertEqual(
            self.rec("Andere", "Andere",
                     "Andere CITROEN C3 PureTech 83 S&S You", ""),
            "Citroen C3")
        self.assertEqual(
            self.rec("Andere", "Andere", "Andere BMW iX xdrive40", ""),
            "BMW iX")

    def test_plus_separated_subtitle(self):
        self.assertEqual(
            self.rec("Elaris", "Andere", "Elaris Andere",
                     "Pio+AS-Reifen+Garantie+Guter Zustand+RFK+Ladekab"),
            "Elaris Pio")

    def test_curated_elaris_skywell_alias(self):
        # Elaris Beo is the rebadged Skywell ET5 — dealers list the donor name.
        self.assertEqual(
            self.rec("Elaris", "Andere", "Elaris Andere",
                     "Skywell ET5/72KW Batterie/ nur 3.950KM/GARANTIE"),
            "Elaris Beo")

    def test_junk_or_empty_subtitle_unrecoverable(self):
        self.assertEqual(
            self.rec("Microcar", "Andere", "Microcar Andere",
                     "Elektro 25km/h ab 15 Jahren/ ab 99€ Monatlich"),
            "")
        self.assertEqual(
            self.rec("BAW", "Andere", "BAW Andere",
                     "Aus dem BAW , der neue FAW T 77 Pro"),
            "")
        self.assertEqual(self.rec("GWM", "Andere", "GWM Andere", ""), "")
        # decimals / bare short numbers are engine tokens, not model names
        self.assertEqual(
            self.rec("Kia", "Andere", "Kia Andere", "1.6 CRDi Vision"), "")
        # single-char opener is too ambiguous to be a model name
        self.assertEqual(
            self.rec("DFSK", "Andere", "DFSK Andere",
                     "C 35 * Klimaanlage  - 11.000KM *"),
            "")

    def test_recovered_token_stripped_from_subtitle(self):
        name, rest = mobilede._recover_andere_model(
            "Seat", "Andere", "Seat Andere", "Tarraco *LED*Virtual*")
        self.assertEqual(name, "Seat Tarraco")
        self.assertNotIn("Tarraco", rest)
        self.assertIn("LED", rest)

    def test_non_andere_untouched(self):
        name, rest = mobilede._recover_andere_model(
            "Dacia", "Spring", "Dacia Spring", "Comfort Plus")
        self.assertEqual(name, "")
        self.assertEqual(rest, "Comfort Plus")

    def test_build_row_recovers_ev_andere(self):
        item = {**EV_ITEM,
                "make": {"id": "1", "localized": "Elaris"},
                "model": {"id": "2", "localized": "Andere"},
                "shortTitle": "Elaris Andere", "subTitle": "PIO Other BEV"}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Model auta"], "Elaris Pio")

    def test_build_row_recovery_feeds_normalize(self):
        # "Cee'd" recovered from subTitle must still hit MODEL_CLEANUP_PATTERNS
        item = {**ICE_ITEM,
                "make": {"id": "1", "localized": "Kia"},
                "model": {"id": "2", "localized": "Andere"},
                "shortTitle": "Kia Andere", "subTitle": "Cee'd SW Gold"}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Model auta"], "Kia Ceed")

    def test_build_row_unrecoverable_keeps_andere(self):
        item = {**EV_ITEM,
                "make": {"id": "1", "localized": "GWM"},
                "model": {"id": "2", "localized": "Andere"},
                "shortTitle": "GWM Andere", "subTitle": ""}
        row = mobilede._build_row(item, 25.0)
        self.assertEqual(row["Model auta"], "GWM Andere")


class FetchBandedTest(unittest.TestCase):
    """Price-band splitter: split while >= RESULT_CAP, fetch when under."""

    def _run(self, counts):
        """counts: {(lo, hi): total}. Fake _count/_fetch_slice; items = one dict per result."""
        fetched = []

        async def fake_count(session, params, sem):
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


class _FakeResp:
    def __init__(self, status, json_data=None, headers=None):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=mock.Mock(), history=(), status=self.status)

    async def json(self):
        return self._json


class _FakeGetCtx:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Yields the queued responses in order; the last one repeats."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, params=None):
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return _FakeGetCtx(resp)


class SearchBackoffTest(unittest.TestCase):
    """_search must ride out Akamai rate-limit (403/429/503) responses with
    progressive backoff, and give up only after _SEARCH_ATTEMPTS."""

    def _run(self, responses):
        sem = asyncio.Semaphore(mobilede.CONCURRENCY)
        session = _FakeSession(responses)
        slept = []

        async def fake_sleep(secs):
            slept.append(secs)

        async def drive():
            return await mobilede._search(session, (), 0, sem)

        with mock.patch.object(mobilede.asyncio, "sleep", fake_sleep):
            result = asyncio.run(drive())
        return result, session.calls, slept

    def test_recovers_after_rate_limit(self):
        # two 403s then a 200 → returns the payload, after backoff sleeps
        responses = [_FakeResp(403), _FakeResp(403),
                     _FakeResp(200, {"numResultsTotal": 5, "items": []})]
        result, calls, slept = self._run(responses)
        self.assertEqual(result["numResultsTotal"], 5)
        self.assertEqual(calls, 3)
        # backoff waits (>= first two schedule entries) were used, not just jitter
        big = [s for s in slept if s >= mobilede._RATE_LIMIT_BACKOFF[0]]
        self.assertGreaterEqual(len(big), 2)

    def test_persistent_rate_limit_raises(self):
        responses = [_FakeResp(403)]  # always 403
        with self.assertRaises(mobilede._RateLimited):
            self._run(responses)

    def test_honours_numeric_retry_after(self):
        responses = [_FakeResp(429, headers={"Retry-After": "7"}),
                     _FakeResp(200, {"numResultsTotal": 1, "items": []})]
        _, _, slept = self._run(responses)
        self.assertTrue(any(7 <= s < 9 for s in slept),
                        f"Retry-After not honoured; sleeps={slept}")

    def test_non_rate_error_also_retried(self):
        # a 500 is retried on the generic path, then succeeds
        responses = [_FakeResp(500), _FakeResp(200, {"numResultsTotal": 2, "items": []})]
        result, calls, _ = self._run(responses)
        self.assertEqual(result["numResultsTotal"], 2)
        self.assertEqual(calls, 2)


class RetryAfterParseTest(unittest.TestCase):
    def test_numeric(self):
        self.assertEqual(mobilede._parse_retry_after({"Retry-After": "12"}), 12.0)

    def test_missing(self):
        self.assertIsNone(mobilede._parse_retry_after({}))

    def test_http_date_ignored(self):
        self.assertIsNone(mobilede._parse_retry_after({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))


class CnbRateTest(unittest.TestCase):
    def test_parse_cnb_line(self):
        text = ("04.07.2026 #128\nzemě|měna|množství|kód|kurz\n"
                "Austrálie|dolar|1|AUD|14,505\nEMU|euro|1|EUR|24,745\n")
        self.assertEqual(mobilede._rate_from_cnb_text(text), 24.745)

    def test_parse_cnb_garbage_returns_none(self):
        self.assertIsNone(mobilede._rate_from_cnb_text("<html>outage</html>"))


if __name__ == "__main__":
    unittest.main()


class CategoryMapTest(unittest.TestCase):
    """_CATEGORY_MAP only translates mobile.de's own taxonomy — the fold lives in
    core/bodies.py. So every value it emits must be a label that fold knows,
    otherwise the label reaches the payload unfolded (that is how "Allspace" and
    "VAN" style strays used to leak into the grid's body filter)."""

    def test_every_category_value_is_a_known_body_label(self):
        from scrapers.core import bodies
        for token, value in mobilede._CATEGORY_MAP.items():
            if value == "":
                continue
            self.assertIn(bodies.to_display(value), bodies.CANONICAL,
                          f"{token} -> {value!r} is not a body core/bodies.py knows")

    def test_limousine_and_othercar_still_blank(self):
        self.assertEqual(mobilede._CATEGORY_MAP["Limousine"], "")
        self.assertEqual(mobilede._CATEGORY_MAP["OtherCar"], "")

    def test_cabrio_does_not_become_a_coupe(self):
        from scrapers.core import bodies
        self.assertEqual(bodies.to_display(mobilede._CATEGORY_MAP["Cabrio"]),
                         "Kabriolet")
