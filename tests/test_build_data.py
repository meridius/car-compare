"""Tests for build-time reference joins (build/build_data.py).

Focused regression coverage for the electric prefix-join, which is case-sensitive
startswith by nature — listings arrive with inconsistent brand casing (e.g. sauto
emits 'MINI' while the reference is normalized to 'Mini'), so the join must fold
case or those cars silently go unmatched.
"""
import os
import sys
import unittest

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from build import build_data as B  # noqa: E402


def _ev_df(model):
    return pd.DataFrame([{"Typ": "Elektrické", "Model auta": model}])


def _ev_ref():
    return pd.DataFrame([{
        "Model auta": "Mini Cooper SE",
        "Objem kufru (l)": 211,
        "Hlučnost (dB)": "",
        "Kapacita baterie (kWh)": 49.2,
        "Dojezd komb. letní WLTP (km)": 402,
        "Dojezd komb. letní EV-database (km)": 330,
        "Cd": "",
        "Tepelné čerpadlo možné (ano/ne)": "ne",
    }])


class SplitBrandModelTest(unittest.TestCase):
    """Task #3: payload/display split of 'Model auta' into 'Značka' + 'Model'.

    Reuses the scraped-side brand parser (core.matching._parse_brand /
    MULTI_WORD_BRANDS) rather than inventing a new splitter — see
    build_data.split_brand_model."""

    def test_single_word_brand(self):
        self.assertEqual(
            B.split_brand_model("Škoda Karoq 1.5 TSI"), ("Škoda", "Karoq 1.5 TSI"))

    def test_multi_word_brand(self):
        self.assertEqual(
            B.split_brand_model("Alfa Romeo Tonale 1.5"), ("Alfa Romeo", "Tonale 1.5"))

    def test_another_multi_word_brand(self):
        self.assertEqual(
            B.split_brand_model("Land Rover Defender 110"), ("Land Rover", "Defender 110"))

    def test_unknown_brand_falls_back_to_first_token(self):
        self.assertEqual(
            B.split_brand_model("Zzz Nothing 1.0"), ("Zzz", "Nothing 1.0"))

    def test_brand_only_no_remainder(self):
        self.assertEqual(B.split_brand_model("Tesla"), ("Tesla", ""))

    def test_blank_input(self):
        self.assertEqual(B.split_brand_model(""), ("", ""))

    def test_nan_input(self):
        self.assertEqual(B.split_brand_model(float("nan")), ("", ""))


class AddBrandModelColumnsTest(unittest.TestCase):
    """add_brand_model_columns() is the payload-only transform: it derives the
    two display columns and drops 'Model auta' — the canonical scrape/state
    schema is untouched (only build_data's payload output changes)."""

    def test_drops_model_auta_adds_znacka_model(self):
        df = pd.DataFrame([
            {"Model auta": "Škoda Karoq 1.5 TSI", "Typ": "Spalovací"},
            {"Model auta": "Alfa Romeo Tonale 1.5", "Typ": "Spalovací"},
        ])
        out = B.add_brand_model_columns(df)
        self.assertNotIn("Model auta", out.columns)
        self.assertIn("Značka", out.columns)
        self.assertIn("Model", out.columns)
        self.assertEqual(out.iloc[0]["Značka"], "Škoda")
        self.assertEqual(out.iloc[0]["Model"], "Karoq")
        self.assertEqual(out.iloc[1]["Značka"], "Alfa Romeo")
        self.assertEqual(out.iloc[1]["Model"], "Tonale")

    def test_task4_strips_engine_vol_and_type_from_ice_model(self):
        """Task #4: the displayed 'Model' column must not carry Objem
        motoru / Typ motoru tokens baked into the matched auth string
        ('Karoq 1.5 TSI') or the unmatched '_format_unmatched' tail
        ('Mokka 1.2 Turbo') — ICE rows only."""
        df = pd.DataFrame([
            {"Model auta": "Škoda Karoq 1.5 TSI", "Typ": "Spalovací"},
            {"Model auta": "Opel Mokka 1.2 Turbo", "Typ": "Spalovací"},
            {"Model auta": "VW Golf 8 Variant 2.0 TDI", "Typ": "Spalovací"},
        ])
        out = B.add_brand_model_columns(df)
        self.assertEqual(out.iloc[0]["Model"], "Karoq")
        self.assertEqual(out.iloc[1]["Model"], "Mokka")
        self.assertEqual(out.iloc[2]["Model"], "Golf 8 Variant")

    def test_task4_ev_variant_number_not_stripped(self):
        """'iV 80' is a battery-tier variant number, not engine displacement —
        must survive untouched on EV rows."""
        df = pd.DataFrame([
            {"Model auta": "Škoda Enyaq iV 80", "Typ": "Elektrické"},
        ])
        out = B.add_brand_model_columns(df)
        self.assertEqual(out.iloc[0]["Model"], "Enyaq iV 80")

    def test_task4_missing_typ_column_leaves_model_untouched(self):
        """Without a 'Typ' column we can't safely tell ICE from EV — skip
        stripping rather than risk mangling an EV variant number."""
        df = pd.DataFrame([{"Model auta": "Škoda Karoq 1.5 TSI"}])
        out = B.add_brand_model_columns(df)
        self.assertEqual(out.iloc[0]["Model"], "Karoq 1.5 TSI")


