# Handoff — body taxonomy (Phase A done) + what's next

Written 2026-07-29. Read this first, then the design spec
`docs/superpowers/specs/2026-07-28-body-taxonomy-design.md` (it has the full Phase
A–E decomposition and an "Implementation outcome" section with the measurements).

## Where the code is

| | |
|---|---|
| Worktree | `.claude/worktrees/body-taxonomy` |
| Branch | `feature/body-taxonomy` — **3 commits, unmerged**, clean tree |
| `main` | **ahead of `origin/main` by 2, unpushed** (`83d2181`, `b1744d3`) |
| Tests | `./bin/test.sh` → **464 pass** |

Branch commits (oldest first):

```
86b3e96  docs(spec): body-style taxonomy design (Phase A)
aa58980  feat(bodies): one module owns the body taxonomy; display 9 vs scoring folded
6a7db11  fix(reference): audit every body label; neutral-zone body scoring
```

**Two decisions are waiting on Martin** and nothing should be pushed/merged without
him saying so: pushing `main`, and merging `feature/body-taxonomy`. The project
merge ritual is squash → rebase → `--ff-only` (see CLAUDE.md). One caveat learned
the hard way: that ritual assumes local `main == origin/main`; when `main` is ahead
(as now), rebase the branch onto **local `main`**, not `origin/main`, or the
`--ff-only` step is impossible.

## Run it locally on fresh data, no scraping

```bash
cd .claude/worktrees/body-taxonomy
./bin/bootstrap-data.sh --build   # pull state from the `data` release + rebuild payload
./bin/serve.sh                    # http://localhost:8000
```

- Needs `gh` auth (repo is private). It was authenticated as
  `martin-lukes01_notino` at handoff time.
- The worktree is **self-contained**: `scrapers/data/scrapes/*.parquet` are real
  files (earlier they were symlinks into the primary checkout — removed).
- State currently in the worktree is the **2026-07-28 08:33** CI scrape
  (mobile.de 202 253 rows, sauto 10 782, autodraft 580, energycars 54).
- A server was left running on `:8000` at handoff; it will not survive a reboot.

**Don't confuse the two data scripts.** `bootstrap-data.sh` pulls per-source
**state** from the release — that's what lets you rebuild with your own code.
`serve.sh --pull` pulls the **already-built payload from Pages**, which mirrors
prod exactly and ignores your local code. To check this branch you want the first.

## What Phase A actually changed

**New `scrapers/core/bodies.py` owns the taxonomy** (same single-source-of-truth
pattern as `core/filters.py`). It replaced **six** disagreeing tables:
`build_data._DISPLAY_BODY_CANON`, `matching._BODY_GROUPS`, `fields.BODY_KEYWORDS`,
`mobilede._CATEGORY_MAP`, a hard-coded `CANON` set in `test_data_integrity`, and
`bodyGroups` in `site/app.js`.

**Vocabulary 6 → 9 display values**: SUV, Kombi, Hatchback, **Liftback**, Sedan,
MPV, Kupé, **Kabriolet**, **Pick-up**.

**Scoring is a NEUTRAL ZONE, not a fold** — this is the load-bearing detail and the
spec's original design was wrong here. `_score_match`: exact body **+3**, same
family (Hatchback ↔ Liftback) **0**, different family **−2**. Folding Liftback into
Hatchback was implemented first and cost **−3 490 Ano**: it removes the false −2 a
mobile.de liftback (tagged `SmallCar` → Hatchback) takes against a Liftback row, but
it also destroys a real signal, so a listing whose text says "Sportback" can no
longer outrank the Hatchback sibling and same-engine siblings tie into `Nejisté`.

