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
