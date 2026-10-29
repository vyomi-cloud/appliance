"""Automatic issue reporting — scrubber, classifier, fingerprint, reporter modes.
Pure Python, no network. Run: python3 tests/conformance/test_issue_report_core.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from core import issue_report as ir  # noqa: E402

failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


# ── scrubber: every category, on real-shaped payloads ──────────────────
for c in json.load(open(os.path.join(HERE, "issue_report_fixtures.json")))["cases"]:
    out = ir.scrub_text(c["message"], 1000)
    left = [f for f in c["forbidden"] if f.lower() in out.lower()]
    check(f"scrub[{c['name']}] removes sensitive values", not left, f"{left} in {out!r}")

check("hash_name is stable and one-way", ir.hash_name("a") == ir.hash_name("a") != ir.hash_name("b")
      and "payroll" not in ir.hash_name("payroll"))
rep = ir.build_report(cloud="aws", service="s3", action="PutObject on 'my-bucket'", status=500,
                      code="InternalError", message="boom 'my-bucket' 10.0.0.1",
                      frames=["/home/u/app/server.py:handler", ("/x/y/core.py", "do_put", 12)],
                      surface="offline", tier="pro", version="3.0.24")
blob = json.dumps(rep)
check("report keeps only the allow-listed keys", set(rep) == {"cloud", "service", "action", "status", "code", "message",
                                                             "frames", "version", "surface", "tier", "kind"}, sorted(rep))
check("report carries no resource name / ip / path", "my-bucket" not in blob and "10.0.0.1" not in blob and "/home" not in blob, blob)
check("frames are file:function only", rep["frames"] == ["server.py:handler", "core.py:do_put"], rep["frames"])
check("frames capped at 5", len(ir.build_report(cloud="aws", service="s3", action="x", frames=[f"f{i}.py:g" for i in range(9)])["frames"]) == 5)

# ── classification ────────────────────────────────────────────────────
check("5xx is reported", ir.should_report(500) and ir.should_report(503, "InternalFailure"))
check("tier lock 403 is not reported", not ir.should_report(403, "tier_locked") and not ir.should_report(403, "TierLimit"))
check("402/403 tier message is not reported", not ir.should_report(402, "", message="tier required: upgrade"))
check("4xx the user caused are not reported", not any(ir.should_report(s, "NoSuchBucket") for s in (400, 404, 409, 422)))
check("cancelled requests are not reported", not ir.should_report(500, cancelled=True))
check("exceptions and JS errors are reported", ir.should_report(None, kind="exception") and ir.should_report(None, kind="js-error"))
check("failed console action: 5xx yes, 4xx no", ir.should_report(500, kind="console-action") and not ir.should_report(404, kind="console-action"))

# ── routing ───────────────────────────────────────────────────────────
check("route: X-Amz-Target", ir.derive_route("POST", "/", {"X-Amz-Target": "DynamoDB_20120810.PutItem"}) == ("aws", "dynamodb", "PutItem"))
check("route: console api", ir.derive_route("POST", "/api/aws/ec2/instances")[:2] == ("aws", "ec2"))
check("route: ARM", ir.derive_route("PUT", "/subscriptions/s/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/a")[:2] == ("azure", "storage"))

# ── fingerprint: one issue per fingerprint ────────────────────────────
a = ir.build_report(cloud="aws", service="s3", action="PutObject", status=500, code="InternalError",
                    message="failed for bucket 'one' at 1.2.3.4 after 41 ms", frames=["a.py:f"])
b = ir.build_report(cloud="aws", service="s3", action="PutObject", status=500, code="InternalError",
                    message="failed for bucket 'two' at 9.9.9.9 after 97 ms", frames=["a.py:f"])
d = ir.build_report(cloud="aws", service="s3", action="GetObject", status=500, code="InternalError",
                    message="failed for bucket 'two' at 9.9.9.9 after 97 ms", frames=["a.py:f"])
check("same bug, different names/ips/numbers -> same fingerprint", ir.fingerprint(a) == ir.fingerprint(b))
check("different action -> different fingerprint", ir.fingerprint(a) != ir.fingerprint(d))

# ── reporter: modes, dedupe, queue, opt-out ───────────────────────────
sent = []
os.environ.pop("VYOMI_NO_TELEMETRY", None)
r = ir.IssueReporter(lambda p: sent.append(p) or True, surface="sandbox", version="1", sync=True)
check("no consent yet -> mode is None, reports go out anonymous", r.mode is None and not r.consent_asked)
p1 = r.report(cloud="aws", service="s3", action="PutObject", status=500, message="boom")
check("a 5xx files exactly one report (anonymous before consent)", len(sent) == 1 and sent[0]["mode"] == "anonymous", sent)
check("payload has no user-identifying field", set(sent[0]) == {"fingerprint", "mode", "report"})
r.report(cloud="aws", service="s3", action="PutObject", status=500, message="boom")
check("a repeat sends nothing new (portal adds the +1 on the existing fingerprint)", len(sent) == 1)
r.report(cloud="aws", service="s3", action="PutObject", status=403, code="tier_locked", message="x")
r.report(cloud="aws", service="s3", action="PutObject", status=404, code="NoSuchBucket", message="x")
check("tier 403 and 4xx never send", len(sent) == 1)
r.set_mode("named")
r.report(cloud="aws", service="sqs", action="SendMessage", status=500, message="other")
check("consenting user -> mode named", sent[-1]["mode"] == "named" and r.public_settings()["mode"] == "named")
r.set_mode("anonymous")
r.report(cloud="gcp", service="pubsub", action="Publish", status=500, message="other2")
check("declined -> mode anonymous, no username anywhere", sent[-1]["mode"] == "anonymous" and "user" not in json.dumps(sent[-1]).lower())
try:
    r.set_mode("everyone"); check("invalid mode rejected", False)
except ValueError:
    check("invalid mode rejected", True)

os.environ["VYOMI_NO_TELEMETRY"] = "1"
n = len(sent)
r2 = ir.IssueReporter(lambda p: sent.append(p) or True, sync=True)
check("VYOMI_NO_TELEMETRY=1 sends nothing", r2.report(cloud="aws", service="s3", action="x", status=500, message="m") is None and len(sent) == n)
os.environ.pop("VYOMI_NO_TELEMETRY")

up = {"ok": False}
q = ir.IssueReporter(lambda p: up["ok"], sync=True)
q.report(cloud="aws", service="s3", action="Put", status=500, message="offline")
check("failed send is queued", q.public_settings()["queued"] == 1)
up["ok"] = True
check("queue retries when the portal is back", q.flush() == 1 and q.public_settings()["queued"] == 0)
saved = {}
q2 = ir.IssueReporter(lambda p: False, sync=True, settings={}, persist=lambda s: saved.update(json.loads(json.dumps(s))))
q2.report(cloud="aws", service="s3", action="Put2", status=500, message="offline")
check("queue is persisted for restart", len(saved.get("queue", [])) == 1)

sys.exit(1 if failed else 0)
