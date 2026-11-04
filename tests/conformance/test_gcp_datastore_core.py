"""Cloud Datastore API v1 (Firestore in Datastore mode) conformance.
Run: PYTHONPATH=. python tests/conformance/test_gcp_datastore_core.py"""
import json

try:
    from core import gcp_firestore_core as fs, gcp_datastore_core as ds
except ImportError:  # pragma: no cover
    import gcp_firestore_core as fs  # type: ignore
    import gcp_datastore_core as ds  # type: ignore

P = "demo"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(st, verb, body=None, headers=None):
    r = ds.dispatch(st, "POST", f"/v1/projects/{P}:{verb}", {}, headers or {}, json.dumps(body or {}).encode())
    return r.status, json.loads(r.body or b"{}")


def S(x): return {"stringValue": x}
def I(x): return {"integerValue": str(x)}
def key(*els, ns=None):
    k = {"path": [{"kind": k, **({"name": v} if isinstance(v, str) else {"id": str(v)} if v else {})} for k, v in els]}
    if ns: k["partitionId"] = {"namespaceId": ns}
    return k


def run() -> int:
    st = fs.FirestoreStore()
    _check("native default DB refuses the Datastore API", call(st, "lookup", {"keys": [key(("A", "x"))]})[0] == 400)
    r = fs.dispatch(st, "POST", f"/v1/projects/{P}/databases", {"databaseId": "(default)"}, {}, json.dumps({"type": "DATASTORE_MODE", "locationId": "us-central1"}).encode())
    _check("datastore-mode database created", r.status == 200 and json.loads(r.body)["type"] == "DATASTORE_MODE")
    _check("native api refused? n/a; lookup on empty DB ok", call(st, "lookup", {"keys": [key(("Task", "t1"))]})[1]["missing"][0]["entity"]["key"]["path"][0]["name"] == "t1")

    def commit(muts, mode="NON_TRANSACTIONAL", **kw):
        return call(st, "commit", {"mode": mode, "mutations": muts, **kw})

    s, c = commit([{"insert": {"key": key(("Task", "t1")), "properties": {"title": S("write docs"), "prio": I(3), "tags": {"arrayValue": {"values": [S("a"), S("b")]}}}}},
                   {"insert": {"key": key(("Task", None)), "properties": {"title": S("auto id"), "prio": I(1)}}},
                   {"upsert": {"key": key(("Task", "t3")), "properties": {"title": S("third"), "prio": I(2)}}}])
    _check("commit 200 with three results", s == 200 and len(c["mutationResults"]) == 3)
    auto = c["mutationResults"][1]["key"]
    _check("incomplete key got an allocated id", auto and int(auto["path"][0]["id"]) > 0)
    _check("insert of existing entity -> ALREADY_EXISTS", commit([{"insert": {"key": key(("Task", "t1")), "properties": {}}}])[0] == 409)
    _check("update of missing entity -> NOT_FOUND", commit([{"update": {"key": key(("Task", "zz")), "properties": {}}}])[0] == 404)
    _check("incomplete key on update refused", commit([{"update": {"key": key(("Task", None)), "properties": {}}}])[0] == 400)
    _check("failed commit changes nothing (atomic)",
           commit([{"upsert": {"key": key(("Task", "t9")), "properties": {}}}, {"insert": {"key": key(("Task", "t1")), "properties": {}}}])[0] == 409
           and call(st, "lookup", {"keys": [key(("Task", "t9"))]})[1]["found"] == [])
    s, l = call(st, "lookup", {"keys": [key(("Task", "t1")), key(("Task", "nope"))]})
    _check("lookup found + missing", len(l["found"]) == 1 and len(l["missing"]) == 1 and l["found"][0]["entity"]["properties"]["prio"]["integerValue"] == "3")
    ver = l["found"][0]["version"]
    _check("baseVersion conflict aborts", commit([{"update": {"key": key(("Task", "t1")), "properties": {"title": S("x")}}, "baseVersion": "99"}])[0] == 409)
    _check("update with right baseVersion", commit([{"update": {"key": key(("Task", "t1")), "properties": {"title": S("write docs v2"), "prio": I(3), "tags": {"arrayValue": {"values": [S("a"), S("b")]}}}}, "baseVersion": ver}])[0] == 200)
    _check("version incremented", call(st, "lookup", {"keys": [key(("Task", "t1"))]})[1]["found"][0]["version"] == str(int(ver) + 1))

    def q(**kw):
        s, r = call(st, "runQuery", {"query": {"kind": [{"name": "Task"}], **kw}})
        return s, r
    s, r = q()
    _check("kind query returns all 3", s == 200 and len(r["batch"]["entityResults"]) == 3 and r["batch"]["moreResults"] == "NO_MORE_RESULTS")
    flt = lambda p, op, v: {"propertyFilter": {"property": {"name": p}, "op": op, "value": v}}
    _check("EQUAL filter", len(q(filter=flt("title", "EQUAL", S("third")))[1]["batch"]["entityResults"]) == 1)
    _check("array property matches any element", len(q(filter=flt("tags", "EQUAL", S("b")))[1]["batch"]["entityResults"]) == 1)
    _check("inequality + same-property order", [x["entity"]["properties"]["prio"]["integerValue"] for x in q(filter=flt("prio", "GREATER_THAN_OR_EQUAL", I(2)), order=[{"property": {"name": "prio"}, "direction": "DESCENDING"}])[1]["batch"]["entityResults"]] == ["3", "2"])
    s, e = q(filter=flt("prio", "GREATER_THAN", I(0)), order=[{"property": {"name": "title"}}])
    _check("inequality ordered by another property needs a composite index", s == 400 and "no matching index found" in e["error"]["message"])
    ri = ds.dispatch(st, "POST", f"/v1/projects/{P}/indexes", {}, {}, json.dumps({"kind": "Task", "properties": [{"name": "prio"}, {"name": "title"}]}).encode())
    _check("composite index created READY", ri.status == 200 and json.loads(ri.body)["response"]["state"] == "READY")
    _check("same query passes with the index", q(filter=flt("prio", "GREATER_THAN", I(0)), order=[{"property": {"name": "title"}}])[0] == 200)
    _check("list indexes", len(json.loads(ds.dispatch(st, "GET", f"/v1/projects/{P}/indexes", {}, {}, b"").body)["indexes"]) == 1)
    # limit + cursor paging
    s, p1 = q(order=[{"property": {"name": "title"}}], limit=2)
    _check("limit pages with MORE_RESULTS_AFTER_LIMIT", len(p1["batch"]["entityResults"]) == 2 and p1["batch"]["moreResults"] == "MORE_RESULTS_AFTER_LIMIT")
    s, p2 = q(order=[{"property": {"name": "title"}}], startCursor=p1["batch"]["endCursor"])
    _check("startCursor continues", len(p2["batch"]["entityResults"]) == 1)
    _check("keys-only projection", all(set(x["entity"]) == {"key"} for x in q(projection=[{"property": {"name": "__key__"}}])[1]["batch"]["entityResults"]))
    _check("property projection", set(q(projection=[{"property": {"name": "prio"}}])[1]["batch"]["entityResults"][0]["entity"]["properties"]) == {"prio"})
    # GQL
    s, g = call(st, "runQuery", {"gqlQuery": {"queryString": "SELECT * FROM Task WHERE prio >= @p ORDER BY prio DESC LIMIT 5", "namedBindings": {"p": {"value": I(2)}}, "allowLiterals": True}})
    _check("GQL SELECT with bindings", s == 200 and len(g["batch"]["entityResults"]) == 2)
    # ancestors + namespaces
    commit([{"insert": {"key": key(("User", "bob"), ("Note", "n1")), "properties": {"t": S("hi")}}},
            {"insert": {"key": key(("Note", "n1"), ns="tenant-b"), "properties": {"t": S("other ns")}}}])
    anc = {"propertyFilter": {"property": {"name": "__key__"}, "op": "HAS_ANCESTOR", "value": {"keyValue": key(("User", "bob"))}}}
    s, r = call(st, "runQuery", {"query": {"kind": [{"name": "Note"}], "filter": anc}})
    _check("HAS_ANCESTOR query", len(r["batch"]["entityResults"]) == 1)
    s, r = call(st, "runQuery", {"partitionId": {"namespaceId": "tenant-b"}, "query": {"kind": [{"name": "Note"}]}})
    _check("namespace isolation", len(r["batch"]["entityResults"]) == 1 and r["batch"]["entityResults"][0]["entity"]["properties"]["t"]["stringValue"] == "other ns")
    s, r = call(st, "runQuery", {"query": {"kind": [{"name": "Note"}]}})
    _check("default namespace does not see tenant-b", len(r["batch"]["entityResults"]) == 1 and r["batch"]["entityResults"][0]["entity"]["properties"]["t"]["stringValue"] == "hi")
    # aggregations
    s, a = call(st, "runAggregationQuery", {"aggregationQuery": {"nestedQuery": {"kind": [{"name": "Task"}]}, "aggregations": [{"count": {}, "alias": "n"}, {"sum": {"property": {"name": "prio"}}, "alias": "s"}, {"avg": {"property": {"name": "prio"}}, "alias": "a"}]}})
    ap = a["batch"]["aggregationResults"][0]["aggregateProperties"]
    _check("COUNT/SUM/AVG", ap["n"]["integerValue"] == "3" and ap["s"]["integerValue"] == "6" and abs(ap["a"]["doubleValue"] - 2.0) < 1e-9)
    # transactions + delete
    s, t = call(st, "beginTransaction", {})
    _check("beginTransaction returns id", s == 200 and t["transaction"])
    _check("commit in a transaction", commit([{"delete": key(("Task", "t3"))}], mode="TRANSACTIONAL", transaction=t["transaction"])[0] == 200)
    _check("reusing a finished transaction refused", commit([], mode="TRANSACTIONAL", transaction=t["transaction"])[0] == 400)
    _check("deleted entity gone", call(st, "lookup", {"keys": [key(("Task", "t3"))]})[1]["found"] == [])
    s, ids = call(st, "allocateIds", {"keys": [key(("Task", None)), key(("Task", None))]})
    _check("allocateIds returns distinct ids", s == 200 and len({k["path"][0]["id"] for k in ids["keys"]}) == 2)
    _check("allocateIds refuses complete keys", call(st, "allocateIds", {"keys": [key(("Task", "x"))]})[0] == 400)
    _check("oversized string rejected", commit([{"upsert": {"key": key(("Task", "big")), "properties": {"x": S("a" * 1048600)}}}])[0] == 400)
    print("datastore core: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
