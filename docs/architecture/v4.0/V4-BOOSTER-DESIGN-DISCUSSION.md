# Booster pack — design decisions (2026-11-06; design only, NOTHING BUILT)

## Part A — Decisions

### 1. What the booster is
- The **booster = the current Pro/Max offline appliance**, licensed on Pro or Max, **with no console of its own**. Not a new codebase.
  The v4 consoles already build for both substrates (`SUBSTRATE=offline|nano`) and speak the same `/_wire` APIs.
- **Nano UI is the only UI, in every case.** The appliance serves no UI on any tier. UI always loads from vyomi.cloud over HTTPS.
- A headless appliance still needs non-UI paths: licence activation/status, pairing with a Nano tab (code/link, CLI-printed),
  health, `vyomi update`, the 70% cap setting. Provide via the `vyomi` CLI + a tiny status endpoint.
- Booster scope is **compute + AI** (VMs, container services, Kubernetes, functions, App Service, Batch; Ollama behind
  Bedrock/Vertex/Azure AI). Non-compute services still run in the browser for browser-homed spaces.

### 2. Tiers
| | Free | Pro | Max |
|---|---|---|---|
| Clouds | all 3, limited | 1 cloud, full | all 3, full |
| Home | browser only | browser, or booster if licensed | browser, or booster if licensed |
| Strategic features | disabled, "Pro/Max" pill | on | on |
| In-browser VM | tiny base VM | + **Python + git VM** | + **Python + git VM** |
| Booster | never | optional add-on | optional add-on |
- Pills are generated from a `tier` field on each capability-registry entry (`core/capabilities/<cloud>/<svc>.json`); a
  separate "Booster" pill marks booster-only features (shown to Free as an upsell).
- Python + git VM image: browser-side (v86), served from the portal to entitled accounts only (real gate), lazy-loaded + cached in OPFS.
  Free-tier VM egress needs the allow-listed proxy; git hosts to be decided.
- Browser-side gating is soft (code ships); real enforcement applies to booster-served features and the VM image.

### 3. Per-space home
- At space creation a booster-licensed user picks **Home: this browser | booster (name)**. Fixed at creation; no live migration
  (explicit export/import only; must be lossless).
- A booster-homed space is accessible **only while the Nano UI can reach the booster**; unreachable => UI blocks actions
  (read-only/locked, "datacenter unreachable" banner, auto-retry; reconcile + label-based orphan cleanup on reconnect).
- Browser-homed spaces are never affected by a booster outage. Space list shows both with a home badge.
- Booster-homed spaces run their services on the booster (survive tab/browser closure; needed by VPN and public TTL mode).
- VPN is booster-to-booster only; no cross-home networking.

### 4. Resource cap
- Booster uses at most **70% of host resources**: RAM hard budget (instances + loaded AI models), CPU shared/overcommittable,
  disk quota; on Docker Desktop = min(70% host, Docker VM limit). Beyond it the Nano UI cannot create more compute; calls fail
  with the clouds\' real capacity errors (InsufficientInstanceCapacity / ZONE_RESOURCE_POOL_EXHAUSTED / AllocationFailed) and the
  Capacity advisor reports the real host budget. Open: AI/VM split, host-pressure refusal rule, usage meter, overhead reserve.

### 5. Connection (tab always dials the booster)
- Universal path = **outbound relay**: the booster dials out to a Cloudflare tunnel; the tab connects over HTTPS/WSS. Works on
  Safari/Chrome/Firefox/managed browsers/other machines. Needs internet on the booster host; traffic traverses Cloudflare
  (verify TLS termination at the booster before claiming data stays local).
- Optimisation + offline path: per-booster HTTPS hostname **`<id>.local.vyomi.cloud`** (wildcard A -> 127.0.0.1; per-booster
  A record to the LAN IP reported by the booster) with a real CA cert, so Safari sees plain HTTPS. Rule: try local hostname first,
  fall back to the relay, else "unreachable" (block). Chrome still shows its one-time local-network permission; DNS-rebinding
  filters can break the hostname => relay fallback.
