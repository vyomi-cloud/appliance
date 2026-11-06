#!/usr/bin/env bash
# Vyomi Booster boot (headless). Hard session TTL: the SESSION token's session_end wins; else now+8h.
#   boot-booster.sh up|resume       start the stack, post readiness, arm the self-expiry
#   boot-booster.sh ttl-left        print seconds until session end (for tests/dashboard)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="$HERE/docker-compose.booster.yml"
PORTAL="${VYOMI_LICENSE_BACKEND_URL:-https://vyomi.cloud}"
CODESPACE="${CODESPACE_NAME:-vyomi-booster-local}"
RUN_DIR="${HOME}/.vyomi-booster"; mkdir -p "$RUN_DIR"
END_FILE="$RUN_DIR/session_end"
log() { echo "[vyomi-booster] $*"; }
post() { curl -fsS -m 10 -X POST "$PORTAL$1" -H 'Content-Type: application/json' -d "$2" >/dev/null 2>&1 || true; }

ttl_seconds() { local t="${1:-8h}" n="${1%[hmd]}" u="${1##*[0-9]}"; case "$u" in m) echo $((n*60));; d) echo $((n*86400));; *) echo $(( ${n:-8}*3600 ));; esac; }

# session_end claim of the signed session token (payload is the 2nd dot-separated base64url part; verified by the simulator).
token_end() {
  [ -n "${VYOMI_BOOSTER_SESSION_TOKEN:-}" ] || return 0
  python3 - "$VYOMI_BOOSTER_SESSION_TOKEN" <<'PY' 2>/dev/null
import base64, json, sys
p = sys.argv[1].split(".")[1]
print(int(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["session_end"]))
PY
}

# session_end (epoch s): VYOMI_BOOSTER_SESSION_END (from the portal's signed token) is capped at start+max; persisted so
# a resume (idle-stop/restart) can NEVER extend the window.
resolve_end() {
  [ -s "$END_FILE" ] && { cat "$END_FILE"; return; }
  local now max end; now=$(date +%s); max=$(( now + $(ttl_seconds "${VYOMI_BOOSTER_MAX_SESSION:-8h}") ))
  end="${VYOMI_BOOSTER_SESSION_END:-$(token_end)}"; end="${end:-$max}"; [ "$end" -gt "$max" ] && end="$max"
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
  post /api/booster/session/ended "{\"codespace_id\":\"$CODESPACE\",\"reason\":\"ttl\"}"
  docker compose -f "$COMPOSE" --profile link down 2>/dev/null || true
  date -u +%FT%TZ > "$RUN_DIR/EXPIRED"; log "session ended — stack stopped (idle timeout will stop the Codespace)."
}

# Outbound relay link (no inbound port): only when the portal supplied a relay URL + session token.
start_link() {
  if [ -n "${VYOMI_RELAY_URL:-}" ] && [ -n "${VYOMI_BOOSTER_SESSION_TOKEN:-}" ]; then
    docker compose -f "$COMPOSE" --profile link up -d link && log "relay link dialling out to $VYOMI_RELAY_URL"
  else
    log "no VYOMI_RELAY_URL / VYOMI_BOOSTER_SESSION_TOKEN - relay link not started."
  fi
}

start_stack() {
  [ -f "$RUN_DIR/EXPIRED" ] && { log "session already expired — not starting."; return 1; }
  docker compose -f "$COMPOSE" up -d simulator
  for _ in $(seq 1 60); do
    if docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 3 http://localhost:9000/healthz >/dev/null 2>&1; then
      post /api/booster/session/ready "{\"codespace_id\":\"$CODESPACE\",\"status\":\"ready\",\"session_end\":$(resolve_end)}"
      start_link
      log "booster ready."; return 0
    fi; sleep 3
  done
  log "WARNING: simulator not healthy in time."
}

case "${1:-up}" in
  up|resume) start_stack && arm_expiry ;;
  ttl-left)  echo $(( $(resolve_end) - $(date +%s) )) ;;
  *) echo "usage: boot-booster.sh [up|resume|ttl-left]" >&2; exit 2 ;;
esac
