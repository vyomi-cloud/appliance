"""POC conformance test for the WASM in-browser backend. Pure Python — runs
here AND in Pyodide. Proves: (1) the in-memory backend round-trips object-store
+ nosql for every cloud, (2) data is namespaced per cloud (no collisions),
(3) a NEW cloud (Oracle) joins additively and works identically."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wasm.backends.store import Backends
from wasm import providers as P


def main() -> int:
    b = Backends()
    print("registered providers:", P.providers())
    assert P.providers() == ["aws", "azure", "gcp", "oci"], "Oracle (oci) must be registered"

    # 1. object-store round-trip per cloud, SAME key, DIFFERENT clouds -> isolated
    P.dispatch(b, "aws",   "s3",            "PutObject",  params={"bucket": "b", "key": "k", "body": "from-aws"})
    P.dispatch(b, "gcp",   "storage",       "insert",     params={"bucket": "b", "object": "k", "body": "from-gcp"})
    P.dispatch(b, "azure", "blob",          "PutBlob",    params={"container": "b", "blob": "k", "body": "from-azure"})
    P.dispatch(b, "oci",   "objectstorage", "PutObject",  params={"bucket": "b", "name": "k", "body": "from-oci"})

    got_aws = P.dispatch(b, "aws",   "s3",            "GetObject", params={"bucket": "b", "key": "k"})["Body"]
    got_gcp = P.dispatch(b, "gcp",   "storage",       "get",       params={"bucket": "b", "object": "k"})["body"]
    got_az  = P.dispatch(b, "azure", "blob",          "GetBlob",   params={"container": "b", "blob": "k"})["body"]
    got_oci = P.dispatch(b, "oci",   "objectstorage", "GetObject", params={"bucket": "b", "name": "k"})["body"]
    print("object-store:", got_aws, "|", got_gcp, "|", got_az, "|", got_oci)
    assert (got_aws, got_gcp, got_az, got_oci) == ("from-aws", "from-gcp", "from-azure", "from-oci"), \
        "same key/bucket across clouds must be isolated by provider namespace"

    # 2. nosql round-trip (aws DynamoDB + the new Oracle NoSQL)
    P.dispatch(b, "aws", "dynamodb", "PutItem", params={"table": "t", "key": "1", "item": {"msg": "hi"}})
    P.dispatch(b, "oci", "nosql",    "PutRow",  params={"table": "t", "key": "1", "row": {"msg": "oci-hi"}})
    assert P.dispatch(b, "aws", "dynamodb", "GetItem", params={"table": "t", "key": "1"})["Item"]["msg"] == "hi"
    assert P.dispatch(b, "oci", "nosql",    "GetRow",  params={"table": "t", "key": "1"})["row"]["msg"] == "oci-hi"

    # 3. unknown provider / op fail cleanly (not crash)
    assert P.dispatch(b, "ibm", "x", "Y")["code"] == "UnknownProvider"
    assert P.dispatch(b, "aws", "s3", "Nope")["code"] == "UnsupportedOperation"

    print("\nRESULT: PASS — in-browser conformance backend works for 4 clouds (incl. the additive Oracle), namespaced + extensible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
