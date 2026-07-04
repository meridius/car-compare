# grow-reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable, agentic tool that finds the car models missing from the reference lists, researches their specs via subagents behind a human review gate, and grows `ev_specs.csv` / `ice_specs.csv` so the unpaired-listing count keeps dropping.

**Architecture:** A deterministic, offline-tested Python core (`build/reference_gap.py`) extracts unpaired listings from a freshly-rebuilt `cars.json`, clusters them by model, classifies each cluster (missing reference vs a normalization fix), and projects impact. The main thread then dispatches haiku/sonnet research subagents (one per missing-reference cluster) that return structured spec rows with cited sources; a human approves a subset; the core appends the rows, rebuilds, and reports the real before/after drop. Repeatable: re-running re-derives gaps, so covered models fall away.

**Tech Stack:** Python 3 stdlib + pandas (no new deps), `unittest`, existing `scrapers.core.normalize` + `build/build_data.py`, Claude Code subagents (WebSearch/WebFetch).

## Global Constraints

- No new runtime dependencies — stdlib + `pandas` only.
- User-facing strings Czech; code identifiers/comments English.
- Reference-CSV column order must match the existing header **exactly**; never reorder.
- CSV is the only persisted output — no DB, no extra data files (JSON under `tmp/` is scratch).
- Tests are offline stdlib `unittest`, run via `./bin/test.sh` (`python3 -m unittest discover -s tests -p "test_*.py"`), which must stay green (62 tests today).
- EV pairing rule (verbatim, from `build/build_data.py:302-304`): a listing pairs iff `listing["Model auta"].lower().startswith(ref["Model auta"].lower())` — longest-prefix, case-insensitive.
- Numeric CSV formatting: `Cd` uses a dot decimal (`0.28`); every other decimal uses a comma (`86,5`) and is therefore quoted by `csv.QUOTE_MINIMAL`; integers stay bare; unknown = empty cell.
- Honesty: never fabricate specs. Every numeric spec carries a source URL in a sidecar; if unfindable, the cell is left blank. `Cd zdroj ∈ {reálné, odhad}` — `odhad` only for body-shape estimates.
- `build/reference_gap.py` runs as a script (like `build_data.py`): set `BASE_DIR = repo root`, `sys.path.insert(0, BASE_DIR)`, then import `scrapers.*`. Tests import it by adding `build/` to `sys.path`.

**Reference schemas (column order authoritative):**

- EV `scrapers/data/reference/ev_specs.csv`: `Model auta, Objem kufru (l), Hlučnost (dB), Kapacita baterie (kWh), Dojezd komb. letní WLTP (km), Dojezd komb. letní EV-database (km), Cd, Cd zdroj, Tepelné čerpadlo možné (ano/ne)`
- ICE `scrapers/data/reference/ice_specs.csv`: `Jednoznačná varianta vozu, Značka, Model, Výbava, Generace, Karoserie, Počet míst, Objem motoru, Typ motoru, Palivo, Hybrid typ, Spotřeba (l/100 km), Objem kufru (l), Hlučnost (dB), Cd, Cd zdroj`

---

## File Structure

- **Create `build/reference_gap.py`** — deterministic core + argparse CLI (`gaps` / `validate` / `apply`). Single responsibility: turn unpaired listings into ranked, classified, projected candidate reference rows, and safely append approved ones.
- **Create `tests/test_reference_gap.py`** — offline unit tests for clustering, classification, projection, validation, CSV formatting.
- **Create `.claude/commands/grow-reference.md`** — the interactive orchestration prompt (dispatch research subagents → gate → apply), mirroring `.claude/commands/tasks-work.md`.
- **Create `bin/grow-reference.sh`** — thin wrapper running the deterministic phases from repo root (mirrors `bin/test.sh` style).
- **Create `docs/superpowers/grow-reference-RESULTS.md`** — demonstration evidence (Task 8).

Module-level constants in `build/reference_gap.py` (define once in Task 1, reused throughout):

```python
FUELS = {"ev": "Elektrické", "ice": "Spalovací"}
REF_FILES = {"ev": "ev_specs.csv", "ice": "ice_specs.csv"}
ID_COL = {"ev": "Model auta", "ice": "Jednoznačná varianta vozu"}
EV_RANGES = {
    "Objem kufru (l)": (50, 900),
    "Hlučnost (dB)": (50, 85),
    "Kapacita baterie (kWh)": (10, 150),
    "Dojezd komb. letní WLTP (km)": (100, 800),
    "Dojezd komb. letní EV-database (km)": (100, 800),
    "Cd": (0.20, 0.45),
}
```

**Cluster dict shape** (produced by `cluster()`, consumed everywhere after):

