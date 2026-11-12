"""Cosmos export endpoints for BI tools (OData feed / CSV / JSON / Parquet) over REAL container data.
Run: PYTHONPATH=. python tests/conformance/test_azure_cosmos_export.py   (Parquet checks need pyarrow; skipped otherwise)"""
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_cosmos_core as c  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


st = c.CosmosStore()
d = lambda m, p, b=None, h=None, q=None: c.dispatch(st, m, p, q or {}, h or {}, json.dumps(b).encode() if b is not None else b"")
d("POST", "/dbs", {"id": "shop"})
d("POST", "/dbs/shop/colls", {"id": "orders", "partitionKey": {"paths": ["/cust"], "kind": "Hash"}})
for i in range(3):
    d("POST", "/dbs/shop/colls/orders/docs", {"id": f"o{i}", "cust": f"c{i % 2}", "total": 10 * (i + 1), "paid": i % 2 == 0, "addr": {"city": "Pune"}, "tags": ["a", "b"]})

r = d("GET", "/vyomi/odata/shop")
check("OData service document lists the container as an entity set", r.status == 200 and json.loads(r.body)["value"][0] == {"name": "orders", "kind": "EntitySet", "url": "orders"}, r.body)
r = d("GET", "/vyomi/odata/shop/$metadata")
check("$metadata declares typed properties", r.status == 200 and b'EntityType Name="orders"' in r.body and b'Name="total" Type="Edm.Int64"' in r.body
      and b'Name="paid" Type="Edm.Boolean"' in r.body and b'Name="addr_city"' in r.body, r.body)
r = d("GET", "/vyomi/odata/shop/orders")
v = json.loads(r.body)["value"]
check("OData feed returns the real documents without system properties", len(v) == 3 and v[0]["total"] == 10 and "_rid" not in v[0] and v[0]["addr_city"] == "Pune", v)
check("$top/$skip honoured", len(json.loads(d("GET", "/vyomi/odata/shop/orders", q={"$top": "1", "$skip": "1"}).body)["value"]) == 1)
r = d("GET", "/vyomi/export/shop/orders.csv")
rows = list(csv.DictReader(io.StringIO(r.body.decode())))
check("CSV export has the real rows and flattened columns", r.status == 200 and len(rows) == 3 and rows[2]["total"] == "30" and rows[0]["addr.city"] == "Pune", r.body)
check("JSON export", len(json.loads(d("GET", "/vyomi/export/shop/orders.json").body)["value"]) == 3)
check("export reflects new writes", (d("POST", "/dbs/shop/colls/orders/docs", {"id": "o9", "cust": "c9", "total": 99}), len(list(csv.DictReader(io.StringIO(d("GET", "/vyomi/export/shop/orders.csv").body.decode()))))== 4)[1])
check("unknown container 404", d("GET", "/vyomi/export/shop/nope.csv").status == 404)
check("unknown database 404", d("GET", "/vyomi/odata/nope").status == 404)
check("unknown format 400", d("GET", "/vyomi/export/shop/orders.xlsx").status == 400)
check("export is read-only", d("POST", "/vyomi/export/shop/orders.csv", {}).status == 405)
try:
    import pyarrow.parquet as pq
    from core import parquet_pyarrow
    parquet_pyarrow.install()
    r = d("GET", "/vyomi/export/shop/orders.parquet")
    t = pq.read_table(io.BytesIO(r.body))
    check("Parquet export is a real Parquet file with typed columns", r.status == 200 and t.num_rows == 4 and str(t.schema.field("paid").type) == "bool", t.schema if r.status == 200 else r.body)
except ImportError:
    print("[SKIP] pyarrow not installed: Parquet checks skipped")
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
