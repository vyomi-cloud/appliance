"""OFFLINE appliance Azure wiring: the data planes below are served by the SAME core engines Nano uses (core/azure_sql_core +
azure_sql_security_core, azure_cosmos_core, azure_cmk_core, azure_storage_svc_core) — proved over the offline HTTP wire
(the real `server.app` on a loopback socket, durable space state), with the native SDK where one exists (azure-cosmos,
azure-storage-queue, azure-data-tables, azure-appconfiguration, azure-mgmt-sql/cosmosdb).

    PYTHONPATH=. python3 -m pytest -q tests/conformance/test_azure_offline_wiring.py
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

_D = Path(tempfile.mkdtemp(prefix="vyomi-azoffline-"))
os.environ["CLOUDLEARN_STATE_FILE"] = str(_D / "state.sqlite3")
os.environ["CLOUDLEARN_LEGACY_STATE_FILE"] = str(_D / "state.pkl")
os.environ["VYOMI_NO_TELEMETRY"] = "1"
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

S = "00000000-0000-0000-0000-cloudlearn01"
RG = f"/subscriptions/{S}/resourceGroups/ow-rg"
C = TestClient(server.app)


@pytest.fixture(scope="module")
def base():
    """The offline appliance on a real loopback socket (SDKs need a real HTTP endpoint)."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True


def arm(method, path, body=None, v="2023-08-01"):
    r = C.request(method, path, params={"api-version": v}, json=body)
    assert r.status_code < 300, (method, path, r.status_code, r.text[:300])
    return r.json() if r.content else {}


def _rg():
    arm("PUT", RG, {"location": "eastus"}, "2021-04-01")


# ───────────────────────────── Azure SQL (security engine) ─────────────────────────────
SRV = f"{RG}/providers/Microsoft.Sql/servers/owsql"


def _sql_setup():
    _rg()
    arm("PUT", SRV, {"location": "eastus", "properties": {"administratorLogin": "adm", "administratorLoginPassword": "Xx123456789!"}})
    for d, props in (("d1", {}), ("led", {"isLedgerOn": True})):
        arm("PUT", f"{SRV}/databases/{d}", {"location": "eastus", "properties": props})
        C.put(f"/azure-sql/servers/owsql/databases/{d}")
    C.put("/azure-sql/servers/owsql")


def Q(sql, login=None, db="d1", **kw):
    h = {"x-vyomi-sql-login": login} if login else {}
    return C.post(f"/azure-sql/servers/owsql/databases/{db}/query", json={"sql": sql, **kw}, headers=h)


