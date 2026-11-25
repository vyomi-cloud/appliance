"""AWS request -> required IAM action(s) + resource ARN(s)  (contract: docs/architecture/v4.0/IAM-ENGINE-CONTRACT.md).

    required(http_request) -> [{"action": "s3:GetObject", "resource": "arn:aws:s3:::b/k", "service": "s3", "operation": "GetObject"}, ...]

`http_request` is the shape the AWS wire router receives: {"method", "path" (may carry "?query"), "query" (dict of str|list, or a raw
string), "headers" (any case), "body" (bytes|str), optional "account" (the caller's account id; default DEFAULT_ACCOUNT)}.
Several entries mean the API needs several actions (or the same action on several resources); AWS requires ALL of them.

Pure Python, stdlib only, no fastapi/socket imports (vendored into Pyodide). Data-driven:
  * service + operation come from the wire: SigV4 credential scope, X-Amz-Target, Action=, or a REST route table
    (core/iam_engine/aws_routes_data.py, generated from botocore models by scripts/gen_iam_aws_routes.py);
  * actions come from the catalog `operations` map (core/iam_catalog/aws/<prefix>.json), ARNs from the catalog resource formats.
Hand overrides for wire quirks are the entries of OVERRIDES below, each with its reason.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import parse_qsl, unquote

from . import aws_routes_data

DEFAULT_ACCOUNT = "123456789012"
DEFAULT_REGION = "us-east-1"
PARTITION = "aws"

# Every hand-written rule in this module, with the reason (the data-driven path handles everything else).
OVERRIDES = {
    "s3.host-style": "virtual-host style (bucket.s3.<region>.amazonaws.com) and access-point hosts carry the bucket in the Host header, not the path",
    "s3.catalog-superset": "the catalog lists every action an S3 API MAY authorise (PutObject -> Acl/Tagging/Retention/LegalHold); conditional ones apply only when the request carries the matching header/param",
    "s3.versions": "a request with ?versionId authorises s3:<Verb>ObjectVersion* INSTEAD of s3:<Verb>Object*",
    "s3.copy": "CopyObject / UploadPartCopy authorise GetObject on the x-amz-copy-source object and PutObject on the destination",
    "sqs.queue-url": "SQS addresses a queue by QueueUrl (http://host/<account>/<name>); the ARN needs name + account",
    "apigateway.method-actions": "API Gateway management APIs authorise apigateway:<HTTP method> on arn:aws:apigateway:<region>::<path> (v2 paths drop the /v2 prefix)",
    "execute-api.data-plane": "execute-api:Invoke is authorised on arn:aws:execute-api:<region>:<acct>:<apiId>/<stage>/<METHOD>/<path>; ManageConnections for @connections",
    "kms.alias": "a KeyId of the form alias/<n> is authorised on the alias ARN (the simulator cannot resolve alias -> key at mapping time)",
    "cloudwatch.cbor": "boto3 >= 1.40 may speak smithy-rpc-v2-cbor to CloudWatch (/service/<svc>/operation/<Op>); the operation is read from the path and the CBOR body is decoded (_cbor_loads) so resources bind exactly like the JSON/query protocols",
    "execute-api.api-id": "the REST API id is resolved from the host label, then from the path-style forms /restapis/<id>/<stage>/_user_request_/.., /apigw/<id>/<stage>/.. and /<id>/<stage>/.. (id = 10 lowercase alphanumerics) so the API's resource policy matches",
    "s3.delete-objects": "DeleteObjects authorises s3:DeleteObject (s3:DeleteObjectVersion for a keyed VersionId) on EACH <Key> of the XML body, not on the bucket-wide wildcard",
    "service-hint": "a host adapter that already knows the request is S3 (anonymous traffic has no signature and an arbitrary Host header) passes http_request['service_hint']='s3'",
    "ec2.run-instances": "RunInstances is also authorised on the new instance/network-interface/volume (wildcard ARNs: they do not exist yet)",
    "create-noun": "catalog gap: Create* actions that list no resource type (eks:CreateCluster) use the resource type named by the operation noun",
    "name-fallback": "a catalog variable <X>Name with no matching parameter falls back to the generic `Name`/`name` parameter (CreateTopic Name, EKS /clusters/{name})",
    "conditional-extra-actions": "when the operation name is itself one of its catalog actions, the OTHER listed actions are conditional and are added only when the request carries a parameter naming them (tags -> TagResource, acl -> *Acl, ...)",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
_CATALOG_DIR = os.path.join(os.path.dirname(_HERE), "iam_catalog", "aws")
_catalog_cache = {}
_catalog_loader = None


def set_catalog_loader(fn):
    """Host hook (Pyodide/Nano): fn(prefix) -> catalog dict | None. Default reads core/iam_catalog/aws/<prefix>.json."""
    global _catalog_loader
    _catalog_loader = fn
    _catalog_cache.clear()


def catalog(prefix):
    if prefix in _catalog_cache:
        return _catalog_cache[prefix]
    cat = None
    try:
        if _catalog_loader:
            cat = _catalog_loader(prefix)
        else:
            with open(os.path.join(_CATALOG_DIR, prefix + ".json")) as f:
                cat = json.load(f)
    except (OSError, ValueError):
        cat = None
    _catalog_cache[prefix] = cat
    return cat


def prefixes():
    return sorted(aws_routes_data.ROUTES["prefixes"])


# --------------------------------------------------------------------------------------------- request parsing
_CRED_RE = re.compile(r"Credential=([^/,\s]+)/(\d{8})/([^/,\s]*)/([^/,\s]+)/aws4_request")
_norm_re = re.compile(r"[^a-z0-9]")


def _norm(s):
    return _norm_re.sub("", str(s).lower())


def _lower(h):
    return {str(k).lower(): ("" if v is None else str(v)) for k, v in (h or {}).items()}


def _parse_query(q):
    out = {}
    if not q:
        return out
    if isinstance(q, str):
        pairs = parse_qsl(q, keep_blank_values=True)
    else:
        pairs = []
        for k, v in q.items():
            if isinstance(v, (list, tuple)):
                pairs.extend((k, x) for x in v)
            else:
                pairs.append((k, v))
    for k, v in pairs:
        out.setdefault(str(k), []).append("" if v is None else str(v))
    return out


def _scope(h, q):
    m = _CRED_RE.search(h.get("authorization", ""))
    if m:
        return {"akid": m.group(1), "date": m.group(2), "region": m.group(3), "signing": m.group(4)}
    cred = (q.get("X-Amz-Credential") or [""])[0]
    if cred:
        parts = unquote(cred).split("/")
        if len(parts) >= 5:
            return {"akid": parts[0], "date": parts[1], "region": parts[2], "signing": parts[3]}
    return {}


def _flatten(obj, out, depth=0):
    """Collect last-key -> scalar values from a decoded JSON body (any depth <= 4)."""
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _flatten(v, out, depth + 1)
            elif v is not None and v != "":
                out.setdefault(_norm(k), []).append(str(v))
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                _flatten(v, out, depth + 1)


def _cbor_loads(data):
    """Minimal CBOR (RFC 8949) decoder for smithy-rpc-v2-cbor request bodies: ints, bytes/text, arrays, maps, tags, simple values,
    float16/32/64 (indefinite lengths included). Raises ValueError on malformed input."""
    import struct

    def item(i, depth=0):
        if depth > 16:
            raise ValueError("too deep")
        ib = data[i]
        i += 1
        major, info = ib >> 5, ib & 31
        if major == 7 and info >= 25 and info <= 27:
            n = {25: 2, 26: 4, 27: 8}[info]
            raw = data[i:i + n]
            if len(raw) != n:
                raise ValueError("short")
            if info == 25:
                h = int.from_bytes(raw, "big")
                e, m = (h >> 10) & 31, h & 1023
                v = (m / 1024.0 if e == 0 else (float("inf") if e == 31 and m == 0 else (float("nan") if e == 31 else (1 + m / 1024.0) * 2.0 ** (e - 15))))
                return (-v if h & 0x8000 else v), i + n
            return struct.unpack(">f" if info == 26 else ">d", raw)[0], i + n
        if info < 24:
            arg = info
        elif info in (24, 25, 26, 27):
            n = 1 << (info - 24)
            raw = data[i:i + n]
            if len(raw) != n:
                raise ValueError("short")
            arg, i = int.from_bytes(raw, "big"), i + n
        elif info == 31:
            arg = None
        else:
            raise ValueError("reserved")
        if major == 0:
            return arg, i
        if major == 1:
            return -1 - arg, i
        if major in (2, 3):
            if arg is None:
                buf = b""
                while data[i] != 0xFF:
                    chunk, i = item(i, depth + 1)
                    buf += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
                i += 1
            else:
                buf, i = data[i:i + arg], i + arg
                if len(buf) != arg:
                    raise ValueError("short")
            return (bytes(buf) if major == 2 else bytes(buf).decode("utf-8", "replace")), i
        if major == 4:
            out = []
            while (arg is None and data[i] != 0xFF) or (arg is not None and len(out) < arg):
                v, i = item(i, depth + 1)
                out.append(v)
            return out, (i + 1 if arg is None else i)
        if major == 5:
            out, n = {}, 0
            while (arg is None and data[i] != 0xFF) or (arg is not None and n < arg):
                k, i = item(i, depth + 1)
                v, i = item(i, depth + 1)
                out[k if isinstance(k, str) else str(k)] = v
                n += 1
            return out, (i + 1 if arg is None else i)
        if major == 6:
            return item(i, depth + 1)
        return {20: False, 21: True, 22: None, 23: None}.get(info), i      # simple values

    val, end = item(0)
    return val


def _form_key(k):
    parts = [p for p in k.split(".") if p and not p.isdigit() and p.lower() != "member"]
    return _norm(parts[-1]) if parts else _norm(k)


class _Req(object):
    __slots__ = ("method", "path", "query", "headers", "body", "host", "scope", "region", "account", "params", "present", "form", "json", "hint")


def _build(http_request):
    r = _Req()
    r.method = str(http_request.get("method") or "GET").upper()
    path = http_request.get("path") or "/"
    qs = None
    if "?" in path:
        path, qs = path.split("?", 1)
    r.path = path or "/"
    r.query = _parse_query(http_request.get("query") if http_request.get("query") else qs)
    r.headers = _lower(http_request.get("headers"))
    body = http_request.get("body") or b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    r.body = bytes(body)
    r.host = r.headers.get("host", "").split(":", 1)[0].lower()
    r.scope = _scope(r.headers, r.query)
    r.region = r.scope.get("region") or DEFAULT_REGION
    r.account = http_request.get("account") or DEFAULT_ACCOUNT
    r.hint = str(http_request.get("service_hint") or "")      # host-supplied service (anonymous S3: no signature, arbitrary Host header)
    ct = r.headers.get("content-type", "").lower()
    r.form, r.json = {}, None
    if r.body and ("x-www-form-urlencoded" in ct or r.body[:7] == b"Action="):
        try:
            r.form = _parse_query(r.body.decode("utf-8", "replace"))
        except Exception:
            r.form = {}
    elif r.body and "cbor" in ct:                                 # override cloudwatch.cbor
        try:
            r.json = _cbor_loads(r.body)
        except Exception:
            r.json = None
    elif r.body and ("json" in ct or r.body[:1] in (b"{", b"[")):
        try:
            r.json = json.loads(r.body.decode("utf-8", "replace"))
        except Exception:
            r.json = None
    r.params, r.present = {}, set()
    for k, vs in r.query.items():
        r.present.add(_norm(k))
        r.params.setdefault(_form_key(k), []).extend(vs)
    for k, vs in r.form.items():
        r.present.add(_norm(k.split(".")[0]))
        r.params.setdefault(_form_key(k), []).extend(vs)
    if r.json is not None:
        _flatten(r.json, r.params)
        if isinstance(r.json, dict):
            r.present.update(_norm(k) for k in r.json)
    for k, v in r.headers.items():
        if k.startswith("x-amz-") and v != "":
            r.present.add(_norm(k))
    return r


# ----------------------------------------------------------------------------------------------- REST routing
_route_cache = {}
_LABEL = re.compile(r"\{([^}]+)\}")


def _compile_routes(prefix):
    if prefix in _route_cache:
        return _route_cache[prefix]
    out = []
    for rt in aws_routes_data.ROUTES["prefixes"].get(prefix, {}).get("rest", []):
        pat, labels, pos = "", [], 0
        for m in _LABEL.finditer(rt["p"]):
            pat += re.escape(rt["p"][pos:m.start()])
            name = m.group(1)
            greedy = name.endswith("+")
            labels.append(name.rstrip("+"))
            pat += "(.+)" if greedy else "([^/]+)"
            pos = m.end()
        pat += re.escape(rt["p"][pos:])
        lit = len(_LABEL.sub("", rt["p"]))
        out.append((rt, re.compile("^" + pat + "/?$"), labels, lit))
    _route_cache[prefix] = out
    return out


def _match_route(prefix, req, path, extra_present=()):
    """Best REST route for (method, path, query, headers) or None. Returns (route, labels dict)."""
    best, best_score = None, None
    qkeys = set(req.query)
    hkeys = set(req.headers)
    for rt, rx, labels, lit in _compile_routes(prefix):
        if rt["m"] != req.method:
            continue
        m = rx.match(path)
        if not m:
            continue
        ok, nlit = True, 0
        for k, v in rt["lq"]:
            vals = req.query.get(k)
            if vals is None or (v is not None and v not in vals):
                ok = False
                break
            nlit += 1
        if not ok:
            continue
        if any(q not in qkeys for q in rt["rq"]):
            continue
        if any(h not in hkeys for h in rt["rh"]):
            continue
        score = (nlit, len(rt["rq"]) + len(rt["rh"]), lit, -len(labels))
        if best_score is None or score > best_score:
            best, best_score = (rt, {n: unquote(g) for n, g in zip(labels, m.groups())}), score
    return best


# ------------------------------------------------------------------------------------------ service + operation
_signing_cache = None


def _prefix_of_signing(name):
    s = aws_routes_data.ROUTES["signing"]
    return s.get(name) or (name if name in aws_routes_data.ROUTES["prefixes"] else None)


def _host_service(host):
    if not host:
        return None
    first = host.split(".")[0]
    if ".execute-api." in host:
        return "execute-api"
    if first in ("s3", "s3-control") or ".s3" in host:
        return "s3"
    return _prefix_of_signing(first)


# S3 virtual-host: bucket.s3.<anything>  |  bucket.s3-<region>.amazonaws.com  |  access point: <name>-<acct>.s3-accesspoint.<region>...
_S3_VHOST = re.compile(r"^(?P<b>.+?)\.s3[.-](?!accesspoint)[^.]*")
_S3_AP_HOST = re.compile(r"^(?P<ap>.+)-(?P<acct>\d{12})\.s3-accesspoint\.")


def _s3_normalize(req):
    """-> (path_style_path, bucket, key, accesspoint). Applies override s3.host-style."""
    path, host = req.path, req.host
    ap = None
    m = _S3_AP_HOST.match(host)
    if m:
        ap = (m.group("ap"), m.group("acct"))
        path = "/" + ap[0] + (path if path.startswith("/") else "/" + path)
        parts = path.lstrip("/").split("/", 1)
        return path, ap[0], (unquote(parts[1]) if len(parts) > 1 and parts[1] else None), ap
    if host and not host.startswith("s3.") and not host.startswith("s3-") and host != "s3":
        m = _S3_VHOST.match(host)
        if m:
            path = "/" + m.group("b") + (path if path.startswith("/") else "/" + path)
    parts = path.lstrip("/").split("/", 1)
    bucket = unquote(parts[0]) if parts and parts[0] else None
    key = unquote(parts[1]) if len(parts) > 1 else None
    return path, bucket, key, ap


def identify(http_request):
    """-> {"prefix","op","labels","req"} or None. The service + operation the wire request invokes."""
    req = http_request if isinstance(http_request, _Req) else _build(http_request)
    h = req.headers
    prefix = _prefix_of_signing(req.scope["signing"]) if req.scope.get("signing") else None
    target = h.get("x-amz-target", "")
    if target:
        tp, _, op = target.rpartition(".")
        tprefix = aws_routes_data.ROUTES["targets"].get(tp) or (aws_routes_data.ROUTES["targets"].get(tp.rsplit(".", 1)[-1]))
        prefix = prefix or tprefix
        if prefix:
            return {"prefix": prefix, "op": op, "labels": {}, "req": req}
    prefix = prefix or _host_service(req.host) or (req.hint if req.hint == "s3" else None)
    action = (req.query.get("Action") or req.form.get("Action") or [None])[0]
    if action and prefix:
        return {"prefix": prefix, "op": action, "labels": {}, "req": req}
    m = re.match(r"^/service/[^/]+/operation/([A-Za-z0-9]+)$", req.path)
    if m and prefix:
        return {"prefix": prefix, "op": m.group(1), "labels": {}, "req": req}
    if prefix == "execute-api":
        return {"prefix": "execute-api", "op": "Invoke", "labels": {}, "req": req}
    if prefix == "s3" or prefix is None:
        p = prefix or "s3"
        if prefix is None and not _is_probably_s3(req):
            return None
        path, bucket, key, ap = _s3_normalize(req)
        hit = _match_route("s3", req, path)
        if hit:
            hit[1].setdefault("Bucket", bucket or "")
            return {"prefix": "s3", "op": hit[0]["op"], "labels": hit[1], "req": req, "s3": (bucket, key, ap)}
        return None
    if prefix == "apigateway":
        hit = _match_route("apigateway", req, req.path)
        return {"prefix": "apigateway", "op": hit[0]["op"] if hit else "", "labels": hit[1] if hit else {}, "req": req}
    if prefix in aws_routes_data.ROUTES["prefixes"]:
        hit = _match_route(prefix, req, req.path)
        if hit:
            return {"prefix": prefix, "op": hit[0]["op"], "labels": hit[1], "req": req}
    return None


def _is_probably_s3(req):
    return not req.scope and (".s3" in req.host or req.host.startswith("s3") or not req.host or req.host in ("localhost", "127.0.0.1"))


# --------------------------------------------------------------------------------------------- ARN construction
_VAR = re.compile(r"\$\{([^}]+)\}")
_PREFER = {"bedrock": ("foundation-model",)}     # several types share ${ResourceId}; a bare model id is a foundation model
_SYN = {"objectname": ["key"], "bucketname": ["bucket"], "securitygroupid": ["groupid"]}   # wire names that differ from the ARN variable


def _lookup(var, params):
    n = _norm(var)
    cands = [n]
    base = n.replace("withpath", "")
    if base != n:
        cands.append(base)
    for v in list(cands):
        for suf in ("name", "id", "arn"):
            if v.endswith(suf) and len(v) > len(suf):
                cands.append(v[: -len(suf)])
        cands.append(v + "name")
        cands.append(v + "id")
    cands.extend(_SYN.get(n, []))
    cands.extend(c.replace("name", "identifier") for c in list(cands) if "name" in c)         # rds DbInstanceName <- DBInstanceIdentifier
    cands.extend("db" + c for c in list(cands))                                              # rds ParameterGroupName <- DBParameterGroupName
    cands.extend(c.replace("instance", "") for c in list(cands) if "instance" in c)
    if n in ("resourceid", "id"):                                                              # bedrock ${ResourceId}: the one identifier in the request
        for k in params:
            if k.endswith(("modelid", "identifier")) and k not in cands:
                cands.append(k)
    for c in cands:
        if c in params and params[c]:
            return params[c][0]
    return None


def _arn_regex(fmt):
    pat, pos = "", 0
    ms = list(_VAR.finditer(fmt))
    for i, m in enumerate(ms):
        pat += re.escape(fmt[pos:m.start()])
        name = m.group(1)
        if name in ("Partition", "Region", "Account"):
            pat += "(?P<%s>[^:]*)" % name
        else:
            last = i == len(ms) - 1 and m.end() == len(fmt)
            pat += "(?P<v%d>%s)" % (i, ".+" if last else "[^/:]+")
        pos = m.end()
    pat += re.escape(fmt[pos:])
    return re.compile("^" + pat + "$")


_arnre_cache = {}


def _bound_arns(prefix, params):
    """ARN-valued params that match a resource format of this service -> [(rtype, arn)]."""
    cat = catalog(prefix)
    if not cat:
        return []
    out = []
    seen = set()
    for vals in params.values():
        for v in vals:
            if not (isinstance(v, str) and v.startswith("arn:")) or v in seen:
                continue
            seen.add(v)
            for rtype, fmts in cat["resources"].items():
                hit = False
                for fmt in fmts:
                    rx = _arnre_cache.get(fmt) or _arnre_cache.setdefault(fmt, _arn_regex(fmt))
                    if rx.match(v):
                        out.append((rtype, v))
                        hit = True
                        break
                if hit:
                    break
    return out


def _fill(fmt, req, params, scope_over=None, allow_name_fallback=False):
    """-> (arn, n_resolved, n_unresolved)."""
    nres = nun = 0

    def sub(m):
        nonlocal nres, nun
        v = m.group(1)
        if v == "Partition":
            return PARTITION
        if v == "Region":
            return req.region
        if v == "Account":
            return (scope_over or {}).get("account") or req.account
        lead = v.endswith("WithoutLeadingSlash")                     # ssm parameter/${ParameterNameWithoutLeadingSlash}
        val = _lookup(v[: -len("WithoutLeadingSlash")] if lead else v, params)
        if val is None and (allow_name_fallback or lead) and (v.endswith("Name") or v.endswith("Id") or lead):
            val = (params.get("name") or [None])[0]
        if val is not None and lead:
            val = val.lstrip("/")
        if val is None:
            nun += 1
            return "*"
        nres += 1
        return val

    return _VAR.sub(sub, fmt), nres, nun


def _resources_for(prefix, action, req, params, bound, allow_name_fallback, scope_over=None):
    cat = catalog(prefix)
    rtypes = (cat["actions"].get(action) or {}).get("r", []) if cat else []
    if not rtypes:
        noun = re.sub(r"^(Create|Register)", "", action).lower()           # override create-noun: catalog gap (eks CreateCluster lists no resource type)
        if action.startswith(("Create", "Register")) and noun in cat["resources"]:
            rtypes = [noun]
        else:
            return ["*"]
    out = []
    for rtype, arn in bound:
        if rtype in rtypes and arn not in out:
            out.append(arn)
    if out:
        return out
    full, part, none = [], [], []
    for rtype in rtypes:
        best = None
        for fmt in cat["resources"].get(rtype, []):
            arn, nr, nu = _fill(fmt, req, params, scope_over, allow_name_fallback)
            if best is None or (nu == 0, nr) > (best[2] == 0, best[1]):
                best = (arn, nr, nu)
        if best is None:
            continue
        (full if best[2] == 0 and best[1] > 0 else part if best[1] > 0 else none).append(best + (rtype,))
    if full:
        top = max(c[1] for c in full)
        pref = _PREFER.get(prefix, ())
        res, seen_sets = [], set()
        for c in sorted((c for c in full if c[1] == top), key=lambda c: c[3] not in pref):
            sig = tuple(v for v in _VAR.findall(cat["resources"][c[3]][0]) if v not in ("Partition", "Region", "Account"))
            if sig in seen_sets:
                continue
            seen_sets.add(sig)
            res.append(c[0])
        return res
    if part:
        return [part[0][0]]
    return [none[0][0]] if none else ["*"]


# ------------------------------------------------------------------------------------- conditional extra actions
_VERBS = ("Put", "Create", "Get", "Set", "Update", "Add", "Delete", "Tag", "Untag", "Associate", "Restore", "Start", "Batch")
_SKIP_TOK = {"object", "bucket", "configuration", "controls", "policy", "resource"}
_COND_CLASS = {"bypass", "tag", "tags", "tagging", "acl", "retention", "legal", "lock", "ownership", "version", "policy"}
_TOK_SYN = {"retention": ("retain", "lockmode"), "legal": ("legalhold",), "tagging": ("tag",), "tags": ("tag",), "tag": ("tag",),
            "ownership": ("ownership",), "lock": ("lock",), "acl": ("acl", "grant"), "version": ("versionid",), "policy": ("policy",), "bypass": ("bypass",)}


def _cond_key(action):
    """Class token of a catalog action that is only conditionally authorised (acl, tagging, lock, ...), else None."""
    name, verb = action, None
    for v in _VERBS:
        if name.startswith(v) and len(name) > len(v):
            verb, name = v, name[len(v):]
            break
    if verb in ("Tag", "Untag"):
        return "tag"
    toks = [t.lower() for t in re.findall(r"[A-Z][a-z0-9]*", name)]
    sig = [t for t in toks if t not in _SKIP_TOK] or toks
    if sig and sig[0] in _COND_CLASS:
        return sig[0]
    if "resource" in toks and "policy" in toks:
        return "policy"
    return None


def _extra_triggered(action, op, present):
    """Override conditional-extra-actions: is conditional catalog action `action` triggered by a key of the request?"""
    key = _cond_key(action)
    if key is None:
        return True
    return any(k in p for k in _TOK_SYN.get(key, (key,)) for p in present)


_VERB_SYN = {"Head": "Get", "Describe": "Describe"}


def _first_tok(name):
    m = re.match(r"[A-Z][a-z]*", name)
    return m.group(0) if m else name


def _actions_for(prefix, op, req, cat):
    """Catalog actions this request authorises: the op's own action (or, for a renamed one, the same-verb action) plus the conditional
    extras (tag/acl/lock/...) the request actually triggers. Other listed actions are ancillary and are not required."""
    acts = list(cat["operations"].get(op) or [])
    if len(acts) <= 1:
        return acts
    if op in acts:
        base = [op]
    else:
        verb = _VERB_SYN.get(_first_tok(op), _first_tok(op))
        plain = [a for a in acts if _cond_key(a) is None]
        base = [a for a in plain if _first_tok(a) == verb] or plain[:1] or acts[:1]
    return base + [a for a in acts if a not in base and _cond_key(a) and _extra_triggered(a, op, req.present)]


# ------------------------------------------------------------------------------------------------ the entry point
def _entry(prefix, action, resource, op):
    return {"action": "%s:%s" % (prefix, action), "resource": resource, "service": prefix, "operation": op}


def _s3_actions(op, acts, req, cat, params):
    """Overrides s3.catalog-superset / s3.versions: choose the S3 actions this request really authorises."""
    if op in ("CopyObject", "UploadPartCopy"):
        return None  # handled by the copy override
    acts = _actions_for("s3", op, req, cat)
    if "versionid" in req.present and op not in ("CopyObject",):
        swapped = []
        for a in acts:
            i = a.find("Object")
            v = a[: i + 6] + "Version" + a[i + 6:] if i >= 0 else None
            swapped.append(v if v and v in cat["actions"] and a != "PutObject" and a != "ListBucket" else a)
        acts = swapped
    return acts


def _s3_arn(cat, rtype, **kw):
    fmt = cat["resources"][rtype][0]
    return _VAR.sub(lambda m: {"Partition": PARTITION}.get(m.group(1), kw.get(m.group(1), "*")), fmt)


def _delete_objects_keys(body):
    """[(key, versionId|None)] from a DeleteObjects XML body (<Delete><Object><Key>..</Key><VersionId>..</VersionId></Object>...)."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body or b"")
    except Exception:
        return []
    out = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "Object":
            continue
        k = v = None
        for ch in el:
            t = ch.tag.split("}")[-1]
            if t == "Key":
                k = ch.text or ""
            elif t == "VersionId":
                v = ch.text or None
        if k is not None:
            out.append((k, v))
    return out


