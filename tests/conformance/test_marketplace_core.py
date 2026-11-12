"""AWS Marketplace, Vyomi edition (AWS-02/AWS-06): SaaS spaces + AMI products + community AMIs via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_marketplace_core.py
"""
import json
import re

from core.aws_wire_router import AwsWireRouter

MP = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/aws-marketplace/aws4_request, SignedHeaders=host, Signature=0"
EC2 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


r = AwsWireRouter()


def mp(method, path, payload=None, query=None):
    o = r.handle(method, path, query or {}, {"authorization": MP, "content-type": "application/json"}, json.dumps(payload).encode() if payload is not None else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def ec2(action, **params):
    body = "&".join([f"Action={action}", "Version=2016-11-15"] + [f"{k}={v}" for k, v in params.items()])
    o = r.handle("POST", "/", {}, {"authorization": EC2, "content-type": "application/x-www-form-urlencoded"}, body.encode())
    return o["status"], o["body"].decode()


def main():
    s, o = mp("POST", "/ListEntities", {"Catalog": "AWSMarketplace", "EntityType": "SaaSProduct"})
    names = [e["Name"] for e in o["EntitySummaryList"]]
    _check("lists SaaS products", s == 200 and "Vyomi Payments Sandbox" in names and len(names) == 6)
    _check("bad catalog 400", mp("POST", "/ListEntities", {"Catalog": "Nope", "EntityType": "SaaSProduct"})[0] == 400)
    _check("bad entity type 400", mp("POST", "/ListEntities", {"Catalog": "AWSMarketplace", "EntityType": "X"})[0] == 400)
    s, o = mp("POST", "/ListEntities", {"Catalog": "AWSMarketplace", "EntityType": "SaaSProduct", "MaxResults": 2})
    _check("paginates", len(o["EntitySummaryList"]) == 2 and o["NextToken"] == "2")
    s, o = mp("POST", "/ListEntities", {"Catalog": "AWSMarketplace", "EntityType": "SaaSProduct", "FilterList": [{"Name": "Category", "ValueList": ["Messaging"]}]})
    _check("filter by category", len(o["EntitySummaryList"]) == 2)
    s, o = mp("GET", "/DescribeEntity", query={"catalog": "AWSMarketplace", "entityId": "vyomi-pay"})
    _check("describe entity", s == 200 and o["EntityType"] == "SaaSProduct" and o["Subscription"] is None)
    _check("describe missing 404", mp("GET", "/DescribeEntity", query={"catalog": "AWSMarketplace", "entityId": "nope"})[0] == 404)

    _check("subscribe needs EULA", mp("POST", "/agreements", {"productId": "vyomi-pay"})[0] == 400)
    _check("unknown product 404", mp("POST", "/agreements", {"productId": "zzz", "acceptEula": True})[0] == 404)
    s, a = mp("POST", "/agreements", {"productId": "vyomi-pay", "acceptEula": True})
    _check("subscribe SaaS -> space", s == 200 and a["Space"]["Endpoint"].startswith("https://vyomi-pay.") and a["Space"]["ApiKey"].startswith("vy_"))
    _check("duplicate subscribe 409", mp("POST", "/agreements", {"productId": "vyomi-pay", "acceptEula": True})[0] == 409)
    s, o = mp("POST", "/ListEntities", {"Catalog": "AWSMarketplace", "EntityType": "SaaSProduct", "FilterList": [{"Name": "Name", "ValueList": ["payments"]}]})
    _check("subscribed flag", o["EntitySummaryList"][0]["Subscribed"] is True)
    _check("agreements list", [x["AgreementId"] for x in mp("GET", "/agreements")[1]["Agreements"]] == [a["AgreementId"]])
    s, c = mp("DELETE", f"/agreements/{a['AgreementId']}")
    _check("unsubscribe", s == 200 and c["Status"] == "CANCELLED")
    _check("unsubscribe twice 404", mp("DELETE", f"/agreements/{a['AgreementId']}")[0] == 404)

    s, a = mp("POST", "/agreements", {"productId": "vyomi-ami-nginx", "acceptEula": True})
    ami = a["ImageId"]
    _check("subscribe AMI -> image", s == 200 and ami.startswith("ami-") and a["ProductCode"])
    st, xml = ec2("DescribeImages", **{"ImageId.1": ami})
    _check("AMI visible in DescribeImages", ami in xml and "aws-marketplace" in xml)
    s, o = mp("POST", "/ListEntities", {"Catalog": "AWSMarketplace", "EntityType": "CommunityAmi"})
    _check("community AMIs seeded", s == 200 and len(o["EntitySummaryList"]) == 6)
    st, xml = ec2("RunInstances", ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro")
    iid = re.search(r"<instanceId>(i-[0-9a-f]+)</instanceId>", xml)
    _check("launch from marketplace AMI", st == 200 and iid)
    s, o = mp("DELETE", f"/agreements/{a['AgreementId']}")
    _check("unsubscribe blocked while instance runs", s == 409)
    ec2("TerminateInstances", **{"InstanceId.1": iid.group(1)})
    _check("unsubscribe after terminate", mp("DELETE", f"/agreements/{a['AgreementId']}")[0] == 200
           and ami not in ec2("DescribeImages", **{"ImageId.1": ami})[1])
    print("Marketplace core: all green")


if __name__ == "__main__":
    main()
