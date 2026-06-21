"""Azure data planes for the CloudLearn simulator.

Control-plane (ARM) resources are metadata; this module gives them *behaviour*:

* **Blob** — a sim-native implementation of the Azure Blob REST contract
  (containers + block blobs, real bytes) under ``/azure-data/blob/{account}/``.
  SharedKey auth is HMAC over HTTP, so unmodified ``azblob`` SDK / ``az storage``
  clients work; the sim ignores the signature (same philosophy as S3 SigV4).
* **SQL** — each ``Microsoft.Sql/servers/databases`` is backed by a real
  database on the running PostgreSQL engine (reusing ``gcp_sql_engine``), so an
  app can connect over the normal wire protocol. (Azure SQL's native protocol is
  TDS; we surface Postgres instead — a simulator simplification.)
* **Service Bus** — an in-process queue/topic broker exposed over a small REST
  surface for HTTP/curl clients. (The real SDK speaks AMQP, which a REST sim
  can't serve without the heavy official emulator.)
* **Cosmos DB** — a sim-native subset of the Cosmos SQL REST API
  (databases/containers/documents) backed by an in-proc store.

All planes ignore credentials and never raise into the control plane.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import time
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response, PlainTextResponse

def _sid() -> str:
    """Active space id (data planes are space-scoped like the control plane).
    Falls back to "global" when no space is active."""
    try:
        import server
        return server._spaces_state().get("active_space_id", "") or "global"
    except Exception:
        return "global"


# ----------------------------------------------------------------------------
# Blob store
# ----------------------------------------------------------------------------
# (space, account) -> {"containers": {name: {...}}, "blobs": {(container,blob): {...}}}
_blob: dict[str, dict] = {}


def _account(sid: str, acct: str) -> dict:
    return _blob.setdefault(sid + "|" + acct, {"containers": {}, "blobs": {}})


def _http_date() -> str:
    return email.utils.formatdate(usegmt=True)


def _etag() -> str:
    return '"0x%s"' % uuid.uuid4().hex[:16].upper()


def _blob_headers(extra: dict | None = None) -> dict:
    h = {"x-ms-version": "2023-11-03", "x-ms-request-id": uuid.uuid4().hex,
         "Date": _http_date(), "Server": "CloudLearn-Azurite/1.0"}
    if extra:
        h.update(extra)
    return h


def _xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


async def _blob_handle(account: str, rest: str, request: Request) -> Response:
    # Storage goes through the backend-aware helpers below (put_blob_bytes /
    # get_blob_rec / list_blobs / ...), which use Azurite when configured and
    # the in-process store otherwise. This handler only shapes the Azure Blob
    # REST request/response — it never touches the backing store directly.
    method = request.method.upper()
    qp = request.query_params
    rest = rest or ""

    # ----- account level: GET ?comp=list -> list containers -----
    if rest == "":
        if method == "GET" and qp.get("comp") == "list":
            items = "".join(
                f"<Container><Name>{_xml_escape(c['name'])}</Name><Properties>"
                f"<Last-Modified>{c.get('created') or _http_date()}</Last-Modified><Etag>{_etag()}</Etag>"
                f"<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
                f"</Properties></Container>"
                for c in list_containers(account))
            xml = ('<?xml version="1.0" encoding="utf-8"?>'
                   f'<EnumerationResults><Containers>{items}</Containers><NextMarker /></EnumerationResults>')
            return Response(content=xml, media_type="application/xml", headers=_blob_headers())
        return Response(status_code=400, content="", headers=_blob_headers())

    parts = rest.split("/", 1)
    container = parts[0]
    blob = parts[1] if len(parts) > 1 else None

    # ----- container level -----
    if blob is None or blob == "":
        if method == "GET" and qp.get("comp") == "list":  # list blobs (restype=container present)
            prefix = qp.get("prefix", "")
            rows = ""
            for o in list_blobs(account, container, prefix):
                rows += (f"<Blob><Name>{_xml_escape(o['name'])}</Name><Properties>"
                         f"<Last-Modified>{o['lastModified']}</Last-Modified><Etag>{o['etag']}</Etag>"
                         f"<Content-Length>{o['size']}</Content-Length>"
                         f"<Content-Type>{_xml_escape(o['contentType'])}</Content-Type>"
                         f"<BlobType>BlockBlob</BlobType>"
                         f"<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
                         f"</Properties></Blob>")
            xml = ('<?xml version="1.0" encoding="utf-8"?>'
                   f'<EnumerationResults ContainerName="{_xml_escape(container)}">'
                   f'<Blobs>{rows}</Blobs><NextMarker /></EnumerationResults>')
            return Response(content=xml, media_type="application/xml", headers=_blob_headers())
        if qp.get("restype") == "container":
            if method == "PUT":
                if container_exists(account, container):
                    return Response(status_code=409, content="", headers=_blob_headers(
                        {"x-ms-error-code": "ContainerAlreadyExists"}))
                create_container(account, container)
                return Response(status_code=201, content="", headers=_blob_headers(
                    {"ETag": _etag(), "Last-Modified": _http_date()}))
            if method == "DELETE":
                delete_container(account, container)
                return Response(status_code=202, content="", headers=_blob_headers())
            if method in ("GET", "HEAD"):  # get container properties
                if not container_exists(account, container):
                    return Response(status_code=404, content="", headers=_blob_headers(
                        {"x-ms-error-code": "ContainerNotFound"}))
                return Response(status_code=200, content="", headers=_blob_headers(
                    {"ETag": _etag(), "Last-Modified": _http_date()}))
        return Response(status_code=400, content="", headers=_blob_headers())

    # ----- blob level -----
    if method == "PUT":
        body = await request.body()
        ct = request.headers.get("content-type") or request.headers.get("x-ms-blob-content-type") or "application/octet-stream"
        meta = {k[len("x-ms-meta-"):]: v for k, v in request.headers.items() if k.lower().startswith("x-ms-meta-")}
        rec = put_blob_bytes(account, container, blob, body, ct, meta)
        md5 = hashlib.md5(body).digest()
        import base64
        return Response(status_code=201, content="", headers=_blob_headers({
            "ETag": rec["etag"], "Last-Modified": rec["mtime"],
            "Content-MD5": base64.b64encode(md5).decode(),
            "x-ms-request-server-encrypted": "true"}))
    if method in ("GET", "HEAD"):
        if method == "HEAD":
            p = blob_props_rec(account, container, blob)
            if not p:
                return Response(status_code=404, content="", headers=_blob_headers(
                    {"x-ms-error-code": "BlobNotFound"}))
            hdrs = _blob_headers({
                "ETag": p["etag"], "Last-Modified": p["mtime"],
                "Content-Length": str(p["size"]), "Accept-Ranges": "bytes",
                "x-ms-blob-type": "BlockBlob", "x-ms-creation-time": p["mtime"]})
            for mk, mv in (p.get("meta") or {}).items():
                hdrs["x-ms-meta-" + mk] = mv
            return Response(status_code=200, content=b"", media_type=p["ct"], headers=hdrs)
        g = get_blob_rec(account, container, blob)
        if not g:
            return Response(status_code=404, content="", headers=_blob_headers(
                {"x-ms-error-code": "BlobNotFound"}))
        hdrs = _blob_headers({
            "ETag": g["etag"], "Last-Modified": g["mtime"],
            "Content-Length": str(len(g["data"])), "Accept-Ranges": "bytes",
            "x-ms-blob-type": "BlockBlob", "x-ms-creation-time": g["mtime"]})
        for mk, mv in (g.get("meta") or {}).items():
            hdrs["x-ms-meta-" + mk] = mv
        return Response(content=g["data"], media_type=g["ct"], headers=hdrs)
    if method == "DELETE":
        existed = delete_blob(account, container, blob)
        return Response(status_code=202 if existed else 404, content="", headers=_blob_headers())
    return Response(status_code=405, content="", headers=_blob_headers())


def storage_keys(account: str) -> dict:
    """Deterministic SharedKey for an account (used by listKeys ARM action). The
    blob plane ignores the signature, so any stable key works for clients."""
    import base64
    seed = hashlib.sha256(("cloudlearn-azure-" + account).encode()).digest()
    val = base64.b64encode(seed).decode()
    return {"keys": [
        {"keyName": "key1", "value": val, "permissions": "FULL"},
        {"keyName": "key2", "value": base64.b64encode(seed[::-1]).decode(), "permissions": "FULL"},
    ]}


# ----------------------------------------------------------------------------
# SQL (real Postgres via gcp_sql_engine)
# ----------------------------------------------------------------------------
def _sql_server_from_id(rid: str) -> str:
    parts = rid.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "servers" and i + 1 < len(parts):
            return parts[i + 1]
    return "sqlserver"


def on_create(full_type: str, rec: dict, base: str) -> None:
    ft = full_type.lower()
    # Microsoft.Compute/virtualMachines → back with a REAL LXD/multipass
    # container (parity with AWS EC2 and GCP Compute, which already do this).
    # Container size is tier-mapped from the chosen vmSize against the host
    # budget so even huge SKUs (Standard_M128ms) don't crush the host.
    if ft == "microsoft.compute/virtualmachines":
        try:
            import server as _srv
            _srv.provision_azure_vm_runtime(rec)
            # MVP P0-2: push the Azure VM into CloudSim Plus so the per-space
            # cloudsim summary reflects Azure compute (parity with EC2 + GCE).
            _srv._cloudsim_sync_azure_vm_resource(rec, "upsert")
        except Exception as exc:
            # Never break the ARM control plane — but DON'T hide the failure
            # either. Surface it on the record so a VM that fails to attach LXD
            # shows *why*, instead of looking like a silent metadata-only VM.
            try:
                _rt = rec.setdefault("properties", {}).setdefault("runtime", {})
                if isinstance(_rt, dict) and not _rt.get("containerName"):
                    _rt.setdefault("status", "provision_error")
                    _rt.setdefault("error", str(exc)[:200])
            except Exception:
                pass
        # After VM provisioning, reconcile NSG rules so new VMs pick up any
        # existing security rules (parity with GCP VPC reconcile-on-create).
        try:
            from routes.azure_console import _azure_nsg_reconcile
            _azure_nsg_reconcile()
        except Exception:
            pass
        return
    # When an NSG or security rule is created/updated, reconcile all VMs.
    if ft in ("microsoft.network/networksecuritygroups",
              "microsoft.network/networksecuritygroups/securityrules"):
        try:
            from routes.azure_console import _azure_nsg_reconcile
            _azure_nsg_reconcile()
        except Exception:
            pass
        return
    if ft == "microsoft.sql/servers/databases":
        try:
            from core import gcp_sql_engine as eng
            if not eng.available("postgres"):
                rec.setdefault("properties", {})["dataPlane"] = "metadata-only (no Postgres engine)"
                return
            server = _sql_server_from_id(rec["id"])
            dbname = rec["name"]
            conn = eng.provision(_sid(), server, dbname, "POSTGRES_16",
                                 user="azureadmin", password="Password123!",
                                 request_host=base)
            rec.setdefault("properties", {})
            rec["properties"]["status"] = "Online"
            rec["properties"]["connectionInfo"] = {
                "engine": "PostgreSQL (simulator-backed)",
                "host": conn["host"], "port": conn["port"], "database": conn["database"],
                "user": conn["user"], "password": conn["password"],
                "connectionString": (f"host={conn['host']} port={conn['port']} "
                                     f"dbname={conn['database']} user={conn['user']} "
                                     f"password={conn['password']}"),
            }
        except Exception as exc:  # never break the control plane
            rec.setdefault("properties", {})["dataPlane"] = f"metadata-only ({exc})"


def on_delete(full_type: str, rec: dict) -> None:
    ft = full_type.lower()
    if ft == "microsoft.compute/virtualmachines":
        try:
            import server as _srv
            _srv.deprovision_azure_vm_runtime(rec)
            # MVP P0-2: clean up the CloudSim Plus VM record.
            _srv._cloudsim_sync_azure_vm_resource(rec, "delete")
        except Exception:
            pass
        return
    if ft == "microsoft.sql/servers/databases":
        try:
            from core import gcp_sql_engine as eng
            server = _sql_server_from_id(rec["id"])
            eng.deprovision(_sid(), server, rec["name"], "POSTGRES_16")
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Service Bus (in-proc REST broker)
# ----------------------------------------------------------------------------
# (space, namespace, entity) -> list[ {id, body, ct, enqueued} ]
_sb: dict[tuple, list] = {}


def _sb_q(sid: str, ns: str, entity: str) -> list:
    return _sb.setdefault((sid, ns, entity), [])


async def _sb_handle(namespace: str, rest: str, request: Request) -> Response:
    method = request.method.upper()
    sid = _sid()
    segs = [s for s in (rest or "").split("/") if s]
    # {entity}/messages         POST -> send
    # {entity}/messages/head    DELETE -> receive&delete ; GET -> peek
    if len(segs) >= 2 and segs[1] == "messages":
        entity = segs[0]
        q = _sb_q(sid, namespace, entity)
        head = len(segs) >= 3 and segs[2] == "head"
        if method == "POST" and not head:
            body = (await request.body()).decode("utf-8", "replace")
            msg = {"messageId": uuid.uuid4().hex, "body": body,
                   "ct": request.headers.get("content-type", "text/plain"),
                   "enqueuedTimeUtc": _http_date()}
            q.append(msg)
            return JSONResponse(status_code=201, content={"messageId": msg["messageId"], "queued": len(q)})
        if head and method in ("DELETE", "GET"):
            if not q:
                return Response(status_code=204, content="")
            msg = q[0] if method == "GET" else q.pop(0)
            return JSONResponse(content=msg, headers={"BrokerProperties": json.dumps(
                {"MessageId": msg["messageId"], "EnqueuedTimeUtc": msg["enqueuedTimeUtc"]})})
    if method == "GET" and len(segs) == 1:  # entity stats
        entity = segs[0]
        return JSONResponse(content={"entity": entity, "namespace": namespace,
                                     "activeMessageCount": len(_sb_q(sid, namespace, entity))})
    return JSONResponse(status_code=400, content={"error": "unsupported Service Bus REST op"})


# ----------------------------------------------------------------------------
# Cosmos DB (sim-native SQL REST subset)
# ----------------------------------------------------------------------------
# (space, account) -> {db: {coll: {docId: doc}}}
_cosmos: dict[tuple, dict] = {}


def _cos_acct(sid: str, a: str) -> dict:
    return _cosmos.setdefault((sid, a), {})


async def _cosmos_handle(account: str, rest: str, request: Request) -> Response:
    method = request.method.upper()
    segs = [s for s in (rest or "").split("/") if s]
    acct = _cos_acct(_sid(), account)
    try:
        import os
        if os.environ.get("CLOUDLEARN_COSMOS_DEBUG"):
            import sys
            print(f"[cosmos] {method} /{rest}", file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        # ----- DatabaseAccount (gateway bootstrap): GET / -----
        if not segs:
            if method in ("GET", "HEAD"):
                return JSONResponse(_cos_db_account(request))
            return JSONResponse(status_code=400, content={"error": "unsupported root op"})

        if segs[0] == "dbs":
            # ----- /dbs : list + create database -----
            if len(segs) == 1:
                if method == "GET":
                    items = [dict({"id": d}, **_cos_meta(_rid_db(d), f"dbs/{d}/",
                                  {"_colls": "colls/", "_users": "users/"})) for d in acct]
                    return JSONResponse({"_rid": "", "Databases": items, "_count": len(items)})
                if method == "POST":
                    body = await _json(request); did = body.get("id")
                    acct.setdefault(did, {})
                    return JSONResponse(status_code=201, content=dict({"id": did},
                            **_cos_meta(_rid_db(did), f"dbs/{did}/", {"_colls": "colls/", "_users": "users/"})))
            db = _resolve_db(acct, segs[1])
            # ----- /dbs/{db} : read / replace / delete database -----
            if len(segs) == 2:
                if method in ("GET", "HEAD"):
                    return (JSONResponse(dict({"id": db}, **_cos_meta(_rid_db(db), f"dbs/{db}/",
                            {"_colls": "colls/", "_users": "users/"}))) if db in acct else _cos_404())
                if method == "PUT":
                    acct.setdefault(db, {})
                    return JSONResponse(status_code=201, content=dict({"id": db},
                            **_cos_meta(_rid_db(db), f"dbs/{db}/")))
                if method == "DELETE":
                    acct.pop(db, None); return Response(status_code=204, content="")
            if len(segs) >= 3 and segs[2] == "colls":
                dbo = acct.setdefault(db, {})
                # ----- /dbs/{db}/colls : list + create container -----
                if len(segs) == 3:
                    if method == "GET":
                        items = [dict({"id": c}, **_cos_meta(_rid_coll(db, c), f"dbs/{db}/colls/{c}/",
                                      {"_docs": "docs/"})) for c in dbo]
                        return JSONResponse({"_rid": "", "DocumentCollections": items, "_count": len(items)})
                    if method == "POST":
                        body = await _json(request); cid = body.get("id"); dbo.setdefault(cid, {})
                        pk = body.get("partitionKey") or {"paths": ["/id"], "kind": "Hash"}
                        return JSONResponse(status_code=201, content=dict(
                            {"id": cid, "partitionKey": pk,
                             "indexingPolicy": {"indexingMode": "consistent", "automatic": True}},
                            **_cos_meta(_rid_coll(db, cid), f"dbs/{db}/colls/{cid}/",
                                        {"_docs": "docs/", "_sprocs": "sprocs/", "_triggers": "triggers/",
                                         "_udfs": "udfs/", "_conflicts": "conflicts/"})))
                coll = _resolve_coll(dbo, db, segs[3])
                # ----- /dbs/{db}/colls/{coll} : read / replace / delete container -----
                if len(segs) == 4:
                    if method in ("GET", "HEAD"):
                        return (JSONResponse(dict({"id": coll, "partitionKey": {"paths": ["/id"], "kind": "Hash"}},
                                **_cos_meta(_rid_coll(db, coll), f"dbs/{db}/colls/{coll}/", {"_docs": "docs/"})))
                                if coll in dbo else _cos_404())
                    if method == "PUT":
                        dbo.setdefault(coll, {})
                        return JSONResponse(status_code=201, content=dict({"id": coll},
                                **_cos_meta(_rid_coll(db, coll), f"dbs/{db}/colls/{coll}/")))
                    if method == "DELETE":
                        dbo.pop(coll, None); return Response(status_code=204, content="")
                # ----- /dbs/{db}/colls/{coll}/pkranges : partition key ranges -----
                # The SDK fetches these to build its collection routing map. A
                # single-partition sim returns one range over the full hash space.
                if len(segs) == 5 and segs[4] == "pkranges":
                    if method in ("GET", "HEAD"):
                        pkr = dict({"id": "0", "minInclusive": "",
                                    "maxExclusive": "FF", "ridPrefix": 0,
                                    "throughputFraction": 1.0, "status": "online", "parents": []},
                                   **_cos_meta(_rid_pk(db, coll), f"dbs/{db}/colls/{coll}/pkranges/0/"))
                        return JSONResponse({"_rid": _rid_coll(db, coll),
                                             "PartitionKeyRanges": [pkr], "_count": 1})
                if len(segs) >= 5 and segs[4] == "docs":
                    docs = dbo.setdefault(coll, {})
                    # ----- /dbs/{db}/colls/{coll}/docs : create / list / query -----
                    if len(segs) == 5:
                        if method == "POST":
                            is_query = (request.headers.get("x-ms-documentdb-isquery", "").lower() == "true"
                                        or "query+json" in (request.headers.get("content-type", "").lower()))
                            body = await _json(request)
                            if is_query:
                                results = _cos_query(docs, body)
                                return JSONResponse({"_rid": "", "Documents": results, "_count": len(results)})
                            did = str(body.get("id") or uuid.uuid4().hex)
                            body["id"] = did
                            body.update(_cos_meta(_rid_doc(db, coll, did),
                                                  f"dbs/{db}/colls/{coll}/docs/{did}/"))
                            docs[did] = body
                            return JSONResponse(status_code=201, content=body)
                        if method == "GET":
                            return JSONResponse({"_rid": "", "Documents": list(docs.values()), "_count": len(docs)})
                    # ----- /dbs/{db}/colls/{coll}/docs/{id} : read / replace / delete -----
                    did = segs[5]
                    if method in ("GET", "HEAD"):
                        return JSONResponse(docs[did]) if did in docs else _cos_404()
                    if method == "PUT":
                        body = await _json(request); body["id"] = did
                        body.update(_cos_meta(_rid_doc(db, coll, did),
                                              f"dbs/{db}/colls/{coll}/docs/{did}/"))
                        docs[did] = body
                        return JSONResponse(content=body)
                    if method == "DELETE":
                        docs.pop(did, None); return Response(status_code=204, content="")
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(status_code=400, content={"error": "unsupported Cosmos REST op"})


def _cos_404():
    return JSONResponse(status_code=404, content={"code": "NotFound"})


async def _json(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


# --- Cosmos response envelopes (the SDK parses _rid/_self/_etag/_ts) ---------
# Cosmos resource ids (_rid) are hierarchical, fixed-width, base64-encoded byte
# strings: database=4 bytes, collection=8 (database's 4 + 4), document=16
# (collection's 8 + 8). The SDK's ResourceId parser rejects anything else
# ("INVALID resource id"). Derive them deterministically from the names so a
# resource keeps the same _rid across create/read.
def _cos_seed(seed: str, n: int) -> bytes:
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).digest()[:n]


def _b64(b: bytes) -> str:
    import base64
    # Keep base64 padding — the Cosmos SDK's ResourceId parser decodes the _rid
    # with a strict decoder and rejects unpadded strings ("INVALID resource id").
    return base64.b64encode(b).decode()


def _rid_db(db: str) -> str:
    return _b64(_cos_seed("db:" + db, 4))


def _rid_coll(db: str, coll: str) -> str:
    return _b64(_cos_seed("db:" + db, 4) + _cos_seed("coll:%s/%s" % (db, coll), 4))


def _rid_doc(db: str, coll: str, did: str) -> str:
    return _b64(_cos_seed("db:" + db, 4) + _cos_seed("coll:%s/%s" % (db, coll), 4)
                + _cos_seed("doc:%s/%s/%s" % (db, coll, did), 8))


def _rid_pk(db: str, coll: str, pk: str = "0") -> str:
    return _b64(_cos_seed("db:" + db, 4) + _cos_seed("coll:%s/%s" % (db, coll), 4)
                + _cos_seed("pk:%s/%s/%s" % (db, coll, pk), 8))


def _resolve_db(acct: dict, seg: str) -> str:
    """A path segment may be a database NAME or its _rid — map back to the name.
    The SDK switches to RID-based addressing after the first reads, and derives
    those rids in ways that don't always round-trip our deterministic rids, so
    fall back to the sole database when there's exactly one (the common case)."""
    if seg in acct:
        return seg
    for d in acct:
        if _rid_db(d) == seg:
            return d
    if len(acct) == 1:
        return next(iter(acct))
    return seg


