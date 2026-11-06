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

Backend: Mailpit (shared SMTP container) offline, in-process in Nano. SendEmail /
SendBulkEmail / the SES SMTP interface validate the request exactly as SES does (verified
sender, content shape, configuration set, suppression list), build the real RFC 5322 message
(HTML, attachments, headers, templates), record it in the store ("sent mailbox") and hand it
to `store.mailer` — set only by the offline appliance (core/ses_mail.py: Mailpit over SMTP, an
optional per-space relay to the user's own SMTP server, the SES SMTP front end and the inbound
listener/IMAP poll feeding the SES v1 receipt rules below). With no mailer (Nano: a browser
cannot speak SMTP) the message is recorded and its SES events are emitted, nothing more.

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

import base64
import hashlib
import hmac
import json
import re
import uuid
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import formatdate, getaddresses
from xml.sax.saxutils import escape as _xesc
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
        self.smtp_credentials: dict[str, dict] = {}   # SES SMTP username (access key id) → {hash}
        self.receipt: dict = {}                       # SES v1 receipt rules: {sets, active, log}
        self.mail_settings: dict = {}                 # {relay: {...}, imap: {...}}  (passwords sealed)

    mailer = None   # offline-only delivery object (core/ses_mail.py); None in Nano / unit tests

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


def _record(store, kind: str, sender: str, dest: dict, content: dict, cs, extra=None) -> dict:
    mid = f"{uuid.uuid4().hex[:16]}-{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:4]}-000000"
    msg = {"MessageId": mid, "Kind": kind, "From": sender, "To": list(dest.get("ToAddresses") or []),
           "Cc": list(dest.get("CcAddresses") or []), "Bcc": list(dest.get("BccAddresses") or []),
           "ConfigurationSetName": cs or "", "Content": content, "sent": _now()}
    if extra:
        msg.update(extra)
    store.messages.append(msg)
    del store.messages[:-500]
    return msg


# ── message composition (the real RFC 5322 bytes SES would put on the wire) ──
def _b64(data) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    try:
        return base64.b64decode(str(data), validate=False)
    except Exception:
        return str(data).encode()


def _message_id_header(mid: str) -> str:
    return f"<{mid}@email.amazonses.com>"


def _fill_body(m: EmailMessage, text: str, html: str) -> None:
    if html and text:
        m.set_content(text)
        m.add_alternative(html, subtype="html")
    elif html:
        m.set_content(html, subtype="html")
    else:
        m.set_content(text or "")


def _template_content(store, tpl: dict, data_json) -> tuple[str, str, str]:
    t = _tpl(store, tpl["TemplateName"]) if tpl.get("TemplateName") else _tpl(store, str(tpl.get("TemplateArn", "")).rsplit("/", 1)[-1])
    try:
        data = json.loads(data_json) if data_json else {}
    except ValueError:
        raise _bad("TemplateData must be valid JSON.")
    c = t["TemplateContent"]
    return _render(c.get("Subject", ""), data), _render(c.get("Text", ""), data), _render(c.get("Html", ""), data)


def _compose(store, kind: str, sender: str, dest: dict, content: dict, mid: str, reply_to=None,
             extra_headers=None) -> bytes:
    if kind == "Raw":
        raw = _b64(content["Raw"]["Data"])
        head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
        if not re.search(rb"(?im)^message-id:", head):
            raw = f"Message-ID: {_message_id_header(mid)}\r\n".encode() + raw
        return raw
    m = EmailMessage()
    if kind == "Template":
        subject, text, html = _template_content(store, content["Template"], content["Template"].get("TemplateData"))
        hdrs, atts = content["Template"].get("Headers") or [], content["Template"].get("Attachments") or []
    else:
        s = content["Simple"]
        subject = (s.get("Subject") or {}).get("Data", "")
        body = s.get("Body") or {}
        text, html = (body.get("Text") or {}).get("Data", ""), (body.get("Html") or {}).get("Data", "")
        hdrs, atts = s.get("Headers") or [], s.get("Attachments") or []
    m["Subject"] = subject
    m["From"] = sender
    if dest.get("ToAddresses"):
        m["To"] = ", ".join(dest["ToAddresses"])
    if dest.get("CcAddresses"):
        m["Cc"] = ", ".join(dest["CcAddresses"])
    if reply_to:
        m["Reply-To"] = ", ".join(reply_to)
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = _message_id_header(mid)
    for h in hdrs:
        if h.get("Name") and h["Name"].lower() not in ("from", "to", "cc", "subject", "message-id"):
            m[h["Name"]] = h.get("Value", "")
    for k, v in (extra_headers or {}).items():
        m[k] = v
    _fill_body(m, text, html)
    for a in atts:
        ctype = a.get("ContentType") or "application/octet-stream"
        main, _, sub = ctype.partition("/")
        m.add_attachment(_b64(a.get("RawContent", b"")), maintype=main or "application", subtype=sub or "octet-stream",
                         filename=a.get("FileName"), disposition=(a.get("ContentDisposition") or "attachment").lower(),
                         cid=a.get("ContentId"))
    return m.as_bytes()


