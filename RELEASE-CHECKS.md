# Release checks — v4.0.0

Generated 2026-11-12 18:55 UTC by [Release checks report](https://github.com/vyomi-cloud/appliance/actions/runs/43256905260) for tag `v4.0.0`.

| Package / check | Platform | Result |
|---|---|---|
| DEB: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Ubuntu (GitHub) | ✅ passed |
| RPM: vyomi + vyomi-docker (install, vyomi commands, uninstall) | Fedora 40 (GitHub) | ✅ passed |
| Homebrew: vyomi + vyomi-docker (install, vyomi commands, uninstall) | macOS (GitHub) | ✅ passed |
| CLI: aws / gcloud / az suites + CLI ↔ console both ways (78/84 checks passed) | Linux, release images | ❌ failure |
| Nano CLI: aws / gcloud / az through the tunnel + CLI ↔ console both ways (79/84 checks passed) | Chromium, release wasm bundle | ❌ failure |
| MSI: install, upgrade, uninstall (+ signing) | Windows (GitHub) | ✅ passed ([run](https://github.com/vyomi-cloud/appliance/actions/runs/43256905286)) |
| Startup: all services + UI status | Linux, release images | ❌ null ([run](https://github.com/vyomi-cloud/appliance/actions/runs/null)) |
| Windows E2E: MSI → vyomi up → services + UI | Windows laptop (private runner) | — not run |

## DEB

#### deb · `vyomi_4.0.0_all.deb` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi_4.0.0_all.deb | 6s |
| ✅ | package manager reports version 4.0.0 | found '4.0.0' |
| ✅ | bundled VERSION is 4.0.0 | /usr/share/vyomi/packaging/common/VERSION = 4.0.0 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.0 | exit 0; compose v4.0.0; ==> Vyomi 4.0.0 is the latest release. |
| ✅ | uninstall vyomi | Removing vyomi (4.0.0) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### deb · `vyomi-docker_4.0.0_all.deb` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker_4.0.0_all.deb | 2s |
| ✅ | package manager reports version 4.0.0 | found '4.0.0' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 0; vyomi (Docker substrate) doctor |
| ✅ | vyomi --version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.0 | exit 0; compose v4.0.0; ==> Vyomi 4.0.0 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v4.0.0 (SHA256-checked) | exit 0; cached compose v4.0.0 |
| ✅ | after update, vyomi runs the cached v4.0.0 |   compose   : v4.0.0 (/tmp/tmp.25LT402755/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Removing vyomi-docker (4.0.0) ... |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## RPM

#### rpm · `vyomi-4.0.0-1.noarch.rpm` — 17/17 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-4.0.0-1.noarch.rpm | 2s |
| ✅ | package manager reports version 4.0.0 | found '4.0.0' |
| ✅ | bundled VERSION is 4.0.0 | /usr/lib/cloud-learn/VERSION = 4.0.0 |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /usr/lib/cloud-learn |
| ✅ | vyomi --version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.0 | exit 0; compose v4.0.0; ==> Vyomi 4.0.0 is the latest release. |
| ✅ | uninstall vyomi | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### rpm · `vyomi-docker-4.0.0-1.noarch.rpm` — 19/19 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker-4.0.0-1.noarch.rpm | 1s |
| ✅ | package manager reports version 4.0.0 | found '4.0.0' |
| ✅ | ships docker-compose.cloudlite.yml | /usr/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /usr/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.0 | exit 0; compose v4.0.0; ==> Vyomi 4.0.0 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v4.0.0 (SHA256-checked) | exit 0; cached compose v4.0.0 |
| ✅ | after update, vyomi runs the cached v4.0.0 |   compose   : v4.0.0 (/tmp/tmp.HCgp6CT2hY/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | uninstall vyomi-docker | Complete! |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## BREW

#### brew · `vyomi` — 18/18 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi | 8s |
| ✅ | package manager reports version 4.0.0 | found '4.0.0' |
| ✅ | bundled VERSION is 4.0.0 | /opt/homebrew/opt/vyomi/libexec/VERSION = 4.0.0 |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi — Vyomi simulator launcher (Max tier: local multi-cloud appliance) |
| ✅ | vyomi doctor runs | exit 0; cloud-learn root: /opt/homebrew/Cellar/vyomi/4.0.0/libexec |
| ✅ | vyomi --version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi -V reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi · docker substrate) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.0 | exit 0; compose v4.0.0; ==> Vyomi 4.0.0 is the latest release. |
| ✅ | brew test vyomi | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi/4.0.0/bin/cloud-learn help 2>&1[0m |
| ✅ | uninstall vyomi | Uninstalling /opt/homebrew/Cellar/socat/1.8.1.3... (16 files, 1.1MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |

#### brew · `vyomi-docker` — 20/20 passed

| | Check | Detail |
|---|---|---|
| ✅ | install vyomi-docker | 3s |
| ✅ | package manager reports version 4.0.0 | found '4.0.0' |
| ✅ | ships docker-compose.cloudlite.yml | /opt/homebrew/opt/vyomi-docker/share/vyomi-docker/docker-compose.cloudlite.yml |
| ✅ | 'vyomi' on PATH | /opt/homebrew/bin/vyomi |
| ✅ | vyomi help runs | exit 0; vyomi (Docker substrate) — Free/Lite/Pro tiers |
| ✅ | vyomi doctor runs | exit 1; vyomi: Docker is required but was not found on PATH. |
| ✅ | vyomi --version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi version reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi -V reports 4.0.0 | exit 0; vyomi 4.0.0 (vyomi-docker · Free/Lite/Pro) |
| ✅ | vyomi --version shows the simulator state |   simulator : not running |
| ✅ | vyomi help lists update + version |  |
| ✅ | vyomi status → docker compose ps | exit 0 |
| ✅ | vyomi logs → docker compose logs | exit 0 |
| ✅ | vyomi down → docker compose down | exit 0 |
| ✅ | vyomi update → latest release v4.0.0 | exit 0; compose v4.0.0; ==> Vyomi 4.0.0 is the latest release. |
| ✅ | vyomi update from v3.0.0 → v4.0.0 (SHA256-checked) | exit 0; cached compose v4.0.0 |
| ✅ | after update, vyomi runs the cached v4.0.0 |   compose   : v4.0.0 (/var/folders/h5/t85nd63d71x27_8gl5gw3l_w0000gn/T/tmp.UCsAWgEPAV/home/.vyomi/docker-compose.cloudlite.yml) |
| ✅ | brew test vyomi-docker | [34m==>[0m [1m/opt/homebrew/Cellar/vyomi-docker/4.0.0/bin/vyomi --help[0m |
| ✅ | uninstall vyomi-docker | Uninstalling /opt/homebrew/Cellar/vyomi-docker/4.0.0... (12 files, 27.6MB) |
| ✅ | uninstall leaves no package and no 'vyomi' on PATH | package entries: 0; vyomi: none |


## CLI (aws / gcloud / az) and CLI ↔ console

**78/84 checks passed** against `http://localhost:9000`.

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

### Both directions: CLI → console and console → CLI (43/44)

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

### CLI suites, each on its own (28/33)

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
| ❌ | azure-defender-automation: 14 passed, 4 failed | Defender raises the storage alert; the automation ran for the alert; the alert is a SecurityAlert row in the workspace; Resource Graph query returns the topic |
| ✅ | azure-dns: 24 passed, 0 failed |  |
| ✅ | azure-loganalytics-tools: 12 passed, 0 failed |  |
| ✅ | azure-monitor: 21 passed, 0 failed |  |
| ❌ | azure-netenforce: 5 passed, 3 failed | Service Bus: other IP BLOCKED (201); Cosmos CORS preflight: unlisted origin BLOCKED (200); diagnostic setting delivered an OperationalLogs row to the workspace |
| ✅ | azure-operationalinsights: 20 passed, 0 failed |  |
| ✅ | azure-packetcapture: 11 passed, 0 failed |  |
| ❌ | azure-rgtools: 6 passed, 1 failed | Insights: 2 resources, 1 untagged, 1 VM |
| ❌ | azure-workbooks: 7 passed, 1 failed | render returns the KQL table (west 17, east 5) |
| ✅ | gcp-artifactregistry: 11 passed, 0 failed |  |
| ✅ | gcp: 6 passed, 0 failed |  |
| ✅ | gcp-cloudscheduler: 13 passed, 0 failed |  |
| ✅ | gcp-container: 14 passed, 0 failed |  |
| ✅ | gcp-iamcredentials: 9 passed, 0 failed |  |
| ✅ | gcp-monitoring: 15 passed, 0 failed |  |
| ✅ | gcp-redis: 20 passed, 0 failed |  |
| ✅ | gcp-scheduler-pubsub: 6 passed, 0 failed |  |
| ✅ | gcp-vertex: 21 passed, 0 failed |  |
| ❌ | gcp-wire-gaps: 1 passed, 20 failed | ets delete; dns managed-zones delete; functions deploy (gen2); functions list finds it; functions describe state ACTIVE; function URL runs the uploaded code (allow-unauthenticated honoured); functions delete; scc findings list; scc assets l |

### Released services with no CLI suite yet (36)

AWS API Gateway, AWS DynamoDB, AWS EC2, AWS EventBridge, AWS IAM, AWS KMS, AWS Lambda, AWS RDS, AWS S3, AWS SQS, AWS Secrets Manager, AWS VPC, AZURE API Management, AZURE Cosmos DB, AZURE Entra ID / RBAC, AZURE Event Grid topics, AZURE Function apps, AZURE Key vaults, AZURE Network Security Group, AZURE SQL servers, AZURE Service Bus, AZURE Storage accounts, AZURE Virtual Machines, AZURE Virtual networks, GCP API Gateway, GCP Cloud Functions, GCP Cloud KMS, GCP Cloud SQL, GCP Cloud Storage, GCP Compute Engine, GCP Eventarc, GCP Firestore, GCP IAM & Admin, GCP Pub/Sub, GCP Secret Manager, GCP VPC Network


## Nano CLI through the tunnel and CLI ↔ console

**79/84 checks passed** against Nano through the relay tunnel `http://127.0.0.1:8090`.

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

### CLI suites, each on its own (28/33)

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
| ❌ | azure-cognitiveservices: 18 passed, 2 failed | account usages list model quotas; location models list |
| ❌ | azure-defender-automation: 11 passed, 7 failed | an automation without scopes/sources/actions is rejected; list automations in the resource group; the automation ran for the alert; the alert is a SecurityAlert row in the workspace; DELETE automation; Resource Graph query returns the topic |
| ✅ | azure-dns: 24 passed, 0 failed |  |
| ✅ | azure-loganalytics-tools: 12 passed, 0 failed |  |
| ✅ | azure-monitor: 21 passed, 0 failed |  |
| ❌ | azure-netenforce: 6 passed, 2 failed | Cosmos CORS preflight: listed origin allowed (204); Cosmos CORS preflight: unlisted origin BLOCKED (204) |
| ✅ | azure-operationalinsights: 20 passed, 0 failed |  |
| ✅ | azure-packetcapture: 11 passed, 0 failed |  |
| ❌ | azure-rgtools: 6 passed, 1 failed | Insights: 2 resources, 1 untagged, 1 VM |
| ✅ | azure-workbooks: 8 passed, 0 failed |  |
| ✅ | gcp-artifactregistry: 11 passed, 0 failed |  |
| ✅ | gcp: 6 passed, 0 failed |  |
| ✅ | gcp-cloudscheduler: 13 passed, 0 failed |  |
| ❌ | gcp-container: 0 passed, 14 failed | ols list shows both pools; gcloud container clusters resize; resize persisted (3 nodes); gcloud container clusters update --update-labels; labels persisted; gcloud container operations list; gcloud container get-server-config; gcloud contai |
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


## Console UI (offline) — aws

❌ 5/19 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `offline-ui-aws-metrics` | 0 | 1 |
| `offline-ui-aws-ec2-detail-tabs` | 0 | 1 |
| `offline-ui-aws-real-tabs` | 0 | 1 |
| `offline-ui-aws-sqs-dlq-tab` | 0 | 1 |
| `offline-ui-aws-rds-connectivity-tabs` | 0 | 1 |
| `offline-ui-aws-vpc-details-tab` | 0 | 1 |
| `offline-ui-aws-vpc-sg-iam-cells` | 0 | 1 |
| `offline-ui-aws-detail-name` | 0 | 1 |
| `offline-ui-aws-apigw-tabs` | 0 | 1 |
| `offline-ui-aws-detail-tabs` | 0 | 1 |
| `offline-ui-sdk-roundtrip` | 1 | 1 |
| `offline-ui-console-home` | 3 | 3 |
| `offline-ui-drawer` | 0 | 1 |
| `offline-ui-default-cloud` | 0 | 1 |


## Console UI (offline) — azure

❌ 7/11 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `offline-ui-azure-metrics` | 1 | 1 |
| `offline-ui-azure-rg-nav` | 0 | 1 |
| `offline-ui-azure-resource-group-detail` | 0 | 1 |
| `offline-ui-azure-apim-appinsights` | 0 | 1 |


## Console UI (offline) — gcp

❌ 5/11 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `offline-ui-gcp-pubsub-subscriptions` | 0 | 1 |
| `offline-ui-gcp-activity-detail` | 0 | 1 |
| `offline-ui-gcp-grid-defaults` | 0 | 1 |
| `offline-ui-gcp-pubsub-grid` | 0 | 1 |
| `offline-ui-gcp-create-defaults` | 0 | 1 |
| `offline-ui-gcp-properties` | 0 | 1 |


## Console UI (Nano) — aws

❌ 35/37 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `nano-ui-default-cloud` | 4 | 1 |
| `nightly-aws-v4-roundtrip` | 89 | 1 |


## Console UI (Nano) — azure

❌ 24/26 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `nano-ui-crawl` | 33 | 1 |
| `nano-ui-azure-cognitiveservices` | 26 | 3 |


## Console UI (Nano) — gcp

❌ 23/25 suites passed

| Failing suite | Passed | Failed |
|---|---|---|
| `nano-ui-crawl` | 16 | 2 |
| `nano-ui-gcp-create-defaults` | 35 | 1 |


