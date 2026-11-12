"""KMS key rotation + Secrets Manager RotateSecret conformance (v2.6.0)."""
import base64

try:
    from core.kms_keystore import InMemoryKeyStore
    from core.kv_store import InMemoryKvStore
    from core import kms_core as kms, secrets_core as sec
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    from kv_store import InMemoryKvStore  # type: ignore
    import kms_core as kms  # type: ignore
    import secrets_core as sec  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    # ── KMS rotation ──────────────────────────────────────────────────────
    ks = InMemoryKeyStore()
    kid = kms.dispatch(ks, "TrentService.CreateKey", {}).body["KeyMetadata"]["KeyId"]
    _check("rotation off by default",
           kms.dispatch(ks, "TrentService.GetKeyRotationStatus", {"KeyId": kid}).body["KeyRotationEnabled"] is False)
    kms.dispatch(ks, "TrentService.EnableKeyRotation", {"KeyId": kid})
    r = kms.dispatch(ks, "TrentService.GetKeyRotationStatus", {"KeyId": kid}).body
    _check("EnableKeyRotation → enabled + period", r["KeyRotationEnabled"] is True and r["RotationPeriodInDays"] == 365)

    ct = kms.dispatch(ks, "TrentService.Encrypt",
                      {"KeyId": kid, "Plaintext": base64.b64encode(b"secret").decode()}).body["CiphertextBlob"]
    kms.dispatch(ks, "TrentService.RotateKeyOnDemand", {"KeyId": kid})
    pt = kms.dispatch(ks, "TrentService.Decrypt", {"CiphertextBlob": ct}).body["Plaintext"]
    _check("ciphertext still decrypts after RotateKeyOnDemand", base64.b64decode(pt) == b"secret")
    kms.dispatch(ks, "TrentService.DisableKeyRotation", {"KeyId": kid})
    _check("DisableKeyRotation → disabled",
           kms.dispatch(ks, "TrentService.GetKeyRotationStatus", {"KeyId": kid}).body["KeyRotationEnabled"] is False)

    # ── automatic rotation really fires (lazy, on next touch — no background
    # scheduler, same pattern as Secrets Manager / DynamoDB TTL) ────────────
    kms.dispatch(ks, "TrentService.EnableKeyRotation", {"KeyId": kid, "RotationPeriodInDays": 90})
    ct2 = kms.dispatch(ks, "TrentService.Encrypt",
                       {"KeyId": kid, "Plaintext": base64.b64encode(b"before-auto-rotation").decode()}).body["CiphertextBlob"]
    before = kms.dispatch(ks, "TrentService.DescribeKey", {"KeyId": kid}).body["KeyMetadata"]["KeyMaterialId"]
    ks.get_key(kid)["LastRotationDate"] -= 91 * 86400  # backdate past the period, like the GCS lifecycle conformance test
    after = kms.dispatch(ks, "TrentService.DescribeKey", {"KeyId": kid}).body["KeyMetadata"]
    _check("past-due period auto-rotates on next touch", after["KeyMaterialId"] != before)
    rotations = kms.dispatch(ks, "TrentService.ListKeyRotations", {"KeyId": kid}).body["Rotations"]
    _check("auto rotation recorded as AWS_KMS_AUTOMATIC", rotations[-1]["RotationType"] == "AWS_KMS_AUTOMATIC")
    pt2 = kms.dispatch(ks, "TrentService.Decrypt", {"CiphertextBlob": ct2}).body["Plaintext"]
    _check("ciphertext from before auto-rotation still decrypts", base64.b64decode(pt2) == b"before-auto-rotation")
    not_due = kms.dispatch(ks, "TrentService.DescribeKey", {"KeyId": kid}).body["KeyMetadata"]["KeyMaterialId"]
    _check("does not re-rotate again before the next period is due", not_due == after["KeyMaterialId"])

    # ── AWS managed keys always rotate automatically, non-configurable ─────
    mkid = kms.dispatch(ks, "TrentService.Encrypt",
                        {"KeyId": "alias/aws/rotationtest", "Plaintext": base64.b64encode(b"x").decode()}
                        ).body["KeyId"]
    mstatus = kms.dispatch(ks, "TrentService.GetKeyRotationStatus", {"KeyId": mkid}).body
    _check("AWS managed key rotation is on by default", mstatus["KeyRotationEnabled"] is True and mstatus["RotationPeriodInDays"] == 365)
    blocked = kms.dispatch(ks, "TrentService.DisableKeyRotation", {"KeyId": mkid})
    _check("DisableKeyRotation on an AWS managed key is rejected",
           blocked.body.get("__type") == "UnsupportedOperationException")

    # ── Secrets rotation ──────────────────────────────────────────────────
    kv = InMemoryKvStore()
    sec.dispatch(kv, "secretsmanager.CreateSecret", {"Name": "db", "SecretString": "p1"})
    cur1 = sec.dispatch(kv, "secretsmanager.GetSecretValue", {"SecretId": "db"}).body["VersionId"]
    newvid = sec.dispatch(kv, "secretsmanager.RotateSecret", {"SecretId": "db"}).body["VersionId"]
    _check("RotateSecret creates a new version", newvid != cur1)
    _check("old version demoted to AWSPREVIOUS",
           sec.dispatch(kv, "secretsmanager.GetSecretValue", {"SecretId": "db", "VersionStage": "AWSPREVIOUS"}).body["VersionId"] == cur1)
    _check("new version is AWSCURRENT",
           sec.dispatch(kv, "secretsmanager.GetSecretValue", {"SecretId": "db", "VersionStage": "AWSCURRENT"}).body["VersionId"] == newvid)

    print("\nKMS + Secrets rotation conformance: ALL GREEN")


if __name__ == "__main__":
    run()
