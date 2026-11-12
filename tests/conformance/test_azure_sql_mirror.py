"""REAL Azure SQL mirroring: tables replicated from the SQL engine into Parquet files in the blob store, incrementally.
Needs pyarrow (the offline appliance's Parquet engine). Run: PYTHONPATH=. python tests/conformance/test_azure_sql_mirror.py"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
try:
    import pyarrow.parquet as pq
except ImportError:
    print("[SKIP] pyarrow not installed: mirroring needs the offline Parquet engine")
    sys.exit(0)
from core import azure_sql_core as az, parquet_pyarrow  # noqa: E402
from core.azure_blob_core import AzureBlobStore  # noqa: E402
from core.sql_store import InMemorySqlStore  # noqa: E402

parquet_pyarrow.install()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


s, blobs = InMemorySqlStore(), AzureBlobStore()


def call(m, p, b=None, q=None):
    r = az.dispatch(s, m, p, q or {}, {}, json.dumps(b).encode() if b is not None else b"", blob_store=blobs)
    return r.status, (json.loads(r.body) if r.body else {})


call("PUT", "/servers/srv")
call("PUT", "/servers/srv/databases/app")
sql = lambda x: call("POST", "/servers/srv/databases/app/query", {"sql": x})
sql("CREATE TABLE orders(id INTEGER PRIMARY KEY, item TEXT, price REAL)")
sql("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
for i in range(1, 6):
    sql(f"INSERT INTO orders VALUES ({i}, 'item{i}', {i * 1.5})")
sql("INSERT INTO users VALUES (1, 'ada')")
M = "/servers/srv/databases/app/mirror"
body = {"container": "fabric-mirror-m1", "prefix": "mirror"}

st, r = call("POST", f"{M}/sync", body)
check("first sync replicates every table", st == 200 and r["summary"]["replicated"] == 2 and r["summary"]["rows"] == 6 and r["syncCount"] == 1, r)
f = r["tables"]["main.orders"]["file"] if "main.orders" in r["tables"] else next(v["file"] for k, v in r["tables"].items() if k.endswith("orders"))
data = bytes(blobs.container_blobs("fabric-mirror-m1")[f"mirror/{f}"]["data"])
t = pq.read_table(io.BytesIO(data))
check("the blob is a real Parquet file with the real rows and types", t.num_rows == 5 and t.column("item").to_pylist()[0] == "item1"
      and str(t.schema.field("price").type) == "double", t.schema)
st, r2 = call("POST", f"{M}/sync", body)
check("second sync with no changes skips both tables", r2["summary"]["upToDate"] == 2 and r2["summary"]["replicated"] == 0 and r2["syncCount"] == 2, r2)
sql("INSERT INTO orders VALUES (6, 'item6', 9.0)")
sql("UPDATE orders SET item='renamed' WHERE id=1")
sql("DELETE FROM orders WHERE id=2")
st, r3 = call("POST", f"{M}/sync", body)
o = next(v for k, v in r3["tables"].items() if k.endswith("orders"))
u = next(v for k, v in r3["tables"].items() if k.endswith("users"))
check("incremental sync rewrites only the changed table", o["state"] == "Replicated" and u["state"] == "UpToDate", r3)
check("row diff counts inserts and removals (update = 1 + 1)", o["rowsInserted"] == 2 and o["rowsRemoved"] == 2 and o["rows"] == 5, o)
names = list(blobs.container_blobs("fabric-mirror-m1"))
check("the old Parquet file was replaced, not accumulated", sum(1 for n in names if "orders/part" in n or ".orders/part" in n) == 1, names)
t2 = pq.read_table(io.BytesIO(bytes(blobs.container_blobs("fabric-mirror-m1")[f"mirror/{o['file']}"]["data"])))
check("the new file holds the new data", "renamed" in t2.column("item").to_pylist() and "item2" not in t2.column("item").to_pylist(), t2.column("item").to_pylist())
st, stt = call("GET", f"{M}/status", q={"container": "fabric-mirror-m1", "prefix": "mirror"})
check("status endpoint returns the last sync", st == 200 and stt["syncCount"] == 3 and stt["summary"]["tables"] == 2, stt)
sql("DROP TABLE users")
st, r4 = call("POST", f"{M}/sync", body)
check("a table dropped at the source loses its mirrored file", not any(k.endswith("users") for k in r4["tables"])
      and not any("users/part" in n for n in blobs.container_blobs("fabric-mirror-m1")), r4)
st, r5 = call("POST", f"{M}/sync", {**body, "tables": ["orders"]})
check("table selection honoured", st == 200 and list(r5["tables"]) and all(k.endswith("orders") for k in r5["tables"]), r5)
check("unknown table -> 404", call("POST", f"{M}/sync", {**body, "tables": ["nope"]})[0] == 404)
check("bad container name -> 400", call("POST", f"{M}/sync", {"container": "A_B"})[0] == 400)
check("missing database -> 404", call("POST", "/servers/srv/databases/zzz/mirror/sync", body)[0] == 404)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
