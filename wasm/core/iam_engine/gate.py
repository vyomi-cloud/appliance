"""The one decision point per request: map -> evaluate -> mode logic -> allow (None) or a denial response spec.

Pure Python (no fastapi / socket): the host (core/middleware.py on Mesh, the service worker on Nano) turns the returned spec
{status, headers, body, content_type} into a real response. Contract: docs/architecture/v4.0/IAM-ENGINE-CONTRACT.md.

  off      -> skip entirely (no mapping, no evaluation, no record)
  audit    -> evaluate, record "would_deny", NEVER block, NEVER raise
  enforce  -> block on deny; FAIL CLOSED if mapping/engine errors; unmapped requests are denied unless settings.allowUnmapped
"""
from __future__ import annotations

import importlib
import json


def _xe(text):
    """XML text escape (& < >). Local on purpose: xml.sax.saxutils imports urllib -> socket, which the Nano (Pyodide) package must not."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


from core.iam_engine import audit as _audit
from core.iam_engine import modes as _modes
from core.iam_engine import routing as _routing
from core.iam_engine.types import request as _request

# Internal / console traffic is not cloud API traffic: never gated.
INTERNAL_PREFIXES = ("/api/", "/mesh/", "/healthz", "/static/", "/assets/", "/ws/", "/favicon.ico", "/console/", "/_")
# Never gated, even when signed: the IAM API itself (so enforcement can always be turned off from the UI/CLI).
ALWAYS_INTERNAL = ("/api/iam/", "/_wire/api/iam/", "/nano/_wire/api/iam/")


def _signed_aws(hr: dict) -> bool:
    h = {str(k).lower(): str(v) for k, v in ((hr or {}).get("headers") or {}).items()}
    auth = h.get("authorization", "")
    q = str((hr or {}).get("query") or "")
    return auth.startswith(("AWS4-", "AWS ")) or "x-amz-target" in h or "X-Amz-Credential" in q or "AWSAccessKeyId" in q


def is_internal(http_request: dict) -> bool:
    """Console / health / static traffic bypasses the gate. A SigV4/SigV2-signed request is an AWS API call, never console traffic:
    S3 buckets named `assets`, `static`, `api`, `console-x` ... must stay gated (path-style requests start with the bucket name)."""
    p = str((http_request or {}).get("path") or "")
    if p.startswith(ALWAYS_INTERNAL):
        return True
    if _signed_aws(http_request):
        return False
    return _routing.strip_wire(p).startswith(INTERNAL_PREFIXES)      # `/_wire/<native path>` is the native request (it is gated); other `/_x` paths are internal


def engines_available(cloud, engines=None, maps=None) -> bool:
    try:
        _engine(cloud, engines)
        _map(cloud, maps)
        return True
    except Exception:
        return False


def _engine(cloud, engines):
    if engines and cloud in engines:
        return engines[cloud]
    return importlib.import_module(f"core.iam_engine.{cloud}_eval")   # lazy: works once the engine branch merges


def _map(cloud, maps):
    if maps and cloud in maps:
        return maps[cloud]
    return importlib.import_module(f"core.iam_engine.map_{cloud}")


def _full_path(hr):
    q = hr.get("query") or ""
    if isinstance(q, dict):
        from urllib.parse import urlencode
        q = urlencode(q, doseq=True)
    return _routing.strip_wire(hr.get("path") or "/") + (("?" + q) if q else "")


def _bare_host(hr):
    h = str(hr.get("host") or (hr.get("headers") or {}).get("host") or "").strip().lower()
    return h.rsplit(":", 1)[0] if h and not h.endswith("]") and ":" in h else (h or None)


def _call_map(m, args, extra):
    """The contract is required(method, url, body); the GCP/Azure maps also take host (and Azure headers). A map that predates them
    (a stand-in, an older vendored copy) is called without."""
    try:
        return m.required(*args, **{k: v for k, v in extra.items() if v})
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return m.required(*args)


def required_permissions(cloud, http_request, maps=None) -> list:
    m = _map(cloud, maps)
    if cloud == "aws":
        out = m.required(http_request)
    elif cloud == "gcp":
        out = _call_map(m, (http_request.get("method", "GET"), _full_path(http_request), http_request.get("body")),
                        {"host": _bare_host(http_request)})
    else:   # the query string selects the data-plane operation (?comp=list, ?restype=container ...); the host names the data-plane service
        out = _call_map(m, (http_request.get("method", "GET"), _full_path(http_request), http_request.get("body")),
                        {"host": _bare_host(http_request), "headers": http_request.get("headers")})
    return list(out or [])


# --------------------------------------------------------------------------- denial shapes

def _principal_name(cloud, principal):
    p = principal or {}
    if cloud == "aws":
        return p.get("arn") or ("anonymous" if p.get("type") == "anonymous" else "unknown")
    if cloud == "gcp":
        return p.get("member") or "unknown"
    return p.get("object_id") or "unknown"


def _aws_protocol(hr, service):
    h = {str(k).lower(): v for k, v in (hr.get("headers") or {}).items()}
    ct = str(h.get("content-type") or "")
    if "x-amz-target" in h or "x-amz-json" in ct or "cbor" in ct:
        ver = "1.0"
        if "x-amz-json-1.1" in ct:
            ver = "1.1"
        return "json", ver
    if service == "s3":
        return "s3", ""
    if service == "ec2":
        return "ec2", ""
    return "query", ""


def _aws_message(principal, action, resource, decision):
    if (principal or {}).get("type") == "anonymous":
        return "Access Denied"                       # what S3 tells an unsigned caller (no principal to name)
    arn = _principal_name("aws", principal)
    if (decision or {}).get("reason") == "explicit_deny":
        why = f"with an explicit deny in {_deny_source(decision)} policy"
    else:
        why = f"because no identity-based policy allows the {action} action"
    return f"User: {arn} is not authorized to perform: {action} on resource: {resource} {why}"


def _deny_source(decision):
    for m in (decision or {}).get("matched") or []:
        if isinstance(m, dict) and m.get("effect") == "Deny":
            return {"scp": "a service control", "rcp": "a resource control", "boundary": "a permissions boundary",
                    "session": "a session", "resource": "a resource-based"}.get(m.get("source"), "an identity-based")
    return "an identity-based"


def denial_spec(cloud, hr, principal, action, resource, decision=None, service=None, message=None) -> dict:
    """The cloud's exact 403 shape."""
    if cloud == "gcp":
        msg = message or f"Permission '{action}' denied on resource '{resource}' (or it may not exist)."
        body = {"error": {"code": 403, "message": msg,
                          "errors": [{"message": msg, "domain": "global", "reason": "forbidden"}],
                          "status": "PERMISSION_DENIED",
                          "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "IAM_PERMISSION_DENIED",
                                       "domain": "iam.googleapis.com", "metadata": {"permission": action}}]}}
        return {"status": 403, "headers": {}, "body": json.dumps(body), "content_type": "application/json; charset=UTF-8"}
    if cloud == "azure" and (decision or {}).get("storageError"):     # SAS / Shared Key: the storage service's own error, not ARM's AuthorizationFailed
        se = decision["storageError"]
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n<Error><Code>%s</Code><Message>%s\nRequestId:00000000-0000-0000-0000-000000000000</Message></Error>'
               % (_xe(se["code"]), _xe(se["message"])))
        return {"status": int(se.get("status") or 403), "headers": {"x-ms-error-code": str(se["code"])}, "body": xml, "content_type": "application/xml"}
    if cloud == "azure":
        who = _principal_name("azure", principal)
        msg = message or (f"The client '{who}' with object id '{who}' does not have authorization to perform action "
                          f"'{action}' over scope '{resource}' or the scope is invalid. If access was recently granted, "
                          f"please refresh your credentials.")
        body = {"error": {"code": "AuthorizationFailed", "message": msg}}
        return {"status": 403, "headers": {"x-ms-failure-cause": "gateway"}, "body": json.dumps(body),
                "content_type": "application/json; charset=utf-8"}
    # AWS
    msg = message or _aws_message(principal, action, resource, decision)
    proto, ver = _aws_protocol(hr, service)
    if proto == "json":
        body = {"__type": "AccessDeniedException", "message": msg}
        return {"status": 403, "headers": {"x-amzn-ErrorType": "AccessDeniedException"}, "body": json.dumps(body),
                "content_type": f"application/x-amz-json-{ver}"}
    if proto == "s3":
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>AccessDenied</Code>'
               f"<Message>{_xe(msg)}</Message><RequestId>0000000000000000</RequestId><HostId></HostId></Error>")
        return {"status": 403, "headers": {}, "body": xml, "content_type": "application/xml"}
    if proto == "ec2":
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<Response><Errors><Error><Code>UnauthorizedOperation</Code>'
               f"<Message>You are not authorized to perform this operation. {_xe(msg)}</Message></Error></Errors>"
               "<RequestID>00000000-0000-0000-0000-000000000000</RequestID></Response>")
        return {"status": 403, "headers": {}, "body": xml, "content_type": "text/xml;charset=UTF-8"}
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<ErrorResponse xmlns="https://iam.amazonaws.com/doc/2010-05-08/"><Error>'
           f"<Type>Sender</Type><Code>AccessDenied</Code><Message>{_xe(msg)}</Message></Error>"
           "<RequestId>00000000-0000-0000-0000-000000000000</RequestId></ErrorResponse>")
    return {"status": 403, "headers": {}, "body": xml, "content_type": "text/xml"}


