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


if __name__ == "__main__":
    unittest.main()
