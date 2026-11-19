# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-19T21:16:50+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**17 change(s), 8 actionable.**
- 🔧 `operation-added` AWS iam: new operation UpdateOpenIDConnectProvider
- 🔧 `operation-changed` AWS iam: operation CreateOpenIDConnectProvider changed
- 🔧 `operation-changed` AWS iam: operation CreateSAMLProvider changed
- 🔧 `operation-changed` AWS iam: operation GetOpenIDConnectProvider changed
- 🔧 `operation-changed` AWS iam: operation GetSAMLProvider changed
- 🔧 `operation-changed` AWS iam: operation UpdateSAMLProvider changed
- 🔧 `operation-changed` AWS rds: operation CreateDBCluster changed
- 🔧 `operation-changed` AWS rds: operation ModifyDBCluster changed
- · `announcement` AWS Lambda now supports a 30-minute timeout for on-demand Event Functions ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-lambda-30-minute-ondemand-event-functions/))
- · `announcement` AWS License Manager now supports AWS Managed Microsoft AD (Hybrid Edition) ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/license-manager-hybrid-ad-support/))
- · `announcement` Amazon Route 53 now supports health checks for private endpoints  ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/route-53-private-endpoint-health-checks/))
- · `announcement` Amazon VPC Flow Logs now supports Amazon EKS metadata ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-vpc-flow-logs-amazon-eks-metadata/))
- · `announcement` Announcing Data as a Service for AWS Marketplace ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-marketplace-data-as-a-service/))
- · `announcement` Aurora PostgreSQL with express configuration now supports Amazon VPC ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aurora-postgresql-express-vpc/))
- · `release` cli:aws: 2.41.1 → 2.41.2
- · `release` pypi:boto3: 1.44.6 → 1.44.7
- · `release` pypi:botocore: 1.44.6 → 1.44.7

Sources that failed this run (1): maven/com.google.cloud:google-cloud-firestore: The read operation timed out

Filed 8 backlog issue(s) labelled `upstream-drift`; 0 pending.
