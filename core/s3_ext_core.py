"""S3 bucket extensions (sweep S3-4) — substrate-independent, loaded by core/s3_object_core.py.

 * Transfer acceleration: Put/GetBucketAccelerateConfiguration (real wire shape) + the `<bucket>.s3-accelerate[.dualstack]
   .amazonaws.com` Host form is accepted for Enabled buckets (InvalidRequest otherwise). It changes nothing about speed.
 * S3 Metadata: CreateBucketMetadataConfiguration / Get / Delete (V2 `?metadataConfiguration`), the V1 table-configuration
   form (`?metadataTable`), UpdateBucketMetadataJournalTableConfiguration / InventoryTableConfiguration. The JOURNAL is a
   queryable per-bucket record log written by the real object mutations (create / update / delete incl. lifecycle); the
   INVENTORY is computed from the live store on every read. Vyomi route: /v20180820/_vyomi/bucket-metadata/{bucket}.
 * A minimal CloudTrail (JSON 1.1, signing name `cloudtrail`): trails + event selectors (basic + advanced) + start/stop
   logging, and the S3 object-level DATA EVENTS (GetObject/PutObject/DeleteObject/...) Vyomi actually serves are recorded
   against matching, logging trails. Vyomi route: /v20180820/_vyomi/bucket-trail/{bucket}.
 * Bucket-level Storage Lens: per-bucket storage + request activity from real store state / served-request counters.
   Vyomi route: /v20180820/_vyomi/bucket-lens/{bucket}.

State lives in `store.account["s3ext"]` so every substrate persists it. NO fastapi / boto3 imports — loads under Pyodide.
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
_REGION = "us-east-1"
_S3NS = "http://s3.amazonaws.com/doc/2006-03-01/"
_JOURNAL_CAP = 5000
_EVENT_CAP = 3000
_DAYS_KEEP = 30
META_SUBS = ("metadataConfiguration", "metadataTable", "metadataJournalTable", "metadataInventoryTable")
_TRAIL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{2,127}$")
_ACCEL_HOST_RE = re.compile(r"^(?P<b>.+?)\.s3-accelerate(\.dualstack)?\.amazonaws\.com(\.cn)?(:\d+)?$", re.I)


def _m():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m                          # type: ignore
    return m


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(store) -> dict:
    st = store.account.setdefault("s3ext", {})
    st.setdefault("journal", {})
    st.setdefault("seq", {})
    st.setdefault("trails", {})
    st.setdefault("events", [])
    st.setdefault("reqs", {})
    return st


def _jresp(status: int, doc):
    m = _m()
    return m.S3Response(status=status, headers=m._amz_headers(), body=json.dumps(doc).encode(), media_type="application/json")


def _jerr(code: str, message: str, status: int):
    return _jresp(status, {"error": code, "message": message})


def _xerr(code: str, message: str, bucket: str, status: int):
    return _m()._error_xml(code, message, f"/{bucket}", status)


def _x(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _t(el, path: str, default: str = "") -> str:
    if el is None:
        return default
    f = el.find(path)
    return (f.text or "").strip() if f is not None and f.text is not None else default


def _strip_ns(root):
    for e in root.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return root


def _parse(body: bytes):
    try:
        return _strip_ns(ET.fromstring(body or b""))
    except ET.ParseError:
        return None


# ═══ Host-style accelerate endpoint ═══════════════════════════════════════════════════
def accelerate_host(store, raw: str, lheaders: dict):
    """`<bucket>.s3-accelerate.amazonaws.com` Host -> (path-style raw path, error response|None). (raw, None) when N/A."""
    host = (lheaders.get("host") or "").strip()
    mt = _ACCEL_HOST_RE.match(host)
    if not mt:
        return raw, None
    bucket = mt.group("b")
    if raw.partition("/")[0] != bucket:
        raw = f"{bucket}/{raw}" if raw else bucket
    meta = store.buckets.get(bucket)
    if meta is None:
        return raw, None                      # NoSuchBucket comes from the normal path
    if (meta.get("cfg") or {}).get("accelerate") != "Enabled":
        return raw, _xerr("InvalidRequest", "S3 Transfer Acceleration is not configured on this bucket", bucket, 400)
    return raw, None


# ═══ Transfer acceleration ════════════════════════════════════════════════════════════
def accelerate(store, method: str, bucket: str, body: bytes):
    m = _m()
    meta = store.buckets[bucket]
    cfg = meta.setdefault("cfg", {})
    if method == "GET":
        st = cfg.get("accelerate", "")
        inner = f"<Status>{st}</Status>" if st else ""
        return m._xml_response(f'<?xml version="1.0" encoding="UTF-8"?><AccelerateConfiguration xmlns="{_S3NS}">{inner}</AccelerateConfiguration>')
    if method == "PUT":
        root = _parse(body)
        status = _t(root, "Status") if root is not None else ""
        if root is None or root.tag != "AccelerateConfiguration" or status not in ("Enabled", "Suspended"):
            return m._error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema", f"/{bucket}", 400)
        if "." in bucket:
            return m._error_xml("InvalidRequest", "S3 Transfer Acceleration is not supported for buckets with periods (.) in their names", f"/{bucket}", 400)
        if m.is_directory_bucket(store, bucket):
            return m._error_xml("InvalidRequest", "S3 Transfer Acceleration is not supported for directory buckets", f"/{bucket}", 400)
        cfg["accelerate"] = status
        return m._done(store, m._empty_response(200))
    return m._error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}", 405)


# ═══ S3 Metadata ══════════════════════════════════════════════════════════════════════
def _table_arn(tb_arn: str, name: str, seed: str) -> str:
    return f"{tb_arn}/table/{uuid.uuid5(uuid.NAMESPACE_URL, seed + name)}"


def _enc_xml(enc: dict | None) -> str:
    if not enc:
        return ""
    return (f"<EncryptionConfiguration><SseAlgorithm>{_x(enc['sse'])}</SseAlgorithm>"
            + (f"<KmsKeyArn>{_x(enc['kms'])}</KmsKeyArn>" if enc.get("kms") else "") + "</EncryptionConfiguration>")


def _enc_from(root):
    e = root.find("EncryptionConfiguration") if root is not None else None
    if e is None:
        return None, None
    sse, kms = _t(e, "SseAlgorithm"), _t(e, "KmsKeyArn")
    if sse not in ("aws:kms", "AES256"):
        return None, "EncryptionConfiguration SseAlgorithm must be aws:kms or AES256."
    if sse == "aws:kms" and not kms:
        return None, "KmsKeyArn is required when SseAlgorithm is aws:kms."
    return {"sse": sse, "kms": kms}, None


def _meta_cfg(store, bucket):
    return (store.buckets[bucket].get("cfg") or {}).get("s3_metadata")


def _parse_expiry(el):
    ex = el.find("RecordExpiration") if el is not None else None
    if ex is None:
        return None, "RecordExpiration is required."
    exp = _t(ex, "Expiration")
    if exp not in ("ENABLED", "DISABLED"):
        return None, "RecordExpiration Expiration must be ENABLED or DISABLED."
    days = None
    if exp == "ENABLED":
        try:
            days = int(_t(ex, "Days"))
        except ValueError:
            return None, "RecordExpiration Days is required when Expiration is ENABLED."
        if days < 7:
            return None, "RecordExpiration Days must be at least 7."
    return {"expiration": exp, "days": days}, None


def _v2_result_xml(bucket: str, cfg: dict) -> str:
    j, inv = cfg["journal"], cfg["inventory"]
    dest = cfg["destination"]
    exp = j["expiry"]
    exp_xml = f"<RecordExpiration><Expiration>{exp['expiration']}</Expiration>" + (f"<Days>{exp['days']}</Days>" if exp.get("days") else "") + "</RecordExpiration>"
    return (f"<MetadataConfigurationResult><DestinationResult><TableBucketType>{dest['type']}</TableBucketType>"
            f"<TableBucketArn>{_x(dest['arn'])}</TableBucketArn><TableNamespace>{_x(dest['namespace'])}</TableNamespace></DestinationResult>"
            f"<JournalTableConfigurationResult><TableStatus>ACTIVE</TableStatus><TableName>journal</TableName>"
            f"<TableArn>{_x(_table_arn(dest['arn'], 'journal', bucket))}</TableArn>{exp_xml}</JournalTableConfigurationResult>"
            f"<InventoryTableConfigurationResult><ConfigurationState>{inv['state']}</ConfigurationState>"
            + (f"<TableStatus>ACTIVE</TableStatus><TableName>inventory</TableName><TableArn>{_x(_table_arn(dest['arn'], 'inventory', bucket))}</TableArn>"
               if inv["state"] == "ENABLED" else "")
            + "</InventoryTableConfigurationResult></MetadataConfigurationResult>")


def metadata_api(store, method: str, bucket: str, query: dict, body: bytes):
    m = _m()
    cfg_all = store.buckets[bucket].setdefault("cfg", {})
    sub = next(k for k in META_SUBS if k in query)
    cur = cfg_all.get("s3_metadata")
    hdr = '<?xml version="1.0" encoding="UTF-8"?>'
    bad = lambda msg: m._error_xml("InvalidRequest", msg, f"/{bucket}", 400)           # noqa: E731
    malformed = m._error_xml("MalformedXML", "The XML you provided was not well-formed or did not validate against our published schema", f"/{bucket}", 400)
    notfound = m._error_xml("MetadataConfigurationNotFound", "The specified bucket does not have a metadata configuration.", f"/{bucket}", 404)
    if m.is_directory_bucket(store, bucket):
        return bad("S3 Metadata is not supported for directory buckets.")
    if sub == "metadataConfiguration":                                                  # V2
        if method == "POST":
            if cur:
                return m._error_xml("MetadataConfigurationAlreadyExists", "A metadata configuration already exists for this bucket.", f"/{bucket}", 409)
            root = _parse(body)
            if root is None or root.tag != "MetadataConfiguration":
                return malformed
            jt, it = root.find("JournalTableConfiguration"), root.find("InventoryTableConfiguration")
            if jt is None:
                return malformed
            exp, err = _parse_expiry(jt)
            if err:
                return bad(err)
            jenc, err = _enc_from(jt)
            if err:
                return bad(err)
            state, ienc = "DISABLED", None
            if it is not None:
                state = _t(it, "ConfigurationState")
                if state not in ("ENABLED", "DISABLED"):
                    return bad("InventoryTableConfiguration ConfigurationState must be ENABLED or DISABLED.")
                ienc, err = _enc_from(it)
                if err:
                    return bad(err)
            else:
                return malformed
            cfg_all["s3_metadata"] = {
                "version": 2, "created": _now(),
                "destination": {"type": "aws", "arn": f"arn:aws:s3tables:{_REGION}:{_ACCOUNT}:bucket/aws-s3",
                                "namespace": "b_" + re.sub(r"[^a-z0-9_]", "_", bucket)},
                "journal": {"expiry": exp, "enc": jenc}, "inventory": {"state": state, "enc": ienc}}
            return m._done(store, m._empty_response(200))
        if method == "GET":
            if not cur or cur["version"] != 2:
                return notfound
            return m._xml_response(f'{hdr}<GetBucketMetadataConfigurationResult xmlns="{_S3NS}">{_v2_result_xml(bucket, cur)}</GetBucketMetadataConfigurationResult>')
        if method == "DELETE":
            if not cur:
                return notfound
            cfg_all.pop("s3_metadata", None)
            _state(store)["journal"].pop(bucket, None)
            return m._done(store, m._empty_response(204))
    elif sub == "metadataTable":                                                        # V1
        if method == "POST":
            if cur:
                return m._error_xml("MetadataConfigurationAlreadyExists", "A metadata configuration already exists for this bucket.", f"/{bucket}", 409)
            root = _parse(body)
            d = root.find("S3TablesDestination") if root is not None else None
            if root is None or root.tag != "MetadataTableConfiguration" or d is None:
                return malformed
            arn, name = _t(d, "TableBucketArn"), _t(d, "TableName")
            if not re.match(r"^arn:aws[-a-z0-9]*:s3tables:[-a-z0-9]*:\d{12}:bucket/[a-z0-9_-]{3,63}$", arn) or not re.match(r"^[0-9a-z_]{1,255}$", name):
                return bad("S3TablesDestination needs a valid table bucket ARN and a table name of lowercase letters, digits and underscores.")
            cfg_all["s3_metadata"] = {"version": 1, "created": _now(),
                                      "destination": {"type": "customer", "arn": arn, "namespace": "b_" + re.sub(r"[^a-z0-9_]", "_", bucket), "table": name},
                                      "journal": {"expiry": {"expiration": "DISABLED", "days": None}, "enc": None}, "inventory": {"state": "DISABLED", "enc": None}}
            return m._done(store, m._empty_response(200))
        if method == "GET":
            if not cur or cur["version"] != 1:
                return notfound
            d = cur["destination"]
            return m._xml_response(
                f'{hdr}<GetBucketMetadataTableConfigurationResult xmlns="{_S3NS}"><MetadataTableConfigurationResult><S3TablesDestinationResult>'
                f"<TableBucketArn>{_x(d['arn'])}</TableBucketArn><TableName>{_x(d['table'])}</TableName>"
                f"<TableArn>{_x(_table_arn(d['arn'], d['table'], bucket))}</TableArn><TableNamespace>{_x(d['namespace'])}</TableNamespace>"
                f"</S3TablesDestinationResult></MetadataTableConfigurationResult><Status>ACTIVE</Status></GetBucketMetadataTableConfigurationResult>")
        if method == "DELETE":
            if not cur:
                return notfound
            cfg_all.pop("s3_metadata", None)
            _state(store)["journal"].pop(bucket, None)
            return m._done(store, m._empty_response(204))
    elif sub in ("metadataJournalTable", "metadataInventoryTable") and method == "PUT":  # V2 updates
        if not cur or cur["version"] != 2:
            return notfound
        root = _parse(body)
        if root is None:
            return malformed
        if sub == "metadataJournalTable":
            if root.tag != "JournalTableConfiguration":
                return malformed
            exp, err = _parse_expiry(root)
            if err:
                return bad(err)
            cur["journal"]["expiry"] = exp
        else:
            if root.tag != "InventoryTableConfiguration":
                return malformed
            state = _t(root, "ConfigurationState")
            if state not in ("ENABLED", "DISABLED"):
                return bad("InventoryTableConfiguration ConfigurationState must be ENABLED or DISABLED.")
            cur["inventory"]["state"] = state
        return m._done(store, m._empty_response(200))
    return m._error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}", 405)


def _journal_cols():
    return ["bucket", "key", "sequence_number", "record_type", "record_timestamp", "version_id", "is_delete_marker", "size",
            "last_modified_date", "e_tag", "storage_class", "is_multipart", "encryption_status", "is_bucket_key_enabled",
            "kms_key_arn", "checksum_algorithm", "object_tags", "user_metadata", "requester", "source_ip_address", "request_id"]


def _next_seq(st, bucket) -> str:
    n = st["seq"].get(bucket, 0) + 1
    st["seq"][bucket] = n
    return f"{int(datetime.now(timezone.utc).timestamp()):08x}{n:016x}"


def _sse_of(store, bucket) -> str:
    cfg = (store.buckets.get(bucket) or {}).get("cfg") or {}
    return "SSE-KMS" if "aws:kms" in str(cfg.get("encryption") or "") else "SSE-S3"


def on_emit(store, bucket: str, key: str, event: str, version, source: str) -> None:
    """Journal one real object mutation (called from s3_object_core._emit)."""
    cfg = _meta_cfg(store, bucket) if bucket in store.buckets else None
    if not cfg or not key:
        return
    if event.startswith("s3:ObjectCreated"):
        rtype = "CREATE"
    elif event.startswith("s3:ObjectRemoved") or event.startswith("s3:LifecycleExpiration"):
        rtype = "DELETE"
        if "DeleteMarkerCreated" in event:
            rtype = "CREATE"
    else:
        return
    st = _state(store)
    v = version or {}
    dm = bool(v.get("is_delete_marker"))
    rec = {"bucket": bucket, "key": key, "sequence_number": _next_seq(st, bucket), "record_type": rtype, "record_timestamp": _now(),
           "version_id": v.get("version_id") if v.get("version_id") not in (None, "null") else None,
           "is_delete_marker": dm, "size": None if rtype == "DELETE" else v.get("size"),
           "last_modified_date": v.get("last_modified"), "e_tag": v.get("etag") or None, "storage_class": v.get("storage_class") if rtype != "DELETE" else None,
           "is_multipart": "-" in str(v.get("etag") or "") if rtype != "DELETE" else None,
           "encryption_status": _sse_of(store, bucket) if rtype != "DELETE" else None,
           "is_bucket_key_enabled": False if rtype != "DELETE" else None, "kms_key_arn": None,
           "checksum_algorithm": (v.get("checksum") or {}).get("algorithm") if isinstance(v.get("checksum"), dict) else None,
           "object_tags": dict(v.get("tags") or {}), "user_metadata": dict(v.get("metadata") or {}),
           "requester": "s3.amazonaws.com" if source == "Lifecycle" else _ACCOUNT, "source_ip_address": "127.0.0.1", "request_id": uuid.uuid4().hex[:16].upper()}
    j = st["journal"].setdefault(bucket, [])
    j.append(rec)
    exp = cfg["journal"]["expiry"]
    if len(j) > _JOURNAL_CAP:
        del j[:len(j) - _JOURNAL_CAP]
    if exp["expiration"] == "ENABLED" and exp.get("days"):
        cut = datetime.now(timezone.utc).timestamp() - exp["days"] * 86400
        j[:] = [r for r in j if _ts(r["record_timestamp"]) >= cut]


def _ts(iso: str) -> float:
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _inventory_rows(store, bucket: str):
    rows = []
    for key, entry in sorted(store.bucket_objects(bucket).items()):
        vs = entry.get("versions") or [] if isinstance(entry, dict) else []
        for idx, v in enumerate(vs):
            rows.append({"bucket": bucket, "key": key, "sequence_number": hashlib.sha1(f"{key}{v.get('version_id')}{v.get('last_modified')}".encode()).hexdigest()[:24],
                         "version_id": v.get("version_id") if v.get("version_id") != "null" else None, "is_latest": idx == 0,
                         "is_delete_marker": bool(v.get("is_delete_marker")), "size": None if v.get("is_delete_marker") else v.get("size"),
                         "last_modified_date": v.get("last_modified"), "e_tag": v.get("etag") or None,
                         "storage_class": None if v.get("is_delete_marker") else (v.get("storage_class") or "STANDARD"),
                         "is_multipart": "-" in str(v.get("etag") or ""), "encryption_status": _sse_of(store, bucket),
                         "is_bucket_key_enabled": False, "kms_key_arn": None,
                         "checksum_algorithm": (v.get("checksum") or {}).get("algorithm") if isinstance(v.get("checksum"), dict) else None,
                         "object_tags": dict(v.get("tags") or {}), "user_metadata": dict(v.get("metadata") or {})})
    return rows


def metadata_view(store, bucket: str, query: dict):
    if bucket not in store.buckets:
        return _jerr("NoSuchBucket", "The specified bucket does not exist.", 404)
    cfg = _meta_cfg(store, bucket)
    if not cfg:
        return _jresp(200, {"configured": False})
    q = query or {}
    table = q.get("table", "journal")
    if table not in ("journal", "inventory"):
        return _jerr("BadRequest", "table must be journal or inventory.", 400)
    try:
        limit = max(1, min(int(q.get("limit") or 100), 1000))
        offset = max(0, int(q.get("offset") or 0))
    except ValueError:
        return _jerr("BadRequest", "limit/offset must be integers.", 400)
    prefix, rtype, key_eq = q.get("prefix", ""), q.get("recordType", ""), q.get("key", "")
    if table == "journal":
        rows = list(reversed(_state(store)["journal"].get(bucket, [])))          # newest first
        cols = _journal_cols()
        enabled = True
        if rtype:
            rows = [r for r in rows if r["record_type"] == rtype]
    else:
        enabled = cfg["inventory"]["state"] == "ENABLED"
        rows = _inventory_rows(store, bucket) if enabled else []
        cols = ["bucket", "key", "sequence_number", "version_id", "is_latest", "is_delete_marker", "size", "last_modified_date", "e_tag",
                "storage_class", "is_multipart", "encryption_status", "is_bucket_key_enabled", "kms_key_arn", "checksum_algorithm", "object_tags", "user_metadata"]
    if prefix:
        rows = [r for r in rows if r["key"].startswith(prefix)]
    if key_eq:
        rows = [r for r in rows if r["key"] == key_eq]
    total = len(rows)
    return _jresp(200, {"configured": True, "version": cfg["version"], "table": table, "tableEnabled": enabled, "columns": cols, "total": total,
                        "offset": offset, "rows": rows[offset:offset + limit],
                        "destination": {"tableBucketArn": cfg["destination"]["arn"], "namespace": cfg["destination"]["namespace"], "tableName": table if cfg["version"] == 2 else cfg["destination"].get("table")},
                        "journalExpiration": cfg["journal"]["expiry"], "inventoryState": cfg["inventory"]["state"]})


# ═══ CloudTrail (minimal) ═════════════════════════════════════════════════════════════
class _CtErr(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _trail_arn(name):
    return f"arn:aws:cloudtrail:{_REGION}:{_ACCOUNT}:trail/{name}"


def _find_trail(st, ident):
    ident = str(ident or "")
    for name, t in st["trails"].items():
        if ident in (name, t["TrailARN"]):
            return t
    raise _CtErr("TrailNotFoundException", f"Unknown trail: {ident} for the user: {_ACCOUNT}", 404)


def _trail_doc(t):
    return {k: v for k, v in t.items() if k not in ("_logging", "_eventSelectors", "_advanced", "_started", "_stopped", "_tags")}


def _validate_selectors(sels):
    if not isinstance(sels, list) or len(sels) > 5:
        raise _CtErr("InvalidEventSelectorsException", "You can have up to 5 event selectors per trail.")
    for s in sels:
        if s.get("ReadWriteType", "All") not in ("All", "ReadOnly", "WriteOnly"):
            raise _CtErr("InvalidEventSelectorsException", "ReadWriteType must be All, ReadOnly or WriteOnly.")
        for d in s.get("DataResources") or []:
            if not d.get("Type") or not isinstance(d.get("Values", []), list):
                raise _CtErr("InvalidEventSelectorsException", "Each DataResource needs a Type and a list of Values.")


def _validate_advanced(sels):
    if not isinstance(sels, list) or not sels or len(sels) > 500:
        raise _CtErr("InvalidEventSelectorsException", "AdvancedEventSelectors needs between 1 and 500 selectors.")
    for s in sels:
        fs = s.get("FieldSelectors")
        if not isinstance(fs, list) or not any(f.get("Field") == "eventCategory" for f in fs):
            raise _CtErr("InvalidEventSelectorsException", "Each advanced event selector needs an eventCategory field selector.")
        for f in fs:
            if not any(k in f for k in ("Equals", "StartsWith", "EndsWith", "NotEquals", "NotStartsWith", "NotEndsWith")):
                raise _CtErr("InvalidEventSelectorsException", f"Field selector {f.get('Field')} needs an operator.")


def _ct_op(store, action: str, p: dict):
    st = _state(store)
    m = _m()
    if action == "CreateTrail":
        name, bucket = p.get("Name"), p.get("S3BucketName")
        if not name or not bucket:
            raise _CtErr("InvalidParameterCombinationException", "Name and S3BucketName are required.")
        if not _TRAIL_RE.match(name) or ".." in name or "--" in name:
            raise _CtErr("InvalidTrailNameException", "Trail name must be 3-128 characters of letters, numbers, periods, underscores and dashes, starting with a letter or number.")
        if name in st["trails"]:
            raise _CtErr("TrailAlreadyExistsException", f"Trail {name} already exists for customer: {_ACCOUNT}")
        if not store.bucket_exists(bucket):
            raise _CtErr("S3BucketDoesNotExistException", f"S3 bucket {bucket} does not exist.")
        t = {"Name": name, "S3BucketName": bucket, "TrailARN": _trail_arn(name), "HomeRegion": _REGION,
             "IncludeGlobalServiceEvents": p.get("IncludeGlobalServiceEvents", True), "IsMultiRegionTrail": bool(p.get("IsMultiRegionTrail", False)),
             "LogFileValidationEnabled": bool(p.get("EnableLogFileValidation", False)), "HasCustomEventSelectors": False,
             "HasInsightSelectors": False, "IsOrganizationTrail": False, "_logging": False, "_eventSelectors": [], "_advanced": [],
             "_tags": list(p.get("TagsList") or [])}
        if p.get("S3KeyPrefix"):
            t["S3KeyPrefix"] = p["S3KeyPrefix"]
        st["trails"][name] = t
        out = {k: v for k, v in _trail_doc(t).items() if k not in ("HasCustomEventSelectors", "HasInsightSelectors", "IsOrganizationTrail", "HomeRegion")}
        out["IsOrganizationTrail"] = False
        return out
    if action == "UpdateTrail":
        t = _find_trail(st, p.get("Name"))
        if p.get("S3BucketName"):
            if not store.bucket_exists(p["S3BucketName"]):
                raise _CtErr("S3BucketDoesNotExistException", f"S3 bucket {p['S3BucketName']} does not exist.")
            t["S3BucketName"] = p["S3BucketName"]
        for a, b in (("S3KeyPrefix", "S3KeyPrefix"), ("IncludeGlobalServiceEvents", "IncludeGlobalServiceEvents"), ("IsMultiRegionTrail", "IsMultiRegionTrail")):
            if a in p:
                t[b] = p[a]
        if "EnableLogFileValidation" in p:
            t["LogFileValidationEnabled"] = bool(p["EnableLogFileValidation"])
        return _trail_doc(t)
    if action in ("DescribeTrails",):
        names = p.get("trailNameList") or []
        rows = [t for t in st["trails"].values() if not names or t["Name"] in names or t["TrailARN"] in names]
        return {"trailList": [_trail_doc(t) for t in rows]}
    if action == "GetTrail":
        return {"Trail": _trail_doc(_find_trail(st, p.get("Name")))}
    if action == "ListTrails":
        return {"Trails": [{"TrailARN": t["TrailARN"], "Name": t["Name"], "HomeRegion": _REGION} for t in st["trails"].values()]}
    if action == "DeleteTrail":
        t = _find_trail(st, p.get("Name"))
        del st["trails"][t["Name"]]
        return {}
    if action in ("StartLogging", "StopLogging"):
        t = _find_trail(st, p.get("Name"))
        t["_logging"] = action == "StartLogging"
        t["_started" if t["_logging"] else "_stopped"] = datetime.now(timezone.utc).timestamp()
        return {}
    if action == "GetTrailStatus":
        t = _find_trail(st, p.get("Name"))
        out = {"IsLogging": t["_logging"]}
        if t.get("_started"):
            out["StartLoggingTime"] = t["_started"]
        if t.get("_stopped"):
            out["StopLoggingTime"] = t["_stopped"]
        return out
    if action == "PutEventSelectors":
        t = _find_trail(st, p.get("TrailName"))
        has_basic, has_adv = "EventSelectors" in p, "AdvancedEventSelectors" in p
        if has_basic == has_adv:
            raise _CtErr("InvalidParameterCombinationException", "Specify exactly one of EventSelectors and AdvancedEventSelectors.")
        if has_basic:
            _validate_selectors(p["EventSelectors"])
            t["_eventSelectors"], t["_advanced"] = p["EventSelectors"], []
        else:
            _validate_advanced(p["AdvancedEventSelectors"])
            t["_advanced"], t["_eventSelectors"] = p["AdvancedEventSelectors"], []
        t["HasCustomEventSelectors"] = True
        out = {"TrailARN": t["TrailARN"]}
        if t["_eventSelectors"]:
            out["EventSelectors"] = t["_eventSelectors"]
        else:
            out["AdvancedEventSelectors"] = t["_advanced"]
        return out
    if action == "PutAdvancedEventSelectors":
        return _ct_op(store, "PutEventSelectors", {"TrailName": p.get("TrailName"), "AdvancedEventSelectors": p.get("AdvancedEventSelectors")})
    if action in ("GetEventSelectors", "GetAdvancedEventSelectors"):
        t = _find_trail(st, p.get("TrailName"))
        out = {"TrailARN": t["TrailARN"]}
        if t["_advanced"]:
            out["AdvancedEventSelectors"] = t["_advanced"]
        else:
            out["EventSelectors"] = t["_eventSelectors"] or [{"ReadWriteType": "All", "IncludeManagementEvents": True, "DataResources": [], "ExcludeManagementEventSources": []}]
        if action == "GetAdvancedEventSelectors":
            out.pop("EventSelectors", None)
            out.setdefault("AdvancedEventSelectors", [])
        return out
    if action == "AddTags":
        t = _find_trail(st, p.get("ResourceId"))
        have = {x["Key"]: x for x in t["_tags"]}
        for x in p.get("TagsList") or []:
            have[x["Key"]] = x
        t["_tags"] = list(have.values())
        return {}
    if action == "ListTags":
        out = []
        for rid in p.get("ResourceIdList") or []:
            t = _find_trail(st, rid)
            out.append({"ResourceId": t["TrailARN"], "TagsList": t["_tags"]})
        return {"ResourceTagList": out}
    raise _CtErr("UnknownOperationException", f"The action {action} is not implemented by Vyomi's minimal CloudTrail.", 400)


def cloudtrail_dispatch(store, target: str, body: bytes):
    m = _m()
    action = (target or "").rsplit(".", 1)[-1]
    try:
        payload = json.loads(body or b"{}")
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}
    try:
        out = _ct_op(store, action, payload)
        status = 200
    except _CtErr as e:
        out, status = {"__type": e.code, "Message": e.message}, e.status
    if status == 200:
        store.persist()
    return m.S3Response(status=status, headers=m._amz_headers(), body=json.dumps(out).encode(), media_type="application/x-amz-json-1.1")


# ── data-event recording ─────────────────────────────────────────────────────────────
_READONLY_OPS = {"GetObject", "HeadObject", "GetObjectAcl", "GetObjectTagging", "ListParts"}
_SKIP_SUBS = ("acl", "tagging", "retention", "legal-hold", "attributes", "torrent", "select", "restore", "versions")


def _classify(method: str, key: str, query: dict, lheaders: dict):
    """Object-level data-event name for one request, else None. Bucket-level reads (ListObjects) are not data events."""
    if not key:
        if method == "POST" and "delete" in query:
            return "DeleteObjects"
        return None
    q = query or {}
    if method == "GET":
        if "tagging" in q:
            return "GetObjectTagging"
        if "acl" in q:
            return "GetObjectAcl"
        if "uploadId" in q:
            return "ListParts"
        return "GetObject" if not any(k in q for k in ("attributes", "retention", "legal-hold", "torrent")) else None
    if method == "HEAD":
        return "HeadObject"
    if method == "PUT":
        if "tagging" in q:
            return "PutObjectTagging"
        if "acl" in q:
            return "PutObjectAcl"
        if "partNumber" in q and "uploadId" in q:
            return "UploadPartCopy" if lheaders.get("x-amz-copy-source") else "UploadPart"
        if any(k in q for k in ("retention", "legal-hold")):
            return None
        return "CopyObject" if lheaders.get("x-amz-copy-source") else "PutObject"
    if method == "DELETE":
        if "uploadId" in q:
            return "AbortMultipartUpload"
        if "tagging" in q:
            return "DeleteObjectTagging"
        return "DeleteObject"
    if method == "POST":
        if "uploads" in q:
            return "CreateMultipartUpload"
        if "uploadId" in q:
            return "CompleteMultipartUpload"
        if "restore" in q:
            return "RestoreObject"
    return None


def _match_basic(sels, bucket, key, ro) -> bool:
    for s in sels:
        rw = s.get("ReadWriteType", "All")
        if (rw == "ReadOnly" and not ro) or (rw == "WriteOnly" and ro):
            continue
        for d in s.get("DataResources") or []:
            if d.get("Type") != "AWS::S3::Object":
                continue
            for v in d.get("Values") or []:
                if v in ("arn:aws:s3", "arn:aws:s3:::"):
                    return True
                if v.startswith("arn:aws:s3:::") and f"arn:aws:s3:::{bucket}/{key}".startswith(v):
                    return True
    return False


def _field_ok(f, val: str) -> bool:
    if "Equals" in f and val not in f["Equals"]:
        return False
    if "NotEquals" in f and val in f["NotEquals"]:
        return False
    if "StartsWith" in f and not any(val.startswith(x) for x in f["StartsWith"]):
        return False
    if "NotStartsWith" in f and any(val.startswith(x) for x in f["NotStartsWith"]):
        return False
    if "EndsWith" in f and not any(val.endswith(x) for x in f["EndsWith"]):
        return False
    if "NotEndsWith" in f and any(val.endswith(x) for x in f["NotEndsWith"]):
        return False
    return True


def _match_advanced(sels, bucket, key, op, ro) -> bool:
    arn = f"arn:aws:s3:::{bucket}/{key}"
    for s in sels:
        ok = True
        for f in s.get("FieldSelectors") or []:
            fld = f.get("Field")
            val = {"eventCategory": "Data", "resources.type": "AWS::S3::Object", "eventName": op, "readOnly": "true" if ro else "false",
                   "resources.ARN": arn}.get(fld)
            if val is None:
                continue
            if not _field_ok(f, val):
                ok = False
                break
        if ok:
            return True
    return False


def _matching_trails(st, bucket, key, op, ro):
    out = []
    for t in st["trails"].values():
        if not t["_logging"]:
            continue
        if t["_advanced"]:
            hit = _match_advanced(t["_advanced"], bucket, key, op, ro)
        else:
            hit = _match_basic(t["_eventSelectors"], bucket, key, ro)
        if hit:
            out.append(t["Name"])
    return out


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def on_request(store, method: str, raw: str, query: dict, lheaders: dict, body: bytes, resp) -> None:
    """After every served S3 request: request counters (Storage Lens) + CloudTrail data events. Best-effort."""
    try:
        raw = (raw or "").lstrip("/")
        bucket, _, key = raw.partition("/")
        bucket = urllib.parse.unquote(bucket)
        if not bucket or bucket in ("v20180820", "__s3tables__", "__cloudtrail__", "__s3_website__") or bucket not in store.buckets:
            return
        key = urllib.parse.unquote(key)
        st = _state(store)
        status = int(getattr(resp, "status", 200) or 200)
        q = query or {}
        # ── request counters (real served requests; the console's own calls count too) ──
        r = st["reqs"].setdefault(bucket, {}).setdefault(_day(), {})
        kind = "AllRequests"
        r[kind] = r.get(kind, 0) + 1
        if key:
            cat = {"GET": "GetRequests", "HEAD": "HeadRequests", "PUT": "PutRequests", "POST": "PostRequests", "DELETE": "DeleteRequests"}.get(method)
        else:
            cat = "ListRequests" if method == "GET" and not any(k in q for k in ("acl", "policy", "versioning", "location", "tagging", "cors", "lifecycle", "encryption", "logging", "website", "notification", "replication", "accelerate", "requestPayment", "object-lock", "ownershipControls", "publicAccessBlock", "metrics", "inventory", "intelligent-tiering", "metadataConfiguration", "metadataTable", "uploads")) else ("PostRequests" if method == "POST" else None)
        if cat:
            r[cat] = r.get(cat, 0) + 1
        if 200 <= status < 300:
            if method == "GET" and key:
                r["BytesDownloaded"] = r.get("BytesDownloaded", 0) + len(getattr(resp, "body", b"") or b"")
            elif method == "PUT" and key:
                r["BytesUploaded"] = r.get("BytesUploaded", 0) + len(body or b"")
        if 400 <= status < 500:
            r["4xxErrors"] = r.get("4xxErrors", 0) + 1
        elif status >= 500:
            r["5xxErrors"] = r.get("5xxErrors", 0) + 1
        days = st["reqs"][bucket]
        if len(days) > _DAYS_KEEP:
            for d in sorted(days)[:len(days) - _DAYS_KEEP]:
                del days[d]
        # ── CloudTrail data events ──
        if not st["trails"]:
            return
        op = _classify(method, key, q, lheaders)
        if not op:
            return
        ro = op in _READONLY_OPS
        trails = _matching_trails(st, bucket, key, op, ro)
        if not trails:
            return
        ua = lheaders.get("user-agent", "")
        ev = {"eventVersion": "1.10", "userIdentity": {"type": "IAMUser", "accountId": _ACCOUNT, "userName": "simulator"},
              "eventTime": _now(), "eventSource": "s3.amazonaws.com", "eventName": op, "awsRegion": (store.buckets[bucket].get("region") or _REGION),
              "sourceIPAddress": "127.0.0.1", "userAgent": ua,
              "requestParameters": {"bucketName": bucket, **({"key": key} if key else {}), "Host": f"{bucket}.s3.{_REGION}.amazonaws.com"},
              "responseElements": None, "requestID": uuid.uuid4().hex[:16].upper(), "eventID": str(uuid.uuid4()), "readOnly": ro,
              "resources": ([{"type": "AWS::S3::Object", "ARN": f"arn:aws:s3:::{bucket}/{key}"}] if key else []) + [{"accountId": _ACCOUNT, "type": "AWS::S3::Bucket", "ARN": f"arn:aws:s3:::{bucket}"}],
              "eventType": "AwsApiCall", "managementEvent": False, "recipientAccountId": _ACCOUNT, "eventCategory": "Data",
              "vyomi": {"trails": trails, "httpStatus": status}}
        if status >= 400:
            ev["errorCode"] = {404: "NoSuchKey", 403: "AccessDenied", 412: "PreconditionFailed"}.get(status, "ClientError" if status < 500 else "InternalError")
        st["events"].append(ev)
        if len(st["events"]) > _EVENT_CAP:
            del st["events"][:len(st["events"]) - _EVENT_CAP]
    except Exception:
        pass


def trail_view(store, bucket: str, query: dict):
    if bucket not in store.buckets:
        return _jerr("NoSuchBucket", "The specified bucket does not exist.", 404)
    st = _state(store)
    probe = f"arn:aws:s3:::{bucket}/"
    trails = []
    for t in st["trails"].values():
        covers = False
        if t["_advanced"]:
            covers = _match_advanced(t["_advanced"], bucket, "x", "GetObject", True) or _match_advanced(t["_advanced"], bucket, "x", "PutObject", False)
        else:
            covers = _match_basic(t["_eventSelectors"], bucket, "x", True) or _match_basic(t["_eventSelectors"], bucket, "x", False)
        if covers:
            rw = "All"
            if not t["_advanced"]:
                rws = {s.get("ReadWriteType", "All") for s in t["_eventSelectors"]}
                rw = "All" if "All" in rws or len(rws) > 1 else next(iter(rws), "All")
            trails.append({"name": t["Name"], "arn": t["TrailARN"], "logging": t["_logging"], "s3Bucket": t["S3BucketName"], "readWriteType": rw,
                           "advanced": bool(t["_advanced"])})
    q = query or {}
    try:
        limit = max(1, min(int(q.get("limit") or 100), 500))
    except ValueError:
        limit = 100
    evs = [e for e in reversed(st["events"]) if e["requestParameters"].get("bucketName") == bucket]
    if q.get("eventName"):
        evs = [e for e in evs if e["eventName"] == q["eventName"]]
    return _jresp(200, {"bucket": bucket, "trails": trails, "total": len(evs), "events": evs[:limit], "probe": probe})


# ═══ Bucket-level Storage Lens ═══════════════════════════════════════════════════════
def lens_view(store, bucket: str, query: dict):
    m = _m()
    if bucket not in store.buckets:
        return _jerr("NoSuchBucket", "The specified bucket does not exist.", 404)
    cur_b = cur_o = non_b = non_o = dm = 0
    by_class: dict = {}
    by_prefix: dict = {}
    for key, entry in store.bucket_objects(bucket).items():
        vs = entry.get("versions") or [] if isinstance(entry, dict) else []
        for idx, v in enumerate(vs):
            if v.get("is_delete_marker"):
                dm += 1
                continue
            size = int(v.get("size") or 0)
            if idx == 0:
                cur_b += size
                cur_o += 1
                p = (key.split("/", 1)[0] + "/") if "/" in key else "(root)"
                e = by_prefix.setdefault(p, {"prefix": p, "bytes": 0, "objects": 0})
                e["bytes"] += size
                e["objects"] += 1
            else:
                non_b += size
                non_o += 1
            sc = v.get("storage_class") or "STANDARD"
            c = by_class.setdefault(sc, {"storageClass": sc, "bytes": 0, "objects": 0})
            c["bytes"] += size
            c["objects"] += 1
    mpu_b = mpu_n = 0
    for up in m._mpu(store).values():
        if up.get("bucket") == bucket:
            mpu_n += 1
            mpu_b += sum(len(p.get("data") or b"") for p in (up.get("parts") or {}).values())
    total = cur_b + non_b
    days = _state(store)["reqs"].get(bucket, {})
    keys = ("AllRequests", "GetRequests", "PutRequests", "HeadRequests", "DeleteRequests", "ListRequests", "PostRequests",
            "BytesDownloaded", "BytesUploaded", "4xxErrors", "5xxErrors")
    tot = {k: sum(d.get(k, 0) for d in days.values()) for k in keys}
    series = [{"date": d, **{k: days[d].get(k, 0) for k in keys}} for d in sorted(days)]
    allr = tot["AllRequests"]
    return _jresp(200, {
        "bucket": bucket, "region": store.buckets[bucket].get("region") or _REGION, "generated": _now(),
        "storage": {"totalBytes": total, "currentBytes": cur_b, "currentObjects": cur_o, "noncurrentBytes": non_b, "noncurrentObjects": non_o,
                    "deleteMarkers": dm, "incompleteMpuBytes": mpu_b, "incompleteMpuUploads": mpu_n,
                    "currentVersionPct": round(100.0 * cur_b / total, 2) if total else 100.0,
                    "avgObjectBytes": round(cur_b / cur_o) if cur_o else 0},
        "byStorageClass": sorted(by_class.values(), key=lambda x: -x["bytes"]),
        "topPrefixes": sorted(by_prefix.values(), key=lambda x: -x["bytes"])[:10],
        "activity": {**tot, "errorRatePct4xx": round(100.0 * tot["4xxErrors"] / allr, 2) if allr else 0.0,
                     "errorRatePct5xx": round(100.0 * tot["5xxErrors"] / allr, 2) if allr else 0.0,
                     "retentionDays": _DAYS_KEEP, "daily": series}})


# ═══ Vyomi-internal routes: /v20180820/_vyomi/<bucket-metadata|bucket-trail|bucket-lens>/{bucket} ═══
def vyomi_route(store, method: str, rest: list, query: dict):
    if len(rest) != 2 or method != "GET":
        return None
    name, bucket = rest[0], urllib.parse.unquote(rest[1])
    fn = {"bucket-metadata": metadata_view, "bucket-trail": trail_view, "bucket-lens": lens_view}.get(name)
    if fn is None:
        return None
    return fn(store, bucket, query)
