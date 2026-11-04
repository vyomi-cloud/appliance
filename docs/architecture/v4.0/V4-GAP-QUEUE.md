# v4 gap queue: every section still showing "Not simulated in Vyomi"

Generated 2026-11-04 from `consoles/tests/gap-scan.mjs` (Playwright, text only) at `28c94126`; regenerate the queue with `consoles/tests/gap-queue.py`.
The scanner visits every route of each console (route tables, `spec-map.json`, a link crawl of sidebars/rows/tabs), runs the per-service fixtures first so detail pages have a real resource, clicks every `[role=tab]` (nested too), steps through wizards (Next) and opens the main action buttons (modals/drawers, then cancels). A finding is a distinct `[data-vyomi-not-simulated]` section (or the NotSimulated panel); it is de-duplicated by cloud + service + capability id (or feature title). `Limited in Vyomi` / `Config only` are counted separately and are NOT in this queue.

Classes: **A** buildable as a lightweight core on both substrates (offline python + Nano in-browser) | **B** belongs to a decided backend family (`V4-GAP-BACKENDS-DECISIONS.md`, family number in the label) | **C** honestly unbuildable (real-cloud-only, hardware, payments, editorial content) | **N** not a gap (state-dependent panel / unverified transient text). Size: S under a day, M a worker sitting, L several sittings or a new core.

## 1. Totals: UI badges vs the capability registry

| Cloud | Distinct Not-simulated sections in the UI | A | B | C | N | Registry `not_simulated` (offline / Nano) | Pages visited (offline / Nano) |
|---|---|---|---|---|---|---|---|
| AWS | 27 | 0 | 11 | 13 | 3 | 18 / 20 | 684 / - |
| GCP | 7 | 0 | 3 | 4 | 0 | 14 / 16 | 250 / - |
| AZURE | 29 | 5 | 16 | 8 | 0 | 32 / 32 | 1054 / - |

The registry only counts features that someone registered in `core/capabilities/<cloud>/*.json`; the UI also carries many hand-declared `NotSimulated` panels (mostly Azure blades, GCP create-wizard sections and EC2/VPC pages) that have no registry entry, hence the difference. The queue below is built from the UI, which is what the user sees.

### Per service

