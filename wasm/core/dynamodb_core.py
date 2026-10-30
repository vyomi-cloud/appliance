# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""DynamoDB core — substrate-independent, faithfully extracted from
providers/aws_services.py (the `_ddb_*` handlers) so the SAME logic runs in
Pro/Max (FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 / socket /
subprocess imports → loads under Pyodide. Persists through the NoSqlStore seam
(core/nosql_store.py).

Each operation takes plain inputs (the parsed JSON payload) and returns a
`DdbResponse` (status, headers, body-dict) — the native AWS DynamoDB wire shapes
(typed attribute values {"S":..}/{"N":..}, `__type` JSON errors with an
`x-amzn-requestid` header, TableDescription/Item/Items/Count). A thin FastAPI
adapter (Pro/Max) or the service-worker / relay bridge (Nano) maps
Request<->DdbResponse and JSON-serialises the body.

Scope (v1 slice — the conformance core): CreateTable, DescribeTable, ListTables,
DeleteTable (honours DeletionProtectionEnabled), UpdateTable (billing mode,
throughput, deletion protection, table class, GSI create/delete), PutItem,
GetItem, DeleteItem, UpdateItem (AttributeUpdates + SET UpdateExpression),
Query (KeyConditionExpression: =, begins_with, BETWEEN), Scan, BatchGetItem,
BatchWriteItem, TagResource/UntagResource/ListTagsOfResource,
UpdateTimeToLive/DescribeTimeToLive (lazy expiry on read), UpdateContinuousBackups/
DescribeContinuousBackups (PITR flag), CreateBackup/ListBackups/DescribeBackup/
DeleteBackup/RestoreTableFromBackup (snapshot copies inside the store),
ExecuteStatement (PartiQL: SELECT/INSERT/UPDATE/DELETE).
DynamoDB Streams (DescribeStream/GetShardIterator/GetRecords/ListStreams) reuse
the same helpers and slot in next.

Faithfulness note: the appliance raises FastAPI HTTPExceptions for
ValidationException / ResourceInUseException (which FastAPI renders as a generic
`{"detail": ...}` body). The conformance core instead returns the NATIVE
`{"__type", "message"}` error shape for ALL errors — that is the canonical wire
behaviour the appliance converges onto, and it is what the conformance suite
asserts on every substrate.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.nosql_store import NoSqlStore


# ── transport types ───────────────────────────────────────────────────────
@dataclass
class DdbResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)

    def json_bytes(self) -> bytes:
        return json.dumps(self.body).encode()


