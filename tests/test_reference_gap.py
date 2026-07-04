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
