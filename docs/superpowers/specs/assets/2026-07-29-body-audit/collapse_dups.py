"""Collapse reference rows the body audit made scoring-identical.

After the audit, some sibling rows describe the SAME car and are identical on every
field matching scores on (canon body, hybrid, engine vol/type, trim, fuel) — e.g.
"Seat Ibiza Sedan 1.5" and "Seat Ibiza Hatchback 1.5" both became Hatchback, because
no Ibiza saloon exists. Two rows that can never be told apart can only ever TIE,
which demotes the whole cluster to Nejisté (classify_match margin rule).

Scope guard: only groups the audit actually touched are collapsed. Pre-existing
scoring-identical groups (Mercedes GLB 5míst/7míst, Nissan X-Trail seat counts,
Mercedes C 220d/300d, KGM Tivoli/Torres engine spellings) are left ALONE — those are
Lever C (reference hygiene), a separate decision about genuinely distinct variants.

Keep-one rule inside a collapsed group, highest score wins:
  2 - PK body token agrees with the audited body
  1 - PK carries no body token
  0 - PK body token contradicts the audited body (the row research disproved)
tie-break: longer PK (more specific).
"""
import csv
import json
import sys

sys.path.insert(0, ".")
from scrapers.core import bodies  # noqa: E402

SP = ("/tmp/claude-1000/-home-martin-projects-meridius-auto/"
      "94cba301-ec72-4eb8-855c-29d0bf0c3f54/scratchpad")
P = "scrapers/data/reference/ice_specs.csv"

verdicts = json.load(open(f"{SP}/verdicts_all.json"))
rows = list(csv.DictReader(open(P, encoding="utf-8")))
flds = list(rows[0].keys())

# Body tokens that can appear in a PK, longest first so "Shooting Brake" wins.
TOKENS = sorted(
    {t for syns in bodies._DISPLAY_SYNONYMS.values() for t in syns},
    key=len, reverse=True,
)


def pk_body_token(pk):
    low = pk.lower()
    for t in TOKENS:
        if t.lower() in low:
            return bodies.to_display(t)
    return None


def score_key(r):
    return (r["Značka"].strip(), r["Model"].strip(),
            bodies.to_scoring((r.get("Karoserie") or "").strip()),
            (r.get("Hybrid typ") or "").strip(),
            (r.get("Objem motoru") or "").strip(),
            (r.get("Typ motoru") or "").strip(),
            (r.get("Verze") or "").strip(),
            (r.get("Palivo") or "").strip())


groups = {}
for r in rows:
    groups.setdefault(score_key(r), []).append(r)

drop = set()
report = []
for k, grp in groups.items():
    if len(grp) < 2:
        continue
    audited = [r for r in grp if r["Jednoznačná varianta vozu"] in verdicts]
    if not audited:
        continue  # pre-existing group — Lever C, not ours to touch

    def rank(r):
        pk = r["Jednoznačná varianta vozu"]
        tok = pk_body_token(pk)
        body = (r.get("Karoserie") or "").strip()
        if tok is None:
            s = 1
        elif tok == body:
            s = 2
        else:
            s = 0
        return (s, len(pk))

    keep = max(grp, key=rank)
    for r in grp:
        if r is not keep:
            drop.add(r["Jednoznačná varianta vozu"])
    report.append((k[0] + " " + k[1], keep["Jednoznačná varianta vozu"],
                   [r["Jednoznačná varianta vozu"] for r in grp if r is not keep]))

out = [r for r in rows if r["Jednoznačná varianta vozu"] not in drop]
with open(P, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=flds, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    w.writerows(out)

print(f"collapsed {len(report)} audit-created groups, dropped {len(drop)} rows")
for name, keep, dropped in sorted(report):
    print(f"  {name}: keep {keep!r}")
    for d in dropped:
        print(f"      drop {d!r}")
print(f"rows: {len(rows)} -> {len(out)}")
