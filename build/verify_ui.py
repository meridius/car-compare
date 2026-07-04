#!/usr/bin/env python3
"""Self-verification for the static dashboard UI (site/).

Serves site/, drives headless Chromium, captures console/page errors, runs a
few light inline checks, and screenshots key views to tmp/ui-verify/.
Exit 0 = pass, 1 = fail. Read the PNGs afterwards to confirm visual correctness.

Usage:
    python3 build/verify_ui.py [--page index|reference] \\
                               [--scenario grid|stav-filter] [--port N]

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

PAGE_FILES = {"index": "index.html", "reference": "reference.html"}


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


SCENARIOS = {
    "grid": scenario_grid,
    "stav-filter": scenario_stav_filter,
    "summary": scenario_summary,
    "sparovano": scenario_sparovano,
    "overview-matching": scenario_overview_matching,
    "archive": scenario_archive,
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

            row_count = page.locator(".ag-row").count()
            if row_count == 0:
                failures.append("no grid rows rendered (.ag-row count == 0)")

            if args.scenario == "grid":
                failures.extend(check_cd_format(page))

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
