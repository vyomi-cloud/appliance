# v4/iam-mesh-gcp-azure

Owner: this session - Base: origin/v4/iam-faithful (d4b716218) - Status: GCP + Azure proven on the real app (in-process, starlette TestClient)

## Purpose
Prove and fix faithful-IAM enforcement for GCP and Azure on the real appliance app (`server.app`), as AWS already is (`test_iam_mesh_server_e2e.py`).

## What was wrong (live stores vs engine state shape)
- GCP `gcp_state` passed `{"policies": {project: policy}, "bindings": []}`; the engine reads `allow_policies {attachment_point: policy}`, `deny_policies`, `custom_roles`, `hierarchy`. Every non-root principal was implicitly denied. Now built from the v4 IAM core slot (`gcp_iam_policies`, `gcp_deny_policies`, `gcp_custom_roles`) merged over the pre-v4 `gcp_iam_state` view; `projects/_` (Cloud Storage's global namespace) is parented to the space's project so project bindings inherit to buckets/objects.
- Azure `azure_state` read `azure_app_context.azure_state_dict()` (a slot nothing writes) and passed raw ARM records (`properties.principalId`); the engine reads flat `principal_id/role_definition_id/scope`. Now reads the live ARM map (`providers.azure_services._state`, resolved as the azure provider), flattens role assignments, passes custom role definitions / deny assignments, and merges the `azure_iam_core` RBAC slot (allow + `kind: deny`).
- Azure data plane: map resources are `/<account>/<container>/<blob>`, `/vaults/<v>/..` (not ARM ids), so no subscription/RG-scoped assignment could ever cover them. New `state["data_scopes"]` (account/vault/namespace/cosmos/appconfig name -> ARM resource id) and `azure_eval._ancestors` inherit data actions from the ARM resource.
- `gate.required_permissions` dropped the query string and host for Azure (so `?comp=list` blob listing mapped to containers/read) and the host for GCP; now passes both (falls back for maps that predate the kwargs).
- Azure maps have no `service` field, so per-service overrides never matched; the gate now uses the provider namespace (`Microsoft.Storage`) as the service key.
- A request with no identity (no `X-Cloudlearn-Principal`, bearer claim, or `active_principal`) is `root`; the engines have no root concept so it was denied. Same rule as AWS now: root bypasses unless `unknownPrincipal: "deny"`.
- `/api/iam/<gcp|azure>/evaluate` built state outside a request, so the provider-scoped stores resolved to the empty AWS space; `state_and_principal` now sets the request provider.
- IAM v2 deny-policy API: the server regex/handler only accepted a one-segment attachment point, but ASGI hands the handler the DECODED path (`cloudresourcemanager.googleapis.com/projects/p`), so `POST /v2/policies/.../denypolicies` returned the S3 405. Router regex + `gcp_iam_core.dispatch` fixed.
- `map_gcp`: `/download/storage/v1/...` and `/v2/policies/{ap}/denypolicies[/id]` (-> `iam.denypolicies.*`) were unmapped (fail-closed 403 in enforce).

## Tests (run with `PYTHONPATH=.:core CLOUDLEARN_TIER_ENFORCE=0 /Users/sudhirganti/Applications/simulator/portal-run/.venv/bin/python -m pytest -p no:cacheprovider`)
- `tests/conformance/test_iam_mesh_gcp_e2e.py`: allow policy via real `setIamPolicy`, enforce/audit/off, per-service off, per-resource enforce, deny policy (v2 API), X-Cloudlearn-Principal and bearer-email principals, exact PERMISSION_DENIED shape, root + `unknownPrincipal: deny`, legacy `enforce_iam` flag, map shapes.
- `tests/conformance/test_iam_mesh_azure_e2e.py`: RG + storage account + role assignments through ARM, Reader/Contributor/Blob Data Reader, AuthorizationFailed shape, oid/appid bearer principals, scope isolation (sibling RG), audit, per-resource and per-service, `/evaluate` agrees with the gate, blob data actions via `/azure-data/blob`, legacy `enforce_rbac` flag.
Re-runnable: unique names, project policy restored, RG deleted, settings reset to off.

## Open
- Not gated at all on Azure (never reach the gate; not "unmapped"): `/openai/...`, `/azure-sql/...`, Graph `/v1.0/...`, `/oauth2/...` and the `/_wire/arm` form. GCP XML API path-style (`/bucket/object` on the simulator host) is routed as AWS S3.
- `testIamPermissions` maps to no permission by design (any caller).
- Data-plane tests cover blob only; queue/table/key vault/service bus/cosmos/app config maps exist but were not driven through the live app. Azure blob SAS/shared-key auth is not modelled by the gate (principal comes from X-Cloudlearn-Principal / bearer claims only).
- GCP allow-policy inheritance only knows project -> resources (no folder/org store); Azure management groups/PIM/group membership not fed from the stores.
- Not run on a deployed Mesh Codespace; in-process only (same app object, same middleware).
