#!/usr/bin/env python3
"""Batch pick for the ai-match-one reference-growth loop.

One state load: classify every live ICE row, dedup worst-first by cluster key
(brand, model_base, engine_vol, engine_type, hybrid), derive an anchored
candidate per cluster, drop junk buckets / existing PKs / rejected PKs /
in-batch dups, and write research inputs for bin/ai-match-one.sh:

    tmp/ref-gap/cand-<md5(link)[:10]>.json   (one per survivor)
    tmp/ref-gap/batch.json                   (summary list)
    tmp/ref-gap/queue.txt                    (links, one per line)

Usage: python3 build/ref_batch_pick.py [DEPTH] [QUEUE_CAP]
  DEPTH      how many worst unique clusters to scan (default 400;
             deepen when the shallow tier is exhausted — see gotchas)
  QUEUE_CAP  max survivors written to the research queue (default: all)

Rejected PKs (proven tie-negative or nonexistent by past batch audits) live in
scrapers/data/reference/rejected_pks.txt — append after every audit so no
future batch re-researches or re-applies them.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from diagnose_unpaired import (  # noqa: E402
    _load_ice_state, row_to_scraped, derive_candidate, simulate_candidate,
    is_junk_bucket, AUTH_CSV)
from scrapers.core.matching import (  # noqa: E402
    load_authoritative_list, classify_match, _model_base_match)

REJECTED_PATH = os.path.join(os.path.dirname(__file__), "..",
                             "scrapers", "data", "reference",
                             "rejected_pks.txt")


def load_rejected():
    if not os.path.exists(REJECTED_PATH):
        return set()
    with open(REJECTED_PATH, encoding="utf-8") as f:
        return {l.strip() for l in f
                if l.strip() and not l.startswith("#")}


def slug(link):
    return hashlib.md5(link.encode()).hexdigest()[:10]


def main():
    depth = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
    rejected = load_rejected()

    ice = _load_ice_state()
    auth_list = load_authoritative_list(AUTH_CSV)
    existing_pks = {a["entry"] for a in auth_list}
    print(f"state: {len(ice)} live ICE, ref: {len(existing_pks)}, "
          f"rejected: {len(rejected)}")

    rows = []
    for i, row in ice.iterrows():
        s = row_to_scraped(row)
        res = classify_match(s, auth_list)
        rows.append((i, s, res["state"], res["score"], row["Odkaz na auto"]))

    ne_ano = [r for r in rows if r[2] != "Ano"]
    ne_ano.sort(key=lambda r: (r[3] is None, r[3] if r[3] is not None else 0))
    print(f"ne-Ano: {len(ne_ano)}")

    seen_keys = set()
    reps = []
    for rec in ne_ano:
        s = rec[1]
        key = (s["brand"].lower(), s["model_base"].lower(),
               s["engine_vol"], s["engine_type"], s["hybrid"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        reps.append(rec)
        if len(reps) >= depth:
            break
    print(f"unique clusters (depth {depth}): {len(reps)}")

    scraped_by_idx = {i: s for i, s, *_ in rows}
    state_by_idx = {i: st for i, _, st, *_ in rows}

    os.makedirs("tmp/ref-gap", exist_ok=True)
    batch = []
    seen_pks = set()
    for i, s, state, score, link in reps:
        if len(batch) >= cap:
            break
        idx = [j for j, sj in scraped_by_idx.items()
               if sj["brand"].lower() == s["brand"].lower()
               and _model_base_match(sj["model_base"], s["model_base"])
               and state_by_idx[j] != "Ano"]
        cluster = ice.loc[idx]
        try:
            cand = derive_candidate(cluster, s["brand"], s["model_base"],
                                    auth_list, anchor=s)
        except Exception as e:
            print(f"SKIP (derive failed) {link}: {e}")
            continue
        if is_junk_bucket(cand):
            continue
        pk = cand["Jednoznačná varianta vozu"]
        if pk in existing_pks or pk in rejected or pk in seen_pks:
            print(f"SKIP {pk}")
            continue
        seen_pks.add(pk)
        before, after = simulate_candidate(cluster, auth_list, cand)
        with open(f"tmp/ref-gap/cand-{slug(link)}.json", "w",
                  encoding="utf-8") as f:
            json.dump({"candidate": cand, "before": before, "after": after,
                       "cluster_links": list(cluster["Odkaz na auto"])},
                      f, ensure_ascii=False, indent=2)
        batch.append({"link": link, "pk": pk, "cluster": len(cluster),
                      "score": score})
        print(f"OK [{len(batch)}] {pk}  cluster={len(cluster)} score={score}")

    with open("tmp/ref-gap/batch.json", "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=2)
    with open("tmp/ref-gap/queue.txt", "w") as f:
        for e in batch:
            f.write(e["link"] + "\n")
    print(f"\nsurvivors: {len(batch)} → tmp/ref-gap/queue.txt")


if __name__ == "__main__":
    main()
