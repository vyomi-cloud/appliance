"""Appliers for the resource types the second batch of exporters writes: DynamoDB, SQS / SNS / EventBridge, KMS, EC2 instances / keys /
volumes / instance profiles, Step Functions, ECR, CloudWatch alarms, AWS Backup. Same contract as ``aws_apply`` (find by natural key,
create through the native API, delete from outputs); stdlib only, so it runs unchanged on Nano."""
from __future__ import annotations

import json

from core.tf_export.apply import applier
from core.tf_export.aws_apply import _claim, _missing, _opt, _paged, _same_tags, _tag_list, _tagspec, code
from core.tf_export.core import tags_of

_GONE = ("NotFound", "NoSuch", "DoesNotExist", "NonExistent", "ResourceNotFound", "ValidationException")


def _gone(exc: Exception, *extra: str) -> bool:
    c = code(exc)
    return _missing(exc, *extra) or any(x in c for x in _GONE[:5])


def _tags_kv(tags: dict, k="Key", v="Value") -> list:
    return [{k: a, v: b} for a, b in tags.items()]


def _s(v) -> str:
    return "true" if v is True else "false" if v is False else str(v)


def _blk(a, name):
    """First nested block's attributes (``{}`` when absent)."""
    return next((b[1] for b in a.blocks_of(name)), {})


# -------------------------------------------------------------------------------------------------------------------- KMS
def _key_out(md):
    return {"id": md["KeyId"], "key_id": md["KeyId"], "arn": md["Arn"]}


@applier("aws_kms_key")
class KmsKey:
    """Keys have no name: an existing customer key with the same description / usage / spec / tags is the one."""

    def find(self, c, a):
        ids = []
        for page in c.kms.get_paginator("list_keys").paginate():
            ids += [k["KeyId"] for k in page.get("Keys", [])]
        for kid in sorted(ids):
            md = c.kms.describe_key(KeyId=kid)["KeyMetadata"]
            if md.get("KeyManager") == "AWS" or md.get("KeyState") in ("PendingDeletion", "PendingReplicaDeletion"):
                continue
            if (md.get("Description") or "") != (a.get("description") or "") or md.get("KeyUsage", "ENCRYPT_DECRYPT") != a.get("key_usage", "ENCRYPT_DECRYPT"):
                continue
            if md.get("KeySpec", "SYMMETRIC_DEFAULT") != a.get("customer_master_key_spec", "SYMMETRIC_DEFAULT"):
                continue
            raw = c.kms.list_resource_tags(KeyId=kid).get("Tags") or []
            if tags_of([{"Key": t["TagKey"], "Value": t["TagValue"]} for t in raw]) != a.tags:
                continue
            if _claim(c, kid):
                return _key_out(md)
        return None

    def create(self, c, a):
        md = c.kms.create_key(**_opt({}, Description=a.get("description"), KeyUsage=a.get("key_usage"), KeySpec=a.get("customer_master_key_spec"),
                                     Policy=a.get("policy"), MultiRegion=a.attrs.get("multi_region"),
                                     Tags=_tags_kv(a.tags, "TagKey", "TagValue") or None))["KeyMetadata"]
        if a.attrs.get("enable_key_rotation"):
            c.kms.enable_key_rotation(KeyId=md["KeyId"])
        if a.attrs.get("is_enabled") is False:
            c.kms.disable_key(KeyId=md["KeyId"])
        c.claimed.add(md["KeyId"])
        return _key_out(md)

    def delete(self, c, out):
        c.kms.schedule_key_deletion(KeyId=out["key_id"], PendingWindowInDays=7)


@applier("aws_kms_alias")
class KmsAlias:
    def _out(self, c, name, key=""):
        return {"id": name, "name": name, "arn": f"arn:aws:kms:{c.region}:{c.account}:{name}", "target_key_id": key}

    def find(self, c, a):
        for page in c.kms.get_paginator("list_aliases").paginate():
            for al in page.get("Aliases", []):
                if al["AliasName"] == a.get("name"):
                    return self._out(c, al["AliasName"], al.get("TargetKeyId", ""))
        return None

    def create(self, c, a):
        c.kms.create_alias(AliasName=a.get("name"), TargetKeyId=a.get("target_key_id"))
        return self._out(c, a.get("name"), a.get("target_key_id"))

    def delete(self, c, out):
        c.kms.delete_alias(AliasName=out["name"])


