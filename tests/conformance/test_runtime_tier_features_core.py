"""Core logic behind the tier-gated runtime routes: audit sinks, notification channels and
cross-tenant RBAC grants (create / list / validate / revoke / permission check)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import audit_sinks, cross_tenant_rbac as xt, notifications  # noqa: E402

failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


st = {}
check("audit sink: unknown kind rejected", raises(audit_sinks.register_sink, st, "t1", {"kind": "pigeon"}))
check("audit sink: webhook needs http(s) url", raises(audit_sinks.register_sink, st, "t1", {"kind": "webhook", "url": "ftp://x"}))
check("audit sink: file needs path", raises(audit_sinks.register_sink, st, "t1", {"kind": "file"}))
s = audit_sinks.register_sink(st, "t1", {"kind": "file", "path": "/tmp/a.jsonl"})
check("audit sink: shaped record", s["id"].startswith("asink-") and s["created_at"] and s["event_count"] == 0, s)
check("audit sink: listed per tenant", [x["id"] for x in audit_sinks.list_sinks(st, "t1")] == [s["id"]]
      and audit_sinks.list_sinks(st, "t2") == [])
check("audit sink: other tenant cannot delete", not audit_sinks.delete_sink(st, "t2", s["id"]))
check("audit sink: delete", audit_sinks.delete_sink(st, "t1", s["id"]) and not audit_sinks.delete_sink(st, "t1", s["id"]))

st = {}
check("channel: unknown kind rejected", raises(notifications.register_channel, st, "t1", {"kind": "pager"}))
check("channel: webhook needs url", raises(notifications.register_channel, st, "t1", {"kind": "webhook", "url": "x"}))
check("channel: email needs mailto", raises(notifications.register_channel, st, "t1", {"kind": "email", "url": "a@b.c"}))
c = notifications.register_channel(st, "t1", {"kind": "email", "url": "mailto:ops@example.com", "name": "ops"})
check("channel: shaped record", c["id"].startswith("nch-") and c["events"] == ["*"] and c["sent_count"] == 0 and c["name"] == "ops", c)
check("channel: listed per tenant", [x["id"] for x in notifications.list_channels(st, "t1")] == [c["id"]]
      and notifications.list_channels(st, "t2") == [])
check("channel: delete", notifications.delete_channel(st, "t1", c["id"]) and not notifications.delete_channel(st, "t1", c["id"]))

st = {}
check("grant: grantee required", raises(xt.create_grant, st, "a", {}))
check("grant: self grant rejected", raises(xt.create_grant, st, "a", {"grantee_tenant": "a"}))
check("grant: bad role rejected", raises(xt.create_grant, st, "a", {"grantee_tenant": "b", "role": "root"}))
g = xt.create_grant(st, "a", {"grantee_tenant": "b", "role": "operator", "services": ["s3"]})
check("grant: shaped record", g["id"].startswith("xtg-") and g["role"] == "operator" and g["use_count"] == 0, g)
check("grant: visible to grantor and grantee only", len(xt.list_grants(st, "a")) == 1 and len(xt.list_grants(st, "b")) == 1
      and xt.list_grants(st, "c") == [])
check("grant: operator may POST on granted service", xt.check(st, "b", "a", "POST", "s3")["ok"])
check("grant: operator may not DELETE", not xt.check(st, "b", "a", "DELETE", "s3")["ok"])
check("grant: other service denied", not xt.check(st, "b", "a", "GET", "ec2")["ok"])
check("grant: use is counted", xt.list_grants(st, "a")[0]["use_count"] == 1)
check("grant: grantee cannot revoke", not xt.delete_grant(st, g["id"], "b"))
check("grant: grantor revokes", xt.delete_grant(st, g["id"], "a") and not xt.check(st, "b", "a", "GET", "s3")["ok"])
sys.exit(1 if failed else 0)
