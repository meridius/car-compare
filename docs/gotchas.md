# Gotchas

Non-obvious behaviors. Update this file whenever you discover something surprising.

---

## autodraft — sentinel string separates model from spec

`"oceníte na cestách:"` (lowercase) marks where the model block ends and spec text begins. The code does `text_lower.index(MODEL_SEPARATOR)` to find this boundary.

- **Electric** fallback: splits on `"Elektro"` when separator absent.
- **Combustion** fallback: splits on fuel keywords (`"Benzín"`, `"Nafta"`, etc.) when separator absent.

## autodraft — STATUS_MAP keywords appear twice in card text

A reserved/sold card looks like: `"{status} {ModelName} {status} oceníte na cestách: ..."` — the status keyword appears at both the start and end of the model block. The parser strips the leading occurrence with `startswith`, then strips the trailing occurrence with `endswith`.

## autodraft — Enyaq variant extracted from URL, not card text (electric only)

Enyaq cards often omit the variant number (50/60/80) in the card text. The URL slug always contains it (e.g. `.../skoda-enyaq-iv-60-132kw...`). `_enyaq_variant_from_url()` extracts it via `_ENYAQ_URL_VARIANT_RE`. Combustion scraper does not have this logic.

## autodraft — price regex uses negative lookbehind

The pattern `(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*Kč` prevents matching year digits that immediately precede the price, e.g. `"9/2022 597 000 Kč"` would otherwise produce `"2022597000"`.

## autodraft — slash split requires spaces to preserve MM/YYYY

`re.split(r'\s+/\s+', rest)` — spaces required around `/`. This preserves date strings like `"03/2030"` as a single segment while still splitting spec parts like `"4x4 / ALU 19"`.

## autodraft — heat pump detected by "Tepelko", not full Czech term (electric only)

Card text uses the informal abbreviation `"Tepelko"`. energycars uses the full `"Tepelné čerpadlo"` string on its detail pages. Don't swap these between scrapers. Combustion scraper does not detect heat pump.

## autodraft — navigation artefacts can prefix model names

Parsed card text sometimes starts with `"Předchozí Další"` (prev/next nav links). `split_model()` strips these with a regex before doing anything else.

## autodraft combustion — separate URLs for benzin and diesel

The autodraft site uses exclusive `?palivo=` params. Combustion scraper loads `?palivo=benzin` and `?palivo=diesel` as separate requests, deduplicating via a shared `seen` set.

## autodraft combustion — fuel extracted from text after MODEL_SEPARATOR

Fuel type (Benzín, Nafta, LPG, CNG) is the first word/phrase in the text appearing after `"oceníte na cestách:"`. `_extract_fuel()` matches against `_FUEL_KEYWORDS` list.

## autodraft combustion — transmission extracted by regex

`_extract_transmission()` searches card text for `\b(Automat|Manu[áa]l(?:ní)?)\b` and normalises to "Automat" or "Manual".

## energycars — `Stav` field is always blank

energycars listings have no status concept. The `Stav` column exists in the DataFrame (for schema consistency) but is never populated.

## energycars — detail page required for most fields

Heat pump, wheel size, and AWD data are only available on the per-listing detail page, not the listing overview. This is why `fetch_detail_data()` is called per car. The overview model name is sometimes ambiguous and gets refined by the H1 on the detail page.

## sauto — uses aiohttp, not Playwright

sauto exposes a REST API. No browser is launched. `aiohttp` sessions handle all requests. This makes it much faster but also means `beautifulsoup4` is not used.

## sauto — results are pre-filtered at API level

`SEARCH_PARAMS` hard-codes price ceiling, year floor, km ceiling, seat/door minimums. Electric also requires heat pump. The resulting CSV is a curated subset, not a full dump.

## sauto combustion — fuel_seo uses comma-separated format

The `fuel_seo` parameter accepts comma-separated values: `"benzin,nafta,lpg-benzin,cng-benzin"`. This mirrors the URL format on sauto.cz.

## sauto combustion — fuel and transmission from detail API

`fuel_cb` and `gearbox_cb` follow the same `{field}_cb.name` pattern as `drive_cb` and `condition_cb`. Belt-and-suspenders: code also rejects hybrid/elektro fuels and "Havarované" condition post-fetch.

## utils — normalisation order matters

`normalize_model()` applies BRAND_MAP first, then MODEL_CLEANUP_PATTERNS. A pattern that expects a short brand name (e.g. `"VW"`) will fail if run before BRAND_MAP expansion replaces `"Volkswagen"`.

## combustion — Extra field is cleaned after extraction

`clean_extra()` removes substrings already captured in dedicated columns (Typ motoru, Výbava, Karoserie, engine volume, kW values) from the Extra text. Extraction must happen **before** cleaning. Both scrapers build an `extracted` dict first, then pass it to `clean_extra()`.

