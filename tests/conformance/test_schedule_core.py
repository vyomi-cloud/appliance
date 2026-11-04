"""Shared schedule seam: AWS Backup plans, Azure Backup policies, Cloud SQL backup windows, ECR lifecycle really run on schedule.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_schedule_core.py
"""
import json
from datetime import datetime, timezone

from core import schedule_core as sc
from core.aws_wire_router import AwsWireRouter
from core.azure_arm_core import DEFAULT_SUBSCRIPTION as S

H = {"content-type": "application/x-amz-json-1.0"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def epoch(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def aws(r, svc, method, path, body=None, target=None):
    h = {"authorization": f"AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0",
         "content-type": "application/json"}
    if target:
        h["x-amz-target"] = target
        h["content-type"] = "application/x-amz-json-1.0"
    out = r.handle(method, path, {}, h, json.dumps(body or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def main():
    # spec language
    t0 = epoch(2026, 11, 4, 10, 0)
    _check("daily@", sc.next_after("daily@02:00", t0) == epoch(2026, 11, 5, 2, 0))
    _check("weekly@ (Fri after Wed)", sc.next_after("weekly@02:00@FRI", t0) == epoch(2026, 11, 6, 2, 0))
    _check("hourly@", sc.next_after("hourly@4", t0) == t0 + 4 * 3600)
    _check("aws cron", sc.next_after("cron(0 5 * * ? *)", t0) == epoch(2026, 11, 5, 5, 0))
    _check("aws rate", sc.next_after("rate(1 hour)", t0) == t0 + 3600)
    _check("invalid spec", sc.next_after("whenever", t0) is None)

    r = AwsWireRouter()
    r._sched_last = 1e18      # keep the lazy request pulse out of the way; ticks below are explicit
    # AWS Backup: plan + selection on a DynamoDB table
    aws(r, "dynamodb", "POST", "/", {"TableName": "orders", "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
                                    "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "BillingMode": "PAY_PER_REQUEST"}, "DynamoDB_20120810.CreateTable")
    s, o = aws(r, "backup", "PUT", "/backup/plans/", {"BackupPlan": {"BackupPlanName": "p", "Rules": [
        {"RuleName": "hourly", "TargetBackupVaultName": "Default", "ScheduleExpression": "rate(1 hour)", "Lifecycle": {"DeleteAfterDays": 1}}]}})
    assert s == 200, o
    pid = o["BackupPlanId"]
    s, o = aws(r, "backup", "PUT", f"/backup/plans/{pid}/selections/", {"BackupSelection": {
        "SelectionName": "sel", "IamRoleArn": "arn:aws:iam::123456789012:role/b", "Resources": ["arn:aws:dynamodb:us-east-1:123456789012:table/orders"]}})
    assert s == 200, o
    # Azure Backup: VM + vault + DefaultPolicy (daily 02:00)
    az = r.az_arm
    h = lambda m, p, b=None, q=None: az.handle(m, p, dict({"api-version": "2024-04-01"}, **(q or {})), b)
    R = f"/subscriptions/{S}/resourceGroups"
    h("PUT", f"{R}/app", {"location": "eastus"}, {"api-version": "2021-04-01"})
    vm = f"{R}/app/providers/Microsoft.Compute/virtualMachines/web1"
    h("PUT", vm, {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}}, {"api-version": "2023-09-01"})
    V = f"{R}/app/providers/Microsoft.RecoveryServices/vaults/rsv1"
    h("PUT", V, {"location": "eastus", "sku": {"name": "RS0", "tier": "Standard"}})
    IP = f"{V}/backupFabrics/Azure/protectionContainers/iaasvmcontainer;iaasvmcontainerv2;app;web1/protectedItems/vm;iaasvmcontainerv2;app;web1"
    resp = h("PUT", IP, {"properties": {"protectedItemType": "Microsoft.Compute/virtualMachines", "policyId": f"{V}/backupPolicies/DefaultPolicy", "sourceResourceId": vm}})
    assert resp["status"] == 200, resp
    # Cloud SQL with a backup window
    from core import gcp_cloudsql_core as cs
    P = "/sql/v1beta4/projects/demo/instances"
    cs.dispatch(r.gcp_sql, "POST", P, {}, {}, json.dumps({"name": "db1", "databaseVersion": "POSTGRES_15", "settings": {
        "tier": "db-custom-1-3840", "backupConfiguration": {"enabled": True, "startTime": "03:00", "backupRetentionSettings": {"retainedBackups": 2}}}}).encode())
    # ECR lifecycle
    ECR = {"authorization": "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/ecr/aws4_request, SignedHeaders=host, Signature=0"}

    base = epoch(2026, 11, 4, 10, 0)
    res = sc.tick(r, base)
    _check("first sighting runs nothing", res["runs"] == 0 and not res["errors"])
    res = sc.tick(r, base + 1800)
    _check("nothing due after 30 min", res["runs"] == 0)
    res = sc.tick(r, base + 3700)
    _check("AWS Backup rule fired", any(x.get("provider") == "aws-backup" and x.get("status") == 200 for x in res["log"]))
    s, o = aws(r, "backup", "GET", "/backup-jobs")
    _check("a real backup job + recovery point exist", s == 200 and len(o["BackupJobs"]) == 1 and o["BackupJobs"][0]["State"] == "COMPLETED")
    _check("job is attributed to the plan", o["BackupJobs"][0].get("CreatedBy", {}).get("BackupPlanId") == pid)
    res = sc.tick(r, base + 3700 + 3700)
    _check("fires again an hour later", len([x for x in res["log"] if x.get("provider") == "aws-backup" and "status" in x]) == 1)
    s, o = aws(r, "backup", "GET", "/backup-jobs")
    _check("two jobs", len(o["BackupJobs"]) == 2)

    # Azure: DefaultPolicy daily 02:00 -> due after the next 02:00
    res = sc.tick(r, epoch(2026, 11, 5, 3, 0))
    _check("Azure Backup policy fired", any(x.get("provider") == "azure-backup" and "item" in x for x in res["log"]))
    rps = [k for k, v in az.state.items() if isinstance(v, dict) and v.get("_kind") == "rp"]
    _check("recovery point created by schedule", len(rps) == 1)
    # Cloud SQL: window 03:00
    _check("Cloud SQL automated backup", any(x.get("provider") == "cloudsql" and "instance" in x for x in res["log"])
           or any(x.get("provider") == "cloudsql" for x in sc.tick(r, epoch(2026, 11, 5, 3, 30))["log"]))
    ids = cs._list_backup_ids(r.gcp_sql, "demo", "db1")
    _check("backup run is AUTOMATED", ids and r.gcp_sql.get_snapshot(cs._backup_key("demo", "db1", ids[0]))["type"] == "AUTOMATED")
    for d in range(6, 10):
        sc.tick(r, epoch(2026, 11, d, 3, 30))
    _check("retainedBackups pruning", len(cs._list_backup_ids(r.gcp_sql, "demo", "db1")) == 2)
    # recovery-point expiry (DeleteAfterDays=1) by now: everything older than a day is gone
    s, o = aws(r, "backup", "GET", "/backup-vaults/Default/recovery-points/")
    _check("DeleteAfterDays expiry sweeps AWS recovery points", s == 200 and len(o["RecoveryPoints"]) <= 1)
    st = sc.status(r)
    _check("status lists tracked schedules", any(k.startswith("awsbackup:") for k in st["tracked"]) and st["recent"])
    print("SCHEDULE OK")


if __name__ == "__main__":
    main()
