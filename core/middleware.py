"""Middleware extracted from server.py.

All middleware functions and classes live here.  The public entry-point is
``register_middleware(app)`` which adds every layer in the exact order that
``server.py`` originally registered them (registration order matters because
FastAPI's ``@app.middleware("http")`` and ``add_middleware()`` both execute in
**reverse** registration order).
"""

from __future__ import annotations

import os
import re
import time
import threading as _threading

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from core.app_context import (
    REQUEST_PROVIDER,
    REQUEST_PUBLIC_BASE,
    REQUEST_TENANT,
    STATE,
    active_tenant_id as _active_tenant_id,
    active_tier as _active_tier,
    azure_state_dict as _azure_state_dict,
    gcp_active_space_dict as _gcp_active_space_dict,
    gcp_iam_state,
    is_azure_native_path as _is_azure_native_path,
    is_gcp_native_path as _is_gcp_native_path,
    persist_state as _persist_state,
    resolve_provider_service as _resolve_provider_service,
    tenant_dict as _tenant_dict,
)

# ---------------------------------------------------------------------------
# Module-level constants & state used by rate-limiter
# ---------------------------------------------------------------------------

_RATE_LOCK = _threading.Lock()
_RATE_BUCKETS: dict[str, tuple[float, float]] = {}   # tenant_id -> (tokens, last_refill_ts)
_RATE_BURST_MULT = 4.0

_RATE_LIMIT_BYPASS_PATHS = (
    "/healthz", "/favicon.ico", "/static/", "/assets/",
    "/api/runtime/branding/",  # public CSS endpoint; per-tenant gate would loop
)

_TIER_ENFORCE = os.environ.get("CLOUDLEARN_TIER_ENFORCE", "1").strip() not in ("0", "false", "")

# ---------------------------------------------------------------------------
# GCP public-base capture helpers
# ---------------------------------------------------------------------------

_GCP_PUBLIC_BASE_ENV = os.environ.get("CLOUDLEARN_PUBLIC_URL", "").rstrip("/")
_GCP_PUBLIC_BASE_DYNAMIC = ""  # last non-local origin seen, for non-request contexts
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _gcp_capture_public_base(request) -> None:
    """Remember the simulator's externally-visible origin so GCP resource
    metadata (selfLinks, URIs, hostnames) reflects the simulator rather than
    *.googleapis.com. Stored per-request (ContextVar) to avoid cross-request
    races; a non-local value also seeds a global fallback for background
    contexts. An explicit CLOUDLEARN_PUBLIC_URL env var always wins."""
    global _GCP_PUBLIC_BASE_DYNAMIC
    if _GCP_PUBLIC_BASE_ENV:
        return
    try:
        host = request.headers.get("host") or request.url.netloc
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        if not host:
            return
        base = f"{scheme}://{host}"
        REQUEST_PUBLIC_BASE.set(base)
        # Only let a non-local request seed the global fallback, so the
        # container healthcheck (Host: 127.0.0.1) never pollutes it.
        if not any(host.split(":", 1)[0] == h for h in _LOCAL_HOSTS):
            _GCP_PUBLIC_BASE_DYNAMIC = base
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GCP IAM enforcement helper
# ---------------------------------------------------------------------------

def _gcp_iam_enforcement_response(request, path: str):
    """Return a 403 JSONResponse if IAM enforcement is enabled for the active
    space and the caller's bindings don't grant the operation; else None.
    Owners/root bypass, and any failure fails open so enforcement bugs never
    block the control plane."""
    try:
        space = _gcp_active_space_dict()
        if not (isinstance(space, dict) and space.get("enforce_iam")):
            return None
        from core import gcp_iam_policy
        required = gcp_iam_policy.permission_for_request(path, request.method)
        if not required:
            return None
        principal = request.headers.get("x-cloudlearn-principal") or str(space.get("active_principal") or "root")
        # space = project: union every stored policy's bindings (one project per space).
        policies = gcp_iam_state.get("policies", {}) if isinstance(gcp_iam_state.get("policies"), dict) else {}
        bindings: list = []
        for policy in policies.values():
            if isinstance(policy, dict):
                bindings.extend(policy.get("bindings", []) if isinstance(policy.get("bindings"), list) else [])
        if gcp_iam_policy.authorize(principal, required, bindings):
            return None
        return JSONResponse(status_code=403, content={"error": {
            "code": 403, "status": "PERMISSION_DENIED",
            "message": f"Permission '{required}' denied for principal '{principal}'.",
        }})
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Azure RBAC enforcement helper
# ---------------------------------------------------------------------------

def _azure_namespace_from_path(path: str) -> str:
    """Extract the Azure resource namespace (e.g. 'Microsoft.Compute') from an
    ARM-style request path like /subscriptions/.../providers/Microsoft.Compute/..."""
    lower = path.lower()
    idx = lower.find("/providers/")
    if idx == -1:
        return ""
    after = path[idx + len("/providers/"):]
    parts = after.split("/")
    return parts[0] if parts else ""


