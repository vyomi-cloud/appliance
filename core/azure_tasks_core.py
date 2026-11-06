"""Azure "Tasks" blades (AKS, API Management, App Configuration, App Service, Cognitive Services) as a small HONEST task
engine (substrate-free, pure Python; Pyodide-loadable).

In Azure, a *task* is a Logic App created from a template: a Recurrence trigger plus actions that call the Azure Resource
Manager with a managed identity. Here the same shape is real:

* ``Microsoft.Logic/workflows`` records (properties.definition = a real Logic Apps definition with a ``Recurrence`` trigger
  and ``Http`` actions against ``https://management.azure.com/...``) live in ARM state; GET/PUT/PATCH/DELETE, ``enable``,
  ``disable``, ``triggers/{t}/run`` and ``runs`` follow the Logic Apps REST shapes.
* ``POST .../providers/Microsoft.Logic/vyomiCreateTask`` builds the workflow from a TEMPLATE (``GET .../providers/Microsoft.Logic/
  vyomiTaskTemplates?resourceType=...`` lists them per resource type) after validating the target resource, the recurrence
  and the template parameters.
* A run executes every action IN ORDER (``runAfter`` respected) by calling the simulator's own ARM
  (``arm.handle``) -- stopping an AKS cluster really changes its powerState, restarting a web app really records the restart,
  rotating a key really changes the key. Each run is a ``workflows/runs`` record with per-action request/response summaries;
  a failing action fails the run and skips its dependents. ``tick`` is called by core/schedule_core.py (provider "azure-tasks").

Honest limits: only ``Recurrence`` triggers and ``Http`` (ARM) / ``Compose`` actions run -- any other action type fails the run with
``ActionNotSupported``; the managed identity is not authorised (ARM calls run as the simulator, RBAC is not evaluated); workflow
expressions (``@{...}``) are not evaluated; no e-mail/Teams connectors, so "report" tasks store their result in the run output.
Schedules coalesce missed fires (schedule_core) and Nano only ticks while the tab is open.
"""
from __future__ import annotations

import datetime
import re
import uuid

try:
    from core import schedule_core as sched
except ImportError:                                  # Pyodide flat layout
    import schedule_core as sched                    # type: ignore

WF_T = "Microsoft.Logic/workflows"
RUN_T = "Microsoft.Logic/workflows/runs"
ARM_HOST = "https://management.azure.com"
AKS, APIM, APPCFG, SITES, COG = ("microsoft.containerservice/managedclusters", "microsoft.apimanagement/service",
                                 "microsoft.appconfiguration/configurationstores", "microsoft.web/sites",
                                 "microsoft.cognitiveservices/accounts")
VM, STORAGE, COSMOS, KV, SB, SQL, SQLDB, CAPP = (
    "microsoft.compute/virtualmachines", "microsoft.storage/storageaccounts", "microsoft.documentdb/databaseaccounts",
    "microsoft.keyvault/vaults", "microsoft.servicebus/namespaces", "microsoft.sql/servers", "microsoft.sql/servers/databases",
    "microsoft.app/containerapps")
_FREQ = {"minute": "minutes", "hour": "hours", "day": "days", "week": "days"}

