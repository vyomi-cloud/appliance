#!/usr/bin/env python3
"""Turn gap-scan.mjs output into the classified implementation queue.

  python3 consoles/tests/gap-queue.py <scan-out-dir>        (dir holds offline-<cloud>.json / nano-<cloud>.json)
  -> docs/architecture/v4.0/V4-GAP-QUEUE.md + V4-GAP-QUEUE.json

Classification (docs/architecture/v4.0/V4-GAP-BACKENDS-DECISIONS.md numbers in family names):
  A  buildable as a lightweight core on BOTH substrates (offline python + Nano in-browser)
  B  belongs to a decided backend family (SSH tunnel / BuildKit+Gitea / observability / security /
     networking / data-analytics / directory / marketplace / billing / support / local LLM)
  C  honestly unbuildable (real-cloud-only, hardware, editorial content, payments)
  N  not a gap (state-dependent panel, e.g. Object Lock shown only when the bucket has no lock)
The rules are ordered regexes over "<service> | <title> | <note>"; the first match wins. Anything that
matches no rule is printed as UNCLASSIFIED and listed in the queue so nothing is silently dropped."""
import json, re, sys, os, collections, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = Path(sys.argv[1])
CLOUDS = ["aws", "gcp", "azure"]

FAMILY = {1: "ssh-shell", 2: "cicd-source", 3: "observability", 4: "security-scanning", 5: "networking-dataplane", 6: "data-analytics",
          7: "directory-orgs", 8: "marketplace-saas", 9: "billing", 10: "support-tickets", 11: "local-llm"}

# theme -> (class, family#, size, deps, label)
T = {}
def theme(name, cls, fam, size, label, deps=()):
    T[name] = dict(cls=cls, family=FAMILY.get(fam), size=size, deps=list(deps), label=label)

# ---------------------------------------------------------------- AWS
theme("s3-metadata", "A", 0, "M", "S3 Metadata configuration (journal + live inventory tables)", ["s3-tables"])
theme("s3-lens", "A", 0, "M", "Storage Lens metrics (bucket Metrics tab)", ["cloudwatch-metrics"])
theme("s3-vectors", "A", 0, "M", "S3 Vector buckets (vector index + query, in-process)")
theme("s3-files", "B", 6, "L", "S3 file systems / Files (NFS-style) ")
theme("s3-fsx", "B", 6, "M", "Access points for FSx", ["s3-files"])
theme("s3-accel", "B", 5, "S", "Transfer acceleration (endpoint alias via Caddy)")
theme("s3-market", "B", 8, "M", "AWS Marketplace for S3 (Vyomi SaaS spaces)")
theme("editorial", "C", 0, "S", "Editorial / marketing / doc-link content with no resource behind it")
theme("objlock-cond", "N", 0, "S", "Object Lock panels (render only when the bucket has no lock; verified real on a locked bucket)")
theme("cloudtrail-core", "A", 0, "L", "CloudTrail event store (new core: record management + S3 data events)")
theme("cloudtrail-s3", "A", 0, "S", "CloudTrail data events for S3", ["cloudtrail-core"])
theme("iam-svc-access", "A", 0, "M", "IAM service access report (derived from CloudTrail + Organizations)", ["cloudtrail-core", "organizations"])
theme("iam-cf-keys", "B", 5, "M", "Root CloudFront key pairs (needs CDN/CloudFront)")
theme("iam-role-mgr", "C", 0, "S", "IAM Role manager (no public API in AWS)")
theme("ec2-ultra", "C", 0, "S", "EC2 UltraServers (multi-host accelerator domains: hardware)")
theme("ec2-zones", "A", 0, "S", "EC2 Zones / AZ listing")
theme("ec2-alarms", "A", 0, "S", "EC2 instance alarms (CloudWatch alarm list for instances)", ["cloudwatch-alarms"])
theme("ec2-events", "A", 0, "S", "EC2 scheduled events page")
theme("ec2-health-rollup", "A", 0, "S", "EC2 account-wide instance status rollup")
theme("ec2-volume-ft", "A", 0, "S", "EBS fault-tolerance (snapshot coverage) widget")
theme("ec2-iam-profile", "A", 0, "S", "Create IAM instance profile page", ["iam"])
theme("ec2-compare-sg", "A", 0, "S", "Compare security group rules")
theme("ec2-type-finder", "A", 0, "S", "Instance type finder")
theme("ec2-recycle", "A", 0, "M", "Recycle Bin (AMI/snapshot retention rules)")
theme("ec2-asg", "A", 0, "M", "Managed resources / Auto Scaling settings tab", ["autoscaling-core"])
theme("ec2-spot", "A", 0, "L", "Spot / purchasing options / capacity manager / reservations (simulated, no billing)")
theme("ec2-connect", "B", 1, "L", "EC2 Connect (SSH/Session Manager/EC2 Instance Connect)", ["tunnel-tcp-relay"])
theme("ec2-metrics", "B", 3, "L", "Instance CPU/network + EBS volume CloudWatch metrics", ["docker-stats-to-cloudwatch"])
theme("ec2-market-ami", "B", 8, "M", "Marketplace + community AMIs")
theme("ec2-imagebuilder", "B", 2, "L", "EC2 Image Builder pipelines", ["buildkit"])
theme("ec2-migrate", "B", 6, "L", "Migrate a server (Application Migration Service)")
theme("ec2-ram", "B", 7, "M", "RAM sharing of security groups", ["directory-service"])
theme("billing-dash", "B", 9, "M", "Cost / spend widgets (cost-saved dashboard, simulated)")
theme("service-health", "C", 0, "S", "Region-wide service health (AWS-side events)")
theme("canvas", "A", 0, "L", "Visual drag-and-drop canvas (CFN Template Studio, EventBridge builder, Lambda Infrastructure Composer)")
theme("eb-crypto", "A", 0, "S", "EventBridge bus/archive KMS encryption", ["kms"])
theme("eb-logs", "A", 0, "S", "EventBridge bus logs to CloudWatch Logs", ["cloudwatch-logs"])
theme("eb-policy", "A", 0, "M", "EventBridge resource-policy enforcement", ["iam-policy-eval"])
theme("eb-archive-create", "A", 0, "S", "Attach archive at bus creation")
theme("eb-schemas", "A", 0, "M", "EventBridge schema registry + discovery")
theme("partner-sources", "B", 8, "M", "Partner event sources / SaaS partners")
theme("cfn-policy", "A", 0, "S", "CloudFormation stack policy enforcement")
theme("cfn-rollback", "A", 0, "M", "CloudFormation rollback triggers (CloudWatch alarms)", ["cloudwatch-alarms"])
theme("cfn-notify", "A", 0, "S", "CloudFormation SNS stack notifications", ["sns"])
theme("cfn-gitsync", "B", 2, "M", "CloudFormation Git sync", ["gitea"])
theme("cfn-stackset-org", "B", 7, "M", "StackSets service-managed permissions (Organizations)", ["directory-service"])
theme("cfn-registry", "B", 8, "L", "CloudFormation public extensions / publisher registry")
theme("ddb-backup", "A", 0, "M", "DynamoDB backup copy across Region/account + AWS Backup integration toggle")
theme("ddb-autoscale", "A", 0, "M", "DynamoDB provisioned-capacity auto scaling", ["autoscaling-core"])
theme("ddb-reserved", "C", 0, "S", "Reserved capacity purchase (billing/payment)")
theme("zero-etl", "B", 6, "L", "Zero-ETL integrations (DynamoDB/RDS to Redshift/lakehouse)")
theme("lambda-agent", "B", 11, "L", "Lambda/AgentCore agent onboarding + AgentCore targets", ["local-llm"])
theme("lambda-rds-proxy", "A", 0, "M", "Lambda RDS databases (RDS Proxy connection helper)", ["rds"])
theme("lambda-cicd", "B", 2, "L", "Lambda CI/CD pipeline application", ["buildkit", "gitea"])
theme("sm-rotation", "A", 0, "M", "Secrets Manager rotation function invocation", ["lambda"])
theme("rds-metrics", "B", 3, "M", "RDS instance metrics (CPU/memory/storage) + Database Insights", ["docker-stats-to-cloudwatch"])
theme("rds-alarms", "A", 0, "S", "RDS CloudWatch alarms tab", ["cloudwatch-alarms"])
theme("rds-dms", "B", 6, "L", "RDS data migrations (DMS)")
theme("rds-iam-assoc", "A", 0, "S", "RDS IAM role association", ["iam"])
theme("rds-restore-s3", "A", 0, "M", "RDS restore from S3 backup", ["s3"])
theme("rds-capres", "C", 0, "S", "RDS capacity reservations (capacity-market / billing construct)")
theme("rds-pages", "A", 0, "M", "RDS dashboard + service-quota pages")
theme("sns-integrations", "A", 0, "S", "SNS Integrations tab (links to wizards)")
theme("sns-fixed", "C", 0, "S", "SNS settings that do not exist in the real API (max message size, TTL)")
theme("sns-sms", "B", 6, "M", "SNS SMS/mobile push OTP + sandbox delivery")
theme("vpc-acct", "A", 0, "S", "VPC account-level pages (encryption control, cross-Region summary)")
theme("vpc-multisubnet", "A", 0, "S", "Create multiple subnets in one batch")
theme("vpc-lattice", "B", 5, "L", "VPC Lattice service networks", ["netsim"])
theme("vpc-nfw-containers", "B", 5, "M", "Network Firewall container associations", ["netsim"])
theme("vpc-external", "C", 0, "S", "Network Manager / external console link-outs")
theme("security-hub", "B", 4, "M", "Security Hub findings", ["trivy-kubescape"])
theme("unverified-text", "N", 0, "S", "Transient 'Not simulated' text without the data attribute (state-dependent / mid-render); re-check")