def _resolve_coll(dbo: dict, db: str, seg: str) -> str:
    if seg in dbo:
        return seg
    for c in dbo:
        if _rid_coll(db, c) == seg or _b64(_cos_seed("coll:%s/%s" % (db, c), 4)) == seg:
            return c
    if len(dbo) == 1:
        return next(iter(dbo))
    return seg


def _cos_meta(rid: str, self_link: str, extra: dict | None = None) -> dict:
    m = {"_rid": rid, "_self": self_link,
         "_etag": '"%s"' % uuid.uuid4().hex, "_ts": int(time.time()),
         "_attachments": "attachments/"}
    if extra:
        m.update(extra)
    return m


def _cos_db_account(request: Request) -> dict:
    """The gateway bootstrap (DatabaseAccount) the SDK fetches on first use.

    The SDK re-dials writableLocations[].databaseAccountEndpoint for every
    subsequent request, so it MUST carry the external scheme + host + port. The
    TLS terminator (caddy) strips the port from the Host header, so fall back to
    X-Forwarded-Host / X-Forwarded-Port and the well-known appliance HTTPS port.
    """
    import os
    host = (request.headers.get("x-forwarded-host")
            or request.headers.get("host") or "localhost")
    if ":" not in host:
        port = (request.headers.get("x-forwarded-port")
                or os.environ.get("CLOUDLEARN_HTTPS_PORT") or "9443")
        host = host + ":" + str(port)
    scheme = request.headers.get("x-forwarded-proto") or "https"
    base = "%s://%s/" % (scheme, host)
    loc = [{"name": "Local", "databaseAccountEndpoint": base}]
    return {
        "_self": "", "id": host.split(":")[0], "_rid": host,
        "media": "//media/", "addresses": "//addresses/", "_dbs": "//dbs/",
        "writableLocations": loc, "readableLocations": loc,
        "enableMultipleWriteLocations": False, "enableNToManyReplicas": False,
        "userReplicationPolicy": {"asyncReplication": False, "minReplicaSetSize": 1,
                                  "maxReplicasetSize": 4},
        "userConsistencyPolicy": {"defaultConsistencyLevel": "Session"},
        "systemReplicationPolicy": {"minReplicaSetSize": 1, "maxReplicasetSize": 4},
        "readPolicy": {"primaryReadCoefficient": 1, "secondaryReadCoefficient": 1},
        "queryEngineConfiguration": "{}",
    }


