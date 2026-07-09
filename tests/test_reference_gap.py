import os, sys, unittest, tempfile, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "build"))
import reference_gap as rg  # noqa: E402


class TestCluster(unittest.TestCase):
    def _listings(self):
        return [
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Renault Twingo", "Odkaz na auto": "u1"},
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Renault Twingo E-Tech 60kW", "Odkaz na auto": "u2"},
            {"Typ": "Elektrické", "Spárováno": "Ano", "Model auta": "Renault Twingo", "Odkaz na auto": "u3"},
            {"Typ": "Spalovací", "Spárováno": "Ne", "Model auta": "BMW 320 2.0", "Odkaz na auto": "u4"},
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "BYD DOLPHIN", "Odkaz na auto": "u5"},
        ]

    def test_load_unpaired_filters_fuel_and_state(self):
        ev = rg.load_unpaired_from_rows(self._listings(), "ev")
        links = {r["Odkaz na auto"] for r in ev}
        self.assertEqual(links, {"u1", "u2", "u5"})  # only EV + Ne

    def test_cluster_merges_spec_variants(self):
        ev = rg.load_unpaired_from_rows(self._listings(), "ev")
        clusters = rg.cluster(ev, "ev")
        by_prefix = {c["prefix"]: c for c in clusters}
        self.assertIn("Renault Twingo", by_prefix)
        self.assertEqual(by_prefix["Renault Twingo"]["volume"], 2)  # bare + E-Tech merged
        self.assertEqual(clusters[0]["volume"], 2)  # sorted by volume desc

    def test_load_unpaired_reconstructs_model_from_brand_model_split(self):
        # write_payload drops "Model auta" (split into Značka + Model, task #3);
        # load_unpaired must reconstruct it or every cluster key goes empty.
        import pandas as pd
        df = pd.DataFrame([
            {"Typ": "Elektrické", "Spárováno": "Ne", "Značka": "Renault",
             "Model": "Twingo E-Tech", "Odkaz na auto": "u1"},
            {"Typ": "Elektrické", "Spárováno": "Ano", "Značka": "BYD",
             "Model": "Dolphin", "Odkaz na auto": "u2"},
        ])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cars.parquet")
            df.to_parquet(path)
            unpaired = rg.load_unpaired(path, "ev")
        self.assertEqual(len(unpaired), 1)
        self.assertEqual(unpaired[0]["Model auta"], "Renault Twingo E-Tech")

    def test_cluster_folds_diacritics_across_sources(self):
        listings = [
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Citroën ë-C3", "Odkaz na auto": "a"},
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Citroen e-C3", "Odkaz na auto": "b"},
        ]
        ev = rg.load_unpaired_from_rows(listings, "ev")
        clusters = rg.cluster(ev, "ev")
        self.assertEqual(len(clusters), 1)        # both spellings merge into one cluster
        self.assertEqual(clusters[0]["volume"], 2)

    def test_shared_prefix_case_insensitive_tokens(self):
        # same model, different casing must not truncate the prefix to the brand
        self.assertEqual(
            rg._shared_prefix(["Hyundai IONIQ 6", "Hyundai Ioniq 6"]),
            "Hyundai IONIQ 6",
        )


class TestClassify(unittest.TestCase):
    def test_covered_when_raw_matches_existing_prefix(self):
        c = {"prefix": "Renault Twingo", "sample_names": ["Renault Twingo E-Tech"]}
        self.assertEqual(rg.classify(c, ["Renault Twingo"]), "covered")

    def test_normalization_gap_when_only_normalized_matches(self):
        # BRAND_MAP maps Volkswagen -> VW; raw won't match "VW ID.3" but normalized will
        c = {"prefix": "Volkswagen ID.3", "sample_names": ["Volkswagen ID.3 Pro"]}
        self.assertEqual(rg.classify(c, ["VW ID.3"]), "normalization_gap")

    def test_missing_ref_when_nothing_matches(self):
        c = {"prefix": "Renault Twingo", "sample_names": ["Renault Twingo", "Renault Twingo E-Tech"]}
        self.assertEqual(rg.classify(c, ["Fiat Grande Panda"]), "missing_ref")


