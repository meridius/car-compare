"""Tests for build/diagnose_unpaired.py — single-listing match diagnosis."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))

import pandas as pd

from scrapers.core.matching import _score_match, classify_match
from diagnose_unpaired import (
    row_to_scraped,
    score_breakdown,
    derive_candidate,
    simulate_candidate,
    merge_research,
    is_junk_bucket,
    _format_csv_row,
    REF_COLUMNS,
)


def auth(entry="Hyundai Santa Fe 1.6 T-GDI Hybrid", brand="Hyundai",
         model_base="Santa Fe", body="SUV", engine_vol="1.6",
         engine_type="T-GDI", hybrid="HEV", fuel="Benzín", trim=""):
    return {"entry": entry, "brand": brand, "model_base": model_base,
            "body": body, "body_raw": body, "engine_vol": engine_vol,
            "engine_type": engine_type, "hybrid": hybrid, "fuel": fuel,
            "trim": trim, "seats": ""}


def state_row(model="Hyundai Santa Fe 1.6 T-GDI Hybrid", body="SUV",
              vol="2.2", etype="CRDi", hybrid="", fuel="Nafta", trim="",
              link="https://example.com/1"):
    return {"Model auta": model, "Karoserie": body, "Objem motoru": vol,
            "Typ motoru": etype, "Hybrid typ": hybrid, "Palivo": fuel,
            "Verze": trim, "Typ": "Spalovací", "Odkaz na auto": link}


class ScoreBreakdownTest(unittest.TestCase):
    def test_breakdown_sums_to_score_match(self):
        """Itemized breakdown must always sum to the real matcher's score."""
        scrapeds = [
            {"brand": "Hyundai", "model_base": "Santa Fe", "body": "SUV",
             "engine_vol": "2.2", "engine_type": "CRDi", "hybrid": "",
             "fuel": "Nafta", "trim": ""},
            {"brand": "Hyundai", "model_base": "Santa Fe", "body": "",
             "engine_vol": "1.6", "engine_type": "T-GDI", "hybrid": "HEV",
             "fuel": "Benzín", "trim": ""},
            {"brand": "Hyundai", "model_base": "Santa Fe", "body": "Kombi",
             "engine_vol": "", "engine_type": "TDI", "hybrid": "PHEV",
             "fuel": "Nafta", "trim": "Style"},
        ]
        auths = [auth(), auth(engine_vol="2.2", engine_type="CRDi",
                              hybrid="", fuel="Nafta", trim="Style")]
        for s in scrapeds:
            for a in auths:
                items = score_breakdown(s, a)
                total = sum(i["points"] for i in items)
                self.assertEqual(total, _score_match(s, a),
                                 f"breakdown drifted from _score_match for {s} vs {a['entry']}")

    def test_breakdown_labels_contradictions(self):
        s = {"brand": "Hyundai", "model_base": "Santa Fe", "body": "SUV",
             "engine_vol": "2.2", "engine_type": "CRDi", "hybrid": "",
             "fuel": "Nafta", "trim": ""}
        items = {i["field"]: i for i in score_breakdown(s, auth())}
        self.assertEqual(items["body"]["points"], 3)
        self.assertEqual(items["engine_vol"]["points"], -1)
        self.assertEqual(items["engine_type"]["points"], -1)
        self.assertEqual(items["hybrid"]["points"], -1)
        self.assertEqual(items["fuel"]["points"], -1)


class RowToScrapedTest(unittest.TestCase):
    def test_matches_matcher_inline_construction(self):
        """row_to_scraped must classify identically to match_to_authoritative."""
        from scrapers.core.matching import match_to_authoritative
        rows = [state_row(), state_row(model="Hyundai Santa Fe", vol="1.6",
                                       etype="T-GDI", hybrid="HEV",
                                       fuel="Benzín", link="https://example.com/2")]
        auth_list = [auth()]
        df = pd.DataFrame(rows)
        matched = match_to_authoritative(df.copy(), auth_list)
        for i, row in df.iterrows():
            res = classify_match(row_to_scraped(row), auth_list)
            self.assertEqual(res["state"], matched.at[i, "Spárováno"])

    def test_handles_nan(self):
        row = pd.Series(state_row(body=None, hybrid=None))
        s = row_to_scraped(row)
        self.assertEqual(s["hybrid"], "")


