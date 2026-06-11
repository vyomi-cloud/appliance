# CloudLearn — Install

The fastest path is the one-liner. Everything else is a variation of it.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/sudhirkumarganti/cloud-learn/main/install.sh | bash
```

What happens, in order:

1. The script verifies you have Docker + Docker Compose v2 running.
2. Creates `~/.cloudlearn/` (no `sudo` needed).
3. Downloads `docker-compose.yml` + host config defaults.
4. Runs `docker compose up -d` — **4 services** start (~30 s):

   | Service | Image | Role |
   |---|---|---|
   | `simulator` | `gansudkum/cloud-learn:latest` | The AWS / GCP / Azure API surface |
   | `cloudsim` | locally-built | The Java CloudSim backbone |
   | `cloudlearn-sql-postgres` | `postgres:16-alpine` | SQL data plane |
   | `cloudlearn-gcs` | `fsouza/fake-gcs-server` | GCS data plane |

5. Opens **http://localhost:9000** in your browser.

Heavy backends (Vault, NATS, MinIO, DynamoDB-local, ElasticMQ, MySQL)
**don't get pulled** until you actually use a feature that needs them.
First S3 click → MinIO is fetched + started in the background, takes
~25 s with a progress banner. Subsequent clicks are instant.

## Variations

| Goal | Command |
|---|---|
| Eager-start all 10 services (skip lazy provisioning) | `curl -fsSL .../install.sh \| bash -s -- --full` |
| Pin a version (avoid `:latest` drift) | `curl -fsSL .../install.sh \| bash -s -- --tag v0.1.0` |
| Dry-run — see what it would do | `curl -fsSL .../install.sh \| bash -s -- --dry-run` |
| Use a fork | `curl -fsSL .../install.sh \| bash -s -- --repo https://raw.githubusercontent.com/me/cloud-learn/main` |

## Day-2 commands

After install, your compose context lives at `~/.cloudlearn/compose`. From there:

```bash
docker compose logs -f simulator       # tail logs
docker compose down                     # stop everything
docker compose pull && up -d            # upgrade to latest tag
docker compose --profile full up -d     # bring up the 6 lazy backends eagerly
```

## Lazy backend provisioning

A new install runs 4 services. The other 6 (MinIO, Vault, NATS,
DynamoDB-local, ElasticMQ, MySQL) provision **on first use**:

- Trigger via the UI (S3 click → MinIO, Secrets click → Vault, etc.) or directly:
  ```bash
  curl -X POST http://localhost:9000/api/runtime/backends/minio/provision
  ```
- Poll status:
  ```bash
  curl http://localhost:9000/api/runtime/backends/minio/status
  # → {"state":"pulling","pull_progress_pct":40, ...}
  ```
- Stop a running backend (frees RAM):
  ```bash
  curl -X POST http://localhost:9000/api/runtime/backends/minio/stop
  ```

Once provisioned, containers stay running until host restart. Persistent
volumes survive `docker compose down`.

## Manual install (without the script)

If you'd rather not pipe a script:

```bash
mkdir -p ~/.cloudlearn/{compose,deployments,config}
cd ~/.cloudlearn/compose

# 1. Get the compose file + host config
curl -O https://raw.githubusercontent.com/sudhirkumarganti/cloud-learn/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/sudhirkumarganti/cloud-learn/main/.cloudlearn-host.json
mkdir .cloudlearn-appliance
curl -o .cloudlearn-appliance/host-sizing-report.json \
  https://raw.githubusercontent.com/sudhirkumarganti/cloud-learn/main/.cloudlearn-appliance/host-sizing-report.json

# 2. Bring it up
docker compose up -d

# 3. Wait for healthy
until curl -fsS http://localhost:9000/healthz >/dev/null; do sleep 1; done
open http://localhost:9000           # or xdg-open on Linux
```

## Package-manager paths (Multipass-VM based)

These are the older, heavier paths. They use a Multipass / VirtualBox VM
under the hood and a wrapper CLI (`cloud-learn up`). Each one ultimately
fetches the same Docker images.

| Platform | Install command |
|---|---|
| macOS / Linux (Brew) | `brew install cloudlearn/tap/cloud-learn && cloud-learn up` |
| Ubuntu / Debian | `sudo apt install cloud-learn && cloud-learn up` |
| Fedora / RHEL | `sudo dnf install cloud-learn && cloud-learn up` |
| Ubuntu (Snap) | `sudo snap install cloud-learn --classic` |
| Windows (Scoop) | `scoop bucket add cloudlearn https://github.com/sudhirkumarganti/scoop-bucket && scoop install cloud-learn` |
| Windows (winget) | `winget install CloudLearn.CloudLearn` _(awaiting MSI)_ |

Use these if you need the Multipass-VM isolation. The `curl-bash` path
above is simpler if you already have Docker.

## From source

```bash
git clone https://github.com/sudhirkumarganti/cloud-learn.git
cd cloud-learn
sudo mkdir -p /var/lib/cloudlearn/deployments
docker compose up -d
```

Builds the simulator + CloudSim from local source. ~5–10 min first build,
near-instant on subsequent restarts.

## Uninstall

```bash
cd ~/.cloudlearn/compose
docker compose down -v          # -v removes the volumes (your simulated state)
rm -rf ~/.cloudlearn
docker image prune              # remove unused images
```

## What you get

A local appliance serving **AWS, GCP, Azure** API endpoints on `:9000`.
Real SDKs (`boto3`, `aws-cli`, `google-cloud-*`, `azure-sdk-*`, Terraform)
hit it natively. Tier policy enforced via license JWT from
`portal.cloudlearn.io`. See the dashboard for live status of each backend
and which service categories your tier unlocks.
