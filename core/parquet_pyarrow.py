"""Offline (FastAPI appliance) Parquet writer for the RDS snapshot export.

core/rds_core.py builds each exported table as (schema, columns) and calls the
platform's `parquet_writer(schema, columns) -> bytes` hook; this is that hook on
the appliance, backed by pyarrow (`pq.write_table` into a BytesIO, gzip-compressed —
the `.gz.parquet` files AWS writes). In the browser the same hook is parquet-wasm
(wasm/parquet-loader.js). NOT vendored to Nano (pyarrow is a native wheel)."""
from __future__ import annotations

import io

_TYPES = {"int64": "int64", "float64": "float64", "bool": "bool_", "string": "string", "binary": "binary"}


def write_parquet(schema: list, columns: list) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    fields = [pa.field(f["name"], getattr(pa, _TYPES.get(f.get("type"), "string"))()) for f in schema]
    arrays = [pa.array(col, type=fld.type) for col, fld in zip(columns, fields)]
    table = pa.Table.from_arrays(arrays, schema=pa.schema(fields))
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="gzip")
    return buf.getvalue()


def install() -> bool:
    """Register write_parquet as rds_core's Parquet writer. False when pyarrow is
    missing — exports then FAIL with a clear FailureCause (no format fallback)."""
    try:
        import pyarrow.parquet  # noqa: F401
    except Exception:
        return False
    from core import rds_core
    rds_core.set_parquet_writer(write_parquet)
    return True