| Cloud | Service | Not simulated (UI) | A | B | C | N | Registry not_simulated (off/Nano) | Registry limited+config_only (offline) |
|---|---|---|---|---|---|---|---|---|
| aws | s3 | 2 | 0 | 0 | 0 | 2 | 0 / 0 | 36 |
| aws | ec2 | 3 | 0 | 2 | 1 | 0 | 1 / 2 | 29 |
| aws | iam | 1 | 0 | 0 | 1 | 0 | 1 / 1 | 22 |
| aws | apigateway | 1 | 0 | 1 | 0 | 0 | 1 / 1 | 1 |
| aws | cloudformation | 2 | 0 | 2 | 0 | 0 | 1 / 1 | 12 |
| aws | cloudwatch | 1 | 0 | 0 | 0 | 1 | 0 / 0 | 15 |
| aws | cost-explorer | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| aws | dynamodb | 2 | 0 | 1 | 1 | 0 | 3 / 3 | 21 |
| aws | eventbridge | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 14 |
| aws | kinesis | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 1 |
| aws | kms | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 3 |
| aws | lambda | 2 | 0 | 2 | 0 | 0 | 2 / 2 | 13 |
| aws | rds | 4 | 0 | 2 | 2 | 0 | 1 / 1 | 20 |
| aws | secretsmanager | 0 | 0 | 0 | 0 | 0 | 2 / 2 | 6 |
| aws | securityhub | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| aws | sns | 2 | 0 | 0 | 2 | 0 | 3 / 3 | 11 |
| aws | sqs | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 4 |
| aws | ssm | 0 | 0 | 0 | 0 | 0 | 0 / 1 | 4 |
| aws | states | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| aws | vpc | 7 | 0 | 1 | 6 | 0 | 2 / 2 | 23 |
| gcp | artifacts | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 5 |
| gcp | cloudscheduler | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| gcp | compute | 7 | 0 | 3 | 4 | 0 | 8 / 9 | 20 |
| gcp | firestore | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 7 |
| gcp | functions | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 6 |
| gcp | iam-admin | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 22 |
| gcp | kms | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 3 |
| gcp | kubernetes | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 7 |
| gcp | logs | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 5 |
| gcp | memorystore | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 3 |
| gcp | monitoring | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 19 |
| gcp | networking | 0 | 0 | 0 | 0 | 0 | 0 / 1 | 10 |
| gcp | pubsub | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 9 |
| gcp | resource-manager | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| gcp | run | 0 | 0 | 0 | 0 | 0 | 2 / 2 | 16 |
| gcp | secret-manager | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 6 |
| gcp | sql | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 9 |
| gcp | storage | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 20 |
| azure | acr | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 18 |
| azure | aks | 7 | 1 | 3 | 3 | 0 | 0 / 0 | 13 |
| azure | apim | 4 | 1 | 2 | 1 | 0 | 1 / 1 | 13 |
| azure | appconfiguration | 3 | 1 | 1 | 1 | 0 | 0 / 0 | 5 |
| azure | appservices | 13 | 2 | 9 | 2 | 0 | 3 / 3 | 16 |
| azure | cognitiveservices | 2 | 0 | 1 | 1 | 0 | 0 / 0 | 4 |
| azure | common | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 10 |
| azure | containerapps | 0 | 0 | 0 | 0 | 0 | 4 / 4 | 5 |
| azure | cosmos | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 13 |
| azure | cost | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 5 |
| azure | defender | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 5 |
| azure | dns | 0 | 0 | 0 | 0 | 0 | 2 / 2 | 2 |
| azure | entra | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 4 |
| azure | eventgrid | 0 | 0 | 0 | 0 | 0 | 3 / 3 | 9 |
| azure | functionapp | 0 | 0 | 0 | 0 | 0 | 3 / 3 | 25 |
| azure | keyvaults | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 8 |
| azure | loganalytics | 0 | 0 | 0 | 0 | 0 | 3 / 3 | 5 |
| azure | managedidentity | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 1 |
| azure | monitor | 0 | 0 | 0 | 0 | 0 | 2 / 2 | 20 |
| azure | nsgs | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 5 |
| azure | resourcegroups | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 4 |
| azure | servicebus | 0 | 0 | 0 | 0 | 0 | 2 / 2 | 11 |
| azure | sql | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 20 |
| azure | storage | 0 | 0 | 0 | 0 | 0 | 6 / 6 | 35 |
| azure | subscriptions | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 20 |
| azure | vms | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 21 |
| azure | vnets | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 15 |

Limited / Config-only badges actually rendered (distinct capability ids seen in the UI, offline run): AWS 163, GCP 15, AZURE 68. Per-service lists are in the scan JSON (`limited`).

## 2. S3, EC2 and IAM in full (the user's complaint)

### AWS S3 (2 sections)

| Section | Where | Class | Size | Family / deps | Batch |
|---|---|---|---|---|---|
| Object Lock legal hold | `#/s3/object/uic-bucket` | N | S | - | AWS-14 |
| Object Lock retention | `#/s3/object/uic-bucket` | N | S | - | AWS-14 |

### AWS EC2 (3 sections)

| Section | Where | Class | Size | Family / deps | Batch |
|---|---|---|---|---|---|
| EC2 Image Builder | `#/ec2/image-builder` | B | L | cicd-source; needs buildkit | AWS-06 |
| Migrate a server | `#/ec2/migrate-a-server` | B | L | data-analytics | AWS-06 |
| UltraServers | `#/ec2/ultraservers` | C | S | - | AWS-14 |

### AWS IAM (1 sections)

| Section | Where | Class | Size | Family / deps | Batch |
|---|---|---|---|---|---|
| Role manager | `#/iam/account-settings` | C | S | - | AWS-07 |

