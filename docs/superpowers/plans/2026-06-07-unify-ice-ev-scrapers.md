# Unify ICE and EV Scrapers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the parallel `electric/` and `combustion/` scraper suites into one fuel-agnostic, source-oriented `scrapers/` package with a single canonical CSV schema, with zero change to published data.

**Architecture:** Shape A — thin functional source-adapters over a shared `core/` (schema, normalize, fields, matching, merge, http, browser, pipeline). Each source emits rows in one canonical schema and inherits a shared post-scrape pipeline. Verification is by output **parity** against a frozen pre-migration baseline, not unit tests.

**Tech Stack:** Python 3, pandas, aiohttp, Playwright, BeautifulSoup. No new dependencies (per `docs/conventions.md`).

**Spec:** `docs/superpowers/specs/2026-06-07-unify-ice-ev-scrapers-design.md`

---

## Conventions for every task

- **Language:** Czech for user-facing strings; English for code/comments (per `docs/conventions.md`).
- **No new deps.** Only pandas / aiohttp / playwright / beautifulsoup4.
- **Relocations are verbatim.** When a step says "move function `foo` from `A` to `B`", copy the
  body exactly; only change imports. Do not "improve" logic — parity depends on identical behavior.
- **Commit after each task** with the message shown in its final step.
- **Run from repo root** unless noted. The package runs via `python -m scrapers.<module>` (see Task 5),
  so `scrapers/` needs `__init__.py` files (created in Task 1).
- **Parity is the test.** After porting each source, regenerate its CSV into a scratch dir and diff
  against the Task 0 baseline with `tools/parity_check.py`. Zero transformation diffs on shared links.

## File structure (created/modified across the plan)

```
scrapers/__init__.py                     (Task 1)
scrapers/core/__init__.py                (Task 1)
scrapers/core/schema.py                  (Task 1)  canonical columns + fuel/Typ constants
scrapers/core/normalize.py               (Task 1)  BRAND_MAP, merged MODEL_CLEANUP_PATTERNS, normalize_model
scrapers/core/fields.py                  (Task 1)  all extraction helpers + BODY_KEYWORDS
scrapers/core/matching.py                (Task 1)  authoritative ICE matching
scrapers/core/merge.py                   (Task 1)  merge_with_previous
scrapers/core/http.py                    (Task 2)  generalized aiohttp paged search + detail fetch
scrapers/core/browser.py                 (Task 3)  generalized Playwright launch/load_all/cookies
scrapers/core/pipeline.py                (Task 4)  run_source(): dedup → ICE-match → merge → write
scrapers/sources/__init__.py             (Task 4)
scrapers/run.py                          (Task 4)  CLI runner
scrapers/sources/sauto.py                (Task 5)  multi-fuel sauto adapter
scrapers/sources/autodraft.py            (Task 6)  multi-fuel autodraft adapter
scrapers/sources/energycars.py           (Task 7)  EV-only energycars adapter
scrapers/data/scrapes/                   (Task 5)  per-source CSV output dir
scrapers/data/reference/ice_specs.csv    (Task 1)  moved from combustion/data/makes-and-models.csv
scrapers/data/reference/ev_specs.csv     (Task 1)  moved from electric/data/new_cars_specs.csv
tools/parity_check.py                    (Task 0)  parity diff harness
build/build_data.py                      (Task 8)  rewired to scrapers/ paths + Typ-from-CSV
bin/run_all.sh                           (Task 9)  calls scrapers/run.py
.github/workflows/scrape-and-deploy.yml  (Task 9)  updated paths
electric/  combustion/                   (Task 10) DELETED
CLAUDE.md docs/*.md                       (Task 10) rewritten for one suite
```

---

## Task 0: Parity baseline + diff harness

**Files:**
- Create: `tools/parity_check.py`
- Create (gitignored scratch): `tmp/parity/baseline/`

- [ ] **Step 1: Snapshot the current published outputs as the baseline.**

Run from repo root:
```bash
mkdir -p tmp/parity/baseline/electric tmp/parity/baseline/combustion tmp/parity/baseline/site
cp electric/data/scrapes/*.csv   tmp/parity/baseline/electric/
cp combustion/data/scrapes/*.csv tmp/parity/baseline/combustion/
cp site/data/cars.json           tmp/parity/baseline/site/
ls -R tmp/parity/baseline
```
Expected: `electric/{autodraft,energycars,sauto}.csv`, `combustion/{autodraft,sauto}.csv`,
`site/cars.json` all present. **This is the frozen baseline — do not regenerate it later.**

- [ ] **Step 2: Ensure scratch dirs are gitignored.**

Append to `.gitignore` if not already covered:
```bash
grep -qxF 'tmp/' .gitignore || echo 'tmp/' >> .gitignore
git check-ignore tmp/parity/baseline   # expect: tmp/parity/baseline
```

- [ ] **Step 3: Write the parity harness.**

