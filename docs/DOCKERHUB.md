# vyomi/appliance

**Local multi-cloud simulator. Real SDKs, real CLIs, real backends — no network required.**

[![GitHub](https://img.shields.io/badge/source-github-blue)](https://github.com/cloudlearn/cloud-learn)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/cloudlearn/cloud-learn/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-readme-orange)](https://github.com/cloudlearn/cloud-learn/blob/main/README.md)

Vyomi gives you AWS, GCP, and Azure-like experiences on your laptop, with cloud-faithful APIs that work with the standard provider SDKs — `boto3`, `aws-sdk-java`, `google-cloud-*`, `azure-sdk-for-*` — and CLIs — `aws`, `gcloud`, `gsutil`, `bq`, `az`, `terraform`. Override the endpoint, point at `http://localhost:9000`, your existing code runs.

## Quick start

The simulator image is the FastAPI control plane. For a full local stack with the 8 real backend integrations (Vault, NATS, MinIO, Postgres, MySQL, DynamoDB Local, ElasticMQ, fake-gcs-server), use docker-compose.

### One-container quick try
```bash
docker run --rm -p 9000:9000 vyomi/appliance:1.0.0
# Open http://localhost:9000/pricing
```

This runs the simulator alone (no real backends). Many services will use in-memory state. For the full experience:

### Full stack via docker-compose
```bash
git clone https://github.com/cloudlearn/cloud-learn && cd cloud-learn
docker compose up -d
# Open http://localhost:9000/pricing
```

## Tags

| Tag | Source | When updated |
|---|---|---|
| `latest` | latest GA release | on every `v*.*.*` tag |
| `1.0.0` | specific version | once, immutable |
| `edge` | latest `main` commit | every push to main |
| `sha-<short>` | specific commit | every push to main |

Use a pinned version (`vyomi/appliance:1.0.0`) in production. `latest` is OK for dev/CI.

## Architectures

Built for `linux/amd64` and `linux/arm64`. Apple Silicon (M1/M2/M3) and AWS Graviton both supported natively (no QEMU emulation).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDLEARN_STATE_FILE` | `/data/cloudlearn_state.pkl` | Persisted state file (mount `/data` for durability) |
| `CLOUDLEARN_LICENSE_TIER` | `free` | Pre-seed a tier on first boot |
| `CLOUDLEARN_VAULT_URL` | `http://cloudlearn-vault:8200` | Real Vault sidecar (for KMS + Secrets) |
| `CLOUDLEARN_NATS_URL` | `nats://cloudlearn-nats:4222` | Real NATS broker (for eventing) |
| `CLOUDLEARN_MINIO_URL` | `http://cloudlearn-minio:9000` | Real MinIO (for S3 bytes) |
| `CLOUDLEARN_BUDGET_BYPASS` | _(unset)_ | Set `1` to disable host-budget enforcement |

Full env reference: [`.env.example`](https://github.com/cloudlearn/cloud-learn/blob/main/.env.example)

## What's inside

- Python 3.14 (slim base)
- Node.js 20+ (for Cloud Functions exec)
- ~150 MB compressed
- Multi-stage build (no compiler toolchain in final image)
- Health-check baked in (`/healthz`)

## Useful endpoints

After boot:
- http://localhost:9000/pricing — pick a tier
- http://localhost:9000/console/aws — AWS console
- http://localhost:9000/console/gcp — GCP console
- http://localhost:9000/console/azure — Azure console
- http://localhost:9000/api/runtime/tier — tier policy
- http://localhost:9000/api/runtime/backends — real backend health
- http://localhost:9000/docs — OpenAPI swagger

## Documentation

Full README, architecture docs, release notes:
https://github.com/cloudlearn/cloud-learn

## Support

- Issues: https://github.com/cloudlearn/cloud-learn/issues
- Enterprise: support@cloudlearn.io
