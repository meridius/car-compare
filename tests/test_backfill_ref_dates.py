"""Tests for build/backfill_ref_dates.py — deriving Přidáno/Upraveno from history."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))

from backfill_ref_dates import compute_dates, row_content_hash


class ComputeDatesTest(unittest.TestCase):
    def test_first_appearance_sets_both_dates(self):
        snaps = [
            ("2026-05-01", {"A": "h1"}),
            ("2026-05-02", {"A": "h1", "B": "h9"}),
        ]
        out = compute_dates(snaps)
        self.assertEqual(out["A"], {"Přidáno": "2026-05-01", "Upraveno": "2026-05-01"})
        self.assertEqual(out["B"], {"Přidáno": "2026-05-02", "Upraveno": "2026-05-02"})

    def test_upraveno_bumps_only_when_content_hash_changes(self):
        snaps = [
            ("2026-05-01", {"A": "h1"}),
            ("2026-05-02", {"A": "h1"}),   # unchanged → no bump
            ("2026-05-03", {"A": "h2"}),   # changed → bump
            ("2026-05-04", {"A": "h2"}),   # unchanged → no bump
        ]
        out = compute_dates(snaps)
        self.assertEqual(out["A"]["Přidáno"], "2026-05-01")
        self.assertEqual(out["A"]["Upraveno"], "2026-05-03")

    def test_row_removed_then_readded_keeps_original_pridano(self):
        # A vanishes at 05-02, returns at 05-03 with new content.
        snaps = [
            ("2026-05-01", {"A": "h1"}),
            ("2026-05-02", {}),
            ("2026-05-03", {"A": "h2"}),
        ]
        out = compute_dates(snaps)
        self.assertEqual(out["A"]["Přidáno"], "2026-05-01")
        self.assertEqual(out["A"]["Upraveno"], "2026-05-03")


class RowContentHashTest(unittest.TestCase):
    def test_ignores_date_columns(self):
        # Changing only the date cols must not change the hash → re-runs idempotent.
        a = {"A": "1", "B": "2", "Přidáno": "2026-05-01", "Upraveno": "2026-05-01"}
        b = {"A": "1", "B": "2", "Přidáno": "2020-01-01", "Upraveno": "2099-12-31"}
        self.assertEqual(row_content_hash(a), row_content_hash(b))

    def test_absent_date_columns_same_as_present(self):
        # A pre-migration blob without the date cols hashes identically to the
        # current file's row once the (irrelevant) date cols are added.
        old = {"A": "1", "B": "2"}
        new = {"A": "1", "B": "2", "Přidáno": "2026-05-01", "Upraveno": "2026-05-01"}
        self.assertEqual(row_content_hash(old), row_content_hash(new))

    def test_content_change_changes_hash(self):
        self.assertNotEqual(
            row_content_hash({"A": "1", "B": "2"}),
            row_content_hash({"A": "1", "B": "3"}),
        )


if __name__ == "__main__":
    unittest.main()