# ---------------------------------------------------------------- GCP
theme("gce-incidents", "C", 0, "S", "Google Cloud incidents / service health")
theme("gce-security-risk", "B", 4, "M", "Compute security risk overview", ["trivy-kubescape"])
theme("gce-recommender", "A", 0, "M", "Recommender engine (Compute Advisor / dashboard recommendations / Recommender & VM Manager)")
theme("gce-ssh", "B", 1, "L", "GCE SSH / OS info / serial (real sshd in container)", ["tunnel-tcp-relay"])
theme("gce-schedules", "A", 0, "M", "Instance schedules (scheduled start/stop)")
theme("gce-import", "B", 6, "L", "Import VM / Migrate to VMs / image import-export history")
theme("gce-backup", "A", 0, "M", "VM backups + extra disks + snapshot schedules / instant snapshots / async replication / consistency groups")
theme("gce-lb-nic", "A", 0, "M", "Multiple NICs + health-check firewall + NEGs", ["netsim"])
theme("gce-opsagent", "B", 3, "M", "Ops Agent install + monitoring on instances", ["observability-stack"])
theme("gce-hw", "C", 0, "S", "Hardware: TPUs, Bare Metal Solution, sole-tenant hardware")
theme("gce-sole", "A", 0, "M", "Sole-tenant nodes / reservations / storage pools / rollouts")
theme("gce-commit", "C", 0, "S", "Committed use discounts (purchase)")
theme("gce-vm-manager", "B", 1, "L", "VM Manager: Patch, OS policies, VM extension policies (guest agent)", ["gce-ssh"])
theme("gce-misc-c", "C", 0, "S", "Preview features / screenshot / capacity advisor (Google-side)")
theme("fs-rules", "A", 0, "L", "Firestore security-rules evaluator")
theme("run-scaling", "A", 0, "M", "Cloud Run/Functions autoscaling factors, health checks, volumes, ephemeral disk, revision tags, connections")
theme("run-net", "B", 5, "M", "Custom URLs, HTTP/2, session affinity, VPC egress, service mesh", ["netsim"])
theme("run-gpu", "C", 0, "S", "GPU for Cloud Run/Functions")
theme("run-sqlconn", "A", 0, "M", "Cloud SQL connections for Run/Functions", ["sql"])
theme("run-kms", "A", 0, "M", "Binary Authorization + CMEK for Run/Functions", ["kms"])
theme("run-source", "B", 2, "L", "Source deploy / connect repo / continuous deployment", ["buildkit", "gitea"])
theme("run-eventarc", "A", 0, "L", "Eventarc triggers (non-Pub/Sub sources)")
theme("run-image-picker", "A", 0, "S", "Artifact Registry image picker", ["artifacts"])
theme("iam-simulate", "A", 0, "M", "Org policy constraint simulation")
theme("iam-wif", "A", 0, "M", "Workload/Workforce identity federation (OIDC/SAML) + attribute mapping", ["sts-core"])
theme("cai-query", "B", 6, "M", "Cloud Asset Inventory custom queries (graph engine)", ["resource-graph-engine"])
theme("org-folders", "B", 7, "M", "Organization / folder browse + privacy & security", ["directory-service"])
theme("logs-correlate", "A", 0, "M", "Logs correlate-by trace")
theme("obs-trace", "B", 3, "L", "Trace explorer / trace + log scopes / Memorystore + app monitoring", ["observability-stack"])
theme("net-hybrid", "B", 5, "L", "VLAN attachments / BYOIP / flow logs", ["netsim", "frr-wireguard"])
theme("sql-flags", "A", 0, "M", "Cloud SQL custom machine shapes, SSL enforcement, CMEK", ["kms"])
theme("gcs-config", "A", 0, "M", "GCS turbo replication / Autoclass / CMEK / per-object keys / holds")
theme("gcs-insights", "B", 6, "L", "GCS Rapid Cache / inventory reports / object enrichments (Storage Insights)")
theme("gcs-sec-insights", "B", 4, "M", "Storage security insights / recommendations", ["trivy-kubescape"])
theme("datastore", "A", 0, "L", "Datastore mode (Firestore in Datastore mode)")
theme("kms-hsm", "C", 0, "S", "HSM / external key protection levels")
theme("kms-import", "A", 0, "M", "Imported key material", ["kms"])
theme("gcp-market", "B", 8, "M", "GCP Marketplace (Vyomi SaaS spaces)")
theme("cloud-hub", "C", 0, "S", "Cloud Hub (Google-side aggregate)")

