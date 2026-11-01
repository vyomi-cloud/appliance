#!/usr/bin/env python3
"""Azure create-and-use regressions (sweep 2026-11-02): RG delete cascade, SQL password echo, APIM.

  python3 sweep_azure.py http://localhost:9000
One [PASS]/[FAIL] line per check, exit 1 on any failure.
"""
import json, subprocess, sys, time, urllib.error, urllib.request

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else "http://localhost:9000").rstrip("/")
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def call(method, path, body=None, headers=None, raw=False):
    h = {"content-type": "application/json"}; h.update(headers or {})
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = r.read(); return r.status, (d if raw else (json.loads(d) if d else {}))
    except urllib.error.HTTPError as e:
        d = e.read()
        try: return e.code, json.loads(d)
        except Exception: return e.code, d.decode("utf-8", "replace")


def containers(prefix):
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    return [n for n in out if prefix in n]


def main():
    sub = call("GET", "/subscriptions?api-version=2020-01-01")[1]["value"][0]["subscriptionId"]
    tag = f"swp{int(time.time()) % 100000}"
    rg = f"/subscriptions/{sub}/resourceGroups/{tag}-rg"
    call("PUT", rg + "?api-version=2021-04-01", {"location": "eastus"})
    # --- Item 3: SQL server never echoes the admin password
    st, sql = call("PUT", f"{rg}/providers/Microsoft.Sql/servers/{tag}sql?api-version=2021-11-01",
                   {"location": "eastus", "properties": {"administratorLogin": "adm", "administratorLoginPassword": "S3cret-Pass!"}})
    check("S3cret-Pass!" not in json.dumps(sql), "SQL server PUT response omits administratorLoginPassword", json.dumps(sql)[:200])
    st, g = call("GET", f"{rg}/providers/Microsoft.Sql/servers/{tag}sql?api-version=2021-11-01")
    check("S3cret-Pass!" not in json.dumps(g) and "administratorLoginPassword" not in json.dumps(g),
          "SQL server GET omits administratorLoginPassword", json.dumps(g)[:200])
    st, lst = call("GET", f"{rg}/providers/Microsoft.Sql/servers?api-version=2021-11-01")
    check("S3cret-Pass!" not in json.dumps(lst), "SQL server LIST omits administratorLoginPassword")
    # --- Item 1: RG delete cascades to runtime + Key Vault data
    kv = f"{tag}kv"
    call("PUT", f"{rg}/providers/Microsoft.KeyVault/vaults/{kv}?api-version=2023-07-01",
         {"location": "eastus", "properties": {"sku": {"family": "A", "name": "standard"}, "tenantId": "00000000-0000-0000-0000-000000000000"}})
    st, _ = call("PUT", f"/azure-data/keyvault/{kv}/secrets/s1", {"value": "topsecret"})
    check(st == 200, "Key Vault secret set", f"HTTP {st}")
    vm = f"{tag}vm"
    call("PUT", f"{rg}/providers/Microsoft.Compute/virtualMachines/{vm}?api-version=2023-09-01", {"location": "eastus", "properties": {
        "hardwareProfile": {"vmSize": "Standard_B1s"},
        "storageProfile": {"imageReference": {"publisher": "Canonical", "offer": "ubuntu-24_04-lts", "sku": "server", "version": "latest"}},
        "osProfile": {"computerName": vm, "adminUsername": "azureuser"}}})
    up = []
    for _ in range(40):
        up = containers(vm)
        if up: break
        time.sleep(2)
    check(bool(up), "Azure VM has a running container", "none found")
    st, _ = call("DELETE", rg + "?api-version=2021-04-01")
    check(st in (200, 202, 204), "RG delete accepted", f"HTTP {st}")
    time.sleep(3)
    check(not containers(vm), "RG delete removed the VM container", str(containers(vm)))
    st, _ = call("GET", f"/azure-data/keyvault/{kv}/secrets/s1")
    check(st != 200, "RG delete destroyed Key Vault secrets (no longer readable)", f"HTTP {st}")
    # --- Item 2: API Management gateway: wrong key 401, unknown API 404, valid flow proxies
    svc = f"{rg}/providers/Microsoft.ApiManagement/service/{tag}apim"
    call("PUT", svc + "?api-version=2023-05-01-preview", {"location": "eastus", "sku": {"name": "Developer", "capacity": 1},
         "properties": {"publisherEmail": "a@b.c", "publisherName": "qa"}})
    call("PUT", svc + "/apis/echo?api-version=2023-05-01-preview",
         {"properties": {"displayName": "echo", "path": "echo", "protocols": ["https"], "serviceUrl": "http://127.0.0.1:9000"}})
    st, sec = call("POST", svc + "/subscriptions/master/listSecrets?api-version=2023-05-01-preview", {})
    key = sec.get("primaryKey") if isinstance(sec, dict) else None
    check(st == 200 and bool(key), "APIM listSecrets returns a primaryKey", f"HTTP {st} {sec}")
    gw = f"/azure-data/apim/{tag}apim"
    st, _ = call("GET", gw + "/echo/healthz", headers={"Ocp-Apim-Subscription-Key": "totallybogus"})
    check(st == 401, "APIM wrong subscription key -> 401", f"HTTP {st}")
    st, _ = call("GET", gw + "/echo/healthz")
    check(st == 401, "APIM missing subscription key -> 401", f"HTTP {st}")
    st, _ = call("GET", gw + "/nosuchapi/x", headers={"Ocp-Apim-Subscription-Key": key or "x"})
    check(st == 404, "APIM unknown API -> 404", f"HTTP {st}")
    st, body = call("GET", gw + "/echo/healthz", headers={"Ocp-Apim-Subscription-Key": key or "x"})
    check(st == 200 and "mock" not in json.dumps(body), "APIM valid key proxies to the backend (no httpx 502)", f"HTTP {st} {str(body)[:120]}")
    sys.exit(1 if fails else 0)


main()