# ── events + delivery ──────────────────────────────────────────────────────
SIMULATOR_DOMAIN = "simulator.amazonses.com"
_EVENT_TYPES = {"Send": "SEND", "Reject": "REJECT", "Bounce": "BOUNCE", "Complaint": "COMPLAINT",
                "Delivery": "DELIVERY", "DeliveryDelay": "DELIVERY_DELAY"}


def _suppress(store, addr: str, reason: str) -> None:
    store.suppression.setdefault(addr, {"EmailAddress": addr, "Reason": reason, "LastUpdateTime": _epoch(),
                                        "Attributes": {}})


def _identity_verified(store, addr: str) -> bool:
    a = _sender_domain(addr)
    dom = a.split("@", 1)[-1]
    for name, i in store.identities.items():
        n = name.lower()
        if i.get("VerifiedForSendingStatus") and (n == a or n == dom):
            return True
    return False


def _emit_destinations(store, msg: dict, ev: dict) -> None:
    """Configuration-set event destinations: SNS is published for real (when the appliance
    provides a mailer); every matching destination is noted on the message."""
    cs = store.config_sets.get(msg.get("ConfigurationSetName") or "")
    if not cs:
        return
    et = _EVENT_TYPES.get(ev["Type"], ev["Type"].upper())
    for name, d in cs["event_destinations"].items():
        if not d.get("Enabled") or et not in (d.get("MatchingEventTypes") or []):
            continue
        payload = {"eventType": ev["Type"], "mail": {"timestamp": msg["sent"], "source": msg["From"],
                   "messageId": msg["MessageId"], "destination": msg["To"] + msg["Cc"] + msg["Bcc"]},
                   ev["Type"].lower(): {k: v for k, v in ev.items() if k not in ("Type",)}}
        topic = (d.get("SnsDestination") or {}).get("TopicArn")
        if topic and store.mailer is not None:
            try:
                store.mailer.publish_sns(topic, payload)
            except Exception as e:   # best effort, like SES's async event publishing
                msg.setdefault("EventErrors", []).append(f"{name}: {e}")
        msg.setdefault("EventDestinations", [])
        if name not in msg["EventDestinations"]:
            msg["EventDestinations"].append(name)


def _relay_split(store, rcpts: list) -> tuple[list, list, str]:
    """Which recipients go to the user's real SMTP relay: sandbox accounts relay only to
    verified identities; production access lifts that, subject to a per-hour cap."""
    cfg = (store.mail_settings or {}).get("relay") or {}
    if not cfg.get("enabled"):
        return [], [], ""
    if store.account.get("ProductionAccessEnabled"):
        cap = int(cfg.get("hourly_cap") or 200)
        now = _epoch()
        log = [t for t in cfg.get("log", []) if now - t < 3600]
        room = max(0, cap - len(log))
        ok, over = list(rcpts[:room]), list(rcpts[room:])
        cfg["log"] = log + [now] * len(ok)
        return ok, over, f"Hourly relay cap of {cap} reached"
    ok = [r for r in rcpts if _identity_verified(store, r)]
    return ok, [r for r in rcpts if r not in ok], "Account is in the SES sandbox: recipient is not a verified identity"


