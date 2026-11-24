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

# Threat A: an agent misusing the MCP. The tool surface is pinned (8 read-only tools + 1 writer).
run "A" "MCP tool surface pinned (8 read-only + 1 writer); the writer carries destructiveHint on the wire" \
  go_tests TestMCPToolSurfaceIsPinned TestMCPToolAnnotationsOnTheWire
run "A" "vyomi_write_env refuses paths outside the project and non-.env.vyomi names" \
  go_tests TestMCPWriteEnv TestMCPWriteEnvRequiresExplicitApproval
run "A" "vyomi_agents_md only proposes AGENTS.md text: it writes nothing, names no endpoints or credentials, and refuses symlinks and bad input" \
  go_tests TestAgentsMDNeverWrites TestAgentsMDSectionIsSafe

# Threat A, hosted surface (docs/architecture/v4.0/HOSTED-MCP-IMPLEMENTATION-PLAN.md §4): the server at
# https://vyomi.cloud/mcp answers from embedded knowledge only. It cannot see the caller's machine, so it has no
# writer, no outbound network, no file access and no path input. Pinned here because the tool contract is what the
# OpenAI and Claude directories review.
run "A" "hosted MCP tool surface pinned (hosted: 8 read-only, 0 writers); annotations and tool names on the wire" \
  go_tests TestHostedToolSurfaceIsPinned TestHostedToolAnnotationsOnTheWire
run "A" "hosted MCP reaches no network (not even a URL a caller supplies) and touches no file; no path input" \
  go_tests TestHostedToolsMakeNoOutboundRequests TestHostedServerCannotDial TestHostedToolsTouchNoFiles TestHostedSchemasHaveNoPath
run "A" "hosted MCP homes are named, never probed; no resources; local stdio mode unchanged" \
  go_tests TestNamedHomeNeverProbesOrReadsEnv TestHostedInitializeAndNoResources TestHostedKnowledgeMatchesLocal
run "A" "hosted MCP descriptions state purpose, use, inputs and no side effects, with no tier pricing or upgrade wording" \
  go_tests TestHostedDescriptionsAreComplete TestHostedTextHasNoPricingOrUpgradeWording
run "A" "hosted MCP HTTP limits: 256 KiB body, no batches, POST only, Origin and protocol-version checks, panic contained" \
  go_tests TestHostedHTTPPathsAcceptPostWithoutRedirect TestHostedHTTPMethodsOtherThanPost TestHostedHTTPBodyLimit TestHostedHTTPRejectsBatchesAndBadJSON TestHostedHTTPOriginAndProtocolVersionHeaders TestHostedHTTPRecoversFromPanic
run "A, 7" "hosted MCP rate limits per client with hashed keys; the request log carries no arguments and no addresses" \
  go_tests TestHostedHTTPRateLimit TestRateLimiterKeysAreHashed TestHostedHTTPLogHasNoArgumentsOrAddresses
run "A" "hosted MCP scan and proposals: no source text accepted, hits and texts bounded, answers equal the local tools" \
  go_tests TestHostedScanHitsRejectSourceText TestHostedScanParityWithLocalScan TestHostedProposeEnvFileMatchesWriteEnv TestHostedProposeAgentsMDMatchesLocal
run "A" "hosted MCP takes no URL, token, key or secret: the Nano relay URL stays on the user's machine (placeholder only)" \
  go_tests TestHostedNanoRelayIsAPlaceholderNeverAnInput

# Threat B: tampering with the core. Enforced on the Mesh host and in the tunnel, for every caller.
run "1, 8" "vyomi-gate: core containers, injection strings and unknown verbs never reach docker" "$NODE" wasm/relay/test-mesh-gate.mjs
run "1, 8" "tunnel: core names refused, \`api\` reaches only 9000/9443, nothing core is listed" "$NODE" wasm/relay/test-mesh-ssh-transport.mjs
run "5, 7" "simulator: session token limits hold; admin controls closed on a Mesh" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_mcp_guardrails_server.py
run "5" "Ed25519 session tokens: pinned keys only; a leaked-key v1 token is refused once v1 is retired (Mesh + relay agree)" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_mesh_session_v2.py
run "5" "relay: v2 verification, forged/unknown-kid/edited tokens refused" "$NODE" wasm/relay/test-mesh-session-v2.mjs
run "5" "keygen prints the exact portal setting names as paste-only values; refuses kids the portal refuses" \
  "$PY" -m pytest -q -p no:cacheprovider tests/test_mesh_session_keygen.py
run "5" "Mesh boot script (appliance copy): keyless v2 accepted first try, v1 needs its key, token never logged" \
  bash tools/guardrails/check-boot-mesh.sh codespace/.devcontainer/mesh/boot-mesh.sh
# Codespaces boot from vyomi-cloud/sandbox, not from this repo (2026-11-22: sandbox still required the v1 key, so every Mesh failed
# under v2). CI checks that copy out and sets VYOMI_SANDBOX_DIR; this script never fetches it itself (no network).
if [ -n "${VYOMI_SANDBOX_DIR:-}" ] && [ -f "$VYOMI_SANDBOX_DIR/.devcontainer/mesh/boot-mesh.sh" ]; then
  run "5" "Mesh boot script (vyomi-cloud/sandbox, what Codespaces boot): same token rules" \
    bash tools/guardrails/check-boot-mesh.sh "$VYOMI_SANDBOX_DIR/.devcontainer/mesh/boot-mesh.sh"
  drift=""
  for a in codespace/.devcontainer/mesh/*; do
    [ -f "$a" ] || continue
    b="$VYOMI_SANDBOX_DIR/.devcontainer/mesh/$(basename "$a")"
    if [ ! -f "$b" ]; then drift="$drift $(basename "$a")(missing)"; elif ! cmp -s "$a" "$b"; then drift="$drift $(basename "$a")"; fi
  done
  if [ -z "$drift" ]; then
    rows+=("| 5 | sandbox .devcontainer/mesh matches codespace/.devcontainer/mesh | PASS |"); echo "PASS  [5] sandbox .devcontainer/mesh matches codespace/.devcontainer/mesh"
  else
    gap "5" "sandbox .devcontainer/mesh differs from codespace/.devcontainer/mesh (Codespaces run the sandbox copy)" "port to vyomi-cloud/sandbox:${drift}"
  fi
else
  skip "5" "Mesh boot script (vyomi-cloud/sandbox, what Codespaces boot)" "set VYOMI_SANDBOX_DIR to a sandbox checkout (CI does)"
fi
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
