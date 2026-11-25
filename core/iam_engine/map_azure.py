"""Azure request -> required RBAC action / dataAction.

`required(method, path, body=None, host=None, headers=None) -> [{"action","resource","data":bool}]`

ARM (control plane): `/subscriptions/{s}/resourceGroups/{rg}/providers/{Provider}/{type}[/{name}/{type}...][/{op}]`
  GET|HEAD -> <Provider>/<types>/read   PUT|PATCH -> write   DELETE -> delete   POST .../{op} -> <Provider>/<types>/{op}/action
  collection level (odd number of segments after the provider) -> read; nested types are joined with "/".
Data plane: Blob/Queue/Table (host `<acct>.<svc>.core.windows.net` or the simulator alias `/azure-data/<svc>/<acct>/...`),
  Key Vault, Service Bus, Cosmos DB, App Configuration -> dataActions.
The returned action uses the casing of core/iam_catalog/azure/*.json when the action exists there (RBAC matching is case-insensitive).
`resource` is the ARM scope/resource ID for control-plane requests and the data-plane resource path for data-plane requests.
Pure Python (json/re/os): Pyodide-safe."""
from __future__ import annotations

import glob
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAT = {}


def _catalog():
    if not _CAT:
        for f in glob.glob(os.path.join(_HERE, "..", "iam_catalog", "azure", "*.json")):
            d = json.load(open(f))
            for k in d.get("actions", {}):
                _CAT.setdefault(k.lower(), k)
            for k in d.get("dataActions", {}):
                _CAT.setdefault(k.lower(), k)
    return _CAT


def _canon(a):
    return _catalog().get(a.lower(), a)


def _out(action, resource, data=False, hint=None):
    e = {"action": _canon(action), "resource": resource, "data": data}
    if hint:
        e["hint"] = hint            # SAS-permission disambiguation the action alone cannot carry (list vs read, update vs process)
    return [e]


def _split(url):
    host = None
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)(.*)$", url or "", re.I)
    if m:
        host, url = m.group(1).split(":")[0].lower(), m.group(2) or "/"
    path, _, query = (url or "/").partition("?")
    q = {}
    for kv in query.split("&"):
        if kv:
            k, _, v = kv.partition("=")
            q[k.lower()] = v
    return host, path, q


_VERB = {"GET": "read", "HEAD": "read", "PUT": "write", "PATCH": "write", "DELETE": "delete", "POST": "write"}


def _arm(method, path):
    p = re.sub(r"/+$", "", path)
    low = p.lower()
    resource = p
    # tenant / subscription / resource-group level
    segs = [s for s in p.split("/") if s]
    lsegs = [s.lower() for s in segs]
    if not segs:
        return []
    ns_idx = None
    for i, s in enumerate(lsegs):
        if s == "providers":
            ns_idx = i                      # the LAST `providers` (extension resources nest them)
    verb = _VERB.get(method, "read")
    if ns_idx is None or ns_idx + 1 >= len(segs):
        if lsegs[0] == "subscriptions":
            rest = lsegs[2:] if len(lsegs) > 1 else []
            if len(lsegs) == 1 or (len(lsegs) == 2 and method in ("GET", "HEAD")):
                return _out("Microsoft.Resources/subscriptions/read", resource)
            if rest[:1] == ["resourcegroups"]:
                tail = rest[2:]
                base = "Microsoft.Resources/subscriptions/resourceGroups"
                if len(rest) == 1:                                    # list groups
                    return _out(base + "/read", resource)
                if not tail:                                          # the group itself
                    return _out("%s/%s" % (base, verb if method != "POST" else "write"), resource)
                if tail[0] == "deployments":
                    return _arm_provider(method, "Microsoft.Resources", ["deployments"] + segs[len(segs) - len(tail) + 1:], resource)
                if method == "POST" and len(tail) == 1:
                    return _out("%s/%s/action" % (base, segs[-1]), resource)
                return _out("%s/%s/%s" % (base, "/".join(t for t in tail[0::2]) if len(tail) > 2 else tail[0], verb), resource)
            if rest[:1] == ["deployments"]:
                return _arm_provider(method, "Microsoft.Resources", ["deployments"] + segs[3:], resource)
            if rest[:1] == ["locations"] and len(rest) == 1:
                return _out("Microsoft.Resources/subscriptions/locations/read", resource)
            if rest[:1] == ["resources"]:
                return _out("Microsoft.Resources/subscriptions/resources/read", resource)
            if rest[:1] == ["providers"] or rest[:1] == ["tagnames"] or rest[:1] == ["tags"]:
                return _out("Microsoft.Resources/subscriptions/%s/%s" % (rest[0] if rest[0] != "tagnames" else "tagNames", verb), resource)
        if lsegs[0] == "tenants":
            return _out("Microsoft.Resources/tenants/read", resource)
        return []
    ns = segs[ns_idx + 1]
    return _arm_provider(method, ns, segs[ns_idx + 2:], resource)


