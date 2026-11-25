"""GCP Policy Troubleshooter (`policytroubleshooter.googleapis.com` v1 + v3 `iam:troubleshoot`) and Cloud Asset `analyzeIamPolicy`
answered by `gcp_eval` over the hierarchy state (pure Python, Pyodide-safe: no fastapi / socket).

  troubleshoot_v1(access_tuple, state)      -> {access, explainedPolicies[...]}                 (allow policies only, like the real v1)
  troubleshoot_v3(access_tuple, state)      -> {overallAccessState, allowPolicyExplanation, denyPolicyExplanation, pabPolicyExplanation}
  analyze_iam_policy(scope, params, state)  -> {mainAnalysis{analysisResults[...]}, serviceAccountImpersonationAnalysis, fullyExplored}

The state is the engine's GCP state (core/iam_state_adapters.gcp_state / iam_state_nano.gcp_state): allow_policies, deny_policies,
custom_roles, hierarchy, groups, pab_policies/pab_bindings, catalog. Decisions come from gcp_eval's own helpers, so the explanation
and `evaluate()` / `:testIamPermissions` can never disagree (the test asserts it)."""
from __future__ import annotations

import datetime as _dt
import re

from . import gcp_eval as G

_STORAGE = re.compile(r"^projects/_/buckets(/|$)")
_HOSTS = (("projects/_/buckets", "storage.googleapis.com"), ("topics", "pubsub.googleapis.com"), ("subscriptions", "pubsub.googleapis.com"),
          ("secrets", "secretmanager.googleapis.com"), ("/instances/", "compute.googleapis.com"), ("/datasets/", "bigquery.googleapis.com"),
          ("/serviceAccounts/", "iam.googleapis.com"), ("/keyRings/", "cloudkms.googleapis.com"))


class GcpError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def full_name(point):
    """Attachment point 'projects/p/...' -> '//service.googleapis.com/projects/p/...' (best-effort host guess)."""
    p = str(point or "").strip("/")
    for needle, host in _HOSTS:
        if (needle.startswith("/") and needle in "/" + p) or (not needle.startswith("/") and p.startswith(needle)):
            return f"//{host}/{p}"
    return f"//cloudresourcemanager.googleapis.com/{p}"


def _member(raw):
    """Principal as the API takes it: a prefixed member, or a bare email (service accounts end in gserviceaccount.com)."""
    raw = str(raw or "").strip()
    if not raw:
        raise GcpError(400, "INVALID_ARGUMENT", "accessTuple.principal is required.")
    if ":" in raw or raw.startswith(("principal", "allUsers", "allAuthenticatedUsers")):
        return raw
    return ("serviceAccount:" if raw.endswith("gserviceaccount.com") else "user:") + raw


def _known_permission(perm, state):
    cat = state.get("catalog") or G.load_catalog()
    allp = cat.get("permissions") or []
    if not allp or perm in set(allp):
        return True
    if state.get("catalog") is None:
        return False                                     # the full on-disk catalog (Mesh) does not know it
    try:                                                 # Nano: state["catalog"] only holds the services of bound roles; ask the permission's own service
        from . import catalog_loader
        return perm in (catalog_loader.load("gcp", perm.split(".")[0]).get("permissions") or {})
    except Exception:
        return True                                      # service catalog not loaded: unverifiable, not invalid


def _eval_cond(expr, ctx, resource):
    env = G._cond_env({"context": ctx}, resource)
    ok, note = G.eval_condition(expr, env)
    return ok, note


def _ctx(cond_ctx):
    """conditionContext of the API -> the engine's context."""
    c = dict(cond_ctx or {})
    out = {}
    t = ((c.get("request") or {}).get("receiveTime"))
    if t:
        out["time"] = t
    if c.get("resource"):
        r = c["resource"]
        out["resource_name"], out["resource_service"], out["resource_type"] = r.get("name"), r.get("service"), r.get("type", "")
    return {k: v for k, v in out.items() if v is not None}


