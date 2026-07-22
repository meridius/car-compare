"""Tests for build-time reference joins (build/build_data.py).

Focused regression coverage for the electric prefix-join, which is case-sensitive
startswith by nature — listings arrive with inconsistent brand casing (e.g. sauto
emits 'MINI' while the reference is normalized to 'Mini'), so the join must fold
case or those cars silently go unmatched.
"""
import os
import sys
import unittest
from unittest import mock

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


class CanonicalizeBodyTest(unittest.TestCase):
    """Bug (Rodina report): the same model shows different Karoserie across its
    listings because sauto's per-listing vehicle_body_cb is seller-tagged and
    noisy (e.g. 17 Enyaq listings 'SUV', one 'Hatchback', one 'Terénní'). That
    breaks the body-type filter. canonicalize_body() overrides the minority
    outliers within an exact-'Model auta' group when one body is a strict
    majority; genuinely split groups (no majority) are left untouched."""

    def _df(self, rows):
        return pd.DataFrame(
            [{"Model auta": m, "Karoserie": b} for m, b in rows])

    def test_minority_outliers_overridden_to_majority(self):
        df = self._df(
            [("Škoda Enyaq iV 80", "SUV")] * 17
            + [("Škoda Enyaq iV 80", "Hatchback"),
               ("Škoda Enyaq iV 80", "Terénní")])
        out = B.canonicalize_body(df)
        self.assertEqual(set(out["Karoserie"]), {"SUV"})

    def test_blank_filled_from_majority(self):
        df = self._df(
            [("VW ID.4", "SUV"), ("VW ID.4", "SUV"), ("VW ID.4", "")])
        out = B.canonicalize_body(df)
        self.assertEqual(list(out["Karoserie"]), ["SUV", "SUV", "SUV"])

    def test_no_majority_left_untouched(self):
        df = self._df(
            [("X", "SUV"), ("X", "SUV"), ("X", "Sedan"), ("X", "Sedan")])
        out = B.canonicalize_body(df)
        self.assertEqual(list(out["Karoserie"]), ["SUV", "SUV", "Sedan", "Sedan"])

    def test_distinct_model_strings_not_cross_contaminated(self):
        df = self._df(
            [("Škoda Octavia", "Liftback"), ("Škoda Octavia", "Liftback"),
             ("Škoda Octavia Combi", "Kombi"), ("Škoda Octavia Combi", "Kombi")])
        out = B.canonicalize_body(df)
        self.assertEqual(
            list(out["Karoserie"]), ["Liftback", "Liftback", "Kombi", "Kombi"])


class DeriveTransmissionTypeTest(unittest.TestCase):
    """Task #26: 'Typ převodovky' is a derived payload column — finer than
    the existing 'Převodovka' (Automat/Manual) + 'Dvouspojková převodovka'
    (Ano/blank) pair, built purely from those two columns plus 'Typ' (no new
    canonical column, no new scrape-time data). Mirrors the classification
    site/transmissions.js already does client-side for its live counts."""

    def test_manual(self):
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "Manual", ""), "Manuální")

    def test_manual_czech_spelling(self):
        # sauto's gearbox_cb.name / mobile.de's German→Czech map already
        # write the long Czech form natively — autodraft is the only source
        # that writes the short "Manual" (see site/transmissions.js's
        # MANUAL_VALUES, which faces the identical inconsistency).
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "Manuální", ""), "Manuální")

    def test_automat_with_dsg_flag(self):
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "Automat", "Ano"),
            "Dvouspojková (DSG/DCT)")

    def test_automat_czech_spelling_with_dsg_flag(self):
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "Automatická", "Ano"),
            "Dvouspojková (DSG/DCT)")

    def test_automat_without_dsg_flag(self):
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "Automat", ""), "Automatická")

    def test_automat_czech_spelling_without_dsg_flag(self):
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "Automatická", ""), "Automatická")

    def test_electric_always_reduction_regardless_of_prevodovka(self):
        # EVs use a fixed single-speed reduction gear — always this value,
        # even if Převodovka/Dvouspojková happen to carry stray data.
        self.assertEqual(
            B.derive_transmission_type("Elektrické", "", ""), "Redukční (EV)")
        self.assertEqual(
            B.derive_transmission_type("Elektrické", "Automat", "Ano"),
            "Redukční (EV)")

    def test_blank_prevodovka_on_ice_is_blank(self):
        self.assertEqual(B.derive_transmission_type("Spalovací", "", ""), "")

    def test_unknown_prevodovka_value_is_blank(self):
        self.assertEqual(
            B.derive_transmission_type("Spalovací", "CVT", ""), "")


