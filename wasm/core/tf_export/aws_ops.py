# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Step Functions state machines, ECR repositories (+ lifecycle / repository policy), CloudWatch alarms, AWS Backup vaults / plans / selections."""
from __future__ import annotations

import json
import re

from core.tf_export import hcl
from core.tf_export.core import Ctx, attempt, exporter, paged, tags_of


def _json(text):
    try:
        return json.loads(text) or None
    except (TypeError, ValueError):
        return None


@exporter(44, "stepfunctions")
def export_sfn(ctx: Ctx) -> None:
    sfn = ctx.c["stepfunctions"]
    machines = []
    for page in sfn.get_paginator("list_state_machines").paginate():
        machines += page.get("stateMachines", [])
    for m in sorted(machines, key=lambda m: m["name"]):
        d = sfn.describe_state_machine(stateMachineArn=m["stateMachineArn"])
        tags = {t["key"]: t["value"] for t in (attempt(sfn.list_tags_for_resource, resourceArn=m["stateMachineArn"]) or {}).get("tags", [])
                if not t["key"].startswith("aws:")}
        attrs: dict = {"name": d["name"], "role_arn": ctx.ref("aws_iam_role", d["roleArn"], "arn"),
                       "type": d["type"] if d.get("type") not in (None, "STANDARD") else None,
                       "definition": hcl.jsonencode(ctx.refify(_json(d["definition"]) or {}))}
        blocks = []
        lc = d.get("loggingConfiguration") or {}
        if lc.get("level") not in (None, "OFF"):
            dest = ((lc.get("destinations") or [{}])[0].get("cloudWatchLogsLogGroup") or {}).get("logGroupArn", "")
            group = dest.split("log-group:", 1)[-1].removesuffix(":*") if "log-group:" in dest else ""
            laddr = ctx.addr.get(("aws_cloudwatch_log_group", group))
            ld = hcl.Tpl([hcl.Ref(f"{laddr}.arn"), ":*"]) if laddr else dest
            blocks.append(("logging_configuration", {"level": lc["level"], "include_execution_data": bool(lc.get("includeExecutionData")),
                                                     "log_destination": ld}))
        if (d.get("tracingConfiguration") or {}).get("enabled"):
            blocks.append(("tracing_configuration", {"enabled": True}))
        attrs["tags"] = tags or None
        ctx.add("aws_sfn_state_machine", m["stateMachineArn"], d["name"], attrs, blocks, file="workflows.tf")


@exporter(46, "ecr")
def export_ecr(ctx: Ctx) -> None:
    ecr = ctx.c["ecr"]
    repos = []
    for page in ecr.get_paginator("describe_repositories").paginate():
        repos += page.get("repositories", [])
    for r in sorted(repos, key=lambda r: r["repositoryName"]):
        name = r["repositoryName"]
        attrs: dict = {"name": name, "image_tag_mutability": r["imageTagMutability"] if r.get("imageTagMutability") not in (None, "MUTABLE") else None,
                       "tags": tags_of([{"Key": t["Key"], "Value": t["Value"]} for t in
                                        (attempt(ecr.list_tags_for_resource, resourceArn=r["repositoryArn"]) or {}).get("tags", [])]) or None}
        blocks = []
        if (r.get("imageScanningConfiguration") or {}).get("scanOnPush"):
            blocks.append(("image_scanning_configuration", {"scan_on_push": True}))
        enc = r.get("encryptionConfiguration") or {}
        if enc.get("encryptionType") == "KMS":
            blocks.append(("encryption_configuration", {"encryption_type": "KMS", "kms_key": ctx.ref("aws_kms_key", enc.get("kmsKey", ""), "arn")}))
        addr = ctx.add("aws_ecr_repository", r["repositoryArn"], name, attrs, blocks, file="registry.tf")
        repo = hcl.Ref(f"{addr}.name")
        short = addr.split(".", 1)[1]
        lp = _json((attempt(ecr.get_lifecycle_policy, repositoryName=name) or {}).get("lifecyclePolicyText"))
        if lp:
            ctx.add("aws_ecr_lifecycle_policy", name, short, {"repository": repo, "policy": hcl.jsonencode(lp)}, file="registry.tf")
        rp = _json((attempt(ecr.get_repository_policy, repositoryName=name) or {}).get("policyText"))
        if rp:
            ctx.add("aws_ecr_repository_policy", name, short, {"repository": repo, "policy": hcl.jsonencode(ctx.refify(rp))}, file="registry.tf")


_DIM_REFS = (("InstanceId", "aws_instance", "id"), ("DBInstanceIdentifier", "aws_db_instance", "identifier"),
             ("TableName", "aws_dynamodb_table", "name"), ("VolumeId", "aws_ebs_volume", "id"))


