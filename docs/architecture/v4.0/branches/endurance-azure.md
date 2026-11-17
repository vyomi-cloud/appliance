# Branch: v4/endurance-azure

## Why
vyomi-endurance Azure lane: an enterprise reference estate (Terraform / OpenTofu, `hashicorp/azurerm ~> 4.0`) that must pass validate -> apply ->
no-diff re-plan -> destroy -> rebuild -> destroy against the REAL simulator server (`server.py`, port 19104 in this lane). Every defect the real provider
exposes is a simulator bug; the estate is never weakened to dodge one.

## Working provider block (authentication / discovery)
```hcl
provider "azurerm" {
  features {}
  metadata_host                   = "host.docker.internal:19114"       # the TLS front (see below), host:port, no scheme
  subscription_id                 = "00000000-0000-0000-0000-cloudlearn01"
  tenant_id                       = "00000000-0000-0000-0000-0000000000aa"
  client_id                       = "00000000-0000-0000-0000-0000000000bb"
  client_secret                   = "vyomi"                             # any value; the token is unsigned and never verified
  resource_provider_registrations = "none"
}
```
Moving parts (all in `tests/endurance/estate/azure/`):
* `front.py` - HTTPS front in front of server.py (azurerm only talks https). It serves `GET /metadata/endpoints` (cloud-environment document),
  `POST /<tenant>/oauth2/v2.0/token` (unsigned JWT with tid/oid/appid claims), OpenID discovery, and reverse-proxies everything else to
  `http://127.0.0.1:19104`, forwarding `Host` and `X-Forwarded-Proto: https` so the simulator renders `https://host.docker.internal:19114/...`
  into `Location`, `vaultUri` and storage endpoints. It logs every >=400 answer as `front-ERR`.
* `run.sh` - OpenTofu in a Linux container (macOS Go ignores `SSL_CERT_FILE`); trusts `~/.vyomi-endurance-azure/cert.pem`, shared plugin cache
  `~/.vyomi-endurance/plugin-cache`, and `--add-host {acct}.{blob,queue,table,file,dfs,web}.core.windows.net:host-gateway` for every storage account the estate creates
  (`VYOMI_AZURE_STORAGE_ACCOUNTS`).
* The cert needs SANs `host.docker.internal`, `localhost`, `*.{blob,queue,table,file,dfs,web}.core.windows.net`.
* Server env for the lane: `VYOMI_AZURE_STORAGE_SUFFIX=core.windows.net:19114` makes `primaryEndpoints.*` host-style
  (`https://acct.blob.core.windows.net:19114/`); giovanni refuses path-style endpoints. The front's metadata advertises the same storage suffix.
* The simulator's built-in resource group `cloudlearn-rg` already exists, so the estate uses `cloudlearn-rg-endurance`.

## F3 finding (RG create ~20 s): NOT a simulator defect
azurerm's `azurerm_resource_group` create uses a hard-coded custom poller (10 s initial delay, then GET every 5 s until 3 consecutive successes);
delete and every VNet/NSG/subnet delete use the SDK's 10 s default delete-poller interval. Real Azure shows the same floor. We now return
201 on create (real behaviour) but the 20 s remains. Likewise `azurerm_key_vault` waits 30 s + 10 x 10 s on the data plane (~130 s), `azurerm_role_assignment` ~20 s.
What WAS a simulator defect: Network child PUTs (subnets) had no `Azure-AsyncOperation` header, making the SDK wait its 10 s default (F401).