class DeriveCandidateTest(unittest.TestCase):
    def test_majority_fields_win(self):
        cluster = pd.DataFrame([
            state_row(link=f"https://example.com/{i}") for i in range(5)
        ] + [state_row(etype="TDI", link="https://example.com/x")])
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe")
        self.assertEqual(cand["Značka"], "Hyundai")
        self.assertEqual(cand["Model"], "Santa Fe")
        self.assertEqual(cand["Objem motoru"], "2.2")
        self.assertEqual(cand["Typ motoru"], "CRDi")
        self.assertEqual(cand["Palivo"], "Nafta")
        self.assertEqual(cand["Karoserie"], "SUV")
        self.assertEqual(cand["Hybrid typ"], "")
        self.assertEqual(cand["Jednoznačná varianta vozu"],
                         "Hyundai Santa Fe 2.2 CRDi")

    def test_model_taken_from_existing_family(self):
        """Rewritten state names carry junk tokens ("Santa Fe Hybrid" on a
        diesel) — Model must come from the existing reference family."""
        cluster = pd.DataFrame([state_row(link=f"https://example.com/{i}")
                                for i in range(3)])
        cand = derive_candidate(cluster, brand="Hyundai",
                                model_base="Santa Fe Hybrid",
                                auth_list=[auth()])
        self.assertEqual(cand["Model"], "Santa Fe")
        self.assertEqual(cand["Jednoznačná varianta vozu"],
                         "Hyundai Santa Fe 2.2 CRDi")

    def test_low_consensus_field_blanked(self):
        cluster = pd.DataFrame([
            state_row(etype="CRDi", link="https://example.com/1"),
            state_row(etype="TDI", link="https://example.com/2"),
        ])
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe")
        self.assertEqual(cand["Typ motoru"], "")

    def test_anchor_subclusters_mixed_engine_family(self):
        """A family cluster mixes variants (Touran 1.5 TSI + 2.0 TDI); with
        an anchor the candidate must describe the diagnosed listing's
        variant, not a cross-variant mongrel."""
        cluster = pd.DataFrame(
            [state_row(vol="1.5", etype="TSI", fuel="Benzín",
                       link=f"https://example.com/tsi{i}") for i in range(4)]
            + [state_row(vol="2.0", etype="TDI", fuel="Nafta",
                         link=f"https://example.com/tdi{i}") for i in range(2)])
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe",
                                anchor={"engine_vol": "2.0",
                                        "engine_type": "TDI"})
        self.assertEqual(cand["Objem motoru"], "2.0")
        self.assertEqual(cand["Typ motoru"], "TDI")
        self.assertEqual(cand["Palivo"], "Nafta")
        self.assertEqual(cand["Jednoznačná varianta vozu"],
                         "Hyundai Santa Fe 2.0 TDI")

    def test_anchor_fills_engine_when_cluster_has_no_consensus(self):
        cluster = pd.DataFrame([
            state_row(vol="", etype="", link="https://example.com/1"),
            state_row(vol="", etype="", link="https://example.com/2"),
        ])
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe",
                                anchor={"engine_vol": "2.0",
                                        "engine_type": "TDI"})
        self.assertEqual(cand["Objem motoru"], "2.0")
        self.assertEqual(cand["Typ motoru"], "TDI")

    def test_fabricated_hybrid_minority_blanked(self):
        """mobile.de fabricated-hybrid gotcha: a minority of mislabeled
        PHEV rows must not stamp the whole candidate hybrid — blanks are a
        real 'not a hybrid' vote."""
        cluster = pd.DataFrame(
            [state_row(link=f"https://example.com/{i}") for i in range(5)]
            + [state_row(hybrid="PHEV", link=f"https://example.com/p{i}")
               for i in range(2)])
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe")
        self.assertEqual(cand["Hybrid typ"], "")
        self.assertNotIn("PHEV", cand["Jednoznačná varianta vozu"])

    def test_genuine_hybrid_majority_kept(self):
        cluster = pd.DataFrame(
            [state_row(hybrid="HEV", vol="1.6", etype="T-GDI", fuel="Benzín",
                       link=f"https://example.com/{i}") for i in range(4)])
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe")
        self.assertEqual(cand["Hybrid typ"], "HEV")


