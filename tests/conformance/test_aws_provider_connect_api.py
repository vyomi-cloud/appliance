"""/api/providers/aws/* — the CLI + SDK connection guides the console's 'Connect' dialogs read."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def main():
    r = requests.get(f"{BASE}/api/providers/aws/cli", timeout=30).json()
    check("cli guide names awscli with an endpoint", r.get("tool") == "awscli" and r.get("endpoint", "").startswith("http"))
    for lang, tool in (("java", "aws-sdk-java"), ("go", "aws-sdk-go"), ("python", "boto3"), ("nodejs", "aws-sdk-js-v3")):
        g = requests.get(f"{BASE}/api/providers/aws/sdk/{lang}", timeout=30).json()
        check(f"sdk/{lang} guide is {tool} with an endpoint", g.get("tool") == tool and bool(g.get("endpoint")))
        s = requests.get(f"{BASE}/api/providers/aws/sdk/{lang}/snippet", timeout=30).json()
        check(f"sdk/{lang} snippet is non-empty and uses the endpoint", bool(s.get("snippet")) and s.get("language") == lang)
    ok = requests.post(f"{BASE}/api/providers/aws/cli/resolve", json={"command": "aws s3 ls"}, timeout=30).json()
    check("cli/resolve resolves 'aws s3 ls' to the s3 service", ok.get("service") == "s3" and ok.get("command") == "aws s3 ls")
    bad = requests.post(f"{BASE}/api/providers/aws/cli/resolve", json={"command": "gcloud x"}, timeout=30).json()
    check("cli/resolve rejects a non-aws command", "must start with" in str(bad.get("notes", "")))
    sys.exit(1 if failed else 0)


main()