## Simulator fixes (F400-F499)
| F | Fix |
|---|-----|
| F400 | RG PUT returns 201 on create |
| F401 | Network child PUTs (subnets, rules) carry LRO headers (was 10 s default wait per subnet) |
| F402 | roleDefinitions `$filter=roleName eq 'X'` honoured, GUID-named full ids (azurerm resolves role names this way) |
| F403 | Blob service properties data-plane call (`?restype=service&comp=properties`) |
| F404 | Table/Queue `primaryEndpoints` form routable |
| F405 | Cosmos account always returns `backupPolicy.type` |
| F406 | Singleton children answer before any PUT (blob/file/queue/tableServices/default, SQL sqlVulnerabilityAssessments, connectionPolicies, auditing, ... , Service Bus networkRuleSets) |
| F407 | Host-style storage endpoints (`VYOMI_AZURE_STORAGE_SUFFIX`) + Host-based routing of `*.blob.*`, `*.table.*`, `*.queue.*` |
| F408 | singleton PUT answers 200, not 201 |
| F409 | Cosmos child PUTs are LROs (200 + headers) |
| F410 | SQL database exposes `currentServiceObjectiveName` / `currentSku` (azurerm `sku_name`) |
| F411 | Cosmos `failoverPolicies` (azurerm `geo_location`) |
| F412 | Cosmos DELETE is 202 + LRO headers |
| F413 | EventGrid topic create is 201 |
| F414 | Service Bus subscription omits empty `clientAffineProperties` (was a forced replacement) |
| F415 | App Service plan PUT is 200 + LRO headers, not a bare 201 |
| F416 | `deletedWorkspaces` list |
| F417 | `checkNameAvailability` POST |
| F418 | Web app config property bags (`azurestorageaccounts`, `slotConfigNames`, `metadata`, `pushSettings`, `authsettings`) |
| F419 | App Insights component PUT is 200 |
| F420 | Unconfigured web app `config/backup` is 404 (azurerm nil-dereferenced the default document: provider panic) |
| F421 | App Insights `currentbillingfeatures` |
| F422 | App Configuration echoes sku as sent, omits `publicNetworkAccess` unless set |
| F423 | App Insights echoes `SamplingPercentage` etc. |
| F424 | `Microsoft.Security/securityContacts` PUT/GET/DELETE |
| F425 | Azure OpenAI deployment of a legacy model name echoes `format: OpenAI` (was the backing model's vendor, forced replacement) |
| F426 | Cognitive account returns `networkAcls` only when configured |
| F427 | Function app: client-sent app settings win over defaults; no default `APPINSIGHTS_INSTRUMENTATIONKEY` |
| F428 | Key Vault `deletedVaults` GET 404 / `purge` 202 |
| F429 | Deleting a site cascades its `config/*` children (leftovers blocked the resource group delete forever) |

Regression tests: `tests/conformance/test_endurance_azure_core.py` (plus the updated `test_azure_webapp_core.py`).

## Open issues / gaps
Gate result (tests/endurance/run_estate.sh estate/azure host.docker.internal:19114): ESTATE CYCLE PASS, 39 resources, init/validate/apply 143 s /
no-diff replan / destroy 94 s / rebuild 144 s / final destroy 94 s (see `estate/azure/estate-report.json`). Time floors are provider-inherent (RG 20 s, KV ~130 s, role assignment 20 s, SQL DB ~70 s).

Covered capabilities: `tests/endurance/estate/coverage-map.azure.json` (38 ids, verify = tf only; SDK/CLI/UI proof not done in this lane).

Open gaps / not done:
* Stage 2 (VMs, AKS, ACR, Container Apps) and API Management, Defender plans beyond pricing, Event Hubs, Azure SQL/PostgreSQL flexible server, AI Foundry/Search are not in the estate yet.
* Key Vault secrets/keys via the data plane (`azurerm_key_vault_secret`) not attempted.
* `front.py` is still a side process (TLS + metadata + token); the server already serves `/{tenant}/oauth2/v2.0/token`, so metadata + TLS termination are the only missing pieces to fold into the appliance image.
* Host-style storage endpoints need `--add-host` per account name in the container and the `VYOMI_AZURE_STORAGE_SUFFIX` env on the server.
* `tests/conformance/test_azure_one_subscription.py::test_resource_groups_persist_and_delete_cascades` fails on a tags assertion (a second PUT without tags); it was not touched by this branch's status change and looks pre-existing (not bisected).
* Several `test_azure_*` suites need SDK packages (`azure.mgmt`, `azure.cosmos`, ...) that are not in the endurance venv, so they were not run.
* Delete latency: network/SQL/NSG deletes cost 10 s each (SDK default delete poll); returning 202 + `Retry-After` did not shorten it (the poller GETs the resource after its fixed delay), so it is left as real-Azure-like.
