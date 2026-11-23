"""STAND-IN request->permission map (S3 only) for the Nano hook e2e; the real core/iam_engine/map_aws.py is on another branch.
Does real work: SigV4 service from the credential scope, S3 path-style REST -> action + ARN, and it LOADS the service catalog (lazy: the
first S3 request raises CatalogUnavailable, which the hook answers by prefetching s3.json)."""
import re
from core.iam_engine import catalog_loader

_SCOPE = re.compile(r"Credential=[^/]+/\d{8}/[^/]+/([^/]+)/aws4_request")


def required(hr):
    h = {k.lower(): v for k, v in (hr.get("headers") or {}).items()}
    m = _SCOPE.search(h.get("authorization", ""))
    if not m or m.group(1) != "s3":
        return []
    parts = [p for p in str(hr["path"]).split("?")[0].split("/") if p]
    bucket, key, meth = (parts[0] if parts else None), ("/".join(parts[1:]) or None), hr["method"]
    if bucket is None:
        op, res = "ListBuckets", "*"
    elif key is None:
        op, res = {"GET": "ListObjectsV2", "PUT": "CreateBucket", "DELETE": "DeleteBucket", "HEAD": "HeadBucket"}.get(meth, "ListObjectsV2"), f"arn:aws:s3:::{bucket}"
    else:
        op, res = {"GET": "GetObject", "HEAD": "HeadObject", "PUT": "PutObject", "POST": "PostObject", "DELETE": "DeleteObject"}.get(meth, "GetObject"), f"arn:aws:s3:::{bucket}/{key}"
    cat = catalog_loader.load("aws", "s3")
    acts = (cat.get("operations") or {}).get(op) or [op]           # catalog: API operation -> authorized action(s)
    action = "s3:" + (op if op in acts else acts[-1])      # catalog lists every action an op MAY need (ListObjectsV2: GetObjectAcl first); the real map_aws resolves this per operation
    return [{"action": action, "resource": res, "service": "s3", "operation": op}]
