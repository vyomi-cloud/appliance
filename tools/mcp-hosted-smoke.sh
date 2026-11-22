#!/usr/bin/env bash
# Smoke test for the hosted Vyomi MCP server (docs/architecture/v4.0/HOSTED-MCP-IMPLEMENTATION-PLAN.md §3, §6).
#
#   go run ./cmd/vyomi mcp --hosted --listen :8080
#   tools/mcp-hosted-smoke.sh http://localhost:8080/mcp     # local or Docker
#   tools/mcp-hosted-smoke.sh https://vyomi.cloud/mcp       # production
#
# The base URL is the one an MCP client is given. Behind the portal's /mcp route the prefix is trimmed, so the
# server also answers on "/" — the script checks both shapes of every path (D-I6).
# Needs curl only. Exits non-zero on the first miss and prints what it got.
set -uo pipefail

BASE="${1:-http://localhost:8080/mcp}"
BASE="${BASE%/}"
ROOT="${BASE%/mcp}"   # the same server without the /mcp prefix
# PR 1 ships four tools; PR 2 takes this to eight.
EXPECT_TOOLS="check_capability get_code_snippet get_sdk_settings list_services"

fail=0
pass() { printf 'PASS  %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n      %s\n' "$1" "${2//$'\n'/$'\n'      }"; fail=1; }

# post <name> <want-status> <body> [curl args...]: POSTs to BASE and checks the status, printing the body on a miss.
post() {
  local name="$1" want="$2" body="$3"; shift 3
  local out code
  out="$(curl -sS -o /tmp/mcp-smoke.$$ -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
         --max-time 20 "$@" --data-binary "$body" "$BASE" 2>&1)" || { bad "$name" "curl: $out"; return 1; }
  code="$out"
  BODY="$(cat /tmp/mcp-smoke.$$ 2>/dev/null)"; rm -f /tmp/mcp-smoke.$$
  if [ "$code" != "$want" ]; then bad "$name" "status $code, want $want: $BODY"; return 1; fi
  pass "$name (HTTP $code)"
}

has() { case "$BODY" in (*"$1"*) return 0;; (*) return 1;; esac; }

echo "Hosted Vyomi MCP smoke test: $BASE"

# ── health ───────────────────────────────────────────────────────────────────
for url in "$BASE/healthz" "$ROOT/healthz"; do
  out="$(curl -sS -o /tmp/mcp-smoke.$$ -w '%{http_code}' --max-time 20 "$url" 2>&1)" || { bad "GET $url" "curl: $out"; continue; }
  BODY="$(cat /tmp/mcp-smoke.$$ 2>/dev/null)"; rm -f /tmp/mcp-smoke.$$
  if [ "$out" = "200" ] && has '"ok":true' && has '"version"'; then pass "GET $url -> $BODY"
  elif [ "$out" = "404" ] && [ "$url" = "$ROOT/healthz" ]; then pass "GET $url -> 404 (no prefix trimming here; fine locally)"
  else bad "GET $url" "status $out: $BODY"; fi
done

# ── initialize, tools/list, one call per tool ────────────────────────────────
post "initialize" 200 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"mcp-hosted-smoke","version":"1"}}}' \
  -H 'MCP-Protocol-Version: 2025-06-18'
has '"protocolVersion"' || bad "initialize negotiates a protocol version" "$BODY"
has '"instructions"'    || bad "initialize returns instructions" "$BODY"
has '"title":"Vyomi"'   || bad 'initialize serverInfo.title is "Vyomi"' "$BODY"

post "notifications/initialized -> 202 empty" 202 '{"jsonrpc":"2.0","method":"notifications/initialized"}'
[ -z "$BODY" ] || bad "a notification must have an empty body" "$BODY"

post "tools/list" 200 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
for tool in $EXPECT_TOOLS; do
  has "\"name\":\"$tool\"" || bad "tools/list contains $tool" "$BODY"
