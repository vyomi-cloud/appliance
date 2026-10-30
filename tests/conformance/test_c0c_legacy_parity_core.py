"""v4 C0c — behaviours ported from the retired offline handlers into the shared cores.

The offline appliance's native AWS KMS and Secrets Manager wire (core/vault_routes.py
`_aws_kms_dispatch` / `_aws_secrets_dispatch`, Vault-backed) and the classic console
REST beside them now run on the shared conformance cores (core/kms_core.py,
core/secrets_core.py). Every legacy behaviour the cores lacked — and that real AWS
also has — was ported; this suite pins each one on the in-memory substrate AND the
file-backed (sqlite) substrate (a fresh store instance must see the state, including
key material, so ciphertext made before a "restart" still decrypts).

The last section exercises the appliance upgrade path (core/appliance_stores.py:
adopting pre-v4 Vault secrets / transit keys and decrypting `vault:v1:` ciphertext)
against a FAKE Vault — host only, skipped where the appliance modules don't import.

Run:  PYTHONPATH=. python3 tests/conformance/test_c0c_legacy_parity_core.py
"""
import base64
import uuid

from core import kms_core as kms
from core import secrets_core as sm
from core.kms_keystore import InMemoryKeyStore
from core.kv_store import InMemoryKvStore
from core.persistent_store import PersistentKeyStore, PersistentKvStore, SqliteStateBackend

K, S = "TrentService.", "secretsmanager."


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _e(b: bytes) -> str:
    return base64.b64encode(b).decode()


# ── AWS KMS ─────────────────────────────────────────────────────────────────
def aws_kms(make, label):
    st = make()
    kid = kms.dispatch(st, K + "CreateKey", {"Description": "d0"}).body["KeyMetadata"]["KeyId"]
    kms.dispatch(st, K + "CreateAlias", {"AliasName": "alias/app", "TargetKeyId": kid})
    enc = kms.dispatch(st, K + "Encrypt", {"KeyId": "alias/app", "Plaintext": _e(b"before")}).body

    # legacy (Encapsulate) + real AWS: a DISABLED key → DisabledException; pending deletion
    # stays KMSInvalidStateException
    kms.dispatch(st, K + "DisableKey", {"KeyId": kid})
    r = kms.dispatch(st, K + "Encrypt", {"KeyId": kid, "Plaintext": _e(b"x")})
    _check(f"[{label}] disabled key → DisabledException", r.body.get("__type") == "DisabledException", r.body)
    r = kms.dispatch(st, K + "Decrypt", {"CiphertextBlob": enc["CiphertextBlob"]})
    _check(f"[{label}] decrypt on disabled key → DisabledException", r.body.get("__type") == "DisabledException")
    kms.dispatch(st, K + "EnableKey", {"KeyId": kid})

    # legacy console PUT {description} = UpdateKeyDescription
    r = kms.dispatch(st, K + "UpdateKeyDescription", {"KeyId": kid, "Description": "edited"})
    _check(f"[{label}] UpdateKeyDescription", r.status == 200)
    md = kms.dispatch(st, K + "DescribeKey", {"KeyId": "alias/app"}).body["KeyMetadata"]
    _check(f"[{label}] description updated", md["Description"] == "edited")

    # legacy: EnableKeyRotation honours an explicit RotationPeriodInDays (also on re-enable)
    kms.dispatch(st, K + "EnableKeyRotation", {"KeyId": kid})
    kms.dispatch(st, K + "EnableKeyRotation", {"KeyId": kid, "RotationPeriodInDays": 180})
    rs = kms.dispatch(st, K + "GetKeyRotationStatus", {"KeyId": kid}).body
    _check(f"[{label}] RotationPeriodInDays updated", rs.get("RotationPeriodInDays") == 180, rs)
    bad = kms.dispatch(st, K + "EnableKeyRotation", {"KeyId": kid, "RotationPeriodInDays": 7})
    _check(f"[{label}] RotationPeriodInDays out of 90..2560 rejected", bad.body.get("__type") == "ValidationException")

    # v4 console: Encrypt against an unseen alias/aws/<service> provisions the AWS managed key
    r = kms.dispatch(st, K + "Encrypt", {"KeyId": "alias/aws/c0c", "Plaintext": _e(b"m")})
    _check(f"[{label}] alias/aws/* auto-provisions on Encrypt", r.status == 200)

    # real AWS: Encrypt / GenerateDataKey need an ENCRYPT_DECRYPT key
    sk = kms.dispatch(st, K + "CreateKey", {"KeyUsage": "SIGN_VERIFY", "KeySpec": "RSA_2048"}).body["KeyMetadata"]["KeyId"]
    r = kms.dispatch(st, K + "Encrypt", {"KeyId": sk, "Plaintext": _e(b"x")})
    _check(f"[{label}] Encrypt on a SIGN_VERIFY key → InvalidKeyUsageException",
           r.body.get("__type") == "InvalidKeyUsageException")
    sig = kms.dispatch(st, K + "Sign", {"KeyId": sk, "Message": _e(b"msg"),
                                         "SigningAlgorithm": "RSASSA_PSS_SHA_256"}).body["Signature"]

    # custom key stores are store state (persisted)
    cks = kms.dispatch(st, K + "CreateCustomKeyStore", {"CustomKeyStoreName": "x1",
                                                         "CustomKeyStoreType": "EXTERNAL_KEY_STORE"}).body
    _check(f"[{label}] custom key store kept in store.custom_key_stores",
           cks["CustomKeyStoreId"] in st.custom_key_stores)

    # rotate on demand, then reload: old + new ciphertext decrypt (material + history persisted)
    kms.dispatch(st, K + "RotateKeyOnDemand", {"KeyId": kid})
    enc2 = kms.dispatch(st, K + "Encrypt", {"KeyId": kid, "Plaintext": _e(b"after")}).body
    st2 = make(reload=True) or st
    for blob, want in ((enc["CiphertextBlob"], b"before"), (enc2["CiphertextBlob"], b"after")):
        d = kms.dispatch(st2, K + "Decrypt", {"CiphertextBlob": blob})
        _check(f"[{label}] decrypt {want.decode()!r} after reload",
               d.status == 200 and base64.b64decode(d.body["Plaintext"]) == want)
    _check(f"[{label}] alias survives reload",
           kms.dispatch(st2, K + "DescribeKey", {"KeyId": "alias/app"}).body["KeyMetadata"]["KeyId"] == kid)
    v = kms.dispatch(st2, K + "Verify", {"KeyId": sk, "Message": _e(b"msg"), "Signature": sig,
                                          "SigningAlgorithm": "RSASSA_PSS_SHA_256"}).body
    _check(f"[{label}] signature verifies after reload", v.get("SignatureValid") is True)
    d = kms.dispatch(st2, K + "DescribeCustomKeyStores", {}).body
    _check(f"[{label}] custom key store survives reload",
           [c["CustomKeyStoreId"] for c in d["CustomKeyStores"]] == [cks["CustomKeyStoreId"]])
    aws_alias = dict(st2.alias_items()).get("alias/aws/c0c")
    _check(f"[{label}] AWS managed key survives reload",
           aws_alias and st2.get_key(aws_alias)["KeyManager"] == "AWS")