# --------------------------------------------------------------------------- the gate

def check(cloud, http_request, state, settings, engines=None, maps=None, audit=None, bypass=None):
    """Return None (allow / off / audit / internal) or a denial response spec. Never raises."""
    try:
        return _check(cloud, http_request or {}, state, settings, engines, maps, audit if audit is not None else _audit.default_log, bypass)
    except Exception as exc:    # last-resort guard: only reachable on a bug in this module itself
        try:
            if _modes.resolve_mode(cloud, settings) == "enforce":
                return denial_spec(cloud, http_request or {}, (http_request or {}).get("principal"), "unknown", "*",
                                   message=f"IAM enforcement error: {exc}")
        except Exception:
            pass
        return None


def _check(cloud, hr, state, settings, engines, maps, log, bypass):
    if not _modes.any_active(settings):
        return None
    if (bypass(hr) if callable(bypass) else is_internal(hr)):
        return None
    principal = hr.get("principal") or {}
    who = _principal_name(cloud, principal)
    allow_unmapped = bool((settings or {}).get("allowUnmapped"))
    # Coarse mode for a request we cannot map (space/global level).
    base_mode = _modes.resolve_mode(cloud, settings)

    try:
        perms = required_permissions(cloud, hr, maps)
    except Exception as exc:
        if base_mode == "off":
            return None
        log.record(cloud, who, "?", "*", base_mode, "error", f"mapping error: {exc}")
        if base_mode == "enforce":
            return denial_spec(cloud, hr, principal, "unknown", "*", message=f"IAM enforcement could not map the request: {exc}")
        return None

    if not perms and cloud == "gcp" and str(hr.get("path") or "").split("?")[0].endswith(":testIamPermissions"):
        return None        # needs no permission by design (any caller may ask which permissions they hold)

    if not perms:
        if base_mode == "off":
            return None
        log.record(cloud, who, "?", "*", base_mode, "unmapped", "no permission mapping for this request",
                   method=hr.get("method"), path=hr.get("path"))
        if base_mode == "enforce" and not allow_unmapped:
            return denial_spec(cloud, hr, principal, "unknown", "*", message=(
                f"Vyomi IAM: no permission mapping for {hr.get('method', '')} {hr.get('path', '')}; denied because enforcement is on "
                f"and 'allowUnmapped' is false."))
        return None

    engine, engine_err = None, None
    try:
        engine = _engine(cloud, engines)
    except Exception as exc:
        engine_err = exc

    deny = None
    for p in perms:
        action, resource = p.get("action", "?"), p.get("resource") or "*"
        if cloud == "azure" and not p.get("service") and "/" in action:
            p = dict(p, service=action.split("/", 1)[0])      # the Azure map has no service field: the provider namespace is the service key
        mode = _modes.resolve_mode(cloud, settings, p.get("service"), resource)
        if mode == "off":
            continue
        try:
            if engine is None:
                raise RuntimeError(f"engine unavailable: {engine_err}")
            ctx = dict(hr.get("context") or {})
            if p.get("hint"):
                ctx["hint"] = p["hint"]             # Azure storage: list vs read, update vs process (SAS permission letters)
            dec = engine.evaluate(_request(cloud, principal, action, resource, ctx, data=bool(p.get("data"))), state)
            allowed = bool(dec.get("allowed"))
            reason, matched = dec.get("reason", ""), dec.get("matched")
        except Exception as exc:
            log.record(cloud, who, action, resource, mode, "error", f"engine error: {exc}")
            if mode == "enforce" and deny is None:
                deny = (p, None, f"IAM enforcement engine error ({exc}); request denied (fail closed).")
            continue
        if allowed:
            log.record(cloud, who, action, resource, mode, "allow", reason, matched)
        elif mode == "audit":
            log.record(cloud, who, action, resource, mode, "would_deny", reason, matched)
        else:
            log.record(cloud, who, action, resource, mode, "deny", reason, matched)
            if deny is None:
                deny = (p, dec, None)
    if deny is None:
        return None
    p, dec, msg = deny
    return denial_spec(cloud, hr, principal, p.get("action", "?"), p.get("resource") or "*", dec, p.get("service"), msg)
