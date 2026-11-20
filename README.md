# Release checks — v4.0.10

Generated 2026-11-20 05:19 UTC by [Release checks report](https://github.com/vyomi-cloud/appliance/actions/runs/44673537008) for tag `v4.0.10`.

| Package / check | Platform | Result |
|---|---|---|
| Offline console UI, Windows MSI, Windows E2E | — | n/a since 4.0 (headless: no offline console, no MSI) |
| DEB: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Ubuntu (GitHub) | ✅ passed |
| RPM: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Fedora 40 (GitHub) | ✅ passed |
| Homebrew: vyomi + vyomi-docker (install, vyomi commands, uninstall) | macOS (GitHub) | ✅ passed |
| CLI: aws / gcloud / az suites + CLI ↔ console both ways (84/84 checks passed) | Linux, release images | ✅ passed |
| Nano CLI: aws / gcloud / az through the tunnel + CLI ↔ console both ways (84/84 checks passed) | Chromium, release wasm bundle | ✅ passed |
| Startup: all services + UI status | Linux, release images | — not run |

## DEB

#### deb · `vyomi_4.0.10_all.deb` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi_4.0.10_all.deb | 5s |
| ✅ | package manager reports version 4.0.10 | found '4.0.10' |
| ✅ | bundled VERSION is 4.0.10 | /usr/share/vyomi/packaging/common/VERSION = 4.0.10 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.10 | exit 0; compose v4.0.10; ==> Vyomi 4.0.10 is the latest release. |
| ✅ | uninstall vyomi | Removing vyomi (4.0.10) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### deb · `vyomi-docker_4.0.10_all.deb` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker_4.0.10_all.deb | 3s |
| ✅ | package manager reports version 4.0.10 | found '4.0.10' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 0; vyomi (Docker substrate) doctor |
| ✅ | vyomi --version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.10 | exit 0; compose v4.0.10; ==> Vyomi 4.0.10 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v4.0.10 (SHA256-checked) | exit 0; cached compose v4.0.10 |
| ✅ | after update, vyomi runs the cached v4.0.10 |   compose   : v4.0.10 (/tmp/tmp.ftAvjr99ji/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Removing vyomi-docker (4.0.10) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## RPM

#### rpm · `vyomi-4.0.10-1.noarch.rpm` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-4.0.10-1.noarch.rpm | 3s |
| ✅ | package manager reports version 4.0.10 | found '4.0.10' |
| ✅ | bundled VERSION is 4.0.10 | /usr/lib/cloud-learn/VERSION = 4.0.10 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.10 | exit 0; compose v4.0.10; ==> Vyomi 4.0.10 is the latest release. |
| ✅ | uninstall vyomi | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### rpm · `vyomi-docker-4.0.10-1.noarch.rpm` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker-4.0.10-1.noarch.rpm | 1s |
| ✅ | package manager reports version 4.0.10 | found '4.0.10' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.10 | exit 0; compose v4.0.10; ==> Vyomi 4.0.10 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v4.0.10 (SHA256-checked) | exit 0; cached compose v4.0.10 |
| ✅ | after update, vyomi runs the cached v4.0.10 |   compose   : v4.0.10 (/tmp/tmp.YHH7uuGb5n/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## BREW

#### brew · `vyomi` — 18/18 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi | 10s |
| ✅ | package manager reports version 4.0.10 | found '4.0.10' |
| ✅ | bundled VERSION is 4.0.10 | /opt/homebrew/opt/vyomi/libexec/VERSION = 4.0.10 |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /opt/homebrew/Cellar/vyomi/4.0.10/libexec |
| ✅ | vyomi --version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.10 | exit 0; compose v4.0.10; ==> Vyomi 4.0.10 is the latest release. |
| ✅ | brew test vyomi | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi/4.0.10/bin/cloud-learn help 2>&1[0m |
| ✅ | uninstall vyomi | Uninstalling /opt/homebrew/Cellar/socat/1.8.1.3... (16 files, 1.1MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### brew · `vyomi-docker` — 20/20 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker | 6s |
| ✅ | package manager reports version 4.0.10 | found '4.0.10' |
| ✅ | ships docker-compose.cloudlite.yml | /opt/homebrew/opt/vyomi-docker/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 4.0.10 | exit 0; vyomi 4.0.10 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.10 | exit 0; compose v4.0.10; ==> Vyomi 4.0.10 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v4.0.10 (SHA256-checked) | exit 0; cached compose v4.0.10 |
| ✅ | after update, vyomi runs the cached v4.0.10 |   compose   : v4.0.10 (/var/folders/q2/p1t6rgxj5fj32g1dc7dmd49r0000gn/T/tmp.wTTST6Peu2/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | brew test vyomi-docker | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi-docker/4.0.10/bin/vyomi --help[0m |
| ✅ | uninstall vyomi-docker | Uninstalling /opt/homebrew/Cellar/vyomi-docker/4.0.10... (12 files, 31.9MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## CLI (aws / gcloud / az) and CLI ↔ console

**84/84 checks passed** against `http://localhost:9000`.

### CLIs (4/4)

| | Check | Detail |
|---|---|---|
| ✅ | aws installed |  |
| ✅ | gcloud installed |  |
| ✅ | az installed |  |
| ✅ | appliance backends ready (17/17) |  |

### Identity: CLI and console use the same account / project / subscription (3/3)

| | Check | Detail |
|---|---|---|
| ✅ | AWS: `aws sts get-caller-identity` account is the console's account |  |
| ✅ | GCP: `gcloud projects list` returns the console's project |  |
| ✅ | Azure: `az account list` (GET /subscriptions) returns the console's subscription |  |

### Both directions: CLI → console and console → CLI (44/44)

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
| ✅ | AWS: DynamoDB table created with the CLI shows in the console |  |
| ✅ | AWS: DynamoDB table created in the console |  |
| ✅ | AWS: DynamoDB table created in the console shows in the CLI |  |
| ✅ | AWS: SNS topic created with the CLI |  |
| ✅ | AWS: SNS topic created with the CLI shows in the console |  |
| ✅ | AWS: SNS topic created in the console |  |
| ✅ | AWS: SNS topic created in the console shows in the CLI |  |
| ✅ | AWS: Secrets Manager secret created with the CLI |  |
| ✅ | AWS: Secrets Manager secret created with the CLI shows in the console |  |
| ✅ | AWS: Secrets Manager secret created in the console |  |
| ✅ | AWS: Secrets Manager secret created in the console shows in the CLI |  |
| ✅ | GCP: Cloud Storage bucket created with the CLI |  |
| ✅ | GCP: Cloud Storage bucket created with the CLI shows in the console |  |
| ✅ | GCP: Cloud Storage bucket created in the console |  |
| ✅ | GCP: Cloud Storage bucket created in the console shows in the CLI |  |
| ✅ | GCP: Pub/Sub topic created with the CLI |  |
| ✅ | GCP: Pub/Sub topic created with the CLI shows in the console |  |
| ✅ | GCP: Pub/Sub topic created in the console |  |
| ✅ | GCP: Pub/Sub topic created in the console shows in the CLI |  |
| ✅ | GCP: Secret Manager secret created with the CLI |  |
| ✅ | GCP: Secret Manager secret created with the CLI shows in the console |  |
| ✅ | GCP: Secret Manager secret created in the console |  |
| ✅ | GCP: Secret Manager secret created in the console shows in the CLI |  |
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

### CLI suites, each on its own (33/33)

| | Check | Detail |
|---|---|---|
| ✅ | aws-apigatewayv2: 40 passed, 0 failed |  |
| ✅ | aws: 15 passed, 0 failed |  |
| ✅ | aws-cloudwatch: 31 passed, 0 failed |  |
| ✅ | aws-ec2-sg-description: 2 passed, 0 failed |  |
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
| ✅ | azure-defender-automation: 18 passed, 0 failed |  |
| ✅ | azure-dns: 24 passed, 0 failed |  |
| ✅ | azure-loganalytics-tools: 12 passed, 0 failed |  |
| ✅ | azure-monitor: 21 passed, 0 failed |  |
| ✅ | azure-netenforce: 8 passed, 0 failed |  |
| ✅ | azure-operationalinsights: 20 passed, 0 failed |  |
| ✅ | azure-packetcapture: 11 passed, 0 failed |  |
| ✅ | azure-rgtools: 7 passed, 0 failed |  |
| ✅ | azure-workbooks: 8 passed, 0 failed |  |
| ✅ | gcp-artifactregistry: 11 passed, 0 failed |  |
| ✅ | gcp: 6 passed, 0 failed |  |
| ✅ | gcp-cloudscheduler: 13 passed, 0 failed |  |
| ✅ | gcp-container: 14 passed, 0 failed |  |
| ✅ | gcp-iamcredentials: 9 passed, 0 failed |  |
| ✅ | gcp-monitoring: 15 passed, 0 failed |  |
| ✅ | gcp-redis: 20 passed, 0 failed |  |
| ✅ | gcp-scheduler-pubsub: 6 passed, 0 failed |  |
| ✅ | gcp-vertex: 21 passed, 0 failed |  |
| ✅ | gcp-wire-gaps: 21 passed, 0 failed |  |

### Released services with no CLI suite yet (36)

AWS API Gateway, AWS DynamoDB, AWS EC2, AWS EventBridge, AWS IAM, AWS KMS, AWS Lambda, AWS RDS, AWS S3, AWS SQS, AWS Secrets Manager, AWS VPC, AZURE API Management, AZURE Cosmos DB, AZURE Entra ID / RBAC, AZURE Event Grid topics, AZURE Function apps, AZURE Key vaults, AZURE Network Security Group, AZURE SQL servers, AZURE Service Bus, AZURE Storage accounts, AZURE Virtual Machines, AZURE Virtual networks, GCP API Gateway, GCP Cloud Functions, GCP Cloud KMS, GCP Cloud SQL, GCP Cloud Storage, GCP Compute Engine, GCP Eventarc, GCP Firestore, GCP IAM & Admin, GCP Pub/Sub, GCP Secret Manager, GCP VPC Network


## Nano CLI through the tunnel and CLI ↔ console

**84/84 checks passed** against Nano through the relay tunnel `http://127.0.0.1:8090`.

### CLIs (4/4)

| | Check | Detail |
|---|---|---|
| ✅ | aws installed |  |
| ✅ | gcloud installed |  |
| ✅ | az installed |  |
| ✅ | Nano tab registered with the relay tunnel |  |

### Identity: CLI and console use the same account / project / subscription (3/3)

| | Check | Detail |
|---|---|---|
| ✅ | AWS: `aws sts get-caller-identity` account is the console's account |  |
| ✅ | GCP: `gcloud projects list` returns the console's project |  |
| ✅ | Azure: `az account list` (GET /subscriptions) returns the console's subscription |  |

### Both directions: CLI → console and console → CLI (44/44)

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
| ✅ | AWS: DynamoDB table created with the CLI shows in the console |  |
| ✅ | AWS: DynamoDB table created in the console |  |
| ✅ | AWS: DynamoDB table created in the console shows in the CLI |  |
| ✅ | AWS: SNS topic created with the CLI |  |
| ✅ | AWS: SNS topic created with the CLI shows in the console |  |
| ✅ | AWS: SNS topic created in the console |  |
| ✅ | AWS: SNS topic created in the console shows in the CLI |  |
| ✅ | AWS: Secrets Manager secret created with the CLI |  |
| ✅ | AWS: Secrets Manager secret created with the CLI shows in the console |  |
| ✅ | AWS: Secrets Manager secret created in the console |  |
| ✅ | AWS: Secrets Manager secret created in the console shows in the CLI |  |
| ✅ | GCP: Cloud Storage bucket created with the CLI |  |
| ✅ | GCP: Cloud Storage bucket created with the CLI shows in the console |  |
| ✅ | GCP: Cloud Storage bucket created in the console |  |
| ✅ | GCP: Cloud Storage bucket created in the console shows in the CLI |  |
| ✅ | GCP: Pub/Sub topic created with the CLI |  |
| ✅ | GCP: Pub/Sub topic created with the CLI shows in the console |  |
| ✅ | GCP: Pub/Sub topic created in the console |  |
| ✅ | GCP: Pub/Sub topic created in the console shows in the CLI |  |
| ✅ | GCP: Secret Manager secret created with the CLI |  |
| ✅ | GCP: Secret Manager secret created with the CLI shows in the console |  |
| ✅ | GCP: Secret Manager secret created in the console |  |
| ✅ | GCP: Secret Manager secret created in the console shows in the CLI |  |
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

### CLI suites, each on its own (33/33)

| | Check | Detail |
|---|---|---|
| ✅ | aws-apigatewayv2: 40 passed, 0 failed |  |
| ✅ | aws: 15 passed, 0 failed |  |
| ✅ | aws-cloudwatch: 31 passed, 0 failed |  |
| ✅ | aws-ec2-sg-description: 2 passed, 0 failed |  |
| ✅ | aws-elbv2: 27 passed, 0 failed |  |
| ✅ | aws-kinesis: 20 passed, 0 failed |  |
| ✅ | aws-logs: 19 passed, 0 failed |  |
| ✅ | aws-sns: 60 passed, 0 failed |  |
| ✅ | aws-ssm: 34 passed, 0 failed |  |
| ✅ | aws-stepfunctions: 26 passed, 0 failed |  |
| ✅ | azure-app: 23 passed, 0 failed |  |
| ✅ | azure-appconfiguration: 32 passed, 0 failed |  |
| ✅ | azure: 6 passed, 0 failed |  |
| ✅ | azure-cognitiveservices: 20 passed, 0 failed |  |
| ✅ | azure-defender-automation: 18 passed, 0 failed |  |
| ✅ | azure-dns: 24 passed, 0 failed |  |
| ✅ | azure-loganalytics-tools: 12 passed, 0 failed |  |
| ✅ | azure-monitor: 21 passed, 0 failed |  |
| ✅ | azure-netenforce: 8 passed, 0 failed |  |
| ✅ | azure-operationalinsights: 20 passed, 0 failed |  |
| ✅ | azure-packetcapture: 11 passed, 0 failed |  |
| ✅ | azure-rgtools: 7 passed, 0 failed |  |
| ✅ | azure-workbooks: 8 passed, 0 failed |  |
| ✅ | gcp-artifactregistry: 11 passed, 0 failed |  |
| ✅ | gcp: 6 passed, 0 failed |  |
| ✅ | gcp-cloudscheduler: 13 passed, 0 failed |  |
| ✅ | gcp-container: 14 passed, 0 failed |  |
| ✅ | gcp-iamcredentials: 9 passed, 0 failed |  |
| ✅ | gcp-monitoring: 15 passed, 0 failed |  |
| ✅ | gcp-redis: 20 passed, 0 failed |  |
| ✅ | gcp-scheduler-pubsub: 6 passed, 0 failed |  |
| ✅ | gcp-vertex: 21 passed, 0 failed |  |
| ✅ | gcp-wire-gaps: 21 passed, 0 failed |  |

### Not applicable on this target (1) — not counted as passed

| Suite | Check | Why |
|---|---|---|
| aws-sns | HTTP/S endpoint delivery (confirmation POST, signed messages, retries, dead-letter queue) | Nano: a browser tab cannot push to HTTP endpoints |

### Released services with no CLI suite yet (36)

AWS API Gateway, AWS DynamoDB, AWS EC2, AWS EventBridge, AWS IAM, AWS KMS, AWS Lambda, AWS RDS, AWS S3, AWS SQS, AWS Secrets Manager, AWS VPC, AZURE API Management, AZURE Cosmos DB, AZURE Entra ID / RBAC, AZURE Event Grid topics, AZURE Function apps, AZURE Key vaults, AZURE Network Security Group, AZURE SQL servers, AZURE Service Bus, AZURE Storage accounts, AZURE Virtual Machines, AZURE Virtual networks, GCP API Gateway, GCP Cloud Functions, GCP Cloud KMS, GCP Cloud SQL, GCP Cloud Storage, GCP Compute Engine, GCP Eventarc, GCP Firestore, GCP IAM & Admin, GCP Pub/Sub, GCP Secret Manager, GCP VPC Network


## Console UI (Nano) — aws

❌ 36/37 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `nano-ui-aws-vpc-row` | 5 | 2 |


## Console UI (Nano) — azure

✅ 26/26 suites passed


## Console UI (Nano) — gcp

✅ 25/25 suites passed



## SDK checks (Python, Go, Java)

❌ SDK checks: 1474/1478 passed (99.7%)

Native-SDK conformance suites (the ones the hourly conformance agent runs) against the published release images, per cloud and language.

| Cloud | Python | Go | Java |
|---|---|---|---|
| aws | 156/158 | 353/354 | 338/339 |
| gcp | 5/5 | 153/153 | 95/95 |
| azure | 19/19 | 216/216 | 139/139 |

| Failing suite | Passed | Failed |
|---|---|---|
| `offline-sdk-python-aws` | 74 | 1 |
| `offline-sdk-java-aws-sns` | 72 | 1 |
| `offline-sdk-go-aws-sns` | 70 | 1 |
| `offline-sweepA-aws` | 13 | 1 |

<!-- sdk-pass-rate: passed=1474 total=1478 not_run=0 rate=99.7 -->

---
Project README: https://github.com/vyomi-cloud/appliance#readme