def _arm_provider(method, ns, rest, resource):
    types = rest[0::2]
    odd = len(rest) % 2 == 1
    if not rest:
        return _out("%s/read" % ns, resource)
    if method == "POST":
        if odd and len(rest) >= 1:
            op = rest[-1]
            tpath = "/".join(rest[0:-1][0::2])
            if not tpath:                                   # provider-level POST (checkNameAvailability, listKeys ...)
                if op.lower().startswith(("check", "validate")) and op.lower().startswith("checkname"):
                    return _out("%s/%s/read" % (ns, op), resource)
                return _out("%s/%s/action" % (ns, op), resource)
            return _out("%s/%s/%s/action" % (ns, tpath, op), resource)
        return _out("%s/%s/write" % (ns, "/".join(types)), resource)
    verb = _VERB.get(method, "read")
    if odd and verb != "read":                              # PUT/DELETE on a bare collection: still the type
        pass
    return _out("%s/%s/%s" % (ns, "/".join(types), verb), resource)


# ----------------------------------------------------------------------------------------------- data plane
_ALIAS = re.compile(r"^/azure-data/(blob|queue|table|keyvault|vault|servicebus|cosmos|appconfig|openai)/([^/]+)(/.*)?$", re.I)
_HOST = (("blob.core.windows.net", "blob"), ("queue.core.windows.net", "queue"), ("table.core.windows.net", "table"),
         ("vault.azure.net", "keyvault"), ("servicebus.windows.net", "servicebus"), ("documents.azure.com", "cosmos"),
         ("azconfig.io", "appconfig"), ("openai.azure.com", "openai"), ("cognitiveservices.azure.com", "openai"))
_SA = "Microsoft.Storage/storageAccounts/"


_ROOT_ALIAS = re.compile(r"^/azure-data/(queue-core|tableroot)(/.*)?$", re.I)
_HOST_LABEL = re.compile(r"^([a-z0-9][a-z0-9-]*)\.(?:queue|table)\.", re.I)
_SHARED = re.compile(r"^\s*SharedKey(?:Lite)?\s+([^:\s]+):", re.I)
DEFAULT_ACCOUNT = "_default"


def _data_target(host, path, headers=None):
    m = _ALIAS.match(path)
    if m:
        k = m.group(1).lower()
        return ("keyvault" if k == "vault" else k), m.group(2), m.group(3) or "/"
    m = _ROOT_ALIAS.match(path)
    if m:                                           # the root Storage wire (v4 console / Nano / host-style SDK): the account is NOT in the path
        hm = _HOST_LABEL.match(host or "")
        sk = _SHARED.match(str((headers or {}).get("authorization") or ""))
        acct = hm.group(1).lower() if hm else (sk.group(1).lower() if sk else DEFAULT_ACCOUNT)
        return ("queue" if m.group(1).lower() == "queue-core" else "table"), acct, m.group(2) or "/"
    for suffix, kind in _HOST:
        if host and host.endswith(suffix):
            return kind, host.split(".")[0], path
    return None, None, path


_BL = "Microsoft.Storage/storageAccounts/blobServices/containers"


