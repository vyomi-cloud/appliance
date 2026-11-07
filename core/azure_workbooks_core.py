"""Azure Workbooks RENDERER (pure Python, Nano + offline) over the real Microsoft.Insights/workbooks CRUD of core/azure_monitor_core.py.

In real Azure the workbook's ``serializedData`` JSON (``Notebook/1.0``) is rendered CLIENT-side by the portal. Vyomi has no portal engine, so this
module is the renderer: ``POST .../Microsoft.Insights/workbooks/{name}/render`` (a Vyomi action on the real resource) executes the workbook
and returns what the portal would draw:

  type 1  text        -> {"type":"text","markdown":...}
  type 9  parameters  -> resolved parameter values (request overrides > the workbook's own value > default)
  type 3  query       -> the item's KQL (parameters substituted: {Name}, {Name:value}, {TimeRange}) is run against the Log Analytics KQL
                         subset (core/azure_operationalinsights_core.run_kql, incl. the AzureActivity feed) -> {"columns","rows","visualization"}
  type 12 group       -> nested items (conditionalVisibility on a parameter is honoured)
  type 11 links       -> the link list (no navigation behaviour)
Anything else (metrics type 10, Resource Graph / ARM / custom-endpoint queries, map/graph visualisations, Resource Health) is reported as
``{"status":"unsupported","reason":...}`` per item -- never an empty success. The query workspace is the item's ``crossComponentResources`` (after
parameter substitution), else the request's ``workspaceId``, else the workbook's ``sourceId`` when that is a workspace, else the only workspace in
the subscription. Only the FIRST resolved workspace is queried (no cross-workspace union). The KQL language itself is the subset documented in
core/capabilities/azure/loganalytics.json (where/project/extend/summarize/top/order/take/count/distinct/render).
"""
from __future__ import annotations

import json
import re

try:
    from core import azure_operationalinsights_core as oi
except ImportError:                                  # pragma: no cover - flat layout
    import azure_operationalinsights_core as oi      # type: ignore

WB = "microsoft.insights/workbooks"
WS = "microsoft.operationalinsights/workspaces"
_PARAM = re.compile(r"\{([A-Za-z_][\w ]*)(?::([A-Za-z]+))?\}")


def _err(status, code, msg):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": msg}}}


def handles(chain):
    return len(chain) == 3 and chain[0].lower() == "workbooks" and chain[2].lower() == "render"


def _walk_params(items, out):
    for it in items or []:
        c = it.get("content") or {}
        if it.get("type") == 9:
            for p in c.get("parameters") or []:
                out.append(p)
        if it.get("type") == 12:
            _walk_params(c.get("items"), out)


def _dur_ms(v):
    if isinstance(v, dict):
        if v.get("durationMs"):
            return int(v["durationMs"])
        if v.get("durationISO"):
            return 86400000
    return 86400000


def _values(wb_items, overrides):
    plist = []
    _walk_params(wb_items, plist)
    vals = {}
    for p in plist:
        name = p.get("name")
        if not name:
            continue
        v = overrides[name] if name in overrides else p.get("value", p.get("defaultValue", ""))
        vals[name] = {"value": v, "type": p.get("type"), "label": p.get("label") or name}
    for k, v in overrides.items():
        vals.setdefault(k, {"value": v, "type": None, "label": k})
    return vals


def _sub(text, vals):
    """Workbook parameter substitution. Returns (text, unresolved names)."""
    missing = []

    def rep(m):
        name, fmt = m.group(1), (m.group(2) or "").lower()
        p = vals.get(name)
        if p is None:
            missing.append(name)
            return m.group(0)
        v = p["value"]
        if p.get("type") == 4 or name.lower() == "timerange":     # time range picker
            ms = _dur_ms(v)
            if fmt in ("", "value"):
                return f"TimeGenerated >= ago({ms}ms)"
            if fmt == "start":
                return f"ago({ms}ms)"
            if fmt == "end":
                return "now()"
            return f"{ms}ms"
        if isinstance(v, list):
            v = ",".join(str(x) for x in v)
        if isinstance(v, dict):
            v = v.get("value", json.dumps(v))
        return str(v)
    return _PARAM.sub(rep, text), missing


def _workspace(state, sub, item_content, vals, req, wb):
    cands = []
    for r in (item_content.get("crossComponentResources") or []):
        r, _m = _sub(str(r), vals)
        cands += [x for x in str(r).split(",") if x]
    if req.get("workspaceId"):
        cands.append(req["workspaceId"])
    if str(wb.get("properties", {}).get("sourceId", "")).lower().startswith("/subscriptions/"):
        cands.append(wb["properties"]["sourceId"])
    for c in cands:
        rec = state.get(str(c).lower())
        if rec is not None and (rec.get("_type") or "").lower() == WS:
            return rec, None
    wss = [r for r in state.values() if isinstance(r, dict) and (r.get("_type") or "").lower() == WS]
    if cands and not wss:
        return None, "none of the referenced Log Analytics workspaces exist"
    if len(wss) == 1:
        return wss[0], None
    if not wss:
        return None, "there is no Log Analytics workspace in the subscription to query"
    return None, "the query item names no workspace (crossComponentResources) and the subscription has several; pass workspaceId"


