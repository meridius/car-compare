# Tasks

> **Workflow:**
>
> 1. Add tasks to `## New`
> 2. Run `/tasks-triage` (or `./bin/ai-tasks-triage.sh` non-interactively) — classifies tasks, assigns ID + routing metadata, moves them to the right section. Policy: **default-and-proceed** — the classifier assumes sensible defaults (recorded in a `📌 assumes:` line) and promotes to Atomic; only genuinely owner-only decisions (new data source, cost, irreversible) go to Needs Scoping.
> 3. Answer questions under `## Needs Scoping` in chat (reply directly under each Q line), then re-run `/tasks-triage` to promote to Atomic. **Veto any `📌 assumes:` line you disagree with** before running `/tasks-work`.
> 4. Run `/tasks-work` (or `./bin/ai-tasks-work.sh`) to execute next Atomic task; `./bin/ai-tasks-work.sh --all` to drain the queue. Every feature is **test-driven / test-verified** — `./bin/test.sh` must pass.
>
> Tasks can declare `· blocked-by: #N` in their metadata — `/tasks-work` skips them until the blocker is done.

## New

<!-- Add new tasks here, then run /tasks-triage -->

- [ ] **Scalable storage for large scrapes (enable DE ICE)** — CSV-in-git doesn't scale to the German ICE market. mobile.de DE ICE alone is ~123k listings under our filters (vs ~1.3k for CZ+SK+AT+PL); enabling it (`ICE_COUNTRIES += "DE"` in `scrapers/sources/mobilede.py`) would push `mobilede.csv` + `cars.json` to hundreds of MB — too big to commit as plain text and to ship as a single Pages JSON. Evaluate: (a) **Git LFS** for the scrape CSVs + built JSON (keeps the current pipeline, just changes how blobs are stored); (b) **SQLite** as the pipeline's storage/query layer (build queries it instead of concatenating CSVs; Pages still needs a JSON export, possibly paginated/filtered server-side or split per-country); (c) hybrid — SQLite of record + LFS for the committed DB. Also reconsider the AG Grid payload: 250k+ rows in one `cars.json` (~200 MB) won't load client-side — likely need server-side row model, pre-filtered shards, or a small API. Decide storage + delivery together before flipping DE on. Note: conflicts with the "CSVs are the sole output format" rule in `docs/conventions.md` — that rule needs revisiting as part of this.

- [ ] **Verze column plumbing** — rename canonical `Výbava` → `Verze` (one column, net 25 cols) and move its display position to right after `Model auta` on BOTH the main grid (`site/app.js`) and reference page (`site/reference.js`). Source of truth = matched reference row's version; unmatched/ambiguous → blank. Touch: `scrapers/core/schema.py`, `scrapers/sources/sauto.py`, `scrapers/sources/autodraft.py`, `scrapers/core/matching.py`, `build/build_data.py`, both JS files. Re-match + `verify_ui.py` both pages.

- [ ] **Reference versioning (data research)** — split reference models into independent rows per version WHERE versions differ in matchable specs (EV battery/power/range — e.g. BYD Dolphin Surf Active/Boost/Comfort, Enyaq tiers); each row carries its own specs + `Verze` value. Populate `Verze` for other models where determinable (editions/trims: First Edition/Essence/Selection). Blank where unknown — do NOT invent. Add `Verze` col to `ev_specs.csv`; rename `ice_specs.csv` `Výbava`→`Verze`. Re-match all scrapes; version assigned only on confident spec match. Fan out per-brand subagents. blocked-by: Verze column plumbing.

- [ ] **Deduplicate reference rows for the same physical car sold under multiple names** — the grow-reference tool (2026-07-04) added BOTH `GWM Ora 03` and `ORA Funky Cat` to `ev_specs.csv` as separate rows: they are the SAME car (GWM Ora 03 = Funky Cat = Good Cat), duplicated only because listings arrive under two name spellings and the EV reference join is prefix-based (one row pairs only one spelling). Problem: (1) identical specs are duplicated across rows → drift + maintenance burden; (2) it is really a normalization/alias problem, not two models. Decide + implement the mechanism: either add `BRAND_MAP` / `MODEL_CLEANUP_PATTERNS` entries in `scrapers/core/normalize.py` so all name spellings of one car collapse to a single canonical `Model auta` (then one reference row suffices), or introduce an explicit reference-alias mechanism (e.g. an alias column read by `join_electric_reference`). Generalises to any rebadged/renamed model (e.g. Škoda Citigo-e ↔ VW e-up! ↔ SEAT Mii electric). Touch: `scrapers/core/normalize.py`, `build/build_data.py`, possibly `ev_specs.csv`. Add a test that both spellings pair to one reference entry. 📌 discovered by: grow-reference demo (docs/superpowers/grow-reference-RESULTS.md).