def _dims(ctx: Ctx, dims: list) -> dict | None:
    out = {}
    for d in dims or []:
        val = d["Value"]
        for dim, rtype, attr in _DIM_REFS:
            if d["Name"] == dim and (rtype, val) in ctx.addr:
                val = ctx.ref(rtype, val, attr)
                break
        out[d["Name"]] = val
    return out or None


@exporter(80, "cloudwatch-alarms")
def export_alarms(ctx: Ctx) -> None:
    cw = ctx.c["cloudwatch"]
    metric, composite = [], []
    for page in cw.get_paginator("describe_alarms").paginate(AlarmTypes=["MetricAlarm", "CompositeAlarm"]):
        metric += page.get("MetricAlarms", [])
        composite += page.get("CompositeAlarms", [])
    for a in sorted(metric, key=lambda a: a["AlarmName"]):
        attrs: dict = {"alarm_name": a["AlarmName"], "alarm_description": a.get("AlarmDescription") or None,
                       "comparison_operator": a["ComparisonOperator"], "evaluation_periods": a["EvaluationPeriods"],
                       "datapoints_to_alarm": a.get("DatapointsToAlarm") if a.get("DatapointsToAlarm") not in (None, a["EvaluationPeriods"]) else None,
                       "threshold": a.get("Threshold"), "threshold_metric_id": a.get("ThresholdMetricId"),
                       "treat_missing_data": a["TreatMissingData"] if a.get("TreatMissingData") not in (None, "missing") else None,
                       "actions_enabled": False if a.get("ActionsEnabled") is False else None,
                       "alarm_actions": ctx.refify(a.get("AlarmActions") or []) or None, "ok_actions": ctx.refify(a.get("OKActions") or []) or None,
                       "insufficient_data_actions": ctx.refify(a.get("InsufficientDataActions") or []) or None,
                       "evaluate_low_sample_count_percentiles": a.get("EvaluateLowSampleCountPercentile") or None}
        blocks = []
        if a.get("Metrics"):
            for q in a["Metrics"]:
                qa = {"id": q["Id"], "expression": q.get("Expression"), "label": q.get("Label") or None,
                      "return_data": q.get("ReturnData") if q.get("ReturnData") is not None and q.get("ReturnData") is not True else None,
                      "period": q.get("Period")}
                kids = []
                ms = q.get("MetricStat")
                if ms:
                    kids.append(("metric", {"metric_name": ms["Metric"]["MetricName"], "namespace": ms["Metric"].get("Namespace"), "period": ms["Period"],
                                            "stat": ms["Stat"], "unit": ms.get("Unit"), "dimensions": _dims(ctx, ms["Metric"].get("Dimensions"))}))
                blocks.append(("metric_query", qa, kids))
        else:
            attrs.update({"metric_name": a.get("MetricName"), "namespace": a.get("Namespace"), "period": a.get("Period"),
                          "statistic": a.get("Statistic"), "extended_statistic": a.get("ExtendedStatistic"), "unit": a.get("Unit"),
                          "dimensions": _dims(ctx, a.get("Dimensions"))})
        attrs["tags"] = tags_of((attempt(cw.list_tags_for_resource, ResourceARN=a["AlarmArn"]) or {}).get("Tags")) or None
        ctx.add("aws_cloudwatch_metric_alarm", a["AlarmArn"], a["AlarmName"], attrs, blocks, file="observability.tf")
    names = {a["AlarmName"]: ctx.addr[("aws_cloudwatch_metric_alarm", a["AlarmArn"])] for a in metric}
    for a in sorted(composite, key=lambda a: a["AlarmName"]):
        # ALARM("name") / OK(name): an exported alarm's name becomes a reference to it (so Terraform orders the two correctly)
        parts: list = []
        last = 0
        for m in re.finditer(r'\b(ALARM|OK|INSUFFICIENT_DATA)\(("?)([^()"]+)\2\)', a["AlarmRule"]):
            if m.group(3) in names and m.group(3) != a["AlarmName"]:
                parts += [a["AlarmRule"][last:m.start(3)], hcl.Ref(f"{names[m.group(3)]}.alarm_name")]
                last = m.end(3)
        parts.append(a["AlarmRule"][last:])
        alarm_rule = hcl.Tpl([p for p in parts if p != ""]) if len(parts) > 1 else a["AlarmRule"]
        attrs = {"alarm_name": a["AlarmName"], "alarm_description": a.get("AlarmDescription") or None, "alarm_rule": alarm_rule,
                 "actions_enabled": False if a.get("ActionsEnabled") is False else None,
                 "alarm_actions": ctx.refify(a.get("AlarmActions") or []) or None, "ok_actions": ctx.refify(a.get("OKActions") or []) or None,
                 "insufficient_data_actions": ctx.refify(a.get("InsufficientDataActions") or []) or None}
        ctx.add("aws_cloudwatch_composite_alarm", a["AlarmArn"], a["AlarmName"], attrs, file="observability.tf")


