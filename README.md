# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-13T19:10:17+00:00

Tracking 4268 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**2 change(s), 0 actionable.**
- · `announcement` Amazon RDS for Oracle reduces downtime for automatic minor version upgrades and scheduled maintenance ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/rds-oracle-reduces-maintenance-downtime-for-amvu-scheduled-upgrades/))
- · `release` pypi:azure-mgmt-cognitiveservices: 14.1.0 → 15.0.0

Sources that failed this run (7): maven/software.amazon.awssdk:dynamodb: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.azure:azure-cosmos: The read operation timed out; maven/com.azure:azure-security-keyvault-secrets: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-dns: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
