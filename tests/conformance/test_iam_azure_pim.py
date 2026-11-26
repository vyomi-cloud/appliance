"""Azure PIM-style eligible / time-bound role assignments through the REAL server (Mesh): eligibility grants nothing, a SelfActivate request grants
the role for its window, the evaluator stops honouring it at expiry, requests are validated like the native API (policy rules, eligibility,
self-service identity), schedules / instances list with $filter=asTarget()."""
import os, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
import tempfile as _tf
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_tf.mkdtemp(prefix="vyomi-iam-"), "state.sqlite3"))   # never leak enforcement settings between runs
pytest.importorskip("fastapi")

SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
AUTHZ = "/providers/Microsoft.Authorization"
CONTRIBUTOR = "b24988ac-6180-42a0-ab88-20f7382dd24c"
READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
API = "?api-version=2020-10-01"


@pytest.fixture(scope="module")
def env():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    uid = uuid.uuid4().hex[:8]
    rg = f"{SUB}/resourceGroups/rg-pim-{uid}"
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    e = {"c": c, "rg": rg, "uid": uid, "alice": f"oid-alice-{uid}", "bob": f"oid-bob-{uid}"}
    yield e
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    c.delete(rg + "?api-version=2021-04-01")


def _as(who):
    return {"X-Cloudlearn-Principal": who}


def _role(g):
    return f"{SUB}{AUTHZ}/roleDefinitions/{g}"


def _req(c, scope, kind, who=None, **props):
    name = str(uuid.uuid4())
    return c.put(f"{scope}{AUTHZ}/{kind}/{name}{API}", headers=_as(who) if who else {}, json={"properties": props}), name


def _write(e, who, name):
    return e["c"].put(f"{e['rg']}/providers/Microsoft.Storage/storageAccounts/{name}?api-version=2023-01-01", headers=_as(who),
                      json={"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"})


def test_eligibility_grants_nothing_activation_grants_and_expiry_removes(env):
    c, rg = env["c"], env["rg"]
    r, _ = _req(c, rg, "roleEligibilityScheduleRequests", requestType="AdminAssign", principalId=env["alice"], roleDefinitionId=_role(CONTRIBUTOR),
                scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "P30D"}})
    assert r.status_code == 201, r.text
    assert r.json()["properties"]["status"] == "Provisioned" and r.json()["properties"]["targetRoleEligibilityScheduleId"].startswith(rg)
    el = c.get(f"{rg}{AUTHZ}/roleEligibilitySchedules{API}&$filter=asTarget()", headers=_as(env["alice"])).json()["value"]
    assert len(el) == 1 and el[0]["properties"]["principalId"] == env["alice"] and el[0]["properties"]["endDateTime"]
    assert c.get(f"{rg}{AUTHZ}/roleEligibilitySchedules{API}&$filter=asTarget()", headers=_as(env["bob"])).json()["value"] == []

    c.put("/api/iam/azure/enforcement", json={"space": "enforce"})
    assert _write(env, env["alice"], "pim" + env["uid"]).status_code == 403                 # eligible is not active

    act, name = _req(c, rg, "roleAssignmentScheduleRequests", env["alice"], requestType="SelfActivate", principalId=env["alice"],
                     roleDefinitionId=_role(CONTRIBUTOR), justification="deploy",
                     scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "PT1H"}})
    assert act.status_code == 201, act.text
    p = act.json()["properties"]
    assert p["requestType"] == "SelfActivate" and p["targetRoleAssignmentScheduleId"].endswith("/roleAssignmentSchedules/" + name)
    assert _write(env, env["alice"], "pim" + env["uid"]).status_code in (200, 201)           # active now
    assert _write(env, env["bob"], "pimb" + env["uid"]).status_code == 403                  # nobody else benefited

    inst = c.get(f"{rg}{AUTHZ}/roleAssignmentScheduleInstances{API}&$filter=asTarget()", headers=_as(env["alice"])).json()["value"]
    assert len(inst) == 1 and inst[0]["properties"]["assignmentType"] == "Activated" and inst[0]["properties"]["endDateTime"]
    sch = c.get(f"{rg}{AUTHZ}/roleAssignmentSchedules/{name}{API}").json()
    assert sch["properties"]["linkedRoleEligibilityScheduleId"].endswith(el[0]["name"])

    # expiry: move the window into the past -> the evaluator denies again, the schedule drops out of the live lists
    from core import iam_analyze_host
    arm = iam_analyze_host._Host().azure_arm()
    rec = next(v for k, v in arm.items() if k.endswith("/roleassignmentschedules/" + name))
    rec["properties"]["endDateTime"] = "2020-01-01T00:00:00.0000000Z"
    assert _write(env, env["alice"], "pimc" + env["uid"]).status_code == 403
    assert c.get(f"{rg}{AUTHZ}/roleAssignmentScheduleInstances{API}&$filter=asTarget()", headers=_as(env["alice"])).json()["value"] == []
    c.put("/api/iam/azure/enforcement", json={"space": "off"})


