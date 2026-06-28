"""Data-integrity invariants over the built dashboard data (site/data/cars.json).

This is the regression net for task #21: it asserts that the served data stays
internally consistent and that the matcher never relapses into the old
"99.8% matched" over-confidence. Builds cars.json once if missing, then runs
offline in well under a second.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scrapers.core.schema import CANONICAL_COLS  # noqa: E402

CARS_JSON = os.path.join(ROOT, "site", "data", "cars.json")


def setUpModule():
    if not os.path.exists(CARS_JSON):
        subprocess.run([sys.executable, os.path.join(ROOT, "build", "build_data.py")],
                       check=True, cwd=ROOT)


class DataIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CARS_JSON, encoding="utf-8") as f:
            cls.cars = json.load(f)["data"]
        cls.ice = [c for c in cls.cars if c.get("Typ") == "Spalovací"]
        cls.ev = [c for c in cls.cars if c.get("Typ") == "Elektrické"]
        cls.assertTrue(cls.ice, "no combustion rows in cars.json")

    @staticmethod
    def _score(car):
        v = car.get("Skóre shody")
        return v if isinstance(v, (int, float)) else None

    def test_skore_column_in_schema(self):
        self.assertIn("Skóre shody", CANONICAL_COLS)

    def test_sparovano_enum_ice(self):
        bad = {c.get("Spárováno") for c in self.ice} - {"Ano", "Nejisté", "Ne"}
        self.assertFalse(bad, f"unexpected ICE Spárováno values: {bad}")

    def test_sparovano_enum_ev(self):
        # EV has no Nejisté state (prefix-join, not scored).
        bad = {c.get("Spárováno") for c in self.ev} - {"Ano", "Ne"}
        self.assertFalse(bad, f"unexpected EV Spárováno values: {bad}")

    def test_no_confident_match_with_nonpositive_score(self):
        """THE core reliability invariant: a confident 'Ano' must never be a
        coin-flip (score 0) or a contradiction (score < 0)."""
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Ano"
                     and self._score(c) is not None and self._score(c) <= 0]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} 'Ano' rows score <= 0 (e.g. "
                         f"{offenders[0]['Model auta'] if offenders else ''})")

    def test_ne_rows_carry_no_score(self):
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Ne" and self._score(c) is not None]
        self.assertEqual(offenders, [], f"{len(offenders)} 'Ne' rows carry a score")

    def test_nejiste_rows_carry_a_score(self):
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Nejisté" and self._score(c) is None]
        self.assertEqual(offenders, [], f"{len(offenders)} 'Nejisté' rows missing score")

    def test_match_rate_is_honest_not_vanity(self):
        """Guard against regression to the old over-confident matcher: uncertainty
        must be surfaced, and the confident rate must be a realistic fraction."""
        n = len(self.ice)
        ano = sum(1 for c in self.ice if c.get("Spárováno") == "Ano")
        nej = sum(1 for c in self.ice if c.get("Spárováno") == "Nejisté")
        self.assertGreaterEqual(nej, 1, "no Nejisté rows — uncertainty not surfaced")
        self.assertLess(ano / n, 0.95,
                        f"Ano rate {ano/n:.1%} >= 95% looks like the old vanity matcher")
        self.assertGreater(ano / n, 0.30, f"Ano rate {ano/n:.1%} suspiciously low")


if __name__ == "__main__":
    unittest.main()
