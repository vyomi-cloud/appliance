"""Firestore INSIGHTS + KEY VISUALIZER conformance (WAVE 5b depth:
gcp.firestore.insights, gcp.firestore.key-visualizer) — both features are derived from
real request activity recorded by the core as it happens (missing-index query failures,
composite-index hits, per-document read/write counts), never synthetic/random data.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_firestore_telemetry_core.py
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


def run() -> int:
    st = FirestoreStore()
    db = "(default)"

    fs.dispatch(st, "POST", f"{DB_BASE}", {"databaseId": db}, {}, b"{}")

    # 1. Insights and Key Visualizer start empty: no requests yet.
    empty = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/{db}:insights", {}, {}, b""))
    _check("insights starts with zero queries", empty["totalQueries"] == 0)
    _check("insights starts with no recommendations", empty["indexRecommendations"] == [])
    kv_empty = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/{db}:keyVisualizer", {}, {}, b""))
    _check("key visualizer starts with no hottest keys", kv_empty["hottestKeys"] == [])

    fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents/widgets", {"documentId": "w1"}, {},
               json.dumps({"fields": {"price": {"integerValue": "10"}}}).encode())

    # 2. Exempt `price` from automatic indexing, then run an inequality query that needs
    # an index -> a REAL recommendation appears, derived from the actual failed query.
    fs.dispatch(st, "PATCH", f"{DB_BASE}/{db}/collectionGroups/widgets/fields/price", {}, {},
               json.dumps({"indexConfig": {"indexes": [], "usesAncestorConfig": False}}).encode())
    q = json.dumps({"structuredQuery": {"from": [{"collectionId": "widgets"}],
                    "where": {"fieldFilter": {"field": {"fieldPath": "price"}, "op": "GREATER_THAN",
                                               "value": {"integerValue": "0"}}}}}).encode()
    for _ in range(3):
        fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, q)
    after_fail = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/{db}:insights", {}, {}, b""))
    _check("insights counted 3 queries", after_fail["totalQueries"] == 3)
    _check("insights recommends an index for widgets.price",
           any(r["collectionGroup"] == "widgets" and r["fieldPath"] == "price" for r in after_fail["indexRecommendations"]))
    _check("insights recommendation occurrence count reflects real repeated failures",
           next(r for r in after_fail["indexRecommendations"] if r["fieldPath"] == "price")["occurrences"] == 3)
    _check("insights totals queries that failed on a missing index", after_fail["queriesMissingIndex"] == 3)

    # 3. Create the recommended index — the query now succeeds and the index shows up as
    # USED (not in unusedIndexes), again derived from the real follow-up query.
    fs.dispatch(st, "POST", f"{DB_BASE}/{db}/collectionGroups/widgets/indexes", {}, {},
               json.dumps({"queryScope": "COLLECTION",
                           "fields": [{"fieldPath": "price", "order": "ASCENDING"}]}).encode())
    ok = fs.dispatch(st, "POST", f"{DB_BASE}/{db}/documents:runQuery", {}, {}, q)
    _check("query succeeds once the recommended index exists", ok.status == 200)
    after_idx = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/{db}:insights", {}, {}, b""))
    _check("the newly created index is not reported unused (it was just matched)",
           not any(u["collectionGroup"] == "widgets" for u in after_idx["unusedIndexes"]))

    # 4. An index that never gets matched by any query shows up as unused.
    fs.dispatch(st, "POST", f"{DB_BASE}/{db}/collectionGroups/orphans/indexes", {}, {},
               json.dumps({"queryScope": "COLLECTION",
                           "fields": [{"fieldPath": "never_queried", "order": "ASCENDING"}]}).encode())
    after_orphan = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/{db}:insights", {}, {}, b""))
    _check("an index nothing ever queried against is reported unused",
           any(u["collectionGroup"] == "orphans" for u in after_orphan["unusedIndexes"]))

    # 5. Key Visualizer reflects real per-document access counts recorded so far.
    for _ in range(5):
        fs.dispatch(st, "GET", f"{DB_BASE}/{db}/documents/widgets/w1", {}, {}, b"")
    fs.dispatch(st, "GET", f"{DB_BASE}/{db}/documents/widgets/w1_absent", {}, {}, b"")  # not found — not tracked as access
    kv = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/{db}:keyVisualizer", {}, {}, b""))
    hottest = {h["key"]: h["count"] for h in kv["hottestKeys"]}
    _check("key visualizer counts real repeated reads of the same document",
           hottest.get("widgets/w1", 0) >= 5)
    widgets_row = next((r for r in kv["rows"] if r["collection"] == "widgets"), None)
    _check("key visualizer groups by collection and reports a real total", widgets_row is not None and widgets_row["total"] >= 5)
    _check("key visualizer buckets into a fixed-size heatmap row", len(widgets_row["buckets"]) == 8)

    # 6. Deleting the database clears all telemetry (no stale cross-database leakage).
    fs.dispatch(st, "DELETE", f"{DB_BASE}/{db}", {}, {}, b"")
    _check("insights state is gone after database delete", db not in st.index_recommendations)
    _check("key access state is gone after database delete", db not in st.key_access)

    print("\nFirestore insights + Key Visualizer conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
