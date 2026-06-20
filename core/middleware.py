"""Middleware extracted from server.py.

All middleware functions and classes live here.  The public entry-point is
``register_middleware(app)`` which adds every layer in the exact order that
``server.py`` originally registered them (registration order matters because
FastAPI's ``@app.middleware("http")`` and ``add_middleware()`` both execute in
**reverse** registration order).
"""

from __future__ import annotations

import os
import time
import threading as _threading

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
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
        if (request.headers.get("x-ms-version")
                and not path.startswith("/azure-data")
                and not path.startswith("/api/")
                and not path.startswith("/assets")
                and not path.startswith("/static")
                and path not in ("/", "/healthz", "/favicon.ico")):
            new_path = "/azure-data/blob" + path
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
    except Exception:
        pass
    return await call_next(request)


async def provider_api_alias_middleware(request, call_next):
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
    if tid:
        from core.app_context import tenants_state as _tenants_state
        known_tenants = _tenants_state().get("tenants", {})
        if tid not in known_tenants:
            return JSONResponse(status_code=403, content={
                "error": {"ok": False, "code": "unknown_tenant",
                          "reason": f"Tenant '{tid}' not found"}
            })
    token = REQUEST_TENANT.set(tid) if tid else None
    try:
        response = await call_next(request)
    finally:
        if token is not None:
            REQUEST_TENANT.reset(token)
    return response


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
    _ensure_capability(capability_path)
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
    if any(p.startswith(x) for x in _RATE_LIMIT_BYPASS_PATHS):
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

    if not _TIER_ENFORCE:
        return await call_next(request)

    provider, service_key = _resolve_provider_service(request)
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
