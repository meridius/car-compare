"""Merge a blank-engine-type reference row into its single typed sibling.

Found while measuring the body audit: the biggest residual Ano loss was NOT the
taxonomy but pairs like

    Mazda 3 Hatchback 2.0 e-Skyactiv G   body=Hatchback vol=2.0 type=(blank)
    Mazda 3 2.0 SKYACTIV-G               body=Hatchback vol=2.0 type=SKYACTIV-G

These describe ONE car. Before the audit they carried DIFFERENT (wrong) bodies —
Fastback vs Hatchback — so the wrong label was accidentally doing the
discrimination; a Hatchback-tagged listing preferred one and matched confidently.
Once both are correctly Hatchback they score identically for any listing that does
not state its engine type, so the whole cluster ties into Nejisté (1 309 Mazda 3
listings alone).

Rule: within (brand, model, display body, engine vol, hybrid, trim, fuel), if
exactly one row has a blank `Typ motoru` and exactly ONE sibling has a type, the
blank row is a strictly-less-specific duplicate -> keep one row, carrying the
engine type over (so typed listings gain +2) and preferring the PK that names its
body (so the display name stays informative).

Deliberately NOT applied when there are 2+ typed siblings (e.g. Cupra Leon 1.5 vs
1.5 TSI vs 1.5 eTSI): there the blank row is a real "type unknown" catch-all and the
tie it creates is honest — a listing that never states its engine type genuinely
cannot be assigned one of two variants.
"""
import csv
import datetime
import sys

sys.path.insert(0, ".")
from scrapers.core import bodies  # noqa: E402

P = "scrapers/data/reference/ice_specs.csv"
TODAY = datetime.date.today().isoformat()

rows = list(csv.DictReader(open(P, encoding="utf-8")))
flds = list(rows[0].keys())


def norm_vol(v):
    v = (v or "").strip()
    try:
        return f"{float(v):.1f}"
    except ValueError:
        return v


def key(r):
    return (r["Značka"].strip(), r["Model"].strip(),
            bodies.to_display((r.get("Karoserie") or "").strip()),
            norm_vol(r.get("Objem motoru")),
            (r.get("Hybrid typ") or "").strip(),
            (r.get("Verze") or "").strip(),
            (r.get("Palivo") or "").strip())


BODY_TOKENS = sorted({t for syns in bodies._DISPLAY_SYNONYMS.values() for t in syns},
                     key=len, reverse=True)


def has_body_token(pk):
    low = pk.lower()
    return any(t.lower() in low for t in BODY_TOKENS)


groups = {}
for r in rows:
    groups.setdefault(key(r), []).append(r)

drop, report = set(), []
for k, grp in groups.items():
    if len(grp) < 2:
        continue
    blanks = [r for r in grp if not (r.get("Typ motoru") or "").strip()]
    typed = [r for r in grp if (r.get("Typ motoru") or "").strip()]
    if len(blanks) != 1 or len(typed) != 1:
        continue  # 0 or 2+ typed siblings -> honest ambiguity, leave alone
    blank, typ = blanks[0], typed[0]
    # Keep the PK that names its body; carry the engine type onto it.
    keep, gone = ((blank, typ) if has_body_token(blank["Jednoznačná varianta vozu"])
                  and not has_body_token(typ["Jednoznačná varianta vozu"])
                  else (typ, blank))
    if not (keep.get("Typ motoru") or "").strip():
        keep["Typ motoru"] = typ["Typ motoru"]
    keep["Upraveno"] = TODAY
    drop.add(gone["Jednoznačná varianta vozu"])
    report.append((keep["Jednoznačná varianta vozu"],
                   gone["Jednoznačná varianta vozu"], keep["Typ motoru"]))

out = [r for r in rows if r["Jednoznačná varianta vozu"] not in drop]
with open(P, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=flds, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    w.writerows(out)

print(f"merged {len(report)} blank-type duplicates")
for keep, gone, t in sorted(report):
    print(f"  keep {keep!r} (type={t!r})   drop {gone!r}")
print(f"rows: {len(rows)} -> {len(out)}")
