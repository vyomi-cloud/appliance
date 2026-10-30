"""v4 C0h — the offline appliance serves Microsoft Graph (Entra ID: users, groups, membership)
through the shared core Nano uses (core/azure_graph_core.py), in the Azure space, durably.
Pre-v4 POST /v1.0/users fell through to the S3 catch-all (405 MethodNotAllowed).
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0h-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def test_users_groups_membership_on_the_core(client):
    nick = f"c0h{uuid.uuid4().hex[:6]}"
    r = client.post("/_wire/v1.0/users", json={
        "accountEnabled": True, "displayName": "C0h User", "mailNickname": nick,
        "userPrincipalName": f"{nick}@vyomi.onmicrosoft.com", "passwordProfile": {"password": "Xy12345!aa"}})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    g = client.post("/v1.0/groups", json={"displayName": nick, "mailEnabled": False,
                                          "mailNickname": nick, "securityEnabled": True})
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    ref = client.post(f"/v1.0/groups/{gid}/members/$ref",
                      json={"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{uid}"})
    assert ref.status_code == 204, ref.text
    members = client.get(f"/v1.0/groups/{gid}/members").json()["value"]
    assert [m["id"] for m in members] == [uid]
    assert any(u["id"] == uid for u in client.get("/beta/users").json()["value"])
    # the directory lives in the Azure space's slot (not an AWS/GCP space)
    from core import app_context as ctx
    from core import appliance_stores as aps
    tok = ctx.REQUEST_PROVIDER.set("azure")
    try:
        assert uid in aps.graph_store().users
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    assert client.delete(f"/v1.0/users/{uid}").status_code == 204
    assert client.get(f"/v1.0/users/{uid}").status_code == 404


def test_unknown_graph_path_is_a_graph_error_not_s3(client):
    r = client.get("/_wire/v1.0/definitelyNotAThing")
    assert r.status_code == 404
    assert r.json()["error"]["code"].startswith("Request_")


def test_cosmos_root_data_plane_on_the_core(client):
    db, coll = f"c0hdb{uuid.uuid4().hex[:6]}", "items"
    assert client.post("/_wire/dbs", json={"id": db}).status_code == 201
    assert client.post(f"/dbs/{db}/colls", json={"id": coll, "partitionKey": {"paths": ["/pk"], "kind": "Hash"}}).status_code == 201
    r = client.post(f"/dbs/{db}/colls/{coll}/docs", json={"id": "a", "pk": "p", "n": 1},
                    headers={"x-ms-documentdb-partitionkey": '["p"]'})
    assert r.status_code == 201, r.text
    got = client.get(f"/dbs/{db}/colls/{coll}/docs/a", headers={"x-ms-documentdb-partitionkey": '["p"]'})
    assert got.status_code == 200 and got.json()["n"] == 1
    from core import app_context as ctx
    from core import appliance_stores as aps
    tok = ctx.REQUEST_PROVIDER.set("azure")
    try:
        assert db in aps.cosmos_store().dbs
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    assert client.delete(f"/dbs/{db}").status_code == 204
