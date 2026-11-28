#!/usr/bin/env python3
"""Release check (needs boto3, azure-storage-blob/-queue, requests): the URLs the simulator hands out WORK with the real SDKs.

Serves the same AwsWireRouter the Nano relay serves on a loopback port (stdlib HTTP, no tab needed) and then uses ONLY what the
simulator returned: SQS QueueUrl -> send/receive, Azure Storage primaryEndpoints -> blob + queue round trip, OpenSearch Endpoint ->
index + search. Prints RELEASE-CHECKS rows; exit 1 on any failure.   python3 scripts/check_endpoint_sdk.py
"""
import json, os, sys, threading, warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import aws_wire_router as w  # noqa: E402

R = w.AwsWireRouter()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _do(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        u = urlsplit(self.path)
        o = R.handle(self.command, u.path, dict(parse_qsl(u.query, keep_blank_values=True)), {k.lower(): v for k, v in self.headers.items()}, body)
        b = o.get("body") or b""
        b = b.encode() if isinstance(b, str) else b
        self.send_response(o["status"])
        for k, v in (o.get("headers") or {}).items():
            if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                self.send_header(k, str(v))
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _do

    def log_message(self, *a):
        pass


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    EP = f"http://127.0.0.1:{srv.server_address[1]}"
    rows = []

    def check(name, fn):
        try:
            detail = fn()
            rows.append((True, name, detail))
        except Exception as e:  # noqa: BLE001
            rows.append((False, name, f"{type(e).__name__}: {str(e)[:120]}"))

    import boto3
    import requests
    kw = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")

    def sqs():
        s = boto3.client("sqs", **kw)
        u = s.create_queue(QueueName="sdk-check")["QueueUrl"]
        assert u.startswith(EP), u
        s.send_message(QueueUrl=u, MessageBody="hi")
        assert [m["Body"] for m in s.receive_message(QueueUrl=u).get("Messages", [])] == ["hi"]
        return u
    check("boto3 SQS: send/receive through the returned QueueUrl", sqs)

    def azure():
        from azure.storage.blob import BlobServiceClient
        from azure.storage.queue import QueueServiceClient
        sid = requests.get(EP + "/subscriptions?api-version=2020-01-01").json()["value"][0]["subscriptionId"]
        b = f"{EP}/subscriptions/{sid}/resourceGroups/sdk-check"
        requests.put(b + "?api-version=2021-04-01", json={"location": "eastus"})
        acct = requests.put(b + "/providers/Microsoft.Storage/storageAccounts/sdkcheck1?api-version=2023-01-01",
                            json={"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).json()
        pe = acct["properties"]["primaryEndpoints"]
        key = requests.post(b + "/providers/Microsoft.Storage/storageAccounts/sdkcheck1/listKeys?api-version=2023-01-01").json()["keys"][0]["value"]
        base = f"DefaultEndpointsProtocol=http;AccountName=sdkcheck1;AccountKey={key};"
        bs = BlobServiceClient.from_connection_string(base + f"BlobEndpoint={pe['blob'].rstrip('/')};")
        bs.create_container("c1")
        bs.get_blob_client("c1", "a.txt").upload_blob(b"hello")
        assert bs.get_blob_client("c1", "a.txt").download_blob().readall() == b"hello"
        qs = QueueServiceClient.from_connection_string(base + f"QueueEndpoint={pe['queue'].rstrip('/')};")
        qs.create_queue("q1")
        qs.get_queue_client("q1").send_message("m")
        assert [m.content for m in qs.get_queue_client("q1").receive_messages()] == ["m"]
        return pe["blob"]
    check("azure-storage-blob/queue: round trip through primaryEndpoints", azure)

    def opensearch():
        o = boto3.client("opensearch", **kw)
        o.create_domain(DomainName="sdk-check")
        ep = o.describe_domain(DomainName="sdk-check")["DomainStatus"]["Endpoint"]
        assert requests.put(f"http://{ep}/idx1/_doc/1", json={"a": "hello"}).status_code in (200, 201)
        assert requests.post(f"http://{ep}/idx1/_search", json={"query": {"match_all": {}}}).json()["hits"]["total"]["value"] == 1
        return ep
    check("OpenSearch: index + search through the domain Endpoint", opensearch)

    print("## Endpoint URLs work with the real SDKs\n\n| Status | Check | Detail |\n|---|---|---|")
    for ok, name, detail in rows:
        print(f"| {'✅' if ok else '❌'} | {name} | {detail} |")
    return 0 if all(r[0] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