class DdbError(Exception):
    """Native DynamoDB error — carries the `__type` code, message and HTTP status
    the wire expects. Raised by the helpers, caught by `dispatch`/operations and
    rendered via `_error`."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


# ── primitives (verbatim from providers/aws_services.py / app_context) ─────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return uuid.uuid4().hex.upper()[:16]


def _fmt_size(n: int) -> str:
    orig = float(n)
    for unit in ["B", "KB", "MB", "GB"]:
        if orig < 1024:
            return f"{orig:.1f} {unit}"
        orig /= 1024
    return f"{orig:.1f} TB"


def _table_arn(store: NoSqlStore, table_name: str) -> str:
    return f"arn:aws:dynamodb:us-east-1:{store.account_id}:table/{table_name}"


# ── typed attribute-value encoding (verbatim) ──────────────────────────────
def _is_typed_value(value: Any) -> bool:
    return (isinstance(value, dict) and len(value) == 1
            and next(iter(value.keys())) in {"S", "N", "BOOL", "NULL", "M", "L", "SS", "NS", "BS", "B"})


def json_to_native(value: Any) -> Any:
    if isinstance(value, dict):
        if _is_typed_value(value):
            type_key, raw = next(iter(value.items()))
            if type_key == "S":
                return str(raw)
            if type_key == "N":
                raw_text = str(raw)
                try:
                    return int(raw_text) if re.fullmatch(r"-?\d+", raw_text) else float(raw_text)
                except Exception:
                    return raw_text
            if type_key == "BOOL":
                return bool(raw)
            if type_key == "NULL":
                return None
            if type_key == "B":
                return raw
            if type_key == "SS":
                return [str(item) for item in (raw or [])]
            if type_key == "NS":
                values = []
                for item in raw or []:
                    try:
                        item_text = str(item)
                        values.append(int(item_text) if re.fullmatch(r"-?\d+", item_text) else float(item_text))
                    except Exception:
                        values.append(str(item))
                return values
            if type_key == "BS":
                return list(raw or [])
            if type_key == "L":
                return [json_to_native(item) for item in (raw or [])]
            if type_key == "M":
                return {k: json_to_native(v) for k, v in (raw or {}).items()}
        return {k: json_to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_to_native(v) for v in value]
    return copy.deepcopy(value)


def native_to_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {"M": {k: native_to_json(v) for k, v in value.items()}}
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return {"SS": [str(item) for item in value]}
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return {"NS": [str(item) for item in value]}
        return {"L": [native_to_json(item) for item in value]}
    if isinstance(value, bool):
        return {"BOOL": value}
    if value is None:
        return {"NULL": True}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"N": str(value)}
    return {"S": str(value)}


def native_item_to_json(item: dict[str, Any]) -> dict[str, Any]:
    return {k: native_to_json(v) for k, v in (item or {}).items()}


def _item_to_native_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise DdbError("ValidationException", "Item must be an object.", 400)
    return {k: json_to_native(v) for k, v in item.items()}


# ── key schema helpers (verbatim, over `store`-held tables) ────────────────
def _table_key_fields(table: dict) -> tuple[str, str]:
    return str(table.get("partition_key_name", "id")), str(table.get("sort_key_name", "") or "")


def _item_key_tuple(table: dict, item: dict[str, Any]) -> tuple[Any, Any | None]:
    pk_name, sk_name = _table_key_fields(table)
    if pk_name not in item:
        raise DdbError("ValidationException", f"Missing partition key '{pk_name}'.", 400)
    pk = item.get(pk_name)
    sk = item.get(sk_name) if sk_name else None
    if sk_name and sk is None:
        raise DdbError("ValidationException", f"Missing sort key '{sk_name}'.", 400)
    return pk, sk


def _item_key_string(table: dict, item: dict[str, Any]) -> str:
    return json.dumps(_item_key_tuple(table, item), default=str, separators=(",", ":"))


def _normalize_table(store: NoSqlStore, table_name: str, table: dict) -> dict:
    table.setdefault("table_name", table_name)
    table.setdefault("table_arn", _table_arn(store, table_name))
    table.setdefault("table_status", "ACTIVE")
    table.setdefault("partition_key_name", "id")
    table.setdefault("partition_key_type", "S")
    table.setdefault("sort_key_name", "")
    table.setdefault("sort_key_type", "S")
    table.setdefault("billing_mode", "PAY_PER_REQUEST")
    table.setdefault("provisioned_throughput", {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5})
    table.setdefault("table_class", "STANDARD")
    table.setdefault("deletion_protection_enabled", False)
    table.setdefault("sse_type", "")
    table.setdefault("tags", {})
    table.setdefault("indexes", [])
    table.setdefault("streams", {"enabled": False, "latest_stream_label": ""})
    table.setdefault("items", {})
    table.setdefault("created", _now())
    table.setdefault("last_modified", _now())
    table.setdefault("ttl_attribute_name", "")
    table.setdefault("ttl_enabled", False)
    table.setdefault("pitr_enabled", False)
    table.setdefault("pitr_earliest", "")
    return table


def _find_table(store: NoSqlStore, table_name: str) -> dict | None:
    table = store.get_table(table_name)
    if isinstance(table, dict):
        return _normalize_table(store, table_name, table)
    return None


def _require_table(store: NoSqlStore, table_name: str) -> dict:
    table = _find_table(store, table_name)
    if not table:
        raise DdbError("ResourceNotFoundException",
                       f"Requested resource not found: Table: {table_name} not found.", 404)
    return table


def _refresh_table_metrics(table: dict) -> None:
    records = list((table.get("items") or {}).values())
    table["item_count"] = len(records)
    try:
        table["table_size_bytes"] = sum(
            len(json.dumps(rec.get("item", {}), sort_keys=True, default=str).encode("utf-8"))
            for rec in records)
    except Exception:
        table["table_size_bytes"] = 0
    table["last_modified"] = _now()


def _table_view(store: NoSqlStore, table: dict, include_items: bool = True) -> dict:
    table = _normalize_table(store, table.get("table_name", ""), table)
    _refresh_table_metrics(table)
    view = {
        "TableName": table.get("table_name", ""),
        "TableArn": table.get("table_arn", ""),
        "TableStatus": table.get("table_status", "ACTIVE"),
        "KeySchema": table.get("key_schema", []),
        "AttributeDefinitions": table.get("attribute_definitions", []),
        "BillingModeSummary": {"BillingMode": table.get("billing_mode", "PAY_PER_REQUEST")},
        "ProvisionedThroughput": copy.deepcopy(table.get("provisioned_throughput", {})),
        "CreationDateTime": table.get("created", ""),
        "ItemCount": int(table.get("item_count", 0) or 0),
        "TableSizeBytes": int(table.get("table_size_bytes", 0) or 0),
        "TableClassSummary": {"TableClass": table.get("table_class", "STANDARD")},
        "DeletionProtectionEnabled": bool(table.get("deletion_protection_enabled", False)),
    }
    sse_type = table.get("sse_type", "")
    if sse_type:
        view["SSEDescription"] = {"Status": "ENABLED", "SSEType": sse_type}
    indexes = table.get("indexes", [])
    if indexes:
        view["GlobalSecondaryIndexes"] = [{
            "IndexName": gsi.get("name", ""),
            "KeySchema": gsi.get("key_schema", []),
            "Projection": gsi.get("projection", {"ProjectionType": "ALL"}),
            "IndexStatus": gsi.get("index_status", "ACTIVE"),
            "ItemCount": int(table.get("item_count", 0) or 0),
        } for gsi in indexes]
    return view


# ── table CRUD (faithful ports over the store) ─────────────────────────────
def _create_table_record(store: NoSqlStore, payload: dict[str, Any]) -> dict:
    table_name = str(payload.get("TableName") or payload.get("table_name") or "").strip()
    if not table_name:
        raise DdbError("ValidationException", "TableName is required.", 400)
    if store.table_exists(table_name):
        raise DdbError("ResourceInUseException",
                       f"Table already exists: {table_name}", 400)

    # Native KeySchema + AttributeDefinitions take precedence; fall back to the
    # console's flat partition/sort fields (the appliance accepts both).
    key_schema = payload.get("KeySchema") or []
    attr_defs = payload.get("AttributeDefinitions") or []
    attr_type = {str(d.get("AttributeName")): str(d.get("AttributeType", "S")).upper()
                 for d in attr_defs if isinstance(d, dict)}
    pk_name = sk_name = ""
    for ks in key_schema:
        if not isinstance(ks, dict):
            continue
        if str(ks.get("KeyType", "")).upper() == "HASH":
            pk_name = str(ks.get("AttributeName", ""))
        elif str(ks.get("KeyType", "")).upper() == "RANGE":
            sk_name = str(ks.get("AttributeName", ""))

    pk_name = (pk_name or str(payload.get("partition_key_name") or "id")).strip() or "id"
    pk_type = (attr_type.get(pk_name) or str(payload.get("partition_key_type") or "S")).strip().upper() or "S"
    sk_name = (sk_name or str(payload.get("sort_key_name") or "")).strip()
    sk_type = (attr_type.get(sk_name) or str(payload.get("sort_key_type") or "S")).strip().upper() or "S"
    billing_mode = str(payload.get("BillingMode") or payload.get("billing_mode") or "PAY_PER_REQUEST").strip().upper() or "PAY_PER_REQUEST"
    throughput = payload.get("ProvisionedThroughput") or payload.get("provisioned_throughput") or {}
    table_class = str(payload.get("TableClass") or payload.get("table_class") or "STANDARD").strip().upper() or "STANDARD"
    deletion_protection = bool(payload.get("DeletionProtectionEnabled") or payload.get("deletion_protection_enabled") or False)
    sse_spec = payload.get("SSESpecification") or payload.get("sse_specification") or {}
    sse_type = str(sse_spec.get("SSEType") or "").strip().upper() if sse_spec.get("Enabled") else ""
    tags = payload.get("Tags") or payload.get("tags") or {}
    if isinstance(tags, list):
        tags = {str(t.get("Key", t.get("key", ""))): str(t.get("Value", t.get("value", "")))
                for t in tags if isinstance(t, dict)}

    # Global secondary indexes: keep each index's KeySchema so Query(IndexName=...)
    # can resolve its own partition/sort keys (distinct from the base table's).
    indexes = []
    for gsi in (payload.get("GlobalSecondaryIndexes") or []):
        if not isinstance(gsi, dict):
            continue
        gks = gsi.get("KeySchema") or []
        g_pk = next((str(k.get("AttributeName", "")) for k in gks
                     if str(k.get("KeyType", "")).upper() == "HASH"), "")
        g_sk = next((str(k.get("AttributeName", "")) for k in gks
                     if str(k.get("KeyType", "")).upper() == "RANGE"), "")
        indexes.append({
            "name": str(gsi.get("IndexName", "")),
            "key_schema": gks,
            "partition_key_name": g_pk,
            "sort_key_name": g_sk,
            "projection": gsi.get("Projection") or {"ProjectionType": "ALL"},
            "index_status": "ACTIVE",
        })

    table = {
        "table_name": table_name,
        "table_arn": _table_arn(store, table_name),
        "table_status": "ACTIVE",
        "partition_key_name": pk_name,
        "partition_key_type": pk_type,
        "sort_key_name": sk_name,
        "sort_key_type": sk_type,
        "billing_mode": billing_mode,
        "provisioned_throughput": {
            "ReadCapacityUnits": int(throughput.get("ReadCapacityUnits", 5) or 5),
            "WriteCapacityUnits": int(throughput.get("WriteCapacityUnits", 5) or 5),
        },
        "table_class": table_class,
        "deletion_protection_enabled": deletion_protection,
        "sse_type": sse_type,
        "tags": copy.deepcopy(tags or {}),
        "indexes": indexes,
        "streams": {"enabled": False, "latest_stream_label": ""},
        "items": {},
        "created": _now(),
        "last_modified": _now(),
    }
    table["attribute_definitions"] = [{"AttributeName": pk_name, "AttributeType": pk_type}]
    table["key_schema"] = [{"AttributeName": pk_name, "KeyType": "HASH"}]
    if sk_name:
        table["attribute_definitions"].append({"AttributeName": sk_name, "AttributeType": sk_type})
        table["key_schema"].append({"AttributeName": sk_name, "KeyType": "RANGE"})
    store.put_table(table_name, table)
    store.mirror_create_table(table_name, table)
    store.persist()
    return table


def _delete_table_record(store: NoSqlStore, table_name: str) -> None:
    if not store.table_exists(table_name):
        raise DdbError("ResourceNotFoundException", f"Table {table_name} not found.", 404)
    store.drop_table(table_name)
    store.mirror_delete_table(table_name)
    store.persist()


def _update_table_record(store: NoSqlStore, table: dict, payload: dict[str, Any]) -> dict:
    if "BillingMode" in payload or "billing_mode" in payload:
        table["billing_mode"] = str(payload.get("BillingMode") or payload.get("billing_mode")).strip().upper()
    if "ProvisionedThroughput" in payload or "provisioned_throughput" in payload:
        pt = payload.get("ProvisionedThroughput") or payload.get("provisioned_throughput") or {}
        current = table.get("provisioned_throughput", {})
        table["provisioned_throughput"] = {
            "ReadCapacityUnits": int(pt.get("ReadCapacityUnits", current.get("ReadCapacityUnits", 5)) or 5),
            "WriteCapacityUnits": int(pt.get("WriteCapacityUnits", current.get("WriteCapacityUnits", 5)) or 5),
        }
    if "DeletionProtectionEnabled" in payload or "deletion_protection_enabled" in payload:
        table["deletion_protection_enabled"] = bool(payload.get("DeletionProtectionEnabled",
                                                                 payload.get("deletion_protection_enabled")))
    if "TableClass" in payload or "table_class" in payload:
        table["table_class"] = str(payload.get("TableClass") or payload.get("table_class")).strip().upper()
    for upd in payload.get("GlobalSecondaryIndexUpdates") or payload.get("global_secondary_index_updates") or []:
        if not isinstance(upd, dict):
            continue
        if "Create" in upd:
            g = upd["Create"]
            gks = g.get("KeySchema") or []
            g_pk = next((str(k.get("AttributeName", "")) for k in gks
                         if str(k.get("KeyType", "")).upper() == "HASH"), "")
            g_sk = next((str(k.get("AttributeName", "")) for k in gks
                         if str(k.get("KeyType", "")).upper() == "RANGE"), "")
            table.setdefault("indexes", []).append({
                "name": str(g.get("IndexName", "")), "key_schema": gks,
                "partition_key_name": g_pk, "sort_key_name": g_sk,
                "projection": g.get("Projection") or {"ProjectionType": "ALL"},
                "index_status": "ACTIVE",
            })
        elif "Delete" in upd:
            name = str(upd["Delete"].get("IndexName", ""))
            table["indexes"] = [g for g in table.get("indexes", []) if g.get("name") != name]
    table["last_modified"] = _now()
    store.persist()
    return table


# ── TTL (faithful lazy-expiry: items past their TTL are dropped on read) ───
def _is_expired(table: dict, item: dict[str, Any]) -> bool:
    attr = table.get("ttl_attribute_name") or ""
    if not table.get("ttl_enabled") or not attr:
        return False
    value = item.get(attr)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value <= datetime.now(timezone.utc).timestamp()


def _expire_table_items(table: dict) -> None:
    items = table.get("items") or {}
    expired = [key for key, rec in items.items() if _is_expired(table, rec.get("item", {}))]
    for key in expired:
        items.pop(key, None)
    if expired:
        _refresh_table_metrics(table)


def _ttl_view(table: dict) -> dict:
    attr = table.get("ttl_attribute_name") or ""
    view = {"TimeToLiveStatus": "ENABLED" if table.get("ttl_enabled") and attr else "DISABLED"}
    if attr:
        view["AttributeName"] = attr
    return view


def _update_ttl(store: NoSqlStore, table: dict, spec: dict[str, Any]) -> dict:
    attr = str(spec.get("AttributeName") or "").strip()
    enabled = bool(spec.get("Enabled"))
    if enabled and not attr:
        raise DdbError("ValidationException", "AttributeName is required to enable TTL.", 400)
    if attr:
        table["ttl_attribute_name"] = attr
    table["ttl_enabled"] = enabled
    table["last_modified"] = _now()
    store.persist()
    return {"AttributeName": table.get("ttl_attribute_name", ""), "Enabled": enabled}


# ── Point-in-time recovery (continuous backups) ────────────────────────────
def _continuous_backups_view(table: dict) -> dict:
    enabled = bool(table.get("pitr_enabled"))
    desc = {"PointInTimeRecoveryStatus": "ENABLED" if enabled else "DISABLED"}
    if enabled:
        desc["EarliestRestorableDateTime"] = table.get("pitr_earliest") or _now()
        desc["LatestRestorableDateTime"] = _now()
    return {"ContinuousBackupsStatus": "ENABLED", "PointInTimeRecoveryDescription": desc}


def _update_continuous_backups(store: NoSqlStore, table: dict, spec: dict[str, Any]) -> None:
    enabled = bool(spec.get("PointInTimeRecoveryEnabled"))
    table["pitr_enabled"] = enabled
    if enabled and not table.get("pitr_earliest"):
        table["pitr_earliest"] = _now()
    table["last_modified"] = _now()
    store.persist()


# ── on-demand backups (snapshot copies inside the store) ───────────────────
def _backup_summary(backup: dict) -> dict:
    return {
        "TableName": backup["table_name"], "TableArn": backup["table_arn"],
        "BackupArn": backup["backup_arn"], "BackupName": backup["backup_name"],
        "BackupStatus": backup.get("backup_status", "AVAILABLE"),
        "BackupType": backup.get("backup_type", "USER"),
        "BackupSizeBytes": int(backup.get("backup_size_bytes", 0) or 0),
        "BackupCreationDateTime": backup["backup_creation_datetime"],
    }


def _backup_description(backup: dict) -> dict:
    src = backup.get("source_table") or {}
    return {
        "BackupDetails": _backup_summary(backup),
        "SourceTableDetails": {
            "TableName": src.get("table_name", ""), "TableArn": src.get("table_arn", ""),
            "TableSizeBytes": int(src.get("table_size_bytes", 0) or 0),
            "KeySchema": src.get("key_schema", []),
            "TableCreationDateTime": src.get("created", ""),
            "ItemCount": int(src.get("item_count", 0) or 0),
            "BillingMode": src.get("billing_mode", "PAY_PER_REQUEST"),
        },
        "SourceTableFeatureDetails": {},
    }


def _create_backup_record(store: NoSqlStore, payload: dict[str, Any]) -> dict:
    table_name = str(payload.get("TableName") or "").strip()
    table = _require_table(store, table_name)
    backup_name = str(payload.get("BackupName") or "").strip()
    if not backup_name:
        raise DdbError("ValidationException", "BackupName is required.", 400)
    _refresh_table_metrics(table)
    backup_id = uuid.uuid4().hex[:16]
    backup_arn = f"{table['table_arn']}/backup/{backup_id}"
    backup = {
        "backup_arn": backup_arn, "backup_name": backup_name, "table_name": table_name,
        "table_arn": table["table_arn"], "backup_status": "AVAILABLE", "backup_type": "USER",
        "backup_size_bytes": int(table.get("table_size_bytes", 0) or 0),
        "backup_creation_datetime": _now(),
        "source_table": copy.deepcopy(table),
    }
    store.put_backup(backup_arn, backup)
    store.persist()
    return backup


def _restore_table_from_backup(store: NoSqlStore, payload: dict[str, Any]) -> dict:
    arn = str(payload.get("BackupArn") or "").strip()
    target = str(payload.get("TargetTableName") or "").strip()
    backup = store.get_backup(arn)
    if not backup:
        raise DdbError("BackupNotFoundException", f"Backup not found: {arn}", 400)
    if not target:
        raise DdbError("ValidationException", "TargetTableName is required.", 400)
    if store.table_exists(target):
        raise DdbError("ResourceInUseException", f"Table already exists: {target}", 400)
    restored = copy.deepcopy(backup.get("source_table") or {})
    restored["table_name"] = target
    restored["table_arn"] = _table_arn(store, target)
    restored["table_status"] = "ACTIVE"
    restored["created"] = _now()
    restored["last_modified"] = _now()
    store.put_table(target, restored)
    store.mirror_create_table(target, restored)
    store.persist()
    return restored


# ── item CRUD (faithful ports over the store) ──────────────────────────────
def _put_item_record(store: NoSqlStore, table: dict, payload: dict[str, Any]) -> dict:
    native_item = _item_to_native_item(payload.get("Item") or payload.get("item") or {})
    key = _item_key_string(table, native_item)
    store.enforce_storage_cap(len(json.dumps(native_item, default=str).encode("utf-8")))
    items = table.setdefault("items", {})
    existing = items.get(key)
    items[key] = {
        "item": native_item,
        "created": existing.get("created", _now()) if existing else _now(),
        "updated": _now(),
        "size_bytes": len(json.dumps(native_item, sort_keys=True, default=str).encode("utf-8")),
    }
    _refresh_table_metrics(table)
    store.mirror_put_item(table["table_name"], key, native_item)
    store.persist()
    return existing or {}


def _get_item_record(store: NoSqlStore, table: dict, payload: dict[str, Any]) -> dict | None:
    native_key = _item_to_native_item(payload.get("Key") or payload.get("key") or {})
    key = _item_key_string(table, native_key)
    return table.get("items", {}).get(key)


def _delete_item_record(store: NoSqlStore, table: dict, payload: dict[str, Any]) -> dict:
    native_key = _item_to_native_item(payload.get("Key") or payload.get("key") or {})
    key = _item_key_string(table, native_key)
    removed = table.get("items", {}).pop(key, None)
    _refresh_table_metrics(table)
    store.mirror_delete_item(table["table_name"], key)
    store.persist()
    return removed or {}


def _update_item_record(store: NoSqlStore, table: dict, payload: dict[str, Any]) -> dict:
    native_key = _item_to_native_item(payload.get("Key") or payload.get("key") or {})
    key = _item_key_string(table, native_key)
    current = copy.deepcopy(table.get("items", {}).get(key, {}).get("item", {}))
    updates = payload.get("AttributeUpdates") or payload.get("attribute_updates") or {}
    if not current:
        current = copy.deepcopy(native_key)
    if updates:
        for name, spec in updates.items():
            if not isinstance(spec, dict):
                continue
            action = str(spec.get("Action", "PUT")).upper()
            value = spec.get("Value")
            if action == "DELETE":
                current.pop(name, None)
            elif value is not None:
                current[name] = json_to_native(value)
    else:
        expr = str(payload.get("UpdateExpression") or payload.get("update_expression") or "").strip()
        values = payload.get("ExpressionAttributeValues") or payload.get("expression_attribute_values") or {}
        if expr.upper().startswith("SET "):
            for clause in expr[4:].split(","):
                if "=" not in clause:
                    continue
                left, right = clause.split("=", 1)
                attr_name = left.strip()
                token = right.strip()
                current[attr_name] = json_to_native(values.get(token, token))
    items = table.setdefault("items", {})
    items[key] = {
        "item": current,
        "created": items.get(key, {}).get("created", _now()),
        "updated": _now(),
        "size_bytes": len(json.dumps(current, sort_keys=True, default=str).encode("utf-8")),
    }
    _refresh_table_metrics(table)
    store.mirror_put_item(table["table_name"], key, current)
    store.persist()
    return items[key]


# ── Query / Scan (verbatim filters) ────────────────────────────────────────
def _sort_key(table: dict, native_item: dict[str, Any]) -> tuple[str, str]:
    pk_name, sk_name = _table_key_fields(table)
    return (str(native_item.get(pk_name, "")), str(native_item.get(sk_name, "")) if sk_name else "")


def _sorted_records(table: dict) -> list[dict]:
    records = list((table.get("items") or {}).values())
    records.sort(key=lambda rec: _sort_key(table, rec.get("item", {})))
    return records


def _gsi_key_fields(table: dict, index_name: str) -> tuple[str, str] | None:
    """Resolve a GSI's (partition, sort) key names from the table's stored indexes."""
    for gsi in table.get("indexes", []):
        if gsi.get("name") == index_name:
            return str(gsi.get("partition_key_name", "")), str(gsi.get("sort_key_name", "") or "")
    return None


def _query_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _sorted_records(table)
    if not records:
        return [], 0
    # Query(IndexName=...) resolves keys from the GSI's own KeySchema, not the base
    # table's — the whole point of a secondary index.
    index_name = str(payload.get("IndexName") or payload.get("index_name") or "").strip()
    if index_name:
        gsi_keys = _gsi_key_fields(table, index_name)
        if gsi_keys is None:
            raise DdbError("ValidationException",
                           f"The table does not have the specified index: {index_name}", 400)
        pk_name, sk_name = gsi_keys
    else:
        pk_name, sk_name = _table_key_fields(table)
    pk_value = payload.get("partition_key_value")
    sk_equals = payload.get("sort_key_equals")
    sk_begins = str(payload.get("sort_key_begins_with") or "")
    sk_between = payload.get("sort_key_between") or []
    expr = str(payload.get("KeyConditionExpression") or payload.get("key_condition_expression") or "").strip()
    names = payload.get("ExpressionAttributeNames") or payload.get("expression_attribute_names") or {}
    values = payload.get("ExpressionAttributeValues") or payload.get("expression_attribute_values") or {}
    if expr:
        for alias, actual in (names or {}).items():
            expr = expr.replace(str(alias), str(actual))
        if pk_value is None:
            m = re.search(rf"\b{re.escape(pk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                pk_value = json_to_native(values.get(m.group(1)))
        if sk_name and not sk_equals and not sk_begins and not sk_between:
            m = re.search(rf"\b{re.escape(sk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                sk_equals = json_to_native(values.get(m.group(1)))
            m = re.search(rf"begins_with\s*\(\s*{re.escape(sk_name)}\s*,\s*(:\w+)\s*\)", expr, flags=re.I)
            if m:
                sk_begins = str(json_to_native(values.get(m.group(1))) or "")
            m = re.search(rf"\b{re.escape(sk_name)}\s+BETWEEN\s+(:\w+)\s+AND\s+(:\w+)", expr, flags=re.I)
            if m:
                sk_between = [json_to_native(values.get(m.group(1))), json_to_native(values.get(m.group(2)))]
    matched = []
    for rec in records:
        item = rec.get("item", {})
        if pk_value is not None and item.get(pk_name) != pk_value:
            continue
        if sk_name:
            current_sk = item.get(sk_name)
            if sk_equals is not None and current_sk != sk_equals:
                continue
            if sk_begins and not str(current_sk or "").startswith(sk_begins):
                continue
            if isinstance(sk_between, list) and len(sk_between) == 2:
                low, high = sk_between
                if not (str(low) <= str(current_sk) <= str(high)):
                    continue
        matched.append(rec)
    limit = max(1, min(int(payload.get("Limit") or payload.get("limit") or 100), 1000))
    return matched[:limit], len(matched)


def _scan_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _sorted_records(table)
    limit = max(1, min(int(payload.get("Limit") or payload.get("limit") or 100), 1000))
    return records[:limit], len(records)


# ── tags ───────────────────────────────────────────────────────────────────
def _tags_view(table: dict) -> dict[str, str]:
    tags = table.setdefault("tags", {})
    if isinstance(tags, list):
        tags = {str(t.get("Key", "")): str(t.get("Value", "")) for t in tags if isinstance(t, dict)}
        table["tags"] = tags
    return copy.deepcopy(tags)


def _set_tags(store: NoSqlStore, table: dict, tags: dict[str, str]) -> None:
    table["tags"] = {str(k): str(v) for k, v in (tags or {}).items()}
    table["last_modified"] = _now()
    store.persist()


# ── PartiQL (ExecuteStatement) ──────────────────────────────────────────────
# A pragmatic subset — SELECT (WHERE on key/attributes), INSERT ... VALUE,
# UPDATE ... SET ... WHERE and DELETE FROM ... WHERE — sufficient for the
# console's PartiQL editor and ordinary CLI usage against a single table.
_SELECT_RE = re.compile(r'^\s*SELECT\s+.+?\s+FROM\s+"?([\w.-]+)"?(?:\s+WHERE\s+(.+))?\s*$', re.I | re.S)
_INSERT_RE = re.compile(r'^\s*INSERT\s+INTO\s+"?([\w.-]+)"?\s+VALUE\s+(\{.*\})\s*$', re.I | re.S)
_UPDATE_RE = re.compile(r'^\s*UPDATE\s+"?([\w.-]+)"?\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?\s*$', re.I | re.S)
_DELETE_RE = re.compile(r'^\s*DELETE\s+FROM\s+"?([\w.-]+)"?(?:\s+WHERE\s+(.+))?\s*$', re.I | re.S)
_AND_RE = re.compile(r"\s+AND\s+", re.I)
_COMMA_RE = re.compile(r"\s*,\s*")


def _split_unquoted(text: str, sep_re: re.Pattern) -> list[str]:
    """Split on a top-level separator, ignoring matches inside '...' strings
    or {}/[] nesting (so literal maps/lists aren't torn apart)."""
    parts, buf, depth, in_str, i, n = [], [], 0, False, 0, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            buf.append(ch)
            in_str = ch != "'"
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if depth == 0:
            m = sep_re.match(text, i)
            if m:
                parts.append("".join(buf))
                buf = []
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _partiql_literal(token: str, params: iter) -> Any:
    token = token.strip()
    if token == "?":
        try:
            return json_to_native(next(params))
        except StopIteration:
            raise DdbError("ValidationException", "Not enough Parameters for the statement.", 400)
    py = re.sub(r"\btrue\b", "True", token, flags=re.I)
    py = re.sub(r"\bfalse\b", "False", py, flags=re.I)
    py = re.sub(r"\bnull\b", "None", py, flags=re.I)
    try:
        return ast.literal_eval(py)
    except Exception:
        raise DdbError("ValidationException", f"Unable to parse PartiQL literal: {token}", 400)


def _partiql_where(clause: str | None, params: iter) -> dict[str, Any]:
    conds: dict[str, Any] = {}
    for part in _split_unquoted(clause, _AND_RE) if clause else []:
        m = re.match(r'^\s*"?([\w.]+)"?\s*=\s*(.+?)\s*$', part.strip())
        if m:
            conds[m.group(1)] = _partiql_literal(m.group(2), params)
    return conds


def _partiql_key(table: dict, conds: dict[str, Any], op: str) -> dict[str, Any]:
    pk_name, sk_name = _table_key_fields(table)
    if pk_name not in conds:
        raise DdbError("ValidationException", f"{op} requires the primary key in WHERE.", 400)
    key = {pk_name: conds[pk_name]}
    if sk_name and sk_name in conds:
        key[sk_name] = conds[sk_name]
    return key


def _execute_statement(store: NoSqlStore, payload: dict[str, Any]) -> DdbResponse:
    stmt = str(payload.get("Statement") or "").strip()
    params = iter(payload.get("Parameters") or [])

    m = _SELECT_RE.match(stmt)
    if m:
        table = _require_table(store, m.group(1))
        _expire_table_items(table)
        conds = _partiql_where(m.group(2), params)
        matched = [r for r in _sorted_records(table)
                   if all(r.get("item", {}).get(k) == v for k, v in conds.items())]
        return _ok({"Items": [native_item_to_json(r["item"]) for r in matched], "Count": len(matched)})

    m = _INSERT_RE.match(stmt)
    if m:
        table = _require_table(store, m.group(1))
        value = _partiql_literal(m.group(2), params)
        if not isinstance(value, dict):
            raise DdbError("ValidationException", "INSERT VALUE must be a map.", 400)
        _put_item_record(store, table, {"Item": native_item_to_json(value)})
        return _ok({})

    m = _UPDATE_RE.match(stmt)
    if m:
        table = _require_table(store, m.group(1))
        conds = _partiql_where(m.group(3), params)
        key = _partiql_key(table, conds, "UPDATE")
        sets: dict[str, Any] = {}
        for assign in _split_unquoted(m.group(2), _COMMA_RE):
            am = re.match(r'^\s*"?([\w.]+)"?\s*=\s*(.+?)\s*$', assign.strip())
            if am:
                sets[am.group(1)] = _partiql_literal(am.group(2), params)
        updated = _update_item_record(store, table, {
            "Key": native_item_to_json(key),
            "AttributeUpdates": {k: {"Action": "PUT", "Value": native_to_json(v)} for k, v in sets.items()},
        })
        return _ok({"Attributes": native_item_to_json(updated.get("item", {}))})

    m = _DELETE_RE.match(stmt)
    if m:
        table = _require_table(store, m.group(1))
        conds = _partiql_where(m.group(2), params)
        key = _partiql_key(table, conds, "DELETE")
        removed = _delete_item_record(store, table, {"Key": native_item_to_json(key)})
        return _ok({"Attributes": native_item_to_json(removed.get("item", {}))} if removed else {})

    raise DdbError("ValidationException", f"Unable to parse PartiQL statement: {stmt}", 400)


# ── response builders ───────────────────────────────────────────────────────
def _ok(body: dict | None = None) -> DdbResponse:
    return DdbResponse(status=200, body=body or {}, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400) -> DdbResponse:
    return DdbResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id()})


