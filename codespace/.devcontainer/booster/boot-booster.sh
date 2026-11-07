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
  docker compose -f "$COMPOSE" --profile link --profile ai down 2>/dev/null || true
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

# Fetch the signed session token + this session's key from the portal (GitHub-verified by CODESPACE_NAME: the portal checks that
# codespace is Available for the owning user). Retries while the portal learns the codespace is up. Needs no secret on this box.
fetch_session() {
  [ -n "${VYOMI_BOOSTER_SESSION_TOKEN:-}" ] && [ -n "${VYOMI_BOOSTER_SESSION_KEY:-}" ] && return 0
  local out tok key end rel i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    out=$(curl -fsS -m 10 -G "$PORTAL/api/booster/session/token" --data-urlencode "codespace_id=$CODESPACE" 2>/dev/null) && {
      tok=$(printf '%s' "$out" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
      key=$(printf '%s' "$out" | sed -n 's/.*"key":"\([^"]*\)".*/\1/p')
      end=$(printf '%s' "$out" | sed -n 's/.*"session_end":\([0-9]*\).*/\1/p')
      rel=$(printf '%s' "$out" | sed -n 's/.*"relay_url":"\([^"]*\)".*/\1/p')
      if [ -n "$tok" ] && [ -n "$key" ]; then
        export VYOMI_BOOSTER_SESSION_TOKEN="$tok" VYOMI_BOOSTER_SESSION_KEY="$key"
        [ -n "$end" ] && export VYOMI_BOOSTER_SESSION_END="$end"
        [ -z "${VYOMI_RELAY_URL:-}" ] && [ -n "$rel" ] && export VYOMI_RELAY_URL="$rel"   # the portal says where to dial out to
        log "session token fetched."; return 0
      fi; }
    sleep 6
  done
  log "WARNING: could not fetch a session token - the booster will refuse requests (fails closed)."; return 1
}

# AI pack: ask the simulator (it holds the RAM ledger) to ADMIT the configured models against the AI bucket; start the model
# servers only for admitted ones. A refusal is logged with its reason and the booster still serves compute. Never blocks readiness.
AI_MIN_FREE_GB="${VYOMI_AI_MIN_FREE_GB:-8}"
start_ai() {
  [ "${VYOMI_BOOSTER_AI:-1}" = "0" ] && { log "AI pack disabled (VYOMI_BOOSTER_AI=0)."; return 0; }
  local plan free; plan=$(docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 5 http://localhost:9000/booster/ai/plan 2>/dev/null) \
    || { log "AI pack: could not read the admission plan - not starting models."; return 0; }
  free=$(df -BG --output=avail "$HOME" 2>/dev/null | tail -1 | tr -dc 0-9)
  if [ -n "$free" ] && [ "$free" -lt "$AI_MIN_FREE_GB" ]; then log "AI pack: only ${free} GB free disk (< ${AI_MIN_FREE_GB}) - not pulling models."; return 0; fi
  local vars; vars=$(printf '%s' "$plan" | python3 -c '
import json, sys
p = json.load(sys.stdin)
for k, e in (p.get("errors") or {}).items():
    print("echo " + json.dumps("AI pack: %s model refused: %s" % (k, e.get("message"))))
if not p.get("ok"):
    sys.exit(3)
c, m = p["chat"], p.get("embed")
print("export VYOMI_AI_CHAT_HF=%s VYOMI_AI_CHAT_CTX=%s VYOMI_BOOSTER_AI_MODEL=%s" % (c["hf"], c["ctx"], c["id"]))
print("export VYOMI_AI_NEED_EMBED=%d" % (1 if m else 0))
if m: print("export VYOMI_AI_EMBED_HF=%s VYOMI_AI_EMBED_CTX=%s" % (m["hf"], m["ctx"]))
' 2>/dev/null); local rc=$?
  eval "$(printf '%s\n' "$vars" | grep '^echo ')" 2>/dev/null
  [ $rc -ne 0 ] && { log "AI pack: chat model not admitted - not starting model servers."; return 0; }
  eval "$(printf '%s\n' "$vars" | grep '^export ')"
  local svc="llm-chat llm"; [ "${VYOMI_AI_NEED_EMBED:-0}" = "1" ] && svc="llm-chat llm-embed llm"
  docker compose -f "$COMPOSE" --profile ai up -d $svc && log "AI pack: starting ${VYOMI_BOOSTER_AI_MODEL} (first start downloads the model)."
  ( for _ in $(seq 1 200); do
      docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 3 http://llm:8080/health >/dev/null 2>&1 && { echo "[vyomi-booster] AI model ready."; exit 0; }
      sleep 6; done; echo "[vyomi-booster] WARNING: AI model not ready after 20 min." ) &
  disown 2>/dev/null || true
}

start_stack() {
  [ -f "$RUN_DIR/EXPIRED" ] && { log "session already expired — not starting."; return 1; }
  fetch_session || true
  docker compose -f "$COMPOSE" up -d simulator
  for _ in $(seq 1 60); do
    if docker compose -f "$COMPOSE" exec -T simulator curl -fsS -m 3 http://localhost:9000/healthz >/dev/null 2>&1; then
      post /api/booster/session/ready "{\"codespace_id\":\"$CODESPACE\",\"status\":\"ready\",\"session_end\":$(resolve_end)}"
      start_ai
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
