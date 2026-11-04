"""Amazon CloudFront signing keys (service `cloudfront`, SigV4 signing name `cloudfront`, rest-xml, API 2020-05-31).

Substrate-independent (no fastapi / boto3 / cryptography; loads under Pyodide). Implements the control plane for what signed
URLs / signed cookies are verified against:
  * public keys   - Create/Get/GetConfig/List/Update/DeletePublicKey (RSA 2048 PEM validated, EncodedKey immutable, ETag + If-Match),
  * key groups    - Create/Get/GetConfig/List/Update/DeleteKeyGroup (1-5 existing public keys; a public key used by a key group
                    cannot be deleted - PublicKeyInUse),
and Vyomi extensions under `/2020-05-31/vyomi/` (not part of the real API, used by the IAM console):
  * root key pairs - the legacy account-level CloudFront key pairs (create from a client-generated public key, activate/deactivate,
                     delete; the private key is never sent to the simulator),
  * validate-signed-url - verifies a CloudFront signed URL exactly the way the edge does: Key-Pair-Id resolves to a public key
                     in a key group (or an active root key pair), canned (Expires) or custom (Policy) policy, expiry / DateGreaterThan,
                     resource wildcard match, IpAddress condition, and the RSA-SHA1 PKCS#1 v1.5 signature (pure-python RSA verify).

Honest limit: Vyomi has no CloudFront distributions or edge, so key groups are not attachable to a cache behavior and nothing
enforces signed URLs on a request; validate-signed-url is the verification you can run. State: `s3_store.account["cloudfront"]`.
"""
from __future__ import annotations

import base64
import hashlib
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
_SHA1_PREFIX = bytes.fromhex("3021300906052b0e03021a05000414")


