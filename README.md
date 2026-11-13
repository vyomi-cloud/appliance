# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-13T18:10:18+00:00

Tracking 4268 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**2 change(s), 1 actionable.**
- 🔧 `spec-commit` Azure web: [Microsoft.Web] Introduce api version 2026-09-01 and VirtualConnections Entity (#45406) ([link](https://github.com/Azure/azure-rest-api-specs/commit/5489588d840c97097d653b15566cb73f003205cb))
- · `announcement` Announcing Accelerated Compute Insights for Amazon CloudWatch ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/accelerated-compute-insights-cloudwatch/))

Sources that failed this run (12): maven/software.amazon.awssdk:s3: The read operation timed out; maven/software.amazon.awssdk:dynamodb: The read operation timed out; maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.google.cloud:google-cloud-firestore: The read operation timed out; maven/com.azure:azure-storage-blob: The read operation timed out; maven/com.azure:azure-security-keyvault-secrets: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appcontainers: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-cognitiveservices: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
