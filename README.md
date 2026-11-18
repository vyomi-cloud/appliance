# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-18T22:14:49+00:00

Tracking 4298 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**4 change(s), 0 actionable.**
- · `announcement` Amazon Aurora DSQL now supports audit logging ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-aurora-dsql-audit-logging/))
- · `announcement` Amazon OpenSearch Ingestion Service now supports next-generation time series collections ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-opensearch-ingestion-service-nextgen-time-series-collections))
- · `announcement` Amazon OpenSearch Memory is now generally available ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-opensearch-memory-generally-available/))
- · `announcement` Amazon SageMaker AI now supports cross-Region inference routing ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/sagemaker-cross-region-routing/))

Sources that failed this run (6): maven/software.amazon.awssdk:s3: The read operation timed out; maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.azure:azure-storage-blob: The read operation timed out; maven/com.azure:azure-cosmos: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appcontainers: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
