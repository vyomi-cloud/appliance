"""Observability core: recorder, OTLP ingest, Jaeger, PromQL-lite/Prometheus API, publishers. Hermetic."""
import json, sys, time
from core import observability_core as O, cloudwatch_core as cw, gcp_monitoring_core as gm

F = []
def ck(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: F.append(n)

obs = O.ObsStore()
T = 1_700_000_000.0
for i in range(30):
    O.record(obs, "aws", "s3", "photos", "GetObject", 200 if i % 10 else 404, 10 + i, ts=T + i)
for i in range(10):
    O.record(obs, "aws", "lambda", "fn1", "Invoke", 200 if i else 500, 100 + i * 10, ts=T + i)
O.record(obs, "gcp", "gcp-gcs", "gb", "GetObject", 200, 5, ts=T)
ck("auto spans recorded", obs.span_count == 41)
r = O.rollup(obs, "aws", "s3", since=T - 1, until=T + 100)
g = r[("aws", "s3", "photos")]
ck("rollup count/errors", g["count"] == 30 and g["errors"] == 3 and g["p50"] >= 24)
ck("extract s3 vhost", O.extract_resource("aws", "s3", "GET", "/k", {"host": "my-b.s3.amazonaws.com"})[0] == "my-b")
ck("extract lambda", O.extract_resource("aws", "lambda", "POST", "/2015-03-31/functions/f1/invocations") == ("f1", "Invoke"))
ck("extract ddb", O.extract_resource("aws", "dynamodb", "POST", "/", {"X-Amz-Target": "DynamoDB_20120810.PutItem"}, b'{"TableName":"t1"}') == ("t1", "PutItem"))

# OTLP
def post(p, o, ct="application/json"):
    return O.dispatch(obs, "POST", p, {}, {"content-type": ct}, json.dumps(o).encode())
tid, sid = "ab" * 16, "cd" * 8
now_ns = int(time.time() * 1e9)
body = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
        "scopeSpans": [{"spans": [{"traceId": tid, "spanId": sid, "name": "POST /pay", "kind": 2, "startTimeUnixNano": str(now_ns), "endTimeUnixNano": str(now_ns + 5_000_000),
                                   "attributes": [{"key": "http.status_code", "value": {"intValue": "500"}}], "status": {"code": 2}},
                                  {"traceId": tid, "spanId": "ee" * 8, "parentSpanId": sid, "name": "db", "startTimeUnixNano": str(now_ns + 1000), "endTimeUnixNano": str(now_ns + 2_000_000)},
                                  {"traceId": "bad", "spanId": sid, "name": "x", "startTimeUnixNano": "1", "endTimeUnixNano": "2"}]}]}]}
rs = post("/_obs/v1/traces", body)
ck("otlp traces partial success", rs.status == 200 and json.loads(rs.body)["partialSuccess"]["rejectedSpans"] == 1)
ck("otlp protobuf rejected 415", post("/_obs/v1/traces", {}, "application/x-protobuf").status == 415)
j = lambda path, q=None: (lambda r: (r.status, json.loads(r.body)))(O.dispatch(obs, "GET", path, q or {}))
st, o = j("/_obs/jaeger/api/services")
ck("jaeger services", "checkout" in o["data"] and "aws-s3" in o["data"])
st, o = j("/_obs/jaeger/api/traces", {"service": "checkout"})
ck("jaeger traces", st == 200 and len(o["data"][0]["spans"]) == 2 and any(t["key"] == "error" for t in o["data"][0]["spans"][0]["tags"]))
st, o = j("/_obs/jaeger/api/traces/" + tid)
ck("jaeger by id + child ref", st == 200 and o["data"][0]["spans"][1]["references"][0]["spanID"] == sid)
ck("jaeger 404", j("/_obs/jaeger/api/traces/" + "0" * 32)[0] == 404 and j("/_obs/jaeger/api/traces")[0] == 400)
ck("trace stats", O.trace_latency_stats(obs)["count"] >= 40)