def _azure_action_matches(pattern: str, namespace: str, method: str) -> bool:
    """Check if an action pattern (e.g. 'Microsoft.Compute/*', '*', '*/read')
    matches the given namespace + HTTP method."""
    # Map HTTP method to Azure action suffix
    method_upper = method.upper()
    action_suffix_map = {
        "GET": "read",
        "PUT": "write",
        "PATCH": "write",
        "POST": "action",
        "DELETE": "delete",
    }
    action_suffix = action_suffix_map.get(method_upper, "read")

    # Wildcard matches everything
    if pattern == "*":
        return True

    # e.g. "*/read" matches any namespace for read operations
    if "/" in pattern:
        parts = pattern.split("/", 1)
        pat_ns = parts[0]
        pat_action = parts[1] if len(parts) > 1 else "*"
        # Check namespace match
        ns_match = (pat_ns == "*" or pat_ns.lower() == namespace.lower())
        # Check action match
        action_match = (pat_action == "*" or pat_action.lower() == action_suffix)
        return ns_match and action_match

    # Bare namespace without slash (unlikely but handle gracefully)
    return pattern.lower() == namespace.lower()


def _azure_rbac_enforcement_response(request, path: str):
    """Return a 403 JSONResponse if Azure RBAC enforcement is enabled for the
    active space and the caller's role assignments don't grant access; else None.
    Fails open so enforcement bugs never block the control plane."""
    try:
        space = _gcp_active_space_dict()
        if not (isinstance(space, dict) and space.get("enforce_rbac")):
            return None

        # Extract the namespace from the ARM path
        namespace = _azure_namespace_from_path(path)
        if not namespace:
            return None

        principal = request.headers.get("x-cloudlearn-principal") or str(space.get("active_principal") or "root")

        # Root/owner bypass
        if principal == "root":
            return None

        # Get the ARM resources for this space
        arm_resources = _azure_state_dict()

        # Find role assignments for this principal
        role_assignments = []
        for key, rec in arm_resources.items():
            rec_type = (rec.get("_type") or rec.get("type") or "").lower()
            if rec_type != "microsoft.authorization/roleassignments":
                continue
            props = rec.get("properties", {})
            if str(props.get("principalId", "")).lower() == principal.lower():
                role_assignments.append(rec)

        if not role_assignments:
            return JSONResponse(status_code=403, content={"error": {
                "code": "AuthorizationFailed",
                "message": f"Principal '{principal}' does not have any role assignments. Access is denied.",
            }})

        # For each assignment, look up the role definition and check permissions
        method = request.method
        for assignment in role_assignments:
            props = assignment.get("properties", {})
            role_def_id = str(props.get("roleDefinitionId", ""))

            # Find the role definition: check by id suffix or name
            role_def = None
            for rkey, rrec in arm_resources.items():
                rrec_type = (rrec.get("_type") or rrec.get("type") or "").lower()
                if rrec_type != "microsoft.authorization/roledefinitions":
                    continue
                rd_props = rrec.get("properties", {})
                # Match by role name (e.g. "Contributor") or by resource id
                if (rd_props.get("roleName", "").lower() == role_def_id.lower()
                        or rrec.get("name", "").lower() == role_def_id.lower()
                        or rrec.get("id", "").lower().endswith("/" + role_def_id.lower())):
                    role_def = rrec
                    break

            if not role_def:
                continue

            rd_props = role_def.get("properties", {})
            permissions_list = rd_props.get("permissions", [])

            for perm in permissions_list:
                actions = perm.get("actions", [])
                not_actions = perm.get("notActions", [])

                # Check if any action pattern matches
                action_granted = any(
                    _azure_action_matches(act, namespace, method)
                    for act in actions
                )
                if not action_granted:
                    continue

                # Check notActions for exclusions
                action_denied = any(
                    _azure_action_matches(na, namespace, method)
                    for na in not_actions
                )
                if action_denied:
                    continue

                # Permission granted
                return None

        return JSONResponse(status_code=403, content={"error": {
            "code": "AuthorizationFailed",
            "message": f"Principal '{principal}' does not have permission to perform this action on namespace '{namespace}'.",
        }})
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rate-limit token-bucket helper
# ---------------------------------------------------------------------------

def _rate_limit_tenant(tenant_id: str, rps: int) -> tuple[bool, float]:
    """Try to consume 1 token from the tenant's bucket. Returns
    `(allowed, retry_after_seconds)`. `rps <= 0` means UNLIMITED -> always allow."""
    if rps <= 0:
        return True, 0.0
    burst = float(rps) * _RATE_BURST_MULT
    now = time.time()
    with _RATE_LOCK:
        tokens, last = _RATE_BUCKETS.get(tenant_id, (burst, now))
        elapsed = now - last
        tokens = min(burst, tokens + elapsed * rps)
        if tokens >= 1.0:
            tokens -= 1.0
            _RATE_BUCKETS[tenant_id] = (tokens, now)
            return True, 0.0
        retry_after = max(0.001, (1.0 - tokens) / float(rps))
        _RATE_BUCKETS[tenant_id] = (tokens, now)
        return False, retry_after


