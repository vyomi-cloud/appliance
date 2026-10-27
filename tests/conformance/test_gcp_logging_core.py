"""Unit tests for core/gcp_logging_core.py (run: python3 tests/conformance/test_gcp_logging_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_logging_core as lg  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, path, body=None, query=None):
    r = lg.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def main():
    st = lg.LoggingStore()
    LN = "projects/p1/logs/app"
    s, b = call(st, "POST", "/v2/entries:write", {"logName": LN, "resource": {"type": "gce_instance", "labels": {"zone": "us-central1-a"}},
        "entries": [{"textPayload": "hello world", "severity": "INFO"},
                    {"jsonPayload": {"user": {"id": 7}, "msg": "boom"}, "severity": "ERROR"},
                    {"textPayload": "debug line", "severity": 100, "labels": {"k": "v"}}]})
    check("entries.write ok", s == 200 and b == {}, b)
    s, b = call(st, "POST", "/v2/entries:write", {"entries": [{"textPayload": "x"}]})
    check("write without logName → 400", s == 400 and b["error"]["status"] == "INVALID_ARGUMENT", b)
    s, b = call(st, "POST", "/v2/entries:write", {"logName": "bad", "entries": [{"textPayload": "x"}]})
    check("write with malformed logName → 400", s == 400, b)
    L = lambda f, **kw: call(st, "POST", "/v2/entries:list", dict({"resourceNames": ["projects/p1"], "filter": f}, **kw))
    s, b = L("")
    check("list all (3, oldest first)", s == 200 and len(b["entries"]) == 3 and b["entries"][0]["textPayload"] == "hello world", b)
    check("entry defaults filled", all(e["insertId"] and e["timestamp"] and e["receiveTimestamp"] for e in b["entries"]))
    check("log name is normalised", b["entries"][0]["logName"] == LN)
    s, b = L("severity>=ERROR")
    check("filter severity>=ERROR", len(b["entries"]) == 1 and b["entries"][0]["severity"] == "ERROR", b)
    s, b = L('resource.type="gce_instance" AND resource.labels.zone:"central1"')
    check("filter resource.type AND labels", len(b["entries"]) == 3, b)
    s, b = L("jsonPayload.user.id=7")
    check("filter nested jsonPayload", len(b["entries"]) == 1, b)
    s, b = L('textPayload:"hello" OR severity=DEBUG')
    check("filter OR", len(b["entries"]) == 2, b)
    s, b = L("NOT severity=INFO -severity=DEBUG")
    check("filter NOT / -", len(b["entries"]) == 1, b)
    s, b = L("boom")
    check("global text search", len(b["entries"]) == 1, b)
    s, b = L('labels.k="v"')
    check("filter labels", len(b["entries"]) == 1, b)
    s, b = L('textPayload=~"^hel+o"')
    check("filter regex", len(b["entries"]) == 1, b)
    s, b = L('timestamp>="2000-01-01T00:00:00Z" AND (severity=INFO OR severity=ERROR)')
    check("filter timestamp + parentheses", len(b["entries"]) == 2, b)
    s, b = L("severity=(")
    check("bad filter → 400", s == 400 and b["error"]["status"] == "INVALID_ARGUMENT", b)
    s, b = L("", orderBy="timestamp desc", pageSize=2)
    check("list desc + pageSize", len(b["entries"]) == 2 and b["entries"][0]["severity"] == "DEFAULT" or b["entries"][0]["severity"] == "DEBUG" and b["nextPageToken"], b)
    s, b2 = L("", orderBy="timestamp desc", pageSize=2, pageToken=b["nextPageToken"])
    check("list next page", len(b2["entries"]) == 1 and "nextPageToken" not in b2, b2)
    s, b = call(st, "POST", "/v2/entries:list", {"filter": ""})
    check("list without resourceNames → 400", s == 400, b)

    s, b = call(st, "GET", "/v2/projects/p1/logs")
    check("logs.list", s == 200 and b["logNames"] == [LN], b)
    s, b = call(st, "DELETE", "/v2/projects/p1/logs/app")
    check("logs.delete", s == 200, b)
    s, b = call(st, "DELETE", "/v2/projects/p1/logs/app")
    check("logs.delete missing → 404", s == 404, b)
    s, b = call(st, "POST", "/v2/entries:write", {"logName": "projects/p1/logs/cloudaudit.googleapis.com%2Factivity", "entries": [{"textPayload": "a"}]})
    s, b = call(st, "GET", "/v2/projects/p1/logs")
    check("log id URL-encoded", b["logNames"] == ["projects/p1/logs/cloudaudit.googleapis.com%2Factivity"], b)

    S = "/v2/projects/p1/sinks"
    s, b = call(st, "POST", S, {"name": "s1", "destination": "storage.googleapis.com/my-bucket", "filter": "severity>=ERROR"}, {"uniqueWriterIdentity": "true"})
    check("create sink", s == 200 and b["name"] == "s1" and b["writerIdentity"].startswith("serviceAccount:service-") and b["createTime"], b)
    s, b = call(st, "POST", S, {"name": "s1", "destination": "storage.googleapis.com/my-bucket"})
    check("duplicate sink → 409", s == 409 and b["error"]["status"] == "ALREADY_EXISTS", b)
    s, b = call(st, "POST", S, {"name": "s2", "destination": "ftp://nope"})
    check("bad destination → 400", s == 400, b)
    s, b = call(st, "POST", S, {"name": "s2", "destination": "pubsub.googleapis.com/projects/p1/topics/t", "filter": "((("})
    check("bad sink filter → 400", s == 400, b)
    s, b = call(st, "GET", S + "/s1")
    check("get sink", s == 200 and b["destination"] == "storage.googleapis.com/my-bucket", b)
    s, b = call(st, "GET", S + "/nope")
    check("get missing sink → 404", s == 404 and b["error"]["status"] == "NOT_FOUND", b)
    s, b = call(st, "PUT", S + "/s1", {"destination": "storage.googleapis.com/other", "disabled": True}, {"updateMask": "destination,disabled"})
    check("update sink (mask)", s == 200 and b["destination"].endswith("other") and b["disabled"] is True and b["filter"] == "severity>=ERROR", b)
    s, b = call(st, "PATCH", S + "/s1", {"x": 1}, {"updateMask": "bogus"})
    check("bad update mask → 400", s == 400, b)
    s, b = call(st, "GET", S)
    check("list sinks", s == 200 and len(b["sinks"]) == 1, b)
    s, b = call(st, "DELETE", S + "/s1")
    check("delete sink", s == 200 and not st.sinks, b)

    M = "/v2/projects/p1/metrics"
    s, b = call(st, "POST", M, {"name": "m1", "filter": "severity>=ERROR", "description": "errors"})
    check("create metric", s == 200 and b["metricDescriptor"]["type"] == "logging.googleapis.com/user/m1" and b["metricDescriptor"]["metricKind"] == "DELTA", b)
    s, b = call(st, "POST", M, {"name": "m2"})
    check("metric without filter → 400", s == 400, b)
    s, b = call(st, "PUT", M + "/m1", {"filter": "severity>=WARNING", "description": "warnings"})
    check("update metric", s == 200 and b["filter"] == "severity>=WARNING" and b["description"] == "warnings", b)
    s, b = call(st, "GET", M)
    check("list metrics", len(b["metrics"]) == 1, b)
    s, b = call(st, "DELETE", M + "/m1")
    s, b = call(st, "GET", M + "/m1")
    check("delete metric", s == 404, b)

    X = "/v2/projects/p1/exclusions"
    s, b = call(st, "POST", X, {"name": "x1", "filter": "severity<WARNING", "description": "drop noise"})
    check("create exclusion", s == 200 and b["name"] == "x1", b)
    s, b = call(st, "PATCH", X + "/x1", {"disabled": True}, {"updateMask": "disabled"})
    check("patch exclusion", s == 200 and b["disabled"] is True, b)
    s, b = call(st, "PATCH", X + "/x1", {"disabled": True})
    check("patch exclusion without mask → 400", s == 400, b)
    s, b = call(st, "DELETE", X + "/x1")
    check("delete exclusion", s == 200 and not st.exclusions, b)

    B = "/v2/projects/p1/locations/global/buckets"
    s, b = call(st, "GET", B)
    check("default buckets exist", {x["name"].rsplit("/", 1)[1] for x in b["buckets"]} == {"_Default", "_Required"}, b)
    s, b = call(st, "POST", B, {"retentionDays": 90, "description": "audit"}, {"bucketId": "b1"})
    check("create bucket", s == 200 and b["retentionDays"] == 90 and b["lifecycleState"] == "ACTIVE", b)
    s, b = call(st, "PATCH", B + "/b1", {"retentionDays": 60}, {"updateMask": "retentionDays"})
    check("patch bucket", s == 200 and b["retentionDays"] == 60, b)
    s, b = call(st, "DELETE", B + "/_Default")
    check("delete _Default → 400", s == 400 and b["error"]["status"] == "FAILED_PRECONDITION", b)
    s, b = call(st, "DELETE", B + "/b1")
    s, b = call(st, "GET", B + "/b1")
    check("delete bucket is soft", b["lifecycleState"] == "DELETE_REQUESTED", b)
    s, b = call(st, "POST", B + "/b1:undelete")
    s, b = call(st, "GET", B + "/b1")
    check("undelete bucket", b["lifecycleState"] == "ACTIVE", b)

    s, b = call(st, "GET", "/v2/monitoredResourceDescriptors")
    check("monitoredResourceDescriptors", s == 200 and any(d["type"] == "gce_instance" for d in b["resourceDescriptors"]), b)
    r = lg.dispatch(st, "GET", B + "/b1", {"$alt": "json;enum-encoding=int"}, {}, b"")
    check("enum-encoding=int", json.loads(r.body)["lifecycleState"] == 1, r.body)
    r = lg.dispatch(st, "POST", "/v2/entries:list", {"$alt": "json;enum-encoding=int"}, {}, json.dumps({"resourceNames": ["projects/p1"]}).encode())
    check("entries severity int", all(isinstance(e["severity"], int) for e in json.loads(r.body)["entries"]), r.body)
    s, b = call(st, "GET", "/v2/nonsense")
    check("unknown path → 404", s == 404, b)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


main()
