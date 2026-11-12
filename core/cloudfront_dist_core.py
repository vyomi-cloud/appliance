"""Amazon CloudFront control plane beyond signing keys (service `cloudfront`, rest-xml, API 2020-05-31), served behind
core/cloudfront_keys_core.dispatch (which owns public keys + key groups): distributions (Create / CreateWithTags / Get / GetConfig /
List / Update / Delete / Copy, ListDistributionsBy{CachePolicyId,OriginRequestPolicyId,ResponseHeadersPolicyId,KeyGroupId,WebACLId}),
invalidations (Create / Get / List), tags (Tag / Untag / ListTagsForResource), origin access controls, origin access identities,
cache / origin-request / response-headers policies (custom CRUD + the AWS managed ones, read-only), monitoring subscriptions, and
CloudFront Functions (Create / Describe / Get / Update / Publish / List / Delete, code validated for a `handler` function).

Distribution configs are stored as the XML the client sent (namespace stripped) so every field round-trips exactly; the control plane
validates what AWS validates (CallerReference idempotency, >=1 origin, DefaultCacheBehavior.TargetOriginId resolves, CNAME uniqueness
across distributions, referenced OAC / OAI / cache + origin-request + response-headers policies must exist, If-Match / ETag, a
distribution must be disabled before delete, policies / OAC / functions still referenced by a distribution cannot be deleted).

Honest limits: there is no edge - a distribution is `Deployed` immediately and serves nothing; invalidations complete instantly and
purge nothing; CloudFront Functions are validated but not executed (TestFunction is not implemented); field-level encryption,
realtime log configs, continuous deployment policies, VPC origins and the Anycast IP lists are not implemented.
State: `s3_store.account["cloudfront"]["dist"]`. Loads under Pyodide (no fastapi / boto3)."""
from __future__ import annotations

import base64
import json
import re
import secrets
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.sax.saxutils import escape as esc

NS = "http://cloudfront.amazonaws.com/doc/2020-05-31/"
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
ACCOUNT = "000000000000"


