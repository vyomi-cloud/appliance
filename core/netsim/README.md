# netsim — one network engine for AWS VPC, GCP VPC and Azure VNet

Goal: an AWS / GCP / Azure networking expert gets the behaviour they expect, enforced on
real packets offline (Docker networks + nftables) and evaluated identically in Nano.
Enforced behaviour beats stored config.

```
vpc_core (EC2 Query)      ─┐
gcp_compute_core (+inst)  ─┼─ from_aws / from_gcp / from_azure ─► model.Topology ─┬─► evaluate.reach()   (Nano + every analyzer)
AzureArm.state (ARM)      ─┘        (read-only)                                   └─► enforce.compile_plan() → Docker nets + nft  (offline)
                                                                                         └─► flowlogs (nft per-flow counters → AWS/GCP/Azure records)
```

| file | what | runs in Pyodide |
|---|---|---|
| `model.py` | cloud-neutral topology: Network, Subnet, Interface, RuleSet (STATEFUL_ALLOW = SG, STATELESS_ORDERED = NACL, STATEFUL_PRIORITY = GCP firewall / Azure NSG), RouteTable, Gateway, Peering | yes |
| `evaluate.py` | `reach(topo, src, dst, proto, port, src_port=None) -> Verdict(reachable, code, reason, path, blocked_by, hops)` | yes |
| `from_aws.py` / `from_gcp.py` / `from_azure.py` | translators from the existing cores' state | yes |
| `enforce.py` | `compile_plan()` (pure) + `DockerEnforcer` (docker CLI: netd sidecar, networks, `nft -f`, DOCKER-USER) | compile yes, driver no |
| `flowlogs.py` | parse `nft -j list set` → AWS v2 / GCP / Azure NSG v2 records | yes |
| `docker/netd/Dockerfile` | alpine + nftables + iptables; `--network host --cap-add NET_ADMIN` | — |

## Tests

```
PYTHONPATH=. python3 tests/netsim/test_aws.py              # 14 — gotchas via the real EC2 Query API
PYTHONPATH=. python3 tests/netsim/test_gcp.py              # 10 — via the Compute REST cores (routers, peering)
PYTHONPATH=. python3 tests/netsim/test_azure.py            # 10 — via the ARM engine
PYTHONPATH=. python3 tests/netsim/test_enforce_compile.py  # 7  — compiler + flow-log format (no Docker)
PYTHONPATH=. python3 -m pytest -q tests/netsim/test_offline_wiring.py      # real server.py, no Docker
PYTHONPATH=. python3 tests/netsim/test_docker_e2e.py                        # REAL packets (core API → enforcer)
PYTHONPATH=. python3 -m pytest -q -s tests/netsim/test_docker_offline_e2e.py  # REAL packets (appliance API → wiring)
```
The Docker tests (skipped without Docker / nft-in-host-netns) create only `netsim-test-*`
containers/networks/images and `inet vyomi_netsim…` tables, and remove them. Every AWS BLOCK in the
core e2e is proven to be OUR drop (tuple present in the `rejects` set), every ALLOW is in `flows`.

## How enforcement works (offline)

* **One Docker bridge per subnet that has interfaces**, real CIDR, gateway `.1` (the VPC router
  address on all three clouds), `com.docker.network.bridge.enable_ip_masquerade=false`.
  Instances run with `--network <subnet net> --ip <model ip>` (`DockerEnforcer.run_args`).
* **One nft table per space**, `table inet vyomi_<space>`, applied as one `nft -f` transaction
  (`table …; delete table …; table … {…}`) → atomic and idempotent. Base chain at
  `filter - 10`; our `drop` is final, our `accept` only means "no objection" (Docker's
  iptables-nft chains still run).
