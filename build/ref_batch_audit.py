#!/usr/bin/env python3
"""Tie audit for a reference-growth batch (see gotchas: a batch can be NET
NEGATIVE — near-dup rows tie existing entries and demote Ano matches).

Compares matching under REF_BEFORE vs the current ice_specs.csv on the local
state, reports the joint delta + transitions, computes each new row's
ISOLATED net on its (brand, model_base) subset, and (with --prune) removes
isolated-negative rows from ice_specs.csv and appends them to
rejected_pks.txt.

Usage:
    python3 build/ref_batch_audit.py REF_BEFORE.csv            # report only
    python3 build/ref_batch_audit.py REF_BEFORE.csv --prune    # + prune negatives

Always re-run (report mode) after pruning or body edits — isolated effects
are not additive and body changes shift matching. Rows the single-body test
flags that duplicate an existing entry should be DROPPED, not body-filled
(the blank body was hiding the tie).
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from diagnose_unpaired import _load_ice_state, row_to_scraped, AUTH_CSV  # noqa: E402
from scrapers.core.matching import (  # noqa: E402
    load_authoritative_list, classify_match, _model_base_match)

REJECTED_PATH = os.path.join(os.path.dirname(__file__), "..",
                             "scrapers", "data", "reference",
                             "rejected_pks.txt")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ref_before = sys.argv[1]
    prune = "--prune" in sys.argv

    ice = _load_ice_state()
    authA = load_authoritative_list(ref_before)
    authB = load_authoritative_list(AUTH_CSV)
    pksA = {a["entry"] for a in authA}
    new_rows = [a for a in authB if a["entry"] not in pksA]
    print(f"state: {len(ice)}, before: {len(authA)}, after: {len(authB)}, "
          f"new: {len(new_rows)}")

    scraped = [row_to_scraped(r) for _, r in ice.iterrows()]

    tot = collections.Counter()
    demoted_from = collections.Counter()
    for s in scraped:
        a = classify_match(s, authA)
        b = classify_match(s, authB)
        tot[(a["state"], b["state"])] += 1
        if a["state"] == "Ano" and b["state"] != "Ano":
            demoted_from[a["entry"]] += 1
    neA = sum(v for (a, _), v in tot.items() if a != "Ano")
    neB = sum(v for (_, b), v in tot.items() if b != "Ano")
    print(f"\nne-Ano before: {neA}   after: {neB}   delta {neB - neA}")
    print("transitions:", {k: v for k, v in tot.items() if k[0] != k[1]})
    if demoted_from:
        print("\ntop demoted old entries (tie sources):")
        for k, v in demoted_from.most_common(10):
            print(f"  {v:5d}  {k}")

    print("\nper-row isolated net (neg = row worsens matching):")
    negatives = []
    for r in new_rows:
        subset = [s for s in scraped
                  if s["brand"].lower() == r["brand"].lower()
                  and _model_base_match(s["model_base"], r["model_base"])]
        aA = sum(classify_match(s, authA)["state"] == "Ano" for s in subset)
        aI = sum(classify_match(s, authA + [r])["state"] == "Ano"
                 for s in subset)
        d = aI - aA
        if d < 0:
            negatives.append(r["entry"])
        print(f"  {d:+6d}  {r['entry']}  (subset {len(subset)})")

    if not prune:
        if negatives:
            print(f"\n{len(negatives)} negative rows — rerun with --prune "
                  f"to drop them and record them in rejected_pks.txt")
        return

    if negatives:
        import csv
        rows = list(csv.reader(open(AUTH_CSV, encoding="utf-8", newline="")))
        kept = [rows[0]] + [r for r in rows[1:]
                            if r and r[0] not in set(negatives)]
        with open(AUTH_CSV, "w", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(kept)
        with open(REJECTED_PATH, "a", encoding="utf-8") as f:
            for pk in negatives:
                f.write(pk + "\n")
        print(f"\npruned {len(negatives)} rows from ice_specs.csv, "
              f"appended to rejected_pks.txt — re-run report mode to verify")
    else:
        print("\nno negative rows — nothing to prune")


if __name__ == "__main__":
    main()
