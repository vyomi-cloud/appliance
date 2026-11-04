"""Offline Cloud SQL read replicas (gcp.sql.replicas — the shared core has them on Nano):
masterInstanceName is kept, the replica is a READ_REPLICA_INSTANCE listed in the primary's
replicaNames, seeded with the primary's databases and mirroring later ones; a replica is
read-only and can't be the master of another replica."""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-sqlrep-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

B = "/sql/v1beta4/projects/vyomi-project/instances"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def test_read_replica_offline(client):
    p = f"rep{uuid.uuid4().hex[:6]}"
    assert client.post(B, json={"name": p, "databaseVersion": "POSTGRES_15", "region": "us-central1"}).status_code == 200
    assert client.post(f"{B}/{p}/databases", json={"name": "appdb"}).status_code == 200
    assert client.post(B, json={"name": f"{p}-rep", "masterInstanceName": p, "region": "us-central1"}).status_code == 200
    client.post(f"{B}/{p}/databases", json={"name": "later"})
    rep = client.get(f"{B}/{p}-rep").json()
    assert rep["masterInstanceName"] == p and rep["instanceType"] == "READ_REPLICA_INSTANCE"
    assert f"{p}-rep" in client.get(f"{B}/{p}").json()["replicaNames"]
    assert [d["name"] for d in client.get(f"{B}/{p}-rep/databases").json()["items"]] == ["appdb", "later"]
    assert any(i.get("masterInstanceName") == p for i in client.get(B).json()["items"])
    assert client.post(f"{B}/{p}-rep/databases", json={"name": "nope"}).status_code == 400
    assert client.post(B, json={"name": f"{p}-rep2", "masterInstanceName": f"{p}-rep"}).status_code == 400
    assert client.post(B, json={"name": f"{p}-orphan", "masterInstanceName": "does-not-exist"}).status_code == 404


def test_backup_and_restore_offline(client):
    p = f"bk{uuid.uuid4().hex[:6]}"
    client.post(B, json={"name": p, "databaseVersion": "POSTGRES_15", "region": "us-central1"})
    client.post(f"{B}/{p}/databases", json={"name": "keepme"})
    assert client.post(f"{B}/{p}/backupRuns", json={"description": "before"}).json()["operationType"] == "BACKUP_VOLUME"
    runs = client.get(f"{B}/{p}/backupRuns").json()["items"]
    assert len(runs) == 1 and runs[0]["status"] == "SUCCESSFUL"
    bid = runs[0]["id"]
    assert client.get(f"{B}/{p}/backupRuns/{bid}").json()["description"] == "before"
    client.delete(f"{B}/{p}/databases/keepme")
    assert client.get(f"{B}/{p}/databases").json()["items"] == []
    r = client.post(f"{B}/{p}/restoreBackup", json={"restoreBackupContext": {"backupRunId": bid}})
    assert r.json()["operationType"] == "RESTORE_VOLUME"
    assert [d["name"] for d in client.get(f"{B}/{p}/databases").json()["items"]] == ["keepme"]
    assert client.post(f"{B}/{p}/restoreBackup", json={"restoreBackupContext": {"backupRunId": "nope"}}).status_code == 404
    client.delete(f"{B}/{p}/backupRuns/{bid}")
    assert "items" not in client.get(f"{B}/{p}/backupRuns").json()
