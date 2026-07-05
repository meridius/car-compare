#!/usr/bin/env python3
"""Self-verification for the static dashboard UI (site/).

Serves site/, drives headless Chromium, captures console/page errors, runs a
few light inline checks, and screenshots key views to tmp/ui-verify/.
Exit 0 = pass, 1 = fail. Read the PNGs afterwards to confirm visual correctness.

Usage:
    python3 build/verify_ui.py [--page index|reference|transmissions] \\
                               [--scenario grid|stav-filter|transmissions] [--port N]

Defaults: --page index --scenario grid --port 0 (OS-assigned free port).
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


def scenario_stav_filter(page):
    page.wait_for_selector(".ag-row", timeout=15000)
    page.evaluate("window.__gridApi.showColumnFilter('Stav')")
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


def scenario_ref_search(page):
    """Type into the reference-page smart search box (#29) and confirm the grid
    quick-filters down to matching, accent-folded rows (typing "skoda" without
    diacritics must still find "Škoda")."""
    page.wait_for_selector(".ag-row", timeout=15000)
    # getDisplayedRowCount, not len(.ag-row): the grid virtualizes rows, so the
    # DOM count is capped by the viewport and doesn't shrink with the total.
    before = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    page.fill("#ref-search-input", "skoda")
    # debounce (200ms) + grid re-filter
    page.wait_for_timeout(600)
    after = page.evaluate("window.__gridApi.getDisplayedRowCount()")
    if not (after < before):
        raise AssertionError(f"quick filter did not reduce rows: before={before} after={after}")
    if after == 0:
        raise AssertionError("quick filter for 'skoda' matched zero rows")
    cells = page.locator('.ag-cell[col-id="Model auta"]').all_inner_texts()
    if not cells or not all("škoda" in c.lower() for c in cells):
        raise AssertionError(f"visible rows are not all Škoda: {cells[:10]}")


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


SCENARIOS = {
    "grid": scenario_grid,
    "stav-filter": scenario_stav_filter,
    "summary": scenario_summary,
    "sparovano": scenario_sparovano,
    "transmission-type-col": scenario_transmission_type_col,
    "overview-matching": scenario_overview_matching,
    "archive": scenario_archive,
    "filter-chips": scenario_filter_chips,
    "ref-search": scenario_ref_search,
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
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    ensure_data()
    os.makedirs(OUT_DIR, exist_ok=True)
    httpd, port = start_server(args.port)
    url = f"http://127.0.0.1:{port}/{PAGE_FILES[args.page]}"
    shot_path = os.path.join(OUT_DIR, f"{args.page}-{args.scenario}.png")

    errors = []
    failures = []
    row_count = 0

    def on_console(msg):
        if msg.type == "error" and "favicon" not in msg.text.lower() and "error #239" not in msg.text:
            errors.append("console: " + msg.text)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("console", on_console)
            page.on("pageerror", lambda exc: errors.append("pageerror: " + str(exc)))

            print(f"Loading {url} (scenario: {args.scenario})…")
            page.goto(url, wait_until="load", timeout=30000)

            try:
                target = SCENARIOS[args.scenario](page)
            except Exception as e:
                failures.append(f"scenario '{args.scenario}' failed: {e}")
                target = None

            if args.page in GRID_PAGES:
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
