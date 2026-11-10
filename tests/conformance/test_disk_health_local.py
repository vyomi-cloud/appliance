"""Host utilization → Disk on a Docker install (no runtime bridge): the disk sample
falls back to measuring the data volume's disk, so the card shows a real number.

Run on host:    python3 tests/conformance/test_disk_health_local.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core import disk_health as dh  # noqa: E402

fails = []


def _check(name, ok):
    print(("  ok  " if ok else "  FAIL ") + name)
    if not ok:
        fails.append(name)


# No bridge answers (every Docker install): the local fallback must give a real sample.
dh._bridge_run = lambda *a, **k: {"returncode": -1, "stdout": "", "stderr": "URLError: Connection refused"}
s = dh._sample_root_disk()
_check("no bridge → disk sample still available", s.get("available") is True)
_check("sample is local", str(s.get("source", "")).startswith("local:"))
_check("sizes are sane", s.get("total_bytes", 0) > 0 and 0 <= s.get("pct_used", -1) <= 100
       and abs(s["used_bytes"] + s["avail_bytes"] - s["total_bytes"]) <= s["total_bytes"])
h = dh.evaluate_health({})
_check("health has a status (not 'unknown')", h.get("available") is True and h.get("status") in ("green", "warn", "freeze"))

# A bridge that answers (Multipass installs) still wins.
dh._bridge_run = lambda *a, **k: {"returncode": 0, "stdout": "1B-blocks Used Avail Use%\n1000 400 600 40%\n", "stderr": ""}
s = dh._sample_root_disk()
_check("bridge answer is used when present", s.get("source") == "bridge" and s.get("pct_used") == 40.0)

print("\nRESULT:", "FAIL" if fails else "PASS — the Disk tile has a real sample with or without a runtime bridge.")
sys.exit(1 if fails else 0)
