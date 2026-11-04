"""GCP VM Manager (OS Config patch jobs/deployments, OS policy assignments, VM extension policies) + BYOIP + Interconnect/VLAN attachments.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_vmmanager_hybrid.py"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core import gcp_osconfig_core as OSC  # noqa: E402

R = AwsWireRouter()
PASS = FAIL = 0
P = "vmm-proj-1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


def mkvm(name, zone="us-central1-a", labels=None, osconfig=False):
    body = {"name": name, "machineType": f"zones/{zone}/machineTypes/e2-micro", "labels": labels or {},
            "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
            "networkInterfaces": [{"network": "global/networks/default"}]}
    if osconfig:
        body["metadata"] = {"items": [{"key": "enable-osconfig", "value": "TRUE"}]}
    st, e = call("POST", f"/compute/v1/projects/{P}/zones/{zone}/instances", body)
    assert st == 200, (st, e)


mkvm("web-1", labels={"env": "prod"}, osconfig=True)
mkvm("web-2", labels={"env": "prod"})
mkvm("db-1", labels={"env": "dev"}, osconfig=True)
call("POST", f"/compute/v1/projects/{P}/zones/us-central1-a/instances/db-1/stop")

# ── patch jobs ──
st, e = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {}})
check("empty instanceFilter rejected", st == 400 and e["error"]["status"] == "INVALID_ARGUMENT")
st, e = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {"all": True}, "patchConfig": {"rebootConfig": "SOMETIMES"}})
check("bad rebootConfig rejected", st == 400)
st, e = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {"all": True}, "duration": "10s"})
check("duration below 30m rejected", st == 400)
st, e = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {"all": True}, "patchConfig": {"apt": {"type": "DIST"}}, "displayName": "all"})
check("execute ok", st == 200 and e["state"] == "STARTED" and e["instanceDetailsSummary"]["pendingInstanceCount"] == 3, e)
jid = e["name"].split("/")[-1]
st, e2 = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {"groupLabels": [{"labels": {"env": "nope"}}]}})
check("no match -> NO_INSTANCES_FOUND", e2["state"] == "NO_INSTANCES_FOUND")
st, e3 = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {"instanceNamePrefixes": ["web-"]}})
cid = e3["name"].split("/")[-1]
st, c = call("POST", f"/v1/projects/{P}/patchJobs/{cid}:cancel")
check("cancel in flight", st == 200 and c["state"] == "CANCELED")
st, c = call("POST", f"/v1/projects/{P}/patchJobs/{cid}:cancel")
check("cancel terminal -> FAILED_PRECONDITION", st == 400 and c["error"]["status"] == "FAILED_PRECONDITION")
time.sleep(OSC.PATCH_FINALIZE_SECONDS + 0.3)
st, j = call("GET", f"/v1/projects/{P}/patchJobs/{jid}")
s = j["instanceDetailsSummary"]
check("job settles COMPLETED_WITH_ERRORS", j["state"] == "COMPLETED_WITH_ERRORS", j)
check("summary: 1 ok, 1 inactive, 1 no agent", s["succeededInstanceCount"] == 1 and s["inactiveInstanceCount"] == 1 and s["noAgentDetectedInstanceCount"] == 1, s)
st, d = call("GET", f"/v1/projects/{P}/patchJobs/{jid}/instanceDetails")
check("instanceDetails", st == 200 and {x["state"] for x in d["patchJobInstanceDetails"]} == {"SUCCEEDED", "INACTIVE", "NO_AGENT_DETECTED"}, d)
check("list jobs", len(call("GET", f"/v1/projects/{P}/patchJobs")[1]["patchJobs"]) == 3)
check("get unknown job 404", call("GET", f"/v1/projects/{P}/patchJobs/nope")[0] == 404)

# ── patch deployments ──
base = {"instanceFilter": {"all": True}, "recurringSchedule": {"timeZone": {"id": "UTC"}, "timeOfDay": {"hours": 3, "minutes": 30},
        "frequency": "WEEKLY", "weekly": {"dayOfWeek": "SUNDAY"}}}
st, e = call("POST", f"/v1/projects/{P}/patchDeployments", base, {"patchDeploymentId": "Bad_ID"})
check("bad deployment id", st == 400)
st, e = call("POST", f"/v1/projects/{P}/patchDeployments", {"instanceFilter": {"all": True}}, {"patchDeploymentId": "x1"})
check("schedule required", st == 400)
st, dep = call("POST", f"/v1/projects/{P}/patchDeployments", base, {"patchDeploymentId": "weekly-sun"})
nxt = dep["recurringSchedule"]["nextExecuteTime"]
from datetime import datetime  # noqa: E402
nd = datetime.fromisoformat(nxt.replace("Z", "+00:00"))
check("weekly nextExecuteTime is a Sunday 03:30", st == 200 and nd.weekday() == 6 and (nd.hour, nd.minute) == (3, 30), dep)
check("duplicate -> 409", call("POST", f"/v1/projects/{P}/patchDeployments", base, {"patchDeploymentId": "weekly-sun"})[0] == 409)
st, dp = call("POST", f"/v1/projects/{P}/patchDeployments/weekly-sun:pause")
check("pause", dp["state"] == "PAUSED")
check("pause twice -> 400", call("POST", f"/v1/projects/{P}/patchDeployments/weekly-sun:pause")[0] == 400)
st, dp = call("POST", f"/v1/projects/{P}/patchDeployments/weekly-sun:resume")
check("resume", dp["state"] == "ACTIVE")
monthly = dict(base, recurringSchedule={"timeOfDay": {"hours": 1}, "frequency": "MONTHLY", "monthly": {"weekDayOfMonth": {"weekOrdinal": 2, "dayOfWeek": "TUESDAY"}}})
st, m = call("POST", f"/v1/projects/{P}/patchDeployments", monthly, {"patchDeploymentId": "second-tue"})
nd = datetime.fromisoformat(m["recurringSchedule"]["nextExecuteTime"].replace("Z", "+00:00"))
check("monthly 2nd Tuesday", st == 200 and nd.weekday() == 1 and 8 <= nd.day <= 14, m)
st, pr = call("PATCH", f"/v1/projects/{P}/patchDeployments/weekly-sun", {"description": "d"}, {"updateMask": "description"})
check("patch description", pr["description"] == "d")
check("one-time in the past rejected", call("POST", f"/v1/projects/{P}/patchDeployments", {"instanceFilter": {"all": True}, "oneTimeSchedule": {"executeTime": "2020-01-01T00:00:00Z"}}, {"patchDeploymentId": "past"})[0] == 400)
check("list deployments", len(call("GET", f"/v1/projects/{P}/patchDeployments")[1]["patchDeployments"]) == 2)
# a recurring schedule whose next fire is already due creates real jobs (rewind it)
OSC._x(R.gcp_compute_vm, "osc_patch_deployments")[f"projects/{P}/patchDeployments/weekly-sun"]["recurringSchedule"]["nextExecuteTime"] = "2026-01-01T00:00:00.000000Z"
st, lst = call("GET", f"/v1/projects/{P}/patchDeployments")
check("due schedule fired a job", any(j.get("patchDeployment", "").endswith("weekly-sun") for j in call("GET", f"/v1/projects/{P}/patchJobs")[1]["patchJobs"]))
check("delete deployment", call("DELETE", f"/v1/projects/{P}/patchDeployments/second-tue")[0] == 200 and call("GET", f"/v1/projects/{P}/patchDeployments/second-tue")[0] == 404)

# ── OS policy assignments ──
pol = {"id": "install-nginx", "mode": "ENFORCEMENT", "resourceGroups": [{"resources": [{"id": "nginx", "pkg": {"desiredState": "INSTALLED", "apt": {"name": "nginx"}}}]}]}
asg = {"description": "nginx", "osPolicies": [pol], "instanceFilter": {"inclusionLabels": [{"labels": {"env": "prod"}}]},
       "rollout": {"disruptionBudget": {"fixed": 1}, "minWaitDuration": "60s"}}
Z = "us-central1-a"
base_url = f"/v1/projects/{P}/locations/{Z}/osPolicyAssignments"
check("bad location", call("POST", f"/v1/projects/{P}/locations/us-central1/osPolicyAssignments", asg, {"osPolicyAssignmentId": "a"})[0] == 400)
check("missing policies", call("POST", base_url, {"instanceFilter": {"all": True}}, {"osPolicyAssignmentId": "a"})[0] == 400)
bad = json.loads(json.dumps(asg)); bad["osPolicies"][0]["resourceGroups"][0]["resources"][0]["pkg"] = {"desiredState": "INSTALLED"}
check("pkg without source", call("POST", base_url, bad, {"osPolicyAssignmentId": "a"})[0] == 400)
bad = json.loads(json.dumps(asg)); bad["rollout"]["disruptionBudget"] = {"fixed": 1, "percent": 10}
check("budget fixed+percent", call("POST", base_url, bad, {"osPolicyAssignmentId": "a"})[0] == 400)
bad = json.loads(json.dumps(asg)); bad["osPolicies"][0]["mode"] = "MAYBE"
check("bad mode", call("POST", base_url, bad, {"osPolicyAssignmentId": "a"})[0] == 400)
st, lro = call("POST", base_url, asg, {"osPolicyAssignmentId": "nginx-prod"})
check("create returns done LRO with revision", st == 200 and lro["done"] and "@" in lro["response"]["name"], lro)
check("duplicate -> 409", call("POST", base_url, asg, {"osPolicyAssignmentId": "nginx-prod"})[0] == 409)
st, g = call("GET", base_url + "/nginx-prod")
check("get", st == 200 and g["osPolicies"][0]["id"] == "install-nginx" and g["rolloutState"] == "SUCCEEDED")
check("matched VMs follow labels", OSC.assignment_instances(R.gcp_compute_vm, P, Z, "nginx-prod") == [f"projects/{P}/zones/{Z}/instances/web-1", f"projects/{P}/zones/{Z}/instances/web-2"])
st, up = call("PATCH", base_url + "/nginx-prod", {"description": "v2"}, {"updateMask": "description"})
check("patch creates new revision", up["response"]["description"] == "v2")
st, rv = call("GET", base_url + "/nginx-prod:listRevisions")
check("two revisions", st == 200 and len(rv["osPolicyAssignments"]) == 2, rv)
check("list", len(call("GET", base_url)[1]["osPolicyAssignments"]) == 1)
check("delete", call("DELETE", base_url + "/nginx-prod")[1]["done"] and call("GET", base_url + "/nginx-prod")[0] == 404)

# ── VM extension policies ──
vx = f"/compute/beta/projects/{P}/global/vmExtensionPolicies"
good = {"name": "ops-agent-prod", "extensionPolicies": {"ops-agent": {"pinnedVersion": "2.46.0"}}, "instanceSelectors": [{"labelSelector": {"inclusionLabels": {"env": "prod"}}}],
        "priority": 10, "rolloutOperation": {"rolloutInput": {"predefinedRolloutPlan": "FAST_ROLLOUT"}}}
check("unknown extension", call("POST", vx, dict(good, extensionPolicies={"nope": {}}))[0] == 400)
check("no selectors", call("POST", vx, dict(good, instanceSelectors=[]))[0] == 400)
check("bad rollout plan", call("POST", vx, dict(good, rolloutOperation={"rolloutInput": {"predefinedRolloutPlan": "X"}}))[0] == 400)
st, op = call("POST", vx, good)
check("insert returns compute operation", st == 200 and op["kind"] == "compute#operation" and op["status"] == "DONE", op)
check("duplicate 409", call("POST", vx, good)[0] == 409)
st, g = call("GET", vx + "/ops-agent-prod")
check("get", st == 200 and g["priority"] == 10)
check("blast radius", len(OSC.vm_extension_status(R.gcp_compute_vm, P, "ops-agent-prod")) == 2)
check("list", len(call("GET", vx)[1]["items"]) == 1)
check("delete", call("DELETE", vx + "/ops-agent-prod")[0] == 200 and call("GET", vx + "/ops-agent-prod")[0] == 404)

# ── BYOIP ──
C = f"/compute/v1/projects/{P}"
pap = {"name": "my-block", "ipCidrRange": "203.0.113.0/24", "dnsVerificationIp": "203.0.113.5", "pdpScope": "REGIONAL_PDP"}
check("private range rejected", call("POST", C + "/global/publicAdvertisedPrefixes", dict(pap, ipCidrRange="10.0.0.0/24", dnsVerificationIp="10.0.0.1"))[0] == 400)
check("/25 rejected", call("POST", C + "/global/publicAdvertisedPrefixes", dict(pap, ipCidrRange="203.0.113.0/25"))[0] == 400)
check("verification ip outside", call("POST", C + "/global/publicAdvertisedPrefixes", dict(pap, dnsVerificationIp="198.51.100.1"))[0] == 400)
check("host bits set", call("POST", C + "/global/publicAdvertisedPrefixes", dict(pap, ipCidrRange="203.0.113.5/24"))[0] == 400)
st, op = call("POST", C + "/global/publicAdvertisedPrefixes", pap)
check("pap insert", st == 200 and op["operationType"] == "insert")
check("overlap rejected", call("POST", C + "/global/publicAdvertisedPrefixes", dict(pap, name="other"))[0] == 400)
st, g = call("GET", C + "/global/publicAdvertisedPrefixes/my-block")
check("pap get has sharedSecret + status", g["status"] == "VALIDATED" and g["sharedSecret"])
pdp = {"name": "my-pdp-a", "parentPrefix": "projects/%s/global/publicAdvertisedPrefixes/my-block" % P, "ipCidrRange": "203.0.113.0/25"}
RG = C + "/regions/us-central1/publicDelegatedPrefixes"
check("pdp out of range", call("POST", RG, dict(pdp, ipCidrRange="198.51.100.0/25"))[0] == 400)
check("pdp missing parent", call("POST", RG, dict(pdp, parentPrefix="projects/%s/global/publicAdvertisedPrefixes/zzz" % P))[0] == 404)
check("pdp ok", call("POST", RG, pdp)[0] == 200)
check("pdp overlap", call("POST", RG, dict(pdp, name="b", ipCidrRange="203.0.113.0/26"))[0] == 400)
check("pdp announce needs parent announced", call("POST", RG + "/my-pdp-a/announce")[0] == 400)
check("delete pap in use", call("DELETE", C + "/global/publicAdvertisedPrefixes/my-block")[0] == 400)
check("pap announce", call("POST", C + "/global/publicAdvertisedPrefixes/my-block/announce")[0] == 200)
check("pdp announce", call("POST", RG + "/my-pdp-a/announce")[0] == 200)
check("pap withdraw blocked while pdp announced", call("POST", C + "/global/publicAdvertisedPrefixes/my-block/withdraw")[0] == 400)
check("pdp delete blocked while announced", call("DELETE", RG + "/my-pdp-a")[0] == 400)
st, g = call("GET", C + "/global/publicAdvertisedPrefixes/my-block")
check("parent lists delegated prefix status", g["publicDelegatedPrefixs"][0]["status"] == "ANNOUNCED")
st, sub = call("PATCH", RG + "/my-pdp-a", {"publicDelegatedSubPrefixs": [{"name": "sub1", "ipCidrRange": "203.0.113.0/27"}]})
check("sub prefix delegation", st == 200 and call("GET", RG + "/my-pdp-a")[1]["publicDelegatedSubPrefixs"][0]["name"] == "sub1")
check("agg pdp", "regions/us-central1" in call("GET", C + "/aggregated/publicDelegatedPrefixes")[1]["items"])
call("PATCH", RG + "/my-pdp-a", {"publicDelegatedSubPrefixs": []})
call("POST", RG + "/my-pdp-a/withdraw")
check("pdp delete", call("DELETE", RG + "/my-pdp-a")[0] == 200)
call("POST", C + "/global/publicAdvertisedPrefixes/my-block/withdraw")
check("pap delete", call("DELETE", C + "/global/publicAdvertisedPrefixes/my-block")[0] == 200)

# ── Interconnect + VLAN attachments ──
st, locs = call("GET", C + "/global/interconnectLocations")
check("locations catalog", st == 200 and len(locs["items"]) >= 5)
ic = {"name": "ic-1", "interconnectType": "DEDICATED", "linkType": "LINK_TYPE_ETHERNET_10G_LR", "requestedLinkCount": 1,
      "location": "projects/%s/global/interconnectLocations/iad-zone1-1" % P, "customerName": "Acme", "nocContactEmail": "noc@acme.example", "adminEnabled": True}
check("bad link type", call("POST", C + "/global/interconnects", dict(ic, linkType="X"))[0] == 400)
check("too many links", call("POST", C + "/global/interconnects", dict(ic, linkType="LINK_TYPE_ETHERNET_100G_LR", requestedLinkCount=3))[0] == 400)
check("unknown location", call("POST", C + "/global/interconnects", dict(ic, location="zzz-1"))[0] == 404)
check("ic insert", call("POST", C + "/global/interconnects", ic)[0] == 200)
st, g = call("GET", C + "/global/interconnects/ic-1")
check("ic ACTIVE with circuits", g["state"] == "ACTIVE" and g["provisionedLinkCount"] == 1 and len(g["circuitInfos"]) == 1)
check("diagnostics", call("GET", C + "/global/interconnects/ic-1/getDiagnostics")[1]["result"]["links"][0]["operationalStatus"] == "LINK_OPERATIONAL_STATUS_UP")
att = {"name": "vlan-1", "type": "DEDICATED", "interconnect": "projects/%s/global/interconnects/ic-1" % P, "router": "projects/%s/regions/us-east4/routers/r1" % P,
       "bandwidth": "BPS_1G", "vlanTag8021q": 100}
AR = C + "/regions/us-east4/interconnectAttachments"
check("attachment needs existing router", call("POST", AR, att)[0] == 404)
call("POST", C + "/global/networks", {"name": "vpc1", "autoCreateSubnetworks": False})
st, o = call("POST", C + "/regions/us-east4/routers", {"name": "r1", "network": "global/networks/vpc1"})
check("router created", st == 200, o)
check("bandwidth beyond capacity", call("POST", AR, dict(att, bandwidth="BPS_20G"))[0] == 400)
check("vlan out of range", call("POST", AR, dict(att, vlanTag8021q=1))[0] == 400)
check("attachment ok", call("POST", AR, att)[0] == 200)
check("vlan reuse rejected", call("POST", AR, dict(att, name="vlan-2"))[0] == 400)
st, a = call("GET", AR + "/vlan-1")
check("attachment ACTIVE, link-local /29 pair", a["state"] == "ACTIVE" and a["cloudRouterIpAddress"].startswith("169.254.") and a["operationalStatus"] == "OS_ACTIVE", a)
check("ic delete blocked by attachment", call("DELETE", C + "/global/interconnects/ic-1")[0] == 400)
call("PATCH", C + "/global/interconnects/ic-1", {"adminEnabled": False})
check("disabling ic downs attachment", call("GET", AR + "/vlan-1")[1]["state"] == "UNPROVISIONED")
st, p = call("POST", AR, {"name": "partner-1", "type": "PARTNER", "router": "projects/%s/regions/us-east4/routers/r1" % P, "edgeAvailabilityDomain": "AVAILABILITY_DOMAIN_1"})
check("partner attachment pending with pairing key", st == 200 and call("GET", AR + "/partner-1")[1]["state"] == "PENDING_PARTNER" and "/us-east4/" in call("GET", AR + "/partner-1")[1]["pairingKey"])
check("agg attachments", len(call("GET", C + "/aggregated/interconnectAttachments")[1]["items"]["regions/us-east4"]["interconnectAttachments"]) == 2)
check("att delete", call("DELETE", AR + "/vlan-1")[0] == 200 and call("DELETE", AR + "/partner-1")[0] == 200)
check("ic delete", call("DELETE", C + "/global/interconnects/ic-1")[0] == 200)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