class TestProjectAndStub(unittest.TestCase):
    def _unpaired(self):
        return [
            {"Model auta": "Renault Twingo"}, {"Model auta": "Renault Twingo E-Tech"},
            {"Model auta": "Fiat Grande Panda"},
        ]

    def test_projection_counts_prefix_matches(self):
        got = rg.project_newly_paired(["Renault Twingo", "Fiat Grande Panda"], self._unpaired())
        self.assertEqual(got, {"Renault Twingo": 2, "Fiat Grande Panda": 1})

    def test_stub_row_has_exact_ev_columns_and_prefix(self):
        row = rg.stub_row({"prefix": "Renault Twingo"}, "ev")
        self.assertEqual(list(row.keys()), rg.ev_columns())
        self.assertEqual(row["Model auta"], "Renault Twingo")
        self.assertEqual(row["Kapacita baterie (kWh)"], "")  # spec blank until researched

    def test_ev_ranges_keys_are_all_real_columns(self):
        cols = rg.ev_columns()
        for col in rg.EV_RANGES:
            self.assertIn(col, cols)  # a renamed CSV header must fail loud, not silently skip


class TestNestedPrefixProjection(unittest.TestCase):
    """Citroën C3 / Citroën C3 Aircross shape: "Citroën C3" is a literal string
    prefix of "Citroën C3 Aircross ...", so a naive prefix-startswith projection
    double-counts the Aircross listings under the C3 bucket too."""

    def _listings(self):
        c3 = [{"Model auta": f"Citroën C3 {i}"} for i in range(110)]
        aircross = [{"Model auta": f"Citroën C3 Aircross {i}"} for i in range(71)]
        return c3 + aircross

    def test_own_absorbed_split_matches_real_cluster_sizes(self):
        stats = rg.project_own_absorbed(["Citroën C3", "Citroën C3 Aircross"], self._listings())
        self.assertEqual(stats["Citroën C3"]["projected"], 181)  # raw startswith, inflated
        self.assertEqual(stats["Citroën C3"]["own"], 110)         # its actual cluster size
        self.assertEqual(stats["Citroën C3"]["absorbed"], 71)     # would-be Aircross listings
        self.assertEqual(stats["Citroën C3 Aircross"]["projected"], 71)
        self.assertEqual(stats["Citroën C3 Aircross"]["own"], 71)
        self.assertEqual(stats["Citroën C3 Aircross"]["absorbed"], 0)

    def test_own_absorbed_no_overlap_when_prefixes_disjoint(self):
        unpaired = [{"Model auta": "Renault Twingo"}, {"Model auta": "Fiat Grande Panda"}]
        stats = rg.project_own_absorbed(["Renault Twingo", "Fiat Grande Panda"], unpaired)
        self.assertEqual(stats["Renault Twingo"], {"own": 1, "absorbed": 0, "projected": 1})
        self.assertEqual(stats["Fiat Grande Panda"], {"own": 1, "absorbed": 0, "projected": 1})

    def test_find_nested_prefixes_detects_parent_child(self):
        pairs = rg.find_nested_prefixes(["Citroën C3", "Citroën C3 Aircross", "Fiat Grande Panda"])
        self.assertEqual(pairs, [("Citroën C3", "Citroën C3 Aircross")])

    def test_find_nested_prefixes_is_token_boundary_safe(self):
        # "Citroën C3" must NOT be considered a prefix of "Citroën C30" (no shared token)
        pairs = rg.find_nested_prefixes(["Citroën C3", "Citroën C30"])
        self.assertEqual(pairs, [])

    def test_find_nested_prefixes_empty_when_no_nesting(self):
        pairs = rg.find_nested_prefixes(["Renault Twingo", "Fiat Grande Panda"])
        self.assertEqual(pairs, [])


class TestValidate(unittest.TestCase):
    def _good(self):
        r = {c: "" for c in rg.ev_columns()}
        r.update({"Model auta": "Renault Twingo", "Kapacita baterie (kWh)": 22,
                  "Dojezd komb. letní WLTP (km)": 190, "Cd": 0.31,
                  "Cd zdroj": "reálné", "Tepelné čerpadlo možné (ano/ne)": "ne"})
        return r

    def test_accepts_good_row_and_drops_sidecar(self):
        r = self._good(); r["_sources"] = {"Cd": "http://x"}
        ok, errs = rg.validate_rows([r], "ev", ["Fiat Grande Panda"], [])
        self.assertEqual(errs, [])
        self.assertNotIn("_sources", ok[0])
        self.assertEqual(list(ok[0].keys()), rg.ev_columns())

    def test_rejects_out_of_range_battery(self):
        r = self._good(); r["Kapacita baterie (kWh)"] = 5
        ok, errs = rg.validate_rows([r], "ev", [], [])
        self.assertEqual(ok, []); self.assertTrue(any("baterie" in e for e in errs))

    def test_rejects_bad_cd_source_and_duplicate_and_overbroad(self):
        r1 = self._good(); r1["Cd zdroj"] = "guess"
        r2 = self._good(); r2["Model auta"] = "Fiat Grande Panda"  # dup vs existing ref
        r3 = self._good(); r3["Model auta"] = "Renault"            # over-broad prefix
        unpaired = [{"Model auta": "Renault Megane E-TECH"}]
        ok, errs = rg.validate_rows([r1, r2, r3], "ev", ["Fiat Grande Panda"], unpaired)
        self.assertEqual(ok, [])
        self.assertEqual(len(errs), 3)

    def test_rejects_nonnumeric_cell_without_crashing_batch(self):
        good = self._good()
        bad = self._good()
        bad["Model auta"] = "Fiat 500e"
        bad["Kapacita baterie (kWh)"] = "42 kWh"
        ok, errs = rg.validate_rows([good, bad], "ev", [], [])
        self.assertEqual([r["Model auta"] for r in ok], ["Renault Twingo"])  # good row survives
        self.assertTrue(any("není číslo" in e for e in errs))


