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
                    r"requestParameters|\"source\"|_SOURCE|raise |_err\(|Error\(|message|Message|docs?:|#")


def static_counts():
    out = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "core", "*.py"))):
        n = 0
        for ln in open(p, encoding="utf-8", errors="replace"):
            if HOST.search(ln) and BUILDS.search(ln) and not BENIGN.search(ln):
                n += 1
        if n:
            out[os.path.basename(p)] = n
    return out


def probe():
    sys.path.insert(0, ROOT)
    from core import aws_wire_router as w
    r = w.AwsWireRouter()
    tun = "check-tunnel.example.net"
    rows = []

    def call(method, path, svc, body=None, target=None):
        h = {"host": tun, "x-forwarded-proto": "https", "content-type": "application/x-amz-json-1.0",
             "authorization": f"AWS4-HMAC-SHA256 Credential=AKIA/20250101/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=x"}
        if target:
            h["x-amz-target"] = target
        o = r.handle(method, path, {}, h, json.dumps(body).encode() if body is not None else b"")
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
    return rows


def main():
    cur = static_counts()
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
        print(f"| ❌ | NEW hardcoded cloud-host URL in core/{f} | {n} lines (allowed {b}) |")
    bad += len(reg)
    left = sum(cur.values())
    print(f"| {'✅' if not reg else '❌'} | No new hardcoded real-cloud URLs (ratchet) | {left} legacy lines remain in {len(cur)} files, baseline {sum(base.values())} |")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
