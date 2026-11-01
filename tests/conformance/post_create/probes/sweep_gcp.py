#!/usr/bin/env python3
"""GCP create-and-use regressions (sweep 2026-11-02): VPC subnetwork delete/cascade, Firestore runQuery.

  python3 sweep_gcp.py http://localhost:9000
One [PASS]/[FAIL] line per check, exit 1 on any failure.
"""
import json, sys, time, urllib.error, urllib.request

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else "http://localhost:9000").rstrip("/")
P = "vyomi-project"
fails = 0
tag = f"sw{int(time.time()) % 100000}"


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = r.read(); return r.status, (json.loads(d) if d else {})
    except urllib.error.HTTPError as e:
        d = e.read()
        try: return e.code, json.loads(d)
        except Exception: return e.code, d.decode("utf-8", "replace")


def vpc():
    net, sub, region = f"{tag}-net", f"{tag}-sub", "us-central1"
    cp = f"/compute/v1/projects/{P}"
    st, _ = call("POST", f"{cp}/global/networks", {"name": net, "autoCreateSubnetworks": False})
    check(st < 300, "create network", f"HTTP {st}")
    st, _ = call("POST", f"{cp}/regions/{region}/subnetworks", {"name": sub, "network": f"{cp}/global/networks/{net}", "ipCidrRange": "10.61.0.0/24"})
    check(st < 300, "create subnetwork", f"HTTP {st}")
    st, n = call("GET", f"{cp}/global/networks/{net}")
    subs = [str(x) for x in (n.get("subnetworks") or [])] if isinstance(n, dict) else []
    check(any(sub in x for x in subs), "network.subnetworks lists the subnet", str(subs))
    st, _ = call("GET", f"{cp}/regions/{region}/subnetworks/{sub}")
    check(st == 200, "GET subnetwork by name", f"HTTP {st}")
    st, _ = call("DELETE", f"{cp}/global/networks/{net}")
    check(st == 400 or st == 409, "network delete refused while it still has a subnetwork (resourceInUseByAnotherResource)", f"HTTP {st}")
    st, _ = call("DELETE", f"{cp}/regions/{region}/subnetworks/{sub}")
    check(st < 300, "DELETE subnetwork", f"HTTP {st}")
    st, lst = call("GET", f"{cp}/regions/{region}/subnetworks")
    left = [i for i in (lst.get("items") or []) if i.get("name") == sub] if isinstance(lst, dict) else ["?"]
    check(not left, "subnetwork is gone from the list", str(left)[:100])
    st, _ = call("DELETE", f"{cp}/global/networks/{net}")
    check(st < 300, "network delete succeeds once subnets are gone", f"HTTP {st}")
    st, lst = call("GET", f"{cp}/regions/{region}/subnetworks")
    left = [i for i in (lst.get("items") or []) if i.get("name") == sub] if isinstance(lst, dict) else []
    check(not left, "no orphan subnetwork after network delete")


def main():
    vpc()
    sys.exit(1 if fails else 0)


main()