class StripIceEngineTokensTest(unittest.TestCase):
    """Task #4: strip_ice_engine_tokens() reuses core.fields extraction/strip
    helpers (no parallel engine-keyword list) to remove Objem motoru / Typ
    motoru tokens from a display 'Model' string."""

    def test_strips_vol_and_type(self):
        self.assertEqual(B.strip_ice_engine_tokens("Karoq 1.5 TSI"), "Karoq")

    def test_strips_turbo_as_engine_type(self):
        self.assertEqual(B.strip_ice_engine_tokens("Mokka 1.2 Turbo"), "Mokka")

    def test_strips_tokens_from_the_middle(self):
        self.assertEqual(
            B.strip_ice_engine_tokens("Golf 8 Variant 2.0 TDI"), "Golf 8 Variant")

    def test_no_tokens_present_returns_unchanged(self):
        self.assertEqual(B.strip_ice_engine_tokens("Enyaq iV 80"), "Enyaq iV 80")

    def test_never_returns_empty_string(self):
        # Stripping "1.5 TSI" down to nothing would leave a blank Model —
        # keep the original instead.
        self.assertEqual(B.strip_ice_engine_tokens("1.5 TSI"), "1.5 TSI")

    def test_blank_input(self):
        self.assertEqual(B.strip_ice_engine_tokens(""), "")


