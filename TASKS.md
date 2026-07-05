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

- [x] **Scalable storage for large scrapes (enable DE ICE)** — DONE 2026-07-04 (branch `worktree-scalable-storage`). Decision: parquet state files + rolling GitHub Release `data` (+ immutable monthly `data-YYYY-MM` snapshots) as canonical store; payload = `site/data/cars.parquet` (snappy) + `cars-meta.json` decoded in-browser by hyparquet; AG Grid Community client-side model kept (verified at 140,975 rows — all `verify_ui` scenarios PASS); new `Odstraněno dne` column + 60-day removed-row retention bounds live data forever; DE ICE enabled (133k mobile.de rows, 38.5 MB CSV → 5–8 MB parquet vs 129 MB cars.json which exceeds GitHub's 100 MiB push block). LFS rejected (Pages can't serve it), SQLite rejected (binary-in-git + browser plumbing, no gain over parquet), R2/B2/HF documented as optional mirrors. Full rationale + measurements: `docs/decisions/001-scalable-storage.md`. First main run bootstraps the release from the frozen seed CSVs; seeds deletable afterwards.

- [ ] **Verze column plumbing** — rename canonical `Výbava` → `Verze` (one column, net 25 cols) and move its display position to right after `Model auta` on BOTH the main grid (`site/app.js`) and reference page (`site/reference.js`). Source of truth = matched reference row's version; unmatched/ambiguous → blank. Touch: `scrapers/core/schema.py`, `scrapers/sources/sauto.py`, `scrapers/sources/autodraft.py`, `scrapers/core/matching.py`, `build/build_data.py`, both JS files. Re-match + `verify_ui.py` both pages.

- [ ] **Reference versioning (data research)** — split reference models into independent rows per version WHERE versions differ in matchable specs (EV battery/power/range — e.g. BYD Dolphin Surf Active/Boost/Comfort, Enyaq tiers); each row carries its own specs + `Verze` value. Populate `Verze` for other models where determinable (editions/trims: First Edition/Essence/Selection). Blank where unknown — do NOT invent. Add `Verze` col to `ev_specs.csv`; rename `ice_specs.csv` `Výbava`→`Verze`. Re-match all scrapes; version assigned only on confident spec match. Fan out per-brand subagents. blocked-by: Verze column plumbing.

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

- [ ] **#26** typ převodovky (transmission type) — new column
  > flow:feature-dev · model:sonnet · effort:medium

- [ ] **#30** větší počet válců a větší objem znamená větší spolehlivost (more cylinders + bigger volume = more reliability — scoring rule)
  > flow:feature-dev · model:sonnet · effort:medium · blocked-by: #24
  > 📌 assumes: add a derived "Spolehlivost" score (1–5) for matched ICE from cylinder count + displacement (more/bigger → higher); needs the #24 cylinders column.

## Done

- [x] **#15** json data files should have static order of lines for cleaner diffs, no single line for everything — DONE 2026-07-05: deterministic multi-line JSON output for cleaner version control diffs. Changes: (1) `build/build_data.py`: `build_reference_json()` sorts records by "Model auta" before writing, changed to `indent=2` and removed `separators` for multi-line format; `write_payload()` updated `cars-meta.json` writer with `indent=2, sort_keys=True`; `update_scrape_history()` changed `indent=1` to `indent=2` for consistent spacing. (2) `build/reference_gap.py`: `_cmd_gaps()` kept existing `indent=2`, added `sort_keys=True` for dict output; `_cmd_validate()` sorts validated rows by "Model auta" before writing `.ok.json`. (3) `tests/test_build_data.py`: new `JSONFormatTest` class with 3 tests verifying multi-line format (>5 lines per file), `indent=2` spacing, idempotency (byte-identical on re-runs), and sorted entries by key. Consumer impact: `site/app.js` and `site/reference.js` use `fetch().then(r.json())` — JSON line/key order doesn't affect parsing. Verified: `./bin/test.sh` green (193 tests, incl. 3 new JSONFormatTest), `python build/build_data.py` clean, `verify_ui.py --page {index,reference} --scenario grid` both PASS, `reference.json` byte-identical on re-runs (confirms stable sorting).

