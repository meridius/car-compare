# mobile.de source — design

Date: 2026-07-04 · Task: TASKS.md **#1 add mobile.de** · Branch: `feature/mobilede-source`

## Goal

Fourth scraper source `mobilede` producing `scrapers/data/scrapes/mobilede.csv` in the
canonical 25-column schema. Fuels: petrol, diesel, EV, hybrid — **no LPG/CNG/hydrogen/
ethanol or gas combinations**. Seller countries: CZ, SK, DE, AT, PL. Filters mirror
sauto (year ≥ 2021, ≤ 100 000 km, ≤ 750 000 Kč, ≥ 4 seats, 4/5 doors, ICE ≥ 100 kW,
no damaged cars).

## Decisions (brainstorm self-answered, owner pre-authorized full autonomy)

### Q1 — API or browser scraping?

**Verified 2026-07-04 by live probes + doc fetch:**

| Route | Status |
| --- | --- |
| Official Search-API (`services.mobile.de/search-api`) | Alive (401 without creds). HTTP Basic auth. **No self-service registration** — credentials granted manually by mobile.de customer support, oriented to commercial partners. Docs: <https://services.mobile.de/docs/search-api.html> |
| Website HTML / `suchen.mobile.de` | 403 — Akamai Bot Manager. Headless Playwright also 403. Dead, especially from GH-runner IPs. |
| App JSON endpoint `https://www.mobile.de/api/s/` | **Works keyless** with header `X-Mobile-Client: de.mobile.android.app`. Full structured JSON. No Akamai, no auth, served fine from datacenter IPs. |

**Decision: aiohttp against the app JSON endpoint.** No browser, mirrors the sauto
adapter architecture. Caveats accepted and documented in gotchas:

- `/api/` is disallowed in mobile.de robots.txt — undocumented private endpoint, may
  change or start enforcing signing at any time. Low-volume personal use.
- Official Search-API is the sanctioned upgrade path: request an API-Account via
  mobile.de customer support (contact form; DE +49 30 81097500). When credentials
  arrive → `var/.env` (`MOBILEDE_SEARCH_API_USER` / `MOBILEDE_SEARCH_API_PASSWORD`,
  gitignored, loaded by `.envrc` via direnv dotenv) + GH repo secrets, and a second
  transport can be added. **Not implemented now** — an untestable code path without
  credentials would violate the test-verified rule.

### Q2 — Countries and volume

Live counts with target filters (year ≥ 2021, ≤ 100k km, ≤ €30k, 4/5 doors, our fuels):
CZ 432 · SK 131 · AT 437 · PL 283 · **DE 259 170 (123k even with ≥ 100 kW)**.

DE full-fuel volume is unusable (dashboard is ~8k rows total). **Decision:**

- **EV config**: `ft=ELECTRICITY`, countries **CZ SK AT PL DE** (~14k, mostly DE —
  German EV import is the point of adding mobile.de).
- **ICE config**: `ft=PETROL DIESEL HYBRID HYBRID_DIESEL`, `pw=100:`, countries
  **CZ SK AT PL** (~1.1k). DE excluded; `ICE_COUNTRIES` is a module constant — flip
  to add DE later if wanted.

### Q3 — Schema

Same canonical 25 columns. No new columns.

## Query parameters (app endpoint, all verified live)

Shared: `s=Car&vc=Car`, `fr=2021:`, `ml=:100000`, `p=:<EUR_CEILING>`, `sc=4:`,
`door=FOUR_OR_FIVE`, `dam=false`. Repeated params = OR (`ft`, `cn`). Pagination:
`psz` (page size, ≤ 100) + `ps` (item offset). **Hard cap: 2000 results per query**
— queries over the cap are split recursively into price bands (`p=min:max`) until
each slice < 2000, then paged.

`EUR_CEILING = round(750000 / rate)` — rate fetched from the CNB daily fixing
(`https://www.cnb.cz/cs/financni_trhy/devizovy_trh/kurzy_devizoveho_trhu/denni_kurz.txt`,
line `EMU|euro|1|EUR|24,745`), fallback constant `24.5` on any failure. Post-filter:
converted price must be ≤ 750 000 Kč exactly.

## Row mapping (item JSON → canonical row)