# ------------------------------------------------------------------------------------------------------------------ DynamoDB
@applier("aws_dynamodb_table")
class DynamoTable:
    def _out(self, t):
        return {"id": t["TableName"], "name": t["TableName"], "arn": t["TableArn"], "stream_arn": t.get("LatestStreamArn", ""),
                "stream_label": t.get("LatestStreamLabel", "")}

    def find(self, c, a):
        try:
            return self._out(c.dynamodb.describe_table(TableName=a.get("name"))["Table"])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise

    @staticmethod
    def _proj(b):
        p = {"ProjectionType": b.get("projection_type") or "ALL"}
        if b.get("non_key_attributes"):
            p["NonKeyAttributes"] = list(b["non_key_attributes"])
        return p

    @staticmethod
    def _schema(h, r=None):
        return [{"AttributeName": h, "KeyType": "HASH"}] + ([{"AttributeName": r, "KeyType": "RANGE"}] if r else [])

    def create(self, c, a):
        on_demand = a.get("billing_mode") == "PAY_PER_REQUEST"
        kw: dict = {"TableName": a.get("name"), "KeySchema": self._schema(a.get("hash_key"), a.get("range_key")),
                    "AttributeDefinitions": [{"AttributeName": b[1]["name"], "AttributeType": b[1]["type"]} for b in a.blocks_of("attribute")],
                    "BillingMode": "PAY_PER_REQUEST" if on_demand else "PROVISIONED"}
        if not on_demand:
            kw["ProvisionedThroughput"] = {"ReadCapacityUnits": int(a.get("read_capacity", 5)), "WriteCapacityUnits": int(a.get("write_capacity", 5))}
        gsis = []
        for _t, b, _k in a.blocks_of("global_secondary_index"):
            g = {"IndexName": b["name"], "KeySchema": self._schema(b.get("hash_key"), b.get("range_key")), "Projection": self._proj(b)}
            if not on_demand:
                g["ProvisionedThroughput"] = {"ReadCapacityUnits": int(b.get("read_capacity", 5)), "WriteCapacityUnits": int(b.get("write_capacity", 5))}
            gsis.append(g)
        lsis = [{"IndexName": b["name"], "KeySchema": self._schema(a.get("hash_key"), b.get("range_key")), "Projection": self._proj(b)}
                for _t, b, _k in a.blocks_of("local_secondary_index")]
        if gsis:
            kw["GlobalSecondaryIndexes"] = gsis
        if lsis:
            kw["LocalSecondaryIndexes"] = lsis
        if a.attrs.get("stream_enabled"):
            kw["StreamSpecification"] = {"StreamEnabled": True, "StreamViewType": a.get("stream_view_type", "NEW_AND_OLD_IMAGES")}
        sse = _blk(a, "server_side_encryption")
        if sse.get("enabled"):
            kw["SSESpecification"] = _opt({"Enabled": True, "SSEType": "KMS"}, KMSMasterKeyId=sse.get("kms_key_arn"))
        _opt(kw, TableClass=a.get("table_class"), DeletionProtectionEnabled=a.attrs.get("deletion_protection_enabled"), Tags=_tag_list(a.tags) or None)
        t = c.dynamodb.create_table(**kw)["TableDescription"]
        ttl = _blk(a, "ttl")
        if ttl.get("enabled"):
            c.dynamodb.update_time_to_live(TableName=a.get("name"), TimeToLiveSpecification={"Enabled": True, "AttributeName": ttl["attribute_name"]})
        if _blk(a, "point_in_time_recovery").get("enabled"):
            c.dynamodb.update_continuous_backups(TableName=a.get("name"), PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})
        return self._out(t)

    def delete(self, c, out):
        try:
            c.dynamodb.update_table(TableName=out["name"], DeletionProtectionEnabled=False)
        except Exception:  # noqa: BLE001 - not protected / not supported
            pass
        c.dynamodb.delete_table(TableName=out["name"])


# ------------------------------------------------------------------------------------------------------------------------ SQS
_SQS_ATTRS = (("visibility_timeout_seconds", "VisibilityTimeout"), ("message_retention_seconds", "MessageRetentionPeriod"),
              ("max_message_size", "MaximumMessageSize"), ("delay_seconds", "DelaySeconds"),
              ("receive_wait_time_seconds", "ReceiveMessageWaitTimeSeconds"), ("kms_master_key_id", "KmsMasterKeyId"),
              ("kms_data_key_reuse_period_seconds", "KmsDataKeyReusePeriodSeconds"), ("policy", "Policy"), ("redrive_policy", "RedrivePolicy"),
              ("redrive_allow_policy", "RedriveAllowPolicy"), ("deduplication_scope", "DeduplicationScope"),
              ("fifo_throughput_limit", "FifoThroughputLimit"))


@applier("aws_sqs_queue")
class SqsQueue:
    def _out(self, c, name, url):
        arn = c.sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"]).get("Attributes", {}).get("QueueArn") \
            or f"arn:aws:sqs:{c.region}:{c.account}:{name}"
        return {"id": url, "url": url, "arn": arn, "name": name}

    def find(self, c, a):
        try:
            url = c.sqs.get_queue_url(QueueName=a.get("name"))["QueueUrl"]
        except Exception as exc:  # noqa: BLE001
            if _gone(exc, "AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"):
                return None
            raise
        return self._out(c, a.get("name"), url)

    def create(self, c, a):
        at = {}
        for tf, aws in _SQS_ATTRS:
            if a.attrs.get(tf) is not None:
                at[aws] = _s(a.attrs[tf])
        for tf, aws in (("fifo_queue", "FifoQueue"), ("content_based_deduplication", "ContentBasedDeduplication"), ("sqs_managed_sse_enabled", "SqsManagedSseEnabled")):
            if a.attrs.get(tf) is not None:
                at[aws] = _s(a.attrs[tf])
        url = c.sqs.create_queue(**_opt({"QueueName": a.get("name"), "Attributes": at}, tags=a.tags or None))["QueueUrl"]
        return self._out(c, a.get("name"), url)

    def delete(self, c, out):
        c.sqs.delete_queue(QueueUrl=out["url"])