def _deliver(store, msg: dict, raw: bytes, rcpts: list) -> None:
    """Apply suppression / the mailbox simulator, hand the rest to the mailer, record SES events."""
    ts = _now()
    events = [{"Type": "Send", "Timestamp": ts}]
    deliver_to, suppressed = [], []
    for r in rcpts:
        a = _sender_domain(r)
        local, _, dom = a.partition("@")
        if dom == SIMULATOR_DOMAIN:
            if local == "bounce":
                events.append({"Type": "Bounce", "Timestamp": ts, "BounceType": "Permanent", "BounceSubType": "General",
                               "Recipients": [a], "Diagnostic": "smtp; 550 5.1.1 user unknown (mailbox simulator)"})
                _suppress(store, a, "BOUNCE")
            elif local == "complaint":
                events.append({"Type": "Complaint", "Timestamp": ts, "Recipients": [a], "ComplaintFeedbackType": "abuse"})
                _suppress(store, a, "COMPLAINT")
            elif local == "suppressionlist":
                events.append({"Type": "Bounce", "Timestamp": ts, "BounceType": "Permanent",
                               "BounceSubType": "OnAccountSuppressionList", "Recipients": [a],
                               "Diagnostic": "Amazon SES did not send the message to this address because it is on the suppression list"})
                suppressed.append(a)
            else:   # success@ / ooto@: accepted by the simulator, never a real mailbox
                events.append({"Type": "Delivery", "Timestamp": ts, "Recipients": [a],
                               "SmtpResponse": "250 2.6.0 Message accepted by the SES mailbox simulator"})
            continue
        if a in store.suppression:
            suppressed.append(a)
            events.append({"Type": "Bounce", "Timestamp": ts, "BounceType": "Permanent",
                           "BounceSubType": "OnAccountSuppressionList", "Recipients": [a],
                           "Diagnostic": "Amazon SES did not send the message to this address because it is on the suppression list"})
            continue
        deliver_to.append(a)
    delivery = {"Status": "Simulated", "InboxId": "", "InboxUrl": "", "Relayed": [], "Suppressed": suppressed}
    if deliver_to:
        relay_ok, relay_no, why = _relay_split(store, deliver_to)
        res = None
        if store.mailer is not None:
            res = store.mailer.deliver(msg, raw, _sender_domain(msg["From"]), deliver_to, relay_ok)
        if res is None:   # Nano: recorded only
            delivery["Status"] = "Recorded (no SMTP in the browser)"
            events.append({"Type": "Delivery", "Timestamp": ts, "Recipients": deliver_to,
                           "SmtpResponse": "250 2.0.0 Ok: recorded"})
        elif res.get("error"):
            delivery["Status"] = "Failed"
            events.append({"Type": "Bounce", "Timestamp": ts, "BounceType": "Transient", "BounceSubType": "General",
                           "Recipients": deliver_to, "Diagnostic": "smtp; " + str(res["error"])})
        else:
            delivery.update(Status="Delivered", InboxId=res.get("inbox_id") or "", InboxUrl=res.get("inbox_url") or "")
            events.append({"Type": "Delivery", "Timestamp": ts, "Recipients": deliver_to,
                           "SmtpResponse": "250 2.0.0 Ok: queued in the local inbox"})
            delivery["Relayed"] = list(res.get("relayed") or [])
            for addr, err in (res.get("relay_failed") or {}).items():
                events.append({"Type": "Bounce", "Timestamp": ts, "BounceType": "Transient", "BounceSubType": "General",
                               "Recipients": [addr], "Diagnostic": "smtp; " + str(err)})
        for addr in relay_no:
            events.append({"Type": "Reject", "Timestamp": ts, "Recipients": [addr], "Reason": why,
                           "Note": "A copy is in the local inbox; not relayed to a real mailbox"})
    msg["Events"] = events
    msg["Delivery"] = delivery
    for ev in events:
        _emit_destinations(store, msg, ev)


def _reply_to(b: dict):
    return b.get("ReplyToAddresses") or None


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
    subject = ((content.get("Simple") or {}).get("Subject") or {}).get("Data", "")
    msg = _record(store, kinds[0], sender, dest, content, cs, {"Subject": subject})
    raw = _compose(store, kinds[0], sender, dest, content, msg["MessageId"], _reply_to(b),
                   {"X-SES-CONFIGURATION-SET": cs} if cs else None)
    if kinds[0] == "Template":
        msg["Subject"] = (message_from_bytes(raw).get("Subject") or "")
    rcpts = list(dest.get("ToAddresses") or []) + list(dest.get("CcAddresses") or []) + list(dest.get("BccAddresses") or [])
    _deliver(store, msg, raw, rcpts)
    store.persist()
    return _ok({"MessageId": msg["MessageId"]})


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
        rep = ((e.get("ReplacementEmailContent") or {}).get("ReplacementTemplate") or {}).get("ReplacementTemplateData")
        body = {"Template": {**tpl, "TemplateData": rep or tpl.get("TemplateData") or "{}",
                             "Headers": e.get("ReplacementHeaders") or tpl.get("Headers") or []}}
        msg = _record(store, "Bulk", sender, e["Destination"], default, cs, {"Subject": ""})
        raw = _compose(store, "Template", sender, e["Destination"], body, msg["MessageId"], _reply_to(b),
                       {"X-SES-CONFIGURATION-SET": cs} if cs else None)
        msg["Subject"] = message_from_bytes(raw).get("Subject") or ""
        d = e["Destination"]
        _deliver(store, msg, raw, list(d.get("ToAddresses") or []) + list(d.get("CcAddresses") or []) + list(d.get("BccAddresses") or []))
        results.append({"Status": "SUCCESS", "MessageId": msg["MessageId"]})
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


