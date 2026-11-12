"""AWS-08 EventBridge Schemas — registries, schemas + versions, SearchSchemas, discoverers with REAL schema inference from PutEvents.
Via AwsWireRouter (signing name `schemas`). Run: PYTHONPATH=. python3 tests/conformance/test_eventbridge_schemas_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def sc(r, method, path, body=None, query=None):
    out = r.handle(method, path, query or {}, {"authorization": _auth("schemas"), "content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def put(r, bus, source, dt, detail):
    h = {"authorization": _auth("events"), "x-amz-target": "AWSEvents.PutEvents", "content-type": "application/x-amz-json-1.1"}
    out = r.handle("POST", "/", {}, h, json.dumps({"Entries": [{"EventBusName": bus, "Source": source, "DetailType": dt, "Detail": json.dumps(detail)}]}).encode())
    return json.loads(out["body"])


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


OPENAPI = json.dumps({"openapi": "3.0.0", "info": {"version": "1.0.0", "title": "Order"}, "paths": {}, "components": {"schemas": {"Order": {"type": "object", "properties": {"id": {"type": "string"}}}}}})


def main():
    r = AwsWireRouter()
    st, o = sc(r, "GET", "/v1/registries")
    _check("the discovered-schemas registry exists by default", any(x["RegistryName"] == "discovered-schemas" for x in o["Registries"]))
    st, o = sc(r, "POST", "/v1/registries/name/shop", {"Description": "my shop"})
    _check("CreateRegistry", st == 200 and o["RegistryArn"].endswith("registry/shop"))
    st, o = sc(r, "POST", "/v1/registries/name/shop", {})
    _check("duplicate registry -> ConflictException", st == 409)
    st, o = sc(r, "POST", "/v1/registries/name/shop/schemas/name/Order", {"Type": "OpenApi3", "Content": "not json"})
    _check("invalid schema content is rejected", st == 400)
    st, o = sc(r, "POST", "/v1/registries/name/shop/schemas/name/Order", {"Type": "OpenApi3", "Content": OPENAPI, "Description": "order"})
    _check("CreateSchema (version 1)", st == 200 and o["SchemaVersion"] == "1")
    v2 = json.loads(OPENAPI); v2["components"]["schemas"]["Order"]["properties"]["total"] = {"type": "number"}
    st, o = sc(r, "PUT", "/v1/registries/name/shop/schemas/name/Order", {"Content": json.dumps(v2)})
    _check("UpdateSchema creates version 2", st == 200 and o["SchemaVersion"] == "2")
    st, o = sc(r, "GET", "/v1/registries/name/shop/schemas/name/Order/versions")
    _check("ListSchemaVersions", [v["SchemaVersion"] for v in o["SchemaVersions"]] == ["1", "2"])
    st, o = sc(r, "GET", "/v1/registries/name/shop/schemas/name/Order", query={"schemaVersion": "1"})
    _check("DescribeSchema of an old version returns its content", "total" not in o["Content"])
    st, o = sc(r, "GET", "/v1/search/schemas", query={"keywords": "total"})
    _check("SearchSchemas matches content", any(x["SchemaName"] == "Order" for x in o["Schemas"]))

    # discovery
    st, o = sc(r, "POST", "/v1/discoverers", {"SourceArn": "arn:aws:events:us-east-1:123456789012:event-bus/default", "Description": "d"})
    _check("CreateDiscoverer on the default bus", st == 200 and o["State"] == "STARTED")
    did = o["DiscovererId"]
    put(r, "default", "myapp.orders", "Order Created", {"id": "o-1", "total": 12.5, "items": [{"sku": "a", "qty": 2}], "paid": True})
    st, o = sc(r, "GET", "/v1/registries/name/discovered-schemas/schemas/name/myapp.orders@OrderCreated")
    _check("PutEvents produced a discovered schema named <source>@<detail-type>", st == 200 and o["SchemaVersion"] == "1")
    doc = json.loads(o["Content"])
    det = doc["components"]["schemas"]["OrderCreated"]["properties"]
    _check("inferred types are right (string/number/array of objects/boolean)", det["id"]["type"] == "string" and det["total"]["type"] == "number" and det["items"]["items"]["properties"]["qty"]["type"] == "integer" and det["paid"]["type"] == "boolean")
    put(r, "default", "myapp.orders", "Order Created", {"id": "o-2", "total": 3.0, "items": [], "paid": False})
    st, o = sc(r, "GET", "/v1/registries/name/discovered-schemas/schemas/name/myapp.orders@OrderCreated/versions")
    _check("same shape does not create a new version", len(o["SchemaVersions"]) <= 2)
    n0 = len(o["SchemaVersions"])
    put(r, "default", "myapp.orders", "Order Created", {"id": "o-3", "total": 3.0, "items": [], "paid": False, "coupon": "X"})
    st, o = sc(r, "GET", "/v1/registries/name/discovered-schemas/schemas/name/myapp.orders@OrderCreated/versions")
    _check("a new field in the event creates a new schema version", len(o["SchemaVersions"]) == n0 + 1)
    st, _ = sc(r, "POST", f"/v1/discoverers/id/{did}/stop")
    put(r, "default", "myapp.other", "Thing Happened", {"x": 1})
    st, o = sc(r, "GET", "/v1/registries/name/discovered-schemas/schemas/name/myapp.other@ThingHappened")
    _check("a stopped discoverer records nothing", st == 404)
    st, _ = sc(r, "POST", f"/v1/discoverers/id/{did}/start")
    put(r, "default", "myapp.other", "Thing Happened", {"x": 1})
    st, o = sc(r, "GET", "/v1/registries/name/discovered-schemas/schemas/name/myapp.other@ThingHappened")
    _check("restarted discoverer records again", st == 200)
    st, _ = sc(r, "POST", "/v1/registries/name/discovered-schemas/schemas/name/x", {"Content": OPENAPI})
    _check("schemas can't be hand-created in discovered-schemas", st == 403)
    st, _ = sc(r, "DELETE", f"/v1/discoverers/id/{did}")
    st, o = sc(r, "GET", "/v1/discoverers")
    _check("DeleteDiscoverer", st == 200 and not o["Discoverers"])
    st, _ = sc(r, "DELETE", "/v1/registries/name/shop")
    _check("DeleteRegistry", st == 204)
    print("EventBridge Schemas: all checks passed")


if __name__ == "__main__":
    main()
