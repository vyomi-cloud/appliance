"""Azure reference app lane 7: Key Vault through the REAL, unmodified azure-keyvault-keys / -secrets / -certificates and azure-mgmt-keyvault.
The vault URL the SDK needs for CryptographyClient(key.id) / KeyClient.get_cryptography_client() is host-only (the SDK drops any path), so the
client points at the simulator's https endpoint WITHOUT a path; the simulator resolves the vault from the key/secret name (or the only vault).
Run: PYTHONPATH=. python tests/conformance/test_azure_ref_vault_sdk.py"""
import os, sys, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
PASS, FAIL = [], []


def step(name, fn):
    try:
        out = fn()
        PASS.append(name); print("PASS", name, "" if out is None else str(out)[:90])
    except Exception as e:  # noqa: BLE001
        FAIL.append(name); print("FAIL", name, type(e).__name__, str(e)[:300])


def main():
    try:
        import azure.keyvault.keys, azure.mgmt.keyvault  # noqa: F401
    except ImportError as e:
        print("SKIP azure key vault SDKs missing:", e); return 0
    from tests.conformance._az_tls_server import start
    tls, http, ca = start()
    from azure.core.credentials import AccessToken

    class Cred:
        def get_token(self, *a, **k): return AccessToken("t", int(time.time()) + 3600)
    SUB = "00000000-0000-0000-0000-cloudlearn01"
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.keyvault import KeyVaultManagementClient
    ResourceManagementClient(Cred(), SUB, base_url=tls).resource_groups.create_or_update("rg", {"location": "eastus"})
    kvm = KeyVaultManagementClient(Cred(), SUB, base_url=tls, polling_interval=0)
    props = {"tenant_id": "00000000-0000-0000-0000-000000000000", "sku": {"family": "A", "name": "standard"}, "access_policies": []}
    S = {}

    def mk_vault():
        v = kvm.vaults.begin_create_or_update("rg", "facilities-kv", {"location": "eastus", "properties": props}).result()
        assert v.name == "facilities-kv" and v.properties.vault_uri
        S["uri"] = v.properties.vault_uri
        return v.properties.vault_uri
    step("arm: vault create (azure-mgmt-keyvault)", mk_vault)
    step("arm: vault get / list_by_resource_group / list", lambda: (kvm.vaults.get("rg", "facilities-kv").name == "facilities-kv"
         and [v.name for v in kvm.vaults.list_by_resource_group("rg")] == ["facilities-kv"] and any(v.name == "facilities-kv" for v in kvm.vaults.list())) or (_ for _ in ()).throw(AssertionError("list")))
    step("arm: vault update access policies", lambda: kvm.vaults.update_access_policy("rg", "facilities-kv", "add", {"properties": {"access_policies": [
        {"tenant_id": props["tenant_id"], "object_id": "11111111-1111-1111-1111-111111111111", "permissions": {"keys": ["get", "wrapKey", "unwrapKey"], "secrets": ["get"]}}]}}).properties.access_policies)
    step("arm: second vault + rbac flag", lambda: kvm.vaults.begin_create_or_update("rg", "other-kv", {"location": "eastus", "properties": {**props, "enable_rbac_authorization": True}}).result().properties.enable_rbac_authorization)

    from azure.keyvault.keys import KeyClient, KeyType, KeyCurveName, KeyRotationLifetimeAction, KeyRotationPolicyAction
    from azure.keyvault.keys.crypto import CryptographyClient, KeyWrapAlgorithm, EncryptionAlgorithm, SignatureAlgorithm
    kc = KeyClient(tls, Cred(), verify_challenge_resource=False)    # host-only vault URL (see module doc)

    def key():
        S["k"] = kc.create_rsa_key("ledger-key", size=2048)
        assert S["k"].key.kty.startswith("RSA") and S["k"].properties.version and S["k"].id.endswith(S["k"].properties.version)
    step("keys: create_rsa_key", key)
    step("keys: create_ec_key", lambda: kc.create_ec_key("ec-key", curve=KeyCurveName.p_256).key.kty)
    step("keys: get_key / list_properties_of_keys / versions", lambda: (kc.get_key("ledger-key").id == S["k"].id
         and "ledger-key" in [k.name for k in kc.list_properties_of_keys()] and len(list(kc.list_properties_of_key_versions("ledger-key"))) == 1) or (_ for _ in ()).throw(AssertionError("get/list")))

    def envelope():
        cc = CryptographyClient(S["k"].id, Cred(), verify_challenge_resource=False)
        for alg in (KeyWrapAlgorithm.rsa_oaep, KeyWrapAlgorithm.rsa_oaep_256):
            w = cc.wrap_key(alg, os.urandom(32)); dek = os.urandom(32)
            w = cc.wrap_key(alg, dek)
            assert w.encrypted_key != dek and cc.unwrap_key(alg, w.encrypted_key).key == dek, alg
        return "rsa-oaep + rsa-oaep-256"
    step("crypto: CryptographyClient(key.id) wrap_key/unwrap_key", envelope)
    step("crypto: KeyClient.get_cryptography_client wrap/unwrap", lambda: (lambda cc: cc.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, cc.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, b"k" * 32).encrypted_key).key == b"k" * 32)(kc.get_cryptography_client("ledger-key", verify_challenge_resource=False)) or (_ for _ in ()).throw(AssertionError("rt")))
    step("crypto: encrypt/decrypt rsa-oaep-256 (CryptographyClient(key.id))", lambda: (lambda cc: cc.decrypt(EncryptionAlgorithm.rsa_oaep_256, cc.encrypt(EncryptionAlgorithm.rsa_oaep_256, b"hello").ciphertext).plaintext == b"hello")(CryptographyClient(S["k"].id, Cred(), verify_challenge_resource=False)) or (_ for _ in ()).throw(AssertionError("rt")))
    step("crypto: remote decrypt of a locally-encrypted blob (decrypt is the service call)", lambda: (lambda cc, kcc: cc.decrypt(EncryptionAlgorithm.rsa_oaep, kcc.encrypt(EncryptionAlgorithm.rsa_oaep, b"x" * 20).ciphertext).plaintext == b"x" * 20)(
        CryptographyClient(S["k"].id, Cred(), verify_challenge_resource=False), CryptographyClient(kc.get_key("ledger-key"), Cred(), verify_challenge_resource=False)) or (_ for _ in ()).throw(AssertionError("rt")))

    def sign():
        import hashlib
        cc = CryptographyClient(S["k"].id, Cred(), verify_challenge_resource=False)
        for alg in (SignatureAlgorithm.rs256, SignatureAlgorithm.ps256):
            d = hashlib.sha256(b"approval").digest()
            sg = cc.sign(alg, d)
            assert cc.verify(alg, d, sg.signature).is_valid, alg
            assert not cc.verify(alg, hashlib.sha256(b"tampered").digest(), sg.signature).is_valid, alg
        e = CryptographyClient(kc.get_key("ec-key").id, Cred(), verify_challenge_resource=False)
        d = hashlib.sha256(b"x").digest(); sg = e.sign(SignatureAlgorithm.es256, d)
        assert e.verify(SignatureAlgorithm.es256, d, sg.signature).is_valid
    step("crypto: sign/verify rs256 ps256 es256", sign)

    def rotate():
        n = kc.rotate_key("ledger-key")
        assert n.properties.version != S["k"].properties.version
        assert len(list(kc.list_properties_of_key_versions("ledger-key"))) == 2
        return "2 versions"
    step("keys: rotate_key + versions", rotate)

    def aes():
        k = kc.create_oct_key("dek-key", size=256, hardware_protected=True)
        assert "oct" in str(k.key.kty).lower(), repr(k.key.kty)
        cc = CryptographyClient(k.id, Cred(), verify_challenge_resource=False)
        e = cc.encrypt(EncryptionAlgorithm.a256_gcm, b"ledger", additional_authenticated_data=b"aad")
        assert e.iv and e.tag and cc.decrypt(EncryptionAlgorithm.a256_gcm, e.ciphertext, iv=e.iv, authentication_tag=e.tag, additional_authenticated_data=b"aad").plaintext == b"ledger"
        w = cc.wrap_key(KeyWrapAlgorithm.aes_256, os.urandom(32))
        assert cc.unwrap_key(KeyWrapAlgorithm.aes_256, w.encrypted_key)
        return "A256GCM + A256KW"
    step("crypto: oct-HSM AES-GCM encrypt/decrypt and AES-KW wrap/unwrap", aes)

    def policy():
        p = kc.get_key_rotation_policy("ledger-key")
        from azure.keyvault.keys import KeyRotationPolicy
        p = kc.update_key_rotation_policy("ledger-key", KeyRotationPolicy(), lifetime_actions=[KeyRotationLifetimeAction(KeyRotationPolicyAction.rotate, time_after_create="P90D")], expires_in="P180D")
        assert kc.get_key_rotation_policy("ledger-key").expires_in == "P180D"
    step("keys: rotation policy get/update", policy)

    def backup():
        b = kc.backup_key("ec-key")
        kc.begin_delete_key("ec-key").wait(); kc.purge_deleted_key("ec-key")
        assert kc.restore_key_backup(b).name == "ec-key"
    step("keys: backup / delete / purge / restore", backup)

    def softdel():
        kc.create_rsa_key("tmp-key"); kc.begin_delete_key("tmp-key").wait()
        assert "tmp-key" in [k.name for k in kc.list_deleted_keys()]
        kc.begin_recover_deleted_key("tmp-key").wait(); assert kc.get_key("tmp-key").name == "tmp-key"
        kc.begin_delete_key("tmp-key").wait(); kc.purge_deleted_key("tmp-key")
    step("keys: soft delete / list deleted / recover / purge", softdel)
    step("keys: update_key_properties disable -> crypto 403", lambda: _disable(kc, CryptographyClient, Cred, EncryptionAlgorithm))
    step("keys: key in other-kv is isolated", lambda: _isolated(tls, Cred, kc))

    from azure.keyvault.secrets import SecretClient
    sc = SecretClient(tls, Cred(), verify_challenge_resource=False)

    def secrets():
        sc.set_secret("db-pass", "v1"); sc.set_secret("db-pass", "v2")
        assert sc.get_secret("db-pass").value == "v2" and len(list(sc.list_properties_of_secret_versions("db-pass"))) == 2
        assert "db-pass" in [s.name for s in sc.list_properties_of_secrets()]
        sc.begin_delete_secret("db-pass").wait(); sc.purge_deleted_secret("db-pass")
    step("secrets: set/get/versions/list/delete/purge", secrets)

    from azure.keyvault.certificates import CertificateClient, CertificatePolicy
    def certs():
        cl = CertificateClient(tls, Cred(), verify_challenge_resource=False)
        cl.begin_create_certificate("app-cert", CertificatePolicy.get_default()).result()
        assert cl.get_certificate("app-cert").name == "app-cert" and "app-cert" in [c.name for c in cl.list_properties_of_certificates()]
    step("certificates: create (self-signed) / get / list", certs)

    def activity():
        from azure.mgmt.monitor import MonitorManagementClient
        evs = list(MonitorManagementClient(Cred(), SUB, base_url=tls).activity_logs.list(filter=f"eventTimestamp ge '{time.strftime('%Y-%m-%dT00:00:00Z', time.gmtime(time.time() - 86400))}'"))
        names = {e.operation_name.value for e in evs if e.operation_name}
        assert "Microsoft.KeyVault/vaults/write" in names, sorted(names)[:10]
    step("activity log: vault write present", activity)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


def _disable(kc, CC, Cred, EA):
    from azure.core.exceptions import HttpResponseError
    kc.update_key_properties("ledger-key", enabled=False)
    try:
        CC(kc.get_key("ledger-key").id, Cred(), verify_challenge_resource=False).decrypt(EA.rsa_oaep_256, b"\0" * 256)
        raise AssertionError("expected failure")
    except HttpResponseError as e:
        assert e.status_code in (400, 403), e.status_code
    finally:
        kc.update_key_properties("ledger-key", enabled=True)


def _isolated(tls, Cred, kc):
    # keys live in the vault their path names; the host-only client resolves facilities-kv (holds the name), never other-kv
    from azure.keyvault.keys import KeyClient
    ok = KeyClient(tls.rstrip("/") + "/azure-data/keyvault/other-kv", Cred(), verify_challenge_resource=False)
    ok.create_rsa_key("only-in-other")
    assert "only-in-other" in [k.name for k in ok.list_properties_of_keys()]
    assert "only-in-other" not in [k.name for k in KeyClient(tls.rstrip("/") + "/azure-data/keyvault/facilities-kv", Cred(), verify_challenge_resource=False).list_properties_of_keys()]


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush(); os._exit(rc)