Create `tools/parity_check.py`:
```python
"""Parity diff: compare a regenerated scraper CSV (or cars.json) against a frozen baseline.

Keys rows on "Odkaz na auto". Reports, for links present in BOTH files, any column whose
value changed (a transformation regression). Links only in one side are listed but tolerated
(live listings appear/vanish between runs).

Usage:
  python tools/parity_check.py csv  OLD.csv NEW.csv [--ignore-cols Typ,Spárováno,Tepelné čerpadlo]
  python tools/parity_check.py json OLD_cars.json NEW_cars.json
Exit 0 = no transformation diffs; exit 1 = regressions found.
"""
import sys
import json
import argparse
import pandas as pd

LINK = "Odkaz na auto"


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, float) and v != v:  # NaN
        return ""
    return str(v).strip()


def _rows_from_csv(path):
    df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
    return {r[LINK]: dict(r) for _, r in df.iterrows() if r.get(LINK)}


def _rows_from_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    recs = data["data"] if isinstance(data, dict) and "data" in data else data
    return {r[LINK]: r for r in recs if r.get(LINK)}


def compare(old, new, ignore_cols):
    old_links, new_links = set(old), set(new)
    shared = old_links & new_links
    regressions = []
    for link in sorted(shared):
        o, n = old[link], new[link]
        cols = (set(o) | set(n)) - set(ignore_cols)
        for c in sorted(cols):
            if _norm(o.get(c)) != _norm(n.get(c)):
                regressions.append((link, c, _norm(o.get(c)), _norm(n.get(c))))
    return regressions, old_links - new_links, new_links - old_links


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["csv", "json"])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--ignore-cols", default="")
    args = ap.parse_args()

    ignore = [c for c in args.ignore_cols.split(",") if c]
    loader = _rows_from_csv if args.kind == "csv" else _rows_from_json
    old, new = loader(args.old), loader(args.new)
    regressions, only_old, only_new = compare(old, new, ignore)

    print(f"shared links: {len(set(old) & set(new))}")
    print(f"only in baseline: {len(only_old)}   only in new: {len(only_new)}")
    if regressions:
        print(f"\n{len(regressions)} TRANSFORMATION DIFFS (regressions):")
        for link, col, ov, nv in regressions[:50]:
            print(f"  {link}\n    [{col}] {ov!r} -> {nv!r}")
        if len(regressions) > 50:
            print(f"  ... +{len(regressions) - 50} more")
        sys.exit(1)
    print("\nOK — no transformation diffs on shared links.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke-test the harness against itself (must pass trivially).**

Run:
```bash
python tools/parity_check.py csv tmp/parity/baseline/combustion/sauto.csv tmp/parity/baseline/combustion/sauto.csv
```
Expected: `OK — no transformation diffs on shared links.` and exit 0.

- [ ] **Step 5: Commit.**
```bash
git add tools/parity_check.py .gitignore
git commit -m "test: add parity-diff harness for scraper unification"
```

---

## Task 1: Scaffold package + relocate/merge the shared core

**Files:**
- Create: `scrapers/__init__.py`, `scrapers/core/__init__.py` (both empty)
- Create: `scrapers/core/schema.py`, `scrapers/core/normalize.py`, `scrapers/core/fields.py`,
  `scrapers/core/matching.py`, `scrapers/core/merge.py`
- Move: `combustion/data/makes-and-models.csv` → `scrapers/data/reference/ice_specs.csv`;
  `electric/data/new_cars_specs.csv` → `scrapers/data/reference/ev_specs.csv` (keep originals until Task 10)
- Source references: `combustion/src/utils.py`, `electric/src/utils.py`

- [ ] **Step 1: Create package dirs + reference data.**
```bash
mkdir -p scrapers/core scrapers/sources scrapers/data/scrapes scrapers/data/reference
touch scrapers/__init__.py scrapers/core/__init__.py
cp combustion/data/makes-and-models.csv scrapers/data/reference/ice_specs.csv
cp electric/data/new_cars_specs.csv     scrapers/data/reference/ev_specs.csv
```

- [ ] **Step 2: Write `scrapers/core/schema.py`** (canonical schema — single source of truth):
```python
"""Canonical CSV schema shared by every scraper source."""

TYP_EV = "Elektrické"
TYP_ICE = "Spalovací"

# Canonical column order. Every source emits exactly these columns.
CANONICAL_COLS = [
    "Typ", "Model auta", "Cena (Kč)", "Nájezd (km)", "Rok výroby",
    "Palivo", "Objem motoru", "Typ motoru", "Hybrid typ", "Výkon (kW)",
    "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
    "Kola", "Náhon 4x4", "Karoserie", "Výbava", "Záruka", "Tepelné čerpadlo",
    "Spárováno", "Extra", "Stav", "Zdroj", "Odkaz na auto",
]


def blank_row() -> dict:
    """Return a dict with every canonical column set to ''. Adapters fill what they have."""
    return {c: "" for c in CANONICAL_COLS}
```

- [ ] **Step 3: Write `scrapers/core/normalize.py`** — merge BOTH `MODEL_CLEANUP_PATTERNS`.

Copy `BRAND_MAP` (identical in both) and `normalize_model` verbatim from
`combustion/src/utils.py:9-30`. For `MODEL_CLEANUP_PATTERNS`, **union** the electric patterns
(`electric/src/utils.py:15-18`) and combustion patterns (`combustion/src/utils.py:13-19`), electric
first (Enyaq), then combustion:
```python
"""Brand/model normalisation shared by all sources."""
import re

BRAND_MAP = {
    "Volkswagen": "VW",
}

# Union of electric + combustion cleanup patterns. Order: brand-expanded input assumed.
MODEL_CLEANUP_PATTERNS = [
    # electric: "Škoda Enyaq 60" → "Škoda Enyaq iV 60"
    (re.compile(r'(Škoda Enyaq)(?!\s+iV)\s+(\d{2})\b'), r'\1 iV \2'),
    # combustion:
    (re.compile(r'X-Perience', re.IGNORECASE), 'Xperience'),
    (re.compile(r'\bcombi\b'), 'Combi'),
    (re.compile(r'\bScout Combi\b'), 'Combi Scout'),
    (re.compile(r'\bRS Combi\b'), 'Combi RS'),
    (re.compile(r'Cee´d', re.IGNORECASE), 'Ceed'),
]


def normalize_model(model: str) -> str:
    """Replace a verbose brand prefix with its short alias and apply cleanup rules."""
    for full, short in BRAND_MAP.items():
        if model == full or model.startswith(full + " "):
            model = short + model[len(full):]
            break
    for pattern, replacement in MODEL_CLEANUP_PATTERNS:
        model = pattern.sub(replacement, model)
    return model
