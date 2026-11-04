"""CloudFront public keys, key groups, root key pairs and signed-URL validation (AWS-07 leftover) via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_cloudfront_keys.py
"""
import base64
import json
import re
import time

import os
import subprocess
import tempfile

from core.aws_wire_router import AwsWireRouter

CF = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/cloudfront/aws4_request, SignedHeaders=host, Signature=0"
NS = 'xmlns="http://cloudfront.amazonaws.com/doc/2020-05-31/"'


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(r, method, path, body="", headers=None):
    out = r.handle(method, path, {}, {"authorization": CF, "content-type": "text/xml", **(headers or {})}, body.encode() if isinstance(body, str) else body)
    return out["status"], out["body"].decode(), {k.lower(): v for k, v in out["headers"].items()}


def vyomi(r, op, doc):
    s, b, _ = call(r, "POST", f"/2020-05-31/vyomi/{op}", json.dumps(doc))
    return s, json.loads(b)


def keypair(bits=2048):
    """(private key path, public PEM) using the openssl CLI - the simulator itself needs no crypto library."""
    d = tempfile.mkdtemp()
    key = os.path.join(d, "k.pem")
    subprocess.run(["openssl", "genrsa", "-out", key, str(bits)], check=True, capture_output=True)
    pem = subprocess.run(["openssl", "rsa", "-in", key, "-pubout"], check=True, capture_output=True).stdout.decode()
    return key, pem


def b64(raw):
    return base64.b64encode(raw).decode().replace("+", "-").replace("=", "_").replace("/", "~")


def sign(priv, policy: bytes):
    raw = subprocess.run(["openssl", "dgst", "-sha1", "-sign", priv], input=policy, check=True, capture_output=True).stdout
    return b64(raw)


def pk_xml(name, ref, key, comment=""):
    return f"<PublicKeyConfig {NS}><CallerReference>{ref}</CallerReference><Name>{name}</Name><EncodedKey>{key}</EncodedKey><Comment>{comment}</Comment></PublicKeyConfig>"