# ------------------------------------------------------------------------------------------------------------------------ SNS
@applier("aws_sns_topic")
class SnsTopic:
    def _out(self, arn):
        return {"id": arn, "arn": arn, "name": arn.rsplit(":", 1)[-1]}

    def find(self, c, a):
        for page in c.sns.get_paginator("list_topics").paginate():
            for t in page.get("Topics", []):
                if t["TopicArn"].rsplit(":", 1)[-1] == a.get("name"):
                    return self._out(t["TopicArn"])
        return None

    def create(self, c, a):
        at = {}
        for tf, aws in (("display_name", "DisplayName"), ("fifo_topic", "FifoTopic"), ("content_based_deduplication", "ContentBasedDeduplication"),
                        ("kms_master_key_id", "KmsMasterKeyId"), ("policy", "Policy"), ("delivery_policy", "DeliveryPolicy")):
            if a.attrs.get(tf) is not None:
                at[aws] = _s(a.attrs[tf])
        arn = c.sns.create_topic(**_opt({"Name": a.get("name"), "Attributes": at}, Tags=_tag_list(a.tags) or None))["TopicArn"]
        return self._out(arn)

    def delete(self, c, out):
        c.sns.delete_topic(TopicArn=out["arn"])


@applier("aws_sns_topic_subscription")
class SnsSubscription:
    def find(self, c, a):
        try:
            for page in c.sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=a.get("topic_arn")):
                for s in page.get("Subscriptions", []):
                    if s["Protocol"] == a.get("protocol") and s["Endpoint"] == a.get("endpoint") and _claim(c, s["SubscriptionArn"]):
                        return {"id": s["SubscriptionArn"], "arn": s["SubscriptionArn"], "topic_arn": s["TopicArn"]}
        except Exception as exc:  # noqa: BLE001
            if not _gone(exc):
                raise
        return None

    def create(self, c, a):
        at = {}
        for tf, aws in (("raw_message_delivery", "RawMessageDelivery"), ("filter_policy", "FilterPolicy"), ("filter_policy_scope", "FilterPolicyScope"),
                        ("redrive_policy", "RedrivePolicy"), ("subscription_role_arn", "SubscriptionRoleArn")):
            if a.attrs.get(tf) is not None:
                at[aws] = _s(a.attrs[tf])
        arn = c.sns.subscribe(**{"TopicArn": a.get("topic_arn"), "Protocol": a.get("protocol"), "Endpoint": a.get("endpoint"), "Attributes": at,
                                 "ReturnSubscriptionArn": True})["SubscriptionArn"]
        c.claimed.add(arn)
        return {"id": arn, "arn": arn, "topic_arn": a.get("topic_arn")}

    def delete(self, c, out):
        c.sns.unsubscribe(SubscriptionArn=out["arn"])


# ------------------------------------------------------------------------------------------------------------------ EventBridge
def _bus(a):
    return a.get("event_bus_name") or "default"


def _bus_kw(a):
    return {"EventBusName": a.get("event_bus_name")} if a.get("event_bus_name") else {}


@applier("aws_cloudwatch_event_bus")
class EventBus:
    def _out(self, b):
        return {"id": b["Name"], "name": b["Name"], "arn": b["Arn"]}

    def find(self, c, a):
        try:
            return self._out(c.events.describe_event_bus(Name=a.get("name")))
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise

    def create(self, c, a):
        r = c.events.create_event_bus(**_opt({"Name": a.get("name")}, Description=a.get("description"), KmsKeyIdentifier=a.get("kms_key_identifier"),
                                             Tags=_tag_list(a.tags) or None))
        return {"id": a.get("name"), "name": a.get("name"), "arn": r.get("EventBusArn", "")}

    def delete(self, c, out):
        c.events.delete_event_bus(Name=out["name"])


@applier("aws_cloudwatch_event_bus_policy")
class EventBusPolicy:
    def find(self, c, a):
        try:
            cur = c.events.describe_event_bus(Name=_bus(a)).get("Policy")
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise
        want = json.loads(a.get("policy")) if isinstance(a.get("policy"), str) else a.get("policy")
        return {"id": _bus(a), "event_bus_name": _bus(a)} if cur and json.loads(cur) == want else None

    def create(self, c, a):
        c.events.put_permission(**_bus_kw(a), Policy=a.get("policy"))
        return {"id": _bus(a), "event_bus_name": _bus(a)}

    def delete(self, c, out):
        kw = {"EventBusName": out["event_bus_name"]} if out["event_bus_name"] != "default" else {}
        c.events.remove_permission(RemoveAllPermissions=True, **kw)


@applier("aws_cloudwatch_event_rule")
class EventRule:
    def _out(self, a, arn):
        b = _bus(a)
        return {"id": a.get("name") if b == "default" else f"{b}/{a.get('name')}", "name": a.get("name"), "arn": arn, "event_bus_name": b}

    def find(self, c, a):
        try:
            return self._out(a, c.events.describe_rule(Name=a.get("name"), **_bus_kw(a))["Arn"])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise

    def create(self, c, a):
        kw = _opt({"Name": a.get("name"), "State": a.get("state") or "ENABLED"}, Description=a.get("description"),
                  ScheduleExpression=a.get("schedule_expression"), EventPattern=a.get("event_pattern"), RoleArn=a.get("role_arn"),
                  Tags=_tag_list(a.tags) or None, **_bus_kw(a))
        return self._out(a, c.events.put_rule(**kw)["RuleArn"])

    def delete(self, c, out):
        kw = {"EventBusName": out["event_bus_name"]} if out["event_bus_name"] != "default" else {}
        c.events.delete_rule(Name=out["name"], Force=True, **kw)


