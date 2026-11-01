"""GCP Cloud KMS core conformance — the GCP analogue of test_kms_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Cloud KMS REST API v1** wire semantics (keyRing / cryptoKey
resources, base64 plaintext/ciphertext, `:encrypt` / `:decrypt` custom methods,
Google `{"error":{...,"status"}}` shape), proving google-cloud-kms / gcloud kms can
drive the core unchanged. The envelope crypto is the SAME reused KeyStore/KmsEngine
seam as AWS KMS, so encrypt/decrypt round-trip with real authenticated crypto.

Run on host:    python3 tests/conformance/test_gcp_kms_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json

try:
    from core.kms_keystore import InMemoryKeyStore
    from core import gcp_kms_core as gkms
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import gcp_kms_core as gkms  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = InMemoryKeyStore()
    LOC = "/v1/projects/demo/locations/global"
    RING = f"{LOC}/keyRings/app-ring"
    KEY = f"{RING}/cryptoKeys/app-key"
    ring_name = "projects/demo/locations/global/keyRings/app-ring"
    key_name = f"{ring_name}/cryptoKeys/app-key"

    # 1. create key ring
    r = gkms.dispatch(st, "POST", f"{LOC}/keyRings", {"keyRingId": "app-ring"}, {}, b"{}")
    _check("create keyRing 200", r.status == 200)
    _check("create keyRing name", _jbody(r)["name"] == ring_name)
    _check("create keyRing createTime", "createTime" in _jbody(r))

    # 1b. duplicate key ring -> 409 ALREADY_EXISTS
    dup = gkms.dispatch(st, "POST", f"{LOC}/keyRings", {"keyRingId": "app-ring"}, {}, b"{}")
    _check("duplicate keyRing 409", dup.status == 409)
    _check("duplicate keyRing status", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2. get key ring + list key rings
    gr = gkms.dispatch(st, "GET", RING, {}, {}, b"")
    _check("get keyRing 200", gr.status == 200 and _jbody(gr)["name"] == ring_name)
    lr = gkms.dispatch(st, "GET", f"{LOC}/keyRings", {}, {}, b"")
    _check("list keyRings has ring", any(k["name"] == ring_name for k in _jbody(lr)["keyRings"]))

    # 3. create crypto key
    ck = gkms.dispatch(st, "POST", f"{RING}/cryptoKeys", {"cryptoKeyId": "app-key"},
                       {"content-type": "application/json"},
                       json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
    _check("create cryptoKey 200", ck.status == 200)
    cko = _jbody(ck)
    _check("create cryptoKey name", cko["name"] == key_name)
    _check("create cryptoKey purpose", cko["purpose"] == "ENCRYPT_DECRYPT")
    _check("create cryptoKey primary version", cko["primary"]["name"].endswith("/cryptoKeyVersions/1"))
    _check("create cryptoKey primary enabled", cko["primary"]["state"] == "ENABLED")

    # 3b. create crypto key on unknown ring -> 404
    badring = gkms.dispatch(st, "POST", f"{LOC}/keyRings/nope/cryptoKeys",
                            {"cryptoKeyId": "k"}, {}, b"{}")
    _check("cryptoKey on missing ring 404", badring.status == 404)

    # 4. get crypto key + list crypto keys
    gk = gkms.dispatch(st, "GET", KEY, {}, {}, b"")
    _check("get cryptoKey 200", gk.status == 200 and _jbody(gk)["name"] == key_name)
    lk = gkms.dispatch(st, "GET", f"{RING}/cryptoKeys", {}, {}, b"")
    _check("list cryptoKeys has key", any(k["name"] == key_name for k in _jbody(lk)["cryptoKeys"]))

    # 5. encrypt -> ciphertext != plaintext, echoes the crypto key name
    secret = b"the launch codes are 0000"
    enc = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {},
                        {"content-type": "application/json"},
                        json.dumps({"plaintext": base64.b64encode(secret).decode()}).encode())
    _check("encrypt 200", enc.status == 200)
    eo = _jbody(enc)
    # EncryptResponse.name is the CryptoKeyVersion used (real Cloud KMS wire).
    _check("encrypt name is the primary cryptoKeyVersion", eo["name"] == key_name + "/cryptoKeyVersions/1")
    _check("encrypt returns ciphertext", bool(eo.get("ciphertext")))
    ciphertext = base64.b64decode(eo["ciphertext"])
    _check("ciphertext != plaintext", ciphertext != secret)

    # 5b. empty plaintext -> 400 INVALID_ARGUMENT
    empty = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {},
                          {"content-type": "application/json"},
                          json.dumps({"plaintext": ""}).encode())
    _check("empty plaintext 400", empty.status == 400 and
           _jbody(empty)["error"]["status"] == "INVALID_ARGUMENT")

    # 6. decrypt -> recovers the EXACT plaintext
    dec = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {},
                        {"content-type": "application/json"},
                        json.dumps({"ciphertext": eo["ciphertext"]}).encode())
    _check("decrypt 200", dec.status == 200)
    recovered = base64.b64decode(_jbody(dec)["plaintext"])
    _check("decrypt round-trips exact plaintext", recovered == secret)

    # 6b. tampered ciphertext -> 400 (authenticated crypto rejects it)
    bad = bytearray(ciphertext)
    bad[-1] ^= 0xFF
    tamper = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {},
                           {"content-type": "application/json"},
                           json.dumps({"ciphertext": base64.b64encode(bytes(bad)).decode()}).encode())
    _check("tampered ciphertext 400", tamper.status == 400)

    # 7. get / encrypt on unknown crypto key -> 404 NOT_FOUND
    miss = gkms.dispatch(st, "GET", f"{RING}/cryptoKeys/ghost", {}, {}, b"")
    _check("unknown cryptoKey 404", miss.status == 404)
    _check("unknown cryptoKey status", _jbody(miss)["error"]["status"] == "NOT_FOUND")
    missenc = gkms.dispatch(st, "POST", f"{RING}/cryptoKeys/ghost:encrypt", {},
                            {"content-type": "application/json"},
                            json.dumps({"plaintext": base64.b64encode(b"x").decode()}).encode())
    _check("encrypt unknown key 404", missenc.status == 404)

    # 8. version lifecycle: create a 2nd version, make it primary, disable/enable,
    #    destroy + restore, and confirm Encrypt is blocked while the primary is disabled.
    v2 = gkms.dispatch(st, "POST", f"{KEY}/cryptoKeyVersions", {}, {}, b"{}")
    _check("create version 200", v2.status == 200)
    v2o = _jbody(v2)
    _check("create version id", v2o["name"] == key_name + "/cryptoKeyVersions/2")
    _check("create version enabled", v2o["state"] == "ENABLED")

    setprim = gkms.dispatch(st, "POST", f"{KEY}:updateCryptoKeyPrimaryVersion", {},
                            {"content-type": "application/json"}, json.dumps({"cryptoKeyVersionId": "2"}).encode())
    _check("updateCryptoKeyPrimaryVersion 200", setprim.status == 200)
    _check("primary is now v2", _jbody(setprim)["primary"]["name"].endswith("/cryptoKeyVersions/2"))

    badprim = gkms.dispatch(st, "POST", f"{KEY}:updateCryptoKeyPrimaryVersion", {},
                            {"content-type": "application/json"}, json.dumps({"cryptoKeyVersionId": "99"}).encode())
    _check("updateCryptoKeyPrimaryVersion unknown version 400", badprim.status == 400)

    dis = gkms.dispatch(st, "PATCH", f"{KEY}/cryptoKeyVersions/2", {}, {"content-type": "application/json"},
                        json.dumps({"state": "DISABLED"}).encode())
    _check("disable version 200", dis.status == 200 and _jbody(dis)["state"] == "DISABLED")

    blocked = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {}, {"content-type": "application/json"},
                            json.dumps({"plaintext": base64.b64encode(b"x").decode()}).encode())
    _check("encrypt with disabled primary → 400 FAILED_PRECONDITION", blocked.status == 400 and
           _jbody(blocked)["error"]["status"] == "FAILED_PRECONDITION")

    en = gkms.dispatch(st, "PATCH", f"{KEY}/cryptoKeyVersions/2", {}, {"content-type": "application/json"},
                       json.dumps({"state": "ENABLED"}).encode())
    _check("re-enable version 200", en.status == 200 and _jbody(en)["state"] == "ENABLED")
    again = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {}, {"content-type": "application/json"},
                          json.dumps({"plaintext": base64.b64encode(b"y").decode()}).encode())
    _check("encrypt with re-enabled primary 200", again.status == 200)

    # 8a. each CryptoKeyVersion has its OWN key material (real rotation, not bookkeeping
    #     over shared bytes) and Decrypt re-checks the ORIGINATING version's state, not
    #     just that the CryptoKey still exists.
    dec_again = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {}, {"content-type": "application/json"},
                              json.dumps({"ciphertext": _jbody(again)["ciphertext"]}).encode())
    _check("decrypt v2 ciphertext 200", dec_again.status == 200)
    _check("decrypt v2 recovers exact plaintext", base64.b64decode(_jbody(dec_again)["plaintext"]) == b"y")
    _check("decrypt reports usedPrimary True (v2 is primary)", _jbody(dec_again)["usedPrimary"] is True)

    setprim2 = gkms.dispatch(st, "POST", f"{KEY}:updateCryptoKeyPrimaryVersion", {},
                             {"content-type": "application/json"}, json.dumps({"cryptoKeyVersionId": "1"}).encode())
    _check("primary switched to v1", _jbody(setprim2)["primary"]["name"].endswith("/cryptoKeyVersions/1"))
    dec_nonprimary = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {}, {"content-type": "application/json"},
                                   json.dumps({"ciphertext": _jbody(again)["ciphertext"]}).encode())
    _check("decrypt still works for a non-primary but enabled version", dec_nonprimary.status == 200)
    _check("usedPrimary now False (v2 is enabled but no longer primary)", _jbody(dec_nonprimary)["usedPrimary"] is False)

    dis2 = gkms.dispatch(st, "PATCH", f"{KEY}/cryptoKeyVersions/2", {}, {"content-type": "application/json"},
                        json.dumps({"state": "DISABLED"}).encode())
    _check("disable v2 (no longer primary) 200", dis2.status == 200)
    blocked_dec = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {}, {"content-type": "application/json"},
                                json.dumps({"ciphertext": _jbody(again)["ciphertext"]}).encode())
    _check("decrypt refuses a ciphertext whose originating version is disabled -> 400 FAILED_PRECONDITION",
           blocked_dec.status == 400 and _jbody(blocked_dec)["error"]["status"] == "FAILED_PRECONDITION")

    en2 = gkms.dispatch(st, "PATCH", f"{KEY}/cryptoKeyVersions/2", {}, {"content-type": "application/json"},
                       json.dumps({"state": "ENABLED"}).encode())
    _check("re-enable v2 200", en2.status == 200)
    setprim3 = gkms.dispatch(st, "POST", f"{KEY}:updateCryptoKeyPrimaryVersion", {},
                             {"content-type": "application/json"}, json.dumps({"cryptoKeyVersionId": "2"}).encode())
    _check("primary switched back to v2", _jbody(setprim3)["primary"]["name"].endswith("/cryptoKeyVersions/2"))

    destroy = gkms.dispatch(st, "POST", f"{KEY}/cryptoKeyVersions/1:destroy", {}, {}, b"{}")
    _check("destroy version 200", destroy.status == 200)
    dobj = _jbody(destroy)
    _check("destroy sets DESTROY_SCHEDULED", dobj["state"] == "DESTROY_SCHEDULED")
    _check("destroy sets destroyTime", "destroyTime" in dobj)
    dup_destroy = gkms.dispatch(st, "POST", f"{KEY}/cryptoKeyVersions/1:destroy", {}, {}, b"{}")
    _check("double destroy → 400 FAILED_PRECONDITION", dup_destroy.status == 400)

    restore = gkms.dispatch(st, "POST", f"{KEY}/cryptoKeyVersions/1:restore", {}, {}, b"{}")
    _check("restore version 200", restore.status == 200 and _jbody(restore)["state"] == "DISABLED")
    bad_restore = gkms.dispatch(st, "POST", f"{KEY}/cryptoKeyVersions/1:restore", {}, {}, b"{}")
    _check("restore a non-scheduled version → 400", bad_restore.status == 400)

    # 8b. v1 is now DISABLED (destroyed + restored above). The ciphertext it minted way
    #     back in step 5 (while ENABLED and primary) must now be refused — the CryptoKey
    #     still exists, but Decrypt tracks the specific version, not just the key.
    stale = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {}, {"content-type": "application/json"},
                          json.dumps({"ciphertext": eo["ciphertext"]}).encode())
    _check("decrypt refuses a ciphertext whose version is now disabled -> 400 FAILED_PRECONDITION",
          stale.status == 400 and _jbody(stale)["error"]["status"] == "FAILED_PRECONDITION")

    listv = gkms.dispatch(st, "GET", f"{KEY}/cryptoKeyVersions", {}, {}, b"")
    _check("list versions has both", len(_jbody(listv)["cryptoKeyVersions"]) == 2)

    # 9. IAM policy on a crypto key: getIamPolicy / setIamPolicy round-trip.
    pol0 = gkms.dispatch(st, "GET", f"{KEY}:getIamPolicy", {}, {}, b"")
    _check("getIamPolicy default empty", pol0.status == 200 and _jbody(pol0)["bindings"] == [])
    setpol = gkms.dispatch(st, "POST", f"{KEY}:setIamPolicy", {}, {"content-type": "application/json"},
                           json.dumps({"policy": {"bindings": [{"role": "roles/cloudkms.cryptoKeyEncrypterDecrypter",
                                                                  "members": ["user:dev@example.com"]}]}}).encode())
    _check("setIamPolicy 200", setpol.status == 200)
    pol1 = gkms.dispatch(st, "GET", f"{KEY}:getIamPolicy", {}, {}, b"")
    _check("getIamPolicy round-trips the binding", _jbody(pol1)["bindings"][0]["members"] == ["user:dev@example.com"])

    # 9b. permissions enforcement (v4 DEPTH): unlike the store-only policy above, the binding
    #     just set actually gates :encrypt / :decrypt / :setIamPolicy by the caller's role.
    denied_enc = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {},
                               {"content-type": "application/json", "X-Cloudlearn-Principal": "bob@example.com"},
                               json.dumps({"plaintext": base64.b64encode(b"z").decode()}).encode())
    _check("encrypt denied for ungranted principal -> 403", denied_enc.status == 403 and
           _jbody(denied_enc)["error"]["status"] == "PERMISSION_DENIED")
    allowed_enc = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {},
                                {"content-type": "application/json", "X-Cloudlearn-Principal": "dev@example.com"},
                                json.dumps({"plaintext": base64.b64encode(b"z").decode()}).encode())
    _check("encrypt allowed for principal granted cryptoKeyEncrypterDecrypter", allowed_enc.status == 200)
    owner_enc = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {}, {"content-type": "application/json"},
                              json.dumps({"plaintext": base64.b64encode(b"z").decode()}).encode())
    _check("encrypt allowed with no principal header (owner bypass)", owner_enc.status == 200)

    denied_dec = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {},
                               {"content-type": "application/json", "X-Cloudlearn-Principal": "bob@example.com"},
                               json.dumps({"ciphertext": _jbody(allowed_enc)["ciphertext"]}).encode())
    _check("decrypt denied for ungranted principal -> 403", denied_dec.status == 403)
    allowed_dec = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {},
                                {"content-type": "application/json", "X-Cloudlearn-Principal": "dev@example.com"},
                                json.dumps({"ciphertext": _jbody(allowed_enc)["ciphertext"]}).encode())
    _check("decrypt allowed for principal granted cryptoKeyEncrypterDecrypter",
           allowed_dec.status == 200 and base64.b64decode(_jbody(allowed_dec)["plaintext"]) == b"z")

    denied_setpol = gkms.dispatch(st, "POST", f"{KEY}:setIamPolicy", {},
                                  {"content-type": "application/json", "X-Cloudlearn-Principal": "bob@example.com"},
                                  json.dumps({"policy": {"bindings": [
                                      {"role": "roles/cloudkms.cryptoKeyEncrypterDecrypter", "members": ["user:dev@example.com"]},
                                  ]}}).encode())
    _check("setIamPolicy denied for a principal without cloudkms.admin -> 403", denied_setpol.status == 403)

    grant_admin = gkms.dispatch(st, "POST", f"{KEY}:setIamPolicy", {}, {"content-type": "application/json"},
                                json.dumps({"policy": {"bindings": [
                                    {"role": "roles/cloudkms.admin", "members": ["user:kms-admin@example.com"]},
                                    {"role": "roles/cloudkms.cryptoKeyEncrypterDecrypter", "members": ["user:dev@example.com"]},
                                ]}}).encode())
    _check("owner (no principal header) grants cloudkms.admin", grant_admin.status == 200)

    admin_setpol = gkms.dispatch(st, "POST", f"{KEY}:setIamPolicy", {},
                                 {"content-type": "application/json", "X-Cloudlearn-Principal": "kms-admin@example.com"},
                                 json.dumps({"policy": {"bindings": [
                                     {"role": "roles/cloudkms.admin", "members": ["user:kms-admin@example.com"]},
                                 ]}}).encode())
    _check("setIamPolicy allowed for a principal granted cloudkms.admin", admin_setpol.status == 200)

    bad_members = gkms.dispatch(st, "POST", f"{KEY}:setIamPolicy", {}, {"content-type": "application/json"},
                                json.dumps({"policy": {"bindings": [{"role": "roles/cloudkms.admin", "members": []}]}}).encode())
    _check("setIamPolicy rejects a binding with empty members -> 400", bad_members.status == 400 and
           _jbody(bad_members)["error"]["status"] == "INVALID_ARGUMENT")

    # 10. project-wide aggregated listing (locations/-/keyRings/-) — the "Key inventory" page.
    agg = gkms.dispatch(st, "GET", "/v1/projects/demo/locations/-/keyRings/-/cryptoKeys", {}, {}, b"")
    _check("aggregated cryptoKeys list 200", agg.status == 200)
    _check("aggregated list includes the key", any(k["name"] == key_name for k in _jbody(agg)["cryptoKeys"]))
    aggrings = gkms.dispatch(st, "GET", "/v1/projects/demo/locations/-/keyRings", {}, {}, b"")
    _check("aggregated keyRings list includes the ring", any(k["name"] == ring_name for k in _jbody(aggrings)["keyRings"]))

    # 11. Autokey (v4 GAP SWEEP wave 5b): AutokeyConfig starts DISABLED; creating a KeyHandle
    #     before it's ACTIVE is refused; setting ACTIVE without a keyProject is refused;
    #     once ACTIVE, creating a KeyHandle really provisions a key ring + a brand-new
    #     CryptoKey (with its own key material) in the configured key project.
    cfg0 = gkms.dispatch(st, "GET", "/v1/projects/demo/autokeyConfig", {}, {}, b"")
    _check("autokeyConfig default DISABLED", cfg0.status == 200 and _jbody(cfg0)["state"] == "DISABLED")

    kh_too_early = gkms.dispatch(st, "POST", "/v1/projects/demo/locations/us-central1/keyHandles", {},
                                 {"content-type": "application/json"},
                                 json.dumps({"resourceTypeSelector": "compute.googleapis.com/Disk"}).encode())
    _check("createKeyHandle before Autokey is ACTIVE -> 400 FAILED_PRECONDITION",
           kh_too_early.status == 400 and _jbody(kh_too_early)["error"]["status"] == "FAILED_PRECONDITION")

    bad_active = gkms.dispatch(st, "PATCH", "/v1/projects/demo/autokeyConfig", {"updateMask": "state"},
                               {"content-type": "application/json"}, json.dumps({"state": "ACTIVE"}).encode())
    _check("set ACTIVE without a keyProject -> 400 FAILED_PRECONDITION",
           bad_active.status == 400 and _jbody(bad_active)["error"]["status"] == "FAILED_PRECONDITION")

    set_kp = gkms.dispatch(st, "PATCH", "/v1/projects/demo/autokeyConfig", {"updateMask": "keyProject,state"},
                           {"content-type": "application/json"},
                           json.dumps({"keyProject": "demo-keys", "state": "ACTIVE"}).encode())
    _check("set keyProject + ACTIVE 200", set_kp.status == 200)
    _check("autokeyConfig now ACTIVE with keyProject", _jbody(set_kp) == {
        "name": "projects/demo/autokeyConfig", "keyProject": "demo-keys", "state": "ACTIVE"})

    bad_selector = gkms.dispatch(st, "POST", "/v1/projects/demo/locations/us-central1/keyHandles", {},
                                 {"content-type": "application/json"},
                                 json.dumps({"resourceTypeSelector": "not-a-selector"}).encode())
    _check("createKeyHandle with a bad resourceTypeSelector -> 400 INVALID_ARGUMENT", bad_selector.status == 400)

    kh = gkms.dispatch(st, "POST", "/v1/projects/demo/locations/us-central1/keyHandles", {"keyHandleId": "disk-1"},
                       {"content-type": "application/json"},
                       json.dumps({"resourceTypeSelector": "compute.googleapis.com/Disk"}).encode())
    _check("createKeyHandle 200", kh.status == 200)
    khbody = _jbody(kh)
    _check("createKeyHandle returns a done Operation", khbody["done"] is True)
    khview = khbody["response"]
    kh_name = "projects/demo/locations/us-central1/keyHandles/disk-1"
    _check("KeyHandle name", khview["name"] == kh_name)
    kms_key = khview.get("kmsKey", "")
    _check("KeyHandle kmsKey is provisioned in the configured key project",
           kms_key.startswith("projects/demo-keys/locations/us-central1/keyRings/autokey-us-central1/cryptoKeys/"))

    # The provisioned key is a REAL, usable CryptoKey — not a bookkeeping reference.
    prov_enc = gkms.dispatch(st, "POST", f"/v1/{kms_key}:encrypt", {}, {"content-type": "application/json"},
                             json.dumps({"plaintext": base64.b64encode(b"autokey works").decode()}).encode())
    _check("Autokey-provisioned CryptoKey really encrypts", prov_enc.status == 200)

    dup_kh = gkms.dispatch(st, "POST", "/v1/projects/demo/locations/us-central1/keyHandles", {"keyHandleId": "disk-1"},
                           {"content-type": "application/json"},
                           json.dumps({"resourceTypeSelector": "compute.googleapis.com/Disk"}).encode())
    _check("duplicate keyHandleId -> 409 ALREADY_EXISTS", dup_kh.status == 409)

    get_kh = gkms.dispatch(st, "GET", f"/v1/{kh_name}", {}, {}, b"")
    _check("getKeyHandle 200", get_kh.status == 200 and _jbody(get_kh)["name"] == kh_name)

    list_kh = gkms.dispatch(st, "GET", "/v1/projects/demo/locations/us-central1/keyHandles", {}, {}, b"")
    _check("listKeyHandles includes it", any(h["name"] == kh_name for h in _jbody(list_kh)["keyHandles"]))

    disable_again = gkms.dispatch(st, "PATCH", "/v1/projects/demo/autokeyConfig", {"updateMask": "state"},
                                  {"content-type": "application/json"}, json.dumps({"state": "DISABLED"}).encode())
    _check("disable Autokey 200", disable_again.status == 200 and _jbody(disable_again)["state"] == "DISABLED")
    kh_after_disable = gkms.dispatch(st, "POST", "/v1/projects/demo/locations/us-central1/keyHandles", {"keyHandleId": "disk-2"},
                                     {"content-type": "application/json"},
                                     json.dumps({"resourceTypeSelector": "compute.googleapis.com/Disk"}).encode())
    _check("createKeyHandle refused once Autokey is disabled again -> 400", kh_after_disable.status == 400)

    print("\nGCP Cloud KMS core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
