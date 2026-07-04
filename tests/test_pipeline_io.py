"""Pins run_source's persistence: parquet state file, canonical columns, dedup."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from scrapers.core import pipeline
from scrapers.core.schema import CANONICAL_COLS, blank_row


class _StubSource:
    SOURCE_NAME = "Stub"
    SOURCE_SLUG = "stub"

    @staticmethod
    async def scrape():
        a = blank_row()
        a.update({"Typ": "Elektrické", "Model auta": "Tesla Model 3",
                  "Odkaz na auto": "https://x/1", "Stav": "Dostupný"})
        dup = dict(a)
        b = blank_row()
        b.update({"Typ": "Elektrické", "Model auta": "BMW i4",
                  "Odkaz na auto": "https://x/2", "Stav": "Dostupný"})
        return [a, dup, b]


class RunSourceTest(unittest.TestCase):
    def test_writes_parquet_state_with_canonical_cols_and_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pipeline, "SCRAPES_DIR", Path(td)):
                out = pipeline.run_source(_StubSource)
            self.assertEqual(out, Path(td) / "stub.parquet")
            df = pd.read_parquet(out)
        self.assertEqual(list(df.columns), CANONICAL_COLS)
        self.assertEqual(len(df), 2)  # duplicate link dropped
        self.assertEqual(set(df["Odkaz na auto"]), {"https://x/1", "https://x/2"})


if __name__ == "__main__":
    unittest.main()
