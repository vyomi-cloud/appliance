# java-orders

Real Spring Boot 3 / Java 17 web app that exercises the **full AWS surface** of the CloudLearn simulator end-to-end.

## What it touches

| Service | What the app does | Backed by |
|---|---|---|
| **RDS Postgres** | `orders` table CRUD | `postgres:16-alpine` |
| **S3** | Receipt HTML upload, presigned URL | MinIO (real bytes) |
| **SQS** | Async `OrderProcessing` queue + worker | ElasticMQ |
| **EventBridge** | `OrderCreated` events | NATS |
| **Secrets Manager** | DB password loaded at startup | Vault KV |
| **KMS** | Credit-card field encrypted before insert | Vault transit |
| **IAM** | Role exists check (sets `iam-role`) | Cedar (read-only) |

## HTTP API

```
POST /orders            { customer, total_cents, cc } → KMS encrypt + INSERT + publish + enqueue
GET  /orders                                          → SELECT all
GET  /orders/{id}                                     → SELECT one
GET  /orders/{id}/receipt                             → HTML → S3 → presigned URL
GET  /health                                          → 5-way readiness probe
```

## Running

```bash
# Build:
docker build -t java-orders:latest .

# Run (point at the simulator):
docker run --rm --network host \
  -e AWS_ENDPOINT_URL=http://192.168.252.7:9000 \
  -e SECRET_NAME=prod/orders/db \
  -e BUCKET=orders-receipts \
  -e QUEUE_NAME=orders-processing-queue \
  -e KMS_KEY_ID=alias/orders-cc-key \
  java-orders:latest

# Once running, hit it:
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/orders -d '{"customer":"alice","total_cents":4999,"cc":"4111111111111111"}' -H "Content-Type: application/json"
curl http://127.0.0.1:8080/orders
curl http://127.0.0.1:8080/orders/1/receipt
```

## Pre-requisites in the simulator

The app expects these AWS resources to exist (the **two e2e validation passes** create them):

1. Secrets Manager secret named `prod/orders/db` with JSON value:
   ```json
   {"url":"jdbc:postgresql://192.168.252.7:5432/<dbname>","user":"<user>","password":"<pw>"}
   ```
   (The `console-pass` Playwright test or the API-pass JUnit test creates a real Postgres DB via the simulator's Azure-SQL-style provisioning path and writes the connection string into Secrets Manager.)
2. KMS key alias `alias/orders-cc-key`
3. S3 bucket `orders-receipts`
4. SQS queue auto-created on first message

## Two validation passes

| Pass | Location | What it does |
|---|---|---|
| **Console pass** | `../console-pass/java-orders.spec.ts` (Playwright) | Headless browser drives `/console/aws` → clicks Create on each service → fills the wizards → then runs the app + asserts its endpoints respond correctly |
| **API pass** | `src/test/java/cloudlearn/orders/ApiPassTest.java` | JUnit5 test uses `aws-sdk-java-v2` directly to provision the 5 resources → starts the app → hits its endpoints |

Both passes prove the **same** end-to-end: the app, when deployed, talks correctly to every backend through the simulator.
