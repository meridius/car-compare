# Handoff — body taxonomy (Phase A done) + what's next

Written 2026-07-29. Read this first, then the design spec
`docs/superpowers/specs/2026-07-28-body-taxonomy-design.md` (it has the full Phase
A–E decomposition and an "Implementation outcome" section with the measurements).

## Where the code is

| | |
|---|---|
| Worktree | `.claude/worktrees/body-taxonomy` |
| Branch | `feature/body-taxonomy` — **5 commits, unmerged**, pushed, clean tree |
| `main` | **in sync with `origin/main`** as of 2026-07-30 (`83d2181`) |
| Tests | `./bin/test.sh` → **464 pass** |

Branch commits (oldest first):

```
86b3e96  docs(spec): body-style taxonomy design (Phase A)
aa58980  feat(bodies): one module owns the body taxonomy; display 9 vs scoring folded
6a7db11  fix(reference): audit every body label; neutral-zone body scoring
4056abc  docs(handoff): Phase A state, local fresh-data recipe, next step
eb952ea  docs(bodies): verify Martin's Karoserie redesign proposal against Phase A
```

**One decision is waiting on Martin**: merging `feature/body-taxonomy`. The project
merge ritual is squash → rebase → `--ff-only` (see CLAUDE.md).

> **Status corrected 2026-07-30.** This block previously said `main` was ahead of
> `origin/main` by 2 unpushed commits, and warned that the merge ritual therefore
> needed a rebase onto **local** `main` rather than `origin/main`. Both were true
> when written; `main` has since been pushed and is now level with `origin/main`
> (`83d2181`, which is the squashed Octavia body-split fix and *is* an ancestor of
> this branch). The plain ritual applies again — but re-check with
> `git rev-list --count origin/main..main` before merging rather than trusting
> either version of this table.

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

## Addendum 2026-07-30 — Martin's "predefined values + conversion table" proposal, verified

Martin proposed a redesign in a later session, before knowing Phase A had landed:

> we should have a set of values for Karoserie predefined. when listing is scraped
> and no reference car is present for it, the value should match our predefined
> values or use the value in the listing. when listing already has reference car
> present, the Karoserie from listing should either match the reference car or use
> empty. we should probably have some conversion table from listing values to
> predefined ones. i'm not sure about the conditions above, you verify

Verified against the branch's own code + the 2026-07-28 state. Three of the four
asks **Phase A already delivered**; the fourth is measurably wrong as stated.

| ask | verdict |
|---|---|
| predefined value set | **done** — `bodies.CANONICAL`, 9 values |
| conversion table listing → predefined | **done** — `bodies.DISPLAY_FOLD` / `to_display()` |
| no reference → fold, else keep listing value | **already the behaviour**, unchanged |
| reference present → listing must match, or blank | **do not implement as stated** — see below |

### Why "match the reference or blank" is net-negative

Measured on 175 494 confidently-matched (`Ano`) ICE rows, counting only
**cross-family** disagreements (`bodies.same_family` excludes Hatchback ↔ Liftback,
which is not a real contradiction — 412 rows):

```
cross-family contradicting Ano rows      3 192   (1.82 % of Ano)
  ├─ reference has NO row for that
  │  nameplate in the listing's body     2 744   (86 %)  → listing is wrong
  └─ reference DOES know that nameplate
     in the listing's body                 448   (14 %)  → matcher mis-picked
```

Blanking all 3 192 throws away the 86 % where the reference is right and the
listing is seller noise — Mercedes B-class tagged `Kombi` (201), Ford Ranger tagged
`SUV` (170), VW Taigo tagged `Kupé` (114), Škoda Karoq tagged `Kombi` (93). That is
precisely the case `apply_reference_body_specs` exists to fix, and blanking would
also break `test_body_coverage_not_regressed` (blank ceiling 20).

**The instinct is right; the trigger is wrong.** A contradiction only carries
information when the reference *already* carries that nameplate in the listing's
body — then the matcher picked the wrong-body sibling, and the honest fix is to add
the missing sibling, not to blank the cell. That is the same bug shape as the
Octavia 2.0 report that started this work.

### The 448, and the discriminator that finds them

Top 7 groups are **426 of 448 (95 %)** — every one a missing body sibling:

| matched entry | ref body | listing body | rows | missing reference row |
|---|---|---|---:|---|
| `Cupra Leon 2.0 TDI` | Hatchback | Kombi | 193 | Leon Sportstourer 2.0 TDI |
| `Škoda Superb Combi Style 2.0 TDI` | Kombi | Liftback | 68 | Superb Liftback 2.0 TDI |
| `Opel Astra 1.6 PHEV` | Hatchback | Kombi | 65 | Astra Sports Tourer PHEV |
| `Hyundai i30 Kombi 1.5 T-GDI MHEV` | Kombi | Liftback | 37 | i30 hatchback 1.5 T-GDI MHEV |
| `Renault Talisman 1.3 TCe` | Sedan | Kombi | 25 | Talisman Grandtour 1.3 TCe |
| `Škoda Superb 2.0 TSI` | Kombi | Liftback | 21 | Superb Liftback 2.0 TSI |
| `VW Arteon Shooting Brake 2.0 TDI` | Kombi | Liftback | 17 | Arteon Liftback 2.0 TDI |

Full dump (all 3 192, `ref_knows` column separates the two buckets):
`docs/superpowers/specs/assets/2026-07-29-body-audit/body-contradictions.csv`.