def _cond_expl(cond, ctx, resource):
    if not cond or not cond.get("expression"):
        return True, None
    ok, note = _eval_cond(cond["expression"], ctx, resource)
    if ok is None:
        return None, {"errors": [{"code": 3, "message": note or "condition could not be evaluated"}]}
    return ok, {"value": ok, "evaluationStates": []}


def _bindings(point, state):
    pol = G._lookup(state.get("allow_policies") or {}, point) or {}
    return pol, pol.get("bindings") or []


def _prep(tuple_, state):
    if not isinstance(tuple_, dict):
        raise GcpError(400, "INVALID_ARGUMENT", "accessTuple is required.")
    member = _member(tuple_.get("principal"))
    perm = str(tuple_.get("permission") or "").strip()
    res = str(tuple_.get("fullResourceName") or "").strip()
    if not perm or not res.startswith("//"):
        raise GcpError(400, "INVALID_ARGUMENT", "accessTuple.permission and a //service.googleapis.com/... fullResourceName are required.")
    if not _known_permission(perm, state):
        raise GcpError(400, "INVALID_ARGUMENT", f"Invalid permission: {perm}")
    principal = {"member": member, "type": member.split(":", 1)[0]}
    return principal, perm, res, G.principal_identities(principal, state), G.ancestry(res, state), _ctx(tuple_.get("conditionContext"))


def _allow_explanations(principal, perm, res, ids, chain, ctx, state, v3):
    pols, overall_state = [], "NOT_GRANTED"
    for ap in chain:
        pol, binds = _bindings(ap, state)
        if not binds:
            continue
        bexp, pstate = [], "NOT_GRANTED"
        for b in binds:
            role = b.get("role", "")
            has = perm in G.role_permissions(role, state)
            ms, any_in = {}, False
            for m in b.get("members") or []:
                inc = G._member_matches(m, ids, principal, state)
                any_in = any_in or inc
                ms[m] = {"membership": "MEMBERSHIP_INCLUDED" if inc else "MEMBERSHIP_NOT_INCLUDED",
                         "relevance": "HEURISTIC_RELEVANCE_HIGH" if inc else "HEURISTIC_RELEVANCE_NORMAL"}
            cond = b.get("condition")
            ok, cexp = _cond_expl(cond, ctx, res)
            if has and any_in:
                acc = "GRANTED" if ok is True else ("UNKNOWN_CONDITIONAL" if ok is None else "NOT_GRANTED")
            else:
                acc = "NOT_GRANTED"
            rel = "HEURISTIC_RELEVANCE_HIGH" if has and any_in else "HEURISTIC_RELEVANCE_NORMAL"
            e = {"role": role, "rolePermission": "ROLE_PERMISSION_INCLUDED" if has else "ROLE_PERMISSION_NOT_INCLUDED",
                 "rolePermissionRelevance": "HEURISTIC_RELEVANCE_HIGH" if has else "HEURISTIC_RELEVANCE_NORMAL", "relevance": rel}
            if v3:
                e["allowAccessState"] = "ALLOW_ACCESS_STATE_" + acc
                e["combinedMembership"] = {"membership": "MEMBERSHIP_INCLUDED" if any_in else "MEMBERSHIP_NOT_INCLUDED",
                                           "relevance": "HEURISTIC_RELEVANCE_HIGH" if any_in else "HEURISTIC_RELEVANCE_NORMAL", "memberships": ms}
            else:
                e["access"] = acc
                e["memberships"] = ms
            if cond and cond.get("expression"):
                e["condition"] = cond
                e["conditionExplanation"] = cexp
            bexp.append(e)
            pstate = _worse(pstate, acc)
        key = "allowAccessState" if v3 else "access"
        pre = "ALLOW_ACCESS_STATE_" if v3 else ""
        pr = {key: pre + pstate, "fullResourceName": full_name(ap), "bindingExplanations": bexp,
              "relevance": "HEURISTIC_RELEVANCE_HIGH" if pstate != "NOT_GRANTED" else "HEURISTIC_RELEVANCE_NORMAL",
              "policy": {"version": pol.get("version", 1), "etag": pol.get("etag", ""), "bindings": binds}}
        pols.append(pr)
        overall_state = _worse(overall_state, pstate)
    return pols, overall_state