Notes: (1) EC2 instance detail tabs could not be reached on the macOS offline run (`RunInstances` fails: "AMI ... is not supported on darwin"); they were scanned on **Nano**, where instances launch, so the two EC2 metrics tabs below appear only from the Nano run (they exist on offline too). (2) The S3 Object Lock legal-hold/retention panels render only for a bucket WITHOUT Object Lock; on a lock-enabled bucket they are real, so they are class N. (3) IAM shows only 3 sections: IAM is largely implemented after the IAM/Organizations sweeps.

## 3. Work batches (in execution order)

Order: AWS (S3, EC2, IAM first, then the rest), then GCP, then Azure; class A before B before C. One batch = about one worker sitting (a few related work packages; each package lists every section it closes).

### AWS-01 S3 buildable gaps: Metadata tables, Storage Lens metrics, S3 Vectors

Classes:  | work packages: 0 | sections closed: 0 | S3 first (user complaint)


### AWS-02 S3 decided-backend + editorial: file systems, FSx access points, Transfer acceleration, Marketplace, Get started

Classes:  | work packages: 0 | sections closed: 0


### AWS-03 EC2 dashboard + ops (zones, alarms, events, health rollup, EBS fault tolerance, IAM profile)

Classes:  | work packages: 0 | sections closed: 0


### AWS-04 EC2 tools + purchasing (compare SG, type finder, Recycle Bin, Auto Scaling settings, Spot/capacity)

Classes:  | work packages: 0 | sections closed: 0


### AWS-05 EC2 reach-in + telemetry: Connect (SSH) and instance/volume metrics

Classes:  | work packages: 0 | sections closed: 0 | decided families #1 and #3


### AWS-06 EC2 marketplace/builder/migration/RAM/cost

Classes: B | work packages: 2 | sections closed: 2

- [ ] **EC2 Image Builder pipelines**: class B, family: cicd-source; needs: buildkit; size L (1 section)
  - ec2: EC2 Image Builder (`#/ec2/image-builder`)
- [ ] **Migrate a server (Application Migration Service)**: class B, family: data-analytics; size L (1 section)
  - ec2: Migrate a server (`#/ec2/migrate-a-server`)

### AWS-07 CloudTrail core + IAM gaps (service access report, CloudFront key pairs, Role manager) + S3 data events

Classes: C | work packages: 1 | sections closed: 1 | IAM third; CloudTrail core unblocks S3 and IAM

- [ ] **IAM Role manager (no public API in AWS)**: class C, size S (1 section)
  - iam: Role manager (`#/iam/account-settings`) [iam.organizations.role-manager]

### AWS-08 EventBridge + CloudFormation + Secrets A items

Classes:  | work packages: 0 | sections closed: 0


### AWS-09 RDS + DynamoDB + Lambda + SNS + VPC A items

Classes:  | work packages: 0 | sections closed: 0


### AWS-10 Visual canvas component (CFN Template Studio, EventBridge builder, Lambda Composer)

Classes:  | work packages: 0 | sections closed: 0 | one shared UI component


### AWS-11 AWS observability + security + billing family: RDS metrics, Security Hub, Cost Explorer

Classes: B | work packages: 1 | sections closed: 1 | families #3 #4 #9

- [ ] **RDS instance metrics (CPU/memory/storage) + Database Insights**: class B, family: observability; needs: docker-stats-to-cloudwatch; size M (1 section)
  - rds: Database Insights metrics (`#/rds/create-database`)

### AWS-12 AWS networking + CI/CD family: VPC Lattice, Network Firewall containers, CloudFormation Git sync, Lambda CI/CD

Classes: B | work packages: 3 | sections closed: 3 | families #5 #2

- [ ] **Network Firewall container associations**: class B, family: networking-dataplane; needs: netsim; size M (1 section)
  - vpc: Container associations (`#/vpc/container-associations`) [aws.vpc.network-firewall-containers]
- [ ] **CloudFormation Git sync**: class B, family: cicd-source; needs: gitea; size M (1 section)
  - cloudformation: Git sync (`#/cloudformation/stacks/gs8pzh8`)
- [ ] **Lambda CI/CD pipeline application**: class B, family: cicd-source; needs: buildkit, gitea; size L (1 section)
  - lambda: CI/CD pipeline application (`#/lambda/create/application`) [lambda.application.cicd-pipeline]

