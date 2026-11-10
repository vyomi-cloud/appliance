# Nightly needs-decision (owner/other-cloud items; the agents append, never delete)

## Azure, 2026-11-11 baseline on a bare simulator (v4-preview, no sibling backends)
ENV, not product (need sibling containers, the Docker socket, azure SDK / playwright installed): offline-sdk-python-azure-ops, offline-sdk-python-azure-vm-runcommand
(no `azure` python module), offline-ui-azure-* (playwright not resolvable from the checkout), offline-cli-azure (SQL connectionInfo needs real Postgres),
offline-cli-azure-app job executions (needs Docker to run the job), offline-post-create-azure-event-delivery (webhook delivery to the test receiver).
To verify on the runner stack (nightly-v4.yml), not here.
UNCLEAR: offline-sdk-go-azure-operationalinsights prints PASS lines but is scored 0 passed / 400 failed: check how the Go runner output is counted (harness bug?).

## Azure Key Vault data plane is per SPACE, not per VAULT (found 2026-11-11, real product gap)
Repro (v4-preview): create RG + vault `va`, `PUT /azure-data/keyvault/va/secrets/s1?api-version=7.4`, then
`GET /azure-data/keyvault/neverexisted/secrets/s1?api-version=7.4` -> 200 with the same secret. Deleting the vault, or the whole RG, leaves the secret readable (200);
the secret id is `https://<host>/secrets/s1/<ver>` without a vault name. Cause: `core/azure_keyvault_secrets_core.py` KvStore is one store per space; the vault
only reaches enforcement via the `x-vyomi-vault` header (core/wire_ingress.py ~L601, azure_arm_core `keyvault_network_denied`).
Real Azure: secrets belong to a vault; a missing/deleted vault is 404/`VaultNotFound`, and ids are `https://<vault>.vault.azure.net/secrets/...`.
Impact: `offline-sweepA-azure` "RG delete destroyed Key Vault secrets" stays red (it was masked by a stale test missing api-version until now).
Decision needed: scope the KvStore by vault name (key = vault + secret; keys/certs too; Nano path as well) = a data-model change in shared KV code. Not done overnight.
