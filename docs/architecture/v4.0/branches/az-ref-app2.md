# v4/az-ref-app2: Azure reference app updated to the merged lane fixes (round 2)

Base: `origin/v4/az-ref-integ` (app + lanes ai, messaging, data, gateway, runtime, vault-containers).

## Changes
- App side (`examples/enterprise-facilities-agent/facilities/azure/`): function settings via `update_application_settings` (create-body settings are ignored); AI Search at the native `<host>/azure-data/search/<svc>`; Key Vault created with azure-mgmt-keyvault models and used through a host-only https URL + `CryptographyClient(key.id)`; Container App runs the real supervisor (`vyomi/python-app`, `VYOMI_APP_SOURCE_B64`, ingress read from `properties.vyomiIngressUrl`); `LogsQueryClient` at `/azure-data/loganalytics`; Event Grid system topic + AzureFunction subscription built with SDK models; APIM MCP server API with `source_api_id` and an all-APIs subscription; WAF App Gateway policy and msal ROPC (known port quirk) handled.
- Simulator fixes (minimal): `core/wire_ingress.py` Key Vault inferred vault is now checked against the provider ARM state (SDK follow-up calls with no vault name returned VaultNotFound for ARM-created vaults); `core/azure_search_core.py` indexer `fieldMappings` can name `metadata_storage_*` source fields (they were silently ignored, leaving source/title null) plus the wasm mirror.
- Test: `tests/conformance/test_azure_ref_app.py` (set `AZ_REF_FULL_STACK=1` on the merged tree to assert the eight passing components).

## Status (observed, no model)
8 PASS (C1, C4, C5, C6, C7, C8, C12, C13), 5 BLOCKED(local model: C2, C3, C9, C10, C11), 0 FAIL. Same with `--start-azurite` (Table ledger on real Azurite; container removed by exact name).
Results: `results/azure-e2e-result-app2.json` (+ `-app2-azurite`).

## Design decisions
- Function-code data access uses connection strings from app settings (like real Functions); the hosted supervisor calls tools directly with the host key (gateway path stays covered by C4).
- A vendor-only property (`vyomiIngressUrl`) is read with the SDK's `cls` callback on the real `container_apps.get`.

## Open issues
- Model steps (C2 one step, C3 hosted `/query`, C9 recall, C10 chat/tools/stream, C11 file_search/On Your Data) are unverified here; they need `VYOMI_LLM_ENDPOINT`.
- The harness trusts the local CA through env; msal ROPC needs the host added to `_domains_without_user_realm_discovery` (port quirk).
