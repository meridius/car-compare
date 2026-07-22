#!/usr/bin/env bash
# Parallel research workers for the reference-growth loop: N workers drain
# tmp/ref-gap/queue.txt (written by build/ref_batch_pick.py), each calling
# `./bin/ai-match-one.sh research LINK` serially. Atomic dispensing via flock.
#
# Usage: RESET_CURSOR=1 ./bin/ref-batch-workers.sh [WORKERS] [ID_OFFSET]
#   RESET_CURSOR=1  start from the top of the queue (first launch);
#                   omit to resume/join a running queue (extra workers).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

WORKERS="${1:-16}"
OFFSET="${2:-0}"
QUEUE="tmp/ref-gap/queue.txt"
LOG_DIR="tmp/ref-gap/logs"
LOCK="tmp/ref-gap/queue.lock"
CURSOR="tmp/ref-gap/queue.cursor"
mkdir -p "$LOG_DIR"

[[ -f "$QUEUE" ]] || { echo "chybí $QUEUE — spusť build/ref_batch_pick.py" >&2; exit 1; }
[[ "${RESET_CURSOR:-}" == "1" || ! -f "$CURSOR" ]] && echo 0 > "$CURSOR"

next_link() {
  (
    flock 9
    local n total
    n=$(cat "$CURSOR")
    total=$(wc -l < "$QUEUE")
    if (( n >= total )); then echo ""; return; fi
    echo $((n + 1)) > "$CURSOR"
    sed -n "$((n + 1))p" "$QUEUE"
  ) 9>"$LOCK"
}

worker() {
  local id="$1" link
  while true; do
    link=$(next_link)
    [[ -z "$link" ]] && break
    echo "[w$id] research: $link"
    if ./bin/ai-match-one.sh research "$link" \
        > "$LOG_DIR/w$id-$(echo -n "$link" | md5sum | cut -c1-10).log" 2>&1; then
      echo "[w$id] OK: $link"
    else
      echo "[w$id] FAIL: $link"
    fi
  done
  echo "[w$id] done"
}

for i in $(seq 1 "$WORKERS"); do
  worker "$((OFFSET + i))" &
done
wait
echo "ALL WORKERS DONE"
