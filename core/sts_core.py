"""STS core — AWS Security Token Service, substrate-independent.

Speaks the AWS **Query protocol** (form-encoded `Action=...`, XML responses in
https://sts.amazonaws.com/doc/2011-06-15/) exactly like an unmodified AWS SDK /
aws-cli sends it. NO fastapi / boto3 / socket imports → loads under Pyodide, so the
same code serves the offline appliance and Nano.

State lives in public dict attrs of `StsStore` (so nano_persist captures it):
  sessions     {access_key_id: session record}   temporary credentials issued
  access_keys  {access_key_id: owner account}     long-term keys seen (GetAccessKeyInfo)

Operations: AssumeRole, AssumeRoleWithWebIdentity, AssumeRoleWithSAML,
GetCallerIdentity, GetSessionToken, GetFederationToken, GetAccessKeyInfo,
DecodeAuthorizationMessage.

Caller identity: a request signed with a temporary key issued by this store
resolves (GetCallerIdentity) to the assumed-role / federated-user / session ARN;
any other key resolves to the account root, as the simulator does elsewhere.
"""
from __future__ import annotations

import base64
import json
import random
import re
import string
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as _xml_escape

STS_NS = "https://sts.amazonaws.com/doc/2011-06-15/"
ACCOUNT_ID = "123456789012"
ROOT_USER_ID = "AIDACLOUDLEARNSIMULATOR"
DEFAULT_DURATION = 3600
_ROLE_ARN = re.compile(r"^arn:aws[a-z-]*:iam::(\d{12}):role/(.+)$")
_SESSION_NAME = re.compile(r"^[\w+=,.@-]{2,64}$")
_B32 = string.ascii_uppercase + "234567"
_ALNUM = string.ascii_letters + string.digits
_CRED_AKID = re.compile(r"Credential=([^/,\s]+)/")


@dataclass
class StsResponse:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class StsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, kind: str = "Sender") -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status, self.kind = code, message, status, kind


class StsStore:
    """In-memory by default; subclass to mirror to a persistent seam."""

    def __init__(self, account_id: str = ACCOUNT_ID) -> None:
        self.account_id = account_id
        self.sessions: dict = {}
        self.access_keys: dict = {}

    def persist(self) -> None:  # seam: overridden by a durable store
        return None


class InMemoryStsStore(StsStore):
    pass


# ── primitives ─────────────────────────────────────────────────────────────
def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _req_id() -> str:
    return str(uuid.uuid4())


def _el(tag: str, value) -> str:
    return f"<{tag}>{_xml_escape(str(value))}</{tag}>"


def _rand(alphabet: str, n: int) -> str:
    return "".join(random.choice(alphabet) for _ in range(n))


