# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-21T02:16:40+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**6 change(s), 0 actionable.**
- · `announcement` AWS Lambda now provides cost optimization recommendations for Event Functions ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-lambda-cost-optimization-recommendations/))
- · `announcement` AWS Lambda now supports a batch size of up to 10,000 messages for Amazon SQS FIFO queues ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-lambda-10K-batch-size-SQSFIFO/))
- · `announcement` Amazon CloudWatch Omni now supports Microsoft Azure platform logs, metrics and traces ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-cloudwatch-omni-microsoft-azure))
- · `announcement` Amazon VPC IPAM policies now support automated internet firewall and AWS Lambda Web Functions and MicroVMs ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/vpc-ipam-policies-firewall-lambda/))
- · `release` pypi:boto3: 1.44.8 → 1.44.9
- · `release` pypi:botocore: 1.44.8 → 1.44.9

Sources that failed this run (2): maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-dns: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
