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
# Every core the native-wire router imports must be vendored too (else Nano can't import it).
router = (ROOT / "core/aws_wire_router.py").read_text()
imported = {m + ".py" for m in re.findall(r"^from core import (\w+)", router, re.M)} | \
           {m + ".py" for m in re.findall(r"^from core\.(\w+) import", router, re.M)}
unvendored = sorted(c for c in imported if c not in cores)
if unvendored:
    raise SystemExit(f"RESULT: FAIL — core/aws_wire_router.py imports cores not vendored for Nano (wasm/build_cores.py): {unvendored}")
if missing:
    raise SystemExit(f"RESULT: FAIL — vendored for Nano but not loaded by wasm/nano-boot.js: {missing}")
print(f"RESULT: PASS — all {len(cores) - len(OFFLINE_ONLY & set(cores))} vendored cores are loaded by Nano")
