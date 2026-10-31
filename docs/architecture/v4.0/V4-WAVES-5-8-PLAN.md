# v4 — depth waves 5–8 (plan, 2026-10-31)

Every one of the 50 v4 console services already has a real backend for its core operations.
These waves close the remaining gaps. Bar: every section is either REAL (on Nano and the
offline appliance) or honestly labelled with the concrete reason.

## Wave 5 — finish the gaps in the 50 services (running)
All 50 services: enforce every `config_only` setting, build every `not_simulated` section a
simulator can model, lift `limited` labels that are only missing engine coverage.

## Wave 6 — open-source backends, support, invoices, hybrid edge (approved)
- OSS backends as optional, lazily-started, pinned, no-telemetry containers (limited on Nano):
  Grafana, Prometheus, OpenTelemetry Collector + Jaeger, Trivy, CoreDNS, Caddy, BuildKit + Gitea;
  DuckDB (also DuckDB-wasm on Nano) for BigQuery/Redshift-lite destinations.
- Microsoft Defender for Cloud on Kubescape (+ native ARM rule engine); AKS Kubernetes object store.
- Existing-engine builds: VPN / Transit Gateway / Interconnect / NCC / Lattice / PrivateLink on
  core/netsim; AWS Organizations, GCP org hierarchy, Workforce Identity, Google Groups;
  Spot / RI / Savings Plans / Capacity / Dedicated Hosts; KMS Autokey; service health and
  Diagnose-and-solve detectors; metrics insights; log anomaly detection; SQL query insights;
  RDS read replicas + Multi-AZ; virtual MFA (TOTP).
- "New support request" (all 3 clouds) files a real ticket with Vyomi (portal SupportTicket).
- Invoices generated from simulated usage, clearly marked simulated. Payment methods: never.
- Hybrid edge networking on core/netsim: FRRouting customer edge (BGP for VPN, Direct Connect /
  ExpressRoute / Interconnect, TGW propagation, BYOIP / advertised prefixes / IP pools — doc
  ranges only, isolated namespaces); Outposts / Local Zones via a Local Gateway router namespace
  + an on-prem LAN network; S3 Transfer Acceleration via one lazy edge proxy + an honest latency
  profile.
- Proposed (pending approval): SCOM Managed Instance lightweight (scom_core + Samba AD DC +
  OpenTelemetry gateway on 5723) and Samba AD for Entra Domain Services / AWS Managed AD / GCP
  Managed AD.

## Wave 7 — consoles for services whose backend already exists
AWS: Kinesis Data Streams, Step Functions, Systems Manager (Parameter Store), EC2 Load
Balancing (ALB/NLB, target groups). GCP: Memorystore, Resource Manager. Azure: Container Apps,
App Configuration, DNS, AI services (Cognitive Services), Log Analytics workspaces.

## Wave 8 — new engines + consoles (top tier)
AWS: ECS, ECR, EKS, ElastiCache, Route 53, Cognito, SES. GCP: Cloud DNS, BigQuery (DuckDB).
Azure: Event Hubs, Cache for Redis, Application Insights, Managed Identities (revisit the
open expansion PRs #222/#225/#226/#227 against the v4 bar).

## Stays honestly labelled (no backend possible / by decision)
Payment methods; Marketplace / Community AMIs, CloudFormation public extensions, partner
solutions (Vyomi will publish its own SaaS-simulator marketplace); Data Box device; Azure Local
insights; DDoS protection; hardware MFA keys; GCP Access Transparency; generative AI assistants.

## After ship
One explainer video per simulated feature (how Vyomi simulates it, live demo from the shipped
consoles, what is limited on Nano vs offline).
