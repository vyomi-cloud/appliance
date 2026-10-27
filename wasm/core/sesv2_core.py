"""Amazon SES v2 core — substrate-independent engine for the AWS SESv2 API.

Targets the NATIVE SESv2 wire — **REST-JSON** (`/v2/email/...`, JSON bodies, errors
signalled by the `x-amzn-ErrorType` header) — so an unmodified boto3 / aws-cli /
aws-sdk-java-v2 / aws-sdk-go-v2 client works with only the endpoint overridden.
Request / response field names and error codes follow the botocore model
(`sesv2/2019-09-27/service-2.json`).

Pure Python (stdlib only — no fastapi / boto3 / socket), so the SAME file runs on the
offline appliance and in Nano (Pyodide). State lives in a `SesV2Store` (plain dicts and
a `persist()` hook) — the seam the offline appliance backs with the space-scoped state
and Nano backs with its shared store registry.

Backend: in-process. Mail is never relayed: SendEmail / SendBulkEmail validate the
request exactly as SES does (verified sender, content shape, configuration set) and
record the message in the store ("sent mailbox"), which the console and tests read back.

Operations: Create/Get/List/Delete EmailIdentity (+ DKIM, MailFrom, Feedback, config-set
attributes, identity policies), Create/Get/List/Delete ConfigurationSet (+ the Put*Options
family and event destinations), Create/Get/List/Update/Delete EmailTemplate (+ TestRender),
Create/Get/List/Update/Delete ContactList and Contact, Put/Get/List/Delete
SuppressedDestination, Create/Get/List/Delete DedicatedIpPool, SendEmail, SendBulkEmail,
Tag/Untag/ListTagsForResource, Get/Put account attributes, Create/Get/List/Delete Tenant,
GetDeliverabilityDashboardOptions.

The `console_*` helpers at the bottom are the flat REST view the web consoles use
(`/api/aws/sesv2/...`), shared by the offline server and Nano.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote

DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
PREFIX = "/v2/email"

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_DOMAIN_RE = re.compile(r"^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")


@dataclass
class SesV2Response:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str = "application/json"


class SesV2Error(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


ACCOUNT_DEFAULTS = {
    "ProductionAccessEnabled": False, "SendingEnabled": True, "DedicatedIpAutoWarmupEnabled": False,
    "SuppressedReasons": [], "VdmEnabled": "DISABLED", "DashboardEnabled": False,
    "Details": None, "PricingAttributes": None,
}


class SesV2Store:
    """State seam: plain dicts the engine reads/writes. `persist()` is called after
    every mutation."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id = account_id
        self.region = region
        self.identities: dict[str, dict] = {}
        self.config_sets: dict[str, dict] = {}
        self.templates: dict[str, dict] = {}
        self.contact_lists: dict[str, dict] = {}
        self.suppression: dict[str, dict] = {}
        self.ip_pools: dict[str, dict] = {}
        self.tenants: dict[str, dict] = {}
        self.tags: dict[str, dict] = {}          # resource ARN → {key: value}
        self.messages: list[dict] = []           # the sent mailbox
        self.account: dict = dict(ACCOUNT_DEFAULTS)

    def persist(self) -> None:
        pass


# ── helpers ────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _arn(store: SesV2Store, kind: str, name: str) -> str:
    return f"arn:aws:ses:{store.region}:{store.account_id}:{kind}/{name}"


def _bad(msg: str) -> SesV2Error:
    return SesV2Error("BadRequestException", msg, 400)


def _notfound(msg: str) -> SesV2Error:
    return SesV2Error("NotFoundException", msg, 404)


def _exists(msg: str) -> SesV2Error:
    return SesV2Error("AlreadyExistsException", msg, 400)


def _need(d: dict, key: str):
    v = d.get(key)
    if v is None or v == "":
        raise _bad(f"1 validation error detected: Value null at '{key[0].lower() + key[1:]}' failed to satisfy constraint: Member must not be null")
    return v


def _tags_in(raw) -> dict:
    out = {}
    for t in raw or []:
        if not isinstance(t, dict) or "Key" not in t:
            raise _bad("Tags must be a list of Key/Value pairs")
        out[str(t["Key"])] = str(t.get("Value", ""))
    return out


def _tags_out(d: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in d.items()]


def _page(items: list, body: dict, q: dict, key: str, extra: dict | None = None) -> dict:
    """NextToken/PageSize pagination (token = the next offset)."""
    token = body.get("NextToken") or q.get("nexttoken")
    size = body.get("PageSize") or q.get("pagesize")
    try:
        start = int(token) if token else 0
        n = int(size) if size else 100
    except ValueError:
        raise _bad("Invalid NextToken or PageSize")
    n = max(1, min(n, 1000))
    out = {key: items[start:start + n]}
    if start + n < len(items):
        out["NextToken"] = str(start + n)
    if extra:
        out.update(extra)
    return out


def _ok(obj=None, status: int = 200) -> SesV2Response:
    return SesV2Response(status, json.dumps(obj if obj is not None else {}).encode())


def _error(code: str, message: str, status: int) -> SesV2Response:
    return SesV2Response(status, json.dumps({"message": message}).encode(),
                         {"x-amzn-ErrorType": code, "x-amzn-errortype": code})


def _tags_key(store: SesV2Store, arn: str) -> dict:
    return store.tags.setdefault(arn, {})


# ── identities ─────────────────────────────────────────────────────────────
def _identity_type(name: str) -> str:
    return "EMAIL_ADDRESS" if "@" in name else "DOMAIN"


def _dkim(store: SesV2Store, name: str, attrs: dict | None) -> dict:
    attrs = attrs or {}
    if "@" in name:
        return {"SigningEnabled": False, "Status": "NOT_STARTED", "Tokens": [], "SigningAttributesOrigin": "AWS_SES"}
    ext = bool(attrs.get("DomainSigningPrivateKey"))
    d = {"SigningEnabled": True, "Status": "SUCCESS", "SigningAttributesOrigin": "EXTERNAL" if ext else "AWS_SES",
         "LastKeyGenerationTimestamp": _epoch()}
    if ext:
        d["Tokens"] = []
    else:
        d["Tokens"] = [uuid.uuid4().hex[:32] for _ in range(3)]
        d["NextSigningKeyLength"] = attrs.get("NextSigningKeyLength") or "RSA_2048_BIT"
        d["CurrentSigningKeyLength"] = d["NextSigningKeyLength"]
    return d


def _identity_dkim_view(i: dict) -> dict:
    d = dict(i["DkimAttributes"])
    d["SigningEnabled"] = i.get("dkim_enabled", d.get("SigningEnabled", False))
    return d


