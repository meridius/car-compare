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

echo "Serving $DIR at http://localhost:$PORT"
python3 -m http.server "$PORT" -d "$DIR"
