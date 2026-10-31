# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-31T10:48:16+00:00

Tracking 4252 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**4 change(s), 0 actionable.**
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed

Sources that failed this run (2): maven/software.amazon.awssdk:dynamodb: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
