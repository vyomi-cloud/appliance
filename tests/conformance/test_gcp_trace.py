"""Cloud Trace v1/v2, Trace scopes, Log scopes (run: PYTHONPATH=. python3 tests/conformance/test_gcp_trace.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False   # engine test: ad-hoc project ids
R = AwsWireRouter()
PASS = FAIL = 0
P = "trace-proj-1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


T1, T2 = "a" * 32, "b" * 32


def span(t, s, name, st, en, parent=None, kind="SERVER", attrs=None):
    d = {"name": f"projects/{P}/traces/{t}/spans/{s}", "spanId": s, "displayName": {"value": name},
         "startTime": st, "endTime": en, "spanKind": kind}
    if parent:
        d["parentSpanId"] = parent
    if attrs:
        d["attributes"] = {"attributeMap": {k: {"stringValue": {"value": v}} for k, v in attrs.items()}}
    return d


s1, s2 = "1" * 16, "2" * 16
st, _ = call("POST", f"/v2/projects/{P}/traces:batchWrite", {"spans": [
    span(T1, s1, "GET /checkout", "2026-11-04T10:00:00Z", "2026-11-04T10:00:00.500Z", attrs={"/http/method": "GET"}),
    span(T1, s2, "db.query", "2026-11-04T10:00:00.1Z", "2026-11-04T10:00:00.3Z", parent=s1, kind="CLIENT")]})
check("batchWrite ok", st == 200)
call("POST", f"/v2/projects/{P}/traces:batchWrite", {"spans": [span(T2, s1, "GET /health", "2026-11-04T11:00:00Z", "2026-11-04T11:00:00.010Z")]})

st, e = call("POST", f"/v2/projects/{P}/traces:batchWrite", {"spans": [span(T1, "3" * 16, "x", "2026-11-04T10:00:05Z", "2026-11-04T10:00:01Z")]})
check("end before start rejected", st == 400 and e["error"]["status"] == "INVALID_ARGUMENT")
st, _ = call("POST", f"/v2/projects/{P}/traces:batchWrite", {"spans": [{**span(T1, "4" * 16, "x", "2026-11-04T10:00:00Z", "2026-11-04T10:00:01Z"), "spanId": "5" * 16}]})
check("spanId/name mismatch rejected", st == 400)
st, _ = call("POST", f"/v2/projects/{P}/traces:batchWrite", {"spans": [span("zz", s1, "x", "2026-11-04T10:00:00Z", "2026-11-04T10:00:01Z")]})
check("bad trace id rejected", st == 400)
st, _ = call("POST", f"/v2/projects/other-project-x/traces:batchWrite", {"spans": [span(T1, s1, "x", "2026-11-04T10:00:00Z", "2026-11-04T10:00:01Z")]})
check("project mismatch rejected", st == 400)
st, _ = call("POST", f"/v2/projects/{P}/traces:batchWrite", {"spans": [span(T1, "6" * 16, "ok", "2026-11-04T10:00:00Z", "2026-11-04T10:00:01Z"), span(T1, "7", "bad", "2026-11-04T10:00:00Z", "2026-11-04T10:00:01Z")]})
st2, g = call("GET", f"/v1/projects/{P}/traces/{T1}")
check("batch is atomic", st == 400 and len(g["spans"]) == 2)
check("get trace COMPLETE v1 shape", st2 == 200 and g["spans"][0]["kind"] == "RPC_SERVER" and g["spans"][1]["parentSpanId"] == s1 and g["spans"][0]["labels"]["/http/method"] == "GET")
check("get missing 404", call("GET", f"/v1/projects/{P}/traces/{'c' * 32}")[0] == 404)

_, l = call("GET", f"/v1/projects/{P}/traces")
check("list MINIMAL has no spans", len(l["traces"]) == 2 and "spans" not in l["traces"][0])
_, l = call("GET", f"/v1/projects/{P}/traces", query={"view": "ROOTSPAN", "filter": "span:db"})
check("filter span: + ROOTSPAN", [t["traceId"] for t in l["traces"]] == [T1] and len(l["traces"][0]["spans"]) == 1)
_, l = call("GET", f"/v1/projects/{P}/traces", query={"filter": "latency:100ms"})
check("filter latency", [t["traceId"] for t in l["traces"]] == [T1])
_, l = call("GET", f"/v1/projects/{P}/traces", query={"filter": '+root:"GET /health"'})
check("filter +root exact", [t["traceId"] for t in l["traces"]] == [T2])
_, l = call("GET", f"/v1/projects/{P}/traces", query={"startTime": "2026-11-04T10:30:00Z"})
check("startTime window", [t["traceId"] for t in l["traces"]] == [T2])
_, l = call("GET", f"/v1/projects/{P}/traces", query={"pageSize": "1", "orderBy": "start"})
check("paging + orderBy", len(l["traces"]) == 1 and l["traces"][0]["traceId"] == T1 and l.get("nextPageToken") == "1")
check("bad filter latency 400", call("GET", f"/v1/projects/{P}/traces", query={"filter": "latency:abc"})[0] == 400)
st, _ = call("PATCH", f"/v1/projects/{P}/traces", {"traces": [{"traceId": "d" * 32, "spans": [
    {"spanId": "11", "name": "legacy-root", "kind": "RPC_CLIENT", "startTime": "2026-11-04T12:00:00Z", "endTime": "2026-11-04T12:00:01Z", "labels": {"k": "v"}}]}]})
check("v1 patchTraces", st == 200 and call("GET", f"/v1/projects/{P}/traces/{'d' * 32}")[1]["spans"][0]["kind"] == "RPC_CLIENT")

# scopes
base = f"/v1/projects/{P}/locations/global/traceScopes"
_, l = call("GET", base)
check("default trace scope listed", l["traceScopes"][0]["name"].endswith("/_Default"))
st, sc = call("POST", base, {"resourceNames": [f"projects/{P}", "projects/other-proj-2"], "description": "x"}, {"traceScopeId": "myscope"})
check("create trace scope", st == 200 and sc["name"].endswith("/traceScopes/myscope") and sc["createTime"])
check("duplicate 409", call("POST", base, {"resourceNames": [f"projects/{P}"]}, {"traceScopeId": "myscope"})[0] == 409)
check("bad resource name 400", call("POST", base, {"resourceNames": ["buckets/x"]}, {"traceScopeId": "s2"})[0] == 400)
check("missing id 400", call("POST", base, {"resourceNames": [f"projects/{P}"]})[0] == 400)
st, sc = call("PATCH", base + "/myscope", {"description": "new"}, {"updateMask": "description"})
check("patch keeps resourceNames", st == 200 and sc["description"] == "new" and len(sc["resourceNames"]) == 2)
check("default immutable", call("DELETE", base + "/_Default")[0] == 400)
check("delete scope", call("DELETE", base + "/myscope")[0] == 200 and call("GET", base + "/myscope")[0] == 404)

lb = f"/v2/projects/{P}/locations/global/logScopes"
view = f"projects/{P}/locations/global/buckets/_Default/views/_AllLogs"
st, sc = call("POST", lb, {"resourceNames": [view]}, {"logScopeId": "ls1"})
check("create log scope", st == 200 and sc["name"].endswith("/logScopes/ls1"))
check("log scope bad view 400", call("POST", lb, {"resourceNames": ["nope"]}, {"logScopeId": "ls2"})[0] == 400)
_, l = call("GET", lb)
check("list log scopes incl default", [x["name"].split("/")[-1] for x in l["logScopes"]] == ["_Default", "ls1"])
check("delete log scope", call("DELETE", lb + "/ls1")[0] == 200)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