### AWS-13 AWS data / directory / marketplace / local-LLM family: DMS, zero-ETL, SNS SMS, StackSets orgs, CFN registry, partner sources, AgentCore

Classes: B | work packages: 3 | sections closed: 5 | families #6 #7 #8 #11

- [ ] **Zero-ETL integrations (DynamoDB/RDS to Redshift/lakehouse)**: class B, family: data-analytics; size L (2 sections)
  - dynamodb: Integrations (`#/dynamodb/integrations`) [dynamodb.account.zero-etl]
  - rds: Create zero-ETL integration (`#/rds/create-zero-etl-integration`)
- [ ] **CloudFormation public extensions / publisher registry**: class B, family: marketplace-saas; size L (1 section)
  - cloudformation: Filters (`#/cloudformation/spotlight`)
- [ ] **Lambda/AgentCore agent onboarding + AgentCore targets**: class B, family: local-llm; needs: local-llm; size L (2 sections)
  - apigateway: AgentCore targets (`#/apigateway/agentcore-targets`) [apigateway.agentcore-targets]
  - lambda: Set up your agent to build with Lambda (`#/lambda`) [lambda.dashboard.agent-onboarding]

### AWS-14 AWS unbuildable / editorial / verify

Classes: C/N | work packages: 8 | sections closed: 15 | class C and N

- [ ] **EC2 UltraServers (multi-host accelerator domains: hardware)**: class C, size S (1 section)
  - ec2: UltraServers (`#/ec2/ultraservers`) [ec2.purchasing.ultraservers]
- [ ] **Reserved capacity purchase (billing/payment)**: class C, size S (1 section)
  - dynamodb: Reserved capacity (`#/dynamodb/reserved-capacity`) [dynamodb.account.reserved-capacity]
- [ ] **RDS capacity reservations (capacity-market / billing construct)**: class C, size S (1 section)
  - rds: Create capacity reservation (`#/rds/capacity-reservations`)
- [ ] **SNS settings that do not exist in the real API (max message size, TTL)**: class C, size S (2 sections)
  - sns: Maximum message size (`#/sns/create-topic`) [sns.topic.max-message-size]
  - sns: Time to Live (TTL) - optional (`#/sns/topics/gs7crds/publish`) [sns.publish.ttl]
- [ ] **Network Manager / external console link-outs**: class C, size S (2 sections)
  - vpc: AWS Network Manager (`#/vpc`)
  - vpc: Integrations (`#/vpc/vpcs/vpc-0bb695c3c5af`) [aws.vpc.integrations]
- [ ] **Region-wide service health (AWS-side events)**: class C, size S (5 sections)
  - rds: The page /rds/service-health (`#/rds/service-health`)
  - vpc: Linked AWS documentation (`#/vpc`)
  - vpc: Linked AWS forums (`#/vpc`)
  - vpc: Linked issue reporting (`#/vpc`)
  - vpc: Service health dashboard (`#/vpc`)
- [ ] **Object Lock panels (render only when the bucket has no lock; verified real on a locked bucket)**: class N, size S (2 sections)
  - s3: Object Lock legal hold (`#/s3/object/uic-bucket`)
  - s3: Object Lock retention (`#/s3/object/uic-bucket`)
- [ ] **Transient 'Not simulated' text without the data attribute (state-dependent / mid-render); re-check**: class N, size S (1 section)
  - cloudwatch: #/cloudwatch/alarms/create (`#/cloudwatch/alarms/create`)

### GCP-01 Compute A: recommender, schedules, backups/snapshots, NIC/NEG, sole-tenant/reservations

Classes:  | work packages: 0 | sections closed: 0


### GCP-02 Run/Functions A: autoscaling, probes, volumes, SQL connections, BinAuthz/CMEK, Eventarc, image picker

Classes:  | work packages: 0 | sections closed: 0


### GCP-03 Identity/data A: org-policy simulation, workload identity federation, Firestore rules, Logs correlate, Datastore, GCS config, SQL flags, KMS import

Classes:  | work packages: 0 | sections closed: 0


