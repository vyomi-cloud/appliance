#!/usr/bin/env python3
"""Post-create probe (offline): Azure role assignments created over ARM must drive checkAccess; built-in roles must list.
  python3 azure_rbac.py http://localhost:9000"""
import json, os, sys, urllib.error, urllib.request

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
S = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
AU = S + "/providers/Microsoft.Authorization"
READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
PID, RA = "11111111-2222-3333-4444-" + os.urandom(6).hex(), "aaaa0002-0000-0000-0000-" + os.urandom(6).hex()
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = r.read()
            return r.status, (json.loads(d) if d else {})
    except urllib.error.HTTPError as e:
        d = e.read()
        return e.code, (json.loads(d) if d else {})


def can(action):
    s, r = call("POST", AU + "/checkAccess?api-version=2018-09-01-preview", {"subject": {"principalId": PID}, "actions": [{"id": action}], "resource": {"id": S}})
    return r["value"][0]["accessDecision"] if s == 200 else f"HTTP {s} {r}"


s, r = call("GET", AU + "/roleDefinitions?api-version=2022-04-01")
names = [x["properties"]["roleName"] for x in r.get("value", [])]
check({"Owner", "Contributor", "Reader"} <= set(names), "built-in roles list over ARM (Owner, Contributor, Reader, ...)", names)
check(can("Microsoft.Compute/virtualMachines/read") == "NotAllowed", "before assignment: NotAllowed", can("Microsoft.Compute/virtualMachines/read"))
try:
    s, r = call("PUT", f"{AU}/roleAssignments/{RA}?api-version=2022-04-01", {"properties": {"roleDefinitionId": f"{AU}/roleDefinitions/{READER}", "principalId": PID, "principalType": "ServicePrincipal"}})
    check(s in (200, 201), "ARM PUT roleAssignment (Reader)", (s, r))
    check(can("Microsoft.Compute/virtualMachines/read") == "Allowed", "Reader can read (checkAccess Allowed)", can("Microsoft.Compute/virtualMachines/read"))
    check(can("Microsoft.Compute/virtualMachines/write") == "NotAllowed", "Reader cannot write", can("Microsoft.Compute/virtualMachines/write"))
finally:
    call("DELETE", f"{AU}/roleAssignments/{RA}?api-version=2022-04-01")
check(can("Microsoft.Compute/virtualMachines/read") == "NotAllowed", "after DELETE the access is revoked", can("Microsoft.Compute/virtualMachines/read"))
sys.exit(1 if fails else 0)
