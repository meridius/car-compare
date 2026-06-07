#!/usr/bin/env bash
# Triage tasks in TASKS.md ## New section.
# Runs non-interactively using a Haiku subagent for classification.
# Usage: ./bin/triage.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PROMPT="$(cat .claude/commands/triage.md)"

claude -p "$PROMPT" \
  --model haiku \
  --permission-mode auto \
  --allowedTools "Read,Edit,Write,Agent"