| Canonical | Source |
| --- | --- |
| Typ | `attr.ft == "Elektro"` → Elektrické, else Spalovací |
| Model auta | `normalize_model(f"{make.localized} {model.localized}")`; BRAND_MAP gains `Skoda→Škoda`, `Citroen→Citroën` (mobile.de strips diacritics) |
| Cena (Kč) | `price.grs.amount` (EUR float) × CNB rate, rounded to int Kč. Only `price.type == "FIXED"` rows with `grs.amount` present; sauto's `MIN_PRICE_KC = 100000` backstop applies after conversion |
| Nájezd (km) | `attr.ml` `"29.000 km"` → 29000 |
| Rok výroby | `attr.fr` `"02/2022"` → 2022 |
| Palivo | ft map: Benzin→Benzín, Diesel→Nafta, Elektro→Elektro, `Hybrid (Benzin/Elektro)`→Benzín, `Hybrid (Diesel/Elektro)`→Nafta |
| Objem motoru | `attr.cc` `"1.499 cm³"` → 1.5 (`sanitize_engine_volume` applied) |
| Typ motoru | `extract_engine_type(subTitle)` |
| Hybrid typ | ft hybrid → `extract_hybrid_type(subTitle)` or default HEV; non-hybrid ft → `extract_hybrid_type(subTitle)` as-is (MHEVs are listed under Benzin) |
| Výkon (kW) | `attr.pw` `"110 kW (150 PS)"` → 110 |
| Převodovka | `attr.tr`: Automatik→Automatická, Schaltgetriebe→Manuální, Halbautomatik→Automatická |
| Dvouspojková převodovka | `extract_dct(subTitle)` |
| Filtr pevných částic | `extract_particle_filter(subTitle)` |
| Kola | blank |
| Náhon 4x4 | `extract_awd(shortTitle + subTitle)` |
| Karoserie | `attr.c` map: OffRoad→SUV, EstateCar→Kombi, SmallCar→Hatchback, Van→VAN, SportsCar→Kupé, Cabrio→Kabriolet, Limousine→"" (ambiguous catch-all, blanked 2026-07-13 — see gotchas), OtherCar→"" ; blank → `extract_body_type` fallback |
| Výbava | `extract_trim(subTitle)` |
| Záruka | "Ano" if `attr.gi` (Garantie) present, else `extract_warranty(subTitle)` |
| Tepelné čerpadlo | blank (not exposed by mobile.de; EV heat-pump requirement can't be enforced here) |
| Spárováno / Skóre shody | standard pipeline (ICE matched at scrape + build; EV prefix-join at build) |
| Extra | `"{cn} {loc}"` seller-location token + EV battery `attr.bc` → `"Baterie 27 kWh"` + `clean_extra`-cleaned subTitle |
| Stav | blank (no availability concept exposed; merge marks vanished rows Odstraněno — energycars precedent) |
| Zdroj | `Mobile.de` |
| Odkaz na auto | item `url` (`https://suchen.mobile.de/auto-inserat/....html`) |

ICE extraction order per conventions: extract first, `clean_extra()` last.

## Architecture

`scrapers/sources/mobilede.py` — `SOURCE_NAME = "Mobile.de"`, `SOURCE_SLUG =
"mobilede"`, `FUELS = {"EV", "ICE"}`, async `scrape()`. Units:

- `_get_eur_czk_rate(session)` — CNB fetch, fallback 24.5
- `_search(session, params, offset)` — one GET, JSON dict
- `_fetch_slice(session, params)` — page one query to its total (≤ 2000)
- `_fetch_all(session, params)` — recursive price-band splitter over the 2000 cap
- parsers: `_parse_int_attr` (ml/pw/cc share "1.499 x" shape), `_year_from_fr`
- `_build_row(item, rate)` — one canonical row or None (guards: price type/floor,
  excluded ft values as belt-and-suspenders)
- concurrency: semaphore 5, jittered; reuses `core/http.DEFAULT_HEADERS` + the
  `X-Mobile-Client` header

Pipeline untouched — `pipeline.run_source` handles dedup/match/merge/write as-is.

## Integration points

- `scrapers/run.py` SOURCES + `bin/run_all.sh` ALL_SOURCES: add `mobilede`
- `build/build_data.py` `load_scraper_csvs` list: add `mobilede`
- `.github/workflows/scrape-and-deploy.yml`: add to matrix; `continue-on-error` for
  the mobilede leg (undocumented endpoint may die — must not block the daily build;
  stale committed mobilede.csv is then reused); no Chromium install (aiohttp-only,
  same condition as sauto)
- `core/normalize.py` BRAND_MAP: `Skoda`, `Citroen`
- Env plumbing (future Search-API): `.envrc` (`dotenv var/.env`), `var/.env`
  gitignored, `var/.env.example` committed; no GH secret set yet (no key exists)
- Docs: CLAUDE.md source table, architecture.md, gotchas.md (new mobile.de section),
  conventions runner lists

## Testing

- `tests/test_mobilede.py` (offline, stdlib unittest): fixture item JSONs captured
  from live probes → `_build_row` golden tests (EV, ICE, hybrid, leasing-guard,
  gas-fuel guard); parser unit tests (ml/pw/cc/fr/price); price-band splitter tested
  with a stubbed fetch (no network)
- `./bin/test.sh` must stay green (incl. data-integrity invariants over rebuilt
  cars.json with mobilede rows present)
- Live verification: `python -m scrapers.run --source mobilede`, column count 25,
  value_counts spot-checks; `python build/build_data.py`; `verify_ui.py` grid pass

## Error handling

Adapter helpers catch broad `Exception` → safe defaults (`""` / `"Ne"`), per
conventions. A failed page fetch retries once, then that slice is dropped with a
printed warning (partial scrape is fine — merge keeps yesterday's rows as
Odstraněno only when a *successful* scrape omits them; a raised error aborts the
source before the CSV is written, keeping the old file intact).

## Risks

- Endpoint is robots-disallowed + undocumented → may break silently; CI
  `continue-on-error` + old CSV reuse contain the blast radius.
- DE EV volume (~14k rows) triples cars.json; AG Grid handles it, page payload grows
  (~gzip 2–3 MB). If too heavy in practice, tighten `EV_COUNTRIES`/price ceiling.
- `psz=100` verified accepted but not yet proven to return 100 items on a big result
  set (probe pool had < 100) — implementation verifies and falls back to 20.
