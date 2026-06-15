# tests/e2e — reference web apps + two-pass validation

End-to-end tests for the Vyomi simulator's reference web apps. Each app
is a **real production-shape application** that exercises every relevant
backend on its target cloud. Each app is validated through **two passes** so
both the console and the API surfaces are proven end-to-end.

## Layout

```
tests/e2e/
├── java-orders/             ← Spring Boot 3 / Java 17, AWS surface
│   ├── pom.xml
│   ├── Dockerfile
│   ├── README.md
│   ├── src/main/java/cloudlearn/orders/
│   │   ├── JavaOrdersApplication.java   ← Spring Boot bootstrap
│   │   ├── AwsConfig.java               ← 7 AWS SDK v2 client beans
│   │   ├── DataConfig.java              ← reads secret → builds Postgres DataSource
│   │   ├── OrdersController.java        ← POST/GET /orders, /receipt, /health
│   │   └── SqsWorker.java               ← background ProcessOrder consumer
│   └── src/test/java/cloudlearn/orders/
│       └── ApiPassTest.java             ← API pass (JUnit5 + aws-sdk-java-v2)
│
├── go-inventory/            ← Go + chi + pgx, GCP surface
│   ├── go.mod, go.sum
│   ├── Dockerfile
│   ├── README.md
│   ├── main.go                          ← all routes, worker, helpers
│   └── api_pass_test.go                 ← API pass (Go test + cloud.google.com/go)
│
├── console-pass/            ← Playwright specs for the console pass of BOTH apps
│   ├── helpers.ts
│   ├── java-orders.spec.ts              ← drives /console/aws + hits the app
│   ├── go-inventory.spec.ts             ← drives /console/gcp + hits the app
│   └── tsconfig.json
│
├── package.json             ← Playwright + TS deps
├── playwright.config.ts
└── README.md                ← (this file)
```

## What each app validates

### java-orders (AWS)
| Service | Used for | Backend |
|---|---|---|
| RDS Postgres | `orders` table CRUD | `postgres:16-alpine` (via Azure-SQL provisioning path) |
| S3 | Receipt HTML upload + presigned URL | MinIO real bytes |
| SQS | `OrderProcessing` async queue + worker | ElasticMQ |
| EventBridge | `OrderCreated` events | NATS |
| Secrets Manager | DB password loaded at startup | Vault KV |
| KMS | Credit-card field encryption | Vault transit |
| IAM | Role/policy existence check | Cedar |

### go-inventory (GCP)
| Service | Used for | Backend |
|---|---|---|
| Cloud SQL Postgres | `items` table CRUD | `postgres:16-alpine` |
| Cloud Storage | Item image upload + public URL | fake-gcs-server |
| Pub/Sub | `ItemCreated` events + worker subscription | Google Pub/Sub emulator |
| Eventarc | `on-item-create` trigger fire | NATS via :fire shim |
| Secret Manager | DB creds JSON loaded at startup | Vault KV |
| Cloud KMS | SKU encryption | Vault transit |
| IAM | Service-account existence check | Cedar |

## The two validation passes

### 1. Console pass (Playwright)

Drives the simulator's web console to provision resources, then validates the
deployed app responds correctly. Uses REST-level provisioning (faster than
clicking through wizards) plus visual loads of `/console/{aws,gcp}` to assert
the SPA renders the resource graph correctly.

```bash
cd tests/e2e
npm install
npx playwright install chromium

# Build + run the apps first (or point APP_BASE_* at running instances):
( cd java-orders   && docker build -t java-orders:latest .   && docker run -d --network host \
    -e AWS_ENDPOINT_URL=http://192.168.252.7:9000 java-orders:latest )
( cd go-inventory  && docker build -t go-inventory:latest .  && docker run -d --network host \
    -e GCP_ENDPOINT_URL=http://192.168.252.7:9000 \
    -e PUBSUB_EMULATOR_HOST=192.168.252.7:8085 go-inventory:latest )

# Then run the Playwright specs:
ENDPOINT=http://192.168.252.7:9000 \
APP_BASE_JAVA=http://192.168.252.7:8080 \
APP_BASE_GO=http://192.168.252.7:8081 \
  npx playwright test
```

Artifacts: screenshots + traces under `playwright-report/`.

### 2. API pass (each app's native test harness)

JUnit5 (Java) and `go test` (Go) drive the same provisioning + assertions
through the SDK clients directly. No browser; faster; easier to debug.

```bash
# Java API pass
cd tests/e2e/java-orders
ENDPOINT=http://192.168.252.7:9000 APP_BASE=http://192.168.252.7:8080 \
  mvn -Dtest=ApiPassTest test

# Go API pass
cd tests/e2e/go-inventory
ENDPOINT=http://192.168.252.7:9000 APP_BASE=http://192.168.252.7:8081 \
  go test -v -run TestApiPass
```

Both passes converge on the same assertions:
- App `/health` returns `UP` with every backend probe `ok:true`
- `POST /orders` (or `/items`) creates a row, encrypts a field via KMS,
  publishes an event, enqueues a worker job, all in one round-trip
- The published event lands in the NATS inbox (cross-checked at
  `GET /__nats/inbox?prefix=<aws.eventbridge.|gcp.eventarc.>`)
- `GET /orders/{id}/receipt` (or `/items/{id}/image`) uploads real bytes
  through the storage layer (MinIO or fake-gcs)

## Why two passes

Each pass catches different failure modes:

| Failure | API pass catches | Console pass catches |
|---|---|---|
| SDK wire mismatch (e.g. RFC1123 dates) | ✅ | ✅ |
| Console SPA JS error | ❌ | ✅ |
| Console wizard field validation bug | ❌ | ✅ |
| Backend HTTP route 404 | ✅ | ✅ |
| App misconfiguration | ✅ (faster) | ✅ |
| Cross-tenant isolation breach | ✅ | ✅ |

A real-world deployment would gate releases on BOTH passes — the Console pass
proves the operator UX still works; the API pass proves the SDK contracts
still work. Run both in CI before merging changes to `server.py`.

## Related test scope

- `tests/conformance/run_conformance.py` — narrower per-service probes (Vault,
  NATS eventing, Cedar IAM, MinIO/DDB/ElasticMQ proxies). Run first to
  isolate failures.
- `tests/cli/{aws,gcp,azure}-cli-smoke.sh` — proves the real CLI binaries
  work against the simulator (smaller surface than the web apps).
- `tests/conformance/aws-sdk-{go,java}/` — focused SDK probes per provider,
  per language.

Each layer narrows the failure-isolation cone:
**unit ← conformance ← CLI smoke ← e2e web app**.