- Certificates: free ACME (Let\'s Encrypt; Google Trust Services/ZeroSSL as backup), DNS-01 via the portal. **Key never leaves the
  booster** (booster makes key+CSR, portal completes the challenge). Never a shared wildcard key. Rate limits: request
  **Public Suffix List** entry for `local.vyomi.cloud` early (takes weeks) + limit increase; verify current limits before committing.
  Unverified: where vyomi.cloud DNS is hosted; Safari accepting a trusted cert on a loopback-resolving name.
- Open: one Vyomi-managed Cloudflare account with named tunnels `<id>.booster.vyomi.cloud` issued by the portal (recommended) vs BYO;
  `vyomi-tunnel` stays for exposing services, bundled in the booster (assumed separate from the Nano<->booster relay).
- Auth: short-lived token bound to account + booster id + entitlement; origin allow-list, Host check, rate limiting.

### 6. Egress
- The booster is the private cloud. Egress follows the **simulated VPC**: no IGW/NAT/route => no way out; with one => the host\'s
  real internet (so Maven/npm/Packagist/Go proxy/git work). No registry mirror (decided). Default-block the host\'s private ranges
  (RFC1918, link-local, Docker bridge) from simulated instances; opt-out is a deliberate step.
- Topology is decided in the Nano UI (desired state); the booster is a reconciler (Docker networks + nftables sidecar via netsim).

### 7. Languages
- Booster adds Java/Node/PHP/Go etc. (function runtimes, app hosting, instance toolchains). One signed base image per language+version,
  pulled on first use; versions mirror each cloud\'s real runtime lists. Free/browser stays Python-centric.

### 8. Tamper resistance + IAM
- Achievable goal = hard, detectable bypass, not impossible (user is root on own host). Signed images/WasmEdge modules only (matches
  "no local hotfix overlay"); private control socket owned by the signed control process; dropped caps, no host mounts; short-lived
  authenticated control channel with signed entitlement; limits enforced on the booster; periodic portal check-in; self-integrity
  check and flagging of containers it did not create. Open: encrypted-at-rest keys/weights (skip initially), bundled engine vs
  user Docker (start with user Docker + signed images).
- **IAM/RBAC for compute access**: layer 1 = Vyomi account/org roles (who may attach/open a booster space); layer 2 = the simulated
  cloud\'s IAM (AWS IAM / GCP IAM / Azure RBAC) evaluated on the booster at every compute entry point (lifecycle, SSH/Connect/OS Login/
  SSM, exec, serial console, ports, function/model invoke, network changes). Real error codes; decisions land in the simulated audit
  log; short-lived credentials/SSH certs issued only after a policy check; no standing keys or raw `docker exec`. Shared/cohort mode maps
  principals to tenants. Open: identity source (recommended: signed-in user = space owner role, space defines its own principals);
  default (owner full access, deny others).

### 9. Trial, lock and reminders
- A Free account that downloads a Pro/Max appliance gets the **14-day trial** (existing per-account, portal-signed reverse trial).
- **Day 15: booster-homed spaces lock** (UI cannot open or act; no new compute/AI). Previously expiry dropped to Free; there is no Free
  offline tier now. Browser-homed spaces keep working. Data is kept and unlocks on a valid Pro/Max entitlement.
- **No grace period.** **Reminders in the Nano UI start 7 days before expiry** (days-left banner, escalating, then lock screen).
- Paid plans: portal issues entitlements for the full billing period and renews at every check-in so online users never lock;
  the 7-day reminder doubles as "connect to renew". Trial stays a hard 14 days. Account-level, not per machine; monotonic-clock
  record to resist clock rollback.
- Open: export while locked (assumed fully closed).

### 10. Phasing (smallest booster first)
1. Nano<->appliance connection (relay first), per-space home, unreachable block, tier flag in licence, 70% cap, console removal on Pro/Max.
2. Signed images + compute IAM (lifecycle, SSH). Docker/WasmEdge compute + Ollama behind the 3 AI services.
3. Extra languages, local HTTPS hostname/certs, Python+git VM image, pills from the registry.
4. Separate tracks, not tied to the booster release: VPN between simulators, TTL public mode, tunnel bundling polish, hardening extras.

### 11. Free-tier gating (first cut — user to mark changes)
Principle: Free completes a real learning loop (create/call/see/fix); Pro/Max sell depth, scale, persistence and realism.
- **Never gated on Free:** CRUD on core services of all 3 clouds; SDK/CLI/Terraform via the tunnel (native wire); IAM/RBAC basics with real
  error codes; tiny base VM (SSH, few ports); databases/object storage at small limits; in-browser WebLLM behind Bedrock/Vertex/Azure AI;
  audit-log views and Service status; explainer videos; marketplace browsing.
- **Gated (Pro/Max pill):** Python+git VM, larger shapes and >couple of concurrent VMs; Capacity advisor, quota/stockout simulation, pool
  resizing; peering/transit/hybrid links (VPN gateway, Interconnect, ExpressRoute) and the nftables network simulator (core VPC/subnets stay
  free); backups with restore jobs, scheduled/long-running jobs, autoscaling; Defender/Kubescape posture, IAM policy simulator, org-wide
  policies; cost-meter drill-down and simulated invoices; space export/import and snapshots beyond the latest; space-size/resource-count
  limits above a modest cap; shared/cohort spaces and extra principals; container-backed OSS backends.
