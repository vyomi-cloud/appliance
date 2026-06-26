# Vyomi Nano — Architecture

> Single source of truth for the **Nano free tier**.
> Status: design **locked 2026-06-26**. S3 conformance core proven (27/27 green on
> host CPython + Pyodide). Remaining backends + the Cloudflare relay: to build.

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
| Vault (Secrets/KV) | `KvStore` | next |
| Postgres/MySQL (RDS) | PGlite / sql.js | planned |
| NATS (eventing) | in-memory pub/sub | planned |
| Cedar (IAM) | cedar-wasm | planned |

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
  (the in-browser analogue of the Pro/Max FastAPI adapter) serves the console's S3 +
  DynamoDB data-plane from the PROVEN cores; the JS stub is retired. Cores vendored
  into `wasm/core/` by `wasm/build_cores.py` (copy-not-fork, byte-identical). Validated
  under real Pyodide loading the bundle as `nano-boot.js` does (30 checks: real ETags,
  versioning, typed DDB items, query/scan). Caught + fixed a latent dispatch bug
  (JSON booleans embedded as Python source).
- ✅ **KMS conformance core** — `core/kms_keystore.py` (KeyStore + KmsEngine crypto
  seam) + `core/kms_core.py` (real handler logic, substrate-free) +
  `tests/conformance/test_kms_core.py` (**36 checks GREEN on host CPython AND real
  Pyodide**). Native JSON wire (TrentService.* dispatch, KeyMetadata, base64
  Plaintext/CiphertextBlob, Decrypt recovers KeyId from the blob, GenerateDataKey,
  KeyState enforcement, aliases, `__type` errors). Crypto is REAL but stdlib-only
  (HMAC-SHA256 keystream + encrypt-then-MAC) so it runs in WASM with no native
  `cryptography`/openssl dep; a WebCrypto AES-GCM engine can swap in behind the seam.
- ⬜ Remaining backends (~~DynamoDB~~ ✅ → ~~Vault/KMS~~ ✅ → Vault/KV → RDS/PGlite → IAM/cedar-wasm).
- ⬜ Cloudflare relay (Worker + Durable Object) + tab-side WS register/dispatch.
- ⬜ `vyomi-nano-bridge` local binary (shares the WS protocol).

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

---

## 11. Roadmap

1. ✅ Wire the proven **S3 + DynamoDB cores** into the Nano console SW (visible
   in-browser conformance — the console data-plane now runs the real cores).
2. **Cloudflare relay** MVP → `aws --endpoint-url <relay> s3 ls` returns a bucket
   created in the Nano tab (proves the core goal: external app ↔ in-browser sim, $0).
3. Extend the **swap table** (DynamoDB ✅ → Vault/KMS ✅ → Vault/KV → RDS → IAM), each
   gated by the shared conformance suite on both substrates.
4. `vyomi-nano-bridge` local binary (offline/private power users).
5. Pricing + funnel wiring (free local-bridge → paid relay → Pro/Max compute).

---

*Related: `wasm/README.md` (the in-browser substrate + console build), ADR-001
(single codebase, tier-as-substrate, never fork), the native-SDK-conformance principle
(green must be real on every substrate).*
