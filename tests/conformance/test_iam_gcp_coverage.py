"""WP gcp-coverage: the request surface, the two coverage numbers, the hierarchy/group/PAB state builder and opaque-token identity.
Pure (no server): the real-store end-to-end is test_iam_gcp_hierarchy_e2e.py."""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]

from core.iam_engine import map_gcp, gcp_eval  # noqa: E402
from core import iam_state_adapters as A, iam_state_nano as N, gcp_iamcredentials_core as IC  # noqa: E402


def _j(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return json.load(f)


# --------------------------------------------------------------------------- map
def _acts(m, url, host=None, body=None):
    return [r["action"] for r in map_gcp.required(m, url, body, host)]


def test_methods_that_used_to_be_unmapped_now_map():
    assert _acts("POST", "/v1/projects/p/triggers", "cloudbuild.googleapis.com") == ["cloudbuild.builds.create"]
    assert _acts("DELETE", "/v1/projects/p/locations/l/triggers/t", "cloudbuild.googleapis.com") == ["cloudbuild.builds.update"]
    assert _acts("GET", "/v2/projects/p/metrics/m", "logging.googleapis.com") == ["logging.logMetrics.get"]
    assert _acts("GET", "/v1/projects/p/policy", "binaryauthorization.googleapis.com") == ["binaryauthorization.policy.get"]
    assert _acts("GET", "/v1/projects/p/locations/l/workloadIdentityPools", "iam.googleapis.com") == ["iam.googleapis.com_workloadIdentityPools.list"]
    got = _acts("POST", "/compute/v1/projects/p/regions/r/firewallPolicies/x/addRule", "compute.googleapis.com")
    assert got and got[0].endswith("irewallPolicies.update"), got       # network firewall policy rules edit the policy (previously unmapped)


def test_alpha_and_beta_versions_map_like_v1():
    for u, h in (("/compute/beta/projects/p/zones/z/instances/i", "compute.googleapis.com"),
                 ("/compute/alpha/projects/p/zones/z/instances/i", "compute.googleapis.com"),
                 ("/v1beta1/projects/p/locations/l/instances/i", "redis.googleapis.com")):
        r = map_gcp.required("GET", u, host=h)
        assert r and r[0]["action"].endswith(".get") and "beta" not in r[0]["resource"] and "alpha" not in r[0]["resource"], (u, r)


def test_flat_paths_tell_resources_apart():
    """The generic /v1/{+name} used to match any resource; the flat path names the collection."""
    assert _acts("GET", "/v1/projects/p/locations/l/indexes/i", "aiplatform.googleapis.com") == ["aiplatform.indexes.get"]
    assert _acts("GET", "/v1/projects/p/locations/l/endpoints/e", "aiplatform.googleapis.com") == ["aiplatform.endpoints.get"]
    assert _acts("GET", "/v1/projects/p/locations/l/clusters/c", "container.googleapis.com") == ["container.clusters.get"]


def test_vyomi_marketplace_and_hub_routes():
    r = map_gcp.required("POST", "/vyomi/gcp/proj/marketplace/subscriptions")
    assert [x["action"] for x in r] == ["consumerprocurement.orders.place"] and r[0]["resource"].endswith("/projects/proj")
    assert _acts("GET", "/vyomi/gcp/proj/marketplace/products/abc") == ["commerceoffercatalog.offers.get"]
    assert set(_acts("GET", "/vyomi/gcp/proj/hub/overview")) == {"servicehealth.events.list", "apphub.applications.list"}


def test_every_method_with_a_permission_round_trips():
    bad = [x["id"] for x in map_gcp.surface() if x["perm"] and not x["mapped"]]
    assert not bad, "methods whose synthesized request does not resolve to their own permission: %s" % bad[:20]


def test_every_emitted_permission_is_in_the_verbatim_catalog():
    cat = set()
    for fn in os.listdir(os.path.join(ROOT, "core", "iam_catalog", "gcp")):
        if not fn.startswith("_"):
            cat |= set(_j("core", "iam_catalog", "gcp", fn)["permissions"])
    emitted = {p for m in _j("core", "iam_catalog", "gcp", "_methods.json")["methods"] for p in m["perm"]}
    assert not emitted - cat, sorted(emitted - cat)[:10]


# --------------------------------------------------------------------------- coverage definition
def _rows():
    return [r for r in _j("wasm", "iam-coverage.json")["services"] if r["cloud"] == "gcp"]


def test_three_services_got_a_catalog_slice():
    by = {r["id"]: r for r in _rows()}
    assert by["security/binauthz"]["catalog"] == ["binaryauthorization"]
    assert by["marketplace"]["catalog"] == ["consumerprocurement", "commerceoffercatalog"]
    assert by["cloud-hub"]["catalog"] == ["servicehealth", "apphub"]
    assert all(r["catalog"] != "none" for r in by.values())


def test_enforceable_follows_the_surface_number_and_strict_has_its_own_floor():
    rows = _rows()
    for r in rows:
        assert r["enforceable"] == (r["mapped_pct"] >= 90.0), r["id"]
        assert r["strict_pct"] >= r["strict_floor"], "%s catalog reach %.1f below floor %d" % (r["id"], r["strict_pct"], r["strict_floor"])
        assert r["surface_methods"] > 0, r["id"]
    assert sum(r["enforceable"] for r in rows) >= 21


# --------------------------------------------------------------------------- hierarchy / groups / PAB state
class _RM:
    def __init__(self):
        self.organizations = {"organizations/1": {}}
        self.folders = {"folders/10": {"name": "folders/10", "parent": "organizations/1", "state": "ACTIVE"},
                        "folders/11": {"name": "folders/11", "parent": "folders/10", "state": "ACTIVE"}}
        self.projects = {"p1": {"name": "projects/555", "projectId": "p1", "parent": {"type": "folder", "id": "11"}}}
        self.groups = {"groups/a": {"groupKey": {"id": "devs@x.com"}}, "groups/b": {"groupKey": {"id": "all@x.com"}}}
        self.group_memberships = {"groups/a/memberships/1": {"preferredMemberKey": {"id": "u@x.com"}},
                                  "groups/b/memberships/1": {"preferredMemberKey": {"id": "devs@x.com"}},
                                  "groups/b/memberships/2": {"preferredMemberKey": {"id": "sa@p.iam.gserviceaccount.com"}}}
        self.pab_policies = {"organizations/1/locations/global/principalAccessBoundaryPolicies/pp": {
            "name": "organizations/1/locations/global/principalAccessBoundaryPolicies/pp",
            "details": {"rules": [{"resources": ["//cloudresourcemanager.googleapis.com/projects/555"], "effect": "ALLOW"}]}}}
        self.pab_bindings = {"b": {"policy": "organizations/1/locations/global/principalAccessBoundaryPolicies/pp",
                                   "target": {"principal": "principal://goog/subject/u@x.com"}}}


def _state(rm=None, config=None):
    st = {"cloud": "gcp", "allow_policies": {"projects/555": {"bindings": [{"role": "roles/storage.objectViewer", "members": ["group:all@x.com"]}]},
                                             "folders/10": {"bindings": [{"role": "roles/storage.objectViewer", "members": ["user:f@x.com"]}]}},
          "deny_policies": {}, "custom_roles": {}, "hierarchy": {"projects/_": "projects/p1"}}
    return A.apply_hierarchy(st, A.gcp_hierarchy_extras(rm, config))


def _can(st, member, resource="//storage.googleapis.com/projects/_/buckets/b", perm="storage.objects.list"):
    return gcp_eval.evaluate({"principal": A.gcp_member(member), "action": perm, "resource": resource, "context": {}}, st)["allowed"]


def test_store_chain_groups_and_number_alias():
    rm = _RM()
    ex = A.gcp_hierarchy_extras(rm)
    assert ex["hierarchy"]["projects/p1"] == "folders/11" and ex["hierarchy"]["folders/11"] == "folders/10" and ex["hierarchy"]["folders/10"] == "organizations/1"
    assert ex["project_aliases"] == {"projects/555": "projects/p1"}
    assert ex["groups"]["group:all@x.com"] == ["group:devs@x.com", "serviceAccount:sa@p.iam.gserviceaccount.com"]
    st = _state(rm)
    assert _can(st, "user:f@x.com")                                   # folder binding reaches the bucket through project -> folder
    assert _can(st, "serviceAccount:sa@p.iam.gserviceaccount.com")    # group member; the binding was attached by project NUMBER
    assert not _can(st, "user:nobody@x.com")


def test_nested_group_and_pab():
    st = _state(_RM())
    # u@x.com: member of devs (-> all) so the project binding applies, but the PAB only lists projects/555 == p1 (alias) -> inside
    assert _can(st, "user:u@x.com")
    rm = _RM()
    rm.pab_policies[next(iter(rm.pab_policies))]["details"]["rules"][0]["resources"] = ["//cloudresourcemanager.googleapis.com/projects/other"]
    st = _state(rm)
    d = gcp_eval.evaluate({"principal": A.gcp_member("user:u@x.com"), "action": "storage.objects.list",
                           "resource": "//storage.googleapis.com/projects/_/buckets/b", "context": {}}, st)
    assert d["allowed"] is False and d["reason"] == "explicit_deny" and d["matched"][0]["source"] == "pab"


def test_config_fills_what_the_store_does_not_hold():
    cfg = {"parents": {"projects/p1": "folders/10"}, "groups": {"group:cfg@x.com": ["user:c@x.com"]}}
    ex = A.gcp_hierarchy_extras(None, cfg)
    assert ex["hierarchy"] == {"projects/p1": "folders/10"} and ex["groups"] == {"group:cfg@x.com": ["user:c@x.com"]}
    st = {"cloud": "gcp", "allow_policies": {"folders/10": {"bindings": [{"role": "roles/storage.objectViewer", "members": ["group:cfg@x.com"]}]}},
          "deny_policies": {}, "custom_roles": {}, "hierarchy": {"projects/_": "projects/p1"}}
    A.apply_hierarchy(st, ex)
    assert _can(st, "user:c@x.com") and not _can(st, "user:d@x.com")
    # the store wins over the config on a conflict
    rm = _RM()
    ex2 = A.gcp_hierarchy_extras(rm, {"parents": {"projects/p1": "folders/99"}})
    assert ex2["hierarchy"]["projects/p1"] == "folders/11"


def test_project_without_a_record_hangs_off_the_organization():
    rm = _RM()
    rm.projects = {}
    st = {"cloud": "gcp", "allow_policies": {"organizations/1": {"bindings": [{"role": "roles/storage.objectViewer", "members": ["user:o@x.com"]}]}},
          "deny_policies": {}, "custom_roles": {}, "hierarchy": {"projects/_": "projects/vyomi-project"}}
    A.apply_hierarchy(st, A.gcp_hierarchy_extras(rm))
    assert st["hierarchy"]["projects/vyomi-project"] == "organizations/1"
    assert _can(st, "user:o@x.com")


# --------------------------------------------------------------------------- opaque tokens
def test_issued_access_token_is_recorded_as_a_hash_and_resolves_to_its_service_account():
    store = IC.IamCredentialsStore()
    out = IC.generate_access_token(store, "sa@p.iam.gserviceaccount.com", {"scope": ["s"]})
    tok = out["accessToken"]
    assert tok not in json.dumps(store.tokens) and len(store.tokens) == 1          # the secret itself is never stored
    assert IC.principal_for_token(store, tok) == "serviceAccount:sa@p.iam.gserviceaccount.com"
    assert IC.principal_for_token(store, "ya29.other") is None
    assert IC.principal_for_token(store, tok, now=time.time() + 10 ** 6) is None   # expired


def test_adapters_resolve_ya29_for_mesh_and_nano():
    store = IC.IamCredentialsStore()
    tok = IC.generate_access_token(store, "sa@p.iam.gserviceaccount.com", {"scope": ["s"]})["accessToken"]
    h = {"Authorization": "Bearer " + tok}
    assert A.gcp_principal(h, {}, store, None)["member"] == "serviceAccount:sa@p.iam.gserviceaccount.com"
    assert N.gcp_principal(h, {"gcp_iamc": store})["member"] == "serviceAccount:sa@p.iam.gserviceaccount.com"
    assert N.gcp_principal({"Authorization": "Bearer ya29.never"}, {"gcp_iamc": store})["type"] == "root"     # unknown token: unchanged
    assert N.gcp_principal({"X-Cloudlearn-Principal": "user:o@x.com", **h}, {"gcp_iamc": store})["member"] == "user:o@x.com"   # explicit override wins
    sts = {"ya29.vyomi-1": {"principal": "principal://iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/pool/subject/s1",
                            "attributes": {"repo": "r"}, "provider": "projects/1/locations/global/workloadIdentityPools/pool/providers/gh", "exp": int(time.time()) + 60}}
    p = A.gcp_principal({"Authorization": "Bearer ya29.vyomi-1"}, {}, None, sts)
    assert p["member"].endswith("/subject/s1") and p["pool"].endswith("workloadIdentityPools/pool")
    sts["ya29.vyomi-1"]["exp"] = int(time.time()) - 1
    assert A.gcp_principal({"Authorization": "Bearer ya29.vyomi-1"}, {}, None, sts)["type"] == "root"
