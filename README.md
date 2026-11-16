# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-16T21:12:10+00:00

Tracking 4282 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**19 change(s), 15 actionable.**
- 🔧 `operation-added` AWS ec2: new operation AssociateKmsKeyId
- 🔧 `operation-added` AWS ec2: new operation CreateTransitGatewayNetworkFunctionAttachment
- 🔧 `operation-added` AWS ec2: new operation DeleteTransitGatewayNetworkFunctionAttachment
- 🔧 `operation-added` AWS ec2: new operation DescribeTransitGatewayNetworkFunctionAttachments
- 🔧 `operation-added` AWS ec2: new operation DisassociateKmsKeyId
- 🔧 `operation-added` AWS ec2: new operation ModifyTransitGatewayNetworkFunctionAttachment
- 🔧 `operation-changed` AWS ec2: operation AcceptVpcEndpointConnections changed
- 🔧 `operation-changed` AWS ec2: operation CreateSnapshot changed
- 🔧 `operation-changed` AWS ec2: operation ModifyVpcEndpointServicePermissions changed
- 🔧 `operation-changed` AWS ec2: operation RejectVpcEndpointConnections changed
- 🔧 `operation-changed` AWS kms: operation ListKeys changed
- 🔧 `operation-changed` AWS lambda: operation CreateFunction changed
- 🔧 `operation-changed` AWS lambda: operation PublishVersion changed
- 🔧 `operation-changed` AWS lambda: operation UpdateFunctionCode changed
- 🔧 `operation-changed` AWS lambda: operation UpdateFunctionConfiguration changed
- · `announcement`  Set up, connect, and govern AI agents faster with Amazon WorkSpaces ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-workspaces-AI-agents-connect-govern))
- · `operation-changed` AWS lambda: operation GetFunctionConfiguration changed
- · `release` pypi:boto3: 1.44.3 → 1.44.4
- · `release` pypi:botocore: 1.44.3 → 1.44.4

Filed 11 backlog issue(s) labelled `upstream-drift`; 0 pending.