# ---------------------------------------------------------------------------
# _DecompressRequestMiddleware (ASGI middleware class)
# ---------------------------------------------------------------------------

class _DecompressRequestMiddleware:
    """Transparently decode gzip/deflate-compressed request bodies. Real Google
    client libraries (e.g. google-cloud-storage for Java) gzip their JSON request
    bodies; without this the handlers' `await request.json()` chokes on the gzip
    magic bytes (0x1f 0x8b) with a UnicodeDecodeError -> 500."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for (k, v) in (scope.get("headers") or [])}
        enc = headers.get(b"content-encoding", b"").lower()
        if enc not in (b"gzip", b"x-gzip", b"deflate"):
            return await self.app(scope, receive, send)
        import gzip as _gzip
        import zlib as _zlib
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.request":
                body += message.get("body", b"")
                more = message.get("more_body", False)
            elif message["type"] == "http.disconnect":
                break
        try:
            body = _gzip.decompress(body) if enc in (b"gzip", b"x-gzip") else _zlib.decompress(body)
        except Exception:
            pass  # leave body untouched if it wasn't actually compressed
        new_headers = [
            (k, v) for (k, v) in (scope.get("headers") or [])
            if k.lower() not in (b"content-encoding", b"content-length")
        ]
        new_headers.append((b"content-length", str(len(body)).encode("ascii")))
        new_scope = dict(scope)
        new_scope["headers"] = new_headers
        delivered = False

        async def _receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        return await self.app(new_scope, _receive, send)


# ---------------------------------------------------------------------------
# HTTP middleware functions
# ---------------------------------------------------------------------------

async def azure_blob_dispatch_middleware(request, call_next):
    """Route native Azure Blob SDK requests to the Azure handler.

    The azure-storage-blob SDK addresses blobs path-style as
    ``/{account}/{container}/{blob}`` — identical in shape to S3's
    ``/{bucket}/{key}`` — so without disambiguation the request falls through
    to the S3 catch-all and comes back as a ``NoSuchBucket`` XML error (an S3
    error leaking onto an Azure client). Every Azure Storage request carries an
    ``x-ms-version`` header that S3 never sends; we use it as the cloud
    signature and rewrite the path onto the existing ``/azure-data/blob/...``
    handler. This keeps each cloud on its own handler end-to-end — Azure
    responses and errors are always Azure-shaped, never S3's.

    Only blob is bridged here (the only Azure storage plane served path-style);
    queue/table would also carry ``x-ms-version`` but are not implemented on
    this surface.
    """
    try:
        path = request.scope.get("path", "") or ""
        host = (request.headers.get("host", "") or "").split(":")[0].lower()
        auth = (request.headers.get("authorization") or "").lower()

        # Host-based Azure data-plane routing (Key Vault + Storage Queue). Real
        # Azure gives each vault/account its OWN hostname ({vault}.vault.azure.net,
        # {acct}.queue.core.windows.net) and the SDKs rebuild request URLs from the
        # HOST, dropping any path prefix — so a path-prefixed endpoint can't work
        # (CryptographyClient hits /keys/... at the root → S3 catch-all). We serve
        # them as *.vault.localtest.me / *.queue.localtest.me and rewrite onto the
        # existing /azure-data/{keyvault,queue}/{name} handlers. Must run BEFORE the
        # blob rule below, since queue requests also carry x-ms-version.
        _m_kv = re.match(r"^([a-z0-9][a-z0-9-]*)\.vault\.", host)
        _m_q = re.match(r"^([a-z0-9][a-z0-9-]*)\.queue\.", host)
        _m_ac = re.match(r"^([a-z0-9][a-z0-9-]*)\.azconfig\.", host)   # App Configuration: {store}.azconfig.*
        if (_m_kv or _m_q or _m_ac) and not path.startswith("/azure-data"):
            kind, name = (("keyvault", _m_kv.group(1)) if _m_kv else
                          ("appconfig", _m_ac.group(1)) if _m_ac else ("queue", _m_q.group(1)))
            tail = "" if path == "/" else path
            new_path = f"/azure-data/{kind}/{name}{tail}"
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
            return await call_next(request)
        # Cosmos SDK auth token is `type=master&...` (often URL-encoded as
        # `type%3dmaster`). It addresses /, /dbs, /dbs/{db}/colls/... at the
        # ROOT and ALSO carries x-ms-version — so detect it FIRST, before the
        # blob rule below would steal it. The SDK drops the account from the
        # path, so route under a fixed `_default` account (Cosmos is space-scoped).
        is_cosmos = ("type%3dmaster" in auth or "type=master" in auth
                     or "type%3dresource" in auth or "type=resource" in auth)
        passthrough = (path.startswith("/azure-data") or path.startswith("/api/")
                       or path.startswith("/assets") or path.startswith("/static")
                       or path in ("/healthz", "/favicon.ico"))
        if is_cosmos and not path.startswith("/azure-data"):
            new_path = "/azure-data/cosmos/_default/" + path.lstrip("/")
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
        elif (request.headers.get("x-ms-version") and not passthrough
                and path not in ("/",)):
            new_path = "/azure-data/blob" + path
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
    except Exception:
        pass
    return await call_next(request)


_METER_TIMER = None


def _storage_write_provider(request, path: str) -> str:
    """Provider whose object-storage data plane this request writes to ('' if none)."""
    if request.method not in ("PUT", "POST"):
        return ""
    if path.startswith("/upload/storage/v1/"):
        return "gcp"
    if path.startswith("/azure-data/blob"):
        return "azure"
    if "/s3/aws4_request" in (request.headers.get("authorization") or ""):
        return "aws"
    return ""


def _schedule_savings_refresh() -> None:
    """Recompute the space's resource graph + cost savings ~1 s after a write (debounced)."""
    global _METER_TIMER
    import threading
    if _METER_TIMER is not None and _METER_TIMER.is_alive():
        return

    def _refresh():
        try:
            from server import _cloudsim_refresh_bridge
            _cloudsim_refresh_bridge("savings.refresh", {})
        except Exception:
            pass
    _METER_TIMER = threading.Timer(1.0, _refresh)
    _METER_TIMER.daemon = True
    _METER_TIMER.start()


