"""S3 bucket sub-resource configuration (encryption, public access block,
policy, CORS, lifecycle): one JSON shape shared by the S3 wire handlers
(XML) and the console API (JSON). Pure functions over a bucket record.

Stored on the bucket record as: ``sse`` (dict), ``public_access_block``
(dict of four booleans), ``policy`` (JSON text), ``cors`` / ``lifecycle``
(the XML document as the client sent it)."""
from __future__ import annotations

import json
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
PAB_KEYS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
DEFAULT_SSE = {"algorithm": "AES256", "kms_key_id": "", "bucket_key_enabled": True}
SSE_ALGORITHMS = ("AES256", "aws:kms", "aws:kms:dsse")


class ConfigError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(node, name: str):
    return [c for c in node if _local(c.tag) == name]


def _text(node, name: str, default: str = "") -> str:
    for c in node:
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return default


def _parse(body: bytes | str):
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        raise ConfigError("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.")


# ── default encryption ─────────────────────────────────────────────────
def get_sse(bucket: dict) -> dict:
    return dict(bucket.get("sse") or DEFAULT_SSE)


def normalize_sse(d: dict) -> dict:
    alg = str(d.get("algorithm") or "AES256")
    if alg not in SSE_ALGORITHMS:
        raise ConfigError("InvalidArgument", f"Server Side Encryption with {alg} is not supported.")
    key = str(d.get("kms_key_id") or "")
    if alg == "AES256":
        key = ""
    return {"algorithm": alg, "kms_key_id": key, "bucket_key_enabled": bool(d.get("bucket_key_enabled", alg == "AES256"))}


def sse_from_xml(body) -> dict:
    root = _parse(body)
    rules = _kids(root, "Rule")
    if not rules:
        raise ConfigError("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.")
    rule = rules[0]
    app = _kids(rule, "ApplyServerSideEncryptionByDefault")
    if not app:
        raise ConfigError("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.")
    return normalize_sse({
        "algorithm": _text(app[0], "SSEAlgorithm"),
        "kms_key_id": _text(app[0], "KMSMasterKeyID"),
        "bucket_key_enabled": _text(rule, "BucketKeyEnabled", "false").lower() == "true",
    })


def sse_to_xml(sse: dict) -> str:
    key = f"<KMSMasterKeyID>{escape(sse['kms_key_id'])}</KMSMasterKeyID>" if sse.get("kms_key_id") else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><ServerSideEncryptionConfiguration xmlns="{S3_NS}"><Rule>'
            f'<ApplyServerSideEncryptionByDefault><SSEAlgorithm>{sse["algorithm"]}</SSEAlgorithm>{key}'
            f'</ApplyServerSideEncryptionByDefault>'
            f'<BucketKeyEnabled>{"true" if sse.get("bucket_key_enabled") else "false"}</BucketKeyEnabled>'
            f'</Rule></ServerSideEncryptionConfiguration>')


# ── block public access ────────────────────────────────────────────────
def get_pab(bucket: dict) -> dict | None:
    """None when the configuration was deleted; new buckets block everything."""
    if "public_access_block" not in bucket:
        return {k: True for k in PAB_KEYS}
    return bucket["public_access_block"] or None


def normalize_pab(d: dict) -> dict:
    return {k: bool(d.get(k, False)) for k in PAB_KEYS}


def pab_from_xml(body) -> dict:
    root = _parse(body)
    return {k: _text(root, k, "false").lower() == "true" for k in PAB_KEYS}


def pab_to_xml(pab: dict) -> str:
    inner = "".join(f"<{k}>{'true' if pab.get(k) else 'false'}</{k}>" for k in PAB_KEYS)
    return f'<?xml version="1.0" encoding="UTF-8"?><PublicAccessBlockConfiguration xmlns="{S3_NS}">{inner}</PublicAccessBlockConfiguration>'


def access_label(bucket: dict) -> str:
    """The grid's 'Access' column, derived from the real settings."""
    pab = get_pab(bucket) or {}
    if all(pab.get(k) for k in PAB_KEYS):
        return "Bucket and objects not public"
    if bucket.get("policy") and '"Principal":"*"' in re.sub(r"\s", "", bucket["policy"]):
        return "Public"
    return "Objects can be public"


# ── bucket policy ──────────────────────────────────────────────────────
def validate_policy(text: str, bucket_name: str) -> str:
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        raise ConfigError("MalformedPolicy", "Policy has invalid JSON")
    if not isinstance(doc, dict) or not doc.get("Statement"):
        raise ConfigError("MalformedPolicy", "Missing required field Statement")
    stmts = doc["Statement"] if isinstance(doc["Statement"], list) else [doc["Statement"]]
    for s in stmts:
        if not isinstance(s, dict) or s.get("Effect") not in ("Allow", "Deny"):
            raise ConfigError("MalformedPolicy", "Missing or invalid Effect in statement")
        if "Action" not in s and "NotAction" not in s:
            raise ConfigError("MalformedPolicy", "Policy statement must contain actions.")
        if "Principal" not in s and "NotPrincipal" not in s:
            raise ConfigError("MalformedPolicy", "Missing required field Principal")
        if "Resource" not in s and "NotResource" not in s:
            raise ConfigError("MalformedPolicy", "Policy statement must contain resources.")
    return json.dumps(doc, indent=2)


