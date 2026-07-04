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

CARS_PARQUET = os.path.join(ROOT, "site", "data", "cars.parquet")
CARS_META = os.path.join(ROOT, "site", "data", "cars-meta.json")


def setUpModule():
    if not os.path.exists(CARS_PARQUET):
        subprocess.run([sys.executable, os.path.join(ROOT, "build", "build_data.py")],
                       check=True, cwd=ROOT)


def _records(path):
    """Parquet rows as dicts with NaN mapped to None (JSON-record parity)."""
    import pandas as pd
    df = pd.read_parquet(path)
    return [
        {k: (None if (isinstance(v, float) and v != v) else v) for k, v in rec.items()}
        for rec in df.to_dict("records")
    ]


class DataIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cars = _records(CARS_PARQUET)
        cls.ice = [c for c in cls.cars if c.get("Typ") == "Spalovací"]
        cls.ev = [c for c in cls.cars if c.get("Typ") == "Elektrické"]
        cls.assertTrue(cls.ice, "no combustion rows in cars.parquet")

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

    def test_zeme_in_schema(self):
        self.assertIn("Země", CANONICAL_COLS)

    def test_every_row_has_country(self):
        """Country must be populated on every listing — CZ sources backfilled to
        'Česko', mobile.de rows carry their per-listing country."""
        offenders = [c for c in self.cars if not str(c.get("Země") or "").strip()]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows missing Země (e.g. "
                         f"{offenders[0].get('Model auta') if offenders else ''})")

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

    def test_phev_consumption_blank(self):
        """PHEV combined consumption is the misleading official WLTP weighted
        figure (~1 l/100 km) — it must be blank, not stamped onto rows."""
        offenders = [c for c in self.ice
                     if c.get("Hybrid typ") == "PHEV"
                     and c.get("Spotřeba (l/100 km)") not in (None, "")]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} PHEV rows carry consumption (e.g. "
                         f"{offenders[0]['Model auta'] if offenders else ''})")

    def test_engine_volume_plausible(self):
        """No ICE row may carry an implausible displacement (sauto's 14.9 bug)."""
        offenders = []
        for c in self.ice:
            v = c.get("Objem motoru")
            if isinstance(v, (int, float)) and not (0.6 <= v <= 8.0):
                offenders.append(c)
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with implausible Objem motoru "
                         f"(e.g. {offenders[0].get('Objem motoru') if offenders else ''})")

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


class PayloadContractTest(unittest.TestCase):
    """Pins the browser-facing artifact: schema dtypes, meta sidecar, retention."""

    def test_no_int64_columns(self):
        import pyarrow.parquet as pq
        schema = pq.read_schema(CARS_PARQUET)
        offenders = [f.name for f in schema if "int64" in str(f.type)]
        self.assertEqual(offenders, [],
                         f"int64 columns decode to BigInt in hyparquet: {offenders}")

    def test_meta_sidecar_keys(self):
        with open(CARS_META, encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(
            set(meta),
            {"buildDate", "trigger", "sources", "matching", "referenceData", "totalCars"},
        )
        self.assertGreater(meta["totalCars"], 0)

    def test_removed_rows_respect_retention(self):
        """Stamped removed rows must be younger than retention (+grace). Rows
        without a stamp are pre-migration seeds and exempt."""
        from datetime import date, timedelta
        from scrapers.core.merge import REMOVED_RETENTION_DAYS
        cars = _records(CARS_PARQUET)
        cutoff = date.today() - timedelta(days=REMOVED_RETENTION_DAYS + 7)
        offenders = []
        for c in cars:
            if c.get("Stav") != "Odstraněno":
                continue
            stamp = c.get("Odstraněno dne")
            if not stamp:
                continue
            try:
                removed_on = date.fromisoformat(str(stamp))
            except ValueError:
                offenders.append(c)
                continue
            if removed_on < cutoff:
                offenders.append(c)
        self.assertEqual(offenders, [],
                         f"{len(offenders)} removed rows older than retention window")


if __name__ == "__main__":
    unittest.main()
