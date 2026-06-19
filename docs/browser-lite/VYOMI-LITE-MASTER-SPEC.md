# Vyomi Lite — Master Spec

Capstone design: layer separation · native-service equivalents (all 3 providers) ·
state persistence across browser restarts · SDK/API/utility conformance.

Companion: `VYOMI-LITE-DESIGN.md` (overview) · `IN-MEMORY-PLAN.md` (backend mapping) ·
`spikes/docker-instance/` (the backend seam).

Guiding principle: **Provider = facade; everything below is shared.** Lite reuses
`server.py`'s actual handlers, so conformance is *inherited*, not reimplemented —
the only conformance deltas are the documented backend swaps.

---

## 1. Layer-separation matrix

| # | Layer | Responsibility | Per-provider? | Reuse / New | Conformance role |
|---|---|---|---|---|---|
| L7 | **Client / SDK** | JS SDKs, boto3-in-Pyodide, CLI-in-WASM, the SPA | no | reuse SPA | the conformance *surface* |
| L6 | **Edge / transport** | service-worker `fetch⇄ASGI`; optional **Portal relay** for external reach | no | new | makes external SDKs/CLIs reachable |
| L5 | **API facade** | per-provider REST shapes, SigV4/OAuth/SharedKey auth, error envelopes, metadata services (IMDS/GCE-md/Azure-IMDS) | **yes** | reuse `providers/*`, routes | wire-shape conformance |
| L4 | **Service engine** | the shared per-category engines (§2) | no | reuse handlers + adapters | semantic conformance |
| L3 | **Runtime / backend** | in-mem stores, WASM engines (PGlite, cedar-wasm), `RuntimeBackend`s, `InstanceManager`, `VirtualNetwork` | no | new + seam | behavior fidelity |
| L2 | **Persistence** | OPFS / IndexedDB, snapshot/rehydrate, export/import, migrations (§3) | no | new | durability |
| L1 | **Host** | Pyodide + Web Workers + service worker | no | new | execution substrate |

**Compute sub-layers** (from the SoC discussion):

```
ProviderFacade (Ec2/Gce/AzureVm)  → normalises to InstanceSpec
        │
InstanceManager  → launch/list/stop/destroy · QUOTA+memory budget · owns VirtualNetwork (in-browser VPC) · multiplexes N Workers
        │
RuntimeBackend   → Simulated · Pyodide(Py) · WebContainer/BrowserPod(Node) · CheerpJ(Java) · Container2Wasm(any) · RemoteDocker(real host)
```

Interfaces:
```python
class ProviderFacade(ABC):     # one per provider — the only place "style" lives
    def to_spec(self, req) -> InstanceSpec: ...
    def to_view(self, inst) -> dict: ...          # IMDS/GCE-md/Azure-IMDS shape
    image_catalog: list; machine_types: list; lifecycle_map: dict

class InstanceManager(ABC):     # shared — the browser hypervisor
    def launch(self, spec) -> Instance: ...       # admission-controlled by budget
    def list/get/stop/start/destroy(...): ...
    def exec(self, id, cmd): ...
    net: VirtualNetwork                            # per-instance virtual IPs, inter-VM routing

class RuntimeBackend(ABC):      # shared — pluggable engines (the spike's seam)
    def create/start/stop/destroy(...): ...
    def deploy(self, app) -> None: ...
    def expose(self) -> str | None: ...            # Portal/relay URL, or None
    def status/ipv4(...): ...
```

---

## 2. Native-service equivalents matrix (organised by category → 3 facades)

| Category | AWS | GCP | Azure | Backing today | **In-browser engine** | Persist sink |
|---|---|---|---|---|---|---|
| Compute (VM) | EC2 | GCE | Azure VM | LXD/Docker | `RuntimeBackend` via `InstanceManager` (Simulated default; WASM runtimes; RemoteDocker for real) | snapshot (IDB) |
| Serverless fn | Lambda | Cloud Functions | Azure Functions | in-proc | **in-proc executor** — run handler in matching WASM runtime (Pyodide/WebContainer/CheerpJ) | code→OPFS, meta→IDB |
| Object storage | S3 | GCS | Blob Storage | MinIO / fake-gcs | **BlobEngine** (in-mem index + bytes in **OPFS**) | OPFS |
| Relational DB | RDS | Cloud SQL | Azure SQL | Postgres / MySQL | **PGlite** (PG, WASM) · **SQLite-WASM** (MySQL/other, dialect shim) | IDB (PGlite) / OPFS |
| NoSQL | DynamoDB | Firestore | Cosmos DB | dynamodb-local / firestore-emu | **moto** (Dynamo) · in-proc document store (Firestore/Cosmos) | snapshot (IDB) |
| Queue / msg | SQS | Pub/Sub | Service Bus | ElasticMQ / pubsub-emu | in-proc queue/topic (visibility timeout, ack) | snapshot (IDB) |
| Eventing | EventBridge | Eventarc | Event Grid | NATS | in-proc async event **bus** | snapshot (IDB) |
| IAM / RBAC | IAM | IAM | RBAC / Entra | `cedar_engine.py` (cedarpy) | **cedar-wasm** (same Cedar engine) | policies → IDB |
| KMS + Secrets | KMS + Secrets Mgr | KMS + Secret Mgr | Key Vault | Vault + `cryptography` | **WebCrypto** (crypto) + in-proc KV | wrapped keys → IDB |
| Networking | VPC | VPC | VNet | metadata | **VirtualNetwork** (in-browser SDN; virtual IPs; inter-Worker routing) | snapshot (IDB) |
| API gateway | API Gateway | API Gateway | API Management | in-proc | in-proc gateway/router | snapshot (IDB) |
| Compute realism | (CloudSim backbone) | — | — | Java JVM `:9010` | **Python local scheduler** (extend existing `local-fallback`) — no JVM | snapshot (IDB) |