# ── CORS ───────────────────────────────────────────────────────────────
def cors_from_xml(xml) -> list[dict]:
    if not xml:
        return []
    root = _parse(xml)
    out = []
    for r in _kids(root, "CORSRule"):
        out.append({
            "id": _text(r, "ID"),
            "allowed_origins": [c.text or "" for c in _kids(r, "AllowedOrigin")],
            "allowed_methods": [c.text or "" for c in _kids(r, "AllowedMethod")],
            "allowed_headers": [c.text or "" for c in _kids(r, "AllowedHeader")],
            "expose_headers": [c.text or "" for c in _kids(r, "ExposeHeader")],
            "max_age_seconds": int(_text(r, "MaxAgeSeconds", "0") or 0),
        })
    return out


def cors_to_xml(rules: list[dict]) -> str:
    parts = []
    for r in rules:
        if not r.get("allowed_origins") or not r.get("allowed_methods"):
            raise ConfigError("MalformedXML", "A CORS rule needs at least one allowed origin and one allowed method.")
        for m in r["allowed_methods"]:
            if m not in ("GET", "PUT", "POST", "DELETE", "HEAD"):
                raise ConfigError("InvalidRequest", f"Found unsupported HTTP method in CORS config. Unsupported method is {m}")
        p = ["<CORSRule>"]
        if r.get("id"):
            p.append(f"<ID>{escape(r['id'])}</ID>")
        p += [f"<AllowedOrigin>{escape(x)}</AllowedOrigin>" for x in r["allowed_origins"]]
        p += [f"<AllowedMethod>{x}</AllowedMethod>" for x in r["allowed_methods"]]
        p += [f"<AllowedHeader>{escape(x)}</AllowedHeader>" for x in r.get("allowed_headers", [])]
        p += [f"<ExposeHeader>{escape(x)}</ExposeHeader>" for x in r.get("expose_headers", [])]
        if r.get("max_age_seconds"):
            p.append(f"<MaxAgeSeconds>{int(r['max_age_seconds'])}</MaxAgeSeconds>")
        p.append("</CORSRule>")
        parts.append("".join(p))
    return f'<?xml version="1.0" encoding="UTF-8"?><CORSConfiguration xmlns="{S3_NS}">{"".join(parts)}</CORSConfiguration>'


# ── lifecycle ──────────────────────────────────────────────────────────
def lifecycle_from_xml(xml) -> list[dict]:
    if not xml:
        return []
    root = _parse(xml)
    out = []
    for r in _kids(root, "Rule"):
        flt = _kids(r, "Filter")
        prefix = _text(flt[0], "Prefix") if flt else _text(r, "Prefix")
        trans = _kids(r, "Transition")
        exp = _kids(r, "Expiration")
        nce = _kids(r, "NoncurrentVersionExpiration")
        out.append({
            "id": _text(r, "ID"),
            "status": _text(r, "Status", "Enabled"),
            "prefix": prefix,
            "transition_days": int(_text(trans[0], "Days", "0") or 0) if trans else 0,
            "transition_storage_class": _text(trans[0], "StorageClass") if trans else "",
            "expiration_days": int(_text(exp[0], "Days", "0") or 0) if exp else 0,
            "noncurrent_expiration_days": int(_text(nce[0], "NoncurrentDays", "0") or 0) if nce else 0,
        })
    return out


def lifecycle_to_xml(rules: list[dict]) -> str:
    parts = []
    for r in rules:
        rid = str(r.get("id") or "").strip()
        if not rid:
            raise ConfigError("InvalidArgument", "Rule ID is required.")
        status = r.get("status") or "Enabled"
        if status not in ("Enabled", "Disabled"):
            raise ConfigError("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema.")
        tdays, edays, ndays = (int(r.get(k) or 0) for k in ("transition_days", "expiration_days", "noncurrent_expiration_days"))
        if not (tdays or edays or ndays):
            raise ConfigError("InvalidRequest", "At least one action needs to be specified in a rule.")
        p = [f"<Rule><ID>{escape(rid)}</ID><Filter><Prefix>{escape(r.get('prefix') or '')}</Prefix></Filter><Status>{status}</Status>"]
        if tdays:
            p.append(f"<Transition><Days>{tdays}</Days><StorageClass>{escape(r.get('transition_storage_class') or 'GLACIER')}</StorageClass></Transition>")
        if edays:
            p.append(f"<Expiration><Days>{edays}</Days></Expiration>")
        if ndays:
            p.append(f"<NoncurrentVersionExpiration><NoncurrentDays>{ndays}</NoncurrentDays></NoncurrentVersionExpiration>")
        p.append("</Rule>")
        parts.append("".join(p))
    return f'<?xml version="1.0" encoding="UTF-8"?><LifecycleConfiguration xmlns="{S3_NS}">{"".join(parts)}</LifecycleConfiguration>'
