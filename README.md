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

15 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #516 | Azure | lifecycle | Retirement: Transition to Entra ID (formerly known as Azure AD) to query data from Azure Monitor application insights by March 31, 2027 | 2026-11-04 |
| #515 | AWS | operation-added | AWS dynamodb: new operation StartBulkPutItems | 2026-11-04 |
| #514 | AWS | operation-added | AWS dynamodb: new operation ListBulkOperations | 2026-11-04 |
| #512 | AWS | operation-added | AWS dynamodb: new operation CancelBulkOperation | 2026-11-04 |
| #513 | AWS | operation-added | AWS dynamodb: new operation DescribeBulkOperation | 2026-11-04 |
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
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
| 2026-11-04T21:28:55+00:00 | 284/286 | 6003 | 401 | 0 | 57.8% |  |
| 2026-11-04T19:20:25+00:00 | 283/286 | 5990 | 405 | 4 | 57.8% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
| 2026-11-04T06:34:24+00:00 | 278/278 | 5990 | 0 | 0 | 55.4% |  |
| 2026-11-04T04:47:31+00:00 | 278/278 | 5980 | 0 | 0 | 55.4% |  |
| 2026-11-04T02:58:58+00:00 | 277/277 | 5975 | 0 | 0 | 55.4% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
