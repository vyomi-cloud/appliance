"""v4 C0i — offline GCP IAM is ONE engine (core/gcp_iam_core.py over AppStateGcpIamStore).

Pins what splitting it from the pre-v4 provider broke, and what the unification must keep:
  * a service account + key + IAM binding + Principal Access Boundary survive a restart;
  * the PAB really narrows testIamPermissions, and Asset Inventory finds the account;
  * pre-v4 `gcp_iam_state` records are adopted once per space (a deleted one stays deleted);
  * `gcp_iam_state` stays a correct view for what still reads it (enforcement middleware).
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-gcp-iam-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core import app_context as ctx  # noqa: E402
from core import appliance_stores as aps  # noqa: E402
from core.vyomi_platform import SQLiteStateStore  # noqa: E402

PROJECT = "vyomi-project"
P = f"/v1/projects/{PROJECT}"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _ok(r):
    assert r.status_code < 300, f"{r.request.method} {r.url} -> {r.status_code}: {r.text[:300]}"
    return r.json() if r.content else {}


def _restart() -> None:
    """A process restart: the kernel state is whatever the state file holds."""
    ctx.persist_state()
    loaded = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    assert loaded, "nothing was saved"
    ctx.STATE.clear()
    ctx.STATE.update(loaded)


def _account(client, display="d") -> dict:
    return _ok(client.post(P + "/serviceAccounts", json={
        "accountId": "sa-" + uuid.uuid4().hex[:8], "serviceAccount": {"displayName": display}}))


def _emails(client) -> list[str]:
    return [a["email"] for a in _ok(client.get(P + "/serviceAccounts")).get("accounts", [])]


def _legacy():
    """The pre-v4 slot of the active GCP space, resolved as a GCP request."""
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        return ctx.gcp_iam_state._target()
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)


def _slot() -> dict:
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        return aps.net_new_core_stores()["gcp_iam"]._dir()
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)


def test_account_key_binding_pab_survive_restart(client):
    sa = _account(client, "durable")
    key = _ok(client.post(f"{P}/serviceAccounts/{sa['email']}/keys", json={}))
    assert key.get("privateKeyData")
    kid = key["name"].rsplit("/", 1)[-1]
    member = f"user:pab-{uuid.uuid4().hex[:6]}@example.com"
    pol = _ok(client.post(f"{P}:getIamPolicy", json={}))
    bindings = pol.get("bindings", []) + [{"role": "roles/viewer", "members": [member]}]
    _ok(client.post(f"{P}:setIamPolicy", json={"policy": {"bindings": bindings}}))
    perm = {"permissions": ["resourcemanager.projects.get"], "member": member}
    assert _ok(client.post(f"{P}:testIamPermissions", json=perm))["permissions"] == perm["permissions"]

    org = _ok(client.get(f"/v3/projects/{PROJECT}"))["parent"]["id"]
    pid = "pab-" + uuid.uuid4().hex[:6]
    pab = _ok(client.post(f"/v3/organizations/{org}/locations/global/principalAccessBoundaryPolicies",
                          params={"principalAccessBoundaryPolicyId": pid},
                          json={"displayName": pid, "details": {"rules": [{"resources": ["projects/elsewhere"]}]}}))
    _ok(client.post(f"/v3/organizations/{org}/locations/global/policyBindings", params={"policyBindingId": pid},
                    json={"policy": pab["name"], "target": {"principal": member}}))

    def _assert_all():
        assert _ok(client.post(f"{P}:testIamPermissions", json=perm))["permissions"] == []   # PAB narrows it
        assert sa["email"] in _emails(client)
        keys = _ok(client.get(f"{P}/serviceAccounts/{sa['email']}/keys"))["keys"]
        assert kid in [k["name"].rsplit("/", 1)[-1] for k in keys]
        assert all("privateKeyData" not in k for k in keys)
        assert "privateKeyData" not in _ok(client.get(f"{P}/serviceAccounts/{sa['email']}/keys/{kid}"))
        got = _ok(client.post(f"{P}:getIamPolicy", json={}))["bindings"]
        assert any(member in b["members"] for b in got)
        found = _ok(client.get(f"{P}:searchAllResources"))["results"]
        assert sa["name"] in [r["name"] for r in found]
    _assert_all()
    _restart()
    _assert_all()


def test_legacy_state_is_adopted_once_per_space(client):
    _ok(client.get(P + "/serviceAccounts"))   # the space exists
    email = f"old-{uuid.uuid4().hex[:6]}@{PROJECT}.iam.gserviceaccount.com"
    account = email.split("@")[0]
    member = f"user:{account}@example.com"
    legacy, slot = _legacy(), _slot()
    legacy.setdefault("service_accounts", {}).setdefault(PROJECT, {})[account] = {
        "name": account, "project": PROJECT, "uniqueId": "1234567890", "email": email, "displayName": "Old",
        "description": "pre-v4", "oauth2ClientId": "oauth-1", "disabled": True, "createTime": "2026-01-01T00:00:00Z",
        "etag": "e", "keys": {"kid1": {"name": f"projects/{PROJECT}/serviceAccounts/{email}/keys/kid1",
                                       "keyAlgorithm": "KEY_ALG_RSA_2048", "keyType": "USER_MANAGED",
                                       "privateKeyData": "c2VjcmV0", "_key_id": "kid1"}},
        "_activity": [{"id": "a1", "resource": f"projects/{PROJECT}/serviceAccounts/{email}", "action": "DISABLE",
                       "role": "", "member": "", "time": "2026-01-01T00:00:00Z"}]}
    slot.pop("gcp_iam_policies", None)
    legacy.setdefault("policies", {})[PROJECT] = {
        "version": 1, "etag": "p", "bindings": [{"role": "roles/viewer", "members": [member]}],
        "auditConfigs": [{"service": "iam.googleapis.com", "auditLogConfigs": [{"logType": "ADMIN_READ"}]}]}
    slot.pop("_vyomi_adopted")   # what a pre-v4 state file looks like

    view = _ok(client.get(f"{P}/serviceAccounts/{email}"))
    assert view["displayName"] == "Old" and view["disabled"] is True and view["uniqueId"] == "1234567890"
    assert view["name"] == f"projects/{PROJECT}/serviceAccounts/{email}"
    assert _ok(client.get(f"{P}/serviceAccounts/1234567890"))["email"] == email      # by unique ID too
    assert "kid1" in _ok(client.get(f"{P}/serviceAccounts/{email}/keys"))["keys"][0]["name"]
    assert _ok(client.get(f"{P}/serviceAccounts/{email}/policyActivity"))["activity"][0]["action"] == "DISABLE"
    pol = _ok(client.post(f"{P}:getIamPolicy", json={}))
    assert member in pol["bindings"][0]["members"] and pol["auditConfigs"]
    found = [r["name"] for r in _ok(client.get(f"{P}:searchAllResources"))["results"]]
    assert view["name"] in found

    # deleted after the upgrade → gone for good: the projection drops it, nothing re-adopts it
    _ok(client.delete(f"{P}/serviceAccounts/{email}"))
    assert account not in (_legacy().get("service_accounts", {}).get(PROJECT) or {})
    _restart()
    assert email not in _emails(client)


def test_legacy_view_follows_the_core(client):
    """What still reads `gcp_iam_state`: the enforcement middleware (bindings), IAM Credentials'
    resolver + the console counts (accounts)."""
    sa = _account(client)
    assert _legacy()["service_accounts"][PROJECT][sa["email"].split("@")[0]]["email"] == sa["email"]
    member = f"user:{uuid.uuid4().hex[:6]}@example.com"
    _ok(client.post(f"{P}:setIamPolicy", json={"policy": {"bindings": [{"role": "roles/owner", "members": [member]}]}}))
    assert _legacy()["policies"][PROJECT]["bindings"] == [{"role": "roles/owner", "members": [member]}]
    from providers.gcp_iamcredentials_console import resolve
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        assert resolve(sa["email"]) == sa["email"] and resolve(sa["uniqueId"]) == sa["email"]
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    tok = _ok(client.post(f"/v1/projects/-/serviceAccounts/{sa['email']}:generateAccessToken", json={"scope": ["x"]}))
    assert tok.get("accessToken")
    assert _ok(client.get(f"{P}/serviceAccounts/{sa['email']}:metrics"))["totalRequests"] == 1
    summary = _ok(client.get("/api/gcp/console/summary", params={"project": PROJECT}))
    assert summary["services"]["gcp-iam"] >= 1


def test_classic_console_contract(client):
    """Pre-v4 callers keep working: flat fields, flat policy, PATCH with `disabled`, GET getIamPolicy."""
    acct = "classic-" + uuid.uuid4().hex[:6]
    made = _ok(client.post(P + "/serviceAccounts", json={"accountId": acct, "displayName": "Classic"}))
    assert made["displayName"] == "Classic"
    email = made["email"]
    upd = _ok(client.patch(f"{P}/serviceAccounts/{email}", json={"displayName": "New", "disabled": True}))
    assert upd["displayName"] == "New" and upd["disabled"] is True
    member = f"user:{acct}@example.com"
    flat = _ok(client.post(f"{P}:setIamPolicy", json={"bindings": [{"role": "roles/viewer", "members": [member]}]}))
    assert flat["bindings"][0]["members"] == [member]
    assert _ok(client.get(f"{P}:getIamPolicy"))["bindings"][0]["members"] == [member]
    # the caller (no `member`) is the space's principal: root keeps the owner bypass
    assert _ok(client.post(f"{P}:testIamPermissions", json={"permissions": ["x.y.z"]}))["permissions"] == ["x.y.z"]
    denied = client.post(f"{P}:testIamPermissions", json={"permissions": ["x.y.z"]},
                         headers={"x-cloudlearn-principal": member})
    assert _ok(denied)["permissions"] == []
    assert email in [a["email"] for a in _ok(client.get(f"/api/gcp/iam/v1/projects/{PROJECT}/serviceAccounts"))["accounts"]]
    # the classic aliases are the same store
    base = "/api/gcp/iam/service-accounts"
    alias = _ok(client.post(base, params={"project": PROJECT}, json={"accountId": "alias-" + uuid.uuid4().hex[:6]}))
    assert alias["displayName"] == alias["email"].split("@")[0]        # the pre-v4 default
    assert alias["email"] in _emails(client)
    assert _ok(client.patch(f"{base}/{alias['email']}", params={"project": PROJECT}, json={"displayName": "A"}))["displayName"] == "A"
    assert _ok(client.get(f"{base}/{alias['email']}", params={"project": PROJECT}))["displayName"] == "A"
    assert alias["email"] in [a["email"] for a in _ok(client.get(base, params={"project": PROJECT}))["accounts"]]
    _ok(client.delete(f"{base}/{alias['email']}", params={"project": PROJECT}))
    assert member in _ok(client.get("/api/gcp/iam/policy", params={"project": PROJECT}))["bindings"][0]["members"]
    # an account whose name overlaps another API's path keyword is still a service account
    odd = _ok(client.post(P + "/serviceAccounts", json={"accountId": "topics-" + uuid.uuid4().hex[:6]}))
    assert _ok(client.get(f"{P}/serviceAccounts/{odd['email']}"))["email"] == odd["email"]
    _ok(client.delete(f"{P}/serviceAccounts/{odd['email']}"))
    assert client.get(f"{P}/serviceAccounts/{odd['email']}/keys").status_code == 404


def test_console_consolidate_moves_core_records(client):
    other = "other-" + uuid.uuid4().hex[:6]
    sa = _ok(client.post(f"/v1/projects/{other}/serviceAccounts", json={"accountId": "mover"}))
    key = _ok(client.post(f"/v1/projects/{other}/serviceAccounts/{sa['email']}/keys", json={}))
    member = f"user:{other}@example.com"
    _ok(client.post(f"/v1/projects/{other}:setIamPolicy",
                    json={"policy": {"bindings": [{"role": "roles/editor", "members": [member]}]}}))
    _ok(client.post("/api/gcp/console/consolidate", json={"project": PROJECT}))
    moved = f"mover@{PROJECT}.iam.gserviceaccount.com"
    assert moved in _emails(client)
    assert _ok(client.get(f"/v1/projects/{other}/serviceAccounts")).get("accounts", []) == []
    kid = key["name"].rsplit("/", 1)[-1]
    assert f"/{moved}/keys/{kid}" in _ok(client.get(f"{P}/serviceAccounts/{moved}/keys"))["keys"][0]["name"]
    assert any(member in b["members"] for b in _ok(client.post(f"{P}:getIamPolicy", json={}))["bindings"])
    assert any(member in b["members"] for b in _legacy()["policies"][PROJECT]["bindings"])
    _ok(client.delete(f"{P}/serviceAccounts/{moved}"))
