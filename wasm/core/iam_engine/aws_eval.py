"""AWS policy evaluation (pure Python, no fastapi/socket; Pyodide-safe).  Spec: the AWS IAM "policy evaluation logic" flowchart.

evaluate(req, state) -> types.decision(...).  See docs/architecture/v4.0/branches/iam-engine-aws.md for the state shape and decisions.

Order implemented:  explicit Deny in ANY applicable policy (identity, boundary, session, SCP, RCP, resource) -> deny;
RCPs (resource account) must allow; SCPs (principal account) must allow; then
  same account : resource policy that grants the principal directly, OR (identity allow AND boundary allow AND session allow)
  cross account: (identity allow AND boundary AND session) AND resource-policy allow
"""
from __future__ import annotations

import base64
import re
import ipaddress
from datetime import datetime, timezone

from .types import decision

_RX = {}


def _wc(pattern, ci=False):
    """Compile an IAM wildcard (* = any run, ? = one char; nothing else is special) to a regex."""
    key = (pattern, ci)
    rx = _RX.get(key)
    if rx is None:
        rx = re.compile("^" + "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern) + "$",
                        re.S | (re.I if ci else 0))
        _RX[key] = rx
    return rx


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _s(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ---------------------------------------------------------------- context & variables
class _Ctx:
    def __init__(self, values):
        self.v = {}
        for k, val in (values or {}).items():
            self.v[str(k).lower()] = [_s(x) for x in _as_list(val)]
        self.missing = []      # condition keys referenced but absent

    def get(self, key):
        return self.v.get(key.lower())

    def has(self, key):
        return key.lower() in self.v


_VAR = re.compile(r"\$\{([^}]*)\}")


def _subst(text, ctx):
    """Policy variables.  ${*} ${?} ${$} are literal escapes.  Unknown variable -> left in place (so it cannot match by accident)."""
    if not isinstance(text, str) or "${" not in text:
        return text

    def rep(m):
        name = m.group(1)
        if name == "*":
            return "\x00STAR"
        if name == "?":
            return "\x00QM"
        if name == "$":
            return "$"
        vals = ctx.get(name)
        return vals[0] if vals else m.group(0)
    return _VAR.sub(rep, text)


def _unescape(text):
    return text.replace("\x00STAR", "*").replace("\x00QM", "?")


def _wild_match(pattern, value, ctx, ci=False):
    p = _subst(pattern, ctx)
    if "\x00" in p:
        # escaped * / ? must match literally: build regex piecewise
        parts = re.split(r"(\x00STAR|\x00QM)", p)
        rx = "^" + "".join(re.escape("*") if x == "\x00STAR" else re.escape("?") if x == "\x00QM"
                           else "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in x) for x in parts) + "$"
        return re.match(rx, value, re.S | (re.I if ci else 0)) is not None
    return _wc(p, ci).match(value) is not None


# ---------------------------------------------------------------- condition operators
def _parse_time(v):
    v = str(v).strip()
    try:
        return float(v)
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ip_in(value, cidr):
    try:
        return ipaddress.ip_address(value) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _arn_like(pattern, value):
    pp, vp = pattern.split(":", 5), value.split(":", 5)
    if len(pp) != 6 or len(vp) != 6:
        return False
    return all(_wc(a).match(b) for a, b in zip(pp, vp))


def _b64(v):
    try:
        return base64.b64decode(v, validate=True)
    except Exception:
        return None


# base operator -> (positive matcher(value, policy_value, ctx) , negated)
def _cmp(fn):
    def f(v, p, ctx):
        a, b = fn(v), fn(p)
        return a, b
    return f


def _mk_numdate(conv, op):
    def m(v, p, ctx):
        a, b = conv(v), conv(_subst(p, ctx))
        if a is None or b is None:
            return False
        return {"Equals": a == b, "LessThan": a < b, "LessThanEquals": a <= b,
                "GreaterThan": a > b, "GreaterThanEquals": a >= b}[op]
    return m


_POS = {
    "StringEquals": lambda v, p, c: v == _unescape(_subst(p, c)),
    "StringEqualsIgnoreCase": lambda v, p, c: v.lower() == _unescape(_subst(p, c)).lower(),
    "StringLike": lambda v, p, c: _wild_match(p, v, c),
    "ArnEquals": lambda v, p, c: _arn_like(_subst(p, c), v),
    "ArnLike": lambda v, p, c: _arn_like(_subst(p, c), v),
    "Bool": lambda v, p, c: v.lower() == _s(_subst(p, c)).lower(),
    "BinaryEquals": lambda v, p, c: _b64(v) is not None and _b64(v) == _b64(_s(p)),
    "IpAddress": lambda v, p, c: _ip_in(v, _s(_subst(p, c))),
    "NumericEquals": _mk_numdate(_num, "Equals"),
    "NumericLessThan": _mk_numdate(_num, "LessThan"),
    "NumericLessThanEquals": _mk_numdate(_num, "LessThanEquals"),
    "NumericGreaterThan": _mk_numdate(_num, "GreaterThan"),
    "NumericGreaterThanEquals": _mk_numdate(_num, "GreaterThanEquals"),
    "DateEquals": _mk_numdate(_parse_time, "Equals"),
    "DateLessThan": _mk_numdate(_parse_time, "LessThan"),
    "DateLessThanEquals": _mk_numdate(_parse_time, "LessThanEquals"),
    "DateGreaterThan": _mk_numdate(_parse_time, "GreaterThan"),
    "DateGreaterThanEquals": _mk_numdate(_parse_time, "GreaterThanEquals"),
}
_NEG = {  # negated operator -> positive twin
    "StringNotEquals": "StringEquals", "StringNotEqualsIgnoreCase": "StringEqualsIgnoreCase", "StringNotLike": "StringLike",
    "ArnNotEquals": "ArnEquals", "ArnNotLike": "ArnLike", "NotIpAddress": "IpAddress",
    "NumericNotEquals": "NumericEquals", "DateNotEquals": "DateEquals",
}
# NOTE: NumericNotEquals/DateNotEquals with an unparsable value: the twin is False, so the negation is True (AWS errors the policy; unverified).


def _eval_condition_block(cond, ctx):
    """True when every (operator, key) pair holds."""
    if not cond:
        return True
    for opname, kv in cond.items():
        if not isinstance(kv, dict):
            return False
        for key, pvals in kv.items():
            if not _eval_one(opname, key, _as_list(pvals), ctx):
                return False
    return True


def _eval_one(opname, key, pvals, ctx):
    setop = None
    base = opname
    if ":" in base:
        pre, base = base.split(":", 1)
        setop = pre
        if setop not in ("ForAllValues", "ForAnyValue"):
            return False
    if_exists = base.endswith("IfExists")
    if if_exists:
        base = base[:-8]
    present = ctx.has(key)
    if base == "Null":
        want_null = any(_s(p).lower() == "true" for p in pvals)
        return (not present) if want_null else present
    if not present:
        ctx.missing.append(key)
        if if_exists:
            return True
        if setop == "ForAllValues":
            return True                    # vacuous truth over an empty set
        if setop == "ForAnyValue":
            return False
        return base in _NEG                # negated operators succeed when the key is absent
    vals = ctx.get(key)
    neg = base in _NEG
    pos = _POS.get(_NEG.get(base, base))
    if pos is None:
        return False

    def one_value_ok(v):
        hit = any(pos(v, p if isinstance(p, str) else _s(p), ctx) for p in pvals)
        return (not hit) if neg else hit
    if setop == "ForAllValues":
        return all(one_value_ok(v) for v in vals)
    if setop == "ForAnyValue":
        return any(one_value_ok(v) for v in vals)
    # no set operator: positive = any (ctx value, policy value) pair matches; negated = no pair matches
    if neg:
        return all(one_value_ok(v) for v in vals)
    return any(one_value_ok(v) for v in vals)


# ---------------------------------------------------------------- statements
def _statements(doc):
    if not isinstance(doc, dict):
        return []
    st = doc.get("Statement")
    if isinstance(st, dict):
        return [st]
    return [s for s in (st or []) if isinstance(s, dict)]


def _norm_policy(p, default_id):
    """Accept a bare document or {"id","document"}.  Returns (id, doc)."""
    if isinstance(p, dict) and "document" in p and "Statement" not in p:
        return str(p.get("id") or default_id), p["document"]
    return default_id, p


def _norm_policies(lst, prefix):
    out = []
    for i, p in enumerate(_as_list(lst)):
        if p is None:
            continue
        out.append(_norm_policy(p, f"{prefix}[{i}]"))
    return out


def _stmt_applies(st, action, resource, ctx, resource_based=False):
    if "Action" in st and "NotAction" in st:
        return False
    if "Action" in st:
        if not any(_wc(a, True).match(action) for a in _as_list(st["Action"])):
            return False
    elif "NotAction" in st:
        if any(_wc(a, True).match(action) for a in _as_list(st["NotAction"])):
            return False
    else:
        return False
    if "Resource" in st and "NotResource" in st:
        return False
    if "Resource" in st:
        if not any(_wild_match(r, resource, ctx) for r in _as_list(st["Resource"])):
            return False
    elif "NotResource" in st:
        if any(_wild_match(r, resource, ctx) for r in _as_list(st["NotResource"])):
            return False
    elif not resource_based:
        return False
    return _eval_condition_block(st.get("Condition"), ctx)


def _collect(policies, source, action, resource, ctx, resource_based=False, principal_ok=None):
    """-> (allows, denies) matched-statement records."""
    allows, denies = [], []
    for pid, doc in policies:
        for i, st in enumerate(_statements(doc)):
            eff = str(st.get("Effect", "")).lower()
            if eff not in ("allow", "deny"):
                continue
            kind = None
            if principal_ok is not None:
                kind = principal_ok(st)
                if kind is None:
                    continue
            if not _stmt_applies(st, action, resource, ctx, resource_based):
                continue
            rec = {"source": source, "id": f"{pid}#{st.get('Sid') or i}", "effect": "Allow" if eff == "allow" else "Deny",
                   "statement": st}
            if kind:
                rec["principal_match"] = kind
            (allows if eff == "allow" else denies).append(rec)
    return allows, denies


# ---------------------------------------------------------------- principals (resource policies)
def _role_arn_of(arn):
    m = re.match(r"^arn:([^:]*):sts::(\d*):assumed-role/([^/]+)/.+$", arn or "")
    if m:
        return f"arn:{m.group(1)}:iam::{m.group(2)}:role/{m.group(3)}"
    return None


def _acct_of(arn):
    parts = (arn or "").split(":")
    return parts[4] if len(parts) > 4 and parts[4].isdigit() else None


def _principal_kind(entry, p):
    """How a Principal entry matches caller p.  -> None | 'wildcard' | 'user' | 'session' | 'role' | 'account' | 'service' | 'federated'."""
    arn, acct, typ = p.get("arn") or "", p.get("account"), p.get("type", "")
    if entry == "*":
        return "wildcard"
    if typ == "service":
        return "service" if entry == p.get("service", arn) else None
    if typ == "federated":
        return "federated" if entry == arn else None
    if not arn:
        return None
    if entry == arn:
        return "session" if ":assumed-role/" in arn else ("user" if ":user/" in arn else "role" if ":role/" in arn else "user")
    if entry == _role_arn_of(arn) or (p.get("role_arn") and entry == p["role_arn"]):
        return "role"
    if re.fullmatch(r"\d{12}", entry) and entry == acct:
        return "account"
    if re.fullmatch(r"arn:[^:]*:iam::\d{12}:root", entry) and entry.split(":")[4] == acct:
        return "account"
    return None


def _principal_match(st, p):
    """None = statement does not apply to this principal, else the kind of match."""
    if "NotPrincipal" in st:
        ents = _principal_entries(st["NotPrincipal"])
        if any(_principal_kind(e, p) for e in ents):
            return None
        return "wildcard"
    if "Principal" not in st:
        return None
    best = None
    rank = {"user": 0, "session": 0, "service": 0, "federated": 0, "role": 1, "wildcard": 2, "account": 3}
    for e in _principal_entries(st["Principal"]):
        k = _principal_kind(e, p)
        if k and (best is None or rank[k] < rank[best]):
            best = k
    return best


def _principal_entries(pr):
    if pr == "*":
        return ["*"]
    if isinstance(pr, dict):
        out = []
        for v in pr.values():
            out.extend(_as_list(v))
        return out
    return _as_list(pr)


# ---------------------------------------------------------------- org layers
def _levels(spec, account):
    """SCP/RCP spec -> list of levels (each level = list of (id, doc)).  Accepts a list of levels (a level being a list of docs or a single doc),
    or {account: that, "*": that}.  Empty -> no SCP in force."""
    if isinstance(spec, dict) and "Statement" not in spec:
        spec = spec.get(account, spec.get("*"))
    out = []
    for i, lv in enumerate(_as_list(spec)):
        docs = [lv] if isinstance(lv, dict) and ("Statement" in lv or "document" in lv) else _as_list(lv)
        out.append(_norm_policies(docs, f"level{i}"))
    return out


# ---------------------------------------------------------------- main
def _build_context(req, state, principal, resource, res_tags):
    raw = {}
    pt = principal.get("tags") or {}
    arn = principal.get("arn")
    raw["aws:CurrentTime"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if arn:
        raw["aws:PrincipalArn"] = (principal.get("role_arn") or _role_arn_of(arn)) if ":assumed-role/" in arn else arn
        name = arn.rsplit("/", 1)[-1]
        if ":user/" in arn:
            raw["aws:username"] = name
        if principal.get("id"):
            raw["aws:userid"] = principal["id"]
    if principal.get("account"):
        raw["aws:PrincipalAccount"] = principal["account"]
    if principal.get("account") and principal.get("type") != "anonymous":
        raw["AWS:SourceOwner"] = principal["account"]       # service-condition key (SNS default topic policy): the caller's account
    if principal.get("type"):
        raw["aws:PrincipalType"] = {"user": "User", "role": "AssumedRole", "root": "Account", "federated": "FederatedUser",
                                    "service": "Service", "anonymous": "Anonymous"}.get(principal["type"], principal["type"])
    if principal.get("org_id") or state.get("org_id"):
        raw["aws:PrincipalOrgID"] = principal.get("org_id") or state.get("org_id")
    for k, v in pt.items():
        raw[f"aws:PrincipalTag/{k}"] = v
    for k, v in (res_tags or {}).items():
        raw[f"aws:ResourceTag/{k}"] = v
    raw["aws:ResourceArn"] = resource
    raw.update(req.get("context") or {})
    ctx = _Ctx(raw)
    if not ctx.has("aws:TagKeys"):
        rk = [str(k).split("/", 1)[1] for k in (req.get("context") or {}) if str(k).lower().startswith("aws:requesttag/")]
        if rk:
            ctx.v["aws:tagkeys"] = rk
    return ctx


# ---------------------------------------------------------------- S3 Block Public Access (RestrictPublicBuckets)
_NON_PUBLIC_CONDITION_KEYS = ("aws:principalorgid", "aws:principalorgpaths", "aws:principalaccount", "aws:principalarn", "aws:sourcevpc", "aws:sourcevpce",
                              "aws:sourceip", "aws:sourcearn", "aws:sourceaccount", "aws:sourceowner", "aws:userid", "aws:principalservicename",
                              "s3:datalinkaccesspointaccount")


def _stmt_public(st):
    """AWS's notion of a public statement: Allow to Principal '*' that no condition limits to an account / org / VPC / IP / ARN."""
    if not isinstance(st, dict) or st.get("Effect") != "Allow":
        return False
    pr = st.get("Principal")
    wild = pr == "*" or (isinstance(pr, dict) and ("*" in _as_list(pr.get("AWS")) or pr.get("AWS") == "*"))
    if not wild:
        return False
    for op, kv in (st.get("Condition") or {}).items():
        for key in (kv or {}):
            if str(key).lower() in _NON_PUBLIC_CONDITION_KEYS:
                return False
    return True


def _s3_bucket(resource):
    r = str(resource or "")
    if not r.startswith("arn:aws:s3:::"):
        return None
    return r[len("arn:aws:s3:::"):].split("/", 1)[0] or None


def _apply_restrict_public_buckets(rpol, resource, principal, cross, bpa):
    """RestrictPublicBuckets: a bucket policy that grants public access is ignored for everyone outside the bucket owner's account (anonymous
    callers and other accounts); service principals and the owner's own principals are unaffected.  ACL-derived grants (Sid 'vyomi-acl:*',
    see core/iam_resource_policies.py) are governed by IgnorePublicAcls, not by this setting.  -> (policy, whether a statement was dropped)."""
    b = _s3_bucket(resource)
    flags = (bpa or {}).get(b) if b else None
    if not flags or not flags.get("RestrictPublicBuckets"):
        return rpol, False
    if not (principal.get("type") == "anonymous" or cross):
        return rpol, False
    doc = rpol if isinstance(rpol, dict) else {}
    stmts = _as_list(doc.get("Statement"))
    keep = [st for st in stmts if not (_stmt_public(st) and not str((st or {}).get("Sid") or "").startswith("vyomi-acl:"))]
    if len(keep) == len(stmts):
        return rpol, False
    return dict(doc, Statement=keep), True


def evaluate(req, state=None):
    state = state or {}
    action = str(req.get("action", ""))
    resource = str(req.get("resource", "*"))
    principal = dict(req.get("principal") or {})
    arn = principal.get("arn") or ""
    rec = (state.get("principals") or {}).get(arn) or {}
    for k in ("policies", "boundary", "groups", "tags"):
        if k not in principal and k in rec:
            principal[k] = rec[k]
    if not principal.get("account"):
        principal["account"] = _acct_of(arn) or state.get("account")
    ptype = principal.get("type") or ("root" if arn.endswith(":root") else "role" if (":role/" in arn or ":assumed-role/" in arn)
                                       else "user" if ":user/" in arn else "")
    principal["type"] = ptype
    # a role session inherits tags of the role; host puts them in principal["tags"]
    res_acct = req.get("resource_account") or _acct_of(resource) or state.get("account") or principal["account"]
    res_tags = req.get("resource_tags") or (state.get("resource_tags") or {}).get(resource)
    ctx = _build_context(req, state, principal, resource, res_tags)
    cross = bool(principal["account"] and res_acct and principal["account"] != res_acct)

    ident = _norm_policies(principal.get("policies"), "identity")
    for g in _as_list(principal.get("groups")):
        grp = (state.get("groups") or {}).get(g) if isinstance(g, str) else g
        if grp:
            ident += _norm_policies(grp.get("policies"), f"group:{g}")
    boundary = _norm_policies(principal.get("boundary"), "boundary") if principal.get("boundary") else []
    sess = _norm_policies(principal.get("session_policy"), "session") if principal.get("session_policy") else []
    scps = _levels(state.get("scps"), principal["account"])
    rcps = _levels(state.get("rcps"), res_acct)
    rpol = req.get("resource_policy") or (state.get("resource_policies") or {}).get(resource)
    bpa_hit = False
    if rpol and state.get("s3_bpa"):
        rpol, bpa_hit = _apply_restrict_public_buckets(rpol, resource, principal, cross, state["s3_bpa"])
    rpols = _norm_policies([rpol], "resource") if rpol else []

    matched = []
    by_principal = lambda st: _principal_match(st, principal)          # noqa: E731

    def layer(pols, source, **kw):
        return _collect(pols, source, action, resource, ctx, **kw)

    # ---- explicit deny anywhere
    denies = []
    ia, idn = layer(ident, "identity")
    ba, bdn = layer(boundary, "boundary")
    sa, sdn = layer(sess, "session")
    ra, rdn = layer(rpols, "resource", resource_based=True, principal_ok=by_principal)
    denies += idn + bdn + sdn + rdn
    scp_allow_levels, rcp_allow_levels = [], []
    for lv in scps:
        a, d = layer(lv, "scp")
        denies += d
        scp_allow_levels.append(a)
    for lv in rcps:
        a, d = layer(lv, "rcp", resource_based=True)
        denies += d
        rcp_allow_levels.append(a)

    def out(allowed, reason, m, failed=None):
        extra = {"missingContext": sorted(set(ctx.missing))}
        if bpa_hit and not allowed:
            extra["blockPublicAccess"] = "RestrictPublicBuckets"
        if failed:
            extra["failedLayer"] = failed
        return decision(allowed, reason, m, **extra)

    if denies:
        return out(False, "explicit_deny", denies)

    # ---- organisation guardrails: every level must allow
    for lvl_name, levels in (("rcp", rcp_allow_levels), ("scp", scp_allow_levels)):
        for a in levels:
            if not a:
                return out(False, "implicit_deny", [], lvl_name)
            matched += a

    # ---- principals that have no identity policies of their own
    root = ptype == "root" and not cross
    if root:
        return out(True, "allow", matched + [{"source": "identity", "id": "root", "effect": "Allow", "statement": {"note": "account root user"}}])
    rp_only = ptype in ("service", "anonymous", "federated") or not arn
    if rp_only:
        if ra:
            return out(True, "allow", matched + ra)
        return out(False, "implicit_deny", [], "resource")

    # ---- identity side: identity allow + boundary + session
    def identity_side():
        if not ia:
            return None, "identity"
        if boundary and not ba:
            return None, "boundary"
        if sess and not sa:
            return None, "session"
        return ia + ba + sa, None

    ident_ok, why = identity_side()
    if cross:
        if ident_ok is None:
            return out(False, "implicit_deny", [], why)
        if not ra:
            return out(False, "implicit_deny", [], "resource")
        return out(True, "allow", matched + ident_ok + ra)

    # ---- same account
    kinds = {r.get("principal_match") for r in ra}
    direct_bypass = ("user" in kinds and ptype == "user") or ("session" in kinds and ":assumed-role/" in arn)
    if ra and direct_bypass:
        return out(True, "allow", matched + [r for r in ra if r.get("principal_match") in ("user", "session")])
    if ra and (kinds & {"role", "wildcard"}):
        # granted by role ARN or '*': boundary / session policy still limit it (see branch doc: unverified for '*')
        if (not boundary or ba) and (not sess or sa):
            return out(True, "allow", matched + [r for r in ra if r.get("principal_match") in ("role", "wildcard")])
    # KMS-style resources: identity policies grant only if the resource policy itself enables them (host lists such ARNs in state)
    if ident_ok is not None and resource in (state.get("resource_policy_requires_grant") or ()):
        return out(False, "implicit_deny", [], "resource")
    if ident_ok is not None:
        return out(True, "allow", matched + ident_ok + [r for r in ra if r.get("principal_match") == "account"])
    return out(False, "implicit_deny", [], why)


# ---------------------------------------------------------------- SimulatePrincipalPolicy helper
_DEC = {"allow": "allowed", "explicit_deny": "explicitDeny", "implicit_deny": "implicitDeny"}


def simulate(principal, actions, resources, context=None, state=None, resource_policy=None, resource_account=None):
    """Shared helper for SimulatePrincipalPolicy / SimulateCustomPolicy.  `principal` as in types.request (policies / boundary /
    session_policy inline).  Returns [{"EvalActionName","EvalResourceName","EvalDecision","MatchedStatements","MissingContextValues"}]
    with EvalDecision in {allowed, explicitDeny, implicitDeny} (the strings the IAM API uses)."""
    out = []
    for a in actions:
        for r in resources or ["*"]:
            req = {"cloud": "aws", "principal": principal, "action": a, "resource": r, "context": dict(context or {})}
            if resource_policy:
                req["resource_policy"] = resource_policy
            if resource_account:
                req["resource_account"] = resource_account
            d = evaluate(req, state or {})
            out.append({"EvalActionName": a, "EvalResourceName": r, "EvalDecision": _DEC[d["reason"]],
                        "MatchedStatements": [{"SourcePolicyId": m["id"], "Effect": m["effect"], "Source": m["source"]} for m in d["matched"]],
                        "MissingContextValues": d.get("missingContext", [])})
    return out