def _meter_storage_write(request, response, orig_path: str) -> None:
    """Meter bytes stored + a write request so savings include real storage billing;
    any other successful write schedules a savings refresh so new resources count."""
    try:
        if response.status_code >= 300 or request.method not in ("PUT", "POST", "DELETE", "PATCH"):
            return
        provider = _storage_write_provider(request, request.scope.get("path", "") or orig_path)
        if provider:
            try:
                nbytes = int(request.headers.get("x-amz-decoded-content-length")
                             or request.headers.get("content-length") or 0)
            except ValueError:
                nbytes = 0
            from core import usage_meter
            space_id = (STATE.get("spaces") or {}).get("active_space_id", "")
            usage_meter.record(space_id, provider, nbytes)
        _schedule_savings_refresh()
    except Exception:
        pass


async def provider_api_alias_middleware(request, call_next):
    response = await _provider_api_alias(request, call_next)
    _meter_storage_write(request, response, request.scope.get("path", ""))
    return response


async def _provider_api_alias(request, call_next):
    path = request.scope.get("path", "")
    _gcp_capture_public_base(request)
    if _is_azure_native_path(path):
        provider = "azure"
    elif _is_gcp_native_path(path) or path.startswith(("/ws/gcp/compute/", "/ws/compute/")):
        provider = "gcp"
    else:
        provider = "aws"
    token = REQUEST_PROVIDER.set(provider)
    request.state.cloudlearn_provider = provider
    request.state.cloudlearn_original_path = path
    if _is_azure_native_path(path):
        try:
            if not path.startswith(("/api/azure/",)):
                denied = _azure_rbac_enforcement_response(request, path)
                if denied is not None:
                    return denied
            return await call_next(request)
        finally:
            REQUEST_PROVIDER.reset(token)
    if _is_gcp_native_path(path) or path.startswith(("/ws/gcp/compute/", "/ws/compute/")):
        try:
            if not path.startswith(("/ws/", "/api/gcp/console/")):
                denied = _gcp_iam_enforcement_response(request, path)
                if denied is not None:
                    return denied
            return await call_next(request)
        finally:
            REQUEST_PROVIDER.reset(token)
    if path.startswith("/api/gcp/"):
        request.scope["path"] = "/api/" + path[len("/api/gcp/"):]
    try:
        return await call_next(request)
    finally:
        REQUEST_PROVIDER.reset(token)


async def tenant_context_middleware(request, call_next):
    """Read X-CloudLearn-Tenant header -> request-scoped tenant override
    (ContextVar). Without the header, requests fall through to the globally
    active tenant. Cross-tenant access is then blocked by the state proxy."""
    tid = (request.headers.get("x-cloudlearn-tenant") or "").strip()
    # Shared-instance multi-user: when no explicit header, bind the request to the
    # developer's tenant from their signed `vyomi_dev` cookie. Off unless
    # VYOMI_SHARED_INSTANCE is set; fail-soft (any error falls through to the
    # global active tenant, i.e. unchanged behavior).
    if not tid:
        try:
            from core import shared_tenancy as _sh
            if _sh.shared_enabled():
                resolved = _sh.resolve_dev_token(request.cookies.get(_sh.COOKIE_NAME, ""))
                if resolved:
                    # Offboarded developer (Phase 6): valid token, but access has
                    # been severed. Refuse — their resources stay, but they can't
                    # reach them. 403 rather than falling through to a global tenant.
                    if _sh.is_disabled(resolved):
                        return JSONResponse(status_code=403, content={
                            "error": {"ok": False, "code": "offboarded",
                                      "reason": "Access for this developer has been revoked."}})
                    tid = resolved
        except Exception:
            pass
    if tid:
        from core.app_context import tenants_state as _tenants_state
        known_tenants = _tenants_state().get("tenants", {})
        if tid not in known_tenants:
            return JSONResponse(status_code=403, content={
                "error": {"ok": False, "code": "unknown_tenant",
                          "reason": f"Tenant '{tid}' not found"}
            })
        # MVP: shared namespaces are unconditional/unfiltered/unlimited — NO per-tenant
        # resource quota. (Fairness caps are deferred; see shared_tenancy.set_quota.)
    token = REQUEST_TENANT.set(tid) if tid else None
    try:
        response = await call_next(request)
    finally:
        if token is not None:
            REQUEST_TENANT.reset(token)
    return response


