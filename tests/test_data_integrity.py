"""Data-integrity invariants over the built dashboard data (site/data/cars.json).

This is the regression net for task #21: it asserts that the served data stays
internally consistent and that the matcher never relapses into the old
"99.8% matched" over-confidence. Builds cars.json once if missing, then runs
offline in well under a second.
"""
import datetime
import collections
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scrapers.core import bodies as _bodies  # noqa: E402
from scrapers.core.schema import CANONICAL_COLS  # noqa: E402
from scrapers.core.matching import load_authoritative_list  # noqa: E402
from build.build_data import strip_ice_engine_tokens  # noqa: E402

CARS_PARQUET = os.path.join(ROOT, "site", "data", "cars.parquet")
CARS_META = os.path.join(ROOT, "site", "data", "cars-meta.json")
REFERENCE_JSON = os.path.join(ROOT, "site", "data", "reference.json")
ICE_SPECS_CSV = os.path.join(ROOT, "scrapers", "data", "reference", "ice_specs.csv")

import re as _re
_ISO_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def setUpModule():
    if not os.path.exists(CARS_PARQUET):
        subprocess.run([sys.executable, os.path.join(ROOT, "build", "build_data.py")],
                       check=True, cwd=ROOT)


def _records(path):
    """Parquet rows as dicts with NaN mapped to None (JSON-record parity)."""
    import pandas as pd
    df = pd.read_parquet(path)
    return [
        {k: (None if (isinstance(v, float) and v != v) else v) for k, v in rec.items()}
        for rec in df.to_dict("records")
    ]


def _name(car):
    """Diagnostic display name for a payload row (task #3: the payload no
    longer carries 'Model auta' — it's split into 'Značka' + 'Model')."""
    return f"{car.get('Značka') or ''} {car.get('Model') or ''}".strip()


class ReferenceDateColumnsTest(unittest.TestCase):
    """Every reference.json row must carry valid yyyy-mm-dd Přidáno + Upraveno,
    and Přidáno must never be after Upraveno."""

    @classmethod
    def setUpClass(cls):
        with open(REFERENCE_JSON, encoding="utf-8") as f:
            cls.rows = json.load(f)
        cls.assertTrue(cls.rows, "reference.json is empty")

    def test_both_date_cols_present_and_iso(self):
        for col in ("Přidáno", "Upraveno"):
            bad = [r for r in self.rows if not _ISO_DATE_RE.match(str(r.get(col) or ""))]
            self.assertEqual(bad, [], f"{len(bad)} rows have non-ISO {col} "
                             f"(e.g. {bad[0].get('Model auta') if bad else ''})")

    def test_pridano_not_after_upraveno(self):
        bad = [r for r in self.rows if str(r.get("Přidáno")) > str(r.get("Upraveno"))]
        self.assertEqual(bad, [], f"{len(bad)} rows have Přidáno after Upraveno")


class ListingDateColumnsTest(unittest.TestCase):
    """The listing payload carries Přidáno/Upraveno (may be blank per row, unlike
    the reference), and where both are set Přidáno must not be after Upraveno."""

    @classmethod
    def setUpClass(cls):
        cls.rows = _records(CARS_PARQUET)
        cls.assertTrue(cls.rows, "cars.parquet is empty")

    def test_both_date_columns_present(self):
        sample = self.rows[0]
        self.assertIn("Přidáno", sample)
        self.assertIn("Upraveno", sample)

    def test_set_dates_are_iso(self):
        for col in ("Přidáno", "Upraveno"):
            bad = [r for r in self.rows
                   if r.get(col) and not _ISO_DATE_RE.match(str(r[col]))]
            self.assertEqual(bad, [], f"{len(bad)} rows have non-ISO {col}")

    def test_pridano_not_after_upraveno(self):
        bad = [r for r in self.rows
               if r.get("Přidáno") and r.get("Upraveno")
               and str(r["Přidáno"]) > str(r["Upraveno"])]
        self.assertEqual(bad, [], f"{len(bad)} listings have Přidáno after Upraveno")


