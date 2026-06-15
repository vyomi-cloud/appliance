# Vyomi — Install

The fastest path is the one-liner. Everything else is a variation of it.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/vyomi-cloud/appliance/main/install.sh | bash
```

What happens, in order:

1. The script verifies you have Docker + Docker Compose v2 running.
2. Creates `~/.cloudlearn/` (no `sudo` needed).
3. Downloads `docker-compose.yml` + host config defaults.
4. Runs `docker compose up -d` — **4 services** start (~30 s):

   | Service | Image | Role |
   |---|---|---|
   | `simulator` | `vyomi/appliance:latest` | The AWS / GCP / Azure API surface |
   | `cloudsim` | locally-built | The Java CloudSim backbone |
   | `cloudlearn-sql-postgres` | `postgres:16-alpine` | SQL data plane |
   | `cloudlearn-gcs` | `fsouza/fake-gcs-server` | GCS data plane |

5. (Optional) Adds a one-time `127.0.0.1 vyomi.local` line to your `/etc/hosts`
   (sudo prompt) so the simulator is reachable at the same `vyomi.local`
   URL that the Multipass-based install paths publish. Idempotent — skipped
   if the line already exists.
6. Opens **http://vyomi.local:9000** in your browser (falls back to
   `http://localhost:9000` if you skipped step 5).

> **Why `vyomi.local`?** The Multipass-based install paths (Brew, .deb, .rpm,
> Scoop) publish the appliance VM at `vyomi.local` via mDNS so users don't
> have to memorise an IP that changes between runs. Docker Compose runs in
> your host Docker so it can't broadcast mDNS — but a single `/etc/hosts`
> entry (`127.0.0.1 vyomi.local`) maps the same hostname to localhost,
> so you can use the same URL across every install path.

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
docker compose logs -f simulator               # tail logs
docker compose down                             # stop everything
docker compose pull && docker compose up -d     # upgrade — Compose does NOT auto-pull on `up`
docker compose --profile full up -d             # bring up the 6 lazy backends eagerly
```

> **Why `pull` is explicit:** `docker compose up` only pulls when the image is missing locally. To force-check Docker Hub on every `up`, either run `docker compose pull` first OR pass `--pull always`. The default `.env.example` pins to a specific version (e.g. `vyomi/appliance:1.2.2`); set `CLOUDLEARN_SIMULATOR_IMAGE=vyomi/appliance:latest` for rolling updates.

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
curl -O https://raw.githubusercontent.com/vyomi-cloud/appliance/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/vyomi-cloud/appliance/main/.cloudlearn-host.json
mkdir .cloudlearn-appliance
curl -o .cloudlearn-appliance/host-sizing-report.json \
  https://raw.githubusercontent.com/vyomi-cloud/appliance/main/.cloudlearn-appliance/host-sizing-report.json

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
| Windows (Scoop) | `scoop bucket add cloudlearn https://github.com/vyomi-cloud/scoop-bucket && scoop install cloud-learn` |
| Windows (winget) | `winget install Vyomi.Vyomi` _(awaiting MSI)_ |

Use these if you need the Multipass-VM isolation. The `curl-bash` path
above is simpler if you already have Docker.

## From source

```bash
git clone https://github.com/vyomi-cloud/appliance.git
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
