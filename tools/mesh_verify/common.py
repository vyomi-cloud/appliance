"""Shared helpers for the Mesh AI verification scripts (tools/mesh_verify). Stdlib only.

Everything here talks to REAL llama-server processes. Where it ran (Codespace vs Mac) is decided by the caller and recorded in the results
(``where`` field): NEVER publish a number from these scripts without that label.
"""
import json
import os
import platform
import subprocess
import time
import urllib.request

CHAT = os.environ.get("MV_CHAT_URL", "http://127.0.0.1:28080")
EMBED = os.environ.get("MV_EMBED_URL", "http://127.0.0.1:28083")
GATEWAY = os.environ.get("MV_GATEWAY_URL", "http://127.0.0.1:28090")   # core.mesh_llm_gateway in front of CHAT + EMBED
WHERE = os.environ.get("MV_WHERE", f"{platform.system()} {platform.machine()} (not a Codespace)")


def post(url, body, timeout=600):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def rss_mb(pid):
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return round(int(out) / 1024) if out else None


def save(name, doc):
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    doc = dict(doc, where=WHERE, when=time.strftime("%Y-%m-%dT%H:%M:%S"))
    with open(os.path.join(d, name + ".json"), "w") as f:
        json.dump(doc, f, indent=1)
    return doc
