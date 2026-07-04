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


if __name__ == "__main__":
    unittest.main()
