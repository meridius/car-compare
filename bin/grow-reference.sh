#!/usr/bin/env bash
# Deterministic phases of grow-reference. The agentic research + review gate is the
# interactive .claude/commands/grow-reference.md flow.
#   ./bin/grow-reference.sh gaps --fuel ev --rebuild --top 30
#   ./bin/grow-reference.sh validate --fuel ev --in tmp/ref-gap/candidates.json
#   ./bin/grow-reference.sh apply --fuel ev --in tmp/ref-gap/candidates.json.ok.json
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 build/reference_gap.py "$@"
