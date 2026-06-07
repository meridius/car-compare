# Gotchas

Non-obvious behaviors. Update this file whenever you discover something surprising.

File paths: source adapters live in `scrapers/sources/`, shared logic in `scrapers/core/`. Each adapter handles every fuel its site offers (sauto + autodraft = EV + ICE; energycars = EV), branching on `Typ` internally — there is no separate electric/combustion code anymore.

---

## autodraft

### sentinel string separates model from spec

`"oceníte na cestách:"` (lowercase) marks where the model block ends and spec text begins. The code does `text_lower.index(MODEL_SEPARATOR)` to find this boundary.

- **EV** fallback: splits on `"Elektro"` when separator absent.
- **ICE** fallback: splits on fuel keywords (`"Benzín"`, `"Nafta"`, etc.) when separator absent.

### STATUS_MAP keywords appear twice in card text

A reserved/sold card looks like: `"{status} {ModelName} {status} oceníte na cestách: ..."` — the status keyword appears at both the start and end of the model block. The parser strips the leading occurrence with `startswith`, then strips the trailing occurrence with `endswith`.

### Enyaq variant extracted from URL, not card text (EV rows)

Enyaq cards often omit the variant number (50/60/80) in the card text. The URL slug always contains it (e.g. `.../skoda-enyaq-iv-60-132kw...`). `_enyaq_variant_from_url()` extracts it via `_ENYAQ_URL_VARIANT_RE`. Only applies to the EV branch.

### price regex uses negative lookbehind

The pattern `(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*Kč` prevents matching year digits that immediately precede the price, e.g. `"9/2022 597 000 Kč"` would otherwise produce `"2022597000"`.

### slash split requires spaces to preserve MM/YYYY

`re.split(r'\s+/\s+', rest)` — spaces required around `/`. This preserves date strings like `"03/2030"` as a single segment while still splitting spec parts like `"4x4 / ALU 19"`.

### heat pump detected by "Tepelko", not full Czech term (EV rows)

Card text uses the informal abbreviation `"Tepelko"`. energycars uses the full `"Tepelné čerpadlo"` string on its detail pages. Don't swap these between sources. The ICE branch does not detect heat pump.

### navigation artefacts can prefix model names

Parsed card text sometimes starts with `"Předchozí Další"` (prev/next nav links). `split_model()` strips these with a regex before doing anything else.

### separate URLs for benzin and diesel (ICE)

The autodraft site uses exclusive `?palivo=` params. The ICE branch loads `?palivo=benzin` and `?palivo=diesel` as separate requests, deduplicating via a shared `seen` set. (EV uses `?palivo=elektro`; there is also an "auta-na-ceste" URL.)

### fuel extracted from text after MODEL_SEPARATOR (ICE)

Fuel type (Benzín, Nafta, LPG, CNG) is the first word/phrase in the text appearing after `"oceníte na cestách:"`. `_extract_fuel()` matches against `_FUEL_KEYWORDS` list.

### transmission extracted by regex (ICE)

`_extract_transmission()` searches card text for `\b(Automat|Manu[áa]l(?:ní)?)\b` and normalises to "Automat" or "Manual".

### engine vol/type extracted from model name first (ICE)

`extract_engine_volume_from_model()` uses a relaxed regex (`\d[.,]\d\b` — no lookahead) to find displacement in the model name. `extract_engine_type()` finds engine tech (TSI, TDI, etc.) in the model name. Both fall back to `extra_rest` if not found. After extraction, `strip_engine_from_model()` removes them from the model name using `\S*` around the engine type to catch prefixed variants like "eTSI" or "BiTDI".

---

## energycars

### `Stav` field is always blank

energycars listings have no status concept. The `Stav` column exists in the schema (for consistency) but is never populated.

### detail page required for most fields

Heat pump, wheel size, and AWD data are only available on the per-listing detail page, not the listing overview. This is why `fetch_detail_data()` is called per car. The overview model name is sometimes ambiguous and gets refined by the H1 on the detail page.

---

## sauto

### uses aiohttp, not Playwright

sauto exposes a REST API. No browser is launched. `aiohttp` sessions (`core/http.py`) handle all requests. This makes it much faster but also means `beautifulsoup4` is not used.

### results are pre-filtered at API level

`_BASE_PARAMS` / `EV_PARAMS` / `ICE_PARAMS` hard-code price ceiling, year floor, km ceiling, seat/door minimums. EV also requires a heat pump; ICE adds engine-power floor + condition + body-type filters. The resulting CSV is a curated subset, not a full dump.

### fuel_seo uses comma-separated format (ICE)

The `fuel_seo` parameter accepts comma-separated values: `"benzin,nafta,lpg-benzin,cng-benzin"`. This mirrors the URL format on sauto.cz. (EV uses `fuel_seo: "elektro"`.)

### fuel and transmission from detail API (ICE)

`fuel_cb` and `gearbox_cb` follow the same `{field}_cb.name` pattern as `drive_cb` and `condition_cb`. Belt-and-suspenders: code also rejects hybrid/elektro fuels and "Havarované" condition post-fetch.

### engine_volume API field is in cc (ICE)

`detail.get("engine_volume")` returns displacement in cubic centimetres (e.g. 1498). Code divides by 1000 when value > 100 to get litres (1.5). Values ≤ 100 are passed through as-is.

### vehicle_body_cb is the primary body type source

The API field `vehicle_body_cb.name` returns Czech body names (Kombi, SUV, Hatchback). These are used directly — `extract_body_type()` is only a fallback when the API field is empty. Applies to both EV and ICE rows.

### build_record skips failed detail fetches

