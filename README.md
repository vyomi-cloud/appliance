# Vyomi service pipeline

_Updated 2026-11-01 01:54 UTC · refreshes after every pipeline run_

## At a glance

- **Released:** 55 services (AWS 19 · GCP 18 · Azure 18) of 1,068 the clouds publish
- **Building now:** nothing
- **In the gate / releasing:** Amazon Cognito Identity Provider (AWS), Amazon EC2 Container Service (AWS), Amazon Elastic Container Registry (AWS), Amazon ElastiCache (AWS), Amazon Kinesis (AWS), Amazon Route 53 (AWS), Amazon Simple Email Service (AWS), AWS CloudFormation (AWS), AWS Security Token Service (AWS), BigQuery API (GCP), Cloud DNS API (GCP), Cloud Logging API (GCP), Cloud Run Admin API (GCP), Cloud Tasks API (GCP), Workflows API (GCP), Application Insights (Azure), Container Registry (Azure), Azure Kubernetes Service (Azure), Event Hubs (Azure), Managed Identities (Azure), Azure Cache for Redis (Azure)
- **Queued:** 41 services (P1 first, then P2)
- **Consoles really implemented:** offline 94% · Nano 95%
- **Hourly tests:** 216 of 222 suites passing (run 01:32 UTC)
- **Upstream watch:** 61 open changes from the real clouds to adopt

## By cloud

| Cloud | Released | Building | In gate | Queued | Console live (offline · Nano) |
|---|---|---|---|---|---|
| AWS | 19 | 0 | 9 | 17 | 86% · 87% |
| GCP | 18 | 0 | 6 | 12 | 97% · 100% |
| Azure | 18 | 0 | 6 | 12 | 100% · 99% |

## In progress

- **Real backend:** what the service should run on · **Backend in the code:** what the branch really runs on — ✅ the code reaches it · ⚠️ not in code: the manifest names it but no code reaches it · in-process: the engine itself is the backend

