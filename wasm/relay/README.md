# Vyomi-Nano relay — external apps ↔ the in-browser sim

This is **step 4** of the Nano architecture (see `../NANO-ARCHITECTURE.md`): how an
**external application on the host OS** reaches the simulator running in a browser
tab. A browser tab can't accept inbound TCP, so it connects **out** over a
WebSocket and registers; the relay holds that WS and forwards external HTTP to it.

```
external app (aws-cli / boto3 / your service) ──HTTP──▶ relay ──WS──▶ Nano tab
        endpoint = <relay>/<session>                          (Pyodide + AwsWireRouter → all 7 cores)
```

The tab serves **all 7 services** (S3 · DynamoDB · KMS · Secrets · SQS · SNS · IAM ·
RDS) **plus the RDS Data API** (`boto3.client('rds-data')` → real SQL on the in-browser
engine). `core/aws_wire_router.py` inspects each forwarded request the way a real cloud
front-end does — SigV4 credential scope, then `X-Amz-Target`, then the Query `Action`
(and the rest-json path for Data API) — and dispatches to the owning proven core in its
native wire. Proven on host CPython AND Pyodide by
`tests/conformance/test_aws_wire_router.py` (22 checks) + `test_rds_data_core.py`. The
Data API is async (it awaits the SQL engine), so the tab routes through
`AwsWireRouter.ahandle`.

Both deliveries share **one WS protocol** (`nano-endpoint.html` is the tab side):
```
relay → tab : {id, method, path, query, headers, body(base64)}
tab → relay : {id, status, headers, body(base64)}
```

## Connect an external CLI / SDK / curl

Point any AWS tool at the relay endpoint — nothing about your app changes except the
endpoint URL. A Nano tab must be open and registered (`GET /health` → `{"tab":true}`).

| | Endpoint URL |
|---|---|
| Local tunnel | `http://127.0.0.1:8090` |
| Cloud tunnel | `https://relay.vyomi.cloud/<session>` |