class ReferencePriceAggregatesTest(unittest.TestCase):
    """Per-reference "spárované vozy & rozpětí cen" aggregate (build_data
    build_*_price_aggs → reference.json): count, price stats, fixed-axis histogram
    and cheapest/dearest links must be internally consistent and feed the
    reference page's "Nabídek" / "Cena na trhu" columns."""

    HIST_BINS = 14  # mirrors build_data.PRICE_HIST_BINS

    @classmethod
    def setUpClass(cls):
        with open(REFERENCE_JSON, encoding="utf-8") as f:
            cls.rows = json.load(f)
        cls.assertTrue(cls.rows, "reference.json is empty")
        cls.priced = [r for r in cls.rows if r.get("Nabídek")]

    def test_every_row_has_count_and_histogram_fields(self):
        for key in ("Nabídek", "Cena histogram"):
            missing = [r.get("Model auta") for r in self.rows if key not in r]
            self.assertEqual(missing, [], f"{len(missing)} rows missing '{key}'")
        bad = [r.get("Model auta") for r in self.rows
               if not isinstance(r["Nabídek"], int) or r["Nabídek"] < 0]
        self.assertEqual(bad, [], f"{len(bad)} rows have a non-int/negative Nabídek")

    def test_some_rows_are_paired(self):
        # Total wiring break (0 populated) is the real failure this guards against;
        # a seed-only build still pairs plenty, real state pairs ~579/622.
        self.assertGreater(len(self.priced), 50,
                           f"only {len(self.priced)} reference rows have any paired listings")

    def test_histogram_sums_to_count(self):
        offenders = []
        for r in self.priced:
            h = r["Cena histogram"]
            if not isinstance(h, list) or len(h) != self.HIST_BINS or sum(h) != r["Nabídek"]:
                offenders.append((r.get("Model auta"), len(h) if isinstance(h, list) else None,
                                  sum(h) if isinstance(h, list) else None, r["Nabídek"]))
        self.assertEqual(offenders, [], f"{len(offenders)} rows: histogram len!=14 or sum!=Nabídek "
                         f"(e.g. {offenders[0] if offenders else ''})")

    def test_price_stats_monotonic(self):
        offenders = []
        for r in self.priced:
            seq = [r.get("Cena min"), r.get("Cena p25"), r.get("Cena medián"),
                   r.get("Cena p75"), r.get("Cena max")]
            if any(v is None for v in seq) or any(seq[i] > seq[i + 1] for i in range(len(seq) - 1)):
                offenders.append((r.get("Model auta"), seq))
        self.assertEqual(offenders, [], f"{len(offenders)} rows: price stats not min≤p25≤med≤p75≤max "
                         f"(e.g. {offenders[0] if offenders else ''})")

    def test_paired_rows_have_links(self):
        offenders = [r.get("Model auta") for r in self.priced
                     if not str(r.get("Odkaz nejlevnější") or "").startswith("http")
                     or not str(r.get("Odkaz nejdražší") or "").startswith("http")]
        self.assertEqual(offenders, [], f"{len(offenders)} paired rows missing cheapest/dearest links")

    def test_rows_have_brand_model_for_index_link(self):
        # Značka + Model feed reference.js indexFilterModel (jump to the index table
        # filtered to a reference model's listings). Every row needs a brand.
        offenders = [r.get("Model auta") for r in self.rows if not str(r.get("Značka") or "").strip()]
        self.assertEqual(offenders, [], f"{len(offenders)} rows missing Značka (breaks index link)")

    def test_unpaired_rows_are_blank(self):
        offenders = []
        for r in self.rows:
            if r.get("Nabídek"):
                continue
            if r.get("Cena medián") is not None or (r.get("Cena histogram") or []):
                offenders.append(r.get("Model auta"))
        self.assertEqual(offenders, [], f"{len(offenders)} unpaired rows carry price stats/histogram")


class DataIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cars = _records(CARS_PARQUET)
        cls.ice = [c for c in cls.cars if c.get("Typ") == "Spalovací"]
        cls.ev = [c for c in cls.cars if c.get("Typ") == "Elektrické"]
        cls.assertTrue(cls.ice, "no combustion rows in cars.parquet")

    @staticmethod
    def _score(car):
        v = car.get("Skóre shody")
        return v if isinstance(v, (int, float)) else None

    def test_skore_column_in_schema(self):
        self.assertIn("Skóre shody", CANONICAL_COLS)

    def test_sparovano_enum_ice(self):
        bad = {c.get("Spárováno") for c in self.ice} - {"Ano", "Nejisté", "Ne"}
        self.assertFalse(bad, f"unexpected ICE Spárováno values: {bad}")

    def test_sparovano_enum_ev(self):
        # EV has no Nejisté state (prefix-join, not scored).
        bad = {c.get("Spárováno") for c in self.ev} - {"Ano", "Ne"}
        self.assertFalse(bad, f"unexpected EV Spárováno values: {bad}")

    def test_zeme_in_schema(self):
        self.assertIn("Země", CANONICAL_COLS)

    def test_every_row_has_country(self):
        """Country must be populated on every listing — CZ sources backfilled to
        'Česko', mobile.de rows carry their per-listing country."""
        offenders = [c for c in self.cars if not str(c.get("Země") or "").strip()]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows missing Země (e.g. "
                         f"{_name(offenders[0]) if offenders else ''})")

    def test_no_confident_match_with_nonpositive_score(self):
        """THE core reliability invariant: a confident 'Ano' must never be a
        coin-flip (score 0) or a contradiction (score < 0)."""
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Ano"
                     and self._score(c) is not None and self._score(c) <= 0]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} 'Ano' rows score <= 0 (e.g. "
                         f"{_name(offenders[0]) if offenders else ''})")

    def test_ne_rows_carry_no_score(self):
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Ne" and self._score(c) is not None]
        self.assertEqual(offenders, [], f"{len(offenders)} 'Ne' rows carry a score")

    def test_nejiste_rows_carry_a_score(self):
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Nejisté" and self._score(c) is None]
        self.assertEqual(offenders, [], f"{len(offenders)} 'Nejisté' rows missing score")

    def test_phev_consumption_blank(self):
        """PHEV combined consumption is the misleading official WLTP weighted
        figure (~1 l/100 km) — it must be blank, not stamped onto rows."""
        offenders = [c for c in self.ice
                     if c.get("Hybrid typ") == "PHEV"
                     and c.get("Spotřeba (l/100 km)") not in (None, "")]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} PHEV rows carry consumption (e.g. "
                         f"{_name(offenders[0]) if offenders else ''})")

    def test_engine_volume_plausible(self):
        """No ICE row may carry an implausible displacement (sauto's 14.9 bug)."""
        offenders = []
        for c in self.ice:
            v = c.get("Objem motoru")
            if isinstance(v, (int, float)) and not (0.6 <= v <= 8.0):
                offenders.append(c)
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with implausible Objem motoru "
                         f"(e.g. {offenders[0].get('Objem motoru') if offenders else ''})")

    def test_match_rate_is_honest_not_vanity(self):
        """Guard against regression to the old over-confident matcher: uncertainty
        must be surfaced, and the confident rate must be a realistic fraction.

        Ceiling raised 0.95 → 0.98 on 2026-07-22 when Levers A1 (listing-trim
        recovery) + B (collapse trim-only ties to their trimless base) lifted the
        honest Ano rate to ~95.2% (live ICE 6559 Nejisté still surfaced, 4.5%).
        Both are principled and false-confidence-free (see matching.py) — the rate
        rose because real trim-only ties resolved, not because uncertainty was
        hidden. 0.98 still fails hard on a return to the ~99.8% vanity matcher."""
        n = len(self.ice)
        ano = sum(1 for c in self.ice if c.get("Spárováno") == "Ano")
        nej = sum(1 for c in self.ice if c.get("Spárováno") == "Nejisté")
        self.assertGreaterEqual(nej, 1, "no Nejisté rows — uncertainty not surfaced")
        self.assertLess(ano / n, 0.98,
                        f"Ano rate {ano/n:.1%} >= 98% looks like the old vanity matcher")
        self.assertGreater(ano / n, 0.30, f"Ano rate {ano/n:.1%} suspiciously low")