**Shared-engine wins:** object storage (3→1 BlobEngine), SQL (3→PGlite/SQLite), IAM
(3→cedar-wasm), eventing/queue (3→in-proc). The 3 providers are *facades* over these.

---

## 3. State persistence across browser restarts

**Two browser stores, by data shape:**

| Store | Holds | Why |
|---|---|---|
| **OPFS** (Origin Private File System) | S3/GCS/Blob object bytes · the app's SQLite state file (maps `.cloudlearn_state.sqlite3`) · function code bundles | large/binary, file-like, sync access in a Worker |
| **IndexedDB** | PGlite database (native target) · JSON snapshots of in-proc stores (Dynamo/SQS/PubSub/Firestore/KV/network/gateway) · Cedar policy sets · wrapped KMS key material | structured, transactional |

**Snapshot / rehydrate cycle:**
1. Repoint `_persist_state` → a **debounced, write-ahead, atomic-swap** writer into IDB/OPFS (no partial states).
2. On boot: rehydrate `STATE` from the snapshot, open PGlite (IDB) and OPFS handles, replay nothing else needed (state is the source of truth).
3. **Versioning + migration:** stamp a `schema_version`; run migrations on load (the app already does this, e.g. `migrate_default_space_names`).

**Durability hardening (honest browser gotchas):**
- Browsers can **evict** OPFS/IDB under storage pressure → call `navigator.storage.persist()` and surface the granted/denied state to the user.
- **Export / Import** a single `.vyomi` bundle (zip of OPFS+IDB dumps) → portability, sharing, backup, and CI fixtures. Turns volatility into a feature.
- **Reset** = clear OPFS+IDB (the "fresh appliance").
- KMS key material stored **wrapped** (WebCrypto non-extractable wrap key, optionally user-passphrase-derived) — never plaintext at rest.

**What does NOT persist (by design):** running runtime processes (Workers) — instances
return to `stopped` on reload and restart their runtime on next start; in-flight
function executions; ephemeral network sockets.

---

## 4. SDK / API / utilities conformance

### 4.1 Define "100%" precisely (the honest part)
Conformance has **four independent axes** — don't conflate them:

| Axis | What it means | Lite ceiling |
|---|---|---|
| **A. API wire contract** | request/response/error envelopes, status codes, headers | **100% achievable** — same `server.py` handlers |
| **B. Semantic behavior** | validation, limits, eventual-consistency, pagination | **~100%** minus documented backend-swap deltas (§4.3) |
| **C. SDK compatibility** | SDKs that call the API | **100% for in-browser SDKs**; external needs a relay (§4.2) |
| **D. Utility/CLI compatibility** | aws-cli, gcloud, az, Terraform | **only via the Portal relay** (no socket in a tab) |

**Because Lite reuses the actual handlers, axes A/B are *inherited* from the
appliance** — the existing conformance harness is the proof, not a hope.

### 4.2 The reachability split (why external tools need a relay)
- **In-browser clients** (the SPA, `aws-sdk-js`/`@google-cloud`/`@azure`, **boto3 running in Pyodide**) hit the service worker → the *same* handlers → **100% conformant**.
- **External clients** (a terminal's `aws-cli`, Terraform, host boto3) have no socket to reach a tab. They work **only** when the in-browser API is exposed via a **Portal/relay** (BrowserPod-style public URL or your WS proxy). With the relay: external SDK/CLI conformance is the same 100% (same handlers). Without it: not reachable — state this plainly in the product.

### 4.3 Conformance-delta ledger (where Lite is < appliance — be explicit)
| Delta | Cause | Mitigation |
|---|---|---|
| RDS **MySQL** dialect gaps | SQLite-WASM stands in for MySQL | run MySQL workloads on PGlite, or document unsupported funcs |
| S3 **presigned-URL / external SigV4** | OPFS blob, no external endpoint | works via relay; else in-browser-only |
| **Compute** behavior (real boot/SSH/docker-in-VM) | Simulated backend | use RemoteDocker (hosted) for real |
| **gRPC** GCP fidelity | in-proc REST only | REST-path conformance only |
| DB **wire-protocol** clients (psql/mysql connect) | no socket | n/a in browser |
| cross-service **event timing** | in-proc bus vs broker | semantics kept, timing approximate |

### 4.4 How 100% is measured (gate, not vibe)
Run the **existing conformance harness against the Lite build**:
- the real-SPA Playwright suite (today 35/35) drives the SPA → in-browser handlers;
- the API conformance suite asserts wire shapes;
- add a **boto3-in-Pyodide** pass + a **relay** pass driving real `aws-cli`/`gcloud`/`az`.
Publish a **per-service conformance scorecard** (✓ / ✓-with-delta / relay-only) so "100%"
is a measured number with an explicit delta list — never a blanket claim.

---

## 5. The one-line architecture

> Provider facades (L5) over shared service engines (L4) over pluggable runtimes +
> an instance manager + virtual network (L3), persisted to OPFS/IndexedDB (L2), all
> hosted in Pyodide + Workers (L1), reached in-browser directly and externally via a
> Portal relay — with conformance inherited from the appliance's own handlers and
> measured by the existing harness.
