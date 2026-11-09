"""Amazon EKS cluster authentication: the verifier side of ``aws eks get-token`` / ``aws-iam-authenticator``.

How a real EKS client authenticates (and what this module does with it):

  1. ``aws eks update-kubeconfig`` writes a kubeconfig whose user is an *exec plugin*: ``aws eks get-token --cluster-name C``.
  2. ``aws eks get-token`` PRESIGNS (SigV4 query-string auth, X-Amz-Expires=60) an STS ``GetCallerIdentity`` GET for
     ``sts.<region>.amazonaws.com`` with ``x-k8s-aws-id: C`` as a signed header, and prints the ExecCredential JSON whose token is
     ``"k8s-aws-v1." + base64url(presigned URL)`` (no padding).
  3. kubectl sends it as ``Authorization: Bearer <token>``. The EKS control plane's authenticator webhook (aws-iam-authenticator)
     decodes the URL, validates it (host is an STS endpoint, Action/Version, signed headers, expiry), CALLS that URL to learn the
     caller identity, and maps the IAM principal to a Kubernetes user + groups (access entries / aws-auth ConfigMap).

``verify_token`` is step 3 with one substitution: instead of calling STS it verifies the SigV4 signature LOCALLY against the secret of
the access key (the simulator owns the IAM store, so the secret is known) and resolves the identity from the same store -- the result
is the identical decision STS would make. ``authorize`` is the access-entry -> Kubernetes identity mapping. ``token_review`` wraps both
in the authentication.k8s.io TokenReview contract, i.e. the body an apiserver ``--authentication-token-webhook-config-file`` webhook sends
and expects back (see docs/architecture/v4.0/EKS-AUTH.md for how the platform layer plugs it into k3s).

Substrate-free (stdlib only). Not built: the aws-auth ConfigMap (CONFIG_MAP authentication mode), IRSA / Pod Identity token exchange,
assumed-role credentials unless the injected ``credentials`` resolver knows them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urlsplit

TOKEN_PREFIX = "k8s-aws-v1."
MAX_EXPIRES = 60                       # aws-iam-authenticator rejects presigned URLs valid for longer than this
MAX_TOKEN_AGE = timedelta(minutes=15)  # ... and tokens older than 15 minutes (kubectl re-execs get-token before then)
CLOCK_SKEW = timedelta(minutes=5)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
STS_HOST_RE = re.compile(r"^sts(\.[a-z0-9-]+)?\.amazonaws\.com(\.cn)?$")

# EKS access policies -> the built-in Kubernetes ClusterRole each one grants (what the real authorizer evaluates).
POLICY_CLUSTER_ROLE = {
    "AmazonEKSClusterAdminPolicy": "cluster-admin",
    "AmazonEKSAdminPolicy": "admin",
    "AmazonEKSEditPolicy": "edit",
    "AmazonEKSViewPolicy": "view",
    "AmazonEKSAdminViewPolicy": "view",
}


class TokenError(Exception):
    """A rejected token. ``code`` mirrors what the authenticator would log (InvalidToken / ExpiredToken / SignatureDoesNotMatch ...)."""

    def __init__(self, code, message):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


# ── SigV4 query-string signing (generation = what `aws eks get-token` does; used by tests and the console) ──────────────────
def _enc(s):
    return quote(str(s), safe="-_.~")


def _canonical_query(params):
    return "&".join("%s=%s" % (_enc(k), _enc(v)) for k, v in sorted((str(k), str(v)) for k, v in params.items()))


def _hmac(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret, date, region, service):
    return _hmac(_hmac(_hmac(_hmac(("AWS4" + secret).encode(), date), region), service), "aws4_request")


def _signature(secret, params, host, headers, signed_headers, region, service="sts"):
    """SigV4 for a presigned GET ``/`` (the payload hash is SHA-256 of the empty body, exactly as botocore's STS presigner)."""
    q = {k: v for k, v in params.items() if k != "X-Amz-Signature"}
    canon_headers = "".join("%s:%s\n" % (h, " ".join(str(headers[h]).split())) for h in signed_headers)
    canonical = "\n".join(["GET", "/", _canonical_query(q), canon_headers, ";".join(signed_headers), EMPTY_SHA256])
    date = params["X-Amz-Date"]
    scope = "%s/%s/%s/aws4_request" % (date[:8], region, service)
    sts = "\n".join(["AWS4-HMAC-SHA256", date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    return hmac.new(_signing_key(secret, date[:8], region, service), sts.encode(), hashlib.sha256).hexdigest()


def generate_token(cluster_name, access_key_id, secret_access_key, region="us-east-1", session_token=None, now=None, host=None):
    """The token `aws eks get-token --cluster-name <cluster_name>` prints (byte-for-byte the same construction)."""
    now = now or datetime.now(timezone.utc)
    host = host or ("sts.%s.amazonaws.com" % region)
    date = now.strftime("%Y%m%dT%H%M%SZ")
    params = {"Action": "GetCallerIdentity", "Version": "2011-06-15", "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
              "X-Amz-Credential": "%s/%s/%s/sts/aws4_request" % (access_key_id, date[:8], region),
              "X-Amz-Date": date, "X-Amz-Expires": str(MAX_EXPIRES), "X-Amz-SignedHeaders": "host;x-k8s-aws-id"}
    if session_token:
        params["X-Amz-Security-Token"] = session_token
    sig = _signature(secret_access_key, params, host, {"host": host, "x-k8s-aws-id": cluster_name}, ["host", "x-k8s-aws-id"], region)
    url = "https://%s/?%s&X-Amz-Signature=%s" % (host, _canonical_query(params), sig)
    return TOKEN_PREFIX + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def decode_token(token):
    """The presigned STS URL inside a ``k8s-aws-v1.`` token."""
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX):
        raise TokenError("InvalidToken", "token is missing the expected %r prefix" % TOKEN_PREFIX)
    b = token[len(TOKEN_PREFIX):]
    try:
        return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
    except Exception:
        raise TokenError("InvalidToken", "token is not valid base64url")


# ── credential resolution (the part STS does) ────────────────────────────────────────────────────────────────────────────
def iam_store_credentials(iam_store, account="123456789012"):
    """Default ``credentials`` resolver over core/iam_store: IAM-user access keys -> ``{"secret", "arn", "account", "user_id"}``.
    Temporary (assumed-role) credentials need an STS-session-aware resolver: inject your own with the same signature."""
    def resolve(access_key_id, security_token=None):
        k = (getattr(iam_store, "access_keys", None) or {}).get(access_key_id)
        if not k or k.get("status", "Active") != "Active":
            return None
        user = k.get("user_name") or "unknown"
        return {"secret": k["secret_access_key"], "arn": "arn:aws:iam::%s:user/%s" % (account, user), "account": account,
                "user_id": "AIDA" + hashlib.sha1(user.encode()).hexdigest()[:17].upper()}
    return resolve


def canonical_principal(arn):
    """``arn:aws:sts::A:assumed-role/Role/session`` -> ``arn:aws:iam::A:role/Role`` (what access entries are keyed by)."""
    m = re.match(r"^arn:(aws[a-z-]*):sts::(\d{12}):assumed-role/([^/]+)/.+$", arn or "")
    return "arn:%s:iam::%s:role/%s" % (m.group(1), m.group(2), m.group(3)) if m else arn


def verify_token(token, cluster_name, credentials, now=None, extra_hosts=(), verify_signature=True):
    """Validate a bearer token exactly as the authenticator does, then resolve the caller. Returns
    ``{"arn", "principal", "account", "user_id", "accessKeyId", "sessionName"}`` or raises ``TokenError``.

    ``credentials(access_key_id, security_token) -> {"secret", "arn", "account", "user_id"} | None`` plays STS's role. ``extra_hosts``
    lists additional hosts accepted as the STS endpoint (the simulator's own endpoint host, for clients that presign against it)."""
    now = now or datetime.now(timezone.utc)
    url = urlsplit(decode_token(token))
    if url.scheme != "https":
        raise TokenError("InvalidToken", "presigned URL must be https")
    host = url.hostname or ""
    if not STS_HOST_RE.match(host) and host not in tuple(extra_hosts):
        raise TokenError("InvalidToken", "host %r is not an STS endpoint" % host)
    if url.path not in ("", "/"):
        raise TokenError("InvalidToken", "unexpected path %r" % url.path)
    pairs = parse_qsl(url.query, keep_blank_values=True)
    q = dict(pairs)
    if len(q) != len(pairs):
        raise TokenError("InvalidToken", "duplicate query parameters")
    if q.get("Action") != "GetCallerIdentity" or q.get("Version") != "2011-06-15":
        raise TokenError("InvalidToken", "presigned request must be sts:GetCallerIdentity (Version 2011-06-15)")
    allowed = {"Action", "Version", "X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date", "X-Amz-Expires", "X-Amz-SignedHeaders",
               "X-Amz-Signature", "X-Amz-Security-Token"}
    if set(q) - allowed:
        raise TokenError("InvalidToken", "unexpected parameters: %s" % ", ".join(sorted(set(q) - allowed)))
    for need in ("X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date", "X-Amz-Expires", "X-Amz-SignedHeaders", "X-Amz-Signature"):
        if need not in q:
            raise TokenError("InvalidToken", "missing %s" % need)
    if q["X-Amz-Algorithm"] != "AWS4-HMAC-SHA256":
        raise TokenError("InvalidToken", "unsupported signing algorithm")
    signed = q["X-Amz-SignedHeaders"].split(";")
    if "x-k8s-aws-id" not in signed:
        raise TokenError("InvalidToken", "x-k8s-aws-id must be a signed header (tokens are bound to one cluster)")
    if set(signed) - {"host", "x-k8s-aws-id"}:
        raise TokenError("InvalidToken", "unexpected signed headers: %s" % ";".join(sorted(set(signed) - {"host", "x-k8s-aws-id"})))
    try:
        expires = int(q["X-Amz-Expires"])
        issued = datetime.strptime(q["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise TokenError("InvalidToken", "malformed X-Amz-Date / X-Amz-Expires")
    if expires > MAX_EXPIRES or expires <= 0:
        raise TokenError("InvalidToken", "X-Amz-Expires must be 1..%d seconds" % MAX_EXPIRES)
    if now > issued + MAX_TOKEN_AGE:     # STS honours a 15-minute window for these URLs (X-Amz-Expires is only capped at 60)
        raise TokenError("ExpiredToken", "token expired")
    if issued - now > CLOCK_SKEW:
        raise TokenError("InvalidToken", "token is dated in the future")
    parts = q["X-Amz-Credential"].split("/")
    if len(parts) != 5 or parts[3] != "sts" or parts[4] != "aws4_request" or parts[1] != q["X-Amz-Date"][:8]:
        raise TokenError("InvalidToken", "malformed X-Amz-Credential scope")
    akid, region = parts[0], parts[2]
    cred = credentials(akid, q.get("X-Amz-Security-Token"))
    if cred is None:
        raise TokenError("InvalidClientTokenId", "The security token included in the request is invalid.")
    if verify_signature:
        want = _signature(cred["secret"], q, host, {"host": url.netloc, "x-k8s-aws-id": cluster_name}, signed, region)
        if not hmac.compare_digest(want, q["X-Amz-Signature"]):
            raise TokenError("SignatureDoesNotMatch", "The request signature we calculated does not match (wrong secret key, or the "
                             "token was minted for another cluster than %r)." % cluster_name)
    arn = cred["arn"]
    m = re.match(r"^arn:aws[a-z-]*:sts::\d{12}:assumed-role/[^/]+/(.+)$", arn)
    return {"arn": arn, "principal": canonical_principal(arn), "account": cred["account"], "user_id": cred.get("user_id", ""),
            "accessKeyId": akid, "sessionName": m.group(1) if m else ""}


# ── identity -> Kubernetes user (access entries) ─────────────────────────────────────────────────────────────────────────
def authorize(cluster, identity):
    """Map a verified IAM identity to a Kubernetes identity using the cluster record's access entries (``cluster["_access"]``, the
    store core/aws_eks_core maintains). Returns ``{"username", "uid", "groups", "bindings"}`` or None when the principal has no access
    entry (the real authenticator answers Unauthorized).

    ``bindings`` lists the ClusterRole grants of the associated access policies ({clusterRole, scope: cluster|namespace, namespaces}); a
    cluster-scoped AmazonEKSClusterAdminPolicy also yields the ``system:masters`` group, the only grant expressible as a group alone. The
    platform layer materialises the rest as (Cluster)RoleBindings to the ``vyomi:eks:<clusterRole>[:<ns>]`` groups also returned."""
    entry = ((cluster.get("_access") or {}).get(identity["principal"]))
    if entry is None:
        return None
    etype = entry.get("type", "STANDARD")
    uname = entry.get("username") or ""
    if etype == "STANDARD" and "{{SessionName}}" in uname:
        uname = uname.replace("{{SessionName}}", identity.get("sessionName") or "")
    if not uname:
        uname = identity["principal"] if ":user/" in identity["principal"] else identity["arn"]
    groups = list(entry.get("kubernetesGroups") or [])
    bindings = []
    for pol in (entry.get("_policies") or {}).values():
        name = pol["policyArn"].rsplit("/", 1)[-1]
        role = POLICY_CLUSTER_ROLE.get(name)
        if not role:
            continue
        sc = pol.get("accessScope") or {"type": "cluster"}
        bindings.append({"clusterRole": role, "scope": sc.get("type", "cluster"), "namespaces": list(sc.get("namespaces") or [])})
        if sc.get("type", "cluster") == "cluster":
            groups.append("system:masters" if role == "cluster-admin" else "vyomi:eks:" + role)
        else:
            groups += ["vyomi:eks:%s:%s" % (role, ns) for ns in sc.get("namespaces") or []]
    return {"username": uname, "uid": "aws-iam-authenticator:%s:%s" % (identity["account"], identity.get("user_id") or ""),
            "groups": list(dict.fromkeys(groups)), "bindings": bindings}


def token_review(review, cluster, credentials, now=None, extra_hosts=()):
    """authentication.k8s.io TokenReview in, TokenReview out -- the webhook contract of ``--authentication-token-webhook-config-file``
    (aws-iam-authenticator speaks exactly this). Never raises: a rejected token is ``status.authenticated=false`` with an error string."""
    token = ((review or {}).get("spec") or {}).get("token", "")
    api = (review or {}).get("apiVersion") or "authentication.k8s.io/v1"
    out = {"apiVersion": api, "kind": "TokenReview"}
    try:
        ident = verify_token(token, cluster["name"], credentials, now=now, extra_hosts=extra_hosts)
        k = authorize(cluster, ident)
        if k is None:
            raise TokenError("AccessDenied", "%s has no access entry on cluster %s" % (ident["principal"], cluster["name"]))
    except TokenError as e:
        out["status"] = {"authenticated": False, "error": str(e)}
        return out
    out["status"] = {"authenticated": True, "user": {"username": k["username"], "uid": k["uid"], "groups": k["groups"],
                                                      "extra": {"arn": [ident["arn"]], "canonicalArn": [ident["principal"]],
                                                                "sessionName": [ident["sessionName"]]}}}
    return out