def _capability_denied_response(_srv, path: str, exc):
    """The structured 403 the consoles show for a tier-locked service (same body as
    the tier middleware: {"error": {code, reason, upgrade_to, active_tier, ...}})."""
    if exc.status_code != 403:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    pack = ""
    try:
        pack = _srv.PLATFORM.kernel.capability_for_path(path) or ""
    except Exception:
        pass
    parts = pack.split(".")   # cloudlearn.<service>.<plan> (AWS) | cloudlearn.<gcp|azure>.<service>.<plan>
    if len(parts) >= 4:
        cloud, service = parts[1], parts[2]
    elif len(parts) == 3:
        cloud, service = "aws", parts[1]
    else:
        cloud, service = "", ""
    try:
        tenant = _tenant_dict(_active_tenant_id()) or {}
    except Exception:
        tenant = {}
    tier = str(tenant.get("license_tier") or (STATE.get("license") or {}).get("tier") or "free")
    result: dict = {}
    try:
        from core import tier_policy as _tp
        result = _tp.check_service(tier, service, request_cloud=cloud or None) if service else {}
    except Exception:
        result = {}
    if not result or result.get("ok"):
        result = {"code": "tier_service_locked", "upgrade_to": "max",
                  "reason": f"{service or 'This service'} is not included in the {tier} tier"}
    result.update({"ok": False, "active_tier": tier, "service": service, "provider": cloud,
                   "detail": exc.detail, "pack": pack})
    return JSONResponse({"error": result}, status_code=403,
                        headers={"X-CloudLearn-Tier-Denied": result.get("code", "tier_locked")})


async def _capability_middleware(request: Request, call_next):
    # Lazy imports for functions still in server.py
    import server as _srv
    _iam_principal_from_request = _srv._iam_principal_from_request
    _iam_resolve_identity = _srv._iam_resolve_identity
    _iam_route_action_resource = _srv._iam_route_action_resource
    _iam_authorize = _srv._iam_authorize
    _iam_deny_response = _srv._iam_deny_response
    _ensure_capability = _srv._ensure_capability

    principal = _iam_principal_from_request(request)
    request.state.iam_principal = principal
    identity = _iam_resolve_identity(principal)
    request.state.iam_identity = identity
    auth = _iam_route_action_resource(request)
    # GCP-native requests are authorized by the GCP IAM PDP (in the provider
    # middleware), not the AWS action model -- don't double-check them as S3/EC2.
    if auth is not None and not identity.get("is_root") and not _is_gcp_native_path(request.url.path) and not _is_azure_native_path(request.url.path):
        action, resource = auth
        allowed, reason = _iam_authorize(principal, action, resource, {
            "aws:PrincipalArn": identity.get("arn", ""),
            "aws:PrincipalType": identity.get("type", ""),
            "aws:username": identity.get("name", ""),
            "aws:RequestedRegion": "us-east-1",
        })
        if not allowed:
            return _iam_deny_response(request, action, resource, reason)
    capability_path = getattr(request.state, "cloudlearn_original_path", request.url.path)
    try:
        _ensure_capability(capability_path)
    except HTTPException as exc:
        # Raised in a middleware, an HTTPException is outside FastAPI's
        # exception handlers: a tier-locked console list (/api/dynamodb/tables on
        # Free) became "500 Exception in ASGI application" instead of the 403
        # the console can explain. Answer it here, in the tier middleware's shape.
        return _capability_denied_response(_srv, capability_path, exc)
    response = await call_next(request)
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        try:
            _persist_state()
        except Exception:
            pass
    return response


