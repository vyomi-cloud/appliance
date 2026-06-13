#!/usr/bin/env bash
# vyomi-host-ssh-bootstrap.sh — set up the user's host SSH identity for the
# Vyomi appliance, so Connect commands shown in the console "just work"
# without the user ever copying a key, chmod'ing a file, or typing ssh
# flags.
#
# Called by `cloud-learn appliance up` and by per-package-manager
# post-install hooks (brew, apt, rpm, snap). Idempotent — safe to run
# repeatedly; existing keys are never overwritten.
#
# What it does:
#   1. Generates ~/.ssh/vyomi_ed25519 if missing (no passphrase).
#   2. Copies the public key to ~/.config/vyomi/host-ssh-pubkey.pub,
#      which the appliance launcher bind-mounts into the simulator
#      container. Every VM the simulator launches gets this key
#      injected as ~ubuntu/.ssh/authorized_keys at first Connect.
#   3. Appends a `Host vyomi-*` block to ~/.ssh/config if not already
#      present, so future `ssh vyomi-i-xxxx.local` style aliases (added
#      in a follow-up) just work.
#
# This file lives at scripts/vyomi-host-ssh-bootstrap.sh in the repo and
# at /opt/vyomi/scripts/vyomi-host-ssh-bootstrap.sh after installation
# by any of the packaging recipes (brew/apt/rpm/snap).

set -euo pipefail

SSH_DIR="${HOME}/.ssh"
KEY_NAME="vyomi_ed25519"
KEY_PATH="${SSH_DIR}/${KEY_NAME}"
PUB_PATH="${KEY_PATH}.pub"
VYOMI_CONFIG_DIR="${HOME}/.config/vyomi"
PUBKEY_MIRROR_PATH="${VYOMI_CONFIG_DIR}/host-ssh-pubkey.pub"
SSH_CONFIG="${SSH_DIR}/config"

log() { printf '%s\n' "$*" >&2; }
notice() { printf '\033[1;36m==>\033[0m %s\n' "$*" >&2; }

mkdir -p "$SSH_DIR" "$VYOMI_CONFIG_DIR"
chmod 700 "$SSH_DIR" 2>/dev/null || true
chmod 700 "$VYOMI_CONFIG_DIR" 2>/dev/null || true

if [ ! -f "$KEY_PATH" ]; then
  notice "Generating Vyomi host SSH key at ${KEY_PATH}"
  if ! command -v ssh-keygen >/dev/null 2>&1; then
    log "✗ ssh-keygen not found. Install OpenSSH first (Mac/Linux ship it; on Win-Git-Bash install Git-for-Windows)."
    exit 1
  fi
  ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" -C "vyomi-appliance-$(hostname -s 2>/dev/null || echo host)" >/dev/null
  chmod 600 "$KEY_PATH"
  chmod 644 "$PUB_PATH"
else
  notice "Vyomi host SSH key already present (${KEY_PATH}) — leaving untouched"
fi

# Mirror the public key into a stable path that the appliance launcher
# bind-mounts into the simulator container. The simulator reads this on
# every VM launch to inject `authorized_keys`.
cp -f "$PUB_PATH" "$PUBKEY_MIRROR_PATH"
chmod 644 "$PUBKEY_MIRROR_PATH"
notice "Mirrored pubkey → ${PUBKEY_MIRROR_PATH}"

# Append SSH config block once (idempotent). The Host pattern is
# deliberately specific to `vyomi-*` so we don't conflict with anything
# else the user might have.
if [ -w "$SSH_DIR" ] && ! grep -q '# vyomi-appliance:start' "$SSH_CONFIG" 2>/dev/null; then
  notice "Adding Host vyomi-* alias block to ${SSH_CONFIG}"
  cat >>"$SSH_CONFIG" <<EOF

# vyomi-appliance:start (managed by vyomi-host-ssh-bootstrap — do not edit between markers)
Host vyomi-*
  User ubuntu
  IdentityFile ${KEY_PATH}
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
# vyomi-appliance:end
EOF
  chmod 600 "$SSH_CONFIG" 2>/dev/null || true
fi

notice "Vyomi SSH bootstrap complete."
echo "  identity: ${KEY_PATH}"
echo "  pubkey  : ${PUB_PATH}"
echo "  mirror  : ${PUBKEY_MIRROR_PATH}"
