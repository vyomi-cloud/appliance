# v4 — backends for the "can't build" gaps (user decisions, 2026-11-02)

Every item below is built on BOTH substrates (Nano in-browser + offline appliance) unless noted.
Honest "limited on Nano" labels are allowed only where a container is genuinely required.

| # | Gap family | Decision |
|---|---|---|
| 1 | Real SSH / shell into compute (EC2 Connect, GCE SSH, Function App SSH/console) | Nano: SSH through the vyomi-tunnel (TCP relay, wave 6 "Tunnel TCP relay"); offline: real sshd in the Docker instance container |
| 2 | Source control + CI/CD (App Service / Function App Deployment Center, Kudu, Cloud Run continuous deployment, Tasks/Automation) | BuildKit + Gitea; PLUS the user can connect their own GitHub (PAT / OAuth) as the source |
| 3 | Observability (Managed Grafana/Prometheus, Trace explorer, App monitoring, scopes, SCOM, metrics pipelines) | ALL real, both substrates: Grafana, Prometheus, OTel Collector + Jaeger, SCOM design from wave 6 |
| 4 | Security scanning / threat detection (Defender alerts, Storage Defender, Storage security insights, Artifact vulnerability scanning) | Trivy + Kubescape (+ runtime detector for alerts), both substrates |
| 5 | Networking data plane (VPN, TGW, route propagation, traffic mirroring, Lattice, DNS Firewall, Network Firewall, Outposts/Local Zones, BYOIP, hybrid connectivity, flow logs, Bastion/Firewall/DDoS, Front Door/CDN, Transfer Acceleration) | FRR, WireGuard, CoreDNS, Caddy, nftables/Suricata on netsim, both substrates |
| 6 | Data / analytics / AI (Document AI enrichments, Rapid Cache, inventory reports, AI Search, Azure Files, data migration/Storage Mover, SNS mobile push, Resource Graph) | Lightweight equivalents for ALL (Samba for Files, DuckDB/graph engine for Resource Graph, embedded search, etc.) |
| 7 | Organizations / multi-account (AWS Organizations, GCP org + folders + move project, Azure management groups/partner, RAM sharing) | One lightweight directory service shared by all three clouds |
| 8 | Marketplaces / catalogs (Marketplace + community AMIs, CFN public extensions, partner solutions) | Vyomi's own SaaS-simulator spaces that users integrate into cloud development |
| 9 | Billing (invoices, spend, savings) | A creative cloud-native dashboard showing how much COST HAS BEEN SAVED by using Vyomi; invoices simulated and marked; payment methods never |
| 10 | Support tickets (every cloud) | Real tickets filed with Vyomi (portal SupportTicket; localhost until the user says deploy) |
| 11 | Bedrock / Vertex AI / Azure AI Foundry, AgentCore | Lightweight local LLM (llama.cpp offline) / WebLLM (Nano) so users build zero-cost agents; shares the Copilot (wave 9) runtime |

Order of attack (smallest, no-container first): 7 → 10 → 9 → 1 (offline sshd) → 3 → 4 → 5 → 2 → 6 → 8 → 11; Nano variants follow each.
