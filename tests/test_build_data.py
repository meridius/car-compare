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


if __name__ == "__main__":
    unittest.main()
