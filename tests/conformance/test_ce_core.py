"""AWS-11 Cost Explorer over the real EC2/EBS/RDS inventory + the Vyomi 'saved' dashboard feed. Via AwsWireRouter (signing name ce).
Run: PYTHONPATH=. python3 tests/conformance/test_ce_core.py
"""
import json
import urllib.parse
from datetime import date, timedelta

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def ce(r, op, body):
    out = r.handle("POST", "/", {}, {"authorization": _auth("ce"), "x-amz-target": "AWSInsightsIndexService." + op, "content-type": "application/x-amz-json-1.1"}, json.dumps(body).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def ec2(r, action, **p):
    body = urllib.parse.urlencode({"Action": action, "Version": "2016-11-15", **p}).encode()
    out = r.handle("POST", "/", {}, {"authorization": _auth("ec2"), "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def main():
    r = AwsWireRouter()
    from core import vpc_core
    ami = vpc_core._default_ami_id(vpc_core._model(r.vpc))
    today = date.today()
    TP = {"Start": today.replace(day=1).isoformat(), "End": (today + timedelta(days=1)).isoformat()}
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": TP, "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"]})
    _check("no resources -> zero cost", st == 200 and o["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"] == "0")
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": TP, "Granularity": "HOURLY", "Metrics": ["UnblendedCost"]})
    _check("HOURLY requires opt-in -> DataUnavailableException", st == 400 and o["__type"] == "DataUnavailableException")
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": {"Start": "2026-13-40", "End": "2026-14-01"}, "Granularity": "DAILY", "Metrics": ["UnblendedCost"]})
    _check("bad dates -> ValidationException", st == 400 and o["__type"] == "ValidationException")
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": TP, "Granularity": "DAILY", "Metrics": ["Nope"]})
    _check("bad metric rejected", st == 400)
    st, o = ce(r, "GetCostForecast", {"TimePeriod": {"Start": (today + timedelta(days=1)).isoformat(), "End": (today + timedelta(days=8)).isoformat()}, "Metric": "UNBLENDED_COST", "Granularity": "DAILY"})
    _check("forecast with no running resources -> DataUnavailableException", st == 400 and o["__type"] == "DataUnavailableException")

    st, x = ec2(r, "RunInstances", ImageId=ami, InstanceType="m5.large", MinCount="1", MaxCount="1")
    _check("an EC2 instance is running", st == 200 and "m5.large" in x)
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": TP, "Granularity": "DAILY", "Metrics": ["UnblendedCost", "UsageQuantity"], "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}]})
    _check("instance cost accrues by service (EC2 compute + EBS)", st == 200 and any(g["Keys"] == ["Amazon Elastic Compute Cloud - Compute"] for res in o["ResultsByTime"] for g in res["Groups"]))
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": TP, "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"],
                                      "Filter": {"Dimensions": {"Key": "INSTANCE_TYPE", "Values": ["m5.large"]}}})
    amt = float(o["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
    _check("filter by INSTANCE_TYPE returns the instance's accrued cost (>=0)", st == 200 and amt >= 0)
    st, o = ce(r, "GetCostAndUsage", {"TimePeriod": TP, "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"], "Filter": {"Dimensions": {"Key": "INSTANCE_TYPE", "Values": ["c5.xlarge"]}}})
    _check("a non-matching filter yields zero", o["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"] == "0")
    st, o = ce(r, "GetDimensionValues", {"TimePeriod": TP, "Dimension": "SERVICE"})
    _check("GetDimensionValues SERVICE lists EC2", any(v["Value"].startswith("Amazon Elastic Compute Cloud") for v in o["DimensionValues"]))
    st, o = ce(r, "GetDimensionValues", {"TimePeriod": TP, "Dimension": "INSTANCE_TYPE", "SearchString": "m5"})
    _check("GetDimensionValues INSTANCE_TYPE search", [v["Value"] for v in o["DimensionValues"]] == ["m5.large"])
    st, o = ce(r, "GetCostForecast", {"TimePeriod": {"Start": (today + timedelta(days=1)).isoformat(), "End": (today + timedelta(days=8)).isoformat()}, "Metric": "UNBLENDED_COST", "Granularity": "DAILY"})
    _check("forecast = run rate x 7 days", st == 200 and len(o["ForecastResultsByTime"]) == 7 and float(o["Total"]["Amount"]) > 0)
    st, o = ce(r, "VyomiGetSavings", {})
    _check("Saved-by-Vyomi feed: simulator cost is $0 and savings equal the AWS-equivalent bill",
           st == 200 and o["SimulatorCostUSD"] == 0.0 and o["ResourceCount"] >= 1 and o["MonthlyRunRateUSD"] > 0 and o["SavedMonthToDateUSD"] == o["RealCloudCostMonthToDateUSD"])
    st, o = ce(r, "Nope", {})
    _check("unknown operation", st == 400)
    print("PASS cost explorer")


if __name__ == "__main__":
    main()