class PayloadWriterTest(unittest.TestCase):
    """Pins the split payload contract (decision 001, option C).

    Live listings → cars.parquet (always loaded); removed (Stav="Odstraněno") →
    cars-archived.parquet (lazy-loaded). Numeric columns must be float64 —
    pyarrow int64 decodes to BigInt in hyparquet and breaks the grid. Blanks
    must arrive as null, not "".
    """

    def _write(self, td):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Model auta": "Škoda Karoq 1.5 TSI",
             "Cena (Kč)": "599000", "Nájezd (km)": "", "Typ motoru": "TSI",
             "Objem motoru": "1.5", "Stav": "Dostupný", "Odkaz na auto": "https://x/1"},
            {"Typ": "Elektrické", "Model auta": "Tesla Model 3",
             "Cena (Kč)": "888000", "Nájezd (km)": "12000", "Typ motoru": "",
             "Objem motoru": "", "Stav": "", "Odkaz na auto": "https://x/2"},
            {"Typ": "Spalovací", "Model auta": "Audi A4 2.0 TDI",
             "Cena (Kč)": "450000", "Nájezd (km)": "88000", "Typ motoru": "TDI",
             "Objem motoru": "2.0", "Stav": "Odstraněno", "Odkaz na auto": "https://x/3"},
        ])
        meta = {"buildDate": "2026-07-04T00:00:00Z", "trigger": "manual",
                "sources": {}, "matching": {}, "referenceData": {},
                "totalCars": 2, "archivedCars": 1}
        return B.write_payload(df, meta, td)

    def test_writes_live_archive_and_meta(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            live_path, archived_path, meta_path = self._write(td)
            self.assertTrue(live_path.endswith("cars.parquet"))
            self.assertTrue(archived_path.endswith("cars-archived.parquet"))
            self.assertTrue(os.path.exists(live_path) and os.path.exists(archived_path))
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        self.assertEqual(
            set(meta),
            {"buildDate", "trigger", "sources", "matching", "referenceData",
             "totalCars", "archivedCars"},
        )

    def test_payload_splits_model_auta_into_znacka_and_model(self):
        """Task #3: write_payload derives 'Značka' + 'Model' from 'Model auta'
        and drops 'Model auta' from both payload parquets."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            live_path, archived_path, _ = self._write(td)
            live = pd.read_parquet(live_path)
            archived = pd.read_parquet(archived_path)
        for frame in (live, archived):
            self.assertNotIn("Model auta", frame.columns)
            self.assertIn("Značka", frame.columns)
            self.assertIn("Model", frame.columns)
        row = live[live["Odkaz na auto"] == "https://x/1"].iloc[0]
        self.assertEqual(row["Značka"], "Škoda")
        self.assertEqual(row["Model"], "Karoq")  # task #4: engine tokens stripped
        row2 = archived.iloc[0]
        self.assertEqual(row2["Značka"], "Audi")
        self.assertEqual(row2["Model"], "A4")  # task #4: engine tokens stripped

    def test_live_excludes_removed_archive_holds_only_removed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            live_path, archived_path, _ = self._write(td)
            live = pd.read_parquet(live_path)
            archived = pd.read_parquet(archived_path)
        self.assertEqual(len(live), 2)
        self.assertNotIn("Odstraněno", set(live["Stav"].dropna()))
        self.assertEqual(len(archived), 1)
        self.assertEqual(set(archived["Stav"]), {"Odstraněno"})

    def test_no_int64_columns_in_either_payload(self):
        import tempfile
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as td:
            live_path, archived_path, _ = self._write(td)
            for path in (live_path, archived_path):
                for field in pq.read_schema(path):
                    self.assertNotIn("int64", str(field.type),
                                     f"{field.name} in {path} is int64 → BigInt in hyparquet")

    def test_blanks_become_null_not_empty_string(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            live_path, _, _ = self._write(td)
            back = pd.read_parquet(live_path)
        self.assertTrue(pd.isna(back.iloc[0]["Nájezd (km)"]))
        self.assertTrue(back.iloc[1]["Typ motoru"] is None or pd.isna(back.iloc[1]["Typ motoru"]))
        self.assertEqual(back.iloc[0]["Cena (Kč)"], 599000.0)
        # "Objem motoru" is numeric in the grid (toFixed) — a string here crashed the UI
        self.assertEqual(back.iloc[0]["Objem motoru"], 1.5)


class LoadScraperDataTest(unittest.TestCase):
    def test_reads_parquet_state_and_masks_blanks_to_nan(self):
        import tempfile
        from pathlib import Path
        from scrapers.core import storage
        with tempfile.TemporaryDirectory() as td:
            storage.write_state(pd.DataFrame(
                [{"Typ": "Elektrické", "Model auta": "X", "Stav": "",
                  "Odkaz na auto": "https://x/1"}]), Path(td) / "sauto")
            df = B.load_scraper_data(scrapes_dir=td)
        self.assertEqual(len(df), 1)
        self.assertTrue(pd.isna(df.iloc[0]["Stav"]))  # "" → NaN, read_csv parity


class ScrapeHistorySeedTest(unittest.TestCase):
    def test_seed_used_when_history_missing(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            seed = os.path.join(td, "seed.json")
            hist = os.path.join(td, "history.json")
            with open(seed, "w", encoding="utf-8") as f:
                json.dump([{"date": "2026-01-01", "total": 5}], f)
            meta = {"buildDate": "2026-07-04T00:00:00Z", "trigger": "manual",
                    "sources": {}, "matching": {}, "totalCars": 7}
            B.update_scrape_history(meta, history_path=hist, seed_path=seed)
            with open(hist, encoding="utf-8") as f:
                out = json.load(f)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["total"], 5)
        self.assertEqual(out[1]["total"], 7)


class ElectricReferenceJoinTest(unittest.TestCase):
    def test_prefix_match_is_case_insensitive(self):
        # Listing 'MINI Cooper SE' must match reference 'Mini Cooper SE'.
        out = B.join_electric_reference(_ev_df("MINI Cooper SE"), _ev_ref())
        row = out[out["Model auta"] == "MINI Cooper SE"].iloc[0]
        self.assertEqual(row["Spárováno"], "Ano")
        self.assertEqual(row["Kapacita baterie (kWh)"], 49.2)

    def test_same_case_still_matches(self):
        out = B.join_electric_reference(_ev_df("Mini Cooper SE Favoured"), _ev_ref())
        row = out.iloc[0]
        self.assertEqual(row["Spárováno"], "Ano")

    def test_non_prefix_stays_unmatched(self):
        out = B.join_electric_reference(_ev_df("Tesla Model 3"), _ev_ref())
        row = out.iloc[0]
        self.assertEqual(row["Spárováno"], "Ne")


class ElectricReferenceJoinAccentFoldTest(unittest.TestCase):
    """mobile.de strips diacritics ('Citroen e-C3') while other sources keep them
    ('Citroën ë-C3'); both spellings must pair to the SAME reference row."""

    def _citroen_ref(self):
        return pd.DataFrame([{
            "Model auta": "Citroën ë-C3",
            "Objem kufru (l)": 310,
            "Hlučnost (dB)": "",
            "Kapacita baterie (kWh)": 43.8,
            "Dojezd komb. letní WLTP (km)": 327,
            "Dojezd komb. letní EV-database (km)": "",
            "Cd": "",
            "Tepelné čerpadlo možné (ano/ne)": "ne",
        }])

    def test_accented_listing_matches(self):
        out = B.join_electric_reference(_ev_df("Citroën ë-C3 You"), self._citroen_ref())
        row = out.iloc[0]
        self.assertEqual(row["Spárováno"], "Ano")
        self.assertEqual(row["Kapacita baterie (kWh)"], 43.8)

    def test_diacritic_stripped_listing_matches_same_reference_row(self):
        # mobile.de-style spelling, no diacritics at all.
        out = B.join_electric_reference(_ev_df("Citroen e-C3 You"), self._citroen_ref())
        row = out.iloc[0]
        self.assertEqual(row["Spárováno"], "Ano")
        self.assertEqual(row["Kapacita baterie (kWh)"], 43.8)

    def test_both_spellings_pair_to_the_same_single_row(self):
        combined = pd.concat([
            _ev_df("Citroën ë-C3 You"),
            _ev_df("Citroen e-C3 You"),
        ], ignore_index=True)
        out = B.join_electric_reference(combined, self._citroen_ref())
        self.assertEqual(set(out["Spárováno"]), {"Ano"})
        self.assertEqual(out["Kapacita baterie (kWh)"].tolist(), [43.8, 43.8])


class ElectricModelAliasTest(unittest.TestCase):
    """GWM Ora 03 / ORA Funky Cat are the same physical car under two market
    names; ev_specs.csv keeps a single canonical row ("GWM Ora 03"). Freshly
    scraped rows are collapsed by normalize_model() at scrape time, but rows
    already sitting in state/seed CSVs from before that alias existed still
    carry the old spelling — fix_electric_model() re-normalizes at build time
    so both old and new rows pair to the one remaining reference row."""

    def _ora_ref(self):
        return pd.DataFrame([{
            "Model auta": "GWM Ora 03",
            "Objem kufru (l)": 228,
            "Hlučnost (dB)": "",
            "Kapacita baterie (kWh)": 45.4,
            "Dojezd komb. letní WLTP (km)": 310,
            "Dojezd komb. letní EV-database (km)": 260,
            "Cd": 0.33,
            "Tepelné čerpadlo možné (ano/ne)": "ano",
        }])

    def test_fix_electric_model_collapses_funky_cat_alias(self):
        self.assertEqual(B.fix_electric_model("ORA Funky Cat 48 kWh"), "GWM Ora 03 48 kWh")
        self.assertEqual(B.fix_electric_model("GWM Ora 03 48 kWh"), "GWM Ora 03 48 kWh")

    def test_both_spellings_pair_to_the_same_single_reference_row(self):
        combined = pd.concat([
            _ev_df("ORA Funky Cat 48 kWh"),
            _ev_df("GWM Ora 03 48 kWh"),
        ], ignore_index=True)
        combined["Model auta"] = combined["Model auta"].map(B.fix_electric_model)
        out = B.join_electric_reference(combined, self._ora_ref())
        self.assertEqual(set(out["Spárováno"]), {"Ano"})
        self.assertEqual(out["Kapacita baterie (kWh)"].tolist(), [45.4, 45.4])


if __name__ == "__main__":
    unittest.main()