```python
{
    "key": "renault twingo",              # canonical grouping key (lowercased)
    "prefix": "Renault Twingo",           # candidate Model auta = shared brand+model prefix of raw names
    "volume": 492,                        # number of unpaired listings
    "sample_names": ["Renault Twingo", "Renault Twingo E-Tech", ...],  # up to 5 raw strings
    "sample_links": ["https://...", ...], # up to 3
    "klass": "missing_ref",               # set by classify(): missing_ref | normalization_gap | covered
    "projected": 492,                     # set by gaps CLI via project_newly_paired
}
```

---

### Task 1: Data loading + clustering

**Files:**
- Create: `build/reference_gap.py`
- Test: `tests/test_reference_gap.py`

**Interfaces:**
- Produces: `FUELS`, `REF_FILES`, `ID_COL`, `EV_RANGES` constants; `load_unpaired(cars_json_path, fuel) -> list[dict]`; `_canonical_key(name) -> str`; `_shared_prefix(names) -> str`; `cluster(listings, fuel) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reference_gap.py
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "build"))
import reference_gap as rg  # noqa: E402


class TestCluster(unittest.TestCase):
    def _listings(self):
        return [
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Renault Twingo", "Odkaz na auto": "u1"},
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "Renault Twingo E-Tech 60kW", "Odkaz na auto": "u2"},
            {"Typ": "Elektrické", "Spárováno": "Ano", "Model auta": "Renault Twingo", "Odkaz na auto": "u3"},
            {"Typ": "Spalovací", "Spárováno": "Ne", "Model auta": "BMW 320 2.0", "Odkaz na auto": "u4"},
            {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "BYD DOLPHIN", "Odkaz na auto": "u5"},
        ]

    def test_load_unpaired_filters_fuel_and_state(self):
        ev = rg.load_unpaired_from_rows(self._listings(), "ev")
        links = {r["Odkaz na auto"] for r in ev}
        self.assertEqual(links, {"u1", "u2", "u5"})  # only EV + Ne

    def test_cluster_merges_spec_variants(self):
        ev = rg.load_unpaired_from_rows(self._listings(), "ev")
        clusters = rg.cluster(ev, "ev")
        by_prefix = {c["prefix"]: c for c in clusters}
        self.assertIn("Renault Twingo", by_prefix)
        self.assertEqual(by_prefix["Renault Twingo"]["volume"], 2)  # bare + E-Tech merged
        self.assertEqual(clusters[0]["volume"], 2)  # sorted by volume desc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/martin/projects/meridius/auto-wt-grow-reference && python3 -m unittest tests.test_reference_gap -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reference_gap'`.

- [ ] **Step 3: Write minimal implementation**

```python
# build/reference_gap.py
"""grow-reference: find missing reference models from unpaired listings, research
their specs (agentic), and grow ev_specs.csv / ice_specs.csv behind a review gate.

Deterministic core — offline, unit-tested. Run as a script:
    python3 build/reference_gap.py gaps --fuel ev --rebuild
"""
import csv
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from scrapers.core.normalize import normalize_model  # noqa: E402

FUELS = {"ev": "Elektrické", "ice": "Spalovací"}
REF_FILES = {"ev": "ev_specs.csv", "ice": "ice_specs.csv"}
ID_COL = {"ev": "Model auta", "ice": "Jednoznačná varianta vozu"}
EV_RANGES = {
    "Objem kufru (l)": (50, 900),
    "Hlučnost (dB)": (50, 85),
    "Kapacita baterie (kWh)": (10, 150),
    "Dojezd komb. letní WLTP (km)": (100, 800),
    "Dojezd komb. letní EV-database (km)": (100, 800),
    "Cd": (0.20, 0.45),
}
CARS_JSON = os.path.join(BASE_DIR, "site", "data", "cars.json")
REF_DIR = os.path.join(BASE_DIR, "scrapers", "data", "reference")

# spec tokens stripped when deriving a model grouping key (powertrain/battery/hp noise)
_KEY_STRIP = re.compile(
    r"\b(\d{2,3}\s?(kw|ps|hp|k)|\d{2,3}([.,]\d)?\s?kwh|e-?tech|e-?tec|awd|4wd|"
    r"long\s?range|comfort|design|style|extended)\b",
    re.IGNORECASE,
)


def load_unpaired_from_rows(rows, fuel):
    typ = FUELS[fuel]
    return [r for r in rows if r.get("Typ") == typ and r.get("Spárováno") == "Ne"]


def load_unpaired(cars_json_path, fuel):
    with open(cars_json_path, encoding="utf-8") as f:
        rows = json.load(f)["data"]
    return load_unpaired_from_rows(rows, fuel)


def _canonical_key(name):
    n = normalize_model(name or "").lower()
    n = _KEY_STRIP.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def _shared_prefix(names):
    """Longest word-boundary prefix common to all raw names in a cluster."""
    if not names:
        return ""
    split = [n.split() for n in names]
    out = []
    for i in range(min(len(w) for w in split)):
        tok = split[0][i]
        if all(w[i] == tok for w in split):
            out.append(tok)
        else:
            break
    return " ".join(out) if out else names[0]


def cluster(listings, fuel):
    groups = {}
    for r in listings:
        key = _canonical_key(r.get("Model auta", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(r)
    clusters = []
    for key, members in groups.items():
        names = [m.get("Model auta", "") for m in members]
        clusters.append({
            "key": key,
            "prefix": _shared_prefix(names) or names[0],
            "volume": len(members),
            "sample_names": sorted(set(names))[:5],
            "sample_links": [m.get("Odkaz na auto", "") for m in members[:3]],
        })
    clusters.sort(key=lambda c: c["volume"], reverse=True)
    return clusters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_reference_gap -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add build/reference_gap.py tests/test_reference_gap.py
git commit -m "feat(reference-gap): unpaired loading + model clustering"
```

