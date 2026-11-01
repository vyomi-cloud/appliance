"""Nano's RDS export Parquet engine: the VENDORED parquet-wasm 0.7.1 + apache-arrow 18.1.0
(wasm/parquet/) driven by the browser loader's own buildParquet(), under Node.

rds_core builds (schema, columns) from a real snapshot and serialises them exactly as
the Pyodide bridge does (rds_core.parquet_spec_json); Node writes the Parquet bytes with
the vendored WASM; pyarrow reads them back and the rows must equal the snapshot's. Also
pins that the loader never reaches a CDN (only same-origin vendored files).

Run:  PYTHONPATH=. python3 tests/conformance/test_rds_parquet_nano.py
(skips — does not fake — without node or pyarrow)
"""
import base64
import io
import os
import shutil
import subprocess

from core import rds_core as rds
from core import sql_store as sq
from core.sql_store import InMemorySqlStore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRIVER = os.path.join(ROOT, "tests", "conformance", "rds_parquet_node.mjs")
VENDOR = os.path.join(ROOT, "wasm", "parquet")


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def run() -> int:
    for f in ("parquet_wasm.js", "parquet_wasm_bg.wasm", "arrow.es2015.min.js", "parquet-loader.js"):
        _check(f"vendored {f}", os.path.isfile(os.path.join(VENDOR, f)))
    loader = open(os.path.join(VENDOR, "parquet-loader.js")).read()
    _check("loader fetches only same-origin vendored files (no CDN)",
           "http://" not in loader.split("*/", 1)[1] and "https://" not in loader.split("*/", 1)[1])
    node = shutil.which("node")
    try:
        import pyarrow.parquet as pq
    except Exception:
        pq = None
    if not node or pq is None:
        print(f"  SKIP  node={bool(node)} pyarrow={pq is not None}")
        return 0
    st = InMemorySqlStore()
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "n1"})
    st.execute_sql("n1", "CREATE TABLE t (id INTEGER, name TEXT, score REAL, ok BOOLEAN, img BLOB)")
    st.execute_sql("n1", "INSERT INTO t VALUES (1, 'a', 1.5, 1, x'00ff'), (2, NULL, NULL, 0, NULL)")
    rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "n1", "DBSnapshotIdentifier": "s"})
    table = st.get_snapshot("s")["data"]["tables"][0]
    schema, columns = sq.parquet_columns(table)
    spec = rds.parquet_spec_json(schema, columns).encode()
    direct = subprocess.run([node, DRIVER, "--direct"], input=spec, capture_output=True, timeout=120)
    _check("node + vendored parquet-wasm (initSync + buildParquet) wrote Parquet", direct.returncode == 0,
           direct.stderr.decode()[-400:])
    out = subprocess.run([node, DRIVER], input=spec, capture_output=True, timeout=120)
    _check("the browser loader path (installParquet -> lazy load -> __nano_parquet_write) wrote Parquet",
           out.returncode == 0, out.stderr.decode()[-400:])
    _check("the lazy load fetched only the vendored files",
           "arrow.es2015.min.js" in out.stderr.decode() and "parquet_wasm_bg.wasm" in out.stderr.decode())
    _check("both paths produce identical rows",
           pq.read_table(io.BytesIO(base64.b64decode(direct.stdout))).to_pylist()
           == pq.read_table(io.BytesIO(base64.b64decode(out.stdout))).to_pylist())
    f = pq.ParquetFile(io.BytesIO(base64.b64decode(out.stdout)))
    _check("pyarrow reads the parquet-wasm bytes: rows equal the snapshot's",
           f.read().to_pylist() == [{"id": 1, "name": "a", "score": 1.5, "ok": True, "img": b"\x00\xff"},
                                    {"id": 2, "name": None, "score": None, "ok": False, "img": None}])
    _check("typed Arrow schema + gzip, same as offline",
           [str(t) for t in f.schema_arrow.types] == ["int64", "string", "double", "bool", "binary"]
           and f.metadata.row_group(0).column(0).compression == "GZIP")
    print("RESULT: PASS — Nano's vendored Parquet engine writes real Parquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
