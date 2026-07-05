"""grow-reference: find missing reference models from unpaired listings, research
their specs (agentic), and grow ev_specs.csv / ice_specs.csv behind a review gate.

Deterministic core — offline, unit-tested. Run as a script:
    python3 build/reference_gap.py gaps --fuel ev --rebuild
"""
import csv
import json
import os
import re
import sys
import unicodedata

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from scrapers.core.normalize import normalize_model  # noqa: E402

FUELS = {"ev": "Elektrické", "ice": "Spalovací"}
REF_FILES = {"ev": "ev_specs.csv", "ice": "ice_specs.csv"}
ID_COL = {"ev": "Model auta", "ice": "Jednoznačná varianta vozu"}
EV_RANGES = {
    "Objem kufru (l)": (50, 900),
    "Hlučnost (dB)": (50, 85),
    "Kapacita baterie (kWh)": (10, 150),
    "Dojezd komb. letní WLTP (km)": (100, 800),
    "Dojezd komb. letní EV-database (km)": (100, 800),
    "Cd": (0.20, 0.45),
}
CARS_PARQUET = os.path.join(BASE_DIR, "site", "data", "cars.parquet")
REF_DIR = os.path.join(BASE_DIR, "scrapers", "data", "reference")

# spec tokens stripped when deriving a model grouping key (powertrain/battery/hp noise)
_KEY_STRIP = re.compile(
    r"\b(\d{2,3}\s?(kw|ps|hp|k)|\d{2,3}([.,]\d)?\s?kwh|e-?tech|e-?tec|awd|4wd|"
    r"long\s?range|comfort|design|style|extended)\b",
    re.IGNORECASE,
)


def load_unpaired_from_rows(rows, fuel):
    typ = FUELS[fuel]
    return [r for r in rows if r.get("Typ") == typ and r.get("Spárováno") == "Ne"]


def load_unpaired(cars_path, fuel):
    import pandas as pd
    df = pd.read_parquet(cars_path)
    rows = [
        {k: (None if (isinstance(v, float) and v != v) else v) for k, v in rec.items()}
        for rec in df.to_dict("records")
    ]
    return load_unpaired_from_rows(rows, fuel)


def _fold_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _canonical_key(name):
    n = _fold_accents(normalize_model(name or "")).lower()
    n = _KEY_STRIP.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def _shared_prefix(names):
    """Longest word-boundary prefix common to all raw names in a cluster.
    Token comparison is case-insensitive (the EV join lowercases both sides, so
    casing never affects pairing) but the first name's original casing is emitted."""
    if not names:
        return ""
    split = [n.split() for n in names]
    out = []
    for i in range(min(len(w) for w in split)):
        tok = split[0][i]
        if all(w[i].lower() == tok.lower() for w in split):
            out.append(tok)
        else:
            break
    return " ".join(out) if out else names[0]