def main():
    r = AwsWireRouter()
    priv, pem = keypair()
    s, b, h = call(r, "POST", "/2020-05-31/public-key", pk_xml("signer-1", "ref-1", pem, "primary"))
    kid = re.search(r"<Id>(K\w+)</Id>", b).group(1)
    _check("CreatePublicKey 201 with Id + ETag", s == 201 and len(kid) == 14 and h.get("etag"))
    s, b, _ = call(r, "POST", "/2020-05-31/public-key", pk_xml("signer-1", "ref-2", pem))
    _check("duplicate name -> PublicKeyAlreadyExists 409", s == 409 and "PublicKeyAlreadyExists" in b)
    _, bad = keypair(1024)
    s, b, _ = call(r, "POST", "/2020-05-31/public-key", pk_xml("small", "ref-3", bad))
    _check("1024-bit key rejected", s == 400 and "2048" in b)
    s, b, _ = call(r, "POST", "/2020-05-31/public-key", pk_xml("junk", "ref-4", "not a key"))
    _check("garbage key rejected", s == 400)
    s, b, h = call(r, "GET", f"/2020-05-31/public-key/{kid}")
    _check("GetPublicKey", s == 200 and "<Name>signer-1</Name>" in b)
    s, b, _ = call(r, "GET", "/2020-05-31/public-key/KDOESNOTEXIST")
    _check("missing -> NoSuchPublicKey 404", s == 404 and "NoSuchPublicKey" in b)
    s, b, _ = call(r, "PUT", f"/2020-05-31/public-key/{kid}/config", pk_xml("signer-1", "ref-1", pem, "new comment"))
    _check("update without If-Match -> InvalidIfMatchVersion", s == 400 and "InvalidIfMatchVersion" in b)
    s, b, _ = call(r, "PUT", f"/2020-05-31/public-key/{kid}/config", pk_xml("signer-1", "ref-1", pem, "new comment"), {"if-match": "EWRONG"})
    _check("stale If-Match -> PreconditionFailed 412", s == 412)
    etag = call(r, "GET", f"/2020-05-31/public-key/{kid}")[2]["etag"]
    s, b, h2 = call(r, "PUT", f"/2020-05-31/public-key/{kid}/config", pk_xml("signer-1", "ref-1", pem, "new comment"), {"if-match": etag})
    _check("UpdatePublicKey", s == 200 and "new comment" in b and h2["etag"] != etag)
    _, pem2 = keypair()
    s, b, _ = call(r, "PUT", f"/2020-05-31/public-key/{kid}/config", pk_xml("signer-1", "ref-1", pem2), {"if-match": h2["etag"]})
    _check("EncodedKey is immutable", s == 400 and "IllegalUpdate" in b)

    kg = lambda items, name="kg-1": f"<KeyGroupConfig {NS}><Name>{name}</Name><Items>" + "".join(f"<PublicKey>{i}</PublicKey>" for i in items) + "</Items></KeyGroupConfig>"
    s, b, _ = call(r, "POST", "/2020-05-31/key-group", kg(["KNOPE"]))
    _check("key group with a missing public key -> NoSuchPublicKey", s == 404 and "NoSuchPublicKey" in b)
    s, b, _ = call(r, "POST", "/2020-05-31/key-group", kg([]))
    _check("empty key group rejected", s == 400)
    s, b, hk = call(r, "POST", "/2020-05-31/key-group", kg([kid]))
    gid = re.search(r"<Id>(K\w+)</Id>", b).group(1)
    _check("CreateKeyGroup", s == 201 and f"<PublicKey>{kid}</PublicKey>" in b)
    s, b, _ = call(r, "POST", "/2020-05-31/key-group", kg([kid]))
    _check("duplicate key group name -> KeyGroupAlreadyExists", s == 409 and "KeyGroupAlreadyExists" in b)
    s, b, _ = call(r, "GET", "/2020-05-31/key-group")
    _check("ListKeyGroups", "<Quantity>1</Quantity>" in b and gid in b)
    s, b, _ = call(r, "GET", "/2020-05-31/public-key")
    _check("ListPublicKeys", "<Quantity>1</Quantity>" in b and kid in b)
    etag = call(r, "GET", f"/2020-05-31/public-key/{kid}")[2]["etag"]
    s, b, _ = call(r, "DELETE", f"/2020-05-31/public-key/{kid}", headers={"if-match": etag})
    _check("public key in a key group cannot be deleted -> PublicKeyInUse 409", s == 409 and "PublicKeyInUse" in b)

    # signed URL validation
    base = "https://d111111abcdef8.cloudfront.net/private/video.mp4"
    exp = int(time.time()) + 600
    canned = json.dumps({"Statement": [{"Resource": base, "Condition": {"DateLessThan": {"AWS:EpochTime": exp}}}]}, separators=(",", ":")).encode()
    url = f"{base}?Expires={exp}&Signature={sign(priv, canned)}&Key-Pair-Id={kid}"
    s, v = vyomi(r, "validate-signed-url", {"url": url})
    _check("valid canned-policy URL", s == 200 and v["valid"] and v["policyKind"] == "canned" and v["keyGroups"] == ["kg-1"])
    s, v = vyomi(r, "validate-signed-url", {"url": url.replace("video.mp4", "other.mp4")})
    _check("URL for a different resource fails the signature", not v["valid"] and any("signature" in x.lower() for x in v["reasons"]))
    old = int(time.time()) - 5
    canned_old = json.dumps({"Statement": [{"Resource": base, "Condition": {"DateLessThan": {"AWS:EpochTime": old}}}]}, separators=(",", ":")).encode()
    s, v = vyomi(r, "validate-signed-url", {"url": f"{base}?Expires={old}&Signature={sign(priv, canned_old)}&Key-Pair-Id={kid}"})
    _check("expired URL", not v["valid"] and any("expired" in x for x in v["reasons"]))
    pol = json.dumps({"Statement": [{"Resource": "https://d111111abcdef8.cloudfront.net/private/*", "Condition": {
        "DateLessThan": {"AWS:EpochTime": exp}, "IpAddress": {"AWS:SourceIp": "203.0.113.0/24"}}}]}, separators=(",", ":")).encode()
    curl = f"{base}?Policy={b64(pol)}&Signature={sign(priv, pol)}&Key-Pair-Id={kid}"
    s, v = vyomi(r, "validate-signed-url", {"url": curl, "clientIp": "203.0.113.9"})
    _check("valid custom policy with wildcard + IP", v["valid"] and v["policyKind"] == "custom")
    s, v = vyomi(r, "validate-signed-url", {"url": curl, "clientIp": "198.51.100.1"})
    _check("client IP outside the policy range", not v["valid"] and any("IP" in x for x in v["reasons"]))
    s, v = vyomi(r, "validate-signed-url", {"url": curl, "keyGroupId": "KNOTTHISONE"})
    _check("key not in the required key group", not v["valid"])
    other, _ = keypair()
    s, v = vyomi(r, "validate-signed-url", {"url": f"{base}?Expires={exp}&Signature={sign(other, canned)}&Key-Pair-Id={kid}"})
    _check("signature by a different private key fails", not v["valid"])
    s, v = vyomi(r, "validate-signed-url", {"url": f"{base}?Expires={exp}"})
    _check("missing Key-Pair-Id/Signature", not v["valid"])

    # root key pairs (legacy account-level)
    rp, rpem = keypair()
    s, k = vyomi(r, "root-key-pairs", {"op": "create", "publicKey": rpem})
    _check("create root key pair", s == 200 and k["id"].startswith("APKA") and k["status"] == "Active")
    ru = f"{base}?Expires={exp}&Signature={sign(rp, canned)}&Key-Pair-Id={k['id']}"
    s, v = vyomi(r, "validate-signed-url", {"url": ru})
    _check("URL signed by an active root key pair is valid", v["valid"] and v.get("signer", "").startswith("self"))
    vyomi(r, "root-key-pairs", {"op": "deactivate", "id": k["id"]})
    s, v = vyomi(r, "validate-signed-url", {"url": ru})
    _check("inactive root key pair is rejected", not v["valid"])
    s, l = vyomi(r, "root-key-pairs", {"op": "list"})
    _check("list root key pairs", len(l["keyPairs"]) == 1 and l["keyPairs"][0]["status"] == "Inactive")
    s, _ = vyomi(r, "root-key-pairs", {"op": "delete", "id": k["id"]})
    _check("delete root key pair", s == 200 and vyomi(r, "root-key-pairs", {"op": "list"})[1]["keyPairs"] == [])

    # tear down
    g_etag = call(r, "GET", f"/2020-05-31/key-group/{gid}")[2]["etag"]
    _check("DeleteKeyGroup", call(r, "DELETE", f"/2020-05-31/key-group/{gid}", headers={"if-match": g_etag})[0] == 204)
    etag = call(r, "GET", f"/2020-05-31/public-key/{kid}")[2]["etag"]
    _check("DeletePublicKey once unused", call(r, "DELETE", f"/2020-05-31/public-key/{kid}", headers={"if-match": etag})[0] == 204)
    print("cloudfront keys conformance OK")


if __name__ == "__main__":
    main()
