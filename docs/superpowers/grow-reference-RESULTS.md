# grow-reference — demonstration results

**Date:** 2026-07-04 · **Branch:** `experiment/grow-reference` (throwaway spike)

## What this is

An agentic, repeatable tool that finds the car models missing from the reference
lists, researches their specs via subagents behind a human review gate, and grows
`ev_specs.csv` / `ice_specs.csv` so the unpaired-listing count drops. See the design
(`docs/superpowers/specs/2026-07-04-grow-reference-design.md`) and plan
(`docs/superpowers/plans/2026-07-04-grow-reference.md`).

Deliverables:
- `build/reference_gap.py` — deterministic core + CLI (`gaps` / `validate` / `apply`), offline unit-tested.
- `tests/test_reference_gap.py` — 20 offline tests (part of the 82-test suite).
- `.claude/commands/grow-reference.md` — interactive orchestration recipe.
- `bin/grow-reference.sh` — deterministic-phase wrapper.

## Result (EV, first pass)

```
Nespárováno EV: 5232 → 2165  (−3067)
```

12 reference models added; the projected drop (3067, longest-prefix simulation) matched
the **measured** drop exactly. `ev_specs.csv`: 78 → 90 rows. `./bin/test.sh`: 81/81 green.

| Model (prefix) | paired | battery kWh | WLTP km | Cd | Cd zdroj |
|---|--:|--:|--:|--:|---|
| Renault Twingo | 492 | 27.5 | 263 | — | *(blanked)* |
| GWM Ora 03 | 421 | 45.4 | 310 | 0.33 | odhad |
| BYD DOLPHIN | 285 | 60 | 427 | 0.301 | reálné |
| ORA Funky Cat | 277 | 45.4 | 310 | 0.33 | odhad |
| Opel Frontera | 232 | 44 | 305 | — | — |
| Renault Megane | 229 | 60 | 450 | 0.29 | reálné |
| Fiat Grande Panda | 227 | 43.8 | 320 | — | — |
| Citroën ë-C3 | 196 | 43.8 | 327 | — | — |
| VW e-up! | 193 | 32.3 | 260 | 0.31 | reálné |
| Citroën C4 (ë-C4) | 175 | 46.3 | 354 | 0.30 | odhad |
| Leapmotor T03 | 171 | 36 | 265 | 0.33 | odhad |
| Renault R 5 | 169 | 52 | 402 | 0.32 | odhad |

## Honesty controls (why the numbers are trustworthy)

- Every numeric spec carries an ev-database.org / manufacturer source URL (sidecar in
  `tmp/ref-gap/candidates.json`).
- **Nothing fabricated.** Where a value wasn't found it is blank (Cd on Twingo / Opel
  Frontera / Fiat Grande Panda / ë-C3; EV-database range on several).
- The controller honesty pass caught and corrected two research errors before anything
  was written: **Twingo Cd 0.656** (physically impossible) → blanked; **GWM Ora 03 Cd
  0.29 "reálné"** with a non-URL "source" → downgraded to `0.33 odhad`.
- `validate_rows` rejects out-of-range numbers, bad `Cd zdroj`, duplicates, over-broad
  prefixes, and non-numeric junk cells before append — all 12 passed.

## Repeatability

Re-run `/grow-reference` (or `./bin/grow-reference.sh gaps --fuel ev --rebuild`) after
any scrape: gaps are re-derived from the fresh `cars.json`, the 12 now-covered models
drop out, and only the remaining ~136 EV gaps surface. This first pass took the top 12
of ~148 missing models; a second pass clears the next tier.

## Known limitations → logged in TASKS.md

1. **Duplicate rows for one physical car under multiple names** — GWM Ora 03 and ORA
   Funky Cat are the same car, added as two rows because listings use two spellings and
   the join is prefix-based. Needs a normalization/alias mechanism.
2. **EV join ignores diacritics** — mobile.de strips accents while other sources keep
   them; one reference row can't pair both spellings. Accent-folding the join would lift
   coverage with no new rows.

Both were discovered by this demo and are written up as tasks under `## New` in TASKS.md.

## Not done here (scoped out)

- The remaining ~136 EV gap models (long tail) — same pipeline, more passes.
- ICE mode — `stub_row`/`validate_rows`/CLI guard EV-only; ICE `Ne` is only 44 listings.
  Adding it reuses the deterministic core + a variant-level research contract.
