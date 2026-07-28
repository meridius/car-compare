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

### detail API has NO cylinder-count field (probed live 2026-07-05)

`https://www.sauto.cz/api/v1/items/{id}` carries `engine_power` / `engine_volume` but
no cylinder field of any spelling (checked against a live listing). The #24 column
"Počet válců" therefore stays blank from sauto; `extract_cylinder_count()`
(core/fields.py) probes plausible keys defensively in case the API grows one, and the
#30 "Spolehlivost" score degrades to volume-only by design.

### Převodovka value spelling differs per source

sauto (`gearbox_cb.name`) and mobile.de's German→Czech map emit "Automatická" /
"Manuální"; autodraft's extractor emits short "Automat" / "Manual". Anything consuming
the column must accept both spellings — `derive_transmission_type()` (build_data.py)
and `AUTOMAT_VALUES`/`MANUAL_VALUES` (site/transmissions.js) do.

### vehicle_body_cb is the primary body type source

The API field `vehicle_body_cb.name` returns Czech body names (Kombi, SUV, Hatchback). These are used directly — `extract_body_type()` is only a fallback when the API field is empty. Applies to both EV and ICE rows.

### build_record skips failed detail fetches

`fetch_detail()` returns `{}` on HTTP errors or exceptions. `build_record()` returns `None` when detail is empty, preventing incomplete records (no Stav, Palivo, Výkon, etc.) from entering the CSV. Without this guard, search-API-only data creates rows with only Model/Cena populated.

### "Ostatní" model recovery (EV)

sauto sometimes returns `model_cb` "Ostatní" for not-yet-indexed models (e.g. a just-launched EV); the real model hides in `additional_model_name` as a project code / trim string. `_recover_ostatni_model()` maps known cases (e.g. Kia EV2 via "QV1" / 42.2 kWh battery) so the car still matches the reference list.

### hard filters are centralized + surfaced on the dashboard

The numeric search thresholds both API scrapers enforce (year, mileage, price,
power, seats) live in **one** place — `scrapers/core/filters.py`. sauto.py and
mobilede.py import the constants (`MAX_MILEAGE_KM` etc.) rather than hard-coding
literals, and `filters.SOURCE_FILTERS` (human-readable, built from the same
constants) is written into `cars-meta.json.filters` by `build_data` and shown in
the dashboard "Přehled dat" overview as the "Kritéria výběru dat" card. So the
enforced value, the advertised value, and `tests/test_filters.py` can never
drift. To change a filter, edit `filters.py` only. Mileage ceiling is
`MAX_MILEAGE_KM = 150000` (raised from 100k on a family request). autodraft and
energycars scrape whole dealer inventories — they apply no numeric filter and
their `SOURCE_FILTERS` entries are empty (just a note).

### operating-lease takeovers leak past the `operating_lease=false` filter

Some listings are operating-lease takeovers ("Převzetí Op. Leasingu") whose `price`
is a buyout fee / akontace, not a purchase price (e.g. a Nissan X-Trail at 12 023 Kč).
The search filter `operating_lease=false` doesn't catch them. `_is_valid_purchase()`
(sauto.py) rejects them via detail fields `price_payment_count` /
`price_original_compensation` / `price_leasing`, plus a `MIN_PRICE_KC = 100000`
floor backstop (under our year≥2021 / km≤150k filters nothing real is cheaper — the
3 bogus rows were 12 023 / 17 009 / 60 500, the next legit car jumps to 150 000+).
Both `build_ev` and `build_ice` drop the row (`return None`).

### implausible engine volume guarded (sauto returns 14.9 l)

