# Vyomi — Full Architecture (Lite + Enterprise)

Single source of truth for the browser-native simulator and how it relates to the
host/hosted appliance. Companion detail: `VYOMI-LITE-MASTER-SPEC.md`,
`IN-MEMORY-PLAN.md`, `VYOMI-LITE-DESIGN.md`, `spikes/docker-instance/`.

---

## 0. Product split (one codebase, two editions)

| | **Vyomi Lite** (B2C) | **Vyomi Enterprise** (B2B) |
|---|---|---|
| Runtime | Browser (Pyodide + WASM) | Self-hosted Docker appliance / hosted pool |
| Compute | Simulated + WASM runtimes; opt-in remote | Real Docker, real VMs, docker-in-VM |
| Tenancy | **single-tenant** (one space/provider) | multi-tenant, RBAC |
| Reach | in-browser (+ optional relay) | real endpoints, external CLI/Terraform |
| Airgapped | offline PWA | **yes — the moat** |
| Role | top-of-funnel / PLG | revenue |

**Both are build targets of this repo**, selected by `VYOMI_BACKEND={lite|enterprise}`.
The simulation core (handlers, Cedar IAM, provider facades, conformance) is shared;
only the backend adapters differ. *Do not fork.*

**Strategy:** integrate best-of-breed WASM runtimes; **don't build a Docker-in-WASM
kernel** (commodity, incumbent-owned). Moat = multi-cloud conformance fidelity +
airgapped + IAM/policy correctness.

---

## 1. Design principles

1. **Provider = facade.** AWS/GCP/Azure differ only in API/metadata/console; everything
   below is shared engines.
2. **One codebase, two backends** behind seams (`ServiceBackend`, `ComputeBackend`).
3. **Conformance is inherited**, not reimplemented — Lite runs the real `server.py` handlers.
4. **Integrate, don't invent** the runtime/network substrate.
5. **Single-tenant Lite** collapses the state model and isolation edge cases.

---

## 2. Layer stack

```
L7 Client/SDK     SPA · aws-sdk-js/@google-cloud/@azure · boto3-in-Pyodide
L6 Edge/transport Service Worker (fetch⇄ASGI + reverse proxy) · Portal relay (external)
L5 API facade     per-provider REST/auth/metadata (IMDS/GCE-md/Azure-IMDS)   [providers/*]
L4 Service engine shared per-category engines (§5)
L3 Runtime/control RuntimeBackends · InstanceManager · VirtualNetwork (§4, §6)
L2 Persistence    OPFS + IndexedDB · snapshot/rehydrate · export/import (§7)
L1 Host           Pyodide · Web Workers · Service Worker · SharedWorker
```

---

## 3. Runtime host (L1)

- **Pyodide worker** — runs `server.py` (FastAPI) as an ASGI app. No socket: the
  **Service Worker** turns each `/api/*` fetch into one `app(scope, receive, send)` cycle.
- **Web Worker per running instance** — true concurrency; isolation.
- **SharedWorker** — the cross-tab network hub (§6).
- **Service Worker** — app-shell cache (offline) + fetch⇄ASGI + cross-tab L7 reverse proxy.

---

## 4. Compute architecture (L3)

```
ProviderFacade (Ec2 / Gce / AzureVm)        ← the only place "style" lives
        │ normalises → InstanceSpec
InstanceManager  (the browser hypervisor)
        │  launch/list/stop/destroy · QUOTA + memory budget (admission control)
        │  owns VirtualNetwork · multiplexes Workers (and cross-tab instances)
        ▼
RuntimeBackend  (pluggable engines — the spike's seam)
   Simulated · Pyodide(Py) · WebContainer/BrowserPod(Node) · CheerpJ(Java)
   Container2Wasm(any image, emulated) · RemoteDocker(real host)
```

```python
class ProviderFacade(ABC):
    def to_spec(self, req) -> InstanceSpec: ...
    def to_view(self, inst) -> dict: ...           # IMDS / GCE-md / Azure-IMDS shape
    image_catalog; machine_types; lifecycle_map

class InstanceManager(ABC):
    def launch(self, spec) -> Instance: ...        # budget-admission-controlled
    def list/get/stop/start/destroy(...): ...
    def exec(self, id, cmd): ...
    net: VirtualNetwork

class RuntimeBackend(ABC):
    def create/start/stop/destroy(...): ...
    def deploy(self, app): ...
    def expose(self) -> str | None: ...            # Portal/relay URL, or None
    def status/ipv4(...): ...
```