---

### Task 2: Cluster classification (missing_ref / normalization_gap / covered)

**Files:**
- Modify: `build/reference_gap.py`
- Test: `tests/test_reference_gap.py`

**Interfaces:**
- Consumes: `cluster()` output, `normalize_model`.
- Produces: `load_reference_models(fuel) -> list[str]`; `classify(cluster, ref_models) -> str` (writes nothing; caller sets `cluster["klass"]`).

- [ ] **Step 1: Write the failing test**

```python
class TestClassify(unittest.TestCase):
    def test_covered_when_raw_matches_existing_prefix(self):
        c = {"prefix": "Renault Twingo", "sample_names": ["Renault Twingo E-Tech"]}
        self.assertEqual(rg.classify(c, ["Renault Twingo"]), "covered")

    def test_normalization_gap_when_only_normalized_matches(self):
        # BRAND_MAP maps Volkswagen -> VW; raw won't match "VW ID.3" but normalized will
        c = {"prefix": "Volkswagen ID.3", "sample_names": ["Volkswagen ID.3 Pro"]}
        self.assertEqual(rg.classify(c, ["VW ID.3"]), "normalization_gap")

    def test_missing_ref_when_nothing_matches(self):
        c = {"prefix": "Renault Twingo", "sample_names": ["Renault Twingo", "Renault Twingo E-Tech"]}
        self.assertEqual(rg.classify(c, ["Fiat Grande Panda"]), "missing_ref")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_reference_gap.TestClassify -v`
Expected: FAIL — `AttributeError: module 'reference_gap' has no attribute 'classify'`.

- [ ] **Step 3: Write minimal implementation**

```python
def load_reference_models(fuel):
    path = os.path.join(REF_DIR, REF_FILES[fuel])
    with open(path, newline="", encoding="utf-8") as f:
        return [row[ID_COL[fuel]] for row in csv.DictReader(f) if row.get(ID_COL[fuel])]


def _prefix_matches(name, ref_low):
    nl = name.lower()
    return any(nl.startswith(r) for r in ref_low)


def classify(cluster, ref_models):
    ref_low = [r.lower() for r in ref_models]
    raws = cluster.get("sample_names") or [cluster["prefix"]]
    if any(_prefix_matches(n, ref_low) for n in raws):
        return "covered"  # sanity: raw already matches a ref prefix (should have been Ano)
    if any(_prefix_matches(normalize_model(n), ref_low) for n in raws):
        return "normalization_gap"  # a BRAND_MAP/cleanup fix would pair it — not a new row
    return "missing_ref"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_reference_gap.TestClassify -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add build/reference_gap.py tests/test_reference_gap.py
git commit -m "feat(reference-gap): classify missing_ref vs normalization_gap"
```

---

### Task 3: Impact projection + row stub

**Files:**
- Modify: `build/reference_gap.py`
- Test: `tests/test_reference_gap.py`

