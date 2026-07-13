# mobile.de "Limousine" body ambiguity — design

**Date:** 2026-07-13
**Status:** approved

## Problem

mobile.de's `attr.c` category taxonomy returns `"Limousine"` for many body
types, not just sedans. German dealers tag hatchbacks (Golf, Focus, BMW 1-series,
Cupra Born), and the endpoint even returns it for EVs that are crossovers /
hatchbacks (BMW i3, BYD ATTO 2, Audi Q4 e-tron Sportback — all mis-tagged
`Sedan/limuzína` in current state).

`_CATEGORY_MAP["Limousine"] = "Sedan/limuzína"` therefore stamps a confident but
frequently-wrong `Karoserie`. Two consequences:

1. **Matching poison** — `matching.py` scores body at weight 3. A hatchback
   listing carrying `Sedan/limuzína` is penalised against the correct hatchback
   reference entry, and cluster body votes / `diagnose_unpaired` candidate rows
   inherit the fake body (research on Ford Focus + Audi A3 candidates confirmed
   the body had to be blanked by hand before `apply`).
2. **Wrong per-listing display body** on unmatched rows.

## Decision

Map `"Limousine" → ""` at the adapter (`_CATEGORY_MAP`). Rejected alternatives:
per-source downweight in `matching.py` (breaks its source-agnostic contract) and
title-based sedan/hatch classification (fragile — German titles rarely carry the
body word).

## Mechanism

`_build_row` line 202 already falls back to the free-text extractor when the map
yields blank:

```python
body = _CATEGORY_MAP.get(attr.get("c", ""), "") or extract_body_type(title_text)
```

`BODY_KEYWORDS` (core/fields.py) contains **no** Sedan/Limousine/Limuzína token,
so `extract_body_type` never re-derives sedan from a German "Limousine" title. It
*does* recover a real token when the title carries one (`Sportback`, `Combi`,
`SUV`, `Variant`, …). Otherwise the body is left blank and filled downstream:

- **Matched ICE (Ano/Nejisté)** → `apply_reference_body_specs` overwrites
  `Karoserie` from the reference entry (correct regardless of the listing).
- **Unmatched / EV** → `canonicalize_body` majority vote, then `derive_body` from
  the model name.

This makes `"Limousine"` behave exactly like the existing `"OtherCar": ""` entry
— the taxonomy's own "unknown" bucket.

## Cost (accepted)

True unmatched sedans lose their explicit tag and fall to `derive_body`, which
cannot always infer "Sedan". Accepted: most `"Limousine"` rows were mis-tagged, so
net body accuracy rises, and matched sedans still get the correct body from the
reference.

## Test

`tests/test_mobilede.py`:
- Limousine item + plain German title → `Karoserie == ""`.
- Limousine item + title carrying `"Sportback"` → `Karoserie == "Sportback"`
  (fallback still recovers real tokens).

## Docs to update

- `docs/gotchas.md` → mobile.de category note.
- `docs/architecture.md` → `_CATEGORY_MAP` description line.
- `docs/superpowers/specs/2026-07-04-mobilede-source-design.md` line 86.
