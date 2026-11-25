"""Governance read models for the three consoles: hierarchy trees, effective policies, "what would this guardrail do" checks.

Pure stdlib (Pyodide-safe, vendored for Nano).  The WRITES are the clouds' own native APIs (AWS Organizations, Resource Manager / Org Policy v2 /
IAM v2 deny + PAB, ARM Microsoft.Management); this module only READS the same stores and evaluates with the same engines the gate uses, so what
the console shows is what the gate enforces.

Routes (served by core/iam_engine/api.IamApi, same on Mesh and Nano):  GET|POST /api/iam/<cloud>/governance/<what>
  aws    organization | effective?account= | check (POST) | s3-public-access
  gcp    hierarchy | orgpolicy?node= | orgpolicy/check (POST) | iam-policies?node=
  azure  hierarchy | effective?scope=

`handle(cloud, what, method, query, body, ctx)`; `ctx` = {store objects} supplied by the host (`host_ctx`).
"""
from __future__ import annotations

import json


def _dict(v):
    try:
        return v if hasattr(v, "get") and hasattr(v, "items") else {}
    except Exception:
        return {}


# ============================================================================== AWS
def _org(iam):
    o = _dict(getattr(iam, "extras", None)).get("org")
    return o if o else None


def _pol_brief(iam, pid):
    p = _dict(_dict(getattr(iam, "org_policies", None)).get(pid))
    return {"id": pid, "name": p.get("name") or pid, "type": p.get("type"), "awsManaged": bool(p.get("aws_managed")), "description": p.get("description", "")}


def aws_organization(iam):
    """The org tree with, per node, the policies attached (SCP / RCP / other)."""
    o = _org(iam)
    if not o:
        return {"organization": None}
    att = _dict(o.get("attachments"))
    nodes = []
    for rid, r in _dict(o.get("roots")).items():
        nodes.append({"id": rid, "type": "ROOT", "name": r.get("name", "Root"), "parent": None, "arn": r.get("arn"),
                      "policyTypes": list(r.get("policy_types") or []), "policies": [_pol_brief(iam, p) for p in att.get(rid, [])]})
    for uid, u in _dict(o.get("ous")).items():
        nodes.append({"id": uid, "type": "ORGANIZATIONAL_UNIT", "name": u.get("name"), "parent": u.get("parent"), "arn": u.get("arn"),
                      "policies": [_pol_brief(iam, p) for p in att.get(uid, [])]})
    for aid, a in _dict(o.get("accounts")).items():
        nodes.append({"id": aid, "type": "ACCOUNT", "name": a.get("name"), "parent": a.get("parent"), "arn": a.get("arn"), "email": a.get("email"),
                      "status": a.get("status"), "management": aid == o.get("master_account_id"),
                      "policies": [_pol_brief(iam, p) for p in att.get(aid, [])]})
    return {"organization": {"id": o["id"], "arn": o.get("arn"), "featureSet": o.get("feature_set"), "managementAccountId": o.get("master_account_id"),
                             "scpAppliesToManagement": bool(o.get("scp_apply_to_management"))},
            "nodes": nodes}


