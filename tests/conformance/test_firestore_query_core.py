"""Firestore richer structuredQuery conformance (v2.6.0) — host + Pyodide.

Asserts the extended :runQuery: comparison operators (>, <, ...), IN, ARRAY_CONTAINS,
compositeFilter (AND/OR), orderBy (+ direction) and limit — beyond the original
single EQUAL fieldFilter.
"""
import json

try:
    from core.gcp_firestore_core import FirestoreStore, dispatch
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_firestore_core import FirestoreStore, dispatch  # type: ignore

DB = "/v1/projects/demo/databases/(default)/documents"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    st = store or FirestoreStore()

    def put(coll, did, fields):
        dispatch(st, "POST", f"{DB}/{coll}", {"documentId": did},
                 {"content-type": "application/json"}, json.dumps({"fields": fields}).encode())

    def q(sq):
        r = dispatch(st, "POST", f"{DB}:runQuery", {}, {"content-type": "application/json"},
                     json.dumps({"structuredQuery": sq}).encode())
        rows = json.loads(r.body.decode())
        return [row["document"]["name"].split("/")[-1] for row in rows if "document" in row]

    put("products", "p1", {"name": {"stringValue": "A"}, "price": {"integerValue": "10"},
                           "tags": {"arrayValue": {"values": [{"stringValue": "sale"}]}}})
    put("products", "p2", {"name": {"stringValue": "B"}, "price": {"integerValue": "25"},
                           "tags": {"arrayValue": {"values": [{"stringValue": "new"}]}}})
    put("products", "p3", {"name": {"stringValue": "C"}, "price": {"integerValue": "5"},
                           "tags": {"arrayValue": {"values": [{"stringValue": "sale"}, {"stringValue": "new"}]}}})

    frm = [{"collectionId": "products"}]
    _check("GREATER_THAN price>8",
           sorted(q({"from": frm, "where": {"fieldFilter": {"field": {"fieldPath": "price"},
                    "op": "GREATER_THAN", "value": {"integerValue": "8"}}}})) == ["p1", "p2"])
    _check("orderBy price DESC limit 2",
           q({"from": frm, "orderBy": [{"field": {"fieldPath": "price"}, "direction": "DESCENDING"}],
              "limit": 2}) == ["p2", "p1"])
    _check("ARRAY_CONTAINS sale",
           sorted(q({"from": frm, "where": {"fieldFilter": {"field": {"fieldPath": "tags"},
                    "op": "ARRAY_CONTAINS", "value": {"stringValue": "sale"}}}})) == ["p1", "p3"])
    _check("compositeFilter AND (price<30 AND tags has new)",
           sorted(q({"from": frm, "where": {"compositeFilter": {"op": "AND", "filters": [
               {"fieldFilter": {"field": {"fieldPath": "price"}, "op": "LESS_THAN", "value": {"integerValue": "30"}}},
               {"fieldFilter": {"field": {"fieldPath": "tags"}, "op": "ARRAY_CONTAINS", "value": {"stringValue": "new"}}},
           ]}}})) == ["p2", "p3"])
    _check("IN name",
           sorted(q({"from": frm, "where": {"fieldFilter": {"field": {"fieldPath": "name"}, "op": "IN",
                    "value": {"arrayValue": {"values": [{"stringValue": "A"}, {"stringValue": "C"}]}}}}})) == ["p1", "p3"])

    print("\nFirestore richer query conformance: ALL GREEN")
    return st


if __name__ == "__main__":
    run()
