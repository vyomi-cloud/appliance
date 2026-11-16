#!/usr/bin/env bash
# Run every AI-console smoke together against the Nano preview (Pyodide + service worker substrate).
#
#   consoles/tests/run-ai-smokes.sh [--port 8841] [--only <substring>] [--timeout 300]
#
# Starts consoles/nano_preview.mjs (tier max) if nothing listens on the port, runs each smoke with the same env the Nano
# runner (run-nano-smokes.mjs) gives them (BASE, UI_PATH=/nano/v4/<cloud>/, WIRE_PATH=/nano/_wire, NANO=1, SUBSTRATE=nano, SHOTS),
# prints PASS/FAIL per smoke and a summary, exit 1 if any fails. Screenshots land in $SHOTS_DIR (default /tmp/ai-smokes).
# Playwright: $PW, else each smoke's own fallback. Build the bundles first: (cd consoles && node build.mjs).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT=8841; ONLY=""; TMO=300
while [ $# -gt 0 ]; do case "$1" in --port) PORT=$2; shift 2;; --only) ONLY=$2; shift 2;; --timeout) TMO=$2; shift 2;; *) echo "unknown arg $1"; exit 2;; esac; done
BASE="http://127.0.0.1:$PORT"
# Playwright: a local install wins, else the shared one (some smokes hardcode a path that may not exist on this machine)
if [ -z "${PW:-}" ]; then for d in "$HERE/../node_modules/playwright" /Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright; do [ -d "$d" ] && PW="$d" && break; done; fi
export PW
SHOTS_DIR="${SHOTS_DIR:-/tmp/ai-smokes}"; mkdir -p "$SHOTS_DIR"

# smoke file : cloud lens
SMOKES="
smoke-aws-bedrock:aws
smoke-aws-bedrock-infer-tune:aws
smoke-aws-bedrockui-a:aws
smoke-aws-ragstudio:aws
smoke-limmodels:aws
smoke-limagents:aws
smoke-limflows:aws
smoke-limvector:aws
smoke-training-ui:aws
smoke-gcp-vertex:gcp
smoke-gcp-vertex-pages:gcp
smoke-limgcpgw:gcp
smoke-azure-aoai:azure
smoke-limflows-azure:azure
smoke-ai-import:aws
smoke-ai-foundry-agents:azure
"

STARTED=""
if ! curl -s -o /dev/null "$BASE/nano/"; then
  node "$HERE/../nano_preview.mjs" --port "$PORT" --tier max >/dev/null 2>&1 & STARTED=$!
  for _ in $(seq 1 40); do curl -s -o /dev/null "$BASE/nano/" && break; sleep 0.5; done
fi
trap '[ -n "$STARTED" ] && kill $STARTED 2>/dev/null' EXIT

pass=0; fail=0; failed=""
for entry in $SMOKES; do
  f="${entry%%:*}"; cloud="${entry##*:}"
  [ -n "$ONLY" ] && case " $ONLY " in *" $f "*) ;; *) continue;; esac
  [ -f "$HERE/$f.mjs" ] || { echo "SKIP $f (no such file)"; continue; }
  log="$SHOTS_DIR/$f.log"
  BASE="$BASE" UI_PATH="/nano/v4/$cloud/" WIRE_PATH="/nano/_wire" NANO=1 SUBSTRATE=nano SHOTS="$SHOTS_DIR/$f" OUT="$SHOTS_DIR/$f" \
    perl -e 'alarm shift; exec @ARGV' "$TMO" node "$HERE/$f.mjs" >"$log" 2>&1
  rc=$?
  nf=$(grep -cE '^\s*\[?FAIL\]? ' "$log"); np=$(grep -cE '^\s*\[?PASS\]? ' "$log")
  if [ $rc -eq 0 ] && [ "$nf" -eq 0 ]; then echo "PASS $f  ($np checks)"; pass=$((pass+1))
  else echo "FAIL $f  (rc=$rc, $np pass / $nf fail)  log: $log"; grep -E '^\s*\[?FAIL\]? ' "$log" | head -5 | sed 's/^/     /'; fail=$((fail+1)); failed="$failed $f"; fi
done
echo; echo "AI smokes: $pass passed, $fail failed${failed:+ ->$failed}"
[ $fail -eq 0 ]
