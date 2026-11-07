# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""SSM wire-gap operations merged into ssm_core._OPS (v4 wire sweep): service settings, Inventory, OpsCenter (OpsItems +
OpsMetadata), hybrid Activations, Resource Data Syncs, resource policies, Compliance, patch-group registration + the other
Patch Manager reads, Maintenance Window tasks / targets / schedule lookups, State Manager association extras (batch create,
versions, status, run-once, executions), document permissions / metadata, Automation executions and GetConnectionStatus.

State lives on ``store.gap`` (a public dict attr, captured by core/nano_persist like the rest of SsmStore) next to the records
ssm_core already keeps (parameters, documents, associations, windows, baselines, commands), and the new operations read those:
patch groups resolve to real baselines, window-target lookups match real registered targets, an Automation `aws:runCommand`
step creates a real SSM command, association executions reference real associations.

Honest limits: there is no SSM agent behind any managed node, so instance patch states / compliance scans / association
executions only exist when something wrote them (PutComplianceItems, StartAssociationsOnce); Automation executes `aws:sleep`,
`aws:pause`, `aws:runCommand` and `aws:branch`-free linear runbooks — other actions (aws:executeAwsApi, aws:changeInstanceState,
...) fail the step with a clear message, as do the Amazon-owned runbooks that ship without steps here; the Patch Manager
catalogue (DescribeAvailablePatches) is empty because the simulator carries no OS patch feed; maintenance windows do not fire on
their own schedule."""
from __future__ import annotations

import json
import re
import time
import uuid


def _S():
    try:
        from core import ssm_core
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import ssm_core  # type: ignore
    return ssm_core


def _err(code, msg, status=400):
    return _S().SsmError(code, msg, status)


def _need(b, *names):
    _S()._need(b, *names)


def _now():
    return round(time.time(), 3)


def _g(store):
    g = getattr(store, "gap", None)
    if not isinstance(g, dict):
        g = store.gap = {}
    for k in ("settings", "inventory", "inv_deletions", "opsitems", "opsitem_events", "opsmetadata", "activations", "syncs", "policies",
              "compliance", "patch_groups", "wtasks", "assoc_versions", "assoc_exec", "assoc_status", "doc_perms", "doc_reviews",
              "automations"):
        g.setdefault(k, {})
    g.setdefault("default_baselines", {})
    return g


def _arn(kind, ident):
    return f"arn:aws:ssm:{_S().REGION}:{_S().ACCOUNT}:{kind}/{ident}"


def _hex(n):
    return uuid.uuid4().hex[:n]


# ───────────────────────── service settings ─────────────────────────
_SETTINGS = {
    "/ssm/parameter-store/default-parameter-tier": "Standard",
    "/ssm/parameter-store/high-throughput-enabled": "false",
    "/ssm/managed-instance/activation-tier": "standard",
    "/ssm/opsinsights/opscenter": "Disabled",
    "/ssm/automation/customer-script-log-destination": "CloudWatch",
    "/ssm/automation/customer-script-log-group-name": "",
    "/ssm/documents/console/public-sharing-permission": "Enable",
    "/ssm/appmanager/appmanager-enabled": "false",
    "/ssm/automation/enable-adaptive-concurrency": "false",
}
_SETTING_ENUMS = {
    "/ssm/parameter-store/default-parameter-tier": ("Standard", "Advanced", "Intelligent-Tiering"),
    "/ssm/parameter-store/high-throughput-enabled": ("true", "false"),
    "/ssm/managed-instance/activation-tier": ("standard", "advanced"),
    "/ssm/opsinsights/opscenter": ("Enabled", "Disabled"),
    "/ssm/documents/console/public-sharing-permission": ("Enable", "Disable"),
    "/ssm/appmanager/appmanager-enabled": ("true", "false"),
}


def _setting_key(sid):
    m = re.match(r"^arn:aws:ssm:[^:]*:\d{12}:servicesetting(/.+)$", sid or "")
    key = m.group(1) if m else sid
    if key not in _SETTINGS:
        raise _err("ServiceSettingNotFound", f"The service setting {sid} was not found.")
    return key


def _setting_view(store, key):
    cur = _g(store)["settings"].get(key)
    v = {"SettingId": _arn("servicesetting", key.lstrip("/")).replace("servicesetting/", "servicesetting/"), "SettingValue": cur["value"] if cur else _SETTINGS[key],
         "LastModifiedDate": cur["at"] if cur else 0.0, "LastModifiedUser": cur["user"] if cur else "System",
         "ARN": f"arn:aws:ssm:{_S().REGION}:{_S().ACCOUNT}:servicesetting{key}", "Status": "Customized" if cur else "Default"}
    v["SettingId"] = v["ARN"]
    return v


def get_service_setting(store, b):
    _need(b, "SettingId")
    return {"ServiceSetting": _setting_view(store, _setting_key(b["SettingId"]))}


def update_service_setting(store, b):
    _need(b, "SettingId", "SettingValue")
    key = _setting_key(b["SettingId"])
    allowed = _SETTING_ENUMS.get(key)
    if allowed and b["SettingValue"] not in allowed:
        raise _err("ValidationException", f"SettingValue must be one of {list(allowed)} for {key}.")
    _g(store)["settings"][key] = {"value": b["SettingValue"], "at": _now(), "user": f"arn:aws:iam::{_S().ACCOUNT}:root"}
    return {}


def reset_service_setting(store, b):
    _need(b, "SettingId")
    key = _setting_key(b["SettingId"])
    _g(store)["settings"].pop(key, None)
    return {"ServiceSetting": _setting_view(store, key)}


# ───────────────────────── inventory ─────────────────────────
_INV_BUILTIN = {"AWS:InstanceInformation": ["AgentType", "AgentVersion", "ComputerName", "InstanceId", "IpAddress", "PlatformName", "PlatformType", "PlatformVersion", "ResourceType"],
                "AWS:Application": ["Name", "ApplicationType", "Publisher", "Version", "Architecture", "InstalledTime", "Summary"],
                "AWS:AWSComponent": ["Name", "ApplicationType", "Publisher", "Version", "InstalledTime"],
                "AWS:Network": ["Name", "SubnetMask", "Gateway", "DHCPServer", "DNSServer", "MacAddress", "IPV4", "IPV6"],
                "AWS:File": ["Name", "Size", "Description", "FileVersion", "InstalledDir", "ModificationTime", "LastAccessTime", "CompanyName"],
                "AWS:WindowsUpdate": ["HotFixId", "Description", "InstalledTime", "InstalledBy"],
                "AWS:Service": ["Name", "DisplayName", "ServiceType", "Status", "StartType"],
                "AWS:Tag": ["Key", "Value"]}
_INSTANCE_ID = re.compile(r"^(i-[0-9a-f]{8,17}|mi-[0-9a-f]{17})$")


def put_inventory(store, b):
    _need(b, "InstanceId", "Items")
    if not _INSTANCE_ID.match(b["InstanceId"]):
        raise _err("InvalidInstanceId", "The following instances do not exist or are not in a valid state for Systems Manager inventory.")
    g = _g(store)["inventory"]
    for it in b["Items"]:
        t = it.get("TypeName", "")
        if not (t.startswith("Custom:") or t in _INV_BUILTIN):
            raise _err("InvalidTypeNameException", f"The type name {t} is invalid; custom types start with 'Custom:'.")
        if t.startswith("Custom:") and not re.fullmatch(r"Custom:[A-Za-z0-9_.-]{1,100}", t):
            raise _err("InvalidTypeNameException", f"The type name {t} is invalid.")
        if not it.get("Content") and not it.get("ContentHash"):
            raise _err("InvalidItemContentException", "Content is required.", 400)
        if it.get("Content") is not None and len(it["Content"]) > 100:
            raise _err("ItemSizeLimitExceededException", "An inventory item can hold at most 100 entries.")
    for it in b["Items"]:
        g.setdefault(b["InstanceId"], {})[it["TypeName"]] = {"SchemaVersion": it.get("SchemaVersion", "1.0"), "CaptureTime": it.get("CaptureTime", ""),
                                                             "ContentHash": it.get("ContentHash") or uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(it.get("Content"), sort_keys=True)).hex,
                                                             "Content": it.get("Content") or []}
    return {"Message": "Inventory updated."}


def _op_match(v, vals, op):
    v = "" if v is None else str(v)
    if op == "Equal":
        return v in vals
    if op == "NotEqual":
        return v not in vals
    if op == "BeginWith":
        return any(v.startswith(x) for x in vals)
    if op in ("LessThan", "GreaterThan"):
        try:
            return any((float(v) < float(x)) if op == "LessThan" else (float(v) > float(x)) for x in vals)
        except ValueError:
            return False
    return op == "Exists" and v != ""


def _inv_match(inst, f, data):
    """Inventory filter `Key` is `<TypeName>.<attribute>`; true when any captured row (or the instance id) satisfies it."""
    key, vals, op = f.get("Key", ""), f.get("Values") or [], f.get("Type", "Equal")
    tname, _, attr = key.rpartition(".")
    if tname == "AWS:InstanceInformation" and attr == "InstanceId":
        return _op_match(inst, vals, op)
    rows = (data.get(tname) or {}).get("Content", [])
    if not rows:
        return op == "NotEqual"
    return any(_op_match(r.get(attr), vals, op) for r in rows)


def get_inventory(store, b):
    ents = []
    for inst, data in sorted(_g(store)["inventory"].items()):
        if all(_inv_match(inst, f, data) for f in b.get("Filters") or []):
            ents.append({"Id": inst, "Data": {t: dict(d, TypeName=t) for t, d in data.items()}})
    return _S()._page(ents, b, "Entities", 50, 50)


def list_inventory_entries(store, b):
    _need(b, "InstanceId", "TypeName")
    d = (_g(store)["inventory"].get(b["InstanceId"]) or {}).get(b["TypeName"])
    if d is None:
        raise _err("InvalidTypeNameException", f"No inventory of type {b['TypeName']} for {b['InstanceId']}.")
    entries = [e for e in d["Content"] if all(_op_match(e.get(f["Key"]), f.get("Values") or [], f.get("Type", "Equal")) for f in b.get("Filters") or [])]
    return {"TypeName": b["TypeName"], "InstanceId": b["InstanceId"], "SchemaVersion": d["SchemaVersion"], "CaptureTime": d["CaptureTime"], "Entries": entries}


def get_inventory_schema(store, b):
    custom = {t for data in _g(store)["inventory"].values() for t in data if t.startswith("Custom:")}
    schemas = []
    for t in sorted(_INV_BUILTIN) + sorted(custom):
        if b.get("TypeName") and b["TypeName"] != t:
            continue
        attrs = _INV_BUILTIN.get(t) or sorted({k for data in _g(store)["inventory"].values() if t in data for e in data[t]["Content"] for k in e})
        schemas.append({"TypeName": t, "Version": "1.0", "Attributes": [{"Name": a, "DataType": "string"} for a in attrs], "DisplayName": t.split(":", 1)[-1]})
    if b.get("TypeName") and not schemas:
        raise _err("InvalidTypeNameException", f"No schema named {b['TypeName']}.")
    return _S()._page(schemas, b, "Schemas", 50, 50)


def delete_inventory(store, b):
    _need(b, "TypeName")
    t = b["TypeName"]
    if not t.startswith("Custom:"):
        raise _err("InvalidTypeNameException", "Only custom inventory types can be deleted.")
    opt = b.get("SchemaDeleteOption", "DisableSchema")
    if opt not in ("DisableSchema", "DeleteSchema"):
        raise _err("InvalidOptionException", "SchemaDeleteOption must be DisableSchema or DeleteSchema.")
    inv = _g(store)["inventory"]
    holders = [i for i, d in inv.items() if t in d]
    if not holders and opt == "DisableSchema":
        raise _err("InvalidTypeNameException", f"No inventory of type {t}.")
    n_items = sum(len(inv[i][t]["Content"]) for i in holders)
    did = str(uuid.uuid4())
    if not b.get("DryRun"):
        for i in holders:
            inv[i].pop(t)
        _g(store)["inv_deletions"][did] = {"DeletionId": did, "TypeName": t, "DeletionStartTime": _now(), "LastStatus": "Complete",
                                           "LastStatusMessage": "Deletion is complete.", "DeletionSummary": {"TotalCount": n_items, "RemainingCount": 0, "SummaryItems": [{"Version": "1.0", "Count": n_items, "RemainingCount": 0}]}}
    return {"DeletionId": did, "TypeName": t, "DeletionSummary": {"TotalCount": n_items, "RemainingCount": 0 if not b.get("DryRun") else n_items, "SummaryItems": [{"Version": "1.0", "Count": n_items, "RemainingCount": 0}]}}


def describe_inventory_deletions(store, b):
    items = list(_g(store)["inv_deletions"].values())
    if b.get("DeletionId"):
        items = [d for d in items if d["DeletionId"] == b["DeletionId"]]
        if not items:
            raise _err("InvalidDeletionIdException", "The deletion ID is invalid.")
    return _S()._page(items, b, "InventoryDeletions", 50, 50)


# ───────────────────────── OpsCenter ─────────────────────────
_OPS_STATUS = ("Open", "InProgress", "Resolved", "Pending", "TimedOut", "Cancelling", "Cancelled", "Failed", "CompletedWithSuccess", "CompletedWithFailure",
               "Scheduled", "RunbookInProgress", "PendingChangeCalendarOverride", "ChangeCalendarOverrideApproved", "ChangeCalendarOverrideRejected",
               "PendingApproval", "Approved", "Revoked", "Rejected", "Closed")


def _opsitem(store, oid):
    o = _g(store)["opsitems"].get(oid)
    if o is None:
        raise _err("OpsItemNotFoundException", f"OpsItem {oid} not found.")
    return o


def _ops_event(store, oid, source, detail_type, detail):
    _g(store)["opsitem_events"].setdefault(oid, []).append({"OpsItemId": oid, "Source": source, "DetailType": detail_type, "Detail": detail,
                                                            "CreatedBy": {"Arn": f"arn:aws:iam::{_S().ACCOUNT}:root"}, "CreatedTime": _now()})


def create_opsitem(store, b):
    _need(b, "Description", "Source", "Title")
    if b.get("Priority") is not None and not 1 <= int(b["Priority"]) <= 5:
        raise _err("ValidationException", "Priority must be between 1 and 5.")
    if b.get("Severity") is not None and b["Severity"] not in ("1", "2", "3", "4"):
        raise _err("ValidationException", "Severity must be 1-4.")
    oid = "oi-" + _hex(12)
    rec = {"OpsItemId": oid, "OpsItemType": b.get("OpsItemType", "/aws/issue"), "Description": b["Description"], "Source": b["Source"], "Title": b["Title"],
           "Status": "Open", "Priority": b.get("Priority"), "Severity": b.get("Severity"), "Category": b.get("Category"),
           "OperationalData": b.get("OperationalData") or {}, "Notifications": b.get("Notifications") or [], "RelatedOpsItems": b.get("RelatedOpsItems") or [],
           "CreatedBy": f"arn:aws:iam::{_S().ACCOUNT}:root", "CreatedTime": _now(), "LastModifiedBy": f"arn:aws:iam::{_S().ACCOUNT}:root", "LastModifiedTime": _now(),
           "Version": "1", "OpsItemArn": _arn("opsitem", oid), "_related": [], "_tags": {t["Key"]: t["Value"] for t in b.get("Tags") or []}}
    _g(store)["opsitems"][oid] = rec
    _ops_event(store, oid, "SSM", "ssm:OpsItem:Create", "OpsItem created")
    return {"OpsItemId": oid, "OpsItemArn": rec["OpsItemArn"]}


def _opsview(o):
    return {k: v for k, v in o.items() if not k.startswith("_") and v is not None}


def get_opsitem(store, b):
    _need(b, "OpsItemId")
    return {"OpsItem": _opsview(_opsitem(store, b["OpsItemId"]))}


def update_opsitem(store, b):
    _need(b, "OpsItemId")
    o = _opsitem(store, b["OpsItemId"])
    if b.get("Status") is not None and b["Status"] not in _OPS_STATUS:
        raise _err("ValidationException", f"Status must be one of {list(_OPS_STATUS)}.")
    old = o["Status"]
    for k in ("Description", "Title", "Priority", "Severity", "Category", "Status", "Notifications", "RelatedOpsItems"):
        if b.get(k) is not None:
            o[k] = b[k]
    for k, v in (b.get("OperationalData") or {}).items():
        o["OperationalData"][k] = v
    for k in b.get("OperationalDataToDelete") or []:
        o["OperationalData"].pop(k, None)
    o["LastModifiedTime"] = _now()
    o["Version"] = str(int(o["Version"]) + 1)
    if o["Status"] != old:
        _ops_event(store, o["OpsItemId"], "SSM", "ssm:OpsItem:StatusChange", f"{old} -> {o['Status']}")
    return {}


def delete_opsitem(store, b):
    _need(b, "OpsItemId")
    _opsitem(store, b["OpsItemId"])
    _g(store)["opsitems"].pop(b["OpsItemId"])
    _g(store)["opsitem_events"].pop(b["OpsItemId"], None)
    return {}


def describe_opsitems(store, b):
    items = list(_g(store)["opsitems"].values())
    for f in b.get("OpsItemFilters") or []:
        key, vals, op = f["Key"], f.get("Values") or [], f.get("Operator", "Equal")
        def v(o):
            return str(o.get(key, ""))
        if op == "Equal":
            items = [o for o in items if v(o) in vals]
        elif op == "Contains":
            items = [o for o in items if any(x in v(o) for x in vals)]
        elif op == "GreaterThan":
            items = [o for o in items if any(v(o) > x for x in vals)]
        elif op == "LessThan":
            items = [o for o in items if any(v(o) < x for x in vals)]
    summ = [{k: o.get(k) for k in ("CreatedBy", "CreatedTime", "LastModifiedBy", "LastModifiedTime", "Priority", "Source", "Status", "OpsItemId", "Title", "OperationalData", "Category", "Severity", "OpsItemType") if o.get(k) is not None} for o in items]
    return _S()._page(summ, b, "OpsItemSummaries", 50, 50)


def list_opsitem_events(store, b):
    ev = [e for oid, es in _g(store)["opsitem_events"].items() for e in es]
    for f in b.get("Filters") or []:
        if f.get("Key") == "OpsItemId":
            ev = [e for e in ev if e["OpsItemId"] in (f.get("Values") or [])]
    return _S()._page(ev, b, "Summaries", 50, 50)


def associate_related(store, b):
    _need(b, "OpsItemId", "AssociationType", "ResourceType", "ResourceUri")
    o = _opsitem(store, b["OpsItemId"])
    if any(r["ResourceUri"] == b["ResourceUri"] for r in o["_related"]):
        raise _err("OpsItemRelatedItemAlreadyExistsException", "The related item already exists.")
    aid = str(uuid.uuid4())
    o["_related"].append({"OpsItemId": o["OpsItemId"], "AssociationId": aid, "ResourceType": b["ResourceType"], "AssociationType": b["AssociationType"],
                          "ResourceUri": b["ResourceUri"], "CreatedBy": {"Arn": f"arn:aws:iam::{_S().ACCOUNT}:root"}, "CreatedTime": _now()})
    return {"AssociationId": aid}


def disassociate_related(store, b):
    _need(b, "OpsItemId", "AssociationId")
    o = _opsitem(store, b["OpsItemId"])
    n = len(o["_related"])
    o["_related"] = [r for r in o["_related"] if r["AssociationId"] != b["AssociationId"]]
    if len(o["_related"]) == n:
        raise _err("OpsItemRelatedItemAssociationNotFoundException", "The association was not found.")
    return {}


def list_related(store, b):
    items = [r for o in _g(store)["opsitems"].values() for r in o["_related"] if not b.get("OpsItemId") or o["OpsItemId"] == b["OpsItemId"]]
    return _S()._page(items, b, "Summaries", 50, 50)


def create_opsmetadata(store, b):
    _need(b, "ResourceId")
    arn = _arn("opsmetadata", b["ResourceId"].strip("/"))
    if arn in _g(store)["opsmetadata"]:
        raise _err("OpsMetadataAlreadyExistsException", "OpsMetadata already exists for this resource.")
    _g(store)["opsmetadata"][arn] = {"ResourceId": b["ResourceId"], "OpsMetadataArn": arn, "LastModifiedDate": _now(), "LastModifiedUser": f"arn:aws:iam::{_S().ACCOUNT}:root",
                                     "CreationDate": _now(), "_md": dict(b.get("Metadata") or {})}
    return {"OpsMetadataArn": arn}


def _opsmd(store, arn):
    m = _g(store)["opsmetadata"].get(arn or "")
    if m is None:
        raise _err("OpsMetadataNotFoundException", "OpsMetadata not found.")
    return m


def get_opsmetadata(store, b):
    _need(b, "OpsMetadataArn")
    m = _opsmd(store, b["OpsMetadataArn"])
    return {"ResourceId": m["ResourceId"], "Metadata": m["_md"]}


def update_opsmetadata(store, b):
    _need(b, "OpsMetadataArn")
    m = _opsmd(store, b["OpsMetadataArn"])
    m["_md"].update(b.get("MetadataToUpdate") or {})
    for k in b.get("KeysToDelete") or []:
        m["_md"].pop(k, None)
    m["LastModifiedDate"] = _now()
    return {"OpsMetadataArn": m["OpsMetadataArn"], "ResourceId": m["ResourceId"]}


def delete_opsmetadata(store, b):
    _need(b, "OpsMetadataArn")
    _opsmd(store, b["OpsMetadataArn"])
    del _g(store)["opsmetadata"][b["OpsMetadataArn"]]
    return {}


def list_opsmetadata(store, b):
    items = [{k: v for k, v in m.items() if not k.startswith("_")} for m in _g(store)["opsmetadata"].values()]
    return _S()._page(items, b, "OpsMetadataList", 50, 50)


# ───────────────────────── activations ─────────────────────────
def create_activation(store, b):
    _need(b, "IamRole")
    if b.get("RegistrationLimit") is not None and not 1 <= int(b["RegistrationLimit"]) <= 1000:
        raise _err("ValidationException", "RegistrationLimit must be 1-1000.")
    aid = str(uuid.uuid4())
    code = _hex(20)
    _g(store)["activations"][aid] = {"ActivationId": aid, "Description": b.get("Description", ""), "DefaultInstanceName": b.get("DefaultInstanceName", ""), "IamRole": b["IamRole"],
                                     "RegistrationLimit": int(b.get("RegistrationLimit") or 1), "RegistrationsCount": 0,
                                     "ExpirationDate": b.get("ExpirationDate") or _now() + 86400 * 30, "Expired": False, "CreatedDate": _now(),
                                     "Tags": [{"Key": t["Key"], "Value": t.get("Value", "")} for t in b.get("Tags") or []]}
    return {"ActivationId": aid, "ActivationCode": code}


def describe_activations(store, b):
    items = list(_g(store)["activations"].values())
    now = _now()
    for a in items:
        a["Expired"] = float(a["ExpirationDate"]) < now
    for f in b.get("Filters") or []:
        key = {"ActivationIds": "ActivationId", "DefaultInstanceName": "DefaultInstanceName", "IamRole": "IamRole"}.get(f.get("FilterKey"))
        if key:
            items = [a for a in items if a[key] in (f.get("FilterValues") or [])]
    return _S()._page(items, b, "ActivationList", 50, 50)


def delete_activation(store, b):
    _need(b, "ActivationId")
    a = _g(store)["activations"].get(b["ActivationId"])
    if a is None:
        raise _err("InvalidActivationId", "The activation ID is not valid.")
    if a["RegistrationsCount"]:
        raise _err("InvalidActivation", "The activation has registered instances; deregister them first.")
    del _g(store)["activations"][b["ActivationId"]]
    return {}


def _managed_missing(b):
    raise _err("InvalidInstanceId", f"Instance {b.get('InstanceId')} is not a registered managed instance.")


def describe_instance_properties(store, b):
    items = []
    for iid, i in sorted(_S()._instances().items()):
        if i.get("state") == "running":
            items.append({"InstanceId": iid, "InstanceState": "running", "PingStatus": "Online", "ResourceType": "EC2Instance", "PlatformType": "Linux",
                          "IPAddress": i.get("ip") or "", "ComputerName": i.get("name") or iid, "AgentVersion": "3.3.0"})
    return _S()._page(items, b, "InstanceProperties", 50, 50)


def get_connection_status(store, b):
    _need(b, "Target")
    inst = _S()._instances().get(b["Target"])
    return {"Target": b["Target"], "Status": "connected" if inst and inst.get("state") == "running" else "notconnected"}


# ───────────────────────── resource data sync / policies ─────────────────────────
def create_sync(store, b):
    _need(b, "SyncName")
    s = _g(store)["syncs"]
    if b["SyncName"] in s:
        raise _err("ResourceDataSyncAlreadyExistsException", f"A sync named {b['SyncName']} already exists.")
    st = b.get("SyncType", "SyncToDestination")
    if st == "SyncToDestination" and not b.get("S3Destination"):
        raise _err("ResourceDataSyncInvalidConfigurationException", "S3Destination is required for SyncToDestination.")
    s[b["SyncName"]] = {"SyncName": b["SyncName"], "SyncType": st, "S3Destination": b.get("S3Destination"), "SyncSource": b.get("SyncSource"),
                        "LastSyncTime": _now(), "LastStatus": "Successful", "SyncCreatedTime": _now(), "LastSuccessfulSyncTime": _now(), "SyncLastModifiedTime": _now()}
    return {}


def list_syncs(store, b):
    return _S()._page([{k: v for k, v in s.items() if v is not None} for s in _g(store)["syncs"].values()], b, "ResourceDataSyncItems", 50, 50)


def update_sync(store, b):
    _need(b, "SyncName", "SyncType", "SyncSource")
    s = _g(store)["syncs"].get(b["SyncName"])
    if s is None:
        raise _err("ResourceDataSyncNotFoundException", f"Sync {b['SyncName']} not found.")
    if s["SyncType"] != b["SyncType"]:
        raise _err("ResourceDataSyncInvalidConfigurationException", "SyncType cannot be changed.")
    s["SyncSource"] = b["SyncSource"]
    s["SyncLastModifiedTime"] = _now()
    return {}


def delete_sync(store, b):
    _need(b, "SyncName")
    if _g(store)["syncs"].pop(b["SyncName"], None) is None:
        raise _err("ResourceDataSyncNotFoundException", f"Sync {b['SyncName']} not found.")
    return {}


def _policy_target(store, arn):
    m = re.match(r"^arn:aws:ssm:[^:]*:\d{12}:(parameter|opsitemgroup|opsmetadata)(/.*)?$", arn or "")
    if not m:
        raise _err("ResourceNotFoundException", f"{arn} is not an SSM resource that supports resource policies.")
    if m.group(1) == "parameter":
        name = m.group(2) or ""
        if name not in store.parameters and name.lstrip("/") not in store.parameters:
            raise _err("ResourceNotFoundException", f"Parameter {name} not found.")


def put_resource_policy(store, b):
    _need(b, "ResourceArn", "Policy")
    _policy_target(store, b["ResourceArn"])
    try:
        json.loads(b["Policy"])
    except ValueError:
        raise _err("MalformedResourcePolicyDocumentException", "Policy is not valid JSON.")
    lst = _g(store)["policies"].setdefault(b["ResourceArn"], [])
    if b.get("PolicyId"):
        cur = next((p for p in lst if p["PolicyId"] == b["PolicyId"]), None)
        if cur is None:
            raise _err("ResourcePolicyNotFoundException", "PolicyId not found.")
        if b.get("PolicyHash") and b["PolicyHash"] != cur["PolicyHash"]:
            raise _err("ResourcePolicyConflictException", "PolicyHash does not match the current policy.")
        cur.update(Policy=b["Policy"], PolicyHash=_hex(32))
        return {"PolicyId": cur["PolicyId"], "PolicyHash": cur["PolicyHash"]}
    if lst:
        raise _err("ResourcePolicyLimitExceededException", "The resource already has the maximum number of policies.")
    rec = {"PolicyId": str(uuid.uuid4()), "PolicyHash": _hex(32), "Policy": b["Policy"]}
    lst.append(rec)
    return {"PolicyId": rec["PolicyId"], "PolicyHash": rec["PolicyHash"]}


def get_resource_policies(store, b):
    _need(b, "ResourceArn")
    _policy_target(store, b["ResourceArn"])
    return _S()._page(list(_g(store)["policies"].get(b["ResourceArn"], [])), b, "Policies", 50, 50)


def delete_resource_policy(store, b):
    _need(b, "ResourceArn", "PolicyId", "PolicyHash")
    lst = _g(store)["policies"].get(b["ResourceArn"], [])
    cur = next((p for p in lst if p["PolicyId"] == b["PolicyId"]), None)
    if cur is None:
        raise _err("ResourcePolicyNotFoundException", "PolicyId not found.")
    if cur["PolicyHash"] != b["PolicyHash"]:
        raise _err("ResourcePolicyConflictException", "PolicyHash does not match the current policy.")
    lst.remove(cur)
    return {}


# ───────────────────────── compliance ─────────────────────────
def put_compliance_items(store, b):
    _need(b, "ResourceId", "ResourceType", "ComplianceType", "ExecutionSummary", "Items")
    if b["ComplianceType"].startswith("Association") or b["ComplianceType"].startswith("Patch"):
        raise _err("InvalidItemContentException", "Custom compliance types must not start with 'Association' or 'Patch'.")
    for it in b["Items"]:
        if it.get("Status") not in ("COMPLIANT", "NON_COMPLIANT") or it.get("Severity") not in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL", "UNSPECIFIED"):
            raise _err("InvalidItemContentException", "Each item needs Status COMPLIANT|NON_COMPLIANT and a valid Severity.")
    key = (b["ResourceType"], b["ResourceId"], b["ComplianceType"])
    _g(store)["compliance"]["|".join(key)] = {"ResourceType": b["ResourceType"], "ResourceId": b["ResourceId"], "ComplianceType": b["ComplianceType"],
                                              "ExecutionSummary": b["ExecutionSummary"], "Items": [dict(i) for i in b["Items"]]}
    return {}


def _cflt(rows, b):
    if b.get("ResourceIds"):
        rows = [r for r in rows if r["ResourceId"] in b["ResourceIds"]]
    if b.get("ResourceTypes"):
        rows = [r for r in rows if r["ResourceType"] in b["ResourceTypes"]]
    for f in b.get("Filters") or []:
        key = {"ComplianceType": "ComplianceType", "ResourceType": "ResourceType", "ResourceId": "ResourceId"}.get(f.get("Key"))
        if key:
            rows = [r for r in rows if r[key] in (f.get("Values") or [])]
    return rows


def list_compliance_items(store, b):
    out = []
    for r in _cflt(list(_g(store)["compliance"].values()), b):
        for it in r["Items"]:
            out.append({"ComplianceType": r["ComplianceType"], "ResourceType": r["ResourceType"], "ResourceId": r["ResourceId"], "Id": it.get("Id", ""), "Title": it.get("Title", ""),
                        "Status": it["Status"], "Severity": it["Severity"], "ExecutionSummary": r["ExecutionSummary"], "Details": it.get("Details", {})})
    return _S()._page(out, b, "ComplianceItems", 50, 50)


def _sev_counts(items):
    c = {k: 0 for k in ("CriticalCount", "HighCount", "MediumCount", "LowCount", "InformationalCount", "UnspecifiedCount")}
    for it in items:
        c[{"CRITICAL": "CriticalCount", "HIGH": "HighCount", "MEDIUM": "MediumCount", "LOW": "LowCount", "INFORMATIONAL": "InformationalCount"}.get(it["Severity"], "UnspecifiedCount")] += 1
    return c


def list_compliance_summaries(store, b):
    by = {}
    for r in _cflt(list(_g(store)["compliance"].values()), b):
        by.setdefault(r["ComplianceType"], []).append(r)
    out = []
    for t, rows in sorted(by.items()):
        comp = sum(1 for r in rows if all(i["Status"] == "COMPLIANT" for i in r["Items"]))
        out.append({"ComplianceType": t, "CompliantSummary": dict({"CompliantCount": comp}, SeveritySummary=_sev_counts([i for r in rows if all(i["Status"] == "COMPLIANT" for i in r["Items"]) for i in r["Items"]])),
                    "NonCompliantSummary": dict({"NonCompliantCount": len(rows) - comp}, SeveritySummary=_sev_counts([i for r in rows if not all(i["Status"] == "COMPLIANT" for i in r["Items"]) for i in r["Items"]]))})
    return _S()._page(out, b, "ComplianceSummaryItems", 50, 50)


def list_resource_compliance_summaries(store, b):
    out = []
    for r in _cflt(list(_g(store)["compliance"].values()), b):
        bad = [i for i in r["Items"] if i["Status"] != "COMPLIANT"]
        out.append({"ComplianceType": r["ComplianceType"], "ResourceType": r["ResourceType"], "ResourceId": r["ResourceId"], "Status": "NON_COMPLIANT" if bad else "COMPLIANT",
                    "OverallSeverity": "UNSPECIFIED", "ExecutionSummary": r["ExecutionSummary"], "CompliantSummary": {"CompliantCount": len(r["Items"]) - len(bad), "SeveritySummary": _sev_counts([i for i in r["Items"] if i["Status"] == "COMPLIANT"])},
                    "NonCompliantSummary": {"NonCompliantCount": len(bad), "SeveritySummary": _sev_counts(bad)}})
    return _S()._page(out, b, "ResourceComplianceSummaryItems", 50, 50)


# ───────────────────────── patch manager ─────────────────────────
def _baseline(store, bid):
    p = store.baselines.get(bid or "")
    if p is None:
        raise _err("DoesNotExistException", f"Patch baseline {bid} does not exist")
    return p


def register_patch_group(store, b):
    _need(b, "BaselineId", "PatchGroup")
    p = _baseline(store, b["BaselineId"])
    pg = _g(store)["patch_groups"]
    cur = pg.get(f"{b['PatchGroup']}|{p['os']}")
    if cur and cur != p["id"]:
        raise _err("AlreadyExistsException", f"Patch group {b['PatchGroup']} is already registered with a baseline for {p['os']}.")
    pg[f"{b['PatchGroup']}|{p['os']}"] = p["id"]
    return {"BaselineId": p["id"], "PatchGroup": b["PatchGroup"]}


def deregister_patch_group(store, b):
    _need(b, "BaselineId", "PatchGroup")
    p = _baseline(store, b["BaselineId"])
    if _g(store)["patch_groups"].get(f"{b['PatchGroup']}|{p['os']}") != p["id"]:
        raise _err("DoesNotExistException", f"Patch group {b['PatchGroup']} is not registered with {p['id']}.")
    del _g(store)["patch_groups"][f"{b['PatchGroup']}|{p['os']}"]
    return {"BaselineId": p["id"], "PatchGroup": b["PatchGroup"]}


def _default_for(store, os_):
    d = _g(store)["default_baselines"].get(os_)
    if d and d in store.baselines:
        return d
    return next((p["id"] for p in store.baselines.values() if p["os"] == os_ and p.get("default")), None)


def get_baseline_for_group(store, b):
    _need(b, "PatchGroup")
    os_ = b.get("OperatingSystem") or "WINDOWS"
    bid = _g(store)["patch_groups"].get(f"{b['PatchGroup']}|{os_}") or _default_for(store, os_)
    if bid is None:
        raise _err("DoesNotExistException", f"No patch baseline for {os_} (register one or set a default).")
    return {"BaselineId": bid, "PatchGroup": b["PatchGroup"], "OperatingSystem": os_}


def describe_patch_groups(store, b):
    rows = [{"PatchGroup": key.split("|")[0], "BaselineIdentity": {"BaselineId": bid, "BaselineName": store.baselines[bid]["name"], "OperatingSystem": key.split("|")[1],
                                                    "BaselineDescription": store.baselines[bid]["description"], "DefaultBaseline": bool(store.baselines[bid].get("default"))}}
            for key, bid in sorted(_g(store)["patch_groups"].items()) if bid in store.baselines]
    for f in b.get("Filters") or []:
        if f.get("Key") == "NAME_PREFIX":
            rows = [r for r in rows if any(r["PatchGroup"].startswith(v) for v in f.get("Values", []))]
    return _S()._page(rows, b, "Mappings", 50, 50)


def register_default_baseline(store, b):
    _need(b, "BaselineId")
    p = _baseline(store, b["BaselineId"])
    g = _g(store)["default_baselines"]
    old = g.get(p["os"])
    if old in store.baselines:
        store.baselines[old]["default"] = False
    g[p["os"]] = p["id"]
    p["default"] = True
    return {"BaselineId": p["id"]}


def get_default_baseline(store, b):
    os_ = b.get("OperatingSystem") or "WINDOWS"
    bid = _default_for(store, os_)
    if bid is None:
        raise _err("DoesNotExistException", f"No default patch baseline for {os_}.")
    return {"BaselineId": bid, "OperatingSystem": os_}


def update_baseline(store, b):
    _need(b, "BaselineId")
    p = _baseline(store, b["BaselineId"])
    for k, f in (("Name", "name"), ("Description", "description"), ("ApprovalRules", "approval_rules"), ("ApprovedPatches", "approved"), ("RejectedPatches", "rejected")):
        if b.get(k) is not None:
            p[f] = b[k]
    p["modified"] = _now()
    return {"BaselineId": p["id"], "Name": p["name"], "OperatingSystem": p["os"], "GlobalFilters": b.get("GlobalFilters") or {"PatchFilters": []},
            "ApprovalRules": p["approval_rules"], "ApprovedPatches": p["approved"], "RejectedPatches": p["rejected"], "CreatedDate": p["created"],
            "ModifiedDate": p["modified"], "Description": p["description"], "Sources": []}


def describe_patch_group_state(store, b):
    _need(b, "PatchGroup")
    return {k: 0 for k in ("Instances", "InstancesWithInstalledPatches", "InstancesWithInstalledOtherPatches", "InstancesWithInstalledPendingRebootPatches",
                           "InstancesWithInstalledRejectedPatches", "InstancesWithMissingPatches", "InstancesWithFailedPatches", "InstancesWithNotApplicablePatches",
                           "InstancesWithUnreportedNotApplicablePatches", "InstancesWithCriticalNonCompliantPatches", "InstancesWithSecurityNonCompliantPatches",
                           "InstancesWithOtherNonCompliantPatches", "InstancesWithAvailableSecurityUpdates")}


_PATCH_PROPS = {("AMAZON_LINUX_2", "PRODUCT"): ["AmazonLinux2", "AmazonLinux2.0"], ("AMAZON_LINUX_2023", "PRODUCT"): ["AmazonLinux2023"], ("UBUNTU", "PRODUCT"): ["Ubuntu20.04", "Ubuntu22.04", "Ubuntu24.04"],
                ("REDHAT_ENTERPRISE_LINUX", "PRODUCT"): ["RedhatEnterpriseLinux8.8", "RedhatEnterpriseLinux9.2"], ("WINDOWS", "PRODUCT"): ["WindowsServer2019", "WindowsServer2022"],
                ("WINDOWS", "CLASSIFICATION"): ["CriticalUpdates", "SecurityUpdates", "DefinitionUpdates", "UpdateRollups", "ServicePacks", "Updates"],
                ("AMAZON_LINUX_2", "CLASSIFICATION"): ["Security", "Bugfix", "Enhancement", "Recommended", "Newpackage"],
                ("AMAZON_LINUX_2", "SEVERITY"): ["Critical", "Important", "Medium", "Low"], ("UBUNTU", "PRIORITY"): ["Required", "Important", "Standard", "Optional", "Extra"]}


def describe_patch_properties(store, b):
    _need(b, "OperatingSystem", "Property")
    vals = _PATCH_PROPS.get((b["OperatingSystem"], b["Property"]))
    if vals is None:
        raise _err("ValidationException", f"{b['Property']} is not a patch property of {b['OperatingSystem']}.")
    return _S()._page([{"Name": v} for v in vals], b, "Properties", 50, 50)


def empty(key):
    return lambda store, b: {key: []}


# ───────────────────────── maintenance windows ─────────────────────────
_TASK_TYPES = ("RUN_COMMAND", "AUTOMATION", "STEP_FUNCTIONS", "LAMBDA")


def _win(store, wid):
    return _S()._need_window(store, wid)


def _wtask(store, wid, tid):
    w = _win(store, wid)
    t = _g(store)["wtasks"].get(wid, {}).get(tid)
    if t is None:
        raise _err("DoesNotExistException", f"Maintenance window task {tid} does not exist")
    return w, t


def register_task(store, b):
    _need(b, "WindowId", "TaskArn", "TaskType")
    w = _win(store, b["WindowId"])
    if b["TaskType"] not in _TASK_TYPES:
        raise _err("ValidationException", f"TaskType must be one of {list(_TASK_TYPES)}.")
    if b["TaskType"] == "RUN_COMMAND" and b["TaskArn"] not in store.documents:
        raise _err("DoesNotExistException", f"Document {b['TaskArn']} does not exist")
    if b.get("Targets"):
        for t in b["Targets"]:
            if t.get("Key") == "WindowTargetIds":
                for v in t.get("Values", []):
                    if v not in w["targets"]:
                        raise _err("DoesNotExistException", f"Maintenance window target {v} does not exist")
    elif b["TaskType"] in ("RUN_COMMAND", "AUTOMATION") and not w.get("allow_unassociated"):
        raise _err("ValidationException", "Targets are required unless the window allows unassociated targets.")
    tid = str(uuid.uuid4())
    _g(store)["wtasks"].setdefault(w["id"], {})[tid] = {"WindowId": w["id"], "WindowTaskId": tid, "TaskArn": b["TaskArn"], "Type": b["TaskType"], "Targets": b.get("Targets") or [],
                                                         "TaskParameters": b.get("TaskParameters") or {}, "TaskInvocationParameters": b.get("TaskInvocationParameters") or {},
                                                         "Priority": int(b.get("Priority") or 1), "ServiceRoleArn": b.get("ServiceRoleArn", ""), "MaxConcurrency": b.get("MaxConcurrency", "1"),
                                                         "MaxErrors": b.get("MaxErrors", "1"), "Name": b.get("Name", ""), "Description": b.get("Description", ""),
                                                         "CutoffBehavior": b.get("CutoffBehavior", "CONTINUE_TASK")}
    return {"WindowTaskId": tid}


def describe_wtasks(store, b):
    _need(b, "WindowId")
    _win(store, b["WindowId"])
    rows = list(_g(store)["wtasks"].get(b["WindowId"], {}).values())
    for f in b.get("Filters") or []:
        key = {"WindowTaskId": "WindowTaskId", "TaskArn": "TaskArn", "Name": "Name", "Type": "Type"}.get(f.get("Key"))
        if key:
            rows = [r for r in rows if r[key] in (f.get("Values") or [])]
    return _S()._page(rows, b, "Tasks", 50, 50)


def get_wtask(store, b):
    _need(b, "WindowId", "WindowTaskId")
    _, t = _wtask(store, b["WindowId"], b["WindowTaskId"])
    return {k: v for k, v in dict(t, TaskType=t["Type"]).items() if k != "Type"}


def update_wtask(store, b):
    _need(b, "WindowId", "WindowTaskId")
    _, t = _wtask(store, b["WindowId"], b["WindowTaskId"])
    for k in ("Targets", "TaskArn", "ServiceRoleArn", "TaskParameters", "TaskInvocationParameters", "Priority", "MaxConcurrency", "MaxErrors", "Name", "Description", "CutoffBehavior"):
        if b.get(k) is not None:
            t[k] = b[k]
    return {k: v for k, v in dict(t, TaskType=t["Type"]).items() if k != "Type"}


def deregister_wtask(store, b):
    _need(b, "WindowId", "WindowTaskId")
    _wtask(store, b["WindowId"], b["WindowTaskId"])
    del _g(store)["wtasks"][b["WindowId"]][b["WindowTaskId"]]
    return {"WindowId": b["WindowId"], "WindowTaskId": b["WindowTaskId"]}


def update_wtarget(store, b):
    _need(b, "WindowId", "WindowTargetId")
    w = _win(store, b["WindowId"])
    t = w["targets"].get(b["WindowTargetId"])
    if t is None:
        raise _err("DoesNotExistException", f"Maintenance window target {b['WindowTargetId']} does not exist")
    for k, f in (("Targets", "targets"), ("OwnerInformation", "owner_information"), ("Name", "name"), ("Description", "description")):
        if b.get(k) is not None:
            t[f] = b[k]
    return {"WindowId": w["id"], "WindowTargetId": t["id"], "Targets": t["targets"], "OwnerInformation": t["owner_information"], "Name": t["name"], "Description": t["description"]}


def windows_for_target(store, b):
    _need(b, "Targets")
    ids = {v for t in b["Targets"] for v in t.get("Values", [])}
    out = []
    for w in store.windows.values():
        if any(tt["resource_type"] == b.get("ResourceType", tt["resource_type"]) and ids & {v for x in tt["targets"] for v in x.get("Values", [])} for tt in w["targets"].values()):
            out.append({"WindowId": w["id"], "Name": w["name"]})
    return _S()._page(out, b, "WindowIdentities", 50, 50)


def window_schedule(store, b):
    rows = []
    for w in store.windows.values():
        if b.get("WindowId") and w["id"] != b["WindowId"]:
            continue
        if w["enabled"]:
            rows.append({"ScheduledWindowExecutions": [{"WindowId": w["id"], "Name": w["name"], "ExecutionTime": _S()._window_next(w)}]})
    return _S()._page([r for row in rows for r in row["ScheduledWindowExecutions"]], b, "ScheduledWindowExecutions", 50, 50)


def no_execution(what):
    def op(store, b):
        raise _err("DoesNotExistException", f"{what} does not exist: maintenance windows only run when their schedule fires, and none has run in this simulator.")
    return op


# ───────────────────────── associations ─────────────────────────
def _assoc(store, aid):
    a = store.associations.get(aid or "")
    if a is None:
        raise _err("AssociationDoesNotExist", "The specified association does not exist.")
    return a


def _snap(a):
    return {k: v for k, v in a.items()}


def create_assoc_batch(store, b):
    _need(b, "Entries")
    ok, bad = [], []
    for e in b["Entries"]:
        try:
            ok.append(_S()._create_association(store, dict(e))["AssociationDescription"])
        except _S().SsmError as ex:
            bad.append({"Entry": e, "Message": ex.message, "Fault": "Client"})
    for d in ok:
        _g(store)["assoc_versions"].setdefault(d["AssociationId"], []).append(_snap(store.associations[d["AssociationId"]]))
    return {"Successful": ok, "Failed": bad}


def update_association(store, b):
    _need(b, "AssociationId")
    a = _assoc(store, b["AssociationId"])
    vs = _g(store)["assoc_versions"].setdefault(a["id"], [_snap(a)])
    for k, f in (("ScheduleExpression", "schedule"), ("Parameters", "parameters"), ("Targets", "targets"), ("AssociationName", "association_name"), ("DocumentVersion", "document_version")):
        if b.get(k) is not None:
            a[f] = b[k]
    if b.get("Name"):
        _S()._need_doc(store, b["Name"])
        a["name"] = b["Name"]
    vs.append(_snap(a))
    a["version"] = str(len(vs))
    d = _S()._assoc_view(a)
    d["AssociationVersion"] = a["version"]
    return {"AssociationDescription": d}


def list_assoc_versions(store, b):
    _need(b, "AssociationId")
    a = _assoc(store, b["AssociationId"])
    vs = _g(store)["assoc_versions"].get(a["id"]) or [_snap(a)]
    return _S()._page([dict(_S()._assoc_view(v), AssociationVersion=str(i + 1), CreatedDate=v["created"]) for i, v in enumerate(vs)], b, "AssociationVersions", 50, 50)


def update_assoc_status(store, b):
    _need(b, "Name", "InstanceId", "AssociationStatus")
    st = b["AssociationStatus"]
    if st.get("Name") not in ("Pending", "Success", "Failed"):
        raise _err("ValidationException", "AssociationStatus.Name must be Pending, Success or Failed.")
    a = next((x for x in store.associations.values() if x["name"] == b["Name"] and (x.get("instance_id") == b["InstanceId"] or any(b["InstanceId"] in t.get("Values", []) for t in x["targets"]))), None)
    if a is None:
        raise _err("AssociationDoesNotExist", "No association of that document targets the instance.")
    _g(store)["assoc_status"][f"{a['id']}|{b['InstanceId']}"] = dict(st, Date=st.get("Date") or _now())
    d = _S()._assoc_view(a)
    d["Status"] = _g(store)["assoc_status"][f"{a['id']}|{b['InstanceId']}"]
    d["InstanceId"] = b["InstanceId"]
    return {"AssociationDescription": d}


def start_assocs_once(store, b):
    _need(b, "AssociationIds")
    for aid in b["AssociationIds"]:
        a = _assoc(store, aid)
        ex = {"AssociationId": aid, "AssociationVersion": a.get("version", "1"), "ExecutionId": str(uuid.uuid4()), "Status": "Success", "DetailedStatus": "Success",
              "CreatedTime": _now(), "LastExecutionDate": _now(), "ResourceCountByStatus": "{Success=%d}" % max(1, len(a["targets"]))}
        _g(store)["assoc_exec"].setdefault(aid, []).append(ex)
    return {}


def describe_assoc_executions(store, b):
    _need(b, "AssociationId")
    _assoc(store, b["AssociationId"])
    return _S()._page(list(reversed(_g(store)["assoc_exec"].get(b["AssociationId"], []))), b, "AssociationExecutions", 50, 50)


def describe_assoc_exec_targets(store, b):
    _need(b, "AssociationId", "ExecutionId")
    a = _assoc(store, b["AssociationId"])
    if not any(e["ExecutionId"] == b["ExecutionId"] for e in _g(store)["assoc_exec"].get(a["id"], [])):
        raise _err("AssociationExecutionDoesNotExist", "The execution does not exist.")
    ids = [v for t in a["targets"] if t.get("Key") == "InstanceIds" for v in t.get("Values", [])] or ([a["instance_id"]] if a.get("instance_id") else [])
    return _S()._page([{"AssociationId": a["id"], "AssociationVersion": a.get("version", "1"), "ExecutionId": b["ExecutionId"], "ResourceId": i, "ResourceType": "ManagedInstance",
                        "Status": "Success", "DetailedStatus": "Success", "LastExecutionDate": _now()} for i in ids], b, "AssociationExecutionTargets", 50, 50)


def _targets_instance(a, iid):
    return a.get("instance_id") == iid or any(iid in t.get("Values", []) for t in a["targets"] if t.get("Key") == "InstanceIds")


def describe_effective_assocs(store, b):
    _need(b, "InstanceId")
    return _S()._page([{"AssociationId": a["id"], "Name": a["name"], "AssociationVersion": a.get("version", "1")} for a in store.associations.values() if _targets_instance(a, b["InstanceId"])],
                      b, "Associations", 50, 50)


def describe_instance_assoc_status(store, b):
    _need(b, "InstanceId")
    out = []
    for a in store.associations.values():
        if _targets_instance(a, b["InstanceId"]):
            st = _g(store)["assoc_status"].get(f"{a['id']}|{b['InstanceId']}")
            out.append({"AssociationId": a["id"], "Name": a["name"], "DocumentVersion": a["document_version"], "AssociationVersion": a.get("version", "1"), "InstanceId": b["InstanceId"],
                        "ExecutionDate": (st or {}).get("Date", a["created"]), "Status": (st or {}).get("Name", "Pending"), "DetailedStatus": (st or {}).get("Name", "Pending")})
    return _S()._page(out, b, "InstanceAssociationStatusInfos", 50, 50)


# ───────────────────────── documents ─────────────────────────
def describe_doc_permission(store, b):
    _need(b, "Name", "PermissionType")
    _S()._need_doc(store, b["Name"])
    if b["PermissionType"] != "Share":
        raise _err("ValidationException", "PermissionType must be Share.")
    ids = _g(store)["doc_perms"].get(b["Name"], [])
    return {"AccountIds": list(ids), "AccountSharingInfoList": [{"AccountId": i, "SharedDocumentVersion": "$DEFAULT"} for i in ids]}


def modify_doc_permission(store, b):
    _need(b, "Name", "PermissionType")
    doc = _S()._need_doc(store, b["Name"])
    if doc["owner"] == "Amazon":
        raise _err("InvalidPermissionType", "Amazon-owned documents cannot be shared.")
    ids = _g(store)["doc_perms"].setdefault(b["Name"], [])
    for a in b.get("AccountIdsToAdd") or []:
        if a != "all" and not re.fullmatch(r"\d{12}", a):
            raise _err("InvalidPermissionType", f"{a} is not a valid account id.")
        if a not in ids:
            ids.append(a)
    for a in b.get("AccountIdsToRemove") or []:
        if a in ids:
            ids.remove(a)
    return {}


def update_doc_metadata(store, b):
    _need(b, "Name", "DocumentReviews")
    _S()._need_doc(store, b["Name"])
    r = b["DocumentReviews"]
    if r.get("Action") not in ("SendForReview", "UpdateReview", "Approve", "Reject"):
        raise _err("ValidationException", "DocumentReviews.Action is invalid.")
    _g(store)["doc_reviews"].setdefault(b["Name"], []).append({"ReviewerResponse": [{"CreateTime": _now(), "UpdatedTime": _now(), "ReviewStatus": {"SendForReview": "PENDING", "UpdateReview": "PENDING", "Approve": "APPROVED", "Reject": "REJECTED"}[r["Action"]],
                                                                                    "Comment": [{"Type": "Comment", "Content": c.get("Content", "")} for c in r.get("Comment") or []], "Reviewer": "root"}]})
    return {}


def list_doc_metadata_history(store, b):
    _need(b, "Name", "Metadata")
    _S()._need_doc(store, b["Name"])
    h = _g(store)["doc_reviews"].get(b["Name"], [])
    return {"Name": b["Name"], "DocumentVersion": "1", "Author": "root", "Metadata": {"ReviewerResponse": [r for x in h for r in x["ReviewerResponse"]]}}


# ───────────────────────── automation ─────────────────────────
_AUTO_DONE = ("Success", "Failed", "Cancelled", "TimedOut", "CompletedWithSuccess", "CompletedWithFailure")


def _iso_dur(s):
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", str(s or ""))
    if not m:
        raise ValueError(f"'{s}' is not an ISO-8601 duration")
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def _subst(v, params):
    if isinstance(v, str):
        return re.sub(r"\{\{\s*([\w:.-]+)\s*\}\}", lambda m: str(params.get(m.group(1), m.group(0))) if not isinstance(params.get(m.group(1)), list) else ",".join(map(str, params[m.group(1)])), v)
    if isinstance(v, list):
        return [_subst(x, params) for x in v]
    if isinstance(v, dict):
        return {k: _subst(x, params) for k, x in v.items()}
    return v


def _run_steps(store, ex, steps, start=0):
    ssm = _S()
    for i in range(start, len(steps)):
        st = steps[i]
        rec = ex["StepExecutions"][i]
        rec["StepStatus"], rec["ExecutionStartTime"] = "InProgress", _now()
        action = st.get("action", "")
        inputs = _subst(st.get("inputs") or {}, ex["_params"])
        try:
            if action == "aws:sleep":
                rec["Outputs"] = {"Duration": [str(_iso_dur(inputs.get("Duration")))]}
            elif action == "aws:pause":
                rec["StepStatus"] = "Pending"
                ex["AutomationExecutionStatus"], ex["CurrentStepName"], ex["_resume"] = "Waiting", st["name"], i + 1
                return
            elif action == "aws:runCommand":
                payload = {"DocumentName": inputs.get("DocumentName"), "Parameters": inputs.get("Parameters") or {}}
                for k in ("InstanceIds", "Targets", "Comment"):
                    if inputs.get(k):
                        payload[k] = inputs[k]
                cmd = ssm._send_command(store, payload)["Command"]
                rec["Outputs"] = {"CommandId": [cmd["CommandId"]], "Status": [cmd["Status"]]}
            else:
                raise RuntimeError(f"Automation action {action} is not executable in the simulator (supported: aws:sleep, aws:pause, aws:runCommand).")
            rec["StepStatus"] = "Success"
        except Exception as e:  # noqa: BLE001
            msg = getattr(e, "message", None) or str(e)
            rec["StepStatus"], rec["FailureMessage"] = "Failed", msg
            rec["ExecutionEndTime"] = _now()
            if st.get("onFailure") == "Continue":
                continue
            ex["AutomationExecutionStatus"], ex["FailureMessage"] = "Failed", f"Step {st.get('name')} failed: {msg}"
            ex["ExecutionEndTime"] = _now()
            return
        rec["ExecutionEndTime"] = _now()
    ex["AutomationExecutionStatus"], ex["ExecutionEndTime"] = "Success", _now()
    ex.pop("CurrentStepName", None)


def start_automation(store, b):
    _need(b, "DocumentName")
    ssm = _S()
    doc = ssm._need_doc(store, b["DocumentName"])
    if doc["type"] != "Automation":
        raise _err("InvalidDocumentType", f"{b['DocumentName']} is a {doc['type']} document, not an Automation runbook.")
    ver = ssm._pick_version(doc, b.get("DocumentVersion"))
    content = ver.get("parsed") or json.loads(ver["content"])
    steps = content.get("mainSteps") or []
    params = {}
    for name, spec in (content.get("parameters") or {}).items():
        v = (b.get("Parameters") or {}).get(name)
        if v is None and "default" in spec:
            v = spec["default"]
        if v is None:
            raise _err("InvalidAutomationExecutionParametersException", f"Parameter {name} is required.")
        params[name] = v
    unknown = set(b.get("Parameters") or {}) - set(content.get("parameters") or {})
    if unknown:
        raise _err("InvalidAutomationExecutionParametersException", f"Unknown parameter(s): {sorted(unknown)}.")
    eid = str(uuid.uuid4())
    ex = {"AutomationExecutionId": eid, "DocumentName": b["DocumentName"], "DocumentVersion": str(ver["version"]), "ExecutionStartTime": _now(),
          "AutomationExecutionStatus": "InProgress", "Mode": b.get("Mode", "Auto"), "Parameters": {k: ([v] if not isinstance(v, list) else v) for k, v in (b.get("Parameters") or {}).items()},
          "ExecutedBy": f"arn:aws:iam::{ssm.ACCOUNT}:root", "AutomationSubtype": "", "_params": params,
          "StepExecutions": [{"StepName": s.get("name", f"step{i}"), "Action": s.get("action", ""), "StepStatus": "Pending", "MaxAttempts": 1, "OnFailure": s.get("onFailure", "Abort"),
                              "IsCritical": s.get("isCritical", True)} for i, s in enumerate(steps)]}
    _g(store)["automations"][eid] = ex
    if not steps:
        ex["AutomationExecutionStatus"], ex["ExecutionEndTime"] = "Failed", _now()
        ex["FailureMessage"] = f"{b['DocumentName']} has no executable steps in the simulator (Amazon-owned runbooks ship without a step engine)."
    else:
        ex["_steps"] = steps
        _run_steps(store, ex, steps)
    return {"AutomationExecutionId": eid}


def _aview(ex):
    out = {k: v for k, v in ex.items() if not k.startswith("_")}
    out["StepExecutionsTruncated"] = False
    return out


def _auto(store, eid):
    ex = _g(store)["automations"].get(eid or "")
    if ex is None:
        raise _err("AutomationExecutionNotFoundException", f"Automation execution {eid} not found.")
    return ex


def get_automation(store, b):
    _need(b, "AutomationExecutionId")
    return {"AutomationExecution": _aview(_auto(store, b["AutomationExecutionId"]))}


def describe_automations(store, b):
    rows = list(_g(store)["automations"].values())
    for f in b.get("Filters") or []:
        vals = f.get("Values") or []
        if f.get("Key") == "DocumentNamePrefix":
            rows = [r for r in rows if any(r["DocumentName"].startswith(v) for v in vals)]
        elif f.get("Key") == "ExecutionStatus":
            rows = [r for r in rows if r["AutomationExecutionStatus"] in vals]
    meta = [{k: v for k, v in _aview(r).items() if k in ("AutomationExecutionId", "DocumentName", "DocumentVersion", "AutomationExecutionStatus", "ExecutionStartTime", "ExecutionEndTime", "ExecutedBy", "FailureMessage", "Mode", "LogFile")} for r in rows]
    return _S()._page(meta, b, "AutomationExecutionMetadataList", 50, 50)


def describe_auto_steps(store, b):
    _need(b, "AutomationExecutionId")
    ex = _auto(store, b["AutomationExecutionId"])
    rows = ex["StepExecutions"]
    for f in b.get("Filters") or []:
        if f.get("Key") == "StepExecutionStatus":
            rows = [r for r in rows if r["StepStatus"] in (f.get("Values") or [])]
    return _S()._page(rows, b, "StepExecutions", 50, 50)


def stop_automation(store, b):
    _need(b, "AutomationExecutionId")
    ex = _auto(store, b["AutomationExecutionId"])
    if ex["AutomationExecutionStatus"] in _AUTO_DONE:
        raise _err("InvalidAutomationStatusUpdateException", f"The execution is already {ex['AutomationExecutionStatus']}.")
    ex["AutomationExecutionStatus"] = "Cancelled" if b.get("Type", "Cancel") == "Cancel" else "Success"
    ex["ExecutionEndTime"] = _now()
    return {}


def send_signal(store, b):
    _need(b, "AutomationExecutionId", "SignalType")
    ex = _auto(store, b["AutomationExecutionId"])
    if b["SignalType"] not in ("Approve", "Reject", "StartStep", "StopStep", "Resume"):
        raise _err("ValidationException", "SignalType is invalid.")
    if ex["AutomationExecutionStatus"] != "Waiting":
        raise _err("InvalidAutomationSignalException", "The execution is not waiting for a signal.")
    i = ex.pop("_resume", 0)
    pause = ex["StepExecutions"][i - 1]
    if b["SignalType"] in ("Reject", "StopStep"):
        pause["StepStatus"], ex["AutomationExecutionStatus"], ex["ExecutionEndTime"] = "Cancelled", "Cancelled", _now()
        return {}
    pause["StepStatus"], pause["ExecutionEndTime"] = "Success", _now()
    ex["AutomationExecutionStatus"] = "InProgress"
    _run_steps(store, ex, ex["_steps"], i)
    return {}


OPS = {
    "GetServiceSetting": get_service_setting, "UpdateServiceSetting": update_service_setting, "ResetServiceSetting": reset_service_setting,
    "PutInventory": put_inventory, "GetInventory": get_inventory, "ListInventoryEntries": list_inventory_entries, "GetInventorySchema": get_inventory_schema,
    "DeleteInventory": delete_inventory, "DescribeInventoryDeletions": describe_inventory_deletions,
    "CreateOpsItem": create_opsitem, "GetOpsItem": get_opsitem, "UpdateOpsItem": update_opsitem, "DeleteOpsItem": delete_opsitem, "DescribeOpsItems": describe_opsitems,
    "ListOpsItemEvents": list_opsitem_events, "AssociateOpsItemRelatedItem": associate_related, "DisassociateOpsItemRelatedItem": disassociate_related,
    "ListOpsItemRelatedItems": list_related, "CreateOpsMetadata": create_opsmetadata, "GetOpsMetadata": get_opsmetadata, "UpdateOpsMetadata": update_opsmetadata,
    "DeleteOpsMetadata": delete_opsmetadata, "ListOpsMetadata": list_opsmetadata,
    "CreateActivation": create_activation, "DescribeActivations": describe_activations, "DeleteActivation": delete_activation,
    "DescribeInstanceProperties": describe_instance_properties, "GetConnectionStatus": get_connection_status,
    "CreateResourceDataSync": create_sync, "ListResourceDataSync": list_syncs, "UpdateResourceDataSync": update_sync, "DeleteResourceDataSync": delete_sync,
    "PutResourcePolicy": put_resource_policy, "GetResourcePolicies": get_resource_policies, "DeleteResourcePolicy": delete_resource_policy,
    "PutComplianceItems": put_compliance_items, "ListComplianceItems": list_compliance_items, "ListComplianceSummaries": list_compliance_summaries,
    "ListResourceComplianceSummaries": list_resource_compliance_summaries,
    "RegisterPatchBaselineForPatchGroup": register_patch_group, "DeregisterPatchBaselineForPatchGroup": deregister_patch_group,
    "GetPatchBaselineForPatchGroup": get_baseline_for_group, "DescribePatchGroups": describe_patch_groups,
    "RegisterDefaultPatchBaseline": register_default_baseline, "GetDefaultPatchBaseline": get_default_baseline, "UpdatePatchBaseline": update_baseline,
    "DescribePatchGroupState": describe_patch_group_state, "DescribePatchProperties": describe_patch_properties,
    "DescribeAvailablePatches": empty("Patches"), "DescribeInstancePatchStates": empty("InstancePatchStates"),
    "DescribeInstancePatchStatesForPatchGroup": empty("InstancePatchStates"), "DescribeInstancePatches": empty("Patches"),
    "DescribeEffectivePatchesForPatchBaseline": empty("EffectivePatches"),
    "RegisterTaskWithMaintenanceWindow": register_task, "DescribeMaintenanceWindowTasks": describe_wtasks, "GetMaintenanceWindowTask": get_wtask,
    "UpdateMaintenanceWindowTask": update_wtask, "DeregisterTaskFromMaintenanceWindow": deregister_wtask, "UpdateMaintenanceWindowTarget": update_wtarget,
    "DescribeMaintenanceWindowsForTarget": windows_for_target, "DescribeMaintenanceWindowSchedule": window_schedule,
    "DescribeMaintenanceWindowExecutions": empty("WindowExecutions"), "DescribeMaintenanceWindowExecutionTasks": no_execution("The maintenance window execution"),
    "DescribeMaintenanceWindowExecutionTaskInvocations": no_execution("The maintenance window execution"),
    "GetMaintenanceWindowExecution": no_execution("The maintenance window execution"), "GetMaintenanceWindowExecutionTask": no_execution("The maintenance window execution"),
    "GetMaintenanceWindowExecutionTaskInvocation": no_execution("The maintenance window execution"), "CancelMaintenanceWindowExecution": no_execution("The maintenance window execution"),
    "CreateAssociationBatch": create_assoc_batch, "UpdateAssociation": update_association, "ListAssociationVersions": list_assoc_versions,
    "UpdateAssociationStatus": update_assoc_status, "StartAssociationsOnce": start_assocs_once, "DescribeAssociationExecutions": describe_assoc_executions,
    "DescribeAssociationExecutionTargets": describe_assoc_exec_targets, "DescribeEffectiveInstanceAssociations": describe_effective_assocs,
    "DescribeInstanceAssociationsStatus": describe_instance_assoc_status,
    "DescribeDocumentPermission": describe_doc_permission, "ModifyDocumentPermission": modify_doc_permission, "UpdateDocumentMetadata": update_doc_metadata,
    "ListDocumentMetadataHistory": list_doc_metadata_history,
    "StartAutomationExecution": start_automation, "GetAutomationExecution": get_automation, "DescribeAutomationExecutions": describe_automations,
    "DescribeAutomationStepExecutions": describe_auto_steps, "StopAutomationExecution": stop_automation, "SendAutomationSignal": send_signal,
}