# ═══════════════════════════════════════════════════════════════════════════
# SES SMTP interface + inbound mail (the SMTP/IMAP sockets live in core/ses_mail.py,
# offline only; everything they decide is decided here so the rules are one piece of code)
# ═══════════════════════════════════════════════════════════════════════════
def smtp_password(secret_access_key: str, region: str = REGION) -> str:
    """SES SMTP password from an IAM secret access key — the documented v4 derivation."""
    def sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()
    sig = sign(("AWS4" + secret_access_key).encode(), "11111111")
    for m in (region, "ses", "aws4_request", "SendRawEmail"):
        sig = sign(sig, m)
    return base64.b64encode(b"\x04" + sig).decode()


def smtp_register(store, access_key_id: str, secret_access_key: str) -> dict:
    if not access_key_id or not secret_access_key:
        raise _bad("AccessKeyId and SecretAccessKey are required.")
    pw = smtp_password(secret_access_key, store.region)
    store.smtp_credentials[access_key_id] = {"hash": hashlib.sha256(pw.encode()).hexdigest(), "created": _now()}
    store.persist()
    return {"username": access_key_id, "password": pw, "region": store.region}


def smtp_authenticate(store, username: str, password: str, secret_lookup=None) -> bool:
    c = store.smtp_credentials.get(username)
    if c:
        return hmac.compare_digest(c["hash"], hashlib.sha256((password or "").encode()).hexdigest())
    if secret_lookup:
        secret = secret_lookup(username)
        if secret:
            return hmac.compare_digest(smtp_password(secret, store.region), password or "")
    return False


class SmtpRefused(Exception):
    def __init__(self, code: int, text: str) -> None:
        super().__init__(text)
        self.code, self.text = code, text


def smtp_ingest(store, mail_from: str, rcpts: list, raw: bytes) -> str:
    """One message submitted through the SES SMTP interface (already authenticated).
    Applies the SES rules and returns the SMTP reply text; raises SmtpRefused."""
    try:
        parsed = message_from_bytes(raw)
        frm = getaddresses([parsed.get("From", "")])
        sender = (frm[0][1] if frm and frm[0][1] else mail_from) or ""
        cs = parsed.get("X-SES-CONFIGURATION-SET") or None
        if cs and cs not in store.config_sets:
            raise SmtpRefused(554, f"Configuration set <{cs}> does not exist.")
        _check_account(store, cs)
        _check_sender(store, sender)
        if not rcpts:
            raise SmtpRefused(554, "Must specify at least one recipient address.")
        if len(rcpts) > 50:
            raise SmtpRefused(554, "Too many recipients; a message can have at most 50.")
        tol = {x.lower() for _, x in getaddresses(parsed.get_all("To", []))}
        ccl = {x.lower() for _, x in getaddresses(parsed.get_all("Cc", []))}
        tos = [r for r in rcpts if r.lower() in tol]
        ccs = [r for r in rcpts if r.lower() in ccl and r not in tos]
        dest = {"ToAddresses": tos, "CcAddresses": ccs, "BccAddresses": [r for r in rcpts if r not in tos and r not in ccs]}
        msg = _record(store, "Smtp", sender, dest, {"Raw": {"Data": ""}}, cs, {"Subject": parsed.get("Subject", "")})
        msg["Content"] = {"Raw": {"Data": "(submitted over SMTP)"}}
        head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
        if not re.search(rb"(?im)^message-id:", head):
            raw = f"Message-ID: {_message_id_header(msg['MessageId'])}\r\n".encode() + raw
        _deliver(store, msg, raw, list(rcpts))
        store.persist()
        return f"Ok {msg['MessageId']}"
    except SesV2Error as e:
        raise SmtpRefused(554, f"Message rejected: {e.message}")


# ── SES v1 (Query protocol): receipt rule sets + identity verification ─────
_V1_NS = "http://ses.amazonaws.com/doc/2010-12-01/"


def _rcpt(store) -> dict:
    r = store.receipt
    r.setdefault("sets", {})
    r.setdefault("active", "")
    r.setdefault("log", [])
    return r


def _qtree(params: dict) -> dict:
    """Flatten `Rule.Actions.member.1.S3Action.BucketName=…` into nested dicts / lists."""
    root: dict = {}
    for k, v in params.items():
        cur = root
        parts = k.split(".")
        for pt in parts[:-1]:
            cur = cur.setdefault(pt, {})
        cur[parts[-1]] = v

    def fix(n):
        if isinstance(n, dict):
            if set(n) == {"member"} and isinstance(n["member"], dict):
                return [fix(n["member"][i]) for i in sorted(n["member"], key=lambda x: int(x) if str(x).isdigit() else 0)]
            return {k: fix(v) for k, v in n.items()}
        if n in ("true", "false"):
            return n == "true"
        return n
    return fix(root)


