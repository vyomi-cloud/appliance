# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-10T21:59:51+00:00

Tracking 4257 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**4 change(s), 0 actionable.**
- · `announcement` Amazon RDS for MySQL 26.10 is now available in Amazon RDS Database Preview Environment  ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/rds-mysql-26-10-preview-environment/))
- · `announcement` Amazon RDS for PostgreSQL announces Extended Support minor versions 13.23-rds.20260819, 12.22-rds.20260820 and 11.22-rds.20260822 ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-postgresql-extended-support/))
- · `announcement` [Launched] Generally Available: Azure Functions support for .NET 11 ([link](https://azure.microsoft.com/updates?id=578773))
- · `operation-removed` GCP storage/v1: operation storage.anywhereCaches.pause removed

Sources that failed this run (2): maven/software.amazon.awssdk:s3: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