class _Err(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def _state(s3_store) -> dict:
    st = s3_store.account.setdefault("cloudfront", {})
    st.setdefault("public_keys", {})
    st.setdefault("key_groups", {})
    st.setdefault("root_keys", {})
    return st


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _id(prefix: str) -> str:
    return prefix + "".join(secrets.choice(_ALNUM) for _ in range(13))


def _etag() -> str:
    return "E" + "".join(secrets.choice(_ALNUM) for _ in range(13))


# ── minimal DER / RSA (public operations only) ────────────────────────────
def _der(buf: bytes, i: int):
    tag = buf[i]
    ln = buf[i + 1]
    j = i + 2
    if ln & 0x80:
        nb = ln & 0x7F
        ln = int.from_bytes(buf[j:j + nb], "big")
        j += nb
    return tag, buf[j:j + ln], j + ln


def parse_public_key(pem: str):
    """-> (n, e) of an RSA SubjectPublicKeyInfo / PKCS#1 PEM, or raises ValueError."""
    m = re.search(r"-----BEGIN (RSA PUBLIC KEY|PUBLIC KEY)-----(.+?)-----END \1-----", pem or "", re.S)
    if not m:
        raise ValueError("not a PEM public key")
    der = base64.b64decode(re.sub(r"\s+", "", m.group(2)))
    tag, body, _ = _der(der, 0)
    if tag != 0x30:
        raise ValueError("bad DER")
    if m.group(1) == "PUBLIC KEY":
        _, _, nxt = _der(body, 0)                 # AlgorithmIdentifier
        t, bits, _ = _der(body, nxt)
        if t != 0x03:
            raise ValueError("bad DER")
        _, body, _ = _der(bits[1:], 0)
    _, n_b, nxt = _der(body, 0)
    _, e_b, _ = _der(body, nxt)
    return int.from_bytes(n_b, "big"), int.from_bytes(e_b, "big")


def rsa_sha1_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    digest = hashlib.sha1(message).digest()
    expect = b"\x00\x01" + b"\xff" * (k - len(_SHA1_PREFIX) - len(digest) - 3) + b"\x00" + _SHA1_PREFIX + digest
    return em == expect


def _cf_b64decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "=").replace("~", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


# ── XML helpers ────────────────────────────────────────────────────────────
def _parse(body: bytes, root: str) -> ET.Element:
    try:
        el = ET.fromstring(body or b"")
    except ET.ParseError:
        raise _Err(400, "MalformedInput", "The XML you provided was not well-formed or did not validate against our published schema.")
    if el.tag.split("}")[-1] != root:
        raise _Err(400, "MalformedInput", f"Expected a {root} document.")
    return el


def _t(el: ET.Element, name: str):
    for c in el:
        if c.tag.split("}")[-1] == name:
            return (c.text or "").strip()
    return None


def _items(el: ET.Element, name: str, child: str) -> list:
    for c in el:
        if c.tag.split("}")[-1] == name:
            return [(x.text or "").strip() for x in c if x.tag.split("}")[-1] == child]
    return []


def _xml(root: str, inner: str, ns: bool = True) -> bytes:
    attr = ' xmlns="' + NS + '"' if ns else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<' + root + attr + ">" + inner + "</" + root + ">").encode()


def _pk_config_xml(c: dict) -> str:
    return (f"<CallerReference>{esc(c['CallerReference'])}</CallerReference><Name>{esc(c['Name'])}</Name>"
            f"<EncodedKey>{esc(c['EncodedKey'])}</EncodedKey>" + (f"<Comment>{esc(c['Comment'])}</Comment>" if c.get("Comment") else ""))


def _pk_xml(k: dict) -> bytes:
    return _xml("PublicKey", f"<Id>{k['Id']}</Id><CreatedTime>{_iso(k['Created'])}</CreatedTime>"
                f"<PublicKeyConfig>{_pk_config_xml(k['Config'])}</PublicKeyConfig>")


def _kg_config_xml(c: dict) -> str:
    return (f"<Name>{esc(c['Name'])}</Name><Items>" + "".join(f"<PublicKey>{i}</PublicKey>" for i in c["Items"]) + "</Items>"
            + (f"<Comment>{esc(c['Comment'])}</Comment>" if c.get("Comment") else ""))


def _kg_inner(g: dict) -> str:
    return f"<Id>{g['Id']}</Id><LastModifiedTime>{_iso(g['Modified'])}</LastModifiedTime><KeyGroupConfig>{_kg_config_xml(g['Config'])}</KeyGroupConfig>"


def _out(status, body=b"", etag=None, location=None, ctype="text/xml"):
    h = {"content-type": ctype}
    if etag:
        h["etag"] = etag
    if location:
        h["location"] = location
    return {"status": status, "headers": h, "body": body}


def _check_if_match(rec: dict, headers: dict):
    im = headers.get("if-match")
    if not im:
        raise _Err(400, "InvalidIfMatchVersion", "The If-Match version is missing or not valid for the resource.")
    if im != rec["ETag"]:
        raise _Err(412, "PreconditionFailed", "The precondition given in one or more of the request-header fields evaluated to false.")


def _validate_encoded_key(pem: str) -> None:
    try:
        n, e = parse_public_key(pem)
    except Exception:
        raise _Err(400, "InvalidArgument", "Your request contains an empty or invalid public key. Public keys must be PEM-encoded RSA keys.")
    if n.bit_length() != 2048:
        raise _Err(400, "InvalidArgument", "Your request contains a public key that is not a 2048-bit RSA key. CloudFront supports 2048-bit RSA keys only.")


# ── public keys ─────────────────────────────────────────────────────────────
def create_public_key(st, headers, body):
    cfg = _parse(body, "PublicKeyConfig")
    c = {"CallerReference": _t(cfg, "CallerReference"), "Name": _t(cfg, "Name"), "EncodedKey": _t(cfg, "EncodedKey"), "Comment": _t(cfg, "Comment") or ""}
    for need in ("CallerReference", "Name", "EncodedKey"):
        if not c[need]:
            raise _Err(400, "InvalidArgument", f"Your request is missing the required {need}.")
    if len(c["Name"]) > 128 or not re.match(r"^[\w\-. ]+$", c["Name"]):
        raise _Err(400, "InvalidArgument", "The public key name is invalid.")
    _validate_encoded_key(c["EncodedKey"])
    for k in st["public_keys"].values():
        if k["Config"]["CallerReference"] == c["CallerReference"]:
            if k["Config"] == c:
                return _out(201, _pk_xml(k), k["ETag"], f"https://cloudfront.amazonaws.com/2020-05-31/public-key/{k['Id']}")
            raise _Err(409, "PublicKeyAlreadyExists", "A public key with the same caller reference but different settings already exists.")
        if k["Config"]["Name"] == c["Name"]:
            raise _Err(409, "PublicKeyAlreadyExists", f"A public key with the name {c['Name']} already exists.")
    if len(st["public_keys"]) >= 10:
        raise _Err(400, "TooManyPublicKeys", "You cannot create more public keys: the account limit is 10.")
    k = {"Id": _id("K"), "Created": time.time(), "Config": c, "ETag": _etag()}
    st["public_keys"][k["Id"]] = k
    return _out(201, _pk_xml(k), k["ETag"], f"https://cloudfront.amazonaws.com/2020-05-31/public-key/{k['Id']}")


def _pk(st, kid):
    k = st["public_keys"].get(kid)
    if not k:
        raise _Err(404, "NoSuchPublicKey", "The specified public key does not exist.")
    return k


def update_public_key(st, kid, headers, body):
    k = _pk(st, kid)
    _check_if_match(k, headers)
    cfg = _parse(body, "PublicKeyConfig")
    new = {"CallerReference": _t(cfg, "CallerReference"), "Name": _t(cfg, "Name"), "EncodedKey": _t(cfg, "EncodedKey"), "Comment": _t(cfg, "Comment") or ""}
    if new["EncodedKey"] != k["Config"]["EncodedKey"] or new["CallerReference"] != k["Config"]["CallerReference"]:
        raise _Err(400, "IllegalUpdate", "CannotChangeImmutablePublicKeyFields: the EncodedKey and CallerReference of a public key cannot be changed.")
    if not new["Name"]:
        raise _Err(400, "InvalidArgument", "Your request is missing the required Name.")
    if any(o["Id"] != kid and o["Config"]["Name"] == new["Name"] for o in st["public_keys"].values()):
        raise _Err(409, "PublicKeyAlreadyExists", f"A public key with the name {new['Name']} already exists.")
    k["Config"], k["ETag"] = new, _etag()
    return _out(200, _pk_xml(k), k["ETag"])


def delete_public_key(st, kid, headers):
    k = _pk(st, kid)
    _check_if_match(k, headers)
    for g in st["key_groups"].values():
        if kid in g["Config"]["Items"]:
            raise _Err(409, "PublicKeyInUse", "The specified public key is in use by a key group.")
    del st["public_keys"][kid]
    return _out(204)


def list_public_keys(st, query):
    ks = sorted(st["public_keys"].values(), key=lambda k: k["Id"])
    mx = int(query.get("MaxItems") or 100)
    start = next((i + 1 for i, k in enumerate(ks) if k["Id"] == query.get("Marker")), 0) if query.get("Marker") else 0
    page = ks[start:start + mx]
    items = "".join(f"<PublicKeySummary><Id>{k['Id']}</Id><Name>{esc(k['Config']['Name'])}</Name><CreatedTime>{_iso(k['Created'])}</CreatedTime>"
                    f"<EncodedKey>{esc(k['Config']['EncodedKey'])}</EncodedKey>" + (f"<Comment>{esc(k['Config']['Comment'])}</Comment>" if k["Config"]["Comment"] else "")
                    + "</PublicKeySummary>" for k in page)
    more = f"<NextMarker>{page[-1]['Id']}</NextMarker>" if start + mx < len(ks) and page else ""
    return _out(200, _xml("PublicKeyList", f"{more}<MaxItems>{mx}</MaxItems><IsTruncated>{'true' if more else 'false'}</IsTruncated><Quantity>{len(page)}</Quantity>"
                          + (f"<Items>{items}</Items>" if page else "")))


# ── key groups ──────────────────────────────────────────────────────────────
def _kg_config(st, body, exclude=None):
    cfg = _parse(body, "KeyGroupConfig")
    c = {"Name": _t(cfg, "Name"), "Items": _items(cfg, "Items", "PublicKey"), "Comment": _t(cfg, "Comment") or ""}
    if not c["Name"]:
        raise _Err(400, "InvalidArgument", "Your request is missing the required Name.")
    if not c["Items"]:
        raise _Err(400, "InvalidArgument", "A key group must contain at least one public key.")
    if len(c["Items"]) > 5:
        raise _Err(400, "TooManyPublicKeysInKeyGroup", "A key group can contain at most 5 public keys.")
    if len(set(c["Items"])) != len(c["Items"]):
        raise _Err(400, "InvalidArgument", "A public key can appear only once in a key group.")
    for pid in c["Items"]:
        if pid not in st["public_keys"]:
            raise _Err(404, "NoSuchPublicKey", f"The specified public key {pid} does not exist.")
    if any(g["Id"] != exclude and g["Config"]["Name"] == c["Name"] for g in st["key_groups"].values()):
        raise _Err(409, "KeyGroupAlreadyExists", f"A key group with the name {c['Name']} already exists.")
    return c


def create_key_group(st, headers, body):
    if len(st["key_groups"]) >= 10:
        raise _Err(400, "TooManyKeyGroups", "You cannot create more key groups: the account limit is 10.")
    g = {"Id": _id("K"), "Modified": time.time(), "Config": _kg_config(st, body), "ETag": _etag()}
    st["key_groups"][g["Id"]] = g
    return _out(201, _xml("KeyGroup", _kg_inner(g)), g["ETag"], f"https://cloudfront.amazonaws.com/2020-05-31/key-group/{g['Id']}")


def _kg(st, gid):
    g = st["key_groups"].get(gid)
    if not g:
        raise _Err(404, "NoSuchResource", "The specified key group does not exist.")
    return g


def update_key_group(st, gid, headers, body):
    g = _kg(st, gid)
    _check_if_match(g, headers)
    g["Config"], g["Modified"], g["ETag"] = _kg_config(st, body, exclude=gid), time.time(), _etag()
    return _out(200, _xml("KeyGroup", _kg_inner(g)), g["ETag"])


def delete_key_group(st, gid, headers):
    g = _kg(st, gid)
    _check_if_match(g, headers)
    del st["key_groups"][gid]
    return _out(204)


def list_key_groups(st, query):
    gs = sorted(st["key_groups"].values(), key=lambda g: g["Id"])
    mx = int(query.get("MaxItems") or 100)
    start = next((i + 1 for i, g in enumerate(gs) if g["Id"] == query.get("Marker")), 0) if query.get("Marker") else 0
    page = gs[start:start + mx]
    items = "".join(f"<KeyGroupSummary><KeyGroup>{_kg_inner(g)}</KeyGroup></KeyGroupSummary>" for g in page)
    more = f"<NextMarker>{page[-1]['Id']}</NextMarker>" if start + mx < len(gs) and page else ""
    return _out(200, _xml("KeyGroupList", f"{more}<MaxItems>{mx}</MaxItems><Quantity>{len(page)}</Quantity>" + (f"<Items>{items}</Items>" if page else "")))


# ── Vyomi extensions: root key pairs + signed-URL validation ──────────────
def _jr(status, doc):
    return _out(status, json.dumps(doc).encode(), ctype="application/json")


def _root(st, p):
    ks = st["root_keys"]
    op, kid = p.get("op"), p.get("id")
    if op == "list":
        return {"keyPairs": [{k: v for k, v in r.items() if k != "n_e"} for r in sorted(ks.values(), key=lambda r: r["created"])]}
    if op == "create":
        pem = str(p.get("publicKey") or "")
        _validate_encoded_key(pem)
        if len([r for r in ks.values()]) >= 2:
            raise _Err(400, "LimitExceeded", "An account can have at most 2 CloudFront key pairs; delete one first.")
        r = {"id": "APKA" + "".join(secrets.choice(_ALNUM) for _ in range(16)), "status": "Active", "created": time.time(), "publicKey": pem}
        ks[r["id"]] = r
        return r
    r = ks.get(kid)
    if not r:
        raise _Err(404, "NoSuchResource", "The specified CloudFront key pair does not exist.")
    if op in ("activate", "deactivate"):
        r["status"] = "Active" if op == "activate" else "Inactive"
        return r
    if op == "delete":
        del ks[kid]
        return {}
    raise _Err(400, "InvalidArgument", f"Unknown operation {op}")


def _match_resource(pattern: str, url: str) -> bool:
    rx = "^" + ".*".join(re.escape(x) for x in pattern.split("*")) + "$"
    rx = rx.replace(r"\?", ".")
    return re.match(rx, url) is not None


def validate_signed_url(st, p, now=None):
    now = time.time() if now is None else now
    raw = str(p.get("url") or "")
    u = urllib.parse.urlsplit(raw)
    q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    reasons, info = [], {}
    kid, sig = q.get("Key-Pair-Id"), q.get("Signature")
    if not kid or not sig:
        return {"valid": False, "reasons": ["The URL is missing Key-Pair-Id and/or Signature, so CloudFront returns 403 (Missing Key-Pair-Id query parameter or cookie value)."]}
    base_query = "&".join(x for x in u.query.split("&") if not x.split("=")[0] in ("Expires", "Policy", "Signature", "Key-Pair-Id"))
    resource = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, base_query, ""))
    if "Policy" in q:
        try:
            policy_text = _cf_b64decode(q["Policy"]).decode()
            policy = json.loads(policy_text)
            stmt = policy["Statement"][0]
            res, cond = stmt["Resource"], stmt.get("Condition", {})
        except Exception:
            return {"valid": False, "reasons": ["The Policy parameter is not a valid base64-encoded CloudFront policy document."]}
        signed = policy_text.encode()
        kind = "custom"
        if not _match_resource(res, resource) and not _match_resource(res, raw.split("?")[0]) and not _match_resource(res, raw):
            reasons.append(f"The policy Resource {res!r} does not match the requested URL.")
        if "DateLessThan" not in cond:
            reasons.append("The policy must contain a DateLessThan condition.")
        elif now >= float(cond["DateLessThan"]["AWS:EpochTime"]):
            reasons.append("The signed URL has expired (DateLessThan is in the past).")
        if "DateGreaterThan" in cond and now < float(cond["DateGreaterThan"]["AWS:EpochTime"]):
            reasons.append("The signed URL is not yet valid (DateGreaterThan is in the future).")
        if "IpAddress" in cond and p.get("clientIp"):
            import ipaddress
            try:
                if ipaddress.ip_address(p["clientIp"]) not in ipaddress.ip_network(cond["IpAddress"]["AWS:SourceIp"], strict=False):
                    reasons.append(f"The client IP {p['clientIp']} is outside the policy's IpAddress range.")
            except ValueError:
                reasons.append("The policy IpAddress condition or the supplied client IP is not valid.")
        info = {"policy": "custom"}
    elif "Expires" in q:
        kind = "canned"
        try:
            exp = int(q["Expires"])
        except ValueError:
            return {"valid": False, "reasons": ["Expires is not an epoch time."]}
        signed = json.dumps({"Statement": [{"Resource": resource, "Condition": {"DateLessThan": {"AWS:EpochTime": exp}}}]}, separators=(",", ":")).encode()
        if now >= exp:
            reasons.append("The signed URL has expired (Expires is in the past).")
        info = {"policy": "canned"}
    else:
        return {"valid": False, "reasons": ["The URL has neither Expires nor Policy."]}
    pub = None
    group_names = []
    if kid in st["public_keys"]:
        pub = st["public_keys"][kid]["Config"]["EncodedKey"]
        group_names = [g["Config"]["Name"] for g in st["key_groups"].values() if kid in g["Config"]["Items"]]
        want = p.get("keyGroupId")
        if want and (want not in st["key_groups"] or kid not in st["key_groups"][want]["Config"]["Items"]):
            reasons.append(f"The key {kid} is not in the trusted key group {want}.")
        elif not group_names:
            reasons.append(f"The public key {kid} is not in any key group, so no distribution can trust it.")
    elif kid in st["root_keys"]:
        r = st["root_keys"][kid]
        pub = r["publicKey"]
        if r["status"] != "Active":
            reasons.append(f"The root key pair {kid} is Inactive.")
        info["signer"] = "self (root key pair)"
    else:
        reasons.append(f"The Key-Pair-Id {kid} does not match any public key or root key pair.")
    if pub is not None:
        try:
            n, e = parse_public_key(pub)
            if not rsa_sha1_verify(n, e, signed, _cf_b64decode(sig)):
                reasons.append("The signature does not match: it was not produced by the private key for this Key-Pair-Id over this policy (RSA-SHA1).")
        except Exception:
            reasons.append("The stored public key could not be used to verify the signature.")
    return {"valid": not reasons, "reasons": reasons, "policyKind": kind, "keyGroups": group_names, **info}