class _LegacyKeyStore(InMemoryKeyStore):
    """A store with the appliance's legacy hook (the real one asks Vault transit)."""

    def legacy_decrypt(self, key_ref, blob):
        self.last = (key_ref, blob)
        return ("legacykey", b"from-vault") if blob.startswith(b"vault:v1:good") else None


def kms_legacy_ciphertext():
    st = _LegacyKeyStore()
    # the pre-v4 Encrypt wrapped Vault's "vault:v1:…" string in base64
    d = kms.dispatch(st, K + "Decrypt", {"CiphertextBlob": _e(b"vault:v1:good"), "KeyId": "alias/x"})
    _check("[legacy] base64-wrapped vault:v1 ciphertext decrypts via legacy_decrypt",
           d.status == 200 and base64.b64decode(d.body["Plaintext"]) == b"from-vault")
    _check("[legacy] the request KeyId reaches the hook", st.last == ("alias/x", b"vault:v1:good"))
    # the pre-v4 GenerateDataKey returned the raw string
    d = kms.dispatch(st, K + "Decrypt", {"CiphertextBlob": "vault:v1:good"})
    _check("[legacy] raw vault:v1 ciphertext decrypts", d.status == 200)
    d = kms.dispatch(st, K + "Decrypt", {"CiphertextBlob": _e(b"vault:v1:bad")})
    _check("[legacy] undecryptable vault:v1 → InvalidCiphertextException",
           d.body.get("__type") == "InvalidCiphertextException")
    d = kms.dispatch(InMemoryKeyStore(), K + "Decrypt", {"CiphertextBlob": _e(b"vault:v1:good")})
    _check("[legacy] without the hook it is just an unknown ciphertext", d.status == 400)