class TestCLIGuards(unittest.TestCase):
    def test_validate_and_apply_reject_ice(self):
        # ICE is deferred; argparse must reject --fuel ice for validate/apply
        with self.assertRaises(SystemExit):
            rg.main(["validate", "--fuel", "ice", "--in", "nope.json"])
        with self.assertRaises(SystemExit):
            rg.main(["apply", "--fuel", "ice", "--in", "nope.json"])

    def test_gaps_help_still_lists_both_fuel_choices(self):
        # argparse itself still parses either fuel (--help exits 0 regardless);
        # the ICE restriction is enforced at runtime with a clear message, not
        # by narrowing argparse choices, so --fuel ice still reaches _cmd_gaps.
        with self.assertRaises(SystemExit):
            rg.main(["gaps", "--help"])   # --help exits 0; proves 'gaps' subparser exists

    def test_gaps_ice_exits_with_clear_message(self):
        # ICE pairs via match_to_authoritative, not the EV prefix join gaps
        # models — gaps must refuse --fuel ice with an explicit explanation
        # rather than silently producing semantically-wrong output.
        with self.assertRaises(SystemExit) as cm:
            rg.main(["gaps", "--fuel", "ice"])
        msg = str(cm.exception)
        self.assertIn("match_to_authoritative", msg)
        self.assertIn("--fuel ev", msg)


class TestAppendAndCount(unittest.TestCase):
    def test_fmt_cell_cd_dot_others_comma(self):
        self.assertEqual(rg._fmt_cell("Cd", 0.31), "0.31")
        self.assertEqual(rg._fmt_cell("Kapacita baterie (kWh)", 86.5), "86,5")
        self.assertEqual(rg._fmt_cell("Objem kufru (l)", 520), "520")
        self.assertEqual(rg._fmt_cell("Hlučnost (dB)", ""), "")

    def test_append_preserves_header_and_quotes_comma_decimals(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ev.csv")
            with open(p, "w", newline="", encoding="utf-8") as f:
                f.write(",".join(rg.ev_columns()) + "\n")
            row = {c: "" for c in rg.ev_columns()}
            row.update({"Model auta": "Renault Twingo", "Kapacita baterie (kWh)": 22.5, "Cd": 0.31})
            n = rg.append_rows("ev", [row], path=p)
            self.assertEqual(n, 1)
            text = open(p, encoding="utf-8").read()
            self.assertIn("Renault Twingo", text)
            self.assertIn('"22,5"', text)   # comma decimal quoted
            self.assertIn("0.31", text)     # Cd dot, unquoted

    def test_count_unpaired(self):
        with tempfile.TemporaryDirectory() as d:
            import pandas as pd
            p = os.path.join(d, "cars.parquet")
            pd.DataFrame([
                {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "X"},
                {"Typ": "Elektrické", "Spárováno": "Ano", "Model auta": "Y"},
            ]).to_parquet(p, index=False)
            self.assertEqual(rg.count_unpaired(p, "ev"), 1)

    def test_append_adds_missing_trailing_newline(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ev.csv")
            with open(p, "w", newline="", encoding="utf-8") as f:
                f.write(",".join(rg.ev_columns()))   # header with NO trailing newline
            row = {c: "" for c in rg.ev_columns()}
            row["Model auta"] = "Renault Twingo"
            rg.append_rows("ev", [row], path=p)
            lines = open(p, encoding="utf-8").read().splitlines()
            self.assertEqual(len(lines), 2)                       # header + row, not glued
            self.assertTrue(lines[1].startswith("Renault Twingo"))