### GCP-04 GCP SSH + observability + security family: GCE SSH, VM Manager, Ops Agent, trace/scopes, security risk, storage security insights

Classes: B | work packages: 2 | sections closed: 2 | families #1 #3 #4

- [ ] **GCE SSH / OS info / serial (real sshd in container)**: class B, family: ssh-shell; needs: tunnel-tcp-relay; size L (1 section)
  - compute: SSH (`#/compute/instances`)
- [ ] **VM Manager: Patch, OS policies, VM extension policies (guest agent)**: class B, family: ssh-shell; needs: gce-ssh; size L (1 section)
  - compute: VM Manager (`#/compute/instances`)

### GCP-05 GCP networking + CI/CD family: VLAN/BYOIP/flow logs, Run networking, source deploy

Classes:  | work packages: 0 | sections closed: 0 | families #5 #2


### GCP-06 GCP data / directory / marketplace family: VM import, Storage Insights, Asset Inventory queries, org/folders, Marketplace

Classes: B | work packages: 1 | sections closed: 1 | families #6 #7 #8

- [ ] **Import VM / Migrate to VMs / image import-export history**: class B, family: data-analytics; size L (1 section)
  - compute: Migrate to Virtual Machines (`#/compute/migrate-to-vms`) [gcp.compute.migrate-to-vms]

### GCP-07 GCP unbuildable

Classes: C | work packages: 3 | sections closed: 4 | class C

- [ ] **Google Cloud incidents / service health**: class C, size S (1 section)
  - compute: Google Cloud incidents (`#/compute/overview`) [gcp.compute.incidents]
- [ ] **Hardware: TPUs, Bare Metal Solution, sole-tenant hardware**: class C, size S (1 section)
  - compute: TPUs (`#/compute/tpus`) [gcp.compute.tpus]
- [ ] **Committed use discounts (purchase)**: class C, size S (2 sections)
  - compute: Capacity advisor (`#/compute/capacity-advisor`) [gcp.compute.capacity-advisor]
  - compute: Committed use discounts (`#/compute/committed-use-discounts`) [gcp.compute.committed-use-discounts]

### AZ-01 Azure common blades A: export template, activity log, RBAC extras, grid tools, resource health/Advisor, diagnostic settings, visualizer

Classes:  | work packages: 0 | sections closed: 0 | cross-cutting kit components applied to every service


### AZ-02 Azure identity/crypto/policy A: managed identity, CMK, Event Grid subscriptions, Azure Policy, RG ops

Classes: A | work packages: 1 | sections closed: 1

- [ ] **User-assigned + managed identity assignment on resources**: class A, needs: managed-identity-core; size M (1 section)
  - appconfiguration: User assigned managed identities (`#/appconfiguration/uic-rg/uicappconfig/identity`)

### AZ-03 Storage + SQL + Cosmos A

Classes: A | work packages: 1 | sections closed: 1

- [ ] **Backup / recovery / geo-replication / disaster recovery (local snapshots)**: class A, size L (1 section)
  - aks: Azure Backup for AKS (`#/aks/uic-rg/uicaks/backup`)

### AZ-04 Compute/containers A: VM ops, ACR import, AKS ops, App Service/Function App ops

Classes: A | work packages: 1 | sections closed: 2

- [ ] **App Service/Function App operations: auth, certificates, autoscale, WebJobs, default docs, path mappings, health check, clone, slots config, bindings editor, invocations**: class A, size L (2 sections)
  - appservices: Database (`#/appservices/create`)
  - appservices: Secure unique default hostname on. (`#/appservices`)

### AZ-05 Azure data-plane services A: APIM, App Configuration, Key Vault, Service Bus/Event Grid, DNS, VNet, Entra, other

Classes: A | work packages: 1 | sections closed: 1

- [ ] **API Management operations: gateways, soft-delete restore, capacity**: class A, size M (1 section)
  - apim: The capacity gauge (`#/apim/uic-rg/gstnb9t`)

### AZ-06 Azure observability + security + support family: monitoring pipeline, Prometheus/Grafana/SCOM, Defender, support requests, Tasks

