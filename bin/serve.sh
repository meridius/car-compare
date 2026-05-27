#!/usr/bin/env bash
# Serve the site/ directory locally for development.
# Usage: ./bin/serve.sh [port]
#   default port: 8000

set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8000}"
DIR="site"

if [ ! -f "$DIR/data/cars.json" ]; then
  echo "cars.json not found — building..."
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
