# IAM engine contract (work packages share this; change it only with the integrator)

Design: `IAM-FAITHFUL-DESIGN.md`. Catalogs: `core/iam_catalog/{aws,gcp,azure}/` (verbatim vendor IDs).

## Package layout (`core/iam_engine/`, pure Python, Pyodide-safe, vendored to `wasm/core/iam_engine/` by `wasm/build_cores.py`)
| Module | Owner WP | Public API |
|---|---|---|
| `types.py` | integrator | `request(...)`, `decision(...)`, `MODES`, `LEVELS` |
| `aws_eval.py` | engine-aws | `evaluate(req, state) -> decision` ; `simulate(...)` helper shared with `SimulatePrincipalPolicy` |
| `gcp_eval.py` | engine-gcp | `evaluate(req, state) -> decision`, `test_iam_permissions(...)` |
| `azure_eval.py` | engine-azure | `evaluate(req, state) -> decision`, `check_access(...)` |
| `map_aws.py` | opmap-aws | `required(http_request) -> [{"action","resource","service","operation"}]` (SigV4 service from credential scope, `X-Amz-Target`, query `Action=`, REST path/verb; S3 virtual-host + path style; uses `core/iam_catalog/aws/*.json` `operations`) |
| `map_gcp.py` | opmap-gcp-azure | `required(method, url, body?) -> [{"action","resource","service"}]` (REST method + path -> permission, from the roles-permissions catalog + method tables) |
| `map_azure.py` | opmap-gcp-azure | `required(method, path, body?) -> [{"action","resource","data":bool}]` (ARM path+verb -> action; data-plane host/path -> dataAction) |
| `modes.py` | enforce-mesh | `resolve_mode(cloud, settings, service, resource_id) -> "off"|"audit"|"enforce"` (resource > service > space > global) ; settings CRUD helpers |
| `audit.py` | enforce-mesh | ring buffer of decisions (same record shape on Mesh and Nano) |
| `gate.py` | enforce-mesh | `check(cloud, http_request, state, settings) -> None | denial_response_spec` : map -> evaluate -> mode logic; fail-closed when mode=enforce, never raises into the caller in audit |

`state` is a plain dict the host builds from its stores (policies, roles, attachments, bindings, assignments, resource policies, tags); the engine never imports a store. Host adapters live outside the package (`core/iam_state_*.py`).

## Settings document (per space, persisted by the host)
```json
{"global": "off", "space": "off", "services": {"s3": "audit"}, "resources": {"arn:aws:s3:::my-bucket": "enforce"}}
```
Resolved most-specific-first: resource > service > space > global. Default everything `off`. Same document on all clouds (resource keys are the vendor resource names).

## HTTP API (Mesh and Nano, identical): `/api/iam/<cloud>/...`
`GET/PUT /api/iam/<cloud>/enforcement` (settings document) ; `GET /api/iam/<cloud>/audit?limit=` ; `POST /api/iam/<cloud>/evaluate` (body = request) -> decision (the effective-access view / Policy Simulator / Troubleshooter / checkAccess front end) ; `GET /api/iam/<cloud>/catalog/<service>` (catalog slice + `vyomi.simulated` flag).

## Error shapes when denying (enforce)
AWS: 403 `AccessDenied` / `AccessDeniedException` / EC2 `UnauthorizedOperation` per protocol (XML or JSON x-amz-json), message "User: <arn> is not authorized to perform: <action> on resource: <resource> ...". GCP: 403 `{"error":{"code":403,"status":"PERMISSION_DENIED","message":"Permission '<p>' denied on resource '<r>' (or it may not exist)."}}`. Azure: 403 `AuthorizationFailed` "The client '<oid>' with object id '<oid>' does not have authorization to perform action '<a>' over scope '<s>' ...".

