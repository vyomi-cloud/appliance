"""Azure Key Vault keys — wrap/unwrap + sign/verify conformance (v2.6.0)."""
import base64
import hashlib
import json

try:
    from core.kms_keystore import InMemoryKeyStore
    from core import azure_keyvault_keys_core as kv
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import azure_keyvault_keys_core as kv  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _b64u(x):
    return base64.urlsafe_b64encode(x).decode().rstrip("=")


def _unb64u(x):
    return base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))


def run(store=None):
    s = store or InMemoryKeyStore()

    def call(path, body):
        return json.loads(kv.dispatch(s, "POST", path, {}, {}, json.dumps(body).encode()).body)

    ver = call("/keys/mykey/create", {"kty": "RSA", "key_size": 2048})["key"]["kid"].split("/")[-1]

    secret = b"a-256-bit-symmetric-key-abcdefgh"
    wrapped = call(f"/keys/mykey/{ver}/wrapkey", {"alg": "RSA-OAEP", "value": _b64u(secret)})["value"]
    unwrapped = call(f"/keys/mykey/{ver}/unwrapkey", {"alg": "RSA-OAEP", "value": wrapped})["value"]
    _check("wrapkey → unwrapkey round-trips", _unb64u(unwrapped) == secret)

    digest = hashlib.sha256(b"the message").digest()
    sig = call(f"/keys/mykey/{ver}/sign", {"alg": "RS256", "value": _b64u(digest)})["value"]
    _check("sign → verify true",
           call(f"/keys/mykey/{ver}/verify", {"alg": "RS256", "digest": _b64u(digest), "value": sig})["value"] is True)
    _check("tampered signature → verify false",
           call(f"/keys/mykey/{ver}/verify", {"alg": "RS256", "digest": _b64u(digest), "value": _b64u(b"x" * 32)})["value"] is False)

    print("\nAzure KV keys wrap/unwrap + sign/verify conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
