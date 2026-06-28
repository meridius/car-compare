#!/usr/bin/env bash
# Execute the next unblocked Atomic task from TASKS.md.
# Implements, verifies, commits, and marks the task done.
# Usage: ./bin/ai-tasks-work.sh [--all]
#   --all  keep running until no unblocked tasks remain (skips flow:feature-dev tasks)

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PROMPT="$(cat .claude/commands/tasks-work.md)"

# Append instruction to skip feature-dev tasks when running in --all mode
PROMPT_ALL="$PROMPT

When running: if the selected task has flow:feature-dev, skip it, print \"Skipping #N <task> (feature-dev — run interactively)\", and pick the next eligible ralph task instead. If only feature-dev tasks remain, print the skip summary and stop."

run_once() {
  local prompt="$1"
  claude -p "$prompt" \
    --model sonnet \
    --permission-mode auto
}

if [[ "${1:-}" == "--all" ]]; then
  while true; do
    tmpfile=$(mktemp)
    run_once "$PROMPT_ALL" | tee "$tmpfile"
    OUTPUT=$(cat "$tmpfile")
    rm -f "$tmpfile"
    if echo "$OUTPUT" | grep -qE "No unblocked Atomic tasks|only feature-dev tasks remain"; then
      # Print any skipped feature-dev tasks as a reminder
      echo ""
      echo "Pending feature-dev tasks (run /tasks-work interactively):"
      grep -A1 'flow:feature-dev' TASKS.md | grep '^\- \[ \]' || echo "  (none)"
      break
    fi
  done
else
  run_once "$PROMPT"
fi
