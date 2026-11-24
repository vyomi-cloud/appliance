"""Which cloud's IAM gate (if any) owns a request that reaches the simulator on a shared path space.

Pure Python (Pyodide-safe). The simulator serves all three clouds on one host, so a request's cloud is not always its path root:
Azure data planes without a `/subscriptions` or `/azure-data` prefix (`/openai/...`, `/azure-openai/...`, `/azure-sql/...`) and the
Cloud Storage XML API (path-style `/<bucket>/<object>`) look like S3 to the router. Used by core/middleware.py (Mesh) and
core/iam_engine/nano_bridge.py (Nano); wasm/nano-iam-hook.js mirrors `classify` (a test keeps the two in step).

classify(method, path, headers, query, host) -> {"cloud": "azure"|"gcp"|None, "exempt": bool, "reason": str, "host": str|None}
  exempt=True   Entra ID (Microsoft Graph `/v1.0|/beta`, `/oauth2`, OIDC discovery): the identity plane is OUT of the RBAC/IAM model
                (Azure RBAC authorizes Azure resources; Entra directory permissions are Graph app roles/scopes). Never gated, never
                audited. Vyomi extension endpoints with no vendor permission (`/openai/vyomi/...`) are exempt too.
  cloud         the gate that must judge the request (None = leave it to the default routing, i.e. AWS for the wire).
  host          a host to hand the maps (the GCP XML API is recognised by `storage.googleapis.com`; on the simulator host the
                request carries no such Host header, so the classifier supplies it).
"""
from __future__ import annotations

import re

WIRE = "/_wire"

_ENTRA = re.compile(
    r"^/(?:v1\.0|beta)(?:/|$)"                                                   # Microsoft Graph
    r"|/oauth2(?:/v2\.0)?/(?:token|authorize|devicecode|logout)$"                # token endpoints, with or without a tenant segment
    r"|^/[^/]+/(?:v2\.0/)?\.well-known/openid-configuration$|^/[^/]+/discovery/(?:v2\.0/)?keys$|^/discovery/(?:v2\.0/)?keys$"
    r"|^/common/userrealm/", re.I)
_COGNITO_POOL = re.compile(r"^/[a-z0-9-]+_[A-Za-z0-9]+/")                         # /{poolId}/oauth2/*: the AWS Cognito hosted UI, not Entra
_AZURE_DP = re.compile(r"^/(?:openai|azure-openai|azure-sql|contentsafety)(?:/|$)", re.I)
_VYOMI_EXT = re.compile(r"^/openai/vyomi/", re.I)
_GCS_HOST = re.compile(r"(?:^|\.)storage\.googleapis\.com$", re.I)
_GOOG_KEY = re.compile(r"Credential=GOOG", re.I)


def strip_wire(path):
    """`/_wire/x` and `/nano/_wire/x` -> `/x`; `/_wire/arm/subscriptions/...` (the ARM alias of the wire) -> `/subscriptions/...`."""
    p = str(path or "/")
    for pre in ("/nano" + WIRE, WIRE):
        if p == pre or p.startswith(pre + "/"):
            p = p[len(pre):] or "/"
            break
    if re.match(r"^/arm(?:/(?:subscriptions|providers|tenants)(?:/|$)|$)", p, re.I):
        p = p[len("/arm"):] or "/"
    return p


def _h(headers, name):
    for k, v in (headers or {}).items():
        if str(k).lower() == name:
            return str(v)
    return ""


def _hostname(host):
    h = str(host or "").strip().lower()
    return h.rsplit(":", 1)[0] if h and not h.endswith("]") and ":" in h else h


def _has_xgoog(headers):
    return any(str(k).lower().startswith("x-goog-") for k in (headers or {}))


def _signed_aws(headers, query=""):
    auth = _h(headers, "authorization")
    q = query if isinstance(query, str) else "&".join("%s=%s" % kv for kv in (query or {}).items())
    return auth.startswith(("AWS4-", "AWS ")) or "X-Amz-Credential" in q or "AWSAccessKeyId" in q or bool(_h(headers, "x-amz-target"))


def gcp_xml_request(path, headers, query="", host=""):
    """Is this a Cloud Storage XML API call (rather than S3)? Evidence, strongest first: a storage.googleapis.com Host, a `GOOG1` /
    `GOOG4-HMAC` Authorization scheme or an S3-style signature whose access key is a Google HMAC key (`GOOG...`), an `x-goog-*`
    header. A bare `Authorization: Bearer` is NOT evidence (AgentCore MCP/A2A calls on the AWS wire carry one)."""
    if _GCS_HOST.search(_hostname(host or _h(headers, "host"))):
        return True
    auth = _h(headers, "authorization")
    if re.match(r"^GOOG(?:1|4)", auth, re.I) or (auth.startswith("AWS4-") and _GOOG_KEY.search(auth)) \
            or (auth.startswith("AWS ") and auth[4:].startswith("GOOG")):
        return True
    q = query if isinstance(query, str) else "&".join("%s=%s" % kv for kv in (query or {}).items())
    if "X-Goog-Algorithm" in q or "GoogleAccessId" in q or re.search(r"X-Amz-Credential=GOOG", q):
        return True
    return _has_xgoog(headers) and not auth.startswith("AWS4-")


def classify(method, path, headers=None, query="", host=""):
    p0 = strip_wire(path).split("?", 1)[0]
    out = {"cloud": None, "exempt": False, "reason": "", "host": None}
    if p0 not in ("", "/") and gcp_xml_request(p0, headers, query, host):
        out.update(cloud="gcp", reason="gcs-xml", host="storage.googleapis.com")
        return out
    if _signed_aws(headers, query):          # an S3 bucket may be called `openai` / `oauth2`: a signed AWS request is never Azure/Entra
        return out
    if _VYOMI_EXT.match(p0):
        out.update(exempt=True, reason="vyomi-extension")
        return out
    if _ENTRA.search(p0) and not _COGNITO_POOL.match(p0) and not p0.startswith("/identities/"):
        out.update(exempt=True, reason="entra")
        return out
    if _AZURE_DP.match(p0):
        out.update(cloud="azure", reason="azure-data-plane")
        return out
    if p0.startswith(("/subscriptions", "/providers", "/tenants")) or re.match(r"^/arm/(?:subscriptions|providers|tenants)(?:/|$)", p0, re.I):
        out.update(cloud="azure", reason="arm")
        return out
    return out
