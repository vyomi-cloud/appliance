#!/usr/bin/env sh
# Vault production-mode initializer.
#
# Idempotent: on first boot, initializes Vault with 1 unseal key (single-node
# convenience — for real HA use 5/3). On subsequent boots, unseals using the
# stored key + enables transit + KV mounts the simulator expects.
#
# State files (kept inside the Vault container's /vault/data volume):
#   /vault/data/init.json   — {keys:[...], root_token:"..."}
#
# This file is sensitive — back it up before running in production.
#
# Used by docker-compose.yml's cloudlearn-vault sidecar.

set -eu

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
INIT_FILE="${INIT_FILE:-/vault/data/init.json}"

# Wait for Vault to be reachable.
i=0
while [ $i -lt 60 ]; do
  if vault status >/dev/null 2>&1 || [ $? -eq 2 ]; then
    break
  fi
  sleep 1
  i=$((i + 1))
done

# `vault status` exits 2 when sealed (which is what we expect on first boot).
status_exit=0
vault status >/dev/null 2>&1 || status_exit=$?

if [ ! -f "$INIT_FILE" ]; then
  echo "==> First boot — initializing Vault (1 key shares / 1 threshold)..."
  vault operator init -key-shares=1 -key-threshold=1 -format=json > "$INIT_FILE"
  chmod 600 "$INIT_FILE"
  echo "==> Init complete. KEEP $INIT_FILE SAFE — it has root token + unseal key."
fi

ROOT_TOKEN=$(grep -E '"root_token"' "$INIT_FILE" | head -1 | sed -E 's/.*"root_token"[^"]*"([^"]+)".*/\1/')
UNSEAL_KEY=$(grep -E '"unseal_keys_b64"|"keys_base64"' "$INIT_FILE" -A 1 | grep -E '"[A-Za-z0-9+/=]{40,}"' | head -1 | sed -E 's/.*"([^"]+)".*/\1/')

# Unseal (no-op if already unsealed).
if [ "$status_exit" -eq 2 ] || ! vault status 2>/dev/null | grep -q "Sealed.*false"; then
  echo "==> Unsealing..."
  vault operator unseal "$UNSEAL_KEY" >/dev/null
fi

# Auth + enable engines the simulator expects.
export VAULT_TOKEN="$ROOT_TOKEN"

vault secrets list 2>/dev/null | grep -q '^transit/' || {
  echo "==> Enabling transit engine..."
  vault secrets enable transit
}

vault secrets list 2>/dev/null | grep -q '^cloudlearn-kv/' || {
  echo "==> Enabling kv-v2 at cloudlearn-kv/..."
  vault secrets enable -path=cloudlearn-kv -version=2 kv
}

# Emit the root token so the simulator container can read it.
# In docker-compose, we cat to a shared volume the simulator mounts.
TOKEN_FILE="${TOKEN_FILE:-/vault/shared/root_token}"
mkdir -p "$(dirname "$TOKEN_FILE")"
printf '%s' "$ROOT_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

echo "==> Vault ready. Root token written to $TOKEN_FILE."
echo "==> Mounts: transit/, cloudlearn-kv/"