**Interfaces:**
- Consumes: `load_unpaired` output, cluster dicts.
- Produces: `project_newly_paired(prefixes, unpaired) -> dict[str,int]`; `ev_columns() -> list[str]`; `stub_row(cluster, fuel) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
class TestProjectAndStub(unittest.TestCase):
    def _unpaired(self):
        return [
            {"Model auta": "Renault Twingo"}, {"Model auta": "Renault Twingo E-Tech"},
            {"Model auta": "Fiat Grande Panda"},
        ]

    def test_projection_counts_prefix_matches(self):
        got = rg.project_newly_paired(["Renault Twingo", "Fiat Grande Panda"], self._unpaired())
        self.assertEqual(got, {"Renault Twingo": 2, "Fiat Grande Panda": 1})

    def test_stub_row_has_exact_ev_columns_and_prefix(self):
        row = rg.stub_row({"prefix": "Renault Twingo"}, "ev")
        self.assertEqual(list(row.keys()), rg.ev_columns())
        self.assertEqual(row["Model auta"], "Renault Twingo")
        self.assertEqual(row["Kapacita baterie (kWh)"], "")  # spec blank until researched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_reference_gap.TestProjectAndStub -v`
Expected: FAIL — `AttributeError: ... 'project_newly_paired'`.

- [ ] **Step 3: Write minimal implementation**

```python
def _ev_header():
    path = os.path.join(REF_DIR, REF_FILES["ev"])
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def ev_columns():
    return _ev_header()


def project_newly_paired(prefixes, unpaired):
    names = [str(r.get("Model auta", "")).lower() for r in unpaired]
    out = {}
    for p in prefixes:
        pl = p.lower()
        out[p] = sum(1 for n in names if n.startswith(pl))
    return out


def stub_row(cluster, fuel):
    if fuel != "ev":
        raise NotImplementedError("ICE stub handled in ICE mode task")
    row = {col: "" for col in ev_columns()}
    row["Model auta"] = cluster["prefix"]
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_reference_gap.TestProjectAndStub -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add build/reference_gap.py tests/test_reference_gap.py
git commit -m "feat(reference-gap): impact projection + EV row stub"
```

---

### Task 4: Row validation

**Files:**
- Modify: `build/reference_gap.py`
- Test: `tests/test_reference_gap.py`

**Interfaces:**
- Consumes: `ev_columns()`, `EV_RANGES`, `load_reference_models`.
- Produces: `validate_rows(rows, fuel, ref_models, unpaired) -> tuple[list[dict], list[str]]`. Strips `_`-prefixed sidecar keys from returned ok-rows. An ok-row has exactly the CSV columns.

- [ ] **Step 1: Write the failing test**

```python
class TestValidate(unittest.TestCase):
    def _good(self):
        r = {c: "" for c in rg.ev_columns()}
        r.update({"Model auta": "Renault Twingo", "Kapacita baterie (kWh)": 22,
                  "Dojezd komb. letní WLTP (km)": 190, "Cd": 0.31,
                  "Cd zdroj": "reálné", "Tepelné čerpadlo možné (ano/ne)": "ne"})
        return r

    def test_accepts_good_row_and_drops_sidecar(self):
        r = self._good(); r["_sources"] = {"Cd": "http://x"}
        ok, errs = rg.validate_rows([r], "ev", ["Fiat Grande Panda"], [])
        self.assertEqual(errs, [])
        self.assertNotIn("_sources", ok[0])
        self.assertEqual(list(ok[0].keys()), rg.ev_columns())

    def test_rejects_out_of_range_battery(self):
        r = self._good(); r["Kapacita baterie (kWh)"] = 5
        ok, errs = rg.validate_rows([r], "ev", [], [])
        self.assertEqual(ok, []); self.assertTrue(any("baterie" in e for e in errs))

    def test_rejects_bad_cd_source_and_duplicate_and_overbroad(self):
        r1 = self._good(); r1["Cd zdroj"] = "guess"
        r2 = self._good(); r2["Model auta"] = "Fiat Grande Panda"  # dup vs existing ref
        r3 = self._good(); r3["Model auta"] = "Renault"            # over-broad prefix
        unpaired = [{"Model auta": "Renault Megane E-TECH"}]
        ok, errs = rg.validate_rows([r1, r2, r3], "ev", ["Fiat Grande Panda"], unpaired)
        self.assertEqual(ok, [])
        self.assertEqual(len(errs), 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_reference_gap.TestValidate -v`
Expected: FAIL — `AttributeError: ... 'validate_rows'`.

- [ ] **Step 3: Write minimal implementation**