# ---------------------------------------------------------------- Azure (cross-cutting blades first)
theme("az-export-template", "A", 0, "M", "Export template (ARM -> Bicep/Terraform) on every resource")
theme("az-activity-cols", "A", 0, "S", "Activity log: edit columns / filters / export")
theme("az-rbac-extras", "A", 0, "S", "Access control extras: Deny assignments, Classic administrators, My access", ["rbac"])
theme("az-grid-tools", "A", 0, "S", "Browse-grid tools: edit columns / bulk tag assignment / manage view / favourites")
theme("az-resource-graph", "B", 6, "M", "Open query (Azure Resource Graph)", ["resource-graph-engine"])
theme("az-monitor-blades", "B", 3, "L", "Per-resource Insights / Metrics / Alerts / Logs / Diagnostic settings / Workbooks / Log Analytics (monitoring pipeline)", ["observability-stack"])
theme("az-diag-settings", "A", 0, "M", "Diagnostic settings (config store + routing to Log Analytics/Storage/Event Hub)", ["loganalytics"])
theme("az-resource-health", "A", 0, "M", "Resource health + Advisor recommendations (derived from resource state)")
theme("az-support", "B", 10, "M", "New support request / Support + Troubleshooting (real tickets with Vyomi)")
theme("az-diagnose", "C", 0, "S", "Diagnose and solve problems (Azure fleet diagnostics)")
theme("az-tasks", "B", 2, "L", "Tasks / Automation / Logic App tasks", ["buildkit"])
theme("az-defender", "B", 4, "L", "Microsoft Defender for Cloud blades", ["trivy-kubescape"])
theme("az-private-net", "B", 5, "L", "Private endpoints / custom VNet / Firewall / Bastion / DDoS / Front Door / network manager", ["netsim"])
theme("az-managed-identity", "A", 0, "M", "User-assigned + managed identity assignment on resources", ["managed-identity-core"])
theme("az-cmk", "A", 0, "M", "Customer-managed keys / encryption (Key Vault backed)", ["keyvaults"])
theme("az-eventgrid-sub", "A", 0, "M", "Event Grid subscriptions on resource events (system topics)", ["eventgrid"])
theme("az-policy", "A", 0, "L", "Azure Policy compliance + assignments", ["policy-engine"])
theme("az-backup-dr", "A", 0, "L", "Backup / recovery / geo-replication / disaster recovery (local snapshots)")
theme("az-visualizer", "A", 0, "M", "Resource visualizer (graph from ARM state)")
theme("az-console-kudu", "B", 1, "L", "App Service console / SSH / Kudu / process explorer / log streaming", ["tunnel-tcp-relay"])
theme("az-cicd", "B", 2, "L", "Deployment Center / GitHub Actions / GitOps / automated deployments", ["buildkit", "gitea"])
theme("az-marketplace", "B", 8, "M", "Marketplace / partner solutions / new-from-marketplace (Vyomi SaaS spaces)")
theme("az-billing", "B", 9, "M", "Cost management + invoices (simulated, 'cost saved' dashboard)")
theme("az-payment", "C", 0, "S", "Payment methods (never)")
theme("az-data-migration", "B", 6, "L", "Data migration / Storage Mover / Data Sync / mirroring / Fabric / integrations")
theme("az-files", "B", 6, "L", "Azure Files / NFS / file shares (Samba)")
theme("az-search", "B", 6, "M", "AI Search / Stream Analytics / Power platform integrations (embedded search + stubs)")
theme("az-storage-protect", "A", 0, "M", "Blob protection: soft delete, versioning, change feed, point-in-time restore, immutability")
theme("az-storage-cfg", "A", 0, "M", "Storage account config: custom domain, CORS, encryption scopes, access control, geo-replication, large file shares")
theme("az-sql-security", "A", 0, "L", "SQL security + perf: TDE keys, Always Encrypted, ledger, masking, classification, auditing, Query Performance Insight")
theme("az-sql-ops", "A", 0, "M", "SQL operations: copy/restore database, geo-replication, stored procedures, maintenance, connectivity policy")
theme("az-cosmos-ops", "A", 0, "M", "Cosmos operations: restore, hierarchical partition keys, CORS, dedicated gateway, CMK, scale/browse blades")
theme("az-aks-ops", "A", 0, "L", "AKS operations: KEDA scaling, backup, extensions, networking settings, policy")
theme("az-app-ops", "A", 0, "L", "App Service/Function App operations: auth, certificates, autoscale, WebJobs, default docs, path mappings, health check, clone, slots config, bindings editor, invocations")
theme("az-apim-ops", "A", 0, "M", "API Management operations: gateways, soft-delete restore, capacity")
theme("az-appconfig-ops", "A", 0, "M", "App Configuration: import/export key-values, CMK, identity, events")
theme("az-kv-ops", "A", 0, "M", "Key Vault: restore backup, deleted keys/secrets, key attributes, content type, rotation policy")
theme("az-entra", "A", 0, "L", "Entra: sign-in logs, BitLocker keys, device blades", ["directory-service"])
theme("az-subscriptions", "B", 7, "M", "Subscriptions: ownership transfer, PIM, partner info, quota requests, certificates", ["directory-service"])
theme("az-rg-ops", "A", 0, "M", "Resource group: force delete, deployment stacks, policy compliance, custom blade layout")
theme("az-vm-ops", "A", 0, "L", "VM operations: updates, boot/performance diagnostics, serial console, disaster recovery, extensions, ASGs, load balancing")
theme("az-vnet-ops", "A", 0, "M", "VNet operations: service endpoints, subnet delegation, advertised prefixes")
theme("az-nsg-flow", "B", 5, "M", "NSG flow logs", ["netsim"])
theme("az-dns-ops", "A", 0, "S", "DNS extras")
theme("az-sb-ops", "A", 0, "M", "Service Bus / Event Grid extras: encryption, networking, events")
theme("az-monitor-products", "B", 3, "L", "Managed Prometheus / Managed Grafana / SCOM / DCR / Azure Local", ["observability-stack"])
theme("az-editorial", "C", 0, "S", "Tutorials / capabilities overview / features overview / quick start / feedback / quotas docs")
theme("az-acr-ops", "A", 0, "M", "ACR import / copy image between registries")
theme("az-vm-guest", "B", 1, "L", "VM guest operations: extensions, update management (needs guest agent over SSH)", ["tunnel-tcp-relay"])
theme("az-unverified", "N", 0, "S", "Transient 'Not simulated' text without the data attribute; re-check")
theme("az-misc", "A", 0, "M", "Other service-specific section (see item note)")

# ---------------------------------------------------------------- rules: (cloud, service-regex, text-regex, theme)
R = []
def r(cloud, svc, text, th): R.append((cloud, re.compile(svc, re.I), re.compile(text, re.I | re.S), th))

