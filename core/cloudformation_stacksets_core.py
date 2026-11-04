"""CloudFormation StackSets with AWS Organizations (service-managed permissions) — substrate-independent, Query-protocol XML.

Adds to core/cloudformation_core: ActivateOrganizationsAccess / DeactivateOrganizationsAccess / DescribeOrganizationsAccess (trusted access,
backed by REAL Organizations service access `member.org.stacksets.cloudformation.amazonaws.com` in the shared Organizations model),
CreateStackSet PermissionModel=SERVICE_MANAGED (needs trusted access + AutoDeployment, like AWS), CreateStackInstances / DeleteStackInstances /
ListStackInstances / DescribeStackInstance with DeploymentTargets (OU ids resolved recursively to ACTIVE member accounts, or Accounts), and
ListStackSetOperations / DescribeStackSetOperation (each create/delete is a recorded operation).

Honest limit: Vyomi is one account, so a member account has no resources of its own — a stack instance is recorded (CURRENT) with the stack id
a real deployment would have, but no stack is created in the target account/Region. Drift detection, update/override operations and
AutoDeployment-triggered instances on account moves are not modeled. State lives on the CloudFormation store (stack_set_instances, stack_set_ops).
"""
from __future__ import annotations

import re
import time
import uuid

SS_PRINCIPAL = "member.org.stacksets.cloudformation.amazonaws.com"
_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
_ACCT = re.compile(r"^\d{12}$")


def _c():
    try:
        from core import cloudformation_core as m
    except ImportError:  # Pyodide flat layout
        import cloudformation_core as m  # type: ignore
    return m


def _org(stores):
    iam = (stores or {}).get("iam")
    return (getattr(iam, "extras", None) or {}).get("org") if iam is not None else None


def _status(stores) -> str:
    o = _org(stores)
    return "ENABLED" if o and SS_PRINCIPAL in o.get("service_access", {}) else "DISABLED"


def _need_mgmt_org(store, stores):
    c = _c()
    o = _org(stores)
    if not o:
        raise c.CfnError("InvalidOperationException", "Your account is not a member of an organization; create one in AWS Organizations first.", 400)
    if o.get("master_account_id") != store.account_id:
        raise c.CfnError("InvalidOperationException", "Only the organization's management account can change trusted access.", 400)
    if o.get("feature_set") != "ALL":
        raise c.CfnError("InvalidOperationException", "The organization must have all features enabled to use service-managed StackSets.", 400)
    return o


def _activate(store, params, stores):
    c = _c()
    o = _need_mgmt_org(store, stores)
    o["service_access"].setdefault(SS_PRINCIPAL, time.time())
    getattr(stores.get("iam"), "persist", lambda: None)()
    return c._envelope("ActivateOrganizationsAccess")


def _deactivate(store, params, stores):
    c = _c()
    o = _need_mgmt_org(store, stores)
    if any(s.get("PermissionModel") == "SERVICE_MANAGED" for s in store.stack_sets.values()):
        raise c.CfnError("InvalidOperationException", "Delete all SERVICE_MANAGED stack sets before deactivating trusted access.", 400)
    o["service_access"].pop(SS_PRINCIPAL, None)
    getattr(stores.get("iam"), "persist", lambda: None)()
    return c._envelope("DeactivateOrganizationsAccess")


def _describe_access(store, params, stores):
    c = _c()
    return c._envelope("DescribeOrganizationsAccess", c._el("Status", _status(stores)))


def _create_stack_set(orig):
    def fn(store, params, stores):
        c = _c()
        model = c._p(params, "PermissionModel", "SELF_MANAGED")
        if model not in ("SELF_MANAGED", "SERVICE_MANAGED"):
            raise c.CfnError("ValidationError", f"Value '{model}' at 'permissionModel' failed to satisfy constraint: Member must satisfy enum value set: [SERVICE_MANAGED, SELF_MANAGED]", 400)
        auto = c._p(params, "AutoDeployment.Enabled")
        if model == "SERVICE_MANAGED":
            if _status(stores) != "ENABLED":
                raise c.CfnError("ValidationError", "Trusted access with AWS Organizations is not activated; call ActivateOrganizationsAccess first.", 400)
            if not auto:
                raise c.CfnError("ValidationError", "AutoDeployment is required when PermissionModel is SERVICE_MANAGED.", 400)
            if c._p(params, "AdministrationRoleARN") or c._p(params, "ExecutionRoleName"):
                raise c.CfnError("ValidationError", "AdministrationRoleARN and ExecutionRoleName are not valid with SERVICE_MANAGED.", 400)
        elif auto:
            raise c.CfnError("ValidationError", "AutoDeployment is only valid with PermissionModel SERVICE_MANAGED.", 400)
        r = orig(store, params, stores)
        name = c._p(params, "StackSetName")
        ss = store.stack_sets.get(name)
        if ss is not None:
            ss["AutoDeployment"] = ({"Enabled": c._bool(auto), "RetainStacksOnAccountRemoval": c._bool(c._p(params, "AutoDeployment.RetainStacksOnAccountRemoval"))}
                                    if model == "SERVICE_MANAGED" else None)
            store.persist()
        return r
    return fn