# OTLP metrics + logs
post("/_obs/v1/metrics", {"resourceMetrics": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "app"}}]}, "scopeMetrics": [{"metrics": [
    {"name": "queue.depth", "gauge": {"dataPoints": [{"asInt": "7", "timeUnixNano": str(int(T * 1e9)), "attributes": [{"key": "q", "value": {"stringValue": "a"}}]}]}}]}]}]})
post("/_obs/v1/logs", {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}, "severityText": "INFO"}]}]}]})
ck("logs kept", obs.logs[0]["body"] == "hello")

# Prometheus API
def q(expr, t=T + 29):
    st, o = j("/_obs/prom/api/v1/query", {"query": expr, "time": str(t)})
    return st, o
st, o = q('vyomi_requests_total{service="s3",code="2xx"}')
ck("instant selector", st == 200 and o["data"]["result"][0]["value"][1] == "27")
st, o = q('sum by (service) (vyomi_requests_total)')
d = {r["metric"].get("service"): r["value"][1] for r in o["data"]["result"]}
ck("sum by", d == {"s3": "30", "lambda": "10", "gcp-gcs": "1"})
st, o = q('increase(vyomi_requests_total{service="s3"}[1m])')
ck("increase", sorted(r["value"][1] for r in o["data"]["result"]) == ["2", "26"])
st, o = q('rate(vyomi_requests_total{service="s3",code="2xx"}[1m])')
ck("rate positive", float(o["data"]["result"][0]["value"][1]) > 0)
st, o = q('histogram_quantile(0.5, sum by (le) (vyomi_request_duration_ms_bucket{service="s3"}))')
ck("histogram_quantile", st == 200 and 10 <= float(o["data"]["result"][0]["value"][1]) <= 50)
st, o = q('vyomi_request_duration_ms_sum{service="s3",code="2xx"} / vyomi_request_duration_ms_count{service="s3",code="2xx"}')
ck("binary vector", abs(float(o["data"]["result"][0]["value"][1]) - 24.5) < 3)
ck("regex matcher", len(q('vyomi_requests_total{service=~"s3|lambda",code!="5xx"}')[1]["data"]["result"]) >= 3)
ck("otlp gauge queryable", q('queue_depth{q="a"}', T + 1)[1]["data"]["result"][0]["value"][1] == "7")
ck("parse error 400", j("/_obs/prom/api/v1/query", {"query": "sum(("})[0] == 400)
st, o = j("/_obs/prom/api/v1/query_range", {"query": 'sum(vyomi_requests_total{service="s3"})', "start": str(T), "end": str(T + 30), "step": "10"})
vals = o["data"]["result"][0]["values"]
ck("query_range monotonic", st == 200 and len(vals) == 4 and [float(v[1]) for v in vals] == sorted(float(v[1]) for v in vals) and vals[-1][1] == "30")
ck("step 0 rejected", j("/_obs/prom/api/v1/query_range", {"query": "up", "step": "0", "start": "1", "end": "2"})[0] == 400)
ck("labels / values / series", "service" in j("/_obs/prom/api/v1/labels")[1]["data"]
   and "s3" in j("/_obs/prom/api/v1/label/service/values")[1]["data"]
   and len(j("/_obs/prom/api/v1/series", {"match[]": 'vyomi_requests_total{service="lambda"}'})[1]["data"]) == 2)
ck("buildinfo + health", j("/_obs/prom/api/v1/status/buildinfo")[0] == 200 and O.dispatch(obs, "GET", "/_obs/prom/-/healthy").status == 200)
ck("exposition", b'vyomi_requests_total{cloud="aws"' in O.dispatch(obs, "GET", "/_obs/metrics").body)
ck("idle -> no series", O.query_instant(O.ObsStore(), "vyomi_requests_total")["result"] == [])

