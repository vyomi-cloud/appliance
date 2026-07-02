# Vyomi-Nano relay — external apps ↔ the in-browser sim

This is **step 4** of the Nano architecture (see `../NANO-ARCHITECTURE.md`): how an
**external application on the host OS** reaches the simulator running in a browser
tab. A browser tab can't accept inbound TCP, so it connects **out** over a
WebSocket and registers; the relay holds that WS and forwards external HTTP to it.

```
external app (aws-cli / boto3 / your service) ──HTTP──▶ relay ──WS──▶ Nano tab
        endpoint = <relay>/<session>                          (Pyodide + AwsWireRouter → all 7 cores)
```

The tab serves **all 7 services** (S3 · DynamoDB · KMS · Secrets · SQS · SNS · IAM ·
RDS) **plus the RDS Data API** (`boto3.client('rds-data')` → real SQL on the in-browser
engine). `core/aws_wire_router.py` inspects each forwarded request the way a real cloud
front-end does — SigV4 credential scope, then `X-Amz-Target`, then the Query `Action`
(and the rest-json path for Data API) — and dispatches to the owning proven core in its
native wire. Proven on host CPython AND Pyodide by
`tests/conformance/test_aws_wire_router.py` (22 checks) + `test_rds_data_core.py`. The
Data API is async (it awaits the SQL engine), so the tab routes through
`AwsWireRouter.ahandle`.

Both deliveries share **one WS protocol** (`nano-endpoint.html` is the tab side):
```
relay → tab : {id, method, path, query, headers, body(base64)}
tab → relay : {id, status, headers, body(base64)}
```

## Files
```
nano-endpoint.html      tab side (standalone) — boots Pyodide, loads all vendored cores +
                        aws_wire_router, registers over WS, dispatches to the REAL cores
relay-shared-worker.js  tab side (SharedWorker) — hosts the endpoint across navigation +
                        auto-detects local vs cloud tunnel and switches dynamically
local-relay.mjs         LOCAL tunnel (Node + ws) — brew-installable as `vyomi-tunnel`
worker.js               CLOUD tunnel — Cloudflare Worker + Durable Object (deployed)
wrangler.toml           Cloudflare config (DO + custom domain + ALLOWED_ORIGIN)
e2e-relay.mjs           headless proof: external client → relay → tab (real core) → response
```

## Validate locally (proven green)
```sh
# 1. serve the repo root so /core/*.py and /wasm/relay/*.html are reachable
python3 -m http.server 8000
# 2. start the local relay (needs the `ws` package; WS_PKG points at it)
WS_PKG=/path/to/node_modules/ws node wasm/relay/local-relay.mjs      # :8090
# 3. run the loop e2e (Playwright)
PW=/path/to/node_modules/playwright node wasm/relay/e2e-relay.mjs
```
Proves (in a REAL browser, headless Chromium): an external HTTP client validated
against the in-browser sim across **all 7 services** — S3 (PUT/GET/LIST), DynamoDB
(typed items), KMS (Encrypt→Decrypt), SQS (Send/Receive), IAM + RDS (Query/XML) —
**plus the in-tab SQL bridge running real Postgres (PGlite)**. The **core goal**
(test an external client against the in-browser sim), no install on the sim side
beyond a tab. A fully self-contained runner (starts its own static server + relay +
browser) lives in the session scratchpad as `e2e-browser.mjs`.

## Two tunnels — local + cloud, auto-selected

The Nano tab reaches a relay two ways and **prefers local, falling back to cloud**
automatically (see `../../docs/guides/nano-tunnel.md`):

| | Local tunnel | Cloud tunnel |
|---|---|---|
| Install | `brew install vyomi-cloud/tap/vyomi-tunnel` | none |
| Endpoint | `http://127.0.0.1:8090` | `https://relay.vyomi.cloud/<session>` |
| Impl | `local-relay.mjs` (this dir) | `worker.js` on Cloudflare |

Selection lives in `relay-shared-worker.js`: it probes the local relay's
`GET /health` every 15 s and switches either direction with no reload.

## Cloud relay (Cloudflare) — DEPLOYED & live at `relay.vyomi.cloud`

Deployed to the Vyomi Cloudflare account as a Worker + SQLite-backed Durable
Object, bound to a Custom Domain. `wrangler.toml` carries it:
`new_sqlite_classes=["RelaySession"]` (free-plan-safe), `[[routes]] pattern =
"relay.vyomi.cloud" custom_domain = true`, `ALLOWED_ORIGIN = "https://vyomi.cloud"`.

```sh
cd wasm/relay
npx wrangler deploy     # redeploy after changes (provisions the custom domain + cert)
npx wrangler dev        # optional: local miniflare — re-run e2e-relay.mjs against the dev URL
```
The user's existing app, unchanged except the endpoint:
```sh
aws --endpoint-url https://relay.vyomi.cloud/<session> s3 ls    # + path-style for S3
```
Validated end-to-end against the live edge with `e2e-relay.mjs` (all 7 services +
PGlite SQL bridge + RDS Data API). The cloud tunnel is gated to `https://vyomi.cloud`,
so it's usable once the Nano bundle is served from there; local dev uses the local
tunnel above.

## Notes
- **Cost:** Cloudflare = no egress fees + DO WebSocket hibernation → near-free at scale.
- **Guardrails (in `worker.js`):** `ALLOWED_ORIGIN` check on register; the unguessable
  `session` id is the bearer capability (like a share link); 6 MiB payload cap (413);
  64 in-flight cap per session (429); 20 s tab timeout (504); alarm-based keepalive ping
  so background-tab throttling can't silently drop the held WS; a fresh tab supersedes a
  stale one on reconnect. Hibernation API (drop in-memory state between requests) is the
  remaining cost optimization — see NANO-ARCHITECTURE.md §7.
- **Local tunnel** (`vyomi-tunnel`, `local-relay.mjs`) is the same protocol with the
  relay on `localhost` — a drop-in offline/private alternative, auto-detected and
  preferred over the cloud tunnel when running. `brew install vyomi-cloud/tap/vyomi-tunnel`.
