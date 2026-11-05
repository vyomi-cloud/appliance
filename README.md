# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-05T21:07:43+00:00

Tracking 4256 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**4 change(s), 1 actionable.**
- 🔧 `spec-commit` Azure keyvault: [KeyVault] Introduce Version 2026-10-01-preview for Azure Key Vault (#47789) ([link](https://github.com/Azure/azure-rest-api-specs/commit/67d7ae2c7878c896d0ddb588e45bd90726ea2044))
- · `announcement` Amazon DynamoDB now supports bulk put items ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-dynamodb-now-supports-bulk-put-items/))
- · `release` pypi:boto3: 1.43.124 → 1.43.125
- · `release` pypi:botocore: 1.43.124 → 1.43.125

Sources that failed this run (1): maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