def _s3_required(ident, req):
    cat = catalog("s3")
    op = ident["op"]
    bucket, key, ap = ident["s3"]
    labels = ident["labels"]
    params = dict(req.params)
    if bucket is None and labels.get("Bucket"):
        bucket = labels["Bucket"]
    if key is None:
        key = labels.get("Key")
    out = []
    if ap:
        akw = {"AccessPointName": ap[0], "Region": req.region, "Account": ap[1], "ObjectName": key or "*"}
    else:
        akw = {"BucketName": bucket or "*", "ObjectName": key or "*"}
    if op.startswith(("CreateAccessPoint", "GetAccessPoint", "DeleteAccessPoint", "PutAccessPoint", "ListAccessPoints")) or "Name" in labels:
        akw.setdefault("AccessPointName", labels.get("name") or labels.get("Name") or "*")
    acts = list(cat["operations"].get(op) or [])
    if op in ("CopyObject", "UploadPartCopy"):
        src = unquote(req.headers.get("x-amz-copy-source", "")).lstrip("/")
        sver = None
        if "?versionId=" in src:
            src, sver = src.split("?versionId=", 1)
        if src.startswith("arn:"):
            src_arn = src
        else:
            src_arn = _s3_arn(cat, "object", BucketName=src.split("/", 1)[0], ObjectName=src.split("/", 1)[1] if "/" in src else "*")
        out.append(_entry("s3", "GetObjectVersion" if sver else "GetObject", src_arn, op))
        dest = _s3_arn(cat, "object", **akw)
        base = ["PutObject"] + [a for a in acts if a in ("PutObjectAcl", "PutObjectTagging", "PutObjectLegalHold", "PutObjectRetention")
                                and _extra_triggered(a, "PutObject", req.present)]
        for a in base:
            out.append(_entry("s3", a, dest, op))
        return out
    if op == "DeleteObjects" and not ap:                                  # override s3.delete-objects
        keys = _delete_objects_keys(req.body)
        if keys:
            out_keys = []
            for k, ver in keys:
                e = _entry("s3", "DeleteObjectVersion" if ver else "DeleteObject", _s3_arn(cat, "object", BucketName=bucket or "*", ObjectName=k), op)
                if e not in out_keys:
                    out_keys.append(e)
            return out_keys
    acts = _s3_actions(op, acts, req, cat, params)
    for a in acts:
        rtypes = (cat["actions"].get(a) or {}).get("r", [])
        if not rtypes:
            out.append(_entry("s3", a, "*", op))
            continue
        want = None
        if ap:
            want = "accesspointobject" if "accesspointobject" in rtypes and key else ("accesspoint" if "accesspoint" in rtypes else None)
        if want is None:
            best = -1
            for rt in rtypes:
                fmt = cat["resources"][rt][0]
                vars_ = [v for v in _VAR.findall(fmt) if v not in ("Partition", "Region", "Account")]
                nres = sum(1 for v in vars_ if akw.get(v, "*") != "*")
                full = bool(vars_) and nres == len(vars_)
                score = (full, nres)
                if best == -1 or score > best:
                    best, want = score, rt
        e = _entry("s3", a, _s3_arn(cat, want, **akw), op)
        if e not in out:
            out.append(e)
    return out


