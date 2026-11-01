"""DynamoDB resource-based policy conformance (v4 wave 5b) — host + Pyodide.

Same contract core/secrets_core.py's PutResourcePolicy proves (see
test_secrets_core.py): the document is validated (valid JSON, Effect +
Principal on every statement), a policy granting '*' access is rejected unless
explicitly confirmed, ExpectedRevisionId is enforced as optimistic concurrency,
and Get/Put/Delete round-trip through the SAME table record other agents would
see over DescribeTable's Permissions tab.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_resource_policy_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

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

    status, body = call("CreateTable", {"TableName": "secured", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                                        "BillingMode": "PAY_PER_REQUEST"})
    arn = body["TableDescription"]["TableArn"]

    status, body = call("GetResourcePolicy", {"ResourceArn": arn})
    _check("no policy yet -> PolicyNotFoundException", status == 400 and body["__type"] == "PolicyNotFoundException")

    status, body = call("PutResourcePolicy", {"ResourceArn": arn, "Policy": "not json"})
    _check("malformed JSON rejected", status == 400 and body["__type"] == "MalformedPolicyDocumentException")

    status, body = call("PutResourcePolicy", {"ResourceArn": arn, "Policy": json.dumps({"Version": "2012-10-17", "Statement": []})})
    _check("empty Statement rejected", status == 400 and body["__type"] == "MalformedPolicyDocumentException")

    public_policy = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": "*", "Action": "dynamodb:GetItem", "Resource": arn}]})
    status, body = call("PutResourcePolicy", {"ResourceArn": arn, "Policy": public_policy})
    _check("public policy rejected by default", status == 400 and body["__type"] == "PolicyNotFoundException")

    status, body = call("PutResourcePolicy", {"ResourceArn": arn, "Policy": public_policy, "ConfirmRemoveSelfResourceAccess": True})
    _check("public policy allowed when confirmed", status == 200)
    revision1 = body["RevisionId"]

    status, body = call("GetResourcePolicy", {"ResourceArn": arn})
    _check("GetResourcePolicy round-trips the document", status == 200 and json.loads(body["Policy"]) == json.loads(public_policy))
    _check("revision matches", body["RevisionId"] == revision1)

    scoped_policy = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:root"}, "Action": "dynamodb:*", "Resource": arn}]})
    status, body = call("PutResourcePolicy", {"ResourceArn": arn, "Policy": scoped_policy, "ExpectedRevisionId": "wrong"})
    _check("stale ExpectedRevisionId rejected", status == 400 and body["__type"] == "PolicyNotFoundException")

    status, body = call("PutResourcePolicy", {"ResourceArn": arn, "Policy": scoped_policy, "ExpectedRevisionId": revision1})
    _check("correct ExpectedRevisionId accepted", status == 200)
    revision2 = body["RevisionId"]
    _check("revision changes on update", revision2 != revision1)

    status, body = call("DeleteResourcePolicy", {"ResourceArn": arn, "ExpectedRevisionId": revision2})
    _check("DeleteResourcePolicy 200", status == 200 and body["RevisionId"] == revision2)

    status, body = call("GetResourcePolicy", {"ResourceArn": arn})
    _check("policy gone after delete", status == 400 and body["__type"] == "PolicyNotFoundException")

    status, body = call("GetResourcePolicy", {"ResourceArn": "arn:aws:dynamodb:us-east-1:123456789012:table/nope"})
    _check("unknown table -> ResourceNotFoundException", status == 400 and body["__type"] == "ResourceNotFoundException")

    print("\nDynamoDB resource-based policy conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
