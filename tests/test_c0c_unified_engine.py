"""v4 C0c — the offline appliance serves native AWS KMS and Secrets Manager through the
shared conformance cores (core/kms_core.py, core/secrets_core.py), over ONE state shared
with the classic console REST, durably, with no Vault.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state file,
like tests/test_c0_unified_engine.py.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0c-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")      # no Vault

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

SIG = ("AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/{svc}/aws4_request, "
       "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64)


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _kms(client, op, body, prefix=""):
    return client.post(prefix + "/", content=json.dumps(body), headers={
        "Authorization": SIG.format(svc="kms"), "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": f"TrentService.{op}"})


def _sm(client, op, body, prefix=""):
    return client.post(prefix + "/", content=json.dumps(body), headers={
        "Authorization": SIG.format(svc="secretsmanager"), "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": f"secretsmanager.{op}"})


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _first_route(path: str, method: str):
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"", "headers": []}
    for r in server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return r
    return None


def test_route_precedence(client):
    for p in ("/api/aws/secrets", "/api/aws/secrets/x", "/api/aws/kms/keys", "/api/aws/kms/keys/k"):
        assert _first_route(p, "GET").endpoint.__module__ == "routes.aws_secrets_kms_unified", p
    assert _first_route("/api/aws/secrets", "POST").endpoint.__module__ == "routes.aws_secrets_kms_unified"
    assert _first_route("/api/aws/kms/keys/k", "DELETE").endpoint.__module__ == "routes.aws_secrets_kms_unified"
    # the native wire: POST / is the root dispatcher, which hands kms / secretsmanager to the cores
    assert _first_route("/", "POST").endpoint.__name__ == "aws_query_root"


def test_kms_wire_without_vault(client):
    """Pre-v4 without Vault: Encrypt → {"CiphertextBlob": ""}. Now real ciphertext."""
    k = _kms(client, "CreateKey", {"Description": "c0c"})
    assert k.status_code == 200, k.text
    kid = k.json()["KeyMetadata"]["KeyId"]
    alias = "alias/" + _u("app")
    assert _kms(client, "CreateAlias", {"AliasName": alias, "TargetKeyId": kid}).status_code == 200
    enc = _kms(client, "Encrypt", {"KeyId": alias, "Plaintext": _b64(b"hello")}).json()
    assert enc["CiphertextBlob"] and enc["KeyId"].endswith(f":key/{kid}")
    dec = _kms(client, "Decrypt", {"CiphertextBlob": enc["CiphertextBlob"]})
    assert dec.status_code == 200 and base64.b64decode(dec.json()["Plaintext"]) == b"hello"
    assert dec.headers["content-type"].startswith("application/x-amz-json-1.1")
    assert dec.headers.get("x-amzn-requestid")
    gdk = _kms(client, "GenerateDataKey", {"KeyId": kid, "KeySpec": "AES_256"}).json()
    assert len(base64.b64decode(gdk["Plaintext"])) == 32
    back = _kms(client, "Decrypt", {"CiphertextBlob": gdk["CiphertextBlob"]}).json()
    assert back["Plaintext"] == gdk["Plaintext"]
    # error shape + status (real AWS: 400 + __type)
    nf = _kms(client, "Encrypt", {"KeyId": "alias/nope-" + uuid.uuid4().hex[:6], "Plaintext": _b64(b"x")})
    assert nf.status_code == 400 and nf.json()["__type"] == "NotFoundException"
    _kms(client, "DisableKey", {"KeyId": kid})
    dis = _kms(client, "Encrypt", {"KeyId": kid, "Plaintext": _b64(b"x")})
    assert dis.status_code == 400 and dis.json()["__type"] == "DisabledException"
    _kms(client, "EnableKey", {"KeyId": kid})


def test_kms_aws_managed_alias_auto_provisions(client):
    svc = "c0c" + uuid.uuid4().hex[:6]
    r = _kms(client, "Encrypt", {"KeyId": f"alias/aws/{svc}", "Plaintext": _b64(b"x")}, prefix="/_wire")
    assert r.status_code == 200, r.text
    md = _kms(client, "DescribeKey", {"KeyId": f"alias/aws/{svc}"}).json()["KeyMetadata"]
    assert md["KeyManager"] == "AWS" and md["KeyState"] == "Enabled"
    aliases = {a["AliasName"] for a in _kms(client, "ListAliases", {}).json()["Aliases"]}
    assert f"alias/aws/{svc}" in aliases
    # AWS managed keys are not "Customer managed keys" in the classic console
    assert md["KeyId"] not in {r["key_id"] for r in client.get("/api/aws/kms/keys").json()["items"]}


def test_kms_native_and_console_share_state(client):
    # console → native
    name = _u("console-key")
    c = client.post("/api/aws/kms/keys", json={"name": name, "description": "from console"}).json()
    assert c["ok"] and c["alias"] == f"alias/{name}"
    md = _kms(client, "DescribeKey", {"KeyId": f"alias/{name}"}).json()["KeyMetadata"]
    assert md["KeyId"] == c["key_id"] and md["Description"] == "from console"
    up = client.put(f"/api/aws/kms/keys/{c['key_id']}", json={"description": "edited", "enabled": False}).json()
    assert up["state"] == "Disabled"
    md = _kms(client, "DescribeKey", {"KeyId": c["key_id"]}).json()["KeyMetadata"]
    assert md["Description"] == "edited" and md["KeyState"] == "Disabled"
    # native → console
    kid = _kms(client, "CreateKey", {"Description": "native"}).json()["KeyMetadata"]["KeyId"]
    rows = {r["key_id"]: r for r in client.get("/api/aws/kms/keys").json()["items"]}
    assert rows[kid]["description"] == "native" and rows[kid]["state"] == "Enabled"
    assert client.get(f"/api/aws/kms/keys/{kid}").json()["key_id"] == kid
    assert client.get("/api/aws/kms/keys/" + uuid.uuid4().hex).status_code == 404
    d = client.delete(f"/api/aws/kms/keys/{kid}").json()
    assert d["scheduled"]
    assert _kms(client, "DescribeKey", {"KeyId": kid}).json()["KeyMetadata"]["KeyState"] == "PendingDeletion"


def test_secrets_wire_without_vault(client):
    """Pre-v4 without Vault: ListSecrets → 500. Now the core."""
    assert _sm(client, "ListSecrets", {}).status_code == 200
    name = _u("db/pass")
    tok1 = str(uuid.uuid4())
    cr = _sm(client, "CreateSecret", {"Name": name, "SecretString": "v1", "ClientRequestToken": tok1})
    assert cr.status_code == 200 and cr.json()["VersionId"] == tok1
    again = _sm(client, "CreateSecret", {"Name": name, "SecretString": "v1", "ClientRequestToken": tok1})
    assert again.status_code == 200 and again.json()["VersionId"] == tok1        # idempotent retry
    dup = _sm(client, "CreateSecret", {"Name": name, "SecretString": "v1"})
    assert dup.status_code == 400 and dup.json()["__type"] == "ResourceExistsException"
    pv = _sm(client, "PutSecretValue", {"SecretId": name, "SecretString": "v2"}, prefix="/_wire").json()
    got = _sm(client, "GetSecretValue", {"SecretId": name}).json()
    assert got["SecretString"] == "v2" and got["VersionId"] == pv["VersionId"]
    prev = _sm(client, "GetSecretValue", {"SecretId": name, "VersionStage": "AWSPREVIOUS"}).json()
    assert prev["SecretString"] == "v1"
    # UpdateSecret with only a description: no new version
    _sm(client, "UpdateSecret", {"SecretId": name, "Description": "d"})
    assert len(_sm(client, "ListSecretVersionIds", {"SecretId": name}).json()["Versions"]) == 2
    assert _sm(client, "DescribeSecret", {"SecretId": name}).json()["Description"] == "d"
    dl = _sm(client, "DeleteSecret", {"SecretId": name, "RecoveryWindowInDays": 7})
    assert dl.status_code == 200
    blocked = _sm(client, "GetSecretValue", {"SecretId": name})
    assert blocked.status_code == 400 and blocked.json()["__type"] == "InvalidRequestException"
    assert name not in [s["Name"] for s in _sm(client, "ListSecrets", {}).json()["SecretList"]]
    _sm(client, "RestoreSecret", {"SecretId": name})
    assert _sm(client, "GetSecretValue", {"SecretId": name}).json()["SecretString"] == "v2"


def test_secrets_native_and_console_share_state(client):
    name = _u("console-sec")
    assert client.post("/api/aws/secrets", json={"name": name, "value": "from-console"}).json()["ok"]
    assert _sm(client, "GetSecretValue", {"SecretId": name}).json()["SecretString"] == "from-console"
    _sm(client, "PutSecretValue", {"SecretId": name, "SecretString": "from-sdk"})
    assert client.get(f"/api/aws/secrets/{name}").json()["value"] == "from-sdk"
    rows = {r["name"]: r for r in client.get("/api/aws/secrets").json()["items"]}
    assert rows[name]["kms_key_id"] == "aws/secretsmanager" and rows[name]["created"]
    upd = client.put(f"/api/aws/secrets/{name}", json={"value": "edited"}).json()
    assert upd["updated"]
    assert _sm(client, "GetSecretValue", {"SecretId": name}).json()["SecretString"] == "edited"
    # native-created secret is in the console list
    n2 = _u("sdk-sec")
    _sm(client, "CreateSecret", {"Name": n2, "SecretString": "x"})
    assert n2 in {r["name"] for r in client.get("/api/aws/secrets").json()["items"]}
    # console delete removes it now (pre-v4 console behaviour)
    assert client.delete(f"/api/aws/secrets/{name}").json()["deleted"]
    assert client.get(f"/api/aws/secrets/{name}").status_code == 404
    gone = _sm(client, "DescribeSecret", {"SecretId": name})
    assert gone.status_code == 400 and gone.json()["__type"] == "ResourceNotFoundException"


def test_state_is_durable_in_the_kernel_store(client):
    """Keys (+ material), aliases, secrets (+ versions) live in the appliance state store
    the tier middleware flushes after each mutation — a restart reloads them, and the
    material is there, so pre-restart ciphertext still decrypts."""
    kid = _kms(client, "CreateKey", {}).json()["KeyMetadata"]["KeyId"]
    alias = "alias/" + _u("dur")
    _kms(client, "CreateAlias", {"AliasName": alias, "TargetKeyId": kid})
    blob = _kms(client, "Encrypt", {"KeyId": kid, "Plaintext": _b64(b"durable")}).json()["CiphertextBlob"]
    cks = _kms(client, "CreateCustomKeyStore", {"CustomKeyStoreName": _u("cks"),
                                                "CustomKeyStoreType": "EXTERNAL_KEY_STORE"}).json()
    sname = _u("dur-sec")
    _sm(client, "CreateSecret", {"Name": sname, "SecretString": "s"})
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    found = {"keys": {}, "mat": {}, "aliases": {}, "cks": {}, "sec": {}}
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        ss = sp.get("service_states") or {}
        kms = ss.get("kms") or {}
        found["keys"].update(kms.get("keys") or {})
        found["mat"].update(kms.get("material") or {})
        found["aliases"].update(kms.get("aliases") or {})
        found["cks"].update(kms.get("custom_key_stores") or {})
        found["sec"].update((ss.get("secretsmanager") or {}).get("secrets") or {})
    assert kid in found["keys"] and isinstance(found["mat"][kid], bytes)
    assert found["aliases"][alias] == kid
    assert cks["CustomKeyStoreId"] in found["cks"]
    assert found["sec"][sname]["versions"]
    # a fresh engine over the reloaded material decrypts the pre-"restart" ciphertext
    from core import kms_core
    from core.kms_keystore import InMemoryKeyStore
    fresh = InMemoryKeyStore()
    fresh.keys.update(found["keys"])
    fresh.material.update(found["mat"])
    out = kms_core.dispatch(fresh, "TrentService.Decrypt", {"CiphertextBlob": blob})
    assert out.status == 200 and base64.b64decode(out.body["Plaintext"]) == b"durable"


def test_legacy_opt_out_restores_the_vault_handlers(monkeypatch):
    from core import wire_ingress
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "s3,dynamodb,gcs")
    assert not wire_ingress.is_unified("kms") and not wire_ingress.is_unified("secretsmanager")
    from fastapi import FastAPI
    from core import vault_routes
    app, disp = FastAPI(), {}
    vault_routes.register(app, aws_dispatchers=disp)
    mods = {(r.path, getattr(r.endpoint, "__module__", "")) for r in app.routes if getattr(r, "endpoint", None)}
    assert ("/api/aws/secrets", "core.vault_routes") in mods
    assert ("/api/aws/kms/keys", "core.vault_routes") in mods
    assert disp["TrentService"] is vault_routes._aws_kms_dispatch
    monkeypatch.setenv("VYOMI_LEGACY_WIRE", "1")
    monkeypatch.delenv("VYOMI_UNIFIED_INGRESS_SERVICES")
    assert not wire_ingress.is_unified("kms")
    monkeypatch.delenv("VYOMI_LEGACY_WIRE")
    app2 = FastAPI()
    vault_routes.register(app2, aws_dispatchers={})
    mods2 = {(r.path, getattr(r.endpoint, "__module__", "")) for r in app2.routes if getattr(r, "endpoint", None)}
    assert ("/api/aws/secrets", "routes.aws_secrets_kms_unified") in mods2
    assert ("/api/aws/secrets", "core.vault_routes") not in mods2
    assert ("/api/aws/kms/keys", "core.vault_routes") not in mods2