@applier("aws_cloudwatch_event_target")
class EventTarget:
    def _out(self, a):
        b, r = _bus(a), a.get("rule")
        return {"id": f"{r}-{a.get('target_id')}" if b == "default" else f"{b}/{r}/{a.get('target_id')}", "rule": r,
                "event_bus_name": b, "target_id": a.get("target_id")}

    def find(self, c, a):
        try:
            for page in c.events.get_paginator("list_targets_by_rule").paginate(Rule=a.get("rule"), **_bus_kw(a)):
                if any(t["Id"] == a.get("target_id") for t in page.get("Targets", [])):
                    return self._out(a)
        except Exception as exc:  # noqa: BLE001
            if not _gone(exc):
                raise
        return None

    def create(self, c, a):
        t = _opt({"Id": a.get("target_id"), "Arn": a.get("arn")}, RoleArn=a.get("role_arn"), Input=a.get("input"), InputPath=a.get("input_path"))
        it = _blk(a, "input_transformer")
        if it:
            t["InputTransformer"] = _opt({"InputTemplate": it.get("input_template")}, InputPathsMap=it.get("input_paths"))
        if _blk(a, "dead_letter_config"):
            t["DeadLetterConfig"] = {"Arn": _blk(a, "dead_letter_config").get("arn")}
        rp = _blk(a, "retry_policy")
        if rp:
            t["RetryPolicy"] = _opt({}, MaximumEventAgeInSeconds=rp.get("maximum_event_age_in_seconds"), MaximumRetryAttempts=rp.get("maximum_retry_attempts"))
        sq = _blk(a, "sqs_target")
        if sq:
            t["SqsParameters"] = {"MessageGroupId": sq.get("message_group_id")}
        r = c.events.put_targets(Rule=a.get("rule"), Targets=[t], **_bus_kw(a))
        if r.get("FailedEntryCount"):
            raise RuntimeError("put_targets failed: " + json.dumps(r.get("FailedEntries")))
        return self._out(a)

    def delete(self, c, out):
        kw = {"EventBusName": out["event_bus_name"]} if out["event_bus_name"] != "default" else {}
        c.events.remove_targets(Rule=out["rule"], Ids=[out["target_id"]], Force=True, **kw)


# --------------------------------------------------------------------------------------------------------------- CloudWatch
def _dim_list(d):
    return [{"Name": k, "Value": str(v)} for k, v in d.items()] if d else None


@applier("aws_cloudwatch_metric_alarm")
class MetricAlarm:
    def _out(self, al):
        return {"id": al["AlarmName"], "alarm_name": al["AlarmName"], "arn": al["AlarmArn"]}

    def find(self, c, a):
        r = c.cloudwatch.describe_alarms(AlarmNames=[a.get("alarm_name")], AlarmTypes=["MetricAlarm"]).get("MetricAlarms", [])
        return self._out(r[0]) if r else None

    def create(self, c, a):
        kw = _opt({"AlarmName": a.get("alarm_name"), "ComparisonOperator": a.get("comparison_operator"),
                   "EvaluationPeriods": int(a.get("evaluation_periods"))},
                  AlarmDescription=a.get("alarm_description"), DatapointsToAlarm=a.get("datapoints_to_alarm"), Threshold=a.get("threshold"),
                  ThresholdMetricId=a.get("threshold_metric_id"), TreatMissingData=a.get("treat_missing_data"),
                  ActionsEnabled=a.attrs.get("actions_enabled"), AlarmActions=a.get("alarm_actions"), OKActions=a.get("ok_actions"),
                  InsufficientDataActions=a.get("insufficient_data_actions"),
                  EvaluateLowSampleCountPercentile=a.get("evaluate_low_sample_count_percentiles"), Tags=_tag_list(a.tags) or None)
        if kw.get("Threshold") is not None:
            kw["Threshold"] = float(kw["Threshold"])
        if a.blocks_of("metric_query"):
            qs = []
            for _t, q, kids in a.blocks_of("metric_query"):
                d = _opt({"Id": q["id"]}, Expression=q.get("expression"), Label=q.get("label"), ReturnData=q.get("return_data"))
                if q.get("period") is not None:
                    d["Period"] = int(q["period"])
                for kt, m, *_ in kids:
                    if kt == "metric":
                        d["MetricStat"] = {"Metric": _opt({"MetricName": m["metric_name"]}, Namespace=m.get("namespace"), Dimensions=_dim_list(m.get("dimensions"))),
                                           "Period": int(m["period"]), "Stat": m["stat"], **({"Unit": m["unit"]} if m.get("unit") else {})}
                qs.append(d)
            kw["Metrics"] = qs
        else:
            _opt(kw, MetricName=a.get("metric_name"), Namespace=a.get("namespace"), Statistic=a.get("statistic"),
                 ExtendedStatistic=a.get("extended_statistic"), Unit=a.get("unit"), Dimensions=_dim_list(a.get("dimensions")))
            if a.get("period") is not None:
                kw["Period"] = int(a.get("period"))
        c.cloudwatch.put_metric_alarm(**kw)
        return self.find(c, a) or {"id": a.get("alarm_name"), "alarm_name": a.get("alarm_name"),
                                   "arn": f"arn:aws:cloudwatch:{c.region}:{c.account}:alarm:{a.get('alarm_name')}"}

    def delete(self, c, out):
        c.cloudwatch.delete_alarms(AlarmNames=[out["alarm_name"]])


