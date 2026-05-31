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
    method = request.method.upper()
    qp = request.query_params
    acct = _account(_sid(), account)
    rest = rest or ""

    # ----- account level: GET ?comp=list -> list containers -----
    if rest == "":
        if method == "GET" and qp.get("comp") == "list":
            items = "".join(
                f"<Container><Name>{_xml_escape(name)}</Name><Properties>"
                f"<Last-Modified>{_http_date()}</Last-Modified><Etag>{_etag()}</Etag>"
                f"<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
                f"</Properties></Container>"
                for name in acct["containers"])
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
            for (c, b), rec in acct["blobs"].items():
                if c != container or not b.startswith(prefix):
                    continue
                rows += (f"<Blob><Name>{_xml_escape(b)}</Name><Properties>"
                         f"<Last-Modified>{rec['mtime']}</Last-Modified><Etag>{rec['etag']}</Etag>"
                         f"<Content-Length>{len(rec['data'])}</Content-Length>"
                         f"<Content-Type>{_xml_escape(rec['ct'])}</Content-Type>"
                         f"<BlobType>BlockBlob</BlobType>"
                         f"<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
                         f"</Properties></Blob>")
            xml = ('<?xml version="1.0" encoding="utf-8"?>'
                   f'<EnumerationResults ContainerName="{_xml_escape(container)}">'
                   f'<Blobs>{rows}</Blobs><NextMarker /></EnumerationResults>')
            return Response(content=xml, media_type="application/xml", headers=_blob_headers())
        if qp.get("restype") == "container":
            if method == "PUT":
                if container in acct["containers"]:
                    return Response(status_code=409, content="", headers=_blob_headers(
                        {"x-ms-error-code": "ContainerAlreadyExists"}))
                acct["containers"][container] = {"created": _http_date()}
                return Response(status_code=201, content="", headers=_blob_headers(
                    {"ETag": _etag(), "Last-Modified": _http_date()}))
            if method == "DELETE":
                acct["containers"].pop(container, None)
                for k in [k for k in acct["blobs"] if k[0] == container]:
                    acct["blobs"].pop(k, None)
                return Response(status_code=202, content="", headers=_blob_headers())
            if method in ("GET", "HEAD"):  # get container properties
                if container not in acct["containers"]:
                    return Response(status_code=404, content="", headers=_blob_headers(
                        {"x-ms-error-code": "ContainerNotFound"}))
                return Response(status_code=200, content="", headers=_blob_headers(
                    {"ETag": _etag(), "Last-Modified": _http_date()}))
        return Response(status_code=400, content="", headers=_blob_headers())

    # ----- blob level -----
    key = (container, blob)
    if method == "PUT":
        body = await request.body()
        acct["containers"].setdefault(container, {"created": _http_date()})
        ct = request.headers.get("content-type") or request.headers.get("x-ms-blob-content-type") or "application/octet-stream"
        meta = {k[len("x-ms-meta-"):]: v for k, v in request.headers.items() if k.lower().startswith("x-ms-meta-")}
        etag = _etag()
        acct["blobs"][key] = {"data": body, "ct": ct, "etag": etag, "mtime": _http_date(), "meta": meta}
        md5 = hashlib.md5(body).digest()
        import base64
        return Response(status_code=201, content="", headers=_blob_headers({
            "ETag": etag, "Last-Modified": _http_date(),
            "Content-MD5": base64.b64encode(md5).decode(),
            "x-ms-request-server-encrypted": "true"}))
    rec = acct["blobs"].get(key)
    if method in ("GET", "HEAD"):
        if not rec:
            return Response(status_code=404, content="", headers=_blob_headers(
                {"x-ms-error-code": "BlobNotFound"}))
        hdrs = _blob_headers({
            "ETag": rec["etag"], "Last-Modified": rec["mtime"],
            "Content-Length": str(len(rec["data"])), "Accept-Ranges": "bytes",
            "x-ms-blob-type": "BlockBlob", "x-ms-creation-time": rec["mtime"]})
        for mk, mv in rec.get("meta", {}).items():
            hdrs["x-ms-meta-" + mk] = mv
        if method == "HEAD":
            return Response(status_code=200, content=b"", media_type=rec["ct"], headers=hdrs)
        return Response(content=rec["data"], media_type=rec["ct"], headers=hdrs)
    if method == "DELETE":
        existed = acct["blobs"].pop(key, None) is not None
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
    # dbs / dbs/{db} / dbs/{db}/colls / dbs/{db}/colls/{coll} / .../docs[/{id}]
    try:
        if segs and segs[0] == "dbs":
            if len(segs) == 1:
                if method == "GET":
                    return JSONResponse({"Databases": [{"id": d} for d in acct], "_count": len(acct)})
                if method == "POST":
                    body = await _json(request); did = body.get("id")
                    acct.setdefault(did, {})
                    return JSONResponse(status_code=201, content={"id": did})
            db = segs[1]
            if len(segs) == 2:
                if method == "PUT":
                    acct.setdefault(db, {}); return JSONResponse(status_code=201, content={"id": db})
                if method == "GET":
                    return JSONResponse({"id": db}) if db in acct else _cos_404()
                if method == "DELETE":
                    acct.pop(db, None); return Response(status_code=204, content="")
            if len(segs) >= 3 and segs[2] == "colls":
                dbo = acct.setdefault(db, {})
                if len(segs) == 3:
                    if method == "GET":
                        return JSONResponse({"DocumentCollections": [{"id": c} for c in dbo], "_count": len(dbo)})
                    if method == "POST":
                        body = await _json(request); cid = body.get("id"); dbo.setdefault(cid, {})
                        return JSONResponse(status_code=201, content={"id": cid})
                coll = segs[3]
                if len(segs) == 4:
                    if method == "PUT":
                        dbo.setdefault(coll, {}); return JSONResponse(status_code=201, content={"id": coll})
                    if method == "DELETE":
                        dbo.pop(coll, None); return Response(status_code=204, content="")
                if len(segs) >= 5 and segs[4] == "docs":
                    docs = dbo.setdefault(coll, {})
                    if len(segs) == 5:
                        if method == "POST":
                            body = await _json(request)
                            did = body.get("id") or uuid.uuid4().hex
                            body["id"] = did; body.setdefault("_rid", uuid.uuid4().hex); body["_ts"] = int(time.time())
                            docs[did] = body
                            return JSONResponse(status_code=201, content=body)
                        if method == "GET":
                            return JSONResponse({"Documents": list(docs.values()), "_count": len(docs)})
                    did = segs[5]
                    if method == "GET":
                        return JSONResponse(docs[did]) if did in docs else _cos_404()
                    if method in ("PUT",):
                        body = await _json(request); body["id"] = did; docs[did] = body
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


# ----------------------------------------------------------------------------
# routes
# ----------------------------------------------------------------------------
def register(app) -> None:
    BLOB = ["GET", "PUT", "DELETE", "HEAD", "POST", "OPTIONS"]

    @app.api_route("/azure-data/blob/{account}", methods=BLOB, include_in_schema=False)
    @app.api_route("/azure-data/blob/{account}/{rest:path}", methods=BLOB, include_in_schema=False)
    async def blob_dispatch(account: str, request: Request, rest: str = ""):
        return await _blob_handle(account, rest, request)

    @app.api_route("/azure-data/servicebus/{namespace}/{rest:path}",
                   methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def sb_dispatch(namespace: str, rest: str, request: Request):
        return await _sb_handle(namespace, rest, request)

    @app.api_route("/azure-data/cosmos/{account}/{rest:path}",
                   methods=["GET", "PUT", "POST", "DELETE"], include_in_schema=False)
    async def cosmos_dispatch(account: str, rest: str, request: Request):
        return await _cosmos_handle(account, rest, request)