sauto's `engine_volume` is occasionally garbage — e.g. 14.9 l for a Kia XCeed
(real 1.5), 14 l for a KGM Korando. `sanitize_engine_volume()` (core/fields.py)
rejects anything outside [0.6, 8.0] l, first recovering from the model name
("XCeed **1.5** T-GDI"), else blanking. Applied in `build_ice` after the cc→l
conversion. autodraft is unaffected (its volume is name-derived, can't exceed 9.9).

### implausibly-low EV power blanked

sauto returns nonsense EV power for some listings (11 kW for a BYD Dolphin Surf).
`sanitize_ev_power()` blanks anything below `MIN_EV_POWER_KW = 20` (no modern EV is
that weak) rather than show a wrong figure. Applied in `build_ev`.

### EV Extra de-duplicated against the model name

`build_ev` runs the listing suffix through `clean_ev_suffix()` before appending it
to Extra: it strips a leading duplicate of the model name and hp/PS shorthand
("BYD Dolphin Surf 156k COMFORT" → "COMFORT"). The hp shorthand (`\d{2,3}k`) is also
stripped from ICE Extra by `clean_extra()` (`_HP_SHORTHAND_RE`); it never matches
"kWh"/"kW" (no word boundary before W).

---

## mobile.de

### keyless app endpoint, not the official Search-API

The adapter talks to `https://www.mobile.de/api/s/` — the private endpoint of the
mobile.de phone apps. It needs **no auth**, only the header
`X-Mobile-Client: de.mobile.android.app`; without it every request returns
`400 "Missing or invalid client header"`. The official Search-API
(`services.mobile.de/search-api`, HTTP Basic) has **no self-service signup** —
credentials are granted manually by mobile.de customer support. If they're ever
granted, `var/.env.example` documents the env vars and the adapter should grow a
second transport. The website HTML and `/consumer/api/` are Akamai-Bot-Manager
blocked (403 even for headless Playwright) — don't try to browser-scrape this site.
Caveat: `/api/` is disallowed in robots.txt and undocumented; it can change or start
enforcing request signing at any time (the CI leg is `continue-on-error` for this
reason).

### 2000-result cap → recursive price-band slicing

Any query exposes at most 2000 results through pagination (`ps` offset / `psz` page
size, max 100): past 2000 the API returns empty `items` with HTTP 200.
`_fetch_banded()` recursively halves the EUR price band (`p=min:max`) until each
slice's `numResultsTotal` < 2000. Band-boundary duplicates are deduped by link in
`pipeline.run_source`.

### prices are EUR — converted via CNB daily fixing

`price.grs.amount` (gross EUR) × CNB rate → "Cena (Kč)". The rate comes from the CNB
daily-fixing text endpoint at scrape time; on any failure a fallback constant
(`EUR_CZK_FALLBACK = 24.5`) is used, so listing prices can drift ±rate between runs.
Only `price.type == "FIXED"` is accepted (leasing/financing offers carry other
types), and sauto's `MIN_PRICE_KC = 100000` backstop applies after conversion.

### fuels are include-only; DE enabled for both EV and ICE

The API has no exclude operator — LPG/CNG/hydrogen are excluded by simply not
requesting them (`ft=PETROL&ft=DIESEL&ft=ELECTRICITY&ft=HYBRID&ft=HYBRID_DIESEL`
is the full allowed universe; repeated params are OR). `_build_row` re-checks
`attr.ft` against `_FUEL_MAP` as belt-and-suspenders. Germany is now in **both**
`EV_COUNTRIES` and `ICE_COUNTRIES` (decision 001 enabled DE ICE — ~123k listings
vs ~1.3k for CZ+SK+AT+PL, the bulk of the dataset). That request volume is what
makes the Akamai block below matter. Hybrids arrive as
`ft="Hybrid (Benzin/Elektro)"` / `"Hybrid (Diesel/Elektro)"` → Palivo Benzín/Nafta +
`Hybrid typ` from `extract_hybrid_type(subTitle)`, **blank when the subtitle carries
no explicit hybrid token** (subtype unknown — see the fabricated-hybrids gotcha below).

### German display strings everywhere

`attr` values are German-formatted display strings, not numbers: `ml` "29.000 km",
`pw` "110 kW (150 PS)", `cc` "1.499 cm³", `bc` "27 kWh", `fr` "02/2022" —
`_parse_number()` takes the first integer and strips dot thousands-separators.
Make names lose their diacritics ("Skoda", "Citroen") — BRAND_MAP restores them,
otherwise ICE matching finds no brand candidates. Category `attr.c` uses mobile.de's
own body taxonomy (OffRoad→SUV, EstateCar→Kombi, SmallCar→Hatchback, …).

### `attr.c` "Limousine" → blank, not "Sedan/limuzína" (it's a catch-all)

German dealers tag hatchbacks — and even EVs (BMW i3, BYD ATTO 2, Cupra Born,
Audi Q4 e-tron Sportback all arrived tagged "Limousine") — under `attr.c`
"Limousine", not just sedans. Mapping it to a confident "Sedan/limuzína" fed a
wrong body into (a) the `matching.py` body score (weight 3 — hatchback listings
got penalised against the correct hatchback reference) and (b) cluster body votes
/ `diagnose_unpaired` candidate rows (Ford Focus + Audi A3 candidates had to be
hand-blanked before `apply`). `_CATEGORY_MAP["Limousine"] = ""` therefore blanks
it, exactly like `"OtherCar"`: `_build_row` falls through to
`extract_body_type(title)` (which recovers a real token — Sportback/Combi/SUV —
when the German title carries one; `BODY_KEYWORDS` has no Sedan/Limousine token so
it never re-derives sedan), and the reference-body / majority-vote / `derive_body`
chain in `build_data` fills the rest. Cost (accepted): true unmatched sedans lose
their explicit tag and fall to `derive_body` — net accuracy still rises because
most "Limousine" rows were mis-tagged, and matched sedans get the body from the
reference regardless. The fix is source-local; `matching.py` stays source-agnostic.
Pinned in `tests/test_mobilede.py` (`test_limousine_category_maps_to_blank`,
`test_limousine_title_body_token_still_recovered`).

### Akamai Bot Manager — low concurrency + patient backoff, no rate headers

The `/api/s/` endpoint sits behind Akamai Bot Manager (`Akamai-GRN` header,
`ak_bmsc` cookie). Probed 2026-07-05: it does **not** trip on instantaneous
concurrency (120 concurrent = all 200) nor on sustained low-rate sequential load
(225 sequential @ ~4/s = all 200). It blocks with a **bare 403 — no Retry-After
or X-RateLimit-\* headers** — once a *datacenter* IP crosses a cumulative,
behavioural threshold: a GitHub-hosted (Azure) runner gets flagged where a
residential IP doesn't, and in CI the daily scrape 403'd only after EV's hundreds
of requests, mid-ICE. So the block is about *who + how much over time*, not raw
burst rate. Mitigations in the adapter:

- **Every** request is semaphore-bounded. `_count` used to bypass the semaphore,
  so the recursive `_fetch_banded` gather fanned out *unbounded* concurrent count
  requests (the burstiest, most bot-like phase). All requests now go through
  `_search(…, sem)`.
- `CONCURRENCY = 3` (was 5): steady low-concurrency pacing over bursts.
- `_search` rides out `403/429/503` with a progressive backoff
  (`_RATE_LIMIT_BACKOFF = 5/15/45/90 s`; honours a numeric `Retry-After` if the
  endpoint ever grows one) so a *windowed* block clears before the leg gives up.
  The backoff sleep is **outside** the semaphore so a throttled worker doesn't
  hold a slot. After `_SEARCH_ATTEMPTS` it propagates.
- The leg staying `continue-on-error` in CI is deliberate: a hard block aborts
  the source so the pipeline reuses last-known state. A *partial* ICE scrape must
  never be written — merge would mark the missing bands' listings `Odstraněno`.
- Ceiling on what this can achieve: Akamai ultimately wants a real browser's JS
  sensor (unavailable here). If the datacenter IP is hard-blocked regardless,
  the sanctioned Search-API (see the keyless-endpoint gotcha) is the fallback.

### Stav is always blank

Like energycars, mobile.de exposes no availability concept in search results. The
merge step still marks vanished listings `Odstraněno`. `attr.gi` (Garantie until
MM/YYYY) drives `Záruka = "Ano"`.

### CI never scrapes on push (rate-limit guard)

mobile.de rate-limits by IP, so the workflow must not scrape on arbitrary changes.
Scraping runs **only** on the daily cron or a manual `workflow_dispatch` (which has a
`skip_scrape` input to deploy without scraping). Pushes to `main` — filtered to paths
that affect the built site (`site/**`, `build/**`, `scrapers/core/**`,
`scrapers/data/reference/**`, the workflow file) — **rebuild + redeploy from the state
already in the rolling `data` release**, no fetch. Mechanics: `scrape` is gated
`if: github.event_name != 'push' && inputs.skip_scrape != 'true'`; `build` runs when
scrape succeeded *or* was skipped (`always() && result != 'failure'/'cancelled'`) and
only pulls the `state-*` artifacts when scrape actually ran.

### "Andere" is mobile.de's junk model bucket — recovered from subTitle/shortTitle

mobile.de returns `Andere` (German "Other") as the model for cars its taxonomy
doesn't index — the scraped name would become e.g. "JAC Andere", "ORA Andere",
even "Andere Andere" (~390 state rows across ~20 clusters, 2026-07). These are
NOT missing reference models: never add an "X Andere" reference row (it would
base-match every future unindexed car of that brand regardless of what it is) —
`build/diagnose_unpaired.py` `candidate`/`apply` hard-refuse such candidates
(`is_junk_bucket`), so the `ai-match-one.sh` loop can't waste an AI research
call on one. The name is recovered adapter-side by `_recover_andere_model()`
(mobilede.py), mirroring sauto's `_recover_ostatni_model()`, from two shapes
probed live 2026-07-12 (48/53 recovered):

- **known make, model "Andere"** → the real model is the *leading token* of
  `subTitle` ("Tarraco *LED*…" → Seat Tarraco; "Crossland 1.2 …" → Opel
  Crossland; "Cee'd SW Gold" → Kia Ceed via normalize_model).
- **make "Andere"** ("Andere Andere") → the real "Make Model" leads
  `shortTitle` after the "Andere " prefix ("Andere Ford Puma 1.0 …" →
  Ford Puma; all-caps brands > 3 chars are title-cased so BRAND_MAP can
  restore diacritics: "CITROEN C3" → Citroën C3).

Junk openers (Elektro/Benzin/German filler — `_ANDERE_JUNK_TOKENS`), decimals,
1-2-digit numbers, years and single-char tokens are rejected → the row keeps
"Make Andere" (conservative, matches as `Ne`). A curated `_ANDERE_RECOVERY`
list (like sauto's) overrides rebadges the heuristic can't know: Elaris Beo is
the rebadged Skywell ET5 and dealers list the donor name. Rows already sitting
in state heal on the next scrape (merge: new data wins by link); removed rows
keep the junk name forever (merge carries forward, see merge gotcha).

### German "Hybrid" listings fabricated PHEV/HEV variants — FIXED 2026-07-13

mobile.de delivers mild/full/plug-in hybrids under one `ft="Hybrid (Benzin/Elektro)"`
umbrella, so the subtitle text is the only subtype signal. The **root cause** was
`extract_hybrid_type()` (core/fields.py) doing naive **substring** matching: the
PHEV token `"iV"` (Škoda badge) matched inside **Priv**acy / Dr**iv**e / Act**iv**e
→ ~15.5k rows stamped a fabricated PHEV (Audi Avant 35 TDIs etc.), while real PHEV
tokens (`GTE`, `Plug-In`, `eHybrid`) and the MHEV token `Mild-Hybrid` were missed
and fell through to a blanket **HEV default** in `_build_row`. So the state held
hundreds of e.g. "BMW 118 PHEV" rows although no 1-series PHEV was ever built.

Fixed in two places:
- **`_HYBRID_PATTERNS` / `extract_hybrid_type` (core/fields.py)** — ordered,
  **word-bounded** regexes, priority **PHEV → MHEV → HEV**. Word boundaries kill
  the `iV`-in-`Privacy` fabrication (and `\biV\b` is **case-sensitive** so Roman
  "IV" generations don't read as the Škoda badge); expanded vocab catches GTE /
  Plug-In / eHybrid / E-Tense / EQ Power (PHEV) and Mild-Hybrid / 48V / mHEV /
  EQ Boost (MHEV). Ambiguous bare badges (Renault "E-Tech" = full OR mild OR EV)
  are deliberately **absent** — they classify only via an explicit full/mild
  qualifier. Source-agnostic (sauto/autodraft benefit too).
- **`_build_row` (mobilede.py)** — dropped the `if not hybrid: hybrid = "HEV"`
  fallback (and the now-dead `_HYBRID_FTS`). A tokenless hybrid → `Hybrid typ`
  **blank** (subtype unknown; `Palivo` still Benzín/Nafta). Blank is the
  zero-fabrication choice: the row is a plain hybrid-fueled ICE and pairs cleanly
  with the non-hybrid reference row (one-sided hybrid penalty is only −1), instead
  of a fabricated PHEV/HEV sibling tying the cluster into Nejisté.

Pinned by `tests/test_fields.py::ExtractHybridTypeTest` (truth table incl. the
substring-noise cases) + `tests/test_mobilede.py` (`test_tokenless_hybrid_gets_blank_type`,
`test_diesel_hybrid_tokenless_blank`, updated `test_hybrid_row` → MHEV on "48V").
**Existing state heals only on the next real mobile.de scrape** (adapter runs at
scrape time; merge: new data wins by link) — removed rows keep the old label
forever (merge carries forward). The earlier reference-growth mitigation still
stands: genuine PHEVs (330e, DS7 E-Tense, …) keep their own rows, fabricated ones
were never added (`diagnose_unpaired` research `exists:false` guard).

### country → the shared "Země" column, not Extra

`attr.cn` (ISO code) maps via `_COUNTRY_MAP` to the Czech country name in the canonical
`Země` column (CZ→Česko, SK→Slovensko, DE→Německo, AT→Rakousko, PL→Polsko; unknown
codes pass through verbatim). Extra now keeps only the city (`attr.loc`), not the old
"CZ Beroun" country-prefixed token. mobile.de is the only source with non-CZ rows —
the three Czech sources hard-code `Země = "Česko"`, and `build_data.backfill_country()`
fills `Česko` on any non-mobile.de row whose `Země` is blank (CSVs written before the
column existed). The dashboard shows `Země` as a set-filter column and a "Země × Typ"
card in the dataset overview.

---

## core — storage & payload (parquet)

### state parquet is stringly on purpose

`storage.write_state()` coerces every column to str with blanks `""` — exact
parity with the old `pd.read_csv(dtype=str).fillna("")` contract. Typed state
would change merge/matching comparisons (e.g. `row["Stav"] == "Odstraněno"` on
NaN). The typed payload is built separately in `build_data.write_payload()`.

### payload numeric columns must be float64, never int64

hyparquet decodes parquet int64 as JavaScript BigInt; grid formatters call
`toFixed` → crash. `write_payload()` casts all numeric cols to float64
(pinned by `test_no_int64_columns`). Same trap: a numeric-in-the-grid column
missing from `numeric_cols` stays a *string* after the stringly state read and
crashes formatters ("Objem motoru" bug) — every `num: true` column in
`site/app.js` COL_CONFIG must be in `write_payload.numeric_cols`.

### hyparquet import must be version-pinned

The unpinned `cdn.jsdelivr.net/npm/hyparquet/+esm` URL serves a stale cached
build. `site/app.js` pins `hyparquet@1.26.2`. Payload uses **snappy** (native
in hyparquet); switching to zstd would require the extra `hyparquet-compressors`
package in the browser.

### full-buffer fetch on purpose (Pages gzip+Range bug)

GitHub Pages computes `Content-Range` against the *gzipped* byte stream for
compressible types, corrupting ranged reads (verified live 2026-07). `app.js`
therefore fetches `cars.parquet` as one ArrayBuffer — no Range requests. If a
future DuckDB-WASM upgrade needs ranged reads, verify Pages serves `.parquet`
uncompressed first.

### seed CSVs are frozen, not dead

`storage.read_state()` prefers `<slug>.parquet`, falls back to the git-tracked
`<slug>.csv`. CI seeds from the rolling `data` release; a fresh clone without
release access still builds from the seeds. The seeds stop being updated — do
not "fix" data in them.

### live / archive split (removed listings are lazy-loaded)

`build_data.write_payload()` splits the payload by `Stav`: live listings →
`cars.parquet` (always loaded), removed (`Stav=="Odstraněno"`) →
`cars-archived.parquet` (fetched only when the user clicks "Načíst archiv" in
`app.js`). So the always-loaded payload stays bounded by the live market even as
removed listings accumulate. `cars-meta.json` carries `archivedCars` so the
button can show the count (and hides when 0). The archive file is always written
(empty frame keeps its schema) so the browser fetch never 404s.

### merge keeps removed rows forever by default

`REMOVED_RETENTION_DAYS = None` → `merge_with_previous()` keeps every removed row
(they become the archive; monthly snapshots are the permanent record). Pass
`retention_days=N` to cap it if the archive ever needs bounding. This is a
deliberate reversal of the original "drop after 60 days" — the live/archive split
removed the size pressure that motivated a hard cap.

### live payload must never contain Odstraněno rows

`test_data_integrity.test_live_payload_has_no_removed_rows` pins it — a removed
row leaking into `cars.parquet` means it shows without the user loading the
archive, and doubles up once they do.

### to reproduce prod locally, pull the payload from Pages — not the release

The built payload lives in two places, and they can disagree. The **deployed
Pages** files (`https://<org>.github.io/car-compare/data/cars.parquet` + sidecars)
are always what prod serves and are **publicly fetchable with no auth**. The
rolling **`data` release** payload asset, however, is only refreshed by *scrape*
runs (daily cron / manual), because that upload step is gated
`if: needs.scrape.result == 'success'`. A **push** deploy rebuilds the payload
and ships it to Pages but historically did *not* republish it to the release — so
after any push (e.g. a reference-CSV change) the release payload lagged prod,
sometimes by tens of thousands of matches. This bit us live 2026-07-09: prod
showed 1 021 unpaired (ref 402/189) while the release asset still held the 09:43
schedule build (1 pull → 14 909 unpaired, ref 301/89).

Two consequences:

- **`bin/serve.sh --pull` downloads the deployed Pages payload directly** (curl,
  no `gh`), so local == prod byte-for-byte regardless of release staleness.
  `bin/bootstrap-data.sh` still pulls the *release* (state parquets, for running
  scrapers locally) — a different job; don't use it to mirror prod's grid.
- The workflow now publishes the **payload** on *every* successful build (push
  included) in a separate step from **state** (scrape-only), so the release asset
  no longer lags Pages. A stale local `site/data/cars.parquet` served without
  `--pull` looks like a prod/local data mismatch — rebuild or `--pull`.

---

## site — URL state codec (`#f=` / `#t=`)

Shareable dashboard state lives in the URL **fragment**, not the query string:
filters `#f=` (both pages) + colour thresholds `#t=` (index only). Encoded by a
compact custom codec in **`site/url-state.js`** (`window.UrlState`), shared by
`app.js` and `reference.js`, **not** base64 — the `ceed` example went from a
~120-char base64 blob to `#f=Model~tcceed`. Column layout is deliberately **not**
in the URL (see below). Pinned by `build/verify_ui.py` scenarios `url-state`
(index) and `url-state-ref` (reference): round-trip battery + live reload +
column-in-localStorage-not-URL + legacy migration. The `#t=` half of `url-state`
drives the threshold from the **column-filter popup** (the drawer has no threshold
boxes any more) and proves it *still colours* after the reload by diffing the
column's inline cell backgrounds — asserting only "the value is back in
localStorage" would pass on a payload that no longer tints.

`url-state.js` is a plain `<script>` loaded **before** the page script in both
HTML files (index's `app.js` is an ES module = deferred, so the plain script runs
first and `window.UrlState` is ready).

### fragment, not query — Referer leak + `btoa` non-Latin1 throw

Two reasons the state moved from `?filters=`/`?cols=` to `#`:
- **Referer leak**: query strings are sent in the `Referer` header to third parties
  (the page loads hyparquet from the jsdelivr CDN), so `?filters=…` leaked the user's
  filters off-site. A `#fragment` is never sent anywhere.
- **`btoa` throws on Czech column names**: the old `saveColState` did
  `btoa(JSON.stringify(ids))` where ids include "Značka"/"Nájezd"/… — `btoa` can't
  encode non-Latin1 and **throws**. `localStorage.setItem` ran first (order-only), so
  the localStorage copy survived but the URL write silently died — `?cols=` had been
  **broken the whole time**. The filters path avoided it with the
  `btoa(unescape(encodeURIComponent(…)))` idiom; cols never got it. The new codec uses
  `encodeURIComponent` throughout — no `btoa`, no throw.

### enc()/dec() escaping — the four raw delimiters

`enc()` = `encodeURIComponent` **plus** percent-encoding the four chars it leaves raw
that the codec uses structurally: `-` `_` `~` `*`. So an `enc()`'d token is drawn from
`[A-Za-z0-9.!'()]` + `%XX` and can never contain a delimiter → splitting on `; , ~ | -`
is always unambiguous, even when a filter *value* contains those chars. `*` (raw) is the
reserved sentinel for a **null set value** (the SetFilter's blank/`(∅)` bucket, which
`getModel()` emits as `null` in `values`). Number `inRange` uses raw `-` as the
from/to separator — safe because a negative value's own `-` is escaped to `%2D`.

### column layout is localStorage-only, never the URL

Full column state (order + sort + width + pin + hide) is persisted to
`localStorage` (`carCompareColState` / `refCompareColState`) on every layout event
(`onDragStopped`/`onSortChanged`/`onColumnPinned`/`onColumnVisible`/resize-finished)
and restored on load — but it is **not** written to the URL. Reason: expressing a
reorder needs the full ordered column list, so any single change would bloat every
shared link with ~40 column tokens. Layout is per-browser convenience state;
filters are the shareable thing. `writeHash()` therefore only ever emits `#f=`/`#t=`
and always strips the legacy `?cols=` param. localStorage stores the full
`getColumnState()` JSON (old format was a bare colId array — `loadColStateFromStorage`
still reads it: `typeof v[0] === "string"` ⇒ map to `{colId}`).

### legacy `?filters=<b64>` links auto-migrate; no `#f=b64:` forward fallback

`onGridReady` reads `#` first; if absent, `UrlState.decodeLegacyFilters()` decodes an
old base64 `?filters=` link, applies it, then `writeHash()` rewrites the address bar
to `#f=` and strips `?filters`/`?cols`. Old shared links keep working and silently
upgrade. (Old `?cols=` links never actually existed — that write always threw on the
`btoa` bug — so only filters are migrated.) There is intentionally **no** forward
`#f=b64:` fallback: the codec is total over the grid's filter universe
(text/number/date/set/combined), so a fallback would catch nothing; an unknown future
filter type should fail loud, not emit opaque base64.

### date filters ride a `D`-prefixed op body (added with "Odstraněno dne")

`agDateColumnFilter` models (`{filterType:"date", type, dateFrom, dateTo}`) encode
via `encSimpleCond`/`decSimpleCond` under the `D` kind char (distinct from text `t`,
number `n`), op map `DATE_OP` (equals/notEqual/greaterThan/lessThan/inRange/blank/
notBlank — no `…OrEqual`, AG's date filter lacks them). `dateFrom`/`dateTo` are
`"YYYY-MM-DD HH:mm:ss"` strings, but the codec **stores only the day** (`dayOnly`) and
restores ` 00:00:00` on decode (`restoreTime`) — date-only filters are always midnight,
so the time is redundant noise in `#f=`. The raw `-` stays the `inRange` separator (same
trick as number `inRange`). Combined AND/OR date conditions work through the same `k`
path. Round-trip + no-time-in-URL pinned in `verify_ui.py` `_codec_battery` (greaterThan
/ inRange / notBlank cases).

---

## site — UI (redesign 2026-07)

### the numeric filter is a distribution track (histogram), not a gradient slider

Every numeric column on **both** pages filters through the custom AG `RangeFilter`
(IFilterComp, `site/app.js` + `site/reference.js`), rendered in the column-filter
popup instead of AG's two text inputs. The popup, top to bottom:

```text
.rf-name-row    .rf-name (column) · .rf-dir ("více = lépe") · .th-reset
.rf-ctl-row     .seg (Vše | Po filtru | Obojí) · .ht-zoom (Lupa) · .rf-readout (hover)
.track-wrap     .ht-track (canvas + .ht-ylabels + the two range thumbs) · .ht-xaxis
.th-pair        od / do number boxes
.rf-blank-row   "Bez hodnoty:" .seg (Skrýt | Zahrnout | Jen ty) · .rf-blank-count
.rf-check       "Jen barvit, nefiltrovat"
```

Drawing lives in **`site/hist-track.js`** (`window.HistTrack`, a plain `<script>` on
both pages); the page module only feeds it data + colours and owns the DOM around it.
`userThresholds[field] = {min,max}` is still the **single source of truth** for both
the heat-map colouring AND row filtering: every editor (thumb, box, reset) routes
through `commitRange(field,min,max)`, which mirrors state into the other controls
(skipping the focused one) and debounces (220 ms) the expensive recolour +
`setColumnFilterModel` + `onFilterChanged` off the 150k-row hot path. `setModel`
writes shared state but does **not** call `commitRange` (AG drives the filter pass),
so there is no loop. Blank-mode / colour-only changes go through
`commitFilterShape()` instead — they alter the model, not the range, so there is no
drag to debounce.

**The two stores still split by concern — filtering vs colouring.** The filter store
(`#f=` / `carCompareFilters`) is the *sole* source of truth for which columns filter;
the threshold store (`#t=` / `carCompareThresholds`) only tints. On load the filter is
restored from the filter store alone — a colour-only threshold is **never** re-armed
as a filter (the deleted `activateRangeFilters()` used to resurrect filters the user
had cleared, 2026-07-13). Setting a range still couples both at *edit* time; only
clearing is asymmetric.

Traps in the track itself:

- **It is a canvas, not flexbox.** DOM bars with `flex:1` + a 1px gap get their
  fractional pixels spread by the browser, so bars come out 4px/5px/4px. `layout()`
  instead picks an **integer** bar width up front, makes every gap exactly `GAP` (1px),
  and pushes the **leftover pixels to the two EDGES as padding** — never between bars.
  It is also one node per track instead of ~50, and hover is arithmetic (`binAt`), not
  hit-testing.
- **Bin count follows the track WIDTH**, capped to one bin per value for coarse
  columns (`maxBins` derived from the column `step`; "Rok výroby" spans 12 values and
  48 bins combed it into bars-and-gaps that read as missing data — those bars widen to
  fill the track instead).
- **Bar heights are sqrt-scaled.** Several columns are extremely peaked (Objem motoru
  is ~all 1.5–2.0 l) and would render as an invisible stub on a linear axis. Read it
  accordingly: **a gridline halfway up the track is a QUARTER of the peak**, not half.
  No number is ever printed off a bar's height — the hover `.rf-readout` prints the
  real count.
- **Count gridlines are rounded DOWN to a nice number ≤ peak, and FROZEN during any
  animation.** A line above the tallest bar reads as a broken axis; and deriving
  `niceTicks()` per frame made the labels flicker through different round numbers, so
  the animated frames carry the END state's ticks. The labels are DOM spans
  (`.ht-ylabels span`) in a `GUTTER = 34` px left gutter, **reused** across frames
  (recreating them made the text twitch), and one unit covers the whole axis (mixing
  "10 tis." with "1 000" reads as two different scales).
- **Which animation runs depends on WHAT changed** (`Track.render`): domain changed
  (Lupa) → interpolate the **axis** and re-bin per frame, so bars spread apart / draw
  together; **bin count** changed (resize) → short cross-fade, because bin *i* means
  something different on the two sides and a height tween would be a lie; counts
  changed (mode switch) → tween the bar heights.
- **Bar colour comes from the value's GLOBAL position** in the column's full range,
  never from the bin index — so a zoomed axis does **not** repaint globally-cheap cars
  red.
- **"Po filtru" counts the rows the grid SHOWS — this column's own range included.**
  Cheap (one pass, no filter simulation) and honest: the bars are literally what is in
  the table, which is also why they shrink as you drag a bound. "Obojí" draws all rows
  faintly behind on a **shared** scale, so the height ratio is the share that survives
  the filter; "Po filtru" alone self-scales, so a narrow filter still draws a readable
  shape. The mode+zoom pair is a **global** appearance pref
  (`localStorage["carCompareHistMode"] = {mode, zoom}`, shared by both pages like the
  palette), so one segment click drives every open track.
- **Filtered values are cached per filter version, never per frame** (`filteredCache`
  keyed on `filterVersion`, bumped in `onFilterChanged`): the tracks re-bin from that
  cached array on **every** animation frame, so a `forEachNodeAfterFilter` pass per
  frame would be fatal. `setHistRows()` drops the caches when the row set changes
  (archive load).
- **Bins are counted over the rows in the grid**, so `loadArchive` concatenates the
  archive rows and repaints. The *range* stays live-anchored (`computeRanges` is not
  re-run), so archive values outside it clamp into the edge bins — the same clamp
  `numericCellStyle` applies to `pos`.
- **`repaintTracks()` must run on theme AND palette change** (`applyTheme`,
  `updateThresholdGradients`) — `heatRGBof` is theme-tuned, so bars baked at dark-mode
  colours would survive a switch to light. `applyTheme` runs from `initTheme()`
  *before* `var liveTracks` is assigned, hence the `if (!liveTracks) return` guard.
- **Known limit — an outlier stretches the axis.** The track spans the column's full
  data range, so "Cena (Kč)" (max 3.36 M from a handful of dealer exotics, p99.5 =
  749 k) compresses the whole real market into the left ~18 %. The Lupa is the per-use
  escape hatch. A permanent fix means giving `colRanges` a robust (quantile) max, which
  changes colouring and the slider's reachable maximum for everyone — a product
  decision, not a rendering one.
- **`fmtRangeNum`, not `fmtNum`** — `app.js` already has a 1-arg `fmtNum(n)` for the
  overview tables. The range formatter is 2-arg (`field, v`, cs-CZ thousands
  separator, `useGrouping:false` for "Rok výroby" — a year is not a thousand) and is
  named `fmtRangeNum` to avoid the hoisted-declaration collision that silently made
  every input read "NaN". Number boxes are `type=text inputmode=decimal` (a
  `type=number` box can't render a thousands separator); `parseNum` strips `\s`
  (JS `\s` covers NBSP/narrow-NBSP that `toLocaleString` emits) and folds the comma
  decimal.
- **`doesFilterPass` coerces** — `reference.json` stores some numeric columns as
  strings ("150"); `computeRanges` (typeof number) skips them so they get number
  boxes but no track, and `doesFilterPass` does `parseFloat` so filtering still works.
  `app.js`'s payload is float64 so this never bites there.
- Pinned by `verify_ui.py` `hist-track` (canvas has ink; `layout()` geometry is
  integer / non-overflowing / maxBins-honouring; `niceTicks()` is a whole-car axis;
  the rendered gridline labels are ≤ 3, increasing and never above the peak),
  `hist-modes` (segment + localStorage + the canvas actually repainting per mode) and
  `hist-zoom` (axis really moves, ± icon flips, count labels do **not** flicker) —
  both pages, both themes.

### blank cells are a filter question, answered with AG's OWN model shapes

"Bez hodnoty" (Skrýt / Zahrnout / Jen ty) makes "show me only cars that HAVE a
number" / "only the ones missing it" expressible, and `rangeModel()` maps it onto
shapes AG already understands:

```text
hide + bounds → { filterType:"number", type:"inRange", … }        (blanks fail)
show + bounds → { operator:"OR", conditions:[ inRange, {type:"blank"} ] }
only          → { filterType:"number", type:"blank" }
colour-only   → no model at all (isFilterActive false)
```

That is why the URL codec (`site/url-state.js`) and `filter-chips.js` needed **no
change**: `#f=Kapacita…~nb` is the existing blank op and `~konr100-200|nb` the
existing combined-OR body. `.rf-blank-count` prints how many rows have no value so the
choice is informed ("Kapacita baterie" is blank on every combustion car), and "Jen ty"
greys out the range + the colour-only checkbox — a numeric range under "only blanks"
would silently do nothing. Pinned by `verify_ui.py` `blank-filter` (row counts *and*
the emitted model for all three states, both pages, both themes).

### three traps found by actually clicking the popup (2026-07-28)

Found only by real clicks/drags — every earlier check drove the filter through
`setColumnFilterModel`, which exercises none of these:

- **The canvas must be `pointer-events: none`.** `RangeFilter.init` appends the two
  range inputs to `.ht-track` *before* `makeTrack()` creates the canvas, so the canvas
  is a later sibling and painted on top: the thumbs became undraggable. Hover is
  listened for on `.ht-track` (arithmetic, not a hit-test), so the painted layers never
  need to be pointer targets — `.ht-canvas`, `.ht-ylabels` and `.ht-xaxis` are all
  click-through.
- **A null model is not a reason to reset "Zahrnout".** "Zahrnout" with no bounds
  filters nothing, so `rangeModel()` returns null, AG echoes that back through
  `setModel(null)` — and the old code read null as "no blank rule" and sprang the pill
  back to "Skrýt", which read as an unclickable button. `setModel` now treats a null
  model as agreement for `show` (and only contradicts `only`, which *is* a filter).
- **`clearFilters()` must re-render the chips itself.** With a colour-only range the AG
  filter model is already empty, so `setFilterModel(null)` changes nothing and
  `onFilterChanged` never fires — the cleared "jen barva" chip stayed on screen. It also
  clears `userThresholds` / `colourOnly` / `blankModes` now and repaints the cells,
  because those ranges are exactly what the chip bar shows; the appearance drawer
  therefore has **no** clearing button at all (it would have read as "clear filters"
  while sitting among colour settings).

### colour-only = a threshold with no filter model, plus its own dashed chip

`colourOnly[field]` (persisted as a field list in `localStorage["carCompareColourOnly"]`)
does not change the `{min,max}` state at all — it only says "do not turn it into a
model", so `isFilterActive()` returns false and the column keeps its tint while hiding
nothing. AG then has no model to render a chip from, so `colourOnlyChips()` feeds
`renderFilterChips({extraChips})` a dashed **`.filter-chip.tint`** with a
`.filter-chip-tag` "jen barva"; its × calls `clearColumnRange()` (colour + blank rule +
model). Without that chip a column could stay tinted with nothing on screen saying so —
which is exactly the invisible leftover the old "chip × keeps the colour" behaviour
produced. A **normal** numeric chip's × now clears the colour too
(`onRemoveField`). Pinned by `verify_ui.py` `colour-only` (row count returns to the
full set, the dashed chip + tag render, the cells' inline heat backgrounds change and
then return to baseline after the ×).

### heat-map colouring is a user-selectable palette × style, theme-aware

`numericCellStyle` (both `site/app.js` and `site/reference.js`) no longer bakes a
fixed red→green HSL. Colour = a **palette** (`redgreen` / `bluered` / `blueorange`
/ `tealamber`; good→mid→bad diverging, `HEAT_PALETTES`) × a **style** (`fullcell`
/ `databar` / `combo`; `HEAT_STYLES`), chosen in Nastavení barev and persisted to
`localStorage["carCompareHeatMode"]` (**shared across index + reference** — it's a
global appearance pref like the theme). Default is soft **red-green combo (bar + tint)**.

- **Theme-aware:** the mid-tone and alphas depend on `isDarkTheme()`; `applyTheme`
  calls `gridApi.refreshCells({force:true})` so cells re-tint on theme switch. The
  old code hard-coded `hsl(h,80,35)` and forced `color:#fff`, so light theme got
  dark slabs with unreadable text. Cells now inherit the theme foreground (no
  forced colour); alphas are tuned so text stays legible over fill.
- **All styles paint via the cell `background` only** (full-cell = `backgroundColor`
  tint; databar / combo = a hard-stop `linear-gradient`) — **no `cellRenderer`**, so
  column virtualisation stays fast. `pos` = value's magnitude in range (bar length);
  `t` = badness 0…1 (colour). `greenHigh` (higher-is-better) flips `t`.
- Colour-blind note: `redgreen` is kept only as an option/default-on-request;
  `bluered`/`blueorange`/`tealamber` are the accessible palettes (they keep the
  blue–yellow axis CVD preserves).

### AG Grid ignores "\n" in headerName under wrapHeaderText — hyphenation does the wrapping

With `wrapHeaderText:true` + `autoHeaderHeight:true`, AG width-wraps header text and
**does not honour embedded `\n`** in `headerName` (the many `hdr:"Foo\nBar"` hints in
COL_CONFIG are effectively decorative). Left to itself it broke words mid-syllable
("Objem motor u"). Fix is CSS in `style.css` `.ag-header-cell-text`:
`white-space:pre-wrap; overflow-wrap:break-word; hyphens:auto` + `lang="cs"` on
`<html>` → long single words hyphenate at proper Czech points. A column too narrow
for even the hyphenated word still breaks ugly — widen it (that's why "Počet válců"
is `w:82`, not 70).

### Stav is availability only — match-confidence colour lives on Spárováno

The Stav cell used to be tinted (and carry a native `title`) by the row's
`Spárováno` value — colour that meant something unrelated to the cell's "Ojeté"
text, and redundant with the Spárováno column. Dropped: `stavRenderer` no longer
sets a title, and Stav's cellStyle is plain. The red/amber tint + a real
`tooltipValueGetter` (rendered by `ColTooltip`) live only on the **Spárováno**
column, where colour and value agree.

### header is a single-row toolbar; nav tabs are real <a> links

`<header>` on all three pages: icon-only brand (`.brand-home` → index.html),
`.nav-tabs` of real `<a>` links (middle/ctrl-click opens a new tab — the old
`<button onclick="location.href">` couldn't), then page-specific controls and a
`.menu-wrap` gear menu holding **Vymazat filtry + Reset sloupců + Nastavení barev
+ Přepnout motiv** (all rarely-used actions live there; the filter-chips bar's
"Vymazat vše" keeps filter-clearing one click away while filters are active).
`applyTheme` updates `#btn-theme .theme-glyph` (a span), NOT the button's
textContent — overwriting textContent would wipe the "Přepnout motiv" label
(index/reference); transmissions keeps a plain icon `#btn-theme` and still sets
textContent. The `#btn-theme` sizing rule is scoped `#btn-theme.icon-btn` — an
unscoped ID rule out-specifies `.menu-item` and renders the menu row oversized.
The reference page's smart-search bar (#29) was **removed** (user request) — the
Model auta floating filter covers the lookup; quick-filter plumbing is gone.

### "Odstraněno dne" is an agDateColumnFilter over ISO strings — needs a comparator

The payload is stringly (dates are `"YYYY-MM-DD"`), so the date column can't use
AG's native Date comparison. `DATE_FILTER_PARAMS` (`site/app.js`) gives
`agDateColumnFilter` a `comparator` that parses the cell string into a **local-midnight**
`Date` via `new Date(+y, +m-1, +d)` — **not** `new Date("2026-07-11")`, which parses
as UTC midnight and shifts a day in negative-offset zones, breaking equality. Blank
cells return -1 (sort before any date) so an after/range filter excludes the live
rows (only Odstraněno rows carry a date — load the archive to see matches).
`buildColumnDefs` passes any `cfg.filterParams` straight through (previously only
`cfg.groups` did).

**`inRangeInclusive: true` is required.** AG's `inRange` defaults to *exclusive*
bounds (`inRangeInclusive: false` → strict `<`/`>`). With day-granular dates a range
like `[08-07, 09-07]` then matches **nothing** — both endpoints excluded and no value
lies strictly between two adjacent days. Inclusive is what "between these dates" means.

**Deliberately NOT `browserDatePicker: true`.** AG defaults `browserDatePicker` to
**true whenever the browser supports `<input type=date>`** — so it must be set to
`false` *explicitly* (omitting it is not enough). The native `<input type=date>` renders
in the *browser's* locale (dd.mm.yyyy / mm/dd/yyyy — never the ISO yyyy-mm-dd the cells
show) and its "Clear" button is untranslatable browser chrome (stays English on an
en-locale browser). AG's own date **text input** defaults to the `yyyy-mm-dd` format —
consistent with the cell display — and its only clear control is the AG "Vymazat" reset
button (localised). Cost: no calendar popup, the user types the date. The date filter's
option dropdown relabels lessThan/greaterThan as **`before`/`after`** (its own locale
keys, distinct from the number filter's) — so `localeText` needs `before`/`after`
(`Před`/`Po`) *in addition to* lessThan/greaterThan, or those two options leak English.

**Digit-mask on the entry field.** AG's date text input accepts any text; a
**capture-phase** `document` `input` listener (`app.js`, scoped to `.ag-date-filter`
inputs) strips non-digits and auto-inserts the two dashes, running *before* AG's own
target-phase handler reads the value so AG only ever parses a clean yyyy-mm-dd. This is
NOT a custom `dateComponent`: a `colDef.dateComponent` class-ref (the documented API) is
silently ignored by AG 33.1.1's built-in date filter — it kept rendering its default
input — so the delegated listener is the working path. It survives popup re-creation.

**Filter chip / codec read dateFrom/dateTo, not filter/filterTo.** Date models carry the
value in `dateFrom`/`dateTo` ("YYYY-MM-DD HH:mm:ss"); `filter-chips.js` had a `date`
branch added (reading `dateFrom`, `slice(0,10)` for day-only) — without it the chip
showed a bare operator + `undefined`. The URL codec strips the midnight time on encode
(`dayOnly`) and restores it on decode (`restoreTime`) so `#f=` stays compact
(`Dg2026-07-05`, not `Dg2026-07-05 00%3A00%3A00`).
Pinned live by `verify_ui.py` `date-filter` scenario + the codec battery. This is
the only non-numeric column with a bespoke filter — `Rok výroby` is a bounded number
and stays in the numeric `RangeFilter`/heat-threshold family (deliberately no date
picker, no slider on a removal date — a date has no good→bad colour axis).

### filter chips are clickable — and the AND/OR cap is 5, set in TWO places

A chip's **label is a `<button>`**: clicking it calls `gridApi.showColumnFilter(field)`
(`openColumnFilter` in `site/filter-chips.js`) — the same popup the header filter icon
opens, so a chip is an *edit* affordance, not just a remove one; the `[×]` still
removes the filter outright. Two non-obvious bits: a popup **can't anchor to a hidden
column's header**, so the chip un-hides the column first (`setColumnsVisible`) and
`ensureColumnVisible`s it; and the label deliberately carries **no `title`** (only an
`aria-label`) so hovering still shows the chip's own full "Header: summary" tooltip
rather than the innermost element's.

**One operator per column filter — the 2nd..Nth AND/OR radio pairs are dead and are
hidden by CSS.** AG joins *all* conditions of a column with a single operator, but it
renders a radio pair per join: only the first is live, the rest carry `.ag-disabled`
and mirror it (clicking one does nothing; clicking the first flips them all). With the
cap raised to 5 that's up to four dead controls, which reads as "A zároveň is broken".
`.ag-filter-condition-operator.ag-disabled { display: none }` (`site/style.css`) hides
them, leaving exactly one live pair that governs every condition. Mixed per-join
operators ("A AND B OR C") are **not** expressible in AG Community — don't try to build
it out of this UI. Pinned by the operator assertions in verify_ui `multi-condition`.
Related trap: AND on one column means *the same cell* satisfies both conditions
("Model obsahuje Golf **a** obsahuje Variant" = "Golf Variant" cars, 31 rows) — the
usual cross-column AND is what separate column filters already do.

Not user-reachable but real: the custom numeric `RangeFilter` **silently drops** a
combined AND/OR model (`setFilterModel({'Cena (Kč)': {operator:'AND', conditions:[…]}})`
→ model `{}`, no filtering). Its popup has no AND/OR radios, so only a hand-written URL
can get there.

The combined AND/OR condition cap is `MAX_FILTER_CONDITIONS = 5` (AG defaults to **2**;
there is no "unlimited" — the option takes a number). It must be repeated in
**`defaultColDef.filterParams` *and* `DATE_FILTER_PARAMS`** in both `site/app.js` and
`site/reference.js`: AG merges `defaultColDef` into a colDef **per property**, so a
colDef's own `filterParams` object *replaces* the default one wholesale (that's why
`DATE_FILTER_PARAMS` already repeated `buttons: ["reset"]`). Only the built-in
text/number/date filters honour it — the custom `RangeFilter`/`SetFilter` comps have no
conditions. Applying a 4-condition model at the default cap is **silently truncated to
2** by AG (that's the red state `verify_ui.py --scenario multi-condition` catches). The
URL codec needed no change: the `k` body joins conditions with `|`, unbounded.
Chip summary for an open range bound prints "od X" / "do Y" (never the raw `null` the
RangeFilter emits). Pinned by verify_ui `chip-click` + `multi-condition` (both pages,
both themes) and the `null`/`undefined` assertion in `filter-chips`.

### Archiv is a toggle backed by a grid external filter

The old one-shot "Načíst archiv" button is now an `.archive-toggle` switch.
`onArchiveToggle(true)` lazy-fetches `cars-archived.parquet` once (`loadArchive`)
then `archiveVisible` drives `isExternalFilterPresent`/`doesExternalFilterPass`
(hides `Stav=="Odstraněno"` when off). `totalRows` stays the live count;
`archivedLoaded` is tracked separately so `updateRowCount` shows the right universe.

### Nastavení barev is a right-side drawer — appearance ONLY (theme, palette, style)

`#settings-panel` is a `position:fixed` right drawer (`.settings-drawer`), not the
old push-down panel that displaced the grid; it closes on Escape **and on any click
outside it** (the opening click comes from `.menu-wrap`, which is excluded).

**It no longer holds per-column ranges.** Those were ~15 always-open rows that
duplicated the column filter — one `{min,max}` state rendered in two places — and they
moved into the numeric filter popup (see the distribution-track gotcha); the drawer
keeps only a hint pointing there plus a "Vymazat všechny rozsahy" button
(`resetThresholds`). What it holds now:

- **Motiv** — `#theme-choices`, two `.theme-card` buttons, each wrapping a
  `.theme-mini` **miniature of the page** (header + filter chip + grid rows with heat
  bars) painted in that theme's *own* tokens (`THEME_MINI`) rather than the live CSS
  vars, because two plain colour swatches would not show what actually changes.
  `window.setTheme("dark"|"light")` is the primitive (`toggleTheme` still works on top
  of it) and the gear menu's "Přepnout motiv" item is **gone** — the theme is the same
  kind of choice as the palette, not a tool. Pinned by `verify_ui.py` `theme-cards`.
- **Barevná škála** / **Styl vybarvení** — `#palette-choices` / `#style-choices`
  (`setHeatMode`, see the heat-map gotcha). Both previews are theme-tuned, so
  `applyTheme` re-renders them.

Everything applies live (no Uložit button). AG's built-in number/text filters are
Czech via `gridOptions.localeText` (the custom SetFilter was already Czech).
Floating-filter inputs are transparent with the fill on `.ag-input-wrapper` — filling
the input paints bands above/below the 24px box (the input spans the full 47px cell).
`verify_ui.py` takes `--theme dark|light` and has `color-drawer` / `theme-cards` /
`tools-menu` / `heat-combo` scenarios; screenshots are `<page>-<scenario>-<theme>.png`.
Note for anyone writing a drawer scenario: **clicking a choice re-renders that choice
row**, so the clicked node is detached by the time anything else looks at it — a
Playwright `Locator.click` retry then waits forever on a detached element, and
`color-drawer` has to re-open the drawer before screenshotting it.

## core — normalize

### normalisation order matters

`normalize_model()` (`core/normalize.py`) applies `BRAND_MAP` first, then `MODEL_CLEANUP_PATTERNS`. A pattern that expects a short brand name (e.g. `"VW"`) will fail if run before BRAND_MAP expansion replaces `"Volkswagen"`.

### Cee´d accent normalisation — three apostrophe spellings

Sauto returns "Kia Cee´d" with an acute accent (´, U+00B4); mobile.de writes
"cee'd" / "cee’d" (straight U+0027 / typographic U+2019 apostrophe). The reference
list uses "Kia Ceed" without any of them. `MODEL_CLEANUP_PATTERNS` folds all three
spellings (`Cee[´'’]d`, case-insensitive) — the apostrophe variants alone hid 859
mobile.de ICE listings from matching. Rows already sitting in state heal at build
time because `build_data` re-runs `normalize_model()` on ICE names before re-match.

---

## core — fields (ICE extraction)

### Extra field is cleaned after extraction

`clean_extra()` removes substrings already captured in dedicated columns (Typ motoru, Verze, Karoserie, engine volume, kW values) from the Extra text. Extraction must happen **before** cleaning. Adapters build an `extracted` dict first, then pass it to `clean_extra()`.

### DCT regex uses lookahead, not trailing \b

`extract_dct()` and `clean_extra()` use `\bKEYWORD(?![A-Za-z])` instead of `\bKEYWORD\b`. DSG often appears as "DSG7", "7DSG", or "DSG_ČR" where a digit/underscore prevents a trailing word boundary. The lookahead `(?![A-Za-z])` allows digits, underscores, and punctuation after the keyword.

### clean_extra uses case-insensitive regex for field stripping

`clean_extra()` uses `re.sub(re.escape(val), "", text, count=1, flags=re.IGNORECASE)` to strip extracted values from Extra. This handles cases like "T-GDi" in Extra when "T-GDI" was extracted to Typ motoru.

### clean_extra strips ALL trim keywords, not just extracted one

Cars can have two trim indicators (e.g. "Elegance" in model name + "R-Line" in extra text). `extract_trim()` returns only the first match (for the Verze column), but `clean_extra()` strips ALL `TRIM_KEYWORDS` from Extra to prevent duplicates leaking through.

### _TRANSMISSION_EXTRA_RE uses no trailing \b after Man

`\bMan\.` has no trailing `\b` because the period is not a word character — a trailing `\b` would only match if the next char is a word character, missing cases where "Man." appears at end-of-string or before whitespace.

### _SEAT_COUNT_RE allows space after dash

`\b[79]-?\s*[Mm][íi]st\b` handles both "7-Míst" and "7- Míst" (with space between dash and M). The space variant appears in some autodraft card texts.

---

## core — matching (ICE)

### auth side reads structured columns; scraped side still parses names

`ice_specs.csv` is column-structured, so `load_authoritative_list()` reads the
feature columns directly — the old auth-side name parsers (`_strip_known_parts`,
`_extract_auth_body/hybrid/fuel/engine_vol/engine_type`, `_AUTH_HYBRID_MAP`,
`_AUTH_FUEL_MAP`) were **deleted**. The **scraped** side is unchanged: listings
arrive messy, so `_parse_brand` / `_clean_model_for_matching` / `_extract_body_from_model`
still parse the listing's "Model auta". The display name (`Jednoznačná varianta vozu`)
is a clean, paren-free, **unique PK decoupled from the matching features** — editing
a name never changes how it matches (the columns do that). Trim (`Verze`) is scored
(+2/−1) so kept trim variants (Octavia Style vs Selection) don't tie into `Nejisté`.
The golden tests build `auth()` dicts directly, so they're insulated from the CSV format.

### SsangYong↔KGM brand alias

The reference list has some models under "SsangYong" and others under "KGM" (brand was renamed). Sauto returns listings under both names. `_BRAND_MATCH_ALIASES` maps each to the other so matching finds candidates regardless of which brand name the listing uses.

### unmatched cars get reformatted

Cars not matching any reference entry are reformatted as "Brand Model EngVol EngType" (e.g. "Opel Mokka 1.2 Turbo"). This is done by `_format_unmatched()` — the original verbose model name is replaced.

### model_base matching uses first-word heuristic

`_model_base_match()` compares the first word of scraped vs reference model base. This handles cases where scraped has extra suffixes ("Golf 8 Variant" → first word "Golf" matches reference "Golf"). Can produce false positives for single-letter model names but the scoring step disambiguates.

### class-named models must strip the leading class word ("Třídy X")

Mercedes A/B-class listings and reference rows are named by class letter: the
model base is "Třídy A" / "Třídy B" (Czech "Class A/B"). The first-word heuristic
above then keys on the *shared* generic word "Třídy", so every "Třídy B" listing
became a candidate of every "Třídy A" reference (and vice versa) — ~930 B-class
mobile.de listings were confidently mislabeled as A, and `diagnose_unpaired`
derived the mongrel "Mercedes-Benz Třídy A 1.9 PHEV" for a B 220 d car by voting
across the polluted (Mercedes, Třídy) cluster. Fix (`matching.py`
`_strip_class_prefix` / `_CLASS_PREFIX_RE`): strip a leading "Třídy"/"Třída"/
"Klasse" so the base is the bare class letter ("A" / "B"), consistent with the
reference's already-bare "C" / "E" / "GLA" models. Applied on **both** the
scraped side (`_clean_model_for_matching`) and the reference side
(`load_authoritative_list` `model_base`) so both reduce to the same token — bare
"A" ≠ bare "B", so the classes stop colliding while still matching within class.
After the fix the (Mercedes, Třídy) listings partition exactly by real class
(2206 A / 1270 B, zero cross-class leakage). The residual B-class Nejisté are the
thin single "Třídy B 180" reference entry (and the fabricated-PHEV problem), not
the collision. Pinned by `tests/test_matching.py::MercedesClassPrefixTest`.

### tri-state confidence: Ano / Nejisté / Ne (not binary)

`classify_match()` (pure, unit-tested in `tests/test_matching.py`) returns a `state` plus a numeric score; `match_to_authoritative()` writes both to `Spárováno` and the `Skóre shody` column:

- **Ano** — confident: best candidate scores ≥ `STRONG_FLOOR` (1) **and** beats the runner-up by ≥ `MARGIN_REQ` (1). "Model auta" set to the auth entry.
- **Nejisté** — a candidate was found but the match is weak (score < floor: 0 = no discriminating field, < 0 = the row's own fields contradict the entry) or ambiguous (tie between distinct variants like "1.2" vs "1.2 Turbo"). The best-guess entry is still written, but flagged — these are **not** reliably one specific model.
- **Ne** — no candidate at all; name reformatted via `_format_unmatched()`, `Skóre shody` left blank.

Before this change the matcher stamped `Ano` on the single highest-scoring candidate regardless of score (`max()` with no floor/margin guard), so ~25% of "matches" were coin-flips or contradictions hidden behind a 99.8% match rate. Thresholds are module constants in `core/matching.py`; after tuning, run `./bin/test.sh` — the data-integrity test asserts the distribution stays honest (no `Ano` row scores ≤ 0; uncertainty is surfaced). EV is not scored (prefix join), so EV `Spárováno` is only Ano/Ne and `Skóre shody` is blank.

### tie-resolvers run at classify_match level, NOT as `_score_match` tweaks (Levers B + A2)

Two Nejisté ties are broken by dedicated **resolvers inside `classify_match`**
(after the confidence check, only when NOT confident), never by adding points in
`_score_match`:
- **Lever B** `_collapse_trim_only` — a trim-only tie with a trimless base → the base.
- **Lever A2** `_resolve_body_tie` — a body-only tie (siblings differ by canonical
  body; the listing's `Karoserie` is blank so every sibling scores the body field
  one-sided and they tie) → the sibling whose canon body equals the body recovered
  from the listing text (`_body_from_text`, gated to **exactly one** token like the
  A1 trim recovery — ambiguous/absent → honest Nejisté). Recovered body rides a
  separate `scraped["body_raw"]` key and feeds **only** the resolver; it never
  touches the primary ±3 canon score, so the display-body invariant is untouched.

Why not the "+1 in `_score_match`" the task literally proposed: a global +1 boosts a
candidate whenever its canon body matches, which can boost a **runner-up** and shrink
a confident winner's margin → **demote a correct Ano** (or flip it). A classify_match
resolver is monotonic — it only runs on already-Nejisté rows, so it can only promote
Nejisté→Ano, never demote (pinned by
`SubBodyTieTest.test_recovered_body_does_not_demote_confident_ano`).

Non-obvious data fact behind A2: the reference has **no same-canon sub-body splits**
(no "Coupé" vs "Gran Coupé" both folding to Kupé as separate rows). Every body-tie is
a *different-canon* tie (Hatchback/Kombi/Sedan) where the listing simply didn't state
its body. So A2's yield is bounded by how many listings carry an *unambiguous* body
word in name+Extra: measured **203 of 1557** live-ICE body-ties flip (Nejisté→Ano,
0 demotions) on full state — Liftback/Gran Coupé/Sportback/VAN/Combi listings; the
other ~1350 are genuinely body-silent → **honest Nejisté** (do not chase them). The
strict exactly-one gate is why 203, not the ~580 a looser "any recoverable token"
probe suggests — the extra ~380 carry two body words and would risk a wrong-sibling
flip. Pinned by `tests/test_matching.py` `BodyFromTextTest` + `SubBodyTieTest`.

---

## core — merge_with_previous

### preserves removed listings

`merge_with_previous()` (`core/merge.py`) loads the previous CSV, keeps rows whose "Odkaz na auto" is no longer in the new scrape, sets their "Stav" to "Odstraněno". New data always wins (`keep="first"` dedup). CSVs grow over time — rows are never deleted, only marked.

### merge happens after authoritative matching

`pipeline.run_source()` calls `merge_with_previous()` AFTER `match_to_authoritative()`. The "Model auta" in removed rows retains the authoritative format from the last successful scrape. If the reference list changes, old removed rows won't get re-matched.

### skips empty-link rows

`merge_with_previous()` skips previous-CSV rows with an empty `Odkaz na auto`. Without this, rows that somehow lost their URL would accumulate as undedupeable copies on every run — this was the root cause of ~8k CSV growth per 4 days.

### merge is O(n²) — a local full scrape vs a large stale previous state hangs

`merge_with_previous()` loops every previous-state row and does
`df[df["Odkaz na auto"] == link]` (a full linear scan of the *new* frame) per
iteration. On CI this is cheap: the previous state is the same-day release, so the
removed set is tiny. But a **local** full mobile.de scrape merged against a
stale/mismatched bootstrap state (~148k previous × ~130k new) is ~19 billion string
compares — it ran **>60 min pegged at one core with no output** (2026-07-14) before
being killed, long after the network fetch (~20 min, clean) finished. Two takeaways:
- To refresh one source's state locally, **move its previous `<slug>.parquet` aside
  first** (`mv … tmp/`) so merge takes the `prev is None` fast path and writes the
  fresh rows directly — you lose the removed/archive rows (fine for a local
  analysis/reference-growth build; canonical state is the release).
- The real fix (not yet done) is to index the new frame by link once
  (`groupby`/`dict`) instead of re-scanning per previous row — O(n) not O(n²).
- Run `python -u -m scrapers.run` (unbuffered) for local scrapes; stdout is
  block-buffered to a file otherwise, so "Hotovo"/errors don't appear until exit.

### mobile.de is NOT Akamai-blocked from a residential IP

The Akamai gotcha above is about **datacenter** IPs (CI/Azure runners). Probed
2026-07-14 from a residential WSL box: a full scrape (129 986 ICE + 17 638 EV,
thousands of `/api/s/` requests at `CONCURRENCY=3`) returned **zero 403s**. So to
refresh state with the current adapter (e.g. to heal the fabricated-hybrid labels
after the 2026-07-13 fix — which only heal on a real scrape), **scrape locally**;
don't wait on CI, which is the environment that gets blocked. This is also the
fastest way to make a reference-growth batch avoid wasted `exists=false` research
calls: on healed state the worst-matched clusters are genuine missing variants, not
fabricated PHEV/HEV (batch 2026-07-14: 58/76 applied = 76 %, vs the stale-state
batch's 17/39 = 44 %; ne-Ano 22 420 → 16 244, and the corrected bodies match cleanly
so gains materialize instead of being suppressed by stale "Sedan" penalties).

### Odkaz clobber on rows present in both scrapes — FIXED (#11)

Previously `merge_with_previous()` did `df.set_index("Odkaz na auto").loc[link]`, which dropped the index column and left the merged row with `Odkaz na auto` = NaN; those empty-link rows were then skipped on the next run, causing churn. Fixed in `core/merge.py` by selecting with a boolean mask (`df[df["Odkaz na auto"] == link].iloc[0]`), which keeps the link column.

**Still recommended:** run parity / regression checks on FRESH scrapes (delete `scrapers/data/scrapes/*.csv` first). Not because of the (now-fixed) link bug, but because merge carries forward each removed row's last authoritative "Model auta" — a changed reference list won't re-match already-removed rows.

### listing lifecycle dates (Přidáno / Upraveno) are merge-stamped, not git-derived

Unlike the reference CSVs (git-tracked → `build/backfill_ref_dates.py`), scraped
listings are not in git, so `merge_with_previous()` stamps their lifecycle dates
from the new-vs-previous comparison:

- **genuinely new link** → `Přidáno = Upraveno = today` (also the `prev is None`
  path: a brand-new source's first scrape stamps every row today).
- **link in both scrapes** → carry `Přidáno` forward; bump `Upraveno` to today
  only when **seller content** changed (`_seller_content_changed`).
- **removed link** → carry both unchanged (removal is `Odstraněno dne`, not an edit).
- **existing state that predates the feature** (columns absent) → blank, filling
  forward (there is no honest date to backfill ~150k rows).

"Seller content" = a sha1 over `CANONICAL_COLS` minus `_DATE_HASH_EXCLUDE`
(`Přidáno`/`Upraveno`/`Odstraněno dne`/`Stav`/`Spárováno`/`Skóre shody`/`Model auta`/
`Odkaz na auto`/`Cena (Kč)`). The match-verdict trio (`Spárováno`/`Skóre shody`/
`Model auta`) is excluded on purpose: a **reference-list edit re-matches rows and
rewrites those columns but must not bump `Upraveno`**. Price is compared separately
with a **1% relative tolerance** (`_PRICE_REL_TOL`) because mobile.de's Kč is
EUR×CNB-daily-fixing and drifts sub-percent day to day — a real price move still
bumps, FX jitter doesn't. `build_data.main()` guard-creates the two columns blank
on a seed-only build (merge not run) so the payload schema is stable. Shown as
`agDateColumnFilter` grid columns like `Odstraněno dne`. Pinned by
`tests/test_merge.py::LifecycleDateTest` and
`tests/test_data_integrity.py::ListingDateColumnsTest`.

---

## build — reference enrichment

### EV battery + edition are extracted from the free-text Extra column

`build_data.extract_ev_extra_specs(df)` (EV rows only) parses the `Extra` string
into two dedicated columns, using pure parsers in `core/fields.py`
(`parse_battery_kwh`, `parse_ev_edition`):

- **`Kapacita baterie (kWh)`**: the per-listing `Baterie NN kWh` (mobile.de +
  sauto) **overwrites** the reference-join nominal (one value per nameplate,
  wrong for multi-battery variants like Dolphin Surf 30/43 kWh); reference is the
  fallback when Extra has no plausible value (guard 20–120 kWh). This is the one
  build-time column where the listing beats the reference.
- **`Verze`**: an edition token matched against the curated
  `EV_EDITION_KEYWORDS` allow-list (Essence/Selection/Active/Boost/Comfort/
  Pro/Pro Performance/…). Display-only — it does **not** drive matching (EV is a
  prefix-join, ICE `Verze` stays reference-trim-driven). Free text / feature
  abbreviations (LED, ACC, SHZ, …) yield blank; ~57% of EV rows are blank, which
  is honest. **Never** free-text-guess an edition — grow the allow-list instead.

**Ordering is load-bearing**: `extract_ev_extra_specs()` MUST run *after*
`apply_verze_display()` (which does `df["Verze"]=""` then fills ICE-Ano — it
would wipe EV editions) and after `join_electric_reference()` (which sets the
nominal battery). See `main()`. Blank `Verze` serialises as parquet NULL (NaN on
read) — same as ICE `Verze` has always done; not a bug. This is the foundation
for future reference version-splitting (the listing name almost never carries the
variant token, so name prefix-join can't assign versions — the Extra can).

### Karoserie (and ICE engine specs) are reference-driven, then vocab-folded, then vote-filled

Family bug: sauto's per-listing `vehicle_body_cb` is seller-tagged and noisy, so
one model scatters across bodies (Škoda Enyaq iV 80: 17 `SUV`, one `Hatchback`,
one `Terénní`) — breaking the body-type filter. The fix is a **hybrid** built in
this order in `main()` (each later step is the fallback for what the earlier
can't reach):

1. **`apply_reference_body_specs(df)`** (reference-driven, the trustworthy source).
   For ICE, overwrites `Karoserie` from the matched auth entry's **`body_raw`**
   (the *unfolded* reference body — `matching.load_authoritative_list` also carries
   the scoring-folded `body`; don't use that for display) for every `Spalovací`
   row whose "Model auta" is an entry seen as a confident **Ano** match — this
   covers Ano rows **and** their Nejisté siblings (matching writes the same entry
   string for both), so the body is uniform inside one variant. Only overwrites
   when the ref body is non-blank (6 ICE ref rows have none). It **also**
   overwrites `Objem motoru` / `Typ motoru` / `Hybrid typ` on **Ano only** (these
   disambiguate variants; per-listing extraction is noisy — a car matched to
   "Formentor 1.5 TSI" can carry 2.0). This is the same reference-as-truth
   principle as `apply_verze_display`, and makes the grid consistent with the
   reference page.
2. **`canonicalize_body_vocab(df)`** folds the whole column onto the canonical
   display set (`_DISPLAY_BODY_CANON`): SUV←CUV/Terénní/VAN(no)/…, Kombi←Combi/
   Variant/SW/…, Sedan←Sedan/limuzína, MPV←VAN, Kupé←Coupé/Kabriolet. **The
   liftback family (Liftback/Sportback/Fastback) folds into Hatchback** — forced
   by data, not taste: `ice_specs.csv` labels that 5-door body class
   *inconsistently* (Octavia non-Combi appears as both "Hatchback" and "Liftback"
   across entries), so the only way to guarantee "same car → one body" without a
   full manual ref re-audit is to collapse them. This is deliberately **not**
   `matching._canonicalize_body` (that scoring fold also collapses Liftback→
   Hatchback but lacks CUV/VAN/Terénní/Kupé).
3. **`canonicalize_body(df)`** (majority vote) — the fallback for what reference
   can't set (EV/ICE-Ne, Nejisté-only groups): groups on exact "Model auta",
   overrides minority outliers when one value is a **strict majority**
   (`count*2 > n`); no-majority groups untouched. Runs on already-folded values,
   so synonym splits (Kombi/Combi) can't defeat the vote.
4. **`backfill_body_fuel`→`derive_body`** fills any still-blank body from the
   model name.

EV body: `ev_specs.csv` now has a hand-populated **`Karoserie`** column (89 rows;
an EV nameplate has one body). `join_electric_reference` carries it and
**overwrites** (reference wins, unlike the fillna-only spec cols) on prefix
match. `site/app.js` `bodyGroups` folds Liftback/Sportback into Hatchback to
match. Invariants pinned in `tests/test_data_integrity.py::BodyTypeConsistencyTest`.

**`test_body_coverage_not_regressed` excludes the "Andere" junk bucket.** The
coverage assertion counts blank `Karoserie` only over rows whose `Model != "Andere"`.
The mobile.de "Andere" catch-all (Peugeot/Kia/Dacia/Hyundai Andere, ~152 rows on
real state) has no derivable passenger body and grows unbounded with the DE-ICE feed,
so a fixed blank ceiling that counted it just tracked how much junk mobile.de
returned — it went red on prod state (157 > 50) with nothing actually wrong. Excluding
Andere, the remaining blanks are a handful of commercial vans with no reference body
(Iveco Andere, Nissan Interstar, Peugeot Boxer, and EV vans Maxus eDeliver 9 / Fiat
Scudo / Merc eSprinter) — 5 on real state, ceiling 20. Still catches a real
derive/fold/vote regression: a genuine model going blank isn't "Andere", so it's
counted. **This test only exercises meaningfully on real full state** (`bin/bootstrap-data.sh`);
a seed-only build lacks the DE-ICE rows.

### diagnose_unpaired candidate is anchored to the diagnosed listing

`derive_candidate` majority-votes over the whole (brand, model_base) cluster —
but a family cluster like (VW, Touran) mixes variants (1.5 TSI + 2.0 TDI), and
an unanchored vote once derived "VW Touran TDI PHEV": engine volume blanked
(no 0.6 consensus across variants) and `Hybrid typ` stamped PHEV by a
*minority* of fabricated-hybrid mislabels, because `_mode_with_consensus`
ignores blanks. Two fixes: `cmd_candidate` passes the diagnosed listing as
`anchor` (vote runs only over engine-compatible rows; engine fields fall back
to the anchor), and `Hybrid typ` uses `_mode_incl_blanks` (a blank is a real
"not a hybrid" vote). Pinned in `tests/test_diagnose_unpaired.py`.

### candidate `simulace` overstates gains when the voted body is wrong

`simulate_candidate` scores the cluster against the candidate row *as derived* —
including the majority-voted `Karoserie`. That vote runs over the listings' own
noisy bodies (mobile.de pre-Limousine-fix state rows still carry a wrong
"Sedan/limuzína"; SmallCar-tagged crossovers carry "Hatchback"), so a candidate
inherits the *wrong* body, matches it (+3), and simulates hundreds of Ano
conversions. Correcting the body before `apply` (Kona/Duster/Focus… are SUVs and
hatchbacks, not sedans — the researcher notes flagged this) turns those +3s into
−2 mismatches and the real-state gain collapses (batch 2026-07-13: simulated
~+1300 Ano, actual +94). Keep the reference truthful anyway: body one-sided
(listing blank) scores 0, so the gains materialize as mobile.de state heals
(`Limousine → ""` on each scrape refreshes live rows). Removed rows keep stale
bodies forever, and SmallCar→Hatchback mislabels don't heal — those clusters stay
Nejisté until the per-listing body noise is addressed. Corollary: also fix the
researcher-flagged hybrid fabrications before apply ("Arteon 1.4 TSI HEV" is
really the eHybrid PHEV; "Kona 1.6 GDI" ships only as HEV) — `exists:true` with a
contradicting `variant_note` still needs a human read.

### a body-agnostic reference PK silently rewrites the WRONG body onto listings

Reported live 2026-07-27: Škoda Octavia **liftbacks** were displayed as `Kombi`
(e.g. sauto listing 209900301 — a 2.0 TDI liftback, `Karoserie` = Liftback and
`Verze` = Top Selection in state, shown as Kombi in the grid). Not a display bug
— a **reference gap** amplified by reference-driven body:

1. `ice_specs.csv` had exactly one 2.0 TDI Octavia row, `Škoda Octavia 2.0 TDI`
   — PK carried **no body token** but `Karoserie` = Kombi. Same for `2.0 TSI`.
   (The 1.5 TSI family was already split Liftback/Combi; the 2.0 rows, added
   later by the ref-growth loop, were not.)
2. A liftback listing scores that row `+2 vol +2 type +1 fuel −2 body = 3`, and
   every genuinely-liftback reference row is a **1.5 TSI** (engine mismatch
   scores far worse) — so the Kombi row wins by a wide margin → **Ano**. Body
   contradiction alone never blocks confidence; it is just −2.
3. `apply_reference_body_specs` then overwrites `Karoserie` from the matched
   entry for the whole entry group. The listing's *correct* Liftback is replaced
   by the reference's Kombi. Reference-as-truth is right when the listing is
   noisy (a Karoq tagged "Kombi") and wrong when the reference is the one
   missing the variant — the mechanism cannot tell the two apart.

Fix is data, not code: split the row per body and **put the body token in the
PK** (`Škoda Octavia Liftback 2.0 TDI` + `Škoda Octavia Combi 2.0 TDI`). The PK
token is load-bearing twice — matching ignores it (it reads the structured
columns), but the *payload* splits Model out of the PK, so without it both rows
collapse to one `(Značka, Model, Verze, Objem, Typ motoru)` key and
`test_matched_ice_entry_has_single_body` breaks. Measured on full state: **190
Octavia rows Kombi → Hatchback**, and the reported listing's score 3 → 8. Zero
non-Octavia rows changed state.

**The fix costs Ano and that is correct.** 201 Octavia rows went Ano → Nejisté
(134 body-blank + 67 stale mobile.de `Sedan/limuzína`): with two same-engine
siblings differing only by body, a listing that never states its body genuinely
ties, and Lever A2 only rescues the ones whose text names exactly one body.
A coin-flip Kombi is worse than an honest Nejisté — do not "fix" this by
re-merging the rows.

Guards: `tests/test_matching.py::BodyAgnosticPKTest` (Octavia 2.0 offers both
bodies) + `OctaviaBodySplitTest` (golden pick/tie behaviour), and
`tests/test_build_data.py::ReferencePayloadKeyTest` (no reference payload key
spans two canonical bodies — catches a naive same-PK split before a build).

**This is a family, not a one-off.** On full state **2 651 confidently-matched
ICE rows across 351 entry groups** display a body contradicting the listing's
own `Karoserie`. They split three ways and only the first is a bug of this kind:
a genuine reference gap (`VW Golf Hatchback 2.0 TDI` vs Kombi listings 140,
`Audi A6 2.0 TDI` Sedan vs Kombi/Avant 60, `Škoda Superb Combi Style 2.0 TDI`
vs liftbacks 64, `VW Arteon Liftback 2.0 TSI` 201); a reference data error
(`Renault Clio 1.3 TCe` labelled Sedan, `Mazda CX-30 2.5` Sedan); and plain
listing noise where the reference is right and the overwrite is doing its job
(`Škoda Karoq 1.5 TSI` tagged Kombi by 91 sellers). Only the first two want
fixing — a blanket "listing body wins" or "body mismatch blocks Ano" rule would
break the third, which is the majority.

### a reference-growth batch can be NET NEGATIVE — audit per-row before merging

Applying researched candidate rows can *worsen* matching even when every row is a
real car that passed the `exists` guard: a new row that shares (brand, model_base)
with an existing entry and scores equal for some listings creates a **tie**, demoting
previously-confident Ano rows to Nejisté (`classify_match` margin rule). Batch 4
(2026-07-15) applied 64 researched rows and moved ne-Ano 16 244 → **16 450** (+206
worse) before auditing. Two mechanisms:

- **near-dup siblings vs existing entries** — "Mercedes-Benz C 2.0" alone demoted
  888 listings (ties against the existing C-class entries); "Škoda Octavia 1.5 TSI"
  −206 (ties vs "Škoda Octavia Combi Style 1.5 TSI" family), etc.
- **near-dup siblings within the batch** — spelling variants of one variant
  ("KGM Tivoli 1.5 T-GDI" / "1.5 TGDI" / "1.5 Turbo") tie *each other* for
  type-blank listings, so isolated gains (+154) collapse jointly.

Isolated per-row effect ≠ joint effect. The working recipe (see batch 4): after
serial apply, diff-classify the full state against ref-without-batch vs ref-with-batch
(one state load, both auth lists), compute each row's isolated net on its
(brand, model_base) subset, drop isolated-negative rows + within-batch spelling dups,
then re-verify jointly. Batch 4: 64 → 47 rows, ne-Ano 16 244 → 14 225 (−2019).
Corollary of the payload single-body invariant (`test_matched_ice_entry_has_single_body`):
a new row whose (Značka, Model, Verze, Objem, Typ motoru) payload key collides with an
existing entry of a *different* body must carry the body token in its PK
("Audi A6 **Avant** 2.0", "Seat Leon **Hatchback** 2.0") — the payload splits Model
from the PK string, so that's what keeps the keys distinct.

### ai-match-one research runs the nested `claude -p` from a temp dir

The research step's `claude -p` used to run inside the repo → the nested
session loaded this project's CLAUDE.md + the user's session hooks and once
spent its final message commenting on `git status` instead of returning the
JSON. And the old `claude | python` pipeline sat in front of `tail`, so the
parse failure exited 0 and looked like success. `cmd_research` now `cd`s to a
`mktemp -d` (no repo context), hardens the prompt ("FINAL message must be
nothing but the JSON"), retries once on unparsable output and fails loud with
the raw-response path.

### grow-reference reads the payload — which no longer carries "Model auta"

`reference_gap.load_unpaired()` clusters unpaired listings from
`site/data/cars.parquet`, but `write_payload()` splits "Model auta" into
Značka + Model and **drops the original column** (task #3). Before the fix the
gaps command silently reported *0 clusters against 2177 unpaired EVs* — the count
comes from `Spárováno` while the cluster keys all folded to "". `load_unpaired`
now reconstructs "Model auta" from Značka+Model (faithful for EV; ICE payload
strips engine tokens, but gaps is EV-only). Any new payload-side column surgery
can break this tooling again — it's pinned by
`test_load_unpaired_reconstructs_model_from_brand_model_split`.

### EV body type vs ICE

EV body type comes from `vehicle_body_cb` (sauto) or `extract_body_type()` (autodraft/energycars). ICE uses the same primary/fallback pattern. EV rows are enriched in `build_data.py` via a prefix join against `ev_specs.csv`; ICE rows via an exact join + re-match against `ice_specs.csv`.

### reference page spec columns: auth-string vs listing-mode

`build_reference_json()` adds 6 per-config spec columns (Palivo, Karoserie, Výkon, Objem motoru, Typ motoru, Hybrid typ) to `reference.json`. Sources differ on purpose:

- **Objem motoru / Typ motoru / Hybrid typ / Karoserie (ICE)** — read straight from the reference's **dedicated columns** via `matching.load_authoritative_list()` (the CSV is now column-structured; these are no longer regex-parsed out of the name). NOT taken from listings: per-listing extraction is noisy — e.g. a listing matched to "Cupra Formentor 1.5 TSI" can carry `Objem motoru` = 2.0. The reference columns are the single source of truth.
- **Karoserie / Výkon (kW)** — not encoded in the reference string, so aggregated from matched listings by **mode** (`_mode_nonempty`, most-common value). Blank when a reference model has no listings. ICE keys on exact "Model auta" == auth entry; EV buckets by longest-prefix (same as `join_electric_reference`).
- **Palivo** — ICE: listing mode → fallback `derive_fuel()` (deterministic, 100% coverage). EV: constant "Elektro".
- **EV** engine columns (Objem motoru / Typ motoru / Hybrid typ) are always blank (N/A).

### paired-cars count + price aggregates (Nabídek / Cena na trhu)

`build_reference_json()` also attaches, per reference row, how many listings pair
with it and their price distribution (`build_ice_price_aggs` / `build_ev_price_aggs`
→ `_price_aggregate`). Fields: `Nabídek` (int count), `Cena min/p25/medián/p75/max`
(Kč), `Cena histogram` (14 ints), `Odkaz nejlevnější/nejdražší` (listing URLs).

- **Bucketing mirrors the spec aggregators**: ICE groups on exact `Model auta` == auth
  entry (so **Ano + Nejisté** listings both count — matching writes the entry string to
  both), EV by longest-prefix. Unmatched (`Ne`) names are `_format_unmatched` strings
  that don't equal an entry, so they don't leak in.
- **The histogram axis is SHARED with the JS renderer** — `PRICE_HIST_MIN/MAX/BINS`
  (100 000 / 800 000 / 14) in `build_data.py` == `PRICE_AXIS_MIN/MAX` +
  `PRICE_HIST_BINS` in `site/reference.js`. Prices are **clipped** into the axis, so
  `sum(histogram) == Nabídek` always (pinned by `ReferencePriceAggregatesTest`). Change
  the axis in **both** places or the bars misalign / the sum invariant breaks.
- **Why 100–800k, not the true max (~3.36M)?** 99.96 % of listings are ≤ 750k (the CZ
  hard filter); only ~63 exceed it (autodraft/energycars dealer exotics, no price
  filter). A data-driven axis to 3.36M would crush every normal car into the left 22 %.
  So the axis is fixed at a robust bound and outliers **clip** to the edge with a `›`
  overflow cap (`overflowMark`, shown when `Cena max > PRICE_AXIS_MAX`) — the true value
  still prints in the row label + popup stat tiles, so the clamp is never a silent lie.
- Unpaired reference rows get `Nabídek = 0`, `None` stats, `[]` histogram, `""` links
  (`_blank_price_fields`) — the cell renders "—".
- Each row also carries **`Značka` + `Model`** (payload split: `split_brand_model` +
  ICE engine strip) so `reference.js` can build an index-page filter matching the index
  grid's own columns — see the three-view gotcha below.

### reference "Cena na trhu" is a three-view cell with a uniform per-view row height

`site/reference.js` renders the price column three ways, switched by the header
segmented toggle (`setPriceView`, persisted to `localStorage["refPriceView"]`,
default `compact`): **compact** (od–medián–do text + sparkline), **boxplot**
(min/quartile/median/max box on the shared axis), **histogram** (inline 14-bin
distribution). Non-obvious bits:

- **One `rowHeight` per view** (`PRICE_ROW_HEIGHTS` = 25/44/58) set via
  `setGridOption("rowHeight", …)` + `resetRowHeights()` — a single value, so **every
  grid row is equal-height** in each mode (the requirement). Histogram is the tallest,
  so it's opt-in, not the default.
- **`Nabídek` + `Cena medián` are NOT in `NUMERIC_COLS`** (price is not a good→bad heat
  axis) — they're in `RANGE_EXTRA`, which only earns them a `colRanges` entry so their
  column-filter `RangeFilter` works (filter by count / median price). They render via
  custom `cellRenderer`s, not the heat `cellStyle`. The `Cena na trhu` column's `field`
  is `Cena medián` so sort/filter act on the median.
- **Two different click targets**: the **count** cell (`Nabídek`) opens the paired
  listings in the **index table** (`openIndexForRef` → `index.html#f=…` in a new tab);
  the **price** cell (`Cena medián`) opens `openPricePopup` (a `position:fixed`
  `#price-popup` card: stat tiles + bigger histogram with a median line + Y-axis + a
  close ×). The popup's header count and a "Zobrazit v tabulce" row link to the **same**
  index-filtered URL; cheapest/dearest still deep-link to the scraped listing.
- **Index-filter URL** (`indexFilterModel`/`indexUrlForRef`): encodes a filter model
  with the shared `url-state` codec (`window.UrlState.encFilters`) over the index grid's
  columns — `Značka` (set) + `Model` (ICE: `equals`, EV: `contains`) + ICE `Objem motoru`
  + `Typ motoru`. **Not variant-exact** for ICE bodies that share an engine (index has no
  "Model auta" column to key on), but reproduces the pairing closely (Octavia 2.0 TDI ref
  → 3169 paired ≈ 3070 index rows). Exposed for verify_ui via `window.__indexUrlForRef`.
- The popup builds `innerHTML` from a model name + scraped URLs, so it escapes text
  (`escHtml`) and allows only `http(s)` hrefs (`safeHref`) — defensive XSS guard. The
  index URL is codec output (percent-encoded), safe in an `href`.
- **`Cena medián` filter slider steps by 1000** (`STEP_VALUES` override in
  `computeRanges`) — a 1-Kč step on a ~750k range is meaningless. `Nabídek` steps by 1.
- Bar/box fills use dedicated theme vars (`--rc-track/-fill/-edge/-bar/-bar-top`) in
  `style.css`, tuned for both themes. Pinned by verify_ui `price-compact` /
  `price-boxplot` / `price-histogram` / `price-popup` (both `--theme`).

### PHEV consumption blanked

Plug-in hybrids' combined consumption is the official WLTP **weighted** figure
(~1 l/100 km — assumes a fully charged battery), which is misleading as a real-world
number. `load_combustion_reference()` blanks `Spotřeba (l/100 km)` for every
`Hybrid typ == PHEV` row; because both the cars.json join and `build_reference_json`
read that loaded frame, the blank propagates to both pages. The column tooltip on
both pages explains why. The source `ice_specs.csv` keeps the WLTP value (blanking
is build-time only). `tests/test_data_integrity.py::test_phev_consumption_blank` pins it.

### Cd column is real-or-estimated, flagged by "Cd zdroj"

Both reference files carry `Cd` (drag coefficient, replaces the old "Aerodynamická
modifikace (lepší/horší)") plus a `Cd zdroj` flag: **`reálné`** = a real published
value (manufacturer press / Wikipedia / ev-database), **`odhad`** = a body-shape
estimate (`BODY_CD` map: SUV~0.33, sedan~0.27, hatch~0.30, …) used where no reliable
Cd was findable. ~42% of rows are estimates — paywalled/blocked spec databases
(automobile-catalog 402, cars-data JS-only) make real per-variant Cd sparse. `Cd
zdroj` shows on the reference page so estimates are never mistaken for measured data.
`Cd` is numeric (lower = better); `Cd zdroj` is **not** carried into the main
`cars.json` grid (reference page only).

### "Servis (Kč/rok)" is a calibrated ESTIMATE, computed at build (not in the CSVs)

Task #23. `service_cost()` / `add_service_cost_column()` (`build/build_data.py`)
derive an estimated **average annual workshop cost over 5 years** (scheduled
servicing + wear repairs; excludes tyres/fuel/insurance/depreciation) for **every**
EV + ICE row from that row's own columns — `base(12000) × fuel × brand-tier ×
segment × engine`. Same payload-derived-display-column treatment as
`Spolehlivost` (not in `CANONICAL_COLS`; added inside `write_payload` after
`add_reliability_column`; in `PAYLOAD_NUMERIC_COLS` → float64). `build_reference_json`
computes the same per reference row. No free per-model CZ source exists, so this
is a **model, never a measured value** — the "odhad" is stated in the header
tooltip + the "Servisní náklady (odhad)" overview card, **not** a per-row `zdroj`
column (which would be a constant). Constants were **calibrated (2026-07-22)**
against real published figures for 20 models (ADAC Werkstattkosten → CZ + Czech
garage data + BOVAG-RAI fuel ratios) — best fit MAPE ≈ 21 %, near-zero bias (see
the "Calibration" section in the spec). Key learning: the real premium-over-
mainstream gap is only ~1.25× (a BMW X3 ≈ a VW Golf), far below intuition; EVs are
~0.35× ICE. Residual per-model scatter is irreducible (ADAC data is ~2× noisy
within a class) — don't chase it; it stays an estimate.

Two non-obvious bits:
- **The `[3000, 60000]` clamp is mathematically inert.** The multiplier product is
  bounded to ≈`[0.32, 2.33]` under the CZ price filters (no exotica at ≤750k Kč),
  so raw ∈ ≈`[3800, 28000]` — the clamp never fires on current data (`clampedListings`
  / `clampedRefs` = 0). It's a **drift / data-quality detector**: `service_cost`
  returns a `clamped` flag, reference rows carry `"Servis mimo rozsah"`, and the
  counts feed the overview + a reference-page ⚠ badge (`servisRenderer`). Never a
  silent clip — mirrors the price-histogram `›` overflow mark.
- **`main()` builds reference.json BEFORE the metadata** (reordered) so the
  per-ref-row clamp flags can feed `metadata.serviceCost.clampedRefs`. `test_meta_sidecar_keys`
  pins the `serviceCost` block; formula truth table in
  `tests/test_build_data.py::ServiceCostTest`.

### reference date columns (Přidáno / Upraveno) are git-derived + writer-stamped

Both reference CSVs carry two trailing ISO `yyyy-mm-dd` columns, shown as the last
two (date-filtered) columns of the reference grid: **`Přidáno`** = when a row (by PK:
`Jednoznačná varianta vozu` for ICE, `Model auta` for EV) first appeared in git
history; **`Upraveno`** = when its content last changed. Two moving parts:

- **`build/backfill_ref_dates.py`** seeds/reconciles both columns from git history.
  It walks `git log --follow` (crosses the electric/combustion → unified rename; PK
  is stable back to `0e39b01`) and hashes each row's content at every commit. Two
  non-obvious bits: (1) **`--follow` is incompatible with `--reverse`** — git
  collapses the log to a *single* commit, so it reads newest→oldest and reverses in
  Python; (2) the content hash **excludes the two date columns**, so re-running is
  **idempotent** (a row's own Upraveno never bumps itself, and a pre-migration blob
  without the cols hashes identically). The working tree is folded in as a final
  "today" snapshot, so uncommitted new/changed rows reconcile to today. It rewrites
  via `csv` (QUOTE_MINIMAL) and is verified to touch **only** the two new columns —
  the existing cells stay byte-identical (no pandas float/NaN reformatting). Run
  `python build/backfill_ref_dates.py` (or `--check` to fail if a run would change
  anything) after committing manual CSV edits so the git-derived dates catch up.
- **Write paths stamp today.** `diagnose_unpaired.py` `apply` and
  `reference_gap.append_rows` both set `Přidáno = Upraveno = date.today()` on the
  rows they add (append_rows only when the header carries the cols and the value is
  blank — never hand-fill them). These are the committed write paths the
  `grow-reference` / `ai-match-one.sh` loops drive, so they're covered transitively.
- **Caveat:** the 2026-07-11 spec-normalization commit rewrote nearly every row, so
  most `Upraveno` collapse to that date — truthful (the rows *were* restructured
  then), and edits since stand out with later dates. `Přidáno` stays well spread
  (2026-05-24 → today).
- `build_reference_json` copies both into `reference.json`; they are **not** carried
  into the main `cars.json` grid (reference page only). Pinned by
  `tests/test_backfill_ref_dates.py`, `test_diagnose_unpaired.ApplyStampsDatesTest`,
  `test_reference_gap` (append stamping), and
  `test_data_integrity.ReferenceDateColumnsTest` (valid ISO + Přidáno ≤ Upraveno).
