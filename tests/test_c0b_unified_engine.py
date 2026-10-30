"""v4 C0b — the offline appliance serves native Azure Blob, GCP Secret Manager and Cloud
KMS through the shared conformance cores, over ONE state shared with the classic console
REST, durably.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state file,
like tests/test_c0_unified_engine.py.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0b-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")      # no Vault
os.environ.pop("CLOUDLEARN_AZURITE_URL", None)                           # no Azurite

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

AZ = {"x-ms-version": "2021-12-02"}


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _first_route(path: str, method: str):
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"", "headers": []}
    for r in server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return r
    return None


def test_native_paths_are_the_shared_cores(client):
    assert _first_route("/v1/projects/p/secrets", "GET").endpoint.__name__ == "_secrets"
    assert _first_route("/v1/projects/p/secrets/s/versions/latest:access", "GET").endpoint.__name__ == "_secrets"
    assert _first_route("/v1/projects/p/locations/global/keyRings", "GET").endpoint.__name__ == "_kms"
    assert _first_route("/api/gcp/secrets", "GET").endpoint.__module__ == "routes.gcp_secrets_kms_unified"
    assert _first_route("/api/gcp/kms/keys", "GET").endpoint.__module__ == "routes.gcp_secrets_kms_unified"


def test_azure_blob_native_console_share_state(client):
    acct, c = _u("acct").replace("-", "")[:20], _u("ctr")
    assert client.put(f"/{acct}/{c}?restype=container", headers=AZ).status_code == 201
    assert client.put(f"/{acct}/{c}?restype=container", headers=AZ).status_code == 409
    up = client.put(f"/{acct}/{c}/a/b.txt", content=b"0123456789",
                    headers={**AZ, "x-ms-blob-type": "BlockBlob", "x-ms-blob-content-type": "text/plain"})
    assert up.status_code == 201, up.text
    rng = client.get(f"/{acct}/{c}/a/b.txt", headers={**AZ, "x-ms-range": "bytes=2-4"})
    assert rng.status_code == 206 and rng.content == b"234"
    assert rng.headers["content-range"] == "bytes 2-4/10"
    assert client.get(f"/{acct}/{c}/a/b.txt", headers={**AZ, "x-ms-range": "bytes=-3"}).content == b"789"
    # the /_wire prefix (v4 consoles) reaches the same engine
    assert client.get(f"/_wire/{acct}/{c}/a/b.txt", headers=AZ).content == b"0123456789"
    # classic console REST sees native writes …
    names = [x["name"] for x in client.get(f"/api/azure/storage/{acct}/containers/{c}/blobs").json()["value"]]
    assert names == ["a/b.txt"]
    # … and native sees console writes
    r = client.post(f"/api/azure/storage/{acct}/containers/{c}/blobs",
                    files={"file": ("console.txt", b"from-console", "text/plain")})
    assert r.status_code == 200 and r.json()["ok"]
    assert client.get(f"/{acct}/{c}/console.txt", headers=AZ).content == b"from-console"
    lst = client.get(f"/{acct}?comp=list", headers=AZ).text
    assert f"<Name>{c}</Name>" in lst
    # account isolation: another account does not see the container
    assert f"<Name>{c}</Name>" not in client.get(f"/other{acct[:10]}?comp=list", headers=AZ).text
    assert client.delete(f"/{acct}/{c}/console.txt", headers=AZ).status_code == 202
    assert client.get(f"/{acct}/{c}/console.txt", headers=AZ).status_code == 404


def test_gcp_secret_manager_native_and_console_share_state(client):
    p, s = _u("proj"), _u("sec")
    r = client.post(f"/v1/projects/{p}/secrets?secretId={s}", json={"replication": {"automatic": {}}})
    assert r.status_code == 200, r.text
    assert client.post(f"/v1/projects/{p}/secrets?secretId={s}", json={}).status_code == 409
    v = client.post(f"/v1/projects/{p}/secrets/{s}:addVersion", json={"payload": {"data": _b64(b"native")}})
    assert v.json()["name"].endswith("/versions/1")
    assert [x["name"] for x in client.get(f"/v1/projects/{p}/secrets").json()["secrets"]] == [f"projects/{p}/secrets/{s}"]
    assert client.get(f"/v1/projects/{p}/secrets/{s}").status_code == 200       # was a 404 pre-v4
    # console sees the SDK secret and adds a version the SDK reads
    assert s in [x["name"] for x in client.get("/api/gcp/secrets").json()["items"]]
    assert client.get(f"/api/gcp/secrets/{s}").json()["value"] == "native"
    assert client.put(f"/api/gcp/secrets/{s}", json={"value": "console"}).json()["version"] == "2"
    acc = client.get(f"/v1/projects/{p}/secrets/{s}/versions/latest:access").json()
    assert base64.b64decode(acc["payload"]["data"]) == b"console"
    assert client.delete(f"/v1/projects/{p}/secrets/{s}").status_code == 200
    assert client.get(f"/api/gcp/secrets/{s}").status_code == 404


def test_gcp_kms_native_and_console_share_state(client):
    p = _u("kproj")
    base = f"/v1/projects/{p}/locations/global/keyRings"
    assert client.post(f"{base}?keyRingId=r1", json={}).status_code == 200
    ck = client.post(f"{base}/r1/cryptoKeys?cryptoKeyId=k1", json={"purpose": 1})
    assert ck.status_code == 200 and ck.json()["purpose"] == "ENCRYPT_DECRYPT"
    enc = client.post(f"{base}/r1/cryptoKeys/k1:encrypt", json={"plaintext": _b64(b"hi")}).json()
    dec = client.post(f"{base}/r1/cryptoKeys/k1:decrypt", json={"ciphertext": enc["ciphertext"]}).json()
    assert base64.b64decode(dec["plaintext"]) == b"hi"
    assert client.post(f"{base}/r1/cryptoKeys/nope:encrypt", json={"plaintext": _b64(b"x")}).status_code == 404
    rows = client.get("/api/gcp/kms/keys").json()["items"]
    assert any(r["name"] == "k1" and r["keyring"] == "r1" and r["project"] == p for r in rows)
    up = client.put("/api/gcp/kms/keys/k1", json={"labels": {"a": "b"}, "rotation_period": "86400s"}).json()
    assert up["labels"] == {"a": "b"}
    got = client.get(f"{base}/r1/cryptoKeys/k1").json()
    assert got["labels"] == {"a": "b"} and got["rotationPeriod"] == "86400s"
    c2 = client.post("/api/gcp/kms/keys", json={"name": "ck", "keyring": "cring"}).json()
    assert c2["ok"]
    assert client.get("/v1/projects/cloudlearn/locations/global/keyRings/cring/cryptoKeys/ck").status_code == 200


def test_state_is_durable_in_the_kernel_store(client):
    """Containers/blobs, secrets (+versions) and KMS keys (+material) live in the
    appliance state store the tier middleware flushes after each mutation."""
    acct, c, p = "durable" + uuid.uuid4().hex[:6], _u("dur"), _u("durp")
    client.put(f"/{acct}/{c}?restype=container", headers=AZ)
    client.put(f"/{acct}/{c}/x.bin", content=b"\x00\x01durable", headers={**AZ, "x-ms-blob-type": "BlockBlob"})
    client.post(f"/v1/projects/{p}/secrets?secretId=s", json={})
    client.post(f"/v1/projects/{p}/secrets/s:addVersion", json={"payload": {"data": _b64(b"v")}})
    client.post(f"/v1/projects/{p}/locations/global/keyRings?keyRingId=r", json={})
    client.post(f"/v1/projects/{p}/locations/global/keyRings/r/cryptoKeys?cryptoKeyId=k", json={})
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    found = {}
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        ss = sp.get("service_states") or {}
        found.setdefault("blob", {}).update(((ss.get("azure_azure_blob") or {}).get("blobs") or {}))
        found.setdefault("sec", {}).update(((ss.get("gcp_gcp_secretmanager") or {}).get("secrets") or {}))
        found.setdefault("mat", {}).update(((ss.get("gcp_gcp_kms") or {}).get("material") or {}))
        found.setdefault("rings", {}).update(((ss.get("gcp_gcp_kms") or {}).get("rings") or {}))
    assert found["blob"][f"{acct}/{c}"]["x.bin"]["data"] == b"\x00\x01durable"
    assert f"{p}/s" in found["sec"]
    assert isinstance(found["mat"][f"projects/{p}/locations/global/keyRings/r/cryptoKeys/k"], bytes)
    assert f"projects/{p}/locations/global/keyRings/r" in found["rings"]


def test_legacy_opt_out_restores_the_vault_handlers(monkeypatch):
    from core import wire_ingress
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "s3,dynamodb,gcs")
    assert not wire_ingress.is_unified("azure_blob")
    assert not wire_ingress.is_unified("gcp_secrets") and not wire_ingress.is_unified("gcp_kms")
    from fastapi import FastAPI
    from core import vault_routes
    app = FastAPI()
    vault_routes.register(app)
    names = {getattr(r, "endpoint", None).__name__ for r in app.routes if getattr(r, "endpoint", None)}
    assert "gcp_secrets_create" in names and "gcp_kms_encrypt" in names
    monkeypatch.delenv("VYOMI_UNIFIED_INGRESS_SERVICES")
    app2 = FastAPI()
    vault_routes.register(app2)
    names2 = {getattr(r, "endpoint", None).__name__ for r in app2.routes if getattr(r, "endpoint", None)}
    assert "gcp_secrets_create" not in names2 and "gcp_kms_encrypt" not in names2
    assert "_secrets" in names2 and "_kms" in names2
