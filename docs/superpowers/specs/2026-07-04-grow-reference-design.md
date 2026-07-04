# grow-reference — agentic reference-model coverage tool

- **Date:** 2026-07-04
- **Status:** Approved design → planning
- **Worktree (throwaway):** `experiment/grow-reference`

## Problem

Scraped listings that match no reference model are "unpaired" (`Spárováno = Ne`).
On the current dataset:

- **EV:** 5251 unpaired listings across 152 distinct model names, against only 78
  reference rows in `ev_specs.csv`. High-volume misses: Renault Twingo (492),
  GWM Ora 03 (428), BYD Dolphin (285), Fiat Grande Panda (229), VW e-up! (193)…
- **ICE:** 44 unpaired listings, 34 names — a low-value long tail.
- ICE `Nejisté` (1815) is **out of scope**: that is matching/trim quality, not
  missing reference rows.

Reference rows are added by hand today. We want a **repeatable, agentic** way to find
the missing models, research their specs, and grow the reference lists so the unpaired
count keeps dropping after every scrape. **EV first** (≈99% of the volume); ICE is a
later mode of the same tool.

## Confirmed pairing rule (the fact the design hinges on)

`build/build_data.py::join_electric_reference` (line 302–304): an EV listing pairs
(`Ano`) iff

```
normalize_model(listing["Model auta"]).lower()  startswith  ref["Model auta"].lower()
```

— longest-prefix, case-insensitive. So a single missing prefix row (`"Renault Twingo"`)
leaves every Twingo unpaired, and adding it pairs all listings whose normalized name
starts with `"renault twingo"`. This makes both **classification** and **projection**
below deterministic and exact.

ICE pairs via `core/matching.match_to_authoritative` (brand + model_base + weighted
feature scoring, tri-state). ICE mode reuses that machinery; EV mode uses the prefix rule.

## Goals

1. Deterministically surface the missing reference models ranked by listing volume.
2. Distinguish **missing-reference** clusters (need a new row) from **normalization
   gaps** (an alias/case fix would pair them against an existing row — e.g. ORA Funky
   Cat = Ora 03). Never spend research on the latter.
3. Research real specs per missing model via subagents, with honesty guarantees.
4. Gate every new row behind human review (projected impact + specs + sources + diff).
5. On approval, append rows, rebuild, and report the **real** before/after unpaired drop.
6. Be re-runnable: after the next scrape, already-covered clusters drop out automatically.

## Non-goals

- Not touching ICE `Nejisté` (different root cause).
- Not auto-applying `BRAND_MAP` / `MODEL_CLEANUP` normalization fixes — those are
  surfaced as a report for the human, not written.
- No new runtime deps (stdlib + pandas only, per project rules).
- Not a scraper — it reads existing scrape CSVs and rebuilds `cars.json`; it never
  hits car-listing sites.

## Architecture (Approach B: skill + Python core + subagent fan-out)

Three layers:

1. **Deterministic core** — `build/reference_gap.py` (new, offline, unit-tested).
2. **Agentic research** — main thread dispatches haiku/sonnet subagents (WebSearch /
   WebFetch) per missing-reference cluster; each returns one structured candidate row.
3. **Review gate + apply** — human approves a subset; core appends, rebuilds, measures.

The repeatable entry point is a `/grow-reference` skill (mirrors the repo's existing
`ai-tasks` / `/triage` / `/work` idiom) whose instructions drive the three layers in
order. A thin `bin/grow_reference.sh` wraps the deterministic phases for manual use.

### Layer 1 — `build/reference_gap.py`

Pure functions (testable) + a small CLI. Reference schemas it must honor:

- **EV** (`ev_specs.csv`, comma-delimited, decimal cells quoted):
  `Model auta, Objem kufru (l), Hlučnost (dB), Kapacita baterie (kWh),
  Dojezd komb. letní WLTP (km), Dojezd komb. letní EV-database (km), Cd, Cd zdroj,
  Tepelné čerpadlo možné (ano/ne)`
- **ICE** (`ice_specs.csv`):
  `Jednoznačná varianta vozu, Značka, Model, Výbava, Generace, Karoserie, Počet míst,
  Objem motoru, Typ motoru, Palivo, Hybrid typ, Spotřeba (l/100 km), Objem kufru (l),
  Hlučnost (dB), Cd, Cd zdroj`

Functions:

- `load_unpaired(cars_json_path, fuel) -> list[dict]` — read `data`, filter `Typ` +
  `Spárováno == "Ne"`.
- `cluster(listings, fuel) -> list[Cluster]` — canonicalize each name
  (`normalize_model` + fuel-specific suffix stripping: hp/PS, battery kWh, trim), group,
  count volume, keep sample raw names + links.
