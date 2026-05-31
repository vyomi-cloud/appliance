# go-inventory

Real Go web app (chi router + pgx + google-cloud-go SDKs) that exercises the **full GCP surface** of the CloudLearn simulator end-to-end.

## What it touches

| Service | What the app does | Backed by |
|---|---|---|
| **Cloud SQL Postgres** | `items` table CRUD | `postgres:16-alpine` |
| **Cloud Storage** | item image upload + public URL | fake-gcs-server (real bytes) |
| **Pub/Sub** | `ItemCreated` events + worker subscription | Google Pub/Sub emulator |
| **Eventarc** | `on-item-create` trigger fired on each POST | NATS (via :fire shim) |
| **Secret Manager** | DB creds JSON loaded at startup | Vault KV |
| **Cloud KMS** | SKU encrypted before insert | Vault transit |
| **IAM** | service account exists check | Cedar (read-only) |
| **Compute Engine** | app runs in a GCE LXD container | LXD/multipass |

## HTTP API

```
POST /items            { name, sku, stock } → KMS encrypt + INSERT + publish + trigger
GET  /items                                 → SELECT all
GET  /items/{id}                            → SELECT one
GET  /items/{id}/image                      → upload PNG to Cloud Storage, return URL
GET  /health                                → 5-way readiness probe
```

## Running

```bash
docker build -t go-inventory:latest .

docker run --rm --network host \
  -e GCP_ENDPOINT_URL=http://192.168.252.7:9000 \
  -e PUBSUB_EMULATOR_HOST=192.168.252.7:8085 \
  -e PROJECT=inventory-app \
  -e SECRET_NAME=inventory-db-creds \
  -e BUCKET=inventory-images \
  -e KMS_KEYRING=inventory-keyring \
  -e KMS_KEY=sku-key \
  -e PUBSUB_TOPIC=inventory-events \
  -e PUBSUB_SUB=inventory-worker \
  go-inventory:latest

curl http://127.0.0.1:8081/health
curl -X POST http://127.0.0.1:8081/items -d '{"name":"widget","sku":"W-001","stock":5}' -H "Content-Type: application/json"
curl http://127.0.0.1:8081/items
curl http://127.0.0.1:8081/items/1/image
```

## Pre-requisites in the simulator

1. Secret Manager secret `inventory-db-creds` (JSON payload `{"url":"...","user":"...","password":"..."}`)
2. KMS keyring `inventory-keyring` + cryptoKey `sku-key`
3. Cloud Storage bucket `inventory-images`
4. Pub/Sub topic `inventory-events` + subscription `inventory-worker`
5. Eventarc trigger `on-item-create` (optional — graceful no-op if missing)

These are created by the **two e2e validation passes**.

## Two validation passes

| Pass | Location | What it does |
|---|---|---|
| **Console pass** | `../console-pass/go-inventory.spec.ts` (Playwright) | Headless browser drives `/console/gcp` → clicks Create on each service → fills the wizards → then runs the app + asserts its endpoints respond correctly |
| **API pass** | `api_pass_test.go` | Go test uses `cloud.google.com/go` directly to provision the 6 resources → starts the app → hits its endpoints |

Both passes prove the same e2e wiring through different entry points.
