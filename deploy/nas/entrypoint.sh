#!/bin/sh
# car-compare job container entrypoint (baked into deploy/nas/Dockerfile).
#
# Modes, chosen by the first argument:
#
#   schedule (the default)  render a crontab from $CAR_COMPARE_CRON and hand it
#                           to supercronic — the long-running container
#   run-once                one full pipeline run now (bin/nas-daily.sh from
#                           the bind-mounted clone); exits 1 on any failure
#   anything else           exec'd verbatim: `sh`, `./bin/test.sh`,
#                           `python -m scrapers.run --source sauto`
#
# The pipeline command is defined once, here, and the crontab entry calls this
# script back with `run-once` rather than repeating it, so the schedule cannot
# drift from the manual invocation.
#
# This file changes only with an image rebuild; everything the run does lives
# in bin/nas-daily.sh, which comes from origin/main on every firing.
set -eu

REPO="${CAR_COMPARE_REPO:-/repo}"
CRON="${CAR_COMPARE_CRON:-0 7 * * *}"
# /repo belongs to the host user and / is not writable for it; $HOME is /tmp.
CRONTAB_FILE="${CAR_COMPARE_CRONTAB_FILE:-/tmp/car-compare.crontab}"

case "${1:-schedule}" in
    schedule)
        printf '%s /usr/local/bin/car-compare-entrypoint run-once\n' "$CRON" > "$CRONTAB_FILE"
        # The two things a schedule gets wrong — the expression and the
        # timezone — visible in `docker logs` without waiting for a firing.
        echo "car-compare: schedule '$CRON', TZ=${TZ:-unset}, now $(date '+%F %T %Z')"
        # -passthrough-logs: the pipeline's own lines reach docker logs
        # unwrapped, so they read the same as a manual run-once.
        exec supercronic -passthrough-logs "$CRONTAB_FILE"
        ;;
    run-once)
        shift
        exec "$REPO/bin/nas-daily.sh" "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