## sauto combustion — engine_volume API field is in cc

`detail.get("engine_volume")` returns displacement in cubic centimetres (e.g. 1498). Code divides by 1000 when value > 100 to get litres (1.5). Values ≤ 100 are passed through as-is.

## sauto combustion — vehicle_body_cb is the primary body type source

The API field `vehicle_body_cb.name` returns Czech body names (Kombi, SUV, Hatchback). These are used directly — `extract_body_type()` is only a fallback when the API field is empty.

## combustion — DCT regex uses lookahead, not trailing \b

`extract_dct()` and `clean_extra()` use `\bKEYWORD(?![A-Za-z])` instead of `\bKEYWORD\b`. This is because DSG often appears as "DSG7", "7DSG", or "DSG_ČR" where digit/underscore prevents a trailing word boundary. The lookahead `(?![A-Za-z])` allows digits, underscores, and punctuation after the keyword.

## combustion — clean_extra uses case-insensitive regex for field stripping

`clean_extra()` uses `re.sub(re.escape(val), "", text, count=1, flags=re.IGNORECASE)` to strip extracted values from Extra. This handles cases like "T-GDi" in Extra when "T-GDI" was extracted to Typ motoru.

## combustion — clean_extra strips ALL trim keywords, not just extracted one

Cars can have two trim indicators (e.g. "Elegance" in model name + "R-Line" in extra text). `extract_trim()` returns only the first match (for the Výbava column), but `clean_extra()` strips ALL `TRIM_KEYWORDS` from Extra to prevent duplicates leaking through.

## autodraft combustion — engine vol/type extracted from model name first

`extract_engine_volume_from_model()` uses a relaxed regex (`\d[.,]\d\b` — no lookahead) to find displacement in the model name. `extract_engine_type()` finds engine tech (TSI, TDI, etc.) in the model name. Both fall back to `extra_rest` if not found. After extraction, `strip_engine_from_model()` removes them from the model name using `\S*` around the engine type to catch prefixed variants like "eTSI" or "BiTDI".

## combustion — _TRANSMISSION_EXTRA_RE uses no trailing \b after Man

`\bMan\.` has no trailing `\b` because the period is not a word character — a trailing `\b` would only match if the next char is a word character, missing cases where "Man." appears at end-of-string or before whitespace.

## combustion — _SEAT_COUNT_RE allows space after dash

`\b[79]-?\s*[Mm][íi]st\b` handles both "7-Míst" and "7- Míst" (with space between dash and M). The space variant appears in some autodraft card texts.

## combustion — SsangYong↔KGM brand alias in matching

Auth list has some models under "SsangYong" and others under "KGM" (brand was renamed). Sauto returns listings under both names. `_BRAND_MATCH_ALIASES` maps each to the other so matching finds candidates regardless of which brand name the listing uses.

## combustion — Cee´d accent normalisation

Sauto returns "Kia Cee´d" with an accent character (´). Auth list uses "Kia Ceed" without accent. `MODEL_CLEANUP_PATTERNS` includes `Cee´d → Ceed` to normalize before matching.

## combustion — unmatched cars get reformatted

Cars not matching any auth entry are reformatted as "Brand Model EngVol EngType" (e.g. "Opel Mokka 1.2 Turbo"). This is done by `_format_unmatched()` — the original verbose model name is replaced.

## combustion — model_base matching uses first-word heuristic

`_model_base_match()` compares first word of scraped vs auth model base. This handles cases where scraped has extra suffixes ("Golf 8 Variant" → first word "Golf" matches auth "Golf"). Can produce false positives for single-letter model names but scoring step disambiguates.

## all scrapers — merge_with_previous preserves removed listings

`merge_with_previous()` in both `utils.py` files loads the previous CSV, finds rows whose "Odkaz na auto" is no longer in the new scrape, sets their "Stav" to "Odstraněno", and appends them. New data always wins (`keep="first"` in dedup). This means CSVs grow over time — rows are never deleted, only marked.

## all scrapers — merge happens after authoritative matching (combustion)

In combustion scrapers, `merge_with_previous()` is called AFTER `match_to_authoritative()`. This means the "Model auta" in removed rows retains the authoritative format from the last successful scrape. If the auth list changes, old removed rows won't get re-matched.

## electric — Karoserie uses vehicle_body_cb API (sauto) or extract_body_type (autodraft/energycars)

Electric sauto scraper gets body type from `detail.get("vehicle_body_cb")` API field (Czech names: Kombi, SUV, Hatchback) with fallback to `extract_body_type()`. Autodraft and energycars use `extract_body_type()` on model name text. Same pattern as combustion sauto.
