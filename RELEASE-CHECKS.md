# Release checks — v3.0.11

Generated 2026-10-27 06:53 UTC by [Release checks report](https://github.com/vyomi-cloud/appliance/actions/runs/40462587087) for tag `v3.0.11`.

| Package / check | Platform | Result |
|---|---|---|
| DEB: cloud-learn + vyomi-docker | Ubuntu (GitHub) | ✅ passed |
| RPM: cloud-learn + vyomi-docker | Fedora 40 (GitHub) | ✅ passed |
| Homebrew: vyomi + vyomi-docker | macOS (GitHub) | ✅ passed |
| MSI: install, upgrade, uninstall (+ signing) | Windows (GitHub) | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/40462587105)) |
| Startup: all services + UI status | Linux, release images | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/40463591259)) |
| Windows E2E: MSI → vyomi up → services + UI | Windows laptop (private runner) | — not run |

## DEB

#### deb · `cloud-learn_3.0.11_all.deb` — 8/8 passed

| | Check | Detail |
|---|---|---|
| ✅ | install cloud-learn_3.0.11_all.deb | 7s |
| ✅ | package manager reports version 3.0.11 | found '3.0.11' |
| ✅ | bundled VERSION is 3.0.11 | /usr/share/vyomi/packaging/common/VERSION = 3.0.11 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; ██╗   ██╗██╗   ██╗ ██████╗ ███╗   ███╗██╗ |
| ✅ | vyomi doctor runs | exit 0; ██╗   ██╗██╗   ██╗ ██████╗ ███╗   ███╗██╗ |
| ✅ | uninstall cloud-learn | Removing cloud-learn (3.0.11) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### deb · `vyomi-docker_3.0.11_all.deb` — 8/8 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker_3.0.11_all.deb | 2s |
| ✅ | package manager reports version 3.0.11 | found '3.0.11' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 0; vyomi (Docker substrate) doctor |
| ✅ | uninstall vyomi-docker | Removing vyomi-docker (3.0.11) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## RPM

#### rpm · `cloud-learn-3.0.11-1.noarch.rpm` — 8/8 passed

| | Check | Detail |
|---|---|---|
| ✅ | install cloud-learn-3.0.11-1.noarch.rpm | 2s |
| ✅ | package manager reports version 3.0.11 | found '3.0.11' |
| ✅ | bundled VERSION is 3.0.11 | /usr/lib/cloud-learn/VERSION = 3.0.11 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; ██╗   ██╗██╗   ██╗ ██████╗ ███╗   ███╗██╗ |
| ✅ | vyomi doctor runs | exit 0; ██╗   ██╗██╗   ██╗ ██████╗ ███╗   ███╗██╗ |
| ✅ | uninstall cloud-learn | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### rpm · `vyomi-docker-3.0.11-1.noarch.rpm` — 8/8 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker-3.0.11-1.noarch.rpm | 1s |
| ✅ | package manager reports version 3.0.11 | found '3.0.11' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | uninstall vyomi-docker | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## BREW

#### brew · `vyomi` — 9/9 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi | 12s |
| ✅ | package manager reports version 3.0.11 | found '3.0.11' |
| ✅ | bundled VERSION is 3.0.11 | /opt/homebrew/opt/vyomi/libexec/VERSION = 3.0.11 |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; ██╗   ██╗██╗   ██╗ ██████╗ ███╗   ███╗██╗ |
| ✅ | vyomi doctor runs | exit 0; ██╗   ██╗██╗   ██╗ ██████╗ ███╗   ███╗██╗ |
| ✅ | brew test vyomi | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi/3.0.11/bin/cloud-learn help 2>&1[0m |
| ✅ | uninstall vyomi | Uninstalling /opt/homebrew/Cellar/socat/1.8.1.3... (16 files, 1.1MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### brew · `vyomi-docker` — 9/9 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker | 5s |
| ✅ | package manager reports version 3.0.11 | found '3.0.11' |
| ✅ | ships docker-compose.cloudlite.yml | /opt/homebrew/opt/vyomi-docker/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | brew test vyomi-docker | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi-docker/3.0.11/bin/vyomi --help[0m |
| ✅ | uninstall vyomi-docker | Uninstalling /opt/homebrew/Cellar/vyomi-docker/3.0.11... (8 files, 216KB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## Startup (all services + UI)

### Vyomi 3.0.11 startup — 26/26 checks passed

| | Check | Detail |
|---|---|---|
| ✅ | simulator answers /healthz | 7s |
| ✅ | readiness reports every service ready | 12/12 ready, 100% |
| ✅ | service Vyomi simulator ready | ready after 7s |
| ✅ | service PostgreSQL ready | ready after 7s |
| ✅ | service MySQL ready | ready after 57s |
| ✅ | service Vault (KMS / secrets) ready | ready after 37s |
| ✅ | service MinIO (S3) ready | ready after 27s |
| ✅ | service DynamoDB ready | ready after 37s |
| ✅ | service NATS (EventBridge) ready | ready after 27s |
| ✅ | service ElasticMQ (SQS) ready | ready after 27s |
| ✅ | service fake-gcs-server ready | ready after 7s |
| ✅ | service Pub/Sub emulator ready | ready after 52s |
| ✅ | service Firestore emulator ready | ready after 52s |
| ✅ | service CloudSim Plus ready | ready after 7s |
| ✅ | /clouds status banner says 'Appliance is Ready' | Appliance is Ready |
| ✅ | /clouds banner counts every service | — all 12 services running |
| ✅ | running version is 3.0.11 | reports 3.0.11 |
| ✅ | AWS console loads its service rail | 14 rail items |
| ✅ | AWS console has no page errors |  |
| ✅ | AWS console has no 5xx API calls |  |
| ✅ | GCP console loads its service rail | 12 rail items |
| ✅ | GCP console has no page errors |  |
| ✅ | GCP console has no 5xx API calls |  |
| ✅ | AZURE console loads its service rail | 15 rail items |
| ✅ | AZURE console has no page errors |  |
| ✅ | AZURE console has no 5xx API calls |  |

