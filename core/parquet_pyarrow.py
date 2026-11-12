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


def read_parquet(data: bytes) -> dict:
    """Reader twin of write_parquet for RestoreDBInstanceFromS3: {"columns": [{"name","type"}], "rows": [[...]]}."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    t = pq.read_table(io.BytesIO(data))
    def kind(ty):
        if pa.types.is_integer(ty):
            return "int64"
        if pa.types.is_floating(ty):
            return "float64"
        if pa.types.is_boolean(ty):
            return "bool"
        if pa.types.is_binary(ty) or pa.types.is_large_binary(ty):
            return "binary"
        return "string"
    cols = [{"name": f.name, "type": kind(f.type)} for f in t.schema]
    lists = [t.column(i).to_pylist() for i in range(t.num_columns)]
    return {"columns": cols, "rows": [list(r) for r in zip(*lists)] if lists else []}


def install() -> bool:
    """Register write_parquet as rds_core's Parquet writer. False when pyarrow is
    missing — exports then FAIL with a clear FailureCause (no format fallback)."""
    try:
        import pyarrow.parquet  # noqa: F401
    except Exception:
        return False
    from core import rds_core
    rds_core.set_parquet_writer(write_parquet)
    try:
        from core import rds_restore_core
        rds_restore_core.set_parquet_reader(read_parquet)
    except Exception:  # noqa: BLE001
        pass
    return True
