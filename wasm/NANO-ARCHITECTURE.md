# Vyomi Nano — Architecture

> Single source of truth for the **Nano free tier**.
> Status: design **locked 2026-06-26**. All 7 AWS cores + Azure ARM proven green
> (host CPython + Pyodide). Cloudflare relay **DEPLOYED & live at relay.vyomi.cloud**
> (+ a brew-installable local tunnel, auto-detected). See `relay/README.md` and
> `../docs/guides/nano-tunnel.md`.

---

## 1. Core goal (the north star)

A developer uses the simulator to **test their EXISTING cloud-native application
and validate its business logic** — pointing *unmodified* native SDKs / CLIs / IaC
at the sim, with **no false greens** (see the native-SDK-conformance principle).

Everything below serves that goal at **zero install and near-zero cost**.

---

## 2. What Nano *is* (definition)

> **Vyomi-Nano ≡ Vyomi-Lite's conformance handlers + a WASM/in-memory
> `BackendProvider`, packaged to run in the browser (Pyodide).**

- **Same handlers, same conformance contract as Lite.** NOT a fork (ADR-001).
- Only the **backend substrate** differs:
  - **Lite** → Docker backends (MinIO, Azurite, Vault, DynamoDB-Local, Postgres…).
  - **Nano** → in-WASM backends (in-memory ObjectStore, PGlite, WebCrypto, cedar-wasm…).
- The Nano **"container"** = the browser **bundle** (Pyodide + handlers + in-WASM
  backends + SPA) — the WASM analogue of Lite's docker-compose stack.
- **No compute** (`vm:0`, exactly like Lite).
- **The guarantee:** the *same conformance suite* must pass on BOTH substrates
  (Lite/Docker AND Nano/WASM). That contract is what stops Nano ever being a
  JS-stub false green.

---

## 3. Tier model

| Tier | Substrate | Compute | External apps reach it? | Cost to us | Price |
|---|---|---|---|---|---|
| **Nano (free)** | WASM in browser | none | via local bridge ($0) **or** cloud relay | ~$0 | free |
| **Nano relay (paid)** | WASM in browser + Cloudflare relay | none | cloud relay (zero install) | near-$0 (no egress) | ~₹299-499 / $4-6 |
| **Lite** | Docker, conformance-only | none | real socket | hosting | ladder |
| **Pro / Max** | Docker / VM | **real (EC2/containers)** | real socket | hosting | ladder |

The paywall is **convenience (no-install relay)** and **capability (real compute)** —
NOT "comprehensive testing," which is free via the local bridge.

---

## 4. Component architecture

```
┌──────────────────────── browser tab (the user's machine, free compute) ─────────────────────────┐
│  SPA console  ──fetch /api/*──▶  service worker  ──▶  Pyodide                                     │
│  (aws/gcp/azure consoles)         (transport)         ├─ conformance handlers (the REAL Lite code)│
│                                                       └─ in-WASM BackendProvider (the swap table) │
│        ▲ outbound wss (register)                                                                  │
└────────┼──────────────────────────────────────────────────────────────────────────────────────-─┘
         │
   ┌─────┴──────────────────────────────┐        the external app (host OS), unchanged:
   │  CONNECTIVITY (see §5)              │  ◀────  aws --endpoint-url <relay-or-localhost> s3 ls
   │  Cloudflare relay  OR  local bridge │        boto3(endpoint_url=…) · terraform · your service
   └────────────────────────────────────┘
```

- **SPA console** — the real `static/{aws,gcp,azure}-console.html`, served verbatim
  (`wasm/` build). Resources/configs are authored here (metadata only).
- **Pyodide** — CPython→WASM. Runs the **real** appliance handlers (proven: pydantic
  2.7 incl. its Rust core loads in Pyodide; FastAPI/Starlette load with a version pin).
- **Conformance core** — `core/s3_object_core.py` etc.: handler logic extracted to be
  substrate-free (no `socket`/`subprocess`/`uvicorn`/`boto3` at import).