def _worse(a, b):
    order = {"NOT_GRANTED": 0, "UNKNOWN_CONDITIONAL": 1, "GRANTED": 2}
    return a if order[a] >= order[b] else b


def troubleshoot_v1(tuple_, state):
    principal, perm, res, ids, chain, ctx = _prep(tuple_, state or {})
    state = state or {}
    pols, acc = _allow_explanations(principal, perm, res, ids, chain, ctx, state, False)
    return {"access": acc, "explainedPolicies": pols}


def _deny_explanation(principal, perm, res, ids, chain, ctx, state):
    resources, overall = [], "NOT_DENIED"
    by_point = {}
    for ap, pol, i, dr in G._deny_rules(state, chain):
        by_point.setdefault(ap, {}).setdefault(id(pol), (pol, []))[1].append((i, dr))
    for ap, pols in by_point.items():
        eps, rstate = [], "NOT_DENIED"
        for pol, rules in pols.values():
            exps, pst = [], "NOT_DENIED"
            for i, dr in rules:
                perm_hit = any(G._perm_pattern_match(p, perm) for p in dr.get("deniedPermissions") or [])
                perm_exc = any(G._perm_pattern_match(p, perm) for p in dr.get("exceptionPermissions") or [])
                pr_hit = G._principal_listed(dr.get("deniedPrincipals"), ids, principal, state)
                pr_exc = G._principal_listed(dr.get("exceptionPrincipals"), ids, principal, state)
                cond = dr.get("denialCondition")
                ok, cexp = _cond_expl(cond, ctx, res)
                applies = perm_hit and not perm_exc and pr_hit and not pr_exc
                st = "NOT_DENIED"
                if applies:
                    st = "DENIED" if ok is True else ("UNKNOWN_CONDITIONAL" if ok is None else "NOT_DENIED")
                e = {"denyAccessState": "DENY_ACCESS_STATE_" + st, "relevance": "HEURISTIC_RELEVANCE_HIGH" if applies else "HEURISTIC_RELEVANCE_NORMAL",
                     "combinedDeniedPermission": {"permissionMatchingState": "PERMISSION_PATTERN_MATCHING_STATE_" + ("MATCHED" if perm_hit else "NOT_MATCHED"),
                                                  "relevance": "HEURISTIC_RELEVANCE_HIGH" if perm_hit else "HEURISTIC_RELEVANCE_NORMAL"},
                     "combinedExceptionPermission": {"permissionMatchingState": "PERMISSION_PATTERN_MATCHING_STATE_" + ("MATCHED" if perm_exc else "NOT_MATCHED"),
                                                     "relevance": "HEURISTIC_RELEVANCE_NORMAL"},
                     "combinedDeniedPrincipal": {"membership": "MEMBERSHIP_INCLUDED" if pr_hit else "MEMBERSHIP_NOT_INCLUDED", "relevance": "HEURISTIC_RELEVANCE_NORMAL"},
                     "combinedExceptionPrincipal": {"membership": "MEMBERSHIP_INCLUDED" if pr_exc else "MEMBERSHIP_NOT_INCLUDED", "relevance": "HEURISTIC_RELEVANCE_NORMAL"}}
                if cond and cond.get("expression"):
                    e["denyCondition"] = cond
                    e["conditionExplanation"] = cexp
                exps.append(e)
                pst = "DENIED" if st == "DENIED" else (pst if pst == "DENIED" else ("UNKNOWN_CONDITIONAL" if st == "UNKNOWN_CONDITIONAL" else pst))
            eps.append({"denyAccessState": "DENY_ACCESS_STATE_" + pst, "policy": {"name": pol.get("name") or pol.get("displayName") or "", "rules": pol.get("rules") or []},
                        "denyRuleExplanations": exps, "relevance": "HEURISTIC_RELEVANCE_HIGH" if pst != "NOT_DENIED" else "HEURISTIC_RELEVANCE_NORMAL"})
            rstate = "DENIED" if "DENIED" in (rstate, pst) else ("UNKNOWN_CONDITIONAL" if "UNKNOWN_CONDITIONAL" in (rstate, pst) else rstate)
        resources.append({"denyAccessState": "DENY_ACCESS_STATE_" + rstate, "fullResourceName": full_name(ap), "explainedPolicies": eps,
                          "relevance": "HEURISTIC_RELEVANCE_HIGH" if rstate != "NOT_DENIED" else "HEURISTIC_RELEVANCE_NORMAL"})
        overall = "DENIED" if "DENIED" in (overall, rstate) else ("UNKNOWN_CONDITIONAL" if "UNKNOWN_CONDITIONAL" in (overall, rstate) else overall)
    return {"denyAccessState": "DENY_ACCESS_STATE_" + overall, "explainedResources": resources,
            "relevance": "HEURISTIC_RELEVANCE_HIGH" if overall != "NOT_DENIED" else "HEURISTIC_RELEVANCE_NORMAL"}, overall