_PK = re.compile(r"^/2020-05-31/public-key(?:/([^/]+)(/config)?)?$")
_KG = re.compile(r"^/2020-05-31/key-group(?:/([^/]+)(/config)?)?$")


def dispatch(s3_store, method: str, path: str, query: dict, headers: dict, body: bytes) -> dict:
    st = _state(s3_store)
    h = {k.lower(): v for k, v in (headers or {}).items()}
    method = method.upper()
    path = urllib.parse.unquote((path or "").split("?", 1)[0]).rstrip("/") or "/"
    query = query or {}
    try:
        if path.startswith("/2020-05-31/vyomi/"):
            op = path.rsplit("/", 1)[-1]
            p = json.loads(body or b"{}")
            if op == "validate-signed-url":
                return _jr(200, validate_signed_url(st, p))
            if op == "overview":      # JSON mirror of ListPublicKeys / ListKeyGroups for the console
                return _jr(200, {"publicKeys": [{"id": k["Id"], "name": k["Config"]["Name"], "comment": k["Config"]["Comment"], "created": k["Created"],
                                                 "keyGroups": [g["Config"]["Name"] for g in st["key_groups"].values() if k["Id"] in g["Config"]["Items"]]}
                                                for k in sorted(st["public_keys"].values(), key=lambda k: k["Created"])],
                                 "keyGroups": [{"id": g["Id"], "name": g["Config"]["Name"], "items": g["Config"]["Items"], "modified": g["Modified"]}
                                               for g in sorted(st["key_groups"].values(), key=lambda g: g["Modified"])]})
            if op == "root-key-pairs":
                out = _root(st, p)
                if p.get("op") != "list":
                    s3_store.persist()
                return _jr(200, out)
            raise _Err(404, "NoSuchResource", "Unknown Vyomi CloudFront extension.")
        m = _PK.match(path)
        if m:
            kid, cfg = m.groups()
            if not kid:
                if method == "POST":
                    r = create_public_key(st, h, body)
                elif method == "GET":
                    r = list_public_keys(st, query)
                else:
                    raise _Err(405, "MethodNotAllowed", "Method not allowed")
            elif cfg:
                k = _pk(st, kid)
                if method == "GET":
                    r = _out(200, _xml("PublicKeyConfig", _pk_config_xml(k["Config"])), k["ETag"])
                elif method == "PUT":
                    r = update_public_key(st, kid, h, body)
                else:
                    raise _Err(405, "MethodNotAllowed", "Method not allowed")
            elif method == "GET":
                k = _pk(st, kid)
                r = _out(200, _pk_xml(k), k["ETag"])
            elif method == "DELETE":
                r = delete_public_key(st, kid, h)
            else:
                raise _Err(405, "MethodNotAllowed", "Method not allowed")
        else:
            m = _KG.match(path)
            if not m:
                raise _Err(404, "NoSuchResource", f"Unsupported CloudFront operation: {method} {path} (only public keys and key groups are implemented).")
            gid, cfg = m.groups()
            if not gid:
                if method == "POST":
                    r = create_key_group(st, h, body)
                elif method == "GET":
                    r = list_key_groups(st, query)
                else:
                    raise _Err(405, "MethodNotAllowed", "Method not allowed")
            elif cfg:
                g = _kg(st, gid)
                if method == "GET":
                    r = _out(200, _xml("KeyGroupConfig", _kg_config_xml(g["Config"])), g["ETag"])
                else:
                    raise _Err(405, "MethodNotAllowed", "Method not allowed")
            elif method == "GET":
                g = _kg(st, gid)
                r = _out(200, _xml("KeyGroup", _kg_inner(g)), g["ETag"])
            elif method == "PUT":
                r = update_key_group(st, gid, h, body)
            elif method == "DELETE":
                r = delete_key_group(st, gid, h)
            else:
                raise _Err(405, "MethodNotAllowed", "Method not allowed")
        if method != "GET":
            s3_store.persist()
        return r
    except _Err as e:
        return {"status": e.status, "headers": {"content-type": "text/xml", "x-amzn-errortype": e.code},
                "body": f'<?xml version="1.0"?><ErrorResponse xmlns="{NS}"><Error><Type>Sender</Type><Code>{e.code}</Code>'
                        f'<Message>{esc(e.message)}</Message></Error><RequestId>{_id("R")}</RequestId></ErrorResponse>'.encode()}
    except (ValueError, KeyError) as e:
        return {"status": 400, "headers": {"content-type": "text/xml", "x-amzn-errortype": "InvalidArgument"},
                "body": f'<?xml version="1.0"?><ErrorResponse xmlns="{NS}"><Error><Type>Sender</Type><Code>InvalidArgument</Code>'
                        f'<Message>{esc(str(e))}</Message></Error></ErrorResponse>'.encode()}
