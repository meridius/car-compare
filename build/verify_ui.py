#!/usr/bin/env python3
"""Self-verification for the static dashboard UI (site/).

Serves site/, drives headless Chromium, captures console/page errors, runs a
few light inline checks, and screenshots key views to tmp/ui-verify/.
Exit 0 = pass, 1 = fail. Read the PNGs afterwards to confirm visual correctness.

Usage:
    python3 build/verify_ui.py [--page index|reference|transmissions] \\
                               [--scenario grid|stav-filter|color-drawer|heat-combo|tools-menu|
                                           hist-track|hist-modes|hist-zoom|blank-filter|
                                           colour-only|theme-cards|…] \\
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
    """Open the Cena (Kč) column filter — the custom RangeFilter renders the
    distribution track (canvas histogram + count axis + dual thumbs), od/do boxes,
    the blank-cell switch and the colour-only checkbox."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Cena (Kč)')")
    page.wait_for_selector(".range-filter .ht-track canvas", timeout=5000)
    page.wait_for_timeout(300)
    return ".range-filter"


def scenario_range_filter_ref(page):
    """Reference page: open the Výkon (kW) column filter — the custom RangeFilter
    od/do boxes + reset + track. Accepts either track flavour so it spans the
    reference page's migration to the canvas distribution track: `.th-slider` is the
    old flat gradient slider, `.ht-track canvas` the histogram one (see hist-track)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Výkon (kW)')")
    page.wait_for_selector(".range-filter .th-slider, .range-filter .ht-track canvas", timeout=5000)
    page.wait_for_timeout(300)
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


def scenario_service_cost_col(page):
    """Scroll the estimated 'Servis (Kč/rok)' column (#23) into view — it sits
    right of the default grid viewport (after 'Spolehlivost')."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.ensureColumnVisible('Servis (Kč/rok)');")
    page.wait_for_timeout(400)
    return None


def scenario_service_cost(page):
    """Open the dataset overview and scroll the 'Servisní náklady (odhad)' card
    (#23) into view — methodology, factor table, clamp counts, source links."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.toggleSummary()")
    page.wait_for_selector("#summary-overlay", timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate(
        "var h=[].slice.call(document.querySelectorAll('#summary-overlay h3'))"
        ".find(function(e){return (e.textContent||'').trim()==="
        "'Servisní náklady (odhad)';});"
        "if(h){h.scrollIntoView({block:'start'});}"
    )
    page.wait_for_timeout(200)
    return "#summary-overlay"


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
    # An open range bound is null in the model — the chip must not print it raw.
    txt = page.inner_text("#filter-chips-bar")
    for junk in ("null", "undefined"):
        if junk in txt:
            raise AssertionError("chip text leaks %r: %r" % (junk, txt))
    return "#filter-chips-bar"


def scenario_chip_click(page):
    """Clicking a filter chip's label must open that column's filter popup — the
    same popup the column-header filter icon opens (the [×] still just removes the
    filter). Also covers the hidden-column case: a popup can't anchor to a header
    that isn't rendered, so the chip unhides the column first.
    Uses "Typ" (present on both index and reference grids)."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate(
        "window.__gridApi.setFilterModel({"
        "  'Typ': { filterType: 'set', values: ['Elektrické'] }"
        "});"
    )
    page.wait_for_selector("#filter-chips-bar .filter-chip", timeout=5000)

    # Hidden column: the chip must bring it back before opening the popup.
    page.evaluate("window.__gridApi.setColumnsVisible(['Typ'], false)")
    page.wait_for_timeout(150)
    page.click("#filter-chips-bar .filter-chip .filter-chip-label")
    page.wait_for_selector(".ag-popup .ag-filter", timeout=5000)
    page.wait_for_timeout(300)

    visible = page.evaluate("window.__gridApi.getColumn('Typ').isVisible()")
    if not visible:
        raise AssertionError("chip click did not unhide the hidden filtered column")
    # The popup must be the *Typ* filter, not some other column's.
    opened = page.evaluate(
        "() => {"
        "  var p = document.querySelector('.ag-popup .ag-filter');"
        "  if (!p) return '';"
        "  var w = p.closest('.ag-popup');"
        "  var t = (w && w.textContent) || '';"
        "  return t;"
        "}"
    )
    if "Elektrické" not in opened:
        raise AssertionError("opened popup does not look like the Typ set filter: %r" % opened[:120])
    # Full viewport: the chips bar sits above the grid, outside .ag-root-wrapper.
    return None