@applier("aws_cloudwatch_composite_alarm")
class CompositeAlarm:
    def find(self, c, a):
        r = c.cloudwatch.describe_alarms(AlarmNames=[a.get("alarm_name")], AlarmTypes=["CompositeAlarm"]).get("CompositeAlarms", [])
        return {"id": r[0]["AlarmName"], "alarm_name": r[0]["AlarmName"], "arn": r[0]["AlarmArn"]} if r else None

    def create(self, c, a):
        c.cloudwatch.put_composite_alarm(**_opt({"AlarmName": a.get("alarm_name"), "AlarmRule": a.get("alarm_rule")},
                                                AlarmDescription=a.get("alarm_description"), ActionsEnabled=a.attrs.get("actions_enabled"),
                                                AlarmActions=a.get("alarm_actions"), OKActions=a.get("ok_actions"),
                                                InsufficientDataActions=a.get("insufficient_data_actions"), Tags=_tag_list(a.tags) or None))
        return self.find(c, a)

    def delete(self, c, out):
        c.cloudwatch.delete_alarms(AlarmNames=[out["alarm_name"]])


# ------------------------------------------------------------------------------------------------------------- Step Functions
@applier("aws_sfn_state_machine")
class StateMachine:
    def _out(self, arn, name):
        return {"id": arn, "arn": arn, "name": name}

    def find(self, c, a):
        for page in c.stepfunctions.get_paginator("list_state_machines").paginate():
            for m in page.get("stateMachines", []):
                if m["name"] == a.get("name"):
                    return self._out(m["stateMachineArn"], m["name"])
        return None

    def create(self, c, a):
        kw = _opt({"name": a.get("name"), "definition": a.get("definition"), "roleArn": a.get("role_arn")}, type=a.get("type"),
                  tags=_tags_kv(a.tags, "key", "value") or None)
        lc = _blk(a, "logging_configuration")
        if lc:
            kw["loggingConfiguration"] = _opt({"level": lc.get("level"), "includeExecutionData": bool(lc.get("include_execution_data"))},
                                              destinations=[{"cloudWatchLogsLogGroup": {"logGroupArn": lc["log_destination"]}}] if lc.get("log_destination") else None)
        if _blk(a, "tracing_configuration").get("enabled"):
            kw["tracingConfiguration"] = {"enabled": True}
        return self._out(c.stepfunctions.create_state_machine(**kw)["stateMachineArn"], a.get("name"))

    def delete(self, c, out):
        c.stepfunctions.delete_state_machine(stateMachineArn=out["arn"])


# ------------------------------------------------------------------------------------------------------------------------ ECR
@applier("aws_ecr_repository")
class EcrRepository:
    def _out(self, r):
        return {"id": r["repositoryName"], "name": r["repositoryName"], "arn": r["repositoryArn"], "repository_url": r.get("repositoryUri", ""),
                "registry_id": r.get("registryId", "")}

    def find(self, c, a):
        try:
            return self._out(c.ecr.describe_repositories(repositoryNames=[a.get("name")])["repositories"][0])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc, "RepositoryNotFoundException"):
                return None
            raise

    def create(self, c, a):
        kw = _opt({"repositoryName": a.get("name")}, imageTagMutability=a.get("image_tag_mutability"), tags=_tags_kv(a.tags) or None)
        if _blk(a, "image_scanning_configuration"):
            kw["imageScanningConfiguration"] = {"scanOnPush": bool(_blk(a, "image_scanning_configuration").get("scan_on_push"))}
        enc = _blk(a, "encryption_configuration")
        if enc:
            kw["encryptionConfiguration"] = _opt({"encryptionType": enc.get("encryption_type") or "AES256"}, kmsKey=enc.get("kms_key"))
        return self._out(c.ecr.create_repository(**kw)["repository"])

    def delete(self, c, out):
        c.ecr.delete_repository(repositoryName=out["name"], force=True)


@applier("aws_ecr_lifecycle_policy")
class EcrLifecycle:
    def find(self, c, a):
        try:
            cur = c.ecr.get_lifecycle_policy(repositoryName=a.get("repository")).get("lifecyclePolicyText")
        except Exception as exc:  # noqa: BLE001
            if _gone(exc, "LifecyclePolicyNotFoundException", "RepositoryNotFoundException"):
                return None
            raise
        want = json.loads(a.get("policy")) if isinstance(a.get("policy"), str) else a.get("policy")
        return {"id": a.get("repository"), "repository": a.get("repository")} if cur and json.loads(cur) == want else None

    def create(self, c, a):
        c.ecr.put_lifecycle_policy(repositoryName=a.get("repository"), lifecyclePolicyText=a.get("policy"))
        return {"id": a.get("repository"), "repository": a.get("repository")}

    def delete(self, c, out):
        c.ecr.delete_lifecycle_policy(repositoryName=out["repository"])


