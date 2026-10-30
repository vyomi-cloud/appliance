"""Every core vendored for Nano (wasm/build_cores.py CORES) must also be loaded into Pyodide by
wasm/nano-boot.js — a router that imports a vendored-but-unloaded core fails EVERY Nano /_wire
request with ImportError (seen when the Cloud Logging core landed).

    PYTHONPATH=. python3 tests/conformance/test_nano_core_manifest.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OFFLINE_ONLY = {"__init__.py", "persistent_store.py"}   # sqlite-backed stores are appliance-only

bc = (ROOT / "wasm/build_cores.py").read_text()
cores = dict.fromkeys(re.findall(r'"([a-z0-9_]+\.py)"', bc[bc.index("CORES"):]))
boot = set(re.findall(r'"([a-z0-9_]+\.py)"', (ROOT / "wasm/nano-boot.js").read_text()))
missing = [c for c in cores if c not in boot and c not in OFFLINE_ONLY]
if missing:
    raise SystemExit(f"RESULT: FAIL — vendored for Nano but not loaded by wasm/nano-boot.js: {missing}")
print(f"RESULT: PASS — all {len(cores) - len(OFFLINE_ONLY & set(cores))} vendored cores are loaded by Nano")