- **BackendProvider seam** — `core/object_store.py`: the data-plane swap point.
- **In-WASM backends** — the swap table:

| Lite backend (Docker) | Nano backend (WASM) | Status |
|---|---|---|
| MinIO (S3) | in-memory `ObjectStore` (→ OPFS) | ✅ done |
| DynamoDB-Local | `NoSqlStore` | ✅ done |
| Azurite (Blob/Queue) | `ObjectStore`/`QueueStore` (azure ns) | pattern ready |
| Vault (KMS) | `KmsEngine` (stdlib AEAD; WebCrypto later) | ✅ done |
| Vault (Secrets/KV) | `KvStore` | ✅ done |
| Postgres/MySQL (RDS) | `SqlStore` (stdlib sqlite3; PGlite later) | ✅ done |
| NATS (eventing) | `MessagingStore` (SQS + SNS pub/sub fan-out) | ✅ done |
| Cedar (IAM) | `AuthzEngine` (Python IAM-JSON eval; cedar-wasm later) | ✅ done |

**Repeatable pattern:** extract handler → seam → in-WASM backend → same conformance
suite green on host CPython **and** Pyodide.

---

## 5. Connectivity — how an EXTERNAL app reaches the in-browser sim

**The fixed constraint:** an existing app is an external process talking HTTP/TCP.
A browser tab **cannot accept inbound TCP**. So *something* must provide the socket
and relay to the tab. The tab connects **outbound** (WebSocket — allowed); the relay
provides the inbound socket. Two deliveries, **sharing one tab-side WS protocol**:

### 5a. Primary: Cloudflare cloud reverse-tunnel (zero install)
- Tab opens `wss://relay.vyomi.cloud/register`; external app hits
  `https://relay.vyomi.cloud/<session>`. (Detail in §6.)
- **Zero install** for the user; **near-free** for us (Cloudflare = no egress fees +
  WebSocket hibernation). This is the default for the no-install experience.

### 5b. Alternative: local bridge (`brew install vyomi-nano-bridge`)
- A tiny binary that **serves the Nano bundle from `http://localhost:9000`** AND
  relays external HTTP → the tab over `ws://localhost`.
- Because page + relay + external app are **all `localhost`**, every browser-sandbox
  issue (mixed-content, PNA, CORS) **disappears**.
- **$0 to us, fast (no cloud hop), private (nothing leaves the machine), offline-capable.**
- Bundle delivery: fetch-and-cache from vyomi.cloud (small binary, auto-current) or
  ship-in-binary (fully offline / air-gapped).
- The right default for **developers** (one `brew` command is no real friction).

---

## 6. The Cloudflare relay (detail)

