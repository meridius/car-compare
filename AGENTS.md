# AGENTS.md

Behavioural instructions for AI agents (Copilot, Claude, etc.) working in this repository.

## Scope

These rules apply to all files in `/home/martin/projects/meridius/auto`.

---

## Mandatory Behaviours

### Run scrapers via the shell script

Always use `./run_scraper.sh` to execute scrapers. Never run `python3 scrape_*.py` directly in instructions to the user unless debugging a single scraper in isolation.

### Never edit generated CSVs

`autodraft.csv` and `energycars.csv` are scraper outputs. Do not suggest or make edits to them directly.

### Preserve column order from `cols.txt`

When adding or reordering columns in a scraper's DataFrame, the final column list must match the order defined in `cols.txt`.

### Keep brand normalisation centralised

All brand-name aliases belong in `utils.BRAND_MAP`. Do not add brand replacements inline inside scraper files.

---

## Code Style Conventions

- **Language**: Czech strings in user-facing output (status labels, print messages); English for code identifiers, comments, and docstrings.
- **Async pattern**: Use `async_playwright` / `async def` throughout. Do not mix sync and async Playwright APIs.
- **Error handling**: Scraping helpers should catch broad `Exception` and return safe defaults (e.g. `"Ne"`, `""`), not raise.
- **Regex flags**: Pass `re.IGNORECASE` when matching AWD/drive-type strings to handle spelling variants.

---

## Workflow

1. **Explore before changing**: read the relevant scraper and `utils.py` before proposing edits.
2. **One concern per function**: extraction helpers (`split_model`, `split_extra`, `fetch_detail_data`, …) should each do one thing.
3. **Test by running**: after any change, verify with `./run_scraper.sh` and spot-check the CSV output.
4. **No external dependencies**: do not add libraries beyond `playwright`, `pandas`, and `beautifulsoup4` without explicit user approval.

---

## Out of Scope

- Do not modify `run_scraper.sh` unless the user explicitly requests it.
- Do not refactor working scraper logic unless asked.
- Do not create additional output files or databases — CSVs are the sole output format.