async def _rate_limit_middleware(request: Request, call_next):
    """Per-tenant token-bucket rate limit. Bypasses health probes + static."""
    p = request.url.path
    # CLOUDLEARN_TIER_ENFORCE=0 is the test/dev escape hatch for every tier
    # limit; the per-tier rate limit is one of them (CI conformance would
    # otherwise 429 against the Free-tier 10 rps cap).
    if not _TIER_ENFORCE or any(p.startswith(x) for x in _RATE_LIMIT_BYPASS_PATHS):
        return await call_next(request)
    try:
        tid = _active_tenant_id() or "anonymous"
        from core import tier_policy as _tp
        tier = _active_tier()
        rps = _tp.rate_limit_rps(tier)
        allowed, retry_after = _rate_limit_tenant(tid, rps)
        if not allowed:
            return JSONResponse({
                "error": {
                    "ok": False, "code": "rate_limited",
                    "reason": f"{tier} tier limit: {rps} requests/sec sustained",
                    "active_tier": tier,
                    "tenant_id": tid,
                    "rate_limit_rps": rps,
                    "retry_after_s": round(retry_after, 3),
                    "docs": "https://cloudlearn.io/docs/tiers",
                }
            }, status_code=429, headers={
                "Retry-After": str(max(1, int(retry_after + 0.999))),
                "X-RateLimit-Limit-RPS": str(rps),
                "X-CloudLearn-Tier": tier,
            })
    except Exception:
        pass  # never let the limiter break a request
    return await call_next(request)


