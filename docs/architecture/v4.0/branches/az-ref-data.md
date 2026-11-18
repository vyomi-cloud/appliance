# v4/az-ref-data: real Azurite behind Table/Queue + Table and Cosmos wire fixes

Lane 4 of the Azure 13/13 reference-architecture build (probe: `docs/architecture/v4.0/REF-ARCH-PROBE-AZURE.md` component 5, `examples/ref-arch-probe/azure/probe_05_approval.py`). Offline / Mesh only for the real backend; Nano keeps the in-browser cores; default (flag off) behaviour changes only by the wire fixes below.

## Changes

| File | What |
|---|---|
| `core/azure_real_backends.py` (new, appliance only, not in the Nano CORES lists) | `VYOMI_AZURE_REAL_BACKENDS=1` + `VYOMI_AZURE_AZURITE_ENDPOINT` replaces `azure_table_core.dispatch` and `azure_queue_core.dispatch` with wrappers that forward the native REST request to Azurite, re-signed with the devstoreaccount1 key (SharedKeyLite for Table, SharedKey for Queue). Installed from `server.py` and `wire_ingress.appliance_router()` (idempotent, no-op when off / emscripten). |
| `core/azure_table_core.py` | PATCH + MERGE verbs, full OData `$filter` (eq/ne/gt/ge/lt/le, and/or/not, parens, typed literals), `$select`, `$top` as page size with `x-ms-continuation-NextPartitionKey/NextRowKey`, `If-Match` -> 412 `UpdateConditionNotSatisfied` / 404, upsert vs update semantics, `Prefer: return-no-content` (204), `$batch` multipart changesets (atomic, one partition, error index), `/t()` collection form. |
| `core/aws_wire_router.py` | `/$batch` requests are classified as Table (the SDK sends `Accept: application/json` there). |
| `core/azure_cosmos_core.py` | `If-Match` -> 412 on replace/patch/delete, `_rid`/`_self` link resolution, PATCH (`set/add/replace/remove/incr/move` + filter predicate), `x-ms-max-item-count` + `x-ms-continuation` paging for read-all and query, transactional batch (200 / 207 + 424, atomic). |
| `core/azure_dataplane.py` | PATCH allowed on the legacy per-account Cosmos route (was the 405). |
| `core/azure_arm_core.py` | ARM `tableServices/tables` PUT answers 200 (the spec; `azure-mgmt-storage` `table.create` rejected 201). |
| `docker-compose.appliance.yml`, `docker-compose.yml`, `codespace/.devcontainer/mesh/docker-compose.mesh.yml` | Azurite gains `--tableHost/--tablePort 10002` (+ published port); env passthrough; Mesh gets profile `azure-real` with `azure-azurite` (loopback-bound 10000/10001/10002). |
| `core/capabilities/azure/{storage,cosmos}.json`, `backends/azure.json` | `azure.storage.tables_sdk_wire`, `azure.storage.tables_real_azurite`, `azure.cosmos.item_wire`; storage notes/differs updated honestly. |
| Tests | `test_azure_table_wire_sdk.py` (flag off, own core), `test_azure_cosmos_wire_sdk.py`, `test_azure_real_backends.py` (docker image or `AZURITE_BIN`; SKIPs cleanly), helpers `_az_inproc.py`, `_az_table_scenario.py`. |

## How to switch the real mode on

* Offline appliance: `VYOMI_AZURE_REAL_BACKENDS=1 VYOMI_AZURE_AZURITE_ENDPOINT=http://vyomi-azurite docker compose -f docker-compose.appliance.yml up -d` (Azurite already runs; Table :10002, Queue :10001).
* Mesh: `VYOMI_AZURE_REAL_BACKENDS=1 VYOMI_AZURE_AZURITE_ENDPOINT=http://azure-azurite docker compose -f docker-compose.mesh.yml --profile azure-real up -d azure-azurite simulator`.
* Ports: `VYOMI_AZURE_AZURITE_TABLE_PORT` (10002), `VYOMI_AZURE_AZURITE_QUEUE_PORT` (10001); `VYOMI_AZURE_REAL_QUEUE=0` keeps Queue on the own core.
* Apps use the same connection string either way: `TableEndpoint=<simulator>/devstoreaccount1` (or Azurite directly: `http://<azurite>:10002/devstoreaccount1`).

## Design decisions

* Same seam as the GCP real mode: the wrappers sit on the two core `dispatch` functions every caller already uses, so nothing else is rewired and Nano is untouched. No silent fallback: an unreachable Azurite answers 503 naming the endpoint.
* The account in the request path is ignored; everything lands in Azurite's single `devstoreaccount1`.
* No own Cosmos engine invented: Cosmos stays Vyomi's own core (no usable open-source engine); never claimed real.
* Cosmos tier: `core/tier_policy.py` maps cosmos to `nosql` (Max on a licensed appliance); tests run with `CLOUDLEARN_TIER_ENFORCE=0`. Gating itself was not re-tested here.

## Open issues

* Real mode: Table service properties/CORS/metrics, ARM table records and anything reading the in-process queue store directly (Event Grid storage-queue destination checks the local queue list) stay on the simulator's state. ARM queue records (`queueServices/default/queues`) are not modelled at all (404, pre-existing).
* Real mode keeps no data-plane state in the simulator, so `azure.storage.tables` console views that list the own store do not show Azurite tables.
* Cosmos: stored procedures / triggers / UDFs not implemented; continuation tokens are offsets over a materialised result.
* `tests/conformance/test_relay_cores_parity.py` fails on trunk for `azure_security_automations_core.py` (nano-endpoint.html CORES), not touched here.
* The real-Azurite test was verified here with the npm `azurite@3.35.0` binary (`AZURITE_BIN`), because Docker Desktop's daemon was down mid-session; the docker path and the compose files are written but not exercised.
