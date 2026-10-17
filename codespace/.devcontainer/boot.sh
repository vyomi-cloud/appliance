#!/usr/bin/env bash
# Vyomi Cloud Sandbox boot orchestrator (P0 MVP). See plan §3.1, §3.3, §3.8.
#
#   boot.sh up          → start the aws-core stack, register with the cost meter
#   boot.sh heartbeat    → (re)arm the running-time heartbeat + the TTL reaper
#
# All portal calls are fail-soft: metering must never block the sandbox.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="$HERE/docker-compose.sandbox.yml"

PORTAL="${VYOMI_LICENSE_BACKEND_URL:-https://vyomi.cloud}"
CODESPACE="${CODESPACE_NAME:-vyomi-sandbox-local}"
ORG="${GITHUB_REPOSITORY_OWNER:-}"
GH_USER="${GITHUB_USER:-}"
PROFILE="${VYOMI_PROFILE:-all-clouds}"
COMPOSE_PROFILES="${COMPOSE_PROFILES:-aws,gcp,azure}"; export COMPOSE_PROFILES
BILLING="${VYOMI_BILLING:-free_personal_quota}"
TTL="${VYOMI_SANDBOX_TTL:-8h}"
FWD_DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"

RUN_DIR="${HOME}/.vyomi-sandbox"
mkdir -p "$RUN_DIR"
HB_PID="$RUN_DIR/heartbeat.pid"
REAP_PID="$RUN_DIR/reaper.pid"

# Forwarded public URL — wins for GCP self-links; empty when run locally.
if [ -n "${CODESPACE_NAME:-}" ]; then
  export CLOUDLEARN_PUBLIC_URL="https://${CODESPACE_NAME}-9000.${FWD_DOMAIN}"
fi

log() { echo "[vyomi-sandbox] $*"; }

post() {  # post <path> <json>   (fail-soft)
  curl -fsS -m 10 -X POST "$PORTAL$1" -H 'Content-Type: application/json' -d "$2" >/dev/null 2>&1 || true
}

# Optional per-sandbox secret for the readiness webhook (portal verifies it iff
# VYOMI_SANDBOX_STATUS_SECRET is configured there too). Empty is fine otherwise.
STATUS_TOKEN="${VYOMI_SANDBOX_STATUS_SECRET:-}"
post_status() {  # post_status <status> <pct>   → the PRIMARY launch-readiness webhook
  post /api/sandbox/status "{\"codespace_id\":\"$CODESPACE\",\"status\":\"$1\",\"pct\":$2,\"token\":\"$STATUS_TOKEN\"}"
}

ttl_seconds() {  # 8h | 90m | 1d | 1w → seconds
  local t="$1" n unit
  n="${t%[hmdw]}"; unit="${t##*[0-9]}"
  case "$unit" in
    m) echo $(( n * 60 )) ;;
    h) echo $(( n * 3600 )) ;;
    d) echo $(( n * 86400 )) ;;
    w) echo $(( n * 604800 )) ;;
    *) echo $(( ${n:-8} * 3600 )) ;;
  esac
}

make_port_public() {
  # Mark the forwarded console port 9000 ORG-visible so a developer who ISN'T the
  # Codespace owner (the turnkey model: the box runs in the org/PAT-owner account,
  # the dev just opens the URL) can still reach it. A default forward is `private`
  # = owner-only → a non-owner dev hitting it gets a proxy error (the 502).
  #
  # ORG (not public) — SOC/InfoSec: the console must not be an anonymous
  # internet-reachable endpoint; only authenticated org members reach it.
  #
  # MUST run AFTER port 9000 is actually forwarded (i.e. after the simulator is
  # listening) — calling it while 9000 isn't forwarded yet silently no-ops and the
  # port stays `private`. That ordering bug is why launches 502'd. Retry to ride
  # out the forward settling.
  if command -v gh >/dev/null 2>&1 && [ -n "${CODESPACE_NAME:-}" ]; then
    local i
    for i in 1 2 3 4 5; do
      if gh codespace ports visibility 9000:org -c "$CODESPACE_NAME" >/dev/null 2>&1; then
        log "console port 9000 → org-visible."
        return 0
      fi
      sleep 2
    done
    log "note: couldn't set port 9000 org-visible after retries — set it in the Ports tab or via the portal."
  fi
}

