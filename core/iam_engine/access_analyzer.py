"""IAM Access Analyzer over the faithful engine (pure Python, Pyodide-safe: no fastapi / socket).

Three parts:
  findings            external-access findings (resource policies + role trust policies) and unused-access findings, generated from the
                      live state: nothing is seeded. `compute(...)` is also what core/iam_core.py's IAM-wire console view calls.
  policy checks       validate_policy / check_no_new_access / check_access_not_granted over the AWS service catalogs and aws_eval
  dispatch            the real `accessanalyzer` REST-JSON service (SigV4 service `access-analyzer`): CreateAnalyzer / ListAnalyzers /
                      GetAnalyzer / DeleteAnalyzer / ListFindings(V2) / GetFinding(V2) / UpdateFindings / ValidatePolicy /
                      CheckNoNewAccess / CheckAccessNotGranted / StartResourceScan

State is injected (`ctx`): {"store": IAM store (analyzers, roles, users, access_keys, activity, account_id, persist()),
"state": aws engine state (resource_policies ...), "audit": [records of the decision ring], "region": str, "now": iso string}."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timezone

from . import analyze_aws, aws_eval

UNUSED_TYPES = ("ACCOUNT_UNUSED_ACCESS", "ORGANIZATION_UNUSED_ACCESS")
ANALYZER_TYPES = ("ACCOUNT", "ORGANIZATION") + UNUSED_TYPES
_RESTRICT_KEYS = ("aws:sourceaccount", "aws:sourceowner", "aws:principalaccount", "aws:sourcearn", "aws:principalarn", "aws:userid",
                  "aws:sourceorgid", "aws:principalorgid")
_RTYPE = (("arn:aws:s3:::", "AWS::S3::Bucket"), (":sqs:", "AWS::SQS::Queue"), (":sns:", "AWS::SNS::Topic"), (":kms:", "AWS::KMS::Key"),
          (":lambda:", "AWS::Lambda::Function"), (":secretsmanager:", "AWS::SecretsManager::Secret"), (":ecr:", "AWS::ECR::Repository"),
          (":execute-api:", "AWS::ApiGateway::RestApi"))


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def resource_type_of(arn):
    for needle, t in _RTYPE:
        if arn.startswith(needle) or needle in arn[:40]:
            return t
    return "AWS::IAM::Role" if ":role/" in arn else "AWS::Resource"


# ================================================================== findings
def finding_id(analyzer_name, kind, resource, principal=""):
    return hashlib.sha1(f"{analyzer_name}|{kind}|{resource}|{principal}".encode()).hexdigest()[:20]


def _cond_restricts(cond, account):
    """True when the statement's Condition pins the caller to this account (so a `*` principal is not external)."""
    for op, kv in (cond or {}).items():
        base = op.split(":", 1)[-1]
        if "Not" in base or base.startswith(("Bool", "Null", "Ip")):
            continue
        for k, vals in (kv or {}).items():
            if str(k).lower() not in _RESTRICT_KEYS or str(k).lower() in ("aws:sourceorgid", "aws:principalorgid"):
                continue
            vs = [str(x) for x in _as_list(vals)]
            if vs and all(account in v for v in vs):
                return True
    return False


def _flat_cond(cond):
    out = {}
    for op, kv in (cond or {}).items():
        for k, v in (kv or {}).items():
            vs = _as_list(v)
            out[str(k)] = str(vs[0]) if vs else ""
    return out


def _external(doc, account, trust=False):
    """[(principal_key, principal_value, statement)] naming a principal outside `account` (or *, unrestricted by account conditions)."""
    out = []
    for st in analyze_aws._stmt_list(doc):
        if str(st.get("Effect", "")).lower() != "allow" or "Principal" not in st:
            continue
        pr = st["Principal"]
        entries = []
        if pr == "*":
            entries.append(("AWS", "*"))
        elif isinstance(pr, dict):
            for k, v in pr.items():
                for x in _as_list(v):
                    entries.append((k, str(x)))
        for k, v in entries:
            if k == "Service":
                continue
            if k == "Federated":
                if trust:
                    out.append((k, v, st))
                continue
            if v == "*":
                if _cond_restricts(st.get("Condition"), account):
                    continue
                out.append((k, v, st))
                continue
            acct = v.split(":")[4] if v.startswith("arn:") and len(v.split(":")) > 4 else (v if re.fullmatch(r"\d{12}", v) else "")
            if acct and acct != account:
                if _cond_restricts(st.get("Condition"), account):
                    continue
                out.append((k, v, st))
    return out


def _stmt_actions(st):
    return [str(a) for a in _as_list(st.get("Action"))] if "Action" in st else []


