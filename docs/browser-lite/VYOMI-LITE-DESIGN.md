# Vyomi Lite — Design

A browser-native, zero-install, offline-capable build of Vyomi. The SPA runs as
today; the FastAPI app runs in **Pyodide** (Python→WASM); every backing container
is replaced by an in-process Python store or a WASM engine. No containers, no
network, no host virtualization.

Companion docs: [`IN-MEMORY-PLAN.md`](./IN-MEMORY-PLAN.md) (per-service backend
mapping) · `spikes/docker-instance/` (the `ComputeBackend` seam pattern this reuses).

---

## 0. The keystone decision (read first)

**Vyomi Lite must be a *build target of this repo*, not a fork.** The difference
between sustainable and a maintenance nightmare is one architectural choice:

> Introduce a `ServiceBackend` seam per service category. The container-backed
> impl (`*Server`) and the in-memory impl (`*Lite`) are two implementations
> selected at boot by a single `VYOMI_BACKEND={server|lite}` switch.

Everything below follows from this. The same `server.py` routes, pydantic models,
and `STATE` logic serve both the appliance and Lite; only the backend adapters
differ. This is the `ComputeBackend` pattern from the Docker spike, generalised.

**Runtime choice: Pyodide, not WebVM.** WebVM/CheerpX is 32-bit-only, has no kernel
(no Docker), and runs CPython as an emulated x86 binary (5–10× slower). Pyodide is
Python compiled straight to WASM — lighter and purpose-built. (See the WebVM-vs-x86
analysis.)

---

## 1. Goals / non-goals

**Goals:** run the AWS/GCP/Azure API + IAM + data-semantics simulator entirely in a
browser tab; zero install; offline; persists across refresh; shares ≥90% of code
with the appliance.

**Non-goals (explicit fidelity cuts):** real compute (EC2/VM/docker-in-VM);
external SDK/CLI/Terraform access (an in-browser app is not a reachable endpoint);
DB wire-protocol clients; multi-process realism; the real-backend conformance harness.

---

## 2. Architecture

```
┌──────────────────────────────── browser tab ───────────────────────────────┐
│  SPA  static/*.html  (REUSED 100%)  ── fetch('/api/..') ──┐                 │
│                                                           ▼                 │
│  Service Worker:  asset cache  +  fetch⇄ASGI router ──►  Pyodide Worker     │
│                                                          │                  │
│                                   server.py (FastAPI, REUSED)               │
│                                   │  ServiceBackend adapters (lite impls)   │
│            ┌──────────────────────┴───────────────────────────┐            │
│            ▼                ▼               ▼                   ▼            │
│   PGlite (WASM PG)   cedar-wasm (IAM)  in-proc Py stores   WebCrypto (KMS)  │
│            │                                │                               │
│            └──── persistence ──►  OPFS / IndexedDB  ◄───────┘               │
└──────────────────────────────────────────────────────────────────────────-─┘
```

Layers:
- **SPA** — unchanged static assets; compute-only screens feature-gated off.
- **Service Worker** — caches the app shell for offline; intercepts `/api/*` and
  forwards to the Pyodide worker; everything else served from cache.
- **Pyodide worker** — runs `server.py` as an ASGI app; the fetch⇄ASGI shim turns
  one HTTP request into one `app(scope, receive, send)` cycle (no socket needed).
- **Backends** — the four delegation points + the in-proc services (§4).
- **Persistence** — OPFS for blobs/sqlite, IndexedDB for PGlite + JSON snapshots.

---

## 3. Reuse vs adapt vs build (the honest inventory)

| Reuse as-is (~90%) | Adapt behind the seam | Delete / stub for Lite | Build new |
|---|---|---|---|
| SPA (`static/*.html`) | `core/cedar_engine.py` → cedar-wasm | LXD/multipass funcs, `runtime_bridge.py` | Pyodide bootstrap + worker |
| FastAPI routes/handlers | `core/gcp_sql_engine.py` → PGlite/SQLite | compute screens (feature-gate) | Service worker + fetch⇄ASGI shim |
| `STATE` model (289 refs) + `app_context.py` | `core/minio_mirror.py` → OPFS blob store | `uvicorn[standard]` (→ ASGI shim) | `ServiceBackend` interfaces + `*Lite` impls |
| pydantic models, boto3 shapes | crypto (`cryptography`) → cryptography-in-Pyodide/WebCrypto | 11 docker-compose services | JS bridges (PGlite, cedar-wasm) |
| business logic / validation | eventing/PubSub/Firestore → in-proc | the launcher (`scripts/cloud-learn`) | persistence snapshotter; build pipeline |

---