def scenario_multi_condition(page):
    """AG caps combined AND/OR filters at 2 conditions by default; we raise it to
    MAX_FILTER_CONDITIONS (5) on every built-in filter (defaultColDef +
    DATE_FILTER_PARAMS). Applying a 4-condition model must survive the round-trip
    through the grid (at the default cap AG drops the extras), show up whole in the
    chip, and round-trip through the URL codec."""
    page.wait_for_selector(".ag-row", timeout=15000)
    field = page.evaluate(
        "() => ['Model','Model auta'].filter(function(f){return !!window.__gridApi.getColumn(f);})[0] || ''"
    )
    if not field:
        raise AssertionError("no text-filter column found (expected Model / Model auta)")

    words = ["Golf", "Octavia", "Ceed", "Kodiaq"]
    model = {
        field: {
            "filterType": "text",
            "operator": "OR",
            "conditions": [{"filterType": "text", "type": "contains", "filter": w} for w in words],
        }
    }
    page.evaluate("(m)=>window.__gridApi.setFilterModel(m)", model)
    page.wait_for_selector("#filter-chips-bar .filter-chip", timeout=5000)
    page.wait_for_timeout(200)

    back = page.evaluate("()=>window.__gridApi.getFilterModel()")
    conds = (back.get(field) or {}).get("conditions") or []
    if len(conds) != len(words):
        raise AssertionError(
            "grid kept %d of %d conditions — maxNumConditions not raised (%r)"
            % (len(conds), len(words), back.get(field))
        )

    chip = page.inner_text("#filter-chips-bar .filter-chip .filter-chip-label")
    for w in words:
        if w not in chip:
            raise AssertionError("chip text is missing condition %r: %r" % (w, chip))

    rt = page.evaluate("(m)=>window.UrlState.decFilters(window.UrlState.encFilters(m))", model)
    if rt != model:
        raise AssertionError("4-condition filter did not survive the URL codec: %r" % rt)

    # Screenshot the popup itself: it must offer more than two condition slots.
    page.evaluate("(f)=>window.__gridApi.ensureColumnVisible(f)", field)
    page.evaluate("(f)=>window.__gridApi.showColumnFilter(f)", field)
    page.wait_for_selector(".ag-popup .ag-filter", timeout=5000)
    page.wait_for_timeout(300)
    slots = page.evaluate(
        "()=>document.querySelectorAll('.ag-popup .ag-filter .ag-filter-body-wrapper .ag-filter-condition, "
        ".ag-popup .ag-filter .ag-filter-body').length"
    )
    if slots < 4:
        raise AssertionError("filter popup rendered %d condition bodies, expected ≥ 4" % slots)

    # AG joins all conditions with ONE operator but renders a radio pair per join;
    # the 2nd..Nth are disabled mirrors of the first (clicking them does nothing).
    # They must be hidden, leaving exactly one live AND/OR control.
    ops = page.evaluate(
        "()=>Array.prototype.map.call("
        "  document.querySelectorAll('.ag-popup .ag-filter .ag-filter-condition-operator'),"
        "  function(el){ var i = el.querySelector('input');"
        "    return { shown: el.offsetParent !== null, disabled: !!(i && i.disabled) }; })"
    )
    shown = [o for o in ops if o["shown"]]
    if any(o["disabled"] for o in shown):
        raise AssertionError(
            "a disabled (dead) AND/OR radio is visible — %d of %d operator controls shown"
            % (len(shown), len(ops))
        )
    if len(shown) != 2:  # one pair = A zároveň + Nebo
        raise AssertionError("expected exactly one live AND/OR pair, found %d shown controls" % len(shown))
    return ".ag-root-wrapper"


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

    # live threshold → #t=, restored on reload, and it still COLOURS after the
    # reload. Drive the real editor: the per-column ranges left the Nastavení-barev
    # drawer (they duplicated the column filter), so the od box now lives in the
    # numeric column-filter popup. Dispatch its `input` event so commitRange() runs —
    # window.saveThresholds() no longer parses the DOM, it only re-persists state.
    #
    # The threshold is set as COLOUR-ONLY ("Jen barvit, nefiltrovat"): the grid then
    # keeps every row, so the same cells stay rendered and their heat backgrounds are
    # directly comparable before / after / across the reload. Cell colour is a pure
    # function of value + threshold, so that map is what proves #t= still tints —
    # not merely that the page loaded.
    page.evaluate("window.__gridApi.setFilterModel(null)")
    page.wait_for_timeout(200)
    th_field = _pick_field(page, _RANGE_FIELDS)
    page.evaluate("(f)=>window.__gridApi.ensureColumnVisible(f)", th_field)
    page.wait_for_timeout(250)
    plain_bg = _cell_backgrounds(page, th_field)
    _open_range_filter(page, th_field)
    page.evaluate(
        "()=>{var c=document.querySelector('.range-filter .rf-check input');"
        " c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));}"
    )
    page.evaluate(
        "()=>{var mn=document.querySelector('.range-filter .th-min');"
        " mn.value='55555'; mn.dispatchEvent(new Event('input',{bubbles:true}));}"
    )
    page.wait_for_timeout(600)  # commitRange debounces persist + writeHash by 220 ms
    tinted_bg = _cell_backgrounds(page, th_field)
    _, moved = _shared_diff(plain_bg, tinted_bg)
    if not moved:
        raise AssertionError("threshold did not change any cell's heat colour before the reload")
    u3 = page.url
    if "t=" not in u3.split("#")[-1]:
        raise AssertionError(f"live threshold: no t= in fragment: {u3}")

    page.goto(u3, wait_until="load", timeout=30000)
    page.wait_for_selector(".ag-row", timeout=15000)
    if "55555" not in (page.evaluate("localStorage.getItem('carCompareThresholds')") or ""):
        raise AssertionError("live reload: threshold not restored from #t=")
    page.evaluate("(f)=>window.__gridApi.ensureColumnVisible(f)", th_field)
    page.wait_for_timeout(300)
    reloaded_bg = _cell_backgrounds(page, th_field)
    keys, differ = _shared_diff(tinted_bg, reloaded_bg)
    if len(keys) < 5:
        raise AssertionError(f"only {len(keys)} comparable cells after the reload — cannot check the tint")
    if differ:
        raise AssertionError(
            "the #t= threshold no longer colours the same way after the reload "
            f"({len(differ)} of {len(keys)} cells differ, e.g. {differ[0]!r})"
        )

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
    # Re-open before screenshotting: clicking a choice chip currently CLOSES the
    # drawer (renderHeatModeChoices detaches the clicked node, so the document
    # "click outside closes" listener sees a detached target — asserted, with the
    # full diagnosis, in the theme-cards scenario). Without this the PNG is of an
    # off-screen drawer, i.e. blank, while every assertion above still passes.
    # The transform transition also needs a beat before the shot.
    page.evaluate("window.openColorSettings()")
    page.wait_for_timeout(400)
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


