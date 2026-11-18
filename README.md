# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-18T18:13:04+00:00

Tracking 4298 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**3 change(s), 0 actionable.**
- · `announcement` Amazon RDS for MySQL supports MySQL minor version 8.4.13 ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-mysql-8413-available/))
- · `announcement` Amazon RDS now supports fast storage volume initialization ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-fast-storage-volume-initialization/))
- · `spec-commit` Azure keyvault: [KeyVault] Use CA initialism for EKM certificate fields in Go (#48339) ([link](https://github.com/Azure/azure-rest-api-specs/commit/4ac82504eaa646635a6305032b2c838058e1bd7d))

Sources that failed this run (3): maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
