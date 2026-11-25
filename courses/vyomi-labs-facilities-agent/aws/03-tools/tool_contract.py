import json

import boto3

lam, ddb = boto3.client("lambda"), boto3.client("dynamodb")


def call(fn, payload):
    r = lam.invoke(FunctionName=fn, Payload=json.dumps(payload).encode())
    return json.loads(r["Payload"].read())


# Read tool: bad input never reaches DynamoDB.
for bad in ("B-12'; DROP TABLE assets;--", "../../etc/passwd", "", None, 12, "b-12", "B-12 " + "x" * 400):
    out = call("facilities-asset-status", {"asset_id": bad})
    assert out.get("error") == "invalid_input", "hostile asset_id %r was not refused: %s" % (bad, out)
assert call("facilities-asset-status", {}).get("error") == "invalid_input"
print("read tool: 8 hostile or malformed inputs refused")
assert call("facilities-asset-status", {"asset_id": "B-12"})["found"] is True       # and the good one still works

# Write tool: schema is enforced too.
base = {"request_id": "req-contract01", "asset_id": "B-12", "summary": "Inspect the boiler PRV", "priority": "P2", "requester": "contract-test"}
for patch in ({"priority": "URGENT"}, {"summary": "x" * 500}, {"asset_id": "B-12; DELETE"}, {"summary": ""}):
    out = call("facilities-create-work-order", dict(base, **patch))
    assert out.get("error") == "invalid_input", "invalid request %r was not refused: %s" % (patch, out)
print("write tool: 4 invalid requests refused")

# Idempotency: the same approved request twice produces ONE work order.
first = call("facilities-create-work-order", base)
second = call("facilities-create-work-order", base)
rows = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["requester"]["S"] == "contract-test"]
assert first["work_order_id"] == second["work_order_id"], "a replay must return the same work order"
assert first["replayed"] is False and second["replayed"] is True, (first, second)
assert len(rows) == 1, "expected exactly one work order, found %d" % len(rows)
print("idempotent: replay returned", second["work_order_id"], "(replayed=True) and the table holds", len(rows), "row")
print("tool contract verified")
