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

## Governance (hierarchies, org policy, guardrails) - branch `v4/iam-governance`
Real stores + read models for the org-level controls, same on Mesh and Nano (cores vendored by `wasm/build_cores.py`):
| Cloud | Native wire (writes) | Core | Engine state key(s) |
|---|---|---|---|
| AWS | Organizations JSON 1.1 (`AttachPolicy`, `DetachPolicy`, `CreatePolicy`, `EnablePolicyType`, `MoveAccount` ...), S3 `PutPublicAccessBlock` (bucket) / s3control (account) | `organizations_core` (attaches FullAWSAccess / RCPFullAWSAccess to every root, OU, account) | `scps`, `rcps` (levels), `s3_bpa` (account + per-bucket flags; `RestrictPublicBuckets` / `IgnorePublicAcls` enforced for anonymous / cross-account callers in `aws_eval`) |
| GCP | `GET /v2/{organizations\|folders\|projects}/{id}/constraints`, `POST\|PATCH\|DELETE /v2/{node}/policies[/{constraint}]`, `...:getEffectivePolicy`, `...:check` (Vyomi extension), resourcemanager v3 folders/projects | `gcp_orgpolicy_core` (catalog, inheritance merge, `dryRunSpec`), `gcp_resourcemanager_core`, `gcp_iam_core` | `hierarchy`, `deny_policies`, `pab_policies`, `pab_bindings` (existing) + org-policy enforcement hooks |
| Azure | `/providers/Microsoft.Management/managementGroups[/{id}[/subscriptions/{sub}]]`, `.../providers/Microsoft.Authorization/{roleAssignments,policyAssignments}` at MG scope | `azure_mgmt_groups_core` | `management_groups`, `subscriptions`, `role_assignments`, `deny_assignments` |

Read models (not native, console + tests): `GET|POST /api/iam/<cloud>/governance/<what>` served by `IamApi` -> `core/iam_governance.handle` (hosts: Mesh `routes/iam_enforcement.py`, Nano `nano-iam-hook`, dev server). `aws`: `organization`, `effective?account=`, `check` (POST), `settings` (POST `{scpAppliesToManagement}`), `s3-public-access`. `gcp`: `hierarchy?project=`, `orgpolicy?node=`, `orgpolicy/check` (POST), `iam-policies?node=`. `azure`: `hierarchy`, `effective?scope=`.

Semantics: AWS SCP/RCP = every level must Allow, a Deny anywhere wins, the management account is exempt unless the Vyomi lab opt-in `scp_apply_to_management` is on (all principals live in that one account). GCP org policy: boolean = nearest policy wins; list = `inheritFromParent` merges, `reset` ignores ancestors; `dryRunSpec` is evaluated separately and never enforced; conditional rules are stored, not evaluated. Azure MG: depth <= 6, 409 on delete with children, root group (id = tenant id) cannot be deleted, RBAC and Policy assignments at an MG apply to every subscription below it.

Known limits (kept honest in the UI): the GCP constraint catalog is a curated subset (~45), engine hooks exist only for service-account / key creation, `gcp.resourceLocations`, `storage.uniformBucketLevelAccess`, `storage.publicAccessPrevention` (bucket create); AWS `DescribeEffectivePolicy` (tag / backup) is not implemented; Azure GET of a missing MG answers 404 (real Azure can answer 403).

## Error shapes when denying (enforce)
AWS: 403 `AccessDenied` / `AccessDeniedException` / EC2 `UnauthorizedOperation` per protocol (XML or JSON x-amz-json), message "User: <arn> is not authorized to perform: <action> on resource: <resource> ...". GCP: 403 `{"error":{"code":403,"status":"PERMISSION_DENIED","message":"Permission '<p>' denied on resource '<r>' (or it may not exist)."}}`. Azure: 403 `AuthorizationFailed` "The client '<oid>' with object id '<oid>' does not have authorization to perform action '<a>' over scope '<s>' ...".

## Rules for every work package
Own branch `v4/iam-<wp>` off `origin/v4/iam-faithful`; branch doc `docs/architecture/v4.0/branches/iam-<wp>.md`; push the branch at once and after each batch; **never push the trunk, main, tags or the portal**; never touch the :8099 server; no feature in a legacy view (rule 12): UI lives in `consoles/src/**`; permission IDs verbatim; no fastapi/socket imports in `core/iam_engine`; tests under `tests/conformance/test_iam_*.py` (run with `/Users/sudhirganti/Applications/simulator/portal-run/.venv/bin/python -m pytest -p no:cacheprovider`); only the files your WP owns (table above) plus your own tests; report what was verified vs not.
