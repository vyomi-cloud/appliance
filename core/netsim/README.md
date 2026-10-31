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
PYTHONPATH=. python3 tests/netsim/test_gcp.py              # 8  — via the Compute REST cores
PYTHONPATH=. python3 tests/netsim/test_azure.py            # 10 — via the ARM engine
PYTHONPATH=. python3 tests/netsim/test_enforce_compile.py  # 7  — compiler + flow-log format (no Docker)
PYTHONPATH=. python3 tests/netsim/test_docker_e2e.py       # REAL packets: evaluator verdict == kernel outcome
```
The e2e test (skipped without Docker / nft-in-host-netns) creates only `netsim-test-*`
containers/networks/images and the table `inet vyomi_netsimtest|netsimgcp|netsimaz`, and removes them.
Last run (Docker 29.4.3, Docker Desktop LinuxKit 6.12): 16/16 AWS cases + 7 GCP + 7 Azure cases,
evaluator == packets on every one; every AWS BLOCK is proven to be OUR drop (tuple present in the
`rejects` set), every ALLOW is in `flows`.

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

## Integration plan (NOT wired yet — deliberate)

1. **One topology per space.** Add `netsim_topology(space)` in the appliance that merges
   `from_aws(vpc store) + from_gcp(net store, inst store, project) + from_azure(arm.state)`
   for that space (a space is one cloud today, so usually just one translator).
2. **Analyzers → `evaluate.reach`** (Nano and offline, same code):
   * `vpc_core.analyze_reachability` / `_analyze_reachability_action` → call `from_aws(store)` +
     `reach()`, map `Verdict.hops` to Reachability Analyzer `explanations` / `forwardPathComponents`.
   * GCP Connectivity Tests (`networkmanagement`), Azure Network Watcher `ipFlowVerify` / `nextHop`
     → same, mapping `code` → GCP `drop cause` / Azure `access`+`ruleName`, `route_lookup()` → nextHop.
   * Nano = evaluator only: no packets, but every analyzer/console answer comes from `reach()`.
3. **Offline enforcement hook.** After any mutating networking call (CreateRoute,
   Authorize/RevokeSecurityGroup*, CreateNetworkAclEntry, Associate*, firewall insert/patch/delete,
   ARM PUT/DELETE on Microsoft.Network/*) and after instance launch/terminate, debounce ~200 ms and
   `DockerEnforcer(space).apply(netsim_topology(space))`.
4. **DockerComputeBackend gets network + ip** (`core/compute/backend.py` already has
   `Instance.network` / `Instance.ip_address`). In `server.py` EC2 launch (`_DOCKER_COMPUTE`,
   ~line 7780) and the GCP/Azure VM launch paths: `apply()` first, then
   `Instance(network=…, ip_address=…)` from `DockerEnforcer.run_args(topo, iface_id)`.
   The appliance container needs only the docker socket (the netd does the privileged part).
   Management access (console SSH/exec bridge) is passed as `mgmt_cidrs` — a documented exception.
5. **Core gaps to fix before enforcing** (found while building the translators):
   * vpc_core: instance `private_ip` is a pseudo IP (`10.0.1.x`) **outside its subnet** → allocate from
     the subnet (.4+) and honour `PrivateIpAddress`; `public_ip` is set on every instance → set only
     with `MapPublicIpOnLaunch` / `AssociatePublicIpAddress` / EIP (the translator already applies the
     real rule); no `ModifySubnetAttribute(MapPublicIpOnLaunch)`, no `ModifyInstanceAttribute
     SourceDestCheck`, `CreateRoute` lacks `InstanceId` / `NetworkInterfaceId` targets; custom route
     tables are created without the `local` route (translator adds it); no flow-log resources.
   * gcp_compute_core: the auto-created `default-route` (0/0 → default-internet-gateway) is not
     materialised (translator adds it unless `_defaultRouteDeleted`); no Cloud Router / Cloud NAT,
     no VPC peering resources (translator takes `cloud_nats=` / `peerings=` until they exist);
     firewall `targetServiceAccounts` / `sourceServiceAccounts` are not stored by `_insert_firewall`.
   * gcp_compute_instances_core: default nic subnetwork path uses the **zone** where the region belongs.
   * azure_arm_data catalog: `routeTables`, `natGateways`, `publicIPAddresses`,
     `applicationSecurityGroups` are `ResourceTypeNotSupported` → add them (translator already reads
     them in ARM shape); peering `peeringState` should flip to Connected only when both links exist
     (translator already enforces that).
6. **Capability levels** (do not change until 1–4 are wired + e2e green in CI):
   * can honestly be `full` offline once wired: `aws.vpc.security-groups`, `aws.vpc.network-acls`,
     `aws.vpc.route-tables`, `aws.vpc.internet-gateways`, `aws.vpc.nat-gateways` (now limited),
     `aws.vpc.peering-connections` (now limited), `aws.vpc.flow-logs` (now not_simulated → limited:
     AWS format only, no S3/CloudWatch delivery yet), `gcp.networking.firewall.crud` / `route.crud`
     (behaviour, not just CRUD), `gcp.networking.peering` (not_simulated → limited until the core
     has peering resources), `azure.nsgs.security_rules`, `azure.nsgs.associations` (limited → full),
     `azure.vnets.peerings`.
   * Nano: same entries become "evaluated" behaviour (analyzer answers), not packets — keep the
     Nano level honest about that (no real traffic between in-browser VMs).
   * NOTE: several of these already read `full` today while nothing is enforced — they describe
     stored config. Re-label or wire; don't leave both.

## Honest limits (as of this commit)

* **Overlapping CIDRs across spaces/VPCs** can't coexist on one Docker host (Docker refuses
  overlapping pools; one host routing table). Two spaces both using `10.0.0.0/16` need a per-space
  network namespace (netd per netns, or a router container per space) — design, not built.
  The AWS default VPC `172.31.0.0/16` sits inside Docker's default address pool: bridges are created
  only for subnets with interfaces, and `ensure_networks` fails loudly on a pool overlap.
* **Inbound from the internet to a public IP** is evaluated (`reach("198.51.100.7", eni)`) but not
  enforced: there is no DNAT from a host-side "public IP" yet, so the enforcer drops all new inbound
  from outside the space (correct for private instances, too strict for public ones).
* **Appliance routes** (AWS instance/ENI target, GCP nextHopInstance/Ip, Azure VirtualAppliance) are
  evaluated (incl. source/dest check) but enforced as drop (needs policy routing into the container).
* IGW/NAT source address is the host's masquerade address on the egress interface, not the EIP /
  NAT public IP (the internet sees "a NATed address", which is the behaviour that matters).
* NAT gateway ephemeral range: real NAT GW uses 1024-65535 toward the internet; we keep the client's
  port (Linux 32768-60999), so a NAT-subnet NACL that only allows 1024-32767 back would behave
  differently. Evaluator and enforcer agree with each other (both use the client port).
* Stateless ACLs are assumed to be AWS NACLs (boundary-only). Azure subnet NSGs are stateful and
  apply inside the subnet (handled).
* No IPv6, no ICMP flow-log records (tcp/udp only in the flow sets), no TGW / VPN / VPC endpoints /
  PrivateLink / egress-only IGW behaviour (route targets become `unsupported` → drop + warning).
* Latency / AZ / packet loss via `tc netem` per bridge: not attempted. Hook point would be the
  netd (`tc qdisc add dev vn<hash> root netem delay …`) keyed by subnet zone pairs.
* Docker Desktop specifics verified: host netns == init netns (nft `log` reaches dmesg),
  `bridge-nf-call-iptables=1`, iptables-nft backend, DOCKER-USER evaluated first. A native Linux
  Docker host should behave the same but must have `br_netfilter` loaded for intra-subnet rules.
