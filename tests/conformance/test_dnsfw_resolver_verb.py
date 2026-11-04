"""Route 53 Resolver DNS Firewall: ResolveDnsQuery simulator verb answers what the VPC resolver would do.
Run: PYTHONPATH=. python3 tests/conformance/test_dnsfw_resolver_verb.py
"""
import re
from urllib.parse import quote

from core import dnsfw_core as df
from core.aws_wire_router import AwsWireRouter


def main():
    r = AwsWireRouter()
    form = "&".join(f"{k}={quote(v)}" for k, v in {"Action": "CreateVpc", "CidrBlock": "10.79.0.0/16"}.items())
    out = r.handle("POST", "/", {}, {"authorization": "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0",
                                     "content-type": "application/x-www-form-urlencoded"}, form.encode())["body"].decode()
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", out).group(1)

    def f(action, body):
        o = r.handle("POST", "/", {}, {"authorization": "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/route53resolver/aws4_request, SignedHeaders=host, Signature=0",
                                       "content-type": "application/x-amz-json-1.1", "x-amz-target": "Route53Resolver." + action}, __import__("json").dumps(body).encode())
        assert o["status"] == 200, (action, o["body"])
        return __import__("json").loads(o["body"])

    q = lambda d, t="A": f("ResolveDnsQuery", {"VpcId": vpc, "DomainName": d, "QueryType": t})
    assert q("x.example.com")["Resolver"] == "RESOLVE" and q("x.example.com")["Action"] is None
    print("  ok  no association -> resolves normally")
    bad = f("CreateFirewallDomainList", {"Name": "bad"})["FirewallDomainList"]["Id"]
    f("UpdateFirewallDomains", {"FirewallDomainListId": bad, "Operation": "ADD", "Domains": ["evil.example.com", "*.cdn.evil.org", "sinkhole.me"]})
    g = f("CreateFirewallRuleGroup", {"Name": "grp"})["FirewallRuleGroup"]["Id"]
    f("CreateFirewallRule", {"FirewallRuleGroupId": g, "FirewallDomainListId": bad, "Priority": 10, "Action": "BLOCK", "BlockResponse": "NXDOMAIN", "Name": "nx"})
    f("AssociateFirewallRuleGroup", {"FirewallRuleGroupId": g, "VpcId": vpc, "Priority": 101, "Name": "assoc"})
    o = q("evil.example.com.")
    assert o["Action"] == "BLOCK" and o["Resolver"] == "NXDOMAIN" and o["Rule"] == "nx", o
    assert q("a.cdn.evil.org")["Resolver"] == "NXDOMAIN"
    assert q("fine.example.com")["Resolver"] == "RESOLVE"
    print("  ok  BLOCK/NXDOMAIN for exact and wildcard, unmatched resolves")
    ov = f("CreateFirewallDomainList", {"Name": "ov"})["FirewallDomainList"]["Id"]
    f("UpdateFirewallDomains", {"FirewallDomainListId": ov, "Operation": "ADD", "Domains": ["phish.test"]})
    f("CreateFirewallRule", {"FirewallRuleGroupId": g, "FirewallDomainListId": ov, "Priority": 20, "Action": "BLOCK", "BlockResponse": "OVERRIDE",
                             "BlockOverrideDomain": "walled.garden.test", "BlockOverrideDnsType": "CNAME", "Name": "ov"})
    o = q("phish.test")
    assert o["Resolver"] == "OVERRIDE" and o["OverrideDomain"] == "walled.garden.test", o
    print("  ok  OVERRIDE returns the CNAME")
    al = f("CreateFirewallDomainList", {"Name": "al"})["FirewallDomainList"]["Id"]
    f("UpdateFirewallDomains", {"FirewallDomainListId": al, "Operation": "ADD", "Domains": ["sinkhole.me"]})
    f("CreateFirewallRule", {"FirewallRuleGroupId": g, "FirewallDomainListId": al, "Priority": 5, "Action": "ALLOW", "Name": "allow"})
    assert q("sinkhole.me")["Action"] == "ALLOW" and q("sinkhole.me")["Resolver"] == "RESOLVE"
    print("  ok  lower-priority-number ALLOW beats BLOCK")
    print("dns firewall resolver verb: all checks passed")


if __name__ == "__main__":
    main()