```

- [ ] **Step 4: Write `scrapers/core/fields.py`.**

Copy verbatim from `combustion/src/utils.py`: the constants `ENGINE_TYPE_KEYWORDS`,
`HYBRID_KEYWORDS`, `BODY_KEYWORDS`, `TRIM_KEYWORDS`, `DCT_KEYWORDS`, the compiled regexes at
lines 124-129, and every extraction helper: `extract_engine_volume`,
`extract_engine_volume_from_model`, `extract_engine_type`, `strip_engine_from_model`,
`extract_hybrid_type`, `extract_body_type`, `extract_trim`, `extract_warranty`, `extract_dct`,
`extract_particle_filter`, `extract_awd`, plus `_WARRANTY_RE`, `_TRANSMISSION_EXTRA_RE`,
`_SEAT_COUNT_RE`, `_EXTRA_CLEANUP_RES`, and `clean_extra` (combustion `utils.py:66-254`). Start the
file with `import re`. These are fuel-agnostic; EV text simply won't match engine patterns.

- [ ] **Step 5: Write `scrapers/core/matching.py`.**

Copy verbatim from `combustion/src/utils.py:257-573` the entire authoritative-matching block:
`MULTI_WORD_BRANDS`, `_BRAND_MATCH_ALIASES`, `_BODY_GROUPS`, `_BODY_CANON`, `_AUTH_BODY_KEYWORDS`,
`_AUTH_HYBRID_MAP`, `_AUTH_FUEL_MAP`, all `_parse_brand`/`_canonicalize_body`/`_extract_auth_*`/
`_strip_known_parts` helpers, `load_authoritative_list`, the module-level regexes `_GEN_RE`,
`_TRIM_IN_MODEL_RE`, `_ENGINE_IN_MODEL_RE`, `_NUM_SUFFIX_RE`, `_clean_model_for_matching`,
`_extract_body_from_model`, `_model_base_match`, `_score_match`, `_format_unmatched`, and
`match_to_authoritative`. Replace its internal references to `ENGINE_TYPE_KEYWORDS`/`TRIM_KEYWORDS`
with an import: add at top `from .fields import ENGINE_TYPE_KEYWORDS, TRIM_KEYWORDS` and `import csv`,
`import re`. (These two constant lists currently live in the same `utils.py`; now they live in
`fields.py`.)

- [ ] **Step 6: Write `scrapers/core/merge.py`.**

Copy `merge_with_previous` verbatim from `combustion/src/utils.py:33-59` (identical to electric).
Start file with `from pathlib import Path` and `import pandas as pd`.

- [ ] **Step 7: Smoke-test imports + behavior parity of normalize/matching.**

Run:
```bash
python -c "
from scrapers.core import schema, normalize, fields, matching, merge
assert len(schema.CANONICAL_COLS) == 24, schema.CANONICAL_COLS
assert normalize.normalize_model('Volkswagen ID.4') == 'VW ID.4'
assert normalize.normalize_model('Škoda Enyaq 60') == 'Škoda Enyaq iV 60'
assert normalize.normalize_model('Škoda Octavia X-Perience') == 'Škoda Octavia Xperience'
assert fields.extract_engine_type('1.5 TSI') == 'TSI'
assert fields.extract_body_type('Octavia Combi') == 'Combi'
auth = matching.load_authoritative_list('scrapers/data/reference/ice_specs.csv')
print('auth entries:', len(auth))
assert len(auth) > 100
print('core OK')
"
```
Expected: `auth entries: <N>` then `core OK`, exit 0.

- [ ] **Step 8: Commit.**
```bash
git add scrapers/__init__.py scrapers/core scrapers/data/reference
git commit -m "feat: scaffold scrapers package, relocate+merge shared core utils"
```

---

## Task 2: `core/http.py` — generalized aiohttp client

**Files:**
- Create: `scrapers/core/http.py`
- Source reference: `combustion/src/scrape_sauto.py:32-108`

- [ ] **Step 1: Write `scrapers/core/http.py`** generalizing sauto's paging + detail fetch:
```python
"""Generic aiohttp helpers for JSON-API sources (sauto; later mobile.de)."""
import asyncio
import aiohttp

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def fetch_all_items(session, search_url, params, page_size=100):
    """Page through a search API that returns {pagination:{total}, results:[...]}."""
    items, offset, total = [], 0, None
    while True:
        page_params = {**params, "limit": page_size, "offset": offset}
        async with session.get(search_url, params=page_params) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if total is None:
            total = data["pagination"]["total"]
            print(f"  Celkem {total} inzerátů")
        batch = data["results"]
        items.extend(batch)
        offset += page_size
        if offset >= total or not batch:
            break
    return items


async def fetch_detail(session, url, semaphore):
    """Return the 'result' dict from an item detail endpoint, or {} on error."""
    try:
        async with semaphore:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("result", {})
    except Exception:
        return {}


async def fetch_all_details(session, urls, concurrency=20):
    """Fetch many detail URLs concurrently, capped by a semaphore. Order preserved."""
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*[fetch_detail(session, u, sem) for u in urls])
```

- [ ] **Step 2: Smoke-test import.**
```bash
python -c "from scrapers.core import http; print('http OK')"
```
Expected: `http OK`.

- [ ] **Step 3: Commit.**
```bash
git add scrapers/core/http.py
git commit -m "feat: add generalized aiohttp client to core"
```

---

## Task 3: `core/browser.py` — generalized Playwright helpers

**Files:**
- Create: `scrapers/core/browser.py`
- Source references: `electric/src/scrape_autodraft.py:114-125` (`load_all`),
  `electric/src/scrape_energycars.py:19-31` (multi-label `load_all`), cookie clicks in both.

- [ ] **Step 1: Write `scrapers/core/browser.py`:**
```python
"""Generic Playwright helpers for browser-based sources (autodraft, energycars)."""


async def accept_cookies(page, texts):
    """Click the first matching cookie-consent button; ignore if none appears."""
    for t in texts:
        try:
            await page.click(f'text="{t}"', timeout=2000)
            await page.wait_for_timeout(500)
            return
        except Exception:
            pass


async def load_all(page, labels):
    """Click each 'load more' label repeatedly until it disappears."""
    for label in labels:
        while True:
            try:
                btn = page.locator(f'text="{label}"')
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(2000)
                else:
                    break
            except Exception:
                break
```

- [ ] **Step 2: Smoke-test import.**
```bash
python -c "from scrapers.core import browser; print('browser OK')"
```
Expected: `browser OK`.

- [ ] **Step 3: Commit.**
```bash
git add scrapers/core/browser.py
git commit -m "feat: add generalized Playwright helpers to core"
```

---

## Task 4: `core/pipeline.py` + `sources/` package + `run.py`

**Files:**
- Create: `scrapers/core/pipeline.py`, `scrapers/sources/__init__.py` (empty), `scrapers/run.py`
- Source reference: post-scrape steps in `combustion/src/scrape_sauto.py:217-225`

- [ ] **Step 1: Write `scrapers/core/pipeline.py`:**
```python
"""Shared post-scrape pipeline: dedup → ICE auth-match → merge-with-previous → write CSV."""
from pathlib import Path
import pandas as pd

from .schema import CANONICAL_COLS, TYP_ICE
from .merge import merge_with_previous
from . import matching

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCRAPES_DIR = DATA_DIR / "scrapes"
AUTH_CSV = DATA_DIR / "reference" / "ice_specs.csv"


def _match_ice(df, auth_list):
    """Run authoritative matching on ICE rows only; leave EV rows untouched."""
    if "Spárováno" not in df.columns:
        df["Spárováno"] = ""
    ice_mask = df["Typ"] == TYP_ICE
    if ice_mask.any():
        ice = df[ice_mask].copy()
        ice = matching.match_to_authoritative(ice, auth_list)
        df.loc[ice_mask, ice.columns] = ice.values
    return df