**Reference audited by 11 Opus agents** (10 ICE batches + 1 EV), 287 rows,
web-verified: 124 ICE + 6 EV bodies corrected, 3 degenerate rows deleted
(`BMW 2.0`, `GWM Haval 1.5`, `FAW Bestune 2.0`), 15 audit-created duplicates
collapsed, 11 blank-`Typ motoru` duplicates merged, 1 PK renamed. ICE rows
791 → 762. Blank bodies 45 → 10 (ICE) and 9 → 3 (EV).

### Numbers, on the same fresh 2026-07-28 state

| | release payload (`main`) | Phase A |
|---|---:|---:|
| live rows | 151 734 | 151 734 |
| Ano | 145 461 | **144 929** (−532) |
| Nejisté | 6 069 | **6 598** (+529) |
| body values | 6 | **9** (Liftback 3 130, Pick-up 154, Kabriolet 1) |

−0.37 % on confidence. Earlier measurement on 07-23 state gave −414, so the effect
is stable. The residual is false confidence that wrong body labels were
manufacturing — a coin-flip body is worse than an honest `Nejisté`.

### Three lessons that cost real time

1. **A fold was the wrong mechanism** (−3 490). See above. Swapping fold → neutral
   measured a **wash (−58)** on current data, because after the audit no nameplate
   has both a Hatchback and a Liftback row, so the family case is rare. Kept on
   correctness grounds, not results: the fold hands out a false **+3** for body
   agreement that never existed.
2. **Correcting the reference makes matching WORSE before better** (−3 380, then
   +4 053 once collapsed). Two rows previously distinguishable *by their wrong
   bodies* become identical on every scored field once both are right, so they can
   only tie. **A body audit is incomplete without a collapse pass.**
3. **The largest single loss was not the taxonomy at all** — blank-`Typ motoru`
   duplicate rows. `Mazda 3 Hatchback 2.0 e-Skyactiv G` had an empty engine type
   sitting next to `Mazda 3 2.0 SKYACTIV-G`; 1 309 Mazda 3 listings in one cluster.
   Merging 11 such pairs recovered **+2 461**.

Everything above is also in `docs/gotchas.md` under "core — matching (ICE)",
including a list of body-name traps (Sportback is not always Liftback — Audi Q3
Sportback is an SUV; Mazda 3 "Fastback" is the saloon; BMW 2-series Gran Coupé is a
Sedan; Mercedes CLA "Coupé" is a Sedan; Mitsubishi Grandis is now an SUV).

### Known wart

`Kabriolet` shows **1** row in the payload. `apply_reference_body_specs` overwrites
a matched listing's body from its reference row, and no reference row is a
Kabriolet yet, so ~22 real convertibles still display as Kupé. Working as designed
(reference-as-truth), but it is the one place the new vocabulary under-delivers.
Fix = add real Kabriolet reference rows, not code.

## Recommended next step (measured, not speculative)

Martin's original ask was rows with empty `Karoserie` **or `Verze`**. Phase A fixed
body. **`Verze` is still ~91 % blank in the payload and is the bigger gap** — and
it's what his Octavia example was really about (that car is a `1.5 eTSI mHEV
Sportline`, i.e. MHEV + trim `Sportline`, not the `iV` PHEV he guessed).

Two findings make it cheap:

**1. We already extract trims and then throw them away.** `apply_verze_display`
(`build/build_data.py`) does `df["Verze"] = ""` then fills only ICE-`Ano` rows from
the matched reference row's trim. But the reference carries `Verze` on **8 of 762
rows**, so the column is empty by construction — while state holds
`extract_trim()` results for ~33 % of mobile.de rows. The docstring's rationale is
sound ("a guess dressed up as a fact"); the cure killed the patient.

**2. The URL slug is untapped, already in state, zero network.** The
`Odkaz na auto` path segment carries the full un-truncated dealer title (mean 61
chars); `Extra` is truncated by mobile.de at ~40. Measured on a 20 000-row sample:

| source | yields a known `TRIM_KEYWORDS` match |
|---|---:|
| `Extra` (what we mine today) | **2.5 %** |
| URL slug | **32.3 %** |

~13× coverage for no scraping, and because it can run at **build** time all 202 k
existing rows heal immediately — no scrape needed.

**Proposed "Phase D-lite":**

1. Mine the slug for trim/engine tokens at build time → `Verze` ~2 % → ~35 %.
2. Let listing-derived trim through but **mark its provenance**, mirroring the
   existing `Cd` / `Cd zdroj` pattern: `Verze` shows the value, a sibling column
   says whether it came from the reference or was mined from the listing. That
   answers the "guess dressed as fact" objection honestly instead of by deletion.
3. Only then Phase C (reference variant fingerprints) and E (gap-driven loop) —
   both much larger.

**Do NOT do next:** mobile.de detail-page fetching. The endpoint is real and
keyless — `https://www.mobile.de/api/a/{id}` with header
`X-Mobile-Client: de.mobile.android.app`, returning un-truncated `title`/`subTitle`,
`attributes` (incl. `doorCount`, `numSeats`, `countryVersion`), `features[]`,
`htmlDescription`; no VIN. But it is ~150 k requests behind Akamai for signal the
slug largely already gives. Revisit only for what the slug cannot answer.