## 4. Backend mapping (summary; full table in IN-MEMORY-PLAN.md)

PGlite (RDS-PG) · SQLite-WASM (RDS-MySQL, **not H2**) · moto (DynamoDB+S3+SQS,
pure-Python) · OPFS blob (S3/GCS bytes) · in-proc Python (Pub/Sub, Firestore,
NATS eventing, KV secrets) · cedar-wasm (IAM/RBAC — same engine as today) ·
cryptography/WebCrypto (KMS) · in-memory state machine (compute metadata only).

---

## 5. Request path (how Python serves the SPA with no server)

1. SPA `fetch('/api/s3/buckets')`.
2. Service worker matches `/api/*` → `postMessage` to Pyodide worker.
3. Worker builds an ASGI `scope`, runs `await app(scope, receive, send)`, collects
   status/headers/body.
4. Worker posts the response back; service worker returns it as a `Response`.
Streaming/large bodies (S3 multipart) handled by chunked `http.request`/`http.response.body` events.

---

## 6. Persistence & lifecycle

- **PGlite** → IndexedDB (native).
- **STATE / app sqlite** → OPFS (maps 1:1 to `.cloudlearn_state.sqlite3`).
- **S3/GCS blobs** → OPFS.
- **in-proc stores** (dynamo/sqs/pubsub/firestore/KV) → debounced JSON snapshot to
  IndexedDB; rehydrate on boot. **Repoint `_persist_state` to this sink.**
- **User controls:** Reset (clear OPFS/IDB), Export/Import workspace (download/upload
  a snapshot bundle) — turns the volatility limitation into a feature.

---

## 7. Build & packaging

- Output = a **static site** (`vyomi.cloud/lite` or a downloadable single-page bundle).
- Pyodide runtime + selected wheels (fastapi, pydantic, boto3, moto, cryptography,
  sqlite) bundled; PGlite + cedar-wasm as JS/WASM assets.
- App code (`server.py`, `core/`, `providers/`) shipped as a Python package loaded
  into Pyodide; lazy-load per-provider modules to cut cold-start.
- Versioned alongside the appliance from the same tag (no separate release train).

---

## 8. Roadmap (phased, each phase has an exit criterion)

| Phase | Scope | Exit criterion |
|---|---|---|
| **P0 — shell spike** | Pyodide + FastAPI + fetch⇄ASGI + SPA + **S3 in-proc only** | SPA loads in a tab and lists/creates an S3 bucket, no server |
| **P1 — AWS core** | S3(OPFS) · DynamoDB(moto) · SQS · IAM(cedar-wasm) · RDS(PGlite) | AWS console fully usable offline |
| **P2 — GCP** | GCS · Pub/Sub · Firestore · Cloud SQL · IAM | GCP console parity |
| **P3 — Azure + KMS/Secrets + eventing** | Azure services · WebCrypto KMS · KV · in-proc bus | all 3 consoles green |
| **P4 — persistence + perf** | OPFS/IDB snapshot+rehydrate · bundle/startup tuning · Reset/Export/Import | survives refresh; cold start acceptable |
| **P5 — distribution** | static deploy, offline PWA, docs | shippable `vyomi-lite` |
| — | compute screens feature-gated OFF throughout | — |

---

## 9. Risk spikes (cheap, high-signal — do before committing P1)

1. **moto imports in Pyodide** (transitive dep tree) — gates the AWS plan.
2. **PGlite↔Python async bridge** perf for many small queries — gates RDS fidelity.
3. **Pyodide bundle size + cold start** (~6–10 MB + wheels) acceptable on target devices.
4. **fetch⇄ASGI shim** streaming/large bodies (S3 multipart upload).
5. **cedar-wasm vs cedarpy API parity** so `cedar_engine.py` swaps via adapter only.

P0 (the shell spike) covers #3 and #4 and is the single highest-signal step.

---

## 10. Decisions to confirm

1. **One codebase + `VYOMI_BACKEND` switch** (recommended) vs a separate Lite fork.
2. **Pyodide** (recommended) vs a JS/TS rewrite of the API layer.
3. **MVP surface** — AWS-only first (recommended), or all three providers.
4. **Persistence scope** — full snapshot/rehydrate in MVP, or ephemeral-then-add.
5. **Distribution** — hosted at `/lite`, downloadable PWA, or both.

---

## 11. Effort (rough)

P0 ≈ days (proves/kills the approach). P1 ≈ 2–4 weeks. P2–P3 ≈ 4–8 weeks.
P4–P5 ≈ 2–4 weeks. The seam refactor (extracting `ServiceBackend`) is the long
pole and benefits the appliance too (it's the same seam the LXD→Docker move needs).