def _envelope(action: str, inner: str) -> StsResponse:
    body = (f'<?xml version="1.0" encoding="UTF-8"?><{action}Response xmlns="{STS_NS}">'
            f"<{action}Result>{inner}</{action}Result>"
            f"<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata></{action}Response>")
    return StsResponse(200, body, {"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400, kind: str = "Sender") -> StsResponse:
    body = (f'<?xml version="1.0" encoding="UTF-8"?><ErrorResponse xmlns="{STS_NS}">'
            f"<Error><Type>{kind}</Type><Code>{_xml_escape(code)}</Code>"
            f"<Message>{_xml_escape(message)}</Message></Error><RequestId>{_req_id()}</RequestId></ErrorResponse>")
    return StsResponse(status, body, {"x-amzn-requestid": _req_id()})


def _members(params: dict, prefix: str) -> list[str]:
    out = []
    for k in sorted(params, key=lambda x: (len(x), x)):
        if re.fullmatch(re.escape(prefix) + r"\.member\.\d+", k):
            out.append(str(params[k]))
    return out


def _tags(params: dict) -> list[dict]:
    tags = []
    for i in range(1, 51):
        k = params.get(f"Tags.member.{i}.Key")
        if k is None:
            break
        tags.append({"Key": str(k), "Value": str(params.get(f"Tags.member.{i}.Value", ""))})
    return tags


def _duration(params: dict, default: int, lo: int = 900, hi: int = 43200) -> int:
    raw = params.get("DurationSeconds")
    if raw in (None, ""):
        return default
    try:
        d = int(raw)
    except (TypeError, ValueError):
        raise StsError("ValidationError", f"Value '{raw}' at 'durationSeconds' failed to satisfy constraint: "
                       "Member must be a number")
    if d < lo or d > hi:
        raise StsError("ValidationError", f"1 validation error detected: Value '{d}' at 'durationSeconds' "
                       f"failed to satisfy constraint: Member must have value between {lo} and {hi}")
    return d


def _role_parts(role_arn: str) -> tuple[str, str, str]:
    m = _ROLE_ARN.match(role_arn or "")
    if not m:
        raise StsError("ValidationError", f"1 validation error detected: Value '{role_arn}' at 'roleArn' "
                       "failed to satisfy constraint: Member must satisfy regular expression pattern: "
                       "arn:aws[a-z-]*:iam::\\d{12}:role/.+")
    path_name = m.group(2)
    return m.group(1), path_name, path_name.rsplit("/", 1)[-1]


def _check_session_name(name: str) -> str:
    if not name:
        raise StsError("ValidationError", "1 validation error detected: Value '' at 'roleSessionName' "
                       "failed to satisfy constraint: Member must not be null")
    if not _SESSION_NAME.match(name):
        raise StsError("ValidationError", f"1 validation error detected: Value '{name}' at 'roleSessionName' "
                       "failed to satisfy constraint: Member must satisfy regular expression pattern: [\\w+=,.@-]*")
    return name


def _credentials(sess: dict) -> str:
    return ("<Credentials>" + _el("AccessKeyId", sess["access_key_id"]) + _el("SecretAccessKey", sess["secret_access_key"])
            + _el("SessionToken", sess["session_token"]) + _el("Expiration", sess["expiration"]) + "</Credentials>")


def _issue(store: StsStore, kind: str, principal_arn: str, user_id: str, duration: int,
           name: str, **extra) -> dict:
    now = _now_dt()
    akid = "ASIA" + _rand(_B32, 16)
    sess = {
        "access_key_id": akid,
        "secret_access_key": _rand(_ALNUM + "/+", 40),
        "session_token": base64.b64encode(("FQoG" + _rand(_ALNUM, 24) + uuid.uuid4().hex).encode()).decode(),
        "kind": kind,
        "name": name,
        "arn": principal_arn,
        "user_id": user_id,
        "account": store.account_id,
        "duration_seconds": duration,
        "issued_at": _iso(now),
        "expiration": _iso(now + timedelta(seconds=duration)),
        "status": "active",
    }
    sess.update(extra)
    store.sessions[akid] = sess
    store.persist()
    return sess


def _packed(policy: str | None, arns: list[str]) -> str:
    size = len(policy or "") + sum(len(a) for a in arns)
    return str(min(99, size * 100 // 2048))


def _check_policy(params: dict) -> str | None:
    pol = params.get("Policy")
    if not pol:
        return None
    try:
        json.loads(pol)
    except Exception:
        raise StsError("MalformedPolicyDocument", "Syntax errors in policy.")
    if len(pol) > 2048:
        raise StsError("PackedPolicyTooLarge", "The policy is too large; the packed size exceeds the limit.")
    return pol


def caller_access_key(headers: dict | None) -> str:
    """Access key id from a SigV4 Authorization header (never verified)."""
    if not headers:
        return ""
    auth = ""
    for k, v in headers.items():
        if str(k).lower() == "authorization":
            auth = str(v)
            break
    m = _CRED_AKID.search(auth)
    return m.group(1) if m else ""


# ── operations ─────────────────────────────────────────────────────────────
def _assume_role(store: StsStore, params: dict, headers=None) -> StsResponse:
    role_arn = str(params.get("RoleArn", ""))
    acct, path_name, role_name = _role_parts(role_arn)
    name = _check_session_name(str(params.get("RoleSessionName", "")))
    duration = _duration(params, DEFAULT_DURATION)
    policy = _check_policy(params)
    pols = _members(params, "PolicyArns")
    role_id = "AROA" + _rand(_B32, 17)
    sess = _issue(store, "assumed-role", f"arn:aws:sts::{acct}:assumed-role/{role_name}/{name}",
                  f"{role_id}:{name}", duration, name, role_arn=role_arn, role_name=role_name,
                  external_id=str(params.get("ExternalId", "")), tags=_tags(params),
                  source_identity=str(params.get("SourceIdentity", "")), operation="AssumeRole")
    inner = (_credentials(sess)
             + f"<AssumedRoleUser>{_el('AssumedRoleId', sess['user_id'])}{_el('Arn', sess['arn'])}</AssumedRoleUser>"
             + _el("PackedPolicySize", _packed(policy, pols)))
    if sess["source_identity"]:
        inner += _el("SourceIdentity", sess["source_identity"])
    return _envelope("AssumeRole", inner)


def _assume_role_web_identity(store: StsStore, params: dict, headers=None) -> StsResponse:
    role_arn = str(params.get("RoleArn", ""))
    acct, _, role_name = _role_parts(role_arn)
    name = _check_session_name(str(params.get("RoleSessionName", "")))
    token = str(params.get("WebIdentityToken", ""))
    if not token:
        raise StsError("ValidationError", "1 validation error detected: Value null at 'webIdentityToken' "
                       "failed to satisfy constraint: Member must not be null")
    parts = token.split(".")
    if len(parts) != 3:
        raise StsError("InvalidIdentityToken", "Couldn't retrieve verification key from your identity provider.")
    sub, aud, iss = "", "", ""
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        sub, aud, iss = str(claims.get("sub", "")), str(claims.get("aud", "")), str(claims.get("iss", ""))
    except Exception:
        pass
    duration = _duration(params, DEFAULT_DURATION)
    role_id = "AROA" + _rand(_B32, 17)
    sess = _issue(store, "assumed-role", f"arn:aws:sts::{acct}:assumed-role/{role_name}/{name}",
                  f"{role_id}:{name}", duration, name, role_arn=role_arn, role_name=role_name,
                  operation="AssumeRoleWithWebIdentity", subject=sub, audience=aud, provider=iss)
    inner = (_credentials(sess)
             + _el("SubjectFromWebIdentityToken", sub or "unknown")
             + f"<AssumedRoleUser>{_el('AssumedRoleId', sess['user_id'])}{_el('Arn', sess['arn'])}</AssumedRoleUser>"
             + _el("PackedPolicySize", _packed(params.get("Policy"), []))
             + _el("Provider", iss) + _el("Audience", aud))
    return _envelope("AssumeRoleWithWebIdentity", inner)


def _assume_role_saml(store: StsStore, params: dict, headers=None) -> StsResponse:
    role_arn = str(params.get("RoleArn", ""))
    acct, _, role_name = _role_parts(role_arn)
    principal = str(params.get("PrincipalArn", ""))
    if not principal.startswith("arn:"):
        raise StsError("ValidationError", f"1 validation error detected: Value '{principal}' at 'principalArn' "
                       "failed to satisfy constraint")
    assertion = str(params.get("SAMLAssertion", ""))
    if not assertion:
        raise StsError("ValidationError", "1 validation error detected: Value null at 'samlAssertion' "
                       "failed to satisfy constraint: Member must not be null")
    try:
        base64.b64decode(assertion, validate=True)
    except Exception:
        raise StsError("InvalidIdentityToken", "Invalid SAML assertion: not base64 encoded.")
    duration = _duration(params, DEFAULT_DURATION)
    name = "saml-session"
    role_id = "AROA" + _rand(_B32, 17)
    sess = _issue(store, "assumed-role", f"arn:aws:sts::{acct}:assumed-role/{role_name}/{name}",
                  f"{role_id}:{name}", duration, name, role_arn=role_arn, role_name=role_name,
                  operation="AssumeRoleWithSAML", provider=principal)
    inner = (_credentials(sess)
             + f"<AssumedRoleUser>{_el('AssumedRoleId', sess['user_id'])}{_el('Arn', sess['arn'])}</AssumedRoleUser>"
             + _el("PackedPolicySize", "0") + _el("Subject", "saml-user") + _el("SubjectType", "persistent")
             + _el("Issuer", principal) + _el("Audience", "https://signin.aws.amazon.com/saml")
             + _el("NameQualifier", base64.b64encode(principal.encode()).decode()))
    return _envelope("AssumeRoleWithSAML", inner)


def resolve_caller(store: StsStore, headers: dict | None) -> dict:
    akid = caller_access_key(headers)
    sess = store.sessions.get(akid)
    if sess and sess.get("status") == "active":
        return {"Arn": sess["arn"], "UserId": sess["user_id"], "Account": sess["account"]}
    return {"Arn": f"arn:aws:iam::{store.account_id}:root", "UserId": ROOT_USER_ID, "Account": store.account_id}


def _get_caller_identity(store: StsStore, params: dict, headers=None) -> StsResponse:
    c = resolve_caller(store, headers)
    return _envelope("GetCallerIdentity", _el("UserId", c["UserId"]) + _el("Account", c["Account"]) + _el("Arn", c["Arn"]))


def _get_session_token(store: StsStore, params: dict, headers=None) -> StsResponse:
    duration = _duration(params, 43200, 900, 129600)
    if params.get("SerialNumber") and not params.get("TokenCode"):
        raise StsError("MissingParameter", "TokenCode is required when SerialNumber is supplied.")
    sess = _issue(store, "session", f"arn:aws:iam::{store.account_id}:root", ROOT_USER_ID, duration,
                  "session-token", operation="GetSessionToken", mfa=bool(params.get("SerialNumber")))
    return _envelope("GetSessionToken", _credentials(sess))


def _get_federation_token(store: StsStore, params: dict, headers=None) -> StsResponse:
    name = str(params.get("Name", ""))
    if not re.fullmatch(r"[\w+=,.@-]{2,32}", name):
        raise StsError("ValidationError", f"1 validation error detected: Value '{name}' at 'name' failed to "
                       "satisfy constraint: Member must satisfy regular expression pattern: [\\w+=,.@-]*")
    duration = _duration(params, 43200, 900, 129600)
    policy = _check_policy(params)
    user_id = f"{store.account_id}:{name}"
    sess = _issue(store, "federated-user", f"arn:aws:sts::{store.account_id}:federated-user/{name}",
                  user_id, duration, name, operation="GetFederationToken", tags=_tags(params))
    inner = (_credentials(sess)
             + f"<FederatedUser>{_el('FederatedUserId', user_id)}{_el('Arn', sess['arn'])}</FederatedUser>"
             + _el("PackedPolicySize", _packed(policy, _members(params, "PolicyArns"))))
    return _envelope("GetFederationToken", inner)


def _get_access_key_info(store: StsStore, params: dict, headers=None) -> StsResponse:
    akid = str(params.get("AccessKeyId", ""))
    if len(akid) < 16 or len(akid) > 128 or not re.fullmatch(r"\w+", akid):
        raise StsError("ValidationError", f"1 validation error detected: Value '{akid}' at 'accessKeyId' "
                       "failed to satisfy constraint: Member must have length greater than or equal to 16")
    sess = store.sessions.get(akid)
    return _envelope("GetAccessKeyInfo", _el("Account", sess["account"] if sess else store.account_id))


def _decode_authorization_message(store: StsStore, params: dict, headers=None) -> StsResponse:
    msg = str(params.get("EncodedMessage", ""))
    if not msg:
        raise StsError("ValidationError", "1 validation error detected: Value null at 'encodedMessage' "
                       "failed to satisfy constraint: Member must not be null")
    try:
        decoded = base64.b64decode(msg, validate=True).decode()
        json.loads(decoded)
    except Exception:
        raise StsError("InvalidAuthorizationMessageException", "The message is invalid.")
    return _envelope("DecodeAuthorizationMessage", _el("DecodedMessage", decoded))


_OPS = {
    "AssumeRole": _assume_role, "AssumeRoleWithWebIdentity": _assume_role_web_identity,
    "AssumeRoleWithSAML": _assume_role_saml, "GetCallerIdentity": _get_caller_identity,
    "GetSessionToken": _get_session_token, "GetFederationToken": _get_federation_token,
    "GetAccessKeyInfo": _get_access_key_info, "DecodeAuthorizationMessage": _decode_authorization_message,
}
OPERATIONS = sorted(_OPS)


def dispatch(store: StsStore, params: dict | None = None, headers: dict | None = None) -> StsResponse:
    """Native STS Query-protocol routing point. `params` is the parsed form body
    ({"Action": "AssumeRole", ...}); `headers` is used only to identify the caller."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "Missing Action parameter")
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"Could not find operation {action} for version 2011-06-15")
    try:
        return op(store, params, headers)
    except StsError as e:
        return _error(e.code, e.message, e.status, e.kind)


# ── console / resource helpers (sessions are the console's resource) ───────
def _status(sess: dict) -> str:
    if sess.get("status") != "active":
        return sess["status"]
    return "expired" if sess["expiration"] <= _iso(_now_dt()) else "active"


def session_row(sess: dict) -> dict:
    return {
        "id": sess["access_key_id"], "name": sess["access_key_id"],
        "access_key_id": sess["access_key_id"],
        "session_name": sess["name"], "type": sess["kind"], "operation": sess.get("operation", ""),
        "role_name": sess.get("role_name") or sess["kind"],
        "arn": sess["arn"], "user_id": sess["user_id"], "account_id": sess["account"],
        "duration_seconds": sess["duration_seconds"], "issued_at": sess["issued_at"],
        "expiration": sess["expiration"], "status": _status(sess),
        "external_id": sess.get("external_id") or "none",
        "source_identity": sess.get("source_identity") or "none",
        "tags": len(sess.get("tags") or []),
    }


def list_sessions(store: StsStore, origin: str | None = "console") -> list[dict]:
    """Console grid rows, newest first. By default only sessions issued from the
    console ("Assume role"); credentials minted by SDK/CLI calls are not listed (they
    would bury the grid) but stay resolvable by GetCallerIdentity / GetAccessKeyInfo
    and addressable by id. Pass origin=None for everything."""
    rows = [s for s in store.sessions.values() if origin is None or s.get("origin", "api") == origin]
    return [session_row(s) for s in sorted(rows, key=lambda s: s["issued_at"], reverse=True)]


def console_create(store: StsStore, body: dict) -> dict:
    """Console 'Assume role' — AssumeRole with form defaults. Returns the session row
    (the secret + token are shown once in the response, like the real API)."""
    body = body or {}
    acct = store.account_id
    role_name = str(body.get("role_name") or "my-role")
    role_arn = str(body.get("role_arn") or f"arn:aws:iam::{acct}:role/{role_name}")
    params = {"Action": "AssumeRole", "RoleArn": role_arn,
              "RoleSessionName": str(body.get("session_name") or body.get("name") or "console-session"),
              "DurationSeconds": str(body.get("duration_seconds") or DEFAULT_DURATION)}
    if body.get("external_id"):
        params["ExternalId"] = str(body["external_id"])
    r = dispatch(store, params)
    if r.status != 200:
        m = re.search(r"<Message>(.*?)</Message>", r.body, re.S)
        c = re.search(r"<Code>(.*?)</Code>", r.body, re.S)
        return {"ok": False, "code": c.group(1) if c else "Error", "error": m.group(1) if m else "failed"}
    akid = re.search(r"<AccessKeyId>(.*?)</AccessKeyId>", r.body).group(1)
    store.sessions[akid]["origin"] = "console"
    store.persist()
    return {"ok": True, **session_row(store.sessions[akid])}


def console_delete(store: StsStore, ident: str) -> dict:
    """Revoke a session (simulator-side; real STS sessions expire, they aren't deleted)."""
    if ident not in store.sessions:
        return {"ok": False, "code": "NotFound", "name": ident}
    del store.sessions[ident]
    store.persist()
    return {"ok": True, "name": ident}