# ── transactional condition evaluation (TransactWriteItems guards) ─────────
# A pragmatic subset of ConditionExpression sufficient for the common transactional
# guards an unmodified SDK emits: attribute_exists(x) / attribute_not_exists(x)
# (idempotent-write guard) and a simple `attr = :v` / `#a = :v` equality. Anything
# unrecognised is treated as satisfied (never a false transaction failure).
def _eval_condition(table: dict, key_payload: dict[str, Any], expr: str,
                    names: dict[str, Any], values: dict[str, Any]) -> bool:
    expr = (expr or "").strip()
    if not expr:
        return True
    record = _get_item_record(None, table, {"Key": key_payload})  # store unused for read
    item = record.get("item", {}) if record else {}

    def _resolve(tok: str) -> str:
        tok = tok.strip()
        return str(names.get(tok, tok)) if tok.startswith("#") else tok

    fn = re.match(r"^\s*(attribute_exists|attribute_not_exists)\s*\(\s*(.+?)\s*\)\s*$",
                  expr, re.IGNORECASE)
    if fn:
        attr = _resolve(fn.group(2))
        present = attr in item
        return present if fn.group(1).lower() == "attribute_exists" else not present

    eq = re.match(r"^\s*(#?[\w.]+)\s*=\s*(:[\w]+)\s*$", expr)
    if eq:
        attr = _resolve(eq.group(1))
        want = json_to_native(values.get(eq.group(2), {}))
        return item.get(attr) == want

    return True   # unsupported predicate → don't fail the transaction


