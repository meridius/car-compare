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


class NormalizeAnoNeTest(unittest.TestCase):
    """Pins normalize_ano_ne() behavior: case-insensitive + whitespace stripping."""

    def test_ano_variations_normalize_to_proper_case(self):
        self.assertEqual(F.normalize_ano_ne("ano"), "Ano")
        self.assertEqual(F.normalize_ano_ne("ANO"), "Ano")
        self.assertEqual(F.normalize_ano_ne("Ano"), "Ano")
        self.assertEqual(F.normalize_ano_ne("Ano "), "Ano")
        self.assertEqual(F.normalize_ano_ne(" Ano"), "Ano")
        self.assertEqual(F.normalize_ano_ne(" ANO "), "Ano")

    def test_ne_variations_normalize_to_proper_case(self):
        self.assertEqual(F.normalize_ano_ne("ne"), "Ne")
        self.assertEqual(F.normalize_ano_ne("NE"), "Ne")
        self.assertEqual(F.normalize_ano_ne("Ne"), "Ne")
        self.assertEqual(F.normalize_ano_ne("Ne "), "Ne")
        self.assertEqual(F.normalize_ano_ne(" Ne"), "Ne")
        self.assertEqual(F.normalize_ano_ne(" NE "), "Ne")

    def test_blank_stays_blank(self):
        self.assertEqual(F.normalize_ano_ne(""), "")
        self.assertEqual(F.normalize_ano_ne(None), "")
        self.assertEqual(F.normalize_ano_ne("  "), "")

    def test_nan_becomes_blank(self):
        # NaN (float NaN) should become blank, not "nan"
        import math
        self.assertEqual(F.normalize_ano_ne(float('nan')), "")

    def test_other_values_unchanged(self):
        # Nejisté should remain unchanged (tri-state for Spárováno)
        self.assertEqual(F.normalize_ano_ne("Nejisté"), "Nejisté")
        # But whitespace should still be stripped
        self.assertEqual(F.normalize_ano_ne(" Nejisté "), "Nejisté")
        # Other state values should pass through
        self.assertEqual(F.normalize_ano_ne("Dostupný"), "Dostupný")
        self.assertEqual(F.normalize_ano_ne("Prodané"), "Prodané")


class RepairYearTest(unittest.TestCase):
    """Pins the sauto 2-digit-year-swap repair (#16): the search-index year can
    drift from the freshly-fetched detail's own date fields."""

    def test_mismatch_repaired_from_in_operation_date(self):
        # VW ID.3 example: search index says 2002, detail's in_operation_date says 2022.
        self.assertEqual(
            F.repair_year("2002", "2022-01-01", None, 2026), "2022",
        )


