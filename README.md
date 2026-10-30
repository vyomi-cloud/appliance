# Release checks — v3.0.33

Generated 2026-10-30 04:33 UTC by [Release checks report](https://github.com/vyomi-cloud/appliance/actions/runs/41003480646) for tag `v3.0.33`.

| Package / check | Platform | Result |
|---|---|---|
| DEB: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Ubuntu (GitHub) | ❌ cancelled |
| RPM: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Fedora 40 (GitHub) | ❌ cancelled |
| Homebrew: vyomi + vyomi-docker (install, vyomi commands, uninstall) | macOS (GitHub) | ❌ cancelled |
| CLI: aws / gcloud / az suites + CLI ↔ console both ways  | Linux, release images | ❌ cancelled |
| MSI: install, upgrade, uninstall (+ signing) | Windows (GitHub) | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/40934343357)) |
| Startup: all services + UI status | Linux, release images | ❌ failure ([run](https://github.com/vyomi-cloud/appliance/actions/runs/40935785259)) |
| Windows E2E: MSI → vyomi up → services + UI | Windows laptop (private runner) | ❌ failure |

## Startup (all services + UI)

### Vyomi 3.0.33 startup — 23/31 checks passed

| | Check | Detail |
|---|---|---|
| ✅ | simulator answers /healthz | 4s |
| ❌ | readiness reports every service ready | 12/17 ready, 91% |
| ✅ | service Vyomi simulator ready | ready after 4s |
| ✅ | service PostgreSQL ready | ready after 4s |
| ✅ | service MySQL ready | ready after 50s |
| ✅ | service Vault (KMS / secrets) ready | ready after 30s |
| ✅ | service MinIO (S3) ready | ready after 20s |
| ✅ | service DynamoDB ready | ready after 30s |
| ✅ | service NATS (EventBridge) ready | ready after 20s |
| ✅ | service ElasticMQ (SQS) ready | ready after 20s |
| ✅ | service fake-gcs-server ready | ready after 4s |
| ✅ | service Pub/Sub emulator ready | ready after 45s |
| ✅ | service Firestore emulator ready | ready after 45s |
| ✅ | service CloudSim Plus ready | ready after 4s |
| ❌ | service VictoriaMetrics (CloudWatch metrics) ready | status loading |
| ❌ | service Caddy gateway (API Gateway V2) ready | status loading |
| ❌ | service Valkey (Memorystore) ready | status loading |
| ❌ | service OCI registry (Artifact Registry) ready | status loading |
| ❌ | service Azurite (Blob / Queue) ready | status loading |
| ❌ | /clouds status banner says 'Appliance is Ready' | Appliance is getting ready |
| ❌ | /clouds banner counts every service | — 12/17 backends ready |
| ✅ | running version is 3.0.33 | reports 3.0.33 |
| ✅ | AWS console loads its service rail | 20 rail items |
| ✅ | AWS console has no page errors |  |
| ✅ | AWS console has no 5xx API calls |  |
| ✅ | GCP console loads its service rail | 18 rail items |
| ✅ | GCP console has no page errors |  |
| ✅ | GCP console has no 5xx API calls |  |
| ✅ | AZURE console loads its service rail | 21 rail items |
| ✅ | AZURE console has no page errors |  |
| ✅ | AZURE console has no 5xx API calls |  |

## Windows E2E

### Vyomi 3.0.8 startup — 26/26 checks passed

| | Check | Detail |
|---|---|---|
| ✅ | simulator answers /healthz | 4s |
| ✅ | readiness reports every service ready | 12/12 ready, 100% |
| ✅ | service Vyomi simulator ready | ready after 6s |
| ✅ | service PostgreSQL ready | ready after 6s |
| ✅ | service MySQL ready | ready after 356s |
| ✅ | service Vault (KMS / secrets) ready | ready after 7s |
| ✅ | service MinIO (S3) ready | ready after 7s |
| ✅ | service DynamoDB ready | ready after 7s |
| ✅ | service NATS (EventBridge) ready | ready after 7s |
| ✅ | service ElasticMQ (SQS) ready | ready after 7s |
| ✅ | service fake-gcs-server ready | ready after 7s |
| ✅ | service Pub/Sub emulator ready | ready after 7s |
| ✅ | service Firestore emulator ready | ready after 7s |
| ✅ | service CloudSim Plus ready | ready after 7s |
| ✅ | /clouds status banner says 'Appliance is Ready' | Appliance is Ready |
| ✅ | /clouds banner counts every service | — all 12 services running |
| ✅ | running version is 3.0.8 | reports 3.0.8 |
| ✅ | AWS console loads its service rail | 12 rail items |
| ✅ | AWS console has no page errors |  |
| ✅ | AWS console has no 5xx API calls |  |
| ✅ | GCP console loads its service rail | 12 rail items |
| ✅ | GCP console has no page errors |  |
| ✅ | GCP console has no 5xx API calls |  |
| ✅ | AZURE console loads its service rail | 15 rail items |
| ✅ | AZURE console has no page errors |  |
| ✅ | AZURE console has no 5xx API calls |  |


---
Project README: https://github.com/vyomi-cloud/appliance#readme
