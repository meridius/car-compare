# /grow-reference — grow reference models to cut unpaired listings

Repeatable loop. Two independent tracks — **EV** (prefix-join gaps) and **ICE**
(matcher-simulated candidate rows). Run one fuel at a time end-to-end.

All research is a **single-pass web agent per row** (see §Research contract). Do
**not** split model tiers by cluster size and do **not** add a second "verify"
subagent stage — fold the cross-check into the one research pass. Research is
I/O-bound reconciliation across spec sources; use a strong model (**Opus**,
effort `high`). Keep the agent graph **flat, ≤1 subagent level** (workflow →
`agent()`; the agent uses WebSearch/WebFetch tools, never spawns its own
subagents). Run the two fuels' workflows **sequentially**, not concurrently —
each stays inside one budget window and the session limit can't truncate the tail.

Scratch lives in `tmp/ref-gap/` (git-ignored). Salvage after every run: if a
workflow hits the session limit mid-run, its completed agents are in
`journal.jsonl` under the run's transcript dir — reload them and resume; don't
re-pay for finished rows.

---

## EV track

### E1. Find the gaps (deterministic)
`./bin/grow-reference.sh gaps --fuel ev --rebuild --top 30`

Rebuilds the payload, writes ranked missing-reference clusters to
`tmp/ref-gap/ev-clusters.json`, prints projected newly-paired counts. Note the
current unpaired total.

- **`gaps` reads `site/data/cars.parquet`**, whose "Model auta" column is split
  into Značka+Model and dropped (`write_payload`, task #3). `load_unpaired`
  reconstructs the name — if a payload change ever makes clusters come back empty
  against a nonzero unpaired count, that reconstruction broke (pinned by
  `test_load_unpaired_reconstructs_model_from_brand_model_split`).
- Skim the **"Normalizační mezery"** list — those pair via a BRAND_MAP /
  MODEL_CLEANUP fix, **not** a new row. Report them; fix in `core/normalize.py`.
- **Exclude `Andere` clusters** (mobile.de's "Other" junk bucket, like sauto's
  "Ostatní"): never add an "X Andere" reference row — it would prefix-match every
  future unindexed car of that brand. Report as an adapter-recovery TODO.
- `own` vs `absorbed` per cluster: add nested siblings together or the parent
  silently swallows the child under its specs (see the VAROVÁNÍ block).

### E2. Research each missing model (one Opus agent per cluster)
Read `tmp/ref-gap/ev-clusters.json` → `missing_ref`. One agent per `prefix`.
See §Research contract (EV field set). Collect returned rows (mapped to the
Czech `ev_specs.csv` columns) into `tmp/ref-gap/candidates.json`.

### E3. Validate
`./bin/grow-reference.sh validate --fuel ev --in tmp/ref-gap/candidates.json`
Fix or drop rejects. Result: `candidates.json.ok.json`. Drop `confidence:none`
rows (model has no BEV version) — report them, don't add.

### E4. Review gate + apply
Present a table (model | projected paired | battery | WLTP | Cd | Cd zdroj |
sources). Get the go on which rows to keep → `tmp/ref-gap/approved.json`, then
`./bin/grow-reference.sh apply --fuel ev --in tmp/ref-gap/approved.json`.
Report `Nespárováno: BEFORE → AFTER (−DELTA)`; `./bin/test.sh` stays green.

---

## ICE track

There is **no `gaps --fuel ice`** — ICE pairs via `matching.match_to_authoritative`
(brand + model_base + weighted scoring), not a prefix join. Candidate rows are
generated and their pairing impact simulated with the real scorer.

### I1. Generate candidate rows (deterministic, matcher-simulated)
`python3 tmp/ref-gap/gen_ice_candidates.py [--min-group 10 --min-combo 8]`

Clusters the `Spárováno==Ne` ICE listings by matcher-parsed (brand, model_base),
derives one candidate row per dominant `(engine_vol, fuel, hybrid, body)` combo,
then **merges tie-prone siblings** (engine-type is dropped — it's extraction
noise; vols within ±0.15 l and blank-field subsets are absorbed, else two rows
tie every listing into `Nejisté`). Prints the simulated
`BEFORE → AFTER {Ano, Nejisté, Ne}` delta from re-running `classify_match` with
the candidates appended. Writes `tmp/ref-gap/ice-candidates.json`.

### I2. Research each candidate (one Opus agent per row)
See §Research contract (ICE field set). The configuration
(vol/fuel/hybrid/body) is **fixed** from listing data — research fills display
specs (Generace, Počet míst, Spotřeba, kufr, dB, Cd) and answers **`exists`**:
does this factory configuration really ship?

- **mobile.de fabricates hybrids.** It files mild hybrids under the same
  `Hybrid (Benzin/Elektro)` umbrella, so the generator emits e.g. "BMW 118 PHEV"
  that never existed. Drop `exists:false` rows whose note says the hybrid variant
  is fabricated (the mislabeled listings still pair with the non-hybrid row —
  one-sided hybrid penalty is only −1 — while a fake sibling ties everything into
  Nejisté; simulation confirms dropping them *raises* Ano). Keep genuine PHEVs
  (330e, DS7 E-Tense…).

### I3. Apply + measure
`python3 tmp/ref-gap/apply_ice.py --research tmp/ref-gap/ice-research-results.json --dry-run`
Review `exists=false` flags, then rerun without `--dry-run`. It merges research
specs into the generated rows, range-validates numerics (blanks out-of-range),
skips duplicates, and appends to `ice_specs.csv`. Then `python3 build/build_data.py`
and re-run `gen_ice_candidates.py` to confirm the **real** delta matches the
simulation; `./bin/test.sh` green.

`append_rows` auto-stamps `Přidáno` + `Upraveno` = today on each new row — never
hand-fill those columns. `build/backfill_ref_dates.py` reconciles them against git
history on later runs (see docs/gotchas.md → build → reference date columns).

---

## Research contract (single Opus pass, self-verifying)

One `agent()` per row, model **Opus**, effort `high`. The agent:
1. Identifies the real EU variant (model year 2021+) for the given name/config.
   Listing names may omit EV badging or misclassify body — resolve to the actual
   car (e.g. "Opel Astra" EV → Astra Electric; "Citroën C3" EV → ë-C3).
2. Fills the spec fields from **official manufacturer / ev-database.org /
   Wikipedia / ADAC / auto-data.net**. **Never invents** — blank (`""`) when not
   found. Picks the **most common EU variant** when several exist; notes which.
3. **Self-verifies** battery+range (EV) or consumption+trunk (ICE) against a
   *second independent source* in the same pass; blanks the cell on >15–20%
   conflict. (This replaces the old separate verify subagent.)
4. Returns `confidence` (high/medium/low) and, for names shared with combustion
   or fabricated by the scraper, an existence verdict (EV: `confidence:none` if
   no BEV; ICE: `exists:false`).

**StructuredOutput schema keys must be ASCII** (`^[a-zA-Z0-9_.-]{1,64}$`) — the
API rejects Czech column names as property keys. Use snake_case keys
(`battery_kwh`, `wltp_km`, `trunk_l`, `cd`, `cd_source`, …) and map them to the
Czech CSV columns in the workflow's final pipeline stage. Force `Model auta` /
`name` to the cluster/candidate value verbatim — never trust the agent's echo
(it's the join key).

Cd: real published value → `Cd zdroj = reálné`; only if none exists, estimate
from body shape → `odhad`.

**Workflow `args`**: pass the cluster/row list as an actual JSON value, and guard
`typeof args === 'string' ? JSON.parse(args) : args` at the top (resume replays
args as a string).
