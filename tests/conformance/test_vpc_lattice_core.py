"""AWS-12 VPC Lattice control plane via AwsWireRouter (signing name `vpc-lattice`), cross-checked against the EC2 model.
Run: PYTHONPATH=. python3 tests/conformance/test_vpc_lattice_core.py
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

    def L(method, path, body=None, query=None):
        out = r.handle(method, path, query or {}, {"authorization": _auth("vpc-lattice"), "content-type": "application/json"},
                       json.dumps(body).encode() if body is not None else b"")
        j = json.loads(out["body"]) if out["body"] else {}
        return out["status"], j, out["headers"].get("x-amzn-errortype")

    def ec2(action, **p):
        form = "&".join(f"{k}={quote(str(v))}" for k, v in {"Action": action, **p}.items())
        out = r.handle("POST", "/", {}, {"authorization": _auth("ec2"), "content-type": "application/x-www-form-urlencoded"}, form.encode())
        return out["body"].decode()

    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", ec2("CreateVpc", CidrBlock="10.7.0.0/16")).group(1)
    vpc2 = re.search(r"<vpcId>(vpc-\w+)</vpcId>", ec2("CreateVpc", CidrBlock="10.8.0.0/16")).group(1)
    sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.7.1.0/24", AvailabilityZone="us-east-1a")).group(1)
    sg = re.search(r"<groupId>(sg-\w+)</groupId>", ec2("CreateSecurityGroup", GroupName="lat", GroupDescription="d", VpcId=vpc)).group(1)

    # service networks
    st, o, e = L("POST", "/servicenetworks", {"name": "Bad_Name"})
    _check("invalid name rejected", st == 400 and e == "ValidationException")
    st, sn, e = L("POST", "/servicenetworks", {"name": "shop-net", "authType": "AWS_IAM", "tags": {"env": "dev"}})
    _check("CreateServiceNetwork", st == 201 and sn["id"].startswith("sn-") and sn["arn"].endswith("servicenetwork/" + sn["id"]) and sn["authType"] == "AWS_IAM")
    st, o, e = L("POST", "/servicenetworks", {"name": "shop-net"})
    _check("duplicate name -> ConflictException", st == 409 and e == "ConflictException")
    st, o, _ = L("GET", f"/servicenetworks/{sn['id']}")
    _check("GetServiceNetwork counts", st == 200 and o["numberOfAssociatedVPCs"] == 0)
    st, o, _ = L("GET", f"/tags/{sn['arn']}")
    _check("tags from create", o["tags"] == {"env": "dev"})
    st, o, _ = L("POST", f"/tags/{sn['arn']}", {"tags": {"a": "1"}})
    st, o, _ = L("DELETE", f"/tags/{sn['arn']}", query={"tagKeys": ["env"]})
    st, o, _ = L("GET", f"/tags/{sn['arn']}")
    _check("TagResource / UntagResource", o["tags"] == {"a": "1"})

    # VPC association
    st, o, e = L("POST", "/servicenetworkvpcassociations", {"serviceNetworkIdentifier": sn["id"], "vpcIdentifier": "vpc-nope"})
    _check("association to a missing VPC rejected", st == 400)
    st, o, e = L("POST", "/servicenetworkvpcassociations", {"serviceNetworkIdentifier": sn["id"], "vpcIdentifier": vpc, "securityGroupIds": ["sg-nope"]})
    _check("unknown security group rejected", st == 400)
    st, snva, e = L("POST", "/servicenetworkvpcassociations", {"serviceNetworkIdentifier": sn["id"], "vpcIdentifier": vpc, "securityGroupIds": [sg]})
    _check("CreateServiceNetworkVpcAssociation", st == 202 and snva["id"].startswith("snva-") and snva["status"] == "ACTIVE")
    st, sn2, _ = L("POST", "/servicenetworks", {"name": "other-net"})
    st, o, e = L("POST", "/servicenetworkvpcassociations", {"serviceNetworkIdentifier": sn2["id"], "vpcIdentifier": vpc})
    _check("a VPC can belong to only one service network", st == 409)
    st, o, _ = L("GET", "/servicenetworkvpcassociations", query={"serviceNetworkIdentifier": sn["id"]})
    _check("ListServiceNetworkVpcAssociations", len(o["items"]) == 1 and o["items"][0]["vpcId"] == vpc)
    st, o, e = L("DELETE", f"/servicenetworks/{sn['id']}")
    _check("service network with associations cannot be deleted", st == 409)

    # target groups
    st, o, e = L("POST", "/targetgroups", {"name": "tg-web", "type": "IP", "config": {"port": 80, "protocol": "HTTP", "vpcIdentifier": "vpc-nope"}})
    _check("target group needs an existing VPC", st == 400)
    st, tg, e = L("POST", "/targetgroups", {"name": "tg-web", "type": "IP", "config": {"port": 80, "protocol": "HTTP", "vpcIdentifier": vpc}})
    _check("CreateTargetGroup (IP)", st == 201 and tg["id"].startswith("tg-") and tg["config"]["healthCheck"]["path"] == "/")
    st, o, _ = L("POST", f"/targetgroups/{tg['id']}/registertargets", {"targets": [{"id": "10.7.1.5"}, {"id": "8.8.8.8"}, {"id": "nope"}]})
    _check("RegisterTargets validates IPs (public/invalid fail)", len(o["successful"]) == 1 and len(o["unsuccessful"]) == 2 and o["successful"][0]["port"] == 80)
    st, o, _ = L("POST", f"/targetgroups/{tg['id']}/listtargets", {})
    _check("ListTargets (unused until attached)", o["items"][0]["status"] == "UNUSED")
    st, tgl, e = L("POST", "/targetgroups", {"name": "tg-fn", "type": "LAMBDA"})
    arn1 = "arn:aws:lambda:us-east-1:123456789012:function:one"
    st, o, _ = L("POST", f"/targetgroups/{tgl['id']}/registertargets", {"targets": [{"id": arn1}, {"id": arn1 + "2"}]})
    _check("Lambda target group: single Lambda ARN target", len(o["successful"]) == 1 and len(o["unsuccessful"]) == 1)

    # services, listeners, rules
    st, svc, e = L("POST", "/services", {"name": "orders", "authType": "AWS_IAM"})
    _check("CreateService with DNS entry", st == 201 and svc["id"].startswith("svc-") and "vpc-lattice-svcs.us-east-1.on.aws" in svc["dnsEntry"]["domainName"])
    st, o, e = L("POST", f"/services/{svc['id']}/listeners", {"name": "http80", "protocol": "HTTP", "port": 80,
                                                              "defaultAction": {"forward": {"targetGroups": [{"targetGroupIdentifier": "tg-nope"}]}}})
    _check("listener action must reference an existing target group", st == 404)
    st, lis, e = L("POST", f"/services/{svc['id']}/listeners", {"name": "http80", "protocol": "HTTP", "port": 80,
                                                                "defaultAction": {"forward": {"targetGroups": [{"targetGroupIdentifier": tg["id"], "weight": 100}]}}})
    _check("CreateListener", st == 201 and lis["id"].startswith("listener-"))
    st, o, e = L("POST", f"/services/{svc['id']}/listeners", {"name": "another", "protocol": "HTTP", "port": 80, "defaultAction": {"fixedResponse": {"statusCode": 404}}})
    _check("duplicate listener port -> Conflict", st == 409)
    st, o, e = L("DELETE", f"/targetgroups/{tg['id']}")
    _check("target group in use cannot be deleted", st == 409)
    st, o, _ = L("POST", f"/targetgroups/{tg['id']}/listtargets", {})
    _check("targets leave UNUSED once the group is attached (health is derived, see test_vpc_lattice_dataplane)", o["items"][0]["status"] != "UNUSED")
    st, o, _ = L("GET", f"/services/{svc['id']}/listeners/{lis['id']}/rules")
    default = o["items"][0]
    _check("default rule is created with the listener", default["isDefault"] is True)
    st, o, e = L("DELETE", f"/services/{svc['id']}/listeners/{lis['id']}/rules/{default['id']}")
    _check("default rule cannot be deleted", st == 400)
    rule_body = {"name": "api-rule", "priority": 10, "match": {"httpMatch": {"pathMatch": {"match": {"prefix": "/api"}, "caseSensitive": False}}},
                 "action": {"fixedResponse": {"statusCode": 200}}}
    st, rule, e = L("POST", f"/services/{svc['id']}/listeners/{lis['id']}/rules", rule_body)
    _check("CreateRule", st == 201 and rule["priority"] == 10)
    st, o, e = L("POST", f"/services/{svc['id']}/listeners/{lis['id']}/rules", {**rule_body, "name": "second"})
    _check("duplicate priority -> Conflict", st == 409)
    st, o, e = L("POST", f"/services/{svc['id']}/listeners/{lis['id']}/rules", {**rule_body, "name": "third", "priority": 11, "match": {"httpMatch": {"pathMatch": {"match": {"prefix": "api"}}}}})
    _check("path match must start with /", st == 400)
    st, o, _ = L("PATCH", f"/services/{svc['id']}/listeners/{lis['id']}/rules", {"rules": [{"ruleIdentifier": rule["id"], "priority": 20}]})
    _check("BatchUpdateRule", len(o["successful"]) == 1 and o["successful"][0]["priority"] == 20)

    # service association + auth/resource policy
    st, snsa, e = L("POST", "/servicenetworkserviceassociations", {"serviceNetworkIdentifier": sn["id"], "serviceIdentifier": svc["id"]})
    _check("CreateServiceNetworkServiceAssociation", st == 202 and snsa["id"].startswith("snsa-"))
    st, o, e = L("DELETE", f"/services/{svc['id']}")
    _check("associated service cannot be deleted", st == 409)
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "vpc-lattice-svcs:Invoke", "Resource": "*"}]})
    st, o, _ = L("PUT", f"/authpolicy/{svc['id']}", {"policy": pol})
    _check("PutAuthPolicy (AWS_IAM service)", st == 200 and o["state"] == "Active")
    st, o, _ = L("PUT", f"/authpolicy/{sn2['id']}", {"policy": pol})
    _check("auth policy needs authType AWS_IAM", st == 400)
    st, o, _ = L("GET", f"/authpolicy/{svc['id']}")
    _check("GetAuthPolicy", json.loads(o["policy"])["Statement"])
    st, o, _ = L("PUT", f"/resourcepolicy/{quote(svc['arn'], safe='')}", {"policy": pol})
    st, o, _ = L("GET", f"/resourcepolicy/{quote(svc['arn'], safe='')}")
    _check("Put/GetResourcePolicy", st == 200 and "policy" in o)

    # resource gateway + configuration
    st, o, e = L("POST", "/resourcegateways", {"name": "rgw-one", "vpcIdentifier": vpc, "subnetIds": ["subnet-nope"]})
    _check("resource gateway needs real subnets in the VPC", st == 400)
    st, rgw, e = L("POST", "/resourcegateways", {"name": "rgw-one", "vpcIdentifier": vpc, "subnetIds": [sub], "securityGroupIds": [sg]})
    _check("CreateResourceGateway", st == 201 and rgw["id"].startswith("rgw-"))
    st, o, e = L("POST", "/resourceconfigurations", {"name": "db-cfg", "type": "SINGLE", "portRanges": ["5432"], "resourceConfigurationDefinition": {"ipResource": {"ipAddress": "10.7.1.9"}}})
    _check("SINGLE configuration requires a gateway", st == 400)
    st, rc, e = L("POST", "/resourceconfigurations", {"name": "db-cfg", "type": "SINGLE", "resourceGatewayIdentifier": rgw["id"], "portRanges": ["5432"],
                                                      "resourceConfigurationDefinition": {"ipResource": {"ipAddress": "10.7.1.9"}}})
    _check("CreateResourceConfiguration", st == 201 and rc["id"].startswith("rcfg-") and rc["protocol"] == "TCP")
    st, o, e = L("DELETE", f"/resourcegateways/{rgw['id']}")
    _check("gateway used by a configuration cannot be deleted", st == 409)
    st, snra, e = L("POST", "/servicenetworkresourceassociations", {"serviceNetworkIdentifier": sn["id"], "resourceConfigurationIdentifier": rc["id"]})
    _check("CreateServiceNetworkResourceAssociation", st == 202 and snra["id"].startswith("snra-"))
    st, o, e = L("DELETE", f"/resourceconfigurations/{rc['id']}")
    _check("associated configuration cannot be deleted", st == 409)

    # domain verification
    st, dv, e = L("POST", "/domainverifications", {"domainName": "example.com"})
    _check("StartDomainVerification returns a TXT challenge, PENDING", st == 201 and dv["status"] == "PENDING" and dv["txtMethodConfig"]["name"].endswith("example.com"))
    st, o, e = L("POST", "/domainverifications", {"domainName": "example.com"})
    _check("duplicate domain -> Conflict", st == 409)

    # teardown order
    for coll, i in (("servicenetworkresourceassociations", snra["id"]), ("servicenetworkserviceassociations", snsa["id"]), ("servicenetworkvpcassociations", snva["id"])):
        st, o, _ = L("DELETE", f"/{coll}/{i}")
        _check(f"delete {coll[:-1]}", st == 202)
    for path in (f"/resourceconfigurations/{rc['id']}", f"/resourcegateways/{rgw['id']}", f"/services/{svc['id']}", f"/targetgroups/{tg['id']}",
                 f"/targetgroups/{tgl['id']}", f"/servicenetworks/{sn['id']}", f"/servicenetworks/{sn2['id']}", f"/domainverifications/{dv['id']}"):
        st, o, e = L("DELETE", path)
        _check(f"delete {path.split('/')[1]}", st in (202, 204), f"{st} {o}")
    st, o, _ = L("GET", "/servicenetworks")
    _check("everything is gone", o["items"] == [])
    print("PASS test_vpc_lattice_core")


if __name__ == "__main__":
    main()