```python
def _num(v):
    if v is None or str(v).strip() == "":
        return None
    return float(str(v).strip().replace(",", "."))


def validate_rows(rows, fuel, ref_models, unpaired):
    cols = ev_columns()  # EV only for now
    ref_low = [r.lower() for r in ref_models]
    unpaired_low = [str(r.get("Model auta", "")).lower() for r in unpaired]
    ok, errs = [], []
    seen = set()
    for i, raw in enumerate(rows):
        clean = {c: raw.get(c, "") for c in cols}
        model = str(clean.get("Model auta", "")).strip()
        problems = []
        if not model:
            problems.append(f"row {i}: prázdné 'Model auta'")
        # numeric ranges
        for col, (lo, hi) in EV_RANGES.items():
            val = _num(clean.get(col))
            if val is not None and not (lo <= val <= hi):
                label = "baterie" if "baterie" in col else col
                problems.append(f"row {i} ({model}): {label}={val} mimo rozsah {lo}-{hi}")
        # Cd zdroj enum (only when Cd present)
        if str(clean.get("Cd", "")).strip():
            if clean.get("Cd zdroj") not in ("reálné", "odhad"):
                problems.append(f"row {i} ({model}): 'Cd zdroj' musí být reálné/odhad")
        # heat pump enum
        hp = str(clean.get("Tepelné čerpadlo možné (ano/ne)", "")).strip()
        if hp and hp not in ("ano", "ne"):
            problems.append(f"row {i} ({model}): tepelné čerpadlo musí být ano/ne")
        # duplicate vs existing + within-batch
        ml = model.lower()
        if ml in ref_low or ml in seen:
            problems.append(f"row {i} ({model}): duplicitní 'Model auta'")
        # over-broad prefix: a reference prefix must be at least brand+model (2 tokens);
        # a bare brand ("Renault") would pair unrelated cars.
        if model and len(model.split()) < 2 and any(n.startswith(ml) for n in unpaired_low):
            problems.append(f"row {i} ({model}): příliš obecný prefix (jen značka)")
        if problems:
            errs.extend(problems)
        else:
            seen.add(ml)
            ok.append(clean)
    return ok, errs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_reference_gap.TestValidate -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add build/reference_gap.py tests/test_reference_gap.py
git commit -m "feat(reference-gap): validate rows (ranges, enums, dup, over-broad)"
```

---

### Task 5: CSV append + unpaired count

**Files:**
- Modify: `build/reference_gap.py`
- Test: `tests/test_reference_gap.py`

**Interfaces:**
- Consumes: `ev_columns()`, `load_unpaired`.
- Produces: `_fmt_cell(col, val) -> str`; `append_rows(fuel, rows, path=None) -> int`; `count_unpaired(cars_json_path, fuel) -> int`.

- [ ] **Step 1: Write the failing test**

```python
import tempfile

class TestAppendAndCount(unittest.TestCase):
    def test_fmt_cell_cd_dot_others_comma(self):
        self.assertEqual(rg._fmt_cell("Cd", 0.31), "0.31")
        self.assertEqual(rg._fmt_cell("Kapacita baterie (kWh)", 86.5), "86,5")
        self.assertEqual(rg._fmt_cell("Objem kufru (l)", 520), "520")
        self.assertEqual(rg._fmt_cell("Hlučnost (dB)", ""), "")

    def test_append_preserves_header_and_quotes_comma_decimals(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ev.csv")
            with open(p, "w", newline="", encoding="utf-8") as f:
                f.write(",".join(rg.ev_columns()) + "\n")
            row = {c: "" for c in rg.ev_columns()}
            row.update({"Model auta": "Renault Twingo", "Kapacita baterie (kWh)": 22.5, "Cd": 0.31})
            n = rg.append_rows("ev", [row], path=p)
            self.assertEqual(n, 1)
            text = open(p, encoding="utf-8").read()
            self.assertIn("Renault Twingo", text)
            self.assertIn('"22,5"', text)   # comma decimal quoted
            self.assertIn("0.31", text)     # Cd dot, unquoted

    def test_count_unpaired(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cars.json")
            json.dump({"data": [
                {"Typ": "Elektrické", "Spárováno": "Ne", "Model auta": "X"},
                {"Typ": "Elektrické", "Spárováno": "Ano", "Model auta": "Y"},
            ]}, open(p, "w"))
            self.assertEqual(rg.count_unpaired(p, "ev"), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_reference_gap.TestAppendAndCount -v`
Expected: FAIL — `AttributeError: ... '_fmt_cell'`.

- [ ] **Step 3: Write minimal implementation**

```python
def _fmt_cell(col, val):
    if val is None or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if col == "Cd":
        return s.replace(",", ".")
    if re.fullmatch(r"-?\d+", s):
        return s
    if re.fullmatch(r"-?\d+\.0", s):
        return s[:-2]  # 520.0 -> 520
    if re.fullmatch(r"-?\d+[.,]\d+", s):
        return s.replace(".", ",")
    return s


def append_rows(fuel, rows, path=None):
    path = path or os.path.join(REF_DIR, REF_FILES[fuel])
    with open(path, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            w.writerow([_fmt_cell(c, r.get(c, "")) for c in header])
    return len(rows)


def count_unpaired(cars_json_path, fuel):
    return len(load_unpaired(cars_json_path, fuel))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_reference_gap -v`
