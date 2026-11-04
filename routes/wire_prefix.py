"""`/_wire/*` — same-origin native-wire prefix for the v4 consoles.

The v4 consoles call each cloud's NATIVE wire API (S3 REST+XML, X-Amz-Target
JSON, Query+XML, GCP REST, Azure ARM/data-plane) but cannot use the bare
native root, because the console page itself is served from that origin's
routes (`/`, `/aws`, ...). They therefore send `<METHOD> /_wire/<native path>`.

Design: an outermost pure-ASGI layer strips the prefix and re-dispatches the
SAME request (method, headers incl. x-amz-target / x-ms-* / content-type,
query string, streamed raw body) into the rest of the app at `/<native path>`.
Because the rewrite happens BEFORE every other middleware, the request is
indistinguishable from SDK/CLI traffic from that point on:

  * the same handler serves it (legacy per-service routes, the S3 catch-all,
    or the opt-in VYOMI_UNIFIED_INGRESS AwsWireRouter) → identical state;
  * every auth / tenant / profile / tier / RBAC middleware evaluates the
    NATIVE path → a request rejected at `/<rest>` is rejected at `/_wire/<rest>`
    (no bypass, and no path-keyed check is ever evaluated against `/_wire`);
  * the native response (status, headers, body) is returned untouched.

It is a single pass (no second trip through the middleware stack), so usage
metering / glass-box capture record the call once. `/_wire/_wire/...` is
refused with 400 (recursion guard) rather than re-stripped.
"""
from __future__ import annotations

import json

PREFIX = "/_wire"
SCOPE_FLAG = "vyomi.wire_prefix"   # set on rewritten scopes; handlers may inspect it


def strip_prefix(path: str) -> str | None:
    """`/_wire/x/y` → `/x/y`, `/_wire` or `/_wire/` → `/`; None if not prefixed."""
    if path == PREFIX:
        return "/"
    if path.startswith(PREFIX + "/"):
        return path[len(PREFIX):] or "/"
    return None


class WirePrefixMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        rest = strip_prefix(scope.get("path") or "")
        if rest is None:
            return await self.app(scope, receive, send)
        if rest == PREFIX or rest.startswith(PREFIX + "/") or scope.get(SCOPE_FLAG):
            return await _reject(send, 400, "WirePrefixRecursion",
                                 "Nested /_wire/ prefixes are not allowed.")
        new_scope = dict(scope)
        new_scope["path"] = rest
        raw = scope.get("raw_path")
        if isinstance(raw, (bytes, bytearray)) and raw.startswith(PREFIX.encode()):
            new_scope["raw_path"] = bytes(raw[len(PREFIX):]) or b"/"
        else:
            new_scope["raw_path"] = rest.encode("utf-8")
        new_scope[SCOPE_FLAG] = True
        return await self.app(new_scope, receive, send)


async def _reject(send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def register(app) -> None:
    """Install as the OUTERMOST user middleware. Call after every other
    add_middleware()/@app.middleware registration (server.py does so at the
    very end, next to the S3 catch-all) so the rewrite precedes all of them."""
    app.add_middleware(WirePrefixMiddleware)