# publishers
c = cw.CloudWatchStore()
names = O.publish_cloudwatch(obs, c, now=T + 120)
ck("cloudwatch published", {"Invocations", "Errors", "Duration", "AllRequests", "4xxErrors"} <= set(names))
s = [v for v in c.metrics.values() if v["MetricName"] == "Invocations"][0]
ck("lambda invocations measured", sum(p[1] for p in s["points"]) == 10)
ck("publish idempotent", O.publish_cloudwatch(obs, c, now=T + 125) == [])
rds = O.publish_rds_stats(c, "db1", {"cpu_pct": 12.5, "mem_used_bytes": 100, "mem_limit_bytes": 400, "connections": 3, "active_backends": 2, "blks_hit": 90, "blks_read": 10}, ts=T)
ck("rds metrics + insights", {"CPUUtilization", "FreeableMemory", "DBLoad", "BufferCacheHitRatio", "DatabaseConnections"} <= set(rds) and "FreeStorageSpace" not in rds)
m = gm.MonitoringStore()
ck("gcp series published", O.publish_gcp(obs, m, "proj-aaaaa", now=T + 120) == ["storage.googleapis.com/api/request_count"] and len(m.time_series) == 1)
n = O.sync_gcp_traces(obs, m, "proj-aaaaa")
ck("gcp trace sync", n >= 40 and any(k.endswith(tid) for k in m.traces))
ob2 = O.ObsStore()
O.record(ob2, "azure", "blob", "acct1", "PUT", 201, 12, ts=T); O.record(ob2, "azure", "blob", "acct1", "GET", 500, 30, ts=T)
am = O.azure_storage_request_metrics(ob2, "acct1", now=T + 5)
ck("azure storage availability/latency", am["Availability"] == 50.0 and am["SuccessE2ELatency"] == 12.0 and O.azure_storage_request_metrics(ob2, "other", now=T) == {})
ds = O.parse_docker_stats('{"CPUPerc":"12.50%","MemUsage":"100MiB / 1GiB","NetIO":"1.5kB / 3kB"}')
ck("docker stats parse", ds["cpu_pct"] == 12.5 and ds["mem_limit_bytes"] == 1024 ** 3 and ds["net_tx_bytes"] == 3000 and O.parse_docker_stats("junk") == {})
ck("pg row parse", O.pg_stats_from_row((3, 10, 1, 5, 95, 0, 2))["active_backends"] == 2)
cwx = cw.CloudWatchStore()
rr = O.dispatch(obs, "POST", "/_obs/rds-stats", {}, {}, json.dumps({"dbInstanceIdentifier": "db9", "stats": {**ds, **O.pg_stats_from_row((3, 10, 1, 5, 95, 0, 2))}}).encode(), cw_store=cwx)
ck("rds-stats push publishes DBLoad", "DBLoad" in json.loads(rr.body)["published"] and any(v["MetricName"] == "CPUUtilization" for v in cwx.metrics.values()))
ck("rds-stats validation", O.dispatch(obs, "POST", "/_obs/rds-stats", {}, {}, b"{}", cw_store=cwx).status == 400)
# Nano substrate: the wire router records measured requests and serves /_obs
from core.aws_wire_router import AwsWireRouter
r = AwsWireRouter()
for _ in range(3):
    r.handle("PUT", "/nano-bkt", {}, {"host": "localhost"}, b"")
r.handle("GET", "/nano-bkt", {}, {"host": "localhost"}, b"")
rows = O.rollup(r.obs, "aws", "s3")
ck("router records s3 per bucket", ("aws", "s3", "nano-bkt") in rows and rows[("aws", "s3", "nano-bkt")]["count"] == 4)
res = r.handle("GET", "/_obs/prom/api/v1/query", {"query": 'vyomi_requests_total{resource="nano-bkt"}'}, {}, b"")
ck("router serves /_obs prom", res["status"] == 200 and json.loads(res["body"])["data"]["result"])
r.obs.recent[:] = [(x[0] - 120,) + x[1:] for x in r.obs.recent]   # age the rows into finished 1-minute buckets
r.handle("POST", "/", {}, {"X-Amz-Target": "GraniteServiceVersion20100801.ListMetrics", "Content-Type": "application/x-amz-json-1.0", "Host": "localhost"}, b"{}")
ck("router cloudwatch read path ok", any(m["MetricName"] == "AllRequests" for m in r.cw.metrics.values()))
print("FAILED: %s" % F if F else "ALL PASS")
sys.exit(1 if F else 0)
