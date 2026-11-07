"""Customer-managed-key encryption is ENFORCED (not config-only) for App Configuration, Cosmos DB and Service Bus:
data is envelope-encrypted at rest with a DEK wrapped by the account's Key Vault key; disabling / deleting the key makes
the data unreadable (403), re-enabling restores it, rotation re-wraps the DEK.
Run: PYTHONPATH=. python tests/conformance/test_azure_cmk_enforced.py"""
import json
from core import azure_cfgext_core as cfg, azure_keyvault_keys_core as kvk, azure_cmk_core as cmk
from core import azure_appconfiguration_core as ac, azure_cosmos_core as cosmos, azure_servicebus_core as sb
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core.kms_keystore import InMemoryKeyStore
from core.messaging_store import MessagingStore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _kv(store, method, path, body=None):
    r = kvk.dispatch(store, method, path, {}, {}, json.dumps(body or {}).encode())
    return r.status, (json.loads(r.body) if r.body else {})


def run():
    kv = InMemoryKeyStore()
    cfg.bind_key_store(kv)
    cmk.bind(kv)
    _kv(kv, "POST", "/keys/cmk1/create", {"kty": "RSA"})
    a = AzureArm()
    RG = f"/subscriptions/{SUB}/resourceGroups/k-rg"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", RG + "/providers/Microsoft.KeyVault/vaults/kv1", {"api-version": "2023-07-01"},
             {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}})
    KEY = "https://kv1.vault.azure.net/keys/cmk1"
    ident = {"type": "SystemAssigned"}

    # ── App Configuration ──
    sid = RG + "/providers/Microsoft.AppConfiguration/configurationStores/cfg1"
    r = a.handle("PUT", sid, {"api-version": "2024-05-01"}, {"location": "eastus", "sku": {"name": "Standard"}, "identity": ident,
                 "properties": {"encryption": {"keyVaultProperties": {"keyIdentifier": KEY}}}})
    _check("appconfig: store with CMK created", r["status"] in (200, 201))
    st = a.state[sid.lower()]
    put = lambda k, v: ac.data_dispatch(a.state, "cfg1", "PUT", f"/kv/{k}", {}, {}, json.dumps({"value": v}))
    get = lambda k: ac.data_dispatch(a.state, "cfg1", "GET", f"/kv/{k}", {}, {})
    _check("appconfig: write ok", put("db", "SECRET-CONN-STRING")["status"] in (200, 201))
    _check("appconfig: read back plaintext through the data plane", get("db")["body"]["value"] == "SECRET-CONN-STRING")
    _check("appconfig: at rest the ARM record holds NO plaintext key-values", "_kv" not in st and "_kv_sealed" in st
           and "SECRET-CONN-STRING" not in json.dumps(st, default=str))
    _kv(kv, "PATCH", "/keys/cmk1", {"attributes": {"enabled": False}})
    r = get("db")
    _check("appconfig: key disabled -> data plane 403", r["status"] == 403 and "inaccessible" in json.dumps(r["body"]).lower())
    _check("appconfig: data still ciphertext while blocked", "_kv" not in st and "SECRET-CONN-STRING" not in json.dumps(st, default=str))
    _kv(kv, "PATCH", "/keys/cmk1", {"attributes": {"enabled": True}})
    _check("appconfig: key re-enabled -> readable again", get("db")["body"]["value"] == "SECRET-CONN-STRING")
    kid1 = st["_kv_sealed"]["keyVersion"]
    _kv(kv, "POST", "/keys/cmk1/create", {"kty": "RSA"})        # rotation: new key version
    _check("appconfig: rotation re-wraps the DEK under the new version on next touch", get("db")["status"] == 200
           and st["_kv_sealed"]["keyVersion"] != kid1)
    _kv(kv, "DELETE", "/keys/cmk1")
    _check("appconfig: key deleted -> data plane 403", get("db")["status"] == 403)
    _kv(kv, "POST", "/deletedkeys/cmk1/recover")
    _check("appconfig: key recovered -> data readable again", get("db")["status"] == 200)

    # ── Cosmos DB ──
    cid = RG + "/providers/Microsoft.DocumentDB/databaseAccounts/cos1"
    r = a.handle("PUT", cid, {"api-version": "2024-05-15"}, {"location": "eastus", "identity": ident,
                 "properties": {"keyVaultKeyUri": KEY, "defaultIdentity": "SystemAssignedIdentity"}})
    _check("cosmos: account with CMK created", r["status"] in (200, 201))
    cs = cosmos.CosmosStore()
    H = {"x-vyomi-account": "cos1"}
    d = lambda m, p, b=None, h=None: cosmos.dispatch(cs, m, p, {}, {**H, **(h or {})}, json.dumps(b or {}).encode(), arm_state=a.state, kv_store=kv)
    d("POST", "/dbs", {"id": "db1"})
    d("POST", "/dbs/db1/colls", {"id": "c1", "partitionKey": {"paths": ["/pk"], "kind": "Hash"}})
    r = d("POST", "/dbs/db1/colls/c1/docs", {"id": "d1", "pk": "a", "ssn": "123-45-6789"}, {"x-ms-documentdb-partitionkey": '["a"]'})
    _check("cosmos: write ok", r.status in (200, 201))
    _check("cosmos: at rest the store holds only the CMK envelope, no plaintext", list(cs.docs) == ["$cmk"] and "123-45-6789" not in json.dumps(cs.docs))
    r = d("GET", "/dbs/db1/colls/c1/docs/d1", None, {"x-ms-documentdb-partitionkey": '["a"]'})
    _check("cosmos: read returns plaintext", r.status == 200 and b"123-45-6789" in r.body)
    _kv(kv, "PATCH", "/keys/cmk1", {"attributes": {"enabled": False}})
    r = d("GET", "/dbs/db1/colls/c1/docs/d1", None, {"x-ms-documentdb-partitionkey": '["a"]'})
    _check("cosmos: key disabled -> 403 substatus 4000", r.status == 403 and r.headers.get("x-ms-substatus") == "4000")
    _check("cosmos: still ciphertext while blocked", list(cs.docs) == ["$cmk"])
    _kv(kv, "PATCH", "/keys/cmk1", {"attributes": {"enabled": True}})
    r = d("GET", "/dbs/db1/colls/c1/docs/d1", None, {"x-ms-documentdb-partitionkey": '["a"]'})
    _check("cosmos: re-enabled -> readable", r.status == 200 and b"123-45-6789" in r.body)
    env = cs.docs["$cmk"]
    cosmos.rotate_cmk(cs, a.state[cid.lower()], kv)
    _check("cosmos: rotate re-wraps DEK only (ciphertext unchanged)", cs.docs["$cmk"]["ct"] == env["ct"] and cs.docs["$cmk"]["wrappedDek"] != env["wrappedDek"])

    # ── Service Bus ──
    nid = RG + "/providers/Microsoft.ServiceBus/namespaces/ns1"
    r = a.handle("PUT", nid, {"api-version": "2022-10-01-preview"}, {"location": "eastus", "sku": {"name": "Premium"}, "identity": ident,
                 "properties": {"encryption": {"keySource": "Microsoft.KeyVault", "keyVaultProperties": [{"keyName": "cmk1", "keyVaultUri": "https://kv1.vault.azure.net"}]}}})
    _check("servicebus: premium namespace with CMK created", r["status"] in (200, 201))
    ns = cmk_ns = sb.cmk_namespace(a.state, {"x-vyomi-namespace": "ns1"})
    _check("servicebus: namespace resolved with a key", ns is not None and sb.cmk_key_uri(ns).endswith("/keys/cmk1"))
    ms = MessagingStore()

    def sbcall(m, p, body=b"", h=None):
        with sb.CmkScope(ms, ns, kv):
            return sb.dispatch(ms, m, p, {}, h or {}, body)
    sbcall("PUT", "/q1")
    sbcall("POST", "/q1/messages", b"top-secret-payload", {"content-type": "text/plain"})
    stored = [m for t in ms.topics.values() for m in t["messages"]]
    _check("servicebus: at rest the message body is not plaintext", all(m["body"] == b"" for m in stored) and ms._sb_sealed
           and "top-secret-payload" not in json.dumps(ms._sb_sealed))
    _kv(kv, "PATCH", "/keys/cmk1", {"attributes": {"enabled": False}})
    try:
        sbcall("GET", "/q1/messages")
        raise AssertionError("expected inaccessible")
    except sb.ServiceBusError as e:
        _check("servicebus: key disabled -> 403 MessagingGatewayKeyInaccessible", e.status == 403 and e.code == "MessagingGatewayKeyInaccessible")
    _kv(kv, "PATCH", "/keys/cmk1", {"attributes": {"enabled": True}})
    r = sbcall("GET", "/q1/messages")
    _check("servicebus: re-enabled -> message readable", b"top-secret-payload" in r.body)
    print("PASS test_azure_cmk_enforced")


if __name__ == "__main__":
    run()
