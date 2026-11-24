# v4/iam-gate-gaps

Owner: this session - Base: origin/v4/iam-faithful (1e8f127f5) - Status: Mesh proven on the real app (TestClient); Nano covered by unit tests only (no browser run)

## Purpose
Close the paths that never reached the faithful-IAM gate (listed under "Still open" in `iam-faithful.md`).

## Why each one bypassed the gate
The simulator serves all three clouds on one host. `core/middleware.py::_provider_api_alias` decided the cloud from the path prefix alone (`is_azure_native_path`: `/subscriptions`, `/azure-data/`; `is_gcp_native_path`: `/compute/v1/`, `/storage/v1/` ...). Everything else is "aws" and was handed to the AWS gate, which only gates SigV4/`X-Amz-Target` traffic. So:
- `/openai/...`, `/azure-openai/...`, `/azure-sql/...`, Graph `/v1.0|/beta`, `/oauth2/...` (Azure data planes / Entra with no `/azure-data` prefix) were "AWS, unsigned -> skip". Worse, the legacy always-on AWS action model (`_capability_middleware` -> `_iam_route_action_resource`) judged them as S3 calls for any non-root principal (`AccessDenied: principal ... has no attached policies for s3:GetObject`).
- `/_wire/arm/...`: `gate.is_internal` treated every `/_...` path as internal (`INTERNAL_PREFIXES` has `/_`), so a `/_wire/<native path>` handed to the gate directly was skipped. (On Mesh the wire middleware strips `/_wire` first, so `/_wire/subscriptions/...` was always gated; the `/arm` alias form did not exist.)
- GCP XML API (`/<bucket>/<object>`, host storage.googleapis.com or GOOG auth) looks exactly like path-style S3: routed as AWS, gated as AWS (or not at all).
- Nano: `nano-iam-hook.js::cloudOf` sent every Bearer request that is not `/subscriptions/...` to **gcp** (so `/openai/...` with a bearer token was judged by the GCP engine) and ignored `api-key`-only calls and Entra.

## What changed
| Piece | Change |
|---|---|
| `core/iam_engine/routing.py` (new, pure) | `classify(method, path, headers, query, host)` -> `{cloud, exempt, reason, host}`; `strip_wire` (`/_wire`, `/nano/_wire`, `/_wire/arm`, `/arm`). Evidence order: GCS XML (storage.googleapis.com host, `GOOG1`/`GOOG4` auth, S3-style signature with a `GOOG...` key, `X-Goog-*` query/headers) > signed AWS (an S3 bucket may be called `openai`) > Entra / Vyomi extension (exempt) > Azure data plane / ARM. A bare `Authorization: Bearer` is NOT GCP evidence (AgentCore MCP calls carry one). |
| `core/middleware.py` | AWS-looking requests go through `_iam_enforce_shared_path`: exempt -> no gate; azure/gcp -> that cloud's gate with that cloud's request provider (settings + stores are per provider); else AWS gate. The legacy AWS action model skips requests another cloud owns. GCS XML requests get host `storage.googleapis.com` so `map_gcp` (already has `_xml_storage`) maps them. |
| `core/iam_engine/map_azure.py` | `/openai`, `/azure-openai[/<acct>]`, `/azure-data/openai/<acct>`, `<acct>.openai.azure.com` -> `Microsoft.CognitiveServices/accounts/OpenAI/*` data actions (chat/completions, completions, embeddings, audio, images, models, deployments, responses, assistants, threads/messages/runs/steps, vector_stores, files, fine-tunes, evals, batches, moderations; all verified present in the catalog). `/azure-sql/servers/{s}[/databases/{d}[...]]` -> `Microsoft.Sql/servers[/databases]/read|write|delete`. `/_wire`, `/_wire/arm`, `/arm`, `/nano/_wire` prefixes are stripped before the ARM mapping. |
| `core/iam_state_adapters.py`, `core/iam_state_nano.py` | `data_scopes` for Cognitive Services accounts (`/cognitiveservices/<acct>`) and SQL servers (`/sql/<srv>`) so data actions inherit from the ARM resource; `/cognitiveservices/_` (account unknown) inherits from the subscription; `azure_openai_account()` resolves the account for the bare `/openai/...` the simulator serves (api-key -> account key, `/deployments/<d>` -> owning account, the only account). Nano's `azure_state` previously had no `data_scopes` at all (blob data actions did not inherit there either). |
| `core/iam_engine/gate.py` | `is_internal` strips the wire prefix first (a `/_wire/<native path>` is gated, `/_vyomi...` etc. stay internal); `_full_path` strips it too. |
| `core/iam_engine/nano_bridge.py`, `wasm/nano-iam-hook.js` | Nano: `routeOf()` mirrors `routing.classify` (a test runs both); exempt requests are never gated; GCS XML requests are gated as GCP; `api-key`-only OpenAI calls reach the Azure gate; the bridge sets the host / OpenAI account like Mesh. |
| `core/iam_engine/api.py` | `/evaluate` for a GCP/Azure principal of type `root` answers allowed (`owner_root`) unless `unknownPrincipal: deny`: the same rule as the live gate. |

