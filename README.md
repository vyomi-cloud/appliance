# Release checks — v3.0.31

Generated 2026-10-29 15:56 UTC by [Release checks report](https://github.com/vyomi-cloud/appliance/actions/runs/40904394002) for tag `v3.0.31`.

| Package / check | Platform | Result |
|---|---|---|
| DEB: cloud-learn + vyomi-docker (install, vyomi commands, uninstall) | Ubuntu (GitHub) | ✅ passed |
| RPM: cloud-learn + vyomi-docker (install, vyomi commands, uninstall) | Fedora 40 (GitHub) | ❌ failure |
| Homebrew: vyomi + vyomi-docker (install, vyomi commands, uninstall) | macOS (GitHub) | ❌ failure |
| MSI: install, upgrade, uninstall (+ signing) | Windows (GitHub) | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/40904394159)) |
| Startup: all services + UI status | Linux, release images | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/40906357113)) |
| Windows E2E: MSI → vyomi up → services + UI | Windows laptop (private runner) | — not run |

## DEB

#### deb · `cloud-learn_3.0.31_all.deb` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install cloud-learn_3.0.31_all.deb | 5s |
| ✅ | package manager reports version 3.0.31 | found '3.0.31' |
| ✅ | bundled VERSION is 3.0.31 | /usr/share/vyomi/packaging/common/VERSION = 3.0.31 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; Vyomi simulator launcher (cloud-learn CLI) — local multi-cloud appliance |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.31 | exit 0; compose v3.0.31; ==> Vyomi 3.0.31 is the latest release. |
| ✅ | uninstall cloud-learn | Removing cloud-learn (3.0.31) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### deb · `vyomi-docker_3.0.31_all.deb` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker_3.0.31_all.deb | 2s |
| ✅ | package manager reports version 3.0.31 | found '3.0.31' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 0; vyomi (Docker substrate) doctor |
| ✅ | vyomi --version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.31 | exit 0; compose v3.0.31; ==> Vyomi 3.0.31 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v3.0.31 (SHA256-checked) | exit 0; cached compose v3.0.31 |
| ✅ | after update, vyomi runs the cached v3.0.31 |   compose   : v3.0.31 (/tmp/tmp.yWK9ua0X7q/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Removing vyomi-docker (3.0.31) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## RPM

#### rpm · `cloud-learn-3.0.31-1.noarch.rpm` — 16/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install cloud-learn-3.0.31-1.noarch.rpm | 1s |
| ✅ | package manager reports version 3.0.31 | found '3.0.31' |
| ✅ | bundled VERSION is 3.0.31 | /usr/lib/cloud-learn/VERSION = 3.0.31 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; Vyomi simulator launcher (cloud-learn CLI) — local multi-cloud appliance |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ❌ | vyomi --version shows the simulator state |  |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.31 | exit 0; compose v3.0.31;  |
| ✅ | uninstall cloud-learn | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### rpm · `vyomi-docker-3.0.31-1.noarch.rpm` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker-3.0.31-1.noarch.rpm | 1s |
| ✅ | package manager reports version 3.0.31 | found '3.0.31' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.31 | exit 0; compose v3.0.31; ==> Vyomi 3.0.31 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v3.0.31 (SHA256-checked) | exit 0; cached compose v3.0.31 |
| ✅ | after update, vyomi runs the cached v3.0.31 |   compose   : v3.0.31 (/tmp/tmp.LhjaT05yMi/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## BREW

#### brew · `vyomi` — 17/18 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi | 7s |
| ✅ | package manager reports version 3.0.31 | found '3.0.31' |
| ✅ | bundled VERSION is 3.0.31 | /opt/homebrew/opt/vyomi/libexec/VERSION = 3.0.31 |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; Vyomi simulator launcher (cloud-learn CLI) — local multi-cloud appliance |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /opt/homebrew/Cellar/vyomi/3.0.31/libexec |
| ✅ | vyomi --version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.31 | exit 0; compose v3.0.31; ==> Vyomi 3.0.31 is the latest release. |
| ❌ | brew test vyomi | /opt/homebrew/Library/Homebrew/test.rb:55:in '<main>' |
| ✅ | uninstall vyomi | Uninstalling /opt/homebrew/Cellar/socat/1.8.1.3... (16 files, 1.1MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### brew · `vyomi-docker` — 20/20 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker | 3s |
| ✅ | package manager reports version 3.0.31 | found '3.0.31' |
| ✅ | ships docker-compose.cloudlite.yml | /opt/homebrew/opt/vyomi-docker/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 3.0.31 | exit 0; vyomi 3.0.31 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.31 | exit 0; compose v3.0.31; ==> Vyomi 3.0.31 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v3.0.31 (SHA256-checked) | exit 0; cached compose v3.0.31 |
| ✅ | after update, vyomi runs the cached v3.0.31 |   compose   : v3.0.31 (/var/folders/n6/hn37q6pj7sj_9dmqqc2113800000gn/T/tmp.wuwMn66mvq/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | brew test vyomi-docker | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi-docker/3.0.31/bin/vyomi --help[0m |
| ✅ | uninstall vyomi-docker | Uninstalling /opt/homebrew/Cellar/vyomi-docker/3.0.31... (8 files, 287.3KB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## Startup (all services + UI)

### Vyomi 3.0.31 startup — 26/26 checks passed

| | Check | Detail |
|---|---|---|
| ✅ | simulator answers /healthz | 7s |
| ✅ | readiness reports every service ready | 12/12 ready, 100% |
| ✅ | service Vyomi simulator ready | ready after 7s |
| ✅ | service PostgreSQL ready | ready after 7s |
| ✅ | service MySQL ready | ready after 42s |
| ✅ | service Vault (KMS / secrets) ready | ready after 17s |
| ✅ | service MinIO (S3) ready | ready after 12s |
| ✅ | service DynamoDB ready | ready after 27s |
| ✅ | service NATS (EventBridge) ready | ready after 17s |
| ✅ | service ElasticMQ (SQS) ready | ready after 17s |
| ✅ | service fake-gcs-server ready | ready after 7s |
| ✅ | service Pub/Sub emulator ready | ready after 42s |
| ✅ | service Firestore emulator ready | ready after 42s |
| ✅ | service CloudSim Plus ready | ready after 7s |
| ✅ | /clouds status banner says 'Appliance is Ready' | Appliance is Ready |
| ✅ | /clouds banner counts every service | — all 12 services running |
| ✅ | running version is 3.0.31 | reports 3.0.31 |
| ✅ | AWS console loads its service rail | 20 rail items |
| ✅ | AWS console has no page errors |  |
| ✅ | AWS console has no 5xx API calls |  |
| ✅ | GCP console loads its service rail | 18 rail items |
| ✅ | GCP console has no page errors |  |
| ✅ | GCP console has no 5xx API calls |  |
| ✅ | AZURE console loads its service rail | 21 rail items |
| ✅ | AZURE console has no page errors |  |
| ✅ | AZURE console has no 5xx API calls |  |


---
Project README: https://github.com/vyomi-cloud/appliance#readme
