# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-28T22:50:53+00:00

Tracking 3924 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**7 change(s), 4 actionable.**
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed
- 🔧 `operation-changed` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed
- · `announcement` Amazon RDS for Oracle now supports September 2026 Monthly Recommended Patch ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/amazon-rds-oracle-september-mrp))
- · `spec-commit` Azure network: Consolidate Network C# resource helpers and client names (#47689) ([link](https://github.com/Azure/azure-rest-api-specs/commit/280ac250381ac5489d68612b067b29f48fc5e03c))
- · `spec-commit` Azure servicebus: fix: improve Service Bus administration Swagger interoperability (#47269) ([link](https://github.com/Azure/azure-rest-api-specs/commit/1758295d22b6a143bb74383febd0c3f6bccfeda5))

Sources that failed this run (1): maven/com.azure.resourcemanager:azure-resourcemanager-cognitiveservices: The read operation timed out

Filed 4 backlog issue(s) labelled `upstream-drift`; 0 pending.