class AddTransmissionTypeColumnTest(unittest.TestCase):
    """add_transmission_type_column() applies derive_transmission_type()
    row-wise and inserts 'Typ převodovky' right after 'Dvouspojková
    převodovka' (payload display order)."""

    def test_adds_column_next_to_dct_flag(self):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Převodovka": "Manual", "Dvouspojková převodovka": "",
             "Model auta": "x"},
            {"Typ": "Spalovací", "Převodovka": "Automat", "Dvouspojková převodovka": "Ano",
             "Model auta": "y"},
            {"Typ": "Elektrické", "Převodovka": "", "Dvouspojková převodovka": "",
             "Model auta": "z"},
        ])
        out = B.add_transmission_type_column(df)
        self.assertEqual(
            list(out.columns).index("Typ převodovky"),
            list(out.columns).index("Dvouspojková převodovka") + 1,
        )
        self.assertEqual(list(out["Typ převodovky"]),
                          ["Manuální", "Dvouspojková (DSG/DCT)", "Redukční (EV)"])

    def test_missing_source_columns_is_a_noop(self):
        df = pd.DataFrame([{"Typ": "Spalovací", "Model auta": "x"}])
        out = B.add_transmission_type_column(df)
        self.assertNotIn("Typ převodovky", out.columns)


