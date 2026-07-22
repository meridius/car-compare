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


def auth(entry, brand, base, body="", vol="", etype="", hybrid="", fuel="", trim=""):
    return {"entry": entry, "brand": brand, "model_base": base, "body": body,
            "engine_vol": vol, "engine_type": etype, "hybrid": hybrid, "fuel": fuel,
            "trim": trim}


def scraped(brand, base, body="", vol="", etype="", hybrid="", fuel="", trim=""):
    return {"brand": brand, "model_base": base, "body": body,
            "engine_vol": vol, "engine_type": etype, "hybrid": hybrid, "fuel": fuel,
            "trim": trim}


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

    def test_trim_disambiguates_otherwise_identical_variants(self):
        # Trim variants are kept as separate reference rows; without trim scoring
        # they tie (Nejisté). The matching scored trim must break the tie.
        al = [auth("Škoda Octavia Combi Style 1.5 TSI", "Škoda", "Octavia",
                   body="Kombi", vol="1.5", etype="TSI", trim="Style"),
              auth("Škoda Octavia Combi Selection 1.5 TSI", "Škoda", "Octavia",
                   body="Kombi", vol="1.5", etype="TSI", trim="Selection")]
        res = M.classify_match(
            scraped("Škoda", "Octavia", body="Kombi", vol="1.5", etype="TSI", trim="Style"), al)
        self.assertEqual(res["state"], "Ano")
        self.assertEqual(res["entry"], "Škoda Octavia Combi Style 1.5 TSI")


class TrimFromTextTest(unittest.TestCase):
    """Lever A: derive a listing's trim from free text (name remainder + Extra)
    when the Verze column is blank, so trim-only sibling ties resolve. Only the
    trims the reference actually carries are emitted, and only when the text
    yields EXACTLY ONE — an ambiguous/empty text stays blank (→ honest Nejisté),
    never a false-confidence flip to the wrong sibling."""

    def test_full_word_trim(self):
        self.assertEqual(M._trim_from_text("Octavia Combi Selection 1.5 TSI"), "Selection")

    def test_sauto_abbreviation(self):
        # sauto Extra codes: "OCTAVIA COM STY TS 110 M6F" → Style, "... SEL ..." → Selection
        self.assertEqual(M._trim_from_text("OCTAVIA COM STY TS 110 M6F"), "Style")
        self.assertEqual(M._trim_from_text("OCTAVIA COM SEL TD 110 A7F"), "Selection")

    def test_no_token_is_blank(self):
        self.assertEqual(M._trim_from_text("Octavia Combi 1.5 TSI Business"), "")

    def test_ambiguous_two_trims_is_blank(self):
        # two distinct trims → can't disambiguate → blank (stay Nejisté)
        self.assertEqual(M._trim_from_text("Octavia Style and Selection pack"), "")

    def test_unknown_trim_not_in_reference_is_blank(self):
        # Titanium/Trend have no reference sibling to match → emitting them can't
        # help and risks noise, so they are not in the emitted vocab.
        self.assertEqual(M._trim_from_text("Ford Puma Titanium"), "")

    def test_word_boundary_no_false_substring(self):
        self.assertEqual(M._trim_from_text("Lifestyle edition"), "")  # not "Life"