# ── Distribution track (site/hist-track.js) ───────────────────────────────────
#
# The numeric column filter's track is a <canvas> histogram of that column's own
# values (bars + count gridlines + hovered-bin marker + out-of-range scrim), with
# the Y labels as DOM spans in a 34 px gutter. Nothing about the bar geometry is in
# the DOM, so these scenarios assert it through the module's pure helpers
# (HistTrack.layout / .histogram) plus the canvas' own pixels — a screenshot alone
# cannot tell a correct histogram from a wrong one.

# Numeric column to drive the range-filter scenarios with, in preference order:
# the index grid has "Cena (Kč)", the reference grid does not — "Výkon (kW)" is on
# both. Keeps one scenario runnable against either page.
_RANGE_FIELDS = ["Cena (Kč)", "Výkon (kW)", "Objem motoru"]
# Columns that are blank on most rows — what the "Bez hodnoty" switch is for.
_SPARSE_FIELDS = ["Kapacita baterie (kWh)", "Dojezd WLTP (km)"]


def _pick_field(page, candidates):
    field = page.evaluate(
        "(fs)=>fs.filter(function(f){return !!window.__gridApi.getColumn(f);})[0] || ''",
        candidates,
    )
    if not field:
        raise AssertionError(f"none of {candidates!r} is a column on this page")
    return field


def _open_range_filter(page, field):
    """Open a numeric column's RangeFilter popup and wait for its canvas track.
    afterGuiAttached measures + paints on the next frame, so give it one."""
    page.evaluate("(f)=>window.__gridApi.showColumnFilter(f)", field)
    page.wait_for_selector(".range-filter", timeout=5000)
    page.wait_for_selector(".range-filter .ht-track canvas", timeout=5000)
    page.wait_for_timeout(350)


def _col_domain(page):
    """The open track's value domain + step — read off the two native range inputs,
    which the RangeFilter seeds straight from colRanges[field]."""
    return page.evaluate(
        "()=>{var r=document.querySelector('.range-filter .ht-track input[type=range]');"
        " return {min:+r.min, max:+r.max, step:+r.step};}"
    )


def _parse_cs_count(txt):
    """cs-CZ count label → float: '12 tis.' → 12000, '1,5 mil.' → 1500000, '840' → 840.
    toLocaleString groups with NBSP / narrow NBSP, so both are folded to a space."""
    t = (txt or "").replace("\u00a0", " ").replace("\u202f", " ").strip()
    mult = 1.0
    for suffix, m in (("mil.", 1e6), ("tis.", 1e3)):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
            mult = m
            break
    t = t.replace(" ", "").replace(",", ".")
    return float(t) * mult


def _ylabels(page):
    return page.evaluate(
        "()=>[].map.call(document.querySelectorAll('.range-filter .ht-ylabels span'),"
        "function(s){return s.textContent||'';})"
    )


def _xlabels(page):
    return page.evaluate(
        "()=>[].map.call(document.querySelectorAll('.range-filter .ht-xaxis span'),"
        "function(s){return s.textContent||'';})"
    )


def _canvas_png(page):
    return page.evaluate("()=>document.querySelector('.range-filter .ht-track canvas').toDataURL()")


def _canvas_ink(page):
    """Non-transparent pixels on the open track's canvas. Gridlines + baseline alone
    are ~1/3 of a painted track, so this distinguishes "bars are drawn" from "the
    axis is drawn and the bars vanished" — which a screenshot-only check misses when
    the scenario passes on everything else."""
    return page.evaluate(
        "()=>{var c=document.querySelector('.range-filter .ht-track canvas');"
        " if(!c||!c.width) return 0;"
        " var d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,n=0;"
        " for(var i=3;i<d.length;i+=4) if(d[i]>8) n++; return n;}"
    )


def _set_range_boxes(page, lo, hi):
    """Drive the od/do boxes the way a user types into them (commitRange debounces
    the recolour + refilter by 220 ms, then AG runs the filter pass)."""
    page.evaluate(
        "(a)=>{var g=document.querySelector('.range-filter');"
        " var mn=g.querySelector('.th-min'), mx=g.querySelector('.th-max');"
        " mn.value=String(a[0]); mn.dispatchEvent(new Event('input',{bubbles:true}));"
        " mx.value=String(a[1]); mx.dispatchEvent(new Event('input',{bubbles:true}));}",
        [lo, hi],
    )
    page.wait_for_timeout(700)


