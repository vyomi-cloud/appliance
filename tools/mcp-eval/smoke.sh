#!/usr/bin/env bash
# Smoke-test the `vyomi mcp` server end to end over stdio: protocol handshake,
# every tool, a resource, and the write-safety rules. Needs jq.
#
#   tools/mcp-eval/smoke.sh                     # uses cmd/vyomi/vyomi (go build first)
#   tools/mcp-eval/smoke.sh /path/to/vyomi      # any binary: vyomi, vyomi-mcp, ...
#   SCAN=~/projects/siftly tools/mcp-eval/smoke.sh   # also scan a real project
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="${1:-$HERE/../../cmd/vyomi/vyomi}"
command -v jq >/dev/null || { echo "needs jq (brew install jq)"; exit 2; }
[ -x "$BIN" ] || { echo "no binary at $BIN (cd cmd/vyomi && go build -o vyomi .)"; exit 2; }
case "$(basename "$BIN")" in vyomi-mcp*) ARGS=() ;; *) ARGS=(mcp) ;; esac

# A tiny fixture project so the scan has known answers.
FIX="$(mktemp -d)"; OUT="$(mktemp -d)"; trap 'rm -rf "$FIX" "$OUT"' EXIT
mkdir -p "$FIX/app" "$FIX/node_modules/x"
printf "import boto3\ns3 = boto3.client('s3')\n" > "$FIX/app/store.py"
printf "from azure.servicebus import ServiceBusClient\n" > "$FIX/app/worker.py"
printf "require('@aws-sdk/client-kinesis')\n" > "$FIX/node_modules/x/index.js"

call() { printf '{"jsonrpc":"2.0","id":%s,"method":"tools/call","params":{"name":"%s","arguments":%s}}\n' "$1" "$2" "$3"; }
{
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
  echo '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
  call 3 vyomi_status '{}'
  call 4 vyomi_services '{"cloud":"aws","live":false}'
  call 5 vyomi_env '{"cloud":"azure","lang":"python"}'
  call 6 vyomi_scan_repo "{\"path\":\"$FIX\"}"
  call 7 vyomi_write_env "{\"path\":\"$OUT\",\"clouds\":[\"aws\"]}"
  call 8 vyomi_write_env "{\"path\":\"$OUT\",\"clouds\":[\"aws\"]}"
  echo '{"jsonrpc":"2.0","id":9,"method":"resources/read","params":{"uri":"vyomi://env/gcp"}}'
  [ -n "${SCAN:-}" ] && call 10 vyomi_scan_repo "{\"path\":\"$SCAN\",\"max_files\":50000}"
} | "$BIN" ${ARGS[@]+"${ARGS[@]}"} 2>"$OUT/stderr" > "$OUT/replies"   # bash 3.2-safe empty array

r()    { jq -c "select(.id==$1)" "$OUT/replies"; }
text() { r "$1" | jq -r '.result.content[0].text'; }
pass=0; fail=0
check() {  # $1 label, $2 command that must succeed
  if eval "$2" >/dev/null 2>&1; then echo "  PASS  $1"; pass=$((pass+1)); else echo "  FAIL  $1"; fail=$((fail+1)); fi
}

echo "vyomi mcp smoke test: $BIN ${ARGS[*]-}"
check "stdout is pure JSON-RPC"            "jq -e . '$OUT/replies'"
check "handshake (serverInfo.name=vyomi)"  "r 1 | jq -e '.result.serverInfo.name==\"vyomi\"'"
check "5 tools listed"                      "r 2 | jq -e '.result.tools|length==5'"
check "vyomi_status answers"                "text 3 | jq -e 'has(\"running\")'"
check "vyomi_services: AWS services known"  "text 4 | jq -e '.clouds.aws.services|length>10'"
check "vyomi_env: Azure connection string"  "text 5 | jq -e '.env_text|contains(\"AZURE_STORAGE_CONNECTION_STRING\")'"
check "vyomi_env: Service Bus AMQP caveat"  "text 5 | jq -e '.notes|tostring|contains(\"AMQP\")'"
check "scan: S3 found + released"           "text 6 | jq -e '.clouds.aws[]|select(.service==\"s3\" and .status==\"released\")'"
check "scan: Service Bus warning"           "text 6 | jq -e '.clouds.azure[]|select(.service==\"servicebus\")|.warning|contains(\"AMQP\")'"
check "scan: node_modules skipped"          "! text 6 | jq -e '.clouds.aws[]|select(.service==\"kinesis\")'"
check "write_env: file written"             "test -s '$OUT/.env.vyomi'"
check "write_env: refuses to overwrite"     "r 8 | jq -e '.result.isError==true'"
check "resource vyomi://env/gcp"            "r 9 | jq -e '.result.contents[0].text|contains(\"PUBSUB_EMULATOR_HOST\")'"

running="$(text 3 | jq -r '.running')"
if [ "$running" = "true" ]; then
  echo "  INFO  simulator: running, tier $(text 3 | jq -r '.license.active_tier // .health.tier'), readiness $(text 3 | jq -r '.readiness.overall_pct // "?"')%"
else
  echo "  INFO  simulator: not running (start it with \`vyomi up\` to test live status)"
fi
if [ -n "${SCAN:-}" ]; then
  echo "  SCAN  $SCAN"
  text 10 | jq -r '.summary[]' | sed 's/^/        /'
fi
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
