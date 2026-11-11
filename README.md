# Vyomi Conformance — hourly report

Run **not yet** · commit `` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 0/0 | 0 | 0 | 0/0 | 0/0 | 0 | 0.0% (0/0) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 |
| [GCP](#gcp) | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 |
| [Azure](#azure) | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 |

<a id="aws"></a>
## AWS

**UI findings: 0**

No open UI findings.

<a id="gcp"></a>
## GCP

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

**UI findings: 0**

No open UI findings.

## New features since the last run

First inventory taken this run; new features are reported from the next run.

## Upstream changes (AWS / GCP / Azure backlog)

25 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #563 | GCP | lifecycle | Google Kubernetes Engine: Change (November 10, 2026) | 2026-11-11 |
| #561 | GCP | lifecycle | Google Kubernetes Engine: Change (November 10, 2026) | 2026-11-11 |
| #562 | GCP | lifecycle | Google Kubernetes Engine: Change (November 10, 2026) | 2026-11-11 |
| #559 | GCP | lifecycle | Google Kubernetes Engine: Extended channel (November 10, 2026) | 2026-11-11 |
| #560 | GCP | lifecycle | Google Kubernetes Engine: No channel (deprecated) (November 10, 2026) | 2026-11-11 |
| #557 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (November 10, 2026) | 2026-11-11 |
| #558 | GCP | lifecycle | Google Kubernetes Engine: Stable channel (November 10, 2026) | 2026-11-11 |
| #540 | GCP | operation-added | GCP storage/v1: new operation storage.anywhereCaches.pause | 2026-11-09 |
| #538 | GCP | operation-added | GCP sqladmin/v1beta4: new operation sql.projects.instances.reconcileNetworking | 2026-11-08 |
| #534 | Azure | spec-commit | Azure storage: [Storage] `2027-03-07` svc version for STG105 Rust releease TypeSpec Changes (#48016) | 2026-11-07 |
| #530 | AWS | operation-added | AWS ssm: new operation RegisterDefaultHostManagementConfiguration | 2026-11-06 |
| #529 | AWS | operation-added | AWS ssm: new operation DeregisterDefaultHostManagementConfiguration | 2026-11-06 |
| #528 | Azure | spec-commit | Azure sql: Update client settings for sql release 2026-08-01-preview (#47938) | 2026-11-06 |
| #519 | GCP | lifecycle | API Gateway: Announcement (November 04, 2026) | 2026-11-05 |
| #516 | Azure | lifecycle | Retirement: Transition to Entra ID (formerly known as Azure AD) to query data from Azure Monitor application insights by March 31, 2027 | 2026-11-04 |
| #180 | Cross-cloud |  | [shared] Conformance crawl must catch: fake charts, page errors under real tiers, cross-cloud layout drift | 2026-10-29 |
| #178 | GCP |  | [gcp] Console Metrics tabs: real charts for every service (replace seeded fake sparklines) | 2026-10-29 |
| #171 | AWS |  | [aws] EventBridge: deliver to every target type through NATS (today only SQS targets) | 2026-10-28 |
| #149 | GCP |  | [gcp] Cloud Scheduler → Pub/Sub: scheduled message must reach gcloud pubsub subscriptions pull (offline appliance) | 2026-10-27 |
| #146 | GCP | lifecycle | Google Kubernetes Engine: Change (October 26, 2026) | 2026-10-27 |
| #144 | GCP | lifecycle | Google Kubernetes Engine: Stable channel (October 26, 2026) | 2026-10-27 |
| #145 | GCP | lifecycle | Google Kubernetes Engine: No channel (deprecated) (October 26, 2026) | 2026-10-27 |
| #143 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (October 26, 2026) | 2026-10-27 |
| #139 | Azure | lifecycle | Retirement: Transition to using standard tests for single-step availability testing in Azure Monitor application insights by September 30, 2028 | 2026-10-27 |
| #138 | Azure | lifecycle | Retirement: Pod name dimension in AKS pod platform metrics | 2026-10-27 |

## Nano ↔ offline parity gaps

None: both targets expose the same services, tabs and operations.

## SDK operations without a test (0 of 0)


## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
| 2026-11-11T14:12:15+00:00 | 290/292 | 6125 | 401 | 0 | 71.5% |  |
| 2026-11-11T12:22:23+00:00 | 290/291 | 6111 | 400 | 0 | 65.6% |  |
| 2026-11-11T10:33:08+00:00 | 289/290 | 6083 | 400 | 0 | 59.1% |  |
| 2026-11-11T08:46:10+00:00 | 288/289 | 6069 | 400 | 0 | 58.1% |  |
| 2026-11-11T07:00:43+00:00 | 288/289 | 6067 | 400 | 0 | 58.1% |  |
| 2026-11-11T05:12:04+00:00 | 288/289 | 6065 | 400 | 0 | 58.1% |  |
| 2026-11-11T03:25:41+00:00 | 288/289 | 6065 | 400 | 0 | 58.1% |  |
| 2026-11-11T01:38:42+00:00 | 288/289 | 6065 | 400 | 0 | 58.1% |  |
| 2026-11-10T23:50:16+00:00 | 288/289 | 6063 | 400 | 0 | 58.1% |  |
| 2026-11-10T22:04:05+00:00 | 288/289 | 6063 | 400 | 0 | 58.1% |  |
| 2026-11-10T20:16:40+00:00 | 287/289 | 6062 | 401 | 0 | 57.8% |  |
| 2026-11-10T18:27:17+00:00 | 291/292 | 6095 | 400 | 0 | 58.8% |  |
| 2026-11-10T16:39:44+00:00 | 288/292 | 6081 | 403 | 2 | 58.8% |  |
| 2026-11-10T14:46:30+00:00 | 290/292 | 6091 | 402 | 2 | 58.8% |  |
| 2026-11-10T12:56:46+00:00 | 291/292 | 6093 | 400 | 0 | 58.8% |  |
| 2026-11-10T11:09:39+00:00 | 291/292 | 6093 | 400 | 0 | 58.8% |  |
| 2026-11-10T09:19:23+00:00 | 291/292 | 6093 | 400 | 0 | 58.8% |  |
| 2026-11-10T07:29:26+00:00 | 291/292 | 6093 | 400 | 0 | 58.8% |  |
| 2026-11-10T05:43:07+00:00 | 208/209 | 3728 | 400 | 0 | 0.0% |  |
| 2026-11-10T03:56:55+00:00 | 291/292 | 6093 | 400 | 0 | 58.8% |  |
| 2026-11-10T02:03:04+00:00 | 290/291 | 6081 | 400 | 0 | 58.8% |  |
| 2026-11-10T00:13:09+00:00 | 288/289 | 6063 | 400 | 0 | 57.8% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