def test_activation_validation_like_the_native_api(env):
    c, rg = env["c"], env["rg"]
    _req(c, rg, "roleEligibilityScheduleRequests", requestType="AdminAssign", principalId=env["bob"], roleDefinitionId=_role(READER),
         scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "P1D"}})
    # nothing eligible for this role
    r, _ = _req(c, rg, "roleAssignmentScheduleRequests", env["bob"], requestType="SelfActivate", principalId=env["bob"], roleDefinitionId=_role(CONTRIBUTOR),
                scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "PT1H"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "RoleAssignmentRequestNoEligibility"
    # longer than the 8 h maximum activation
    r, _ = _req(c, rg, "roleAssignmentScheduleRequests", env["bob"], requestType="SelfActivate", principalId=env["bob"], roleDefinitionId=_role(READER),
                scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "PT9H"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "RoleAssignmentRequestPolicyValidationFailed" and "ExpirationRule" in r.json()["error"]["message"]
    # self-service for somebody else
    r, _ = _req(c, rg, "roleAssignmentScheduleRequests", env["alice"], requestType="SelfActivate", principalId=env["bob"], roleDefinitionId=_role(READER),
                scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "PT1H"}})
    assert r.status_code == 403
    # malformed
    r, _ = _req(c, rg, "roleAssignmentScheduleRequests", requestType="Bogus", principalId=env["bob"], roleDefinitionId=_role(READER))
    assert r.status_code == 400 and r.json()["error"]["code"] == "InvalidRequestContent"
    r, _ = _req(c, rg, "roleAssignmentScheduleRequests", requestType="AdminAssign", principalId=env["bob"], roleDefinitionId=_role(READER),
                scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "tomorrow"}})
    assert r.status_code == 400
    # deactivate removes the grant
    ok, name = _req(c, rg, "roleAssignmentScheduleRequests", env["bob"], requestType="SelfActivate", principalId=env["bob"], roleDefinitionId=_role(READER),
                    scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "PT2H"}})
    assert ok.status_code == 201
    d, _ = _req(c, rg, "roleAssignmentScheduleRequests", env["bob"], requestType="SelfDeactivate", principalId=env["bob"], roleDefinitionId=_role(READER))
    assert d.status_code == 201
    assert c.get(f"{rg}{AUTHZ}/roleAssignmentSchedules{API}&$filter=asTarget()", headers=_as(env["bob"])).json()["value"] == []
    assert c.post(f"{rg}{AUTHZ}/roleAssignmentScheduleRequests/{name}/cancel{API}").status_code == 400      # already provisioned


def test_admin_assign_time_bound_active_assignment_and_request_listing(env):
    c, rg = env["c"], env["rg"]
    who = "oid-tb-" + env["uid"]
    r, name = _req(c, rg, "roleAssignmentScheduleRequests", requestType="AdminAssign", principalId=who, roleDefinitionId=_role(CONTRIBUTOR),
                   scheduleInfo={"expiration": {"type": "AfterDuration", "duration": "PT30M"}})
    assert r.status_code == 201 and r.json()["properties"]["scheduleInfo"]["expiration"]["duration"] == "PT30M"
    c.put("/api/iam/azure/enforcement", json={"space": "enforce"})
    assert _write(env, who, "tb" + env["uid"]).status_code in (200, 201)
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    lst = c.get(f"{rg}{AUTHZ}/roleAssignmentScheduleRequests{API}").json()["value"]
    assert any(v["name"] == name for v in lst)
    assert c.get(f"{rg}{AUTHZ}/roleAssignmentScheduleRequests/{name}{API}").json()["properties"]["principalId"] == who
    assert c.get(f"{rg}{AUTHZ}/roleAssignmentScheduleRequests/{uuid.uuid4()}{API}").status_code == 404