# ── Secrets Manager ─────────────────────────────────────────────────────────
def secrets(make, label):
    st = make()
    tok = str(uuid.uuid4())
    r = sm.dispatch(st, S + "CreateSecret", {"Name": "app/db", "SecretString": "v1", "ClientRequestToken": tok,
                                              "KmsKeyId": "alias/custom", "Description": "db",
                                              "Tags": [{"Key": "env", "Value": "dev"}]})
    _check(f"[{label}] ClientRequestToken is the VersionId", r.body.get("VersionId") == tok, r.body)
    r = sm.dispatch(st, S + "CreateSecret", {"Name": "app/db", "SecretString": "v1", "ClientRequestToken": tok})
    _check(f"[{label}] CreateSecret retry with the same token is idempotent", r.status == 200)
    r = sm.dispatch(st, S + "CreateSecret", {"Name": "app/db", "SecretString": "other", "ClientRequestToken": tok})
    _check(f"[{label}] same token, different value → ResourceExistsException",
           r.body.get("__type") == "ResourceExistsException")
    # legacy: PutSecretValue overwrites (new version); real AWS: AWSCURRENT/AWSPREVIOUS
    p = sm.dispatch(st, S + "PutSecretValue", {"SecretId": "app/db", "SecretString": "v2"}).body
    # legacy console: per-secret encryption key (kms_key_id) + description are kept
    d = sm.dispatch(st, S + "DescribeSecret", {"SecretId": "app/db"}).body
    _check(f"[{label}] KmsKeyId kept", d.get("KmsKeyId") == "alias/custom")
    _check(f"[{label}] Tags kept", d.get("Tags") == [{"Key": "env", "Value": "dev"}])
    # UpdateSecret without a value: metadata only, no new version
    sm.dispatch(st, S + "UpdateSecret", {"SecretId": "app/db", "Description": "db2"})
    vs = sm.dispatch(st, S + "ListSecretVersionIds", {"SecretId": "app/db"}).body["Versions"]
    _check(f"[{label}] UpdateSecret(Description) adds no version", len(vs) == 2)
    sm.dispatch(st, S + "TagResource", {"SecretId": "app/db", "Tags": [{"Key": "team", "Value": "a"}]})
    sm.dispatch(st, S + "UntagResource", {"SecretId": "app/db", "TagKeys": ["env"]})
    ls = sm.dispatch(st, S + "ListSecrets", {}).body["SecretList"]
    _check(f"[{label}] ListSecrets carries Tags + SecretVersionsToStages",
           ls[0].get("Tags") == [{"Key": "team", "Value": "a"}] and len(ls[0]["SecretVersionsToStages"]) == 2)
    # recovery window: scheduled → hidden + blocked; recreate is refused; restore works
    sm.dispatch(st, S + "CreateSecret", {"Name": "tmp", "SecretString": "t"})
    sm.dispatch(st, S + "DeleteSecret", {"SecretId": "tmp", "RecoveryWindowInDays": 7})
    r = sm.dispatch(st, S + "CreateSecret", {"Name": "tmp", "SecretString": "t2"})
    _check(f"[{label}] create over a scheduled-deletion name → InvalidRequestException",
           r.body.get("__type") == "InvalidRequestException")
    names = [s["Name"] for s in sm.dispatch(st, S + "ListSecrets", {}).body["SecretList"]]
    _check(f"[{label}] scheduled secret hidden from ListSecrets", names == ["app/db"])
    # legacy console delete = immediate (ForceDeleteWithoutRecovery)
    sm.dispatch(st, S + "CreateSecret", {"Name": "gone", "SecretString": "g"})
    sm.dispatch(st, S + "DeleteSecret", {"SecretId": "gone", "ForceDeleteWithoutRecovery": True})

    st2 = make(reload=True) or st
    g = sm.dispatch(st2, S + "GetSecretValue", {"SecretId": "app/db"}).body
    _check(f"[{label}] current value + VersionId after reload",
           g.get("SecretString") == "v2" and g.get("VersionId") == p["VersionId"])
    g = sm.dispatch(st2, S + "GetSecretValue", {"SecretId": "app/db", "VersionStage": "AWSPREVIOUS"}).body
    _check(f"[{label}] AWSPREVIOUS after reload", g.get("SecretString") == "v1" and g.get("VersionId") == tok)
    r = sm.dispatch(st2, S + "RestoreSecret", {"SecretId": "tmp"})
    _check(f"[{label}] restore after reload", r.status == 200 and
           sm.dispatch(st2, S + "GetSecretValue", {"SecretId": "tmp"}).body.get("SecretString") == "t")
    r = sm.dispatch(st2, S + "DescribeSecret", {"SecretId": "gone"})
    _check(f"[{label}] force-deleted secret is gone", r.body.get("__type") == "ResourceNotFoundException")


