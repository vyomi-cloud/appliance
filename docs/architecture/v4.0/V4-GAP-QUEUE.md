# v4 gap queue: every section still showing "Not simulated in Vyomi"

Generated 2026-11-03 from `consoles/tests/gap-scan.mjs` (Playwright, text only) at `0edff635`; regenerate the queue with `consoles/tests/gap-queue.py`.
The scanner visits every route of each console (route tables, `spec-map.json`, a link crawl of sidebars/rows/tabs), runs the per-service fixtures first so detail pages have a real resource, clicks every `[role=tab]` (nested too), steps through wizards (Next) and opens the main action buttons (modals/drawers, then cancels). A finding is a distinct `[data-vyomi-not-simulated]` section (or the NotSimulated panel); it is de-duplicated by cloud + service + capability id (or feature title). `Limited in Vyomi` / `Config only` are counted separately and are NOT in this queue.

Classes: **A** buildable as a lightweight core on both substrates (offline python + Nano in-browser) | **B** belongs to a decided backend family (`V4-GAP-BACKENDS-DECISIONS.md`, family number in the label) | **C** honestly unbuildable (real-cloud-only, hardware, payments, editorial content) | **N** not a gap (state-dependent panel / unverified transient text). Size: S under a day, M a worker sitting, L several sittings or a new core.

## 1. Totals: UI badges vs the capability registry

| Cloud | Distinct Not-simulated sections in the UI | A | B | C | N | Registry `not_simulated` (offline / Nano) | Pages visited (offline / Nano) |
|---|---|---|---|---|---|---|---|
| AWS | 103 | 46 | 35 | 16 | 6 | 38 / 38 | 693 / 695 |
| GCP | 102 | 48 | 37 | 17 | 0 | 15 / 16 | 355 / 355 |
| AZURE | 478 | 234 | 207 | 36 | 1 | 59 / 59 | 2038 / 900 |

The registry only counts features that someone registered in `core/capabilities/<cloud>/*.json`; the UI also carries many hand-declared `NotSimulated` panels (mostly Azure blades, GCP create-wizard sections and EC2/VPC pages) that have no registry entry, hence the difference. The queue below is built from the UI, which is what the user sees.

### Per service

| Cloud | Service | Not simulated (UI) | A | B | C | N | Registry not_simulated (off/Nano) | Registry limited+config_only (offline) |
|---|---|---|---|---|---|---|---|---|
| aws | s3 | 11 | 4 | 4 | 1 | 2 | 6 / 6 | 28 |
| aws | ec2 | 20 | 11 | 8 | 1 | 0 | 5 / 5 | 11 |
| aws | iam | 3 | 1 | 1 | 1 | 0 | 3 / 3 | 20 |
| aws | (home) | 1 | 0 | 1 | 0 | 0 | 0 / 0 | 0 |
| aws | apigateway | 1 | 0 | 1 | 0 | 0 | 1 / 1 | 1 |
| aws | cloudformation | 12 | 4 | 8 | 0 | 0 | 2 / 2 | 8 |
| aws | cloudwatch | 1 | 0 | 0 | 0 | 1 | 0 / 0 | 15 |
| aws | cost-explorer | 1 | 0 | 1 | 0 | 0 | 0 / 0 | 0 |
| aws | dynamodb | 5 | 3 | 1 | 1 | 0 | 4 / 4 | 18 |
| aws | eventbridge | 17 | 11 | 1 | 2 | 3 | 0 / 0 | 7 |
| aws | kinesis | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 1 |
| aws | kms | 0 | 0 | 0 | 0 | 0 | 1 / 1 | 3 |
| aws | lambda | 4 | 2 | 2 | 0 | 0 | 4 / 4 | 11 |
| aws | rds | 11 | 5 | 4 | 2 | 0 | 1 / 1 | 14 |
| aws | secretsmanager | 1 | 1 | 0 | 0 | 0 | 3 / 3 | 5 |
| aws | sns | 4 | 1 | 1 | 2 | 0 | 5 / 5 | 9 |
| aws | sqs | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 4 |
| aws | ssm | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 3 |
| aws | states | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| aws | vpc | 11 | 3 | 2 | 6 | 0 | 3 / 3 | 20 |
| gcp | artifacts | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 5 |
| gcp | cloud-hub | 1 | 0 | 0 | 1 | 0 | 0 / 0 | 0 |
| gcp | cloudscheduler | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 2 |
| gcp | compute | 41 | 17 | 11 | 13 | 0 | 1 / 1 | 3 |
| gcp | dashboard | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 0 |
| gcp | datastore | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 0 |
| gcp | firestore | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 7 |
| gcp | functions | 11 | 7 | 3 | 1 | 0 | 0 / 0 | 5 |
| gcp | iam-admin | 6 | 4 | 2 | 0 | 0 | 1 / 1 | 19 |
| gcp | kms | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 3 |
| gcp | kubernetes | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 7 |
| gcp | logs | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 4 |
| gcp | memorystore | 1 | 0 | 1 | 0 | 0 | 1 / 1 | 2 |
| gcp | monitoring | 4 | 0 | 4 | 0 | 0 | 4 / 4 | 15 |
| gcp | networking | 3 | 0 | 3 | 0 | 0 | 2 / 3 | 8 |
| gcp | products | 1 | 0 | 1 | 0 | 0 | 0 / 0 | 0 |
| gcp | pubsub | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 9 |
| gcp | resource-manager | 1 | 0 | 1 | 0 | 0 | 1 / 1 | 1 |
| gcp | run | 18 | 10 | 7 | 1 | 0 | 1 / 1 | 7 |
| gcp | secret-manager | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 6 |
| gcp | security | 2 | 1 | 0 | 1 | 0 | 0 / 0 | 0 |
| gcp | sql | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 5 |
| gcp | storage | 8 | 4 | 4 | 0 | 0 | 4 / 4 | 14 |
| azure | (home) | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 0 |
| azure | acr | 10 | 5 | 5 | 0 | 0 | 1 / 1 | 17 |
| azure | aks | 26 | 12 | 11 | 3 | 0 | 0 / 0 | 9 |
| azure | apim | 12 | 7 | 4 | 1 | 0 | 1 / 1 | 11 |
| azure | appconfiguration | 20 | 13 | 6 | 1 | 0 | 0 / 0 | 3 |
| azure | appservices | 48 | 25 | 21 | 2 | 0 | 4 / 4 | 5 |
| azure | cognitiveservices | 16 | 9 | 6 | 1 | 0 | 0 / 0 | 4 |
| azure | containerapps | 14 | 7 | 4 | 3 | 0 | 5 / 5 | 4 |
| azure | cosmos | 35 | 15 | 16 | 4 | 0 | 0 / 0 | 6 |
| azure | cost | 3 | 0 | 2 | 1 | 0 | 3 / 3 | 4 |
| azure | defender | 1 | 0 | 1 | 0 | 0 | 2 / 2 | 3 |
| azure | dns | 5 | 4 | 0 | 1 | 0 | 2 / 2 | 2 |
| azure | entra | 6 | 5 | 0 | 1 | 0 | 0 / 0 | 4 |
| azure | eventgrid | 5 | 4 | 1 | 0 | 0 | 3 / 3 | 8 |
| azure | functionapp | 21 | 10 | 10 | 1 | 0 | 7 / 7 | 20 |
| azure | keyvaults | 31 | 16 | 12 | 3 | 0 | 0 / 0 | 6 |
| azure | loganalytics | 7 | 5 | 1 | 1 | 0 | 3 / 3 | 5 |
| azure | monitor | 15 | 0 | 13 | 1 | 1 | 6 / 6 | 17 |
| azure | nsgs | 8 | 4 | 4 | 0 | 0 | 1 / 1 | 4 |
| azure | resourcegroups | 22 | 13 | 9 | 0 | 0 | 0 / 0 | 2 |
| azure | servicebus | 14 | 9 | 4 | 1 | 0 | 5 / 5 | 8 |
| azure | sql | 48 | 20 | 24 | 4 | 0 | 0 / 0 | 8 |
| azure | storage | 57 | 28 | 25 | 4 | 0 | 12 / 12 | 22 |
| azure | subscriptions | 12 | 5 | 7 | 0 | 0 | 3 / 3 | 15 |
| azure | vms | 20 | 10 | 10 | 0 | 0 | 0 / 0 | 18 |
| azure | vnets | 21 | 7 | 11 | 3 | 0 | 1 / 1 | 7 |

Limited / Config-only badges actually rendered (distinct capability ids seen in the UI, offline run): AWS 124, GCP 92, AZURE 174. Per-service lists are in the scan JSON (`limited`).

## 2. S3, EC2 and IAM in full (the user's complaint)

### AWS S3 (11 sections)

| Section | Where | Class | Size | Family / deps | Batch |
|---|---|---|---|---|---|
| AWS CloudTrail data events | `#/s3/buckets/gs68b3d [tab:Properties]` | A | S | -; needs cloudtrail-core | AWS-07 |
| Metadata configuration | `#/s3/buckets/gs68b3d [tab:Metadata]` | A | M | -; needs s3-tables | AWS-01 |
| Storage Lens metrics | `#/s3/buckets/gs68b3d [tab:Metrics]` | A | M | -; needs cloudwatch-metrics | AWS-01 |
| The page /s3/vector-buckets | `#/s3/vector-buckets` | A | M | - | AWS-01 |
| AWS Marketplace for S3 | `#/s3/marketplace` | B | M | marketplace-saas | AWS-02 |
| The page /s3/access-points-fsx | `#/s3/access-points-fsx` | B | M | data-analytics; needs s3-files | AWS-02 |
| The page /s3/file-systems | `#/s3/file-systems` | B | L | data-analytics | AWS-02 |
| Transfer acceleration | `#/s3/buckets/gs68b3d [tab:Properties]` | B | S | networking-dataplane | AWS-02 |
| Amazon S3 | `#/s3/get-started` | C | S | - | AWS-02 |
| Object Lock legal hold | `#/s3/object/gsn4e25` | N | S | - | AWS-14 |
| Object Lock retention | `#/s3/object/gsn4e25` | N | S | - | AWS-14 |

### AWS EC2 (20 sections)

| Section | Where | Class | Size | Family / deps | Batch |
|---|---|---|---|---|---|
| All instances | `#/ec2/instances` | A | S | - | AWS-03 |
| Compare security group rules | `#/ec2/compare-security-group-rules` | A | S | - | AWS-04 |
| Create IAM profile | `#/ec2/launch-instance` | A | S | -; needs iam | AWS-03 |
| Events | `#/ec2/events` | A | S | - | AWS-03 |
| Fault tolerance for all volumes in this Region | `#/ec2/volumes` | A | S | - | AWS-03 |
| Instance alarms | `#/ec2` | A | S | -; needs cloudwatch-alarms | AWS-03 |
| Instance type finder | `#/ec2/instance-type-finder` | A | S | - | AWS-04 |
| Managed resources | `#/ec2/settings [tab:Auto Scaling groups]` | A | M | -; needs autoscaling-core | AWS-04 |
| Recycle Bin | `#/ec2/recycle-bin` | A | M | - | AWS-04 |
| Spot Requests | `#/ec2/ultraservers` | A | L | - | AWS-04 |
| Zones | `#/ec2` | A | S | - | AWS-03 |
| AWS Marketplace AMIs | `#/ec2/ami-catalog [tab:AWS Marketplace AMIs]` | B | M | marketplace-saas | AWS-06 |
| CPU and network metrics | `#/ec2/instances/i-07f4b187b0d740d3a [tab:Monitoring]` | B | L | observability; needs docker-stats-to-cloudwatch | AWS-05 |
| CloudWatch metrics | `#/ec2/volumes/vol-22b4f13e0f72 [tab:Monitoring]` | B | L | observability; needs docker-stats-to-cloudwatch | AWS-05 |
| Connect | `#/ec2/instances` | B | L | ssh-shell; needs tunnel-tcp-relay | AWS-05 |
| EC2 Image Builder | `#/ec2/image-builder` | B | L | cicd-source; needs buildkit | AWS-06 |
| EC2 cost | `#/ec2` | B | M | billing | AWS-06 |
| Migrate a server | `#/ec2/migrate-a-server` | B | L | data-analytics | AWS-06 |
| Shared with | `#/ec2/security-groups/sg-018db77eace3 [tab:Sharing]` | B | M | directory-orgs; needs directory-service | AWS-06 |
| Service health | `#/ec2` | C | S | - | AWS-06 |

