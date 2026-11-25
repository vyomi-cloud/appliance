"""Nano host adapters (core/iam_state_nano.py): engine `state` + principal from the in-browser registry shapes, lazy multi-catalog need,
and the full bridge path (real map + real engine + real gate) per cloud. The registry is a plain stand-in with the SAME attributes the
Nano stores have (InMemoryIamStore, gcp_* namespaces, AzureArm.state). Browser proof: wasm/ui-tests/iam/iam-hook-e2e.mjs."""
import ast
import base64
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CAT = ROOT / "core" / "iam_catalog"


def _jwt(c):
    return "x." + base64.urlsafe_b64encode(json.dumps(c).encode()).decode().rstrip("=") + ".y"


def test_module_is_pure_python_no_server_stack():
    src = (ROOT / "core" / "iam_state_nano.py").read_text()
    names = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            names.add(n.module.split(".")[0])
    assert not names & {"fastapi", "starlette", "socket", "sqlite3", "requests", "boto3", "subprocess", "uvicorn"}, names
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
for m in ('fastapi','starlette','socket','_socket','requests','boto3','sqlite3'): sys.modules[m] = None
from core import iam_state_nano
print('OK')
"""
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, env={"PYTHONPATH": str(ROOT)}, capture_output=True, text=True)
    assert r.stdout.startswith("OK"), r.stdout + r.stderr


@pytest.fixture
def N():
    from core.iam_engine import catalog_loader
    from core import iam_state_nano
    catalog_loader.reset(); catalog_loader.set_reader(None)
    iam_state_nano.set_known({c: [p.stem for p in (CAT / c).glob("*.json")] for c in ("aws", "gcp", "azure")})
    yield iam_state_nano
    catalog_loader.reset()


def preload(cloud, svc):
    from core.iam_engine import catalog_loader
    catalog_loader.preload(cloud, svc, (CAT / cloud / f"{svc}.json").read_text())


def aws_registry():
    from core.iam_store import InMemoryIamStore
    s = InMemoryIamStore()
    u = {"user_name": "alice", "arn": "arn:aws:iam::123456789012:user/alice", "inline_policies": {"p": {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}]}}, "attached_policies": [], "groups": [], "tags": {}}
    s.users["alice"] = u
    s.access_keys["AKIAALICE0000000001"] = {"user_name": "alice", "status": "Active"}
    return {"iam": s}


def test_aws_principal_and_state_from_the_nano_store(N):
    reg = aws_registry()
    hdr = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAALICE0000000001/20261123/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"}
    st, pr = N.state_and_principal("aws", hdr, "", reg)
    assert pr["arn"] == "arn:aws:iam::123456789012:user/alice" and pr["type"] == "user"
    assert st["principals"][pr["arn"]]["policies"][0]["document"]["Statement"][0]["Action"] == "s3:GetObject"
    _, unk = N.state_and_principal("aws", {"Authorization": hdr["Authorization"].replace("AKIAALICE0000000001", "AKIAOTHER")}, "", reg)
    assert unk["type"] == "unknown"


def test_gcp_state_shape_and_one_need_listing_every_missing_catalog(N):
    from core.iam_store import InMemoryIamStore
    s = InMemoryIamStore()
    s.gcp_iam_policies = {"projects/p": {"version": 1, "bindings": [{"role": "roles/storage.objectViewer", "members": ["user:a@x.com"]},
                                                                    {"role": "roles/pubsub.editor", "members": ["user:a@x.com"]}]}}
    s.gcp_deny_policies = {"cloudresourcemanager.googleapis.com%2Fprojects%2Fp": {"d1": {"name": "d1", "rules": [{"denyRule": {"deniedPermissions": ["storage.objects.delete"]}}]}}}
    s.gcp_custom_roles = {"projects/p/roles/x": {"includedPermissions": ["storage.objects.get"]}}
    gcs = types.SimpleNamespace(buckets={"bkt": {}})
    reg = {"gcp_iam": s, "gcs": gcs}
    with pytest.raises(Exception) as ei:
        N.state_and_principal("gcp", {}, "", reg)
    assert ei.value.needs == [["gcp", "_methods"]]                      # the request map first
    preload("gcp", "_methods")
    with pytest.raises(Exception) as ei:
        N.state_and_principal("gcp", {}, "", reg)
    assert ei.value.needs == [["gcp", "pubsub"], ["gcp", "storage"]]    # ALL missing at once: one prefetch round, not one per service
    preload("gcp", "pubsub"); preload("gcp", "storage")
    st, pr = N.state_and_principal("gcp", {"authorization": "Bearer " + _jwt({"email": "a@x.com"})}, "", reg)
    assert pr == {"member": "user:a@x.com", "type": "user"}
    assert st["allow_policies"]["projects/p"]["bindings"][0]["role"] == "roles/storage.objectViewer"
    assert st["deny_policies"]["cloudresourcemanager.googleapis.com/projects/p"][0]["name"] == "d1"
    assert st["hierarchy"] == {"projects/_/buckets/bkt": "projects/p"} and "projects/p/roles/x" in st["custom_roles"]
    assert "storage.objects.get" in st["catalog"]["roles"]["roles/storage.objectViewer"]
    assert N.gcp_principal({"authorization": "Bearer ya29.opaque"})["type"] == "root"


def test_gcp_basic_role_needs_every_service_catalog(N):
    from core.iam_store import InMemoryIamStore
    s = InMemoryIamStore()
    s.gcp_iam_policies = {"projects/p": {"bindings": [{"role": "roles/editor", "members": ["user:a@x.com"]}]}}
    preload("gcp", "_methods")
    with pytest.raises(Exception) as ei:
        N.state_and_principal("gcp", {}, "", {"gcp_iam": s})
    assert len(ei.value.needs) == len([p for p in (CAT / "gcp").glob("*.json") if not p.stem.startswith("_")])


def test_azure_state_shape_principal_and_roles_need(N):
    sc = "/subscriptions/s1"
    arm = types.SimpleNamespace(state={
        "ra1": {"id": sc + "/providers/Microsoft.Authorization/roleAssignments/ra1", "name": "ra1", "_type": "microsoft.authorization/roleassignments",
                "properties": {"principalId": "oid-1", "roleDefinitionId": sc + "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7",
                               "scope": sc, "principalType": "User"}},
        "rd1": {"id": "rd1", "name": "rd1", "_type": "microsoft.authorization/roledefinitions", "properties": {"roleName": "X", "permissions": [{"actions": ["a/b/read"]}]}},
        "rg": {"id": sc + "/resourceGroups/rg", "_type": "microsoft.resources/subscriptions/resourcegroups"}})
    reg = {"az_arm": arm, "az_graph": types.SimpleNamespace(group_members={"g1": {"oid-1"}})}
    with pytest.raises(Exception) as ei:
        N.state_and_principal("azure", {}, "", reg)
    assert ei.value.needs == [["azure", "_roles"]]
    preload("azure", "_roles")
    st, pr = N.state_and_principal("azure", {"authorization": "Bearer " + _jwt({"oid": "oid-1"})}, "", reg)
    assert pr["object_id"] == "oid-1" and pr["type"] == "User"
    assert st["role_assignments"] == [{"id": sc + "/providers/Microsoft.Authorization/roleAssignments/ra1", "principal_id": "oid-1", "principal_type": "User",
                                       "scope": sc, "role_definition_id": sc + "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7",
                                       "condition": None, "condition_version": None}]
    assert len(st["role_definitions"]) == 1 and st["groups"] == {"g1": ["oid-1"]} and "acdd72a7-3385-48ef-bd42-f606fba81ae7" in st["builtin_roles"]
    assert N.azure_principal({})["type"] == "root"


def test_azure_state_console_deny_assignment_is_a_deny_not_an_allow(N):
    """The console's Add deny assignment PUTs a roleAssignments record with kind=deny + denyActions (Mesh's adapter already maps it)."""
    sc = "/subscriptions/s1"
    arm = types.SimpleNamespace(state={"d1": {"id": sc + "/providers/Microsoft.Authorization/roleAssignments/d1", "name": "d1", "_type": "microsoft.authorization/roleassignments",
        "properties": {"kind": "deny", "principalId": "oid-1", "principalType": "User", "scope": sc, "denyActions": ["Microsoft.Storage/storageAccounts/read"]}}})
    preload("azure", "_roles")
    st, _ = N.state_and_principal("azure", {}, "", {"az_arm": arm})
    assert st["role_assignments"] == []
    assert st["deny_assignments"] == [{"id": sc + "/providers/Microsoft.Authorization/roleAssignments/d1", "scope": sc, "principals": [{"id": "oid-1", "type": "User"}],
        "exclude_principals": [], "permissions": [{"actions": ["Microsoft.Storage/storageAccounts/read"], "notActions": [], "dataActions": [], "notDataActions": []}],
        "is_system_protected": False, "do_not_apply_to_child_scopes": False}]


# ---------------------------------------------------------------------------------------------------- full bridge: real map + engine + gate
class Host:
    def __init__(self, docs):
        self.docs, self.ring = docs, []

    def get_settings(self, c): return json.dumps(self.docs[c]) if c in self.docs else None
    def put_settings(self, c, j): self.docs[c] = json.loads(j)
    def audit_push(self, j): self.ring.insert(0, json.loads(j))
    def audit_list(self, c): return json.dumps(self.ring)
    def audit_clear(self): self.ring.clear()


@pytest.fixture
def bridge(N, monkeypatch):
    from core.iam_engine import nano_bridge as nb
    host = Host({c: {"space": "enforce"} for c in ("aws", "gcp", "azure")})
    monkeypatch.setattr(nb, "_apis", {}); monkeypatch.setattr(nb, "_have", set()); monkeypatch.setattr(nb, "_audit_log", None)
    known = {c: [p.stem for p in (CAT / c).glob("*.json")] for c in ("aws", "gcp", "azure")}
    nb.configure(host, json.dumps(known))
    nb.set_state_override(None)
    yield nb, host
    nb.set_state_override(None)
    from core.iam_engine import map_aws
    map_aws.set_catalog_loader(None)      # configure() installs the Nano (memory) catalog loader into the real map module: do not leak it


def run(nb, req, doc, reg, monkeypatch):
    monkeypatch.setattr(nb, "_registry", lambda: reg)
    for _ in range(8):                                                         # what nano-iam-hook.js does: prefetch every `need`, retry
        out = json.loads(nb.check(json.dumps(req), json.dumps(doc)))
        if "need" not in out:
            return out
        for c, s in out["need"]:
            nb.preload(c, s, (CAT / c / f"{s}.json").read_text())
    raise AssertionError("did not converge")


def test_bridge_aws_allow_deny_and_unknown_key_is_root(bridge, monkeypatch):
    nb, host = bridge
    reg = aws_registry()
    sig = lambda k: {"authorization": f"AWS4-HMAC-SHA256 Credential={k}/20261123/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0", "host": "s3.amazonaws.com"}
    rq = lambda m, k: {"cloud": "aws", "method": m, "path": "/b/o", "query": {}, "headers": sig(k), "body_b64": ""}
    assert run(nb, rq("GET", "AKIAALICE0000000001"), host.docs["aws"], reg, monkeypatch) == {"ok": True}
    d = run(nb, rq("PUT", "AKIAALICE0000000001"), host.docs["aws"], reg, monkeypatch)["deny"]
    assert d["status"] == 403 and b"s3:PutObject" in base64.b64decode(d["body_b64"])
    assert run(nb, rq("PUT", "AKIAUNKNOWN"), host.docs["aws"], reg, monkeypatch) == {"ok": True}          # unknown key = account root
    assert "deny" in run(nb, rq("PUT", "AKIAUNKNOWN"), dict(host.docs["aws"], unknownPrincipal="deny"), reg, monkeypatch)


def test_bridge_gcp_inherit_allow_and_exact_denial(bridge, monkeypatch):
    from core.iam_store import InMemoryIamStore
    nb, host = bridge
    s = InMemoryIamStore()
    s.gcp_iam_policies = {"projects/p": {"bindings": [{"role": "roles/storage.objectViewer", "members": ["user:a@x.com"]}]}}
    reg = {"gcp_iam": s, "gcs": types.SimpleNamespace(buckets={"bkt": {}})}
    rq = lambda m, tok: {"cloud": "gcp", "method": m, "path": "/storage/v1/b/bkt/o/obj", "query": {}, "headers": {"authorization": "Bearer " + tok}, "body_b64": ""}
    a = _jwt({"email": "a@x.com"})
    assert run(nb, rq("GET", a), host.docs["gcp"], reg, monkeypatch) == {"ok": True}
    d = run(nb, rq("DELETE", a), host.docs["gcp"], reg, monkeypatch)["deny"]
    body = json.loads(base64.b64decode(d["body_b64"]))
    assert d["status"] == 403 and body["error"]["status"] == "PERMISSION_DENIED" and "storage.objects.delete" in body["error"]["message"]
    assert run(nb, rq("DELETE", "ya29.opaque"), host.docs["gcp"], reg, monkeypatch) == {"ok": True}        # no identity = project owner
    assert "deny" in run(nb, rq("DELETE", "ya29.opaque"), dict(host.docs["gcp"], unknownPrincipal="deny"), reg, monkeypatch)


def test_bridge_azure_reader_allow_and_authorization_failed(bridge, monkeypatch):
    nb, host = bridge
    sc = "/subscriptions/11111111-1111-1111-1111-111111111111"
    arm = types.SimpleNamespace(state={"ra": {"id": "ra", "_type": "microsoft.authorization/roleassignments",
                                              "properties": {"principalId": "oid-1", "roleDefinitionId": "acdd72a7-3385-48ef-bd42-f606fba81ae7", "scope": sc}}})
    reg = {"az_arm": arm}
    rq = lambda m: {"cloud": "azure", "method": m, "path": sc + "/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa", "query": {"api-version": "2023-01-01"},
                    "headers": {"authorization": "Bearer " + _jwt({"oid": "oid-1"})}, "body_b64": ""}
    assert run(nb, rq("GET"), host.docs["azure"], reg, monkeypatch) == {"ok": True}
    d = run(nb, rq("DELETE"), host.docs["azure"], reg, monkeypatch)["deny"]
    assert d["status"] == 403 and json.loads(base64.b64decode(d["body_b64"]))["error"]["code"] == "AuthorizationFailed"
    assert [r["decision"] for r in host.ring] == ["deny", "allow"]


def test_vendored_extras_current():
    r = subprocess.run([sys.executable, str(ROOT / "wasm" / "build_cores.py"), "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ROOT / "wasm" / "core" / "iam_state_nano.py").read_bytes() == (ROOT / "core" / "iam_state_nano.py").read_bytes()


def test_azure_preload_feeds_map_casing_without_rereading_disk(N):
    from core.iam_engine import map_azure
    saved = dict(map_azure._CAT)
    try:
        map_azure._CAT.clear()
        N.on_preload("azure", "Microsoft.Storage", (CAT / "azure" / "Microsoft.Storage.json").read_text())
        assert "" in map_azure._CAT and map_azure._CAT["microsoft.storage/storageaccounts/read"] == "Microsoft.Storage/storageAccounts/read"
        assert map_azure._catalog() is map_azure._CAT and len(map_azure._CAT) > 100       # non-empty: never rebuilt by globbing the disk
    finally:
        map_azure._CAT.clear(); map_azure._CAT.update(saved)
