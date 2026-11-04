"""VPC Lattice data-plane evaluator (POST /vyomi/invoke + derived target health) via AwsWireRouter.
Run: PYTHONPATH=. python3 tests/conformance/test_vpc_lattice_dataplane.py
"""
import json
import re
from urllib.parse import quote

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"{name} {extra}")
    print(f"  ok  {name}")


def main():
    r = AwsWireRouter()

    def L(method, path, body=None):
        out = r.handle(method, path, {}, {"authorization": _auth("vpc-lattice"), "content-type": "application/json"},
                       json.dumps(body).encode() if body is not None else b"")
        return out["status"], (json.loads(out["body"]) if out["body"] else {})

    def ec2(action, **p):
        form = "&".join(f"{k}={quote(str(v))}" for k, v in {"Action": action, **p}.items())
        return r.handle("POST", "/", {}, {"authorization": _auth("ec2"), "content-type": "application/x-www-form-urlencoded"}, form.encode())["body"].decode()

    def mk(cidr):
        vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", ec2("CreateVpc", CidrBlock=cidr)).group(1)
        sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", ec2("CreateSubnet", VpcId=vpc, CidrBlock=cidr.replace("0.0/16", "1.0/24"), AvailabilityZone="us-east-1a")).group(1)
        return vpc, sub
    vpc, sub = mk("10.21.0.0/16")
    cvpc, csub = mk("10.22.0.0/16")
    sg_open = re.search(r"<groupId>(sg-\w+)</groupId>", ec2("CreateSecurityGroup", GroupName="open", GroupDescription="d", VpcId=vpc)).group(1)
    sg_shut = re.search(r"<groupId>(sg-\w+)</groupId>", ec2("CreateSecurityGroup", GroupName="shut", GroupDescription="d", VpcId=vpc)).group(1)
    ec2("AuthorizeSecurityGroupIngress", GroupId=sg_open, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": 8080,
        "IpPermissions.1.ToPort": 8080, "IpPermissions.1.IpRanges.1.CidrIp": "169.254.171.0/24"})
    def run(sg, s):
        return re.search(r"<instanceId>(i-\w+)</instanceId>", ec2("RunInstances", InstanceType="t3.micro", MinCount=1, MaxCount=1, SubnetId=s, **{"SecurityGroupId.1": sg})).group(1)
    sg_c = re.search(r"<groupId>(sg-\w+)</groupId>", ec2("CreateSecurityGroup", GroupName="cli", GroupDescription="d", VpcId=cvpc)).group(1)
    i_ok, i_shut, i_client = run(sg_open, sub), run(sg_shut, sub), run(sg_c, csub)

    _, tg = L("POST", "/targetgroups", {"name": "tg-web", "type": "INSTANCE", "config": {"port": 8080, "protocol": "HTTP", "vpcIdentifier": vpc}})
    _, tg2 = L("POST", "/targetgroups", {"name": "tg-api", "type": "INSTANCE", "config": {"port": 8080, "protocol": "HTTP", "vpcIdentifier": vpc}})
    L("POST", f"/targetgroups/{tg['id']}/registertargets", {"targets": [{"id": i_ok}, {"id": i_shut}]})
    L("POST", f"/targetgroups/{tg2['id']}/registertargets", {"targets": [{"id": i_shut}]})
    _, svc = L("POST", "/services", {"name": "orders", "authType": "NONE"})
    _, lis = L("POST", f"/services/{svc['id']}/listeners", {"name": "http", "protocol": "HTTP", "port": 80,
               "defaultAction": {"forward": {"targetGroups": [{"targetGroupIdentifier": tg["id"], "weight": 1}]}}})
    L("POST", f"/services/{svc['id']}/listeners/{lis['id']}/rules", {"name": "api", "priority": 10,
      "match": {"httpMatch": {"pathMatch": {"match": {"prefix": "/api"}}}}, "action": {"forward": {"targetGroups": [{"targetGroupIdentifier": tg2["id"], "weight": 1}]}}})
    L("POST", f"/services/{svc['id']}/listeners/{lis['id']}/rules", {"name": "teapot", "priority": 5,
      "match": {"httpMatch": {"method": "POST", "headerMatches": [{"name": "x-mode", "match": {"exact": "tea"}}]}}, "action": {"fixedResponse": {"statusCode": 418}}})
    _, sn = L("POST", "/servicenetworks", {"name": "net1"})

    inv = lambda **b: L("POST", "/vyomi/invoke", {"host": svc["dnsEntry"]["domainName"], "sourceInstanceId": i_client, "seed": 1, **b})[1]

    # target health is derived: SG that admits 169.254.171.0/24 on 8080 -> HEALTHY, other -> UNHEALTHY, unused before wiring is moot (in use via listener)
    h = {t["id"]: t for t in L("POST", f"/targetgroups/{tg['id']}/listtargets", {})[1]["items"]}
    _check("open-SG instance HEALTHY", h[i_ok]["status"] == "HEALTHY", h[i_ok])
    _check("closed-SG instance UNHEALTHY Target.Timeout", h[i_shut]["status"] == "UNHEALTHY" and h[i_shut]["reasonCode"] == "Target.Timeout", h[i_shut])

    # DNS is per-VPC: not resolvable until the caller VPC is associated with a network that contains the service
    o = inv()
    _check("no VPC association -> NXDOMAIN", o["dnsResult"] == "NXDOMAIN" and not o["resolved"], o)
    L("POST", "/servicenetworkvpcassociations", {"serviceNetworkIdentifier": sn["id"], "vpcIdentifier": cvpc})
    o = inv()
    _check("service not in the network -> NXDOMAIN", o["dnsResult"] == "NXDOMAIN", o)
    L("POST", "/servicenetworkserviceassociations", {"serviceNetworkIdentifier": sn["id"], "serviceIdentifier": svc["id"]})
    o = inv()
    _check("resolves + default rule forwards to the HEALTHY target only", o["outcome"] == "FORWARDED" and o["target"]["id"] == i_ok and o["matchedRule"]["isDefault"], o)
    o = inv(path="/api/x")
    _check("prefix rule routes to tg-api whose only target is unhealthy -> 503", o["statusCode"] == 503 and o["matchedRule"]["priority"] == 10, o)
    o = inv(method="POST", path="/api/x", headers={"X-Mode": "tea"})
    _check("priority 5 (method+header) wins over priority 10 -> fixed 418", o["statusCode"] == 418 and o["matchedRule"]["priority"] == 5, o)
    o = inv(method="GET", headers={"X-Mode": "tea"}, path="/")
    _check("method mismatch falls to default", o["matchedRule"]["isDefault"], o)
    o = inv(port=9999)
    _check("no listener on port -> connection refused", o["connection"] == "REFUSED", o)
    # association SGs gate the caller
    _, shut2 = L("POST", "/servicenetworkvpcassociations", {"serviceNetworkIdentifier": sn["id"], "vpcIdentifier": vpc})
    # stopping the healthy instance makes the target UNAVAILABLE -> 503
    ec2("StopInstances", **{"InstanceId.1": i_ok})
    h = {t["id"]: t for t in L("POST", f"/targetgroups/{tg['id']}/listtargets", {})[1]["items"]}
    _check("stopped instance UNAVAILABLE", h[i_ok]["status"] == "UNAVAILABLE", h[i_ok])
    _check("all targets down -> 503", inv()["statusCode"] == 503)
    ec2("StartInstances", **{"InstanceId.1": i_ok})
    _check("restart -> forwarded again", inv()["outcome"] == "FORWARDED")

    # AWS_IAM: no principal -> 403; no policy -> implicit deny; allow/deny statements; deny wins
    L("PATCH", f"/services/{svc['id']}", {"authType": "AWS_IAM"})
    _check("AWS_IAM unsigned -> 403", inv()["statusCode"] == 403)
    o = inv(principal="arn:aws:iam::123456789012:role/app")
    _check("AWS_IAM, no policy -> implicit deny", o["statusCode"] == 403 and o["authDecision"] == "implicit", o)
    pol = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": "*", "Action": "vpc-lattice-svcs:Invoke", "Resource": "*"},
        {"Effect": "Deny", "Principal": "*", "Action": "vpc-lattice-svcs:Invoke", "Resource": "*",
         "Condition": {"StringEquals": {"vpc-lattice-svcs:RequestMethod": "DELETE"}}}]}
    L("PUT", f"/authpolicy/{svc['id']}", {"policy": json.dumps(pol)})
    P = "arn:aws:iam::123456789012:role/app"
    _check("allow statement admits GET", inv(principal=P)["outcome"] == "FORWARDED")
    o = inv(principal=P, method="DELETE")
    _check("conditional Deny wins for DELETE", o["statusCode"] == 403 and o["authDecision"] == "deny", o)
    print("vpc lattice dataplane: all checks passed")


if __name__ == "__main__":
    main()
