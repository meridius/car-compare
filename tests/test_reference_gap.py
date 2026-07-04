import os, sys, unittest
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

    def test_cluster_folds_diacritics_across_sources(self):
        listings = [
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Citroën ë-C3", "Odkaz na auto": "a"},
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Citroen e-C3", "Odkaz na auto": "b"},
        ]
        ev = rg.load_unpaired_from_rows(listings, "ev")
        clusters = rg.cluster(ev, "ev")
        self.assertEqual(len(clusters), 1)        # both spellings merge into one cluster
        self.assertEqual(clusters[0]["volume"], 2)


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