# ── upgrade path (appliance stores over a FAKE Vault) ──────────────────────
class _FakeVault:
    """Just enough of core.vault_client + the pre-v4 index helpers of core.vault_routes."""

    def __init__(self, sid):
        self.sid = sid
        self.kv = {("aws", sid, "app/db"): [
            {"version": 1, "created_time": "2026-09-01T10:00:00.123456789Z", "value": "old"},
            {"version": 2, "created_time": "2026-09-02T10:00:00Z", "value": "new"},
            {"version": 3, "created_time": "2026-09-03T10:00:00Z", "value": None, "destroyed": True}],
            ("aws", sid, "plain"): [{"version": 1, "created_time": "2026-09-05T00:00:00Z", "value": "p"}]}
        self.transit = {"0123456789abcdef0123456789abcdef", "default", "my-alias"}
        self.calls = 0

    # vault_client
    def available(self):
        self.calls += 1
        return True

    def kv_list_versions(self, prov, sid, name):
        return [{k: v for k, v in x.items() if k != "value"} for x in self.kv.get((prov, sid, name), [])]

    def kv_get(self, prov, sid, name, version=None):
        for x in self.kv.get((prov, sid, name), []):
            if x["version"] == version and x["value"] is not None:
                return {"data": {"value": x["value"]}, "metadata": {"version": version}}
        return None

    def transit_list_keys(self, prov, sid):
        return sorted(self.transit) if sid == self.sid else []

    def transit_decrypt(self, prov, sid, key, ct):
        if sid == self.sid and key in self.transit and ct == f"vault:v1:{key}":
            return _e(b"legacy-" + key.encode())
        return None

    # vault_routes
    def _aws_secret_index_get(self, sid):
        return ["app/db", "plain"]

    def _aws_secret_created(self, sid):
        return {"app/db": "2026-09-01T10:00:00.000000Z"}

    def _aws_secret_meta(self, sid, name):
        return ({"kms_key_id": "alias/custom", "description": "db creds"} if name == "app/db"
                else {"kms_key_id": "aws/secretsmanager"})


