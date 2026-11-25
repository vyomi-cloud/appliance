"""Nano substrate for the identity depth work: the same engine modules over the Nano state adapter (iam_state_nano) and the Nano bridge host.
PIM eligibility -> activation -> access, STS trust evaluation and the IAM events API run with NO Mesh provider modules (a fake nano registry)."""
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

SUB = "/subscriptions/s1"
READER = "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"


class _Arm:
    def __init__(self):
        self.state = {}


def _registry(arm):
    from core import nano_registry
    nano_registry.get = lambda: {"az_arm": arm}      # the page's in-browser ARM core, as nano_registry exposes it
    return nano_registry


def test_pim_activation_grants_access_on_the_nano_adapter_and_events_api_serves_it():
    from core.iam_engine import azure_pim, azure_eval as E, api as iam_api
    from core import iam_events_core as ev, iam_state_nano
    from core.iam_engine import catalog_loader
    catalog_loader.reset(); catalog_loader.set_reader(None)
    catalog_loader.preload('azure', '_roles', open(os.path.join(ROOT, 'core', 'iam_catalog', 'azure', '_roles.json')).read())
    arm = _Arm()
    _registry(arm)
    sc = SUB + "/resourceGroups/rg1"
    now = time.time()
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))   # noqa: E731
    azure_pim.put_request(arm.state, sc, azure_pim.ELIG_REQ, "11111111-1111-1111-1111-111111111111", {"properties": {"requestType": "AdminAssign", "principalId": "u1", "roleDefinitionId": READER,
                          "scheduleInfo": {"startDateTime": iso(now - 60), "expiration": {"type": "NoExpiration"}}}}, caller={"object_id": "admin"})
    st = iam_state_nano.azure_state({'az_arm': arm})
    assert not any(ra.get("principal_id") == "u1" for ra in st["role_assignments"])            # eligible grants nothing
    azure_pim.put_request(arm.state, sc, azure_pim.ACT_REQ, "22222222-2222-2222-2222-222222222222", {"properties": {"requestType": "SelfActivate", "principalId": "u1", "roleDefinitionId": READER,
                          "scheduleInfo": {"startDateTime": iso(now), "expiration": {"type": "AfterDuration", "duration": "PT1H"}}}}, caller={"object_id": "u1"})
    st = iam_state_nano.azure_state({'az_arm': arm})
    act = [ra for ra in st["role_assignments"] if ra.get("principal_id") == "u1"]
    assert act and E._active(act[0])                                                              # activated: live, with an end time
    # the events API on the Nano shape (no Mesh trail; GCP/Azure ring + decisions)
    ev.record("azure", "microsoft.authorization", "roleAssignmentScheduleRequests/write", "u1", sc, "success", "", "", False, {}, operationName="Microsoft.Authorization/roleAssignmentScheduleRequests/write")
    api = iam_api.IamApi(state_fn=lambda c: st, catalog_fn=lambda c, s: None, inventory_fn=lambda: None)
    status, out = api.handle("GET", "/api/iam/azure/events", {"scope": "all"}, None)
    assert status == 200 and any("roleAssignmentScheduleRequests" in e["name"] for e in out["events"])
    status, out = api.handle("GET", "/api/iam/azure/events/export", {"format": "csv"}, None)
    assert status == 200 and out["contentType"] == "text/csv" and out["body"].startswith("time,cloud,service,name,principal")