- [ ] **EV reference join ignores diacritics across sources** — `build/build_data.py::join_electric_reference` matches by `listing.lower().startswith(ref.lower())` but does NOT accent-fold, while mobile.de (the dominant source) strips diacritics from scraped names (`docs/gotchas.md`: "Skoda", "Citroen", "e-C3") and other sources preserve them ("Škoda", "Citroën", "ë-C3"). Consequence: one reference row (e.g. `Citroën ë-C3`) pairs the diacritic-preserving listings but leaves the diacritic-stripped mobile.de ones unpaired (and vice-versa), so accented EV models need duplicate rows or stay under-paired. (The grow-reference clustering already accent-folds, which dedups gap *candidates* but masks this pairing gap.) Fix: accent-fold BOTH sides in `join_electric_reference` (NFKD + strip combining marks, mirroring `reference_gap._fold_accents`), or accent-fold listing `Model auta` once at build time. Expected effect: more EV listings pair against the SAME reference rows — higher coverage, no new rows. Add a test (a stripped + an accented spelling of one model both pair). Touch: `build/build_data.py`, maybe `scrapers/core/normalize.py`. 📌 discovered by: grow-reference demo.

## Needs Scoping

Tasks below need your input — they are genuinely owner-only decisions (new data source, cost, or product direction). Reply directly under each Q line in chat, then run `/tasks-triage` to promote to Atomic.

- [ ] **#2** widen scraping on sauto.cz and other sites
  > ❓ Q1: Which filters to relax? (price ceiling, year floor, km ceiling, body types?)
  I don't know, tell me which you have enabled currently and let me decide.
  > ❓ Q2: Any other sites in scope besides sauto?
  All sites currently with filters.

- [ ] **#23** average annual service cost over 5 years
  > ❓ Q1: Should this be a scraped/enriched field on listings, a reference model spec column, or a standalone dashboard metric aggregating service cost data?
  This should be a reference model spec column, enriched from external data sources.
  > ❓ Q2: Where is the service cost data sourced from — external API, manual reference CSV, or estimated/derived from engine type/volume?
  Not sure yet, you investigate and propose a source.
  > ❓ Q3: Does this apply to both EV and ICE, or ICE only?
  Both.

- [ ] **#25** AI summary of reference model from web sentiment: pros/cons, reliability, comfort — propose quantification
  > ❓ Q1: Is the web scraping/sentiment analysis part of this task, or do you want a design proposal only for how to store + display AI-generated summaries?
  > ❓ Q2: Where should this appear — reference page, per-listing detail modal, or a separate review/sentiment dashboard?
  > ❓ Q3: Should quantified scores (reliability: 1–5, comfort: 1–5) be stored in ev_specs.csv / ice_specs.csv, or computed on-the-fly in build_data.py?

- [ ] **#27** service interval
  > ❓ Q1: Is this a scraped field from listings, a static reference model spec, or derived from engine type/fuel?
  > ❓ Q2: Should it apply to both EV and ICE?

