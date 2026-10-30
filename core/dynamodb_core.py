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

Scope: CreateTable (GSIs + LSIs), DescribeTable, ListTables, DeleteTable (honours
DeletionProtectionEnabled), UpdateTable (billing mode, throughput, deletion
protection, table class, GSI create/delete), PutItem, GetItem, DeleteItem,
UpdateItem (UpdateExpression + legacy AttributeUpdates / Expected), Query
(KeyConditionExpression or legacy KeyConditions; GSI/LSI projections), Scan
(segments), BatchGetItem, BatchWriteItem, TransactWriteItems (CancellationReasons),
TransactGetItems, TagResource/UntagResource/ListTagsOfResource,
UpdateTimeToLive/DescribeTimeToLive (lazy expiry on read), UpdateContinuousBackups/
DescribeContinuousBackups (PITR flag), CreateBackup/ListBackups/DescribeBackup/
DeleteBackup/RestoreTableFromBackup (snapshot copies inside the store),
ExecuteStatement (PartiQL: SELECT/INSERT/UPDATE/DELETE).

Parity: items are kept as TYPED AttributeValues (record["av"]) — the source of
truth for the wire — next to the legacy native projection (record["item"]) the
console REST reads. Behaviour is measured differentially against DynamoDB Local
by tests/parity/ddb_differential.py; known gaps are listed in
core/capabilities/aws/dynamodb.json.

