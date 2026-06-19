# Vyomi Lite — In-Memory Backend Plan (browser build)

**Principle:** the Python FastAPI app (`server.py`) runs in the browser via
**Pyodide**; the SPA already runs in the browser; **every external backing
container is replaced by an in-process Python store or a WASM in-memory engine.**
Zero containers, zero network, zero host virtualization.

This plan maps each of the 11 backing services to an in-browser equivalent and is
grounded in where `server.py` actually delegates to a real backend today.

---

## 1. Target architecture

```
┌──────────────────────────── browser tab ────────────────────────────┐
│  SPA (static HTML/JS, unchanged)  ──fetch('/api/..')──┐              │
│                                                       ▼              │
│  Service Worker  ── fetch⇄ASGI shim ──►  Pyodide: server.py (FastAPI)│
│                                              │  adapters             │
│        in-memory engines  ◄──────────────────┤                      │
│   PGlite(WASM) · cedar-wasm(WASM) · WebCrypto · in-proc Py stores    │
│        persistence ►  OPFS / IndexedDB (snapshots)                   │
└──────────────────────────────────────────────────────────────────────┘
```
The "UI in Python" = the FastAPI app + thin backend adapters in Pyodide. The
adapters call in-memory engines instead of opening sockets to containers.

---

## 2. Brutally-honest constraints (read before the table)

- **No sockets in a browser.** The current RDS/Cloud SQL fidelity — an *unmodified
  app connecting over the real psycopg2/pymysql wire protocol* (`core/gcp_sql_engine.py`)
  — **cannot exist in-browser.** In-process SQL *execution* survives; external wire
  clients do not. Same for "point real `aws-cli` at the sim": an in-browser app is
  not a reachable server.
- **No real compute.** Already established: LXD/Docker/dockerd don't run in a WASM
  sandbox. Compute (EC2/GCE/Azure VM, docker-in-VM) becomes an **in-memory state
  machine — metadata only.** Feature-gate it OFF in the SPA.
- **Pyodide can't load arbitrary C/Rust wheels.** Swaps required: `cedarpy`(Rust)→
  cedar-wasm, gRPC GCP clients→in-proc, `uvicorn[standard]`→ASGI shim,
  `psycopg2`→PGlite. Good news: `cryptography`, `sqlite3`, `pydantic-core` **are**
  prebuilt in Pyodide.
- **In-memory is volatile.** Anything that must survive a refresh needs an explicit
  snapshot to OPFS/IndexedDB (you already have `_persist_state` — repoint its sink).
- **Cross-language calls are async.** PGlite and cedar-wasm are JS/WASM; Python calls
  them through the Pyodide JS bridge and `await`s JS promises. Handlers that touch
  SQL or IAM become `async` (FastAPI is already async-friendly).

---

## 3. The mapping (core deliverable)

