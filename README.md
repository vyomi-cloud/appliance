# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-27T22:50:16+00:00

Tracking 3923 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**7 change(s), 4 actionable.**
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed
- · `spec-commit` Azure network: [Network] Update TypeSpec configuration for .NET SDK compatibility (#47643) ([link](https://github.com/Azure/azure-rest-api-specs/commit/5b3ac33ab54d588beaca346f351b95f5765e2457))
- · `spec-commit` Azure storage: Update types and auth naming for .NET (#47667) ([link](https://github.com/Azure/azure-rest-api-specs/commit/548d44095be067632e36c74969cce42472ed1431))
- · `announcement` [Launched] Generally Available: Higher limit of Azure Blob Storage accounts per region per subscription ([link](https://azure.microsoft.com/updates?id=578358))

Filed 4 backlog issue(s) labelled `upstream-drift`; 0 pending.