## Rules for every work package
Own branch `v4/iam-<wp>` off `origin/v4/iam-faithful`; branch doc `docs/architecture/v4.0/branches/iam-<wp>.md`; push the branch at once and after each batch; **never push the trunk, main, tags or the portal**; never touch the :8099 server; no feature in a legacy view (rule 12): UI lives in `consoles/src/**`; permission IDs verbatim; no fastapi/socket imports in `core/iam_engine`; tests under `tests/conformance/test_iam_*.py` (run with `/Users/sudhirganti/Applications/simulator/portal-run/.venv/bin/python -m pytest -p no:cacheprovider`); only the files your WP owns (table above) plus your own tests; report what was verified vs not.

## Analysis APIs (native wire, Mesh and Nano; WP simulate-analyze, `branches/iam-simulate-analyze.md`)
Answered by the engine over the live state, with the vendor's own wire shape (no `/api/iam` indirection). Pure modules in `core/iam_engine/`: `analyze_aws.py` (simulate, context keys), `access_analyzer.py` (findings, policy checks, the REST service), `analyze_gcp.py`, `analyze_azure.py`, `analyze_wire.py` (route table + dispatch; the host injects state). Mesh: `core/middleware.py` -> `core/iam_analyze_host.py`; Nano: `wasm/nano-iam-hook.js analysisRoute/analyze` -> `nano_bridge.analyze`. Not gated (analysis, like `testIamPermissions`).
| Cloud | Route | Notes |
|---|---|---|
| AWS | IAM Query `SimulatePrincipalPolicy`, `SimulateCustomPolicy` | `core/iam_core.py` -> `analyze_aws.simulate` (aws_eval); EvaluationResults with EvalDecision, MatchedStatements{SourcePolicyId,SourcePolicyType,Start/EndPosition}, MissingContextValues, OrganizationsDecisionDetail, PermissionsBoundaryDecisionDetail; ContextEntries; ResourcePolicy/ResourceOwner/CallerArn |
| AWS | IAM Query `GetContextKeysForPrincipalPolicy`, `GetContextKeysForCustomPolicy` | condition keys + policy variables referenced, catalog casing |
| AWS | access-analyzer REST (SigV4 service `access-analyzer`): `PUT/GET /analyzer`, `GET/DELETE /analyzer/{name}`, `POST /finding`, `POST /findingv2`, `GET /finding/{id}`, `GET /findingv2/{id}`, `PUT /finding` (UpdateFindings), `POST /resource/scan`, `POST /policy/validation`, `POST /policy/check-no-new-access`, `POST /policy/check-access-not-granted` | shared analyzer store with the IAM-wire console view (`store.analyzers`); findings generated from resource policies fed by `core/iam_resource_policies.py`, role trust policies, the activity log and the decision ring |
| AWS | IAM `GenerateServiceLastAccessedDetails` / `GetServiceLastAccessedDetails` | now also folds the decision ring (allowed decisions; role sessions included) |
| GCP | `POST /v1/iam:troubleshoot`, `POST /v3/iam:troubleshoot` (policytroubleshooter) | v1 = allow policies only (as the real v1); v3 adds deny + principal-access-boundary explanations |
| GCP | `GET /v1/{projects\|folders\|organizations}/{id}:analyzeIamPolicy` (cloudasset) | identity / resource / access (roles, permissions) selectors, expandGroups / expandRoles, conditionEvaluation |
| Azure | `POST {scope}/providers/Microsoft.Authorization/checkAccess` with the native PascalCase body | bare JSON array response; the legacy lower-case body keeps the store's own handler (`{"value":[...]}`) |
| Azure | `GET {scope}/providers/Microsoft.Authorization/permissions` | effective permissions of the calling principal |
| Azure | `GET {scope}/providers/Microsoft.Authorization/roleAssignments?$filter=atScope()\|principalId eq '..'\|assignedTo('..')` | other filters / no filter: the store's own list |
| Azure | `GET {scope}/providers/Microsoft.Authorization/roleEligibilitySchedules[Instances]`, `roleAssignmentSchedules[Instances]` | from role assignments / `state["eligibility"]`; the store has no PIM records, so eligible lists are empty today |
