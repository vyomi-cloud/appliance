"""Security Command Center REST v2: sources, findings (filter/group/state/mute/marks), custom findings, mute + notification configs
(notifications are PUBLISHED to a simulator Pub/Sub topic).

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_gcp_scc_core.py
"""
import base64
import json

from core.aws_wire_router import AwsWireRouter
AwsWireRouter.STRICT_GCP_PROJECT = False   # engine conformance uses ad-hoc project ids (main's one-project-per-space rule is exercised elsewhere)


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


R = AwsWireRouter()
R._sched_last = 1e18


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {"content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def main():
    P = "projects/demo"
    call("POST", "/storage/v1/b", {"name": "pubbk"}, {"project": "demo"})
    call("PUT", "/storage/v1/b/pubbk/iam", {"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]})
    s, o = call("GET", f"/v2/{P}/sources")
    names = {x["displayName"] for x in o["sources"]}
    _check("built-in sources", {"Security Health Analytics", "Event Threat Detection", "Container Analysis"} <= names)
    sha = next(x["name"] for x in o["sources"] if x["displayName"] == "Security Health Analytics")

    s, o = call("GET", f"/v2/{P}/sources/-/findings", query={"filter": 'category="PUBLIC_BUCKET_ACL" AND state="ACTIVE"'})
    _check("list findings with filter", s == 200 and o["totalSize"] == 1 and o["listFindingsResults"][0]["finding"]["severity"] == "CRITICAL")
    f = o["listFindingsResults"][0]["finding"]
    _check("resource block + canonicalName", o["listFindingsResults"][0]["resource"]["type"] == "google.cloud.storage.Bucket" and "/locations/global/findings/" in f["canonicalName"])
    _check("bad filter field 400", call("GET", f"/v2/{P}/sources/-/findings", query={"filter": 'bogus="x"'})[0] == 400)
    _check("bad filter syntax 400", call("GET", f"/v2/{P}/sources/-/findings", query={"filter": 'state ='})[0] == 400)
    s, o = call("GET", f"/v2/{P}/locations/global/sources/-/findings", query={"filter": 'resource_name:"pubbk" AND NOT severity="LOW"', "orderBy": "severity"})
    _check("locations/global form + NOT + resource_name:", s == 200 and all(x["finding"]["severity"] != "LOW" for x in o["listFindingsResults"]) and o["totalSize"] >= 1)
    s, o = call("GET", f"/v2/{P}/sources/-/findings", query={"pageSize": "2"})
    _check("pagination", len(o["listFindingsResults"]) == 2 and o["nextPageToken"])
    s, o2 = call("GET", f"/v2/{P}/sources/-/findings", query={"pageSize": "2", "pageToken": o["nextPageToken"]})
    _check("second page differs", o2["listFindingsResults"][0]["finding"]["name"] != o["listFindingsResults"][0]["finding"]["name"])
    s, g = call("POST", f"/v2/{P}/sources/-/findings:group", {"groupBy": "category"})
    _check("group by category", s == 200 and any(r["properties"]["category"] == "PUBLIC_BUCKET_ACL" for r in g["groupByResults"]))

    # get / state / mute / marks
    name = f["name"]
    s, g1 = call("GET", "/v2/" + name)
    _check("get finding", s == 200 and g1["category"] == "PUBLIC_BUCKET_ACL")
    s, o = call("POST", "/v2/" + name + ":setState", {"state": "INACTIVE"})
    _check("setState", s == 200 and o["state"] == "INACTIVE")
    _check("setState invalid 400", call("POST", "/v2/" + name + ":setState", {"state": "NOPE"})[0] == 400)
    s, o = call("GET", f"/v2/{P}/sources/-/findings", query={"filter": 'category="PUBLIC_BUCKET_ACL" AND state="ACTIVE"'})
    _check("inactive finding leaves the ACTIVE filter", o["totalSize"] == 0)
    s, o = call("POST", "/v2/" + name + ":setMute", {"mute": "MUTED"})
    _check("setMute", o["mute"] == "MUTED")
    s, o = call("PATCH", "/v2/" + name + "/securityMarks", {"marks": {"owner": "sec"}}, {"updateMask": "marks.owner"})
    _check("security marks", o["marks"] == {"owner": "sec"})
    s, o = call("GET", f"/v2/{P}/sources/-/findings", query={"filter": 'security_marks.marks.owner="sec"'})
    _check("filter on marks", o["totalSize"] == 1)
    _check("builtin finding PATCH refused", call("PATCH", "/v2/" + name, {"severity": "LOW"})[0] == 403)

    # custom source + finding
    s, src = call("POST", f"/v2/{P}/sources", {"displayName": "Pen test", "description": "manual"})
    _check("create source", s == 200 and src["displayName"] == "Pen test")
    _check("duplicate source 409", call("POST", f"/v2/{P}/sources", {"displayName": "Pen test"})[0] == 409)
    body = {"state": "ACTIVE", "category": "MANUAL_FINDING", "resourceName": "//compute.googleapis.com/projects/demo/zones/z/instances/i1", "eventTime": "2026-11-04T00:00:00Z", "severity": "HIGH"}
    s, cf = call("POST", "/v2/" + src["name"] + "/findings", body, {"findingId": "abc123"})
    _check("create custom finding", s == 200 and cf["name"].endswith("/findings/abc123"))
    _check("duplicate finding 409", call("POST", "/v2/" + src["name"] + "/findings", body, {"findingId": "abc123"})[0] == 409)
    _check("builtin source finding create refused", call("POST", "/v2/" + sha + "/findings", body, {"findingId": "x1"})[0] == 403)
    _check("missing eventTime 400", call("POST", "/v2/" + src["name"] + "/findings", {k: v for k, v in body.items() if k != "eventTime"}, {"findingId": "x2"})[0] == 400)
    s, o = call("PATCH", "/v2/" + cf["name"], {"severity": "LOW"}, {"updateMask": "severity"})
    _check("patch custom finding", o["severity"] == "LOW")

    # mute config applies by filter
    s, mc = call("POST", f"/v2/{P}/locations/global/muteConfigs", {"filter": 'category="MANUAL_FINDING"', "description": "noise"}, {"muteConfigId": "mute-manual"})
    _check("create mute config", s == 200 and mc["name"].endswith("/muteConfigs/mute-manual"))
    s, o = call("GET", "/v2/" + cf["name"])
    _check("mute config mutes matching finding", o["mute"] == "MUTED" and o["muteInitiator"].endswith("muteConfigs/mute-manual"))
    _check("bad mute filter 400", call("POST", f"/v2/{P}/locations/global/muteConfigs", {"filter": "x"}, {"muteConfigId": "bad"})[0] == 400)
    _check("list mute configs", len(call("GET", f"/v2/{P}/locations/global/muteConfigs")[1]["muteConfigs"]) == 1)
    _check("delete mute config", call("DELETE", "/v2/" + mc["name"])[0] == 200 and call("GET", "/v2/" + mc["name"])[0] == 404)

    # notification config -> Pub/Sub
    _check("notification needs topic", call("POST", f"/v2/{P}/locations/global/notificationConfigs", {"pubsubTopic": "projects/demo/topics/scc", "streamingConfig": {"filter": 'state="ACTIVE"'}}, {"configId": "n1"})[0] == 400)
    call("PUT", "/v1/projects/demo/topics/scc", {})
    call("PUT", "/v1/projects/demo/subscriptions/scc-sub", {"topic": "projects/demo/topics/scc"})
    s, nc = call("POST", f"/v2/{P}/locations/global/notificationConfigs", {"pubsubTopic": "projects/demo/topics/scc", "streamingConfig": {"filter": 'state="ACTIVE" AND severity="CRITICAL"'}}, {"configId": "n1"})
    _check("create notification config", s == 200 and nc["name"].endswith("/notificationConfigs/n1"))
    _check("bad notification filter 400", call("POST", f"/v2/{P}/locations/global/notificationConfigs", {"pubsubTopic": "projects/demo/topics/scc", "streamingConfig": {"filter": "(("}}, {"configId": "n2"})[0] == 400)
    s, o = call("POST", "/v1/projects/demo/subscriptions/scc-sub:pull", {"maxMessages": 10})
    _check("existing findings are not replayed", not o.get("receivedMessages"))
    call("POST", "/storage/v1/b", {"name": "pubbk2"}, {"project": "demo"})
    call("PUT", "/storage/v1/b/pubbk2/iam", {"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]})
    from core import schedule_core as sc
    import time
    sc.tick(R, time.time())             # baseline
    sc.tick(R, time.time() + 120)       # scc:notify due -> sync
    s, o = call("POST", "/v1/projects/demo/subscriptions/scc-sub:pull", {"maxMessages": 10})
    msgs = [json.loads(base64.b64decode(m["message"]["data"])) for m in o.get("receivedMessages", [])]
    _check("new CRITICAL finding published to Pub/Sub", any(m["finding"]["resourceName"].endswith("pubbk2") and m["notificationConfigName"].endswith("n1") for m in msgs))
    _check("delete notification config", call("DELETE", "/v2/" + nc["name"])[0] == 200)
    # org parent
    s, o = call("GET", "/v2/organizations/123/sources/-/findings", query={"pageSize": "1"})
    _check("organization parent aggregates", s == 200 and o["totalSize"] >= 1)
    print("SCC OK")


if __name__ == "__main__":
    main()