def _blob(method, path, q, h, acct):
    """Blob data-plane permissions, each carrying the ABAC attribute context the request determines (role-assignment conditions reference
    @Resource[...containers:name], ...blobs:path, @Request[...blobs:prefix|snapshot|versionId|encryptionScopeName] and @Environment)."""
    out = _blob_perms(method, path, q, h, acct)
    parts = [s for s in path.split("/") if s]
    if acct and parts and parts[0] == acct and "." not in (h or ""):
        parts = parts[1:]
    if not parts or not out:
        return out
    hdr = {str(k).lower(): v for k, v in (h or {}).items()} if isinstance(h, dict) else {}
    qq = q if isinstance(q, dict) else {}
    res = {_BL + ":name": parts[0]}
    if len(parts) > 1:
        res[_BL + "/blobs:path"] = "/".join(parts[1:])
    req = {}
    for src, key in (("prefix", "prefix"), ("snapshot", "snapshot"), ("versionid", "versionId")):
        if qq.get(src):
            req[_BL + "/blobs:" + key] = qq[src]
    if hdr.get("x-ms-encryption-scope"):
        req[_BL + "/blobs:encryptionScopeName"] = hdr["x-ms-encryption-scope"]
    for e in out:
        e["context"] = {"resource": res, "request": req}
    return out


def _blob_perms(method, path, q, h, acct):
    parts = [s for s in path.split("/") if s]
    if acct and parts and parts[0] == acct and "." not in (h or ""):
        parts = parts[1:]
    c = _SA + "blobServices/containers"
    if not parts:
        return _out(c + "/read", "/" + acct, True, "list") if q.get("comp") == "list" else []
    cont = parts[0]
    res = "/%s/%s" % (acct, "/".join(parts))
    if len(parts) == 1:                                    # container
        if q.get("comp") == "list":
            return _out(c + "/blobs/read", res, True, "list")
        if method == "DELETE":
            return _out(c + "/delete", res, True)
        if method in ("PUT", "POST") and q.get("comp") in (None, "metadata", "acl", "lease"):
            return _out(c + "/write", res, True)
        return _out(c + "/read", res, True)
    bl = c + "/blobs"
    comp = q.get("comp", "")
    if method in ("GET", "HEAD"):
        return _out(bl + "/tags/read" if comp == "tags" else bl + "/read", res, True)
    if method == "DELETE":
        return _out(bl + "/delete", res, True)
    if comp == "tags":
        return _out(bl + "/tags/write", res, True)
    hdr = {k.lower(): v for k, v in (h or {}).items()}
    if comp == "appendblock" or (hdr.get("x-ms-blob-type", "").lower() == "appendblob"):
        return _out(bl + "/add/action", res, True)
    return _out(bl + "/write", res, True)


def _queue(method, path, q, acct):
    parts = [s for s in path.split("/") if s]
    base = _SA + "queueServices/queues"
    res = "/%s/%s" % (acct, "/".join(parts))
    if not parts:
        return _out(base + "/read", res, True)
    if len(parts) == 1:
        return _out(base + ("/delete" if method == "DELETE" else "/write" if method in ("PUT", "POST") else "/read"), res, True)
    if len(parts) == 2 and parts[1] == "messages":
        if method == "POST":
            return _out(base + "/messages/add/action", res, True)
        if method == "DELETE":
            return _out(base + "/messages/delete", res, True)
        if q.get("peekonly", "").lower() == "true":
            return _out(base + "/messages/read", res, True)
        return _out(base + "/messages/process/action", res, True)
    if len(parts) >= 3:
        return _out(base + ("/messages/delete" if method == "DELETE" else "/messages/process/action"), res, True, "update" if method == "PUT" else None)
    return _out(base + "/read", res, True)


def _table(method, path, q, acct):
    p = path.strip("/")
    res = "/%s/%s" % (acct, p)
    base = _SA + "tableServices/tables"
    if p.lower() == "tables":
        return _out(base + ("/write" if method == "POST" else "/read"), res, True)
    if p.lower().startswith("tables("):
        return _out(base + ("/delete" if method == "DELETE" else "/read"), res, True)
    if method in ("GET", "HEAD"):
        return _out(base + "/entities/read", res, True)
    if method == "POST":
        return _out(base + "/entities/add/action", res, True)
    if method in ("MERGE", "PATCH"):
        return _out(base + "/entities/update/action", res, True)
    if method == "DELETE":
        return _out(base + "/entities/delete", res, True)
    return _out(base + "/entities/write", res, True)


