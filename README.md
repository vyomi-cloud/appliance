# Vyomi service pipeline

Updated **2026-10-26 15:31 UTC** · **36 services released** (AWS 12 / GCP 12 / Azure 12) · **81 in the pipeline** (P1 + P2) · covering all **1068 services** AWS, GCP and Azure publish (catalog of 2026-10-26).

A new service goes live only when the service gate passes: engine, native SDK/CLI wire, console UI offline + Nano, Java + Go + CLI test beds, Playwright console tests offline + Nano, registered with the hourly conformance run and the upstream watcher. Then it is released (patch version) and handed off to both hourly jobs.

**Stages:** 📋 Queued → 🛠 Building → 🔍 In gate → 🚀 Releasing → 🟢 Released. Columns Engine…PW Nano are the gate's static checks on the service branch (⬜ = not checked yet). Offline backend is the cheap, permissively licensed software behind the service offline ([rules + defaults](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/expansion/backends.json)); the gate checks its license, arch, pinning and idle memory. Nano ↔ offline compares every console feature (pages, tabs, columns, create fields, actions, operations) between the two simulators from the latest hourly inventory; a new service can't pass the gate unless both match. Hourly hand-off shows the latest hourly UI crawl (⚠️ n = open findings) and the service's own suites; upstream hand-off shows whether the watcher tracks the API and any open drift issues.

