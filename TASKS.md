# Tasks

> **Workflow:**
>
> 1. Add tasks to `## New`
> 2. Run `/triage` (or `./bin/triage.sh` non-interactively) — classifies tasks, assigns ID + routing metadata, moves them to the right section
> 3. Answer questions under `## Needs Scoping` in chat (reply directly under each Q line), then re-run `/triage` to promote to Atomic
> 4. Run `/work` (or `./bin/work.sh`) to execute next Atomic task; `./bin/work.sh --all` to drain the queue
>
> Tasks can declare `· blocked-by: #N` in their metadata — `/work` skips them until the blocker is done.

## New

<!-- Add new tasks here, then run /triage -->

## Needs Scoping

Tasks below need your input. Reply directly under each Q line in chat, then run `/triage` to promote to Atomic.

- [ ] **#1** add mobile.de
  > ❓ Q1: Requires browser scraping or REST API available?
  > ❓ Q2: Czech listings only or EU-wide?
  > ❓ Q3: Same canonical schema, or new fields needed?

- [ ] **#2** widen scraping on sauto.cz and other sites
  > ❓ Q1: Which filters to relax? (price ceiling, year floor, km ceiling, body types?)
  > ❓ Q2: Any other sites in scope besides sauto?

- [ ] **#3** split "Model auta" col into "Značka" + "Model" displayed in that order
  > ❓ Q1: Split client-side in app.js/reference.js, or emit separate fields from build_data.py?
  > ❓ Q2: Matching and reference enrichment key on "Model auta" — how should they behave post-split?

- [ ] **#4** "Model auta" should not contain Objem motoru / Typ motoru values
  > ❓ Q1: Strip from scraped names only, or also from reference CSVs?
  > ❓ Q2: Does stripping break the reference join key for ICE?

- [ ] **#5** add Karoserie (and other cols) to Referenční modely page for matching
  > ❓ Q1: Which columns specifically — just Karoserie, or also Palivo / Objem / Výkon?
  > ❓ Q2: Are these already in ice_specs.csv / ev_specs.csv, or need adding to reference CSVs?

## Atomic

Ready to execute. Pick next unchecked item, use its `flow · model · effort` metadata to run.

- [ ] **#9** Add "Celkem" row to bottom of "Karoserie × Pohon" table in dataset overview; separate Celkem row/col with bolder lines
  > flow:ralph · model:sonnet · effort:medium

- [ ] **#10** Use decimals in "%" col of "Párování s referenčními modely" table in dataset overview
  > flow:ralph · model:haiku · effort:low

- [ ] **#11** Fix `merge_with_previous` NaN-link bug: `set_index("Odkaz na auto").loc[link]` drops index col, clobbering link on rows present in both scrapes (`scrapers/core/merge.py`)
  > flow:ralph · model:haiku · effort:low

- [ ] **#12** Fix EV `Spárováno` = null vs ICE `Spárováno` = "Ne" asymmetry (`build/build_data.py`)
  > flow:ralph · model:haiku · effort:low

- [ ] **#13** Normalize "Ne" / "Ano" values to proper case in all fields across all sources
  > flow:ralph · model:haiku · effort:low

- [ ] **#14** Report empty `Spárováno` values in UI (so pairing gaps are visible and actionable)
  > flow:ralph · model:sonnet · effort:medium

- [ ] **#15** json data files should have static order of lines for cleaner diffs, no single line for everything
  > flow:feature-dev · model:haiku · effort:low

## Done

- [x] **#8** Reference page row height = main page row height
  > flow:ralph · model:haiku · effort:low

- [x] **#7** "Objem motoru" col sortable + filterable as numbers
  > flow:ralph · model:sonnet · effort:low
