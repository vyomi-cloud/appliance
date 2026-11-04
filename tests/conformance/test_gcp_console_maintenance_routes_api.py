#!/usr/bin/env python3
"""GCP console maintenance routes: POST /api/gcp/console/{consolidate,vpc-reconcile}
and the un-prefixed /api/sub/artifactregistry/{op}/{name} alias of /api/gcp/sub/..."""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
fails = 0


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def check(name, ok):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    fails += 0 if ok else 1


s, b = call("GET", "/api/gcp/catalog")
project = (b or {}).get("project", "vyomi-project")
s, b = call("POST", "/api/gcp/console/consolidate", {"project": project})
check("consolidate returns project + updated count", s == 200 and b.get("project") == project and isinstance(b.get("updated"), int))
s, b2 = call("POST", "/api/gcp/console/consolidate", {"project": project})
check("consolidate is idempotent (second run updates nothing)", s == 200 and b2.get("updated") == 0)
s, b = call("POST", "/api/gcp/console/vpc-reconcile")
check("vpc-reconcile reports enforcement + instances", s == 200 and "enforced" in b and isinstance(b.get("instances"), list))
s1, a = call("GET", "/api/sub/artifactregistry/listPackages/no-such-repo")
s2, g = call("GET", "/api/gcp/sub/artifactregistry/listPackages/no-such-repo")
check("un-prefixed artifactregistry sub route matches the /api/gcp one", s1 == s2 == 200 and a == g and a.get("ok") is True)
s, b = call("POST", "/api/sub/artifactregistry/getLabels/no-such-repo")
check("getLabels on a missing repository is 404 NotFound", s == 404)
sys.exit(1 if fails else 0)
