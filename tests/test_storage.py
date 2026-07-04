"""Golden tests for scrapers/core/storage.py — parquet state files with CSV seed fallback.

State files are stringly-typed: every column str, blanks "" (never NaN/"nan").
This mirrors the old `pd.read_csv(dtype=str).fillna("")` semantics exactly.
"""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scrapers.core import storage


def _df(rows, cols=("Model auta", "Cena (Kč)", "Odkaz na auto")):
    return pd.DataFrame(rows, columns=list(cols))


class RoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_values_blanks_and_diacritics(self):
        df = _df([
            ["Škoda Enyaq iV 60", "1 190 000", "https://x/1"],
            ["Kia Cee´d", "", "https://x/2"],
        ])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "sauto"
            written = storage.write_state(df, base)
            self.assertEqual(written, base.with_suffix(".parquet"))
            back = storage.read_state(base)
        self.assertEqual(list(back.columns), list(df.columns))
        self.assertEqual(back.iloc[0]["Model auta"], "Škoda Enyaq iV 60")
        self.assertEqual(back.iloc[1]["Cena (Kč)"], "")  # blank stays "", not "nan"
        self.assertTrue(all(isinstance(v, str) for v in back.values.ravel()))

    def test_nan_written_comes_back_as_empty_string(self):
        df = _df([["A", None, "https://x/1"]])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            storage.write_state(df, base)
            back = storage.read_state(base)
        self.assertEqual(back.iloc[0]["Cena (Kč)"], "")

    def test_row_order_preserved(self):
        df = _df([[f"m{i}", str(i), f"https://x/{i}"] for i in range(50)])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            storage.write_state(df, base)
            back = storage.read_state(base)
        self.assertEqual(list(back["Model auta"]), [f"m{i}" for i in range(50)])


class FallbackTest(unittest.TestCase):
    def test_read_prefers_parquet_over_csv(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            _df([["from-csv", "1", "https://x/1"]]).to_csv(base.with_suffix(".csv"), index=False)
            storage.write_state(_df([["from-parquet", "2", "https://x/2"]]), base)
            back = storage.read_state(base)
        self.assertEqual(back.iloc[0]["Model auta"], "from-parquet")

    def test_read_falls_back_to_seed_csv(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            _df([["seeded", "", "https://x/1"]]).to_csv(base.with_suffix(".csv"), index=False)
            back = storage.read_state(base)
        self.assertEqual(back.iloc[0]["Model auta"], "seeded")
        self.assertEqual(back.iloc[0]["Cena (Kč)"], "")  # csv blank → "" too

    def test_read_returns_none_when_neither_exists(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(storage.read_state(Path(td) / "missing"))


class SchemaEvolutionTest(unittest.TestCase):
    """Adding/removing canonical columns must not corrupt old state files."""

    def test_old_state_missing_new_column_reindexes_to_blank(self):
        old = _df([["m", "1", "https://x/1"]])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            storage.write_state(old, base)
            back = storage.read_state(base)
            new_cols = list(old.columns) + ["Odstraněno dne"]
            evolved = back.reindex(columns=new_cols).fillna("")
        self.assertEqual(evolved.iloc[0]["Odstraněno dne"], "")
        self.assertEqual(list(evolved.columns), new_cols)

    def test_dropped_column_disappears_after_reindex(self):
        old = _df([["m", "1", "https://x/1"]])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            storage.write_state(old, base)
            back = storage.read_state(base)
            evolved = back.reindex(columns=["Model auta", "Odkaz na auto"]).fillna("")
        self.assertNotIn("Cena (Kč)", evolved.columns)


if __name__ == "__main__":
    unittest.main()
