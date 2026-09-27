#!/usr/bin/env bash
# The whole daily pipeline for a scheduled host (the deploy/nas job container,
# via its entrypoint's `run-once`): the job the GitHub Actions cron used to do,
# moved to a residential IP because mobile.de's Akamai front blocks CI runners.
#
#   1. fetch origin/main and reset the clone to it, then re-exec the fresh copy
#   2. logic tests (the payload invariants are skipped — yesterday's payload may
#      predate today's code)
#   3. the four scrapers ONE AFTER ANOTHER (small host: two Chromiums plus a
#      pandas build would swap); a failed source keeps its previous state
#   4. build_data.py (+ the payload invariants, opt-in — see NAS_DAILY_PAYLOAD_TESTS)
#   5. publish: rolling `data` release (state + payload + history), the monthly
#      data-YYYY-MM snapshot once per month, then dispatch the Pages deploy
#
# Exit 0 only when every step and every source succeeded. A failed source still
# publishes the others (its state stays yesterday's, like CI's continue-on-error
# mobilede leg) but the job exits 1 at the end with one `FAILED: <source>` line
# each, so a notifier can hook on it. A failed logic test or build publishes
# nothing.
#
# Environment:
#   CAR_COMPARE_STATE_DIR     required. Per-source <slug>.parquet + scrape_history.json;
#                             must already hold every source's state (seed it once
#                             with bin/bootstrap-data.sh) — a missing previous state
#                             would make merge stamp every listing new and drop the
#                             archive from the next published release
#   GH_TOKEN_FILE             file holding a GitHub token (Contents RW for release
#                             uploads, Actions RW for the Pages dispatch)
#   NAS_DAILY_FETCH=1         do step 1. Off by default so a run from a working
#                             clone never resets it; the job image sets it on
#   NAS_DAILY_PUBLISH=0       skip step 5 (dry run: everything local)
#   NAS_DAILY_SOURCES         space-separated subset (default: all four)
#   NAS_DAILY_SOURCE_TIMEOUT  per-source `timeout` (default 3h)
#   NAS_DAILY_PAYLOAD_TESTS=1 also run tests/test_data_integrity.py on the fresh
#                             build. Off by default: on full state it peaks at
#                             ~3.2 GB RSS (more than a small host has), and CI
#                             never gated a publish on it. When on, a failure is
#                             reported (`FAILED: payload-invariants`, exit 1) but
#                             does not hold back the day's data.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1

log() { echo "[nas-daily $(date '+%F %T')] $*"; }
die() { log "FAILED: $*"; exit 1; }
# MemAvailable of the host (the container sees the host's /proc/meminfo) — the
# number to watch on a small box; logged around every heavy step.
mem() { awk '/^MemAvailable:/ {printf "%d MB available\n", $2/1024}' /proc/meminfo 2>/dev/null; }

# --- 1. fetch ----------------------------------------------------------------
# The reset rewrites this very file. bash reads a script incrementally, so the
# rest of the run must come from a fresh exec of the new copy, never from this
# process continuing into bytes that changed underneath it.
if [ "${NAS_DAILY_FETCH:-0}" = 1 ] && [ "${_NAS_DAILY_FETCHED:-}" != 1 ]; then
    git fetch --quiet origin main || die "git fetch origin main"
    git reset --quiet --hard FETCH_HEAD || die "git reset to origin/main"
    _NAS_DAILY_FETCHED=1 exec bash "$REPO/bin/nas-daily.sh" "$@"
fi
log "code $(git rev-parse --short HEAD) ($(git log -1 --format=%cs))"

STATE_DIR="${CAR_COMPARE_STATE_DIR:-}"
[ -n "$STATE_DIR" ] || die "CAR_COMPARE_STATE_DIR is not set"
export CAR_COMPARE_STATE_DIR="$STATE_DIR"
SOURCES="${NAS_DAILY_SOURCES:-sauto autodraft energycars mobilede}"
for src in $SOURCES; do
    [ -f "$STATE_DIR/$src.parquet" ] \
        || die "no previous state $STATE_DIR/$src.parquet — seed it with bin/bootstrap-data.sh"