- [x] **#28** nová stránka s přehledem převodovek: popisky — DONE 2026-07-05: new static `site/transmissions.html`/`.js` page (dark theme, same header/nav conventions) with a hand-seeded catalogue table (Manuální, Automat/hydrodynamický měnič, DSG/DCT dvouspojková, CVT, eCVT, redukční jednostupňová EV) — Czech name, princip, typické vozy/motorizace, poznámka; live per-type counts computed client-side from `cars.parquet` via the same hyparquet loader as `app.js` (n/a for CVT/eCVT, which the dataset doesn't tag separately from Automat). Added "Převodovky" nav button to `index.html` and `reference.html` toolbars. Quality ratings (#31) deferred as assumed. Verified: `python build/build_data.py`, new `verify_ui.py --page transmissions --scenario transmissions` scenario (PASS, screenshot confirms table + live counts), `--page index --scenario grid` PASS (nav button doesn't break the grid), `./bin/test.sh` 166 tests OK.

- [x] **grow-reference: `gaps --fuel ice` uses EV prefix semantics (wrong for ICE)** — DONE 2026-07-05: chosen resolution was to restrict, not implement — `_cmd_gaps` now exits (code 1) with a bilingual message when `--fuel ice` is passed, explaining ICE pairs via `match_to_authoritative` (not the EV prefix join `gaps` models) and pointing at `--fuel ev`; argparse `choices` for `gaps --fuel` deliberately kept as `{ev,ice}` (not narrowed) so the runtime message fires instead of a generic argparse error, and the `gaps` subparser/`--fuel` help text now documents the ICE restriction. `validate`/`apply` already restricted `--fuel` to `choices=["ev"]` — no other subcommand needed the ICE-valid check. Test: `tests/test_reference_gap.py::TestCLIGuards::test_gaps_ice_exits_with_clear_message`. Low urgency deferred per scope (ICE `Ne` is only 44 listings). 📌 discovered by: grow-reference final review.
- [x] **grow-reference: nested-prefix projection over-counts + sub-model over-capture** — DONE 2026-07-05: `build/reference_gap.py` adds `project_own_absorbed()` (splits each candidate prefix's raw startswith count into `own` — listings for which it is the longest matching candidate prefix — vs `absorbed` — listings that would only fall to it if a longer nested sibling isn't added) and `find_nested_prefixes()` (token-boundary-safe parent/child detection), both wired into `_cmd_gaps` which now prints `own`/`absorbed` per row and a VAROVÁNÍ block naming absorbed children. Confirmed on the live dataset: `Citroën C3` → projected 180 (own 110, absorbed 70 from `Citroën C3 Aircross`) — matches the bug report exactly — and surfaced further real nesting (`Hyundai IONIQ`/`Ioniq 6`, `Opel Astra`/`Astra Electric`, `DS Automobiles DS3`/`DS3 Crossback`, `MINI Aceman`/`Aceman E`, `Opel Zafira` family). Tests: `tests/test_reference_gap.py::TestNestedPrefixProjection` (5 new, synthetic C3/C3-Aircross shape). 📌 discovered by: grow-reference final review.
- [x] **#4** "Model auta" should not contain Objem motoru / Typ motoru values — DONE 2026-07-05: builds on #3's Značka/Model split. `build/build_data.py::strip_ice_engine_tokens()` reuses `core/fields.extract_engine_type` / `extract_engine_volume_from_model` / `strip_engine_from_model` (no parallel keyword list) to strip displacement/engine-tech tokens off the tail of the derived "Model" string for ICE rows only (`Typ == "Spalovací"`, gated so EV variant numbers like Enyaq's "iV 80" are never touched); `add_brand_model_columns()` applies it per-row, falling back to the original string if stripping would leave it empty. `tests/test_data_integrity.py::test_confident_ice_model_matches_reference_entry` updated to apply the identical strip to `ice_specs.csv` entries before comparing, keeping the confident-match guard meaningful post-strip. Verified: `./bin/test.sh` green (184 tests), `python build/build_data.py` clean, `verify_ui.py --page index --scenario grid` PASS — screenshot confirms Model shows "Junior"/"A4 Avant 35"/"Karoq" etc. with no bare 1.5/2.0/TSI/TDI tokens while Objem motoru/Typ motoru columns stay populated.
- [x] **#24** počet válců (number of cylinders) — new column — DONE 2026-07-05: new ICE-only canonical column `Počet válců` (`scrapers/core/schema.py`, 28 cols, positioned right after `Typ motoru`/before `Hybrid typ`). Populated only from `Sauto.cz` today via a new tolerant lookup `scrapers/core/fields.py::extract_cylinder_count()` — the sauto detail API's exact field name is unconfirmed (not in `docs/sauto-api-fields.md`'s documented list), so it probes several plausible keys (`engine_cylinders`/`cylinder_count`/`cylinders`/`num_cylinders`/`cylinder`, plus the coded `*_cb.{name,value}` object shape) and stays blank rather than inventing a value. autodraft/energycars/mobile.de leave it blank (no known equivalent field; mobile.de's `attr` object has no documented cylinder key). `blank_row()`/`merge_with_previous()`/`build_data.py`'s state concat all tolerate the previous 27-col seed CSVs/parquet lacking the column with no special-case code needed (pandas' natural key-union + NaN→"" fill, mirroring how prior schema growth was handled). Added to `build/build_data.py::PAYLOAD_NUMERIC_COLS` (float64, never int64 — hyparquet BigInt gotcha) and `site/app.js` COL_CONFIG (narrow numeric column, number filter, next to "Objem motoru"). Verified: `./bin/test.sh` green (187 tests, new coverage in `tests/test_schema.py`, `tests/test_fields.py`, `tests/test_sauto.py`, `tests/test_merge.py`, `tests/test_data_integrity.py`), `python build/build_data.py` clean, `verify_ui.py --page index --scenario grid` PASS (screenshot confirms the column header renders in position; blank today since the frozen seed CSVs predate real sauto scrapes with cylinder data).
- [x] **EV data leaks: mobile.de 0 kW + sauto wrecked EV** — DONE 2026-07-05: `scrapers/sources/mobilede.py` now runs EV `Výkon (kW)` through `sanitize_ev_power()` (blanks the ~10 Dacia Spring/Hyundai Kona Elektro/Opel Mokka-e rows carrying a literal `pw: "0 kW"`), and `scrapers/sources/sauto.py::build_ev` now rejects `condition_cb.name == "Havarované"` the same way `build_ice` already did (the leaked wrecked MG MG4). Both mirror an existing proven guard rather than inventing a new one. 📌 discovered by: #21 integrity tests.
- [x] **#19** many reference models are missing data in various cols — DONE 2026-07-05: codeable part only (per scope note, no external data sourced). `site/reference.js`/`.html`/`style.css` add a missing-spec badge column (⚠ N, tooltip lists the missing Czech column names) computed client-side per row against a key-spec set (ICE: Spotřeba [skipped for PHEV — intentionally blanked], Objem motoru, Typ motoru, Cd, Hlučnost; EV: Kapacita baterie, Dojezd WLTP, Dojezd EV-database, Cd — listing-aggregated columns like Karoserie/Výkon excluded since their blanks reflect no matching listings, not a data gap), plus a header "Neúplné: N / M" toggle button wired as an AG Grid external filter (independent of column filters/quick search, like the existing search box). Observed: 156/390 reference rows (40%) currently miss ≥1 key spec. Verified: `python build/build_data.py` + `verify_ui.py --page reference --scenario grid/ref-search/missing-specs` (new scenario) all exit 0, screenshots confirm badges + toggle.
- [x] **#3** split "Model auta" col into "Značka" + "Model" displayed in that order — DONE 2026-07-05: payload/display-only split, canonical `Model auta` untouched (matching/merge/join still key on it). `build/build_data.py::split_brand_model` reuses `core/matching._parse_brand` (MULTI_WORD_BRANDS list + first-token fallback); `add_brand_model_columns()` derives "Značka"/"Model" and drops "Model auta" inside `write_payload` (both live + archived parquet). `site/app.js` COL_CONFIG replaces the single "Model auta" column with "Značka" (set filter) then "Model" (text filter) at the same pinned-left position; no other site/ references needed updating (grepped, only that one col-def + the untouched reference page). `tests/test_data_integrity.py` required-fields/confident-match guards rebuilt from a reconstructed Značka+Model name. Verified: `./bin/test.sh` green (171 tests), `python build/build_data.py` clean, `verify_ui.py --page index --scenario {grid,filter-chips,pairing-gap,summary}` all PASS (screenshots confirm Stav/Značka/Model column order + correct values).

