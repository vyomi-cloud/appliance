# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-27T20:34:53+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**7 change(s), 4 actionable.**
- 🔧 `operation-changed` AWS cloudwatch: operation GetOTelEnrichment changed
- 🔧 `operation-changed` AWS cloudwatch: operation StartOTelEnrichment changed
- 🔧 `operation-changed` AWS cloudwatch: operation UpdateOTelEnrichment changed
- 🔧 `operation-changed` AWS rds: operation DeleteDBCluster changed
- · `release` cli:aws: 2.42.4 → 2.42.5
- · `release` pypi:boto3: 1.44.12 → 1.44.13
- · `release` pypi:botocore: 1.44.12 → 1.44.13

Sources that failed this run (1): maven/com.azure.resourcemanager:azure-resourcemanager-appcontainers: The read operation timed out

Filed 4 backlog issue(s) labelled `upstream-drift`; 0 pending.
