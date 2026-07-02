"""IamStore + AuthzEngine — the data-plane + decision seams for IAM (ADR-001).

The IAM control-plane logic (users/roles/policies/groups/attachments, native wire
shapes) is substrate-independent and lives in core/iam_core.py. THESE are the two
seams it persists/decides through, so the same handler runs on any substrate:

    Pro/Max : IamStore + a Cedar engine (cedarpy, Rust) when cedar_enforcement is on
    Nano    : InMemoryIamStore + NativeIamEvaluator (pure-Python, in-WASM)
    tests   : InMemoryIamStore + NativeIamEvaluator

Authorization is a SEAM (AuthzEngine). The appliance already ships TWO evaluators:
a pure-Python AWS IAM-JSON evaluator (`_iam_authorize` in server.py) AND an
optional Cedar engine (cedarpy — a Rust binding that won't load under Pyodide).
The Nano default is the Python evaluator, ported here as NativeIamEvaluator — it
is the REAL authorization logic (explicit-deny-wins, wildcard action/resource,
condition operators), not a stub, and runs identically on host CPython and
Pyodide. A `cedar-wasm` engine (the WASM build of Cedar) can swap in behind this
SAME interface in-browser later. Per the native-SDK-conformance principle the
*decision* is what must conform; the engine behind it is our private pick.

Nothing here imports fastapi / boto3 / socket / cedarpy, so it loads under Pyodide.

State shapes (record shapes owned by iam_core):
    users    : { user_name -> user }
    groups   : { group_name -> group }
    roles    : { role_name -> role }
    policies : { policy_arn -> managed-policy }
    access_keys : { access_key_id -> key }
"""
from __future__ import annotations

import fnmatch
from typing import Any

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID


# ── authorization (decision) seam ──────────────────────────────────────────
class AuthzEngine:
    """Decision seam. evaluate() returns (decision, reason) where decision is one
    of 'allowed' | 'explicitDeny' | 'implicitDeny' (the AWS SimulatePrincipalPolicy
    EvalDecision vocabulary). Subclass to back with Cedar / cedar-wasm."""

    def evaluate(self, policy_documents: list[dict], action: str, resource: str,
                 context: dict[str, str]) -> tuple[str, str]:  # pragma: no cover
        raise NotImplementedError


class NativeIamEvaluator(AuthzEngine):
    """Pure-Python AWS IAM-JSON policy evaluator — a faithful port of server.py's
    `_iam_authorize` family (verbatim matching/condition logic), with CORRECTED
    semantics: explicit deny wins across ALL statements (the appliance returned on
    the first matching statement, which an allow-before-deny ordering could wrongly
    allow). Pyodide-safe (stdlib fnmatch only)."""

    @staticmethod
    def _value_matches(pattern: Any, value: str) -> bool:
        if isinstance(pattern, list):
            return any(NativeIamEvaluator._value_matches(item, value) for item in pattern)
        if pattern is None:
            return False
        pattern = str(pattern).strip()
        value = str(value or "")
        if not pattern:
            return False
        return fnmatch.fnmatchcase(value.lower(), pattern.lower())

    @staticmethod
    def _condition_matches(condition: dict, context: dict[str, str]) -> bool:
        if not condition:
            return True
        for operator, operands in condition.items():
            if not isinstance(operands, dict):
                return False
            op = operator.lower()
            for key, expected in operands.items():
                actual = context.get(key, "")
                if op in {"stringequals", "arnequals"}:
                    if isinstance(expected, list):
                        if actual not in [str(i) for i in expected]:
                            return False
                    elif actual != str(expected):
                        return False
                elif op in {"stringlike", "arnlike"}:
                    if not NativeIamEvaluator._value_matches(expected, actual):
                        return False
                else:
                    return False
        return True

    @classmethod
    def _statement_matches(cls, statement: dict, action: str, resource: str,
                           context: dict[str, str]) -> bool:
        if not isinstance(statement, dict):
            return False
        effect = str(statement.get("Effect", "Allow")).strip().lower()
        if effect not in {"allow", "deny"}:
            return False
        if "Action" in statement:
            if not cls._value_matches(statement.get("Action"), action):
                return False
        elif "NotAction" in statement:
            if cls._value_matches(statement.get("NotAction"), action):
                return False
        else:
            return False
        if "Resource" in statement:
            if not cls._value_matches(statement.get("Resource"), resource):
                return False
        elif "NotResource" in statement:
            if cls._value_matches(statement.get("NotResource"), resource):
                return False
        return cls._condition_matches(statement.get("Condition", {}) or {}, context)

    def evaluate(self, policy_documents: list[dict], action: str, resource: str,
                 context: dict[str, str]) -> tuple[str, str]:
        explicit_deny = False
        allow = False
        for doc in policy_documents or []:
            statements = (doc or {}).get("Statement", [])
            if isinstance(statements, dict):
                statements = [statements]
            for stmt in statements:
                if not self._statement_matches(stmt, action, resource, context):
                    continue
                eff = str(stmt.get("Effect", "")).strip().lower()
                if eff == "deny":
                    explicit_deny = True
                elif eff == "allow":
                    allow = True
        if explicit_deny:
            return "explicitDeny", f"explicit deny for {action} on {resource}"
        if allow:
            return "allowed", ""
        return "implicitDeny", f"no statement allows {action} on {resource}"


# ── data-plane seam ────────────────────────────────────────────────────────
class IamStore:
    """Base seam. In-memory by default; subclass to add a mirror / persistence."""

    def __init__(self, engine: AuthzEngine | None = None,
                 account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, dict[str, Any]] = {}
        self.policies: dict[str, dict[str, Any]] = {}      # keyed by ARN
        self.access_keys: dict[str, dict[str, Any]] = {}   # keyed by AccessKeyId
        self.engine: AuthzEngine = engine or NativeIamEvaluator()
        self.account_id = account_id

    # ── accessors ─────────────────────────────────────────────────────
    def get_user(self, name: str) -> dict | None:
        return self.users.get(name)

    def get_role(self, name: str) -> dict | None:
        return self.roles.get(name)

    def get_group(self, name: str) -> dict | None:
        return self.groups.get(name)

    def get_policy(self, arn: str) -> dict | None:
        return self.policies.get(arn)

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def persist(self) -> None:
        """Flush state to durable storage (appliance ctx in Pro/Max, IDB/OPFS in Nano)."""

    def mirror(self, kind: str, key: str, record: dict | None) -> None:
        """Best-effort write-through/delete in an external backend."""


class InMemoryIamStore(IamStore):
    """The Nano / test substrate: pure in-memory, zero external deps."""
