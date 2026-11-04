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

64 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #502 | Azure | spec-commit | Azure cosmos-db: Add 2026-07-15 stable API version for Cosmos DB (#45986) | 2026-11-03 |
| #500 | Azure | spec-commit | Azure cognitiveservices: [CognitiveServices] Add project tool controls and private CA trust to 2026-09-15-preview (#47492) | 2026-11-03 |
| #499 | Azure | spec-commit | Azure web: [Microsoft.Web] Introduce new api version "2026-08-01" and new resource type "Microsoft.Web/sites/silos", "Microsoft.Web/serverfarms/silos", "Microsoft.Web/sites/managedTrafficConfig/default", ""Micro | 2026-11-03 |
| #340 | Azure | spec-commit | Azure compute: WorkloadManager: correct 2026-11-01-preview resource contract (#47558) | 2026-10-30 |
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
| 2026-11-04T06:34:24+00:00 | 278/278 | 5990 | 0 | 0 | 55.4% |  |
| 2026-11-04T04:47:31+00:00 | 278/278 | 5980 | 0 | 0 | 55.4% |  |
| 2026-11-04T02:58:58+00:00 | 277/277 | 5975 | 0 | 0 | 55.4% |  |
| 2026-11-04T01:01:24+00:00 | 274/277 | 5970 | 4 | 3 | 55.4% |  |
| 2026-11-03T22:59:53+00:00 | 269/277 | 5931 | 15 | 0 | 55.4% |  |
| 2026-11-03T20:49:26+00:00 | 268/277 | 5930 | 16 | 0 | 55.4% |  |
| 2026-11-03T18:42:53+00:00 | 283/286 | 6012 | 402 | 2 | 57.8% |  |
| 2026-11-03T16:42:06+00:00 | 285/286 | 6023 | 400 | 0 | 57.8% |  |
| 2026-11-03T14:52:53+00:00 | 285/286 | 6023 | 400 | 0 | 57.8% |  |
| 2026-11-03T13:04:52+00:00 | 285/286 | 6023 | 400 | 0 | 57.8% |  |
| 2026-11-03T11:13:26+00:00 | 283/285 | 6006 | 402 | 2 | 57.8% |  |
| 2026-11-03T09:25:17+00:00 | 282/284 | 5999 | 402 | 2 | 57.8% |  |
| 2026-11-03T07:33:01+00:00 | 281/283 | 5994 | 402 | 2 | 56.7% |  |
| 2026-11-03T05:41:26+00:00 | 280/282 | 5978 | 402 | 2 | 55.4% |  |
| 2026-11-03T03:40:09+00:00 | 279/282 | 5976 | 403 | 2 | 55.4% |  |
| 2026-11-03T01:44:15+00:00 | 277/281 | 5971 | 404 | 2 | 55.4% |  |
| 2026-11-02T23:57:39+00:00 | 276/278 | 5946 | 402 | 2 | 55.4% |  |
| 2026-11-02T21:58:12+00:00 | 272/277 | 5912 | 405 | 2 | 55.4% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
