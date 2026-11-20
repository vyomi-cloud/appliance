# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-20T23:16:41+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**5 change(s), 1 actionable.**
- 🔧 `spec-commit` Azure compute: Document planned deprecation of VM agent platform updates (#48364) ([link](https://github.com/Azure/azure-rest-api-specs/commit/dc95922996b3528c75a471eaa5e37b3e753dbed4))
- · `announcement` AWS Lambda MicroVMs now supports customer managed keys in AWS KMS ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/lambda-microvms-customer-managed-keys/))
- · `announcement` AWS Lambda adds support for Node.js 26 ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-lambda-nodejs-26/))
- · `announcement` Amazon RDS Custom now supports the latest Cumulative Update and GDR updates for Microsoft SQL Server ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-custom-supports-latest-cumulative-update-gdr-microsoft-sql-server/))
- · `announcement` Amazon RDS for Db2 now supports new Canadian time zones ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-db2-supports-new-canadian-time))

Sources that failed this run (1): maven/com.azure:azure-security-keyvault-secrets: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
