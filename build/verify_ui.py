#!/usr/bin/env python3
"""Self-verification for the static dashboard UI (site/).

Serves site/, drives headless Chromium, captures console/page errors, runs a
few light inline checks, and screenshots key views to tmp/ui-verify/.
Exit 0 = pass, 1 = fail. Read the PNGs afterwards to confirm visual correctness.

Usage:
    python3 build/verify_ui.py [--page index|reference|transmissions] \\
                               [--scenario grid|stav-filter|color-drawer|heat-combo|tools-menu|…] \\
                               [--theme dark|light] [--port N]

Defaults: --page index --scenario grid --theme dark --port 0 (OS-assigned free port).
Screenshots land in tmp/ui-verify/<page>-<scenario>-<theme>.png.
"""
import argparse
import functools
import http.server
import os
import subprocess
import sys
import threading

from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(BASE_DIR, "site")
OUT_DIR = os.path.join(BASE_DIR, "tmp", "ui-verify")
CARS_PARQUET = os.path.join(SITE_DIR, "data", "cars.parquet")

PAGE_FILES = {"index": "index.html", "reference": "reference.html", "transmissions": "transmissions.html"}

# Pages that render an AG Grid (".ag-row" is the universal "did content load"
# signal for those); transmissions.html is a plain HTML table instead.
GRID_PAGES = {"index", "reference"}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def ensure_data():
    if not os.path.exists(CARS_PARQUET):
        print("cars.parquet not found — building…")
        subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "build", "build_data.py")],
            check=True,
        )


def start_server(port):
    handler = functools.partial(_QuietHandler, directory=SITE_DIR)
    httpd = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


# ── Scenarios: each performs interactions, waits for its expected element,
#    and returns a CSS selector to screenshot (None = full viewport). ──

def scenario_grid(page):
    page.wait_for_selector(".ag-row", timeout=15000)
    return None


def scenario_loading(page):
    """Capture the loading overlay (spinner + 'Načítání dat…') that covers the
    grid while cars.parquet is fetched+decoded. The decode is fast enough locally
    that the overlay would vanish before the screenshot, so throttle the parquet
    response by ~3 s and reload, keeping the overlay on screen to capture."""
    import time

    def _slow(route):
        time.sleep(3)
        route.continue_()

    page.route("**/cars.parquet", _slow)
    page.reload(wait_until="commit")
    page.wait_for_selector("#loading-overlay:not(.hidden)", timeout=5000)
    return "#loading-overlay"


def scenario_stav_filter(page):
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Stav')")
    page.wait_for_selector(".set-filter", timeout=5000)
    return ".set-filter"


def scenario_cena_filter(page):
    """Open the Cena (Kč) column filter — the custom RangeFilter renders a dual
    min/max slider (track = the column's good→bad heat gradient) above od/do number
    boxes, instead of AG's default two text inputs."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Cena (Kč)')")
    page.wait_for_selector(".range-filter .th-slider", timeout=5000)
    page.wait_for_timeout(200)
    return ".range-filter"


def scenario_range_filter_ref(page):
    """Reference page: open the Výkon (kW) column filter — the custom RangeFilter
    dual slider + od/do boxes + reset, coupled to the colour-drawer slider."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Výkon (kW)')")
    page.wait_for_selector(".range-filter .th-slider", timeout=5000)
    page.wait_for_timeout(200)
    return ".range-filter"


