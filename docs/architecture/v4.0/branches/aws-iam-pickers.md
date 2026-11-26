# v4/aws-iam-pickers

Branch from `origin/v4/aws-ux-refresh`. UI only, under `consoles/src/aws` (v4 AWS console).

## What it adds
- `kit/PermissionPicker.jsx`: `ServicePicker` (Commonly used, then Other, searchable), `ActionPicker`, `ResourceArnPicker`, `PermissionPicker`, `PrincipalPicker`, `useCatalog(s)` (one shared cache over `GET /api/iam/aws/catalog/<svc>`; answered in-browser on Nano).
- `kit/iamPolicy.js`: pure logic (visual model <-> IAM JSON, validation, wildcard expansion), unit-tested under node.
- `kit/iamServices.js`: prefix/name list generated from the `service`/`name` fields of `core/iam_catalog/aws/*.json` (37 services). Regenerate when a catalog is added.
- `kit/PolicyAttachTable.jsx`: searchable, type-filterable, paginated managed-policy table with checkboxes.
- `services/iam/PolicyEditor.jsx`: Visual editor (many statements, actions by access level, resources per catalog type, request conditions, status bar) and JSON editor (line numbers, Edit statement panel, catalog validation).
- Used by: CreatePolicy, PolicySimulator, EffectiveAccess, Enforcement, and the attach modals in UserDetail/RoleDetail/GroupDetail.

## Known gaps
- The catalogs have no per-action description text, so the action "Info" popover shows access level, resource types and condition keys (all verbatim from the catalog), not AWS prose.
- Visual editor cannot show NotAction/NotResource/Principal statements (stays in JSON with a notice).
- Policy-level checks are limited to what the catalog can prove (no IAM Access Analyzer style findings).

## Tests
- `node consoles/tests/iam-pickers-unit.mjs`
- `NODE_PATH=<playwright dir> SHOTS=<dir> node consoles/tests/smoke-aws-iam-pickers.mjs` (needs `node consoles/build.mjs --cloud aws` first)
- `consoles/tests/smoke-iam-ui.mjs` updated for the Effective access pickers.
