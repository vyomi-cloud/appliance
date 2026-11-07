#!/usr/bin/env bash
# Join this machine to the LLM mesh (docs/architecture/v4.0/BOOSTER-LLM-MESH.md). Used by:
#   - the GitHub-Actions runner workflow (before starting Ollama / llama-rpc-server), and
#   - the booster Codespace (codespace/.devcontainer/booster/mesh-up.sh wraps this file) - same agent, role "booster".
#
#   mesh-up.sh [up]     join (idempotent: a live agent is reused)         mesh-up.sh down    leave gracefully + remove the interface
#   mesh-up.sh status   print the status json
#
# env (required for up): VYOMI_RELAY_URL (wss://relay[/mesh])  VYOMI_MESH_TOKEN (portal-minted, mesh-node role)
# env (optional): MESH_DIR (default $RUNNER_TEMP or /tmp)/vyomi-mesh   VYOMI_MESH_IFACE=wgvyomi   WS_PKG   MESH_JS (path of booster-mesh.mjs)
#                 TTL_S   JOIN_TIMEOUT_S=60
# Nothing inbound is opened. The WireGuard private key is generated inside the node agent and never leaves it. The token is read from
# the environment, masked, deleted from the agent's environment after startup, and never printed. Logs (agent.log) carry no secrets.
set +x
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cmd="${1:-up}"
MESH_DIR="${MESH_DIR:-${RUNNER_TEMP:-/tmp}/vyomi-mesh}"; mkdir -p "$MESH_DIR"
IFACE="${VYOMI_MESH_IFACE:-wgvyomi}"
STATUS="$MESH_DIR/status.json"; PIDF="$MESH_DIR/agent.pid"; LOG="$MESH_DIR/agent.log"
MESH_JS="${MESH_JS:-}"
if [ -z "$MESH_JS" ]; then for c in "$HERE/booster-mesh.mjs" "$HERE/../../wasm/relay/booster-mesh.mjs" /opt/runner/booster-mesh.mjs; do [ -f "$c" ] && { MESH_JS="$c"; break; }; done; fi
log() { echo "[mesh-up] $*"; }
SUDO=""; SUDOE=""; [ "$(id -u)" -ne 0 ] && { SUDO="sudo -n"; SUDOE="sudo -n -E"; }

alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
linked() { [ -f "$STATUS" ] && grep -q '"linked":true' "$STATUS" 2>/dev/null; }
addr_of() { sed -n 's/.*"address":"\([0-9.]*\)".*/\1/p' "$STATUS" 2>/dev/null | head -1; }

case "$cmd" in
  status) [ -f "$STATUS" ] && cat "$STATUS" || { echo '{"linked":false}'; exit 1; }; exit 0 ;;
  down)
    if alive; then $SUDO kill -TERM "$(cat "$PIDF")" 2>/dev/null; for _ in $(seq 1 20); do alive || break; sleep 0.25; done; fi
    $SUDO ip link del "$IFACE" 2>/dev/null; rm -f "$PIDF" "$STATUS"; log "left the mesh"; exit 0 ;;
  up) ;;
  *) echo "usage: $0 [up|down|status]"; exit 2 ;;
esac

: "${VYOMI_RELAY_URL:?VYOMI_RELAY_URL required}"
: "${VYOMI_MESH_TOKEN:?VYOMI_MESH_TOKEN required}"
[ -n "${GITHUB_ACTIONS:-}" ] && echo "::add-mask::${VYOMI_MESH_TOKEN}"          # public-repo logs are world-readable

if alive && linked; then log "already joined as $(addr_of)"; echo "VYOMI_MESH_ADDR=$(addr_of)"; exit 0; fi
alive && { $SUDO kill -TERM "$(cat "$PIDF")" 2>/dev/null; sleep 1; }            # stale/half-joined agent: restart cleanly

[ -n "$MESH_JS" ] || { log "booster-mesh.mjs not found"; exit 3; }
command -v node >/dev/null || { log "node is required"; exit 3; }
if ! command -v wg >/dev/null || ! command -v ip >/dev/null; then
  log "installing wireguard-tools"
  $SUDO apt-get update -qq >/dev/null 2>&1; $SUDO apt-get install -y -qq wireguard-tools iproute2 >/dev/null 2>&1 || { log "cannot install wireguard-tools"; exit 3; }
fi
# Kernel WireGuard if the kernel has it, else the userspace wireguard-go (needs /dev/net/tun). The agent does the fallback itself;
# we only make sure the binary exists when the kernel module is missing.
if ! $SUDO ip link add _vyomi_probe type wireguard 2>/dev/null; then
  command -v wireguard-go >/dev/null || { $SUDO apt-get install -y -qq wireguard-go >/dev/null 2>&1 || log "no kernel wireguard and wireguard-go not installable"; }
else $SUDO ip link del _vyomi_probe 2>/dev/null; fi

rm -f "$STATUS"
export VYOMI_MESH_IFACE="$IFACE" VYOMI_MESH_STATUS="$STATUS" WS_PKG="${WS_PKG:-/opt/runner/node_modules/ws}"
# The token travels in the environment only (sudo -E), never in argv. The agent unsets the token from its own environment right after reading it.
export VYOMI_MESH_TOKEN
$SUDOE nohup node "$MESH_JS" agent >>"$LOG" 2>&1 &
echo $! >"$PIDF"; disown 2>/dev/null || true
T="${JOIN_TIMEOUT_S:-60}"
for _ in $(seq 1 $((T * 4))); do
  linked && break
  alive || { log "agent exited before joining (see $LOG, last lines follow)"; tail -n 5 "$LOG" 2>/dev/null | sed 's/Bearer [^ ]*/Bearer ***/'; exit 4; }
  sleep 0.25
done
linked || { log "join timed out after ${T}s"; tail -n 5 "$LOG" 2>/dev/null; exit 4; }
A="$(addr_of)"; log "joined mesh as $A"
echo "VYOMI_MESH_ADDR=$A"
[ -n "${GITHUB_ENV:-}" ] && echo "VYOMI_MESH_ADDR=$A" >>"$GITHUB_ENV"
exit 0
