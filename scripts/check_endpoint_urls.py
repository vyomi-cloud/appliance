#!/usr/bin/env python3
"""Release check: user-facing URLs / connection strings must point at the SIMULATOR, not the real cloud.

A queue URL of https://sqs.us-east-1.amazonaws.com/... is useless to someone reaching the simulator through a tunnel.
Two halves:

  1. RUNTIME probe - drive the AWS wire router the way a tunnelled client does (Host: <tunnel>, X-Forwarded-Proto: https) and
     assert that the URLs it hands back (SQS QueueUrl, API Gateway invokeUrl) carry that host and no real-cloud hostname.
  2. STATIC ratchet - count source lines in core/*.py that build a URL on a real cloud hostname (amazonaws.com, googleapis.com,
     windows.net, azure.com, ...), minus known-benign shapes (ARNs, XML namespaces, log names, @type). Each file may only go DOWN
     from scripts/endpoint_urls.baseline.json; a new hardcoded endpoint fails the release. Fix a file, then `--update`.

    python3 scripts/check_endpoint_urls.py            # table rows for RELEASE-CHECKS.md, exit 1 on any failure
    python3 scripts/check_endpoint_urls.py --update   # lower the baseline after a fix
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "scripts", "endpoint_urls.baseline.json")
HOST = re.compile(r"(amazonaws\.com|googleapis\.com|windows\.net|\.azure\.com|azurewebsites\.net|cloudapp\.azure|run\.app|cloudfront\.net|cloudfunctions\.net)")
BUILDS = re.compile(r"""f["']|%s|\.format\(""")
BENIGN = re.compile(r"arn:|logName|logs/|type\.googleapis|xmlns|/doc/20|schemas|oauth|/auth/|www-authenticate|cloudtrail|CloudTrail|"
                    r"origin\(\)|public_origin|requestParameters|\"source\"|_SOURCE|raise |_err\(|Error\(|message|Message|docs?:|#")


# Lines that name a real cloud host but are NOT something a user connects to. Each pattern says why.
EXEMPT = [
    (r"cognito-idp\.|sts\.windows\.net|login\.microsoftonline|sts\.%s\.amazonaws", "token issuer / audience identity URLs (JWT claims)"),
    (r"iam\.googleapis\.com|principal://|\"//[a-z]+\.googleapis\.com|f\"//[a-z]+\.googleapis\.com|\"//[a-z]+\.googleapis\.com", "audit text / full resource names (`//svc.googleapis.com/...`)"),
    (r"cloudfront\.amazonaws\.com/2020-05-31|\.cloudfront\.net \(CloudFront\)", "control-plane Location header / `via` header"),
    (r"selfLink|targetLink|self_link", "GCP control-plane resource identifiers (clients treat them as ids)"),
    (r"ART_ACCOUNT|storagePath|outputBlob|vyomibootdiag|urlsafe_b64encode|Cannot connect to server", "internal artifact locations parsed by the simulator"),
    (r"compute-1\.amazonaws\.com", "EC2 public DNS display name (the Connect tab shows the exact ssh string)"),
    (r"vpce\.amazonaws\.com|clientvpn|privateDnsName", "private-endpoint DNS names (not connectable from outside the VPC)"),
    (r"_o else|origin\(\) or|else f\"https|else \"https|\"domain\": f\"d\{secrets|\"Endpoint\": f\"search-|collectionEndpoint|dns = f\"\{'internal-'|\{tag\}\.\{loc\}\.run\.app|\"https://%s-%s\.%s\.run\.app\"|\"secondaryEndpoints\"|\"table\": f\"https://\{acct\}-secondary",
     "stored / no-request fallback; the read path rewrites it to the request host"),
    (r"rds\.\{r\}\.amazonaws\.com|\{src\}\.amazonaws\.com|disk\.csi\.azure\.com", "region/event-source names, not endpoints"),
]
EXEMPT_FILES = {"gcp_compute_core.py": "GCP control-plane identifiers", "gcp_compute_instances_core.py": "GCP control-plane identifiers",
                "gcp_container_core.py": "GCP control-plane identifiers", "gcp_function_runtime.py": "function-runtime instance metadata / JWT issuers"}
_EX = [(re.compile(p), why) for p, why in EXEMPT]


def static_counts(detail=False):
    out, exempt = {}, {}
    for p in sorted(glob.glob(os.path.join(ROOT, "core", "*.py"))):
        n = e = 0
        for ln in open(p, encoding="utf-8", errors="replace"):
            if HOST.search(ln) and BUILDS.search(ln) and not BENIGN.search(ln):
                if os.path.basename(p) in EXEMPT_FILES or any(rx.search(ln) for rx, _ in _EX):
                    e += 1
                else:
                    n += 1
        if n:
            out[os.path.basename(p)] = n
        if e:
            exempt[os.path.basename(p)] = e
    # Console sources: a copyable endpoint must come from common/connect.js (`extUrl` / `sdkEndpoint`), which is the tunnel on Nano - a bare
    # `location.origin` there is the page's own /nano/_wire service-worker path, unreachable from the user's CLI.
    for p in sorted(glob.glob(os.path.join(ROOT, "consoles", "src", "**", "*.js*"), recursive=True)):
        if p.endswith("connect.js") or ".test." in p:
            continue
        n = sum(1 for ln in open(p, encoding="utf-8", errors="replace") if "location.origin" in ln and not ln.lstrip().startswith(("//", "*", "/*")))
        if n:
            out["consoles/" + os.path.relpath(p, os.path.join(ROOT, "consoles", "src"))] = n
    return (out, exempt) if detail else out


