"""IAM Service Account Credentials on the offline appliance: the native
`google-cloud-iamcredentials` / `gcloud --impersonate-service-account` REST wire
(`/v1/projects/-/serviceAccounts/{sa}:generateAccessToken|generateIdToken|signBlob|signJwt`)
and the console REST (`/api/gcp/iamcredentials/...`) the GCP console catalog drives. Both are
thin adapters over core/gcp_iamcredentials_core.py on the SAME shared store, so a credential
issued by the SDK/CLI shows up in the console's "Issued credentials" grid and vice-versa.

Service accounts are the appliance's IAM service accounts (console-created or
`/v1/projects/{p}/serviceAccounts`); an unknown account answers 403 like Google."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_iamcredentials_core as core

DEFAULT_PROJECT = "demo"


async def _json_body(request):
    """Console form body; a missing/invalid JSON body is a 400, not a 500."""
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(400, detail="Request body must be a JSON object.")
    if not isinstance(b, dict):
        raise HTTPException(400, detail="Request body must be a JSON object.")
    return b


class _Shim:
    """Minimal Request stand-in for providers.gcp_iam.api_gcp_iam_create_service_account."""

    def __init__(self, payload):
        self._p = payload

    async def json(self):
        return self._p


def resolve(ident):
    """Service-account email / uniqueId -> email, or None (appliance IAM state)."""
    try:
        from core.app_context import gcp_iam_state
        for accts in gcp_iam_state.get("service_accounts", {}).values():
            for rec in accts.values():
                if ident in (rec.get("email"), rec.get("uniqueId")):
                    return rec["email"]
    except Exception:
        pass
    return None


def _http_error(r_or_e):
    if hasattr(r_or_e, "body"):
        try:
            return HTTPException(r_or_e.status, detail=json.loads(r_or_e.body)["error"]["message"])
        except Exception:
            return HTTPException(r_or_e.status, detail="error")
    return HTTPException(r_or_e.status, detail=r_or_e.message)


def register(app, on_change=None):
    """`on_change(action, console_view_or_name)` lets the host sync CloudSim events/usage."""
    store = core.shared_store

    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    # ── native wire ───────────────────────────────────────────────────────
    async def native(request: Request):
        body = await request.body()
        before = set(store().issued)
        r = core.dispatch(store(), request.method, request.url.path, dict(request.query_params),
                          dict(request.headers), body, resolver=resolve)
        for cid in set(store().issued) - before:
            changed("create", core.console_view(store().issued[cid]))
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    app.add_api_route("/v1/projects/{project}/serviceAccounts/{account}", native, methods=["POST"], include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/iamcredentials/credentials lands on these.
    @app.get("/api/iamcredentials/credentials")
    async def list_credentials():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/iamcredentials/credentials")
    async def issue_credential(request: Request):
        b = await _json_body(request)
        sa = core.form_service_account(b)
        if "@" in sa and not resolve(sa):   # the console issues for the account, creating it if absent
            acct, _, rest = sa.partition("@")
            from core import wire_ingress as _wi
            if _wi.is_unified("gcp_iam"):
                from routes import gcp_iam_unified as _giam
                _giam.create_account(rest.split(".")[0], acct)
            else:
                from providers import gcp_iam
                await gcp_iam.api_gcp_iam_create_service_account(rest.split(".")[0], _Shim({"accountId": acct}))
        try:
            v = core.issue_from_form(store(), b, resolve)
        except core._E as e:
            raise _http_error(e)
        changed("create", v)
        return v

    @app.get("/api/iamcredentials/credentials/{name}")
    async def get_credential(name: str):
        rec = store().issued.get(name)
        if rec is None:
            raise HTTPException(404, detail=f"Credential {name} not found.")
        return core.console_view(rec)

    @app.delete("/api/iamcredentials/credentials/{name}")
    async def revoke_credential(name: str):
        if store().issued.pop(name, None) is None:
            raise HTTPException(404, detail=f"Credential {name} not found.")
        changed("delete", name)
        return {"message": "Credential record deleted", "name": name}
