"""The simulator's externally-visible origin for the CURRENT request.

User-facing URLs (SQS QueueUrl, SNS unsubscribe, API Gateway invoke URL, ...) must point at the simulator
the client actually reached (localhost, a LAN host or a tunnel), never at the real cloud's hostname.
The front door (offline middleware / Nano wire router) calls ``set_from_headers`` once per request; cores call ``origin()``.
Pure stdlib so it vendors verbatim into the Nano bundle.
"""
from contextvars import ContextVar

_ORIGIN: ContextVar[str] = ContextVar("vyomi_public_origin", default="")


def set_from_headers(headers) -> str:
    hl = {str(k).lower(): v for k, v in (headers or {}).items()}
    host = hl.get("x-forwarded-host") or hl.get("host") or ""
    if not host:
        return ""
    base = f"{(hl.get('x-forwarded-proto') or 'http').split(',')[0].strip()}://{host.split(',')[0].strip()}"
    _ORIGIN.set(base)
    return base


def origin() -> str:
    """`http(s)://host[:port]` of this request ('' when unknown, e.g. a background task)."""
    return _ORIGIN.get()


def rewrite_app_hosts(text: str, origin: str) -> str:
    """App Service `<app>.azurewebsites.net` -> `<simulator host>/azure-data/site/<app>` (the front door that serves the app on the host the
    client reached). With a scheme (`https://app.azurewebsites.net/api/x`) the origin is used; bare host names get host[:port]/path.
    `<app>.scm.azurewebsites.net` has no route and is left alone."""
    import re
    if not origin or "azurewebsites.net" not in text:
        return text
    hostport = origin.split("://", 1)[-1]
    pat = re.compile(r"(https?://)?(?<![.\w-])([a-z0-9][a-z0-9-]*)\.azurewebsites\.net")
    return pat.sub(lambda m: (origin if m.group(1) else hostport) + "/azure-data/site/" + m.group(2), text)