_REC = {"frequency": "Day", "interval": 1}
TEMPLATES = [
    {"id": "aks-stop-cluster", "title": "Stop the AKS cluster on a schedule", "resourceTypes": [AKS], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [20], "minutes": [0]}},
     "description": "Calls the cluster's stop action so node pools are deallocated outside working hours.", "params": [],
     "actions": lambda rid, p: [("Stop_cluster", "POST", f"{rid}/stop", "2024-02-01", None)]},
    {"id": "aks-start-cluster", "title": "Start the AKS cluster on a schedule", "resourceTypes": [AKS], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [7], "minutes": [0]}},
     "description": "Calls the cluster's start action at the beginning of the working day.", "params": [],
     "actions": lambda rid, p: [("Start_cluster", "POST", f"{rid}/start", "2024-02-01", None)]},
    {"id": "apim-gateway-usage-report", "title": "Capture a gateway usage report", "resourceTypes": [APIM], "recurrence": {"frequency": "Hour", "interval": 1},
     "description": "Reads the service's gateway request analytics and capacity and keeps them in the run output (no e-mail connector).", "params": [],
     "actions": lambda rid, p: [("Get_gateway_usage", "GET", f"{rid}/vyomiAnalytics", "2023-05-01-preview", None)]},
    {"id": "appconfig-rotate-key", "title": "Rotate an access key on a schedule", "resourceTypes": [APPCFG], "recurrence": {"frequency": "Week", "interval": 1},
     "description": "Regenerates one access key of the store.", "params": [{"name": "keyId", "label": "Access key id", "required": True}],
     "actions": lambda rid, p: [("Regenerate_key", "POST", f"{rid}/regenerateKey", "2023-03-01", {"id": p["keyId"]})]},
    {"id": "appconfig-keys-report", "title": "Capture the store's access keys inventory", "resourceTypes": [APPCFG], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Lists the access keys (ids and flags) into the run output.", "params": [],
     "actions": lambda rid, p: [("List_keys", "POST", f"{rid}/listKeys", "2023-03-01", None)]},
    {"id": "webapp-restart", "title": "Restart the web app on a schedule", "resourceTypes": [SITES], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [3], "minutes": [0]}},
     "description": "Calls the site's restart action.", "params": [],
     "actions": lambda rid, p: [("Restart_site", "POST", f"{rid}/restart", "2023-01-01", None)]},
    {"id": "webapp-stop", "title": "Stop the web app on a schedule", "resourceTypes": [SITES], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [20], "minutes": [0]}},
     "description": "Stops the site outside working hours.", "params": [],
     "actions": lambda rid, p: [("Stop_site", "POST", f"{rid}/stop", "2023-01-01", None)]},
    {"id": "webapp-start", "title": "Start the web app on a schedule", "resourceTypes": [SITES], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [7], "minutes": [0]}},
     "description": "Starts the site at the beginning of the working day.", "params": [],
     "actions": lambda rid, p: [("Start_site", "POST", f"{rid}/start", "2023-01-01", None)]},
    {"id": "cogsvc-rotate-key", "title": "Rotate a Cognitive Services key on a schedule", "resourceTypes": [COG], "recurrence": {"frequency": "Week", "interval": 1},
     "description": "Regenerates Key1 or Key2 of the account.", "params": [{"name": "keyName", "label": "Key to regenerate", "default": "Key1", "enum": ["Key1", "Key2"]}],
     "actions": lambda rid, p: [("Regenerate_key", "POST", f"{rid}/regenerateKey", "2023-05-01", {"keyName": p.get("keyName", "Key1")})]},
    {"id": "cogsvc-usage-report", "title": "Capture the account's usage", "resourceTypes": [COG], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Reads the account's quota usages into the run output.", "params": [],
     "actions": lambda rid, p: [("Get_usages", "GET", f"{rid}/usages", "2023-05-01", None)]},
    {"id": "vm-deallocate", "title": "Stop (deallocate) the virtual machine on a schedule", "resourceTypes": [VM], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [20], "minutes": [0]}},
     "description": "Deallocates the VM outside working hours so compute is not billed.", "params": [],
     "actions": lambda rid, p: [("Deallocate_VM", "POST", f"{rid}/deallocate", "2024-03-01", None)]},
    {"id": "vm-start", "title": "Start the virtual machine on a schedule", "resourceTypes": [VM], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [7], "minutes": [0]}},
     "description": "Starts the VM at the beginning of the working day.", "params": [],
     "actions": lambda rid, p: [("Start_VM", "POST", f"{rid}/start", "2024-03-01", None)]},
    {"id": "vm-restart", "title": "Restart the virtual machine on a schedule", "resourceTypes": [VM], "recurrence": {"frequency": "Week", "interval": 1},
     "description": "Restarts the VM.", "params": [],
     "actions": lambda rid, p: [("Restart_VM", "POST", f"{rid}/restart", "2024-03-01", None)]},
    {"id": "containerapp-stop", "title": "Stop the container app on a schedule", "resourceTypes": [CAPP], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [20], "minutes": [0]}},
     "description": "Stops the app outside working hours.", "params": [],
     "actions": lambda rid, p: [("Stop_app", "POST", f"{rid}/stop", "2024-03-01", None)]},
    {"id": "containerapp-start", "title": "Start the container app on a schedule", "resourceTypes": [CAPP], "recurrence": {"frequency": "Day", "interval": 1, "schedule": {"hours": [7], "minutes": [0]}},
     "description": "Starts the app at the beginning of the working day.", "params": [],
     "actions": lambda rid, p: [("Start_app", "POST", f"{rid}/start", "2024-03-01", None)]},
    {"id": "storage-rotate-key", "title": "Rotate a storage account key on a schedule", "resourceTypes": [STORAGE], "recurrence": {"frequency": "Week", "interval": 1},
     "description": "Regenerates key1 or key2 of the account.", "params": [{"name": "keyName", "label": "Key to regenerate", "default": "key1", "enum": ["key1", "key2"]}],
     "actions": lambda rid, p: [("Regenerate_key", "POST", f"{rid}/regenerateKey", "2023-01-01", {"keyName": p.get("keyName", "key1")})]},
    {"id": "storage-keys-report", "title": "Capture the account's key inventory", "resourceTypes": [STORAGE], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Lists the account keys into the run output.", "params": [],
     "actions": lambda rid, p: [("List_keys", "POST", f"{rid}/listKeys", "2023-01-01", None)]},
    {"id": "cosmos-rotate-key", "title": "Rotate a Cosmos DB account key on a schedule", "resourceTypes": [COSMOS], "recurrence": {"frequency": "Week", "interval": 1},
     "description": "Regenerates one key of the account.", "params": [{"name": "keyKind", "label": "Key to regenerate", "default": "secondary", "enum": ["primary", "secondary", "primaryReadonly", "secondaryReadonly"]}],
     "actions": lambda rid, p: [("Regenerate_key", "POST", f"{rid}/regenerateKey", "2023-11-15", {"keyKind": p.get("keyKind", "secondary")})]},
    {"id": "cosmos-account-report", "title": "Capture the account's configuration", "resourceTypes": [COSMOS], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Reads the account (regions, consistency, network rules) into the run output.", "params": [],
     "actions": lambda rid, p: [("Get_account", "GET", rid, "2023-11-15", None)]},
    {"id": "keyvault-config-report", "title": "Capture the vault's configuration", "resourceTypes": [KV], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Reads the vault (access model, soft delete, network rules) into the run output.", "params": [],
     "actions": lambda rid, p: [("Get_vault", "GET", rid, "2023-07-01", None)]},
    {"id": "servicebus-queues-report", "title": "Capture the namespace's queues", "resourceTypes": [SB], "recurrence": {"frequency": "Hour", "interval": 1},
     "description": "Lists the queues (message counts, dead-letter counts) into the run output.", "params": [],
     "actions": lambda rid, p: [("List_queues", "GET", f"{rid}/queues", "2022-10-01-preview", None)]},
    {"id": "sql-databases-report", "title": "Capture the server's databases", "resourceTypes": [SQL], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Lists the databases (SKU, status, size) into the run output.", "params": [],
     "actions": lambda rid, p: [("List_databases", "GET", f"{rid}/databases", "2023-05-01-preview", None)]},
    {"id": "sqldb-report", "title": "Capture the database's configuration", "resourceTypes": [SQLDB], "recurrence": {"frequency": "Day", "interval": 1},
     "description": "Reads the database into the run output.", "params": [],
     "actions": lambda rid, p: [("Get_database", "GET", rid, "2023-05-01-preview", None)]},
]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body, "scope": "", "type": "", "name": ""}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}, "scope": "", "type": "", "name": ""}