def _cos_query(docs: dict, body: dict) -> list:
    """Minimal SQL: support `SELECT * FROM c [WHERE c.field = 'value']`."""
    import re
    q = str(body.get("query") or "")
    out = list(docs.values())
    m = re.search(r"WHERE\s+c\.(\w+)\s*=\s*'([^']*)'", q, re.I)
    if m:
        f, v = m.group(1), m.group(2)
        out = [d for d in out if str(d.get(f)) == v]
    return out


# ----------------------------------------------------------------------------
# Function Apps (serverless execution via gcp_function_runtime)
# ----------------------------------------------------------------------------
async def _function_app_handle(app_name: str, function_name: str, request: Request) -> Response:
    """Invoke an Azure Function App by executing its deployed code."""
    sid = _sid()
    # Look up the Function App ARM resource from the active space.
    try:
        import server
        spaces_state = server._spaces_state()
        active_id = spaces_state.get("active_space_id", "")
        space = (spaces_state.get("spaces") or {}).get(active_id) or {}
        svc = space.get("service_states") or {}
        azure_resources = (svc.get("azure_arm") or {}).get("resources") or {}
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Unable to access space state"})

    # Find the function app resource by name (type microsoft.web/sites, kind functionapp)
    func_rec = None
    for rec in azure_resources.values():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("_type", "")).lower() == "microsoft.web/sites" and rec.get("name", "").lower() == app_name.lower():
            func_rec = rec
            break

    if not func_rec:
        return JSONResponse(status_code=404, content={"error": f"Function App '{app_name}' not found"})

    props = func_rec.get("properties") or {}
    code = props.get("code") or props.get("sourceCode") or ""
    entry = props.get("entryPoint") or "main"
    runtime = props.get("runtime") or "python"
    timeout = int(props.get("timeout") or 30)

    # Parse request payload
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Record usage event
    try:
        from core.app_context import record_usage
        record_usage("azure.functionapp.invoke", {"app": app_name, "function": function_name})
    except Exception:
        pass

    # Execute the function code
    if not code.strip():
        return JSONResponse(content={
            "invocationId": uuid.uuid4().hex,
            "result": {"message": f"Hello from {app_name}/{function_name}", "input": payload},
            "status": "FALLBACK",
        })

    try:
        from core import gcp_function_runtime
        out = gcp_function_runtime.execute(code, entry, runtime, payload, timeout=timeout)
        if out.get("status") == "SUCCESS":
            return JSONResponse(content={
                "invocationId": uuid.uuid4().hex,
                "result": out.get("result"),
                "logs": out.get("logs", ""),
                "status": "SUCCESS",
            })
        return JSONResponse(status_code=500, content={
            "invocationId": uuid.uuid4().hex,
            "error": out.get("error"),
            "logs": out.get("logs", ""),
            "status": "ERROR",
        })
    except Exception as exc:
        # Fallback to canned response if runtime unavailable
        return JSONResponse(content={
            "invocationId": uuid.uuid4().hex,
            "result": {"message": f"Hello from {app_name}/{function_name}", "input": payload},
            "status": "FALLBACK",
            "note": str(exc)[:200],
        })


