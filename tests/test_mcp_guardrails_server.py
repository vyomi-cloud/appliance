"""Server-side guardrails (docs/architecture/v4.0/MCP-GUARDRAILS-INCIDENT-DESIGN.md).

The MCP is a client on the user's laptop, so these checks call the simulator's own code paths the way ANY client would
(SDK, curl, an agent through the MCP). Each test names the premise item it covers.

- item 5: limits enforced upstream (the portal's session token) cannot be bypassed through the API.
- item 7: internal controls are not open on a Mesh, which runs the developer distribution mode.

Runs without the full simulator: when core.app_context cannot be imported (a partial checkout), a minimal stand-in is used.
`server` is always stubbed so the budget-toggle routes can be exercised without importing server.py.
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

KEY = "k" * 43
SESSION_KEY = "test-session-key"

from tests import mesh_testkey as testkey  # noqa: E402  (v2 tokens signed with the public test vector)


def _load_ctx():
    try:
        from core import app_context
        return app_context
    except Exception:            # partial checkout: stand-in with the two names these routes use
        stub = types.ModuleType("core.app_context")
        stub.STATE = {}
        stub._mode = "developer"
        stub.distribution_mode = lambda: os.environ.get("CLOUDLEARN_DISTRIBUTION_MODE", "developer")
        stub.appliance_mode_enabled = lambda: stub.distribution_mode() == "appliance"
        stub.tenants_state = lambda: {"tenants": {}}
        import core
        sys.modules["core.app_context"] = stub
        core.app_context = stub
        return stub


CTX = _load_ctx()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from core import admin_auth, mesh_session
    monkeypatch.setattr(admin_auth, "_cached_key", KEY)
    monkeypatch.delenv("VYOMI_ROLE", raising=False)
    monkeypatch.delenv("VYOMI_MESH_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("VYOMI_MESH_SESSION_KEY", SESSION_KEY)        # a v1-era key in the env must change nothing (v1 retired)
    monkeypatch.setattr(mesh_session, "TRUSTED_KEYS", testkey.trusted(mesh_session))   # tests sign with the public test vector
    monkeypatch.setenv("CLOUDLEARN_DISTRIBUTION_MODE", "developer")
    if hasattr(CTX, "host_config"):                       # the real module: a host config file must not decide the mode
        monkeypatch.setattr(CTX, "host_config", lambda: {})
    mesh_session.reset_for_tests()
    yield
    mesh_session.reset_for_tests()


def _mesh(monkeypatch):
    monkeypatch.setenv("VYOMI_ROLE", "mesh")


# ---------------------------------------------------------------- item 7: admin-key checks

def _guarded_app():
    from core.admin_auth import require_admin_key
    app = FastAPI()

    @app.post("/api/guarded")
    def guarded(request: Request):
        require_admin_key(request)
        return {"ok": True}

    return TestClient(app)


def test_item7_local_developer_mode_unchanged():
    """Local developer mode (a laptop, not a Mesh) keeps the no-key shortcut."""
    assert _guarded_app().post("/api/guarded").status_code == 200


def test_item7_mesh_requires_admin_key(monkeypatch):
    """A Mesh runs CLOUDLEARN_DISTRIBUTION_MODE=developer; that must not open admin endpoints."""
    _mesh(monkeypatch)
    c = _guarded_app()
    r = c.post("/api/guarded")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_key_required"
    assert c.post("/api/guarded", headers={"X-CloudLearn-Admin-Key": "wrong"}).status_code == 403
    assert c.post("/api/guarded", headers={"X-CloudLearn-Admin-Key": KEY}).status_code == 200


def test_item7_appliance_mode_requires_admin_key(monkeypatch):
    monkeypatch.setenv("CLOUDLEARN_DISTRIBUTION_MODE", "appliance")
    assert _guarded_app().post("/api/guarded").status_code == 403


def _licensing_client(monkeypatch):
    fake_server = types.ModuleType("server")
    fake_server._BUDGET_BYPASSED = False
    monkeypatch.setitem(sys.modules, "server", fake_server)
    from routes import licensing
    app = FastAPI()
    licensing.register(app)
    return TestClient(app), fake_server


@pytest.mark.parametrize("path", ["/api/runtime/budget/disable", "/api/runtime/budget/enable"])
def test_item7_budget_toggle_refused_on_mesh_even_with_key(monkeypatch, path):
    """The host-clamp gate is not a user toggle on a Mesh, whoever holds the key."""
    _mesh(monkeypatch)
    c, srv = _licensing_client(monkeypatch)
    assert c.post(path).status_code == 403
    r = c.post(path, headers={"X-CloudLearn-Admin-Key": KEY})
    assert r.status_code == 403 and "Mesh" in r.text
    assert srv._BUDGET_BYPASSED is False


def test_item7_budget_toggle_still_works_in_local_developer_mode(monkeypatch):
    c, srv = _licensing_client(monkeypatch)
    assert c.post("/api/runtime/budget/disable").json()["bypassed"] is True
    assert srv._BUDGET_BYPASSED is True
    c.post("/api/runtime/budget/enable")
    assert srv._BUDGET_BYPASSED is False


# ---------------------------------------------------------------- item 5: upstream limits hold through the API

def _tok(tier="pro", end_in=3600, **kw):
    return testkey.mint("acct-1", tier, time.time() + end_in, **kw)


def _authorise(token="", provider="aws", path="/"):
    from core import mesh_session
    headers = {mesh_session.HEADER: token} if token else {}
    return mesh_session.authorise(headers, path, provider)


def test_item5_no_token_nothing_served():
    err = _authorise()
    assert err is not None and err.code == "MeshSessionRequired"


def test_item5_forged_token_refused():
    from core import mesh_session
    forged = testkey.forged("acct-1", "max", time.time() + 3600)          # claims the trusted kid, another key signed it
    assert _authorise(forged).code == "MeshSessionBadSignature"
    v1 = mesh_session.mint("acct-1", "max", time.time() + 3600, key=SESSION_KEY)   # F2: minted with the key the Codespace holds
    assert _authorise(v1).code == "MeshSessionV1Retired"


def test_item5_free_tier_token_refused():
    assert _authorise(_tok("free")).code == "MeshTierNotEligible"


def test_item5_expired_session_latches():
    from core import mesh_session
    assert _authorise(_tok(end_in=-5)).status == 410
    assert mesh_session.session_ended()
    assert _authorise(_tok()).code == "MeshSessionExpired"   # a fresh token does not revive an ended session


def test_item5_pro_is_locked_to_one_cloud():
    t = _tok("pro", primary_cloud="aws")
    assert _authorise(t, "aws") is None
    err = _authorise(t, "gcp")
    assert err is not None and err.code == "tier_provider_locked"


def test_item5_runner_token_cannot_drive_the_mesh():
    assert _authorise(_tok("max", role="llm-runner")).code == "MeshSessionWrongRole"


def test_item5_session_middleware_refuses_without_token(monkeypatch):
    from core import mesh_session
    _mesh(monkeypatch)
    inner = FastAPI()

    @inner.get("/api/anything")
    def anything():
        return {"served": True}

    c = TestClient(mesh_session.SessionMiddleware(inner))
    r = c.get("/api/anything")
    assert r.status_code == 401 and r.headers.get("x-vyomi-mesh-denied") == "MeshSessionRequired"
    assert c.get("/api/anything", headers={mesh_session.HEADER: _tok("max")}).json() == {"served": True}