def run_source(source_module):
    """Execute a source adapter and persist its CSV via the shared pipeline."""
    import asyncio
    rows = asyncio.run(source_module.scrape())
    df = pd.DataFrame(rows, columns=CANONICAL_COLS)
    df.drop_duplicates(subset="Odkaz na auto", inplace=True)
    df.sort_values("Odkaz na auto", inplace=True)

    auth = matching.load_authoritative_list(AUTH_CSV)
    df = _match_ice(df, auth)

    SCRAPES_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = SCRAPES_DIR / f"{source_module.SOURCE_SLUG}.csv"
    df = merge_with_previous(df, csv_path)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"Hotovo – uloženo {len(df)} aut do {source_module.SOURCE_SLUG}.csv")
    return csv_path
```

Note: `match_to_authoritative` operates on a DataFrame and reads/writes columns by name (per
`combustion/src/utils.py:521-572`); restricting to the ICE subset before calling it keeps EV rows
unmatched, matching the spec.

- [ ] **Step 2: Write `scrapers/run.py`:**
```python
"""CLI runner: execute all source adapters (or a subset via --source)."""
import argparse
import importlib

from scrapers.core import pipeline

SOURCES = ["sauto", "autodraft", "energycars"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", choices=SOURCES,
                    help="run only these sources (default: all)")
    args = ap.parse_args()
    targets = args.source or SOURCES
    for name in targets:
        mod = importlib.import_module(f"scrapers.sources.{name}")
        print(f"=== {mod.SOURCE_NAME} ===")
        pipeline.run_source(mod)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Create empty `scrapers/sources/__init__.py`.**
```bash
touch scrapers/sources/__init__.py
```

- [ ] **Step 4: Smoke-test imports (sources not yet present — expect clean import of pipeline/run).**
```bash
python -c "from scrapers.core import pipeline; import scrapers.run; print('pipeline+run OK')"
```
Expected: `pipeline+run OK`.

- [ ] **Step 5: Commit.**
```bash
git add scrapers/core/pipeline.py scrapers/run.py scrapers/sources/__init__.py
git commit -m "feat: add shared scrape pipeline and CLI runner"
```

---

## Task 5: `sources/sauto.py` — multi-fuel adapter (pilot)

**Files:**
- Create: `scrapers/sources/sauto.py`
- Source references: `electric/src/scrape_sauto.py` (EV `build_record`, Enyaq, heat pump),
  `combustion/src/scrape_sauto.py` (ICE `build_record`, fuel/condition exclusion, field extraction)

This adapter queries BOTH the EV search and the ICE search, builds one canonical row per listing,
and returns the combined list. It reuses `core/http.py`.

- [ ] **Step 1: Write `scrapers/sources/sauto.py`.**

The adapter has two search configs and one `build_record` per fuel, both writing canonical rows.
Reproduce the EV record logic from `electric/src/scrape_sauto.py:103-181` and the ICE record logic
from `combustion/src/scrape_sauto.py:111-201`, mapped onto `schema.blank_row()` and tagged with `Typ`:

