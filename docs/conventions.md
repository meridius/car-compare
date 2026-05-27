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

All brand-name aliases belong in `utils.BRAND_MAP`. Never add brand replacements inline inside scraper files.

Model cleanup patterns (regex fixups) belong in `utils.MODEL_CLEANUP_PATTERNS`.

## Column Order

The final DataFrame column list must match the order in `{suite}/data/scrape-data-cols.txt`. Never reorder silently.

## Running Scrapers

- Recommend `./electric/bin/run_scraper.sh` or `./combustion/bin/run_scraper.sh` (handles dep check + parallel run).
- Run individual scrapers only when debugging a single scraper in isolation (`cd electric/src && python3 scrape_*.py`).

## Verification After Changes

After modifying any scraper or `utils.py`, **always run the affected scraper(s)** and verify the CSV output before reporting the task as complete. Check:

1. Scraper runs without errors
2. Column count matches `scrape-data-cols.txt`
3. New/changed fields are populated (spot-check with `pandas value_counts`)
4. Existing fields still correct (model, price, mileage)

## UI Verification After Changes

After modifying anything under `site/` (`app.js`, `reference.js`, `style.css`, HTML),
**always run `build/verify_ui.py`** for the affected page/scenario and **Read the resulting
screenshot** before reporting the task as complete. This is mandatory — the site has no build
step, no type checking, and no tests, so a console error or visual regression is otherwise
invisible.

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
