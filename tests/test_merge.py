"""Golden tests for merge_with_previous: removal stamping + optional retention.

State layer semantics:
- a vanished link is kept with Stav="Odstraněno" and stamped "Odstraněno dne"=today
- the stamp is preserved on later merges (not re-stamped)
- by default (retention_days=None) removed rows are kept forever — they become
  the lazy-loaded archive in the dashboard (decision 001, option C)
- when a retention_days cap IS passed, rows removed longer ago are dropped
- a reappearing link takes the fresh row (blank stamp) — new data always wins
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from scrapers.core import storage
from scrapers.core.merge import merge_with_previous

COLS = ["Model auta", "Stav", "Odstraněno dne", "Odkaz na auto"]
TODAY = date(2026, 7, 4)


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


def _merge(new_df, prev_df, today=TODAY, retention_days=None):
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "src"
        if prev_df is not None:
            storage.write_state(prev_df, base)
        return merge_with_previous(new_df, base, today=today, retention_days=retention_days)


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

    def test_default_keeps_all_removed_forever(self):
        # No retention cap by default — removed rows become the lazy archive.
        ancient = (TODAY - timedelta(days=3650)).isoformat()
        prev = _df([["ancient", "Odstraněno", ancient, "https://x/1"]])
        new = _df([["B", "Dostupný", "", "https://x/2"]])
        out = _merge(new, prev)  # retention_days=None
        self.assertIn("https://x/1", set(out["Odkaz na auto"]))

    def test_retention_cap_drops_rows_older_than_cutoff(self):
        cap = 60
        old_date = (TODAY - timedelta(days=cap + 1)).isoformat()
        edge_date = (TODAY - timedelta(days=cap)).isoformat()
        prev = _df([
            ["too-old", "Odstraněno", old_date, "https://x/1"],
            ["edge-keep", "Odstraněno", edge_date, "https://x/2"],
        ])
        new = _df([["B", "Dostupný", "", "https://x/3"]])
        out = _merge(new, prev, retention_days=cap)
        self.assertNotIn("https://x/1", set(out["Odkaz na auto"]))
        self.assertIn("https://x/2", set(out["Odkaz na auto"]))

    def test_retention_cap_ignores_non_removed_rows(self):
        # a bogus stamp on a live row must not delete it even with a cap set
        prev = _df([["A", "Dostupný", "2020-01-01", "https://x/1"]])
        new = _df([["A", "Dostupný", "", "https://x/1"]])
        out = _merge(new, prev, retention_days=60)
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

    def test_previous_state_missing_pocet_valcu_column(self):
        """#24: a previous state file predating the 'Počet válců' column (not
        referenced by key inside merge_with_previous — unlike 'Odstraněno dne')
        must still merge, relying on pandas' natural key-union + NaN-fill when
        building the result frame from per-row dicts."""
        prev = pd.DataFrame(
            [["A", "Dostupný", "https://x/1"]],
            columns=["Model auta", "Stav", "Odkaz na auto"],
        )
        new = pd.DataFrame(
            [["B", "Dostupný", "4", "https://x/2"]],
            columns=["Model auta", "Stav", "Počet válců", "Odkaz na auto"],
        )
        out = _merge(new, prev)
        self.assertEqual(len(out), 2)
        fresh = out[out["Odkaz na auto"] == "https://x/2"].iloc[0]
        self.assertEqual(fresh["Počet válců"], "4")
        old = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertTrue(pd.isna(old["Počet válců"]) or old["Počet válců"] == "")


if __name__ == "__main__":
    unittest.main()
