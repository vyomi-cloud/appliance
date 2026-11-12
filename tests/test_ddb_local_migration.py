"""v4 C0 upgrade path — tables a pre-v4 appliance kept in DynamoDB Local are copied ONCE
into the shared DynamoDB core on appliance start (core/ddb_local_migration.py).

Boots the real server.py in-process (FastAPI TestClient, like tests/test_c0_unified_engine.py)
against a throwaway state file, with CLOUDLEARN_DYNAMODB_URL pointing at a real
amazon/dynamodb-local populated beforehand. Skipped when no DynamoDB Local is reachable:

  docker run -d --name vyomi-parity-ddblocal -p 127.0.0.1:8123:8000 \\
      amazon/dynamodb-local:latest -jar DynamoDBLocal.jar -inMemory -sharedDb
  DDB_LOCAL_URL=http://127.0.0.1:8123 .venv/bin/python -m pytest tests/test_ddb_local_migration.py
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

DDB_LOCAL_URL = os.environ.get("DDB_LOCAL_URL", "http://127.0.0.1:8123")

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-ddbmig-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_BACKEND_WARMUP", "off")
os.environ["CLOUDLEARN_DYNAMODB_URL"] = DDB_LOCAL_URL
os.environ["VYOMI_DDB_MIGRATE_WAIT_S"] = "0"
os.environ.pop("VYOMI_DDB_MIGRATE_FROM_LOCAL", None)

from core import ddb_local_migration as mig  # noqa: E402

_SRC = mig._Local(DDB_LOCAL_URL)
pytestmark = pytest.mark.skipif(not _SRC.reachable(), reason=f"no DynamoDB Local at {DDB_LOCAL_URL}")

SIG = ("AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/dynamodb/aws4_request, "
       "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64)
DDBH = {"Authorization": SIG, "Content-Type": "application/x-amz-json-1.0"}

SUFFIX = uuid.uuid4().hex[:6]
ORDERS = f"mig-orders-{SUFFIX}"
EVENTS = f"mig-events-{SUFFIX}"
BIG = f"mig-big-{SUFFIX}"
BLOB = "x" * 40_000                          # 40 KB items → > 1 MB table → several Scan pages


def _local(op: str, payload: dict) -> dict:
    status, body = _SRC.call(op, payload)
    assert status == 200, (op, body)
    return body


def _populate_ddb_local() -> None:
    for name in [n for n in _SRC.table_names()]:       # this container is the test's own oracle
        _SRC.call("DeleteTable", {"TableName": name})
    _local("CreateTable", {
        "TableName": ORDERS, "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "customer", "KeyType": "HASH"}, {"AttributeName": "order_id", "KeyType": "RANGE"}],
        "AttributeDefinitions": [{"AttributeName": "customer", "AttributeType": "S"},
                                 {"AttributeName": "order_id", "AttributeType": "N"},
                                 {"AttributeName": "status", "AttributeType": "S"},
                                 {"AttributeName": "placed", "AttributeType": "S"}],
        "GlobalSecondaryIndexes": [{"IndexName": "by-status", "KeySchema": [
            {"AttributeName": "status", "KeyType": "HASH"}, {"AttributeName": "order_id", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "KEYS_ONLY"}}],
        "LocalSecondaryIndexes": [{"IndexName": "by-placed", "KeySchema": [
            {"AttributeName": "customer", "KeyType": "HASH"}, {"AttributeName": "placed", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["total"]}}]})
    for i in range(1, 6):
        _local("PutItem", {"TableName": ORDERS, "Item": {
            "customer": {"S": "alice" if i % 2 else "bob"}, "order_id": {"N": str(i)},
            "status": {"S": "SHIPPED" if i < 4 else "PENDING"}, "placed": {"S": f"2026-10-0{i}"},
            "total": {"N": "12345678901234567890123456789012345678" if i == 1 else f"{i}.10"},
            "tags": {"SS": ["gift", "express"]}, "lines": {"L": [{"S": "a"}, {"S": "a"}]},
            "sizes": {"NS": ["1", "2.5"]}, "raw": {"B": "AAEC"},
            "meta": {"M": {"ok": {"BOOL": True}, "none": {"NULL": True}}}}})
    _local("CreateTable", {
        "TableName": EVENTS, "BillingMode": "PROVISIONED",
        "ProvisionedThroughput": {"ReadCapacityUnits": 7, "WriteCapacityUnits": 3},
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    _local("UpdateTimeToLive", {"TableName": EVENTS, "TimeToLiveSpecification": {"AttributeName": "expires", "Enabled": True}})
    _local("PutItem", {"TableName": EVENTS, "Item": {"id": {"S": "e1"}, "expires": {"N": "4102444800"}}})
    _local("CreateTable", {
        "TableName": BIG, "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "k", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "k", "AttributeType": "S"}]})
    for i in range(40):
        _local("PutItem", {"TableName": BIG, "Item": {"k": {"S": f"k{i:03d}"}, "blob": {"S": BLOB}}})
    first = _local("Scan", {"TableName": BIG})
    assert "LastEvaluatedKey" in first, "fixture must span several Scan pages"


_populate_ddb_local()

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core import app_context as ctx  # noqa: E402
from core import appliance_stores  # noqa: E402


def _ddb(client, op, body):
    r = client.post("/", content=json.dumps(body), headers={**DDBH, "X-Amz-Target": f"DynamoDB_20120810.{op}"})
    return r.status_code, r.json()


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:      # startup hooks run here → the migration
        yield c


def test_migration_ran_once_at_boot_and_recorded_marker(client):
    marker = ctx.STATE.get("migrations", {}).get(mig.MARKER_KEY)
    assert marker, "no migration marker recorded"
    print("\n[migration marker]", json.dumps(marker, indent=1))
    assert marker["status"] == "migrated" and marker["tables"] == 3 and marker["items"] == 5 + 1 + 40
    assert marker["errors"] == []


def test_tables_schema_indexes_and_settings(client):
    st, names = _ddb(client, "ListTables", {})
    assert st == 200 and {ORDERS, EVENTS, BIG} <= set(names["TableNames"])
    st, d = _ddb(client, "DescribeTable", {"TableName": ORDERS})
    t = d["Table"]
    assert t["KeySchema"] == [{"AttributeName": "customer", "KeyType": "HASH"},
                              {"AttributeName": "order_id", "KeyType": "RANGE"}]
    assert {a["AttributeName"]: a["AttributeType"] for a in t["AttributeDefinitions"]} == \
        {"customer": "S", "order_id": "N", "status": "S", "placed": "S"}
    assert t["BillingModeSummary"]["BillingMode"] == "PAY_PER_REQUEST"
    assert [g["IndexName"] for g in t["GlobalSecondaryIndexes"]] == ["by-status"]
    assert t["GlobalSecondaryIndexes"][0]["Projection"] == {"ProjectionType": "KEYS_ONLY"}
    assert t["LocalSecondaryIndexes"][0]["Projection"] == {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["total"]}
    st, d = _ddb(client, "DescribeTable", {"TableName": EVENTS})
    assert "BillingModeSummary" not in d["Table"]
    assert d["Table"]["ProvisionedThroughput"]["ReadCapacityUnits"] == 7
    assert d["Table"]["ProvisionedThroughput"]["WriteCapacityUnits"] == 3
    st, ttl = _ddb(client, "DescribeTimeToLive", {"TableName": EVENTS})
    assert ttl["TimeToLiveDescription"] == {"TimeToLiveStatus": "ENABLED", "AttributeName": "expires"}


def test_items_are_identical_typed_values(client):
    key = {"customer": {"S": "alice"}, "order_id": {"N": "1"}}
    st, got = _ddb(client, "GetItem", {"TableName": ORDERS, "Key": key})
    _, want = _SRC.call("GetItem", {"TableName": ORDERS, "Key": key})

    def norm(item):
        return {k: ({t: sorted(v)} if t in ("SS", "NS", "BS") else {t: v})
                for k, av in item.items() for t, v in av.items()}
    assert norm(got["Item"]) == norm(want["Item"])
    assert got["Item"]["total"] == {"N": "12345678901234567890123456789012345678"}   # 38 digits intact
    assert got["Item"]["lines"] == {"L": [{"S": "a"}, {"S": "a"}]}                     # a List, not a set
    assert got["Item"]["raw"] == {"B": "AAEC"}
    st, q = _ddb(client, "Query", {"TableName": ORDERS, "IndexName": "by-status",
                                   "KeyConditionExpression": "#s = :s", "ExpressionAttributeNames": {"#s": "status"},
                                   "ExpressionAttributeValues": {":s": {"S": "SHIPPED"}}})
    assert q["Count"] == 3 and all(set(i) == {"customer", "order_id", "status"} for i in q["Items"])


def test_multi_page_table_fully_copied(client):
    items, esk = [], None
    while True:
        st, page = _ddb(client, "Scan", {"TableName": BIG, "Limit": 15, **({"ExclusiveStartKey": esk} if esk else {})})
        items += page["Items"]
        esk = page.get("LastEvaluatedKey")
        if not esk:
            break
    assert sorted(i["k"]["S"] for i in items) == [f"k{i:03d}" for i in range(40)]
    assert all(i["blob"]["S"] == BLOB for i in items)


def test_classic_console_sees_migrated_tables(client):
    names = [t["table_name"] for t in client.get("/api/dynamodb/tables").json().get("tables", [])]
    assert ORDERS in names and BIG in names


def test_never_repeats(client):
    _local("CreateTable", {"TableName": f"mig-late-{SUFFIX}", "BillingMode": "PAY_PER_REQUEST",
                           "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                           "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    again = mig.maybe_migrate(log=lambda m: None)
    assert again["status"] == "skipped" and again["reason"] == "already migrated"
    st, names = _ddb(client, "ListTables", {})
    assert f"mig-late-{SUFFIX}" not in names["TableNames"]


def test_guard_rails(client, monkeypatch):
    marker = ctx.STATE["migrations"].pop(mig.MARKER_KEY)
    try:
        # opt-out
        monkeypatch.setenv("VYOMI_DDB_MIGRATE_FROM_LOCAL", "0")
        assert mig.maybe_migrate(log=lambda m: None)["status"] == "skipped"
        # the core already has tables → never merges/overwrites
        monkeypatch.delenv("VYOMI_DDB_MIGRATE_FROM_LOCAL")
        r = mig.maybe_migrate(log=lambda m: None)
        assert r["status"] == "skipped" and "already has" in r["reason"]
        # source unreachable → nothing recorded, retried next start
        monkeypatch.setenv("CLOUDLEARN_DYNAMODB_URL", "http://127.0.0.1:1")
        store = appliance_stores.ddb_store()
        empty = type(store)({}, account_id=store.account_id)
        assert mig.maybe_migrate(empty, log=lambda m: None)["status"] == "unreachable"
        assert mig.MARKER_KEY not in ctx.STATE["migrations"]
    finally:
        ctx.STATE["migrations"][mig.MARKER_KEY] = marker


def test_merge_mode_adds_only_missing_tables(client, monkeypatch):
    marker = ctx.STATE["migrations"].pop(mig.MARKER_KEY)
    try:
        monkeypatch.setenv("VYOMI_DDB_MIGRATE_FROM_LOCAL", "merge")
        _ddb(client, "PutItem", {"TableName": ORDERS, "Item": {"customer": {"S": "carol"}, "order_id": {"N": "9"}}})
        r = mig.maybe_migrate(log=lambda m: None, persist=lambda: None)
        assert r["status"] == "migrated" and r["tables"] == 1 and set(r["skipped_existing"]) == {ORDERS, EVENTS, BIG}
        st, got = _ddb(client, "GetItem", {"TableName": ORDERS, "Key": {"customer": {"S": "carol"}, "order_id": {"N": "9"}}})
        assert "Item" in got                     # post-upgrade data untouched
    finally:
        ctx.STATE["migrations"][mig.MARKER_KEY] = marker
