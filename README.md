# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-11T01:59:59+00:00

Tracking 4258 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**2 change(s), 1 actionable.**
- 🔧 `operation-added` GCP storage/v1: new operation storage.anywhereCaches.pause
- · `spec-commit` Azure apimanagement: Fix API Management nested resource operation identities (#47949) ([link](https://github.com/Azure/azure-rest-api-specs/commit/f5d8b5a7cd1a6abf2a38c39ada5be61035d4aafe))

Sources that failed this run (1): maven/software.amazon.awssdk:sqs: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