def _cell_backgrounds(page, field):
    """{cell text: inline background} for the rendered cells of one column. The heat
    tint is a pure function of the value + the column's colour range, so this map is
    the observable proof that a threshold is (or is no longer) colouring."""
    return page.evaluate(
        "(f)=>{var o={};"
        " document.querySelectorAll('.ag-cell[col-id=\"'+f+'\"]').forEach(function(c){"
        "   var t=(c.textContent||'').trim();"
        "   if(t) o[t]=c.style.background||c.style.backgroundColor||'';});"
        " return o;}",
        field,
    )


def _shared_diff(a, b):
    keys = [k for k in a if k in b]
    return keys, [k for k in keys if a[k] != b[k]]


def scenario_hist_track(page):
    """The numeric filter's track is a value histogram on a <canvas>.

    Asserts what a screenshot cannot:
      1. the canvas has a backing store and actual ink in it;
      2. HistTrack.layout() geometry is sound at several widths — integer bar width
         and bin count, `bins*(bar+GAP) - GAP <= innerW` (leftover pixels become
         padding at the two EDGES, never fractional bar widths), maxBins honoured;
      3. HistTrack.niceTicks(peak) is a valid COUNT axis at every peak: whole cars
         (≥ 1, never a fraction), ≤ peak, strictly increasing, ≤ 3 of them, and no two
         rendering to the same label;
      4. the count axis draws at most 3 gridline labels, all parseable, strictly
         increasing, and none above the peak bin count the data implies (a label
         above the tallest bar reads as a broken axis);
      5. every value falls inside a bin over the full domain (histogram total == n).
    """
    page.wait_for_selector(".ag-row", timeout=15000)
    field = _pick_field(page, _RANGE_FIELDS)
    _open_range_filter(page, field)

    painted = page.evaluate(
        "()=>{var c=document.querySelector('.range-filter .ht-track canvas');"
        " if(!c||!c.width||!c.height) return {w:0,h:0,ink:0};"
        " var d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,n=0;"
        " for(var i=3;i<d.length;i+=4) if(d[i]>8) n++;"
        " return {w:c.width,h:c.height,ink:n};}"
    )
    if not painted["w"] or not painted["h"]:
        raise AssertionError(f"the track canvas has no backing store: {painted}")
    if painted["ink"] < 200:
        raise AssertionError(f"track canvas is (nearly) blank — nothing was drawn: {painted}")

    geom = page.evaluate(
        "()=>{var out=[];[120,300,301,640].forEach(function(w){"
        " [null,12,48].forEach(function(mb){var l=window.HistTrack.layout(w,mb);"
        "   out.push({w:w,maxBins:mb,bar:l.bar,bins:l.bins});});});return out;}"
    )
    for g in geom:
        if g["bar"] != int(g["bar"]) or g["bins"] != int(g["bins"]):
            raise AssertionError(f"layout() returned fractional geometry: {g}")
        if g["bar"] < 1 or g["bins"] < 2:
            raise AssertionError(f"layout() degenerate: {g}")
        span = g["bins"] * (g["bar"] + 1) - 1      # GAP == 1
        if span > g["w"]:
            raise AssertionError(f"layout() overflows the track ({span} px of {g['w']}): {g}")
        if g["maxBins"] and g["bins"] > g["maxBins"]:
            raise AssertionError(f"layout() ignored maxBins: {g}")

    # The gridlines label a COUNT of cars, so they must be whole cars ≥ 1 — a peaked
    # column filtered down to a handful of rows must not grow a "0" gridline (the
    # labels are printed with 0 decimals, so a 0.25 tick reads "0", and two sub-1
    # ticks read as two identical "0" lines).
    ticks = page.evaluate(
        "()=>[1,2,3,6,9,30,120,4000,41234,152000].map(function(p){"
        " return {peak:p, ticks:window.HistTrack.niceTicks(p)};})"
    )
    for row in ticks:
        ts, peak = row["ticks"], row["peak"]
        if len(ts) > 3:
            raise AssertionError(f"niceTicks({peak}) returned {len(ts)} gridlines, expected ≤ 3: {ts}")
        for t in ts:
            if t < 1 or t != int(t):
                raise AssertionError(
                    f"niceTicks({peak}) → {ts}: a count gridline must be a whole number of "
                    f"cars ≥ 1, {t} is not"
                )
            if t > peak:
                raise AssertionError(f"niceTicks({peak}) → {ts}: {t} sits above the tallest bar")
        for a, b in zip(ts, ts[1:]):
            if not b > a:
                raise AssertionError(f"niceTicks({peak}) is not strictly increasing: {ts}")
        rendered = [_parse_cs_count(x) for x in page.evaluate(
            "(ts)=>{var f=ts.map(function(v){return window.HistTrack.fmtInt(v);});return f;}", ts)]
        if len(set(rendered)) != len(rendered):
            raise AssertionError(f"niceTicks({peak}) → {ts} renders duplicate labels: {rendered}")

    # Recompute the histogram the track drew (same domain, same layout maths as
    # Track.metrics) so the gridline labels can be checked against a real peak.
    probe = page.evaluate(
        "(f)=>{var tr=document.querySelector('.range-filter .ht-track');"
        " var r=tr.querySelector('input[type=range]'), min=+r.min, max=+r.max, step=+r.step;"
        " var innerW=Math.max(40, tr.getBoundingClientRect().width - window.HistTrack.GUTTER);"
        " var maxBins=null;"
        " if(step){var steps=Math.round((max-min)/step)+1; if(steps<=200) maxBins=Math.max(2,steps);}"
        " var lay=window.HistTrack.layout(innerW, maxBins), vals=[];"
        # reference.json stores some numeric columns as strings ("150"), and the
        # page's own value providers coerce — so coerce here too, or the probe finds
        # nothing to bin on the reference page.
        " window.__gridApi.forEachNode(function(n){var v=n.data&&n.data[f];"
        "   var num=typeof v==='number'?v:parseFloat(v);"
        "   if(isFinite(num)) vals.push(num);});"
        " var h=window.HistTrack.histogram(vals, min, max, lay.bins);"
        " return {peak:h.peak, total:h.total, n:vals.length, bins:lay.bins, bar:lay.bar};}",
        field,
    )
    if probe["n"] < 10 or probe["peak"] <= 0:
        raise AssertionError(f"no distribution to draw for {field!r}: {probe}")
    if probe["total"] != probe["n"]:
        raise AssertionError(
            f"{probe['n'] - probe['total']} value(s) fell outside every bin over the "
            f"full domain: {probe}"
        )

    labels = _ylabels(page)
    if not labels:
        raise AssertionError("the count axis drew no gridline labels")
    if len(labels) > 3:
        raise AssertionError(f"count axis drew {len(labels)} labels, expected ≤ 3: {labels}")
    try:
        vals = [_parse_cs_count(t) for t in labels]
    except ValueError as e:
        raise AssertionError(f"unparseable gridline label in {labels}: {e}")
    for a, b in zip(vals, vals[1:]):
        if not b > a:
            raise AssertionError(f"gridline labels are not strictly increasing: {labels}")
    if vals[-1] > probe["peak"] * 1.02:
        raise AssertionError(
            f"top gridline {labels[-1]!r} ({vals[-1]:.0f}) exceeds the peak bin count "
            f"{probe['peak']} — the axis would sit above the tallest bar"
        )
    return ".range-filter"