class SimulateTest(unittest.TestCase):
    def test_new_row_flips_cluster_to_ano(self):
        cluster = pd.DataFrame([state_row(link=f"https://example.com/{i}")
                                for i in range(3)])
        auth_list = [auth()]
        cand = derive_candidate(cluster, brand="Hyundai", model_base="Santa Fe")
        before, after = simulate_candidate(cluster, auth_list, cand)
        self.assertEqual(before["Nejisté"], 3)
        self.assertEqual(after["Ano"], 3)


class MergeResearchTest(unittest.TestCase):
    def _cand(self):
        return {c: "" for c in REF_COLUMNS} | {
            "Jednoznačná varianta vozu": "Hyundai Santa Fe 2.2 CRDi",
            "Značka": "Hyundai", "Model": "Santa Fe", "Karoserie": "SUV",
            "Objem motoru": "2.2", "Typ motoru": "CRDi", "Palivo": "Nafta"}

    def test_merges_and_range_validates(self):
        research = {"generace": "Gen 4", "seats": "7",
                    "consumption_l100km": "6.9", "trunk_l": "634",
                    "noise_db": "999", "cd": "0.34", "cd_source": "reálné"}
        out = merge_research(self._cand(), research)
        self.assertEqual(out["Generace"], "Gen 4")
        self.assertEqual(out["Spotřeba (l/100 km)"], "6.9")
        self.assertEqual(out["Hlučnost (dB)"], "")  # 999 out of range → blank
        self.assertEqual(out["Cd zdroj"], "reálné")

    def test_csv_row_uses_czech_decimal_for_consumption(self):
        out = merge_research(self._cand(), {"consumption_l100km": "6.9",
                                            "noise_db": "67.1"})
        row = _format_csv_row(out)
        self.assertEqual(row[REF_COLUMNS.index("Spotřeba (l/100 km)")], "6,9")
        self.assertEqual(row[REF_COLUMNS.index("Hlučnost (dB)")], "67.1")
        self.assertEqual(len(row), len(REF_COLUMNS))


class JunkBucketTest(unittest.TestCase):
    """Marketplace junk buckets (Andere/Ostatní) must never become reference
    rows — candidate/apply refuse them (docs/gotchas.md → mobile.de → Andere)."""

    def test_junk_buckets_rejected(self):
        self.assertTrue(is_junk_bucket({"Značka": "JAC", "Model": "Andere"}))
        self.assertTrue(is_junk_bucket({"Značka": "Andere", "Model": "Andere"}))
        self.assertTrue(is_junk_bucket({"Značka": "Kia", "Model": "Ostatní"}))
        self.assertTrue(is_junk_bucket({"Značka": "Kia", "Model": "andere 1.5"}))

    def test_real_models_pass(self):
        self.assertFalse(is_junk_bucket({"Značka": "Hyundai", "Model": "Santa Fe"}))
        self.assertFalse(is_junk_bucket({"Značka": "Škoda", "Model": "Octavia"}))


class ApplyStampsDatesTest(unittest.TestCase):
    """A newly applied reference row must carry Přidáno + Upraveno = today."""

    def test_ref_columns_end_with_date_cols(self):
        self.assertEqual(REF_COLUMNS[-2:], ["Přidáno", "Upraveno"])

    def test_apply_writes_today_in_both_date_cols(self):
        import argparse
        import csv
        import datetime
        import json
        import tempfile
        import diagnose_unpaired as du

        cand = {
            "Jednoznačná varianta vozu": "Testovací Vůz 9.9 XYZ",
            "Značka": "Testovací", "Model": "Vůz",
        }
        today = datetime.date.today().isoformat()
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "ice_specs.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(REF_COLUMNS)
            cand_path = os.path.join(d, "cand.json")
            with open(cand_path, "w", encoding="utf-8") as f:
                json.dump(cand, f)

            orig = du.AUTH_CSV
            du.AUTH_CSV = csv_path
            try:
                du.cmd_apply(argparse.Namespace(
                    candidate=cand_path, research=None, dry_run=False))
            finally:
                du.AUTH_CSV = orig

            with open(csv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[-1]["Přidáno"], today)
        self.assertEqual(rows[-1]["Upraveno"], today)


if __name__ == "__main__":
    unittest.main()