class _Err(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _rid(prefix="E", n=13):
    return prefix + "".join(secrets.choice(_ALNUM) for _ in range(n))


def _etag():
    return _rid("E")


def _st(s3):
    d = s3.account.setdefault("cloudfront", {}).setdefault("dist", {})
    for k in ("dists", "invals", "oacs", "oais", "cps", "orps", "rhps", "funcs", "tags", "monitor"):
        d.setdefault(k, {})
    return d


# ───────────────────────── xml helpers ─────────────────────────
def _strip(el):
    for e in el.iter():
        if isinstance(e.tag, str):
            e.tag = e.tag.split("}")[-1]
    return el


def _parse(body, root=None):
    try:
        el = _strip(ET.fromstring(body or b""))
    except ET.ParseError:
        raise _Err(400, "MalformedInput", "The XML you provided was not well-formed or did not validate against our published schema.")
    if root and el.tag != root:
        raise _Err(400, "MalformedInput", f"Expected a {root} document.")
    return el


def _ser(el):
    return ET.tostring(el, encoding="unicode")


def _txt(el, path, default=None):
    f = el.find(path)
    return default if f is None or f.text is None else f.text.strip()


def _doc(root, inner):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<' + root + ' xmlns="' + NS + '">' + inner + "</" + root + ">").encode()


def _out(status, body=b"", etag=None, location=None, ctype="text/xml"):
    h = {"content-type": ctype}
    if etag:
        h["etag"] = etag
    if location:
        h["location"] = location
    return {"status": status, "headers": h, "body": body}


def _if_match(rec, h):
    im = h.get("if-match")
    if not im:
        raise _Err(400, "InvalidIfMatchVersion", "The If-Match version is missing or not valid for the resource.")
    if im != rec["etag"]:
        raise _Err(412, "PreconditionFailed", "The precondition given in one or more of the request-header fields evaluated to false.")


def _sub(cfg_xml, name):
    """Serialized first child <name>...</name> of a stored config, '' if absent."""
    m = re.search(rf"<{name}(?:\s[^>]*)?>.*?</{name}>|<{name}\s*/>", cfg_xml, re.S)
    return m.group(0) if m else ""


def _page(items, query):
    mi = int(query.get("MaxItems") or 100)
    marker = query.get("Marker") or ""
    ids = [i["id"] for i in items]
    start = ids.index(marker) + 1 if marker in ids else 0
    chunk = items[start:start + mi]
    trunc = start + mi < len(items)
    return chunk, f"<Marker>{esc(marker)}</Marker>" + (f"<NextMarker>{chunk[-1]['id']}</NextMarker>" if trunc and chunk else "") + f"<MaxItems>{mi}</MaxItems><IsTruncated>{'true' if trunc else 'false'}</IsTruncated><Quantity>{len(chunk)}</Quantity>"


# ───────────────────────── managed policies ─────────────────────────
_MANAGED = {
    "cp": {"658327ea-f89d-4fab-a63d-7e88639e58f6": ("Managed-CachingOptimized", "Default policy when CF compression is enabled", 1, 86400, 31536000),
           "4135ea2d-6df8-44a3-9df3-4b5a84be39ad": ("Managed-CachingDisabled", "Policy with caching disabled", 0, 0, 0),
           "b2884449-e4de-46a7-ac36-70bc7f1ddd6d": ("Managed-CachingOptimizedForUncompressedObjects", "Default policy when CF compression is disabled", 1, 86400, 31536000)},
    "orp": {"216adef6-5c7f-47e4-b989-5492eafa07d3": ("Managed-AllViewer", "Policy to forward all parameters in viewer requests"),
            "88a5eaf4-2fd4-4709-b370-b4c650ea3fcf": ("Managed-CORS-S3Origin", "Policy for S3 origin with CORS")},
    "rhp": {"67f7725c-6f97-4210-82d7-5512b31e9d03": ("Managed-SecurityHeadersPolicy", "Adds a set of security headers to every response"),
            "5cc3b908-e619-4b99-88e5-2cf7f45965bd": ("Managed-CORS-With-Preflight", "Allows all origins for CORS requests")},
}


def _managed_cfg(kind, pid):
    m = _MANAGED[kind][pid]
    if kind == "cp":
        return (f"<CachePolicyConfig><Comment>{esc(m[1])}</Comment><Name>{m[0]}</Name><DefaultTTL>{m[3]}</DefaultTTL><MaxTTL>{m[4]}</MaxTTL><MinTTL>{m[2]}</MinTTL>"
                "<ParametersInCacheKeyAndForwardedToOrigin><EnableAcceptEncodingGzip>true</EnableAcceptEncodingGzip><EnableAcceptEncodingBrotli>true</EnableAcceptEncodingBrotli>"
                "<HeadersConfig><HeaderBehavior>none</HeaderBehavior></HeadersConfig><CookiesConfig><CookieBehavior>none</CookieBehavior></CookiesConfig>"
                "<QueryStringsConfig><QueryStringBehavior>none</QueryStringBehavior></QueryStringsConfig></ParametersInCacheKeyAndForwardedToOrigin></CachePolicyConfig>")
    if kind == "orp":
        return (f"<OriginRequestPolicyConfig><Comment>{esc(m[1])}</Comment><Name>{m[0]}</Name><HeadersConfig><HeaderBehavior>allViewer</HeaderBehavior></HeadersConfig>"
                "<CookiesConfig><CookieBehavior>all</CookieBehavior></CookiesConfig><QueryStringsConfig><QueryStringBehavior>all</QueryStringBehavior></QueryStringsConfig></OriginRequestPolicyConfig>")
    return f"<ResponseHeadersPolicyConfig><Comment>{esc(m[1])}</Comment><Name>{m[0]}</Name></ResponseHeadersPolicyConfig>"


# ───────────────────────── generic CRUD kinds ─────────────────────────
KINDS = {
    "oac": dict(seg="origin-access-control", cfg="OriginAccessControlConfig", obj="OriginAccessControl", lst="OriginAccessControlList", item="OriginAccessControlSummary", store="oacs",
                nsuch="NoSuchOriginAccessControl", dup="OriginAccessControlAlreadyExists", inuse="OriginAccessControlInUse", label="origin access control"),
    "oai": dict(seg="origin-access-identity/cloudfront", cfg="CloudFrontOriginAccessIdentityConfig", obj="CloudFrontOriginAccessIdentity", lst="CloudFrontOriginAccessIdentityList",
                item="CloudFrontOriginAccessIdentitySummary", store="oais", nsuch="NoSuchCloudFrontOriginAccessIdentity", dup="CloudFrontOriginAccessIdentityAlreadyExists",
                inuse="CloudFrontOriginAccessIdentityInUse", label="origin access identity"),
    "cp": dict(seg="cache-policy", cfg="CachePolicyConfig", obj="CachePolicy", lst="CachePolicyList", item="CachePolicySummary", store="cps", nsuch="NoSuchCachePolicy",
               dup="CachePolicyAlreadyExists", inuse="CachePolicyInUse", label="cache policy"),
    "orp": dict(seg="origin-request-policy", cfg="OriginRequestPolicyConfig", obj="OriginRequestPolicy", lst="OriginRequestPolicyList", item="OriginRequestPolicySummary",
                store="orps", nsuch="NoSuchOriginRequestPolicy", dup="OriginRequestPolicyAlreadyExists", inuse="OriginRequestPolicyInUse", label="origin request policy"),
    "rhp": dict(seg="response-headers-policy", cfg="ResponseHeadersPolicyConfig", obj="ResponseHeadersPolicy", lst="ResponseHeadersPolicyList", item="ResponseHeadersPolicySummary",
                store="rhps", nsuch="NoSuchResponseHeadersPolicy", dup="ResponseHeadersPolicyAlreadyExists", inuse="ResponseHeadersPolicyInUse", label="response headers policy"),
}


def _validate_kind(kind, el):
    if kind == "oac":
        if not _txt(el, "Name"):
            raise _Err(400, "InvalidArgument", "Name is required.")
        if _txt(el, "SigningProtocol") != "sigv4":
            raise _Err(400, "InvalidArgument", "SigningProtocol must be sigv4.")
        if _txt(el, "SigningBehavior") not in ("never", "always", "no-override"):
            raise _Err(400, "InvalidArgument", "SigningBehavior must be never, always or no-override.")
        if _txt(el, "OriginAccessControlOriginType") not in ("s3", "mediastore", "lambda", "mediapackagev2"):
            raise _Err(400, "InvalidArgument", "OriginAccessControlOriginType must be s3, mediastore, lambda or mediapackagev2.")
    elif kind == "oai":
        if not _txt(el, "CallerReference") or _txt(el, "Comment") is None:
            raise _Err(400, "MissingArgument", "CallerReference and Comment are required.")
    else:
        if not _txt(el, "Name"):
            raise _Err(400, "InvalidArgument", "Name is required.")
        if kind == "cp" and _txt(el, "MinTTL") is None:
            raise _Err(400, "InvalidArgument", "MinTTL is required.")
        if kind == "cp":
            mn, df, mx = (int(_txt(el, k, 0) or 0) for k in ("MinTTL", "DefaultTTL", "MaxTTL"))
            if mn < 0 or not (mn <= df <= mx or (df == 0 and mx == 0)) and _txt(el, "DefaultTTL") is not None and _txt(el, "MaxTTL") is not None:
                raise _Err(400, "InvalidArgument", "TTLs must satisfy MinTTL <= DefaultTTL <= MaxTTL.")


def _obj_inner(kind, r):
    head = f"<Id>{r['id']}</Id>"
    if kind == "oai":
        head += f"<S3CanonicalUserId>{r['s3user']}</S3CanonicalUserId>"
    if kind in ("cp", "orp", "rhp"):
        head += f"<LastModifiedTime>{_iso(r['modified'])}</LastModifiedTime>"
    return head + r["cfg"]


def _obj_xml(kind, r):
    return f"<{KINDS[kind]['obj']}>{_obj_inner(kind, r)}</{KINDS[kind]['obj']}>"


def _cfg_doc(root, cfg):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + cfg.replace(f"<{root}>", f'<{root} xmlns="{NS}">', 1)).encode()


