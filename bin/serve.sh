#!/usr/bin/env bash
# Serve the site/ directory locally for development.
# Usage: ./bin/serve.sh [--pull] [port]
#   --pull   first download the prod payload from the `data` release
#            (via bin/bootstrap-data.sh) so you see the same data as prod
#   default port: 8000

set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "--pull" ]; then
  shift
  ./bin/bootstrap-data.sh
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
