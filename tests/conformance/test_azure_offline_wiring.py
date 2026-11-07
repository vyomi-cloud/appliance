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


# ───────────────────────────── Cosmos DB (dedicated gateway + CMK) with the real azure-cosmos SDK ─────────────────────────────
def _hdr_transport(extra):
    from tests.conformance._az_http_bridge import header_transport
    return header_transport(extra)


def test_cosmos_dedicated_gateway_cache_over_offline_wire(base):
    from azure.cosmos import CosmosClient
    _rg()
    acct = f"{RG}/providers/Microsoft.DocumentDB/databaseAccounts/owdgw"
    arm("PUT", acct, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard"}}, "2024-05-15")
    seen = {}
    hook = lambda hdrs, body=None: seen.update(hdrs=dict(hdrs))

    def client(dedicated=False, max_age=None):
        h = {"x-vyomi-account": "owdgw", **({"x-vyomi-endpoint": "dedicated"} if dedicated else {}),
             **({"x-ms-dedicatedgateway-max-age": str(max_age)} if max_age is not None else {})}
        return CosmosClient(base, credential="a2V5", transport=_hdr_transport(h), enable_endpoint_discovery=False)
    std = client()
    c = std.create_database("d").create_container("c", partition_key={"paths": ["/pk"], "kind": "Hash"})
    c.upsert_item({"id": "1", "pk": "a", "v": 1})
    with pytest.raises(Exception) as ei:                      # no gateway provisioned yet
        client(True).get_database_client("d").get_container_client("c").read_item("1", "a")
    assert "503" in str(ei.value) or "not available" in str(ei.value)
    arm("PUT", acct + "/services/SqlDedicatedGateway",
        {"properties": {"serviceType": "SqlDedicatedGateway", "instanceSize": "Cosmos.D4s", "instanceCount": 1}}, "2024-05-15")
    cc = client(True, 60000).get_database_client("d").get_container_client("c")
    cc.read_item("1", "a", response_hook=hook)
    assert seen["hdrs"].get("x-ms-cosmos-cachehit") == "False"
    cc.read_item("1", "a", response_hook=hook)
    assert seen["hdrs"].get("x-ms-cosmos-cachehit") == "True" and float(seen["hdrs"].get("x-ms-request-charge")) == 0.0
    sc = std.get_database_client("d").get_container_client("c")
    sc.upsert_item({"id": "1", "pk": "a", "v": 2})             # behind the gateway: cached read stays stale
    assert cc.read_item("1", "a", response_hook=hook)["v"] == 1
    sc.read_item("1", "a", response_hook=hook)
    assert "x-ms-cosmos-cachehit" not in seen["hdrs"]          # the standard endpoint is never cached
    bp = client(True, 0).get_database_client("d").get_container_client("c")
    assert bp.read_item("1", "a", response_hook=hook)["v"] == 2     # max-age 0 bypasses
    cc.upsert_item({"id": "1", "pk": "a", "v": 3})
    assert cc.read_item("1", "a", response_hook=hook)["v"] == 3     # write-through


def test_cosmos_cmk_encryption_over_offline_wire(base):
    from azure.core.exceptions import HttpResponseError
    from azure.cosmos import CosmosClient
    _rg()
    assert _kvkey("POST", "/keys/cmkc/create", {"kty": "RSA"}).status_code == 200
    arm("PUT", f"{RG}/providers/Microsoft.KeyVault/vaults/owkv", {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}}, "2023-07-01")
    key = "https://owkv.vault.azure.net/keys/cmkc"
    arm("PUT", f"{RG}/providers/Microsoft.DocumentDB/databaseAccounts/owcmk",
        {"location": "eastus", "identity": {"type": "SystemAssigned"},
         "properties": {"keyVaultKeyUri": key, "defaultIdentity": "SystemAssignedIdentity"}}, "2024-05-15")
    cl = CosmosClient(base, credential="a2V5", transport=_hdr_transport({"x-vyomi-account": "owcmk"}), enable_endpoint_discovery=False)
    c = cl.create_database("cd").create_container("cc", partition_key={"paths": ["/pk"], "kind": "Hash"})
    c.upsert_item({"id": "1", "pk": "a", "secret": "TOP-SECRET-VALUE"})
    assert c.read_item("1", "a")["secret"] == "TOP-SECRET-VALUE"
    from core import wire_ingress as _wi
    from core import app_context as ctx
    tok = ctx.REQUEST_PROVIDER.set("azure")          # the store is a durable slot of the Azure space
    try:
        docs = json.dumps(_wi.appliance_router().az_cosmos.docs, default=str)
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    assert "$cmk" in docs and "TOP-SECRET" not in docs     # only the CMK envelope is at rest
    _kvkey("PATCH", "/keys/cmkc", {"attributes": {"enabled": False}})
    with pytest.raises(HttpResponseError) as ei:
        c.read_item("1", "a")
    assert ei.value.status_code == 403
    _kvkey("PATCH", "/keys/cmkc", {"attributes": {"enabled": True}})
    assert c.read_item("1", "a")["secret"] == "TOP-SECRET-VALUE"