# ── native-wire dispatcher (X-Amz-Target action → operation) ───────────────
# The single routing point for the native AWS DynamoDB JSON protocol — what an
# unmodified aws-cli / boto3 client speaks. Shared by the Nano relay/bridge (tab
# side) and, on convergence, the appliance's _ddb_api_aws. `target` is the raw
# X-Amz-Target header, e.g. "DynamoDB_20120810.PutItem"; `payload` is the parsed
# JSON request body.
def dispatch(store: NoSqlStore, target: str, payload: dict | None = None) -> DdbResponse:
    payload = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("MissingAction", "The request must include X-Amz-Target.", 400)

    def table_name() -> str:
        name = str(payload.get("TableName") or payload.get("table_name") or "").strip()
        if not name:
            # Tagging (and other resource-level) operations identify the table only by
            # ResourceArn ("arn:aws:dynamodb:<region>:<acct>:table/<name>[/index/…]").
            arn = str(payload.get("ResourceArn") or "")
            if ":table/" in arn:
                name = arn.split(":table/", 1)[1].split("/", 1)[0]
        return name

    try:
        if action == "ListTables":
            return _ok({"TableNames": store.table_names()})

        if action == "CreateTable":
            table = _create_table_record(store, payload)
            return _ok({"TableDescription": _table_view(store, table, include_items=False)})

        if action == "DescribeTable":
            table = _require_table(store, table_name())
            return _ok({"Table": _table_view(store, table, include_items=True)})

        if action == "DeleteTable":
            name = table_name()
            table = _require_table(store, name)
            if table.get("deletion_protection_enabled"):
                raise DdbError("ValidationException",
                               f"Table cannot be deleted while DeletionProtectionEnabled is set to true. "
                               f"Table: {name}", 400)
            _delete_table_record(store, name)
            return _ok({"TableDescription": {"TableName": name, "TableStatus": "DELETING"}})

        if action == "UpdateTable":
            table = _require_table(store, table_name())
            _update_table_record(store, table, payload)
            return _ok({"TableDescription": _table_view(store, table, include_items=False)})

        if action == "UpdateTimeToLive":
            table = _require_table(store, table_name())
            spec = _update_ttl(store, table, payload.get("TimeToLiveSpecification") or {})
            return _ok({"TimeToLiveSpecification": spec})

        if action == "DescribeTimeToLive":
            table = _require_table(store, table_name())
            return _ok({"TimeToLiveDescription": _ttl_view(table)})

        if action == "UpdateContinuousBackups":
            table = _require_table(store, table_name())
            _update_continuous_backups(store, table, payload.get("PointInTimeRecoverySpecification") or {})
            return _ok({"ContinuousBackupsDescription": _continuous_backups_view(table)})

        if action == "DescribeContinuousBackups":
            table = _require_table(store, table_name())
            return _ok({"ContinuousBackupsDescription": _continuous_backups_view(table)})

        if action == "CreateBackup":
            backup = _create_backup_record(store, payload)
            return _ok({"BackupDetails": _backup_summary(backup)})

        if action == "ListBackups":
            tname = table_name()
            rows = [b for b in store.list_backups() if not tname or b["table_name"] == tname]
            rows.sort(key=lambda b: b["backup_creation_datetime"])
            return _ok({"BackupSummaries": [_backup_summary(b) for b in rows]})

        if action == "DescribeBackup":
            arn = str(payload.get("BackupArn") or "").strip()
            backup = store.get_backup(arn)
            if not backup:
                raise DdbError("BackupNotFoundException", f"Backup not found: {arn}", 400)
            return _ok({"BackupDescription": _backup_description(backup)})

        if action == "DeleteBackup":
            arn = str(payload.get("BackupArn") or "").strip()
            backup = store.get_backup(arn)
            if not backup:
                raise DdbError("BackupNotFoundException", f"Backup not found: {arn}", 400)
            backup["backup_status"] = "DELETED"
            desc = _backup_description(backup)
            store.drop_backup(arn)
            store.persist()
            return _ok({"BackupDescription": desc})

        if action == "RestoreTableFromBackup":
            restored = _restore_table_from_backup(store, payload)
            return _ok({"TableDescription": _table_view(store, restored, include_items=False)})

        if action == "ExecuteStatement":
            return _execute_statement(store, payload)

        if action == "PutItem":
            table = _require_table(store, table_name())
            old = _put_item_record(store, table, payload)
            return_old = str(payload.get("ReturnValues", "NONE")).upper() in {"ALL_OLD", "UPDATED_OLD"}
            attrs = native_item_to_json(copy.deepcopy(old.get("item", {}))) if old and return_old else {}
            return _ok({"Attributes": attrs} if attrs else {})

        if action == "GetItem":
            table = _require_table(store, table_name())
            _expire_table_items(table)
            record = _get_item_record(store, table, payload)
            return _ok({"Item": native_item_to_json(record.get("item", {}))} if record else {})

        if action == "DeleteItem":
            table = _require_table(store, table_name())
            removed = _delete_item_record(store, table, payload)
            return_old = str(payload.get("ReturnValues", "NONE")).upper() == "ALL_OLD"
            attrs = native_item_to_json(removed.get("item", {})) if removed and return_old else {}
            return _ok({"Attributes": attrs} if attrs else {})

        if action == "UpdateItem":
            table = _require_table(store, table_name())
            updated = _update_item_record(store, table, payload)
            return _ok({"Attributes": native_item_to_json(updated.get("item", {}))})

        if action == "Query":
            table = _require_table(store, table_name())
            _expire_table_items(table)
            matched, scanned = _query_filter(table, payload)
            return _ok({"Items": [native_item_to_json(r.get("item", {})) for r in matched],
                        "Count": len(matched), "ScannedCount": scanned})

        if action == "Scan":
            table = _require_table(store, table_name())
            _expire_table_items(table)
            matched, scanned = _scan_filter(table, payload)
            return _ok({"Items": [native_item_to_json(r.get("item", {})) for r in matched],
                        "Count": len(matched), "ScannedCount": scanned})

        if action == "BatchGetItem":
            responses: dict[str, list] = {}
            for tname, req in (payload.get("RequestItems") or {}).items():
                table = _find_table(store, str(tname))
                if not table:
                    continue
                _expire_table_items(table)
                rows = []
                for key in (req or {}).get("Keys") or []:
                    record = _get_item_record(store, table, {"Key": key})
                    if record:
                        rows.append(native_item_to_json(record.get("item", {})))
                responses[tname] = rows
            return _ok({"Responses": responses, "UnprocessedKeys": {}})

        if action == "BatchWriteItem":
            for tname, ops in (payload.get("RequestItems") or {}).items():
                table = _find_table(store, str(tname))
                if not table:
                    continue
                for op in ops or []:
                    if "PutRequest" in op:
                        _put_item_record(store, table, {"Item": op["PutRequest"].get("Item", {})})
                    elif "DeleteRequest" in op:
                        _delete_item_record(store, table, {"Key": op["DeleteRequest"].get("Key", {})})
            return _ok({"UnprocessedItems": {}})

        if action == "TransactWriteItems":
            # All-or-nothing: evaluate every guard/ConditionCheck against the
            # current state FIRST; only if all pass do we apply the writes. A
            # failed guard raises TransactionCanceledException with no side effects.
            ops = payload.get("TransactItems") or payload.get("transact_items") or []
            planned = []
            for entry in ops:
                if not isinstance(entry, dict):
                    continue
                kind, spec = next(iter(entry.items()))
                tname = str(spec.get("TableName") or spec.get("table_name") or "").strip()
                table = _require_table(store, tname)
                key_payload = (spec.get("Item") if kind == "Put"
                               else spec.get("Key")) or {}
                cond = str(spec.get("ConditionExpression")
                           or spec.get("condition_expression") or "").strip()
                names = spec.get("ExpressionAttributeNames") or {}
                values = spec.get("ExpressionAttributeValues") or {}
                if cond and not _eval_condition(table, key_payload, cond, names, values):
                    return _error("TransactionCanceledException",
                                  "Transaction cancelled, please refer cancellation "
                                  "reasons for specific reasons [ConditionalCheckFailed]",
                                  400)
                planned.append((kind, table, spec))
            for kind, table, spec in planned:
                if kind == "Put":
                    _put_item_record(store, table, {"Item": spec.get("Item", {})})
                elif kind == "Delete":
                    _delete_item_record(store, table, {"Key": spec.get("Key", {})})
                elif kind == "Update":
                    _update_item_record(store, table, spec)
                # ConditionCheck: guard already evaluated above, no mutation.
            return _ok({})

        if action == "TransactGetItems":
            ops = payload.get("TransactItems") or payload.get("transact_items") or []
            responses = []
            for entry in ops:
                get = (entry or {}).get("Get") or {}
                tname = str(get.get("TableName") or "").strip()
                table = _find_table(store, tname)
                record = _get_item_record(store, table, {"Key": get.get("Key", {})}) if table else None
                responses.append({"Item": native_item_to_json(record.get("item", {}))}
                                 if record else {})
            return _ok({"Responses": responses})

        if action == "TagResource":
            table = _require_table(store, table_name())
            tags = payload.get("Tags") or payload.get("tags") or {}
            if isinstance(tags, list):
                tags = {str(t.get("Key", "")): str(t.get("Value", "")) for t in tags if isinstance(t, dict)}
            merged = _tags_view(table)
            merged.update(tags if isinstance(tags, dict) else {})
            _set_tags(store, table, merged)
            return _ok({})

        if action == "UntagResource":
            table = _require_table(store, table_name())
            tags = _tags_view(table)
            for key in payload.get("TagKeys") or payload.get("tag_keys") or []:
                tags.pop(str(key), None)
            _set_tags(store, table, tags)
            return _ok({})

        if action == "ListTagsOfResource":
            table = _require_table(store, table_name())
            return _ok({"Tags": [{"Key": k, "Value": v} for k, v in _tags_view(table).items()]})

        return _error("UnknownOperationException", f"The action {action} is not implemented.", 400)
    except DdbError as e:
        return _error(e.code, e.message, e.status)