def _ous_accounts(o, ou_ids):
    """ACTIVE member accounts under the OUs/roots, recursively."""
    out, stack = {}, list(ou_ids)
    while stack:
        pid = stack.pop()
        for u in o["ous"].values():
            if u["parent"] == pid:
                stack.append(u["id"])
        for a in o["accounts"].values():
            if a["parent"] == pid and a.get("state", "ACTIVE") == "ACTIVE":
                out[a["id"]] = pid
    return out


def _set(store, params):
    c = _c()
    name = c._p(params, "StackSetName")
    ss = store.stack_sets.get(name)
    if not ss:
        raise c.CfnError("StackSetNotFoundException", f"StackSet {name} not found", 400)
    return ss


def _ops(store) -> dict:
    return store.__dict__.setdefault("stack_set_ops", {})


def _record_op(store, ss, action, accounts, regions):
    op_id = str(uuid.uuid4())
    now = _c()._now_iso()
    _ops(store)[op_id] = {"OperationId": op_id, "StackSetId": ss["StackSetId"], "StackSetName": ss["StackSetName"], "Action": action,
                          "Status": "SUCCEEDED", "CreationTimestamp": now, "EndTimestamp": now, "Accounts": sorted(accounts), "Regions": list(regions)}
    return op_id


def _targets(store, ss, params, stores):
    c = _c()
    regions = c._members(params, "Regions")
    if not regions:
        raise c.CfnError("ValidationError", "Regions is required.", 400)
    for r in regions:
        if not _REGION.match(r):
            raise c.CfnError("ValidationError", f"Region {r} is not a valid Region.", 400)
    accts = c._members(params, "Accounts")
    dt_accts = c._members(params, "DeploymentTargets.Accounts")
    ous = c._members(params, "DeploymentTargets.OrganizationalUnitIds")
    model = ss.get("PermissionModel", "SELF_MANAGED")
    resolved: dict[str, str | None] = {}
    if model == "SELF_MANAGED":
        if ous or c._p(params, "DeploymentTargets.AccountFilterType"):
            raise c.CfnError("ValidationError", "OrganizationalUnitIds are only valid for SERVICE_MANAGED stack sets.", 400)
        accts = accts or dt_accts
        if not accts:
            raise c.CfnError("ValidationError", "Accounts is required for SELF_MANAGED stack sets.", 400)
        for a in accts:
            if not _ACCT.match(a):
                raise c.CfnError("ValidationError", f"Account {a} is not a valid 12-digit account id.", 400)
            resolved[a] = None
    else:
        if accts:
            raise c.CfnError("ValidationError", "Use DeploymentTargets (OrganizationalUnitIds) for SERVICE_MANAGED stack sets.", 400)
        if _status(stores) != "ENABLED":
            raise c.CfnError("ValidationError", "Trusted access with AWS Organizations is not activated.", 400)
        o = _org(stores)
        flt = c._p(params, "DeploymentTargets.AccountFilterType", "NONE")
        if not ous and not dt_accts:
            raise c.CfnError("ValidationError", "DeploymentTargets must contain OrganizationalUnitIds or Accounts.", 400)
        for u in ous:
            if u not in o["ous"] and u not in o["roots"]:
                raise c.CfnError("ValidationError", f"Organizational unit {u} does not exist in the organization.", 400)
        by_ou = _ous_accounts(o, ous)
        for a in dt_accts:
            if a not in o["accounts"]:
                raise c.CfnError("ValidationError", f"Account {a} is not a member of the organization.", 400)
        if flt == "NONE":
            if dt_accts:
                raise c.CfnError("ValidationError", "Specify Accounts only together with AccountFilterType (INTERSECTION, DIFFERENCE or UNION).", 400)
            resolved = dict(by_ou)
        elif flt == "UNION":
            resolved = {**{a: None for a in dt_accts}, **by_ou}
        elif flt == "INTERSECTION":
            resolved = {a: p for a, p in by_ou.items() if a in dt_accts}
        elif flt == "DIFFERENCE":
            resolved = {a: p for a, p in by_ou.items() if a not in dt_accts}
        else:
            raise c.CfnError("ValidationError", f"Invalid AccountFilterType {flt}.", 400)
        if not resolved:
            raise c.CfnError("ValidationError", "The deployment targets resolve to no active accounts.", 400)
    return regions, resolved