**Worker** (HTTP entry) + **Durable Object** (one per session, holds the tab's WS):

```
tab → wss://relay.vyomi.cloud/register → Worker → Durable Object(<session>) holds WS
external app → https://relay.vyomi.cloud/<session>/... → Worker → that DO
            → forward over WS → tab (WASM) → response → back to the app
```

- **Cost lever:** **DO WebSocket Hibernation** — idle tab connections aren't billed
  for wall-clock → hold thousands of connected-idle tabs cheaply. Plus Cloudflare's
  **no egress fees**. → near-free until real volume.
- **Request correlation:** DO assigns a request-ID; sends `{id, request}` over WS;
  tab replies `{id, response}`; DO resolves the matching pending promise (handles
  concurrent in-flight calls).
- **External app config:** `aws --endpoint-url https://relay.vyomi.cloud/<session>`
  (+ path-style for S3). Handlers don't enforce SigV4 → the **unmodified SDK/CLI works**.

---

## 7. Browser sandbox & security

WebSocket is one of the few APIs **exempt from the Same-Origin Policy** — a
`vyomi.cloud` tab may open a cross-origin `wss://` to the relay. No CORS, no prompt.
Implications (config + server-side, not hard blocks):

| Concern | Handling |
|---|---|
| Mixed content | relay serves **`wss://`** (Cloudflare TLS) |
| CSP | list relay in `connect-src 'self' wss://relay.vyomi.cloud` |
| Origin spoofing | **validate `Origin: https://vyomi.cloud`** on the WS handshake (server-side) |
| Auth | **token** (URL/first message) — NOT cookies (3rd-party cookie blocking) |
| Cross-origin isolation (Pyodide threads/SAB) | **WS is exempt from COEP** → no conflict |
| Private Network Access | **N/A for the cloud relay** (public host). *Only the local bridge would hit PNA — which is why the bridge serves the bundle from localhost (§5b).* |
| Background-tab throttling | keepalive ping/pong + "keep this tab active" UX (reliability, not security) |

**Net:** the cloud relay AVOIDS the two worst sandbox traps (mixed-content-to-localhost,
PNA) that the naive local approach hits. Security-wise it's the *easier* path.

---

## 8. Cost & pricing

- **Compute:** $0 — runs in the user's browser.
- **Local bridge:** $0 to us (user's machine does everything).
- **Cloud relay:** near-$0 on Cloudflare (no egress + hibernation); a heavy user is
  mostly small JSON calls → ~$1-3/mo of relay if uncapped. **Cap payloads** (Nano is
  for logic/conformance, not bulk data).
- **Pricing:** comprehensive testing is **free** (local bridge). Charge for the
  **no-install cloud relay** (~₹299-499 / ~$4-6/mo; value play $9-19 vs LocalStack
  ~$35) and for **real compute** (Pro/Max).

---

## 9. Status (what's built)

- ✅ **S3 conformance core** — `core/object_store.py` (seam) + `core/s3_object_core.py`
  (real handler logic, substrate-free) + `tests/conformance/test_s3_core.py`
  (**33 checks GREEN on host CPython AND Pyodide**). Branch `feat/wasm-conformance-backend`.
- ✅ **DynamoDB conformance core** — `core/nosql_store.py` (seam) + `core/dynamodb_core.py`
  (real `_ddb_*` handler logic, substrate-free) + `tests/conformance/test_dynamodb_core.py`
  (**45 checks GREEN on host CPython AND real Pyodide**). Native JSON wire (X-Amz-Target
  dispatch, typed attribute values, KeyConditionExpression begins_with/BETWEEN,
  AttributeUpdates + SET, Batch*, `__type` errors). Same repeatable pattern as S3.
- ✅ **Pyodide feasibility de-risked** (5 spikes): pydantic 2.7 (Rust core) + Starlette
  load in-browser; direct-ASGI invocation works; blockers were dep-pinning only.
- ✅ **Nano SPA / consoles** — real aws/gcp/azure consoles served from `wasm/`
  (splash→dashboard→console flow, headless-validated). See `wasm/README.md`.
- ✅ **Cores wired into the Nano console SW** — `wasm/providers/aws_core_adapter.py`
  (the in-browser analogue of the Pro/Max FastAPI adapter) serves the console's
  **S3 + DynamoDB + KMS + Secrets + SQS + IAM + RDS** data-plane from the PROVEN
  cores; the JS stub is retired. The adapter translates console REST ↔ each core's
  native wire (S3 method+path, DDB/KMS/Secrets/SQS X-Amz-Target JSON, IAM/RDS Query
  +XML). Cores vendored into `wasm/core/` by `wasm/build_cores.py` (15 modules,
  copy-not-fork, byte-identical). Validated under real Pyodide loading the bundle as
  `nano-boot.js` does (**55 checks**: real ETags, versioning, typed DDB items,
  query/scan, KMS key+alias lifecycle, secret CRUD, SQS send/receive/in-flight, IAM
  user CRUD, RDS instance lifecycle stop/start/delete + endpoint). RDS control plane
  is wired without loading sqlite3 (data plane lazy-loads it). Caught + fixed a latent
  dispatch bug (JSON booleans embedded as Python source) and an RDS delete adapter
  bug (re-reading the just-deleted instance lost the `deleting` status).
- ✅ **KMS conformance core** — `core/kms_keystore.py` (KeyStore + KmsEngine crypto
  seam) + `core/kms_core.py` (real handler logic, substrate-free) +
  `tests/conformance/test_kms_core.py` (**36 checks GREEN on host CPython AND real
  Pyodide**). Native JSON wire (TrentService.* dispatch, KeyMetadata, base64
  Plaintext/CiphertextBlob, Decrypt recovers KeyId from the blob, GenerateDataKey,
  KeyState enforcement, aliases, `__type` errors). Crypto is REAL but stdlib-only
  (HMAC-SHA256 keystream + encrypt-then-MAC) so it runs in WASM with no native
  `cryptography`/openssl dep; a WebCrypto AES-GCM engine can swap in behind the seam.
- ✅ **Secrets Manager conformance core** — `core/kv_store.py` (KvStore seam) +
  `core/secrets_core.py` (real handler logic, substrate-free) +
  `tests/conformance/test_secrets_core.py` (**32 checks GREEN on host CPython AND
  real Pyodide**). Native JSON wire (secretsmanager.* dispatch, ARN/VersionId,
  SecretString/SecretBinary, AWSCURRENT/AWSPREVIOUS stages, get by stage or
  VersionId, scheduled deletion + restore, `__type` errors). Canonical-wire upgrade
  over the thin appliance handler (UUID VersionIds + real version stages).
- ✅ **RDS conformance core** — `core/sql_store.py` (SqlStore seam + a REAL SQL
  engine: stdlib sqlite3) + `core/rds_core.py` (control plane + data plane,
  substrate-free) + `tests/conformance/test_rds_core.py` (**29 checks GREEN on host
  CPython AND real Pyodide**). Native RDS Query protocol with XML
  (CreateDBInstance/Describe/Modify/Delete/Start/Stop/snapshots, endpoint+port,
  `<ErrorResponse>`) PLUS a real SQL data plane — CREATE TABLE/INSERT/SELECT
  actually run, per-instance isolated, gated by instance state. sqlite3 is a
  **loadable Pyodide package** (`pyodide.loadPackage("sqlite3")`), so the core
  lazy-imports it and the bundle loader must load it before SQL runs; a PGlite/
  Postgres-wire engine swaps in behind the seam for unmodified-psycopg2 later.
- ✅ **IAM conformance core** — `core/iam_store.py` (IamStore seam + AuthzEngine
  decision seam) + `core/iam_core.py` (control plane + evaluator, substrate-free) +
  `tests/conformance/test_iam_core.py` (**28 checks GREEN on host CPython AND real
  Pyodide**). Native RDS-style Query protocol with XML (users/roles/policies/groups,
  attach/detach, inline policies, access keys, `<ErrorResponse><Code>NoSuchEntity>`)
  PLUS REAL policy evaluation via SimulatePrincipalPolicy — the appliance's own
  pure-Python IAM-JSON evaluator (explicit-deny-wins across all statements, wildcard
  action/resource, conditions, group-inherited policies), not a stub. cedarpy (Rust)
  won't load in WASM; a `cedar-wasm` engine swaps in behind the AuthzEngine seam.
- ✅ **Messaging/eventing conformance core** — `core/messaging_store.py` (MessagingStore
  seam, with a controllable clock for visibility timeouts) + `core/sqs_core.py`
  (faithful SQS port, JSON wire) + `core/sns_core.py` (greenfield SNS, native Query/XML
  wire) + `tests/conformance/test_messaging_core.py` (**32 checks GREEN on host CPython
  AND real Pyodide**). SQS: send/receive + visibility-timeout hide & auto-redeliver +
  delete-by-ReceiptHandle + ChangeMessageVisibility + purge. SNS: topics + subscriptions
  + REAL **fan-out** (Publish delivers the SNS envelope into the subscribed SQS queue —
  the canonical SNS→SQS pub/sub pattern, the WASM analogue of NATS). SNS was greenfield
  (the appliance lacks it) but targets the native SNS wire.
- ✅ **Swap table COMPLETE** — every Lite backend now has a proven in-WASM equivalent,
  each gated by a shared conformance suite green on host CPython AND real Pyodide.
- ✅ **Relay serves ALL 7 services** — `core/aws_wire_router.py` is the native-AWS-wire
  front door: it inspects each relayed request the way a real cloud front-end does
  (SigV4 credential scope → `X-Amz-Target` → Query `Action`) and dispatches to the
  owning proven core in its native wire (S3 method+path; DynamoDB/KMS/Secrets/SQS JSON;
  IAM/RDS/SNS Query+XML), SNS+SQS sharing one MessagingStore for fan-out. Substrate-free,
  proven by `tests/conformance/test_aws_wire_router.py` (**22 checks GREEN on host CPython
  AND real Pyodide**). The relay tab (`wasm/relay/nano-endpoint.html`) loads it; the
  production Worker (`wasm/relay/worker.js`) is hardened (6 MiB payload cap, 64 in-flight
  cap, 20 s tab timeout, alarm-based keepalive ping, supersede-stale-tab on reconnect).
  So an UNMODIFIED SDK/CLI (`--endpoint-url <relay>/<session>`) is served by the SAME
  logic the conformance suite proves, for every service — not just S3. **Proven in a
  REAL browser** (headless Chromium, `wasm/relay/e2e-relay.mjs`): external HTTP client
  → local relay → browser tab (Pyodide + router + all cores) → response across all 7
  services + the in-tab SQL bridge, with PGlite (real Postgres) loaded in the tab.
- ✅ **RDS engine swap → PGlite (real Postgres), the first browser-side engine swap** —
  `core/sql_store.py` gains `PGliteSqlStore` (Postgres compiled to WASM) behind the
  UNCHANGED `SqlStore` seam, plus an additive ASYNC data plane (`SqlStore.aexecute_sql`
  + `rds_core.aexecute_sql`, sharing the sync path's instance-state gate — no
  divergence). PGlite is async, so the swap proves the **async-engine pattern**: the
  seam stays sync by default (sqlite3, green on host+Pyodide), and an async browser
  engine overrides only `aexecute_sql`. Gives genuine Postgres dialect/wire — `$1`
  placeholders, SERIAL, RETURNING, ILIKE, real types — that sqlite can't match, so an
  unmodified Postgres-SQL app validates faithfully. Proven by
  `tests/conformance/test_rds_pglite_core.py`: the async contract is GREEN on the
  sqlite3 default (host + Pyodide), and `run_pglite()` confirms REAL Postgres
  (PostgreSQL 18.3) on the Pyodide+PGlite substrate. The browser binds it via
  `wasm/pglite-loader.js` (installs `globalThis.__nano_pglite_new`); the relay tab
  exposes an in-tab async SQL bridge (`window.__nano.sql`) for the RDS Data-API /
  in-browser apps. (Key enabler: Pyodide can `await` host async APIs — verified.)
- ✅ **RDS Data API over the relay** — `core/rds_data_core.py` serves the
  `boto3.client('rds-data')` rest-json wire (Execute / BatchExecute / transactions,
  AWS-typed field values, named `:params` rewritten to the engine's placeholder via
  `SqlStore.param_placeholder`) onto the SqlStore data plane. This is the ONE
  relational path that survives the HTTP relay (Postgres-wire TCP can't), so an
  unmodified external app runs real SQL against the in-browser engine. It's async, so
  the router gained `AwsWireRouter.ahandle` (serves rds-data async, delegates every
  sync service to `handle`); the relay tab's request handler is now async. Proven by
  `tests/conformance/test_rds_data_core.py` (Execute/BatchExecute, typed records,
  isNull, error mapping → GREEN on sqlite3 host+Pyodide AND PGlite real-Postgres), and
  **end-to-end in a real browser** (`e2e-relay.mjs` step 8: external ExecuteStatement →
  relay → tab → PGlite → typed records, reading a row the in-tab bridge inserted —
  proving one shared engine). Transactions are accepted/well-shaped but autocommit (no
  cross-call rollback yet) — documented in the core.
- ⬜ `vyomi-nano-bridge` local binary (shares the WS protocol).
- ⬜ Remaining browser-engine swaps are OPTIONAL fidelity upgrades (the pure-Python
  defaults already conform): WebCrypto AES-GCM behind `KmsEngine` (async; zero
  conformance gain over the stdlib AEAD engine), cedar-wasm behind `AuthzEngine` (needs
  an IAM-JSON→Cedar layer — the Python IAM-JSON evaluator is already more faithful).

---

## 10. Honest boundaries

- **What Nano validates:** API / SDK / CLI / data-plane conformance + business logic,
  for the console and for apps that can run in-browser (Python + pytest/boto3 today;
  Java/Go via CheerpJ/Go-WASM later), AND — via the relay/bridge — **external apps on
  the host OS** pointing their SDK at the tunnel endpoint.
- **What it does NOT do:** real **compute** (no actual EC2/containers — that's Pro/Max);
  apps that won't fit a browser runtime when run in-tab (full Spring Boot, native deps)
  must use a reachable endpoint (relay/bridge → handlers, fine) or Pro/Max.
- **Tab liveness:** the WASM tab must stay open + connected for the relay/bridge to
  serve. Mitigated by keepalive; inherent to free in-browser compute.
- **Relay is HTTP, not raw TCP:** the relay forwards HTTP, so HTTP-based SDKs (boto3,
  aws-cli, **RDS Data API**) work end-to-end — `boto3.client('rds-data')` runs real
  SQL against the in-browser engine over the relay (proven). A native Postgres-wire
  client (psycopg2 over TCP) can't traverse the HTTP relay — real Postgres (PGlite) is
  reachable in-browser and over the RDS Data API, not the bare 5432 wire. Bare-wire DB
  access is a Pro/Max concern (a real reachable Postgres).

---

## 11. Roadmap

1. ✅ Wire the proven **S3 + DynamoDB cores** into the Nano console SW (visible
   in-browser conformance — the console data-plane now runs the real cores).
2. ✅ **Cloudflare relay — DEPLOYED & live at `relay.vyomi.cloud`.** `aws --endpoint-url
   https://relay.vyomi.cloud/<session> ...` is served by the in-browser cores for ALL 7
   services (native-wire router). Worker + SQLite Durable Object on a Custom Domain;
   validated end-to-end against the live edge via `e2e-relay.mjs`. A brew-installable
   **local tunnel** (`vyomi-tunnel`) is auto-detected and preferred, with dynamic
   failover to cloud. (Proves the core goal: external app ↔ in-browser sim, $0.)
3. ✅ Extend the **swap table** (DynamoDB ✅ → Vault/KMS ✅ → Vault/KV ✅ → RDS ✅ → IAM ✅ →
   NATS/eventing ✅) — COMPLETE; each gated by the shared conformance suite on both
   substrates. ✅ All cores now wired into the console SW (55-check Pyodide validation).
   The browser-side engine swaps — WebCrypto/PGlite/cedar-wasm — remain future work
   behind their seams.
4. `vyomi-nano-bridge` local binary (offline/private power users).
5. Pricing + funnel wiring (free local-bridge → paid relay → Pro/Max compute).

---

*Related: `wasm/README.md` (the in-browser substrate + console build), ADR-001
(single codebase, tier-as-substrate, never fork), the native-SDK-conformance principle
(green must be real on every substrate).*
