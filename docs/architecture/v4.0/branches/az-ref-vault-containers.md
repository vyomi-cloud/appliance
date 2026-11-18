# v4/az-ref-vault-containers: Key Vault crypto with the real SDK + Container Apps that run (Azure reference app, lane 7)

Base `origin/v4-on-main`. Gaps found by the Azure app lane (`v4/az-ref-app`): component 13 (Key Vault `kid` / vault host) and component 3 (Container App ingress).

## Changes
### Key Vault (C13)
- Cause of `VaultNotFound '_'` / `CryptographyClient(key.id)` failures: (1) root-path requests are rewritten to `/azure-data/keyvault/_/...` and `_` was read as a vault NAME; (2) the SDK rebuilds the vault URL from a key id as `scheme://host:port` only (a path prefix is dropped, and `KeyClient.get_cryptography_client` builds `<vault_url>/keys/<name>` which is an invalid id for a path-form vault URL), while the simulator has no `<vault>.vault.azure.net` host. A path-form vault URL can therefore never work with CryptographyClient.
- Fix (`core/azure_keyvault_secrets_core.py` `vault_of` / `infer_vault*`, used by `core/wire_ingress.py` and the Nano router `core/aws_wire_router.py`): `_` means "no vault"; for Azure SDK traffic with no vault identity the vault is inferred: legacy namespace first, else the vault holding the key/secret/cert name (newest wins), else the only vault. `<vault>.vault.<any host>` Host headers also name the vault. Header-less callers keep the legacy shared namespace (existing access/networking tests unchanged).
- `core/azure_keyvault_keys_core.py`: `GET /keys/{name}/versions`, `POST /keys/{name}/rotate`, `GET|PUT /keys/{name}/rotationpolicy`, REAL EC keys (P-256/384/521/256K, ES256/384/512, raw r||s) and REAL AES oct-HSM keys (A128/192/256 GCM, CBC/CBCPAD, KW) when `cryptography` is importable (RSA was already real).
- Test `tests/conformance/test_azure_ref_vault_sdk.py` (real azure-mgmt-keyvault, azure-keyvault-keys/-secrets/-certificates, azure-mgmt-monitor): vault create/get/list/access policies/RBAC; create RSA/EC/oct, get/list/versions, `CryptographyClient(key.id)` + `get_cryptography_client` wrap/unwrap (RSA-OAEP, -256), encrypt/decrypt, sign/verify (RS256, PS256, ES256), AES-GCM + AES-KW, rotate, rotation policy, backup/delete/purge/restore, soft delete/recover, disable -> 403, secrets set/get/versions/delete/purge, certificate create/get/list, Activity Log has `Microsoft.KeyVault/vaults/write`. Harness `tests/conformance/_az_tls_server.py` (appliance in-process, http + TLS ports, local CA).
- Capability `azure.keyvaults.keys.sdk-crypto`.
### Container Apps (C3 hosting)
- `providers/azure_app_runtime.py`: sandboxed-process runtime. Image `vyomi/python-app*`, or any container carrying `VYOMI_APP_SOURCE_B64` (base64 zip / single .py), runs as a subprocess behind the Cloud Functions sandbox guard (`core/gcp_function_runtime._GUARD_SRC`: scrubbed env, sockets only to loopback + simulator, files confined, no subprocess). Entry: `python -c`/`-m`/script command, `VYOMI_APP_ENTRY`, or `app.py|main.py|server.py`. Other images keep the existing Docker path (command/args are now passed through). Logs, status, stop, restart, stats work for both.
- `core/azure_app_core.py`: `env[].secretRef` is resolved from `configuration.secrets` before the replica starts; runtime record says `sandbox-process` vs `docker`.
- `routes/azure_containerapps_ingress.py` (+ `core/middleware.py` Host rewrite, `server.py` registration): ingress served at `/azure-data/containerapps/<app>/...`, `<app>--<revision>` pinning, and `Host: <app>.<domain>.azurecontainerapps.io`; weighted revision choice from ingress traffic; waits for the replica port (cold start) up to 30 s.
- `providers/azure_services.py`: app resources carry `properties.vyomiIngressUrl`.
- Test `tests/conformance/test_azure_ref_containerapps_sdk.py` (azure-mgmt-appcontainers + HTTP to the app): create, ingress by path and Host header, POST proxying, env + secretRef, loopback callback to the simulator, no egress, no host file reads, host env not inherited, revisions/replicas, traffic weights and revision pinning, stop -> 503 / start, delete kills the process. Capability `azure.containerapps.ingress.sandbox-runtime`.

## Recipe for the app lane
- Key Vault: create `facilities-kv` with azure-mgmt-keyvault models (a plain dict body sends snake_case keys and is ignored). Use `KeyClient("https://localhost:<tls-port>", cred, verify_challenge_resource=False)` (host-only URL, NOT `properties.vault_uri`, which stays the path form for the console), then `CryptographyClient(key.id, ...)` / `kc.get_cryptography_client("ledger-key", verify_challenge_resource=False)` work unchanged. Trust the local CA via REQUESTS_CA_BUNDLE/SSL_CERT_FILE (or lane 5's `VYOMI_AZURE_TLS_PORT`).
- Container App: image `vyomi/python-app:latest`, env `VYOMI_APP_SOURCE_B64` (zip of the agent app, entry `app.py`; reads `PORT`), `VYOMI_ENDPOINT` is preset to the simulator. After create read `properties.vyomiIngressUrl` (ARM GET) and POST `/query` there; the app needs only libraries installed in the simulator's Python.

## Design decisions
- No new backend, no new core module (so the four core lists are unchanged): vault resolution lives in the existing Key Vault cores; the runtime is the existing Container Apps runtime hook plus the existing Functions sandbox guard; the proxy is a route.
- Vault inference only for Azure SDK traffic and only when the request names no vault, so the legacy shared-namespace behaviour and every existing Key Vault test are unchanged.
- The sandbox is a guard-rail (interpreter-level), same honesty as `gcp-ref-sandbox.md`; it is not a container.

## Open issues
- Docker path for non-`vyomi/python-app` images is not exercised by this branch's tests (no suitable local image); only the command passthrough is new.
- Two vaults holding the same key name: inference picks the newest; clients wanting the other must use the path-form vault URL.
- Data-plane key operations are emitted to diagnostic settings (AuditEvent) when configured; they do not appear in the Activity Log (as on real Azure, which logs only control-plane there).
- Scale rules/replicas are records (one replica per revision, no scale-to-zero); system logs are not shipped to Log Analytics; Easy Auth, custom domains, TLS on the app FQDN, internal-ingress isolation not simulated.
- `test_relay_cores_parity` already fails on trunk (`azure_security_automations_core.py` missing from nano-endpoint.html); untouched.
- The AI claims register was not regenerated (partial venv).
