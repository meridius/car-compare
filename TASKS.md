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

- [ ] **#16** https://www.sauto.cz/osobni/detail/volkswagen/id3/210446333 has 2002, but is really a 2022 model year — need to detect and fix these cases
  > ❓ Q1: Should we add detection/correction logic to the sauto scraper itself (in scrapers/sources/sauto.py) or to the build/post-processing pipeline (build_data.py)?
  > ❓ Q2: Do you have a pattern/rule for detecting 2-digit year swaps (e.g., all cases where year is 19XX but listing content suggests 20XX), or should we look for specific API field mismatches (in_operation_date vs manufacturing_date)?
  > ❓ Q3: Should corrected years be logged/tracked, or just silently fixed?

- [ ] **#17** https://www.sauto.cz/osobni/detail/dacia/bigster/210225179 has model year 1900, but is actually 2026 - detect and fix these cases
  > ❓ Q1: Is this part of the same fix as task 16, or a separate edge case (year = 1900 vs year = 19XX)? Should we apply both a swap-correction (19XX → 20XX) and a clamp/validation (1900 is invalid)?
  > ❓ Q2: What's the valid year range for this scraper (should be roughly 2021–2026 based on vehicle_age_from filter, correct)?
  > ❓ Q3: Should invalid years be rejected entirely (return None/skip row) or repaired (e.g., infer from in_operation_date fallback)?

- [ ] **#18** web UI should display set filters above the table on both pages
  > ❓ Q1: Should the filter display be a persistent bar above the grid, or a modal/collapsible section? (e.g., 'Active filters: Typ=Elektrické Palivo=Benzín [×] [×]')
  > ❓ Q2: Should clicking a filter tag remove that filter, or only show it for reference?
  > ❓ Q3: Does this need to appear on both index and reference pages, or just one?

- [ ] **#19** many reference models are missing data in various cols
  > ❓ Q1: Which columns in the reference data are missing (e.g., Objem kufru, Hlučnost, Kapacita baterie)? Should we prioritize filling any particular ones?
  > ❓ Q2: Is the ask to manually audit/add the missing data to the reference CSVs (ice_specs.csv / ev_specs.csv), or to detect/flag the gaps in the UI?
  > ❓ Q3: For EV vs ICE — are different sets of columns expected to be populated?

- [ ] **#20** reorder cols in the reference table to match the main table for easier visual scanning
  > ❓ Q1: Should the reference table match the column order of the main cars table exactly, or follow a different but more logical order?
  > ❓ Q2: Which columns are currently in the reference table (site/reference.html / build_reference_json() output)? What is the desired order?

- [ ] **#21** there should be automated tests for data integrity issues like mismatch between data in Model col and relevant cols, format of all data in each col
  > ❓ Q1: Should these tests run as part of the scrape pipeline (e.g., post-build in build_data.py, or in scrapers/core/), as CI/CD checks, or both?
  > ❓ Q2: What specific mismatches concern you (e.g., model year format, price format, 19XX year swaps, missing required fields)?
  > ❓ Q3: Should failing tests block the build/deploy, or only warn/log?

## Atomic

Ready to execute. Pick next unchecked item, use its `flow · model · effort` metadata to run.

- [ ] **#12** Fix EV `Spárováno` = null vs ICE `Spárováno` = "Ne" asymmetry (`build/build_data.py`)
  > flow:ralph · model:haiku · effort:low

- [ ] **#13** Normalize "Ne" / "Ano" values to proper case in all fields across all sources
  > flow:ralph · model:haiku · effort:low

- [ ] **#14** Report empty `Spárováno` values in UI (so pairing gaps are visible and actionable)
  > flow:ralph · model:sonnet · effort:medium

- [ ] **#15** json data files should have static order of lines for cleaner diffs, no single line for everything
  > flow:feature-dev · model:haiku · effort:low

- [ ] **#22** scroll bars in tables are very thin and hard to use since they are hidden behind the page scroll bar
  > flow:ralph · model:haiku · effort:low

## Done

- [x] **#11** Fix `merge_with_previous` NaN-link bug: `set_index("Odkaz na auto").loc[link]` drops index col, clobbering link on rows present in both scrapes (`scrapers/core/merge.py`)
  > flow:ralph · model:haiku · effort:low

- [x] **#10** Use decimals in "%" col of "Párování s referenčními modely" table in dataset overview
  > flow:ralph · model:haiku · effort:low

- [x] **#9** Add "Celkem" row to bottom of "Karoserie × Pohon" table in dataset overview; separate Celkem row/col with bolder lines
  > flow:ralph · model:sonnet · effort:medium

- [x] **#8** Reference page row height = main page row height
  > flow:ralph · model:haiku · effort:low

- [x] **#7** "Objem motoru" col sortable + filterable as numbers
  > flow:ralph · model:sonnet · effort:low
