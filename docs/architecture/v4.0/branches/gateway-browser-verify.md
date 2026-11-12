# v4/gateway-browser-verify

Owner: gateway-browser-verify session - Started: 2026-11-12 - Base: origin/v4-on-main (2a48912d7) - Status: verification done, see open issues

## Purpose
Close the unverified parts of the Nano gateway-forwarding + event-bus work (docs/architecture/v4.0/GATEWAY-NANO-FORWARDING.md section 7, branch doc nano-gateway-forwarding.md).

## Architecture
- `wasm/relay/e2e-gateway-portal.mjs`: real Chromium on a LOCAL PORTAL (copy of the DB, throwaway CLOUDLEARN_STATE_DIR, vendored bundle via `vendor_to_portal.py --apply` into a scratch portal worktree).
  MODE=sw drives the console + service worker + in-page Pyodide (`/nano/_wire`); MODE=shared starts `relay-shared-worker.js` (SharedWorker) and calls it through the local relay.
  Both prove: API + config + gateway, real 2xx through the local relay backend map, 401 without a key, quota 200/200/429, unmapped refused (503), Eventarc retries advancing on API calls and dead-lettering to Pub/Sub.
- `wasm/relay/test-worker-gw-live.mjs`: hosted `/gw-egress` policy against the real `worker.js` under `wrangler dev` (workerd, local, nothing deployed): 19 checks.
- `packaging/tunnel/bin/*`: gateway egress ported into the packaged relay (see decisions).
- Hourly runner fixes (`tests/conformance/hourly/run_suites.py`, `suites.json`).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Port the gateway pieces into the packaged `vyomi-tunnel.mjs` by hand; copy mesh-cli.mjs + gw-egress*.mjs verbatim | Overwrite it with `local-relay.mjs` | There is NO sync script (the header "Re-sync: see header" points at itself) and the packaged copy is a deliberate fork (always signed in, lazy Mesh hub, no runner/LLM hubs). A whole-file copy would regress it. |
| Runner: a zero-total "(0 failed)" match falls through to PASS/FAIL line counting | Reword every test footer | Every `RESULT: PASS ... (0 failed)` suite was scored "NO CHECKS RAN" = red. Fixing the parser fixes all of them. |
| Portal e2e and wrangler-live registered as `pending` with the reason | Registering them as runnable | CI has no portal and no wrangler; pending shows in every run and cannot hide. |

## Open issues
- [ ] Eventarc `httpEndpoint` destinations cannot reach a real backend on Nano: `event_bus_engine.http_deliver` uses urllib, which fails in Pyodide ("unknown url type: https"). Retry + DLQ work; the bridge (`vyomiBackendFetch`) is not wired into event delivery (the bus is synchronous). (owner: next session)
- [ ] `packaging/tunnel` has no sync script; the fork can drift again. Decide on a generator or a drift test. (owner: tunnel session)
- [ ] CI cannot run the portal e2e or wrangler-live yet (pending entries). (owner: CI)
- [ ] test_capabilities sweep takes ~7 min by design (hundreds of test files, Playwright smokes); it does not hang. See the report for the remaining unrelated failures. (owner: -)