# AWS
r("aws", "s3", r"Metadata configuration", "s3-metadata")
r("aws", "s3", r"Storage Lens", "s3-lens")
r("aws", "s3", r"CloudTrail data events", "cloudtrail-s3")
r("aws", "s3", r"Transfer acceleration", "s3-accel")
r("aws", "s3", r"Object Lock", "objlock-cond")
r("aws", "s3", r"vector-buckets", "s3-vectors")
r("aws", "s3", r"access-points-fsx", "s3-fsx")
r("aws", "s3", r"file-systems", "s3-files")
r("aws", "s3", r"Marketplace", "s3-market")
r("aws", "s3", r"Amazon S3|get-started", "editorial")
r("aws", "iam", r"CloudFront key", "iam-cf-keys")
r("aws", "iam", r"Role manager", "iam-role-mgr")
r("aws", "iam", r"Service access report", "iam-svc-access")
r("aws", "ec2", r"UltraServers", "ec2-ultra")
r("aws", "ec2", r"Service health", "service-health")
r("aws", "ec2", r"^ec2 \| Zones", "ec2-zones")
r("aws", "ec2", r"Instance alarms", "ec2-alarms")
r("aws", "ec2", r"EC2 cost", "billing-dash")
r("aws", "ec2", r"\| Events \|", "ec2-events")
r("aws", "ec2", r"All instances", "ec2-health-rollup")
r("aws", "ec2", r"\| Connect", "ec2-connect")
r("aws", "ec2", r"Create IAM profile", "ec2-iam-profile")
r("aws", "ec2", r"Spot Requests|purchasing", "ec2-spot")
r("aws", "ec2", r"Marketplace AMIs|Community AMIs|marketplace-community", "ec2-market-ami")
r("aws", "ec2", r"Fault tolerance", "ec2-volume-ft")
r("aws", "ec2", r"Shared with|ram-sharing", "ec2-ram")
r("aws", "ec2", r"Managed resources|Auto Scaling", "ec2-asg")
r("aws", "ec2", r"Compare security group", "ec2-compare-sg")
r("aws", "ec2", r"Image Builder", "ec2-imagebuilder")
r("aws", "ec2", r"Instance type finder", "ec2-type-finder")
r("aws", "ec2", r"Migrate a server", "ec2-migrate")
r("aws", "ec2", r"Recycle Bin", "ec2-recycle")
r("aws", "ec2", r"CPU and network metrics|CloudWatch metrics", "ec2-metrics")
r("aws", "apigateway", r"AgentCore", "lambda-agent")
r("aws", "cloudformation", r"Stack policy", "cfn-policy")
r("aws", "cloudformation", r"Rollback configuration", "cfn-rollback")
r("aws", "cloudformation", r"Notification options", "cfn-notify")
r("aws", "cloudformation", r"Git sync", "cfn-gitsync")
r("aws", "cloudformation", r"Trusted access", "cfn-stackset-org")
r("aws", "cloudformation", r"Canvas", "canvas")
r("aws", "cloudformation", r"Registry|Filter|Configuration \||Modules|Publisher|public-extensions|activated-extensions", "cfn-registry")
r("aws", "cloudformation", r"Spotlight|spotlight", "editorial")
r("aws", "cloudwatch", r"alarms/create", "unverified-text")
r("aws", "dynamodb", r"Backup", "ddb-backup")
r("aws", "dynamodb", r"Auto scaling", "ddb-autoscale")
r("aws", "dynamodb", r"Reserved capacity", "ddb-reserved")
r("aws", "dynamodb", r"Integrations", "zero-etl")
r("aws", "eventbridge", r"Builder mode", "canvas")
r("aws", "eventbridge", r"KMS key|Encryption", "eb-crypto")
r("aws", "eventbridge", r"CloudWatch Logs|\| Logs \|", "eb-logs")
r("aws", "eventbridge", r"Resource-based policy", "eb-policy")
r("aws", "eventbridge", r"Attaching an archive", "eb-archive-create")
r("aws", "eventbridge", r"Schema", "eb-schemas")
r("aws", "eventbridge", r"Partner", "partner-sources")
r("aws", "eventbridge", r"Learn|Quick starts", "editorial")
r("aws", "eventbridge", r"#/eventbridge", "unverified-text")
r("aws", "lambda", r"agent", "lambda-agent")
r("aws", "lambda", r"RDS databases", "lambda-rds-proxy")
r("aws", "lambda", r"CI/CD", "lambda-cicd")
r("aws", "lambda", r"Infrastructure Composer", "canvas")
r("aws", "secretsmanager", r"Rotation function", "sm-rotation")
r("aws", "rds", r"CPUUtilization|Database Insights", "rds-metrics")
r("aws", "rds", r"CloudWatch alarms", "rds-alarms")
r("aws", "rds", r"Data migrations", "rds-dms")
r("aws", "rds", r"IAM role association", "rds-iam-assoc")
r("aws", "rds", r"Restore from S3", "rds-restore-s3")
r("aws", "rds", r"capacity reservation", "rds-capres")
r("aws", "rds", r"zero-ETL", "zero-etl")
r("aws", "rds", r"service-health", "service-health")
r("aws", "rds", r"dashboard|service-quota", "rds-pages")
r("aws", "sns", r"Maximum message size|Time to Live", "sns-fixed")
r("aws", "sns", r"Integrations", "sns-integrations")
r("aws", "sns", r"Verification code", "sns-sms")
r("aws", "vpc", r"Service health|documentation|forums|issue reporting", "service-health")
r("aws", "vpc", r"encryption control|Cross-Region", "vpc-acct")
r("aws", "vpc", r"Network Manager|Integrations", "vpc-external")
r("aws", "vpc", r"multiple subnets", "vpc-multisubnet")
r("aws", "vpc", r"Lattice|Service networks", "vpc-lattice")
r("aws", "vpc", r"Container associations", "vpc-nfw-containers")
r("aws", "cost-explorer", r".", "billing-dash")
r("aws", r"\(home\)", r"Security Hub|No security data|#/", "security-hub")

# GCP
r("gcp", "compute", r"Google Cloud incidents", "gce-incidents")
r("gcp", "compute", r"Security risk", "gce-security-risk")
r("gcp", "compute", r"Compute Advisor|Recommender", "gce-recommender")
r("gcp", "compute", r"\| SSH|OS info", "gce-ssh")
r("gcp", "compute", r"schedules \||Instance schedules|Snapshot schedules|Enable snapshot|snapshot schedule", "gce-backup")
r("gcp", "compute", r"Import VM|Migrate to Virtual|Image import|Image export", "gce-import")
r("gcp", "compute", r"Additional storage|Back up your data|Instant snapshots|Async Replication|Consistency Groups", "gce-backup")
r("gcp", "compute", r"Load Balancer Health|network interface|Network endpoint", "gce-lb-nic")
r("gcp", "compute", r"Ops Agent", "gce-opsagent")
r("gcp", "compute", r"TPUs|Servers|Networks|VRFs|Volumes|NFS Shares|Procurements|Maintenance Events", "gce-hw")
r("gcp", "compute", r"Sole-tenant|Reservations|Storage Pools|Rollouts", "gce-sole")
r("gcp", "compute", r"Committed use|Capacity advisor", "gce-commit")
r("gcp", "compute", r"Patch|OS policies|extension policies|VM Manager", "gce-vm-manager")
r("gcp", "compute", r"Screenshot|Preview Features", "gce-misc-c")
r("gcp", "firestore", r"rules", "fs-rules")
r("gcp", "(run|functions)", r"Custom URLs|HTTP/2|Service Mesh", "run-net")
r("gcp", "(run|functions)", r"GPU", "run-gpu")
r("gcp", "(run|functions)", r"Cloud SQL connections", "run-sqlconn")
r("gcp", "(run|functions)", r"Binary Authorization", "run-kms")
r("gcp", "(run|functions)", r"Source|Connect repo|Continuous deployment", "run-source")
r("gcp", "(run|functions)", r"Eventarc|Trigger|event sources", "run-eventarc")
r("gcp", "(run|functions)", r"\| Select \|", "run-image-picker")
r("gcp", "(run|functions)", r"autoscaling|Ephemeral|Health checks|Volumes|Revision tags", "run-scaling")
r("gcp", "iam-admin", r"Simulating", "iam-simulate")
r("gcp", "iam-admin", r"Cloud Asset Inventory", "cai-query")
r("gcp", "iam-admin", r"OIDC|SAML|Attribute mapping|workforce", "iam-wif")
r("gcp", "iam-admin", r"Privacy", "org-folders")
r("gcp", "logs", r"Correlate", "logs-correlate")
r("gcp", "memorystore", r"Monitoring", "obs-trace")
r("gcp", "monitoring", r".", "obs-trace")
r("gcp", "networking", r"VLAN|Bring your own IP|Flow log", "net-hybrid")
r("gcp", "resource-manager", r"organization|folder", "org-folders")
r("gcp", "sql", r".", "sql-flags")
r("gcp", "storage", r"Rapid Cache|Inventory reports|enrichments", "gcs-insights")
r("gcp", "storage", r"Recommendations", "gcs-sec-insights")
r("gcp", "storage", r"turbo|Autoclass|CMEK|Per-object", "gcs-config")
r("gcp", "datastore", r".", "datastore")
r("gcp", "products", r"Marketplace", "gcp-market")
r("gcp", "security", r"HSM", "kms-hsm")
r("gcp", "security", r"Imported key", "kms-import")
r("gcp", "dashboard", r"Recommend", "gce-recommender")
r("gcp", "cloud-hub", r".", "cloud-hub")