### AWS IAM (3 sections)

| Section | Where | Class | Size | Family / deps | Batch |
|---|---|---|---|---|---|
| Service access report | `#/iam/service-control-policies/gs09sf0` | A | M | -; needs cloudtrail-core, organizations | AWS-07 |
| CloudFront key pairs | `#/iam/security-credentials` | B | M | networking-dataplane | AWS-07 |
| Role manager | `#/iam/account-settings` | C | S | - | AWS-07 |

Notes: (1) EC2 instance detail tabs could not be reached on the macOS offline run (`RunInstances` fails: "AMI ... is not supported on darwin"); they were scanned on **Nano**, where instances launch, so the two EC2 metrics tabs below appear only from the Nano run (they exist on offline too). (2) The S3 Object Lock legal-hold/retention panels render only for a bucket WITHOUT Object Lock; on a lock-enabled bucket they are real, so they are class N. (3) IAM shows only 3 sections: IAM is largely implemented after the IAM/Organizations sweeps.

## 3. Work batches (in execution order)

Order: AWS (S3, EC2, IAM first, then the rest), then GCP, then Azure; class A before B before C. One batch = about one worker sitting (a few related work packages; each package lists every section it closes).

### AWS-01 S3 buildable gaps: Metadata tables, Storage Lens metrics, S3 Vectors

Classes: A | work packages: 3 | sections closed: 3 | S3 first (user complaint)

- [ ] **S3 Metadata configuration (journal + live inventory tables)**: class A, needs: s3-tables; size M (1 section)
  - s3: Metadata configuration (`#/s3/buckets/gs68b3d`) [s3.bucket.metadata-configuration]
- [ ] **Storage Lens metrics (bucket Metrics tab)**: class A, needs: cloudwatch-metrics; size M (1 section)
  - s3: Storage Lens metrics (`#/s3/buckets/gs68b3d`) [s3.bucket.storage-lens]
- [ ] **S3 Vector buckets (vector index + query, in-process)**: class A, size M (1 section)
  - s3: The page /s3/vector-buckets (`#/s3/vector-buckets`)

### AWS-02 S3 decided-backend + editorial: file systems, FSx access points, Transfer acceleration, Marketplace, Get started

Classes: B/C | work packages: 5 | sections closed: 5

- [ ] **S3 file systems / Files (NFS-style) **: class B, family: data-analytics; size L (1 section)
  - s3: The page /s3/file-systems (`#/s3/file-systems`)
- [ ] **Access points for FSx**: class B, family: data-analytics; needs: s3-files; size M (1 section)
  - s3: The page /s3/access-points-fsx (`#/s3/access-points-fsx`)
- [ ] **Transfer acceleration (endpoint alias via Caddy)**: class B, family: networking-dataplane; size S (1 section)
  - s3: Transfer acceleration (`#/s3/buckets/gs68b3d`) [s3.bucket.accelerate]
- [ ] **AWS Marketplace for S3 (Vyomi SaaS spaces)**: class B, family: marketplace-saas; size M (1 section)
  - s3: AWS Marketplace for S3 (`#/s3/marketplace`) [s3.account.marketplace]
- [ ] **Editorial / marketing / doc-link content with no resource behind it**: class C, size S (1 section)
  - s3: Amazon S3 (`#/s3/get-started`) [s3.account.get-started]

### AWS-03 EC2 dashboard + ops (zones, alarms, events, health rollup, EBS fault tolerance, IAM profile)

Classes: A | work packages: 6 | sections closed: 6

- [ ] **EC2 Zones / AZ listing**: class A, size S (1 section)
  - ec2: Zones (`#/ec2`)
- [ ] **EC2 instance alarms (CloudWatch alarm list for instances)**: class A, needs: cloudwatch-alarms; size S (1 section)
  - ec2: Instance alarms (`#/ec2`)
- [ ] **EC2 scheduled events page**: class A, size S (1 section)
  - ec2: Events (`#/ec2/events`)
- [ ] **EC2 account-wide instance status rollup**: class A, size S (1 section)
  - ec2: All instances (`#/ec2/instances`)
- [ ] **EBS fault-tolerance (snapshot coverage) widget**: class A, size S (1 section)
  - ec2: Fault tolerance for all volumes in this Region (`#/ec2/volumes`)
- [ ] **Create IAM instance profile page**: class A, needs: iam; size S (1 section)
  - ec2: Create IAM profile (`#/ec2/launch-instance`)

### AWS-04 EC2 tools + purchasing (compare SG, type finder, Recycle Bin, Auto Scaling settings, Spot/capacity)

Classes: A | work packages: 5 | sections closed: 5

- [ ] **Compare security group rules**: class A, size S (1 section)
  - ec2: Compare security group rules (`#/ec2/compare-security-group-rules`)
- [ ] **Instance type finder**: class A, size S (1 section)
  - ec2: Instance type finder (`#/ec2/instance-type-finder`)
- [ ] **Recycle Bin (AMI/snapshot retention rules)**: class A, size M (1 section)
  - ec2: Recycle Bin (`#/ec2/recycle-bin`)
- [ ] **Managed resources / Auto Scaling settings tab**: class A, needs: autoscaling-core; size M (1 section)
  - ec2: Managed resources (`#/ec2/settings`) [ec2.settings.other]
- [ ] **Spot / purchasing options / capacity manager / reservations (simulated, no billing)**: class A, size L (1 section)
  - ec2: Spot Requests (`#/ec2/dedicated-hosts`) [ec2.purchasing-options]

### AWS-05 EC2 reach-in + telemetry: Connect (SSH) and instance/volume metrics

Classes: B | work packages: 2 | sections closed: 3 | decided families #1 and #3

- [ ] **EC2 Connect (SSH/Session Manager/EC2 Instance Connect)**: class B, family: ssh-shell; needs: tunnel-tcp-relay; size L (1 section)
  - ec2: Connect (`#/ec2/instances`) [ec2.instances.connect]
- [ ] **Instance CPU/network + EBS volume CloudWatch metrics**: class B, family: observability; needs: docker-stats-to-cloudwatch; size L (2 sections)
  - ec2: CPU and network metrics (`#/ec2/instances/i-07f4b187b0d740d3a`)
  - ec2: CloudWatch metrics (`#/ec2/volumes/vol-22b4f13e0f72`)

### AWS-06 EC2 marketplace/builder/migration/RAM/cost

Classes: B/C | work packages: 6 | sections closed: 6

- [ ] **Marketplace + community AMIs**: class B, family: marketplace-saas; size M (1 section)
  - ec2: AWS Marketplace AMIs (`#/ec2/ami-catalog`) [ec2.ami-catalog.marketplace-community]
- [ ] **EC2 Image Builder pipelines**: class B, family: cicd-source; needs: buildkit; size L (1 section)
  - ec2: EC2 Image Builder (`#/ec2/image-builder`)
- [ ] **Migrate a server (Application Migration Service)**: class B, family: data-analytics; size L (1 section)
  - ec2: Migrate a server (`#/ec2/migrate-a-server`)
- [ ] **RAM sharing of security groups**: class B, family: directory-orgs; needs: directory-service; size M (1 section)
  - ec2: Shared with (`#/ec2/security-groups/sg-018db77eace3`) [ec2.security-groups.ram-sharing]
- [ ] **Cost / spend widgets (cost-saved dashboard, simulated)**: class B, family: billing; size M (1 section)
  - ec2: EC2 cost (`#/ec2`)
- [ ] **Region-wide service health (AWS-side events)**: class C, size S (1 section)
  - ec2: Service health (`#/ec2`)

### AWS-07 CloudTrail core + IAM gaps (service access report, CloudFront key pairs, Role manager) + S3 data events

Classes: A/B/C | work packages: 4 | sections closed: 4 | IAM third; CloudTrail core unblocks S3 and IAM

- [ ] **CloudTrail data events for S3**: class A, needs: cloudtrail-core; size S (1 section)
  - s3: AWS CloudTrail data events (`#/s3/buckets/gs68b3d`) [s3.bucket.cloudtrail-data-events]
- [ ] **IAM service access report (derived from CloudTrail + Organizations)**: class A, needs: cloudtrail-core, organizations; size M (1 section)
  - iam: Service access report (`#/iam/service-control-policies/gs09sf0`) [iam.organizations.service-access-report]
- [ ] **Root CloudFront key pairs (needs CDN/CloudFront)**: class B, family: networking-dataplane; size M (1 section)
  - iam: CloudFront key pairs (`#/iam/security-credentials`) [iam.root.cloudfront-key-pairs]
- [ ] **IAM Role manager (no public API in AWS)**: class C, size S (1 section)
  - iam: Role manager (`#/iam/account-settings`) [iam.organizations.role-manager]

### AWS-08 EventBridge + CloudFormation + Secrets A items

Classes: A | work packages: 9 | sections closed: 14

- [ ] **EventBridge bus/archive KMS encryption**: class A, needs: kms; size S (3 sections)
  - eventbridge: Archive encryption with a customer KMS key (`#/eventbridge/create-archive`)
  - eventbridge: Encryption (`#/eventbridge/event-buses/default`)
  - eventbridge: Event bus encryption with a customer KMS key (`#/eventbridge`)
- [ ] **EventBridge bus logs to CloudWatch Logs**: class A, needs: cloudwatch-logs; size S (2 sections)
  - eventbridge: Delivering bus logs to CloudWatch Logs / S3 / Firehose (`#/eventbridge`)
  - eventbridge: Logs (`#/eventbridge/event-buses/default`)
- [ ] **EventBridge resource-policy enforcement**: class A, needs: iam-policy-eval; size M (2 sections)
  - eventbridge: Resource-based policy (`#/eventbridge/event-buses/default`)
  - eventbridge: Resource-based policy enforcement (`#/eventbridge`)
- [ ] **Attach archive at bus creation**: class A, size S (1 section)
  - eventbridge: Attaching an archive at bus-creation time (`#/eventbridge`)
- [ ] **EventBridge schema registry + discovery**: class A, size M (2 sections)
  - eventbridge: Schema discovery (`#/eventbridge`)
  - eventbridge: Schemas (`#/eventbridge/schemas`)
- [ ] **CloudFormation stack policy enforcement**: class A, size S (1 section)
  - cloudformation: Stack policy (`#/cloudformation/stacks/gs2v5zy`)
- [ ] **CloudFormation rollback triggers (CloudWatch alarms)**: class A, needs: cloudwatch-alarms; size M (1 section)
  - cloudformation: Rollback configuration (`#/cloudformation/stacks/gs2v5zy`)
- [ ] **CloudFormation SNS stack notifications**: class A, needs: sns; size S (1 section)
  - cloudformation: Notification options (`#/cloudformation/stacks/gs2v5zy`)
