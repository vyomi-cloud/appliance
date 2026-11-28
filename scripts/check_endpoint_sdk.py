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
KNOWN_GAPS = ["DAX cluster endpoint (proprietary DAX protocol)", "Redshift address:5439 (no SQL engine)", "ElastiCache / Memorystore Redis endpoints (no Redis engine)",
              "Azure SQL `*.database.windows.net:1433` (no TDS engine)", "Azure Service Bus / Key Vault host-style endpoints (use the tunnel's amqp bridge / `*.vault.localtest.me`)",
              "Cloud Run container images are not executed (the front door answers 202 with the reason; Python-source services run)"]


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

    def cosmos():
        from azure.cosmos import CosmosClient
        sid = requests.get(EP + "/subscriptions?api-version=2020-01-01").json()["value"][0]["subscriptionId"]
        b = f"{EP}/subscriptions/{sid}/resourceGroups/sdk-check"
        a = b + "/providers/Microsoft.DocumentDB/databaseAccounts/sdkcos1?api-version=2023-04-15"
        requests.put(a, json={"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard", "locations": [{"locationName": "eastus", "failoverPriority": 0}]}})
        ep = requests.get(a).json()["properties"]["documentEndpoint"].rstrip("/")
        key = requests.post(b + "/providers/Microsoft.DocumentDB/databaseAccounts/sdkcos1/listKeys?api-version=2023-04-15").json()["primaryMasterKey"]
        ct = CosmosClient(ep, key, connection_verify=False).create_database("db1").create_container("c1", partition_key={"paths": ["/pk"], "kind": "Hash"})
        ct.create_item({"id": "1", "pk": "a", "v": 1})
        assert [i["v"] for i in ct.query_items("SELECT * FROM c", enable_cross_partition_query=True)] == [1]
        return ep
    check("azure-cosmos: create + query through documentEndpoint", cosmos)

    def ecr():
        import base64
        e = boto3.client("ecr", **kw)
        uri = e.create_repository(repositoryName="sdk-check")["repository"]["repositoryUri"]
        assert uri.startswith(EP.split("://", 1)[1]), uri
        t = e.get_authorization_token()["authorizationData"][0]
        assert t["proxyEndpoint"] == EP, t["proxyEndpoint"]
        usr = tuple(base64.b64decode(t["authorizationToken"]).decode().split(":", 1))
        assert requests.get(EP + "/v2/", auth=usr).status_code == 200
        return uri
    check("ECR: repositoryUri/proxyEndpoint -> the registry /v2/ answers", ecr)

    def cloudfront():
        s3 = boto3.client("s3", **kw)
        s3.create_bucket(Bucket="sdk-site")
        s3.put_object(Bucket="sdk-site", Key="index.html", Body=b"<h1>hi</h1>", ContentType="text/html")
        d = boto3.client("cloudfront", **kw).create_distribution(DistributionConfig={
            "CallerReference": "sdk1", "Comment": "t", "Enabled": True, "DefaultRootObject": "index.html",
            "Origins": {"Quantity": 1, "Items": [{"Id": "o1", "DomainName": "sdk-site.s3.amazonaws.com", "S3OriginConfig": {"OriginAccessIdentity": ""}}]},
            "DefaultCacheBehavior": {"TargetOriginId": "o1", "ViewerProtocolPolicy": "allow-all",
                                     "ForwardedValues": {"QueryString": False, "Cookies": {"Forward": "none"}}, "MinTTL": 0}})["Distribution"]
        r = requests.get("http://" + d["DomainName"] + "/")
        assert r.status_code == 200 and "<h1>hi</h1>" in r.text, (r.status_code, r.text[:60])
        return d["DomainName"]
    check("CloudFront: GET https://<DomainName>/ serves the S3 origin", cloudfront)

    def elb():
        import io, zipfile
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("index.py", "def handler(e, c):\n  return {'statusCode': 200, 'headers': {'content-type': 'text/plain'}, 'body': 'hello from ' + e['path']}\n")
        role = boto3.client("iam", **kw).create_role(RoleName="sdk-elb", AssumeRolePolicyDocument="{}")["Role"]["Arn"]
        fa = boto3.client("lambda", **kw).create_function(FunctionName="sdk-web", Runtime="python3.12", Role=role, Handler="index.handler", Code={"ZipFile": z.getvalue()})["FunctionArn"]
        e, ec2 = boto3.client("elbv2", **kw), boto3.client("ec2", **kw)
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        sn = [ec2.create_subnet(VpcId=vpc, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=f"us-east-1{'ab'[i]}")["Subnet"]["SubnetId"] for i in range(2)]
        lb = e.create_load_balancer(Name="sdk-alb", Subnets=sn)["LoadBalancers"][0]
        tg = e.create_target_group(Name="sdk-tg", TargetType="lambda")["TargetGroups"][0]["TargetGroupArn"]
        e.register_targets(TargetGroupArn=tg, Targets=[{"Id": fa}])
        ls = e.create_listener(LoadBalancerArn=lb["LoadBalancerArn"], Port=80, Protocol="HTTP", DefaultActions=[
            {"Type": "fixed-response", "FixedResponseConfig": {"StatusCode": "404", "ContentType": "text/plain", "MessageBody": "nope"}}])["Listeners"][0]["ListenerArn"]
        e.create_rule(ListenerArn=ls, Priority=1, Conditions=[{"Field": "path-pattern", "Values": ["/app/*"]}], Actions=[{"Type": "forward", "TargetGroupArn": tg}])
        a, b = requests.get("http://" + lb["DNSName"] + "/app/x"), requests.get("http://" + lb["DNSName"] + "/other")
        assert (a.status_code, a.text) == (200, "hello from /app/x") and (b.status_code, b.text) == (404, "nope"), (a.status_code, a.text[:40], b.status_code)
        return lb["DNSName"]
    check("ALB: rule -> Lambda target, default -> fixed-response via DNSName", elb)

    def run():
        P = "nano-project"
        requests.post(EP + f"/v2/projects/{P}/locations/us-central1/services?serviceId=sdkrun", json={"template": {"containers": [{"image": "us-docker.pkg.dev/cloudrun/container/hello"}]}})
        u = requests.get(EP + f"/v2/projects/{P}/locations/us-central1/services/sdkrun").json()["uri"]
        assert u.startswith(EP + "/_run/"), u
        requests.post(EP + f"/v2/projects/{P}/locations/us-central1/services/sdkrun:setIamPolicy", json={"policy": {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]}})
        assert requests.get(u + "/").status_code in (200, 202)
        return u
    check("Cloud Run: service uri is the /_run/ front door and answers", run)

    def appservice():
        sid = requests.get(EP + "/subscriptions?api-version=2020-01-01").json()["value"][0]["subscriptionId"]
        b = f"{EP}/subscriptions/{sid}/resourceGroups/sdk-web"
        requests.put(b + "?api-version=2021-04-01", json={"location": "eastus"})
        requests.put(b + "/providers/Microsoft.Web/sites/sdkapp1?api-version=2022-09-01", json={"location": "eastus", "kind": "app", "properties": {}})
        dh = requests.get(b + "/providers/Microsoft.Web/sites/sdkapp1?api-version=2022-09-01").json()["properties"]["defaultHostName"]
        assert "azurewebsites.net" not in dh and "/azure-data/site/sdkapp1" in dh, dh
        r = requests.get("http://" + dh + "/")
        assert r.status_code in (200, 403), r.status_code   # 403 = the simulator's empty-app page (no content deployed)
        return dh
    check("App Service: defaultHostName is the /azure-data/site/<app> front door", appservice)

    print("## Endpoint URLs work with the real SDKs\n\n| Status | Check | Detail |\n|---|---|---|")
    for ok, name, detail in rows:
        print(f"| {'✅' if ok else '❌'} | {name} | {detail} |")
    print("\n**Known gaps** (the simulator has no data plane behind these, so their endpoint fields keep the realistic cloud name):\n")
    for g in KNOWN_GAPS:
        print(f"- {g}")
    return 0 if all(r[0] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
