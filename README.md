# Vyomi service pipeline

_Updated 2026-10-27 13:08 UTC · refreshes after every pipeline run_

## At a glance

- **Released:** 44 services (AWS 16 · GCP 16 · Azure 12) of 1,068 the clouds publish
- **Building now:** nothing
- **In the gate / releasing:** Amazon CloudWatch (AWS), Amazon Cognito Identity Provider (AWS), Amazon EC2 Container Service (AWS), Amazon Elastic Container Registry (AWS), Amazon ElastiCache (AWS), Amazon Kinesis (AWS), Amazon Route 53 (AWS), Amazon Simple Email Service (AWS), Amazon Simple Notification Service (AWS), AmazonApiGatewayV2 (AWS), AWS CloudFormation (AWS), AWS Security Token Service (AWS), Artifact Registry API (GCP), BigQuery API (GCP), Cloud DNS API (GCP), Cloud Logging API (GCP), Cloud Monitoring API (GCP), Cloud Run Admin API (GCP), Cloud Tasks API (GCP)
- **Queued:** 54 services (P1 first, then P2)
- **Consoles really implemented:** offline 51% · Nano 66%
- **Hourly tests:** 66 of 69 suites passing (run 12:41 UTC)
- **Upstream watch:** 5 open changes from the real clouds to adopt

## By cloud

| Cloud | Released | Building | In gate | Queued | Console live (offline · Nano) |
|---|---|---|---|---|---|
| AWS | 16 | 0 | 12 | 17 | 43% · 68% |
| GCP | 16 | 0 | 7 | 13 | 42% · 62% |
| Azure | 12 | 0 | 0 | 24 | 68% · 70% |

## In progress

