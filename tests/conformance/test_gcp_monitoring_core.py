"""Unit tests for core/gcp_monitoring_core.py (run: python3 tests/conformance/test_gcp_monitoring_core.py)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_monitoring_core as mon  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


P = "/v3/projects/p1"
P1 = "/v1/projects/p1"


def call(st, method, path, body=None, query=None):
    r = mon.dispatch(st, method, P + path if path.startswith("/") and not path.startswith("/v3") else path,
                     query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def call1(st, method, path, body=None, query=None):
    r = mon.dispatch(st, method, P1 + path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def policy(name="cpu-high", **kw):
    p = {"displayName": name, "combiner": "OR", "conditions": [{
        "displayName": "cpu > 80%", "conditionThreshold": {
            "filter": 'metric.type = "compute.googleapis.com/instance/cpu/utilization" AND resource.type = "gce_instance"',
            "comparison": "COMPARISON_GT", "thresholdValue": 0.8, "duration": "300s"}}]}
    p.update(kw)
    return p


def main():
    st = mon.MonitoringStore()
    # alert policies
    s, b = call(st, "POST", "/alertPolicies", policy())
    pid = b.get("name", "").rsplit("/", 1)[-1]
    check("create alert policy", s == 200 and b["enabled"] is True and b["name"].startswith("projects/p1/alertPolicies/")
          and b["conditions"][0]["name"].startswith(b["name"] + "/conditions/") and b["creationRecord"]["mutateTime"], b)
    s, b = call(st, "POST", "/alertPolicies", policy(displayName=""))
    check("missing displayName → 400", s == 400 and b["error"]["status"] == "INVALID_ARGUMENT", b)
    s, b = call(st, "POST", "/alertPolicies", policy(conditions=[]))
    check("no conditions → 400", s == 400, b)
    bad = policy()
    bad["conditions"][0]["conditionThreshold"].pop("comparison")
    s, b = call(st, "POST", "/alertPolicies", bad)
    check("threshold without comparison → 400", s == 400, b)
    s, b = call(st, "POST", "/alertPolicies", policy(notificationChannels=["projects/p1/notificationChannels/nope"]))
    check("unknown notification channel → 400", s == 400, b)
    s, b = call(st, "GET", "/alertPolicies/" + pid)
    check("get alert policy", s == 200 and b["displayName"] == "cpu-high", b)
    s, b = call(st, "GET", "/alertPolicies/999")
    check("get missing policy → 404", s == 404 and b["error"]["status"] == "NOT_FOUND", b)
    s, b = call(st, "PATCH", "/alertPolicies/" + pid, {"enabled": False, "displayName": "renamed"}, {"updateMask": "enabled,display_name"})
    check("patch policy (update_mask, snake_case)", s == 200 and b["enabled"] is False and b["displayName"] == "renamed"
          and b["conditions"], b)
    s, b = call(st, "PATCH", "/alertPolicies/" + pid, {"displayName": "x"}, {"updateMask": "name"})
    check("patch bad mask → 400", s == 400, b)
    call(st, "POST", "/alertPolicies", policy("second"))
    s, b = call(st, "GET", "/alertPolicies", query={"filter": 'display_name = "second"'})
    check("list policies filter", s == 200 and len(b["alertPolicies"]) == 1 and b["totalSize"] == 1, b)
    s, b = call(st, "GET", "/alertPolicies", query={"pageSize": "1"})
    check("list policies pagination", len(b["alertPolicies"]) == 1 and b.get("nextPageToken"), b)
    s, b2 = call(st, "GET", "/alertPolicies", query={"pageSize": "1", "pageToken": b["nextPageToken"]})
    check("next page", len(b2["alertPolicies"]) == 1 and "nextPageToken" not in b2, b2)
    s, b = call(st, "GET", "/alertPolicies/" + pid, query={"$alt": "json;enum-encoding=int"})
    check("enum-encoding=int", b["conditions"][0]["conditionThreshold"]["comparison"] == 1 and b["combiner"] == 2, b)
    s, b = call(st, "DELETE", "/alertPolicies/" + pid)
    check("delete policy", s == 200 and b == {}, b)
    s, b = call(st, "DELETE", "/alertPolicies/" + pid)
    check("delete again → 404", s == 404, b)

    # notification channels
    s, ch = call(st, "POST", "/notificationChannels", {"type": "email", "displayName": "ops", "labels": {"email_address": "ops@example.com"}})
    check("create email channel", s == 200 and ch["verificationStatus"] == "VERIFIED" and ch["enabled"] is True, ch)
    s, b = call(st, "POST", "/notificationChannels", {"type": "email", "labels": {}})
    check("channel missing label → 400", s == 400, b)
    s, b = call(st, "POST", "/notificationChannels", {"type": "carrier-pigeon", "labels": {}})
    check("unknown channel type → 400", s == 400, b)
    s, b = call(st, "POST", "/alertPolicies", policy("wired", notificationChannels=[ch["name"]]))
    check("policy with channel", s == 200 and b["notificationChannels"] == [ch["name"]], b)
    cid = ch["name"].rsplit("/", 1)[-1]
    s, b = call(st, "DELETE", "/notificationChannels/" + cid)
    check("delete in-use channel → 400 FAILED_PRECONDITION", s == 400 and b["error"]["status"] == "FAILED_PRECONDITION", b)
    s, b = call(st, "PATCH", "/notificationChannels/" + cid, {"displayName": "ops2"}, {"updateMask": "display_name"})
    check("patch channel", s == 200 and b["displayName"] == "ops2", b)
    s, b = call(st, "POST", "/notificationChannels/%s:getVerificationCode" % cid, {})
    check("getVerificationCode", s == 200 and len(b["code"]) == 6, b)
    s, b = call(st, "DELETE", "/notificationChannels/" + cid, query={"force": "true"})
    check("force delete channel", s == 200, b)
    s, b = call(st, "GET", "/alertPolicies", query={"filter": 'display_name = "wired"'})
    check("force delete detaches from policy", b["alertPolicies"][0]["notificationChannels"] == [], b)
    s, b = call(st, "GET", "/notificationChannelDescriptors")
    check("channel descriptors", s == 200 and any(d["type"] == "slack" for d in b["channelDescriptors"]), b)

    # metric descriptors
    s, b = call(st, "POST", "/metricDescriptors", {"type": "custom.googleapis.com/app/latency", "metricKind": "GAUGE",
                                                   "valueType": "DOUBLE", "unit": "ms", "description": "d",
                                                   "labels": [{"key": "route", "valueType": "STRING"}]})
    check("create custom descriptor", s == 200 and b["name"] == "projects/p1/metricDescriptors/custom.googleapis.com/app/latency", b)
    s, b = call(st, "POST", "/metricDescriptors", {"type": "compute.googleapis.com/mine", "metricKind": "GAUGE", "valueType": "DOUBLE"})
    check("non-custom prefix → 400", s == 400, b)
    s, b = call(st, "POST", "/metricDescriptors", {"type": "custom.googleapis.com/app/latency", "metricKind": "CUMULATIVE", "valueType": "DOUBLE"})
    check("conflicting redefinition → 409", s == 409, b)
    s, b = call(st, "GET", "/metricDescriptors/custom.googleapis.com/app/latency")
    check("get descriptor with slashes in id", s == 200 and b["unit"] == "ms", b)
    s, b = call(st, "GET", "/metricDescriptors/compute.googleapis.com/instance/cpu/utilization")
    check("get built-in descriptor", s == 200 and b["metricKind"] == "GAUGE", b)
    s, b = call(st, "GET", "/metricDescriptors", query={"filter": 'metric.type = starts_with("custom.googleapis.com")'})
    check("list descriptors filter", [d["type"] for d in b["metricDescriptors"]] == ["custom.googleapis.com/app/latency"], b)
    s, b = call(st, "DELETE", "/metricDescriptors/compute.googleapis.com/instance/cpu/utilization")
    check("delete built-in → 400", s == 400, b)

    # time series
    now = datetime.now(timezone.utc).replace(microsecond=0)
    t0 = now - timedelta(minutes=10)

    def write(val, when, route="/a", metric="custom.googleapis.com/app/latency", key="doubleValue"):
        return call(st, "POST", "/timeSeries", {"timeSeries": [{
            "metric": {"type": metric, "labels": {"route": route}},
            "resource": {"type": "global", "labels": {"project_id": "p1"}},
            "points": [{"interval": {"endTime": iso(when)}, "value": {key: val}}]}]})
    for i in range(5):
        s, b = write(float(i + 1), t0 + timedelta(minutes=i))
    check("write time series", s == 200 and b == {}, b)
    s, b = write(9.0, t0 + timedelta(minutes=1))
    check("out-of-order point → 400", s == 400 and "order" in b["error"]["message"], b)
    s, b = write("x", now, key="stringValue")
    check("value type mismatch → 400", s == 400, b)
    s, b = write(1, now, metric="compute.googleapis.com/instance/cpu/utilization")
    check("write built-in metric → 400", s == 400, b)
    s, b = write(3, now, metric="custom.googleapis.com/auto/created", key="int64Value")
    s2, d = call(st, "GET", "/metricDescriptors/custom.googleapis.com/auto/created")
    check("write implicitly creates descriptor", s == 200 and s2 == 200 and d["valueType"] == "INT64", d)
    write(10.0, t0, route="/b")
    q = {"filter": 'metric.type = "custom.googleapis.com/app/latency"', "interval.startTime": iso(t0 - timedelta(minutes=1)),
         "interval.endTime": iso(now)}
    s, b = call(st, "GET", "/timeSeries", query=q)
    a = [t for t in b["timeSeries"] if t["metric"]["labels"]["route"] == "/a"][0]
    check("list time series (newest first)", s == 200 and len(b["timeSeries"]) == 2 and len(a["points"]) == 5
          and a["points"][0]["value"]["doubleValue"] == 5.0 and a["metricKind"] == "GAUGE" and a["valueType"] == "DOUBLE", b)
    s, b = call(st, "GET", "/timeSeries", query=dict(q, filter='metric.type = "custom.googleapis.com/app/latency" AND metric.labels.route = "/b"'))
    check("filter by metric label", len(b["timeSeries"]) == 1, b)
    s, b = call(st, "GET", "/timeSeries", query=dict(q, view="HEADERS"))
    check("HEADERS view has no points", all("points" not in t for t in b["timeSeries"]), b)
    s, b = call(st, "GET", "/timeSeries", query={"filter": 'resource.type = "global"', "interval.endTime": iso(now)})
    check("filter without metric.type → 400", s == 400, b)
    s, b = call(st, "GET", "/timeSeries", query=dict(q, **{"aggregation.alignmentPeriod": "600s", "aggregation.perSeriesAligner": "ALIGN_MEAN"}))
    pts = [t for t in b["timeSeries"] if t["metric"]["labels"]["route"] == "/a"][0]["points"]
    check("align: mean over one 600s bucket", sum(float(p["value"]["doubleValue"]) for p in pts) > 0 and
          all("startTime" in p["interval"] for p in pts), b)
    s, b = call(st, "GET", "/timeSeries", query=dict(q, **{"aggregation.alignmentPeriod": "3600s", "aggregation.perSeriesAligner": "ALIGN_MAX",
                                                           "aggregation.crossSeriesReducer": "REDUCE_SUM"}))
    check("reduce: sum of per-series max across series", len(b["timeSeries"]) == 1
          and b["timeSeries"][0]["points"][0]["value"]["doubleValue"] == 15.0, b)
    s, b = call(st, "GET", "/timeSeries", query=dict(q, **{"aggregation.alignmentPeriod": "60s", "aggregation.perSeriesAligner": "ALIGN_COUNT"}))
    check("align count → int64", b["timeSeries"][0]["valueType"] == "INT64", b)
    s, b = call(st, "DELETE", "/metricDescriptors/custom.googleapis.com/app/latency")
    s2, b2 = call(st, "GET", "/timeSeries", query=q)
    check("delete descriptor drops its series", s == 200 and b2 == {}, b2)

    # groups
    s, g = call(st, "POST", "/groups", {"displayName": "prod", "filter": 'resource.metadata.name=has_substring("prod")'})
    check("create group", s == 200 and g["name"].startswith("projects/p1/groups/") and g["isCluster"] is False, g)
    s, b = call(st, "POST", "/groups", {"displayName": "no-filter"})
    check("group needs filter → 400", s == 400, b)
    s, c = call(st, "POST", "/groups", {"displayName": "child", "filter": "x", "parentName": g["name"]})
    gid = g["name"].rsplit("/", 1)[-1]
    s, b = call(st, "GET", "/groups")
    check("list groups (field is `group`)", len(b["group"]) == 2, b)
    s, b = call(st, "DELETE", "/groups/" + gid)
    check("delete parent without recursive → 400", s == 400, b)
    s, b = call(st, "PUT", "/groups/" + gid, {"displayName": "prod2", "filter": "y"})
    check("update group (PUT)", s == 200 and b["displayName"] == "prod2", b)
    s, b = call(st, "GET", "/groups/%s/members" % gid)
    check("group members", s == 200 and b.get("totalSize", 0) == 0, b)
    s, b = call(st, "DELETE", "/groups/" + gid, query={"recursive": "true"})
    check("recursive delete", s == 200 and not st.groups, b)

    # group membership is evaluated for real against the resource instances this project's
    # own time series have actually reported — not an always-empty stub
    s, g2 = call(st, "POST", "/groups", {"displayName": "globals", "filter": 'resource.type = "global"'})
    s, b = call(st, "GET", "/groups/%s/members" % g2["name"].rsplit("/", 1)[-1])
    check("group members matches real resource instances", s == 200 and b["totalSize"] == 1
          and b["members"][0]["type"] == "global" and b["members"][0]["labels"]["project_id"] == "p1", b)
    s, g3 = call(st, "POST", "/groups", {"displayName": "nothing", "filter": 'resource.type = "gce_instance"'})
    s, b = call(st, "GET", "/groups/%s/members" % g3["name"].rsplit("/", 1)[-1])
    check("group with no matching resources → empty members", s == 200 and b["totalSize"] == 0, b)
    call(st, "DELETE", "/groups/" + g2["name"].rsplit("/", 1)[-1])
    call(st, "DELETE", "/groups/" + g3["name"].rsplit("/", 1)[-1])

    # uptime checks
    up = {"displayName": "homepage", "monitoredResource": {"type": "uptime_url", "labels": {"host": "example.com"}},
          "httpCheck": {"path": "/", "port": 443, "useSsl": True}, "period": "300s", "timeout": "10s"}
    s, u = call(st, "POST", "/uptimeCheckConfigs", up)
    check("create uptime check", s == 200 and u["name"].startswith("projects/p1/uptimeCheckConfigs/homepage-")
          and u["httpCheck"]["requestMethod"] == "GET", u)
    s, b = call(st, "POST", "/uptimeCheckConfigs", dict(up, timeout=None))
    check("uptime needs timeout → 400", s == 400, b)
    s, b = call(st, "POST", "/uptimeCheckConfigs", dict(up, period="7s"))
    check("uptime bad period → 400", s == 400, b)
    uid = u["name"].rsplit("/", 1)[-1]
    s, b = call(st, "PATCH", "/uptimeCheckConfigs/" + uid, {"displayName": "home2"}, {"updateMask": "display_name"})
    check("patch uptime check", s == 200 and b["displayName"] == "home2" and b["httpCheck"]["port"] == 443, b)
    s, b = call(st, "GET", "/uptimeCheckConfigs")
    check("list uptime checks", len(b["uptimeCheckConfigs"]) == 1, b)
    s, b = call(st, "GET", "/v3/uptimeCheckIps")
    check("uptime check IPs", s == 200 and b["uptimeCheckIps"], b)
    s, b = call(st, "DELETE", "/uptimeCheckConfigs/" + uid)
    check("delete uptime check", s == 200 and not st.uptime_checks, b)

    # resource descriptors
    s, b = call(st, "GET", "/monitoredResourceDescriptors")
    check("monitored resource descriptors", any(d["type"] == "gce_instance" for d in b["resourceDescriptors"]), b)
    s, b = call(st, "GET", "/monitoredResourceDescriptors/gce_instance")
    check("get monitored resource descriptor", s == 200 and b["name"] == "projects/p1/monitoredResourceDescriptors/gce_instance", b)

    # console form
    v = mon.create_from_form(st, {"name": "console-pol", "email": "a@b.co"}, "p1")
    check("console form creates policy + email channel", v["state"] == "Enabled" and v["channels_text"] == "a@b.co"
          and v["metric_type"] == "compute.googleapis.com/instance/cpu/utilization" and v["threshold_text"] == "> 0.8", v)
    blanks = [k for k in ("id", "display_name", "state", "severity_text", "condition_summary", "metric_type", "threshold_text",
                          "channels_text", "combiner_text", "last_modified", "incidents", "documentation_text") if v.get(k) in (None, "")]
    check("console view has no blank columns", not blanks, blanks)
    check("unknown path → 404", call(st, "GET", "/v3/nope")[0] == 404)

    # dashboards (v1 API)
    s, d = call1(st, "POST", "/dashboards", {"displayName": "My Dashboard"})
    check("create dashboard", s == 200 and d["name"].startswith("projects/p1/dashboards/")
          and d["mosaicLayout"]["tiles"] == [] and d["etag"], d)
    s, b = call1(st, "POST", "/dashboards", {"displayName": ""})
    check("dashboard missing displayName → 400", s == 400, b)
    did = d["name"].rsplit("/", 1)[-1]
    s, b = call1(st, "GET", "/dashboards/" + did)
    check("get dashboard", s == 200 and b["displayName"] == "My Dashboard", b)
    s, b = call1(st, "GET", "/dashboards/nope")
    check("get missing dashboard → 404", s == 404, b)
    s, b = call1(st, "PATCH", "/dashboards/" + did, {"displayName": "Renamed", "etag": d["etag"]})
    check("patch dashboard (etag ok)", s == 200 and b["displayName"] == "Renamed" and b["etag"] != d["etag"], b)
    s, b = call1(st, "PATCH", "/dashboards/" + did, {"displayName": "Stale", "etag": "wrong"})
    check("patch dashboard stale etag → 409", s == 409, b)
    call1(st, "POST", "/dashboards", {"displayName": "Second"})
    s, b = call1(st, "GET", "/dashboards")
    check("list dashboards", s == 200 and len(b["dashboards"]) == 2, b)
    s, b = call1(st, "DELETE", "/dashboards/" + did)
    check("delete dashboard", s == 200 and b == {}, b)
    s, b = call1(st, "GET", "/dashboards/" + did)
    check("get deleted dashboard → 404", s == 404, b)

    # snoozes (v1 API)
    s, pol = call(st, "POST", "/alertPolicies", policy("snooze-target"))
    snooze = {"displayName": "maintenance", "criteria": {"policies": [pol["name"]]},
              "interval": {"startTime": iso(now), "endTime": iso(now + timedelta(hours=1))}}
    s, sn = call1(st, "POST", "/snoozes", snooze)
    check("create snooze", s == 200 and sn["name"].startswith("projects/p1/snoozes/")
          and sn["criteria"]["policies"] == [pol["name"]], sn)
    s, b = call1(st, "POST", "/snoozes", dict(snooze, criteria={"policies": ["projects/p1/alertPolicies/nope"]}))
    check("snooze unknown policy → 400", s == 400, b)
    s, b = call1(st, "POST", "/snoozes", dict(snooze, interval={"startTime": iso(now), "endTime": iso(now)}))
    check("snooze end before/eq start → 400", s == 400, b)
    sid = sn["name"].rsplit("/", 1)[-1]
    s, b = call1(st, "GET", "/snoozes/" + sid)
    check("get snooze", s == 200 and b["displayName"] == "maintenance", b)
    s, b = call1(st, "PATCH", "/snoozes/" + sid, {"displayName": "extended"}, {"updateMask": "display_name"})
    check("patch snooze", s == 200 and b["displayName"] == "extended" and b["criteria"]["policies"] == [pol["name"]], b)
    s, b = call1(st, "GET", "/snoozes")
    check("list snoozes", s == 200 and len(b["snoozes"]) == 1, b)
    check("unknown v1 path → 404", call1(st, "GET", "/nope")[0] == 404)

    # services & SLOs (Service Monitoring API, v3)
    s, svc = call(st, "POST", "/services", {"displayName": "checkout"})
    check("create service", s == 200 and svc["name"].startswith("projects/p1/services/") and svc["custom"] == {}, svc)
    s, b = call(st, "POST", "/services", {"displayName": ""})
    check("service missing displayName → 400", s == 400, b)
    svcid = svc["name"].rsplit("/", 1)[-1]
    slo = {"displayName": "99% availability", "goal": 0.99, "rollingPeriod": "2592000s",
           "serviceLevelIndicator": {"basicSli": {"availability": {}}}}
    s, o = call(st, "POST", "/services/%s/serviceLevelObjectives" % svcid, slo)
    check("create SLO", s == 200 and o["name"].startswith(svc["name"] + "/serviceLevelObjectives/") and o["goal"] == 0.99, o)
    s, b = call(st, "POST", "/services/%s/serviceLevelObjectives" % svcid, dict(slo, goal=1.5))
    check("SLO bad goal → 400", s == 400, b)
    s, b = call(st, "POST", "/services/%s/serviceLevelObjectives" % svcid, dict(slo, rollingPeriod="2592000s", calendarPeriod="MONTH"))
    check("SLO both periods → 400", s == 400, b)
    oid = o["name"].rsplit("/", 1)[-1]
    s, b = call(st, "GET", "/services/%s/serviceLevelObjectives/%s" % (svcid, oid))
    check("get SLO", s == 200 and b["displayName"] == "99% availability", b)
    s, b = call(st, "GET", "/services/%s/serviceLevelObjectives" % svcid)
    check("list SLOs", s == 200 and len(b["serviceLevelObjectives"]) == 1, b)
    s, b = call(st, "GET", "/services")
    check("list services", s == 200 and len(b["services"]) == 1, b)
    s, b = call(st, "DELETE", "/services/" + svcid)
    check("delete service cascades SLOs", s == 200 and not st.slos and not st.services, b)

    # uptime check with a synthetic-monitor target (same collection, different check type)
    s, sm = call(st, "POST", "/uptimeCheckConfigs", {
        "displayName": "synthetic-login", "monitoredResource": {"type": "uptime_url", "labels": {"host": "example.com"}},
        "syntheticMonitor": {"cloudFunctionV2": {"name": "projects/p1/locations/us-central1/functions/login-check"}},
        "period": "300s", "timeout": "10s"})
    check("create synthetic monitor (uptime check with synthetic_monitor target)", s == 200 and sm["syntheticMonitor"]["cloudFunctionV2"]["name"].endswith("login-check"), sm)
    s, b = call(st, "POST", "/uptimeCheckConfigs", {
        "displayName": "both", "monitoredResource": {"type": "uptime_url", "labels": {"host": "example.com"}},
        "httpCheck": {"path": "/"}, "syntheticMonitor": {"cloudFunctionV2": {"name": "x"}}, "period": "300s", "timeout": "10s"})
    check("synthetic monitor + http_check → 400", s == 400, b)
    call(st, "DELETE", "/uptimeCheckConfigs/" + sm["name"].rsplit("/", 1)[-1])

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


main()