- [x] **#29** referenční model se vyhledává podle: značka, model, rok výroby, výkon motoru, objem motoru, typ motoru, úroveň výbavy (reference model search) — DONE 2026-07-05: smart search box above the reference grid (`site/reference.html`/`.js`), accent-insensitive (folds diacritics on both the query and every column's quick-filter text via `getQuickFilterText`) AG Grid quick filter over `Model auta` (značka/model/výbava), `Výkon (kW)`, `Objem motoru`, `Typ motoru`; debounced 200ms, clear (×) button, independent of column filters/filter-chips bar. No schema change (reference has no separate rok výroby column). Verified: `verify_ui.py --page reference --scenario ref-search` (new scenario) PASS.
- [x] **#14** Report empty `Spárováno` values in UI (so pairing gaps are visible and actionable)
  > done: added a `Nespárováno: N (M nejistých)` toolbar button (`site/index.html`, `site/app.js`) that counts live `Spárováno == "Ne"/"Nejisté"` rows and toggles the `Spárováno` set filter to `{Ne, Nejisté}` on click, merging with any existing filter model rather than clobbering it; counts refresh on `onModelUpdated`/`onFilterChanged` from the full loaded dataset so the label stays stable while filtering. New `verify_ui.py` scenario `pairing-gap` exercises the merge/toggle-off/active-state behaviour.

