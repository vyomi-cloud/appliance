# Vyomi Conformance — hourly report

Run **2026-10-30T07:35:16+00:00** · commit `f849a88ed083` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 17/18 | 254 | 9 | 28/43 | 25/38 | 88 | 43.3% (149/344) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 |
| [GCP](#gcp) | 17/17 | 245 | 0 | 9/18 | 11/18 | 45 |
| [Azure](#azure) | 0/0 | 0 | 0 | 19/25 | 14/20 | 43 |

<a id="aws"></a>
## AWS

**UI findings: 0**

No open UI findings.

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 2.6 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 15 | 0 | 18.0 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 25.0 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 22.0 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 66.4 |
| ✅ | `nano-ui-gcp-detail-panes` | nano | ui | 4 | 0 | 24.4 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 2.4 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 2.6 |
| ✅ | `nano-ui-gcp-iam-detail` | nano | ui | 4 | 0 | 12.3 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 19.1 |
| ✅ | `nano-ui-gcp-labels-tab` | nano | ui | 18 | 0 | 85.1 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 2.5 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 23.5 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 5.1 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 2.5 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 22.5 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 2.7 |

**UI findings: 45**

<details><summary><b>Compute Engine</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Disks | tab 'Disks' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Metadata | tab 'Metadata' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Connect | tab 'Connect' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Scheduling | tab 'Scheduling' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Logs | tab 'Logs' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Firestore</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Data | tab 'Data' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Query builder | tab 'Query builder' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Indexes | tab 'Indexes' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Security rules | tab 'Security rules' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Import / Export | tab 'Import / Export' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud SQL</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Connectivity | tab 'Connectivity' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Flags | tab 'Flags' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Logging | tab 'Logging' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Query Insights | tab 'Query Insights' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Compute Engine</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Metadata | tab 'Metadata' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Connect | tab 'Connect' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Scheduling | tab 'Scheduling' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Kubernetes Engine</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Details | tab 'Details' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Observability | tab 'Observability' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Memorystore for Redis</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Details | tab 'Details' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Connection | tab 'Connection' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Configuration | tab 'Configuration' shows no backend data and nothing about this resource |

</details>

<details><summary><b>IAM Service Account Credentials</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Credential | tab 'Credential' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Delegation | tab 'Delegation' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Signing | tab 'Signing' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Kubernetes Engine</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Details | tab 'Details' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Observability | tab 'Observability' shows no backend data and nothing about this resource |

</details>

<details><summary><b>IAM Service Account Credentials</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Credential | tab 'Credential' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Delegation | tab 'Delegation' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Signing | tab 'Signing' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Pub/Sub</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Messages | tab 'Messages' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Encryption | tab 'Encryption' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Eventarc</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Event matching | tab 'Event matching' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Logs | tab 'Logs' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud Scheduler</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Last execution | tab 'Last execution' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Retry policy | tab 'Retry policy' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud Scheduler</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Last execution | tab 'Last execution' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Retry policy | tab 'Retry policy' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud SQL</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Connectivity | tab 'Connectivity' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Memorystore for Redis</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Configuration | tab 'Configuration' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Pub/Sub</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<a id="azure"></a>
## Azure

**UI findings: 43**

<details><summary><b>Function apps</b> (nano) — 8 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | App keys | tab 'App keys' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Environment variables | tab 'Environment variables' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Authentication | tab 'Authentication' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Identity | tab 'Identity' shows no backend data and nothing about this resource |
| `STATIC_TAB` | TLS/SSL settings | tab 'TLS/SSL settings' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Scale up (App Service plan) | tab 'Scale up (App Service plan)' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Deployment Center | tab 'Deployment Center' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Log stream | tab 'Log stream' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Function apps</b> (offline) — 8 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Functions | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | App keys | placeholder pane ('This pane mirrors … view') |
| `STATIC_TAB` | Environment variables | tab 'Environment variables' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Authentication | tab 'Authentication' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | TLS/SSL settings | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Scale up (App Service plan) | placeholder pane ('This pane mirrors … view') |
| `STATIC_TAB` | Deployment Center | tab 'Deployment Center' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Log stream | placeholder pane ('This pane mirrors … view') |

</details>

<details><summary><b>Virtual Machines</b> (nano) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Networking | fabricated value marked 'simulated' |
| `STATIC_TAB` | Connect | tab 'Connect' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Identity | fabricated value marked 'simulated' |
| `STATIC_TAB` | Auto-shutdown | tab 'Auto-shutdown' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Extensions + applications | tab 'Extensions + applications' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Run command | tab 'Run command' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Alerts | tab 'Alerts' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Virtual Machines</b> (offline) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Networking | fabricated value marked 'simulated' |
| `STATIC_TAB` | Connect | tab 'Connect' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Auto-shutdown | tab 'Auto-shutdown' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Backup | tab 'Backup' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Extensions + applications | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Run command | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Alerts | placeholder pane ('This pane mirrors … view') |

</details>

<details><summary><b>Container Apps</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Containers | tab 'Containers' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Secrets | tab 'Secrets' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Identity | tab 'Identity' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Container Apps</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Containers | tab 'Containers' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Scale | tab 'Scale' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Secrets | tab 'Secrets' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Service Bus</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Geo-recovery | tab 'Geo-recovery' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Identity | fabricated value marked 'simulated' |

</details>

<details><summary><b>DNS zones</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Name servers | tab 'Name servers' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Entra ID / RBAC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Conditions | tab 'Conditions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Service Bus</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Geo-recovery | placeholder pane ('This pane mirrors … view') |

</details>

<details><summary><b>DNS zones</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Name servers | tab 'Name servers' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Entra ID / RBAC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Conditions | placeholder pane ('This pane mirrors … view') |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 9 | 9 | 274.9 |

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/gcp] 18 services crawled, 9 with findings
UI crawl nano: 9/18 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":172,"static":58}
```

</details>

## New features since the last run

| Target | Cloud | Service | Kind | Feature | SDK test |
|---|---|---|---|---|---|
| offline | GCP | gcp_secretmanager_core | operation | PatchSecret | ❌ |
| nano | GCP | gcp_secretmanager_core | operation | PatchSecret | ❌ |

## Upstream changes (AWS / GCP / Azure backlog)

60 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #252 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #250 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #251 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #249 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #247 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #246 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #244 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #245 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #239 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #240 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #237 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #238 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #234 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #235 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #233 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #232 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #231 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #230 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #228 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #229 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #219 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #220 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #218 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #217 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #193 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #191 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #192 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #190 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #186 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #184 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #185 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #183 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #180 | Cross-cloud |  | [shared] Conformance crawl must catch: fake charts, page errors under real tiers, cross-cloud layout drift | 2026-10-29 |
| #178 | GCP |  | [gcp] Console Metrics tabs: real charts for every service (replace seeded fake sparklines) | 2026-10-29 |
| #171 | AWS |  | [aws] EventBridge: deliver to every target type through NATS (today only SQS targets) | 2026-10-28 |
| #169 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |
| #170 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-28 |
| #168 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-28 |
| #167 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-28 |
| #165 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |

## Nano ↔ offline parity gaps

- Azure operation **CreateChild** (azure_subresource_core): only in nano
- Azure operation **DeleteChild** (azure_subresource_core): only in nano
- Azure operation **ListChildren** (azure_subresource_core): only in nano
- Azure operation **UpdateChild** (azure_subresource_core): only in nano
- Azure service **Blob containers** (Blob containers): only in nano
- Azure service **Cosmos databases** (Cosmos databases): only in nano
- Azure service **Key Vault keys** (Key Vault keys): only in nano
- Azure service **Key Vault secrets** (Key Vault secrets): only in nano
- Azure service **Storage queues** (Storage queues): only in nano

## SDK operations without a test (210 of 1218)

<details><summary>AWS · <code>apigatewayv2_core</code> (nano) — 6</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand, TagTarget

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (nano) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>elbv2_core</code> (nano) — 1</summary>

TagTarget

</details>
<details><summary>AWS · <code>kinesis_core</code> (nano) — 7</summary>

DescribeConsumer, DisableMonitoring, EnableMonitoring, ListConsumers, PutPolicy, StartEncryption, StopEncryption

</details>
<details><summary>AWS · <code>logs_core</code> (nano) — 1</summary>

RunInsights

</details>
<details><summary>AWS · <code>sns_core</code> (nano) — 4</summary>

PublishToEndpoint, PublishToPhone, PublishToTopic, SubscribeResult

</details>
<details><summary>AWS · <code>ssm_core</code> (nano) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (nano) — 7</summary>

CreateRepo, DeleteRepo, GetRepo, ListRepos, PatchRepo, TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (nano) — 16</summary>

CreateChannel, CreateDescriptor, CreateUptime, DeleteChannel, DeleteDescriptor, DeleteGroup, GetDescriptor, GetUptime, ListChannels, ListDescriptors, ListGroups, ListTimeSeries, PatchChannel, PatchPolicy, PatchUptime, UpdateGroup

</details>
<details><summary>GCP · <code>gcp_secretmanager_core</code> (nano) — 1</summary>

PatchSecret

</details>
<details><summary>AWS · <code>apigatewayv2_core</code> (offline) — 6</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand, TagTarget

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (offline) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>elbv2_core</code> (offline) — 1</summary>

TagTarget

</details>
<details><summary>AWS · <code>kinesis_core</code> (offline) — 7</summary>

DescribeConsumer, DisableMonitoring, EnableMonitoring, ListConsumers, PutPolicy, StartEncryption, StopEncryption

</details>
<details><summary>AWS · <code>logs_core</code> (offline) — 1</summary>

RunInsights

</details>
<details><summary>AWS · <code>sns_core</code> (offline) — 4</summary>

PublishToEndpoint, PublishToPhone, PublishToTopic, SubscribeResult

</details>
<details><summary>AWS · <code>ssm_core</code> (offline) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (offline) — 7</summary>

CreateRepo, DeleteRepo, GetRepo, ListRepos, PatchRepo, TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (offline) — 16</summary>

CreateChannel, CreateDescriptor, CreateUptime, DeleteChannel, DeleteDescriptor, DeleteGroup, GetDescriptor, GetUptime, ListChannels, ListDescriptors, ListGroups, ListTimeSeries, PatchChannel, PatchPolicy, PatchUptime, UpdateGroup

</details>
<details><summary>GCP · <code>gcp_secretmanager_core</code> (offline) — 1</summary>

PatchSecret

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-30T07:35:16+00:00 | 17/18 | 254 | 9 | 88 | 43.3% |  |
| 2026-10-30T06:05:16+00:00 | 225/233 | 4848 | 84 | 71 | 43.3% |  |
| 2026-10-30T03:58:30+00:00 | 218/226 | 4774 | 100 | 156 | 43.3% |  |
| 2026-10-30T01:47:29+00:00 | 215/223 | 4740 | 109 | 148 | 43.1% |  |
| 2026-10-29T23:56:10+00:00 | 215/223 | 4762 | 87 | 79 | 43.1% |  |
| 2026-10-29T22:06:27+00:00 | 215/223 | 4749 | 100 | 161 | 43.1% |  |
| 2026-10-29T19:55:18+00:00 | 207/216 | 4653 | 111 | 224 | 42.6% |  |
| 2026-10-29T17:38:33+00:00 | 203/215 | 4682 | 78 | 6 | 42.6% |  |
| 2026-10-29T15:43:50+00:00 | 180/182 | 3721 | 6 | 8 | 42.1% |  |
| 2026-10-29T14:08:26+00:00 | 179/181 | 3708 | 5 | 7 | 42.1% |  |
| 2026-10-29T12:34:40+00:00 | 177/181 | 3687 | 11 | 8 | 42.1% |  |
| 2026-10-29T10:56:55+00:00 | 176/178 | 3670 | 5 | 7 | 39.6% |  |
| 2026-10-29T08:59:30+00:00 | 174/176 | 3654 | 6 | 10 | 34.4% |  |
| 2026-10-29T07:25:18+00:00 | 172/175 | 3647 | 6 | 7 | 34.4% |  |
| 2026-10-29T05:46:05+00:00 | 159/175 | 3589 | 54 | 44 | 34.4% |  |
| 2026-10-29T03:56:27+00:00 | 115/123 | 2760 | 39 | 29 | 16.1% |  |
| 2026-10-29T01:35:23+00:00 | 93/105 | 2464 | 85 | 81 | 14.3% |  |
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 98 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 104 | 14.3% |  |
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 104 | 14.3% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
