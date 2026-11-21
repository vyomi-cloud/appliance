# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-21T01:16:37+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**5 change(s), 0 actionable.**
- · `announcement` AWS Network Firewall introduces automated Internet firewall in public preview ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/network-firewall-automated-internet/))
- · `announcement` Amazon RDS for Oracle now supports Replica First Patching for reduced downtime ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/rds-oracle-replica-first-patching/))
- · `announcement` Cloud Scheduler: Feature (November 20, 2026) ([link](https://docs.cloud.google.com/release-notes#November_20_2026))
- · `announcement` Cloud Storage: Feature (November 20, 2026) ([link](https://docs.cloud.google.com/release-notes#November_20_2026))
- · `release` cli:aws: 2.42.0 → 2.42.1

Sources that failed this run (3): maven/software.amazon.awssdk:dynamodb: The read operation timed out; maven/com.google.cloud:google-cloud-firestore: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appcontainers: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
