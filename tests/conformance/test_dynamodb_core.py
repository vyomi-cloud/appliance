"""DynamoDB core conformance — the acceptance gate for the WASM extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE AWS DynamoDB wire semantics (X-Amz-Target dispatch, typed
attribute values {"S":..}/{"N":..}, TableDescription/Item/Items/Count shapes,
KeyConditionExpression with begins_with + BETWEEN, AttributeUpdates + SET
UpdateExpression, BatchWriteItem/BatchGetItem, native {"__type","message"}
errors) — proving the extracted core conforms regardless of substrate. No
network, no fastapi/boto3: pure functions over the NoSqlStore seam.

Run on host:    python3 tests/conformance/test_dynamodb_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as ddb
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as ddb  # type: ignore

T = "DynamoDB_20120810."  # the native X-Amz-Target prefix


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemoryNoSqlStore()

    # 1. CreateTable (native KeySchema + AttributeDefinitions) -> TableDescription
    r = ddb.dispatch(st, T + "CreateTable", {
        "TableName": "Music",
        "AttributeDefinitions": [
            {"AttributeName": "Artist", "AttributeType": "S"},
            {"AttributeName": "SongTitle", "AttributeType": "S"},
        ],
        "KeySchema": [
            {"AttributeName": "Artist", "KeyType": "HASH"},
            {"AttributeName": "SongTitle", "KeyType": "RANGE"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    })
    _check("create 200", r.status == 200)
    td = r.body["TableDescription"]
    _check("create TableName", td["TableName"] == "Music")
    _check("create TableStatus ACTIVE", td["TableStatus"] == "ACTIVE")
    _check("create KeySchema HASH+RANGE",
           td["KeySchema"] == [{"AttributeName": "Artist", "KeyType": "HASH"},
                               {"AttributeName": "SongTitle", "KeyType": "RANGE"}])
    _check("create TableArn", td["TableArn"].endswith(":table/Music"))

    # 2. CreateTable again -> ResourceInUseException (native __type)
    dup = ddb.dispatch(st, T + "CreateTable", {"TableName": "Music",
                       "KeySchema": [{"AttributeName": "Artist", "KeyType": "HASH"}],
                       "AttributeDefinitions": [{"AttributeName": "Artist", "AttributeType": "S"}]})
    _check("duplicate 400", dup.status == 400)
    _check("duplicate __type ResourceInUseException", dup.body["__type"] == "ResourceInUseException")

    # 3. PutItem -> 200; typed values round-trip through native encoding
    p = ddb.dispatch(st, T + "PutItem", {"TableName": "Music", "Item": {
        "Artist": {"S": "No One You Know"},
        "SongTitle": {"S": "Call Me Today"},
        "Year": {"N": "2015"},
        "InStock": {"BOOL": True},
        "Genres": {"SS": ["pop", "rock"]},
    }})
    _check("put 200", p.status == 200)

    # 4. GetItem -> native typed Item; N stays a number-string, BOOL preserved
    g = ddb.dispatch(st, T + "GetItem", {"TableName": "Music",
        "Key": {"Artist": {"S": "No One You Know"}, "SongTitle": {"S": "Call Me Today"}}})
    _check("get 200", g.status == 200)
    item = g.body["Item"]
    _check("get S value", item["Artist"] == {"S": "No One You Know"})
    _check("get N value", item["Year"] == {"N": "2015"})
    _check("get BOOL value", item["InStock"] == {"BOOL": True})
    _check("get SS value", item["Genres"] == {"SS": ["pop", "rock"]})

    # 5. GetItem missing key -> empty body (DynamoDB returns no Item key)
    miss = ddb.dispatch(st, T + "GetItem", {"TableName": "Music",
        "Key": {"Artist": {"S": "Nobody"}, "SongTitle": {"S": "Nothing"}}})
    _check("get-missing 200", miss.status == 200)
    _check("get-missing no Item", "Item" not in miss.body)

    # 6. PutItem missing partition key -> ValidationException
    bad = ddb.dispatch(st, T + "PutItem", {"TableName": "Music",
        "Item": {"SongTitle": {"S": "Orphan"}}})
    _check("put-missing-pk 400", bad.status == 400)
    _check("put-missing-pk ValidationException", bad.body["__type"] == "ValidationException")

    # 7. Seed several sort-key rows for one partition, then Query
    for title in ["Aria", "Ballad", "Chorus", "Coda"]:
        ddb.dispatch(st, T + "PutItem", {"TableName": "Music", "Item": {
            "Artist": {"S": "No One You Know"}, "SongTitle": {"S": title}}})

    # 7a. Query KeyConditionExpression: partition = :a  (all rows for the artist)
    q = ddb.dispatch(st, T + "Query", {"TableName": "Music",
        "KeyConditionExpression": "Artist = :a",
        "ExpressionAttributeValues": {":a": {"S": "No One You Know"}}})
    _check("query 200", q.status == 200)
    _check("query Count = 5", q.body["Count"] == 5)  # Call Me Today + 4 seeded
    _check("query Items typed", all("Artist" in i for i in q.body["Items"]))

    # 7b. Query begins_with on the sort key -> only "Aria"
    qb = ddb.dispatch(st, T + "Query", {"TableName": "Music",
        "KeyConditionExpression": "Artist = :a AND begins_with(SongTitle, :p)",
        "ExpressionAttributeValues": {":a": {"S": "No One You Know"}, ":p": {"S": "Ar"}}})
    _check("query begins_with Count 1", qb.body["Count"] == 1)
    _check("query begins_with match", qb.body["Items"][0]["SongTitle"] == {"S": "Aria"})

    # 7c. Query BETWEEN on the sort key -> Ballad..Coda inclusive (Ballad,Call,Chorus,Coda)
    qbt = ddb.dispatch(st, T + "Query", {"TableName": "Music",
        "KeyConditionExpression": "Artist = :a AND SongTitle BETWEEN :lo AND :hi",
        "ExpressionAttributeValues": {":a": {"S": "No One You Know"},
                                      ":lo": {"S": "B"}, ":hi": {"S": "D"}}})
    titles = sorted(i["SongTitle"]["S"] for i in qbt.body["Items"])
    _check("query BETWEEN window", titles == ["Ballad", "Call Me Today", "Chorus", "Coda"])

    # 8. UpdateItem via SET UpdateExpression
    u = ddb.dispatch(st, T + "UpdateItem", {"TableName": "Music",
        "Key": {"Artist": {"S": "No One You Know"}, "SongTitle": {"S": "Aria"}},
        "UpdateExpression": "SET Plays = :p",
        "ExpressionAttributeValues": {":p": {"N": "42"}}})
    _check("update 200", u.status == 200)
    _check("update SET applied", u.body["Attributes"]["Plays"] == {"N": "42"})

    # 8b. UpdateItem via legacy AttributeUpdates (PUT + DELETE)
    u2 = ddb.dispatch(st, T + "UpdateItem", {"TableName": "Music",
        "Key": {"Artist": {"S": "No One You Know"}, "SongTitle": {"S": "Aria"}},
        "AttributeUpdates": {"Mood": {"Action": "PUT", "Value": {"S": "calm"}},
                             "Plays": {"Action": "DELETE"}}})
    _check("update PUT added attr", u2.body["Attributes"]["Mood"] == {"S": "calm"})
    _check("update DELETE removed attr", "Plays" not in u2.body["Attributes"])

    # 9. Scan -> all items, Count + ScannedCount
    sc = ddb.dispatch(st, T + "Scan", {"TableName": "Music"})
    _check("scan 200", sc.status == 200)
    _check("scan Count = 5", sc.body["Count"] == 5)
    _check("scan ScannedCount = 5", sc.body["ScannedCount"] == 5)

    # 10. DeleteItem -> 200; subsequent GetItem returns no Item
    d = ddb.dispatch(st, T + "DeleteItem", {"TableName": "Music",
        "Key": {"Artist": {"S": "No One You Know"}, "SongTitle": {"S": "Coda"}}})
    _check("delete 200", d.status == 200)
    after = ddb.dispatch(st, T + "GetItem", {"TableName": "Music",
        "Key": {"Artist": {"S": "No One You Know"}, "SongTitle": {"S": "Coda"}}})
    _check("get after delete no Item", "Item" not in after.body)

    # 11. Operations on a missing table -> ResourceNotFoundException
    nf = ddb.dispatch(st, T + "GetItem", {"TableName": "Ghost", "Key": {"id": {"S": "x"}}})
    _check("missing table 404", nf.status == 404)
    _check("missing table __type", nf.body["__type"] == "ResourceNotFoundException")

    # 12. BatchWriteItem (Put + Delete) then BatchGetItem
    ddb.dispatch(st, T + "CreateTable", {"TableName": "Tags",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    bw = ddb.dispatch(st, T + "BatchWriteItem", {"RequestItems": {"Tags": [
        {"PutRequest": {"Item": {"id": {"S": "t1"}, "label": {"S": "alpha"}}}},
        {"PutRequest": {"Item": {"id": {"S": "t2"}, "label": {"S": "beta"}}}},
    ]}})
    _check("batch-write 200", bw.status == 200)
    _check("batch-write no UnprocessedItems", bw.body["UnprocessedItems"] == {})
    bg = ddb.dispatch(st, T + "BatchGetItem", {"RequestItems": {"Tags": {
        "Keys": [{"id": {"S": "t1"}}, {"id": {"S": "t2"}}]}}})
    got = sorted(i["label"]["S"] for i in bg.body["Responses"]["Tags"])
    _check("batch-get round-trips both", got == ["alpha", "beta"])

    # 13. ListTables + DescribeTable
    lt = ddb.dispatch(st, T + "ListTables", {})
    _check("list-tables both present", sorted(lt.body["TableNames"]) == ["Music", "Tags"])
    dt = ddb.dispatch(st, T + "DescribeTable", {"TableName": "Tags"})
    _check("describe ItemCount = 2", dt.body["Table"]["ItemCount"] == 2)

    # 14. Tags lifecycle
    ddb.dispatch(st, T + "TagResource", {"TableName": "Tags",
        "Tags": [{"Key": "env", "Value": "nano"}, {"Key": "team", "Value": "sim"}]})
    tags = ddb.dispatch(st, T + "ListTagsOfResource", {"TableName": "Tags"})
    pairs = {t["Key"]: t["Value"] for t in tags.body["Tags"]}
    _check("tags set", pairs == {"env": "nano", "team": "sim"})
    ddb.dispatch(st, T + "UntagResource", {"TableName": "Tags", "TagKeys": ["team"]})
    tags2 = ddb.dispatch(st, T + "ListTagsOfResource", {"TableName": "Tags"})
    _check("tags after untag", [t["Key"] for t in tags2.body["Tags"]] == ["env"])

    # 15. DeleteTable -> DELETING; then it's gone
    dtl = ddb.dispatch(st, T + "DeleteTable", {"TableName": "Tags"})
    _check("delete-table status DELETING", dtl.body["TableDescription"]["TableStatus"] == "DELETING")
    gone = ddb.dispatch(st, T + "DescribeTable", {"TableName": "Tags"})
    _check("delete-table then describe 404", gone.status == 404)

    # 16. Unknown action -> UnknownOperationException; missing target -> MissingAction
    unk = ddb.dispatch(st, T + "Frobnicate", {})
    _check("unknown action 400", unk.body["__type"] == "UnknownOperationException")
    noact = ddb.dispatch(st, "", {})
    _check("missing target MissingAction", noact.body["__type"] == "MissingAction")

    print("\nRESULT: PASS — DynamoDB core conforms (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
