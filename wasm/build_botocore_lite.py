#!/usr/bin/env python3
"""Build wasm/pylib/botocore-lite.whl: botocore's pure-Python serializers/parsers/models + the service models Nano's Terraform exporter reads
(ec2, s3, logs, iam, lambda, apigateway, rds, secretsmanager). Not the whole 20 MB data set. Source: the PyPI botocore wheel (Apache-2.0)."""
import io, sys, zipfile
from pathlib import Path

# A small working AWSRequest: enough for botocore.auth.SigV4Auth to sign a request an agent then sends through the in-process router (no sockets).
AWSREQUEST_HEAD = """class HeadersDict(dict):
    def __init__(self, d=None):
        super().__init__()
        for k, v in dict(d or {}).items():
            self[k] = v
    def __setitem__(self, k, v):
        super().__setitem__(str(k).lower(), (str(k), v))
    def __getitem__(self, k):
        return super().__getitem__(str(k).lower())[1]
    def __contains__(self, k):
        return super().__contains__(str(k).lower())
    def __delitem__(self, k):
        super().__delitem__(str(k).lower())
    def get(self, k, d=None):
        return self[k] if k in self else d
    def items(self):
        return [(k, v) for k, v in super().values()]
    def keys(self):
        return [k for k, v in super().values()]
    def values(self):
        return [v for k, v in super().values()]
    def __iter__(self):
        return iter(self.keys())
    def __len__(self):
        return super().__len__()
    def copy(self):
        return HeadersDict(dict(self.items()))

class AWSRequest:
    def __init__(self, method=None, url=None, headers=None, data=None, params=None, auth_path=None, stream_output=False):
        self.method, self.url, self.data, self.params, self.auth_path = method, url, data, params or {}, auth_path
        self.headers = HeadersDict(headers)
        self.context = {}
    @property
    def body(self):
        b = self.data
        return b.encode("utf-8") if isinstance(b, str) else (b if b is not None else b"")
    def prepare(self):
        return self
""".replace("\n", "\n")
STUBS = {
    "botocore/httpsession.py": "class URLLib3Session:  # Nano: no sockets\n    pass\n\ndef get_cert_path(*a, **k):\n    return None\n\nclass ProxyConfiguration:\n    pass\n",
    "botocore/awsrequest.py": AWSREQUEST_HEAD + "\n\nclass AWSResponse:\n    pass\n\nclass AWSPreparedRequest:\n    pass\n\nclass AWSRequestPreparer:\n    pass\n\ndef create_request_object(*a, **k):\n    raise NotImplementedError\n\ndef prepare_request_dict(*a, **k):\n    raise NotImplementedError\n\ndef _urljoin(a, b, *r):\n    return a.rstrip(\"/\") + \"/\" + str(b).lstrip(\"/\")\n\nclass AWSConnection:\n    pass\n\nclass AWSHTTPConnection:\n    pass\n\nclass AWSHTTPSConnection:\n    pass\n\nclass AWSHTTPConnectionPool:\n    pass\n\nclass AWSHTTPSConnectionPool:\n    pass\n",
}
KEEP = ("ec2", "s3", "logs", "iam", "lambda", "apigateway", "rds", "secretsmanager", "dynamodb", "sqs", "sns", "events", "kms", "stepfunctions", "ecr", "cloudwatch", "backup")
# Service models for the Bedrock / AgentCore family come from a NEWER botocore wheel (the 1.35 code wheel predates AgentCore); models are plain JSON,
# so the older serializers/parsers read them. Usage: build_botocore_lite.py <botocore-1.35.x.whl> [<newer botocore.whl for EXTRA models>]
EXTRA = ("bedrock", "bedrock-runtime", "bedrock-agent", "bedrock-agent-runtime", "bedrock-agentcore", "bedrock-agentcore-control")
src = Path(sys.argv[1]); newer = Path(sys.argv[2]) if len(sys.argv) > 2 else None; out = Path(__file__).parent / "pylib" / "botocore-lite.whl"
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
if newer:
    old, buf = buf.getvalue(), io.BytesIO()
    with zipfile.ZipFile(newer) as zn, zipfile.ZipFile(io.BytesIO(old)) as zold, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout2:
        have = set()
        for i in zold.infolist():
            zout2.writestr(i.filename, zold.read(i)); have.add(i.filename)
        lat = {}
        for n in zn.namelist():
            pt = n.split("/")
            if n.startswith("botocore/data/") and len(pt) >= 5 and pt[2] in EXTRA:
                lat[pt[2]] = max(lat.get(pt[2], ""), pt[3])
        for n in zn.namelist():
            pt = n.split("/")
            if n.startswith("botocore/data/") and len(pt) >= 5 and pt[2] in EXTRA and pt[3] == lat[pt[2]] and pt[-1].startswith(("service-2", "paginators-1")) and n not in have:
                zout2.writestr(n, zn.read(n))
out.write_bytes(buf.getvalue()); print(out, round(out.stat().st_size / 1e6, 2), "MB")