def _kind_summary(kind, r, type_="custom"):
    k = KINDS[kind]
    cfg = r["cfg"]
    if kind == "oac":
        return (f"<{k['item']}><Id>{r['id']}</Id><Description>{esc(_txt(ET.fromstring(cfg), 'Description', ''))}</Description><Name>{esc(_txt(ET.fromstring(cfg), 'Name', ''))}</Name>"
                f"{_sub(cfg, 'OriginAccessControlOriginType')}{_sub(cfg, 'SigningBehavior')}{_sub(cfg, 'SigningProtocol')}</{k['item']}>")
    if kind == "oai":
        return f"<{k['item']}><Id>{r['id']}</Id><S3CanonicalUserId>{r['s3user']}</S3CanonicalUserId><Comment>{esc(_txt(ET.fromstring(cfg), 'Comment', ''))}</Comment></{k['item']}>"
    return f"<{k['item']}><Type>{type_}</Type>{_obj_xml(kind, r)}</{k['item']}>"


def _managed_rec(kind, pid):
    return {"id": pid, "cfg": _managed_cfg(kind, pid), "modified": 1700000000.0, "etag": "ETVPDKIKX0DER", "managed": True}


def _find(st, kind, rid):
    k = KINDS[kind]
    r = st[k["store"]].get(rid)
    if r is None and kind in _MANAGED and rid in _MANAGED[kind]:
        r = _managed_rec(kind, rid)
    if r is None:
        raise _Err(404, k["nsuch"], f"The specified {k['label']} does not exist.")
    return r


def _in_use(st, kind, rid):
    pat = {"oac": "OriginAccessControlId", "oai": "OriginAccessIdentity", "cp": "CachePolicyId", "orp": "OriginRequestPolicyId", "rhp": "ResponseHeadersPolicyId"}[kind]
    needle = f">{rid}<" if kind != "oai" else f"origin-access-identity/cloudfront/{rid}"
    return [d["id"] for d in st["dists"].values() if pat in d["cfg"] and needle in d["cfg"]]


def kind_create(st, kind, h, body):
    k = KINDS[kind]
    el = _parse(body, k["cfg"])
    _validate_kind(kind, el)
    name = _txt(el, "Name")
    cr = _txt(el, "CallerReference")
    for r in st[k["store"]].values():
        e = ET.fromstring(r["cfg"])
        if (kind == "oai" and cr and _txt(e, "CallerReference") == cr) or (kind != "oai" and _txt(e, "Name") == name):
            raise _Err(409, k["dup"], f"A {k['label']} with the same {'caller reference' if kind == 'oai' else 'name'} already exists.")
    rid = _rid("E") if kind in ("oac", "oai") else "-".join([secrets.token_hex(4), secrets.token_hex(2), secrets.token_hex(2), secrets.token_hex(2), secrets.token_hex(6)])
    r = {"id": rid, "cfg": _ser(el), "modified": time.time(), "etag": _etag(), "s3user": secrets.token_hex(32)}
    st[k["store"]][rid] = r
    return _out(201, _doc(k["obj"], _obj_inner(kind, r)), r["etag"], f"https://cloudfront.amazonaws.com/2020-05-31/{k['seg']}/{rid}")


def kind_get(st, kind, rid, cfg_only=False):
    r = _find(st, kind, rid)
    k = KINDS[kind]
    if cfg_only:
        return _out(200, _cfg_doc(k["cfg"], r["cfg"]), r["etag"])
    return _out(200, _doc(k["obj"], _obj_inner(kind, r)), r["etag"])


def kind_update(st, kind, rid, h, body):
    k = KINDS[kind]
    r = _find(st, kind, rid)
    if r.get("managed"):
        raise _Err(400, "IllegalUpdate", f"Managed {k['label']}s cannot be modified.")
    _if_match(r, h)
    el = _parse(body, k["cfg"])
    _validate_kind(kind, el)
    if kind == "oai" and _txt(el, "CallerReference") != _txt(ET.fromstring(r["cfg"]), "CallerReference"):
        raise _Err(400, "IllegalUpdate", "CallerReference cannot be changed.")
    r["cfg"], r["modified"], r["etag"] = _ser(el), time.time(), _etag()
    return _out(200, _doc(k["obj"], _obj_inner(kind, r)), r["etag"])


def kind_delete(st, kind, rid, h):
    k = KINDS[kind]
    r = _find(st, kind, rid)
    if r.get("managed"):
        raise _Err(400, "IllegalDelete", f"Managed {k['label']}s cannot be deleted.")
    _if_match(r, h)
    users = _in_use(st, kind, rid)
    if users:
        raise _Err(409, k["inuse"], f"The {k['label']} is still referenced by distribution {users[0]}.")
    del st[k["store"]][rid]
    return _out(204)


def kind_list(st, kind, query):
    k = KINDS[kind]
    items = sorted(st[k["store"]].values(), key=lambda r: r["modified"])
    rows = []
    if kind in _MANAGED and query.get("Type") != "custom":
        rows += [_managed_rec(kind, pid) for pid in _MANAGED[kind]]
    if query.get("Type") == "managed":
        items = []
    allrows = [(r, "managed") for r in rows] + [(r, "custom") for r in items]
    chunk, meta = _page([r for r, _ in allrows], query)
    typ = {r["id"]: t for r, t in allrows}
    body = meta + "<Items>" + "".join(_kind_summary(kind, r, typ[r["id"]]) for r in chunk) + "</Items>"
    if not chunk:
        body = meta
    return _out(200, _doc(k["lst"], body))


