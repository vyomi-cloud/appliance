"""`/_wire/<native path>` must behave exactly like `/<native path>` on the
offline appliance: same handler, same state, same middleware verdicts.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway
state file, like tests/test_api_parity_contracts.py does with a subprocess.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-wire-prefix-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
# CI escape hatch for tier limits (Free tier locks DynamoDB, caps buckets);
# test_tier_lock_applies_to_wire re-enables enforcement explicitly.
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from routes.wire_prefix import strip_prefix  # noqa: E402

# Dummy SigV4 header, as the console's browser-side signer sends it.
SIGV4_S3 = ("AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/s3/aws4_request, "
            "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64)
SIGV4_DDB = SIGV4_S3.replace("/s3/", "/dynamodb/")
DDB_HDRS = {"Content-Type": "application/x-amz-json-1.0", "Authorization": SIGV4_DDB}


def _u(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def test_strip_prefix_unit():
    assert strip_prefix("/_wire") == "/"
    assert strip_prefix("/_wire/") == "/"
    assert strip_prefix("/_wire/b/k/x.txt") == "/b/k/x.txt"
    assert strip_prefix("/_wirex/b") is None
    assert strip_prefix("/b/_wire/x") is None


def test_s3_create_via_wire_visible_natively(client):
    bucket = _u("wire-ui")
    r = client.put(f"/_wire/{bucket}", headers={"Authorization": SIGV4_S3})
    assert r.status_code == 200, r.text
    # ListBuckets through BOTH paths sees it.
    for path in ("/", "/_wire/"):
        r = client.get(path, headers={"Authorization": SIGV4_S3})
        assert r.status_code == 200, (path, r.text[:300])
        assert "ListAllMyBucketsResult" in r.text and f"<Name>{bucket}</Name>" in r.text, path
    # Binary object round trip: put via /_wire, get natively and via /_wire.
    blob = bytes(range(256)) * 4
    r = client.put(f"/_wire/{bucket}/dir/obj.bin", content=blob,
                   headers={"Authorization": SIGV4_S3, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    etag = r.headers.get("etag")
    for path in (f"/{bucket}/dir/obj.bin", f"/_wire/{bucket}/dir/obj.bin"):
        g = client.get(path, headers={"Authorization": SIGV4_S3})
        assert g.status_code == 200, (path, g.text[:200])
        assert g.content == blob, path
        assert g.headers.get("etag") == etag, path
    # ListObjectsV2 with a query string survives the prefix.
    r = client.get(f"/_wire/{bucket}?list-type=2&prefix=dir/", headers={"Authorization": SIGV4_S3})
    assert r.status_code == 200 and "<Key>dir/obj.bin</Key>" in r.text, r.text[:300]


def test_s3_create_natively_visible_via_wire(client):
    bucket = _u("wire-cli")
    assert client.put(f"/{bucket}", headers={"Authorization": SIGV4_S3}).status_code == 200
    assert client.put(f"/{bucket}/hello.txt", content=b"hi from cli",
                      headers={"Authorization": SIGV4_S3}).status_code == 200
    r = client.get("/_wire/", headers={"Authorization": SIGV4_S3})
    assert f"<Name>{bucket}</Name>" in r.text
    g = client.get(f"/_wire/{bucket}/hello.txt", headers={"Authorization": SIGV4_S3})
    assert g.status_code == 200 and g.content == b"hi from cli"
    # Native error shape passes through unchanged.
    m = client.get(f"/_wire/{bucket}/missing.txt", headers={"Authorization": SIGV4_S3})
    n = client.get(f"/{bucket}/missing.txt", headers={"Authorization": SIGV4_S3})
    assert m.status_code == n.status_code == 404
    strip_rid = lambda b: re.sub(rb"<RequestId>[^<]*</RequestId>", b"", b)  # noqa: E731
    assert strip_rid(m.content) == strip_rid(n.content)


def _ddb(client, path: str, op: str, body: dict):
    return client.post(path, content=json.dumps(body),
                       headers={**DDB_HDRS, "X-Amz-Target": f"DynamoDB_20120810.{op}"})


def _table_names(resp) -> list:
    # Native ListTables is {"TableNames": [...]}. When DynamoDB Local is not
    # running (as in this test) the appliance's in-memory FALLBACK answers
    # with {"table_names": [...]} — a pre-existing fidelity gap of the
    # fallback, identical on both paths, which is what this test pins.
    j = resp.json()
    return j.get("TableNames") or j.get("table_names") or []


def test_dynamodb_via_wire_and_native(client):
    table = _u("wire_tbl")
    r = _ddb(client, "/_wire/", "CreateTable", {
        "TableName": table,
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "BillingMode": "PAY_PER_REQUEST"})
    assert r.status_code == 200, r.text
    a = _ddb(client, "/", "ListTables", {})
    b = _ddb(client, "/_wire/", "ListTables", {})
    assert a.status_code == b.status_code == 200
    assert a.content == b.content
    assert table in _table_names(b), b.text
    r = _ddb(client, "/_wire/", "PutItem", {"TableName": table,
                                             "Item": {"id": {"S": "a"}, "v": {"N": "7"}}})
    assert r.status_code == 200, r.text
    # Written via the console prefix, read via the native path (and reverse).
    gi = _ddb(client, "/", "GetItem", {"TableName": table, "Key": {"id": {"S": "a"}}})
    assert gi.status_code == 200 and gi.json()["Item"]["v"] == {"N": "7"}, gi.text
    assert _ddb(client, "/", "PutItem", {"TableName": table,
                                         "Item": {"id": {"S": "b"}}}).status_code == 200
    gi = _ddb(client, "/_wire/", "GetItem", {"TableName": table, "Key": {"id": {"S": "b"}}})
    assert gi.status_code == 200 and gi.json()["Item"]["id"] == {"S": "b"}, gi.text


def test_recursion_guard(client):
    for path in ("/_wire/_wire/", "/_wire/_wire/some-bucket", "/_wire/_wire"):
        r = client.get(path, headers={"Authorization": SIGV4_S3})
        assert r.status_code == 400, (path, r.status_code, r.text[:200])
        assert r.json()["error"]["code"] == "WirePrefixRecursion"


def test_unknown_tenant_rejected_on_both_paths(client):
    h = {"Authorization": SIGV4_S3, "X-CloudLearn-Tenant": "no-such-tenant-" + uuid.uuid4().hex[:6]}
    a = client.get("/", headers=h)
    b = client.get("/_wire/", headers=h)
    assert a.status_code == b.status_code == 403
    assert a.json() == b.json()


def test_path_keyed_profile_gate_applies_to_wire(client, monkeypatch):
    # aws-full sandbox profile: GCP paths are refused by the path-keyed tier
    # middleware. The prefixed request must be judged on the NATIVE path too.
    monkeypatch.setenv("VYOMI_PROFILE", "aws-full")
    a = client.get("/storage/v1/b?project=demo")
    b = client.get("/_wire/storage/v1/b?project=demo")
    assert a.status_code == 403, a.text[:200]
    assert b.status_code == 403, b.text[:200]
    assert a.json() == b.json()
    assert b.headers.get("x-vyomi-profile-denied") == a.headers.get("x-vyomi-profile-denied")
    # And AWS stays allowed under the same profile.
    assert client.get("/_wire/", headers={"Authorization": SIGV4_S3}).status_code == 200


def test_tier_lock_applies_to_wire(client, monkeypatch):
    # Free tier locks DynamoDB in the path/target-keyed tier middleware.
    import core.middleware as mw
    monkeypatch.setattr(mw, "_TIER_ENFORCE", True)
    a = _ddb(client, "/", "ListTables", {})
    b = _ddb(client, "/_wire/", "ListTables", {})
    assert a.status_code == 403, a.text[:200]
    assert b.status_code == 403, b.text[:200]
    assert a.json() == b.json()


def test_gcs_list_via_wire_matches_native(client):
    a = client.get("/storage/v1/b?project=demo")
    b = client.get("/_wire/storage/v1/b?project=demo")
    assert a.status_code == b.status_code
    assert a.content == b.content