async def _tier_enforcement_middleware(request: Request, call_next):
    """Enforce tier_policy.check_service before handlers run.

    Lets non-provider requests through. On denial, returns a structured
    JSON 403 body the SPA renders as an upgrade modal.
    """
    # -- Custom-domain Host -> tenant resolution (Enterprise tier) ----------
    # When the inbound Host matches a configured custom-domain, set the
    # active tenant for the rest of this request. Tenants without a custom
    # domain are unaffected (the regular X-CloudLearn-Tenant header path
    # still works).
    try:
        from core import tenant_theming as _tt
        host_header = request.headers.get("host", "")
        domain_tenant = _tt.resolve_domain_to_tenant(STATE, host_header)
        if domain_tenant:
            # Stash for downstream handlers to read via state
            request.state.resolved_tenant_id = domain_tenant
    except Exception:
        pass

    # -- Cross-tenant RBAC: X-CloudLearn-Acting-As-Tenant header ------------
    # When a user wants to operate on another tenant's resources via an
    # explicit grant, they send the target tenant in this header. The
    # grant is checked against cross_tenant_rbac.check() -- on deny -> 403;
    # on allow -> request executes against the target tenant's state.
    acting_as = request.headers.get("x-cloudlearn-acting-as-tenant", "").strip()
    if acting_as:
        try:
            from core import cross_tenant_rbac as _xt
            grantee = _active_tenant_id()  # the caller's actual tenant
            # Service hint from URL for fine-grained scope. Best-effort.
            svc_hint = ""
            try:
                _provider_svc, _svc_key = _resolve_provider_service(request)
                svc_hint = _svc_key or ""
            except Exception:
                pass
            grant_check = _xt.check(STATE, grantee, acting_as,
                                     request.method, service=svc_hint)
            if not grant_check.get("ok"):
                return JSONResponse({
                    "error": {
                        "ok": False, "code": "xt_rbac_denied",
                        "reason": grant_check.get("reason", "cross-tenant access not granted"),
                        "grantee_tenant": grantee,
                        "target_tenant": acting_as,
                        "method": request.method,
                        "service": svc_hint,
                        "docs": "https://cloudlearn.io/docs/cross-tenant-rbac",
                    }
                }, status_code=403, headers={"X-CloudLearn-XTRBAC-Denied": "1"})
            # Grant approved -- swap the resolved tenant for this request.
            request.state.resolved_tenant_id = acting_as
            request.state.xt_rbac_grant_id = grant_check.get("grant_id", "")
            request.state.xt_rbac_role = grant_check.get("role", "")
        except Exception:
            pass  # fail-open on lookup errors (logged via diagnostics elsewhere)

    provider, service_key = _resolve_provider_service(request)

    # -- PROFILE gate (VYOMI_PROFILE) — enforced INDEPENDENTLY of tier ---------
    # A sandbox booted for one cloud (e.g. aws-full) denies requests to clouds
    # not in the profile (GCP/Azure), even when CLOUDLEARN_TIER_ENFORCE=0.
    if provider and service_key:
        from core import tier_policy as _tp
        pres = _tp.check_profile(service_key, request_cloud=provider)
        if not pres.get("ok"):
            pres["active_profile"] = _tp.active_profile()
            pres["docs"] = "https://vyomi.cloud/docs/profiles"
            return JSONResponse(
                {"error": pres}, status_code=403,
                headers={"X-Vyomi-Profile-Denied": pres.get("code", "profile_locked")})

    if not _TIER_ENFORCE:
        return await call_next(request)
    if not provider or not service_key:
        return await call_next(request)

    # Get active tenant's tier + primary_cloud (Student-only).
    try:
        tenant = _tenant_dict(_active_tenant_id()) or {}
    except Exception:
        tenant = {}
    tier = str(tenant.get("license_tier")
               or (STATE.get("license") or {}).get("tier")
               or "free")
    # Same cutoff as server._active_tier: a lapsed subscription / ended trial
    # reads as Free immediately, offline, before the next refresh lands.
    if tier != "free":
        try:
            from core import license_remote as _lr
            if _lr.is_sub_expired(STATE.get("license_claims") or {}):
                tier = "free"
        except Exception:
            pass
    primary_cloud = str(tenant.get("primary_cloud") or "")

    # -- SSO Bearer-token validation (Enterprise tier, when configured) -----
    # If a Bearer token is present AND the active tenant has SSO configured,
    # validate the token against the IdP's JWKS. Bare-header (no Bearer)
    # requests pass through unchanged so existing X-CloudLearn-Tenant flows
    # keep working -- SSO is additive, not replacement.
    authz = request.headers.get("authorization", "")
    if authz.startswith("Bearer ") and tenant:
        sso_conf = (STATE.get("sso_config") or {}).get(_active_tenant_id()) or {}
        if sso_conf.get("enabled"):
            try:
                from core import sso_config as _sso
                validation = _sso.validate_bearer(STATE, _active_tenant_id(), authz)
                if not validation.get("ok"):
                    return JSONResponse({
                        "error": {
                            "ok": False, "code": "sso_invalid_token",
                            "reason": validation.get("reason", "invalid"),
                            "active_tier": tier,
                            "docs": "https://cloudlearn.io/docs/sso",
                        }
                    }, status_code=401, headers={"X-CloudLearn-SSO-Denied": "1"})
                # Stash claims for downstream handlers
                request.state.sso_user = validation.get("user_identifier")
                request.state.sso_claims = validation.get("claims")
            except Exception:
                pass  # fail-open on internal errors

    from core import tier_policy as _tp
    result = _tp.check_service(tier, service_key,
                               primary_cloud=primary_cloud,
                               request_cloud=provider)
    if not result["ok"]:
        # Augment with the docs URL + active tier facts for the SPA modal.
        result["active_tier"] = tier
        result["request_provider"] = provider
        result["request_service"] = service_key
        result["docs"] = "https://cloudlearn.io/docs/tiers"
        # Fire a notifications event for tier-limit denials so configured
        # channels (Slack/webhook) get a heads-up when users hit a wall.
        try:
            from core import notifications as _nt
            _nt.emit(STATE, _active_tenant_id(), "tier.limit_denied", {
                "summary": result.get("reason", "tier limit hit"),
                "active_tier": tier, "code": result.get("code"),
                "upgrade_to": result.get("upgrade_to"),
                "provider": provider, "service": service_key,
            })
        except Exception:
            pass
        return JSONResponse(
            {"error": result},
            status_code=403,
            headers={"X-CloudLearn-Tier-Denied": result.get("code", "tier_locked")},
        )

    # -- Cedar IAM enforcement ------------------------------------------------
    # Cedar fires for ALL tiers when the active space has explicit Cedar
    # policies configured.  When no policies exist, cedar_engine returns
    # default-allow so this is a no-op for users who haven't set up IAM.
    # (Previously gated on Developer+ tiers only; now any tier can opt-in
    # by adding Cedar policies to their space.)
    tier_policy = _tp.policy_for(tier)
    _cedar_tier_enabled = (tier_policy.get("features") or {}).get("cedar_enforcement")
    # Check whether the space has explicit Cedar policies — if so, enforce
    # regardless of tier.
    _cedar_space_has_policies = False
    try:
        spaces_state = STATE.get("spaces") or {}
        _active_space_id_check = spaces_state.get("active_space_id", "")
        if _active_space_id_check:
            from core import cedar_engine as _cedar_check
            _cedar_space_has_policies = bool(_cedar_check.get_policies(_active_space_id_check).strip())
    except Exception:
        pass
    if _cedar_tier_enabled or _cedar_space_has_policies:
        try:
            spaces_state = STATE.get("spaces") or {}
            active_space_id = spaces_state.get("active_space_id", "")
            if active_space_id:
                from core import cedar_engine as _cedar
                principal = f'User::"{_active_tenant_id()}"'
                action = f'Action::"{provider}:{service_key}:{request.method}"'
                resource = f'Resource::"{provider}/{service_key}"'
                allowed, reason = _cedar.evaluate(
                    active_space_id, principal, action, resource,
                    context={"path": str(request.url.path),
                             "method": request.method,
                             "provider": provider,
                             "service": service_key},
                )
                if not allowed:
                    return JSONResponse({
                        "error": {
                            "ok": False, "code": "cedar_denied",
                            "reason": f"Cedar policy denied this action: {reason}",
                            "active_tier": tier,
                            "principal": principal,
                            "action": action,
                            "resource": resource,
                            "diagnostic": reason,
                            "docs": "https://cloudlearn.io/docs/cedar",
                        }
                    }, status_code=403, headers={"X-CloudLearn-Cedar-Denied": "1"})
        except Exception:
            # Never let Cedar errors break the control plane -- fail-open with
            # a log line. Operators see the issue via /api/iam/evaluate probes.
            pass

    return await call_next(request)


