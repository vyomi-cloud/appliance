"""v4 C0 — the offline appliance serves native S3 / DynamoDB / GCS through the shared
conformance cores, over ONE state shared with the classic console REST, durably.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state
file, the way tests/test_wire_prefix.py does.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")   # no MinIO: inline bytes only

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core import wire_ingress  # noqa: E402

SIG = ("AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/{svc}/aws4_request, "
       "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64)
S3H = {"Authorization": SIG.format(svc="s3")}
DDBH = {"Authorization": SIG.format(svc="dynamodb"), "Content-Type": "application/x-amz-json-1.0"}
NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _ddb(client, op, body):
    return client.post("/", content=json.dumps(body), headers={**DDBH, "X-Amz-Target": f"DynamoDB_20120810.{op}"})


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def test_unified_services_parsing(monkeypatch):
    monkeypatch.delenv("VYOMI_UNIFIED_INGRESS_SERVICES", raising=False)
    monkeypatch.delenv("VYOMI_LEGACY_WIRE", raising=False)
    # C0b added azure_blob / gcp_secrets / gcp_kms to the default set
    assert wire_ingress.unified_services() == {"s3", "dynamodb", "gcs", "azure_blob", "gcp_secrets", "gcp_kms"}
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "s3")
    assert wire_ingress.unified_services() == {"s3"}
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "none")
    assert wire_ingress.unified_services() == frozenset()
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "s3,dynamodb,gcs")
    monkeypatch.setenv("VYOMI_LEGACY_WIRE", "1")
    assert wire_ingress.unified_services() == frozenset()


def test_engine_is_the_shared_core(client):
    """The routes registered for the native wire are the C0 core-backed ones."""
    paths = {getattr(r, "path", ""): getattr(r, "endpoint", None) for r in server.app.routes}
    assert paths["/{bucket}/{key:path}"].__name__ == "s3_object_unified"
    assert "/storage/v1/b/{rest:path}" in paths


def test_s3_native_and_classic_share_state(client):
    b = _u("c0-s3")
    assert client.put(f"/{b}", headers=S3H).status_code == 200
    assert client.put(f"/{b}", headers=S3H).status_code == 409          # BucketAlreadyOwnedByYou
    assert client.put(f"/{b}?versioning", headers=S3H,
                      content=f"<VersioningConfiguration {NS}><Status>Enabled</Status></VersioningConfiguration>"
                      ).status_code == 200
    assert client.put(f"/{b}/k.txt", headers=S3H, content=b"native").status_code == 200
    listed = client.get("/api/s3/buckets").json()["buckets"]
    row = next(x for x in listed if x["name"] == b)
    assert row["versioning"] == "Enabled"
    keys = [o["key"] for o in client.get(f"/api/s3/buckets/{b}/objects").json()["objects"]]
    assert "k.txt" in keys
    # reverse: a classic-console bucket is visible on the native wire
    cb = _u("c0-classic")
    assert client.post(f"/api/s3/buckets/{cb}").status_code in (200, 201)
    assert f"<Name>{cb}</Name>" in client.get("/", headers=S3H).text
    assert f"<Name>{cb}</Name>" in client.get("/_wire/", headers=S3H).text


def test_s3_notification_is_delivered_and_round_trips(client):
    b = _u("c0-notif")
    client.put(f"/{b}", headers=S3H)
    cfg = (f"<NotificationConfiguration {NS}><QueueConfiguration><Id>q</Id>"
           "<Queue>arn:aws:sqs:us-east-1:123456789012:c0-q</Queue><Event>s3:ObjectCreated:*</Event>"
           "</QueueConfiguration></NotificationConfiguration>")
    assert client.put(f"/{b}?notification", headers=S3H, content=cfg).status_code == 200
    assert "c0-q" in client.get(f"/{b}?notification", headers=S3H).text
    client.put(f"/{b}/obj", headers=S3H, content=b"x")
    from core import app_context as ctx
    deliveries = ctx.buckets[b]["notifications"]["deliveries"]
    assert any(d["event_name"] == "s3:ObjectCreated:Put" for d in deliveries), deliveries


def test_reserved_names_still_404(client):
    assert client.get("/api/definitely-not-a-route", headers=S3H).status_code == 404


def test_root_browser_vs_sdk(client):
    html = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    assert "ListAllMyBucketsResult" not in html.text
    sdk = client.get("/", headers={**S3H, "User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    assert "ListAllMyBucketsResult" in sdk.text
    assert "ListAllMyBucketsResult" in client.get("/_wire/", headers={"User-Agent": "Mozilla/5.0"}).text


def test_dynamodb_native_and_classic_share_state(client):
    t = _u("c0-tbl")
    r = _ddb(client, "CreateTable", {"TableName": t, "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                     "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    assert r.status_code == 200, r.text
    _ddb(client, "PutItem", {"TableName": t, "Item": {"id": {"S": "a"}, "n": {"N": "1"}}})
    names = [x["table_name"] for x in client.get("/api/dynamodb/tables").json()["tables"]]
    assert t in names
    client.post(f"/api/dynamodb/tables/{t}/items", json={"item": {"id": "b", "n": 2}})
    got = _ddb(client, "GetItem", {"TableName": t, "Key": {"id": {"S": "b"}}}).json()
    assert got["Item"]["n"] == {"N": "2"}
    cond = _ddb(client, "PutItem", {"TableName": t, "Item": {"id": {"S": "a"}},
                                    "ConditionExpression": "attribute_not_exists(id)"})
    assert cond.status_code == 400 and "ConditionalCheckFailed" in cond.text


def test_gcs_native_console_alias_and_facade_share_state(client):
    b = _u("c0-gcs")
    r = client.post("/storage/v1/b?project=p", json={"name": b, "labels": {"env": "c0"},
                                                     "retentionPolicy": {"retentionPeriod": 5}})
    assert r.status_code == 200, r.text
    up = client.post(f"/upload/storage/v1/b/{b}/o?uploadType=media&name=a%2Fb.txt",
                     content=b"gcs-bytes", headers={"Content-Type": "text/plain"})
    assert up.status_code == 200, up.text
    assert client.get(f"/storage/v1/b/{b}/o/a%2Fb.txt?alt=media").content == b"gcs-bytes"
    assert client.get(f"/_wire/download/storage/v1/b/{b}/o/a%2Fb.txt?alt=media").content == b"gcs-bytes"
    assert client.get(f"/api/gcp/storage/v1/b/{b}").json()["labels"] == {"env": "c0"}
    facade = [x["name"] for x in client.get("/api/console/gcs/buckets").json()["buckets"]]
    assert b in facade
    fb = _u("c0-facade")
    client.post(f"/api/console/gcs/buckets/{fb}")
    assert fb in [x["name"] for x in client.get("/storage/v1/b").json().get("items", [])]


def test_state_is_durable_in_the_kernel_store(client):
    """Bucket config / GCS settings / tables live in the appliance state store that the
    tier middleware flushes after each mutation — a fresh load (= restart) sees them."""
    b, g, t = _u("c0-dur"), _u("c0-durg"), _u("c0-durt")
    client.put(f"/{b}", headers=S3H)
    client.put(f"/{b}?tagging", headers=S3H,
               content=f"<Tagging {NS}><TagSet><Tag><Key>k</Key><Value>v</Value></Tag></TagSet></Tagging>")
    client.post("/storage/v1/b", json={"name": g, "labels": {"x": "y"}})
    _ddb(client, "CreateTable", {"TableName": t, "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                 "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    blob = json.dumps(state, default=lambda o: "<bytes>")
    assert f'"{b}"' in blob and '"tagging"' in blob
    assert f'"{g}"' in blob and '"labels": {"x": "y"}' in blob
    assert f'"{t}"' in blob