Classes: B | work packages: 2 | sections closed: 8 | families #3 #4 #10 #2

- [ ] **Per-resource Insights / Metrics / Alerts / Logs / Diagnostic settings / Workbooks / Log Analytics (monitoring pipeline)**: class B, family: observability; needs: observability-stack; size L (3 sections)
  - apim: Monitor + secure (`#/apim/create`)
  - appservices: Application Insights (`#/appservices/create`)
  - appservices: Events (preview) (`#/appservices/uic-rg/uicapp/events`)
- [ ] **Tasks / Automation / Logic App tasks**: class B, family: cicd-source; needs: buildkit; size L (5 sections)
  - aks: Tasks (`#/aks/uic-rg/uicaks/tasks`)
  - apim: Tasks (`#/apim/uic-rg/uicapim/tasks`)
  - appconfiguration: Tasks (`#/appconfiguration/uic-rg/uicappconfig/tasks`)
  - appservices: Tasks (`#/appservices/uic-rg/uicapp/tasks`)
  - cognitiveservices: Tasks (`#/cognitiveservices/uic-rg/uiccogsvc/tasks`)

### AZ-07 Azure networking + SSH + CI/CD family: private endpoints/Firewall/Bastion/DDoS, NSG flow logs, App Service console/Kudu, VM guest ops, Deployment Center

Classes: B | work packages: 2 | sections closed: 8 | families #5 #1 #2

- [ ] **App Service console / SSH / Kudu / process explorer / log streaming**: class B, family: ssh-shell; needs: tunnel-tcp-relay; size L (6 sections)
  - appservices: Advanced Tools (`#/appservices/uic-rg/uicapp/advancedtools`)
  - appservices: App Service Editor (Preview) (`#/appservices/uic-rg/uicapp/appeditor`)
  - appservices: Console (`#/appservices/uic-rg/uicapp/console`)
  - appservices: Extensions (`#/appservices/uic-rg/uicapp/extensions`)
  - appservices: Live log streaming (`#/appservices/uic-rg/uicapp/logstream`)
  - appservices: Process explorer (`#/appservices/uic-rg/uicapp/processexplorer`)
- [ ] **Deployment Center / GitHub Actions / GitOps / automated deployments**: class B, family: cicd-source; needs: buildkit, gitea; size L (2 sections)
  - aks: Automated deployments (GitHub Actions) (`#/aks/uic-rg/uicaks/automateddeployments`)
  - aks: Flux GitOps configurations (`#/aks/uic-rg/uicaks/gitops`)

### AZ-08 Azure data / directory / marketplace / billing family: Resource Graph, migration, Files, AI Search, subscriptions, Marketplace, Cost Management

Classes:  | work packages: 0 | sections closed: 0 | families #6 #7 #8 #9


### AZ-09 Azure unbuildable / editorial

Classes: C | work packages: 2 | sections closed: 8 | class C and N

- [ ] **Diagnose and solve problems (Azure fleet diagnostics)**: class C, size S (5 sections)
  - aks: Diagnose and solve problems (`#/aks/uic-rg/uicaks/diagnose`)
  - apim: Diagnose and solve problems (`#/apim/uic-rg/uicapim/diagnose`)
  - appconfiguration: Diagnose and solve problems (`#/appconfiguration/uic-rg/uicappconfig/diagnose`)
  - appservices: Diagnose and solve problems (`#/appservices/uic-rg/uicapp/diagnose`)
  - cognitiveservices: Diagnose and solve problems (`#/cognitiveservices/uic-rg/uiccogsvc/diagnose`)
- [ ] **Tutorials / capabilities overview / features overview / quick start / feedback / quotas docs**: class C, size S (3 sections)
  - aks: The capabilities overview (`#/aks/uic-rg/gsrypa8`)
  - aks: Tutorials (`#/aks/uic-rg/gsrypa8`)
  - appservices: The capabilities overview (`#/appservices/uic-rg/uicapp`)

## 4. Substrate differences (offline vs Nano)

