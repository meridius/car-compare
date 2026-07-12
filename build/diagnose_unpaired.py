"""Diagnose why an ICE listing pairs badly and derive a candidate reference row.

The single-listing counterpart of the mass grow-reference loop: pick the worst
listing, explain its score field-by-field against every candidate the real
matcher sees, derive a structured ice_specs.csv candidate row from the
listing's cluster, and simulate the pairing delta with the real classifier.

Usage:
    python3 build/diagnose_unpaired.py pick [--n 15]
    python3 build/diagnose_unpaired.py explain --link URL
    python3 build/diagnose_unpaired.py candidate --link URL [--out FILE]

All modes read the per-source state parquets (run ./bin/bootstrap-data.sh
first to mirror prod). Scores here are the real ones: the same
normalize + parse + classify path build_data.rematch_combustion uses.
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "build"))

import pandas as pd

from scrapers.core import matching
from scrapers.core.matching import (
    _canonicalize_body,
    _clean_model_for_matching,
    _extract_body_from_model,
    _parse_brand,
    _score_match,
    classify_match,
    find_candidates,
    load_authoritative_list,
)

AUTH_CSV = os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")

REF_COLUMNS = [
    "Jednoznačná varianta vozu", "Značka", "Model", "Verze", "Generace",
    "Karoserie", "Počet míst", "Objem motoru", "Typ motoru", "Palivo",
    "Hybrid typ", "Spotřeba (l/100 km)", "Objem kufru (l)", "Hlučnost (dB)",
    "Cd", "Cd zdroj",
]

# A field must reach this share of the cluster's non-blank values to be
# trusted in the candidate row; below it the extraction is noise → blank.
CONSENSUS_MIN = 0.6


def _cell(row, col):
    v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v) else str(v)


def row_to_scraped(row):
    """Build the matcher's scraped-features dict from a state row.

    Mirrors the inline construction in matching.match_to_authoritative —
    tests pin that both classify identically.
    """
    model_auta = _cell(row, "Model auta")
    brand, remainder = _parse_brand(model_auta)
    body = _cell(row, "Karoserie") or _extract_body_from_model(remainder)
    return {
        "brand": brand,
        "model_base": _clean_model_for_matching(remainder),
        "body": body,
        "engine_vol": _cell(row, "Objem motoru"),
        "engine_type": _cell(row, "Typ motoru"),
        "hybrid": _cell(row, "Hybrid typ"),
        "fuel": _cell(row, "Palivo"),
        "trim": _cell(row, "Verze"),
    }


def score_breakdown(scraped, auth):
    """Itemize _score_match per field. Sum is asserted equal to the real score."""
    items = []

    def add(field, points, sval, aval):
        items.append({"field": field, "points": points,
                      "scraped": sval, "auth": aval})

    sb, ab = _canonicalize_body(scraped.get("body", "")), auth["body"]
    if sb and ab:
        add("body", 3 if sb == ab else -2, sb, ab)

    sv, av = scraped.get("engine_vol", ""), auth["engine_vol"]
    if sv and av:
        try:
            add("engine_vol", 2 if abs(float(sv) - float(av)) <= 0.15 else -1, sv, av)
        except ValueError:
            pass

    se, ae = scraped.get("engine_type", "").lower(), auth["engine_type"].lower()
    if se and ae:
        add("engine_type", 2 if se == ae else -1,
            scraped.get("engine_type", ""), auth["engine_type"])

    sh, ah = scraped.get("hybrid", ""), auth["hybrid"]
    if sh and ah:
        add("hybrid", 3 if sh == ah else -2, sh, ah)
    elif sh or ah:
        add("hybrid", -1, sh or "(blank)", ah or "(blank)")

    sf, af = scraped.get("fuel", ""), auth["fuel"]
    if sf and af:
        add("fuel", 1 if sf == af else -1, sf, af)

    st, at = scraped.get("trim", ""), auth.get("trim", "")
    if st and at:
        add("trim", 2 if st == at else -1, st, at)

    total = sum(i["points"] for i in items)
    real = _score_match(scraped, auth)
    if total != real:  # self-check: breakdown must never drift from the matcher
        raise AssertionError(f"score_breakdown drifted: {total} != {real}")
    return items


def _mode_with_consensus(values):
    """Most common non-blank value if it reaches CONSENSUS_MIN, else ''."""
    vals = [v for v in values if v]
    if not vals:
        return ""
    top = pd.Series(vals).value_counts()
    if top.iloc[0] / len(vals) >= CONSENSUS_MIN:
        return top.index[0]
    return ""


def derive_candidate(cluster, brand, model_base, auth_list=None):
    """Derive one structured ice_specs.csv candidate row from a listing cluster.

    Matching feature columns come from majority vote over the cluster; display
    spec columns (Generace, Spotřeba, kufr, dB, Cd, …) stay blank for research.

    When the model family already exists in auth_list, Model is taken from the
    existing candidates' model_base (mode) — the parsed listing base can carry
    junk tokens inherited from the scrape-time best-guess rewrite of
    "Model auta" (e.g. "Santa Fe Hybrid" on a diesel row).
    """
    if auth_list:
        fam = find_candidates({"brand": brand, "model_base": model_base}, auth_list)
        if fam:
            model_base = pd.Series([a["model_base"] for a in fam]).mode()[0]
    feats = {
        "Karoserie": _mode_with_consensus(
            _canonicalize_body(_cell(r, "Karoserie")) for _, r in cluster.iterrows()),
        "Objem motoru": _mode_with_consensus(
            _cell(r, "Objem motoru") for _, r in cluster.iterrows()),
        "Typ motoru": _mode_with_consensus(
            _cell(r, "Typ motoru") for _, r in cluster.iterrows()),
        "Palivo": _mode_with_consensus(
            _cell(r, "Palivo") for _, r in cluster.iterrows()),
        "Hybrid typ": _mode_with_consensus(
            _cell(r, "Hybrid typ") for _, r in cluster.iterrows()),
    }
    name_parts = [brand, model_base, feats["Objem motoru"], feats["Typ motoru"],
                  feats["Hybrid typ"]]
    cand = {c: "" for c in REF_COLUMNS}
    cand.update(feats)
    cand["Značka"] = brand
    cand["Model"] = model_base
    cand["Jednoznačná varianta vozu"] = " ".join(p for p in name_parts if p)
    return cand


def _candidate_to_auth(cand):
    return {
        "entry": cand["Jednoznačná varianta vozu"],
        "brand": cand["Značka"],
        "model_base": cand["Model"],
        "body": _canonicalize_body(cand["Karoserie"]),
        "body_raw": cand["Karoserie"],
        "engine_vol": cand["Objem motoru"],
        "engine_type": cand["Typ motoru"],
        "hybrid": cand["Hybrid typ"],
        "fuel": cand["Palivo"],
        "trim": cand["Verze"],
        "seats": cand["Počet míst"],
    }


def simulate_candidate(cluster, auth_list, cand):
    """(before, after) state counts over the cluster when cand joins auth_list."""
    def counts(alist):
        c = {"Ano": 0, "Nejisté": 0, "Ne": 0}
        for _, row in cluster.iterrows():
            c[classify_match(row_to_scraped(row), alist)["state"]] += 1
        return c
    return counts(auth_list), counts(auth_list + [_candidate_to_auth(cand)])


# ---------------------------------------------------------------------------
# data loading / CLI
# ---------------------------------------------------------------------------

def _load_ice_state():
    """Concat state parquets and normalize names the way build_data does pre-match."""
    from build_data import load_scraper_data, strip_listing_noise, _normalize_model
    df = load_scraper_data()
    ice = df[df["Typ"] == "Spalovací"].copy()
    live = ice["Stav"].astype(str) != "Odstraněno"
    ice = ice[live]
    ice["Model auta"] = ice["Model auta"].map(
        lambda m: _normalize_model(strip_listing_noise(str(m))))
    return ice


def _find_row(ice, link):
    hit = ice[ice["Odkaz na auto"] == link]
    if hit.empty:
        sys.exit(f"listing not found in state: {link}")
    return hit.iloc[0]


def _cluster_for(ice, scraped, auth_list):
    """Rows the matcher sees as the same (brand, model_base) that aren't Ano."""
    idx = []
    for i, row in ice.iterrows():
        s = row_to_scraped(row)
        if s["brand"].lower() != scraped["brand"].lower():
            continue
        if not matching._model_base_match(s["model_base"], scraped["model_base"]):
            continue
        if classify_match(s, auth_list)["state"] != "Ano":
            idx.append(i)
    return ice.loc[idx]


