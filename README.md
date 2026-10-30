# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-30T23:47:41+00:00

Tracking 4252 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**9 change(s), 1 actionable.**
- 🔧 `spec-commit` Azure compute: WorkloadManager: correct 2026-11-01-preview resource contract (#47558) ([link](https://github.com/Azure/azure-rest-api-specs/commit/411fb227a905864f972d26ab88b21ef69e1f67b2))
- · `announcement` Managed Prometheus collectors now support Amazon MSK consumer-group metrics ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/prometheus-collectors-msk-metrics/))
- · `spec-commit` Azure storage: Remove known-encoding suppressions immediately before rfc7231 in storage TypeSpec (#47794) ([link](https://github.com/Azure/azure-rest-api-specs/commit/759a12cf1df0cefd32ecc0968a3f201b905c02e2))
- · `spec-commit` Azure storage: STG105 add handwritten swaggers for new api version (#47761) ([link](https://github.com/Azure/azure-rest-api-specs/commit/418fc8bf77b536fe624f81f60212aa5a12569354))
- · `spec-commit` Azure storage: Storage STG105 (TypeSpec) (#47158) ([link](https://github.com/Azure/azure-rest-api-specs/commit/e92d56507558ffba90b5a9362d2ae4b64fdf4592))
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed

Sources that failed this run (1): maven/com.azure.resourcemanager:azure-resourcemanager-dns: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