def _pab_explanation(principal, res, ids, chain, state):
    pabs = G._pab_applicable(state, ids, principal)
    if not pabs:
        return {"accessState": "PAB_ACCESS_STATE_NOT_ENFORCED", "explainedPolicies": [], "relevance": "HEURISTIC_RELEVANCE_NORMAL"}, "NOT_ENFORCED"
    allowed_res = [r for _b, _n, pol in pabs for r in G._pab_resources(pol)]
    inside = any(a in chain for a in allowed_res)
    st = "ALLOWED" if inside else "NOT_ALLOWED"
    exps = [{"accessState": "PAB_ACCESS_STATE_" + st, "policy": {"name": str(n), "rules": pol.get("rules") or (pol.get("details") or {}).get("rules") or []},
             "relevance": "HEURISTIC_RELEVANCE_HIGH"} for _b, n, pol in pabs]
    return {"accessState": "PAB_ACCESS_STATE_" + st, "explainedPolicies": exps,
            "relevance": "HEURISTIC_RELEVANCE_HIGH" if not inside else "HEURISTIC_RELEVANCE_NORMAL"}, st


def troubleshoot_v3(tuple_, state):
    state = state or {}
    principal, perm, res, ids, chain, ctx = _prep(tuple_, state)
    pols, acc = _allow_explanations(principal, perm, res, ids, chain, ctx, state, True)
    deny, dst = _deny_explanation(principal, perm, res, ids, chain, ctx, state)
    pab, pst = _pab_explanation(principal, res, ids, chain, state)
    if pst == "NOT_ALLOWED" or dst == "DENIED":
        overall = "CANNOT_ACCESS"
    elif acc == "GRANTED":
        overall = "UNKNOWN_CONDITIONAL" if dst == "UNKNOWN_CONDITIONAL" else "CAN_ACCESS"
    elif acc == "UNKNOWN_CONDITIONAL":
        overall = "UNKNOWN_CONDITIONAL"
    else:
        overall = "CANNOT_ACCESS"
    return {"accessTuple": dict(tuple_, principal=principal["member"]), "overallAccessState": overall,
            "allowPolicyExplanation": {"allowAccessState": "ALLOW_ACCESS_STATE_" + acc, "explainedPolicies": pols,
                                       "relevance": "HEURISTIC_RELEVANCE_HIGH" if acc != "NOT_GRANTED" else "HEURISTIC_RELEVANCE_NORMAL"},
            "denyPolicyExplanation": deny, "pabPolicyExplanation": pab}


# ------------------------------------------------------------------ analyzeIamPolicy
def _first(v):
    return (v[0] if isinstance(v, list) and v else v) if v not in (None, "") else None


def _many(params, key):
    v = params.get(key)
    if v is None:
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v]) if x != ""]


def _flag(params, key):
    return str(_first(params.get(key)) or "").lower() == "true"