def _xml_of(tag: str, v) -> str:
    if isinstance(v, dict):
        return f"<{tag}>" + "".join(_xml_of(k, x) for k, x in v.items()) + f"</{tag}>"
    if isinstance(v, list):
        return f"<{tag}>" + "".join(_xml_of("member", x) for x in v) + f"</{tag}>"
    if isinstance(v, bool):
        v = "true" if v else "false"
    return f"<{tag}>{_xesc(str(v))}</{tag}>"


def _v1_ok(action: str, result: dict | None = None) -> SesV2Response:
    inner = "".join(_xml_of(k, x) for k, x in (result or {}).items())
    body = (f'<{action}Response xmlns="{_V1_NS}"><{action}Result>{inner}</{action}Result>'
            f"<ResponseMetadata><RequestId>{uuid.uuid4()}</RequestId></ResponseMetadata></{action}Response>")
    return SesV2Response(200, body.encode(), {}, "text/xml")


def _v1_err(code: str, msg: str, status: int = 400) -> SesV2Response:
    body = (f'<ErrorResponse xmlns="{_V1_NS}"><Error><Type>Sender</Type><Code>{code}</Code>'
            f"<Message>{_xesc(msg)}</Message></Error><RequestId>{uuid.uuid4()}</RequestId></ErrorResponse>")
    return SesV2Response(status, body.encode(), {}, "text/xml")


_ACTION_KINDS = ("S3Action", "LambdaAction", "SNSAction", "StopAction", "BounceAction", "AddHeaderAction", "WorkmailAction")


def _norm_rule(rule: dict) -> dict:
    if not rule.get("Name") or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", str(rule["Name"])):
        raise SesV2Error("InvalidParameterValue", "Rule name must be alphanumeric, '-', '_' or '.', and start with a letter or digit.")
    acts = rule.get("Actions") or []
    if not isinstance(acts, list):
        acts = [acts]
    for a in acts:
        kinds = [k for k in a if k in _ACTION_KINDS]
        if len(kinds) != 1:
            raise SesV2Error("InvalidParameterValue", "Each action must contain exactly one action type.")
    rec = rule.get("Recipients") or []
    return {"Name": rule["Name"], "Enabled": bool(rule.get("Enabled", False)),
            "TlsPolicy": rule.get("TlsPolicy") or "Optional",
            "Recipients": rec if isinstance(rec, list) else [rec],
            "Actions": acts, "ScanEnabled": bool(rule.get("ScanEnabled", False))}


def _rs(store, name: str) -> dict:
    s = _rcpt(store)["sets"].get(name)
    if s is None:
        raise SesV2Error("RuleSetDoesNotExist", f"Rule set does not exist: {name}")
    return s


def _find_rule(rs: dict, name: str) -> int:
    for i, r in enumerate(rs["Rules"]):
        if r["Name"] == name:
            return i
    raise SesV2Error("RuleDoesNotExist", f"Rule does not exist: {name}")