def _apigw_required(ident, req):
    path = req.path
    if path.startswith("/v2/"):
        path = path[3:]
    return [{"action": "apigateway:" + req.method, "resource": "arn:%s:apigateway:%s::%s" % (PARTITION, req.region, path.rstrip("/") or "/"),
             "service": "apigateway", "operation": ident["op"]}]


_API_ID = re.compile(r"^[a-z0-9]{10}$")


def _execute_api_target(req):
    """-> (api_id, stage, rest_segments): override execute-api.api-id."""
    segs = [s for s in req.path.split("/") if s]
    label = req.host.split(".")[0] if ".execute-api." in req.host else ""
    if label:                                                              # <id>.execute-api.<region|localhost>/<stage>/<path>
        return label, (segs[0] if segs else "*"), segs[1:]
    if len(segs) >= 3 and segs[0] == "restapis":                          # /restapis/<id>/<stage>/_user_request_/<path>
        return segs[1], segs[2], [s for s in segs[3:] if s != "_user_request_"]
    if len(segs) >= 2 and segs[0] == "apigw":                             # Caddy path-style fallback /apigw/<id>/<stage>/<path>
        return segs[1], (segs[2] if len(segs) > 2 else "*"), segs[3:]
    if segs and _API_ID.match(segs[0]):                                    # /<id>/<stage>/<path>
        return segs[0], (segs[1] if len(segs) > 1 else "*"), segs[2:]
    return "*", "*", segs