def upgrade_path():
    try:
        from core import appliance_stores as aps
        from core import vault_client as vc
        from core import vault_routes as vr
    except Exception as exc:   # pragma: no cover - not the appliance (e.g. Pyodide)
        print(f"  skip upgrade path (appliance modules unavailable: {exc})")
        return
    fake = _FakeVault(aps._active_space_id())
    saved = {}
    for mod, names in ((vc, ("available", "kv_list_versions", "kv_get", "transit_list_keys", "transit_decrypt")),
                       (vr, ("_aws_secret_index_get", "_aws_secret_created", "_aws_secret_meta"))):
        for n in names:
            saved[(mod, n)] = getattr(mod, n)
            setattr(mod, n, getattr(fake, n))
    try:
        sec = aps.AppStateAwsKvStore({}, account_id="123456789012")
        sec.adopt()
        sec.adopt()          # once per space
        _check("[upgrade] Vault secrets adopted", sorted(sec.names()) == ["app/db", "plain"])
        g = sm.dispatch(sec, S + "GetSecretValue", {"SecretId": "app/db"}).body
        _check("[upgrade] newest live Vault version is AWSCURRENT", g.get("SecretString") == "new")
        g = sm.dispatch(sec, S + "GetSecretValue", {"SecretId": "app/db", "VersionStage": "AWSPREVIOUS"}).body
        _check("[upgrade] the one before is AWSPREVIOUS", g.get("SecretString") == "old")
        _check("[upgrade] destroyed Vault versions are skipped",
               len(sm.dispatch(sec, S + "ListSecretVersionIds", {"SecretId": "app/db"}).body["Versions"]) == 2)
        d = sm.dispatch(sec, S + "DescribeSecret", {"SecretId": "app/db"}).body
        _check("[upgrade] console description + encryption key adopted",
               d["Description"] == "db creds" and d.get("KmsKeyId") == "alias/custom")
        _check("[upgrade] default aws/secretsmanager key is not echoed as KmsKeyId",
               "KmsKeyId" not in sm.dispatch(sec, S + "DescribeSecret", {"SecretId": "plain"}).body)
        _check("[upgrade] RFC3339 creation time parses", abs(d["CreatedDate"] - 1788256800.0) < 1, d)
        prev = sm.dispatch(sec, S + "GetSecretValue", {"SecretId": "app/db", "VersionStage": "AWSPREVIOUS"}).body
        _check("[upgrade] Vault's nanosecond version times parse",
               abs(prev["CreatedDate"] - 1788256800.123456) < 0.001, prev)
        sm.dispatch(sec, S + "PutSecretValue", {"SecretId": "app/db", "SecretString": "newer"})
        sec._adopted.clear()
        sec.adopt()          # a re-adopt never clobbers state written since
        _check("[upgrade] re-adoption keeps newer state",
               sm.dispatch(sec, S + "GetSecretValue", {"SecretId": "app/db"}).body["SecretString"] == "newer")

        ks = aps.AppStateAwsKeyStore({}, {}, {}, {}, account_id="123456789012")
        ks.adopt()
        _check("[upgrade] CreateKey-style transit keys adopted (32-hex ids only)",
               ks.key_ids() == ["0123456789abcdef0123456789abcdef"])
        kid = "0123456789abcdef0123456789abcdef"
        d = kms.dispatch(ks, K + "Decrypt", {"CiphertextBlob": _e(f"vault:v1:{kid}".encode()), "KeyId": kid})
        _check("[upgrade] pre-v4 ciphertext of an adopted key decrypts",
               d.status == 200 and base64.b64decode(d.body["Plaintext"]) == b"legacy-" + kid.encode()
               and d.body["KeyId"].endswith(f":key/{kid}"))
        d = kms.dispatch(ks, K + "Decrypt", {"CiphertextBlob": _e(b"vault:v1:my-alias"), "KeyId": "alias/my-alias"})
        _check("[upgrade] unresolved alias → its tail names the transit key (pre-v4 naming)",
               d.status == 200 and base64.b64decode(d.body["Plaintext"]) == b"legacy-my-alias")
        d = kms.dispatch(ks, K + "Decrypt", {"CiphertextBlob": _e(b"vault:v1:default")})
        _check("[upgrade] no KeyId: every key of the space, then 'default', is tried", d.status == 200)
        enc = kms.dispatch(ks, K + "Encrypt", {"KeyId": kid, "Plaintext": _e(b"fresh")}).body
        d = kms.dispatch(ks, K + "Decrypt", {"CiphertextBlob": enc["CiphertextBlob"]})
        _check("[upgrade] adopted key encrypts with fresh core material",
               base64.b64decode(d.body["Plaintext"]) == b"fresh")
        calls = fake.calls
        ks.adopt()
        _check("[upgrade] adoption runs once per space", fake.calls == calls)
    finally:
        for (mod, n), fn in saved.items():
            setattr(mod, n, fn)


def no_vault_upgrade_is_a_noop():
    try:
        from core import appliance_stores as aps
        from core import vault_client as vc
    except Exception:   # pragma: no cover
        return
    orig = vc.available
    vc.available = lambda: False
    try:
        ks = aps.AppStateAwsKeyStore({}, {}, {}, {})
        ks.adopt()
        sec = aps.AppStateAwsKvStore({})
        sec.adopt()
        _check("[upgrade] no Vault → nothing adopted, nothing raised", not ks.key_ids() and not sec.names())
        _check("[upgrade] no Vault → legacy ciphertext is simply undecryptable",
               ks.legacy_decrypt("k", b"vault:v1:x") is None)
    finally:
        vc.available = orig


def _persistent(cls, sid):
    be = SqliteStateBackend(":memory:")

    def make(reload=False):
        return cls(be, store_id=sid)
    return make


def _memory(cls):
    def make(reload=False):
        return None if reload else cls()
    return make


def run() -> int:
    print("AWS KMS:")
    aws_kms(_memory(InMemoryKeyStore), "mem")
    aws_kms(_persistent(PersistentKeyStore, "akms"), "sqlite")
    kms_legacy_ciphertext()
    print("Secrets Manager:")
    secrets(_memory(InMemoryKvStore), "mem")
    secrets(_persistent(PersistentKvStore, "asec"), "sqlite")
    print("Upgrade path (fake Vault):")
    upgrade_path()
    no_vault_upgrade_is_a_noop()
    print("\nC0c legacy-parity (AWS KMS / Secrets Manager cores): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
