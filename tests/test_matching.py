"""Golden unit tests for ICE reference-model matching (scrapers/core/matching.py).

These pin the tri-state confidence behaviour so the matcher can be refactored
without silently regressing to over-confident assignments. Pure, no network,
runs in milliseconds.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.core import matching as M  # noqa: E402


def auth(entry, brand, base, body="", vol="", etype="", hybrid="", fuel=""):
    return {"entry": entry, "brand": brand, "model_base": base, "body": body,
            "engine_vol": vol, "engine_type": etype, "hybrid": hybrid, "fuel": fuel}


def scraped(brand, base, body="", vol="", etype="", hybrid="", fuel=""):
    return {"brand": brand, "model_base": base, "body": body,
            "engine_vol": vol, "engine_type": etype, "hybrid": hybrid, "fuel": fuel}


class ClassifyMatchTest(unittest.TestCase):
    def test_no_candidate_is_ne(self):
        res = M.classify_match(scraped("Zzz", "Nothing"), [auth("Foo Bar", "Foo", "Bar")])
        self.assertEqual(res["state"], "Ne")
        self.assertIsNone(res["score"])
        self.assertIsNone(res["entry"])

    def test_strong_clear_winner_is_ano(self):
        al = [auth("Škoda Karoq 1.5 TSI", "Škoda", "Karoq", vol="1.5", etype="TSI"),
              auth("Škoda Karoq 2.0 TDI", "Škoda", "Karoq", vol="2.0", etype="TDI")]
        res = M.classify_match(scraped("Škoda", "Karoq", vol="1.5", etype="TSI"), al)
        self.assertEqual(res["state"], "Ano")
        self.assertEqual(res["entry"], "Škoda Karoq 1.5 TSI")
        self.assertGreaterEqual(res["score"], M.STRONG_FLOOR)

    def test_tie_is_nejiste(self):
        # Two distinct variants score identically — the old matcher silently
        # picked the first; now it must be flagged uncertain.
        al = [auth("Audi A6 2.0 TDI", "Audi", "A6", vol="2.0", etype="TDI"),
              auth("Audi A6 Sport 2.0 TDI", "Audi", "A6 Sport", vol="2.0", etype="TDI")]
        res = M.classify_match(scraped("Audi", "A6", vol="2.0", etype="TDI"), al)
        self.assertEqual(res["state"], "Nejisté")
        self.assertEqual(res["margin"], 0)

    def test_thin_data_score_zero_is_nejiste(self):
        # No discriminating fields → score 0 → not a confident match.
        res = M.classify_match(scraped("Foo", "Bar"), [auth("Foo Bar", "Foo", "Bar")])
        self.assertEqual(res["state"], "Nejisté")
        self.assertEqual(res["score"], 0)

    def test_contradiction_is_nejiste_but_keeps_best_guess(self):
        # Diesel listing vs petrol-PHEV reference: fields contradict → negative
        # score → Nejisté, but the best-guess entry is still recorded.
        al = [auth("Audi Q3 TFSI (PHEV)", "Audi", "Q3", etype="TFSI", hybrid="PHEV")]
        res = M.classify_match(scraped("Audi", "Q3", etype="TDI"), al)
        self.assertEqual(res["state"], "Nejisté")
        self.assertLess(res["score"], 0)
        self.assertEqual(res["entry"], "Audi Q3 TFSI (PHEV)")

    def test_single_candidate_meeting_floor_is_ano(self):
        # margin is None (no runner-up) → no ambiguity → Ano if score >= floor.
        res = M.classify_match(scraped("Foo", "Bar", fuel="Benzín"),
                               [auth("Foo Bar", "Foo", "Bar", fuel="Benzín")])
        self.assertEqual(res["state"], "Ano")
        self.assertIsNone(res["margin"])

    def test_clear_margin_promotes_to_ano(self):
        al = [auth("Foo Bar 1.5 TSI", "Foo", "Bar", vol="1.5", etype="TSI"),  # +4
              auth("Foo Bar 1.5", "Foo", "Bar", vol="1.5")]                    # +2
        res = M.classify_match(scraped("Foo", "Bar", vol="1.5", etype="TSI"), al)
        self.assertEqual(res["state"], "Ano")
        self.assertGreaterEqual(res["margin"], M.MARGIN_REQ)


class MatchToAuthoritativeDataFrameTest(unittest.TestCase):
    def test_df_gets_tristate_and_score_columns(self):
        import pandas as pd
        from scrapers.core.schema import blank_row, CANONICAL_COLS

        al = [auth("Škoda Karoq 1.5 TSI", "Škoda", "Karoq", vol="1.5", etype="TSI")]
        r1 = blank_row(); r1.update({"Model auta": "Škoda Karoq",
                                     "Objem motoru": "1.5", "Typ motoru": "TSI"})
        r2 = blank_row(); r2.update({"Model auta": "Zzz Nothing"})
        df = pd.DataFrame([r1, r2], columns=CANONICAL_COLS)

        out = M.match_to_authoritative(df, al)
        self.assertIn("Skóre shody", out.columns)
        self.assertEqual(out.iloc[0]["Spárováno"], "Ano")
        self.assertEqual(out.iloc[0]["Model auta"], "Škoda Karoq 1.5 TSI")
        self.assertEqual(out.iloc[1]["Spárováno"], "Ne")
        self.assertEqual(out.iloc[1]["Skóre shody"], "")


if __name__ == "__main__":
    unittest.main()
