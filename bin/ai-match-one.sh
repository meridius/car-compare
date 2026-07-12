#!/usr/bin/env bash
# Fix one unpaired/uncertain ICE listing end-to-end: diagnose why it pairs
# badly, derive a candidate reference row, AI-research its display specs,
# apply, rebuild, test. Wraps build/diagnose_unpaired.py.
#
# AI usage per command — everything not marked [AI] is deterministic, 0 tokens:
#   pick [N]       no AI — rank worst-matched listings from state
#   diagnose LINK  no AI — per-field score breakdown + candidate row + simulation
#   research LINK  [AI] one `claude -p` Opus call with web search (~60–100k
#                  tokens, the only paid step in the loop; AI_DRY=1 prints the
#                  prompt instead of calling)
#   apply LINK     no AI — range-validated append to ice_specs.csv + rebuild + tests
#   full LINK      diagnose + research + apply (AI cost = the one research call)
#
# Usage: ./bin/ai-match-one.sh pick [N]
#        ./bin/ai-match-one.sh full "https://www.sauto.cz/osobni/detail/..."
# Needs real state first: ./bin/bootstrap-data.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

OUTDIR="tmp/ref-gap"
mkdir -p "$OUTDIR"

slug() { echo -n "$1" | md5sum | cut -c1-10; }

require_state() {
  ls scrapers/data/scrapes/*.parquet >/dev/null 2>&1 \
    || { echo "chybí state parquety — spusť ./bin/bootstrap-data.sh" >&2; exit 1; }
}

cmd_pick() {  # no AI
  require_state
  python3 build/diagnose_unpaired.py pick --n "${1:-15}"
}

cmd_diagnose() {  # no AI
  require_state
  local link="$1" s; s=$(slug "$1")
  python3 build/diagnose_unpaired.py explain --link "$link"
  python3 build/diagnose_unpaired.py candidate --link "$link" --out "$OUTDIR/cand-$s.json"
  echo
  echo "kandidát: $OUTDIR/cand-$s.json — další krok: ./bin/ai-match-one.sh research \"$link\""
}

cmd_research() {  # [AI] — the single Opus call of the loop
  local link="$1" s; s=$(slug "$1")
  local cand="$OUTDIR/cand-$s.json" out="$OUTDIR/research-$s.json"
  [[ -f "$cand" ]] || { echo "chybí $cand — spusť nejdřív diagnose" >&2; exit 1; }

  # Embed only the candidate object — the wrapper's cluster_links can be
  # thousands of URLs and once blew execve's argument-size limit.
  local cand_row prompt
  cand_row=$(python3 -c "
import json
d = json.load(open('$cand', encoding='utf-8'))
print(json.dumps(d.get('candidate', d), ensure_ascii=False, indent=1))")

  prompt="Research the real EU-market car (model year 2021+) behind this candidate reference row derived from Czech/German marketplace listings:

$cand_row

1. Confirm this factory configuration really ships in the EU 2021+ (exists true/false). Watch for scraper-fabricated hybrid variants that never existed.
2. Fill display specs for the most common EU variant (note which) from official manufacturer material / ADAC / auto-data.net / Wikipedia:
   generation label (\"Gen N\" style), seat count, combined WLTP consumption l/100km, trunk litres (seats up, 5-seat config behind 2nd row), interior noise dB, drag coefficient Cd (real published -> cd_source \"reálné\", body-shape estimate -> \"odhad\").
3. Self-verify consumption and trunk against a SECOND independent source; on >15-20% conflict return \"\" for that field. Never invent — \"\" when not found.

Return ONLY this JSON object, numbers as dot-decimal strings, no prose:
{\"exists\": true, \"variant_note\": \"\", \"generace\": \"\", \"seats\": \"\", \"consumption_l100km\": \"\", \"trunk_l\": \"\", \"noise_db\": \"\", \"cd\": \"\", \"cd_source\": \"\", \"confidence\": \"high|medium|low\", \"sources\": []}

IMPORTANT: your FINAL message must be nothing but that JSON object — no prose,
no commentary, no remarks about files or the working directory."

  if [[ "${AI_DRY:-}" == "1" ]]; then
    echo "$prompt"
    return
  fi

  # [AI] Opus + web tools; output is the JSON contract diagnose_unpaired.py
  # apply expects. Runs from a neutral temp dir so the nested claude doesn't
  # load this repo's CLAUDE.md/hooks and pollute its final message (a run that
  # saw the repo replied about git status instead of the JSON, and the old
  # `claude | python` pipeline masked the parse failure behind tail's exit 0).
  # One retry on unparsable output, then fail loud.
  local abs_out tmpdir raw attempt
  abs_out="$PWD/$out"
  tmpdir=$(mktemp -d)
  raw="$tmpdir/raw.txt"
  for attempt in 1 2; do
    (cd "$tmpdir" && claude -p "$prompt" \
      --model opus \
      --permission-mode auto \
      --allowedTools "WebSearch,WebFetch") > "$raw" || true
    if python3 - "$raw" "$abs_out" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8").read()
start, end = raw.find('{'), raw.rfind('}')
if start < 0 or end <= start:
    sys.exit(1)
try:
    data = json.loads(raw[start:end + 1])
except ValueError:
    sys.exit(1)
json.dump(data, open(sys.argv[2], "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("výzkum zapsán: %s (confidence: %s)" % (sys.argv[2], data.get("confidence")))
PY
    then
      rm -rf "$tmpdir"
      return 0
    fi
    echo "pokus $attempt: odpověď bez parsovatelného JSON, zkouším znovu" >&2
  done
  echo "výzkum selhal — žádný JSON v odpovědi (surová odpověď: $raw)" >&2
  return 1
}

cmd_apply() {  # no AI
  require_state
  local link="$1" s; s=$(slug "$1")
  local cand="$OUTDIR/cand-$s.json" research="$OUTDIR/research-$s.json"
  [[ -f "$research" ]] || { echo "chybí $research — spusť nejdřív research" >&2; exit 1; }
  python3 build/diagnose_unpaired.py apply --candidate "$cand" --research "$research" --dry-run
  read -r -p "aplikovat? [y/N] " ok
  [[ "$ok" == "y" ]] || { echo "zrušeno"; exit 0; }
  python3 build/diagnose_unpaired.py apply --candidate "$cand" --research "$research"
  python3 build/build_data.py
  ./bin/test.sh
}

cmd_full() {
  cmd_diagnose "$1"
  cmd_research "$1"   # [AI]
  cmd_apply "$1"
}

case "${1:-}" in
  pick)     cmd_pick "${2:-15}" ;;
  diagnose) cmd_diagnose "${2:?LINK}" ;;
  research) cmd_research "${2:?LINK}" ;;
  apply)    cmd_apply "${2:?LINK}" ;;
  full)     cmd_full "${2:?LINK}" ;;
  *)        sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
