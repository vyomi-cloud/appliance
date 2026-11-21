#!/usr/bin/env bash
# Guardrail suite: one check per premise item of docs/architecture/v4.0/MCP-GUARDRAILS-INCIDENT-DESIGN.md.
# Deterministic, no network, no Docker. Used as a hard release gate by .github/workflows/guardrails.yml.
#
#   bash tools/guardrails/run.sh            # from the repo root
#   WS_PKG=<path to ws> PY=<python with fastapi, httpx, pytest> bash tools/guardrails/run.sh
#
# Exit 0 only when every implemented check passes. Items with no automated check yet are listed as GAP (not a failure),
# so the summary always shows what the gate does NOT cover.
set -uo pipefail
cd "$(dirname "$0")/../.."

PY="${PY:-python3}"
NODE="${NODE:-node}"
fail=0
rows=()

run() {   # run <item(s)> <description> <command...>
  local item="$1" desc="$2"; shift 2
  local log; log="$(mktemp)"
  if "$@" >"$log" 2>&1; then
    rows+=("| $item | $desc | PASS |")
    echo "PASS  [$item] $desc"
  else
    rows+=("| $item | $desc | **FAIL** |")
    echo "FAIL  [$item] $desc"; sed 's/^/      /' "$log" | tail -40
    fail=1
  fi
  rm -f "$log"
}
gap() { rows+=("| $1 | $2 | GAP: $3 |"); echo "GAP   [$1] $2 ($3)"; }
# go_tests <name>...: run exactly these Go tests and require every one to report PASS. `go test -run` exits 0 when the pattern
# matches nothing, so a renamed test would otherwise turn the gate green without running anything.
go_tests() {
  local pat out rc=0; pat="^($(IFS='|'; echo "$*"))\$"
  out="$(go -C cmd/vyomi test -count=1 -v -run "$pat" . 2>&1)" || rc=1
  echo "$out" | tail -20
  for t in "$@"; do echo "$out" | grep -q -- "--- PASS: $t " || { echo "missing PASS for $t"; rc=1; }; done
  return "$rc"
}
skip() { rows+=("| $1 | $2 | SKIP: $3 |"); echo "SKIP  [$1] $2 ($3)"; }

# Threat A: an agent misusing the MCP. The tool surface is pinned (7 read-only tools + 1 writer).
run "A" "MCP tool surface pinned (7 read-only + 1 writer); the writer carries destructiveHint on the wire" \
  go_tests TestMCPToolSurfaceIsPinned TestMCPToolAnnotationsOnTheWire
run "A" "vyomi_write_env refuses paths outside the project and non-.env.vyomi names" \
  go_tests TestMCPWriteEnv TestMCPWriteEnvRequiresExplicitApproval

# Threat B: tampering with the core. Enforced on the Mesh host and in the tunnel, for every caller.
run "1, 8" "vyomi-gate: core containers, injection strings and unknown verbs never reach docker" "$NODE" wasm/relay/test-mesh-gate.mjs
run "1, 8" "tunnel: core names refused, \`api\` reaches only 9000/9443, nothing core is listed" "$NODE" wasm/relay/test-mesh-ssh-transport.mjs
run "5, 7" "simulator: session token limits hold; admin controls closed on a Mesh" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_mcp_guardrails_server.py
run "5" "Ed25519 session tokens: pinned keys only; a leaked-key v1 token is refused once v1 is retired (Mesh + relay agree)" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_mesh_session_v2.py
run "5" "relay: v2 verification, forged/unknown-kid/edited tokens refused" "$NODE" wasm/relay/test-mesh-session-v2.mjs
# F2 stays a GAP until the code constant retires v1 (and a portal key is pinned). The env cannot change either value.
if "$PY" -c 'import sys; sys.path.insert(0, "."); from core import mesh_session as m; sys.exit(0 if (not m.V1_ACCEPTED and m.TRUSTED_KEYS) else 1)' 2>/dev/null; then
  rows+=("| 5 | v1 (HMAC) session tokens retired; portal key pinned | PASS |"); echo "PASS  [5] v1 (HMAC) session tokens retired; portal key pinned"
else
  gap "5" "v1 (HMAC) session tokens still accepted, so a Codespace owner can mint their own (F2)" "after ~8 h of v2-only minting (portal MESH_SESSION_TOKEN_VERSION=v2), set V1_ACCEPTED = False in core/mesh_session.py and wasm/relay/mesh-session.mjs"
fi

gap "2" "licence fingerprint tamper detection" "not built (portal integrity check, MESH-SOFTWARE-PROTECTION layer 6)"
gap "3" "core egress only via the tunnel" "no network policy yet"
gap "4" "no code/config injected into a core container" "needs the core vs user-workload boundary defined"
gap "6" "no runtime instrumentation of agents" "item not yet defined"

summary="$(printf '%s\n' "| Item | Check | Result |" "|---|---|---|" "${rows[@]}")"
echo; echo "$summary"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  { echo "## Guardrail suite"; echo; echo "$summary"; } >> "$GITHUB_STEP_SUMMARY"
fi
exit "$fail"
