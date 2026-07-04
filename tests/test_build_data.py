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


class PayloadWriterTest(unittest.TestCase):
    """Pins site/data/cars.parquet + cars-meta.json contract (see decision 001).

    Numeric columns must be float64 — pyarrow int64 decodes to BigInt in
    hyparquet and breaks the grid. Blanks must arrive as null, not "".
    """

    def _write(self, td):
        df = pd.DataFrame([
            {"Typ": "Spalovací", "Model auta": "Škoda Karoq 1.5 TSI",
             "Cena (Kč)": "599000", "Nájezd (km)": "", "Typ motoru": "TSI",
             "Objem motoru": "1.5", "Odkaz na auto": "https://x/1"},
            {"Typ": "Elektrické", "Model auta": "Tesla Model 3",
             "Cena (Kč)": "888000", "Nájezd (km)": "12000", "Typ motoru": "",
             "Objem motoru": "", "Odkaz na auto": "https://x/2"},
        ])
        meta = {"buildDate": "2026-07-04T00:00:00Z", "trigger": "manual",
                "sources": {}, "matching": {}, "referenceData": {}, "totalCars": 2}
        return B.write_payload(df, meta, td)

    def test_writes_parquet_and_meta_sidecar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            parquet_path, meta_path = self._write(td)
            self.assertTrue(os.path.exists(parquet_path))
            self.assertTrue(parquet_path.endswith("cars.parquet"))
            import json
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        self.assertEqual(
            set(meta),
            {"buildDate", "trigger", "sources", "matching", "referenceData", "totalCars"},
        )

    def test_no_int64_columns_in_payload(self):
        import tempfile
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as td:
            parquet_path, _ = self._write(td)
            schema = pq.read_schema(parquet_path)
        for field in schema:
            self.assertNotIn("int64", str(field.type),
                             f"{field.name} is int64 → BigInt in hyparquet")

    def test_blanks_become_null_not_empty_string(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            parquet_path, _ = self._write(td)
            back = pd.read_parquet(parquet_path)
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


if __name__ == "__main__":
    unittest.main()
