# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-12T21:09:50+00:00

Tracking 4268 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**24 change(s), 19 actionable.**
- 🔧 `operation-added` AWS cloudwatch: new operation DeleteMetricDataQueryDefinition
- 🔧 `operation-added` AWS cloudwatch: new operation GetMetricDataQueryDefinition
- 🔧 `operation-added` AWS cloudwatch: new operation ListMetricDataQueryDefinitions
- 🔧 `operation-added` AWS cloudwatch: new operation PutMetricDataQueryDefinition
- 🔧 `operation-added` AWS ec2: new operation CreateMetricCategory
- 🔧 `operation-added` AWS ec2: new operation DeleteMetricCategory
- 🔧 `operation-added` AWS ec2: new operation DescribeMetricCategories
- 🔧 `operation-added` AWS ec2: new operation ModifyMetricCategory
- 🔧 `operation-changed` AWS ec2: operation ModifyVpcEncryptionControl changed
- 🔧 `operation-changed` AWS ec2: operation MonitorInstances changed
- 🔧 `operation-changed` AWS ec2: operation UnmonitorInstances changed
- 🔧 `operation-added` AWS secretsmanager: new operation AssociateCrossAccountReplica
- 🔧 `operation-added` AWS secretsmanager: new operation DisassociateCrossAccountReplica
- 🔧 `operation-added` AWS secretsmanager: new operation ListResourcePolicies
- 🔧 `operation-changed` AWS secretsmanager: operation CreateSecret changed
- 🔧 `operation-changed` AWS secretsmanager: operation DeleteResourcePolicy changed
- 🔧 `operation-changed` AWS secretsmanager: operation DescribeSecret changed
- 🔧 `operation-changed` AWS secretsmanager: operation GetResourcePolicy changed
- 🔧 `operation-changed` AWS secretsmanager: operation PutResourcePolicy changed
- · `operation-changed` AWS ec2: operation ModifyAccountVpcEncryptionControl changed
- · `announcement` Amazon MWAA Serverless supports DuckDB operators ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-mwaa-serverless-duckdb-operators/))
- · `release` cli:aws: 2.40.1 → 2.40.2
- · `release` pypi:boto3: 1.44.1 → 1.44.2
- · `release` pypi:botocore: 1.44.1 → 1.44.2

Filed 19 backlog issue(s) labelled `upstream-drift`; 0 pending.
