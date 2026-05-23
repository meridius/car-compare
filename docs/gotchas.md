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