def scenario_body_filter(page):
    """Open the Karoserie set filter — after the reference-driven + folded body
    vocabulary, the checkboxes must be the clean canonical set (SUV / Hatchback /
    Kombi / Sedan / MPV / Kupé), not the old synonym sprawl (CUV, Terénní, VAN,
    Combi, Sedan/limuzína, Liftback)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Karoserie')")
    page.wait_for_selector(".set-filter", timeout=5000)
    return ".set-filter"


def scenario_summary(page):
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.toggleSummary()")
    page.wait_for_selector("#summary-chart-container canvas", timeout=10000)
    page.wait_for_timeout(500)
    page.evaluate("document.getElementById('summary-chart-container').scrollIntoView({block:'center'})")
    page.wait_for_timeout(200)
    return "#summary-overlay"


def scenario_build_info(page):
    """Open the dataset overview and keep the first card ('Poslední sestavení')
    in view, so the 'Spuštění' label is visible — a push-triggered build must
    read 'Automaticky (push)', not 'Manuální' (only workflow_dispatch is manual)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.toggleSummary()")
    page.wait_for_selector("#summary-body", timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate("document.getElementById('summary-body').scrollTop = 0")
    page.wait_for_timeout(200)
    return "#summary-overlay"


def scenario_sparovano(page):
    """Filter to uncertain+unmatched rows and scroll the match columns into view,
    so the tri-state Spárováno coloring (amber=Nejisté, red=Ne) and the new
    'Skóre shody' confidence column are visible in the screenshot."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate(
        "window.__gridApi.setFilterModel("
        "{ 'Spárováno': { filterType: 'set', values: ['Nejisté', 'Ne'] } });"
        "window.__gridApi.ensureColumnVisible('Skóre shody');"
    )
    page.wait_for_timeout(400)
    return None


def scenario_transmission_type_col(page):
    """Scroll the new derived 'Typ převodovky' column (#26) into view — it
    sits far right of the default grid viewport (after 'Dvouspojková
    převodovka'), so the default 'grid' scenario screenshot never shows it."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.ensureColumnVisible('Typ převodovky');")
    page.wait_for_timeout(400)
    return None


def scenario_overview_matching(page):
    """Open the dataset overview and scroll the 'Párování s referenčními modely'
    card into view, so the tri-state matching table (Spárováno / Nejisté /
    Nespárováno) is captured."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.toggleSummary()")
    page.wait_for_selector("#summary-overlay", timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate(
        "var h=[].slice.call(document.querySelectorAll('#summary-overlay *'))"
        ".find(function(e){return (e.textContent||'').trim()==="
        "'Párování s referenčními modely';});"
        "if(h){h.scrollIntoView({block:'center'});}"
    )
    page.wait_for_timeout(200)
    return "#summary-overlay"


def scenario_data_filters(page):
    """Open the dataset overview and scroll the 'Kritéria výběru dat' card into
    view — the per-source hard filters (mileage, price, year, …) fed from
    cars-meta.json.filters."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.toggleSummary()")
    page.wait_for_selector("#summary-overlay .filters-source", timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate(
        "var h=[].slice.call(document.querySelectorAll('#summary-overlay h3'))"
        ".find(function(e){return (e.textContent||'').trim()==="
        "'Kritéria výběru dat';});"
        "if(h){h.scrollIntoView({block:'start'});}"
    )
    page.wait_for_timeout(200)
    return "#summary-overlay"


def scenario_archive(page):
    """Click 'Načíst archiv' to lazy-load cars-archived.parquet, then filter the
    grid to the loaded removed listings so the archive rows are visible in the
    screenshot. Asserts the fetch+decode+applyTransaction path actually adds rows."""
    page.wait_for_selector(".ag-row", timeout=15000)
    # Button is hidden when there are no archived rows — nothing to verify then.
    if not page.evaluate("(function(){var b=document.getElementById('btn-archive');"
                         "return b && b.style.display !== 'none';})()"):
        return None
    before = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    page.evaluate("window.loadArchive()")
    # Wait until the button flips to the loaded label (fetch + decode complete).
    page.wait_for_function(
        "document.getElementById('btn-archive').textContent.indexOf('načten') >= 0",
        timeout=20000,
    )
    page.evaluate(
        "window.__gridApi.setFilterModel("
        "{ 'Stav': { filterType: 'set', values: ['Odstraněno'] } });"
    )
    page.wait_for_timeout(400)
    after = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if after == 0:
        raise AssertionError("archive loaded but no Odstraněno rows displayed")
    return None


def scenario_date_filter(page):
    """agDateColumnFilter on the ISO-string "Odstraněno dne" column (index only).
    Removal dates live only on Odstraněno rows, so load the archive first, then
    prove the string→Date comparator end-to-end: a far-past `after` shows exactly
    the dated rows (blank live rows fall out via the -1 return), a far-future
    `after` shows none. Then open the popup (browser date picker) for the shot."""
    page.wait_for_selector(".ag-row", timeout=15000)
    has_archive = page.evaluate("(function(){var b=document.getElementById('btn-archive');"
                                "return b && b.style.display !== 'none';})()")
    if has_archive:
        page.evaluate("window.loadArchive()")
        page.wait_for_function(
            "document.getElementById('btn-archive').textContent.indexOf('načten') >= 0",
            timeout=20000)
        page.wait_for_timeout(300)
        dated = page.evaluate(
            "(function(){var n=0;window.__gridApi.forEachNode(function(x){"
            "if(x.data && x.data['Odstraněno dne']) n++;});return n;})()")
        if dated:
            page.evaluate("window.__gridApi.setFilterModel({'Odstraněno dne':"
                          "{filterType:'date',type:'greaterThan',dateFrom:'2000-01-01 00:00:00',dateTo:null}});")
            page.wait_for_timeout(400)
            past = page.evaluate("window.__gridApi.getDisplayedRowCount()")
            if past != dated:
                raise AssertionError("date after far-past: %d shown, expected %d dated rows" % (past, dated))
            page.evaluate("window.__gridApi.setFilterModel({'Odstraněno dne':"
                          "{filterType:'date',type:'greaterThan',dateFrom:'2999-01-01 00:00:00',dateTo:null}});")
            page.wait_for_timeout(400)
            future = page.evaluate("window.__gridApi.getDisplayedRowCount()")
            if future != 0:
                raise AssertionError("date after far-future: %d shown, expected 0" % future)

            # inRange must be INCLUSIVE: a single-day range [X, X] shows the rows
            # dated X (AG's default exclusive bounds would show 0 — the reported bug).
            probe = page.evaluate(
                "(function(){var m={},best=null,bn=0;window.__gridApi.forEachNode(function(x){"
                "var d=x.data&&x.data['Odstraněno dne'];if(d){m[d]=(m[d]||0)+1;if(m[d]>bn){bn=m[d];best=d;}}});"
                "return {day:best,n:bn};})()")
            day, n = probe["day"], probe["n"]
            page.evaluate("(d)=>window.__gridApi.setFilterModel({'Odstraněno dne':"
                          "{filterType:'date',type:'inRange',dateFrom:d+' 00:00:00',dateTo:d+' 00:00:00'}})", day)
            page.wait_for_timeout(400)
            got = page.evaluate("window.__gridApi.getDisplayedRowCount()")
            if got != n:
                raise AssertionError("inRange [%s,%s] shown %d, expected %d (inclusive bounds)" % (day, day, got, n))
            page.evaluate("window.__gridApi.setFilterModel(null)")
            page.wait_for_timeout(200)

        # Applied-filter chip shows the DATE (not a bare ">"/undefined), and the
        # URL fragment carries no redundant time component.
        page.evaluate("window.__gridApi.setFilterModel({'Odstraněno dne':"
                      "{filterType:'date',type:'greaterThan',dateFrom:'2026-07-05 00:00:00',dateTo:null}});")
        page.wait_for_timeout(300)
        chip = page.inner_text("#filter-chips-bar") if page.query_selector("#filter-chips-bar .filter-chip") else ""
        if "undefined" in chip:
            raise AssertionError("filter chip shows 'undefined': %r" % chip)
        if "2026-07-05" not in chip:
            raise AssertionError("filter chip missing the filtered date: %r" % chip)
        h = page.evaluate("location.hash")
        if "00:00:00" in h or "00%3A00" in h:
            raise AssertionError("URL fragment carries redundant time: %s" % h)
        page.evaluate("window.__gridApi.setFilterModel(null)")
        page.wait_for_timeout(150)

    # Masked entry field: digits only, dashes auto-inserted, drives the filter.
    page.evaluate("window.__gridApi.showColumnFilter('Odstraněno dne')")
    page.wait_for_selector(".ag-filter-wrapper", timeout=5000)
    inp = page.query_selector(".ag-filter-wrapper .ag-filter-body input")
    if inp:
        inp.click()
        page.keyboard.type("2026a07b05")  # letters must be dropped, dashes auto-added
        val = inp.input_value()
        if val != "2026-07-05":
            raise AssertionError("masked input did not format digits→yyyy-mm-dd: %r" % val)
        page.wait_for_timeout(300)
        df = page.evaluate("(function(){var m=window.__gridApi.getFilterModel()['Odstraněno dne'];"
                           "return m && m.dateFrom;})()")
        if not df or not str(df).startswith("2026-07-05"):
            raise AssertionError("masked input did not apply the filter: dateFrom=%r" % df)
        # clear via the "Vymazat" reset button → filter cleared, rows return, popup
        # stays open with an empty field for the screenshot
        page.click(".ag-filter-wrapper button")
        page.wait_for_timeout(200)
        if page.evaluate("window.__gridApi.getFilterModel()['Odstraněno dne']"):
            raise AssertionError("reset button did not clear the date filter")
    page.wait_for_timeout(200)
    return ".ag-filter"


def scenario_date_filter_ref(page):
    """agDateColumnFilter on the reference page's ISO-string "Přidáno" column.
    Every reference row carries a date (unlike Odstraněno dne), so a far-past
    `after` shows all rows and a far-future `after` shows none — proving the
    string→local-midnight comparator end-to-end. Then scroll the column into
    view and open the popup for the screenshot."""
    page.wait_for_selector(".ag-row", timeout=15000)
    total = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    page.evaluate("window.__gridApi.setFilterModel({'Přidáno':"
                  "{filterType:'date',type:'greaterThan',dateFrom:'2000-01-01 00:00:00',dateTo:null}});")
    page.wait_for_timeout(400)
    past = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if past != total:
        raise AssertionError("Přidáno after far-past: %d shown, expected %d" % (past, total))
    page.evaluate("window.__gridApi.setFilterModel({'Přidáno':"
                  "{filterType:'date',type:'greaterThan',dateFrom:'2999-01-01 00:00:00',dateTo:null}});")
    page.wait_for_timeout(400)
    future = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if future != 0:
        raise AssertionError("Přidáno after far-future: %d shown, expected 0" % future)

    # inRange must be INCLUSIVE — a single-day range [X,X] shows the rows dated X.
    probe = page.evaluate(
        "(function(){var m={},best=null,bn=0;window.__gridApi.forEachNode(function(x){"
        "var d=x.data&&x.data['Přidáno'];if(d){m[d]=(m[d]||0)+1;if(m[d]>bn){bn=m[d];best=d;}}});"
        "return {day:best,n:bn};})()")
    day, n = probe["day"], probe["n"]
    page.evaluate("(d)=>window.__gridApi.setFilterModel({'Přidáno':"
                  "{filterType:'date',type:'inRange',dateFrom:d+' 00:00:00',dateTo:d+' 00:00:00'}})", day)
    page.wait_for_timeout(400)
    got = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if got != n:
        raise AssertionError("inRange [%s,%s] shown %d, expected %d (inclusive bounds)" % (day, day, got, n))
    page.evaluate("window.__gridApi.setFilterModel(null)")
    page.wait_for_timeout(200)

    page.evaluate("window.__gridApi.ensureColumnVisible('Přidáno')")
    page.evaluate("window.__gridApi.showColumnFilter('Přidáno')")
    page.wait_for_selector(".ag-filter-wrapper", timeout=5000)
    page.wait_for_timeout(300)
    return ".ag-root-wrapper"


def scenario_filter_chips(page):
    """Apply a set filter + a number filter via the grid API (equivalent to a
    user picking values in the filter popups), then confirm the active-filter
    chips bar (#18) renders one chip per filtered column with a visible [×].
    Uses "Typ" and "Výkon (kW)" — the two columns common to both index and
    reference grids — so this scenario runs unmodified on either page."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate(
        "window.__gridApi.setFilterModel({"
        "  'Typ': { filterType: 'set', values: ['Elektrické'] },"
        "  'Výkon (kW)': { filterType: 'number', type: 'greaterThan', filter: 100 }"
        "});"
    )
    page.wait_for_selector("#filter-chips-bar .filter-chip", timeout=5000)
    page.wait_for_timeout(200)
    return "#filter-chips-bar"


def scenario_pairing_gap(page):
    """Click the #14 unpaired-listings shortcut button and confirm it toggles
    the Spárováno set filter to {Ne, Nejisté} (merging, not clobbering, an
    existing filter), the chips bar reflects it, and the grid row count drops.
    Clicking again must clear just that filter (toggle off)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    # Pre-set an unrelated filter to prove the toggle merges rather than clobbers.
    page.evaluate(
        "window.__gridApi.setFilterModel({"
        "  'Typ': { filterType: 'set', values: ['Spalovací'] }"
        "});"
    )
    page.wait_for_timeout(200)
    before = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    page.wait_for_selector("#btn-pairing-gap", state="visible", timeout=5000)
    page.click("#btn-pairing-gap")
    page.wait_for_selector("#filter-chips-bar .filter-chip", timeout=5000)
    page.wait_for_timeout(200)
    after = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    model = page.evaluate("window.__gridApi.getFilterModel()")
    if "Spárováno" not in model:
        raise AssertionError("clicking the shortcut did not apply the Spárováno filter")
    if "Typ" not in model:
        raise AssertionError("the pre-existing Typ filter was clobbered")
    if after >= before:
        raise AssertionError("row count did not shrink after applying the unpaired filter")
    is_active = page.evaluate(
        "document.getElementById('btn-pairing-gap').classList.contains('active')"
    )
    if not is_active:
        raise AssertionError("shortcut button did not reflect active state")
    # Toggle off and confirm the Spárováno filter (only) is cleared.
    page.click("#btn-pairing-gap")
    page.wait_for_timeout(200)
    model_after_toggle_off = page.evaluate("window.__gridApi.getFilterModel()")
    if "Spárováno" in model_after_toggle_off:
        raise AssertionError("second click did not clear the Spárováno filter")
    if "Typ" not in model_after_toggle_off:
        raise AssertionError("second click clobbered the unrelated Typ filter")
    # Re-apply for the screenshot so the filtered state (button + chips) is visible.
    page.click("#btn-pairing-gap")
    page.wait_for_selector("#filter-chips-bar .filter-chip", timeout=5000)
    page.wait_for_timeout(200)
    return None


def scenario_missing_specs(page):
    """Click the reference page's "Neúplné: N / M" toggle (#19) and confirm the
    grid's external filter actually narrows the rows to ones carrying a
    missing-spec badge (⚠) in the first column. Uses getDisplayedRowCount()
    rather than counting ".ag-row" — the grid virtualizes rows, so the DOM row
    count is capped at whatever fits the viewport and doesn't shrink with the
    total until it drops below that cap."""
    page.wait_for_selector(".ag-row", timeout=15000)
    before = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    page.click("#btn-incomplete")
    page.wait_for_timeout(300)
    after = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if not (after < before):
        raise AssertionError(f"incomplete toggle did not reduce rows: before={before} after={after}")
    if after == 0:
        raise AssertionError("incomplete toggle matched zero rows")
    if "active" not in (page.get_attribute("#btn-incomplete", "class") or ""):
        raise AssertionError("toggle button did not get 'active' class")
    badges = page.locator(".missing-badge").all_inner_texts()
    if not badges:
        raise AssertionError("no missing-spec badges rendered after filtering to incomplete rows")
    if not all("⚠" in b for b in badges):
        raise AssertionError(f"visible badges missing the warning glyph: {badges[:10]}")
    return None


def scenario_transmissions(page):
    """transmissions.html (#28) has no AG Grid — confirm the static catalogue
    table rendered (all seed rows present) and the live per-type counts were
    filled in from cars.parquet (still "–"/"n/a" placeholders would mean the
    hyparquet fetch/decode silently failed)."""
    page.wait_for_selector(".transmission-table tbody tr", timeout=15000)
    rows = page.locator(".transmission-table tbody tr").count()
    if rows < 5:
        raise AssertionError(f"expected the full seed catalogue, got {rows} rows")
    page.wait_for_function(
        "document.querySelector('.trans-count[data-count-key=\"manual\"]')"
        ".textContent.indexOf('vozů') >= 0",
        timeout=15000,
    )
    return ".transmission-table-wrap"


def scenario_verze_ev(page):
    """Filter to a splittable EV nameplate (BYD Dolphin Surf) and reveal the
    'Verze' column, so the Extra-extracted editions (Active/Boost/Comfort) are
    visible in the grid — the default 'grid' scenario scrolls Verze off-screen."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate(
        "window.__gridApi.setFilterModel("
        "{ 'Model': { filterType: 'text', type: 'contains', filter: 'Dolphin Surf' } });"
        "window.__gridApi.ensureColumnVisible('Verze');"
    )
    page.wait_for_timeout(400)
    return None


def _codec_battery(page):
    """Round-trip filters + thresholds through window.UrlState and assert enc()
    never emits a raw delimiter. Shared by the index + reference url-state checks
    (window.UrlState is loaded on both pages)."""
    import json

    filter_cases = [
        {"Model": {"filterType": "text", "type": "contains", "filter": "ceed"}},
        {"Extra": {"filterType": "text", "type": "notContains", "filter": "a,b;c~d-e_f*g|h=i"}},
        {"Typ": {"filterType": "set", "values": ["Elektrické", "Spalovací"]}},
        {"Stav": {"filterType": "set", "values": ["Dostupný", None]}},
        {"Cena (Kč)": {"filterType": "number", "type": "inRange", "filter": 100000, "filterTo": 750000}},
        {"Objem motoru": {"filterType": "number", "type": "equals", "filter": 1.5}},
        {"Model": {"filterType": "text", "type": "blank"}},
        {"Cena (Kč)": {"filterType": "number", "operator": "OR", "conditions": [
            {"filterType": "number", "type": "lessThan", "filter": 50000},
            {"filterType": "number", "type": "greaterThan", "filter": 700000}]}},
        {"Odstraněno dne": {"filterType": "date", "type": "greaterThan", "dateFrom": "2026-07-01 00:00:00", "dateTo": None}},
        {"Odstraněno dne": {"filterType": "date", "type": "inRange", "dateFrom": "2026-06-01 00:00:00", "dateTo": "2026-07-11 00:00:00"}},
        {"Odstraněno dne": {"filterType": "date", "type": "notBlank"}},
    ]
    for i, case in enumerate(filter_cases):
        back = page.evaluate("(m)=>window.UrlState.decFilters(window.UrlState.encFilters(m))", case)
        if back != case:
            raise AssertionError(f"filter round-trip {i} mismatch: in={json.dumps(case,ensure_ascii=False)} out={json.dumps(back,ensure_ascii=False)}")

    # date filters must not leak the midnight time into the URL (stripped on
    # encode, restored on decode — the round-trip above still holds)
    enc_date = page.evaluate("(m)=>window.UrlState.encFilters(m)", filter_cases[8])
    if "00:00:00" in enc_date or "00%3A00" in enc_date:
        raise AssertionError(f"date filter encoded with redundant time: {enc_date}")

    for case in [{"Cena (Kč)": {"min": 12345}}, {"Rok výroby": {"max": 2020}},
                 {"Cena (Kč)": {"min": 100000, "max": 750000}, "Výkon (kW)": {"min": 90}}]:
        back = page.evaluate("(m)=>window.UrlState.decThresholds(window.UrlState.encThresholds(m))", case)
        if back != case:
            raise AssertionError(f"threshold round-trip mismatch: out={json.dumps(back,ensure_ascii=False)}")

    leak = page.evaluate(
        "()=>{var bad=[];['a;b','a,b','a~b','a-b','a_b','a|b','a=b','a*b','Cena (Kč)','Škoda'].forEach("
        "function(s){var e=window.UrlState.enc(s);if(/[;,~*_=|-]/.test(e))bad.push(s+'->'+e);"
        "if(window.UrlState.dec(e)!==s)bad.push('rt '+s+'->'+e);});return bad;}")
    if leak:
        raise AssertionError(f"enc() delimiter/round-trip leak: {leak}")


def scenario_url_state(page):
    """Exercise the shared URL-state codec on index.html end-to-end:

    1. round-trip a battery of filter + threshold models through window.UrlState
       (delimiters-in-value, null set value, inRange, combined AND/OR);
    2. live filter → URL gains #f= (no legacy ?filters=); reload restores it;
    3. column layout (sort/reorder/width/pin) persists to localStorage and is
       restored on reload, but MUST NOT appear in the URL (no #c=);
    4. colour threshold → #t=; reload restores it;
    5. legacy ?filters=<base64> link → applied AND auto-migrated to #f=.
    """
    import base64
    import json

    page.wait_for_selector(".ag-row", timeout=15000)
    _codec_battery(page)

    # live filter → # fragment (no legacy query)
    page.evaluate("window.__gridApi.setFilterModel({'Model':{filterType:'text',type:'contains',filter:'ceed'}})")
    page.wait_for_timeout(200)
    u = page.url
    if "#f=" not in u:
        raise AssertionError(f"live filter: no #f= in URL: {u}")
    if "filters=" in u.split("#")[0]:
        raise AssertionError(f"live filter: legacy ?filters= present: {u}")
    page.goto(u, wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    if page.evaluate("window.__gridApi.getFilterModel().Model.filter") != "ceed":
        raise AssertionError("live reload: filter not restored from #f=")

    # column layout: persists to localStorage, restored on reload, NEVER in the URL
    page.evaluate(
        "window.__gridApi.applyColumnState({"
        "  state:[{colId:'Palivo'},{colId:'Cena (Kč)',sort:'desc'},{colId:'Model',width:300},{colId:'Výkon (kW)',pinned:'right'}],"
        "  applyOrder:false});"
        "window.__gridApi.moveColumns(['Palivo'],0);")
    page.wait_for_timeout(200)
    ucol = page.url
    if "c=" in ucol.split("#")[-1]:
        raise AssertionError(f"column layout leaked into URL fragment: {ucol}")
    if not page.evaluate("!!localStorage.getItem('carCompareColState')"):
        raise AssertionError("column layout not persisted to localStorage")
    page.goto(ucol, wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    cs = page.evaluate("window.__gridApi.getColumnState()")
    order = [c["colId"] for c in cs]
    if order[0] != "Palivo":
        raise AssertionError(f"cols reload: reorder not restored, first={order[0]}")
    if abs(next(c for c in cs if c["colId"] == "Model")["width"] - 300) > 2:
        raise AssertionError("cols reload: width not restored")
    if next(c for c in cs if c["colId"] == "Výkon (kW)")["pinned"] != "right":
        raise AssertionError("cols reload: pin not restored")
    if next(c for c in cs if c["colId"] == "Cena (Kč)")["sort"] != "desc":
        raise AssertionError("cols reload: sort not restored")

    # reset the layout so it doesn't bleed into the threshold reloads below
    page.evaluate("window.resetColOrder()")

    # live threshold → #t=, restored on reload. Drive the REAL colour-drawer path:
    # open the drawer (renders #threshold-inputs), set a min box and dispatch its
    # `input` event so commitRange() runs. NB: window.saveThresholds() no longer
    # parses the DOM (state flows through commitRange since the coupling refactor),
    # so setting a box value + calling it is a no-op — hence the input event.
    page.evaluate("window.__gridApi.setFilterModel(null)")
    page.evaluate("window.openColorSettings()")
    page.wait_for_selector("#threshold-inputs .threshold-row .th-min", timeout=5000)
    page.evaluate(
        "(function(){"
        "  var mn = document.querySelector('#threshold-inputs .threshold-row .th-min');"
        "  mn.value = '55555';"
        "  mn.dispatchEvent(new Event('input', {bubbles:true}));"
        "})()"
    )
    page.wait_for_timeout(500)  # commitRange debounces persist + writeHash by 220 ms
    u3 = page.url
    if "t=" not in u3.split("#")[-1]:
        raise AssertionError(f"live threshold: no t= in fragment: {u3}")
    page.goto(u3, wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    if "55555" not in (page.evaluate("localStorage.getItem('carCompareThresholds')") or ""):
        raise AssertionError("live reload: threshold not restored from #t=")

    # legacy ?filters=<base64> link → applied + migrated to #
    page.evaluate("localStorage.clear()")
    legacy_b64 = base64.b64encode(json.dumps(
        {"Model": {"filterType": "text", "type": "contains", "filter": "enyaq"}}).encode()).decode()
    base = page.url.split("#")[0].split("?")[0]
    page.goto(f"{base}?filters={legacy_b64}", wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    page.wait_for_timeout(300)
    if page.evaluate("window.__gridApi.getFilterModel().Model.filter") != "enyaq":
        raise AssertionError("legacy: base64 filter not applied")
    lu = page.url
    if "#f=" not in lu or "filters=" in lu.split("#")[0]:
        raise AssertionError(f"legacy: not migrated to #/old query not stripped: {lu}")
    page.wait_for_timeout(200)
    return None


def scenario_url_state_ref(page):
    """reference.html shares the codec but has no colour thresholds. Verify:
    codec battery; live filter → #f= (no legacy query); reload restores it;
    a sort persists to localStorage but NOT the URL; legacy ?filters= migrates."""
    import base64
    import json

    page.wait_for_selector(".ag-row", timeout=15000)
    _codec_battery(page)

    page.evaluate("window.__gridApi.setFilterModel({'Model auta':{filterType:'text',type:'contains',filter:'octavia'}})")
    page.wait_for_timeout(200)
    u = page.url
    if "#f=" not in u or "filters=" in u.split("#")[0]:
        raise AssertionError(f"ref live filter: bad URL: {u}")
    page.goto(u, wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    if page.evaluate("window.__gridApi.getFilterModel()['Model auta'].filter") != "octavia":
        raise AssertionError("ref reload: filter not restored from #f=")

    # sort → localStorage only, not URL
    page.evaluate("window.__gridApi.applyColumnState({state:[{colId:'Výkon (kW)',sort:'desc'}]})")
    page.wait_for_timeout(200)
    if "c=" in page.url.split("#")[-1]:
        raise AssertionError(f"ref: column layout leaked into URL: {page.url}")
    if not page.evaluate("!!localStorage.getItem('refCompareColState')"):
        raise AssertionError("ref: column layout not persisted to localStorage")

    # legacy ?filters= migrates
    page.evaluate("localStorage.clear()")
    legacy_b64 = base64.b64encode(json.dumps(
        {"Model auta": {"filterType": "text", "type": "contains", "filter": "enyaq"}}).encode()).decode()
    base = page.url.split("#")[0].split("?")[0]
    page.goto(f"{base}?filters={legacy_b64}", wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    page.wait_for_timeout(300)
    if page.evaluate("window.__gridApi.getFilterModel()['Model auta'].filter") != "enyaq":
        raise AssertionError("ref legacy: base64 filter not applied")
    if "#f=" not in page.url or "filters=" in page.url.split("#")[0]:
        raise AssertionError(f"ref legacy: not migrated to #: {page.url}")
    return None


def scenario_color_drawer(page):
    """Open the colour-settings drawer (gear menu → 'Nastavení barev…') and confirm
    it renders the heat-map choice chips: #palette-choices and #style-choices must
    both be populated with .choice buttons, and clicking a non-default palette chip
    must move the .active state onto it (the setHeatMode wiring behind the chips)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.openColorSettings()")
    page.wait_for_selector("#palette-choices .choice", timeout=5000)
    if page.evaluate("document.querySelectorAll('#style-choices .choice').length") == 0:
        raise AssertionError("#style-choices rendered no .choice buttons")
    # clicking the 2nd palette chip (a non-default one) must make it the active chip
    page.locator("#palette-choices .choice").nth(1).click()
    page.wait_for_timeout(200)
    active_idx = page.evaluate(
        "[].findIndex.call(document.querySelectorAll('#palette-choices .choice'),"
        "function(c){return c.classList.contains('active');})"
    )
    if active_idx != 1:
        raise AssertionError(
            f"palette click did not move .active onto the clicked chip (active idx={active_idx})"
        )
    return "#settings-panel"


def scenario_heat_combo(page):
    """Switch the heat-map colouring to the blue–red 'combo' (bar + tint) mode via
    the public setHeatMode API and confirm it applies without error — the grid
    re-tints in place (background only, no cellRenderer). Asserts the mode stuck."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.setHeatMode('bluered','combo')")
    page.wait_for_timeout(300)
    mode = page.evaluate("window.getHeatMode()")
    if mode.get("palette") != "bluered" or mode.get("style") != "combo":
        raise AssertionError(f"heat mode not applied: {mode}")
    return None


def scenario_tools_menu(page):
    """Open the gear/tools popup menu (colour settings + theme toggle) and confirm
    it becomes visible (drops the .hidden class)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.toggleToolsMenu()")
    page.wait_for_selector("#tools-menu:not(.hidden)", timeout=5000)
    return "#tools-menu"


def scenario_threshold_filter_clear(page):
    """Regression: a colour-only threshold (set in Nastavení barev, no active row
    filter) must NOT resurrect as a filter after reload. The threshold↔filter
    coupling stores filtering in the filter store (#f= / carCompareFilters) and
    colour in the threshold store (#t= / carCompareThresholds); load-time
    re-derivation of a filter from every threshold (the deleted activateRangeFilters)
    used to bring back filters the user had cleared via the chip ×.

    Repro (per TASKS.md, verified 2026-07-13): colour threshold in localStorage +
    empty filter store + bare reload → grid must show the FULL, unfiltered row set,
    while the colour threshold survives (it is an appearance pref)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    full = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if not full or full < 10:
        raise AssertionError(f"unexpected baseline row count: {full}")

    # Seed exactly the task's repro state: a colour-only threshold, no filter model.
    page.evaluate(
        "(function(){"
        "  localStorage.setItem('carCompareThresholds',"
        "    JSON.stringify({'Cena (Kč)':{min:100000,max:300000}}));"
        "  localStorage.removeItem('carCompareFilters');"
        "})()"
    )

    # Bare reload — no #f= / #t= fragment, no ?filters= query.
    base = page.url.split("#")[0].split("?")[0]
    page.goto(base, wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    page.wait_for_timeout(300)

    fm = page.evaluate("window.__gridApi.getFilterModel() || {}")
    if "Cena (Kč)" in fm:
        raise AssertionError(f"colour-only threshold resurrected as a filter on reload: {fm}")
    after = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if after != full:
        raise AssertionError(f"grid filtered after bare reload: {after} != full {full}")

    # The colour threshold itself must persist (it still tints the column).
    th = page.evaluate("localStorage.getItem('carCompareThresholds')") or ""
    if "100000" not in th:
        raise AssertionError("colour threshold lost on reload (should persist for tinting)")
    return None


def _set_price_view(page, view):
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("(v) => window.setPriceView(v)", view)
    page.wait_for_timeout(300)


def scenario_price_compact(page):
    """Reference 'Cena na trhu' column in the default Kompaktní view — text
    od–medián–do + sparkline, plus the Nabídek count column with its bar."""
    _set_price_view(page, "compact")
    page.wait_for_selector(".rc-spark", timeout=5000)
    return None


def scenario_price_boxplot(page):
    """Reference 'Cena na trhu' in Box-plot view — per-row min/quartile/median/max
    box on the shared 100–800 tis Kč axis (taller uniform rows)."""
    _set_price_view(page, "boxplot")
    page.wait_for_selector(".rc-band", timeout=5000)
    return None


def scenario_price_histogram(page):
    """Reference 'Cena na trhu' in Histogram view — inline per-row price distribution
    (14 bins, shared axis, median tick); tallest uniform row height."""
    _set_price_view(page, "histogram")
    page.wait_for_selector(".rc-bars", timeout=5000)
    return None


def scenario_price_popup(page):
    """Click-detail popup for a paired reference model — big histogram + od/medián/do
    stats + cheapest/dearest listing links. Opened via the test hook."""
    page.wait_for_selector(".ag-row", timeout=15000)
    ok = page.evaluate("() => window.__openPricePopup('Škoda Octavia 2.0 TDI')")
    if not ok:
        # Fall back to the busiest model if that exact entry isn't in this build.
        page.evaluate(
            "() => { let best=null; window.__gridApi.forEachNode(n=>{"
            "  if(n.data && n.data['Nabídek'] && (!best || n.data['Nabídek']>best['Nabídek'])) best=n.data;});"
            "  if(best) window.__openPricePopup(best['Model auta']); }"
        )
    page.wait_for_selector("#price-popup:not(.hidden)", timeout=5000)
    page.wait_for_timeout(200)
    return "#price-popup"


SCENARIOS = {
    "grid": scenario_grid,
    "price-compact": scenario_price_compact,
    "price-boxplot": scenario_price_boxplot,
    "price-histogram": scenario_price_histogram,
    "price-popup": scenario_price_popup,
    "threshold-filter-clear": scenario_threshold_filter_clear,
    "color-drawer": scenario_color_drawer,
    "heat-combo": scenario_heat_combo,
    "tools-menu": scenario_tools_menu,
    "url-state": scenario_url_state,
    "url-state-ref": scenario_url_state_ref,
    "loading": scenario_loading,
    "verze-ev": scenario_verze_ev,
    "stav-filter": scenario_stav_filter,
    "cena-filter": scenario_cena_filter,
    "range-filter-ref": scenario_range_filter_ref,
    "body-filter": scenario_body_filter,
    "summary": scenario_summary,
    "build-info": scenario_build_info,
    "sparovano": scenario_sparovano,
    "transmission-type-col": scenario_transmission_type_col,
    "overview-matching": scenario_overview_matching,
    "data-filters": scenario_data_filters,
    "archive": scenario_archive,
    "date-filter": scenario_date_filter,
    "date-filter-ref": scenario_date_filter_ref,
    "filter-chips": scenario_filter_chips,
    "pairing-gap": scenario_pairing_gap,
    "missing-specs": scenario_missing_specs,
    "transmissions": scenario_transmissions,
}


def check_cd_format(page):
    """Assert the Cd column renders as a bare integer percent: the '%' sign lives
    in the header ('… (%)'), cells are plain integers (no '%', no decimals).

    This guards the exact regression that a green screenshot + exit 0 missed once:
    a per-page valueFormatter still appending ' %' to each cell. Column-virtualised
    grids only render on-screen columns, so scroll Cd into view via the grid API
    first, otherwise its cells are absent from the DOM and silently un-checked.
    """
    try:
        page.evaluate("window.__gridApi && window.__gridApi.ensureColumnVisible('Cd')")
        page.wait_for_timeout(200)
    except Exception:
        pass
    res = page.evaluate(
        "() => {"
        "  var cells = Array.prototype.slice.call("
        "    document.querySelectorAll('.ag-cell[col-id=\"Cd\"]'))"
        "    .map(function(c){return (c.textContent||'').trim();})"
        "    .filter(function(s){return s.length;});"
        "  var h = document.querySelector('.ag-header-cell[col-id=\"Cd\"]');"
        "  return { cells: cells.slice(0, 80), header: h ? (h.textContent||'') : '' };"
        "}"
    )
    problems = []
    if "%" not in res["header"]:
        problems.append("Cd header missing '%' sign: " + repr(res["header"]))
    if not res["cells"]:
        problems.append("Cd column has no rendered cells (could not verify format)")
    for txt in res["cells"]:
        if "%" in txt:
            problems.append("Cd cell still contains '%': " + repr(txt))
            break
        if not txt.lstrip("-").isdigit():
            problems.append("Cd cell is not an integer: " + repr(txt))
            break
    return problems


def main():
    ap = argparse.ArgumentParser(description="Verify dashboard UI in a headless browser.")
    ap.add_argument("--page", choices=PAGE_FILES, default="index")
    ap.add_argument("--scenario", choices=SCENARIOS, default="grid")
    ap.add_argument("--theme", choices=("dark", "light"), default="dark")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    ensure_data()
    os.makedirs(OUT_DIR, exist_ok=True)
    httpd, port = start_server(args.port)
    url = f"http://127.0.0.1:{port}/{PAGE_FILES[args.page]}"
    shot_path = os.path.join(OUT_DIR, f"{args.page}-{args.scenario}-{args.theme}.png")

    errors = []
    failures = []
    row_count = 0

    def on_console(msg):
        if msg.type == "error" and "favicon" not in msg.text.lower():
            errors.append("console: " + msg.text)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # Seed the theme into localStorage BEFORE any page script runs: the pages
            # read carCompareTheme on load (defaulting to dark), so an init script on
            # the context makes the page render in the requested theme from the first
            # paint. Init scripts re-run on every navigation, so scenarios that reload
            # (or call localStorage.clear()) keep the requested theme.
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            context.add_init_script(
                "try{localStorage.setItem('carCompareTheme','%s');}catch(e){}" % args.theme
            )
            page = context.new_page()
            page.on("console", on_console)
            page.on("pageerror", lambda exc: errors.append("pageerror: " + str(exc)))

            print(f"Loading {url} (scenario: {args.scenario})…")
            page.goto(url, wait_until="load", timeout=30000)

            try:
                target = SCENARIOS[args.scenario](page)
            except Exception as e:
                failures.append(f"scenario '{args.scenario}' failed: {e}")
                target = None

            if args.scenario == "loading":
                # 'loading' deliberately screenshots the pre-data overlay (parquet
                # fetch throttled), so the grid has no rows yet — skip row checks.
                pass
            elif args.page in GRID_PAGES:
                row_count = page.locator(".ag-row").count()
                if row_count == 0:
                    failures.append("no grid rows rendered (.ag-row count == 0)")

                if args.scenario == "grid":
                    failures.extend(check_cd_format(page))
            else:
                row_count = page.locator(".transmission-table tbody tr").count()
                if row_count == 0:
                    failures.append("no table rows rendered (transmission-table has 0 rows)")

            if target:
                page.locator(target).screenshot(path=shot_path)
            else:
                page.screenshot(path=shot_path, full_page=False)

            browser.close()
    finally:
        httpd.shutdown()

    if errors:
        failures.append(f"{len(errors)} console/page error(s)")

    print(f"\nrows rendered: {row_count}")
    print(f"screenshot:    {shot_path}")
    if errors:
        print("errors:")
        for e in errors:
            print("  - " + e)

    if failures:
        print("\nFAIL:")
        for f in failures:
            print("  - " + f)
        sys.exit(1)

    print("\nPASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