@applier("aws_ecr_repository_policy")
class EcrRepoPolicy:
    def find(self, c, a):
        try:
            cur = c.ecr.get_repository_policy(repositoryName=a.get("repository")).get("policyText")
        except Exception as exc:  # noqa: BLE001
            if _gone(exc, "RepositoryPolicyNotFoundException", "RepositoryNotFoundException"):
                return None
            raise
        want = json.loads(a.get("policy")) if isinstance(a.get("policy"), str) else a.get("policy")
        return {"id": a.get("repository"), "repository": a.get("repository")} if cur and json.loads(cur) == want else None

    def create(self, c, a):
        c.ecr.set_repository_policy(repositoryName=a.get("repository"), policyText=a.get("policy"))
        return {"id": a.get("repository"), "repository": a.get("repository")}

    def delete(self, c, out):
        c.ecr.delete_repository_policy(repositoryName=out["repository"])


# ---------------------------------------------------------------------------------------------------------------------- Backup
@applier("aws_backup_vault")
class BackupVault:
    def _out(self, v):
        return {"id": v["BackupVaultName"], "name": v["BackupVaultName"], "arn": v["BackupVaultArn"]}

    def find(self, c, a):
        try:
            return self._out(c.backup.describe_backup_vault(BackupVaultName=a.get("name")))
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise

    def create(self, c, a):
        r = c.backup.create_backup_vault(**_opt({"BackupVaultName": a.get("name")}, EncryptionKeyArn=a.get("kms_key_arn"), BackupVaultTags=a.tags or None))
        return {"id": a.get("name"), "name": a.get("name"), "arn": r["BackupVaultArn"]}

    def delete(self, c, out):
        c.backup.delete_backup_vault(BackupVaultName=out["name"])


@applier("aws_backup_vault_lock_configuration")
class BackupVaultLock:
    def find(self, c, a):
        try:
            v = c.backup.describe_backup_vault(BackupVaultName=a.get("backup_vault_name"))
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise
        return {"id": a.get("backup_vault_name"), "backup_vault_name": a.get("backup_vault_name")} if v.get("Locked") else None

    def create(self, c, a):
        c.backup.put_backup_vault_lock_configuration(**_opt({"BackupVaultName": a.get("backup_vault_name")}, MinRetentionDays=a.get("min_retention_days"),
                                                            MaxRetentionDays=a.get("max_retention_days"),
                                                            ChangeableForDays=a.get("changeable_for_days")))
        return {"id": a.get("backup_vault_name"), "backup_vault_name": a.get("backup_vault_name")}

    def delete(self, c, out):
        c.backup.delete_backup_vault_lock_configuration(BackupVaultName=out["backup_vault_name"])


@applier("aws_backup_plan")
class BackupPlan:
    def _out(self, p):
        return {"id": p["BackupPlanId"], "arn": p["BackupPlanArn"], "name": p.get("BackupPlanName", ""), "version": p.get("VersionId", "")}

    def find(self, c, a):
        for page in c.backup.get_paginator("list_backup_plans").paginate():
            for p in page.get("BackupPlansList", []):
                if p["BackupPlanName"] == a.get("name") and _claim(c, p["BackupPlanId"]):
                    return self._out(p)
        return None

    @staticmethod
    def _lc(kids):
        for k in kids:
            if k[0] == "lifecycle":
                return _opt({}, MoveToColdStorageAfterDays=k[1].get("cold_storage_after"), DeleteAfterDays=k[1].get("delete_after"))
        return None

    def create(self, c, a):
        rules = []
        for _t, r, kids in a.blocks_of("rule"):
            d = _opt({"RuleName": r["rule_name"], "TargetBackupVaultName": r["target_vault_name"],
                      "StartWindowMinutes": int(r.get("start_window") or 480), "CompletionWindowMinutes": int(r.get("completion_window") or 10080)},
                     ScheduleExpression=r.get("schedule"), RecoveryPointTags=r.get("recovery_point_tags") or None,
                     EnableContinuousBackup=r.get("enable_continuous_backup"), Lifecycle=self._lc(kids))
            copies = []
            for k in kids:
                if k[0] == "copy_action":
                    copies.append(_opt({"DestinationBackupVaultArn": k[1]["destination_vault_arn"]}, Lifecycle=self._lc(k[2] if len(k) > 2 else [])))
            if copies:
                d["CopyActions"] = copies
            rules.append(d)
        p = c.backup.create_backup_plan(**_opt({"BackupPlan": {"BackupPlanName": a.get("name"), "Rules": rules}}, BackupPlanTags=a.tags or None))
        c.claimed.add(p["BackupPlanId"])
        return {"id": p["BackupPlanId"], "arn": p["BackupPlanArn"], "name": a.get("name"), "version": p.get("VersionId", "")}

    def delete(self, c, out):
        c.backup.delete_backup_plan(BackupPlanId=out["id"])


