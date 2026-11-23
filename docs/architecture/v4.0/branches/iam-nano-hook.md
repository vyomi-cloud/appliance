# v4/iam-nano-hook (WP nano-hook)

Runs the SAME faithful-IAM engine, API and gate inside the browser build (Nano) that Mesh runs, with identical routes, settings document, audit record shape and denial shapes. Contract: `IAM-ENGINE-CONTRACT.md`. Mesh side: `v4/iam-enforce-mesh` (modes/audit/gate/api, read from that ref; not merged here).

## 1. How Nano receives calls, and where the hook sits
```
SDK / CLI / Terraform --> relay (Cloudflare or local vyomi-tunnel) --WS--> relay SharedWorker (wasm/relay/relay-shared-worker.js)
                                                                        handle(reqJson) -> _handle -> AwsWireRouter.ahandle        [PATH A]
v4 console (React) --fetch BASE/_wire/<native path>--> sw.js handleWire --runInPage(["_wire","wire",M,{...}])--> page nano-boot.js
                                                                        adispatch0 -> wasm/providers/wire_adapter.ahandle -> AwsWireRouter   [PATH B]
v4 console / legacy console --fetch BASE/api/<svc>/...--> sw.js route() --> runInPage([prov,svc,op,params])--> adispatch -> _disp0 -> providers.dispatch -> console adapters -> cores   [PATH C]
```
Both A and B end in `core/aws_wire_router.AwsWireRouter` (all three clouds' native REST: S3 REST, X-Amz-Target JSON, Query XML, GCP REST, Azure data plane) over the one shared registry `core/nano_registry.get()`. Azure ARM `/subscriptions/*` rides a separate tuple `("azure","_arm",...)` into `AzureArm`.

Chosen hook points (JS decides, Python decides only when needed):
| Path | Hook | Why there |
|---|---|---|
| A relay (SDK/CLI, all clouds) | `relay-shared-worker.js` `handle` wrapper -> `nano-iam-hook.guardWire` | The request is complete (method, path, query, headers incl. Authorization, base64 body) and not yet dispatched; a denial is returned in the same `{status,headers,body}` frame the relay already sends, so no relay/Worker change. |
| B `/_wire` (console + in-page SDK) | `nano-boot.js` `adispatch0` `_wire` branch (same `guardWire`) | The service worker only forwards. Putting the hook in the page keeps `sw.js` untouched for gating (the SW is the fragile part) and reuses the page's Pyodide. A denial = the `{status,headers,body_b64}` `wire_adapter` would have returned. |
| `/api/iam/*` | `sw.js route`: 8 guarded lines, `startsWith("/api/iam/")` -> `runInPage(["_iam","api",...])`; `nano-boot adispatch0` `_iam` -> `NanoIamHook.api` | Same routes/bodies as Mesh `routes/iam_enforcement.py`. |
| C console adapters (`/api/<svc>/...`) | **designed, not wired**: `adispatch0` before `dispatch(prov,svc,op,params)` | Console adapter ops (`prov,svc,op`) are not wire requests, so `map_*` cannot map them; gating needs an op->action table per adapter. Mesh does not gate them either (`gate.INTERNAL_PREFIXES` skips `/api/`, console traffic is admin), so skipping them keeps behaviour identical. If it is ever wanted, it needs a `console_ops` table owned by the opmap WPs. |
| Azure ARM tuple `("azure","_arm")` | **designed, not wired**: `adispatch0` for `svc=="_arm"` | The tuple carries no headers/credentials (console and SDK are indistinguishable), so there is no principal. Needs the SW to pass `Authorization`; then `guardWire` works unchanged. |

Credential-less requests are never gated (console traffic), identically to Mesh. Principal = access key (AWS SigV4/presigned/SigV2) or Bearer claims (GCP/Azure) via `core/iam_state_adapters.py` (Mesh WP; the same functions), bound to Nano's registry stores (`iam`, `gcp_iam`, `az_arm.state`).

## 2. Per-cloud status (wired vs designed)
| | Settings + `/api/iam` + audit | Wire hook (JS + bridge) | Verified in browser |
|---|---|---|---|
| AWS | wired | wired (SigV4 / presigned / SigV2 detection) | S3 prototype, real gate/modes/audit/api, STAND-IN map/evaluator/adapters |
| GCP | wired (cloud-generic) | wired (Bearer, non-ARM path -> gcp; `x-goog-*`) | not run: needs `map_gcp`/`gcp_eval` (other WPs) |
| Azure | wired (cloud-generic) | wired for data plane and `/_wire/subscriptions` (Bearer or `x-ms-version`); ARM tuple path designed | not run: needs `map_azure`/`azure_eval` |
| Console adapter path | n/a | designed (see above) | n/a |
Cloud detection (`nano-iam-hook.js cloudOf`) is a JS heuristic over credentials; an ambiguous Bearer request is routed to gcp unless the path is ARM/data-plane. Wrong detection is harmless: the cloud's gate simply maps nothing and (mode-dependent) records `unmapped`.

## 3. Off is free; lazy loading
- Per-space settings (`iam-enforcement:<cloud>` in the shared `nano-spaces` IndexedDB `meta` store; same document as Mesh) are cached in JS and kept fresh over a BroadcastChannel. With every level `off`, `guard()` is one resolved-promise await + a property scan: measured 0.16 us/request, **0 Python calls, 0 engine fetch, 0 catalog fetch** over 20,302 requests (asserted by the e2e).
- Only when a level is `audit|enforce`: the engine is mounted once into the Pyodide FS from `core/iam_engine/manifest.json` (engine modules + host adapters, written by `wasm/build_cores.py`), then each service catalog (`core/iam_catalog/<cloud>/<service>.json`, incl. `gcp/_methods.json` when generated) is fetched on first use and cached in IndexedDB keyed by the manifest digest. Boot loaders list neither (tested). Catalogs are 4.1 MB total; a request touches the few KB it needs.
- Python cannot await `fetch`, so the bridge answers `{"need":[[cloud,service]]}` (from `CatalogUnavailable`, an `OSError` on `iam_catalog/...json`, or the services of the mapped permissions); JS prefetches, `preload()`s and calls again (max 6 rounds). `core/iam_engine/catalog_loader.py` : `load(cloud, service)` with an injected reader (Mesh `filesystem_reader`, Nano memory reader fed by `preload`).
- Failure policy: gate unavailable/crashed -> fail open, except fail CLOSED (503) when any level of that cloud's document is `enforce`.

## 4. Files
`core/iam_engine/catalog_loader.py`, `core/iam_engine/nano_bridge.py` (IamApi per cloud over a JS-backed settings store and a shared-ring audit log; `check` with `bypass=lambda: False`, because `gate.INTERNAL_PREFIXES` includes `/console` and would skip a bucket named `console-*`), `wasm/nano-iam-hook.js`, `wasm/build_cores.py` (vendors `core/iam_engine/*.py`, `core/iam_catalog/**`, `core/iam_state_adapters.py`/`iam_state_nano.py` when present; `--check` verifies byte-identity), generated `wasm/core/iam_engine/**` + `wasm/core/iam_catalog/**`, edits: `wasm/nano-boot.js` (+8 lines), `wasm/relay/relay-shared-worker.js` (+9), `wasm/sw.js` (+8), tests `tests/conformance/test_iam_nano_hook.py`, `wasm/ui-tests/iam/{iam-hook-e2e.mjs,standin/*}`.

## 5. Measurements (Chrome stable, headless, Pyodide 0.26.2, N=300; engine: REAL gate/modes/audit from enforce-mesh + STAND-IN map_aws/aws_eval/adapters, 3 identity policies, S3 only)
| | per request |
|---|---|
| hook, space off | 0.16 us, 0 Python calls |
| decision (JS guard -> bridge.check -> map -> evaluate -> audit record), allow | p50 0.12 ms, p95 0.17 ms |
| decision, deny (incl. XML denial) | p50 0.125 ms, p95 0.185 ms |
| first request after turning enforcement on (engine mount + s3 catalog fetch) | 8 - 68 ms, once |
| SDK GET end-to-end through SW (noise dominated: 62-107 ms) | off p50 70.7 / enforce p50 94.9; alternating 100-call rounds: off 107.5, 77.8 vs enforce 84.1, 77.8 |
The decision is far under the few-ms target; the end-to-end difference is within run-to-run noise (SW + bridge dominate). **These use stand-in map/evaluator**: the real AWS engine (full SCP/boundary/condition evaluation, 4,463-action catalog) and real state building will cost more; re-run `iam-hook-e2e.mjs` once the real modules are vendored (it uses them automatically). `state` is rebuilt per request from the stores (adapters); a large IAM store makes that the likely hot spot (cache by store version if it shows).

## 6. Tests
`tests/conformance/test_iam_nano_hook.py` (9): package imports with fastapi/socket/sqlite3/requests/boto3... blocked in a fresh interpreter and `os.environ` wiped (+ AST scan), importing imports no catalog, lazy loader/reader, bridge need->allow->deny->audit shape with the real gate from the ref, `/api/iam` routes via real `IamApi`, vendor byte-identity. `wasm/ui-tests/iam/iam-hook-e2e.mjs` (18 checks, Chrome): off path, enforcement/audit/catalog/evaluate API, allow/deny/audit/explicit deny, console traffic ungated, denied request never reaches the core, audit-mode, resource-level override, reload persistence.

## 7. Open issues
- `iam_state_adapters.py`, `map_*`, `*_eval` are not on this branch; the bridge imports them lazily and reports `{"error": ...}` (fail open unless enforce). After the merge, `python3 wasm/build_cores.py` vendors them; nothing else changes. `wasm/service-inventory.json` does not exist on this base: `vyomi.simulated` is reported `null`.
- Relay SharedWorker hook is syntax-checked and shares `guardWire`, but was not run in a browser (the e2e covers the page `/_wire` path); `relay/nano-endpoint.html` (tab variant) is not hooked.
- Audit ring is shared by last-writer-wins IndexedDB writes (1000 records) plus BroadcastChannel merges; two contexts writing within 300 ms can drop a record's persistence (not its live view).
- `gate.check` converts a `CatalogUnavailable` raised inside the engine/map into an error record (fail-closed in enforce). The bridge pre-flights the mapping and the mapped services' catalogs to avoid that; an engine that lazily loads a catalog the mapping did not name would be denied on first use.
- `gate.is_internal` prefixes (`/console`, `/_`) would skip legitimate S3 bucket paths on Mesh (bucket `console-x`); Nano bypasses the prefix check by design.
- Pre-existing failures before this branch: `test_nano_core_manifest.py` (aws_governance_core.py vendored but not loaded by nano-boot.js), `test_nano_embed.py` (needs boto3).
