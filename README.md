# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-10T20:59:46+00:00

Tracking 4258 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**6 change(s), 1 actionable.**
- 🔧 `operation-added` GCP storage/v1: new operation storage.anywhereCaches.pause
- · `announcement` Compute Engine: Feature (November 10, 2026) ([link](https://docs.cloud.google.com/release-notes#November_10_2026))
- · `release` go:github.com/aws/aws-sdk-go-v2/service/s3: v1.114.9 → v1.114.10
- · `release` go:github.com/aws/aws-sdk-go-v2/service/sqs: v1.52.11 → v1.53.0
- · `release` pypi:boto3: 1.43.127 → 1.44.0
- · `release` pypi:botocore: 1.43.127 → 1.44.0

Sources that failed this run (1): maven/software.amazon.awssdk:sqs: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
