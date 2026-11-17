# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Budgets (JSON 1.1, X-Amz-Target AWSBudgetServiceGateway.*, signing name `budgetservice`) and
AWS Resource Groups (rest-json, signing name `resource-groups`) control planes — substrate-independent.

State lives in `store.account["governance"]` of the S3 ObjectStore (persisted with the buckets, carried by Nano's
generic store snapshot). Wire shapes follow the real services: Budgets is json-1.1, so timestamps are epoch NUMBERS;
unset fields are omitted; DescribeBudget returns the default CostTypes the real service fills in.
Endurance F204 (budgets) / F205 (resource-groups). NO fastapi/boto3.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_DEFAULT_COST_TYPES = {"IncludeCredit": True, "IncludeDiscount": True, "IncludeOtherSubscription": True,
                       "IncludeRecurring": True, "IncludeRefund": True, "IncludeSubscription": True,
                       "IncludeSupport": True, "IncludeTax": True, "IncludeUpfront": True,
                       "UseAmortized": False, "UseBlended": False}


def _st(store) -> dict:
    return store.account.setdefault("governance", {"budgets": {}, "groups": {}, "tags": {}})


def _json(status, doc, ct="application/x-amz-json-1.1"):
    body = b"" if doc is None else json.dumps(doc).encode()
    return {"status": status, "headers": {"content-type": ct, "x-amzn-requestid": "vyomi-gov"}, "body": body}


def _err(status, code, msg, ct="application/x-amz-json-1.1"):
    return {"status": status, "headers": {"content-type": ct, "x-amzn-errortype": code, "x-amzn-requestid": "vyomi-gov"},
            "body": json.dumps({"__type": code, "message": msg, "Message": msg}).encode()}


# ── Budgets ────────────────────────────────────────────────────────────────────────────
def _month_start() -> int:
    t = time.gmtime()
    return int(time.mktime(time.struct_time((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, 0))) - time.timezone)


