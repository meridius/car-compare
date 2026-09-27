"""Golden tests for scrapers/core/storage.py — parquet state files with CSV seed fallback.

State files are stringly-typed: every column str, blanks "" (never NaN/"nan").
This mirrors the old `pd.read_csv(dtype=str).fillna("")` semantics exactly.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_old_vybava_parquet_column_reads_back_as_verze(self):
        """Verze column plumbing: old state parquet still carries 'Výbava' —
        read_state must rename it transparently so every consumer (pipeline
        merge, build_data) only ever sees 'Verze'."""
        old = _df([["m", "1", "https://x/1", "Style"]],
                  cols=("Model auta", "Cena (Kč)", "Odkaz na auto", "Výbava"))
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            storage.write_state(old, base)
            back = storage.read_state(base)
        self.assertNotIn("Výbava", back.columns)
        self.assertIn("Verze", back.columns)
        self.assertEqual(back.iloc[0]["Verze"], "Style")

    def test_old_vybava_seed_csv_column_reads_back_as_verze(self):
        old = _df([["m", "1", "https://x/1", "Style"]],
                  cols=("Model auta", "Cena (Kč)", "Odkaz na auto", "Výbava"))
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            old.to_csv(base.with_suffix(".csv"), index=False)
            back = storage.read_state(base)
        self.assertNotIn("Výbava", back.columns)
        self.assertEqual(back.iloc[0]["Verze"], "Style")

    def test_new_state_already_named_verze_is_left_alone(self):
        """If a state file already has 'Verze' (post-rename scrape), the rename
        must be a no-op — never overwrite real Verze data with a stray legacy
        'Výbava' column that happens to also be present."""
        df = pd.DataFrame([{"Model auta": "m", "Verze": "Fresh", "Výbava": "Stale"}])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "s"
            storage.write_state(df, base)
            back = storage.read_state(base)
        self.assertEqual(back.iloc[0]["Verze"], "Fresh")


class StateDirOverrideTest(unittest.TestCase):
    """CAR_COMPARE_STATE_DIR moves live state out of the clone (NAS runs reset the
    clone to origin/main each day; state must survive that)."""

    def test_default_is_repo_scrapes_dir(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(storage.STATE_DIR_ENV, None)
            self.assertEqual(storage.state_dir(),
                             Path(storage.__file__).resolve().parent.parent / "data" / "scrapes")

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {storage.STATE_DIR_ENV: td}):
            self.assertEqual(storage.state_dir(), Path(td))

    def test_pipeline_writes_to_override(self):
        from scrapers.core import pipeline
        from scrapers.core.schema import blank_row

        class _StubSource:
            SOURCE_SLUG = "stub"

            @staticmethod
            async def scrape():
                r = blank_row()
                r.update({"Typ": "Elektrické", "Model auta": "BMW i4",
                          "Odkaz na auto": "https://x/1", "Stav": "Dostupný"})
                return [r]

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {storage.STATE_DIR_ENV: td}):
            out = pipeline.run_source(_StubSource)
            self.assertEqual(out, Path(td) / "stub.parquet")
            self.assertTrue(out.exists())

    def test_build_reads_from_override(self):
        from build import build_data
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {storage.STATE_DIR_ENV: td}):
            storage.write_state(_df([["X", "1", "https://x/1"]]), Path(td) / "sauto")
            df = build_data.load_scraper_data()
        self.assertEqual(list(df["Model auta"]), ["X"])


if __name__ == "__main__":
    unittest.main()