- [x] **Deduplicate reference rows for the same physical car sold under multiple names** — DONE 2026-07-05: collapsed all name spellings to one canonical `Model auta` via a new `MODEL_CLEANUP_PATTERNS` entry in `scrapers/core/normalize.py` (`ORA Funky Cat` / `GWM Ora Funky Cat` / `Ora Good Cat` → `GWM Ora 03`), applied at scrape time in every adapter (as before) and re-applied in `build/build_data.py::fix_electric_model` at build time so rows already sitting in state/seed CSVs from before the alias existed still collapse onto the single remaining `GWM Ora 03` row in `ev_specs.csv` (the duplicate `ORA Funky Cat` row was deleted — both rows carried identical specs). Chosen over an explicit reference-alias column because it fixes the problem at the source for all four sources and needs no new schema; generalises to any future same-car-different-spelling case without touching `build_data.py`'s join logic again. Verified: `./bin/test.sh` green (126 tests, incl. new `tests/test_normalize.py::OraFunkyCatAliasTest` and `tests/test_build_data.py::ElectricModelAliasTest`); `python build/build_data.py` reports `Electric reference: 15108/17276 matched` (unchanged vs baseline) with the live `GWM Ora 03` row now `Spárováno=Ano`. 📌 discovered by: grow-reference demo (docs/superpowers/grow-reference-RESULTS.md).

- [x] **#13** Normalize "Ne" / "Ano" values to proper case in all fields across all sources
  > done: added `normalize_ano_ne()` helper in `scrapers/core/fields.py` that maps case-insensitive
  > "ano"/"ANO" → "Ano" and "ne"/"NE" → "Ne", stripping whitespace. Applied centrally in both
  > `scrapers/core/pipeline.py::_normalize_ano_ne_columns()` (after merge_with_previous) and
  > `build/build_data.py::main()` (after reading state from seed/parquet) so old rows with
  > inconsistent casing are normalized. Boolean columns covered: Dvouspojková převodovka, Filtr
  > pevných částic, Náhon 4x4, Záruka, Tepelné čerpadlo, Spárováno (tri-state Nejisté values
  > pass through unchanged). Test-driven: unit tests cover variations, whitespace, blanks, and
  > non-boolean values. Commit: 0b2d0f4.