def create_email_identity(store, p, q, b):
    name = _need(b, "EmailIdentity").strip()
    if not (_EMAIL_RE.match(name) or _DOMAIN_RE.match(name)):
        raise _bad(f"Invalid identity: {name}")
    if name in store.identities:
        raise _exists(f"Identity <{name}> already exists.")
    cs = b.get("ConfigurationSetName")
    if cs and cs not in store.config_sets:
        raise _notfound(f"Configuration set <{cs}> does not exist.")
    dkim = _dkim(store, name, b.get("DkimSigningAttributes"))
    store.identities[name] = {
        "EmailIdentity": name, "IdentityType": _identity_type(name), "created": _now(),
        "FeedbackForwardingStatus": True, "VerifiedForSendingStatus": True, "VerificationStatus": "SUCCESS",
        "DkimAttributes": dkim, "dkim_enabled": dkim["SigningEnabled"],
        "MailFromAttributes": {"MailFromDomain": "", "MailFromDomainStatus": "", "BehaviorOnMxFailure": "USE_DEFAULT_VALUE"},
        "Policies": {}, "ConfigurationSetName": cs or "", "SendingEnabled": True,
    }
    store.tags[_arn(store, "identity", name)] = {t["Key"]: t["Value"] for t in b.get("Tags") or []}
    store.persist()
    return _ok({"IdentityType": _identity_type(name), "VerifiedForSendingStatus": True,
                "DkimAttributes": _identity_dkim_view(store.identities[name])})


def _ident(store, name: str) -> dict:
    i = store.identities.get(name)
    if i is None:
        raise _notfound(f"Email identity <{name}> does not exist.")
    return i


