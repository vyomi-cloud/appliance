# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-20T21:16:27+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**13 change(s), 2 actionable.**
- 🔧 `operation-changed` AWS ssm: operation CreateDocument changed
- 🔧 `operation-changed` AWS ssm: operation UpdateDocument changed
- · `announcement` AWS Lambda MicroVMs is now available in 7 additional AWS regions ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/aws-lambda-microvms-7-regions))
- · `announcement` AgentCore runtime instances now support Amazon EC2 G7 instances ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/agentcore-ec2-g7/))
- · `announcement` Amazon CloudWatch Observability EKS add-on now supports custom OpenTelemetry and Prometheus telemetry ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/cloudwatch-eks-addon-custom-telemetry/))
- · `announcement` Amazon DynamoDB vector search now supports new inline filter operators  ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/dynamodb-vector-filters/))
- · `announcement` Amazon S3 Vectors raises the filterable metadata limit to 40 KB per vector ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-s3-vectors-raises-filterable-metadata-40kb-per-vector/))
- · `announcement` Amazon Transcribe announces a synchronous transcription API ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-transcribe-sync-api/))
- · `announcement` Amazon Transcribe now available in AWS European Sovereign Cloud ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-transcribe-germany/))
- · `announcement` IAM Roles Anywhere now supports aliases to simplify workload configuration ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/iam-roles-anywhere-alias/))
- · `release` cli:aws: 2.41.2 → 2.42.0
- · `release` pypi:boto3: 1.44.7 → 1.44.8
- · `release` pypi:botocore: 1.44.7 → 1.44.8

Filed 2 backlog issue(s) labelled `upstream-drift`; 0 pending.