def scenario_hist_modes(page):
    """The three .seg buttons pick WHAT the bars count: Vše (every row in the grid) /
    Po filtru (the rows the grid shows) / Obojí (both layers, shared scale). It is a
    global appearance pref, so it persists to localStorage carCompareHistMode.

    Another column is filtered first: with nothing filtered "Po filtru" == "Vše" and
    a repaint would be indistinguishable from a no-op."""
    page.wait_for_selector(".ag-row", timeout=15000)
    field = _pick_field(page, _RANGE_FIELDS)
    narrow = _pick_field(page, ["Typ", "Palivo", "Karoserie"])
    value = page.evaluate(
        "(f)=>{var v=null;window.__gridApi.forEachNode(function(n){"
        "if(v===null&&n.data&&n.data[f]) v=n.data[f];});return v;}",
        narrow,
    )
    page.evaluate(
        "(a)=>window.__gridApi.setFilterModel({[a[0]]:{filterType:'set',values:[a[1]]}})",
        [narrow, value],
    )
    page.wait_for_timeout(400)
    _open_range_filter(page, field)

    # Ink on the first (un-animated) paint = the reference for "the bars are there".
    baseline_ink = _canvas_ink(page)
    if baseline_ink < 200:
        raise AssertionError(f"nothing painted before the first mode switch (ink={baseline_ink})")

    shots = {}
    for mode in ("all", "filter", "both"):
        page.click(".range-filter .rf-ctl-row .seg button[data-value='%s']" % mode)
        page.wait_for_timeout(450)          # ANIM_MS 170 + rAF settle
        active = page.evaluate(
            "()=>{var b=document.querySelector('.range-filter .rf-ctl-row .seg button.active');"
            " return b ? b.dataset.value : '';}"
        )
        if active != mode:
            raise AssertionError(f"clicked {mode!r} but the active segment is {active!r}")
        stored = page.evaluate("()=>{try{return JSON.parse(localStorage.getItem('carCompareHistMode'))||{};}catch(e){return {};}}")
        if stored.get("mode") != mode:
            raise AssertionError(f"localStorage carCompareHistMode did not follow: {stored}")
        ink = _canvas_ink(page)
        if ink < baseline_ink * 0.5:
            raise AssertionError(
                "mode %r left the track without bars (ink %d vs %d before the switch) — the "
                "height tween paints NaN heights, so the last animated frame is bar-less and "
                "stays on screen until an unrelated repaint" % (mode, ink, baseline_ink)
            )
        shots[mode] = _canvas_png(page)

    if shots["all"] == shots["filter"]:
        raise AssertionError("canvas did not repaint between 'Vše' and 'Po filtru'")
    if shots["both"] == shots["filter"]:
        raise AssertionError("'Obojí' painted the same as 'Po filtru' — no context layer")
    if shots["both"] == shots["all"]:
        raise AssertionError("'Obojí' painted the same as 'Vše' — no filtered layer")
    return ".range-filter"