def _v1_dispatch(store, a: str, t: dict) -> SesV2Response:
    r = _rcpt(store)
    if a == "CreateReceiptRuleSet":
        n = t.get("RuleSetName")
        if not n or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", str(n)):
            raise SesV2Error("InvalidParameterValue", "Invalid RuleSetName.")
        if n in r["sets"]:
            raise SesV2Error("AlreadyExists", f"Rule set already exists: {n}")
        r["sets"][n] = {"Name": n, "CreatedTimestamp": _now(), "Rules": []}
        return _v1_ok(a)
    if a == "CloneReceiptRuleSet":
        src = _rs(store, t.get("OriginalRuleSetName", ""))
        n = t.get("RuleSetName")
        if n in r["sets"]:
            raise SesV2Error("AlreadyExists", f"Rule set already exists: {n}")
        r["sets"][n] = {"Name": n, "CreatedTimestamp": _now(), "Rules": json.loads(json.dumps(src["Rules"]))}
        return _v1_ok(a)
    if a == "DeleteReceiptRuleSet":
        n = t.get("RuleSetName", "")
        if n == r["active"]:
            raise SesV2Error("CannotDelete", f"Cannot delete the active rule set: {n}")
        r["sets"].pop(n, None)
        return _v1_ok(a)
    if a == "ListReceiptRuleSets":
        return _v1_ok(a, {"RuleSets": [{"Name": s["Name"], "CreatedTimestamp": s["CreatedTimestamp"]}
                                       for s in sorted(r["sets"].values(), key=lambda x: x["Name"])]})
    if a == "DescribeReceiptRuleSet":
        s = _rs(store, t.get("RuleSetName", ""))
        return _v1_ok(a, {"Metadata": {"Name": s["Name"], "CreatedTimestamp": s["CreatedTimestamp"]}, "Rules": s["Rules"]})
    if a == "DescribeActiveReceiptRuleSet":
        if not r["active"]:
            return _v1_ok(a)
        s = _rs(store, r["active"])
        return _v1_ok(a, {"Metadata": {"Name": s["Name"], "CreatedTimestamp": s["CreatedTimestamp"]}, "Rules": s["Rules"]})
    if a == "SetActiveReceiptRuleSet":
        n = t.get("RuleSetName") or ""
        if n:
            _rs(store, n)
        r["active"] = n
        return _v1_ok(a)
    if a == "CreateReceiptRule":
        s = _rs(store, t.get("RuleSetName", ""))
        rule = _norm_rule(t.get("Rule") or {})
        if any(x["Name"] == rule["Name"] for x in s["Rules"]):
            raise SesV2Error("AlreadyExists", f"Rule already exists: {rule['Name']}")
        after = t.get("After")
        pos = _find_rule(s, after) + 1 if after else len(s["Rules"])
        s["Rules"].insert(pos, rule)
        return _v1_ok(a)
    if a == "UpdateReceiptRule":
        s = _rs(store, t.get("RuleSetName", ""))
        rule = _norm_rule(t.get("Rule") or {})
        s["Rules"][_find_rule(s, rule["Name"])] = rule
        return _v1_ok(a)
    if a == "DescribeReceiptRule":
        s = _rs(store, t.get("RuleSetName", ""))
        return _v1_ok(a, {"Rule": s["Rules"][_find_rule(s, t.get("RuleName", ""))]})
    if a == "DeleteReceiptRule":
        s = _rs(store, t.get("RuleSetName", ""))
        del s["Rules"][_find_rule(s, t.get("RuleName", ""))]
        return _v1_ok(a)
    if a == "ReorderReceiptRuleSet":
        s = _rs(store, t.get("RuleSetName", ""))
        names = t.get("RuleNames") or []
        by = {x["Name"]: x for x in s["Rules"]}
        if sorted(names) != sorted(by):
            raise SesV2Error("RuleDoesNotExist", "RuleNames must list every rule in the rule set exactly once.")
        s["Rules"] = [by[n] for n in names]
        return _v1_ok(a)
    # identities (v1 view over the same store as v2)
    if a in ("VerifyEmailIdentity", "VerifyDomainIdentity", "VerifyEmailAddress"):
        n = t.get("EmailAddress") or t.get("Domain")
        if n and n not in store.identities:
            create_email_identity(store, {}, {}, {"EmailIdentity": n})
        return _v1_ok(a, {"VerificationToken": uuid.uuid4().hex} if a == "VerifyDomainIdentity" else None)
    if a == "ListIdentities":
        want = t.get("IdentityType")
        names = sorted(n for n, i in store.identities.items()
                       if not want or i["IdentityType"] == {"EmailAddress": "EMAIL_ADDRESS", "Domain": "DOMAIN"}.get(want))
        return _v1_ok(a, {"Identities": names})
    if a == "DeleteIdentity":
        store.identities.pop(t.get("Identity", ""), None)
        return _v1_ok(a)
    if a == "GetIdentityVerificationAttributes":
        ids = t.get("Identities") or []
        return _v1_ok(a, {"VerificationAttributes": {"entry": [
            {"key": i, "value": {"VerificationStatus": "Success" if i in store.identities else "NotStarted"}} for i in ids]}})
    return _v1_err("InvalidAction", f"The action {a} is not valid for this web service.")


def dispatch_query(store, params: dict) -> SesV2Response:
    """SES v1 Query protocol (`Action=…&Version=2010-12-01`), form-decoded into `params`."""
    a = str(params.get("Action", ""))
    t = _qtree({k: v for k, v in params.items() if k not in ("Action", "Version")})
    try:
        out = _v1_dispatch(store, a, t)
        store.persist()
        return out
    except SesV2Error as e:
        return _v1_err(e.code, e.message, e.status)


V1_ACTIONS = ("CreateReceiptRuleSet", "CloneReceiptRuleSet", "DeleteReceiptRuleSet", "ListReceiptRuleSets",
              "DescribeReceiptRuleSet", "DescribeActiveReceiptRuleSet", "SetActiveReceiptRuleSet",
              "CreateReceiptRule", "UpdateReceiptRule", "DescribeReceiptRule", "DeleteReceiptRule",
              "ReorderReceiptRuleSet", "VerifyEmailIdentity", "VerifyDomainIdentity", "ListIdentities",
              "DeleteIdentity", "GetIdentityVerificationAttributes")


# ── inbound: which receipt rules apply to a message, and what they do ──────
def _rule_matches(rule: dict, rcpt: str) -> bool:
    if not rule.get("Enabled"):
        return False
    rec = rule.get("Recipients") or []
    if not rec:
        return True
    a = rcpt.lower()
    dom = a.split("@", 1)[-1]
    for x in rec:
        x = x.lower().lstrip(".")
        if x == a or x == dom or dom.endswith("." + x):
            return True
    return False


