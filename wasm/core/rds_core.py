# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""RDS core — substrate-independent, extracted from the appliance RDS handler
(server.py `_rds_*` / `api_rds_query`) so the SAME logic runs in Pro/Max
(FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 / socket / psycopg2 /
subprocess imports → loads under Pyodide. Persists + runs SQL through the SqlStore
seam (core/sql_store.py).

RDS speaks the AWS **Query protocol**: form-encoded POST with `Action=...&...` and
**XML** responses (not JSON/X-Amz-Target). The control plane returns an
`RdsResponse` (status, XML body, headers) in the native shapes
(<CreateDBInstanceResult><DBInstance>...</DBInstance></...>, <ErrorResponse>).

The DATA plane is special: AWS has no "run SQL" API — clients connect to the
endpoint over the Postgres/MySQL wire. In Nano that wire isn't reachable in-tab,
so `execute_sql()` exposes the instance's REAL SQL engine (sqlite3 via SqlStore)
to in-browser callers / the console query tool / the relay. The engine is real
(it actually parses + runs SQL); a PGlite/Postgres-wire engine swaps in behind
the seam for unmodified-psycopg2 conformance later.

Scope (v1 slice): CreateDBInstance, DescribeDBInstances, ModifyDBInstance,
DeleteDBInstance, StartDBInstance, StopDBInstance, RebootDBInstance,
CreateDBSnapshot, DescribeDBSnapshots + the execute_sql data-plane. Subnet/
parameter groups, read replicas, and Multi-AZ reuse the same helpers and slot in
next.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from core.sql_store import SqlStore, TransactionError, TransactionLimitError
from core import cloudwatch_core as _cw_core

RDS_NS = "http://rds.amazonaws.com/doc/2014-10-31/"
_ENGINE_PORT = {"postgres": 5432, "postgresql": 5432, "aurora-postgresql": 5432,
                "mysql": 3306, "mariadb": 3306, "aurora-mysql": 3306}


@dataclass
class RdsResponse:
    status: int = 200
    body: str = ""          # XML text
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class RdsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


# ── primitives ─────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _instance_arn(store: SqlStore, db_id: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:db:{db_id}"


def _snapshot_arn(store: SqlStore, snap_id: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:snapshot:{snap_id}"


def _subnet_group_arn(store: SqlStore, name: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:subgrp:{name}"


def _parameter_group_arn(store: SqlStore, name: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:pg:{name}"


def _proxy_arn(store: SqlStore, name: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:db-proxy:{name}"


def _option_group_arn(store: SqlStore, name: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:og:{name}"


def _event_subscription_arn(store: SqlStore, name: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:es:{name}"


def _integration_arn(store: SqlStore, name: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:integration:{name}"


def _certificate_arn(store: SqlStore, cert_id: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:cert:{cert_id}"


DEFAULT_CA = "rds-ca-rsa2048-g1"  # the current (non-expiring) CA; anything else needs updating

# Real AWS RDS CA catalog (DescribeCertificates) — the actual identifiers + validity
# windows AWS publishes. CACertificateIdentifier is validated against this list
# (CreateDBInstance/ModifyDBInstance reject anything else), and it's what the
# certificate-update page's "CA expiration date" is derived from, instead of "-".
CERTIFICATE_CATALOG: dict[str, dict] = {
    "rds-ca-2019": {"type": "CA", "valid_from": "2019-09-19", "valid_till": "2024-08-22"},
    "rds-ca-rsa2048-g1": {"type": "CA", "valid_from": "2021-06-28", "valid_till": "2061-06-28"},
    "rds-ca-rsa4096-g1": {"type": "CA", "valid_from": "2021-06-28", "valid_till": "2121-06-28"},
    "rds-ca-ecc384-g1": {"type": "CA", "valid_from": "2021-06-28", "valid_till": "2121-06-28"},
}


def _engine_port(engine: str) -> int:
    return _ENGINE_PORT.get(engine.lower(), 5432)


def _members(params: dict, prefix: str) -> list:
    """Collect an AWS Query-protocol list parameter: `{prefix}.member.{i}` (scalar)
    or `{prefix}.member.{i}.{field}` (structured, e.g. Tags.member.1.Key). Returns
    a list of strings for a scalar list, dicts for a structured one."""
    out: list = []
    i = 1
    while True:
        scalar_key = f"{prefix}.member.{i}"
        if scalar_key in params:
            out.append(params[scalar_key])
            i += 1
            continue
        struct_prefix = scalar_key + "."
        sub = {k[len(struct_prefix):]: v for k, v in params.items() if k.startswith(struct_prefix)}
        if not sub:
            break
        out.append(sub)
        i += 1
    return out


def _tags_from_params(params: dict) -> dict[str, str]:
    return {str(t.get("Key", "")): str(t.get("Value", "")) for t in _members(params, "Tags") if t.get("Key")}


def _tag_list_xml(tags: dict[str, str]) -> str:
    inner = "".join(f"<Tag>{_el('Key', k)}{_el('Value', v)}</Tag>" for k, v in tags.items())
    return f"<TagList>{inner}</TagList>"


def _log_event(store: SqlStore, source_id: str, source_type: str, message: str,
               categories: list[str] | None = None, msg_store=None) -> None:
    categories = categories or ["notification"]
    store.add_event({
        "source_identifier": source_id, "source_type": source_type,
        "message": message, "date": _now(),
        "event_categories": categories,
    })
    if msg_store is not None:
        _notify_subscribers(store, msg_store, source_id, source_type, categories, message)


def _notify_subscribers(store: SqlStore, msg_store, source_id: str, source_type: str,
                        categories: list[str], message: str) -> None:
    """Real fan-out: every ENABLED event subscription whose SourceType matches (or
    is unset — "all sources") and whose EventCategories overlaps (or is empty —
    "all categories") gets this event delivered to its SNS topic, through the
    SAME sns_core.publish_arn seam EventBridge targets use. A topic that doesn't
    exist (or no SnsTopicArn at all) is silently skipped — publish_arn()'s own
    contract — matching a subscription that was never confirmed in real SNS."""
    try:
        from core import sns_core as sns_mod
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import sns_core as sns_mod  # type: ignore
    for name in store.event_subscription_names():
        sub = store.get_event_subscription(name)
        if not sub or not sub.get("enabled", True):
            continue
        sub_source = sub.get("source_type") or ""
        if sub_source and sub_source != source_type:
            continue
        sub_cats = sub.get("event_categories") or []
        if sub_cats and not (set(sub_cats) & set(categories)):
            continue
        arn = sub.get("sns_topic_arn")
        if arn:
            sns_mod.publish_arn(msg_store, arn, f"RDS event for {source_id} ({source_type}): {message}")


# ── response builders (native RDS Query-protocol XML) ──────────────────────
def _success(action: str, result_inner: str, status: int = 200) -> RdsResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{RDS_NS}">'
           f'<{action}Result>{result_inner}</{action}Result>'
           f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return RdsResponse(status=status, body=xml)


def _error(code: str, message: str, status: int = 400) -> RdsResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{RDS_NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return RdsResponse(status=status, body=xml)


def _el(tag: str, value) -> str:
    return f"<{tag}>{_xml_escape(str(value))}</{tag}>"


def _db_instance_xml(db: dict) -> str:
    parts = [
        "<DBInstance>",
        _el("DBInstanceIdentifier", db["db_instance_identifier"]),
        _el("DBInstanceClass", db.get("db_instance_class", "db.t3.micro")),
        _el("Engine", db.get("engine", "postgres")),
        _el("EngineVersion", db.get("engine_version", "16.4")),
        _el("DBInstanceStatus", db.get("db_instance_status", "available")),
        _el("MasterUsername", db.get("master_username", "admin")),
        _el("AllocatedStorage", db.get("allocated_storage", 20)),
        _el("StorageType", db.get("storage_type", "gp3")),
        _el("AvailabilityZone", db.get("availability_zone", "us-east-1a")),
        _el("MultiAZ", str(db.get("multi_az", False)).lower()),
        (_el("SecondaryAvailabilityZone", db["secondary_availability_zone"]) if db.get("secondary_availability_zone") else ""),
        _el("PubliclyAccessible", str(db.get("publicly_accessible", False)).lower()),
        _el("DBInstanceArn", db.get("db_instance_arn", "")),
        _el("InstanceCreateTime", db.get("created", "")),
        _el("DbInstancePort", db.get("endpoint_port", 5432)),
        _el("BackupRetentionPeriod", db.get("backup_retention_period", 7)),
        _el("DeletionProtection", str(db.get("deletion_protection", False)).lower()),
        _el("LatestRestorableTime", db.get("updated", db.get("created", ""))),
        _el("CACertificateIdentifier", db.get("ca_certificate_identifier", DEFAULT_CA)),
        "<Endpoint>",
        _el("Address", db.get("endpoint_address", "")),
        _el("Port", db.get("endpoint_port", 5432)),
        _el("HostedZoneId", "Z1PVIF0B656C1W"),
        "</Endpoint>",
        "<DBSubnetGroup>",
        _el("DBSubnetGroupName", db.get("db_subnet_group_name", "default")),
        _el("VpcId", "vpc-default"),
        "</DBSubnetGroup>",
        "<VpcSecurityGroups>",
        "".join(f"<VpcSecurityGroupMembership>{_el('VpcSecurityGroupId', sg)}{_el('Status', 'active')}</VpcSecurityGroupMembership>"
               for sg in db.get("vpc_security_group_ids", ["sg-default"])),
        "</VpcSecurityGroups>",
        "<DBParameterGroups>",
        f"<DBParameterGroupStatus>{_el('DBParameterGroupName', db.get('db_parameter_group_name', 'default'))}{_el('ParameterApplyStatus', 'in-sync')}</DBParameterGroupStatus>",
        "</DBParameterGroups>",
        (_el("ReadReplicaSourceDBInstanceIdentifier", db["read_replica_source_db_instance_identifier"])
         if db.get("read_replica_source_db_instance_identifier") else ""),
        "<ReadReplicaDBInstanceIdentifiers>" +
        "".join(_el("ReadReplicaDBInstanceIdentifier", r) for r in db.get("read_replica_db_instance_identifiers", [])) +
        "</ReadReplicaDBInstanceIdentifiers>",
        "</DBInstance>",
    ]
    return "".join(parts)


def _db_snapshot_xml(snap: dict) -> str:
    return "".join([
        "<DBSnapshot>",
        _el("DBSnapshotIdentifier", snap["db_snapshot_identifier"]),
        _el("DBSnapshotArn", snap.get("db_snapshot_arn")
            or f"arn:aws:rds:us-east-1:123456789012:snapshot:{snap['db_snapshot_identifier']}"),
        _el("DBInstanceIdentifier", snap.get("db_instance_identifier", "")),
        _el("Status", snap.get("status", "available")),
        _el("Engine", snap.get("engine", "postgres")),
        _el("EngineVersion", snap.get("engine_version", "16.4")),
        _el("AllocatedStorage", snap.get("allocated_storage", 20)),
        _el("SnapshotCreateTime", snap.get("created", "")),
        _el("SnapshotType", snap.get("snapshot_type", "manual")),
        "</DBSnapshot>",
    ])


def _subnet_xml(sn: dict) -> str:
    return "".join([
        "<Subnet>",
        _el("SubnetIdentifier", sn.get("subnet_identifier", "")),
        f"<SubnetAvailabilityZone>{_el('Name', sn.get('availability_zone', 'us-east-1a'))}</SubnetAvailabilityZone>",
        _el("SubnetStatus", "Active"),
        "</Subnet>",
    ])


def _subnet_group_xml(sg: dict) -> str:
    subnets = "".join(_subnet_xml(s) for s in sg.get("subnets", []))
    return "".join([
        "<DBSubnetGroup>",
        _el("DBSubnetGroupName", sg["db_subnet_group_name"]),
        _el("DBSubnetGroupDescription", sg.get("db_subnet_group_description", "")),
        _el("VpcId", sg.get("vpc_id", "vpc-default")),
        _el("SubnetGroupStatus", sg.get("subnet_group_status", "Complete")),
        _el("DBSubnetGroupArn", sg.get("db_subnet_group_arn", "")),
        f"<Subnets>{subnets}</Subnets>",
        "</DBSubnetGroup>",
    ])


def _parameter_xml(name: str, p: dict) -> str:
    return "".join([
        "<Parameter>",
        _el("ParameterName", name),
        _el("ParameterValue", p.get("parameter_value", "")),
        _el("AllowedValues", p.get("allowed_values", "")),
        _el("IsModifiable", str(p.get("is_modifiable", True)).lower()),
        _el("Source", p.get("source", "engine-default")),
        _el("ApplyType", p.get("apply_type", "dynamic")),
        _el("DataType", p.get("data_type", "string")),
        _el("Description", p.get("description", "")),
        "</Parameter>",
    ])


def _parameter_group_xml(pg: dict) -> str:
    return "".join([
        "<DBParameterGroup>",
        _el("DBParameterGroupName", pg["db_parameter_group_name"]),
        _el("DBParameterGroupFamily", pg.get("db_parameter_group_family", "")),
        _el("Description", pg.get("description", "")),
        _el("DBParameterGroupArn", pg.get("db_parameter_group_arn", "")),
        "</DBParameterGroup>",
    ])


def _proxy_xml(px: dict) -> str:
    return "".join([
        "<DBProxy>",
        _el("DBProxyName", px["db_proxy_name"]),
        _el("DBProxyArn", px.get("db_proxy_arn", "")),
        _el("EngineFamily", px.get("engine_family", "POSTGRESQL")),
        _el("Status", px.get("status", "available")),
        _el("CreatedDate", px.get("created", "")),
        "</DBProxy>",
    ])


def _option_group_xml(og: dict) -> str:
    return "".join([
        "<OptionGroup>",
        _el("OptionGroupName", og["option_group_name"]),
        _el("OptionGroupDescription", og.get("option_group_description", "")),
        _el("EngineName", og.get("engine_name", "")),
        _el("MajorEngineVersion", og.get("major_engine_version", "")),
        _el("OptionGroupArn", og.get("option_group_arn", "")),
        "<Options></Options>",
        "</OptionGroup>",
    ])


def _event_subscription_xml(es: dict) -> str:
    cats = "".join(_el("EventCategory", c) for c in es.get("event_categories", []))
    return "".join([
        "<EventSubscription>",
        _el("CustSubscriptionId", es["cust_subscription_id"]),
        _el("SnsTopicArn", es.get("sns_topic_arn", "")),
        _el("Status", es.get("status", "active")),
        _el("SourceType", es.get("source_type", "db-instance")),
        f"<EventCategoriesList>{cats}</EventCategoriesList>",
        _el("Enabled", str(es.get("enabled", True)).lower()),
        _el("CustomerAwsId", es.get("customer_aws_id", "")),
        _el("SubscriptionCreationTime", es.get("created", "")),
        "</EventSubscription>",
    ])


def _event_xml(ev: dict) -> str:
    cats = "".join(_el("EventCategory", c) for c in ev.get("event_categories", []))
    return "".join([
        "<Event>",
        _el("SourceIdentifier", ev.get("source_identifier", "")),
        _el("SourceType", ev.get("source_type", "db-instance")),
        _el("Message", ev.get("message", "")),
        _el("Date", ev.get("date", "")),
        f"<EventCategories>{cats}</EventCategories>",
        "</Event>",
    ])


def _automated_backup_xml(db: dict) -> str:
    return "".join([
        "<DBInstanceAutomatedBackup>",
        _el("DBInstanceIdentifier", db["db_instance_identifier"]),
        _el("Region", "us-east-1"),
        _el("Engine", db.get("engine", "postgres")),
        _el("Status", "replicating" if db.get("db_instance_status") == "available" else "retained"),
        _el("EarliestRestorableTime", db.get("created", "")),
        _el("LatestRestorableTime", db.get("updated", db.get("created", ""))),
        _el("Encrypted", "true"),
        "</DBInstanceAutomatedBackup>",
    ])


def _reserved_instance_xml(ri: dict) -> str:
    return "".join([
        "<ReservedDBInstance>",
        _el("ReservedDBInstanceId", ri["reserved_db_instance_id"]),
        _el("LeaseId", ri.get("lease_id", "")),
        _el("ReservedDBInstancesOfferingId", ri.get("offering_id", "")),
        _el("ProductDescription", ri.get("product_description", "")),
        _el("DBInstanceClass", ri.get("db_instance_class", "db.t3.micro")),
        _el("OfferingType", ri.get("offering_type", "No Upfront")),
        _el("State", ri.get("state", "active")),
        _el("MultiAZ", str(ri.get("multi_az", False)).lower()),
        _el("StartTime", ri.get("start_time", "")),
        _el("Duration", ri.get("duration", 31536000)),
        _el("DBInstanceCount", ri.get("db_instance_count", 1)),
        _el("CurrencyCode", "USD"),
        "</ReservedDBInstance>",
    ])


def _export_task_xml(et: dict) -> str:
    return "".join([
        "<ExportTask>",
        _el("ExportTaskIdentifier", et["export_task_identifier"]),
        _el("SourceArn", et.get("source_arn", "")),
        _el("SourceType", et.get("source_type", "SNAPSHOT")),
        _el("S3Bucket", et.get("s3_bucket", "")),
        _el("S3Prefix", et.get("s3_prefix", "")),
        _el("IamRoleArn", et.get("iam_role_arn", "")),
        _el("KmsKeyId", et.get("kms_key_id", "")),
        _el("Status", et.get("status", "COMPLETE")),
        _el("PercentProgress", et.get("percent_progress", 100)),
        _el("SnapshotTime", et.get("created", "")),
        _el("TaskStartTime", et.get("created", "")),
        _el("TaskEndTime", et.get("task_end_time", "")),
        _el("FailureCause", et.get("failure_cause", "")) if et.get("failure_cause") else "",
        ("<ExportOnly>" + "".join(_el("member", x) for x in et.get("export_only") or []) + "</ExportOnly>")
        if et.get("export_only") else "",
        _el("TotalExtractedDataInGB", et.get("total_extracted_data_in_gb", 0)),
        "</ExportTask>",
    ])


def _custom_engine_version_xml(cev: dict) -> str:
    return "".join([
        "<DBEngineVersion>",
        _el("Engine", cev.get("engine", "")),
        _el("EngineVersion", cev.get("engine_version", "")),
        _el("DBEngineVersionDescription", cev.get("description", "")),
        _el("DBEngineDescription", cev.get("engine", "")),
        _el("Status", cev.get("status", "available")),
        _el("CreateTime", cev.get("created", "")),
        "</DBEngineVersion>",
    ])


def _integration_xml(ig: dict) -> str:
    return "".join([
        "<Integration>",
        _el("IntegrationName", ig["integration_name"]),
        _el("IntegrationArn", ig.get("integration_arn", "")),
        _el("SourceArn", ig.get("source_arn", "")),
        _el("TargetArn", ig.get("target_arn", "")),
        _el("Status", ig.get("status", "active")),
        _el("CreateTime", ig.get("created", "")),
        "</Integration>",
    ])


def _db_recommendation_xml(rec: dict) -> str:
    return "".join([
        "<DBRecommendation>",
        _el("RecommendationId", rec["recommendation_id"]),
        _el("Severity", rec.get("severity", "medium")),
        _el("Status", "active"),
        _el("Detection", rec.get("detection", "")),
        _el("Recommendation", rec.get("recommendation", "")),
        _el("Impact", rec.get("impact", "")),
        _el("Category", rec.get("category", "")),
        _el("CreatedTime", rec.get("created", "")),
        _el("UpdatedTime", rec.get("created", "")),
        _el("ResourceArn", rec.get("resource_arn", "")),
        "</DBRecommendation>",
    ])


def _certificate_xml(store: SqlStore, cert_id: str, info: dict) -> str:
    return "".join([
        "<Certificate>",
        _el("CertificateIdentifier", cert_id),
        _el("CertificateType", info.get("type", "CA")),
        _el("ValidFrom", f"{info['valid_from']}T00:00:00Z"),
        _el("ValidTill", f"{info['valid_till']}T00:00:00Z"),
        _el("CertificateArn", _certificate_arn(store, cert_id)),
        _el("CustomerOverride", "false"),
        "</Certificate>",
    ])


def _describe_certificates(store: SqlStore, params: dict) -> RdsResponse:
    cert_id = str(params.get("CertificateIdentifier", "")).strip()
    if cert_id:
        info = CERTIFICATE_CATALOG.get(cert_id)
        if not info:
            raise RdsError("CertificateNotFound", f"Certificate {cert_id} not found.", 404)
        ids = [cert_id]
    else:
        ids = sorted(CERTIFICATE_CATALOG)
    inner = ("<Certificates>" + "".join(_certificate_xml(store, i, CERTIFICATE_CATALOG[i]) for i in ids)
             + "</Certificates>")
    return _success("DescribeCertificates", inner)


def _validate_ca_certificate(cert_id: str) -> None:
    """CACertificateIdentifier is only ever one of the real CA ids RDS actually
    issues (DescribeCertificates) — CreateDBInstance/ModifyDBInstance reject
    anything else, the way AWS does, instead of storing an arbitrary string."""
    if cert_id not in CERTIFICATE_CATALOG:
        raise RdsError("CertificateNotFound", f"Certificate {cert_id} not found.", 404)


# ── helpers ────────────────────────────────────────────────────────────────
def _require_instance(store: SqlStore, db_id: str) -> dict:
    db = store.get_instance(db_id)
    if not db:
        raise RdsError("DBInstanceNotFound", f"DBInstance {db_id} not found.", 404)
    return db


def _int(params: dict, key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


# ── control-plane operations ────────────────────────────────────────────────
def _create_db_instance(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    if not db_id:
        raise RdsError("InvalidParameterValue", "DBInstanceIdentifier is required.", 400)
    if store.instance_exists(db_id):
        raise RdsError("DBInstanceAlreadyExists", f"DBInstance {db_id} already exists.", 400)
    engine = str(params.get("Engine", "postgres")).lower()
    ca_cert = str(params.get("CACertificateIdentifier", DEFAULT_CA))
    _validate_ca_certificate(ca_cert)
    multi_az = str(params.get("MultiAZ", "false")).lower() == "true"
    availability_zone = str(params.get("AvailabilityZone", "us-east-1a"))
    record = {
        "db_instance_identifier": db_id,
        "db_instance_class": str(params.get("DBInstanceClass", "db.t3.micro")),
        "engine": engine,
        "engine_version": str(params.get("EngineVersion", "16.4")),
        "db_name": str(params.get("DBName", "")),
        "db_instance_status": "available",  # Nano: no provisioning lag, ready at once
        "master_username": str(params.get("MasterUsername", "admin")),
        "master_user_password": str(params.get("MasterUserPassword", "")),
        "allocated_storage": _int(params, "AllocatedStorage", 20),
        "storage_type": str(params.get("StorageType", "gp3")),
        "availability_zone": availability_zone,
        "multi_az": multi_az,
        "secondary_availability_zone": _secondary_az(availability_zone) if multi_az else None,
        "read_replica_source_db_instance_identifier": None,
        "read_replica_db_instance_identifiers": [],
        "publicly_accessible": str(params.get("PubliclyAccessible", "false")).lower() == "true",
        "backup_retention_period": _int(params, "BackupRetentionPeriod", 7),
        "endpoint_address": f"{db_id}.nano-rds.local",
        "endpoint_port": _int(params, "Port", _engine_port(engine)),
        "db_instance_arn": _instance_arn(store, db_id),
        "db_subnet_group_name": str(params.get("DBSubnetGroupName", "default")),
        "db_parameter_group_name": str(params.get("DBParameterGroupName", "default")),
        "vpc_security_group_ids": _members(params, "VpcSecurityGroupIds") or ["sg-default"],
        "deletion_protection": str(params.get("DeletionProtection", "false")).lower() == "true",
        "ca_certificate_identifier": ca_cert,
        "created": _now(),
        "updated": _now(),
        "runtime_backend": "sqlite",  # Nano data-plane engine
    }
    store.put_instance(db_id, record)
    tags = _tags_from_params(params)
    if tags:
        store.set_tags(record["db_instance_arn"], tags)
    # The SQL engine opens LAZILY on first execute_sql — so the control plane
    # needs no sqlite3 (a loadable Pyodide package), only the data plane does.
    store.mirror_create_instance(db_id, record)
    store.persist()
    _log_event(store, db_id, "db-instance", f"DB instance {db_id} created.", ["creation"], msg_store)
    return _success("CreateDBInstance", _db_instance_xml(record))


def _describe_db_instances(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    if db_id:
        ids = [db_id] if store.instance_exists(db_id) else []
        if not ids:
            raise RdsError("DBInstanceNotFound", f"DBInstance {db_id} not found.", 404)
    else:
        ids = store.instance_ids()
    inner = "<DBInstances>" + "".join(_db_instance_xml(store.get_instance(i)) for i in ids) + "</DBInstances>"
    return _success("DescribeDBInstances", inner)


def _modify_db_instance(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    if params.get("CACertificateIdentifier") is not None:
        _validate_ca_certificate(str(params["CACertificateIdentifier"]))
    for param, field_name, caster in (
        ("DBInstanceClass", "db_instance_class", str),
        ("AllocatedStorage", "allocated_storage", int),
        ("EngineVersion", "engine_version", str),
        ("BackupRetentionPeriod", "backup_retention_period", int),
        ("MasterUserPassword", "master_user_password", str),
        ("CACertificateIdentifier", "ca_certificate_identifier", str),
    ):
        if params.get(param) is not None:
            try:
                db[field_name] = caster(params[param])
            except (TypeError, ValueError):
                pass
    if params.get("MultiAZ") is not None:
        multi_az = str(params["MultiAZ"]).lower() == "true"
        db["multi_az"] = multi_az
        db["secondary_availability_zone"] = _secondary_az(db.get("availability_zone", "us-east-1a")) if multi_az else None
    db["updated"] = _now()
    store.persist()
    _log_event(store, db["db_instance_identifier"], "db-instance", "DB instance modified.", ["configuration change"], msg_store)
    return _success("ModifyDBInstance", _db_instance_xml(db))


def _set_status(store: SqlStore, params: dict, action: str, status: str, msg_store=None) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    if db.get("deletion_protection") and action == "DeleteDBInstance":
        raise RdsError("InvalidParameterCombination",
                       "Cannot delete a DB instance with deletion protection enabled.", 400)
    db_id = db["db_instance_identifier"]
    force_failover = action == "RebootDBInstance" and str(params.get("ForceFailover", "false")).lower() == "true"
    if force_failover:
        if not db.get("multi_az"):
            raise RdsError("InvalidParameterCombination",
                           "ForceFailover can only be used with a Multi-AZ DB instance.", 400)
        _log_event(store, db_id, "db-instance", "Multi-AZ instance failover started.", ["failover"], msg_store)
        primary, secondary = db.get("availability_zone", "us-east-1a"), db.get("secondary_availability_zone") or _secondary_az(db.get("availability_zone", "us-east-1a"))
        db["availability_zone"], db["secondary_availability_zone"] = secondary, primary
    db["db_instance_status"] = status
    db["updated"] = _now()
    store.persist()
    if force_failover:
        _log_event(store, db_id, "db-instance",
                   f"Multi-AZ instance failover completed. New primary is in Availability Zone {db['availability_zone']}.",
                   ["failover"], msg_store)
    else:
        _log_event(store, db_id, "db-instance", f"DB instance status set to {status}.", msg_store=msg_store)
    return _success(action, _db_instance_xml(db))


def _delete_db_instance(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    db = _require_instance(store, db_id)
    if db.get("deletion_protection"):
        raise RdsError("InvalidParameterCombination",
                       "Cannot delete a DB instance with deletion protection enabled.", 400)
    if db.get("read_replica_db_instance_identifiers"):
        raise RdsError("InvalidDBInstanceState",
                       f"DB instance {db_id} cannot be deleted because it has read replicas: "
                       f"{', '.join(db['read_replica_db_instance_identifiers'])}.", 400)
    if str(params.get("SkipFinalSnapshot", "true")).lower() != "true":
        snap_id = str(params.get("FinalDBSnapshotIdentifier", f"{db_id}-final"))
        _make_snapshot(store, db, snap_id, snapshot_type="automated", captured=params.get(_SNAPSHOT_DATA))
    source_id = db.get("read_replica_source_db_instance_identifier")
    if source_id:
        source = store.get_instance(source_id)
        if source:
            source["read_replica_db_instance_identifiers"] = [
                r for r in source.get("read_replica_db_instance_identifiers", []) if r != db_id]
    db = dict(db)
    db["db_instance_status"] = "deleting"
    store.drop_instance(db_id)
    store.mirror_delete_instance(db_id)
    store.persist()
    _log_event(store, db_id, "db-instance", f"DB instance {db_id} deleted.", ["deletion"], msg_store)
    return _success("DeleteDBInstance", _db_instance_xml(db))


_SNAPSHOT_DATA = "__vyomi_snapshot_data"   # adispatch() pre-captures async engines' tables under this key


def _capture_snapshot_data(store: SqlStore, db: dict, captured=None) -> dict:
    """The instance's tables at snapshot time (what StartExportTask exports). Sync
    engines are read here; an async engine (PGlite) is read by adispatch() first and
    handed in as `captured` — the sync path can't await it, so it records why not."""
    try:
        from core import sql_store as _sq
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import sql_store as _sq  # type: ignore
    dialect = _sq.engine_dialect(store)
    out = {"dialect": dialect, "schema": _sq.default_schema(dialect),
           "database": db.get("db_name") or db["db_instance_identifier"]}
    if captured is not None:
        out["tables"] = captured
        return out
    if _sq.is_async_engine(store):
        return {}
    try:
        out["tables"] = _sq.dump_tables(store, db["db_instance_identifier"])
    except Exception:   # no engine available (e.g. sqlite3 not loaded) — no data to snapshot
        return {}
    return out


def _make_snapshot(store: SqlStore, db: dict, snap_id: str, snapshot_type: str = "manual",
                   captured=None) -> dict:
    data = _capture_snapshot_data(store, db, captured)
    snap = {
        "db_snapshot_identifier": snap_id,
        "db_instance_identifier": db["db_instance_identifier"],
        "status": "available",
        "engine": db.get("engine", "postgres"),
        "engine_version": db.get("engine_version", "16.4"),
        "allocated_storage": db.get("allocated_storage", 20),
        "snapshot_type": snapshot_type,
        "created": _now(),
        "db_snapshot_arn": _snapshot_arn(store, snap_id),
    }
    if data:
        snap["data"] = data
    store.put_snapshot(snap_id, snap)
    return snap


def _create_db_snapshot(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    snap_id = str(params.get("DBSnapshotIdentifier", "")).strip()
    if not snap_id:
        raise RdsError("InvalidParameterValue", "DBSnapshotIdentifier is required.", 400)
    if store.get_snapshot(snap_id):
        raise RdsError("DBSnapshotAlreadyExists", f"Snapshot {snap_id} already exists.", 400)
    snap = _make_snapshot(store, db, snap_id, snapshot_type="manual", captured=params.get(_SNAPSHOT_DATA))
    tags = _tags_from_params(params)
    if tags:
        store.set_tags(_snapshot_arn(store, snap_id), tags)
    store.persist()
    _log_event(store, db["db_instance_identifier"], "db-instance", f"Snapshot {snap_id} created.", ["backup"], msg_store)
    return _success("CreateDBSnapshot", _db_snapshot_xml(snap))


def _delete_db_snapshot(store: SqlStore, params: dict) -> RdsResponse:
    snap_id = str(params.get("DBSnapshotIdentifier", "")).strip()
    snap = store.get_snapshot(snap_id)
    if not snap:
        raise RdsError("DBSnapshotNotFound", f"Snapshot {snap_id} not found.", 404)
    store.drop_snapshot(snap_id)
    store.persist()
    return _success("DeleteDBSnapshot", _db_snapshot_xml(snap))


def _restore_db_instance_from_db_snapshot(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    snap_id = str(params.get("DBSnapshotIdentifier", "")).strip()
    snap = store.get_snapshot(snap_id)
    if not snap:
        raise RdsError("DBSnapshotNotFound", f"Snapshot {snap_id} not found.", 404)
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    if not db_id:
        raise RdsError("InvalidParameterValue", "DBInstanceIdentifier is required.", 400)
    if store.instance_exists(db_id):
        raise RdsError("DBInstanceAlreadyExists", f"DBInstance {db_id} already exists.", 400)
    engine = snap.get("engine", "postgres")
    record = {
        "db_instance_identifier": db_id,
        "db_instance_class": str(params.get("DBInstanceClass", "db.t3.micro")),
        "engine": engine,
        "engine_version": snap.get("engine_version", "16.4"),
        "db_instance_status": "available",
        "master_username": "admin",
        "master_user_password": "",
        "allocated_storage": snap.get("allocated_storage", 20),
        "storage_type": str(params.get("StorageType", "gp3")),
        "availability_zone": str(params.get("AvailabilityZone", "us-east-1a")),
        "multi_az": str(params.get("MultiAZ", "false")).lower() == "true",
        "publicly_accessible": str(params.get("PubliclyAccessible", "false")).lower() == "true",
        "backup_retention_period": 7,
        "endpoint_address": f"{db_id}.nano-rds.local",
        "endpoint_port": _engine_port(engine),
        "db_instance_arn": _instance_arn(store, db_id),
        "db_subnet_group_name": str(params.get("DBSubnetGroupName", "default")),
        "db_parameter_group_name": "default",
        "vpc_security_group_ids": ["sg-default"],
        "deletion_protection": False,
        "created": _now(),
        "updated": _now(),
        "runtime_backend": "sqlite",
        "restored_from": snap_id,
    }
    store.put_instance(db_id, record)
    store.mirror_create_instance(db_id, record)
    store.persist()
    _log_event(store, db_id, "db-instance", f"DB instance {db_id} restored from snapshot {snap_id}.", ["creation"], msg_store)
    return _success("RestoreDBInstanceFromDBSnapshot", _db_instance_xml(record))


def _describe_db_snapshots(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    snaps = [store.get_snapshot(s) for s in store.snapshot_ids()]
    if db_id:
        snaps = [s for s in snaps if s.get("db_instance_identifier") == db_id]
    inner = "<DBSnapshots>" + "".join(_db_snapshot_xml(s) for s in snaps) + "</DBSnapshots>"
    return _success("DescribeDBSnapshots", inner)


_PARAM_FAMILIES = {
    "mysql": {
        "max_connections": ("151", "integer", "1-100000"),
        "innodb_buffer_pool_size": ("134217728", "integer", "5242880-18446744073709551615"),
        "slow_query_log": ("0", "boolean", "0,1"),
        "character_set_server": ("utf8mb4", "string", ""),
    },
    "postgres": {
        "max_connections": ("100", "integer", "1-262143"),
        "shared_buffers": ("16384", "integer", "16-1073741823"),
        "log_min_duration_statement": ("-1", "integer", "-1-2147483647"),
        "rds.force_ssl": ("1", "boolean", "0,1"),
    },
}


def _default_parameters(family: str) -> dict:
    key = "mysql" if any(s in family.lower() for s in ("mysql", "maria")) else "postgres"
    return {name: {"parameter_value": val, "data_type": dtype, "allowed_values": allowed,
                   "is_modifiable": True, "source": "engine-default", "apply_type": "dynamic",
                   "description": f"{name} (engine default)"}
            for name, (val, dtype, allowed) in _PARAM_FAMILIES[key].items()}


# ── DB subnet groups ─────────────────────────────────────────────────────────
def _create_db_subnet_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBSubnetGroupName", "")).strip()
    if not name:
        raise RdsError("InvalidParameterValue", "DBSubnetGroupName is required.", 400)
    if store.get_subnet_group(name):
        raise RdsError("DBSubnetGroupAlreadyExists", f"DB subnet group {name} already exists.", 400)
    subnet_ids = _members(params, "SubnetIds")
    if not subnet_ids:
        raise RdsError("InvalidParameterValue", "SubnetIds is required.", 400)
    azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
    record = {
        "db_subnet_group_name": name,
        "db_subnet_group_description": str(params.get("DBSubnetGroupDescription", "")),
        "vpc_id": str(params.get("VpcId", "vpc-default")),
        "subnet_group_status": "Complete",
        "subnets": [{"subnet_identifier": sid, "availability_zone": azs[i % len(azs)]}
                   for i, sid in enumerate(subnet_ids)],
        "db_subnet_group_arn": _subnet_group_arn(store, name),
        "created": _now(),
    }
    store.put_subnet_group(name, record)
    store.persist()
    return _success("CreateDBSubnetGroup", _subnet_group_xml(record))


def _describe_db_subnet_groups(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBSubnetGroupName", "")).strip()
    if name:
        if not store.get_subnet_group(name):
            raise RdsError("DBSubnetGroupNotFoundFault", f"DB subnet group {name} not found.", 404)
        names = [name]
    else:
        names = store.subnet_group_names()
    inner = "<DBSubnetGroups>" + "".join(_subnet_group_xml(store.get_subnet_group(n)) for n in names) + "</DBSubnetGroups>"
    return _success("DescribeDBSubnetGroups", inner)


def _delete_db_subnet_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBSubnetGroupName", "")).strip()
    if not store.get_subnet_group(name):
        raise RdsError("DBSubnetGroupNotFoundFault", f"DB subnet group {name} not found.", 404)
    store.drop_subnet_group(name)
    store.persist()
    return _success("DeleteDBSubnetGroup", "")


# ── DB parameter groups ──────────────────────────────────────────────────────
def _create_db_parameter_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBParameterGroupName", "")).strip()
    if not name:
        raise RdsError("InvalidParameterValue", "DBParameterGroupName is required.", 400)
    if store.get_parameter_group(name):
        raise RdsError("DBParameterGroupAlreadyExists", f"DB parameter group {name} already exists.", 400)
    family = str(params.get("DBParameterGroupFamily", "postgres16"))
    record = {
        "db_parameter_group_name": name,
        "db_parameter_group_family": family,
        "description": str(params.get("Description", "")),
        "type": str(params.get("Type", "DB Parameter Group")),
        "db_parameter_group_arn": _parameter_group_arn(store, name),
        "parameters": _default_parameters(family),
    }
    store.put_parameter_group(name, record)
    store.persist()
    return _success("CreateDBParameterGroup", _parameter_group_xml(record))


def _describe_db_parameter_groups(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBParameterGroupName", "")).strip()
    if name:
        if not store.get_parameter_group(name):
            raise RdsError("DBParameterGroupNotFound", f"DB parameter group {name} not found.", 404)
        names = [name]
    else:
        names = store.parameter_group_names()
    inner = "<DBParameterGroups>" + "".join(_parameter_group_xml(store.get_parameter_group(n)) for n in names) + "</DBParameterGroups>"
    return _success("DescribeDBParameterGroups", inner)


def _delete_db_parameter_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBParameterGroupName", "")).strip()
    if not store.get_parameter_group(name):
        raise RdsError("DBParameterGroupNotFound", f"DB parameter group {name} not found.", 404)
    store.drop_parameter_group(name)
    store.persist()
    return _success("DeleteDBParameterGroup", "")


def _describe_db_parameters(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBParameterGroupName", "")).strip()
    pg = store.get_parameter_group(name)
    if not pg:
        raise RdsError("DBParameterGroupNotFound", f"DB parameter group {name} not found.", 404)
    inner = "<Parameters>" + "".join(_parameter_xml(n, p) for n, p in sorted(pg["parameters"].items())) + "</Parameters>"
    return _success("DescribeDBParameters", inner)


def _modify_db_parameter_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBParameterGroupName", "")).strip()
    pg = store.get_parameter_group(name)
    if not pg:
        raise RdsError("DBParameterGroupNotFound", f"DB parameter group {name} not found.", 404)
    for item in _members(params, "Parameters"):
        pname = item.get("ParameterName")
        if not pname:
            continue
        p = pg["parameters"].setdefault(pname, {"data_type": "string", "allowed_values": "",
                                                "is_modifiable": True, "apply_type": "dynamic", "description": ""})
        p["parameter_value"] = item.get("ParameterValue", "")
        p["source"] = "user"
    store.persist()
    return _success("ModifyDBParameterGroup", _el("DBParameterGroupName", name))


# ── tags (ListTagsForResource / AddTagsToResource / RemoveTagsFromResource) ──
def _list_tags_for_resource(store: SqlStore, params: dict) -> RdsResponse:
    arn = str(params.get("ResourceName", "")).strip()
    return _success("ListTagsForResource", _tag_list_xml(store.get_tags(arn)))


def _add_tags_to_resource(store: SqlStore, params: dict) -> RdsResponse:
    arn = str(params.get("ResourceName", "")).strip()
    tags = store.get_tags(arn)
    tags.update(_tags_from_params(params))
    store.set_tags(arn, tags)
    store.persist()
    return _success("AddTagsToResource", "")


def _remove_tags_from_resource(store: SqlStore, params: dict) -> RdsResponse:
    arn = str(params.get("ResourceName", "")).strip()
    tags = store.get_tags(arn)
    for key in _members(params, "TagKeys"):
        tags.pop(key, None)
    store.set_tags(arn, tags)
    store.persist()
    return _success("RemoveTagsFromResource", "")


# ── events ────────────────────────────────────────────────────────────────
def _describe_events(store: SqlStore, params: dict) -> RdsResponse:
    source_id = str(params.get("SourceIdentifier", "")).strip()
    events = store.list_events()
    if source_id:
        events = [e for e in events if e.get("source_identifier") == source_id]
    events = sorted(events, key=lambda e: e.get("date", ""), reverse=True)
    inner = "<Events>" + "".join(_event_xml(e) for e in events) + "</Events>"
    return _success("DescribeEvents", inner)


# ── RDS Proxy ────────────────────────────────────────────────────────────────
def _create_db_proxy(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBProxyName", "")).strip()
    if not name:
        raise RdsError("InvalidParameterValue", "DBProxyName is required.", 400)
    if store.get_proxy(name):
        raise RdsError("DBProxyAlreadyExistsFault", f"DB proxy {name} already exists.", 400)
    record = {
        "db_proxy_name": name,
        "db_proxy_arn": _proxy_arn(store, name),
        "engine_family": str(params.get("EngineFamily", "POSTGRESQL")),
        "status": "available",
        "created": _now(),
    }
    store.put_proxy(name, record)
    store.persist()
    return _success("CreateDBProxy", _proxy_xml(record))


def _describe_db_proxies(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBProxyName", "")).strip()
    if name:
        if not store.get_proxy(name):
            raise RdsError("DBProxyNotFoundFault", f"DB proxy {name} not found.", 404)
        names = [name]
    else:
        names = store.proxy_names()
    inner = "<DBProxies>" + "".join(_proxy_xml(store.get_proxy(n)) for n in names) + "</DBProxies>"
    return _success("DescribeDBProxies", inner)


def _delete_db_proxy(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("DBProxyName", "")).strip()
    px = store.get_proxy(name)
    if not px:
        raise RdsError("DBProxyNotFoundFault", f"DB proxy {name} not found.", 404)
    store.drop_proxy(name)
    store.persist()
    return _success("DeleteDBProxy", _proxy_xml(px))


# ── option groups ────────────────────────────────────────────────────────────
def _create_option_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("OptionGroupName", "")).strip()
    if not name:
        raise RdsError("InvalidParameterValue", "OptionGroupName is required.", 400)
    if store.get_option_group(name):
        raise RdsError("OptionGroupAlreadyExistsFault", f"Option group {name} already exists.", 400)
    record = {
        "option_group_name": name,
        "option_group_description": str(params.get("OptionGroupDescription", "")),
        "engine_name": str(params.get("EngineName", "mysql")),
        "major_engine_version": str(params.get("MajorEngineVersion", "")),
        "option_group_arn": _option_group_arn(store, name),
    }
    store.put_option_group(name, record)
    store.persist()
    return _success("CreateOptionGroup", _option_group_xml(record))


def _describe_option_groups(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("OptionGroupName", "")).strip()
    if name:
        if not store.get_option_group(name):
            raise RdsError("OptionGroupNotFoundFault", f"Option group {name} not found.", 404)
        names = [name]
    else:
        names = store.option_group_names()
    inner = "<OptionGroupsList>" + "".join(_option_group_xml(store.get_option_group(n)) for n in names) + "</OptionGroupsList>"
    return _success("DescribeOptionGroups", inner)


def _delete_option_group(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("OptionGroupName", "")).strip()
    if not store.get_option_group(name):
        raise RdsError("OptionGroupNotFoundFault", f"Option group {name} not found.", 404)
    store.drop_option_group(name)
    store.persist()
    return _success("DeleteOptionGroup", "")


# ── event subscriptions ──────────────────────────────────────────────────────
def _create_event_subscription(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("SubscriptionName", "")).strip()
    if not name:
        raise RdsError("InvalidParameterValue", "SubscriptionName is required.", 400)
    if store.get_event_subscription(name):
        raise RdsError("SubscriptionAlreadyExistFault", f"Event subscription {name} already exists.", 400)
    record = {
        "cust_subscription_id": name,
        "sns_topic_arn": str(params.get("SnsTopicArn", "")),
        "source_type": str(params.get("SourceType", "db-instance")),
        "event_categories": _members(params, "EventCategories"),
        "enabled": str(params.get("Enabled", "true")).lower() == "true",
        "status": "active",
        "customer_aws_id": store.account_id,
        "created": _now(),
    }
    store.put_event_subscription(name, record)
    store.persist()
    return _success("CreateEventSubscription", _event_subscription_xml(record))


def _describe_event_subscriptions(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("SubscriptionName", "")).strip()
    if name:
        if not store.get_event_subscription(name):
            raise RdsError("SubscriptionNotFoundFault", f"Event subscription {name} not found.", 404)
        names = [name]
    else:
        names = store.event_subscription_names()
    inner = ("<EventSubscriptionsList>"
             + "".join(_event_subscription_xml(store.get_event_subscription(n)) for n in names)
             + "</EventSubscriptionsList>")
    return _success("DescribeEventSubscriptions", inner)


def _delete_event_subscription(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("SubscriptionName", "")).strip()
    es = store.get_event_subscription(name)
    if not es:
        raise RdsError("SubscriptionNotFoundFault", f"Event subscription {name} not found.", 404)
    store.drop_event_subscription(name)
    store.persist()
    return _success("DeleteEventSubscription", _event_subscription_xml(es))


# ── reserved DB instances (a purchase is just a commitment record — no real
# billing system is needed to track that one exists; the offering catalog and
# actual payment are genuinely out of Vyomi's scope) ────────────────────────
def _purchase_reserved_db_instance(store: SqlStore, params: dict) -> RdsResponse:
    reservation_id = str(params.get("ReservedDBInstanceId") or f"ri-{uuid.uuid4().hex[:12]}")
    if store.get_reserved_instance(reservation_id):
        raise RdsError("ReservedDBInstanceAlreadyExistsFault",
                       f"Reserved DB instance {reservation_id} already exists.", 400)
    record = {
        "reserved_db_instance_id": reservation_id,
        "lease_id": str(uuid.uuid4()),
        "offering_id": str(params.get("ReservedDBInstancesOfferingId", "")),
        "product_description": str(params.get("ProductDescription", "rds")),
        "db_instance_class": str(params.get("DBInstanceClass", "db.t3.micro")),
        "offering_type": str(params.get("OfferingType", "No Upfront")),
        "state": "active",
        "multi_az": str(params.get("MultiAZ", "false")).lower() == "true",
        "db_instance_count": _int(params, "DBInstanceCount", 1),
        "start_time": _now(),
    }
    store.put_reserved_instance(reservation_id, record)
    store.persist()
    return _success("PurchaseReservedDBInstancesOffering", _reserved_instance_xml(record))


def _describe_reserved_db_instances(store: SqlStore, params: dict) -> RdsResponse:
    reservation_id = str(params.get("ReservedDBInstanceId", "")).strip()
    if reservation_id:
        ri = store.get_reserved_instance(reservation_id)
        if not ri:
            raise RdsError("ReservedDBInstanceNotFoundFault",
                           f"Reserved DB instance {reservation_id} not found.", 404)
        ids = [reservation_id]
    else:
        ids = store.reserved_instance_ids()
    inner = ("<ReservedDBInstances>" + "".join(_reserved_instance_xml(store.get_reserved_instance(i)) for i in ids)
             + "</ReservedDBInstances>")
    return _success("DescribeReservedDBInstances", inner)


def _describe_db_instance_automated_backups(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    ids = [db_id] if db_id else store.instance_ids()
    dbs = [store.get_instance(i) for i in ids if store.get_instance(i)
          and store.get_instance(i).get("backup_retention_period", 0) > 0]
    inner = ("<DBInstanceAutomatedBackups>" + "".join(_automated_backup_xml(d) for d in dbs)
             + "</DBInstanceAutomatedBackups>")
    return _success("DescribeDBInstanceAutomatedBackups", inner)


# ── exports to S3 — the snapshot's REAL table data, as Apache Parquet, written into
# the SIMULATOR's own S3 store (the same s3_object_core.put_object every PutObject
# uses — nothing leaves the simulator), in AWS's layout:
#
#   <prefix>/<task>/export_info_<task>.json
#   <prefix>/<task>/export_tables_info_<task>_from_1_to_<N>.json
#   <prefix>/<task>/<database>/<schema>.<table>/part-00000-<n>.gz.parquet
#
# The Parquet bytes come from a PLATFORM-supplied writer `parquet_writer(schema,
# columns) -> bytes` (this core stays Pyodide-pure): pyarrow offline
# (core/parquet_pyarrow.py, installed by the appliance), parquet-wasm in the browser
# (wasm/parquet-loader.js, bridged below). No writer, or a writer that fails, makes
# the task FAIL with a FailureCause — never a silent fallback to another format. A
# bucket that doesn't exist fails the task the same way. ─
_PARQUET_WRITER = None


def set_parquet_writer(fn) -> None:
    """Install the platform's Parquet writer: fn(schema, columns) -> bytes (or an
    awaitable of bytes). schema = [{"name", "type"}] with types from
    core.sql_store.ARROW_TYPES; columns = column-major value lists."""
    global _PARQUET_WRITER
    _PARQUET_WRITER = fn


def parquet_spec_json(schema: list, columns: list) -> str:
    """The JSON the browser Parquet engine takes (binary cells tagged base64)."""
    import base64 as _b64
    cols = [[({"$b64": _b64.b64encode(v).decode()} if isinstance(v, (bytes, bytearray)) else v) for v in col]
            for col in columns]
    return json.dumps({"schema": schema, "columns": cols})


async def _pyodide_parquet_writer(schema: list, columns: list) -> bytes:
    """Browser writer: globalThis.__nano_parquet_write (wasm/parquet/parquet-loader.js —
    vendored parquet-wasm + apache-arrow, lazy-loaded on the first export)."""
    from js import globalThis  # lazy: Pyodide-only
    fn = getattr(globalThis, "__nano_parquet_write", None)
    if fn is None:
        raise RuntimeError("the in-browser Parquet engine (parquet-wasm) is not installed in this context")
    out = await fn(parquet_spec_json(schema, columns))
    return bytes(out.to_py()) if hasattr(out, "to_py") else bytes(out)


def _resolve_parquet_writer():
    if _PARQUET_WRITER is not None:
        return _PARQUET_WRITER
    import sys
    if sys.platform == "emscripten":
        return _pyodide_parquet_writer
    return None


def _snapshot_id_of(source_arn: str) -> str:
    return source_arn.rsplit(":", 1)[-1] if ":snapshot:" in source_arn else ""


def _export_only_match(filters: list, database: str, schema: str, table: str) -> bool:
    if not filters:
        return True
    names = {database, f"{database}.{schema}", f"{database}.{schema}.{table}", f"{schema}.{table}", table}
    return any(f in names for f in filters)


def _export_begin(store: SqlStore, params: dict, s3_store) -> tuple:
    """Validate + build the task record and the list of files to write.
    Returns (record, files, failure_cause); files = [(key, kind, payload)] with kind
    "parquet" (payload = (schema, columns)) or "json" (payload = bytes)."""
    task_id = str(params.get("ExportTaskIdentifier", "")).strip()
    if not task_id:
        raise RdsError("InvalidParameterValue", "ExportTaskIdentifier is required.", 400)
    if store.get_export_task(task_id):
        raise RdsError("ExportTaskAlreadyExistsFault", f"Export task {task_id} already exists.", 400)
    source_arn = str(params.get("SourceArn", "")).strip()
    bucket = str(params.get("S3BucketName", "")).strip()
    if not source_arn:
        raise RdsError("InvalidParameterValue", "SourceArn is required.", 400)
    if not bucket:
        raise RdsError("InvalidParameterValue", "S3BucketName is required.", 400)
    snap_id = _snapshot_id_of(source_arn)
    snap = store.get_snapshot(snap_id) if snap_id else None
    if snap is None:
        raise RdsError("DBSnapshotNotFound", f"DBSnapshot {snap_id or source_arn} not found.", 404)
    prefix = str(params.get("S3Prefix", "")).strip().strip("/")
    export_only = _members(params, "ExportOnly")
    record = {
        "export_task_identifier": task_id,
        "source_arn": source_arn,
        "source_type": "CLUSTER_SNAPSHOT" if ":cluster-snapshot:" in source_arn else "SNAPSHOT",
        "s3_bucket": bucket,
        "s3_prefix": prefix,
        "iam_role_arn": str(params.get("IamRoleArn", "")),
        "kms_key_id": str(params.get("KmsKeyId", "")),
        "export_only": export_only,
        "snapshot_time": snap.get("created", ""),
        "status": "COMPLETE",
        "failure_cause": "",
        "percent_progress": 100,
        "total_extracted_data_in_gb": 0,
        "created": _now(),
        "task_end_time": _now(),
    }
    if s3_store is None:
        return record, [], "No S3 store is attached to this RDS engine; nothing can be exported."
    if not s3_store.bucket_exists(bucket):
        return record, [], f"Unable to write to s3://{bucket}/: the bucket does not exist."
    data = snap.get("data")
    if not isinstance(data, dict):
        return record, [], (f"DB snapshot {snap_id} carries no table data (it was taken before this "
                            "engine captured snapshot contents); take a new snapshot and export that.")
    try:
        from core import sql_store as _sq
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import sql_store as _sq  # type: ignore
    dialect = data.get("dialect", "sqlite")
    database = data.get("database") or snap.get("db_instance_identifier", "db")
    schema_name = data.get("schema") or _sq.default_schema(dialect)
    base = f"{prefix}/{task_id}" if prefix else task_id
    files, tables_info = [], []
    for t in data.get("tables") or []:
        if not _export_only_match(export_only, database, schema_name, t["name"]):
            continue
        schema, columns = _sq.parquet_columns(t, dialect)
        part = uuid.uuid4().hex[:8]
        target = f"{database}/{schema_name}.{t['name']}"
        files.append((f"{base}/{target}/part-00000-{part}.gz.parquet", "parquet", (schema, columns)))
        tables_info.append({"tableStatistics": {"extractionStartTime": record["created"],
                                                "extractionEndTime": record["task_end_time"],
                                                "partitioningInfo": {"numberOfPartitions": 1,
                                                                     "numberOfCompletedPartitions": 1}},
                            "schemaMetadata": {"originalTypeMappings": [
                                {"columnName": c["name"], "originalType": c.get("decl", ""),
                                 "expectedExportedType": s["type"], "originalCharMaxLength": 0,
                                 "originalNumPrecision": 0, "originalDateTimePrecision": 0}
                                for c, s in zip(t.get("columns") or [], schema)]},
                            "status": "COMPLETE", "sizeGB": 0.0, "target": target,
                            "rows": len(t.get("rows") or [])})
    n = max(1, len(tables_info))
    info = {"exportTaskIdentifier": task_id, "sourceArn": source_arn, "exportOnly": export_only,
            "snapshotTime": record["snapshot_time"], "taskStartTime": record["created"],
            "taskEndTime": record["task_end_time"], "s3Bucket": bucket, "s3Prefix": prefix,
            "exportedFilesPath": base, "iamRoleArn": record["iam_role_arn"], "kmsKeyId": record["kms_key_id"],
            "status": "COMPLETE", "percentProgress": 100, "totalExportedDataInGB": 0.0,
            "format": "parquet", "compression": "gzip"}
    files.append((f"{base}/export_info_{task_id}.json", "json", json.dumps(info, indent=2).encode()))
    files.append((f"{base}/export_tables_info_{task_id}_from_1_to_{n}.json", "json",
                  json.dumps({"perTableStatus": tables_info}, indent=2).encode()))
    return record, files, ""


def _put_export_object(s3_store, bucket: str, key: str, body: bytes, ctype: str) -> str:
    try:
        from core import s3_object_core as s3c
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import s3_object_core as s3c  # type: ignore
    r = s3c.put_object(s3_store, bucket, key, body, {"content-type": ctype})
    if r.status != 200:
        return f"Unable to write to s3://{bucket}/{key}: the bucket does not exist."
    return ""


def _export_finish(store: SqlStore, record: dict, failure_cause: str, written: int) -> RdsResponse:
    if failure_cause:
        record["status"] = "FAILED"
        record["failure_cause"] = failure_cause
    record["total_extracted_data_in_gb"] = int(written // (1024 ** 3))   # AWS reports whole GB
    record["exported_bytes"] = written
    record["task_end_time"] = _now()
    store.put_export_task(record["export_task_identifier"], record)
    store.persist()
    return _success("StartExportTask", _export_task_members(record))


def _export_task_members(record: dict) -> str:
    """StartExportTask / CancelExportTask return the ExportTask's members DIRECTLY in
    the Result element (botocore's shape), unlike DescribeExportTasks' <ExportTask> list."""
    xml = _export_task_xml(record)
    return xml[len("<ExportTask>"):-len("</ExportTask>")]


def _start_export_task(store: SqlStore, params: dict, s3_store=None) -> RdsResponse:
    """Sync path (offline: pyarrow). An async-only writer (the browser's parquet-wasm)
    needs adispatch(); here it fails the task instead of blocking."""
    record, files, cause = _export_begin(store, params, s3_store)
    written = 0
    writer = _resolve_parquet_writer() if not cause else None
    if not cause and writer is None and any(k == "parquet" for _, k, _ in files):
        cause = "The Parquet engine is not available on this platform; the export was not written."
    for key, kind, payload in ([] if cause else files):
        if kind == "parquet":
            try:
                body = writer(*payload)
                if hasattr(body, "__await__"):
                    if hasattr(body, "close"):
                        body.close()
                    raise RuntimeError("the Parquet engine here is asynchronous; use the async dispatch path")
                body = bytes(body)
            except Exception as e:  # noqa: BLE001 — surfaced as the task's FailureCause
                cause = f"Parquet engine failed: {e}"
                break
            ctype = "application/vnd.apache.parquet"
        else:
            body, ctype = payload, "application/json"
        cause = _put_export_object(s3_store, record["s3_bucket"], key, body, ctype)
        if cause:
            break
        written += len(body)
    return _export_finish(store, record, cause, written)


async def _astart_export_task(store: SqlStore, params: dict, s3_store=None) -> RdsResponse:
    record, files, cause = _export_begin(store, params, s3_store)
    written = 0
    writer = _resolve_parquet_writer() if not cause else None
    if not cause and writer is None and any(k == "parquet" for _, k, _ in files):
        cause = "The Parquet engine is not available on this platform; the export was not written."
    for key, kind, payload in ([] if cause else files):
        if kind == "parquet":
            try:
                body = writer(*payload)
                if hasattr(body, "__await__"):
                    body = await body
                body = bytes(body)
            except Exception as e:  # noqa: BLE001
                cause = f"Parquet engine failed: {e}"
                break
            ctype = "application/vnd.apache.parquet"
        else:
            body, ctype = payload, "application/json"
        cause = _put_export_object(s3_store, record["s3_bucket"], key, body, ctype)
        if cause:
            break
        written += len(body)
    return _export_finish(store, record, cause, written)


def _cancel_export_task(store: SqlStore, params: dict) -> RdsResponse:
    task_id = str(params.get("ExportTaskIdentifier", "")).strip()
    task = store.get_export_task(task_id)
    if not task:
        raise RdsError("ExportTaskNotFoundFault", f"Export task {task_id} not found.", 404)
    task = dict(task)
    task["status"] = "CANCELED"
    store.drop_export_task(task_id)
    store.persist()
    return _success("CancelExportTask", _export_task_members(task))


def _describe_export_tasks(store: SqlStore, params: dict) -> RdsResponse:
    task_id = str(params.get("ExportTaskIdentifier", "")).strip()
    if task_id:
        task = store.get_export_task(task_id)
        if not task:
            raise RdsError("ExportTaskNotFoundFault", f"Export task {task_id} not found.", 404)
        ids = [task_id]
    else:
        ids = store.export_task_ids()
    inner = "<ExportTasks>" + "".join(_export_task_xml(store.get_export_task(i)) for i in ids) + "</ExportTasks>"
    return _success("DescribeExportTasks", inner)


# ── zero-ETL integrations (the integration's existence/status is a metadata
# record; the real cross-service Redshift data pipe is out of Vyomi's scope) ─
def _create_integration(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("IntegrationName", "")).strip()
    if not name:
        raise RdsError("InvalidParameterValue", "IntegrationName is required.", 400)
    if store.get_integration(name):
        raise RdsError("IntegrationConflictOperationFault", f"Integration {name} already exists.", 400)
    record = {
        "integration_name": name,
        "integration_arn": _integration_arn(store, name),
        "source_arn": str(params.get("SourceArn", "")),
        "target_arn": str(params.get("TargetArn", "")),
        "status": "active",
        "created": _now(),
    }
    store.put_integration(name, record)
    store.persist()
    return _success("CreateIntegration", _integration_xml(record))


def _delete_integration(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("IntegrationName", "")).strip()
    ig = store.get_integration(name)
    if not ig:
        raise RdsError("IntegrationNotFoundFault", f"Integration {name} not found.", 404)
    store.drop_integration(name)
    store.persist()
    return _success("DeleteIntegration", _integration_xml(ig))


def _describe_integrations(store: SqlStore, params: dict) -> RdsResponse:
    name = str(params.get("IntegrationName", "")).strip()
    if name:
        if not store.get_integration(name):
            raise RdsError("IntegrationNotFoundFault", f"Integration {name} not found.", 404)
        names = [name]
    else:
        names = store.integration_names()
    inner = "<Integrations>" + "".join(_integration_xml(store.get_integration(n)) for n in names) + "</Integrations>"
    return _success("DescribeIntegrations", inner)


# ── RDS Custom engine versions (registering install media is a metadata
# record; the customer-managed EC2 instance RDS Custom actually runs on is
# out of Vyomi's scope) ──────────────────────────────────────────────────
def _create_custom_db_engine_version(store: SqlStore, params: dict) -> RdsResponse:
    engine = str(params.get("Engine", "")).strip()
    engine_version = str(params.get("EngineVersion", "")).strip()
    if not engine or not engine_version:
        raise RdsError("InvalidParameterValue", "Engine and EngineVersion are required.", 400)
    cev_id = f"{engine}-{engine_version}"
    if store.get_custom_engine_version(cev_id):
        raise RdsError("CustomDBEngineVersionAlreadyExistsFault",
                       f"Custom engine version {cev_id} already exists.", 400)
    record = {
        "engine": engine, "engine_version": engine_version,
        "description": str(params.get("Description", "")),
        "status": "available", "created": _now(),
    }
    store.put_custom_engine_version(cev_id, record)
    store.persist()
    return _success("CreateCustomDBEngineVersion", _custom_engine_version_xml(record))


def _delete_custom_db_engine_version(store: SqlStore, params: dict) -> RdsResponse:
    cev_id = f"{params.get('Engine', '')}-{params.get('EngineVersion', '')}"
    cev = store.get_custom_engine_version(cev_id)
    if not cev:
        raise RdsError("CustomDBEngineVersionNotFoundFault", f"Custom engine version {cev_id} not found.", 404)
    store.drop_custom_engine_version(cev_id)
    store.persist()
    return _success("DeleteCustomDBEngineVersion", _custom_engine_version_xml(cev))


def _describe_db_engine_versions(store: SqlStore, params: dict) -> RdsResponse:
    # Scope: only the custom engine versions Vyomi itself registered — the full
    # standard-engine catalogue (every postgres/mysql/... version AWS ships) is
    # not modeled.
    ids = store.custom_engine_version_ids()
    inner = ("<DBEngineVersions>" + "".join(_custom_engine_version_xml(store.get_custom_engine_version(i)) for i in ids)
             + "</DBEngineVersions>")
    return _success("DescribeDBEngineVersions", inner)


# ── DB recommendations (real RDS generates these from its own monitoring;
# Vyomi has no such engine, so it derives the same two advisories AWS gives
# from the instance's own live configuration — a real check, not canned data) ─
def _recommendations_for(store: SqlStore) -> list[dict]:
    recs = []
    for db_id in store.instance_ids():
        db = store.get_instance(db_id)
        arn = db.get("db_instance_arn", _instance_arn(store, db_id))
        if not db.get("multi_az"):
            recs.append({
                "recommendation_id": f"rec-multiaz-{db_id}",
                "severity": "medium", "category": "availability",
                "detection": "Single-AZ deployment",
                "recommendation": "Enable Multi-AZ deployment for high availability.",
                "impact": "Availability", "resource_arn": arn, "created": db.get("created", ""),
            })
        if db.get("ca_certificate_identifier", DEFAULT_CA) != DEFAULT_CA:
            recs.append({
                "recommendation_id": f"rec-cacert-{db_id}",
                "severity": "high", "category": "security",
                "detection": "CA certificate nearing expiration",
                "recommendation": f"Update the CA certificate (currently {db.get('ca_certificate_identifier')}).",
                "impact": "Security", "resource_arn": arn, "created": db.get("created", ""),
            })
        if not db.get("backup_retention_period"):
            recs.append({
                "recommendation_id": f"rec-nobackup-{db_id}",
                "severity": "high", "category": "reliability",
                "detection": "Automated backups disabled",
                "recommendation": "Set a backup retention period greater than 0 to enable automated backups.",
                "impact": "Reliability", "resource_arn": arn, "created": db.get("created", ""),
            })
        if not db.get("deletion_protection"):
            recs.append({
                "recommendation_id": f"rec-delprot-{db_id}",
                "severity": "medium", "category": "reliability",
                "detection": "Deletion protection disabled",
                "recommendation": "Enable deletion protection to guard against accidental deletion.",
                "impact": "Reliability", "resource_arn": arn, "created": db.get("created", ""),
            })
    return recs


def _describe_db_recommendations(store: SqlStore, params: dict) -> RdsResponse:
    inner = ("<DBRecommendations>" + "".join(_db_recommendation_xml(r) for r in _recommendations_for(store))
             + "</DBRecommendations>")
    return _success("DescribeDBRecommendations", inner)


# ── rds.logs: DescribeDBLogFiles / DownloadDBLogFilePortion — real native RDS
# actions, backed by the SAME error-log ring buffer execute_sql/aexecute_sql
# append to on a genuine failed statement (see _append_error_log above). ──
def _log_file_name(db: dict) -> str:
    engine = str(db.get("engine", "postgres")).lower()
    if "mysql" in engine or "maria" in engine:
        return "error/mysql-error-running.log"
    return "error/postgresql.log"


def _describe_db_log_files(store: SqlStore, params: dict) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    lines = store.log_lines(db["db_instance_identifier"])
    size = sum(len(line.encode("utf-8")) + 1 for _, line in lines)
    last_written = int((lines[-1][0] if lines else 0) * 1000)
    inner = ("<DescribeDBLogFiles><DescribeDBLogFilesDetails>"
             + _el("LogFileName", _log_file_name(db)) + _el("LastWritten", last_written) + _el("Size", size)
             + "</DescribeDBLogFilesDetails></DescribeDBLogFiles>")
    return _success("DescribeDBLogFiles", inner)


def _download_db_log_file_portion(store: SqlStore, params: dict) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    lines = store.log_lines(db["db_instance_identifier"])
    try:
        start = max(0, int(params.get("Marker", "0") or "0"))
    except ValueError:
        start = 0
    chunk = lines[start:start + 200]
    text = "\n".join(line for _, line in chunk)
    pending = (start + len(chunk)) < len(lines)
    inner = (_el("LogFileData", text) + _el("Marker", start + len(chunk))
             + _el("AdditionalDataPending", "true" if pending else "false"))
    return _success("DownloadDBLogFilePortion", inner)


# ── rds.replication: read replicas (real, stateful linkage + synchronous
# write forwarding — see _replicate_write/_areplicate_write above) and
# Multi-AZ failover (RebootDBInstance ForceFailover genuinely swaps the
# instance's live AvailabilityZone, not just a stored flag). ──────────────
_AZ_LETTERS = "abcdef"


def _secondary_az(primary_az: str) -> str:
    """A different AZ letter in the same region — e.g. us-east-1a -> us-east-1b."""
    if primary_az and primary_az[-1] in _AZ_LETTERS:
        base, letter = primary_az[:-1], primary_az[-1]
        nxt = _AZ_LETTERS[(_AZ_LETTERS.index(letter) + 1) % len(_AZ_LETTERS)]
        return f"{base}{nxt}"
    return f"{primary_az}b" if primary_az else "us-east-1b"


def _create_db_instance_read_replica(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    source_id = str(params.get("SourceDBInstanceIdentifier", "")).strip()
    if not db_id:
        raise RdsError("InvalidParameterValue", "DBInstanceIdentifier is required.", 400)
    if store.instance_exists(db_id):
        raise RdsError("DBInstanceAlreadyExists", f"DBInstance {db_id} already exists.", 400)
    source = _require_instance(store, source_id)
    if source.get("read_replica_source_db_instance_identifier"):
        raise RdsError("InvalidParameterValue",
                       f"DB instance {source_id} is itself a read replica — cascading replicas are not supported.", 400)
    record = {
        "db_instance_identifier": db_id,
        "db_instance_class": str(params.get("DBInstanceClass", source.get("db_instance_class", "db.t3.micro"))),
        "engine": source.get("engine", "postgres"),
        "engine_version": source.get("engine_version", "16.4"),
        "db_instance_status": "available",
        "master_username": source.get("master_username", "admin"),
        "master_user_password": source.get("master_user_password", ""),
        "allocated_storage": source.get("allocated_storage", 20),
        "storage_type": source.get("storage_type", "gp3"),
        "availability_zone": str(params.get("AvailabilityZone", source.get("availability_zone", "us-east-1a"))),
        "multi_az": False,
        "publicly_accessible": str(params.get("PubliclyAccessible", "false")).lower() == "true",
        "backup_retention_period": 0,
        "endpoint_address": f"{db_id}.nano-rds.local",
        "endpoint_port": source.get("endpoint_port", _engine_port(source.get("engine", "postgres"))),
        "db_instance_arn": _instance_arn(store, db_id),
        "db_subnet_group_name": source.get("db_subnet_group_name", "default"),
        "db_parameter_group_name": source.get("db_parameter_group_name", "default"),
        "vpc_security_group_ids": list(source.get("vpc_security_group_ids", ["sg-default"])),
        "deletion_protection": False,
        "ca_certificate_identifier": source.get("ca_certificate_identifier", DEFAULT_CA),
        "created": _now(),
        "updated": _now(),
        "runtime_backend": "sqlite",
        "read_replica_source_db_instance_identifier": source_id,
        "read_replica_db_instance_identifiers": [],
    }
    store.put_instance(db_id, record)
    source.setdefault("read_replica_db_instance_identifiers", []).append(db_id)
    store.mirror_create_instance(db_id, record)
    store.persist()
    _log_event(store, db_id, "db-instance", f"DB instance {db_id} created as a read replica of {source_id}.", ["creation"], msg_store)
    return _success("CreateDBInstanceReadReplica", _db_instance_xml(record))


def _promote_read_replica(store: SqlStore, params: dict, msg_store=None) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    source_id = db.get("read_replica_source_db_instance_identifier")
    if not source_id:
        raise RdsError("InvalidDBInstanceState", "DB instance is not a read replica.", 400)
    source = store.get_instance(source_id)
    if source:
        source["read_replica_db_instance_identifiers"] = [
            r for r in source.get("read_replica_db_instance_identifiers", []) if r != db["db_instance_identifier"]]
    if "backup_retention_period" not in params:
        db["backup_retention_period"] = 1
    db["read_replica_source_db_instance_identifier"] = None
    db["updated"] = _now()
    store.persist()
    _log_event(store, db["db_instance_identifier"], "db-instance", "Read replica promoted to a standalone DB instance.",
               ["creation"], msg_store)
    return _success("PromoteReadReplica", _db_instance_xml(db))


# ── native-wire dispatcher (Query-protocol Action → operation) ─────────────
# The single routing point for the native AWS RDS Query protocol — what an
# unmodified aws-cli / boto3 RDS client speaks. `params` is the parsed
# form-encoded body ({"Action": "CreateDBInstance", "DBInstanceIdentifier": ...}).
def dispatch(store: SqlStore, params: dict | None = None, msg_store=None, s3_store=None,
             _internal: bool = False) -> RdsResponse:
    """`msg_store` (the shared SNS/SQS store) delivers real event-subscription
    notifications; `s3_store` lets StartExportTask write a real object. Both
    optional — omitting them keeps every action working, just without that
    cross-service fan-out (e.g. the conformance tests that construct a bare
    SqlStore)."""
    params = params if isinstance(params, dict) else {}
    if not _internal and _SNAPSHOT_DATA in params:   # only adispatch() may hand in captured tables
        params = {k: v for k, v in params.items() if k != _SNAPSHOT_DATA}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must include an Action.", 400)
    try:
        if action == "CreateDBInstance":
            return _create_db_instance(store, params, msg_store)
        if action == "DescribeDBInstances":
            return _describe_db_instances(store, params)
        if action == "ModifyDBInstance":
            return _modify_db_instance(store, params, msg_store)
        if action == "DeleteDBInstance":
            return _delete_db_instance(store, params, msg_store)
        if action == "StartDBInstance":
            return _set_status(store, params, "StartDBInstance", "available", msg_store)
        if action == "StopDBInstance":
            return _set_status(store, params, "StopDBInstance", "stopped", msg_store)
        if action == "RebootDBInstance":
            return _set_status(store, params, "RebootDBInstance", "available", msg_store)
        if action == "CreateDBSnapshot":
            return _create_db_snapshot(store, params, msg_store)
        if action == "DescribeDBSnapshots":
            return _describe_db_snapshots(store, params)
        if action == "DeleteDBSnapshot":
            return _delete_db_snapshot(store, params)
        if action == "RestoreDBInstanceFromDBSnapshot":
            return _restore_db_instance_from_db_snapshot(store, params, msg_store)
        if action == "CreateDBSubnetGroup":
            return _create_db_subnet_group(store, params)
        if action == "DescribeDBSubnetGroups":
            return _describe_db_subnet_groups(store, params)
        if action == "DeleteDBSubnetGroup":
            return _delete_db_subnet_group(store, params)
        if action == "CreateDBParameterGroup":
            return _create_db_parameter_group(store, params)
        if action == "DescribeDBParameterGroups":
            return _describe_db_parameter_groups(store, params)
        if action == "DeleteDBParameterGroup":
            return _delete_db_parameter_group(store, params)
        if action == "DescribeDBParameters":
            return _describe_db_parameters(store, params)
        if action == "ModifyDBParameterGroup":
            return _modify_db_parameter_group(store, params)
        if action == "ListTagsForResource":
            return _list_tags_for_resource(store, params)
        if action == "AddTagsToResource":
            return _add_tags_to_resource(store, params)
        if action == "RemoveTagsFromResource":
            return _remove_tags_from_resource(store, params)
        if action == "DescribeEvents":
            return _describe_events(store, params)
        if action == "CreateDBProxy":
            return _create_db_proxy(store, params)
        if action == "DescribeDBProxies":
            return _describe_db_proxies(store, params)
        if action == "DeleteDBProxy":
            return _delete_db_proxy(store, params)
        if action == "CreateOptionGroup":
            return _create_option_group(store, params)
        if action == "DescribeOptionGroups":
            return _describe_option_groups(store, params)
        if action == "DeleteOptionGroup":
            return _delete_option_group(store, params)
        if action == "CreateEventSubscription":
            return _create_event_subscription(store, params)
        if action == "DescribeEventSubscriptions":
            return _describe_event_subscriptions(store, params)
        if action == "DeleteEventSubscription":
            return _delete_event_subscription(store, params)
        if action == "PurchaseReservedDBInstancesOffering":
            return _purchase_reserved_db_instance(store, params)
        if action == "DescribeReservedDBInstances":
            return _describe_reserved_db_instances(store, params)
        if action == "DescribeDBInstanceAutomatedBackups":
            return _describe_db_instance_automated_backups(store, params)
        if action == "StartExportTask":
            return _start_export_task(store, params, s3_store)
        if action == "CancelExportTask":
            return _cancel_export_task(store, params)
        if action == "DescribeExportTasks":
            return _describe_export_tasks(store, params)
        if action == "CreateIntegration":
            return _create_integration(store, params)
        if action == "DeleteIntegration":
            return _delete_integration(store, params)
        if action == "DescribeIntegrations":
            return _describe_integrations(store, params)
        if action == "CreateCustomDBEngineVersion":
            return _create_custom_db_engine_version(store, params)
        if action == "DeleteCustomDBEngineVersion":
            return _delete_custom_db_engine_version(store, params)
        if action == "DescribeDBEngineVersions":
            return _describe_db_engine_versions(store, params)
        if action == "DescribeDBRecommendations":
            return _describe_db_recommendations(store, params)
        if action == "DescribeCertificates":
            return _describe_certificates(store, params)
        if action == "DescribeDBLogFiles":
            return _describe_db_log_files(store, params)
        if action == "DownloadDBLogFilePortion":
            return _download_db_log_file_portion(store, params)
        if action == "CreateDBInstanceReadReplica":
            return _create_db_instance_read_replica(store, params, msg_store)
        if action == "PromoteReadReplica":
            return _promote_read_replica(store, params, msg_store)
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    except RdsError as e:
        return _error(e.code, e.message, e.status)


async def adispatch(store: SqlStore, params: dict | None = None, msg_store=None, s3_store=None) -> RdsResponse:
    """Async front door (AwsWireRouter.ahandle — the Nano relay / console and the
    offline appliance). Same actions as dispatch(); the ones that read the engine's
    DATA await it, so an async engine (PGlite) is snapshotted for real and the
    browser's async Parquet writer (parquet-wasm) can run for StartExportTask."""
    params = dict(params) if isinstance(params, dict) else {}
    params.pop(_SNAPSHOT_DATA, None)   # never accepted from the wire
    action = str(params.get("Action", "")).strip()
    try:
        if action == "StartExportTask":
            return await _astart_export_task(store, params, s3_store)
        snapshotting = (action == "CreateDBSnapshot" or (
            action == "DeleteDBInstance" and str(params.get("SkipFinalSnapshot", "true")).lower() != "true"))
        if snapshotting:
            try:
                from core import sql_store as _sq
            except ImportError:  # pragma: no cover - Pyodide flat layout
                import sql_store as _sq  # type: ignore
            db_id = str(params.get("DBInstanceIdentifier", "")).strip()
            if _sq.is_async_engine(store) and store.get_instance(db_id):
                try:
                    params[_SNAPSHOT_DATA] = await _sq.adump_tables(store, db_id)
                except Exception:
                    pass
    except RdsError as e:
        return _error(e.code, e.message, e.status)
    return dispatch(store, params, msg_store=msg_store, s3_store=s3_store, _internal=True)


# ── data plane (NOT a native RDS action — the in-tab SQL bridge) ───────────
def _dataplane_precheck(store: SqlStore, db_instance_identifier: str) -> dict | None:
    """Shared gate for the sync + async data-plane entries (no divergence)."""
    db = store.get_instance(db_instance_identifier)
    if not db:
        return {"ok": False, "code": "DBInstanceNotFound",
                "message": f"DBInstance {db_instance_identifier} not found."}
    if db.get("db_instance_status") != "available":
        return {"ok": False, "code": "InvalidDBInstanceState",
                "message": f"DBInstance is {db.get('db_instance_status')}."}
    return None


# ── rds.monitoring: CloudWatch metrics genuinely derived from real activity
# (never synthetic). `cw_store` is wired onto the SqlStore by the same seam as
# vpc_core's StatusCheckFailed (AwsWireRouter / nano_registry set
# `store.cw_store = <the shared CloudWatchStore>`); it's absent for a bare
# SqlStore (e.g. conformance tests that don't construct one), in which case
# this is a no-op rather than an error. ──────────────────────────────────
def _push_activity_metrics(store: SqlStore, db_id: str, sql: str | None = None) -> None:
    cw = getattr(store, "cw_store", None)
    if cw is None:
        return
    dims = [{"Name": "DBInstanceIdentifier", "Value": db_id}]
    if sql is not None:
        metric = "ReadIOPS" if sql.strip()[:6].upper() == "SELECT" else "WriteIOPS"
        _cw_core.ingest_internal_metric(cw, "AWS/RDS", metric, dims, 1.0, unit="Count")
    _cw_core.ingest_internal_metric(cw, "AWS/RDS", "DatabaseConnections", dims,
                                    float(store.open_transaction_count(db_id)), unit="Count")


# ── rds.logs: one real error-log file per instance, built from genuine SQL
# execution failures (never fabricated — an instance with no failed
# statements has an empty log). ───────────────────────────────────────────
def _append_error_log(store: SqlStore, db_id: str, sql: str, message: str) -> None:
    store.append_log_line(db_id, f"{_now()} ERROR:  {message}\n  STATEMENT:  {sql}")


# ── rds.replication: a write statement run WITHOUT an explicit transaction
# (autocommit — the common case for ExecuteStatement/the console query tool)
# is really replayed against every read replica's own engine, so a replica's
# data genuinely reflects the source's writes (lag is always ~0, since this
# is synchronous). Statements run inside an explicit BeginTransaction are NOT
# forwarded (replicas are independent engines, not a literal shared WAL) —
# disclosed in the rds.replication capability limitations. ────────────────
def _replicate_write(store: SqlStore, source_id: str, sql: str, params: list | None) -> None:
    if sql.strip()[:6].upper() == "SELECT":
        return
    source = store.get_instance(source_id)
    if not source:
        return
    for replica_id in source.get("read_replica_db_instance_identifiers", []):
        try:
            store.execute_sql(replica_id, sql, params)
        except Exception:
            pass  # a replica-side failure never fails the source write


async def _areplicate_write(store: SqlStore, source_id: str, sql: str, params: list | None) -> None:
    if sql.strip()[:6].upper() == "SELECT":
        return
    source = store.get_instance(source_id)
    if not source:
        return
    for replica_id in source.get("read_replica_db_instance_identifiers", []):
        try:
            await store.aexecute_sql(replica_id, sql, params)
        except Exception:
            pass


def execute_sql(store: SqlStore, db_instance_identifier: str, sql: str,
                params: list | None = None) -> dict:
    """Run real SQL against an instance's engine (sqlite3 in Nano). Used by the
    console query tool / in-browser apps / the relay — the analogue of connecting
    over the Postgres wire. Returns {ok, columns, rows, rowcount} or {ok:False}."""
    err = _dataplane_precheck(store, db_instance_identifier)
    if err:
        return err
    try:
        result = store.execute_sql(db_instance_identifier, sql, params)
        _push_activity_metrics(store, db_instance_identifier, sql)
        _replicate_write(store, db_instance_identifier, sql, params)
        return {"ok": True, **result}
    except Exception as e:
        _append_error_log(store, db_instance_identifier, sql, str(e))
        return {"ok": False, "code": "SQLError", "message": str(e)}


async def aexecute_sql(store: SqlStore, db_instance_identifier: str, sql: str,
                       params: list | None = None) -> dict:
    """Async twin of execute_sql — SAME {ok, columns, rows, rowcount} contract, but
    awaits the engine so an ASYNC data-plane (PGlite over the real Postgres wire)
    can back RDS in the browser. Sync engines work unchanged (the base store's
    aexecute_sql delegates to execute_sql)."""
    err = _dataplane_precheck(store, db_instance_identifier)
    if err:
        return err
    try:
        result = await store.aexecute_sql(db_instance_identifier, sql, params)
        _push_activity_metrics(store, db_instance_identifier, sql)
        await _areplicate_write(store, db_instance_identifier, sql, params)
        return {"ok": True, **result}
    except Exception as e:
        _append_error_log(store, db_instance_identifier, sql, str(e))
        return {"ok": False, "code": "SQLError", "message": str(e)}


# ── explicit transactions (RDS Data API Begin/Execute/Commit/RollbackTransaction)
# — a REAL cross-call transaction: statements run through a transaction id are
# not autocommitted until CommitTransaction (or discarded on Rollback). The
# connection limit enforced here is the instance's OWN max_connections, read
# live from its attached DB parameter group — so raising/lowering that
# parameter in the console genuinely changes how many transactions can be open
# at once (ModifyDBParameterGroup round-trips into real enforcement, not just
# storage). ───────────────────────────────────────────────────────────────
def _max_connections_for(store: SqlStore, db: dict) -> int | None:
    pg = store.get_parameter_group(db.get("db_parameter_group_name", ""))
    if not pg:
        return None
    p = (pg.get("parameters") or {}).get("max_connections")
    if not p:
        return None
    try:
        return int(p.get("parameter_value"))
    except (TypeError, ValueError):
        return None


async def abegin_transaction(store: SqlStore, db_instance_identifier: str) -> dict:
    """Returns {ok, transactionId} or {ok:False, code, message}."""
    err = _dataplane_precheck(store, db_instance_identifier)
    if err:
        return err
    db = store.get_instance(db_instance_identifier)
    limit = _max_connections_for(store, db)
    try:
        tx_id = await store.abegin_transaction(db_instance_identifier, limit=limit)
        _push_activity_metrics(store, db_instance_identifier)
        return {"ok": True, "transactionId": tx_id}
    except TransactionLimitError as e:
        return {"ok": False, "code": "BadRequestException", "message": str(e)}


async def aexecute_in_transaction(store: SqlStore, transaction_id: str, sql: str,
                                  params: list | None = None) -> dict:
    db_id = store.transaction_db_id(transaction_id)
    try:
        result = await store.aexecute_in_transaction(transaction_id, sql, params)
        if db_id is not None:
            _push_activity_metrics(store, db_id, sql)
        return {"ok": True, **result}
    except TransactionError as e:
        return {"ok": False, "code": "TransactionNotFoundException", "message": str(e)}
    except Exception as e:
        if db_id is not None:
            _append_error_log(store, db_id, sql, str(e))
        return {"ok": False, "code": "SQLError", "message": str(e)}


async def acommit_transaction(store: SqlStore, transaction_id: str) -> dict:
    db_id = store.transaction_db_id(transaction_id)
    ok = await store.acommit_transaction(transaction_id)
    if not ok:
        return {"ok": False, "code": "TransactionNotFoundException",
                "message": f"Transaction {transaction_id} is not found or has expired."}
    if db_id is not None:
        _push_activity_metrics(store, db_id)
    return {"ok": True}


async def arollback_transaction(store: SqlStore, transaction_id: str) -> dict:
    db_id = store.transaction_db_id(transaction_id)
    ok = await store.arollback_transaction(transaction_id)
    if not ok:
        return {"ok": False, "code": "TransactionNotFoundException",
                "message": f"Transaction {transaction_id} is not found or has expired."}
    if db_id is not None:
        _push_activity_metrics(store, db_id)
    return {"ok": True}
