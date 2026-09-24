# Setup Vyomi — GitHub Action

Boot a local **multi-cloud digital twin** (AWS · GCP · Azure) in CI and run your
integration tests against it with **unmodified SDKs/CLIs** — no cloud account, no
bill, no live-cloud flakiness.

> Release 3.0 · Phase 1 — the **Cloud CI Testing** solution enabler. See
> `docs/ROADMAP-v3.md`. This action is a scaffold; publishing it to the GitHub
> Marketplace is tracked as an external step (needs the org + release).

## Usage

```yaml
jobs:
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Start Vyomi twin
        id: vyomi
        uses: ./.github/actions/setup-vyomi
        with:
          version: "2.2.2"   # or "latest"

      - name: Run tests against the twin
        env:
          AWS_ENDPOINT_URL: ${{ steps.vyomi.outputs.endpoint }}
          AWS_ACCESS_KEY_ID: test
          AWS_SECRET_ACCESS_KEY: test
          AWS_DEFAULT_REGION: us-east-1
        run: |
          # boto3 / aws-cli / google-cloud-* / azure-sdk-* all point at the twin
          python -m pytest tests/integration
```

## Inputs
| Input | Default | Description |
|---|---|---|
| `version` | `latest` | Appliance image tag |
| `port` | `9000` | Host port for the twin |
| `wait-timeout` | `120` | Seconds to wait for health |

## Outputs
| Output | Description |
|---|---|
| `endpoint` | Base URL of the twin (point SDKs/CLIs here) |

## Notes
- Uses the **ephemeral/CI profile**: the simulator boots fast; heavy backends
  (MinIO, Vault, DynamoDB, …) lazy-provision on first use.
- Health gate polls `GET /api/runtime/tier`.
- For a fully in-browser/no-Docker option, see Vyomi Nano (Free tier).