**The discriminator must be family-aware.** Comparing bodies exactly reports 305
actionable rows; letting a `Hatchback` reference row cover a `Liftback` listing
(via `bodies.same_family`) reports **448**. The exact-match version silently hides
the whole Superb/i30/Arteon liftback family, because the reference labels those
nameplates `Hatchback` while the listings say `Liftback`. Reproduction script is
inline in the session transcript; it is ~30 lines over
`load_authoritative_list` + `match_to_authoritative` + `bodies.to_display`.

Worth making standing: this is the precise, measurable version of Martin's rule #4,
and it is a better guard than a blanket invariant — it flags only the rows where a
contradiction actually means something. Candidate home:
`tests/test_data_integrity.py` with a ceiling (448 today), or a `build/` report.

### Superseded by Phase A — do not re-derive

Measured pre-merge and now stale; recorded only so nobody redoes the work:

- **"There are two disagreeing canon tables (16 conflicts)"** — real then, fixed by
  `bodies.py`. Phase A actually replaced **six**.
- **"Liftback can't be its own value because 5 nameplates are inconsistently
  labelled"** (Audi A1, Audi A3, Mazda 3, Peugeot 408, Škoda Octavia) — the
  reference audit resolved all five; `Liftback` is now a real display value with
  3 130 rows.
- **"Only one listing body value is unmapped: `Allspace` (6 rows)"** — still true,
  and now deliberate: `bodies._NOT_A_BODY` lists it with Alltrack / Scout /
  OtherCar / Limousine / Andere. It is a trim leaking into the body field.
- **Pre-Phase-A contradiction counts** (2 651 → 2 451 rows, 351 groups, 82/18
  split) — superseded by the 3 192 / 86-14 numbers above. The split moved because
  the audit closed most genuine gaps; the *rate* rose because the vocabulary went
  6 → 9 values, so pairs that used to fold together now register as different.

### The root cause is still present at scale: 88 body-agnostic reference PKs

The Octavia bug was `Škoda Octavia 2.0 TDI` — a PK with **no body token** carrying
`Karoserie = Kombi`, so liftback listings matched it and had Kombi written onto them.
The audit fixed *labels*; it did not fix *PK ambiguity*. Still on the current CSV:

**88 reference rows whose PK carries no body token while their nameplate has 2+
display bodies** →
`docs/superpowers/specs/assets/2026-07-29-body-audit/body-agnostic-pks.csv`

Not all 88 are live bugs — the ambiguity only bites when a listing of the *other*
body actually matches that row, and the 448 measured above are the realized subset.
But it is the risk surface, and it maps straight onto the top offenders:
`Cupra Leon 2.0 TDI` (Hatchback; nameplate has Hatchback+Kombi),
`Škoda Superb 2.0 TSI` and `Škoda Superb TSI` (Kombi; nameplate has Hatchback+Kombi),
`Opel Astra 1.6 PHEV`, `Renault Talisman 1.3 TCe`, plus whole families never yet
looked at — `Audi A6 2.0/2.0 TFSI/3.0 TDI` and `Audi A4 2.0 TDI` (Sedan vs Avant),
`BMW 3 2.0` / `BMW 5 2.0` / `BMW 320 2.0 TSI` (Sedan vs Touring),
`Mercedes-Benz C 220d` / `C 300d` / `CLA` (Sedan vs Kombi),
`Dacia Jogger`, `Renault Espace`, `Opel Vivaro`, `Ford Tourneo Custom` (Kombi vs MPV).

Three rows in that list have a **blank** `Karoserie` and a multi-body nameplate —
`Citroën C5 1.6 PureTech`, `Citroën C5 1.6 PureTech PHEV`, `BMW 218 2.0` — so they
score the body field one-sided against every sibling and can only ever tie.

**Fix pattern is the one already proven on Octavia:** split per body, put the body
token in the PK (`… Liftback 2.0 TDI` / `… Combi 2.0 TDI`), and expect it to *cost*
`Ano` on body-silent listings — that cost is honest (see lesson 2 above). The
Octavia precedent measured 190 rows corrected for 201 rows Ano → Nejisté, and the
guards written for it are already in the tree:
`tests/test_matching.py::BodyAgnosticPKTest`, `OctaviaBodySplitTest`, and
`tests/test_build_data.py::ReferencePayloadKeyTest` (no reference payload key may
span two canonical bodies — this is what stops a naive same-PK split).

### Five PKs whose body token contradicts their own Karoserie column

```
Audi A3 Hatchback 40 TFSI e       PK Hatchback   column Liftback    (same family)
Ford Mondeo Liftback 2.0 EcoBlue  PK Liftback    column Hatchback   (same family)
Škoda Superb Liftback 1.5 TSI     PK Liftback    column Hatchback   (same family)
VW Arteon Liftback 2.0 TSI        PK Liftback    column Hatchback   (same family)
Fiat 500X Hatchback 1.4           PK Hatchback   column SUV         <-- real error
```

The four same-family ones are harmless to scoring under the neutral zone but make
the PK misleading and are why the family-aware discriminator was needed at all.
`Fiat 500X Hatchback 1.4` is a genuine mislabel — the 500X is a crossover; either
the PK token or the column is wrong.

### Verze — no new finding, but one correction

The earlier session independently measured 67 171 ICE state rows carrying an
extracted `Verze` against 7 091 surviving into the payload, and reached the same
conclusion as "Recommended next step" above. Nothing to add — **the URL-slug
finding (32.3 % vs 2.5 % from `Extra`) is the stronger lead and supersedes it.**
One correction to this file's own claim that the reference carries `Verze` on
"8 of 762 rows": on the current CSV it is 8 rows, confirmed — so `apply_verze_display`
really can only ever fill ~1 % of matched rows. The column is empty by construction,
not by data scarcity.

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