def cmd_pick(args):
    ice = _load_ice_state()
    auth_list = load_authoritative_list(AUTH_CSV)
    rows = []
    for _, row in ice.iterrows():
        res = classify_match(row_to_scraped(row), auth_list)
        if res["state"] != "Ano":
            rows.append({"link": row["Odkaz na auto"],
                         "model": row["Model auta"],
                         "state": res["state"],
                         "score": res["score"] if res["score"] is not None else "",
                         "entry": res["entry"] or ""})
    out = pd.DataFrame(rows)
    out["_s"] = pd.to_numeric(out["score"], errors="coerce")
    out = out.sort_values("_s", na_position="last").drop(columns="_s")
    print(out.head(args.n).to_string(index=False))
    print(f"\ncelkem ne-Ano: {len(out)} "
          f"(Nejisté {sum(out.state == 'Nejisté')}, Ne {sum(out.state == 'Ne')})")


def cmd_explain(args):
    ice = _load_ice_state()
    auth_list = load_authoritative_list(AUTH_CSV)
    row = _find_row(ice, args.link)
    scraped = row_to_scraped(row)
    print(f"listing: {row['Model auta']}  [{args.link}]")
    print(f"parsed:  {scraped}\n")
    cands = find_candidates(scraped, auth_list)
    if not cands:
        print("žádný kandidát (Spárováno=Ne) — chybí referenční řádek pro "
              f"({scraped['brand']}, {scraped['model_base']})")
        return
    scored = sorted(((_score_match(scraped, a), a) for a in cands),
                    key=lambda x: x[0], reverse=True)
    for score, a in scored:
        print(f"kandidát: {a['entry']}  → score {score}")
        for it in score_breakdown(scraped, a):
            sign = "+" if it["points"] > 0 else ""
            print(f"    {it['field']:<12} {sign}{it['points']:<3} "
                  f"listing={it['scraped']!r} ref={it['auth']!r}")
    res = classify_match(scraped, auth_list)
    print(f"\nverdikt: {res['state']} (score {res['score']}, margin {res['margin']})")