- [ ] **Secrets Manager rotation function invocation**: class A, needs: lambda; size M (1 section)
  - secretsmanager: Rotation function (`#/secretsmanager/newsecret`) [secretsmanager.rotation.lambda-function]

### AWS-09 RDS + DynamoDB + Lambda + SNS + VPC A items

Classes: A | work packages: 10 | sections closed: 13

- [ ] **RDS CloudWatch alarms tab**: class A, needs: cloudwatch-alarms; size S (1 section)
  - rds: CloudWatch alarms (`#/rds/databases/gs5lbsk`)
- [ ] **RDS IAM role association**: class A, needs: iam; size S (1 section)
  - rds: IAM role association (`#/rds/create-database`)
- [ ] **RDS restore from S3 backup**: class A, needs: s3; size M (1 section)
  - rds: Restore from S3 (`#/rds/restore-from-s3`)
- [ ] **RDS dashboard + service-quota pages**: class A, size M (2 sections)
  - rds: The page /rds/dashboard (`#/rds/dashboard`)
  - rds: The page /rds/service-quota (`#/rds/service-quota`)
- [ ] **DynamoDB backup copy across Region/account + AWS Backup integration toggle**: class A, size M (2 sections)
  - dynamodb: Copy a backup to another account or Region (`#/dynamodb/backups`)
  - dynamodb: Turn off AWS Backup integration for DynamoDB (`#/dynamodb/backups`)
- [ ] **DynamoDB provisioned-capacity auto scaling**: class A, needs: autoscaling-core; size M (1 section)
  - dynamodb: Auto scaling (`#/dynamodb/create-table`) [dynamodb.autoscaling]
- [ ] **Lambda RDS databases (RDS Proxy connection helper)**: class A, needs: rds; size M (1 section)
  - lambda: RDS databases (`#/lambda/functions/gs24hpo`) [lambda.function.rds-databases]
- [ ] **SNS Integrations tab (links to wizards)**: class A, size S (1 section)
  - sns: Integrations (`#/sns/topics/gs0o41f`) [sns.topic.integrations]
- [ ] **VPC account-level pages (encryption control, cross-Region summary)**: class A, size S (2 sections)
  - vpc: Account-level encryption control (`#/vpc`)
  - vpc: Cross-Region resource summary (`#/vpc`)
- [ ] **Create multiple subnets in one batch**: class A, size S (1 section)
  - vpc: Creating multiple subnets in one batch (`#/vpc/create-subnet`)

### AWS-10 Visual canvas component (CFN Template Studio, EventBridge builder, Lambda Composer)

Classes: A | work packages: 1 | sections closed: 3 | one shared UI component

- [ ] **Visual drag-and-drop canvas (CFN Template Studio, EventBridge builder, Lambda Infrastructure Composer)**: class A, size L (3 sections)
  - cloudformation: Canvas (`#/cloudformation/template-studio`)
  - eventbridge: Builder mode (`#/eventbridge/create-rule`)
  - lambda: Build with Infrastructure Composer (`#/lambda/create/application`) [lambda.application.infrastructure-composer]

### AWS-11 AWS observability + security + billing family: RDS metrics, Security Hub, Cost Explorer

Classes: B | work packages: 3 | sections closed: 4 | families #3 #4 #9

- [ ] **RDS instance metrics (CPU/memory/storage) + Database Insights**: class B, family: observability; needs: docker-stats-to-cloudwatch; size M (2 sections)
  - rds: CPUUtilization, FreeStorageSpace, FreeableMemory (`#/rds/databases/gs5lbsk`)
  - rds: Database Insights metrics (`#/rds/create-database`)
- [ ] **Security Hub findings**: class B, family: security-scanning; needs: trivy-kubescape; size M (1 section)
  - (home): #/ (`#/`)
- [ ] **Cost / spend widgets (cost-saved dashboard, simulated)**: class B, family: billing; size M (1 section)
  - cost-explorer: The service "cost-explorer" (`#/cost-explorer`)

### AWS-12 AWS networking + CI/CD family: VPC Lattice, Network Firewall containers, CloudFormation Git sync, Lambda CI/CD

Classes: B | work packages: 4 | sections closed: 4 | families #5 #2

- [ ] **VPC Lattice service networks**: class B, family: networking-dataplane; needs: netsim; size L (1 section)
  - vpc: Service networks (`#/vpc/lattice-services`) [aws.vpc.lattice]
- [ ] **Network Firewall container associations**: class B, family: networking-dataplane; needs: netsim; size M (1 section)
  - vpc: Container associations (`#/vpc/container-associations`) [aws.vpc.network-firewall-containers]
- [ ] **CloudFormation Git sync**: class B, family: cicd-source; needs: gitea; size M (1 section)
  - cloudformation: Git sync (`#/cloudformation/stacks/gs2v5zy`)
- [ ] **Lambda CI/CD pipeline application**: class B, family: cicd-source; needs: buildkit, gitea; size L (1 section)
  - lambda: CI/CD pipeline application (`#/lambda/create/application`) [lambda.application.cicd-pipeline]

### AWS-13 AWS data / directory / marketplace / local-LLM family: DMS, zero-ETL, SNS SMS, StackSets orgs, CFN registry, partner sources, AgentCore

Classes: B | work packages: 7 | sections closed: 14 | families #6 #7 #8 #11

- [ ] **RDS data migrations (DMS)**: class B, family: data-analytics; size L (1 section)
  - rds: Data migrations (`#/rds/databases/gs5lbsk`)
- [ ] **Zero-ETL integrations (DynamoDB/RDS to Redshift/lakehouse)**: class B, family: data-analytics; size L (2 sections)
  - dynamodb: Integrations (`#/dynamodb/integrations`) [dynamodb.account.zero-etl]
  - rds: Create zero-ETL integration (`#/rds/create-zero-etl-integration`)
- [ ] **SNS SMS/mobile push OTP + sandbox delivery**: class B, family: data-analytics; size M (1 section)
  - sns: Verification code delivery (`#/sns/mobile/text-messaging`) [sns.sms.otp-delivery]
- [ ] **StackSets service-managed permissions (Organizations)**: class B, family: directory-orgs; needs: directory-service; size M (1 section)
  - cloudformation: Trusted access with AWS Organizations (`#/cloudformation/stacksets`)
- [ ] **CloudFormation public extensions / publisher registry**: class B, family: marketplace-saas; size L (6 sections)
  - cloudformation: Configuration (`#/cloudformation/registry/public-extensions/resource-type/AWS%3A%3AIAM%3A%3ARole`)
  - cloudformation: Filter (`#/cloudformation/registry/public-extensions`)
  - cloudformation: Filters (`#/cloudformation/spotlight`)
  - cloudformation: Modules (`#/cloudformation/registry/activated-extensions`)
  - cloudformation: Publisher registration (`#/cloudformation/registry/publisher`)
  - cloudformation: Registry: Public extensions (`#/cloudformation/registry/public-extensions`)
- [ ] **Partner event sources / SaaS partners**: class B, family: marketplace-saas; size M (1 section)
  - eventbridge: Partner event sources (`#/eventbridge/partner-event-sources`)
- [ ] **Lambda/AgentCore agent onboarding + AgentCore targets**: class B, family: local-llm; needs: local-llm; size L (2 sections)
  - apigateway: AgentCore targets (`#/apigateway/agentcore-targets`) [apigateway.agentcore-targets]
  - lambda: Set up your agent to build with Lambda (`#/lambda`) [lambda.dashboard.agent-onboarding]

### AWS-14 AWS unbuildable / editorial / verify

Classes: C/N | work packages: 8 | sections closed: 19 | class C and N

- [ ] **Reserved capacity purchase (billing/payment)**: class C, size S (1 section)
  - dynamodb: Reserved capacity (`#/dynamodb/reserved-capacity`) [dynamodb.account.reserved-capacity]
- [ ] **RDS capacity reservations (capacity-market / billing construct)**: class C, size S (1 section)
  - rds: Create capacity reservation (`#/rds/capacity-reservations`)
- [ ] **SNS settings that do not exist in the real API (max message size, TTL)**: class C, size S (2 sections)
  - sns: Maximum message size (`#/sns/create-topic`) [sns.topic.max-message-size]
  - sns: Time to Live (TTL) - optional (`#/sns/topics/gs0o41f/publish`) [sns.publish.ttl]
- [ ] **Network Manager / external console link-outs**: class C, size S (2 sections)
  - vpc: AWS Network Manager (`#/vpc`)
  - vpc: Integrations (`#/vpc/vpcs/vpc-068241adcd19`) [aws.vpc.integrations]
- [ ] **Region-wide service health (AWS-side events)**: class C, size S (5 sections)
  - rds: The page /rds/service-health (`#/rds/service-health`)
  - vpc: Linked AWS documentation (`#/vpc`)
  - vpc: Linked AWS forums (`#/vpc`)
  - vpc: Linked issue reporting (`#/vpc`)
  - vpc: Service health dashboard (`#/vpc`)
- [ ] **Editorial / marketing / doc-link content with no resource behind it**: class C, size S (2 sections)
  - eventbridge: Learn (`#/eventbridge/learn`)
  - eventbridge: Quick starts (`#/eventbridge/quick-starts`)
- [ ] **Object Lock panels (render only when the bucket has no lock; verified real on a locked bucket)**: class N, size S (2 sections)
  - s3: Object Lock legal hold (`#/s3/object/gsn4e25`)
  - s3: Object Lock retention (`#/s3/object/gsn4e25`)
- [ ] **Transient 'Not simulated' text without the data attribute (state-dependent / mid-render); re-check**: class N, size S (4 sections)
  - cloudwatch: #/cloudwatch/alarms/create (`#/cloudwatch/alarms/create`)
  - eventbridge: #/eventbridge (`#/eventbridge`)
  - eventbridge: #/eventbridge/create-event-bus (`#/eventbridge/create-event-bus`)
  - eventbridge: #/eventbridge/home (`#/eventbridge/home`)

### GCP-01 Compute A: recommender, schedules, backups/snapshots, NIC/NEG, sole-tenant/reservations

Classes: A | work packages: 4 | sections closed: 18

- [ ] **Recommender engine (Compute Advisor / dashboard recommendations / Recommender & VM Manager)**: class A, size M (3 sections)
  - compute: Compute Advisor (`#/compute/compute-advisor`)
  - compute: Recommender & VM Manager (`#/compute/instances`)
  - dashboard: No recommendations (`#/dashboard`)
- [ ] **VM backups + extra disks + snapshot schedules / instant snapshots / async replication / consistency groups**: class A, size M (8 sections)
  - compute: Additional storage and VM backups (`#/compute/instances/create`)
  - compute: Async Replication (`#/compute/async-replication`)
  - compute: Back up your data (`#/compute/instances/create`)
  - compute: Consistency Groups (`#/compute/consistency-groups`)
  - compute: Enable snapshot schedule (`#/compute/disks/create`)
  - compute: Instance schedules (`#/compute/instances`)
  - compute: Instant snapshots (`#/compute/snapshots`)
  - compute: Snapshot schedules (`#/compute/snapshots`)
- [ ] **Multiple NICs + health-check firewall + NEGs**: class A, needs: netsim; size M (3 sections)
  - compute: Add a network interface (`#/compute/instances/create`)
  - compute: Allow Load Balancer Health Checks (`#/compute/instances/create`)
  - compute: Network endpoint groups (`#/compute/network-endpoint-groups`)
- [ ] **Sole-tenant nodes / reservations / storage pools / rollouts**: class A, size M (4 sections)
  - compute: Reservations (`#/compute/reservations`)
  - compute: Rollouts (`#/compute/rollouts`)
  - compute: Sole-tenant nodes (`#/compute/sole-tenant-nodes`)
  - compute: Storage Pools (`#/compute/storage-pools`)