def _lifecycle(lc: dict | None):
    if not lc:
        return None
    return {"cold_storage_after": lc.get("MoveToColdStorageAfterDays"), "delete_after": lc.get("DeleteAfterDays")}


@exporter(81, "backup")
def export_backup(ctx: Ctx) -> None:
    bk = ctx.c["backup"]
    vaults = []
    for page in bk.get_paginator("list_backup_vaults").paginate():
        vaults += page.get("BackupVaultList", [])
    for v in sorted(vaults, key=lambda v: v["BackupVaultName"]):
        name = v["BackupVaultName"]
        if name == "Default" or name.startswith("aws/"):
            continue
        key = v.get("EncryptionKeyArn") or ""
        kref = ctx.ref("aws_kms_key", key, "arn") if ("aws_kms_key", key) in ctx.addr else None
        tags = (attempt(bk.list_tags, ResourceArn=v["BackupVaultArn"]) or {}).get("Tags") or {}
        ctx.add("aws_backup_vault", name, name, {"name": name, "kms_key_arn": kref, "tags": {k: x for k, x in tags.items() if not k.startswith("aws:")} or None},
                file="backup.tf")
        if v.get("Locked"):
            ctx.add("aws_backup_vault_lock_configuration", name, name,
                    {"backup_vault_name": ctx.ref("aws_backup_vault", name, "name"), "min_retention_days": v.get("MinRetentionDays"),
                     "max_retention_days": v.get("MaxRetentionDays")}, file="backup.tf")
    plans = []
    for page in bk.get_paginator("list_backup_plans").paginate():
        plans += page.get("BackupPlansList", [])
    for p in sorted(plans, key=lambda p: p["BackupPlanName"]):
        got = bk.get_backup_plan(BackupPlanId=p["BackupPlanId"])["BackupPlan"]
        blocks = []
        for r in sorted(got.get("Rules", []), key=lambda r: r["RuleName"]):
            ra: dict = {"rule_name": r["RuleName"], "target_vault_name": ctx.ref("aws_backup_vault", r["TargetBackupVaultName"], "name"),
                        "schedule": r.get("ScheduleExpression"),
                        "start_window": r["StartWindowMinutes"] if r.get("StartWindowMinutes") not in (None, 480) else None,
                        "completion_window": r["CompletionWindowMinutes"] if r.get("CompletionWindowMinutes") not in (None, 10080) else None,
                        "enable_continuous_backup": True if r.get("EnableContinuousBackup") else None,
                        "recovery_point_tags": r.get("RecoveryPointTags") or None}
            kids = []
            if _lifecycle(r.get("Lifecycle")):
                kids.append(("lifecycle", _lifecycle(r["Lifecycle"])))
            for c in r.get("CopyActions") or []:
                ck = [("lifecycle", _lifecycle(c["Lifecycle"]))] if _lifecycle(c.get("Lifecycle")) else []
                kids.append(("copy_action", {"destination_vault_arn": ctx.refify(c["DestinationBackupVaultArn"])}, ck))
            blocks.append(("rule", ra, kids))
        tags = (attempt(bk.list_tags, ResourceArn=p["BackupPlanArn"]) or {}).get("Tags") or {}
        paddr = ctx.add("aws_backup_plan", p["BackupPlanId"], p["BackupPlanName"],
                        {"name": p["BackupPlanName"], "tags": {k: x for k, x in tags.items() if not k.startswith("aws:")} or None}, blocks, file="backup.tf")
        for s in sorted(paged(bk.list_backup_selections, "BackupSelectionsList", BackupPlanId=p["BackupPlanId"]), key=lambda s: s["SelectionName"]):
            sel = bk.get_backup_selection(BackupPlanId=p["BackupPlanId"], SelectionId=s["SelectionId"])["BackupSelection"]
            sa: dict = {"name": sel["SelectionName"], "plan_id": hcl.Ref(f"{paddr}.id"), "iam_role_arn": ctx.ref("aws_iam_role", sel["IamRoleArn"], "arn"),
                        "resources": ctx.refify(sel.get("Resources") or []) or None, "not_resources": ctx.refify(sel.get("NotResources") or []) or None}
            tag_blocks = [("selection_tag", {"type": t["ConditionType"], "key": t["ConditionKey"], "value": t["ConditionValue"]})
                          for t in sorted(sel.get("ListOfTags") or [], key=lambda t: (t["ConditionKey"], t["ConditionValue"]))]
            ctx.add("aws_backup_selection", f"{p['BackupPlanId']}/{s['SelectionId']}", f"{p['BackupPlanName']}_{sel['SelectionName']}", sa, tag_blocks,
                    file="backup.tf")