class LoadAuthoritativeListTest(unittest.TestCase):
    """The reference CSV now carries structured feature columns; the loader must
    read them directly instead of regex-parsing the display name."""

    def _write(self, content):
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        self.addCleanup(lambda: os.remove(f.name))
        return f.name

    _HEADER = ("Jednoznačná varianta vozu,Značka,Model,Verze,Generace,Karoserie,"
               "Počet míst,Objem motoru,Typ motoru,Palivo,Hybrid typ,"
               "Spotřeba (l/100 km),Objem kufru (l),Hlučnost (dB),Cd\n")

    def test_reads_feature_columns_not_name(self):
        # The paren-free name alone would parse to blank fuel/body; only reading
        # the columns yields them. This is the whole point of the restructure.
        path = self._write(self._HEADER +
                           "Škoda Karoq 1.5 TSI,Škoda,Karoq,,,SUV,,1.5,TSI,Benzín,,6.2,521,69,0.33\n")
        r = M.load_authoritative_list(path)[0]
        self.assertEqual(r["entry"], "Škoda Karoq 1.5 TSI")
        self.assertEqual(r["brand"], "Škoda")
        self.assertEqual(r["model_base"], "Karoq")
        self.assertEqual(r["body"], "SUV")
        self.assertEqual(r["engine_vol"], "1.5")
        self.assertEqual(r["engine_type"], "TSI")
        self.assertEqual(r["fuel"], "Benzín")
        self.assertEqual(r["hybrid"], "")

    def test_body_is_canonicalized(self):
        path = self._write(self._HEADER +
                           "VW Golf Variant 1.5 TSI,VW,Golf,,,Variant,,1.5,TSI,Benzín,,5.6,611,69,0.30\n")
        r = M.load_authoritative_list(path)[0]
        self.assertEqual(r["body"], "Kombi")  # Variant -> Kombi synonym group

    def test_reads_trim_column(self):
        path = self._write(self._HEADER +
                           "Škoda Octavia Combi Style 1.5 TSI,Škoda,Octavia,Style,Gen 4,Kombi,,1.5,TSI,Benzín,,5.6,640,69,0.27\n")
        r = M.load_authoritative_list(path)[0]
        self.assertEqual(r["trim"], "Style")

    def test_body_raw_is_unfolded(self):
        # body_raw keeps the display value; body is scoring-folded. A Liftback
        # reference row must expose body_raw="Liftback" (display) even though
        # body="Hatchback" (scoring group).
        path = self._write(self._HEADER +
                           "Škoda Octavia Liftback 1.5 TSI,Škoda,Octavia,,,Liftback,,1.5,TSI,Benzín,,5.6,600,69,0.27\n")
        r = M.load_authoritative_list(path)[0]
        self.assertEqual(r["body_raw"], "Liftback")
        self.assertEqual(r["body"], "Hatchback")  # scoring fold, unchanged


class BodyCanonScoringFoldTest(unittest.TestCase):
    """Scoring-side _canonicalize_body must fold the listing-emitted synonyms so
    an obvious SUV/MPV/coupé listing doesn't lose match points against the
    reference (which uses the canonical label)."""

    def test_suv_synonyms(self):
        for syn in ("CUV", "Terénní", "Offroad", "Crossover"):
            self.assertEqual(M._canonicalize_body(syn), "SUV", syn)

    def test_mpv_synonyms(self):
        self.assertEqual(M._canonicalize_body("VAN"), "MPV")

    def test_kupe_synonyms(self):
        for syn in ("Kupé", "Coupé", "Coupe"):
            self.assertEqual(M._canonicalize_body(syn), "Kupé", syn)

    def test_unknown_passes_through(self):
        self.assertEqual(M._canonicalize_body("Pick-up"), "Pick-up")

    def test_cuv_listing_scores_against_suv_reference(self):
        scraped = {"body": "CUV"}
        a = auth("Škoda Karoq 1.5 TSI", "Škoda", "Karoq", body="SUV")
        # Before the fold, CUV != SUV → −2; after, +3.
        self.assertGreater(M._score_match(scraped, a), 0)


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

    def test_verze_column_feeds_trim_scoring(self):
        """Verze column plumbing: match_to_authoritative reads the scraped-side
        trim from the canonical 'Verze' column (renamed from 'Výbava'), not a
        stale 'Výbava' column. The auth-side CSV column name is unaffected."""
        import pandas as pd
        from scrapers.core.schema import blank_row, CANONICAL_COLS

        al = [auth("Škoda Octavia Combi Style 1.5 TSI", "Škoda", "Octavia",
                   body="Kombi", vol="1.5", etype="TSI", trim="Style"),
              auth("Škoda Octavia Combi Selection 1.5 TSI", "Škoda", "Octavia",
                   body="Kombi", vol="1.5", etype="TSI", trim="Selection")]
        r1 = blank_row(); r1.update({"Model auta": "Škoda Octavia Combi",
                                     "Karoserie": "Kombi", "Objem motoru": "1.5",
                                     "Typ motoru": "TSI", "Verze": "Style"})
        df = pd.DataFrame([r1], columns=CANONICAL_COLS)

        out = M.match_to_authoritative(df, al)
        self.assertEqual(out.iloc[0]["Spárováno"], "Ano")
        self.assertEqual(out.iloc[0]["Model auta"], "Škoda Octavia Combi Style 1.5 TSI")

    def test_score_assignment_survives_strict_column_dtypes(self):
        """Regression: pandas 3.x makes a column's dtype strict, and the
        'Skóre shody' column arrives with different dtypes across the pipeline:
          - 'string' on a fresh scrape (blank_row seeds "") — rejects ints,
          - 'float64' after a CSV round-trip in build_data (numeric + NaN) —
            rejects strings.
        match_to_authoritative must handle both without raising TypeError."""
        import warnings
        import pandas as pd
        from scrapers.core.schema import blank_row, CANONICAL_COLS

        al = [auth("Škoda Karoq 1.5 TSI", "Škoda", "Karoq", vol="1.5", etype="TSI")]
        for dtype in ("string", "float64", "object"):
            with self.subTest(dtype=dtype):
                r1 = blank_row(); r1.update({"Model auta": "Škoda Karoq",
                                             "Objem motoru": "1.5", "Typ motoru": "TSI"})
                df = pd.DataFrame([r1], columns=CANONICAL_COLS)
                # float64 can't hold "" — use NaN, as a CSV round-trip would.
                df["Skóre shody"] = (
                    pd.Series([float("nan")], dtype="float64") if dtype == "float64"
                    else df["Skóre shody"].astype(dtype)
                )
                # pandas 3.x hard-raises TypeError on an incompatible-dtype set;
                # pandas 2.x only warns (FutureWarning). Promote that warning to
                # an error so this regression is caught on either version.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", FutureWarning)
                    out = M.match_to_authoritative(df, al)  # must not raise
                self.assertEqual(out.iloc[0]["Spárováno"], "Ano")
                self.assertGreaterEqual(int(out.iloc[0]["Skóre shody"]), M.STRONG_FLOOR)


