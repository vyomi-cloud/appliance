# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-10T18:00:10+00:00

Tracking 4258 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**2 change(s), 1 actionable.**
- 🔧 `operation-added` GCP storage/v1: new operation storage.anywhereCaches.pause
- · `announcement` Amazon OpenSearch Service now lets you validate and roll back version upgrades ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-opensearch-service/upgrades/))

Sources that failed this run (2): maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
