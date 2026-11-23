# Faithful IAM for AWS, GCP and Azure (Mesh and Nano)

Status: design + Phase 0 started (AWS catalog generated). Branch `v4/iam-faithful`. Owner decisions marked **[assumed]** were not answered
explicitly; they are the recommended defaults and are cheap to flip.

## 1. Goal
Support each cloud's real permission model as-is for every service Vyomi simulates, and let the user switch enforcement on and off per
resource. A policy that works in Vyomi must work unchanged on the real cloud and vice versa.

## 2. State on trunk (2026-11-23)
| | AWS | GCP | Azure |
|---|---|---|---|
| Control plane | `core/iam_core.py` (3.4k lines) | `core/gcp_iam_core.py`, `gcp_iamcredentials_core.py` | `core/azure_iam_core.py` |
| Decision engine | `SimulatePrincipalPolicy` only | `core/gcp_iam_policy.py`: ~16 permissions curated | `checkAccess` (wildcards, notActions, deny, scope inheritance) |
| Request-time enforcement | none | opt-in per space (`enforce_iam`), fails open | opt-in per space (`enforce_rbac`), fails open |
No per-resource switch; the browser build (Nano) has no request-time hook.

## 3. Principles
1. **Permission IDs are verbatim and read-only** (`s3:GetObject`, `compute.instances.get`, `Microsoft.Storage/storageAccounts/read`). No renaming, no `vyomi:` prefix. Vyomi metadata sits beside the ID (the `vyomi` block: simulated, enforceable, catalogVersion). Vyomi's own control actions use a separate `vyomi:` namespace that cloud policies cannot reference.
2. **Generate catalogs from the vendors' data**, never type permissions by hand.
3. **One engine in pure Python** (no fastapi/socket imports, loads under Pyodide), shared by Mesh and Nano via `build_cores.py`; each cloud supplies its own semantics and catalog.
4. **One decision point per request**, per substrate; only the hook differs.
5. **Every new service extends IAM** through an onboarding gate (section 8).

## 4. Scope (the numbers are measured, not estimated)
In scope = the services in the v4 console registries (86 today: AWS 26, GCP 29, Azure 31; `wasm/service-inventory.json`, rule 13).
AWS: 37 IAM prefixes (the services plus the cross-service prefixes policies use) = **4,463 actions** in `core/iam_catalog/aws/`
(864 KB). GCP and Azure catalogs are Phase 0 work (sources below). The whole-cloud totals (~18k AWS, ~12k GCP, ~15-20k Azure) are
approximate; we ship only the in-scope slice and refresh it when a service is added. **[assumed]** Catalog = full vendor list for
in-scope services, each permission marked simulated or catalog-only; only simulated ones are enforced.

## 5. Catalog sources
- **AWS**: official Service Reference `servicereference.us-east-1.amazonaws.com` (JSON per service: actions, access level, data-plane flag, resource types + ARN formats, condition keys, and the **API operation -> authorized actions** map). Done: `scripts/gen_iam_catalog.py aws`.
- **GCP**: per-service permission and role pages under `cloud.google.com/iam/docs/roles-permissions/<service>` (roles -> permissions, launch stage) plus the REST discovery docs for method -> permission. Parser: next.
- **Azure**: `MicrosoftDocs/azure-docs` `articles/role-based-access-control/permissions/*.md` (provider operations incl. data actions) and `built-in-roles.md` (role definitions). Parser: next. **[assumed]** Entra ID directory roles / Graph permissions are out of the first release; Azure RBAC only.

## 6. Engine, per cloud (faithful semantics)
- **AWS**: explicit deny > SCP/RCP > permissions boundary > session policy > identity + resource policies (incl. cross-account); conditions (`StringLike`, `IfExists`, set operators, `aws:*`/service keys, tags, policy variables), `NotAction`/`NotResource`.
- **GCP**: allow policies with hierarchy inheritance (org > folder > project > resource), deny policies (win), principal access boundaries, CEL conditions, custom roles, groups.
- **Azure**: role assignments with scope inheritance, `actions`/`notActions`/`dataActions`, ABAC conditions, deny assignments, eligible (PIM-style) assignments.

## 7. Enforcement and toggles
- Setting `enforcement` = `off | audit | enforce`, resolved most-specific first: **resource > service > space > global**. **[assumed]** default `off` for existing spaces; `audit` logs "would deny" without blocking.
- Once on, denial is real (fail closed); fail-open stays only for `audit` and internal console traffic.
- Exact error shapes per cloud (AWS `AccessDeniedException`/`UnauthorizedOperation`, GCP 403 `PERMISSION_DENIED`, Azure `AuthorizationFailed`).
- Surfaces: API, CLI (`vyomi iam enforce ...`), and the v4 consoles (`consoles/src`, never the legacy views): per-resource/per-service control + an effective-access view (Policy Simulator / Policy Troubleshooter / `checkAccess`).

## 8. Mesh and Nano
Same engine and data. Hook: Mesh = `core/middleware.py`, one step before every handler; Nano = `wasm/nano-sw.js` / kernel before dispatch to the in-browser core. **[assumed]** Nano gets enforcement in the same release (the engine is shared); the hook is prototyped on S3 first because the service worker is the fragile part. Nano loads catalogs lazily per service; audit log is a local ring buffer in the same format.

## 9. Request -> permission contract (the big piece)
Each simulated API maps to one or more permissions + a target resource: AWS from the catalog `operations` map (done by the generator; per-service overrides for the wire quirks), GCP from REST method -> permission, Azure from ARM operation -> action. A conformance test fails if a service core exposes an API with no mapping.

## 10. Onboarding gate (every new service/feature enhances IAM)
A service is not done until: catalog slice generated (`gen_iam_catalog.py` prefix list), `permission_map` covers each API, IAM fixtures exist. CI fails on an unmapped API or a stale catalog. Coverage table generated for the console Home and this doc.

## 11. Phases
0 catalogs + contract (AWS catalog done) -> 1 AWS engine + S3/DynamoDB/SQS/SNS/KMS/Secrets/Lambda wiring -> 2 GCP and Azure engines (extend `gcp_iam_policy.py`, `azure_iam_core.py`) -> 3 remaining services in waves (compute/network, data, integration, AI/security) -> 4 surfaces (API/CLI/consoles) -> 5 proof (native-SDK allow/deny matrix in off/audit/enforce on both substrates, parity vs `console-captures`).

## 12. Risks
Nano service worker hook; per-request cost in Pyodide (budget a few ms, measure); per-resource enforcement needs tags and resource policies exposed by every store in one shape; AWS wire quirks (some operations authorize on a different action than their name).