- `classify(cluster, existing_ref) -> {"missing_ref" | "normalization_gap" | "covered"}`
  — simulate the prefix rule against existing `Model auta`; if a lightly-normalized /
  aliased variant would match, it's a `normalization_gap`.
- `rank(clusters)` — by listing volume desc.
- `project_newly_paired(new_prefixes, unpaired) -> {prefix: count}` — exact prefix
  simulation of how many currently-unpaired listings each proposed row would pair.
- `stub_row(cluster, fuel) -> dict` — reference-row skeleton. The EV `Model auta` is the
  shared brand+model **prefix of the actual stored listing strings** in the cluster (the
  join compares raw names, so the prefix must match them, not a re-normalized form);
  `normalize_model` is used only to *group* names, and `project_newly_paired` runs against
  the real unpaired strings so the gate shows true coverage. ICE structured fields
  inferrable from listings are pre-filled; spec fields left blank for research.
- `validate_rows(rows, fuel, existing_ref) -> (ok, errors)` — columns match header
  exactly; numeric ranges (EV: battery 10–150 kWh, range 100–800 km, trunk 50–800 l,
  noise 50–80 dB, Cd 0.20–0.45); `Cd zdroj ∈ {reálné, odhad}`; heat-pump `∈ {ano, ne}`;
  reject duplicate `Model auta` (EV) / `Jednoznačná varianta vozu` (ICE) vs existing;
  **reject over-broad prefixes** — a proposed EV `Model auta` that is a prefix of a
  *different* model's listings (e.g. bare `"Renault"`) is flagged, since it would pair
  unrelated cars.
- `append_rows(fuel, rows)` — append preserving the file's delimiter/quoting.
- `measure(before_json, after_json, fuel) -> {before, after, delta}`.

CLI:

```
python -m build.reference_gap gaps   --fuel ev [--rebuild] [--top N]   # → tmp/ref-gap/ev-clusters.json + normalization report
python -m build.reference_gap validate --fuel ev --in candidates.json  # → ok/errors
python -m build.reference_gap apply  --fuel ev --in approved.json       # append + rebuild + before/after
```

### Layer 2 — research subagent contract

For each top-N `missing_ref` cluster, dispatch one subagent (haiku default; sonnet when
the model is ambiguous/obscure). Prompt supplies: canonical model name, sample listing
titles + links, the exact target column list. Rules the subagent must obey:

- Return **strict JSON** with exactly the reference columns.
- **Cite a source URL** for every numeric spec (kept in a sidecar, not the CSV).
- **Never invent** battery/range/consumption — if not findable, leave blank + flag.
- `Cd`: use a real published value with `Cd zdroj = reálné`; only if none is findable,
  fall back to a body-shape estimate with `Cd zdroj = odhad`.
- Heat-pump possible: `ano`/`ne`.

Optional cheap **adversarial second pass**: a verifier subagent tries to refute each
row's specs; contradicted rows are dropped or downgraded to blank. On by default,
toggleable.

### Layer 3 — review gate + apply

Present a table — model │ volume │ projected newly-paired │ key specs │ Cd source
(reálné/odhad) │ research URLs — plus the raw CSV diff. Human approves a subset.
`apply` appends only approved rows, reruns `build/build_data.py`, and prints the real
before/after unpaired count (which validates the projection).

## Data flow (end to end)

```
/grow-reference --fuel ev --top 30
  1. reference_gap gaps --rebuild        → fresh cars.json, ranked clusters, norm-gap report
  2. (main thread) dispatch N research subagents over missing_ref clusters → candidate rows
  3. reference_gap validate              → drop malformed / dup / out-of-range rows
  4. GATE: show table + diff + projection → human approves subset
  5. reference_gap apply                 → append ev_specs.csv, rebuild, print real drop
```

## Testing

`tests/test_reference_gap.py` (stdlib `unittest`, offline, no network):

- clustering groups variant spellings of one model together;
- `classify` returns `missing_ref` vs `normalization_gap` vs `covered` correctly
  (fixtures include an alias case like Funky Cat ↔ Ora and an already-covered prefix);
- `validate_rows` rejects out-of-range numbers, bad `Cd zdroj`, duplicates, wrong columns;
- `project_newly_paired` counts prefix matches exactly.

`./bin/test.sh` must stay green (62 tests today).

## Repeatability & success criteria

- **Repeatable:** re-running after a new scrape re-derives gaps from the fresh
  `cars.json`; covered clusters vanish, only new gaps surface.
- **Success:** a demonstrated EV unpaired drop (adding the top ~30 EV models should
  clear on the order of 3–4k of the 5251), `./bin/test.sh` green, and **no fabricated
  specs** — every applied row is either sourced (`reálné`) or explicitly estimated
  (`odhad`), nothing invented.

## Throwaway-tree note

All work lives in the `experiment/grow-reference` worktree. It is a spike to prove the
approach and the unpaired drop; merging into `main` is a later, separate decision.
