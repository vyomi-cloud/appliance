# Vyomi

[![CI](https://github.com/cloudlearn/cloud-learn/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudlearn/cloud-learn/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](docs/RELEASE_NOTES_v1.0.md)

**Local-first multi-cloud simulator. Real SDKs, real CLIs, real backends — no network required.**

> Note: Vyomi is the customer-facing brand at [vyomi.cloud](https://vyomi.cloud). The codebase, the `cloud-learn` CLI, the Docker image (`cloudlearn/simulator`), and the GitHub repo stay named `cloudlearn` / `cloud-learn` so existing installs keep working.

Vyomi gives you AWS, GCP, and Azure-like experiences on your laptop, with cloud-faithful APIs that work with the standard `boto3`, `aws-sdk-java`, `google-cloud-*`, `azure-sdk-for-*`, plus the `aws` / `gcloud` / `gsutil` / `az` / `terraform` CLIs. Override the endpoint, point at `http://localhost:9000`, and your existing code runs.

## What's in v1.0

| Pillar | Status |
|---|---|
| **3 cloud providers** — AWS, GCP, Azure | ✅ 29 services total (9+9+11), real-backed where it matters |
| **8 real backend integrations** — Vault, NATS, MinIO, DynamoDB Local, ElasticMQ, Cedar, Postgres, MySQL | ✅ |
| **Standard SDKs work natively** — boto3, aws-sdk-java/go, google-cloud-*, azure-sdk-for-* | ✅ |
| **Standard CLIs work natively** — `aws`, `gcloud`, `gsutil`, `bq`, `az`, `terraform` | ✅ |
| **3 native cloud consoles** — `/console/aws`, `/console/gcp`, `/console/azure` | ✅ |
| **4-tier licensing** — Free (₹0) · Student (₹299/mo) · Developer (₹599/mo) · Enterprise (₹99/dev/mo, min 10) | ✅ |
| **Multi-tenant + cross-tenant RBAC** — viewer/operator/admin roles, per-tenant isolation | ✅ |
| **Terraform export + import** — round-trip your simulator state to real HCL | ✅ |
| **3 reference apps** — Java Spring Boot (AWS), Go+chi (GCP), Go+chi (Azure) | ✅ |
| **Enterprise extras** — SSO (OIDC), Helm chart + air-gapped install, audit sinks, custom domain, branding, notifications | ✅ |

See [`docs/RELEASE_NOTES_v1.0.md`](docs/RELEASE_NOTES_v1.0.md) for the full feature list.

## Quick start

### Homebrew (macOS / Linux)
```bash
brew install cloudlearn/tap/cloud-learn
cloud-learn up
```

### Docker Compose (development)
```bash
git clone https://github.com/cloudlearn/cloud-learn && cd cloud-learn
docker compose up -d
open http://localhost:9000/pricing
```

### From source
```bash
git clone https://github.com/cloudlearn/cloud-learn && cd cloud-learn
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
- **Free** — 10 service categories × 3 clouds (locks NoSQL + eventing). Up to 1 VM/DB, host-capped sizes. Community support.
- **Student** — All services on 1 primary cloud. 10 VMs, 5 DBs, full Terraform export, Cloud Shell.
- **Developer** — All 35 services × 3 clouds. Cedar IAM, per-resource cost simulation, CI integration, single-cloud Terraform deploy.
- **Enterprise** — Multi-cloud deploy, SSO, Helm + air-gap, custom domain, branding, audit sinks, cross-tenant RBAC, dedicated Slack.

Switch tiers any time via `POST /api/license/signup`.

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

MIT. See [`LICENSE`](LICENSE).
