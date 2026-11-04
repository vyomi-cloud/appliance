"""GCE instance ssh-keys metadata + OS info (Vyomi verbs :sshKeys / :osInfo) on the Compute core."""
import base64
import json
import struct

from core import gcp_compute_instances_core as gce

PROJECT, ZONE = "demo-proj", "us-central1-a"
BASE = "/compute/v1/projects/%s" % PROJECT


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    print("  ok ", name)


def key(seed=b"x"):
    t = b"ssh-ed25519"
    blob = struct.pack(">I", len(t)) + t + struct.pack(">I", 32) + (seed * 32)[:32]
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " me@laptop"


def call(store, method, path, body=None):
    r = gce.dispatch(store, method, BASE + path, {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body.decode())


s = gce.ComputeStore()
st, _ = call(s, "POST", "/zones/%s/instances" % ZONE, {"name": "vm1", "machineType": "e2-medium",
             "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}]})
ok("insert", st == 200)
st, b = call(s, "GET", "/zones/%s/instances/vm1:sshKeys" % ZONE)
ok("no keys initially", st == 200 and b["effectiveKeys"] == [] and not b["blockProjectSshKeys"])
st, b = call(s, "POST", "/zones/%s/instances/vm1:sshKeys" % ZONE, {"sshKeys": "alice:" + key(b"a")})
ok("set instance key", st == 200)
st, b = call(s, "GET", "/zones/%s/instances/vm1" % ZONE)
ok("metadata item is real state", any(i["key"] == "ssh-keys" and i["value"].startswith("alice:") for i in b["metadata"]["items"]))
st, b = call(s, "POST", "/zones/%s/instances/vm1:sshKeys" % ZONE, {"sshKeys": "bob-no-key"})
ok("malformed line rejected", st == 400 and b["error"]["status"] == "INVALID_ARGUMENT")
st, b = call(s, "POST", "/zones/%s/instances/vm1:sshKeys" % ZONE, {"sshKeys": "alice:ssh-ed25519 AAAAnotvalid"})
ok("bad key blob rejected", st == 400)
call(s, "POST", "/setCommonInstanceMetadata", {"items": [{"key": "ssh-keys", "value": "carol:" + key(b"c")}]})
st, b = call(s, "GET", "/zones/%s/instances/vm1:sshKeys" % ZONE)
ok("project key merged", [k["user"] for k in b["effectiveKeys"]] == ["alice", "carol"] and b["effectiveKeys"][0]["fingerprint"].startswith("SHA256:"))
call(s, "POST", "/zones/%s/instances/vm1:sshKeys" % ZONE, {"sshKeys": "alice:" + key(b"a"), "blockProjectSshKeys": True})
st, b = call(s, "GET", "/zones/%s/instances/vm1:sshKeys" % ZONE)
ok("block-project-ssh-keys honoured", b["blockProjectSshKeys"] and [k["user"] for k in b["effectiveKeys"]] == ["alice"])
st, b = call(s, "GET", "/zones/%s/instances/vm1:osInfo" % ZONE)
ok("os info declared from image", st == 200 and b["id"] == "debian" and b["source"] == "image")
st, b = call(s, "GET", "/zones/%s/instances/nope:sshKeys" % ZONE)
ok("unknown instance 404", st == 404)
print("PASS test_gce_ssh_metadata")
