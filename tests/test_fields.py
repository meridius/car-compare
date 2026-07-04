"""Unit tests for Phase-1 data-quality guards in scrapers/core/fields.py.

Pure, offline, stdlib unittest. Pins the engine-volume sanity guard, the EV
power floor, the EV-suffix dedup, and the hp-shorthand stripping in clean_extra.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.core import fields as F  # noqa: E402


class SanitizeEngineVolumeTest(unittest.TestCase):
    def test_plausible_passes_through(self):
        self.assertEqual(F.sanitize_engine_volume("1.5"), "1.5")
        self.assertEqual(F.sanitize_engine_volume("2.0"), "2.0")
        self.assertEqual(F.sanitize_engine_volume(1.5), "1.5")

    def test_implausible_recovered_from_model_name(self):
        # sauto's bad 14.9 for a Kia XCeed (real 1.5)
        self.assertEqual(
            F.sanitize_engine_volume("14.9", "Kia XCeed 1.5 T-GDI (Crossover)"),
            "1.5",
        )
        # KGM Korando 14 -> 1.5 from the name
        self.assertEqual(
            F.sanitize_engine_volume("14", "KGM Korando 1.5 GDI-T 2WD"),
            "1.5",
        )

    def test_implausible_without_recovery_is_blank(self):
        self.assertEqual(F.sanitize_engine_volume("14.9", "Kia XCeed T-GDI"), "")
        self.assertEqual(F.sanitize_engine_volume("0.1"), "")

    def test_empty_stays_empty(self):
        self.assertEqual(F.sanitize_engine_volume(""), "")
        self.assertEqual(F.sanitize_engine_volume(None), "")


class SanitizeEvPowerTest(unittest.TestCase):
    def test_plausible_passes_through(self):
        self.assertEqual(F.sanitize_ev_power(115), "115")
        self.assertEqual(F.sanitize_ev_power("65"), "65")

    def test_implausibly_low_is_blank(self):
        # sauto's bad 11 kW for a BYD Dolphin Surf
        self.assertEqual(F.sanitize_ev_power(11), "")
        self.assertEqual(F.sanitize_ev_power("0"), "")

    def test_empty_stays_empty(self):
        self.assertEqual(F.sanitize_ev_power(""), "")
        self.assertEqual(F.sanitize_ev_power(None), "")


class CleanEvSuffixTest(unittest.TestCase):
    def test_strips_model_dup_and_hp_shorthand(self):
        # "BYD Dolphin Surf 156k COMFORT" duplicates the model + hp shorthand
        self.assertEqual(
            F.clean_ev_suffix("BYD Dolphin Surf 156k COMFORT", "BYD Dolphin Surf"),
            "COMFORT",
        )

    def test_keeps_non_duplicate_text(self):
        self.assertEqual(F.clean_ev_suffix("Long Range AWD", "Tesla Model 3"), "Long Range AWD")

    def test_does_not_touch_kwh(self):
        # hp-shorthand stripping must not eat a battery "43 kWh"
        self.assertIn("kWh", F.clean_ev_suffix("Boost 43 kWh", "BYD Dolphin Surf"))


class CleanExtraHpShorthandTest(unittest.TestCase):
    def test_strips_hp_shorthand(self):
        out = F.clean_extra("Ibrida 145k e", {})
        self.assertNotIn("145k", out)


class RepairYearTest(unittest.TestCase):
    """Pins the sauto 2-digit-year-swap repair (#16): the search-index year can
    drift from the freshly-fetched detail's own date fields."""

    def test_mismatch_repaired_from_in_operation_date(self):
        # VW ID.3 example: search index says 2002, detail's in_operation_date says 2022.
        self.assertEqual(
            F.repair_year("2002", "2022-01-01", None, 2026), "2022",
        )

    def test_century_swap_repaired(self):
        # 19XX/20XX mixup falls out of the same "trust the detail fields" rule.
        self.assertEqual(
            F.repair_year("1998", "2018-06-01", None, 2026), "2018",
        )

    def test_falls_back_to_manufacturing_date(self):
        self.assertEqual(
            F.repair_year("2002", None, "2022-03-01", 2026), "2022",
        )

    def test_agreement_is_left_unchanged(self):
        self.assertEqual(
            F.repair_year("2022", "2022-01-01", None, 2026), "2022",
        )

    def test_no_candidate_keeps_original(self):
        self.assertEqual(F.repair_year("2022", None, None, 2026), "2022")
        self.assertEqual(F.repair_year("", None, None, 2026), "")

    def test_blank_year_filled_from_candidate(self):
        self.assertEqual(F.repair_year("", "2022-01-01", None, 2026), "2022")


if __name__ == "__main__":
    unittest.main()