# ───────────────────────── distributions ─────────────────────────
def _validate_dist(st, el, self_id=None):
    if _txt(el, "CallerReference") is None or _txt(el, "CallerReference") == "":
        raise _Err(400, "MissingArgument", "CallerReference is required.")
    if _txt(el, "Enabled") not in ("true", "false"):
        raise _Err(400, "MissingArgument", "Enabled is required (true or false).")
    if _txt(el, "Comment") is None:
        raise _Err(400, "MissingArgument", "Comment is required.")
    origins = el.findall("Origins/Items/Origin") + el.findall("Origins/Items/member")
    if not origins:
        raise _Err(400, "InvalidArgument", "The parameter Origins does not contain any origin.")
    oids = []
    for o in origins:
        oid, dn = _txt(o, "Id"), _txt(o, "DomainName")
        if not oid or not dn:
            raise _Err(400, "InvalidArgument", "Each origin needs an Id and a DomainName.")
        if oid in oids:
            raise _Err(400, "InvalidArgument", f"Origin Id {oid} is duplicated.")
        oids.append(oid)
        oac = _txt(o, "OriginAccessControlId")
        if oac and oac not in st["oacs"]:
            raise _Err(404, "NoSuchOriginAccessControl", f"The origin access control {oac} does not exist.")
        oai = _txt(o, "S3OriginConfig/OriginAccessIdentity")
        if oai:
            oid_ = oai.rsplit("/", 1)[-1]
            if oid_ not in st["oais"]:
                raise _Err(404, "NoSuchCloudFrontOriginAccessIdentity", f"The origin access identity {oid_} does not exist.")
        if oac and oai:
            raise _Err(400, "TooManyOriginCustomHeaders" if False else "InvalidArgument", "An origin cannot use both an OAC and an OAI.")
    dcb = el.find("DefaultCacheBehavior")
    if dcb is None:
        raise _Err(400, "MissingArgument", "DefaultCacheBehavior is required.")
    behaviors = [dcb] + el.findall("CacheBehaviors/Items/CacheBehavior")
    for b in behaviors:
        if _txt(b, "TargetOriginId") not in oids:
            raise _Err(400, "NoSuchOrigin", f"The specified origin {_txt(b, 'TargetOriginId')} does not exist.")
        if _txt(b, "ViewerProtocolPolicy") not in ("allow-all", "https-only", "redirect-to-https"):
            raise _Err(400, "InvalidArgument", "ViewerProtocolPolicy must be allow-all, https-only or redirect-to-https.")
        for tag, kind in (("CachePolicyId", "cp"), ("OriginRequestPolicyId", "orp"), ("ResponseHeadersPolicyId", "rhp")):
            v = _txt(b, tag)
            if v and v not in st[KINDS[kind]["store"]] and v not in _MANAGED[kind]:
                raise _Err(404, KINDS[kind]["nsuch"], f"The {KINDS[kind]['label']} {v} does not exist.")
        for fa in b.findall("FunctionAssociations/Items/FunctionAssociation"):
            arn = _txt(fa, "FunctionARN") or ""
            nm = arn.rsplit("/", 1)[-1]
            if nm not in st["funcs"]:
                raise _Err(404, "NoSuchFunctionExists", f"The function {nm} does not exist.")
            if "LIVE" not in st["funcs"][nm]["stages"]:
                raise _Err(400, "InvalidAssociation", f"Function {nm} must be published (LIVE) before it can be associated.")
    aliases = [(a.text or "").strip().lower() for a in el.findall("Aliases/Items/CNAME")]
    for d in st["dists"].values():
        if d["id"] == self_id:
            continue
        for a in aliases:
            if a in d["aliases"]:
                raise _Err(409, "CNAMEAlreadyExists", f"One or more of the CNAMEs you provided are already associated with a different resource ({a}).")
    return aliases


def _dist_xml(d):
    return (f"<Id>{d['id']}</Id><ARN>arn:aws:cloudfront::{ACCOUNT}:distribution/{d['id']}</ARN><Status>{d['status']}</Status><LastModifiedTime>{_iso(d['modified'])}</LastModifiedTime>"
            f"<InProgressInvalidationBatches>0</InProgressInvalidationBatches><DomainName>{d['domain']}</DomainName>"
            "<ActiveTrustedSigners><Enabled>false</Enabled><Quantity>0</Quantity></ActiveTrustedSigners><ActiveTrustedKeyGroups><Enabled>false</Enabled><Quantity>0</Quantity></ActiveTrustedKeyGroups>"
            f"<DistributionConfig>{d['cfg']}</DistributionConfig>")


def _cfg_inner(el):
    return "".join(_ser(c) for c in el)  # children only


def _new_dist(st, el, staging=False):
    cr = _txt(el, "CallerReference")
    for d in st["dists"].values():
        if d["caller"] == cr:
            if d["cfg"] == _cfg_inner(el):
                return d, False
            raise _Err(409, "DistributionAlreadyExists", f"The caller reference {cr} is already used by distribution {d['id']} with a different configuration.")
    aliases = _validate_dist(st, el)
    did = _rid("E", 13)
    d = {"id": did, "caller": cr, "cfg": _cfg_inner(el), "aliases": aliases, "status": "Deployed", "modified": time.time(), "etag": _etag(),
         "domain": f"d{secrets.token_hex(7)[:13]}.cloudfront.net", "staging": staging}
    st["dists"][did] = d
    return d, True