@applier("aws_backup_selection")
class BackupSelection:
    def find(self, c, a):
        try:
            for s in _paged_token(c.backup.list_backup_selections, "BackupSelectionsList", BackupPlanId=a.get("plan_id")):
                if s["SelectionName"] == a.get("name"):
                    return {"id": s["SelectionId"], "plan_id": a.get("plan_id"), "selection_id": s["SelectionId"]}
        except Exception as exc:  # noqa: BLE001
            if not _gone(exc):
                raise
        return None

    def create(self, c, a):
        sel = _opt({"SelectionName": a.get("name"), "IamRoleArn": a.get("iam_role_arn")}, Resources=list(a.get("resources") or []) or None,
                   NotResources=list(a.get("not_resources") or []) or None)
        tags = [{"ConditionType": b[1]["type"], "ConditionKey": b[1]["key"], "ConditionValue": b[1]["value"]} for b in a.blocks_of("selection_tag")]
        if tags:
            sel["ListOfTags"] = tags
        r = c.backup.create_backup_selection(BackupPlanId=a.get("plan_id"), BackupSelection=sel)
        return {"id": r["SelectionId"], "plan_id": a.get("plan_id"), "selection_id": r["SelectionId"]}

    def delete(self, c, out):
        c.backup.delete_backup_selection(BackupPlanId=out["plan_id"], SelectionId=out["selection_id"])


def _paged_token(fn, key, **kw):
    out, tok = [], None
    while True:
        r = fn(**kw, **({"NextToken": tok} if tok else {}))
        out += r.get(key, [])
        tok = r.get("NextToken")
        if not tok:
            return out


# ------------------------------------------------------------------------------------------------------------------------ EC2
@applier("aws_iam_instance_profile")
class InstanceProfile:
    def _out(self, p):
        return {"id": p["InstanceProfileName"], "name": p["InstanceProfileName"], "arn": p["Arn"], "unique_id": p.get("InstanceProfileId", "")}

    def find(self, c, a):
        try:
            return self._out(c.iam.get_instance_profile(InstanceProfileName=a.get("name"))["InstanceProfile"])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise

    def create(self, c, a):
        p = c.iam.create_instance_profile(**_opt({"InstanceProfileName": a.get("name")}, Path=a.get("path"), Tags=_tag_list(a.tags) or None))["InstanceProfile"]
        if a.get("role"):
            c.iam.add_role_to_instance_profile(InstanceProfileName=a.get("name"), RoleName=a.get("role"))
        return self._out(p)

    def delete(self, c, out):
        p = c.iam.get_instance_profile(InstanceProfileName=out["name"])["InstanceProfile"]
        for r in p.get("Roles", []):
            c.iam.remove_role_from_instance_profile(InstanceProfileName=out["name"], RoleName=r["RoleName"])
        c.iam.delete_instance_profile(InstanceProfileName=out["name"])


@applier("aws_key_pair")
class KeyPair:
    def _out(self, k):
        return {"id": k["KeyName"], "key_name": k["KeyName"], "key_pair_id": k.get("KeyPairId", ""), "fingerprint": k.get("KeyFingerprint", ""),
                "arn": f"arn:aws:ec2:::key-pair/{k.get('KeyPairId', k['KeyName'])}"}

    def find(self, c, a):
        try:
            return self._out(c.ec2.describe_key_pairs(KeyNames=[a.get("key_name")])["KeyPairs"][0])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc, "InvalidKeyPair.NotFound"):
                return None
            raise

    def create(self, c, a):
        r = c.ec2.import_key_pair(KeyName=a.get("key_name"), PublicKeyMaterial=str(a.get("public_key", "")).encode(),
                                  **({"TagSpecifications": _tagspec("key-pair", a.tags)} if a.tags else {}))
        return self._out(r)

    def delete(self, c, out):
        c.ec2.delete_key_pair(KeyName=out["key_name"])


def _root_volumes(c) -> set:
    out = set()
    for page in c.ec2.get_paginator("describe_instances").paginate():
        for res in page.get("Reservations", []):
            for i in res.get("Instances", []):
                for m in i.get("BlockDeviceMappings", []):
                    if m.get("DeviceName") == i.get("RootDeviceName") and m.get("Ebs"):
                        out.add(m["Ebs"]["VolumeId"])
    return out


@applier("aws_ebs_volume")
class EbsVolume:
    """No name: an unclaimed, non-root volume in the same zone with the same size / type / encryption / tags is the one."""

    def _out(self, c, v):
        return {"id": v["VolumeId"], "arn": f"arn:aws:ec2:{c.region}:{c.account}:volume/{v['VolumeId']}", "size": v.get("Size", 0),
                "availability_zone": v.get("AvailabilityZone", "")}

    def find(self, c, a):
        roots = None
        for page in c.ec2.get_paginator("describe_volumes").paginate():
            for v in page.get("Volumes", []):
                if v.get("State") in ("deleting", "deleted") or v.get("AvailabilityZone") != a.get("availability_zone"):
                    continue
                if v.get("Size") != a.get("size") or v.get("VolumeType") != (a.get("type") or "gp2") or bool(v.get("Encrypted")) != bool(a.get("encrypted")):
                    continue
                if not _same_tags(v.get("Tags"), a.tags):
                    continue
                roots = _root_volumes(c) if roots is None else roots
                if v["VolumeId"] not in roots and _claim(c, v["VolumeId"]):
                    return self._out(c, v)
        return None

    def create(self, c, a):
        v = c.ec2.create_volume(**_opt({"AvailabilityZone": a.get("availability_zone"), "TagSpecifications": _tagspec("volume", a.tags)},
                                       Size=a.get("size"), VolumeType=a.get("type"), Encrypted=a.attrs.get("encrypted"), KmsKeyId=a.get("kms_key_id"),
                                       Iops=a.get("iops"), Throughput=a.get("throughput"), SnapshotId=a.get("snapshot_id")))
        c.claimed.add(v["VolumeId"])
        return self._out(c, v)

    def delete(self, c, out):
        c.ec2.delete_volume(VolumeId=out["id"])