class ServiceCostTest(unittest.TestCase):
    """service_cost() (task #23): calibrated annual workshop-cost estimate,
    base(9000) × fuel × brand-tier × segment × engine, rounded to 500 Kč and
    clamped to [3000, 60000]. Pure — truth table pins every factor."""

    def _sc(self, typ, palivo, hybrid, znacka, karoserie, objem):
        return B.service_cost(typ, palivo, hybrid, znacka, karoserie, objem)[0]

    # Expected values pin the constants CALIBRATED 2026-07-22 against 20 real
    # models (ADAC Werkstattkosten → CZ + Czech garage data). base=12000.
    def test_petrol_mainstream_compact_is_base(self):
        self.assertEqual(self._sc("Spalovací", "Benzín", "", "VW", "Hatchback", "1.5"), "12000")

    def test_diesel_factor(self):
        # 12000 × 1.10 = 13200 → 13000
        self.assertEqual(self._sc("Spalovací", "Nafta", "", "Škoda", "Kombi", "2.0"), "13000")

    def test_premium_brand_tier(self):
        # 12000 × 1.25 = 15000
        self.assertEqual(self._sc("Spalovací", "Benzín", "", "BMW", "Sedan", "2.0"), "15000")

    def test_ev_is_cheap_even_when_premium(self):
        # 12000 × 0.35 × 1.25 = 5250 → 5000
        self.assertEqual(self._sc("Elektrické", "Elektro", "", "Tesla", "Sedan", ""), "5000")

    def test_ev_suv_mainstream(self):
        # 12000 × 0.35 × 1.10 = 4620 → 4500
        self.assertEqual(self._sc("Elektrické", "Elektro", "", "Škoda", "SUV", ""), "4500")

    def test_budget_brand_suv(self):
        # 12000 × 0.90 × 1.10 = 11880 → 12000
        self.assertEqual(self._sc("Spalovací", "Benzín", "", "Dacia", "SUV", "1.3"), "12000")

    def test_phev_hybrid_factor(self):
        # 12000 × 1.10 × 1.25 = 16500
        self.assertEqual(self._sc("Spalovací", "Benzín", "PHEV", "BMW", "Sedan", "2.0"), "16500")

    def test_hybrid_typ_wins_over_palivo(self):
        # MHEV multiplier (1.05) is used, not the underlying diesel (1.10)
        # 12000 × 1.05 × 1.25 = 15750 → 16000
        self.assertEqual(self._sc("Spalovací", "Nafta", "MHEV", "Audi", "Kombi", "2.0"), "16000")

    def test_large_engine_and_suv(self):
        # 12000 × 1.10 (SUV) × 1.10 (>2.0) = 14520 → 14500
        self.assertEqual(self._sc("Spalovací", "Benzín", "", "VW", "SUV", "3.0"), "14500")

    def test_small_engine(self):
        # 12000 × 0.95 = 11400 → 11500
        self.assertEqual(self._sc("Spalovací", "Benzín", "", "Škoda", "Hatchback", "1.0"), "11500")

    def test_lpg_substring_match(self):
        # 12000 × 1.05 = 12600 → 12500
        self.assertEqual(self._sc("Spalovací", "LPG + Benzín", "", "Škoda", "Sedan", "1.6"), "12500")

    def test_ev_overrides_missing_palivo(self):
        # 12000 × 0.35 × 0.90 = 3780 → 4000
        self.assertEqual(self._sc("Elektrické", "", "", "Dacia", "Hatchback", ""), "4000")

    def test_blank_when_no_fuel_signal(self):
        val, clamped = B.service_cost("Spalovací", "", "", "VW", "Sedan", "2.0")
        self.assertEqual(val, "")
        self.assertFalse(clamped)

    def test_garbage_engine_volume_does_not_explode(self):
        # sauto's 14.9 l garbage: engine factor is binned (>2.0 → 1.10), so it
        # only nudges one bin (12000·1.10 = 13200 → 13000), never blows up.
        self.assertEqual(self._sc("Spalovací", "Benzín", "", "VW", "Sedan", "14.9"), "13000")

    def test_round_and_clamp_low(self):
        self.assertEqual(B._round_and_clamp_service(2000), (3000, True))

    def test_round_and_clamp_high(self):
        self.assertEqual(B._round_and_clamp_service(70000), (60000, True))

    def test_round_and_clamp_within_bounds(self):
        self.assertEqual(B._round_and_clamp_service(9000), (9000, False))

    def test_clamp_boundaries_not_flagged(self):
        self.assertEqual(B._round_and_clamp_service(3000), (3000, False))
        self.assertEqual(B._round_and_clamp_service(60000), (60000, False))


class AddServiceCostColumnTest(unittest.TestCase):
    """add_service_cost_column() inserts 'Servis (Kč/rok)' right after
    'Spolehlivost' and covers every EV + ICE row that has a fuel signal."""

    def test_inserted_after_spolehlivost(self):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Spolehlivost": "4", "Značka": "VW",
             "Palivo": "Benzín", "Hybrid typ": "", "Karoserie": "Hatchback",
             "Objem motoru": "1.5"},
        ])
        out = B.add_service_cost_column(df)
        self.assertEqual(
            list(out.columns).index("Servis (Kč/rok)"),
            list(out.columns).index("Spolehlivost") + 1,
        )
        self.assertEqual(list(out["Servis (Kč/rok)"]), ["12000"])

    def test_covers_ev_ice_and_blanks_when_no_fuel(self):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Značka": "Škoda", "Palivo": "Nafta",
             "Hybrid typ": "", "Karoserie": "Kombi", "Objem motoru": "2.0"},
            {"Typ": "Elektrické", "Značka": "Tesla", "Palivo": "Elektro",
             "Hybrid typ": "", "Karoserie": "Sedan", "Objem motoru": ""},
            {"Typ": "Spalovací", "Značka": "VW", "Palivo": "",
             "Hybrid typ": "", "Karoserie": "Sedan", "Objem motoru": ""},
        ])
        out = B.add_service_cost_column(df)
        self.assertEqual(list(out["Servis (Kč/rok)"]), ["13000", "5000", ""])

    def test_znacka_derived_from_model_auta_when_no_znacka_column(self):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Model auta": "BMW 320i 2.0 TSI",
             "Palivo": "Benzín", "Hybrid typ": "", "Karoserie": "Sedan",
             "Objem motoru": "2.0"},
        ])
        out = B.add_service_cost_column(df)
        self.assertEqual(list(out["Servis (Kč/rok)"]), ["15000"])

    def test_noop_without_typ(self):
        df = pd.DataFrame([{"Model auta": "x"}])
        out = B.add_service_cost_column(df)
        self.assertNotIn("Servis (Kč/rok)", out.columns)

    def test_count_clamped_listings_zero_on_normal_data(self):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Značka": "VW", "Palivo": "Benzín",
             "Hybrid typ": "", "Karoserie": "Hatchback", "Objem motoru": "1.5"},
        ])
        self.assertEqual(B.count_service_clamped_listings(df), 0)


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