def _keyvault(method, path, vault):
    parts = [s for s in path.split("/") if s]
    res = "/vaults/%s%s" % (vault, path if path != "/" else "")
    if not parts:
        return []
    kind = parts[0].lower()
    ns = "Microsoft.KeyVault/vaults/"
    if kind in ("deletedsecrets", "deletedkeys", "deletedcertificates"):
        kind = kind[len("deleted"):]
        if method == "DELETE":
            return _out(ns + kind + "/purge/action", res, True)
        if len(parts) > 2 and parts[-1].lower() == "recover":
            return _out(ns + kind + "/recover/action", res, True)
        return _out(ns + kind + "/read" if kind != "secrets" else ns + "secrets/readMetadata/action", res, True)
    if kind not in ("secrets", "keys", "certificates"):
        return []
    op = parts[2].lower() if len(parts) > 2 else ""
    if kind == "secrets":
        if method == "DELETE":
            return _out(ns + "secrets/delete", res, True)
        if len(parts) == 1 or op in ("versions",):
            return _out(ns + "secrets/readMetadata/action", res, True)
        if method == "GET":
            return _out(ns + "secrets/getSecret/action", res, True)
        if method == "PUT":
            return _out(ns + "secrets/setSecret/action", res, True)
        if method == "PATCH":
            return _out(ns + "secrets/update/action", res, True)
        if parts[-1].lower() in ("backup", "restore", "recover"):
            return _out(ns + "secrets/%s/action" % parts[-1].lower(), res, True)
        return _out(ns + "secrets/setSecret/action", res, True)
    if method == "DELETE":
        return _out(ns + kind + "/delete", res, True)
    opmap = {"create": "create", "import": "import", "sign": "sign", "verify": "verify", "encrypt": "encrypt", "decrypt": "decrypt",
             "wrapkey": "wrap", "unwrapkey": "unwrap", "backup": "backup", "restore": "restore", "rotate": "rotate",
             "recover": "recover", "release": "release", "pending": None, "issuers": None, "contacts": None}
    if method == "POST" and len(parts) >= 2:
        o = parts[-1].lower()
        if o in opmap and opmap[o]:
            return _out(ns + "%s/%s/action" % (kind, opmap[o]), res, True)
        if o == "restore":
            return _out(ns + "%s/restore/action" % kind, res, True)
    if method == "PUT" and kind == "keys":
        return _out(ns + "keys/import/action", res, True)
    if method == "PUT" and kind == "certificates" and len(parts) >= 3 and parts[2].lower() == "pending":
        return _out(ns + "certificates/update/action", res, True)
    if method in ("PATCH",):
        return _out(ns + kind + "/update/action", res, True)
    if method == "POST" and kind == "certificates":
        return _out(ns + "certificates/create/action", res, True)
    return _out(ns + kind + "/read", res, True)


def _servicebus(method, path, ns):
    parts = [s for s in path.split("/") if s]
    res = "/namespaces/%s%s" % (ns, path)
    last = parts[-1].lower() if parts else ""
    if method == "POST" and last != "head":
        return _out("Microsoft.ServiceBus/namespaces/messages/send/action", res, True)
    if last in ("head",) or "messages/head" in path.lower() or (parts and parts[-1].lower() == "messages" and method in ("DELETE",)):
        return _out("Microsoft.ServiceBus/namespaces/messages/receive/action", res, True)
    if method in ("GET", "DELETE") and len(parts) >= 3 and parts[-2].lower() == "messages":
        return _out("Microsoft.ServiceBus/namespaces/messages/receive/action", res, True)
    if method == "POST":
        return _out("Microsoft.ServiceBus/namespaces/messages/receive/action", res, True)
    return []


def _cosmos(method, path, hdr, acct):
    base = "Microsoft.DocumentDB/databaseAccounts/"
    parts = [s for s in path.split("/") if s]
    res = "/databaseAccounts/%s%s" % (acct, path)
    if not parts or parts[0] in ("dbs",) and "docs" not in parts and "sprocs" not in parts:
        return _out(base + "readMetadata", res, True)
    if "docs" in parts:
        i = parts.index("docs")
        item = base + "sqlDatabases/containers/items/"
        if len(parts) == i + 1:
            if method == "POST":
                if hdr.get("x-ms-documentdb-isquery", "").lower() == "true" or "query+json" in hdr.get("content-type", ""):
                    return _out(base + "sqlDatabases/containers/executeQuery", res, True)
                if hdr.get("x-ms-documentdb-is-upsert", "").lower() == "true":
                    return _out(item + "upsert", res, True)
                return _out(item + "create", res, True)
            return _out(item + "read", res, True)
        return _out(item + ("delete" if method == "DELETE" else "replace" if method == "PUT" else "read"), res, True)
    if "sprocs" in parts and method == "POST" and len(parts) > parts.index("sprocs") + 1:
        return _out(base + "sqlDatabases/containers/executeStoredProcedure", res, True)
    return _out(base + "readMetadata", res, True)


