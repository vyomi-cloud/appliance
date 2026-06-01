# Production-mode Vault config used by docker-compose.yml + Helm chart.
# Replaces -dev mode (which loses keys on restart). Backed by file storage —
# fine for the single-instance simulator. For HA, swap to `consul` / `raft`.

ui            = true
disable_mlock = true
api_addr      = "http://0.0.0.0:8200"

storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true   # the simulator-Vault hop is intra-host/intra-pod
}

# Audit log to stdout (captured by docker logs / kubectl logs)
# Note: enabled at runtime via `vault audit enable` in init script,
# not in the config file (Vault doesn't accept audit blocks here).
