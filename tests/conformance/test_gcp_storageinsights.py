"""GCS Storage Insights inventory reports + Anywhere Cache
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_storageinsights.py)."""
import csv
import datetime
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core import gcp_storageinsights_core as SI  # noqa: E402

R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None, raw=None):
    out = R.handle(method, path, query or {}, {"content-type": "application/json"}, raw if raw is not None else (json.dumps(body).encode() if body is not None else b""))
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {"raw": out["body"]}


def media(bucket, name):
    s = R.handle("GET", f"/storage/v1/b/{bucket}/o/{name.replace('/', '%2F')}", {"alt": "media"}, {}, b"")
    return s["status"], s["body"]


call("POST", "/storage/v1/b", {"name": "src-inv", "location": "US-CENTRAL1"}, {"project": "p1"})
call("POST", "/storage/v1/b", {"name": "dst-inv", "location": "US-CENTRAL1"}, {"project": "p1"})
call("POST", "/storage/v1/b", {"name": "eu-src", "location": "EU"}, {"project": "p1"})
for n, d in (("a.txt", "hello"), ("dir/b.log", "xyzzy")):
    R.handle("POST", "/upload/storage/v1/b/src-inv/o", {"uploadType": "media", "name": n}, {"content-type": "text/plain"}, d.encode())

today = datetime.date.today()
D = lambda d: {"year": d.year, "month": d.month, "day": d.day}  # noqa: E731
cfg = {"displayName": "nightly", "frequencyOptions": {"frequency": "DAILY", "startDate": D(today - datetime.timedelta(days=1)), "endDate": D(today + datetime.timedelta(days=30))},
       "csvOptions": {"recordSeparator": "\n", "delimiter": ",", "headerRequired": True},
       "objectMetadataReportOptions": {"metadataFields": ["project", "bucket", "name", "size", "storageClass"], "storageFilters": {"bucket": "src-inv"},
                                       "storageDestinationOptions": {"bucket": "dst-inv", "destinationPath": "reports"}}}
BASE = "/v1/projects/p1/locations/us-central1/reportConfigs"
s, c = call("POST", BASE, cfg, {"reportConfigId": "nightly"})
check("create report config", s == 200 and c["name"] == "projects/p1/locations/us-central1/reportConfigs/nightly", c)
check("duplicate -> 409", call("POST", BASE, cfg, {"reportConfigId": "nightly"})[0] == 409)
import copy  # noqa: E402
bad = copy.deepcopy(cfg); bad["objectMetadataReportOptions"]["metadataFields"] = ["bucket", "size"]
check("metadataFields must include project/bucket/name", call("POST", BASE, bad, {"reportConfigId": "x1"})[0] == 400)
bad = copy.deepcopy(cfg); bad["objectMetadataReportOptions"]["metadataFields"] = ["project", "bucket", "name", "nope"]
check("unknown metadata field -> 400", call("POST", BASE, bad, {"reportConfigId": "x2"})[0] == 400)
bad = copy.deepcopy(cfg); bad["objectMetadataReportOptions"]["storageFilters"]["bucket"] = "ghost"
check("missing source bucket -> 404", call("POST", BASE, bad, {"reportConfigId": "x3"})[0] == 404)
check("config location must match the source bucket", call("POST", "/v1/projects/p1/locations/europe/reportConfigs", cfg, {"reportConfigId": "x4"})[0] == 400)
bad = copy.deepcopy(cfg); bad["frequencyOptions"]["frequency"] = "HOURLY"
check("bad frequency -> 400", call("POST", BASE, bad, {"reportConfigId": "x5"})[0] == 400)
bad = copy.deepcopy(cfg); del bad["csvOptions"]; bad["parquetOptions"] = {}
check("parquet rejected honestly", call("POST", BASE, bad, {"reportConfigId": "x6"})[0] == 400)

