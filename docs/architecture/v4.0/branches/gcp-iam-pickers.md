# v4/gcp-iam-pickers

Real-console IAM pickers in the v4 GCP console (consoles/src/gcp/services/iam-admin), fed by the verbatim catalog
`core/iam_catalog/gcp/*.json` via `GET /api/iam/gcp/catalog/<svc>` (Mesh `/_wire/...`, Nano `/nano/_wire/...`).

- `catalog.js`: loads all 38 slices once, merges 477 roles / 8082 permissions; role search (title, id, description, permissions); permission property filter (`service:storage`, `status:`, `role:`, free text).
- `cel.js`: JS mirror of the engine CEL subset (gcp_eval.py grammar, allowed functions/methods) + builder <-> CEL sync.
- `pickers.jsx`: RolePicker (popup: Search, Top results, Currently used/Basic/All roles, product chips, Manage Roles), PrincipalPicker (stores + free typing), ConditionPanel (builder + editor), PermissionTable / AddPermissionsDialog, PermissionAutocomplete, ResourceAutocomplete.
- Wired into Iam.jsx (Grant access: multi roles, per-role condition, conditional bindings, version 3), CreateRole.jsx, RoleDetail.jsx (edit permissions), EffectiveAccess.jsx, Enforcement.jsx.
- Theme: MuiPopover/MuiPopper z-index 1500 so menus open above the side panels.
- Test: `consoles/tests/smoke-gcp-iam-pickers.mjs` (Playwright, Chrome channel, real catalog files served as the catalog route).

Known gaps: the catalog has no per-permission launch status (all show Supported); 8082 permissions vs 14524 in the real console;
27 catalog roles have no description (the id is shown instead); "Help me choose roles" links to docs (no assistant).
