# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure API Management gateway data plane — /azure-data/apim/{service}/{api-path...}.

The request path whose measured traffic feeds the derived `Capacity` metric (core/azure_monitor_core.py):
every call lands in the observability recorder with op `Gateway:<METHOD>` (core/observability_core.py), so the
metric is computed from requests the gateway REALLY served, never invented.

Behaviour (the same admission checks the console's Test action replays, core/azure_arm_core._apim_test_connect):
  * the service must exist in the ARM state (404 ServiceNotFound);
  * a subscription key (`Ocp-Apim-Subscription-Key` header or `subscription-key` query) belonging to an ACTIVE
    subscription of THIS service is required (401 otherwise);
  * the first path segment selects the API (by name or `properties.path`); an API with `properties.mockResponse`
    returns it, every other request returns a generic mock. Nothing is proxied off the box (Nano runs in a browser);
    the offline appliance's own handler (core/azure_dataplane._apim_handle) additionally proxies `serviceUrl`.
"""
from __future__ import annotations

import json

_JSON = {"content-type": "application/json"}


def _resp(status, obj):
    return {"status": status, "headers": dict(_JSON), "body": json.dumps(obj).encode()}


def handle(state, method, path, query, lheaders):
    segs = [s for s in path.split("?", 1)[0].split("/") if s]       # azure-data / apim / <service> / <rest...>
    if len(segs) < 3:
        return _resp(404, {"error": {"code": "ServiceNotFound", "message": "No API Management service named in the request path."}})
    service, rest = segs[2], segs[3:]
    svc_rid, svc_rec = None, None
    for rid, rec in state.items():
        if str(rec.get("_type", "")).lower() == "microsoft.apimanagement/service" and str(rec.get("name", "")).lower() == service.lower():
            svc_rid, svc_rec = rid, rec
            break
    if svc_rec is None:
        return _resp(404, {"error": {"code": "ServiceNotFound", "message": f"APIM service '{service}' not found"}})
    key = lheaders.get("ocp-apim-subscription-key") or (query or {}).get("subscription-key") or ""
    if isinstance(key, list):
        key = key[0] if key else ""
    if not key:
        return _resp(401, {"statusCode": 401, "message": "Access denied due to missing subscription key. "
                                                      "Include 'Ocp-Apim-Subscription-Key' header."})
    pre = svc_rid.lower() + "/subscriptions/"
    sub = next((r for k, r in state.items() if k.startswith(pre)
                and key in ((r.get("properties") or {}).get("primaryKey"), (r.get("properties") or {}).get("secondaryKey"))), None)
    if sub is None or (sub.get("properties") or {}).get("state", "active") != "active":
        return _resp(401, {"statusCode": 401, "message": "Access denied due to invalid subscription key."})
    seg0 = rest[0].lower() if rest else ""
    api = None
    apre = svc_rid.lower() + "/apis/"
    for k, r in state.items():
        if k.startswith(apre) and "/" not in k[len(apre):]:
            if str(r.get("name", "")).lower() == seg0 or str((r.get("properties") or {}).get("path", "")).strip("/").lower() == seg0:
                api = r
                break
    mock = ((api or {}).get("properties") or {}).get("mockResponse")
    if mock is not None and mock != "":
        return _resp(200, mock if isinstance(mock, dict) else {"value": mock})
    return _resp(200, {"statusCode": 200, "message": "OK", "service": service, "path": "/".join(rest), "method": method.upper(), "mock": True})