* Pipeline: stateless subnet ACL chains on every packet crossing a subnet boundary (both
  directions — that is what makes "forgot the ephemeral range" fail for real) → `ct state
  established,related accept` (what makes SG / firewall / NSG stateful) → per-interface route
  chain (longest prefix → priority → user-over-system, compiled from the evaluator's own helpers)
  → per-interface egress layers (nic → subnet → network) → per-interface ingress layers.
* **Masquerade only** for interfaces whose internet path is real (public IP behind an IGW,
  AWS NAT gateway, GCP Cloud NAT, Azure NAT gateway / default outbound), toward non-model addresses.
* Docker drops traffic between different bridges (`DOCKER` chain); the netd inserts
  `DOCKER-USER -s/-d <enforced subnet> -j ACCEPT` (comment `vyomi_<space>`) so the decision is ours.
* Bridged (same-subnet) traffic is filtered too: Docker Desktop has `bridge-nf-call-iptables=1`,
  so intra-subnet SG / NSG decisions are enforced (proven by e2e case 4 / Azure case 4).
* **Flow logs**: every accepted packet updates the dynamic set `flows`, every drop updates
  `rejects` (5-tuple → packets/bytes). `DockerEnforcer.flow_sets()` reads them (carrying counters
  across re-applies, since the atomic redefine recreates the sets); `FlowLogCollector` turns
  deltas into AWS v2 records (implemented + tested), GCP VPC flow records and Azure NSG v2 tuples.

## Integration status (phase N1 — wired)

**One evaluator behind every analyzer** (offline and Nano run the same cores; `core/netsim` is vendored
to `wasm/core/netsim` via `CORE_PKGS` in `wasm/build_cores.py` and every Pyodide loader):

| cloud | API | where |
|---|---|---|
| AWS | `AnalyzeReachability` (simulator verb, console) + native Reachability Analyzer: `Create/Describe/DeleteNetworkInsightsPath`, `Start/Describe/DeleteNetworkInsightsAnalysis` (networkPathFound, forwardPathComponentSet, explanationSet) | `core/vpc_core.py` |
| GCP | networkmanagement v1 `projects/*/locations/global/connectivityTests` (create LRO, get, list, patch, delete, `:rerun`; steps + drop causes) | `core/gcp_compute_core.py` (routed as `gcp-compute`; offline route in `routes/gcp_firestore_compute_unified.py`) |
| Azure | `Microsoft.Network/networkWatchers/{nw}/ipFlowVerify` (access + ruleName) and `/nextHop` (type, IP, routeTableId) | `core/azure_arm_core.py` |

**Core gaps closed** (conformance: `tests/conformance/test_{vpc,gcp,azure}_netsim_core.py`): in-subnet
IP allocation (EC2 + Azure NICs), EC2 public-IP rules, ModifySubnetAttribute, SourceDestCheck,
CreateRoute Instance/ENI targets, `local` route on custom tables; GCP default route, firewall service
accounts, Cloud Router/NAT, network peering, default-subnetwork region; Azure routeTables / natGateways /
publicIPAddresses / applicationSecurityGroups / networkWatchers.

**Offline enforcement** (`core/netsim/wiring.py`, default OFF):

* `VYOMI_NETSIM_ENFORCE=1` (or `auto`: on when the Docker daemon is a Linux engine). Needs the netd
  image: `docker build -t vyomi/netd:1 docker/netd` (override with `VYOMI_NETD_IMAGE`). The appliance only
  needs the docker socket; DockerEnforcer starts `vyomi-netd` (`--network host --cap-add NET_ADMIN`).
* Knobs: `VYOMI_NETSIM_PREFIX` (network names, default `vyomi-net-`), `VYOMI_NETD_NAME`,
  `VYOMI_NETSIM_DEBOUNCE_MS` (250), `VYOMI_NETSIM_MGMT_CIDRS` (extra management sources; the appliance
  container's own IPs are always management), `VYOMI_NETSIM_INBOUND_DNAT=1` (1:1 DNAT to public IPs —
  opt-in because simulated public IPs sit in real cloud ranges and the rule would capture host traffic to
  that exact address), `VYOMI_NETSIM_SPACE_PREFIX` (table/network namespace, used by tests).
* `netsim_topology(space)` = vpc_core slot + the legacy EC2 instance records (offline RunInstances) +
  the GCP VPC/VM core stores + Azure ARM state. `schedule_apply()` runs after EC2 Query VPC mutations,
  EC2 launch/start/terminate and GCP compute mutations; `server._docker_instance_obj` takes the subnet
  bridge + model IP from `docker_attach()` (EC2, GCE). Every path is wrapped: a failure is recorded in
  `wiring.status()` and the instance falls back to the legacy network — launch never breaks.
* **Offline AWS VPC is now ONE engine:** the EC2 Query VPC actions (`CreateVpc`, `CreateSubnet`, SGs,
  route tables, IGWs, `DescribeSecurityGroups` …) are served by `core/vpc_core` instead of the pre-v4
  `vpc_state` handlers (which only covered half the actions, so NACLs/NAT/peering lived in a different
  store than their VPC). Pre-v4 readers of `vpc_state` get a mirror (`_engine: vpc_core`).
  `VYOMI_VPC_ENGINE=legacy` restores the old routing.
* **Upgrade adoption (no VPC is lost):** on first access in core mode, every pre-v4 `vpc_state` object of
  the space — VPCs (+tags, DHCP option set id), subnets (+route-table association), security groups (+all
  ingress/egress rules; a SG-referencing rule keeps only the SG, not the old 0.0.0.0/0 placeholder), route
  tables (+routes, main flag, associations) and internet gateways (+attachment) — is copied into the
  `vpc_core` slot with the SAME IDs (`vpc_core.adopt_legacy_slot`), once per space (`_adopted_legacy`
  marker, so an object deleted after the upgrade is never resurrected) and idempotent per object. The
  pre-v4 store never held EIPs, NAT gateways, NACLs, peering or ENIs (those were always vpc_core). EC2
  instances launched against legacy subnets/SGs keep their references; netsim gives them a stable
  in-subnet address (`netsim_ip`) for the enforced network. Caveat: the pre-v4 REST VPC console
  (`/api/aws/vpc…`) still writes `vpc_state`; objects it creates after adoption are not picked up.
* Docker published ports (the console's SSH port-publish path) are DNAT'd by Docker and pass as
  management traffic (`ct status dnat`), like a cloud console's own connect path.

Real-packet proof: `tests/netsim/test_docker_e2e.py` (core API → enforcer, 18 AWS + 7 GCP + 7 Azure
cases incl. inbound DNAT) and `tests/netsim/test_docker_offline_e2e.py` (the appliance's own HTTP API →
vpc_core → wiring → packets; the appliance's AnalyzeReachability answer == kernel outcome).

## Honest limits (as of phase N1)

* **Azure VMs are not packet-enforced offline**: the offline Azure VM runtime is LXD/Multipass, not the
  Docker compute backend. NSGs/UDRs are evaluated (Network Watcher) on both substrates.
* **Nano has no packets**: there, netsim is the behaviour (analyzer answers), not enforcement.
* **Overlapping CIDRs across spaces/VPCs** still can't coexist on one Docker host (one routing table,
  Docker refuses overlapping pools). Needs a network namespace per space (netd per netns / router
  container) — designed, not built. `ensure_networks` fails loudly; attach then falls back.
* **Inbound DNAT** is opt-in (see above) and only for interfaces whose egress is via an IGW with a public
  IP; egress still masquerades to the host address (the real internet would not route replies to a
  simulated EIP), so outbound flows show the host address, inbound flows see the real client.
* **Appliance routes** (instance/ENI/VirtualAppliance next hops) are evaluated (incl. source/dest check)
  but enforced as drop.
* NAT gateway ephemeral range: real NAT GW uses 1024-65535; we keep the client port (evaluator and
  enforcer agree with each other).
* Stateless ACLs are assumed to be AWS NACLs (boundary-only); Azure subnet NSGs are stateful and apply
  inside the subnet (handled).
* Flow logs: per-flow counters + AWS/GCP/Azure record rendering exist (`flowlogs.py`), but no
  `CreateFlowLogs` API / delivery to CloudWatch Logs, Cloud Logging or storage yet.
* No IPv6, no ICMP flow records, no TGW / VPN / VPC endpoints / PrivateLink / egress-only IGW behaviour
  (route targets become `unsupported` → drop + warning). Latency/AZ via `tc netem`: not attempted.
* Consoles: the Azure VNet subnet blade still shows its old "NAT gateway / Route table not modelled"
  placeholders and there is no console blade yet for Network Insights, Connectivity Tests or Network
  Watcher — the APIs are real, the UI pickers are a follow-up.
* Docker Desktop specifics verified: host netns == init netns, `bridge-nf-call-iptables=1`,
  iptables-nft backend, DOCKER-USER evaluated first. A native Linux host must have `br_netfilter`
  loaded for intra-subnet rules.
