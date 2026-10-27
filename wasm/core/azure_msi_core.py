"""Azure Managed Identities core (``Microsoft.ManagedIdentity`` — user-assigned identities, federated credentials).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

ARM REST of the ``msi`` resource provider (azure-rest-api-specs ``specification/msi/resource-manager``,
api-version 2023-01-31), so ``azure-mgmt-msi`` / ``armmsi`` / ``com.azure.resourcemanager.msi`` and
``az identity create|show|list|update|delete|list-resources`` / ``az identity federated-credential …``
work unchanged:

    Microsoft.ManagedIdentity/userAssignedIdentities     (CreateOrUpdate / Update / Delete / Get / ListByResourceGroup /
                                                          ListBySubscription)
    .../userAssignedIdentities/{name}/listAssociatedResources   (POST, $filter / $orderby / $top / $skiptoken)
    .../userAssignedIdentities/{name}/federatedIdentityCredentials/{credName}   (CreateOrUpdate / Delete / Get / List)

Federated credentials live INSIDE the identity's ARM record (underscore key ``_fic``, never serialised to
ARM clients), so they are space-scoped and persisted by the same seams as the rest of ARM (offline
``azure_arm_state``; Nano ``az_arm``). ``listAssociatedResources`` scans the same ARM state for resources
whose ``identity.userAssignedIdentities`` references the identity.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able object
or ``None``). Nothing here is long-running (every operation is synchronous, as in Azure).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

NAMESPACE = "Microsoft.ManagedIdentity"
UAI_TYPE = "userassignedidentities"          # ARM reports the type as Microsoft.ManagedIdentity/userAssignedIdentities
UAI_ARM_TYPE = f"{NAMESPACE}/userAssignedIdentities"
FIC_ARM_TYPE = f"{UAI_ARM_TYPE}/federatedIdentityCredentials"
API_VERSION = "2023-01-31"
DEFAULT_LOCATION = "eastus"
TENANT_ID = "00000000-0000-0000-0000-000000000000"
MAX_FIC = 20
ISOLATION_SCOPES = ("None", "Regional")
DEFAULT_PAGE = 100


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _uai_rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{UAI_ARM_TYPE}/{name}"


def _not_found(name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{UAI_ARM_TYPE}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _identities(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == UAI_ARM_TYPE.lower()]


# ═══════════════════════════ names / ids ═════════════════════════════════════════
_UAI_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{2,127}$")
_FIC_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{2,119}$")


def _guid(rid, role):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rid.lower()}#{role}"))


# ═══════════════════════════ identities ══════════════════════════════════════════
def _system_data(rec_or_now=None):
    ts = _now()
    return {"createdBy": "cloudlearn@vyomi.local", "createdByType": "User", "createdAt": ts,
            "lastModifiedBy": "cloudlearn@vyomi.local", "lastModifiedByType": "User", "lastModifiedAt": ts}


def _touch(rec):
    sd = rec.get("systemData")
    if sd:
        sd["lastModifiedAt"] = _now()


def _uai_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    return out


def _isolation(pay):
    v = pay.get("isolationScope")
    if v is None:
        return None
    for s in ISOLATION_SCOPES:
        if str(v).lower() == s.lower():
            return s
    raise _E(400, "BadRequest", f"The isolationScope '{v}' is invalid. Allowed values are None, Regional.")


def _put_uai(state, sub, rg, rid, name, payload, method):
    if not _UAI_NAME.match(name or ""):
        raise _E(400, "InvalidResourceName",
                 f"The resource name '{name}' is invalid. Names must be 3 to 128 characters of letters, digits, "
                 "hyphens and underscores, starting with a letter or digit.")
    pay = payload.get("properties") or {}
    tags = payload.get("tags")
    if tags is not None and not isinstance(tags, dict):
        raise _E(400, "BadRequest", "tags must be an object of string values.")
    scope = _isolation(pay)
    rec = state.get(rid.lower())
    if rec is None:
        if method == "PATCH":
            raise _not_found(name, rg)
        loc = payload.get("location")
        if not loc:
            raise _E(400, "LocationRequired", "The location property is required for this definition.")
        props = {"tenantId": TENANT_ID, "principalId": _guid(rid, "principal"), "clientId": _guid(rid, "client")}
        if scope:
            props["isolationScope"] = scope
        rec = {"id": rid, "name": name, "type": UAI_ARM_TYPE, "location": str(loc).lower().replace(" ", ""),
               "tags": dict(tags or {}), "systemData": _system_data(), "properties": props,
               "_type": UAI_ARM_TYPE, "_sub": sub, "_rg": rg, "_fic": {}}
        state[rid.lower()] = rec
        return rec, True
    loc = payload.get("location")
    if method == "PUT" and loc and str(loc).lower().replace(" ", "") != rec["location"]:
        raise _E(400, "InvalidResourceLocation",
                 f"The resource '{name}' already exists in location '{rec['location']}' in resource group '{rg}'. "
                 f"A resource with the same name cannot be created in location '{loc}'. "
                 "Please select a new resource name.")
    if tags is not None:
        rec["tags"] = dict(tags)
    elif method == "PUT":
        rec["tags"] = {}
    if scope:
        rec["properties"]["isolationScope"] = scope
    _touch(rec)
    return rec, False


def _page(items, query, base, path, extra=""):
    top = _to_int(query.get("$top"))
    skip = _to_int(query.get("$skiptoken"), 0) or 0
    rest = items[skip:]
    if top is None or top <= 0 or len(rest) <= top:
        return {"value": rest}
    q = f"api-version={query.get('api-version') or API_VERSION}&$top={top}&$skiptoken={skip + top}{extra}"
    return {"value": rest[:top], "nextLink": f"{base}{quote(path)}?{q}"}


def _list_uai(state, sub, rg, query, base):
    xs = [r for r in _identities(state) if r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
    xs.sort(key=lambda r: (r["name"].lower(), r["id"].lower()))
    path = f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if rg else "") + f"/providers/{UAI_ARM_TYPE}"
    return _ok(_page([_uai_view(r) for r in xs], query, base, path))


# ═══════════════════════════ associated resources ════════════════════════════════
_COND = re.compile(r"^\s*(?:(contains|startswith|endswith)\(\s*(\w+)\s*,\s*'((?:[^']|'')*)'\s*\)|(\w+)\s+(eq|ne)\s+'((?:[^']|'')*)')\s*$", re.I)


def _filter_conds(expr):
    conds = []
    for part in re.split(r"\s+and\s+", expr or "", flags=re.I):
        if not part.strip():
            continue
        m = _COND.match(part)
        if not m:
            raise _E(400, "InvalidFilter", f"The $filter expression '{part.strip()}' is not supported. Use eq/ne, "
                                           "contains, startswith or endswith on name, type, resourceGroup or subscriptionId.")
        fn, f1, v1, f2, op, v2 = m.groups()
        field, val = (f1, v1) if fn else (f2, v2)
        field = field.lower()
        if field not in ("name", "type", "resourcegroup", "subscriptionid"):
            raise _E(400, "InvalidFilter", f"The $filter property '{field}' is not supported.")
        conds.append(((fn or op).lower(), field, val.replace("''", "'").lower()))
    return conds


def _match(item, conds):
    for op, field, val in conds:
        have = str({"name": item["name"], "type": item["type"], "resourcegroup": item["resourceGroup"],
                    "subscriptionid": item["subscriptionId"]}[field]).lower()
        ok = {"eq": have == val, "ne": have != val, "contains": val in have, "startswith": have.startswith(val),
              "endswith": have.endswith(val)}[op]
        if not ok:
            return False
    return True


def associated_resources(state, rec):
    """ARM resources (any engine) whose ``identity.userAssignedIdentities`` names this identity."""
    key = rec["id"].lower()
    out = []
    for r in state.values():
        if not isinstance(r, dict) or r is rec or not r.get("id") or str(r.get("_type", "")).lower() == UAI_ARM_TYPE.lower():
            continue
        ua = (r.get("identity") or {}).get("userAssignedIdentities") or {}
        if any(str(k).lower() == key for k in ua):
            m = re.match(r"^/subscriptions/([^/]+)/resourceGroups/([^/]+)/", r["id"], re.I)
            out.append({"id": r["id"], "name": r.get("name") or r["id"].rsplit("/", 1)[-1],
                        "type": r.get("type") or r.get("_type") or "", "resourceGroup": m.group(2) if m else r.get("_rg", ""),
                        "subscriptionId": m.group(1) if m else r.get("_sub", "")})
    return out


def _list_associated(state, rec, query, base):
    items = associated_resources(state, rec)
    items = [i for i in items if _match(i, _filter_conds(query.get("$filter")))]
    ob = (query.get("$orderby") or "name asc").strip().split()
    field = ob[0].lower() if ob else "name"
    if field not in ("name", "type", "resourcegroup", "subscriptionid"):
        raise _E(400, "InvalidOrderBy", f"The $orderby property '{ob[0]}' is not supported.")
    key = {"name": "name", "type": "type", "resourcegroup": "resourceGroup", "subscriptionid": "subscriptionId"}[field]
    items.sort(key=lambda i: str(i[key]).lower(), reverse=len(ob) > 1 and ob[1].lower() == "desc")
    top = _to_int(query.get("$top"))
    if top is not None and not 1 <= top <= 1000:
        raise _E(400, "BadRequest", "$top must be between 1 and 1000.")
    q = dict(query)
    if top is None:
        q["$top"] = str(DEFAULT_PAGE)
    extra = "".join(f"&{k}={quote(query[k])}" for k in ("$filter", "$orderby") if query.get(k))
    return _ok(_page(items, q, base, f"{rec['id']}/listAssociatedResources", extra))


# ═══════════════════════════ federated identity credentials ══════════════════════
def _fic_view(rec, c):
    return {"id": f"{rec['id']}/federatedIdentityCredentials/{c['name']}", "name": c["name"], "type": FIC_ARM_TYPE,
            "systemData": c["systemData"],
            "properties": {"issuer": c["issuer"], "subject": c["subject"], "audiences": list(c["audiences"])}}


def _fic_fields(props, cur):
    issuer = props.get("issuer", cur and cur["issuer"])
    subject = props.get("subject", cur and cur["subject"])
    aud = props.get("audiences", cur and cur["audiences"])
    for f, v in (("issuer", issuer), ("subject", subject)):
        if not isinstance(v, str) or not v:
            raise _E(400, "BadRequest", f"The federated identity credential property '{f}' is required.")
    if not isinstance(aud, list) or not aud or not all(isinstance(a, str) and a for a in aud):
        raise _E(400, "BadRequest", "The federated identity credential property 'audiences' is required.")
    if len(aud) != 1:
        raise _E(400, "BadRequest", "The federated identity credential 'audiences' must contain exactly one value.")
    if not re.match(r"^https://[^\s/]+", issuer) or len(issuer) > 600:
        raise _E(400, "BadRequest", f"The issuer '{issuer}' is invalid. The issuer must be an https URL.")
    if len(subject) > 600:
        raise _E(400, "BadRequest", "The subject must be at most 600 characters.")
    return issuer, subject, list(aud)


def _fic_ops(state, rec, rest, method, payload, query, base):
    store = rec["_fic"]
    if rest[0].lower() != "federatedidentitycredentials" or len(rest) > 2:
        return _err(404, "ResourceTypeNotSupported",
                    f"The resource type '{UAI_ARM_TYPE}/{'/'.join(rest)}' is not supported.")
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_fic_view(rec, c) for c in sorted(store.values(), key=lambda c: c["name"].lower())]
        return _ok(_page(items, query, base, f"{rec['id']}/federatedIdentityCredentials"))
    name = rest[1]
    cur = store.get(name.lower())
    if method == "GET":
        if cur is None:
            raise _E(404, "ResourceNotFound", f"The Resource '{FIC_ARM_TYPE}/{rec['name']}/{name}' under resource group "
                                              f"'{rec['_rg']}' was not found. For more details please go to https://aka.ms/ARMResourceNotFoundFix")
        return _ok(_fic_view(rec, cur))
    if method == "PUT":
        if not _FIC_NAME.match(name):
            raise _E(400, "InvalidResourceName",
                     f"The federated identity credential name '{name}' is invalid. Names must be 3 to 120 characters of "
                     "letters, digits, hyphens and underscores, starting with a letter or digit.")
        issuer, subject, aud = _fic_fields(payload.get("properties") or {}, None)
        for o in store.values():
            if o["name"].lower() != name.lower() and o["issuer"] == issuer and o["subject"] == subject:
                raise _E(409, "Conflict", f"A federated identity credential with issuer '{issuer}' and subject "
                                          f"'{subject}' already exists on this identity ('{o['name']}').")
        if cur is None and len(store) >= MAX_FIC:
            raise _E(400, "BadRequest", f"The identity already has the maximum of {MAX_FIC} federated identity credentials.")
        sd = cur["systemData"] if cur else _system_data()
        sd["lastModifiedAt"] = _now()
        c = {"name": cur["name"] if cur else name, "issuer": issuer, "subject": subject, "audiences": aud, "systemData": sd}
        store[name.lower()] = c
        return _ok(_fic_view(rec, c), 200 if cur else 201)
    if method == "DELETE":
        if cur is None:
            return _ok(None, 204)
        store.pop(name.lower(), None)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ dispatch ════════════════════════════════════════════
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.ManagedIdentity`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, base)
    except _E as e:
        return _err(e.status, e.code, e.message)


def handles(chain):
    return bool(chain) and chain[0].lower() == UAI_TYPE


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_uai(state, sub, rg, query, base)
    name = chain[1]
    if rg is None:
        return _err(400, "InvalidResourceId", "User-assigned identities must be addressed within a resource group.")
    rid = _uai_rid(sub, rg, name)
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found(name, rg)
        if rest[0].lower() == "listassociatedresources" and len(rest) == 1:
            if method != "POST":
                return _err(405, "MethodNotAllowed", "POST required.")
            return _list_associated(state, rec, query, base)
        return _fic_ops(state, rec, rest, method, payload, query, base)
    if method == "GET":
        if rec is None:
            raise _not_found(name, rg)
        return _ok(_uai_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _put_uai(state, sub, rg, rid, name, payload, method)
        return _ok(_uai_view(rec), 201 if created else 200, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        return _ok(None, 200, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("userAssignedIdentities", API_VERSION)]


def credential_count(rec):
    return len(rec.get("_fic") or {})
