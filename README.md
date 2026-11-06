# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-06T21:08:11+00:00

Tracking 4258 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**8 change(s), 2 actionable.**
- 🔧 `operation-added` AWS ssm: new operation DeregisterDefaultHostManagementConfiguration
- 🔧 `operation-added` AWS ssm: new operation RegisterDefaultHostManagementConfiguration
- · `release` cli:aws: 2.39.5 → 2.39.6
- · `release` go:github.com/aws/aws-sdk-go-v2/service/dynamodb: v1.73.1 → v1.73.2
- · `release` go:github.com/aws/aws-sdk-go-v2/service/s3: v1.114.8 → v1.114.9
- · `release` go:github.com/aws/aws-sdk-go-v2/service/sqs: v1.52.10 → v1.52.11
- · `release` pypi:boto3: 1.43.125 → 1.43.126
- · `release` pypi:botocore: 1.43.125 → 1.43.126

Filed 2 backlog issue(s) labelled `upstream-drift`; 0 pending.
