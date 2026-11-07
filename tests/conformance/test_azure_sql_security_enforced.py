"""Azure SQL security features are ENFORCED against the real engine: Data Discovery (name + data scan, audit sensitivity),
Dynamic Data Masking (non-privileged logins), Ledger (append-only, hash chain, digest, verify, tamper detection),
Always Encrypted (ciphertext at rest, deterministic equality, CMK disable blocks decryption).
Run: PYTHONPATH=. python tests/conformance/test_azure_sql_security_enforced.py"""
import json
from core import azure_sql_core as sql, azure_keyvault_keys_core as kvk, azure_cmk_core as cmk
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from core.kms_keystore import InMemoryKeyStore
from core.sql_store import SqlStore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    kv = InMemoryKeyStore()
    cmk.bind(kv)
    kvk.dispatch(kv, "POST", "/keys/cmk1/create", {}, {}, json.dumps({"kty": "RSA"}).encode())
    a = AzureArm(); av = {"api-version": "2023-08-01"}
    a.handle("PUT", f"/subscriptions/{S}/resourceGroups/r", {"api-version": "2021-04-01"}, {"location": "eastus"})
    srv = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Sql/servers/sx"
    a.handle("PUT", srv, av, {"location": "eastus", "properties": {"administratorLogin": "adm", "administratorLoginPassword": "Xx123456789!"}})
    db = srv + "/databases/d1"
    a.handle("PUT", db, av, {"location": "eastus", "properties": {}})
    ledb = srv + "/databases/led"
    a.handle("PUT", ledb, av, {"location": "eastus", "properties": {"isLedgerOn": True}})
    st = SqlStore()
    D = lambda m, p, b=None, h=None: sql.dispatch(st, m, p, {}, h or {}, json.dumps(b).encode() if b is not None else b"", arm_state=a.state, kv_store=kv)
    Q = lambda s, p=None, h=None, db="d1", **kw: D("POST", f"/servers/sx/databases/{db}/query", {"sql": s, "params": p, **kw}, h)
    J = lambda r: json.loads(r.body)
    D("PUT", "/servers/sx"); D("PUT", "/servers/sx/databases/d1"); D("PUT", "/servers/sx/databases/led")

    # ── masking + discovery ──
    Q("CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT, ssn TEXT, salary INTEGER, note TEXT)")
    Q("INSERT INTO people VALUES (1,'alice@example.com','123-45-6789',90000,'hello')")
    a.handle("PUT", f"{db}/dataMaskingPolicies/Default", av, {"properties": {"dataMaskingState": "Enabled", "exemptPrincipals": "boss"}})
    for n, props in {"r1": {"columnName": "email", "maskingFunction": "Email"}, "r2": {"columnName": "ssn", "maskingFunction": "SSN"},
                     "r3": {"columnName": "salary", "maskingFunction": "Default"}, "r4": {"columnName": "note", "maskingFunction": "Text", "prefixSize": 1, "suffixSize": 1, "replacementString": "***"}}.items():
        a.handle("PUT", f"{db}/dataMaskingPolicies/Default/rules/{n}", av, {"properties": {"schemaName": "dbo", "tableName": "people", **props}})
    admin = J(Q("SELECT email, ssn, salary, note FROM people"))["rows"][0]
    _check("admin sees real data", admin == ["alice@example.com", "123-45-6789", 90000, "hello"])
    m = J(Q("SELECT email, ssn, salary, note FROM people", h={"x-vyomi-sql-login": "bob"}))["rows"][0]
    _check("non-privileged login gets masked values", m == ["aXXX@XXXX.com", "XXX-XX-6789", 0, "h***o"])
    m = J(Q("SELECT p.email AS e, * FROM people p", h={"x-vyomi-sql-login": "bob"}))["rows"][0]
    _check("alias + star expansion masked", m[0] == "aXXX@XXXX.com" and m[2] == "aXXX@XXXX.com")
    _check("exempt principal sees real data", J(Q("SELECT email FROM people", h={"x-vyomi-sql-login": "boss"}))["rows"][0][0] == "alice@example.com")
    r = Q("GRANT UNMASK TO bob")
    _check("GRANT UNMASK by admin ok", r.status == 200)
    _check("UNMASK permission reveals data", J(Q("SELECT email FROM people", h={"x-vyomi-sql-login": "bob"}))["rows"][0][0] == "alice@example.com")
    _check("non-admin cannot GRANT", Q("GRANT UNMASK TO eve", h={"x-vyomi-sql-login": "bob"}).status == 403)
    Q("REVOKE UNMASK FROM bob")
    _check("REVOKE restores masking", J(Q("SELECT email FROM people", h={"x-vyomi-sql-login": "bob"}))["rows"][0][0] == "aXXX@XXXX.com")
    Q("INSERT INTO people VALUES (2,'bob@example.org','987-65-4321',50000,'x')")
    _check("stored data is not altered by masking", J(Q("SELECT email FROM people WHERE id=1"))["rows"][0][0] == "alice@example.com")
    d = J(D("GET", "/servers/sx/databases/d1/security/discovery"))
    byc = {c["column"]: c for c in d["columns"]}
    _check("discovery: data scan finds email + SSN from real values", byc["email"]["recommendation"]["source"] == "data" and byc["ssn"]["recommendation"]["informationType"] == "National ID")
    _check("discovery: name pattern finds salary", byc["salary"]["recommendation"]["source"] == "name")
    a.handle("PUT", f"{db}/schemas/dbo/tables/people/columns/email/sensitivityLabels/current", {"api-version": "2020-11-01-preview"},
             {"properties": {"labelName": "Confidential", "informationType": "Contact Info", "rank": "Medium"}})
    Q("SELECT email, note FROM people")
    ins = J(D("GET", "/servers/sx/databases/d1/queryinsights"))
    aud = [x for x in ins["audit"] if x.get("dataSensitivityInformation")]
    _check("audit records data sensitivity information for a classified read", aud and aud[0]["dataSensitivityInformation"][0]["columnName"] == "email")

    # ── ledger ──
    Q("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT) WITH (LEDGER = ON (APPEND_ONLY = ON))", db="d1")
    _check("append-only: insert ok", Q("INSERT INTO t VALUES (1,'a')").status == 200)
    r = Q("UPDATE t SET v='z' WHERE id=1")
    _check("append-only: update rejected", r.status == 400 and "37359" in J(r)["error"]["message"])
    _check("append-only: delete rejected", Q("DELETE FROM t WHERE id=1").status == 400)
    _check("reserved ledger tables not writable", Q("DELETE FROM __vyomi_ledger_blocks").status == 403)
    Q("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT)", db="led")     # isLedgerOn database -> updatable ledger table
    Q("INSERT INTO u VALUES (1,'a')", db="led"); Q("UPDATE u SET v='b' WHERE id=1", db="led")
    h = J(D("GET", "/servers/sx/databases/led/security/ledger/history?table=u"))["value"] if False else None
    hist = sql._sec.ledger_history(st, "azuresql:sx/led", "u")
    _check("updatable ledger: UPDATE recorded as DELETE+INSERT history", [x["operation"] for x in hist] == ["INSERT", "DELETE", "INSERT"])
    dg = J(D("POST", "/servers/sx/databases/led/security/ledger/digest"))
    _check("digest generated", dg["hash"].startswith("0x") and dg["block_id"] >= 1)
    v = J(D("POST", "/servers/sx/databases/led/security/ledger/verify"))
    _check("verify succeeds on untampered ledger", v["ok"] and v["digestsVerified"] == 1)
    st.execute_sql("azuresql:sx/led", "UPDATE u SET v='HACKED' WHERE id=1")     # DBA bypassing the ledger path
    v = J(D("POST", "/servers/sx/databases/led/security/ledger/verify"))
    _check("verify detects out-of-band row tampering", not v["ok"] and "outside the ledger" in v["issues"][0])
    st.execute_sql("azuresql:sx/led", "UPDATE u SET v='b' WHERE id=1")
    st.execute_sql("azuresql:sx/led", "UPDATE __vyomi_ledger_blocks SET op='X' WHERE block_id=1")
    v = J(D("POST", "/servers/sx/databases/led/security/ledger/verify"))
    _check("verify detects an altered block / digest mismatch", not v["ok"] and any("altered" in i or "Digest" in i for i in v["issues"]))

    # ── Always Encrypted ──
    Q("CREATE TABLE pat (id INTEGER PRIMARY KEY, ssn TEXT, dx TEXT)")
    Q("INSERT INTO pat VALUES (1,'111-22-3333','flu')")
    _check("create CMK from Key Vault key", D("PUT", "/servers/sx/databases/d1/security/ae/cmk/cmk_a", {"keyPath": "https://kv1.vault.azure.net/keys/cmk1"}).status == 200)
    _check("CMK on missing key rejected", D("PUT", "/servers/sx/databases/d1/security/ae/cmk/bad", {"keyPath": "https://kv1.vault.azure.net/keys/nope"}).status == 400)
    _check("create CEK wrapped by CMK", D("PUT", "/servers/sx/databases/d1/security/ae/cek/cek_a", {"cmk": "cmk_a"}).status == 200)
    r = J(D("POST", "/servers/sx/databases/d1/security/ae/encrypt", {"table": "pat", "column": "ssn", "cek": "cek_a", "encryptionType": "Deterministic"}))
    _check("existing rows encrypted in place", r["rowsEncrypted"] == 1)
    D("POST", "/servers/sx/databases/d1/security/ae/encrypt", {"table": "pat", "column": "dx", "cek": "cek_a", "encryptionType": "Randomized"})
    raw = st.execute_sql("azuresql:sx/d1", "SELECT ssn, dx FROM pat")["rows"][0]
    _check("ciphertext at rest, not plaintext", raw[0].startswith("0x01") and "111-22-3333" not in raw[0] and "flu" not in raw[1])
    _check("without driver setting the server returns ciphertext", J(Q("SELECT ssn FROM pat"))["rows"][0][0].startswith("0x01"))
    _check("plaintext param without column encryption rejected", Q("INSERT INTO pat VALUES (?,?,?)", [2, "999-99-9999", "cold"]).status == 400)
    _check("literal into encrypted column rejected", Q("INSERT INTO pat (id, ssn, dx) VALUES (3,'1','2')", columnEncryptionSetting="Enabled").status == 400)
    r = Q("INSERT INTO pat (id, ssn, dx) VALUES (?,?,?)", [2, "999-99-9999", "cold"], columnEncryptionSetting="Enabled")
    _check("driver-encrypted insert ok", r.status == 200)
    r = J(Q("SELECT id, ssn, dx FROM pat WHERE ssn = ?", ["999-99-9999"], columnEncryptionSetting="Enabled"))
    _check("deterministic equality + client-side decrypt", r["rows"] == [[2, "999-99-9999", "cold"]])
    _check("randomized equality rejected", Q("SELECT id FROM pat WHERE dx = ?", ["cold"], columnEncryptionSetting="Enabled").status == 400)
    _check("range/LIKE on encrypted column rejected", Q("SELECT id FROM pat WHERE ssn > ?", ["1"], columnEncryptionSetting="Enabled").status == 400)
    kvk.dispatch(kv, "PATCH", "/keys/cmk1", {}, {}, json.dumps({"attributes": {"enabled": False}}).encode())
    r = Q("SELECT ssn FROM pat", columnEncryptionSetting="Enabled")
    _check("CMK disabled -> driver cannot decrypt", r.status == 500 and "AZURE_KEY_VAULT" in J(r)["error"]["message"])
    print("PASS test_azure_sql_security_enforced")


if __name__ == "__main__":
    run()
