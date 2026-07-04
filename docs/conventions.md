# Conventions

## Language

- **Czech** — user-facing strings: status labels, print messages (e.g. `"Hotovo – uloženo N aut"`)
- **English** — code identifiers, comments, docstrings

## Async Pattern

Use `async_playwright` / `async def` throughout autodraft and energycars. Never mix sync and async Playwright APIs.

## Error Handling

Scraping helpers catch broad `Exception` and return safe defaults — never raise:

```python
except Exception:
    return "Ne", "", "Ne", ""
```

Safe defaults: `"Ne"` for boolean fields, `""` for text/numeric fields.

## Regex

Pass `re.IGNORECASE` when matching AWD / drive-type strings to handle spelling variants.

Use `re.IGNORECASE` + `re.fullmatch` / `re.search` / `re.compile` consistently; don't mix `str.lower()` comparisons with case-sensitive patterns.

## Brand Normalisation

All brand-name aliases belong in `core/normalize.py` `BRAND_MAP`. Never add brand replacements inline inside source adapters.

Model cleanup patterns (regex fixups) belong in `core/normalize.py` `MODEL_CLEANUP_PATTERNS`.

## Column Order

The final DataFrame column list must match `CANONICAL_COLS` in `scrapers/core/schema.py`. Never reorder silently. Adapters emit exactly these 24 columns (use `blank_row()` for the ones they don't fill).

## Running Scrapers

- Recommend `./bin/run_all.sh` (dep check + run all sources), or `./bin/run_all.sh --source <name>` for a subset.
- Debug a single source with `python -m scrapers.run --source <name>` (sources: `sauto`, `autodraft`, `energycars`, `mobilede`).

## Verification After Changes

After modifying any source adapter or `core/` module, **always run the affected source(s)** and verify the CSV output before reporting the task as complete. Check:

1. `python -m scrapers.run --source <name>` runs without errors
2. Column count matches `CANONICAL_COLS` in `scrapers/core/schema.py` (25)
3. New/changed fields are populated (spot-check with `pandas value_counts`)
4. Existing fields still correct (model, price, mileage)

Parity / regression checks should run on a **fresh** scrape (delete `scrapers/data/scrapes/*.csv` first) — see the `merge_with_previous` gotcha (the link-clobber bug is fixed, but merge still carries forward old matched names).

## Testing

Fast offline net — **stdlib `unittest`, no extra deps, no network.** Run after any change to `core/`, `build/`, or the reference CSVs:

```bash
./bin/test.sh            # matching golden tests + data-integrity invariants
./bin/test.sh -v         # verbose
```

- `tests/test_matching.py` — pins `classify_match()` tri-state behaviour (Ano / Nejisté / Ne, score floor, tie/contradiction handling).
- `tests/test_data_integrity.py` — invariants over the built `site/data/cars.json` (no confident `Ano` scoring ≤ 0, `Spárováno` enum, honest match-rate band). Builds `cars.json` if missing.

**Fast inner loop:** `python build/build_data.py` (offline, ~9s against existing CSVs) + `./bin/test.sh` (<1s) verifies matching / build / enrichment changes **without a network scrape**. Only `sources/*.py` adapter changes need a real scrape.

## UI Verification After Changes

After modifying anything under `site/` (`app.js`, `reference.js`, `style.css`, HTML),
**always run `build/verify_ui.py`** for the affected page/scenario and **Read the resulting
screenshot** before reporting the task as complete. This is mandatory — the site has no build
step and no type checking, so a console error or visual regression is otherwise
invisible (the `unittest` suite covers data/logic, not rendering).

```bash
python3 build/verify_ui.py --page index --scenario grid          # default grid view
python3 build/verify_ui.py --page index --scenario stav-filter   # opens Stav filter popup
python3 build/verify_ui.py --page reference --scenario grid       # reference page
```

The script launches headless Chromium, captures console/page errors (exit 1 on any), checks the
grid rendered rows, and writes `tmp/ui-verify/<page>-<scenario>.png`. Confirm both:

1. **Exit 0** — no console/page JS errors, grid rendered.
2. **Screenshot looks right** — Read the PNG and check the actual change (layout, grouping,
   counts, dark-theme contrast). Exit 0 alone does not prove visual correctness.

When a change touches a view no existing scenario covers, add a named scenario function to
`SCENARIOS` in `build/verify_ui.py` (perform the interaction, wait for the expected element,
return its selector to screenshot).

## Dependencies

Allowed: `playwright`, `pandas`, `beautifulsoup4`, `aiohttp` (sauto only).
Do not add new libraries without explicit user approval.

## Output

CSVs are the sole output format. Never suggest databases, extra files, or append modes.

## Function Scope

Each extraction helper (`split_model`, `split_extra`, `fetch_detail_data`, …) must do one thing. Resist combining concerns.