def aws_effective(iam, account):
    """Effective SCPs / RCPs for an account: one level per org node on the path root -> OUs -> account (the engine's levels: every level must
    allow, any Deny anywhere wins).  Management account: none (as AWS) unless the lab sets scp_apply_to_management."""
    o = _org(iam)
    if not o:
        return {"organization": None}
    accounts = _dict(o.get("accounts"))
    if account not in accounts:
        raise ValueError("account %s is not in the organization" % account)
    ous, att = _dict(o.get("ous")), _dict(o.get("attachments"))
    path, cur, seen = [account], accounts[account].get("parent"), set()
    while cur and cur not in seen:
        seen.add(cur)
        path.append(cur)
        cur = _dict(ous.get(cur)).get("parent")
    path.reverse()
    names = {}
    for rid, r in _dict(o.get("roots")).items():
        names[rid] = r.get("name", "Root")
    for uid, u in ous.items():
        names[uid] = u.get("name")
    names[account] = accounts[account].get("name")
    exempt = account == o.get("master_account_id") and not o.get("scp_apply_to_management")
    out = {"account": account, "name": accounts[account].get("name"), "management": account == o.get("master_account_id"), "exemptFromScps": exempt,
           "path": [{"id": n, "name": names.get(n)} for n in path], "scp": [], "rcp": []}
    pols = _dict(getattr(iam, "org_policies", None))
    deny = []
    for key, kind in (("scp", "SERVICE_CONTROL_POLICY"), ("rcp", "RESOURCE_CONTROL_POLICY")):
        for n in path:
            ps = []
            for pid in att.get(n, []):
                p = _dict(pols.get(pid))
                if p.get("type") != kind:
                    continue
                try:
                    doc = json.loads(p.get("content") or "{}")
                except Exception:
                    doc = {}
                ps.append({"id": pid, "name": p.get("name"), "awsManaged": bool(p.get("aws_managed")), "document": doc})
                for st in (doc.get("Statement") if isinstance(doc.get("Statement"), list) else [doc.get("Statement")] if doc.get("Statement") else []):
                    if isinstance(st, dict) and st.get("Effect") == "Deny":
                        deny.append({"kind": key.upper(), "node": n, "nodeName": names.get(n), "policy": p.get("name"), "sid": st.get("Sid"),
                                     "actions": st.get("Action") or st.get("NotAction"), "resources": st.get("Resource"), "hasCondition": bool(st.get("Condition"))})
            out[key].append({"node": n, "nodeName": names.get(n), "policies": ps})
    out["denyStatements"] = deny
    return out


def aws_check(iam, account, action, resource="*", context=None):
    """Would the guardrails (SCP + RCP chain of `account`) let an otherwise-unrestricted principal of that account do `action`?  Uses the
    SAME engine + level builder as the live gate (iam_resource_policies.org_levels)."""
    from core import iam_resource_policies as rp
    from core.iam_engine import aws_eval
    o = _org(iam)
    if not o or account not in _dict(o.get("accounts")):
        raise ValueError("account %s is not in the organization" % account)
    lv = rp.org_levels(iam, account) if account != o.get("master_account_id") or o.get("scp_apply_to_management") else {"scps": [], "rcps": []}
    principal = {"arn": "arn:aws:iam::%s:user/governance-check" % account, "type": "user", "account": account,
                 "policies": [{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}]}
    d = aws_eval.evaluate({"action": action, "resource": resource or "*", "principal": principal, "context": dict(context or {})},
                          {"account": account, "scps": lv["scps"], "rcps": lv["rcps"]})
    blame = [m for m in d.get("matched", []) if m.get("source") in ("scp", "rcp")]
    return {"account": account, "action": action, "resource": resource, "allowed": d["allowed"], "reason": d["reason"],
            "failedLayer": d.get("failedLayer"), "matched": blame, "levels": {"scp": len(lv["scps"]), "rcp": len(lv["rcps"])}}


def aws_s3_public_access(s3):
    """Account + per-bucket Block Public Access with what each bucket exposes (public policy / public ACL) and what the block does about it."""
    from core import iam_resource_policies as rp
    from core.iam_engine import aws_eval
    acct = {k: bool(_dict(_dict(getattr(s3, "account", None)).get("pab")).get(k)) for k in rp._BPA_KEYS}
    rows = []
    for b, meta in _dict(getattr(s3, "buckets", None)).items():
        meta = _dict(meta)
        own = rp._bpa_flags(_dict(meta.get("cfg")).get("publicAccessBlock"))
        eff = rp.s3_bpa(s3, b)
        doc = rp._doc(_dict(meta.get("cfg")).get("policy"))
        public_policy = bool(doc) and any(aws_eval._stmt_public(st) for st in aws_eval._as_list(doc.get("Statement")))
        acl = rp._acl_policies(s3, b, meta)
        public_acl = bool(acl)
        rows.append({"bucket": b, "own": own, "effective": eff, "publicPolicy": public_policy, "publicAcl": public_acl,
                     "publiclyAccessible": (public_policy and not eff["RestrictPublicBuckets"]) or (public_acl and not eff["IgnorePublicAcls"]),
                     "blockedBy": [k for k in ("RestrictPublicBuckets",) if public_policy and eff[k]] + [k for k in ("IgnorePublicAcls",) if public_acl and eff[k]]})
    return {"account": acct, "buckets": sorted(rows, key=lambda r: r["bucket"])}


