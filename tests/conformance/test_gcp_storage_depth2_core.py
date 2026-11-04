"""GCS depth-wave-5 sub-resources: the items in consoles/agent-queue/gcp-storage.json's
depth_targets that moved from config_only/not_simulated to a real, enforced "limited"
behaviour (see core/capabilities/gcp/storage.json):

  - permissions: setIamPolicy really REJECTS a binding granting allUsers /
    allAuthenticatedUsers while the bucket's public access prevention is enforced
  - cors: an OPTIONS preflight and a matching GET both carry real Access-Control-*
    response headers for a configured origin; a non-matching origin gets none
  - encryption (CMEK): defaultKmsKeyName must be a well-formed Cloud KMS CryptoKey
    resource name, and every new object written to the bucket is stamped with it
  - operations: the Turbo replication switch (rpo) is a real, listable
    /b/{bucket}/operations resource
  - interoperability: HMAC key issue/list/state-toggle/delete-when-INACTIVE round-trip
    under projects/{p}/hmacKeys

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_depth2_core.py
"""
import json

try:
    from core.object_store import InMemoryObjectStore
    from core import gcp_storage_core as gcs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import gcp_storage_core as gcs  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def _call(st, m, p, q=None, body=None, ct="application/json", headers=None):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    hdrs = {"content-type": ct, **(headers or {})}
    return gcs.dispatch(st, m, p, q or {}, hdrs, raw)