def dist_create(st, h, body, query):
    if "WithTags" in query:
        root = _parse(body, "DistributionConfigWithTags")
        cfg = root.find("DistributionConfig")
        if cfg is None:
            raise _Err(400, "MalformedInput", "DistributionConfig is required.")
        d, _new = _new_dist(st, cfg)
        for t in root.findall("Tags/Items/Tag"):
            st["tags"].setdefault(f"arn:aws:cloudfront::{ACCOUNT}:distribution/{d['id']}", {})[_txt(t, "Key")] = _txt(t, "Value", "")
    else:
        d, _new = _new_dist(st, _parse(body, "DistributionConfig"))
    return _out(201, _doc("Distribution", _dist_xml(d)), d["etag"], f"https://cloudfront.amazonaws.com/2020-05-31/distribution/{d['id']}")


def _dist(st, did):
    d = st["dists"].get(did)
    if d is None:
        raise _Err(404, "NoSuchDistribution", "The specified distribution does not exist.")
    return d


def dist_update(st, did, h, body):
    d = _dist(st, did)
    _if_match(d, h)
    el = _parse(body, "DistributionConfig")
    if _txt(el, "CallerReference") != d["caller"]:
        raise _Err(400, "IllegalUpdate", "CallerReference cannot be changed.")
    d["aliases"] = _validate_dist(st, el, did)
    d["cfg"], d["modified"], d["etag"] = _cfg_inner(el), time.time(), _etag()
    return _out(200, _doc("Distribution", _dist_xml(d)), d["etag"])


def dist_delete(st, did, h):
    d = _dist(st, did)
    _if_match(d, h)
    if _txt(ET.fromstring("<r>" + d["cfg"] + "</r>"), "Enabled") == "true":
        raise _Err(409, "DistributionNotDisabled", "The distribution you are trying to delete has not been disabled.")
    del st["dists"][did]
    st["invals"].pop(did, None)
    st["monitor"].pop(did, None)
    st["tags"].pop(f"arn:aws:cloudfront::{ACCOUNT}:distribution/{did}", None)
    return _out(204)


def _dist_summary(d):
    c = d["cfg"]
    root = ET.fromstring("<r>" + c + "</r>")
    return (f"<DistributionSummary><Id>{d['id']}</Id><ARN>arn:aws:cloudfront::{ACCOUNT}:distribution/{d['id']}</ARN><Status>{d['status']}</Status><LastModifiedTime>{_iso(d['modified'])}</LastModifiedTime>"
            f"<DomainName>{d['domain']}</DomainName>{_sub(c, 'Aliases') or '<Aliases><Quantity>0</Quantity></Aliases>'}{_sub(c, 'Origins')}{_sub(c, 'DefaultCacheBehavior')}"
            f"{_sub(c, 'CacheBehaviors') or '<CacheBehaviors><Quantity>0</Quantity></CacheBehaviors>'}{_sub(c, 'CustomErrorResponses') or '<CustomErrorResponses><Quantity>0</Quantity></CustomErrorResponses>'}"
            f"<Comment>{esc(_txt(root, 'Comment', ''))}</Comment><PriceClass>{_txt(root, 'PriceClass', 'PriceClass_All')}</PriceClass><Enabled>{_txt(root, 'Enabled', 'true')}</Enabled>"
            f"{_sub(c, 'ViewerCertificate') or '<ViewerCertificate><CloudFrontDefaultCertificate>true</CloudFrontDefaultCertificate></ViewerCertificate>'}"
            f"{_sub(c, 'Restrictions') or '<Restrictions><GeoRestriction><RestrictionType>none</RestrictionType><Quantity>0</Quantity></GeoRestriction></Restrictions>'}"
            f"<WebACLId>{esc(_txt(root, 'WebACLId', ''))}</WebACLId><HttpVersion>{_txt(root, 'HttpVersion', 'http2')}</HttpVersion>"
            f"<IsIPV6Enabled>{_txt(root, 'IsIPV6Enabled', 'true')}</IsIPV6Enabled><Staging>{'true' if d.get('staging') else 'false'}</Staging></DistributionSummary>")


def dist_list(st, query, only=None, wrapper="DistributionList"):
    items = sorted((d for d in st["dists"].values() if only is None or only(d)), key=lambda d: d["modified"])
    chunk, meta = _page(items, query)
    body = meta + ("<Items>" + "".join(_dist_summary(d) for d in chunk) + "</Items>" if chunk else "")
    return _out(200, _doc(wrapper, body))


def dist_by_id_list(st, query, needle_tag, value):
    items = sorted((d for d in st["dists"].values() if f"<{needle_tag}>{value}<" in d["cfg"] or f"<{needle_tag}>{value}</" in d["cfg"]), key=lambda d: d["modified"])
    chunk, meta = _page(items, query)
    body = meta + ("<Items>" + "".join(f"<DistributionId>{d['id']}</DistributionId>" for d in chunk) + "</Items>" if chunk else "")
    return _out(200, _doc("DistributionIdList", body))


def dist_copy(st, did, h, body):
    src = _dist(st, did)
    el = _parse(body, "CopyDistributionRequest") if body else None
    cr = _txt(el, "CallerReference") if el is not None else None
    if not cr:
        raise _Err(400, "MissingArgument", "CallerReference is required.")
    cfg = _parse(("<DistributionConfig>" + src["cfg"] + "</DistributionConfig>").encode())
    cfg.find("CallerReference").text = cr
    enabled = _txt(el, "Enabled")
    if enabled in ("true", "false"):
        cfg.find("Enabled").text = enabled
    aliases = cfg.find("Aliases")
    if aliases is not None:   # a copy must not claim the primary's CNAMEs
        for c in list(aliases):
            aliases.remove(c)
        ET.SubElement(aliases, "Quantity").text = "0"
    d, _ = _new_dist(st, cfg, staging=_txt(el, "Staging") == "true")
    return _out(201, _doc("Distribution", _dist_xml(d)), d["etag"], f"https://cloudfront.amazonaws.com/2020-05-31/distribution/{d['id']}")


