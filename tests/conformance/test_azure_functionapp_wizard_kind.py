"""The Function app create wizard must yield a site of kind functionapp[,linux].

Without it the console PUTs a kind-less site, the engine stores it as a Web App and the
Functions tab 404s ("'functions' is not supported on a Web App") -- found by the Nano UI crawl.
Run: python3 tests/conformance/test_azure_functionapp_wizard_kind.py
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from core import azure_wizards  # noqa: E402

FAIL = 0


def check(name, ok):
    global FAIL
    FAIL += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")


def build(wiz, values):
    """The console's submitWizard synthetic expansion (wasm/azure-console.html)."""
    body = {}
    for k, v in values.items():
        m = wiz["synthetic_map"].get(k)
        exp = (m or {}).get(v) or (m or {}).get("*")
        for path, val in (exp or {}).items():
            body[path] = v if val == "$value" else val
    return body


wiz = azure_wizards.WIZARDS["functionapp"]
check("linux default -> kind functionapp,linux", build(wiz, {"__osType__": "linux"}).get("kind") == "functionapp,linux")
check("windows -> kind functionapp", build(wiz, {"__osType__": "windows"}).get("kind") == "functionapp")

fx = json.load(open(os.path.join(ROOT, "wasm", "fixtures", "azure-catalog.json")))
fa = next(s for s in fx["services"] if s["key"] == "functionapp")
check("Nano fixture carries the same map", fa["wizard"]["synthetic_map"] == wiz["synthetic_map"])
sys.exit(1 if FAIL else 0)
