# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-11T22:58:59+00:00

Tracking 4257 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**12 change(s), 0 actionable.**
- · `announcement` AWS Cloud WAN now supports Flow Logs ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-cloud-wan-flow-logs/))
- · `announcement` AWS Emulator is now available for building and testing AWS applications locally ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-emulator-now-available/))
- · `spec-commit` Azure authorization: Upgrade stable TypeSpec 1.18 and TypeSpec Azure 0.74 dependencies (#48161) ([link](https://github.com/Azure/azure-rest-api-specs/commit/877ddd8c245dfc007825cfb5916d841c3face3c2))
- · `spec-commit` Azure compute: [Compute Recommender] Preserve GA C# compatibility and regular IsZonal naming (#48078) ([link](https://github.com/Azure/azure-rest-api-specs/commit/0cfe0454095022e6e28fcc64775aef2e90abc227))
- · `spec-commit` Azure keyvault: Upgrade stable TypeSpec 1.18 and TypeSpec Azure 0.74 dependencies (#48161) ([link](https://github.com/Azure/azure-rest-api-specs/commit/877ddd8c245dfc007825cfb5916d841c3face3c2))
- · `spec-commit` Azure operationalinsights: Upgrade stable TypeSpec 1.18 and TypeSpec Azure 0.74 dependencies (#48161) ([link](https://github.com/Azure/azure-rest-api-specs/commit/877ddd8c245dfc007825cfb5916d841c3face3c2))
- · `spec-commit` Azure resources: Upgrade stable TypeSpec 1.18 and TypeSpec Azure 0.74 dependencies (#48161) ([link](https://github.com/Azure/azure-rest-api-specs/commit/877ddd8c245dfc007825cfb5916d841c3face3c2))
- · `spec-commit` Azure sql: Upgrade stable TypeSpec 1.18 and TypeSpec Azure 0.74 dependencies (#48161) ([link](https://github.com/Azure/azure-rest-api-specs/commit/877ddd8c245dfc007825cfb5916d841c3face3c2))
- · `spec-commit` Azure storage: Upgrade stable TypeSpec 1.18 and TypeSpec Azure 0.74 dependencies (#48161) ([link](https://github.com/Azure/azure-rest-api-specs/commit/877ddd8c245dfc007825cfb5916d841c3face3c2))
- · `announcement` Google Kubernetes Engine: Feature (November 11, 2026) ([link](https://docs.cloud.google.com/release-notes#November_11_2026))
- · `release` pypi:boto3: 1.44.0 → 1.44.1
- · `release` pypi:botocore: 1.44.0 → 1.44.1

Sources that failed this run (15): maven/software.amazon.awssdk:s3: The read operation timed out; maven/software.amazon.awssdk:dynamodb: The read operation timed out; maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.google.cloud:google-cloud-firestore: The read operation timed out; maven/com.azure:azure-storage-blob: The read operation timed out; maven/com.azure:azure-cosmos: The read operation timed out; maven/com.azure:azure-security-keyvault-secrets: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appcontainers: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
