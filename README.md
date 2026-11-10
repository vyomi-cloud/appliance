# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-10T19:59:44+00:00

Tracking 4257 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**5 change(s), 0 actionable.**
- · `announcement` AWS Compute Optimizer now supports additional Amazon EC2 instance types in the AWS GovCloud (US) Regions ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/aws-compute-optimizer-amazon-ec2/))
- · `spec-commit` Azure cognitiveservices: Remove Cognitive Services JavaScript contract tests (#48108) ([link](https://github.com/Azure/azure-rest-api-specs/commit/e4d2d2ae2c8f429796350ca6b443159a8991ca42))
- · `operation-removed` GCP storage/v1: operation storage.anywhereCaches.pause removed
- · `release` cli:aws: 2.39.7 → 2.40.0
- · `release` go:github.com/aws/aws-sdk-go-v2/service/dynamodb: v1.73.2 → v1.74.0

Sources that failed this run (2): maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
