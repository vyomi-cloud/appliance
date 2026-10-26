"""EC2 console detail pages call GET /api/ec2/instances/{id}; it must return the instance."""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
fails = 0


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(name, ok):
    global fails
    print(("[PASS] " if ok else "[FAIL] ") + name)
    fails += 0 if ok else 1


st, created = call("POST", "/api/ec2/instances", {"name": "get-by-id-check"})
iid = (created.get("instance") or created).get("instance_id", "")
check("create instance returns an id", bool(iid))
st, inst = call("GET", f"/api/ec2/instances/{iid}")
check("GET /api/ec2/instances/{id} returns 200", st == 200)
check("GET returns that instance", inst.get("instance_id") == iid and inst.get("state"))
st, _ = call("GET", "/api/ec2/instances/i-doesnotexist")
check("unknown id returns 404", st == 404)
if iid:
    call("POST", f"/api/ec2/instances/{iid}/terminate")
sys.exit(1 if fails else 0)
