# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-30T19:47:35+00:00

Tracking 4252 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**13 change(s), 0 actionable.**
- · `operation-changed` AWS logs: operation DeleteAccountPolicy changed
- · `operation-changed` AWS logs: operation PutAccountPolicy changed
- · `announcement` Amazon RDS for Oracle no longer requires automatic minor version upgrades for JVM, Spatial, Locator, and OLAP options ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/oracle-jvm-spatial-locator-olap-options-amvu-optional/))
- · `spec-commit` Azure storage: STG105 add handwritten swaggers for new api version (#47761) ([link](https://github.com/Azure/azure-rest-api-specs/commit/418fc8bf77b536fe624f81f60212aa5a12569354))
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed
- · `operation-flapping` GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed
- · `release` cli:aws: 2.39.2 → 2.39.3
- · `release` go:github.com/aws/aws-sdk-go-v2/service/dynamodb: v1.72.2 → v1.72.3
- · `release` go:github.com/aws/aws-sdk-go-v2/service/sqs: v1.52.7 → v1.52.8
- · `release` pypi:boto3: 1.43.122 → 1.43.123
- · `release` pypi:botocore: 1.43.122 → 1.43.123

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