- [ ] **#31** transmission quality: eCVT good (belt), CVT bad (planetary), ZF hydraulic, AISIN, DSG wet not dry, planetary, mechatronic not great (transmission quality rating rules)
  > ❓ Q1: Should transmission quality be a scored column (1–5 or Good/Fair/Poor) in ice_specs.csv, or UI-only display logic when rendering listings?
  > ❓ Q2: Where is transmission brand/subtype data sourced from — extracted from listings, enriched in reference CSVs, or matched via a new lookup table? (Current listings don't reliably distinguish wet/dry DSG, eCVT/CVT.)

- [ ] **#32** rozvody motoru: lepší jsou řetězy než řemeny, nebrat namáčené řemeny (engine timing: chains better than belts, avoid wet belts — rating rule)
  > ❓ Q1: Is this a new "Engine Timing Type" column extracted from listings + enriched in reference, or a quality scoring rule applied to matched models?
  > ❓ Q2: How is wet vs. dry belt info sourced — extracted from Extra text, stored in reference CSV, or inferred from engine model/year? (Not present in current listing data.)

- [ ] **#33** stav km a problémy na technické: portál občana/portál dopravy, cebia, car vertical (mileage state & inspection problems via external portals)
  > ❓ Q1: Should this be a new data source integrated into the scrape pipeline, or a post-build enrichment joined by VIN/registration number to existing listings?
  > ❓ Q2: Which external API/portal should be queried — all four, or prioritize by availability/data quality?
  > ❓ Q3: Should tech inspection results (pass/fail/defects) appear as a new column on listings, or linked as a detail modal per car?

## Atomic

Ready to execute. Pick next unchecked item, use its `flow · model · effort` metadata to run. **Veto any `📌 assumes:` line before running** — the classifier chose that default for you.

- [ ] **#3** split "Model auta" col into "Značka" + "Model" displayed in that order
  > flow:feature-dev · model:sonnet · effort:medium
  > emit "Značka" + "Model" as separate display fields from build_data.py (Značka then Model); remove "Model auta" col

- [ ] **#4** "Model auta" should not contain Objem motoru / Typ motoru values
  > flow:feature-dev · model:sonnet · effort:medium · blocked-by: #3
  > 📌 assumes: after the #3 split, the Model display column shows brand+model only; engine vol/type live solely in their own columns; reference join keeps using the full auth string internally (do NOT strip ice_specs.csv).

- [ ] **#13** Normalize "Ne" / "Ano" values to proper case in all fields across all sources
  > flow:ralph · model:haiku · effort:low

- [ ] **#14** Report empty `Spárováno` values in UI (so pairing gaps are visible and actionable)
  > flow:ralph · model:sonnet · effort:medium
  > 📌 note: largely addressed by tri-state Spárováno coloring (Ne=red, Nejisté=amber, no more nulls); remaining work is surfacing a count/filter shortcut.

- [ ] **#15** json data files should have static order of lines for cleaner diffs, no single line for everything
  > flow:feature-dev · model:haiku · effort:low

- [ ] **#16** sauto listing has year 2002 but is really 2022 — detect and fix 2-digit year swaps (<https://www.sauto.cz/osobni/detail/volkswagen/id3/210446333>)
  > flow:feature-dev · model:sonnet · effort:medium
  > 📌 assumes: fix in scrapers/sources/sauto.py; detect via in_operation_date / manufacturing_date vs Rok výroby mismatch + 19XX→20XX swap heuristic; log corrected years.

- [ ] **#17** sauto listing has year 1900 but is really 2026 — detect and fix invalid years (<https://www.sauto.cz/osobni/detail/dacia/bigster/210225179>)
  > flow:feature-dev · model:sonnet · effort:medium · blocked-by: #16
  > 📌 assumes: same module/logic as #16; clamp years outside [2000 .. current year+1] and repair from in_operation_date; skip the row only if unrepairable.

- [ ] **#18** web UI should display set filters above the table on both pages
  > flow:feature-dev · model:sonnet · effort:medium
  > 📌 assumes: persistent bar above the grid showing active filters as chips with an [×] to clear each; on BOTH index and reference pages.

- [ ] **#19** many reference models are missing data in various cols
  > flow:ralph · model:sonnet · effort:medium
  > 📌 assumes: codeable part only — add a UI indicator on the reference page flagging models missing key spec columns; do NOT source/enter external data (that's a separate manual task).

- [ ] **#20** reorder cols in the reference table to match the main table for easier visual scanning
  > flow:ralph · model:sonnet · effort:low
  > 📌 assumes: reorder reference table columns to match the main cars table's column order.

- [ ] **#21** automated tests for data integrity (mismatch between Model col and relevant cols, format of all data in each col)
  > flow:ralph · model:sonnet · effort:medium
  > 📌 assumes: core integrity harness already added (tests/test_data_integrity.py); this extends it with per-column format checks (numeric price/year/km, enum columns, required-field presence).

- [ ] **#22** scroll bars in tables are very thin and hard to use since they are hidden behind the page scroll bar
  > flow:ralph · model:haiku · effort:low

- [ ] **#24** počet válců (number of cylinders) — new column
  > flow:feature-dev · model:sonnet · effort:medium

- [ ] **#26** typ převodovky (transmission type) — new column
  > flow:feature-dev · model:sonnet · effort:medium

- [ ] **#28** nová stránka s přehledem převodovek: popisky (new page with transmission overview: descriptions)
  > flow:feature-dev · model:sonnet · effort:medium
  > 📌 assumes: static lookup page listing transmission types present in the dataset + seed descriptions; wire quality ratings (#31) in later.

- [ ] **#29** referenční model se vyhledává podle: značka, model, rok výroby, výkon motoru, objem motoru, typ motoru, úroveň výbavy (reference model search)
  > flow:feature-dev · model:sonnet · effort:medium
  > 📌 assumes: UI search/filter controls on the reference page over existing columns (značka, model, rok, výkon, objem, typ motoru, Výbava as trim); no schema change.

- [ ] **#30** větší počet válců a větší objem znamená větší spolehlivost (more cylinders + bigger volume = more reliability — scoring rule)
  > flow:feature-dev · model:sonnet · effort:medium · blocked-by: #24
  > 📌 assumes: add a derived "Spolehlivost" score (1–5) for matched ICE from cylinder count + displacement (more/bigger → higher); needs the #24 cylinders column.

## Done

- [x] **#1** add mobile.de
  > done (branch `feature/mobilede-source`): aiohttp adapter on the keyless app JSON endpoint
  > (`X-Mobile-Client` header; official Search-API has no self-service signup — env plumbing
  > prepared in `var/.env.example` for when support grants credentials). Fuels petrol/diesel/
  > EV/hybrid include-only (no gas); EV: CZ/SK/AT/PL/DE, ICE: CZ/SK/AT/PL (DE=123k rows —
  > excluded, `ICE_COUNTRIES` knob); EUR→Kč via CNB daily fixing; 2000-cap price-band slicing.
  > See docs/gotchas.md → mobile.de.

- [x] **#12** Fix EV `Spárováno` = null vs ICE `Spárováno` = "Ne" asymmetry (`build/build_data.py`)
  > flow:ralph · model:haiku · effort:low

- [x] **#5** add Karoserie (and other cols) to Referenční modely page for matching
  > flow:feature-dev · model:sonnet · effort:medium
  > done: reference page + reference.json now carry Palivo, Karoserie, Výkon (kW), Objem motoru, Typ motoru, Hybrid typ.

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