def _execute_api_required(req):
    host_id, stage, rest_segs = _execute_api_target(req)
    rest = "/".join(rest_segs)
    if rest.startswith("@connections"):
        return [{"action": "execute-api:ManageConnections", "resource": "arn:%s:execute-api:%s:%s:%s/%s/POST/%s" % (
            PARTITION, req.region, req.account, host_id, stage, rest), "service": "execute-api", "operation": "ManageConnections"}]
    return [{"action": "execute-api:Invoke", "resource": "arn:%s:execute-api:%s:%s:%s/%s/%s/%s" % (
        PARTITION, req.region, req.account, host_id, stage, req.method, rest), "service": "execute-api", "operation": "Invoke"}]


_S3_HDR_KEYS = ("x-amz-acl", "x-amz-server-side-encryption", "x-amz-storage-class", "x-amz-copy-source", "x-amz-metadata-directive",
                "x-amz-grant-read", "x-amz-grant-write", "x-amz-grant-full-control", "x-amz-server-side-encryption-aws-kms-key-id")


def _s3_request_context(http_request):
    """The S3 condition keys a request carries on its own: s3:prefix / s3:delimiter / s3:max-keys (list query) and the s3:x-amz-* request headers."""
    from urllib.parse import parse_qsl
    q = http_request.get("query") or ""
    qd = dict(parse_qsl(q, keep_blank_values=True)) if isinstance(q, str) else dict(q)
    ctx = {}
    for qk, ck in (("prefix", "s3:prefix"), ("delimiter", "s3:delimiter"), ("max-keys", "s3:max-keys")):
        if qk in qd:
            ctx[ck] = qd[qk]
    hdr = {str(k).lower(): v for k, v in (http_request.get("headers") or {}).items()}
    for h in _S3_HDR_KEYS:
        if h in hdr:
            ctx["s3:" + h] = hdr[h]
    return ctx


