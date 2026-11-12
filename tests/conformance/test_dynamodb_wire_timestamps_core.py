"""DynamoDB wire timestamps are epoch NUMBERS, as in real DynamoDB (official SDKs refuse ISO strings).

Go SDK v2 fails with "expected Date to be a JSON Number" and Java v1 with "Input timestamp string must be no
longer than 20 characters" when CreateTable returns CreationDateTime as an ISO string.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_wire_timestamps_core.py
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
    print(f"[PASS] {name}")


def _is_epoch(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v - time.time()) < 3600


def run(store=None):
    s = store or InMemoryNoSqlStore()

    def call(a, p):
        r = d.dispatch(s, P + a, p)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    st, body = call("CreateTable", {"TableName": "ts-t", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                                    "BillingMode": "PAY_PER_REQUEST"})
    _check("CreateTable 200", st == 200)
    _check("CreateTable CreationDateTime is an epoch number", _is_epoch(body["TableDescription"]["CreationDateTime"]))
    st, body = call("DescribeTable", {"TableName": "ts-t"})
    _check("DescribeTable CreationDateTime is an epoch number", _is_epoch(body["Table"]["CreationDateTime"]))
    st, body = call("ListTables", {})
    _check("ListTables still lists the table", body["TableNames"] == ["ts-t"])

    st, body = call("CreateBackup", {"TableName": "ts-t", "BackupName": "b1"})
    _check("CreateBackup 200", st == 200)
    arn = body["BackupDetails"]["BackupArn"]
    _check("CreateBackup BackupCreationDateTime is an epoch number", _is_epoch(body["BackupDetails"]["BackupCreationDateTime"]))
    st, body = call("DescribeBackup", {"BackupArn": arn})
    _check("DescribeBackup BackupCreationDateTime is an epoch number", _is_epoch(body["BackupDescription"]["BackupDetails"]["BackupCreationDateTime"]))
    _check("DescribeBackup TableCreationDateTime is an epoch number", _is_epoch(body["BackupDescription"]["SourceTableDetails"]["TableCreationDateTime"]))
    print("DDB WIRE TIMESTAMPS OK")


if __name__ == "__main__":
    run()