def _appconfig(method, path, store):
    parts = [s for s in path.split("/") if s]
    res = "/configurationStores/%s%s" % (store, path)
    kind = parts[0].lower() if parts else ""
    base = "Microsoft.AppConfiguration/configurationStores/"
    if kind in ("kv", "keys", "labels", "revisions", "locks"):
        if kind == "kv" and method in ("PUT", "POST"):
            return _out(base + "keyValues/write", res, True)
        if kind == "kv" and method == "DELETE":
            return _out(base + "keyValues/delete", res, True)
        if kind == "locks":
            return _out(base + "keyValues/write", res, True)
        return _out(base + "keyValues/read", res, True)
    if kind == "snapshots":
        if method == "POST":
            return _out(base + "snapshots/archive/action", res, True)
        return _out(base + "snapshots/" + ("write" if method in ("PUT", "PATCH") else "read"), res, True)
    return []


# ----------------------------------------------------------------------------------------------- Azure OpenAI data plane
# Data actions of Microsoft.CognitiveServices/accounts/OpenAI/* (verbatim from the catalog). The account is the resource
# (`/cognitiveservices/<account>`, inherited from the ARM account via state["data_scopes"]); the simulator's `/openai/...` has no
# account in the path, so the host adapter resolves it (key / deployment) and passes it as the `x-vyomi-data-account` header.
_OAI = "Microsoft.CognitiveServices/accounts/OpenAI/"
_OAI_OP = {"chat/completions": "deployments/chat/completions/action", "completions": "deployments/completions/action",
           "embeddings": "deployments/embeddings/action", "images/generations": "images/generations/action",
           "moderations": "moderations/action", "extensions/chat/completions": "deployments/extensions/chat/completions/action",
           "realtime": "deployments/realtime/action"}
_OAI_TOP = {"responses": "responses", "files": "files", "fine_tuning": "fine-tunes", "fine-tunes": "fine-tunes", "evals": "evals",
            "assistants": "assistants", "vector_stores": "assistants/vector_stores", "threads": "assistants/threads",
            "batches": "batches", "stored-completions": "stored-completions"}


def _rw(method, base):
    return "%s/%s" % (base, {"GET": "read", "HEAD": "read", "DELETE": "delete"}.get(method, "write"))


def _openai(method, path, acct):
    p = re.sub(r"^/(?:azure-openai|openai)(?=/|$)", "", path.split("?", 1)[0], flags=re.I)
    p = re.sub(r"^/openai(?=/|$)", "", p, flags=re.I)            # /azure-openai/openai/... and /azure-data/openai/<acct>/openai/...
    p = re.sub(r"^/v1(?=/|$)", "", p)
    segs = [x for x in p.split("/") if x]
    res = "/cognitiveservices/" + (acct or "_")
    if not segs:
        return _out(_OAI + "models/read", res, True)
    if segs[0] == "deployments":
        if len(segs) == 1 or (len(segs) == 2 and method != "POST"):
            return _out(_OAI + _rw(method, "deployments"), res, True)
        tail = "/".join(segs[2:])
        if tail.startswith("audio"):
            return _out(_OAI + "deployments/audio/action", res, True)
        if tail in _OAI_OP:
            return _out(_OAI + _OAI_OP[tail], res, True)
        return _out(_OAI + _rw(method, "deployments"), res, True)
    head = segs[0]
    if head == "models":
        return _out(_OAI + "models/read", res, True)
    if head in ("chat", "completions", "embeddings", "images", "moderations", "audio", "realtime"):
        tail = "/".join(segs)
        if tail.startswith("audio"):
            return _out(_OAI + "deployments/audio/action", res, True)
        return _out(_OAI + _OAI_OP.get(tail, "deployments/" + head + "/action"), res, True)
    base = _OAI_TOP.get(head)
    if not base:
        return []
    if head == "threads" or head == "assistants" or head == "vector_stores":
        rest = segs[1:]
        if head == "threads":
            for key, name in (("runs", "runs"), ("messages", "messages")):
                if key in rest:
                    nested = "/".join(["runs", "steps"] if "steps" in rest else [name])
                    base = "assistants/threads/" + nested
                    break
        elif head == "vector_stores":
            for key in ("file_batches", "files"):
                if key in rest:
                    base = "assistants/vector_stores/" + key
                    break
    if head == "batches" and segs[-1] == "cancel":
        return _out(_OAI + "batches/cancel/action", res, True)
    if head == "batches" and method == "POST":
        return _out(_OAI + "batches/action", res, True)
    if head == "evals" and method == "DELETE":
        return _out(_OAI + "evals/write", res, True)
    return _out(_OAI + _rw(method, base), res, True)


