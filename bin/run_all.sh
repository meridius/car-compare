#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."

# Ensure CWD is repo root so `python -m scrapers.run` can resolve the package.
cd "$ROOT"

ALL_SOURCES=(sauto autodraft energycars mobilede)

# Parse --source NAME (repeatable, mirrors scrapers.run); default to all sources.
SOURCES=()
while [ $# -gt 0 ]; do
    case "$1" in
        --source) SOURCES+=("$2"); shift 2 ;;
        --source=*) SOURCES+=("${1#--source=}"); shift ;;
        *) echo "Neznámý argument: $1" >&2; exit 2 ;;
    esac
done
if [ ${#SOURCES[@]} -eq 0 ]; then
    SOURCES=("${ALL_SOURCES[@]}")
fi

# Dependency checks run ONCE, serially, before fan-out — concurrent pip /
# playwright installs would race on the same cache.
echo "==> Kontroluji Python závislosti..."
python3 -c "import playwright, pandas, bs4, aiohttp" 2>/dev/null || {
    echo "    Instaluji chybějící balíčky..."
    pip install playwright pandas beautifulsoup4 aiohttp
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

# Each source writes its own data/scrapes/<slug>.csv and only reads the shared
# reference files, so sources are write-independent and safe to run in parallel.
# Fuel configurations inside a source (EV/ICE, palivo URLs) stay serial — that
# ordering lives in each adapter's scrape() and is untouched here.
echo "==> Spouštím ${#SOURCES[@]} zdroj(ů) paralelně: ${SOURCES[*]}"
LOG_DIR="$(mktemp -d)"
trap 'rm -rf "$LOG_DIR"' EXIT

declare -A PIDS
for src in "${SOURCES[@]}"; do
    python3 -m scrapers.run --source "$src" >"$LOG_DIR/$src.log" 2>&1 &
    PIDS[$src]=$!
done

# Wait for every source; collect failures. Logs are printed grouped per source
# (live interleaving of 3 processes would be unreadable).
FAILED=()
for src in "${SOURCES[@]}"; do
    if wait "${PIDS[$src]}"; then
        status="OK"
    else
        status="SELHALO"
        FAILED+=("$src")
    fi
    echo "===== [$src] $status ====="
    cat "$LOG_DIR/$src.log"
done

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "==> CHYBA: selhaly zdroje: ${FAILED[*]}" >&2
    exit 1
fi

echo "==> Vše dokončeno."