class MercedesClassPrefixTest(unittest.TestCase):
    """Mercedes 'Třídy X' family collision (TASKS.md): the model base for every
    Mercedes A/B-class listing is 'Třídy A' / 'Třídy B', which share the generic
    first word 'Třídy'. _model_base_match's first-word heuristic then made every
    'Třídy B' listing a candidate of every 'Třídy A' reference (and vice versa),
    pulling the wrong class into scoring. Fix: strip the leading class word so the
    base is the bare class letter ('A' / 'B'), consistent with the already-bare
    'C' / 'E' / 'GLA' reference models."""

    _REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scrapers", "data", "reference", "ice_specs.csv")

    def test_clean_model_strips_class_prefix(self):
        self.assertEqual(M._clean_model_for_matching("Třídy B"), "B")
        self.assertEqual(M._clean_model_for_matching("Třídy A 180"), "A")
        # unrelated multi-token bases are untouched
        self.assertEqual(M._clean_model_for_matching("Santa Fe"), "Santa Fe")

    def test_load_authoritative_strips_class_prefix(self):
        al = M.load_authoritative_list(self._REF)
        merc = [a for a in al if a["brand"] == "Mercedes-Benz"
                and a["entry"].startswith("Mercedes-Benz Třídy")]
        self.assertTrue(merc, "expected Mercedes Třídy reference rows")
        bases = {a["model_base"] for a in merc}
        self.assertTrue(bases <= {"A", "B"},
                        f"class prefix not stripped: {bases}")

    def test_class_b_listing_does_not_match_class_a_reference(self):
        import pandas as pd
        from scrapers.core.schema import blank_row, CANONICAL_COLS

        al = M.load_authoritative_list(self._REF)
        r = blank_row(); r.update({"Model auta": "Mercedes-Benz Třídy B 200",
                                    "Objem motoru": "1.3"})
        df = pd.DataFrame([r], columns=CANONICAL_COLS)
        out = M.match_to_authoritative(df, al)
        model = out.iloc[0]["Model auta"]
        self.assertNotIn("Třídy A", model,
                         f"class-B listing leaked into class-A reference: {model}")


class ReferenceCSVSchemaTest(unittest.TestCase):
    """Reference-versioning plumbing: the auth-side reference CSVs carry the
    'Verze' column (ICE renamed from 'Výbava'; EV newly added) so version data
    can be curated there. Pins the header contract load_authoritative_list and
    the EV reference loader depend on."""

    _REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scrapers", "data", "reference")

    def _header(self, name):
        with open(os.path.join(self._REF, name), encoding="utf-8") as f:
            return f.readline().rstrip("\n").split(",")

    def test_ice_specs_has_verze_not_vybava(self):
        cols = self._header("ice_specs.csv")
        self.assertIn("Verze", cols)
        self.assertNotIn("Výbava", cols)

    def test_ev_specs_has_verze(self):
        self.assertIn("Verze", self._header("ev_specs.csv"))

    def test_load_authoritative_reads_trim_from_verze(self):
        path = os.path.join(self._REF, "ice_specs.csv")
        recs = M.load_authoritative_list(path)
        self.assertTrue(any(r["trim"] for r in recs),
                        "no trims read — 'Verze' column not wired into matching")


if __name__ == "__main__":
    unittest.main()