def get_email_identity(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    mf = {k: v for k, v in i["MailFromAttributes"].items() if v != ""}
    out = {"IdentityType": i["IdentityType"], "FeedbackForwardingStatus": i["FeedbackForwardingStatus"],
           "VerifiedForSendingStatus": i["VerifiedForSendingStatus"], "VerificationStatus": i["VerificationStatus"],
           "DkimAttributes": _identity_dkim_view(i), "Policies": dict(i["Policies"]),
           "Tags": _tags_out(store.tags.get(_arn(store, "identity", i["EmailIdentity"]), {}))}
    if mf:
        out["MailFromAttributes"] = mf
    if i["ConfigurationSetName"]:
        out["ConfigurationSetName"] = i["ConfigurationSetName"]
    return _ok(out)


def list_email_identities(store, p, q, b):
    items = [{"IdentityType": i["IdentityType"], "IdentityName": n, "SendingEnabled": i["SendingEnabled"],
              "VerificationStatus": i["VerificationStatus"]} for n, i in sorted(store.identities.items())]
    return _ok(_page(items, b, q, "EmailIdentities"))


def delete_email_identity(store, p, q, b):
    name = p["EmailIdentity"]
    _ident(store, name)
    del store.identities[name]
    store.tags.pop(_arn(store, "identity", name), None)
    store.persist()
    return _ok()


def put_identity_dkim(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    if "@" in i["EmailIdentity"]:
        raise _bad("DKIM is not supported for email address identities.")
    i["dkim_enabled"] = bool(b.get("SigningEnabled", True))
    store.persist()
    return _ok()


def put_identity_dkim_signing(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    if "@" in i["EmailIdentity"]:
        raise _bad("DKIM signing attributes are not supported for email address identities.")
    origin = b.get("SigningAttributesOrigin") or "AWS_SES"
    if origin not in ("AWS_SES", "EXTERNAL"):
        raise _bad("SigningAttributesOrigin must be AWS_SES or EXTERNAL")
    attrs = b.get("SigningAttributes") or {}
    i["DkimAttributes"] = _dkim(store, i["EmailIdentity"], {
        "DomainSigningPrivateKey": attrs.get("DomainSigningPrivateKey") if origin == "EXTERNAL" else None,
        "NextSigningKeyLength": b.get("SigningAttributes", {}).get("NextSigningKeyLength")})
    i["dkim_enabled"] = True
    store.persist()
    d = i["DkimAttributes"]
    return _ok({"DkimStatus": d["Status"], "DkimTokens": d["Tokens"]})


def put_identity_feedback(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    i["FeedbackForwardingStatus"] = bool(b.get("EmailForwardingEnabled", True))
    store.persist()
    return _ok()


def put_identity_mail_from(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    dom = b.get("MailFromDomain") or ""
    beh = b.get("BehaviorOnMxFailure") or "USE_DEFAULT_VALUE"
    if beh not in ("USE_DEFAULT_VALUE", "REJECT_MESSAGE"):
        raise _bad("BehaviorOnMxFailure must be USE_DEFAULT_VALUE or REJECT_MESSAGE")
    i["MailFromAttributes"] = {"MailFromDomain": dom, "MailFromDomainStatus": "SUCCESS" if dom else "",
                               "BehaviorOnMxFailure": beh}
    store.persist()
    return _ok()


def put_identity_config_set(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    cs = b.get("ConfigurationSetName") or ""
    if cs and cs not in store.config_sets:
        raise _notfound(f"Configuration set <{cs}> does not exist.")
    i["ConfigurationSetName"] = cs
    store.persist()
    return _ok()


def _policy_check(i, name, must_exist):
    if must_exist and name not in i["Policies"]:
        raise _notfound(f"Policy <{name}> does not exist.")
    if not must_exist and name in i["Policies"]:
        raise _exists(f"Policy <{name}> already exists.")


def create_identity_policy(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    _policy_check(i, p["PolicyName"], False)
    i["Policies"][p["PolicyName"]] = _need(b, "Policy")
    store.persist()
    return _ok()


def update_identity_policy(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    _policy_check(i, p["PolicyName"], True)
    i["Policies"][p["PolicyName"]] = _need(b, "Policy")
    store.persist()
    return _ok()


def delete_identity_policy(store, p, q, b):
    i = _ident(store, p["EmailIdentity"])
    _policy_check(i, p["PolicyName"], True)
    del i["Policies"][p["PolicyName"]]
    store.persist()
    return _ok()


def get_identity_policies(store, p, q, b):
    return _ok({"Policies": dict(_ident(store, p["EmailIdentity"])["Policies"])})


# ── configuration sets ─────────────────────────────────────────────────────
def _cs(store, name: str) -> dict:
    c = store.config_sets.get(name)
    if c is None:
        raise _notfound(f"Configuration set <{name}> does not exist.")
    return c


def create_config_set(store, p, q, b):
    name = _need(b, "ConfigurationSetName")
    if not _NAME_RE.match(name):
        raise _bad("ConfigurationSetName may contain only letters, numbers, underscores and dashes (max 64).")
    if name in store.config_sets:
        raise _exists(f"Configuration set <{name}> already exists.")
    store.config_sets[name] = {
        "ConfigurationSetName": name, "created": _now(),
        "TrackingOptions": b.get("TrackingOptions") or {},
        "DeliveryOptions": b.get("DeliveryOptions") or {},
        "ReputationOptions": b.get("ReputationOptions") or {"ReputationMetricsEnabled": False},
        "SendingOptions": b.get("SendingOptions") or {"SendingEnabled": True},
        "SuppressionOptions": b.get("SuppressionOptions") or {},
        "VdmOptions": b.get("VdmOptions") or {},
        "ArchivingOptions": b.get("ArchivingOptions") or {},
        "event_destinations": {},
    }
    store.tags[_arn(store, "configuration-set", name)] = {t["Key"]: t["Value"] for t in b.get("Tags") or []}
    store.persist()
    return _ok()


def get_config_set(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    out = {"ConfigurationSetName": c["ConfigurationSetName"],
           "Tags": _tags_out(store.tags.get(_arn(store, "configuration-set", c["ConfigurationSetName"]), {}))}
    for k in ("TrackingOptions", "DeliveryOptions", "ReputationOptions", "SendingOptions",
              "SuppressionOptions", "VdmOptions", "ArchivingOptions"):
        if c[k]:
            out[k] = c[k]
    return _ok(out)


def list_config_sets(store, p, q, b):
    return _ok(_page(sorted(store.config_sets), b, q, "ConfigurationSets"))


def delete_config_set(store, p, q, b):
    name = p["ConfigurationSetName"]
    _cs(store, name)
    del store.config_sets[name]
    store.tags.pop(_arn(store, "configuration-set", name), None)
    store.persist()
    return _ok()


def _put_cs_option(field_name: str, mapping: dict):
    def h(store, p, q, b):
        c = _cs(store, p["ConfigurationSetName"])
        val = dict(c[field_name])
        for body_key, key in mapping.items():
            if body_key in b:
                val[key] = b[body_key]
        c[field_name] = val
        store.persist()
        return _ok()
    return h


def put_cs_vdm(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    c["VdmOptions"] = b.get("VdmOptions") or {}
    store.persist()
    return _ok()


def put_cs_archiving(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    c["ArchivingOptions"] = {"ArchiveArn": b["ArchiveArn"]} if b.get("ArchiveArn") else {}
    store.persist()
    return _ok()


def _dest_view(name: str, d: dict) -> dict:
    out = {"Name": name, "Enabled": d.get("Enabled", False), "MatchingEventTypes": d.get("MatchingEventTypes") or []}
    for k in ("CloudWatchDestination", "KinesisFirehoseDestination", "SnsDestination", "EventBridgeDestination",
              "PinpointDestination"):
        if k in d:
            out[k] = d[k]
    return out


def create_event_destination(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    name = _need(b, "EventDestinationName")
    d = _need(b, "EventDestination")
    if not d.get("MatchingEventTypes"):
        raise _bad("MatchingEventTypes must contain at least one event type.")
    if name in c["event_destinations"]:
        raise _exists(f"Event destination <{name}> already exists.")
    c["event_destinations"][name] = d
    store.persist()
    return _ok()


def update_event_destination(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    name = p["EventDestinationName"]
    if name not in c["event_destinations"]:
        raise _notfound(f"Event destination <{name}> does not exist.")
    c["event_destinations"][name] = _need(b, "EventDestination")
    store.persist()
    return _ok()


def delete_event_destination(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    name = p["EventDestinationName"]
    if name not in c["event_destinations"]:
        raise _notfound(f"Event destination <{name}> does not exist.")
    del c["event_destinations"][name]
    store.persist()
    return _ok()


def get_event_destinations(store, p, q, b):
    c = _cs(store, p["ConfigurationSetName"])
    return _ok({"EventDestinations": [_dest_view(n, d) for n, d in c["event_destinations"].items()]})


# ── templates ──────────────────────────────────────────────────────────────
def _tpl(store, name: str) -> dict:
    t = store.templates.get(name)
    if t is None:
        raise _notfound(f"Template <{name}> does not exist.")
    return t


def _tpl_content(b: dict) -> dict:
    c = _need(b, "TemplateContent")
    if not c.get("Subject") and not c.get("Html") and not c.get("Text"):
        raise _bad("TemplateContent must have a Subject and at least one of Html or Text.")
    return {k: c[k] for k in ("Subject", "Html", "Text") if c.get(k) is not None}


def create_template(store, p, q, b):
    name = _need(b, "TemplateName")
    if name in store.templates:
        raise _exists(f"Template <{name}> already exists.")
    store.templates[name] = {"TemplateName": name, "TemplateContent": _tpl_content(b), "created": _now(),
                             "CreatedTimestamp": _epoch()}
    store.persist()
    return _ok()


def get_template(store, p, q, b):
    t = _tpl(store, p["TemplateName"])
    return _ok({"TemplateName": t["TemplateName"], "TemplateContent": t["TemplateContent"]})


def list_templates(store, p, q, b):
    items = [{"TemplateName": n, "CreatedTimestamp": t["CreatedTimestamp"]} for n, t in sorted(store.templates.items())]
    return _ok(_page(items, b, q, "TemplatesMetadata"))


def update_template(store, p, q, b):
    t = _tpl(store, p["TemplateName"])
    t["TemplateContent"] = _tpl_content(b)
    store.persist()
    return _ok()


def delete_template(store, p, q, b):
    _tpl(store, p["TemplateName"])
    del store.templates[p["TemplateName"]]
    store.persist()
    return _ok()


_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def _render(text: str, data: dict) -> str:
    return _VAR_RE.sub(lambda m: str(data.get(m.group(1), "")), text or "")


def test_render_template(store, p, q, b):
    t = _tpl(store, p["TemplateName"])
    try:
        data = json.loads(_need(b, "TemplateData"))
    except ValueError:
        raise _bad("TemplateData must be valid JSON.")
    c = t["TemplateContent"]
    parts = [f"Subject: {_render(c.get('Subject', ''), data)}", "MIME-Version: 1.0",
             "Content-Type: multipart/alternative; boundary=\"----=_vyomi\"", ""]
    if c.get("Text"):
        parts += ["------=_vyomi", "Content-Type: text/plain; charset=UTF-8", "", _render(c["Text"], data)]
    if c.get("Html"):
        parts += ["------=_vyomi", "Content-Type: text/html; charset=UTF-8", "", _render(c["Html"], data)]
    parts.append("------=_vyomi--")
    return _ok({"RenderedTemplate": "\n".join(parts)})


# ── contact lists / contacts ───────────────────────────────────────────────
def _cl(store, name: str) -> dict:
    c = store.contact_lists.get(name)
    if c is None:
        raise _notfound(f"List with name: {name} doesn't exist.")
    return c


def create_contact_list(store, p, q, b):
    name = _need(b, "ContactListName")
    if name in store.contact_lists:
        raise _exists(f"List with name: {name} already exists.")
    now = _epoch()
    store.contact_lists[name] = {"ContactListName": name, "Description": b.get("Description") or "",
                                 "Topics": b.get("Topics") or [], "CreatedTimestamp": now,
                                 "LastUpdatedTimestamp": now, "contacts": {}}
    store.tags[_arn(store, "contact-list", name)] = {t["Key"]: t["Value"] for t in b.get("Tags") or []}
    store.persist()
    return _ok()


def get_contact_list(store, p, q, b):
    c = _cl(store, p["ContactListName"])
    out = {k: c[k] for k in ("ContactListName", "Topics", "CreatedTimestamp", "LastUpdatedTimestamp")}
    if c["Description"]:
        out["Description"] = c["Description"]
    out["Tags"] = _tags_out(store.tags.get(_arn(store, "contact-list", c["ContactListName"]), {}))
    return _ok(out)


def list_contact_lists(store, p, q, b):
    items = [{"ContactListName": n, "LastUpdatedTimestamp": c["LastUpdatedTimestamp"]}
             for n, c in sorted(store.contact_lists.items())]
    return _ok(_page(items, b, q, "ContactLists"))


def update_contact_list(store, p, q, b):
    c = _cl(store, p["ContactListName"])
    if "Topics" in b:
        c["Topics"] = b["Topics"] or []
    if "Description" in b:
        c["Description"] = b["Description"] or ""
    c["LastUpdatedTimestamp"] = _epoch()
    store.persist()
    return _ok()


def delete_contact_list(store, p, q, b):
    _cl(store, p["ContactListName"])
    del store.contact_lists[p["ContactListName"]]
    store.tags.pop(_arn(store, "contact-list", p["ContactListName"]), None)
    store.persist()
    return _ok()


def _topic_defaults(c: dict) -> list:
    return [{"TopicName": t["TopicName"], "SubscriptionStatus": t.get("DefaultSubscriptionStatus", "OPT_OUT")}
            for t in c["Topics"]]


def _contact_view(lst: dict, ct: dict, full: bool) -> dict:
    out = {"EmailAddress": ct["EmailAddress"], "TopicPreferences": ct["TopicPreferences"],
           "TopicDefaultPreferences": _topic_defaults(lst), "UnsubscribeAll": ct["UnsubscribeAll"],
           "LastUpdatedTimestamp": ct["LastUpdatedTimestamp"]}
    if full:
        out["ContactListName"] = lst["ContactListName"]
        out["CreatedTimestamp"] = ct["CreatedTimestamp"]
        out["AttributesData"] = ct["AttributesData"]
    return out


def _check_topics(lst: dict, prefs: list):
    names = {t["TopicName"] for t in lst["Topics"]}
    for tp in prefs:
        if tp.get("TopicName") not in names:
            raise _bad(f"Topic <{tp.get('TopicName')}> does not exist in the contact list.")


def create_contact(store, p, q, b):
    lst = _cl(store, p["ContactListName"])
    addr = _need(b, "EmailAddress")
    if addr in lst["contacts"]:
        raise _exists(f"Contact with email address: {addr} already exists.")
    _check_topics(lst, b.get("TopicPreferences") or [])
    now = _epoch()
    lst["contacts"][addr] = {"EmailAddress": addr, "TopicPreferences": b.get("TopicPreferences") or [],
                             "UnsubscribeAll": bool(b.get("UnsubscribeAll", False)),
                             "AttributesData": b.get("AttributesData") or "", "CreatedTimestamp": now,
                             "LastUpdatedTimestamp": now}
    store.persist()
    return _ok()


def _contact(store, p) -> tuple[dict, dict]:
    lst = _cl(store, p["ContactListName"])
    ct = lst["contacts"].get(p["EmailAddress"])
    if ct is None:
        raise _notfound(f"Contact with email address: {p['EmailAddress']} doesn't exist.")
    return lst, ct


def get_contact(store, p, q, b):
    lst, ct = _contact(store, p)
    return _ok(_contact_view(lst, ct, True))


def list_contacts(store, p, q, b):
    lst = _cl(store, p["ContactListName"])
    items = [_contact_view(lst, c, False) for _, c in sorted(lst["contacts"].items())]
    flt = b.get("Filter") or {}
    if flt.get("FilteredStatus") == "OPT_IN":
        items = [i for i in items if not i["UnsubscribeAll"]]
    elif flt.get("FilteredStatus") == "OPT_OUT":
        items = [i for i in items if i["UnsubscribeAll"]]
    return _ok(_page(items, b, q, "Contacts"))


def update_contact(store, p, q, b):
    lst, ct = _contact(store, p)
    if "TopicPreferences" in b:
        _check_topics(lst, b["TopicPreferences"] or [])
        ct["TopicPreferences"] = b["TopicPreferences"] or []
    if "UnsubscribeAll" in b:
        ct["UnsubscribeAll"] = bool(b["UnsubscribeAll"])
    if "AttributesData" in b:
        ct["AttributesData"] = b["AttributesData"] or ""
    ct["LastUpdatedTimestamp"] = _epoch()
    store.persist()
    return _ok()


def delete_contact(store, p, q, b):
    lst, ct = _contact(store, p)
    del lst["contacts"][p["EmailAddress"]]
    store.persist()
    return _ok()


# ── suppression list ───────────────────────────────────────────────────────
def put_suppressed(store, p, q, b):
    addr = _need(b, "EmailAddress")
    reason = _need(b, "Reason")
    if reason not in ("BOUNCE", "COMPLAINT"):
        raise _bad("Reason must be BOUNCE or COMPLAINT")
    store.suppression[addr] = {"EmailAddress": addr, "Reason": reason, "LastUpdateTime": _epoch()}
    store.persist()
    return _ok()


def get_suppressed(store, p, q, b):
    s = store.suppression.get(p["EmailAddress"])
    if s is None:
        raise _notfound(f"{p['EmailAddress']} is not on your suppression list")
    return _ok({"SuppressedDestination": dict(s)})


def list_suppressed(store, p, q, b):
    reasons = q.get("reason") or []
    items = [dict(s) for _, s in sorted(store.suppression.items()) if not reasons or s["Reason"] in reasons]
    return _ok(_page(items, b, q, "SuppressedDestinationSummaries"))


def delete_suppressed(store, p, q, b):
    if p["EmailAddress"] not in store.suppression:
        raise _notfound(f"{p['EmailAddress']} is not on your suppression list")
    del store.suppression[p["EmailAddress"]]
    store.persist()
    return _ok()


# ── dedicated IP pools ─────────────────────────────────────────────────────
def create_ip_pool(store, p, q, b):
    name = _need(b, "PoolName")
    if name in store.ip_pools:
        raise _exists(f"Pool <{name}> already exists.")
    mode = b.get("ScalingMode") or "STANDARD"
    if mode not in ("STANDARD", "MANAGED"):
        raise _bad("ScalingMode must be STANDARD or MANAGED")
    store.ip_pools[name] = {"PoolName": name, "ScalingMode": mode, "created": _now()}
    store.tags[_arn(store, "dedicated-ip-pool", name)] = {t["Key"]: t["Value"] for t in b.get("Tags") or []}
    store.persist()
    return _ok()


def get_ip_pool(store, p, q, b):
    pool = store.ip_pools.get(p["PoolName"])
    if pool is None:
        raise _notfound(f"Pool <{p['PoolName']}> does not exist.")
    return _ok({"DedicatedIpPool": {"PoolName": pool["PoolName"], "ScalingMode": pool["ScalingMode"]}})


def list_ip_pools(store, p, q, b):
    return _ok(_page(sorted(store.ip_pools), b, q, "DedicatedIpPools"))


def delete_ip_pool(store, p, q, b):
    if p["PoolName"] not in store.ip_pools:
        raise _notfound(f"Pool <{p['PoolName']}> does not exist.")
    del store.ip_pools[p["PoolName"]]
    store.tags.pop(_arn(store, "dedicated-ip-pool", p["PoolName"]), None)
    store.persist()
    return _ok()


# ── sending ────────────────────────────────────────────────────────────────
def _sender_domain(addr: str) -> str:
    m = re.search(r"<([^>]+)>", addr)
    a = (m.group(1) if m else addr).strip()
    return a.lower()


def _check_sender(store, addr: str):
    a = _sender_domain(addr)
    if not _EMAIL_RE.match(a):
        raise _bad(f"Illegal address: {addr}")
    dom = a.split("@", 1)[1]
    for cand in (a, dom):
        for name, i in store.identities.items():
            if name.lower() == cand and i["SendingEnabled"] and i["VerifiedForSendingStatus"]:
                return
    raise SesV2Error("MessageRejected", f"Email address is not verified. The following identities failed the check "
                     f"in region {store.region.upper()}: {addr}", 400)


def _check_account(store, cs):
    if not store.account["SendingEnabled"]:
        raise SesV2Error("SendingPausedException", "Sending is paused for this account.", 400)
    if cs:
        c = _cs(store, cs)
        if not c["SendingOptions"].get("SendingEnabled", True):
            raise SesV2Error("SendingPausedException", f"Sending is paused for configuration set {cs}.", 400)


def _check_dest(d: dict):
    n = sum(len(d.get(k) or []) for k in ("ToAddresses", "CcAddresses", "BccAddresses"))
    if n == 0:
        raise _bad("Must specify at least one recipient address.")
    if n > 50:
        raise _bad("Too many recipients; a message can have at most 50.")
    for k in ("ToAddresses", "CcAddresses", "BccAddresses"):
        for a in d.get(k) or []:
            if not _EMAIL_RE.match(_sender_domain(a)):
                raise _bad(f"Illegal address: {a}")


def _record(store, kind: str, sender: str, dest: dict, content: dict, cs, extra=None) -> str:
    mid = f"{uuid.uuid4().hex[:16]}-{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:4]}-000000"
    msg = {"MessageId": mid, "Kind": kind, "From": sender, "To": list(dest.get("ToAddresses") or []),
           "Cc": list(dest.get("CcAddresses") or []), "Bcc": list(dest.get("BccAddresses") or []),
           "ConfigurationSetName": cs or "", "Content": content, "sent": _now()}
    if extra:
        msg.update(extra)
    store.messages.append(msg)
    del store.messages[:-500]
    return mid


def send_email(store, p, q, b):
    content = _need(b, "Content")
    kinds = [k for k in ("Simple", "Raw", "Template") if k in content]
    if len(kinds) != 1:
        raise _bad("Content must contain exactly one of Simple, Raw or Template.")
    cs = b.get("ConfigurationSetName")
    _check_account(store, cs)
    dest = b.get("Destination") or {}
    sender = b.get("FromEmailAddress")
    if kinds[0] == "Simple":
        s = content["Simple"]
        if not (s.get("Subject") or {}).get("Data"):
            raise _bad("Simple content requires a Subject.")
        body = s.get("Body") or {}
        if not ((body.get("Text") or {}).get("Data") or (body.get("Html") or {}).get("Data")):
            raise _bad("Simple content requires a Body with Text or Html.")
        _check_dest(dest)
    elif kinds[0] == "Template":
        t = content["Template"]
        if not t.get("TemplateName") and not t.get("TemplateArn"):
            raise _bad("Template content requires TemplateName or TemplateArn.")
        if t.get("TemplateName"):
            _tpl(store, t["TemplateName"])
        _check_dest(dest)
    else:
        if not (content["Raw"] or {}).get("Data"):
            raise _bad("Raw content requires Data.")
        if not dest:
            raise _bad("Raw sending requires a Destination.")
        _check_dest(dest)
    if not sender:
        raise _bad("FromEmailAddress is required.")
    _check_sender(store, sender)
    mid = _record(store, kinds[0], sender, dest, content, cs, {"Subject": ((content.get("Simple") or {}).get("Subject") or {}).get("Data", "")})
    store.persist()
    return _ok({"MessageId": mid})


def send_bulk_email(store, p, q, b):
    entries = _need(b, "BulkEmailEntries")
    default = _need(b, "DefaultContent")
    tpl = (default.get("Template") or {})
    if not tpl.get("TemplateName") and not tpl.get("TemplateArn"):
        raise _bad("DefaultContent.Template requires TemplateName or TemplateArn.")
    if tpl.get("TemplateName"):
        _tpl(store, tpl["TemplateName"])
    cs = b.get("ConfigurationSetName")
    _check_account(store, cs)
    sender = b.get("FromEmailAddress")
    if not sender:
        raise _bad("FromEmailAddress is required.")
    _check_sender(store, sender)
    if len(entries) > 50:
        raise _bad("A bulk send can have at most 50 entries.")
    results = []
    for e in entries:
        try:
            _check_dest(e.get("Destination") or {})
        except SesV2Error as err:
            results.append({"Status": "INVALID_PARAMETER", "Error": err.message})
            continue
        mid = _record(store, "Bulk", sender, e["Destination"], default, cs, {"Subject": ""})
        results.append({"Status": "SUCCESS", "MessageId": mid})
    store.persist()
    return _ok({"BulkEmailEntryResults": results})


# ── tags ───────────────────────────────────────────────────────────────────
def _known_arn(store, arn: str) -> bool:
    m = re.match(r"^arn:aws:ses:[^:]+:[^:]+:([a-z-]+)/(.+)$", arn or "")
    if not m:
        return False
    kind, name = m.groups()
    coll = {"identity": store.identities, "configuration-set": store.config_sets,
            "contact-list": store.contact_lists, "dedicated-ip-pool": store.ip_pools}.get(kind)
    if kind == "tenant":
        return name.split("/")[0] in store.tenants
    return coll is not None and name in coll


def tag_resource(store, p, q, b):
    arn = _need(b, "ResourceArn")
    if not _known_arn(store, arn):
        raise _notfound(f"Resource {arn} does not exist.")
    _tags_key(store, arn).update(_tags_in(_need(b, "Tags")))
    store.persist()
    return _ok()


def untag_resource(store, p, q, b):
    arn = q.get("resourcearn")
    if not arn or not _known_arn(store, arn):
        raise _notfound(f"Resource {arn} does not exist.")
    for k in q.get("tagkeys") or []:
        _tags_key(store, arn).pop(k, None)
    store.persist()
    return _ok()


def list_tags(store, p, q, b):
    arn = q.get("resourcearn")
    if not arn or not _known_arn(store, arn):
        raise _notfound(f"Resource {arn} does not exist.")
    return _ok({"Tags": _tags_out(store.tags.get(arn, {}))})


# ── account ────────────────────────────────────────────────────────────────
def get_account(store, p, q, b):
    a = store.account
    sent = len([m for m in store.messages])
    out = {"DedicatedIpAutoWarmupEnabled": a["DedicatedIpAutoWarmupEnabled"], "EnforcementStatus": "HEALTHY",
           "ProductionAccessEnabled": a["ProductionAccessEnabled"],
           "SendQuota": {"Max24HourSend": 50000.0 if a["ProductionAccessEnabled"] else 200.0,
                         "MaxSendRate": 14.0 if a["ProductionAccessEnabled"] else 1.0, "SentLast24Hours": float(sent)},
           "SendingEnabled": a["SendingEnabled"],
           "SuppressionAttributes": {"SuppressedReasons": list(a["SuppressedReasons"])},
           "VdmAttributes": {"VdmEnabled": a["VdmEnabled"]}}
    if a["Details"]:
        out["Details"] = a["Details"]
    if a["PricingAttributes"]:
        out["PricingAttributes"] = a["PricingAttributes"]
    return _ok(out)


def put_account_sending(store, p, q, b):
    store.account["SendingEnabled"] = bool(b.get("SendingEnabled", False))
    store.persist()
    return _ok()


def put_account_warmup(store, p, q, b):
    store.account["DedicatedIpAutoWarmupEnabled"] = bool(b.get("AutoWarmupEnabled", False))
    store.persist()
    return _ok()


def put_account_suppression(store, p, q, b):
    store.account["SuppressedReasons"] = b.get("SuppressedReasons") or []
    store.persist()
    return _ok()


def put_account_vdm(store, p, q, b):
    store.account["VdmEnabled"] = (b.get("VdmAttributes") or {}).get("VdmEnabled", "DISABLED")
    store.persist()
    return _ok()


def put_account_details(store, p, q, b):
    d = {k: b[k] for k in ("MailType", "WebsiteURL", "ContactLanguage", "UseCaseDescription",
                           "AdditionalContactEmailAddresses") if k in b}
    if b.get("MailType") not in ("MARKETING", "TRANSACTIONAL"):
        raise _bad("MailType must be MARKETING or TRANSACTIONAL")
    d["ReviewDetails"] = {"Status": "GRANTED", "CaseId": "vyomi-" + uuid.uuid4().hex[:8]}
    store.account["Details"] = d
    store.account["ProductionAccessEnabled"] = bool(b.get("ProductionAccessEnabled", False))
    store.persist()
    return _ok()


def get_dashboard(store, p, q, b):
    return _ok({"DashboardEnabled": store.account["DashboardEnabled"], "ActiveSubscribedDomains": [],
                "PendingExpirationSubscribedDomains": []})


def put_dashboard(store, p, q, b):
    store.account["DashboardEnabled"] = bool(b.get("DashboardEnabled", False))
    store.persist()
    return _ok()


# ── tenants ────────────────────────────────────────────────────────────────
def _tenant_view(t: dict) -> dict:
    return {"TenantName": t["TenantName"], "TenantId": t["TenantId"], "TenantArn": t["TenantArn"],
            "CreatedTimestamp": t["CreatedTimestamp"], "SendingStatus": t["SendingStatus"]}


def create_tenant(store, p, q, b):
    name = _need(b, "TenantName")
    if not _NAME_RE.match(name):
        raise _bad("TenantName may contain only letters, numbers, underscores and dashes (max 64).")
    if name in store.tenants:
        raise _exists(f"Tenant <{name}> already exists.")
    tid = "ten-" + uuid.uuid4().hex[:24]
    arn = _arn(store, "tenant", f"{name}/{tid}")
    t = {"TenantName": name, "TenantId": tid, "TenantArn": arn, "CreatedTimestamp": _epoch(), "SendingStatus": "ENABLED"}
    store.tenants[name] = t
    store.tags[arn] = {x["Key"]: x["Value"] for x in b.get("Tags") or []}
    store.persist()
    return _ok({**_tenant_view(t), "Tags": _tags_out(store.tags[arn])})


def get_tenant(store, p, q, b):
    name = _need(b, "TenantName")
    t = store.tenants.get(name)
    if t is None:
        raise _notfound(f"Tenant <{name}> does not exist.")
    return _ok({"Tenant": {**_tenant_view(t), "Tags": _tags_out(store.tags.get(t["TenantArn"], {}))}})


def list_tenants(store, p, q, b):
    items = [{k: t[k] for k in ("TenantName", "TenantId", "TenantArn", "CreatedTimestamp")}
             for _, t in sorted(store.tenants.items())]
    return _ok(_page(items, b, q, "Tenants"))


def delete_tenant(store, p, q, b):
    name = _need(b, "TenantName")
    t = store.tenants.get(name)
    if t is None:
        raise _notfound(f"Tenant <{name}> does not exist.")
    del store.tenants[name]
    store.tags.pop(t["TenantArn"], None)
    store.persist()
    return _ok()


# ── routing ────────────────────────────────────────────────────────────────
def _route(method, pattern, fn, op, also=()):
    rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")
    return [(m, rx, fn, op) for m in (method, *also)]


_R = (
    [(m, rx, fn, op) for spec in [
        # identities
        ("POST", "/identities", create_email_identity, "CreateEmailIdentity"),
        ("GET", "/identities", list_email_identities, "ListEmailIdentities"),
        ("POST", "/list-identities", list_email_identities, "ListEmailIdentities"),
        ("GET", "/identities/{EmailIdentity}", get_email_identity, "GetEmailIdentity"),
        ("DELETE", "/identities/{EmailIdentity}", delete_email_identity, "DeleteEmailIdentity"),
        ("PUT", "/identities/{EmailIdentity}/dkim", put_identity_dkim, "PutEmailIdentityDkimAttributes"),
        ("PUT", "/identities/{EmailIdentity}/dkim/signing", put_identity_dkim_signing, "PutEmailIdentityDkimSigningAttributes"),
        ("PUT", "/identities/{EmailIdentity}/feedback", put_identity_feedback, "PutEmailIdentityFeedbackAttributes"),
        ("PUT", "/identities/{EmailIdentity}/mail-from", put_identity_mail_from, "PutEmailIdentityMailFromAttributes"),
        ("PUT", "/identities/{EmailIdentity}/configuration-set", put_identity_config_set, "PutEmailIdentityConfigurationSetAttributes"),
        ("GET", "/identities/{EmailIdentity}/policies", get_identity_policies, "GetEmailIdentityPolicies"),
        ("POST", "/identities/{EmailIdentity}/policies/{PolicyName}", create_identity_policy, "CreateEmailIdentityPolicy"),
        ("PUT", "/identities/{EmailIdentity}/policies/{PolicyName}", update_identity_policy, "UpdateEmailIdentityPolicy"),
        ("DELETE", "/identities/{EmailIdentity}/policies/{PolicyName}", delete_identity_policy, "DeleteEmailIdentityPolicy"),
        # configuration sets
        ("POST", "/configuration-sets", create_config_set, "CreateConfigurationSet"),
        ("GET", "/configuration-sets", list_config_sets, "ListConfigurationSets"),
        ("POST", "/list-configuration-sets", list_config_sets, "ListConfigurationSets"),
        ("GET", "/configuration-sets/{ConfigurationSetName}", get_config_set, "GetConfigurationSet"),
        ("DELETE", "/configuration-sets/{ConfigurationSetName}", delete_config_set, "DeleteConfigurationSet"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/sending",
         _put_cs_option("SendingOptions", {"SendingEnabled": "SendingEnabled"}), "PutConfigurationSetSendingOptions"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/reputation-options",
         _put_cs_option("ReputationOptions", {"ReputationMetricsEnabled": "ReputationMetricsEnabled"}), "PutConfigurationSetReputationOptions"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/delivery-options",
         _put_cs_option("DeliveryOptions", {"TlsPolicy": "TlsPolicy", "SendingPoolName": "SendingPoolName", "MaxDeliverySeconds": "MaxDeliverySeconds"}),
         "PutConfigurationSetDeliveryOptions"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/tracking-options",
         _put_cs_option("TrackingOptions", {"CustomRedirectDomain": "CustomRedirectDomain", "HttpsPolicy": "HttpsPolicy"}), "PutConfigurationSetTrackingOptions"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/suppression-options",
         _put_cs_option("SuppressionOptions", {"SuppressedReasons": "SuppressedReasons"}), "PutConfigurationSetSuppressionOptions"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/vdm-options", put_cs_vdm, "PutConfigurationSetVdmOptions"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/archiving-options", put_cs_archiving, "PutConfigurationSetArchivingOptions"),
        ("POST", "/configuration-sets/{ConfigurationSetName}/event-destinations", create_event_destination, "CreateConfigurationSetEventDestination"),
        ("GET", "/configuration-sets/{ConfigurationSetName}/event-destinations", get_event_destinations, "GetConfigurationSetEventDestinations"),
        ("PUT", "/configuration-sets/{ConfigurationSetName}/event-destinations/{EventDestinationName}", update_event_destination, "UpdateConfigurationSetEventDestination"),
        ("DELETE", "/configuration-sets/{ConfigurationSetName}/event-destinations/{EventDestinationName}", delete_event_destination, "DeleteConfigurationSetEventDestination"),
        # templates
        ("POST", "/templates", create_template, "CreateEmailTemplate"),
        ("GET", "/templates", list_templates, "ListEmailTemplates"),
        ("GET", "/templates/{TemplateName}", get_template, "GetEmailTemplate"),
        ("PUT", "/templates/{TemplateName}", update_template, "UpdateEmailTemplate"),
        ("DELETE", "/templates/{TemplateName}", delete_template, "DeleteEmailTemplate"),
        ("POST", "/templates/{TemplateName}/render", test_render_template, "TestRenderEmailTemplate"),
        # contact lists
        ("POST", "/contact-lists", create_contact_list, "CreateContactList"),
        ("GET", "/contact-lists", list_contact_lists, "ListContactLists"),
        ("GET", "/contact-lists/{ContactListName}", get_contact_list, "GetContactList"),
        ("PUT", "/contact-lists/{ContactListName}", update_contact_list, "UpdateContactList"),
        ("DELETE", "/contact-lists/{ContactListName}", delete_contact_list, "DeleteContactList"),
        ("POST", "/contact-lists/{ContactListName}/contacts", create_contact, "CreateContact"),
        ("GET", "/contact-lists/{ContactListName}/contacts", list_contacts, "ListContacts"),
        ("POST", "/contact-lists/{ContactListName}/contacts/list", list_contacts, "ListContacts"),
        ("GET", "/contact-lists/{ContactListName}/contacts/{EmailAddress}", get_contact, "GetContact"),
        ("PUT", "/contact-lists/{ContactListName}/contacts/{EmailAddress}", update_contact, "UpdateContact"),
        ("DELETE", "/contact-lists/{ContactListName}/contacts/{EmailAddress}", delete_contact, "DeleteContact"),
        # suppression
        ("PUT", "/suppression/addresses", put_suppressed, "PutSuppressedDestination"),
        ("GET", "/suppression/addresses", list_suppressed, "ListSuppressedDestinations"),
        ("GET", "/suppression/addresses/{EmailAddress}", get_suppressed, "GetSuppressedDestination"),
        ("DELETE", "/suppression/addresses/{EmailAddress}", delete_suppressed, "DeleteSuppressedDestination"),
        # dedicated IP pools
        ("POST", "/dedicated-ip-pools", create_ip_pool, "CreateDedicatedIpPool"),
        ("GET", "/dedicated-ip-pools", list_ip_pools, "ListDedicatedIpPools"),
        ("GET", "/dedicated-ip-pools/{PoolName}", get_ip_pool, "GetDedicatedIpPool"),
        ("DELETE", "/dedicated-ip-pools/{PoolName}", delete_ip_pool, "DeleteDedicatedIpPool"),
        # sending
        ("POST", "/outbound-emails", send_email, "SendEmail"),
        ("POST", "/outbound-bulk-emails", send_bulk_email, "SendBulkEmail"),
        # tags
        ("POST", "/tags", tag_resource, "TagResource"),
        ("DELETE", "/tags", untag_resource, "UntagResource"),
        ("GET", "/tags", list_tags, "ListTagsForResource"),
        # account
        ("GET", "/account", get_account, "GetAccount"),
        ("PUT", "/account/sending", put_account_sending, "PutAccountSendingAttributes"),
        ("PUT", "/account/dedicated-ips/warmup", put_account_warmup, "PutAccountDedicatedIpWarmupAttributes"),
        ("PUT", "/account/suppression", put_account_suppression, "PutAccountSuppressionAttributes"),
        ("PUT", "/account/vdm", put_account_vdm, "PutAccountVdmAttributes"),
        ("POST", "/account/details", put_account_details, "PutAccountDetails"),
        ("GET", "/deliverability-dashboard", get_dashboard, "GetDeliverabilityDashboardOptions"),
        ("PUT", "/deliverability-dashboard", put_dashboard, "PutDeliverabilityDashboardOption"),
        # tenants
        ("POST", "/tenants", create_tenant, "CreateTenant"),
        ("POST", "/tenants/get", get_tenant, "GetTenant"),
        ("POST", "/tenants/list", list_tenants, "ListTenants"),
        ("POST", "/tenants/delete", delete_tenant, "DeleteTenant"),
    ] for (m, rx, fn, op) in _route(*spec)]
)

OPERATIONS = sorted({op for _, _, _, op in _R})


def is_sesv2_path(path: str) -> bool:
    return path == PREFIX or path.startswith(PREFIX + "/")


def dispatch(store: SesV2Store, method: str, path: str, query: dict | None, headers: dict | None,
             body: bytes | None) -> SesV2Response:
    """Serve ONE REST-JSON request. `query` is a flat {name: value} dict (values may be lists)."""
    method = (method or "GET").upper()
    sub = path[len(PREFIX):] if path.startswith(PREFIX) else path
    sub = sub.split("?", 1)[0].rstrip("/") or "/"
    q = {str(k).lower(): v for k, v in (query or {}).items()}
    q = {k: ([v] if isinstance(v, str) else list(v)) if k in ("tagkeys", "reason") else (v[0] if isinstance(v, (list, tuple)) else v)
         for k, v in q.items()}
    seen_path = False
    for meth, rx, fn, _op in _R:
        m = rx.match(sub)
        if not m:
            continue
        seen_path = True
        if meth != method:
            continue
        try:
            raw = body or b""
            try:
                parsed = json.loads(raw) if raw.strip() else {}
            except ValueError:
                raise _bad("Malformed JSON request body.")
            if not isinstance(parsed, dict):
                raise _bad("Request body must be a JSON object.")
            params = {k: unquote(v) for k, v in m.groupdict().items()}
            return fn(store, params, q, parsed)
        except SesV2Error as e:
            return _error(e.code, e.message, e.status)
    if seen_path:
        return _error("MethodNotAllowedException", f"The {method} method is not allowed for {PREFIX}{sub}.", 405)
    return _error("NotFoundException", f"The action for {PREFIX}{sub} is not valid for this web service.", 404)


# ── console REST view (flat, shared by the offline server and Nano) ────────
def _ts(v) -> str:
    return datetime.fromtimestamp(float(v), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def console_identity(store, i: dict) -> dict:
    dk = _identity_dkim_view(i)
    mf = i["MailFromAttributes"]
    return {
        "identity": i["EmailIdentity"], "type": "Email address" if i["IdentityType"] == "EMAIL_ADDRESS" else "Domain",
        "status": "Verified" if i["VerifiedForSendingStatus"] else "Pending verification",
        "sending": "Enabled" if i["SendingEnabled"] else "Disabled",
        "dkim": "Successful" if dk.get("Status") == "SUCCESS" and dk.get("SigningEnabled") else "Not configured",
        "mail_from": mf["MailFromDomain"] or "Default (amazonses.com)",
        "config_set": i["ConfigurationSetName"] or "None",
        "region": store.region, "created": i["created"],
        "arn": _arn(store, "identity", i["EmailIdentity"]),
        "feedback_forwarding": "Enabled" if i["FeedbackForwardingStatus"] else "Disabled",
        "dkim_tokens": ", ".join(dk.get("Tokens") or []) or "None",
        "policies": len(i["Policies"]),
        "tags": dict(store.tags.get(_arn(store, "identity", i["EmailIdentity"]), {})),
    }


def console_list(store) -> dict:
    return {"items": [console_identity(store, i) for _, i in sorted(store.identities.items())]}


def console_create(store, body: dict) -> dict:
    name = (body.get("identity") or body.get("name") or "").strip()
    payload = {"EmailIdentity": name}
    if body.get("config_set") and body["config_set"] != "None":
        payload["ConfigurationSetName"] = body["config_set"]
    r = create_email_identity(store, {}, {}, payload)
    if r.status >= 300:
        raise SesV2Error(r.headers.get("x-amzn-ErrorType", "Error"), json.loads(r.body).get("message", ""), r.status)
    return console_identity(store, store.identities[name])


def console_get(store, name: str) -> dict:
    return console_identity(store, _ident(store, name))


def console_delete(store, name: str) -> dict:
    delete_email_identity(store, {"EmailIdentity": name}, {}, {})
    return {"deleted": name}


CHILD_KINDS = ("configuration-sets", "templates", "contact-lists", "suppression", "sent-emails")


def console_children(store, kind: str) -> dict:
    if kind == "configuration-sets":
        rows = [{"name": n, "sending": "Enabled" if c["SendingOptions"].get("SendingEnabled", True) else "Disabled",
                 "reputation_metrics": "Enabled" if c["ReputationOptions"].get("ReputationMetricsEnabled") else "Disabled",
                 "tls_policy": c["DeliveryOptions"].get("TlsPolicy", "OPTIONAL"),
                 "event_destinations": len(c["event_destinations"]), "created": c["created"]}
                for n, c in sorted(store.config_sets.items())]
    elif kind == "templates":
        rows = [{"name": n, "subject": t["TemplateContent"].get("Subject") or "(none)",
                 "has_html": "Yes" if t["TemplateContent"].get("Html") else "No",
                 "has_text": "Yes" if t["TemplateContent"].get("Text") else "No", "created": t["created"]}
                for n, t in sorted(store.templates.items())]
    elif kind == "contact-lists":
        rows = [{"name": n, "description": c["Description"] or "No description", "topics": len(c["Topics"]),
                 "contacts": len(c["contacts"]), "last_updated": _ts(c["LastUpdatedTimestamp"])}
                for n, c in sorted(store.contact_lists.items())]
    elif kind == "suppression":
        rows = [{"name": n, "reason": s["Reason"].title(), "last_updated": _ts(s["LastUpdateTime"])}
                for n, s in sorted(store.suppression.items())]
    elif kind == "sent-emails":
        rows = [{"name": m["MessageId"], "from": m["From"], "to": ", ".join(m["To"]) or "-",
                 "subject": m.get("Subject") or f"({m['Kind']})", "config_set": m["ConfigurationSetName"] or "None",
                 "sent": m["sent"]} for m in reversed(store.messages)]
    else:
        raise _notfound(f"Unknown collection {kind}")
    return {"items": rows}


def console_child_create(store, kind: str, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if kind == "configuration-sets":
        create_config_set(store, {}, {}, {"ConfigurationSetName": name,
                                          "ReputationOptions": {"ReputationMetricsEnabled": True},
                                          "DeliveryOptions": {"TlsPolicy": body.get("tls_policy") or "OPTIONAL"}})
    elif kind == "templates":
        create_template(store, {}, {}, {"TemplateName": name, "TemplateContent": {
            "Subject": body.get("subject") or "Hello {{name}}", "Text": "Hello {{name}},\nWelcome to Vyomi.",
            "Html": "<p>Hello {{name}},</p><p>Welcome to Vyomi.</p>"}})
    elif kind == "contact-lists":
        create_contact_list(store, {}, {}, {"ContactListName": name, "Description": body.get("description") or "",
                                            "Topics": [{"TopicName": "updates", "DisplayName": "Product updates",
                                                        "Description": "Product news", "DefaultSubscriptionStatus": "OPT_IN"}]})
    elif kind == "suppression":
        put_suppressed(store, {}, {}, {"EmailAddress": name, "Reason": (body.get("reason") or "BOUNCE").upper()})
    else:
        raise _bad(f"Cannot create {kind}")
    return {"created": name}


def console_child_delete(store, kind: str, name: str) -> dict:
    fn = {"configuration-sets": (delete_config_set, "ConfigurationSetName"), "templates": (delete_template, "TemplateName"),
          "contact-lists": (delete_contact_list, "ContactListName"), "suppression": (delete_suppressed, "EmailAddress")}.get(kind)
    if fn is None:
        raise _bad(f"Cannot delete {kind}")
    fn[0](store, {fn[1]: name}, {}, {})
    return {"deleted": name}


def console_dispatch(store, method: str, path: str, query: dict | None, body: dict | None):
    """Serve `/api/aws/sesv2/...`; returns (status, json-able). Shared by server + Nano."""
    sub = path.split("/api/aws/sesv2", 1)[-1].strip("/")
    parts = [unquote(x) for x in sub.split("/") if x]
    body = body or {}
    try:
        if parts[:1] == ["identities"]:
            if len(parts) == 1:
                if method == "GET":
                    return 200, console_list(store)
                if method == "POST":
                    return 200, console_create(store, body)
            elif len(parts) == 2:
                if method == "GET":
                    return 200, console_get(store, parts[1])
                if method == "DELETE":
                    return 200, console_delete(store, parts[1])
        elif parts and parts[0] in CHILD_KINDS:
            if len(parts) == 1 and method == "GET":
                return 200, console_children(store, parts[0])
            if len(parts) == 1 and method == "POST":
                return 200, console_child_create(store, parts[0], body)
            if len(parts) == 2 and method == "DELETE":
                return 200, console_child_delete(store, parts[0], parts[1])
        return 404, {"error": f"No such route: {method} {path}"}
    except SesV2Error as e:
        return e.status, {"error": e.message, "code": e.code}