def scenario_hist_zoom(page):
    """.ht-zoom shrinks the value axis onto the filtered rows ("Po filtru" only —
    zooming "Vše" would be a no-op, so the button is disabled there).

    The zoom animates the DOMAIN and re-bins per frame; the count gridlines are
    deliberately FROZEN to the end state, because deriving niceTicks() per frame
    made the labels flicker through different round numbers. So:
      • the value axis really moves (first AND last label change),
      • the ± icon and its aria-label flip,
      • the count labels change at most once across the whole animation.
    """
    page.wait_for_selector(".ag-row", timeout=15000)
    field = _pick_field(page, _RANGE_FIELDS)
    _open_range_filter(page, field)
    page.click(".range-filter .rf-ctl-row .seg button[data-value='filter']")
    page.wait_for_timeout(450)

    # Narrow this column's own range: the zoom collapses the gap between the
    # filtered rows' extent and the full domain, so there must be a gap.
    dom = _col_domain(page)
    span = dom["max"] - dom["min"]
    lo = dom["min"] + span * 0.25
    hi = dom["min"] + span * 0.45
    page.evaluate(
        "(a)=>window.__gridApi.setColumnFilterModel(a[0],"
        "{filterType:'number',type:'inRange',filter:a[1],filterTo:a[2]})"
        ".then(function(){window.__gridApi.onFilterChanged();})",
        [field, lo, hi],
    )
    page.wait_for_timeout(600)

    before_x = _xlabels(page)
    before_zoom = page.evaluate(
        "()=>{var b=document.querySelector('.range-filter .ht-zoom');"
        " return {aria:b.getAttribute('aria-label')||'', paths:b.querySelectorAll('path').length,"
        "         on:b.classList.contains('on'), disabled:!!b.disabled};}"
    )
    if before_zoom["disabled"]:
        raise AssertionError("Lupa is still disabled in 'Po filtru' mode")

    page.click(".range-filter .ht-zoom")
    samples = []
    for _ in range(9):
        samples.append(tuple(_ylabels(page)))
        page.wait_for_timeout(25)
    page.wait_for_timeout(450)

    after_x = _xlabels(page)
    after_zoom = page.evaluate(
        "()=>{var b=document.querySelector('.range-filter .ht-zoom');"
        " return {aria:b.getAttribute('aria-label')||'', paths:b.querySelectorAll('path').length,"
        "         on:b.classList.contains('on')};}"
    )
    if after_zoom["aria"] == before_zoom["aria"]:
        raise AssertionError(f"zoom aria-label did not flip: {before_zoom['aria']!r}")
    if after_zoom["paths"] == before_zoom["paths"]:
        raise AssertionError(
            f"zoom icon did not flip +/− (still {after_zoom['paths']} paths)"
        )
    if not after_zoom["on"]:
        raise AssertionError("zoom button did not take the .on state")
    if before_x[0] == after_x[0] or before_x[-1] == after_x[-1]:
        raise AssertionError(
            f"value axis did not zoom: {before_x} → {after_x}"
        )

    settled = tuple(_ylabels(page))
    distinct = set(samples) | {settled}
    if len(distinct) > 2:
        raise AssertionError(
            "count gridline labels flickered during the zoom (%d distinct sets, expected ≤ 2): %r"
            % (len(distinct), sorted(distinct))
        )
    if samples[-1] != settled and samples[-2] != settled:
        raise AssertionError(
            f"count labels kept changing after the animation: {samples[-2:]} vs {settled}"
        )
    return ".range-filter"


def scenario_blank_filter(page):
    """"Bez hodnoty" (Skrýt / Zahrnout / Jen ty) turns blank cells into a real filter
    question, and maps onto AG's OWN model shapes — which is why the URL codec and
    the filter chips needed no new token:

        hide + bounds → {inRange}
        show + bounds → {operator:"OR", conditions:[inRange, {type:"blank"}]}
        only          → {type:"blank"}

    Driven on a sparse column (Kapacita baterie is blank on every combustion car),
    asserting both the row counts and the emitted model.
    """
    page.wait_for_selector(".ag-row", timeout=15000)
    field = _pick_field(page, _SPARSE_FIELDS)
    total = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    blanks = page.evaluate(
        "(f)=>{var n=0;window.__gridApi.forEachNode(function(x){var v=x.data&&x.data[f];"
        " if(!(typeof v==='number'&&isFinite(v))) n++;});return n;}",
        field,
    )
    if not blanks or blanks >= total:
        raise AssertionError(f"{field!r} is not sparse on this page ({blanks} blank of {total})")
    _open_range_filter(page, field)

    def model():
        return page.evaluate("(f)=>(window.__gridApi.getFilterModel()||{})[f]", field)

    def pick(mode):
        page.click(".range-filter .rf-blank-row .seg button[data-value='%s']" % mode)
        page.wait_for_timeout(500)
        active = page.evaluate(
            "()=>{var b=document.querySelector('.range-filter .rf-blank-row .seg button.active');"
            " return b ? b.dataset.value : '';}"
        )
        if active != mode:
            raise AssertionError(f"clicked blank mode {mode!r}, active is {active!r}")

    # The switch prints how many rows are missing a value, so the choice is informed.
    shown = page.inner_text(".range-filter .rf-blank-count")
    digits = "".join(ch for ch in shown if ch.isdigit())
    if not digits or int(digits) != blanks:
        raise AssertionError(f"blank count label {shown!r} != {blanks} rows without a value")

    # "Jen ty" → exactly the blank rows, via AG's bare blank model.
    pick("only")
    only_shown = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if only_shown != blanks:
        raise AssertionError(f"'Jen ty' shows {only_shown} rows, expected {blanks} blanks")
    m = model()
    if not m or m.get("type") != "blank" or m.get("filterType") != "number" or m.get("conditions"):
        raise AssertionError(f"'Jen ty' emitted {m!r}, expected a bare number/blank model")

    # "Skrýt" + a range → plain inRange; blanks fail it.
    pick("hide")
    dom = _col_domain(page)
    span = dom["max"] - dom["min"]
    lo = round(dom["min"] + span * 0.2)
    hi = round(dom["min"] + span * 0.8)
    _set_range_boxes(page, lo, hi)
    hide_shown = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    m = model()
    if not m or m.get("type") != "inRange":
        raise AssertionError(f"'Skrýt' + range emitted {m!r}, expected an inRange model")
    if float(m.get("filter")) != lo or float(m.get("filterTo")) != hi:
        raise AssertionError(f"range bounds did not reach the model: {m!r} (wanted {lo}–{hi})")
    leaked = page.evaluate(
        "(f)=>{var n=0;window.__gridApi.forEachNodeAfterFilter(function(x){var v=x.data&&x.data[f];"
        " if(!(typeof v==='number'&&isFinite(v))) n++;});return n;}",
        field,
    )
    if leaked:
        raise AssertionError(f"'Skrýt' left {leaked} blank row(s) in the grid")
    if not 0 < hide_shown < total - blanks + 1:
        raise AssertionError(f"'Skrýt' + range shows {hide_shown} of {total} rows — implausible")

    # "Zahrnout" → the same range OR blank; the blanks come back on top.
    pick("show")
    show_shown = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    m = model()
    conds = (m or {}).get("conditions") or []
    types = sorted(c.get("type") for c in conds)
    if (m or {}).get("operator") != "OR" or types != ["blank", "inRange"]:
        raise AssertionError(f"'Zahrnout' emitted {m!r}, expected OR[inRange, blank]")
    if show_shown < hide_shown:
        raise AssertionError(f"'Zahrnout' shows fewer rows than 'Skrýt' ({show_shown} < {hide_shown})")
    if show_shown != hide_shown + blanks:
        raise AssertionError(
            f"'Zahrnout' shows {show_shown}, expected range {hide_shown} + {blanks} blanks"
        )

    # …and back to "Skrýt": the blanks drop out again.
    pick("hide")
    back = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if back != hide_shown:
        raise AssertionError(f"'Skrýt' after 'Zahrnout' shows {back}, expected {hide_shown}")
    return ".range-filter"


