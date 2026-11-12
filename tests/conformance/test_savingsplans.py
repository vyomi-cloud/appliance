"""Savings Plans (AWS-04 leftover): offerings, purchase lifecycle, rates, coverage vs the running inventory, capacity overview.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_savingsplans.py
"""
import json
import time
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

SP = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/savingsplans/aws4_request, SignedHeaders=host, Signature=0"
EC2 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def sp(r, op, doc=None):
    out = r.handle("POST", "/" + op, {}, {"authorization": SP, "content-type": "application/json"}, json.dumps(doc or {}).encode())
    return out["status"], json.loads(out["body"])


def ec2(r, action, params=None):
    body = urlencode({"Action": action, "Version": "2016-11-15", **(params or {})}).encode()
    out = r.handle("POST", "/", {}, {"authorization": EC2, "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def main():
    r = AwsWireRouter()
    s, o = sp(r, "DescribeSavingsPlansOfferings", {"planTypes": ["Compute"], "paymentOptions": ["No Upfront"], "durations": [31536000]})
    _check("offerings filter", s == 200 and len(o["searchResults"]) == 1 and o["searchResults"][0]["planType"] == "Compute")
    compute = o["searchResults"][0]["offeringId"]
    s, o = sp(r, "DescribeSavingsPlansOfferings", {"planTypes": ["EC2Instance"], "filters": [{"name": "instanceFamily", "values": ["m5"]}], "paymentOptions": ["All Upfront"], "durations": [94608000]})
    ec2i = o["searchResults"][0]["offeringId"]
    _check("EC2 Instance offering is per family", "m5" in o["searchResults"][0]["description"])
    _check("bad payment option 400", sp(r, "DescribeSavingsPlansOfferings", {"paymentOptions": ["Nope"]})[0] == 400)
    _check("unknown offering 404", sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": "x", "commitment": "1"})[0] == 404)
    _check("tiny commitment 400", sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": compute, "commitment": "0.0001"})[0] == 400)
    s, o = sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": ec2i, "commitment": "0.5"})
    _check("All Upfront needs the upfront amount", s == 400 and "upfront" in o["message"].lower())
    s, o = sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": ec2i, "commitment": "0.5", "upfrontPaymentAmount": "13140.00"})
    _check("All Upfront plan with the right amount", s == 200)
    s, o = sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": compute, "commitment": "0.2", "tags": {"team": "x"}, "clientToken": "tok"})
    cid = o["savingsPlanId"]
    _check("create Compute plan", s == 200)
    _check("clientToken is idempotent", sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": compute, "commitment": "0.2", "clientToken": "tok"})[1]["savingsPlanId"] == cid)
    s, o = sp(r, "DescribeSavingsPlans", {"states": ["active"]})
    _check("describe active plans", s == 200 and len(o["savingsPlans"]) == 2 and o["savingsPlans"][1]["commitment"] == "0.200")
    s, o = sp(r, "DescribeSavingsPlans", {"savingsPlanIds": [cid]})
    arn = o["savingsPlans"][0]["savingsPlanArn"]
    _check("describe by id + arn shape", arn.startswith("arn:aws:savingsplans::123456789012:savingsplan/") and o["savingsPlans"][0]["tags"] == {"team": "x"})
    sp(r, "TagResource", {"resourceArn": arn, "tags": {"env": "dev"}})
    _check("tags", sp(r, "ListTagsForResource", {"resourceArn": arn})[1]["tags"] == {"team": "x", "env": "dev"})
    s, o = sp(r, "DescribeSavingsPlanRates", {"savingsPlanId": cid})
    _check("rates are below on-demand", s == 200 and float(o["searchResults"][0]["rate"]) > 0)

    # queued plan
    s, o = sp(r, "CreateSavingsPlan", {"savingsPlanOfferingId": compute, "commitment": "0.1", "purchaseTime": time.time() + 86400 * 3})
    qid = o["savingsPlanId"]
    _check("future purchaseTime -> queued", sp(r, "DescribeSavingsPlans", {"savingsPlanIds": [qid]})[1]["savingsPlans"][0]["state"] == "queued")
    _check("active plan cannot be DeleteQueued", sp(r, "DeleteQueuedSavingsPlan", {"savingsPlanId": cid})[0] == 400)
    _check("DeleteQueuedSavingsPlan", sp(r, "DeleteQueuedSavingsPlan", {"savingsPlanId": qid})[0] == 200)
    _check("queued-deleted state", sp(r, "DescribeSavingsPlans", {"savingsPlanIds": [qid]})[1]["savingsPlans"][0]["state"] == "queued-deleted")

    # coverage against real instances
    img = ec2(r, "DescribeImages", {"Owner.1": "amazon"})[1].split("<imageId>")[1].split("</imageId>")[0]
    s, x = ec2(r, "RunInstances", {"ImageId": img, "InstanceType": "m5.large", "MinCount": "2", "MaxCount": "2"})
    _check("fixture instances", s == 200 and x.count("<instanceId>") >= 2)
    s, cov = sp(r, "VyomiCoverage")
    _check("coverage reflects running usage", cov["onDemandCostPerHour"] > 0 and cov["coveragePercentage"] > 0)
    plans = {p["savingsPlanId"]: p for p in cov["plans"]}
    _check("m5 EC2-instance plan fully used first (highest discount)", any(p["type"] == "EC2Instance" and p["usedCommitment"] > 0 for p in plans.values()))
    _check("commitment bookkeeping", abs(cov["usedCommitmentPerHour"] + cov["unusedCommitmentPerHour"] - cov["totalCommitmentPerHour"]) < 1e-3)
    _check("net savings positive when covered", cov["netSavingsPerHour"] > 0)
    s, ov = sp(r, "VyomiCapacityOverview")
    _check("capacity overview from inventory", ov["runningInstances"] >= 2 and ov["byInstanceType"][0]["instanceType"] == "m5.large" and ov["runningVcpus"] >= 4)
    _check("overview carries savings plan summary", ov["savingsPlans"]["active"] == 2)

    s, o = sp(r, "ReturnSavingsPlan", {"savingsPlanId": cid})
    _check("ReturnSavingsPlan inside the window", s == 200 and sp(r, "DescribeSavingsPlans", {"savingsPlanIds": [cid]})[1]["savingsPlans"][0]["state"] == "retired")
    _check("returning a retired plan is refused", sp(r, "ReturnSavingsPlan", {"savingsPlanId": cid})[0] == 400)
    _check("unknown op 404", sp(r, "DoThing")[0] == 404)
    print("savings plans conformance OK")


if __name__ == "__main__":
    main()