`fetch_detail()` returns `{}` on HTTP errors or exceptions. `build_record()` returns `None` when detail is empty, preventing incomplete records (no Stav, Palivo, Výkon, etc.) from entering the CSV. Without this guard, search-API-only data creates rows with only Model/Cena populated.

### "Ostatní" model recovery (EV)

sauto sometimes returns `model_cb` "Ostatní" for not-yet-indexed models (e.g. a just-launched EV); the real model hides in `additional_model_name` as a project code / trim string. `_recover_ostatni_model()` maps known cases (e.g. Kia EV2 via "QV1" / 42.2 kWh battery) so the car still matches the reference list.

---

## core — normalize

### normalisation order matters

`normalize_model()` (`core/normalize.py`) applies `BRAND_MAP` first, then `MODEL_CLEANUP_PATTERNS`. A pattern that expects a short brand name (e.g. `"VW"`) will fail if run before BRAND_MAP expansion replaces `"Volkswagen"`.

### Cee´d accent normalisation

Sauto returns "Kia Cee´d" with an accent character (´). The reference list uses "Kia Ceed" without accent. `MODEL_CLEANUP_PATTERNS` includes `Cee´d → Ceed` to normalize before matching.

---

## core — fields (ICE extraction)

### Extra field is cleaned after extraction

`clean_extra()` removes substrings already captured in dedicated columns (Typ motoru, Výbava, Karoserie, engine volume, kW values) from the Extra text. Extraction must happen **before** cleaning. Adapters build an `extracted` dict first, then pass it to `clean_extra()`.

### DCT regex uses lookahead, not trailing \b

`extract_dct()` and `clean_extra()` use `\bKEYWORD(?![A-Za-z])` instead of `\bKEYWORD\b`. DSG often appears as "DSG7", "7DSG", or "DSG_ČR" where a digit/underscore prevents a trailing word boundary. The lookahead `(?![A-Za-z])` allows digits, underscores, and punctuation after the keyword.

### clean_extra uses case-insensitive regex for field stripping

`clean_extra()` uses `re.sub(re.escape(val), "", text, count=1, flags=re.IGNORECASE)` to strip extracted values from Extra. This handles cases like "T-GDi" in Extra when "T-GDI" was extracted to Typ motoru.

### clean_extra strips ALL trim keywords, not just extracted one

Cars can have two trim indicators (e.g. "Elegance" in model name + "R-Line" in extra text). `extract_trim()` returns only the first match (for the Výbava column), but `clean_extra()` strips ALL `TRIM_KEYWORDS` from Extra to prevent duplicates leaking through.

### _TRANSMISSION_EXTRA_RE uses no trailing \b after Man

`\bMan\.` has no trailing `\b` because the period is not a word character — a trailing `\b` would only match if the next char is a word character, missing cases where "Man." appears at end-of-string or before whitespace.

### _SEAT_COUNT_RE allows space after dash

`\b[79]-?\s*[Mm][íi]st\b` handles both "7-Míst" and "7- Míst" (with space between dash and M). The space variant appears in some autodraft card texts.

---

## core — matching (ICE)

### SsangYong↔KGM brand alias

The reference list has some models under "SsangYong" and others under "KGM" (brand was renamed). Sauto returns listings under both names. `_BRAND_MATCH_ALIASES` maps each to the other so matching finds candidates regardless of which brand name the listing uses.

### unmatched cars get reformatted

Cars not matching any reference entry are reformatted as "Brand Model EngVol EngType" (e.g. "Opel Mokka 1.2 Turbo"). This is done by `_format_unmatched()` — the original verbose model name is replaced.

### model_base matching uses first-word heuristic

`_model_base_match()` compares the first word of scraped vs reference model base. This handles cases where scraped has extra suffixes ("Golf 8 Variant" → first word "Golf" matches reference "Golf"). Can produce false positives for single-letter model names but the scoring step disambiguates.

---

## core — merge_with_previous

### preserves removed listings

`merge_with_previous()` (`core/merge.py`) loads the previous CSV, keeps rows whose "Odkaz na auto" is no longer in the new scrape, sets their "Stav" to "Odstraněno". New data always wins (`keep="first"` dedup). CSVs grow over time — rows are never deleted, only marked.

### merge happens after authoritative matching

`pipeline.run_source()` calls `merge_with_previous()` AFTER `match_to_authoritative()`. The "Model auta" in removed rows retains the authoritative format from the last successful scrape. If the reference list changes, old removed rows won't get re-matched.

### skips empty-link rows

`merge_with_previous()` skips previous-CSV rows with an empty `Odkaz na auto`. Without this, rows that somehow lost their URL would accumulate as undedupeable copies on every run — this was the root cause of ~8k CSV growth per 4 days.

### KNOWN BUG — clobbers Odkaz on rows present in both scrapes

For rows present in BOTH the previous and the new scrape, `merge_with_previous()` does `df.set_index("Odkaz na auto").loc[link]` — which returns the row **without** the index column. So the merged row gets `Odkaz na auto` = NaN. On the next run those empty-link rows are skipped (see above), causing churn. Pre-existing (predates the unification); slated for a separate fix.

**Consequence:** parity / regression checks MUST run on FRESH scrapes (delete `scrapers/data/scrapes/*.csv` first) so no previous CSV exists — otherwise the merge corrupts links and the numbers lie.

---

## build — reference enrichment

### EV body type vs ICE

EV body type comes from `vehicle_body_cb` (sauto) or `extract_body_type()` (autodraft/energycars). ICE uses the same primary/fallback pattern. EV rows are enriched in `build_data.py` via a prefix join against `ev_specs.csv`; ICE rows via an exact join + re-match against `ice_specs.csv`.