def scenario_colour_only(page):
    """"Jen barvit, nefiltrovat" keeps the range as a colour threshold but emits NO
    filter model (isFilterActive false), so the grid returns to its full row set
    while the column stays tinted. Because AG then has nothing to render a chip
    from, the range rides into the chips bar as a dashed .filter-chip.tint carrying
    a "jen barva" tag — otherwise a column could stay tinted with nothing on screen
    saying so. Its × clears the range outright (colour included).

    The tint is asserted through the cells' inline backgrounds: the heat colour is a
    pure function of value + colour range, so a changed threshold must change them,
    and clearing must restore exactly the baseline map.
    """
    page.wait_for_selector(".ag-row", timeout=15000)
    field = _pick_field(page, _RANGE_FIELDS)
    page.evaluate("(f)=>window.__gridApi.ensureColumnVisible(f)", field)
    page.wait_for_timeout(250)
    total = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    base_bg = _cell_backgrounds(page, field)
    if len(base_bg) < 5:
        raise AssertionError(f"only {len(base_bg)} rendered cells for {field!r} — cannot check the tint")

    _open_range_filter(page, field)
    dom = _col_domain(page)
    span = dom["max"] - dom["min"]
    lo = round(dom["min"] + span * 0.25)
    hi = round(dom["min"] + span * 0.60)
    _set_range_boxes(page, lo, hi)
    filtered = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if filtered >= total:
        raise AssertionError(f"the range did not filter anything ({filtered} of {total})")

    page.evaluate(
        "()=>{var c=document.querySelector('.range-filter .rf-check input');"
        " c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));}"
    )
    page.wait_for_timeout(600)

    unfiltered = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if unfiltered != total:
        raise AssertionError(f"colour-only still filters: {unfiltered} of {total} rows")
    if page.evaluate("(f)=>!!(window.__gridApi.getFilterModel()||{})[f]", field):
        raise AssertionError("colour-only left a filter model behind")

    chip = page.evaluate(
        "()=>{var c=document.querySelector('#filter-chips-bar .filter-chip.tint');"
        " if(!c) return null;"
        " var t=c.querySelector('.filter-chip-tag'), l=c.querySelector('.filter-chip-label');"
        " return {tag:t?(t.textContent||'').trim():'', label:l?(l.textContent||'').trim():'',"
        "         close:!!c.querySelector('.filter-chip-close')};}"
    )
    if not chip:
        raise AssertionError("no dashed .filter-chip.tint chip for the colour-only range")
    if chip["tag"] != "jen barva":
        raise AssertionError(f"tint chip tag is {chip['tag']!r}, expected 'jen barva'")
    if field.split(" (")[0] not in chip["label"] or not chip["close"]:
        raise AssertionError(f"tint chip is missing its column or × : {chip!r}")

    tint_bg = _cell_backgrounds(page, field)
    keys, changed = _shared_diff(base_bg, tint_bg)
    if len(keys) < 5:
        raise AssertionError(f"only {len(keys)} comparable cells after the colour-only switch")
    if not changed:
        raise AssertionError("colour-only range did not change a single cell's heat colour")
    if any(not tint_bg[k] for k in keys):
        raise AssertionError("a cell lost its heat background entirely under colour-only")

    page.click("#filter-chips-bar .filter-chip.tint .filter-chip-close")
    page.wait_for_timeout(600)
    if page.query_selector("#filter-chips-bar .filter-chip.tint"):
        raise AssertionError("the tint chip survived its own ×")
    cleared_bg = _cell_backgrounds(page, field)
    _, still = _shared_diff(base_bg, cleared_bg)
    if still:
        raise AssertionError(
            f"{len(still)} cell(s) kept the colour-only tint after the chip × (e.g. {still[0]!r})"
        )
    th = page.evaluate("()=>localStorage.getItem('carCompareThresholds')||''")
    if field in th:
        raise AssertionError(f"the chip × left {field!r} in carCompareThresholds: {th}")

    # Put the colour-only state back for the screenshot: the assertions end on a
    # cleared grid, which looks exactly like the plain `grid` scenario and documents
    # nothing. The shot should show the dashed "jen barva" chip over a tinted column.
    _open_range_filter(page, field)
    page.evaluate(
        "()=>{var c=document.querySelector('.range-filter .rf-check input');"
        " c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));}"
    )
    _set_range_boxes(page, lo, hi)
    page.keyboard.press("Escape")          # close the popup so the chip bar is unobstructed
    page.wait_for_timeout(400)
    if not page.query_selector("#filter-chips-bar .filter-chip.tint"):
        raise AssertionError("the colour-only range did not come back for the screenshot")
    return None