s, det = call("GET", BASE + "/nightly/reportDetails")
check("a report was generated for the due slot", s == 200 and len(det["reportDetails"]) == 1 and det["reportDetails"][0]["rowCount"] == "2", det)
prefix = det["reportDetails"][0]["reportPathPrefix"]
check("report path prefix points at the destination bucket", prefix.startswith("gs://dst-inv/reports/") and "_nightly" in prefix, prefix)
key = prefix[len("gs://dst-inv/"):] + "_0.csv"
st, data = media("dst-inv", key)
rows = list(csv.reader(io.StringIO(data.decode()))) if st == 200 else []
check("CSV object landed in the destination bucket with real rows", rows and rows[0] == ["project", "bucket", "name", "size", "storageClass"] and ["p1", "src-inv", "a.txt", "5", "STANDARD"] in [r for r in rows] or any(r[2] == "a.txt" and r[3] == "5" for r in rows), rows)
check("manifest written", media("dst-inv", prefix[len("gs://dst-inv/"):] + "_manifest.json")[0] == 200)
s, rn = call("POST", BASE + "/nightly:runNow")
check("runNow adds a report detail", s == 200 and len(call("GET", BASE + "/nightly/reportDetails")[1]["reportDetails"]) == 2, rn)
s, lst = call("GET", BASE, query={"filter": 'objectMetadataReportOptions.storageFilters.bucket="src-inv"'})
check("list filtered by source bucket", len(lst["reportConfigs"]) == 1)
s, up = call("PATCH", BASE + "/nightly", {"displayName": "renamed"}, {"updateMask": "displayName"})
check("patch displayName", s == 200 and up["displayName"] == "renamed")
check("patch without updateMask -> 400", call("PATCH", BASE + "/nightly", {"displayName": "x"})[0] == 400)
check("delete with details needs force", call("DELETE", BASE + "/nightly")[0] == 400)
check("force delete", call("DELETE", BASE + "/nightly", query={"force": "true"})[0] == 200 and call("GET", BASE + "/nightly")[0] == 404)
future = copy.deepcopy(cfg); future["frequencyOptions"]["startDate"] = D(today + datetime.timedelta(days=5))
call("POST", BASE, future, {"reportConfigId": "later"})
check("future-dated config has no report yet", call("GET", BASE + "/later/reportDetails")[1]["reportDetails"] == [])
check("runNow outside the window -> 400", call("POST", BASE + "/later:runNow")[0] == 400)

# ── Anywhere Cache ──
AC = "/storage/v1/b/src-inv/anywhereCaches"
s, op = call("POST", AC, {"zone": "us-central1-a", "ttl": "7200s", "admissionPolicy": "admit-on-second-miss"})
check("create cache returns an operation", s == 200 and op["done"] and op["response"]["zone"] == "us-central1-a", op)
check("duplicate zone -> 409", call("POST", AC, {"zone": "us-central1-a"})[0] == 409)
check("zone from another region -> 400", call("POST", AC, {"zone": "europe-west1-b"})[0] == 400)
check("ttl out of range -> 400", call("POST", AC, {"zone": "us-central1-b", "ttl": "60s"})[0] == 400)
check("bad admission policy -> 400", call("POST", AC, {"zone": "us-central1-b", "admissionPolicy": "always"})[0] == 400)
s, g = call("GET", AC + "/us-central1-a")
check("cache starts in 'creating'", g["state"] == "creating", g)
check("cannot pause while creating", call("POST", AC + "/us-central1-a/pause")[0] == 400)
SI.CACHE_CREATE_SECONDS = 0
s, g = call("GET", AC + "/us-central1-a")
check("cache becomes 'running'", g["state"] == "running" and g["ttl"] == "7200s" and g["admissionPolicy"] == "admit-on-second-miss", g)
check("pause", call("POST", AC + "/us-central1-a/pause")[1]["state"] == "paused")
check("cannot pause twice", call("POST", AC + "/us-central1-a/pause")[0] == 400)
check("resume", call("POST", AC + "/us-central1-a/resume")[1]["state"] == "running")
s, u = call("PATCH", AC + "/us-central1-a", {"ttl": "3600s"})
check("update ttl", s == 200 and call("GET", AC + "/us-central1-a")[1]["ttl"] == "3600s")
check("list caches", len(call("GET", AC)[1]["items"]) == 1)
check("disable", call("POST", AC + "/us-central1-a/disable")[1]["state"] == "disabled")
check("cache on a missing bucket -> 404", call("GET", "/storage/v1/b/nope/anywhereCaches")[0] == 404)
check("multi-region bucket accepts any zone in the region group", call("POST", "/storage/v1/b/eu-src/anywhereCaches", {"zone": "europe-west1-b"})[0] == 200)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
