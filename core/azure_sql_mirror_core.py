"""Azure SQL "Mirror database" worker: REAL incremental replication of a database's tables into Parquet files in the
simulator's own Azure Blob store (the shape of Fabric's mirrored-database landing zone). Substrate-free; the Parquet bytes
come from the platform writer hook (pyarrow offline, core/parquet_pyarrow.py).

    POST /servers/{s}/databases/{db}/mirror/sync     {"container": "...", "prefix": "...", "tables": [...]}  -> run one sync
    GET  /servers/{s}/databases/{db}/mirror/status?container=..&prefix=..                                   -> last sync status

What really happens: every selected table is read from the real SQL engine (SqlStore: sqlite, or Postgres in Pro/Max),
hashed row by row and compared with the manifest the previous sync wrote (``<prefix>/_status.json`` in the same container).
An unchanged table is skipped; a changed table gets a NEW Parquet file (``<prefix>/<table>/part-<n>.parquet``) with the
old file removed; a table dropped at the source loses its file. Per table the status carries rows inserted / removed since the
last sync (row-hash diff, so an UPDATE counts as one removed + one inserted), the current row count and the sync time.

NOT modelled: Microsoft Fabric itself (workspaces, OneLake, Delta transaction logs, SQL analytics endpoint) is not in scope,
this is a Parquet landing zone only; syncs run when requested (no change-feed tail), and the whole table is re-read to diff.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

try:
    from core import azure_blob_core as _bl, sql_store as _sq
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_blob_core as _bl  # type: ignore
    import sql_store as _sq  # type: ignore

STATUS = "_status.json"


class MirrorError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _put(blob_store, container, name, data, content_type):
    now = _bl._now_http()
    blob_store.container_blobs(container)[name] = {
        "data": data, "size": len(data), "content_type": content_type, "blob_type": "BlockBlob", "etag": _bl._etag(),
        "last_modified": now, "created": now, "md5": _bl._md5_b64(data), "access_tier": "Hot", "encryption_scope": "", "metadata": {}}


def _writer():
    try:
        from core import rds_core as r
    except ImportError:  # pragma: no cover
        import rds_core as r  # type: ignore
    w = r._resolve_parquet_writer()
    if w is None:
        raise MirrorError(501, "NotImplemented", "Mirroring writes Parquet and needs the offline appliance (pyarrow); this context has no synchronous Parquet engine.")
    return w


def _row_hashes(table):
    return sorted(hashlib.sha1(json.dumps(r, default=str, separators=(",", ":")).encode()).hexdigest()[:12] for r in table.get("rows") or [])


def _diff(old, new):
    """Multiset difference of two sorted hash lists -> (inserted, removed)."""
    from collections import Counter
    a, b = Counter(old), Counter(new)
    return sum((b - a).values()), sum((a - b).values())


def read_status(blob_store, container, prefix):
    entry = blob_store.container_blobs(container).get(f"{prefix}/{STATUS}") if blob_store.container_exists(container) else None
    if not entry:
        return None
    return json.loads(bytes(entry["data"]).decode("utf-8"))


def sync(store, db_id, blob_store, container, prefix, tables=None, server="", database=""):
    if blob_store is None:
        raise MirrorError(501, "NotImplemented", "No blob store is attached to this SQL engine.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", container or ""):
        raise MirrorError(400, "InvalidParameter", "container must be a valid blob container name (3-63 lowercase letters, digits, hyphens).")
    prefix = (prefix or "").strip("/") or "mirror"
    if _sq.is_async_engine(store):
        raise MirrorError(501, "NotImplemented", "Mirroring reads the source synchronously; this engine (PGlite) is asynchronous.")
    write = _writer()
    dumped = _sq.dump_tables(store, db_id)
    dialect = _sq.engine_dialect(_sq.engine_store_for(store, db_id))
    schema_name = _sq.default_schema(dialect)
    want = {t for t in (tables or [])}
    missing = sorted(want - {t["name"] for t in dumped})
    if missing:
        raise MirrorError(404, "ResourceNotFound", f"Table(s) not found in the source database: {', '.join(missing)}.")
    if not blob_store.container_exists(container):
        blob_store.create_container(container)
    prev = read_status(blob_store, container, prefix) or {"tables": {}, "syncCount": 0}
    out, started = {}, _now()
    for t in dumped:
        if want and t["name"] not in want:
            continue
        key = f"{schema_name}.{t['name']}"
        hashes = _row_hashes(t)
        old = prev["tables"].get(key)
        digest = hashlib.sha1((json.dumps(t["columns"]) + "|" + "".join(hashes)).encode()).hexdigest()
        if old and old.get("digest") == digest and f"{prefix}/{old['file']}" in blob_store.container_blobs(container):
            out[key] = {**old, "state": "UpToDate", "rowsInserted": 0, "rowsRemoved": 0}
            continue
        schema, columns = _sq.parquet_columns(t, dialect)
        data = write(schema, columns)
        if not isinstance(data, (bytes, bytearray)):
            raise MirrorError(501, "NotImplemented", "The Parquet engine in this context is asynchronous; mirroring needs the offline appliance.")
        n = (old or {}).get("version", 0) + 1
        fname = f"{key}/part-{n:05d}.parquet"
        _put(blob_store, container, f"{prefix}/{fname}", bytes(data), "application/octet-stream")
        if old:
            blob_store.container_blobs(container).pop(f"{prefix}/{old['file']}", None)
        ins, rem = _diff((old or {}).get("rowHashes", []), hashes)
        out[key] = {"state": "Replicated", "file": fname, "version": n, "rows": len(t.get("rows") or []), "digest": digest,
                    "rowsInserted": ins, "rowsRemoved": rem, "bytes": len(data), "lastSyncedAt": _now(), "rowHashes": hashes,
                    "columns": [c["name"] for c in t.get("columns") or []]}
    # tables dropped at the source (or de-selected) lose their file
    for key, old in prev["tables"].items():
        if key not in out:
            if want and key.split(".", 1)[-1] not in want and key.split(".", 1)[-1] in {t["name"] for t in dumped}:
                out[key] = old        # de-selected but still present: left as it was
            else:
                blob_store.container_blobs(container).pop(f"{prefix}/{old['file']}", None)
    status = {"server": server, "database": database, "container": container, "prefix": prefix, "startedAt": started, "completedAt": _now(),
              "syncCount": prev.get("syncCount", 0) + 1, "tables": out,
              "summary": {"tables": len(out), "replicated": sum(1 for v in out.values() if v["state"] == "Replicated"),
                          "upToDate": sum(1 for v in out.values() if v["state"] == "UpToDate"),
                          "rows": sum(v["rows"] for v in out.values()), "rowsInserted": sum(v["rowsInserted"] for v in out.values() if "rowsInserted" in v),
                          "rowsRemoved": sum(v["rowsRemoved"] for v in out.values() if "rowsRemoved" in v)}}
    _put(blob_store, container, f"{prefix}/{STATUS}", json.dumps(status).encode(), "application/json")
    blob_store.persist()
    return {k: v for k, v in status.items()} | {"tables": {k: {a: b for a, b in v.items() if a != "rowHashes"} for k, v in out.items()}}