- [x] **#21** automated tests for data integrity — DONE 2026-07-05: `tests/test_data_integrity.py::ColumnFormatIntegrityTest` adds per-column format/enum/required-field invariants (Cena, Rok výroby, Nájezd, Výkon, Objem motoru numeric bounds; Typ/Stav/Spárováno/Země/boolean-column enums; required-field + link-uniqueness checks; confident-ICE-row-must-match-reference guard). Surfaced 3 real data issues along the way (2 pinned as small-tolerance regression guards, 1 reported): mobile.de leaves ~10 EV rows at an implausible 0 kW (sauto has a `sanitize_ev_power` guard mobile.de never calls); one frozen-seed row (Dacia Bigster) carries the historical sauto "1900 sentinel date" bug that `repair_year()` now guards against; `sauto.py build_ev` is missing the `Havarované` (wrecked) rejection that `build_ice` has, leaking one wrecked EV into live listings.

- [x] **EV reference join ignores diacritics across sources** — DONE 2026-07-05 — `build/build_data.py::join_electric_reference` matched by `listing.lower().startswith(ref.lower())` but did NOT accent-fold, while mobile.de (the dominant source) strips diacritics from scraped names (`docs/gotchas.md`: "Skoda", "Citroen", "e-C3") and other sources preserve them ("Škoda", "Citroën", "ë-C3"). Consequence: one reference row (e.g. `Citroën ë-C3`) paired the diacritic-preserving listings but left the diacritic-stripped mobile.de ones unpaired (and vice-versa), so accented EV models needed duplicate rows or stayed under-paired. (The grow-reference clustering already accent-folds, which dedups gap *candidates* but masked this pairing gap.) Fix: added `_fold_accents` (NFKD + strip combining marks, mirroring `reference_gap._fold_accents`) plus `_match_electric_ref` — tries an exact case-insensitive prefix match first, falling back to an accent-folded comparison only when nothing matches exactly. Exact-first matters: the reference list carries distinct rows differing only by diacritics with genuinely different specs (e.g. "Renault Megane" vs "Renault Mégane" — different Tepelné čerpadlo/Dojezd), so folding unconditionally would silently redirect an already-correct match to the wrong row. Applied identically in `join_electric_reference` and `build_ev_listing_specs` (the reference-page EV bucketing) so counts don't diverge. Verified against the real local dataset (17,276 EV listings): zero regressions, matched count unchanged (15108/17276) — this snapshot doesn't currently carry a live diacritic-stripped mismatch, but the fix is pinned by `tests/test_build_data.py::ElectricReferenceJoinAccentFoldTest` (accented "Citroën ë-C3 …" and stripped "Citroen e-C3 …" now both pair to the same reference row). Touch: `build/build_data.py`, `tests/test_build_data.py`. 📌 discovered by: grow-reference demo.

- [x] **#20** reorder cols in the reference table to match the main table for easier visual scanning
  > done: `site/reference.js` COL_DEFS reordered so shared columns follow the main grid's
  > order (`site/app.js` COL_CONFIG); reference-only "Tepelné čerpadlo možné" kept at the end.

- [x] **#18** web UI should display set filters above the table on both pages
  > done: shared `site/filter-chips.js` renders a chip bar (column name + human summary,
  > [×] per chip, "Vymazat vše" at 2+) above the grid on index + reference; hidden when empty.

- [x] **#17** sauto listing has year 1900 but is really 2026 — detect and fix invalid years
  > done: `repair_year()` extended with a [MIN_VALID_YEAR..current_year+1] clamp — an
  > out-of-range in_operation_date (e.g. the 1900-01-01 sentinel) falls back to
  > manufacturing_date; returns `None` when neither field is repairable so
  > `build_ev`/`build_ice` drop the row instead of publishing a bogus year.

- [x] **#16** sauto listing has year 2002 but is really 2022 — detect and fix 2-digit year swaps
  > done: `repair_year()` in `scrapers/core/fields.py` reconciles item-derived year against the
  > freshly-fetched detail's `in_operation_date`/`manufacturing_date` (trusts the live detail over
  > a stale search-index snapshot); wired into `sauto.py::_common`; logs each correction.

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

- [x] **#22** scroll bars in tables are very thin and hard to use since they are hidden behind the page scroll bar
  > done: 14px webkit scrollbar + scrollbar-color for Firefox, visible #4b5563 thumb with border, scoped to .ag-theme-alpine-dark/.ag-theme-alpine on both index + reference pages; verify_ui both pages PASS