Cheap filler with no data risk: **Phase B**, the `karoserie.html` docs page. The 9
SVG silhouettes are already drawn, reviewed and committed at
`docs/superpowers/specs/assets/2026-07-28-body-silhouettes-v4.html` (+ `.png`).
Known nits to fix while porting: the kupé roof arc is thin; Hatchback vs Kombi
separate only on length + window count; SUV and MPV are the same silhouette family.

## Other useful context

- **sauto's detail call is already made and mostly discarded.** It returns
  `additional_model_name` (e.g. `"1.5 eTSI mHEV, Sportline"` — explicit trim!),
  `equipment_cb` (~60 items), `description`, `vin`, `doors`, `capacity`,
  `battery_capacity`, `gearbox_levels_cb`. Zero new requests to capture. But sauto
  is only ~2.5 k of 152 k rows, and adapter-side changes need a real scrape to
  take effect.
- **Build is slow and block-buffers.** A full rebuild on 152 k rows takes ~4 min,
  most of it "Re-matching combustion against authoritative list". Always run
  `python3 -u build/build_data.py` — without `-u`, stdout redirected to a file
  shows nothing until exit and looks hung.
- **Rebuild the payload before trusting the integrity suite.** Any reference PK
  change makes `test_confident_ice_model_matches_reference_entry` fail against a
  stale payload (it reported 2 938 offenders during the Octavia merge — all stale).
- **`cd` does not reliably persist between tool calls** in this setup. Several
  measurements were silently taken against the *primary* checkout instead of the
  worktree. Always `cd` explicitly in each command and check `pwd`.
- **Audit artifacts are preserved in-repo** at
  `docs/superpowers/specs/assets/2026-07-29-body-audit/`:
  - `verdicts_all.json` — the 287 agent body decisions, keyed by reference PK.
    Re-checkable against the CSV; this is the audit trail for every corrected body.
  - `body_queue.json` — the 93-nameplate review queue the plausible-pair detector
    produced, with every candidate row's fields. Regenerate it any time from
    `bodies.pairs_are_plausible`.
  - `collapse_dups.py` — collapses scoring-identical sibling rows an audit created
    (the +4 053 pass). Scoped to groups the audit touched; pre-existing groups
    (Mercedes GLB seat counts, X-Trail, C 220d/300d, KGM engine spellings) are
    deliberately left alone as Lever C.
  - `merge_blank_type.py` — merges a blank-`Typ motoru` row into its single typed
    sibling (the +2 461 pass). Deliberately skips groups with 2+ typed siblings,
    where the blank row is a real "type unknown" catch-all and the tie is honest.

  Both scripts are one-shot data migrations, not supported tooling: they rewrite
  `ice_specs.csv` in place and assume the worktree cwd. Read before re-running.
