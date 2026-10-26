# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-26T19:54:49+00:00

Tracking 3423 AWS + GCP operations, 12 Azure spec areas, 35 SDK/CLI packages and 3 lifecycle feeds.

**7 change(s), 3 actionable.**
- 🔧 `operation-added` AWS kms: new operation Decapsulate
- 🔧 `operation-added` AWS kms: new operation Encapsulate
- 🔧 `operation-changed` AWS kms: operation GetPublicKey changed
- · `announcement` AWS IAM Identity Center now supports cross-Region trusted identity propagation ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/aws-iam-identity-center-cross-region-tip/))
- · `announcement` Amazon WorkSpaces Core Managed Instances now supports ModifyVolume API ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/amazon-workspaces-cmi-modifyvolume/))
- · `release` pypi:boto3: 1.43.118 → 1.43.119
- · `release` pypi:botocore: 1.43.118 → 1.43.119

Filed 3 backlog issue(s) labelled `upstream-drift`; 0 pending.