def compute(analyzer, ctx):
    """-> findings (dicts), deterministic ids. `analyzer` = the stored record ({name, type, created, archived, unused_access_age})."""
    store, state = ctx["store"], ctx.get("state") or {}
    account = getattr(store, "account_id", "") or ""
    out = []
    if analyzer["type"] not in UNUSED_TYPES:
        pols = dict(state.get("resource_policies") or {})
        for arn, doc in pols.items():
            if ":alias/" in arn or not isinstance(doc, dict):
                continue
            if ":secret:" in arn and any(o != arn and o.startswith(arn + "-") for o in pols):
                continue                    # the by-name duplicate the host feeds for suffix-less calls
            for k, v, st in _external(doc, account):
                out.append(_ext_finding(analyzer, resource_type_of(arn), arn, k, v, st, account, ctx))
        for r in (getattr(store, "roles", None) or {}).values():
            for k, v, st in _external(r.get("assume_role_policy_document") or {}, account, trust=True):
                out.append(_ext_finding(analyzer, "AWS::IAM::Role", r["arn"], k, v, st, account, ctx))
    else:
        out.extend(_unused(analyzer, ctx))
    return out


def _ext_finding(analyzer, rtype, resource, pkey, pval, st, account, ctx):
    fid = finding_id(analyzer["name"], "ExternalAccess", resource, pkey + ":" + pval)
    cond = _flat_cond(st.get("Condition"))
    return {"id": fid, "type": "ExternalAccess", "resource_type": rtype, "resource": resource, "principals": [pval],
            "principal": {pkey: pval}, "action": _stmt_actions(st), "condition": cond,
            "isPublic": pval == "*" and not cond, "status": "ARCHIVED" if fid in analyzer.get("archived", []) else "ACTIVE",
            "created": analyzer["created"], "resourceOwnerAccount": account}


