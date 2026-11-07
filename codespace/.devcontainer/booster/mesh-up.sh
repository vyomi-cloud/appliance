#!/usr/bin/env bash
# Booster-side LLM-mesh join (docs/architecture/v4.0/BOOSTER-LLM-MESH.md). The Codespace is just another mesh node (role "booster",
# 100.96.0.2): same agent as the runners, same idempotent script - this wrapper only locates it and points at the booster state dir.
#
#   VYOMI_RELAY_URL=wss://... VYOMI_MESH_TOKEN=... bash mesh-up.sh [up|down|status]
#
# The token is the portal-minted mesh-role token for THIS session (the portal injects it the same way as the booster session token).
# The gateway containers reach runners at their WG addresses (http://100.96.1.N:11434) through the host's wg interface: docker's default
# bridge NATs outbound traffic, so no host networking is needed. Nothing is published; no inbound port is opened.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
export MESH_DIR="${MESH_DIR:-${VYOMI_STATE_DIR:-/var/lib/vyomi}/mesh}"
mkdir -p "$MESH_DIR" 2>/dev/null || export MESH_DIR=/tmp/vyomi-mesh
export MESH_JS="${MESH_JS:-$REPO/wasm/relay/booster-mesh.mjs}"
export WS_PKG="${WS_PKG:-$(npm root -g 2>/dev/null)/ws}"
if [ ! -d "$WS_PKG" ]; then   # the 'ws' package: install it next to the state dir once
  (cd "$MESH_DIR" && npm i --no-audit --no-fund --silent ws@8.18.0 >/dev/null 2>&1) && export WS_PKG="$MESH_DIR/node_modules/ws"
fi
exec bash "$REPO/docker/booster-runner-llm/mesh-up.sh" "$@"