# Azure (cross-cutting first)
r("azure", ".", r"Export template|Bicep template export|Terraform template export|ARM-to-(Bicep|Terraform)", "az-export-template")
r("azure", ".", r"Edit columns|Activity log (filters|: )|Export Activity Logs", "az-activity-cols")
r("azure", ".", r"Deny assignments|Classic administrators|My access", "az-rbac-extras")
r("azure", ".", r"Bulk tag|Assign tags|Bulk-assigning|Manage view|multi-selection|Favorite resources|blade layout|customization|role-assignments grid", "az-grid-tools")
r("azure", ".", r"Resource Graph", "az-resource-graph")
r("azure", ".", r"New support request|Support \+ Troubleshooting|support ticket", "az-support")
r("azure", ".", r"Diagnose and solve", "az-diagnose")
r("azure", ".", r"^[a-z]+ \| Tasks|\| Tasks \|", "az-tasks")
r("azure", ".", r"Defender", "az-defender")
r("azure", ".", r"Private endpoint|Custom virtual network|Custom VNet|network injection|Azure Firewall|\| Firewall|Bastion|DDoS|Front Door|Network manager|Virtual networks|Cluster networking", "az-private-net")
r("azure", ".", r"NSG flow", "az-nsg-flow")
r("azure", ".", r"Tutorials|capabilities overview|features overview|Features overview|Quick start|Feedback|Learn", "az-editorial")
r("azure", "cost", r"Payment", "az-payment")
r("azure", "cost", r"Invoices|\|", "az-billing")
r("azure", ".", r"Cost Management", "az-billing")
r("azure", ".", r"Marketplace|Partner solutions|Partner information", "az-marketplace")
r("azure", "monitor", r"Prometheus|Grafana|SCOM|Azure Local|datacollectionrules|Dashboards with", "az-monitor-products")
r("azure", ".", r"Diagnostic settings", "az-diag-settings")
r("azure", ".", r"Resource health|Advisor", "az-resource-health")
r("azure", ".", r"Insights|Alert|Metrics|metrics|Logs|Log Analytics|Workbooks|monitoring|Events \(preview\)|Availability / latency|Exceptions|Severity/category|Application Insights|Quick Insights|Additional alert|Notifications|charts", "az-monitor-blades")
r("azure", ".", r"User assigned managed|User-assigned managed|Managed identity|Server identity|identity", "az-managed-identity")
r("azure", ".", r"Customer-managed key|Encryption|encryption|CMK|key management|Rotate key", "az-cmk")
r("azure", ".", r"Event Grid subscriptions", "az-eventgrid-sub")
r("azure", ".", r"Azure Policy|Policy compliance", "az-policy")
r("azure", ".", r"Deployment Center|GitHub Actions|Flux GitOps|Automated deployments", "az-cicd")
r("azure", ".", r"Console|Advanced Tools|App Service Editor|Live log|Process explorer|Serial console|Extensions \|", "az-console-kudu")
r("azure", ".", r"Azure Backup|Backup|Recovery|Disaster recovery|Geo-replication|geo-replic|Restoring a|Restore a|Copy a database|Restore Backup", "az-backup-dr")
r("azure", ".", r"Resource visualizer", "az-visualizer")
r("azure", ".", r"Data migration|Storage Mover|Data Sync|Mirroring|Fabric|Power BI|Power Apps|Power Automate|Stream Analytics|Azure Function integration", "az-data-migration")
r("azure", ".", r"Azure Files|NFS|File shares|File service|Large file|File shares|Access protocols|Queue service|Table service|Other services", "az-files")
r("azure", ".", r"Search", "az-search")


# Azure per-service leftovers (after the cross-cutting rules above)
r("azure", "acr", r"Importing an image", "az-acr-ops")
r("azure", "aks", r"KEDA|extensions and applications", "az-aks-ops")
r("azure", "apim", r"Gateways|capacity gauge", "az-apim-ops")
r("azure", "appconfiguration", r"import", "az-appconfig-ops")
r("azure", "monitor", r"Not simulated in Vyomi", "az-unverified")
r("azure", "monitor", r"Open query|Resources", "az-monitor-blades")
r("azure", "apim", r"^apim \| Events", "az-eventgrid-sub")
r("azure", "apim", r"Monitor \+ secure", "az-monitor-blades")
r("azure", "containerapps", r"Networking", "az-private-net")
r("azure", "(appservices|functionapp)", r"Networking", "az-private-net")
r("azure", "(appservices|functionapp)", r".", "az-app-ops")
r("azure", "cosmos", r".", "az-cosmos-ops")
r("azure", "keyvaults", r".", "az-kv-ops")
r("azure", "monitor", r"changeanalysis|#/monitor", "az-monitor-blades")
r("azure", "resourcegroups", r".", "az-rg-ops")
r("azure", "sql", r"external SQL client", "az-diagnose")
r("azure", "sql", r"Integrations", "az-data-migration")
r("azure", "sql", r"Database watcher|Performance overview|Query Performance", "az-monitor-blades")
r("azure", "sql", r"Stored procedures|Maintenance|Connect", "az-sql-ops")
r("azure", "sql", r".", "az-sql-security")
r("azure", "storage", r"Tools \+ SDKs", "az-editorial")
r("azure", "storage", r"Deploy|Add to library", "az-export-template")
r("azure", "storage", r"^storage \| Events", "az-eventgrid-sub")
r("azure", "storage", r"Custom domain|Resource instances|route-specific|Metadata rewrite|Advanced", "az-storage-cfg")
r("azure", "storage", r".", "az-storage-protect")
r("azure", "subscriptions", r".", "az-subscriptions")
r("azure", "vms", r"Extensions|Updates", "az-vm-guest")
r("azure", "vms", r"Performance diagnostics", "az-monitor-blades")
r("azure", "vms", r".", "az-vm-ops")
r("azure", "vnets", r"Advertised", "az-private-net")
r("azure", "vnets", r"Other diagnostic", "az-diagnose")
r("azure", "vnets", r".", "az-vnet-ops")
r("azure", "dns", r".", "az-dns-ops")
r("azure", "(servicebus|eventgrid)", r".", "az-sb-ops")
r("azure", "entra", r".", "az-entra")
r("azure", "(cost)", r".", "az-billing")
r("azure", "(home)", r".", "az-grid-tools")
r("azure", ".", r".", "az-misc")

# ---------------------------------------------------------------- batches
# (id, cloud, title, themes, rationale) in queue order
B = []
def batch(i, cloud, title, themes, why=""):
    B.append(dict(id=i, cloud=cloud, title=title, themes=themes, why=why))

