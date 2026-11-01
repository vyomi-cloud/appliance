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
- SCOM Managed Instance, lightweight (approved): `scom_core` (ARM resource + wizard with real
  dependency checks, YAML management packs, health rollup, alerts, OperationsManager/DW tables in
  the user's Azure SQL db — Nano + offline); Samba AD DC + CoreDNS for real domain join (the same
  backend makes Entra Domain Services, AWS Managed Microsoft AD and GCP Managed AD real); an
  OpenTelemetry Collector gateway on 5723 with mTLS and agents in on-prem LAN containers over the
  hybrid network. No Microsoft SCOM / SQL Server / Windows is shipped; management packs, the
  Operations console and the Windows agent stay honestly labelled.
- (Vyomi Copilot moved to wave 9 — see below.)

- **Tunnel TCP relay (shared infra, approved 2026-11-01).** vyomi-tunnel 1.1 adds raw TCP
  listeners (127.0.0.1 only, opened on request from the tab), relaying connection
  open/data/close frames over the existing WebSocket to the Nano tab; offline hosts the same
  protocol servers in-process on real ports. First protocol: the **DAX wire protocol** (CBOR,
  handshake/auth, `endpoints` discovery → the tunnel address, item/query/batch/transact) on
  dax_core's cache, so unmodified DAX SDK clients work on Nano and offline. Local tunnel only
  (the Cloudflare relay cannot accept inbound TCP). Follow-ups on the same relay: Postgres
  wire (RDS/Cloud SQL → PGlite), Redis RESP (ElastiCache/Memorystore/Azure Cache), AMQP
  (Service Bus), Kafka (Event Hubs). Publishing tunnel 1.1 needs the user's npm OTP.

## Wave 7 — consoles for services whose backend already exists
AWS: Kinesis Data Streams, Step Functions, Systems Manager (Parameter Store), EC2 Load
Balancing (ALB/NLB, target groups). GCP: Memorystore, Resource Manager. Azure: Container Apps,
App Configuration, DNS, AI services (Cognitive Services), Log Analytics workspaces.

## Wave 8 — new engines + consoles (top tier)
AWS: ECS, ECR, EKS, ElastiCache, Route 53, Cognito, SES. GCP: Cloud DNS, BigQuery (DuckDB).
Azure: Event Hubs, Cache for Redis, Application Insights, Managed Identities (revisit the
open expansion PRs #222/#225/#226/#227 against the v4 bar).

## Wave 9 — Vyomi Copilot (local LLM, optional download), after waves 5–8
Spike result: viable only with app-orchestrated grounding (BM25 over the capability registry,
ui-spec, api.js and curated docs; the app decides read-only tool calls; "is it simulated?"
answered from the registry; generated CLI/Terraform/Bicep validated before display). Models
(Apache-2.0): appliance Granite-4.0-1B or Qwen3.5-2B via llama.cpp (~2.4–2.8 GB RSS, opt-in
`vyomi copilot enable`); Nano Qwen3.5-2B via WebLLM in a Web Worker, WebGPU only, self-hosted
weights (~1.1 GB). ~3 weeks. Scheduled after backend integration so the grounding corpus is stable.

## Stays honestly labelled (no backend possible / by decision)
Payment methods; Marketplace / Community AMIs, CloudFormation public extensions, partner
solutions (Vyomi will publish its own SaaS-simulator marketplace); Data Box device; Azure Local
insights; DDoS protection; hardware MFA keys; GCP Access Transparency; generative AI assistants.

## After ship
One explainer video per simulated feature (how Vyomi simulates it, live demo from the shipped
consoles, what is limited on Nano vs offline).
