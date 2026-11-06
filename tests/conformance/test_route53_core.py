"""Route 53 engine conformance — host (CPython) and Pyodide.

Drives core/route53_core.py on the native REST-XML wire: hosted zone and record
lifecycle, atomic change batches, health checks, delegation sets, tags, query
logging, resolution, the CoreDNS zone files, the errors real SDKs branch on and the
console REST view built on the same engine.
"""
import re

try:
    from core import route53_core as r53
except ImportError:  # pragma: no cover - Pyodide flat layout
    import route53_core as r53  # type: ignore

P = r53.PREFIX
NS = f'xmlns="{r53.NS}"'


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or r53.Route53Store()

    def call(method, path, body="", **q):
        return r53.dispatch(s, method, P + path, q, {}, body.encode())

    def ok(method, path, body="", **q):
        r = call(method, path, body, **q)
        if r.status >= 300:
            raise AssertionError((method, path, r.body))
        return r.body.decode()

    def code(method, path, body="", **q):
        r = call(method, path, body, **q)
        return r.status, re.search(r"<Code>(.*?)</Code>", r.body.decode()).group(1)

    def one(tag, body):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    def change(zid, *chs):
        xs = "".join(
            f"<Change><Action>{a}</Action><ResourceRecordSet><Name>{n}</Name><Type>{t}</Type>{extra}</ResourceRecordSet></Change>"
            for a, n, t, extra in chs)
        return f"<ChangeResourceRecordSetsRequest {NS}><ChangeBatch><Changes>{xs}</Changes></ChangeBatch></ChangeResourceRecordSetsRequest>"

    def rr(ttl, *vals):
        return f"<TTL>{ttl}</TTL><ResourceRecords>" + "".join(f"<ResourceRecord><Value>{v}</Value></ResourceRecord>" for v in vals) + "</ResourceRecords>"

    # ── hosted zones ──
    create = f"<CreateHostedZoneRequest {NS}><Name>Example.com</Name><CallerReference>ref-1</CallerReference><HostedZoneConfig><Comment>hi</Comment></HostedZoneConfig></CreateHostedZoneRequest>"
    r = call("POST", "/hostedzone", create)
    body = r.body.decode()
    zid = one("Id", body).split("/")[-1]
    _check("create returns 201 + Location", r.status == 201 and zid in r.headers["Location"])
    _check("zone id is real-shaped", re.fullmatch(r"Z[0-9A-Z]{19}", zid) is not None)
    _check("name normalised with trailing dot", "<Name>example.com.</Name>" in body)
    _check("four name servers", body.count("<NameServer>") == 4)
    _check("change starts PENDING", "<Status>PENDING</Status>" in body)
    cid = re.search(r"<ChangeInfo><Id>/change/(.*?)</Id>", body).group(1)
    _check("GetChange is INSYNC", "<Status>INSYNC</Status>" in ok("GET", f"/change/{cid}"))
    _check("duplicate caller reference", code("POST", "/hostedzone", create) == (409, "HostedZoneAlreadyExists"))
    _check("bad domain name", code("POST", "/hostedzone", create.replace("Example.com", "bad..name").replace("ref-1", "r2"))[1] == "InvalidDomainName")
    _check("private zone needs a VPC", code("POST", "/hostedzone", create.replace("<HostedZoneConfig>", "<HostedZoneConfig><PrivateZone>true</PrivateZone>").replace("ref-1", "r3"))[1] == "InvalidInput")
    g = ok("GET", f"/hostedzone/{zid}")
    _check("get shows SOA+NS count", "<ResourceRecordSetCount>2</ResourceRecordSetCount>" in g and "<Comment>hi</Comment>" in g)
    _check("get accepts /hostedzone/ prefixed id", "<HostedZone>" in ok("GET", f"/hostedzone/%2Fhostedzone%2F{zid}"))
    _check("missing zone", code("GET", "/hostedzone/ZNOPE") == (404, "NoSuchHostedZone"))
    _check("list", zid in ok("GET", "/hostedzone") and "<IsTruncated>false</IsTruncated>" in ok("GET", "/hostedzone"))
    _check("count", "<HostedZoneCount>1</HostedZoneCount>" in ok("GET", "/hostedzonecount"))
    _check("by name", zid in ok("GET", "/hostedzonesbyname", dnsname="example.com"))
    _check("update comment", "<Comment>new</Comment>" in ok("POST", f"/hostedzone/{zid}", f"<UpdateHostedZoneCommentRequest {NS}><Comment>new</Comment></UpdateHostedZoneCommentRequest>"))

    # ── record sets ──
    r = ok("POST", f"/hostedzone/{zid}/rrset", change(zid, ("CREATE", "www.example.com", "A", rr(300, "192.0.2.1", "192.0.2.2")),
                                                      ("CREATE", "*.example.com", "TXT", rr(60, '"hello"'))))
    _check("change batch accepted", "<Status>PENDING</Status>" in r)
    lst = ok("GET", f"/hostedzone/{zid}/rrset")
    _check("records listed incl. SOA/NS", lst.count("<ResourceRecordSet>") == 4 and "<Type>SOA</Type>" in lst)
    _check("wildcard echoed as octal escape", "\\052.example.com." in lst)
    _check("create dup is atomic InvalidChangeBatch", code("POST", f"/hostedzone/{zid}/rrset", change(zid, ("CREATE", "new.example.com", "A", rr(60, "1.1.1.1")), ("CREATE", "www.example.com", "A", rr(300, "9.9.9.9"))))[1] == "InvalidChangeBatch")
    _check("nothing from the failed batch applied", "new.example.com" not in ok("GET", f"/hostedzone/{zid}/rrset"))
    _check("outside the zone", code("POST", f"/hostedzone/{zid}/rrset", change(zid, ("CREATE", "x.other.org", "A", rr(60, "1.1.1.1"))))[1] == "InvalidChangeBatch")
    _check("CNAME beside A rejected", code("POST", f"/hostedzone/{zid}/rrset", change(zid, ("CREATE", "www.example.com", "CNAME", rr(60, "a.example.com"))))[1] == "InvalidChangeBatch")
    ok("POST", f"/hostedzone/{zid}/rrset", change(zid, ("UPSERT", "www.example.com", "A", rr(120, "192.0.2.9"))))
    _check("upsert replaces", "192.0.2.9" in ok("GET", f"/hostedzone/{zid}/rrset") and "192.0.2.2" not in ok("GET", f"/hostedzone/{zid}/rrset"))
    _check("delete with wrong values", code("POST", f"/hostedzone/{zid}/rrset", change(zid, ("DELETE", "www.example.com", "A", rr(120, "0.0.0.0"))))[1] == "InvalidChangeBatch")
    _check("list by name/type", ok("GET", f"/hostedzone/{zid}/rrset", name="www.example.com", type="A", maxitems="1").count("<ResourceRecordSet>") == 1)
    page = ok("GET", f"/hostedzone/{zid}/rrset", maxitems="2")
    _check("pagination", "<IsTruncated>true</IsTruncated>" in page and "<NextRecordName>" in page)
    ok("POST", f"/hostedzone/{zid}/rrset", change(zid, ("CREATE", "alias.example.com", "A", f'<AliasTarget><HostedZoneId>{zid}</HostedZoneId><DNSName>www.example.com</DNSName><EvaluateTargetHealth>false</EvaluateTargetHealth></AliasTarget>')))
    t = ok("GET", "/testdnsanswer", hostedzoneid=zid, recordname="alias.example.com", recordtype="A")
    _check("TestDNSAnswer follows alias", "192.0.2.9" in t and "<ResponseCode>NOERROR</ResponseCode>" in t)
    _check("TestDNSAnswer wildcard", "hello" in ok("GET", "/testdnsanswer", hostedzoneid=zid, recordname="a.b.example.com", recordtype="TXT"))
    _check("TestDNSAnswer NXDOMAIN", "NXDOMAIN" in ok("GET", "/testdnsanswer", hostedzoneid=zid, recordname="nope.example.org", recordtype="A"))
    zf = r53.zone_files(s)["example.com"]
    _check("zone file for CoreDNS", "www.example.com. 120 IN A 192.0.2.9" in zf and "alias.example.com. 60 IN A 192.0.2.9" in zf and "SOA" in zf)

    # ── delete rules ──
    _check("non-empty zone cannot be deleted", code("DELETE", f"/hostedzone/{zid}") == (400, "HostedZoneNotEmpty"))
    ok("POST", f"/hostedzone/{zid}/rrset", change(zid, ("DELETE", "www.example.com", "A", rr(120, "192.0.2.9")),
                                                  ("DELETE", "alias.example.com", "A", f"<AliasTarget><HostedZoneId>{zid}</HostedZoneId><DNSName>www.example.com</DNSName><EvaluateTargetHealth>false</EvaluateTargetHealth></AliasTarget>"),
                                                  ("DELETE", "*.example.com", "TXT", rr(60, '"hello"'))))

    # ── health checks ──
    hc = f"<CreateHealthCheckRequest {NS}><CallerReference>hc-1</CallerReference><HealthCheckConfig><Type>HTTPS</Type><FullyQualifiedDomainName>www.example.com</FullyQualifiedDomainName></HealthCheckConfig></CreateHealthCheckRequest>"
    r = call("POST", "/healthcheck", hc)
    hid = one("Id", r.body.decode())
    _check("health check 201 with defaults", r.status == 201 and "<Port>443</Port>" in r.body.decode() and "<RequestInterval>30</RequestInterval>" in r.body.decode())
    _check("health check dup", code("POST", "/healthcheck", hc)[1] == "HealthCheckAlreadyExists")
    _check("health check get/list/count", hid in ok("GET", f"/healthcheck/{hid}") and hid in ok("GET", "/healthcheck") and "<HealthCheckCount>1" in ok("GET", "/healthcheckcount"))
    u = ok("POST", f"/healthcheck/{hid}", f"<UpdateHealthCheckRequest {NS}><FailureThreshold>5</FailureThreshold></UpdateHealthCheckRequest>")
    _check("update bumps version", "<FailureThreshold>5</FailureThreshold>" in u and "<HealthCheckVersion>2</HealthCheckVersion>" in u)
    _check("status observations", "HealthCheckObservation" in ok("GET", f"/healthcheck/{hid}/status"))
    ok("POST", f"/hostedzone/{zid}/rrset", change(zid, ("CREATE", "hc.example.com", "A", rr(60, "1.2.3.4") + f"<HealthCheckId>{hid}</HealthCheckId>")))
    _check("health check in use", code("DELETE", f"/healthcheck/{hid}")[1] == "HealthCheckInUse")
    ok("POST", f"/hostedzone/{zid}/rrset", change(zid, ("DELETE", "hc.example.com", "A", rr(60, "1.2.3.4"))))

    # ── tags ──
    ok("POST", f"/tags/hostedzone/{zid}", f"<ChangeTagsForResourceRequest {NS}><AddTags><Tag><Key>env</Key><Value>dev</Value></Tag></AddTags></ChangeTagsForResourceRequest>")
    _check("tags listed", "<Key>env</Key><Value>dev</Value>" in ok("GET", f"/tags/hostedzone/{zid}"))
    _check("tags for resources", "<ResourceId>" + zid in ok("POST", "/tags/hostedzone", f"<ListTagsForResourcesRequest {NS}><ResourceIds><ResourceId>{zid}</ResourceId></ResourceIds></ListTagsForResourcesRequest>"))
    ok("POST", f"/tags/hostedzone/{zid}", f"<ChangeTagsForResourceRequest {NS}><RemoveTagKeys><Key>env</Key></RemoveTagKeys></ChangeTagsForResourceRequest>")
    _check("tag removed", "<Key>env</Key>" not in ok("GET", f"/tags/hostedzone/{zid}"))

    # ── delegation sets / query logging / misc ──
    d = ok("POST", "/delegationset", f"<CreateReusableDelegationSetRequest {NS}><CallerReference>d1</CallerReference></CreateReusableDelegationSetRequest>")
    did = one("Id", d).split("/")[-1]
    _check("delegation set", did in ok("GET", f"/delegationset/{did}") and did in ok("GET", "/delegationset"))
    z2 = ok("POST", "/hostedzone", create.replace("ref-1", "ref-2").replace("Example.com", "other.org").replace("</CallerReference>", f"</CallerReference><DelegationSetId>{did}</DelegationSetId>"))
    z2id = one("Id", z2).split("/")[-1]
    _check("zone uses the delegation set name servers", all(n in z2 for n in re.findall(r"<NameServer>(.*?)</NameServer>", d)))
    _check("delegation set in use", code("DELETE", f"/delegationset/{did}")[1] == "DelegationSetInUse")
    ql = ok("POST", "/queryloggingconfig", f"<CreateQueryLoggingConfigRequest {NS}><HostedZoneId>{z2id}</HostedZoneId><CloudWatchLogsLogGroupArn>arn:aws:logs:us-east-1:123456789012:log-group:/r53</CloudWatchLogsLogGroupArn></CreateQueryLoggingConfigRequest>")
    qid = one("Id", ql)
    _check("query logging config", qid in ok("GET", f"/queryloggingconfig/{qid}") and qid in ok("GET", "/queryloggingconfig"))
    _check("query logging dup", code("POST", "/queryloggingconfig", f"<CreateQueryLoggingConfigRequest {NS}><HostedZoneId>{z2id}</HostedZoneId><CloudWatchLogsLogGroupArn>a</CloudWatchLogsLogGroupArn></CreateQueryLoggingConfigRequest>")[1] == "QueryLoggingConfigAlreadyExists")
    ok("DELETE", f"/queryloggingconfig/{qid}")
    _check("dnssec", "NOT_SIGNING" in ok("GET", f"/hostedzone/{zid}/dnssec"))
    _check("limits", "<Value>500</Value>" in ok("GET", "/accountlimit/MAX_HOSTED_ZONES_BY_OWNER") and "<Value>10000</Value>" in ok("GET", f"/hostedzonelimit/{zid}/MAX_RRSETS_BY_ZONE"))
    _check("checker ip ranges", "CheckerIpRange" in ok("GET", "/checkeripranges"))
    priv = ok("POST", "/hostedzone", f"<CreateHostedZoneRequest {NS}><Name>corp.internal</Name><VPC><VPCRegion>us-east-1</VPCRegion><VPCId>vpc-1</VPCId></VPC><CallerReference>p1</CallerReference><HostedZoneConfig><PrivateZone>true</PrivateZone></HostedZoneConfig></CreateHostedZoneRequest>")
    pid = one("Id", priv).split("/")[-1]
    _check("by VPC", pid in ok("GET", "/hostedzonesbyvpc", vpcid="vpc-1", vpcregion="us-east-1"))
    _check("last VPC cannot be disassociated", code("POST", f"/hostedzone/{pid}/disassociatevpc", f"<DisassociateVPCFromHostedZoneRequest {NS}><VPC><VPCRegion>us-east-1</VPCRegion><VPCId>vpc-1</VPCId></VPC></DisassociateVPCFromHostedZoneRequest>")[1] == "LastVPCAssociation")
    ok("POST", f"/hostedzone/{pid}/associatevpc", f"<AssociateVPCWithHostedZoneRequest {NS}><VPC><VPCRegion>us-east-1</VPCRegion><VPCId>vpc-2</VPCId></VPC></AssociateVPCWithHostedZoneRequest>")
    ok("POST", f"/hostedzone/{pid}/disassociatevpc", f"<DisassociateVPCFromHostedZoneRequest {NS}><VPC><VPCRegion>us-east-1</VPCRegion><VPCId>vpc-1</VPCId></VPC></DisassociateVPCFromHostedZoneRequest>")
    _check("unknown route", code("GET", "/nothing")[1] == "InvalidAction")

    # ── console view ──
    c = r53.console_create(s, {"name": "console.dev"})
    _check("console create fills every column", all(str(c[k]) for k in ("name", "type", "created_by", "record_count", "comment", "zone_id")))
    r53.console_record_upsert(s, c["zone_id"], {"name": "app.console.dev", "type": "A", "ttl": 60, "values": "10.0.0.1"})
    got = r53.console_get(s, "console.dev.")
    _check("console records tab", any(x["name"] == "app.console.dev." and x["value"] == "10.0.0.1" for x in got["records"]))
    r53.console_child_create(s, "health-checks", {"target": "10.0.0.1", "type": "TCP", "port": 22})
    _check("console health checks", len(r53.console_children(s, "health-checks")["items"]) == 2)
    r53.console_delete(s, c["zone_id"])
    _check("console delete removes zone + records", all(x["zone_id"] != c["zone_id"] for x in r53.console_list(s)["items"]))
    return s


def test_route53_core():
    run()


if __name__ == "__main__":
    run()
    print("route53 core: all checks passed")