| # | Backing container (today) | Cloud API | Real-fidelity source in code | **In-browser in-memory equivalent** | Runtime | Fidelity kept / lost |
|---|---|---|---|---|---|---|
| 1 | postgres:16 | RDS / Cloud SQL (PG) | `core/gcp_sql_engine.py` (psycopg2) | **PGlite** (Postgres→WASM, persists to IndexedDB) | WASM/JS | KEEP real PG SQL + persistence · LOSE external wire clients |
| 2 | mysql:8.0 | RDS (MySQL) | `gcp_sql_engine.py` (pymysql) | **SQLite-WASM (sql.js)** + dialect shim — **NOT H2** | WASM | KEEP basic SQL · LOSE MySQL-specific funcs (H2 rejected: JVM, won't run in browser) |
| 3 | dynamodb-local (JVM) | DynamoDB | providers/dynamodb state | **moto** DynamoDB backend (pure-Python) | Python | KEEP item/query/GSI semantics · LOSE a few edge behaviors |
| 4 | minio (Go) | S3 | `core/minio_mirror.py` | in-proc blob store + **OPFS** for bytes (or moto S3) | Python+OPFS | KEEP S3 API + durable-ish bytes · LOSE external SigV4 SDK / real presign |
| 5 | fake-gcs (Go) | GCS | gcp storage | same blob engine as S3 | Python+OPFS | as S3 |
| 6 | elasticmq (JVM) | SQS | sqs state | in-proc queue w/ visibility timeout (moto SQS) | Python | KEEP send/recv/visibility · LOSE exact timing |
| 7 | pubsub emulator (JVM) | Pub/Sub | gcp pubsub | in-proc topic/subscription model | Python | KEEP publish/pull/ack · LOSE gRPC streaming |
| 8 | firestore emulator (JVM) | Firestore | gcp firestore | in-proc document store (collections/docs/subset queries) | Python | KEEP CRUD + simple queries · LOSE composite-index / realtime |
| 9 | vault (Go) — transit | KMS | `cryptography` (C/Rust) | **cryptography-in-Pyodide** or **WebCrypto** | Python/WASM | KEEP encrypt/decrypt/sign · LOSE Vault policy layer |
| 10 | vault (Go) — KV | Secrets Mgr | secrets state | in-proc KV dict (+OPFS) | Python | KEEP get/put/version · LOSE Vault auth |
| 11 | nats (Go) | EventBridge/Eventarc/Event Grid | core eventing | in-proc async pub/sub bus | Python | KEEP fan-out · LOSE durable streams/JetStream |
| 12 | cloudsim (JVM) | EC2/GCE/Azure compute | server.py LXD/Docker | in-memory instance **state machine** | Python | metadata only · NO real compute/SSH/docker-in-VM |
| — | IAM/RBAC engine | AWS IAM / GCP IAM / Azure RBAC | `core/cedar_engine.py` (cedarpy) | **cedar-wasm** (`@cedar-policy/cedar-wasm`) | WASM/JS | KEEP **the same Cedar engine** · LOSE ~nothing |
| — | `.cloudlearn_state.sqlite3` | persisted app state | `core/app_context.py` | **SQLite-WASM + OPFS** | WASM | 1:1 mapping |

**Refinements to the seed examples (honest):**
- *Postgres → pg-mem* → use **PGlite** instead: it's real Postgres compiled to WASM
  (true SQL fidelity + IndexedDB persistence), where pg-mem is a partial reimpl.
- *MySQL → H2* → **drop H2**: it's a JVM database; there is no JVM in the browser.
  Collapse MySQL onto SQLite-WASM with a dialect shim and accept reduced MySQL
  fidelity, or run a second PGlite and translate.
- *DynamoDB → in-memory dynamo* → **moto** gives you a Python-native, in-process
  DynamoDB (and S3/SQS) backend — one library covers three rows, no separate Node
  process (dynalite is Node-only).
- *Cedar → cedar in-memory* → **cedar-wasm** is the official WASM build; it's the
  *same* engine `cedar_engine.py` already targets, so the swap is an adapter, not a
  reimplementation.

---

## 4. Dependency disposition (Pyodide)

| Keep (Pyodide-available) | Swap | Add (JS/WASM via bridge) |
|---|---|---|
| fastapi, starlette, pydantic(+core), boto3/botocore (pure-py, shapes), sqlite3, cryptography | psycopg2→PGlite · pymysql→SQLite · google-cloud-pubsub/firestore (gRPC)→in-proc · cedarpy→cedar-wasm · uvicorn[standard]→ASGI shim · docker→(compute off) | PGlite, cedar-wasm, sql.js |

---

## 5. The fetch ⇄ ASGI shim (how a Python app serves the SPA with no server)

Service worker intercepts `/api/*`, builds an ASGI scope, drives the app in Pyodide:

```js
// sw.js
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith('/api/')) e.respondWith(toPyodide(e.request));
});
// toPyodide -> postMessage to the Pyodide worker -> await app(scope, receive, send) -> Response
```
```python
# in Pyodide: dispatch one request through the ASGI app, collect the response
async def handle(scope, body):
    out = {}
    async def receive(): return {"type":"http.request","body":body}
    async def send(ev):
        if ev["type"]=="http.response.start": out["status"], out["headers"] = ev["status"], ev["headers"]
        elif ev["type"]=="http.response.body": out.setdefault("body", b""); out["body"] += ev.get("body", b"")
    await app(scope, receive, send)
    return out
```

---

## 6. Cross-language bridge pattern (Python → PGlite / cedar-wasm)

```python
import js
from pyodide.ffi import to_js
pglite = js.PGlite.new("idb://vyomi")                 # JS object, persists to IndexedDB
res    = await pglite.query(sql, to_js(params))       # await a JS promise from Python
rows   = res.rows.to_py()
# cedar_engine.py adapter:
decision = await js.cedar.isAuthorized(to_js(request), to_js(policies), to_js(entities))
```

---

## 7. Persistence

| Store | Sink |
|---|---|
| PGlite (RDS PG) | IndexedDB (native) |
| App STATE / sqlite | OPFS |
| S3/GCS blobs | OPFS |
| in-proc Python stores (dynamo/sqs/pubsub/firestore/KV) | periodic JSON snapshot → IndexedDB; rehydrate on boot (repoint `_persist_state`) |

---

## 8. Fidelity ledger (the honest scorecard)

**KEEP:** every REST API shape · IAM/RBAC evaluation (identical Cedar engine) · real
Postgres SQL · S3/GCS/DynamoDB/SQS/Pub-Sub/Firestore CRUD semantics · KMS crypto ·
state persistence.

**LOSE:** real compute (EC2/VM/docker-in-VM) · external SDK/CLI access to the sim (an
in-browser app isn't a reachable endpoint for `aws-cli`/Terraform) · DB wire-protocol
clients · MySQL-specific behavior · gRPC streaming fidelity · the conformance harness
paths that hit real backends · multi-process realism.

**Net:** Vyomi Lite is a faithful **API + IAM + data-semantics** simulator for
learning/demo in a browser — a deliberately lower-fidelity SKU, not the appliance.

---

## 9. Phasing

- **P0 — shell spike:** Pyodide + FastAPI + fetch⇄ASGI shim serving the SPA with ONE
  in-proc service (S3). Proves the hardest plumbing (serving Python with no server).
- **P1 — AWS core:** S3(OPFS) · DynamoDB(moto) · SQS(moto) · IAM(cedar-wasm) · RDS(PGlite).
- **P2 — GCP:** GCS · Pub/Sub · Firestore · Cloud SQL · IAM.
- **P3 — Azure + KMS/Secrets + eventing bus.**
- **P4 — persistence (OPFS/IndexedDB snapshot+rehydrate) + Pyodide bundle/startup tuning.**
- Compute stays feature-gated OFF throughout.

---

## 10. Risks to validate first (cheap spikes, high signal)

1. **moto imports cleanly in Pyodide** (its transitive deps) — gates P1.
2. **PGlite↔Python async bridge** perf for many small queries — gates RDS fidelity.
3. **Pyodide bundle size + cold start** acceptable (~6–10 MB runtime + packages).
4. **fetch⇄ASGI shim** handles streaming / large bodies (S3 multipart uploads).
5. **cedar-wasm API parity** with cedarpy so `cedar_engine.py` swaps via adapter only.

> Reuses the `ComputeBackend` seam idea from `spikes/docker-instance/`: define a
> thin backend interface per service so the in-memory engine is one implementation
> and the container-backed one stays for the server build.
