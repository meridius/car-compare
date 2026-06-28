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


if __name__ == "__main__":
    unittest.main()