class JSONFormatTest(unittest.TestCase):
    """Task #15: JSON files should have static order of lines for cleaner diffs.

    - Multi-line with indent=2 (not single-line blobs)
    - Czech text readable (ensure_ascii=False)
    - Deterministic key order (sort_keys=True for dicts)
    - For lists of objects, sorted by a stable key
    """

    def test_reference_json_multi_line_and_sorted(self):
        """reference.json should be multi-line with entries sorted by Model auta."""
        import tempfile
        import json

        # Create sample reference data: unsorted by Model auta
        comb_ref = pd.DataFrame([
            {"Jednoznačná varianta vozu": "Škoda Karoq 1.5 TSI", "Spotřeba (l/100 km)": 5.5},
            {"Jednoznačná varianta vozu": "Alfa Romeo Tonale 1.5", "Spotřeba (l/100 km)": 6.0},
        ])
        elec_ref = pd.DataFrame([
            {"Model auta": "Tesla Model 3", "Kapacita baterie (kWh)": 75.0},
            {"Model auta": "BYD Dolphin", "Kapacita baterie (kWh)": 44.9},
        ])
        df = pd.DataFrame([])  # empty cars for this test

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "reference.json")
            # Patch the output path
            original_build = B.build_reference_json
            def patched_build(comb_ref, elec_ref, df):
                records = []
                # Simple minimal records for testing
                for _, row in comb_ref.iterrows():
                    model = row.get("Jednoznačná varianta vozu", "")
                    rec = {"Model auta": model, "Typ": "Spalovací"}
                    records.append(rec)
                for _, row in elec_ref.iterrows():
                    model = row.get("Model auta", "")
                    rec = {"Model auta": model, "Typ": "Elektrické"}
                    records.append(rec)
                # Sort by Model auta for deterministic output (mimics build_reference_json)
                records.sort(key=lambda r: r.get("Model auta", ""))
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
                return records

            B.build_reference_json = patched_build
            try:
                B.build_reference_json(comb_ref, elec_ref, df)

                # Verify multi-line (not a single line)
                with open(out_path, "r", encoding="utf-8") as f:
                    content = f.read()
                lines = content.strip().split("\n")
                self.assertGreater(len(lines), 5, "JSON should be multi-line")

                # Verify indent=2 (lines start with spaces or brackets)
                for line in lines[1:]:
                    if line.startswith("}") or line.startswith("]"):
                        continue
                    if line.strip():
                        spaces = len(line) - len(line.lstrip())
                        self.assertTrue(
                            spaces % 2 == 0,
                            f"Line should be indented by 2: {line!r}"
                        )

                # Verify it's valid JSON
                data = json.loads(content)
                self.assertIsInstance(data, list)

                # Verify entries are sorted by Model auta
                if len(data) > 1:
                    models = [rec.get("Model auta", "") for rec in data]
                    self.assertEqual(models, sorted(models),
                        "Records should be sorted by 'Model auta'")

                # Verify idempotency: running twice produces identical output
                with open(out_path, "r", encoding="utf-8") as f:
                    first_run = f.read()

                B.build_reference_json(comb_ref, elec_ref, df)
                with open(out_path, "r", encoding="utf-8") as f:
                    second_run = f.read()

                self.assertEqual(first_run, second_run,
                    "JSON output should be byte-identical on repeated runs")
            finally:
                B.build_reference_json = original_build

    def test_cars_meta_json_multi_line_and_sorted_keys(self):
        """cars-meta.json should be multi-line with sorted keys."""
        import tempfile
        import json

        metadata = {
            "totalCars": 100,
            "buildDate": "2026-07-05T12:00:00Z",
            "trigger": "manual",
            "sources": {"sauto": {"total": 50}},
            "matching": {"combustion": {"total": 30}},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "cars-meta.json")

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2, sort_keys=True)

            # Verify multi-line
            with open(out_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.strip().split("\n")
            self.assertGreater(len(lines), 3, "JSON should be multi-line")

            # Verify indent=2
            for line in lines[1:]:
                if line.startswith("}"):
                    continue
                if line.strip():
                    spaces = len(line) - len(line.lstrip())
                    self.assertTrue(spaces % 2 == 0, f"Should be indented by 2: {line!r}")

            # Verify valid JSON
            data = json.loads(content)
            self.assertIsInstance(data, dict)

            # Verify idempotency
            with open(out_path, "r", encoding="utf-8") as f:
                first_run = f.read()

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2, sort_keys=True)

            with open(out_path, "r", encoding="utf-8") as f:
                second_run = f.read()

            self.assertEqual(first_run, second_run,
                "JSON output should be byte-identical on repeated runs")

    def test_scrape_history_json_multi_line(self):
        """scrape_history.json should be multi-line (not single-line)."""
        import tempfile
        import json

        history = [
            {
                "date": "2026-07-04T06:00:00Z",
                "trigger": "schedule",
                "sources": {"sauto": {"total": 50}},
                "total": 150,
            },
            {
                "date": "2026-07-05T06:00:00Z",
                "trigger": "manual",
                "sources": {"sauto": {"total": 60}},
                "total": 160,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "scrape_history.json")

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

            # Verify multi-line
            with open(out_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.strip().split("\n")
            self.assertGreater(len(lines), 5, "JSON should be multi-line, not single line")

            # Verify indent=2
            for line in lines[1:]:
                if line.startswith("]") or line.startswith("}"):
                    continue
                if line.strip():
                    spaces = len(line) - len(line.lstrip())
                    self.assertTrue(spaces % 2 == 0, f"Should be indented by 2: {line!r}")

            # Verify valid JSON
            data = json.loads(content)
            self.assertIsInstance(data, list)
class ReliabilityScoreTest(unittest.TestCase):
    """Task #30: coarse "more cylinders + bigger displacement = more reliable"
    heuristic (owner's rule of thumb, NOT empirical reliability data). Cylinder
    count (#24) is populated for only a slice of sauto ICE rows today, so the
    score must degrade gracefully to a volume-only estimate when it's blank."""

    def test_small_engine_low_cylinder_count_scores_1(self):
        self.assertEqual(B.reliability_score(1.0, 3), "1")

    def test_volume_only_midsize_scores_3(self):
        self.assertEqual(B.reliability_score(1.5, ""), "3")

    def test_volume_only_two_liter_scores_4(self):
        self.assertEqual(B.reliability_score(2.0, None), "4")

    def test_big_engine_six_cylinders_scores_5(self):
        self.assertEqual(B.reliability_score(3.0, 6), "5")

    def test_blank_volume_scores_blank_regardless_of_cylinders(self):
        # The rule needs an engine to reason about; EV rows and any ICE row
        # missing displacement stay blank even if cylinders happen to be known.
        self.assertEqual(B.reliability_score("", 4), "")
        self.assertEqual(B.reliability_score(None, 4), "")

    def test_nan_volume_scores_blank(self):
        self.assertEqual(B.reliability_score(float("nan"), 4), "")

    def test_blend_rounds_up_from_volume_alone(self):
        # 1.0 l alone would score 1, but paired with 6 cylinders the blend
        # (volume=1, cylinders=5) averages to 3 -- cylinders can lift a small
        # engine's score, not just confirm a big one.
        self.assertEqual(B.reliability_score(1.0, 6), "3")

    def test_four_cylinders_component_is_3(self):
        # Volume component for 1.3l is 2; blended with 4-cyl (component 3)
        # averages to 2.5 -> rounds to 2 (Python banker's rounding: round(2.5)==2).
        self.assertEqual(B.reliability_score(1.3, 4), "2")

    def test_score_never_exceeds_bounds(self):
        for vol, cyl in [(0.1, 1), (0.1, 2), (10.0, 12)]:
            score = B.reliability_score(vol, cyl)
            self.assertIn(score, {"1", "2", "3", "4", "5"})

    def test_add_reliability_column_ice_only(self):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Objem motoru": 2.0, "Počet válců": ""},
            {"Typ": "Elektrické", "Objem motoru": "", "Počet válců": ""},
        ])
        out = B.add_reliability_column(df)
        self.assertEqual(out.loc[0, "Spolehlivost"], "4")
        self.assertEqual(out.loc[1, "Spolehlivost"], "")

    def test_add_reliability_column_positioned_after_pocet_valcu(self):
        df = pd.DataFrame([{"Typ": "Spalovací", "Objem motoru": 1.5, "Počet válců": ""}])
        out = B.add_reliability_column(df)
        cols = list(out.columns)
        self.assertEqual(cols.index("Spolehlivost"), cols.index("Počet válců") + 1)