**Per-language "deploy a real app" targets:** Python→Pyodide · Node→WebContainers/
BrowserPod · Java→CheerpJ · any image→Container2Wasm (emulated) · full fidelity→
RemoteDocker. Memory budget caps concurrent heavy runtimes (a handful of JVM/Node).

### 4a. RuntimeBackend language matrix (WASM)

Two ways a language runs in WASM: **runtime-in-WASM** (the interpreter/VM is compiled
to WASM → runs *unmodified source*; bigger, slower start — best for "deploy my app")
vs **compile-to-WASM** (the app is built to a `.wasm` artifact; small/fast — needs a
build step). `container2wasm` is the slow catch-all for everything else.

| Group | Languages | Toolchain (RuntimeBackend impl) | Maturity | "Deploy app" fit |
|---|---|---|---|---|
| **Runtime-in-WASM** (run source) | **Python** ✓ | Pyodide | prod | best |
| | **JS / TypeScript / Node** ✓ | WebContainers · BrowserPod · QuickJS-wasm | prod | best |
| | **Java / JVM** (+Kotlin, Scala, Clojure) ✓ | CheerpJ (JVM→WASM) · TeaVM (AOT) | maturing (Java 17 gating) | best |
| | **C# / F# (.NET)** | Blazor / Mono-WASM | prod | best (enterprise) |
| | **Ruby** | ruby.wasm (CRuby→WASM) | working | best |
| | **PHP** | php-wasm | working | best |
| | **R** | WebR | working | niche (data) |
| | **Lua** | wasmoon | working | embed/scripting |
| | Perl | WebPerl | experimental | niche |
| **Compile-to-WASM** (run artifact) | **Rust** | rustc `wasm32` | prod | good (bring `.wasm`) |
| | **C / C++** | Emscripten · clang/wasi-sdk | prod | good |
| | **Go** (+ **TinyGo**) | `GOOS=wasip1` · TinyGo | prod | good |
| | **AssemblyScript** | asc | prod | good |
| | **Zig** | zig wasm/wasi | prod | good |
| | **Swift** | SwiftWasm | maturing | good |
| | **Kotlin/Wasm** | Kotlin/Wasm | maturing | good |
| | **Dart / Flutter** | dart2wasm | maturing | good (UI) |
| **Any image** (emulated) | anything in a container | container2wasm (CPU emu) | experimental | catch-all, slow |

✓ = shipped in P4. **Recommended next additions:** Ruby + PHP + .NET (run-source, high
demand) and Go + Rust + C/C++ (tiny/fast artifacts).

**Cross-cutting:** runtime-in-WASM images are large (Pyodide ~6–10 MB, Blazor larger)
→ the InstanceManager budget caps concurrency. Networking via the SDN/tcpip.js (§6);
filesystem via OPFS (§7); threads are per-runtime-limited. Compiled langs usually
"bring a `.wasm`" since in-browser compilation is heavy.

---

## 5. Service engines (L4/L5) — single-tenant, in-memory

| Category | AWS / GCP / Azure | In-browser engine | Persist |
|---|---|---|---|
| Object storage | S3 / GCS / Blob | **BlobEngine** (index + bytes in OPFS) | OPFS |
| Relational DB | RDS / Cloud SQL / Azure SQL | **PGlite** (PG) · SQLite-WASM (MySQL) | IDB/OPFS |
| NoSQL | DynamoDB / Firestore / Cosmos | **moto** + in-proc doc store | IDB |
| Queue/Event | SQS·EventBridge / PubSub·Eventarc / SvcBus·EventGrid | in-proc queue + bus | IDB |
| IAM/RBAC | IAM / IAM / RBAC | **cedar-wasm** (same engine) | IDB |
| KMS+Secrets | KMS+SM / KMS+SM / KeyVault | **WebCrypto** + KV | IDB (wrapped) |
| Functions | Lambda / Cloud Fn / Azure Fn | in-proc executor on the WASM runtimes | OPFS+IDB |
| Compute realism | CloudSim (JVM) | **PythonLocalBackend** (default) or **CheerpJBackend** | IDB |
| Networking | VPC / VPC / VNet | **VirtualNetwork** (§6) | IDB |