def probe():
    sys.path.insert(0, ROOT)
    from core import aws_wire_router as w
    r = w.AwsWireRouter()
    tun = "check-tunnel.example.net"
    rows = []

    def call(method, path, svc, body=None, target=None, query=None):
        h = {"host": tun, "x-forwarded-proto": "https", "content-type": "application/x-amz-json-1.0",
             "authorization": f"AWS4-HMAC-SHA256 Credential=AKIA/20250101/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=x"}
        if target:
            h["x-amz-target"] = target
        o = r.handle(method, path, query or {}, h, body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b""))
        return json.loads(o["body"] or b"{}")

    def verdict(name, url):
        ok = bool(url) and url.startswith(f"https://{tun}/") and not HOST.search(url)
        rows.append((ok, name, url or "(none)"))

    call("POST", "/", "sqs", {"QueueName": "url-check"}, "AmazonSQS.CreateQueue")
    verdict("SQS CreateQueue/GetQueueUrl -> QueueUrl on the request host",
            call("POST", "/", "sqs", {"QueueName": "url-check"}, "AmazonSQS.GetQueueUrl").get("QueueUrl"))
    verdict("SQS ListQueues -> QueueUrls on the request host",
            (call("POST", "/", "sqs", {}, "AmazonSQS.ListQueues").get("QueueUrls") or [""])[0])
    a = call("POST", "/restapis", "apigateway", {"name": "url-check"})
    call("POST", f"/restapis/{a.get('id')}/deployments", "apigateway", {"stageName": "prod"})
    verdict("API Gateway stage -> invokeUrl on the request host",
            call("GET", f"/restapis/{a.get('id')}/stages/prod", "apigateway").get("invokeUrl"))
    stg = f"/restapis/{a.get('id')}/stages/prod/exports/oas30"
    verdict("API Gateway OpenAPI export -> servers[0].url on the request host",
            ((call("GET", stg, "apigateway").get("servers") or [{}])[0]).get("url"))
    call("POST", "/storage/v1/b?project=p", "storage", {"name": "url-check"})
    o = call("POST", "/upload/storage/v1/b/url-check/o", "storage", b"hi", query={"uploadType": "media", "name": "a.txt"})
    verdict("GCS bucket selfLink on the request host", call("GET", "/storage/v1/b/url-check", "storage").get("selfLink"))
    verdict("GCS object mediaLink on the request host", o.get("mediaLink"))
    # Azure Storage: primaryEndpoints.blob is a path-style data plane on the request host (the SDK-verified Azurite shape)
    subs = json.loads(r.handle("GET", "/subscriptions", {"api-version": "2020-01-01"}, {"host": tun, "x-forwarded-proto": "https"}, b"")["body"])
    sid = subs["value"][0]["subscriptionId"]
    az = {"host": tun, "x-forwarded-proto": "https", "content-type": "application/json"}
    rg = f"/subscriptions/{sid}/resourceGroups/url-check"
    r.handle("PUT", rg, {"api-version": "2021-04-01"}, az, b'{"location":"eastus"}')
    acct = json.loads(r.handle("PUT", rg + "/providers/Microsoft.Storage/storageAccounts/urlcheck1", {"api-version": "2023-01-01"}, az,
                               b'{"location":"eastus","sku":{"name":"Standard_LRS"},"kind":"StorageV2"}')["body"])
    blob = ((acct.get("properties") or {}).get("primaryEndpoints") or {}).get("blob", "")
    ok = blob.startswith(f"https://{tun}/azure-data/blob/urlcheck1") and not HOST.search(blob)
    rows.append((ok, "Azure Storage primaryEndpoints.blob on the request host", blob or "(none)"))
    # OpenSearch: the data plane is served at the root of the origin, so the domain endpoint is the request host
    call("POST", "/2021-01-01/opensearch/domain", "es", {"DomainName": "url-check"})
    ep = ((call("GET", "/2021-01-01/opensearch/domain/url-check", "es").get("DomainStatus") or {}).get("Endpoint")) or ""
    rows.append((ep == tun, "OpenSearch domain Endpoint is the request host", ep or "(none)"))
    return rows


def main():
    cur, exempt = static_counts(detail=True)
    if "--update" in sys.argv:
        json.dump(cur, open(BASELINE, "w"), indent=1, sort_keys=True)
        print(f"baseline updated: {sum(cur.values())} hardcoded cloud-host URL lines in {len(cur)} files")
        return 0
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    bad = 0
    print("## Endpoint URLs (simulator host, not the real cloud)\n")
    print("| Status | Check | Detail |\n|---|---|---|")
    for ok, name, detail in probe():
        bad += (not ok)
        print(f"| {'✅' if ok else '❌'} | {name} | {detail} |")
    reg = {f: (n, base.get(f, 0)) for f, n in cur.items() if n > base.get(f, 0)}
    for f, (n, b) in sorted(reg.items()):
        print(f"| ❌ | NEW hardcoded cloud-host URL / bare location.origin in {f if f.startswith('consoles/') else 'core/' + f} | {n} lines (allowed {b}) |")
    bad += len(reg)
    left = sum(cur.values())
    print(f"| {'✅' if not reg else '❌'} | No new hardcoded real-cloud URLs (ratchet) | {left} known-gap lines in {len(cur)} files (baseline {sum(base.values())}); "
          f"{sum(exempt.values())} exempt lines (identifiers, audit text, internal locations) |")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
