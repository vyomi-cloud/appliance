#!/usr/bin/env python3
"""Azure check 5: resource groups made/deleted in the console vs ARM REST, compared on name + location.
    VYOMI_BASE_URL=http://localhost:9100 NODE_PATH=... python3 tests/conformance/nightly/azure-roundtrip.py
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from tests.conformance.nightly.lib.roundtrip import run_roundtrip  # noqa: E402

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
SUB = os.environ.get("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-cloudlearn01")
API = "2021-04-01"
DRIVER = os.path.join(os.path.dirname(__file__), "azure-ui-driver.mjs")
ENV = {**os.environ, "VYOMI_CONSOLE_URL": os.environ.get("VYOMI_CONSOLE_URL", BASE + "/console/azure")}


def arm(method, name, body=None):
    req = urllib.request.Request(f"{BASE}/subscriptions/{SUB}/resourcegroups/{name}?api-version={API}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def ui(cmd, name):
    p = subprocess.run(["node", DRIVER, cmd, name], env=ENV, capture_output=True, text=True, timeout=120)
    line = (p.stdout.strip().splitlines() or ["{}"])[-1]
    d = json.loads(line)
    if not d.get("ok"):
        raise RuntimeError(f"ui {cmd}: {d.get('error') or p.stderr[-200:]}")
    return d.get("data")


class Azure:
    fields = ("name", "location")

    def ui_create(self, n): ui("create", n)
    def client_create(self, n): arm("PUT", n, {"location": "eastus"})
    def client_read(self, n):
        r = arm("GET", n)
        return None if r is None else {"name": r["name"], "location": r["location"]}
    def ui_read(self, n):
        d = ui("read", n)
        if d is None:
            return None
        # the console list shows the display region; compare against ARM's own value for the same RG
        cells = d["cells"]
        arm_loc = (arm("GET", n) or {}).get("location")
        shown = next((c for c in cells if arm_loc and arm_loc.replace(" ", "").lower() in c.replace(" ", "").lower()), None)
        return {"name": d["name"], "location": arm_loc if shown else cells[1] if len(cells) > 1 else ""}
    def ui_delete(self, n): ui("delete", n); time.sleep(2)
    def client_delete(self, n): arm("DELETE", n); time.sleep(2)


if __name__ == "__main__":
    base = f"rt-az-{int(time.time()) % 100000}"
    fails = run_roundtrip(Azure(), base)
    for n in (f"{base}-ui", f"{base}-client"):  # never leave test data behind
        try: arm("DELETE", n)
        except Exception: pass
    sys.exit(1 if fails else 0)
