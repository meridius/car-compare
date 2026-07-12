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


if __name__ == "__main__":
    unittest.main()