# ----------------------------------------------------------------------------
# APIM gateway (data plane)
# ----------------------------------------------------------------------------
# Per-space rate-limit buckets for APIM subscription keys: (sid, svc, key) -> (tokens, ts)
_apim_rate: dict[tuple, tuple[float, float]] = {}
_APIM_RATE_RPS = 10  # default requests/sec per subscription key


async def _apim_handle(service_name: str, rest: str, request: Request) -> Response:
    """Data-plane proxy for Azure API Management.

    Looks up the APIM ARM resource, finds a matching child API, applies basic
    policies (subscription-key check, rate limiting), then returns the backend
    response or a mock.
    """
    sid = _sid()
    method = request.method.upper()

    # ── locate the APIM ARM resource ──
    try:
        import server
        spaces_state = server._spaces_state()
        active_id = spaces_state.get("active_space_id", "")
        space = (spaces_state.get("spaces") or {}).get(active_id) or {}
        svc = space.get("service_states") or {}
        azure_resources = (svc.get("azure_arm") or {}).get("resources") or {}
    except Exception:
        return JSONResponse(status_code=500, content={"error": {"code": "InternalError", "message": "Unable to access space state"}})

    # Find the APIM service resource by name
    apim_rec = None
    for rec in azure_resources.values():
        if not isinstance(rec, dict):
            continue
        if (str(rec.get("_type", "")).lower() == "microsoft.apimanagement/service"
                and rec.get("name", "").lower() == service_name.lower()):
            apim_rec = rec
            break

    if not apim_rec:
        return JSONResponse(status_code=404, content={"error": {"code": "ServiceNotFound",
                            "message": f"APIM service '{service_name}' not found"}})

    # ── subscription-key policy ──
    sub_key = request.headers.get("ocp-apim-subscription-key") or request.query_params.get("subscription-key") or ""
    if not sub_key:
        return JSONResponse(status_code=401, content={
            "statusCode": 401,
            "message": "Access denied due to missing subscription key. "
                       "Include 'Ocp-Apim-Subscription-Key' header."})

    # ── simple per-key rate limiting ──
    import threading
    now = time.time()
    rk = (sid, service_name, sub_key)
    burst = float(_APIM_RATE_RPS) * 4.0
    tokens, last = _apim_rate.get(rk, (burst, now))
    elapsed = now - last
    tokens = min(burst, tokens + elapsed * _APIM_RATE_RPS)
    if tokens < 1.0:
        return JSONResponse(status_code=429, content={
            "statusCode": 429, "message": "Rate limit exceeded. Try again later."})
    tokens -= 1.0
    _apim_rate[rk] = (tokens, now)

    # ── find matching child API ──
    rest = rest or ""
    api_path_segment = rest.split("/")[0] if rest else ""
    matched_api = None
    for rkey, rec in azure_resources.items():
        if not isinstance(rec, dict):
            continue
        rec_type = str(rec.get("_type", "")).lower()
        if rec_type == "microsoft.apimanagement/service/apis":
            # Match if the API name or path matches the first segment
            api_name = rec.get("name", "")
            api_props = rec.get("properties") or {}
            api_path = api_props.get("path", "").strip("/")
            if (api_name.lower() == api_path_segment.lower()
                    or api_path.lower() == api_path_segment.lower()):
                matched_api = rec
                break

    # ── route to backend or return mock ──
    if matched_api:
        api_props = matched_api.get("properties") or {}
        backend_url = api_props.get("serviceUrl") or api_props.get("backendUrl") or ""
        mock_response = api_props.get("mockResponse") or api_props.get("mock_response")

        if mock_response:
            # Record usage
            try:
                from core.app_context import record_usage
                record_usage("azure.apim.invoke", {"service": service_name, "api": matched_api.get("name", ""), "mode": "mock"})
            except Exception:
                pass
            if isinstance(mock_response, dict):
                return JSONResponse(content=mock_response)
            return JSONResponse(content={"value": mock_response})

        if backend_url:
            # Record usage
            try:
                from core.app_context import record_usage
                record_usage("azure.apim.invoke", {"service": service_name, "api": matched_api.get("name", ""), "mode": "proxy"})
            except Exception:
                pass
            # Strip the matched API segment from the rest path for proxying
            sub_path = "/".join(rest.split("/")[1:]) if "/" in rest else ""
            target = f"{backend_url.rstrip('/')}/{sub_path}" if sub_path else backend_url
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    body = await request.body()
                    resp = await client.request(
                        method, target,
                        content=body if body else None,
                        headers={k: v for k, v in request.headers.items()
                                 if k.lower() not in ("host", "content-length", "ocp-apim-subscription-key")},
                    )
                    return Response(content=resp.content, status_code=resp.status_code,
                                    media_type=resp.headers.get("content-type", "application/json"))
            except Exception as exc:
                return JSONResponse(status_code=502, content={
                    "statusCode": 502,
                    "message": f"Backend unavailable: {exc!s}"[:300]})

    # No matching API found — return a generic mock
    try:
        from core.app_context import record_usage
        record_usage("azure.apim.invoke", {"service": service_name, "path": rest, "mode": "default-mock"})
    except Exception:
        pass
    return JSONResponse(content={
        "statusCode": 200,
        "message": "OK",
        "service": service_name,
        "path": rest,
        "method": method,
        "mock": True,
    })