def run() -> int:
    st = InMemoryObjectStore()

    # 1. public access prevention is enforced on setIamPolicy
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {
        "name": "pap", "iamConfiguration": {"publicAccessPrevention": "enforced"}})
    bad = _call(st, "PUT", "/storage/v1/b/pap/iam", body={"bindings": [
        {"role": "roles/storage.objectViewer", "members": ["allUsers"]}]})
    _check("setIamPolicy rejects allUsers while PAP enforced", bad.status == 400
           and _j(bad)["error"]["errors"][0]["reason"] == "publicAccessPrevention")
    ok = _call(st, "PUT", "/storage/v1/b/pap/iam", body={"bindings": [
        {"role": "roles/storage.objectViewer", "members": ["user:dev@example.com"]}]})
    _check("setIamPolicy still allows a non-public binding", ok.status == 200)
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "nopap"})
    allowed = _call(st, "PUT", "/storage/v1/b/nopap/iam", body={"bindings": [
        {"role": "roles/storage.objectViewer", "members": ["allUsers"]}]})
    _check("allUsers allowed when PAP is not enforced", allowed.status == 200)

    # 2. CORS headers are now real
    cors_rule = [{"origin": ["https://example.com"], "method": ["GET"], "responseHeader": ["Content-Type"], "maxAgeSeconds": 600}]
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "cb", "cors": cors_rule})
    _call(st, "POST", "/upload/storage/v1/b/cb/o", {"uploadType": "media", "name": "a.txt"}, b"hi", "text/plain")
    pre = _call(st, "OPTIONS", "/storage/v1/b/cb/o/a.txt", headers={"Origin": "https://example.com"})
    _check("preflight 200 for matching origin", pre.status == 200)
    _check("preflight carries ACAO for matching origin", pre.headers.get("access-control-allow-origin") == "https://example.com")
    get = _call(st, "GET", "/storage/v1/b/cb/o/a.txt", headers={"Origin": "https://example.com"})
    _check("matching-origin GET carries CORS headers", get.headers.get("access-control-allow-origin") == "https://example.com")
    other = _call(st, "GET", "/storage/v1/b/cb/o/a.txt", headers={"Origin": "https://evil.example"})
    _check("non-matching origin gets no CORS header", "access-control-allow-origin" not in (other.headers or {}))
    nohdr = _call(st, "GET", "/storage/v1/b/cb/o/a.txt")
    _check("no Origin header -> no CORS header", "access-control-allow-origin" not in (nohdr.headers or {}))

    # 3. CMEK: shape-validated, stamped onto new objects
    bad_key = _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "cmek-bad", "encryption": {"defaultKmsKeyName": "not-a-key"}})
    _check("malformed CMEK key name rejected", bad_key.status == 400)
    key_name = "projects/p/locations/us/keyRings/r/cryptoKeys/k"
    good = _j(_call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "cmek", "encryption": {"defaultKmsKeyName": key_name}}))
    _check("CMEK key kept on bucket", good["encryption"]["defaultKmsKeyName"] == key_name)
    obj = _j(_call(st, "POST", "/upload/storage/v1/b/cmek/o", {"uploadType": "media", "name": "o.txt"}, b"data", "text/plain"))
    _check("new object stamped with bucket's CMEK key", obj.get("kmsKeyName") == key_name)
    cleared = _j(_call(st, "PATCH", "/storage/v1/b/cmek", body={"encryption": None}))
    _check("clearing CMEK removes it from the bucket view", "encryption" not in cleared)
    obj2 = _j(_call(st, "POST", "/upload/storage/v1/b/cmek/o", {"uploadType": "media", "name": "p.txt"}, b"data", "text/plain"))
    _check("object created after clearing CMEK has no kmsKeyName", "kmsKeyName" not in obj2)

    # 4. Operations: a real listable resource, recorded on a turbo-replication change
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "dualr", "location": "nam4"})
    empty_ops = _j(_call(st, "GET", "/storage/v1/b/dualr/operations"))
    _check("no operations before any rpo change", empty_ops["items"] == [])
    _call(st, "PATCH", "/storage/v1/b/dualr", body={"rpo": "ASYNC_TURBO"})
    ops = _j(_call(st, "GET", "/storage/v1/b/dualr/operations"))
    _check("turbo-replication change recorded as a DONE operation", len(ops["items"]) == 1
           and ops["items"][0]["done"] is True and ops["items"][0]["metadata"]["type"] == "ChangeTurboReplication")
    op_id = ops["items"][0]["name"].split("/")[-1]
    _check("operation get 200", _call(st, "GET", f"/storage/v1/b/dualr/operations/{op_id}").status == 200)
    _check("unknown operation 404", _call(st, "GET", "/storage/v1/b/dualr/operations/nope").status == 404)
    _call(st, "PATCH", "/storage/v1/b/dualr", body={"rpo": "DEFAULT"})
    ops2 = _j(_call(st, "GET", "/storage/v1/b/dualr/operations"))
    _check("switching back records a second operation", len(ops2["items"]) == 2)

    # 5. Interoperability: HMAC keys
    created = _j(_call(st, "POST", "/storage/v1/projects/p/hmacKeys", body={"serviceAccountEmail": "svc@p.iam.gserviceaccount.com"}))
    _check("create returns secret once", "secret" in created and created["metadata"]["state"] == "ACTIVE")
    access_id = created["metadata"]["accessId"]
    missing_sa = _call(st, "POST", "/storage/v1/projects/p/hmacKeys", body={})
    _check("missing serviceAccountEmail rejected", missing_sa.status == 400)
    listed = _j(_call(st, "GET", "/storage/v1/projects/p/hmacKeys"))
    _check("list has the key, no secret", any(k["accessId"] == access_id for k in listed["items"]) and "secret" not in listed["items"][0])
    got = _j(_call(st, "GET", f"/storage/v1/projects/p/hmacKeys/{access_id}"))
    _check("get by accessId", got["accessId"] == access_id)
    del_active = _call(st, "DELETE", f"/storage/v1/projects/p/hmacKeys/{access_id}")
    _check("cannot delete an ACTIVE key", del_active.status == 400)
    _call(st, "PUT", f"/storage/v1/projects/p/hmacKeys/{access_id}", body={"state": "INACTIVE"})
    _check("deleting an INACTIVE key 204", _call(st, "DELETE", f"/storage/v1/projects/p/hmacKeys/{access_id}").status == 204)
    _check("key gone after delete", _call(st, "GET", f"/storage/v1/projects/p/hmacKeys/{access_id}").status == 404)

    print("\nGCS depth-wave-5 (permissions/cors/encryption/operations/interoperability) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