All errors use the NATIVE `{"__type", "message"}` shape with DynamoDB's HTTP 400
(500 only for internal errors).
"""
from __future__ import annotations

import copy
import json
import re
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.nosql_store import NoSqlStore
from core import dynamodb_expr as _expr


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
    the wire expects (plus optional extra body members, e.g. the old `Item` of a
    ConditionalCheckFailedException or a transaction's CancellationReasons)."""

    def __init__(self, code: str, message: str, status: int = 400, extra: dict | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra or {}


def _validation(message: str) -> DdbError:
    return DdbError("ValidationException", message, 400)


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


# ── typed attribute-value encoding (legacy native projection) ──────────────
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
        if value and all(isinstance(item, str) for item in value):
            return {"SS": [str(item) for item in value]}
        if value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
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


# ── key schema helpers (over `store`-held tables) ──────────────────────────
def _table_key_fields(table: dict) -> tuple[str, str]:
    return str(table.get("partition_key_name", "id")), str(table.get("sort_key_name", "") or "")


def _item_key_tuple(table: dict, item: dict[str, Any]) -> tuple[Any, Any | None]:
    pk_name, sk_name = _table_key_fields(table)
    if pk_name not in item:
        raise DdbError("ValidationException", "One of the required keys was not given a value", 400)
    pk = item.get(pk_name)
    sk = item.get(sk_name) if sk_name else None
    if sk_name and sk is None:
        raise DdbError("ValidationException", "One of the required keys was not given a value", 400)
    return pk, sk


def _item_key_string(table: dict, item: dict[str, Any]) -> str:
    """The storage key of an item (from its NATIVE projection — the format every
    console/legacy writer uses, so all writers address the same record)."""
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
    table.setdefault("local_indexes", [])
    table.setdefault("streams", {"enabled": False, "latest_stream_label": ""})
    table.setdefault("items", {})
    table.setdefault("created", _now())
    table.setdefault("last_modified", _now())
    table.setdefault("ttl_attribute_name", "")
    table.setdefault("ttl_enabled", False)
    table.setdefault("pitr_enabled", False)
    table.setdefault("pitr_earliest", "")
    return table


_RNF = "Requested resource not found: Table: {} not found"


def _find_table(store: NoSqlStore, table_name: str) -> dict | None:
    table = store.get_table(table_name)
    if isinstance(table, dict):
        return _normalize_table(store, table_name, table)
    return None


def _require_table(store: NoSqlStore, table_name: str) -> dict:
    table = _find_table(store, table_name)
    if not table:
        raise DdbError("ResourceNotFoundException", _RNF.format(table_name), 400)
    return table


def _refresh_table_metrics(table: dict) -> None:
    records = [r for r in (table.get("items") or {}).values() if isinstance(r, dict)]
    table["item_count"] = len(records)
    try:
        table["table_size_bytes"] = sum(int(r.get("size_bytes") or 0) for r in records)
    except Exception:
        table["table_size_bytes"] = 0
    table["last_modified"] = _now()


def _attr_types(table: dict) -> dict[str, str]:
    return {str(d.get("AttributeName")): str(d.get("AttributeType", "S"))
            for d in table.get("attribute_definitions", []) if isinstance(d, dict)}


def _index_view(table: dict, idx: dict) -> dict:
    v = {
        "IndexName": idx.get("name", ""),
        "KeySchema": idx.get("key_schema", []),
        "Projection": idx.get("projection", {"ProjectionType": "ALL"}),
        "IndexArn": f"{table.get('table_arn', '')}/index/{idx.get('name', '')}",
        "IndexSizeBytes": 0,
        "ItemCount": int(table.get("item_count", 0) or 0),
    }
    return v


def _table_view(store: NoSqlStore, table: dict, include_items: bool = True) -> dict:
    table = _normalize_table(store, table.get("table_name", ""), table)
    _refresh_table_metrics(table)
    ppr = str(table.get("billing_mode", "PAY_PER_REQUEST")).upper() == "PAY_PER_REQUEST"
    pt = copy.deepcopy(table.get("provisioned_throughput", {}))
    if ppr:
        pt = {"ReadCapacityUnits": 0, "WriteCapacityUnits": 0}
    pt.setdefault("NumberOfDecreasesToday", 0)
    view = {
        "TableName": table.get("table_name", ""),
        "TableArn": table.get("table_arn", ""),
        "TableId": table.setdefault("table_id", str(uuid.uuid4())),
        "TableStatus": table.get("table_status", "ACTIVE"),
        "KeySchema": table.get("key_schema", []),
        "AttributeDefinitions": table.get("attribute_definitions", []),
        "ProvisionedThroughput": pt,
        "CreationDateTime": table.get("created", ""),
        "ItemCount": int(table.get("item_count", 0) or 0),
        "TableSizeBytes": int(table.get("table_size_bytes", 0) or 0),
        "TableClassSummary": {"TableClass": table.get("table_class", "STANDARD")},
        "DeletionProtectionEnabled": bool(table.get("deletion_protection_enabled", False)),
    }
    # DynamoDB reports BillingModeSummary for on-demand tables and for tables whose
    # billing mode was ever changed; a table created PROVISIONED has none.
    if ppr or table.get("billing_mode_summary"):
        view["BillingModeSummary"] = {"BillingMode": table.get("billing_mode", "PAY_PER_REQUEST")}
    sse_type = table.get("sse_type", "")
    if sse_type:
        view["SSEDescription"] = {"Status": "ENABLED", "SSEType": sse_type}
    gsis = table.get("indexes", [])
    if gsis:
        view["GlobalSecondaryIndexes"] = [{**_index_view(table, g), "IndexStatus": g.get("index_status", "ACTIVE")}
                                          for g in gsis]
    lsis = table.get("local_indexes", [])
    if lsis:
        view["LocalSecondaryIndexes"] = [_index_view(table, li) for li in lsis]
    return view


# ── table CRUD ─────────────────────────────────────────────────────────────
def _index_record(spec: dict) -> dict:
    gks = spec.get("KeySchema") or []
    g_pk = next((str(k.get("AttributeName", "")) for k in gks if str(k.get("KeyType", "")).upper() == "HASH"), "")
    g_sk = next((str(k.get("AttributeName", "")) for k in gks if str(k.get("KeyType", "")).upper() == "RANGE"), "")
    return {"name": str(spec.get("IndexName", "")), "key_schema": gks,
            "partition_key_name": g_pk, "sort_key_name": g_sk,
            "projection": spec.get("Projection") or {"ProjectionType": "ALL"}, "index_status": "ACTIVE"}


def _validate_create_table(payload: dict, native: bool) -> None:
    """DynamoDB's CreateTable validation (native wire only — the console REST's
    flat partition/sort fields keep their lenient defaults)."""
    if not native:
        return
    name = str(payload.get("TableName") or "")
    # (DynamoDB also requires 3..255 characters; short names are accepted here — see
    # core/capabilities/aws/dynamodb.json.)
    if len(name) > 255 or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
        raise _validation("Invalid table/index name.  Table/index names must be between 3 and 255 characters long, "
                          "and may contain only the characters a-z, A-Z, 0-9, '_', '-', and '.'")
    ks = payload.get("KeySchema") or []
    if not ks or len(ks) > 2 or str(ks[0].get("KeyType", "")).upper() != "HASH" or \
            (len(ks) == 2 and str(ks[1].get("KeyType", "")).upper() != "RANGE"):
        raise _validation("Invalid KeySchema: The first KeySchemaElement is not a HASH key type")
    defs = payload.get("AttributeDefinitions") or []
    defined = [str(d.get("AttributeName")) for d in defs if isinstance(d, dict)]
    for d in defs:
        if str(d.get("AttributeType", "")) not in ("S", "N", "B"):
            raise _validation("Member must satisfy enum value set: [B, N, S]")
    used: list = []
    for spec in [{"KeySchema": ks}] + list(payload.get("GlobalSecondaryIndexes") or []) + \
            list(payload.get("LocalSecondaryIndexes") or []):
        for k in spec.get("KeySchema") or []:
            if k.get("AttributeName") not in used:
                used.append(str(k.get("AttributeName")))
    missing = [u for u in used if u not in defined]
    if missing:
        raise _validation("One or more parameter values were invalid: Some index key attributes are not defined in "
                          f"AttributeDefinitions. Keys: [{', '.join(missing)}], AttributeDefinitions: [{', '.join(defined)}]")
    if len(set(defined)) != len(set(used)):
        raise _validation("The number of attributes in key schema must match the number of attributes defined in "
                          "attribute definitions.")
    # NB: DynamoDB's implicit default is PROVISIONED (so omitting both BillingMode and
    # ProvisionedThroughput is an error there); we keep the pre-v4 lenient default of
    # on-demand for that case — see core/capabilities/aws/dynamodb.json.
    billing = str(payload.get("BillingMode") or "").upper()
    if billing == "PROVISIONED" and not payload.get("ProvisionedThroughput"):
        raise _validation("No provisioned throughput specified for the table")
    if billing == "PAY_PER_REQUEST" and payload.get("ProvisionedThroughput"):
        raise _validation("One or more parameter values were invalid: Neither ReadCapacityUnits nor WriteCapacityUnits "
                          "can be specified when BillingMode is PAY_PER_REQUEST")
    lsis = payload.get("LocalSecondaryIndexes") or []
    if lsis:
        if len(ks) < 2:
            raise _validation("One or more parameter values were invalid: Table KeySchema does not have a range key, "
                              "which is required when specifying a LocalSecondaryIndex")
        for li in lsis:
            lks = li.get("KeySchema") or []
            if not lks or lks[0].get("AttributeName") != ks[0].get("AttributeName"):
                raise _validation("One or more parameter values were invalid: Index KeySchema does not have the same "
                                  f"leading hash key as table KeySchema for index: {li.get('IndexName')}")
    names = [str(i.get("IndexName")) for i in list(payload.get("GlobalSecondaryIndexes") or []) + list(lsis)]
    if len(set(names)) != len(names):
        raise _validation("One or more parameter values were invalid: Duplicate index name")


def _create_table_record(store: NoSqlStore, payload: dict[str, Any]) -> dict:
    table_name = str(payload.get("TableName") or payload.get("table_name") or "").strip()
    if not table_name:
        raise DdbError("ValidationException", "TableName is required.", 400)
    native = bool(payload.get("KeySchema"))
    _validate_create_table(payload, native)
    if store.table_exists(table_name):
        raise DdbError("ResourceInUseException", f"Table already exists: {table_name}", 400)

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
    explicit_billing = payload.get("BillingMode") or payload.get("billing_mode")
    default_billing = "PROVISIONED" if native and payload.get("ProvisionedThroughput") else "PAY_PER_REQUEST"
    billing_mode = str(explicit_billing or default_billing).strip().upper() or "PAY_PER_REQUEST"
    throughput = payload.get("ProvisionedThroughput") or payload.get("provisioned_throughput") or {}
    table_class = str(payload.get("TableClass") or payload.get("table_class") or "STANDARD").strip().upper() or "STANDARD"
    deletion_protection = bool(payload.get("DeletionProtectionEnabled") or payload.get("deletion_protection_enabled") or False)
    sse_spec = payload.get("SSESpecification") or payload.get("sse_specification") or {}
    sse_type = str(sse_spec.get("SSEType") or "").strip().upper() if sse_spec.get("Enabled") else ""
    tags = payload.get("Tags") or payload.get("tags") or {}
    if isinstance(tags, list):
        tags = {str(t.get("Key", t.get("key", ""))): str(t.get("Value", t.get("value", "")))
                for t in tags if isinstance(t, dict)}

    # Secondary indexes keep their own KeySchema so Query(IndexName=...) resolves
    # the index's partition/sort keys (distinct from the base table's).
    indexes = [_index_record(g) for g in (payload.get("GlobalSecondaryIndexes") or []) if isinstance(g, dict)]
    local_indexes = [_index_record(li) for li in (payload.get("LocalSecondaryIndexes") or []) if isinstance(li, dict)]

    table = {
        "table_name": table_name,
        "table_arn": _table_arn(store, table_name),
        "table_status": "ACTIVE",
        "partition_key_name": pk_name,
        "partition_key_type": pk_type,
        "sort_key_name": sk_name,
        "sort_key_type": sk_type,
        "billing_mode": billing_mode,
        "billing_mode_summary": billing_mode == "PAY_PER_REQUEST",
        "provisioned_throughput": {
            "ReadCapacityUnits": int(throughput.get("ReadCapacityUnits", 5) or 5),
            "WriteCapacityUnits": int(throughput.get("WriteCapacityUnits", 5) or 5),
        },
        "table_class": table_class,
        "deletion_protection_enabled": deletion_protection,
        "sse_type": sse_type,
        "tags": copy.deepcopy(tags or {}),
        "indexes": indexes,
        "local_indexes": local_indexes,
        "streams": {"enabled": False, "latest_stream_label": ""},
        "items": {},
        "created": _now(),
        "last_modified": _now(),
        "table_id": str(uuid.uuid4()),
    }
    defs = [{"AttributeName": pk_name, "AttributeType": pk_type}]
    table["key_schema"] = [{"AttributeName": pk_name, "KeyType": "HASH"}]
    if sk_name:
        defs.append({"AttributeName": sk_name, "AttributeType": sk_type})
        table["key_schema"].append({"AttributeName": sk_name, "KeyType": "RANGE"})
    for name, t in attr_type.items():          # index key attributes
        if name not in (pk_name, sk_name):
            defs.append({"AttributeName": name, "AttributeType": t})
    table["attribute_definitions"] = defs
    store.put_table(table_name, table)
    store.mirror_create_table(table_name, table)
    store.persist()
    return table


def _delete_table_record(store: NoSqlStore, table_name: str) -> None:
    if not store.table_exists(table_name):
        raise DdbError("ResourceNotFoundException", _RNF.format(table_name), 400)
    store.drop_table(table_name)
    store.mirror_delete_table(table_name)
    store.persist()


def _update_table_record(store: NoSqlStore, table: dict, payload: dict[str, Any]) -> dict:
    if "BillingMode" in payload or "billing_mode" in payload:
        table["billing_mode"] = str(payload.get("BillingMode") or payload.get("billing_mode")).strip().upper()
        table["billing_mode_summary"] = True
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
    defs = {d["AttributeName"]: d for d in table.get("attribute_definitions", []) if isinstance(d, dict)}
    for d in payload.get("AttributeDefinitions") or []:
        if isinstance(d, dict) and d.get("AttributeName") not in defs:
            defs[d["AttributeName"]] = {"AttributeName": d["AttributeName"], "AttributeType": d.get("AttributeType", "S")}
    table["attribute_definitions"] = list(defs.values())
    for upd in payload.get("GlobalSecondaryIndexUpdates") or payload.get("global_secondary_index_updates") or []:
        if not isinstance(upd, dict):
            continue
        if "Create" in upd:
            table.setdefault("indexes", []).append(_index_record(upd["Create"]))
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


def _parse_restore_datetime(v: Any) -> datetime:
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise _validation(f"Invalid RestoreDateTime: {v}")


def _restore_table_to_point_in_time(store: NoSqlStore, payload: dict[str, Any]) -> dict:
    source = str(payload.get("SourceTableName") or "").strip()
    target = str(payload.get("TargetTableName") or "").strip()
    table = _require_table(store, source)
    if not table.get("pitr_enabled"):
        raise DdbError("InvalidRestoreTimeException",
                       f"Point in time recovery is not enabled for table: {source}", 400)
    if not target:
        raise DdbError("ValidationException", "TargetTableName is required.", 400)
    if store.table_exists(target):
        raise DdbError("TableAlreadyExistsException", f"Table already exists: {target}", 400)
    use_latest = bool(payload.get("UseLatestRestorableTime"))
    restore_dt = payload.get("RestoreDateTime")
    if not use_latest:
        if restore_dt is None:
            raise _validation("Either RestoreDateTime or UseLatestRestorableTime must be specified.")
        earliest = _parse_restore_datetime(table.get("pitr_earliest") or _now())
        latest = datetime.now(timezone.utc)
        when = _parse_restore_datetime(restore_dt)
        if when < earliest or when > latest:
            raise DdbError("InvalidRestoreTimeException",
                           "RestoreDateTime must be between EarliestRestorableDateTime and "
                           "LatestRestorableDateTime.", 400)
    # Vyomi keeps no change history, so any point within the PITR window restores the
    # table's current (latest) state — see core/capabilities/aws/dynamodb.json.
    _refresh_table_metrics(table)
    restored = copy.deepcopy(table)
    restored["table_name"] = target
    restored["table_arn"] = _table_arn(store, target)
    restored["table_status"] = "ACTIVE"
    restored["created"] = _now()
    restored["last_modified"] = _now()
    restored["pitr_enabled"] = False
    restored.pop("pitr_earliest", None)
    store.put_table(target, restored)
    store.mirror_create_table(target, restored)
    store.persist()
    return restored


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


# ── typed item records ─────────────────────────────────────────────────────
# record = {"item": <native projection — console REST / legacy readers>,
#           "av":   <typed AttributeValue map — the wire's source of truth>,
#           "created", "updated", "size_bytes"}
# A record written by a legacy/console writer has no "av" (or a stale one whose
# attribute set no longer matches "item"); it is then derived from the native item.
def _rec_av(rec: dict | None) -> dict:
    if not isinstance(rec, dict):
        return {}
    av = rec.get("av")
    item = rec.get("item") or {}
    if isinstance(av, dict) and set(av) == set(item):
        return av
    return {k: native_to_json(v) for k, v in item.items()}


def _store_av(store: NoSqlStore, table: dict, key: str, av_item: dict) -> dict:
    items = table.setdefault("items", {})
    existing = items.get(key)
    native = {k: json_to_native(v) for k, v in av_item.items()}
    rec = {"item": native, "av": copy.deepcopy(av_item),
           "created": existing.get("created", _now()) if isinstance(existing, dict) else _now(),
           "updated": _now(), "size_bytes": _expr.item_size(av_item)}
    items[key] = rec
    store.mirror_put_item(table["table_name"], key, native)
    return rec


def _drop_key(store: NoSqlStore, table: dict, key: str) -> dict | None:
    removed = table.get("items", {}).pop(key, None)
    if removed is not None:
        store.mirror_delete_item(table["table_name"], key)
    return removed


def _expr_error(kind: str, exc: "_expr.ExprError") -> DdbError:
    if exc.bare or not kind:
        return _validation(exc.message)
    return _validation(f"Invalid {kind}: {exc.message}")


def _validate_item(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise _validation("Item must be an object.")
    if any(str(k) == "" for k in raw):
        raise _validation("Empty attribute name")
    try:
        return {str(k): _expr.validate_av(v) for k, v in raw.items()}
    except _expr.ExprError as exc:
        raise _validation(exc.message)


def _key_names(table: dict) -> list[str]:
    pk, sk = _table_key_fields(table)
    return [pk] + ([sk] if sk else [])


def _storage_key(table: dict, av_key: dict) -> str:
    return _item_key_string(table, {k: json_to_native(v) for k, v in av_key.items()})


def _check_item_keys(table: dict, item: dict) -> None:
    """Key-attribute validation for a full item (PutItem / BatchWrite Put / Transact Put)."""
    types = _attr_types(table)
    for k in _key_names(table):
        v = item.get(k)
        if v is None:
            raise _validation("One of the required keys was not given a value")
        if _expr.av_type(v) != types.get(k, _expr.av_type(v)):
            raise _validation("One or more parameter values were invalid: Type mismatch for key")
        t = _expr.av_type(v)
        if t in ("S", "B") and v[t] == "":
            raise _validation("One or more parameter values are not valid. The AttributeValue for a key attribute "
                              f"cannot contain an empty {'string' if t == 'S' else 'binary'} value. Key: {k}")
    for idx in list(table.get("indexes", [])) + list(table.get("local_indexes", [])):
        for k in (idx.get("partition_key_name"), idx.get("sort_key_name")):
            if not k or k not in item:
                continue
            v, want = item[k], types.get(k)
            t = _expr.av_type(v)
            if want and t != want:
                raise _validation("One or more parameter values were invalid: Type mismatch for Index Key")
            if t in ("S", "B") and v[t] == "":
                raise _validation("One or more parameter values are not valid. A value specified for a secondary index "
                                  "key is not supported. The AttributeValue for a key attribute cannot contain an empty "
                                  f"string value. IndexName: {idx.get('name')}, IndexKey: {k}")
    if _expr.item_size(item) > _expr.MAX_ITEM_BYTES:
        raise _validation("Item size has exceeded the maximum allowed size")


def _key_from_param(table: dict, raw: Any) -> tuple[dict, str]:
    """Validate a `Key` parameter (GetItem / DeleteItem / UpdateItem / BatchGet /
    BatchWrite Delete / Transact*). Returns (typed key, storage key)."""
    key = _validate_item(raw if isinstance(raw, dict) else {})
    names = _key_names(table)
    types = _attr_types(table)
    if len(key) != len(names):
        raise _validation("The number of conditions on the keys is invalid")
    for k in names:
        v = key.get(k)
        if v is None or _expr.av_type(v) != types.get(k, _expr.av_type(v)):
            raise _validation("The provided key element does not match the schema")
        t = _expr.av_type(v)
        if t in ("S", "B") and v[t] == "":
            raise _validation("One or more parameter values are not valid. The AttributeValue for a key attribute "
                              f"cannot contain an empty {'string' if t == 'S' else 'binary'} value. Key: {k}")
    return key, _storage_key(table, key)


class _Exprs:
    """All expressions of ONE request, parsed against one shared name/value
    context so unused ExpressionAttributeNames/Values are detected like DynamoDB."""

    def __init__(self, payload: dict):
        self.names = payload.get("ExpressionAttributeNames")
        self.values = payload.get("ExpressionAttributeValues")
        if self.values is not None and not self.values:
            raise _validation("ExpressionAttributeValues must not be empty")
        if self.names is not None and not self.names:
            raise _validation("ExpressionAttributeNames must not be empty")
        self.ctx = _expr._Ctx(self.names or {}, self.values or {})
        self.any = False

    def condition(self, text: Any, kind: str = "ConditionExpression"):
        if text is None:
            return None
        self.any = True
        try:
            return _expr.parse_condition(str(text), self.ctx)
        except _expr.ExprError as exc:
            raise _expr_error(kind, exc)

    def update(self, text: Any):
        if text is None:
            return None
        self.any = True
        try:
            return _expr.parse_update(str(text), self.ctx)
        except _expr.ExprError as exc:
            raise _expr_error("UpdateExpression", exc)

    def projection(self, text: Any):
        if text is None:
            return None
        self.any = True
        try:
            return _expr.parse_projection(str(text), self.ctx)
        except _expr.ExprError as exc:
            raise _expr_error("ProjectionExpression", exc)

    def finish(self) -> None:
        if self.values:
            unused = [k for k in self.values if k not in self.ctx.used_values]
            if not self.any:
                raise _validation("ExpressionAttributeValues can only be specified when using expressions: "
                                  "ConditionExpression is null")
            if unused:
                raise _validation("Value provided in ExpressionAttributeValues unused in expressions: keys: {"
                                  + ", ".join(unused) + "}")
        if self.names:
            unused = [k for k in self.names if k not in self.ctx.used_names]
            if not self.any:
                raise _validation("ExpressionAttributeNames can only be specified when using expressions")
            if unused:
                raise _validation("Value provided in ExpressionAttributeNames unused in expressions: keys: {"
                                  + ", ".join(unused) + "}")


# Legacy (pre-expression) parameters — Expected / KeyConditions / QueryFilter /
# ScanFilter / AttributesToGet — are translated into expressions so the one engine
# evaluates them (older SDK mappers, e.g. Java v1 DynamoDBMapper, still send them).
_LEGACY_OPS = {"EQ": "=", "NE": "<>", "LE": "<=", "LT": "<", "GE": ">=", "GT": ">"}


def _legacy_to_expr(conds: dict, conditional_op: str, payload: dict, prefix: str) -> str:
    names = payload.setdefault("ExpressionAttributeNames", {})
    values = payload.setdefault("ExpressionAttributeValues", {})
    parts = []
    for i, (attr, spec) in enumerate((conds or {}).items()):
        n = f"#{prefix}{i}"
        names[n] = attr
        spec = spec or {}
        vals = spec.get("AttributeValueList") or ([spec["Value"]] if "Value" in spec else [])
        op = str(spec.get("ComparisonOperator") or ("EQ" if "Value" in spec else "")).upper()
        if not op:
            exists = spec.get("Exists", True)
            parts.append(f"attribute_exists({n})" if exists else f"attribute_not_exists({n})")
            continue
        refs = []
        for j, v in enumerate(vals):
            r = f":{prefix}{i}_{j}"
            values[r] = v
            refs.append(r)
        if op in _LEGACY_OPS:
            parts.append(f"{n} {_LEGACY_OPS[op]} {refs[0]}")
        elif op == "NOT_NULL":
            parts.append(f"attribute_exists({n})")
        elif op == "NULL":
            parts.append(f"attribute_not_exists({n})")
        elif op == "CONTAINS":
            parts.append(f"contains({n}, {refs[0]})")
        elif op == "NOT_CONTAINS":
            parts.append(f"NOT contains({n}, {refs[0]})")
        elif op == "BEGINS_WITH":
            parts.append(f"begins_with({n}, {refs[0]})")
        elif op == "BETWEEN":
            parts.append(f"{n} BETWEEN {refs[0]} AND {refs[1]}")
        elif op == "IN":
            parts.append(f"{n} IN ({', '.join(refs)})")
        else:
            raise _validation(f"Unsupported operator on KeyCondition: {op}")
    if not values:
        payload.pop("ExpressionAttributeValues", None)
    return f" {str(conditional_op or 'AND').upper()} ".join(parts)


def _translate_legacy(payload: dict) -> dict:
    payload = dict(payload)
    if payload.get("Expected") and not payload.get("ConditionExpression"):
        payload["ConditionExpression"] = _legacy_to_expr(payload.pop("Expected"), payload.get("ConditionalOperator"), payload, "lx")
    if payload.get("KeyConditions") and not payload.get("KeyConditionExpression"):
        payload["KeyConditionExpression"] = _legacy_to_expr(payload.pop("KeyConditions"), "AND", payload, "lk")
    for key in ("QueryFilter", "ScanFilter"):
        if payload.get(key) and not payload.get("FilterExpression"):
            payload["FilterExpression"] = _legacy_to_expr(payload.pop(key), payload.get("ConditionalOperator"), payload, "lf")
    if payload.get("AttributesToGet") and not payload.get("ProjectionExpression"):
        names = payload.setdefault("ExpressionAttributeNames", {})
        refs = []
        for i, a in enumerate(payload.pop("AttributesToGet")):
            names[f"#la{i}"] = a
            refs.append(f"#la{i}")
        payload["ProjectionExpression"] = ", ".join(refs)
    return payload


def _ccf(old: dict | None, payload: dict) -> DdbError:
    extra = {}
    if old and str(payload.get("ReturnValuesOnConditionCheckFailure") or "").upper() == "ALL_OLD":
        extra["Item"] = copy.deepcopy(old)
    return DdbError("ConditionalCheckFailedException", "The conditional request failed", 400, extra)


def _rv(payload: dict, allowed: tuple) -> str:
    rv = str(payload.get("ReturnValues") or "NONE").upper()
    if rv not in allowed:
        raise _validation("Return values set to invalid value")
    return rv


# ── single-item operations ─────────────────────────────────────────────────
def _op_put(store: NoSqlStore, payload: dict) -> dict:
    table = _require_table(store, str(payload.get("TableName") or ""))
    item = _validate_item(payload.get("Item"))
    _check_item_keys(table, item)
    rv = _rv(payload, ("NONE", "ALL_OLD"))
    ex = _Exprs(payload)
    cond = ex.condition(payload.get("ConditionExpression"))
    ex.finish()
    key = _storage_key(table, {k: item[k] for k in _key_names(table)})
    rec = table.get("items", {}).get(key)
    old = _rec_av(rec) if rec else None
    if cond is not None and not _expr.evaluate(cond, old or {}):
        raise _ccf(old, payload)
    store.enforce_storage_cap(_expr.item_size(item))
    _store_av(store, table, key, item)
    _refresh_table_metrics(table)
    store.persist()
    return {"Attributes": copy.deepcopy(old)} if rv == "ALL_OLD" and old else {}


def _op_get(store: NoSqlStore, payload: dict) -> dict:
    table = _require_table(store, str(payload.get("TableName") or ""))
    _expire_table_items(table)
    _, key = _key_from_param(table, payload.get("Key"))
    ex = _Exprs(payload)
    proj = ex.projection(payload.get("ProjectionExpression"))
    ex.finish()
    rec = table.get("items", {}).get(key)
    if not rec:
        return {}
    item = _rec_av(rec)
    return {"Item": _expr.project_paths(item, proj) if proj is not None else copy.deepcopy(item)}


def _op_delete(store: NoSqlStore, payload: dict) -> dict:
    table = _require_table(store, str(payload.get("TableName") or ""))
    _, key = _key_from_param(table, payload.get("Key"))
    rv = _rv(payload, ("NONE", "ALL_OLD"))
    ex = _Exprs(payload)
    cond = ex.condition(payload.get("ConditionExpression"))
    ex.finish()
    rec = table.get("items", {}).get(key)
    old = _rec_av(rec) if rec else None
    if cond is not None and not _expr.evaluate(cond, old or {}):
        raise _ccf(old, payload)
    if rec:
        _drop_key(store, table, key)
        _refresh_table_metrics(table)
        store.persist()
    return {"Attributes": copy.deepcopy(old)} if rv == "ALL_OLD" and old else {}


def _apply_attribute_updates(table: dict, current: dict, updates: dict) -> tuple[dict, list]:
    new = copy.deepcopy(current)
    touched = []
    keys = set(_key_names(table))
    for name, spec in (updates or {}).items():
        if name in keys:
            raise _validation("One or more parameter values were invalid: Cannot update attribute "
                              f"{name}. This attribute is part of the key")
        spec = spec if isinstance(spec, dict) else {}
        action = str(spec.get("Action", "PUT")).upper()
        value = _expr.validate_av(spec["Value"]) if spec.get("Value") is not None else None
        touched.append([name])
        cur = new.get(name)
        if action == "PUT":
            if value is None:
                raise _validation("One or more parameter values were invalid: Only DELETE action is allowed when no "
                                  "attribute value is specified")
            new[name] = value
        elif action == "DELETE":
            if value is None:
                new.pop(name, None)
            elif cur is not None:
                t = _expr.av_type(value)
                if t != _expr.av_type(cur) or t not in ("SS", "NS", "BS"):
                    raise _validation("Type mismatch for attribute to update")
                rest = [x for x in cur[t] if not any(_expr.av_eq({t[0]: x}, {t[0]: y}) for y in value[t])]
                if rest:
                    new[name] = {t: rest}
                else:
                    new.pop(name, None)
        elif action == "ADD":
            t = _expr.av_type(value)
            if cur is None:
                new[name] = value
            elif t == "N" and _expr.av_type(cur) == "N":
                new[name] = {"N": _expr._arith(cur["N"], value["N"], "+")}
            elif t == _expr.av_type(cur) and t in ("SS", "NS", "BS"):
                new[name] = {t: list(cur[t]) + [x for x in value[t]
                                                if not any(_expr.av_eq({t[0]: x}, {t[0]: y}) for y in cur[t])]}
            else:
                raise _validation("Type mismatch for attribute to update")
    return new, touched


def _op_update(store: NoSqlStore, payload: dict) -> dict:
    table = _require_table(store, str(payload.get("TableName") or ""))
    key_av, key = _key_from_param(table, payload.get("Key"))
    rv = _rv(payload, ("NONE", "ALL_OLD", "UPDATED_OLD", "ALL_NEW", "UPDATED_NEW"))
    ex = _Exprs(payload)
    cond = ex.condition(payload.get("ConditionExpression"))
    actions = ex.update(payload.get("UpdateExpression"))
    ex.finish()
    rec = table.get("items", {}).get(key)
    old = _rec_av(rec) if rec else None
    if cond is not None and not _expr.evaluate(cond, old or {}):
        raise _ccf(old, payload)
    base = old if old is not None else copy.deepcopy(key_av)
    try:
        if actions is not None:
            for a in actions:
                if a[1][0] in _key_names(table):
                    raise _validation("One or more parameter values were invalid: Cannot update attribute "
                                      f"{a[1][0]}. This attribute is part of the key")
            new, touched = _expr.apply_actions(base, actions)
        else:
            new, touched = _apply_attribute_updates(table, base, payload.get("AttributeUpdates") or {})
    except _expr.ExprError as exc:
        raise _expr_error("UpdateExpression", exc)
    _check_item_keys(table, new)
    store.enforce_storage_cap(_expr.item_size(new))
    _store_av(store, table, key, new)
    _refresh_table_metrics(table)
    store.persist()
    if rv == "NONE":
        return {}
    if rv == "ALL_OLD":
        return {"Attributes": copy.deepcopy(old)} if old else {}
    if rv == "ALL_NEW":
        return {"Attributes": copy.deepcopy(new)}
    if rv == "UPDATED_NEW" and actions is not None:
        touched = [a[1] for a in actions if a[0] != "REMOVE"]     # a REMOVEd path has no new value
    src = old if rv == "UPDATED_OLD" else new
    out = _expr.project_paths(src or {}, [[p[0]] for p in touched])   # whole top-level attributes
    return {"Attributes": out} if out else {}


# ── Query / Scan ───────────────────────────────────────────────────────────
def _index_spec(table: dict, index_name: str) -> dict | None:
    for idx in list(table.get("indexes", [])) + list(table.get("local_indexes", [])):
        if idx.get("name") == index_name:
            return idx
    return None


def _read_keys(table: dict, index_name: str) -> tuple[str, str, dict | None]:
    if not index_name:
        pk, sk = _table_key_fields(table)
        return pk, sk, None
    idx = _index_spec(table, index_name)
    if idx is None:
        raise _validation(f"The table does not have the specified index: {index_name}")
    return str(idx.get("partition_key_name", "")), str(idx.get("sort_key_name", "") or ""), idx


def _index_project(table: dict, idx: dict | None, item: dict) -> dict:
    if idx is None:
        return item
    proj = idx.get("projection") or {}
    ptype = str(proj.get("ProjectionType") or "ALL").upper()
    if ptype == "ALL":
        return item
    keep = set(_key_names(table)) | {idx.get("partition_key_name"), idx.get("sort_key_name")}
    if ptype == "INCLUDE":
        keep |= set(proj.get("NonKeyAttributes") or [])
    return {k: v for k, v in item.items() if k in keep}


def _order_tuple(table: dict, item: dict, pk: str, sk: str) -> tuple:
    tk = tuple(_expr.sort_value(item.get(k)) for k in _key_names(table))
    return (_expr.sort_value(item.get(sk)) if sk else (0,),) + tk


def _read(store: NoSqlStore, payload: dict, query: bool) -> dict:
    table = _require_table(store, str(payload.get("TableName") or ""))
    _expire_table_items(table)
    index_name = str(payload.get("IndexName") or "").strip()
    pk, sk, idx = _read_keys(table, index_name)
    ex = _Exprs(payload)
    pk_val = sk_node = None
    if query:
        kce = payload.get("KeyConditionExpression")
        if kce is None:
            raise _validation("Either the KeyConditions or KeyConditionExpression parameter must be specified in the request.")
        node = ex.condition(kce, "KeyConditionExpression")
        try:
            pk_val, sk_node = _expr.split_key_condition(node, pk, sk)
        except _expr.ExprError as exc:
            raise _expr_error("KeyConditionExpression", exc)
        types = _attr_types(table)
        sk_vals = [n[1] for n in (sk_node[2:] if sk_node and sk_node[0] in ("cmp", "between") else
                                  (sk_node[2] if sk_node else [])) if isinstance(n, tuple) and n[0] == "val"]
        if _expr.av_type(pk_val) != types.get(pk, _expr.av_type(pk_val)) or \
                (sk and sk_node is not None and sk_node[0] != "func"
                 and any(_expr.av_type(v) != types.get(sk, _expr.av_type(v)) for v in sk_vals)):
            raise _validation("One or more parameter values were invalid: Condition parameter type does not match schema type")
    if idx is not None and payload.get("ConsistentRead") and idx in table.get("indexes", []):
        raise _validation("Consistent reads are not supported on global secondary indexes")
    filt = ex.condition(payload.get("FilterExpression"), "FilterExpression")
    proj = ex.projection(payload.get("ProjectionExpression"))
    ex.finish()
    if query and filt is not None:
        for path in _expr.condition_paths(filt):
            if path and path[0] in (pk, sk):
                raise _validation(f"Filter Expression can only contain non-primary key attributes: "
                                  f"Primary key attribute: {path[0]}")
    select = str(payload.get("Select") or "").upper()
    if select and select not in ("ALL_ATTRIBUTES", "ALL_PROJECTED_ATTRIBUTES", "SPECIFIC_ATTRIBUTES", "COUNT"):
        raise _validation("1 validation error detected: Value '%s' at 'select' failed to satisfy constraint: Member "
                          "must satisfy enum value set: [SPECIFIC_ATTRIBUTES, COUNT, ALL_ATTRIBUTES, "
                          "ALL_PROJECTED_ATTRIBUTES]" % payload.get("Select"))
    limit = payload.get("Limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise _validation("Limit must be an integer")
        if limit < 1:
            raise _validation("Limit must be greater than or equal to 1")

    rows = [_rec_av(r) for r in (table.get("items") or {}).values() if isinstance(r, dict)]
    if idx is not None:     # a sparse index holds only the items carrying its keys
        rows = [r for r in rows if pk in r and (not sk or sk in r)]
    if query:
        rows = [r for r in rows if _expr.av_eq(r.get(pk), pk_val) and (sk_node is None or _expr.evaluate(sk_node, r))]
        rows.sort(key=lambda r: _order_tuple(table, r, pk, sk))
        forward = payload.get("ScanIndexForward") is not False
        if not forward:
            rows.reverse()
    else:
        seg, total = payload.get("Segment"), payload.get("TotalSegments")
        if (seg is None) != (total is None):
            raise _validation("The TotalSegments parameter is required but was not present in the request when "
                              "Segment parameter is present" if total is None else
                              "The Segment parameter is required but was not present in the request when parameter "
                              "TotalSegments is present")
        if total is not None:
            seg, total = int(seg), int(total)
            if not (1 <= total <= 1000000) or not (0 <= seg < total):
                raise _validation(f"The Segment parameter is zero-based and must be less than parameter TotalSegments: "
                                  f"Segment: {seg} is not less than TotalSegments: {total}")
            rows = [r for r in rows if zlib.crc32(_storage_key(table, {k: r[k] for k in _key_names(table)}).encode())
                    % total == seg]
        rows.sort(key=lambda r: _storage_key(table, {k: r[k] for k in _key_names(table)}))
        forward = True
    esk = payload.get("ExclusiveStartKey")
    if isinstance(esk, dict) and esk:
        esk = _validate_item(esk)
        need = set(_key_names(table)) | ({pk, sk} - {""} if idx is not None else set())
        if set(esk) != need:
            raise _validation("The provided starting key is invalid: The provided key element does not match the schema")
        if query:
            if not _expr.av_eq(esk.get(pk), pk_val):
                raise _validation("The provided starting key does not match the range key predicate")
            mark = _order_tuple(table, esk, pk, sk)
            rows = [r for r in rows if (_order_tuple(table, r, pk, sk) > mark) == forward
                    and _order_tuple(table, r, pk, sk) != mark]
        else:
            mark = _storage_key(table, {k: esk[k] for k in _key_names(table)})
            rows = [r for r in rows if _storage_key(table, {k: r[k] for k in _key_names(table)}) > mark]
    page = rows[:limit] if limit else rows
    out = [r for r in page if filt is None or _expr.evaluate(filt, r)]
    body: dict = {"Count": len(out), "ScannedCount": len(page)}
    if select != "COUNT":
        items = [_index_project(table, idx, r) for r in out]
        if proj is not None:
            items = [_expr.project_paths(r, proj) for r in items]
        body["Items"] = [copy.deepcopy(r) for r in items]
    if limit and len(page) == limit and page and not (query and _at_far_bound(sk_node, page[-1], sk, forward)):
        last = page[-1]
        names = list(_key_names(table)) + ([a for a in (pk, sk) if a and a not in _key_names(table)] if idx else [])
        body["LastEvaluatedKey"] = {a: copy.deepcopy(last[a]) for a in names if a in last}
    return body


def _at_far_bound(sk_node, last: dict, sk: str, forward: bool) -> bool:
    """True when the last item read sits exactly on the inclusive far bound of the
    sort-key condition — DynamoDB then knows the range is exhausted and returns no
    LastEvaluatedKey even though Limit was reached (measured against DynamoDB Local)."""
    if not sk_node or not sk or sk not in last:
        return False
    bound = None
    if sk_node[0] == "between":
        bound = sk_node[3] if forward else sk_node[2]
    elif sk_node[0] == "cmp" and sk_node[1] in ("<=", ">="):
        path_left = sk_node[2][0] == "path"
        op = sk_node[1] if path_left else {"<=": ">=", ">=": "<="}[sk_node[1]]
        if (op == "<=" and forward) or (op == ">=" and not forward):
            bound = sk_node[3] if path_left else sk_node[2]
    return bool(bound and bound[0] == "val" and _expr.av_eq(last.get(sk), bound[1]))


# ── batch / transactions ───────────────────────────────────────────────────
def _op_batch_write(store: NoSqlStore, payload: dict) -> dict:
    req = payload.get("RequestItems") or {}
    if not req:
        raise _validation("1 validation error detected: Value null at 'requestItems' failed to satisfy constraint: "
                          "Member must not be null")
    total = sum(len(v or []) for v in req.values())
    if total > 25:
        raise _validation("Too many items requested for the BatchWriteItem call")
    plan = []
    for tname, ops in req.items():
        table = _require_table(store, str(tname))
        seen = set()
        for op in ops or []:
            if "PutRequest" in op:
                item = _validate_item((op["PutRequest"] or {}).get("Item"))
                _check_item_keys(table, item)
                key = _storage_key(table, {k: item[k] for k in _key_names(table)})
                plan.append(("put", table, key, item))
            elif "DeleteRequest" in op:
                _, key = _key_from_param(table, (op["DeleteRequest"] or {}).get("Key"))
                plan.append(("del", table, key, None))
            else:
                raise _validation("Supplied AttributeValue has more than one datatypes set, must contain exactly one "
                                  "of the supported datatypes")
            if key in seen:
                raise _validation("Provided list of item keys contains duplicates")
            seen.add(key)
    for kind, table, key, item in plan:
        if kind == "put":
            store.enforce_storage_cap(_expr.item_size(item))
            _store_av(store, table, key, item)
        else:
            _drop_key(store, table, key)
        _refresh_table_metrics(table)
    store.persist()
    return {"UnprocessedItems": {}}


def _op_batch_get(store: NoSqlStore, payload: dict) -> dict:
    req = payload.get("RequestItems") or {}
    if sum(len((v or {}).get("Keys") or []) for v in req.values()) > 100:
        raise _validation("Too many items requested for the BatchGetItem call")
    responses: dict = {}
    for tname, spec in req.items():
        spec = spec or {}
        table = _require_table(store, str(tname))
        _expire_table_items(table)
        spec = _translate_legacy(spec)
        ex = _Exprs(spec)
        proj = ex.projection(spec.get("ProjectionExpression"))
        ex.finish()
        rows, seen = [], set()
        for k in spec.get("Keys") or []:
            _, key = _key_from_param(table, k)
            if key in seen:
                raise _validation("Provided list of item keys contains duplicates")
            seen.add(key)
            rec = table.get("items", {}).get(key)
            if rec:
                item = _rec_av(rec)
                rows.append(_expr.project_paths(item, proj) if proj is not None else copy.deepcopy(item))
        responses[tname] = rows
    return {"Responses": responses, "UnprocessedKeys": {}}


def _op_transact_write(store: NoSqlStore, payload: dict) -> dict:
    ops = payload.get("TransactItems") or payload.get("transact_items") or []
    if not ops:
        raise _validation("1 validation error detected: Value null at 'transactItems' failed to satisfy constraint: "
                          "Member must not be null")
    if len(ops) > 100:
        raise _validation("1 validation error detected: Value at 'transactItems' failed to satisfy constraint: "
                          "Member must have length less than or equal to 100")
    planned, seen = [], set()
    for entry in ops:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise _validation("TransactItems can only contain one of Check, Put, Update or Delete")
        kind, spec = next(iter(entry.items()))
        spec = _translate_legacy(spec or {})
        table = _require_table(store, str(spec.get("TableName") or ""))
        ex = _Exprs(spec)
        cond = ex.condition(spec.get("ConditionExpression"))
        actions = None
        if kind == "Put":
            item = _validate_item(spec.get("Item"))
            _check_item_keys(table, item)
            key = _storage_key(table, {k: item[k] for k in _key_names(table)})
            key_av = {k: item[k] for k in _key_names(table)}
        elif kind in ("Update", "Delete", "ConditionCheck"):
            key_av, key = _key_from_param(table, spec.get("Key"))
            item = None
            if kind == "Update":
                actions = ex.update(spec.get("UpdateExpression"))
                if actions is None:
                    raise _validation("1 validation error detected: Value null at 'transactItems.1.member.update."
                                      "updateExpression' failed to satisfy constraint: Member must not be null")
                for a in actions:
                    if a[1][0] in _key_names(table):
                        raise _validation("One or more parameter values were invalid: Cannot update attribute "
                                          f"{a[1][0]}. This attribute is part of the key")
            if kind == "ConditionCheck" and cond is None:
                raise _validation("The expression can not be empty;")
        else:
            raise _validation(f"Invalid TransactItems member: {kind}")
        ex.finish()
        planned.append((kind, table, key, key_av, item, cond, actions, spec))
    reasons, failed, results = [], False, []
    staged: dict = {}      # (table, key) -> item after the earlier operations of this request
    for kind, table, key, key_av, item, cond, actions, spec in planned:
        ident = (table["table_name"], key)
        if ident in staged:
            old = staged[ident]
        else:
            rec = table.get("items", {}).get(key)
            old = _rec_av(rec) if rec else None
        new = None
        if cond is not None and not _expr.evaluate(cond, old or {}):
            r = {"Code": "ConditionalCheckFailed", "Message": "The conditional request failed"}
            if old and str(spec.get("ReturnValuesOnConditionCheckFailure") or "").upper() == "ALL_OLD":
                r["Item"] = copy.deepcopy(old)
            reasons.append(r)
            failed = True
            continue
        if kind == "Update":
            try:
                new, _ = _expr.apply_actions(old if old is not None else copy.deepcopy(key_av), actions)
            except _expr.ExprError as exc:
                raise _expr_error("UpdateExpression", exc)
            _check_item_keys(table, new)
        reasons.append({"Code": "None"})
        results.append((kind, table, key, item if kind == "Put" else new))
        if kind != "ConditionCheck":
            staged[ident] = item if kind == "Put" else (new if kind == "Update" else None)
    # (DynamoDB Local reports failed conditions before the one-operation-per-item rule)
    if not failed:
        for kind, table, key, *_ in planned:
            if (table["table_name"], key) in seen:
                raise _validation("Transaction request cannot include multiple operations on one item")
            seen.add((table["table_name"], key))
    if failed:
        codes = ", ".join(r["Code"] for r in reasons)
        raise DdbError("TransactionCanceledException",
                       f"Transaction cancelled, please refer cancellation reasons for specific reasons [{codes}]",
                       400, {"CancellationReasons": reasons})
    for kind, table, key, item in results:
        if kind in ("Put", "Update"):
            _store_av(store, table, key, item)
        elif kind == "Delete":
            _drop_key(store, table, key)
        _refresh_table_metrics(table)
    store.persist()
    return {}


def _op_transact_get(store: NoSqlStore, payload: dict) -> dict:
    ops = payload.get("TransactItems") or payload.get("transact_items") or []
    plan, seen = [], set()
    for entry in ops:
        spec = _translate_legacy((entry or {}).get("Get") or {})
        table = _require_table(store, str(spec.get("TableName") or ""))
        _, key = _key_from_param(table, spec.get("Key"))
        ex = _Exprs(spec)
        proj = ex.projection(spec.get("ProjectionExpression"))
        ex.finish()
        if (table["table_name"], key) in seen:
            raise _validation("Transaction request cannot include multiple operations on one item")
        seen.add((table["table_name"], key))
        plan.append((table, key, proj))
    responses = []
    for table, key, proj in plan:
        rec = table.get("items", {}).get(key)
        if not rec:
            responses.append({})
            continue
        item = _rec_av(rec)
        responses.append({"Item": _expr.project_paths(item, proj) if proj is not None else copy.deepcopy(item)})
    return {"Responses": responses}


# ── PartiQL (ExecuteStatement) ──────────────────────────────────────────────
# SELECT [*|paths] FROM "t"["."index"] [WHERE cond], INSERT INTO "t" VALUE {map},
# UPDATE "t" SET a = v[, ...] [REMOVE b] WHERE key-eqs [AND cond],
# DELETE FROM "t" WHERE key-eqs [AND cond]. WHERE clauses are translated into the
# condition-expression engine (= <> != < <= > >=, AND/OR/NOT, BETWEEN, IN [..],
# begins_with/contains/attribute_type/size, IS [NOT] MISSING).
_PQ_TOKEN = re.compile(r"""\s*(?:
    (?P<str>'(?:[^']|'')*')
  | (?P<qid>"(?:[^"]|"")*")
  | (?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<op><<|>>|<>|!=|<=|>=|=|<|>)
  | (?P<punct>[(){}\[\],:.*?])
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
)""", re.X)


def _pq_tokens(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = text.strip().rstrip(";")
    while pos < len(text):
        if not text[pos:].strip():
            break
        m = _PQ_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise _validation(f"Statement wasn't well formed, can't be processed: unexpected token near "
                              f"'{text[pos:pos + 10]}'")
        pos = m.end()
        out.append((m.lastgroup, m.group(m.lastgroup)))
    return out


class _PQ:
    def __init__(self, toks, params):
        self.t, self.i, self.params = toks, 0, list(params or [])
        self.pi = 0
        self.names: dict = {}
        self.values: dict = {}

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def word(self, w: str) -> bool:
        k, t = self.peek()
        return k == "word" and t.upper() == w

    def take(self, kind=None, text=None):
        k, t = self.peek()
        if k is None or (kind and k != kind) or (text and (t.upper() if k == "word" else t) != text):
            raise _validation("Statement wasn't well formed, can't be processed: Unexpected "
                              + (f"token '{t}'" if k else "end of statement"))
        self.i += 1
        return k, t

    def ident(self) -> str:
        k, t = self.take()
        if k == "qid":
            return t[1:-1].replace('""', '"')
        if k == "word":
            return t
        raise _validation(f"Statement wasn't well formed, can't be processed: Unexpected token '{t}'")

    def literal(self) -> dict:
        k, t = self.peek()
        if k == "punct" and t == "?":
            self.take()
            if self.pi >= len(self.params):
                raise _validation("Number of parameters in request and statement don't match.")
            v = self.params[self.pi]
            self.pi += 1
            try:
                return _expr.validate_av(v)
            except _expr.ExprError as exc:
                raise _validation(exc.message)
        if k == "str":
            self.take()
            return {"S": t[1:-1].replace("''", "'")}
        if k == "num":
            self.take()
            try:
                return {"N": _expr.canon_number(t)}
            except _expr.ExprError as exc:
                raise _validation(exc.message)
        if k == "word" and t.upper() in ("TRUE", "FALSE"):
            self.take()
            return {"BOOL": t.upper() == "TRUE"}
        if k == "word" and t.upper() == "NULL":
            self.take()
            return {"NULL": True}
        if (k, t) == ("punct", "{"):
            self.take()
            m: dict = {}
            while self.peek() != ("punct", "}"):
                kk, tt = self.take()
                if kk not in ("str", "qid"):
                    raise _validation("Statement wasn't well formed, can't be processed: map keys must be strings")
                self.take("punct", ":")
                m[tt[1:-1]] = self.literal()
                if self.peek() == ("punct", ","):
                    self.take()
            self.take("punct", "}")
            return {"M": m}
        if (k, t) == ("punct", "["):
            self.take()
            items = []
            while self.peek() != ("punct", "]"):
                items.append(self.literal())
                if self.peek() == ("punct", ","):
                    self.take()
            self.take("punct", "]")
            return {"L": items}
        if (k, t) == ("op", "<<"):
            self.take()
            items = []
            while self.peek() != ("op", ">>"):
                items.append(self.literal())
                if self.peek() == ("punct", ","):
                    self.take()
            self.take("op", ">>")
            ts = {_expr.av_type(x) for x in items}
            if len(ts) != 1 or next(iter(ts)) not in ("S", "N", "B"):
                raise _validation("Statement wasn't well formed, can't be processed: invalid set literal")
            t0 = next(iter(ts))
            return {t0 + "S": [x[t0] for x in items]}
        raise _validation(f"Statement wasn't well formed, can't be processed: Unexpected token '{t}'")

    def _name(self, attr: str) -> str:
        ref = f"#p{len(self.names)}"
        self.names[ref] = attr
        return ref

    def _value(self, av: dict) -> str:
        ref = f":p{len(self.values)}"
        self.values[ref] = av
        return ref

    def path(self) -> str:
        parts = [self._name(self.ident())]
        while True:
            if self.peek() == ("punct", "."):
                self.take()
                parts.append("." + self._name(self.ident()))
            elif self.peek() == ("punct", "["):
                self.take()
                k, t = self.take("num")
                self.take("punct", "]")
                parts.append(f"[{t}]")
            else:
                return "".join(parts)

    def operand(self) -> str:
        k, t = self.peek()
        if k in ("str", "num") or (k == "punct" and t in ("?", "{", "[")) or (k == "op" and t == "<<") or \
                (k == "word" and t.upper() in ("TRUE", "FALSE", "NULL")):
            return self._value(self.literal())
        if k == "word" and t.lower() == "size" and self.peek(1) == ("punct", "("):
            self.take()
            self.take("punct", "(")
            p = self.path()
            self.take("punct", ")")
            return f"size({p})"
        return self.path()

    def cond(self) -> str:
        left = self.conj()
        while self.word("OR"):
            self.take()
            left = f"({left}) OR ({self.conj()})"
        return left

    def conj(self) -> str:
        left = self.neg()
        while self.word("AND"):
            self.take()
            left = f"{left} AND {self.neg()}"
        return left

    def neg(self) -> str:
        if self.word("NOT"):
            self.take()
            return f"NOT ({self.neg()})"
        if self.peek() == ("punct", "("):
            self.take()
            c = self.cond()
            self.take("punct", ")")
            return f"({c})"
        k, t = self.peek()
        if k == "word" and t.lower() in ("begins_with", "contains", "attribute_type") and self.peek(1) == ("punct", "("):
            self.take()
            self.take("punct", "(")
            a = self.path()
            self.take("punct", ",")
            b = self.operand()
            self.take("punct", ")")
            return f"{t.lower()}({a}, {b})"
        left = self.operand()
        k, t = self.peek()
        if k == "op":
            self.take()
            return f"{left} {'<>' if t == '!=' else t} {self.operand()}"
        if self.word("BETWEEN"):
            self.take()
            lo = self.operand()
            self.take("word", "AND")
            return f"{left} BETWEEN {lo} AND {self.operand()}"
        if self.word("IN"):
            self.take()
            close = "]" if self.peek() == ("punct", "[") else ")"
            self.take("punct")
            opts = [self.operand()]
            while self.peek() == ("punct", ","):
                self.take()
                opts.append(self.operand())
            self.take("punct", close)
            return f"{left} IN ({', '.join(opts)})"
        if self.word("IS"):
            self.take()
            neg = False
            if self.word("NOT"):
                self.take()
                neg = True
            self.take("word", "MISSING")
            return f"attribute_exists({left})" if neg else f"attribute_not_exists({left})"
        raise _validation("Statement wasn't well formed, can't be processed: Unexpected "
                          + (f"token '{t}'" if k else "end of statement"))

    def table_ref(self) -> tuple[str, str]:
        name = self.ident()
        index = ""
        if self.peek() == ("punct", "."):
            self.take()
            index = self.ident()
        return name, index


def _pq_where_key(table: dict, where: str, names: dict, values: dict) -> dict | None:
    """The full primary key when the WHERE clause pins every key attribute by equality."""
    key = {}
    for k in _key_names(table):
        ref = next((r for r, a in names.items() if a == k), None)
        if not ref:
            return None
        m = re.search(rf"(?:^|\s|\(){re.escape(ref)} = (:p\d+)", where)
        if not m:
            return None
        key[k] = values[m.group(1)]
    return key


def _execute_statement(store: NoSqlStore, payload: dict[str, Any]) -> DdbResponse:
    stmt = str(payload.get("Statement") or "").strip()
    toks = _pq_tokens(stmt)
    p = _PQ(toks, payload.get("Parameters"))
    if not toks:
        raise _validation("Statement wasn't well formed, can't be processed: empty statement")
    verb = toks[0][1].upper()

    def condition(where: str):
        if not where:
            return None
        ctx = _expr._Ctx(p.names, p.values)
        try:
            return _expr.parse_condition(where, ctx)
        except _expr.ExprError as exc:
            raise _validation(f"Statement wasn't well formed, can't be processed: {exc.message}")

    def finish():
        if p.peek()[0] is not None:
            raise _validation(f"Statement wasn't well formed, can't be processed: Unexpected token '{p.peek()[1]}'")
        if p.pi != len(p.params):
            raise _validation("Number of parameters in request and statement don't match.")

    if verb == "SELECT":
        p.take()
        paths = None
        if p.peek() == ("punct", "*"):
            p.take()
        else:
            paths = [p.path()]
            while p.peek() == ("punct", ","):
                p.take()
                paths.append(p.path())
        p.take("word", "FROM")
        tname, index = p.table_ref()
        where = ""
        if p.word("WHERE"):
            p.take()
            where = p.cond()
        finish()
        table = _require_table(store, tname)
        _expire_table_items(table)
        pk, sk, idx = _read_keys(table, index)
        node = condition(where)
        rows = [_rec_av(r) for r in (table.get("items") or {}).values() if isinstance(r, dict)]
        if idx is not None:
            rows = [r for r in rows if pk in r and (not sk or sk in r)]
        rows = [r for r in rows if node is None or _expr.evaluate(node, r)]
        rows.sort(key=lambda r: (_expr.sort_value(r.get(pk)), _order_tuple(table, r, pk, sk)))
        rows = [_index_project(table, idx, r) for r in rows]
        if paths:
            ctx = _expr._Ctx(p.names, {})
            proj = [ctx.path(x) for x in paths]
            rows = [_expr.project_paths(r, proj) for r in rows]
        return _ok({"Items": [copy.deepcopy(r) for r in rows]})

    if verb == "INSERT":
        p.take()
        p.take("word", "INTO")
        tname, _ = p.table_ref()
        p.take("word", "VALUE")
        value = p.literal()
        finish()
        if _expr.av_type(value) != "M":
            raise _validation("Unsupported operation: Inserting a non-map value is not supported.")
        table = _require_table(store, tname)
        item = value["M"]
        _check_item_keys(table, item)
        key = _storage_key(table, {k: item[k] for k in _key_names(table)})
        if table.get("items", {}).get(key):
            raise DdbError("DuplicateItemException", "Duplicate primary key exists in table", 400)
        store.enforce_storage_cap(_expr.item_size(item))
        _store_av(store, table, key, item)
        _refresh_table_metrics(table)
        store.persist()
        return _ok({"Items": []})

    if verb in ("UPDATE", "DELETE"):
        p.take()
        if verb == "DELETE":
            p.take("word", "FROM")
        tname, _ = p.table_ref()
        sets, removes = [], []
        if verb == "UPDATE":
            while p.word("SET") or p.word("REMOVE"):
                kw = p.take()[1].upper()
                while True:
                    target = p.path()
                    if kw == "SET":
                        p.take("op", "=")
                        rhs = p.operand()
                        sets.append(f"{target} = {rhs}")
                    else:
                        removes.append(target)
                    if p.peek() == ("punct", ","):
                        p.take()
                        continue
                    break
            if not sets and not removes:
                raise _validation("Statement wasn't well formed, can't be processed: UPDATE requires SET or REMOVE")
        p.take("word", "WHERE")
        where = p.cond()
        finish()
        table = _require_table(store, tname)
        key = _pq_where_key(table, where, p.names, p.values)
        if key is None:
            raise _validation("Where clause does not contain a mandatory equality on all key attributes")
        node = condition(where)
        skey = _storage_key(table, key)
        rec = table.get("items", {}).get(skey)
        old = _rec_av(rec) if rec else None
        if old is None or not _expr.evaluate(node, old):
            if verb == "DELETE" and old is None:
                return _ok({"Items": []})
            raise DdbError("ConditionalCheckFailedException", "The conditional request failed", 400)
        if verb == "DELETE":
            _drop_key(store, table, skey)
        else:
            expr = ""
            if sets:
                expr += "SET " + ", ".join(sets)
            if removes:
                expr += " REMOVE " + ", ".join(removes)
            ctx = _expr._Ctx(p.names, p.values)
            try:
                actions = _expr.parse_update(expr, ctx)
                for a in actions:
                    if a[1][0] in _key_names(table):
                        raise _validation("One or more parameter values were invalid: Cannot update attribute "
                                          f"{a[1][0]}. This attribute is part of the key")
                new, _ = _expr.apply_actions(old, actions)
            except _expr.ExprError as exc:
                raise _validation(exc.message)
            _check_item_keys(table, new)
            _store_av(store, table, skey, new)
        _refresh_table_metrics(table)
        store.persist()
        return _ok({"Items": []})

    raise _validation(f"Statement wasn't well formed, can't be processed: Unsupported statement '{toks[0][1]}'")


# ── response builders ───────────────────────────────────────────────────────
def _ok(body: dict | None = None) -> DdbResponse:
    return DdbResponse(status=200, body=body or {}, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400, extra: dict | None = None) -> DdbResponse:
    body = {"__type": code, "message": message}
    body.update(extra or {})
    return DdbResponse(status=status, body=body, headers={"x-amzn-requestid": _req_id()})


# ── console-REST shaped Query / Scan (Nano adapter + /api/dynamodb payloads) ─
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



# ── native-wire dispatcher (X-Amz-Target action → operation) ───────────────
# The single routing point for the native AWS DynamoDB JSON protocol — what an
# unmodified aws-cli / boto3 client speaks. Shared by the Nano relay/bridge (tab
# side) and the appliance's unified ingress. `target` is the raw X-Amz-Target
# header, e.g. "DynamoDB_20120810.PutItem"; `payload` is the parsed JSON body.
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
        if action in ("PutItem", "GetItem", "DeleteItem", "UpdateItem", "Query", "Scan",
                      "BatchWriteItem", "BatchGetItem", "TransactWriteItems", "TransactGetItems"):
            payload = _translate_legacy(payload)

        if action == "ListTables":
            names = store.table_names()
            start = str(payload.get("ExclusiveStartTableName") or "")
            if start:
                names = [n for n in names if n > start]
            limit = payload.get("Limit")
            body: dict = {"TableNames": names}
            if limit:
                limit = int(limit)
                if limit < 1 or limit > 100:
                    raise _validation("1 validation error detected: Value '%s' at 'limit' failed to satisfy constraint: "
                                      "Member must have value less than or equal to 100" % limit)
                if len(names) > limit:
                    body = {"TableNames": names[:limit], "LastEvaluatedTableName": names[limit - 1]}
            return _ok(body)

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
            view = _table_view(store, table, include_items=False)
            view["TableStatus"] = "DELETING"
            _delete_table_record(store, name)
            return _ok({"TableDescription": view})

        if action == "UpdateTable":
            table = _require_table(store, table_name())
            _update_table_record(store, table, payload)
            view = _table_view(store, table, include_items=False)
            created = {str((u.get("Create") or {}).get("IndexName")) for u in payload.get("GlobalSecondaryIndexUpdates") or []
                       if isinstance(u, dict) and "Create" in u}
            for g in view.get("GlobalSecondaryIndexes", []):
                if g["IndexName"] in created:     # backfill is instantaneous here; DescribeTable then shows ACTIVE
                    g["IndexStatus"] = "CREATING"
                    g["Backfilling"] = False
                    if str(table.get("billing_mode")).upper() == "PAY_PER_REQUEST":
                        g["OnDemandThroughput"] = {"MaxReadRequestUnits": -1, "MaxWriteRequestUnits": -1}
            return _ok({"TableDescription": view})

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

        if action == "RestoreTableToPointInTime":
            restored = _restore_table_to_point_in_time(store, payload)
            return _ok({"TableDescription": _table_view(store, restored, include_items=False)})

        if action == "ExecuteStatement":
            return _execute_statement(store, payload)

        if action == "PutItem":
            return _ok(_op_put(store, payload))

        if action == "GetItem":
            return _ok(_op_get(store, payload))

        if action == "DeleteItem":
            return _ok(_op_delete(store, payload))

        if action == "UpdateItem":
            return _ok(_op_update(store, payload))

        if action == "Query":
            if payload.get("KeyConditionExpression") is None and any(
                    k in payload for k in ("partition_key_value", "sort_key_equals", "sort_key_begins_with",
                                           "sort_key_between")):
                table = _require_table(store, table_name())          # console-REST shaped payload
                _expire_table_items(table)
                matched, scanned = _query_filter(table, payload)
                return _ok({"Items": [_rec_av(r) for r in matched], "Count": len(matched), "ScannedCount": scanned})
            return _ok(_read(store, payload, query=True))

        if action == "Scan":
            return _ok(_read(store, payload, query=False))

        if action == "BatchGetItem":
            return _ok(_op_batch_get(store, payload))

        if action == "BatchWriteItem":
            return _ok(_op_batch_write(store, payload))

        if action == "TransactWriteItems":
            return _ok(_op_transact_write(store, payload))

        if action == "TransactGetItems":
            return _ok(_op_transact_get(store, payload))

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
        return _error(e.code, e.message, e.status, e.extra)
