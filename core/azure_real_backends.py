"""Real Azurite as the simulator's Azure Table (and Storage Queue) data plane (offline / Mesh only).

Switch: VYOMI_AZURE_REAL_BACKENDS=1 plus VYOMI_AZURE_AZURITE_ENDPOINT. Off (the default) this module
does nothing. Never enabled on Nano: Azurite is a Node process and needs a container runtime.

  VYOMI_AZURE_AZURITE_ENDPOINT      Azurite host, e.g. `azurite` or `http://127.0.0.1` (default scheme http).
                                    A value that already carries a port is used as the TABLE endpoint.
  VYOMI_AZURE_AZURITE_TABLE_PORT    default 10002 (ignored when the endpoint carries a port)
  VYOMI_AZURE_AZURITE_QUEUE_PORT    default 10001
  VYOMI_AZURE_REAL_QUEUE=0          opt the Storage Queue wire back out (Table only)

How: install() replaces `azure_table_core.dispatch` and `azure_queue_core.dispatch` with wrappers that
forward the native REST request to Azurite, re-signed with Azurite's well-known development account
(devstoreaccount1 + its published key). Every caller already goes through those two functions (the wire
front door via azure_storage_svc_core.serve, Event Grid's queue destination), so one seam covers them and
the cores stay untouched (Nano keeps them). What stays on the simulator's own code: storage-account
service properties / CORS / logging / metrics (azure_storage_svc_core wraps the dispatch), the ARM
control plane (Microsoft.Storage accounts and ARM table records).

Unreachable Azurite -> 503 naming the endpoint; there is no silent fallback to the in-process core.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.utils import formatdate

_log = logging.getLogger("vyomi.realbackends")
ENV = "VYOMI_AZURE_REAL_BACKENDS"
ACCOUNT = "devstoreaccount1"
# Azurite's published development key (documented by Microsoft; not a secret).
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
VERSION = "2021-08-06"
_installed = False

_DROP_REQ = {"host", "authorization", "content-length", "date", "x-ms-date", "x-ms-version", "connection",
             "accept-encoding", "x-vyomi-account", "x-vyomi-service", "x-forwarded-for", "x-forwarded-proto",
             "x-forwarded-host", "x-real-ip", "cookie", "origin", "referer", "user-agent", "x-http-method"}
_DROP_RESP = {"transfer-encoding", "content-length", "connection", "date", "server", "keep-alive"}


def _truthy(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _endpoint() -> str:
    return (os.environ.get("VYOMI_AZURE_AZURITE_ENDPOINT") or "").strip().rstrip("/")


def enabled(kind: str = "table") -> bool:
    if sys.platform == "emscripten" or not _truthy(os.environ.get(ENV, "")) or not _endpoint():
        return False
    if kind == "queue" and os.environ.get("VYOMI_AZURE_REAL_QUEUE", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return True


def base_url(kind: str = "table") -> str:
    ep = _endpoint()
    if "://" not in ep:
        ep = "http://" + ep
    u = urllib.parse.urlsplit(ep)
    if u.port and kind == "table":
        return f"{u.scheme}://{u.netloc}"
    host = u.hostname or "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    port = os.environ.get("VYOMI_AZURE_AZURITE_TABLE_PORT", "10002") if kind == "table" else \
        os.environ.get("VYOMI_AZURE_AZURITE_QUEUE_PORT", "10001")
    return f"{u.scheme}://{host}:{port}"


def status() -> dict:
    return {"enabled": enabled(), "table": base_url("table") if enabled() else "",
            "queue": base_url("queue") if enabled("queue") else "", "installed": _installed}


# ── signing (SharedKey / SharedKeyLite for devstoreaccount1) ─────────────────────────────
def _sign(sts: str) -> str:
    return base64.b64encode(hmac.new(base64.b64decode(KEY), sts.encode("utf-8"), hashlib.sha256).digest()).decode()


def _canon_resource(path: str, query: dict, lite_table: bool) -> str:
    # `path` already starts with /devstoreaccount1: Azurite's path-style (IP) URL signs the account twice
    res = "/" + ACCOUNT + path
    if lite_table:
        return res + (f"?comp={query['comp']}" if query.get("comp") else "")
    for k in sorted(query, key=str.lower):
        res += f"\n{k.lower()}:{query[k]}"
    return res


def _sign_headers(kind: str, method: str, path: str, query: dict, headers: dict, body: bytes) -> dict:
    date = formatdate(usegmt=True)
    out = {"x-ms-date": date, "x-ms-version": VERSION}
    if kind == "table":
        sts = date + "\n" + _canon_resource(path, query, True)
        out["Authorization"] = f"SharedKeyLite {ACCOUNT}:{_sign(sts)}"
        return out
    h = {k.lower(): v for k, v in headers.items()}
    ch = "".join(f"{k}:{v}\n" for k, v in sorted({**{k: v for k, v in h.items() if k.startswith("x-ms-")}, **out}.items()))
    length = str(len(body)) if body else ""
    sts = "\n".join([method, h.get("content-encoding", ""), h.get("content-language", ""), length, h.get("content-md5", ""),
                     h.get("content-type", ""), "", h.get("if-modified-since", ""), h.get("if-match", ""),
                     h.get("if-none-match", ""), h.get("if-unmodified-since", ""), h.get("range", "")]) + "\n" + ch + \
        _canon_resource(path, query, False)
    out["Authorization"] = f"SharedKey {ACCOUNT}:{_sign(sts)}"
    return out


# ── HTTP to Azurite ──────────────────────────────────────────────────────────────────────
def _norm_path(kind: str, path: str, query: dict) -> str:
    segs = [s for s in path.split("/") if s]
    if kind == "table":
        if segs and segs[0].lower() == ACCOUNT:
            segs = segs[1:]
    else:   # queue: the leading account segment is optional on the simulator's wire
        if segs and segs[0].lower() == ACCOUNT:
            segs = segs[1:]
        elif len(segs) == 1 and query.get("comp") == "list":
            segs = []
        elif len(segs) >= 2 and segs[1] != "messages":
            segs = segs[1:]
    return "/" + "/".join(segs)


def _forward(kind: str, method: str, path: str, query, headers, body, resp_cls):
    query = {k: ("" if v is None else str(v)) for k, v in (query or {}).items()}
    if "?" in path:
        path, _, qs = path.partition("?")
        query = {**dict(urllib.parse.parse_qsl(qs, keep_blank_values=True)), **query}
    hd = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()
    if method == "POST" and hd.get("x-http-method", "").upper() == "MERGE":
        method = "MERGE"
    body = body or b""
    qpath = "/" + ACCOUNT + _norm_path(kind, path, query)
    url = base_url(kind) + urllib.parse.quote(qpath, safe="/()',=$@:;!*~") + \
        (("?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)) if query else "")
    fwd = {k: v for k, v in hd.items() if k not in _DROP_REQ}
    fwd.update(_sign_headers(kind, method, qpath, query, fwd, body))
    req = urllib.request.Request(url, data=body or None,
                                 method=method, headers=fwd)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, rh, rb = r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        status, rh, rb = e.code, dict(e.headers.items()), e.read()
    except Exception as exc:
        msg = f"Azurite {kind} endpoint {base_url(kind)} is unreachable: {type(exc).__name__}"
        if kind == "table":
            return resp_cls(status=503, headers={"x-ms-error-code": "ServiceUnavailable"},
                            body=json.dumps({"odata.error": {"code": "ServiceUnavailable", "message": {"lang": "en-us", "value": msg}}}).encode())
        return resp_cls(status=503, headers={"x-ms-error-code": "ServerBusy", "content-type": "application/xml"},
                        body=f'<?xml version="1.0"?><Error><Code>ServerBusy</Code><Message>{msg}</Message></Error>'.encode(), media_type="application/xml")
    out = {k.lower(): v for k, v in rh.items() if k.lower() not in _DROP_RESP}
    ct = out.get("content-type")
    return resp_cls(status=status, headers=out, body=rb, media_type=ct if ct else None)


def _wrap(kind: str, mod):
    orig = mod.dispatch

    def dispatch(store, method, path, query=None, headers=None, body=b""):
        if not enabled(kind):
            return orig(store, method, path, query, headers, body)
        return _forward(kind, method, path, query, headers, body, mod.Response)
    dispatch.__wrapped__ = orig
    return dispatch


def install() -> bool:
    """Idempotent; a no-op unless VYOMI_AZURE_REAL_BACKENDS=1 and an Azurite endpoint is set."""
    global _installed
    if _installed or not enabled():
        return _installed
    try:
        from core import azure_table_core, azure_queue_core
    except ImportError:   # pragma: no cover
        return False
    azure_table_core.dispatch = _wrap("table", azure_table_core)
    if enabled("queue"):
        azure_queue_core.dispatch = _wrap("queue", azure_queue_core)
    _installed = True
    _log.info("Azure real backends: Table -> %s, Queue -> %s", base_url("table"), base_url("queue") if enabled("queue") else "(own core)")
    return True


def uninstall() -> None:
    """Test hook: restore the in-process cores."""
    global _installed
    from core import azure_table_core, azure_queue_core
    for mod in (azure_table_core, azure_queue_core):
        w = getattr(mod.dispatch, "__wrapped__", None)
        if w is not None:
            mod.dispatch = w
    _installed = False