# ───────────────────────── invalidations ─────────────────────────
def inval_create(st, did, body):
    _dist(st, did)
    el = _parse(body, "InvalidationBatch")
    cr = _txt(el, "CallerReference")
    paths = [(p.text or "").strip() for p in el.findall("Paths/Items/Path")]
    if not cr:
        raise _Err(400, "MissingArgument", "CallerReference is required.")
    if not paths:
        raise _Err(400, "MissingArgument", "At least one path is required.")
    for p in paths:
        if not p.startswith("/"):
            raise _Err(400, "InvalidArgument", f"Invalid path '{p}': invalidation paths must start with '/'.")
        if "*" in p[:-1]:
            raise _Err(400, "InvalidArgument", f"Invalid path '{p}': '*' is only allowed as the last character.")
    rows = st["invals"].setdefault(did, {})
    for r in rows.values():
        if r["caller"] == cr:
            if r["paths"] == paths:
                return _out(201, _doc("Invalidation", _inval_xml(r)), None, f"https://cloudfront.amazonaws.com/2020-05-31/distribution/{did}/invalidation/{r['id']}")
            raise _Err(409, "InvalidationBatchAlreadyExists" if False else "BatchTooLarge" if False else "InvalidArgument", "CallerReference already used with different paths.")
    iid = _rid("I", 13)
    r = {"id": iid, "caller": cr, "paths": paths, "created": time.time(), "status": "Completed"}
    rows[iid] = r
    return _out(201, _doc("Invalidation", _inval_xml(r)), None, f"https://cloudfront.amazonaws.com/2020-05-31/distribution/{did}/invalidation/{iid}")


def _inval_xml(r):
    return (f"<Id>{r['id']}</Id><Status>{r['status']}</Status><CreateTime>{_iso(r['created'])}</CreateTime><InvalidationBatch><Paths><Quantity>{len(r['paths'])}</Quantity><Items>"
            + "".join(f"<Path>{esc(p)}</Path>" for p in r["paths"]) + f"</Items></Paths><CallerReference>{esc(r['caller'])}</CallerReference></InvalidationBatch>")


def inval_get(st, did, iid):
    _dist(st, did)
    r = st["invals"].get(did, {}).get(iid)
    if r is None:
        raise _Err(404, "NoSuchInvalidation", "The specified invalidation does not exist.")
    return _out(200, _doc("Invalidation", _inval_xml(r)))


def inval_list(st, did, query):
    _dist(st, did)
    items = sorted(st["invals"].get(did, {}).values(), key=lambda r: -r["created"])
    chunk, meta = _page(items, query)
    body = meta + ("<Items>" + "".join(f"<InvalidationSummary><Id>{r['id']}</Id><CreateTime>{_iso(r['created'])}</CreateTime><Status>{r['status']}</Status></InvalidationSummary>" for r in chunk) + "</Items>" if chunk else "")
    return _out(200, _doc("InvalidationList", body))


# ───────────────────────── tags / monitoring ─────────────────────────
def _tag_arn(st, query):
    arn = query.get("Resource", "")
    m = re.fullmatch(rf"arn:aws:cloudfront::{ACCOUNT}:(distribution|streaming-distribution)/([A-Z0-9]+)", arn)
    if not m or (m.group(1) == "distribution" and m.group(2) not in st["dists"]):
        raise _Err(404, "NoSuchResource", f"The resource {arn} does not exist.")
    return arn


def tags_op(st, method, query, body):
    arn = _tag_arn(st, query)
    cur = st["tags"].setdefault(arn, {})
    if method == "GET":
        return _out(200, _doc("Tags", "<Items>" + "".join(f"<Tag><Key>{esc(k)}</Key><Value>{esc(v)}</Value></Tag>" for k, v in cur.items()) + "</Items>"))
    op = query.get("Operation")
    if op == "Tag":
        el = _parse(body, "Tags")
        new = {_txt(t, "Key"): _txt(t, "Value", "") for t in el.findall("Items/Tag")}
        if len(cur) + len([k for k in new if k not in cur]) > 50:
            raise _Err(400, "TooManyTags" if False else "InvalidTagging", "A resource can have at most 50 tags.")
        cur.update(new)
    elif op == "Untag":
        el = _parse(body, "TagKeys")
        for k in el.findall("Items/Key"):
            cur.pop((k.text or "").strip(), None)
    else:
        raise _Err(400, "InvalidArgument", "Operation must be Tag or Untag.")
    return _out(204)


def monitor_op(st, method, did, body):
    _dist(st, did)
    if method == "POST":
        el = _parse(body, "MonitoringSubscription")
        v = _txt(el, "RealtimeMetricsSubscriptionConfig/RealtimeMetricsSubscriptionStatus")
        if v not in ("Enabled", "Disabled"):
            raise _Err(400, "InvalidArgument", "RealtimeMetricsSubscriptionStatus must be Enabled or Disabled.")
        st["monitor"][did] = v
    elif method == "DELETE":
        st["monitor"].pop(did, None)
        return _out(200, b"")
    v = st["monitor"].get(did, "Disabled")
    return _out(200, _doc("MonitoringSubscription", f"<RealtimeMetricsSubscriptionConfig><RealtimeMetricsSubscriptionStatus>{v}</RealtimeMetricsSubscriptionStatus></RealtimeMetricsSubscriptionConfig>"))


# ───────────────────────── functions ─────────────────────────
def _fn(st, name):
    f = st["funcs"].get(name)
    if f is None:
        raise _Err(404, "NoSuchFunctionExists", f"The function {name} does not exist.")
    return f


