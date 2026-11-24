# v4/iam-engine-azure (WP engine-azure)

Base: `origin/v4/iam-faithful`. Files: `core/iam_engine/azure_eval.py`, `core/iam_catalog/azure/_roles.json`, `scripts/gen_iam_catalog.py` (new `azure roles` subcommand; `check()` now skips `_*` files), `tests/conformance/test_iam_engine_azure.py`.

## What it does
- `_roles.json`: 507 built-in roles (GUID, roleName, description, actions/notActions/dataActions/notDataActions, assignableScopes, category) taken verbatim from the JSON blocks in the per-category pages of `built-in-roles/*.md` in MicrosoftDocs/azure-docs. Owner / Contributor / Reader / User Access Administrator checked exact. Regenerate: `python3 scripts/gen_iam_catalog.py azure roles`.
- `evaluate(req, state)` / `check_access(state, principal_id, action, scope, data=...)`: deny assignments first (explicit_deny), then role assignments (scope inheritance incl. management-group chain, principal + transitive group match, PIM-eligible inactive unless `activated`, ABAC condition), per-role actions minus notActions, separate data plane (`req["data"]=True`), union across roles. State shape is in the module docstring.
- ABAC: ActionMatches, SubOperationMatches, @Resource/@Request/@Principal/@Environment, Exists/NotExists, String*/Numeric*/Bool*/Guid*/DateTime*/Ip* operators, ForAnyOfAnyValues/ForAllOfAnyValues/ForAnyOfAllValues/ForAllOfAllValues, AND/OR/!.

## Assumptions / not verified against real Azure (guesses recorded, not claimed)
- Missing attribute: every comparison is false (`!` then turns it true). Real Azure behaviour for Not* operators on absent attributes is unconfirmed.
- AND binds tighter than OR (conditions in the wild are fully parenthesised).
- Plain operator with a set RHS: any-match for positive ops, all-match for Not ops (undocumented convenience). Single-valued operator on a multi-valued attribute = false.
- ForAllOf* on an empty list is vacuously true; ForAnyOf* false.
- DateTime comparison is ISO string comparison (UtcNow supplied by the host in `context.environment`); no clock read inside the engine.
- Unparseable / unsupported conditions fail closed (grant not applied).
- Deny-assignment `excludePrincipals` honoured for group membership too; deny-assignment conditions are not evaluated; Everyone = 00000000-0000-0000-0000-000000000000.
- Custom-role `assignableScopes` is not enforced at evaluation time. Assignment expiry (`end` dates) is the host's job (it should drop expired rows / set `activated`).
- Role-definition-level conditions (a few built-ins ship with an ABAC constraint) are not in the docs JSON blocks and so not in `_roles.json`.
- Entra directory roles (Global Administrator etc.) are out of scope; `elevateAccess` is just an action string.