def scenario_theme_cards(page):
    """The colour drawer picks the theme from two miniatures of the page itself
    (.theme-card > .theme-mini, painted in that theme's own tokens) — the gear
    menu's "Přepnout motiv" item is gone and window.setTheme(theme) is the
    primitive. Clicking a card must flip data-theme, persist carCompareTheme and
    move the .active state; both directions are exercised so the screenshot ends up
    in the requested --theme."""
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.openColorSettings()")
    page.wait_for_selector("#theme-choices .theme-card", timeout=5000)
    page.wait_for_timeout(350)          # drawer slides in (transform transition)

    cards = page.evaluate(
        "()=>[].map.call(document.querySelectorAll('#theme-choices .theme-card'),"
        " function(b){return {mini:!!b.querySelector('.theme-mini'),"
        "   active:b.classList.contains('active'), label:(b.textContent||'').trim()};})"
    )
    if len(cards) != 2:
        raise AssertionError(f"expected 2 theme cards, got {len(cards)}: {cards}")
    if not all(c["mini"] for c in cards):
        raise AssertionError(f"a theme card has no .theme-mini miniature: {cards}")
    if sum(1 for c in cards if c["active"]) != 1:
        raise AssertionError(f"exactly one theme card must be active: {cards}")

    start = page.evaluate("document.documentElement.getAttribute('data-theme')")
    other = [i for i, c in enumerate(cards) if not c["active"]][0]
    problems = []

    def click_card(idx):
        page.locator("#theme-choices .theme-card").nth(idx).click()
        page.wait_for_timeout(400)
        st = page.evaluate(
            "()=>({theme:document.documentElement.getAttribute('data-theme'),"
            " stored:localStorage.getItem('carCompareTheme'),"
            " open:!document.getElementById('settings-panel').classList.contains('hidden'),"
            " active:[].findIndex.call(document.querySelectorAll('#theme-choices .theme-card'),"
            "   function(c){return c.classList.contains('active');})})"
        )
        if not st["open"]:
            # Deferred, not raised: the theme itself still applies, and the rest of
            # the contract (both directions) is worth checking in one run.
            msg = ("picking a theme CLOSES the drawer — setTheme() re-renders the cards, so the "
                   "document 'click outside closes' listener sees a DETACHED e.target whose "
                   "closest('#settings-panel') is null (same for the palette/style chips)")
            if msg not in problems:
                problems.append(msg)
            page.evaluate("window.openColorSettings()")
            page.wait_for_timeout(400)
        return st

    st = click_card(other)
    if st["theme"] == start:
        raise AssertionError(f"clicking the inactive theme card did not flip data-theme ({start})")
    if st["stored"] != st["theme"]:
        raise AssertionError(f"localStorage carCompareTheme={st['stored']!r} != data-theme={st['theme']!r}")
    if st["active"] != other:
        raise AssertionError(f"the .active card did not move onto the clicked one: {st}")

    back = click_card(1 - other)
    if back["theme"] != start or back["stored"] != start:
        raise AssertionError(f"clicking back did not restore {start!r}: {back}")
    if problems:
        raise AssertionError("; ".join(problems))
    return "#settings-panel"


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
    "hist-track": scenario_hist_track,
    "hist-modes": scenario_hist_modes,
    "hist-zoom": scenario_hist_zoom,
    "blank-filter": scenario_blank_filter,
    "colour-only": scenario_colour_only,
    "theme-cards": scenario_theme_cards,
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
    "service-cost": scenario_service_cost,
    "service-cost-col": scenario_service_cost_col,
    "archive": scenario_archive,
    "date-filter": scenario_date_filter,
    "date-filter-ref": scenario_date_filter_ref,
    "filter-chips": scenario_filter_chips,
    "chip-click": scenario_chip_click,
    "multi-condition": scenario_multi_condition,
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
