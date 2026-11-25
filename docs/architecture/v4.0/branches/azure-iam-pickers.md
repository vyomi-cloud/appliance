# Branch v4/azure-iam-pickers: real Azure RBAC pickers

Provenance (read this first): the Azure "Access control (IAM)" blade and the Add role assignment, Add custom role, ABAC and Check access
flows were built from Microsoft's documentation, not from a real portal capture (the tenant has no subscription, so the blade could not be
captured). Only the **member picker widget** was matched against a real portal screenshot of the same widget (Entra "Add assignments":
info bar, Search with info icon, "N results found", All/Users tabs, Name/Type/Details table with avatar + checkbox, right pane
"Selected (n)" + Reset + "No items selected", blue Add). Blade chrome follows the Entra role blade screenshot. Not claimed: pixel parity
with the Azure RBAC blades.

Kit: `consoles/src/azure/kit/pickers/` - RolePicker, MemberPicker, ScopePicker, PermissionPicker, AbacBuilder, Fields (PrincipalField,
ActionField, ScopeField), AddRoleAssignmentWizard, AddCustomRoleWizard, DenyAssignmentDialog, data.js.

Data sources (no free text where a catalog/store exists): roles = `GET /api/iam/azure/catalog/_roles` (507 verbatim built-ins) + ARM custom
roleDefinitions; permissions = `GET /api/iam/azure/catalog/<Microsoft.Provider>`; members = Graph users/groups/servicePrincipals + ARM
user-assigned identities; scopes = ARM subscription > resource groups > resources. Provider search lists the 28 namespaces with a catalog
file (a constant in data.js; other names can be typed and answer "no catalog").

Wired into: ResourceIam (all service blades + resource groups), Subscription IAM page, deny-assignment add, Check access, Effective access.
Enforcement page has no free-text for catalog/store data (mode radios only), so it was left unchanged.

Assumptions / gaps:
- Role assignment PUT carries ARM fields (roleDefinitionId, principalType, condition, conditionVersion "2.0", description) plus `roleName`
  and `kind` because core/azure_iam_core.py resolves by roleName; that backend currently stores only principalId/role/scope/kind/denyActions,
  so condition, description and principalType are sent but NOT yet enforced/persisted server-side. Same for custom-role
  assignableScopes and deny-assignment name/description. (Backend work, not done here.)
- ABAC attribute list (Resource/Request/Environment) is from Microsoft's documented storage attributes; the Code view is generated and
  read-only; the evaluator subset is core/iam_engine/azure_eval.py. Principal (custom security) attributes are not offered.
- "Privileged administrator roles" = Owner, Contributor, User Access Administrator, RBAC Administrator, Privileged Role Administrator,
  or roles with `*` / Microsoft.Authorization write actions (documented set approximated).
- Deny assignments cannot be created in the real portal; Vyomi adds them (labelled).
- Blades sit above the Nano relay-tunnel bar (bottom 34px) via a body:has(#nano-foot) rule.
- Management groups are not in the scope tree.

Test: `consoles/tests/smoke-azure-iam-pickers.mjs` (Playwright, Chrome channel) against the built bundle with a mocked wire that serves
the real catalog files.