# ---------------------------------------------------------------------------
# Public entry-point: register all middleware on the FastAPI app
# ---------------------------------------------------------------------------

async def request_recorder_middleware(request, call_next):
    """Record every provider-scoped request (provider, service, path, status, latency) for the
    console Metrics tabs. Outermost layer so it times the whole stack; never alters the response."""
    path = request.url.path
    if path.startswith(("/api/metrics", "/static/", "/assets/", "/console")) or path in ("/healthz", "/favicon.ico"):
        return await call_next(request)
    t0 = time.time()
    status = 500
    body = b""
    if request.method in _GCP_MUTATING and ("/gcp/" in path or path.startswith("/v1")):
        try:
            body = await request.body()
        except Exception:
            body = b""
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        try:
            from core import request_metrics as _rm
            prov, svc = _rm.classify(path, _resolve_provider_service(request))
            if prov and svc:
                _rm.record(prov, svc, request.method, path, status, (time.time() - t0) * 1000.0,
                           query=request.url.query or "", host=request.headers.get("host", ""))
                if prov == "gcp" and request.method in _GCP_MUTATING and status < 300:
                    _record_gcp_activity(svc, request.method, path, body)
        except Exception:
            pass


_GCP_MUTATING = ("POST", "PUT", "PATCH", "DELETE")
_GCP_READ_VERBS = ("get", "list", "search", "query", "lookup", "batchget", "test", "run", "read", "fetch")
# Services that record their own, richer activity events.
_GCP_SELF_RECORDING = ("artifactregistry",)


def _record_gcp_activity(svc: str, method: str, path: str, body: bytes) -> None:
    """Console Activity tab: one cloudsim event per successful GCP mutation, naming the
    resource it touched (body `name`, else the last path segment)."""
    if svc in _GCP_SELF_RECORDING:
        return
    last = path.rstrip("/").rsplit("/", 1)[-1]
    action = last.split(":", 1)[1] if ":" in last else ""
    if action.lower().startswith(_GCP_READ_VERBS):
        return
    name = last.split(":", 1)[0]
    try:
        import json as _json
        doc = _json.loads(body) if body else {}
        if isinstance(doc, dict):
            for k in ("name", "id", "instanceId", "databaseId", "topicId", "triggerId"):
                if isinstance(doc.get(k), str) and doc[k]:
                    name = doc[k].rsplit("/", 1)[-1]
                    break
    except Exception:
        pass
    if method == "POST" and not action:
        verb = "create"
    elif method in ("PUT", "PATCH"):
        verb = "update"
    elif method == "DELETE":
        verb = "delete"
    else:
        verb = action or "update"
    from core.app_context import record_usage
    record_usage(f"gcp.{svc}.{verb}", {"resource": name, "method": method, "path": path})


def register_middleware(app) -> None:
    """Add every middleware layer to *app* in the exact registration order
    that ``server.py`` originally used.

    Registration order (FastAPI runs these in **reverse**):

    1. ``@app.middleware("http")`` for ``provider_api_alias_middleware``
    2. ``@app.middleware("http")`` for ``tenant_context_middleware``
    3. ``app.add_middleware(_DecompressRequestMiddleware)``
    4. ``app.add_middleware(CORSMiddleware, ...)``
    5. ``@app.middleware("http")`` for ``_capability_middleware``
    6. ``@app.middleware("http")`` for ``_rate_limit_middleware``
    7. ``@app.middleware("http")`` for ``_tier_enforcement_middleware``
    """

    # 1. provider_api_alias_middleware
    app.middleware("http")(provider_api_alias_middleware)

    # 2. tenant_context_middleware
    app.middleware("http")(tenant_context_middleware)

    # 3. _DecompressRequestMiddleware (ASGI)
    app.add_middleware(_DecompressRequestMiddleware)

    # 4. CORSMiddleware — lock down origins in appliance mode
    from core.app_context import appliance_mode_enabled
    if appliance_mode_enabled():
        origins = ["http://localhost:9000", "http://127.0.0.1:9000",
                   "http://localhost:8080", "http://127.0.0.1:8080"]
    else:
        origins = ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["ETag", "x-amz-request-id", "x-amz-id-2", "Content-Range"],
    )

    # 5. _capability_middleware
    app.middleware("http")(_capability_middleware)

    # 6. _rate_limit_middleware
    app.middleware("http")(_rate_limit_middleware)

    # 7. _tier_enforcement_middleware
    app.middleware("http")(_tier_enforcement_middleware)

    # 8. azure_blob_dispatch — registered LAST so it is the OUTERMOST layer and
    # runs FIRST: it rewrites native Azure Blob SDK paths onto /azure-data/blob
    # before tier-enforcement classifies the provider or the S3 catch-all can
    # claim them. (Starlette runs http middleware in reverse registration order.)
    app.middleware("http")(azure_blob_dispatch_middleware)

    # 9. request_recorder_middleware — registered after azure_blob_dispatch so it is the outermost layer.
    app.middleware("http")(request_recorder_middleware)