Expected: PASS (all tests across TestCluster/Classify/Project/Validate/AppendAndCount).

- [ ] **Step 5: Commit**

```bash
git add build/reference_gap.py tests/test_reference_gap.py
git commit -m "feat(reference-gap): CSV-format-preserving append + unpaired count"
```

---

### Task 6: CLI (`gaps` / `validate` / `apply`)

**Files:**
- Modify: `build/reference_gap.py`
- Create: `bin/grow-reference.sh`

**Interfaces:**
- Consumes: every function above.
- Produces: `main(argv)` argparse dispatcher; scratch dir `tmp/ref-gap/`.

- [ ] **Step 1: Implement the CLI (no unit test — exercised by smoke run in Step 2)**

```python
def _rebuild():
    import subprocess
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "build", "build_data.py")],
                   check=True, cwd=BASE_DIR)


def _cmd_gaps(a):
    if a.rebuild:
        _rebuild()
    unpaired = load_unpaired(CARS_JSON, a.fuel)
    ref_models = load_reference_models(a.fuel)
    clusters = cluster(unpaired, a.fuel)
    for c in clusters:
        c["klass"] = classify(c, ref_models)
    proj = project_newly_paired([c["prefix"] for c in clusters], unpaired)
    for c in clusters:
        c["projected"] = proj.get(c["prefix"], 0)
    missing = [c for c in clusters if c["klass"] == "missing_ref"]
    norm = [c for c in clusters if c["klass"] == "normalization_gap"]
    if a.top:
        missing = missing[: a.top]
    outdir = os.path.join(BASE_DIR, "tmp", "ref-gap")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{a.fuel}-clusters.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"missing_ref": missing, "normalization_gap": norm}, f,
                  ensure_ascii=False, indent=2)
    print(f"Nespárováno {a.fuel.upper()}: {len(unpaired)} inzerátů, "
          f"{len(clusters)} modelů ({len(missing)} chybí v referencích, "
          f"{len(norm)} normalizace).")
    print(f"Top {len(missing)} chybějících (→ {out}):")
    for c in missing:
        print(f"  {c['projected']:5d}  {c['prefix']}   e.g. {c['sample_names'][:2]}")
    if norm:
        print(f"Normalizační mezery (oprav BRAND_MAP/MODEL_CLEANUP, nepřidávej řádek):")
        for c in norm[:15]:
            print(f"  {c['volume']:5d}  {c['prefix']}")


def _cmd_validate(a):
    rows = json.load(open(a.infile, encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    ref_models = load_reference_models(a.fuel)
    unpaired = load_unpaired(CARS_JSON, a.fuel)
    ok, errs = validate_rows(rows, a.fuel, ref_models, unpaired)
    for e in errs:
        print("  CHYBA:", e)
    okfile = a.infile + ".ok.json"
    json.dump(ok, open(okfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"OK: {len(ok)}/{len(rows)} řádků prošlo → {okfile}")
    return 0 if not errs else 1


def _cmd_apply(a):
    rows = json.load(open(a.infile, encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    ref_models = load_reference_models(a.fuel)
    unpaired = load_unpaired(CARS_JSON, a.fuel)
    ok, errs = validate_rows(rows, a.fuel, ref_models, unpaired)
    if errs:
        for e in errs:
            print("  CHYBA:", e)
        print("Aplikace přerušena — oprav chyby.")
        return 1
    before = count_unpaired(CARS_JSON, a.fuel)
    n = append_rows(a.fuel, ok)
    _rebuild()
    after = count_unpaired(CARS_JSON, a.fuel)
    print(f"Přidáno {n} referenčních modelů ({a.fuel}).")
    print(f"Nespárováno: {before} → {after}  (−{before - after})")
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="grow-reference: covergrowth for reference models")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gaps"); g.add_argument("--fuel", required=True, choices=list(FUELS))
    g.add_argument("--rebuild", action="store_true"); g.add_argument("--top", type=int, default=0)
    g.set_defaults(fn=_cmd_gaps)
    v = sub.add_parser("validate"); v.add_argument("--fuel", required=True, choices=list(FUELS))
    v.add_argument("--in", dest="infile", required=True); v.set_defaults(fn=_cmd_validate)
    ap = sub.add_parser("apply"); ap.add_argument("--fuel", required=True, choices=list(FUELS))
    ap.add_argument("--in", dest="infile", required=True); ap.set_defaults(fn=_cmd_apply)
    args = p.parse_args(argv)
    rc = args.fn(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the CLI end to end**

Run: `python3 build/reference_gap.py gaps --fuel ev --rebuild --top 20`
Expected: rebuild runs; prints `Nespárováno EV: <N> inzerátů, ... modelů`; writes `tmp/ref-gap/ev-clusters.json`; top-20 missing models listed with projected counts (Renault Twingo etc. near the top).

- [ ] **Step 3: Create the bin wrapper**

```bash
# bin/grow-reference.sh
#!/usr/bin/env bash
# Deterministic phases of grow-reference. The agentic research + review gate is the
# interactive .claude/commands/grow-reference.md flow.
#   ./bin/grow-reference.sh gaps --fuel ev --rebuild --top 30
#   ./bin/grow-reference.sh validate --fuel ev --in tmp/ref-gap/candidates.json
#   ./bin/grow-reference.sh apply --fuel ev --in tmp/ref-gap/candidates.json.ok.json
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 build/reference_gap.py "$@"
```

- [ ] **Step 4: Make it executable and verify**

Run: `chmod +x bin/grow-reference.sh && ./bin/grow-reference.sh gaps --fuel ev --top 5`
Expected: same output as Step 2 (no rebuild this time), top-5 listed.

- [ ] **Step 5: Commit**

```bash
git add build/reference_gap.py bin/grow-reference.sh
git commit -m "feat(reference-gap): gaps/validate/apply CLI + bin wrapper"
```

---

### Task 7: Interactive orchestration command

**Files:**
- Create: `.claude/commands/grow-reference.md`

**Interfaces:**
- Consumes: the CLI from Task 6; Claude Code subagents (haiku/sonnet) with WebSearch/WebFetch.
- Produces: the repeatable human-facing recipe. No code/tests — it is a prompt document. Validated by the Task 8 demonstration.

- [ ] **Step 1: Write the command prompt**

Create `.claude/commands/grow-reference.md` with exactly this content:

````markdown
# /grow-reference — grow reference models to cut unpaired listings

Repeatable loop. Default fuel EV (biggest gap). Steps:

## 1. Find the gaps (deterministic)
Run: `./bin/grow-reference.sh gaps --fuel ev --rebuild --top 30`
This rebuilds `cars.json`, then writes ranked missing-reference clusters to
`tmp/ref-gap/ev-clusters.json` and prints projected newly-paired counts. Note the
current unpaired total. Skim the "Normalizační mezery" list — those are BRAND_MAP /
MODEL_CLEANUP fixes, NOT research targets; report them separately, do not research them.

## 2. Research each missing model (agentic — one subagent per cluster)
Read `tmp/ref-gap/ev-clusters.json` → `missing_ref`. For each cluster, dispatch a
subagent (model `haiku`; use `sonnet` for obscure/ambiguous models) with this contract:

> Research the electric car **"{prefix}"** (sample listing titles: {sample_names}).
> Return ONLY strict JSON with these exact keys:
> `Model auta` (= "{prefix}"), `Objem kufru (l)`, `Hlučnost (dB)`,
> `Kapacita baterie (kWh)`, `Dojezd komb. letní WLTP (km)`,
> `Dojezd komb. letní EV-database (km)`, `Cd`, `Cd zdroj`,
> `Tepelné čerpadlo možné (ano/ne)`, plus `_sources` (object mapping each numeric
> field to a source URL) and `_confidence` ("high"/"medium"/"low").
> Rules: use official manufacturer / ev-database / Wikipedia figures. NEVER invent a
> number — if you cannot find it, use "" (empty). `Cd`: real published value with
> `Cd zdroj`="reálné"; only if none exists, estimate from body shape and set
> `Cd zdroj`="odhad". `Tepelné čerpadlo možné`: "ano"/"ne"/"". If the car has several
> battery variants, give the most common one and note it in `_confidence`.

Collect the returned JSON rows into `tmp/ref-gap/candidates.json` (a JSON array).

## 3. (Optional) adversarial check
For any row with `_confidence` != "high", dispatch a second `haiku` subagent to refute
the specs (independent lookup). If it contradicts battery/range, blank those cells.

## 4. Validate
Run: `./bin/grow-reference.sh validate --fuel ev --in tmp/ref-gap/candidates.json`
Fix or drop any row the validator rejects. Result: `candidates.json.ok.json`.

## 5. Review gate (human)
Present a table: model | projected newly-paired | battery | WLTP | Cd | Cd zdroj |
source URLs. Ask the user which rows to apply. Write the approved subset to
`tmp/ref-gap/approved.json`.

## 6. Apply + measure
Run: `./bin/grow-reference.sh apply --fuel ev --in tmp/ref-gap/approved.json`
Report the printed `Nespárováno: BEFORE → AFTER (−DELTA)`. Run `./bin/test.sh` to
confirm the suite stays green.
````

- [ ] **Step 2: Verify the CLI commands it references exist**

Run: `python3 build/reference_gap.py gaps --help && python3 build/reference_gap.py validate --help && python3 build/reference_gap.py apply --help`
Expected: all three subcommands print usage (confirms the runbook's commands are real).

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/grow-reference.md
git commit -m "feat(reference-gap): /grow-reference interactive orchestration command"
```

