# v4/iam-enforce-mesh (WP enforce-mesh)

Enforcement machinery, HTTP API, CLI and the Mesh hook for faithful IAM. Contract: `IAM-ENGINE-CONTRACT.md`.

## Substrate-neutral (pure Python, `core/iam_engine/`, vendored to Nano by `build_cores.py`)
- `modes.py`: settings document, `validate`, `resolve_mode` (resource > service > space > global, default off; Azure resource ids case-insensitive), `set_mode`, `any_active`; injectable persistence: `MemorySettingsStore`, `HolderSettingsStore(holder_fn, persist)`. Anything with `get()` / `put(doc)` works (Nano backs it with IDB/OPFS).
- `audit.py`: `AuditLog` ring buffer (default 1000), identical record shape on both substrates; `default_log`.
- `gate.py`: `check(cloud, http_request, state, settings, engines=None, maps=None, audit=None, bypass=None)` -> `None | {status, headers, body, content_type}`. `http_request` = `{method, path, query, headers(lowercase), body, principal}`. off=skip; audit=evaluate+record `would_deny`, never blocks/raises; enforce=block, fail closed on engine/map error; unmapped: logged, allowed in off/audit, denied in enforce unless `settings.allowUnmapped`. Engines/maps are lazy-imported (`core.iam_engine.<cloud>_eval`, `map_<cloud>`).
- `api.py`: `IamApi(settings_store, state_fn, catalog_fn, inventory_fn, audit_log, engines, maps).handle(method, path, query, body) -> (status, json)` implements ALL `/api/iam/<cloud>/{enforcement,audit,evaluate,catalog/<service>}` routes.

## What the Nano side must call
1. Build `IamApi` once with a Nano settings store (get/put), a `state_fn(cloud)` that returns the engine state from Nano's in-browser stores, and `catalog_fn` (lazy fetch of `core/iam_catalog/...`). Route `/api/iam/*` from the service worker to `api.handle(...)`.
2. Before dispatching to a service core, call `gate.check(cloud, http_request, state, settings)`; if it returns a spec, respond with it. Principal resolution for Nano is Nano's to provide (`http_request["principal"]`).
`wasm/build_cores.py` must also vendor `core/iam_engine/{modes,audit,gate,api}.py` (not done here).

## Mesh-only (outside core/iam_engine)
- `core/iam_state_adapters.py`: principal resolution (AWS SigV4/SigV2/presigned access key -> user, or `extras["sts_sessions"]`; `X-Cloudlearn-Principal`; GCP/Azure header or unverified bearer claims) and `state` builders.
- `core/middleware.py`: `_iam_enforce` hook (AWS wire, GCP native, Azure native). Legacy `enforce_iam` / `enforce_rbac` flags map to space=enforce + allowUnmapped; legacy helpers still run (`_FALLBACK`) while the engine/map modules are not installed, so the hook is inert until the engine branches merge. Settings live in `space["iam_enforcement"]`.
- `routes/iam_enforcement.py` (FastAPI wrapper, registered in server.py with one try-block).
- CLI `cmd/vyomi/iam.go`: `vyomi iam enforce <cloud> [--service S|--resource R] <mode>`, `vyomi iam status`, `vyomi iam audit [cloud] [--limit N]`.

## Known gaps
Anonymous / unsigned AWS requests and console pages are not gated (hook requires an access key or x-amz-target). Mesh does not mint STS sessions today, so assumed-role principals resolve only if a host records `extras["sts_sessions"]`. No end-to-end middleware test with real engines (they are on other branches).
