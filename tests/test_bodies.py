"""Canonical body-style taxonomy invariants (scrapers/core/bodies.py).

Phase A of docs/superpowers/specs/2026-07-28-body-taxonomy-design.md. The point of
the module is that ONE table owns the fold; these tests pin the properties that
made the four previously-duplicated tables drift apart.
"""

import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrapers.core import bodies

REPO = os.path.join(os.path.dirname(__file__), "..")
ICE_CSV = os.path.join(REPO, "scrapers", "data", "reference", "ice_specs.csv")
EV_CSV = os.path.join(REPO, "scrapers", "data", "reference", "ev_specs.csv")


class CanonicalVocabularyTest(unittest.TestCase):
    def test_nine_display_values_in_stable_order(self):
        self.assertEqual(
            bodies.CANONICAL,
            ("SUV", "Kombi", "Hatchback", "Liftback", "Sedan", "MPV",
             "Kupé", "Kabriolet", "Pick-up"),
        )

    def test_display_fold_is_idempotent(self):
        """Folding a canonical value must return it unchanged — otherwise running
        the fold twice (build_data does, via reference then vote) would drift."""
        for v in bodies.CANONICAL:
            self.assertEqual(bodies.to_display(v), v, v)

    def test_every_canonical_value_has_a_scoring_canon(self):
        """The gap this catches for real: Kabriolet and Pick-up had no _BODY_GROUPS
        entry, so a convertible listing scored -2 against every reference row."""
        for v in bodies.CANONICAL:
            self.assertIn(v, bodies.SCORING_FOLD, v)

    def test_scoring_canons_are_themselves_canonical(self):
        for canon, scoring in bodies.SCORING_FOLD.items():
            self.assertIn(scoring, bodies.CANONICAL, f"{canon} -> {scoring}")

    def test_liftback_family_folds_to_hatchback_for_scoring_only(self):
        """The load-bearing split: display keeps Liftback distinct (it comes from
        the reference), scoring folds it (listings cannot distinguish it — a
        mobile.de liftback arrives tagged SmallCar -> Hatchback)."""
        self.assertEqual(bodies.to_display("Sportback"), "Liftback")
        self.assertEqual(bodies.to_display("Fastback"), "Liftback")
        self.assertEqual(bodies.to_display("Liftback"), "Liftback")
        for raw in ("Sportback", "Fastback", "Liftback", "Hatchback"):
            self.assertEqual(bodies.to_scoring(raw), "Hatchback", raw)

    def test_shooting_brake_is_kombi_in_both_taxonomies(self):
        self.assertEqual(bodies.to_display("Shooting Brake"), "Kombi")
        self.assertEqual(bodies.to_scoring("Shooting Brake"), "Kombi")

    def test_kabriolet_is_not_kupe(self):
        """It used to fold to Kupé, which is simply false — an open car is not a
        fixed-roof car, and it is the most decision-relevant body fact there is."""
        self.assertEqual(bodies.to_display("Kabriolet"), "Kabriolet")
        self.assertEqual(bodies.to_display("Cabrio"), "Kabriolet")
        self.assertEqual(bodies.to_display("Roadster"), "Kabriolet")
        self.assertNotEqual(bodies.to_scoring("Kabriolet"), bodies.to_scoring("Kupé"))

    def test_suv_absorbs_cuv_and_terenni(self):
        for raw in ("SUV", "CUV", "Terénní", "Crossover", "OffRoad"):
            self.assertEqual(bodies.to_display(raw), "SUV", raw)

    def test_kombi_absorbs_brand_nomenclature(self):
        for raw in ("Kombi", "Combi", "Variant", "Avant", "SW", "Touring",
                    "Sports Tourer", "Grandtour", "EstateCar"):
            self.assertEqual(bodies.to_display(raw), "Kombi", raw)

    def test_non_body_labels_fold_to_blank(self):
        """"Allspace" is a VW trim that leaked into BODY_KEYWORDS and produced
        Karoserie="Allspace" rows. A non-body must blank, not pass through, so the
        vote/derive chain can fill it."""
        self.assertEqual(bodies.to_display("Allspace"), "")

    def test_blank_and_none_are_blank(self):
        self.assertEqual(bodies.to_display(""), "")
        self.assertEqual(bodies.to_display(None), "")
        self.assertEqual(bodies.to_scoring(""), "")

    def test_fold_is_case_and_whitespace_insensitive(self):
        self.assertEqual(bodies.to_display("  sportBACK "), "Liftback")
        self.assertEqual(bodies.to_display("sedan/limuzína"), "Sedan")

    def test_unknown_value_passes_through(self):
        """Deliberate: an unrecognised body must stay visible rather than silently
        becoming blank or SUV, so the totality test below can catch it."""
        self.assertEqual(bodies.to_display("Trikolka"), "Trikolka")

    def test_display_then_scoring_equals_scoring(self):
        """to_scoring must be the composition, so callers can't get a different
        answer by folding for display first (build_data does exactly that)."""
        for raw in ("Sportback", "CUV", "Shooting Brake", "Cabrio", "VAN",
                    "Sedan/limuzína", "Pick-up", "Coupé"):
            self.assertEqual(
                bodies.to_scoring(bodies.to_display(raw)),
                bodies.to_scoring(raw), raw,
            )