def _fn_summary(f, stage):
    s = f["stages"][stage]
    return (f"<Name>{esc(f['name'])}</Name><Status>{'UNPUBLISHED' if 'LIVE' not in f['stages'] and stage == 'DEVELOPMENT' else 'UNASSOCIATED'}</Status>"
            f"<FunctionConfig><Comment>{esc(f['comment'])}</Comment><Runtime>{f['runtime']}</Runtime></FunctionConfig>"
            f"<FunctionMetadata><FunctionARN>arn:aws:cloudfront::{ACCOUNT}:function/{f['name']}</FunctionARN><Stage>{stage}</Stage><CreatedTime>{_iso(f['created'])}</CreatedTime>"
            f"<LastModifiedTime>{_iso(s['modified'])}</LastModifiedTime></FunctionMetadata>")


def _check_code(code):
    try:
        txt = base64.b64decode(code).decode("utf-8")
    except Exception:
        raise _Err(400, "InvalidArgument", "FunctionCode must be base64-encoded UTF-8.")
    if not txt.strip():
        raise _Err(400, "InvalidArgument", "FunctionCode is empty.")
    if not re.search(r"\bfunction\s+handler\s*\(", txt) and not re.search(r"\bhandler\s*=", txt):
        raise _Err(400, "FunctionSizeLimitExceeded" if False else "InvalidArgument", "The function code must define a `handler` function.")
    if len(txt.encode()) > 10240:
        raise _Err(400, "FunctionSizeLimitExceeded", "The function code exceeds the 10 KB limit.")
    return txt


def fn_create(st, body):
    el = _parse(body, "CreateFunctionRequest")
    name = _txt(el, "Name")
    if not name or not re.fullmatch(r"[a-zA-Z0-9-_]{1,64}", name):
        raise _Err(400, "InvalidArgument", "Function names are 1-64 characters of [a-zA-Z0-9-_].")
    if name in st["funcs"]:
        raise _Err(409, "FunctionAlreadyExists", f"Function {name} already exists.")
    runtime = _txt(el, "FunctionConfig/Runtime")
    if runtime not in ("cloudfront-js-1.0", "cloudfront-js-2.0"):
        raise _Err(400, "InvalidArgument", "Runtime must be cloudfront-js-1.0 or cloudfront-js-2.0.")
    code = _check_code(_txt(el, "FunctionCode", ""))
    now = time.time()
    f = {"name": name, "comment": _txt(el, "FunctionConfig/Comment", ""), "runtime": runtime, "created": now, "etag": _etag(),
         "stages": {"DEVELOPMENT": {"code": code, "modified": now, "etag": None}}}
    f["stages"]["DEVELOPMENT"]["etag"] = f["etag"]
    st["funcs"][name] = f
    return _out(201, _doc("FunctionSummary", _fn_summary(f, "DEVELOPMENT")), f["etag"], f"https://cloudfront.amazonaws.com/2020-05-31/function/{name}")


def fn_describe(st, name, query):
    f = _fn(st, name)
    stage = query.get("Stage") or ("LIVE" if "LIVE" in f["stages"] else "DEVELOPMENT")
    if stage not in f["stages"]:
        raise _Err(404, "NoSuchFunctionExists", f"Function {name} has no {stage} stage.")
    return _out(200, _doc("FunctionSummary", _fn_summary(f, stage)), f["stages"][stage]["etag"])


def fn_get(st, name, query):
    f = _fn(st, name)
    stage = query.get("Stage") or ("LIVE" if "LIVE" in f["stages"] else "DEVELOPMENT")
    if stage not in f["stages"]:
        raise _Err(404, "NoSuchFunctionExists", f"Function {name} has no {stage} stage.")
    return _out(200, f["stages"][stage]["code"].encode(), f["stages"][stage]["etag"], ctype="application/octet-stream")


def fn_update(st, name, h, body):
    f = _fn(st, name)
    dev = f["stages"]["DEVELOPMENT"]
    if not h.get("if-match"):
        raise _Err(400, "InvalidIfMatchVersion", "The If-Match version is missing or not valid for the resource.")
    if h["if-match"] != dev["etag"]:
        raise _Err(412, "PreconditionFailed", "The precondition given in one or more of the request-header fields evaluated to false.")
    el = _parse(body, "UpdateFunctionRequest")
    rt = _txt(el, "FunctionConfig/Runtime")
    if rt not in ("cloudfront-js-1.0", "cloudfront-js-2.0"):
        raise _Err(400, "InvalidArgument", "Runtime must be cloudfront-js-1.0 or cloudfront-js-2.0.")
    dev["code"] = _check_code(_txt(el, "FunctionCode", ""))
    f["comment"], f["runtime"] = _txt(el, "FunctionConfig/Comment", ""), rt
    dev["modified"], dev["etag"] = time.time(), _etag()
    return _out(200, _doc("FunctionSummary", _fn_summary(f, "DEVELOPMENT")), dev["etag"])


def fn_publish(st, name, h):
    f = _fn(st, name)
    dev = f["stages"]["DEVELOPMENT"]
    if not h.get("if-match"):
        raise _Err(400, "InvalidIfMatchVersion", "The If-Match version is missing or not valid for the resource.")
    if h["if-match"] != dev["etag"]:
        raise _Err(412, "PreconditionFailed", "The precondition given in one or more of the request-header fields evaluated to false.")
    f["stages"]["LIVE"] = {"code": dev["code"], "modified": time.time(), "etag": _etag()}
    return _out(200, _doc("FunctionSummary", _fn_summary(f, "LIVE")), f["stages"]["LIVE"]["etag"])