def required(http_request):
    """-> list of {"action","resource","service","operation"[, "context"]}; [] when the request is not an AWS API call this module understands.
    S3 entries carry the request-derived condition keys (the gate merges `context` into the evaluation context)."""
    out = _required(http_request)
    if out and any(e.get("service") == "s3" for e in out):
        ctx = _s3_request_context(http_request)
        if ctx:
            for e in out:
                if e.get("service") == "s3":
                    e["context"] = dict(ctx)
    return out


def _required(http_request):
    req = _build(http_request)
    ident = identify(req)
    if ident is None:
        return []
    prefix, op = ident["prefix"], ident["op"]
    if prefix == "execute-api":
        return _execute_api_required(req)
    if prefix == "apigateway":
        return _apigw_required(ident, req) if op else []
    cat = catalog(prefix)
    if cat is None or op not in cat["operations"]:
        return []
    if prefix == "s3":
        return _s3_required(ident, req)
    params = dict(req.params)
    for k, v in ident["labels"].items():
        params.setdefault(_norm(k), []).insert(0, v)
    scope_over = None
    if prefix == "sqs":                                          # override sqs.queue-url
        qu = (params.get("queueurl") or [""])[0]
        if qu:
            segs = [s for s in qu.split("?")[0].rstrip("/").split("/") if s]
            if len(segs) >= 2:
                params["queuename"] = [segs[-1]]
                if segs[-2].isdigit():
                    scope_over = {"account": segs[-2]}
    if prefix == "kms":                                          # override kms.alias
        kid = (params.get("keyid") or [""])[0]
        if kid.startswith("alias/"):
            return [_entry("kms", a, "arn:%s:kms:%s:%s:%s" % (PARTITION, req.region, req.account, kid), op) for a in cat["operations"][op]]
    bound = _bound_arns(prefix, params)
    acts = _actions_for(prefix, op, req, cat)
    if prefix == "ec2" and op == "RunInstances":                  # override ec2.run-instances: the instance/volume/ENI do not exist yet -> wildcards
        extra = [("instance", "RunInstances"), ("network-interface", "RunInstances"), ("volume", "RunInstances")]
        out = []
        for a in acts:
            for res in _resources_for(prefix, a, req, params, bound, False, scope_over):
                out.append(_entry(prefix, a, res, op))
        for rt, a in extra:
            out.append(_entry(prefix, a, _VAR.sub(lambda m: {"Partition": PARTITION, "Region": req.region, "Account": req.account}.get(m.group(1), "*"), cat["resources"][rt][0]), op))
        return out
    nf = op.startswith(("Create", "Put", "Register")) or bool(ident["labels"])
    out, seen = [], set()
    for a in acts:
        for res in _resources_for(prefix, a, req, params, bound, nf, scope_over):
            e = _entry(prefix, a, res, op)
            k = (e["action"], e["resource"])
            if k not in seen:
                seen.add(k)
                out.append(e)
    return out


