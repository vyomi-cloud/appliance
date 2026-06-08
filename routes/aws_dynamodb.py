"""AWS DynamoDB table CRUD, item operations, query/scan, tagging.

Extracted from server.py — contains all DynamoDB helper functions and
route handlers for /api/dynamodb/* endpoints plus the /dynamodb JSON-RPC
endpoint used by real AWS SDK/CLI clients.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from core import app_context as ctx
from core.models import (
    DynamoDBItemRequest,
    DynamoDBQueryRequest,
    DynamoDBScanRequest,
    DynamoDBTableRequest,
    DynamoDBTagRequest,
)

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# Aliases for shared utilities
# ---------------------------------------------------------------------------

_now = ctx.now
_id = ctx.id_gen
_record_usage = ctx.record_usage

# ---------------------------------------------------------------------------
# State access
# ---------------------------------------------------------------------------

ddb_state = ctx.ddb_state


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _ddb_state() -> dict:
    return ddb_state


def _ddb_tables() -> dict:
    return _ddb_state().setdefault("tables", {})


def _ddb_table_arn(table_name: str) -> str:
    return f"arn:aws:dynamodb:us-east-1:{ctx.AWS_ACCOUNT_ID}:table/{table_name}"


def _ddb_is_typed_value(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and next(iter(value.keys())) in {"S", "N", "BOOL", "NULL", "M", "L", "SS", "NS", "BS", "B"}


def _ddb_json_to_native(value: Any) -> Any:
    if isinstance(value, dict):
        if _ddb_is_typed_value(value):
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
                return [_ddb_json_to_native(item) for item in (raw or [])]
            if type_key == "M":
                return {k: _ddb_json_to_native(v) for k, v in (raw or {}).items()}
        return {k: _ddb_json_to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ddb_json_to_native(v) for v in value]
    return copy.deepcopy(value)


def _ddb_native_to_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {"M": {k: _ddb_native_to_json(v) for k, v in value.items()}}
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return {"SS": [str(item) for item in value]}
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return {"NS": [str(item) for item in value]}
        return {"L": [_ddb_native_to_json(item) for item in value]}
    if isinstance(value, bool):
        return {"BOOL": value}
    if value is None:
        return {"NULL": True}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"N": str(value)}
    return {"S": str(value)}


def _ddb_native_item_to_json(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _ddb_native_to_json(v) for k, v in (item or {}).items()}


def _ddb_item_to_native_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise HTTPException(400, detail="ValidationException: Item must be an object.")
    return {k: _ddb_json_to_native(v) for k, v in item.items()}


def _ddb_table_key_fields(table: dict) -> tuple[str, str]:
    return str(table.get("partition_key_name", "id")), str(table.get("sort_key_name", "") or "")


def _ddb_item_key_tuple(table: dict, item: dict[str, Any]) -> tuple[Any, Any | None]:
    pk_name, sk_name = _ddb_table_key_fields(table)
    if pk_name not in item:
        raise HTTPException(400, detail=f"ValidationException: Missing partition key '{pk_name}'.")
    pk = item.get(pk_name)
    sk = item.get(sk_name) if sk_name else None
    if sk_name and sk is None:
        raise HTTPException(400, detail=f"ValidationException: Missing sort key '{sk_name}'.")
    return pk, sk


def _ddb_item_key_string(table: dict, item: dict[str, Any]) -> str:
    return json.dumps(_ddb_item_key_tuple(table, item), default=str, separators=(",", ":"))


def _fmt_size(n: int) -> str:
    orig = n
    for unit in ["B", "KB", "MB", "GB"]:
        if orig < 1024:
            return f"{orig:.1f} {unit}"
        orig /= 1024
    return f"{orig:.1f} TB"


def _req_id() -> str:
    import uuid
    return uuid.uuid4().hex.upper()[:16]


def _persist_state() -> None:
    _srv()._persist_state()


def _ddb_normalize_table(table_name: str, table: dict) -> dict:
    table.setdefault("table_name", table_name)
    table.setdefault("table_arn", _ddb_table_arn(table_name))
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


def _ddb_find_table(table_name: str) -> dict | None:
    table = _ddb_tables().get(table_name)
    if isinstance(table, dict):
        return _ddb_normalize_table(table_name, table)
    return None


def _ddb_refresh_table_metrics(table: dict) -> None:
    records = list((table.get("items") or {}).values())
    table["item_count"] = len(records)
    try:
        table["table_size_bytes"] = sum(len(json.dumps(rec.get("item", {}), sort_keys=True, default=str).encode("utf-8")) for rec in records)
    except Exception:
        table["table_size_bytes"] = 0
    table["last_modified"] = _now()


def _ddb_item_record_view(table: dict, key: str, record: dict) -> dict:
    native = copy.deepcopy(record.get("item", {}))
    pk_name, sk_name = _ddb_table_key_fields(table)
    key_obj = {pk_name: native.get(pk_name)}
    if sk_name:
        key_obj[sk_name] = native.get(sk_name)
    return {
        "key": key_obj,
        "item": native,
        "item_json": _ddb_native_item_to_json(native),
        "created": record.get("created", ""),
        "updated": record.get("updated", ""),
        "size_bytes": int(record.get("size_bytes", 0) or 0),
        "size_human": _fmt_size(int(record.get("size_bytes", 0) or 0)),
    }


def _ddb_table_view(table: dict, include_items: bool = True, native_items: bool = True) -> dict:
    table = _ddb_normalize_table(table.get("table_name", ""), table)
    _ddb_refresh_table_metrics(table)
    records = sorted((table.get("items") or {}).items(), key=lambda kv: json.dumps(_ddb_item_key_tuple(table, kv[1].get("item", {})), default=str))
    view = {
        "table_name": table.get("table_name", ""),
        "table_arn": table.get("table_arn", ""),
        "table_status": table.get("table_status", "ACTIVE"),
        "partition_key_name": table.get("partition_key_name", "id"),
        "partition_key_type": table.get("partition_key_type", "S"),
        "sort_key_name": table.get("sort_key_name", ""),
        "sort_key_type": table.get("sort_key_type", "S"),
        "billing_mode": table.get("billing_mode", "PAY_PER_REQUEST"),
        "provisioned_throughput": copy.deepcopy(table.get("provisioned_throughput", {})),
        "tags": copy.deepcopy(table.get("tags", {})),
        "indexes": copy.deepcopy(table.get("indexes", [])),
        "streams": copy.deepcopy(table.get("streams", {"enabled": False, "latest_stream_label": ""})),
        "created": table.get("created", ""),
        "last_modified": table.get("last_modified", ""),
        "item_count": int(table.get("item_count", 0) or 0),
        "table_size_bytes": int(table.get("table_size_bytes", 0) or 0),
        "table_size_human": _fmt_size(int(table.get("table_size_bytes", 0) or 0)),
    }
    if include_items:
        items = [_ddb_item_record_view(table, key, record) for key, record in records]
        view["items"] = [item["item"] if native_items else item["item_json"] for item in items]
        view["item_rows"] = items
    return view


def _ddb_create_table_record(payload: dict[str, Any]) -> dict:
    table_name = str(payload.get("table_name") or payload.get("TableName") or "").strip()
    if not table_name:
        raise HTTPException(400, detail="ValidationException: TableName is required.")
    tables = _ddb_tables()
    if table_name in tables:
        raise HTTPException(409, detail="ResourceInUseException: Table already exists.")
    # Extract key schema from AWS SDK format (KeySchema + AttributeDefinitions)
    key_schema = payload.get("KeySchema") or payload.get("key_schema") or []
    attr_defs_input = payload.get("AttributeDefinitions") or payload.get("attribute_definitions") or []
    _attr_type_map = {ad.get("AttributeName", ""): ad.get("AttributeType", "S") for ad in attr_defs_input if isinstance(ad, dict)}
    pk_name = ""
    sk_name = ""
    for ks in key_schema:
        if isinstance(ks, dict):
            if ks.get("KeyType") == "HASH":
                pk_name = ks.get("AttributeName", "")
            elif ks.get("KeyType") == "RANGE":
                sk_name = ks.get("AttributeName", "")
    if not pk_name:
        pk_name = str(payload.get("partition_key_name") or payload.get("PartitionKeyName") or "id").strip() or "id"
    if not sk_name:
        sk_name = str(payload.get("sort_key_name") or payload.get("SortKeyName") or "").strip()
    pk_type = _attr_type_map.get(pk_name, str(payload.get("partition_key_type") or payload.get("PartitionKeyType") or "S").strip().upper() or "S")
    sk_type = _attr_type_map.get(sk_name, str(payload.get("sort_key_type") or payload.get("SortKeyType") or "S").strip().upper() or "S")
    billing_mode = str(payload.get("billing_mode") or payload.get("BillingMode") or "PAY_PER_REQUEST").strip().upper() or "PAY_PER_REQUEST"
    throughput = payload.get("provisioned_throughput") or payload.get("ProvisionedThroughput") or {}
    tags = payload.get("tags") or payload.get("Tags") or {}
    if isinstance(tags, list):
        tags = {str(tag.get("Key", tag.get("key", ""))): str(tag.get("Value", tag.get("value", ""))) for tag in tags if isinstance(tag, dict)}
    table = {
        "table_name": table_name,
        "table_arn": _ddb_table_arn(table_name),
        "table_status": "ACTIVE",
        "partition_key_name": pk_name,
        "partition_key_type": pk_type,
        "sort_key_name": sk_name,
        "sort_key_type": sk_type,
        "billing_mode": billing_mode,
        "provisioned_throughput": {
            "ReadCapacityUnits": int(throughput.get("ReadCapacityUnits", payload.get("read_capacity_units", 5)) or 5),
            "WriteCapacityUnits": int(throughput.get("WriteCapacityUnits", payload.get("write_capacity_units", 5)) or 5),
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

    # GSI / LSI support
    gsi_list = payload.get("GlobalSecondaryIndexes") or payload.get("global_secondary_indexes") or []
    lsi_list = payload.get("LocalSecondaryIndexes") or payload.get("local_secondary_indexes") or []
    indexes = []
    attr_defs = {ad["AttributeName"] for ad in table["attribute_definitions"]}
    for idx_def in gsi_list:
        idx = {
            "IndexName": idx_def.get("IndexName", idx_def.get("index_name", "")),
            "IndexType": "GSI",
            "KeySchema": idx_def.get("KeySchema", idx_def.get("key_schema", [])),
            "Projection": idx_def.get("Projection", idx_def.get("projection", {"ProjectionType": "ALL"})),
            "IndexStatus": "ACTIVE",
            "IndexArn": f"{_ddb_table_arn(table_name)}/index/{idx_def.get('IndexName', idx_def.get('index_name', ''))}",
        }
        if idx_def.get("ProvisionedThroughput"):
            idx["ProvisionedThroughput"] = idx_def["ProvisionedThroughput"]
        indexes.append(idx)
        for ks in idx.get("KeySchema", []):
            if ks.get("AttributeName") and ks["AttributeName"] not in attr_defs:
                attr_defs.add(ks["AttributeName"])
                table["attribute_definitions"].append({"AttributeName": ks["AttributeName"], "AttributeType": "S"})
    for idx_def in lsi_list:
        idx = {
            "IndexName": idx_def.get("IndexName", idx_def.get("index_name", "")),
            "IndexType": "LSI",
            "KeySchema": idx_def.get("KeySchema", idx_def.get("key_schema", [])),
            "Projection": idx_def.get("Projection", idx_def.get("projection", {"ProjectionType": "ALL"})),
            "IndexStatus": "ACTIVE",
            "IndexArn": f"{_ddb_table_arn(table_name)}/index/{idx_def.get('IndexName', idx_def.get('index_name', ''))}",
        }
        indexes.append(idx)
        for ks in idx.get("KeySchema", []):
            if ks.get("AttributeName") and ks["AttributeName"] not in attr_defs:
                attr_defs.add(ks["AttributeName"])
                table["attribute_definitions"].append({"AttributeName": ks["AttributeName"], "AttributeType": "S"})
    table["indexes"] = indexes

    # Also add attribute definitions from payload if provided
    extra_attrs = payload.get("AttributeDefinitions") or payload.get("attribute_definitions") or []
    for ad in extra_attrs:
        aname = ad.get("AttributeName", "")
        if aname and aname not in attr_defs:
            attr_defs.add(aname)
            table["attribute_definitions"].append({"AttributeName": aname, "AttributeType": ad.get("AttributeType", "S")})
        elif aname in attr_defs:
            # Update type if explicitly specified
            for existing_ad in table["attribute_definitions"]:
                if existing_ad["AttributeName"] == aname:
                    existing_ad["AttributeType"] = ad.get("AttributeType", existing_ad["AttributeType"])

    # Stream support
    stream_spec = payload.get("StreamSpecification") or payload.get("stream_specification") or {}
    if stream_spec:
        stream_enabled = stream_spec.get("StreamEnabled", stream_spec.get("stream_enabled", False))
        stream_view_type = stream_spec.get("StreamViewType", stream_spec.get("stream_view_type", "NEW_AND_OLD_IMAGES"))
        if stream_enabled:
            stream_label = _now().replace(":", "-").replace("+", "-")
            table["streams"] = {
                "enabled": True,
                "stream_view_type": stream_view_type,
                "stream_arn": f"{_ddb_table_arn(table_name)}/stream/{stream_label}",
                "latest_stream_label": stream_label,
            }
            table["stream_records"] = []

    tables[table_name] = table
    _persist_state()
    _record_usage("dynamodb.create_table", {"table_name": table_name})
    return table


def _ddb_delete_table_record(table_name: str) -> None:
    tables = _ddb_tables()
    if table_name not in tables:
        raise HTTPException(404, detail="ResourceNotFoundException: Table not found.")
    tables.pop(table_name, None)
    _persist_state()
    _record_usage("dynamodb.delete_table", {"table_name": table_name})


def _ddb_emit_stream_record(table: dict, event_name: str, old_image: dict | None, new_image: dict | None) -> None:
    """Append a stream record if streams are enabled on the table."""
    streams = table.get("streams", {})
    if not streams.get("enabled"):
        return
    import uuid
    view_type = streams.get("stream_view_type", "NEW_AND_OLD_IMAGES")
    record: dict[str, Any] = {
        "eventID": uuid.uuid4().hex[:32],
        "eventName": event_name,
        "eventVersion": "1.1",
        "eventSource": "aws:dynamodb",
        "awsRegion": "us-east-1",
        "approximateCreationDateTime": _now(),
    }
    dynamodb_record: dict[str, Any] = {
        "ApproximateCreationDateTime": _now(),
        "SequenceNumber": str(len(table.get("stream_records", [])) + 1).zfill(21),
        "SizeBytes": 0,
        "StreamViewType": view_type,
    }
    # Build Keys from the new or old image
    pk_name, sk_name = _ddb_table_key_fields(table)
    source = new_image or old_image or {}
    keys: dict[str, Any] = {}
    if pk_name in source:
        keys[pk_name] = _ddb_native_to_json(source[pk_name])
    if sk_name and sk_name in source:
        keys[sk_name] = _ddb_native_to_json(source[sk_name])
    dynamodb_record["Keys"] = keys
    if view_type in ("NEW_AND_OLD_IMAGES", "NEW_IMAGE") and new_image is not None:
        dynamodb_record["NewImage"] = _ddb_native_item_to_json(new_image)
    if view_type in ("NEW_AND_OLD_IMAGES", "OLD_IMAGE") and old_image is not None:
        dynamodb_record["OldImage"] = _ddb_native_item_to_json(old_image)
    record["dynamodb"] = dynamodb_record
    stream_records = table.setdefault("stream_records", [])
    stream_records.append(record)
    # Cap at 1000 records
    if len(stream_records) > 1000:
        table["stream_records"] = stream_records[-1000:]


def _ddb_put_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_item = _ddb_item_to_native_item(payload.get("item") or payload.get("Item") or {})
    key = _ddb_item_key_string(table, native_item)
    items = table.setdefault("items", {})
    existing = items.get(key)
    old_image = copy.deepcopy(existing.get("item", {})) if existing else None
    items[key] = {
        "item": native_item,
        "created": existing.get("created", _now()) if existing else _now(),
        "updated": _now(),
        "size_bytes": len(json.dumps(native_item, sort_keys=True, default=str).encode("utf-8")),
    }
    _ddb_emit_stream_record(table, "MODIFY" if existing else "INSERT", old_image, copy.deepcopy(native_item))
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.put_item", {"table_name": table["table_name"]})
    return existing or {}


def _ddb_get_item_record(table: dict, payload: dict[str, Any]) -> dict | None:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    return table.get("items", {}).get(key)


def _ddb_delete_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    removed = table.get("items", {}).pop(key, None)
    if removed:
        _ddb_emit_stream_record(table, "REMOVE", copy.deepcopy(removed.get("item", {})), None)
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.delete_item", {"table_name": table["table_name"]})
    return removed or {}


def _ddb_update_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    old_record = table.get("items", {}).get(key, {})
    old_image = copy.deepcopy(old_record.get("item", {})) if old_record else None
    current = copy.deepcopy(old_record.get("item", {})) if old_record else {}
    updates = payload.get("attribute_updates") or payload.get("AttributeUpdates") or {}
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
                current[name] = _ddb_json_to_native(value)
    else:
        expr = str(payload.get("update_expression") or payload.get("UpdateExpression") or "").strip()
        values = payload.get("expression_attribute_values") or payload.get("ExpressionAttributeValues") or {}
        if expr.upper().startswith("SET "):
            for clause in expr[4:].split(","):
                if "=" not in clause:
                    continue
                left, right = clause.split("=", 1)
                attr_name = left.strip()
                token = right.strip()
                current[attr_name] = _ddb_json_to_native(values.get(token, token))
    items = table.setdefault("items", {})
    items[key] = {
        "item": current,
        "created": items.get(key, {}).get("created", _now()),
        "updated": _now(),
        "size_bytes": len(json.dumps(current, sort_keys=True, default=str).encode("utf-8")),
    }
    _ddb_emit_stream_record(table, "MODIFY" if old_image else "INSERT", old_image, copy.deepcopy(current))
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.update_item", {"table_name": table["table_name"]})
    return items[key]


def _ddb_sort_key(table: dict, native_item: dict[str, Any]) -> tuple[str, str]:
    pk_name, sk_name = _ddb_table_key_fields(table)
    return (str(native_item.get(pk_name, "")), str(native_item.get(sk_name, "")) if sk_name else "")


def _ddb_sorted_records(table: dict) -> list[dict]:
    records = list((table.get("items") or {}).values())
    records.sort(key=lambda rec: _ddb_sort_key(table, rec.get("item", {})))
    return records


def _ddb_expr_value(raw: Any) -> Any:
    return _ddb_json_to_native(raw)


def _ddb_index_key_fields(table: dict, index_name: str) -> tuple[str, str] | None:
    """Return (pk_name, sk_name) for the given index, or None if not found."""
    for idx in table.get("indexes", []):
        if idx.get("IndexName") == index_name:
            ks = idx.get("KeySchema", [])
            pk = ""
            sk = ""
            for entry in ks:
                if entry.get("KeyType") == "HASH":
                    pk = entry.get("AttributeName", "")
                elif entry.get("KeyType") == "RANGE":
                    sk = entry.get("AttributeName", "")
            return (pk, sk) if pk else None
    return None


def _ddb_query_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _ddb_sorted_records(table)
    if not records:
        return [], 0
    index_name = payload.get("IndexName") or payload.get("index_name") or ""
    if index_name:
        idx_keys = _ddb_index_key_fields(table, index_name)
        if idx_keys:
            pk_name, sk_name = idx_keys
        else:
            pk_name, sk_name = _ddb_table_key_fields(table)
    else:
        pk_name, sk_name = _ddb_table_key_fields(table)
    pk_value = payload.get("partition_key_value")
    sk_equals = payload.get("sort_key_equals")
    sk_begins = str(payload.get("sort_key_begins_with") or "")
    sk_between = payload.get("sort_key_between") or []
    expr = str(payload.get("key_condition_expression") or payload.get("KeyConditionExpression") or "").strip()
    names = payload.get("expression_attribute_names") or payload.get("ExpressionAttributeNames") or {}
    values = payload.get("expression_attribute_values") or payload.get("ExpressionAttributeValues") or {}
    if expr:
        for alias, actual in (names or {}).items():
            expr = expr.replace(str(alias), str(actual))
        if pk_value is None:
            m = re.search(rf"\b{re.escape(pk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                pk_value = _ddb_expr_value(values.get(m.group(1)))
        if sk_name and not sk_equals and not sk_begins and not sk_between:
            m = re.search(rf"\b{re.escape(sk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                sk_equals = _ddb_expr_value(values.get(m.group(1)))
            m = re.search(rf"begins_with\s*\(\s*{re.escape(sk_name)}\s*,\s*(:\w+)\s*\)", expr, flags=re.I)
            if m:
                sk_begins = str(_ddb_expr_value(values.get(m.group(1))) or "")
            m = re.search(rf"\b{re.escape(sk_name)}\s+BETWEEN\s+(:\w+)\s+AND\s+(:\w+)", expr, flags=re.I)
            if m:
                sk_between = [_ddb_expr_value(values.get(m.group(1))), _ddb_expr_value(values.get(m.group(2)))]
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
    limit = max(1, min(int(payload.get("limit") or payload.get("Limit") or 100), 1000))
    return matched[:limit], len(matched)


def _ddb_scan_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _ddb_sorted_records(table)
    limit = max(1, min(int(payload.get("limit") or payload.get("Limit") or 100), 1000))
    return records[:limit], len(records)


def _ddb_table_response(table: dict, include_items: bool = True) -> dict:
    view = _ddb_table_view(table, include_items=include_items, native_items=True)
    if include_items:
        view["items"] = [copy.deepcopy(item["item"]) for item in view.get("item_rows", [])]
    return {"table": view}


def _ddb_list_tables_response() -> dict:
    tables = [_ddb_table_view(table, include_items=False) for _, table in sorted(_ddb_tables().items(), key=lambda kv: kv[0])]
    return {"table_names": [table["table_name"] for table in tables], "tables": tables, "count": len(tables)}


def _ddb_item_rows(table: dict, records: list[dict], native_items: bool = True) -> list[dict]:
    rows = [_ddb_item_record_view(table, key, record) for key, record in [(key, record) for key, record in ((k, r) for k, r in ((k, v) for k, v in (table.get("items") or {}).items()))]]
    return rows


def _ddb_tag_map(table: dict) -> dict[str, str]:
    tags = table.setdefault("tags", {})
    if isinstance(tags, list):
        tags = {str(tag.get("Key", "")): str(tag.get("Value", "")) for tag in tags if isinstance(tag, dict)}
        table["tags"] = tags
    return tags


def _ddb_tags_view(table: dict) -> dict[str, str]:
    return copy.deepcopy(_ddb_tag_map(table))


def _ddb_set_tags(table: dict, tags: dict[str, str]) -> None:
    table["tags"] = {str(k): str(v) for k, v in (tags or {}).items()}
    table["last_modified"] = _now()
    _persist_state()


def _ddb_json_response(payload: dict[str, Any], status: int = 200) -> Response:
    return JSONResponse(status_code=status, content=payload, headers={"x-amzn-requestid": _req_id()})


def _ddb_error_response(code: str, message: str, status: int = 400) -> Response:
    return _ddb_json_response({"__type": code, "message": message}, status=status)


# ---------------------------------------------------------------------------
# Route handlers — DynamoDB JSON-RPC (real SDK/CLI)
# ---------------------------------------------------------------------------


async def api_dynamodb_aws(request: Request):
    """POST /api/dynamodb/aws and POST /dynamodb — DynamoDB JSON-RPC endpoint.

    Proxies to amazon/dynamodb-local for real DDB semantics (PartiQL,
    secondary indexes, Streams, etc.). Falls back to the legacy in-memory
    handler if DDB Local is unreachable.
    """
    try:
        from core import dynamodb_proxy as _ddbp
        status, body, ctype = await _ddbp.proxy(request)
        if status != 502:
            return Response(content=body, status_code=status, media_type=ctype)
    except Exception:
        pass
    # Fall back to the provider-level handler.
    import providers.aws_services as _aws_svc
    return await _aws_svc._ddb_api_aws(request)


# ---------------------------------------------------------------------------
# Console REST API route handlers
# ---------------------------------------------------------------------------


def api_dynamodb_list_tables():
    return _ddb_list_tables_response()


def api_dynamodb_create_table(req: DynamoDBTableRequest):
    # Proxy to DynamoDB Local (best-effort) AND keep in-memory state in sync.
    try:
        from core import dynamodb_proxy as _ddbp
        if _ddbp.available():
            import urllib.request, urllib.error
            key_schema = [{"AttributeName": req.partition_key_name or "id", "KeyType": "HASH"}]
            attr_defs = [{"AttributeName": req.partition_key_name or "id", "AttributeType": req.partition_key_type or "S"}]
            if req.sort_key_name:
                key_schema.append({"AttributeName": req.sort_key_name, "KeyType": "RANGE"})
                attr_defs.append({"AttributeName": req.sort_key_name, "AttributeType": req.sort_key_type or "S"})
            proxy_body = json.dumps({"TableName": req.table_name, "KeySchema": key_schema,
                                     "AttributeDefinitions": attr_defs,
                                     "BillingMode": req.billing_mode or "PAY_PER_REQUEST"}).encode()
            proxy_req = urllib.request.Request(
                _ddbp._DDB_URL, data=proxy_body, method="POST",
                headers={"X-Amz-Target": "DynamoDB_20120810.CreateTable",
                         "Content-Type": "application/x-amz-json-1.0",
                         "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            urllib.request.urlopen(proxy_req, timeout=5)
    except Exception:
        pass
    table = _ddb_create_table_record({
        "table_name": req.table_name,
        "partition_key_name": req.partition_key_name,
        "partition_key_type": req.partition_key_type,
        "sort_key_name": req.sort_key_name,
        "sort_key_type": req.sort_key_type,
        "billing_mode": req.billing_mode,
        "read_capacity_units": req.read_capacity_units,
        "write_capacity_units": req.write_capacity_units,
        "tags": req.tags or {},
    })
    _record_usage("dynamodb.create_table", {"table_name": req.table_name})
    return _ddb_table_response(table, include_items=False)


def api_dynamodb_get_table(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    return _ddb_table_response(table, include_items=True)


def api_dynamodb_delete_table(table_name: str):
    # Proxy to DynamoDB Local (best-effort) AND delete from in-memory.
    try:
        from core import dynamodb_proxy as _ddbp
        if _ddbp.available():
            import urllib.request, urllib.error
            proxy_body = json.dumps({"TableName": table_name}).encode()
            proxy_req = urllib.request.Request(
                _ddbp._DDB_URL, data=proxy_body, method="POST",
                headers={"X-Amz-Target": "DynamoDB_20120810.DeleteTable",
                         "Content-Type": "application/x-amz-json-1.0",
                         "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            urllib.request.urlopen(proxy_req, timeout=5)
    except Exception:
        pass
    _ddb_delete_table_record(table_name)
    _record_usage("dynamodb.delete_table", {"table_name": table_name})
    return {"deleted": True, "table_name": table_name}


def api_dynamodb_list_items(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    rows = _ddb_table_view(table, include_items=True)["item_rows"]
    return {"table_name": table_name, "items": rows, "count": len(rows)}


def api_dynamodb_put_item(table_name: str, req: DynamoDBItemRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    # Proxy to DynamoDB Local (best-effort write-through).
    try:
        from core import dynamodb_proxy as _ddbp
        if _ddbp.available():
            import urllib.request, urllib.error
            item_json = _ddb_native_item_to_json(_ddb_item_to_native_item(req.item))
            proxy_body = json.dumps({"TableName": table_name, "Item": item_json}).encode()
            proxy_req = urllib.request.Request(
                _ddbp._DDB_URL, data=proxy_body, method="POST",
                headers={"X-Amz-Target": "DynamoDB_20120810.PutItem",
                         "Content-Type": "application/x-amz-json-1.0",
                         "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            urllib.request.urlopen(proxy_req, timeout=5)
    except Exception:
        pass
    old = _ddb_put_item_record(table, {"item": req.item})
    native_item = _ddb_item_to_native_item(req.item)
    key = _ddb_item_key_string(table, native_item)
    record = table.get("items", {}).get(key, {})
    _record_usage("dynamodb.put_item", {"table_name": table_name})
    return {"table_name": table_name, "item": _ddb_item_record_view(table, key, record), "previous": old.get("item", {}) if old else {}}


def api_dynamodb_update_item(table_name: str, req: DynamoDBItemRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    updated = _ddb_update_item_record(table, {
        "key": req.key,
        "attribute_updates": req.attribute_updates or {},
        "update_expression": req.update_expression,
        "expression_attribute_values": req.expression_attribute_values or {},
    })
    _record_usage("dynamodb.update_item", {"table_name": table_name})
    return {"table_name": table_name, "item": updated.get("item", {})}


def api_dynamodb_delete_item(table_name: str, req: DynamoDBItemRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    # Proxy to DynamoDB Local (best-effort).
    try:
        from core import dynamodb_proxy as _ddbp
        if _ddbp.available():
            import urllib.request, urllib.error
            key_json = _ddb_native_item_to_json(_ddb_item_to_native_item(req.key or {}))
            proxy_body = json.dumps({"TableName": table_name, "Key": key_json}).encode()
            proxy_req = urllib.request.Request(
                _ddbp._DDB_URL, data=proxy_body, method="POST",
                headers={"X-Amz-Target": "DynamoDB_20120810.DeleteItem",
                         "Content-Type": "application/x-amz-json-1.0",
                         "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            urllib.request.urlopen(proxy_req, timeout=5)
    except Exception:
        pass
    removed = _ddb_delete_item_record(table, {"key": req.key})
    _record_usage("dynamodb.delete_item", {"table_name": table_name})
    return {"table_name": table_name, "deleted": True, "item": removed.get("item", {})}


def api_dynamodb_query_items(table_name: str, req: DynamoDBQueryRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    # Try DynamoDB Local proxy first when a KeyConditionExpression is provided.
    try:
        from core import dynamodb_proxy as _ddbp
        if _ddbp.available() and req.key_condition_expression:
            import urllib.request, urllib.error
            proxy_payload: dict[str, Any] = {"TableName": table_name,
                                             "KeyConditionExpression": req.key_condition_expression}
            if req.expression_attribute_values:
                proxy_payload["ExpressionAttributeValues"] = {
                    k: _ddb_native_to_json(_ddb_json_to_native(v)) if isinstance(v, dict) else _ddb_native_to_json(v)
                    for k, v in req.expression_attribute_values.items()}
            if req.expression_attribute_names:
                proxy_payload["ExpressionAttributeNames"] = req.expression_attribute_names
            if req.limit:
                proxy_payload["Limit"] = req.limit
            proxy_body = json.dumps(proxy_payload).encode()
            proxy_req = urllib.request.Request(
                _ddbp._DDB_URL, data=proxy_body, method="POST",
                headers={"X-Amz-Target": "DynamoDB_20120810.Query",
                         "Content-Type": "application/x-amz-json-1.0",
                         "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            with urllib.request.urlopen(proxy_req, timeout=10) as r:
                if r.status == 200:
                    result = json.loads(r.read())
                    items_raw = result.get("Items", [])
                    native_items = [_ddb_json_to_native({"M": item}) for item in items_raw]
                    rows = [{"item": ni, "key": "", "created": "", "updated": "", "size_bytes": 0, "size_human": "0 B"} for ni in native_items]
                    return {"table_name": table_name,
                            "items": [_ddb_item_record_view(table, "", {"item": ni}) for ni in native_items],
                            "count": len(items_raw), "scanned_count": result.get("ScannedCount", len(items_raw)),
                            "_proxy": "dynamodb-local"}
    except Exception:
        pass
    payload = {
        "partition_key_value": req.partition_key_value,
        "sort_key_equals": req.sort_key_equals,
        "sort_key_begins_with": req.sort_key_begins_with,
        "sort_key_between": req.sort_key_between or [],
        "limit": req.limit,
        "key_condition_expression": req.key_condition_expression,
        "expression_attribute_values": req.expression_attribute_values or {},
        "expression_attribute_names": req.expression_attribute_names or {},
    }
    rows, count = _ddb_query_filter(table, payload)
    return {"table_name": table_name, "items": [_ddb_item_record_view(table, row.get("key", ""), row) for row in rows], "count": len(rows), "scanned_count": count}


def api_dynamodb_scan_items(table_name: str, req: DynamoDBScanRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    # Try DynamoDB Local proxy first.
    try:
        from core import dynamodb_proxy as _ddbp
        if _ddbp.available():
            import urllib.request, urllib.error
            proxy_payload: dict[str, Any] = {"TableName": table_name}
            if req.limit:
                proxy_payload["Limit"] = req.limit
            proxy_body = json.dumps(proxy_payload).encode()
            proxy_req = urllib.request.Request(
                _ddbp._DDB_URL, data=proxy_body, method="POST",
                headers={"X-Amz-Target": "DynamoDB_20120810.Scan",
                         "Content-Type": "application/x-amz-json-1.0",
                         "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            with urllib.request.urlopen(proxy_req, timeout=10) as r:
                if r.status == 200:
                    result = json.loads(r.read())
                    items_raw = result.get("Items", [])
                    native_items = [_ddb_json_to_native({"M": item}) for item in items_raw]
                    return {"table_name": table_name,
                            "items": [_ddb_item_record_view(table, "", {"item": ni}) for ni in native_items],
                            "count": len(items_raw), "scanned_count": result.get("ScannedCount", len(items_raw)),
                            "_proxy": "dynamodb-local"}
    except Exception:
        pass
    rows, count = _ddb_scan_filter(table, {"limit": req.limit})
    return {"table_name": table_name, "items": [_ddb_item_record_view(table, row.get("key", ""), row) for row in rows], "count": len(rows), "scanned_count": count}


def api_dynamodb_list_tags(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def api_dynamodb_tag_table(table_name: str, req: DynamoDBTagRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    tags = _ddb_tags_view(table)
    tags.update({str(k): str(v) for k, v in (req.tags or {}).items()})
    _ddb_set_tags(table, tags)
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def api_dynamodb_untag_table(table_name: str, payload: dict[str, Any]):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    tags = _ddb_tags_view(table)
    for key in payload.get("keys", []) if isinstance(payload, dict) else []:
        tags.pop(str(key), None)
    _ddb_set_tags(table, tags)
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(app: FastAPI, **kwargs) -> None:
    """Register DynamoDB routes on the FastAPI app.

    The two wire-protocol routes (POST /api/dynamodb/aws and POST /dynamodb)
    are registered here. Console CRUD routes are registered via
    providers/aws_routes.py using the dynamic _proxy/_add_route mechanism.
    """

    @app.api_route("/api/dynamodb/aws", methods=["POST"], include_in_schema=False)
    @app.api_route("/dynamodb", methods=["POST"], include_in_schema=False)
    async def _api_dynamodb_aws(request: Request):
        return await api_dynamodb_aws(request)
