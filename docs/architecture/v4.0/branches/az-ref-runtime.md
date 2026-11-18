# v4/az-ref-runtime

Owner: Azure reference-arch lane 6 - Started: 2026-11-18 - Base: origin/v4-on-main (1e285e638) - Status: ready for review

## Purpose
Reference components 7 (Tools) and 8 (Observability) on Azure: a deployed Function App must reach the simulator with the REAL Azure SDKs, be
addressable like `https://<app>.azurewebsites.net/api/<fn>` with function keys, show up in ARM, and Application Insights telemetry must be
queryable in the Log Analytics workspace.

## Changes
- `core/gcp_function_runtime.py` (existing sandbox, reused): Azure Functions worker (`azure_invoke`, `azure_discover`, `azure_function_env`, `azure_libraries`), a managed-identity loopback endpoint in the guard (`IDENTITY_ENDPOINT`/`IDENTITY_HEADER`), and the `azure` namespace is no longer shadowed (the Vyomi `azure.functions` shim is a last-on-path fallback only; the real `azure-functions` package wins).
- `providers/azure_functions_host.py` (new, not a Nano core): zip deploy -> discovered functions (v1 `function.json`, v2 decorators imported in the sandbox) stored in the site record, HTTP front door with route templates/methods/key auth, admin API, trigger seam.
- `core/azure_dataplane.py`: zipdeploy/invoke/`run_function_sync` delegate to the host for zip-deployed apps (legacy single-code apps keep the old path); catch-all `{function_name:path}`.
- `core/middleware.py`: `<app>.azurewebsites.*` Host form -> `/azure-data/functions/<app>/...`.
- `core/azure_arm_ext_core.py`: host/function key ARM routes now fall through to the Microsoft.Web engine (one key store, shared with the host).
- `core/azure_operationalinsights_core.py`: App* tables (8) defined, `ingest_appinsights()`, KQL dynamic member access (`Properties.key`, `Properties["k"]`). `core/azure_monitor_core.py`: component connection string is absolute. `providers/azure_loganalytics_routes.py` + `routes/observability.py`: `/v2/track`, `/v2.1/track`, `/_obs/v2(.1)/track`.
- `requirements.txt`: azure-functions, azure-identity, azure-data-tables, azure-cosmos, azure-servicebus, azure-keyvault-secrets/keys, azure-monitor-opentelemetry-exporter, opentelemetry-sdk (azure-storage-blob/queue already present).
- Capabilities: `azure.functionapp.sdk-runtime`, `azure.appinsights.track-ingest` (+ regenerated `cmd/vyomi/mcp_*`). Tests: `tests/conformance/test_azure_functions_runtime_sdk.py` (25 checks), `tests/conformance/test_azure_appinsights_ingest_sdk.py` (7 checks).

## How a function reaches the simulator
Subprocess per call (scrubbed env), standard Functions env: `FUNCTIONS_WORKER_RUNTIME`, `WEBSITE_SITE_NAME`, `WEBSITE_HOSTNAME`, app settings and connection strings as env, `AzureWebJobsStorage` (blob/table/queue endpoints on the simulator unless the app sets its own), `VYOMI_ENDPOINT` (simulator URL; `VYOMI_SELF_URL` else the last request base else loopback:9000), `VYOMI_AMQP_HOST/PORT` when the host has them, and `IDENTITY_ENDPOINT`/`IDENTITY_HEADER` so `DefaultAzureCredential().get_token()` works (unsigned alg=none JWT; it is always granted, even without a system-assigned identity). Azure SDKs refuse bearer tokens over plain http, so Blob/Table/Cosmos/Service Bus calls from a function use connection strings/keys. Egress is limited to loopback + the simulator, files to the function dir, no subprocess.
Libraries: the appliance wheel set (`gcp_function_runtime.azure_libraries()`); `requirements.txt` is checked against it (no internet), failing the deploy with the available list. Not a VM.

## Contracts for other lanes
- Event Grid / Service Bus delivery to functions: `providers.azure_functions_host`: `functions_with_trigger(rec, "serviceBusTrigger", topicName=..., subscriptionName=...)` (or `queueName`, `eventGridTrigger`, `blobTrigger`) then `invoke_trigger(rec, fn, payload)`; payload per trigger type is documented on `invoke_trigger`. `core.azure_dataplane.run_function_sync(app, fn, method, payload)` keeps its signature (Event Grid AzureFunction destination) and routes non-http triggers to the same seam. Find the app record with `core.azure_dataplane._find_function_app(name)`.
- Function auth: `x-functions-key` / `?code=` = function key, host function key or master key; admin level needs the master key. Keys: ARM `list_function_keys`/`list_host_keys` and `/admin/host/keys` are one store.
- Application Insights: `ingest_appinsights(state, items)` writes into the workspace linked via `WorkspaceResourceId`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Reuse the GCP sandbox runtime (subprocess + audit hook + env scrub) | new executor / Docker | owner rule: no new backend |
| Real `azure-functions` package, shim only as fallback; no `azure/__init__.py` shadow | keep shim shadowing `azure` | function code must import `azure.data.tables`/`azure.cosmos`/`azure.servicebus` |
| v2 functions discovered by importing `function_app.py` in the sandbox at deploy time | regex on source | decorators/bindings are code; never import user code in the simulator process |
| Host logic in `providers/` (offline only), no new core | new core module | Nano cannot spawn processes; avoids the four CORES lists |
| Telemetry into the existing workspace store (`_store`) | separate AI store | one KQL engine, same tables a real workspace-based component has |

## Nano difference
No process spawn: the in-interpreter sandbox stays (stdlib + shims, no SDKs, no function keys); `/v2/track` is not served on Nano.

## Open issues
- [ ] opencensus-ext-azure 1.1.15 is broken on Python 3.13 (handler lock), so its handlers were not exercised; its wire is the same track API.
- [ ] No timer scheduler, no blob/queue listeners, input bindings arrive as None, output bindings are captured not delivered.
- [ ] Classic components (no workspace) accept telemetry but there is no `/v1/apps/{id}/query` or Live Metrics.
- [ ] Parameterised Cosmos queries (`parameters=[...]` returned `[]` in the probe) are lane 4's core; not touched here.
- [ ] Managed-identity token is unsigned; a validating gateway (lane gateway JWKS) would need signed tokens.
- [ ] Per-call process start (about 0.5 s), no warm instances.
- [ ] `test_relay_cores_parity` fails on trunk for `azure_security_automations_core.py` (pre-existing, not from this lane).
- [ ] `test_azure_sdk_webhost_autoscale_apim_prom.py` needs azure-mgmt-apimanagement (skipped in this venv).