# ============================================================================== GCP
def gcp_hierarchy(rm, policy_counts=None, project=None):
    """organization -> folders -> projects, with counts of org policies attached to each node."""
    from core import gcp_resourcemanager_core as G
    org = G.get_or_create_default_org(rm)
    if project and project not in _dict(getattr(rm, "projects", None)):
        G._get_or_create_project(rm, project)   # the console project exists from first use, as in GCP
    pols = _dict(getattr(rm, "org_policies", None))

    def n_pol(node):
        p = node + "/policies/"
        return sum(1 for k in pols if k.startswith(p))
    folders = {k: f for k, f in _dict(getattr(rm, "folders", None)).items() if f.get("state", "ACTIVE") == "ACTIVE"}
    out = {"id": org["name"], "type": "organization", "name": org.get("displayName"), "orgPolicies": n_pol(org["name"]), "children": []}

    def kids(parent):
        res = []
        for fn, f in sorted(folders.items()):
            if G._parent_str(f.get("parent")) == parent:
                res.append({"id": fn, "type": "folder", "name": f.get("displayName"), "orgPolicies": n_pol(fn), "children": kids(fn)})
        for pid, p in sorted(_dict(getattr(rm, "projects", None)).items()):
            if G._parent_str(p.get("parent")) == parent and p.get("state", "ACTIVE") == "ACTIVE":
                res.append({"id": "projects/" + pid, "type": "project", "name": p.get("displayName") or pid, "number": str(p.get("name", "")).rsplit("/", 1)[-1],
                            "orgPolicies": n_pol("projects/" + pid), "children": []})
        return res
    out["children"] = kids(org["name"])
    return out


def gcp_orgpolicy_view(rm, node):
    """The inheritance view for `node`: every constraint that has a policy on the node or any ancestor, each with the per-level policy and the effective result."""
    from core import gcp_orgpolicy_core as op
    chain = op.chain(rm, node)
    pols = _dict(getattr(rm, "org_policies", None))
    seen = []
    for n in chain:
        for k in pols:
            if k.startswith(n + "/policies/"):
                c = op.cid(k.split("/policies/", 1)[1])
                if c not in seen and op.get_constraint(c):
                    seen.append(c)
    rows = []
    for c in sorted(seen):
        e, d = op.effective(rm, node, c), op.effective(rm, node, c, dry_run=True)
        levels = []
        for n in reversed(chain):             # root first
            p = op._policy(rm, n, c)
            levels.append({"node": n, "spec": (p or {}).get("spec"), "dryRunSpec": (p or {}).get("dryRunSpec")})
        rows.append({"constraint": "constraints/" + c, "displayName": op.get_constraint(c)["displayName"], "kind": e["kind"], "effective": e,
                     "dryRunEffective": d if any(l["dryRunSpec"] for l in levels) else None, "levels": levels,
                     "enforcedByVyomi": op.get_constraint(c)["vyomi"]["enforcedBy"]})
    return {"node": node, "chain": chain, "constraints": rows}


def gcp_iam_policies(rm, gcp_iam, node):
    """IAM-side governance at a node and its ancestors: allow bindings count, deny policies, PAB bindings targeting the node's principal sets."""
    from core import gcp_orgpolicy_core as op
    chain = op.chain(rm, node)
    allow = _dict(getattr(gcp_iam, "gcp_iam_policies", None))
    deny = _dict(getattr(gcp_iam, "gcp_deny_policies", None))
    out = {"node": node, "levels": []}
    for n in chain:
        key = n.replace("/", "%2F")
        dp = deny.get(n) or deny.get(key) or {}
        dl = [v for v in (dp.values() if isinstance(dp, dict) else dp or []) if isinstance(v, dict)]
        out["levels"].append({"node": n, "allowBindings": len(_dict(allow.get(n)).get("bindings") or []), "denyPolicies": [d.get("displayName") or d.get("name") for d in dl]})
    org = chain[-1]
    out["pabPolicies"] = sorted(_dict(getattr(rm, "pab_policies", None)))
    out["pabBindings"] = [b.get("name") for b in _dict(getattr(rm, "pab_bindings", None)).values() if isinstance(b, dict)]
    out["organization"] = org
    return out