```python
"""Sauto.cz adapter — both EV and ICE listings via the JSON search API."""
import re
import aiohttp

from scrapers.core import http, schema
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import (
    extract_body_type, extract_engine_volume, extract_engine_type,
    extract_hybrid_type, extract_trim, extract_warranty, extract_dct,
    extract_particle_filter, extract_awd, clean_extra,
)

SOURCE_NAME = "Sauto.cz"
SOURCE_SLUG = "sauto"
FUELS = {"EV", "ICE"}

SEARCH_URL = "https://www.sauto.cz/api/v1/items/search"
DETAIL_URL = "https://www.sauto.cz/api/v1/items/{id}"
LISTING_URL = "https://www.sauto.cz/osobni/detail/{man}/{mod}/{id}"

_BASE_PARAMS = {
    "price_to": 750000, "vehicle_age_from": 2021, "tachometer_to": 100000,
    "capacity_from": 4, "door_from": 5, "category_id": 838, "operating_lease": "false",
}
EV_PARAMS = {**_BASE_PARAMS, "fuel_seo": "elektro", "equipment_seo": "tepelne-cerpadlo"}
ICE_PARAMS = {**_BASE_PARAMS, "fuel_seo": "benzin,nafta,lpg-benzin,cng-benzin",
              "engine_power_from": 100, "condition_seo": "nove,ojete,predvadeci",
              "typ_seo": "cuv,kombi,suv,hatchback,mpv"}

AWD_RE = re.compile(r'všech\s+kol|4x4|AWD|4MATIC|quattro|xDrive', re.IGNORECASE)
_EXCLUDED_FUEL_RE = re.compile(r'hybrid|elektro', re.IGNORECASE)
_ENYAQ_VARIANT_RE = re.compile(r'\biV\s*(80x?|60|50)\b|\b(80x?|60|50)\b', re.IGNORECASE)


def _enyaq_variant(suffix):
    m = _ENYAQ_VARIANT_RE.search(suffix)
    if m:
        return f"iV {(m.group(1) or m.group(2)).lower()}"
    return ""


def _listing_link(item):
    return LISTING_URL.format(man=item["manufacturer_cb"]["seo_name"],
                              mod=item["model_cb"]["seo_name"], id=item["id"])


def _common(item):
    """Return (model_base, suffix, price, mileage, year) shared by both fuels."""
    brand = item["manufacturer_cb"]["name"]
    model = item["model_cb"]["name"]
    suffix = item.get("additional_model_name") or ""
    if model == "Ostatní" and suffix:
        model_base, suffix = normalize_model(f"{brand} {suffix}"), ""
    else:
        model_base = normalize_model(f"{brand} {model}")
    price = item.get("price") or ""
    mileage = item.get("tachometer") or ""
    year = (item.get("in_operation_date") or item.get("manufacturing_date") or "")[:4]
    return model_base, suffix, price, mileage, year


def build_ev(item, detail):
    """EV canonical row (port of electric/src/scrape_sauto.py:103-181)."""
    if not detail:
        return None
    model_base, suffix, price, mileage, year = _common(item)
    battery_kw = detail.get("battery_capacity") or ""
    vehicle_range = detail.get("vehicle_range") or ""
    if re.search(r'\bEnyaq\b', model_base, re.IGNORECASE) and suffix:
        v = _enyaq_variant(suffix)
        if v:
            model_base = f"Škoda Enyaq {v}"
    if re.fullmatch(r'Škoda Enyaq(?: iV)?', model_base) and battery_kw:
        try:
            bc = float(str(battery_kw).replace(",", "."))
            model_base = f"Škoda Enyaq {'iV 50' if bc <= 56 else 'iV 60' if bc <= 65 else 'iV 80'}"
        except ValueError:
            pass
    drive_name = (detail.get("drive_cb") or {}).get("name", "")
    body_api = (detail.get("vehicle_body_cb") or {}).get("name", "")
    extra_parts = []
    if vehicle_range:
        extra_parts.append(f"Dojezd {vehicle_range} km")
    if battery_kw:
        extra_parts.append(f"Baterie {battery_kw} kWh")
    if suffix:
        extra_parts.append(suffix)

    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_EV,
        "Model auta": model_base, "Cena (Kč)": price, "Nájezd (km)": mileage,
        "Výkon (kW)": detail.get("engine_power") or "", "Rok výroby": year,
        "Palivo": "Elektro", "Tepelné čerpadlo": "Ano",
        "Náhon 4x4": "Ano" if AWD_RE.search(drive_name) else "Ne",
        "Karoserie": body_api or extract_body_type(model_base),
        "Extra": " / ".join(extra_parts),
        "Stav": (detail.get("condition_cb") or {}).get("name", ""),
        "Zdroj": SOURCE_NAME, "Odkaz na auto": _listing_link(item),
    })
    return row


def build_ice(item, detail):
    """ICE canonical row (port of combustion/src/scrape_sauto.py:111-201)."""
    if not detail:
        return None
    fuel = (detail.get("fuel_cb") or {}).get("name", "")
    if _EXCLUDED_FUEL_RE.search(fuel):
        return None
    condition = (detail.get("condition_cb") or {}).get("name", "")
    if "Havarované" in condition:
        return None
    model_base, suffix, price, mileage, year = _common(item)
    drive_name = (detail.get("drive_cb") or {}).get("name", "")
    awd = "Ano" if AWD_RE.search(drive_name) else "Ne"
    if awd == "Ne" and extract_awd(suffix) == "Ano":
        awd = "Ano"
    gearbox = (detail.get("gearbox_cb") or {}).get("name", "")

    raw = detail.get("engine_volume")
    if raw and int(raw) > 100:
        engine_volume = f"{int(raw) / 1000:.1f}"
    elif raw:
        engine_volume = str(raw)
    else:
        engine_volume = extract_engine_volume(suffix)
    body_api = (detail.get("vehicle_body_cb") or {}).get("name", "")
    body_type = body_api or extract_body_type(model_base + " " + suffix)
    extra_text = suffix if suffix else ""

    extracted = {
        "Objem motoru": engine_volume,
        "Typ motoru": extract_engine_type(suffix),
        "Hybrid typ": extract_hybrid_type(suffix),
        "Karoserie": body_type,
        "Výbava": extract_trim(suffix),
        "Záruka": extract_warranty(suffix),
        "Dvouspojková převodovka": extract_dct(gearbox + " " + suffix + " " + extra_text),
        "Filtr pevných částic": extract_particle_filter(suffix),
    }
    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_ICE,
        "Model auta": model_base, "Cena (Kč)": price, "Nájezd (km)": mileage,
        "Výkon (kW)": detail.get("engine_power") or "", "Rok výroby": year,
        "Palivo": fuel, "Převodovka": gearbox, "Náhon 4x4": awd,
        "Extra": clean_extra(extra_text, extracted),
        "Stav": condition, "Zdroj": SOURCE_NAME, "Odkaz na auto": _listing_link(item),
        **extracted,
    })
    return row


async def _scrape_fuel(session, params, builder):
    items = await http.fetch_all_items(session, SEARCH_URL, params)
    print(f"  Staženo {len(items)} položek. Načítám detaily...")
    urls = [DETAIL_URL.format(id=it["id"]) for it in items]
    details = await http.fetch_all_details(session, urls)
    return [r for r in (builder(it, d) for it, d in zip(items, details)) if r is not None]


async def scrape():
    async with aiohttp.ClientSession(headers=http.DEFAULT_HEADERS) as session:
        print("Načítám EV inzeráty ze Sauto API...")
        ev = await _scrape_fuel(session, EV_PARAMS, build_ev)
        print("Načítám ICE inzeráty ze Sauto API...")
        ice = await _scrape_fuel(session, ICE_PARAMS, build_ice)
    return ev + ice
```

- [ ] **Step 2: Run the new sauto adapter into a scratch CSV.**
```bash
python -m scrapers.run --source sauto
ls -l scrapers/data/scrapes/sauto.csv
```
Expected: prints EV + ICE counts, writes `scrapers/data/scrapes/sauto.csv`. (Note: first run has no
previous CSV so `merge_with_previous` is a no-op — good for parity.)

- [ ] **Step 3: Parity-diff against the combined baseline sauto CSVs.**

The new single sauto CSV must reproduce the union of the two old sauto CSVs. Build a combined
baseline and diff (ignore the intended new columns):
```bash
python -c "
import pandas as pd
e = pd.read_csv('tmp/parity/baseline/electric/sauto.csv', dtype=str).fillna('')
c = pd.read_csv('tmp/parity/baseline/combustion/sauto.csv', dtype=str).fillna('')
pd.concat([e, c], ignore_index=True).to_csv('tmp/parity/sauto_baseline_combined.csv', index=False)
"
python tools/parity_check.py csv tmp/parity/sauto_baseline_combined.csv scrapers/data/scrapes/sauto.csv \
  --ignore-cols "Typ,Spárováno"
```
Expected: `OK — no transformation diffs on shared links.` exit 0. Investigate ANY transformation
diff (it means the port changed behavior). `only in baseline/only in new` counts reflect live
listing churn + EV rows now carrying ICE columns — tolerated. Spot-check a handful of EV rows have
`Typ=Elektrické, Tepelné čerpadlo=Ano` and ICE rows have `Typ=Spalovací, Palivo` set.

- [ ] **Step 4: Commit.**
```bash
git add scrapers/sources/sauto.py
git commit -m "feat: unified multi-fuel sauto adapter on shared core"
```

---

## Task 6: `sources/autodraft.py` — multi-fuel adapter

**Files:**
- Create: `scrapers/sources/autodraft.py`
- Source references: `electric/src/scrape_autodraft.py` (EV branch, Enyaq-from-URL, heat pump),
  `combustion/src/scrape_autodraft.py` (ICE branch, fuel/transmission, field extraction)

This adapter loads the EV URLs and the ICE URLs in one browser session, parses each card into a
canonical row, dedups via a shared `seen` set. It reuses `core/browser.py`.

- [ ] **Step 1: Write `scrapers/sources/autodraft.py`.**

