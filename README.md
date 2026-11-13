# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-13T20:10:17+00:00

Tracking 4268 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**4 change(s), 1 actionable.**
- 🔧 `spec-commit` Azure apimanagement: [Microsoft.ApiManagement] Align AI Gateway 2026-11-01 contracts with control-plane consistency (#48020) ([link](https://github.com/Azure/azure-rest-api-specs/commit/f22c4322f74536073300e48109f34f16c59491d7))
- · `announcement` AWS Secrets Manager now supports cross-account replication ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/secrets-manager-cross-account/))
- · `announcement` Aurora PostgreSQL with express configuration now supported in CloudFormation ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aurora-postgresql-cloudformation/))
- · `release` cli:aws: 2.40.2 → 2.40.3

Sources that failed this run (10): maven/software.amazon.awssdk:s3: The read operation timed out; maven/software.amazon.awssdk:dynamodb: The read operation timed out; maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.google.cloud:google-cloud-firestore: The read operation timed out; maven/com.azure:azure-cosmos: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure:azure-data-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