# -------------------------------------------------------------------------------------------------- coverage
def _signing_for(prefix):
    sig = aws_routes_data.ROUTES["signing"]
    names = sorted((k for k, v in sig.items() if v == prefix), key=lambda k: (k != prefix, k))
    return names[0] if names else prefix


def synthesize(prefix, op):
    """Fabricate a wire request for catalog operation `op` (the coverage round-trip). None when the op has no known wire form."""
    ent = aws_routes_data.ROUTES["prefixes"].get(prefix)
    if not ent or op not in ent["ops"]:
        return None
    region = DEFAULT_REGION
    auth = "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20260101/%s/%s/aws4_request, SignedHeaders=host, Signature=0" % (region, _signing_for(prefix))
    headers = {"Authorization": auth, "Host": "%s.%s.amazonaws.com" % (_signing_for(prefix), region)}
    routes = [r for r in ent["rest"] if r["op"] == op]
    if routes:
        r = routes[0]
        path = _LABEL.sub(lambda m: "x" if not m.group(1).endswith("+") else "x/y", r["p"])
        query = {k: (v if v is not None else "") for k, v in r["lq"]}
        for q in r["rq"]:
            query.setdefault(q, "1")
        for hn in r["rh"]:
            headers[hn] = "x/y"
        if prefix == "s3":
            headers["Host"] = "s3.%s.amazonaws.com" % region
        return {"method": r["m"], "path": path, "query": query, "headers": headers, "body": b""}
    if ent["target"]:
        headers["X-Amz-Target"] = "%s.%s" % (ent["target"][0], op)
        headers["Content-Type"] = "application/x-amz-json-1.0"
        return {"method": "POST", "path": "/", "query": {}, "headers": headers, "body": b"{}"}
    if ent["query"]:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return {"method": "POST", "path": "/", "query": {}, "headers": headers, "body": ("Action=%s&Version=2000-01-01" % op).encode()}
    return None