Combine both autodraft scrapers. Shared parsing helpers (`extract_model_and_status`, `split_model`,
`split_extra`) come from `combustion/src/scrape_autodraft.py:74-145` (the combustion `split_model`
also strips the "2letá záruka" prefix — keep that superset version). Keep electric-only
`_enyaq_variant_from_url` and `Tepelko` heat-pump detection for EV cards; keep combustion `_extract_fuel`,
`_extract_transmission`, `_EXCLUDED_FUEL_RE`, and the full field-extraction for ICE cards. EV cards
come from `?palivo=elektro` + the coming-soon page (elektro checkbox); ICE cards from
`?palivo=benzin`, `?palivo=diesel` + coming-soon (benzin/diesel checkboxes).

```python
"""Autodraft.cz adapter — both EV and ICE listings via Playwright + BeautifulSoup."""
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scrapers.core import browser, schema
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import (
    extract_body_type, extract_engine_volume, extract_engine_volume_from_model,
    extract_engine_type, strip_engine_from_model, extract_hybrid_type, extract_trim,
    extract_warranty, extract_dct, extract_particle_filter, extract_awd, clean_extra,
)

SOURCE_NAME = "Autodraft.cz"
SOURCE_SLUG = "autodraft"
FUELS = {"EV", "ICE"}

# (url, is_on_the_way, fuel_kind, url_fuel)  fuel_kind in {"EV","ICE"}
URLS = [
    ("https://www.autodraft.cz/auta.html?palivo=elektro", False, "EV", ""),
    ("https://www.autodraft.cz/auta.html?palivo=benzin", False, "ICE", "Benzín"),
    ("https://www.autodraft.cz/auta.html?palivo=diesel", False, "ICE", "Nafta"),
    ("https://www.autodraft.cz/auta-na-ceste.html", True, "BOTH", ""),
]
LOAD_MORE = ["Načíst další auta"]
COOKIE_TEXTS = ["Accept all"]

STATUS_MAP = {
    "domluvená prohlídka": "Zamluvené", "zálohované": "Zamluvené",
    "zarezervované": "Zamluvené", "prodané": "Prodané",
}
MODEL_SEPARATOR = "oceníte na cestách:"
_FUEL_KEYWORDS = ["LPG + benzín", "CNG + benzín", "Benzín", "Nafta", "Diesel", "LPG", "CNG"]
_EXCLUDED_FUEL_RE = re.compile(r'\b(?:Elektro|Hybrid)\b', re.IGNORECASE)
_TRANSMISSION_RE = re.compile(r'\b(automat(?:ick[áa])?|DSG|manu[áa]l(?:ní)?|Man\.|MAN)\b', re.IGNORECASE)
_ENYAQ_URL_VARIANT_RE = re.compile(r'enyaq-(?:iv-?)?(80x?|60|50)', re.IGNORECASE)
```

Then port verbatim from the combustion scraper: `_extract_fuel` (`:55-60`),
`_extract_transmission` (`:63-71`), `extract_model_and_status` (`:74-102`), `split_model`
(`:105-112`), `split_extra` (`:124-145`); and from the electric scraper `_enyaq_variant_from_url`
(`:107-111`). Then the scrape loop:

```python
def _enyaq_variant_from_url(url):
    m = _ENYAQ_URL_VARIANT_RE.search(url)
    return f"iV {m.group(1)}" if m else ""


def _build_ev(text, base_name, power, kola, nahon_4x4, rok, extra_rest, status, link):
    if re.search(r'\bEnyaq\b', base_name, re.IGNORECASE) and not re.search(r'iV\s+\d', base_name):
        v = _enyaq_variant_from_url(link)
        if v:
            base_name = f"Škoda Enyaq {v}"
    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_EV, "Model auta": base_name, "Výkon (kW)": power,
        "Rok výroby": rok, "Palivo": "Elektro",
        "Tepelné čerpadlo": "Ano" if "Tepelko" in text else "Ne",
        "Kola": kola, "Náhon 4x4": nahon_4x4,
        "Karoserie": extract_body_type(base_name + " " + extra_rest),
        "Extra": extra_rest, "Stav": status, "Zdroj": SOURCE_NAME, "Odkaz na auto": link,
    })
    return row, base_name


def _build_ice(text, base_name, power, kola, nahon_4x4, rok, extra_rest, status, link, fuel):
    if extract_awd(extra_rest) == "Ano" or extract_awd(base_name) == "Ano":
        nahon_4x4 = "Ano"
    engine_vol = extract_engine_volume_from_model(base_name) or extract_engine_volume(extra_rest)
    engine_type = extract_engine_type(base_name) or extract_engine_type(extra_rest)
    base_name = strip_engine_from_model(base_name,
        extract_engine_volume_from_model(base_name), extract_engine_type(base_name))
    trim = extract_trim(base_name) or extract_trim(extra_rest)
    extracted = {
        "Objem motoru": engine_vol, "Typ motoru": engine_type,
        "Hybrid typ": extract_hybrid_type(text),
        "Karoserie": extract_body_type(base_name + " " + extra_rest),
        "Výbava": trim, "Záruka": extract_warranty(text),
        "Dvouspojková převodovka": extract_dct(text),
        "Filtr pevných částic": extract_particle_filter(extra_rest),
    }
    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_ICE, "Model auta": base_name, "Výkon (kW)": power,
        "Rok výroby": rok, "Palivo": fuel, "Převodovka": _extract_transmission(text),
        "Kola": kola, "Náhon 4x4": nahon_4x4,
        "Extra": clean_extra(extra_rest, extracted),
        "Stav": status, "Zdroj": SOURCE_NAME, "Odkaz na auto": link, **extracted,
    })
    return row


async def scrape():
    rows, seen = [], set()
    async with async_playwright() as p:
        page = await (await p.chromium.launch(headless=True)).new_page()
        for url, is_on_the_way, kind, url_fuel in URLS:
            print(f"Zpracovávám: {url}")
            await page.goto(url)
            await browser.accept_cookies(page, COOKIE_TEXTS)
            if is_on_the_way:
                for lbl in ["elektro", "benzin", "diesel"]:
                    try:
                        await page.click(f'label:has-text("{lbl}")', timeout=3000)
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass
            await browser.load_all(page, LOAD_MORE)
            soup = BeautifulSoup(await page.content(), "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/detail/" not in href:
                    continue
                text = a.get_text(separator=" ", strip=True)
                link = href if href.startswith("http") else "https://www.autodraft.cz" + href
                if link in seen:
                    continue

                is_ev = ("Elektro" in text) if kind in ("EV", "BOTH") else False
                is_excluded = bool(_EXCLUDED_FUEL_RE.search(text))
                # Determine fuel for ICE rows
                fuel = url_fuel
                tl = text.lower()
                if not fuel and MODEL_SEPARATOR in tl:
                    after = text[tl.index(MODEL_SEPARATOR) + len(MODEL_SEPARATOR):].strip()
                    fuel = _extract_fuel(after)

                if kind == "EV":
                    if "Elektro" not in text:   # electric on-list page already filtered, guard anyway
                        pass
                elif kind == "ICE":
                    if is_excluded:
                        continue
                    if is_on_the_way and not fuel:
                        continue
                else:  # BOTH (coming-soon page): route per card
                    if not is_ev and is_excluded:
                        continue
                    if not is_ev and not fuel:
                        continue

                model, status = extract_model_and_status(text, is_on_the_way)
                base_name, extra = split_model(model)
                base_name = normalize_model(base_name)
                power, kola, nahon_4x4, rok, extra_rest = split_extra(extra)
                price_m = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*Kč", text)
                mileage_m = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*km", text)
                year_m = re.search(r'(?<!\d)\d{1,2}/(20[12]\d)(?!\d)', text)
                if year_m:
                    rok = year_m.group(1)

                route_ev = is_ev or kind == "EV"
                if route_ev:
                    row, base_name = _build_ev(text, base_name, power, kola, nahon_4x4, rok,
                                               extra_rest, status, link)
                else:
                    row = _build_ice(text, base_name, power, kola, nahon_4x4, rok,
                                     extra_rest, status, link, fuel)
                row["Cena (Kč)"] = price_m.group(1).replace(" ", "") if price_m else ""
                row["Nájezd (km)"] = mileage_m.group(1).replace(" ", "") if mileage_m else ""
                seen.add(link)
                rows.append(row)
        return rows
```

