#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Argument parsing: -s / --scrapers accepts a comma-separated list of scraper
# names (e.g. "autodraft" or "autodraft,energycars"). Defaults to all.
# ---------------------------------------------------------------------------
SCRAPERS="autodraft energycars sauto"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--scrapers)
            SCRAPERS="${2//,/ }"
            shift 2
            ;;
        *)
            echo "Usage: $0 [-s|--scrapers SCRAPER1,SCRAPER2]"
            echo "  Available scrapers: autodraft, energycars, sauto"
            exit 1
            ;;
    esac
done

echo "==> Kontroluji Python závislosti..."
python3 -c "import playwright, pandas, bs4" 2>/dev/null || {
    echo "    Instaluji chybějící balíčky..."
    pip install playwright pandas beautifulsoup4
}

echo "==> Kontroluji Playwright Chromium prohlížeč..."
_chromium_ok=$(python3 - 2>/dev/null <<'PYEOF'
from playwright.sync_api import sync_playwright
import os, sys
try:
    with sync_playwright() as p:
        print("yes" if os.path.isfile(p.chromium.executable_path) else "no")
except Exception:
    print("no")
PYEOF
)
if [ "${_chromium_ok:-no}" != "yes" ]; then
    echo "    Instaluji Playwright Chromium..."
    playwright install chromium
fi

# ---------------------------------------------------------------------------
# Launch selected scrapers in parallel; collect PIDs and report failures.
# ---------------------------------------------------------------------------
echo "==> Spouštím scrapers: $SCRAPERS"
declare -a pids=()
declare -a names=()

for scraper in $SCRAPERS; do
    script="$SCRIPT_DIR/scrape_${scraper}.py"
    if [[ ! -f "$script" ]]; then
        echo "  WARN: scraper '$scraper' nenalezen ($script), přeskakuji."
        continue
    fi
    python3 "$script" &
    pids+=($!)
    names+=("$scraper")
done

failed=0
for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
        echo "  [OK] ${names[$i]}"
    else
        echo "  [FAIL] ${names[$i]}"
        failed=$((failed + 1))
    fi
done

if [[ $failed -gt 0 ]]; then
    echo "==> $failed scraper(s) selhaly." >&2
    exit 1
fi
echo "==> Všechny scrapers dokončeny."
