"""Each v4 lens registry lists a service id once. A duplicate (a v4 `load:` entry plus a stale
`classic:` one, left by a merge) makes the lookup keep the last entry, so a built service shows
"Not simulated".

    PYTHONPATH=. python3 tests/conformance/test_console_registry_unique.py
"""
import collections, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
bad = {}
for cloud in ("aws", "gcp", "azure"):
    ids = re.findall(r'^\s*\{ id: "([^"]+)"', (ROOT / f"consoles/src/{cloud}/services/registry.js").read_text(), re.M)
    dups = [i for i, n in collections.Counter(ids).items() if n > 1]
    if dups: bad[cloud] = dups
if bad:
    raise SystemExit(f"RESULT: FAIL — duplicate service ids in lens registries: {bad}")
print("RESULT: PASS — every lens registry lists each service once")
