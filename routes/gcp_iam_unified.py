"""v4 C0i — GCP IAM on the offline appliance, ONE engine.

Native wire, served by the shared core Nano uses (core/gcp_iam_core.py) over the appliance's
space-scoped, persisted state (core/appliance_stores.AppStateGcpIamStore):

  * /v1/projects/{p}:getIamPolicy | :setIamPolicy | :testIamPermissions
  * /v1/projects/{p}/serviceAccounts[/{account}[/keys[/{key}] | /policyActivity | :metrics |
    :enable | :disable | :getIamPolicy | :setIamPolicy | :testIamPermissions]]

(and the same under /_wire/, rewritten by routes/wire_prefix.py). Pre-v4 these were
providers/gcp_iam.py over `gcp_iam_state`, split from the core that already served custom roles,
Workload Identity, Asset Inventory, …: a Principal Access Boundary never narrowed
testIamPermissions, and Asset Inventory could not see a service account.

The classic paths stay aliases onto the same store: /api/gcp/iam/v1/… and /api/gcp/iam/policy,
/api/gcp/iam/test-permissions, /api/gcp/iam/service-accounts[/{account}], with the pre-v4 body
leniency (flat setIamPolicy body, top-level displayName, PATCH with `disabled`, GET getIamPolicy).

`gcp_iam_state` stays CORRECT, not authoritative: the store projects every write back into it
(so the enforcement middleware, consoles' counts and the CloudSim inventory read live data), and
adopts its pre-v4 records once per space. Both live in AppStateGcpIamStore, so no path can skip them.

The legacy `users/groups/roles/policies/account-settings/identity-providers` CRUD under
/api/gcp/iam/ has no core counterpart (they are console-only records) and stays in providers/gcp_iam.py.

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without gcp_iam (or VYOMI_LEGACY_WIRE=1) mounts nothing.
"""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import Request, Response

from core import gcp_iam_core as core
from core import wire_ingress as _wi

_WIRE_PREFIXES = ("/api/gcp/iam", "/_wire")


def _store():
    from core import appliance_stores as aps
    return aps.net_new_core_stores()["gcp_iam"]


def _call(method: str, path: str, query: dict | None = None, headers: dict | None = None, body: bytes = b""):
    """One request on the core. Not through the router's path sniffing: a service account named
    `topics-reader` or `locations-bot` must never be classified as another API (same reason as
    wire_ingress.dispatch_service)."""
    from core import app_context as ctx
    r = _wi.new_services_router() or _wi.appliance_router()
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        return core.dispatch(_store(), method, path, query or {}, headers or {}, body,
                             rm_store=r.gcp_rm, logger=r._iam_audit_log, iamc_store=r.gcp_iamc)
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)


def _out(resp) -> Response:
    return Response(content=resp.body, status_code=resp.status, media_type="application/json")


def _json_body(raw: bytes) -> dict:
    try:
        d = json.loads(raw or b"{}")
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def _native_path(request: Request) -> str:
    p = (request.scope.get("path") or request.url.path).split("?", 1)[0]
    for pre in _WIRE_PREFIXES:
        if p.startswith(pre + "/"):
            return p[len(pre):]
    return p


def _policy_body(raw: bytes) -> bytes:
    """Pre-v4 callers (the classic console) POST the policy itself; the wire nests it. Treating a
    flat body as `{"policy": {}}` would wipe the project's bindings."""
    d = _json_body(raw)
    return raw if isinstance(d.get("policy"), dict) else json.dumps({"policy": d}).encode()


def create_body(d: dict, default_display_name: bool = False) -> bytes:
    """serviceAccounts.create, also taking the pre-v4 flat fields (classic console, /api aliases)."""
    account = str(d.get("accountId") or d.get("serviceAccountId") or d.get("name") or "").split("/")[-1].strip()
    spec = dict(d["serviceAccount"]) if isinstance(d.get("serviceAccount"), dict) else {}
    name = d.get("displayName") or d.get("display_name")
    if name and "displayName" not in spec:
        spec["displayName"] = str(name)
    elif default_display_name:
        spec.setdefault("displayName", account)
    if d.get("description") and "description" not in spec:
        spec["description"] = str(d["description"])
    return json.dumps({"accountId": account, "serviceAccount": spec}).encode()


def _test_permissions(request: Request, path: str, query: dict, raw: bytes) -> Response:
    """With an explicit `member` the core decides (bindings + Principal Access Boundary). Without
    one the caller is the principal: X-Cloudlearn-Principal or the space's active principal, whose
    owner bypass is the appliance's enforcement contract (core/gcp_iam_policy.py)."""
    d = _json_body(raw)
    if d.get("member") is not None:
        return _out(_call("POST", path, query, dict(request.headers), raw))
    from core import app_context as ctx, gcp_iam_policy
    permissions = [p for p in (d.get("permissions") or []) if isinstance(p, str)]
    resource = path.rsplit(":", 1)[0].removeprefix("/v1/").strip("/")
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        space = ctx.gcp_active_space_dict()
        principal = request.headers.get("x-cloudlearn-principal") or str((space or {}).get("active_principal") or "root")
        pol = getattr(_store(), "gcp_iam_policies", {}).get(resource) or {}
        granted = [p for p in permissions if gcp_iam_policy.authorize(principal, p, pol.get("bindings") or [])]
        r = _wi.new_services_router() or _wi.appliance_router()
        boundary = core._pab_allowed_resources(r.gcp_rm, principal)
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)
    if boundary is not None and resource not in boundary:
        granted = []
    return Response(content=json.dumps({"permissions": granted}), media_type="application/json")


