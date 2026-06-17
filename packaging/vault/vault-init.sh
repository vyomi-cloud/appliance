#!/usr/bin/env sh
# Vault production-mode entrypoint + initializer.
#
# This script is PID 1 inside the vault container. It:
#   1. Starts `vault server` in the background using vault-config.hcl
#   2. Initializes on first boot (writes /vault/data/init.json with the
#      unseal key + root token)
#   3. Unseals on every boot using the stored key
#   4. Enables the transit/ and cloudlearn-kv/ engines the simulator needs
#   5. Writes the root token to /vault/shared/root_token for the simulator
#      container to read
#   6. Forwards SIGTERM to the vault server process for graceful shutdown
#   7. Waits on the server PID — exits when vault server exits
#
# State files (kept inside the cloudlearn-vault-data named volume):
#   /vault/data/init.json   — {keys:[...], root_token:"..."}
#   /vault/data/...         — Vault's own storage backend files
#
# Idempotent: rerunning this script (i.e. container restart) preserves all
# state. KMS keys / Secrets Manager secrets / Azure Key Vault entries
# survive across `docker compose up --force-recreate` thanks to the named
# volume cloudlearn-vault-data + this script's unseal-not-init logic on
# subsequent boots.

set -eu

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
INIT_FILE="${INIT_FILE:-/vault/data/init.json}"
TOKEN_FILE="${TOKEN_FILE:-/vault/shared/root_token}"
VAULT_CONFIG="${VAULT_CONFIG:-/vault/config/vault-config.hcl}"

# Start vault server in background. Output goes to stdout (docker logs).
echo "==> Starting Vault server (config: $VAULT_CONFIG)..."
vault server -config="$VAULT_CONFIG" &
VAULT_PID=$!

# Forward SIGTERM/SIGINT to vault server so docker stop is graceful.
trap 'echo "==> Forwarding SIGTERM to vault server (pid $VAULT_PID)"; kill -TERM "$VAULT_PID"; wait "$VAULT_PID"; exit $?' INT TERM

export VAULT_ADDR

# Wait for Vault API to be reachable (sealed status = exit 2 = "reachable").
i=0
while [ $i -lt 60 ]; do
  status_exit=0
  vault status >/dev/null 2>&1 || status_exit=$?
  if [ "$status_exit" = "0" ] || [ "$status_exit" = "2" ]; then
    break
  fi
  sleep 1
  i=$((i + 1))
done

if [ "$i" -ge 60 ]; then
  echo "!! Vault server did not become reachable within 60s — bailing"
  kill -TERM "$VAULT_PID" 2>/dev/null || true
  exit 1
fi

# First boot — init.
if [ ! -f "$INIT_FILE" ]; then
  echo "==> First boot — initializing Vault (1 key shares / 1 threshold)..."
  vault operator init -key-shares=1 -key-threshold=1 -format=json > "$INIT_FILE"
  chmod 600 "$INIT_FILE"
  echo "==> Init complete. KEEP $INIT_FILE SAFE — it has root token + unseal key."
fi

ROOT_TOKEN=$(grep -E '"root_token"' "$INIT_FILE" | head -1 | sed -E 's/.*"root_token"[^"]*"([^"]+)".*/\1/')
UNSEAL_KEY=$(grep -E '"unseal_keys_b64"|"keys_base64"' "$INIT_FILE" -A 1 | grep -E '"[A-Za-z0-9+/=]{40,}"' | head -1 | sed -E 's/.*"([^"]+)".*/\1/')

# Unseal (no-op if already unsealed).
if ! vault status 2>/dev/null | grep -q "Sealed.*false"; then
  echo "==> Unsealing Vault..."
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

# Publish root token for the simulator to read on its startup.
mkdir -p "$(dirname "$TOKEN_FILE")"
printf '%s' "$ROOT_TOKEN" > "$TOKEN_FILE"
chmod 644 "$TOKEN_FILE"

echo "==> Vault ready (prod mode, file backend, unsealed)."
echo "==> Root token written to $TOKEN_FILE."
echo "==> Mounts: transit/, cloudlearn-kv/"

# Wait on the server. Exits when the server exits (or when SIGTERM is
# forwarded above).
wait "$VAULT_PID"
