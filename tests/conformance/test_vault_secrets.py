"""v2.5.0 Phase 1 — Secrets cores on REAL Vault KV v2 (durable across fresh store).

Exercises the GCP Secret Manager core (all 3 secrets cores share the KvStore seam);
value survives a fresh store loading from Vault. Host-only (needs a running Vault).
Run:  PYTHONPATH=. python3 tests/conformance/test_vault_secrets.py
"""
import base64, json
from core.vault_backed_store import VaultBackedKvStore
from core import gcp_secretmanager_core as sec

P = "/v1/projects/demo"
def _check(n,c):
    if not c: raise AssertionError(n)
    print(f"  ok  {n}")
def _j(r): return json.loads(r.body.decode()) if r.body else {}

def run() -> int:
    PFX="v25sectest/"
    a = VaultBackedKvStore(prefix=PFX)
    sec.dispatch(a, "POST", f"{P}/secrets", {"secretId":"db-pw"}, {}, json.dumps({"replication":{"automatic":{}}}).encode())
    sec.dispatch(a, "POST", f"{P}/secrets/db-pw:addVersion", {}, {},
                 json.dumps({"payload":{"data":base64.b64encode(b"hunter2").decode()}}).encode())
    # fresh store — must load the secret from Vault
    b = VaultBackedKvStore(prefix=PFX)
    acc = _j(sec.dispatch(b, "GET", f"{P}/secrets/db-pw/versions/latest:access", {}, {}, b""))
    _check("secret value survives a fresh Vault-backed store", base64.b64decode(acc["payload"]["data"]) == b"hunter2")
    # cleanup
    sec.dispatch(b, "DELETE", f"{P}/secrets/db-pw", {}, {}, b"")
    print("\nPHASE 1: ALL GREEN — secrets cores on real Vault KV v2 (fresh-store durable)")
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
