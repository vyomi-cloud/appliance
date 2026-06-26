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
DeleteTable, PutItem, GetItem, DeleteItem, UpdateItem (AttributeUpdates + SET
UpdateExpression), Query (KeyConditionExpression: =, begins_with, BETWEEN),
Scan, BatchGetItem, BatchWriteItem, TagResource/UntagResource/ListTagsOfResource.
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
    table.setdefault("tags", {})
    table.setdefault("indexes", [])
    table.setdefault("streams", {"enabled": False, "latest_stream_label": ""})
    table.setdefault("items", {})
    table.setdefault("created", _now())
    table.setdefault("last_modified", _now())
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
    }
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
    tags = payload.get("Tags") or payload.get("tags") or {}
    if isinstance(tags, list):
        tags = {str(t.get("Key", t.get("key", ""))): str(t.get("Value", t.get("value", "")))
                for t in tags if isinstance(t, dict)}

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
        "tags": copy.deepcopy(tags or {}),
        "indexes": [],
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


def _query_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _sorted_records(table)
    if not records:
        return [], 0
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


# ── response builders ───────────────────────────────────────────────────────
def _ok(body: dict | None = None) -> DdbResponse:
    return DdbResponse(status=200, body=body or {}, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400) -> DdbResponse:
    return DdbResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id()})


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
        return str(payload.get("TableName") or payload.get("table_name") or "").strip()

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
            _delete_table_record(store, name)
            return _ok({"TableDescription": {"TableName": name, "TableStatus": "DELETING"}})

        if action == "PutItem":
            table = _require_table(store, table_name())
            old = _put_item_record(store, table, payload)
            return_old = str(payload.get("ReturnValues", "NONE")).upper() in {"ALL_OLD", "UPDATED_OLD"}
            attrs = native_item_to_json(copy.deepcopy(old.get("item", {}))) if old and return_old else {}
            return _ok({"Attributes": attrs} if attrs else {})

        if action == "GetItem":
            table = _require_table(store, table_name())
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
            matched, scanned = _query_filter(table, payload)
            return _ok({"Items": [native_item_to_json(r.get("item", {})) for r in matched],
                        "Count": len(matched), "ScannedCount": scanned})

        if action == "Scan":
            table = _require_table(store, table_name())
            matched, scanned = _scan_filter(table, payload)
            return _ok({"Items": [native_item_to_json(r.get("item", {})) for r in matched],
                        "Count": len(matched), "ScannedCount": scanned})

        if action == "BatchGetItem":
            responses: dict[str, list] = {}
            for tname, req in (payload.get("RequestItems") or {}).items():
                table = _find_table(store, str(tname))
                if not table:
                    continue
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