def _view(rec):
    return {k: v for k, v in rec.items() if not str(k).startswith("_")}


def _wf_id(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Logic/workflows/{name}"


def list_templates(resource_type=None):
    rt = (resource_type or "").lower()
    return [{k: v for k, v in t.items() if k != "actions"} for t in TEMPLATES if not rt or rt in t["resourceTypes"]]


def spec_of(recurrence):
    """Logic Apps recurrence -> schedule_core spec (None when it cannot be scheduled)."""
    if not isinstance(recurrence, dict):
        return None
    f = str(recurrence.get("frequency", "")).lower()
    try:
        n = int(recurrence.get("interval", 1))
    except (TypeError, ValueError):
        return None
    if f not in _FREQ or n < 1:
        return None
    sc = recurrence.get("schedule") or {}
    if f == "day" and sc.get("hours"):
        h, m = int(sc["hours"][0]), int((sc.get("minutes") or [0])[0])
        if n == 1 and 0 <= h <= 23 and 0 <= m <= 59:
            return f"daily@{h:02d}:{m:02d}"
        return None
    if f == "week":
        n *= 7
    unit = _FREQ[f]
    spec = f"rate({n} {unit[:-1] if n == 1 else unit})"
    return spec if sched.valid(spec) else None


def _definition(tpl, rid, params, recurrence):
    actions, prev = {}, None
    for name, method, path, ver, body in tpl["actions"](rid, params):
        a = {"type": "Http", "inputs": {"method": method, "uri": f"{ARM_HOST}{path}?api-version={ver}",
                                         "authentication": {"type": "ManagedServiceIdentity"}}, "runAfter": {prev: ["Succeeded"]} if prev else {}}
        if body is not None:
            a["inputs"]["body"] = body
        actions[name] = a
        prev = name
    return {"$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
            "contentVersion": "1.0.0.0", "triggers": {"Recurrence": {"type": "Recurrence", "recurrence": recurrence}}, "actions": actions}


def _validate_def(d):
    if not isinstance(d, dict) or not isinstance(d.get("triggers"), dict) or not d["triggers"]:
        return "properties.definition.triggers is required."
    for n, t in d["triggers"].items():
        if str(t.get("type", "")).lower() != "recurrence":
            return f"Trigger '{n}': only Recurrence triggers are supported by this engine."
        if spec_of(t.get("recurrence")) is None:
            return f"Trigger '{n}': recurrence must have frequency Minute|Hour|Day|Week and a positive interval."
    return None


def _put(state, sub, rg, name, body, existing=None):
    rid = _wf_id(sub, rg, name)
    p = dict(body.get("properties") or {})
    now = _now()
    rec = existing or {"id": rid, "name": name, "type": WF_T, "_type": WF_T, "_sub": sub, "_rg": rg, "_created": now, "_seq": 0}
    rec["location"] = body.get("location") or rec.get("location") or "eastus"
    rec["tags"] = body.get("tags") if body.get("tags") is not None else rec.get("tags", {})
    rec["properties"] = {"provisioningState": "Succeeded", "createdTime": (rec.get("properties") or {}).get("createdTime", now), "changedTime": now,
                         "state": p.get("state", (rec.get("properties") or {}).get("state", "Enabled")), "version": uuid.uuid4().hex[:20].upper(),
                         "accessEndpoint": f"https://prod-00.{rec['location']}.logic.azure.com:443/workflows/{uuid.uuid5(uuid.NAMESPACE_URL, rid).hex}",
                         "definition": p.get("definition") or (rec.get("properties") or {}).get("definition"), "parameters": p.get("parameters") or {}}
    state[rid.lower()] = rec
    return rec


# ── run ───────────────────────────────────────────────────────────────────────
def run_workflow(arm, wf, trigger="Recurrence", now=None):
    state = arm.state
    d = (wf.get("properties") or {}).get("definition") or {}
    start = _now()
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f") + uuid.uuid4().hex[:4]
    results, status = {}, "Succeeded"
    order = list((d.get("actions") or {}).keys())
    done = set()
    while order:
        progressed = False
        for name in list(order):
            act = d["actions"][name]
            deps = act.get("runAfter") or {}
            if any(x not in done for x in deps):
                continue
            order.remove(name)
            done.add(name)
            progressed = True
            if any(results.get(x, {}).get("status") not in [s for s in (deps[x] or ["Succeeded"])] for x in deps):
                results[name] = {"status": "Skipped", "code": "ActionSkipped"}
                continue
            results[name] = _exec(arm, act)
            if results[name]["status"] != "Succeeded":
                status = "Failed"
        if not progressed:
            for name in order:
                results[name] = {"status": "Skipped", "code": "ActionSkipped"}
            status = "Failed"
            break
    if any(r["status"] == "Skipped" for r in results.values()) and status == "Succeeded":
        status = "Failed"
    rid = f"{wf['id']}/runs/{run_id}"
    rec = {"id": rid, "name": run_id, "type": RUN_T, "_type": RUN_T, "_sub": wf["_sub"], "_rg": wf["_rg"], "_created": start,
           "properties": {"startTime": start, "endTime": _now(), "status": status, "waitEndTime": start,
                          "correlation": {"clientTrackingId": run_id}, "trigger": {"name": trigger, "startTime": start, "endTime": start, "status": "Succeeded"},
                          "workflow": {"id": wf["id"], "name": wf["name"], "type": WF_T}, "vyomiActions": results}}
    if status == "Failed":
        bad = next((r for r in results.values() if r["status"] == "Failed"), {})
        rec["properties"]["error"] = {"code": bad.get("code", "ActionFailed"), "message": bad.get("message", "An action failed.")}
    state[rid.lower()] = rec
    runs = sorted((k for k, v in state.items() if isinstance(v, dict) and v.get("_type") == RUN_T and k.startswith(wf["id"].lower() + "/runs/")))
    for k in runs[:-50]:
        state.pop(k, None)           # keep the 50 newest runs
    return rec


def _exec(arm, act):
    t = str(act.get("type", ""))
    inp = act.get("inputs")
    if t.lower() == "compose":
        return {"status": "Succeeded", "outputs": inp}
    if t.lower() != "http" or not isinstance(inp, dict):
        return {"status": "Failed", "code": "ActionNotSupported", "message": f"Action type '{t}' is not supported by the simulator's workflow engine (Http to ARM and Compose only)."}
    uri = str(inp.get("uri", ""))
    if not uri.startswith(ARM_HOST + "/"):
        return {"status": "Failed", "code": "ActionNotSupported", "message": f"Only {ARM_HOST} URIs can be called (no outbound connectors)."}
    path, _, qs = uri[len(ARM_HOST):].partition("?")
    q = dict(x.split("=", 1) for x in qs.split("&") if "=" in x)
    method = str(inp.get("method", "GET")).upper()
    r = arm.handle(method, path, q, inp.get("body"))
    st = r.get("status", 500)
    body = r.get("body")
    out = {"status": "Succeeded" if st < 300 else "Failed", "request": {"method": method, "uri": uri}, "response": {"statusCode": st, "body": _trim(body)}}
    if st >= 300:
        out["code"] = (body or {}).get("error", {}).get("code", "ActionFailed") if isinstance(body, dict) else "ActionFailed"
        out["message"] = (body or {}).get("error", {}).get("message", f"HTTP {st}") if isinstance(body, dict) else f"HTTP {st}"
    return out


def _trim(b):
    s = repr(b)
    return b if len(s) <= 4000 else {"truncated": s[:4000]}


# ── ARM routes ────────────────────────────────────────────────────────────────
def route(arm, method, sub, rg, after, payload=None, query=None):
    low = [a.lower() for a in after]
    if low[0] != "microsoft.logic" or len(low) < 2:
        return None
    state = arm.state
    payload = payload or {}
    if low[1] == "vyomitasktemplates" and len(low) == 2:
        return _ok({"value": list_templates((query or {}).get("resourceType"))}) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
    if low[1] == "vyomicreatetask" and len(low) == 2:
        return _create(arm, method, sub, rg, payload)
    if low[1] != "workflows":
        return None
    if len(low) == 2:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET only.")
        items = [_view(r) for r in list(state.values()) if isinstance(r, dict) and r.get("_type") == WF_T and r.get("_sub") == sub
                 and (not rg or str(r.get("_rg", "")).lower() == rg.lower())]
        return _ok({"value": items})
    if not rg:
        return _err(400, "InvalidResourceGroup", "A resource group is required.")
    name = after[2]
    rid = _wf_id(sub, rg, name)
    wf = state.get(rid.lower())
    if len(low) == 3:
        if method == "GET":
            return _ok(_view(wf)) if wf else _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Logic/workflows/{name}' under resource group '{rg}' was not found.")
        if method in ("PUT", "PATCH"):
            if method == "PATCH":
                if not wf:
                    return _err(404, "ResourceNotFound", f"Workflow '{name}' not found.")
                payload = {"location": wf.get("location"), "tags": payload.get("tags", wf.get("tags")),
                           "properties": dict(wf["properties"], **(payload.get("properties") or {}))}
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,79}", name):
                return _err(400, "InvalidResourceName", f"The workflow name '{name}' is not valid.")
            bad = _validate_def((payload.get("properties") or {}).get("definition"))
            if bad:
                return _err(400, "InvalidTemplate", bad)
            if str((payload.get("properties") or {}).get("state", "Enabled")) not in ("Enabled", "Disabled"):
                return _err(400, "InvalidRequestContent", "properties.state must be Enabled or Disabled.")
            return _ok(_view(_put(state, sub, rg, name, payload, wf)), 200 if wf else 201)
        if method == "DELETE":
            if wf:
                pre = rid.lower() + "/"
                for k in [k for k in state if str(k).startswith(pre)]:
                    state.pop(k, None)
                state.pop(rid.lower(), None)
            return _ok(None, 200 if wf else 204)
        return _err(405, "MethodNotAllowed", "Unsupported method.")
    if wf is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Logic/workflows/{name}' under resource group '{rg}' was not found.")
    if len(low) == 4 and low[3] in ("enable", "disable") and method == "POST":
        wf["properties"]["state"] = "Enabled" if low[3] == "enable" else "Disabled"
        wf["properties"]["changedTime"] = _now()
        return _ok(None, 200)
    if low[3] == "runs" and method == "GET":
        runs = [_view(r) for k, r in list(state.items()) if isinstance(r, dict) and r.get("_type") == RUN_T and str(k).startswith(rid.lower() + "/runs/")]
        runs.sort(key=lambda r: r["properties"]["startTime"], reverse=True)
        if len(low) == 4:
            return _ok({"value": runs})
        one = next((r for r in runs if r["name"] == after[4]), None)
        return _ok(one) if one else _err(404, "ResourceNotFound", f"Run '{after[4]}' not found.")
    if len(low) == 6 and low[3] == "triggers" and low[5] == "run" and method == "POST":
        if wf["properties"].get("state") != "Enabled":
            return _err(400, "WorkflowDisabled", "The workflow is disabled; enable it before running a trigger.")
        if after[4] not in ((wf["properties"].get("definition") or {}).get("triggers") or {}):
            return _err(404, "TriggerNotFound", f"Trigger '{after[4]}' not found.")
        run = run_workflow(arm, wf, after[4])
        return _ok({"runId": run["name"], "status": run["properties"]["status"]}, 200)
    return None


