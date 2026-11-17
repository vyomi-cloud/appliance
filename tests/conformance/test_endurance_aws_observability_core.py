"""vyomi-endurance AWS stage 7/8 (observability, lifecycle) regressions found by the Terraform estate. Host + Pyodide.

    PYTHONPATH=. python3 tests/conformance/test_endurance_aws_observability_core.py
"""
import json

from core import cloudwatch_core as cw
from core import ssm_core as ssm
from core import aws_governance_core as gov
from core.object_store import InMemoryObjectStore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


def run():
    # F200 composite alarm rules reference hyphenated alarm names unquoted
    s = cw.CloudWatchStore()
    for n in ("endurance-a", "endurance-b.c"):
        r = cw.dispatch(s, {"Action": "PutMetricAlarm", "AlarmName": n, "Namespace": "N", "MetricName": "M", "Period": "60",
                            "EvaluationPeriods": "2", "Threshold": "1", "ComparisonOperator": "GreaterThanThreshold", "Statistic": "Sum"})
        _check(f"PutMetricAlarm {n}", r.status == 200)
    r = cw.dispatch(s, {"Action": "PutCompositeAlarm", "AlarmName": "comp",
                        "AlarmRule": 'ALARM(endurance-a) OR ALARM("endurance-b.c") AND NOT OK(endurance-a)'})
    _check("F200 composite alarm rule with hyphenated/dotted names parses", r.status == 200)
    r = cw.dispatch(s, {"Action": "PutCompositeAlarm", "AlarmName": "bad", "AlarmRule": "ALARM(endurance-a) OR"})
    _check("F200 a truly malformed rule is still rejected", r.status == 400)
    # F202 DatapointsToAlarm omitted on read-back when unset
    d = cw.dispatch(s, {"Action": "DescribeAlarms", "AlarmNames.member.1": "endurance-a"}).body
    _check("F202 unset DatapointsToAlarm is not invented on DescribeAlarms", b"DatapointsToAlarm" not in (d if isinstance(d, bytes) else str(d).encode()))
    cw.dispatch(s, {"Action": "PutMetricAlarm", "AlarmName": "dp", "Namespace": "N", "MetricName": "M", "Period": "60", "EvaluationPeriods": "3",
                    "DatapointsToAlarm": "2", "Threshold": "1", "ComparisonOperator": "GreaterThanThreshold", "Statistic": "Sum"})
    d = cw.dispatch(s, {"Action": "DescribeAlarms", "AlarmNames.member.1": "dp"}).body
    _check("F202 a set DatapointsToAlarm is still returned", b"DatapointsToAlarm" in (d if isinstance(d, bytes) else str(d).encode()))

    # F203 maintenance window ScheduleTimezone only when set
    st = ssm.SsmStore()
    w = ssm.dispatch(st, "AmazonSSM.CreateMaintenanceWindow", {"Name": "win-one", "Schedule": "cron(0 2 ? * SUN *)", "Duration": 3, "Cutoff": 1,
                                                                "AllowUnassociatedTargets": False}).body["WindowId"]
    g = ssm.dispatch(st, "AmazonSSM.GetMaintenanceWindow", {"WindowId": w}).body
    _check("F203 no ScheduleTimezone when none was set", "ScheduleTimezone" not in g)
    w2 = ssm.dispatch(st, "AmazonSSM.CreateMaintenanceWindow", {"Name": "win-two", "Schedule": "cron(0 2 ? * SUN *)", "Duration": 3, "Cutoff": 1,
                                                                 "AllowUnassociatedTargets": False, "ScheduleTimezone": "Asia/Kolkata"}).body["WindowId"]
    _check("F203 ScheduleTimezone returned when set",
           ssm.dispatch(st, "AmazonSSM.GetMaintenanceWindow", {"WindowId": w2}).body["ScheduleTimezone"] == "Asia/Kolkata")

    # F204 AWS Budgets control plane (json-1.1: epoch number times)
    o = InMemoryObjectStore()
    T = "AWSBudgetServiceGateway."
    def b(op, **p):
        r = gov.budgets_handle(o, T + op, json.dumps(p).encode())
        return r["status"], (json.loads(r["body"]) if r["body"] else {})
    bud = {"BudgetName": "m", "BudgetType": "COST", "TimeUnit": "MONTHLY", "BudgetLimit": {"Amount": "500", "Unit": "USD"}}
    note = {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 80, "ThresholdType": "PERCENTAGE"}
    _check("F204 CreateBudget", b("CreateBudget", AccountId="123456789012", Budget=bud,
                                  NotificationsWithSubscribers=[{"Notification": note, "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "a@b.c"}]}])[0] == 200)
    _check("F204 duplicate budget rejected", b("CreateBudget", AccountId="123456789012", Budget=bud)[1]["__type"] == "DuplicateRecordException")
    got = b("DescribeBudget", AccountId="123456789012", BudgetName="m")[1]["Budget"]
    _check("F204 DescribeBudget returns epoch-number TimePeriod + default CostTypes",
           isinstance(got["TimePeriod"]["Start"], int) and got["CostTypes"]["IncludeTax"] is True and got["BudgetLimit"]["Amount"] == "500")
    _check("F204 notifications + subscribers readable",
           b("DescribeNotificationsForBudget", AccountId="123456789012", BudgetName="m")[1]["Notifications"][0]["Threshold"] == 80
           and b("DescribeSubscribersForNotification", AccountId="123456789012", BudgetName="m", Notification=note)[1]["Subscribers"][0]["Address"] == "a@b.c")
    _check("F204 DeleteBudget then NotFound", b("DeleteBudget", AccountId="123456789012", BudgetName="m")[0] == 200
           and b("DescribeBudget", AccountId="123456789012", BudgetName="m")[1]["__type"] == "NotFoundException")

    # F205 Resource Groups
    def rg(method, path, **p):
        r = gov.rg_handle(o, method, path, json.dumps(p).encode() if p else b"")
        return r["status"], (json.loads(r["body"]) if r["body"] else {})
    q = {"Type": "TAG_FILTERS_1_0", "Query": "{}"}
    c = rg("POST", "/groups", Name="est", ResourceQuery=q, Tags={"a": "b"})
    _check("F205 CreateGroup returns Group + query + tags", c[0] == 200 and c[1]["Group"]["GroupArn"].endswith(":group/est") and c[1]["Tags"] == {"a": "b"})
    _check("F205 GetGroup / GetGroupQuery", rg("POST", "/get-group", Group="est")[1]["Group"]["Name"] == "est"
           and rg("POST", "/get-group-query", Group="est")[1]["GroupQuery"]["ResourceQuery"] == q)
    arn = c[1]["Group"]["GroupArn"]
    _check("F205 tags GET/PUT/PATCH", rg("PUT", f"/resources/{arn}/tags", Tags={"x": "y"})[0] == 200
           and rg("GET", f"/resources/{arn}/tags")[1]["Tags"] == {"a": "b", "x": "y"}
           and rg("PATCH", f"/resources/{arn}/tags", Keys=["x"])[0] == 200 and rg("GET", f"/resources/{arn}/tags")[1]["Tags"] == {"a": "b"})
    _check("F205 DeleteGroup then 404", rg("POST", "/delete-group", Group="est")[0] == 200 and rg("POST", "/get-group", Group="est")[0] == 404)
    print("Endurance aws-observability regressions: ALL GREEN")


if __name__ == "__main__":
    run()
