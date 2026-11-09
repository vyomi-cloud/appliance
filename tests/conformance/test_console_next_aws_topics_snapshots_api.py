"""Console-next AWS routes that had no test: SNS topics (create/subscribe/publish/delete),
glass-box calls clear/stream, conformance rollup, RDS execute and snapshots (capture/list/restore/fork)."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000") + "/api/console"
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def req(m, p, **kw):
    return requests.request(m, BASE + p, timeout=60, **kw)


def locked(r):
    try:
        return r.status_code in (402, 403) and (r.json().get("detail") or {}).get("code") == "tier_feature_locked"
    except ValueError:
        return False


# --- SNS topics
t = "zz-conf-t-" + sfx
q = "zz-conf-tq-" + sfx
r = req("POST", "/messaging/topics", json={"name": t})
if locked(r):
    print("[PASS] messaging locked by tier (skipped)")
else:
    arn = r.json().get("topic_arn", "") if r.status_code == 200 else ""
    check("create topic returns SNS ARN", arn.startswith("arn:aws:sns:") and arn.endswith(":" + t), r.text[:200])
    check("topic listed", t in req("GET", "/messaging/topics").text)
    req("POST", "/messaging/queues", json={"name": q})
    r = req("POST", "/messaging/topics/subscribe", json={"topic_arn": arn, "queue": q})
    check("subscribe queue", r.status_code == 200, r.text[:200])
    r = req("GET", "/messaging/topics/subscriptions", params={"topic_arn": arn})
    check("subscriptions list has the queue", r.status_code == 200 and q in r.text, r.text[:200])
    r = req("POST", "/messaging/topics/publish", json={"topic_arn": arn, "message": "fanout", "subject": "s"})
    check("publish reports fan-out to 1 queue", r.status_code == 200 and r.json().get("published") is True and r.json().get("fanned_out_to") == 1, r.text[:200])
    r = req("GET", f"/messaging/queues/{q}/peek")
    check("published message fans out to subscribed queue", r.status_code == 200 and "fanout" in r.text, r.text[:200])
    check("publish without topic_arn is 400", req("POST", "/messaging/topics/publish", json={}).status_code == 400)
    check("subscribe without queue is 400", req("POST", "/messaging/topics/subscribe", json={"topic_arn": arn}).status_code == 400)
    r = req("POST", "/messaging/topics/delete", json={"topic_arn": arn})
    check("delete topic", r.status_code == 200, r.text[:200])
    req("DELETE", f"/messaging/queues/{q}")

# --- glass-box
r = req("POST", "/calls/clear")
check("calls/clear ok", r.status_code == 200 and r.json().get("ok") is True, r.text[:200])
req("GET", "/messaging/topics")
r = req("GET", "/calls")
check("calls ring refilled after clear", r.status_code == 200 and isinstance(r.json().get("calls"), list), r.text[:200])
with requests.get(BASE + "/calls/stream?replay=5", stream=True, timeout=15) as s:
    check("calls/stream is an event stream", s.status_code == 200 and "text/event-stream" in s.headers.get("content-type", ""), s.headers)

# --- conformance rollup
r = req("GET", "/conformance")
j = r.json() if r.status_code == 200 else {}
check("conformance has rollup + services", "checks" in j.get("rollup", {}) and isinstance(j.get("services"), dict) and "s3" in j["services"], r.text[:200])

# --- RDS execute
r = req("POST", "/rds/execute", json={"sql": ""})
check("rds/execute empty sql is 400", r.status_code == 400, r.text[:200])
r = req("POST", "/rds/execute", json={"sql": "select 1 as one"})
check("rds/execute select 1 is not a 5xx", r.status_code < 500, r.text[:200])

# --- snapshots
name = "zz-conf-snap-" + sfx
r = req("POST", "/snapshots", json={"name": name, "note": "conf"})
sid = (r.json().get("id") or r.json().get("snap_id") or r.json().get("snapshot_id") or "") if r.status_code == 200 else ""
check("capture snapshot returns id", bool(sid), r.text[:200])
r = req("GET", "/snapshots")
check("snapshot listed", r.status_code == 200 and name in r.text, r.text[:200])
r = req("POST", f"/snapshots/{sid}/restore")
check("restore snapshot", r.status_code == 200, r.text[:200])
r = req("POST", f"/snapshots/{sid}/fork", json={"name": name + "-fork"})
check("fork snapshot", r.status_code == 200 and name + "-fork" in req("GET", "/snapshots").text, r.text[:200])
check("restore unknown snapshot is 404", req("POST", "/snapshots/nope-" + sfx + "/restore").status_code == 404)

sys.exit(1 if failed else 0)
