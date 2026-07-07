"""The scraper hard-filter constants (scrapers/core/filters.py) are the single
source of truth: the adapters must enforce exactly the thresholds advertised to
the dashboard. These tests fail if an adapter query drifts from the shared
constant, or if the human-readable SOURCE_FILTERS text stops matching the
numbers it is built from.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scrapers.core import filters  # noqa: E402
from scrapers.sources import sauto, mobilede  # noqa: E402


class MileageBumpTest(unittest.TestCase):
    """Family request: raise the mileage ceiling from 100k to 150k km."""

    def test_shared_constant_is_150k(self):
        self.assertEqual(filters.MAX_MILEAGE_KM, 150000)

    def test_sauto_enforces_shared_mileage(self):
        self.assertEqual(sauto._BASE_PARAMS["tachometer_to"], filters.MAX_MILEAGE_KM)

    def test_mobilede_enforces_shared_mileage(self):
        self.assertIn(("ml", f":{filters.MAX_MILEAGE_KM}"), mobilede._BASE_PARAMS)


class AdapterMatchesSharedConstantsTest(unittest.TestCase):
    """Every knob the adapter enforces comes from filters.py — no literals."""

    def test_sauto_base_params(self):
        self.assertEqual(sauto._BASE_PARAMS["price_to"], filters.MAX_PRICE_KC)
        self.assertEqual(sauto._BASE_PARAMS["vehicle_age_from"], filters.MIN_YEAR)
        self.assertEqual(sauto._BASE_PARAMS["capacity_from"], filters.MIN_SEATS)
        self.assertEqual(sauto.MIN_PRICE_KC, filters.MIN_PRICE_KC)

    def test_sauto_ice_power(self):
        self.assertEqual(sauto.ICE_PARAMS["engine_power_from"], filters.MIN_POWER_KW_ICE)

    def test_mobilede_base_params(self):
        self.assertIn(("fr", f"{filters.MIN_YEAR}:"), mobilede._BASE_PARAMS)
        self.assertIn(("sc", f"{filters.MIN_SEATS}:"), mobilede._BASE_PARAMS)
        self.assertEqual(mobilede.PRICE_CEILING_KC, filters.MAX_PRICE_KC)
        self.assertEqual(mobilede.MIN_PRICE_KC, filters.MIN_PRICE_KC)

    def test_mobilede_ice_power(self):
        self.assertIn(("pw", f"{filters.MIN_POWER_KW_ICE}:"), mobilede.ICE_EXTRA)


class SourceFiltersTextTest(unittest.TestCase):
    """The dashboard text is derived from the constants, so it must carry the
    live numbers — pinning it stops a stale hand-edited string from lying."""

    def test_all_four_sources_described(self):
        names = {s["source"] for s in filters.SOURCE_FILTERS}
        self.assertEqual(
            names, {"Sauto.cz", "Mobile.de", "Autodraft.cz", "Energycars.cz"})

    def test_mileage_text_reflects_constant(self):
        # 150000 -> "150 000" (non-breaking space, Czech grouping) appears in
        # every source that has a mileage filter
        pretty = filters._km(filters.MAX_MILEAGE_KM)
        self.assertEqual(pretty, "150 000")
        for s in filters.SOURCE_FILTERS:
            if s["source"] in ("Sauto.cz", "Mobile.de"):
                self.assertTrue(
                    any(f"do {pretty} km" in line for line in s["common"]),
                    f"{s['source']} mileage line missing/stale")

    def test_curated_sources_have_no_numeric_filters(self):
        for s in filters.SOURCE_FILTERS:
            if s["source"] in ("Autodraft.cz", "Energycars.cz"):
                self.assertEqual(s["common"], [])
                self.assertEqual(s["ev"], [])
                self.assertEqual(s["ice"], [])


if __name__ == "__main__":
    unittest.main()
