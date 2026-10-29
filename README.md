# Vyomi service pipeline

_Updated 2026-10-29 05:32 UTC · refreshes after every pipeline run_

## At a glance

- **Released:** 52 services (AWS 18 · GCP 16 · Azure 18) of 1,068 the clouds publish
- **Building now:** Amazon Cognito Identity Provider (AWS, 18/18 checks), Amazon EC2 Container Service (AWS, 19/19 checks), Amazon Elastic Container Registry (AWS, 20/20 checks), Amazon ElastiCache (AWS, 20/20 checks), Amazon Kinesis (AWS, 17/18 checks), Amazon Route 53 (AWS, 20/20 checks), Amazon Simple Email Service (AWS, 17/18 checks), Amazon Simple Notification Service (AWS, 17/18 checks), AWS CloudFormation (AWS, 20/20 checks), AWS Security Token Service (AWS, 18/18 checks), Artifact Registry API (GCP, 17/18 checks), BigQuery API (GCP, 17/18 checks), Cloud DNS API (GCP, 17/18 checks), Cloud Logging API (GCP, 17/18 checks), Cloud Monitoring API (GCP, 17/18 checks), Cloud Run Admin API (GCP, 19/19 checks), Cloud Tasks API (GCP, 17/18 checks), Workflows API (GCP, 17/18 checks), applicationinsights (Azure, 16/17 checks), containerregistry (Azure, 20/20 checks), containerservice (Azure, 16/17 checks), eventhub (Azure, 16/17 checks), msi (Azure, 17/17 checks), redis (Azure, 20/20 checks)
- **In the gate / releasing:** nothing
- **Queued:** 41 services (P1 first, then P2)
- **Consoles really implemented:** offline 59% · Nano 70%
- **Hourly tests:** 115 of 123 suites passing (run 03:56 UTC)
- **Upstream watch:** 46 open changes from the real clouds to adopt

## By cloud

| Cloud | Released | Building | In gate | Queued | Console live (offline · Nano) |
|---|---|---|---|---|---|
| AWS | 18 | 10 | 0 | 17 | 51% · 68% |
| GCP | 16 | 8 | 0 | 12 | 47% · 66% |
| Azure | 18 | 6 | 0 | 12 | 75% · 75% |

## In progress

