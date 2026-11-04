"""v4 C0f — behaviours ported from the retired offline Lambda / Key Vault handlers into the
shared cores, and the upgrade path.

The offline appliance's Lambda REST (server.py `_lambda_*` + routes/aws_lambda.py, snake_case
records) and its Vault-only Key Vault data plane (core/vault_routes.py) now run on
core/lambda_core.py and core/azure_keyvault_{secrets,keys,certificates}_core.py; ACR runs on
core/azure_acr_core.py. Every legacy behaviour the cores lacked — and that the real services
also have — was ported; this suite pins each one on the in-memory substrate AND the
file-backed (sqlite) substrate (a fresh store instance must see the state).

The last section exercises the appliance upgrade path (core/appliance_stores.py: converting
pre-v4 Lambda functions / layers in place, adopting pre-v4 Vault-backed Key Vault secrets and
RSA keys) — host only, skipped where the appliance modules don't import.

Run:  PYTHONPATH=. python3 tests/conformance/test_c0f_legacy_parity_core.py
"""
import base64
import io
import json
import zipfile

from core import azure_acr_core as acr
from core import azure_keyvault_certificates_core as kvc
from core import azure_keyvault_keys_core as kvk
from core import azure_keyvault_secrets_core as kvs
from core import lambda_core as lam
from core.kms_keystore import InMemoryKeyStore
from core.kv_store import InMemoryKvStore
from core.persistent_store import PersistentKeyStore, PersistentKvStore, SqliteStateBackend

API = {"api-version": "7.4"}
F = "/2015-03-31/functions"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


# ── substrates ───────────────────────────────────────────────────────────────────────
class _LamStore:
    """A lambda_core store; with a backend, its `_lambda_*` collections write through."""
    _ATTRS = ("_lambda_functions", "_lambda_layers", "_lambda_esms")

    def __init__(self, backend=None, sid="lam"):
        self._be, self._sid = backend, sid
        if backend is not None:
            for k, v in backend.load(sid).items():
                setattr(self, k, v)

    def persist(self):
        if self._be is not None:
            self._be.save(self._sid, {a: getattr(self, a) for a in self._ATTRS if hasattr(self, a)})


class _AcrStore(acr.AcrRegistryStore):
    def __init__(self, backend=None, sid="acr"):
        super().__init__()
        self._be, self._sid = backend, sid
        if backend is not None:
            self.repos = backend.load(sid).get("repos", {})

    def save(self):
        if self._be is not None:
            self._be.save(self._sid, {"repos": self.repos})


def _memory(kind):
    def make(reload=False):
        if reload:
            return None
        return {"lam": _LamStore, "kv": InMemoryKvStore, "key": InMemoryKeyStore, "acr": _AcrStore}[kind]()
    return make


def _sqlite(kind):
    be = SqliteStateBackend(":memory:")

    def make(reload=False):
        if kind == "lam":
            return _LamStore(be)
        if kind == "kv":
            return PersistentKvStore(be, store_id="c0f-kv")
        if kind == "key":
            return PersistentKeyStore(be, store_id="c0f-key")
        return _AcrStore(be)
    return make


