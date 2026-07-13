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


# Extended fixture: seller price (Cena) + a match-derived col (Skóre shody) so the
# lifecycle-date rules can be exercised (content change vs match-only change).
LCOLS = ["Model auta", "Cena (Kč)", "Skóre shody", "Stav",
         "Odstraněno dne", "Odkaz na auto", "Přidáno", "Upraveno"]


def _ldf(rows):
    return pd.DataFrame(rows, columns=LCOLS)


class LifecycleDateTest(unittest.TestCase):
    # rows: [Model, Cena, Skóre, Stav, OdstrDne, Odkaz, Přidáno, Upraveno]

    def test_genuinely_new_row_stamped_today(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""],
                    ["B", "600000", "3", "Dostupný", "", "https://x/2", "", ""]])
        out = _merge(new, prev)
        added = out[out["Odkaz na auto"] == "https://x/2"].iloc[0]
        self.assertEqual(added["Přidáno"], "2026-07-04")
        self.assertEqual(added["Upraveno"], "2026-07-04")

    def test_no_previous_state_stamps_all_rows_today(self):
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, None)
        self.assertEqual(out.iloc[0]["Přidáno"], "2026-07-04")
        self.assertEqual(out.iloc[0]["Upraveno"], "2026-07-04")

    def test_unchanged_row_carries_dates_forward(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-10"]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "2026-06-01")
        self.assertEqual(row["Upraveno"], "2026-06-10")  # NOT bumped

    def test_unchanged_row_with_blank_dates_stays_blank(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "")
        self.assertEqual(row["Upraveno"], "")

    def test_mileage_change_bumps_upraveno(self):
        # Nájezd is a seller field IN the hash — the clean "bump" case.
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        # Nájezd (km) is a seller field in the hash — set it different on each side.
        prev["Nájezd (km)"] = "40000"
        new["Nájezd (km)"] = "45000"
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "2026-06-01")   # carried
        self.assertEqual(row["Upraveno"], "2026-07-04")  # bumped

    def test_model_auta_change_alone_does_not_bump(self):
        # Model auta is rewritten by matching (reference edits), so a change to it
        # with identical seller content must NOT bump Upraveno.
        prev = _ldf([["Škoda Octavia", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["Škoda Octavia 1.5 TSI", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # NOT bumped

    def test_match_score_change_alone_does_not_bump(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "500000", "9", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # Skóre shody excluded

    def test_price_jitter_under_one_percent_does_not_bump(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "503000", "3", "Dostupný", "", "https://x/1", "", ""]])  # +0.6%
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # FX jitter absorbed

    def test_real_price_move_bumps_upraveno(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]])
        new = _ldf([["A", "480000", "3", "Dostupný", "", "https://x/1", "", ""]])  # -4%
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-07-04")  # real drop bumps

    def test_removed_row_carries_dates_and_is_not_bumped(self):
        prev = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-05"]])
        new = _ldf([["B", "600000", "3", "Dostupný", "", "https://x/2", "", ""]])
        out = _merge(new, prev)
        gone = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(gone["Stav"], "Odstraněno")
        self.assertEqual(gone["Odstraněno dne"], "2026-07-04")
        self.assertEqual(gone["Přidáno"], "2026-06-01")   # carried
        self.assertEqual(gone["Upraveno"], "2026-06-05")  # NOT bumped

    def test_prev_without_date_columns_leaves_blank(self):
        # Existing state predates the feature → columns absent → blank backfill.
        legacy_cols = ["Model auta", "Cena (Kč)", "Skóre shody", "Stav",
                       "Odstraněno dne", "Odkaz na auto"]
        prev = pd.DataFrame([["A", "500000", "3", "Dostupný", "", "https://x/1"]],
                            columns=legacy_cols)
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Přidáno"], "")
        self.assertEqual(row["Upraveno"], "")

    def test_new_canonical_column_absent_from_prev_does_not_bump(self):
        # State written by an older code version lacks a canonical content column
        # the new scrape now carries; identical seller content otherwise must NOT
        # bump Upraveno (schema-migration idempotency, cf. backfill_ref_dates).
        prev = pd.DataFrame(
            [["A", "500000", "3", "Dostupný", "", "https://x/1", "2026-06-01", "2026-06-01"]],
            columns=["Model auta", "Cena (Kč)", "Skóre shody", "Stav",
                     "Odstraněno dne", "Odkaz na auto", "Přidáno", "Upraveno"],
        )
        new = _ldf([["A", "500000", "3", "Dostupný", "", "https://x/1", "", ""]])
        new["Počet válců"] = "4"   # canonical content col absent from prev
        out = _merge(new, prev)
        row = out[out["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Upraveno"], "2026-06-01")  # not bumped


if __name__ == "__main__":
    unittest.main()
