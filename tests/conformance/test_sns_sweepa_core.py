"""SNS sweep A: real AWS/SNS SMS delivery metrics (aggregate + per country) from actual publishes.

Run: PYTHONPATH=. python3 tests/conformance/test_sns_sweepa_core.py
"""
import json
import time
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter
from core import sns_core

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/%s/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def sns(r, **params):
    out = r.handle("POST", "/", {}, {"authorization": AUTH % "sns", "content-type": "application/x-www-form-urlencoded"}, urlencode(params).encode())
    return out["status"], (out.get("body") or b"").decode()


def stat(r, metric, dims, stat="Sum"):
    h = {"authorization": AUTH % "monitoring", "x-amz-target": "GraniteServiceVersion20100801.GetMetricStatistics", "content-type": "application/x-amz-json-1.0"}
    out = r.handle("POST", "/", {}, h, json.dumps({"Namespace": "AWS/SNS", "MetricName": metric, "Dimensions": dims,
                   "StartTime": time.time() - 3600, "EndTime": time.time() + 60, "Period": 3600, "Statistics": [stat]}).encode())
    return json.loads(out["body"])["Datapoints"]


def run() -> int:
    r = AwsWireRouter()
    _check("country lookup", sns_core.sms_country("+14155550100") == "US" and sns_core.sms_country("+447700900123") == "GB"
           and sns_core.sms_country("+919876543210") == "IN" and sns_core.sms_country("+999123456789") == "ZZ")
    for phone in ("+14155550100", "+447700900123"):
        st, _ = sns(r, Action="CreateSMSSandboxPhoneNumber", PhoneNumber=phone)
        otp = sns_core._state(r.msg)["sandbox"][phone]["otp"]
        sns(r, Action="VerifySMSSandboxPhoneNumber", PhoneNumber=phone, OneTimePassword=otp)
    for phone, n in (("+14155550100", 2), ("+447700900123", 1)):
        for _ in range(n):
            st, body = sns(r, Action="Publish", PhoneNumber=phone, Message="hello")
            _check(f"Publish to {phone}", st == 200)
    _check("aggregate NumberOfNotificationsDelivered counts every SMS", stat(r, "NumberOfNotificationsDelivered", [])[0]["Sum"] == 3)
    _check("per-country delivered (US=2)", stat(r, "NumberOfNotificationsDelivered", [{"Name": "Country", "Value": "US"}])[0]["Sum"] == 2)
    _check("per-country delivered (GB=1)", stat(r, "NumberOfNotificationsDelivered", [{"Name": "Country", "Value": "GB"}])[0]["Sum"] == 1)
    _check("SMSSuccessRate average is 1.0", stat(r, "SMSSuccessRate", [], "Average")[0]["Average"] == 1.0)
    spent = stat(r, "SMSMonthToDateSpentUSD", [], "Maximum")[0]["Maximum"]
    _check("month-to-date spend tracks the simulated cost", abs(spent - 3 * sns_core.SMS_COST_USD) < 1e-4)
    print("\nRESULT: PASS - SNS sweep A")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
