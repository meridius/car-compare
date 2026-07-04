"""Offline tests for core/normalize.py (no network).

Pins the general "collapse multi-name spellings of the same physical car"
mechanism (BRAND_MAP / MODEL_CLEANUP_PATTERNS), exercised here against the
GWM Ora 03 / ORA Funky Cat rebadge — the same car sold under two names, which
otherwise duplicates rows in ev_specs.csv (see docs/gotchas.md).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.core.normalize import normalize_model  # noqa: E402


class OraFunkyCatAliasTest(unittest.TestCase):
    """GWM Ora 03 == ORA Funky Cat == Ora Good Cat — same physical car, different
    market names. Only this specific same-car-different-spelling pair is in
    scope; badge-engineered-but-distinct cars (e.g. Citigo-e / e-up!) must NOT
    be collapsed by this mechanism."""

    def test_bare_ora_funky_cat_collapses_to_canonical(self):
        self.assertEqual(normalize_model("ORA Funky Cat 48 kWh"), "GWM Ora 03 48 kWh")

    def test_gwm_prefixed_funky_cat_collapses_to_canonical(self):
        self.assertEqual(normalize_model("GWM Ora Funky Cat 48 kWh"), "GWM Ora 03 48 kWh")

    def test_lowercase_variant_collapses(self):
        self.assertEqual(normalize_model("Ora Funky Cat 48 kWh"), "GWM Ora 03 48 kWh")

    def test_already_canonical_name_is_unaffected(self):
        self.assertEqual(normalize_model("GWM Ora 03 48 kWh"), "GWM Ora 03 48 kWh")

    def test_unrelated_model_is_unaffected(self):
        self.assertEqual(normalize_model("Škoda Enyaq 80"), "Škoda Enyaq iV 80")


if __name__ == "__main__":
    unittest.main()