def _auth_entry(entry, trim):
    return {"entry": entry, "brand": "", "model_base": "", "body": "", "engine_vol": "",
            "engine_type": "", "hybrid": "", "fuel": "", "trim": trim, "seats": ""}


class ApplyVerzeDisplayTest(unittest.TestCase):
    """apply_verze_display() is the payload-time overwrite: the displayed
    'Verze' comes only from a confidently-matched (Spárováno == 'Ano') ICE
    reference row's trim — never the scrape-extracted value, and never for
    EV (no trim concept) or weak/unmatched ICE matches."""

    def test_confident_ice_match_gets_reference_trim(self):
        df = pd.DataFrame([{
            "Typ": "Spalovací", "Model auta": "Škoda Octavia Combi Style 1.5 TSI",
            "Spárováno": "Ano",
        }])
        with mock.patch.object(
            B.comb_utils, "load_authoritative_list",
            return_value=[_auth_entry("Škoda Octavia Combi Style 1.5 TSI", "Style")],
        ):
            out = B.apply_verze_display(df)
        self.assertEqual(out.iloc[0]["Verze"], "Style")

    def test_uncertain_ice_match_is_blanked(self):
        df = pd.DataFrame([{
            "Typ": "Spalovací", "Model auta": "Škoda Octavia Combi Style 1.5 TSI",
            "Spárováno": "Nejisté",
        }])
        with mock.patch.object(
            B.comb_utils, "load_authoritative_list",
            return_value=[_auth_entry("Škoda Octavia Combi Style 1.5 TSI", "Style")],
        ):
            out = B.apply_verze_display(df)
        self.assertEqual(out.iloc[0]["Verze"], "")

    def test_unmatched_ice_is_blanked(self):
        df = pd.DataFrame([{
            "Typ": "Spalovací", "Model auta": "Opel Mokka 1.2 Turbo", "Spárováno": "Ne",
        }])
        with mock.patch.object(B.comb_utils, "load_authoritative_list", return_value=[]):
            out = B.apply_verze_display(df)
        self.assertEqual(out.iloc[0]["Verze"], "")

    def test_ev_row_always_blanked_even_when_marked_ano(self):
        # EV rows are "matched" via a prefix join with no trim concept — never
        # show a reference trim on an EV row even if Spárováno somehow says Ano.
        df = pd.DataFrame([{
            "Typ": "Elektrické", "Model auta": "Škoda Enyaq iV 80", "Spárováno": "Ano",
        }])
        with mock.patch.object(
            B.comb_utils, "load_authoritative_list",
            return_value=[_auth_entry("Škoda Enyaq iV 80", "Should never show")],
        ):
            out = B.apply_verze_display(df)
        self.assertEqual(out.iloc[0]["Verze"], "")

    def test_empty_df_is_a_noop(self):
        df = pd.DataFrame(columns=["Typ", "Model auta", "Spárováno"])
        out = B.apply_verze_display(df)
        self.assertIn("Verze", out.columns)
        self.assertEqual(len(out), 0)


