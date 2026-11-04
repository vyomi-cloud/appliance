# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
    saml_providers : { arn -> provider }
    oidc_providers : { arn -> provider }
    account_aliases : [alias, ...]        (IAM allows at most one in real AWS; we allow a small list)
    password_policy : dict | None          (GetAccountPasswordPolicy shape, or None = IAM default)
    credential_report : {"generated": iso8601, "content": csv-str} | None
    org_policies : { policy_id -> SCP/RCP }   (Vyomi-only — see iam_core's CreateOrgPolicy)
    access_requests : { request_id -> account-access request }  (Vyomi-only — see RequestAccountAccess)
    virtual_mfa_devices : { serial_number(arn) -> virtual MFA device, assigned or not }
    activity : [ {principal_arn, service, action, time}, ... ]  (native-wire activity log —
        every request signed with an IAM USER's own access key, AKID-attributed by
        aws_wire_router.py; the console's own operator credential doesn't appear here.
        Backs GenerateServiceLastAccessedDetails, the Vyomi-only policy-from-activity
        generator, and Access Analyzer's unused-access findings — see iam_core.record_activity)
    trust_anchors : { arn -> IAM Roles Anywhere trust anchor }      (Vyomi-only)
    rolesanywhere_profiles : { arn -> IAM Roles Anywhere profile }  (Vyomi-only)
    analyzers : { analyzer_name -> Access Analyzer analyzer }       (Vyomi-only)
    extras : { ssh_keys, service_creds, signing_certs, server_certs, events } — see iam_core._x
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
    def _expand(value: Any, context: dict) -> Any:
        """Policy variables: ${aws:username}, ${aws:PrincipalTag/team}, … resolved from the request context."""
        if isinstance(value, list):
            return [NativeIamEvaluator._expand(v, context) for v in value]
        if not isinstance(value, str) or "${" not in value:
            return value
        import re
        return re.sub(r"\$\{([^}]+)\}", lambda m: str(context.get(m.group(1), m.group(0))), value)

    @staticmethod
    def _cmp_values(base: str, actual: str, wanted: list[str]) -> bool:
        """True if `actual` satisfies the POSITIVE form of operator `base` against ANY wanted value."""
        if base in ("stringequals", "arnequals"):
            return actual in wanted
        if base == "stringequalsignorecase":
            return actual.lower() in [w.lower() for w in wanted]
        if base in ("stringlike", "arnlike"):
            return NativeIamEvaluator._value_matches(wanted, actual)
        if base.startswith("numeric"):
            try:
                a = float(actual)
                nums = [float(w) for w in wanted]
            except ValueError:
                return False
            fn = {"numericequals": lambda n: a == n, "numericlessthan": lambda n: a < n, "numericlessthanequals": lambda n: a <= n,
                  "numericgreaterthan": lambda n: a > n, "numericgreaterthanequals": lambda n: a >= n}.get(base)
            return bool(fn) and any(fn(n) for n in nums)
        if base.startswith("date"):
            def ts(v):
                v = str(v).strip()
                try:
                    return float(v)
                except ValueError:
                    from datetime import datetime, timezone
                    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
            try:
                a = ts(actual)
                dates = [ts(w) for w in wanted]
            except ValueError:
                return False
            fn = {"dateequals": lambda d: a == d, "datelessthan": lambda d: a < d, "datelessthanequals": lambda d: a <= d,
                  "dategreaterthan": lambda d: a > d, "dategreaterthanequals": lambda d: a >= d}.get(base)
            return bool(fn) and any(fn(d) for d in dates)
        if base == "ipaddress":
            import ipaddress
            try:
                ip = ipaddress.ip_address(actual)
                return any(ip in ipaddress.ip_network(str(w), strict=False) for w in wanted)
            except ValueError:
                return False
        if base == "bool":
            return actual.lower() in [w.lower() for w in wanted]
        if base == "binaryequals":
            return actual in wanted
        return False

    _NEGATED = {"stringnotequals": "stringequals", "stringnotequalsignorecase": "stringequalsignorecase", "stringnotlike": "stringlike",
                "arnnotequals": "arnequals", "arnnotlike": "arnlike", "numericnotequals": "numericequals",
                "notipaddress": "ipaddress"}

    @staticmethod
    def _condition_matches(condition: dict, context: dict[str, str]) -> bool:
        if not condition:
            return True
        for operator, operands in condition.items():
            if not isinstance(operands, dict):
                return False
            op = operator
            qualifier = ""
            if ":" in op:
                qualifier, op = op.split(":", 1)
            op = op.lower()
            if_exists = op.endswith("ifexists")
            if if_exists:
                op = op[: -len("ifexists")]
            negated = op in NativeIamEvaluator._NEGATED
            base = NativeIamEvaluator._NEGATED.get(op, op)
            for key, expected in operands.items():
                present = key in context and context[key] is not None
                if op == "null":
                    want_absent = str(expected[0] if isinstance(expected, list) else expected).lower() == "true"
                    if (not present) != want_absent:
                        return False
                    continue
                if not present:
                    if if_exists or negated or qualifier.lower() == "forallvalues":
                        continue       # IfExists / negated operators / ForAllValues are true for an absent key
                    return False
                wanted = NativeIamEvaluator._expand(expected if isinstance(expected, list) else [expected], context)
                hit = NativeIamEvaluator._cmp_values(base, str(context[key]), [str(w) for w in wanted])
                if hit == negated:
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
        self.saml_providers: dict[str, dict[str, Any]] = {}     # keyed by ARN
        self.oidc_providers: dict[str, dict[str, Any]] = {}     # keyed by ARN
        self.account_aliases: list[str] = []
        self.password_policy: dict[str, Any] | None = None
        self.credential_report: dict[str, Any] | None = None
        self.org_policies: dict[str, dict[str, Any]] = {}       # keyed by PolicyId (SCP/RCP, Vyomi-only)
        self.access_requests: dict[str, dict[str, Any]] = {}    # keyed by RequestId (Vyomi-only)
        self.virtual_mfa_devices: dict[str, dict[str, Any]] = {}   # keyed by SerialNumber (ARN)
        self.activity: list[dict[str, Any]] = []                   # native-wire activity log (Vyomi-only)
        self.trust_anchors: dict[str, dict[str, Any]] = {}         # keyed by ARN (Roles Anywhere, Vyomi-only)
        self.rolesanywhere_profiles: dict[str, dict[str, Any]] = {}   # keyed by ARN (Roles Anywhere, Vyomi-only)
        self.analyzers: dict[str, dict[str, Any]] = {}             # keyed by analyzer name (Access Analyzer, Vyomi-only)
        self.extras: dict[str, Any] = {}   # ssh_keys/service_creds/signing_certs/server_certs/events (see iam_core._x)
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
