"""Automatic issue reporting on the REAL appliance path: the ASGI middleware + intake routes
mounted on a FastAPI app. A forced 5xx files exactly one scrubbed report; a repeat adds none
(the portal adds the +1); tier 403 / 4xx / VYOMI_NO_TELEMETRY send nothing.
Run: python3 tests/conformance/test_issue_report_middleware.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import issue_report as ir  # noqa: E402
from core import issue_report_runtime as rt  # noqa: E402

failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


os.environ.pop("VYOMI_NO_TELEMETRY", None)
sent = []
reporter = ir.IssueReporter(lambda p: sent.append(p) or True, surface="offline", version="3.0.24", sync=True)
rt.reset_reporter(reporter)

app = FastAPI()
app.add_middleware(rt.IssueReportMiddleware, reporter_fn=lambda: reporter)


@app.get("/api/aws/s3/buckets/{name}")
def boom(name: str):
    return JSONResponse({"code": "InternalError", "detail": f"disk failure for '{name}' from 10.1.2.3 user a@b.io"}, status_code=500)


@app.get("/api/aws/ec2/crash")
def crash():
    raise RuntimeError("unexpected state for arn:aws:ec2:us-east-1:123456789012:instance/i-0abc")


@app.get("/api/aws/s3/locked")
def locked():
    return JSONResponse({"code": "tier_locked", "detail": "upgrade"}, status_code=403)


@app.get("/api/aws/s3/missing")
def missing():
    raise HTTPException(404, "no such bucket")


from routes import issue_reporting  # noqa: E402
issue_reporting.register(app)

c = TestClient(app, raise_server_exceptions=False)
r = c.get("/api/aws/s3/buckets/payroll-2026")
check("the 5xx response reaches the client unchanged", r.status_code == 500 and r.json()["code"] == "InternalError")
check("forced 5xx files exactly one report", len(sent) == 1, sent)
blob = repr(sent)
check("report has cloud/service/status/code", sent[0]["report"]["cloud"] == "aws" and sent[0]["report"]["service"] == "s3"
      and sent[0]["report"]["status"] == 500 and sent[0]["report"]["code"] == "InternalError", sent[0]["report"])
check("report is scrubbed (name, ip, email gone)", "payroll-2026" not in blob and "10.1.2.3" not in blob and "a@b.io" not in blob, blob)
c.get("/api/aws/s3/buckets/payroll-2027")
check("a repeat of the same bug adds no new report", len(sent) == 1)

r = c.get("/api/aws/ec2/crash")
check("unhandled exception answers 500 and is reported with frames", r.status_code == 500 and len(sent) == 2
      and sent[1]["report"]["kind"] == "exception" and sent[1]["report"]["frames"], sent[1:])
check("exception report carries no account id / instance id", "123456789012" not in repr(sent[1]) and "i-0abc" not in repr(sent[1]), sent[1])

n = len(sent)
c.get("/api/aws/s3/locked"); c.get("/api/aws/s3/missing"); c.get("/nope")
check("tier 403 and 4xx never file", len(sent) == n)

# console intake route
r = c.post("/api/issue-reporting/report", json={"kind": "js-error", "cloud": "aws", "service": "console",
                                                 "message": "TypeError at user@x.com", "action": "window.onerror"})
check("console JS error is accepted and sent", r.json()["reported"] is True and len(sent) == n + 1)
r = c.post("/api/issue-reporting/report", json={"kind": "js-error", "message": "x", "cancelled": True})
check("cancelled console request is not reported", r.json()["reported"] is False)
r = c.post("/api/issue-reporting/report", json={"kind": "console-action", "status": 404, "message": "nf"})
check("console 4xx is not reported", r.json()["reported"] is False)

# settings
r = c.get("/api/issue-reporting").json()
check("settings start undecided", r["mode"] is None and r["consent_asked"] is False and r["enabled"] is True, r)
check("PUT named", c.put("/api/issue-reporting", json={"mode": "named"}).json()["mode"] == "named")
check("choice persists (dialog never shows again)", c.get("/api/issue-reporting").json()["consent_asked"] is True)
check("PUT anonymous", c.put("/api/issue-reporting", json={"mode": "anonymous"}).json()["mode"] == "anonymous")
check("PUT invalid -> 400", c.put("/api/issue-reporting", json={"mode": "x"}).status_code == 400)

# account sync from licence refresh
st = {}
rt.apply_account_mode(st, "named")
check("licence refresh syncs the portal account's mode", st["issue_reporting"]["mode"] == "named")
rt.apply_account_mode(st, "bogus")
check("unknown mode from the portal is ignored", st["issue_reporting"]["mode"] == "named")

# opt-out
os.environ["VYOMI_NO_TELEMETRY"] = "1"
n = len(sent)
c.get("/api/aws/s3/buckets/other"); c.get("/api/aws/ec2/crash")
c.post("/api/issue-reporting/report", json={"kind": "js-error", "message": "fresh error"})
check("VYOMI_NO_TELEMETRY=1: nothing is sent from any path", len(sent) == n)
check("VYOMI_NO_TELEMETRY=1: settings say disabled", c.get("/api/issue-reporting").json()["enabled"] is False)
os.environ.pop("VYOMI_NO_TELEMETRY")

# ── the REAL appliance app (server.py): middleware is installed, settings route is live ──
import server  # noqa: E402
sent2 = []
real = ir.IssueReporter(lambda p: sent2.append(p) or True, surface="sandbox", version="3.0.24", sync=True)
rt.reset_reporter(real)


@server.app.get("/api/aws/s3/__force500")
def _force500():
    raise RuntimeError("forced failure for 'acme-prod' 203.0.113.9")


server.app.router.routes.insert(0, server.app.router.routes.pop())   # ahead of any catch-all
rc = TestClient(server.app, raise_server_exceptions=False)
r = rc.get("/api/aws/s3/__force500")
check("real appliance: forced 5xx answers 500", r.status_code == 500, r.status_code)
check("real appliance: exactly one scrubbed report, surface=sandbox", len(sent2) == 1 and sent2[0]["report"]["surface"] == "sandbox"
      and "acme-prod" not in repr(sent2) and "203.0.113.9" not in repr(sent2), sent2)
rc.get("/api/aws/s3/__force500")
check("real appliance: repeat adds no new report", len(sent2) == 1)
check("real appliance: settings route is registered", rc.get("/api/issue-reporting").json()["mode"] is None)
rt.reset_reporter(None)
sys.exit(1 if failed else 0)
