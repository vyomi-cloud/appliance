# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-13T21:10:25+00:00

Tracking 4276 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**16 change(s), 12 actionable.**
- 🔧 `operation-added` AWS ec2: new operation AssociateNetworkingFlexCostAllocationPolicy
- 🔧 `operation-added` AWS ec2: new operation CreateNetworkingFlexCostAllocationPolicy
- 🔧 `operation-added` AWS ec2: new operation DeleteNetworkingFlexCostAllocationPolicies
- 🔧 `operation-added` AWS ec2: new operation DescribeNetworkingFlexCostAllocationPolicies
- 🔧 `operation-added` AWS ec2: new operation DescribeNetworkingFlexCostAllocationPolicyAssociations
- 🔧 `operation-added` AWS ec2: new operation DisassociateNetworkingFlexCostAllocationPolicy
- 🔧 `operation-added` AWS ec2: new operation GetNetworkingFlexCostAllocationPolicyVersions
- 🔧 `operation-added` AWS ec2: new operation ModifyNetworkingFlexCostAllocationPolicy
- 🔧 `operation-changed` AWS lambda: operation CreateFunction changed
- 🔧 `operation-changed` AWS lambda: operation PublishVersion changed
- 🔧 `operation-changed` AWS lambda: operation UpdateFunctionCode changed
- 🔧 `operation-changed` AWS lambda: operation UpdateFunctionConfiguration changed
- · `operation-changed` AWS lambda: operation GetFunctionConfiguration changed
- · `operation-changed` AWS ssm: operation CreateCloudConnector changed
- · `release` pypi:boto3: 1.44.2 → 1.44.3
- · `release` pypi:botocore: 1.44.2 → 1.44.3

Sources that failed this run (9): maven/software.amazon.awssdk:s3: The read operation timed out; maven/software.amazon.awssdk:sqs: The read operation timed out; maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.azure:azure-cosmos: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appcontainers: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-cognitiveservices: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 12 backlog issue(s) labelled `upstream-drift`; 0 pending.