# ----------------------------------------------------------------------------
# Blob backend — Azurite when configured, in-process fallback otherwise.
#
# These helpers are the single source of truth for blob storage: both the
# console routes (/api/azure/storage/...) and the native Blob REST handler
# (_blob_handle) go through them, so a file uploaded from the console is
# immediately readable by azure-storage-blob — and lives in Azurite (durable,
# real open-source emulator), exactly like S3→MinIO and GCS→fake-gcs.
# ----------------------------------------------------------------------------
def _store():
    """Return the azure_blob_store module if Azurite is configured + reachable,
    else None (caller uses the in-process _blob dict)."""
    try:
        from core import azure_blob_store as _abs
        return _abs if _abs.available() else None
    except Exception:
        return None


def put_blob_bytes(account: str, container: str, blob: str, data: bytes,
                   content_type: str | None = None, meta: dict | None = None) -> dict:
    st = _store()
    if st:
        try:
            return st.put_blob(_sid(), account, container, blob, data, content_type, meta)
        except Exception:
            pass  # fall through to in-process on transient backend errors
    acct = _account(_sid(), account)
    acct["containers"].setdefault(container, {"created": _http_date()})
    rec = {"data": data, "ct": content_type or "application/octet-stream",
           "etag": _etag(), "mtime": _http_date(), "meta": meta or {}}
    acct["blobs"][(container, blob)] = rec
    return rec


