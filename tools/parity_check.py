"""Parity diff: compare a regenerated scraper CSV (or cars.json) against a frozen baseline.

Keys rows on "Odkaz na auto". Reports, for links present in BOTH files, any column whose
value changed (a transformation regression). Links only in one side are listed but tolerated
(live listings appear/vanish between runs).

Usage:
  python tools/parity_check.py csv  OLD.csv NEW.csv [--ignore-cols Typ,Spárováno,Tepelné čerpadlo]
  python tools/parity_check.py json OLD_cars.json NEW_cars.json
Exit 0 = no transformation diffs; exit 1 = regressions found.
"""
import sys
import json
import argparse
import pandas as pd

LINK = "Odkaz na auto"


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, float) and v != v:  # NaN
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    return str(v).strip()


def _rows_from_csv(path):
    df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
    return {r[LINK]: dict(r) for _, r in df.iterrows() if r.get(LINK)}


def _rows_from_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    recs = data["data"] if isinstance(data, dict) and "data" in data else data
    return {r[LINK]: r for r in recs if r.get(LINK)}


def compare(old, new, ignore_cols):
    old_links, new_links = set(old), set(new)
    shared = old_links & new_links
    regressions = []
    for link in sorted(shared):
        o, n = old[link], new[link]
        cols = (set(o) | set(n)) - set(ignore_cols)
        for c in sorted(cols):
            if _norm(o.get(c)) != _norm(n.get(c)):
                regressions.append((link, c, _norm(o.get(c)), _norm(n.get(c))))
    return regressions, old_links - new_links, new_links - old_links


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["csv", "json"])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--ignore-cols", default="")
    args = ap.parse_args()

    ignore = [c for c in args.ignore_cols.split(",") if c]
    loader = _rows_from_csv if args.kind == "csv" else _rows_from_json
    old, new = loader(args.old), loader(args.new)
    regressions, only_old, only_new = compare(old, new, ignore)

    print(f"shared links: {len(set(old) & set(new))}")
    print(f"only in baseline: {len(only_old)}   only in new: {len(only_new)}")
    if regressions:
        print(f"\n{len(regressions)} TRANSFORMATION DIFFS (regressions):")
        for link, col, ov, nv in regressions[:50]:
            print(f"  {link}\n    [{col}] {ov!r} -> {nv!r}")
        if len(regressions) > 50:
            print(f"  ... +{len(regressions) - 50} more")
        sys.exit(1)
    print("\nOK — no transformation diffs on shared links.")
    sys.exit(0)


if __name__ == "__main__":
    main()
