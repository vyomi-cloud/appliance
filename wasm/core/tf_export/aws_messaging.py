# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""SQS queues (+ dead-letter redrive, policy), SNS topics + subscriptions, EventBridge buses / rules / targets."""
from __future__ import annotations

import json

from core.tf_export import hcl
from core.tf_export.core import Ctx, attempt, exporter, paged, tags_of

_SQS_INT = (("VisibilityTimeout", "visibility_timeout_seconds", 30), ("MessageRetentionPeriod", "message_retention_seconds", 345600),
            ("MaximumMessageSize", "max_message_size", 262144), ("DelaySeconds", "delay_seconds", 0),
            ("ReceiveMessageWaitTimeSeconds", "receive_wait_time_seconds", 0))


def _json(text):
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        return None
    return out or None


def _kms(ctx: Ctx, key: str):
    return ctx.ref("aws_kms_key", key, "arn") if key.startswith("arn:") else key


@exporter(42, "sqs")
def export_sqs(ctx: Ctx) -> None:
    sqs = ctx.c["sqs"]
    urls: list[str] = []
    for page in sqs.get_paginator("list_queues").paginate():
        urls += page.get("QueueUrls", [])
    got = {}
    for url in sorted(urls):
        a = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"]).get("Attributes", {})
        got[url] = a
        ctx.reserve("aws_sqs_queue", a["QueueArn"], url.rstrip("/").rsplit("/", 1)[-1])  # reserved first: a dead-letter queue is referenced by ARN
    for url in sorted(urls):
        a, name = got[url], url.rstrip("/").rsplit("/", 1)[-1]
        attrs: dict = {"name": name}
        for src, dst, default in _SQS_INT:
            if src in a and int(a[src]) != default:
                attrs[dst] = int(a[src])
        if a.get("FifoQueue") == "true":
            attrs["fifo_queue"] = True
            if a.get("ContentBasedDeduplication") == "true":
                attrs["content_based_deduplication"] = True
            if a.get("DeduplicationScope") == "messageGroup":
                attrs["deduplication_scope"] = "messageGroup"
            if a.get("FifoThroughputLimit") == "perMessageGroupId":
                attrs["fifo_throughput_limit"] = "perMessageGroupId"
        if a.get("KmsMasterKeyId"):
            attrs["kms_master_key_id"] = _kms(ctx, a["KmsMasterKeyId"])
            if a.get("KmsDataKeyReusePeriodSeconds") not in (None, "300"):
                attrs["kms_data_key_reuse_period_seconds"] = int(a["KmsDataKeyReusePeriodSeconds"])
        elif a.get("SqsManagedSseEnabled") == "false":
            attrs["sqs_managed_sse_enabled"] = False
        if _json(a.get("Policy")):
            attrs["policy"] = hcl.jsonencode(ctx.refify(_json(a["Policy"]), a["QueueArn"]))
        rd = _json(a.get("RedrivePolicy"))
        if rd:
            if isinstance(rd.get("maxReceiveCount"), str):
                rd["maxReceiveCount"] = int(rd["maxReceiveCount"])
            attrs["redrive_policy"] = hcl.jsonencode(ctx.refify(rd, a["QueueArn"]))
        if _json(a.get("RedriveAllowPolicy")):
            attrs["redrive_allow_policy"] = hcl.jsonencode(ctx.refify(_json(a["RedriveAllowPolicy"]), a["QueueArn"]))
        attrs["tags"] = (attempt(sqs.list_queue_tags, QueueUrl=url) or {}).get("Tags") or None
        ctx.add("aws_sqs_queue", a["QueueArn"], name, attrs, file="messaging.tf")


@exporter(43, "sns")
def export_sns(ctx: Ctx) -> None:
    sns = ctx.c["sns"]
    arns: list[str] = []
    for page in sns.get_paginator("list_topics").paginate():
        arns += [t["TopicArn"] for t in page.get("Topics", [])]
    topics = {}
    for arn in sorted(arns):
        topics[arn] = sns.get_topic_attributes(TopicArn=arn).get("Attributes", {})
        ctx.reserve("aws_sns_topic", arn, arn.rsplit(":", 1)[-1])
    for arn in sorted(arns):
        a, name = topics[arn], arn.rsplit(":", 1)[-1]
        attrs: dict = {"name": name, "display_name": a.get("DisplayName") or None}
        if a.get("FifoTopic") == "true":
            attrs["fifo_topic"] = True
            if a.get("ContentBasedDeduplication") == "true":
                attrs["content_based_deduplication"] = True
        if a.get("KmsMasterKeyId"):
            attrs["kms_master_key_id"] = _kms(ctx, a["KmsMasterKeyId"])
        pol = _json(a.get("Policy"))
        if pol and not all(s.get("Sid") == "__default_statement_ID" for s in pol.get("Statement", [])):
            attrs["policy"] = hcl.jsonencode(ctx.refify(pol, arn))
        if _json(a.get("DeliveryPolicy")):
            attrs["delivery_policy"] = hcl.jsonencode(_json(a["DeliveryPolicy"]))
        attrs["tags"] = tags_of((attempt(sns.list_tags_for_resource, ResourceArn=arn) or {}).get("Tags")) or None
        addr = ctx.add("aws_sns_topic", arn, name, attrs, file="messaging.tf")
        subs = []
        for page in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=arn):
            subs += page.get("Subscriptions", [])
        for s in sorted(subs, key=lambda s: (s["Protocol"], s["Endpoint"])):
            if s["SubscriptionArn"] == "PendingConfirmation":
                ctx.skip("aws_sns_topic_subscription", f"{name}/{s['Endpoint']}", "subscription is pending confirmation")
                continue
            sa = sns.get_subscription_attributes(SubscriptionArn=s["SubscriptionArn"]).get("Attributes", {})
            sub: dict = {"topic_arn": hcl.Ref(f"{addr}.arn"), "protocol": s["Protocol"], "endpoint": ctx.refify(s["Endpoint"])}
            if sa.get("RawMessageDelivery") == "true":
                sub["raw_message_delivery"] = True
            if _json(sa.get("FilterPolicy")):
                sub["filter_policy"] = hcl.jsonencode(_json(sa["FilterPolicy"]))
                if sa.get("FilterPolicyScope") == "MessageBody":
                    sub["filter_policy_scope"] = "MessageBody"
            if _json(sa.get("RedrivePolicy")):
                sub["redrive_policy"] = hcl.jsonencode(ctx.refify(_json(sa["RedrivePolicy"])))
            if sa.get("SubscriptionRoleArn"):
                sub["subscription_role_arn"] = ctx.ref("aws_iam_role", sa["SubscriptionRoleArn"], "arn")
            ctx.add("aws_sns_topic_subscription", s["SubscriptionArn"], f"{name}_{s['Protocol']}_{s['Endpoint'].rsplit(':', 1)[-1]}", sub, file="messaging.tf")