**CloudSim note:** `cloudsim-backbone` is already behind a client seam with a Python
`local-fallback`. Lite default = Python scheduler (no JVM). Optional high-fidelity =
**CheerpJBackend** running the unmodified JAR in CheerpJ — **gated on the Java-17
spike** (CloudSim Plus 8.5.7 needs Java 17; CheerpJ 17 support is maturing).

---

## 6. Networking — the fractal topology

**The mapping (cloud-accurate):**

| Cloud construct | Browser realization | Transport |
|---|---|---|
| **Instance / host** | a **tab** | — |
| **Availability Zone** (fault domain) | a **browser process** (its same-origin tabs share one hub) | SharedWorker (free IPC) |
| **VPC / Region** (spans AZs) | **federation of browsers** | **WebRTC / overlay** (a real network hop) |
| **Multi-region** | browsers on **different devices** | overlay + DERP relay (NAT traversal) |

**Iron rule:** cross-tab (same browser, same origin) is free shared IPC; **crossing the
browser boundary is a real network hop** (sandboxes share nothing) — which is exactly
why a browser makes a faithful AZ.

### 6a. Intra-AZ (cross-tab, same browser) — fully client-side
```
 Tab A (server app)        Tab B (client/test)
   │ virtual NIC               │ fetch('http://myapp.local:8080')
   ▼                           ▼
 ┌──── SharedWorker = VPC router/switch ─────────────────────────┐
 │ IPAM · subnets · route tables · SECURITY GROUPS · NACLs · DNS │
 └───────────────┬───────────────────────────────────────────────┘
                 │  Service Worker = L7 reverse proxy (fetch from any tab → hub)
 tcpip.js (lwIP-WASM) per instance → REAL TCP sockets over the hub transport
 BroadcastChannel → discovery/signaling
```
- Each tab = an instance/ENI with a **private IP** (hub IPAM).
- **Security groups are enforced**: A→B:8080 delivered only if B's SG allows A; A→B:22
  refused. *Real* enforcement between *real* running apps — the credibility moment.
- **tcpip.js** gives real TCP (not just fetch-proxied HTTP); virtual DNS resolves
  `myapp.local → 10.0.1.5`.

### 6b. Inter-AZ / VPC (cross-browser) — needs a wire
- **WebRTC** data channels (P2P, tiny signaling to exchange ICE/SDP) **or** an
  **overlay** (Tailscale-wasm: WireGuard + gVisor netstack in WASM, DERP relays;
  or libp2p). Each browser-AZ joins the VPC overlay.
- **Shared VPC state** (IPAM/routes/SGs across AZs) via a **CRDT** so AZs converge
  without a central authority; handle partitions explicitly.
- This tier is **not purely offline** (signaling/relay) and is **opt-in/advanced**.

### 6c. The payoff
A real **multi-AZ HA demo, client-side**: replicate a service across Chrome-AZ and
Edge-AZ, load-balance via private DNS, **kill Chrome → AZ outage → live failover to
the Edge-AZ replica.** Independent processes = real fault domains. No cloud account.

### 6d. Faithful vs approximated
- **Faithful:** private IPs, subnet isolation, **SG/NACL enforcement**, route tables,
  private DNS, IGW egress (`fetch`/WS), real instance-to-instance TCP, AZ fault isolation.
- **Approximated:** L3/L4 over a message/overlay transport (not L2 on a wire);
  bandwidth/latency/MTU simulated; same-origin per AZ; handful of instances (memory);
  live fabric tied to open tabs; cross-device needs relay/NAT traversal.

---

## 7. State persistence across restarts (L2)

| Store | Holds |
|---|---|
| **OPFS** | object bytes (S3/GCS/Blob) · the app SQLite state file (maps `.cloudlearn_state.sqlite3`) · function code |
| **IndexedDB** | PGlite DB · JSON snapshots of in-proc stores (Dynamo/SQS/PubSub/Firestore/KV/network) · Cedar policies · **wrapped** KMS keys |

- Repoint `_persist_state` → **debounced, write-ahead, atomic-swap** writer; rehydrate
  `STATE` on boot; `schema_version` + migrations (already present, e.g. `migrate_default_space_names`).
- `navigator.storage.persist()` to resist eviction; surface granted/denied.
- **Export/Import a `.vyomi` bundle** (zip of OPFS+IDB) → backup/share/CI fixtures.
- **Reset** = clear OPFS+IDB. Running Workers don't persist → instances reload `stopped`.