- AWS: only on offline: apigateway: AgentCore targets; cloudformation: Git sync; cloudformation: Filters; cloudwatch: #/cloudwatch/alarms/create; dynamodb: Reserved capacity; dynamodb: Integrations; ec2: UltraServers; iam: Role manager; lambda: Set up your agent to build with Lambda; lambda: CI/CD pipeline application; rds: Database Insights metrics; rds: Create capacity reservation; rds: Create zero-ETL integration; s3: Object Lock legal hold; s3: Object Lock retention; sns: Maximum message size; sns: Time to Live (TTL) - optional; vpc: Service health dashboard; vpc: Linked AWS documentation; vpc: Linked AWS forums; vpc: Linked issue reporting; vpc: AWS Network Manager; vpc: Integrations; vpc: Container associations; ec2: EC2 Image Builder; ec2: Migrate a server; rds: The page /rds/service-health. Only on Nano: none.
- GCP: only on offline: compute: Google Cloud incidents; compute: SSH; compute: VM Manager; compute: TPUs; compute: Committed use discounts; compute: Capacity advisor; compute: Migrate to Virtual Machines. Only on Nano: none.
- AZURE: only on offline: aks: The capabilities overview; aks: Tutorials; aks: Diagnose and solve problems; aks: Azure Backup for AKS; aks: Flux GitOps configurations; aks: Automated deployments (GitHub Actions); aks: Tasks; apim: Monitor + secure; apim: The capacity gauge; apim: Diagnose and solve problems; apim: Tasks; appconfiguration: Diagnose and solve problems; appconfiguration: User assigned managed identities; appconfiguration: Tasks; appservices: Secure unique default hostname on.; appservices: Database; appservices: Application Insights; appservices: The capabilities overview; appservices: Diagnose and solve problems; appservices: Events (preview); appservices: Console; appservices: Advanced Tools; appservices: App Service Editor (Preview); appservices: Extensions; appservices: Live log streaming; appservices: Process explorer; appservices: Tasks; cognitiveservices: Diagnose and solve problems; cognitiveservices: Tasks. Only on Nano: none.

## 5. What the scanner could not reach

- aws/offline: pages 684; unreached parameterised routes: /cloudformation/stacks/:name/update, /ec2/instances/:id, /ec2/instances/:id/create-image, /ec2/create-snapshot/:volumeId, /ec2/security-groups/:id/edit-outbound-rules, /eventbridge/archives/:name/edit, /eventbridge/pipes/:name, /vpc/vpcs/:id/edit-settings, /vpc/security-groups/:id/edit-inbound-rules, /vpc/security-groups/:id/edit-outbound-rules, /vpc/service-networks/:id, /vpc/lattice-services/:id, /vpc/lattice-target-groups/:id, /vpc/transit-gateway-route-tables/:id; fixture errors: 6 (ec2/live-instance: POST / -> 503 <Response><Errors><Error><Code>AMI 'Amazon Linux 2023' is not supported on da...)
- azure/offline: pages 1054; unreached parameterised routes: /sql/servers/:rg/:server; fixture errors: 0
- gcp/offline: pages 250; unreached parameterised routes: /security/kms/keyring/manage/:location/:name, /security/kms/key/manage/:location/:keyring/:name, /security/secret-manager/secret/:name, /security/secret-manager/regional/:location/:name; fixture errors: 3 (iam-admin/deny-policy: POST /v2/policies/cloudresourcemanager.googleapis.com%2Fprojects%2Fvyomi-project/denypo...)
- Parameterised edit routes that need a second id (e.g. `/ec2/security-groups/:id/edit-outbound-rules`, `/vpc/vpcs/:id/edit-settings`) were visited separately with a real id (`EXTRA_ROUTES`) and show no Not-simulated sections; `/ec2/instances/:id` and `/ec2/create-snapshot/:volumeId` have no offline reach on macOS.
- Azure (2026-11-04 rescan): offline run with MAX_PAGES=4000 SHAPE_CAP=60 finished naturally at 1054 pages (no page cap hit); Nano was not re-scanned in that run.
- States that only appear after a real action (a running instance's serial console, a failed deployment, a scheduled maintenance event) are not covered; the scanner opens and cancels wizards/modals but does not submit them.