def cmd_candidate(args):
    ice = _load_ice_state()
    auth_list = load_authoritative_list(AUTH_CSV)
    row = _find_row(ice, args.link)
    scraped = row_to_scraped(row)
    cluster = _cluster_for(ice, scraped, auth_list)
    print(f"cluster ({scraped['brand']}, {scraped['model_base']}): {len(cluster)} ne-Ano řádků")
    cand = derive_candidate(cluster, scraped["brand"], scraped["model_base"], auth_list)
    before, after = simulate_candidate(cluster, auth_list, cand)
    print(f"kandidátní řádek: {json.dumps(cand, ensure_ascii=False, indent=2)}")
    print(f"simulace: {before} → {after}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"candidate": cand, "before": before, "after": after,
                       "cluster_links": list(cluster["Odkaz na auto"])},
                      f, ensure_ascii=False, indent=2)
        print(f"zapsáno: {args.out}")


# Plausibility windows for researched display specs; out-of-range → blank.
SPEC_RANGES = {
    "Spotřeba (l/100 km)": (3.0, 15.0),
    "Objem kufru (l)": (150, 900),
    "Hlučnost (dB)": (60, 78),
    "Cd": (0.20, 0.45),
    "Počet míst": (2, 9),
}

# research JSON (snake_case, see grow-reference research contract) → CSV column
RESEARCH_KEYS = {
    "generace": "Generace",
    "seats": "Počet míst",
    "consumption_l100km": "Spotřeba (l/100 km)",
    "trunk_l": "Objem kufru (l)",
    "noise_db": "Hlučnost (dB)",
    "cd": "Cd",
    "cd_source": "Cd zdroj",
}


def merge_research(cand, research):
    """Fold researched display specs into a candidate row, range-validating."""
    out = dict(cand)
    for key, col in RESEARCH_KEYS.items():
        val = str(research.get(key, "") or "").strip()
        if not val:
            continue
        if col in SPEC_RANGES:
            try:
                lo, hi = SPEC_RANGES[col]
                if not lo <= float(val) <= hi:
                    print(f"  mimo rozsah, blank: {col} = {val}")
                    continue
            except ValueError:
                print(f"  nečíselné, blank: {col} = {val}")
                continue
        out[col] = val
    return out


def _format_csv_row(cand):
    """Serialize to ice_specs.csv conventions: Spotřeba quoted czech-comma,
    Hlučnost/Cd dot-decimal."""
    row = dict(cand)
    spot = row.get("Spotřeba (l/100 km)", "")
    if spot:
        row["Spotřeba (l/100 km)"] = str(spot).replace(".", ",")
    return [row.get(c, "") for c in REF_COLUMNS]


def cmd_apply(args):
    import csv
    with open(args.candidate, encoding="utf-8") as f:
        payload = json.load(f)
    cand = payload["candidate"] if "candidate" in payload else payload
    if args.research:
        with open(args.research, encoding="utf-8") as f:
            research = json.load(f)
        if research.get("exists") is False:
            sys.exit("research says exists=false — neaplikuji (viz mobile.de "
                     "fabricated-hybrids gotcha)")
        cand = merge_research(cand, research)
    existing = {a["entry"] for a in load_authoritative_list(AUTH_CSV)}
    pk = cand["Jednoznačná varianta vozu"]
    if pk in existing:
        sys.exit(f"duplikát, neaplikuji: {pk}")
    print(json.dumps(cand, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("(dry-run — nic nezapsáno)")
        return
    with open(AUTH_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(_format_csv_row(cand))
    print(f"přidáno do ice_specs.csv: {pk}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("pick", help="rank worst-matched ICE listings")
    sp.add_argument("--n", type=int, default=15)
    sp.set_defaults(fn=cmd_pick)
    se = sub.add_parser("explain", help="field-by-field score breakdown")
    se.add_argument("--link", required=True)
    se.set_defaults(fn=cmd_explain)
    sc = sub.add_parser("candidate", help="derive + simulate a reference row")
    sc.add_argument("--link", required=True)
    sc.add_argument("--out")
    sc.set_defaults(fn=cmd_candidate)
    sa = sub.add_parser("apply", help="append candidate (+research) to ice_specs.csv")
    sa.add_argument("--candidate", required=True, help="JSON from `candidate --out`")
    sa.add_argument("--research", help="research JSON (snake_case keys)")
    sa.add_argument("--dry-run", action="store_true")
    sa.set_defaults(fn=cmd_apply)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
