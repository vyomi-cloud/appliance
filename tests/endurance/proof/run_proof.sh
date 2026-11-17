#!/bin/sh
# vyomi-endurance proof layers (SDK / CLI / UI) for the AWS estate.
#   run_proof.sh <endpoint> [tfstate] [out_dir]
# Prereqs: the estate is APPLIED against the server at <endpoint> (tests/endurance/run_estate.sh applies, or: estate/aws/run.sh apply -auto-approve
# -var=endpoint=http://host.docker.internal:<port>) and its terraform.tfstate is kept; the server runs in mesh mode for the UI layer:
#   python tests/endurance/proof/run_mesh_server.py <port>      (see docs/architecture/v4.0/branches/endurance-proof.md)
# <endpoint> is the host-reachable URL (http://127.0.0.1:<port>). Writes <out_dir>/proof.json, proof-detail.json, estate/coverage-map.proof.json.
# Env: PYTHON (venv with boto3+botocore), NODE_PATH (a node_modules holding playwright), CONSOLES_NODE_MODULES (to build wasm/v4/aws if missing).
set -u
EP="${1:?endpoint}"; HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../../.." && pwd)"
STATE="${2:-$HERE/../estate/aws/terraform.tfstate}"; OUT="${3:-$HERE/out}"; mkdir -p "$OUT"
PYTHON="${PYTHON:-$HOME/.vyomi-endurance/venv/bin/python}"; export PYTHON
free=$(df -g / | tail -1 | awk '{print $4}'); [ "$free" -lt 3 ] && { echo "DISK GUARD: only ${free} GiB free, stop"; exit 3; }
[ -f "$STATE" ] || { echo "no terraform state at $STATE: apply the estate first"; exit 2; }
if [ ! -f "$ROOT/wasm/v4/aws/main.js" ]; then
  [ -e "$ROOT/consoles/node_modules" ] || { [ -n "${CONSOLES_NODE_MODULES:-}" ] && ln -s "$CONSOLES_NODE_MODULES" "$ROOT/consoles/node_modules"; }
  (cd "$ROOT/consoles" && node build.mjs --cloud aws) >"$OUT/build.log" 2>&1 || { echo "v4 AWS console build failed (see $OUT/build.log)"; exit 2; }
fi
"$HERE/sdk/run_sdk.sh" "$EP" "$STATE" "$OUT/sdk.json" > "$OUT/sdk.log" 2>&1; echo "sdk: $(grep -c '^PASS' "$OUT/sdk.log") pass, $(grep -c '^FAIL' "$OUT/sdk.log") fail"
"$HERE/cli/run_cli.sh" "$EP" "$STATE" "$OUT/cli.json" > "$OUT/cli.log" 2>&1; echo "cli: $(grep -c '^PASS' "$OUT/cli.log") pass, $(grep -c '^FAIL' "$OUT/cli.log") fail"
node "$HERE/ui/run_ui.mjs" "$EP" "$STATE" "$OUT/ui.json" > "$OUT/ui.log" 2>&1; echo "ui:  $(grep -c '^PASS' "$OUT/ui.log") pass, $(grep -c '^FAIL' "$OUT/ui.log") fail"
[ -f "$OUT/ui.json" ] || echo '{"fatal":"ui runner produced no output","checks":{}}' > "$OUT/ui.json"
"$PYTHON" "$HERE/aggregate.py" "$OUT/sdk.json" "$OUT/cli.json" "$OUT/ui.json" "$OUT"
rc=$?; cp "$OUT/proof.json" "$HERE/proof.json"; exit $rc