- [ ] **Step 2: Run + parity-diff.**
```bash
python -m scrapers.run --source autodraft
python -c "
import pandas as pd
e = pd.read_csv('tmp/parity/baseline/electric/autodraft.csv', dtype=str).fillna('')
c = pd.read_csv('tmp/parity/baseline/combustion/autodraft.csv', dtype=str).fillna('')
pd.concat([e, c], ignore_index=True).to_csv('tmp/parity/autodraft_baseline_combined.csv', index=False)
"
python tools/parity_check.py csv tmp/parity/autodraft_baseline_combined.csv \
  scrapers/data/scrapes/autodraft.csv --ignore-cols "Typ,Spárováno"
```
Expected: exit 0. Investigate any transformation diff. (Coming-soon page now routes EV vs ICE per
card by `"Elektro" in text`; verify a few coming-soon EV cards landed as `Elektrické` and ICE as
`Spalovací` with fuel set.)

- [ ] **Step 3: Commit.**
```bash
git add scrapers/sources/autodraft.py
git commit -m "feat: unified multi-fuel autodraft adapter on shared core"
```

---

## Task 7: `sources/energycars.py` — EV-only adapter

**Files:**
- Create: `scrapers/sources/energycars.py`
- Source reference: `electric/src/scrape_energycars.py` (whole file)

energycars is EV-only and uses listing→detail concurrency. Port it nearly verbatim, mapping output
to canonical rows (Typ=Elektrické, Palivo=Elektro) and using `core/browser.py` for cookies/load_all.
Keep its own `fetch_detail_data` (its detail parsing — heat pump / wheels / drive / H1 / price —
is energycars-specific and stays in the adapter).

- [ ] **Step 1: Write `scrapers/sources/energycars.py`** porting `electric/src/scrape_energycars.py`,
with these changes: import `from scrapers.core import browser, schema` and
`from scrapers.core.normalize import normalize_model`, `from scrapers.core.fields import extract_body_type`;
replace the inline `load_all` with `browser.load_all(page, ["Načíst další", "Zobrazit více", "Načíst více"])`
and cookie loop with `browser.accept_cookies(page, ["Souhlasím", "Accept all", "Přijmout vše"])`;
build each car via `schema.blank_row()` then `.update({...})` with `"Typ": schema.TYP_EV,
"Palivo": "Elektro"`, the same field values as the original (`:181-195`), and keep the detail-page
post-processing loop (`:203-212`). Expose `SOURCE_NAME = "EnergyCars.cz"`, `SOURCE_SLUG = "energycars"`,
`FUELS = {"EV"}`, and `async def scrape()` returning the list of canonical rows (drop the DataFrame/CSV
writing — the pipeline does that). Keep `DETAIL_CONCURRENCY = 5` and the `async_playwright` browser
lifecycle inside `scrape()`.

- [ ] **Step 2: Run + parity-diff.**
```bash
python -m scrapers.run --source energycars
python tools/parity_check.py csv tmp/parity/baseline/electric/energycars.csv \
  scrapers/data/scrapes/energycars.csv --ignore-cols "Typ,Spárováno"
```
Expected: exit 0 (energycars `Stav` is always `Dostupný`; no auth matching since EV).

- [ ] **Step 3: Commit.**
```bash
git add scrapers/sources/energycars.py
git commit -m "feat: energycars EV adapter on shared core"
```

---

## Task 8: Rewire `build/build_data.py` + cars.json parity

**Files:**
- Modify: `build/build_data.py`
- Source reference: current `build/build_data.py` (whole file)

- [ ] **Step 1: Replace the CSV-loading + Typ assignment.**

Replace `load_electric_csvs` + `load_combustion_csvs` (`build/build_data.py:22-42`) with one loader
reading the unified per-source CSVs, which already carry `Typ`:
```python
def load_scraper_csvs():
    dfs = []
    scrapes = os.path.join(BASE_DIR, "scrapers", "data", "scrapes")
    for name in ["sauto", "autodraft", "energycars"]:
        path = os.path.join(scrapes, f"{name}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            dfs.append(df)
            print(f"  {name}: {len(df)} rows")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
```
In `main()` (`:232-238`) replace the two loader calls + concat with:
```python
    print("Loading scraper CSVs...")
    df = load_scraper_csvs()
    print(f"  Combined: {len(df)} rows, {len(df.columns)} columns")
```
Do NOT set `df["Typ"]` — it comes from the CSV now.

- [ ] **Step 2: Point reference loaders at the new paths.**

In `load_combustion_reference` (`:44-48`) change the path to
`os.path.join(BASE_DIR, "scrapers", "data", "reference", "ice_specs.csv")`. In
`load_electric_reference` (`:50-56`) change it to
`os.path.join(BASE_DIR, "scrapers", "data", "reference", "ev_specs.csv")`. Leave the join logic
(`join_combustion_reference`, `join_electric_reference`) unchanged — it routes on
`df["Typ"] == "Spalovací"` / `"Elektrické"`, which still holds.