class ColumnFormatIntegrityTest(unittest.TestCase):
    """Per-column format/enum/required-field invariants over the live payload
    (task #21). Every bound below was checked against the current built
    payload first; where the bound had to be weakened, the comment records
    why and cites the real data it was weakened for."""

    _CURRENT_YEAR = datetime.date.today().year

    # Sources that actually enforce the [100000, 750000] Kč scrape window at
    # fetch time (see docs/architecture.md "sauto API Filters" / "mobile.de
    # API Filters"). Autodraft/energycars have no such filter in their
    # adapters, so their listings legitimately range outside it.
    _PRICE_WINDOW_SOURCES = {"Sauto.cz", "Mobile.de"}
    _PRICE_FLOOR = 100000
    _PRICE_CEILING = 750000

    @classmethod
    def setUpClass(cls):
        cls.cars = _records(CARS_PARQUET)
        cls.ice = [c for c in cls.cars if c.get("Typ") == "Spalovací"]
        cls.ev = [c for c in cls.cars if c.get("Typ") == "Elektrické"]
        cls.assertTrue(cls.ice, "no combustion rows in cars.parquet")

    @staticmethod
    def _num(car, col):
        v = car.get(col)
        return v if isinstance(v, (int, float)) else None

    # -- Cena (Kč) ---------------------------------------------------------

    def test_cena_numeric_and_positive(self):
        """Every row must carry a positive numeric price.

        The task spec's [100000, 750000] scrape-window bound does NOT hold
        globally: Autodraft.cz and Energycars.cz have no price filter coded
        in their adapters (only sauto/mobile.de do — see
        docs/architecture.md), so live rows there legitimately range up to
        ~3.36M Kč. That's an intentional asymmetry between sources, not a
        bug, so the global invariant is the honest weaker one; the window
        itself is still checked below for the two sources that enforce it.
        """
        offenders = [c for c in self.cars
                     if not (isinstance(c.get("Cena (Kč)"), (int, float))
                             and c["Cena (Kč)"] > 0)]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with non-numeric/non-positive Cena "
                         f"(e.g. {_name(offenders[0]) if offenders else ''})")

    def test_cena_within_scrape_window_for_filtered_sources(self):
        offenders = [c for c in self.cars
                     if c.get("Zdroj") in self._PRICE_WINDOW_SOURCES
                     and isinstance(c.get("Cena (Kč)"), (int, float))
                     and not (self._PRICE_FLOOR <= c["Cena (Kč)"] <= self._PRICE_CEILING)]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} {self._PRICE_WINDOW_SOURCES} rows outside "
                         f"[{self._PRICE_FLOOR}, {self._PRICE_CEILING}] Kč "
                         f"(e.g. {offenders[0].get('Cena (Kč)') if offenders else ''} "
                         f"{_name(offenders[0]) if offenders else ''})")

    # -- Rok výroby ----------------------------------------------------------

    def test_rok_vyroby_numeric_int_in_range(self):
        """[2000, current_year+1] per MIN_VALID_YEAR (core/fields.py
        repair_year). Blanks tolerated (legitimately unknown year).

        Real finding: one frozen-seed row (Dacia Bigster 1.2 TCe, Sauto.cz)
        carries Rok výroby=1900 — sauto's historical "sentinel date" bug
        that repair_year() now guards against (it would return None and drop
        the row today, per its own docstring). The seed CSVs are a frozen
        bootstrap snapshot that predates the fix and is intentionally never
        re-fixed (docs/gotchas.md: "seeds stop being updated — do not 'fix'
        data in them"), so this is legacy data, not a live regression. The
        tolerance below is 1 known row, not an open-ended allowance.
        """
        lo, hi = 2000, self._CURRENT_YEAR + 1
        offenders = [c for c in self.cars
                     if isinstance(c.get("Rok výroby"), (int, float))
                     and not (lo <= c["Rok výroby"] <= hi)]
        self.assertLessEqual(len(offenders), 1,
                             f"{len(offenders)} rows with Rok výroby outside [{lo}, {hi}] "
                             f"(known: 1 frozen-seed sentinel row; e.g. "
                             f"{offenders[0].get('Rok výroby') if offenders else ''} "
                             f"{_name(offenders[0]) if offenders else ''} / "
                             f"{offenders[0].get('Zdroj') if offenders else ''})")

    # -- Nájezd (km) ---------------------------------------------------------

    def test_najezd_numeric_nonnegative(self):
        """The 100k km scrape ceiling only binds at fetch time for sources
        that enforce it; removed/carried-forward rows can exceed it, so this
        only pins numeric + non-negative (per task spec)."""
        offenders = [c for c in self.cars
                     if isinstance(c.get("Nájezd (km)"), (int, float))
                     and c["Nájezd (km)"] < 0]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with negative Nájezd "
                         f"(e.g. {_name(offenders[0]) if offenders else ''})")

    # -- Výkon (kW) ------------------------------------------------------

    def test_vykon_numeric_nonnegative_when_present(self):
        """Task spec wants strictly > 0 when present. Real finding: 10
        Mobile.de EV rows (Dacia Spring, Hyundai Kona Elektro, Opel Mokka/-e)
        carry an explicit 0 kW — the source's 'pw' attr is genuinely "0" for
        these listings. sauto has an equivalent guard (sanitize_ev_power,
        core/fields.py) that blanks implausible low EV power; mobile.de's
        `_build_row` now calls it too (fixed in scrapers/sources/mobilede.py),
        so fresh scrapes won't reproduce this. The 10 existing rows live in
        the frozen seed CSV (never re-fixed, see docs/gotchas.md) and only
        clear once that source has actually re-scraped past this point — the
        invariant here is deliberately the weaker >= 0 so it still catches
        negative/garbage values in the meantime.
        """
        offenders = [c for c in self.cars
                     if isinstance(c.get("Výkon (kW)"), (int, float))
                     and c["Výkon (kW)"] < 0]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with negative Výkon "
                         f"(e.g. {_name(offenders[0]) if offenders else ''})")

    def test_vykon_zero_rows_are_a_known_small_set(self):
        """Tracks the known (now-fixed-at-source, see above) Mobile.de 0-kW
        gap so a regression that grows it silently is caught, without
        hard-failing on the 10 legacy rows still sitting in the frozen seed
        CSV."""
        offenders = [c for c in self.cars if c.get("Výkon (kW)") == 0]
        self.assertLessEqual(len(offenders), 15,
                             f"{len(offenders)} rows with 0 kW — Mobile.de EV power gap "
                             f"has grown past the known ~10, investigate "
                             f"(e.g. {_name(offenders[0]) if offenders else ''})")

    # -- Objem motoru ------------------------------------------------------

    def test_objem_motoru_in_plausible_range_when_present(self):
        """[0.6, 8.0] l per sanitize_engine_volume (core/fields.py)."""
        offenders = [c for c in self.cars
                     if isinstance(c.get("Objem motoru"), (int, float))
                     and not (0.6 <= c["Objem motoru"] <= 8.0)]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with implausible Objem motoru "
                         f"(e.g. {offenders[0].get('Objem motoru') if offenders else ''} "
                         f"{_name(offenders[0]) if offenders else ''})")

    # -- Počet válců ---------------------------------------------------------

    def test_pocet_valcu_plausible_range_when_present(self):
        """#24: no production passenger car has fewer than 2 or more than 16
        cylinders. Column is only populated for sauto ICE rows today; blank
        elsewhere is expected, not an error."""
        offenders = [c for c in self.cars
                     if isinstance(c.get("Počet válců"), (int, float))
                     and not (2 <= c["Počet válců"] <= 16)]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with implausible Počet válců "
                         f"(e.g. {offenders[0].get('Počet válců') if offenders else ''} "
                         f"{_name(offenders[0]) if offenders else ''})")

    # -- Spolehlivost (#30) ---------------------------------------------------

    def test_spolehlivost_in_plausible_range_when_present(self):
        """Derived score is always an int 1-5 when present."""
        offenders = [c for c in self.cars
                     if isinstance(c.get("Spolehlivost"), (int, float))
                     and not (1 <= c["Spolehlivost"] <= 5)]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with out-of-range Spolehlivost "
                         f"(e.g. {offenders[0].get('Spolehlivost') if offenders else ''} "
                         f"{_name(offenders[0]) if offenders else ''})")

    def test_spolehlivost_blank_for_electric_rows(self):
        """The heuristic is about combustion engines; EV rows never get a score."""
        offenders = [c for c in self.cars
                     if c.get("Typ") == "Elektrické"
                     and isinstance(c.get("Spolehlivost"), (int, float))]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} electric rows unexpectedly carry a Spolehlivost score")

    def test_spolehlivost_blank_only_when_volume_blank_for_ice_rows(self):
        """ICE rows with a known Objem motoru must always get a score — the
        column should degrade to volume-only, never disappear outright."""
        offenders = [c for c in self.cars
                     if c.get("Typ") == "Spalovací"
                     and isinstance(c.get("Objem motoru"), (int, float))
                     and not isinstance(c.get("Spolehlivost"), (int, float))]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} combustion rows with a known engine volume "
                         f"but no Spolehlivost score (e.g. {_name(offenders[0]) if offenders else ''})")

    # -- Servis (Kč/rok) (#23) ------------------------------------------------

    def test_service_cost_in_plausible_range_when_present(self):
        """Every non-blank estimate sits inside the [3000, 60000] clamp window."""
        offenders = [c for c in self.cars
                     if isinstance(c.get("Servis (Kč/rok)"), (int, float))
                     and not (3000 <= c["Servis (Kč/rok)"] <= 60000)]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with out-of-range Servis "
                         f"(e.g. {offenders[0].get('Servis (Kč/rok)') if offenders else ''} "
                         f"{_name(offenders[0]) if offenders else ''})")

    def test_service_cost_present_when_fuel_known(self):
        """A row with a fuel signal (any ICE with Palivo, or any EV) must get an
        estimate — the column should never silently disappear."""
        offenders = [c for c in self.cars
                     if (c.get("Typ") == "Elektrické"
                         or (c.get("Typ") == "Spalovací" and str(c.get("Palivo") or "").strip()))
                     and not isinstance(c.get("Servis (Kč/rok)"), (int, float))]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} rows with a known fuel but no Servis estimate "
                         f"(e.g. {_name(offenders[0]) if offenders else ''})")

    def test_ev_service_cost_cheaper_than_ice_on_average(self):
        """Fuel-factor sanity: EVs are ~0.45× ICE in the model, so the EV mean
        must land below the ICE mean."""
        ice_vals = [c["Servis (Kč/rok)"] for c in self.ice
                    if isinstance(c.get("Servis (Kč/rok)"), (int, float))]
        ev_vals = [c["Servis (Kč/rok)"] for c in self.ev
                   if isinstance(c.get("Servis (Kč/rok)"), (int, float))]
        if ice_vals and ev_vals:
            self.assertLess(sum(ev_vals) / len(ev_vals), sum(ice_vals) / len(ice_vals),
                            "EV mean service cost should be below ICE mean")

    # -- Enum columns --------------------------------------------------------

    def test_typ_enum(self):
        bad = {c.get("Typ") for c in self.cars} - {"Elektrické", "Spalovací"}
        self.assertFalse(bad, f"unexpected Typ values: {bad}")

    def test_stav_enum(self):
        """Real finding: docs/CLAUDE.md documents Stav as an availability enum
        (Dostupný / Chystá se / Zamluvené / Prodané / Odstraněno / blank), but
        sauto.py actually fills Stav from the API's condition_cb ("Nové",
        "Ojeté", "Předváděcí" — vehicle condition, not availability; this
        mapping is documented separately in docs/sauto-api-fields.md). Live
        rows never carry "Odstraněno" (that's archive-only, see
        test_live_payload_has_no_removed_rows) and never "Chystá se" in the
        current dataset. "Havarované" is supposed to be filtered out (sauto.py
        build_ice rejects it) — build_ev now has the equivalent guard too, see
        test_no_havarovane_ev_rows below, which pins the one legacy leaked row
        precisely instead of silently widening this enum to hide it.
        """
        allowed = {"", "Dostupný", "Chystá se", "Zamluvené", "Prodané",
                   "Nové", "Ojeté", "Předváděcí", "Havarované"}
        bad = {str(c.get("Stav") or "") for c in self.cars} - allowed
        self.assertFalse(bad, f"unexpected Stav values: {bad}")

    def test_no_havarovane_ev_rows(self):
        """Real bug found while writing this test: sauto.py's build_ice
        rejects condition == 'Havarované' (damaged/wrecked) but build_ev had
        no equivalent check, so a wrecked EV leaked into the live listings.
        Fixed at the source in scrapers/sources/sauto.py::build_ev — fresh
        scrapes won't reproduce it. The one known row (MG MG4, Sauto.cz)
        still sits in the frozen seed CSV (never re-fixed, see
        docs/gotchas.md) until that source re-scrapes past this point. The
        tolerance below is that one known legacy row, not an open-ended
        allowance — it still fails if the leak grows."""
        offenders = [c for c in self.ev if c.get("Stav") == "Havarované"]
        self.assertLessEqual(len(offenders), 1,
                             f"{len(offenders)} EV rows with Stav=Havarované — sauto.py "
                             f"build_ev is missing the 'Havarované' guard that build_ice has "
                             f"(e.g. {_name(offenders[0]) if offenders else ''})")

    def test_sparovano_enum_all(self):
        bad = {str(c.get("Spárováno") or "") for c in self.cars} - {"Ano", "Nejisté", "Ne", ""}
        self.assertFalse(bad, f"unexpected Spárováno values: {bad}")

    def test_zeme_enum(self):
        allowed = {"", "Česko", "Slovensko", "Německo", "Rakousko", "Polsko"}
        bad = {str(c.get("Země") or "") for c in self.cars} - allowed
        self.assertFalse(bad, f"unexpected Země values: {bad}")

    def test_boolean_columns_enum(self):
        bool_cols = ["Dvouspojková převodovka", "Filtr pevných částic",
                     "Náhon 4x4", "Záruka", "Tepelné čerpadlo"]
        for col in bool_cols:
            with self.subTest(col=col):
                bad = {str(c.get(col) or "") for c in self.cars} - {"Ano", "Ne", ""}
                self.assertFalse(bad, f"unexpected {col} values: {bad}")

    # -- Required fields / uniqueness ---------------------------------------

    def test_required_fields_nonempty(self):
        for col in ["Zdroj", "Odkaz na auto"]:
            with self.subTest(col=col):
                offenders = [c for c in self.cars if not str(c.get(col) or "").strip()]
                self.assertEqual(offenders, [], f"{len(offenders)} rows missing {col}")

        # Task #3: "Model auta" was split into "Značka" + "Model" in the payload
        # (build_data.add_brand_model_columns) — require the reconstructed name
        # to be non-empty rather than either half individually (a single-word
        # model, e.g. "Tesla", legitimately leaves "Model" blank).
        with self.subTest(col="Značka+Model"):
            offenders = [c for c in self.cars if not _name(c)]
            self.assertEqual(offenders, [], f"{len(offenders)} rows missing Značka+Model")

    def test_odkaz_na_auto_unique_in_live_payload(self):
        """Cross-source duplicates are structurally impossible (each source's
        link is a distinct domain); within a source, merge_with_previous dedups
        on this column (core/merge.py, keep='first'). If this ever fails it's
        a real merge/dedup regression, not a bound to weaken."""
        # O(n) count — list.count() in a comprehension is O(n²) and times out
        # once the live payload grows past ~100k rows.
        counts = collections.Counter(c["Odkaz na auto"] for c in self.cars)
        dupes = {l for l, n in counts.items() if n > 1}
        self.assertFalse(dupes, f"{len(dupes)} duplicate 'Odkaz na auto' values in live payload")

    # -- Model/column mismatch guard -----------------------------------------

    def test_confident_ice_model_matches_reference_entry(self):
        """A confident (Spárováno=Ano) ICE row's 'Model auta' must be an exact
        entry in ice_specs.csv's PK column ('Jednoznačná varianta vozu') —
        match_to_authoritative rewrites it to that exact string on a
        confident match (core/matching.py). The payload no longer carries
        'Model auta' directly: task #3 split it into 'Značka' + 'Model', and
        task #4 additionally strips Objem motoru / Typ motoru tokens (e.g.
        "1.5 TSI") off the displayed 'Model' so it isn't duplicated with the
        dedicated columns. Reconstruct via _name() and apply the identical
        strip to each auth entry before comparing, so the guard still checks
        real identity rather than being neutered by the stripped suffix."""
        entries = {strip_ice_engine_tokens(r["entry"])
                   for r in load_authoritative_list(ICE_SPECS_CSV)}
        offenders = [c for c in self.ice
                     if c.get("Spárováno") == "Ano" and _name(c) not in entries]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} confident ICE rows whose Značka+Model isn't in "
                         f"ice_specs.csv (e.g. {_name(offenders[0]) if offenders else ''})")


