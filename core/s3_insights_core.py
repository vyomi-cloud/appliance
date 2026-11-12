"""S3 account insights — substrate-independent, loaded by core/s3_object_core.py.

 * IAM Access Analyzer for S3 (console feature): findings are COMPUTED ON EVERY READ from each bucket's
   and access point's effective policy + ACL + (bucket/access-point/account) Block Public Access, so they
   can never be stale. Only archive state and first-seen/updated stamps are persisted
   (`store.account["access_analysis"]`). Routed as `/v20180820/_vyomi/access-analysis…` (JSON). The full
   `accessanalyzer` service API (analyzers, archive rules, unused-access, policy validation) is NOT simulated.
 * Storage Lens: s3control Put/Get/List/DeleteStorageLensConfiguration (+tagging), Put/Get/List/Delete
   StorageLensGroup (+Create/Update), TagResource/UntagResource/ListTagsForResource for lens resources, the
   built-in `default-account-dashboard`, and dashboard DATA computed from the real object store
   (`/v20180820/_vyomi/storage-lens/{id}` JSON) with a lazily recorded daily snapshot trend.

NO fastapi / boto3 imports — loads under Pyodide.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

_ACCOUNT = "123456789012"
_HOME = "us-east-1"
_NS = "http://awss3control.amazonaws.com/doc/2016-08-20/"
DEFAULT_DASHBOARD = "default-account-dashboard"
_ID_RE = re.compile(r"^[a-zA-Z0-9\-_.]{1,64}$")
_GROUP_RE = re.compile(r"^[a-zA-Z0-9\-_]{1,64}$")
_SNAPSHOT_KEEP = 30
_PUBLIC_GROUPS = ("http://acs.amazonaws.com/groups/global/AllUsers", "http://acs.amazonaws.com/groups/global/AuthenticatedUsers")


def _m():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m                          # type: ignore
    return m


def _jresp(status: int, doc):
    m = _m()
    return m.S3Response(status=status, headers=m._amz_headers(), body=json.dumps(doc).encode(), media_type="application/json")


def _jerr(code: str, message: str, status: int):
    return _jresp(status, {"error": code, "message": message})


def _day(iso: str) -> str:
    return iso[:10]


# ═══ IAM Access Analyzer for S3 ═══════════════════════════════════════════════════════
_CANON_OWNER = "simulator"


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def _acct_of(value: str):
    """The account id inside an account id / IAM ARN / resource ARN, else None."""
    if re.fullmatch(r"\d{12}", value or ""):
        return value
    mt = re.match(r"^arn:aws[-a-z]*:[a-z0-9-]*:[a-z0-9-]*:(\d{12}):", value or "")
    return mt.group(1) if mt else None


def _stmt_principals(st: dict):
    """-> (wildcard: bool, accounts: set[str], odd: bool). Service/Federated principals are not external access."""
    pr = st.get("Principal")
    wild, accts = False, set()
    if "NotPrincipal" in st and st.get("Effect") == "Allow":
        return True, accts
    if pr == "*":
        return True, accts
    if isinstance(pr, dict):
        for v in _as_list(pr.get("AWS")):
            if v == "*":
                wild = True
            else:
                a = _acct_of(str(v))
                if a:
                    accts.add(a)
    return wild, accts


def _cond_restrictions(st: dict):
    """-> dict(orgs=set, accounts=set|None, vpc=bool). `accounts` is None when no account-style condition key restricts
    the statement. Negated operators are ignored (they never narrow a statement to a known principal set)."""
    orgs, accounts, vpc = set(), None, False
    for op, kv in (st.get("Condition") or {}).items():
        if "Not" in op or not isinstance(kv, dict):
            continue
        for key, val in kv.items():
            k = key.lower()
            vals = [str(x) for x in _as_list(val)]
            if k in ("aws:principalorgid", "aws:sourceorgid", "aws:principalorgpaths", "aws:resourceorgid"):
                orgs.update(vals)
            elif k in ("aws:sourceaccount", "aws:principalaccount", "aws:sourceowner"):
                accounts = (accounts or set()) | {a for a in (_acct_of(v) for v in vals) if a}
            elif k in ("aws:sourcearn", "aws:principalarn"):
                accounts = (accounts or set()) | {a for a in (_acct_of(v) for v in vals) if a}
            elif k in ("aws:sourcevpc", "aws:sourcevpce"):
                vpc = True
    return {"orgs": orgs, "accounts": accounts, "vpc": vpc}


def _policy_findings(policy_doc, pab: dict, vpc_only: bool = False):
    """Findings + suppressed notes from one resource policy.
    -> (findings: [{kind, principal, via_detail, actions}], suppressed: [str])"""
    findings, suppressed = {}, []
    if not policy_doc:
        return [], []
    try:
        pol = json.loads(policy_doc) if isinstance(policy_doc, str) else policy_doc
    except Exception:
        return [], []
    stmts = pol.get("Statement") if isinstance(pol, dict) else None
    for i, st in enumerate(_as_list(stmts)):
        if not isinstance(st, dict) or st.get("Effect") != "Allow":
            continue
        label = f"statement {i}" + (f" (Sid {st['Sid']})" if st.get("Sid") else "")
        actions = [str(a) for a in _as_list(st.get("Action"))] or ["*"]
        wild, accts = _stmt_principals(st)
        cr = _cond_restrictions(st)
        if cr["vpc"] or vpc_only:
            continue                                           # limited to a VPC / VPC endpoint: not external access
        found = []
        if wild:
            if cr["orgs"]:
                found += [("Shared", f"org:{o}", f"{label}: Principal * limited by an organization condition to {o}") for o in sorted(cr["orgs"])]
            elif cr["accounts"] is not None:
                found += [("Shared", f"account:{a}", f"{label}: Principal * limited by a condition key to account {a}") for a in sorted(cr["accounts"]) if a != _ACCOUNT]
            else:
                if pab.get("RestrictPublicBuckets"):
                    suppressed.append(f"{label}: public (Principal *) but neutralised by RestrictPublicBuckets")
                else:
                    found.append(("Public", "*", f"{label}: Allow with Principal * and no restricting condition"))
        for a in sorted(accts):
            if cr["accounts"] is not None and cr["accounts"] <= {_ACCOUNT}:
                continue
            if a != _ACCOUNT:
                found.append(("Shared", f"account:{a}", f"{label}: Allow for principal in account {a}"))
        for kind, principal, reason in found:
            f = findings.setdefault((kind, principal), {"kind": kind, "principal": principal, "reasons": [], "actions": []})
            f["reasons"].append(reason)
            for a in actions:
                if a not in f["actions"]:
                    f["actions"].append(a)
    return list(findings.values()), suppressed


def _acl_grants(m, meta: dict):
    """(grantee_kind, value, permission) triples of a bucket ACL (stored XML, else the canned ACL)."""
    xml = meta.get("acl")
    out = []
    if xml:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return out
        for e in root.iter():
            if isinstance(e.tag, str) and "}" in e.tag:
                e.tag = e.tag.split("}", 1)[1]
        for g in root.iter("Grant"):
            gr, perm = g.find("Grantee"), (g.findtext("Permission") or "")
            if gr is None:
                continue
            uri, cid, email = gr.findtext("URI"), gr.findtext("ID"), gr.findtext("EmailAddress")
            if uri:
                out.append(("group", uri, perm))
            elif cid:
                out.append(("canonical", cid, perm))
            elif email:
                out.append(("email", email, perm))
        return out
    for uri, perm in m._CANNED_ACL_GRANTS.get(meta.get("canned_acl") or "private", []):
        out.append(("group", uri, perm))
    return out


def _fid(arn: str, via: str, principal: str) -> str:
    return hashlib.sha1(f"{arn}|{via}|{principal}".encode()).hexdigest()[:20]


def compute_findings(store):
    """-> (findings, resources). Pure function of the store (no persistence)."""
    m = _m()
    findings, resources = [], []
    acct_pab = m._account_pab(store)
    for name in sorted(store.buckets):
        meta = store.buckets[name] or {}
        if meta.get("internal") or meta.get("bucket_type") == "Directory":
            continue
        arn = f"arn:aws:s3:::{name}"
        pab = m._public_access_block(store, name)
        pol_doc = (meta.get("cfg") or {}).get("policy")
        fs, sup = _policy_findings(pol_doc, pab)
        for f in fs:
            findings.append({**f, "resource": name, "resourceArn": arn, "resourceType": "AWS::S3::Bucket", "via": "Bucket policy",
                             "region": meta.get("region") or _HOME})
        # ACL
        ack = []
        for gk, val, perm in _acl_grants(m, meta):
            if gk == "group" and val in _PUBLIC_GROUPS:
                if pab.get("IgnorePublicAcls"):
                    sup.append(f"ACL grants {perm} to {val.rsplit('/', 1)[-1]} but is neutralised by IgnorePublicAcls")
                else:
                    ack.append(("Public", "*", f"Bucket ACL grants {perm} to {val.rsplit('/', 1)[-1]}", perm))
            elif gk == "canonical" and val != _CANON_OWNER:
                ack.append(("Shared", f"canonical:{val}", f"Bucket ACL grants {perm} to canonical user {val}", perm))
            elif gk == "email":
                ack.append(("Shared", f"email:{val}", f"Bucket ACL grants {perm} to {val}", perm))
        merged = {}
        for kind, principal, reason, perm in ack:
            f = merged.setdefault((kind, principal), {"kind": kind, "principal": principal, "reasons": [], "actions": []})
            f["reasons"].append(reason)
            if perm not in f["actions"]:
                f["actions"].append(perm)
        for f in merged.values():
            findings.append({**f, "resource": name, "resourceArn": arn, "resourceType": "AWS::S3::Bucket", "via": "Bucket ACL",
                             "region": meta.get("region") or _HOME})
        # access points of the bucket
        for apn, rec in sorted(((meta.get("access_points")) or {}).items()):
            apab = {k: bool(rec.get("pab", {}).get(k)) or pab.get(k, False) for k in m._PAB_KEYS}
            afs, asup = _policy_findings(rec.get("policy"), apab, vpc_only=bool(rec.get("vpc")))
            for f in afs:
                findings.append({**f, "resource": apn, "resourceArn": rec["arn"], "resourceType": "AWS::S3::AccessPoint", "via": "Access point policy",
                                 "region": meta.get("region") or _HOME, "bucket": name})
            sup += [f"access point {apn}: {s}" for s in asup]
        public = any(f["kind"] == "Public" and f["resource"] == name and f["resourceType"] == "AWS::S3::Bucket" for f in findings)
        shared = any(f["kind"] == "Shared" and f.get("bucket", f["resource"]) == name for f in findings)
        resources.append({"name": name, "arn": arn, "region": meta.get("region") or _HOME, "public": public, "shared": shared, "suppressed": sup,
                          "blockPublicAccess": pab, "bucketBlockPublicAccess": {k: pab[k] and not acct_pab[k] or False for k in pab}})
    return findings, resources


def _analysis_state(store) -> dict:
    return store.account.setdefault("access_analysis", {"archived": {}, "seen": {}})


def access_analysis(store) -> dict:
    """The recomputed analysis + archive state; first-seen/updated stamps maintained for the findings that exist NOW."""
    m = _m()
    findings, resources = compute_findings(store)
    st = _analysis_state(store)
    now, alive = m._now(), set()
    out = []
    for f in findings:
        fid = _fid(f["resourceArn"], f["via"], f["principal"])
        alive.add(fid)
        fp = hashlib.sha1(json.dumps([f["reasons"], f["actions"], f["kind"]], sort_keys=True).encode()).hexdigest()
        seen = st["seen"].get(fid)
        if seen is None:
            seen = st["seen"][fid] = {"first": now, "updated": now, "fp": fp}
        elif seen["fp"] != fp:
            seen.update({"updated": now, "fp": fp})
            st["archived"].pop(fid, None)                       # a changed finding re-activates (like a real analyzer)
        out.append({**f, "id": fid, "status": "Archived" if fid in st["archived"] else "Active", "firstSeen": seen["first"], "updatedAt": seen["updated"],
                    "isPublic": f["kind"] == "Public", "access": "Public" if f["kind"] == "Public" else "Shared with other AWS accounts or organizations"})
    for gone in [k for k in st["seen"] if k not in alive]:      # resolved: the cause was removed
        st["seen"].pop(gone, None)
        st["archived"].pop(gone, None)
    for r in resources:
        r["activeFindings"] = sum(1 for f in out if f["status"] == "Active" and (f["resource"] == r["name"] or f.get("bucket") == r["name"]))
    return {"generatedAt": now, "accountBlockPublicAccess": m._account_pab(store), "findings": out, "buckets": resources,
            "analyzer": {"scope": "this account", "note": "Findings are recomputed from each request; the full IAM Access Analyzer service API is not simulated."}}


def s3_vyomi(store, method: str, segs: list, query: dict, body: bytes):
    """/v20180820/_vyomi/<access-analysis|storage-lens>… (segs[0] == v20180820, segs[1] == _vyomi)."""
    m = _m()
    rest = segs[2:]
    if not rest:
        return _jerr("NotFound", "unknown", 404)
    if rest[0] == "access-analysis":
        if len(rest) == 1 and method == "GET":
            r = access_analysis(store)
            store.persist()
            return _jresp(200, r)
        if len(rest) == 3 and rest[1] == "findings" and method in ("PUT", "POST", "DELETE"):
            return _jerr("BadRequest", "use /findings/{id}/archive", 400)
        if len(rest) == 4 and rest[1] == "findings" and rest[3] in ("archive", "unarchive") and method in ("PUT", "POST"):
            r = access_analysis(store)
            ids = {f["id"] for f in r["findings"]}
            if rest[2] not in ids:
                return _jerr("NotFound", "No such finding (it may have been resolved).", 404)
            st = _analysis_state(store)
            if rest[3] == "archive":
                st["archived"][rest[2]] = m._now()
            else:
                st["archived"].pop(rest[2], None)
            store.persist()
            return _jresp(200, {"id": rest[2], "status": "Archived" if rest[3] == "archive" else "Active"})
        return _jerr("MethodNotAllowed", method, 405)
    if rest[0] == "storage-lens" and method == "GET" and len(rest) == 2:
        data = lens_data(store, urllib.parse.unquote(rest[1]), query)
        store.persist()
        return data
    return _jerr("NotFound", "unknown", 404)


# ═══ Storage Lens: configurations, groups, tags ═══════════════════════════════════════
def _lens(store) -> dict:
    return store.account.setdefault("lens", {"configs": {}, "groups": {}, "snapshots": {}})


def _lens_arn(cid: str) -> str:
    return f"arn:aws:s3:{_HOME}:{_ACCOUNT}:storage-lens/{cid}"


def _group_arn(name: str) -> str:
    return f"arn:aws:s3:{_HOME}:{_ACCOUNT}:storage-lens-group/{name}"


def _default_config_xml() -> str:
    return (f"<StorageLensConfiguration><Id>{DEFAULT_DASHBOARD}</Id><AccountLevel><ActivityMetrics><IsEnabled>false</IsEnabled></ActivityMetrics>"
            "<BucketLevel><ActivityMetrics><IsEnabled>false</IsEnabled></ActivityMetrics></BucketLevel></AccountLevel>"
            f"<IsEnabled>true</IsEnabled><StorageLensArn>{_lens_arn(DEFAULT_DASHBOARD)}</StorageLensArn></StorageLensConfiguration>")


def _strip(el):
    for e in el.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return el


def _get_cfg(store, cid: str):
    c = _lens(store)["configs"].get(cid)
    if c is None and cid == DEFAULT_DASHBOARD:
        return {"id": cid, "xml": _default_config_xml(), "tags": {}, "created": None, "default": True}
    return c


def _cfg_root(c: dict):
    return _strip(ET.fromstring(c["xml"]))


def _text(el, path: str, default: str = "") -> str:
    if el is None:
        return default
    v = el.findtext(path)
    return v.strip() if isinstance(v, str) else default


def _with_ns(xml: str, tag: str) -> str:
    return xml.replace(f"<{tag}>", f'<{tag} xmlns="{_NS}">', 1)


def _err(code, msg, status):
    return _m()._s3c_error(code, msg, status)


def _parse_tags(el):
    out = {}
    if el is None:
        return out
    for t in el.findall("Tag"):
        out[(t.findtext("Key") or "")] = t.findtext("Value") or ""
    return out


def _validate_tags(tags: dict):
    if len(tags) > 50:
        return "A resource can have at most 50 tags."
    for k, v in tags.items():
        if not k or len(k) > 128 or len(v) > 256 or k.lower().startswith("aws:"):
            return f"Invalid tag '{k}'."
    return None


def _bool(root, path: str):
    v = _text(root, path).lower()
    return None if v == "" else v == "true"


def _validate_config(store, cid: str, root):
    m = _m()
    if root.tag != "StorageLensConfiguration":
        return _err("MalformedXML", "StorageLensConfiguration is required.", 400)
    if _text(root, "Id") != cid:
        return _err("InvalidRequest", "The Id in the configuration must match the configuration id in the URI.", 400)
    if root.find("AccountLevel") is None or root.find("AccountLevel/BucketLevel") is None:
        return _err("InvalidRequest", "AccountLevel with a BucketLevel is required.", 400)
    if _bool(root, "IsEnabled") is None:
        return _err("InvalidRequest", "IsEnabled is required.", 400)
    inc, exc = root.find("Include"), root.find("Exclude")
    if inc is not None and exc is not None and len(inc) and len(exc):
        return _err("InvalidRequest", "Include and Exclude cannot both be specified.", 400)
    for sec in (inc, exc):
        for bk in (sec.findall("Buckets/Arn") if sec is not None else []):
            if not re.match(r"^arn:aws[-a-z]*:s3:::[a-z0-9.-]{3,63}$", (bk.text or "").strip()):
                return _err("InvalidRequest", f"Invalid bucket ARN '{bk.text}'.", 400)
    sc = root.find("AccountLevel/BucketLevel/PrefixLevel/StorageMetrics/SelectionCriteria")
    if sc is not None:
        d = _text(sc, "Delimiter")
        if d and len(d) != 1:
            return _err("InvalidRequest", "Delimiter must be a single character.", 400)
        md = _text(sc, "MaxDepth")
        if md and not (md.isdigit() and 1 <= int(md) <= 10):
            return _err("InvalidRequest", "MaxDepth must be between 1 and 10.", 400)
        mp = _text(sc, "MinStorageBytesPercentage")
        try:
            if mp and not (0.1 <= float(mp) <= 100):
                raise ValueError
        except ValueError:
            return _err("InvalidRequest", "MinStorageBytesPercentage must be between 0.1 and 100.", 400)
    for exp in ("DataExport/S3BucketDestination", "ExpandedPrefixesDataExport/S3BucketDestination"):
        d = root.find(exp)
        if d is None:
            continue
        if _text(d, "Format") not in ("CSV", "Parquet") or _text(d, "OutputSchemaVersion") != "V_1":
            return _err("InvalidRequest", "S3BucketDestination needs Format CSV|Parquet and OutputSchemaVersion V_1.", 400)
        bn = _text(d, "Arn").rsplit(":::", 1)[-1]
        if not _text(d, "Arn") or not store.bucket_exists(bn):
            return _err("InvalidRequest", "The data export destination bucket does not exist.", 400)
        if _text(d, "AccountId") != _ACCOUNT:
            return _err("InvalidRequest", "The data export destination AccountId must be your account.", 400)
    for gl in root.findall("AccountLevel/StorageLensGroupLevel/SelectionCriteria/Include/Arn") + root.findall("AccountLevel/StorageLensGroupLevel/SelectionCriteria/Exclude/Arn"):
        if (gl.text or "").strip().rsplit("/", 1)[-1] not in _lens(store)["groups"]:
            return _err("InvalidRequest", f"Storage Lens group {gl.text} does not exist.", 400)
    return None


def _entry_xml(c: dict) -> str:
    root = _cfg_root(c)
    return (f"<StorageLensConfiguration><Id>{c['id']}</Id><StorageLensArn>{_lens_arn(c['id'])}</StorageLensArn><HomeRegion>{_HOME}</HomeRegion>"
            f"<IsEnabled>{'true' if _bool(root, 'IsEnabled') else 'false'}</IsEnabled></StorageLensConfiguration>")


def s3control_lens(store, method: str, segs: list, query: dict, body: bytes):
    """segs = [v20180820, storagelens, …]"""
    m = _m()
    lens = _lens(store)
    rest = segs[2:]
    if not rest:
        if method != "GET":
            return m._s3c_error("MethodNotAllowed", method, 405)
        ids = sorted(set(lens["configs"]) | {DEFAULT_DASHBOARD})
        rows, nxt = m._page([_get_cfg(store, i) for i in ids], query)
        return m._s3c_ok("ListStorageLensConfigurations", "".join(_entry_xml(c) for c in rows) + m._next_xml(nxt))
    cid = rest[0]
    sub = rest[1] if len(rest) > 1 else ""
    if sub not in ("", "tagging") or len(rest) > 2:
        return m._s3c_error("NotImplemented", "Unknown Storage Lens operation.", 501)
    c = _get_cfg(store, cid)
    if sub == "" and method == "PUT":
        if not _ID_RE.match(cid):
            return _err("InvalidRequest", "Storage Lens configuration ids may contain letters, numbers, hyphens, underscores and periods (1-64).", 400)
        req = m._s3c_root(body)
        if req is None:
            return m._s3c_malformed()
        cfg = req.find("StorageLensConfiguration") if req.tag != "StorageLensConfiguration" else req
        if cfg is None:
            return _err("MalformedXML", "StorageLensConfiguration is required.", 400)
        bad = _validate_config(store, cid, cfg)
        if bad:
            return bad
        tags = _parse_tags(req.find("Tags")) if req.tag != "StorageLensConfiguration" else {}
        if _validate_tags(tags):
            return _err("InvalidTag", _validate_tags(tags), 400)
        if c is None and len(lens["configs"]) >= 50:
            return _err("InvalidRequest", "You can create at most 50 Storage Lens dashboards per account and home region.", 400)
        for tag in cfg.findall("StorageLensArn"):
            cfg.remove(tag)
        ET.SubElement(cfg, "StorageLensArn").text = _lens_arn(cid)
        prev = lens["configs"].get(cid)
        lens["configs"][cid] = {"id": cid, "xml": ET.tostring(cfg, encoding="unicode"), "tags": (tags or (prev or {}).get("tags") or {}),
                                "created": (prev or {}).get("created") or m._now()}
        return m._done(store, m._empty_response(200))
    if c is None:
        return _err("NoSuchConfiguration", "The specified Storage Lens configuration does not exist.", 404)
    if sub == "" and method == "GET":
        return m._xml_response('<?xml version="1.0" encoding="UTF-8"?>' + _with_ns(c["xml"], "StorageLensConfiguration"))
    if sub == "" and method == "DELETE":
        if cid == DEFAULT_DASHBOARD:
            return _err("InvalidRequest", "The default dashboard cannot be deleted. You can disable it instead.", 400)
        lens["configs"].pop(cid, None)
        lens["snapshots"].pop(cid, None)
        return m._done(store, m._empty_response(204))
    if sub == "tagging":
        if method == "GET":
            return m._s3c_ok("GetStorageLensConfigurationTagging", m._tags_xml(list(c["tags"].items()), "Tags", "Tag"))
        if method == "PUT":
            req = m._s3c_root(body)
            if req is None:
                return m._s3c_malformed()
            tags = _parse_tags(req.find("Tags"))
            if _validate_tags(tags):
                return _err("InvalidTag", _validate_tags(tags), 400)
            if cid == DEFAULT_DASHBOARD and cid not in lens["configs"]:
                lens["configs"][cid] = {**c, "created": m._now()}
                c = lens["configs"][cid]
            c["tags"] = tags
            return m._done(store, m._empty_response(204))
        if method == "DELETE":
            c["tags"] = {}
            return m._done(store, m._empty_response(204))
    return m._s3c_error("MethodNotAllowed", method, 405)


# ── Storage Lens groups ────────────────────────────────────────────────────────────────
_COND_TYPES = ("MatchAnyPrefix", "MatchAnySuffix", "MatchAnyTag", "MatchObjectAge", "MatchObjectSize")


def _parse_cond(el):
    """-> (cond dict, error str|None) for a filter / And / Or container."""
    cond = {}
    for ch in el:
        t = ch.tag
        if t == "MatchAnyPrefix":
            cond["prefix"] = [(p.text or "") for p in ch.findall("Prefix")]
        elif t == "MatchAnySuffix":
            cond["suffix"] = [(p.text or "") for p in ch.findall("Suffix")]
        elif t == "MatchAnyTag":
            cond["tag"] = [((x.findtext("Key") or ""), (x.findtext("Value") or "")) for x in ch.findall("Tag")]
        elif t in ("MatchObjectAge", "MatchObjectSize"):
            a, b = ("DaysGreaterThan", "DaysLessThan") if t == "MatchObjectAge" else ("BytesGreaterThan", "BytesLessThan")
            d = {}
            for key, tag in (("gt", a), ("lt", b)):
                v = ch.findtext(tag)
                if v not in (None, ""):
                    try:
                        d[key] = int(v)
                    except ValueError:
                        return None, f"{tag} must be an integer."
                    if d[key] < 0:
                        return None, f"{tag} must not be negative."
            if not d:
                return None, f"{t} needs {a} and/or {b}."
            if "gt" in d and "lt" in d and d["gt"] >= d["lt"]:
                return None, f"{a} must be less than {b}."
            cond["age" if t == "MatchObjectAge" else "size"] = d
        elif t in ("And", "Or"):
            continue
        else:
            return None, f"Unknown filter member {t}."
    for k in ("prefix", "suffix", "tag"):
        if k in cond and not cond[k]:
            return None, "Match lists must contain at least one entry."
    return cond, None


def parse_group_filter(f):
    """Filter element -> {"op": "single"|"And"|"Or", "cond": {...}} or error string."""
    if f is None:
        return None, "Filter is required."
    and_, or_ = f.find("And"), f.find("Or")
    top = [ch for ch in f if ch.tag in _COND_TYPES]
    if (1 if and_ is not None else 0) + (1 if or_ is not None else 0) + (1 if top else 0) != 1:
        return None, "Specify exactly one of a single match condition, And, or Or in Filter."
    if and_ is not None or or_ is not None:
        el = and_ if and_ is not None else or_
        cond, err = _parse_cond(el)
        if err:
            return None, err
        if not cond:
            return None, "And/Or must contain at least one match condition."
        return {"op": "And" if and_ is not None else "Or", "cond": cond}, None
    if len(top) != 1:
        return None, "Only one match condition may be specified outside And/Or."
    cond, err = _parse_cond(f)
    return ({"op": "single", "cond": cond}, None) if not err else (None, err)


def _cond_matches(cond: dict, key: str, ver: dict, now: datetime, mode: str) -> bool:
    checks = []
    if "prefix" in cond:
        checks.append(any(key.startswith(p) for p in cond["prefix"]))
    if "suffix" in cond:
        checks.append(any(key.endswith(s) for s in cond["suffix"]))
    if "tag" in cond:
        tg = ver.get("tags") or {}
        checks.append(any(tg.get(k) == v for k, v in cond["tag"]))
    if "age" in cond:
        try:
            lm = datetime.strptime(ver.get("last_modified", "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            days = (now - lm).total_seconds() / 86400.0
        except ValueError:
            days = 0.0
        a = cond["age"]
        checks.append(("gt" not in a or days > a["gt"]) and ("lt" not in a or days < a["lt"]))
    if "size" in cond:
        sz = int(ver.get("size") or 0)
        s = cond["size"]
        checks.append(("gt" not in s or sz > s["gt"]) and ("lt" not in s or sz < s["lt"]))
    if not checks:
        return True
    return any(checks) if mode == "Or" else all(checks)


def group_matches(flt: dict, key: str, ver: dict, now: datetime) -> bool:
    return _cond_matches(flt["cond"], key, ver, now, "Or" if flt["op"] == "Or" else "And")


def _group_xml(g: dict) -> str:
    return (f"<StorageLensGroup><Name>{g['name']}</Name>{g['filter_xml']}<StorageLensGroupArn>{_group_arn(g['name'])}</StorageLensGroupArn></StorageLensGroup>")


def _group_from_req(body: bytes, tag: str, name_from_uri: str | None):
    m = _m()
    req = m._s3c_root(body)
    if req is None:
        return None, None, m._s3c_malformed()
    g = req.find("StorageLensGroup")
    if g is None:
        return None, None, _err("MalformedXML", "StorageLensGroup is required.", 400)
    name = _text(g, "Name")
    if name_from_uri is not None and name != name_from_uri:
        return None, None, _err("InvalidRequest", "The group Name must match the name in the URI.", 400)
    if not _GROUP_RE.match(name):
        return None, None, _err("InvalidRequest", "Storage Lens group names may contain letters, numbers, hyphens and underscores (1-64).", 400)
    f = g.find("Filter")
    flt, err = parse_group_filter(f)
    if err:
        return None, None, _err("InvalidRequest", err, 400)
    return {"name": name, "filter": flt, "filter_xml": ET.tostring(f, encoding="unicode"), "tags": {}}, req, None


def s3control_group(store, method: str, segs: list, query: dict, body: bytes):
    m = _m()
    groups = _lens(store)["groups"]
    rest = segs[2:]
    if not rest:
        if method == "GET":
            rows, nxt = m._page([groups[n] for n in sorted(groups)], query)
            return m._s3c_ok("ListStorageLensGroups", "".join(
                f"<StorageLensGroup><Name>{g['name']}</Name><StorageLensGroupArn>{_group_arn(g['name'])}</StorageLensGroupArn><HomeRegion>{_HOME}</HomeRegion></StorageLensGroup>"
                for g in rows) + m._next_xml(nxt))
        if method == "POST":
            g, req, err = _group_from_req(body, "Create", None)
            if err:
                return err
            if g["name"] in groups:
                return _err("Conflict", "A Storage Lens group with this name already exists.", 409)
            if len(groups) >= 50:
                return _err("InvalidRequest", "You can create at most 50 Storage Lens groups per account and home region.", 400)
            tags = _parse_tags(req.find("Tags"))
            if _validate_tags(tags):
                return _err("InvalidTag", _validate_tags(tags), 400)
            g["tags"] = tags
            g["created"] = m._now()
            groups[g["name"]] = g
            return m._done(store, m._empty_response(204))
        return m._s3c_error("MethodNotAllowed", method, 405)
    name = rest[0]
    if len(rest) > 1:
        return m._s3c_error("NotImplemented", "Unknown Storage Lens group operation.", 501)
    if method == "PUT":
        if name not in groups:
            return _err("NoSuchStorageLensGroup", "The specified Storage Lens group does not exist.", 404)
        g, _req, err = _group_from_req(body, "Update", name)
        if err:
            return err
        g["tags"], g["created"] = groups[name]["tags"], groups[name].get("created")
        groups[name] = g
        return m._done(store, m._empty_response(204))
    g = groups.get(name)
    if g is None:
        return _err("NoSuchStorageLensGroup", "The specified Storage Lens group does not exist.", 404)
    if method == "GET":
        return m._xml_response('<?xml version="1.0" encoding="UTF-8"?>' + _with_ns(_group_xml(g), "StorageLensGroup"))
    if method == "DELETE":
        groups.pop(name, None)
        return m._done(store, m._empty_response(204))
    return m._s3c_error("MethodNotAllowed", method, 405)


def s3control_tags(store, method: str, segs: list, query: dict, body: bytes):
    """/v20180820/tags/{resourceArn+} for Storage Lens dashboards and groups (other resource types: NoSuchResource)."""
    m = _m()
    arn = "/".join(segs[2:])
    mt = re.match(r"^arn:aws:s3:[a-z0-9-]*:\d{12}:storage-lens(-group)?/(.+)$", arn)
    target = None
    if mt:
        if mt.group(1):
            target = _lens(store)["groups"].get(mt.group(2))
        else:
            target = _get_cfg(store, mt.group(2))
            if target is not None and mt.group(2) == DEFAULT_DASHBOARD and method != "GET":
                target = _lens(store)["configs"].setdefault(DEFAULT_DASHBOARD, {**target, "created": m._now()})
    if target is None:
        return _err("NoSuchResource", "The specified resource does not exist or does not support tagging.", 404)
    if method == "GET":
        return m._s3c_ok("ListTagsForResource", m._tags_xml(list(target["tags"].items()), "Tags", "Tag"))
    if method == "POST":
        req = m._s3c_root(body)
        if req is None:
            return m._s3c_malformed()
        merged = {**target["tags"], **_parse_tags(req.find("Tags"))}
        if _validate_tags(merged):
            return _err("InvalidTag", _validate_tags(merged), 400)
        target["tags"] = merged
        return m._done(store, m._s3c_ok("TagResource"))
    if method == "DELETE":
        raw = (query or {}).get("tagKeys") or ""
        for k in (raw if isinstance(raw, list) else [x for x in str(raw).split(",") if x]):
            target["tags"].pop(k, None)
        return m._done(store, m._empty_response(204))
    return m._s3c_error("MethodNotAllowed", method, 405)


# ═══ Storage Lens: dashboard data from the real store ═════════════════════════════════
def _config_scope(store, c: dict):
    """-> predicate(bucket_name, region) for the dashboard's Include/Exclude."""
    root = _cfg_root(c)
    inc = {(a.text or "").strip().rsplit(":::", 1)[-1] for a in root.findall("Include/Buckets/Arn")}
    exc = {(a.text or "").strip().rsplit(":::", 1)[-1] for a in root.findall("Exclude/Buckets/Arn")}
    iregs = {(a.text or "").strip() for a in root.findall("Include/Regions/Region")}
    eregs = {(a.text or "").strip() for a in root.findall("Exclude/Regions/Region")}

    def ok(name, region):
        if inc and name not in inc:
            return False
        if name in exc:
            return False
        if iregs and region not in iregs:
            return False
        return region not in eregs
    return ok, root


