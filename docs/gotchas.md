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
`Hybrid typ` from `extract_hybrid_type(subTitle)`, defaulting to HEV.

### German display strings everywhere

`attr` values are German-formatted display strings, not numbers: `ml` "29.000 km",
`pw` "110 kW (150 PS)", `cc` "1.499 cm³", `bc` "27 kWh", `fr` "02/2022" —
`_parse_number()` takes the first integer and strips dot thousands-separators.
Make names lose their diacritics ("Skoda", "Citroen") — BRAND_MAP restores them,
otherwise ICE matching finds no brand candidates. Category `attr.c` uses mobile.de's
own body taxonomy (OffRoad→SUV, EstateCar→Kombi, Limousine→Sedan/limuzína, …) — note
German "Limousine" lumps sedans with some hatchbacks.

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

### "Andere" is mobile.de's junk model bucket (like sauto's "Ostatní")

mobile.de returns `Andere` (German "Other") as the model for cars its taxonomy
doesn't index — the scraped name becomes e.g. "JAC Andere", "ORA Andere", even
"Andere Andere" (~117 EV listings across ~20 clusters, 2026-07). These are NOT
missing reference models: never add an "X Andere" reference row (it would
prefix-match every future unindexed car of that brand regardless of what it is).
The real fix is adapter-side recovery from other attrs, mirroring sauto's
`_recover_ostatni_model()` — TODO, not yet implemented for mobile.de.

### German "Hybrid" listings fabricate PHEV/HEV variants that never existed

mobile.de delivers mild hybrids under the same `ft="Hybrid (Benzin/Elektro)"`
umbrella as full/plug-in hybrids, and `_build_row` → `extract_hybrid_type(subTitle)`
then stamps `Hybrid typ` HEV (default) or PHEV (on plug-in-ish tokens) — so the
state contains hundreds of e.g. "BMW 118 PHEV" rows although no 1-series PHEV was
ever built (BMW's PHEV line starts at 225xe/230e). Consequence for reference
growth: data-generated ICE rows with `Hybrid typ` set were web-checked, and rows
whose hybrid variant does not exist (23 of the first 47 researched) were dropped —
simulation showed dropping them *raises* confident matches (+989 Ano) because the
mislabeled listings still pair with the non-hybrid row (one-sided hybrid penalty
is only −1) while a fake PHEV sibling row ties everything into Nejisté. Genuine
PHEVs (330e, DS7 E-Tense, …) keep their own rows. Adapter-level MHEV detection is
the proper upstream fix — TODO.

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
column-in-localStorage-not-URL + legacy migration.

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
(text/number/set/combined), so a fallback would catch nothing; an unknown future
filter type should fail loud, not emit opaque base64.

---

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

### tri-state confidence: Ano / Nejisté / Ne (not binary)

`classify_match()` (pure, unit-tested in `tests/test_matching.py`) returns a `state` plus a numeric score; `match_to_authoritative()` writes both to `Spárováno` and the `Skóre shody` column:

- **Ano** — confident: best candidate scores ≥ `STRONG_FLOOR` (1) **and** beats the runner-up by ≥ `MARGIN_REQ` (1). "Model auta" set to the auth entry.
- **Nejisté** — a candidate was found but the match is weak (score < floor: 0 = no discriminating field, < 0 = the row's own fields contradict the entry) or ambiguous (tie between distinct variants like "1.2" vs "1.2 Turbo"). The best-guess entry is still written, but flagged — these are **not** reliably one specific model.
- **Ne** — no candidate at all; name reformatted via `_format_unmatched()`, `Skóre shody` left blank.

Before this change the matcher stamped `Ano` on the single highest-scoring candidate regardless of score (`max()` with no floor/margin guard), so ~25% of "matches" were coin-flips or contradictions hidden behind a 99.8% match rate. Thresholds are module constants in `core/matching.py`; after tuning, run `./bin/test.sh` — the data-integrity test asserts the distribution stays honest (no `Ano` row scores ≤ 0; uncertainty is surfaced). EV is not scored (prefix join), so EV `Spárováno` is only Ano/Ne and `Skóre shody` is blank.

---

## core — merge_with_previous

### preserves removed listings

`merge_with_previous()` (`core/merge.py`) loads the previous CSV, keeps rows whose "Odkaz na auto" is no longer in the new scrape, sets their "Stav" to "Odstraněno". New data always wins (`keep="first"` dedup). CSVs grow over time — rows are never deleted, only marked.

### merge happens after authoritative matching

`pipeline.run_source()` calls `merge_with_previous()` AFTER `match_to_authoritative()`. The "Model auta" in removed rows retains the authoritative format from the last successful scrape. If the reference list changes, old removed rows won't get re-matched.

### skips empty-link rows

`merge_with_previous()` skips previous-CSV rows with an empty `Odkaz na auto`. Without this, rows that somehow lost their URL would accumulate as undedupeable copies on every run — this was the root cause of ~8k CSV growth per 4 days.

### Odkaz clobber on rows present in both scrapes — FIXED (#11)

Previously `merge_with_previous()` did `df.set_index("Odkaz na auto").loc[link]`, which dropped the index column and left the merged row with `Odkaz na auto` = NaN; those empty-link rows were then skipped on the next run, causing churn. Fixed in `core/merge.py` by selecting with a boolean mask (`df[df["Odkaz na auto"] == link].iloc[0]`), which keeps the link column.

**Still recommended:** run parity / regression checks on FRESH scrapes (delete `scrapers/data/scrapes/*.csv` first). Not because of the (now-fixed) link bug, but because merge carries forward each removed row's last authoritative "Model auta" — a changed reference list won't re-match already-removed rows.

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
