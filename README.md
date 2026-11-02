# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-02T21:28:17+00:00

Tracking 4252 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**8 change(s), 0 actionable.**
- · `announcement` AWS Lambda now supports queues for Apache Kafka in self-managed Kafka event sources ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-lambda-queue-kafka-esm/))
- · `announcement` Amazon CloudFront now supports self-service increases in AWS Service Quotas ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/cloudfront-self-service-quotas/))
- · `spec-commit` Azure compute: [Compute] Clarify Auto zone placement and Any-only disk alignment documentation (#47457) ([link](https://github.com/Azure/azure-rest-api-specs/commit/05ff20f36d7d4de3a774e5c6b37e1e58a66eaadf))
- · `announcement` Cloud Run functions: Feature (November 02, 2026) ([link](https://docs.cloud.google.com/release-notes#November_02_2026))
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed

Sources that failed this run (1): maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
