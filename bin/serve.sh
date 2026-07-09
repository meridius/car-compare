#!/usr/bin/env bash
# Serve the site/ directory locally for development.
# Usage: ./bin/serve.sh [--pull] [port]
#   --pull   download the payload that is CURRENTLY DEPLOYED to prod (GitHub
#            Pages) straight into site/data/, so the local site is byte-identical
#            to prod. This is the already-built payload prod serves — no local
#            rebuild, and no `gh` auth (Pages assets are publicly fetchable).
#            Deliberately NOT the `data` release payload asset: that asset is
#            only refreshed by scrape runs, so it lags prod after any push
#            deploy. (For per-source STATE to run scrapers locally, use
#            bin/bootstrap-data.sh instead — a different job.)
#   default port: 8000

set -euo pipefail
cd "$(dirname "$0")/.."

PROD_BASE="https://meridius.github.io/car-compare/data"

if [ "${1:-}" = "--pull" ]; then
  shift
  echo "Downloading deployed prod payload from $PROD_BASE …"
  mkdir -p site/data
  for f in cars.parquet cars-archived.parquet cars-meta.json reference.json scrape_history.json; do
    if curl -sSfL -o "site/data/$f" "$PROD_BASE/$f"; then
      echo "  $f"
    else
      echo "  (skip $f — not on prod)"
    fi
  done
fi

PORT="${1:-8000}"
DIR="site"

if [ ! -f "$DIR/data/cars.parquet" ]; then
  echo "cars.parquet not found — building..."
  python3 build/build_data.py
fi

echo "Serving $DIR at http://localhost:$PORT (no-cache)"
python3 -c "
import http.server, functools, os
os.chdir('$DIR')
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()
http.server.HTTPServer(('', $PORT), H).serve_forever()
"
