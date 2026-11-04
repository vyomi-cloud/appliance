"""Amazon EventBridge Schemas (service `schemas`, SigV4 signing name `schemas`, rest-json) — substrate-independent.

Registries -> schemas -> versions, discoverers, SearchSchemas, with the real REST shapes (`/v1/registries/name/{r}`,
`/v1/registries/name/{r}/schemas/name/{s}`, `/v1/discoverers`, `/v1/search/schemas`). Schema discovery is REAL:
a started discoverer on an event bus infers an OpenAPI 3 schema from every PutEvents payload (name
`<source>@<detail-type>` in registry `discovered-schemas`) and bumps the schema's version when the observed shape changes.
State lives in the EventBridge store's persisted bag (`eventbridge_core._bag`) so offline + Nano both persist it.
Pure Python (no fastapi/boto3) — loads under Pyodide.

Honest limits: code bindings / language generation (GetCodeBindingSource, PutCodeBinding) are not implemented; AWS
service-event schemas in the `aws.events` registry are not shipped, only schemas you create or discover; the inferred
schema covers JSON types, nesting and arrays (no format/enum inference).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
DISCOVERED = "discovered-schemas"
_NAME_RE = re.compile(r"^[A-Za-z0-9._@\-/]{1,385}$")


@dataclass
class SchemasResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


class _Err(Exception):
    def __init__(self, code, message, status):
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _st(store) -> dict:
    from core import eventbridge_core as ebc
    reg = ebc._bag(store, "schema_registries")
    if DISCOVERED not in reg:
        reg[DISCOVERED] = {"RegistryName": DISCOVERED, "RegistryArn": _reg_arn(DISCOVERED), "Description": "Schemas discovered from events",
                           "Tags": {}, "schemas": {}}
    return {"registries": reg, "discoverers": ebc._bag(store, "schema_discoverers")}


def _reg_arn(n):
    return f"arn:aws:schemas:{_REGION}:{_ACCOUNT}:registry/{n}"


def _schema_arn(r, s):
    return f"arn:aws:schemas:{_REGION}:{_ACCOUNT}:schema/{r}/{s}"


def _registry(st, name):
    r = st["registries"].get(name)
    if r is None:
        raise _Err("NotFoundException", f"Registry {name} not found.", 404)
    return r


def _schema(st, rname, sname):
    s = _registry(st, rname)["schemas"].get(sname)
    if s is None:
        raise _Err("NotFoundException", f"Schema {sname} not found in registry {rname}.", 404)
    return s


# ── inference (OpenAPI 3 from a JSON event) ──────────────────────────────────────────
def _infer(v):
    if isinstance(v, bool):
        return {"type": "boolean"}
    if isinstance(v, int):
        return {"type": "integer", "format": "int64"}
    if isinstance(v, float):
        return {"type": "number", "format": "double"}
    if isinstance(v, str):
        return {"type": "string"}
    if isinstance(v, list):
        items = [_infer(x) for x in v]
        uniq = []
        for i in items:
            if i not in uniq:
                uniq.append(i)
        return {"type": "array", "items": uniq[0] if len(uniq) == 1 else ({"oneOf": uniq} if uniq else {})}
    if isinstance(v, dict):
        return {"type": "object", "properties": {k: _infer(x) for k, x in v.items()}}
    return {}


def _title(detail_type: str) -> str:
    t = re.sub(r"[^A-Za-z0-9]+", " ", detail_type or "").title().replace(" ", "")
    return t or "Event"


def _openapi_for_event(env: dict) -> str:
    title = _title(env.get("detail-type", ""))
    doc = {"openapi": "3.0.0", "info": {"version": "1.0.0", "title": title},
           "paths": {},
           "components": {"schemas": {
               "AWSEvent": {"type": "object", "required": ["detail-type", "resources", "detail", "id", "source", "time", "region", "version", "account"],
                            "x-amazon-events-detail-type": env.get("detail-type", ""), "x-amazon-events-source": env.get("source", ""),
                            "properties": {"detail": {"$ref": f"#/components/schemas/{title}"}, "account": {"type": "string"}, "detail-type": {"type": "string"},
                                           "id": {"type": "string"}, "region": {"type": "string"}, "resources": {"type": "array", "items": {"type": "object"}},
                                           "source": {"type": "string"}, "time": {"type": "string", "format": "date-time"}, "version": {"type": "string"}}},
               title: _infer(env.get("detail") or {})}}}
    return json.dumps(doc, sort_keys=True)


def discover(store, bus_name: str, envelope: dict) -> None:
    """Called by PutEvents: every STARTED discoverer on this bus records/updates the event's schema."""
    st = _st(store)
    arn = f"arn:aws:events:{_REGION}:{_ACCOUNT}:event-bus/{bus_name}"
    if not any(d["State"] == "STARTED" and d["SourceArn"].rsplit("/", 1)[-1] == bus_name for d in st["discoverers"].values()):
        return
    name = f"{envelope.get('source', 'unknown')}@{re.sub(r'[^A-Za-z0-9]+', '', envelope.get('detail-type', '') or 'Event')}"
    content = _openapi_for_event(envelope)
    reg = st["registries"][DISCOVERED]
    s = reg["schemas"].get(name)
    if s is None:
        reg["schemas"][name] = {"SchemaName": name, "SchemaArn": _schema_arn(DISCOVERED, name), "Type": "OpenApi3", "Description": "Schema discovered from events",
                                "Tags": {}, "LastModified": _now(), "versions": [{"SchemaVersion": "1", "Content": content, "CreatedDate": _now()}]}
    elif s["versions"][-1]["Content"] != content:
        # merge: a changed shape (new field/type) becomes a new version
        s["versions"].append({"SchemaVersion": str(len(s["versions"]) + 1), "Content": content, "CreatedDate": _now()})
        s["LastModified"] = _now()