---

## 8. SDK/API/utility conformance (L6/L7)

Four independent axes; "100%" defined precisely:

| Axis | Lite ceiling |
|---|---|
| API wire contract | **100%** (same handlers) |
| Semantic behavior | ~100% minus backend-swap deltas |
| In-browser SDKs (aws-sdk-js, boto3-in-Pyodide) | **100%** |
| External CLI/Terraform | **only via Portal relay** (no socket in a tab) |

**Delta ledger:** MySQL-on-SQLite dialect · S3 presign/external-SigV4 (relay-only) ·
compute behavior (Simulated unless RemoteDocker) · gRPC GCP fidelity · DB wire clients
(gone) · cross-service event timing.

**Measured, not claimed:** run the existing harness (35/35 real-SPA + API suite) against
the Lite build; add a boto3-in-Pyodide pass and a relay pass for real CLIs; publish a
per-service scorecard (✓ / ✓-with-delta / relay-only).

---

## 9. Component inventory — reuse / integrate / build

| Reuse (this repo) | Integrate (3rd-party WASM) | Build (new, thin) |
|---|---|---|
| SPA · FastAPI handlers · `STATE`/`app_context` · pydantic · boto3 shapes · provider facades · Cedar logic · conformance harness | Pyodide · PGlite · cedar-wasm · moto · WebContainers/BrowserPod · CheerpJ · container2wasm · tcpip.js · Tailscale-wasm/libp2p | Service Worker + fetch⇄ASGI · SharedWorker hub + Service-Worker proxy · `ServiceBackend`/`ComputeBackend`/`InstanceManager`/`VirtualNetwork` · persistence snapshotter · build pipeline |

---

## 10. Roadmap

| Phase | Scope | Exit criterion |
|---|---|---|
| **P0 shell** | Pyodide + FastAPI + fetch⇄ASGI + SPA + 1 service (S3) | SPA lists/creates a bucket, no server |
| **P1 AWS core** | S3·DynamoDB·SQS·IAM·RDS (single-tenant) | AWS console usable offline |
| **P2 networking** | SharedWorker hub + Service-Worker proxy + tcpip.js (intra-AZ VPC, SG enforced) | tab-A app reachable + SG-blocked from tab-B |
| **P3 GCP + Azure** | remaining services | 3 consoles green |
| **P4 compute** | RuntimeBackends (Pyodide/Node/Java/container2wasm) + InstanceManager budget | deploy a real app in a tab |
| **P5 persistence** | OPFS/IDB snapshot+rehydrate · Export/Import | survives refresh |
| **P6 multi-AZ (opt-in)** | WebRTC/overlay federation + CRDT VPC state | cross-browser HA failover demo |
| **P7 distribution** | static PWA, offline, docs, conformance scorecard | shippable Lite |

Enterprise tracks in parallel: LXD→Docker compute (spike) · airgapped · SSO/RBAC/audit.

---

## 11. Risk register (spike before committing)

1. **moto imports in Pyodide** (dep tree) — gates P1.
2. **PGlite↔Python async bridge** perf — gates RDS fidelity.
3. **Pyodide bundle/cold-start** on target devices — gates everything.
4. **fetch⇄ASGI shim** streaming/large bodies (S3 multipart).
5. **SharedWorker support** (Safari ≥16.4; else leader-tab via Web Locks) — gates P2.
6. **CheerpJ Java-17** for CloudSim — gates the high-fidelity CloudSim option.
7. **WebRTC NAT traversal + CRDT convergence** — gates P6.

P0 is the single highest-signal step (covers #3 and #4).

---

## 12. One-paragraph summary

Provider facades over shared in-memory/WASM service engines, with compute as a
pluggable `RuntimeBackend` orchestrated by an `InstanceManager`, and a `VirtualNetwork`
that is a **fractal**: tabs are hosts, a browser is an Availability Zone (same-origin
tabs share a SharedWorker hub that enforces VPC security groups over real tcpip.js TCP),
federated browsers form a VPC/region over WebRTC/overlay, and devices are multi-region.
State lives in OPFS/IndexedDB; conformance is inherited from the appliance's own
handlers and measured by the existing harness. Lite (B2C, single-tenant, browser) and
Enterprise (B2B, real compute, airgapped) are two backends of one codebase — and every
hard runtime/network piece is integrated, not invented, so the moat stays in the
simulation.
