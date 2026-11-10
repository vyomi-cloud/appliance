"""AWS SDK-info routes (/api/providers/aws/sdk/<lang> and /snippet) return endpoint-pointed config and snippets."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def get(path):
    r = requests.get(f"{BASE}{path}", timeout=30)
    return r.status_code, (r.json() if r.status_code == 200 else {})


def main():
    info = {
        "java": (get("/api/providers/aws/sdk/java"), get("/api/providers/aws/sdk/java/snippet"), "endpointOverride"),
        "go": (get("/api/providers/aws/sdk/go"), get("/api/providers/aws/sdk/go/snippet"), "LoadDefaultConfig"),
        "python": (get("/api/providers/aws/sdk/python"), get("/api/providers/aws/sdk/python/snippet"), "boto3"),
        "nodejs": (get("/api/providers/aws/sdk/nodejs"), get("/api/providers/aws/sdk/nodejs/snippet"), "@aws-sdk"),
    }
    for lang, ((s1, body), (s2, snip), marker) in info.items():
        check(f"{lang} info returns provider aws with config", s1 == 200 and body.get("provider") == "aws" and bool(body.get("config")))
        check(f"{lang} snippet contains endpoint and {marker}", s2 == 200 and snip.get("language") == lang and marker in snip.get("snippet", "") and snip.get("endpoint", "") in snip.get("snippet", ""))
    sys.exit(1 if failed else 0)


main()
