"""v4 C0f — Azure Key Vault, Container Registry and Service Bus data planes on the offline
appliance, ONE engine each (the cores Nano and dev_server use), space-scoped and persisted.

Key Vault (core/azure_keyvault_{secrets,keys,certificates}_core.py over
core/appliance_stores.AppStateAzure{Kv,Key}Store):
  * `/azure-data/keyvault/{vault}/{secrets|keys|certificates}…` — the vaultUri the offline ARM
    catalog hands out, and where the host-based `{vault}.vault.*` rewrite (core/middleware.py)
    lands the native SDKs;
  * root `/{secrets|keys|certificates}…?api-version=…` — the v4 console (`/_wire/secrets…`) and
    SDKs pointed straight at the appliance. Before v4 these fell through to the S3 catch-all
    ("NoSuchBucket"), so the v4 Azure smoke failed offline at "Key Vault secret create"; and the
    `/azure-data/keyvault/…` handlers were Vault-only (503 without Vault).
  One Key Vault namespace per space, as on Nano (the vault segment is accepted, not a partition).

Container Registry (core/azure_acr_core.py over AppStateAcrStore): the registry host's own
OCI/Docker Registry v2 surface (`/v2/`, `/v2/_catalog`, `/v2/{repo}/manifests/{ref}`,
`/v2/{repo}/tags/list`) and the ACR REST extension (`/acr/v1/…`). Only those shapes are claimed
(`/v2/projects/…`, `/v2/entries…` are GCP; `/v2/apis…` is API Gateway V2). The ARM side
(Microsoft.ContainerRegistry, and Microsoft.ContainerService for AKS) is served by the shared
core ARM engine through providers/azure_services.handle_arm.

Service Bus (core/azure_servicebus_core.py over AppStateServiceBusStore): the namespace-root
REST the v4 Service Bus Explorer and REST clients use — `PUT|DELETE /{entity}` (atom+xml),
`/{entity}/messages…`, `/{entity}/$deadletterqueue/messages…`, `/{topic}/subscriptions/…`.
Claimed with the same signals as Nano's router (an atom+xml entity body, BrokerProperties, or an
entity that already exists in this space) — never a plain S3 / SQS path. The pre-v4
`/azure-data/servicebus/{namespace}/…` broker (core/azure_dataplane.py) is unchanged.

Root paths are rewritten (pure ASGI, innermost user middleware — after the `/_wire` strip) to
`/azure-data/keyvault/_/…` and `/azure-data/acr/…`, which the routes below serve. Registered
BEFORE core/vault_routes (whose `/azure-data/keyvault/…` handlers are the pre-v4 path). Opt-out:
VYOMI_UNIFIED_INGRESS_SERVICES without azure_keyvault / azure_acr (or VYOMI_LEGACY_WIRE=1).
"""
from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import Request

from core import wire_ingress as _wi

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
_KV_ROOTS = ("secrets", "keys", "certificates", "deletedsecrets", "deletedkeys", "deletedcertificates")


def acr_path(path: str) -> bool:
    """A registry-host path azure_acr_core serves (mirrors aws_wire_router._azure_service)."""
    p = path.split("?", 1)[0]
    if p == "/acr/v1" or p.startswith("/acr/v1/"):
        return True
    if p in ("/v2", "/v2/", "/v2/_catalog"):
        return True
    segs = [s for s in p.split("/") if s]
    if len(segs) >= 3 and segs[0] == "v2" and segs[1] not in ("projects", "entries", "policies"):
        return segs[-2] == "manifests" or (segs[-2] == "tags" and segs[-1] == "list")
    return False


def sb_path(path: str, headers: dict, exists) -> bool:
    """A Service Bus namespace-root request (mirrors AwsWireRouter._servicebus_service, but an
    entity-scoped path additionally needs the entity to exist or an SB-only header)."""
    if "x-ms-version" in headers or "x-ms-blob-type" in headers or "x-amz-target" in headers:
        return False
    auth = str(headers.get("authorization") or "")
    if auth.startswith("AWS4-") or "X-Amz-" in path:
        return False
    segs = [s for s in path.split("?", 1)[0].split("/") if s]
    if not segs or segs[0] in ("api", "azure-data", "_wire", "v4", "static", "assets", "subscriptions"):
        return False
    sb_header = "brokerproperties" in headers or "atom+xml" in str(headers.get("content-type") or "")
    if sb_header:
        return True
    if segs[0].startswith("$") or not exists(segs[0]):
        return False
    return len(segs) == 1 or segs[1] in ("messages", "$deadletterqueue", "subscriptions")


