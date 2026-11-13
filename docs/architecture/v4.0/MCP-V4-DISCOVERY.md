# MCP v4 — Phase 0 discovery (D0)

Status: 2026-11-14. Branch `v4/mcp-v4-knowledge`, base `origin/v4-on-main` @ `41161ac3e`. Answers the "Not yet verified" list of
`vyomi-mcp-v4-spec.md` §1 (spec and plan live outside the repo, in the owner's specs folder). Run unattended; every value below
was observed, not inferred, unless the row says "code reading".

| D0 item | Status |
|---|---|
| 1. Nano wiring per cloud through `:8090` | **done** (headless Nano tab, real SDKs) — table §1 |
| 2. Codespace mesh API target in `vyomi-tunnel list mesh` | **open - owner run** (needs a Pro/Max key and a running Mesh Codespace) |
| 3. `vyomi-tunnel list --json` shape | **done** (every branch except a live Codespace) — §2 |
| 4. Space semantics on a mesh (which space a direct `:9000` call hits) | **open - owner run** (needs a mesh with two mesh-homed spaces) |

## 0. Rig (exact)

| Part | Value |
|---|---|
| Static server | `python3 -m http.server 8017 --bind 127.0.0.1` at the worktree root. **Deviation:** the planned `:8000` was taken by an unrelated local app and `:8001` by Docker (`*:8001`, IPv6), so `:8017` was used and passed through `TAB_URL`. |
| Relay | `cd wasm/relay && NODE_PATH=/tmp/mcpv4-tools/node_modules RELAY_PORT=8090 node local-relay.mjs` (v1.2.0 banner; `VYOMI_RELAY_AUTH` unset, so no key is read). AMQP raw-TCP listener on `127.0.0.1:5672`. |
| Tab | Playwright 1.65.0, Chrome Headless Shell 158.0.8127.18, `PLAYWRIGHT_BROWSERS_PATH=/tmp/mcpv4-tools/browsers`, page `http://127.0.0.1:8017/wasm/relay/nano-endpoint.html?relay=ws://127.0.0.1:8090/register&core=/wasm/core`. Pyodide v0.26.2 from jsDelivr (`wasm/pyodide-source.json` is `{"local": false}`). Registered in < 1 min; `/health` then reported `tab:true`. |
| Harness | `PW=/tmp/mcpv4-tools/node_modules/playwright RELAY_HTTP=http://127.0.0.1:8090 TAB_URL=<above> node wasm/relay/e2e-relay.mjs`: steps 0–6 PASS (boot, S3, DynamoDB, KMS, SQS, IAM, RDS control plane); **step 7 FAIL** `sql select {"ok":false,"code":"SQLError","message":"error: relation \"t\" does not exist"}` (pre-existing, same defect as `aws-rds-data` below). |
| SDKs | venv `/tmp/mcpv4-venv`, Python 3.12.10: boto3/botocore 1.44.3, azure-core 1.41.0, azure-storage-blob 12.31.1, azure-storage-queue 12.18.1, azure-cosmos 4.17.1, azure-keyvault-secrets 4.12.0, azure-servicebus 7.15.0, google-cloud-pubsub 2.44.0, google-cloud-firestore 2.34.1, google-cloud-storage 3.17.1, grpcio 1.85.1 |
| Probe script | `/tmp/mcpv4-scripts/probe_sdks.py` (not in the repo); raw results `/tmp/mcpv4-logs/probe1.jsonl`, `probe2.jsonl` |

## 1. Nano wiring per cloud through `http://127.0.0.1:8090` (item 1)

Credentials in every row are the dummy ones the offline wiring already hands out (`test`/`test`, the Azurite key, the Cosmos
emulator key, a fake bearer token).

| # | SDK | Call | Env / config used | Result |
|---|---|---|---|---|
| 1 | boto3 | s3 create_bucket, put/get_object, list_objects_v2 | `AWS_ENDPOINT_URL=http://127.0.0.1:8090`, path-style addressing | **works** |
| 2 | boto3 | dynamodb create_table, put_item, get_item | same | **works** |
| 3 | boto3 | sqs create_queue, send, receive | same | **works** (QueueUrl comes back as `https://sqs.us-east-1.amazonaws.com/123456789012/<q>`; boto3 still sends to the endpoint) |
| 4 | boto3 | sns create_topic, subscribe(sqs), publish | same | **works** (fan-out delivered to the SQS subscriber) |
| 5 | boto3 | secretsmanager create_secret, get_secret_value | same | **works** |
| 6 | boto3 | rds create_db_instance + rds-data `SELECT 1` | same | **works** (`[[{"longValue": 1}]]`) |
| 7 | boto3 | rds-data CREATE TABLE, INSERT, SELECT (three calls) | same | **fails**: `BadRequestException: SQLError: error: relation "t" does not exist`. State does not survive between statements on Nano (same as harness step 7). A Nano core defect, not a wiring issue |
| 8 | azure-storage-blob | create_container, upload, download | the **offline** connection string rendered for `:8090`: `BlobEndpoint=http://127.0.0.1:8090/devstoreaccount1;QueueEndpoint=http://devstoreaccount1.queue.localtest.me:8090;` | **works** |
| 9 | azure-storage-blob | same | path-style only: `BlobEndpoint=http://127.0.0.1:8090/devstoreaccount1` | **works** |
| 10 | azure-storage-blob | same | host-style: `BlobEndpoint=http://devstoreaccount1.blob.localtest.me:8090` | **works** |
| 11 | azure-storage-queue | create_queue, send, receive | offline connection string (host-style `QueueEndpoint`, `*.localtest.me` → 127.0.0.1) | **works** |
| 12 | azure-storage-queue | same | path-style `QueueEndpoint=http://127.0.0.1:8090/devstoreaccount1` | **works** |
| 13 | azure-cosmos | create database/container, upsert, read | `AZURE_COSMOS_ENDPOINT=http://127.0.0.1:8090` (root, **plain HTTP**), emulator key | **works** |
| 14 | azure-cosmos | same | offline form `http://127.0.0.1:8090/azure-data/cosmos/devstoreaccount1` | **fails**: `NotFound: Unknown resource path: /azure-data/cosmos/devstoreaccount1` (the Nano router has no `/azure-data/cosmos/<acct>` alias; Cosmos is served at the root) |
| 15 | azure-keyvault-secrets | set_secret, get_secret | `AZURE_KEYVAULT_URL=http://cloudlearn.vault.localtest.me:8090` | **fails** in the SDK, before any request: `ServiceRequestError: Bearer token authentication is not permitted for non-TLS protected (non-https) URLs.` |
| 16 | azure-keyvault-secrets | same, `verify_challenge_resource=False` / root URL / per-call `enforce_https=False` | as 15, and `http://127.0.0.1:8090` | **fails** (same error in all three variants) |
| 17 | azure-servicebus | AMQP send + receive on a queue | `Endpoint=sb://127.0.0.1;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;` (raw TCP `127.0.0.1:5672`) | **works once the entity exists**. Without it: `MessagingEntityNotFoundError ... amqp:not-found` (the in-tab engine answering, so the AMQP path itself is fine) |
| 18 | REST (urllib) | Service Bus entity create | `PUT http://127.0.0.1:8090/<name>` with `content-type: application/atom+xml;type=entry` and a `TopicDescription` body | **works** (HTTP 201). Note the path is the **root**, not `/azure-data/servicebus/<name>` |
| 19 | azure-servicebus | `ServiceBusAdministrationClient.create_queue` | `Endpoint=sb://127.0.0.1:8090;...;UseDevelopmentEmulator=true;` | **fails**: `ServiceRequestError: [SSL: WRONG_VERSION_NUMBER]` (the admin client is HTTPS-only) |
| 20 | google-cloud-storage | create_bucket, upload, download, list | `STORAGE_EMULATOR_HOST=http://127.0.0.1:8090`, `GOOGLE_CLOUD_PROJECT=vyomi-project`, anonymous credentials | **works** |
| 21 | google-cloud-storage | same | as 20 but `GOOGLE_CLOUD_PROJECT=cloudlearn` (today's offline value) | **fails**: `403 ... does not have storage.buckets.list access` (the Nano project is `nano-project`, aliased as `vyomi-project`; `wasm/core/gcp_project.py:30,33,186`) |
| 22 | google-cloud-pubsub | create topic/subscription, publish, pull | `PUBSUB_EMULATOR_HOST=127.0.0.1:8090` | **fails**: hangs until the 40 s probe timeout. gRPC needs HTTP/2; the relay is HTTP/1.1 only (`curl --http2-prior-knowledge http://127.0.0.1:8090/health` → exit 56) |
| 23 | google-cloud-firestore | document set/get | `FIRESTORE_EMULATOR_HOST=127.0.0.1:8090` | **fails**: same timeout, same cause (gRPC) |
| 24 | REST (urllib) | Pub/Sub v1 JSON: PUT topic, PUT subscription, `:publish`, `:pull` | `http://127.0.0.1:8090/v1/projects/vyomi-project/...` | **works** |
| 25 | REST (urllib) | Firestore v1 JSON: createDocument, get | `http://127.0.0.1:8090/v1/projects/vyomi-project/databases/(default)/documents/...` | **works** |

Not exercised (left `"verified": false` in `scripts/mcp_wiring.json` → `homes.nano`): the ARM management SDKs against
`AZURE_RESOURCE_MANAGER_ENDPOINT`, Service Bus AMQP over WebSocket (`ws://127.0.0.1:8090/$servicebus/websocket`), any
non-Python SDK (Node/Java/Go Cosmos and Key Vault SDKs may differ on plain HTTP), and the cloud relay (`nano-cloud`).

### 1.1 What this means for `homes.nano`

| Cloud | Nano value | Differs from offline? |
|---|---|---|
| AWS | `AWS_ENDPOINT_URL=http://127.0.0.1:8090` + the same dummy credentials | endpoint only |
| Azure Storage | the offline connection string with `{sim}` = `http://127.0.0.1:8090` works unchanged (path-style blob, host-style queue) | no |
| Azure Cosmos | `AZURE_COSMOS_ENDPOINT=http://127.0.0.1:8090` (root, plain HTTP; Python SDK verified) | **yes**: offline is `https://{tls}/azure-data/cosmos/{account}`; Nano has no TLS and no path alias |
| Azure Key Vault | **not via the tunnel**: the SDKs refuse bearer auth over plain HTTP | **yes**: drop the value, warn |
| Azure Service Bus | AMQP works: `Endpoint=sb://127.0.0.1;...;UseDevelopmentEmulator=true` (port 5672); create entities first via REST `PUT {sim}/<name>` (atom+xml) or the console | **yes**: the offline note says "REST only, no AMQP" |
| GCP Storage | `STORAGE_EMULATOR_HOST=http://127.0.0.1:8090` | endpoint only |
| GCP project | `GOOGLE_CLOUD_PROJECT=vyomi-project` | **yes**: offline hands out `cloudlearn`, which Nano rejects (403/404) |
| GCP Pub/Sub, Firestore | **not via the tunnel** with the gRPC client libraries; the REST JSON API at `{sim}/v1/projects/vyomi-project/...` works | **yes**: offline points at separate gRPC emulators `:8085` / `:8080` |
| GCP Secret Manager, KMS | not exercised; offline uses `https://{tls}` (REST); on Nano the REST API rides `{sim}` over HTTP. Unverified | yes (no TLS) |

**Spec Q3 (Can Nano serve Cosmos / Key Vault SDKs through the HTTP tunnel?):** Cosmos **yes** (Python `azure-cosmos` over plain
HTTP at the root endpoint). Key Vault **no**: the Azure SDK refuses bearer tokens on non-HTTPS URLs before sending anything, so
`homes.nano` marks it `via_tunnel: false`. This is the client's rule, not the simulator's: only a TLS front (a mesh, or a future
`https://` tunnel listener) fixes it.

## 2. `vyomi-tunnel list --json` (item 3)

Captured with the in-repo canonical CLI (`node wasm/relay/local-relay.mjs list <scope> --json`, v1.2.0 code, the same code
`vyomi-tunnel` 1.2.1 ships). To exercise every branch **without reading `~/.vyomi` or calling vyomi.cloud**, the runs used
`env -i`, `HOME` and `VYOMI_HOME` in a fresh temp dir, dummy `VYOMI_ACCESS_KEY_ID`/`VYOMI_SECRET_ACCESS_KEY` env vars, and
`VYOMI_PORTAL_URL=http://127.0.0.1:18099`: a local fake portal answering `POST /api/tunnel/session` (scripts:
`/tmp/mcpv4-scripts/list-cases.sh`, `fake-portal.mjs`; full output `/tmp/mcpv4-logs/list-cases.txt`).

**Envelope (actual):** `{"targets": [ {where, name, type, address, connect}, ... ], "notes": [string, ...]}`. There is **no
`schema` field**, and the array is named **`targets`, not `rows`** as spec §4.3 says. T1 must decide: rename to `rows`, add
`schema: 1`, or both. The H1 parser reads both names (see the branch document, unattended decisions).

**Exit codes:** 0 when at least one target is listed; 1 when none (JSON still printed); 2 on no credentials or a usage error
(nothing on stdout). An auth failure (`NoMeshSession`, `SessionEnded`, bad key) exits 1 with **no JSON** and one stderr line,
**for every scope, `nano` included**: the session check runs before any scope logic (`wasm/relay/mesh-cli.mjs:330`).

| Case | `list nano --json` | `list mesh --json` | `list all --json` |
|---|---|---|---|
| No credentials | exit 2; stdout empty; stderr `vyomi-tunnel: No Vyomi credentials. Download your access key and secret from https://vyomi.cloud/account/tunnel-credentials ...` | same | same |
| Free key, tab up | exit 0; targets `nano-api` (`where:local, type:api, address:http://127.0.0.1:8090, connect:"aws --endpoint-url http://127.0.0.1:8090 ...   (tab connected)"`) + one row per `/health` VM; notes `[]` | exit 1; `{"targets":[],"notes":["mesh: Mesh needs a Pro or Max plan."]}` | exit 0; nano rows + the mesh note |
| Free/Pro key, relay down | exit 1; `{"targets":[],"notes":["local relay not running on :18091 (run: vyomi-tunnel)"]}` | — | — |
| Pro key, no GitHub login (no Codespace reachable) | as Free | exit 1; notes `["mesh: not signed in to GitHub. Run \`vyomi-tunnel login\`."]` | nano rows + that note |
| Portal says `NoMeshSession` | exit 1; stdout empty; stderr `vyomi-tunnel: Mesh is not running. Start it in the Vyomi console, then retry.` | same | same |
| Session ended (`session_end` past) | exit 1; stdout empty; stderr `vyomi-tunnel: your Mesh session has ended. Start Mesh again in the console.` | same | same |
| Pro key + live Codespace | **open - owner run** (item 2). From code (`mesh-cli.mjs:358-361`): rows `{where:"mesh", name, type: host\|instance\|k3s\|llm\|service, address: "<ip>[:<port0>]", connect}` with `connect` = `vyomi-tunnel forward <name> 6443:6443` (k3s), `ssh <name>.vyomi` (ssh-able), or `vyomi-tunnel forward <name> <p>:<p>` (first port) | | |

Verbatim sample (Free key, tab up, two Nano RDS instances created by the probes):

```json
{
  "targets": [
    { "where": "local", "name": "nano-api", "type": "api", "address": "http://127.0.0.1:8090",
      "connect": "aws --endpoint-url http://127.0.0.1:8090 ...   (tab connected)" },
    { "where": "browser", "name": "db-rds_d0db3b9aa5", "type": "vm", "address": "127.0.0.1:22000",
      "connect": "ssh -p 22000 user@127.0.0.1" },
    { "where": "browser", "name": "db-rds_d0one7808c0", "type": "vm", "address": "127.0.0.1:22001",
      "connect": "ssh -p 22001 user@127.0.0.1" }
  ],
  "notes": []
}
```

Side effects observed in the temp `HOME` (so they would happen in a real home too): `list mesh` with a Pro key writes
`~/.vyomi/ssh_config`, appends to `~/.ssh/config` (`configureSsh({yes:true})`, `mesh-cli.mjs:256`) and runs `gh`, which
writes `~/.local/state/gh/device-id`. The MCP's codespace probe therefore is **not** side-effect free; the H1 probe only runs
`list mesh --json` when `vyomi-tunnel` is installed (spec Q5), with an 8 s cap.

## 3. Other findings

1. **Nano RDS proxies are listed as VMs.** `/health` returned `vms:[{"vm":"db-rds_d0db3b9aa5","port":5432,"host_port":22000}]`
   and `dbs:[]` after an RDS `CreateDBInstance`, so `list` shows them as `type: vm` with an `ssh -p` connect line. The `db-tcp`
   rows (`dbs[]`, `wasm/relay/local-relay.mjs:129`) are never filled for RDS. Owner: tunnel session.
2. **RDS Data API state is lost between statements on Nano** (rows 7 and harness step 7). Owner: Nano core / PGlite.
3. **The offline Service Bus note may be stale.** `scripts/mcp_wiring.json` says "AMQP ... is NOT supported" and the MCP
   instructions repeat it. On Nano, AMQP works (`core/azure_servicebus_amqp.py`). Whether the offline/mesh appliance now
   serves AMQP too was not checked tonight: an L2 item for a mesh run.
4. **GCP project id.** Nano rejects `cloudlearn`; v4 consoles and docs use `vyomi-project`. Whether a v4 mesh still accepts
   `cloudlearn` was not checked: an L2 item.

## 4. Items 2 and 4 — open, owner run

- **Item 2:** with a Pro/Max key and a running Mesh Codespace run `vyomi-tunnel list mesh --json`; record the appliance
  container's `name`, `type` and `address`; then `vyomi-tunnel forward <it> 9000:9000` and `curl -s 127.0.0.1:9000/mesh/status`.
- **Item 4:** on a mesh with two mesh-homed spaces, `aws --endpoint-url http://127.0.0.1:9000 s3 ls` and
  `curl -s 127.0.0.1:9000/api/spaces/active`; note which space answered. Answers spec Q4 (default if unanswered: report the
  mesh's active space and warn when there is more than one).