| Service | Cloud | Stage | Checks | Still missing |
|---|---|---|---|---|
| Amazon CloudWatch [#52](https://github.com/vyomi-cloud/appliance/issues/52) | AWS | 🔍 In gate ([PR #95](https://github.com/vyomi-cloud/appliance/pull/95)) | 18/18 | — |
| Amazon Cognito Identity Provider [#53](https://github.com/vyomi-cloud/appliance/issues/53) | AWS | 🔍 In gate ([PR #96](https://github.com/vyomi-cloud/appliance/pull/96)) | 18/18 | — |
| Amazon EC2 Container Service [#55](https://github.com/vyomi-cloud/appliance/issues/55) | AWS | 🔍 In gate ([PR #101](https://github.com/vyomi-cloud/appliance/pull/101)) | 19/19 | — |
| Amazon Elastic Container Registry [#54](https://github.com/vyomi-cloud/appliance/issues/54) | AWS | 🔍 In gate ([PR #100](https://github.com/vyomi-cloud/appliance/pull/100)) | 20/20 | — |
| Amazon ElastiCache [#56](https://github.com/vyomi-cloud/appliance/issues/56) | AWS | 🔍 In gate ([PR #102](https://github.com/vyomi-cloud/appliance/pull/102)) | 20/20 | — |
| Amazon Kinesis [#58](https://github.com/vyomi-cloud/appliance/issues/58) | AWS | 🔍 In gate ([PR #104](https://github.com/vyomi-cloud/appliance/pull/104)) | 18/18 | — |
| Amazon Route 53 [#60](https://github.com/vyomi-cloud/appliance/issues/60) | AWS | 🔍 In gate ([PR #106](https://github.com/vyomi-cloud/appliance/pull/106)) | 20/20 | — |
| Amazon Simple Email Service [#61](https://github.com/vyomi-cloud/appliance/issues/61) | AWS | 🔍 In gate ([PR #107](https://github.com/vyomi-cloud/appliance/pull/107)) | 18/18 | — |
| Amazon Simple Notification Service [#62](https://github.com/vyomi-cloud/appliance/issues/62) | AWS | 🔍 In gate ([PR #108](https://github.com/vyomi-cloud/appliance/pull/108)) | 18/18 | — |
| AmazonApiGatewayV2 [#50](https://github.com/vyomi-cloud/appliance/issues/50) | AWS | 🔍 In gate ([PR #91](https://github.com/vyomi-cloud/appliance/pull/91)) | 19/19 | — |
| AWS CloudFormation [#51](https://github.com/vyomi-cloud/appliance/issues/51) | AWS | 🔍 In gate ([PR #93](https://github.com/vyomi-cloud/appliance/pull/93)) | 20/20 | — |
| AWS Security Token Service [#65](https://github.com/vyomi-cloud/appliance/issues/65) | AWS | 🔍 In gate ([PR #112](https://github.com/vyomi-cloud/appliance/pull/112)) | 18/18 | — |
| Artifact Registry API [#66](https://github.com/vyomi-cloud/appliance/issues/66) | GCP | 🔍 In gate ([PR #114](https://github.com/vyomi-cloud/appliance/pull/114)) | 18/18 | — |
| BigQuery API [#67](https://github.com/vyomi-cloud/appliance/issues/67) | GCP | 🔍 In gate ([PR #115](https://github.com/vyomi-cloud/appliance/pull/115)) | 18/18 | — |
| Cloud DNS API [#71](https://github.com/vyomi-cloud/appliance/issues/71) | GCP | 🔍 In gate ([PR #120](https://github.com/vyomi-cloud/appliance/pull/120)) | 18/18 | — |
| Cloud Logging API [#73](https://github.com/vyomi-cloud/appliance/issues/73) | GCP | 🔍 In gate ([PR #122](https://github.com/vyomi-cloud/appliance/pull/122)) | 18/18 | — |
| Cloud Monitoring API [#74](https://github.com/vyomi-cloud/appliance/issues/74) | GCP | 🔍 In gate ([PR #123](https://github.com/vyomi-cloud/appliance/pull/123)) | 18/18 | — |
| Cloud Run Admin API [#76](https://github.com/vyomi-cloud/appliance/issues/76) | GCP | 🔍 In gate ([PR #125](https://github.com/vyomi-cloud/appliance/pull/125)) | 19/19 | — |
| Cloud Tasks API [#69](https://github.com/vyomi-cloud/appliance/issues/69) | GCP | 🔍 In gate ([PR #118](https://github.com/vyomi-cloud/appliance/pull/118)) | 18/18 | — |

## Released services

- **Console live:** parts of the console that are really implemented, offline · Nano
- **UI issues:** problems the latest hourly crawl found, offline · Nano

### AWS

| Service | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|
| EC2 | 🧩 6/13 · 🧩 6/13 | 0 · 0 | ✅ watched | before gate |
| S3 | 🧩 6/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| IAM | 🧩 7/11 · 🧩 3/11 | 0 · 0 | ✅ watched | before gate |
| RDS | 🧩 8/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| DynamoDB | 🧩 4/13 · 🧩 10/13 | 1 · 1 | ✅ watched | before gate |
| SQS | 🧩 5/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Lambda | 🧩 6/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| API Gateway | 🧩 6/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| VPC | 🧩 7/13 · 🧩 12/13 | 0 · 0 | ✅ watched | before gate |
| EventBridge | 🧩 3/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| Secrets Manager | 🧩 4/13 · 🧩 9/13 | 2 · 2 | ✅ watched | before gate |
| KMS | 🧩 5/13 · 🧩 11/13 | 0 · 0 | ⚠️ 3 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+kms) | before gate |
| CloudWatch Logs | — | – · – | ✅ watched | [v3.0.11](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.11) |
| Elastic Load Balancing | — | – · – | ✅ watched | [v3.0.10](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.10) |
| Systems Manager | — | – · – | ✅ watched | [v3.0.12](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.12) |
| Step Functions | — | – · – | ✅ watched | [v3.0.13](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.13) |

### GCP

| Service | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|
| Compute Engine | 🧩 5/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Storage | 🧩 7/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Cloud SQL | 🧩 4/13 · 🧩 8/13 | 0 · 0 | ⚠️ 2 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+sqladmin/v1beta4) | before gate |
| Pub/Sub | 🧩 6/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Firestore | 🧩 6/13 · 🧩 3/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Functions | 🧩 5/13 · 🧩 6/13 | 0 · 0 | ✅ watched | before gate |
| API Gateway | 🧩 5/12 · 🧩 9/12 | 0 · 0 | ✅ watched | before gate |
| VPC Network | 🧩 5/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| IAM & Admin | 🧩 4/9 · ✅ 9/9 | 0 · 0 | ✅ watched | before gate |
| Eventarc | 🧩 6/12 · 🧩 8/12 | 0 · 0 | ✅ watched | before gate |
| Secret Manager | 🧩 5/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Cloud KMS | 🧩 6/13 · 🧩 10/13 | 0 · 0 | ⚠️ 3 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+cloudkms/v1) | before gate |
| Cloud Scheduler | — | – · – | ✅ watched | [v3.0.14](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.14) |
| Kubernetes Engine | — | – · – | ✅ watched | [v3.0.15](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.15) |
| IAM Service Account Credentials | — | – · – | ✅ watched | [v3.0.16](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.16) |
| Memorystore for Redis | — | – · – | ✅ watched | [v3.0.17](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.17) |

### Azure

| Service | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|
| Virtual Machines | 🧩 10/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Storage accounts | 🧩 9/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| SQL servers | 🧩 8/13 · 🧩 7/13 | 0 · 0 | ✅ watched | before gate |
| Service Bus | 🧩 9/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Cosmos DB | 🧩 8/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Function apps | 🧩 7/13 · 🧩 7/13 | 0 · 0 | ✅ watched | before gate |
| API Management | 🧩 10/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| Virtual networks | 🧩 8/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Network Security Group | ✅ 3/3 · ✅ 3/3 | 0 · 0 | ✅ watched | before gate |
| Event Grid topics | 🧩 8/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Key vaults | 🧩 9/13 · 🧩 7/13 | 0 · 2 | ✅ watched | before gate |
| Entra ID / RBAC | 🧩 5/6 · 🧩 5/6 | 0 · 0 | ✅ watched | before gate |

- **Nano ↔ offline gaps:** Blob containers (Nano-only), Cosmos databases (Nano-only), Key Vault keys (Nano-only), Key Vault secrets (Nano-only), Storage queues (Nano-only), azure_subresource_core (Nano-only)

## Up next

<details><summary><b>AWS</b> — 17 queued</summary>

| Service | Priority | Issue | Offline backend |
|---|---|---|---|
| Amazon Athena | P2 | not filed | duckdb |
| Amazon Bedrock Runtime | P2 | not filed | ollama · 50 MB · Max |
| Amazon DynamoDB Streams | P2 | not filed | in-process |
| Amazon Elastic File System | P2 | not filed | in-process |
| Amazon EventBridge Scheduler | P2 | not filed | in-process |
| Amazon Kinesis Firehose | P2 | not filed | nats · 10 MB · Lite |
| Amazon OpenSearch Service | P2 | not filed | opensearch · 700 MB · Max |
| AmazonMQ | P2 | not filed | rabbitmq · 100 MB · Pro |
| Auto Scaling | P2 | not filed | in-process |
| AWS AppSync | P2 | not filed | in-process |
| AWS Backup | P2 | not filed | in-process |
| AWS Batch | P2 | not filed | docker · Pro |
| AWS Certificate Manager | P2 | not filed | in-process |
| AWS CodeBuild | P2 | not filed | docker · Pro |
| AWS Glue | P2 | not filed | duckdb |
| AWS X-Ray | P2 | not filed | in-process |
| Managed Streaming for Kafka | P2 | not filed | kafka · 400 MB · Max |

</details>

<details><summary><b>GCP</b> — 13 queued</summary>

| Service | Priority | Issue | Offline backend |
|---|---|---|---|
| Workflows API | P1 | [#77](https://github.com/vyomi-cloud/appliance/issues/77) | in-process |
| Agent Platform API | P2 | not filed | ollama · 50 MB · Max |
| Batch API | P2 | not filed | docker · Pro |
| Certificate Manager API | P2 | not filed | in-process |
| Cloud Bigtable Admin API | P2 | not filed | in-process |
| Cloud Composer API | P2 | not filed | in-process |
| Cloud Dataproc API | P2 | not filed | in-process |
| Cloud Datastore API | P2 | not filed | in-process |
| Cloud Filestore API | P2 | not filed | in-process |
| Cloud Spanner API | P2 | not filed | spanner-emulator · 150 MB · Pro |
| Cloud Trace API | P2 | not filed | in-process |
| Cloud Translation API | P2 | not filed | in-process |
| Dataflow API | P2 | not filed | in-process |

</details>

<details><summary><b>Azure</b> — 24 queued</summary>

| Service | Priority | Issue | Offline backend |
|---|---|---|---|
| app | P1 | [#78](https://github.com/vyomi-cloud/appliance/issues/78) | docker · Pro |
| appconfiguration | P1 | [#79](https://github.com/vyomi-cloud/appliance/issues/79) | in-process |
| applicationinsights | P1 | [#80](https://github.com/vyomi-cloud/appliance/issues/80) | in-process |
| cognitiveservices | P1 | [#81](https://github.com/vyomi-cloud/appliance/issues/81) | ollama · 50 MB · Max |
| containerregistry | P1 | [#82](https://github.com/vyomi-cloud/appliance/issues/82) | registry · 10 MB · Lite |
| containerservice | P1 | [#83](https://github.com/vyomi-cloud/appliance/issues/83) | k3s · 500 MB · Max |
| dns | P1 | [#84](https://github.com/vyomi-cloud/appliance/issues/84) | coredns · 15 MB · Lite |
| eventhub | P1 | [#85](https://github.com/vyomi-cloud/appliance/issues/85) | nats · 10 MB · Lite |
| monitor | P1 | [#86](https://github.com/vyomi-cloud/appliance/issues/86) | in-process |
| msi | P1 | [#87](https://github.com/vyomi-cloud/appliance/issues/87) | in-process |
| operationalinsights | P1 | [#88](https://github.com/vyomi-cloud/appliance/issues/88) | duckdb |
| redis | P1 | [#89](https://github.com/vyomi-cloud/appliance/issues/89) | valkey · 8 MB · Lite |
| batch | P2 | not filed | docker · Pro |
| cdn | P2 | not filed | caddy · 15 MB · Lite |
| datafactory | P2 | not filed | in-process |
| frontdoor | P2 | not filed | caddy · 15 MB · Lite |
| mysql | P2 | not filed | mariadb · 90 MB · Pro |
| notificationhubs | P2 | not filed | in-process |
| postgresql | P2 | not filed | postgres · 40 MB · Lite |
| privatedns | P2 | not filed | coredns · 15 MB · Lite |
| search | P2 | not filed | in-process |
| servicefabric | P2 | not filed | in-process |
| signalr | P2 | not filed | in-process |
| synapse | P2 | not filed | duckdb |

</details>

## Details

<details><summary>Gate checks — Amazon CloudWatch (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/cloudwatch_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/cloudwatch_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | cloudwatch |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Amazon Cognito Identity Provider (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/cognito_idp_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/cognito_idp_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | cognito-idp |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Amazon EC2 Container Service (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/ecs_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/ecs_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | ecs |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'substrate', 'name': 'docker', 'tier': 'pro'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: docker; chose docker |
| ✅ | substrate backends are Pro or Max only | tier=pro |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Amazon Elastic Container Registry (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/ecr_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/ecr_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | ecr |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'registry', 'image': 'registry:2.8.3', 'license': 'Apache-2.0', 'tier': 'lite', 'compose_service': 'vy |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: registry; chose registry |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=Apache-2.0 |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=Apache-2.0 |
| ✅ | backend image is pinned to a version (not latest) | registry:2.8.3 |

</details>

<details><summary>Gate checks — Amazon ElastiCache (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/elasticache_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/elasticache_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | elasticache |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'valkey', 'image': 'valkey/valkey:8.0.1-alpine', 'license': 'BSD-3-Clause', 'tier': 'lite', 'compose_s |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: valkey; chose valkey |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=BSD-3-Clause |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=BSD-3-Clause |
| ✅ | backend image is pinned to a version (not latest) | valkey/valkey:8.0.1-alpine |

</details>

<details><summary>Gate checks — Amazon Kinesis (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/kinesis_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/kinesis_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | kinesis |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'reason': 'Kinesis semantics (shards, hash-key routing, sequence numbers, iterators, resharding lineage) live |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: nats; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Amazon Route 53 (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/route53_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/route53_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | route53 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'coredns', 'image': 'coredns/coredns:1.11.3', 'license': 'Apache-2.0', 'tier': 'lite', 'compose_servic |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: coredns; chose coredns |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=Apache-2.0 |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=Apache-2.0 |
| ✅ | backend image is pinned to a version (not latest) | coredns/coredns:1.11.3 |

</details>

<details><summary>Gate checks — Amazon Simple Email Service (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/sesv2_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/sesv2_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | sesv2 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'reason': "SES v2 has no SMTP data plane in its API: SendEmail is validated and recorded by the engine and sh |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: mailpit; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Amazon Simple Notification Service (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/sns_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/sns_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | sns |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — AmazonApiGatewayV2 (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/apigatewayv2_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/apigatewayv2_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | apigatewayv2 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |
| ✅ | blank like the real console: Routes / Authorization | AWS shows - in the Authorization column for routes with no authorizer attached (authorizationType NONE) |

</details>

<details><summary>Gate checks — AWS CloudFormation (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/cloudformation_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/cloudformation_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | cloudformation |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |
| ✅ | blank like the real console: Events / Status reason | AWS console shows - for the Status reason of successful stack events |
| ✅ | blank like the real console: Outputs / Export name | AWS console shows - for an output that declares no Export |

</details>

<details><summary>Gate checks — AWS Security Token Service (AWS)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/sts_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/sts_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | aws-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | sts |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Artifact Registry API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_artifactregistry_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_artifactregistry_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | artifactregistry/v1 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'reason': "Control plane first: repositories, packages, versions, tags, files and docker images live in the e |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: registry; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — BigQuery API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_bigquery_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_bigquery_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | bigquery/v2 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'name': 'sqlite', 'reason': 'SQL runs on the stdlib sqlite3 engine inside the core (a GoogleSQL-to-SQLite tra |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: duckdb; chose sqlite |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Cloud DNS API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_dns_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_dns_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | dns/v1 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'reason': 'Zones, record sets and changes are control-plane state held by the engine (identical offline and i |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: coredns; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Cloud Logging API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_logging_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_logging_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | logging/v2 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Cloud Monitoring API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_monitoring_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_monitoring_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | monitoring/v3 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Cloud Run Admin API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_run_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_run_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | run/v2 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'substrate', 'name': 'docker', 'tier': 'pro'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: docker; chose docker |
| ✅ | substrate backends are Pro or Max only | tier=pro |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Cloud Tasks API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_cloudtasks_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_cloudtasks_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | gcp-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | cloudtasks/v2 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or the manifest says why not | recommended: in-process; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Console parts not live yet — AWS (136)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| EC2 | offline | tab: Tags | static |
| EC2 | offline | tab: Details | static |
| EC2 | offline | tab: Monitoring | static |
| EC2 | offline | tab: Networking | static |
| EC2 | offline | tab: Security | partial |
| EC2 | offline | tab: Storage | static |
| EC2 | offline | tab: Connect | static |
| Lambda | offline | tab: Tags | static |
| Lambda | offline | tab: Code | static |
| Lambda | offline | tab: Test | static |
| Lambda | offline | tab: Environment variables | static |
| Lambda | offline | tab: Versions | static |
| Lambda | offline | tab: Aliases | static |
| Lambda | offline | tab: Resource-based policy | static |
| S3 | offline | tab: Tags | static |
| S3 | offline | tab: Versions | static |
| S3 | offline | tab: Bucket Versioning | static |
| S3 | offline | tab: Event notifications | static |
| S3 | offline | tab: Lifecycle rules | static |
| S3 | offline | tab: Default encryption | static |
| S3 | offline | tab: Block Public Access | static |
| RDS | offline | tab: Tags | static |
| RDS | offline | tab: Endpoints | partial |
| RDS | offline | tab: Networking | partial |
| RDS | offline | tab: Permissions | static |
| RDS | offline | tab: Modify | static |
| DynamoDB | offline | create: create with defaults | partial |
| DynamoDB | offline | tab: Overview | static |
| DynamoDB | offline | tab: Tags | static |
| DynamoDB | offline | tab: Query/Scan | static |
| DynamoDB | offline | tab: Indexes | static |
| DynamoDB | offline | tab: Streams and triggers | static |
| DynamoDB | offline | tab: Read/write capacity | static |
| DynamoDB | offline | tab: Encryption at rest | static |
| DynamoDB | offline | tab: Time to live | static |
| SQS | offline | tab: Tags | static |
| SQS | offline | tab: Send and receive messages | static |
| SQS | offline | tab: Purge messages | static |
| SQS | offline | tab: Configuration | static |
| SQS | offline | tab: Dead-letter queue | static |
| SQS | offline | tab: Encryption | static |
| SQS | offline | tab: Access policy | static |
| SQS | offline | tab: Monitoring | static |
| API Gateway | offline | tab: Tags | static |
| API Gateway | offline | tab: Resources | unimplemented |
| API Gateway | offline | tab: Authorizers | static |
| API Gateway | offline | tab: Models | static |
| API Gateway | offline | tab: Stages | unimplemented |
| API Gateway | offline | tab: Deployments | static |
| API Gateway | offline | tab: Resource policy | static |
| EventBridge | offline | tab: Overview | partial |
| EventBridge | offline | tab: Activity | partial |
| EventBridge | offline | tab: Tags | partial |
| EventBridge | offline | tab: Rule details | partial |
| EventBridge | offline | tab: Targets | partial |
| EventBridge | offline | tab: Event pattern | partial |
| EventBridge | offline | tab: Invocations | partial |
| EventBridge | offline | tab: Dead-letter queue | partial |
| EventBridge | offline | tab: Properties | partial |
| EventBridge | offline | tab: Permissions | partial |
| VPC | offline | tab: VPC details | unimplemented |
| VPC | offline | tab: NAT gateways | static |
| VPC | offline | tab: Endpoints | static |
| VPC | offline | tab: Security groups | partial |
| VPC | offline | tab: Network ACLs | static |
| VPC | offline | tab: Flow logs | static |
| IAM | offline | tab: Users | partial |
| IAM | offline | tab: Identity providers | static |
| IAM | offline | tab: Password policy | static |
| IAM | offline | tab: Access Analyzer | static |
| Secrets Manager | offline | create: create with defaults | partial |
| Secrets Manager | offline | tab: Tags | static |
| Secrets Manager | offline | tab: Secret value | static |
| Secrets Manager | offline | tab: Versions | static |
| Secrets Manager | offline | tab: Rotation | static |
| Secrets Manager | offline | tab: Replication | static |
| Secrets Manager | offline | tab: Resource policy | static |
| Secrets Manager | offline | tab: Encryption key | static |
| Secrets Manager | offline | tab: Properties | static |
| KMS | offline | tab: Tags | static |
| KMS | offline | tab: General configuration | static |
| KMS | offline | tab: Key policy | static |
| KMS | offline | tab: Aliases | static |
| KMS | offline | tab: Key rotation | static |
| KMS | offline | tab: Key users | static |
| KMS | offline | tab: Key administrators | static |
| KMS | offline | tab: Grants | static |
| EC2 | nano | tab: Tags | static |
| EC2 | nano | tab: Details | static |
| EC2 | nano | tab: Monitoring | static |
| EC2 | nano | tab: Networking | static |
| EC2 | nano | tab: Security | partial |
| EC2 | nano | tab: Storage | static |
| EC2 | nano | tab: Connect | static |
| Lambda | nano | tab: Tags | static |
| Lambda | nano | tab: Code | static |
| Lambda | nano | tab: Test | static |
| S3 | nano | tab: Activity | partial |
| S3 | nano | tab: Tags | static |
| S3 | nano | tab: Bucket Versioning | static |
| S3 | nano | tab: Default encryption | unimplemented |
| S3 | nano | tab: Block Public Access | unimplemented |
| RDS | nano | tab: Activity | partial |
| RDS | nano | tab: Tags | static |
| RDS | nano | tab: Endpoints | partial |
| RDS | nano | tab: Networking | partial |
| RDS | nano | tab: Modify | unimplemented |
| DynamoDB | nano | create: create with defaults | partial |
| DynamoDB | nano | tab: Tags | static |
| DynamoDB | nano | tab: Query/Scan | static |
| SQS | nano | tab: Tags | static |
| SQS | nano | tab: Send and receive messages | static |
| SQS | nano | tab: Configuration | static |
| SQS | nano | tab: Dead-letter queue | static |
| SQS | nano | tab: Monitoring | static |
| API Gateway | nano | tab: Tags | static |
| API Gateway | nano | tab: Stages | partial |
| API Gateway | nano | tab: Settings | static |
| EventBridge | nano | tab: Tags | static |
| EventBridge | nano | tab: Rule details | static |
| EventBridge | nano | tab: Properties | static |
| VPC | nano | tab: VPC details | unimplemented |
| IAM | nano | tab: Overview | unimplemented |
| IAM | nano | tab: Users | unimplemented |
| IAM | nano | tab: User groups | unimplemented |
| IAM | nano | tab: Roles | unimplemented |
| IAM | nano | tab: Policies | unimplemented |
| IAM | nano | tab: Identity providers | unimplemented |
| IAM | nano | tab: Password policy | unimplemented |
| IAM | nano | tab: Access Analyzer | unimplemented |
| Secrets Manager | nano | create: create with defaults | partial |
| Secrets Manager | nano | tab: Tags | static |
| Secrets Manager | nano | tab: Secret value | static |
| Secrets Manager | nano | tab: Properties | static |
| KMS | nano | tab: Tags | static |
| KMS | nano | tab: General configuration | static |

</details>

<details><summary>Console parts not live yet — GCP (143)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| Compute Engine | offline | tab: Activity | static |
| Compute Engine | offline | tab: Permissions | static |
| Compute Engine | offline | tab: Labels | static |
| Compute Engine | offline | tab: Networking | static |
| Compute Engine | offline | tab: Disks | static |
| Compute Engine | offline | tab: Machine size | static |
| Compute Engine | offline | tab: Metadata | static |
| Compute Engine | offline | tab: Startup script | static |
| Cloud Functions | offline | tab: Activity | static |
| Cloud Functions | offline | tab: Permissions | static |
| Cloud Functions | offline | tab: Labels | static |
| Cloud Functions | offline | tab: Source | static |
| Cloud Functions | offline | tab: Trigger | static |
| Cloud Functions | offline | tab: Variables | static |
| Cloud Functions | offline | tab: Testing | static |
| Cloud Functions | offline | tab: Networking | static |
| Cloud Storage | offline | tab: Activity | static |
| Cloud Storage | offline | tab: Permissions | static |
| Cloud Storage | offline | tab: Labels | static |
| Cloud Storage | offline | tab: Lifecycle | static |
| Cloud Storage | offline | tab: Encryption | static |
| Cloud Storage | offline | tab: Retention | static |
| Cloud SQL | offline | tab: Activity | static |
| Cloud SQL | offline | tab: Permissions | static |
| Cloud SQL | offline | tab: Labels | static |
| Cloud SQL | offline | tab: Databases | static |
| Cloud SQL | offline | tab: Users | static |
| Cloud SQL | offline | tab: Backups | static |
| Cloud SQL | offline | tab: Replicas | static |
| Cloud SQL | offline | tab: Connectivity | static |
| Cloud SQL | offline | tab: Flags | static |
| Firestore | offline | tab: Permissions | static |
| Firestore | offline | tab: Labels | static |
| Firestore | offline | tab: Data | static |
| Firestore | offline | tab: Query builder | static |
| Firestore | offline | tab: Indexes | static |
| Firestore | offline | tab: Security rules | static |
| Firestore | offline | tab: Import / Export | static |
| VPC Network | offline | tab: Activity | static |
| VPC Network | offline | tab: Permissions | static |
| VPC Network | offline | tab: Labels | static |
| VPC Network | offline | tab: Subnets | static |
| VPC Network | offline | tab: Firewall rules | static |
| VPC Network | offline | tab: Routes | static |
| VPC Network | offline | tab: VPC peering | static |
| VPC Network | offline | tab: Properties | static |
| Pub/Sub | offline | tab: Permissions | static |
| Pub/Sub | offline | tab: Labels | static |
| Pub/Sub | offline | tab: Subscriptions | static |
| Pub/Sub | offline | tab: Schema | static |
| Pub/Sub | offline | tab: Messages | static |
| Pub/Sub | offline | tab: Encryption | static |
| Pub/Sub | offline | tab: Metrics | static |
| API Gateway | offline | tab: Activity | static |
| API Gateway | offline | tab: Permissions | static |
| API Gateway | offline | tab: Labels | static |
| API Gateway | offline | tab: Configs | static |
| API Gateway | offline | tab: Routes | static |
| API Gateway | offline | tab: Metrics | static |
| API Gateway | offline | tab: Logs | static |
| Eventarc | offline | tab: Activity | static |
| Eventarc | offline | tab: Permissions | static |
| Eventarc | offline | tab: Labels | static |
| Eventarc | offline | tab: Event matching | static |
| Eventarc | offline | tab: Metrics | static |
| Eventarc | offline | tab: Logs | static |
| Secret Manager | offline | tab: Activity | static |
| Secret Manager | offline | tab: Permissions | static |
| Secret Manager | offline | tab: Labels | static |
| Secret Manager | offline | tab: Secret value | static |
| Secret Manager | offline | tab: Versions | static |
| Secret Manager | offline | tab: Rotation | static |
| Secret Manager | offline | tab: Replication | static |
| Secret Manager | offline | tab: Encryption | static |
| Cloud KMS | offline | tab: Activity | static |
| Cloud KMS | offline | tab: Permissions | static |
| Cloud KMS | offline | tab: Labels | static |
| Cloud KMS | offline | tab: Versions | static |
| Cloud KMS | offline | tab: Key policy | static |
| Cloud KMS | offline | tab: Import jobs | static |
| Cloud KMS | offline | tab: Metrics | static |
| IAM & Admin | offline | tab: Members | static |
| IAM & Admin | offline | tab: Permissions | static |
| IAM & Admin | offline | tab: Keys | static |
| IAM & Admin | offline | tab: Properties | static |
| IAM & Admin | offline | tab: Activity log | static |
| Compute Engine | nano | tab: Activity | partial |
| Compute Engine | nano | tab: Permissions | static |
| Compute Engine | nano | tab: Labels | static |
| Compute Engine | nano | tab: Networking | static |
| Compute Engine | nano | tab: Metadata | static |
| Cloud Functions | nano | tab: Permissions | static |
| Cloud Functions | nano | tab: Labels | static |
| Cloud Functions | nano | tab: Source | static |
| Cloud Functions | nano | tab: Trigger | static |
| Cloud Functions | nano | tab: Variables | static |
| Cloud Functions | nano | tab: Testing | static |
| Cloud Functions | nano | tab: Networking | static |
| Cloud Storage | nano | tab: Permissions | static |
| Cloud Storage | nano | tab: Labels | static |
| Cloud Storage | nano | tab: Lifecycle | static |
| Cloud Storage | nano | tab: Encryption | static |
| Cloud Storage | nano | tab: Retention | static |
| Cloud SQL | nano | tab: Activity | partial |
| Cloud SQL | nano | tab: Permissions | static |
| Cloud SQL | nano | tab: Labels | static |
| Cloud SQL | nano | tab: Connectivity | static |
| Cloud SQL | nano | tab: Flags | static |
| Firestore | nano | tab: Overview | static |
| Firestore | nano | tab: Activity | partial |
| Firestore | nano | tab: Permissions | static |
| Firestore | nano | tab: Labels | static |
| Firestore | nano | tab: Data | static |
| Firestore | nano | tab: Query builder | static |
| Firestore | nano | tab: Indexes | static |
| Firestore | nano | tab: Security rules | static |
| Firestore | nano | tab: Import / Export | static |
| Firestore | nano | tab: Properties | static |
| VPC Network | nano | tab: Permissions | static |
| VPC Network | nano | tab: Labels | static |
| VPC Network | nano | tab: Subnets | static |
| VPC Network | nano | tab: Routes | static |
| VPC Network | nano | tab: VPC peering | static |
| Pub/Sub | nano | tab: Activity | partial |
| Pub/Sub | nano | tab: Permissions | static |
| Pub/Sub | nano | tab: Labels | static |
| Pub/Sub | nano | tab: Messages | static |
| Pub/Sub | nano | tab: Encryption | static |
| API Gateway | nano | tab: Permissions | static |
| API Gateway | nano | tab: Labels | static |
| API Gateway | nano | tab: Logs | static |
| Eventarc | nano | tab: Activity | partial |
| Eventarc | nano | tab: Permissions | static |
| Eventarc | nano | tab: Metrics | partial |
| Eventarc | nano | tab: Logs | static |
| Secret Manager | nano | tab: Permissions | static |
| Secret Manager | nano | tab: Labels | static |
| Secret Manager | nano | tab: Secret value | static |
| Secret Manager | nano | tab: Rotation | static |
| Secret Manager | nano | tab: Encryption | static |
| Cloud KMS | nano | tab: Permissions | static |
| Cloud KMS | nano | tab: Labels | static |
| Cloud KMS | nano | tab: Key policy | static |

</details>

<details><summary>Console parts not live yet — Azure (92)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| Virtual Machines | offline | tab: Tags | static |
| Virtual Machines | offline | tab: Connect | static |
| Virtual Machines | offline | tab: Identity | static |
| Storage accounts | offline | tab: Tags | static |
| Storage accounts | offline | tab: Diagnose and solve problems | static |
| Storage accounts | offline | tab: Tables | static |
| Storage accounts | offline | tab: Networking | static |
| SQL servers | offline | tab: Tags | static |
| SQL servers | offline | tab: Diagnose and solve problems | static |
| SQL servers | offline | tab: Deleted databases | static |
| SQL servers | offline | tab: Failover groups | static |
| SQL servers | offline | tab: Backups | static |
| Service Bus | offline | tab: Tags | static |
| Service Bus | offline | tab: Diagnose and solve problems | static |
| Service Bus | offline | tab: Geo-recovery | static |
| Service Bus | offline | tab: Networking | static |
| Cosmos DB | offline | tab: Tags | static |
| Cosmos DB | offline | tab: Diagnose and solve problems | static |
| Cosmos DB | offline | tab: Replicate data globally | static |
| Cosmos DB | offline | tab: Default consistency | static |
| Cosmos DB | offline | tab: Backup & Restore | static |
| Function apps | offline | tab: Tags | static |
| Function apps | offline | tab: Diagnose and solve problems | static |
| Function apps | offline | tab: Functions | static |
| Function apps | offline | tab: Environment variables | static |
| Function apps | offline | tab: Authentication | static |
| Function apps | offline | tab: Identity | static |
| API Management | offline | tab: Tags | static |
| API Management | offline | tab: Diagnose and solve problems | static |
| API Management | offline | tab: Named values | static |
| Virtual networks | offline | tab: Tags | static |
| Virtual networks | offline | tab: Diagnose and solve problems | static |
| Virtual networks | offline | tab: Address space | static |
| Virtual networks | offline | tab: Subnets | static |
| Virtual networks | offline | tab: DNS servers | static |
| Event Grid topics | offline | tab: Tags | static |
| Event Grid topics | offline | tab: Diagnose and solve problems | static |
| Event Grid topics | offline | tab: Topic types | static |
| Event Grid topics | offline | tab: Networking | static |
| Event Grid topics | offline | tab: Identity | static |
| Key vaults | offline | tab: Tags | static |
| Key vaults | offline | tab: Diagnose and solve problems | static |
| Key vaults | offline | tab: Access policies | static |
| Key vaults | offline | tab: Access configuration | static |
| Entra ID / RBAC | offline | tab: Conditions | static |
| Virtual Machines | nano | page: Virtual Machines | static |
| Virtual Machines | nano | tab: Tags | static |
| Virtual Machines | nano | tab: Diagnose and solve problems | static |
| Virtual Machines | nano | tab: Connect | static |
| Storage accounts | nano | tab: Tags | static |
| Storage accounts | nano | tab: Diagnose and solve problems | static |
| Storage accounts | nano | tab: File shares | static |
| Storage accounts | nano | tab: Tables | static |
| Storage accounts | nano | tab: Networking | static |
| SQL servers | nano | tab: Tags | static |
| SQL servers | nano | tab: Diagnose and solve problems | static |
| SQL servers | nano | tab: Pricing tier | static |
| SQL servers | nano | tab: Deleted databases | static |
| SQL servers | nano | tab: Failover groups | static |
| SQL servers | nano | tab: Backups | static |
| Service Bus | nano | tab: Tags | static |
| Service Bus | nano | tab: Diagnose and solve problems | static |
| Service Bus | nano | tab: Geo-recovery | static |
| Service Bus | nano | tab: Networking | static |
| Cosmos DB | nano | tab: Tags | static |
| Cosmos DB | nano | tab: Throughput (RU/s) | static |
| Cosmos DB | nano | tab: Replicate data globally | static |
| Cosmos DB | nano | tab: Backup & Restore | static |
| Function apps | nano | tab: Tags | static |
| Function apps | nano | tab: Diagnose and solve problems | static |
| Function apps | nano | tab: App keys | static |
| Function apps | nano | tab: Environment variables | static |
| Function apps | nano | tab: Authentication | static |
| Function apps | nano | tab: Identity | static |
| API Management | nano | tab: Tags | static |
| API Management | nano | tab: Diagnose and solve problems | static |
| API Management | nano | tab: Named values | static |
| Virtual networks | nano | tab: Tags | static |
| Virtual networks | nano | tab: Diagnose and solve problems | static |
| Virtual networks | nano | tab: Address space | static |
| Virtual networks | nano | tab: Connected devices | static |
| Event Grid topics | nano | tab: Tags | static |
| Event Grid topics | nano | tab: Diagnose and solve problems | static |
| Event Grid topics | nano | tab: Networking | static |
| Event Grid topics | nano | tab: Identity | static |
| Key vaults | nano | tab: Tags | static |
| Key vaults | nano | tab: Diagnose and solve problems | static |
| Key vaults | nano | tab: Secrets | unimplemented |
| Key vaults | nano | tab: Keys | unimplemented |
| Key vaults | nano | tab: Access policies | static |
| Key vaults | nano | tab: Access configuration | static |
| Entra ID / RBAC | nano | tab: Conditions | static |

</details>

<details><summary>Latest hourly test results</summary>

| Suite | Result | Checks |
|---|---|---|
| offline-ui-crawl | ❌ | 36/38 |
| offline-console-actions | ✅ | 246/246 |
| offline-api-ec2-instance-detail | ✅ | 3/3 |
| offline-api-s3-bucket-creation-date | ✅ | 3/3 |
| offline-api-aws-provider-connect | ✅ | 11/11 |
| offline-api-gcp-eventarc-trigger-defaults | ✅ | 6/6 |
| offline-api-ec2-default-public-ip | ✅ | 3/3 |
| offline-sdk-python-aws | ✅ | 88/88 |
| offline-sdk-go-aws | ✅ | 14/14 |
| offline-sdk-go-gcp | ✅ | 5/5 |
| offline-sdk-go-azure | ✅ | 14/14 |
| offline-sdk-java-aws | ✅ | 13/13 |
| offline-sdk-java-gcp | ✅ | 6/6 |
| offline-sdk-java-azure | ✅ | 5/5 |
| offline-cost-savings | ✅ | 11/11 |
| offline-cli-aws | ✅ | 15/15 |
| offline-cli-gcp | ✅ | 6/6 |
| offline-cli-azure | ✅ | 6/6 |
| offline-ui-core | ✅ | 9/9 |
| nano-ui-crawl | ❌ | 40/43 |
| nano-cores | ✅ | 37/37 |
| nano-aws-iam-detail | ✅ | 8/8 |
| nano-aws-ec2-launch | ✅ | 13/13 |
| nano-ui-aws-api | ❌ | 5/6 |
| nano-ui-aws-tabs | ✅ | 11/11 |
| nano-ui-gcp-tabs | ✅ | 6/6 |
| nano-ui-gcp-activity-detail | ✅ | 2/2 |
| nano-ui-gcp-grid-defaults | ✅ | 39/39 |
| nano-ui-gcp-pubsub-subscriptions | ✅ | 3/3 |
| nano-ui-gcp-metrics-counts | ✅ | 3/3 |
| offline-ui-gcp-pubsub-subscriptions | ✅ | 3/3 |
| offline-ui-gcp-activity-detail | ✅ | 2/2 |
| offline-ui-gcp-grid-defaults | ✅ | 39/39 |
| nano-ui-gcp-pubsub-grid | ✅ | 3/3 |
| offline-ui-gcp-pubsub-grid | ✅ | 3/3 |
| offline-api-cost-savings-extras | ✅ | 12/12 |
| nano-ui-aws-vpc-apigw-lists | ✅ | 5/5 |
| nano-ui-aws-compute-reload | ✅ | 4/4 |
| nano-ui-azure-savings | ✅ | 8/8 |
| nano-ui-aws-compute-savings | ✅ | 6/6 |
| nano-ui-aws-ec2-detail-tabs | ✅ | 5/5 |
| offline-ui-aws-ec2-detail-tabs | ✅ | 5/5 |
| offline-ui-aws-detail-name | ✅ | 4/4 |
| offline-ui-aws-sqs-dlq-tab | ✅ | 2/2 |
| nano-ui-aws-sqs-dlq-tab | ✅ | 2/2 |
| nano-ui-aws-rds-connectivity-tabs | ✅ | 3/3 |
| offline-ui-aws-rds-connectivity-tabs | ✅ | 3/3 |
| nano-ui-aws-vpc-details-tab | ✅ | 2/2 |
| offline-ui-aws-vpc-details-tab | ✅ | 2/2 |
| offline-ui-aws-apigw-tabs | ✅ | 4/4 |
| offline-api-gcp-pubsub-savings | ✅ | 8/8 |
| offline-api-gcp-apigateway-savings | ✅ | 5/5 |
| offline-api-gcp-console-next | ✅ | 28/28 |
| offline-api-gcp-grid-columns | ✅ | 19/19 |
| offline-api-gcp-vault-console-secrets | ✅ | 9/9 |
| offline-api-aws-console-savings | ✅ | 12/12 |
| offline-api-aws-eventbridge-rule-defaults | ✅ | 14/14 |
| nano-ui-azure-tabs | ✅ | 71/71 |
| nano-ui-azure-dp | ✅ | 5/5 |
| nano-ui-azure-flat-create | ✅ | 8/8 |
| offline-ui-azure-flat-create | ✅ | 8/8 |
| nano-ui-azure-dp-detail | ✅ | 12/12 |
| nano-ui-azure-rail-last | ✅ | 3/3 |
| nano-ui-azure-home | ✅ | 7/7 |
| nano-ui-budget-savings | ✅ | 5/5 |
| nano-ui-reload-backend | ✅ | 3/3 |
| nano-ui-azure-rg-nav | ✅ | 3/3 |
| offline-ui-azure-rg-nav | ✅ | 3/3 |
| nano-ui-azure-storage-console | ✅ | 12/12 |

</details>

<details><summary>Not yet scheduled — AWS (390 of 435 published)</summary>

| Service | Upstream id | Operations |
|---|---|---|
| — | `accessanalyzer` |  |
| — | `account` |  |
| — | `account-access` |  |
| — | `acm-pca` |  |
| — | `agent-registry` |  |
| — | `agent-registry-control` |  |
| — | `aiops` |  |
| — | `amp` |  |
| — | `amplify` |  |
| — | `amplifybackend` |  |
| — | `amplifyuibuilder` |  |
| — | `apigatewaymanagementapi` |  |
| — | `appconfig` |  |
| — | `appconfigdata` |  |
| — | `appfabric` |  |
| — | `appflow` |  |
| — | `appintegrations` |  |
| — | `application-autoscaling` |  |
| — | `application-insights` |  |
| — | `application-signals` |  |
| — | `applicationcostprofiler` |  |
| — | `appmesh` |  |
| — | `apprunner` |  |
| — | `appstream` |  |
| — | `arc-region-switch` |  |
| — | `arc-zonal-shift` |  |
| — | `artifact` |  |
| — | `auditmanager` |  |
| — | `autoscaling-plans` |  |
| — | `b2bi` |  |
| — | `backup-gateway` |  |
| — | `backupsearch` |  |
| — | `bcm-dashboards` |  |
| — | `bcm-data-exports` |  |
| — | `bcm-pricing-calculator` |  |
| — | `bcm-recommended-actions` |  |
| — | `bedrock` |  |
| — | `bedrock-agent` |  |
| — | `bedrock-agent-runtime` |  |
| — | `bedrock-agentcore` |  |
| — | `bedrock-agentcore-control` |  |
| — | `bedrock-data-automation` |  |
| — | `bedrock-data-automation-runtime` |  |
| — | `billing` |  |
| — | `billingconductor` |  |
| — | `braket` |  |
| — | `budgets` |  |
| — | `ce` |  |
| — | `chatbot` |  |
| — | `chime` |  |
| — | `chime-sdk-identity` |  |
| — | `chime-sdk-media-pipelines` |  |
| — | `chime-sdk-meetings` |  |
| — | `chime-sdk-messaging` |  |
| — | `chime-sdk-voice` |  |
| — | `cleanrooms` |  |
| — | `cleanroomsml` |  |
| — | `cloud9` |  |
| — | `cloudcontrol` |  |
| — | `clouddirectory` |  |
| — | `cloudfront` |  |
| — | `cloudfront-keyvaluestore` |  |
| — | `cloudhsm` |  |
| — | `cloudhsmv2` |  |
| — | `cloudsearch` |  |
| — | `cloudsearchdomain` |  |
| — | `cloudtrail` |  |
| — | `cloudtrail-data` |  |
| — | `cloudwatchomni` |  |
| — | `codeartifact` |  |
| — | `codecatalyst` |  |
| — | `codecommit` |  |
| — | `codeconnections` |  |
| — | `codedeploy` |  |
| — | `codeguru-reviewer` |  |
| — | `codeguru-security` |  |
| — | `codeguruprofiler` |  |
| — | `codepipeline` |  |
| — | `codestar-connections` |  |
| — | `codestar-notifications` |  |
| — | `cognito-identity` |  |
| — | `cognito-sync` |  |
| — | `comprehend` |  |
| — | `comprehendmedical` |  |
| — | `compute-optimizer` |  |
| — | `compute-optimizer-automation` |  |
| — | `config` |  |
| — | `connect` |  |
| — | `connect-contact-lens` |  |
| — | `connectcampaigns` |  |
| — | `connectcampaignsv2` |  |
| — | `connectcases` |  |
| — | `connecthealth` |  |
| — | `connectparticipant` |  |
| — | `continuum` |  |
| — | `controlcatalog` |  |
| — | `controltower` |  |
| — | `cost-optimization-hub` |  |
| — | `cur` |  |
| — | `customer-profiles` |  |
| — | `databrew` |  |
| — | `dataexchange` |  |
| — | `datapipeline` |  |
| — | `datasync` |  |
| — | `datazone` |  |
| — | `dax` |  |
| — | `deadline` |  |
| — | `detective` |  |
| — | `devicefarm` |  |
| — | `devops-agent` |  |
| — | `devops-guru` |  |
| — | `directconnect` |  |
| — | `discovery` |  |
| — | `dlm` |  |
| — | `dms` |  |
| — | `docdb` |  |
| — | `docdb-elastic` |  |
| — | `drs` |  |
| — | `ds` |  |
| — | `ds-data` |  |
| — | `dsql` |  |
| — | `ebs` |  |
| — | `ec2-instance-connect` |  |
| — | `ecr-public` |  |
| — | `eks` |  |
| — | `eks-auth` |  |
| — | `elasticbeanstalk` |  |
| — | `elb` |  |
| — | `elementalinference` |  |
| — | `emr` |  |
| — | `emr-containers` |  |
| — | `emr-serverless` |  |
| — | `endusermessaging` |  |
| — | `entityresolution` |  |
| — | `es` |  |
| — | `eventbridgev2` |  |
| — | `evs` |  |
| — | `fis` |  |
| — | `fms` |  |
| — | `forecast` |  |
| — | `forecastquery` |  |
| — | `frauddetector` |  |
| — | `freetier` |  |
| — | `fsx` |  |
| — | `gamelift` |  |
| — | `gameliftstreams` |  |
| — | `geo-maps` |  |
| — | `geo-places` |  |
| — | `geo-routes` |  |
| — | `glacier` |  |
| — | `globalaccelerator` |  |
| — | `grafana` |  |
| — | `greengrass` |  |
| — | `greengrassv2` |  |
| — | `groundstation` |  |
| — | `guardduty` |  |
| — | `health` |  |
| — | `healthlake` |  |
| — | `iam-toolbox` |  |
| — | `identitystore` |  |
| — | `imagebuilder` |  |
| — | `importexport` |  |
| — | `inspector` |  |
| — | `inspector-scan` |  |
| — | `inspector2` |  |
| — | `interconnect` |  |
| — | `internetmonitor` |  |
| — | `invoicing` |  |
| — | `iot` |  |
| — | `iot-data` |  |
| — | `iot-jobs-data` |  |
| — | `iot-managed-integrations` |  |
| — | `iotdeviceadvisor` |  |
| — | `iotfleetwise` |  |
| — | `iotsecuretunneling` |  |
| — | `iotsitewise` |  |
| — | `iotthingsgraph` |  |
| — | `iottwinmaker` |  |
| — | `iotwireless` |  |
| — | `ivs` |  |
| — | `ivs-realtime` |  |
| — | `ivschat` |  |
| — | `kafkaconnect` |  |
| — | `kendra` |  |
| — | `kendra-ranking` |  |
| — | `keyspaces` |  |
| — | `keyspacesstreams` |  |
| — | `kinesis-video-archived-media` |  |
| — | `kinesis-video-media` |  |
| — | `kinesis-video-signaling` |  |
| — | `kinesis-video-webrtc-storage` |  |
| — | `kinesisanalytics` |  |
| — | `kinesisanalyticsv2` |  |
| — | `kinesisvideo` |  |
| — | `lakeformation` |  |
| — | `lambda-core` |  |
| — | `lambda-microvms` |  |
| — | `lambda-web` |  |
| — | `launch-wizard` |  |
| — | `lex-models` |  |
| — | `lex-runtime` |  |
| — | `lexv2-models` |  |
| — | `lexv2-runtime` |  |
| — | `license-manager` |  |
| — | `license-manager-linux-subscriptions` |  |
| — | `license-manager-user-subscriptions` |  |
| — | `lightsail` |  |
| — | `location` |  |
| — | `lookoutequipment` |  |
| — | `m2` |  |
| — | `machinelearning` |  |
| — | `macie2` |  |
| — | `mailmanager` |  |
| — | `managedblockchain` |  |
| — | `managedblockchain-query` |  |
| — | `marketplace-agreement` |  |
| — | `marketplace-catalog` |  |
| — | `marketplace-deployment` |  |
| — | `marketplace-discovery` |  |
| — | `marketplace-entitlement` |  |
| — | `marketplace-reporting` |  |
| — | `marketplacecommerceanalytics` |  |
| — | `mediaconnect` |  |
| — | `mediaconvert` |  |
| — | `medialive` |  |
| — | `mediapackage` |  |
| — | `mediapackage-vod` |  |
| — | `mediapackagev2` |  |
| — | `mediastore` |  |
| — | `mediastore-data` |  |
| — | `mediatailor` |  |
| — | `medical-imaging` |  |
| — | `memorydb` |  |
| — | `meteringmarketplace` |  |
| — | `mgh` |  |
| — | `mgn` |  |
| — | `migration-hub-refactor-spaces` |  |
| — | `migrationhub-config` |  |
| — | `migrationhuborchestrator` |  |
| — | `migrationhubstrategy` |  |
| — | `mpa` |  |
| — | `mturk` |  |
| — | `mwaa` |  |
| — | `mwaa-serverless` |  |
| — | `neptune` |  |
| — | `neptune-graph` |  |
| — | `neptunedata` |  |
| — | `network-firewall` |  |
| — | `network-security-manager` |  |
| — | `networkflowmonitor` |  |
| — | `networkmanager` |  |
| — | `networkmonitor` |  |
| — | `notifications` |  |
| — | `notificationscontacts` |  |
| — | `nova-act` |  |
| — | `oam` |  |
| — | `observabilityadmin` |  |
| — | `odb` |  |
| — | `omics` |  |
| — | `opensearchserverless` |  |
| — | `organizations` |  |
| — | `osis` |  |
| — | `outposts` |  |
| — | `partnercentral-account` |  |
| — | `partnercentral-benefits` |  |
| — | `partnercentral-channel` |  |
| — | `partnercentral-revenue-measurement` |  |
| — | `partnercentral-selling` |  |
| — | `payment-cryptography` |  |
| — | `payment-cryptography-data` |  |
| — | `pca-connector-ad` |  |
| — | `pca-connector-scep` |  |
| — | `pcs` |  |
| — | `personalize` |  |
| — | `personalize-events` |  |
| — | `personalize-runtime` |  |
| — | `pi` |  |
| — | `pinpoint` |  |
| — | `pinpoint-email` |  |
| — | `pinpoint-sms-voice` |  |
| — | `pinpoint-sms-voice-v2` |  |
| — | `pipes` |  |
| — | `polly` |  |
| — | `pricing` |  |
| — | `pricing-plan-manager` |  |
| — | `proton` |  |
| — | `qapps` |  |
| — | `qbusiness` |  |
| — | `qconnect` |  |
| — | `quicksight` |  |
| — | `ram` |  |
| — | `rbin` |  |
| — | `redshift` |  |
| — | `redshift-data` |  |
| — | `redshift-serverless` |  |
| — | `rekognition` |  |
| — | `repostspace` |  |
| — | `resiliencehub` |  |
| — | `resiliencehubv2` |  |
| — | `resource-explorer-2` |  |
| — | `resource-groups` |  |
| — | `resourcegroupstaggingapi` |  |
| — | `rolesanywhere` |  |
| — | `route53-recovery-cluster` |  |
| — | `route53-recovery-control-config` |  |
| — | `route53-recovery-readiness` |  |
| — | `route53domains` |  |
| — | `route53globalresolver` |  |
| — | `route53profiles` |  |
| — | `route53resolver` |  |
| — | `rtbfabric` |  |
| — | `rum` |  |
| — | `s3control` |  |
| — | `s3files` |  |
| — | `s3outposts` |  |
| — | `s3tables` |  |
| — | `s3vectors` |  |
| — | `sagemaker` |  |
| — | `sagemaker-a2i-runtime` |  |
| — | `sagemaker-edge` |  |
| — | `sagemaker-featurestore-runtime` |  |
| — | `sagemaker-geospatial` |  |
| — | `sagemaker-metrics` |  |
| — | `sagemaker-runtime` |  |
| — | `sagemakerjobruntime` |  |
| — | `sagemakertrainingsessionruntime` |  |
| — | `savingsplans` |  |
| — | `schemas` |  |
| — | `sdb` |  |
| — | `security-ir` |  |
| — | `securityagent` |  |
| — | `securityhub` |  |
| — | `securitylake` |  |
| — | `serverlessrepo` |  |
| — | `service-quotas` |  |
| — | `servicecatalog` |  |
| — | `servicecatalog-appregistry` |  |
| — | `servicediscovery` |  |
| — | `ses` |  |
| — | `shield` |  |
| — | `signer` |  |
| — | `signer-data` |  |
| — | `signin` |  |
| — | `simpledbv2` |  |
| — | `sms-voice` |  |
| — | `snow-device-management` |  |
| — | `snowball` |  |
| — | `socialmessaging` |  |
| — | `ssm-contacts` |  |
| — | `ssm-guiconnect` |  |
| — | `ssm-incidents` |  |
| — | `ssm-quicksetup` |  |
| — | `ssm-sap` |  |
| — | `sso` |  |
| — | `sso-admin` |  |
| — | `sso-oidc` |  |
| — | `storagegateway` |  |
| — | `supplychain` |  |
| — | `support` |  |
| — | `support-app` |  |
| — | `supportauthz` |  |
| — | `sustainability` |  |
| — | `swf` |  |
| — | `synthetics` |  |
| — | `taxsettings` |  |
| — | `textract` |  |
| — | `timestream-influxdb` |  |
| — | `timestream-query` |  |
| — | `timestream-write` |  |
| — | `transcribe` |  |
| — | `transfer` |  |
| — | `translate` |  |
| — | `trustedadvisor` |  |
| — | `uxc` |  |
| — | `verifiedpermissions` |  |
| — | `voice-id` |  |
| — | `vpc-lattice` |  |
| — | `waf` |  |
| — | `waf-regional` |  |
| — | `wafv2` |  |
| — | `wellarchitected` |  |
| — | `wickr` |  |
| — | `wisdom` |  |
| — | `workdocs` |  |
| — | `workmail` |  |
| — | `workmailmessageflow` |  |
| — | `workspaces` |  |
| — | `workspaces-instances` |  |
| — | `workspaces-thin-client` |  |
| — | `workspaces-web` |  |

</details>

<details><summary>Not yet scheduled — GCP (281 of 316 published)</summary>

| Service | Upstream id | Operations |
|---|---|---|
| Abusive Experience Report API | `abusiveexperiencereport/v1` |  |
| Accelerated Mobile Pages (AMP) URL API | `acceleratedmobilepageurl/v1` |  |
| Access Approval API | `accessapproval/v1` |  |
| Access Context Manager API | `accesscontextmanager/v1` |  |
| Address Validation API | `addressvalidation/v1` |  |
| Ad Exchange Buyer API II | `adexchangebuyer2/v2beta1` |  |
| Ad Experience Report API | `adexperiencereport/v1` |  |
| Admin SDK API | `admin/reports_v1` |  |
| AdMob API | `admob/v1` |  |
| AdSense Management API | `adsense/v2` |  |
| AdSense Platform API | `adsenseplatform/v1` |  |
| Advisory Notifications API | `advisorynotifications/v1` |  |
| Agencies and Brands API | `agenciesandbrands/v1` |  |
| Agent Identity API | `agentidentity/v1` |  |
| Agent Identity Credentials API | `agentidentitycredentials/v1` |  |
| Agent Registry API | `agentregistry/v1` |  |
| Air Quality API | `airquality/v1` |  |
| Google Workspace Alert Center API | `alertcenter/v1beta1` |  |
| AlloyDB API | `alloydb/v1` |  |
| Google Analytics Admin API | `analyticsadmin/v1beta` |  |
| Google Analytics Data API | `analyticsdata/v1beta` |  |
| Analytics Hub API | `analyticshub/v1` |  |
| Android Developer ID Status API | `androiddeveloperidstatus/v1` |  |
| Android Device Provisioning Partner API | `androiddeviceprovisioning/v1` |  |
| Google Play EMM API | `androidenterprise/v1` |  |
| Android Management API | `androidmanagement/v1` |  |
| Google Play Android Developer API | `androidpublisher/v3` |  |
| Apigee API | `apigee/v1` |  |
| API hub API | `apihub/v1` |  |
| API Keys API | `apikeys/v2` |  |
| API Management API | `apim/v1alpha` |  |
| App Engine Admin API | `appengine/v1` |  |
| App Hub API | `apphub/v1` |  |
| Google Workspace Marketplace API | `appsmarket/v2` |  |
| Area120 Tables API | `area120tables/v1alpha1` |  |
| Places Aggregate API | `areainsights/v1` |  |
| Assured Workloads API | `assuredworkloads/v1` |  |
| Audit Manager API | `auditmanager/v1` |  |
| Authorized Buyers Marketplace API | `authorizedbuyersmarketplace/v1` |  |
| Backup and DR Service API | `backupdr/v1` |  |
| Bare Metal Solution API | `baremetalsolution/v2` |  |
| BeyondCorp API | `beyondcorp/v1` |  |
| Lakehouse API | `biglake/v1` |  |
| BigQuery Connection API | `bigqueryconnection/v1` |  |
| BigQuery Data Policy API | `bigquerydatapolicy/v2` |  |
| BigQuery Data Transfer API | `bigquerydatatransfer/v1` |  |
| BigQuery Reservation API | `bigqueryreservation/v1` |  |
| Cloud Billing Budget API | `billingbudgets/v1` |  |
| Binary Authorization API | `binaryauthorization/v1` |  |
| Blockchain Node Engine API | `blockchainnodeengine/v1` |  |
| Blogger API | `blogger/v3` |  |
| Books API | `books/v1` |  |
| Business Profile Performance API | `businessprofileperformance/v1` |  |
| Google Calendar API | `calendar/v3` |  |
| Gemini Enterprise for Customer Experience API | `ces/v1` |  |
| Google Chat API | `chat/v1` |  |
| Checks API | `checks/v1alpha` |  |
| Chrome Management API | `chromemanagement/v1` |  |
| Chrome Policy API | `chromepolicy/v1` |  |
| Chrome UX Report API | `chromeuxreport/v1` |  |
| Chrome Web Store API | `chromewebstore/v2` |  |
| Google Civic Information API | `civicinfo/v2` |  |
| Google Classroom API | `classroom/v1` |  |
| Cloud Asset API | `cloudasset/v1` |  |
| Cloud Billing API | `cloudbilling/v1` |  |
| Cloud Build API | `cloudbuild/v2` |  |
| Cloud Channel API | `cloudchannel/v1` |  |
| Cloud Commerce Partner Procurement API | `cloudcommerceprocurement/v1` |  |
| Cloud Controls Partner API | `cloudcontrolspartner/v1` |  |
| Cloud Deploy API | `clouddeploy/v1` |  |
| Error Reporting API | `clouderrorreporting/v1beta1` |  |
| Cloud Identity API | `cloudidentity/v1` |  |
| Cloud Location Finder API | `cloudlocationfinder/v1` |  |
| Cloud Number Registry API | `cloudnumberregistry/v1alpha` |  |
| Cloud Product Registry API | `cloudproductregistry/v1` |  |
| Cloud Profiler API | `cloudprofiler/v2` |  |
| Cloud Resource Manager API | `cloudresourcemanager/v3` |  |
| Cloud Search API | `cloudsearch/v1` |  |
| Cloud Shell API | `cloudshell/v1` |  |
| Google Cloud Support API | `cloudsupport/v2` |  |
| Infrastructure Manager API | `config/v1` |  |
| Connectors API | `connectors/v2` |  |
| Contact Center AI Platform API | `contactcenteraiplatform/v1alpha1` |  |
| Contact Center AI Insights API | `contactcenterinsights/v1` |  |
| Container Analysis API | `containeranalysis/v1` |  |
| Document AI Warehouse API | `contentwarehouse/v1` |  |
| CSS API | `css/v1` |  |
| Curation Partners API | `curationpartners/v1` |  |
| Custom Search API | `customsearch/v1` |  |
| Database Center API | `databasecenter/v1beta` |  |
| Google Cloud Data Catalog API | `datacatalog/v1` |  |
| Dataform API | `dataform/v1` |  |
| Cloud Data Fusion API | `datafusion/v1` |  |
| Data Labeling API | `datalabeling/v1beta1` |  |
| Data Lineage API | `datalineage/v1` |  |
| Data Manager API | `datamanager/v1` |  |
| Database Migration API | `datamigration/v1` |  |
| Data pipelines API | `datapipelines/v1` |  |
| Cloud Dataplex API | `dataplex/v1` |  |
| Data Portability API | `dataportability/v1` |  |
| Datastream API | `datastream/v1` |  |
| Deep Review API | `deepreview/v1` |  |
| Cloud Deployment Manager V2 API | `deploymentmanager/v2` |  |
| Developer Connect API | `developerconnect/v1` |  |
| Developer Knowledge API | `developerknowledge/v1` |  |
| Device Run API | `devicerun/v1alpha` |  |
| Campaign Manager 360 API | `dfareporting/v5` |  |
| Dialogflow API | `dialogflow/v3` |  |
| Digital Asset Links API | `digitalassetlinks/v1` |  |
| API Discovery Service | `discovery/v1` |  |
| Discovery Engine API | `discoveryengine/v1` |  |
| Display & Video 360 API | `displayvideo/v5` |  |
| Sensitive Data Protection (DLP) | `dlp/v2` |  |
| Google Docs API | `docs/v1` |  |
| Cloud Document AI API | `documentai/v1` |  |
| Cloud Domains API | `domains/v1` |  |
| DoubleClick Bid Manager API | `doubleclickbidmanager/v2` |  |
| Search Ads 360 API | `doubleclicksearch/v2` |  |
| Drive API | `drive/v3` |  |
| Drive Activity API | `driveactivity/v2` |  |
| Drive Labels API | `drivelabels/v2` |  |
| Essential Contacts API | `essentialcontacts/v1` |  |
| Fact Check Tools API | `factchecktools/v1alpha1` |  |
| Firebase Cloud Messaging API | `fcm/v1` |  |
| Firebase Cloud Messaging Data API | `fcmdata/v1beta1` |  |
| Firebase Management API | `firebase/v1beta1` |  |
| Firebase App Check API | `firebaseappcheck/v1` |  |
| Firebase App Distribution API | `firebaseappdistribution/v1` |  |
| Firebase App Hosting API | `firebaseapphosting/v1` |  |
| Firebase Crashlytics API | `firebasecrashlytics/v1alpha` |  |
| Firebase Realtime Database Management API | `firebasedatabase/v1beta` |  |
| Firebase SQL Connect API | `firebasedataconnect/v1` |  |
| Firebase Dynamic Links API | `firebasedynamiclinks/v1` |  |
| Firebase Hosting API | `firebasehosting/v1` |  |
| Firebase ML API | `firebaseml/v1` |  |
| Firebase Rules API | `firebaserules/v1` |  |
| Cloud Storage for Firebase API | `firebasestorage/v1beta` |  |
| Fitness API | `fitness/v1` |  |
| Google Forms API | `forms/v1` |  |
| Cloud FTP API | `ftp/v1` |  |
| Google Play Games Services API | `games/v1` |  |
| Google Play Games Services Publishing API | `gamesConfiguration/v1configuration` |  |
| Google Play Games Services Management API | `gamesManagement/v1management` |  |
| Backup for GKE API | `gkebackup/v1` |  |
| GKE Hub API | `gkehub/v2` |  |
| GKE On-Prem API | `gkeonprem/v1` |  |
| Gmail API | `gmail/v1` |  |
| Gmail Postmaster Tools API | `gmailpostmastertools/v2` |  |
| Groups Migration API | `groupsmigration/v1` |  |
| Groups Settings API | `groupssettings/v1` |  |
| Google Health API | `health/v4` |  |
| Cloud Healthcare API | `healthcare/v1` |  |
| HomeGraph API | `homegraph/v1` |  |
| Cluster Director API | `hypercomputecluster/v1` |  |
| Cloud Identity-Aware Proxy API | `iap/v1` |  |
| Identity Toolkit API | `identitytoolkit/v3` |  |
| Cloud IDS API | `ids/v1` |  |
| Web Search Indexing API | `indexing/v3` |  |
| Application Integration API | `integrations/v2` |  |
| Cloud Talent Solution API | `jobs/v4` |  |
| Google Keep API | `keep/v1` |  |
| Knowledge Graph Search API | `kgsearch/v1` |  |
| KMS Inventory API | `kmsinventory/v1` |  |
| Cloud Natural Language API | `language/v2` |  |
| Library Agent API | `libraryagent/v1` |  |
| Enterprise License Manager API | `licensing/v1` |  |
| Local Services API | `localservices/v1` |  |
| Looker (Google Cloud core) API | `looker/v1` |  |
| Managed Service for Microsoft Active Directory API | `managedidentities/v1` |  |
| Managed Service for Apache Kafka API | `managedkafka/v1` |  |
| Manufacturer Center API | `manufacturers/v1` |  |
| Google Marketing Platform Admin API | `marketingplatformadmin/v1alpha` |  |
| Google Meet API | `meet/v2` |  |
| Cloud Memorystore for Memcached API | `memcache/v1` |  |
| Merchant API | `merchantapi/reviews_v1beta` |  |
| Dataproc Metastore API | `metastore/v1` |  |
| Migration Center API | `migrationcenter/v1` |  |
| AI Platform Training & Prediction API | `ml/v1` |  |
| My Business Account Management API | `mybusinessaccountmanagement/v1` |  |
| My Business Business Information API | `mybusinessbusinessinformation/v1` |  |
| My Business Lodging API | `mybusinesslodging/v1` |  |
| My Business Notifications API | `mybusinessnotifications/v1` |  |
| My Business Place Actions API | `mybusinessplaceactions/v1` |  |
| My Business Q&A API | `mybusinessqanda/v1` |  |
| My Business Verifications API | `mybusinessverifications/v1` |  |
| NetApp API | `netapp/v1` |  |
| Network Connectivity API | `networkconnectivity/v1` |  |
| Network Management API | `networkmanagement/v1` |  |
| Network Security API | `networksecurity/v1` |  |
| Network Services API | `networkservices/v1` |  |
| Notebooks API | `notebooks/v2` |  |
| Google OAuth2 API | `oauth2/v2` |  |
| Observability API | `observability/v1` |  |
| On-Demand Scanning API | `ondemandscanning/v1` |  |
| Oracle Database@Google Cloud API | `oracledatabase/v1` |  |
| Organization Policy API | `orgpolicy/v2` |  |
| OS Config API | `osconfig/v2` |  |
| Cloud OS Login API | `oslogin/v1` |  |
| PageSpeed Insights API | `pagespeedonline/v5` |  |
| Parallelstore API | `parallelstore/v1` |  |
| Parameter Manager API | `parametermanager/v1` |  |
| Payments Reseller Subscription API | `paymentsresellersubscription/v1` |  |
| People API | `people/v1` |  |
| Places API (New) | `places/v1` |  |
| Google Play Custom App Publishing API | `playcustomapp/v1` |  |
| Google Play Developer Reporting API | `playdeveloperreporting/v1beta1` |  |
| Google Play Grouping API | `playgrouping/v1alpha1` |  |
| Google Play Integrity API | `playintegrity/v1` |  |
| Policy Analyzer API | `policyanalyzer/v1` |  |
| Policy Simulator API | `policysimulator/v1` |  |
| Policy Troubleshooter API | `policytroubleshooter/v3` |  |
| Pollen API | `pollen/v1` |  |
| Poly API | `poly/v1` |  |
| Certificate Authority API | `privateca/v1` |  |
| SAS Portal API (Testing) | `prod_tt_sasportal/v1alpha1` |  |
| Public Certificate Authority API | `publicca/v1` |  |
| Pub/Sub Lite API | `pubsublite/v1` |  |
| Rapid Migration Assessment API | `rapidmigrationassessment/v1` |  |
| Reader Revenue Subscription Linking API | `readerrevenuesubscriptionlinking/v1` |  |
| Real-time Bidding API | `realtimebidding/v1` |  |
| reCAPTCHA Enterprise API | `recaptchaenterprise/v1` |  |
| Recommendations AI (Beta) | `recommendationengine/v1beta1` |  |
| Recommender API | `recommender/v1` |  |
| Google Workspace Reseller API | `reseller/v1` |  |
| AI Commerce Search API | `retail/v2` |  |
| Cloud Runtime Configuration API | `runtimeconfig/v1` |  |
| App Lifecycle Manager API | `saasservicemgmt/v1` |  |
| Safe Browsing API | `safebrowsing/v5` |  |
| SAS Portal API | `sasportal/v1alpha1` |  |
| Apps Script API | `script/v1` |  |
| Search Ads 360 Reporting API | `searchads360/v23` |  |
| Google Search Console API | `searchconsole/v1` |  |
| Secure Source Manager API | `securesourcemanager/v1` |  |
| Security Command Center API | `securitycenter/v1` |  |
| Security Posture API | `securityposture/v1` |  |
| Service Consumer Management API | `serviceconsumermanagement/v1` |  |
| Service Control API | `servicecontrol/v2` |  |
| Service Directory API | `servicedirectory/v1` |  |
| Service Management API | `servicemanagement/v1` |  |
| Service Networking API | `servicenetworking/v1` |  |
| Service Usage API | `serviceusage/v1` |  |
| Google Sheets API | `sheets/v4` |  |
| Site Verification API | `siteVerification/v1` |  |
| Google Slides API | `slides/v1` |  |
| Smart Device Management API | `smartdevicemanagement/v1` |  |
| Solar API | `solar/v1` |  |
| Cloud Speech-to-Text API | `speech/v1` |  |
| Storage Batch Operations API | `storagebatchoperations/v1` |  |
| Storage Transfer API | `storagetransfer/v1` |  |
| Street View Publish API | `streetviewpublish/v1` |  |
| Security Token Service API | `sts/v1` |  |
| Tag Manager API | `tagmanager/v2` |  |
| Google Tasks API | `tasks/v1` |  |
| Cloud Testing API | `testing/v1` |  |
| Cloud Text-to-Speech API | `texttospeech/v1` |  |
| Threat Intelligence API | `threatintelligence/v1beta` |  |
| Cloud Tool Results API | `toolresults/v1beta3` |  |
| Cloud TPU API | `tpu/v2` |  |
| Traffic Director API | `trafficdirector/v3` |  |
| Transcoder API | `transcoder/v1` |  |
| Travel Impact Model API | `travelimpactmodel/v1` |  |
| Google Vault API | `vault/v1` |  |
| Chrome Verified Access API | `verifiedaccess/v2` |  |
| versionhistory.googleapis.com API | `versionhistory/v1` |  |
| Cloud Video Intelligence API | `videointelligence/v1` |  |
| Cloud Vision API | `vision/v1` |  |
| VM Migration API | `vmmigration/v1` |  |
| VMware Engine API | `vmwareengine/v1` |  |
| Serverless VPC Access API | `vpcaccess/v1` |  |
| Google Wallet API | `walletobjects/v1` |  |
| Web Content Publisher API | `webcontentpublisher/v1` |  |
| Web Fonts Developer API | `webfonts/v1` |  |
| Web Risk API | `webrisk/v1` |  |
| Web Security Scanner API | `websecurityscanner/v1` |  |
| Workflow Executions API | `workflowexecutions/v1` |  |
| Workload Manager API | `workloadmanager/v1` |  |
| Google Workspace Events API | `workspaceevents/v1` |  |
| Cloud Workstations API | `workstations/v1` |  |
| YouTube Data API v3 | `youtube/v3` |  |
| YouTube Analytics API | `youtubeAnalytics/v2` |  |
| YouTube Reporting API | `youtubereporting/v1` |  |

</details>

<details><summary>Not yet scheduled — Azure (282 of 317 published)</summary>

| Service | Upstream id | Operations |
|---|---|---|
| — | `EnterpriseKnowledgeGraph` |  |
| — | `addons` |  |
| — | `adhybridhealthservice` |  |
| — | `advisor` |  |
| — | `agricultureplatform` |  |
| — | `agrifood` |  |
| — | `ai` |  |
| — | `ai-foundry` |  |
| — | `alertsmanagement` |  |
| — | `analysisservices` |  |
| — | `anyscale` |  |
| — | `apicenter` |  |
| — | `appcomplianceautomation` |  |
| — | `applink` |  |
| — | `appplatform` |  |
| — | `artifactsigning` |  |
| — | `attestation` |  |
| — | `automanage` |  |
| — | `automation` |  |
| — | `awsconnector` |  |
| — | `azsadmin` |  |
| — | `azure-kusto` |  |
| — | `azure-native-integrations` |  |
| — | `azureactivedirectory` |  |
| — | `azurearcdata` |  |
| — | `azuredata` |  |
| — | `azuredatatransfer` |  |
| — | `azuredependencymap` |  |
| — | `azurefleet` |  |
| — | `azureintegrationspaces` |  |
| — | `azurelargeinstance` |  |
| — | `azureresiliencemanagement` |  |
| — | `azurestack` |  |
| — | `azurestackhci` |  |
| — | `baremetalinfrastructure` |  |
| — | `billing` |  |
| — | `billingbenefits` |  |
| — | `billingtrust` |  |
| — | `blueprint` |  |
| — | `botservice` |  |
| — | `carbon` |  |
| — | `certificateregistration` |  |
| — | `chaos` |  |
| — | `cloudhealth` |  |
| — | `cloudshell` |  |
| — | `codesigning` |  |
| — | `commerce` |  |
| — | `common-types` |  |
| — | `communication` |  |
| — | `communitytraining` |  |
| — | `computebulkactions` |  |
| — | `computelimit` |  |
| — | `computeschedule` |  |
| — | `confidentialledger` |  |
| — | `confluent` |  |
| — | `connectedcache` |  |
| — | `connectedvmware` |  |
| — | `consumption` |  |
| — | `containerinstance` |  |
| — | `containerstorage` |  |
| — | `contosowidgetmanager` |  |
| — | `cost-management` |  |
| — | `cpim` |  |
| — | `customer-insights` |  |
| — | `customerlockbox` |  |
| — | `customproviders` |  |
| — | `dashboard` |  |
| — | `databasefleetmanager` |  |
| — | `databasewatcher` |  |
| — | `databox` |  |
| — | `databoxedge` |  |
| — | `databricks` |  |
| — | `datacatalog` |  |
| — | `datadog` |  |
| — | `datalake-analytics` |  |
| — | `datalake-store` |  |
| — | `datamigration` |  |
| — | `dataprotection` |  |
| — | `datashare` |  |
| — | `dell` |  |
| — | `desktopvirtualization` |  |
| — | `devcenter` |  |
| — | `developerhub` |  |
| — | `deviceprovisioningservices` |  |
| — | `deviceregistry` |  |
| — | `deviceupdate` |  |
| — | `devops` |  |
| — | `devopsinfrastructure` |  |
| — | `devspaces` |  |
| — | `devtestlabs` |  |
| — | `dfp` |  |
| — | `digitaltwins` |  |
| — | `discovery` |  |
| — | `dnc` |  |
| — | `dnsresolver` |  |
| — | `domainregistration` |  |
| — | `domainservices` |  |
| — | `durabletask` |  |
| — | `dynamicstelemetry` |  |
| — | `dynatrace` |  |
| — | `edge` |  |
| — | `edgemarketplace` |  |
| — | `edgeoperator` |  |
| — | `edgeorder` |  |
| — | `edgeorderpartner` |  |
| — | `edgezones` |  |
| — | `education` |  |
| — | `elastic` |  |
| — | `elasticsan` |  |
| — | `engagementfabric` |  |
| — | `ews` |  |
| — | `extendedlocation` |  |
| — | `fabric` |  |
| — | `fileshares` |  |
| — | `fist` |  |
| — | `fluidrelay` |  |
| — | `gcpconnector` |  |
| — | `github-network` |  |
| — | `graphservicesprod` |  |
| — | `guestconfiguration` |  |
| — | `hanaonazure` |  |
| — | `hardwaresecuritymodules` |  |
| — | `hdinsight` |  |
| — | `healthbot` |  |
| — | `healthcareapis` |  |
| — | `healthdataaiservices` |  |
| — | `help` |  |
| — | `horizondb` |  |
| — | `hybridaks` |  |
| — | `hybridcloud` |  |
| — | `hybridcompute` |  |
| — | `hybridconnectivity` |  |
| — | `hybridkubernetes` |  |
| — | `hybridnetwork` |  |
| — | `imagebuilder` |  |
| — | `imds` |  |
| — | `impact` |  |
| — | `inferenceservice` |  |
| — | `informatica` |  |
| — | `intune` |  |
| — | `iotcentral` |  |
| — | `iothub` |  |
| — | `iotoperations` |  |
| — | `iotoperationsdataprocessor` |  |
| — | `iotoperationsmq` |  |
| — | `iotoperationsorchestrator` |  |
| — | `iotspaces` |  |
| — | `kubernetesconfiguration` |  |
| — | `kubernetesruntime` |  |
| — | `labservices` |  |
| — | `liftrarize` |  |
| — | `liftrcommvault` |  |
| — | `liftrhyperexecute` |  |
| — | `liftrmongodb` |  |
| — | `liftrpinecone` |  |
| — | `liftrqumulo` |  |
| — | `liftrweightsandbiases` |  |
| — | `loadtestservice` |  |
| — | `logic` |  |
| — | `m365securityandcompliance` |  |
| — | `machinelearning` |  |
| — | `machinelearningservices` |  |
| — | `maintenance` |  |
| — | `managednetwork` |  |
| — | `managednetworkfabric` |  |
| — | `managedoperations` |  |
| — | `managedservices` |  |
| — | `management` |  |
| — | `managementpartner` |  |
| — | `manufacturingplatform` |  |
| — | `maps` |  |
| — | `mariadb` |  |
| — | `marketplace` |  |
| — | `marketplacecatalog` |  |
| — | `marketplacenotifications` |  |
| — | `marketplaceordering` |  |
| — | `migrate` |  |
| — | `migrateprojects` |  |
| — | `mission` |  |
| — | `mongocluster` |  |
| — | `monitoringservice` |  |
| — | `mysqldiscovery` |  |
| — | `napster` |  |
| — | `netapp` |  |
| — | `networkcloud` |  |
| — | `networkfunction` |  |
| — | `newrelic` |  |
| — | `nginx` |  |
| — | `oep` |  |
| — | `offazurespringboot` |  |
| — | `onlineexperimentation` |  |
| — | `operationsmanagement` |  |
| — | `oracle` |  |
| — | `orbital` |  |
| — | `orbitalplanetarycomputer` |  |
| — | `paloaltonetworks` |  |
| — | `peering` |  |
| — | `platformvalidation` |  |
| — | `playwrighttesting` |  |
| — | `policyinsights` |  |
| — | `portal` |  |
| — | `portalservices` |  |
| — | `postgresqlhsc` |  |
| — | `powerbidedicated` |  |
| — | `powerbiembedded` |  |
| — | `powerbiprivatelinks` |  |
| — | `powerplatform` |  |
| — | `privatetrafficmanager` |  |
| — | `professionalservice` |  |
| — | `programenrollment` |  |
| — | `programmableconnectivity` |  |
| — | `providerhub` |  |
| — | `purestorage` |  |
| — | `purview` |  |
| — | `purviewdatagovernace` |  |
| — | `purviewdatagovernance` |  |
| — | `purviewpolicy` |  |
| — | `quantum` |  |
| — | `quota` |  |
| — | `recommendationsservice` |  |
| — | `recoveryservices` |  |
| — | `recoveryservicesbackup` |  |
| — | `recoveryservicesdatareplication` |  |
| — | `recoveryservicessiterecovery` |  |
| — | `redhatopenshift` |  |
| — | `redisenterprise` |  |
| — | `relationships` |  |
| — | `relay` |  |
| — | `reservations` |  |
| — | `resourceconnector` |  |
| — | `resourcegraph` |  |
| — | `resourcehealth` |  |
| — | `resourcemover` |  |
| — | `resources` |  |
| — | `riskiq` |  |
| — | `saas` |  |
| — | `scheduler` |  |
| — | `schemaregistry` |  |
| — | `scom` |  |
| — | `scvmm` |  |
| — | `security` |  |
| — | `securityandcompliance` |  |
| — | `securityinsights` |  |
| — | `serialconsole` |  |
| — | `service-map` |  |
| — | `servicefabricmanagedclusters` |  |
| — | `servicefabricmesh` |  |
| — | `servicelinker` |  |
| — | `servicenetworking` |  |
| — | `softwareplan` |  |
| — | `solutions` |  |
| — | `sovereign` |  |
| — | `sphere` |  |
| — | `splitio` |  |
| — | `sqlvirtualmachine` |  |
| — | `standbypool` |  |
| — | `storageactions` |  |
| — | `storagecache` |  |
| — | `storagediscovery` |  |
| — | `storageimportexport` |  |
| — | `storagemover` |  |
| — | `storagepool` |  |
| — | `storagesync` |  |
| — | `streamanalytics` |  |
| — | `subscription` |  |
| — | `support` |  |
| — | `syntex` |  |
| — | `terraform` |  |
| — | `testbase` |  |
| — | `timeseriesinsights` |  |
| — | `trafficmanager` |  |
| — | `translation` |  |
| — | `verifiedid` |  |
| — | `vi` |  |
| — | `vmware` |  |
| — | `vmwarecloudsimple` |  |
| — | `webpubsub` |  |
| — | `widget` |  |
| — | `windowsesu` |  |
| — | `windowsiot` |  |
| — | `workloadmonitor` |  |
| — | `workloads` |  |

</details>

## How to read this page

- **Stages:** 📋 Queued → 🛠 Building → 🔍 In gate → 🚀 Releasing → released
- **A service goes live only when the gate passes:** engine, native SDK/CLI, console offline + Nano, Java/Go/CLI/Playwright tests, cheap licensed backend, hourly + upstream registration
- **Console parts:** service page, create, resource detail and each detail tab
  - ✅ live = real data from the API
  - 🟡 partial = real but some fields blank
  - ⬜ static = hard-coded or generic text
  - ❌ unimplemented = errors, 404/501, empty
- **Console live `6/12 · 5/12`:** 6 of 12 parts live offline, 5 of 12 in Nano
- **Backends:** [rules and defaults](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/expansion/backends.json)
- **Links:** [backlog](https://github.com/vyomi-cloud/appliance/issues?q=label%3Anew-service) · [expansion runs](https://github.com/vyomi-cloud/appliance/actions/workflows/expansion-agent.yml) · [run log](https://github.com/vyomi-cloud/appliance/tree/expansion-state) · [hourly report](https://github.com/vyomi-cloud/appliance/tree/conformance-report) · [upstream watcher](https://github.com/vyomi-cloud/appliance/tree/upstream-state) · [full catalog](https://github.com/vyomi-cloud/appliance/blob/main/docs/expansion/CLOUD-CATALOG.md)