| Service | Cloud | Stage | Checks | Real backend | Backend in the code | Still missing |
|---|---|---|---|---|---|---|
| Amazon Cognito Identity Provider [#53](https://github.com/vyomi-cloud/appliance/issues/53) | AWS | 🔍 In gate ([PR #199](https://github.com/vyomi-cloud/appliance/pull/199)) | 18/18 | in-process | in-process | — |
| Amazon EC2 Container Service [#55](https://github.com/vyomi-cloud/appliance/issues/55) | AWS | 🔍 In gate ([PR #201](https://github.com/vyomi-cloud/appliance/pull/201)) | 19/19 | docker · Pro · + caddy gateway | docker · Pro ✅ | — |
| Amazon Elastic Container Registry [#54](https://github.com/vyomi-cloud/appliance/issues/54) | AWS | 🔍 In gate ([PR #200](https://github.com/vyomi-cloud/appliance/pull/200)) | 20/20 | registry · Lite | registry · 10 MB · Lite ✅ | — |
| Amazon ElastiCache [#56](https://github.com/vyomi-cloud/appliance/issues/56) | AWS | 🔍 In gate ([PR #202](https://github.com/vyomi-cloud/appliance/pull/202)) | 20/20 | valkey · Lite | valkey · 8 MB · Lite ✅ | — |
| Amazon Kinesis [#58](https://github.com/vyomi-cloud/appliance/issues/58) | AWS | 🚀 Releasing | 20/20 | nats · Lite | nats · 10 MB · Lite ⚠️ not in code | — |
| Amazon Route 53 [#60](https://github.com/vyomi-cloud/appliance/issues/60) | AWS | 🔍 In gate ([PR #205](https://github.com/vyomi-cloud/appliance/pull/205)) | 20/20 | coredns · Lite | coredns · 15 MB · Lite ✅ | — |
| Amazon Simple Email Service [#61](https://github.com/vyomi-cloud/appliance/issues/61) | AWS | 🔍 In gate ([PR #206](https://github.com/vyomi-cloud/appliance/pull/206)) | 20/20 | mailpit · Lite | mailpit · 15 MB · Lite ✅ | — |
| AWS CloudFormation [#51](https://github.com/vyomi-cloud/appliance/issues/51) | AWS | 🔍 In gate ([PR #197](https://github.com/vyomi-cloud/appliance/pull/197)) | 20/20 | iac-engine · in-process | in-process | — |
| AWS Security Token Service [#65](https://github.com/vyomi-cloud/appliance/issues/65) | AWS | 🔍 In gate ([PR #209](https://github.com/vyomi-cloud/appliance/pull/209)) | 18/18 | in-process | in-process | — |
| BigQuery API [#67](https://github.com/vyomi-cloud/appliance/issues/67) | GCP | 🔍 In gate ([PR #211](https://github.com/vyomi-cloud/appliance/pull/211)) | 17/18 | duckdb · in-process | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud DNS API [#71](https://github.com/vyomi-cloud/appliance/issues/71) | GCP | 🔍 In gate ([PR #213](https://github.com/vyomi-cloud/appliance/pull/213)) | 17/18 | coredns · Lite | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud Logging API [#73](https://github.com/vyomi-cloud/appliance/issues/73) | GCP | 🔍 In gate ([PR #214](https://github.com/vyomi-cloud/appliance/pull/214)) | 17/18 | logstore · in-process · + fluent-bit agent | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Cloud Run Admin API [#76](https://github.com/vyomi-cloud/appliance/issues/76) | GCP | 🔍 In gate ([PR #216](https://github.com/vyomi-cloud/appliance/pull/216)) | 19/19 | docker · Pro · + caddy gateway | docker · Pro ⚠️ not in code | — |
| Cloud Tasks API [#69](https://github.com/vyomi-cloud/appliance/issues/69) | GCP | 🔍 In gate ([PR #212](https://github.com/vyomi-cloud/appliance/pull/212)) | 20/20 | nats · Lite | nats · 10 MB · Lite ✅ | — |
| Workflows API [#77](https://github.com/vyomi-cloud/appliance/issues/77) | GCP | 🔍 In gate ([PR #221](https://github.com/vyomi-cloud/appliance/pull/221)) | 17/18 | workflow-engine · in-process · + temporal engine | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Application Insights [#80](https://github.com/vyomi-cloud/appliance/issues/80) | Azure | 🔍 In gate ([PR #222](https://github.com/vyomi-cloud/appliance/pull/222)) | 16/17 | logstore · in-process · + fluent-bit agent | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Container Registry [#82](https://github.com/vyomi-cloud/appliance/issues/82) | Azure | 🔍 In gate ([PR #223](https://github.com/vyomi-cloud/appliance/pull/223)) | 20/20 | registry · Lite | registry · 10 MB · Lite ✅ | — |
| Azure Kubernetes Service [#83](https://github.com/vyomi-cloud/appliance/issues/83) | Azure | 🔍 In gate ([PR #224](https://github.com/vyomi-cloud/appliance/pull/224)) | 16/17 | k3s · Max | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Event Hubs [#85](https://github.com/vyomi-cloud/appliance/issues/85) | Azure | 🔍 In gate ([PR #225](https://github.com/vyomi-cloud/appliance/pull/225)) | 16/17 | nats · Lite · + amqp protocol | in-process | backend is the recommended one, or a different real backend the manifest justifies |
| Managed Identities [#87](https://github.com/vyomi-cloud/appliance/issues/87) | Azure | 🔍 In gate ([PR #226](https://github.com/vyomi-cloud/appliance/pull/226)) | 17/17 | in-process | in-process | — |
| Azure Cache for Redis [#89](https://github.com/vyomi-cloud/appliance/issues/89) | Azure | 🔍 In gate ([PR #227](https://github.com/vyomi-cloud/appliance/pull/227)) | 20/20 | valkey · Lite | valkey · 8 MB · Lite ✅ | — |

<details><summary><b>Backend evidence</b> — where each service's code reaches its backend, or why it runs in-process</summary>

| Service | Cloud | Evidence |
|---|---|---|
| Amazon EC2 Container Service | AWS | docker · Pro: `core/ecs_docker_runtime.py` runs docker |
| Amazon Elastic Container Registry | AWS | registry · 10 MB · Lite: `routes/aws_ecr.py` uses VYOMI_ECR_REGISTRY_URL |
| Amazon ElastiCache | AWS | valkey · 8 MB · Lite: `routes/aws_elasticache.py` uses VYOMI_VALKEY_HOST |
| Amazon Kinesis | AWS | the manifest says nats, but no code the branch adds reaches it |
| Amazon Route 53 | AWS | coredns · 15 MB · Lite: `routes/aws_route53.py` uses VYOMI_DNS_ZONES_DIR |
| Amazon Simple Email Service | AWS | mailpit · 15 MB · Lite: `core/ses_mail.py` uses VYOMI_MAILPIT_HOST |
| BigQuery API | GCP | in-process: SQL runs on the stdlib sqlite3 engine inside the core (a GoogleSQL-to-SQLite translation): zero containers, no extra dependency, and it is exactly what Nano runs in Pyodide, where DuckDB is not available |
| Cloud DNS API | GCP | in-process: Zones, record sets and changes are control-plane state held by the engine (identical offline and in Nano, zero extra containers or idle memory). The shared CoreDNS data plane (dig/nslookup answering from these zones) is better added once, for Route 53 / Cloud DNS / Azure DNS together, with a zone-file sync from the shared store; it needs no change to this API surface. |
| Cloud Run Admin API | GCP | the manifest says docker, but no code the branch adds reaches it |
| Cloud Tasks API | GCP | nats · 10 MB · Lite: `core/gcp_cloudtasks_delivery.py` imports nats |
| Container Registry | Azure | registry · 10 MB · Lite: `providers/azure_containerregistry_routes.py` uses CLOUDLEARN_REGISTRY_URL |
| Azure Kubernetes Service | Azure | in-process: This release is control plane only (clusters, node pools, upgrades, credentials, maintenance, snapshots); the console says so. The recommended Max-tier k3s container would only add a real Kubernetes API behind the cluster FQDN, which is not served yet, so no container is added and every tier runs the same in-process engine. |
| Event Hubs | Azure | in-process: Event Hubs' native wire is AMQP 1.0 / Kafka, which no Vyomi tier exposes; the engine keeps the partitioned event log in-process (state in the ARM store, identical in Nano), served over the REST send API and the console Data Explorer, so the shared NATS container would add memory without a reachable data plane. |
| Azure Cache for Redis | Azure | valkey · 8 MB · Lite: `providers/azure_redis_routes.py` uses CLOUDLEARN_VALKEY_HOST |

</details>

## Released services

- **Console live:** parts of the console that are really implemented, offline · Nano
- **UI issues:** problems the latest hourly crawl found, offline · Nano
- **Real backend:** what the service should run on ([backends.json](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/expansion/backends.json)) · **Wired today:** ✅ real · 🟡 partial · ⚪ management API only

### AWS

| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|---|---|
| EC2 | — | not audited | 🧩 13/18 · 🧩 14/18 | 0 · 0 | ✅ watched | before gate |
| S3 | — | not audited | 🧩 17/18 · 🧩 17/18 | 0 · 0 | ✅ watched | before gate |
| IAM | — | not audited | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | before gate |
| RDS | — | not audited | 🧩 17/18 · 🧩 17/18 | 0 · 0 | ✅ watched | before gate |
| DynamoDB | — | not audited | 🧩 15/19 · 🧩 15/19 | 3 · 3 | ✅ watched | before gate |
| SQS | — | not audited | 🧩 12/13 · 🧩 12/13 | 0 · 0 | ✅ watched | before gate |
| Lambda | — | not audited | 🧩 13/16 · 🧩 13/16 | 0 · 0 | ✅ watched | before gate |
| API Gateway | caddy · Lite | not audited | 🧩 13/15 · 🧩 11/15 | 0 · 0 | ✅ watched | before gate |
| VPC | — | not audited | 🧩 10/14 · ✅ 14/14 | 2 · 0 | ✅ watched | before gate |
| EventBridge | nats · Lite | 🟡 rules match and deliver to SQS only; Lambda/HTTP/other targets not delivered | 🧩 12/14 · 🧩 12/14 | 0 · 0 | ✅ watched | before gate |
| Secrets Manager | — | not audited | 🧩 13/15 · 🧩 13/15 | 1 · 1 | ✅ watched | before gate |
| KMS | — | not audited | 🧩 14/16 · 🧩 14/16 | 1 · 1 | ✅ watched | before gate |
| CloudWatch Logs | logstore · in-process · + fluent-bit agent | ✅ in-process engine, SQLite store; filter + Insights queries | 🧩 10/11 · 🧩 10/11 | 0 · 0 | ✅ watched | [v3.0.11](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.11) |
| Elastic Load Balancing | caddy · Lite | ⚪ no traffic forwarded (Caddy not wired) | 🧩 7/8 · 🧩 7/8 | 0 · 0 | ✅ watched | [v3.0.10](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.10) |
| Systems Manager | in-process | 🟡 Parameter Store real; Run Command reports Success without running | 🧩 8/10 · 🧩 8/10 | 1 · 1 | ✅ watched | [v3.0.12](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.12) |
| Step Functions | workflow-engine · in-process · + temporal engine | ✅ ASL interpreter runs executions and calls Lambda; Wait doesn't sleep | 🧩 11/12 · 🧩 11/12 | 0 · 0 | ✅ watched | [v3.0.13](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.13) |
| API Gateway V2 | caddy · Lite | not audited | 🧩 12/13 · 🧩 12/13 | 0 · 0 | ✅ watched | [v3.0.25](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.25) |
| Amazon CloudWatch | victoriametrics · Lite · + vmalert agent | not audited | — | – · – | ✅ watched | [v3.0.26](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.26) |
| Amazon SNS | nats · Lite | not audited | 🧩 9/10 · 🧩 9/10 | 0 · 0 | ✅ watched | [v3.0.28](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.28) |

### GCP

| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|---|---|
| Compute Engine | — | not audited | ✅ 18/18 · ✅ 18/18 | 0 · 0 | ⚠️ 1 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+compute/v1) | before gate |
| Cloud Storage | — | not audited | ✅ 14/14 · ✅ 14/14 | 0 · 0 | ✅ watched | before gate |
| Cloud SQL | — | not audited | ✅ 17/17 · ✅ 17/17 | 0 · 0 | ⚠️ 50 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+sqladmin/v1beta4) | before gate |
| Pub/Sub | — | not audited | 🧩 7/13 · ✅ 13/13 | 0 · 0 | ✅ watched | before gate |
| Firestore | — | not audited | ✅ 13/13 · ✅ 13/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Functions | — | not audited | ✅ 15/15 · ✅ 15/15 | 0 · 0 | ✅ watched | before gate |
| API Gateway | caddy · Lite | not audited | ✅ 12/12 · ✅ 12/12 | 0 · 0 | ✅ watched | before gate |
| VPC Network | — | not audited | ✅ 13/13 · ✅ 13/13 | 0 · 0 | ✅ watched | before gate |
| IAM & Admin | — | not audited | ✅ 9/9 · ✅ 9/9 | 0 · 0 | ✅ watched | before gate |
| Eventarc | — | not audited | ✅ 12/12 · ✅ 12/12 | 0 · 0 | ✅ watched | before gate |
| Secret Manager | — | not audited | ✅ 13/13 · ✅ 13/13 | 0 · 0 | ✅ watched | before gate |
| Cloud KMS | — | not audited | ✅ 13/13 · ✅ 13/13 | 0 · 0 | ✅ watched | before gate |
| Cloud Scheduler | in-process | 🟡 cron fires only on reads; HTTP targets not sent (#147-#149) | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | [v3.0.14](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.14) |
| Kubernetes Engine | k3s · Max | ⚪ no Kubernetes API; kubectl can't connect (k3s not wired) | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | [v3.0.15](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.15) |
| IAM Service Account Credentials | in-process | ✅ real RS256-signed tokens, JWTs and blobs | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | [v3.0.16](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.16) |
| Memorystore for Redis | valkey · Lite | 🟡 one shared 64 MB Valkey; port not published, no per-instance AUTH | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | [v3.0.17](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.17) |
| Artifact Registry | registry · Lite | not audited | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | [v3.0.29](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.29) |
| Cloud Monitoring | victoriametrics · Lite · + vmalert agent | not audited | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | [v3.0.30](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.30) |

### Azure

| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |
|---|---|---|---|---|---|---|
| Virtual Machines | — | not audited | ✅ 22/22 · 🧩 21/22 | 0 · 0 | ⚠️ 1 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+compute) | before gate |
| Storage accounts | — | not audited | ✅ 22/22 · ✅ 22/22 | 0 · 0 | ✅ watched | before gate |
| SQL servers | — | not audited | ✅ 22/22 · ✅ 22/22 | 0 · 0 | ✅ watched | before gate |
| Service Bus | messaging-core · in-process · + nats agent · + amqp protocol | 🟡 REST management + messaging only; native SDKs need AMQP (in PRs #35-#45, not merged) | ✅ 17/17 · ✅ 17/17 | 0 · 0 | ✅ watched | before gate |
| Cosmos DB | — | not audited | ✅ 20/20 · ✅ 20/20 | 0 · 0 | ✅ watched | before gate |
| Function apps | — | not audited | ✅ 23/23 · ✅ 23/23 | 0 · 0 | ✅ watched | before gate |
| API Management | caddy · Lite | not audited | ✅ 20/20 · ✅ 20/20 | 0 · 0 | ✅ watched | before gate |
| Virtual networks | — | not audited | ✅ 17/17 · ✅ 17/17 | 0 · 0 | ✅ watched | before gate |
| Network Security Group | — | not audited | ✅ 11/11 · ✅ 11/11 | 0 · 0 | ✅ watched | before gate |
| Event Grid topics | — | not audited | ✅ 16/16 · ✅ 16/16 | 0 · 0 | ✅ watched | before gate |
| Key vaults | — | not audited | ✅ 17/17 · ✅ 17/17 | 0 · 0 | ✅ watched | before gate |
| Entra ID / RBAC | — | not audited | ✅ 6/6 · ✅ 6/6 | 0 · 0 | ✅ watched | before gate |
| Container Apps | docker · Pro · + caddy gateway | 🟡 real containers on Pro/Max only; no ingress URL | ✅ 17/17 · ✅ 17/17 | 0 · 0 | ✅ watched | [v3.0.18](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.18) |
| App Configuration | in-process | ✅ real key-value data plane | ✅ 16/16 · ✅ 16/16 | 0 · 0 | ✅ watched | [v3.0.19](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.19) |
| Azure AI services | ollama · Max | ⚪ no model inference (Ollama not wired) | ✅ 16/16 · ✅ 16/16 | 0 · 0 | ✅ watched | [v3.0.20](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.20) |
| DNS zones | coredns · Lite | ⚪ no DNS server answers (CoreDNS not wired) | ✅ 14/14 · ✅ 14/14 | 0 · 0 | ✅ watched | [v3.0.21](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.21) |
| Monitor alerts | victoriametrics · Lite · + vmalert agent | ⚪ alert rules stored, never evaluated or fired (vmalert not wired) | ✅ 15/15 · ✅ 15/15 | 0 · 0 | ✅ watched | [v3.0.22](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.22) |
| Log Analytics | logstore · in-process · + fluent-bit agent | ⚪ workspaces only; no ingestion or KQL queries | ✅ 16/16 · ✅ 16/16 | 0 · 0 | ✅ watched | [v3.0.23](https://github.com/vyomi-cloud/appliance/releases/tag/v3.0.23) |

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
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'nats', 'image': 'nats:2-alpine', 'license': 'Apache-2.0', 'tier': 'lite', 'compose_service': 'vyomi-n |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: nats; chose nats |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=Apache-2.0 |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=Apache-2.0 |
| ✅ | backend image is pinned to a version (not latest) | nats:2-alpine |

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
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'mailpit', 'image': 'axllent/mailpit:v1.20', 'license': 'MIT', 'tier': 'lite', 'compose_service': 'vyo |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: mailpit; chose mailpit |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=MIT |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=MIT |
| ✅ | backend image is pinned to a version (not latest) | axllent/mailpit:v1.20 |

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
| ✅ | manifest declares its offline backend (in-process / container / substrate) | backend={'kind': 'container', 'name': 'nats', 'image': 'nats:2-alpine', 'license': 'Apache-2.0', 'tier': 'lite', 'compose_service': 'vyomi-n |
| ✅ | backend is the recommended one, or a different real backend the manifest justifies | recommended: nats; chose nats |
| ✅ | backend license is permissive (or GPL as an unmodified separate container) | license=Apache-2.0 |
| ✅ | backend license is not denied (SSPL / BSL / RSAL / Elastic / AGPL / proprietary) | license=Apache-2.0 |
| ✅ | backend image is pinned to a version (not latest) | nats:2-alpine |

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

<details><summary>Gate checks — Application Insights (Azure)</summary>

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

<details><summary>Gate checks — Container Registry (Azure)</summary>

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

<details><summary>Gate checks — Azure Kubernetes Service (Azure)</summary>

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

<details><summary>Gate checks — Event Hubs (Azure)</summary>

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

<details><summary>Gate checks — Managed Identities (Azure)</summary>

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

<details><summary>Gate checks — Azure Cache for Redis (Azure)</summary>

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

<details><summary>Console parts not live yet — AWS (69)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| EC2 | offline | page: EC2 | static |
| EC2 | offline | tab: Tags | static |
| EC2 | offline | tab: Details | partial |
| EC2 | offline | tab: Networking | partial |
| EC2 | offline | tab: Security | partial |
| Lambda | offline | tab: Tags | static |
| Lambda | offline | tab: Configuration | partial |
| Lambda | offline | tab: Versions | partial |
| S3 | offline | tab: Tags | static |
| RDS | offline | tab: Tags | static |
| DynamoDB | offline | create: create with defaults | partial |
| DynamoDB | offline | detail: resource detail | partial |
| DynamoDB | offline | tab: Overview | partial |
| DynamoDB | offline | tab: Tags | static |
| SQS | offline | tab: Tags | static |
| Amazon SNS | offline | tab: Tags | static |
| API Gateway | offline | tab: Tags | static |
| API Gateway | offline | tab: Settings | partial |
| API Gateway V2 | offline | tab: Tags | static |
| EventBridge | offline | tab: Tags | static |
| EventBridge | offline | tab: Rule details | partial |
| Step Functions | offline | tab: Tags | static |
| Kinesis | offline | tab: Tags | static |
| VPC | offline | page: VPC | partial |
| VPC | offline | create: create with defaults | partial |
| VPC | offline | tab: Subnets | partial |
| VPC | offline | tab: Route tables | partial |
| Elastic Load Balancing | offline | tab: Tags | static |
| Secrets Manager | offline | tab: Tags | static |
| Secrets Manager | offline | tab: Secret value | partial |
| KMS | offline | tab: Tags | static |
| KMS | offline | tab: General configuration | partial |
| CloudWatch Logs | offline | tab: Tags | static |
| Systems Manager | offline | tab: Tags | static |
| Systems Manager | offline | tab: History | partial |
| CloudWatch | offline | tab: Tags | static |
| EC2 | nano | tab: Tags | static |
| EC2 | nano | tab: Details | partial |
| EC2 | nano | tab: Networking | partial |
| EC2 | nano | tab: Security | partial |
| Lambda | nano | tab: Tags | static |
| Lambda | nano | tab: Configuration | partial |
| Lambda | nano | tab: Versions | partial |
| S3 | nano | tab: Tags | static |
| RDS | nano | tab: Tags | static |
| DynamoDB | nano | create: create with defaults | partial |
| DynamoDB | nano | detail: resource detail | partial |
| DynamoDB | nano | tab: Overview | partial |
| DynamoDB | nano | tab: Tags | static |
| SQS | nano | tab: Tags | static |
| Amazon SNS | nano | tab: Tags | static |
| API Gateway | nano | tab: Tags | static |
| API Gateway | nano | tab: Stages | partial |
| API Gateway | nano | tab: Deployments | partial |
| API Gateway | nano | tab: Settings | partial |
| API Gateway V2 | nano | tab: Tags | static |
| EventBridge | nano | tab: Tags | static |
| EventBridge | nano | tab: Rule details | partial |
| Step Functions | nano | tab: Tags | static |
| Kinesis | nano | tab: Tags | static |
| Elastic Load Balancing | nano | tab: Tags | static |
| Secrets Manager | nano | tab: Tags | static |
| Secrets Manager | nano | tab: Secret value | partial |
| KMS | nano | tab: Tags | static |
| KMS | nano | tab: General configuration | partial |
| CloudWatch Logs | nano | tab: Tags | static |
| Systems Manager | nano | tab: Tags | static |
| Systems Manager | nano | tab: History | partial |
| CloudWatch | nano | tab: Tags | static |

</details>

<details><summary>Console parts not live yet — GCP (6)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| Pub/Sub | offline | tab: Labels | unimplemented |
| Pub/Sub | offline | tab: Subscriptions | unimplemented |
| Pub/Sub | offline | tab: Schema | unimplemented |
| Pub/Sub | offline | tab: Messages | unimplemented |
| Pub/Sub | offline | tab: Encryption | unimplemented |
| Pub/Sub | offline | tab: Properties | static |

</details>

<details><summary>Console parts not live yet — Azure (1)</summary>

| Service | Console | Part | State |
|---|---|---|---|
| Virtual Machines | nano | page: Virtual Machines | static |

</details>

<details><summary>Latest hourly test results</summary>

| Suite | Result | Checks |
|---|---|---|
| offline-ui-crawl | ❌ | 53/58 |
| offline-console-actions | ✅ | 371/371 |
| offline-api-ec2-instance-detail | ✅ | 3/3 |
| offline-api-s3-bucket-creation-date | ✅ | 3/3 |
| offline-sdk-python-azure-ops | ✅ | 8/8 |
| offline-api-azure-console-data-planes | ✅ | 36/36 |
| offline-api-aws-provider-connect | ✅ | 11/11 |
| offline-sdk-python-aws-kms-kem | ✅ | 6/6 |
| offline-sdk-python-aws-ops2 | ✅ | 20/20 |
| offline-sdk-python-aws-ops | ✅ | 12/12 |
| offline-api-gcp-eventarc-trigger-defaults | ✅ | 6/6 |
| offline-api-aws-sdk-info-routes | ✅ | 8/8 |
| offline-api-ec2-capacity-reservation-fleet | ✅ | 9/9 |
| offline-api-ec2-capacity-manager-scores | ✅ | 6/6 |
| offline-api-ec2-get-image-findings | ✅ | 4/4 |
| offline-api-ec2-default-public-ip | ✅ | 3/3 |
| offline-sdk-python-aws | ✅ | 79/79 |
| offline-sdk-go-aws | ✅ | 14/14 |
| offline-sdk-go-gcp | ✅ | 5/5 |
| offline-sdk-go-gcp-admin | ✅ | 26/26 |
| offline-sdk-go-azure | ✅ | 14/14 |
| offline-sdk-java-aws | ✅ | 29/29 |
| offline-sdk-java-gcp | ✅ | 6/6 |
| offline-sdk-java-azure | ✅ | 5/5 |
| offline-cost-savings | ✅ | 11/11 |
| offline-cli-aws | ✅ | 15/15 |
| offline-cli-gcp | ✅ | 6/6 |
| offline-cli-azure | ✅ | 6/6 |
| offline-ui-core | ✅ | 9/9 |
| nano-ui-crawl | ❌ | 59/63 |
| nano-cores | ✅ | 344/344 |
| nano-aws-iam-detail | ✅ | 8/8 |
| nano-aws-ec2-launch | ✅ | 13/13 |
| offline-request-metrics | ✅ | 4/4 |
| nano-ui-azure-metrics | ✅ | 12/12 |
| offline-ui-azure-metrics | ✅ | 12/12 |
| nano-ui-aws-metrics | ✅ | 10/10 |
| offline-ui-aws-metrics | ✅ | 10/10 |
| nano-ui-aws-api | ✅ | 6/6 |
| nano-ui-aws-tabs | ✅ | 16/16 |
| nano-ui-gcp-tabs | ✅ | 6/6 |
| nano-ui-gcp-activity-detail | ✅ | 2/2 |
| nano-ui-gcp-grid-defaults | ✅ | 39/39 |
| nano-ui-gcp-pubsub-subscriptions | ✅ | 3/3 |
| nano-ui-gcp-firestore-usage | ✅ | 2/2 |
| nano-ui-gcp-metrics-counts | ✅ | 3/3 |
| offline-ui-gcp-pubsub-subscriptions | ✅ | 3/3 |
| offline-ui-gcp-activity-detail | ✅ | 2/2 |
| offline-ui-gcp-grid-defaults | ✅ | 39/39 |
| nano-ui-aws-vpc-apigw-lists | ✅ | 5/5 |
| nano-ui-aws-compute-reload | ✅ | 4/4 |
| nano-ui-azure-savings | ✅ | 8/8 |
| nano-ui-aws-compute-savings | ✅ | 6/6 |
| nano-ui-aws-ec2-detail-tabs | ✅ | 5/5 |
| offline-ui-aws-ec2-detail-tabs | ✅ | 5/5 |
| offline-api-aws-detail-tabs | ✅ | 200/200 |
| nano-core-aws-detail-tabs | ✅ | 104/104 |
| nano-ui-aws-real-tabs | ✅ | 59/59 |
| offline-ui-aws-real-tabs | ❌ | 57/59 |
| offline-ui-aws-sqs-dlq-tab | ✅ | 2/2 |
| nano-ui-aws-sqs-dlq-tab | ✅ | 2/2 |
| nano-ui-aws-rds-connectivity-tabs | ✅ | 3/3 |
| offline-ui-aws-rds-connectivity-tabs | ✅ | 3/3 |
| nano-ui-aws-vpc-details-tab | ✅ | 2/2 |
| offline-ui-aws-vpc-details-tab | ❌ | 0/1 |
| nano-ui-aws-vpc-sg-iam-cells | ✅ | 3/3 |
| offline-ui-aws-vpc-sg-iam-cells | ❌ | 1/2 |
| offline-api-gcp-pubsub-savings | ✅ | 11/11 |
| offline-api-gcp-apigateway-savings | ✅ | 5/5 |
| offline-api-gcp-console-next | ✅ | 28/28 |
| offline-api-gcp-grid-columns | ✅ | 19/19 |
| offline-api-azure-console-lens | ✅ | 33/33 |
| offline-api-azure-console-routes | ✅ | 35/35 |
| offline-api-gcp-console-vault-lens | ✅ | 15/15 |
| offline-api-gcp-console-pubsub-lens | ✅ | 16/16 |
| offline-api-gcp-vault-console-secrets | ✅ | 9/9 |
| offline-api-aws-console-savings | ✅ | 12/12 |
| offline-api-aws-sdk-info-extras-config | ✅ | 11/11 |
| offline-api-aws-wire-routes | ✅ | 7/7 |
| nano-ui-azure-flat-create | ✅ | 8/8 |
| offline-ui-azure-flat-create | ✅ | 8/8 |
| nano-ui-azure-dp-detail | ✅ | 12/12 |
| nano-ui-azure-rail-last | ✅ | 3/3 |
| nano-ui-azure-rg-nav | ✅ | 3/3 |
| offline-ui-azure-rg-nav | ✅ | 3/3 |
| nano-ui-azure-keyvault-tabs | ✅ | 9/9 |
| nano-ui-gcp-pubsub-grid | ✅ | 3/3 |
| offline-ui-gcp-pubsub-grid | ✅ | 3/3 |
| offline-api-cost-savings-extras | ✅ | 12/12 |
| offline-ui-aws-detail-name | ✅ | 4/4 |
| offline-ui-aws-apigw-tabs | ✅ | 4/4 |
| offline-api-aws-eventbridge-rule-defaults | ✅ | 14/14 |
| nano-ui-azure-tabs | ✅ | 71/71 |
| nano-ui-azure-dp | ✅ | 5/5 |
| nano-ui-azure-home | ✅ | 12/12 |
| nano-ui-budget-savings | ✅ | 5/5 |
| nano-ui-reload-backend | ✅ | 3/3 |
| nano-ui-azure-storage-console | ✅ | 12/12 |
| offline-sdk-java-aws-elbv2 | ✅ | 41/41 |
| offline-sdk-go-aws-elbv2 | ✅ | 60/60 |
| offline-cli-aws-elbv2 | ✅ | 27/27 |
| offline-ui-aws-elbv2 | ✅ | 24/24 |
| nano-ui-aws-elbv2 | ✅ | 24/24 |
| offline-sdk-java-aws-logs | ✅ | 16/16 |
| offline-sdk-go-aws-logs | ✅ | 29/29 |
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
| offline-api-gcp-cloudscheduler-timer | ✅ | 9/9 |
| offline-api-gcp-cloudscheduler-pubsub | ✅ | 7/7 |
| offline-api-gcp-cloudscheduler-http | ✅ | 10/10 |
| offline-cli-gcp-cloudscheduler | ✅ | 13/13 |
| offline-ui-gcp-cloudscheduler | ✅ | 24/24 |
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
| nano-ui-azure-app | ✅ | 29/29 |
| offline-sdk-java-azure-appconfiguration | ✅ | 28/28 |
| offline-sdk-go-azure-appconfiguration | ✅ | 34/34 |
| offline-cli-azure-appconfiguration | ✅ | 32/32 |
| offline-ui-azure-appconfiguration | ✅ | 31/31 |
| nano-ui-azure-appconfiguration | ✅ | 28/28 |
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
| nano-ui-azure-monitor | ✅ | 29/29 |
| offline-sdk-java-azure-operationalinsights | ✅ | 23/23 |
| offline-sdk-go-azure-operationalinsights | ✅ | 33/33 |
| offline-cli-azure-operationalinsights | ✅ | 20/20 |
| offline-ui-azure-operationalinsights | ✅ | 34/34 |
| nano-ui-azure-operationalinsights | ✅ | 33/33 |
| nano-ui-aws-lambda-row | ✅ | 4/4 |
| nano-ui-aws-ec2-row | ✅ | 6/6 |
| nano-ui-aws-apigw-row | ✅ | 6/6 |
| nano-ui-aws-detail-tabs | ✅ | 6/6 |
| offline-ui-aws-detail-tabs | ✅ | 6/6 |
| nano-ui-aws-vpc-row | ✅ | 7/7 |
| nano-ui-aws-eventbridge-row | ✅ | 4/4 |
| nano-ui-aws-settings-tabs | ✅ | 10/10 |
| nano-ui-aws-iam-detail | ✅ | 4/4 |
| nano-ui-gcp-create-defaults | ✅ | 36/36 |
| offline-ui-gcp-create-defaults | ✅ | 36/36 |
| offline-api-gcp-console-savings | ✅ | 12/12 |
| offline-ui-azure-nsg-roledef-create | ✅ | 7/7 |
| nano-ui-azure-nsg-roledef-create | ✅ | 7/7 |
| offline-ui-azure-tags-tab | ✅ | 36/36 |
| nano-ui-azure-tags-tab | ✅ | 36/36 |
| offline-ui-azure-nsg-rules | ✅ | 8/8 |
| nano-ui-azure-nsg-rules | ✅ | 8/8 |
| offline-sdk-java-aws-kinesis | ✅ | 34/34 |
| offline-sdk-go-aws-kinesis | ✅ | 26/26 |
| offline-cli-aws-kinesis | ✅ | 20/20 |
| offline-ui-aws-kinesis | ✅ | 19/19 |
| offline-sdk-java-gcp-artifactregistry | ✅ | 13/13 |
| offline-sdk-go-gcp-artifactregistry | ✅ | 21/21 |
| offline-cli-gcp-artifactregistry | ✅ | 11/11 |
| offline-ui-gcp-artifactregistry | ❌ | 1/7 |
| offline-ui-gcp-metrics-tab | ✅ | 5/5 |
| nano-ui-aws-kinesis | ✅ | 19/19 |
| offline-sdk-java-aws-apigatewayv2 | ✅ | 46/46 |
| offline-sdk-go-aws-apigatewayv2 | ✅ | 39/39 |
| offline-cli-aws-apigatewayv2 | ✅ | 40/40 |
| offline-ui-aws-apigatewayv2 | ✅ | 21/21 |
| nano-ui-aws-apigatewayv2 | ✅ | 21/21 |
| offline-sdk-java-aws-cloudwatch | ✅ | 26/26 |
| offline-sdk-go-aws-cloudwatch | ✅ | 37/37 |
| offline-cli-aws-cloudwatch | ✅ | 31/31 |
| offline-ui-aws-cloudwatch | ✅ | 23/23 |
| nano-ui-aws-cloudwatch | ✅ | 21/21 |
| offline-sdk-java-aws-sns | ✅ | 73/73 |
| offline-sdk-go-aws-sns | ✅ | 71/71 |
| offline-cli-aws-sns | ✅ | 76/76 |
| offline-ui-aws-sns | ✅ | 36/36 |
| nano-ui-aws-sns | ✅ | 36/36 |
| nano-ui-gcp-artifactregistry | ✅ | 15/15 |
| offline-sdk-java-gcp-monitoring | ✅ | 24/24 |
| offline-sdk-go-gcp-monitoring | ✅ | 34/34 |
| offline-cli-gcp-monitoring | ✅ | 15/15 |
| offline-ui-gcp-monitoring | ✅ | 23/23 |
| nano-ui-gcp-monitoring | ✅ | 23/23 |
| nano-ui-aws-secrets-created | ✅ | 3/3 |
| offline-api-gcp-pubsub-tabs-project | ✅ | 6/6 |

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