### 1. Set credentials (required once per shell)
The sim never verifies the SigV4 signature, but the AWS CLI/SDK refuse to *sign* a
request with no credentials (`Unable to locate credentials`). Any non-empty values work.
S3 bucket ops also need **path-style** addressing (there's no `*.127.0.0.1` vhost DNS):

```sh
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_S3_ADDRESSING_STYLE=path          # or: aws configure set default.s3.addressing_style path
```
One-off inline (no persistent export):
```sh
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 \
  aws --endpoint-url http://127.0.0.1:8090 s3 ls
```

### 2. aws CLI (native, unchanged except `--endpoint-url`)
```sh
EP=http://127.0.0.1:8090
aws --endpoint-url $EP s3 mb s3://my-bucket
aws --endpoint-url $EP s3 ls
aws --endpoint-url $EP s3 cp ./file.txt s3://my-bucket/
aws --endpoint-url $EP dynamodb list-tables
aws --endpoint-url $EP sqs create-queue --queue-name jobs
aws --endpoint-url $EP kms create-key
```

### 3. boto3 / native SDK
```python
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3", endpoint_url="http://127.0.0.1:8090",
    aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1",
    config=Config(s3={"addressing_style": "path"}),
)
s3.create_bucket(Bucket="my-bucket")
print([b["Name"] for b in s3.list_buckets()["Buckets"]])

# RDS Data API → real SQL on the in-browser engine (PGlite/sqlite3)
rds = boto3.client("rds-data", endpoint_url="http://127.0.0.1:8090",
                   aws_access_key_id="test", aws_secret_access_key="test",
                   region_name="us-east-1")
rds.execute_statement(resourceArn="arn:aws:rds:us-east-1:0:cluster:nano",
                      secretArn="arn:aws:secretsmanager:us-east-1:0:secret:nano",
                      database="app", sql="select 1 as n")
```

### 4. curl (no signing — the sim ignores it; S3 is path-style)
```sh
EP=http://127.0.0.1:8090
curl $EP/                                   # S3 ListAllMyBuckets (XML)
curl -X PUT $EP/my-bucket                    # create bucket
curl -X PUT --data-binary @file.txt $EP/my-bucket/file.txt   # put object
curl $EP/my-bucket/file.txt                  # get object
curl -X DELETE $EP/my-bucket                 # delete bucket
```

### 5. GCP — gcloud CLI (no `auth login`)
gcloud refuses to run without an account and would otherwise phone home to real Google.
**Disable credentials** and **override the storage endpoint** instead — this is gcloud's
equivalent of the dummy AWS creds:
```sh
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_CORE_PROJECT=demo                 # matches the Nano GCP console project
export CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE=http://127.0.0.1:8090/storage/v1/

gcloud storage buckets create gs://my-bucket
gcloud storage ls
gcloud storage cp ./file.txt gs://my-bucket/
```
Persistent equivalent (writes `~/.config/gcloud`, so you don't repeat it):
```sh
gcloud config set auth/disable_credentials true
gcloud config set project demo
gcloud config set api_endpoint_overrides/storage http://127.0.0.1:8090/storage/v1/
```
Notes:
- The storage override **must end in `/storage/v1/`** (the path the relay routes to the GCS core).
- `gcloud storage rm --recursive` isn't supported yet (it calls a `/storageLayout` endpoint
  the core doesn't implement); create / list / cp / objects work.
- Other GCP services follow the same pattern — `CLOUDSDK_API_ENDPOINT_OVERRIDES_<SERVICE>`
  (e.g. `_FIRESTORE`, `_PUBSUB`, `_SECRETMANAGER`, `_CLOUDKMS`, `_SQLADMIN`) → `http://127.0.0.1:8090/`.

### 6. Azure — az CLI (no `az login`)
Point `az storage` at the relay with the **well-known Azurite connection string**, overriding
`BlobEndpoint` — no `az login`, and the sim ignores the Shared-Key signature (tested live):
```sh
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:8090/devstoreaccount1;"

az storage container create --name my-container
az storage container list -o table
az storage blob upload --container-name my-container --name hi.txt --file ./hi.txt --overwrite
az storage blob list   --container-name my-container -o table
az storage blob download --container-name my-container --name hi.txt --file ./out.txt
```
Notes:
- The `AccountKey` is the fixed public Azurite dev key — any value works (the sim doesn't
  verify the signature); keep it so `az` accepts the connection string.
- `BlobEndpoint` **must include the `/devstoreaccount1` account segment** (the relay strips it).
- Azure Blob is a **data-plane** API (what `az storage` uses) — distinct from ARM account
  management (the console's control plane). Queue works the same way with `QueueEndpoint=…;`
  + `az storage queue`; Cosmos / Key Vault are reachable over the relay via their own endpoints.

### Shared state — UI, cmd, curl, and SDK are one store
Resources you create in **any** Nano console UI (AWS/GCP/Azure) are visible to the CLI/SDK/
curl, and vice-versa — **every service of every cloud** draws from one shared store set
(`nano_registry`), and that set syncs across the console tab and the relay worker via
IndexedDB + a BroadcastChannel (so it also survives reload). Create and list through the
same relay during a session. Note: a SharedWorker endpoint only picks up code changes after
its version bumps or you close **all** same-origin tabs and reopen.

## Files
```
nano-endpoint.html      tab side (standalone) — boots Pyodide, loads all vendored cores +
                        aws_wire_router, registers over WS, dispatches to the REAL cores
relay-shared-worker.js  tab side (SharedWorker) — hosts the endpoint across navigation +
                        auto-detects local vs cloud tunnel and switches dynamically
local-relay.mjs         LOCAL tunnel (Node + ws) — brew-installable as `vyomi-tunnel`
worker.js               CLOUD tunnel — Cloudflare Worker + Durable Object (deployed)
wrangler.toml           Cloudflare config (DO + custom domain + ALLOWED_ORIGIN)
e2e-relay.mjs           headless proof: external client → relay → tab (real core) → response
```

## Validate locally (proven green)
```sh
# 1. serve the repo root so /core/*.py and /wasm/relay/*.html are reachable
python3 -m http.server 8000
# 2. start the local relay (needs the `ws` package; WS_PKG points at it)
WS_PKG=/path/to/node_modules/ws node wasm/relay/local-relay.mjs      # :8090
# 3. run the loop e2e (Playwright)
PW=/path/to/node_modules/playwright node wasm/relay/e2e-relay.mjs
```
Proves (in a REAL browser, headless Chromium): an external HTTP client validated
against the in-browser sim across **all 7 services** — S3 (PUT/GET/LIST), DynamoDB
(typed items), KMS (Encrypt→Decrypt), SQS (Send/Receive), IAM + RDS (Query/XML) —
**plus the in-tab SQL bridge running real Postgres (PGlite)**. The **core goal**
(test an external client against the in-browser sim), no install on the sim side
beyond a tab. A fully self-contained runner (starts its own static server + relay +
browser) lives in the session scratchpad as `e2e-browser.mjs`.

## Two tunnels — local + cloud, auto-selected

The Nano tab reaches a relay two ways and **prefers local, falling back to cloud**
automatically (see `../../docs/guides/nano-tunnel.md`):

| | Local tunnel | Cloud tunnel |
|---|---|---|
| Install | `brew install vyomi-cloud/tap/vyomi-tunnel` | none |
| Endpoint | `http://127.0.0.1:8090` | `https://relay.vyomi.cloud/<session>` |
| Impl | `local-relay.mjs` (this dir) | `worker.js` on Cloudflare |

Selection lives in `relay-shared-worker.js`: it probes the local relay's
`GET /health` every 15 s and switches either direction with no reload.

## Cloud relay (Cloudflare) — DEPLOYED & live at `relay.vyomi.cloud`

Deployed to the Vyomi Cloudflare account as a Worker + SQLite-backed Durable
Object, bound to a Custom Domain. `wrangler.toml` carries it:
`new_sqlite_classes=["RelaySession"]` (free-plan-safe), `[[routes]] pattern =
"relay.vyomi.cloud" custom_domain = true`, `ALLOWED_ORIGIN = "https://vyomi.cloud"`.

```sh
cd wasm/relay
npx wrangler deploy     # redeploy after changes (provisions the custom domain + cert)
npx wrangler dev        # optional: local miniflare — re-run e2e-relay.mjs against the dev URL
```
The user's existing app, unchanged except the endpoint:
```sh
aws --endpoint-url https://relay.vyomi.cloud/<session> s3 ls    # + path-style for S3
```
Validated end-to-end against the live edge with `e2e-relay.mjs` (all 7 services +
PGlite SQL bridge + RDS Data API). The cloud tunnel is gated to `https://vyomi.cloud`,
so it's usable once the Nano bundle is served from there; local dev uses the local
tunnel above.

## Notes
- **Cost:** Cloudflare = no egress fees + DO WebSocket hibernation → near-free at scale.
- **Guardrails (in `worker.js`):** `ALLOWED_ORIGIN` check on register; the unguessable
  `session` id is the bearer capability (like a share link); 6 MiB payload cap (413);
  64 in-flight cap per session (429); 20 s tab timeout (504); alarm-based keepalive ping
  so background-tab throttling can't silently drop the held WS; a fresh tab supersedes a
  stale one on reconnect. Hibernation API (drop in-memory state between requests) is the
  remaining cost optimization — see NANO-ARCHITECTURE.md §7.
- **Local tunnel** (`vyomi-tunnel`, `local-relay.mjs`) is the same protocol with the
  relay on `localhost` — a drop-in offline/private alternative, auto-detected and
  preferred over the cloud tunnel when running. `brew install vyomi-cloud/tap/vyomi-tunnel`.