CARS_ARCHIVED = os.path.join(ROOT, "site", "data", "cars-archived.parquet")


class PayloadContractTest(unittest.TestCase):
    """Pins the browser-facing artifacts: the live/archive split, dtypes, meta."""

    def test_no_int64_columns_in_either_payload(self):
        import pyarrow.parquet as pq
        for path in (CARS_PARQUET, CARS_ARCHIVED):
            offenders = [f.name for f in pq.read_schema(path) if "int64" in str(f.type)]
            self.assertEqual(offenders, [],
                             f"int64 in {os.path.basename(path)} → BigInt in hyparquet: {offenders}")

    def test_meta_sidecar_keys(self):
        with open(CARS_META, encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(
            set(meta),
            {"buildDate", "trigger", "sources", "matching", "referenceData",
             "totalCars", "archivedCars", "filters", "serviceCost"},
        )
        self.assertGreater(meta["totalCars"], 0)
        # filters carries the per-source hard-filter criteria for the dashboard
        self.assertTrue(any(s["source"] == "Sauto.cz" for s in meta["filters"]))
        # serviceCost (#23): methodology + the two clamp counts (drift signal)
        sc = meta["serviceCost"]
        self.assertEqual(sc["unit"], "Kč/rok")
        self.assertIn("factors", sc)
        self.assertTrue(sc["sources"])
        self.assertIsInstance(sc["clampedListings"], int)
        self.assertIsInstance(sc["clampedRefs"], int)
        self.assertGreaterEqual(sc["clampedListings"], 0)
        self.assertGreaterEqual(sc["clampedRefs"], 0)

    def test_live_payload_has_no_removed_rows(self):
        """cars.parquet is the always-loaded live set — removed listings belong
        in cars-archived.parquet, not here (decision 001, option C)."""
        offenders = [c for c in _records(CARS_PARQUET) if c.get("Stav") == "Odstraněno"]
        self.assertEqual(offenders, [],
                         f"{len(offenders)} 'Odstraněno' rows leaked into the live payload")

    def test_archive_holds_only_removed_rows(self):
        archived = _records(CARS_ARCHIVED)
        bad = [c for c in archived if c.get("Stav") != "Odstraněno"]
        self.assertEqual(bad, [], f"{len(bad)} non-removed rows in the archive payload")

    def test_meta_archived_count_matches_archive_file(self):
        with open(CARS_META, encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["archivedCars"], len(_records(CARS_ARCHIVED)))


class BodyTypeConsistencyTest(unittest.TestCase):
    """Pins the family bug fix: reference-driven + vocabulary-folded Karoserie
    (build_data.apply_reference_body_specs + canonicalize_body_vocab). The core
    invariant is 'same car → one body'."""

    # The canonical display vocabulary the whole grid must collapse onto. Read from
    # scrapers/core/bodies.py rather than re-listed here — a local copy is how the
    # taxonomy drifted across five files in the first place.
    CANON = set(_bodies.CANONICAL)

    @classmethod
    def setUpClass(cls):
        cls.cars = _records(CARS_PARQUET)

    def test_vocab_is_canonical(self):
        """No synonym sprawl leaks: every non-blank Karoserie is in the canonical
        set (no CUV / Terénní / VAN / Combi / Liftback / Sedan-limuzína …)."""
        stray = sorted({str(c["Karoserie"]) for c in self.cars
                        if c.get("Karoserie") and str(c["Karoserie"]) not in self.CANON})
        self.assertEqual(stray, [], f"non-canonical body labels leaked: {stray}")

    def test_matched_ice_entry_has_single_body(self):
        """Every confidently-matched (Ano) ICE auth entry maps to exactly one
        body — the invariant Miroslav reported broken. Group by the fields that
        together identify an auth entry in the payload (Model auta is split into
        Značka+Model, so use those + Verze + engine)."""
        from collections import defaultdict
        groups = defaultdict(set)
        for c in self.cars:
            if c.get("Typ") == "Spalovací" and c.get("Spárováno") == "Ano" and c.get("Karoserie"):
                key = (c.get("Značka"), c.get("Model"), c.get("Verze"),
                       c.get("Objem motoru"), c.get("Typ motoru"))
                groups[key].add(str(c["Karoserie"]))
        split = {k: v for k, v in groups.items() if len(v) > 1}
        self.assertEqual(split, {}, f"auth entries with >1 body: {split}")

    def test_matched_ev_nameplate_has_single_body(self):
        """Matched (Ano) EV rows of one nameplate share one body — the reported
        car (Škoda Enyaq) must not scatter across SUV/Hatchback/Terénní again."""
        from collections import defaultdict
        groups = defaultdict(set)
        for c in self.cars:
            if c.get("Typ") == "Elektrické" and c.get("Spárováno") == "Ano" and c.get("Karoserie"):
                groups[(c.get("Značka"), c.get("Model"))].add(str(c["Karoserie"]))
        split = {k: v for k, v in groups.items() if len(v) > 1}
        self.assertEqual(split, {}, f"EV nameplates with >1 body: {split}")

    def test_enyaq_is_uniformly_suv(self):
        bodies = {str(c["Karoserie"]) for c in self.cars
                  if (c.get("Značka") == "Škoda"
                      and str(c.get("Model") or "").startswith("Enyaq")
                      and c.get("Karoserie"))}
        self.assertEqual(bodies, {"SUV"}, f"Enyaq bodies: {bodies}")

    def test_body_coverage_not_regressed(self):
        """Reference-pairing + fold + vote + derive must keep body near-fully
        populated for rows that *can* have a body. The mobile.de "Andere" junk
        bucket is excluded: it is the unindexed-model catch-all (gotcha: never add
        an "X Andere" reference row) — its members have no derivable passenger body
        and their count grows unbounded with the DE-ICE feed, so counting them here
        would only track how much junk mobile.de returned, not a body regression.
        With them excluded the ceiling still catches a real derive/fold/vote
        regression: a mainstream model going blank adds hundreds/thousands of rows
        (e.g. every Octavia), blowing past the ceiling. The remaining blanks are a
        long tail of niche imports (low-volume Chinese EVs — Dayun/JAC/DongFeng/
        Bestune — 1-3 listings each) and commercial vans (Iveco Daily, Peugeot
        Boxer, Nissan Interstar, Maxus/Merc e-vans) with no reference row and no
        derivable passenger body. That tail grew when the build ran against genuinely
        fresh full DE state (~36 on 2026-07-14) vs the older bootstrap state the
        original ceiling (20) was set on — mainstream nameplates the feed surfaced
        (BMW M135, Jaguar XE, Volvo S90, BYD Atto, …) were added to
        `_BODY_NAME_RULES`/`_BODY_MODEL_MAP` in build_data, leaving only the
        genuinely-underivable tail. Ceiling is padded above that for feed churn."""
        blank = sum(
            1 for c in self.cars
            if not c.get("Karoserie") and str(c.get("Model") or "") != "Andere"
        )
        self.assertLessEqual(blank, 45, f"{blank} non-junk rows have a blank Karoserie")


if __name__ == "__main__":
    unittest.main()