def cluster(listings, fuel):
    groups = {}
    for r in listings:
        key = _canonical_key(r.get("Model auta", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(r)
    clusters = []
    for key, members in groups.items():
        names = [m.get("Model auta", "") for m in members]
        clusters.append({
            "key": key,
            "prefix": _shared_prefix(names) or names[0],
            "volume": len(members),
            "sample_names": sorted(set(names))[:5],
            "sample_links": [m.get("Odkaz na auto", "") for m in members[:3]],
        })
    clusters.sort(key=lambda c: c["volume"], reverse=True)
    return clusters


def load_reference_models(fuel):
    path = os.path.join(REF_DIR, REF_FILES[fuel])
    with open(path, newline="", encoding="utf-8") as f:
        return [row[ID_COL[fuel]] for row in csv.DictReader(f) if row.get(ID_COL[fuel])]


def _prefix_matches(name, ref_low):
    nl = name.lower()
    return any(nl.startswith(r) for r in ref_low)


def classify(cluster, ref_models):
    ref_low = [r.lower() for r in ref_models]
    raws = cluster.get("sample_names") or [cluster["prefix"]]
    if any(_prefix_matches(n, ref_low) for n in raws):
        return "covered"  # sanity: raw already matches a ref prefix (should have been Ano)
    if any(_prefix_matches(normalize_model(n), ref_low) for n in raws):
        return "normalization_gap"  # a BRAND_MAP/cleanup fix would pair it — not a new row
    return "missing_ref"


def _ev_header():
    path = os.path.join(REF_DIR, REF_FILES["ev"])
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def ev_columns():
    return _ev_header()


def project_newly_paired(prefixes, unpaired):
    names = [str(r.get("Model auta", "")).lower() for r in unpaired]
    out = {}
    for p in prefixes:
        pl = p.lower()
        out[p] = sum(1 for n in names if n.startswith(pl))
    return out


def _is_token_prefix(parent, child):
    """True if parent's tokens are a strict, word-boundary-safe prefix of child's
    tokens (case-insensitive). Token-based so "Citroën C3" prefixes "Citroën C3
    Aircross" but NOT "Citroën C30" (no shared final token)."""
    pt = parent.lower().split()
    ct = child.lower().split()
    return len(pt) < len(ct) and ct[: len(pt)] == pt


def find_nested_prefixes(prefixes):
    """Pairs (parent, child) among `prefixes` where parent is a token-prefix of
    child — e.g. ("Citroën C3", "Citroën C3 Aircross"). Approving `parent` alone
    would silently absorb `child`'s listings under the wrong model's specs."""
    return [
        (parent, child)
        for parent in prefixes
        for child in prefixes
        if parent != child and _is_token_prefix(parent, child)
    ]


def project_own_absorbed(prefixes, unpaired):
    """Split each candidate prefix's raw startswith count into:
      - own:      listings for which this prefix is the LONGEST matching
                  candidate prefix (i.e. its real cluster size).
      - absorbed: listings that also startswith this prefix but whose true
                  (longest) match is a different, longer candidate prefix — they
                  would only "fall to" this prefix if that longer/nested sibling
                  is never added as its own reference row.
    Prevents nested prefixes (e.g. "Citroën C3" vs "Citroën C3 Aircross") from
    double-counting the same listing's impact under both the parent and child."""
    names = [str(r.get("Model auta", "")).lower() for r in unpaired]
    stats = {p: {"own": 0, "absorbed": 0, "projected": 0} for p in prefixes}
    for n in names:
        matches = [p for p in prefixes if n.startswith(p.lower())]
        if not matches:
            continue
        longest = max(matches, key=len)
        for p in matches:
            stats[p]["projected"] += 1
            stats[p]["own" if p == longest else "absorbed"] += 1
    return stats


def stub_row(cluster, fuel):
    if fuel != "ev":
        raise NotImplementedError("ICE stub handled in ICE mode task")
    row = {col: "" for col in ev_columns()}
    row["Model auta"] = cluster["prefix"]
    return row


def _num(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def validate_rows(rows, fuel, ref_models, unpaired):
    cols = ev_columns()  # EV only for now
    ref_low = [r.lower() for r in ref_models]
    unpaired_low = [str(r.get("Model auta", "")).lower() for r in unpaired]
    ok, errs = [], []
    seen = set()
    for i, raw in enumerate(rows):
        clean = {c: raw.get(c, "") for c in cols}
        model = str(clean.get("Model auta", "")).strip()
        problems = []
        if not model:
            problems.append(f"row {i}: prázdné 'Model auta'")
        # numeric ranges
        for col, (lo, hi) in EV_RANGES.items():
            rawv = str(clean.get(col, "")).strip()
            if rawv == "":
                continue
            val = _num(rawv)
            if val is None:
                problems.append(f"row {i} ({model}): {col}='{rawv}' není číslo")
            elif not (lo <= val <= hi):
                label = "baterie" if "baterie" in col else col
                problems.append(f"row {i} ({model}): {label}={val} mimo rozsah {lo}-{hi}")
        # Cd zdroj enum (only when Cd present)
        if str(clean.get("Cd", "")).strip():
            if clean.get("Cd zdroj") not in ("reálné", "odhad"):
                problems.append(f"row {i} ({model}): 'Cd zdroj' musí být reálné/odhad")
        # heat pump enum
        hp = str(clean.get("Tepelné čerpadlo možné (ano/ne)", "")).strip()
        if hp and hp not in ("ano", "ne"):
            problems.append(f"row {i} ({model}): tepelné čerpadlo musí být ano/ne")
        # duplicate vs existing + within-batch
        ml = model.lower()
        if ml in ref_low or ml in seen:
            problems.append(f"row {i} ({model}): duplicitní 'Model auta'")
        # over-broad prefix: a reference prefix must be at least brand+model (2 tokens);
        # a bare brand ("Renault") would pair unrelated cars.
        if model and len(model.split()) < 2 and any(n.startswith(ml) for n in unpaired_low):
            problems.append(f"row {i} ({model}): příliš obecný prefix (jen značka)")
        if problems:
            errs.extend(problems)
        else:
            seen.add(ml)
            ok.append(clean)
    return ok, errs


def _fmt_cell(col, val):
    if val is None or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if col == "Cd":
        return s.replace(",", ".")
    if re.fullmatch(r"-?\d+", s):
        return s
    if re.fullmatch(r"-?\d+\.0", s):
        return s[:-2]  # 520.0 -> 520
    if re.fullmatch(r"-?\d+[.,]\d+", s):
        return s.replace(".", ",")
    return s


def append_rows(fuel, rows, path=None):
    path = path or os.path.join(REF_DIR, REF_FILES[fuel])
    with open(path, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    # Ensure the file ends with a newline before appending; otherwise a new row
    # would glue onto the last existing line and corrupt both.
    needs_nl = False
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            needs_nl = f.read(1) != b"\n"
    with open(path, "a", newline="", encoding="utf-8") as f:
        if needs_nl:
            f.write("\n")
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            w.writerow([_fmt_cell(c, r.get(c, "")) for c in header])
    return len(rows)


def count_unpaired(cars_path, fuel):
    return len(load_unpaired(cars_path, fuel))


def _rebuild():
    import subprocess
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "build", "build_data.py")],
                   check=True, cwd=BASE_DIR)


_GAPS_ICE_UNSUPPORTED_MSG = (
    "gaps --fuel ice not implemented: ICE listings pair via "
    "scrapers.core.matching.match_to_authoritative (brand + model_base + "
    "weighted scoring), not the EV case-insensitive prefix join this command "
    "models — its clusters/projections would be semantically wrong for ICE. "
    "Use --fuel ev.\n"
    "gaps --fuel ice není implementováno: ICE inzeráty se párují přes "
    "scrapers.core.matching.match_to_authoritative (značka + model + vážené "
    "skóre), ne přes prefixové párování EV, které tento příkaz modeluje — "
    "shluky/projekce by pro ICE byly věcně špatně. Použij --fuel ev."
)


def _cmd_gaps(a):
    if a.fuel == "ice":
        sys.exit(_GAPS_ICE_UNSUPPORTED_MSG)
    if a.rebuild:
        _rebuild()
    unpaired = load_unpaired(CARS_PARQUET, a.fuel)
    ref_models = load_reference_models(a.fuel)
    clusters = cluster(unpaired, a.fuel)
    for c in clusters:
        c["klass"] = classify(c, ref_models)
    missing = [c for c in clusters if c["klass"] == "missing_ref"]
    norm = [c for c in clusters if c["klass"] == "normalization_gap"]
    total_missing = len(missing)

    # Own/absorbed split + nested-prefix warning are computed over the FULL
    # missing_ref candidate set (not the --top-sliced display list): a nested
    # child can be absorbed by a surfaced parent even if the child itself falls
    # outside the top N printed rows.
    missing_prefixes = [c["prefix"] for c in missing]
    stats = project_own_absorbed(missing_prefixes, unpaired)
    for c in missing:
        s = stats[c["prefix"]]
        c["projected"], c["own"], c["absorbed"] = s["projected"], s["own"], s["absorbed"]
    nested = find_nested_prefixes(missing_prefixes)
    volume_by_prefix = {c["prefix"]: c["volume"] for c in missing}

    if a.top:
        missing = missing[: a.top]
    outdir = os.path.join(BASE_DIR, "tmp", "ref-gap")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{a.fuel}-clusters.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"missing_ref": missing, "normalization_gap": norm}, f,
                  ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Nespárováno {a.fuel.upper()}: {len(unpaired)} inzerátů, "
          f"{len(clusters)} modelů ({total_missing} chybí v referencích, "
          f"{len(norm)} normalizace).")
    print(f"Top {len(missing)} z {total_missing} chybějících (→ {out}):")
    for c in missing:
        print(f"  {c['projected']:5d} (own {c['own']}, absorbed {c['absorbed']})  "
              f"{c['prefix']}   e.g. {c['sample_names'][:2]}")
    if nested:
        print("VAROVÁNÍ: vnořené prefixy — přidání rodiče samotného potichu pohltí dítě "
              "pod jeho specifikacemi (přidej OBA, nebo dítě zvlášť):")
        for parent, child in nested:
            print(f"  {parent!r} pohlcuje {child!r} "
                  f"(dítě má {volume_by_prefix.get(child, '?')} vlastních inzerátů)")
    if norm:
        print(f"Normalizační mezery (oprav BRAND_MAP/MODEL_CLEANUP, nepřidávej řádek):")
        for c in norm[:15]:
            print(f"  {c['volume']:5d}  {c['prefix']}")


