"""KMS core conformance — the acceptance gate for the WASM extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE AWS KMS wire semantics (TrentService.* X-Amz-Target
dispatch, KeyMetadata shapes, base64 Plaintext/CiphertextBlob, Decrypt round-trip
that RECOVERS the KeyId from the blob, GenerateDataKey returning Plaintext +
CiphertextBlob, tamper rejection, KeyState enforcement, aliases, native
{"__type","message"} errors) — proving the extracted core conforms regardless of
substrate. The crypto is REAL (authenticated, key-separated, tamper-detected),
just substrate-free (stdlib only). No network, no fastapi/boto3/hvac.

Run on host:    python3 tests/conformance/test_kms_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import base64

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.kms_keystore import InMemoryKeyStore
    from core import kms_core as kms
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import kms_core as kms  # type: ignore

T = "TrentService."  # the native KMS X-Amz-Target prefix


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _b64(s: str) -> bytes:
    return base64.b64decode(s)


def run() -> int:
    st = InMemoryKeyStore()

    # 1. CreateKey -> KeyMetadata with native fields
    r = kms.dispatch(st, T + "CreateKey", {"Description": "test key"})
    _check("create 200", r.status == 200)
    md = r.body["KeyMetadata"]
    key_id = md["KeyId"]
    _check("create KeyState Enabled", md["KeyState"] == "Enabled")
    _check("create Arn", md["Arn"].endswith(f":key/{key_id}"))
    _check("create KeySpec SYMMETRIC_DEFAULT", md["KeySpec"] == "SYMMETRIC_DEFAULT")
    _check("create KeyUsage ENCRYPT_DECRYPT", md["KeyUsage"] == "ENCRYPT_DECRYPT")
    _check("create Origin AWS_KMS", md["Origin"] == "AWS_KMS")

    # 2. Encrypt -> base64 CiphertextBlob that is NOT the plaintext
    secret = b"the launch codes are 0000"
    enc = kms.dispatch(st, T + "Encrypt", {"KeyId": key_id, "Plaintext": base64.b64encode(secret).decode()})
    _check("encrypt 200", enc.status == 200)
    blob_b64 = enc.body["CiphertextBlob"]
    _check("encrypt blob present", bool(blob_b64))
    _check("encrypt blob != plaintext", _b64(blob_b64) != secret)
    _check("encrypt KeyId is the key ARN", enc.body["KeyId"].endswith(f":key/{key_id}"))

    # 3. Decrypt WITHOUT KeyId -> recovers KeyId from the blob, round-trips plaintext
    dec = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": blob_b64})
    _check("decrypt 200", dec.status == 200)
    _check("decrypt round-trips plaintext", _b64(dec.body["Plaintext"]) == secret)
    _check("decrypt recovers KeyId from blob", dec.body["KeyId"].endswith(f":key/{key_id}"))

    # 4. Tampered ciphertext -> InvalidCiphertextException (auth tag rejects it)
    raw = bytearray(_b64(blob_b64))
    raw[-1] ^= 0x01  # flip one bit of the MAC tag
    bad = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": base64.b64encode(bytes(raw)).decode()})
    _check("tampered blob 400", bad.status == 400)
    _check("tampered blob InvalidCiphertextException", bad.body["__type"] == "InvalidCiphertextException")

    # 5. Key separation: a second key cannot decrypt key1's blob
    r2 = kms.dispatch(st, T + "CreateKey", {})
    key2 = r2.body["KeyMetadata"]["KeyId"]
    wrong = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": blob_b64, "KeyId": key2})
    _check("wrong key rejected", wrong.status == 400 and wrong.body["__type"] == "IncorrectKeyException")

    # 6. GenerateDataKey -> Plaintext (32 bytes) + CiphertextBlob; blob decrypts to the data key
    dk = kms.dispatch(st, T + "GenerateDataKey", {"KeyId": key_id, "KeySpec": "AES_256"})
    _check("gen-data-key 200", dk.status == 200)
    plain_dk = _b64(dk.body["Plaintext"])
    _check("data key is 32 bytes", len(plain_dk) == 32)
    dk_round = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": dk.body["CiphertextBlob"]})
    _check("data key blob decrypts to the plaintext data key", _b64(dk_round.body["Plaintext"]) == plain_dk)

    # 6b. GenerateDataKeyWithoutPlaintext omits Plaintext
    dkw = kms.dispatch(st, T + "GenerateDataKeyWithoutPlaintext", {"KeyId": key_id})
    _check("gen-data-key-without-plaintext has no Plaintext", "Plaintext" not in dkw.body)
    _check("gen-data-key-without-plaintext has CiphertextBlob", bool(dkw.body.get("CiphertextBlob")))

    # 7. GenerateRandom -> N random bytes, no key needed
    rnd = kms.dispatch(st, T + "GenerateRandom", {"NumberOfBytes": 16})
    _check("generate-random 16 bytes", len(_b64(rnd.body["Plaintext"])) == 16)

    # 8. DescribeKey by KeyId
    desc = kms.dispatch(st, T + "DescribeKey", {"KeyId": key_id})
    _check("describe KeyId matches", desc.body["KeyMetadata"]["KeyId"] == key_id)

    # 9. Aliases: create, list, encrypt VIA the alias, describe VIA the alias
    kms.dispatch(st, T + "CreateAlias", {"AliasName": "alias/app-key", "TargetKeyId": key_id})
    al = kms.dispatch(st, T + "ListAliases", {})
    names = [a["AliasName"] for a in al.body["Aliases"]]
    _check("alias listed", "alias/app-key" in names)
    enc_alias = kms.dispatch(st, T + "Encrypt", {"KeyId": "alias/app-key", "Plaintext": base64.b64encode(b"via alias").decode()})
    _check("encrypt via alias 200", enc_alias.status == 200)
    dec_alias = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": enc_alias.body["CiphertextBlob"]})
    _check("decrypt via alias round-trips", _b64(dec_alias.body["Plaintext"]) == b"via alias")
    desc_alias = kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/app-key"})
    _check("describe via alias resolves to key", desc_alias.body["KeyMetadata"]["KeyId"] == key_id)

    # 10. DisableKey -> Encrypt fails KMSInvalidStateException; EnableKey -> works again
    kms.dispatch(st, T + "DisableKey", {"KeyId": key_id})
    disabled = kms.dispatch(st, T + "Encrypt", {"KeyId": key_id, "Plaintext": base64.b64encode(b"x").decode()})
    _check("encrypt on disabled key 400", disabled.status == 400)
    _check("encrypt on disabled key KMSInvalidStateException", disabled.body["__type"] == "KMSInvalidStateException")
    kms.dispatch(st, T + "EnableKey", {"KeyId": key_id})
    reenabled = kms.dispatch(st, T + "Encrypt", {"KeyId": key_id, "Plaintext": base64.b64encode(b"x").decode()})
    _check("encrypt after re-enable 200", reenabled.status == 200)

    # 11. ScheduleKeyDeletion -> PendingDeletion + DeletionDate; Encrypt then fails
    sched = kms.dispatch(st, T + "ScheduleKeyDeletion", {"KeyId": key_id, "PendingWindowInDays": 7})
    _check("schedule deletion KeyState PendingDeletion", sched.body["KeyState"] == "PendingDeletion")
    _check("schedule deletion has DeletionDate", "DeletionDate" in sched.body)
    pend = kms.dispatch(st, T + "Encrypt", {"KeyId": key_id, "Plaintext": base64.b64encode(b"x").decode()})
    _check("encrypt on pending-deletion key fails", pend.body["__type"] == "KMSInvalidStateException")

    # 12. ListKeys contains both keys
    lk = kms.dispatch(st, T + "ListKeys", {})
    listed = {k["KeyId"] for k in lk.body["Keys"]}
    _check("list-keys has both", key_id in listed and key2 in listed)

    # 13. NotFoundException for an unknown key; MissingAction for empty target
    nf = kms.dispatch(st, T + "DescribeKey", {"KeyId": "does-not-exist"})
    _check("missing key NotFoundException", nf.body["__type"] == "NotFoundException")
    noact = kms.dispatch(st, "", {})
    _check("missing target MissingAction", noact.body["__type"] == "MissingAction")

    print("\nRESULT: PASS — KMS core conforms (native wire semantics, real crypto) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