def _budget_out(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_") and v is not None}


def _norm_budget(b: dict, old: dict | None = None) -> dict:
    out = dict(b)
    if out.get("BudgetType", "COST") == "COST" or out.get("CostTypes"):
        out["CostTypes"] = {**_DEFAULT_COST_TYPES, **(out.get("CostTypes") or {})}
    tp = dict(out.get("TimePeriod") or {})
    tp.setdefault("Start", _month_start())
    tp.setdefault("End", 3706473600)   # 2087-06-15, the real service default
    out["TimePeriod"] = tp
    out["CalculatedSpend"] = {"ActualSpend": {"Amount": "0.0", "Unit": (out.get("BudgetLimit") or {}).get("Unit", "USD")}}
    out["LastUpdatedTime"] = int(time.time())
    out.setdefault("BudgetType", "COST")
    return out


def budgets_dispatch(store, target: str, payload: dict):
    s = _st(store)["budgets"]
    op = target.rsplit(".", 1)[-1]
    acct = payload.get("AccountId") or _ACCOUNT
    name = payload.get("BudgetName") or (payload.get("Budget") or {}).get("BudgetName")
    if op == "CreateBudget":
        b = payload.get("Budget") or {}
        name = b.get("BudgetName")
        if not name:
            return _err(400, "InvalidParameterException", "BudgetName is required")
        if name in s:
            return _err(400, "DuplicateRecordException", f"Error creating budget: {name} - the budget already exists.")
        notifs = []
        for nws in payload.get("NotificationsWithSubscribers") or []:
            notifs.append({"Notification": nws.get("Notification") or {}, "Subscribers": nws.get("Subscribers") or []})
        s[name] = {"Budget": _norm_budget(b), "Notifications": notifs}
        tags = payload.get("ResourceTags") or []
        if tags:
            _st(store)["tags"][_budget_arn(name)] = {t["Key"]: t["Value"] for t in tags}
        store.persist()
        return _json(200, {})
    if op == "DescribeBudgets":
        return _json(200, {"Budgets": [_norm_budget(r["Budget"]) for r in s.values()]})
    if name not in s:
        return _err(400, "NotFoundException", f"Budget {name} not found." if name else "BudgetName is required")
    rec = s[name]
    if op == "DescribeBudget":
        return _json(200, {"Budget": _budget_out(_norm_budget(rec["Budget"]))})
    if op == "UpdateBudget":
        nb = payload.get("NewBudget") or {}
        rec["Budget"] = _norm_budget(nb)
        store.persist()
        return _json(200, {})
    if op == "DeleteBudget":
        del s[name]
        _st(store)["tags"].pop(_budget_arn(name), None)
        store.persist()
        return _json(200, {})
    nkey = lambda n: (n.get("NotificationType"), n.get("ComparisonOperator"), n.get("Threshold"), n.get("ThresholdType"))
    if op == "DescribeNotificationsForBudget":
        return _json(200, {"Notifications": [{**x["Notification"], "NotificationState": "OK"} for x in rec["Notifications"]]})
    if op == "CreateNotification":
        n = payload.get("Notification") or {}
        if any(nkey(x["Notification"]) == nkey(n) for x in rec["Notifications"]):
            return _err(400, "DuplicateRecordException", "The notification already exists.")
        rec["Notifications"].append({"Notification": n, "Subscribers": payload.get("Subscribers") or []})
        store.persist()
        return _json(200, {})
    n = payload.get("Notification") or payload.get("OldNotification") or {}
    ent = next((x for x in rec["Notifications"] if nkey(x["Notification"]) == nkey(n)), None)
    if op in ("DeleteNotification", "UpdateNotification", "DescribeSubscribersForNotification",
              "CreateSubscriber", "DeleteSubscriber", "UpdateSubscriber"):
        if ent is None:
            return _err(400, "NotFoundException", "Notification not found.")
        if op == "DeleteNotification":
            rec["Notifications"].remove(ent)
        elif op == "UpdateNotification":
            ent["Notification"] = payload.get("NewNotification") or ent["Notification"]
        elif op == "DescribeSubscribersForNotification":
            return _json(200, {"Subscribers": ent["Subscribers"]})
        elif op == "CreateSubscriber":
            ent["Subscribers"].append(payload.get("Subscriber") or {})
        elif op == "DeleteSubscriber":
            sub = payload.get("Subscriber") or {}
            ent["Subscribers"] = [x for x in ent["Subscribers"] if x != sub]
        elif op == "UpdateSubscriber":
            old, new = payload.get("OldSubscriber") or {}, payload.get("NewSubscriber") or {}
            ent["Subscribers"] = [new if x == old else x for x in ent["Subscribers"]]
        store.persist()
        return _json(200, {})
    if op == "DescribeBudgetActionsForBudget":
        return _json(200, {"Actions": []})
    return _err(400, "InvalidParameterException", f"Unsupported Budgets operation {op}")


def _budget_arn(name):
    return f"arn:aws:budgets::{_ACCOUNT}:budget/{name}"


def budgets_tags(store, target: str, payload: dict):
    op = target.rsplit(".", 1)[-1]
    arn = payload.get("ResourceARN", "")
    t = _st(store)["tags"].setdefault(arn, {})
    if op == "TagResource":
        for x in payload.get("ResourceTags") or []:
            t[x["Key"]] = x["Value"]
        store.persist()
        return _json(200, {})
    if op == "UntagResource":
        for k in payload.get("ResourceTagKeys") or []:
            t.pop(k, None)
        store.persist()
        return _json(200, {})
    return _json(200, {"ResourceTags": [{"Key": k, "Value": v} for k, v in t.items()]})


def budgets_handle(store, target: str, body: bytes):
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return _err(400, "SerializationException", "invalid JSON")
    if target.rsplit(".", 1)[-1] in ("TagResource", "UntagResource", "ListTagsForResource"):
        return budgets_tags(store, target, payload)
    return budgets_dispatch(store, target, payload)


# ── Resource Groups ────────────────────────────────────────────────────────────────────
def _group_arn(name):
    return f"arn:aws:resource-groups:{_REGION}:{_ACCOUNT}:group/{name}"


def _rg_name(v):
    return str(v or "").rsplit("/", 1)[-1]


def rg_handle(store, method: str, raw_path: str, body: bytes):
    ct = "application/json"
    g = _st(store)["groups"]
    path = urllib.parse.unquote(raw_path.split("?", 1)[0]).strip("/")
    try:
        p = json.loads(body) if body else {}
    except ValueError:
        return _err(400, "BadRequestException", "invalid JSON", ct)
    if path == "groups" and method == "POST":
        name = p.get("Name")
        if not name or not re.match(r"^[a-zA-Z0-9_\.-]{1,300}$", name):
            return _err(400, "BadRequestException", "Invalid group name", ct)
        if name in g:
            return _err(400, "BadRequestException", f"Group {name} already exists.", ct)
        rec = {"GroupArn": _group_arn(name), "Name": name}
        if p.get("Description") is not None:
            rec["Description"] = p["Description"]
        g[name] = {"Group": rec, "ResourceQuery": p.get("ResourceQuery"), "Configuration": p.get("Configuration")}
        if p.get("Tags"):
            _st(store)["tags"][rec["GroupArn"]] = dict(p["Tags"])
        store.persist()
        out = {"Group": rec}
        if p.get("ResourceQuery"):
            out["ResourceQuery"] = p["ResourceQuery"]
        if p.get("Tags"):
            out["Tags"] = dict(p["Tags"])
        return _json(200, out, ct)
    if path == "groups-list":
        ids = [{"GroupName": n, "GroupArn": r["Group"]["GroupArn"]} for n, r in g.items()]
        return _json(200, {"GroupIdentifiers": ids, "Groups": [{"GroupName": n, "GroupArn": r["Group"]["GroupArn"]} for n, r in g.items()]}, ct)
    m = re.match(r"^resources/(.+)/tags$", path)
    if m:
        arn = m.group(1)
        t = _st(store)["tags"].setdefault(arn, {})
        if method == "GET":
            return _json(200, {"Arn": arn, "Tags": dict(t)}, ct)
        if method == "PUT":
            t.update(p.get("Tags") or {})
            store.persist()
            return _json(200, {"Arn": arn, "Tags": p.get("Tags") or {}}, ct)
        if method == "PATCH":
            for k in p.get("Keys") or []:
                t.pop(k, None)
            store.persist()
            return _json(200, {"Arn": arn, "Keys": p.get("Keys") or []}, ct)
    gname = _rg_name(p.get("Group") or p.get("GroupName"))
    mg = re.match(r"^groups/([^/]+)(?:/(.*))?$", path)
    if mg and not gname:
        gname = _rg_name(mg.group(1))
    sub = path if not mg else (mg.group(2) or "")
    if path in ("get-group", "delete-group", "update-group", "get-group-query", "update-group-query",
                "get-group-configuration", "put-group-configuration", "list-group-resources") or mg:
        if gname not in g:
            return _err(404, "NotFoundException", f"Group {gname} not found.", ct)
        r = g[gname]
        if path == "get-group" or (mg and not sub and method == "GET"):
            return _json(200, {"Group": r["Group"]}, ct)
        if path == "delete-group" or (mg and not sub and method == "DELETE"):
            _st(store)["tags"].pop(r["Group"]["GroupArn"], None)
            del g[gname]
            store.persist()
            return _json(200, {"Group": r["Group"]}, ct)
        if path == "update-group":
            if "Description" in p:
                r["Group"]["Description"] = p["Description"]
            store.persist()
            return _json(200, {"Group": r["Group"]}, ct)
        if path == "get-group-query":
            if not r["ResourceQuery"]:
                return _err(404, "NotFoundException", "Group has no query.", ct)
            return _json(200, {"GroupQuery": {"GroupName": gname, "ResourceQuery": r["ResourceQuery"]}}, ct)
        if path == "update-group-query":
            r["ResourceQuery"] = p.get("ResourceQuery")
            store.persist()
            return _json(200, {"GroupQuery": {"GroupName": gname, "ResourceQuery": r["ResourceQuery"]}}, ct)
        if path == "get-group-configuration":
            return _json(200, {"GroupConfiguration": {"Configuration": r.get("Configuration") or [], "Status": "UPDATE_COMPLETE"}}, ct)
        if path == "list-group-resources":
            return _json(200, {"ResourceIdentifiers": [], "Resources": []}, ct)
    return _err(404, "NotFoundException", f"Unknown Resource Groups operation {method} /{path}", ct)
