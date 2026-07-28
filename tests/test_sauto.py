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


class WreckedConditionTest(unittest.TestCase):
    """build_ice rejects condition == 'Havarované' (wrecked); build_ev must
    mirror that guard — a wrecked MG MG4 leaked into live EV listings because
    it didn't (#21 integrity test test_no_havarovane_ev_rows)."""

    def test_build_ev_drops_wrecked_condition(self):
        item = _make_item()
        detail = _make_detail(condition_cb={"name": "Havarované"})
        self.assertIsNone(S.build_ev(item, detail))

    def test_build_ev_keeps_non_wrecked_condition(self):
        item = _make_item()
        detail = _make_detail(condition_cb={"name": "Ojeté"})
        self.assertIsNotNone(S.build_ev(item, detail))


class InvalidYearTest(unittest.TestCase):
    """#17: a year outside [2000..current+1] is repaired from the other detail
    date field, or the row is dropped when neither field is usable."""

    def test_sentinel_year_repaired_from_manufacturing_date(self):
        # Dacia Bigster example: in_operation_date is the 1900-01-01 sentinel,
        # manufacturing_date carries the real 2026.
        item = _make_item(
            manufacturer_cb={"name": "Dacia", "seo_name": "dacia"},
            model_cb={"name": "Bigster", "seo_name": "bigster"},
            additional_model_name="1.2 103kW Journey",
            in_operation_date="1900-01-01",
        )
        detail = _make_detail(
            fuel_cb={"name": "Benzín"},
            in_operation_date="1900-01-01",
            manufacturing_date="2026-01-01",
        )
        row = S.build_ice(item, detail)
        self.assertIsNotNone(row)
        self.assertEqual(row["Rok výroby"], "2026")

    def test_unrepairable_year_drops_the_row(self):
        item = _make_item(in_operation_date="1900-01-01")
        detail = _make_detail(in_operation_date="1900-01-01", manufacturing_date=None)
        self.assertIsNone(S.build_ev(item, detail))
        # fuel_cb must be a non-EV/hybrid fuel or build_ice drops it for that
        # reason first — use a plain ICE fuel so the year-drop path is isolated.
        ice_detail = _make_detail(fuel_cb={"name": "Benzín"},
                                   in_operation_date="1900-01-01", manufacturing_date=None)
        self.assertIsNone(S.build_ice(item, ice_detail))


class CylinderCountTest(unittest.TestCase):
    """#24: build_ice populates 'Počet válců' from the detail payload via the
    tolerant scrapers.core.fields.extract_cylinder_count() lookup."""

    def test_build_ice_populates_cylinder_count(self):
        item = _make_item(
            manufacturer_cb={"name": "Škoda", "seo_name": "skoda"},
            model_cb={"name": "Octavia", "seo_name": "octavia"},
            additional_model_name="1.5 TSI Style",
        )
        detail = _make_detail(fuel_cb={"name": "Benzín"}, engine_cylinders=4)
        row = S.build_ice(item, detail)
        self.assertIsNotNone(row)
        self.assertEqual(row["Počet válců"], "4")

    def test_build_ice_leaves_cylinder_count_blank_when_absent(self):
        # Current sauto detail payloads don't document a cylinder field at all
        # (docs/sauto-api-fields.md) — must stay blank, never invented.
        item = _make_item(
            manufacturer_cb={"name": "Škoda", "seo_name": "skoda"},
            model_cb={"name": "Octavia", "seo_name": "octavia"},
            additional_model_name="1.5 TSI Style",
        )
        detail = _make_detail(fuel_cb={"name": "Benzín"})
        row = S.build_ice(item, detail)
        self.assertIsNotNone(row)
        self.assertEqual(row["Počet válců"], "")


if __name__ == "__main__":
    unittest.main()


class IceBodyFilterTest(unittest.TestCase):
    """sauto's typ_seo must request every passenger body we display, or a whole body
    class is silently absent from the dataset (sedans + liftbacks were, until
    core/bodies.py made Liftback a first-class value)."""

    def test_typ_seo_requests_liftback_and_sedan(self):
        typ = S.ICE_PARAMS["typ_seo"].split(",")
        self.assertIn("liftback", typ)
        self.assertIn("sedanlimuzina", typ)

    def test_typ_seo_values_are_unique_and_nonempty(self):
        typ = S.ICE_PARAMS["typ_seo"].split(",")
        self.assertEqual(sorted(typ), sorted(set(typ)))
        self.assertTrue(all(t.strip() for t in typ))