batch("AWS-01", "aws", "S3 buildable gaps: Metadata tables, Storage Lens metrics, S3 Vectors", ["s3-metadata", "s3-lens", "s3-vectors"], "S3 first (user complaint)")
batch("AWS-02", "aws", "S3 decided-backend + editorial: file systems, FSx access points, Transfer acceleration, Marketplace, Get started", ["s3-files", "s3-fsx", "s3-accel", "s3-market", "editorial:s3"], "")
batch("AWS-03", "aws", "EC2 dashboard + ops (zones, alarms, events, health rollup, EBS fault tolerance, IAM profile)", ["ec2-zones", "ec2-alarms", "ec2-events", "ec2-health-rollup", "ec2-volume-ft", "ec2-iam-profile"], "")
batch("AWS-04", "aws", "EC2 tools + purchasing (compare SG, type finder, Recycle Bin, Auto Scaling settings, Spot/capacity)", ["ec2-compare-sg", "ec2-type-finder", "ec2-recycle", "ec2-asg", "ec2-spot"], "")
batch("AWS-05", "aws", "EC2 reach-in + telemetry: Connect (SSH) and instance/volume metrics", ["ec2-connect", "ec2-metrics"], "decided families #1 and #3")
batch("AWS-06", "aws", "EC2 marketplace/builder/migration/RAM/cost", ["ec2-market-ami", "ec2-imagebuilder", "ec2-migrate", "ec2-ram", "billing-dash:ec2", "service-health:ec2"], "")
batch("AWS-07", "aws", "CloudTrail core + IAM gaps (service access report, CloudFront key pairs, Role manager) + S3 data events", ["cloudtrail-core", "cloudtrail-s3", "iam-svc-access", "iam-cf-keys", "iam-role-mgr"], "IAM third; CloudTrail core unblocks S3 and IAM")
batch("AWS-08", "aws", "EventBridge + CloudFormation + Secrets A items", ["eb-crypto", "eb-logs", "eb-policy", "eb-archive-create", "eb-schemas", "cfn-policy", "cfn-rollback", "cfn-notify", "sm-rotation"], "")
batch("AWS-09", "aws", "RDS + DynamoDB + Lambda + SNS + VPC A items", ["rds-alarms", "rds-iam-assoc", "rds-restore-s3", "rds-pages", "ddb-backup", "ddb-autoscale", "lambda-rds-proxy", "sns-integrations", "vpc-acct", "vpc-multisubnet"], "")
batch("AWS-10", "aws", "Visual canvas component (CFN Template Studio, EventBridge builder, Lambda Composer)", ["canvas"], "one shared UI component")
batch("AWS-11", "aws", "AWS observability + security + billing family: RDS metrics, Security Hub, Cost Explorer", ["rds-metrics", "security-hub", "billing-dash"], "families #3 #4 #9")
batch("AWS-12", "aws", "AWS networking + CI/CD family: VPC Lattice, Network Firewall containers, CloudFormation Git sync, Lambda CI/CD", ["vpc-lattice", "vpc-nfw-containers", "cfn-gitsync", "lambda-cicd"], "families #5 #2")
batch("AWS-13", "aws", "AWS data / directory / marketplace / local-LLM family: DMS, zero-ETL, SNS SMS, StackSets orgs, CFN registry, partner sources, AgentCore", ["rds-dms", "zero-etl", "sns-sms", "cfn-stackset-org", "cfn-registry", "partner-sources", "lambda-agent"], "families #6 #7 #8 #11")
batch("AWS-14", "aws", "AWS unbuildable / editorial / verify", ["ec2-ultra", "ddb-reserved", "rds-capres", "sns-fixed", "vpc-external", "service-health", "editorial", "objlock-cond", "unverified-text"], "class C and N")

batch("GCP-01", "gcp", "Compute A: recommender, schedules, backups/snapshots, NIC/NEG, sole-tenant/reservations", ["gce-recommender", "gce-schedules", "gce-backup", "gce-lb-nic", "gce-sole"], "")
batch("GCP-02", "gcp", "Run/Functions A: autoscaling, probes, volumes, SQL connections, BinAuthz/CMEK, Eventarc, image picker", ["run-scaling", "run-sqlconn", "run-kms", "run-eventarc", "run-image-picker"], "")
batch("GCP-03", "gcp", "Identity/data A: org-policy simulation, workload identity federation, Firestore rules, Logs correlate, Datastore, GCS config, SQL flags, KMS import", ["iam-simulate", "iam-wif", "fs-rules", "logs-correlate", "datastore", "gcs-config", "sql-flags", "kms-import"], "")
batch("GCP-04", "gcp", "GCP SSH + observability + security family: GCE SSH, VM Manager, Ops Agent, trace/scopes, security risk, storage security insights", ["gce-ssh", "gce-vm-manager", "gce-opsagent", "obs-trace", "gce-security-risk", "gcs-sec-insights"], "families #1 #3 #4")
batch("GCP-05", "gcp", "GCP networking + CI/CD family: VLAN/BYOIP/flow logs, Run networking, source deploy", ["net-hybrid", "run-net", "run-source"], "families #5 #2")
batch("GCP-06", "gcp", "GCP data / directory / marketplace family: VM import, Storage Insights, Asset Inventory queries, org/folders, Marketplace", ["gce-import", "gcs-insights", "cai-query", "org-folders", "gcp-market"], "families #6 #7 #8")
batch("GCP-07", "gcp", "GCP unbuildable", ["gce-incidents", "gce-hw", "gce-commit", "gce-misc-c", "run-gpu", "kms-hsm", "cloud-hub"], "class C")

batch("AZ-01", "azure", "Azure common blades A: export template, activity log, RBAC extras, grid tools, resource health/Advisor, diagnostic settings, visualizer", ["az-export-template", "az-activity-cols", "az-rbac-extras", "az-grid-tools", "az-resource-health", "az-diag-settings", "az-visualizer"], "cross-cutting kit components applied to every service")
batch("AZ-02", "azure", "Azure identity/crypto/policy A: managed identity, CMK, Event Grid subscriptions, Azure Policy, RG ops", ["az-managed-identity", "az-cmk", "az-eventgrid-sub", "az-policy", "az-rg-ops"], "")
batch("AZ-03", "azure", "Storage + SQL + Cosmos A", ["az-storage-protect", "az-storage-cfg", "az-sql-security", "az-sql-ops", "az-cosmos-ops", "az-backup-dr"], "")
batch("AZ-04", "azure", "Compute/containers A: VM ops, ACR import, AKS ops, App Service/Function App ops", ["az-vm-ops", "az-acr-ops", "az-aks-ops", "az-app-ops"], "")
batch("AZ-05", "azure", "Azure data-plane services A: APIM, App Configuration, Key Vault, Service Bus/Event Grid, DNS, VNet, Entra, other", ["az-apim-ops", "az-appconfig-ops", "az-kv-ops", "az-sb-ops", "az-dns-ops", "az-vnet-ops", "az-entra", "az-misc"], "")
batch("AZ-06", "azure", "Azure observability + security + support family: monitoring pipeline, Prometheus/Grafana/SCOM, Defender, support requests, Tasks", ["az-monitor-blades", "az-monitor-products", "az-defender", "az-support", "az-tasks"], "families #3 #4 #10 #2")
batch("AZ-07", "azure", "Azure networking + SSH + CI/CD family: private endpoints/Firewall/Bastion/DDoS, NSG flow logs, App Service console/Kudu, VM guest ops, Deployment Center", ["az-private-net", "az-nsg-flow", "az-console-kudu", "az-vm-guest", "az-cicd"], "families #5 #1 #2")
batch("AZ-08", "azure", "Azure data / directory / marketplace / billing family: Resource Graph, migration, Files, AI Search, subscriptions, Marketplace, Cost Management", ["az-resource-graph", "az-data-migration", "az-files", "az-search", "az-subscriptions", "az-marketplace", "az-billing"], "families #6 #7 #8 #9")
batch("AZ-09", "azure", "Azure unbuildable / editorial", ["az-diagnose", "az-payment", "az-editorial", "az-unverified"], "class C and N")

