# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-18T21:13:09+00:00

Tracking 4298 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**8 change(s), 4 actionable.**
- 🔧 `operation-changed` AWS iam: operation CreateLoginProfile changed
- 🔧 `operation-changed` AWS iam: operation CreateRole changed
- 🔧 `operation-changed` AWS iam: operation UpdateLoginProfile changed
- 🔧 `operation-changed` AWS iam: operation UpdateRole changed
- · `announcement` Amazon RDS for MySQL now supports MySQL major version 9.7 ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-mysql-974-available/))
- · `release` go:github.com/aws/aws-sdk-go-v2/service/s3: v1.115.0 → v1.116.0
- · `release` pypi:boto3: 1.44.5 → 1.44.6
- · `release` pypi:botocore: 1.44.5 → 1.44.6

Sources that failed this run (5): maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.azure:azure-security-keyvault-secrets: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-cognitiveservices: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 4 backlog issue(s) labelled `upstream-drift`; 0 pending.