class DisplayFoldTotalityTest(unittest.TestCase):
    """Every body value that actually occurs in the reference CSVs must fold onto a
    canonical value. This is the test that catches "someone added a new label".
    """

    def _ref_bodies(self, path, col="Karoserie"):
        with open(path, encoding="utf-8") as fh:
            return {(r.get(col) or "").strip()
                    for r in csv.DictReader(fh)} - {""}

    def test_ice_reference_bodies_are_all_canonical(self):
        unknown = sorted(v for v in self._ref_bodies(ICE_CSV)
                         if bodies.to_display(v) not in bodies.CANONICAL)
        self.assertEqual(unknown, [], f"ice_specs.csv has non-canonical bodies: {unknown}")

    def test_ev_reference_bodies_are_all_canonical(self):
        unknown = sorted(v for v in self._ref_bodies(EV_CSV)
                         if bodies.to_display(v) not in bodies.CANONICAL)
        self.assertEqual(unknown, [], f"ev_specs.csv has non-canonical bodies: {unknown}")


class PlausiblePairTest(unittest.TestCase):
    """Pass 3 of the reference audit, kept as a standing invariant so the review
    queue can never silently regrow.

    Nameplate body *conflict* is NOT an error — body is itself a variant dimension
    (VW Golf 2.0 TDI is legitimately [Hatchback, Kombi] = Golf + Golf Variant). Only
    an *implausible* combination is.
    """

    def test_no_reference_nameplate_mixes_implausible_bodies(self):
        with open(ICE_CSV, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        by_nameplate = {}
        for r in rows:
            body = bodies.to_display((r.get("Karoserie") or "").strip())
            if not body:
                continue
            by_nameplate.setdefault(
                (r["Značka"].strip(), r["Model"].strip()), set()).add(body)

        offenders = sorted(
            f"{zn} {mo}: {sorted(bs)}"
            for (zn, mo), bs in by_nameplate.items()
            if not bodies.pairs_are_plausible(bs)
        )
        self.assertEqual(offenders, [], "implausible body sets:\n  " + "\n  ".join(offenders))

    def test_detector_accepts_real_multi_body_ranges(self):
        self.assertTrue(bodies.pairs_are_plausible({"Hatchback", "Kombi"}))   # Golf + Variant
        self.assertTrue(bodies.pairs_are_plausible({"Sedan", "Kombi"}))       # A4 + Avant
        self.assertTrue(bodies.pairs_are_plausible({"Sedan", "Liftback"}))    # A3 sedan + Sportback
        self.assertTrue(bodies.pairs_are_plausible({"Kupé", "Kabriolet"}))
        self.assertTrue(bodies.pairs_are_plausible({"SUV"}))
        self.assertTrue(bodies.pairs_are_plausible(set()))

    def test_detector_rejects_implausible_combinations(self):
        self.assertFalse(bodies.pairs_are_plausible({"SUV", "Sedan"}))        # Volvo S60 error
        self.assertFalse(bodies.pairs_are_plausible({"Hatchback", "SUV"}))    # Nissan Juke error
        self.assertFalse(bodies.pairs_are_plausible({"Kombi", "SUV"}))        # Dacia Duster error

    def test_hatchback_liftback_pair_is_implausible(self):
        """Same physical body labelled two ways (Audi A3 [Hatchback, Sportback]).
        Whitelisting it would suppress exactly the error this pass exists to find."""
        self.assertFalse(bodies.pairs_are_plausible({"Hatchback", "Liftback"}))


if __name__ == "__main__":
    unittest.main()
