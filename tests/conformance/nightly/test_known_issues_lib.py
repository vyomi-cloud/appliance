"""known_issues.py: parse open rows per cloud, add/refresh auto rows without duplicates, resolve moves a row out.
Run: python3 tests/conformance/nightly/test_known_issues_lib.py"""
import shutil, tempfile
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location("ki", Path(__file__).parent / "lib" / "known_issues.py")
ki = importlib.util.module_from_spec(spec); spec.loader.exec_module(ki)

SRC = ki.DEFAULT
tmp = Path(tempfile.mkdtemp()) / "KI.md"
shutil.copy(SRC, tmp)


def check(n, c):
    if not c: raise AssertionError(n)
    print("  ok ", n)


az = ki.list_open("azure", tmp)
check("azure rows are AZ-*", az and all(r["id"].startswith("AZ-") for r in az))
check("gcp rows include GW-*/GCP-*", any(r["id"].startswith(("GW-", "GCP-")) for r in ki.list_open("gcp", tmp)))
check("add creates the auto section + a row", ki.add_issue("azure", "vm-power", "S2", "VM stop leaves container", "core/x.py", path=tmp) == "added")
check("add again is an update, not a duplicate", ki.add_issue("azure", "vm-power", "S1", "VM stop leaves container (again)", "core/x.py", path=tmp) == "updated")
rows = [r for r in ki.list_open("azure", tmp) if r["id"] == "AUTO-azure-vm-power"]
check("exactly one auto row, refreshed", len(rows) == 1 and rows[0]["impact"] == "S1")
check("other clouds do not see it", not [r for r in ki.list_open("aws", tmp) if r["id"].startswith("AUTO-azure")])
n = len(ki.list_open("azure", tmp))
check("resolve removes the row", ki.resolve("AUTO-azure-vm-power", "abc123", tmp) and len(ki.list_open("azure", tmp)) == n - 1)
check("resolved row is not listed as open", all(r["id"] != "AUTO-azure-vm-power" for r in ki.list_open(None, tmp)))
check("resolve of an unknown id is False", ki.resolve("AZ-999", "x", tmp) is False)
print("PASS")
