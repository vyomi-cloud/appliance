# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-17T00:12:11+00:00

Tracking 4282 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**5 change(s), 1 actionable.**
- 🔧 `lifecycle` Amazon ECR now replicates image deletions across regions and accounts ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/replication-deletes-amazon-ecr))
- · `announcement` AWS IAM Identity Center now supports ForceAuthn in SAML requests ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/iam-identity-center-reauth/))
- · `announcement` API Gateway: Feature (November 10, 2026) ([link](https://docs.cloud.google.com/release-notes#November_10_2026))
- · `announcement` Compute Engine: Feature (November 16, 2026) ([link](https://docs.cloud.google.com/release-notes#November_16_2026))
- · `announcement` Google Kubernetes Engine: Feature (November 16, 2026) ([link](https://docs.cloud.google.com/release-notes#November_16_2026))

Sources that failed this run (1): maven/com.azure:azure-security-keyvault-secrets: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