def _zip(src, mod="app.py"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(mod, src)
        z.writestr("README.txt", "not code")
    return base64.b64encode(b.getvalue()).decode()


def _l(st, method, path, body=None, headers=None, query=None):
    r = lam.dispatch(st, method, path, query or {}, headers or {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return r.status, (json.loads(r.body) if r.body else {}), r.headers
    except Exception:
        return r.status, r.body, r.headers


# ── Lambda ───────────────────────────────────────────────────────────────────────────
def lambda_parity(make, label):
    st = make()
    s, b, _ = _l(st, "POST", F, {"FunctionName": "bad name!", "Code": {"Source": "x"}})
    _check(f"[{label}] CreateFunction validates the name (InvalidParameterValueException)", s == 400)
    src = "import json\ndef handler(e, c):\n    print('log-line')\n    return {'k': e.get('k')}\n"
    s, b, _ = _l(st, "POST", F, {"FunctionName": "zipfn", "Handler": "app.handler", "Code": {"ZipFile": _zip(src)}})
    _check(f"[{label}] CreateFunction accepts a real .zip deployment package", s == 201 and b["CodeSize"] == len(src))
    s, b, _ = _l(st, "GET", F + "/arn:aws:lambda:us-east-1:123456789012:function:zipfn")
    _check(f"[{label}] GetFunction by full ARN", s == 200 and b["Configuration"]["FunctionName"] == "zipfn")
    s, b, h = _l(st, "POST", F + "/zipfn/invocations", {"k": 3}, headers={"X-Amz-Log-Type": "Tail"})
    _check(f"[{label}] Invoke + LogType=Tail returns X-Amz-Log-Result", s == 200 and b == {"k": 3}
           and "X-Amz-Log-Result" in h)
    s, b, h = _l(st, "POST", F + "/zipfn/invocations", {}, headers={"X-Amz-Invocation-Type": "Event"})
    _check(f"[{label}] InvocationType=Event → 202, empty body", s == 202 and b == {})
    s, b, h = _l(st, "POST", F + "/zipfn/invocations", {}, headers={"X-Amz-Invocation-Type": "DryRun"})
    _check(f"[{label}] InvocationType=DryRun → 204", s == 204)
    _l(st, "PUT", F + "/zipfn/code", {"ZipFile": _zip("def handler(e, c):\n    raise ValueError('no')\n")})
    s, b, h = _l(st, "POST", F + "/zipfn/invocations", {})
    _check(f"[{label}] function error → 200 + X-Amz-Function-Error + errorType",
           s == 200 and h.get("X-Amz-Function-Error") == "Unhandled" and b["errorType"] == "ValueError")
    s, b, _ = _l(st, "POST", F + "/zipfn/policy", {"StatementId": "s3", "Action": "lambda:InvokeFunction",
                                                  "Principal": "s3.amazonaws.com", "SourceArn": "arn:aws:s3:::bkt",
                                                  "SourceAccount": "123456789012"})
    stmt = json.loads(b["Statement"])
    _check(f"[{label}] AddPermission keeps Principal + SourceArn / SourceAccount conditions",
           stmt["Principal"] == {"Service": "s3.amazonaws.com"}
           and stmt["Condition"]["ArnLike"]["AWS:SourceArn"] == "arn:aws:s3:::bkt")
    fn = lam._functions(st)["zipfn"]
    _check(f"[{label}] can_invoke: matching service source allowed",
           lam.can_invoke(fn, "s3.amazonaws.com", "arn:aws:s3:::bkt", "123456789012"))
    _check(f"[{label}] can_invoke: other source denied, direct caller allowed",
           not lam.can_invoke(fn, "sns.amazonaws.com", "arn:aws:sns:x", "") and lam.can_invoke(fn))
    s, b, _ = _l(st, "POST", "/2015-03-31/layers/lib/versions", {"Content": {"Source": "X = 1\n"}})
    _check(f"[{label}] PublishLayerVersion keeps the layer source (merged into a real runtime)",
           s == 201 and lam._layers(st)["lib"]["versions"][1]["Source"] == "X = 1\n")
    seen = {}
    st.run_function = lambda f, e, c: (seen.update(fn=f["name"], ctx=c), {"ok": True, "result": "real", "logs": "hi\n"})[1]
    s, b, h = _l(st, "POST", F + "/zipfn/invocations", {"a": 1})
    _check(f"[{label}] runtime seam: store.run_function runs the code (not the sandbox)",
           b == "real" and seen["fn"] == "zipfn" and seen["ctx"]["function_name"] == "zipfn")
    _check(f"[{label}] runtime logs recorded on the invocation", lam._functions(st)["zipfn"]["invocations"][0]["LogTail"] == "hi\n")
    del st.run_function
    _check(f"[{label}] invoke_by_arn reaches the function by ARN (qualified)",
           lam.invoke_by_arn(st, lam._fn_arn("zipfn") + ":$LATEST", {"x": 1}) and not lam.invoke_by_arn(st, "nope", {}))
    st2 = make(reload=True)
    if st2 is not None:
        _check(f"[{label}] a fresh store sees function, policy, layer, invocations",
               "zipfn" in lam._functions(st2) and lam._functions(st2)["zipfn"]["policy_statements"]
               and "lib" in lam._layers(st2) and lam._functions(st2)["zipfn"]["invocations"])


# ── Key Vault ────────────────────────────────────────────────────────────────────────
def _k(mod, st, method, path, body=None, headers=None):
    r = mod.dispatch(st, method, path, API, headers or {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, (json.loads(r.body) if r.body else {}), r.headers


def keyvault_parity(make_kv, make_key, label):
    sec, cert, key = make_kv(), make_kv(), make_key()
    sdk = {"x-ms-client-request-id": "1", "user-agent": "azsdk-python-keyvault-keys/4"}
    s, _, h = _k(kvk, key, "POST", "/keys/k/create", {"kty": "RSA"}, headers=sdk)
    _check(f"[{label}] keys: SDK probe without a token → 401 challenge (as secrets / certificates)",
           s == 401 and "www-authenticate" in h)
    s, b, _ = _k(kvk, key, "POST", "/keys/k/create", {"kty": "RSA", "key_size": 2048, "tags": {"a": "b"}})
    ver = b["key"]["kid"].rsplit("/", 1)[1]
    _check(f"[{label}] keys: create (tags kept)", s == 200 and b.get("tags") == {"a": "b"})
    pt = base64.urlsafe_b64encode(b"hello").decode().rstrip("=")
    s, e, _ = _k(kvk, key, "POST", "/keys/k/encrypt", {"alg": "RSA-OAEP", "value": pt})
    s2, d, _ = _k(kvk, key, "POST", f"/keys/k/{ver}/decrypt", {"alg": "RSA-OAEP", "value": e["value"]})
    _check(f"[{label}] keys: versionless encrypt → versioned decrypt round-trips", s == 200 and d["value"] == pt)
    s, b, _ = _k(kvk, key, "PATCH", "/keys/k", {"attributes": {"enabled": False}})
    _check(f"[{label}] keys: UpdateKeyProperties (PATCH) disables", s == 200 and b["attributes"]["enabled"] is False)
    if b["key"]["n"] and kvk._rsa_mod():
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.hazmat.primitives import hashes
        n = int.from_bytes(base64.urlsafe_b64decode(b["key"]["n"] + "=="), "big")
        pub = rsa.RSAPublicNumbers(65537, n).public_key()
        ct = pub.encrypt(b"client-side", padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
        s, d, _ = _k(kvk, key, "POST", f"/keys/k/{ver}/decrypt",
                     {"alg": "RSA-OAEP", "value": base64.urlsafe_b64encode(ct).decode().rstrip("=")})
        _check(f"[{label}] keys: real RSA — client-side encrypt with (n, e) decrypts on the service",
               s == 200 and base64.urlsafe_b64decode(d["value"] + "==") == b"client-side")
    s, b, _ = _k(kvs, sec, "PUT", "/secrets/s1", {"value": "v1"})
    _k(kvs, sec, "PUT", "/secrets/s1", {"value": "v2"})
    _check(f"[{label}] secrets: set twice → current = v2", _k(kvs, sec, "GET", "/secrets/s1")[1]["value"] == "v2")
    s, b, _ = _k(kvc, cert, "POST", "/certificates/c1/create", {"policy": {}}, headers={**sdk, "authorization": "Bearer x"})
    _check(f"[{label}] certificates: SDK create → 202 completed CertificateOperation",
           s == 202 and b["status"] == "completed" and b["id"].endswith("/certificates/c1/pending"))
    s, b, _ = _k(kvc, cert, "GET", "/certificates/c1/pending")
    _check(f"[{label}] certificates: GET …/pending", s == 200 and b["status"] == "completed")
    s, b, _ = _k(kvc, cert, "POST", "/certificates/c2/create", {"policy": {}})
    _check(f"[{label}] certificates: non-SDK create keeps 200 + bundle", s == 200 and b.get("x5t"))


def acr_parity(make, label):
    st = make()
    r = acr.dispatch(st, "PUT", "/v2/app/manifests/v1", {}, {"content-type": "application/vnd.oci.image.manifest.v1+json"}, b'{"schemaVersion":2}')
    if hasattr(st, "save"):
        st.save()
    _check(f"[{label}] ACR: manifest push → 201 + digest", r.status == 201 and r.headers.get("docker-content-digest", "").startswith("sha256:"))
    st2 = make(reload=True)
    if st2 is not None:
        r = acr.dispatch(st2, "GET", "/v2/app/manifests/v1", {}, {}, b"")
        _check(f"[{label}] ACR: a fresh store pulls the manifest bytes", r.status == 200 and r.body == b'{"schemaVersion":2}')


# ── upgrade path (appliance only) ───────────────────────────────────────────────────
def upgrade_path():
    try:
        from core import appliance_stores as aps
    except Exception as exc:   # pragma: no cover - not on Pyodide
        print(f"  skip upgrade path ({exc})")
        return
    legacy = {"function_name": "old", "function_arn": "arn:aws:lambda:us-east-1:123456789012:function:old",
              "runtime": "python3.12", "handler": "lambda_function.lambda_handler",
              "code": "def lambda_handler(e, c):\n    return 1\n", "environment": {"A": "1"},
              "timeout": 7, "memory_size": 256, "description": "pre-v4", "created": "2026-10-01T10:00:00Z",
              "last_modified": "2026-10-02T10:00:00Z", "tags": [{"Key": "team", "Value": "x"}],
              "permissions": [{"statement_id": "s3", "principal": "s3.amazonaws.com", "action": "lambda:InvokeFunction",
                               "source_arn": "arn:aws:s3:::b", "source_account": ""}],
              "versions": [{"version": "$LATEST"}, {"version": "1", "description": "v1", "created": "2026-10-01T11:00:00Z"}],
              "invocations": [{"id": "i1", "at": "2026-10-02T09:00:00Z", "status": "error", "stdout": "out", "error": "boom"}]}
    slot = {"functions": {"old": legacy}, "layers": {"lib": {"layer_name": "lib", "code": "Y=2\n", "latest_version": 3,
                                                               "runtime": "python3.12", "created": "2026-10-01T10:00:00Z"}}}
    n = aps.adopt_legacy_lambda(slot)
    fn = slot["functions"]["old"]
    _check("[upgrade] pre-v4 function + layer converted in place", n == 2 and fn["source"].startswith("def lambda_handler"))
    _check("[upgrade] config / env / tags carried", fn["env"] == {"A": "1"} and fn["timeout"] == 7
           and fn["memory_size"] == 256 and fn["tags"] == {"team": "x"} and fn["description"] == "pre-v4")
    _check("[upgrade] permissions → policy statements with SourceArn",
           fn["policy_statements"]["s3"]["Condition"]["ArnLike"]["AWS:SourceArn"] == "arn:aws:s3:::b")
    _check("[upgrade] numeric versions kept, next_version continues", "1" in fn["versions"] and fn["next_version"] == 2)
    _check("[upgrade] recent invocations kept (error + logs)", fn["invocations"][0]["Error"] and fn["invocations"][0]["LogTail"] == "out")
    _check("[upgrade] layer → core layer version with its source", slot["layers"]["lib"]["versions"][3]["Source"] == "Y=2\n")
    s, b, _ = _l(type("S", (), {"_lambda_functions": slot["functions"], "_lambda_layers": slot["layers"]})(), "GET", F + "/old")
    _check("[upgrade] the converted record is served natively", s == 200 and b["Configuration"]["Handler"] == "lambda_function.lambda_handler")
    _check("[upgrade] idempotent (second pass converts nothing)", aps.adopt_legacy_lambda(slot) == 0)

    class FakeVault:
        def __init__(self):
            self.kv = {"__idx__v1__secrets": {"data": {"value": json.dumps(["db"])}},
                       "v1__db": {"data": {"value": "pw"}},
                       "__idx__v2__secrets": {"data": {"value": json.dumps(["db", "api"])}},
                       "v2__db": {"data": {"value": "other"}}, "v2__api": {"data": {"value": "k"}}}

        def kv_get(self, provider, space, name, version=None):
            return self.kv.get(name)
    if kvk._rsa_mod():
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    else:
        pem = None
    fv = FakeVault()
    if pem:
        fv.kv["__idx__v1__keys"] = {"data": {"value": json.dumps(["rsa1"])}}
        fv.kv["v1__rsa1__rsapriv"] = {"data": {"value": pem}}
    kslot = {"secrets": {}, "keys": {}, "material": {}}
    n = aps.adopt_legacy_keyvault(kslot, "sp", ["v1", "v2"], fv)
    _check("[upgrade] Vault secrets adopted; a name in two vaults keeps the first vault's value",
           kslot["secrets"]["db"]["versions"][kslot["secrets"]["db"]["current"]]["value"] == "pw"
           and "api" in kslot["secrets"])
    st = InMemoryKvStore()
    st.secrets = kslot["secrets"]
    _check("[upgrade] adopted secret served by the core", _k(kvs, st, "GET", "/secrets/api")[1]["value"] == "k")
    if pem:
        ks = InMemoryKeyStore()
        ks.keys, ks.material = kslot["keys"], kslot["material"]
        pt = base64.urlsafe_b64encode(b"x").decode().rstrip("=")
        e = _k(kvk, ks, "POST", "/keys/rsa1/encrypt", {"alg": "RSA-OAEP", "value": pt})[1]
        d = _k(kvk, ks, "POST", "/keys/rsa1/decrypt", {"alg": "RSA-OAEP", "value": e["value"]})[1]
        _check("[upgrade] pre-v4 RSA key (Vault PEM) adopted as a real RSA key", d["value"] == pt and n == 3)


def run() -> int:
    print("Lambda:")
    lambda_parity(_memory("lam"), "mem")
    lambda_parity(_sqlite("lam"), "sqlite")
    print("Key Vault:")
    keyvault_parity(_memory("kv"), _memory("key"), "mem")
    keyvault_parity(_sqlite("kv"), _sqlite("key"), "sqlite")
    print("Container Registry:")
    acr_parity(_memory("acr"), "mem")
    acr_parity(_sqlite("acr"), "sqlite")
    print("Upgrade path:")
    upgrade_path()
    print("\nC0f legacy-parity (Lambda / Key Vault / ACR cores): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
