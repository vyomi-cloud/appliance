"""Nano must not fire requests that are expected to fail (the UI crawler scores them as findings).

1. The tunnel panel probes the hosted relay (503 'no Nano tab registered' for anyone not connected
   through it) only while the Cloudflare tab carries traffic.
2. The Pyodide loaders read wasm/pyodide-source.json instead of HEAD-probing /vendor/pyodide/pyodide.mjs
   (a 404 on every bundle that does not ship the vendored runtime).
"""
import json, os, re, sys

W = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "wasm")
rd = lambda p: open(os.path.join(W, p), encoding="utf-8").read()
fails = []

tabs = rd("nano-tunnel-tabs.js")
if re.search(r"^\s*probe\('local'[^\n]*;\s*probe\('cloud'", tabs, re.M):
    fails.append("tunnel panel probes the hosted relay unconditionally")
if not re.search(r"if \(active\(\) === 'cloud'\) probe\('cloud'", tabs):
    fails.append("hosted-relay probe is not gated on the Cloudflare tab being in use")

for f in ("nano-boot.js", "relay/relay-shared-worker.js", "relay/nano-endpoint.html"):
    s = rd(f)
    if re.search(r'fetch\(PYODIDE_LOCAL \+ "pyodide\.mjs"', s):
        fails.append(f + " HEAD-probes the local pyodide path")
    if "pyodide-source.json" not in s:
        fails.append(f + " does not read pyodide-source.json")

src = json.loads(rd("pyodide-source.json"))
if src.get("local") is not False and not os.path.isdir(os.path.join(W, "vendor", "pyodide")):
    fails.append("pyodide-source.json says local but wasm/vendor/pyodide is absent")
if "pyodide-source.json" not in rd("fetch_pyodide.py"):
    fails.append("fetch_pyodide.py does not flip pyodide-source.json")

for x in fails:
    print("FAIL", x)
print("PASS" if not fails else "FAILED", len(fails))
sys.exit(1 if fails else 0)