class ExtractEvExtraSpecsTest(unittest.TestCase):
    def _row(self, typ, extra, battery="", verze=""):
        return {"Typ": typ, "Extra": extra,
                "Kapacita baterie (kWh)": battery, "Verze": verze}

    def test_listing_battery_overrides_reference(self):
        df = pd.DataFrame([self._row(
            "Elektrické", "Oldenburg / Baterie 43 kWh / Dolphin Surf 43kWh Boost",
            battery=30.0)])  # reference nominal 30
        out = B.extract_ev_extra_specs(df)
        self.assertEqual(float(out.iloc[0]["Kapacita baterie (kWh)"]), 43.0)
        self.assertEqual(out.iloc[0]["Verze"], "Boost")

    def test_absent_battery_keeps_reference(self):
        df = pd.DataFrame([self._row(
            "Elektrické", "LED*KLIMA*ACC", battery=58.0)])
        out = B.extract_ev_extra_specs(df)
        self.assertEqual(float(out.iloc[0]["Kapacita baterie (kWh)"]), 58.0)
        self.assertEqual(out.iloc[0]["Verze"], "")

    def test_ice_rows_untouched(self):
        df = pd.DataFrame([self._row(
            "Spalovací", "Baterie 43 kWh / Comfort", battery="", verze="Style")])
        out = B.extract_ev_extra_specs(df)
        self.assertEqual(out.iloc[0]["Verze"], "Style")       # ICE Verze preserved
        self.assertEqual(out.iloc[0]["Kapacita baterie (kWh)"], "")  # not populated

    def test_edition_only_no_battery(self):
        df = pd.DataFrame([self._row(
            "Elektrické", "Suhl / 55 Essence LED", battery=55.0)])
        out = B.extract_ev_extra_specs(df)
        self.assertEqual(float(out.iloc[0]["Kapacita baterie (kWh)"]), 55.0)
        self.assertEqual(out.iloc[0]["Verze"], "Essence")

    def test_arrow_null_extra_does_not_crash(self):
        # Regression: on the full dataset the Extra column is arrow-backed and
        # carries nulls, so .astype(str).map fed float NaN to parse_battery_kwh
        # and the CI build crashed (TypeError: expected string ... got 'float').
        df = pd.DataFrame([
            self._row("Elektrické", "Baterie 60 kWh / Comfort"),
            self._row("Elektrické", None),
        ])
        df["Extra"] = df["Extra"].astype("string[pyarrow]")
        out = B.extract_ev_extra_specs(df)               # must not raise
        self.assertEqual(float(out.iloc[0]["Kapacita baterie (kWh)"]), 60.0)
        self.assertEqual(out.iloc[0]["Verze"], "Comfort")
        self.assertEqual(out.iloc[1]["Kapacita baterie (kWh)"], "")
        self.assertEqual(out.iloc[1]["Verze"], "")


if __name__ == "__main__":
    unittest.main()
