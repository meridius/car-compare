"""Unit tests for sauto purchase-validity guard (operating-lease takeovers,
deposit-only prices). Pure, offline, stdlib unittest."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.sources import sauto as S  # noqa: E402


class IsValidPurchaseTest(unittest.TestCase):
    def test_normal_purchase_ok(self):
        # Omoda 5 — real one-time price, no lease markers
        self.assertTrue(S._is_valid_purchase(480000, {}))

    def test_lease_takeover_rejected_by_payment_count(self):
        # Nissan X-Trail operating-lease takeover (12 023 Kč buyout)
        detail = {"price_payment_count": 1, "price_original_compensation": 12022}
        self.assertFalse(S._is_valid_purchase(12023, detail))

    def test_lease_flag_rejects_even_high_price(self):
        self.assertFalse(S._is_valid_purchase(500000, {"price_leasing": 9999}))

    def test_below_floor_rejected(self):
        # Lexus RX 17 009, Dodge Durango 60 500 — deposit-only, no lease flag
        self.assertFalse(S._is_valid_purchase(17009, {}))
        self.assertFalse(S._is_valid_purchase(60500, {}))

    def test_at_floor_ok(self):
        self.assertTrue(S._is_valid_purchase(100000, {}))

    def test_unparseable_price_not_dropped_on_floor(self):
        self.assertTrue(S._is_valid_purchase("", {}))


def _make_item(**overrides):
    item = {
        "id": 210446333,
        "manufacturer_cb": {"name": "Volkswagen", "seo_name": "volkswagen"},
        "model_cb": {"name": "ID.3", "seo_name": "id3"},
        "additional_model_name": "ProPerform 150 kW 58 kWh",
        "price": 480000,
        "tachometer": 30000,
        "in_operation_date": "2002-01-01",
        "manufacturing_date": None,
    }
    item.update(overrides)
    return item


def _make_detail(**overrides):
    detail = {
        "fuel_cb": {"name": "Elektro"},
        "condition_cb": {"name": "Ojeté"},
        "drive_cb": {"name": "Pohon předních kol"},
        "gearbox_cb": {"name": "Automatická"},
        "engine_power": 150,
        "battery_capacity": 58,
        "vehicle_range": 400,
        "in_operation_date": "2022-01-01",
        "manufacturing_date": None,
    }
    detail.update(overrides)
    return detail


class CommonYearRepairTest(unittest.TestCase):
    """End-to-end: a sauto search-index/detail year mismatch (#16) must not
    leak into the built row — Rok výroby comes out corrected."""

    def test_common_repairs_swapped_year(self):
        item = _make_item()
        detail = _make_detail()
        _, _, _, _, year = S._common(item, detail)
        self.assertEqual(year, "2022")

    def test_build_ev_row_has_repaired_year(self):
        item = _make_item()
        detail = _make_detail()
        row = S.build_ev(item, detail)
        self.assertIsNotNone(row)
        self.assertEqual(row["Rok výroby"], "2022")


if __name__ == "__main__":
    unittest.main()
