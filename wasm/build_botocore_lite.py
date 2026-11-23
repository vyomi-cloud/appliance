#!/usr/bin/env python3
"""Build wasm/pylib/botocore-lite.whl: botocore's pure-Python serializers/parsers/models + the service models Nano's Terraform exporter reads
(ec2, s3, logs, iam, lambda, apigateway, rds, secretsmanager). Not the whole 20 MB data set. Source: the PyPI botocore wheel (Apache-2.0)."""
import io, sys, zipfile
from pathlib import Path

STUBS = {
    "botocore/httpsession.py": "class URLLib3Session:  # Nano: no sockets\n    pass\n\ndef get_cert_path(*a, **k):\n    return None\n\nclass ProxyConfiguration:\n    pass\n",
    "botocore/awsrequest.py": "class AWSRequest:\n    pass\n\nclass AWSResponse:\n    pass\n\nclass AWSPreparedRequest:\n    pass\n\nclass HeadersDict(dict):\n    pass\n\nclass AWSRequestPreparer:\n    pass\n\ndef create_request_object(*a, **k):\n    raise NotImplementedError\n\ndef prepare_request_dict(*a, **k):\n    raise NotImplementedError\n\ndef _urljoin(a, b, *r):\n    return a.rstrip(\"/\") + \"/\" + str(b).lstrip(\"/\")\n\nclass AWSConnection:\n    pass\n\nclass AWSHTTPConnection:\n    pass\n\nclass AWSHTTPSConnection:\n    pass\n\nclass AWSHTTPConnectionPool:\n    pass\n\nclass AWSHTTPSConnectionPool:\n    pass\n",
}
KEEP = ("ec2", "s3", "logs", "iam", "lambda", "apigateway", "rds", "secretsmanager")
src = Path(sys.argv[1]); out = Path(__file__).parent / "pylib" / "botocore-lite.whl"
buf = io.BytesIO()
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
    latest = {}
    for n in zin.namelist():
        pt = n.split("/")
        if n.startswith("botocore/data/") and len(pt) >= 4 and pt[2] in KEEP:
            latest[pt[2]] = max(latest.get(pt[2], ""), pt[3])
    for i in zin.infolist():
        n = i.filename
        if n.startswith("botocore/data/"):
            parts = n.split("/")
            if len(parts) < 5 or parts[2] not in KEEP or parts[3] != latest[parts[2]] or not parts[-1].startswith(("service-2", "paginators-1")):
                continue
        elif not n.startswith("botocore/"):
            continue
        # Nano never opens a socket (transport is the in-process router) and Pyodide's urllib3 2.x lacks names these modules import: stub them.
        if n in ("botocore/httpsession.py", "botocore/awsrequest.py"):
            zout.writestr(n, STUBS[n]); continue
        zout.writestr(n, zin.read(n))
out.write_bytes(buf.getvalue()); print(out, round(out.stat().st_size / 1e6, 2), "MB")
