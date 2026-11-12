#!/usr/bin/env bash
# Vyomi Mesh boot (headless). Hard session TTL: the SESSION token's session_end wins; else now+8h.
#   boot-mesh.sh up|resume       start the stack, post readiness, arm the self-expiry
#   boot-mesh.sh ttl-left        print seconds until session end (for tests/dashboard)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="$HERE/docker-compose.mesh.yml"
PORTAL="${VYOMI_LICENSE_BACKEND_URL:-https://vyomi.cloud}"
CODESPACE="${CODESPACE_NAME:-vyomi-mesh-local}"
RUN_DIR="${HOME}/.vyomi-mesh"; mkdir -p "$RUN_DIR"
END_FILE="$RUN_DIR/session_end"
log() { echo "[vyomi-mesh] $*"; }
post() { curl -fsS -m 10 -X POST "$PORTAL$1" -H 'Content-Type: application/json' -d "$2" >/dev/null 2>&1 || true; }

ttl_seconds() { local t="${1:-8h}" n="${1%[hmd]}" u="${1##*[0-9]}"; case "$u" in m) echo $((n*60));; d) echo $((n*86400));; *) echo $(( ${n:-8}*3600 ));; esac; }

# session_end claim of the signed session token (payload is the 2nd dot-separated base64url part; verified by the simulator).
token_end() {
  [ -n "${VYOMI_MESH_SESSION_TOKEN:-}" ] || return 0
  # Pure shell: the Codespace host (minimal Ubuntu) has no python3, so a python parse here silently returned nothing and the token's
  # real session_end was ignored in favour of the 8 h cap.
  local p; p=$(printf '%s' "$VYOMI_MESH_SESSION_TOKEN" | cut -d. -f2 | tr '_-' '/+')
  while [ $(( ${#p} % 4 )) -ne 0 ]; do p="${p}="; done
  printf '%s' "$p" | base64 -d 2>/dev/null | sed -n 's/.*"session_end": *\([0-9]*\).*/\1/p'
}

# session_end (epoch s): VYOMI_MESH_SESSION_END (from the portal's signed token) is capped at start+max; persisted so
# a resume (idle-stop/restart) can NEVER extend the window.
resolve_end() {
  [ -s "$END_FILE" ] && { cat "$END_FILE"; return; }
  local now max end; now=$(date +%s); max=$(( now + $(ttl_seconds "${VYOMI_MESH_MAX_SESSION:-8h}") ))
  end="${VYOMI_MESH_SESSION_END:-$(token_end)}"; end="${end:-$max}"; [ "$end" -gt "$max" ] && end="$max"
  echo "$end" | tee "$END_FILE"
}

arm_expiry() {
  local end left; end="$(resolve_end)"; left=$(( end - $(date +%s) ))
  if [ "$left" -le 0 ]; then expire; return; fi
  [ -f "$RUN_DIR/expiry.pid" ] && kill -0 "$(cat "$RUN_DIR/expiry.pid")" 2>/dev/null && return 0
  log "self-expiry armed: ${left}s"
  ( sleep "$left"; expire ) >/dev/null 2>&1 & echo $! > "$RUN_DIR/expiry.pid"; disown 2>/dev/null || true
}
expire() {
  post /api/mesh/session/ended "{\"codespace_id\":\"$CODESPACE\",\"reason\":\"ttl\"}"
  docker compose -f "$COMPOSE" --profile ai down 2>/dev/null || true
  date -u +%FT%TZ > "$RUN_DIR/EXPIRED"; log "session ended — stack stopped (idle timeout will stop the Codespace)."
}

# No outbound link: the Codespace never dials anything. The laptop's vyomi-tunnel connects IN over ssh (the sshd devcontainer feature) and
# reaches the simulator (http://<container-ip>:9000), Docker instances and k3s through that one session. Nothing is published.

# Fetch the signed session token + this session's key from the portal (GitHub-verified by CODESPACE_NAME: the portal checks that
# codespace is Available for the owning user). Retries while the portal learns the codespace is up. Needs no secret on this box.
fetch_session() {
  [ -n "${VYOMI_MESH_SESSION_TOKEN:-}" ] && [ -n "${VYOMI_MESH_SESSION_KEY:-}" ] && return 0
  local out tok key end i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    out=$(curl -fsS -m 10 -G "$PORTAL/api/mesh/session/token" --data-urlencode "codespace_id=$CODESPACE" 2>/dev/null) && {
      tok=$(printf '%s' "$out" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
      key=$(printf '%s' "$out" | sed -n 's/.*"key":"\([^"]*\)".*/\1/p')
      end=$(printf '%s' "$out" | sed -n 's/.*"session_end":\([0-9]*\).*/\1/p')
      if [ -n "$tok" ] && [ -n "$key" ]; then
        export VYOMI_MESH_SESSION_TOKEN="$tok" VYOMI_MESH_SESSION_KEY="$key"
        [ -n "$end" ] && export VYOMI_MESH_SESSION_END="$end"
        log "session token fetched."; return 0
      fi; }
    sleep 6
  done
  log "WARNING: could not fetch a session token - the mesh will refuse requests (fails closed)."; return 1
}

# AI pack: ask the simulator (it holds the RAM ledger) to ADMIT the configured models against the AI bucket; start the model
# servers only for admitted ones. A refusal is logged with its reason and the mesh still serves compute. Never blocks readiness.
AI_MIN_FREE_GB="${VYOMI_AI_MIN_FREE_GB:-8}"
start_ai() {
  [ "${VYOMI_MESH_AI:-1}" = "0" ] && { log "AI pack disabled (VYOMI_MESH_AI=0)."; return 0; }
  local plan free; plan=$(docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 5 http://localhost:9000/mesh/ai/plan 2>/dev/null) \
    || { log "AI pack: could not read the admission plan - not starting models."; return 0; }
  free=$(df -BG --output=avail "$HOME" 2>/dev/null | tail -1 | tr -dc 0-9)
  if [ -n "$free" ] && [ "$free" -lt "$AI_MIN_FREE_GB" ]; then log "AI pack: only ${free} GB free disk (< ${AI_MIN_FREE_GB}) - not pulling models."; return 0; fi
  # Parse with the SIMULATOR's python: the Codespace host (minimal Ubuntu base) has no python3, which made this step always report
  # "chat model not admitted" on a real Codespace. The simulator image always ships it.
  local vars; vars=$(printf '%s' "$plan" | docker compose -f "$COMPOSE" exec -T simulator python3 -c '
import json, sys
p = json.load(sys.stdin)
for k, e in (p.get("errors") or {}).items():
    print("echo " + json.dumps("AI pack: %s model refused: %s" % (k, e.get("message"))))
if not p.get("ok"):
    sys.exit(3)
c, m = p["chat"], p.get("embed")
print("export VYOMI_AI_CHAT_HF=%s VYOMI_AI_CHAT_CTX=%s VYOMI_MESH_AI_MODEL=%s" % (c["hf"], c["ctx"], c["id"]))
print("export VYOMI_AI_NEED_EMBED=%d" % (1 if m else 0))
if m: print("export VYOMI_AI_EMBED_HF=%s VYOMI_AI_EMBED_CTX=%s" % (m["hf"], m["ctx"]))
' 2>/dev/null); local rc=$?
  eval "$(printf '%s\n' "$vars" | grep '^echo ')" 2>/dev/null
  [ $rc -ne 0 ] && { log "AI pack: chat model not admitted - not starting model servers."; return 0; }
  eval "$(printf '%s\n' "$vars" | grep '^export ')"
  local svc="llm-chat llm"; [ "${VYOMI_AI_NEED_EMBED:-0}" = "1" ] && svc="llm-chat llm-embed llm"
  docker compose -f "$COMPOSE" --profile ai up -d $svc && log "AI pack: starting ${VYOMI_MESH_AI_MODEL} (first start downloads the model)."
  ( for _ in $(seq 1 200); do
      docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 3 http://llm:8080/health >/dev/null 2>&1 && { echo "[vyomi-mesh] AI model ready."; exit 0; }
      sleep 6; done; echo "[vyomi-mesh] WARNING: AI model not ready after 20 min." ) &
  disown 2>/dev/null || true
}

# A working Mesh = we hold the signed session token AND the simulator answers /mesh/status as a mesh (VYOMI_ROLE=mesh code present).
mesh_verified() {
  [ -n "${VYOMI_MESH_SESSION_TOKEN:-}" ] || return 1
  docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 5 http://localhost:9000/mesh/status 2>/dev/null </dev/null | grep -Eq '"mesh": *true'
}

# Health report. A Codespace can be "running" and still be unusable (DNS broken so apt-get fails, no egress, services down). Run the checks
# INSIDE the simulator container (selfcheck.py is core/mesh_selfcheck.py from the appliance repo; the container has python3, this host does not),
# add the Codespace HOST's own DNS/apt check, and post the report to the portal. The console shows it and only lets the user Join when every
# item is ok; otherwise the portal stops this Codespace. Never blocks readiness. `boot-mesh.sh selfcheck` re-runs it by hand.
host_item() {
  local h detail hint ok=false
  h=$(cat /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null | sed -n 's#^[^\#]*https\{0,1\}://\([A-Za-z0-9.-]*\).*#\1#p' | head -1); h="${h:-archive.ubuntu.com}"
  if getent hosts "$h" >/dev/null 2>&1 && getent hosts github.com >/dev/null 2>&1; then ok=true; detail="resolved github.com and $h"
  else detail="cannot resolve $h or github.com"; hint="Name resolution is failing on the Codespace host, so apt-get and package installs will fail."; fi
  printf '{"id":"host_dns","label":"Codespace host DNS (apt)","ok":%s,"detail":"%s","hint":"%s"}' "$ok" "$detail" "$hint"
}
selfcheck_report() {
  local out rest payload i
  out=$(docker compose -f "$COMPOSE" exec -T simulator python3 - < "$HERE/selfcheck.py" 2>/dev/null | tail -n 1)
  case "$out" in
    \{*\"items\":\ \[*) rest="${out#*\"items\": \[}"; payload="{\"codespace_id\":\"$CODESPACE\",\"items\":[$(host_item), $rest" ;;
    *) payload="{\"codespace_id\":\"$CODESPACE\",\"items\":[$(host_item), {\"id\":\"selfcheck\",\"label\":\"Health checks\",\"ok\":false,\"detail\":\"could not run inside the simulator container\",\"hint\":\"The checks could not run. Stop the Mesh and start it again.\"}]}" ;;
  esac
  for i in 1 2 3; do
    curl -fsS -m 10 -X POST "$PORTAL/api/mesh/session/selfcheck" -H 'Content-Type: application/json' -d "$payload" >/dev/null 2>&1 && { log "health report posted."; return 0; }
    sleep 3
  done
  log "WARNING: could not post the health report to the portal."; return 1
}

start_stack() {
  [ -f "$RUN_DIR/EXPIRED" ] && { log "session already expired — not starting."; return 1; }
  fetch_session || true
  docker compose -f "$COMPOSE" up -d simulator
  for _ in $(seq 1 60); do
    if docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 3 http://localhost:9000/healthz >/dev/null 2>&1; then
      # /healthz is served by ANY appliance image (the 2026-11-10 :latest was a v3 build with no Mesh code and still passed it).
      # Report ready only for a real Mesh: a session token in hand and the Mesh role answering /mesh/status.
      if ! mesh_verified; then
        log "ERROR: the simulator is up but is not a working Mesh (session token: ${VYOMI_MESH_SESSION_TOKEN:+present}${VYOMI_MESH_SESSION_TOKEN:-MISSING}; image: $(docker compose -f "$COMPOSE" images -q simulator 2>/dev/null | head -1)). NOT reporting ready."
        return 1
      fi
      post /api/mesh/session/ready "{\"codespace_id\":\"$CODESPACE\",\"status\":\"ready\",\"session_end\":$(resolve_end)}"
      selfcheck_report || true
      start_ai
      log "mesh ready."; return 0
    fi; sleep 3
  done
  log "WARNING: simulator not healthy in time."
}

case "${1:-up}" in
  up|resume) start_stack && arm_expiry ;;
  selfcheck) selfcheck_report ;;
  ttl-left)  echo $(( $(resolve_end) - $(date +%s) )) ;;
  *) echo "usage: boot-mesh.sh [up|resume|selfcheck|ttl-left]" >&2; exit 2 ;;
esac
