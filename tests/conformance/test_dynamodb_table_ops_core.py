"""DynamoDB table-ops conformance (v4 console pilot) — host + Pyodide.

Asserts the ops the v4 console's Dashboard/Backups/PartiQL/Settings pages need
for real: UpdateTable (billing mode, throughput, deletion protection, table
class, GSI create/delete), DeleteTable honouring DeletionProtectionEnabled,
TTL (UpdateTimeToLive/DescribeTimeToLive + lazy expiry on read), continuous
backups (PITR), on-demand backups (Create/List/Describe/Delete/Restore), and
PartiQL ExecuteStatement (SELECT/INSERT/UPDATE/DELETE).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_table_ops_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json
import time

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as d
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as d  # type: ignore

P = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemoryNoSqlStore()

    def call(a, p):
        r = d.dispatch(s, P + a, p)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    # ── UpdateTable + DeleteTable deletion protection ──
    call("CreateTable", {
        "TableName": "orders",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        # (only key attributes may be defined — DynamoDB rejects an unused "customer" definition)
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    })
    status, body = call("UpdateTable", {"TableName": "orders", "BillingMode": "PROVISIONED",
                                        "ProvisionedThroughput": {"ReadCapacityUnits": 10, "WriteCapacityUnits": 7},
                                        "DeletionProtectionEnabled": True, "TableClass": "STANDARD_INFREQUENT_ACCESS"})
    _check("UpdateTable 200", status == 200)
    td = body["TableDescription"]
    _check("UpdateTable billing mode", td["BillingModeSummary"]["BillingMode"] == "PROVISIONED")
    _check("UpdateTable throughput", td["ProvisionedThroughput"]["ReadCapacityUnits"] == 10
           and td["ProvisionedThroughput"]["WriteCapacityUnits"] == 7)
    _check("UpdateTable deletion protection", td["DeletionProtectionEnabled"] is True)
    _check("UpdateTable table class", td["TableClassSummary"]["TableClass"] == "STANDARD_INFREQUENT_ACCESS")

    status, body = call("UpdateTable", {"TableName": "orders", "GlobalSecondaryIndexUpdates": [
        {"Create": {"IndexName": "by-customer", "KeySchema": [{"AttributeName": "customer", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"}}}]})
    gsis = body["TableDescription"].get("GlobalSecondaryIndexes", [])
    _check("UpdateTable GSI create", any(g["IndexName"] == "by-customer" for g in gsis))

    status, body = call("DeleteTable", {"TableName": "orders"})
    _check("DeleteTable blocked by deletion protection", status == 400 and body["__type"] == "ValidationException")

    call("UpdateTable", {"TableName": "orders", "GlobalSecondaryIndexUpdates": [
        {"Delete": {"IndexName": "by-customer"}}]})
    _, body = call("DescribeTable", {"TableName": "orders"})
    _check("UpdateTable GSI delete", not body["Table"].get("GlobalSecondaryIndexes"))

    call("UpdateTable", {"TableName": "orders", "DeletionProtectionEnabled": False})
    status, _ = call("DeleteTable", {"TableName": "orders"})
    _check("DeleteTable allowed once protection is off", status == 200)

    # ── TTL: UpdateTimeToLive / DescribeTimeToLive + lazy expiry ──
    call("CreateTable", {"TableName": "sessions",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    _, body = call("DescribeTimeToLive", {"TableName": "sessions"})
    _check("TTL default disabled", body["TimeToLiveDescription"]["TimeToLiveStatus"] == "DISABLED")
    status, body = call("UpdateTimeToLive", {"TableName": "sessions",
        "TimeToLiveSpecification": {"AttributeName": "expiresAt", "Enabled": True}})
    _check("UpdateTimeToLive 200", status == 200)
    _check("UpdateTimeToLive echoes spec", body["TimeToLiveSpecification"] == {"AttributeName": "expiresAt", "Enabled": True})
    _, body = call("DescribeTimeToLive", {"TableName": "sessions"})
    _check("TTL enabled + attribute", body["TimeToLiveDescription"] == {"TimeToLiveStatus": "ENABLED", "AttributeName": "expiresAt"})

    call("PutItem", {"TableName": "sessions", "Item": {"id": {"S": "live"}, "expiresAt": {"N": str(int(time.time()) + 3600)}}})
    call("PutItem", {"TableName": "sessions", "Item": {"id": {"S": "dead"}, "expiresAt": {"N": str(int(time.time()) - 3600)}}})
    _, body = call("GetItem", {"TableName": "sessions", "Key": {"id": {"S": "dead"}}})
    _check("expired item dropped on GetItem", "Item" not in body)
    _, body = call("Scan", {"TableName": "sessions"})
    _check("Scan only returns live items", [i["id"]["S"] for i in body["Items"]] == ["live"])

    # ── Continuous backups (PITR) ──
    _, body = call("DescribeContinuousBackups", {"TableName": "sessions"})
    _check("PITR default disabled", body["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"] == "DISABLED")
    status, body = call("UpdateContinuousBackups", {"TableName": "sessions",
        "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}})
    _check("UpdateContinuousBackups 200", status == 200)
    _check("PITR now enabled", body["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"] == "ENABLED")
    _check("PITR has earliest restorable time", bool(body["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"].get("EarliestRestorableDateTime")))

    # ── RestoreTableToPointInTime (requires PITR enabled on the source) ──
    call("CreateTable", {"TableName": "no-pitr",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    status, body = call("RestoreTableToPointInTime", {"SourceTableName": "no-pitr", "TargetTableName": "no-pitr-restored",
                                                       "UseLatestRestorableTime": True})
    _check("RestoreTableToPointInTime blocked without PITR", status == 400 and body["__type"] == "InvalidRestoreTimeException")

    status, body = call("RestoreTableToPointInTime", {"SourceTableName": "sessions", "TargetTableName": "sessions-pitr",
                                                       "UseLatestRestorableTime": True})
    _check("RestoreTableToPointInTime 200", status == 200)
    _check("RestoreTableToPointInTime restored table is ACTIVE", body["TableDescription"]["TableStatus"] == "ACTIVE")
    _, body = call("Scan", {"TableName": "sessions-pitr"})
    _check("RestoreTableToPointInTime carries over current items", [i["id"]["S"] for i in body["Items"]] == ["live"])

    status, body = call("RestoreTableToPointInTime", {"SourceTableName": "sessions", "TargetTableName": "sessions-pitr-2",
                                                       "RestoreDateTime": time.time() + 3600})
    _check("RestoreTableToPointInTime rejects a time outside the PITR window",
           status == 400 and body["__type"] == "InvalidRestoreTimeException")

    # ── On-demand backups: Create / List / Describe / Delete / Restore ──
    call("CreateTable", {"TableName": "catalog",
        "KeySchema": [{"AttributeName": "sku", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "sku", "AttributeType": "S"}]})
    call("PutItem", {"TableName": "catalog", "Item": {"sku": {"S": "A1"}, "name": {"S": "Widget"}}})
    status, body = call("CreateBackup", {"TableName": "catalog", "BackupName": "catalog-snap-1"})
    _check("CreateBackup 200", status == 200)
    arn = body["BackupDetails"]["BackupArn"]
    _check("CreateBackup status AVAILABLE", body["BackupDetails"]["BackupStatus"] == "AVAILABLE")

    call("PutItem", {"TableName": "catalog", "Item": {"sku": {"S": "A2"}, "name": {"S": "Gadget"}}})  # added AFTER the snapshot

    _, body = call("ListBackups", {"TableName": "catalog"})
    _check("ListBackups finds it", any(b["BackupArn"] == arn for b in body["BackupSummaries"]))

    _, body = call("DescribeBackup", {"BackupArn": arn})
    _check("DescribeBackup source table name", body["BackupDescription"]["SourceTableDetails"]["TableName"] == "catalog")
    _check("DescribeBackup source item count is pre-snapshot", body["BackupDescription"]["SourceTableDetails"]["ItemCount"] == 1)

    status, body = call("RestoreTableFromBackup", {"BackupArn": arn, "TargetTableName": "catalog-restored"})
    _check("RestoreTableFromBackup 200", status == 200)
    _check("restored table is ACTIVE", body["TableDescription"]["TableStatus"] == "ACTIVE")
    _, body = call("Scan", {"TableName": "catalog-restored"})
    _check("restore only has the pre-snapshot item", [i["sku"]["S"] for i in body["Items"]] == ["A1"])
    _, body = call("Scan", {"TableName": "catalog"})
    _check("live table keeps both items", sorted(i["sku"]["S"] for i in body["Items"]) == ["A1", "A2"])

    status, body = call("DeleteBackup", {"BackupArn": arn})
    _check("DeleteBackup 200", status == 200)
    status, body = call("DescribeBackup", {"BackupArn": arn})
    _check("DeleteBackup then describe -> BackupNotFoundException", status == 400 and body["__type"] == "BackupNotFoundException")

    # ── PartiQL ExecuteStatement: SELECT / INSERT / UPDATE / DELETE ──
    call("CreateTable", {"TableName": "people",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})

    status, body = call("ExecuteStatement", {"Statement": "INSERT INTO \"people\" VALUE {'id': 'p1', 'name': 'Ada', 'age': 30}"})
    _check("PartiQL INSERT 200", status == 200)
    _, body = call("GetItem", {"TableName": "people", "Key": {"id": {"S": "p1"}}})
    _check("PartiQL INSERT persisted", body["Item"]["name"] == {"S": "Ada"} and body["Item"]["age"] == {"N": "30"})

    call("ExecuteStatement", {"Statement": "INSERT INTO \"people\" VALUE {'id': 'p2', 'name': 'Bob', 'age': 44}"})
    status, body = call("ExecuteStatement", {"Statement": "SELECT * FROM \"people\" WHERE age = 44"})
    _check("PartiQL SELECT by attribute", status == 200 and len(body["Items"]) == 1 and body["Items"][0]["id"] == {"S": "p2"})

    status, body = call("ExecuteStatement", {"Statement": "UPDATE \"people\" SET age = 31 WHERE id = 'p1'"})
    _check("PartiQL UPDATE 200", status == 200)
    _, body = call("GetItem", {"TableName": "people", "Key": {"id": {"S": "p1"}}})
    _check("PartiQL UPDATE applied", body["Item"]["age"] == {"N": "31"})

    status, body = call("ExecuteStatement", {"Statement": "DELETE FROM \"people\" WHERE id = 'p2'"})
    _check("PartiQL DELETE 200", status == 200)
    _, body = call("GetItem", {"TableName": "people", "Key": {"id": {"S": "p2"}}})
    _check("PartiQL DELETE removed item", "Item" not in body)

    status, body = call("ExecuteStatement", {"Statement": "SELECT * FROM \"people\" WHERE id = ?",
                                              "Parameters": [{"S": "p1"}]})
    _check("PartiQL SELECT with ? parameter", status == 200 and len(body["Items"]) == 1)

    print("\nDynamoDB table-ops conformance (UpdateTable/TTL/PITR/Backups/PartiQL): ALL GREEN")
    return s


if __name__ == "__main__":
    run()