Links: [backlog](https://github.com/vyomi-cloud/appliance/issues?q=label%3Anew-service) · [expansion runs](https://github.com/vyomi-cloud/appliance/actions/workflows/expansion-agent.yml) · [usage-limit log](https://github.com/vyomi-cloud/appliance/tree/expansion-state) · [hourly conformance report](https://github.com/vyomi-cloud/appliance/tree/conformance-report) · [upstream watcher](https://github.com/vyomi-cloud/appliance/tree/upstream-state) · [full catalog](https://github.com/vyomi-cloud/appliance/blob/main/docs/expansion/CLOUD-CATALOG.md)

**Latest hourly run** (2026-10-26 15:30 UTC): `offline-ui-crawl` ❌ 5/38 · `offline-console-actions` ❌ 231/246 · `offline-sdk-python-aws` ❌ 87/88 · `offline-sdk-go-aws` ✅ 14/14 · `offline-sdk-go-gcp` ✅ 5/5 · `offline-sdk-go-azure` ✅ 14/14 · `offline-sdk-java-aws` ✅ 13/13 · `offline-sdk-java-gcp` ✅ 6/6 · `offline-sdk-java-azure` ✅ 5/5 · `offline-cost-savings` ❌ 2/9 · `offline-cli-aws` ✅ 15/15 · `offline-cli-gcp` ✅ 6/6 · `offline-cli-azure` ❌ 5/6 · `offline-ui-core` ✅ 9/9 · `nano-ui-crawl` ❌ 0/43 · `nano-cores` ❌ 0/1 · `nano-ui-aws-api` ❌ 5/6 · `nano-ui-aws-tabs` ✅ 11/11 · `nano-ui-gcp-tabs` ❌ 0/1 · `nano-ui-azure-tabs` ✅ 71/71 · `nano-ui-azure-dp` ✅ 5/5 · `nano-ui-azure-home` ✅ 7/7

## AWS — 12 released, 33 in the pipeline, 390 not yet scheduled (435 published by AWS)

Released: **12** · 📋 Queued: **15** · 🛠 Building: **1** · · Not filed: **17**

**Nano ↔ offline parity:** ✅ every console page has the same features on both.

| Service | Pri | Stage | Offline backend | Engine | Nano | Console | Java | Go | CLI | PW offline | PW Nano | Nano ↔ offline | Gate | Release | Hourly conformance hand-off | Upstream watcher hand-off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **EC2** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 30/30 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 9 | 👁 watched (809 ops) |
| **S3** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 27/27 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 2 | 👁 watched (116 ops) |
| **IAM** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 21/21 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 2 | 👁 watched (180 ops) |
| **RDS** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 32/32 | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 2 | 👁 watched (168 ops) |
| **DynamoDB** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 30/30 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 4 | 👁 watched (58 ops) |
| **SQS** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 22/22 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 2 | 👁 watched (23 ops) |
| **Lambda** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 29/29 | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 2 | 👁 watched (88 ops) |
| **API Gateway** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 26/26 | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 2 | 👁 watched (124 ops) |
| **VPC** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 33/33 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 2 | 👁 watched (809 ops) |
| **EventBridge** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 26/26 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 6 · UI nano ⚠️ 2 | 👁 watched (57 ops) |
| **Secrets Manager** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 24/24 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 8 · UI nano ⚠️ 6 | 👁 watched (23 ops) |
| **KMS** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 27/27 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 2 | 👁 watched (54 ops) |
| Amazon CloudWatch [#52](https://github.com/vyomi-cloud/appliance/issues/52) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon CloudWatch Logs [#59](https://github.com/vyomi-cloud/appliance/issues/59) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Cognito Identity Provider [#53](https://github.com/vyomi-cloud/appliance/issues/53) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon EC2 Container Service [#55](https://github.com/vyomi-cloud/appliance/issues/55) | P1 | 📋 Queued | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Elastic Container Registry [#54](https://github.com/vyomi-cloud/appliance/issues/54) | P1 | 📋 Queued | registry · 10 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon ElastiCache [#56](https://github.com/vyomi-cloud/appliance/issues/56) | P1 | 📋 Queued | valkey · 8 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Kinesis [#58](https://github.com/vyomi-cloud/appliance/issues/58) | P1 | 📋 Queued | nats · 10 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Route 53 [#60](https://github.com/vyomi-cloud/appliance/issues/60) | P1 | 📋 Queued | coredns · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Simple Email Service [#61](https://github.com/vyomi-cloud/appliance/issues/61) | P1 | 📋 Queued | mailpit · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Simple Notification Service [#62](https://github.com/vyomi-cloud/appliance/issues/62) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Simple Systems Manager (SSM) [#63](https://github.com/vyomi-cloud/appliance/issues/63) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AmazonApiGatewayV2 [#50](https://github.com/vyomi-cloud/appliance/issues/50) | P1 | 🛠 Building | in-process | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⏳ gated | static 15/17 · live — | — | ⏳ after release | ✅ registered |
| AWS CloudFormation [#51](https://github.com/vyomi-cloud/appliance/issues/51) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS Security Token Service [#65](https://github.com/vyomi-cloud/appliance/issues/65) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS Step Functions [#64](https://github.com/vyomi-cloud/appliance/issues/64) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Elastic Load Balancing [#57](https://github.com/vyomi-cloud/appliance/issues/57) | P1 | 📋 Queued | caddy · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Athena | P2 | · Not filed | duckdb (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Bedrock Runtime | P2 | · Not filed | ollama · 50 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon DynamoDB Streams | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Elastic File System | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon EventBridge Scheduler | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon Kinesis Firehose | P2 | · Not filed | nats · 10 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Amazon OpenSearch Service | P2 | · Not filed | opensearch · 700 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AmazonMQ | P2 | · Not filed | rabbitmq · 100 MB · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Auto Scaling | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS AppSync | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS Backup | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS Batch | P2 | · Not filed | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS Certificate Manager | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS CodeBuild | P2 | · Not filed | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS Glue | P2 | · Not filed | duckdb (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| AWS X-Ray | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Managed Streaming for Kafka | P2 | · Not filed | kafka · 400 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |

**Gate details**

<details><summary>AWS AmazonApiGatewayV2 — gate 15/17</summary>

| | Check | Detail |
|---|---|---|
| ✅ | manifest has cloud, key, name, upstream, core, operations, suites |  |
| ❌ | manifest status is ready | status=building |
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
| ❌ | manifest declares its offline backend (in-process / container / substrate) | backend=missing |
| ✅ | claimed operations exist in the real API | not upstream: [] |

</details>

<details><summary><b>Not yet scheduled (P3): 390 services</b> — the rest of AWS's 435 published services; scheduled by promoting them to P1/P2 in tests/conformance/expansion/priorities.json</summary>

| Service | Upstream id | Operations | Stage |
|---|---|---|---|
| — | `accessanalyzer` |  | · not scheduled |
| — | `account` |  | · not scheduled |
| — | `account-access` |  | · not scheduled |
| — | `acm-pca` |  | · not scheduled |
| — | `agent-registry` |  | · not scheduled |
| — | `agent-registry-control` |  | · not scheduled |
| — | `aiops` |  | · not scheduled |
| — | `amp` |  | · not scheduled |
| — | `amplify` |  | · not scheduled |
| — | `amplifybackend` |  | · not scheduled |
| — | `amplifyuibuilder` |  | · not scheduled |
| — | `apigatewaymanagementapi` |  | · not scheduled |
| — | `appconfig` |  | · not scheduled |
| — | `appconfigdata` |  | · not scheduled |
| — | `appfabric` |  | · not scheduled |
| — | `appflow` |  | · not scheduled |
| — | `appintegrations` |  | · not scheduled |
| — | `application-autoscaling` |  | · not scheduled |
| — | `application-insights` |  | · not scheduled |
| — | `application-signals` |  | · not scheduled |
| — | `applicationcostprofiler` |  | · not scheduled |
| — | `appmesh` |  | · not scheduled |
| — | `apprunner` |  | · not scheduled |
| — | `appstream` |  | · not scheduled |
| — | `arc-region-switch` |  | · not scheduled |
| — | `arc-zonal-shift` |  | · not scheduled |
| — | `artifact` |  | · not scheduled |
| — | `auditmanager` |  | · not scheduled |
| — | `autoscaling-plans` |  | · not scheduled |
| — | `b2bi` |  | · not scheduled |
| — | `backup-gateway` |  | · not scheduled |
| — | `backupsearch` |  | · not scheduled |
| — | `bcm-dashboards` |  | · not scheduled |
| — | `bcm-data-exports` |  | · not scheduled |
| — | `bcm-pricing-calculator` |  | · not scheduled |
| — | `bcm-recommended-actions` |  | · not scheduled |
| — | `bedrock` |  | · not scheduled |
| — | `bedrock-agent` |  | · not scheduled |
| — | `bedrock-agent-runtime` |  | · not scheduled |
| — | `bedrock-agentcore` |  | · not scheduled |
| — | `bedrock-agentcore-control` |  | · not scheduled |
| — | `bedrock-data-automation` |  | · not scheduled |
| — | `bedrock-data-automation-runtime` |  | · not scheduled |
| — | `billing` |  | · not scheduled |
| — | `billingconductor` |  | · not scheduled |
| — | `braket` |  | · not scheduled |
| — | `budgets` |  | · not scheduled |
| — | `ce` |  | · not scheduled |
| — | `chatbot` |  | · not scheduled |
| — | `chime` |  | · not scheduled |
| — | `chime-sdk-identity` |  | · not scheduled |
| — | `chime-sdk-media-pipelines` |  | · not scheduled |
| — | `chime-sdk-meetings` |  | · not scheduled |
| — | `chime-sdk-messaging` |  | · not scheduled |
| — | `chime-sdk-voice` |  | · not scheduled |
| — | `cleanrooms` |  | · not scheduled |
| — | `cleanroomsml` |  | · not scheduled |
| — | `cloud9` |  | · not scheduled |
| — | `cloudcontrol` |  | · not scheduled |
| — | `clouddirectory` |  | · not scheduled |
| — | `cloudfront` |  | · not scheduled |
| — | `cloudfront-keyvaluestore` |  | · not scheduled |
| — | `cloudhsm` |  | · not scheduled |
| — | `cloudhsmv2` |  | · not scheduled |
| — | `cloudsearch` |  | · not scheduled |
| — | `cloudsearchdomain` |  | · not scheduled |
| — | `cloudtrail` |  | · not scheduled |
| — | `cloudtrail-data` |  | · not scheduled |
| — | `cloudwatchomni` |  | · not scheduled |
| — | `codeartifact` |  | · not scheduled |
| — | `codecatalyst` |  | · not scheduled |
| — | `codecommit` |  | · not scheduled |
| — | `codeconnections` |  | · not scheduled |
| — | `codedeploy` |  | · not scheduled |
| — | `codeguru-reviewer` |  | · not scheduled |
| — | `codeguru-security` |  | · not scheduled |
| — | `codeguruprofiler` |  | · not scheduled |
| — | `codepipeline` |  | · not scheduled |
| — | `codestar-connections` |  | · not scheduled |
| — | `codestar-notifications` |  | · not scheduled |
| — | `cognito-identity` |  | · not scheduled |
| — | `cognito-sync` |  | · not scheduled |
| — | `comprehend` |  | · not scheduled |
| — | `comprehendmedical` |  | · not scheduled |
| — | `compute-optimizer` |  | · not scheduled |
| — | `compute-optimizer-automation` |  | · not scheduled |
| — | `config` |  | · not scheduled |
| — | `connect` |  | · not scheduled |
| — | `connect-contact-lens` |  | · not scheduled |
| — | `connectcampaigns` |  | · not scheduled |
| — | `connectcampaignsv2` |  | · not scheduled |
| — | `connectcases` |  | · not scheduled |
| — | `connecthealth` |  | · not scheduled |
| — | `connectparticipant` |  | · not scheduled |
| — | `continuum` |  | · not scheduled |
| — | `controlcatalog` |  | · not scheduled |
| — | `controltower` |  | · not scheduled |
| — | `cost-optimization-hub` |  | · not scheduled |
| — | `cur` |  | · not scheduled |
| — | `customer-profiles` |  | · not scheduled |
| — | `databrew` |  | · not scheduled |
| — | `dataexchange` |  | · not scheduled |
| — | `datapipeline` |  | · not scheduled |
| — | `datasync` |  | · not scheduled |
| — | `datazone` |  | · not scheduled |
| — | `dax` |  | · not scheduled |
| — | `deadline` |  | · not scheduled |
| — | `detective` |  | · not scheduled |
| — | `devicefarm` |  | · not scheduled |
| — | `devops-agent` |  | · not scheduled |
| — | `devops-guru` |  | · not scheduled |
| — | `directconnect` |  | · not scheduled |
| — | `discovery` |  | · not scheduled |
| — | `dlm` |  | · not scheduled |
| — | `dms` |  | · not scheduled |
| — | `docdb` |  | · not scheduled |
| — | `docdb-elastic` |  | · not scheduled |
| — | `drs` |  | · not scheduled |
| — | `ds` |  | · not scheduled |
| — | `ds-data` |  | · not scheduled |
| — | `dsql` |  | · not scheduled |
| — | `ebs` |  | · not scheduled |
| — | `ec2-instance-connect` |  | · not scheduled |
| — | `ecr-public` |  | · not scheduled |
| — | `eks` |  | · not scheduled |
| — | `eks-auth` |  | · not scheduled |
| — | `elasticbeanstalk` |  | · not scheduled |
| — | `elb` |  | · not scheduled |
| — | `elementalinference` |  | · not scheduled |
| — | `emr` |  | · not scheduled |
| — | `emr-containers` |  | · not scheduled |
| — | `emr-serverless` |  | · not scheduled |
| — | `endusermessaging` |  | · not scheduled |
| — | `entityresolution` |  | · not scheduled |
| — | `es` |  | · not scheduled |
| — | `eventbridgev2` |  | · not scheduled |
| — | `evs` |  | · not scheduled |
| — | `fis` |  | · not scheduled |
| — | `fms` |  | · not scheduled |
| — | `forecast` |  | · not scheduled |
| — | `forecastquery` |  | · not scheduled |
| — | `frauddetector` |  | · not scheduled |
| — | `freetier` |  | · not scheduled |
| — | `fsx` |  | · not scheduled |
| — | `gamelift` |  | · not scheduled |
| — | `gameliftstreams` |  | · not scheduled |
| — | `geo-maps` |  | · not scheduled |
| — | `geo-places` |  | · not scheduled |
| — | `geo-routes` |  | · not scheduled |
| — | `glacier` |  | · not scheduled |
| — | `globalaccelerator` |  | · not scheduled |
| — | `grafana` |  | · not scheduled |
| — | `greengrass` |  | · not scheduled |
| — | `greengrassv2` |  | · not scheduled |
| — | `groundstation` |  | · not scheduled |
| — | `guardduty` |  | · not scheduled |
| — | `health` |  | · not scheduled |
| — | `healthlake` |  | · not scheduled |
| — | `iam-toolbox` |  | · not scheduled |
| — | `identitystore` |  | · not scheduled |
| — | `imagebuilder` |  | · not scheduled |
| — | `importexport` |  | · not scheduled |
| — | `inspector` |  | · not scheduled |
| — | `inspector-scan` |  | · not scheduled |
| — | `inspector2` |  | · not scheduled |
| — | `interconnect` |  | · not scheduled |
| — | `internetmonitor` |  | · not scheduled |
| — | `invoicing` |  | · not scheduled |
| — | `iot` |  | · not scheduled |
| — | `iot-data` |  | · not scheduled |
| — | `iot-jobs-data` |  | · not scheduled |
| — | `iot-managed-integrations` |  | · not scheduled |
| — | `iotdeviceadvisor` |  | · not scheduled |
| — | `iotfleetwise` |  | · not scheduled |
| — | `iotsecuretunneling` |  | · not scheduled |
| — | `iotsitewise` |  | · not scheduled |
| — | `iotthingsgraph` |  | · not scheduled |
| — | `iottwinmaker` |  | · not scheduled |
| — | `iotwireless` |  | · not scheduled |
| — | `ivs` |  | · not scheduled |
| — | `ivs-realtime` |  | · not scheduled |
| — | `ivschat` |  | · not scheduled |
| — | `kafkaconnect` |  | · not scheduled |
| — | `kendra` |  | · not scheduled |
| — | `kendra-ranking` |  | · not scheduled |
| — | `keyspaces` |  | · not scheduled |
| — | `keyspacesstreams` |  | · not scheduled |
| — | `kinesis-video-archived-media` |  | · not scheduled |
| — | `kinesis-video-media` |  | · not scheduled |
| — | `kinesis-video-signaling` |  | · not scheduled |
| — | `kinesis-video-webrtc-storage` |  | · not scheduled |
| — | `kinesisanalytics` |  | · not scheduled |
| — | `kinesisanalyticsv2` |  | · not scheduled |
| — | `kinesisvideo` |  | · not scheduled |
| — | `lakeformation` |  | · not scheduled |
| — | `lambda-core` |  | · not scheduled |
| — | `lambda-microvms` |  | · not scheduled |
| — | `lambda-web` |  | · not scheduled |
| — | `launch-wizard` |  | · not scheduled |
| — | `lex-models` |  | · not scheduled |
| — | `lex-runtime` |  | · not scheduled |
| — | `lexv2-models` |  | · not scheduled |
| — | `lexv2-runtime` |  | · not scheduled |
| — | `license-manager` |  | · not scheduled |
| — | `license-manager-linux-subscriptions` |  | · not scheduled |
| — | `license-manager-user-subscriptions` |  | · not scheduled |
| — | `lightsail` |  | · not scheduled |
| — | `location` |  | · not scheduled |
| — | `lookoutequipment` |  | · not scheduled |
| — | `m2` |  | · not scheduled |
| — | `machinelearning` |  | · not scheduled |
| — | `macie2` |  | · not scheduled |
| — | `mailmanager` |  | · not scheduled |
| — | `managedblockchain` |  | · not scheduled |
| — | `managedblockchain-query` |  | · not scheduled |
| — | `marketplace-agreement` |  | · not scheduled |
| — | `marketplace-catalog` |  | · not scheduled |
| — | `marketplace-deployment` |  | · not scheduled |
| — | `marketplace-discovery` |  | · not scheduled |
| — | `marketplace-entitlement` |  | · not scheduled |
| — | `marketplace-reporting` |  | · not scheduled |
| — | `marketplacecommerceanalytics` |  | · not scheduled |
| — | `mediaconnect` |  | · not scheduled |
| — | `mediaconvert` |  | · not scheduled |
| — | `medialive` |  | · not scheduled |
| — | `mediapackage` |  | · not scheduled |
| — | `mediapackage-vod` |  | · not scheduled |
| — | `mediapackagev2` |  | · not scheduled |
| — | `mediastore` |  | · not scheduled |
| — | `mediastore-data` |  | · not scheduled |
| — | `mediatailor` |  | · not scheduled |
| — | `medical-imaging` |  | · not scheduled |
| — | `memorydb` |  | · not scheduled |
| — | `meteringmarketplace` |  | · not scheduled |
| — | `mgh` |  | · not scheduled |
| — | `mgn` |  | · not scheduled |
| — | `migration-hub-refactor-spaces` |  | · not scheduled |
| — | `migrationhub-config` |  | · not scheduled |
| — | `migrationhuborchestrator` |  | · not scheduled |
| — | `migrationhubstrategy` |  | · not scheduled |
| — | `mpa` |  | · not scheduled |
| — | `mturk` |  | · not scheduled |
| — | `mwaa` |  | · not scheduled |
| — | `mwaa-serverless` |  | · not scheduled |
| — | `neptune` |  | · not scheduled |
| — | `neptune-graph` |  | · not scheduled |
| — | `neptunedata` |  | · not scheduled |
| — | `network-firewall` |  | · not scheduled |
| — | `network-security-manager` |  | · not scheduled |
| — | `networkflowmonitor` |  | · not scheduled |
| — | `networkmanager` |  | · not scheduled |
| — | `networkmonitor` |  | · not scheduled |
| — | `notifications` |  | · not scheduled |
| — | `notificationscontacts` |  | · not scheduled |
| — | `nova-act` |  | · not scheduled |
| — | `oam` |  | · not scheduled |
| — | `observabilityadmin` |  | · not scheduled |
| — | `odb` |  | · not scheduled |
| — | `omics` |  | · not scheduled |
| — | `opensearchserverless` |  | · not scheduled |
| — | `organizations` |  | · not scheduled |
| — | `osis` |  | · not scheduled |
| — | `outposts` |  | · not scheduled |
| — | `partnercentral-account` |  | · not scheduled |
| — | `partnercentral-benefits` |  | · not scheduled |
| — | `partnercentral-channel` |  | · not scheduled |
| — | `partnercentral-revenue-measurement` |  | · not scheduled |
| — | `partnercentral-selling` |  | · not scheduled |
| — | `payment-cryptography` |  | · not scheduled |
| — | `payment-cryptography-data` |  | · not scheduled |
| — | `pca-connector-ad` |  | · not scheduled |
| — | `pca-connector-scep` |  | · not scheduled |
| — | `pcs` |  | · not scheduled |
| — | `personalize` |  | · not scheduled |
| — | `personalize-events` |  | · not scheduled |
| — | `personalize-runtime` |  | · not scheduled |
| — | `pi` |  | · not scheduled |
| — | `pinpoint` |  | · not scheduled |
| — | `pinpoint-email` |  | · not scheduled |
| — | `pinpoint-sms-voice` |  | · not scheduled |
| — | `pinpoint-sms-voice-v2` |  | · not scheduled |
| — | `pipes` |  | · not scheduled |
| — | `polly` |  | · not scheduled |
| — | `pricing` |  | · not scheduled |
| — | `pricing-plan-manager` |  | · not scheduled |
| — | `proton` |  | · not scheduled |
| — | `qapps` |  | · not scheduled |
| — | `qbusiness` |  | · not scheduled |
| — | `qconnect` |  | · not scheduled |
| — | `quicksight` |  | · not scheduled |
| — | `ram` |  | · not scheduled |
| — | `rbin` |  | · not scheduled |
| — | `redshift` |  | · not scheduled |
| — | `redshift-data` |  | · not scheduled |
| — | `redshift-serverless` |  | · not scheduled |
| — | `rekognition` |  | · not scheduled |
| — | `repostspace` |  | · not scheduled |
| — | `resiliencehub` |  | · not scheduled |
| — | `resiliencehubv2` |  | · not scheduled |
| — | `resource-explorer-2` |  | · not scheduled |
| — | `resource-groups` |  | · not scheduled |
| — | `resourcegroupstaggingapi` |  | · not scheduled |
| — | `rolesanywhere` |  | · not scheduled |
| — | `route53-recovery-cluster` |  | · not scheduled |
| — | `route53-recovery-control-config` |  | · not scheduled |
| — | `route53-recovery-readiness` |  | · not scheduled |
| — | `route53domains` |  | · not scheduled |
| — | `route53globalresolver` |  | · not scheduled |
| — | `route53profiles` |  | · not scheduled |
| — | `route53resolver` |  | · not scheduled |
| — | `rtbfabric` |  | · not scheduled |
| — | `rum` |  | · not scheduled |
| — | `s3control` |  | · not scheduled |
| — | `s3files` |  | · not scheduled |
| — | `s3outposts` |  | · not scheduled |
| — | `s3tables` |  | · not scheduled |
| — | `s3vectors` |  | · not scheduled |
| — | `sagemaker` |  | · not scheduled |
| — | `sagemaker-a2i-runtime` |  | · not scheduled |
| — | `sagemaker-edge` |  | · not scheduled |
| — | `sagemaker-featurestore-runtime` |  | · not scheduled |
| — | `sagemaker-geospatial` |  | · not scheduled |
| — | `sagemaker-metrics` |  | · not scheduled |
| — | `sagemaker-runtime` |  | · not scheduled |
| — | `sagemakerjobruntime` |  | · not scheduled |
| — | `sagemakertrainingsessionruntime` |  | · not scheduled |
| — | `savingsplans` |  | · not scheduled |
| — | `schemas` |  | · not scheduled |
| — | `sdb` |  | · not scheduled |
| — | `security-ir` |  | · not scheduled |
| — | `securityagent` |  | · not scheduled |
| — | `securityhub` |  | · not scheduled |
| — | `securitylake` |  | · not scheduled |
| — | `serverlessrepo` |  | · not scheduled |
| — | `service-quotas` |  | · not scheduled |
| — | `servicecatalog` |  | · not scheduled |
| — | `servicecatalog-appregistry` |  | · not scheduled |
| — | `servicediscovery` |  | · not scheduled |
| — | `ses` |  | · not scheduled |
| — | `shield` |  | · not scheduled |
| — | `signer` |  | · not scheduled |
| — | `signer-data` |  | · not scheduled |
| — | `signin` |  | · not scheduled |
| — | `simpledbv2` |  | · not scheduled |
| — | `sms-voice` |  | · not scheduled |
| — | `snow-device-management` |  | · not scheduled |
| — | `snowball` |  | · not scheduled |
| — | `socialmessaging` |  | · not scheduled |
| — | `ssm-contacts` |  | · not scheduled |
| — | `ssm-guiconnect` |  | · not scheduled |
| — | `ssm-incidents` |  | · not scheduled |
| — | `ssm-quicksetup` |  | · not scheduled |
| — | `ssm-sap` |  | · not scheduled |
| — | `sso` |  | · not scheduled |
| — | `sso-admin` |  | · not scheduled |
| — | `sso-oidc` |  | · not scheduled |
| — | `storagegateway` |  | · not scheduled |
| — | `supplychain` |  | · not scheduled |
| — | `support` |  | · not scheduled |
| — | `support-app` |  | · not scheduled |
| — | `supportauthz` |  | · not scheduled |
| — | `sustainability` |  | · not scheduled |
| — | `swf` |  | · not scheduled |
| — | `synthetics` |  | · not scheduled |
| — | `taxsettings` |  | · not scheduled |
| — | `textract` |  | · not scheduled |
| — | `timestream-influxdb` |  | · not scheduled |
| — | `timestream-query` |  | · not scheduled |
| — | `timestream-write` |  | · not scheduled |
| — | `transcribe` |  | · not scheduled |
| — | `transfer` |  | · not scheduled |
| — | `translate` |  | · not scheduled |
| — | `trustedadvisor` |  | · not scheduled |
| — | `uxc` |  | · not scheduled |
| — | `verifiedpermissions` |  | · not scheduled |
| — | `voice-id` |  | · not scheduled |
| — | `vpc-lattice` |  | · not scheduled |
| — | `waf` |  | · not scheduled |
| — | `waf-regional` |  | · not scheduled |
| — | `wafv2` |  | · not scheduled |
| — | `wellarchitected` |  | · not scheduled |
| — | `wickr` |  | · not scheduled |
| — | `wisdom` |  | · not scheduled |
| — | `workdocs` |  | · not scheduled |
| — | `workmail` |  | · not scheduled |
| — | `workmailmessageflow` |  | · not scheduled |
| — | `workspaces` |  | · not scheduled |
| — | `workspaces-instances` |  | · not scheduled |
| — | `workspaces-thin-client` |  | · not scheduled |
| — | `workspaces-web` |  | · not scheduled |

</details>

## GCP — 12 released, 24 in the pipeline, 281 not yet scheduled (316 published by GCP)

Released: **12** · 📋 Queued: **12** · · Not filed: **12**

**Nano ↔ offline parity:** ✅ every console page has the same features on both.

| Service | Pri | Stage | Offline backend | Engine | Nano | Console | Java | Go | CLI | PW offline | PW Nano | Nano ↔ offline | Gate | Release | Hourly conformance hand-off | Upstream watcher hand-off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Compute Engine** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 30/30 | baseline (pre-gate) | <=3.0.8 | UI offline ✅ · UI nano ⚠️ 3 | 👁 watched (1018 ops) |
| **Cloud Storage** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 23/23 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 1 | 👁 watched (87 ops) |
| **Cloud SQL** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 28/28 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched (85 ops) · [⚠️ 1 drift](https://github.com/vyomi-cloud/appliance/issues?q=is%3Aopen+label%3Aupstream-drift+sqladmin/v1beta4) |
| **Pub/Sub** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 19/19 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 5 · UI nano ⚠️ 7 | 👁 watched (46 ops) |
| **Firestore** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 20/20 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 3 · UI nano ⚠️ 7 | 👁 watched (60 ops) |
| **Cloud Functions** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 24/24 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 4 · UI nano ⚠️ 5 | 👁 watched (21 ops) |
| **API Gateway** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 19/19 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched (30 ops) |
| **VPC Network** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 21/21 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 4 · UI nano ⚠️ 7 | 👁 watched (1018 ops) |
| **IAM & Admin** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 16/16 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 1 | 👁 watched (137 ops) |
| **Eventarc** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 20/20 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 4 · UI nano ⚠️ 3 | 👁 watched (66 ops) |
| **Secret Manager** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 20/20 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched (36 ops) |
| **Cloud KMS** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 25/25 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 2 · UI nano ⚠️ 9 | 👁 watched (87 ops) |
| Artifact Registry API [#66](https://github.com/vyomi-cloud/appliance/issues/66) | P1 | 📋 Queued | registry · 10 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| BigQuery API [#67](https://github.com/vyomi-cloud/appliance/issues/67) | P1 | 📋 Queued | duckdb (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud DNS API [#71](https://github.com/vyomi-cloud/appliance/issues/71) | P1 | 📋 Queued | coredns · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Logging API [#73](https://github.com/vyomi-cloud/appliance/issues/73) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Monitoring API [#74](https://github.com/vyomi-cloud/appliance/issues/74) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Run Admin API [#76](https://github.com/vyomi-cloud/appliance/issues/76) | P1 | 📋 Queued | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Scheduler API [#68](https://github.com/vyomi-cloud/appliance/issues/68) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Tasks API [#69](https://github.com/vyomi-cloud/appliance/issues/69) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Google Cloud Memorystore for Redis API [#75](https://github.com/vyomi-cloud/appliance/issues/75) | P1 | 📋 Queued | valkey · 8 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| IAM Service Account Credentials API [#72](https://github.com/vyomi-cloud/appliance/issues/72) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Kubernetes Engine API [#70](https://github.com/vyomi-cloud/appliance/issues/70) | P1 | 📋 Queued | k3s · 500 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Workflows API [#77](https://github.com/vyomi-cloud/appliance/issues/77) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Agent Platform API | P2 | · Not filed | ollama · 50 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Batch API | P2 | · Not filed | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Certificate Manager API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Bigtable Admin API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Composer API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Dataproc API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Datastore API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Filestore API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Spanner API | P2 | · Not filed | spanner-emulator · 150 MB · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Trace API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Cloud Translation API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| Dataflow API | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |

<details><summary><b>Not yet scheduled (P3): 281 services</b> — the rest of GCP's 316 published services; scheduled by promoting them to P1/P2 in tests/conformance/expansion/priorities.json</summary>

| Service | Upstream id | Operations | Stage |
|---|---|---|---|
| Abusive Experience Report API | `abusiveexperiencereport/v1` |  | · not scheduled |
| Accelerated Mobile Pages (AMP) URL API | `acceleratedmobilepageurl/v1` |  | · not scheduled |
| Access Approval API | `accessapproval/v1` |  | · not scheduled |
| Access Context Manager API | `accesscontextmanager/v1` |  | · not scheduled |
| Address Validation API | `addressvalidation/v1` |  | · not scheduled |
| Ad Exchange Buyer API II | `adexchangebuyer2/v2beta1` |  | · not scheduled |
| Ad Experience Report API | `adexperiencereport/v1` |  | · not scheduled |
| Admin SDK API | `admin/reports_v1` |  | · not scheduled |
| AdMob API | `admob/v1` |  | · not scheduled |
| AdSense Management API | `adsense/v2` |  | · not scheduled |
| AdSense Platform API | `adsenseplatform/v1` |  | · not scheduled |
| Advisory Notifications API | `advisorynotifications/v1` |  | · not scheduled |
| Agencies and Brands API | `agenciesandbrands/v1` |  | · not scheduled |
| Agent Identity API | `agentidentity/v1` |  | · not scheduled |
| Agent Identity Credentials API | `agentidentitycredentials/v1` |  | · not scheduled |
| Agent Registry API | `agentregistry/v1` |  | · not scheduled |
| Air Quality API | `airquality/v1` |  | · not scheduled |
| Google Workspace Alert Center API | `alertcenter/v1beta1` |  | · not scheduled |
| AlloyDB API | `alloydb/v1` |  | · not scheduled |
| Google Analytics Admin API | `analyticsadmin/v1beta` |  | · not scheduled |
| Google Analytics Data API | `analyticsdata/v1beta` |  | · not scheduled |
| Analytics Hub API | `analyticshub/v1` |  | · not scheduled |
| Android Developer ID Status API | `androiddeveloperidstatus/v1` |  | · not scheduled |
| Android Device Provisioning Partner API | `androiddeviceprovisioning/v1` |  | · not scheduled |
| Google Play EMM API | `androidenterprise/v1` |  | · not scheduled |
| Android Management API | `androidmanagement/v1` |  | · not scheduled |
| Google Play Android Developer API | `androidpublisher/v3` |  | · not scheduled |
| Apigee API | `apigee/v1` |  | · not scheduled |
| API hub API | `apihub/v1` |  | · not scheduled |
| API Keys API | `apikeys/v2` |  | · not scheduled |
| API Management API | `apim/v1alpha` |  | · not scheduled |
| App Engine Admin API | `appengine/v1` |  | · not scheduled |
| App Hub API | `apphub/v1` |  | · not scheduled |
| Google Workspace Marketplace API | `appsmarket/v2` |  | · not scheduled |
| Area120 Tables API | `area120tables/v1alpha1` |  | · not scheduled |
| Places Aggregate API | `areainsights/v1` |  | · not scheduled |
| Assured Workloads API | `assuredworkloads/v1` |  | · not scheduled |
| Audit Manager API | `auditmanager/v1` |  | · not scheduled |
| Authorized Buyers Marketplace API | `authorizedbuyersmarketplace/v1` |  | · not scheduled |
| Backup and DR Service API | `backupdr/v1` |  | · not scheduled |
| Bare Metal Solution API | `baremetalsolution/v2` |  | · not scheduled |
| BeyondCorp API | `beyondcorp/v1` |  | · not scheduled |
| Lakehouse API | `biglake/v1` |  | · not scheduled |
| BigQuery Connection API | `bigqueryconnection/v1` |  | · not scheduled |
| BigQuery Data Policy API | `bigquerydatapolicy/v2` |  | · not scheduled |
| BigQuery Data Transfer API | `bigquerydatatransfer/v1` |  | · not scheduled |
| BigQuery Reservation API | `bigqueryreservation/v1` |  | · not scheduled |
| Cloud Billing Budget API | `billingbudgets/v1` |  | · not scheduled |
| Binary Authorization API | `binaryauthorization/v1` |  | · not scheduled |
| Blockchain Node Engine API | `blockchainnodeengine/v1` |  | · not scheduled |
| Blogger API | `blogger/v3` |  | · not scheduled |
| Books API | `books/v1` |  | · not scheduled |
| Business Profile Performance API | `businessprofileperformance/v1` |  | · not scheduled |
| Google Calendar API | `calendar/v3` |  | · not scheduled |
| Gemini Enterprise for Customer Experience API | `ces/v1` |  | · not scheduled |
| Google Chat API | `chat/v1` |  | · not scheduled |
| Checks API | `checks/v1alpha` |  | · not scheduled |
| Chrome Management API | `chromemanagement/v1` |  | · not scheduled |
| Chrome Policy API | `chromepolicy/v1` |  | · not scheduled |
| Chrome UX Report API | `chromeuxreport/v1` |  | · not scheduled |
| Chrome Web Store API | `chromewebstore/v2` |  | · not scheduled |
| Google Civic Information API | `civicinfo/v2` |  | · not scheduled |
| Google Classroom API | `classroom/v1` |  | · not scheduled |
| Cloud Asset API | `cloudasset/v1` |  | · not scheduled |
| Cloud Billing API | `cloudbilling/v1` |  | · not scheduled |
| Cloud Build API | `cloudbuild/v2` |  | · not scheduled |
| Cloud Channel API | `cloudchannel/v1` |  | · not scheduled |
| Cloud Commerce Partner Procurement API | `cloudcommerceprocurement/v1` |  | · not scheduled |
| Cloud Controls Partner API | `cloudcontrolspartner/v1` |  | · not scheduled |
| Cloud Deploy API | `clouddeploy/v1` |  | · not scheduled |
| Error Reporting API | `clouderrorreporting/v1beta1` |  | · not scheduled |
| Cloud Identity API | `cloudidentity/v1` |  | · not scheduled |
| Cloud Location Finder API | `cloudlocationfinder/v1` |  | · not scheduled |
| Cloud Number Registry API | `cloudnumberregistry/v1alpha` |  | · not scheduled |
| Cloud Product Registry API | `cloudproductregistry/v1` |  | · not scheduled |
| Cloud Profiler API | `cloudprofiler/v2` |  | · not scheduled |
| Cloud Resource Manager API | `cloudresourcemanager/v3` |  | · not scheduled |
| Cloud Search API | `cloudsearch/v1` |  | · not scheduled |
| Cloud Shell API | `cloudshell/v1` |  | · not scheduled |
| Google Cloud Support API | `cloudsupport/v2` |  | · not scheduled |
| Infrastructure Manager API | `config/v1` |  | · not scheduled |
| Connectors API | `connectors/v2` |  | · not scheduled |
| Contact Center AI Platform API | `contactcenteraiplatform/v1alpha1` |  | · not scheduled |
| Contact Center AI Insights API | `contactcenterinsights/v1` |  | · not scheduled |
| Container Analysis API | `containeranalysis/v1` |  | · not scheduled |
| Document AI Warehouse API | `contentwarehouse/v1` |  | · not scheduled |
| CSS API | `css/v1` |  | · not scheduled |
| Curation Partners API | `curationpartners/v1` |  | · not scheduled |
| Custom Search API | `customsearch/v1` |  | · not scheduled |
| Database Center API | `databasecenter/v1beta` |  | · not scheduled |
| Google Cloud Data Catalog API | `datacatalog/v1` |  | · not scheduled |
| Dataform API | `dataform/v1` |  | · not scheduled |
| Cloud Data Fusion API | `datafusion/v1` |  | · not scheduled |
| Data Labeling API | `datalabeling/v1beta1` |  | · not scheduled |
| Data Lineage API | `datalineage/v1` |  | · not scheduled |
| Data Manager API | `datamanager/v1` |  | · not scheduled |
| Database Migration API | `datamigration/v1` |  | · not scheduled |
| Data pipelines API | `datapipelines/v1` |  | · not scheduled |
| Cloud Dataplex API | `dataplex/v1` |  | · not scheduled |
| Data Portability API | `dataportability/v1` |  | · not scheduled |
| Datastream API | `datastream/v1` |  | · not scheduled |
| Deep Review API | `deepreview/v1` |  | · not scheduled |
| Cloud Deployment Manager V2 API | `deploymentmanager/v2` |  | · not scheduled |
| Developer Connect API | `developerconnect/v1` |  | · not scheduled |
| Developer Knowledge API | `developerknowledge/v1` |  | · not scheduled |
| Device Run API | `devicerun/v1alpha` |  | · not scheduled |
| Campaign Manager 360 API | `dfareporting/v5` |  | · not scheduled |
| Dialogflow API | `dialogflow/v3` |  | · not scheduled |
| Digital Asset Links API | `digitalassetlinks/v1` |  | · not scheduled |
| API Discovery Service | `discovery/v1` |  | · not scheduled |
| Discovery Engine API | `discoveryengine/v1` |  | · not scheduled |
| Display & Video 360 API | `displayvideo/v5` |  | · not scheduled |
| Sensitive Data Protection (DLP) | `dlp/v2` |  | · not scheduled |
| Google Docs API | `docs/v1` |  | · not scheduled |
| Cloud Document AI API | `documentai/v1` |  | · not scheduled |
| Cloud Domains API | `domains/v1` |  | · not scheduled |
| DoubleClick Bid Manager API | `doubleclickbidmanager/v2` |  | · not scheduled |
| Search Ads 360 API | `doubleclicksearch/v2` |  | · not scheduled |
| Drive API | `drive/v3` |  | · not scheduled |
| Drive Activity API | `driveactivity/v2` |  | · not scheduled |
| Drive Labels API | `drivelabels/v2` |  | · not scheduled |
| Essential Contacts API | `essentialcontacts/v1` |  | · not scheduled |
| Fact Check Tools API | `factchecktools/v1alpha1` |  | · not scheduled |
| Firebase Cloud Messaging API | `fcm/v1` |  | · not scheduled |
| Firebase Cloud Messaging Data API | `fcmdata/v1beta1` |  | · not scheduled |
| Firebase Management API | `firebase/v1beta1` |  | · not scheduled |
| Firebase App Check API | `firebaseappcheck/v1` |  | · not scheduled |
| Firebase App Distribution API | `firebaseappdistribution/v1` |  | · not scheduled |
| Firebase App Hosting API | `firebaseapphosting/v1` |  | · not scheduled |
| Firebase Crashlytics API | `firebasecrashlytics/v1alpha` |  | · not scheduled |
| Firebase Realtime Database Management API | `firebasedatabase/v1beta` |  | · not scheduled |
| Firebase SQL Connect API | `firebasedataconnect/v1` |  | · not scheduled |
| Firebase Dynamic Links API | `firebasedynamiclinks/v1` |  | · not scheduled |
| Firebase Hosting API | `firebasehosting/v1` |  | · not scheduled |
| Firebase ML API | `firebaseml/v1` |  | · not scheduled |
| Firebase Rules API | `firebaserules/v1` |  | · not scheduled |
| Cloud Storage for Firebase API | `firebasestorage/v1beta` |  | · not scheduled |
| Fitness API | `fitness/v1` |  | · not scheduled |
| Google Forms API | `forms/v1` |  | · not scheduled |
| Cloud FTP API | `ftp/v1` |  | · not scheduled |
| Google Play Games Services API | `games/v1` |  | · not scheduled |
| Google Play Games Services Publishing API | `gamesConfiguration/v1configuration` |  | · not scheduled |
| Google Play Games Services Management API | `gamesManagement/v1management` |  | · not scheduled |
| Backup for GKE API | `gkebackup/v1` |  | · not scheduled |
| GKE Hub API | `gkehub/v2` |  | · not scheduled |
| GKE On-Prem API | `gkeonprem/v1` |  | · not scheduled |
| Gmail API | `gmail/v1` |  | · not scheduled |
| Gmail Postmaster Tools API | `gmailpostmastertools/v2` |  | · not scheduled |
| Groups Migration API | `groupsmigration/v1` |  | · not scheduled |
| Groups Settings API | `groupssettings/v1` |  | · not scheduled |
| Google Health API | `health/v4` |  | · not scheduled |
| Cloud Healthcare API | `healthcare/v1` |  | · not scheduled |
| HomeGraph API | `homegraph/v1` |  | · not scheduled |
| Cluster Director API | `hypercomputecluster/v1` |  | · not scheduled |
| Cloud Identity-Aware Proxy API | `iap/v1` |  | · not scheduled |
| Identity Toolkit API | `identitytoolkit/v3` |  | · not scheduled |
| Cloud IDS API | `ids/v1` |  | · not scheduled |
| Web Search Indexing API | `indexing/v3` |  | · not scheduled |
| Application Integration API | `integrations/v2` |  | · not scheduled |
| Cloud Talent Solution API | `jobs/v4` |  | · not scheduled |
| Google Keep API | `keep/v1` |  | · not scheduled |
| Knowledge Graph Search API | `kgsearch/v1` |  | · not scheduled |
| KMS Inventory API | `kmsinventory/v1` |  | · not scheduled |
| Cloud Natural Language API | `language/v2` |  | · not scheduled |
| Library Agent API | `libraryagent/v1` |  | · not scheduled |
| Enterprise License Manager API | `licensing/v1` |  | · not scheduled |
| Local Services API | `localservices/v1` |  | · not scheduled |
| Looker (Google Cloud core) API | `looker/v1` |  | · not scheduled |
| Managed Service for Microsoft Active Directory API | `managedidentities/v1` |  | · not scheduled |
| Managed Service for Apache Kafka API | `managedkafka/v1` |  | · not scheduled |
| Manufacturer Center API | `manufacturers/v1` |  | · not scheduled |
| Google Marketing Platform Admin API | `marketingplatformadmin/v1alpha` |  | · not scheduled |
| Google Meet API | `meet/v2` |  | · not scheduled |
| Cloud Memorystore for Memcached API | `memcache/v1` |  | · not scheduled |
| Merchant API | `merchantapi/reviews_v1beta` |  | · not scheduled |
| Dataproc Metastore API | `metastore/v1` |  | · not scheduled |
| Migration Center API | `migrationcenter/v1` |  | · not scheduled |
| AI Platform Training & Prediction API | `ml/v1` |  | · not scheduled |
| My Business Account Management API | `mybusinessaccountmanagement/v1` |  | · not scheduled |
| My Business Business Information API | `mybusinessbusinessinformation/v1` |  | · not scheduled |
| My Business Lodging API | `mybusinesslodging/v1` |  | · not scheduled |
| My Business Notifications API | `mybusinessnotifications/v1` |  | · not scheduled |
| My Business Place Actions API | `mybusinessplaceactions/v1` |  | · not scheduled |
| My Business Q&A API | `mybusinessqanda/v1` |  | · not scheduled |
| My Business Verifications API | `mybusinessverifications/v1` |  | · not scheduled |
| NetApp API | `netapp/v1` |  | · not scheduled |
| Network Connectivity API | `networkconnectivity/v1` |  | · not scheduled |
| Network Management API | `networkmanagement/v1` |  | · not scheduled |
| Network Security API | `networksecurity/v1` |  | · not scheduled |
| Network Services API | `networkservices/v1` |  | · not scheduled |
| Notebooks API | `notebooks/v2` |  | · not scheduled |
| Google OAuth2 API | `oauth2/v2` |  | · not scheduled |
| Observability API | `observability/v1` |  | · not scheduled |
| On-Demand Scanning API | `ondemandscanning/v1` |  | · not scheduled |
| Oracle Database@Google Cloud API | `oracledatabase/v1` |  | · not scheduled |
| Organization Policy API | `orgpolicy/v2` |  | · not scheduled |
| OS Config API | `osconfig/v2` |  | · not scheduled |
| Cloud OS Login API | `oslogin/v1` |  | · not scheduled |
| PageSpeed Insights API | `pagespeedonline/v5` |  | · not scheduled |
| Parallelstore API | `parallelstore/v1` |  | · not scheduled |
| Parameter Manager API | `parametermanager/v1` |  | · not scheduled |
| Payments Reseller Subscription API | `paymentsresellersubscription/v1` |  | · not scheduled |
| People API | `people/v1` |  | · not scheduled |
| Places API (New) | `places/v1` |  | · not scheduled |
| Google Play Custom App Publishing API | `playcustomapp/v1` |  | · not scheduled |
| Google Play Developer Reporting API | `playdeveloperreporting/v1beta1` |  | · not scheduled |
| Google Play Grouping API | `playgrouping/v1alpha1` |  | · not scheduled |
| Google Play Integrity API | `playintegrity/v1` |  | · not scheduled |
| Policy Analyzer API | `policyanalyzer/v1` |  | · not scheduled |
| Policy Simulator API | `policysimulator/v1` |  | · not scheduled |
| Policy Troubleshooter API | `policytroubleshooter/v3` |  | · not scheduled |
| Pollen API | `pollen/v1` |  | · not scheduled |
| Poly API | `poly/v1` |  | · not scheduled |
| Certificate Authority API | `privateca/v1` |  | · not scheduled |
| SAS Portal API (Testing) | `prod_tt_sasportal/v1alpha1` |  | · not scheduled |
| Public Certificate Authority API | `publicca/v1` |  | · not scheduled |
| Pub/Sub Lite API | `pubsublite/v1` |  | · not scheduled |
| Rapid Migration Assessment API | `rapidmigrationassessment/v1` |  | · not scheduled |
| Reader Revenue Subscription Linking API | `readerrevenuesubscriptionlinking/v1` |  | · not scheduled |
| Real-time Bidding API | `realtimebidding/v1` |  | · not scheduled |
| reCAPTCHA Enterprise API | `recaptchaenterprise/v1` |  | · not scheduled |
| Recommendations AI (Beta) | `recommendationengine/v1beta1` |  | · not scheduled |
| Recommender API | `recommender/v1` |  | · not scheduled |
| Google Workspace Reseller API | `reseller/v1` |  | · not scheduled |
| AI Commerce Search API | `retail/v2` |  | · not scheduled |
| Cloud Runtime Configuration API | `runtimeconfig/v1` |  | · not scheduled |
| App Lifecycle Manager API | `saasservicemgmt/v1` |  | · not scheduled |
| Safe Browsing API | `safebrowsing/v5` |  | · not scheduled |
| SAS Portal API | `sasportal/v1alpha1` |  | · not scheduled |
| Apps Script API | `script/v1` |  | · not scheduled |
| Search Ads 360 Reporting API | `searchads360/v23` |  | · not scheduled |
| Google Search Console API | `searchconsole/v1` |  | · not scheduled |
| Secure Source Manager API | `securesourcemanager/v1` |  | · not scheduled |
| Security Command Center API | `securitycenter/v1` |  | · not scheduled |
| Security Posture API | `securityposture/v1` |  | · not scheduled |
| Service Consumer Management API | `serviceconsumermanagement/v1` |  | · not scheduled |
| Service Control API | `servicecontrol/v2` |  | · not scheduled |
| Service Directory API | `servicedirectory/v1` |  | · not scheduled |
| Service Management API | `servicemanagement/v1` |  | · not scheduled |
| Service Networking API | `servicenetworking/v1` |  | · not scheduled |
| Service Usage API | `serviceusage/v1` |  | · not scheduled |
| Google Sheets API | `sheets/v4` |  | · not scheduled |
| Site Verification API | `siteVerification/v1` |  | · not scheduled |
| Google Slides API | `slides/v1` |  | · not scheduled |
| Smart Device Management API | `smartdevicemanagement/v1` |  | · not scheduled |
| Solar API | `solar/v1` |  | · not scheduled |
| Cloud Speech-to-Text API | `speech/v1` |  | · not scheduled |
| Storage Batch Operations API | `storagebatchoperations/v1` |  | · not scheduled |
| Storage Transfer API | `storagetransfer/v1` |  | · not scheduled |
| Street View Publish API | `streetviewpublish/v1` |  | · not scheduled |
| Security Token Service API | `sts/v1` |  | · not scheduled |
| Tag Manager API | `tagmanager/v2` |  | · not scheduled |
| Google Tasks API | `tasks/v1` |  | · not scheduled |
| Cloud Testing API | `testing/v1` |  | · not scheduled |
| Cloud Text-to-Speech API | `texttospeech/v1` |  | · not scheduled |
| Threat Intelligence API | `threatintelligence/v1beta` |  | · not scheduled |
| Cloud Tool Results API | `toolresults/v1beta3` |  | · not scheduled |
| Cloud TPU API | `tpu/v2` |  | · not scheduled |
| Traffic Director API | `trafficdirector/v3` |  | · not scheduled |
| Transcoder API | `transcoder/v1` |  | · not scheduled |
| Travel Impact Model API | `travelimpactmodel/v1` |  | · not scheduled |
| Google Vault API | `vault/v1` |  | · not scheduled |
| Chrome Verified Access API | `verifiedaccess/v2` |  | · not scheduled |
| versionhistory.googleapis.com API | `versionhistory/v1` |  | · not scheduled |
| Cloud Video Intelligence API | `videointelligence/v1` |  | · not scheduled |
| Cloud Vision API | `vision/v1` |  | · not scheduled |
| VM Migration API | `vmmigration/v1` |  | · not scheduled |
| VMware Engine API | `vmwareengine/v1` |  | · not scheduled |
| Serverless VPC Access API | `vpcaccess/v1` |  | · not scheduled |
| Google Wallet API | `walletobjects/v1` |  | · not scheduled |
| Web Content Publisher API | `webcontentpublisher/v1` |  | · not scheduled |
| Web Fonts Developer API | `webfonts/v1` |  | · not scheduled |
| Web Risk API | `webrisk/v1` |  | · not scheduled |
| Web Security Scanner API | `websecurityscanner/v1` |  | · not scheduled |
| Workflow Executions API | `workflowexecutions/v1` |  | · not scheduled |
| Workload Manager API | `workloadmanager/v1` |  | · not scheduled |
| Google Workspace Events API | `workspaceevents/v1` |  | · not scheduled |
| Cloud Workstations API | `workstations/v1` |  | · not scheduled |
| YouTube Data API v3 | `youtube/v3` |  | · not scheduled |
| YouTube Analytics API | `youtubeAnalytics/v2` |  | · not scheduled |
| YouTube Reporting API | `youtubereporting/v1` |  | · not scheduled |

</details>

## Azure — 12 released, 24 in the pipeline, 282 not yet scheduled (317 published by Azure)

Released: **12** · 📋 Queued: **12** · · Not filed: **12**

**Nano ↔ offline parity gaps** (the hourly agent closes these):

| Console page | Offline only | Nano only |
|---|---|---|
| Blob containers | — | column: Name, create_field: Blob container, service: Blob containers |
| Cosmos databases | — | column: Name, create_field: Cosmos database, service: Cosmos databases |
| Key Vault keys | — | column: Name, create_field: Key Vault key, service: Key Vault keys |
| Key Vault secrets | — | column: Name, create_field: Key Vault secret, service: Key Vault secrets |
| Storage queues | — | column: Name, create_field: Storage queue, service: Storage queues |
| azure_subresource_core | — | operation: CreateChild, operation: DeleteChild, operation: ListChildren, operation: UpdateChild |

| Service | Pri | Stage | Offline backend | Engine | Nano | Console | Java | Go | CLI | PW offline | PW Nano | Nano ↔ offline | Gate | Release | Hourly conformance hand-off | Upstream watcher hand-off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Virtual Machines** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 27/27 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Storage accounts** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 28/28 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **SQL servers** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 27/27 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Service Bus** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 21/21 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Cosmos DB** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 24/24 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Function apps** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 27/27 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **API Management** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 25/25 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Virtual networks** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 21/21 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Network Security Group** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 6/6 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Event Grid topics** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 21/21 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Key vaults** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 22/22 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| **Entra ID / RBAC** | — | 🟢 Released | — | — | — | — | — | — | — | — | — | ✅ 10/10 | baseline (pre-gate) | <=3.0.8 | UI offline ⚠️ 1 · UI nano ⚠️ 1 | 👁 watched |
| app [#78](https://github.com/vyomi-cloud/appliance/issues/78) | P1 | 📋 Queued | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| appconfiguration [#79](https://github.com/vyomi-cloud/appliance/issues/79) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| applicationinsights [#80](https://github.com/vyomi-cloud/appliance/issues/80) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| cognitiveservices [#81](https://github.com/vyomi-cloud/appliance/issues/81) | P1 | 📋 Queued | ollama · 50 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| containerregistry [#82](https://github.com/vyomi-cloud/appliance/issues/82) | P1 | 📋 Queued | registry · 10 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| containerservice [#83](https://github.com/vyomi-cloud/appliance/issues/83) | P1 | 📋 Queued | k3s · 500 MB · Max (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| dns [#84](https://github.com/vyomi-cloud/appliance/issues/84) | P1 | 📋 Queued | coredns · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| eventhub [#85](https://github.com/vyomi-cloud/appliance/issues/85) | P1 | 📋 Queued | nats · 10 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| monitor [#86](https://github.com/vyomi-cloud/appliance/issues/86) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| msi [#87](https://github.com/vyomi-cloud/appliance/issues/87) | P1 | 📋 Queued | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| operationalinsights [#88](https://github.com/vyomi-cloud/appliance/issues/88) | P1 | 📋 Queued | duckdb (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| redis [#89](https://github.com/vyomi-cloud/appliance/issues/89) | P1 | 📋 Queued | valkey · 8 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| batch | P2 | · Not filed | docker · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| cdn | P2 | · Not filed | caddy · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| datafactory | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| frontdoor | P2 | · Not filed | caddy · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| mysql | P2 | · Not filed | mariadb · 90 MB · Pro (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| notificationhubs | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| postgresql | P2 | · Not filed | postgres · 40 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| privatedns | P2 | · Not filed | coredns · 15 MB · Lite (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| search | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| servicefabric | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| signalr | P2 | · Not filed | in-process | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |
| synapse | P2 | · Not filed | duckdb (default) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⏳ gated | — | — | ⏳ after release | ⏳ registered at build |

<details><summary><b>Not yet scheduled (P3): 282 services</b> — the rest of Azure's 317 published services; scheduled by promoting them to P1/P2 in tests/conformance/expansion/priorities.json</summary>

| Service | Upstream id | Operations | Stage |
|---|---|---|---|
| — | `EnterpriseKnowledgeGraph` |  | · not scheduled |
| — | `addons` |  | · not scheduled |
| — | `adhybridhealthservice` |  | · not scheduled |
| — | `advisor` |  | · not scheduled |
| — | `agricultureplatform` |  | · not scheduled |
| — | `agrifood` |  | · not scheduled |
| — | `ai` |  | · not scheduled |
| — | `ai-foundry` |  | · not scheduled |
| — | `alertsmanagement` |  | · not scheduled |
| — | `analysisservices` |  | · not scheduled |
| — | `anyscale` |  | · not scheduled |
| — | `apicenter` |  | · not scheduled |
| — | `appcomplianceautomation` |  | · not scheduled |
| — | `applink` |  | · not scheduled |
| — | `appplatform` |  | · not scheduled |
| — | `artifactsigning` |  | · not scheduled |
| — | `attestation` |  | · not scheduled |
| — | `automanage` |  | · not scheduled |
| — | `automation` |  | · not scheduled |
| — | `awsconnector` |  | · not scheduled |
| — | `azsadmin` |  | · not scheduled |
| — | `azure-kusto` |  | · not scheduled |
| — | `azure-native-integrations` |  | · not scheduled |
| — | `azureactivedirectory` |  | · not scheduled |
| — | `azurearcdata` |  | · not scheduled |
| — | `azuredata` |  | · not scheduled |
| — | `azuredatatransfer` |  | · not scheduled |
| — | `azuredependencymap` |  | · not scheduled |
| — | `azurefleet` |  | · not scheduled |
| — | `azureintegrationspaces` |  | · not scheduled |
| — | `azurelargeinstance` |  | · not scheduled |
| — | `azureresiliencemanagement` |  | · not scheduled |
| — | `azurestack` |  | · not scheduled |
| — | `azurestackhci` |  | · not scheduled |
| — | `baremetalinfrastructure` |  | · not scheduled |
| — | `billing` |  | · not scheduled |
| — | `billingbenefits` |  | · not scheduled |
| — | `billingtrust` |  | · not scheduled |
| — | `blueprint` |  | · not scheduled |
| — | `botservice` |  | · not scheduled |
| — | `carbon` |  | · not scheduled |
| — | `certificateregistration` |  | · not scheduled |
| — | `chaos` |  | · not scheduled |
| — | `cloudhealth` |  | · not scheduled |
| — | `cloudshell` |  | · not scheduled |
| — | `codesigning` |  | · not scheduled |
| — | `commerce` |  | · not scheduled |
| — | `common-types` |  | · not scheduled |
| — | `communication` |  | · not scheduled |
| — | `communitytraining` |  | · not scheduled |
| — | `computebulkactions` |  | · not scheduled |
| — | `computelimit` |  | · not scheduled |
| — | `computeschedule` |  | · not scheduled |
| — | `confidentialledger` |  | · not scheduled |
| — | `confluent` |  | · not scheduled |
| — | `connectedcache` |  | · not scheduled |
| — | `connectedvmware` |  | · not scheduled |
| — | `consumption` |  | · not scheduled |
| — | `containerinstance` |  | · not scheduled |
| — | `containerstorage` |  | · not scheduled |
| — | `contosowidgetmanager` |  | · not scheduled |
| — | `cost-management` |  | · not scheduled |
| — | `cpim` |  | · not scheduled |
| — | `customer-insights` |  | · not scheduled |
| — | `customerlockbox` |  | · not scheduled |
| — | `customproviders` |  | · not scheduled |
| — | `dashboard` |  | · not scheduled |
| — | `databasefleetmanager` |  | · not scheduled |
| — | `databasewatcher` |  | · not scheduled |
| — | `databox` |  | · not scheduled |
| — | `databoxedge` |  | · not scheduled |
| — | `databricks` |  | · not scheduled |
| — | `datacatalog` |  | · not scheduled |
| — | `datadog` |  | · not scheduled |
| — | `datalake-analytics` |  | · not scheduled |
| — | `datalake-store` |  | · not scheduled |
| — | `datamigration` |  | · not scheduled |
| — | `dataprotection` |  | · not scheduled |
| — | `datashare` |  | · not scheduled |
| — | `dell` |  | · not scheduled |
| — | `desktopvirtualization` |  | · not scheduled |
| — | `devcenter` |  | · not scheduled |
| — | `developerhub` |  | · not scheduled |
| — | `deviceprovisioningservices` |  | · not scheduled |
| — | `deviceregistry` |  | · not scheduled |
| — | `deviceupdate` |  | · not scheduled |
| — | `devops` |  | · not scheduled |
| — | `devopsinfrastructure` |  | · not scheduled |
| — | `devspaces` |  | · not scheduled |
| — | `devtestlabs` |  | · not scheduled |
| — | `dfp` |  | · not scheduled |
| — | `digitaltwins` |  | · not scheduled |
| — | `discovery` |  | · not scheduled |
| — | `dnc` |  | · not scheduled |
| — | `dnsresolver` |  | · not scheduled |
| — | `domainregistration` |  | · not scheduled |
| — | `domainservices` |  | · not scheduled |
| — | `durabletask` |  | · not scheduled |
| — | `dynamicstelemetry` |  | · not scheduled |
| — | `dynatrace` |  | · not scheduled |
| — | `edge` |  | · not scheduled |
| — | `edgemarketplace` |  | · not scheduled |
| — | `edgeoperator` |  | · not scheduled |
| — | `edgeorder` |  | · not scheduled |
| — | `edgeorderpartner` |  | · not scheduled |
| — | `edgezones` |  | · not scheduled |
| — | `education` |  | · not scheduled |
| — | `elastic` |  | · not scheduled |
| — | `elasticsan` |  | · not scheduled |
| — | `engagementfabric` |  | · not scheduled |
| — | `ews` |  | · not scheduled |
| — | `extendedlocation` |  | · not scheduled |
| — | `fabric` |  | · not scheduled |
| — | `fileshares` |  | · not scheduled |
| — | `fist` |  | · not scheduled |
| — | `fluidrelay` |  | · not scheduled |
| — | `gcpconnector` |  | · not scheduled |
| — | `github-network` |  | · not scheduled |
| — | `graphservicesprod` |  | · not scheduled |
| — | `guestconfiguration` |  | · not scheduled |
| — | `hanaonazure` |  | · not scheduled |
| — | `hardwaresecuritymodules` |  | · not scheduled |
| — | `hdinsight` |  | · not scheduled |
| — | `healthbot` |  | · not scheduled |
| — | `healthcareapis` |  | · not scheduled |
| — | `healthdataaiservices` |  | · not scheduled |
| — | `help` |  | · not scheduled |
| — | `horizondb` |  | · not scheduled |
| — | `hybridaks` |  | · not scheduled |
| — | `hybridcloud` |  | · not scheduled |
| — | `hybridcompute` |  | · not scheduled |
| — | `hybridconnectivity` |  | · not scheduled |
| — | `hybridkubernetes` |  | · not scheduled |
| — | `hybridnetwork` |  | · not scheduled |
| — | `imagebuilder` |  | · not scheduled |
| — | `imds` |  | · not scheduled |
| — | `impact` |  | · not scheduled |
| — | `inferenceservice` |  | · not scheduled |
| — | `informatica` |  | · not scheduled |
| — | `intune` |  | · not scheduled |
| — | `iotcentral` |  | · not scheduled |
| — | `iothub` |  | · not scheduled |
| — | `iotoperations` |  | · not scheduled |
| — | `iotoperationsdataprocessor` |  | · not scheduled |
| — | `iotoperationsmq` |  | · not scheduled |
| — | `iotoperationsorchestrator` |  | · not scheduled |
| — | `iotspaces` |  | · not scheduled |
| — | `kubernetesconfiguration` |  | · not scheduled |
| — | `kubernetesruntime` |  | · not scheduled |
| — | `labservices` |  | · not scheduled |
| — | `liftrarize` |  | · not scheduled |
| — | `liftrcommvault` |  | · not scheduled |
| — | `liftrhyperexecute` |  | · not scheduled |
| — | `liftrmongodb` |  | · not scheduled |
| — | `liftrpinecone` |  | · not scheduled |
| — | `liftrqumulo` |  | · not scheduled |
| — | `liftrweightsandbiases` |  | · not scheduled |
| — | `loadtestservice` |  | · not scheduled |
| — | `logic` |  | · not scheduled |
| — | `m365securityandcompliance` |  | · not scheduled |
| — | `machinelearning` |  | · not scheduled |
| — | `machinelearningservices` |  | · not scheduled |
| — | `maintenance` |  | · not scheduled |
| — | `managednetwork` |  | · not scheduled |
| — | `managednetworkfabric` |  | · not scheduled |
| — | `managedoperations` |  | · not scheduled |
| — | `managedservices` |  | · not scheduled |
| — | `management` |  | · not scheduled |
| — | `managementpartner` |  | · not scheduled |
| — | `manufacturingplatform` |  | · not scheduled |
| — | `maps` |  | · not scheduled |
| — | `mariadb` |  | · not scheduled |
| — | `marketplace` |  | · not scheduled |
| — | `marketplacecatalog` |  | · not scheduled |
| — | `marketplacenotifications` |  | · not scheduled |
| — | `marketplaceordering` |  | · not scheduled |
| — | `migrate` |  | · not scheduled |
| — | `migrateprojects` |  | · not scheduled |
| — | `mission` |  | · not scheduled |
| — | `mongocluster` |  | · not scheduled |
| — | `monitoringservice` |  | · not scheduled |
| — | `mysqldiscovery` |  | · not scheduled |
| — | `napster` |  | · not scheduled |
| — | `netapp` |  | · not scheduled |
| — | `networkcloud` |  | · not scheduled |
| — | `networkfunction` |  | · not scheduled |
| — | `newrelic` |  | · not scheduled |
| — | `nginx` |  | · not scheduled |
| — | `oep` |  | · not scheduled |
| — | `offazurespringboot` |  | · not scheduled |
| — | `onlineexperimentation` |  | · not scheduled |
| — | `operationsmanagement` |  | · not scheduled |
| — | `oracle` |  | · not scheduled |
| — | `orbital` |  | · not scheduled |
| — | `orbitalplanetarycomputer` |  | · not scheduled |
| — | `paloaltonetworks` |  | · not scheduled |
| — | `peering` |  | · not scheduled |
| — | `platformvalidation` |  | · not scheduled |
| — | `playwrighttesting` |  | · not scheduled |
| — | `policyinsights` |  | · not scheduled |
| — | `portal` |  | · not scheduled |
| — | `portalservices` |  | · not scheduled |
| — | `postgresqlhsc` |  | · not scheduled |
| — | `powerbidedicated` |  | · not scheduled |
| — | `powerbiembedded` |  | · not scheduled |
| — | `powerbiprivatelinks` |  | · not scheduled |
| — | `powerplatform` |  | · not scheduled |
| — | `privatetrafficmanager` |  | · not scheduled |
| — | `professionalservice` |  | · not scheduled |
| — | `programenrollment` |  | · not scheduled |
| — | `programmableconnectivity` |  | · not scheduled |
| — | `providerhub` |  | · not scheduled |
| — | `purestorage` |  | · not scheduled |
| — | `purview` |  | · not scheduled |
| — | `purviewdatagovernace` |  | · not scheduled |
| — | `purviewdatagovernance` |  | · not scheduled |
| — | `purviewpolicy` |  | · not scheduled |
| — | `quantum` |  | · not scheduled |
| — | `quota` |  | · not scheduled |
| — | `recommendationsservice` |  | · not scheduled |
| — | `recoveryservices` |  | · not scheduled |
| — | `recoveryservicesbackup` |  | · not scheduled |
| — | `recoveryservicesdatareplication` |  | · not scheduled |
| — | `recoveryservicessiterecovery` |  | · not scheduled |
| — | `redhatopenshift` |  | · not scheduled |
| — | `redisenterprise` |  | · not scheduled |
| — | `relationships` |  | · not scheduled |
| — | `relay` |  | · not scheduled |
| — | `reservations` |  | · not scheduled |
| — | `resourceconnector` |  | · not scheduled |
| — | `resourcegraph` |  | · not scheduled |
| — | `resourcehealth` |  | · not scheduled |
| — | `resourcemover` |  | · not scheduled |
| — | `resources` |  | · not scheduled |
| — | `riskiq` |  | · not scheduled |
| — | `saas` |  | · not scheduled |
| — | `scheduler` |  | · not scheduled |
| — | `schemaregistry` |  | · not scheduled |
| — | `scom` |  | · not scheduled |
| — | `scvmm` |  | · not scheduled |
| — | `security` |  | · not scheduled |
| — | `securityandcompliance` |  | · not scheduled |
| — | `securityinsights` |  | · not scheduled |
| — | `serialconsole` |  | · not scheduled |
| — | `service-map` |  | · not scheduled |
| — | `servicefabricmanagedclusters` |  | · not scheduled |
| — | `servicefabricmesh` |  | · not scheduled |
| — | `servicelinker` |  | · not scheduled |
| — | `servicenetworking` |  | · not scheduled |
| — | `softwareplan` |  | · not scheduled |
| — | `solutions` |  | · not scheduled |
| — | `sovereign` |  | · not scheduled |
| — | `sphere` |  | · not scheduled |
| — | `splitio` |  | · not scheduled |
| — | `sqlvirtualmachine` |  | · not scheduled |
| — | `standbypool` |  | · not scheduled |
| — | `storageactions` |  | · not scheduled |
| — | `storagecache` |  | · not scheduled |
| — | `storagediscovery` |  | · not scheduled |
| — | `storageimportexport` |  | · not scheduled |
| — | `storagemover` |  | · not scheduled |
| — | `storagepool` |  | · not scheduled |
| — | `storagesync` |  | · not scheduled |
| — | `streamanalytics` |  | · not scheduled |
| — | `subscription` |  | · not scheduled |
| — | `support` |  | · not scheduled |
| — | `syntex` |  | · not scheduled |
| — | `terraform` |  | · not scheduled |
| — | `testbase` |  | · not scheduled |
| — | `timeseriesinsights` |  | · not scheduled |
| — | `trafficmanager` |  | · not scheduled |
| — | `translation` |  | · not scheduled |
| — | `verifiedid` |  | · not scheduled |
| — | `vi` |  | · not scheduled |
| — | `vmware` |  | · not scheduled |
| — | `vmwarecloudsimple` |  | · not scheduled |
| — | `webpubsub` |  | · not scheduled |
| — | `widget` |  | · not scheduled |
| — | `windowsesu` |  | · not scheduled |
| — | `windowsiot` |  | · not scheduled |
| — | `workloadmonitor` |  | · not scheduled |
| — | `workloads` |  | · not scheduled |

</details>
