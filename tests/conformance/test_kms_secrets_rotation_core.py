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
