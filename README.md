# Release checks — v3.0.34

Generated 2026-10-30 14:44 UTC by [Release checks report](https://github.com/vyomi-cloud/appliance/actions/runs/41073064095) for tag `v3.0.34`.

| Package / check | Platform | Result |
|---|---|---|
| DEB: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Ubuntu (GitHub) | ✅ passed |
| RPM: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Fedora 40 (GitHub) | ✅ passed |
| Homebrew: vyomi + vyomi-docker (install, vyomi commands, uninstall) | macOS (GitHub) | ✅ passed |
| CLI: aws / gcloud / az suites + CLI ↔ console both ways (60/74 checks passed) | Linux, release images | ❌ failure |
| MSI: install, upgrade, uninstall (+ signing) | Windows (GitHub) | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/41071795907)) |
| Startup: all services + UI status | Linux, release images | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/41073140511)) |
| Windows E2E: MSI → vyomi up → services + UI | Windows laptop (private runner) | — not run |

## DEB

#### deb · `vyomi_3.0.34_all.deb` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi_3.0.34_all.deb | 13s |
| ✅ | package manager reports version 3.0.34 | found '3.0.34' |
| ✅ | bundled VERSION is 3.0.34 | /usr/share/vyomi/packaging/common/VERSION = 3.0.34 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.34 | exit 0; compose v3.0.34; ==> Vyomi 3.0.34 is the latest release. |
| ✅ | uninstall vyomi | Removing vyomi (3.0.34) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### deb · `vyomi-docker_3.0.34_all.deb` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker_3.0.34_all.deb | 3s |
| ✅ | package manager reports version 3.0.34 | found '3.0.34' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 0; vyomi (Docker substrate) doctor |
| ✅ | vyomi --version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.34 | exit 0; compose v3.0.34; ==> Vyomi 3.0.34 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v3.0.34 (SHA256-checked) | exit 0; cached compose v3.0.34 |
| ✅ | after update, vyomi runs the cached v3.0.34 |   compose   : v3.0.34 (/tmp/tmp.1dy2AEq5pl/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Removing vyomi-docker (3.0.34) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## RPM

#### rpm · `vyomi-3.0.34-1.noarch.rpm` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-3.0.34-1.noarch.rpm | 1s |
| ✅ | package manager reports version 3.0.34 | found '3.0.34' |
| ✅ | bundled VERSION is 3.0.34 | /usr/lib/cloud-learn/VERSION = 3.0.34 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.34 | exit 0; compose v3.0.34; ==> Vyomi 3.0.34 is the latest release. |
| ✅ | uninstall vyomi | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### rpm · `vyomi-docker-3.0.34-1.noarch.rpm` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker-3.0.34-1.noarch.rpm | 1s |
| ✅ | package manager reports version 3.0.34 | found '3.0.34' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.34 | exit 0; compose v3.0.34; ==> Vyomi 3.0.34 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v3.0.34 (SHA256-checked) | exit 0; cached compose v3.0.34 |
| ✅ | after update, vyomi runs the cached v3.0.34 |   compose   : v3.0.34 (/tmp/tmp.d4u2XqyZmV/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## BREW

#### brew · `vyomi` — 18/18 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi | 11s |
| ✅ | package manager reports version 3.0.34 | found '3.0.34' |
| ✅ | bundled VERSION is 3.0.34 | /opt/homebrew/opt/vyomi/libexec/VERSION = 3.0.34 |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /opt/homebrew/Cellar/vyomi/3.0.34/libexec |
| ✅ | vyomi --version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.34 | exit 0; compose v3.0.34; ==> Vyomi 3.0.34 is the latest release. |
| ✅ | brew test vyomi | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi/3.0.34/bin/cloud-learn help 2>&1[0m |
| ✅ | uninstall vyomi | Uninstalling /opt/homebrew/Cellar/socat/1.8.1.3... (16 files, 1.1MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### brew · `vyomi-docker` — 20/20 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker | 3s |
| ✅ | package manager reports version 3.0.34 | found '3.0.34' |
| ✅ | ships docker-compose.cloudlite.yml | /opt/homebrew/opt/vyomi-docker/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 3.0.34 | exit 0; vyomi 3.0.34 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v3.0.34 | exit 0; compose v3.0.34; ==> Vyomi 3.0.34 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v3.0.34 (SHA256-checked) | exit 0; cached compose v3.0.34 |
| ✅ | after update, vyomi runs the cached v3.0.34 |   compose   : v3.0.34 (/var/folders/n6/hn37q6pj7sj_9dmqqc2113800000gn/T/tmp.PD9vl8JFlB/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | brew test vyomi-docker | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi-docker/3.0.34/bin/vyomi --help[0m |
| ✅ | uninstall vyomi-docker | Uninstalling /opt/homebrew/Cellar/vyomi-docker/3.0.34... (8 files, 321.1KB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## CLI (aws / gcloud / az) and CLI ↔ console

**60/74 checks passed** against `http://localhost:9000`.

### CLIs (4/4)

| | Check | Detail |
|---|---|---|
| ✅ | aws installed |  |
| ✅ | gcloud installed |  |
| ✅ | az installed |  |
| ✅ | appliance backends ready (17/17) |  |

### Identity: CLI and console use the same account / project / subscription (2/3)

| | Check | Detail |
|---|---|---|
| ✅ | AWS: `aws sts get-caller-identity` account is the console's account |  |
| ❌ | GCP: `gcloud projects list` returns the console's project | CLI=4: <?xml version="1.0" encoding="UTF-8"?><Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist.</Message><Resource>/v1</Resource><RequestId>E1609B21612141CF</RequestId></Error>  console=123456789012 |
| ✅ | Azure: `az account list` (GET /subscriptions) returns the console's subscription |  |

### Both directions: CLI → console and console → CLI (37/44)

| | Check | Detail |
|---|---|---|
| ✅ | AWS: S3 bucket created with the CLI |  |
| ✅ | AWS: S3 bucket created with the CLI shows in the console |  |
| ✅ | AWS: S3 bucket created in the console |  |
| ✅ | AWS: S3 bucket created in the console shows in the CLI |  |
| ✅ | AWS: SQS queue created with the CLI |  |
| ✅ | AWS: SQS queue created with the CLI shows in the console |  |
| ✅ | AWS: SQS queue created in the console |  |
| ✅ | AWS: SQS queue created in the console shows in the CLI |  |
| ✅ | AWS: DynamoDB table created with the CLI |  |
| ❌ | AWS: DynamoDB table created with the CLI shows in the console | console lists [] |
| ✅ | AWS: DynamoDB table created in the console |  |
| ✅ | AWS: DynamoDB table created in the console shows in the CLI |  |
| ✅ | AWS: SNS topic created with the CLI |  |
| ✅ | AWS: SNS topic created with the CLI shows in the console |  |
| ✅ | AWS: SNS topic created in the console |  |
| ✅ | AWS: SNS topic created in the console shows in the CLI |  |
| ✅ | AWS: Secrets Manager secret created with the CLI |  |
| ✅ | AWS: Secrets Manager secret created with the CLI shows in the console |  |
| ✅ | AWS: Secrets Manager secret created in the console |  |
| ❌ | AWS: Secrets Manager secret created in the console shows in the CLI | CLI lists [] |
| ✅ | GCP: Cloud Storage bucket created with the CLI |  |
| ❌ | GCP: Cloud Storage bucket created with the CLI shows in the console | console lists [] |
| ✅ | GCP: Cloud Storage bucket created in the console |  |
| ❌ | GCP: Cloud Storage bucket created in the console shows in the CLI | CLI lists ['cliclou3371067'] |
| ✅ | GCP: Pub/Sub topic created with the CLI |  |
| ❌ | GCP: Pub/Sub topic created with the CLI shows in the console | console lists [] |
| ✅ | GCP: Pub/Sub topic created in the console |  |
| ❌ | GCP: Pub/Sub topic created in the console shows in the CLI | CLI lists ['clipubs3371067', 'projects/gcp-dev/topics/clipubs3371067'] |
| ✅ | GCP: Secret Manager secret created with the CLI |  |
| ✅ | GCP: Secret Manager secret created with the CLI shows in the console |  |
| ✅ | GCP: Secret Manager secret created in the console |  |
| ❌ | GCP: Secret Manager secret created in the console shows in the CLI | CLI lists [] |
| ✅ | Azure: resource group created with the CLI |  |
| ✅ | Azure: resource group created with the CLI shows in the console |  |
| ✅ | Azure: resource group created in the console |  |
| ✅ | Azure: resource group created in the console shows in the CLI |  |
| ✅ | Azure: storage account created with the CLI |  |
| ✅ | Azure: storage account created with the CLI shows in the console |  |
| ✅ | Azure: storage account created in the console |  |
| ✅ | Azure: storage account created in the console shows in the CLI |  |
| ✅ | Azure: virtual network created with the CLI |  |
| ✅ | Azure: virtual network created with the CLI shows in the console |  |
| ✅ | Azure: virtual network created in the console |  |
| ✅ | Azure: virtual network created in the console shows in the CLI |  |

### CLI suites, each on its own (17/23)

| | Check | Detail |
|---|---|---|
| ✅ | aws-apigatewayv2: 40 passed, 0 failed |  |
| ✅ | aws: 15 passed, 0 failed |  |
| ✅ | aws-cloudwatch: 31 passed, 0 failed |  |
| ✅ | aws-elbv2: 27 passed, 0 failed |  |
| ✅ | aws-kinesis: 20 passed, 0 failed |  |
| ✅ | aws-logs: 19 passed, 0 failed |  |
| ✅ | aws-sns: 76 passed, 0 failed |  |
| ✅ | aws-ssm: 34 passed, 0 failed |  |
| ✅ | aws-stepfunctions: 26 passed, 0 failed |  |
| ✅ | azure-app: 23 passed, 0 failed |  |
| ✅ | azure-appconfiguration: 32 passed, 0 failed |  |
| ✅ | azure: 6 passed, 0 failed |  |
| ✅ | azure-cognitiveservices: 20 passed, 0 failed |  |
| ✅ | azure-dns: 24 passed, 0 failed |  |
| ✅ | azure-monitor: 21 passed, 0 failed |  |
| ✅ | azure-operationalinsights: 20 passed, 0 failed |  |
| ❌ | gcp-artifactregistry: 0 passed, 11 failed |  new repository; update description; describe shows the updated description; set-iam-policy; get-iam-policy returns the binding; docker images list (empty repository); gcloud artifacts repositories delete; describe after delete is NOT_FOUND |
| ✅ | gcp: 6 passed, 0 failed |  |
| ❌ | gcp-cloudscheduler: 1 passed, 12 failed | s update http; update persisted (schedule); gcloud scheduler jobs pause; job is PAUSED; gcloud scheduler jobs resume; gcloud scheduler jobs run; gcloud scheduler jobs create pubsub; gcloud scheduler jobs delete; deleted job is gone (NOT_FOU |
| ❌ | gcp-container: 2 passed, 12 failed | ols list shows both pools; gcloud container clusters resize; resize persisted (3 nodes); gcloud container clusters update --update-labels; labels persisted; gcloud container node-pools delete; gcloud container clusters delete; deleted clust |
| ❌ | gcp-iamcredentials: 1 passed, 8 failed | 0-hex key id; gcloud iam service-accounts sign-jwt; signed JWT has three dot-separated parts; JWT payload carries the claims; unknown service account is rejected (PERMISSION_DENIED); console log shows the signed blob + JWT issued by the CLI |
| ❌ | gcp-monitoring: 1 passed, 14 failed | nnel; gcloud alpha monitoring channels update; channel update persisted (displayName); gcloud alpha monitoring channel-descriptors list; gcloud monitoring policies create --policy-from-file; gcloud monitoring policies describe (name, compar |
| ❌ | gcp-redis: 2 passed, 18 failed | pdate --size; resize persisted (4 GB); gcloud redis instances update --update-labels --update-redis-config; labels and redis config persisted; gcloud redis instances create (standard HA, AUTH); standard tier has an alternative zone and repl |

### Released services with no CLI suite yet (36)

AWS API Gateway, AWS DynamoDB, AWS EC2, AWS EventBridge, AWS IAM, AWS KMS, AWS Lambda, AWS RDS, AWS S3, AWS SQS, AWS Secrets Manager, AWS VPC, AZURE API Management, AZURE Cosmos DB, AZURE Entra ID / RBAC, AZURE Event Grid topics, AZURE Function apps, AZURE Key vaults, AZURE Network Security Group, AZURE SQL servers, AZURE Service Bus, AZURE Storage accounts, AZURE Virtual Machines, AZURE Virtual networks, GCP API Gateway, GCP Cloud Functions, GCP Cloud KMS, GCP Cloud SQL, GCP Cloud Storage, GCP Compute Engine, GCP Eventarc, GCP Firestore, GCP IAM & Admin, GCP Pub/Sub, GCP Secret Manager, GCP VPC Network


## Startup (all services + UI)

### Vyomi 3.0.34 startup — 31/31 checks passed

| | Check | Detail |
|---|---|---|
| ✅ | simulator answers /healthz | 0s |
| ✅ | readiness reports every service ready | 17/17 ready, 100% |
| ✅ | service Vyomi simulator ready | ready after 1s |
| ✅ | service PostgreSQL ready | ready after 1s |
| ✅ | service MySQL ready | ready after 16s |
| ✅ | service Vault (KMS / secrets) ready | ready after 6s |
| ✅ | service MinIO (S3) ready | ready after 1s |
| ✅ | service DynamoDB ready | ready after 6s |
| ✅ | service NATS (EventBridge) ready | ready after 1s |
| ✅ | service ElasticMQ (SQS) ready | ready after 1s |
| ✅ | service fake-gcs-server ready | ready after 1s |
| ✅ | service Pub/Sub emulator ready | ready after 11s |
| ✅ | service Firestore emulator ready | ready after 11s |
| ✅ | service CloudSim Plus ready | ready after 1s |
| ✅ | service VictoriaMetrics (CloudWatch metrics) ready | ready after 1s |
| ✅ | service Caddy gateway (API Gateway V2) ready | ready after 1s |
| ✅ | service Valkey (Memorystore) ready | ready after 1s |
| ✅ | service OCI registry (Artifact Registry) ready | ready after 1s |
| ✅ | service Azurite (Blob / Queue) ready | ready after 6s |
| ✅ | /clouds status banner says 'Appliance is Ready' | Appliance is Ready |
| ✅ | /clouds banner counts every service | — all 17 services running |
| ✅ | running version is 3.0.34 | reports 3.0.34 |
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
