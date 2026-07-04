"""Golden tests for merge_with_previous: removal stamping + 60-day retention.

State layer semantics:
- a vanished link is kept with Stav="Odstraněno" and stamped "Odstraněno dne"=today
- the stamp is preserved on later merges (not re-stamped)
- rows removed more than REMOVED_RETENTION_DAYS ago are dropped from state
  (they live on in the monthly snapshot releases — see docs/decisions/001)
- a reappearing link takes the fresh row (blank stamp) — new data always wins
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from scrapers.core import storage
from scrapers.core.merge import REMOVED_RETENTION_DAYS, merge_with_previous

COLS = ["Model auta", "Stav", "Odstraněno dne", "Odkaz na auto"]
TODAY = date(2026, 7, 4)


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


def _merge(new_df, prev_df, today=TODAY):
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "src"
        if prev_df is not None:
            storage.write_state(prev_df, base)
        return merge_with_previous(new_df, base, today=today)


class MergeTest(unittest.TestCase):
    def test_no_previous_state_returns_df_unchanged(self):
        new = _df([["A", "Dostupný", "", "https://x/1"]])
        out = _merge(new, None)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["Stav"], "Dostupný")

    def test_vanished_row_stamped_with_today(self):
        prev = _df([["A", "Dostupný", "", "https://x/1"]])
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Stav"], "Odstraněno")
        self.assertEqual(gone["Odstraněno dne"], "2026-07-04")

    def test_existing_stamp_preserved(self):
        prev = _df([["A", "Odstraněno", "2026-05-20", "https://x/1"]])
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Odstraněno dne"], "2026-05-20")

    def test_legacy_removed_row_without_stamp_gets_stamped_today(self):
        prev = _df([["A", "Odstraněno", "", "https://x/1"]])
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Odstraněno dne"], "2026-07-04")

    def test_reappearing_link_takes_fresh_row(self):
        prev = _df([["A old", "Odstraněno", "2026-06-01", "https://x/1"]])
        new = _df([["A new", "Dostupný", "", "https://x/1"]])
        out = _merge(new, prev)
        self.assertEqual(len(out), 1)
        row = out.iloc[0]
        self.assertEqual(row["Model auta"], "A new")
        self.assertEqual(row["Stav"], "Dostupný")
        self.assertEqual(row["Odstraněno dne"], "")

    def test_retention_drops_rows_older_than_cutoff(self):
        old_date = (TODAY - timedelta(days=REMOVED_RETENTION_DAYS + 1)).isoformat()
        edge_date = (TODAY - timedelta(days=REMOVED_RETENTION_DAYS)).isoformat()
        prev = _df([
            ["too-old", "Odstraněno", old_date, "https://x/1"],
            ["edge-keep", "Odstraněno", edge_date, "https://x/2"],
        ])
        new = _df([["B", "Dostupný", "", "https://x/3"]])
        out = _merge(new, prev)
        self.assertNotIn("https://x/1", set(out["Odkaz na auto"]))
        self.assertIn("https://x/2", set(out["Odkaz na auto"]))

    def test_retention_ignores_non_removed_rows(self):
        # a bogus stamp on a live row must not delete it
        prev = _df([["A", "Dostupný", "2020-01-01", "https://x/1"]])
        new = _df([["A", "Dostupný", "", "https://x/1"]])
        out = _merge(new, prev)
        self.assertEqual(len(out), 1)

    def test_unparsable_stamp_is_kept_and_restamped(self):
        prev = _df([["A", "Odstraněno", "garbage", "https://x/1"]])
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Odstraněno dne"], "2026-07-04")

    def test_empty_link_rows_in_previous_are_skipped(self):
        prev = _df([["ghost", "Dostupný", "", ""]])
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["Odkaz na auto"], "https://x/2")

    def test_previous_state_missing_odstraneno_dne_column(self):
        # pre-migration state file (26-col schema) must still merge
        prev = pd.DataFrame(
            [["A", "Dostupný", "https://x/1"]],
            columns=["Model auta", "Stav", "Odkaz na auto"],
        )
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Stav"], "Odstraněno")
        self.assertEqual(gone["Odstraněno dne"], "2026-07-04")


if __name__ == "__main__":
    unittest.main()
