# vyomi/appliance

**Local multi-cloud simulator. Real SDKs, real CLIs, real backends — no network required.**

[![Source](https://img.shields.io/badge/source-github-blue)](https://github.com/vyomi-cloud/appliance)
[![License](https://img.shields.io/badge/license-BSL%201.1-orange)](https://github.com/vyomi-cloud/appliance/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-vyomi.cloud-purple)](https://vyomi.cloud/docs)
[![Pricing](https://img.shields.io/badge/pricing-Free%20%E2%80%94%20Enterprise-green)](https://vyomi.cloud/pricing)

Vyomi gives you AWS, GCP, and Azure-like experiences on your laptop, with cloud-faithful APIs that work with the standard provider SDKs — `boto3`, `aws-sdk-java`, `google-cloud-*`, `azure-sdk-for-*` — and CLIs — `aws`, `gcloud`, `gsutil`, `bq`, `az`, `terraform`. Override the endpoint, point at `http://localhost:9000`, your existing code runs.

## Quick start

The simulator image is the FastAPI control plane. For a full local stack with the 8 real backend integrations (Vault, NATS, MinIO, Postgres, MySQL, DynamoDB Local, ElasticMQ, fake-gcs-server), use docker-compose.

### One-container quick try
```bash
docker run --rm -p 9000:9000 vyomi/appliance:latest
# Open http://localhost:9000/pricing
```

This runs the simulator alone (no real backends). Many services will use in-memory state. For the full experience:

### Full stack via docker-compose
```bash
git clone https://github.com/vyomi-cloud/appliance && cd appliance
docker compose up -d
# Open http://localhost:9000/pricing
```

### Recommended: the Vyomi appliance launcher

For a hands-off install that provisions a Multipass VM, brings up the full backend stack, and gives you `https://vyomi.local/` with a trusted local cert:

```bash
brew install vyomi-cloud/tap/vyomi   # macOS
# or .deb / .rpm / scoop — see vyomi.cloud/install
vyomi up
```

## Tags

| Tag | Source | When updated |
|---|---|---|
| `latest` | latest GA release | on every `v*.*.*` tag (stable only — never pre-releases) |
| `2.0.6`, `2.0.5`, … | specific version | once, immutable |
| `edge` | manual workflow_dispatch from main | only when explicitly run |
| `sha-<short>` | specific commit | only on manual dispatch |

Use a pinned version (`vyomi/appliance:2.0.6`) in production. `latest` is OK for dev/CI.

Also published to GHCR at `ghcr.io/vyomi-cloud/appliance` if you prefer pulling from GitHub.

## Architectures

Built for `linux/amd64` and `linux/arm64`. Apple Silicon (M1/M2/M3/M4) and AWS Graviton both supported natively (no QEMU emulation).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDLEARN_STATE_FILE` | `/data/cloudlearn_state.pkl` | Persisted state file (mount `/data` for durability) |
| `CLOUDLEARN_LICENSE_TIER` | `free` | Pre-seed a tier on first boot |
| `CLOUDLEARN_VAULT_URL` | `http://cloudlearn-vault:8200` | Real Vault sidecar (for KMS + Secrets) |
| `CLOUDLEARN_NATS_URL` | `nats://cloudlearn-nats:4222` | Real NATS broker (for eventing) |
| `CLOUDLEARN_MINIO_URL` | `http://cloudlearn-minio:9000` | Real MinIO (for S3 bytes) |
| `CLOUDLEARN_BUDGET_BYPASS` | _(unset)_ | Set `1` to disable host-budget enforcement |
| `VYOMI_INSTALL_ID` | _(auto)_ | Pre-issued install id from the package-manager phone-home; the simulator adopts it so the install funnel stays continuous |

`CLOUDLEARN_*` env names are kept for backward compatibility from the pre-rebrand v1.x line; the `VYOMI_*` aliases work identically.

Full env reference: [`.env.example`](https://github.com/vyomi-cloud/appliance/blob/main/.env.example)

## What's inside

- Python 3.14 (slim base)
- Node.js 20+ (for Cloud Functions exec)
- ~150 MB compressed
- Multi-stage build (no compiler toolchain in final image)
- Non-root runtime user (`cloudlearn:cloudlearn`)
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

Full docs, architecture diagrams, conformance reports, release notes:
- **Docs**: https://vyomi.cloud/docs
- **Pricing**: https://vyomi.cloud/pricing
- **Source**: https://github.com/vyomi-cloud/appliance

## Support

- Issues & bug reports: https://github.com/vyomi-cloud/appliance/issues
- Discussions & feature requests: https://github.com/vyomi-cloud/appliance/discussions
- Enterprise enquiries: support@vyomi.cloud

## License

Business Source License 1.1 — free for development, evaluation, and most production use. See [LICENSE](https://github.com/vyomi-cloud/appliance/blob/main/LICENSE) for the change-date / change-license terms. Contact `support@vyomi.cloud` for commercial questions.