def get_blob_rec(account: str, container: str, blob: str) -> dict | None:
    """Full record {data, ct, etag, mtime, meta} or None."""
    st = _store()
    if st:
        return st.get_blob(_sid(), account, container, blob)
    return _account(_sid(), account)["blobs"].get((container, blob))


def blob_props_rec(account: str, container: str, blob: str) -> dict | None:
    """Metadata only {size, ct, etag, mtime, meta} or None (for HEAD)."""
    st = _store()
    if st:
        return st.blob_props(_sid(), account, container, blob)
    rec = _account(_sid(), account)["blobs"].get((container, blob))
    if not rec:
        return None
    return {"size": len(rec["data"]), "ct": rec["ct"], "etag": rec["etag"],
            "mtime": rec["mtime"], "meta": rec.get("meta", {})}


def list_blobs(account: str, container: str, prefix: str = "") -> list[dict]:
    st = _store()
    if st:
        return st.list_blobs(_sid(), account, container, prefix)
    acct = _account(_sid(), account)
    out = []
    for (c, b), rec in acct["blobs"].items():
        if c != container or not b.startswith(prefix):
            continue
        out.append({"name": b, "size": len(rec["data"]), "contentType": rec["ct"],
                    "etag": rec["etag"], "lastModified": rec["mtime"]})
    return sorted(out, key=lambda o: o["name"])


def list_containers(account: str) -> list[dict]:
    st = _store()
    if st:
        out = []
        for name in st.list_containers(_sid(), account):
            out.append({"name": name, "created": _http_date(),
                        "blobCount": len(st.list_blobs(_sid(), account, name))})
        return out
    acct = _account(_sid(), account)
    # union of explicitly-created containers and any implied by a stored blob
    names = set(acct["containers"].keys()) | {c for (c, _b) in acct["blobs"]}
    out = []
    for name in names:
        meta = acct["containers"].get(name) or {}
        blobs = sum(1 for (c, _b) in acct["blobs"] if c == name)
        out.append({"name": name, "created": meta.get("created", _http_date()),
                    "blobCount": blobs})
    return sorted(out, key=lambda o: o["name"])


