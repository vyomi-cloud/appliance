"""Azure AI Search indexer data sources beyond Blob: Cosmos DB (NoSQL API) and Azure SQL, read from the SIMULATED stores.

A thin reader: it only turns rows of the existing Vyomi engines into the row dicts the indexer already knows how to push
through field mappings / skillsets / projections (core/azure_search_core.run_indexer). Pure Python, Pyodide-loadable.

* ``cosmosdb``: ``credentials.connectionString`` = ``AccountEndpoint=...;AccountKey=...;Database=<db>``; ``container.name`` =
  collection; ``container.query`` optional Cosmos SQL (``@HighWaterMark`` is replaced with the stored watermark). Reads the
  CosmosStore the Cosmos data plane writes (core/azure_cosmos_core).
* ``azuresql``: ``Server=tcp:<server>.database.windows.net,1433;Database=<db>`` (or ``Initial Catalog``); ``container.name`` =
  table or view (schema prefix such as ``dbo.`` is dropped). Reads through the Azure SQL data plane (core/azure_sql_core.execute_sql).
* ``HighWaterMarkChangeDetectionPolicy`` makes runs incremental (watermark in the indexer status ``finalTrackingState``);
  ``SoftDeleteColumnDeletionDetectionPolicy`` removes documents whose soft-delete column holds the marker value.

Limits: no SqlIntegratedChangeTracking, no managed-identity / private-endpoint connection strings (the connection string only
names the simulated account / server), Cosmos queries use the pragmatic SQL subset of core/azure_cosmos_core.
"""
from __future__ import annotations

import re

_SYS = ("_rid", "_self", "_etag", "_attachments", "_lsn")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _kv(cs, *names):
    for n in names:
        m = re.search(r"(?:^|;)\s*%s\s*=\s*([^;]+)" % re.escape(n), cs or "", re.I)
        if m:
            return m.group(1).strip()
    return None


def read(ds, cosmos_store, sql_store, watermark=None):
    """-> (rows, new_watermark, error). Each row is a plain dict (system properties kept for Cosmos so ``_ts`` can be mapped)."""
    t = ds["type"]
    cs = (ds.get("credentials") or {}).get("connectionString", "")
    cont = ds["container"]
    pol = ds.get("dataChangeDetectionPolicy") or {}
    hwm_col = pol.get("highWaterMarkColumnName") if str(pol.get("@odata.type", "")).endswith("HighWaterMarkChangeDetectionPolicy") else None
    if str(pol.get("@odata.type", "")).endswith("SqlIntegratedChangeTrackingPolicy"):
        return None, watermark, "SqlIntegratedChangeTrackingPolicy is not supported by Vyomi; use HighWaterMarkChangeDetectionPolicy."
    if t == "cosmosdb":
        if cosmos_store is None:
            return None, watermark, "No Cosmos DB store is attached to this search service."
        db = _kv(cs, "Database")
        if not db:
            return None, watermark, "The Cosmos DB connection string must name the database (Database=<name>)."
        if db not in cosmos_store.dbs:
            return None, watermark, f"The Cosmos DB database '{db}' does not exist."
        cname = cont["name"]
        if cname not in (cosmos_store.docs.get(db) or {}):
            return None, watermark, f"The Cosmos DB container '{cname}' does not exist in database '{db}'."
        docs = list(cosmos_store.docs[db][cname].values())
        q = cont.get("query")
        if q:
            try:
                from core import azure_cosmos_core as _cos
            except ImportError:  # Pyodide flat layout
                import azure_cosmos_core as _cos  # type: ignore
            q = q.replace("@HighWaterMark", str(watermark if watermark is not None else 0))
            docs = _cos._run_query(docs, q)
            if any(not isinstance(d, dict) for d in docs):
                return None, watermark, "The Cosmos DB query must return documents (SELECT * or an object projection)."
        if hwm_col:
            if watermark is not None:
                docs = [d for d in docs if isinstance(d.get(hwm_col), (int, float)) and d[hwm_col] >= watermark]
            docs.sort(key=lambda d: (d.get(hwm_col) is None, d.get(hwm_col) or 0))
        rows = [{k: v for k, v in d.items() if k not in _SYS} for d in docs]
    elif t == "azuresql":
        if sql_store is None:
            return None, watermark, "No Azure SQL store is attached to this search service."
        srv = _kv(cs, "Server", "Data Source") or ""
        srv = re.sub(r"^tcp:", "", srv, flags=re.I).split(",")[0].split(".")[0]
        db = _kv(cs, "Database", "Initial Catalog")
        if not srv or not db:
            return None, watermark, "The SQL connection string must name Server and Database."
        table = cont["name"].split(".")[-1].strip("[]\"")
        if not _IDENT.match(table):
            return None, watermark, f"Invalid table or view name '{cont['name']}'."
        sql, params = f'SELECT * FROM "{table}"', []
        if hwm_col:
            if not _IDENT.match(hwm_col):
                return None, watermark, f"Invalid high water mark column '{hwm_col}'."
            if watermark is not None:
                sql += f' WHERE "{hwm_col}" >= ?'
                params = [watermark]
            sql += f' ORDER BY "{hwm_col}"'
        try:
            from core import azure_sql_core as _sql
        except ImportError:
            import azure_sql_core as _sql  # type: ignore
        r = _sql.execute_sql(sql_store, srv, db, sql, params)
        if not r["ok"]:
            return None, watermark, f"SQL read failed: {r['message']}"
        rows = [dict(zip(r["columns"], row)) for row in r["rows"]]
    else:
        return None, watermark, f"Data source type '{t}' is not readable by Vyomi indexers (azureblob, cosmosdb and azuresql are)."
    new_wm = watermark
    if hwm_col:
        vals = [r.get(hwm_col) for r in rows if isinstance(r.get(hwm_col), (int, float, str))]
        if vals:
            new_wm = max(vals) if not isinstance(watermark, type(vals[0])) or watermark is None else max(vals + [watermark])
    return rows, new_wm, None


def is_deleted(ds, row):
    """True when the data source's soft-delete policy marks this row as deleted."""
    pol = ds.get("dataDeletionDetectionPolicy") or {}
    if str(pol.get("@odata.type", "")).endswith("SoftDeleteColumnDeletionDetectionPolicy"):
        col, marker = pol.get("softDeleteColumnName"), pol.get("softDeleteMarkerValue")
        return col is not None and str(row.get(col)).lower() == str(marker).lower()
    return False
