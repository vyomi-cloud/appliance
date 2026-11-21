# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-21T00:16:35+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**6 change(s), 2 actionable.**
- 🔧 `spec-commit` Azure compute: Document planned deprecation of VM agent platform updates (#48364) ([link](https://github.com/Azure/azure-rest-api-specs/commit/dc95922996b3528c75a471eaa5e37b3e753dbed4))
- 🔧 `lifecycle` Retirement: Support for Azure Functions OpenAI Extension ends on April 20, 2027 ([link](https://azure.microsoft.com/updates?id=579952))
- · `announcement` AWS Backup now supports incremental backups for Amazon DynamoDB ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-backup-incremental-backups-dynamodb/))
- · `announcement` Amazon Cognito extends multi-Region replication to additional AWS Regions ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/cognito-mrr-opt-in-regions/))
- · `announcement` Amazon RDS for Oracle now supports Primary Endpoint ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/rds-oracle-primary-endpoint-v2/))
- · `announcement` Amazon SageMaker adds new capabilities – improved blueprints and catalog experience, simplified data quality monitoring, and support for DuckDB 2.0 and DuckDB extensions ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-sagemaker-adds-new-capabilities/))

Sources that failed this run (1): maven/com.google.cloud:google-cloud-storage: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