# ============================================================================== Azure
def azure_hierarchy(arm_state):
    from core import azure_mgmt_groups_core as mg
    t = mg.tree(arm_state)
    pa = {}
    ra = {}
    for r in arm_state.values():
        if isinstance(r, dict) and r.get("_mg") and str(r.get("_type", "")).lower() == "microsoft.authorization/policyassignments":
            pa[str(r["_mg"]).lower()] = pa.get(str(r["_mg"]).lower(), 0) + 1

    def decorate(n):
        n["policyAssignments"] = pa.get(str(n["name"]).lower(), 0) if n["kind"] == "managementGroup" else None
        for c in n["children"]:
            decorate(c)
    decorate(t)
    return {"root": t, "maxDepth": mg.MAX_DEPTH}


def azure_effective(arm_state, state, scope):
    """Role assignments, deny assignments and policy assignments that apply at `scope`, each with the scope it is inherited from."""
    from core import azure_mgmt_groups_core as mg
    from core.iam_engine import azure_eval
    anc = azure_eval._ancestors(azure_eval._norm(scope), state)
    low = {a: i for i, a in enumerate(anc)}
    roles = []
    for a in state.get("role_assignments", []):
        sc = azure_eval._norm(a.get("scope") or "/")
        if sc in low:
            roles.append({"id": a.get("id"), "principalId": a.get("principal_id"), "roleDefinitionId": a.get("role_definition_id"),
                          "scope": a.get("scope"), "inheritedFrom": None if sc == azure_eval._norm(scope) else a.get("scope"), "distance": low[sc]})
    denies = []
    for d in state.get("deny_assignments", []):
        sc = azure_eval._norm(d.get("scope") or "/")
        if sc in low and (sc == azure_eval._norm(scope) or not d.get("do_not_apply_to_child_scopes")):
            denies.append({"id": d.get("id"), "scope": d.get("scope"), "principals": d.get("principals")})
    policies = []
    sub = None
    s = str(scope)
    if s.lower().startswith("/subscriptions/"):
        sub = s.split("/")[2]
        for r in mg.policy_assignments_above(arm_state, sub):
            policies.append({"name": r["name"], "scope": r["properties"].get("scope"), "definition": r["properties"].get("policyDefinitionId"),
                             "enforcementMode": r["properties"].get("enforcementMode")})
        for r in arm_state.values():
            if isinstance(r, dict) and str(r.get("_type", "")).lower() == "microsoft.authorization/policyassignments" and r.get("_sub") and r.get("_sub").lower() == sub.lower():
                policies.append({"name": r["name"], "scope": "/subscriptions/" + sub, "definition": (r.get("properties") or {}).get("policyDefinitionId"),
                                 "enforcementMode": (r.get("properties") or {}).get("enforcementMode", "Default")})
    elif mg.scope_mg(s):
        for n in mg.chain(arm_state, mg.scope_mg(s)):
            pfx = mg._key(n) + "/providers/microsoft.authorization/policyassignments/"
            for k, r in sorted(arm_state.items()):
                if k.startswith(pfx):
                    policies.append({"name": r["name"], "scope": mg.mg_id(n), "definition": r["properties"].get("policyDefinitionId"),
                                     "enforcementMode": r["properties"].get("enforcementMode")})
    return {"scope": scope, "ancestors": anc, "roleAssignments": sorted(roles, key=lambda r: r["distance"]), "denyAssignments": denies, "policyAssignments": policies}