def _create_instances(store, params, stores):
    c = _c()
    ss = _set(store, params)
    regions, targets = _targets(store, ss, params, stores)
    insts = store.stack_set_instances.setdefault(ss["StackSetName"], [])
    for acct, ou in targets.items():
        for rg in regions:
            if any(i["Account"] == acct and i["Region"] == rg for i in insts):
                continue
            sid = uuid.uuid4()
            insts.append({"StackSetId": ss["StackSetId"], "Region": rg, "Account": acct, "OrganizationalUnitId": ou, "Status": "CURRENT",
                          "StackId": f"arn:aws:cloudformation:{rg}:{acct}:stack/StackSet-{ss['StackSetName']}-{sid}/{uuid.uuid4()}"})
    op = _record_op(store, ss, "CREATE", targets, regions)
    store.persist()
    return c._envelope("CreateStackInstances", c._el("OperationId", op))


def _delete_instances(store, params, stores):
    c = _c()
    ss = _set(store, params)
    regions, targets = _targets(store, ss, params, stores)
    if c._p(params, "RetainStacks") == "":
        raise c.CfnError("ValidationError", "RetainStacks is required.", 400)
    insts = store.stack_set_instances.get(ss["StackSetName"], [])
    keep = [i for i in insts if not (i["Account"] in targets and i["Region"] in regions)]
    if len(keep) == len(insts):
        raise c.CfnError("StackInstanceNotFoundException", "The specified stack instances do not exist.", 404)
    store.stack_set_instances[ss["StackSetName"]] = keep
    op = _record_op(store, ss, "DELETE", targets, regions)
    store.persist()
    return c._envelope("DeleteStackInstances", c._el("OperationId", op))


def _member_xml(i, tag="member"):
    c = _c()
    return (f"<{tag}>" + c._el("StackSetId", i["StackSetId"]) + c._el("Region", i["Region"]) + c._el("Account", i["Account"]) +
            c._el("StackId", i["StackId"]) + c._el("Status", i["Status"]) + c._el("OrganizationalUnitId", i.get("OrganizationalUnitId")) +
            "<StackInstanceStatus><DetailedStatus>SUCCEEDED</DetailedStatus></StackInstanceStatus><DriftStatus>NOT_CHECKED</DriftStatus>" + f"</{tag}>")


def _list_instances(store, params, stores):
    c = _c()
    ss = _set(store, params)
    acct, reg = c._p(params, "StackInstanceAccount"), c._p(params, "StackInstanceRegion")
    items = [i for i in store.stack_set_instances.get(ss["StackSetName"], []) if (not acct or i["Account"] == acct) and (not reg or i["Region"] == reg)]
    return c._envelope("ListStackInstances", "<Summaries>" + "".join(_member_xml(i) for i in items) + "</Summaries>")


def _describe_instance(store, params, stores):
    c = _c()
    ss = _set(store, params)
    acct, reg = c._p(params, "StackInstanceAccount"), c._p(params, "StackInstanceRegion")
    i = next((x for x in store.stack_set_instances.get(ss["StackSetName"], []) if x["Account"] == acct and x["Region"] == reg), None)
    if not i:
        raise c.CfnError("StackInstanceNotFoundException", f"Stack instance for account {acct} in {reg} not found.", 404)
    return c._envelope("DescribeStackInstance", _member_xml(i, "StackInstance"))


def _list_ops(store, params, stores):
    c = _c()
    ss = _set(store, params)
    ops = [o for o in _ops(store).values() if o["StackSetName"] == ss["StackSetName"]]
    ops.sort(key=lambda o: o["CreationTimestamp"], reverse=True)
    return c._envelope("ListStackSetOperations", "<Summaries>" + "".join(
        "<member>" + c._el("OperationId", o["OperationId"]) + c._el("Action", o["Action"]) + c._el("Status", o["Status"]) +
        c._el("CreationTimestamp", o["CreationTimestamp"]) + c._el("EndTimestamp", o["EndTimestamp"]) + "</member>" for o in ops) + "</Summaries>")


def _describe_op(store, params, stores):
    c = _c()
    ss = _set(store, params)
    o = _ops(store).get(c._p(params, "OperationId"))
    if not o or o["StackSetName"] != ss["StackSetName"]:
        raise c.CfnError("OperationNotFoundException", f"Operation {c._p(params, 'OperationId')} not found.", 404)
    return c._envelope("DescribeStackSetOperation", "<StackSetOperation>" + c._el("OperationId", o["OperationId"]) + c._el("StackSetId", o["StackSetId"]) +
                       c._el("Action", o["Action"]) + c._el("Status", o["Status"]) + c._el("CreationTimestamp", o["CreationTimestamp"]) +
                       c._el("EndTimestamp", o["EndTimestamp"]) + "</StackSetOperation>")


def install(actions: dict) -> None:
    actions.update({
        "ActivateOrganizationsAccess": _activate, "DeactivateOrganizationsAccess": _deactivate,
        "DescribeOrganizationsAccess": _describe_access, "CreateStackInstances": _create_instances,
        "DeleteStackInstances": _delete_instances, "ListStackInstances": _list_instances,
        "DescribeStackInstance": _describe_instance, "ListStackSetOperations": _list_ops,
        "DescribeStackSetOperation": _describe_op,
    })
    actions["CreateStackSet"] = _create_stack_set(actions["CreateStackSet"])