def _days(iso):
    for fmt in ("%Y-%m-%dT%H:%M:%S.000Z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return max(0, (datetime.now(timezone.utc) - datetime.strptime(iso, fmt).replace(tzinfo=timezone.utc)).days)
        except Exception:
            continue
    return 0


def last_accessed(ctx):
    """{principal_arn: {service_namespace: {"last": iso, "actions": {action: iso}}}} from the IAM activity log AND the decision ring
    (allowed decisions only: a request that was denied is not an access). Roles appear here only through the ring."""
    store, out = ctx["store"], {}

    def add(arn, svc, action, t):
        ent = out.setdefault(arn, {}).setdefault(svc, {"last": t, "actions": {}})
        ent["last"] = max(ent["last"], t)
        if action:
            ent["actions"][action] = max(ent["actions"].get(action, ""), t)

    for e in getattr(store, "activity", None) or []:
        svc = str(e.get("service") or "")
        add(e["principal_arn"], svc, f"{svc}:{e['action']}" if e.get("action") else "", str(e.get("time") or ""))
    for r in ctx.get("audit") or []:
        if r.get("cloud") != "aws" or r.get("decision") not in ("allow", "would_deny") and r.get("decision") != "allow":
            continue
        act, pr = str(r.get("action") or ""), str(r.get("principal") or "")
        if ":" not in act or not pr.startswith("arn:"):
            continue
        m = re.match(r"^arn:([^:]*):sts::(\d*):assumed-role/([^/]+)/", pr)
        arn = f"arn:{m.group(1)}:iam::{m.group(2)}:role/{m.group(3)}" if m else pr
        add(arn, act.split(":", 1)[0], act, str(r.get("time") or ""))
    return out


def _unused(analyzer, ctx):
    store, state = ctx["store"], ctx.get("state") or {}
    age = int(analyzer.get("unused_access_age", 90) or 90)
    acct = store.account_id
    seen = last_accessed(ctx)
    out = []

    def mk(kind, rtype, resource, extra, who=None):
        fid = finding_id(analyzer["name"], kind, resource, extra.get("_key", ""))
        d = {"id": fid, "type": kind, "resource_type": rtype, "resource": resource, "principals": [who] if who else [],
             "status": "ARCHIVED" if fid in analyzer.get("archived", []) else "ACTIVE", "created": analyzer["created"], "resourceOwnerAccount": acct}
        d.update({k: v for k, v in extra.items() if k != "_key"})
        out.append(d)

    used_users = {a.rsplit("/", 1)[-1] for a, v in seen.items() if ":user/" in a and v}
    for k in (getattr(store, "access_keys", None) or {}).values():
        uarn = (store.users.get(k["user_name"]) or {}).get("arn") or f"arn:aws:iam::{acct}:user/{k['user_name']}"
        if k["user_name"] in used_users or _days(k["created"]) < age:
            continue
        mk("UnusedIAMUserAccessKey", "AWS::IAM::AccessKey", k["access_key_id"], {"age_days": _days(k["created"]), "access_key_id": k["access_key_id"]}, uarn)
    for r in (getattr(store, "roles", None) or {}).values():
        if r["arn"] in seen or _days(r.get("created") or analyzer["created"]) < age:
            continue
        mk("UnusedIAMRole", "AWS::IAM::Role", r["arn"], {"age_days": _days(r.get("created") or "")})
    principals = state.get("principals") or {}
    for arn, rec in principals.items():
        if ":assumed-role/" in arn:
            continue
        ent = (getattr(store, "users", {}) or {}).get(arn.rsplit("/", 1)[-1]) if ":user/" in arn else (getattr(store, "roles", {}) or {}).get(arn.rsplit("/", 1)[-1])
        if not ent or _days(ent.get("created") or "") < age:
            continue
        granted = {}
        for p in list(rec.get("policies") or []):
            for st in analyze_aws._stmt_list(p.get("document") or {}):
                if str(st.get("Effect", "")).lower() == "allow":
                    for a in _stmt_actions(st):
                        if ":" in a and not a.startswith("*"):
                            granted.setdefault(a.split(":", 1)[0].lower(), set()).add(a)
        used = {s.lower() for s in (seen.get(arn) or {})}
        for svc, acts in sorted(granted.items()):
            if svc in used:
                continue
            mk("UnusedPermission", "AWS::IAM::User" if ":user/" in arn else "AWS::IAM::Role", arn,
               {"service_namespace": svc, "actions": sorted(acts), "_key": svc}, arn)
    return out


# ------------------------------------------------------------------ REST (JSON) shapes
def _ext_summary(f, arn):
    return {"id": f["id"], "resourceType": f["resource_type"], "resource": f["resource"], "status": f["status"], "isPublic": f["isPublic"],
            "principal": f["principal"], "action": f["action"], "condition": f["condition"], "createdAt": f["created"], "analyzedAt": f["created"],
            "updatedAt": f["created"], "resourceOwnerAccount": f["resourceOwnerAccount"], "analyzerArn": arn}


def _v2_summary(f):
    d = {"id": f["id"], "resourceType": f["resource_type"], "resource": f["resource"], "status": f["status"], "findingType": _V2TYPE[f["type"]],
         "createdAt": f["created"], "analyzedAt": f["created"], "updatedAt": f["created"], "resourceOwnerAccount": f["resourceOwnerAccount"]}
    return d


_V2TYPE = {"ExternalAccess": "ExternalAccess", "UnusedIAMUserAccessKey": "UnusedIAMUserAccessKey", "UnusedIAMRole": "UnusedIAMRole",
           "UnusedPermission": "UnusedPermission"}


def _v2_detail(f):
    d = _v2_summary(f)
    if f["type"] == "ExternalAccess":
        det = {"externalAccessDetails": {"action": f["action"], "condition": f["condition"], "isPublic": f["isPublic"], "principal": f["principal"], "sources": [{"type": "POLICY"}]}}
    elif f["type"] == "UnusedIAMUserAccessKey":
        det = {"unusedIamUserAccessKeyDetails": {"accessKeyId": f["access_key_id"]}}
    elif f["type"] == "UnusedIAMRole":
        det = {"unusedIamRoleDetails": {}}
    else:
        det = {"unusedPermissionDetails": {"serviceNamespace": f["service_namespace"], "actions": [{"action": a} for a in f["actions"]]}}
    d["findingDetails"] = [det]
    return d


# ================================================================== policy checks
def _link(sev, code):
    return ("https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-reference-policy-checks.html#access-analyzer-reference-policy-checks-"
            + {"ERROR": "error", "WARNING": "warning", "SECURITY_WARNING": "security-warning", "SUGGESTION": "suggestion"}[sev] + "-" + code.lower().replace("_", "-"))


def _loc(path, span):
    loc = {"path": [({"index": p} if isinstance(p, int) else {"value": p}) for p in path]}
    if span:
        loc["span"] = {"start": {"line": span[0][0], "column": span[0][1], "offset": span[0][2]},
                       "end": {"line": span[1][0], "column": span[1][1], "offset": span[1][2]}}
    return loc


def _wild_actions(pattern):
    """Catalog actions matched by an action pattern, or None when the service has no catalog in this bundle."""
    svc, _, name = pattern.partition(":")
    if not name:
        return None
    cat = analyze_aws.catalog(svc)
    if cat is None:
        return None
    names = list(cat.get("actions", {}))
    return [f"{svc.lower()}:{n}" for n in names if fnmatch.fnmatchcase(n.lower(), name.lower())]


def validate_policy(doc, policy_type="IDENTITY_POLICY", text=None):
    """-> [finding dicts in the ValidatePolicy shape]. Only issue codes this implementation can establish from the catalogs / document
    structure are emitted (see docs/architecture/v4.0/branches/iam-simulate-analyze.md for the list)."""
    text = text if text is not None else json.dumps(doc, indent=2)
    spans = analyze_aws.statement_spans(text)
    out = []

    def add(sev, code, msg, path, span=None):
        out.append({"findingDetails": msg, "findingType": sev, "issueCode": code, "learnMoreLink": _link(sev, code), "locations": [_loc(path, span)]})

    if "Version" not in doc:
        add("SUGGESTION", "MISSING_VERSION", "The policy does not specify a version. Add Version 2012-10-17 so that policy variables and newer features behave as documented.", ["Version"])
    stmts = doc.get("Statement")
    single = isinstance(stmts, dict)
    for i, st in enumerate(analyze_aws._stmt_list(doc)):
        base = ["Statement"] if single else ["Statement", i]
        sp = spans[i] if i < len(spans) else None
        if "Action" not in st and "NotAction" not in st:
            add("ERROR", "MISSING_ACTION", "Missing Action or NotAction element. Add one of them to the statement.", base, sp)
        if policy_type in ("IDENTITY_POLICY", "SERVICE_CONTROL_POLICY") and "Resource" not in st and "NotResource" not in st and policy_type == "IDENTITY_POLICY":
            add("ERROR", "MISSING_RESOURCE", "Missing Resource or NotResource element. Add one of them to the statement.", base, sp)
        if policy_type in ("RESOURCE_POLICY", "RESOURCE_CONTROL_POLICY") and "Principal" not in st and "NotPrincipal" not in st:
            add("ERROR", "MISSING_PRINCIPAL", "Missing Principal element. Add a Principal or NotPrincipal element to the statement.", base, sp)
        acts = _as_list(st.get("Action")) if "Action" in st else []
        for j, a in enumerate(acts):
            a = str(a)
            if a == "*":
                continue
            got = _wild_actions(a)
            if got is not None and not got:
                add("ERROR", "INVALID_ACTION", f"The action {a} does not exist. Verify that the action name is correct.", base + ["Action", j] if isinstance(st.get("Action"), list) else base + ["Action"], sp)
        _deep_checks(st, base, sp, add, policy_type)
        eff = str(st.get("Effect", "")).lower()
        res = [str(r) for r in _as_list(st.get("Resource"))]
        if eff == "allow" and policy_type == "IDENTITY_POLICY" and any(r == "*" or r.endswith("/*") and r.startswith("arn:aws:iam::") or r in ("arn:aws:iam::*:role/*",) for r in res):
            lit = any(str(a).lower() == "iam:passrole" for a in acts)
            wild = any(a == "*" or (":" in str(a) and str(a).split(":", 1)[0].lower() in ("iam", "*") and "*" in str(a) and fnmatch.fnmatchcase("passrole", str(a).split(":", 1)[1].lower())) for a in acts)
            if lit:
                add("SECURITY_WARNING", "PASS_ROLE_WITH_STAR_IN_RESOURCE", "Using the iam:PassRole action with wildcards (*) in the resource can be overly permissive because it allows iam:PassRole permissions on multiple resources. We recommend that you specify resource ARNs or add the iam:PassedToService condition key to your statement.", base + ["Resource"], sp)
            elif wild:
                add("SECURITY_WARNING", "PASS_ROLE_WITH_STAR_IN_ACTION_AND_RESOURCE", "Using the iam:PassRole action with wildcards (*) in the action and the resource can be overly permissive because it allows iam:PassRole permissions on multiple resources. We recommend that you specify resource ARNs or add the iam:PassedToService condition key to your statement.", base + ["Resource"], sp)
    return out


# ---- catalog-provable resource / condition-key / redundancy checks (ValidatePolicy beyond structure)
_TPL_CACHE = {}


def _tpl_regex(tpl):
    parts = re.split(r"\$\{[^}]*\}", tpl)
    rx = ""
    for n, part in enumerate(parts):
        rx += re.escape(part)
        if n < len(parts) - 1:
            rx += ".*" if n == len(parts) - 2 and not parts[-1] and part.endswith("/") else "[^:/]*"     # a trailing placeholder (object key) may contain '/'
    return re.compile("^" + rx + "$")


def _resource_types(cat, svc, arn):
    """Resource-type names of the service catalog whose ARN templates match `arn` (empty when none)."""
    key = (svc, id(cat))
    if key not in _TPL_CACHE:
        _TPL_CACHE[key] = [(name, _tpl_regex(t)) for name, tpls in cat.get("resources", {}).items() for t in tpls]
    return [n for n, rx in _TPL_CACHE[key] if rx.match(arn)]


def _canon_key(k):
    k = re.sub(r"\$\{[^}]*\}", "<key>", k)
    return re.sub(r"/[^/]*$", "/<key>", k).lower() if "/" in k else k.lower()


def _catalog_key_set(cat):
    return {_canon_key(k) for k in cat.get("conditionKeys", {})}


def _cond_keys(cond):
    out = []
    for op, body in (cond or {}).items():
        if isinstance(body, dict):
            out.extend((op, k) for k in body)
    return out


def _deep_checks(st, base, sp, add, policy_type):
    acts = [str(a) for a in _as_list(st.get("Action"))] if "Action" in st else []
    singles = [a for a in acts if ":" in a and "*" not in a and "?" not in a]
    res_field = "Resource"
    res = [str(r) for r in _as_list(st.get(res_field))] if res_field in st else []
    rpath = base + [res_field]
    done = set()
    for r in res:
        if not r.startswith("arn:") or r.count(":") < 5:
            continue
        _, _part, rsvc, region, _acct, rest = r.split(":", 5)
        if "$" in r:
            continue
        for a in singles:
            svc, _, name = a.partition(":")
            cat = analyze_aws.catalog(svc)
            if cat is None or name not in cat.get("actions", {}):
                continue
            ainfo = cat["actions"][name]
            if rsvc and rsvc != "*" and rsvc.lower() != svc.lower():
                if not (svc.lower() == "s3" and rsvc.lower() == "s3-object-lambda"):
                    add("ERROR", "UNSUPPORTED_RESOURCE_FOR_ACTION", f"The resource {r} is for service {rsvc}, but the action {a} belongs to service {svc}. Use a resource of the {svc} service.", rpath, sp)
                continue
            if (r, a) in done:
                continue
            done.add((r, a))
            if region and region != "*" and ("region", r) not in done:
                done.add(("region", r))
                regionless = f"arn:{_part}:{rsvc}::{_acct}:{rest}"
                rt = _resource_types(cat, svc, regionless)
                if rt and not any("${Region}" in t for n in rt for t in cat["resources"][n]):
                    add("ERROR", "INVALID_ARN_REGION", f"The resource ARN {r} specifies the Region {region}, but the resource type {'/'.join(rt)} of service {svc} has no Region. Leave the Region field of the ARN empty.", rpath, sp)
                    continue
            types = _resource_types(cat, svc, r)
            sup = ainfo.get("r") or []
            if types and sup and not (set(types) & set(sup)):
                add("ERROR", "UNSUPPORTED_ACTION_FOR_RESOURCE", f"The action {a} does not support the resource type {'/'.join(types)} of the resource {r}. Supported resource types for this action: {', '.join(sup)}.", rpath, sp)
    # condition keys: a service-prefixed key that the service catalog does not define
    seen_svcs = {a.partition(":")[0].lower() for a in acts if ":" in a and not a.startswith("*")}
    for op, key in _cond_keys(st.get("Condition")):
        kp = key.partition(":")
        if not kp[2] or kp[0].lower() == "aws":
            continue
        cat = analyze_aws.catalog(kp[0])
        if cat is None:
            continue
        ks = _catalog_key_set(cat)
        if _canon_key(key) not in ks:
            add("ERROR", "INVALID_CONDITION_KEY", f"The condition key {key} does not exist for service {kp[0]}. Verify that the condition key name is correct.", base + ["Condition", op, key], sp)
    # redundant actions (same statement)
    lowered = [a.lower() for a in acts]
    for j, a in enumerate(lowered):
        dup = a in lowered[:j]
        cover = next((b for b in lowered if b != a and "*" in b and fnmatch.fnmatchcase(a, b)), None)
        if dup or cover:
            why = "is listed more than once" if dup else f"is already covered by {cover}"
            add("SUGGESTION", "REDUNDANT_ACTION", f"The action {acts[j]} {why} in this statement. Remove the redundant action.", base + ["Action", j] if isinstance(st.get("Action"), list) else base + ["Action"], sp)


def _expand_statement_actions(st):
    """Concrete action ids a statement's Action / NotAction can cover (catalog-expanded; unknown services keep the literal pattern)."""
    acts, full = [], None
    if "Action" in st:
        for a in (str(x) for x in _as_list(st["Action"])):
            if a == "*":
                for pre in analyze_aws.catalog_prefixes():
                    acts.extend(_wild_actions(pre + ":*") or [])
                acts.append("*")
                continue
            got = _wild_actions(a)
            acts.extend(got if got else [a])
    elif "NotAction" in st:
        ex = [str(x) for x in _as_list(st["NotAction"])]
        for pre in analyze_aws.catalog_prefixes():
            for a in _wild_actions(pre + ":*") or []:
                if not any(fnmatch.fnmatchcase(a.lower(), e.lower()) for e in ex):
                    acts.append(a)
    return list(dict.fromkeys(acts))[:6000]


def _strip_cond(doc):
    d = dict(doc)
    d["Statement"] = [({k: v for k, v in s.items() if k != "Condition"} if str(s.get("Effect", "")).lower() == "allow" else s) for s in analyze_aws._stmt_list(doc)]
    return d


def _grants(docs, action, resource, resource_based=False, principal=None, ignore_conditions=False):
    pols = aws_eval._norm_policies(docs, "p")
    ctx = aws_eval._Ctx({})
    ok = None
    if resource_based:
        fake = principal or {"arn": "", "type": "anonymous"}
        ok = lambda st: aws_eval._principal_match(st, fake)       # noqa: E731
    al, dn = aws_eval._collect(pols, "p", action, resource, ctx, resource_based=resource_based, principal_ok=ok)
    return al, dn


def _equal_cond_covers(existing_docs, st, action, resource, resource_based=False, principal=None):
    cond = st.get("Condition")
    if not cond:
        return False
    for doc in existing_docs:
        for es in analyze_aws._stmt_list(doc):
            if str(es.get("Effect", "")).lower() != "allow" or es.get("Condition") != cond:
                continue
            probe = {k: v for k, v in es.items() if k != "Condition"}
            fake = principal or {"arn": "", "type": "anonymous"}
            if resource_based and not aws_eval._principal_match(probe, fake):
                continue
            if aws_eval._stmt_applies(probe, action, resource, aws_eval._Ctx({}), resource_based):
                return True
    return False


def check_no_new_access(new_doc, existing_doc, policy_type="IDENTITY_POLICY"):
    """-> (result "PASS"|"FAIL", [reasons])."""
    rb = policy_type == "RESOURCE_POLICY"
    reasons = []
    new_nc = _strip_cond(new_doc)
    for i, st in enumerate(analyze_aws._stmt_list(new_doc)):
        if str(st.get("Effect", "")).lower() != "allow":
            continue
        res = [str(r) for r in _as_list(st.get("Resource"))] or ["*"]
        if "NotResource" in st:
            res = ["*"]
        principals = [None]
        if rb:
            principals = []
            pr = st.get("Principal")
            ents = [("AWS", "*")] if pr == "*" else [(k, str(x)) for k, v in (pr or {}).items() for x in _as_list(v)]
            for k, v in ents or [("AWS", "*")]:
                if v == "*":
                    principals.append({"arn": "", "type": "anonymous", "_n": "*"})
                elif re.fullmatch(r"\d{12}", v) or re.fullmatch(r"arn:[^:]*:iam::\d{12}:root", v):
                    a = v if v.isdigit() else v.split(":")[4]
                    principals.append({"arn": f"arn:aws:iam::{a}:root", "type": "root", "account": a, "_n": v})
                elif k == "Service":
                    principals.append({"type": "service", "service": v, "arn": v, "_n": v})
                else:
                    principals.append({"arn": v, "type": "user" if ":user/" in v else "role", "account": v.split(":")[4] if v.startswith("arn:") else "", "_n": v})
        hits = []
        for a in _expand_statement_actions(st):
            for r in res:
                for pr_ in principals:
                    al, dn = _grants([new_nc], a, r, rb, pr_)
                    if not al or dn:
                        continue
                    eal, edn = _grants([existing_doc], a, r, rb, pr_)
                    if (eal and not edn) or _equal_cond_covers([existing_doc], st, a, r, rb, pr_):
                        continue
                    hits.append((a, r, (pr_ or {}).get("_n")))
        if hits:
            n = len(hits)
            a, r, p = hits[0]
            reasons.append({"description": f"New access in the statement: the action {a} on {r}" + (f" for principal {p}" if p else "")
                            + (f" (and {n - 1} more)" if n > 1 else "") + " is not granted by the existing policy.",
                            "statementIndex": i, **({"statementId": st["Sid"]} if st.get("Sid") else {})})
    return ("FAIL" if reasons else "PASS"), reasons


def check_access_not_granted(doc, access, policy_type="IDENTITY_POLICY"):
    """access = [{"actions": [...], "resources": [...]}]. -> (result, reasons)."""
    rb = policy_type == "RESOURCE_POLICY"
    reasons, seen = [], set()
    nc = doc
    for entry in access or []:
        acts = [str(a) for a in entry.get("actions") or []]
        ress = [str(r) for r in entry.get("resources") or []]
        for a in acts:
            concrete = _wild_actions(a) or [a] if "*" in a else [a]
            for ca in concrete:
                for i, st in enumerate(analyze_aws._stmt_list(doc)):
                    if str(st.get("Effect", "")).lower() != "allow":
                        continue
                    fake = {"arn": "", "type": "anonymous"} if rb else None
                    for r in (ress or [None]):
                        probe = {k: v for k, v in st.items() if k != "Condition"}
                        if rb and not aws_eval._principal_match(probe, fake) and "Principal" not in st:
                            continue
                        if r is None:
                            hit = (any(aws_eval._wc(x, True).match(ca) for x in _as_list(st.get("Action"))) if "Action" in st
                                   else ("NotAction" in st and not any(aws_eval._wc(x, True).match(ca) for x in _as_list(st.get("NotAction")))))
                        else:
                            hit = aws_eval._stmt_applies(probe, ca, r, aws_eval._Ctx({}), rb)
                        if hit and (i, ca, r) not in seen:
                            seen.add((i, ca, r))
                            reasons.append({"description": f"The policy grants access to {ca}" + (f" on {r}" if r else "") + f" in statement {i}.",
                                            "statementIndex": i, **({"statementId": st["Sid"]} if st.get("Sid") else {})})
    # an explicit deny of the same (action, resource) cancels the grant
    return ("FAIL" if reasons else "PASS"), reasons


# ================================================================== REST dispatch
def _json(status, obj, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    return {"status": status, "headers": h, "body": json.dumps(obj).encode()}


def _err(status, etype, msg, extra=None):
    return _json(status, dict({"message": msg}, **(extra or {})), {"x-amzn-errortype": etype})


def _page(items, body, query, key):
    try:
        n = int(body.get("maxResults") or query.get("maxResults") or 100)
    except (TypeError, ValueError):
        n = 100
    tok = body.get("nextToken") or query.get("nextToken")
    start = int(tok) if str(tok or "").isdigit() else 0
    chunk = items[start:start + n]
    out = {key: chunk}
    if start + n < len(items):
        out["nextToken"] = str(start + n)
    return out


def _analyzer_summary(a):
    d = {"arn": a["arn"], "name": a["name"], "type": a["type"], "createdAt": a["created"], "status": "ACTIVE", "tags": a.get("tags") or {}}
    if a["type"] in UNUSED_TYPES:
        d["configuration"] = {"unusedAccess": {"unusedAccessAge": int(a.get("unused_access_age", 90))}}
    return d


def _find_analyzer(store, arn_or_name):
    name = str(arn_or_name or "").rsplit("/", 1)[-1]
    return store.analyzers.get(name)


def matches(method, path, headers=None):
    """Is this an Access Analyzer REST request? (credential scope service `access-analyzer`, or an access-analyzer host)."""
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    scope = "/access-analyzer/aws4_request" in h.get("authorization", "")
    host = h.get("host", "").lower().startswith("access-analyzer.")
    if not (scope or host):
        return False
    p = path.split("?", 1)[0]
    return bool(re.match(r"^/(analyzer|finding|findingv2|policy/(validation|check-no-new-access|check-access-not-granted|check-no-public-access)|resource/scan|recommendation)(/|$)", p))


def dispatch(method, path, query, body, ctx):
    """-> router response {status, headers, body}. `body` = bytes."""
    method = method.upper()
    p = path.split("?", 1)[0].rstrip("/") or "/"
    q = query or {}
    q = {k: (v[0] if isinstance(v, list) and v else v) for k, v in q.items()}
    try:
        req = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(req, dict):
            raise ValueError
    except Exception:
        return _err(400, "ValidationException", "Request body is not valid JSON.")
    store = ctx["store"]
    region, acct = ctx.get("region") or "us-east-1", store.account_id
    now = ctx.get("now") or _now()

    # ---- policy checks
    if method == "POST" and p == "/policy/validation":
        ptype = req.get("policyType") or "IDENTITY_POLICY"
        if ptype not in ("IDENTITY_POLICY", "RESOURCE_POLICY", "SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY"):
            return _err(400, "ValidationException", f"policyType {ptype} is not valid.")
        raw = req.get("policyDocument")
        try:
            doc = analyze_aws.parse_doc(raw)
        except ValueError as e:
            return _err(400, "ValidationException", "Policy document is not valid JSON: " + str(e))
        fs = validate_policy(doc, ptype, raw if isinstance(raw, str) else None)
        return _json(200, _page(fs, {}, q, "findings"))
    if method == "POST" and p in ("/policy/check-no-new-access", "/policy/check-access-not-granted"):
        ptype = req.get("policyType") or "IDENTITY_POLICY"
        try:
            if p.endswith("no-new-access"):
                new, old = analyze_aws.parse_doc(req.get("newPolicyDocument")), analyze_aws.parse_doc(req.get("existingPolicyDocument"))
                res, reasons = check_no_new_access(new, old, ptype)
                msg = "The modified permissions did not grant new access." if res == "PASS" else "The modified permissions grant new access."
            else:
                doc = analyze_aws.parse_doc(req.get("policyDocument"))
                access = req.get("access") or []
                if not access:
                    return _err(400, "ValidationException", "access is required.")
                res, reasons = check_access_not_granted(doc, access, ptype)
                msg = "The policy document does not grant access to perform the listed actions or resources." if res == "PASS" else "The policy document grants access to perform one or more of the listed actions or resources."
        except ValueError as e:
            return _err(400, "ValidationException", "Policy document is not valid JSON: " + str(e))
        return _json(200, {"result": res, "message": msg, "reasons": reasons})

    # ---- analyzers
    if p == "/analyzer" and method == "PUT":
        name, atype = str(req.get("analyzerName") or "").strip(), str(req.get("type") or "").strip()
        if not name or atype not in ANALYZER_TYPES:
            return _err(400, "ValidationException", f"analyzerName and type ({', '.join(ANALYZER_TYPES)}) are required.")
        if name in store.analyzers:
            return _err(409, "ConflictException", f"Analyzer {name} already exists.", {"resourceId": name, "resourceType": "Analyzer"})
        cfg = ((req.get("configuration") or {}).get("unusedAccess") or {})
        store.analyzers[name] = {"name": name, "arn": f"arn:aws:access-analyzer:{region}:{acct}:analyzer/{name}", "type": atype, "created": now,
                                 "unused_access_age": int(cfg.get("unusedAccessAge") or 90), "archived": [], "tags": req.get("tags") or {}}
        store.persist()
        return _json(200, {"arn": store.analyzers[name]["arn"]})
    if p == "/analyzer" and method == "GET":
        items = sorted(store.analyzers.values(), key=lambda a: a["created"])
        t = q.get("type")
        return _json(200, _page([_analyzer_summary(a) for a in items if not t or a["type"] == t], {}, q, "analyzers"))
    m = re.match(r"^/analyzer/([^/]+)$", p)
    if m:
        a = store.analyzers.get(m.group(1))
        if a is None:
            return _err(404, "ResourceNotFoundException", f"Analyzer {m.group(1)} not found.", {"resourceId": m.group(1), "resourceType": "Analyzer"})
        if method == "GET":
            return _json(200, {"analyzer": _analyzer_summary(a)})
        if method == "DELETE":
            del store.analyzers[m.group(1)]
            store.persist()
            return {"status": 200, "headers": {"content-type": "application/json"}, "body": b""}
    if p == "/resource/scan" and method == "POST":
        if _find_analyzer(store, req.get("analyzerArn")) is None:
            return _err(404, "ResourceNotFoundException", "Analyzer not found.")
        return {"status": 200, "headers": {"content-type": "application/json"}, "body": b""}

    # ---- findings
    if p in ("/finding", "/findingv2") and method in ("POST", "PUT") or re.match(r"^/finding(v2)?/[^/]+$", p) and method == "GET":
        v2 = p.startswith("/findingv2")
        arn = req.get("analyzerArn") or q.get("analyzerArn")
        a = _find_analyzer(store, arn)
        if a is None:
            return _err(404, "ResourceNotFoundException", f"Analyzer {arn} not found.", {"resourceId": str(arn), "resourceType": "Analyzer"})
        fs = compute(a, ctx)
        if method == "PUT":                                             # UpdateFindings
            ids = [str(i) for i in req.get("ids") or []]
            st = req.get("status")
            if st not in ("ACTIVE", "ARCHIVED"):
                return _err(400, "ValidationException", "status must be ACTIVE or ARCHIVED.")
            arch = set(a.get("archived", []))
            (arch.update if st == "ARCHIVED" else arch.difference_update)(ids)
            a["archived"] = sorted(arch)
            store.persist()
            return {"status": 200, "headers": {"content-type": "application/json"}, "body": b""}
        if method == "POST":                                            # ListFindings(V2)
            flt = req.get("filter") or {}
            out = []
            for f in fs:
                if v2 is False and f["type"] != "ExternalAccess":
                    continue
                row = _v2_summary(f) if v2 else _ext_summary(f, a["arn"])
                if all(_crit(row, k, c) for k, c in flt.items()):
                    out.append(row)
            srt = req.get("sort") or {}
            if srt.get("attributeName"):
                out.sort(key=lambda r: str(r.get(srt["attributeName"], "")), reverse=srt.get("orderBy") == "DESC")
            return _json(200, _page(out, req, q, "findings"))
        fid = p.rsplit("/", 1)[-1]                                      # GetFinding(V2)
        for f in fs:
            if f["id"] == fid:
                return _json(200, _v2_detail(f) if v2 else {"finding": _ext_summary(f, a["arn"])})
        return _err(404, "ResourceNotFoundException", f"Finding {fid} not found.", {"resourceId": fid, "resourceType": "Finding"})
    return _err(404, "UnknownOperationException", f"{method} {p} is not an Access Analyzer operation.")


def _crit(row, key, crit):
    v = row
    for part in str(key).split("."):
        v = v.get(part) if isinstance(v, dict) else None
    sv = "" if v is None else str(v if not isinstance(v, bool) else str(v).lower())
    if "eq" in crit and sv not in [str(x) for x in crit["eq"]]:
        return False
    if "neq" in crit and sv in [str(x) for x in crit["neq"]]:
        return False
    if "contains" in crit and not any(str(x) in sv for x in crit["contains"]):
        return False
    if "exists" in crit and (v is not None) != bool(crit["exists"]):
        return False
    return True