# ───────────────────────────── Storage Queue / Table service properties (native SDKs) ─────────────────────────────
def test_storage_queue_and_table_service_properties_over_offline_wire(base):
    import urllib.error
    import urllib.request
    from azure.core.credentials import AzureNamedKeyCredential
    from azure.data.tables import TableAnalyticsLogging, TableCorsRule, TableRetentionPolicy, TableServiceClient
    from azure.storage.queue import CorsRule, Metrics, QueueAnalyticsLogging, QueueServiceClient, RetentionPolicy
    _rg()
    sa = f"{RG}/providers/Microsoft.Storage/storageAccounts/owqacct"
    arm("PUT", sa, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01")
    cred = AzureNamedKeyCredential("owqacct", "a2V5")
    hdr = {"x-vyomi-service": "queue", "x-vyomi-account": "owqacct"}
    qs = QueueServiceClient(account_url=base + "/owqacct", credential=cred, headers=hdr, api_version="2021-08-06")
    props = qs.get_service_properties()
    assert not props["analytics_logging"].write and props["cors"] == []
    qs.set_service_properties(
        analytics_logging=QueueAnalyticsLogging(read=True, write=True, delete=False, retention_policy=RetentionPolicy(enabled=True, days=2)),
        hour_metrics=Metrics(enabled=True, include_apis=True, retention_policy=RetentionPolicy(enabled=True, days=3)),
        minute_metrics=Metrics(enabled=True, include_apis=False),
        cors=[CorsRule(allowed_origins=["https://app.example.com"], allowed_methods=["GET", "PUT"], allowed_headers=["x-ms-*"],
                       exposed_headers=["x-ms-request-id"], max_age_in_seconds=120)])
    p = qs.get_service_properties()
    assert p["analytics_logging"].read and p["analytics_logging"].retention_policy.days == 2 and p["hour_metrics"].include_apis
    assert p["cors"][0].max_age_in_seconds == 120

    def preflight(origin, method="PUT"):
        req = urllib.request.Request(base + "/owqacct/q1/messages", method="OPTIONS",
                                     headers={**hdr, "Origin": origin, "Access-Control-Request-Method": method, "x-ms-version": "2021-08-06"})
        try:
            r = urllib.request.urlopen(req)
            return r.status, {k.title(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            return e.code, {k.title(): v for k, v in e.headers.items()}
    st, h = preflight("https://app.example.com")
    assert st == 200 and h["Access-Control-Allow-Origin"] == "https://app.example.com" and h["Access-Control-Max-Age"] == "120"
    assert preflight("https://evil.example.com")[0] == 403
    assert preflight("https://app.example.com", "DELETE")[0] == 403
    qc = qs.get_queue_client("q1"); qc.create_queue(); qc.send_message("hello")
    vh = {**hdr, "x-ms-version": "2021-08-06"}
    logs = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/owqacct/?restype=service&comp=vyomi-logs", headers=vh)).read())["value"]
    assert any(e["operation"] == "write" for e in logs) and not any(e["operation"] == "delete" for e in logs)
    mets = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/owqacct/?restype=service&comp=vyomi-metrics", headers=vh)).read())["value"]
    assert any(m["interval"] == "hourMetrics" and m["api"] for m in mets) and not any(m["interval"] == "minuteMetrics" and m["api"] for m in mets)
    assert any(m["TotalRequests"] >= 2 for m in mets)
    # ARM queueServices CORS is shared with the data plane
    arm("PUT", sa + "/queueServices/default", {"properties": {"cors": {"corsRules": [{"allowedOrigins": ["https://arm.example.com"], "allowedMethods": ["GET"],
                                                                                       "maxAgeInSeconds": 5, "exposedHeaders": ["*"], "allowedHeaders": ["*"]}]}}}, "2023-01-01")
    assert preflight("https://arm.example.com", "GET")[0] == 200
    # Table service: same enforcement through the real azure-data-tables SDK
    ts = TableServiceClient(endpoint=base, credential=cred, headers={"x-vyomi-service": "table", "x-vyomi-account": "owqacct"})
    ts.set_service_properties(analytics_logging=TableAnalyticsLogging(read=True, write=True, delete=True, retention_policy=TableRetentionPolicy(enabled=True, days=1)),
                              cors=[TableCorsRule(allowed_origins=["https://t.example.com"], allowed_methods=["GET"], allowed_headers=["*"], exposed_headers=["*"], max_age_in_seconds=30)])
    tp = ts.get_service_properties()
    assert tp["analytics_logging"].delete and tp["cors"][0].max_age_in_seconds == 30
    ts.create_table("t1")
    tlogs = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/?restype=service&comp=vyomi-logs",
                                                                      headers={"x-vyomi-service": "table", "x-vyomi-account": "owqacct", "x-ms-version": "2021-08-06"})).read())["value"]
    assert any("Tables" in e["request"] for e in tlogs)


