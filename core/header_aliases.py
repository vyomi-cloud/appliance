"""HTTP header alias middleware — Phase 7 of the v2.0.0 vyomi rebrand.

The appliance historically uses ``X-CloudLearn-*`` request and response
headers (Tenant, Tier-Denied, Bridge-Token, Admin-Key, Cedar-Denied, etc.).
Starting v2.0.0 the canonical name is ``X-Vyomi-*``. For back-compat we
ship **both** names on the wire — clients can send either, the server
sets both on responses — so no in-flight client breaks during the
transition.

Instead of touching the 24 read/write call sites in core/middleware.py,
core/admin_auth.py, core/audit_sinks.py, etc., we do this transparently
at the ASGI layer:

    Incoming  request : for each X-CloudLearn-X header, ensure
                        X-Vyomi-X is also present (and vice-versa) so
                        downstream handlers reading either name see the
                        value regardless of which one the client sent.

    Outgoing  response: same trick — any X-CloudLearn-X header the app
                        sets gets a matching X-Vyomi-X copy (and vice-
                        versa) before the response leaves the server.

The middleware is idempotent — if both aliases are already set, neither
is overwritten. Conflict resolution: server-side handlers that READ a
header should prefer ``X-Vyomi-*`` when both exist (already the case in
the few places that do this — see core/middleware.py: vyomi-first
fallback to cloudlearn).

Slated for removal in v3.0 alongside the CLI shim and env-var aliases.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Iterable

# Lower-case bytes prefixes — ASGI headers are bytes + case-insensitive.
_OLD_PREFIX = b"x-cloudlearn-"
_NEW_PREFIX = b"x-vyomi-"


def _alias_pairs(headers: Iterable[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Returns an augmented header list with X-CloudLearn-* ↔ X-Vyomi-*
    aliases added for any pair that's missing one side. Doesn't mutate
    the input. Idempotent."""
    out = list(headers)
    present_lower: set[bytes] = {name.lower() for name, _ in out}
    for name, value in list(out):
        n_lower = name.lower()
        if n_lower.startswith(_OLD_PREFIX):
            # X-CloudLearn-Foo → also publish X-Vyomi-Foo
            alias = _NEW_PREFIX + n_lower[len(_OLD_PREFIX):]
            if alias not in present_lower:
                out.append((alias, value))
                present_lower.add(alias)
        elif n_lower.startswith(_NEW_PREFIX):
            # X-Vyomi-Foo → also publish X-CloudLearn-Foo (legacy clients)
            alias = _OLD_PREFIX + n_lower[len(_NEW_PREFIX):]
            if alias not in present_lower:
                out.append((alias, value))
                present_lower.add(alias)
    return out


class HeaderAliasMiddleware:
    """ASGI-level X-CloudLearn-* ↔ X-Vyomi-* alias bridge.

    Wraps the FastAPI app. Doesn't touch the body, query string, or
    anything except the headers list. Adds at most ~14 entries per
    request (one per X-CloudLearn-* header in current use); the
    overhead is negligible (microseconds)."""

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]],
                       send: Callable[[dict], Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Inbound: clone & augment the request headers BEFORE handlers run.
        scope = dict(scope)
        scope["headers"] = _alias_pairs(scope.get("headers", []))

        # Outbound: intercept the http.response.start message and alias
        # any X-CloudLearn-*/X-Vyomi-* response headers the app sets.
        async def aliased_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                message = dict(message)
                message["headers"] = _alias_pairs(message.get("headers", []))
            await send(message)

        await self.app(scope, receive, aliased_send)
