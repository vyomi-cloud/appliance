# Vyomi — the Multi-Cloud Digital Twin Runtime

[![CI](https://github.com/vyomi-cloud/appliance/actions/workflows/ci.yml/badge.svg)](https://github.com/vyomi-cloud/appliance/actions/workflows/ci.yml)
[![License: BSL 1.1](https://img.shields.io/badge/license-BSL%201.1-orange.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.8-green.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/docker-vyomi%2Fappliance-blue.svg)](https://hub.docker.com/r/vyomi/appliance)

**Build for the cloud, without the cloud.** Vyomi is a **multi-cloud digital twin runtime** — a faithful, *running* replica of your AWS, GCP, and Azure environment on your own machine. Real services, real SDKs, real backends; no cloud account, no cloud bill, no network required.

> Often searched for as a *local multi-cloud simulator* or a *LocalStack alternative* — Vyomi goes further: a real digital twin on real backends across all three clouds, not single-cloud mocks.

Point your existing SDKs/CLIs — `boto3`, `aws-sdk-java`, `google-cloud-*`, `azure-sdk-for-*`, plus `aws` / `gcloud` / `gsutil` / `az` / `terraform` — at `http://localhost:9000`, and your code runs unchanged. When you're ready, one-click **Terraform export** promotes the same stack to production cloud.

### Why a digital twin, not a mock? (vs LocalStack / Moto / Azurite)

LocalStack mocks AWS; Moto, [Azurite](https://github.com/Azure/Azurite), and the GCP emulators each cover a single cloud. **Vyomi runs all three major clouds on real backends** (Postgres, MySQL, MinIO/S3, DynamoDB, Vault, NATS, Azurite, the Firestore emulator) with native **multi-cloud NoSQL** — DynamoDB, Firestore, and Cosmos DB — so the twin behaves like the real thing while you build and test cross-cloud apps locally. Full head-to-head: **[vyomi.cloud/compare/localstack](https://vyomi.cloud/compare/localstack)**.

> The CLI is `vyomi` (with a `cloud-learn` deprecation shim through v2.x), the Docker image is `vyomi/appliance`, and the brew tap is `vyomi-cloud/tap`. **Upgrading from v1.x?** Read [`docs/MIGRATION-v2.md`](docs/MIGRATION-v2.md) first.

## What's in v1.0

| Pillar | Status |
|---|---|
| **3 cloud providers** — AWS, GCP, Azure | ✅ 29 services total (9+9+11), real-backed where it matters |
| **8 real backend integrations** — Vault, NATS, MinIO, DynamoDB Local, ElasticMQ, Cedar, Postgres, MySQL | ✅ |
| **Standard SDKs work natively** — boto3, aws-sdk-java/go, google-cloud-*, azure-sdk-for-* | ✅ |
| **Standard CLIs work natively** — `aws`, `gcloud`, `gsutil`, `bq`, `az`, `terraform` | ✅ |
| **3 native cloud consoles** — `/console/aws`, `/console/gcp`, `/console/azure` | ✅ |
| **4-tier licensing** — Free (₹0) · Pro (₹299/mo) · Max (₹599/mo) · Enterprise (₹99/dev/mo, min 10) | ✅ |
| **Multi-tenant + cross-tenant RBAC** — viewer/operator/admin roles, per-tenant isolation | ✅ |
| **Terraform export + import** — round-trip your simulator state to real HCL | ✅ |
| **3 reference apps** — Java Spring Boot (AWS), Go+chi (GCP), Go+chi (Azure) | ✅ |
| **Enterprise extras** — SSO (OIDC), Helm chart + air-gapped install, audit sinks, custom domain, branding, notifications | ✅ |

See [`docs/RELEASE_NOTES_v1.0.md`](docs/RELEASE_NOTES_v1.0.md) for the full feature list.

## Quick start

### Homebrew (macOS / Linux)
```bash
brew install vyomi-cloud/tap/vyomi
vyomi up
```

### Docker Compose (development)
```bash
git clone https://github.com/vyomi-cloud/appliance && cd appliance
docker compose up -d
open http://localhost:9000/pricing
```

### From source
```bash
git clone https://github.com/vyomi-cloud/appliance && cd appliance
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 9000
```

First-time browsers land on `/pricing` to pick a tier. After that, the URL you actually want is one of:
- `/console/aws` · `/console/gcp` · `/console/azure` — native cloud consoles
- `/api/runtime/tier` — current tier policy
- `/api/runtime/backends` — health of all 8 real backends
- `/docs` — auto-generated OpenAPI swagger

## Using your existing cloud SDKs

```python
# Python (boto3) — AWS
import boto3
s3 = boto3.client("s3", endpoint_url="http://localhost:9000")
s3.create_bucket(Bucket="my-bucket")
s3.put_object(Bucket="my-bucket", Key="hello.txt", Body=b"world")
```

```java
// Java (aws-sdk-java-v2)
S3Client s3 = S3Client.builder()
    .endpointOverride(URI.create("http://localhost:9000"))
    .region(Region.US_EAST_1)
    .credentialsProvider(StaticCredentialsProvider.create(
        AwsBasicCredentials.create("test", "test")))
    .build();
```

```go
// Go (google-cloud-go)
client, _ := storage.NewClient(ctx,
    option.WithEndpoint("http://localhost:9000"),
    option.WithoutAuthentication())
bucket := client.Bucket("my-bucket")
```

```hcl
# Terraform
provider "aws" {
  endpoints {
    s3 = "http://localhost:9000"
  }
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  region = "us-east-1"
}
```

## Reference apps

Three minimal web apps that exercise each cloud's 7 core services through real SDKs:

| App | Cloud | Stack | Services exercised |
|---|---|---|---|
| [`tests/e2e/java-orders`](tests/e2e/java-orders) | **AWS** | Spring Boot, Java 17 | RDS · S3 · SQS · EventBridge · Secrets Mgr · KMS · IAM |
| [`tests/e2e/go-inventory`](tests/e2e/go-inventory) | **GCP** | Go + chi | Cloud SQL · GCS · Pub/Sub · Eventarc · Secret Mgr · Cloud KMS · IAM |
| [`tests/e2e/azure-tickets`](tests/e2e/azure-tickets) | **Azure** | Go + chi | Postgres Flex · Blob · Service Bus · Event Grid · KV-secrets · KV-keys · RBAC |

Each has its own `api_pass_test.go` / `ApiPassTest.java` that round-trips against a live simulator.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                            FastAPI (port 9000)                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                        │
│  │ /aws/* (S3)│ │ /v1/* (GCP)│ │ /sub/* (Az)│   ← provider routes    │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘                        │
│        │              │              │                                │
│  ┌─────┴──────────────┴──────────────┴────────┐                       │
│  │  Middleware: rate-limit → SSO → tier-gate │                       │
│  │             → Cedar → custom-domain       │                       │
│  └─────┬──────────────────────────────────┬──┘                       │
│        │                                  │                          │
│  ┌─────┴─────┐   ┌──────────────┐   ┌─────┴─────┐                    │
│  │  CloudSim │   │ tier_policy  │   │   state   │                    │
│  │  backbone │   │   (4 tiers)  │   │ (SQLite)  │                    │
│  └─────┬─────┘   └──────────────┘   └───────────┘                    │
└────────┼─────────────────────────────────────────────────────────────┘
         │
   ┌─────┴───────────────────────────────────────────────────────┐
   │                  Real backends (sidecar containers)          │
   │  Vault  NATS  MinIO  DDB-local  ElasticMQ  PG  MySQL  Cedar │
   └──────────────────────────────────────────────────────────────┘
```

Full design: [`docs/architecture/CLOUDLEARN_FULL_ARCHITECTURE.md`](docs/architecture/CLOUDLEARN_FULL_ARCHITECTURE.md)
Production deployment: [`docs/PRODUCTION_DEPLOYMENT.md`](docs/PRODUCTION_DEPLOYMENT.md)

## Tier system

`/pricing` shows the 4 tiers side-by-side; tier middleware enforces the gates server-side. Standard SDKs work natively on every tier (the "Standard capability" bar at the bottom of `/pricing`).

Tier escalation:
- **Free** (₹0/mo) — 10 service categories × 3 clouds (locks NoSQL + eventing). Tight quantity caps (1 of each resource per space). Community support.
- **Pro** (₹299/mo) — pick **one** primary cloud, all 12 services on it (other two visible but locked). 5 spaces, medium VM size, 10 GB storage, Cloud Shell, CloudSim Power model.
- **Max** (₹599/mo) — all 35 services × all 3 clouds. 25 spaces, large VM size, 100 GB storage, Cedar IAM enforcement, full CloudSim + cost simulation, CI integration.
- **Enterprise** (from ₹99/dev/mo, 10-dev min) — everything in Max plus multi-tenant, SSO, audit-log sinks, Helm + air-gapped install, custom domain, 24/7 support.

Switch tiers any time via `POST /api/license/signup`. *(Pro/Max were named Student/Developer before 2026-06-17; the old names still work as aliases.)*

## Conformance & testing

```bash
# Run the conformance harness against a live simulator
python tests/conformance/run_conformance.py \
  --endpoint http://localhost:9000 \
  --isolate-spaces \
  --fail-under 85.0
```

CI workflows in `.github/workflows/`:
- `ci.yml` — lint + conformance (≥85% gate) + tier-middleware smoke + 3-cloud refapp build matrix on every PR
- `release.yml` — tag-triggered release artifact build

## Contributing

- Adding a service: update the per-provider catalog + tier_policy category mapping. See `docs/architecture/CLOUDLEARN_LLD.md`.
- Adding a tier feature: extend `core/tier_policy.py` and add an `_enforce_tier_feature("X")` gate at the endpoint.
- Footguns + design decisions documented in [`docs/architecture/`](docs/architecture/).

## License

Source-available under the **Business Source License 1.1** with a Vyomi-specific Additional Use Grant. Auto-converts to Apache 2.0 four years after each release.

What this means in plain English:

- **You can:** read the source, use Vyomi non-commercially, run it internally at your company, audit the licensing/tier code, send pull requests
- **You can't (without a separate commercial agreement):** offer Vyomi as a hosted multi-cloud simulator service, modify/bypass the tier-enforcement code, or rebrand and resell it

See [`LICENSE`](LICENSE) for the full text. For commercial hosting, white-label, or OEM arrangements, contact licensing@vyomi.cloud.

