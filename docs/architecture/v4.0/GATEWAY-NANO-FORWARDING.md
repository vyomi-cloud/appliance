# Gateway data plane on Nano: forwarding to a real backend (design spike, 2026-11-12)

Status: spike. Nothing here is built except the relay CORES fix in section 5. Scope: GCP API Gateway first (`core/gcp_apigateway_gateway.py`); the same
hook serves AWS API Gateway v2 (`apigatewayv2_gateway.py`) and Azure APIM (`azure_apim_gateway_core.py`) because they share the engine (blocker 1).

## 1. What works on Nano today, and what does not

The tab runs `AwsWireRouter` in Pyodide. `gcp-gateway-invoke` calls `gcpgw.handle(..., http_fetch=default_http_fetch())`, and `default_http_fetch()` returns
`None` on `sys.platform == "emscripten"`, so the gateway answers **503 "The backend cannot be reached from this runtime"** AFTER route match, API key / JWT checks
and quota. So on Nano: 404 / 401 / 400 / 429 are real, a proxied 2xx is not. (JWT also fails closed: `default_verify_sig()` is `None` on emscripten.)

## 2. Why the tab cannot just call the backend

- The Python engine is synchronous (`handle` -> `http_fetch(...)` returns a tuple). Pyodide is pinned to 0.26.2 (no `run_sync` / JSPI), so Python cannot block on a JS `fetch`.
  The async door exists: `AwsWireRouter.ahandle` (used by the relay worker, `relay-shared-worker.js` `_handle`) already awaits async services (RDS Data, `llm_core.arun`).
- A browser `fetch` from the tab is limited by CORS (the user's backend will not send CORS headers for `*.vyomi.cloud`), mixed content (https page -> http backend) and
  Private Network Access (page -> localhost / 192.168.x needs a user permission prompt). A user's real backend is typically `localhost:3000` or a dev server, so direct fetch is not viable.
- The only component that lives on the user's machine, has real sockets, and is already trusted by the tab is the local relay (`vyomi-tunnel`, `wasm/relay/local-relay.mjs`).
  It already does the reverse direction (external app -> relay -> WS -> tab) and one allow-listed outbound hop for the VMs (`/egress?u=`, `wasm/relay/egress.mjs`).

## 3. Recommended design (not built)

1. **Engine split** (`gcp_apigateway_gateway.py`, then the v2 / APIM handlers): `handle()` becomes `plan()` + `finish()`. `plan()` does route match, auth and quota and returns
   either a final response or a `Forward(method, url, headers, body, timeout, state)`; `finish(forward, status, headers, body)` shapes the response. The sync `handle()` keeps
   its signature (plan, call `http_fetch`, finish) so the appliance and every existing test are unchanged. Quota is counted exactly once, in `plan()`.
2. **Async hop in the router** (`aws_wire_router.ahandle`): for `gcp-gateway-invoke` call `plan()`; on a `Forward`, `await` a JS bridge `js.vyomiBackendFetch(forward)` and return
   `finish(...)`. Precedent: the `llm_core.arun` branch in the same function.
3. **JS bridge** (`relay-shared-worker.js`, next to `db-bridge.js`): POSTs the forward to the local relay `http://127.0.0.1:<port>/gw-egress` with the tunnel session token; the
   hosted relay (`relay.vyomi.cloud`) cannot reach the user's localhost, so without a local `vyomi-tunnel` the answer stays 503 with a message that names the fix.
4. **Relay route `/gw-egress`** (`local-relay.mjs`, mirrored in `worker.js` only for public backends): refuses anything not in an explicit **backend map** the user started the
   tunnel with. Config alias -> real origin, e.g. `vyomi-tunnel gateway-backend https://hello-abc123-uc.a.run.app=http://127.0.0.1:3000`. Requests whose
   origin is not in the map get 502 "backend not mapped" (never an open proxy, no private-IP access except mapped targets), and every call needs the existing tunnel credentials
   (`~/.vyomi/credentials`, decision 2026-11-10: every command needs a key). Public https backends may be reached unmapped only if the host passes an allow-list the user opts in to.
5. **Mesh / offline** need none of this: they run the same engine on a real network (`default_http_fetch`), and `VYOMI_GATEWAY_BACKEND_OVERRIDES` already offers the same alias idea server-side.

## 4. Effort and risks

Four touch points (engine split, router async branch, worker bridge, relay route + CLI subcommand) and a Nano e2e on :8099 with a real local backend. Estimate 1-2 days with
tests; it is not "small and safe" for this branch because it changes the shared engine used by three clouds and adds an authenticated egress surface to the relay (SSRF review needed).
Open decisions for the owner: (a) is a mapped-origin allow-list acceptable UX, or should mapped backends be declared in the gateway config (`x-vyomi-backend-local`)? (b) should the hosted relay
ever proxy public backends for Nano users without a local tunnel (cost + abuse), or is "Nano forwards only through a local vyomi-tunnel" the rule?
(c) PNA: Chrome 142+ prompts for page -> `127.0.0.1`; the existing relay path already has this and the memory note says to expect the prompt.

## 5. Found and fixed in this spike

`wasm/relay/relay-shared-worker.js` and `wasm/relay/nano-endpoint.html` (the loaders behind `vyomi-tunnel` / external SDKs) listed neither `gcp_apigateway_core.py` nor
`gcp_apigateway_gateway.py`, although `aws_wire_router.py` imports them at module level: `python3 wasm/build_cores.py` reported "RELAY CORES DRIFT ... will ImportError at browser boot".
Both lists now carry them (after `gcp_eventarc_core.py`, as in `nano-boot.js`); `build_cores.py` now prints "relay CORES lists are import-closed". This was NOT browser-tested here.

## 6. Test-only hook added on this branch

`VYOMI_GATEWAY_BACKEND_OVERRIDES="https://backend.rt.test=http://127.0.0.1:PORT"` (`core/gcp_apigateway_gateway.py` `default_http_fetch`): redirects calls for an exact
https origin to another origin, so the control plane's https-only rule stays intact and a loopback backend can be used by `gcp-v4-roundtrip.mjs`. Unset in production.
