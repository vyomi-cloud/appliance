import re

ASSET = re.compile(r"^[A-Z]{1,3}-[0-9]{1,4}$")
PRIORITIES = {"P1", "P2", "P3", "P4"}


def validate(call):
    errs = []
    if not ASSET.match(str(call.get("asset_id", ""))):
        errs.append("asset_id must look like B-12")
    if call.get("priority", "P3") not in PRIORITIES:
        errs.append("priority must be one of P1..P4")
    s = str(call.get("summary", ""))
    if not 3 <= len(s) <= 300 or any(ord(c) < 32 for c in s):
        errs.append("summary must be 3-300 printable characters")
    return errs


good = {"asset_id": "B-12", "priority": "P2", "summary": "Boiler pressure above limit"}
assert validate(good) == []
poisoned = {
    "odata injection": {**good, "asset_id": "B-12' or PartitionKey ne '"},
    "path traversal": {**good, "asset_id": "../../secrets"},
    "oversized summary": {**good, "summary": "x" * 5000},
    "control characters": {**good, "summary": "ok\x00\x1b[31m"},
    "unknown priority": {**good, "priority": "P0; drop"},
}
for name, call in poisoned.items():
    errs = validate(call)
    assert errs, name + " must be refused"
    print("refused:", name, "->", errs[0])
print("tool contract verified: 5 of 5 poisoned calls refused")