---

### Task 8: Demonstration — prove the EV unpaired drop

**Files:**
- Create: `docs/superpowers/grow-reference-RESULTS.md`
- Modify: `scrapers/data/reference/ev_specs.csv` (via `apply`)

**Interfaces:**
- Consumes: the full pipeline (Tasks 1-7).
- Produces: evidence of a real before/after drop; the demonstration doubles as the first real run.

- [ ] **Step 1: Generate gaps**

Run: `./bin/grow-reference.sh gaps --fuel ev --rebuild --top 30`
Record the printed unpaired total (BEFORE) and the top missing models.

- [ ] **Step 2: Research the top ~20 missing_ref clusters**

Dispatch subagents per Task 7 §2 (haiku default). Assemble `tmp/ref-gap/candidates.json`.
Keep to the top ~20 by projected impact for the demo (log that this is a demo subset, not all clusters).

- [ ] **Step 3: Validate**

Run: `./bin/grow-reference.sh validate --fuel ev --in tmp/ref-gap/candidates.json`
Expected: most rows pass; drop/fix any rejected. Produces `candidates.json.ok.json`.

- [ ] **Step 4: Review gate**

Present the table to the user, get the approved subset → `tmp/ref-gap/approved.json`.

- [ ] **Step 5: Apply + measure**