def _twin(prefix, got, op):
    """Two catalog operations on the identical wire form (e.g. S3 GetBucketLifecycle / GetBucketLifecycleConfiguration) that authorise
    the same actions are indistinguishable on the wire; either identification is correct."""
    cat = catalog(prefix)
    return sorted(cat["operations"].get(got, [])) == sorted(cat["operations"].get(op, [])) and bool(cat["operations"].get(op))


def coverage(prefix_list=None):
    """-> {prefix: {"ops": n, "mapped": n, "unmapped": [op,...]}} for catalog operations, by wire round-trip."""
    res = {}
    for prefix in (prefix_list or prefixes()):
        cat = catalog(prefix)
        if not cat:
            continue
        mapped, unmapped = 0, []
        for op in sorted(cat["operations"]):
            ok = False
            req = synthesize(prefix, op)
            if req is not None:
                try:
                    ent = required(req)
                except Exception:
                    ent = []
                ok = any(e["service"] == prefix and (e["operation"] == op or _twin(prefix, e["operation"], op)) for e in ent)
            if ok:
                mapped += 1
            else:
                unmapped.append(op)
        res[prefix] = {"ops": len(cat["operations"]), "mapped": mapped, "unmapped": unmapped}
    return res


def _main(argv):
    if "--coverage" in argv:
        cov = coverage()
        tm = tt = 0
        for p, c in sorted(cov.items()):
            pct = 100.0 * c["mapped"] / c["ops"] if c["ops"] else 100.0
            tm += c["mapped"]
            tt += c["ops"]
            print("%-22s %4d/%-4d  %5.1f%%  unmapped=%d" % (p, c["mapped"], c["ops"], pct, len(c["unmapped"])))
            if "-v" in argv and c["unmapped"]:
                print("    " + ", ".join(c["unmapped"]))
        print("TOTAL %d/%d  %.1f%%" % (tm, tt, 100.0 * tm / max(tt, 1)))
        return 0
    if "--overrides" in argv:
        for k, v in OVERRIDES.items():
            print("%-28s %s" % (k, v))
        return 0
    print("usage: python3 -m core.iam_engine.map_aws --coverage [-v] | --overrides")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