def test_sql_datamasking_ledger_discovery_over_offline_wire():
    _sql_setup()
    db = f"{SRV}/databases/d1"
    Q("CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT, ssn TEXT, salary INTEGER, note TEXT)")
    Q("INSERT INTO people VALUES (1,'alice@example.com','123-45-6789',90000,'hello')")
    arm("PUT", f"{db}/dataMaskingPolicies/Default", {"properties": {"dataMaskingState": "Enabled", "exemptPrincipals": "boss"}})
    for n, props in {"r1": {"columnName": "email", "maskingFunction": "Email"}, "r2": {"columnName": "ssn", "maskingFunction": "SSN"},
                     "r3": {"columnName": "salary", "maskingFunction": "Default"},
                     "r4": {"columnName": "note", "maskingFunction": "Text", "prefixSize": 1, "suffixSize": 1, "replacementString": "***"}}.items():
        arm("PUT", f"{db}/dataMaskingPolicies/Default/rules/{n}", {"properties": {"schemaName": "dbo", "tableName": "people", **props}})
    assert Q("SELECT email, ssn, salary, note FROM people").json()["rows"][0] == ["alice@example.com", "123-45-6789", 90000, "hello"]
    assert Q("SELECT email, ssn, salary, note FROM people", "bob").json()["rows"][0] == ["aXXX@XXXX.com", "XXX-XX-6789", 0, "h***o"]
    assert Q("SELECT email FROM people", "boss").json()["rows"][0][0] == "alice@example.com"
    assert Q("GRANT UNMASK TO bob").status_code == 200
    assert Q("SELECT email FROM people", "bob").json()["rows"][0][0] == "alice@example.com"
    assert Q("GRANT UNMASK TO eve", "bob").status_code == 403
    Q("REVOKE UNMASK FROM bob")
    assert Q("SELECT email FROM people", "bob").json()["rows"][0][0] == "aXXX@XXXX.com"

    # data discovery: recommendations from real values + a classified read lands in the audit log
    d = C.get("/azure-sql/servers/owsql/databases/d1/security/discovery").json()
    byc = {c["column"]: c for c in d["columns"]}
    assert byc["email"]["recommendation"]["source"] == "data" and byc["ssn"]["recommendation"]["informationType"] == "National ID"
    assert byc["salary"]["recommendation"]["source"] == "name"
    arm("PUT", f"{db}/schemas/dbo/tables/people/columns/email/sensitivityLabels/current",
        {"properties": {"labelName": "Confidential", "informationType": "Contact Info", "rank": "Medium"}}, "2020-11-01-preview")
    Q("SELECT email, note FROM people")
    ins = C.get("/azure-sql/servers/owsql/databases/d1/queryinsights").json()
    aud = [x for x in ins["audit"] if x.get("dataSensitivityInformation")]
    assert aud and aud[0]["dataSensitivityInformation"][0]["columnName"] == "email"

    # ledger: append-only table + updatable ledger database, digest, verify
    Q("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT) WITH (LEDGER = ON (APPEND_ONLY = ON))")
    assert Q("INSERT INTO t VALUES (1,'a')").status_code == 200
    r = Q("UPDATE t SET v='z' WHERE id=1")
    assert r.status_code == 400 and "37359" in r.json()["error"]["message"]
    assert Q("DELETE FROM t WHERE id=1").status_code == 400
    assert Q("DELETE FROM __vyomi_ledger_blocks").status_code == 403
    Q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)", db="led")
    Q("INSERT INTO u VALUES (1,'a')", db="led"); Q("UPDATE u SET v='b' WHERE id=1", db="led")
    dg = C.post("/azure-sql/servers/owsql/databases/led/security/ledger/digest").json()
    assert dg["hash"].startswith("0x") and dg["block_id"] >= 1
    v = C.post("/azure-sql/servers/owsql/databases/led/security/ledger/verify").json()
    assert v["ok"] and v["digestsVerified"] == 1
    # tamper the stored ledger block (a DBA bypassing the ledger path) -> verify must fail
    from core import azure_sql_core as _sql
    from core import wire_ingress as _wi
    st = _wi._NEW_SERVICES_ROUTER.rds
    st.execute_sql("azuresql:owsql/led", "UPDATE u SET v='HACKED' WHERE id=1")
    v = C.post("/azure-sql/servers/owsql/databases/led/security/ledger/verify").json()
    assert not v["ok"] and "outside the ledger" in v["issues"][0]


def _kvkey(method, path, body=None):
    return C.request(method, path, params={"api-version": "7.4"}, json=body or {})


def test_sql_always_encrypted_over_offline_wire():
    _sql_setup()
    assert _kvkey("POST", "/keys/cmk1/create", {"kty": "RSA"}).status_code == 200
    D = "/azure-sql/servers/owsql/databases/d1/security/ae"
    Q("CREATE TABLE pat (id INTEGER PRIMARY KEY, ssn TEXT, dx TEXT)")
    Q("INSERT INTO pat VALUES (1,'111-22-3333','flu')")
    assert C.put(f"{D}/cmk/cmk_a", json={"keyPath": "https://kv1.vault.azure.net/keys/cmk1"}).status_code == 200
    assert C.put(f"{D}/cmk/bad", json={"keyPath": "https://kv1.vault.azure.net/keys/nope"}).status_code == 400
    assert C.put(f"{D}/cek/cek_a", json={"cmk": "cmk_a"}).status_code == 200
    r = C.post(f"{D}/encrypt", json={"table": "pat", "column": "ssn", "cek": "cek_a", "encryptionType": "Deterministic"}).json()
    assert r["rowsEncrypted"] == 1
    C.post(f"{D}/encrypt", json={"table": "pat", "column": "dx", "cek": "cek_a", "encryptionType": "Randomized"})
    assert Q("SELECT ssn FROM pat").json()["rows"][0][0].startswith("0x01")        # ciphertext without the driver setting
    assert Q("INSERT INTO pat VALUES (?,?,?)", params=[2, "999-99-9999", "cold"]).status_code == 400
    assert Q("INSERT INTO pat (id, ssn, dx) VALUES (?,?,?)", params=[2, "999-99-9999", "cold"], columnEncryptionSetting="Enabled").status_code == 200
    r = Q("SELECT id, ssn, dx FROM pat WHERE ssn = ?", params=["999-99-9999"], columnEncryptionSetting="Enabled").json()
    assert r["rows"] == [[2, "999-99-9999", "cold"]]
    assert Q("SELECT id FROM pat WHERE dx = ?", params=["cold"], columnEncryptionSetting="Enabled").status_code == 400
    _kvkey("PATCH", "/keys/cmk1", {"attributes": {"enabled": False}})
    r = Q("SELECT ssn FROM pat", columnEncryptionSetting="Enabled")
    assert r.status_code == 500 and "AZURE_KEY_VAULT" in r.json()["error"]["message"]