def _query_item(state, sub, it, c, vals, req, wb):
    base = {"type": "query", "name": it.get("name"), "title": c.get("title") or it.get("name") or "", "size": c.get("size"),
            "visualization": c.get("visualization") or "table"}
    qt = c.get("queryType", 0)
    if qt != 0:
        return {**base, "status": "unsupported", "reason": {1: "Azure Resource Graph queries", 2: "Azure Data Explorer queries", 7: "Azure Monitor metrics via ARM"}.get(qt, f"query type {qt}") +
                " are not rendered (only Log Analytics KQL, queryType 0)."}
    query, missing = _sub(str(c.get("query") or ""), vals)
    if missing:
        return {**base, "status": "error", "error": f"Unresolved workbook parameter(s): {', '.join(sorted(set(missing)))}"}
    rec, why = _workspace(state, sub, c, vals, req, wb)
    if rec is None:
        return {**base, "status": "error", "error": why}
    try:
        res = oi.run_kql(rec, query, extra={"AzureActivity": oi.activity_table(state, sub)})
    except oi.KqlError as e:
        return {**base, "status": "error", "error": f"KQL: {e}", "query": query}
    t = res["tables"][0]
    return {**base, "status": "ok", "query": query, "workspace": rec["id"], "columns": t["columns"], "rows": t["rows"], "rowCount": len(t["rows"])}


def _render_items(state, sub, items, vals, req, wb):
    out = []
    for it in items or []:
        c = it.get("content") or {}
        cv = it.get("conditionalVisibility")
        if cv and cv.get("parameterName"):
            cur = (vals.get(cv["parameterName"]) or {}).get("value")
            want = cv.get("value")
            ok = (str(cur) == str(want)) if cv.get("comparison", "isEqualTo") == "isEqualTo" else (str(cur) != str(want))
            if not ok:
                out.append({"type": "hidden", "name": it.get("name"), "reason": f"conditionalVisibility on {cv['parameterName']}"})
                continue
        t = it.get("type")
        if t == 1:
            out.append({"type": "text", "name": it.get("name"), "markdown": _sub(str(c.get("json") or ""), vals)[0]})
        elif t == 9:
            out.append({"type": "parameters", "name": it.get("name"),
                        "parameters": [{"name": p.get("name"), "label": p.get("label") or p.get("name"), "value": vals.get(p.get("name"), {}).get("value")}
                                       for p in (c.get("parameters") or [])]})
        elif t == 3:
            out.append(_query_item(state, sub, it, c, vals, req, wb))
        elif t == 12:
            out.append({"type": "group", "name": it.get("name"), "title": c.get("title") or it.get("name") or "", "items": _render_items(state, sub, c.get("items"), vals, req, wb)})
        elif t == 11:
            out.append({"type": "links", "name": it.get("name"), "links": [{"label": l.get("linkLabel"), "style": l.get("style"), "target": l.get("linkTarget")} for l in (c.get("links") or [])]})
        else:
            names = {10: "Azure Monitor metrics items", 13: "info/other items", 14: "Resource Health items"}
            out.append({"type": "unsupported", "name": it.get("name"), "status": "unsupported", "reason": f"{names.get(t, f'item type {t}')} are not rendered."})
    return out


def render(state, sub, rg, name, payload):
    rec = state.get(f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Insights/workbooks/{name}".lower())
    if rec is None or (rec.get("_type") or "").lower() != WB:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Insights/workbooks/{name}' under resource group '{rg}' was not found.")
    try:
        doc = json.loads(rec["properties"]["serializedData"])
    except (ValueError, KeyError, TypeError):
        return _err(400, "InvalidWorkbookContent", "properties.serializedData is not valid workbook JSON.")
    if not isinstance(doc, dict) or not isinstance(doc.get("items", []), list):
        return _err(400, "InvalidWorkbookContent", "serializedData must be a Notebook/1.0 document with an 'items' array.")
    req = payload if isinstance(payload, dict) else {}
    overrides = req.get("parameters") if isinstance(req.get("parameters"), dict) else {}
    vals = _values(doc.get("items"), overrides)
    items = _render_items(state, sub, doc.get("items"), vals, req, rec)
    flat = []

    def walk(xs):
        for x in xs:
            flat.append(x)
            if x.get("type") == "group":
                walk(x["items"])
    walk(items)
    q = [x for x in flat if x.get("type") == "query"]
    return {"status": 200, "headers": {}, "body": {
        "id": rec["id"], "name": rec["name"], "displayName": rec["properties"].get("displayName"), "version": doc.get("version"),
        "parameters": {k: v["value"] for k, v in vals.items()}, "items": items,
        "summary": {"queries": len(q), "ok": sum(1 for x in q if x.get("status") == "ok"), "errors": sum(1 for x in q if x.get("status") == "error"),
                    "unsupported": sum(1 for x in flat if x.get("status") == "unsupported")}}}