def fn_delete(st, name, h):
    f = _fn(st, name)
    if not h.get("if-match"):
        raise _Err(400, "InvalidIfMatchVersion", "The If-Match version is missing or not valid for the resource.")
    if h["if-match"] != f["stages"]["DEVELOPMENT"]["etag"]:
        raise _Err(412, "PreconditionFailed", "The precondition given in one or more of the request-header fields evaluated to false.")
    arn = f"arn:aws:cloudfront::{ACCOUNT}:function/{name}"
    users = [d["id"] for d in st["dists"].values() if arn in d["cfg"]]
    if users:
        raise _Err(409, "FunctionInUse", f"Function {name} is associated with distribution {users[0]}.")
    del st["funcs"][name]
    return _out(204)


def fn_list(st, query):
    stage = query.get("Stage")
    rows = []
    for f in sorted(st["funcs"].values(), key=lambda x: x["created"]):
        for s in (["LIVE"] if stage == "LIVE" else ["DEVELOPMENT"] if stage == "DEVELOPMENT" else ["DEVELOPMENT"]):
            if s in f["stages"]:
                rows.append({"id": f["name"], "xml": f"<FunctionSummary>{_fn_summary(f, s)}</FunctionSummary>"})
    chunk, meta = _page(rows, query)
    return _out(200, _doc("FunctionList", meta + ("<Items>" + "".join(r["xml"] for r in chunk) + "</Items>" if chunk else "")))


# ───────────────────────── routing ─────────────────────────
_P = "/2020-05-31"


def dispatch(s3_store, method, path, query, h, body):
    """-> response dict, or None when the path is not one of ours (the caller 404s)."""
    st = _st(s3_store)
    seg = [urllib.parse.unquote(s) for s in path.strip("/").split("/")]
    if not seg or seg[0] != "2020-05-31":
        return None
    seg = seg[1:]
    try:
        r = _route(st, method, seg, query, h, body)
    except _Err as e:
        return {"status": e.status, "headers": {"content-type": "text/xml", "x-amzn-errortype": e.code},
                "body": f'<?xml version="1.0"?><ErrorResponse xmlns="{NS}"><Error><Type>Sender</Type><Code>{e.code}</Code><Message>{esc(e.message)}</Message></Error>'
                        f'<RequestId>{_rid("R")}</RequestId></ErrorResponse>'.encode()}
    if r is not None and method != "GET":
        try:
            s3_store.persist()
        except Exception:
            pass
    return r


def _route(st, m, seg, q, h, body):
    n = len(seg)
    if not seg:
        return None
    s0 = seg[0]
    if s0 == "distribution":
        if n == 1:
            return dist_create(st, h, body, q) if m == "POST" else dist_list(st, q) if m == "GET" else None
        did = seg[1]
        if n == 2:
            if m == "GET":
                d = _dist(st, did)
                return _out(200, _doc("Distribution", _dist_xml(d)), d["etag"])
            return dist_delete(st, did, h) if m == "DELETE" else None
        if n == 3 and seg[2] == "config":
            if m == "GET":
                d = _dist(st, did)
                return _out(200, _doc("DistributionConfig", d["cfg"]), d["etag"])
            return dist_update(st, did, h, body) if m == "PUT" else None
        if n == 3 and seg[2] == "copy" and m == "POST":
            return dist_copy(st, did, h, body)
        if n == 3 and seg[2] == "invalidation":
            return inval_create(st, did, body) if m == "POST" else inval_list(st, did, q) if m == "GET" else None
        if n == 4 and seg[2] == "invalidation" and m == "GET":
            return inval_get(st, did, seg[3])
        return None
    if s0 == "distributions" and n == 3 and seg[2] == "monitoring-subscription":
        return monitor_op(st, m, seg[1], body) if m in ("GET", "POST", "DELETE") else None
    if s0 == "distribution" and n == 1:
        return None
    if s0 == "tagging" and m in ("GET", "POST"):
        return tags_op(st, m, q, body)
    by = {"distributionsByCachePolicyId": "CachePolicyId", "distributionsByOriginRequestPolicyId": "OriginRequestPolicyId",
          "distributionsByResponseHeadersPolicyId": "ResponseHeadersPolicyId", "distributionsByKeyGroupId": "KeyGroup"}
    if s0 in by and n == 2 and m == "GET":
        if s0 == "distributionsByKeyGroupId":
            return dist_by_id_list(st, q, "KeyGroup", seg[1])
        return dist_by_id_list(st, q, by[s0], seg[1])
    if s0 == "distributionsByWebACLId" and n == 2 and m == "GET":
        wid = "" if seg[1] == "null" else seg[1]
        return dist_list(st, q, only=lambda d: f"<WebACLId>{wid}</WebACLId>" in d["cfg"] or (not wid and "<WebACLId>" not in d["cfg"]))
    for kind, k in KINDS.items():
        segs = k["seg"].split("/")
        if seg[:len(segs)] != segs:
            continue
        rest = seg[len(segs):]
        if not rest:
            return kind_create(st, kind, h, body) if m == "POST" else kind_list(st, kind, q) if m == "GET" else None
        if len(rest) == 1:
            return (kind_get(st, kind, rest[0]) if m == "GET" else kind_update(st, kind, rest[0], h, body) if m == "PUT" else kind_delete(st, kind, rest[0], h) if m == "DELETE" else None)
        if len(rest) == 2 and rest[1] == "config" and m == "GET":
            return kind_get(st, kind, rest[0], cfg_only=True)
        return None
    if s0 == "function":
        if n == 1:
            return fn_create(st, body) if m == "POST" else fn_list(st, q) if m == "GET" else None
        if n == 2:
            return fn_get(st, seg[1], q) if m == "GET" else fn_update(st, seg[1], h, body) if m == "PUT" else fn_delete(st, seg[1], h) if m == "DELETE" else None
        if n == 3 and seg[2] == "describe" and m == "GET":
            return fn_describe(st, seg[1], q)
        if n == 3 and seg[2] == "publish" and m == "POST":
            return fn_publish(st, seg[1], h)
    return None
