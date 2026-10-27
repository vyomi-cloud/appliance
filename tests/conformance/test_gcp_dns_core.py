"""Unit tests for core/gcp_dns_core.py (run: python3 tests/conformance/test_gcp_dns_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_dns_core as dns  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


Z = "/dns/v1/projects/p1/managedZones"


def call(st, method, path, body=None, query=None):
    r = dns.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def rr(name, typ="A", data=("1.2.3.4",), ttl=300):
    return {"name": name, "type": typ, "ttl": ttl, "rrdatas": list(data)}


def main():
    st = dns.CloudDnsStore()
    s, b = call(st, "POST", Z, {"name": "z1", "dnsName": "example.com.", "description": "d"})
    check("create zone", s == 200 and b["kind"] == "dns#managedZone" and len(b["nameServers"]) == 4
          and b["visibility"] == "public" and b["id"].isdigit(), b)
    s, b = call(st, "POST", Z, {"name": "z1", "dnsName": "example.com."})
    check("duplicate zone → 409 alreadyExists", s == 409 and b["error"]["errors"][0]["reason"] == "alreadyExists", b)
    s, b = call(st, "POST", Z, {"name": "z2", "dnsName": "example.com"})
    check("dnsName without trailing dot → 400", s == 400 and b["error"]["status"] == "INVALID_ARGUMENT", b)
    s, b = call(st, "POST", Z, {"name": "Bad_Name", "dnsName": "x.com."})
    check("bad zone name → 400", s == 400, b)
    s, b = call(st, "GET", Z + "/nope")
    check("get missing zone → 404 notFound", s == 404 and b["error"]["errors"][0]["reason"] == "notFound", b)
    s, b = call(st, "GET", Z + "/z1")
    check("get zone", s == 200 and b["name"] == "z1" and b["dnsName"] == "example.com.", b)
    s, b = call(st, "GET", Z)
    check("list zones", s == 200 and [z["name"] for z in b["managedZones"]] == ["z1"], b)
    s, b = call(st, "GET", Z, query={"dnsName": "other.org."})
    check("list zones filtered by dnsName", s == 200 and not b.get("managedZones"), b)

    s, b = call(st, "GET", Z + "/z1/rrsets")
    check("new zone has NS + SOA", s == 200 and [r["type"] for r in b["rrsets"]] == ["NS", "SOA"], b)
    soa0 = b["rrsets"][1]["rrdatas"][0]

    s, b = call(st, "POST", Z + "/z1/changes", {"additions": [rr("www.example.com."), rr("m.example.com.", "MX", ["10 mail.example.com."])]})
    check("change adds record sets", s == 200 and b["status"] == "done" and b["id"] == "1" and len(b["additions"]) == 2, b)
    s, b = call(st, "GET", Z + "/z1/rrsets")
    soa1 = [r for r in b["rrsets"] if r["type"] == "SOA"][0]["rrdatas"][0]
    check("SOA serial bumped by change", int(soa1.split()[2]) == int(soa0.split()[2]) + 1, (soa0, soa1))
    s, b = call(st, "POST", Z + "/z1/changes", {"additions": [rr("www.example.com.")]})
    check("adding an existing rrset → 409", s == 409 and "already exists" in b["error"]["message"], b)
    s, b = call(st, "POST", Z + "/z1/changes", {"additions": [rr("x.other.org.")]})
    check("name outside the zone → 400", s == 400, b)
    s, b = call(st, "POST", Z + "/z1/changes", {"additions": [rr("bad.example.com.", "A", ["not-an-ip"])]})
    check("bad A rrdata → 400", s == 400, b)
    s, b = call(st, "POST", Z + "/z1/changes", {"additions": [rr("c.example.com.", "CNAME", ["www.example.com"])]})
    check("CNAME target without dot → 400", s == 400, b)
    s, b = call(st, "POST", Z + "/z1/changes", {"deletions": [rr("www.example.com.", ttl=60)]})
    check("delete with wrong ttl → 412 conditionNotMet", s == 412 and b["error"]["errors"][0]["reason"] == "conditionNotMet", b)
    s, b = call(st, "POST", Z + "/z1/changes", {"deletions": [rr("ghost.example.com.")]})
    check("delete missing → 404", s == 404, b)
    s, b = call(st, "POST", Z + "/z1/changes", {"additions": [rr("www.example.com.", "CNAME", ["a.example.com."])]})
    check("CNAME next to A → 409", s == 409, b)
    s, b = call(st, "POST", Z + "/z1/changes", {"deletions": [rr("www.example.com.")], "additions": [rr("www.example.com.", ttl=60, data=["9.9.9.9"])]})
    check("atomic replace (delete + add)", s == 200 and b["id"] == "2", b)

    s, b = call(st, "GET", Z + "/z1/rrsets/www.example.com./A")
    check("rrsets.get", s == 200 and b["ttl"] == 60 and b["rrdatas"] == ["9.9.9.9"], b)
    s, b = call(st, "PATCH", Z + "/z1/rrsets/www.example.com./A", {"ttl": 120, "rrdatas": ["8.8.8.8"]})
    check("rrsets.patch", s == 200 and b["ttl"] == 120 and b["rrdatas"] == ["8.8.8.8"], b)
    s, b = call(st, "POST", Z + "/z1/rrsets", rr("t.example.com.", "TXT", ['"hello"']))
    check("rrsets.create", s == 200 and b["type"] == "TXT", b)
    s, b = call(st, "GET", Z + "/z1/rrsets", query={"name": "t.example.com.", "type": "TXT"})
    check("rrsets.list filtered by name+type", [r["name"] for r in b["rrsets"]] == ["t.example.com."], b)
    s, b = call(st, "GET", Z + "/z1/rrsets", query={"type": "A"})
    check("rrsets.list type without name → 400", s == 400, b)
    s, b = call(st, "GET", Z + "/z1/rrsets", query={"maxResults": "2"})
    check("rrsets.list pagination", len(b["rrsets"]) == 2 and b["nextPageToken"] == "2", b)
    s, b2 = call(st, "GET", Z + "/z1/rrsets", query={"maxResults": "2", "pageToken": b["nextPageToken"]})
    check("rrsets.list page 2", len(b2["rrsets"]) >= 1 and b2["rrsets"][0] != b["rrsets"][0], b2)
    s, b = call(st, "DELETE", Z + "/z1/rrsets/t.example.com./TXT")
    check("rrsets.delete", s == 200, b)
    s, b = call(st, "GET", Z + "/z1/rrsets/t.example.com./TXT")
    check("deleted rrset → 404", s == 404, b)

    s, b = call(st, "GET", Z + "/z1/changes")
    check("changes.list", s == 200 and len(b["changes"]) >= 4 and b["changes"][0]["id"] == "1", b)
    s, b = call(st, "GET", Z + "/z1/changes", query={"sortOrder": "descending"})
    check("changes.list descending", int(b["changes"][0]["id"]) > int(b["changes"][-1]["id"]), b)
    s, b = call(st, "GET", Z + "/z1/changes/1")
    check("changes.get", s == 200 and b["kind"] == "dns#change", b)
    s, b = call(st, "GET", Z + "/z1/changes/999")
    check("changes.get missing → 404", s == 404, b)

    s, b = call(st, "POST", Z + "/z1/changes", {"deletions": [[r for r in call(st, "GET", Z + "/z1/rrsets")[1]["rrsets"] if r["type"] == "NS"][0]]})
    check("cannot delete apex NS → 400", s == 400, b)

    s, b = call(st, "PATCH", Z + "/z1", {"description": "new", "labels": {"env": "dev"}})
    check("patch zone returns operation", s == 200 and b["kind"] == "dns#operation" and b["status"] == "DONE", b)
    s, b = call(st, "GET", Z + "/z1")
    check("patch persisted", b["description"] == "new" and b["labels"] == {"env": "dev"}, b)

    s, b = call(st, "DELETE", Z + "/z1")
    check("delete non-empty zone → 400 containerNotEmpty", s == 400 and b["error"]["errors"][0]["reason"] == "containerNotEmpty", b)
    for r in call(st, "GET", Z + "/z1/rrsets")[1]["rrsets"]:
        if r["type"] not in ("NS", "SOA"):
            call(st, "DELETE", Z + "/z1/rrsets/%s/%s" % (r["name"], r["type"]))
    s, b = call(st, "DELETE", Z + "/z1")
    check("delete empty zone → 204", s == 204, b)
    s, b = call(st, "GET", Z + "/z1")
    check("deleted zone gone", s == 404, b)

    # private zone + dnssec + keys
    s, b = call(st, "POST", Z, {"name": "priv", "dnsName": "corp.internal.", "visibility": "private",
                                "privateVisibilityConfig": {"networks": [{"networkUrl": "projects/p1/global/networks/default"}]}})
    check("private zone has no nameServers", s == 200 and "nameServers" not in b and b["visibility"] == "private", b)
    s, b = call(st, "POST", Z, {"name": "sec", "dnsName": "sec.org.", "dnssecConfig": {"state": "on"}})
    s, b = call(st, "GET", Z + "/sec/dnsKeys")
    check("dnsKeys populated for DNSSEC zone", s == 200 and {k["type"] for k in b["dnsKeys"]} == {"keySigning", "zoneSigning"}, b)
    s, b = call(st, "GET", Z + "/priv/dnsKeys")
    check("dnsKeys empty without DNSSEC", s == 200 and not b["dnsKeys"], b)

    # policies
    PP = "/dns/v1/projects/p1/policies"
    s, b = call(st, "POST", PP, {"name": "pol", "enableInboundForwarding": True,
                                 "networks": [{"networkUrl": "projects/p1/global/networks/default"}]})
    check("create policy", s == 200 and b["kind"] == "dns#policy" and b["enableInboundForwarding"], b)
    s, b = call(st, "DELETE", PP + "/pol")
    check("delete attached policy → 400", s == 400, b)
    s, b = call(st, "PATCH", PP + "/pol", {"networks": [], "enableLogging": True})
    check("patch policy", s == 200 and b["policy"]["enableLogging"] and b["policy"]["networks"] == [], b)
    s, b = call(st, "GET", PP)
    check("list policies", [p["name"] for p in b["policies"]] == ["pol"], b)
    s, b = call(st, "DELETE", PP + "/pol")
    check("delete policy", s == 204, b)

    s, b = call(st, "GET", "/dns/v1/projects/p1")
    check("projects.get quota", s == 200 and b["kind"] == "dns#project" and b["quota"]["managedZones"] > 0, b)

    v = dns.console_view(st.zones["p1/priv"])
    blank = [k for k in ("id", "dns_name", "zone_type", "description_text", "record_count", "name_servers_text",
                         "dnssec_state", "created") if v.get(k) in (None, "")]
    check("console view columns filled", not blank and v["zone_type"] == "Private", blank)
    f = dns.zone_from_form({"name": "web", "dnsName": "web.dev", "description": ""})
    check("zone_from_form adds trailing dot", f["dnsName"] == "web.dev." and f["visibility"] == "public", f)

    print(f"RESULT pass={PASS} fail={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
