#!/usr/bin/env bash
# Run the offline test suite (stdlib unittest — no extra deps, no network).
# Fast inner loop for logic/build changes: matching golden tests + data-integrity
# invariants over the built site/data/cars.json.
#   ./bin/test.sh            # all tests
#   ./bin/test.sh -v         # verbose
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 -m unittest discover -s tests -p "test_*.py" "$@"
