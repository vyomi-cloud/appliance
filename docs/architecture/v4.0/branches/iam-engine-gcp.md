# v4/iam-engine-gcp

Owner WP: engine-gcp. Files: `core/iam_engine/gcp_eval.py`, `tests/conformance/test_iam_engine_gcp.py` (75 cases).

## API
`evaluate(req, state) -> decision` and `test_iam_permissions(principal, resource, permissions, state, context=None) -> [granted]`; also `eval_condition`, `role_permissions`, `load_catalog`. State shape is in the module docstring (allow_policies, deny_policies, pab_policies/pab_bindings, custom_roles, groups, hierarchy, optional catalog).

## Order
PAB (principal outside eligible resources -> explicit_deny, matched source `pab`) -> deny policies (org/folder/project/resource; deniedPrincipals, exceptionPrincipals, deniedPermissions, exceptionPermissions, denialCondition) -> allow policies unioned over resource, folder, project, org. Conditional bindings that are false/unsupported appear in `matched` with effect `NotApplicable` and a `note`.

## CEL subset
Literals, `request.time`, `resource.name|type|service`, `== != < <= > >= && || ! in ?:`, `+ - * / %`, `startsWith endsWith contains matches size`, `has()`, `timestamp() duration()`, time getters (fixed `+HH:MM` offsets only). Anything else raises CelUnsupported -> condition not satisfied (allow does not grant). Runtime errors follow CEL short-circuit absorption, otherwise not satisfied.

## Decisions where Google behaviour is not verified (assumptions)
- Basic roles are NOT in the catalog as permission lists. owner = all catalog permissions; editor = all minus `*.setIamPolicy`, `iam.roles.*`, project delete/move, org admin, orgpolicy set; viewer = read-style verbs (get/list/search/export/...) plus getIamPolicy. These are approximations, not Google's exact lists.
- Deny permission names: `service.googleapis.com/resource.verb` with fnmatch wildcards, or bare `svc.res.verb`. The service-prefix -> FQDN map is `<prefix>.googleapis.com` with a few exceptions (resourcemanager->cloudresourcemanager, cloudsql->sqladmin, firebaseauth->identitytoolkit); other mismatches are possible.
- An unevaluable denialCondition applies the deny (fail closed); Google rejects invalid expressions at write time instead.
- PAB: only ALLOW rules, union across bound policies, no enforcement-state/DRY_RUN, no per-permission PAB support filtering; a PAB denial is reported as `explicit_deny`.
- Deleted custom roles and `stage=DISABLED` grant nothing. `deleted:` members never match. `projectOwner:/Editor:/Viewer:` resolved via the project's own policy bindings only.

## Open issues
Service-agent implicit grants, legacy bucket/object ACLs (uniform bucket-level access off), IAM v2 deny policy inheritance edge cases, named time zones, CEL macros (`exists`, `all`), tag-based conditions (`resource.matchTag`), `api.getAttribute`, workforce/workload pool attribute sets beyond simple prefix match, PAB policy versions/bindings conditions, resource-name aliases (project number vs id). Host adapter (state builder) is another WP.