# ----------------------------------------------------------------------------------------------- Azure SQL (`/azure-sql/...`)
# The simulator's SQL data plane (query / security / mirror / recommendations) has no vendor dataAction: a T-SQL connection is
# authorized by SQL or Entra logins, not Azure RBAC. What a caller can do through the simulator's HTTP surface is administer the
# server/database, so it maps to the Microsoft.Sql control plane: GET -> read, PUT/POST (create, query, apply, sync) -> write,
# DELETE -> delete, on servers/databases of the ARM server (`/sql/<server>`, inherited from the ARM resource).
def _azure_sql(method, path):
    segs = [x for x in re.sub(r"^/azure-sql", "", path.split("?", 1)[0], flags=re.I).split("/") if x]
    if len(segs) < 2 or segs[0].lower() != "servers":
        return []
    res = "/sql/" + segs[1]
    typ = "Microsoft.Sql/servers/databases" if len(segs) > 2 and segs[2].lower() == "databases" else "Microsoft.Sql/servers"
    verb = {"GET": "read", "HEAD": "read", "DELETE": "delete"}.get(method, "write")
    if typ.endswith("databases") and len(segs) == 5 and segs[4] in ("query", "queryinsights") and method == "POST":
        verb = "read"                                    # a SELECT-style query is the closest thing to a read
    return _out("%s/%s" % (typ, verb), res)


def _strip_wire(path):
    p = path
    for pre in ("/nano/_wire", "/_wire"):
        if p == pre or p.startswith(pre + "/"):
            p = p[len(pre):] or "/"
            break
    return re.sub(r"^/arm(?=/(?:subscriptions|providers|tenants)(?:/|$))", "", p, flags=re.I) or "/"


def required(method, path, body=None, host=None, headers=None):
    method = (method or "GET").upper()
    h, p, q = _split(path)
    p = _strip_wire(p)                     # /_wire/arm/subscriptions/.. and /_wire/subscriptions/.. are the same ARM request
    host = host or h
    hdr = {k.lower(): v for k, v in (headers or {}).items()}
    if re.match(r"^/(?:openai|azure-openai)(?:/|$)", p, re.I):
        acct = hdr.get("x-vyomi-data-account")
        if not acct and host and host.endswith(("openai.azure.com", "cognitiveservices.azure.com")):
            acct = host.split(".")[0]
        m = re.match(r"^/azure-openai/([^/]+)(/openai(?:/.*)?)$", p, re.I)      # /azure-openai/<account>/openai/...
        if m:
            acct, p = m.group(1), m.group(2)
        return _openai(method, p, acct)
    if re.match(r"^/azure-sql(?:/|$)", p, re.I):
        return _azure_sql(method, p)
    kind, acct, dpath = _data_target(host, p, hdr)
    if kind == "openai":
        return _openai(method, dpath, acct)
    if kind:
        if kind == "blob":
            return _blob(method, dpath, q, headers, acct)
        if kind == "queue":
            return _queue(method, dpath, q, acct)
        if kind == "table":
            return _table(method, dpath, q, acct)
        if kind == "keyvault":
            return _keyvault(method, dpath, acct)
        if kind == "servicebus":
            return _servicebus(method, dpath, acct)
        if kind == "cosmos":
            return _cosmos(method, dpath, hdr, acct)
        if kind == "appconfig":
            return _appconfig(method, dpath, acct)
    if p.startswith("/subscriptions") or p.startswith("/providers") or p.startswith("/tenants"):
        return _arm(method, p)
    return []