def kv_root_path(path: str, query_string: bytes) -> bool:
    p = path.split("?", 1)[0]
    head = p.lstrip("/").split("/", 1)[0]
    return head in _KV_ROOTS and b"api-version=" in (query_string or b"")


class AzureDataPlaneRewrite:
    """`/secrets…?api-version` → `/azure-data/keyvault/_/secrets…`; registry shapes →
    `/azure-data/acr/…` (the native path is restored for the core in the handlers)."""

    def __init__(self, app, kv: bool, acr: bool, sb: bool = False):
        self.app, self.kv, self.acr, self.sb = app, kv, acr, sb

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            new = None
            if self.kv and kv_root_path(path, scope.get("query_string") or b""):
                new = "/azure-data/keyvault/_" + path
            elif self.acr and acr_path(path):
                new = "/azure-data/acr" + path
            elif self.sb and sb_path(path, {k.decode("latin-1").lower(): v.decode("latin-1")
                                            for k, v in scope.get("headers") or []}, _sb_exists):
                new = "/azure-data/sbroot" + path
            if new is not None:
                scope = dict(scope)
                scope["path"] = new
                scope["raw_path"] = new.encode("utf-8")
        await self.app(scope, receive, send)


def _query(request: Request) -> dict:
    return {k: v[-1] for k, v in parse_qs(request.scope.get("query_string", b"").decode("latin-1"),
                                          keep_blank_values=True).items()}


def _raw(request: Request) -> str:
    raw = request.scope.get("raw_path")
    p = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) and raw else request.url.path
    return p.split("?", 1)[0]


async def _kv(request: Request):
    body = await request.body()
    return _wi.to_response(_wi.dispatch_service("azure_keyvault", request.method, _raw(request),
                                                _query(request), dict(request.headers), body))


async def _acr(request: Request):
    body = await request.body()
    path = _raw(request)[len("/azure-data/acr"):] or "/"
    return _wi.to_response(_wi.dispatch_service("azure_acr", request.method, path,
                                                _query(request), dict(request.headers), body))


def _sb_exists(name: str) -> bool:
    """Read-only: is `name` a Service Bus entity of the tenant's Azure space? (Never creates a
    space or a slot — this runs for every candidate root path.)"""
    from urllib.parse import unquote
    try:
        from core import app_context as ctx
        ss = ctx.STATE.get("spaces") or {}
        tid = ctx.active_tenant_id()
        active = (ss.get("spaces") or {}).get(ss.get("active_space_id", "")) or {}
        cands = [active] + list((ss.get("spaces") or {}).values())
        for sp in cands:
            if not isinstance(sp, dict) or str(sp.get("provider") or "aws").lower() != "azure":
                continue
            if (sp.get("tenant_id") or ctx.DEFAULT_TENANT_ID) != tid:
                continue
            topics = ((sp.get("service_states") or {}).get("azure_azure_servicebus") or {}).get("topics") or {}
            return unquote(name) in topics
    except Exception:
        pass
    return False


async def _sb(request: Request):
    body = await request.body()
    path = _raw(request)[len("/azure-data/sbroot"):] or "/"
    from urllib.parse import unquote
    return _wi.to_response(_wi.dispatch_service("azure_servicebus", request.method, unquote(path),
                                                _query(request), dict(request.headers), body))


def register(app) -> None:
    kv, acr = _wi.is_unified("azure_keyvault"), _wi.is_unified("azure_acr")
    sb = _wi.is_unified("azure_servicebus")
    if sb:
        app.add_route("/azure-data/sbroot/{rest:path}", _sb, methods=_METHODS)
    if kv:
        app.add_route("/azure-data/keyvault/{vault}/{rest:path}", _kv, methods=_METHODS)
    if acr:
        app.add_route("/azure-data/acr/{rest:path}", _acr, methods=_METHODS)
        app.add_route("/azure-data/acr", _acr, methods=_METHODS)
    if kv or acr or sb:
        app.add_middleware(AzureDataPlaneRewrite, kv=kv, acr=acr, sb=sb)