# ── operations ───────────────────────────────────────────────────────────────────────
def _reg_view(r):
    return {"RegistryName": r["RegistryName"], "RegistryArn": r["RegistryArn"], "Description": r.get("Description", ""), "Tags": r.get("Tags", {})}


def _create_registry(st, name, p, q):
    if not _NAME_RE.match(name):
        raise _Err("BadRequestException", "Invalid registry name.", 400)
    if name in st["registries"]:
        raise _Err("ConflictException", f"Registry {name} already exists.", 409)
    st["registries"][name] = {"RegistryName": name, "RegistryArn": _reg_arn(name), "Description": p.get("Description", ""), "Tags": p.get("tags", {}) or {}, "schemas": {}}
    return 200, _reg_view(st["registries"][name])


def _describe_registry(st, name, p, q):
    return 200, _reg_view(_registry(st, name))


def _update_registry(st, name, p, q):
    r = _registry(st, name)
    if "Description" in p:
        r["Description"] = p["Description"]
    return 200, _reg_view(r)


def _delete_registry(st, name, p, q):
    if name == DISCOVERED:
        raise _Err("ForbiddenException", "The discovered-schemas registry cannot be deleted.", 403)
    _registry(st, name)
    del st["registries"][name]
    return 204, {}


def _list_registries(st, p, q):
    items = [_reg_view(r) for r in st["registries"].values()]
    if q.get("registryNamePrefix"):
        items = [i for i in items if i["RegistryName"].startswith(q["registryNamePrefix"])]
    return 200, {"Registries": items}


def _sch_view(rname, s, version=None, content=False):
    v = s["versions"][-1] if version is None else next((x for x in s["versions"] if x["SchemaVersion"] == str(version)), None)
    if v is None:
        raise _Err("NotFoundException", f"Schema version {version} not found.", 404)
    out = {"SchemaName": s["SchemaName"], "SchemaArn": s["SchemaArn"], "SchemaVersion": v["SchemaVersion"], "Type": s["Type"], "Description": s.get("Description", ""),
           "LastModified": s["LastModified"], "VersionCreatedDate": v["CreatedDate"], "Tags": s.get("Tags", {})}
    if content:
        out["Content"] = v["Content"]
    return out


def _validate_content(typ, content):
    try:
        doc = json.loads(content)
    except Exception:
        raise _Err("BadRequestException", "Schema content must be valid JSON.", 400)
    if typ == "OpenApi3" and not (isinstance(doc, dict) and str(doc.get("openapi", "")).startswith("3")):
        raise _Err("BadRequestException", "OpenApi3 content needs an \"openapi\": \"3.x\" field.", 400)
    if typ == "JSONSchemaDraft4" and not isinstance(doc, dict):
        raise _Err("BadRequestException", "JSONSchemaDraft4 content must be a JSON object.", 400)


