#!/bin/sh
# Vyomi install-funnel phone-home (POSIX sh — used by brew / .deb / .rpm).
# ───────────────────────────────────────────────────────────────────────
# Fires a single fail-soft HTTP POST when the CLI package finishes
# installing. The portal records a DOWNLOADED state for this install_id
# (per-channel attribution), which is then upgraded to INSTALLED when
# the user runs `vyomi up` and the simulator's FastAPI startup hook
# registers itself. This closes the funnel that previously started at
# "the user actually booted the appliance" — important for measuring
# package-manager conversion (which channel sends us the most users
# who end up activating?).
#
# Privacy:
#   • payload = { install_id, version, host_os, channel, state }
#   • install_id is a random 16-char hex generated once per host and
#     persisted at $HOME/.vyomi/install_id. The same id is later picked
#     up by the CLI (via VYOMI_INSTALL_ID env) and the simulator boot
#     hook, so DOWNLOADED → INSTALLED is the same row.
#   • Country is resolved server-side from Cloudflare's CF-IPCountry
#     header at the portal edge. We never send an IP.
#   • Opt-out: export VYOMI_NO_TELEMETRY=1 in the shell that runs the
#     install (works for brew/deb/rpm; respected by all 4 channels).
#
# Failure modes:
#   • DNS / network failures → silently swallowed (`2>/dev/null`).
#   • 4xx/5xx              → swallowed (curl `-f` would exit non-zero,
#                            so we DON'T use `-f` here).
#   • curl missing         → script exits 0 without any side effect.
#   • Timeout              → 3s total (`--max-time`). The install must
#                            never block more than that on telemetry.
#
# Required argument: $1 = channel (brew | deb | rpm | docker | tarball).
# Optional environment:
#   VYOMI_PHONE_HOME_URL  override portal endpoint (testing)
#   VYOMI_VERSION         version string to report (else read from VERSION
#                         file in the package, else "unknown")
#   VYOMI_NO_TELEMETRY    if set to anything truthy, exit immediately.
# ───────────────────────────────────────────────────────────────────────

set -e   # fail-fast inside the script, but the OUTER caller still must
         # ignore our exit code — package managers will run us with
         # `|| true`. We use `set -e` so a malformed install_id file
         # doesn't silently send garbage.

CHANNEL="${1:-tarball}"
PORTAL_URL="${VYOMI_PHONE_HOME_URL:-https://vyomi.cloud}/api/install/register"

# Honour the opt-out.
case "${VYOMI_NO_TELEMETRY:-}" in
  1|true|TRUE|yes|YES) exit 0 ;;
esac

# Curl is the one hard dependency. If it's missing, exit silently —
# we'd rather miss a phone-home than fail a package install.
command -v curl >/dev/null 2>&1 || exit 0

# Resolve $HOME. Package managers sometimes run postinst as root with
# HOME=/root; brew runs as the user. For DOWNLOADED we want a
# per-machine id, not per-user, so we prefer /var/lib/vyomi when root,
# fall back to $HOME/.vyomi otherwise.
if [ "$(id -u 2>/dev/null || echo 99)" = "0" ]; then
  VYOMI_DIR="/var/lib/vyomi"
else
  VYOMI_DIR="${HOME:-/tmp}/.vyomi"
fi
mkdir -p "$VYOMI_DIR" 2>/dev/null || exit 0

ID_FILE="$VYOMI_DIR/install_id"
if [ -r "$ID_FILE" ]; then
  INSTALL_ID="$(cat "$ID_FILE" 2>/dev/null | tr -d '[:space:]' | head -c 64)"
fi

# ── Upgrade-continuity probe ──────────────────────────────────────────────
# When this script runs during `brew upgrade` / `apt upgrade` / `dnf
# upgrade` of an EXISTING customer install, the marker file may be
# missing (v2.0.5 didn't write it) but the appliance is still running
# from before and already has a stable install_id in STATE. Probe its
# read-only /api/runtime/install-id endpoint and adopt that value so the
# portal's funnel row stays continuous instead of splitting at upgrade.
#
# Fail-soft: a 2s timeout per probe, both probes give up gracefully if
# the appliance is stopped or unreachable. We fall through to random.
if [ -z "$INSTALL_ID" ] || [ "$(printf '%s' "$INSTALL_ID" | wc -c | tr -d ' ')" -lt 8 ]; then
  for probe_url in "http://vyomi.local:9000" "http://127.0.0.1:9000"; do
    probe_id="$(curl -sS --max-time 2 "$probe_url/api/runtime/install-id" 2>/dev/null \
                | sed -n 's/.*"install_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
                | tr -d '[:space:]' | head -c 64)"
    if [ -n "$probe_id" ] && [ "$(printf '%s' "$probe_id" | wc -c | tr -d ' ')" -ge 8 ]; then
      INSTALL_ID="$probe_id"
      break
    fi
  done
fi

if [ -z "$INSTALL_ID" ] || [ "$(printf '%s' "$INSTALL_ID" | wc -c | tr -d ' ')" -lt 8 ]; then
  # Generate 16 random hex chars. /dev/urandom is universal; head -c 8
  # gives us 8 bytes which we hex-encode → 16 chars.
  INSTALL_ID="$(od -An -tx1 -N8 /dev/urandom 2>/dev/null | tr -d ' \n')"
  # Fall back to date+pid if /dev/urandom is somehow unavailable.
  [ -n "$INSTALL_ID" ] || INSTALL_ID="$(date +%s)$$"
  # Pad to at least 8 chars to satisfy the portal validator.
  while [ "$(printf '%s' "$INSTALL_ID" | wc -c | tr -d ' ')" -lt 8 ]; do
    INSTALL_ID="${INSTALL_ID}0"
  done
fi

# Persist whichever id we ended up with — random OR appliance-derived —
# so the next phone-home (and the CLI launcher's env-export) sees it.
if [ ! -r "$ID_FILE" ] || [ "$(cat "$ID_FILE" 2>/dev/null | tr -d '[:space:]')" != "$INSTALL_ID" ]; then
  printf '%s' "$INSTALL_ID" > "$ID_FILE" 2>/dev/null || true
  chmod 0644 "$ID_FILE" 2>/dev/null || true
fi

# Resolve version — prefer env, then a VERSION file alongside this
# script (brew/deb/rpm all ship one).
if [ -n "${VYOMI_VERSION:-}" ]; then
  VERSION="$VYOMI_VERSION"
elif [ -r "$(dirname "$0")/VERSION" ]; then
  VERSION="$(tr -d '[:space:]' < "$(dirname "$0")/VERSION")"
else
  VERSION="unknown"
fi

HOST_OS="$(uname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo unknown)"

# Build payload. No PII — install_id is random, host_os is linux/darwin,
# channel is the package manager that invoked us.
PAYLOAD="$(printf '{"install_id":"%s","version":"%s","host_os":"%s","channel":"%s","state":"DOWNLOADED"}' \
  "$INSTALL_ID" "$VERSION" "$HOST_OS" "$CHANNEL")"

# Fire and forget. --max-time 3 because the user is waiting for their
# install to finish. Silenced stderr because curl's "couldn't resolve
# host" message would otherwise pollute the install output.
curl -sS -X POST "$PORTAL_URL" \
  --max-time 3 \
  -H 'Content-Type: application/json' \
  -H "User-Agent: vyomi-postinst/$VERSION ($CHANNEL)" \
  -d "$PAYLOAD" >/dev/null 2>&1 || true

exit 0