class ExtractCylinderCountTest(unittest.TestCase):
    """#24: the sauto detail API's exact cylinder-count field name is
    unconfirmed (not documented in docs/sauto-api-fields.md), so the lookup
    probes several plausible keys rather than hard-coding one guess."""

    def test_plain_engine_cylinders_key(self):
        self.assertEqual(F.extract_cylinder_count({"engine_cylinders": 4}), "4")

    def test_alternate_cylinders_key(self):
        self.assertEqual(F.extract_cylinder_count({"cylinders": 6}), "6")

    def test_cylinder_count_key(self):
        self.assertEqual(F.extract_cylinder_count({"cylinder_count": "3"}), "3")

    def test_coded_cb_object_form(self):
        # Mirrors the *_cb.{name,value} shape used by other sauto detail fields.
        self.assertEqual(F.extract_cylinder_count({"cylinders_cb": {"value": 8}}), "8")

    def test_missing_field_is_blank(self):
        self.assertEqual(F.extract_cylinder_count({}), "")
        self.assertEqual(F.extract_cylinder_count(None), "")

    def test_implausible_value_is_blank(self):
        self.assertEqual(F.extract_cylinder_count({"engine_cylinders": 0}), "")
        self.assertEqual(F.extract_cylinder_count({"engine_cylinders": 42}), "")

    def test_unparseable_value_is_blank(self):
        self.assertEqual(F.extract_cylinder_count({"engine_cylinders": "n/a"}), "")

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

    # -- #17: clamp years outside [MIN_VALID_YEAR .. current_year + 1] --------

    def test_sentinel_in_operation_date_falls_back_to_manufacturing_date(self):
        # Dacia Bigster example: in_operation_date is the 1900 sentinel,
        # manufacturing_date carries the real year.
        self.assertEqual(
            F.repair_year("1900", "1900-01-01", "2026-01-01", 2026), "2026",
        )

    def test_out_of_range_year_with_no_candidate_is_unrepairable(self):
        self.assertIsNone(F.repair_year("1900", None, None, 2026))
        self.assertIsNone(F.repair_year("1900", "1900-01-01", "1900-01-01", 2026))

    def test_future_year_beyond_current_plus_one_is_invalid(self):
        self.assertIsNone(F.repair_year("2099", None, None, 2026))
        self.assertEqual(F.repair_year("2099", "2025-01-01", None, 2026), "2025")

    def test_missing_year_with_no_candidate_stays_blank_not_dropped(self):
        # No data at all is not the same as an explicit invalid value — leave
        # it blank, don't signal a row-drop.
        self.assertEqual(F.repair_year("", None, None, 2026), "")

    def test_in_range_year_with_no_candidate_kept(self):
        self.assertEqual(F.repair_year("2023", None, None, 2026), "2023")


class ParseBatteryKwhTest(unittest.TestCase):
    def test_mobilede_format(self):
        self.assertEqual(F.parse_battery_kwh("Gera / Baterie 56 kWh / 55 Essence"), "56")

    def test_sauto_format(self):
        self.assertEqual(F.parse_battery_kwh("Dojezd 310 km / Baterie 43 kWh / COMFORT"), "43")

    def test_case_insensitive_and_spacing(self):
        self.assertEqual(F.parse_battery_kwh("baterie30kwh"), "30")

    def test_absent_blank(self):
        self.assertEqual(F.parse_battery_kwh("LED*KLIMA*ACC"), "")
        self.assertEqual(F.parse_battery_kwh(""), "")

    def test_implausible_blanked(self):
        self.assertEqual(F.parse_battery_kwh("Baterie 5 kWh"), "")     # too small
        self.assertEqual(F.parse_battery_kwh("Baterie 900 kWh"), "")   # too large

    def test_non_string_is_blank(self):
        # Arrow-backed Extra columns feed float NaN / None through .map on the
        # full dataset; the helper must return "" not raise (CI build crash).
        self.assertEqual(F.parse_battery_kwh(float("nan")), "")
        self.assertEqual(F.parse_battery_kwh(None), "")


class ParseEvEditionTest(unittest.TestCase):
    def test_single_keyword(self):
        self.assertEqual(F.parse_ev_edition("Suhl / Baterie 51 kWh / 55 Essence LED"), "Essence")
        self.assertEqual(F.parse_ev_edition("Baterie 30 kWh / ... Active Carplay"), "Active")

    def test_canonical_casing_from_uppercase(self):
        self.assertEqual(F.parse_ev_edition("Baterie 43 kWh / COMFORT"), "Comfort")

    def test_multiword_wins_over_bare_token(self):
        # "First Edition" precedes any bare token in the allow-list order.
        self.assertEqual(F.parse_ev_edition("Škoda Epiq First Edition 55"), "First Edition")

    def test_feature_noise_yields_blank(self):
        self.assertEqual(F.parse_ev_edition("LED*KLIMA*DAB+*ACC*SHZ*PDCh*18\"ALU"), "")

    def test_absent_blank(self):
        self.assertEqual(F.parse_ev_edition(""), "")

    def test_non_string_is_blank(self):
        self.assertEqual(F.parse_ev_edition(float("nan")), "")
        self.assertEqual(F.parse_ev_edition(None), "")


if __name__ == "__main__":
    unittest.main()