@applier("aws_volume_attachment")
class VolumeAttachment:
    def _out(self, a):
        return {"id": f"vai-{a.get('instance_id')}-{a.get('volume_id')}", "device_name": a.get("device_name"), "volume_id": a.get("volume_id"),
                "instance_id": a.get("instance_id")}

    def find(self, c, a):
        try:
            vs = c.ec2.describe_volumes(VolumeIds=[a.get("volume_id")]).get("Volumes", [])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                return None
            raise
        for v in vs:
            if any(x.get("InstanceId") == a.get("instance_id") and x.get("State", "attached") in ("attached", "attaching") for x in v.get("Attachments", [])):
                return self._out(a)
        return None

    def create(self, c, a):
        c.ec2.attach_volume(Device=a.get("device_name"), InstanceId=a.get("instance_id"), VolumeId=a.get("volume_id"))
        return self._out(a)

    def delete(self, c, out):
        c.ec2.detach_volume(VolumeId=out["volume_id"], InstanceId=out["instance_id"], Force=True)


@applier("aws_instance")
class Instance:
    """No name: an unclaimed live instance with the same image / type / subnet / tags is the one."""

    def _out(self, c, i):
        return {"id": i["InstanceId"], "arn": f"arn:aws:ec2:{c.region}:{c.account}:instance/{i['InstanceId']}", "instance_state": (i.get("State") or {}).get("Name", ""),
                "private_ip": i.get("PrivateIpAddress", ""), "public_ip": i.get("PublicIpAddress", ""), "subnet_id": i.get("SubnetId", ""),
                "availability_zone": (i.get("Placement") or {}).get("AvailabilityZone", ""), "private_dns": i.get("PrivateDnsName", ""),
                "public_dns": i.get("PublicDnsName", "")}

    def find(self, c, a):
        for page in c.ec2.get_paginator("describe_instances").paginate():
            for res in page.get("Reservations", []):
                for i in res.get("Instances", []):
                    if (i.get("State") or {}).get("Name") in ("terminated", "shutting-down"):
                        continue
                    if i.get("ImageId") != a.get("ami") or i.get("InstanceType") != a.get("instance_type") or not _same_tags(i.get("Tags"), a.tags):
                        continue
                    if a.get("subnet_id") and i.get("SubnetId") != a.get("subnet_id"):
                        continue
                    if _claim(c, i["InstanceId"]):
                        return self._out(c, i)
        return None

    def _root_device(self, c, ami):
        try:
            return c.ec2.describe_images(ImageIds=[ami])["Images"][0].get("RootDeviceName") or "/dev/xvda"
        except Exception:  # noqa: BLE001
            return "/dev/xvda"

    def create(self, c, a):
        kw = _opt({"ImageId": a.get("ami"), "InstanceType": a.get("instance_type"), "MinCount": 1, "MaxCount": 1,
                   "TagSpecifications": _tagspec("instance", a.tags)},
                  SubnetId=a.get("subnet_id"), SecurityGroupIds=list(a.get("vpc_security_group_ids") or []) or None, KeyName=a.get("key_name"),
                  EbsOptimized=a.attrs.get("ebs_optimized"), UserData=a.get("user_data"))
        if a.attrs.get("monitoring"):
            kw["Monitoring"] = {"Enabled": True}
        if a.get("iam_instance_profile"):
            kw["IamInstanceProfile"] = {"Name": a.get("iam_instance_profile")}
        md = _blk(a, "metadata_options")
        if md:
            kw["MetadataOptions"] = _opt({}, HttpEndpoint=md.get("http_endpoint"), HttpTokens=md.get("http_tokens"),
                                         HttpPutResponseHopLimit=md.get("http_put_response_hop_limit"))
        rb = _blk(a, "root_block_device")
        if rb:
            kw["BlockDeviceMappings"] = [{"DeviceName": self._root_device(c, a.get("ami")),
                                          "Ebs": _opt({}, VolumeSize=rb.get("volume_size"), VolumeType=rb.get("volume_type"), Encrypted=rb.get("encrypted"),
                                                      DeleteOnTermination=rb.get("delete_on_termination"))}]
        i = c.ec2.run_instances(**kw)["Instances"][0]
        c.claimed.add(i["InstanceId"])
        return self._out(c, i)

    def delete(self, c, out):
        c.ec2.terminate_instances(InstanceIds=[out["id"]])