def _cmd_validate(a):
    rows = json.load(open(a.infile, encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    ref_models = load_reference_models(a.fuel)
    unpaired = load_unpaired(CARS_PARQUET, a.fuel)
    ok, errs = validate_rows(rows, a.fuel, ref_models, unpaired)
    for e in errs:
        print("  CHYBA:", e)
    okfile = a.infile + ".ok.json"
    # Sort the validated rows by "Model auta" for deterministic output
    ok_sorted = sorted(ok, key=lambda r: r.get("Model auta", ""))
    with open(okfile, "w", encoding="utf-8") as f:
        json.dump(ok_sorted, f, ensure_ascii=False, indent=2)
    print(f"OK: {len(ok)}/{len(rows)} řádků prošlo → {okfile}")
    return 0 if not errs else 1


def _cmd_apply(a):
    rows = json.load(open(a.infile, encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    ref_models = load_reference_models(a.fuel)
    unpaired = load_unpaired(CARS_PARQUET, a.fuel)
    ok, errs = validate_rows(rows, a.fuel, ref_models, unpaired)
    if errs:
        for e in errs:
            print("  CHYBA:", e)
        print("Aplikace přerušena — oprav chyby.")
        return 1
    before = count_unpaired(CARS_PARQUET, a.fuel)
    n = append_rows(a.fuel, ok)
    _rebuild()
    after = count_unpaired(CARS_PARQUET, a.fuel)
    print(f"Přidáno {n} referenčních modelů ({a.fuel}).")
    print(f"Nespárováno: {before} → {after}  (−{before - after})")
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="grow-reference: covergrowth for reference models")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gaps", description="EV-only: ICE pairs via match_to_authoritative, "
                       "not this command's prefix-join model — see reference_gap._GAPS_ICE_UNSUPPORTED_MSG")
    g.add_argument("--fuel", required=True, choices=list(FUELS),
                    help="ev is fully supported; ice is accepted by argparse but rejected at "
                         "runtime with an explanation (ICE pairs via match_to_authoritative, "
                         "a different, non-prefix matching model — use ev)")
    g.add_argument("--rebuild", action="store_true"); g.add_argument("--top", type=int, default=0)
    g.set_defaults(fn=_cmd_gaps)
    v = sub.add_parser("validate"); v.add_argument("--fuel", required=True, choices=["ev"])
    v.add_argument("--in", dest="infile", required=True); v.set_defaults(fn=_cmd_validate)
    ap = sub.add_parser("apply"); ap.add_argument("--fuel", required=True, choices=["ev"])
    ap.add_argument("--in", dest="infile", required=True); ap.set_defaults(fn=_cmd_apply)
    args = p.parse_args(argv)
    rc = args.fn(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
