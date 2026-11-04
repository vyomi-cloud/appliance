# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-04T22:07:06+00:00

Tracking 4256 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**21 change(s), 5 actionable.**
- 🔧 `operation-added` AWS dynamodb: new operation CancelBulkOperation
- 🔧 `operation-added` AWS dynamodb: new operation DescribeBulkOperation
- 🔧 `operation-added` AWS dynamodb: new operation ListBulkOperations
- 🔧 `operation-added` AWS dynamodb: new operation StartBulkPutItems
- 🔧 `lifecycle` Retirement: Transition to Entra ID (formerly known as Azure AD) to query data from Azure Monitor application insights by March 31, 2027 ([link](https://azure.microsoft.com/updates?id=transition-to-azure-ad-to-query-data-from-azure-monitor-application-insights-by-31-march-2026))
- · `announcement` AWS DataSync Enhanced mode supports OpenID Connect (OIDC) for Google Cloud and Microsoft Azure ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/datasync-enhanced-oidc-google-azure/))
- · `operation-changed` AWS rds: operation CopyDBSnapshot changed
- · `announcement` Amazon CloudWatch now supports API keys for OpenTelemetry traces ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-cloudwatch-api-keys-opentelemetry/))
- · `announcement` Amazon DocumentDB (with MongoDB compatibility) is now available in the Asia Pacific (Taipei) and Asia Pacific (New Zealand) Regions ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-documentdb-mongodb-compatibility-asia-pacific-taipei-new-zealand-regions/))
- · `announcement` Amazon EC2 and VPC now display related resources for all resource types ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/ec2-vpc-related-resources-all-types/))
- · `announcement` Amazon RDS for Oracle now supports copying option groups during cross-Region snapshot copy ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-rds-oracle-cross-region-snapshot-copy-option-group/))
- · `announcement` New features for Amazon EC2 Capacity Manager ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/ec2-capacity-manager-supportability-and-fulfillment/))
- · `announcement` [In preview] Public Preview: Multi-disk crash-consistent VM restore points for Premium SSD v2 and Ultra Disks on VMs with SCSI disk controller ([link](https://azure.microsoft.com/updates?id=579162))
- · `announcement` Virtual Private Cloud: Feature (November 03, 2026) ([link](https://docs.cloud.google.com/release-notes#November_03_2026))
- · `release` cli:aws: 2.39.3 → 2.39.4
- · `release` go:cloud.google.com/go/pubsub: v1.51.1 → v1.52.0
- · `release` go:github.com/aws/aws-sdk-go-v2/service/dynamodb: v1.72.3 → v1.73.0
- · `release` go:github.com/aws/aws-sdk-go-v2/service/s3: v1.114.6 → v1.114.7
- · `release` go:github.com/aws/aws-sdk-go-v2/service/sqs: v1.52.8 → v1.52.9
- · `release` pypi:boto3: 1.43.123 → 1.43.124
- · `release` pypi:botocore: 1.43.123 → 1.43.124

Filed 5 backlog issue(s) labelled `upstream-drift`; 0 pending.