def container_exists(account: str, container: str) -> bool:
    st = _store()
    if st:
        return container in set(st.list_containers(_sid(), account))
    return container in _account(_sid(), account)["containers"]


def create_container(account: str, container: str) -> dict:
    st = _store()
    if st:
        st.create_container(_sid(), account, container)
        return {"name": container, "created": _http_date()}
    acct = _account(_sid(), account)
    rec = acct["containers"].setdefault(container, {"created": _http_date()})
    return {"name": container, "created": rec["created"]}


def delete_blob(account: str, container: str, blob: str) -> bool:
    st = _store()
    if st:
        return st.delete_blob(_sid(), account, container, blob)
    acct = _account(_sid(), account)
    return acct["blobs"].pop((container, blob), None) is not None


def delete_container(account: str, container: str) -> int:
    st = _store()
    if st:
        return st.delete_container(_sid(), account, container)
    acct = _account(_sid(), account)
    acct["containers"].pop(container, None)
    keys = [k for k in acct["blobs"] if k[0] == container]
    for k in keys:
        acct["blobs"].pop(k, None)
    return len(keys)


# ----------------------------------------------------------------------------
# Azure Storage Queue (native REST) — Azurite-backed; the AMQP→HTTP substitution
# for Service Bus. Served under /azure-data/queue/{account} so it never collides
# with the blob surface (both carry x-ms-version). Terminates the native Queue
# protocol and re-issues via core.azure_queue_store (the azure-storage-queue
# Python SDK → Azurite), so unmodified native clients round-trip.
# ----------------------------------------------------------------------------
def _queue_store():
    try:
        from core import azure_queue_store as _aqs
        return _aqs if _aqs.available() else None
    except Exception:
        return None


def _q_fmt(dt) -> str:
    try:
        return email.utils.format_datetime(dt, usegmt=True)
    except Exception:
        return email.utils.formatdate(usegmt=True)


def _queue_messages_xml(msgs: list, include_text: bool) -> str:
    from xml.sax.saxutils import escape
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<QueueMessagesList>"]
    for m in msgs:
        out.append("<QueueMessage>")
        out.append(f"<MessageId>{escape(str(m.get('id', '')))}</MessageId>")
        out.append(f"<InsertionTime>{_q_fmt(m.get('insertion_time'))}</InsertionTime>")
        out.append(f"<ExpirationTime>{_q_fmt(m.get('expiration_time'))}</ExpirationTime>")
        out.append(f"<PopReceipt>{escape(str(m.get('pop_receipt', '')))}</PopReceipt>")
        out.append(f"<TimeNextVisible>{_q_fmt(m.get('time_next_visible'))}</TimeNextVisible>")
        if include_text:
            out.append(f"<DequeueCount>{int(m.get('dequeue_count', 1) or 1)}</DequeueCount>")
            out.append(f"<MessageText>{escape(str(m.get('content', '')))}</MessageText>")
        out.append("</QueueMessage>")
    out.append("</QueueMessagesList>")
    return "".join(out)


def _xml_response(body: str, status: int = 200) -> Response:
    return Response(content=body, status_code=status, media_type="application/xml")


async def _queue_handle(account: str, rest: str, request: Request) -> Response:
    import re
    from xml.sax.saxutils import escape, unescape
    method = request.method
    qp = request.query_params
    sid = _sid()
    store = _queue_store()
    rest = (rest or "").strip("/")
    parts = rest.split("/") if rest else []

    # list queues: GET /{account}?comp=list
    if not parts:
        if method == "GET" and qp.get("comp") == "list":
            names = store.list_queues(sid, account) if store else []
            items = "".join(f"<Queue><Name>{escape(n)}</Name></Queue>" for n in names)
            return _xml_response('<?xml version="1.0" encoding="utf-8"?>'
                                 f"<EnumerationResults><Queues>{items}</Queues>"
                                 "<NextMarker /></EnumerationResults>")
        return Response(status_code=400, content="")

    queue = parts[0]

    # /{account}/{queue}  → create / delete / metadata
    if len(parts) == 1:
        if method == "PUT":
            if store:
                store.create_queue(sid, account, queue)
            return Response(status_code=201, content="")
        if method == "DELETE":
            if store:
                store.delete_queue(sid, account, queue)
            return Response(status_code=204, content="")
        if method in ("GET", "HEAD"):
            return Response(status_code=200, content="")
        return Response(status_code=400, content="")

    # /{account}/{queue}/messages[/{messageid}]
    if len(parts) >= 2 and parts[1] == "messages":
        # delete one message: DELETE /{queue}/messages/{messageid}?popreceipt=
        if len(parts) == 3 and method == "DELETE":
            if store:
                store.delete_message(sid, account, queue, parts[2], qp.get("popreceipt", ""))
            return Response(status_code=204, content="")
        if len(parts) == 2 and method == "POST":   # enqueue
            raw = (await request.body()).decode("utf-8", "replace")
            mt = re.search(r"<MessageText>(.*?)</MessageText>", raw, re.S)
            text = unescape(mt.group(1)) if mt else raw
            if not store:
                return Response(status_code=503, content="")
            m = store.send_message(sid, account, queue, text)
            return _xml_response(_queue_messages_xml([m], include_text=False), status=201)
        if len(parts) == 2 and method == "GET":     # dequeue
            try:
                num = max(1, int(qp.get("numofmessages", "1") or "1"))
            except Exception:
                num = 1
            try:
                vis = int(qp.get("visibilitytimeout", "30") or "30")
            except Exception:
                vis = 30
            msgs = store.receive_messages(sid, account, queue, num, vis) if store else []
            return _xml_response(_queue_messages_xml(msgs, include_text=True))
        if len(parts) == 2 and method == "DELETE":  # clear messages
            return Response(status_code=204, content="")

    return Response(status_code=400, content="")