Run: `./bin/grow-reference.sh apply --fuel ev --in tmp/ref-gap/approved.json`
Expected: `Nespárováno: BEFORE → AFTER (−DELTA)` with DELTA in the thousands.

- [ ] **Step 6: Confirm suite green + write results**

Run: `./bin/test.sh`
Expected: OK (still green; data-integrity invariants hold).
Write `docs/superpowers/grow-reference-RESULTS.md`: BEFORE/AFTER counts, rows added, per-model newly-paired, any `odhad` Cd flags, and the re-run instructions.

- [ ] **Step 7: Commit**

```bash
git add scrapers/data/reference/ev_specs.csv docs/superpowers/grow-reference-RESULTS.md
git commit -m "feat(reference-gap): grow EV reference, demonstrate unpaired drop"
```

---

## Self-Review

**Spec coverage:**
- Deterministic core (load/cluster/classify/project/stub/validate/append/measure) → Tasks 1-5. ✓
- Missing-ref vs normalization-gap distinction → Task 2 + surfaced in `gaps` CLI (Task 6). ✓
- CLI `gaps`/`validate`/`apply` → Task 6. ✓
- Agentic research subagent contract + honesty rules → Task 7 §2. ✓
- Review gate → Task 7 §5, Task 8 §4. ✓
- Apply + real before/after → Task 6 `_cmd_apply` + Task 8 §5. ✓
- Repeatability → `--rebuild` re-derives gaps; documented in Task 7. ✓
- Testing (offline unittest; suite stays green) → Tasks 1-5 tests + Task 8 §6. ✓
- Over-broad prefix guard → Task 4. ✓
- CSV format (Cd dot / comma-decimal quoting) → Task 5 `_fmt_cell`. ✓
- EV-first, ICE later → EV throughout; `stub_row`/`validate_rows` raise/branch EV-only, ICE is a follow-up (out of this plan's scope, matches spec).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command + expected output.

**Type consistency:** `load_unpaired_from_rows`/`load_unpaired`, `cluster`, `classify`, `load_reference_models`, `project_newly_paired`, `ev_columns`, `stub_row`, `validate_rows`, `_fmt_cell`, `append_rows`, `count_unpaired`, `main` — names/signatures consistent across tasks and the CLI. `_cmd_apply` uses `count_unpaired` (not spec's `measure`) — intentional simplification, defined in Task 5. Cluster dict keys (`prefix`, `volume`, `sample_names`, `klass`, `projected`) consistent between `cluster()`, `classify()` consumer, and the CLI.

**Note:** ICE mode (variant-level rows, extra structured fields) is deliberately deferred — `stub_row`/`validate_rows` guard `fuel != "ev"`. Adding it is a future plan that reuses Tasks 1-2, 6.
