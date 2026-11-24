# Branch v4/iam-engine-aws (WP engine-aws)

`core/iam_engine/aws_eval.py`: `evaluate(req, state) -> decision` and `simulate(...)` helper. Pure Python, stdlib only.

## Evaluation order
1. Explicit Deny in any applicable statement (identity, boundary, session, SCP, RCP, resource) -> `explicit_deny`.
2. RCP levels (resource account) and SCP levels (principal account): every level needs an applicable Allow (union within a level).
3. Root user (same account) -> allow after the above. Service / federated / anonymous principals: resource policy Allow only.
4. Same account: a resource policy naming the user ARN (user caller) or session ARN (assumed-role caller) grants alone, bypassing boundary and session policy. A grant by role ARN or `*` still needs boundary and session to allow. Account-root grants need an identity Allow. Otherwise identity Allow AND boundary AND session.
5. Cross account: (identity Allow AND boundary AND session) AND resource-policy Allow.
Decision extras: `missingContext` (condition keys referenced but absent), `failedLayer` (identity|boundary|session|scp|rcp|resource) on implicit deny. `matched` records `{source,id,effect,statement}` (`id` = `policyId#Sid-or-index`).

## State / request shape
`req.principal`: `{arn,type(user|role|root|federated|service|anonymous),account,tags,policies,boundary,session_policy,groups}` (policy entries: bare doc or `{id,document}`). Missing fields fall back to `state.principals[arn]`; groups resolve via `state.groups[name].policies`.
`state`: `account`, `scps` / `rcps` (list of levels, a level = list of docs; or `{account|"*": levels}`), `resource_policies{arn:doc}`, `resource_tags{arn:{}}`, `org_id`. Per-request overrides: `req.resource_policy`, `req.resource_account`, `req.resource_tags`, `req.context` (condition keys, case-insensitive; values scalar or list).
Auto keys: aws:PrincipalArn (role ARN for sessions), PrincipalAccount, PrincipalType, username, userid, PrincipalOrgID, PrincipalTag/*, ResourceTag/*, ResourceArn, CurrentTime (now unless given), TagKeys (derived from RequestTag/*).

## Conditions
All of String*/Numeric*/Date*/Bool/BinaryEquals/IpAddress/NotIpAddress (v4+v6)/Arn*/Null, `ForAllValues:`/`ForAnyValue:`, `IfExists`. Missing key: positive operators false, negated true, IfExists true, ForAllValues true, ForAnyValue false. Policy variables `${key}`, escapes `${*} ${?} ${$}`, in Resource and condition values.

## Helper for SimulatePrincipalPolicy
`aws_eval.simulate(principal, actions, resources, context, state, resource_policy, resource_account)` returns IAM-API shaped rows (allowed/explicitDeny/implicitDeny, matched, missing context). NOT wired into `core/iam_core.py` (left unchanged; existing behaviour differs in places, e.g. it lets a resource policy naming the caller ARN bypass the boundary for any principal and treats resource "*" loosely). Wiring is a follow-up for the integrator.

## Unverified / open (not guessed beyond this)
- `*` principal in a same-account resource policy: treated as a grant still limited by boundary/session; real AWS behaviour for boundaries here is unverified.
- Role-ARN grant bypass rules (boundary/session) follow my reading of the docs table; unverified against real AWS.
- SCP exemptions (management account, service-linked roles) not modelled; host should pass empty `scps` for those.
- Unknown policy variable leaves the literal text (never matches); real AWS may reject/behave differently.
- Numeric/Date NotEquals with unparsable values returns true (AWS would invalidate the policy).
- Multi-valued context key without a set operator: positive = any value matches, negated = no value matches (AWS says unreliable).
- Not modelled: VPC endpoint policies, ABAC session-tag transitivity, resource-control of KMS grants, service-specific implicit rules (e.g. KMS key policy requiring explicit principal), `aws:*` defaults beyond the list above, ARN-segment wildcard rules beyond per-segment `*`/`?`.
- Request resource `*` only matches Resource `*` (literal), as in AWS.