### GCP-02 Run/Functions A: autoscaling, probes, volumes, SQL connections, BinAuthz/CMEK, Eventarc, image picker

Classes: A | work packages: 5 | sections closed: 17

- [ ] **Cloud Run/Functions autoscaling factors, health checks, volumes, ephemeral disk, revision tags, connections**: class A, size M (10 sections)
  - functions: Customize autoscaling factors (`#/functions/create`)
  - functions: Ephemeral disk (`#/functions/create`)
  - functions: Health checks (`#/functions/create`)
  - functions: Revision tags (`#/functions/detail/us-central1/gs2h15y`)
  - functions: Volumes (`#/functions/create`)
  - run: Customize autoscaling factors (`#/run/create`)
  - run: Ephemeral disk (`#/run/create`)
  - run: Health checks (`#/run/create`)
  - run: Revision tags (`#/run/detail/us-central1/gs2h15y`)
  - run: Volumes (`#/run/create`)
- [ ] **Cloud SQL connections for Run/Functions**: class A, needs: sql; size M (2 sections)
  - functions: Cloud SQL connections (`#/functions/create`)
  - run: Cloud SQL connections (`#/run/create`)
- [ ] **Binary Authorization + CMEK for Run/Functions**: class A, needs: kms; size M (2 sections)
  - functions: Verify container deployment with Binary Authorization, Encryption (Google-managed encrypti (`#/functions/create`)
  - run: Verify container deployment with Binary Authorization, Encryption (Google-managed encrypti (`#/run/create`)
- [ ] **Eventarc triggers (non-Pub/Sub sources)**: class A, size L (2 sections)
  - run: Event triggers (Eventarc) (`#/run/jobs/details/us-central1/gsp21nz`)
  - run: Trigger (optional) (`#/run/create`)
- [ ] **Artifact Registry image picker**: class A, needs: artifacts; size S (1 section)
  - run: Select (`#/run/jobs/create`)

### GCP-03 Identity/data A: org-policy simulation, workload identity federation, Firestore rules, Logs correlate, Datastore, GCS config, SQL flags, KMS import

Classes: A | work packages: 8 | sections closed: 13

- [ ] **Org policy constraint simulation**: class A, size M (1 section)
  - iam-admin: Simulating a constraint change against existing resources (`#/iam-admin/orgpolicies`)
- [ ] **Workload/Workforce identity federation (OIDC/SAML) + attribute mapping**: class A, needs: sts-core; size M (3 sections)
  - iam-admin: Attribute mapping and condition configuration for an external provider (`#/iam-admin/workload-identity-pools`)
  - iam-admin: Connecting an external OIDC/SAML identity provider (`#/iam-admin/workload-identity-pools`)
  - iam-admin: Connecting an external OIDC/SAML workforce identity provider (`#/iam-admin/workforce-identity-pools`)
- [ ] **Firestore security-rules evaluator**: class A, size L (1 section)
  - firestore: Security rules enforcement (`#/firestore/create-database`)
- [ ] **Logs correlate-by trace**: class A, size M (1 section)
  - logs: Correlate by (`#/logs`)
- [ ] **Datastore mode (Firestore in Datastore mode)**: class A, size L (1 section)
  - datastore: The product "datastore" (`#/datastore`)
- [ ] **GCS turbo replication / Autoclass / CMEK / per-object keys / holds**: class A, size M (4 sections)
  - storage: Add turbo replication (`#/storage/create-bucket`)
  - storage: Autoclass (`#/storage/create-bucket`)
  - storage: Data encryption with Cloud KMS keys (CMEK) (`#/storage/create-bucket`)
  - storage: Per-object customer-managed encryption keys (`#/storage/browser/gs4c74y`)
- [ ] **Cloud SQL custom machine shapes, SSL enforcement, CMEK**: class A, needs: kms; size M (1 section)
  - sql: Custom machine shapes, SSL/TLS enforcement and Cloud KMS customer-managed encryption (`#/sql/create/instance`)
- [ ] **Imported key material**: class A, needs: kms; size M (1 section)
  - security: Imported key material (`#/security/kms/key/create`)

### GCP-04 GCP SSH + observability + security family: GCE SSH, VM Manager, Ops Agent, trace/scopes, security risk, storage security insights

Classes: B | work packages: 6 | sections closed: 13 | families #1 #3 #4

- [ ] **GCE SSH / OS info / serial (real sshd in container)**: class B, family: ssh-shell; needs: tunnel-tcp-relay; size L (2 sections)
  - compute: OS info (`#/compute/instances/us-central1-a/gsb7oke`)
  - compute: SSH (`#/compute/instances`)
- [ ] **VM Manager: Patch, OS policies, VM extension policies (guest agent)**: class B, family: ssh-shell; needs: gce-ssh; size L (3 sections)
  - compute: OS policies (`#/compute/os-policies`)
  - compute: Patch (`#/compute/patch`)
  - compute: VM extension policies (`#/compute/vm-extension-policies`)
- [ ] **Ops Agent install + monitoring on instances**: class B, family: observability; needs: observability-stack; size M (1 section)
  - compute: Install Ops Agent for Monitoring and Logging (`#/compute/instances/create`)
- [ ] **Trace explorer / trace + log scopes / Memorystore + app monitoring**: class B, family: observability; needs: observability-stack; size L (5 sections)
  - memorystore: Monitoring (`#/memorystore/instances/us-central1/gs3cb09/overview`) [gcp.memorystore.monitoring]
  - monitoring: Application labels (`#/monitoring/application-monitoring`) [gcp.monitoring.application-monitoring]
  - monitoring: Distributed tracing (`#/monitoring/trace-explorer`) [gcp.monitoring.trace-explorer]
  - monitoring: Log scopes (`#/monitoring/settings`) [gcp.monitoring.settings.log-scopes]
  - monitoring: Trace scopes (`#/monitoring/settings`) [gcp.monitoring.settings.trace-scopes]
- [ ] **Compute security risk overview**: class B, family: security-scanning; needs: trivy-kubescape; size M (1 section)
  - compute: Security risk overview (`#/compute/security-risk-overview`)
- [ ] **Storage security insights / recommendations**: class B, family: security-scanning; needs: trivy-kubescape; size M (1 section)
  - storage: Recommendations (`#/storage/advisor`) [gcp.storage.security-insights]

### GCP-05 GCP networking + CI/CD family: VLAN/BYOIP/flow logs, Run networking, source deploy

Classes: B | work packages: 3 | sections closed: 13 | families #5 #2

- [ ] **VLAN attachments / BYOIP / flow logs**: class B, family: networking-dataplane; needs: netsim, frr-wireguard; size L (3 sections)
  - networking: Bring your own IP (`#/networking/bring-your-own-ip`) [gcp.networking.byoip]
  - networking: Flow log records (`#/networking/vpc-flow-logs`)
  - networking: VLAN attachments (`#/networking/vpc-flow-logs`) [gcp.networking.hybrid-connectivity]
- [ ] **Custom URLs, HTTP/2, session affinity, VPC egress, service mesh**: class B, family: networking-dataplane; needs: netsim; size M (4 sections)
  - functions: Custom URLs (`#/functions/create`)
  - functions: Use HTTP/2 end-to-end, Session affinity, Connect to a VPC for outbound traffic, Join a Ser (`#/functions/create`)
  - run: Custom URLs (`#/run/create`)
  - run: Use HTTP/2 end-to-end, Session affinity, Connect to a VPC for outbound traffic, Join a Ser (`#/run/create`)
- [ ] **Source deploy / connect repo / continuous deployment**: class B, family: cicd-source; needs: buildkit, gitea; size L (6 sections)
  - functions: Source (`#/functions/detail/us-central1/gs2h15y`)
  - run: Connect repo (`#/run`)
  - run: Connect repository (`#/run/overview`)
  - run: Continuous deployment (`#/run/detail/us-central1/gs2h15y`)
  - run: Non-Pub/Sub event sources (`#/run/detail/us-central1/gs2h15y`)
  - run: Source (`#/run/detail/us-central1/gs2h15y`)

### GCP-06 GCP data / directory / marketplace family: VM import, Storage Insights, Asset Inventory queries, org/folders, Marketplace

Classes: B | work packages: 5 | sections closed: 11 | families #6 #7 #8

- [ ] **Import VM / Migrate to VMs / image import-export history**: class B, family: data-analytics; size L (4 sections)
  - compute: Image export history (`#/compute/images`)
  - compute: Image import history (`#/compute/images`)
  - compute: Import VM (`#/compute/instances`)
  - compute: Migrate to Virtual Machines (`#/compute/migrate-to-vms`)
- [ ] **GCS Rapid Cache / inventory reports / object enrichments (Storage Insights)**: class B, family: data-analytics; size L (3 sections)
  - storage: Inventory reports (`#/storage/browser/gs4c74y`) [gcp.storage.inventory-reports]
  - storage: Object enrichments (`#/storage/object-enrichments`) [gcp.storage.object-enrichments]
  - storage: Rapid Cache (`#/storage/monitoring`) [gcp.storage.rapid-cache]
- [ ] **Cloud Asset Inventory custom queries (graph engine)**: class B, family: data-analytics; needs: resource-graph-engine; size M (1 section)
  - iam-admin: Custom Cloud Asset Inventory queries (full query language) (`#/iam-admin/analyzer`)
- [ ] **Organization / folder browse + privacy & security**: class B, family: directory-orgs; needs: directory-service; size M (2 sections)
  - iam-admin: Privacy & Security (`#/iam-admin/privacy`) [gcp.iam-admin.privacy-security]
  - resource-manager: Browsing for a parent organization or folder (`#/resource-manager/create`)
- [ ] **GCP Marketplace (Vyomi SaaS spaces)**: class B, family: marketplace-saas; size M (1 section)
  - products: Marketplace (`#/products`)

### GCP-07 GCP unbuildable

Classes: C | work packages: 7 | sections closed: 17 | class C

- [ ] **Google Cloud incidents / service health**: class C, size S (1 section)
  - compute: Google Cloud incidents (`#/compute`)
- [ ] **Hardware: TPUs, Bare Metal Solution, sole-tenant hardware**: class C, size S (8 sections)
  - compute: Maintenance Events (`#/compute/bms/maintenance-events`)
  - compute: NFS Shares (`#/compute/bms/nfs-shares`)
  - compute: Networks (`#/compute/bms/networks`)
  - compute: Procurements (`#/compute/bms/procurements`)
  - compute: Servers (`#/compute/bms/servers`)
  - compute: TPUs (`#/compute/tpus`)
  - compute: VRFs (`#/compute/bms/vrfs`)
  - compute: Volumes (`#/compute/bms/volumes`)
- [ ] **Committed use discounts (purchase)**: class C, size S (2 sections)
  - compute: Capacity advisor (`#/compute/capacity-advisor`)
  - compute: Committed use discounts (`#/compute/committed-use-discounts`)
- [ ] **Preview features / screenshot / capacity advisor (Google-side)**: class C, size S (2 sections)
  - compute: Preview Features (`#/compute/preview-features`)
  - compute: Screenshot (`#/compute/instances/us-central1-a/gsb7oke`)
- [ ] **GPU for Cloud Run/Functions**: class C, size S (2 sections)
  - functions: GPU (`#/functions/create`)
  - run: GPU (`#/run/create`)
- [ ] **HSM / external key protection levels**: class C, size S (1 section)
  - security: HSM, External and External via VPC protection levels (`#/security/kms/key/create`)
- [ ] **Cloud Hub (Google-side aggregate)**: class C, size S (1 section)
  - cloud-hub: The product "cloud-hub" (`#/cloud-hub`)

### AZ-01 Azure common blades A: export template, activity log, RBAC extras, grid tools, resource health/Advisor, diagnostic settings, visualizer

Classes: A | work packages: 7 | sections closed: 120 | cross-cutting kit components applied to every service

- [ ] **Export template (ARM -> Bicep/Terraform) on every resource**: class A, size M (29 sections)
  - aks: Bicep template export (`#/aks/uic-rg/uicaks/exporttemplate`)
  - aks: Terraform template export (`#/aks/uic-rg/uicaks/exporttemplate`)
  - appconfiguration: Bicep template export (`#/appconfiguration/uic-rg/gsox6i6/exporttemplate`)
  - appconfiguration: Terraform template export (`#/appconfiguration/uic-rg/gsox6i6/exporttemplate`)
  - appservices: ARM-to-Bicep decompilation (`#/appservices/uic-rg/uicapp/exporttemplate`)
  - appservices: ARM-to-Terraform export (`#/appservices/uic-rg/uicapp/exporttemplate`)
  - cognitiveservices: Bicep template export (`#/cognitiveservices/uic-rg/uiccogsvc/exporttemplate`)
  - cognitiveservices: Terraform template export (`#/cognitiveservices/uic-rg/uiccogsvc/exporttemplate`)
  - containerapps: ARM-to-Bicep decompilation (`#/containerapps/uic-rg/uicapp/exporttemplate`)
  - containerapps: ARM-to-Terraform export (`#/containerapps/uic-rg/uicapp/exporttemplate`)
  - cosmos: Bicep template export (`#/cosmos/uic-rg/uiccosmos/exporttemplate`)
  - cosmos: Terraform template export (`#/cosmos/uic-rg/uiccosmos/exporttemplate`)
  - dns: Export template (`#/dns/uic-rg/uic-dns-zone.com/exporttemplate`)
  - eventgrid: Bicep template export (`#/eventgrid/topics/cloudlearn-rg/uic-eg-topic/exporttemplate`)
  - ... and 15 more (full list in V4-GAP-QUEUE.json)
- [ ] **Activity log: edit columns / filters / export**: class A, size S (17 sections)
  - acr: Activity log: Edit columns (`#/acr/uic-rg/uicacr/activitylog`)
  - aks: Edit columns (`#/aks/uic-rg/uicaks/activitylog`)
  - apim: The Edit columns action (`#/apim/uic-rg/gsohiig/activitylog`)
  - appconfiguration: Edit columns (`#/appconfiguration/uic-rg/gsox6i6/activitylog`)
  - appservices: Activity log filters and export (`#/appservices/uic-rg/uicapp/activitylog`)
  - cognitiveservices: Edit columns (`#/cognitiveservices/uic-rg/uiccogsvc/activitylog`)
  - containerapps: Activity log filters and export (`#/containerapps/uic-rg/uicapp/activitylog`)
  - cosmos: Edit columns on the activity log (`#/cosmos/uic-rg/uiccosmos/activitylog`)
  - eventgrid: Edit columns (`#/eventgrid/topics/cloudlearn-rg/uic-eg-topic/activitylog`)
  - keyvaults: Edit columns (`#/keyvaults/uic-rg/uickv/activitylog`)
  - nsgs: Edit columns (`#/nsgs/uic-rg/uicnsg/activitylog`)
  - resourcegroups: Activity, Edit columns, Export Activity Logs, Insights, Feedback, Pin current filters and  (`#/resourcegroups/uic-rg/activitylog`)
  - sql: Edit columns on the activity log (`#/sql/uic-rg/uicsqlsrv/uicsqldb/activitylog`)
  - storage: Edit columns (`#/storage/uic-rg/gs83m2h/activitylog`)
  - ... and 3 more (full list in V4-GAP-QUEUE.json)
- [ ] **Access control extras: Deny assignments, Classic administrators, My access**: class A, needs: rbac; size S (31 sections)
  - acr: Classic administrators (`#/acr/uic-rg/uicacr/iam`)
  - acr: Deny assignments (`#/acr/uic-rg/uicacr/iam`)
  - aks: Classic administrators (`#/aks/uic-rg/uicaks/iam`)
  - aks: My access (`#/aks/uic-rg/uicaks/iam`)
  - apim: Deny assignments (`#/apim/uic-rg/gsohiig/iam`)
  - appconfiguration: Classic administrators (`#/appconfiguration/uic-rg/gsox6i6/iam`)
  - appconfiguration: My access (`#/appconfiguration/uic-rg/gsox6i6/iam`)
  - appservices: Classic administrators (`#/appservices/uic-rg/uicapp/iam`)
  - appservices: Deny assignments (`#/appservices/uic-rg/uicapp/iam`)
  - cognitiveservices: Classic administrators (`#/cognitiveservices/uic-rg/uiccogsvc/iam`)
  - cognitiveservices: My access (`#/cognitiveservices/uic-rg/uiccogsvc/iam`)
  - containerapps: Classic administrators (`#/containerapps/uic-rg/uicapp/iam`)
  - containerapps: Deny assignments (`#/containerapps/uic-rg/uicapp/iam`)
  - cosmos: Deny assignments (`#/cosmos/uic-rg/uiccosmos/iam`)
  - ... and 17 more (full list in V4-GAP-QUEUE.json)
- [ ] **Browse-grid tools: edit columns / bulk tag assignment / manage view / favourites**: class A, size S (19 sections)
  - (home): Favorite resources (`#/`)
  - aks: Manage view customization, Open query (Azure Resource Graph), Assign tags and bulk Start/S (`#/aks`)
  - apim: Bulk-assigning tags from the browse grid (`#/apim`)
  - appconfiguration: Manage deleted configuration stores, Open query (Azure Resource Graph) and Assign tags fro (`#/appconfiguration`)
  - cognitiveservices: Manage view, Open query (Azure Resource Graph) and Assign tags from the command bar (`#/cognitiveservices`)
  - cosmos: Bulk tag assignment from the browse grid (`#/cosmos`)
  - dns: Bulk tag assignment (`#/dns`)
  - keyvaults: Manage deleted vaults, Open query (Azure Resource Graph) and Assign tags from the command  (`#/keyvaults`)
  - loganalytics: Assign tags from the command bar (`#/loganalytics`)
  - nsgs: Open query (Azure Resource Graph) and Assign tags from the command bar (`#/nsgs`)
  - resourcegroups: Assign tags across a multi-selection and Open query (Azure Resource Graph) from the comman (`#/resourcegroups`)
  - resourcegroups: Saving a custom blade layout (`#/resourcegroups/uic-rg`)
  - servicebus: Open query (Azure Resource Graph) and Assign tags from the command bar (`#/servicebus`)
  - sql: Reservations, Open query (Azure Resource Graph) and Assign tags from the command bar (`#/sql`)
  - ... and 5 more (full list in V4-GAP-QUEUE.json)
- [ ] **Resource health + Advisor recommendations (derived from resource state)**: class A, size M (15 sections)
  - aks: Advisor recommendations (`#/aks/uic-rg/gs04rnr`)
  - appconfiguration: Resource health (`#/appconfiguration/uic-rg/gsox6i6/resourcehealth`)
  - appservices: Advisor recommendations (`#/appservices/uic-rg/uicapp`)
  - appservices: Resource health (`#/appservices/uic-rg/uicapp/resourcehealth`)
  - cognitiveservices: Resource health (`#/cognitiveservices/uic-rg/uiccogsvc/resourcehealth`)
  - cosmos: Resource health (`#/cosmos/uic-rg/uiccosmos/resourcehealth`)
  - functionapp: Advisor recommendations (`#/functionapp/uic-rg/uicfn`)
  - keyvaults: Advisor recommendations (`#/keyvaults/uic-rg/gs5upkp`)
  - keyvaults: Resource health (`#/keyvaults/uic-rg/uickv/resourcehealth`)
  - resourcegroups: Advisor recommendations (`#/resourcegroups/uic-rg`)
  - resourcegroups: Resource health (`#/resourcegroups/uic-rg/resourcehealth`)
  - servicebus: Resource health (`#/servicebus/uic-rg/uicsbns/resourcehealth`)
  - sql: Resource health (`#/sql/uic-rg/uicsqlsrv/uicsqldb/resourcehealth`)
  - storage: Advisor recommendations (`#/storage/uic-rg/gskbx8l`)
  - ... and 1 more (full list in V4-GAP-QUEUE.json)
- [ ] **Diagnostic settings (config store + routing to Log Analytics/Storage/Event Hub)**: class A, needs: loganalytics; size M (7 sections)
  - aks: Diagnostic settings (`#/aks/uic-rg/uicaks/diagnosticsettings`)
  - appconfiguration: Diagnostic settings (`#/appconfiguration/uic-rg/gsox6i6/diagnosticsettings`)
  - cognitiveservices: Diagnostic settings (`#/cognitiveservices/uic-rg/uiccogsvc/diagnosticsettings`)
  - cosmos: Diagnostic settings (`#/cosmos/uic-rg/uiccosmos/diagnosticsettings`)
  - keyvaults: Diagnostic settings (`#/keyvaults/uic-rg/uickv/diagnosticsettings`)
  - resourcegroups: Diagnostic settings (`#/resourcegroups/uic-rg/diagnosticsettings`)
  - sql: Diagnostic settings (`#/sql/uic-rg/uicsqlsrv/uicsqldb/diagnosticsettings`)
- [ ] **Resource visualizer (graph from ARM state)**: class A, size M (2 sections)
  - appservices: Resource visualizer (`#/appservices/uic-rg/uicapp/visualizer`)
  - resourcegroups: The Resource visualizer graph (`#/resourcegroups/uic-rg/resourcevisualizer`)

### AZ-02 Azure identity/crypto/policy A: managed identity, CMK, Event Grid subscriptions, Azure Policy, RG ops

Classes: A | work packages: 5 | sections closed: 33

- [ ] **User-assigned + managed identity assignment on resources**: class A, needs: managed-identity-core; size M (14 sections)
  - acr: User assigned managed identities (`#/acr/uic-rg/uicacr/identity`)
  - appconfiguration: Managed identity (`#/appconfiguration/uic-rg/gsox6i6/identity`)
  - appservices: User assigned managed identities (`#/appservices/uic-rg/uicapp/identity`)
  - cognitiveservices: User assigned managed identity (`#/cognitiveservices/uic-rg/uiccogsvc/identity`)
  - containerapps: Identity providers (`#/containerapps/uic-rg/uicapp/authentication`)
  - containerapps: User assigned managed identities (`#/containerapps/uic-rg/uicapp/identity`)
  - cosmos: Managed identity assignment (`#/cosmos/uic-rg/uiccosmos/identity`)
  - entra: Managed identity sign-ins (`#/entra/signinlogs`)
  - functionapp: User assigned managed identities (`#/functionapp/uic-rg/uicfn/identity`)
  - sql: Server identity (`#/sql/create`)
  - sql: User assigned managed identity (`#/sql/uic-rg/uicsqlsrv/uicsqldb/identity`)
  - storage: Azure Files identity-based access (`#/storage/uic-rg/gskbx8l`)
  - subscriptions: Microsoft Entra Privileged Identity Management (PIM) eligible-subscription assignments (`#/subscriptions`)
  - vms: User-assigned managed identities (`#/vms/uic-rg/uicvm/identity`)
- [ ] **Customer-managed keys / encryption (Key Vault backed)**: class A, needs: keyvaults; size M (9 sections)
  - appconfiguration: Customer-managed key encryption (`#/appconfiguration/uic-rg/gsox6i6/encryption`)
  - cosmos: Customer-managed key rotation (Data Encryption blade) (`#/cosmos/uic-rg/uiccosmos/dataencryption`)
  - keyvaults: VM/ARM-template/Disk-Encryption secret retrieval from this vault (`#/keyvaults/uic-rg/uickv/accessconfiguration`)
  - servicebus: Encryption (`#/servicebus/uic-rg/uicsbns/encryption`)
  - sql: Transparent data encryption key management (`#/sql/create`)
  - storage: Customer-managed keys (CMK) (`#/storage/create`)
  - storage: Encryption scope and Enable version-level immutability support for new containers (`#/storage/uic-rg/gsvtnpv/containers`)
  - storage: Infrastructure encryption (`#/storage/create`)
  - storage: Rotate key (`#/storage/uic-rg/uicstorage/accesskeys`)
- [ ] **Event Grid subscriptions on resource events (system topics)**: class A, needs: eventgrid; size M (5 sections)
  - apim: Events (`#/apim/uic-rg/gsohiig/events`)
  - appconfiguration: Event Grid subscriptions on configuration store events (`#/appconfiguration/uic-rg/gsox6i6/events`)
  - keyvaults: Event Grid subscriptions on key vault events (`#/keyvaults/uic-rg/uickv/events`)
  - resourcegroups: Event Grid subscriptions on resource group events (`#/resourcegroups/uic-rg/events`)
  - storage: Events (`#/storage/uic-rg/uicstorage/events`)
- [ ] **Azure Policy compliance + assignments**: class A, needs: policy-engine; size L (3 sections)
  - aks: Azure Policy assignments (`#/aks/uic-rg/uicaks/policies`)
  - resourcegroups: Azure Policy compliance (`#/resourcegroups/uic-rg/policies`)
  - subscriptions: Azure Policy compliance management for the subscription (`#/subscriptions`)
- [ ] **Resource group: force delete, deployment stacks, policy compliance, custom blade layout**: class A, size M (2 sections)
  - resourcegroups: Deployment stacks (`#/resourcegroups/uic-rg/deploymentstacks`)
  - resourcegroups: Force delete (`#/resourcegroups/uic-rg/delete`)

### AZ-03 Storage + SQL + Cosmos A

Classes: A | work packages: 6 | sections closed: 38

- [ ] **Blob protection: soft delete, versioning, change feed, point-in-time restore, immutability**: class A, size M (7 sections)
  - storage: Access control (`#/storage/create`)
  - storage: Blob change feed (`#/storage/uic-rg/gskbx8l`)
  - storage: Blob soft delete (`#/storage/uic-rg/gskbx8l`)
  - storage: Blob versioning (`#/storage/uic-rg/gskbx8l`)
  - storage: Container soft delete (`#/storage/uic-rg/gskbx8l`)
  - storage: Data protection (`#/storage/create`)
  - storage: Tracking (`#/storage/create`)
- [ ] **Storage account config: custom domain, CORS, encryption scopes, access control, geo-replication, large file shares**: class A, size M (5 sections)
  - storage: Advanced (`#/storage/uic-rg/uicstorage/containers`)
  - storage: Custom domain (`#/storage/uic-rg/uicstorage/networking`)
  - storage: Metadata rewrite (`#/storage/uic-rg/uicstorage/datalakegen2upgrade`)
  - storage: Publish route-specific endpoints for Microsoft network routing and Internet routing (`#/storage/uic-rg/uicstorage/networking`)
  - storage: Resource instances (`#/storage/uic-rg/uicstorage/networking`)
- [ ] **SQL security + perf: TDE keys, Always Encrypted, ledger, masking, classification, auditing, Query Performance Insight**: class A, size L (4 sections)
  - sql: Always Encrypted (`#/sql/create`)
  - sql: Data Discovery & Classification (`#/sql/uic-rg/uicsqlsrv/uicsqldb/datadiscovery`)
  - sql: Dynamic Data Masking rules (`#/sql/uic-rg/uicsqlsrv/uicsqldb/datamasking`)
  - sql: Ledger (`#/sql/create`)
- [ ] **SQL operations: copy/restore database, geo-replication, stored procedures, maintenance, connectivity policy**: class A, size M (4 sections)
  - sql: Connection policy (`#/sql/create`)
  - sql: Connectivity (`#/sql/servers/uic-rg/uicsqlsrv/networking`)
  - sql: Maintenance event history (`#/sql/uic-rg/uicsqlsrv/uicsqldb/maintenance`)
  - sql: Stored procedures (T-SQL procedural objects) (`#/sql/uic-rg/uicsqlsrv/uicsqldb/queryeditor`)
- [ ] **Cosmos operations: restore, hierarchical partition keys, CORS, dedicated gateway, CMK, scale/browse blades**: class A, size M (5 sections)
  - cosmos: CORS rules (`#/cosmos/uic-rg/uiccosmos/cors`)
  - cosmos: Dedicated Gateway (integrated cache) provisioning (`#/cosmos/uic-rg/uiccosmos/dedicatedgateway`)
  - cosmos: Hierarchical (multi-level) partition keys (`#/cosmos/uic-rg/uiccosmos/dataexplorer`)
  - cosmos: The Browse blade (select a container from Data Explorer instead) (`#/cosmos/uic-rg/uiccosmos/browse`)
  - cosmos: The Scale blade (select a container from Data Explorer instead) (`#/cosmos/uic-rg/uiccosmos/scale`)
- [ ] **Backup / recovery / geo-replication / disaster recovery (local snapshots)**: class A, size L (13 sections)
  - aks: Azure Backup for AKS (`#/aks/uic-rg/uicaks/backup`)
  - apim: Restoring a soft-deleted API Management service (`#/apim/uic-rg/gsd2ato`)
  - cosmos: Restoring a deleted/backed-up account (`#/cosmos`)
  - keyvaults: Restore Backup (`#/keyvaults/uic-rg/uickv/certificates`)
  - keyvaults: Restore Backup and Manage deleted keys (`#/keyvaults/uic-rg/uickv/keys`)
  - keyvaults: Restore Backup, View sample code and Manage deleted secrets (`#/keyvaults/uic-rg/uickv/secrets`)
  - sql: Copy a database (`#/sql/uic-rg/uicsqlsrv/gs14aup`)
  - sql: Geo-replication / active geo-replicas (`#/sql/uic-rg/uicsqlsrv/uicsqldb/replicas`)
  - sql: Restore a database (`#/sql/uic-rg/uicsqlsrv/gs14aup`)
  - storage: Geo-replication (`#/storage/uic-rg/uicstorage/redundancy`)
  - storage: Recovery (`#/storage/create`)
  - storage: Restoring a deleted storage account (`#/storage`)
  - vms: Disaster recovery (`#/vms/uic-rg/uicvm/disasterrecovery`)

### AZ-04 Compute/containers A: VM ops, ACR import, AKS ops, App Service/Function App ops

Classes: A | work packages: 4 | sections closed: 29

- [ ] **VM operations: updates, boot/performance diagnostics, serial console, disaster recovery, extensions, ASGs, load balancing**: class A, size L (4 sections)
  - vms: Application security groups (`#/vms/uic-rg/uicvm/asgs`)
  - vms: Boot diagnostics (`#/vms/uic-rg/uicvm/bootdiagnostics`)
  - vms: Load balancing (`#/vms/uic-rg/uicvm/loadbalancing`)
  - vms: Picking an existing standalone managed disk to attach (`#/vms/uic-rg/uicvm/disks`)
- [ ] **ACR import / copy image between registries**: class A, size M (1 section)
  - acr: Importing an image from another registry or source (`#/acr/uic-rg/gs48fdu`)
- [ ] **AKS operations: KEDA scaling, backup, extensions, networking settings, policy**: class A, size L (2 sections)
  - aks: Cluster extensions and applications (`#/aks/uic-rg/uicaks/extensionsapplications`)
  - aks: KEDA-based application scaling (`#/aks/uic-rg/uicaks/applicationscaling`)
- [ ] **App Service/Function App operations: auth, certificates, autoscale, WebJobs, default docs, path mappings, health check, clone, slots config, bindings editor, invocations**: class A, size L (22 sections)
  - appservices: API Management (`#/appservices/uic-rg/uicapp/apimanagement`)
  - appservices: API definition (`#/appservices/uic-rg/uicapp/apidefinition`)
  - appservices: App Service plan (`#/appservices/uic-rg/uicapp/appserviceplan`)
  - appservices: Authentication (`#/appservices/uic-rg/uicapp/authentication`)
  - appservices: Autoscale (rule-based/schedule-based scaling) (`#/appservices/uic-rg/uicapp/scaleout`)
  - appservices: Certificates (`#/appservices/uic-rg/uicapp/certificates`)
  - appservices: Clone App (`#/appservices/uic-rg/uicapp/cloneapp`)
  - appservices: Database (`#/appservices/create`)
  - appservices: Default documents (`#/appservices/uic-rg/uicapp/configuration`)
  - appservices: Error pages (preview) (`#/appservices/uic-rg/uicapp/configuration`)
  - appservices: Health check (`#/appservices/uic-rg/uicapp/healthcheck`)
  - appservices: Path mappings (`#/appservices/uic-rg/uicapp/configuration`)
  - appservices: Quotas (`#/appservices/uic-rg/uicapp/quotas`)
  - appservices: Secure unique default hostname on. (`#/appservices`)
  - ... and 8 more (full list in V4-GAP-QUEUE.json)

### AZ-05 Azure data-plane services A: APIM, App Configuration, Key Vault, Service Bus/Event Grid, DNS, VNet, Entra, other

Classes: A | work packages: 6 | sections closed: 14

- [ ] **API Management operations: gateways, soft-delete restore, capacity**: class A, size M (2 sections)
  - apim: Gateways (`#/apim/uic-rg/uicapim/apis/create`)
  - apim: The capacity gauge (`#/apim/uic-rg/gsd2ato`)
- [ ] **App Configuration: import/export key-values, CMK, identity, events**: class A, size M (2 sections)
  - appconfiguration: Bulk import/export of key-values (file, App Service, another configuration store) (`#/appconfiguration/uic-rg/gsox6i6/importexport`)
  - appconfiguration: Export and Import of key-values (file, App Service, another configuration store) (`#/appconfiguration/uic-rg/gsox6i6/explorer`)
- [ ] **Key Vault: restore backup, deleted keys/secrets, key attributes, content type, rotation policy**: class A, size M (2 sections)
  - keyvaults: Activation/expiration dates and tags on a new key (`#/keyvaults/uic-rg/uickv/keys`)
  - keyvaults: Content type, lifetime action and advanced policy configuration on a new certificate (`#/keyvaults/uic-rg/uickv/certificates`)
- [ ] **Service Bus / Event Grid extras: encryption, networking, events**: class A, size M (2 sections)
  - servicebus: Events (`#/servicebus/uic-rg/uicsbns/events`)
  - servicebus: Networking (`#/servicebus/uic-rg/uicsbns/networking`)
- [ ] **VNet operations: service endpoints, subnet delegation, advertised prefixes**: class A, size M (2 sections)
  - vnets: Service Endpoints (`#/vnets/uic-rg/uicvnet/subnets`)
  - vnets: Subnet Delegation (`#/vnets/uic-rg/uicvnet/subnets`)
- [ ] **Entra: sign-in logs, BitLocker keys, device blades**: class A, needs: directory-service; size L (4 sections)
  - entra: BitLocker keys (`#/entra/devices`)
  - entra: More commands (`#/entra/auditlogs`)
  - entra: User sign-ins (interactive) (`#/entra/signinlogs`)
  - entra: User sign-ins (non-interactive) (`#/entra/signinlogs`)

### AZ-06 Azure observability + security + support family: monitoring pipeline, Prometheus/Grafana/SCOM, Defender, support requests, Tasks

Classes: B | work packages: 5 | sections closed: 125 | families #3 #4 #10 #2

- [ ] **Per-resource Insights / Metrics / Alerts / Logs / Diagnostic settings / Workbooks / Log Analytics (monitoring pipeline)**: class B, family: observability; needs: observability-stack; size L (77 sections)
  - acr: Alerts (`#/acr/uic-rg/uicacr/alerts`)
  - acr: Insights (`#/acr/uic-rg/uicacr/insights`)
  - acr: Logs (`#/acr/uic-rg/uicacr/logs`)
  - acr: Metrics (`#/acr/uic-rg/uicacr/metrics`)
  - aks: Alert rules (`#/aks/uic-rg/uicaks/alerts`)
  - aks: Cluster metrics (`#/aks/uic-rg/uicaks/metrics`)
  - aks: Cluster monitoring (CPU/memory charts, node and pod health) (`#/aks/uic-rg/gs04rnr`)
  - aks: Container insights (`#/aks/uic-rg/uicaks/insights`)
  - aks: Log Analytics queries (`#/aks/uic-rg/uicaks/logs`)
  - aks: Workbooks (`#/aks/uic-rg/uicaks/workbooks`)
  - apim: API Management monitoring (capacity, requests, latency charts) (`#/apim/uic-rg/gsd2ato`)
  - apim: Monitor + secure (`#/apim/create`)
  - appconfiguration: Alert rules (`#/appconfiguration/uic-rg/gsox6i6/alerts`)
  - appconfiguration: Configuration store metrics (`#/appconfiguration/uic-rg/gsox6i6/metrics`)
  - ... and 63 more (full list in V4-GAP-QUEUE.json)
- [ ] **Managed Prometheus / Managed Grafana / SCOM / DCR / Azure Local**: class B, family: observability; needs: observability-stack; size L (6 sections)
  - monitor: #/monitor/datacollectionrules (`#/monitor/datacollectionrules`)
  - monitor: Azure Local (`#/monitor/insights-azurelocal`) [azure.monitor.azure_local_insights]
  - monitor: Azure Managed Grafana (`#/monitor/managedgrafana`) [azure.monitor.managed_grafana]
  - monitor: Azure Monitor SCOM managed instance (`#/monitor/scommanagedinstance`) [azure.monitor.scom_managed_instance]
  - monitor: Dashboards with Grafana (`#/monitor/grafanadashboards`) [azure.monitor.grafana_dashboards]
  - monitor: Managed Prometheus (`#/monitor/managedprometheus`) [azure.monitor.managed_prometheus]
- [ ] **Microsoft Defender for Cloud blades**: class B, family: security-scanning; needs: trivy-kubescape; size L (9 sections)
  - appservices: Enable Microsoft Defender for App Service (`#/appservices/create`)
  - cosmos: Microsoft Defender for Cloud (`#/cosmos/uic-rg/uiccosmos/defender`)
  - defender: Security alerts (`#/defender`) [azure.defender.alerts]
  - keyvaults: Microsoft Defender for Cloud (`#/keyvaults/uic-rg/uickv/defender`)
  - resourcegroups: Microsoft Defender for Cloud (`#/resourcegroups/uic-rg/security`)
  - sql: Microsoft Defender for Cloud (`#/sql/uic-rg/uicsqlsrv/uicsqldb/defender`)
  - sql: Microsoft Defender for SQL (`#/sql/create`)
  - storage: Microsoft Defender for Cloud (`#/storage/uic-rg/uicstorage/defender`)
  - vnets: Microsoft Defender for Cloud (`#/vnets/uic-rg/uicvnet/defender`)
- [ ] **New support request / Support + Troubleshooting (real tickets with Vyomi)**: class B, family: support-tickets; size M (19 sections)
  - acr: Support + Troubleshooting (`#/acr/uic-rg/uicacr/support`) [azure.acr.support_troubleshooting]
  - aks: Support + Troubleshooting (`#/aks/uic-rg/uicaks/supporttroubleshooting`)
  - apim: Support + Troubleshooting (`#/apim/uic-rg/gsohiig/support`)
  - appconfiguration: Support + Troubleshooting (`#/appconfiguration/uic-rg/gsox6i6/support`)
  - appservices: New support request (`#/appservices/uic-rg/uicapp/supportrequest`)
  - cognitiveservices: Support + Troubleshooting (`#/cognitiveservices/uic-rg/uiccogsvc/support`)
  - cosmos: Support + Troubleshooting (`#/cosmos/uic-rg/uiccosmos/support`)
  - cost: New support request (`#/cost/support`) [azure.monitor.new_support_request]
  - functionapp: New support request (`#/functionapp/uic-rg/uicfn/new-support-request`) [azure.functionapp.newsupportrequest]
  - keyvaults: Support + Troubleshooting (`#/keyvaults/uic-rg/uickv/support`)
  - monitor: New support request (`#/monitor/support`) [azure.monitor.new_support_request]
  - nsgs: Support + Troubleshooting (`#/nsgs/uic-rg/uicnsg/support`)
  - resourcegroups: Support + Troubleshooting (`#/resourcegroups/uic-rg/support`)
  - servicebus: Support + Troubleshooting (`#/servicebus/uic-rg/uicsbns/support`)
  - ... and 5 more (full list in V4-GAP-QUEUE.json)
- [ ] **Tasks / Automation / Logic App tasks**: class B, family: cicd-source; needs: buildkit; size L (14 sections)
  - aks: Tasks (`#/aks/uic-rg/uicaks/tasks`)
  - apim: Tasks (`#/apim/uic-rg/gsohiig/tasks`)
  - appconfiguration: Tasks (`#/appconfiguration/uic-rg/gsox6i6/tasks`)
  - appservices: Tasks (`#/appservices/uic-rg/uicapp/tasks`)
  - cognitiveservices: Tasks (`#/cognitiveservices/uic-rg/uiccogsvc/tasks`)
  - cosmos: Tasks (`#/cosmos/uic-rg/uiccosmos/tasks`)
  - eventgrid: Tasks (`#/eventgrid/topics/cloudlearn-rg/uic-eg-topic/tasks`) [azure.eventgrid.topic.tools]
  - functionapp: Tasks (`#/functionapp/uic-rg/uicfn/tasks`) [azure.functionapp.tasks]
  - keyvaults: Tasks (`#/keyvaults/uic-rg/uickv/tasks`)
  - resourcegroups: Tasks (`#/resourcegroups/uic-rg/tasks`)
  - servicebus: Tasks (`#/servicebus/uic-rg/uicsbns/tasks`)
  - sql: Tasks (`#/sql/uic-rg/uicsqlsrv/uicsqldb/tasks`)
  - storage: Tasks (`#/storage/uic-rg/uicstorage/tasks`)
  - vms: Tasks (`#/vms/uic-rg/uicvm/tasks`)

### AZ-07 Azure networking + SSH + CI/CD family: private endpoints/Firewall/Bastion/DDoS, NSG flow logs, App Service console/Kudu, VM guest ops, Deployment Center

Classes: B | work packages: 5 | sections closed: 48 | families #5 #1 #2

- [ ] **Private endpoints / custom VNet / Firewall / Bastion / DDoS / Front Door / network manager**: class B, family: networking-dataplane; needs: netsim; size L (31 sections)
  - aks: Cluster networking settings (configured at create time; see the create wizard's Networking (`#/aks/uic-rg/uicaks/networking`)
  - appconfiguration: Private endpoint (`#/appconfiguration/create`)
  - appservices: Enable network injection (`#/appservices/create`)
  - appservices: Networking (`#/appservices/uic-rg/uicapp/networking`)
  - cognitiveservices: Private endpoint connections (`#/cognitiveservices/uic-rg/uiccogsvc/networking`)
  - containerapps: Custom VNet integration (`#/containerapps/environments/uic-rg/uiccae/networking`)
  - containerapps: Custom virtual network (`#/containerapps/environments/create`)
  - containerapps: Networking (`#/containerapps/uic-rg/uicapp/dapr`) [azure.containerapps.app.networking]
  - cosmos: Private endpoint / VNet networking configuration (see the create wizard's Connectivity met (`#/cosmos/uic-rg/uiccosmos/networking`)
  - keyvaults: Private endpoint (`#/keyvaults/create`)
  - keyvaults: Private endpoint connections (`#/keyvaults/uic-rg/uickv/networking`)
  - sql: Private endpoint connections (`#/sql/servers/uic-rg/uicsqlsrv/networking`)
  - sql: Private endpoints (`#/sql/create`)
  - sql: Virtual networks (`#/sql/servers/uic-rg/uicsqlsrv/networking`)
  - ... and 17 more (full list in V4-GAP-QUEUE.json)
- [ ] **NSG flow logs**: class B, family: networking-dataplane; needs: netsim; size M (1 section)
  - nsgs: NSG flow logs (`#/nsgs/uic-rg/uicnsg/flowlogs`)
- [ ] **App Service console / SSH / Kudu / process explorer / log streaming**: class B, family: ssh-shell; needs: tunnel-tcp-relay; size L (9 sections)
  - appservices: Advanced Tools (`#/appservices/uic-rg/uicapp/advancedtools`)
  - appservices: App Service Editor (Preview) (`#/appservices/uic-rg/uicapp/appeditor`)
  - appservices: Console (`#/appservices/uic-rg/uicapp/console`)
  - appservices: Extensions (`#/appservices/uic-rg/uicapp/extensions`)
  - appservices: Live log streaming (`#/appservices/uic-rg/uicapp/logstream`)
  - appservices: Process explorer (`#/appservices/uic-rg/uicapp/processexplorer`)
  - functionapp: Advanced Tools (`#/functionapp/uic-rg/uicfn/advanced-tools`) [azure.functionapp.advancedtools]
  - functionapp: Extensions (`#/functionapp/uic-rg/uicfn/extensions`) [azure.functionapp.extensions]
  - vms: Serial console (`#/vms/uic-rg/uicvm/serialconsole`)
- [ ] **VM guest operations: extensions, update management (needs guest agent over SSH)**: class B, family: ssh-shell; needs: tunnel-tcp-relay; size L (2 sections)
  - vms: Extensions + applications (`#/vms/uic-rg/uicvm/extensions`)
  - vms: Updates (`#/vms/uic-rg/uicvm/updates`)
- [ ] **Deployment Center / GitHub Actions / GitOps / automated deployments**: class B, family: cicd-source; needs: buildkit, gitea; size L (5 sections)
  - aks: Automated deployments (GitHub Actions) (`#/aks/uic-rg/uicaks/automateddeployments`)
  - aks: Flux GitOps configurations (`#/aks/uic-rg/uicaks/gitops`)
  - appservices: Deployment Center (`#/appservices/uic-rg/uicapp/deploymentcenter`)
  - appservices: GitHub Actions details (`#/appservices/create`)
  - functionapp: Deployment Center (`#/functionapp/uic-rg/uicfn/deployment-center`) [azure.functionapp.deploymentcenter]

### AZ-08 Azure data / directory / marketplace / billing family: Resource Graph, migration, Files, AI Search, subscriptions, Marketplace, Cost Management

Classes: B | work packages: 6 | sections closed: 34 | families #6 #7 #8 #9

- [ ] **Data migration / Storage Mover / Data Sync / mirroring / Fabric / integrations**: class B, family: data-analytics; size L (12 sections)
  - cosmos: Azure Function integration (`#/cosmos/uic-rg/uiccosmos/addfunction`)
  - cosmos: Power BI integration (`#/cosmos/uic-rg/uiccosmos/powerbi`)
  - cosmos: The Data Migration tool integration (`#/cosmos/uic-rg/uiccosmos/datamigration`)
  - sql: Azure Stream Analytics integration (`#/sql/uic-rg/uicsqlsrv/uicsqldb/streamanalytics`)
  - sql: Data Sync between databases (`#/sql/uic-rg/uicsqlsrv/uicsqldb/syncdatabases`)
  - sql: Integrations (`#/sql/uic-rg/uicsqlsrv/gs14aup`)
  - sql: Mirroring this database into Microsoft Fabric (`#/sql/uic-rg/uicsqlsrv/uicsqldb/mirrorfabric`)
  - sql: Power Apps integration (`#/sql/uic-rg/uicsqlsrv/uicsqldb/powerapps`)
  - sql: Power Automate integration (`#/sql/uic-rg/uicsqlsrv/uicsqldb/powerautomate`)
  - sql: Power BI integration (`#/sql/uic-rg/uicsqlsrv/uicsqldb/powerbi`)
  - storage: Data migration (`#/storage/uic-rg/uicstorage/datamigration`)
  - storage: Storage Mover (`#/storage/uic-rg/uicstorage/storagemover`)
- [ ] **Azure Files / NFS / file shares (Samba)**: class B, family: data-analytics; size L (9 sections)
  - storage: Access protocols (`#/storage/create`)
  - storage: Azure Files (`#/storage/create`)
  - storage: File service (`#/storage/uic-rg/uicstorage/cors`)
  - storage: File shares (`#/storage/uic-rg/uicstorage/fileshares`)
  - storage: Large file shares (`#/storage/uic-rg/uicstorage/configuration`)
  - storage: NFS v3 (`#/storage/uic-rg/gskbx8l`)
  - storage: Other services (`#/storage/uic-rg/uicstorage/endpoints`)
  - storage: Queue service (`#/storage/uic-rg/uicstorage/cors`)
  - storage: Table service (`#/storage/uic-rg/uicstorage/cors`)
- [ ] **AI Search / Stream Analytics / Power platform integrations (embedded search + stubs)**: class B, family: data-analytics; size M (3 sections)
  - cosmos: Azure Cognitive Search integration (`#/cosmos/uic-rg/uiccosmos/addsearch`)
  - sql: Azure AI Search integration (`#/sql/uic-rg/uicsqlsrv/uicsqldb/addazuresearch`)
  - storage: Azure AI Search (`#/storage/uic-rg/uicstorage/azureaisearch`)
- [ ] **Subscriptions: ownership transfer, PIM, partner info, quota requests, certificates**: class B, family: directory-orgs; needs: directory-service; size M (4 sections)
  - subscriptions: Management certificates (`#/subscriptions/00000000-0000-0000-0000-cloudlearn01/managementcertificates`)
  - subscriptions: Requesting a quota increase (`#/subscriptions/00000000-0000-0000-0000-cloudlearn01/usagequotas`)
  - subscriptions: Subscription ownership-transfer requests (`#/subscriptions`)
  - subscriptions: Top free services by usage (`#/subscriptions/00000000-0000-0000-0000-cloudlearn01`)
- [ ] **Marketplace / partner solutions / new-from-marketplace (Vyomi SaaS spaces)**: class B, family: marketplace-saas; size M (4 sections)
  - resourcegroups: Creating a new resource from the Marketplace (`#/resourcegroups/uic-rg`)
  - storage: Partner solutions (`#/storage/uic-rg/uicstorage/partnersolutions`)
  - subscriptions: Creating a new resource from the Marketplace (`#/subscriptions/00000000-0000-0000-0000-cloudlearn01/resources`)
  - subscriptions: Partner information (`#/subscriptions/00000000-0000-0000-0000-cloudlearn01/partnerinformation`) [azure.subscriptions.partner_information]
- [ ] **Cost management + invoices (simulated, 'cost saved' dashboard)**: class B, family: billing; size M (2 sections)
  - cosmos: Cost Management for this account (`#/cosmos/uic-rg/uiccosmos/costmgmt`)
  - cost: Invoices (`#/cost/invoices`) [azure.cost.invoices]

### AZ-09 Azure unbuildable / editorial

Classes: C/N | work packages: 4 | sections closed: 37 | class C and N

- [ ] **Diagnose and solve problems (Azure fleet diagnostics)**: class C, size S (17 sections)
  - aks: Diagnose and solve problems (`#/aks/uic-rg/uicaks/diagnose`)
  - apim: Diagnose and solve problems (`#/apim/uic-rg/gsohiig/diagnose`)
  - appconfiguration: Diagnose and solve problems (`#/appconfiguration/uic-rg/gsox6i6/diagnose`)
  - appservices: Diagnose and solve problems (`#/appservices/uic-rg/uicapp/diagnose`)
  - cognitiveservices: Diagnose and solve problems (`#/cognitiveservices/uic-rg/uiccogsvc/diagnose`)
  - containerapps: Diagnose and solve problems (`#/containerapps/environments/uic-rg/uiccae/logs`) [azure.containerapps.environment.tools]
  - containerapps: Diagnose and solve problems (`#/containerapps/uic-rg/uicapp/events`) [azure.containerapps.app.tools]
  - containerapps: Diagnose and solve problems (`#/containerapps/jobs/uic-rg/uicjob/diagnose`) [azure.containerapps.job.tools]
  - cosmos: Diagnose and solve problems (`#/cosmos/uic-rg/uiccosmos/diagnose`)
  - dns: Diagnose and solve problems (`#/dns/uic-rg/uic-dns-zone.com/diagnose`)
  - keyvaults: Diagnose and solve problems (`#/keyvaults/uic-rg/uickv/diagnose`)
  - loganalytics: Diagnose and solve problems (`#/loganalytics/uic-rg/uiclaw/diagnose`) [azure.loganalytics.workspace.tools]
  - servicebus: Diagnose and solve problems (`#/servicebus/uic-rg/uicsbns/diagnose`)
  - sql: Diagnose and solve problems (`#/sql/uic-rg/uicsqlsrv/uicsqldb/diagnose`)
  - ... and 3 more (full list in V4-GAP-QUEUE.json)
- [ ] **Payment methods (never)**: class C, size S (1 section)
  - cost: Payment methods (`#/cost/paymentmethods`) [azure.cost.payment_methods]
- [ ] **Tutorials / capabilities overview / features overview / quick start / feedback / quotas docs**: class C, size S (18 sections)
  - aks: The capabilities overview (`#/aks/uic-rg/gs04rnr`)
  - aks: Tutorials (`#/aks/uic-rg/gs04rnr`)
  - appservices: The capabilities overview (`#/appservices/uic-rg/uicapp`)
  - cosmos: The Features overview (`#/cosmos/uic-rg/uiccosmos/features`)
  - cosmos: The Quick start code samples blade (`#/cosmos/uic-rg/uiccosmos/quickstart`)
  - cosmos: Tutorials (`#/cosmos/uic-rg/uiccosmos`)
  - entra: Export Data Settings, Troubleshoot, Columns, Got feedback? (`#/entra/signinlogs`)
  - functionapp: The capabilities overview (`#/functionapp/uic-rg/uicfn`)
  - keyvaults: The capabilities overview (`#/keyvaults/uic-rg/gs5upkp`)
  - keyvaults: Tutorials (`#/keyvaults/uic-rg/gs5upkp`)
  - monitor: Feedback (`#/monitor/insightshub`)
  - sql: The features overview (`#/sql/uic-rg/uicsqlsrv/gs14aup`)
  - sql: Tutorials (`#/sql/uic-rg/uicsqlsrv/gs14aup`)
  - storage: The capabilities overview (`#/storage/uic-rg/gskbx8l`)
  - ... and 4 more (full list in V4-GAP-QUEUE.json)
- [ ] **Transient 'Not simulated' text without the data attribute; re-check**: class N, size S (1 section)
  - monitor: Not simulated in Vyomi (`#/monitor/metrics`)

## 4. Substrate differences (offline vs Nano)

- AWS: only on offline: none. Only on Nano: ec2: CPU and network metrics; ec2: CloudWatch metrics.
- GCP: only on offline: none. Only on Nano: networking: Flow log records.
- AZURE: only on offline: none. Only on Nano: none.

## 5. What the scanner could not reach

- aws/nano: pages 695; unreached parameterised routes: /cloudformation/stacks/:name/update, /ec2/create-snapshot/:volumeId, /ec2/security-groups/:id/edit-outbound-rules, /eventbridge/archives/:name/edit, /eventbridge/pipes/:name, /vpc/vpcs/:id/edit-settings, /vpc/security-groups/:id/edit-inbound-rules, /vpc/security-groups/:id/edit-outbound-rules, /vpc/transit-gateway-route-tables/:id; fixture errors: 1 (rds/live-export-task: POST / -> 404 <?xml version="1.0" encoding="UTF-8"?><ErrorResponse xmlns="http://rds.ama...)
- aws/offline: pages 693; unreached parameterised routes: /cloudformation/stacks/:name/update, /ec2/instances/:id, /ec2/instances/:id/create-image, /ec2/create-snapshot/:volumeId, /ec2/security-groups/:id/edit-outbound-rules, /eventbridge/archives/:name/edit, /eventbridge/pipes/:name, /vpc/vpcs/:id/edit-settings, /vpc/security-groups/:id/edit-inbound-rules, /vpc/security-groups/:id/edit-outbound-rules, /vpc/transit-gateway-route-tables/:id; fixture errors: 6 (ec2/live-instance: POST / -> 503 <Response><Errors><Error><Code>AMI 'Amazon Linux 2023' is not supported on da...)
- azure/nano: pages 900; unreached parameterised routes: /apim/:rg/:name/apis/create/:apitype, /sql/servers/:rg/:server; fixture errors: 0
- azure/offline: pages 2038; unreached parameterised routes: /apim/:rg/:name/apis/create/:apitype, /sql/servers/:rg/:server; fixture errors: 0
- gcp/nano: pages 355; unreached parameterised routes: /security/kms/keyring/manage/:location/:name, /security/kms/key/manage/:location/:keyring/:name, /security/secret-manager/secret/:name, /security/secret-manager/regional/:location/:name; fixture errors: 0
- gcp/offline: pages 355; unreached parameterised routes: /security/kms/keyring/manage/:location/:name, /security/kms/key/manage/:location/:keyring/:name, /security/secret-manager/secret/:name, /security/secret-manager/regional/:location/:name; fixture errors: 3 (iam-admin/deny-policy: POST /v2/policies/cloudresourcemanager.googleapis.com%2Fprojects%2Fvyomi-project/denypo...)
- Parameterised edit routes that need a second id (e.g. `/ec2/security-groups/:id/edit-outbound-rules`, `/vpc/vpcs/:id/edit-settings`) were visited separately with a real id (`EXTRA_ROUTES`) and show no Not-simulated sections; `/ec2/instances/:id` and `/ec2/create-snapshot/:volumeId` have no offline reach on macOS.
- Azure: the Nano run used the default link-crawl cap (900 pages) and the offline run a raised cap (SHAPE_CAP=60) and was stopped after ~2000 pages once the distinct-finding count had stayed flat for 140 pages; both give the same 488 raw sections (Azure ARM blades are mostly reached through `spec-map.json` seeds, the crawl only adds more resource instances).
- States that only appear after a real action (a running instance's serial console, a failed deployment, a scheduled maintenance event) are not covered; the scanner opens and cancels wizards/modals but does not submit them.

