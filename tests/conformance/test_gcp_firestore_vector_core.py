"""Firestore VECTOR INDEX + findNearest conformance (WAVE 5b depth: gcp.firestore.vector-indexes)
— a real vector field type, real brute-force k-NN search, and a real vector-index
requirement (findNearest on an unindexed field+dimension fails, exactly like production).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_firestore_vector_core.py
"""
import json

try:
    from core.gcp_firestore_core import FirestoreStore
    from core import gcp_firestore_core as fs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_firestore_core import FirestoreStore  # type: ignore
    import gcp_firestore_core as fs  # type: ignore

PROJECT = "demo-project"
DB_BASE = f"/v1/projects/{PROJECT}/databases"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def _vec(values):
    return fs._encode_vector(values)


def run() -> int:
    st = FirestoreStore()
    db = "(default)"

    # Seed three documents with 3-dimensional embeddings.
    docs = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.9, 0.1, 0.0],
        "c": [0.0, 1.0, 0.0],
    }
    for doc_id, vec in docs.items():
        fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents/items", {"documentId": doc_id}, {},
                   json.dumps({"fields": {"embedding": _vec(vec), "name": {"stringValue": doc_id}}}).encode())

    find_nearest_req = json.dumps({"structuredQuery": {
        "from": [{"collectionId": "items"}],
        "findNearest": {"vectorField": {"fieldPath": "embedding"}, "queryVector": _vec([1.0, 0.0, 0.0]),
                         "distanceMeasure": "EUCLIDEAN", "limit": 2},
    }}).encode()

    # 1. findNearest without a vector index fails — the index requirement is REAL, not
    # decorative: production Firestore also rejects findNearest with no matching index.
    no_index = fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, find_nearest_req)
    _check("findNearest without a vector index -> FAILED_PRECONDITION", no_index.status == 400)
    _check("missing vector index recorded as an insights recommendation",
           any(r["collectionGroup"] == "items" for r in st.index_recommendations.get(db, {}).values()))

    # 2. Create the vector index (3 dimensions) on items.embedding.
    ic = fs.dispatch(st, "POST", f"{DB_BASE}/{db}/collectionGroups/items/indexes", {}, {},
                     json.dumps({"queryScope": "COLLECTION",
                                 "fields": [{"fieldPath": "embedding", "vectorConfig": {"dimension": 3, "flat": {}}}]}).encode())
    _check("create vector index 200", ic.status == 200)
    idx = _jbody(ic)
    _check("vector index fields carry vectorConfig", idx["fields"][0]["vectorConfig"]["dimension"] == 3)

    # 3. findNearest now succeeds and returns the two closest vectors to [1,0,0] in order: a, b.
    ok = fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, find_nearest_req)
    _check("findNearest with a vector index -> 200", ok.status == 200)
    rows = _jbody(ok)
    names = [r["document"]["fields"]["name"]["stringValue"] for r in rows if "document" in r]
    _check("findNearest returns exactly 2 results (limit)", len(names) == 2)
    _check("findNearest orders by real distance: a (exact match) then b (close)", names == ["a", "b"])

    # 4. A different dimension still requires its own index.
    wrong_dim_req = json.dumps({"structuredQuery": {
        "from": [{"collectionId": "items"}],
        "findNearest": {"vectorField": {"fieldPath": "embedding"}, "queryVector": _vec([1.0, 0.0]),
                         "distanceMeasure": "EUCLIDEAN", "limit": 1},
    }}).encode()
    wrong_dim = fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, wrong_dim_req)
    _check("findNearest with an un-indexed dimension -> FAILED_PRECONDITION", wrong_dim.status == 400)

    # 5. COSINE distance measure also really changes the ranking: vector c=[0,1,0] is
    # closest to a query vector that leans toward the Y axis under cosine similarity.
    cosine_req = json.dumps({"structuredQuery": {
        "from": [{"collectionId": "items"}],
        "findNearest": {"vectorField": {"fieldPath": "embedding"}, "queryVector": _vec([0.1, 0.9, 0.0]),
                         "distanceMeasure": "COSINE", "limit": 1},
    }}).encode()
    cres = _jbody(fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, cosine_req))
    _check("COSINE findNearest picks the vector most aligned in direction",
           cres[0]["document"]["fields"]["name"]["stringValue"] == "c")

    # 6. distanceResultField actually attaches the computed distance to each result doc.
    annotated_req = json.dumps({"structuredQuery": {
        "from": [{"collectionId": "items"}],
        "findNearest": {"vectorField": {"fieldPath": "embedding"}, "queryVector": _vec([1.0, 0.0, 0.0]),
                         "distanceMeasure": "EUCLIDEAN", "limit": 1, "distanceResultField": "vector_distance"},
    }}).encode()
    ares = _jbody(fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, annotated_req))
    _check("distanceResultField attaches the real computed distance",
           ares[0]["document"]["fields"]["vector_distance"]["doubleValue"] == 0.0)

    print("\nFirestore vector-index conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
