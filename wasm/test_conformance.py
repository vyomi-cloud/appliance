"""POC conformance test for the WASM in-browser backend. Pure Python — runs
here AND in Pyodide. Proves: (1) the in-browser data-plane round-trips
object-store + nosql for every cloud, (2) data is isolated per cloud (no
collisions), (3) a NEW cloud (Oracle) joins additively and works identically.

AWS S3 + DynamoDB are now served by the PROVEN conformance cores (via
aws_core_adapter) — same logic as tests/conformance/, so AWS speaks the real
console contract (create-bucket-then-put, base64 bodies, real ETags, typed
items). GCP/Azure/OCI still ride the generic stub backends (their cores land as
the swap table extends). The deeper AWS guarantees live in
tests/conformance/test_{s3,dynamodb}_core.py; this just proves the wiring."""
import base64
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wasm.backends.store import Backends
from wasm import providers as P


def main() -> int:
    b = Backends()
    print("registered providers:", P.providers())
    assert P.providers() == ["aws", "azure", "gcp", "oci"], "Oracle (oci) must be registered"

    # 1. object-store round-trip per cloud, SAME key, DIFFERENT clouds -> isolated.
    #    AWS goes through the real S3 core (bucket must exist; bodies are base64).
    P.dispatch(b, "aws", "s3", "CreateBucket", params={"name": "b"})
    P.dispatch(b, "aws", "s3", "PutObject",
               params={"bucket": "b", "key": "k", "body_b64": base64.b64encode(b"from-aws").decode()})
    P.dispatch(b, "gcp",   "storage",       "insert",    params={"bucket": "b", "object": "k", "body": "from-gcp"})
    P.dispatch(b, "azure", "blob",          "PutBlob",   params={"container": "b", "blob": "k", "body": "from-azure"})
    P.dispatch(b, "oci",   "objectstorage", "PutObject", params={"bucket": "b", "name": "k", "body": "from-oci"})

    got_aws = base64.b64decode(
        P.dispatch(b, "aws", "s3", "GetObject", params={"bucket": "b", "key": "k"})["body_b64"]).decode()
    got_gcp = P.dispatch(b, "gcp",   "storage",       "get",       params={"bucket": "b", "object": "k"})["body"]
    got_az  = P.dispatch(b, "azure", "blob",          "GetBlob",   params={"container": "b", "blob": "k"})["body"]
    got_oci = P.dispatch(b, "oci",   "objectstorage", "GetObject", params={"bucket": "b", "name": "k"})["body"]
    print("object-store:", got_aws, "|", got_gcp, "|", got_az, "|", got_oci)
    assert (got_aws, got_gcp, got_az, got_oci) == ("from-aws", "from-gcp", "from-azure", "from-oci"), \
        "same key/bucket across clouds must be isolated by provider namespace"

    # 2. nosql round-trip — aws DynamoDB (real core) + the new Oracle NoSQL (stub).
    P.dispatch(b, "aws", "dynamodb", "CreateTable", params={"name": "t", "partition_key": "key"})
    P.dispatch(b, "aws", "dynamodb", "PutItem", params={"table": "t", "item": {"key": "1", "msg": "hi"}})
    P.dispatch(b, "oci", "nosql",    "PutRow",  params={"table": "t", "key": "1", "row": {"msg": "oci-hi"}})
    aws_items = P.dispatch(b, "aws", "dynamodb", "ListItems", params={"table": "t"})["items"]
    assert aws_items and aws_items[0]["msg"] == "hi"
    assert P.dispatch(b, "oci", "nosql", "GetRow", params={"table": "t", "key": "1"})["row"]["msg"] == "oci-hi"

    # 3. unknown provider / op fail cleanly (not crash)
    assert P.dispatch(b, "ibm", "x", "Y")["code"] == "UnknownProvider"
    assert P.dispatch(b, "aws", "s3", "Nope")["code"] == "UnsupportedOperation"

    print("\nRESULT: PASS — in-browser backend works for 4 clouds (AWS via the proven "
          "S3/DynamoDB cores; incl. the additive Oracle), isolated + extensible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