def lens_data(store, cid: str, query: dict):
    m = _m()
    c = _get_cfg(store, cid)
    if c is None:
        return _jerr("NoSuchConfiguration", "The specified Storage Lens configuration does not exist.", 404)
    ok, root = _config_scope(store, c)
    q = query or {}
    try:
        top_n = max(1, min(int(q.get("topN") or 20), 100))
    except ValueError:
        top_n = 20
    gname = q.get("group") or ""
    groups = _lens(store)["groups"]
    only_group = groups.get(gname) if gname else None
    if gname and only_group is None:
        return _jerr("NoSuchStorageLensGroup", f"Storage Lens group {gname} does not exist.", 404)
    sc = root.find("AccountLevel/BucketLevel/PrefixLevel/StorageMetrics/SelectionCriteria")
    delim = _text(sc, "Delimiter") or "/"
    try:
        max_depth = int(_text(sc, "MaxDepth") or 10)
    except ValueError:
        max_depth = 10
    try:
        min_pct = float(_text(sc, "MinStorageBytesPercentage") or 0)
    except ValueError:
        min_pct = 0.0
    prefix_enabled = _bool(root, "AccountLevel/BucketLevel/PrefixLevel/StorageMetrics/IsEnabled")
    incl_groups = [(a.text or "").strip().rsplit("/", 1)[-1] for a in root.findall("AccountLevel/StorageLensGroupLevel/SelectionCriteria/Include/Arn")]
    excl_groups = {(a.text or "").strip().rsplit("/", 1)[-1] for a in root.findall("AccountLevel/StorageLensGroupLevel/SelectionCriteria/Exclude/Arn")}
    group_names = [g for g in (incl_groups or []) if g in groups and g not in excl_groups]
    now = datetime.now(timezone.utc)

    tot = {"currentBytes": 0, "currentObjects": 0, "noncurrentBytes": 0, "noncurrentObjects": 0, "deleteMarkers": 0, "incompleteMpuBytes": 0,
           "incompleteMpuUploads": 0}
    by_bucket, by_class, by_prefix = {}, {}, {}
    by_group = {g: {"bytes": 0, "objects": 0} for g in group_names}
    buckets = []
    for name in sorted(store.buckets):
        meta = store.buckets[name] or {}
        if meta.get("internal") or meta.get("bucket_type") == "Directory":
            continue
        region = meta.get("region") or _HOME
        if not ok(name, region):
            continue
        buckets.append(name)
        b = by_bucket.setdefault(name, {"bucket": name, "region": region, "bytes": 0, "objects": 0, "currentBytes": 0, "noncurrentBytes": 0, "deleteMarkers": 0,
                                        "incompleteMpuBytes": 0})
        for key, entry in store.bucket_objects(name).items():
            vs = entry.get("versions") or [] if isinstance(entry, dict) else []
            for idx, v in enumerate(vs):
                if v.get("is_delete_marker"):
                    if only_group is None:
                        tot["deleteMarkers"] += 1
                        b["deleteMarkers"] += 1
                    continue
                if only_group is not None and (idx != 0 or not group_matches(only_group["filter"], key, v, now)):
                    continue
                size = int(v.get("size") or 0)
                if idx == 0:
                    tot["currentBytes"] += size
                    tot["currentObjects"] += 1
                    b["currentBytes"] += size
                else:
                    tot["noncurrentBytes"] += size
                    tot["noncurrentObjects"] += 1
                    b["noncurrentBytes"] += size
                b["bytes"] += size
                b["objects"] += 1
                sc_name = v.get("storage_class") or "STANDARD"
                cl = by_class.setdefault(sc_name, {"storageClass": sc_name, "bytes": 0, "objects": 0})
                cl["bytes"] += size
                cl["objects"] += 1
                if idx == 0:
                    segs_ = key.split(delim)
                    for d in range(1, min(max_depth, len(segs_) - 1) + 1):
                        pre = delim.join(segs_[:d]) + delim
                        pr = by_prefix.setdefault((name, pre), {"bucket": name, "prefix": pre, "depth": d, "bytes": 0, "objects": 0})
                        pr["bytes"] += size
                        pr["objects"] += 1
                    for g in group_names:
                        if group_matches(groups[g]["filter"], key, v, now):
                            by_group[g]["bytes"] += size
                            by_group[g]["objects"] += 1
    if only_group is None:
        for up in m._mpu(store).values():
            if up.get("bucket") in by_bucket:
                size = sum(int(p.get("size") or len(p.get("data") or b"")) for p in m._parts(up).values())
                tot["incompleteMpuBytes"] += size
                tot["incompleteMpuUploads"] += 1
                by_bucket[up["bucket"]]["incompleteMpuBytes"] += size
                by_bucket[up["bucket"]]["bytes"] += size
    total_bytes = tot["currentBytes"] + tot["noncurrentBytes"] + tot["incompleteMpuBytes"]
    objects = tot["currentObjects"] + tot["noncurrentObjects"]
    object_bytes = tot["currentBytes"] + tot["noncurrentBytes"]
    summary = {**tot, "totalBytes": total_bytes, "objectCount": objects, "bucketCount": len(buckets),
               "avgObjectBytes": (object_bytes // objects) if objects else 0,
               "currentVersionPct": round(100.0 * tot["currentBytes"] / object_bytes, 2) if object_bytes else 0.0,
               "noncurrentVersionPct": round(100.0 * tot["noncurrentBytes"] / object_bytes, 2) if object_bytes else 0.0,
               "deleteMarkerPct": round(100.0 * tot["deleteMarkers"] / (objects + tot["deleteMarkers"]), 2) if (objects + tot["deleteMarkers"]) else 0.0,
               "incompleteMpuPct": round(100.0 * tot["incompleteMpuBytes"] / total_bytes, 2) if total_bytes else 0.0}
    prefixes = [p for p in by_prefix.values() if total_bytes and 100.0 * p["bytes"] / total_bytes >= min_pct]
    prefixes.sort(key=lambda p: (-p["bytes"], p["bucket"], p["prefix"]))
    pct = lambda b: round(100.0 * b / total_bytes, 2) if total_bytes else 0.0
    snap = _record_snapshot(store, cid, summary) if only_group is None else None
    snaps = list(_lens(store)["snapshots"].get(cid, []))
    return _jresp(200, {
        "id": cid, "arn": _lens_arn(cid), "isDefault": cid == DEFAULT_DASHBOARD, "enabled": bool(_bool(root, "IsEnabled")), "generatedAt": m._now(),
        "scope": {"buckets": buckets, "group": gname or None, "prefixDelimiter": delim, "maxDepth": max_depth, "minStorageBytesPercentage": min_pct,
                  "prefixAggregationConfigured": bool(prefix_enabled)},
        "summary": summary,
        "byBucket": sorted(({**b, "pct": pct(b["bytes"])} for b in by_bucket.values()), key=lambda r: -r["bytes"]),
        "byStorageClass": sorted(({**r, "pct": pct(r["bytes"])} for r in by_class.values()), key=lambda r: -r["bytes"]),
        "byPrefix": [{**p, "pct": pct(p["bytes"])} for p in prefixes[:top_n]],
        "byGroup": [{"group": g, "arn": _group_arn(g), **v, "pct": pct(v["bytes"])} for g, v in by_group.items()],
        "trend": snaps,
        "activityMetrics": {"modelled": False, "enabledInConfig": bool(_bool(root, "AccountLevel/ActivityMetrics/IsEnabled")),
                            "reason": "Request and bytes-transferred activity metrics are not modelled: the simulator keeps no account-wide request counters."},
    })


def _record_snapshot(store, cid: str, summary: dict):
    """Daily snapshot, recorded lazily on read: today's row is created once and refreshed on later reads the same day."""
    m = _m()
    rows = _lens(store)["snapshots"].setdefault(cid, [])
    today = _day(m._now())
    row = {"date": today, "totalBytes": summary["totalBytes"], "objectCount": summary["objectCount"], "currentBytes": summary["currentBytes"],
           "noncurrentBytes": summary["noncurrentBytes"], "deleteMarkers": summary["deleteMarkers"], "incompleteMpuBytes": summary["incompleteMpuBytes"],
           "bucketCount": summary["bucketCount"]}
    if rows and rows[-1]["date"] == today:
        rows[-1] = row
    else:
        rows.append(row)
    del rows[:-_SNAPSHOT_KEEP]
    return row