@exporter(45, "eventbridge")
def export_events(ctx: Ctx) -> None:
    ev = ctx.c["events"]
    for b in sorted(paged(ev.list_event_buses, "EventBuses"), key=lambda b: b["Name"]):
        name = b["Name"]
        bus_ref = None
        if name != "default":
            full = ev.describe_event_bus(Name=name)
            attrs = {"name": name, "description": full.get("Description") or None,
                     "kms_key_identifier": ctx.ref("aws_kms_key", full["KmsKeyIdentifier"], "arn") if full.get("KmsKeyIdentifier") else None,
                     "tags": tags_of((attempt(ev.list_tags_for_resource, ResourceARN=b["Arn"]) or {}).get("Tags")) or None}
            addr = ctx.add("aws_cloudwatch_event_bus", name, name, attrs, file="events.tf")
            bus_ref = hcl.Ref(f"{addr}.name")
            if _json(full.get("Policy")):
                ctx.add("aws_cloudwatch_event_bus_policy", name, name,
                        {"event_bus_name": bus_ref, "policy": hcl.jsonencode(ctx.refify(_json(full["Policy"])))}, file="events.tf")
        for r in sorted(paged(ev.list_rules, "Rules", EventBusName=name), key=lambda r: r["Name"]):
            if r.get("ManagedBy"):
                continue
            rule = ev.describe_rule(Name=r["Name"], EventBusName=name)
            pattern = _json(rule.get("EventPattern"))
            rattrs: dict = {"name": r["Name"], "event_bus_name": bus_ref, "description": rule.get("Description") or None,
                            "schedule_expression": rule.get("ScheduleExpression") or None,
                            "event_pattern": hcl.jsonencode(pattern) if pattern else None,
                            "state": "DISABLED" if rule.get("State") == "DISABLED" else None,
                            "role_arn": ctx.ref("aws_iam_role", rule["RoleArn"], "arn") if rule.get("RoleArn") else None,
                            "tags": tags_of((attempt(ev.list_tags_for_resource, ResourceARN=rule["Arn"]) or {}).get("Tags")) or None}
            hint = f"{name}_{r['Name']}" if name != "default" else r["Name"]
            raddr = ctx.add("aws_cloudwatch_event_rule", f"{name}/{r['Name']}", hint, rattrs, file="events.tf")
            for t in sorted(paged(ev.list_targets_by_rule, "Targets", Rule=r["Name"], EventBusName=name), key=lambda t: t["Id"]):
                tattrs: dict = {"rule": hcl.Ref(f"{raddr}.name"), "event_bus_name": bus_ref, "target_id": t["Id"], "arn": ctx.refify(t["Arn"]),
                                "role_arn": ctx.ref("aws_iam_role", t["RoleArn"], "arn") if t.get("RoleArn") else None,
                                "input": t.get("Input"), "input_path": t.get("InputPath")}
                blocks = []
                it = t.get("InputTransformer")
                if it:
                    blocks.append(("input_transformer", {"input_paths": it.get("InputPathsMap") or None, "input_template": it.get("InputTemplate")}))
                if (t.get("DeadLetterConfig") or {}).get("Arn"):
                    blocks.append(("dead_letter_config", {"arn": ctx.refify(t["DeadLetterConfig"]["Arn"])}))
                rp = t.get("RetryPolicy")
                if rp:
                    blocks.append(("retry_policy", {"maximum_event_age_in_seconds": rp.get("MaximumEventAgeInSeconds"),
                                                    "maximum_retry_attempts": rp.get("MaximumRetryAttempts")}))
                if (t.get("SqsParameters") or {}).get("MessageGroupId"):
                    blocks.append(("sqs_target", {"message_group_id": t["SqsParameters"]["MessageGroupId"]}))
                ctx.add("aws_cloudwatch_event_target", f"{name}/{r['Name']}/{t['Id']}", f"{hint}_{t['Id']}", tattrs, blocks, file="events.tf")