done
has '"readOnlyHint":true' || bad "tools carry readOnlyHint" "$BODY"
case "$BODY" in (*'"destructiveHint":true'*) bad "no hosted tool may be destructive" "$BODY";; esac
case "$BODY" in (*'"path"'*) bad "no hosted tool may take a path" "$BODY";; esac

call() { # call <tool> <arguments-json>
  post "tools/call $1" 200 "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}" || return
  case "$BODY" in (*'"isError":true'*) bad "tools/call $1 returned an error" "$BODY";; esac
}
for tool in $EXPECT_TOOLS; do
  case "$tool" in
    list_services)              call "$tool" '{"cloud":"aws","home":"nano"}';;
    check_capability)           call "$tool" '{"query":"bucket versioning"}';;
    get_code_snippet)           call "$tool" '{"cloud":"aws","service":"s3","lang":"cli","home":"nano"}';;
    get_sdk_settings)           call "$tool" '{"cloud":"aws","home":"nano","format":"dotenv"}';;
    get_scan_rules)             call "$tool" '{"languages":["python"]}';;
    summarize_scan_hits)        call "$tool" '{"home":"nano","hits":[{"rule":"aws-python-1","file":"app.py","line":3,"token":"s3"}]}';;
    propose_env_file)           call "$tool" '{"clouds":["aws"],"home":"nano"}';;
    propose_agents_md_section)  call "$tool" '{"clouds":["aws"]}';;
    *)                          bad "tools/call $tool" "the smoke script has no arguments for this tool";;
  esac
done

# ── D-I2: no resources in hosted v1 ──────────────────────────────────────────
post "resources/list is empty" 200 '{"jsonrpc":"2.0","id":3,"method":"resources/list"}'
has '"resources":[]' || bad "hosted resources/list must be empty" "$BODY"

# ── D-I6: every path shape takes POST, with no redirect ──────────────────────
for url in "$BASE" "$BASE/" "$ROOT" "$ROOT/"; do
  out="$(curl -sS -o /dev/null -w '%{http_code} %{num_redirects} %{redirect_url}' --max-time 20 \
         -X POST -H 'Content-Type: application/json' \
         --data-binary '{"jsonrpc":"2.0","id":4,"method":"ping"}' "$url" 2>&1)" || { bad "POST $url" "curl: $out"; continue; }
  set -- $out
  code="$1"; redirects="${2:-0}"; location="${3:-}"
  if [ "$code" = "200" ] && [ "$redirects" = "0" ]; then pass "POST $url -> 200, no redirect"
  else bad "POST $url" "status $code after $redirects redirect(s) ${location:+-> $location}; a redirect breaks POST"; fi
done

# ── method and input limits ──────────────────────────────────────────────────
for method in GET DELETE; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -X "$method" "$BASE" 2>&1)"
  if [ "$code" = "405" ]; then pass "$method $BASE -> 405"; else bad "$method $BASE" "status $code, want 405"; fi
done

big="$(head -c 300000 /dev/zero | tr '\0' 'x')"
post "oversize body -> 413" 413 "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"check_capability\",\"arguments\":{\"query\":\"$big\"}}}"
post "JSON-RPC batch -> 400" 400 '[{"jsonrpc":"2.0","id":6,"method":"tools/list"}]'
post "invalid JSON -> 400" 400 '{"jsonrpc":'
post "unknown MCP-Protocol-Version -> 400" 400 '{"jsonrpc":"2.0","id":7,"method":"ping"}' -H 'MCP-Protocol-Version: 2099-01-01'
post "unknown browser Origin -> 403" 403 '{"jsonrpc":"2.0","id":8,"method":"ping"}' -H 'Origin: https://evil.example'

echo
if [ "$fail" = 0 ]; then echo "All hosted MCP smoke checks passed against $BASE"; else echo "Hosted MCP smoke test FAILED against $BASE"; fi
exit "$fail"
