#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."

# Ensure CWD is repo root so `python -m scrapers.run` can resolve the package.
cd "$ROOT"

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

echo "==> Spouštím unified scraper..."
python3 -m scrapers.run "$@"

echo "==> Vše dokončeno."