# ----------------------------------------------------------------------------
# routes
# ----------------------------------------------------------------------------
def register(app) -> None:
    BLOB = ["GET", "PUT", "DELETE", "HEAD", "POST", "OPTIONS"]

    @app.api_route("/azure-data/blob/{account}", methods=BLOB, include_in_schema=False)
    @app.api_route("/azure-data/blob/{account}/{rest:path}", methods=BLOB, include_in_schema=False)
    async def blob_dispatch(account: str, request: Request, rest: str = ""):
        return await _blob_handle(account, rest, request)

    # Native Azure Storage Queue surface (Azurite-backed) — the AMQP→HTTP
    # substitution for Service Bus. The native azure-storage-queue SDK is pointed
    # here via QueueEndpoint=.../azure-data/queue/{account}; the /azure-data
    # prefix is a dispatch passthrough so it never collides with the blob handler.
    QUEUE = ["GET", "PUT", "DELETE", "HEAD", "POST", "OPTIONS"]

    @app.api_route("/azure-data/queue/{account}", methods=QUEUE, include_in_schema=False)
    @app.api_route("/azure-data/queue/{account}/{rest:path}", methods=QUEUE, include_in_schema=False)
    async def queue_dispatch(account: str, request: Request, rest: str = ""):
        return await _queue_handle(account, rest, request)

    # Console-friendly container + blob list + multipart upload (parity with
    # S3's "Upload object" button). These hit the SAME _blob store as the
    # native Blob SDK, so a console upload is immediately readable by
    # azure-storage-blob. Dedicated Azure routes — they NEVER fall through to
    # the S3 handler, so responses/errors stay Azure-shaped.
    @app.get("/api/azure/storage/{account}/containers", include_in_schema=False)
    def azure_container_console_list(account: str):
        return {"value": list_containers(account)}

    @app.delete("/api/azure/storage/{account}/containers/{container}/blobs/{blob:path}",
                include_in_schema=False)
    def azure_blob_console_delete(account: str, container: str, blob: str):
        deleted = delete_blob(account, container, blob)
        if not deleted:
            return JSONResponse(status_code=404,
                                content={"ok": False, "error": "blob not found",
                                         "account": account, "container": container, "blob": blob})
        return {"ok": True, "deleted": True, "account": account,
                "container": container, "blob": blob}

    @app.delete("/api/azure/storage/{account}/containers/{container}",
                include_in_schema=False)
    def azure_container_console_delete(account: str, container: str):
        n = delete_container(account, container)
        return {"ok": True, "deleted": True, "account": account,
                "container": container, "blobsDeleted": n}

    @app.post("/api/azure/storage/{account}/containers", include_in_schema=False)
    async def azure_container_console_create(account: str, request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = (body.get("name") or request.query_params.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": "missing container 'name'"})
        rec = create_container(account, name)
        return {"ok": True, "account": account, **rec}

    @app.get("/api/azure/storage/{account}/containers/{container}/blobs",
             include_in_schema=False)
    def azure_blob_console_list(account: str, container: str, prefix: str = ""):
        return {"value": list_blobs(account, container, prefix)}

    @app.post("/api/azure/storage/{account}/containers/{container}/blobs",
              include_in_schema=False)
    async def azure_blob_console_upload(account: str, container: str, request: Request):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": "missing 'file' field"})
        blob = (getattr(upload, "filename", None)
                or request.query_params.get("name") or "object").strip()
        data = await upload.read()
        ct = getattr(upload, "content_type", None) or "application/octet-stream"
        rec = put_blob_bytes(account, container, blob, data, ct)
        return {"ok": True, "account": account, "container": container, "blob": blob,
                "size": len(data), "contentType": ct, "etag": rec["etag"]}

    # Storage Queue console CRUD — backed by the SAME Azurite-queue store the
    # native azure-storage-queue SDK reads (core/azure_queue_store.py), so a
    # console-created queue is immediately visible to the SDK and vice-versa.
    # These NEVER touch the ARM Service Bus state (a different service) — they
    # stay on the conformant data-plane backend.
    @app.get("/api/azure/storage/{account}/queues", include_in_schema=False)
    def azure_queue_console_list(account: str):
        store = _queue_store()
        return {"value": store.list_queues(_sid(), account) if store else []}

    @app.post("/api/azure/storage/{account}/queues", include_in_schema=False)
    async def azure_queue_console_create(account: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = (body.get("name") or request.query_params.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": "missing queue 'name'"})
        store = _queue_store()
        if not store:
            return JSONResponse(status_code=503,
                                content={"ok": False, "error": "queue backend unavailable"})
        store.create_queue(_sid(), account, name)
        return {"ok": True, "account": account, "name": name}

    @app.delete("/api/azure/storage/{account}/queues/{queue}", include_in_schema=False)
    def azure_queue_console_delete(account: str, queue: str):
        store = _queue_store()
        deleted = store.delete_queue(_sid(), account, queue) if store else False
        return {"ok": True, "deleted": bool(deleted), "account": account, "queue": queue}

    @app.api_route("/azure-data/servicebus/{namespace}/{rest:path}",
                   methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def sb_dispatch(namespace: str, rest: str, request: Request):
        return await _sb_handle(namespace, rest, request)

    COSMOS_METHODS = ["GET", "PUT", "POST", "DELETE", "HEAD", "OPTIONS"]

    @app.api_route("/azure-data/cosmos/{account}", methods=COSMOS_METHODS, include_in_schema=False)
    @app.api_route("/azure-data/cosmos/{account}/{rest:path}", methods=COSMOS_METHODS,
                   include_in_schema=False)
    async def cosmos_dispatch(account: str, request: Request, rest: str = ""):
        return await _cosmos_handle(account, rest, request)

    @app.post("/azure-data/functions/{app_name}/{function_name}", include_in_schema=False)
    async def function_app_invoke(app_name: str, function_name: str, request: Request):
        return await _function_app_handle(app_name, function_name, request)

    APIM_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

    @app.api_route("/azure-data/apim/{service_name}", methods=APIM_METHODS, include_in_schema=False)
    @app.api_route("/azure-data/apim/{service_name}/{rest:path}", methods=APIM_METHODS, include_in_schema=False)
    async def apim_dispatch(service_name: str, request: Request, rest: str = ""):
        return await _apim_handle(service_name, rest, request)
