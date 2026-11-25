"""AWS STS trust evaluation + federation (pure Python, Pyodide-safe: stdlib only; shared by Mesh and Nano through core/aws_wire_router.py).

  assume_role(store, params, caller)                    sts:AssumeRole            trust policy of the role evaluated against the caller
  assume_role_with_web_identity(store, params)          sts:AssumeRoleWithWebIdentity   OIDC provider from the IAM store, aud/sub/amr conditions
  assume_role_with_saml(store, params)                  sts:AssumeRoleWithSAML    SAML provider from the IAM store, saml:* conditions
  roles_anywhere_session(store, profile_arn, trust_anchor_arn, role_arn, cert_pem, duration)    rolesanywhere CreateSession

REAL: the role's AssumeRolePolicyDocument is evaluated with the same operator/variable engine as every other policy (aws_eval): Effect,
Principal (AWS account root / user / role / session, Federated, Service, NotPrincipal), Action, Condition (sts:ExternalId,
sts:RoleSessionName, sts:SourceIdentity, aws:PrincipalArn / PrincipalTag / PrincipalOrgID, aws:MultiFactorAuthPresent, aws:RequestTag /
TagKeys, <provider>:aud|sub|amr|<claim>, saml:aud|iss|sub|sub_type|doc|namequalifier). An explicit Deny beats an Allow; same-account
`:root` / `*` principals additionally require an identity-policy allow of sts:AssumeRole for an IAM caller (as in AWS). The provider must
exist in the IAM store, the token's audience must be in its ClientIDList, an expired token / assertion is rejected, DurationSeconds is
bounded by the role's MaxSessionDuration (900 s minimum). The issued session is recorded (store.extras["sts_sessions"]) so a later request
signed with the ASIA key evaluates as the assumed-role principal (session policy, session tags and the role's own policies).

APPROXIMATED (said plainly): the OIDC token signature is NOT verified (the simulator has no network egress to fetch the issuer's JWKS and
does not model thumbprint pinning); SAML assertion signatures are not verified; Roles Anywhere extracts the certificate subject / issuer CN
with a small DER reader and does not validate the chain, revocation or the X509 SigV4 request signature."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from xml.etree import ElementTree as ET

from . import aws_eval as E

SAML_AUDIENCES = ("https://signin.aws.amazon.com/saml", "https://signin.amazonaws.cn/saml", "https://signin.amazonaws-us-gov.com/saml")
MIN_DURATION = 900
_ANY = "*"


class StsError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ------------------------------------------------------------------ helpers
def _now():
    return time.time()


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _rand(n):
    return uuid.uuid4().hex.upper()[:n]


def _members(params, prefix):
    """Flat Query list `Prefix.member.N` -> [values] (also accepts a real list)."""
    v = params.get(prefix)
    if isinstance(v, list):
        return v
    out = []
    for k in sorted(params, key=lambda s: (len(s), s)):
        if re.fullmatch(re.escape(prefix) + r"\.member\.\d+(\.arn)?", k):
            out.append(params[k])
    return out


def _tags(params):
    """Tags.member.N.Key/Value -> {key: value}."""
    out = {}
    for k, v in params.items():
        m = re.fullmatch(r"Tags\.member\.(\d+)\.Key", k)
        if m:
            out[v] = params.get(f"Tags.member.{m.group(1)}.Value", "")
    return out


def _acct(store):
    return getattr(store, "account_id", "") or "000000000000"


def _role_by_arn(store, role_arn):
    m = re.fullmatch(r"arn:[^:]*:iam::(\d{12}):role/(?:.*/)?([^/]+)", str(role_arn or ""))
    if not m:
        return None
    r = (store.roles or {}).get(m.group(2))
    return r if r and r.get("arn") == role_arn else None


def _duration(params, role, default=3600):
    raw = params.get("DurationSeconds")
    if raw in (None, ""):
        return min(default, int(role.get("max_session_duration") or 3600))
    try:
        d = int(raw)
    except (TypeError, ValueError):
        raise StsError("ValidationError", f"1 validation error detected: Value '{raw}' at 'durationSeconds' failed to satisfy constraint: "
                                          "Member must have value less than or equal to 43200")
    mx = int(role.get("max_session_duration") or 3600)
    if d < MIN_DURATION:
        raise StsError("ValidationError", f"1 validation error detected: Value '{d}' at 'durationSeconds' failed to satisfy constraint: "
                                          f"Member must have value greater than or equal to {MIN_DURATION}")
    if d > mx:
        raise StsError("ValidationError", f"The requested DurationSeconds exceeds the MaxSessionDuration set for this role.")
    return d


def _session_policy(params):
    raw = params.get("Policy")
    if not raw:
        return None
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(doc, dict) or "Statement" not in doc:
            raise ValueError
        return doc
    except ValueError:
        raise StsError("MalformedPolicyDocument", "Syntax errors in policy.")


# ------------------------------------------------------------------ trust evaluation
def evaluate_trust(trust_doc, action, principal, raw_context):
    """-> {"allowed": bool, "reason": "allow"|"explicit_deny"|"implicit_deny", "matched": [..], "kinds": {kind...}}.
    `principal` is the engine principal dict ({"arn","type","account"} | {"type":"federated","arn": provider_arn} |
    {"type":"service","service": "x.amazonaws.com"})."""
    ctx = E._Ctx(raw_context)
    matched, kinds, allowed, denied = [], set(), False, False
    for i, st in enumerate(E._statements(trust_doc or {})):
        eff = str(st.get("Effect", "")).lower()
        if eff not in ("allow", "deny"):
            continue
        acts = E._as_list(st.get("Action"))
        nacts = E._as_list(st.get("NotAction"))
        if acts and not any(E._wc(a, True).match(action) for a in acts):
            continue
        if nacts and any(E._wc(a, True).match(action) for a in nacts):
            continue
        if not acts and not nacts:
            continue
        kind = E._principal_match(st, principal)
        if kind is None:
            continue
        if not E._eval_condition_block(st.get("Condition"), ctx):
            continue
        matched.append({"source": "trust", "id": st.get("Sid") or f"statement{i}", "effect": "Allow" if eff == "allow" else "Deny",
                        "statement": st})
        if eff == "deny":
            denied = True
        else:
            allowed = True
            kinds.add(kind)
    if denied:
        return {"allowed": False, "reason": "explicit_deny", "matched": matched, "kinds": kinds}
    return {"allowed": allowed, "reason": "allow" if allowed else "implicit_deny", "matched": matched, "kinds": kinds}


def _identity_allows(store, caller, action, resource):
    try:
        from core import iam_state_adapters as ad
        state = ad.aws_state(store)
        return bool(E.evaluate({"cloud": "aws", "principal": dict(caller), "action": action, "resource": resource, "context": {}}, state).get("allowed"))
    except Exception:
        return False


def _caller_context(caller):
    raw = {}
    arn = caller.get("arn") or ""
    if arn:
        raw["aws:PrincipalArn"] = E._role_arn_of(arn) or arn
    if caller.get("account"):
        raw["aws:PrincipalAccount"] = caller["account"]
    for k, v in (caller.get("tags") or {}).items():
        raw[f"aws:PrincipalTag/{k}"] = v
    if caller.get("org_id"):
        raw["aws:PrincipalOrgID"] = caller["org_id"]
    return raw


def _access_denied(caller_arn, action, resource):
    return StsError("AccessDenied", f"User: {caller_arn} is not authorized to perform: {action} on resource: {resource}", 403)


# ------------------------------------------------------------------ sessions
def _record_session(store, role, session_name, duration, session_policy, tags, extra=None):
    akid, now = "ASIA" + _rand(16), _now()
    sess = {"role_name": role["role_name"], "session_name": session_name, "issued": now, "expires": now + duration,
            "session_policy": session_policy, "tags": dict(tags or {}), "assumed_role_id": role.get("role_id", "AROA" + _rand(17)) + ":" + session_name}
    sess.update(extra or {})
    ex = store.extras
    sessions = ex.setdefault("sts_sessions", {})
    for k in [k for k, v in sessions.items() if v.get("expires", 0) < now - 3600]:      # purge long-expired sessions
        del sessions[k]
    sessions[akid] = sess
    try:
        store.persist()
    except Exception:
        pass
    return akid, sess


def _credentials(akid, sess):
    return {"AccessKeyId": akid, "SecretAccessKey": base64.b64encode(hashlib.sha256((akid + "secret").encode()).digest()).decode()[:40],
            "SessionToken": "IQoJb3JpZ2luX2Vj" + base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode().rstrip("="),
            "Expiration": _iso(sess["expires"])}


def _result(store, role, akid, sess, **extra):
    acct = _acct(store)
    r = {"Credentials": _credentials(akid, sess),
         "AssumedRoleUser": {"AssumedRoleId": sess["assumed_role_id"],
                             "Arn": f"arn:aws:sts::{acct}:assumed-role/{role['role_name']}/{sess['session_name']}"},
         "PackedPolicySize": 6 if sess.get("session_policy") else 0}
    r.update(extra)
    return r


def session_is_live(sess, now=None):
    return float(sess.get("expires") or 0) > (now or _now())


# ------------------------------------------------------------------ AssumeRole
def assume_role(store, params, caller):
    role_arn = str(params.get("RoleArn") or "")
    sname = str(params.get("RoleSessionName") or "")
    if not role_arn or not sname:
        raise StsError("ValidationError", "RoleArn and RoleSessionName are required.")
    if not re.fullmatch(r"[\w+=,.@-]{2,64}", sname):
        raise StsError("ValidationError", f"1 validation error detected: Value '{sname}' at 'roleSessionName' failed to satisfy constraint: "
                                          "Member must satisfy regular expression pattern: [\\w+=,.@-]*")
    caller = dict(caller or {})
    carn = caller.get("arn") or f"arn:aws:iam::{_acct(store)}:root"
    role = _role_by_arn(store, role_arn)
    if role is None:
        raise _access_denied(carn, "sts:AssumeRole", role_arn)
    ext = params.get("ExternalId")
    tags = _tags(params)
    raw = _caller_context(caller)
    raw.update({"sts:RoleSessionName": sname, "sts:SourceIdentity": params.get("SourceIdentity"),
                "aws:SourceIdentity": params.get("SourceIdentity"), "sts:ExternalId": ext})
    raw = {k: v for k, v in raw.items() if v not in (None, "")}
    if params.get("SerialNumber"):
        raw["aws:MultiFactorAuthPresent"] = bool(params.get("TokenCode"))
    elif caller.get("mfa"):
        raw["aws:MultiFactorAuthPresent"] = True
    for k, v in tags.items():
        raw[f"aws:RequestTag/{k}"] = v
    if tags:
        raw["aws:TagKeys"] = list(tags)
    p = {"arn": carn, "account": caller.get("account") or _acct(store), "type": caller.get("type") or "root", "tags": caller.get("tags") or {}}
    if p["type"] == "unknown":
        p["type"] = "root"
        p["arn"] = f"arn:aws:iam::{p['account']}:root"
    res = evaluate_trust(role.get("assume_role_policy_document") or {}, "sts:AssumeRole", p, raw)
    if not res["allowed"]:
        raise _access_denied(carn, "sts:AssumeRole", role_arn)
    # same-account `:root` / `*` principal: the caller's own identity policy must also allow it (an explicit user/role ARN needs no more)
    if p["type"] in ("user", "role") and p["account"] == _acct(store) and res["kinds"] <= {"account", "wildcard"}:
        full = dict(caller)
        full.setdefault("account", p["account"])
        if not _identity_allows(store, full, "sts:AssumeRole", role_arn):
            raise _access_denied(carn, "sts:AssumeRole", role_arn)
    d = _duration(params, role)
    akid, sess = _record_session(store, role, sname, d, _session_policy(params), tags,
                                 {"source_identity": params.get("SourceIdentity"), "assumed_by": carn})
    extra = {"SourceIdentity": params["SourceIdentity"]} if params.get("SourceIdentity") else {}
    return _result(store, role, akid, sess, **extra)


# ------------------------------------------------------------------ web identity (OIDC)
def _b64url(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decode_jwt(token):
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise StsError("InvalidIdentityToken", "Couldn't retrieve verification key from your identity provider,  "
                                               "please reference AssumeRoleWithWebIdentity documentation for requirements")
    try:
        claims = json.loads(_b64url(parts[1]).decode("utf-8"))
        if not isinstance(claims, dict):
            raise ValueError
    except Exception:
        raise StsError("InvalidIdentityToken", "Couldn't retrieve verification key from your identity provider,  "
                                               "please reference AssumeRoleWithWebIdentity documentation for requirements")
    return claims


def _provider_key(url):
    return re.sub(r"^https?://", "", str(url or "")).rstrip("/")


def find_oidc_provider(store, issuer):
    key = _provider_key(issuer).lower()
    for arn, p in (store.oidc_providers or {}).items():
        if _provider_key(p.get("url")).lower() == key:
            return arn, p
    return None, None


def assume_role_with_web_identity(store, params, now=None):
    now = now or _now()
    role_arn, sname, token = str(params.get("RoleArn") or ""), str(params.get("RoleSessionName") or ""), params.get("WebIdentityToken")
    if not (role_arn and sname and token):
        raise StsError("ValidationError", "RoleArn, RoleSessionName and WebIdentityToken are required.")
    claims = decode_jwt(token)
    iss = str(claims.get("iss") or "")
    parr, prov = find_oidc_provider(store, iss)
    if prov is None:
        raise StsError("InvalidIdentityToken", f"No OpenIDConnect provider found in your account for {iss}")
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp < now:
        raise StsError("ExpiredTokenException", f"Token expired: current date/time {_iso(now)} must be before the expiration date/time {_iso(exp)}")
    auds = [str(a) for a in E._as_list(claims.get("aud"))] or [str(claims.get("azp") or claims.get("client_id") or "")]
    if "azp" in claims:
        auds.append(str(claims["azp"]))
    clients = list(prov.get("client_ids") or [])
    if clients and not any(a in clients for a in auds):
        raise StsError("InvalidIdentityToken", "Incorrect token audience")
    role = _role_by_arn(store, role_arn)
    if role is None:
        raise StsError("AccessDenied", f"Not authorized to perform sts:AssumeRoleWithWebIdentity", 403)
    pk = _provider_key(iss)
    raw = {"aws:FederatedProvider": pk, f"{pk}:aud": auds[0] if auds else "", f"{pk}:sub": claims.get("sub")}
    if claims.get("amr") is not None:
        raw[f"{pk}:amr"] = E._as_list(claims["amr"])
    for k, v in claims.items():
        if k in ("iss", "aud", "sub", "exp", "iat", "nbf", "amr", "jti") or isinstance(v, (dict, list)):
            continue
        raw[f"{pk}:{k}"] = v
    if "cognito-identity.amazonaws.com" in pk:
        raw["cognito-identity.amazonaws.com:aud"] = auds[0] if auds else ""
        raw["cognito-identity.amazonaws.com:sub"] = claims.get("sub")
    tags = {}
    tag_claim = claims.get("https://aws.amazon.com/tags")
    if isinstance(tag_claim, dict):                       # session tags carried in the token (principal_tags)
        for k, v in (tag_claim.get("principal_tags") or {}).items():
            tags[k] = v[0] if isinstance(v, list) and v else v
    raw = {k: v for k, v in raw.items() if v not in (None, "")}
    res = evaluate_trust(role.get("assume_role_policy_document") or {}, "sts:AssumeRoleWithWebIdentity",
                         {"type": "federated", "arn": parr, "account": _acct(store)}, raw)
    if not res["allowed"]:
        raise StsError("AccessDenied", "Not authorized to perform sts:AssumeRoleWithWebIdentity", 403)
    d = _duration(params, role)
    akid, sess = _record_session(store, role, sname, d, _session_policy(params), tags,
                                 {"federated": {"provider": pk, "subject": claims.get("sub"), "audience": auds[0] if auds else ""}})
    return _result(store, role, akid, sess, SubjectFromWebIdentityToken=str(claims.get("sub") or ""),
                   Audience=auds[0] if auds else "", Provider=pk)


# ------------------------------------------------------------------ SAML
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_saml(assertion_b64):
    try:
        xml = base64.b64decode(assertion_b64 + "=" * (-len(str(assertion_b64)) % 4)).decode("utf-8")
        root = ET.fromstring(xml)
    except Exception:
        raise StsError("InvalidIdentityToken", "Unable to parse the SAML assertion.")
    out = {"issuer": "", "audiences": [], "name_id": "", "name_format": "", "recipient": "", "not_on_or_after": None, "attrs": {}}
    for el in root.iter():
        t = _local(el.tag)
        if t == "Issuer" and not out["issuer"]:
            out["issuer"] = (el.text or "").strip()
        elif t == "Audience":
            out["audiences"].append((el.text or "").strip())
        elif t == "NameID":
            out["name_id"], out["name_format"] = (el.text or "").strip(), el.attrib.get("Format", "")
        elif t == "SubjectConfirmationData":
            out["recipient"] = el.attrib.get("Recipient", "") or out["recipient"]
            if el.attrib.get("NotOnOrAfter"):
                out["not_on_or_after"] = out["not_on_or_after"] or el.attrib["NotOnOrAfter"]
        elif t == "Conditions" and el.attrib.get("NotOnOrAfter"):
            out["not_on_or_after"] = el.attrib["NotOnOrAfter"]
        elif t == "Attribute":
            vals = [(v.text or "").strip() for v in el if _local(v.tag) == "AttributeValue"]
            out["attrs"].setdefault(el.attrib.get("Name", ""), []).extend(vals)
    return out


def _parse_ts(s):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", str(s or ""))
    if not m:
        return None
    import calendar
    return calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))


def assume_role_with_saml(store, params, now=None):
    now = now or _now()
    role_arn, parn, assertion = str(params.get("RoleArn") or ""), str(params.get("PrincipalArn") or ""), params.get("SAMLAssertion")
    if not (role_arn and parn and assertion):
        raise StsError("ValidationError", "RoleArn, PrincipalArn and SAMLAssertion are required.")
    a = parse_saml(assertion)
    prov = (store.saml_providers or {}).get(parn)
    if prov is None:
        raise StsError("InvalidIdentityToken", f"Provider {parn} not found in your account.")
    meta = prov.get("metadata_document") or ""
    ent = re.search(r"entityID=[\"']([^\"']+)[\"']", meta)
    if ent and a["issuer"] != ent.group(1):
        raise StsError("InvalidIdentityToken", f"Issuer {a['issuer']} not present in specified SAML provider")
    exp = _parse_ts(a["not_on_or_after"])
    if exp is not None and exp < now:
        raise StsError("ExpiredTokenException", f"Token must be redeemed within 5 minutes of issuance (NotOnOrAfter {a['not_on_or_after']})")
    if not any(x in SAML_AUDIENCES for x in a["audiences"]):
        raise StsError("InvalidIdentityToken", "Audience restriction in the SAML assertion does not include the AWS sign-in endpoint")
    claimed = [tuple(sorted(s.strip() for s in v.split(",") if s.strip())) for v in a["attrs"].get("https://aws.amazon.com/SAML/Attributes/Role", [])]
    if claimed and tuple(sorted((role_arn, parn))) not in claimed:
        raise StsError("AccessDenied", "Not authorized to perform sts:AssumeRoleWithSAML", 403)
    role = _role_by_arn(store, role_arn)
    if role is None:
        raise StsError("AccessDenied", "Not authorized to perform sts:AssumeRoleWithSAML", 403)
    friendly = parn.rsplit("/", 1)[-1]
    fmt = a["name_format"].rsplit(":", 1)[-1] if a["name_format"] else ""
    sub_type = {"persistent": "persistent", "transient": "transient"}.get(fmt, "persistent" if fmt else "")
    raw = {"saml:aud": a["recipient"] or SAML_AUDIENCES[0], "saml:iss": a["issuer"], "saml:sub": a["name_id"], "saml:sub_type": sub_type,
           "saml:doc": f"{_acct(store)}/{friendly}",
           "saml:namequalifier": base64.b64encode(hashlib.sha1(f"{a['issuer']}{_acct(store)}/{friendly}".encode()).digest()).decode()}
    for name, vals in a["attrs"].items():
        short = name.rsplit("/", 1)[-1]
        if short in ("eduPersonAffiliation", "eduPersonPrincipalName", "eduPersonEntitlement", "eduPersonOrgDN", "eduPersonPrimaryAffiliation",
                     "eduPersonScopedAffiliation", "eduPersonTargetedID", "eduPersonAssurance", "eduPersonOrgUnitDN", "eduPersonPrimaryOrgUnitDN"):
            raw["saml:" + short.lower()] = vals
    raw = {k: v for k, v in raw.items() if v not in (None, "")}
    res = evaluate_trust(role.get("assume_role_policy_document") or {}, "sts:AssumeRoleWithSAML",
                         {"type": "federated", "arn": parn, "account": _acct(store)}, raw)
    if not res["allowed"]:
        raise StsError("AccessDenied", "Not authorized to perform sts:AssumeRoleWithSAML", 403)
    sname = (a["attrs"].get("https://aws.amazon.com/SAML/Attributes/RoleSessionName") or [a["name_id"] or "saml-session"])[0]
    sd = (a["attrs"].get("https://aws.amazon.com/SAML/Attributes/SessionDuration") or [None])[0]
    p2 = dict(params)
    if sd and not p2.get("DurationSeconds") and str(sd).isdigit():
        p2["DurationSeconds"] = sd
    d = _duration(p2, role)
    akid, sess = _record_session(store, role, sname, d, _session_policy(params), {},
                                 {"federated": {"provider": parn, "subject": a["name_id"], "issuer": a["issuer"]}})
    return _result(store, role, akid, sess, Subject=a["name_id"], SubjectType=sub_type or "unspecified", Issuer=a["issuer"],
                   Audience=a["recipient"] or SAML_AUDIENCES[0], NameQualifier=raw["saml:namequalifier"])


# ------------------------------------------------------------------ IAM Roles Anywhere
def _der(buf, i):
    tag = buf[i]
    ln = buf[i + 1]
    j = i + 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[j:j + n], "big")
        j += n
    return tag, j, j + ln


def _name_cn(buf, start, end):
    """Common Name (OID 2.5.4.3) of an X.501 Name (sequence of RDN sets)."""
    i = start
    while i < end:
        _, s, e = _der(buf, i)                 # SET
        _, s2, e2 = _der(buf, s)               # SEQUENCE
        _, s3, e3 = _der(buf, s2)              # OID
        if bytes(buf[s3:e3]) == b"\x55\x04\x03":
            _, s4, e4 = _der(buf, e3)
            return bytes(buf[s4:e4]).decode("utf-8", "replace")
        i = e
    return ""


def parse_certificate(pem):
    """-> {"subject_cn","issuer_cn","serial"} from a PEM X.509 certificate (minimal DER reader; no chain validation)."""
    m = re.search(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", str(pem or ""), re.S)
    if not m:
        raise StsError("ValidationException", "Invalid certificate: expected a PEM encoded X.509 certificate.", 400)
    try:
        buf = base64.b64decode(re.sub(r"\s+", "", m.group(1)))
        _, s, _e = _der(buf, 0)                # Certificate
        _, s, _e = _der(buf, s)                # tbsCertificate
        i = s
        if buf[i] == 0xA0:                     # [0] version
            _, _, i = _der(buf, i)
        _, ss, i = _der(buf, i)                # serial
        serial = bytes(buf[ss:i]).hex()
        _, _, i = _der(buf, i)                 # signature algorithm
        _, is_, ie = _der(buf, i)              # issuer
        _, _, i = _der(buf, ie)                # validity
        _, ss2, se = _der(buf, i)              # subject
        return {"subject_cn": _name_cn(buf, ss2, se), "issuer_cn": _name_cn(buf, is_, ie), "serial": serial}
    except Exception:
        raise StsError("ValidationException", "Invalid certificate: could not be parsed.", 400)


def roles_anywhere_session(store, profile_arn, trust_anchor_arn, role_arn, cert_pem, duration=3600):
    """rolesanywhere CreateSession. -> {"credentialSet":[...], "subjectArn": ...} (REST-JSON shape)."""
    x = store.extras
    anchors = (getattr(store, "trust_anchors", None) or x.get("trust_anchors") or {})
    profiles = (getattr(store, "rolesanywhere_profiles", None) or x.get("rolesanywhere_profiles") or {})
    anchor = next((a for a in anchors.values() if a.get("arn") == trust_anchor_arn or a.get("trustAnchorArn") == trust_anchor_arn), None)
    profile = next((p for p in profiles.values() if p.get("arn") == profile_arn or p.get("profileArn") == profile_arn), None)
    if anchor is None:
        raise StsError("ResourceNotFoundException", f"Trust anchor {trust_anchor_arn} not found.", 404)
    if profile is None:
        raise StsError("ResourceNotFoundException", f"Profile {profile_arn} not found.", 404)
    if anchor.get("enabled") is False or profile.get("enabled") is False:
        raise StsError("AccessDeniedException", "Trust anchor or profile is disabled.", 403)
    roles = [r for r in (profile.get("roleArns") or profile.get("role_arns") or [])]
    if role_arn not in roles:
        raise StsError("AccessDeniedException", f"Role {role_arn} is not part of profile {profile_arn}.", 403)
    role = _role_by_arn(store, role_arn)
    if role is None:
        raise StsError("ResourceNotFoundException", f"Role {role_arn} not found.", 404)
    cert = parse_certificate(cert_pem)
    try:
        anchor_cn = parse_certificate(anchor.get("source_data") or anchor.get("sourceData") or "")["subject_cn"]
    except StsError:
        anchor_cn = ""
    if anchor_cn and cert["issuer_cn"] != anchor_cn:       # issuer name must be the anchor CA's subject (the signature itself is not verified)
        raise StsError("AccessDeniedException", "Untrusted certificate. Insufficient certificate: the issuer is not the trust anchor.", 403)
    raw = {"aws:SourceArn": trust_anchor_arn, "aws:PrincipalTag/x509Subject/CN": cert["subject_cn"],
           "aws:PrincipalTag/x509Issuer/CN": cert["issuer_cn"], "sts:RoleSessionName": cert["serial"][:32] or "session"}
    svc = {"type": "service", "service": "rolesanywhere.amazonaws.com", "arn": "rolesanywhere.amazonaws.com", "account": _acct(store)}
    res = evaluate_trust(role.get("assume_role_policy_document") or {}, "sts:AssumeRole", svc, raw)
    if not res["allowed"]:
        raise StsError("AccessDeniedException", f"Not authorized to perform sts:AssumeRole on {role_arn}: the role trust policy does not allow "
                                                "rolesanywhere.amazonaws.com for this trust anchor / certificate.", 403)
    d = _duration({"DurationSeconds": duration}, role, 3600) if duration else min(3600, int(role.get("max_session_duration") or 3600))
    akid, sess = _record_session(store, role, cert["serial"][:32] or "rolesanywhere", d, None,
                                 {"x509Subject/CN": cert["subject_cn"], "x509Issuer/CN": cert["issuer_cn"]},
                                 {"rolesanywhere": {"trust_anchor": trust_anchor_arn, "profile": profile_arn, "subject_cn": cert["subject_cn"]}})
    c = _credentials(akid, sess)
    return {"credentialSet": [{"assumedRoleUser": {"arn": f"arn:aws:sts::{_acct(store)}:assumed-role/{role['role_name']}/{sess['session_name']}",
                                                   "assumedRoleId": sess["assumed_role_id"]},
                               "credentials": {"accessKeyId": akid, "secretAccessKey": c["SecretAccessKey"], "sessionToken": c["SessionToken"],
                                               "expiration": c["Expiration"]},
                               "packedPolicySize": 0, "roleArn": role_arn}],
            "subjectArn": f"arn:aws:rolesanywhere:us-east-1:{_acct(store)}:subject/{uuid.uuid4()}"}


# ------------------------------------------------------------------ XML rendering (Query protocol)
_NS = "https://sts.amazonaws.com/doc/2011-06-15/"


def _xml_escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _to_xml(v):
    if isinstance(v, dict):
        return "".join(f"<{k}>{_to_xml(x)}</{k}>" for k, x in v.items())
    return _xml_escape(v)


def render(action, result, request_id):
    return ('<?xml version="1.0" encoding="UTF-8"?>' f'<{action}Response xmlns="{_NS}"><{action}Result>{_to_xml(result)}</{action}Result>'
            f"<ResponseMetadata><RequestId>{request_id}</RequestId></ResponseMetadata></{action}Response>")


def render_error(err, request_id):
    return ('<?xml version="1.0" encoding="UTF-8"?>' f'<ErrorResponse xmlns="{_NS}"><Error><Type>Sender</Type><Code>{_xml_escape(err.code)}</Code>'
            f"<Message>{_xml_escape(err.message)}</Message></Error><RequestId>{request_id}</RequestId></ErrorResponse>")
