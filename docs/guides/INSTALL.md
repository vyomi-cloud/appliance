# CloudLearn — Installation

Pick the path that matches your platform. Every path lands on the same
endpoint: `http://localhost:9000`.

## At a glance

| Platform | Install command | Boundary | Image source |
|---|---|---|---|
| **Docker (any OS)** | `docker compose up -d` | host containers | Docker Hub |
| **Docker (one-shot)** | `docker run -p 9000:9000 gansudkum/cloud-learn:1.0.0` | single container | Docker Hub |
| **macOS / Linux (Brew)** | `brew install cloudlearn/tap/cloud-learn && cloud-learn up` | Multipass VM | Homebrew + Docker Hub |
| **Ubuntu / Debian / Mint** | `sudo apt install cloud-learn && cloud-learn up` | Multipass VM | APT repo + Docker Hub |
| **Fedora / RHEL / CentOS** | `sudo dnf install cloud-learn && cloud-learn up` | Multipass VM | RPM repo + Docker Hub |
| **Ubuntu (Snap)** | `sudo snap install cloud-learn --classic` | Multipass VM | Snap Store |
| **Windows (winget)** | `winget install CloudLearn.CloudLearn` | Multipass VM | winget + Docker Hub |
| **Windows (Chocolatey)** | `choco install cloud-learn` | Multipass VM | Chocolatey + Docker Hub |
| **From source** | `git clone … && docker compose up -d` | host containers | local build |

## Docker — the fastest path

### One-shot try (no real backends; in-memory only)
```bash
docker run --rm -p 9000:9000 gansudkum/cloud-learn:1.0.0
open http://localhost:9000/pricing
```

Good for kicking the tires. Most services run with in-memory state since the
real backends (Vault, NATS, MinIO, Postgres, MySQL, DynamoDB Local, ElasticMQ,
Cedar) aren't started. For the full experience, use docker-compose:

### Full stack via docker-compose
```bash
git clone https://github.com/cloudlearn/cloud-learn && cd cloud-learn
docker compose up -d
open http://localhost:9000/pricing
```

13 containers come up: the simulator + 8 real backends + CloudSim backbone +
fake-gcs + supporting sidecars. First boot pulls ~600 MB of images. Subsequent
starts: ~30 seconds.

To customize ports / passwords, copy `.env.example` to `.env` and edit before
`docker compose up`.

### Stop
```bash
docker compose down              # stop containers (keep volumes)
docker compose down -v           # stop + drop all data (clean slate)
```

## Homebrew (macOS + Linux)

```bash
brew tap cloudlearn/tap
brew install cloud-learn
cloud-learn up
```

`cloud-learn up` provisions a Multipass VM appliance (4 CPUs, 8 GB RAM, 32 GB
disk by default) and runs the full docker-compose stack inside. Browser URL is
printed on success.

Stop:
```bash
cloud-learn down       # stop VM (keep state)
cloud-learn restart    # restart inside the same VM
cloud-learn status     # show VM + simulator status
cloud-learn doctor     # diagnostic
```

Prerequisites: `multipass` (auto-installed from Homebrew cask if missing).

## APT — Debian / Ubuntu / Mint

```bash
# Add the apt repo
curl -fsSL https://apt.cloudlearn.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloudlearn.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudlearn.gpg] https://apt.cloudlearn.io stable main" \
  | sudo tee /etc/apt/sources.list.d/cloudlearn.list

sudo apt update
sudo apt install cloud-learn
cloud-learn up
```

Or grab the `.deb` directly from the GitHub Release page and `sudo dpkg -i`.

## RPM — Fedora / RHEL / CentOS / openSUSE

```bash
sudo dnf install https://github.com/cloudlearn/cloud-learn/releases/download/v1.0.0/cloud-learn-1.0.0-1.noarch.rpm
cloud-learn up
```

A proper YUM/DNF repo is in the v1.1 roadmap.

## Snap — Ubuntu

```bash
sudo snap install cloud-learn --classic
cloud-learn up
```

Note: cloud-learn uses **classic confinement** because the launcher controls
Multipass + Docker on the host. The simulator stack itself runs sandboxed
inside the Multipass VM.

## Winget — Windows 10/11

```powershell
winget install CloudLearn.CloudLearn
cloud-learn up
```

Prerequisite: Multipass for Windows. `winget install Canonical.Multipass`.

## Chocolatey — Windows (traditional)

```powershell
choco install cloud-learn
cloud-learn up
```

## From source (development)

```bash
git clone https://github.com/cloudlearn/cloud-learn && cd cloud-learn
docker compose up -d
# Or run uvicorn directly without docker:
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 9000
```

This is the path for contributors. Tests live in `tests/`; conformance harness
at `tests/conformance/run_conformance.py`. See [`README.md`](../../README.md#contributing)
for the contributor guide.

## Production deployment

For Helm + Kubernetes + Vault prod-mode + backup procedures:
[`docs/PRODUCTION_DEPLOYMENT.md`](../PRODUCTION_DEPLOYMENT.md)

## Verify the install

```bash
curl http://localhost:9000/healthz                   # simulator alive
curl http://localhost:9000/api/runtime/tier          # current tier policy
curl http://localhost:9000/api/runtime/backends      # 8 backend health
open http://localhost:9000/pricing                   # pick a tier
open http://localhost:9000/console/aws               # AWS console
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `port 9000 already in use` | another service on 9000 | `CLOUDLEARN_SIMULATOR_PORT=9001 docker compose up` |
| `cloud-learn up` hangs at "waiting for simulator" | Multipass VM still booting (cold start) | wait 5-10 min on first run; subsequent boots ~30s |
| `docker compose pull` fails | rate-limited by Docker Hub anon pulls | `docker login` first |
| Vault keys disappear on restart | running dev-mode (default) | switch to prod mode: [`docs/PRODUCTION_DEPLOYMENT.md`](../PRODUCTION_DEPLOYMENT.md) |
| Brew install fails on "outdated formula" | tap cache stale | `brew update && brew install cloud-learn` |

More: `cloud-learn doctor` runs a 12-point diagnostic.