def analyze_iam_policy(scope, params, state):
    """`scope` = 'projects/p' | 'folders/N' | 'organizations/N' (the path of `/v1/{scope}:analyzeIamPolicy`).
    `params` = flat query params (analysisQuery.identitySelector.identity ...; repeated keys may be lists). Allow policies only (the real
    API does not evaluate deny policies or principal access boundaries)."""
    state = state or {}
    q = "analysisQuery."
    identity = _first(params.get(q + "identitySelector.identity"))
    resource = _first(params.get(q + "resourceSelector.fullResourceName"))
    roles, perms = _many(params, q + "accessSelector.roles"), _many(params, q + "accessSelector.permissions")
    if not (identity or resource or roles or perms):
        raise GcpError(400, "INVALID_ARGUMENT", "analysisQuery must set at least one of identitySelector, resourceSelector or accessSelector.")
    if not re.match(r"^(projects|folders|organizations)/[^/]+$", scope):
        raise GcpError(400, "INVALID_ARGUMENT", f"Invalid scope {scope!r}: expected projects/{{id}}, folders/{{id}} or organizations/{{id}}.")
    qscope = _first(params.get(q + "scope"))
    if qscope and qscope != scope:
        raise GcpError(400, "INVALID_ARGUMENT", "analysisQuery.scope does not match the request scope.")
    expand_groups, expand_roles = _flag(params, q + "options.expandGroups"), _flag(params, q + "options.expandRoles")
    at = _first(params.get(q + "conditionContext.accessTime"))
    ctx = {"time": at} if at else {}
    if at:
        try:
            when = G._parse_ts(at)
            if when < _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=1):
                raise GcpError(400, "INVALID_ARGUMENT", "conditionContext.accessTime must not be earlier than the current time.")
        except GcpError:
            raise
        except Exception:
            raise GcpError(400, "INVALID_ARGUMENT", "conditionContext.accessTime is not a valid timestamp.")
    ids = None
    principal = None
    if identity:
        m = _member(identity)
        principal = {"member": m, "type": m.split(":", 1)[0]}
        ids = G.principal_identities(principal, state)
        if not expand_groups:
            ids = {m}
    chain = G.ancestry(resource, state) if resource else None
    if resource and not resource.startswith("//"):
        raise GcpError(400, "INVALID_ARGUMENT", "resourceSelector.fullResourceName must be a //service.googleapis.com/... name.")
    results = []
    for key, pol in sorted((state.get("allow_policies") or {}).items()):
        point = G._norm_key(key)
        # the policy must live under the scope (or at it) ...
        if scope not in G.ancestry(point, state):
            continue
        # ... and, for a resource query, apply to that resource (attached on it or an ancestor)
        if chain is not None and point not in chain:
            continue
        for b in (pol or {}).get("bindings") or []:
            role = b.get("role", "")
            rp = G.role_permissions(role, state)
            if roles and role not in roles:
                continue
            if perms and not all(p in rp for p in perms):
                continue
            members = [m for m in b.get("members") or []]
            if ids is not None:
                members = [m for m in members if G._member_matches(m, ids, principal, state)]
                if not members:
                    continue
            cond = b.get("condition")
            cond_eval = None
            if cond and cond.get("expression"):
                rn = resource or full_name(point)
                if not at and "request.time" in cond["expression"]:
                    cond_eval = "CONDITIONAL"
                else:
                    ok, _n = _eval_cond(cond["expression"], ctx, rn)
                    cond_eval = "TRUE" if ok is True else ("FALSE" if ok is False else "CONDITIONAL")
            if perms:
                accesses = [{"permission": p, "analysisState": {"code": "OK"}} for p in perms]
            elif expand_roles:
                accesses = [{"permission": p, "analysisState": {"code": "OK"}} for p in sorted(rp)]
            else:
                accesses = [{"role": role, "analysisState": {"code": "OK"}}]
            acl = {"resources": [{"fullResourceName": resource or full_name(point), "analysisState": {"code": "OK"}}], "accesses": accesses,
                   "resourceEdges": []}
            if cond_eval:
                acl["conditionEvaluation"] = {"evaluationValue": cond_eval}
            binding = {"role": role, "members": b.get("members") or []}
            if cond:
                binding["condition"] = cond
            results.append({"attachedResourceFullName": full_name(point), "iamBinding": binding, "accessControlLists": [acl],
                            "identityList": {"identities": [{"name": m, "analysisState": {"code": "OK"}} for m in members], "groupEdges": []},
                            "fullyExplored": True})
    out = {"mainAnalysis": {"analysisQuery": {"scope": scope, **_echo(params)}, "analysisResults": results, "fullyExplored": True, "nonCriticalErrors": []},
           "serviceAccountImpersonationAnalysis": [], "fullyExplored": True}
    if _flag(params, q + "options.includeDenyPolicies"):
        out["vyomiDenyAnalysis"] = _deny_analysis(scope, chain, ids, principal, perms, ctx, resource, state)
        for r in results:       # annotate each allowed permission that a matching deny rule covers
            for acl in r["accessControlLists"]:
                for ac in acl["accesses"]:
                    perm = ac.get("permission")
                    if perm:
                        hits = [d for d in out["vyomiDenyAnalysis"]["denyRules"] if any(G._perm_pattern_match(x, perm) for x in d["deniedPermissions"])
                                and not any(G._perm_pattern_match(x, perm) for x in d["exceptionPermissions"])]
                        if hits:
                            ac["vyomiDeniedBy"] = [{"policy": h["policy"], "ruleIndex": h["ruleIndex"], "state": h["state"]} for h in hits]
    return out