install_clis() {
  # Pre-install the native SDK/CLIs so developers don't hit "aws: command not
  # found" — in the BACKGROUND so it never slows provisioning or the appliance
  # boot. Best-effort (pip first, apt fallback).
  ( python3 -m pip install --quiet boto3 awscli >/dev/null 2>&1 \
      || (sudo apt-get update -qq && sudo apt-get install -y -qq awscli python3-boto3) >/dev/null 2>&1 \
      || true ) &
}

start_stack() {
  log "pulling + starting stack (profile=$PROFILE · clouds=$COMPOSE_PROFILES)…"
  install_clis
  docker compose -f "$COMPOSE" up -d
  log "waiting for the simulator (http://localhost:9000/healthz)…"
  for i in $(seq 1 60); do
    if curl -fsS -m 3 http://localhost:9000/healthz >/dev/null 2>&1; then
      log "simulator is up."
      make_port_public               # NOW that 9000 is forwarded, set visibility (was called too early)
      post_status ready 100          # PRIMARY readiness webhook → the launch modal opens off this
      if [ -n "${CLOUDLEARN_PUBLIC_URL:-}" ]; then
        log "console → ${CLOUDLEARN_PUBLIC_URL}"
      fi
      return 0
    fi
    post_status booting $(( i * 100 / 60 ))   # progress webhook (best-effort)
    sleep 3
  done
  log "WARNING: simulator did not report healthy in time (continuing)."
  make_port_public                   # best-effort even if health timed out
}

provision() {
  local ttl_s; ttl_s="$(ttl_seconds "$TTL")"
  log "registering sandbox with the cost meter (org=${ORG:-personal} billing=$BILLING profile=$PROFILE)…"
  post /api/sandbox/provision "$(cat <<JSON
{"codespace_id":"$CODESPACE","org":"$ORG","owner_email":"${GH_USER:+$GH_USER@users.noreply.github.com}","github_login":"$GH_USER","profile_id":"$PROFILE","compute_profile":"S","billing":"$BILLING","ttl_seconds":$ttl_s,"install_id":"$CODESPACE"}
JSON
)"
}

start_heartbeat() {
  # Idempotent: don't start a second loop.
  if [ -f "$HB_PID" ] && kill -0 "$(cat "$HB_PID")" 2>/dev/null; then
    log "heartbeat already running (pid $(cat "$HB_PID"))."; return 0
  fi
  log "arming running-time heartbeat (every 5 min)…"
  ( while true; do
      post /api/sandbox/heartbeat "{\"codespace_id\":\"$CODESPACE\"}"
      sleep 300
    done ) >/dev/null 2>&1 &
  echo $! > "$HB_PID"
  disown 2>/dev/null || true
}

arm_reaper() {
  # MVP-lite TTL: after VYOMI_SANDBOX_TTL, stop the stack + tell the meter.
  # (Hard org-level scheduled-Action reaper is a fast-follow; GitHub idle/
  # retention is the backstop.)
  if [ -f "$REAP_PID" ] && kill -0 "$(cat "$REAP_PID")" 2>/dev/null; then
    return 0
  fi
  local ttl_s; ttl_s="$(ttl_seconds "$TTL")"
  log "arming TTL reaper ($TTL = ${ttl_s}s)…"
  ( sleep "$ttl_s"
    post /api/sandbox/teardown "{\"codespace_id\":\"$CODESPACE\"}"
    docker compose -f "$COMPOSE" down 2>/dev/null || true
    echo "$(date -u +%FT%TZ) sandbox TTL reached ($TTL) — stack stopped." > "$RUN_DIR/EXPIRED"
  ) >/dev/null 2>&1 &
  echo $! > "$REAP_PID"
  disown 2>/dev/null || true
}

case "${1:-up}" in
  up)
    start_stack
    provision
    start_heartbeat
    arm_reaper
    log "ready. Open the forwarded port 9000 to reach the console."
    ;;
  heartbeat)
    # Runs on every Codespace RESTART (postStartCommand). The stack does NOT
    # reliably survive an idle-stop under docker-in-docker, so bring it back up
    # (idempotent: `docker compose up -d` is a no-op if already running) and
    # re-assert port visibility BEFORE re-arming — otherwise port 9000 is dead
    # and the console 502s after a restart. (Does not re-provision the cost meter.)
    start_stack
    start_heartbeat
    arm_reaper
    ;;
  *)
    echo "usage: boot.sh [up|heartbeat]" >&2; exit 2 ;;
esac