# ───────────────────────────── CMK for App Configuration + Service Bus ─────────────────────────────
def _cmk_vault(key):
    _rg()
    assert _kvkey("POST", f"/keys/{key}/create", {"kty": "RSA"}).status_code == 200
    arm("PUT", f"{RG}/providers/Microsoft.KeyVault/vaults/owkv2", {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}}, "2023-07-01")
    return f"https://owkv2.vault.azure.net/keys/{key}"


def test_appconfiguration_cmk_over_offline_wire(base):
    from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
    from azure.core.exceptions import HttpResponseError
    from providers import azure_services
    key = _cmk_vault("cmkac")
    sid = f"{RG}/providers/Microsoft.AppConfiguration/configurationStores/owcfg"
    arm("PUT", sid, {"location": "eastus", "sku": {"name": "Standard"}, "identity": {"type": "SystemAssigned"},
                     "properties": {"encryption": {"keyVaultProperties": {"keyIdentifier": key}}}}, "2024-05-01")
    ac = AzureAppConfigurationClient.from_connection_string(f"Endpoint={base}/azure-data/appconfig/owcfg;Id=cred;Secret=c2VjcmV0")
    ac.set_configuration_setting(ConfigurationSetting(key="db", value="PRIVATE-CONN-STRING"))
    assert ac.get_configuration_setting("db").value == "PRIVATE-CONN-STRING"
    from core import app_context as ctx
    tok = ctx.REQUEST_PROVIDER.set("azure")
    try:
        rec = azure_services._state[sid.lower()]
        rec = json.loads(json.dumps(rec, default=str))
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    assert "_kv" not in rec and "_kv_sealed" in rec and "PRIVATE-CONN-STRING" not in json.dumps(rec, default=str)   # sealed at rest
    _kvkey("PATCH", "/keys/cmkac", {"attributes": {"enabled": False}})
    with pytest.raises(HttpResponseError) as ei:
        ac.get_configuration_setting("db")
    assert ei.value.status_code == 403
    _kvkey("PATCH", "/keys/cmkac", {"attributes": {"enabled": True}})
    assert ac.get_configuration_setting("db").value == "PRIVATE-CONN-STRING"


def test_servicebus_namespace_cmk_over_offline_wire():
    key = _cmk_vault("cmksb")
    nid = f"{RG}/providers/Microsoft.ServiceBus/namespaces/owns"
    arm("PUT", nid, {"location": "eastus", "sku": {"name": "Premium"}, "identity": {"type": "SystemAssigned"},
                     "properties": {"encryption": {"keySource": "Microsoft.KeyVault",
                                                   "keyVaultProperties": [{"keyName": "cmksb", "keyVaultUri": "https://owkv2.vault.azure.net"}]}}}, "2022-10-01-preview")
    H = {"x-vyomi-namespace": "owns", "content-type": "application/atom+xml"}
    assert C.put("/owq1", headers=H, content=b"<entry xmlns='http://www.w3.org/2005/Atom'><content type='application/xml'><QueueDescription xmlns='http://schemas.microsoft.com/netservices/2010/10/servicebus/connect'/></content></entry>").status_code in (200, 201)
    assert C.post("/owq1/messages", headers={"x-vyomi-namespace": "owns", "content-type": "text/plain"}, content=b"top-secret-payload").status_code in (200, 201)
    from core import wire_ingress as _wi
    from core import app_context as ctx
    tok = ctx.REQUEST_PROVIDER.set("azure")
    try:
        sealed = json.dumps(getattr(_wi.appliance_router().az_sb, "_sb_sealed", {}), default=str)
        raw = [m for t in _wi.appliance_router().az_sb.topics.values() for m in t["messages"]]
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    assert sealed and "top-secret-payload" not in sealed and all(m["body"] == b"" for m in raw)      # sealed at rest
    _kvkey("PATCH", "/keys/cmksb", {"attributes": {"enabled": False}})
    r = C.get("/owq1/messages", headers={"x-vyomi-namespace": "owns"})
    assert r.status_code == 403 and "key is disabled" in r.text
    _kvkey("PATCH", "/keys/cmksb", {"attributes": {"enabled": True}})
    r = C.get("/owq1/messages", headers={"x-vyomi-namespace": "owns"})
    assert r.status_code == 200 and b"top-secret-payload" in r.content