def inbound_accepts(store, rcpt: str) -> bool:
    """The inbound listener takes mail only for a verified identity (domain or address)."""
    return _identity_verified(store, rcpt)


def inbound_plan(store, rcpts: list, mail_from: str, raw: bytes) -> dict:
    """Run the ACTIVE rule set against a received message. Returns the actions to execute
    ({'type', 'cfg', 'rule'}), the SES receipt-event payload and any bounce to answer with."""
    r = _rcpt(store)
    parsed = message_from_bytes(raw)
    mid = uuid.uuid4().hex
    now = _now()
    mail = {"timestamp": now, "source": mail_from, "messageId": mid, "destination": list(rcpts),
            "headersTruncated": False,
            "headers": [{"name": k, "value": str(v)} for k, v in parsed.items()][:50],
            "commonHeaders": {"from": [parsed.get("From", "")], "to": [parsed.get("To", "")],
                              "subject": parsed.get("Subject", ""), "messageId": parsed.get("Message-ID", "")}}
    plan, hit, bounce = [], [], None
    s = r["sets"].get(r["active"]) if r["active"] else None
    stop = False
    for rule in (s["Rules"] if s else []):
        if stop:
            break
        matched = [x for x in rcpts if _rule_matches(rule, x)]
        if not matched:
            continue
        hit.append(rule["Name"])
        for act in rule["Actions"]:
            kind = next(k for k in act if k in _ACTION_KINDS)
            plan.append({"type": kind, "cfg": act[kind], "rule": rule["Name"], "recipients": matched})
            if kind == "StopAction":
                stop = True
                break
            if kind == "BounceAction":
                c = act[kind]
                bounce = {"code": int(c.get("SmtpReplyCode") or 550), "status": c.get("StatusCode") or "5.1.1",
                          "message": c.get("Message") or "Mailbox does not exist"}
                stop = True
                break
    receipt = {"timestamp": now, "processingTimeMillis": 1, "recipients": list(rcpts), "spamVerdict": {"status": "PASS"},
               "virusVerdict": {"status": "PASS"}, "spfVerdict": {"status": "PASS"}, "dkimVerdict": {"status": "PASS"},
               "dmarcVerdict": {"status": "PASS"}, "action": {}}
    log = r["log"]
    log.append({"MessageId": mid, "From": mail_from, "To": list(rcpts), "Subject": parsed.get("Subject", ""),
                "received": now, "Rules": hit, "Actions": [p["type"] for p in plan]})
    del log[:-100]
    store.persist()
    return {"messageId": mid, "mail": mail, "receipt": receipt, "plan": plan, "bounce": bounce, "rules": hit}


def inbound_event(plan: dict, action: dict) -> dict:
    """The SES -> Lambda / SNS receipt event for one action."""
    rc = dict(plan["receipt"])
    rc["action"] = {"type": action["type"].replace("Action", ""), **{k[0].lower() + k[1:]: v for k, v in action["cfg"].items()}}
    return {"Records": [{"eventSource": "aws:ses", "eventVersion": "1.0", "ses": {"receipt": rc, "mail": plan["mail"]}}]}


# ── console view of the above ──────────────────────────────────────────────
def _mask(cfg: dict) -> dict:
    out = {k: v for k, v in (cfg or {}).items() if k not in ("password_enc", "log")}
    out["has_password"] = bool((cfg or {}).get("password_enc"))
    return out


def console_mail_settings(store) -> dict:
    ms = store.mail_settings or {}
    relay, imap = ms.get("relay") or {}, ms.get("imap") or {}
    return {"relay": _mask(relay), "imap": _mask(imap),
            "sandbox": not store.account.get("ProductionAccessEnabled"),
            "inbox_ui": getattr(store.mailer, "ui_url", "") if store.mailer else "",
            "smtp_available": store.mailer is not None}


def console_mail_settings_put(store, body: dict) -> dict:
    if store.mailer is None:
        raise SesV2Error("NotSupported", "Real delivery needs the offline appliance; the browser cannot speak SMTP.", 400)
    ms = store.mail_settings
    for key in ("relay", "imap"):
        if key not in body:
            continue
        inb = body[key] or {}
        cur = ms.setdefault(key, {})
        for f in ("enabled", "host", "port", "security", "username", "folder", "hourly_cap", "interval"):
            if f in inb:
                cur[f] = inb[f]
        if inb.get("enabled") and not str(cur.get("host") or "").strip():
            raise _bad(f"{key}: host is required to enable it.")
        if inb.get("password"):
            cur["password_enc"] = store.mailer.seal(str(inb["password"]))
    store.persist()
    return console_mail_settings(store)


