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
