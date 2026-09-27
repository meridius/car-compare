#!/usr/bin/env bash
# Download the current data snapshot from the rolling GitHub Release `data`
# into the local tree, so a fresh clone has real state to build and serve from.
#
# Without this, the pipeline falls back to the frozen seed CSVs tracked in git
# (older, smaller). See docs/decisions/001-scalable-storage.md.
#
# Usage:
#   ./bin/bootstrap-data.sh            # download state + payload
#   ./bin/bootstrap-data.sh --build    # …then rebuild cars.parquet from state
#
# CAR_COMPARE_STATE_DIR (see scrapers/core/storage.py) redirects the state
# parquets — and a copy of scrape_history.json — out of the clone.
#
# Requires the `gh` CLI, authenticated with read access to the repo (the repo
# is private, so its release assets are NOT publicly downloadable).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v gh >/dev/null || { echo "gh CLI not found — see https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated — run 'gh auth login'"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading 'data' release assets…"
if ! gh release download data --dir "$TMP" --clobber 2>/dev/null; then
  echo "No 'data' release yet (first main-branch run publishes it)."
  echo "Frozen seed CSVs cover the bootstrap — nothing to download."
  exit 0
fi

STATE_DIR="${CAR_COMPARE_STATE_DIR:-scrapers/data/scrapes}"
mkdir -p "$STATE_DIR" site/data

# Per-source state parquets → the state dir (drives build + merge).
for slug in sauto autodraft energycars mobilede; do
  if [ -f "$TMP/$slug.parquet" ]; then
    cp "$TMP/$slug.parquet" "$STATE_DIR/"
    echo "  state:   $slug.parquet → $STATE_DIR"
  fi
done
# An out-of-clone state dir also keeps the scrape history (bin/nas-daily.sh
# restores it into site/data before each build).
if [ -n "${CAR_COMPARE_STATE_DIR:-}" ] && [ -f "$TMP/scrape_history.json" ]; then
  cp "$TMP/scrape_history.json" "$STATE_DIR/"
  echo "  state:   scrape_history.json → $STATE_DIR"
fi

# Built payload + sidecars → site/data/ (lets serve.sh run without a rebuild).
for f in cars.parquet cars-archived.parquet cars-meta.json reference.json scrape_history.json; do
  if [ -f "$TMP/$f" ]; then
    cp "$TMP/$f" site/data/
    echo "  payload: $f"
  fi
done

echo "Done — local tree now mirrors the 'data' release."

if [ "${1:-}" = "--build" ]; then
  echo "Rebuilding cars.parquet from downloaded state…"
  python3 build/build_data.py
fi