- [ ] **Step 3: Run the build into a scratch output and parity-diff cars.json.**

Temporarily redirect output is unnecessary — the build writes `site/data/cars.json`. First copy the
current one aside (already in baseline), run, then diff:
```bash
python build/build_data.py
python tools/parity_check.py json tmp/parity/baseline/site/cars.json site/data/cars.json \
  --ignore-cols "Typ,Spárováno"
```
Expected: exit 0 on transformation diffs for shared links. `only in baseline/only in new` reflects
live churn. If regressions appear, they indicate a column-mapping mismatch in the build rewrite.

- [ ] **Step 4: UI verification (mandatory per `docs/conventions.md`).**
```bash
python3 build/verify_ui.py --page index --scenario grid
python3 build/verify_ui.py --page reference --scenario grid
```
Expected: exit 0 for both; then **Read** `tmp/ui-verify/index-grid.png` and
`tmp/ui-verify/reference-grid.png` and confirm the grid renders with cars and the dark theme intact.

- [ ] **Step 5: Commit.**
```bash
git add build/build_data.py
git commit -m "feat: build_data reads unified scraper CSVs + Typ from data"
```

---

## Task 9: Update `bin/` + GitHub Actions workflow

**Files:**
- Modify: `bin/run_all.sh`
- Delete: `electric/bin/run_scraper.sh`, `combustion/bin/run_scraper.sh` (in Task 10 tree delete; here just rewire run_all)
- Modify: `.github/workflows/scrape-and-deploy.yml`

- [ ] **Step 1: Read the current `bin/run_all.sh` and dep-check pattern.**
```bash
cat bin/run_all.sh
cat electric/bin/run_scraper.sh
```
(Understand the dependency check + invocation; the new runner replaces both suite scripts.)

- [ ] **Step 2: Rewrite `bin/run_all.sh`** to invoke the unified runner. Replace the body that calls
the two suite `run_scraper.sh` scripts with a single dependency check (playwright/pandas/aiohttp/bs4
+ `playwright install chromium`) followed by:
```bash
python -m scrapers.run "$@"
```
so `./bin/run_all.sh` runs all sources and `./bin/run_all.sh --source sauto` filters. Keep the
shebang, `set -euo pipefail`, and any existing venv/activation lines from the original script.

- [ ] **Step 3: Update the workflow paths.**

In `.github/workflows/scrape-and-deploy.yml`, replace the steps that run the two suite scrapers with
one step `python -m scrapers.run`, and update any committed-data paths from
`electric/data/scrapes` + `combustion/data/scrapes` to `scrapers/data/scrapes`. Leave the schedule,
build step (`python build/build_data.py`), and Pages deploy unchanged.
```bash
grep -n "electric\|combustion\|run_scraper\|build_data" .github/workflows/scrape-and-deploy.yml
```
(Use the grep output to find every path that needs updating.)

- [ ] **Step 4: Verify the runner end-to-end via the bin entrypoint (no network assertion — just that it dispatches).**
```bash
bash -n bin/run_all.sh                 # syntax check
python -m scrapers.run --source energycars   # one real source as smoke (or skip if offline)
```

- [ ] **Step 5: Commit.**
```bash
git add bin/run_all.sh .github/workflows/scrape-and-deploy.yml
git commit -m "chore: run all sources via unified runner in bin + CI"
```

---

## Task 10: Cutover — delete old trees + rewrite docs

**Files:**
- Delete: `electric/`, `combustion/` (entire trees)
- Modify: `CLAUDE.md`, `docs/architecture.md`, `docs/conventions.md`, `docs/gotchas.md`

- [ ] **Step 1: Final full-pipeline parity before deleting anything.**

Run all sources via the unified runner, rebuild, and re-diff cars.json one last time:
```bash
python -m scrapers.run
python build/build_data.py
python tools/parity_check.py json tmp/parity/baseline/site/cars.json site/data/cars.json \
  --ignore-cols "Typ,Spárováno"
python3 build/verify_ui.py --page index --scenario grid   # then Read the PNG
```
Expected: exit 0; screenshot good. **Do not proceed to deletion until this passes.**

- [ ] **Step 2: Delete the old suite trees.**
```bash
git rm -r electric combustion
```

- [ ] **Step 3: Rewrite the docs for one suite.**

Update each doc to describe the single `scrapers/` package, one canonical 24-column schema, the
source-adapter contract, and the `python -m scrapers.run` entrypoint:
- `CLAUDE.md` — replace the two-suite tables/commands with the unified layout + run commands; update
  "Quick Reference" (brand alias → `scrapers/core/normalize.py`; add column → `core/schema.py` +
  adapter; concurrency knobs → adapter constants).
- `docs/architecture.md` — replace the two-tree diagram with the `scrapers/` tree; update Data Flow,
  Scraper Comparison (now per-source, each multi-fuel where applicable), Column tables (one schema),
  Normalisation/Field-extraction/Matching pipelines (now in `core/`).
- `docs/conventions.md` — update paths in "Running Scrapers" and "Verification After Changes" to the
  unified runner; keep the "no new deps", language, async, regex, column-order conventions.
- `docs/gotchas.md` — keep every existing gotcha (the parsing behaviors are unchanged) but re-home
  them under per-source headings (sauto / autodraft / energycars) and fix file paths to `scrapers/`.

- [ ] **Step 4: Final import + run smoke after deletion (ensures nothing imported the old trees).**
```bash
python -c "import scrapers.run; from scrapers.sources import sauto, autodraft, energycars; print('ok')"
python build/build_data.py >/dev/null && echo "build ok"
```
Expected: `ok` then `build ok`.

- [ ] **Step 5: Commit.**
```bash
git add -A
git commit -m "refactor: cut over to unified scrapers package, remove electric/combustion suites"
```

---

## Done criteria

- `scrapers/` is the only scraper tree; `electric/` and `combustion/` are gone.
- One canonical 24-column schema (`core/schema.py`); both `scrape-data-cols.txt` removed.
- `python -m scrapers.run` (and `bin/run_all.sh`) runs sauto + autodraft + energycars, each emitting
  canonical rows; sauto + autodraft cover both fuels.
- `cars.json` parity-clean vs the pre-migration baseline (no transformation diffs on shared links);
  `verify_ui.py` exit 0 + screenshot confirmed.
- Docs describe the single suite. No new dependencies added.
- `mobile.de` is NOT added here — it is the next spec, now cheap (one adapter + a `run.py` entry).