- **Booster-only (upsell pill for Free):** powerful compute, extra languages, Ollama models, VPN, public TTL mode.
- Guard: review the gated list against quickstarts and capability-registry `tests` so no tutorial dead-ends on a pill.

### 12. Decisions added later on 2026-11-06
- **Trial includes the booster:** booster = Pro/Max, so trial users experience it (14 days, then lock — §9).
- **No export while locked.** Locked = fully closed; data kept, unlocks on a valid entitlement.
- **One Vyomi-managed Cloudflare account**, a named tunnel per booster issued by the portal.
- **IAM identity:** the space defines its own principals (signed-in user = owner role; default deny others).
- **Shared/cohort mode moves to cloud spaces:** a shared Codespaces booster hosts one booster-homed space per member; by the time a member's
  Nano opens, their space already exists (3 people sharing => 3 spaces ready). No shared mutable space; isolation is per-space IAM/tenant.
- **VPN: only booster-homed spaces are eligible to join a VPN** (booster-to-booster). Clearly labelled in the UI: topology view shows the VPN and its peers; browser-homed spaces show the option as unavailable with a 'Booster' label. Cloud-spaces confirmed: one booster-homed space per member on a shared host.
- **Public exposure: to be planned** (see below).

### Public exposure (TTL-driven) — planning outline
Goal: a booster-homed space's chosen endpoints are reachable from the public internet for a limited time.
- Exposure is explicit and per endpoint (instance public IP + open SG, load balancer, API gateway, public bucket) — nothing is public by default.
- Reached via Cloudflare ingress on `*.sim.vyomi.cloud` through the same managed account; HTTP(S) first, raw TCP later.
- TTL set by the user, capped per tier; auto-closes at expiry, on lock, or on booster loss; manual kill switch; always shown in the UI with a countdown.
- Abuse controls: Cloudflare WAF + rate limits, bandwidth cap, verified account only, interstitial/banner for phishing risk, portal-side takedown,
  logging of exposures. Egress remains the simulated VPC rules.
- Open: tier limits (TTL/endpoints/bandwidth), hostname scheme, default auth (public vs token vs IAM), ToS/legal, who pays for bandwidth.