done
log "state $STATE_DIR; $(mem)"

# --- 2. logic tests ------------------------------------------------------------
# Hermetic: no state override (tests fall back to the seed CSVs), payload
# invariants off. A red suite stops the run before any state is touched.
log "tests"
env -u CAR_COMPARE_STATE_DIR CAR_COMPARE_SKIP_PAYLOAD_TESTS=1 ./bin/test.sh \
    || die "tests (nothing scraped, nothing published)"

# --- 3. scrape -----------------------------------------------------------------
# run_source writes <slug>.parquet only after its scrape completed, so a failed
# or timed-out source leaves yesterday's state in place.
failed=()
for src in $SOURCES; do
    log "scrape $src; $(mem)"
    start=$SECONDS
    if timeout "${NAS_DAILY_SOURCE_TIMEOUT:-3h}" python -u -m scrapers.run --source "$src"; then
        log "scrape $src ok in $((SECONDS - start)) s"
    else
        log "scrape $src FAILED (exit $?) after $((SECONDS - start)) s — keeping previous state"
        failed+=("$src")
    fi
done

# --- 4. build + payload invariants ---------------------------------------------
# The history lives with the state (the clone is disposable); build_data reads
# and appends it in site/data, so it is copied in and back out around the build.
mkdir -p site/data
[ -f "$STATE_DIR/scrape_history.json" ] && cp "$STATE_DIR/scrape_history.json" site/data/
log "build; $(mem)"
start=$SECONDS
BUILD_TRIGGER=schedule python -u build/build_data.py || die "build_data.py (nothing published)"
log "build ok in $((SECONDS - start)) s; $(mem)"
if [ "${NAS_DAILY_PAYLOAD_TESTS:-0}" = 1 ]; then
    python -m unittest discover -s tests -p "test_data_integrity.py" \
        || failed+=("payload-invariants")
fi
cp site/data/scrape_history.json "$STATE_DIR/"

# --- 5. publish ----------------------------------------------------------------
if [ "${NAS_DAILY_PUBLISH:-1}" = 1 ]; then
    if [ -n "${GH_TOKEN_FILE:-}" ]; then
        GH_TOKEN="$(cat "$GH_TOKEN_FILE")" || die "cannot read GH_TOKEN_FILE"
        export GH_TOKEN
    fi
    [ -n "${GH_TOKEN:-}" ] || die "no GitHub token (set GH_TOKEN_FILE)"

    state_files=("$STATE_DIR"/*.parquet)   # every source's, not just this run's
    payload=(site/data/cars.parquet site/data/cars-archived.parquet
             site/data/cars-meta.json site/data/reference.json)

    log "publish to release 'data'"
    gh release view data >/dev/null 2>&1 || gh release create data \
        --title "Data (rolling)" \
        --notes "Current scraper state + built payload. Assets are clobbered daily; monthly data-YYYY-MM releases are the immutable history." \
        || die "gh release create data"
    gh release upload data --clobber "${state_files[@]}" "${payload[@]}" \
        site/data/scrape_history.json || die "gh release upload data"

    # First successful publish of the month freezes the snapshot. Keyed on
    # "does it exist yet", not "is it the 1st", so a failed 1st still gets one.
    tag="data-$(date +%Y-%m)"
    if ! gh release view "$tag" >/dev/null 2>&1; then
        log "monthly snapshot $tag"
        gh release create "$tag" \
            --title "Data snapshot $(date +%Y-%m)" \
            --notes "Immutable monthly snapshot (see docs/decisions/001-scalable-storage.md)." \
            "${state_files[@]}" "${payload[@]}" site/data/scrape_history.json \
            || die "gh release create $tag"
    fi

    log "dispatch the Pages deploy"
    gh workflow run scrape-and-deploy.yml --ref main -f deploy_only=true \
        || die "gh workflow run (release is published; Pages is stale)"
else
    log "NAS_DAILY_PUBLISH=0 — not publishing"
fi

if [ ${#failed[@]} -gt 0 ]; then
    for src in "${failed[@]}"; do log "FAILED: $src"; done
    exit 1
fi
log "done; $(mem)"