def _create(arm, method, sub, rg, b):
    if method != "POST":
        return _err(405, "MethodNotAllowed", "POST only.")
    if not rg:
        return _err(400, "InvalidResourceGroup", "A resource group is required.")
    tpl = next((t for t in TEMPLATES if t["id"] == b.get("templateId")), None)
    if not tpl:
        return _err(400, "InvalidTemplate", f"Unknown task template '{b.get('templateId')}'.")
    rid = str(b.get("resourceId") or "")
    target = arm.state.get(rid.lower())
    if target is None:
        return _err(404, "ResourceNotFound", f"Target resource '{rid}' was not found.")
    if str(target.get("type", "")).lower() not in tpl["resourceTypes"]:
        return _err(400, "InvalidTemplate", f"Template '{tpl['id']}' does not apply to {target.get('type')}.")
    params = {**{p["name"]: p["default"] for p in tpl["params"] if "default" in p}, **(b.get("parameters") or {})}
    for p in tpl["params"]:
        if p.get("required") and not params.get(p["name"]):
            return _err(400, "InvalidTemplate", f"Parameter '{p['label']}' ({p['name']}) is required.")
        if p.get("enum") and params.get(p["name"]) not in p["enum"]:
            return _err(400, "InvalidTemplate", f"Parameter '{p['name']}' must be one of {p['enum']}.")
    rec_ = b.get("recurrence") or tpl["recurrence"]
    if spec_of(rec_) is None:
        return _err(400, "InvalidTemplate", "recurrence must have frequency Minute|Hour|Day|Week, a positive interval and (Day only) schedule.hours/minutes.")
    name = str(b.get("name") or f"task-{tpl['id']}-{target['name']}")[:80]
    if arm.state.get(_wf_id(sub, rg, name).lower()):
        return _err(409, "Conflict", f"A task named '{name}' already exists in resource group '{rg}'.")
    body = {"location": target.get("location") or "eastus",
            "tags": {"vyomi-task-template": tpl["id"], "vyomi-task-target": target["id"]},
            "properties": {"state": "Enabled", "definition": _definition(tpl, target["id"], params, rec_)}}
    return _ok(_view(_put(arm.state, sub, rg, name, body)), 201)


# ── scheduler provider ────────────────────────────────────────────────────────
def tick(arm, now, tk, log):
    live, ran = set(), 0
    for rid, wf in list(arm.state.items()):
        if not isinstance(wf, dict) or wf.get("_type") != WF_T or (wf.get("properties") or {}).get("state") != "Enabled":
            continue
        for tn, t in ((wf["properties"].get("definition") or {}).get("triggers") or {}).items():
            spec = spec_of(t.get("recurrence"))
            if not spec:
                continue
            key = f"azwf:{rid}:{tn}"
            live.add(key)
            if tk.due(key, spec, now):
                run = run_workflow(arm, wf, tn)
                ran += 1
                log.append({"provider": "azure-tasks", "workflow": wf["name"], "status": run["properties"]["status"]})
    tk.forget_missing("azwf:", live)
    return ran