# ============================================================================== dispatcher + host binding
def host_ctx(cloud):
    """The live stores for `cloud` (Mesh appliance stores, else the Nano registry). Missing pieces are simply absent."""
    out = {}
    try:
        from core import appliance_stores as A
        if cloud == "aws":
            out["iam"], out["s3"] = A.iam_store(), A.s3_store()
        elif cloud == "gcp":
            ns = A.net_new_core_stores()
            out["rm"], out["gcp_iam"] = ns.get("gcp_rm"), ns.get("gcp_iam")
        else:
            try:
                from providers import azure_services
                out["arm_state"] = azure_services._state
            except Exception:
                from core.app_context import azure_state_dict
                out["arm_state"] = azure_state_dict()
            out["rbac"] = A.net_new_core_stores().get("iam")
        return out
    except ImportError:
        pass
    try:
        from core import nano_registry
        reg = nano_registry.get()
        if cloud == "aws":
            out["iam"], out["s3"] = reg.get("iam"), reg.get("s3")
        elif cloud == "gcp":
            out["rm"], out["gcp_iam"] = reg.get("gcp_rm"), reg.get("gcp_iam")
        else:
            arm = reg.get("az_arm")
            out["arm_state"] = getattr(arm, "state", None)
            out["rbac"] = reg.get("iam")
    except Exception:
        pass
    return out


def handle(cloud, what, method, query=None, body=None, ctx=None, azure_state_fn=None):
    """-> (status, json-able).  `what` = path after /governance/ (e.g. 'effective', 'orgpolicy/check')."""
    q = {str(k): (v[0] if isinstance(v, list) and v else v) for k, v in (query or {}).items()}
    body = body if isinstance(body, dict) else {}
    ctx = ctx if ctx is not None else host_ctx(cloud)
    method = str(method).upper()
    try:
        if cloud == "aws":
            iam, s3 = ctx.get("iam"), ctx.get("s3")
            if what == "organization" and method == "GET" and iam is not None:
                return 200, aws_organization(iam)
            if what == "effective" and method == "GET" and iam is not None:
                return 200, aws_effective(iam, q.get("account") or getattr(iam, "account_id", ""))
            if what == "check" and method == "POST" and iam is not None:
                if not body.get("action"):
                    return 400, {"error": "body: {account?, action, resource?, context?}"}
                return 200, aws_check(iam, body.get("account") or getattr(iam, "account_id", ""), body["action"], body.get("resource") or "*", body.get("context"))
            if what == "settings" and method == "POST" and iam is not None:
                o = _org(iam)
                if not o:
                    return 400, {"error": "no organization"}
                o["scp_apply_to_management"] = bool(body.get("scpAppliesToManagement"))
                p = getattr(iam, "persist", None)
                if callable(p):
                    p()
                return 200, {"scpAppliesToManagement": o["scp_apply_to_management"]}
            if what == "s3-public-access" and method == "GET" and s3 is not None:
                return 200, aws_s3_public_access(s3)
        elif cloud == "gcp":
            rm = ctx.get("rm")
            if rm is None:
                return 501, {"error": "Resource Manager store not available"}
            if what == "hierarchy" and method == "GET":
                return 200, gcp_hierarchy(rm, project=q.get("project"))
            if what == "orgpolicy" and method == "GET":
                return 200, gcp_orgpolicy_view(rm, q.get("node") or "projects/" + (next(iter(getattr(rm, "projects", {}) or {}), "") or ""))
            if what == "orgpolicy/check" and method == "POST":
                from core import gcp_orgpolicy_core as op
                if not body.get("node") or not body.get("constraint"):
                    return 400, {"error": "body: {node, constraint, value?}"}
                return 200, op.check(rm, body["node"], body["constraint"], body.get("value"))
            if what == "iam-policies" and method == "GET":
                return 200, gcp_iam_policies(rm, ctx.get("gcp_iam"), q.get("node") or "projects/" + (next(iter(getattr(rm, "projects", {}) or {}), "") or ""))
        elif cloud == "azure":
            arm = ctx.get("arm_state")
            if arm is None:
                return 501, {"error": "ARM state not available"}
            if what == "hierarchy" and method == "GET":
                return 200, azure_hierarchy(arm)
            if what == "effective" and method == "GET":
                if not q.get("scope"):
                    return 400, {"error": "query: scope"}
                from core import iam_state_adapters as ad
                st = ad.azure_state(arm, ctx.get("rbac"))
                return 200, azure_effective(arm, st, q["scope"])
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 404, {"error": "unknown governance route '%s' for %s" % (what, cloud)}