def _create_schema(st, rname, sname, p, q):
    reg = _registry(st, rname)
    if rname == DISCOVERED:
        raise _Err("ForbiddenException", "Schemas in discovered-schemas are created by discoverers.", 403)
    typ = p.get("Type", "OpenApi3")
    if typ not in ("OpenApi3", "JSONSchemaDraft4"):
        raise _Err("BadRequestException", "Type must be OpenApi3 or JSONSchemaDraft4.", 400)
    _validate_content(typ, p.get("Content", ""))
    if sname in reg["schemas"]:
        raise _Err("ConflictException", f"Schema {sname} already exists.", 409)
    reg["schemas"][sname] = {"SchemaName": sname, "SchemaArn": _schema_arn(rname, sname), "Type": typ, "Description": p.get("Description", ""), "Tags": p.get("tags", {}) or {},
                             "LastModified": _now(), "versions": [{"SchemaVersion": "1", "Content": p["Content"], "CreatedDate": _now()}]}
    return 200, _sch_view(rname, reg["schemas"][sname])


def _describe_schema(st, rname, sname, p, q):
    return 200, _sch_view(rname, _schema(st, rname, sname), q.get("schemaVersion"), content=True)


def _update_schema(st, rname, sname, p, q):
    s = _schema(st, rname, sname)
    if p.get("Content") is not None:
        _validate_content(p.get("Type") or s["Type"], p["Content"])
        s["versions"].append({"SchemaVersion": str(len(s["versions"]) + 1), "Content": p["Content"], "CreatedDate": _now()})
    if "Description" in p:
        s["Description"] = p["Description"]
    s["LastModified"] = _now()
    return 200, _sch_view(rname, s)


def _delete_schema(st, rname, sname, p, q):
    _schema(st, rname, sname)
    del st["registries"][rname]["schemas"][sname]
    return 204, {}


def _list_schemas(st, rname, p, q):
    reg = _registry(st, rname)
    items = [{"SchemaName": s["SchemaName"], "SchemaArn": s["SchemaArn"], "LastModified": s["LastModified"], "VersionCount": len(s["versions"]), "Tags": s.get("Tags", {})}
             for s in reg["schemas"].values()]
    if q.get("schemaNamePrefix"):
        items = [i for i in items if i["SchemaName"].startswith(q["schemaNamePrefix"])]
    return 200, {"Schemas": items}


def _list_versions(st, rname, sname, p, q):
    s = _schema(st, rname, sname)
    return 200, {"SchemaVersions": [{"SchemaName": sname, "SchemaArn": s["SchemaArn"], "SchemaVersion": v["SchemaVersion"], "Type": s["Type"]} for v in s["versions"]]}


def _search(st, p, q):
    kw = [k.strip().lower() for k in (q.get("keywords") or "").split(",") if k.strip()]
    out = []
    for rname, reg in st["registries"].items():
        if q.get("registryName") and q["registryName"] != rname:
            continue
        hits = []
        for s in reg["schemas"].values():
            hay = (s["SchemaName"] + " " + s.get("Description", "") + " " + s["versions"][-1]["Content"]).lower()
            if all(k in hay for k in kw):
                hits.append({"SchemaName": s["SchemaName"], "SchemaArn": s["SchemaArn"], "SchemaVersions": [{"SchemaVersion": v["SchemaVersion"], "Type": s["Type"]} for v in s["versions"]]})
        if hits:
            out.append({"RegistryName": rname, "Schemas": hits})
    return 200, {"Schemas": [{"RegistryName": o["RegistryName"], "SchemaName": h["SchemaName"], "SchemaArn": h["SchemaArn"], "SchemaVersions": h["SchemaVersions"]} for o in out for h in o["Schemas"]]}


def _disc_view(d):
    return {"DiscovererId": d["DiscovererId"], "DiscovererArn": d["DiscovererArn"], "SourceArn": d["SourceArn"], "Description": d.get("Description", ""),
            "State": d["State"], "CrossAccount": False, "Tags": d.get("Tags", {})}


def _create_discoverer(st, p, q):
    src = p.get("SourceArn", "")
    if ":event-bus/" not in src:
        raise _Err("BadRequestException", "SourceArn must be an EventBridge event bus ARN.", 400)
    if any(d["SourceArn"] == src for d in st["discoverers"].values()):
        raise _Err("ConflictException", "A discoverer already exists for this event bus.", 409)
    did = "".join(re.findall(r"[0-9a-f]", uuid.uuid4().hex))[:10]
    did = f"{did}"
    d = {"DiscovererId": did, "DiscovererArn": f"arn:aws:schemas:{_REGION}:{_ACCOUNT}:discoverer/{did}", "SourceArn": src, "Description": p.get("Description", ""),
         "State": "STARTED", "Tags": p.get("tags", {}) or {}}
    st["discoverers"][did] = d
    return 200, _disc_view(d)