def console_smtp_credentials(store, body: dict) -> dict:
    r = smtp_register(store, str(body.get("access_key_id") or body.get("AccessKeyId") or "").strip(),
                      str(body.get("secret_access_key") or body.get("SecretAccessKey") or "").strip())
    r.update(endpoint=getattr(store.mailer, "smtp_endpoint", "localhost:2587") if store.mailer else "localhost:2587",
             inbound_endpoint=getattr(store.mailer, "inbound_endpoint", "localhost:2525") if store.mailer else "localhost:2525")
    return r


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
        "config_set": i["ConfigurationSetName"] or "Not set",
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
    if body.get("config_set") and body["config_set"] not in ("None", "Not set"):
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


CHILD_KINDS = ("configuration-sets", "templates", "contact-lists", "suppression", "sent-emails", "received-emails", "mail-settings")


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
                 "subject": m.get("Subject") or f"({m['Kind']})", "config_set": m["ConfigurationSetName"] or "Not set",
                 "delivery": (m.get("Delivery") or {}).get("Status") or "Recorded",
                 "inbox": (m.get("Delivery") or {}).get("InboxUrl") or "Not delivered to an inbox",
                 "events": ", ".join(e["Type"] for e in m.get("Events") or []) or "Send",
                 "sent": m["sent"]} for m in reversed(store.messages)]
    elif kind == "received-emails":
        rows = [{"name": m["MessageId"], "from": m["From"] or "-", "to": ", ".join(m["To"]) or "-",
                 "subject": m["Subject"] or "(no subject)", "rules": ", ".join(m["Rules"]) or "No rule matched",
                 "actions": ", ".join(m["Actions"]) or "None", "received": m["received"]}
                for m in reversed(_rcpt(store)["log"])]
    elif kind == "mail-settings":
        rows = _mail_setting_rows(store)
    else:
        raise _notfound(f"Unknown collection {kind}")
    return {"items": rows}


def _mail_setting_rows(store) -> list:
    ms = console_mail_settings(store)
    relay, imap, live = ms["relay"], ms["imap"], ms["smtp_available"]
    act = _rcpt(store)["active"]
    ep = (getattr(store.mailer, "smtp_endpoint", "localhost:2587"), getattr(store.mailer, "inbound_endpoint", "localhost:2525"))

    def hp(c):
        return f"{c['host']}:{c.get('port') or 'default'} ({(c.get('security') or 'starttls').upper()})" if c.get("host") else "Not configured"
    return [
        {"name": "Sending mode", "value": "Sandbox (verified recipients only)" if ms["sandbox"] else "Production access",
         "status": "Active", "detail": "Production access is requested with PutAccountDetails; it lifts the relay's sandbox rule."},
        {"name": "Local inbox", "value": ms["inbox_ui"] or "Not available in Nano",
         "status": "Always on" if live else "Unavailable",
         "detail": "Every sent message is delivered to the Mailpit inbox." if live else "Browsers cannot speak SMTP: Nano keeps the API and the Sent list."},
        {"name": "SES SMTP interface", "value": ep[0] + " (STARTTLS)" if live else "Not available in Nano",
         "status": "Listening" if live else "Unavailable", "detail": "Use SMTP credentials derived from an IAM secret access key."},
        {"name": "Deliver to real inboxes (outbound relay)", "value": hp(relay),
         "status": "Enabled" if relay.get("enabled") else "Disabled",
         "detail": "Password stored encrypted." if relay.get("has_password") else "Your own SMTP server: Gmail app password, Office 365 or a company relay."},
        {"name": "Inbound SMTP listener", "value": ep[1] if live else "Not available in Nano",
         "status": ("Active rule set: " + act) if act else "No active rule set",
         "detail": "Accepts mail for verified identities and runs the active receipt rule set."},
        {"name": "Inbound IMAP poll", "value": hp(imap), "status": "Enabled" if imap.get("enabled") else "Disabled",
         "detail": "Polls a real mailbox and runs new messages through the same receipt rules."},
    ]


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
        elif parts[:1] == ["mail-settings"]:
            if method == "GET":
                return 200, {**console_mail_settings(store), "items": _mail_setting_rows(store)}
            if method == "POST":
                console_mail_settings_put(store, body)
                return 200, {**console_mail_settings(store), "items": _mail_setting_rows(store)}
        elif parts[:1] == ["smtp-credentials"] and method == "POST":
            return 200, console_smtp_credentials(store, body)
        elif parts[:1] == ["inbound-poll"] and method == "POST":
            if store.mailer is None:
                raise SesV2Error("NotSupported", "Inbound IMAP polling needs the offline appliance.", 400)
            return 200, store.mailer.poll_imap_now()
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