- **Pro cloud switching:** allowed at renewal time only.
- **Lite is dissolved into Free;** remove from the portal (user: already being removed). No separate Lite tier remains.
- **`vyomi-tunnel` is not redesigned.** It stays what it is: tab dials `ws://127.0.0.1:8090/register` and local SDK/CLI calls are forwarded to the
  tab, serving **browser-homed** spaces. Booster-homed spaces need no tunnel for local tools (they hit the booster's own port directly).
  Two genuinely new paths are separate from it: (1) Nano tab -> booster connection (local HTTPS hostname, Cloudflare relay fallback) and
  (2) public ingress (internet -> exposed booster endpoint). The booster bundles the Cloudflare connector for (1) and (2); the user sees one
  "tunnel" concept in the UI. Known gaps in vyomi-tunnel unchanged (no auth, HTTP only, TCP relay planned 1.1).

### 13. VPN design (simple), cap split, cert test, free-VM git hosts
- **VPN**: no corporate VPN concept. Each VPN gets a unique ID created from the Nano UI; other users join by entering the ID (+ join token /
  owner approval) in their own Nano UI. Only booster-homed spaces can be members. Control plane = portal (membership, ID, addressing, keys);
  data plane = booster-to-booster WireGuard mesh, so instances in different spaces can ping each other. Browsers are only the UI.
  Needs: non-overlapping VPC CIDRs enforced or NAT at join, NAT traversal (STUN/hole-punch) with a WSS/TCP relay fallback for CGNAT/UDP-blocked
  networks, key rotation, leave/kick, and a UI that shows members, status and latency.
- **70% cap split: 50% compute / 50% AI** (of the capped budget). Open: whether idle share is borrowable by the other side.
- **Certificate test required**: Safari (real, on macOS) must trust a publicly-issued cert on `<id>.local.vyomi.cloud` resolving to 127.0.0.1
  and make a fetch + WSS from an https://vyomi.cloud page, plus Chrome/Firefox. Needs DNS control of the zone + one real ACME issuance.
- **Free-VM egress allow-list (proposal, to refine)**: github.com, gitlab.com, bitbucket.org, codeberg.org (HTTPS git); pypi.org,
  files.pythonhosted.org; raw.githubusercontent.com, objects.githubusercontent.com. No SSH-protocol git (proxy is HTTP(S)); everything else denied.

### 14. VPN design v2 — cloud-native facades over a neutral WireGuard link (supersedes the VPN bullet in §13)
VPN is a simulated cloud service per cloud (AWS Site-to-Site VPN/CGW/VGW; GCP HA VPN + external VPN gateway + tunnel; Azure VNet gateway +
local network gateway + connection), backed by a WireGuard data plane between booster-homed spaces. Cross-cloud (AWS Pro <-> GCP Pro) works
because the two sides only share a neutral link, exactly as real AWS<->GCP VPN works by exchanging a peer IP + pre-shared key.
- **Endpoint address:** the portal gives every booster a stable simulated VPN endpoint IP (reserved documentation range) mapped to that booster.
  This is what a user puts in AWS "customer gateway IP" / GCP "external VPN gateway interface IP" / Azure "local network gateway IP".
- **Pairing = (endpoint IP, pre-shared key) matching on both sides**, like the real clouds. When the portal sees side A (peer = B-endpoint, PSK)
  and side B (peer = A-endpoint, same PSK) it brokers the WireGuard link: exchanges public keys/endpoints, uses a WSS relay when UDP is blocked.
  Native SDK/CLI/Terraform therefore works unchanged on each cloud; no Vyomi-specific API required.
- **Nano UI "Join with VPN ID"** is sugar: the creator gets a VPN ID (endpoint + PSK bundle) to share; the joiner enters it and the UI creates
  the matching native resources on their cloud. Owner approval on first join; key rotation, leave/kick.
- **Routing:** static routes first (propagation into route tables already honoured by core/netsim); BGP later via the FRR hybrid-edge work.
  Overlapping CIDRs are rejected with each cloud's own error. Tunnel state goes UP on WireGuard handshake (today it reports DOWN: no IKE peer).
- **Multi-party:** pairwise connections first; hub topology (Transit Gateway / Cloud Router / vWAN) later.
- **Max** with all three clouds can also link its own AWS/GCP/Azure spaces locally with the same native constructs, no WireGuard hop needed.
- **Honest limits:** WireGuard, not IPsec (no real router can connect; downloadable customer-gateway config must say so); only booster-homed spaces
  (labelled); both ends need the portal for the introduction.

### 15. Private management interface (control API isolation)
- The booster's control API binds **only to loopback and a private management interface (`wg-mgmt`)**, never to the LAN or public internet.
  `wg-mgmt` is firewalled to our control plane; other boosters cannot connect. It is part of the locked-down runtime (§8): invisible to
  and not editable by users, and **not** exposed as a simulated-cloud VPN service (user-created VPNs in §14 are separate).
- Reaching it from a tab: unchanged order — local HTTPS hostname -> Cloudflare relay -> unreachable (block). A portal-hosted WireGuard
  hub-and-spoke relay was considered and rejected: it duplicates Cloudflare, adds cost/privacy burden to us, and UDP is blocked on some networks.
- The portal's `<id>.local.vyomi.cloud` record may resolve to the booster's stable management address for devices that have a client.
- **Optional, later (power users):** a WireGuard/Tailscale-style client on a user's device lets any browser (incl. Safari) reach the booster
  by its private address with no relay. A browser tab cannot join WireGuard by itself, and an HTTPS page still needs the trusted hostname/cert
  on that address (no plain-HTTP private IP).

### Still open
Public-exposure details (tier limits for TTL/endpoints/bandwidth, hostname scheme, bandwidth cost, terms, first release vs separate track);
free-tier gating list review; borrowable idle share in the 50/50 split; vyomi.cloud DNS host; current CA rate limits; GCP/Azure VPN core state check.

---

## Part B — Earlier notes (2026-11-02, partly superseded by Part A)

Superseded: "fall back to in-browser when the booster is unreachable" (now: per-space home, booster spaces lock), "a page served by the booster itself" (booster serves no UI), transport order (now Part A §5).


## Proposal (user)
Drop the Nano / Pro / Max build split. Everything is Nano (UI + in-browser WASM backends) with
tiers free / student / developer / enterprise. A **booster pack** = the offline appliance ("Pro")
minus its UI, installed on a student/developer laptop or an enterprise GitHub Codespace. The Nano UI
auto-detects it and routes backend calls to it. Open question the design hangs on: **how the Nano
tab talks to the booster.**

## Agreed points
- Tiers become portal-signed **entitlement flags** checked by the booster, not separate builds.
  Substrates collapse to two: browser (Nano) and booster (headless offline appliance, same cores,
  so a superset of Nano). Consoles already speak native cloud APIs over `/_wire`; the service worker
  routes `/_wire` to Pyodide today and would route it to the booster when attached.
- **Fallback is required:** if the booster is unreachable (laptop off, licence not renewed, user on
  another machine) the tab falls back to the in-browser Nano resources (free tier).
- **Roaming:** a Cloudflare tunnel in front of the booster lets the user reach it from anywhere
  while the host machine is up.
- Switch a whole **space** to the booster at once (cross-service links break if the two ends live on
  different substrates). Keep periodic browser snapshots of the space; on fallback boot Nano from the
  last snapshot with a banner; on reconnect OFFER keep-browser vs replace-with-host (no auto-merge).

## Connection model
The **tab always dials the booster** (a browser tab cannot accept inbound connections). Handshake:
tab sends version + pairing token; booster returns version range, entitlements, capability list
(the existing capability registry). Then `/_wire` calls go tab -> booster over the socket (or plain
fetch), with the socket kept for heartbeat, push events and later TCP framing. While attached,
local tools (aws-cli etc.) can hit the booster's own port directly — no relay needed.
Transport order: direct 127.0.0.1 -> local vyomi-tunnel -> Cloudflare tunnel / Codespaces URL.

## Verified facts (probe, 2026-11-02, Chromium via Playwright, from https://vyomi.cloud)
- Default: tab -> `http://127.0.0.1` / `localhost` (fetch AND WebSocket) is **blocked**:
  `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS` ("Permission was denied").
- With Chrome's **"local-network-access" permission granted**, requests reach the local server
  (a normal fetch then needs CORS headers from the server). So direct localhost works only after the
  user clicks Allow on a one-time per-site prompt.
- NOT tested: Firefox, Safari (Playwright has only Chromium installed; Safari is the riskiest), real
  headed Chrome with a human clicking Allow, a real WebSocket server, a real Cloudflare tunnel.
- Public HTTPS targets (Cloudflare URL, Codespaces forwarded URL) avoid the local-network check and
  mixed content. A page served by the booster itself (same-origin local) also avoids it.

## Current `vyomi-tunnel` 1.0.0 (wasm/relay/local-relay.mjs; npm copy in packaging/tunnel/)
Reverse direction only: tab dials `ws://127.0.0.1:8090/register`; local SDK/CLI HTTP requests are
forwarded over the WS to the freshest open tab (id-correlated; 503 no tab, 504 after 15 s; ping/pong
every 10 s; `/health` beacon with CORS + Private-Network-Access headers used for auto-detect;
loopback-only by default). Gaps for the booster: no tab->host request direction, **no auth** (CORS `*`,
any local process/website can register or call), HTTP request/response only (TCP relay for SSH/DAX
planned as 1.1, not in code), and its PNA comment predates Chrome's new permission prompt.

## Risks / open decisions
1. Browser coverage of direct localhost (Safari/Firefox unknown) -> always ship the tunnel/public-URL
   fallback and an "open the console from your booster" local-served option.
2. Booster listening on localhost or a public tunnel needs: bind 127.0.0.1, origin allow-list
   (vyomi.cloud), per-install pairing token, Host-header check (DNS rebinding), session expiry,
   entitlement check; Cloudflare/Codespaces URLs are internet-reachable so the token is mandatory.
3. Cloudflare tunnels carry HTTP + WebSocket only (no inbound raw TCP); quick tunnels are fragile
   (random URL, no SLA, no SSE); named tunnels need an account + domain. SSH/DAX need the browser-side
   TCP relay over WebSocket frames.
4. Large transfers (S3 uploads) over one multiplexed socket need chunking or an HTTP side channel.
5. Version skew between the always-fresh web UI and an old booster -> handshake version range + graceful
   degradation / update prompt.
6. Fallback semantics still to define: which features degrade without a booster; snapshot cadence;
   reconnect conflict UX.
7. Codespaces: public forwarded port + join token vs GitHub-authenticated private port (unanswered).
8. Should a space move to the booster permanently or fall back automatically (user: fallback is
   required; migration direction/UX still open).

## Suggested next steps (not started)
- Spike: booster stub (handshake, CORS, token check) + tab client with fallback; run behind
  `cloudflared` with a short-lived token-protected URL (needs user OK — publishes a test URL).
- Install Playwright Firefox + WebKit and rerun the localhost probe; user to try real Safari/Firefox.
- Write the full design doc once the transport + auth decisions above are settled.
- User still has a "Design 2" to discuss.