def _deny_analysis(scope, chain, ids, principal, perms, ctx, resource, state):
    """VYOMI EXTENSION (the real analyzeIamPolicy does not evaluate deny policies): the IAM v2 deny rules that apply under `scope` / to the
    resource, narrowed to the queried identity and permissions, each with its condition state."""
    rules = []
    for ap, pol, i, dr in G._deny_rules(state, chain or G.ancestry(scope, state)):
        if chain is None and scope not in G.ancestry(ap, state):
            continue
        dp, ex = list(dr.get("deniedPermissions") or []), list(dr.get("exceptionPermissions") or [])
        if perms and not any(G._perm_pattern_match(x, p) for x in dp for p in perms):
            continue
        if ids is not None and not G._principal_listed(dr.get("deniedPrincipals"), ids, principal, state):
            continue
        cond = dr.get("denialCondition")
        st = "UNCONDITIONAL"
        if cond and cond.get("expression"):
            ok, _n = _eval_cond(cond["expression"], ctx, resource or full_name(ap))
            st = "DENIES" if ok is True else ("DOES_NOT_APPLY" if ok is False else "CONDITIONAL")
        rules.append({"attachedResourceFullName": full_name(ap), "policy": pol.get("name") or pol.get("displayName") or "", "ruleIndex": i,
                      "deniedPrincipals": list(dr.get("deniedPrincipals") or []), "exceptionPrincipals": list(dr.get("exceptionPrincipals") or []),
                      "deniedPermissions": dp, "exceptionPermissions": ex, "denialCondition": cond, "state": st})
    return {"note": "Vyomi extension: Cloud Asset analyzeIamPolicy does not evaluate deny policies.", "denyRules": rules}


def _echo(params):
    out = {}
    if _first(params.get("analysisQuery.identitySelector.identity")):
        out["identitySelector"] = {"identity": _first(params["analysisQuery.identitySelector.identity"])}
    if _first(params.get("analysisQuery.resourceSelector.fullResourceName")):
        out["resourceSelector"] = {"fullResourceName": _first(params["analysisQuery.resourceSelector.fullResourceName"])}
    acc = {}
    if _many(params, "analysisQuery.accessSelector.roles"):
        acc["roles"] = _many(params, "analysisQuery.accessSelector.roles")
    if _many(params, "analysisQuery.accessSelector.permissions"):
        acc["permissions"] = _many(params, "analysisQuery.accessSelector.permissions")
    if acc:
        out["accessSelector"] = acc
    return out
