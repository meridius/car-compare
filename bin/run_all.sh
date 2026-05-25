#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."

MODE="all"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --electric)    MODE="electric"; shift ;;
        --combustion)  MODE="combustion"; shift ;;
        --all)         MODE="all"; shift ;;
        -s|--scrapers) EXTRA_ARGS+=("-s" "$2"); shift 2 ;;
        *)             echo "Usage: $0 [--electric|--combustion|--all] [-s SCRAPERS]"
                       exit 1 ;;
    esac
done

failed=0

if [[ "$MODE" == "electric" || "$MODE" == "all" ]]; then
    echo "=== ELECTRIC ==="
    "$ROOT/electric/bin/run_scraper.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" || failed=$((failed + 1))
fi

if [[ "$MODE" == "combustion" || "$MODE" == "all" ]]; then
    echo "=== COMBUSTION ==="
    "$ROOT/combustion/bin/run_scraper.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" || failed=$((failed + 1))
fi

if [[ $failed -gt 0 ]]; then
    echo "==> $failed runner(s) selhalo." >&2
    exit 1
fi

echo "=== BUILD ==="
python3 "$ROOT/build/build_data.py"

echo "==> Vše dokončeno."
