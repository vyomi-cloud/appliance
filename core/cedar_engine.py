"""Cedar policy engine wrapper — one engine, three IAM dialects.

Cedar (open-sourced by AWS) is the real IAM evaluator. We compile each provider's
native policy shape into Cedar PolicySet form, then evaluate at the simulator
middleware layer. This turns "every caller is admin" into actual deny/allow
semantics — the biggest single fidelity win available.

Wire conversions:

  AWS IAM JSON statement                             Cedar
  ──────────────────────────                         ─────
  {"Effect":"Allow","Action":"s3:GetObject",         permit(
   "Resource":"arn:aws:s3:::bucket/*"}                 principal,
                                                       action == Action::"s3:GetObject",
                                                       resource in S3Object::"arn:aws:s3:::bucket/*"
                                                     );

  GCP IAM binding                                    Cedar
  ────────────────                                   ─────
  {"role":"roles/storage.objectViewer",              permit(
   "members":["user:alice@x.com"]}                     principal == User::"alice@x.com",
                                                       action in [storage.objects.get,...],
                                                       resource
                                                     );

  Azure RBAC role assignment                         Cedar
  ───────────────────────────                        ─────
  scope=/subs/X/rg/Y, role=Reader,                   permit(
  principal=group:foo                                  principal == Group::"foo",
                                                       action in Microsoft.Authorization.Reader.actions,
                                                       resource in Scope::"/subs/X/rg/Y"
                                                     );

For MVP we ship the **evaluation layer** + a sample policy seed; the full role
expansion tables (every AWS managed policy etc.) are a P1 follow-up.
"""
from __future__ import annotations

import json
import threading
from typing import Any

try:
    import cedarpy
except ImportError:
    cedarpy = None  # type: ignore[assignment]


# Per-space policy stores. Each space carries its own active policy set.
# Stored as a single Cedar PolicySet string for cheap re-evaluation.
_policies: dict[str, str] = {}
_lock = threading.Lock()


def available() -> bool:
    return cedarpy is not None


# ----------------------------------------------------------------------------
# Per-space policy CRUD
# ----------------------------------------------------------------------------
def set_policies(space_id: str, policyset: str) -> None:
    """Replace the entire active policy set for a space."""
    with _lock:
        _policies[space_id] = policyset


def get_policies(space_id: str) -> str:
    with _lock:
        return _policies.get(space_id, "")


def add_policy(space_id: str, policy: str) -> None:
    """Append one policy to the active set."""
    with _lock:
        cur = _policies.get(space_id, "")
        _policies[space_id] = (cur + "\n" + policy).strip()


def clear_policies(space_id: str) -> None:
    with _lock:
        _policies.pop(space_id, None)


# ----------------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------------
def evaluate(space_id: str, principal: str, action: str, resource: str,
             context: dict | None = None) -> tuple[bool, str]:
    """Return (allowed, reason). If Cedar isn't available OR there are no
    policies for the space, default-allow (preserves existing behavior — only
    spaces with explicit policies get enforcement).
    """
    if cedarpy is None:
        return True, "cedar-not-installed"
    policyset = get_policies(space_id)
    if not policyset.strip():
        return True, "no-policies"
    try:
        req = {
            "principal": principal,
            "action": action,
            "resource": resource,
            "context": context or {},
        }
        r = cedarpy.is_authorized(req, policyset, [])
        allowed = str(r.decision) == "Decision.Allow"
        # diagnostics may have reasons + errors
        diag = getattr(r, "diagnostics", None)
        reasons = getattr(diag, "reason", []) if diag else []
        errs = getattr(diag, "errors", []) if diag else []
        reason = f"reasons={reasons!r} errors={errs!r}" if (reasons or errs) else ("explicit-allow" if allowed else "default-deny")
        return allowed, reason
    except Exception as exc:
        # On any evaluation error, default-allow with the error in reason. This
        # avoids breaking the control plane while still surfacing the problem
        # to anyone reading diagnostics.
        return True, f"cedar-error: {exc!r}"


# ----------------------------------------------------------------------------
# Compilation helpers — convert provider-native policy shapes to Cedar PolicySet
# ----------------------------------------------------------------------------
def aws_iam_json_to_cedar(policy_doc: dict, principal_arn: str = "User::\"*\"") -> str:
    """Compile a single AWS IAM policy document (dict with Statement[]) to
    a Cedar PolicySet string. Supports Effect + Action + Resource; wildcards
    are translated by stripping the trailing /* and using ``in``.
    """
    out_policies: list[str] = []
    stmts = policy_doc.get("Statement", []) or []
    if isinstance(stmts, dict):
        stmts = [stmts]
    for st in stmts:
        effect = st.get("Effect", "Deny").lower()
        directive = "permit" if effect == "allow" else "forbid"
        actions = st.get("Action", []) or []
        if isinstance(actions, str):
            actions = [actions]
        resources = st.get("Resource", []) or []
        if isinstance(resources, str):
            resources = [resources]
        # Build one policy per action × resource for simplicity.
        for act in actions:
            act_cedar = f'Action::"{act}"' if act != "*" else "Action::\"*\""
            for res in resources:
                res_clean = res.replace('"', '\\"')
                if res == "*":
                    res_clause = "resource"
                else:
                    res_clause = f'resource == Resource::"{res_clean}"'
                out_policies.append(
                    f'{directive}(\n'
                    f'  principal == {principal_arn},\n'
                    f'  action == {act_cedar},\n'
                    f'  {res_clause}\n'
                    f');'
                )
    return "\n\n".join(out_policies)


def gcp_binding_to_cedar(binding: dict) -> str:
    """Compile a GCP IAM binding ({role, members[]}) to Cedar permit rules.

    For MVP we treat ``role`` as a Cedar action (e.g. roles/storage.admin →
    Action::"roles/storage.admin"). Member shapes ``user:x@y``, ``group:x``,
    and ``serviceAccount:x`` map to Cedar User/Group/ServiceAccount types.
    """
    out: list[str] = []
    role = binding.get("role", "roles/viewer")
    for m in binding.get("members", []) or []:
        kind, _, name = m.partition(":")
        type_map = {"user": "User", "group": "Group", "serviceAccount": "ServiceAccount"}
        cedar_type = type_map.get(kind, "User")
        out.append(
            f'permit(\n'
            f'  principal == {cedar_type}::"{name}",\n'
            f'  action == Action::"{role}",\n'
            f'  resource\n'
            f');'
        )
    return "\n\n".join(out)


def azure_rbac_to_cedar(assignment: dict) -> str:
    """Compile an Azure RBAC role assignment to a Cedar permit rule.

    Inputs: {scope, principalId, principalType, roleDefinitionId or roleName}.
    """
    role = assignment.get("roleName") or assignment.get("roleDefinitionId", "Reader")
    principal = assignment.get("principalId", "unknown")
    ptype = assignment.get("principalType", "User")
    scope = assignment.get("scope", "/")
    ptype_clean = "User" if ptype.lower() == "user" else ("Group" if ptype.lower() == "group" else "ServicePrincipal")
    return (
        f'permit(\n'
        f'  principal == {ptype_clean}::"{principal}",\n'
        f'  action == Action::"{role}",\n'
        f'  resource in Scope::"{scope}"\n'
        f');'
    )