| Service | Cloud | Stage | Checks | Real backend | Built with | Still missing |
|---|---|---|---|---|---|---|
| Amazon Cognito Identity Provider [#53](https://github.com/vyomi-cloud/appliance/issues/53) | AWS | 🛠 Building | 18/18 | in-process | in-process | — |
| Amazon EC2 Container Service [#55](https://github.com/vyomi-cloud/appliance/issues/55) | AWS | 🛠 Building | 19/19 | docker · Pro · + caddy gateway | docker · Pro | — |
| Amazon Elastic Container Registry [#54](https://github.com/vyomi-cloud/appliance/issues/54) | AWS | 🛠 Building | 20/20 | registry · Lite | registry · 10 MB · Lite | — |
| Amazon ElastiCache [#56](https://github.com/vyomi-cloud/appliance/issues/56) | AWS | 🛠 Building | 20/20 | valkey · Lite | valkey · 8 MB · Lite | — |
| Amazon Kinesis [#58](https://github.com/vyomi-cloud/appliance/issues/58) | AWS | 🛠 Building | 17/18 | nats · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Amazon Route 53 [#60](https://github.com/vyomi-cloud/appliance/issues/60) | AWS | 🛠 Building | 20/20 | coredns · Lite | coredns · 15 MB · Lite | — |
| Amazon Simple Email Service [#61](https://github.com/vyomi-cloud/appliance/issues/61) | AWS | 🛠 Building | 17/18 | mailpit · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Amazon Simple Notification Service [#62](https://github.com/vyomi-cloud/appliance/issues/62) | AWS | 🛠 Building | 17/18 | nats · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| AWS CloudFormation [#51](https://github.com/vyomi-cloud/appliance/issues/51) | AWS | 🛠 Building | 20/20 | iac-engine · in-process | in-process | — |
| AWS Security Token Service [#65](https://github.com/vyomi-cloud/appliance/issues/65) | AWS | 🛠 Building | 18/18 | in-process | in-process | — |
| Artifact Registry API [#66](https://github.com/vyomi-cloud/appliance/issues/66) | GCP | 🛠 Building | 17/18 | registry · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| BigQuery API [#67](https://github.com/vyomi-cloud/appliance/issues/67) | GCP | 🛠 Building | 17/18 | duckdb · in-process | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud DNS API [#71](https://github.com/vyomi-cloud/appliance/issues/71) | GCP | 🛠 Building | 17/18 | coredns · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud Logging API [#73](https://github.com/vyomi-cloud/appliance/issues/73) | GCP | 🛠 Building | 17/18 | logstore · in-process · + fluent-bit agent | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud Monitoring API [#74](https://github.com/vyomi-cloud/appliance/issues/74) | GCP | 🛠 Building | 17/18 | victoriametrics · Lite · + vmalert agent | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud Run Admin API [#76](https://github.com/vyomi-cloud/appliance/issues/76) | GCP | 🛠 Building | 19/19 | docker · Pro · + caddy gateway | docker · Pro | — |
| Cloud Tasks API [#69](https://github.com/vyomi-cloud/appliance/issues/69) | GCP | 🛠 Building | 17/18 | nats · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Workflows API [#77](https://github.com/vyomi-cloud/appliance/issues/77) | GCP | 🛠 Building | 17/18 | workflow-engine · in-process · + temporal engine | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| applicationinsights [#80](https://github.com/vyomi-cloud/appliance/issues/80) | Azure | 🛠 Building | 16/17 | logstore · in-process · + fluent-bit agent | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| containerregistry [#82](https://github.com/vyomi-cloud/appliance/issues/82) | Azure | 🛠 Building | 20/20 | registry · Lite | registry · 10 MB · Lite | — |
| containerservice [#83](https://github.com/vyomi-cloud/appliance/issues/83) | Azure | 🛠 Building | 16/17 | k3s · Max | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| eventhub [#85](https://github.com/vyomi-cloud/appliance/issues/85) | Azure | 🛠 Building | 16/17 | nats · Lite · + amqp protocol | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| msi [#87](https://github.com/vyomi-cloud/appliance/issues/87) | Azure | 🛠 Building | 17/17 | in-process | in-process | — |
| redis [#89](https://github.com/vyomi-cloud/appliance/issues/89) | Azure | 🛠 Building | 20/20 | valkey · Lite | valkey · 8 MB · Lite | — |

## Released services

- **Console live:** parts of the console that are really implemented, offline · Nano
- **UI issues:** problems the latest hourly crawl found, offline · Nano
- **Real backend:** what the service should run on ([backends.json](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/expansion/backends.json)) · **Wired today:** ✅ real · 🟡 partial · ⚪ management API only

### AWS

| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|---|---|
| EC2 | — | not audited | 🧩 5/13 · 🧩 5/13 | 0 · 5 | ⚠️ 3 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+ec2) | before gate |
| S3 | — | not audited | 🧩 6/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| IAM | — | not audited | 🧩 7/11 · 🧩 3/11 | 0 · 0 | ✅ watched | before gate |
| RDS | — | not audited | 🧩 8/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| DynamoDB | — | not audited | 🧩 4/13 · 🧩 10/13 | 1 · 1 | ✅ watched | before gate |
| SQS | — | not audited | 🧩 5/13 · 🧩 8/13 | 1 · 1 | ✅ watched | before gate |
| Lambda | — | not audited | 🧩 6/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| API Gateway | caddy · Lite | not audited | 🧩 8/13 · 🧩 10/13 | 0 · 2 | ✅ watched | before gate |
| VPC | — | not audited | 🧩 7/13 · 🧩 9/13 | 0 · 4 | ⚠️ 3 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+ec2) | before gate |
| EventBridge | nats · Lite | 🟡 rules match and deliver to SQS only; Lambda/HTTP/other targets not delivered | 🧩 6/13 · 🧩 10/13 | 0 · 1 | ✅ watched | before gate |
| Secrets Manager | — | not audited | 🧩 4/13 · 🧩 9/13 | 2 · 2 | ✅ watched | before gate |
| KMS | — | not audited | 🧩 5/13 · 🧩 11/13 | 0 · 0 | ✅ watched | before gate |
| CloudWatch Logs | logstore · in-process · + fluent-bit agent | ✅ in-process engine, SQLite store; filter + Insights queries | 🧩 10/11 · 🧩 10/11 | 0 · 0 | ✅ watched | [v3.0.11](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.11) |
| Elastic Load Balancing | caddy · Lite | ⚪ no traffic forwarded (Caddy not wired) | 🧩 7/8 · 🧩 7/8 | 0 · 0 | ✅ watched | [v3.0.10](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.10) |
| Systems Manager | in-process | 🟡 Parameter Store real; Run Command reports Success without running | 🧩 5/10 · 🧩 5/10 | 1 · 1 | ✅ watched | [v3.0.12](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.12) |
| Step Functions | workflow-engine · in-process · + temporal engine | ✅ ASL interpreter runs executions and calls Lambda; Wait doesn't sleep | 🧩 8/12 · 🧩 8/12 | 0 · 0 | ✅ watched | [v3.0.13](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.13) |
| API Gateway V2 | caddy · Lite | not audited | — | – · – | ✅ watched | [v3.0.25](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.25) |
| Amazon CloudWatch | victoriametrics · Lite · + vmalert agent | not audited | — | – · – | ✅ watched | [v3.0.26](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.26) |

### GCP

| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|---|---|
| Compute Engine | — | not audited | 🧩 5/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Storage | — | not audited | 🧩 7/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Cloud SQL | — | not audited | 🧩 5/13 · 🧩 9/13 | 0 · 0 | ⚠️ 26 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+sqladmin/v1beta4) | before gate |
| Pub/Sub | — | not audited | 🧩 5/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Firestore | — | not audited | 🧩 5/13 · 🧩 5/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Functions | — | not audited | 🧩 5/13 · 🧩 7/13 | 0 · 0 | ✅ watched | before gate |
| API Gateway | caddy · Lite | not audited | 🧩 6/12 · 🧩 8/12 | 0 · 2 | ✅ watched | before gate |
| VPC Network | — | not audited | 🧩 4/13 · 🧩 6/13 | 0 · 0 | ✅ watched | before gate |
| IAM & Admin | — | not audited | 🧩 4/9 · 🧩 8/9 | 0 · 0 | ✅ watched | before gate |
| Eventarc | — | not audited | 🧩 5/12 · 🧩 9/12 | 0 · 0 | ✅ watched | before gate |
| Secret Manager | — | not audited | 🧩 5/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Cloud KMS | — | not audited | 🧩 6/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Scheduler | in-process | 🟡 cron fires only on reads; HTTP targets not sent (#147-#149) | 🧩 8/11 · 🧩 9/11 | 0 · 0 | ✅ watched | [v3.0.14](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.14) |
| Kubernetes Engine | k3s · Max | ⚪ no Kubernetes API; kubectl can't connect (k3s not wired) | 🧩 7/11 · 🧩 8/11 | 0 · 0 | ✅ watched | [v3.0.15](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.15) |
| IAM Service Account Credentials | in-process | ✅ real RS256-signed tokens, JWTs and blobs | 🧩 7/11 · 🧩 8/11 | 0 · 0 | ✅ watched | [v3.0.16](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.16) |
| Memorystore for Redis | valkey · Lite | 🟡 one shared 64 MB Valkey; port not published, no per-instance AUTH | 🧩 9/11 · 🧩 8/11 | 0 · 0 | ✅ watched | [v3.0.17](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.17) |

### Azure

| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|---|---|
| Virtual Machines | — | not audited | 🧩 10/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Storage accounts | — | not audited | 🧩 10/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| SQL servers | — | not audited | 🧩 9/13 · 🧩 8/13 | 0 · 0 | ✅ watched | before gate |
| Service Bus | messaging-core · in-process · + nats agent · + amqp protocol | 🟡 REST management + messaging only; native SDKs need AMQP (in PRs #35-#45, not merged) | 🧩 9/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Cosmos DB | — | not audited | 🧩 9/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| Function apps | — | not audited | 🧩 7/13 · 🧩 7/13 | 0 · 0 | ✅ watched | before gate |
| API Management | caddy · Lite | not audited | 🧩 9/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Virtual networks | — | not audited | 🧩 9/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| Network Security Group | — | not audited | 🧩 9/11 · 🧩 10/11 | 0 · 0 | ✅ watched | before gate |
| Event Grid topics | — | not audited | 🧩 9/13 · 🧩 9/13 | 0 · 0 | ✅ watched | before gate |
| Key vaults | — | not audited | 🧩 10/13 · 🧩 10/13 | 0 · 0 | ✅ watched | before gate |
| Entra ID / RBAC | — | not audited | 🧩 5/6 · 🧩 5/6 | 0 · 0 | ✅ watched | before gate |
| Container Apps | docker · Pro · + caddy gateway | 🟡 real containers on Pro/Max only; no ingress URL | 🧩 8/13 · 🧩 9/13 | 0 · 0 | ✅ watched | [v3.0.18](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.18) |
| App Configuration | in-process | ✅ real key-value data plane | 🧩 11/13 · 🧩 11/13 | 0 · 0 | ✅ watched | [v3.0.19](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.19) |
| Azure AI services | ollama · Max | ⚪ no model inference (Ollama not wired) | 🧩 11/13 · 🧩 10/13 | 0 · 0 | ✅ watched | [v3.0.20](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.20) |
| DNS zones | coredns · Lite | ⚪ no DNS server answers (CoreDNS not wired) | 🧩 9/13 · 🧩 10/13 | 0 · 0 | ✅ watched | [v3.0.21](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.21) |
| Monitor alerts | victoriametrics · Lite · + vmalert agent | ⚪ alert rules stored, never evaluated or fired (vmalert not wired) | 🧩 12/13 · ✅ 13/13 | 0 · 0 | ✅ watched | [v3.0.22](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.22) |
| Log Analytics | logstore · in-process · + fluent-bit agent | ⚪ workspaces only; no ingestion or KQL queries | 🧩 11/13 · 🧩 11/13 | 0 · 0 | ✅ watched | [v3.0.23](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.23) |

- **Nano ↔ offline gaps:** Blob containers (Nano-only), Cosmos databases (Nano-only), Key Vault keys (Nano-only), Key Vault secrets (Nano-only), Storage queues (Nano-only), azure_subresource_core (Nano-only)

## Up next

<details><summary><b>AWS</b> — 17 queued</summary>

| Service | Priority | Issue | Real backend |
|---|---|---|---|
| Amazon Athena | P2 | not filed | duckdb · in-process |
| Amazon Bedrock Runtime | P2 | not filed | ollama · Max |
| Amazon DynamoDB Streams | P2 | not filed | in-process |
| Amazon Elastic File System | P2 | not filed | in-process |
| Amazon EventBridge Scheduler | P2 | not filed | in-process |
| Amazon Kinesis Firehose | P2 | not filed | nats · Lite |
| Amazon OpenSearch Service | P2 | not filed | opensearch · Max |
| AmazonMQ | P2 | not filed | rabbitmq · Pro · + amqp protocol |
| Auto Scaling | P2 | not filed | in-process |
| AWS AppSync | P2 | not filed | in-process |
| AWS Backup | P2 | not filed | in-process |
| AWS Batch | P2 | not filed | docker · Pro |
| AWS Certificate Manager | P2 | not filed | in-process |
| AWS CodeBuild | P2 | not filed | docker · Pro |
| AWS Glue | P2 | not filed | duckdb · in-process |
| AWS X-Ray | P2 | not filed | in-process |
| Managed Streaming for Kafka | P2 | not filed | kafka · Max |

</details>

<details><summary><b>GCP</b> — 12 queued</summary>

| Service | Priority | Issue | Real backend |
|---|---|---|---|
| Agent Platform API | P2 | not filed | ollama · Max |
| Batch API | P2 | not filed | docker · Pro |
| Certificate Manager API | P2 | not filed | in-process |
| Cloud Bigtable Admin API | P2 | not filed | in-process |
| Cloud Composer API | P2 | not filed | in-process |
| Cloud Dataproc API | P2 | not filed | in-process |
| Cloud Datastore API | P2 | not filed | in-process |
| Cloud Filestore API | P2 | not filed | in-process |
| Cloud Spanner API | P2 | not filed | spanner-emulator · Pro |
| Cloud Trace API | P2 | not filed | in-process |
| Cloud Translation API | P2 | not filed | in-process |
| Dataflow API | P2 | not filed | in-process |

</details>

<details><summary><b>Azure</b> — 12 queued</summary>

| Service | Priority | Issue | Real backend |
|---|---|---|---|
| batch | P2 | not filed | docker · Pro |
| cdn | P2 | not filed | caddy · Lite |
| datafactory | P2 | not filed | in-process |
| frontdoor | P2 | not filed | caddy · Lite |
| mysql | P2 | not filed | mariadb · Pro |
| notificationhubs | P2 | not filed | in-process |
| postgresql | P2 | not filed | postgres · Lite |
| privatedns | P2 | not filed | coredns · Lite |
| search | P2 | not filed | in-process |
| servicefabric | P2 | not filed | in-process |
| signalr | P2 | not filed | in-process |
| synapse | P2 | not filed | duckdb · in-process |

</details>

## Platform features (highest priority)

Built by the agent ahead of everything else, then **reviewed and merged by a person**.

| Feature | Stage | Review PR |
|---|---|---|
| Automatic issue reporting from Nano, offline and sandboxes (user's GitHub account, bot fallback) [#187](https://github.com/vyomi-cloud/appliance/issues/187) | 👀 In review | [PR #189](https://github.com/vyomi-cloud/appliance/pull/189) |

## Backend upgrades

Existing work rebuilt onto main by the agent, then **reviewed and merged by a person** (never auto-merged).

| Upgrade | Source PRs | Stage | Review PR |
|---|---|---|---|
| Azure Service Bus over AMQP 1.0 (Rohith's stack #34→#45) [#181](https://github.com/vyomi-cloud/appliance/issues/181) | [#34](https://github.com/vyomi-cloud/appliance/pull/34) → [#35](https://github.com/vyomi-cloud/appliance/pull/35) → [#37](https://github.com/vyomi-cloud/appliance/pull/37) → [#38](https://github.com/vyomi-cloud/appliance/pull/38) → [#39](https://github.com/vyomi-cloud/appliance/pull/39) → [#40](https://github.com/vyomi-cloud/appliance/pull/40) → [#45](https://github.com/vyomi-cloud/appliance/pull/45) | 👀 In review | [PR #188](https://github.com/vyomi-cloud/appliance/pull/188) |
| Siftly: app profiles, Azure Blob fidelity, Postgres 16 + pgvector (Rohith's stack #43→#46) [#182](https://github.com/vyomi-cloud/appliance/issues/182) | [#43](https://github.com/vyomi-cloud/appliance/pull/43) → [#44](https://github.com/vyomi-cloud/appliance/pull/44) → [#46](https://github.com/vyomi-cloud/appliance/pull/46) | 👀 In review | [PR #194](https://github.com/vyomi-cloud/appliance/pull/194) |

## Real backends and vyomi-libs

Every service must run on a real backend, so a created resource really works. Shared engines become `vyomi-<lib>` packages, one per capability across all three clouds.

| Lib | Cloud services | Real backends it drives | Nano | Phase |
|---|---|---|---|---|
| **vyomi-iam** | Shared IAM enforcement (#172-#175), AWS STS, GCP IAM Credentials, Azure managed-identity tokens | in-process | yes | 3 |
| **vyomi-identity** | Cognito user + identity pools, GCP Identity Platform, Entra External ID / B2C | in-process | yes | 3 |
| **vyomi-workflow** | Step Functions, GCP Workflows, Logic Apps | temporal, workflow-engine | yes | 1 |
| **vyomi-iac** | CloudFormation + Cloud Control, ARM/Bicep, Deployment Manager, Infrastructure Manager | iac-engine, opentofu | in-process part | 5 |
| **vyomi-logs** | CloudWatch Logs, Cloud Logging, Log Analytics, Application Insights | fluent-bit, logstore, victorialogs | yes | 2 |
| **vyomi-metrics** | CloudWatch metrics + alarms, Cloud Monitoring, Azure Monitor, managed Prometheus | victoriametrics, vmalert | subset | 5 |
| **vyomi-messaging** | Service Bus, SNS, EventBridge, Cloud Tasks, Kinesis, Event Hubs, Cloud Scheduler, Amazon MQ; later SQS and Pub/Sub | amqp, kafka, messaging-core, nats, rabbitmq | subset | 2 |
| **vyomi-gateway** | API Gateway v1/v2, ELB/ALB, GCP API Gateway, API Management, Front Door | caddy | control plane | 4 |
| **vyomi-containers** | Cloud Run, Container Apps, App Runner, ECS | docker, knative | control plane | 5 |
| **vyomi-kubernetes** | GKE, AKS, EKS | k3s | control plane | 5 |
| **vyomi-mail** | SES (v1 receipt rules + v2), alert email | mailpit | control plane | 4 |
| **vyomi-dns** | Route 53, Cloud DNS, Azure DNS | coredns | control plane | 4 |
| **vyomi-cache** | ElastiCache, Memorystore, Azure Cache for Redis | valkey | control plane | 4 |
| **vyomi-registry** | ECR, Artifact Registry, ACR | registry | control plane | 4 |
| **vyomi-ai** | Bedrock, Vertex AI, Azure AI services | ollama | control plane | 5 |

<details><summary><b>Shared backends</b> — what each one is and what it serves</summary>

| Backend | Kind | Tier | Idle RAM | Lib | Serves |
|---|---|---|---|---|---|
| valkey | container | Lite | 8 MB | vyomi-cache | aws:elasticache, azure:redis, gcp:redis/v1 |
| registry | container | Lite | 10 MB | vyomi-registry | aws:ecr, azure:containerregistry, gcp:artifactregistry/v1 |
| coredns | container | Lite | 15 MB | vyomi-dns | aws:route53, azure:dns, azure:privatedns, gcp:dns/v1 |
| mailpit | container | Lite | 15 MB | vyomi-mail | aws:ses, aws:sesv2 |
| messaging-core | in-process | All | 0 MB | vyomi-messaging | azure:Microsoft.ServiceBus, azure:servicebus |
| nats | container | Lite | 10 MB | vyomi-messaging | aws:events, aws:firehose, aws:kinesis, aws:sns, azure:Microsoft.ServiceBus, azure:eventhub, azure:servicebus, gcp:cloudtasks/v2 |
| caddy | gateway | Lite | 15 MB | vyomi-gateway | aws:apigateway, aws:apigatewaymanagementapi, aws:apigatewayv2, aws:apprunner, aws:ecs, aws:elbv2, azure:Microsoft.ApiManagement, azure:apimanagement, azure:app, azure:cdn, azure:frontdoor, gcp:apigateway/v1, gcp:run/v2 |
| workflow-engine | in-process | All | 0 MB | vyomi-workflow | aws:stepfunctions, azure:logic, gcp:workflows/v1 |
| iac-engine | in-process | All | 0 MB | vyomi-iac | aws:cloudcontrol, aws:cloudformation, azure:resources, gcp:deploymentmanager/v2 |
| logstore | in-process | All | 0 MB | vyomi-logs | aws:logs, azure:applicationinsights, azure:operationalinsights, gcp:logging/v2 |
| duckdb | in-process | All | — MB | — | aws:athena, aws:glue, azure:synapse, gcp:bigquery/v2 |
| docker | substrate | Pro | — MB | vyomi-containers | aws:apprunner, aws:batch, aws:codebuild, aws:ecs, azure:app, azure:batch, gcp:batch/v1, gcp:cloudbuild/v1, gcp:run/v2 |
| k3s | container | Max | 500 MB | vyomi-kubernetes | aws:eks, azure:containerservice, gcp:container/v1 |
| postgres | container | Lite | 40 MB | — | azure:postgresql |
| mariadb | container | Pro | 90 MB | — | azure:mysql |
| kafka | container | Max | 400 MB | vyomi-messaging | aws:kafka |
| opensearch | container | Max | 700 MB | — | aws:opensearch |
| rabbitmq | container | Pro | 100 MB | vyomi-messaging | aws:mq |
| spanner-emulator | container | Pro | 150 MB | — | gcp:spanner/v1 |
| ollama | container | Max | 50 MB | vyomi-ai | aws:bedrock-runtime, azure:cognitiveservices, gcp:aiplatform/v1 |
| fluent-bit | agent | Lite | 5 MB | vyomi-logs | aws:logs, azure:applicationinsights, azure:operationalinsights, gcp:logging/v2 |
| victorialogs | optional | Max | 30 MB | vyomi-logs | aws:logs, azure:applicationinsights, azure:operationalinsights, gcp:logging/v2 |
| victoriametrics | container | Lite | 40 MB | vyomi-metrics | aws:amp, aws:cloudwatch, azure:monitor, gcp:monitoring/v3 |
| vmalert | agent | Lite | 10 MB | vyomi-metrics | aws:amp, aws:cloudwatch, azure:monitor, gcp:monitoring/v3 |
| knative | optional | Max | 400 MB | vyomi-containers | azure:app, gcp:run/v2 |
| temporal | engine | Pro | 150 MB | vyomi-workflow | aws:stepfunctions, azure:logic, gcp:workflows/v1 |
| opentofu | container | Lite | 0 MB | vyomi-iac | gcp:config/v1 |
| amqp | protocol | All | 0 MB | vyomi-messaging | aws:mq, azure:Microsoft.ServiceBus, azure:eventhub, azure:servicebus |

</details>

<details><summary><b>vyomi-messaging layers</b> — one core, a protocol adapter per wire format</summary>

| Layer | Serves |
|---|---|
| Protocol adapter: AMQP 1.0 (Rohith's stack #34-#45) | Azure Service Bus, Event Hubs; Amazon MQ for ActiveMQ |
| Protocol adapter: HTTP Query / JSON | SQS, SNS, Kinesis, EventBridge |
| Protocol adapter: HTTP / gRPC | GCP Pub/Sub, Cloud Tasks |
| Protocol adapter: Kafka (later) | Event Hubs Kafka endpoint, Amazon MSK |
| Shared core: queues, topics, subscriptions, leases/locks, redelivery, DLQ, ordering, dedup | all of the above |
| Durable delivery: NATS JetStream | all of the above |

AMQP isn't the common protocol: only Azure Service Bus/Event Hubs and Amazon MQ (ActiveMQ) speak it; AWS SQS/SNS/Kinesis and GCP Pub/Sub SDKs use HTTP or gRPC. Amazon MQ for RabbitMQ (AMQP 0-9-1) keeps real RabbitMQ.

</details>

<details><summary><b>vyomi-libs design</b> — shape, Nano wheels, contract, release, migration</summary>

- **Shape:** one Python package per lib, three ways to run it: a **core wheel** (`vyomi-<lib>`, pure `py3-none-any`, no server deps; what Nano loads), a **service image** `vyomi/<lib>:<version>` (core + ASGI server + controller for the open-source backend it drives; multi-arch, pinned), and **embedded mode** (the appliance imports the wheel in-process, for the Free/Lite RAM budgets).
- **Nano gets wheels, not images:** pinned wheels are vendored into the Nano bundle (`wasm/wheels/` → portal `app/nano/wheels/`, same-origin, service-worker cached) and installed with `micropip`, sha256-checked against `libs.lock.json`; never fetched from PyPI at runtime. Each lib's CI also runs its contract tests in Pyodide.
- **Contract v1:** the `dispatch(store, method, path, query, headers, body)` shape today's engines use; context headers from the appliance (`X-Vyomi-Space`, `-Principal`, `-Request-Id`, `-Tier`); each lib owns its storage (with export/import); cross-service calls go back through the front door so IAM applies; one event schema on NATS; `/healthz` `/readyz` `/metrics` `/version`; contract tests every lib must pass.
- **Release:** libs start in this repo under `libs/<lib>/` with their own CODEOWNERS, CI, changelog and tag (`vyomi-logs/v1.4.0` publishes the image, wheel and sdist). The appliance pins versions in `libs.lock.json`; a lib bump is a one-line PR that runs full conformance. A lib can move to its own repo later with no change to the appliance.
- **Runtime:** libs start on demand (`core/backend_provisioner.py`) when a service is first used; the dashboard lists each cloud service with its lib, version and live state, and each lib/backend with its health.
- **Migration:** phase 0 framework (contract, scaffold, release workflow, lock file, Pyodide harness, Nano wheel loader); 1 vyomi-workflow (the Step Functions engine moves unchanged); 2 vyomi-logs + vyomi-messaging (Rohith's Service Bus stack #34-#45 first, gated on Siftly A1-A9 and every SQS suite); 3 vyomi-iam + vyomi-identity; 4 gateway, dns, cache, mail, registry; 5 metrics, iac, containers, kubernetes, ai. The in-process engine stays as the fallback until its lib passes the same tests.
- **Open decisions:** embedded mode on Free/Lite; tiers for heavy backends (k3s, Temporal, Ollama, VictoriaLogs); Azure AI services backend; monorepo first then split; image names; publishing wheels on public PyPI.

</details>

## Details

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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: in-process; chose in-process |
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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: docker; chose docker |
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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: registry; chose registry |
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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: valkey; chose valkey |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: nats; chose in-process |
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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: coredns; chose coredns |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: mailpit; chose in-process |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: nats; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

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
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'name': 'iac-engine'} |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: iac-engine; chose iac-engine |
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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: in-process; chose in-process |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: registry; chose in-process |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: duckdb; chose sqlite |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: coredns; chose in-process |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: logstore; chose in-process |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: victoriametrics; chose in-process |
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
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: docker; chose docker |
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
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: nats; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — Workflows API (GCP)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/gcp_workflows_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/gcp_workflows_core.py |
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
| ✅ | upstream id tracked by the hourly upstream watcher | workflows/v1 |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: workflow-engine; chose in-process |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary>Gate checks — applicationinsights (Azure)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/azure_applicationinsights_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/azure_applicationinsights_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | azure-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | applicationinsights |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: logstore; chose in-process |

</details>

<details><summary>Gate checks — containerregistry (Azure)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/azure_containerregistry_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/azure_containerregistry_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | azure-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | containerregistry |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'registry', 'image': 'registry:2.8.3', 'license': 'Apache-2.0', 'tier': 'lite', 'compose_service': 'vy |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: registry; chose registry |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=Apache-2.0 |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=Apache-2.0 |
| ✅ | backend image is pinned to a version (not latest) | registry:2.8.3 |

</details>

<details><summary>Gate checks — containerservice (Azure)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/azure_containerservice_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/azure_containerservice_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | azure-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | containerservice |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'reason': 'This release is control plane only (clusters, node pools, upgrades, credentials, maintenance, snap |
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: k3s; chose in-process |

</details>

<details><summary>Gate checks — eventhub (Azure)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/azure_eventhub_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/azure_eventhub_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | azure-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | eventhub |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process', 'reason': "Event Hubs' native wire is AMQP 1.0 / Kafka, which no Vyomi tier exposes; the engine keeps the par |
| ❌ | backend is the recommended one, or a different real backend the manifest justifies | recommended: nats; chose in-process |

</details>

<details><summary>Gate checks — msi (Azure)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/azure_msi_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/azure_msi_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | azure-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | msi |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'in-process'} |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: in-process; chose in-process |

</details>

<details><summary>Gate checks — redis (Azure)</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ✅ | manifest status is ready | status=ready |
| ✅ | engine exists in core/ | core/azure_redis_core.py |
| ✅ | Nano copy is byte-identical (wasm/core/) | wasm/core/azure_redis_core.py |
| ✅ | engine listed in wasm/build_cores.py |  |
| ✅ | service in the Nano console catalog (wasm/fixtures) | azure-catalog.json |
| ✅ | Nano console entry is identical to the offline catalog's (build_fixtures.py) |  |
| ✅ | registry entry (pending-release or released) |  |
| ✅ | every manifest suite is registered in the hourly suites.json | missing: [] |
| ✅ | has a offline sdk-java test bed |  |
| ✅ | has a offline sdk-go test bed |  |
| ✅ | has a offline cli test bed |  |
| ✅ | has a offline ui test bed |  |
| ✅ | has a nano ui test bed |  |
| ✅ | upstream id tracked by the hourly upstream watcher | redis |
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'valkey', 'image': 'valkey/valkey:8.0.1-alpine', 'license': 'BSD-3-Clause', 'tier': 'lite', 'compose_s |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: valkey; chose valkey |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=BSD-3-Clause |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=BSD-3-Clause |
| ✅ | backend image is pinned to a version (not latest) | valkey/valkey:8.0.1-alpine |

</details>

<details><summary>Console parts not live yet — AWS (156)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| EC2 | offline | tab: Tags | static |
| EC2 | offline | tab: Details | static |
| EC2 | offline | tab: Status and alarms | static |
| EC2 | offline | tab: Monitoring | unimplemented |
| EC2 | offline | tab: Networking | partial |
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
| SQS | offline | tab: Dead-letter queue | partial |
| SQS | offline | tab: Encryption | static |
| SQS | offline | tab: Access policy | static |
| SQS | offline | tab: Monitoring | static |
| API Gateway | offline | tab: Tags | static |
| API Gateway | offline | tab: Authorizers | static |
| API Gateway | offline | tab: Models | static |
| API Gateway | offline | tab: Deployments | static |
| API Gateway | offline | tab: Resource policy | static |
| EventBridge | offline | tab: Tags | static |
| EventBridge | offline | tab: Rule details | static |
| EventBridge | offline | tab: Targets | static |
| EventBridge | offline | tab: Event pattern | static |
| EventBridge | offline | tab: Dead-letter queue | static |
| EventBridge | offline | tab: Properties | static |
| EventBridge | offline | tab: Permissions | static |
| Step Functions | offline | tab: Tags | static |
| Step Functions | offline | tab: Definition | static |
| Step Functions | offline | tab: Properties | static |
| Step Functions | offline | tab: Monitoring | static |
| VPC | offline | tab: VPC details | unimplemented |
| VPC | offline | tab: NAT gateways | static |
| VPC | offline | tab: Endpoints | static |
| VPC | offline | tab: Security groups | partial |
| VPC | offline | tab: Network ACLs | static |
| VPC | offline | tab: Flow logs | static |
| Elastic Load Balancing | offline | tab: Tags | static |
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
| CloudWatch Logs | offline | tab: Tags | static |
| Systems Manager | offline | tab: Tags | static |
| Systems Manager | offline | tab: Value | static |
| Systems Manager | offline | tab: History | partial |
| Systems Manager | offline | tab: Properties | static |
| Systems Manager | offline | tab: Monitoring | static |
| EC2 | nano | tab: Tags | static |
| EC2 | nano | tab: Details | static |
| EC2 | nano | tab: Status and alarms | static |
| EC2 | nano | tab: Monitoring | unimplemented |
| EC2 | nano | tab: Networking | partial |
| EC2 | nano | tab: Security | partial |
| EC2 | nano | tab: Storage | static |
| EC2 | nano | tab: Connect | unimplemented |
| Lambda | nano | tab: Tags | static |
| Lambda | nano | tab: Code | static |
| Lambda | nano | tab: Test | static |
| S3 | nano | tab: Tags | static |
| S3 | nano | tab: Bucket Versioning | static |
| S3 | nano | tab: Default encryption | unimplemented |
| S3 | nano | tab: Block Public Access | unimplemented |
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
| SQS | nano | tab: Dead-letter queue | partial |
| SQS | nano | tab: Monitoring | static |
| API Gateway | nano | tab: Tags | static |
| API Gateway | nano | tab: Resources | unimplemented |
| API Gateway | nano | tab: Stages | unimplemented |
| EventBridge | nano | tab: Tags | static |
| EventBridge | nano | tab: Rule details | static |
| EventBridge | nano | tab: Properties | static |
| Step Functions | nano | tab: Tags | static |
| Step Functions | nano | tab: Definition | static |
| Step Functions | nano | tab: Properties | static |
| Step Functions | nano | tab: Monitoring | static |
| VPC | nano | tab: VPC details | unimplemented |
| VPC | nano | tab: Subnets | unimplemented |
| VPC | nano | tab: Route tables | unimplemented |
| VPC | nano | tab: Internet gateways | unimplemented |
| Elastic Load Balancing | nano | tab: Tags | static |
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
| CloudWatch Logs | nano | tab: Tags | static |
| Systems Manager | nano | tab: Tags | static |
| Systems Manager | nano | tab: Value | static |
| Systems Manager | nano | tab: History | partial |
| Systems Manager | nano | tab: Properties | static |
| Systems Manager | nano | tab: Monitoring | static |

</details>

<details><summary>Console parts not live yet — GCP (166)</summary>

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
| Kubernetes Engine | offline | tab: Details | static |
| Kubernetes Engine | offline | tab: Networking | static |
| Kubernetes Engine | offline | tab: Observability | static |
| Kubernetes Engine | offline | tab: Metrics | static |
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
| Cloud SQL | offline | tab: Connectivity | static |
| Cloud SQL | offline | tab: Flags | static |
| Firestore | offline | tab: Activity | static |
| Firestore | offline | tab: Permissions | static |
| Firestore | offline | tab: Labels | static |
| Firestore | offline | tab: Data | static |
| Firestore | offline | tab: Query builder | static |
| Firestore | offline | tab: Indexes | static |
| Firestore | offline | tab: Security rules | static |
| Firestore | offline | tab: Import / Export | static |
| Memorystore for Redis | offline | tab: Configuration | static |
| Memorystore for Redis | offline | tab: Metrics | static |
| VPC Network | offline | tab: Activity | static |
| VPC Network | offline | tab: Permissions | static |
| VPC Network | offline | tab: Labels | static |
| VPC Network | offline | tab: Subnets | static |
| VPC Network | offline | tab: Firewall rules | static |
| VPC Network | offline | tab: Routes | static |
| VPC Network | offline | tab: VPC peering | static |
| VPC Network | offline | tab: Properties | static |
| VPC Network | offline | tab: Network metrics | static |
| Pub/Sub | offline | tab: Activity | static |
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
| API Gateway | offline | tab: Metrics | static |
| API Gateway | offline | tab: Logs | static |
| Eventarc | offline | tab: Activity | static |
| Eventarc | offline | tab: Permissions | static |
| Eventarc | offline | tab: Labels | static |
| Eventarc | offline | tab: Event matching | static |
| Eventarc | offline | tab: Destination | static |
| Eventarc | offline | tab: Metrics | static |
| Eventarc | offline | tab: Logs | static |
| Cloud Scheduler | offline | tab: Last execution | static |
| Cloud Scheduler | offline | tab: Retry policy | static |
| Cloud Scheduler | offline | tab: Metrics | static |
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
| IAM Service Account Credentials | offline | tab: Credential | static |
| IAM Service Account Credentials | offline | tab: Delegation | static |
| IAM Service Account Credentials | offline | tab: Signing | static |
| IAM Service Account Credentials | offline | tab: Metrics | static |
| Compute Engine | nano | tab: Permissions | static |
| Compute Engine | nano | tab: Labels | static |
| Compute Engine | nano | tab: Networking | static |
| Compute Engine | nano | tab: Metadata | static |
| Cloud Functions | nano | tab: Permissions | static |
| Cloud Functions | nano | tab: Labels | static |
| Cloud Functions | nano | tab: Source | static |
| Cloud Functions | nano | tab: Trigger | static |
| Cloud Functions | nano | tab: Variables | static |
| Cloud Functions | nano | tab: Networking | static |
| Kubernetes Engine | nano | tab: Details | static |
| Kubernetes Engine | nano | tab: Networking | static |
| Kubernetes Engine | nano | tab: Observability | static |
| Cloud Storage | nano | tab: Permissions | static |
| Cloud Storage | nano | tab: Labels | static |
| Cloud Storage | nano | tab: Lifecycle | static |
| Cloud Storage | nano | tab: Retention | static |
| Cloud SQL | nano | tab: Permissions | static |
| Cloud SQL | nano | tab: Labels | static |
| Cloud SQL | nano | tab: Connectivity | static |
| Cloud SQL | nano | tab: Flags | static |
| Firestore | nano | tab: Overview | static |
| Firestore | nano | tab: Labels | static |
| Firestore | nano | tab: Data | static |
| Firestore | nano | tab: Query builder | static |
| Firestore | nano | tab: Indexes | static |
| Firestore | nano | tab: Security rules | static |
| Firestore | nano | tab: Import / Export | static |
| Firestore | nano | tab: Properties | static |
| Memorystore for Redis | nano | tab: Details | static |
| Memorystore for Redis | nano | tab: Connection | static |
| Memorystore for Redis | nano | tab: Configuration | static |
| VPC Network | nano | tab: Permissions | static |
| VPC Network | nano | tab: Labels | static |
| VPC Network | nano | tab: Subnets | static |
| VPC Network | nano | tab: Routes | static |
| VPC Network | nano | tab: VPC peering | static |
| VPC Network | nano | tab: Properties | static |
| VPC Network | nano | tab: Network metrics | partial |
| Pub/Sub | nano | tab: Permissions | static |
| Pub/Sub | nano | tab: Labels | static |
| Pub/Sub | nano | tab: Messages | static |
| Pub/Sub | nano | tab: Encryption | static |
| API Gateway | nano | tab: Permissions | static |
| API Gateway | nano | tab: Labels | static |
| API Gateway | nano | tab: Metrics | partial |
| API Gateway | nano | tab: Logs | static |
| Eventarc | nano | tab: Permissions | static |
| Eventarc | nano | tab: Labels | static |
| Eventarc | nano | tab: Metrics | partial |
| Cloud Scheduler | nano | tab: Last execution | static |
| Cloud Scheduler | nano | tab: Retry policy | static |
| Secret Manager | nano | tab: Permissions | static |
| Secret Manager | nano | tab: Labels | static |
| Secret Manager | nano | tab: Rotation | static |
| Secret Manager | nano | tab: Replication | static |
| Secret Manager | nano | tab: Encryption | static |
| Cloud KMS | nano | tab: Permissions | static |
| Cloud KMS | nano | tab: Labels | static |
| Cloud KMS | nano | tab: Key policy | static |
| Cloud KMS | nano | tab: Import jobs | static |
| IAM & Admin | nano | tab: Permissions | static |
| IAM Service Account Credentials | nano | tab: Credential | static |
| IAM Service Account Credentials | nano | tab: Delegation | static |
| IAM Service Account Credentials | nano | tab: Signing | static |

</details>

<details><summary>Console parts not live yet — Azure (119)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| Virtual Machines | offline | tab: Tags | static |
| Virtual Machines | offline | tab: Connect | static |
| Virtual Machines | offline | tab: Identity | static |
| Storage accounts | offline | tab: Diagnose and solve problems | static |
| Storage accounts | offline | tab: Tables | static |
| Storage accounts | offline | tab: Networking | static |
| SQL servers | offline | tab: Diagnose and solve problems | static |
| SQL servers | offline | tab: Deleted databases | static |
| SQL servers | offline | tab: Failover groups | static |
| SQL servers | offline | tab: Backups | static |
| Service Bus | offline | tab: Tags | static |
| Service Bus | offline | tab: Diagnose and solve problems | static |
| Service Bus | offline | tab: Geo-recovery | static |
| Service Bus | offline | tab: Networking | static |
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
| API Management | offline | tab: Policies | unimplemented |
| API Management | offline | tab: Named values | static |
| Virtual networks | offline | tab: Diagnose and solve problems | static |
| Virtual networks | offline | tab: Address space | static |
| Virtual networks | offline | tab: Subnets | static |
| Virtual networks | offline | tab: DNS servers | static |
| Network Security Group | offline | tab: Diagnose and solve problems | static |
| Network Security Group | offline | tab: Locks | static |
| Event Grid topics | offline | tab: Diagnose and solve problems | static |
| Event Grid topics | offline | tab: Topic types | static |
| Event Grid topics | offline | tab: Networking | static |
| Event Grid topics | offline | tab: Identity | static |
| Key vaults | offline | tab: Diagnose and solve problems | static |
| Key vaults | offline | tab: Access policies | static |
| Key vaults | offline | tab: Access configuration | static |
| Container Apps | offline | tab: Tags | static |
| Container Apps | offline | tab: Diagnose and solve problems | static |
| Container Apps | offline | tab: Containers | static |
| Container Apps | offline | tab: Scale | static |
| Container Apps | offline | tab: Secrets | static |
| App Configuration | offline | tab: Diagnose and solve problems | static |
| App Configuration | offline | tab: Networking | static |
| DNS zones | offline | tab: Tags | static |
| DNS zones | offline | tab: Diagnose and solve problems | static |
| DNS zones | offline | tab: Name servers | static |
| DNS zones | offline | tab: Locks | static |
| Monitor alerts | offline | tab: Diagnose and solve problems | static |
| Log Analytics | offline | tab: Tags | static |
| Log Analytics | offline | tab: Diagnose and solve problems | static |
| Azure AI services | offline | tab: Diagnose and solve problems | static |
| Azure AI services | offline | tab: Networking | static |
| Entra ID / RBAC | offline | tab: Conditions | static |
| Virtual Machines | nano | page: Virtual Machines | static |
| Virtual Machines | nano | tab: Tags | static |
| Virtual Machines | nano | tab: Diagnose and solve problems | static |
| Virtual Machines | nano | tab: Connect | static |
| Storage accounts | nano | tab: Diagnose and solve problems | static |
| Storage accounts | nano | tab: File shares | static |
| Storage accounts | nano | tab: Tables | static |
| Storage accounts | nano | tab: Networking | static |
| SQL servers | nano | tab: Diagnose and solve problems | static |
| SQL servers | nano | tab: Pricing tier | static |
| SQL servers | nano | tab: Deleted databases | static |
| SQL servers | nano | tab: Failover groups | static |
| SQL servers | nano | tab: Backups | static |
| Service Bus | nano | tab: Tags | static |
| Service Bus | nano | tab: Diagnose and solve problems | static |
| Service Bus | nano | tab: Geo-recovery | static |
| Service Bus | nano | tab: Networking | static |
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
| API Management | nano | tab: Policies | unimplemented |
| API Management | nano | tab: Named values | static |
| Virtual networks | nano | tab: Diagnose and solve problems | static |
| Virtual networks | nano | tab: Subnets | static |
| Virtual networks | nano | tab: Connected devices | static |
| Network Security Group | nano | tab: Diagnose and solve problems | static |
| Event Grid topics | nano | tab: Diagnose and solve problems | static |
| Event Grid topics | nano | tab: Topic types | static |
| Event Grid topics | nano | tab: Networking | static |
| Event Grid topics | nano | tab: Identity | static |
| Key vaults | nano | tab: Diagnose and solve problems | static |
| Key vaults | nano | tab: Access policies | static |
| Key vaults | nano | tab: Access configuration | static |
| Container Apps | nano | tab: Tags | static |
| Container Apps | nano | tab: Diagnose and solve problems | static |
| Container Apps | nano | tab: Containers | static |
| Container Apps | nano | tab: Secrets | static |
| App Configuration | nano | tab: Diagnose and solve problems | static |
| App Configuration | nano | tab: Networking | static |
| DNS zones | nano | tab: Tags | static |
| DNS zones | nano | tab: Diagnose and solve problems | static |
| DNS zones | nano | tab: Locks | static |
| Log Analytics | nano | tab: Tags | static |
| Log Analytics | nano | tab: Diagnose and solve problems | static |
| Azure AI services | nano | tab: Diagnose and solve problems | static |
| Azure AI services | nano | tab: Identity | static |
| Azure AI services | nano | tab: Networking | static |
| Entra ID / RBAC | nano | tab: Conditions | static |
| Blob containers | nano | detail: resource detail | unimplemented |
| Cosmos databases | nano | detail: resource detail | unimplemented |
| Key Vault secrets | nano | detail: resource detail | unimplemented |
| Key Vault keys | nano | detail: resource detail | unimplemented |
| Storage queues | nano | page: Storage queues (crawl error) | unimplemented |

</details>

<details><summary>Latest hourly test results</summary>

| Suite | Result | Checks |
|---|---|---|
| offline-ui-crawl | ❌ | 48/52 |
| offline-console-actions | ❌ | 278/293 |
| offline-api-ec2-instance-detail | ✅ | 3/3 |
| offline-api-s3-bucket-creation-date | ✅ | 3/3 |
| offline-api-gcp-eventarc-trigger-defaults | ✅ | 6/6 |
| offline-api-ec2-default-public-ip | ✅ | 3/3 |
| offline-sdk-python-aws | ✅ | 88/88 |
| offline-sdk-go-aws | ✅ | 14/14 |
| offline-sdk-go-gcp | ✅ | 5/5 |
| offline-sdk-go-azure | ✅ | 14/14 |
| offline-sdk-java-aws | ✅ | 29/29 |
| offline-sdk-java-gcp | ✅ | 6/6 |
| offline-sdk-java-azure | ✅ | 5/5 |
| offline-cost-savings | ❌ | 10/11 |
| offline-cli-aws | ✅ | 15/15 |
| offline-cli-gcp | ✅ | 6/6 |
| offline-cli-azure | ✅ | 6/6 |
| offline-ui-core | ✅ | 9/9 |
| nano-ui-crawl | ❌ | 43/57 |
| nano-cores | ✅ | 11/11 |
| nano-ui-aws-lambda-row | ✅ | 4/4 |
| nano-ui-aws-ec2-row | ✅ | 5/5 |
| nano-ui-aws-apigw-row | ✅ | 4/4 |
| nano-ui-aws-vpc-row | ✅ | 4/4 |
| nano-ui-aws-eventbridge-row | ✅ | 4/4 |
| nano-ui-aws-settings-tabs | ✅ | 10/10 |
| nano-ui-aws-iam-detail | ✅ | 4/4 |
| nano-ui-aws-api | ✅ | 6/6 |
| nano-ui-aws-tabs | ✅ | 11/11 |
| nano-ui-gcp-tabs | ✅ | 8/8 |
| nano-ui-gcp-pubsub-grid | ✅ | 3/3 |
| offline-ui-gcp-pubsub-grid | ✅ | 3/3 |
| offline-api-aws-console-savings | ✅ | 6/6 |
| nano-ui-gcp-create-defaults | ✅ | 36/36 |
| offline-ui-gcp-create-defaults | ❌ | 34/36 |
| offline-api-gcp-console-savings | ✅ | 12/12 |
| offline-api-cost-savings-extras | ✅ | 12/12 |
| offline-ui-aws-detail-name | ✅ | 4/4 |
| offline-ui-aws-apigw-tabs | ✅ | 4/4 |
| offline-api-aws-eventbridge-rule-defaults | ✅ | 14/14 |
| nano-ui-azure-tabs | ✅ | 71/71 |
| nano-ui-azure-dp | ✅ | 5/5 |
| nano-ui-azure-home | ✅ | 7/7 |
| nano-ui-budget-savings | ✅ | 5/5 |
| nano-ui-reload-backend | ✅ | 3/3 |
| nano-ui-azure-storage-console | ✅ | 12/12 |
| offline-sdk-java-aws-elbv2 | ✅ | 41/41 |
| offline-sdk-go-aws-elbv2 | ✅ | 53/53 |
| offline-cli-aws-elbv2 | ✅ | 27/27 |
| offline-ui-aws-elbv2 | ✅ | 24/24 |
| nano-ui-aws-elbv2 | ✅ | 24/24 |
| offline-sdk-java-aws-logs | ✅ | 16/16 |
| offline-sdk-go-aws-logs | ✅ | 19/19 |
| offline-cli-aws-logs | ✅ | 19/19 |
| offline-ui-aws-logs | ✅ | 33/33 |
| nano-ui-aws-logs | ✅ | 33/33 |
| offline-sdk-java-aws-ssm | ✅ | 33/33 |
| offline-sdk-go-aws-ssm | ✅ | 38/38 |
| offline-cli-aws-ssm | ✅ | 34/34 |
| offline-ui-aws-ssm | ✅ | 19/19 |
| nano-ui-aws-ssm | ✅ | 19/19 |
| offline-sdk-java-aws-stepfunctions | ✅ | 41/41 |
| offline-sdk-go-aws-stepfunctions | ✅ | 39/39 |
| offline-cli-aws-stepfunctions | ✅ | 26/26 |
| offline-ui-aws-stepfunctions | ✅ | 22/22 |
| nano-ui-aws-stepfunctions | ✅ | 22/22 |
| offline-sdk-java-gcp-cloudscheduler | ✅ | 12/12 |
| offline-sdk-go-gcp-cloudscheduler | ✅ | 13/13 |
| offline-cli-gcp-cloudscheduler | ✅ | 13/13 |
| offline-ui-gcp-cloudscheduler | ✅ | 23/23 |
| nano-ui-gcp-cloudscheduler | ✅ | 23/23 |
| offline-sdk-java-gcp-container | ✅ | 14/14 |
| offline-sdk-go-gcp-container | ✅ | 15/15 |
| offline-cli-gcp-container | ✅ | 14/14 |
| offline-ui-gcp-container | ✅ | 21/21 |
| nano-ui-gcp-container | ✅ | 21/21 |
| offline-sdk-java-gcp-iamcredentials | ✅ | 11/11 |
| offline-sdk-go-gcp-iamcredentials | ✅ | 17/17 |
| offline-cli-gcp-iamcredentials | ✅ | 9/9 |
| offline-ui-gcp-iamcredentials | ✅ | 21/21 |
| nano-ui-gcp-iamcredentials | ✅ | 21/21 |
| offline-sdk-java-gcp-redis | ✅ | 15/15 |
| offline-sdk-go-gcp-redis | ✅ | 16/16 |
| offline-cli-gcp-redis | ✅ | 20/20 |
| offline-ui-gcp-redis | ✅ | 22/22 |
| nano-ui-gcp-redis | ✅ | 22/22 |
| offline-sdk-java-azure-app | ✅ | 15/15 |
| offline-sdk-go-azure-app | ✅ | 29/29 |
| offline-cli-azure-app | ✅ | 23/23 |
| offline-ui-azure-app | ✅ | 29/29 |
| nano-ui-azure-app | ❌ | 28/29 |
| offline-sdk-java-azure-appconfiguration | ✅ | 28/28 |
| offline-sdk-go-azure-appconfiguration | ✅ | 34/34 |
| offline-cli-azure-appconfiguration | ✅ | 32/32 |
| offline-ui-azure-appconfiguration | ✅ | 31/31 |
| nano-ui-azure-appconfiguration | ❌ | 27/28 |
| offline-sdk-java-azure-cognitiveservices | ✅ | 28/28 |
| offline-sdk-go-azure-cognitiveservices | ✅ | 39/39 |
| offline-cli-azure-cognitiveservices | ✅ | 20/20 |
| offline-ui-azure-cognitiveservices | ✅ | 31/31 |
| nano-ui-azure-cognitiveservices | ✅ | 29/29 |
| offline-sdk-java-azure-dns | ✅ | 20/20 |
| offline-sdk-go-azure-dns | ✅ | 31/31 |
| offline-cli-azure-dns | ✅ | 24/24 |
| offline-ui-azure-dns | ✅ | 30/30 |
| nano-ui-azure-dns | ✅ | 28/28 |
| offline-sdk-java-azure-monitor | ✅ | 20/20 |
| offline-sdk-go-azure-monitor | ✅ | 30/30 |
| offline-cli-azure-monitor | ✅ | 21/21 |
| offline-ui-azure-monitor | ✅ | 30/30 |
| nano-ui-azure-monitor | ❌ | 28/29 |
| offline-sdk-java-azure-operationalinsights | ✅ | 23/23 |
| offline-sdk-go-azure-operationalinsights | ✅ | 33/33 |
| offline-cli-azure-operationalinsights | ✅ | 20/20 |
| offline-ui-azure-operationalinsights | ✅ | 34/34 |
| nano-ui-azure-operationalinsights | ✅ | 33/33 |
| offline-ui-azure-nsg-roledef-create | ✅ | 7/7 |
| nano-ui-azure-nsg-roledef-create | ✅ | 7/7 |
| nano-ui-azure-keyvault-tabs | ✅ | 12/12 |
| offline-ui-azure-tags-tab | ✅ | 36/36 |
| nano-ui-azure-tags-tab | ✅ | 36/36 |
| offline-ui-azure-nsg-rules | ✅ | 8/8 |
| nano-ui-azure-nsg-rules | ✅ | 8/8 |

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
