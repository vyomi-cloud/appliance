# Vyomi service pipeline

Updated **2026-10-26 14:54 UTC** · **36 services released** (AWS 12 / GCP 12 / Azure 12) · **81 in the pipeline** (P1 + P2).

A new service goes live only when the service gate passes: engine, native SDK/CLI wire, console UI offline + Nano, Java + Go + CLI test beds, Playwright console tests offline + Nano, registered with the hourly conformance run and the upstream watcher. Then it is released (patch version) and handed off to both hourly jobs.

**Stages:** 📋 Queued → 🛠 Building → 🔍 In gate → 🚀 Releasing → 🟢 Released. Columns Engine…PW Nano are the gate's static checks on the service branch (⬜ = not checked yet). Hourly hand-off shows the latest hourly UI crawl (⚠️ n = open findings) and the service's own suites; upstream hand-off shows whether the watcher tracks the API and any open drift issues.

Links: [backlog](https://github.com/vyomi-cloud/appliance/issues?q=label%3Anew-service) · [expansion runs](https://github.com/vyomi-cloud/appliance/actions/workflows/expansion-agent.yml) · [usage-limit log](https://github.com/vyomi-cloud/appliance/tree/expansion-state) · [hourly conformance report](https://github.com/vyomi-cloud/appliance/tree/conformance-report) · [upstream watcher](https://github.com/vyomi-cloud/appliance/tree/upstream-state) · [full catalog](https://github.com/vyomi-cloud/appliance/blob/main/docs/expansion/CLOUD-CATALOG.md)

**Latest hourly run** (2026-10-26 13:05 UTC): `offline-ui-crawl` ❌ 5/38 · `offline-console-actions` ❌ 229/246 · `offline-sdk-python-aws` ❌ 81/86 · `offline-sdk-go-aws` ✅ 14/14 · `offline-sdk-go-gcp` ✅ 5/5 · `offline-sdk-go-azure` ✅ 14/14 · `offline-sdk-java-aws` ✅ 13/13 · `offline-sdk-java-gcp` ✅ 6/6 · `offline-sdk-java-azure` ✅ 5/5 · `offline-cost-savings` ❌ 2/9 · `offline-cli-aws` ✅ 15/15 · `offline-cli-gcp` ✅ 6/6 · `offline-cli-azure` ❌ 5/6 · `offline-ui-core` ✅ 9/9 · `nano-ui-crawl` ❌ 1/43 · `nano-cores` ❌ 0/1 · `nano-ui-aws-api` ❌ 5/6 · `nano-ui-aws-tabs` ✅ 11/11 · `nano-ui-gcp-tabs` ❌ 0/1 · `nano-ui-azure-tabs` ✅ 71/71 · `nano-ui-azure-dp` ✅ 5/5 · `nano-ui-azure-home` ✅ 7/7

## AWS — 12 released, 33 in the pipeline

Released: **12** · 📋 Queued: **15** · 🛠 Building: **1** · · Not filed: **17**

| Service | Pri | Stage | Engine | Nano | Console | Java | Go | CLI | PW offline | PW Nano | Gate | Release | Hourly conformance hand-off | Upstream watcher hand-off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **EC2** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 9 | 👁 watched (809 ops) |
| **S3** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 2 | 👁 watched (116 ops) |
| **IAM** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 2 | 👁 watched (180 ops) |
| **RDS** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 2 | 👁 watched (168 ops) |
| **DynamoDB** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 3 · UI nano ⚠️ 4 | 👁 watched (58 ops) |
| **SQS** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 2 | 👁 watched (23 ops) |
| **Lambda** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 2 | 👁 watched (88 ops) |
| **API Gateway** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 2 | 👁 watched (124 ops) |
| **VPC** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 2 | 👁 watched (809 ops) |
| **EventBridge** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 6 · UI nano ⚠️ 2 | 👁 watched (57 ops) |
| **Secrets Manager** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 8 · UI nano ⚠️ 6 | 👁 watched (23 ops) |
| **KMS** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 2 | 👁 watched (54 ops) |
| Amazon CloudWatch [#52](https://github.com/vyomi-cloud/appliance/issues/52) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon CloudWatch Logs [#59](https://github.com/vyomi-cloud/appliance/issues/59) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Cognito Identity Provider [#53](https://github.com/vyomi-cloud/appliance/issues/53) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon EC2 Container Service [#55](https://github.com/vyomi-cloud/appliance/issues/55) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Elastic Container Registry [#54](https://github.com/vyomi-cloud/appliance/issues/54) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon ElastiCache [#56](https://github.com/vyomi-cloud/appliance/issues/56) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Kinesis [#58](https://github.com/vyomi-cloud/appliance/issues/58) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Route 53 [#60](https://github.com/vyomi-cloud/appliance/issues/60) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Simple Email Service [#61](https://github.com/vyomi-cloud/appliance/issues/61) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Simple Notification Service [#62](https://github.com/vyomi-cloud/appliance/issues/62) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Simple Systems Manager (SSM) [#63](https://github.com/vyomi-cloud/appliance/issues/63) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AmazonApiGatewayV2 [#50](https://github.com/vyomi-cloud/appliance/issues/50) | P1 | 🛠 Building | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | no manifest yet | — | ⏳ after release | ⏳ registered at build |
| AWS CloudFormation [#51](https://github.com/vyomi-cloud/appliance/issues/51) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS Security Token Service [#65](https://github.com/vyomi-cloud/appliance/issues/65) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS Step Functions [#64](https://github.com/vyomi-cloud/appliance/issues/64) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Elastic Load Balancing [#57](https://github.com/vyomi-cloud/appliance/issues/57) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Athena | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Bedrock Runtime | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon DynamoDB Streams | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Elastic File System | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon EventBridge Scheduler | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Kinesis Firehose | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Amazon OpenSearch Service | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AmazonMQ | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Auto Scaling | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS AppSync | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS Backup | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS Batch | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS Certificate Manager | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS CodeBuild | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS Glue | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| AWS X-Ray | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Managed Streaming for Kafka | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |

## GCP — 12 released, 24 in the pipeline

Released: **12** · 📋 Queued: **12** · · Not filed: **12**

| Service | Pri | Stage | Engine | Nano | Console | Java | Go | CLI | PW offline | PW Nano | Gate | Release | Hourly conformance hand-off | Upstream watcher hand-off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Compute Engine** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 4 | 👁 watched (1018 ops) |
| **Cloud Storage** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 1 | 👁 watched (87 ops) |
| **Cloud SQL** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched (85 ops) |
| **Pub/Sub** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 5 · UI nano ⚠️ 7 | 👁 watched (46 ops) |
| **Firestore** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 3 · UI nano ⚠️ 7 | 👁 watched (60 ops) |
| **Cloud Functions** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 4 · UI nano ⚠️ 5 | 👁 watched (21 ops) |
| **API Gateway** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched (30 ops) |
| **VPC Network** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 4 · UI nano ⚠️ 7 | 👁 watched (1018 ops) |
| **IAM & Admin** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 1 | 👁 watched (137 ops) |
| **Eventarc** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 4 · UI nano ⚠️ 3 | 👁 watched (66 ops) |
| **Secret Manager** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched (36 ops) |
| **Cloud KMS** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 9 | 👁 watched (87 ops) |
| Artifact Registry API [#66](https://github.com/vyomi-cloud/appliance/issues/66) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| BigQuery API [#67](https://github.com/vyomi-cloud/appliance/issues/67) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud DNS API [#71](https://github.com/vyomi-cloud/appliance/issues/71) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Logging API [#73](https://github.com/vyomi-cloud/appliance/issues/73) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Monitoring API [#74](https://github.com/vyomi-cloud/appliance/issues/74) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Run Admin API [#76](https://github.com/vyomi-cloud/appliance/issues/76) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Scheduler API [#68](https://github.com/vyomi-cloud/appliance/issues/68) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Tasks API [#69](https://github.com/vyomi-cloud/appliance/issues/69) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Google Cloud Memorystore for Redis API [#75](https://github.com/vyomi-cloud/appliance/issues/75) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| IAM Service Account Credentials API [#72](https://github.com/vyomi-cloud/appliance/issues/72) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Kubernetes Engine API [#70](https://github.com/vyomi-cloud/appliance/issues/70) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Workflows API [#77](https://github.com/vyomi-cloud/appliance/issues/77) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Agent Platform API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Batch API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Certificate Manager API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Bigtable Admin API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Composer API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Dataproc API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Datastore API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Filestore API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Spanner API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Trace API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Translation API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| Dataflow API | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |

## Azure — 12 released, 24 in the pipeline

Released: **12** · 📋 Queued: **12** · · Not filed: **12**

| Service | Pri | Stage | Engine | Nano | Console | Java | Go | CLI | PW offline | PW Nano | Gate | Release | Hourly conformance hand-off | Upstream watcher hand-off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Virtual Machines** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Storage accounts** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **SQL servers** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Service Bus** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Cosmos DB** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Function apps** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **API Management** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Virtual networks** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Network Security Group** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Event Grid topics** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Key vaults** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Entra ID / RBAC** | — | 🟢 Released | — | — | — | — | — | — | — | — | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| app [#78](https://github.com/vyomi-cloud/appliance/issues/78) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| appconfiguration [#79](https://github.com/vyomi-cloud/appliance/issues/79) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| applicationinsights [#80](https://github.com/vyomi-cloud/appliance/issues/80) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| cognitiveservices [#81](https://github.com/vyomi-cloud/appliance/issues/81) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| containerregistry [#82](https://github.com/vyomi-cloud/appliance/issues/82) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| containerservice [#83](https://github.com/vyomi-cloud/appliance/issues/83) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| dns [#84](https://github.com/vyomi-cloud/appliance/issues/84) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| eventhub [#85](https://github.com/vyomi-cloud/appliance/issues/85) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| monitor [#86](https://github.com/vyomi-cloud/appliance/issues/86) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| msi [#87](https://github.com/vyomi-cloud/appliance/issues/87) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| operationalinsights [#88](https://github.com/vyomi-cloud/appliance/issues/88) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| redis [#89](https://github.com/vyomi-cloud/appliance/issues/89) | P1 | 📋 Queued | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| batch | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| cdn | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| datafactory | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| frontdoor | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| mysql | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| notificationhubs | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| postgresql | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| privatedns | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| search | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| servicefabric | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| signalr | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
| synapse | P2 | · Not filed | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | — | — | ⏳ after release | ⏳ registered at build |