async def _native(request: Request) -> Response:
    path, method = _native_path(request), request.method.upper()
    query, raw = dict(request.query_params), await request.body()
    headers = dict(request.headers)
    last = path.rsplit("/", 1)[-1]
    if last.endswith(":getIamPolicy"):
        return _out(_call("POST", path, query, headers, b"{}"))      # GET was the pre-v4 form too
    if last.endswith(":setIamPolicy"):
        return _out(_call("POST", path, query, headers, _policy_body(raw)))
    if last.endswith(":testIamPermissions"):
        return _test_permissions(request, path, query, raw)
    if method == "POST" and path.endswith("/serviceAccounts"):
        return _out(_call("POST", path, query, headers, create_body(_json_body(raw))))
    if method in ("PATCH", "PUT"):
        d = _json_body(raw)
        resp = _call("PATCH", path, query, headers, raw)
        spec = d["serviceAccount"] if isinstance(d.get("serviceAccount"), dict) else d
        if resp.status < 300 and "disabled" in spec:    # pre-v4 PATCH also flipped the state
            verb = "disable" if spec["disabled"] else "enable"
            _call("POST", f"{path}:{verb}", query, headers, b"{}")
            return _out(_call("GET", path, query, headers))
        return _out(resp)
    return _out(_call(method, path, query, headers, raw))


def _project(request: Request) -> str:
    from core.app_context import gcp_project_name
    return gcp_project_name(request.query_params.get("project"))


async def _alias_policy(request: Request) -> Response:
    raw = await request.body()
    path = f"/v1/projects/{_project(request)}:" + ("setIamPolicy" if request.method == "POST" else "getIamPolicy")
    body = _policy_body(raw) if request.method == "POST" else b"{}"
    return _out(_call("POST", path, {}, dict(request.headers), body))


async def _alias_test(request: Request) -> Response:
    return _test_permissions(request, f"/v1/projects/{_project(request)}:testIamPermissions", {}, await request.body())


async def _alias_accounts(request: Request) -> Response:
    path = f"/v1/projects/{_project(request)}/serviceAccounts"
    if request.method == "POST":
        return _out(_call("POST", path, {}, dict(request.headers),
                          create_body(_json_body(await request.body()), default_display_name=True)))
    return _out(_call("GET", path, {}, dict(request.headers)))


async def _alias_account(request: Request) -> Response:
    account = quote(request.path_params["account"], safe="@:")
    return await _native_as(request, f"/v1/projects/{_project(request)}/serviceAccounts/{account}")


async def _native_as(request: Request, path: str) -> Response:
    scope = dict(request.scope, path=path)
    async def _receive():
        return {"type": "http.request", "body": await request.body(), "more_body": False}
    return await _native(Request(scope, _receive))


def create_account(project: str, account_id: str) -> None:
    """The IAM Credentials console issues for an account, creating it if absent."""
    _call("POST", f"/v1/projects/{project}/serviceAccounts", body=create_body({"accountId": account_id}))


def edit_policy(resource: str, role: str, member: str, add: bool) -> None:
    """A Privileged Access Manager grant: a real change of the policy this wire serves."""
    from core import app_context as ctx
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        (core.grant_member if add else core.revoke_member)(_store(), resource, role, member)
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)


def consolidate(target: str) -> int:
    """/api/gcp/console/consolidate (space = one project): move this store's records too."""
    from core import app_context as ctx, appliance_stores as aps
    tok = ctx.REQUEST_PROVIDER.set("gcp")
    try:
        return aps.retarget_gcp_iam(_store(), target)
    finally:
        ctx.REQUEST_PROVIDER.reset(tok)


def register(app) -> None:
    if not _wi.is_unified("gcp_iam"):
        return
    p = "/projects/{project}"
    sa = p + "/serviceAccounts"
    one = sa + "/{account}"
    for pre in ("/v1", "/api/gcp/iam/v1"):
        app.add_api_route(pre + p + ":getIamPolicy", _native, methods=["GET", "POST"], include_in_schema=False)
        app.add_api_route(pre + p + ":setIamPolicy", _native, methods=["POST"], include_in_schema=False)
        app.add_api_route(pre + p + ":testIamPermissions", _native, methods=["POST"], include_in_schema=False)
        app.add_api_route(pre + sa, _native, methods=["GET", "POST"], include_in_schema=False)
        # POST {account} (no verb below) stays IAM Credentials' (providers/gcp_iamcredentials_console.py)
        for verb in ("enable", "disable", "getIamPolicy", "setIamPolicy", "testIamPermissions"):
            app.add_api_route(pre + one + ":" + verb, _native, methods=["POST"], include_in_schema=False)
        app.add_api_route(pre + one, _native, methods=["GET", "PATCH", "PUT", "DELETE"], include_in_schema=False)
        app.add_api_route(pre + one + "/keys", _native, methods=["GET", "POST"], include_in_schema=False)
        app.add_api_route(pre + one + "/keys/{key}", _native, methods=["GET", "DELETE"], include_in_schema=False)
        app.add_api_route(pre + one + "/policyActivity", _native, methods=["GET"], include_in_schema=False)
    app.add_api_route("/api/gcp/iam/policy", _alias_policy, methods=["GET", "POST"], include_in_schema=False)
    app.add_api_route("/api/gcp/iam/test-permissions", _alias_test, methods=["POST"], include_in_schema=False)
    app.add_api_route("/api/gcp/iam/service-accounts", _alias_accounts, methods=["GET", "POST"], include_in_schema=False)
    app.add_api_route("/api/gcp/iam/service-accounts/{account}", _alias_account,
                      methods=["GET", "PATCH", "DELETE"], include_in_schema=False)