def _disc(st, did):
    d = st["discoverers"].get(did)
    if d is None:
        raise _Err("NotFoundException", f"Discoverer {did} not found.", 404)
    return d


_ROUTES = []


def _route(method, pattern):
    def deco(fn):
        _ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


_route("POST", r"/v1/registries/name/([^/]+)")(lambda st, g, p, q: _create_registry(st, g[0], p, q))
_route("GET", r"/v1/registries/name/([^/]+)")(lambda st, g, p, q: _describe_registry(st, g[0], p, q))
_route("PUT", r"/v1/registries/name/([^/]+)")(lambda st, g, p, q: _update_registry(st, g[0], p, q))
_route("DELETE", r"/v1/registries/name/([^/]+)")(lambda st, g, p, q: _delete_registry(st, g[0], p, q))
_route("GET", r"/v1/registries")(lambda st, g, p, q: _list_registries(st, p, q))
_route("POST", r"/v1/registries/name/([^/]+)/schemas/name/(.+)")(lambda st, g, p, q: _create_schema(st, g[0], g[1], p, q))
_route("GET", r"/v1/registries/name/([^/]+)/schemas/name/([^/]+)/versions")(lambda st, g, p, q: _list_versions(st, g[0], g[1], p, q))
_route("GET", r"/v1/registries/name/([^/]+)/schemas/name/([^/]+)")(lambda st, g, p, q: _describe_schema(st, g[0], g[1], p, q))
_route("PUT", r"/v1/registries/name/([^/]+)/schemas/name/([^/]+)")(lambda st, g, p, q: _update_schema(st, g[0], g[1], p, q))
_route("DELETE", r"/v1/registries/name/([^/]+)/schemas/name/([^/]+)")(lambda st, g, p, q: _delete_schema(st, g[0], g[1], p, q))
_route("GET", r"/v1/registries/name/([^/]+)/schemas")(lambda st, g, p, q: _list_schemas(st, g[0], p, q))
_route("GET", r"/v1/search/schemas")(lambda st, g, p, q: _search(st, p, q))
_route("POST", r"/v1/discoverers")(lambda st, g, p, q: _create_discoverer(st, p, q))
_route("GET", r"/v1/discoverers")(lambda st, g, p, q: (200, {"Discoverers": [_disc_view(d) for d in st["discoverers"].values()]}))
_route("GET", r"/v1/discoverers/id/([^/]+)")(lambda st, g, p, q: (200, _disc_view(_disc(st, g[0]))))
_route("DELETE", r"/v1/discoverers/id/([^/]+)")(lambda st, g, p, q: (st["discoverers"].pop(_disc(st, g[0])["DiscovererId"]) and (204, {})))
_route("POST", r"/v1/discoverers/id/([^/]+)/start")(lambda st, g, p, q: (200, _disc_view(_disc(st, g[0]) | {"State": "STARTED"})) if _set_state(st, g[0], "STARTED") else None)
_route("POST", r"/v1/discoverers/id/([^/]+)/stop")(lambda st, g, p, q: (200, _disc_view(_disc(st, g[0]))) if _set_state(st, g[0], "STOPPED") else None)


def _set_state(st, did, state):
    _disc(st, did)["State"] = state
    return True


_MUTATING = {"POST", "PUT", "DELETE"}


def dispatch(store, method: str, raw_path: str, query: dict, headers: dict, body: bytes) -> SchemasResponse:
    path = urllib.parse.unquote(raw_path.split("?", 1)[0])
    method = (method or "GET").upper()

    def resp(status, doc):
        return SchemasResponse(status=status, body=(json.dumps(doc).encode() if status != 204 else b""), headers={"x-amzn-requestid": uuid.uuid4().hex})

    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return resp(400, {"Code": "BadRequestException", "Message": "The request body must be a JSON object"})
    st = _st(store)
    for m, rx, fn in _ROUTES:
        mt = rx.match(path)
        if m == method and mt:
            try:
                out = fn(st, [urllib.parse.unquote(g) for g in mt.groups()], p, dict(query or {}))
            except _Err as e:
                return resp(e.status, {"Code": e.code, "Message": e.message})
            if method in _MUTATING:
                try:
                    store.persist()
                except Exception:
                    pass
            return resp(out[0], out[1])
    return resp(404, {"Code": "NotFoundException", "Message": f"Unknown EventBridge Schemas operation: {method} {path}"})
