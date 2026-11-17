# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-17T21:12:40+00:00

Tracking 4298 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**95 change(s), 25 actionable.**
- 🔧 `operation-changed` AWS apigateway: operation CreateAuthorizer changed
- 🔧 `operation-added` AWS ec2: new operation ModifyTransitGatewayPeeringAttachment
- 🔧 `operation-changed` AWS ec2: operation CreateVpcPeeringConnection changed
- 🔧 `operation-changed` AWS ec2: operation DescribeCapacityBlockOfferings changed
- 🔧 `operation-changed` AWS ec2: operation PurchaseCapacityBlock changed
- 🔧 `operation-added` AWS kinesis: new operation AcknowledgeDeadLetterQueueRecords
- 🔧 `operation-added` AWS kinesis: new operation AcknowledgeQueueRecords
- 🔧 `operation-added` AWS kinesis: new operation CreateQueue
- 🔧 `operation-added` AWS kinesis: new operation DeleteQueue
- 🔧 `operation-added` AWS kinesis: new operation DescribeQueue
- 🔧 `operation-added` AWS kinesis: new operation ListQueues
- 🔧 `operation-added` AWS kinesis: new operation ReceiveDeadLetterQueueRecords
- 🔧 `operation-added` AWS kinesis: new operation ReceiveQueueRecords
- 🔧 `operation-added` AWS kinesis: new operation RestoreDeadLetterQueueRecords
- 🔧 `operation-added` AWS kinesis: new operation UpdateDeadLetterQueueRecordsVisibility
- 🔧 `operation-added` AWS kinesis: new operation UpdateQueue
- 🔧 `operation-added` AWS kinesis: new operation UpdateQueueRecordsVisibility
- 🔧 `operation-added` AWS lambda: new operation DeleteDurableExecution
- 🔧 `operation-added` AWS lambda: new operation PauseDurableExecution
- 🔧 `operation-added` AWS lambda: new operation ResumeDurableExecution
- 🔧 `operation-changed` AWS s3: operation AbortMultipartUpload changed
- 🔧 `operation-changed` AWS s3: operation CreateMultipartUpload changed
- 🔧 `operation-changed` AWS s3: operation ListParts changed
- 🔧 `operation-changed` AWS s3: operation UploadPart changed
- 🔧 `operation-changed` AWS s3: operation UploadPartCopy changed
- · `announcement` AWS Security Hub Network Scanning now supports scanning Amazon Relational Database Service (Amazon RDS) database instances ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/security-hub-network-scanning-rds/))
- · `announcement` AWS Security Hub now detects when vulnerable software is running on Amazon EC2 instances ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/security-hub-detects-vulnerable-software/))
- · `announcement` AWS Transit Gateway now shares resource context with firewalls for segmentation policies ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/transit-gateway-firewall-context-sharing/))
- · `operation-changed` AWS apigateway: operation GetAuthorizer changed
- · `operation-changed` AWS apigateway: operation UpdateAuthorizer changed
- · `operation-changed` AWS lambda: operation GetDurableExecution changed
- · `announcement` Amazon SageMaker now supports AI data preparation capabilities to build high-quality datasets for model development ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/sagemaker-ai-data-prep-capabilities/))
- · `announcement` [In development] Private Preview: Azure confidential VMs on 5th Gen AMD EPYC processors (DCasv7 and ECasv7 series) ([link](https://azure.microsoft.com/updates?id=581199))
- · `announcement` [In preview] Public Preview:  AI-assisted data modeler and other updates in Azure Cosmos DB extension for VS Code  ([link](https://azure.microsoft.com/updates?id=578444))
- · `announcement` [In preview] Public Preview: Azure Artifact Validation for VM images ([link](https://azure.microsoft.com/updates?id=581249))
- · `announcement` [In preview] Public Preview: Azure Blob Storage turbo tier ([link](https://azure.microsoft.com/updates?id=579031))
- · `announcement` [In preview] Public Preview: Azure Compute Spot plus ([link](https://azure.microsoft.com/updates?id=581145))
- · `announcement` [In preview] Public Preview: Azure Functions Network Troubleshooter v2 ([link](https://azure.microsoft.com/updates?id=578980))
- · `announcement` [In preview] Public Preview: Azure Functions support for Node.js 26 ([link](https://azure.microsoft.com/updates?id=578807))
- · `announcement` [In preview] Public Preview: Azure Functions support for Python 3.15 ([link](https://azure.microsoft.com/updates?id=578802))
- · `announcement` [In preview] Public Preview: Azure Monitor traces and Trace Analytics ([link](https://azure.microsoft.com/updates?id=580184))
- · `announcement` [In preview] Public Preview: Azure Network Watcher – Packet capture insights ([link](https://azure.microsoft.com/updates?id=578172))
- · `announcement` [In preview] Public Preview: Azure SQL Database container provisioning in SQL Server Management Studio ([link](https://azure.microsoft.com/updates?id=579665))
- · `announcement` [In preview] Public Preview: Azure SQL updates for mid-November 2026  ([link](https://azure.microsoft.com/updates?id=579359))
- · `announcement` [In preview] Public Preview: Bring-your-own image and Cosmos DB MCP server in Azure Connector Namespace hosted MCP​ ([link](https://azure.microsoft.com/updates?id=579435))
- · `announcement` [In preview] Public Preview: Build with Azure SQL Database container locally without an Azure subscription or credit card  ([link](https://azure.microsoft.com/updates?id=579525))
- · `announcement` [In preview] Public Preview: Compute templates for Azure ([link](https://azure.microsoft.com/updates?id=580624))
- · `announcement` [In preview] Public Preview: Durable Task SDK for Go  ([link](https://azure.microsoft.com/updates?id=578748))
- · `announcement` [In preview] Public Preview: Embedding generation in Azure Cosmos DB  ([link](https://azure.microsoft.com/updates?id=578049))
- · `announcement` [In preview] Public Preview: Fine-grained role-based access control for databases and collections in Azure DocumentDB  ([link](https://azure.microsoft.com/updates?id=578262))
- · `announcement` [In preview] Public Preview: Hosted Skill and Agent Bindings for Azure Functions ([link](https://azure.microsoft.com/updates?id=578845))
- · `announcement` [In preview] Public Preview: MSSQL extension for Visual Studio Code - local-to-cloud deployment wizard  ([link](https://azure.microsoft.com/updates?id=579014))
- · `announcement` [In preview] Public Preview: MSSQL extension for Visual Studio Code performance dashboard  ([link](https://azure.microsoft.com/updates?id=579004))
- · `announcement` [In preview] Public Preview: MSSQL extension for Visual Studio Code- Azure SQL Database container provisioning  ([link](https://azure.microsoft.com/updates?id=579009))
- · `announcement` [In preview] Public Preview: Managed MCP Server in Azure Cosmos DB  ([link](https://azure.microsoft.com/updates?id=578434))
- · `announcement` [In preview] Public Preview: Native disaster recovery for Azure Functions durable task scheduler ([link](https://azure.microsoft.com/updates?id=578762))
- · `announcement` [In preview] Public Preview: Network Watcher Private Link support ([link](https://azure.microsoft.com/updates?id=578792))
- · `announcement` [In preview] Public Preview: OS-level dependency support via containers for Azure Functions Flex Consumption ([link](https://azure.microsoft.com/updates?id=578975))
- · `announcement` [In preview] Public Preview: Session-based authentication for Azure Blob and Data Lake Storage ([link](https://azure.microsoft.com/updates?id=580306))
- · `announcement` [In preview] Public Preview: Task Queues for Azure Functions durable task scheduler ([link](https://azure.microsoft.com/updates?id=578989))
- · `announcement` [In preview] Public Preview: VM adaptive placement ([link](https://azure.microsoft.com/updates?id=581244))
- · `announcement` [In preview] Public Preview: Virtual network integration in Logic Apps Automation ([link](https://azure.microsoft.com/updates?id=580549))
- · `announcement` [Launched] Generally Available: Azure AI Gateway  ([link](https://azure.microsoft.com/updates?id=580080))
- · `announcement` [Launched] Generally Available: Azure API Management Premium v2  ([link](https://azure.microsoft.com/updates?id=580046))
- · `announcement` [Launched] Generally Available: Azure Backup for Azure Cosmos DB ([link](https://azure.microsoft.com/updates?id=579147))
- · `announcement` [Launched] Generally Available: Azure Backup for Azure Cosmos DB  ([link](https://azure.microsoft.com/updates?id=578044))
- · `announcement` [Launched] Generally Available: Azure Cosmos DB SDK for Rust  ([link](https://azure.microsoft.com/updates?id=578054))
- · `announcement` [Launched] Generally Available: Azure Cosmos DB Shell  ([link](https://azure.microsoft.com/updates?id=578439))
- · `announcement` [Launched] Generally Available: Azure Cosmos DB full-text search BM25 score projection ([link](https://azure.microsoft.com/updates?id=577531))
- · `announcement` [Launched] Generally Available: Azure Ebsv6 and Ebdsv6 ([link](https://azure.microsoft.com/updates?id=581160))
- · `announcement` [Launched] Generally Available: Azure HorizonDB Auditing ([link](https://azure.microsoft.com/updates?id=579928))
- · `announcement` [Launched] Generally Available: Azure HorizonDB Generic Log Analytics Integration ([link](https://azure.microsoft.com/updates?id=579574))
- · `announcement` [Launched] Generally Available: Azure HorizonDB Monitoring via Alerts ([link](https://azure.microsoft.com/updates?id=579933))
- · `announcement` [Launched] Generally Available: Azure Linux 4.0 ([link](https://azure.microsoft.com/updates?id=581165))
- · `announcement` [Launched] Generally Available: Azure Managed Redis database integration guidance  ([link](https://azure.microsoft.com/updates?id=577553))
- · `announcement` [Launched] Generally Available: Azure Monitor Health Models  ([link](https://azure.microsoft.com/updates?id=580261))
- · `announcement` [Launched] Generally Available: Azure SQL Managed Instance link support for availability groups with multiple databases  ([link](https://azure.microsoft.com/updates?id=578028))
- · `announcement` [Launched] Generally Available: Azure SQL Managed Instance updates for mid-November 2026  ([link](https://azure.microsoft.com/updates?id=578465))
- · `announcement` [Launched] Generally Available: Azure SQL updates for mid-November 2026  ([link](https://azure.microsoft.com/updates?id=578471))
- · `announcement` [Launched] Generally Available: Customer-managed keys for Azure Functions durable task scheduler  ([link](https://azure.microsoft.com/updates?id=578768))
- · `announcement` [Launched] Generally Available: Database Hub in Microsoft Fabric ([link](https://azure.microsoft.com/updates?id=579216))
- · `announcement` [Launched] Generally Available: Durable Task extension for Microsoft Agent Framework ([link](https://azure.microsoft.com/updates?id=578829))
- · `announcement` [Launched] Generally Available: Fuzzy string match is available across Microsoft SQL offerings  ([link](https://azure.microsoft.com/updates?id=578998))
- · `announcement` [Launched] Generally Available: Golang support on Azure Functions Flex Consumption ([link](https://azure.microsoft.com/updates?id=578812))
- · `announcement` [Launched] Generally Available: Managed Connectors in Azure Functions ([link](https://azure.microsoft.com/updates?id=579440))
- · `announcement` [Launched] Generally Available: Microsoft Agent 365 integration with Azure API Management and Azure AI Gateway  ([link](https://azure.microsoft.com/updates?id=580055))
- · `announcement` [Launched] Generally Available: Private endpoints for Azure Functions durable task scheduler  ([link](https://azure.microsoft.com/updates?id=578824))
- · `announcement` [Launched] Generally Available: Smart Tier (Azure Blob and Data Lake Storage) in Azure Government and China regions ([link](https://azure.microsoft.com/updates?id=579040))
- · `announcement` [Launched] Generally Available: Symmetric keys on Azure Key Vault Premium  ([link](https://azure.microsoft.com/updates?id=579374))
- · `announcement` [Launched] Generally Available: Transparent data encryption (TDE) in Azure SQL Database AES keys  ([link](https://azure.microsoft.com/updates?id=579531))
- · `announcement` [Launched] Generally Available: Unified Model API in Azure API Management  ([link](https://azure.microsoft.com/updates?id=580036))
- · `announcement` [Launched] Generally Available: Zone-redundant Next-gen GP tier in Azure SQL Managed Instance  ([link](https://azure.microsoft.com/updates?id=578033))
- · `announcement` Cloud Monitoring: Change (November 17, 2026) ([link](https://docs.cloud.google.com/release-notes#November_17_2026))
- · `release` pypi:boto3: 1.44.4 → 1.44.5
- · `release` pypi:botocore: 1.44.4 → 1.44.5

Filed 25 backlog issue(s) labelled `upstream-drift`; 0 pending.
