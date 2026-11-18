# MCP v4 — Phase 0 discovery (D0)

Status: 2026-11-14 (items 2 and 4 added in run 3). Branch `v4/mcp-v4-knowledge`, base `origin/v4-on-main` @ `41161ac3e`. Answers the "Not yet verified" list of
`vyomi-mcp-v4-spec.md` §1 (spec and plan live outside the repo, in the owner's specs folder). Run unattended; every value below
was observed, not inferred, unless the row says "code reading".

| D0 item | Status |
|---|---|
| 1. Nano wiring per cloud through `:8090` | **done** (headless Nano tab, real SDKs) — table §1 |
| 2. Codespace mesh API target in `vyomi-tunnel list mesh` | **verified locally; real-Codespace confirmation folded into MESH-GOLIVE-CHECKLIST §4** (run 3, §4.1) |
| 3. `vyomi-tunnel list --json` shape | **done** (every branch except a live Codespace) — §2 |
| 4. Space semantics on a mesh (which space a direct `:9000` call hits) | **verified locally; real-Codespace confirmation folded into MESH-GOLIVE-CHECKLIST §4** (run 3, §4.2) |

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

**Resolved in T1 (vyomi-tunnel 1.3.0, same branch, run 2):** the envelope is now `{schema: 1, rows, notes}`; JSON is printed on
every path but a usage error (no credentials: exit 2 with the error as a note); `NoMeshSession`/`SessionEnded` list Nano and note the
Mesh; listing never runs `configureSsh`. The 1.2.x observations below are kept as recorded.

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
| Pro key + live Codespace | Rows verified locally in run 3 (§4.1); a live Codespace is still to confirm (item 2). From code (`mesh-cli.mjs:358-361`): rows `{where:"mesh", name, type: host\|instance\|k3s\|llm\|service, address: "<ip>[:<port0>]", connect}` with `connect` = `vyomi-tunnel forward <name> 6443:6443` (k3s), `ssh <name>.vyomi` (ssh-able), or `vyomi-tunnel forward <name> <p>:<p>` (first port) | | |

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

## 4. Items 2 and 4 — verified locally (run 3, 2026-11-14)

Both items ran on a **local** v4 mesh; no licence, portal, GitHub, Codespace or relay was involved. What a real Codespace still has
to confirm (the ssh transport, the real `docker ps` of a Codespace, the Nano tab against a Codespace mesh) belongs in
`MESH-GOLIVE-CHECKLIST.md` §4. The lines to add there are in §4.3. Run 3 did not edit the checklist, which is outside this branch's paths.

**Rig.** Image `vyomi-mcpv4-mesh:local` built from this worktree (`docker build`, VERSION 4.0.0). `codespace/.devcontainer/mesh/docker-compose.mesh.yml`
ran unchanged as compose project `vyomi-mesh` (so the container is `vyomi-mesh-simulator-1`, as in a Codespace), plus an override in `/tmp`:
image `vyomi-mcpv4-mesh:local`, `127.0.0.1:9100:9000`, and **one deviation**: the network was renamed `mcpv4-run3-net` (and
`VYOMI_INSTANCE_NETWORK` with it). The compose file pins the name `vyomi-net`, and on this machine that network belongs to the owner's
`vyomi` project, which runs its own `simulator` service. Neither the container name nor the classification depends on the network name.
`up -d --pull never simulator` was used because the file says `pull_policy: always` and a local image cannot be pulled. The session token
was minted as in `MESH-LOCAL-VALIDATION.md`: `core.mesh_session.mint('local-max','max', now+8h, key=<random>)`, passed as
`VYOMI_MESH_SESSION_KEY` / `VYOMI_MESH_SESSION_TOKEN`. There was no AI profile. `curl -s 127.0.0.1:9100/mesh/status` returned `mesh: true, headless: true,
version 4.0.0, tier max, locked false, health ok`.

### 4.1 Item 2: the appliance row in `vyomi-tunnel list mesh`

`docker inspect` with the exact format from `wasm/relay/mesh-ssh.mjs` `list()`, run on the mesh project's running containers
(a Codespace runs only those; this Mac runs about 40 others):

```
/vyomi-mesh-simulator-1|vyomi-mcpv4-mesh:local|172.23.0.2 |9000/tcp
```

`classifyTargets()` (imported from `mesh-ssh.mjs`, unmodified) returned two targets: `host` (kind `host`, ports `[22]`) and
**`{name: "vyomi-mesh-simulator-1", kind: "service", what: "service container", ip: "172.23.0.2", ports: [9000]}`**. Through the
`list` mapping in `mesh-cli.mjs`, this becomes the `list mesh --json` row:

```json
{ "where": "mesh", "name": "vyomi-mesh-simulator-1", "type": "service", "address": "172.23.0.2:9000",
  "connect": "vyomi-tunnel forward vyomi-mesh-simulator-1 9000:9000" }
```

So the appliance API target is the **compose container name `vyomi-mesh-simulator-1`, type `service`, port 9000**. The H1 guess
("a service row on :9000") holds. The image `EXPOSE`s only 9000 and compose `expose`s 9000, so `ports[0]` is 9000.

**The name "simulator".**
- The compose-service lookup (`simulatorTarget()`: `docker ps --filter label=com.docker.compose.service=simulator`) **does resolve** the
  service. It is what `httpToSimulator` (the Nano tab's compute calls) uses. On this shared Mac it matched two containers
  (`vyomi-mesh-simulator-1` and the owner's `vyomi-simulator-1`), and `head -1` picked the mesh's. A Codespace has only one.
- `vyomi-tunnel forward simulator 9000:9000` **does not resolve**: `forwardSsh` calls `resolve()`, which tries only `vyomi-i-simulator`,
  `vyomi-simulator` and `simulator` as container names (all "no such container"). It never consults the compose label. The user has
  to type the full name, which is what the `connect` line shows. A tunnel follow-up could make `resolve("simulator")` fall back to
  `composeContainer("simulator")`. This branch does not touch `wasm/**`.

**MCP.** `vyomi mcp` (this branch) was run with `VYOMI_TUNNEL_BIN` set to a fake tunnel that prints `{schema:1, rows, notes}` built
from the classification above, plus `VYOMI_ACCESS_KEY_ID=<dummy>` and `HOME`/`VYOMI_HOME` in `/tmp`. The calls were `initialize`, `vyomi_status` and
`vyomi_reach {scope: mesh}`:

| Scenario | `vyomi_status` selected | Notes |
|---|---|---|
| Codespace rows only, nothing local (`VYOMI_MESH_URL` and `:9000` dead) | `mesh-codespace` (reachable, not serving) | `detail.api_target = vyomi-mesh-simulator-1`; hint ``Run `vyomi-tunnel forward vyomi-mesh-simulator-1 9000:9000` ...``; reach lists both rows plus the "no forward yet" note |
| + a forward row `127.0.0.1:9100 -> vyomi-mesh-simulator-1:9000`, `VYOMI_MESH_URL=http://127.0.0.1:9100`, `:9000` dead | `mesh-codespace` (serving, endpoint `http://127.0.0.1:9100`) | mesh-local is folded in ("this port is the Codespace forward"); `active_space` and `spaces_warning` from the mesh |
| Codespace rows, `VYOMI_MESH_URL=:9100`, no forward row, `:9000` dead | `mesh-local` (`:9100`) | `mesh-codespace` reachable with the same `api_target` |
| Either of the above with the owner's offline appliance live on `:9000` | none (`several homes answer (mesh-local, offline)` / `(offline, mesh-codespace)`) | correct: two homes serve; the hint asks which space |

`codespaceHome` picks the appliance row as is, so item 2 needed **no fix**.

### 4.2 Item 4: several spaces on one mesh

A fresh mesh already has **three spaces, one per cloud**: `space-legacy` (aws-default, active), `space-azure-default` and
`space-gcp-default`. Two more AWS spaces were created with `POST /api/spaces {provider: aws, name}` (`run3-one` = `space-df5afd24f69c`,
`run3-two` = `space-2eaf506b27fd`). **Creating a space does not activate it.** After each step, boto3 1.44.3 (path-style, dummy keys,
`endpoint_url=http://127.0.0.1:9100`) ran `create_bucket` and `list_buckets`:

| Step | `/api/spaces/active` | `create_bucket` | `list_buckets` (= space answering) |
|---|---|---|---|
| 0 fresh mesh | space-legacy (aws-default, aws) | run3-b0 ok | run3-b0 → **aws-default** |
| 1 after creating run3-one + run3-two | space-legacy (unchanged) | run3-b-aftercreate ok | run3-b-aftercreate, run3-b0 → **aws-default** |
| 2 switch → run3-one | space-df5afd24f69c | run3-b1 ok | run3-b1 → **run3-one** |
| 3 switch → run3-two | space-2eaf506b27fd | run3-b2 ok | run3-b2 → **run3-two** |
| 4 switch back → run3-one | space-df5afd24f69c | — | run3-b1 → **run3-one** (isolated, kept) |
| 5 switch → aws-default | space-legacy | — | run3-b-aftercreate, run3-b0 → **aws-default** |
| 6 switch → gcp-default (a GCP space active) | space-gcp-default (gcp), unchanged by the call | run3-b-gcpactive ok | run3-b-aftercreate, run3-b-gcpactive, run3-b0 → **aws-default** (the pivot) |
| 7 switch → run3-two | space-2eaf506b27fd | — | run3-b2 → **run3-two** |

**Answer to spec Q4.** On a mesh, nothing in a direct SDK or CLI call picks the space. A call for cloud X lands in the mesh's own,
process-wide **active space when that space is an X space**. Otherwise it lands in **the first X space** (`_SpaceScopedDictProxy._pivot_to_matching_space`,
`core/app_context.py:907`, which walks the spaces in insertion order), and the active space does not change (step 6). Each space
keeps its own buckets. The mesh's active space changes only with `POST /api/spaces/<id>/switch` on the mesh.

**How the Nano tab differs** (code reading, `wasm/` unchanged). The Nano tab keeps its active space in the browser: `sw.js:1478` handles
`POST /api/spaces/<id>/switch` by writing IndexedDB `meta.active` only, and `mesh-link.js` learns `active` from the service
worker's answers (`setActive`, `localStorage vyomi.active_space`). For a mesh-homed active space, or any compute call during a portal
session, `mesh-link.js` forwards `/_wire/*` to the mesh with only the session or mesh token. **No space id is sent**, so the mesh serves
its own active space, or the first space of the call's cloud. The space a Nano user selects and the mesh space that answers are
therefore independent. Switching in the Nano console does not move a laptop SDK call either, and neither does it move the tab's own mesh-routed calls.

**`vyomi_status` (`VYOMI_MESH_URL=http://127.0.0.1:9100`).** `active_space` reported the mesh's `/api/spaces/active`, `run3-two`, correctly.
`spaces_warning` **was seen**, but the original wording had two defects, both fixed in `cmd/vyomi/mcp_tools.go` (`spacesWarning`):
1. The warning appeared on **every fresh mesh** ("This mesh hosts 3 spaces", with one space per cloud and no ambiguity). Now it appears
   only when some cloud has more than one space.
2. It said "switch spaces in the Nano console", which does not change the mesh. Now it names where each cloud's calls land and how
   the mesh's active space really changes. Output after the fix, on this mesh: *"This mesh hosts 5 spaces (3 aws). Direct SDK and CLI
   calls to http://127.0.0.1:9100 go to ONE space per cloud: the mesh's own active space for its cloud, otherwise that cloud's first
   space. Now: aws -> run3-two (the active space); azure -> azure-default; gcp -> gcp-default. Switching spaces in the Nano console does
   not change this; only POST http://127.0.0.1:9100/api/spaces/<space_id>/switch on the mesh does. Ask the user which space they mean
   before creating resources."*

   Regression test: `TestMCPStatusMeshSpacesWarning`, which fails on the old code and uses the `/api/spaces` bodies from this run.

### 4.3 For `MESH-GOLIVE-CHECKLIST.md` §4 (real Codespace; to add, not added by this branch)
- [ ] `vyomi-tunnel list mesh --json` shows `{where: mesh, name: vyomi-mesh-simulator-1, type: service, address: <ip>:9000}` (and nothing else from
      the compose project unless the AI profile runs); `vyomi-tunnel forward vyomi-mesh-simulator-1 9000:9000`, then `curl -s 127.0.0.1:9000/mesh/status`
      → `mesh: true`. `vyomi_status` selects `mesh-codespace` (serving).
- [ ] Two AWS spaces on the Codespace mesh: a laptop `aws --endpoint-url http://127.0.0.1:9000 s3 ls` follows the mesh's `/api/spaces/active`,
      not the space selected in the Nano tab; `vyomi_status` shows `spaces_warning`.