# ---------------------------------------------------------------- load
def norm_title(t):
    return re.sub(r"^[^|]{1,60} \| ", "", t or "").strip()

def load():
    items = {}
    for cloud in CLOUDS:
        for sub in ("offline", "nano"):
            for fn in (SCAN / f"{sub}-{cloud}.json", SCAN / "extras" / f"{sub}-{cloud}.json"):
                if not fn.exists():
                    continue
                d = json.load(open(fn))
                for f in d["findings"]:
                    title = norm_title(f["title"] if not f["feature"].startswith("(badge") else f["title"])
                    key = (cloud, f["service"], f["capabilityId"] or title.lower())
                    it = items.setdefault(key, dict(cloud=cloud, service=f["service"], capabilityId=f["capabilityId"], title=title,
                                                    note=f["note"], badge=f["badge"], routes=set(), contexts=set(), substrates=set(), textonly=f["feature"].startswith("(badge")))
                    it["routes"].update(f["routes"]); it["contexts"].update(f["contexts"]); it["substrates"].add(sub)
                    if not it["note"] and f["note"]:
                        it["note"] = f["note"]
    return items

def classify(it):
    text = f'{it["service"]} | {it["title"]} | {it["note"][:200]} | {" ".join(sorted(it["routes"])[:3])}'
    head = f'{it["service"]} | {it["title"]} | '
    for cloud, svc, rx, th in R:
        if cloud != it["cloud"] or not svc.search(it["service"]):
            continue
        if rx.search(head):          # title only: notes/routes are too loose (e.g. "metrics" inside a storage note)
            return th
    return None

def registry_counts():
    reg = {}
    for cloud in CLOUDS:
        d = ROOT / "core" / "capabilities" / cloud
        for f in sorted(d.glob("*.json")):
            for cid, e in json.load(open(f)).items():
                if cid.startswith("$"):
                    continue
                for sub in ("offline", "nano"):
                    lv = (e.get("level") or {}).get(sub) or (e.get("level") or {}).get("offline") or "not_simulated"
                    reg.setdefault((cloud, f.stem), collections.Counter())[f"{sub}:{lv}"] += 1
    return reg