## Entra is exempt (explicit, documented)
Microsoft Graph (`/v1.0`, `/beta`), `/oauth2/...` (token/authorize/devicecode/logout, with or without a tenant segment), OIDC discovery/JWKS and `/common/userrealm` are the identity plane. Azure RBAC authorizes Azure resources; directory access is Graph app roles/scopes (Entra is out of scope per the design). They are never gated and never audited. Cognito `/{poolId}/oauth2/*` is AWS and is not exempted by this rule. `/openai/vyomi/...` (Vyomi extension endpoints with no vendor permission) is exempt as well.

## The `root` would_deny finding
Not reproducible with default settings on the merged backend (the gate lets an unidentified / `root` caller through since the mesh-gcp-azure work; audit stays empty). It reproduces ONLY with `unknownPrincipal: "deny"` (every unidentified request, console reads of `roleDefinitions` included, is judged and would-denied: by design) and in `POST /api/iam/azure/evaluate` for `{"type":"root"}` (engine has no root concept -> implicit deny, while the live gate allowed). The second is fixed (see api.py row); the first is documented behaviour, covered by a test.

## Tests
`tests/conformance/test_iam_gate_gaps.py` (re-runnable: unique names, enforcement reset to off, resource group deleted): classifier cases; verbatim-ID map tests; `is_internal`; JS/Python classifier parity under node; the Nano bridge denying `/openai/...` with the exact data action; the real app through `starlette.testclient` for Azure OpenAI (both routes, Reader/Contributor denied, `Cognitive Services OpenAI User` allowed, audit, per-service off), Azure SQL, Entra exemption, the wire/ARM aliases, GCS XML (GCP error shape, GOOG1, audit) and S3 untouched, and the `root` finding.

## Open / not done
- Nano was NOT driven in a browser for these paths (unit + bridge tests only). Re-run the Nano Chrome e2e against `/openai` and GCS XML.
- `/api/projects/<id>/...` (Foundry project endpoint) and `/contentsafety/...` are classified Azure but `/api/` is console traffic on Mesh (skipped by the AWS gate) and Content Safety has no mapped permission yet (denied in enforce unless `allowUnmapped`).
- GCS XML with a bare OAuth bearer and no `x-goog-*` header on the simulator host is indistinguishable from other bearer traffic and is not detected. Google HMAC keys (`GOOG...`) are not mapped to IAM principals (the caller is the active principal / root).
- Azure SQL data plane has no vendor data action (T-SQL auth is SQL/Entra logins): it is mapped to `Microsoft.Sql` control-plane read/write/delete as a faithful approximation; `POST .../query` maps to `databases/read`.
- Not run on a deployed Mesh Codespace.
