# Vyomi-Nano relay — external apps ↔ the in-browser sim

This is **step 4** of the Nano architecture (see `../NANO-ARCHITECTURE.md`): how an
**external application on the host OS** reaches the simulator running in a browser
tab. A browser tab can't accept inbound TCP, so it connects **out** over a
WebSocket and registers; the relay holds that WS and forwards external HTTP to it.

```
external app (aws-cli / boto3 / your service) ──HTTP──▶ relay ──WS──▶ Nano tab
        endpoint = <relay>/<session>                                  (Pyodide + real S3 core)
```

Both deliveries share **one WS protocol** (`nano-endpoint.html` is the tab side):
```
relay → tab : {id, method, path, query, headers, body(base64)}
tab → relay : {id, status, headers, body(base64)}
```

## Files
```
nano-endpoint.html  tab side — boots Pyodide, loads core/{object_store,s3_object_core}.py,
                    registers over WS, dispatches native-S3 requests to the REAL core
local-relay.mjs     dev/validation relay (Node + ws) — the stand-in for the Worker
worker.js           PRODUCTION relay — Cloudflare Worker + Durable Object (deploy-ready)
wrangler.toml       Cloudflare config (DO binding, ALLOWED_ORIGIN)
e2e-relay.mjs       headless proof: external client → relay → tab (real core) → response
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
Proves: external PUT/GET/LIST/DELETE (native S3 wire) served by the in-browser core —
the **core goal** (test an external client against the in-browser sim), no install on
the sim side beyond a tab.

## Deploy the production relay (Cloudflare)
```sh
cd wasm/relay
npx wrangler dev        # local miniflare — re-run e2e-relay.mjs against the dev URL
npx wrangler deploy     # to your Cloudflare account; route relay.vyomi.cloud → this Worker
```
Then the user's existing app, unchanged except the endpoint:
```sh
aws --endpoint-url https://relay.vyomi.cloud/<session> s3 ls    # + path-style for S3
```

## Notes
- **Cost:** Cloudflare = no egress fees + DO WebSocket hibernation → near-free at scale.
- **Guardrails:** `ALLOWED_ORIGIN` check on register; add a per-session token + payload
  caps + keepalive ping/pong before production (see NANO-ARCHITECTURE.md §7).
- **Local bridge** (`vyomi-nano-bridge`) is the same protocol with the relay on
  `localhost` — a drop-in offline/private alternative (TODO).