def main():
    items, ok, unclassified = None, None, None
    items = load()
    for it in items.values():
        it["theme"] = classify(it) or "UNCLASSIFIED"
    unclassified = [i for i in items.values() if i["theme"] == "UNCLASSIFIED"]
    if unclassified:
        print("UNCLASSIFIED", len(unclassified))
        for it in unclassified:
            print(" ", it["cloud"], it["service"], "|", it["title"][:70], "|", sorted(it["routes"])[0], "|", it["note"][:60])
        sys.exit(1)

    # scanner meta (pages, limited, unreached) per cloud/substrate
    meta = {}
    for cloud in CLOUDS:
        for sub in ("offline", "nano"):
            fn = SCAN / f"{sub}-{cloud}.json"
            if fn.exists():
                d = json.load(open(fn))
                meta[(cloud, sub)] = dict(pages=len(d["visited"]), limited=d["limited"], unreached=d.get("unreachedPatterns", []), fixtureErrors=d.get("fixtureErrors", []), errors=d.get("errors", []))
    reg = registry_counts()

    # ---- batches
    theme_batch = {}
    for b in B:
        for t in b["themes"]:
            theme_batch.setdefault(t.split(":")[0], []).append((b["id"], t))
    def batch_for(it):
        cands = theme_batch.get(it["theme"], [])
        if not cands:
            raise SystemExit(f'theme {it["theme"]} not in any batch')
        for bid, t in cands:
            if ":" in t:
                if t.split(":")[1] == it["service"]:
                    return bid
            else:
                # prefer an unqualified entry unless a qualified one matches the service
                q = [x for x in cands if ":" in x[1] and x[1].split(":")[1] == it["service"]]
                return q[0][0] if q else bid
        return cands[0][0]
    for it in items.values():
        it["batch"] = batch_for(it)
        th = T[it["theme"]]
        it.update(cls=th["cls"], family=th["family"], size=th["size"], deps=th["deps"])

    # ---- summary tables
    sv = collections.defaultdict(lambda: collections.Counter())
    for it in items.values():
        sv[(it["cloud"], it["service"])][it["cls"]] += 1
    cloud_tot = collections.defaultdict(collections.Counter)
    for it in items.values():
        cloud_tot[it["cloud"]][it["cls"]] += 1; cloud_tot[it["cloud"]]["all"] += 1

    queue = []
    for b in B:
        its = [i for i in items.values() if i["batch"] == b["id"]]
        by_theme = collections.OrderedDict()
        for t in b["themes"]:
            tn = t.split(":")[0]
            by_theme.setdefault(tn, [])
        for i in sorted(its, key=lambda x: (x["service"], x["title"])):
            by_theme[i["theme"]].append(i)
        themes = [dict(theme=t, **T[t], count=len(v), items=[dict(service=i["service"], title=i["title"], capabilityId=i["capabilityId"], routes=sorted(i["routes"])[:4],
                  where=sorted(i["contexts"])[:4], substrates=sorted(i["substrates"]), note=i["note"][:300]) for i in v]) for t, v in by_theme.items() if v]
        queue.append(dict(id=b["id"], cloud=b["cloud"], title=b["title"], why=b["why"], classes=sorted({t["cls"] for t in themes}), themes=themes,
                          sections=sum(t["count"] for t in themes)))

    # ---- JSON
    js = dict(generated=datetime.date.today().isoformat(), scanner="consoles/tests/gap-scan.mjs", baseCommit=os.popen("git -C %s rev-parse --short HEAD" % ROOT).read().strip(),
              classes={"A": "buildable lightweight on both substrates", "B": "decided backend family (V4-GAP-BACKENDS-DECISIONS.md)", "C": "honestly unbuildable / editorial", "N": "not a gap (state-dependent / unverified text)"},
              totals={c: dict(cloud_tot[c]) for c in CLOUDS},
              perService=[dict(cloud=c, service=s, **dict(v), total=sum(v.values())) for (c, s), v in sorted(sv.items())],
              registry={f"{c}/{s}": dict(v) for (c, s), v in sorted(reg.items())},
              scan={f"{c}/{s}": dict(pages=m["pages"], unreachedPatterns=m["unreached"], fixtureErrors=[e[:160] for e in m["fixtureErrors"]]) for (c, s), m in meta.items()},
              batches=queue)
    (ROOT / "docs/architecture/v4.0/V4-GAP-QUEUE.json").write_text(json.dumps(js, indent=1))

    # ---- Markdown
    L = []
    w = L.append
    w("# v4 gap queue: every section still showing \"Not simulated in Vyomi\"")
    w("")
    w(f"Generated {js['generated']} from `consoles/tests/gap-scan.mjs` (Playwright, text only) at `{js['baseCommit']}`; regenerate the queue with `consoles/tests/gap-queue.py`.")
    w("The scanner visits every route of each console (route tables, `spec-map.json`, a link crawl of sidebars/rows/tabs), runs the per-service fixtures first so detail pages have a real resource, clicks every `[role=tab]` (nested too), steps through wizards (Next) and opens the main action buttons (modals/drawers, then cancels). A finding is a distinct `[data-vyomi-not-simulated]` section (or the NotSimulated panel); it is de-duplicated by cloud + service + capability id (or feature title). `Limited in Vyomi` / `Config only` are counted separately and are NOT in this queue.")
    w("")
    w("Classes: **A** buildable as a lightweight core on both substrates (offline python + Nano in-browser) | **B** belongs to a decided backend family (`V4-GAP-BACKENDS-DECISIONS.md`, family number in the label) | **C** honestly unbuildable (real-cloud-only, hardware, payments, editorial content) | **N** not a gap (state-dependent panel / unverified transient text). Size: S under a day, M a worker sitting, L several sittings or a new core.")
    w("")
    w("## 1. Totals: UI badges vs the capability registry")
    w("")
    w("| Cloud | Distinct Not-simulated sections in the UI | A | B | C | N | Registry `not_simulated` (offline / Nano) | Pages visited (offline / Nano) |")
    w("|---|---|---|---|---|---|---|---|")
    for c in CLOUDS:
        rn = lambda sub: sum(v.get(f"{sub}:not_simulated", 0) for (cc, s), v in reg.items() if cc == c)
        pg = lambda sub: meta.get((c, sub), {}).get("pages", "-")
        t = cloud_tot[c]
        w(f"| {c.upper()} | {t['all']} | {t['A']} | {t['B']} | {t['C']} | {t['N']} | {rn('offline')} / {rn('nano')} | {pg('offline')} / {pg('nano')} |")
    w("")
    w("The registry only counts features that someone registered in `core/capabilities/<cloud>/*.json`; the UI also carries many hand-declared `NotSimulated` panels (mostly Azure blades, GCP create-wizard sections and EC2/VPC pages) that have no registry entry, hence the difference. The queue below is built from the UI, which is what the user sees.")
    w("")
    w("### Per service")
    w("")
    w("| Cloud | Service | Not simulated (UI) | A | B | C | N | Registry not_simulated (off/Nano) | Registry limited+config_only (offline) |")
    w("|---|---|---|---|---|---|---|---|---|")
    keys = sorted({(c, s) for (c, s) in sv} | {k for k in reg}, key=lambda k: (CLOUDS.index(k[0]), {"s3": 0, "ec2": 1, "iam": 2}.get(k[1], 9), k[1]))
    for (c, s) in keys:
        v = sv.get((c, s), collections.Counter()); rg = reg.get((c, s), collections.Counter())
        lim = rg.get("offline:limited", 0) + rg.get("offline:config_only", 0)
        w(f"| {c} | {s} | {sum(v.values())} | {v['A']} | {v['B']} | {v['C']} | {v['N']} | {rg.get('offline:not_simulated',0)} / {rg.get('nano:not_simulated',0)} | {lim} |")
    w("")
    w("Limited / Config-only badges actually rendered (distinct capability ids seen in the UI, offline run): " + ", ".join(f"{c.upper()} {len(meta[(c,'offline')]['limited'])}" for c in CLOUDS if (c, 'offline') in meta) + ". Per-service lists are in the scan JSON (`limited`).")
    w("")
    w("## 2. S3, EC2 and IAM in full (the user's complaint)")
    w("")
    for svc in ("s3", "ec2", "iam"):
        its = sorted([i for i in items.values() if i["cloud"] == "aws" and i["service"] == svc], key=lambda x: (x["cls"], x["title"]))
        w(f"### AWS {svc.upper()} ({len(its)} sections)")
        w("")
        w("| Section | Where | Class | Size | Family / deps | Batch |")
        w("|---|---|---|---|---|---|")
        for i in its:
            route = min(i["routes"], key=lambda x: (len(x), x)) if i["routes"] else ""
            ctxs = sorted(i["contexts"], key=lambda c: (c != "page", not c.startswith("tab:"), c))
            where = route + (" [" + ctxs[0] + "]" if ctxs and ctxs[0] != "page" else "")
            fam = (i["family"] or "-") + ("; needs " + ", ".join(i["deps"]) if i["deps"] else "")
            w(f"| {i['title']} | `{where}` | {i['cls']} | {i['size']} | {fam} | {i['batch']} |")
        w("")
    w("Notes: (1) EC2 instance detail tabs could not be reached on the macOS offline run (`RunInstances` fails: \"AMI ... is not supported on darwin\"); they were scanned on **Nano**, where instances launch, so the two EC2 metrics tabs below appear only from the Nano run (they exist on offline too). (2) The S3 Object Lock legal-hold/retention panels render only for a bucket WITHOUT Object Lock; on a lock-enabled bucket they are real, so they are class N. (3) IAM shows only 3 sections: IAM is largely implemented after the IAM/Organizations sweeps.")
    w("")
    w("## 3. Work batches (in execution order)")
    w("")
    w("Order: AWS (S3, EC2, IAM first, then the rest), then GCP, then Azure; class A before B before C. One batch = about one worker sitting (a few related work packages; each package lists every section it closes).")
    w("")
    n = 0
    for b in queue:
        w(f"### {b['id']} {b['title']}")
        w("")
        w(f"Classes: {'/'.join(b['classes'])} | work packages: {len(b['themes'])} | sections closed: {b['sections']}" + (f" | {b['why']}" if b["why"] else ""))
        w("")
        for t in b["themes"]:
            fam = f" family: {t['family']};" if t["family"] else ""
            dep = f" needs: {', '.join(t['deps'])};" if t["deps"] else ""
            w(f"- [ ] **{t['label']}**: class {t['cls']},{fam}{dep} size {t['size']} ({t['count']} section{'s' if t['count']!=1 else ''})")
            shown = t["items"][:14]
            for i in shown:
                loc = min(i["routes"], key=lambda x: (len(x), x)) if i["routes"] else ""
                w(f"  - {i['service']}: {i['title'][:90]} (`{loc}`)" + (f" [{i['capabilityId']}]" if i["capabilityId"] else ""))
            if len(t["items"]) > len(shown):
                w(f"  - ... and {len(t['items'])-len(shown)} more (full list in V4-GAP-QUEUE.json)")
        w("")
    w("## 4. Substrate differences (offline vs Nano)")
    w("")
    for c in CLOUDS:
        only = collections.defaultdict(list)
        for i in items.values():
            if i["cloud"] == c and len(i["substrates"]) == 1:
                only[sorted(i["substrates"])[0]].append(f"{i['service']}: {i['title'][:50]}")
        w(f"- {c.upper()}: only on offline: {'; '.join(only['offline']) or 'none'}. Only on Nano: {'; '.join(only['nano']) or 'none'}.")
    w("")
    w("## 5. What the scanner could not reach")
    w("")
    for (c, s), m in sorted(meta.items()):
        w(f"- {c}/{s}: pages {m['pages']}; unreached parameterised routes: {', '.join(m['unreached']) or 'none'}; fixture errors: {len(m['fixtureErrors'])}" + (f" ({m['fixtureErrors'][0][:110]}...)" if m['fixtureErrors'] else ""))
    w("- Parameterised edit routes that need a second id (e.g. `/ec2/security-groups/:id/edit-outbound-rules`, `/vpc/vpcs/:id/edit-settings`) were visited separately with a real id (`EXTRA_ROUTES`) and show no Not-simulated sections; `/ec2/instances/:id` and `/ec2/create-snapshot/:volumeId` have no offline reach on macOS.")
    w("- Azure (2026-11-04 rescan): offline run with MAX_PAGES=4000 SHAPE_CAP=60 finished naturally at 1054 pages (no page cap hit); Nano was not re-scanned in that run.")
    w("- States that only appear after a real action (a running instance's serial console, a failed deployment, a scheduled maintenance event) are not covered; the scanner opens and cancels wizards/modals but does not submit them.")
    w("")
    (ROOT / "docs/architecture/v4.0/V4-GAP-QUEUE.md").write_text("\n".join(L) + "\n")
    print("batches", len(queue), "items", len(items), {c: dict(cloud_tot[c]) for c in CLOUDS})

if __name__ == "__main__":
    main()
