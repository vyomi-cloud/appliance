"""Cloud Storage Insights inventory reports + Anywhere (Rapid) Cache — substrate-independent (no fastapi / boto3).

Used by core/gcp_storage_core.py (state lives on the GCS ObjectStore as `_gcs_si`):
  * storageinsights.googleapis.com/v1  projects/{p}/locations/{l}/reportConfigs[/{id}]  and  .../reportDetails[/{id}]
      - config validation (frequency, start/end dates, CSV options, metadataFields, source/destination buckets,
        location must match the source bucket's location, parquet not available)
      - report generation: a REAL CSV of the source bucket's objects (+ a *_manifest.json) is written into the
        destination bucket of the same simulator. Generation is lazy: due reports are produced whenever the
        config / its details are read, plus an explicit :runNow (Vyomi extension — the real service just schedules).
  * storage/v1  b/{bucket}/anywhereCaches[/{zone}[:pause|:resume|:disable]]
      - zone must belong to the bucket's location, one cache per zone, ttl 1h..7d, admission policy,
        creating -> running state machine (time based), pause/resume/disable, update (PATCH)
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import datetime

REPORT_FIELDS = ["project", "bucket", "name", "location", "size", "timeCreated", "timeDeleted", "updated", "storageClass",
                 "etag", "retentionExpirationTime", "crc32c", "md5Hash", "generation", "metageneration", "contentType",
                 "contentEncoding", "contentDisposition", "contentLanguage", "cacheControl", "customTime", "componentCount",
                 "kmsKeyName", "eventBasedHold", "temporaryHold", "objectRetention", "metadata"]
REQUIRED_FIELDS = ("project", "bucket", "name")
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")
CACHE_CREATE_SECONDS = 8   # a cache is 'creating' this long before it is 'running'
_ZONE = re.compile(r"^([a-z]+-[a-z]+[0-9]+)-[a-z]$")


class SiError(Exception):
    def __init__(self, status, gstatus, message):
        super().__init__(message)
        self.status, self.gstatus, self.message = status, gstatus, message


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _state(store):
    s = getattr(store, "_gcs_si", None)
    if s is None:
        s = {"configs": {}, "details": {}, "caches": {}}
        store._gcs_si = s
    return s


def _date(d):
    try:
        return datetime.date(int(d["year"]), int(d["month"]), int(d["day"]))
    except Exception:
        raise SiError(400, "INVALID_ARGUMENT", "frequencyOptions dates must be {year, month, day}.")


def _loc(store, bucket):
    return (store.buckets.get(bucket, {}).get("location") or "US").lower()


# ── report configs ───────────────────────────────────────────────────────────
def _validate_config(store, body, location, project):
    if not isinstance(body, dict):
        raise SiError(400, "INVALID_ARGUMENT", "Request body must be a ReportConfig.")
    if len(str(body.get("displayName") or "")) > 256:
        raise SiError(400, "INVALID_ARGUMENT", "displayName must be at most 256 characters.")
    fo = body.get("frequencyOptions") or {}
    if fo.get("frequency") not in ("DAILY", "WEEKLY"):
        raise SiError(400, "INVALID_ARGUMENT", "frequencyOptions.frequency must be DAILY or WEEKLY.")
    start, end = _date(fo.get("startDate") or {}), _date(fo.get("endDate") or {})
    if end < start:
        raise SiError(400, "INVALID_ARGUMENT", "frequencyOptions.endDate must not be before startDate.")
    if (end - start).days > 366 * 2:
        raise SiError(400, "INVALID_ARGUMENT", "A report config can run for at most two years.")
    if body.get("parquetOptions") is not None:
        raise SiError(400, "INVALID_ARGUMENT", "parquetOptions are not available in this Vyomi build (no Parquet encoder in the simulator); use csvOptions.")
    csv_o = body.get("csvOptions")
    if csv_o is None:
        raise SiError(400, "INVALID_ARGUMENT", "Exactly one of csvOptions or parquetOptions must be set.")
    delim = csv_o.get("delimiter", ",")
    if len(delim) != 1:
        raise SiError(400, "INVALID_ARGUMENT", "csvOptions.delimiter must be a single character.")
    om = body.get("objectMetadataReportOptions")
    if not isinstance(om, dict):
        raise SiError(400, "INVALID_ARGUMENT", "objectMetadataReportOptions is required.")
    fields = om.get("metadataFields") or []
    bad = [f for f in fields if f not in REPORT_FIELDS]
    if bad:
        raise SiError(400, "INVALID_ARGUMENT", "Unknown metadataFields: %s." % ", ".join(bad))
    if not fields:
        raise SiError(400, "INVALID_ARGUMENT", "metadataFields must not be empty.")
    miss = [f for f in REQUIRED_FIELDS if f not in fields]
    if miss:
        raise SiError(400, "INVALID_ARGUMENT", "metadataFields must include: %s." % ", ".join(REQUIRED_FIELDS))
    src = ((om.get("storageFilters") or {}).get("bucket")) or ""
    dest = ((om.get("storageDestinationOptions") or {}).get("bucket")) or ""
    if not src or not store.bucket_exists(src):
        raise SiError(404, "NOT_FOUND", "Source bucket '%s' does not exist." % src)
    if not dest or not store.bucket_exists(dest):
        raise SiError(404, "NOT_FOUND", "Destination bucket '%s' does not exist." % dest)
    if _loc(store, src) != location.lower():
        raise SiError(400, "FAILED_PRECONDITION", "The report config's location '%s' must match the source bucket's location '%s'." % (location, _loc(store, src)))
    path = (om.get("storageDestinationOptions") or {}).get("destinationPath") or ""
    if path.startswith("/") or ".." in path.split("/"):
        raise SiError(400, "INVALID_ARGUMENT", "destinationPath must be a relative object path prefix.")


def _view(cfg):
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


def _cfg_name(project, location, cid):
    return "projects/%s/locations/%s/reportConfigs/%s" % (project, location, cid)


def create_config(store, project, location, query, body):
    cid = str(query.get("reportConfigId") or "").strip() or ("rc-" + str(int(time.time() * 1000))[-9:])
    if not _ID.match(cid):
        raise SiError(400, "INVALID_ARGUMENT", "reportConfigId is invalid.")
    _validate_config(store, body, location, project)
    name = _cfg_name(project, location, cid)
    cfgs = _state(store)["configs"]
    if name in cfgs:
        raise SiError(409, "ALREADY_EXISTS", "ReportConfig %s already exists." % name)
    cfg = dict(body)
    cfg.update(name=name, createTime=_now(), updateTime=_now(), _lastRun="")
    cfgs[name] = cfg
    _sweep(store, only=name)
    store.persist()
    return _view(cfgs[name])


def list_configs(store, project, location, query):
    _sweep(store)
    flt = str(query.get("filter") or "")
    out = []
    for n, c in sorted(_state(store)["configs"].items()):
        if not n.startswith("projects/%s/locations/%s/" % (project, location)):
            continue
        if flt.startswith("objectMetadataReportOptions.storageFilters.bucket="):
            if c["objectMetadataReportOptions"]["storageFilters"]["bucket"] != flt.split("=", 1)[1].strip('"\''):
                continue
        out.append(_view(c))
    return {"reportConfigs": out}


def get_config(store, name):
    c = _state(store)["configs"].get(name)
    if c is None:
        raise SiError(404, "NOT_FOUND", "ReportConfig %s not found." % name)
    return c


def patch_config(store, name, query, body):
    c = get_config(store, name)
    mask = [m for m in str(query.get("updateMask") or "").split(",") if m]
    if not mask:
        raise SiError(400, "INVALID_ARGUMENT", "updateMask is required.")
    merged = dict(c)
    for m in mask:
        k = m.split(".")[0]
        if k not in ("displayName", "frequencyOptions", "csvOptions", "objectMetadataReportOptions"):
            raise SiError(400, "INVALID_ARGUMENT", "Field '%s' cannot be updated." % m)
        if k in body:
            merged[k] = body[k]
    loc = name.split("/")[3]
    _validate_config(store, merged, loc, name.split("/")[1])
    for k in {m.split(".")[0] for m in mask}:
        c[k] = merged[k]
    c["updateTime"] = _now()
    store.persist()
    return _view(c)


def delete_config(store, name, query):
    get_config(store, name)
    st = _state(store)
    has = [d for d in st["details"].values() if d["_config"] == name]
    if has and str(query.get("force", "")).lower() != "true":
        raise SiError(400, "FAILED_PRECONDITION", "ReportConfig has %d report detail(s); pass force=true to delete them too." % len(has))
    for k in [k for k, d in st["details"].items() if d["_config"] == name]:
        del st["details"][k]
    del st["configs"][name]
    store.persist()
    return {}


# ── report generation ────────────────────────────────────────────────────────
def _field_value(store, project, bucket, name, e, f):
    if f == "project":
        return project
    if f == "bucket":
        return bucket
    if f == "name":
        return name
    if f == "location":
        return _loc(store, bucket).upper()
    if f == "size":
        return e.get("size", 0)
    if f == "metadata":
        return json.dumps(e.get("metadata") or {}, sort_keys=True) if e.get("metadata") else ""
    v = e.get(f, "")
    return "" if v is None else v


def _generate(store, cfg, snapshot):
    from core import gcp_storage_core as gs   # lazy: gcs entry builder
    name = cfg["name"]
    _, project, _, location, _, cid = name.split("/")
    om = cfg["objectMetadataReportOptions"]
    src, dopt = om["storageFilters"]["bucket"], om["storageDestinationOptions"]
    dest, path = dopt["bucket"], (dopt.get("destinationPath") or "").strip("/")
    if not store.bucket_exists(src) or not store.bucket_exists(dest):
        return _record(store, cfg, snapshot, None, 0, 9, "Source or destination bucket no longer exists.")
    fields = om["metadataFields"]
    co = cfg["csvOptions"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=co.get("delimiter", ","), lineterminator=co.get("recordSeparator", "\n").replace("\\n", "\n") or "\n")
    if co.get("headerRequired"):
        w.writerow(fields)
    rows = 0
    for oname, e in sorted(store.bucket_objects(src).items()):
        if oname.endswith("/"):
            continue
        w.writerow([_field_value(store, project, src, oname, e, f) for f in fields])
        rows += 1
    stamp = snapshot.strftime("%Y-%m-%dT%H:%M:%S")
    prefix = (path + "/" if path else "") + stamp + "_" + cid
    objs = store.bucket_objects(dest)
    data = buf.getvalue().encode()
    key = prefix + "_0.csv"
    objs[key] = gs._new_entry(objs, key, data, "text/csv", {})
    store.mirror_put(dest, key, data, "text/csv", {})
    manifest = json.dumps({"snapshotTime": snapshot.strftime("%Y-%m-%dT%H:%M:%SZ"), "reportConfig": name, "sourceBucket": src,
                           "shardsCount": 1, "rowCount": rows, "files": [key]}).encode()
    mkey = prefix + "_manifest.json"
    objs[mkey] = gs._new_entry(objs, mkey, manifest, "application/json", {})
    store.mirror_put(dest, mkey, manifest, "application/json", {})
    return _record(store, cfg, snapshot, "gs://%s/%s" % (dest, prefix), rows, 0, "")


def _record(store, cfg, snapshot, prefix, rows, code, err):
    st = _state(store)
    n = 1 + sum(1 for d in st["details"].values() if d["_config"] == cfg["name"])
    did = "%s-%d" % (snapshot.strftime("%Y%m%dT%H%M%S"), n)
    name = "%s/reportDetails/%s" % (cfg["name"], did)
    d = {"name": name, "snapshotTime": snapshot.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": {"code": code, **({"message": err} if err else {})},
         "reportPathPrefix": prefix or "", "shardsCount": 1 if prefix else 0, "rowCount": str(rows), "_config": cfg["name"]}
    if err:
        d["processingErrorsCount"] = "1"
    st["details"][name] = d
    return d


def _due_snapshots(cfg, today):
    fo = cfg["frequencyOptions"]
    start, end = _date(fo["startDate"]), _date(fo["endDate"])
    step = 1 if fo["frequency"] == "DAILY" else 7
    last = cfg.get("_lastRun") or ""
    out, d = [], start
    while d <= min(end, today):
        if d.isoformat() > last:
            out.append(d)
        d += datetime.timedelta(days=step)
    return out[-1:]   # only the most recent missed slot (the service does not backfill history)


def _sweep(store, only=None):
    today = datetime.datetime.now(datetime.timezone.utc)
    for name, cfg in list(_state(store)["configs"].items()):
        if only and name != only:
            continue
        for day in _due_snapshots(cfg, today.date()):
            snap = datetime.datetime.combine(day, datetime.time(0, 0), tzinfo=datetime.timezone.utc) if day < today.date() else today.replace(microsecond=0)
            _generate(store, cfg, snap)
            cfg["_lastRun"] = day.isoformat()


def run_now(store, name):
    cfg = get_config(store, name)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    fo = cfg["frequencyOptions"]
    if now.date() < _date(fo["startDate"]) or now.date() > _date(fo["endDate"]):
        raise SiError(400, "FAILED_PRECONDITION", "Today is outside the report config's start/end date window.")
    d = _generate(store, cfg, now)
    store.persist()
    return {k: v for k, v in d.items() if not k.startswith("_")}


def list_details(store, config_name, query):
    get_config(store, config_name)
    _sweep(store, only=config_name)
    items = [{k: v for k, v in d.items() if not k.startswith("_")} for d in _state(store)["details"].values() if d["_config"] == config_name]
    return {"reportDetails": sorted(items, key=lambda d: d["snapshotTime"], reverse=True)}


def get_detail(store, name):
    d = _state(store)["details"].get(name)
    if d is None:
        raise SiError(404, "NOT_FOUND", "ReportDetail %s not found." % name)
    return {k: v for k, v in d.items() if not k.startswith("_")}


def dispatch_insights(store, method, segs, query, body):
    """segs: ['projects',P,'locations',L,'reportConfigs'|'reportDetails', ...]. Returns (status, obj)."""
    project, location = segs[1], segs[3]
    kind = segs[4].split(":")[0]
    rest = segs[5:]
    try:
        if kind == "reportConfigs":
            if not rest:
                if method == "POST":
                    return 200, create_config(store, project, location, query, body)
                if method == "GET":
                    return 200, list_configs(store, project, location, query)
            else:
                cid, _, verb = rest[0].partition(":")
                name = _cfg_name(project, location, cid)
                if len(rest) == 1 and not verb:
                    if method == "GET":
                        _sweep(store, only=name)
                        return 200, _view(get_config(store, name))
                    if method == "PATCH":
                        return 200, patch_config(store, name, query, body)
                    if method == "DELETE":
                        return 200, delete_config(store, name, query)
                if len(rest) == 1 and verb == "runNow" and method == "POST":
                    return 200, run_now(store, name)
        if kind == "reportConfigs" and len(rest) >= 2 and rest[1] == "reportDetails" and method == "GET":
            name = _cfg_name(project, location, rest[0])
            if len(rest) == 2:
                return 200, list_details(store, name, query)
            return 200, get_detail(store, "%s/reportDetails/%s" % (name, rest[2]))
        if kind == "reportDetails":
            return 400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "reportDetails are addressed under their reportConfig: .../reportConfigs/{id}/reportDetails."}}
    except SiError as e:
        return e.status, {"error": {"code": e.status, "message": e.message, "status": e.gstatus}}
    return 404, {"error": {"code": 404, "message": "Unknown storageinsights path.", "status": "NOT_FOUND"}}


# ── Anywhere Cache ───────────────────────────────────────────────────────────
def _cache_state(c):
    if c["_state"] == "creating" and time.time() - c["_t"] >= CACHE_CREATE_SECONDS:
        c["_state"] = "running"
    return c["_state"]


def _cache_view(bucket, c):
    return {"kind": "storage#anywhereCache", "id": "%s/%s" % (bucket, c["zone"]), "selfLink": "https://www.googleapis.com/storage/v1/b/%s/anywhereCaches/%s" % (bucket, c["zone"]),
            "bucket": bucket, "zone": c["zone"], "state": _cache_state(c), "ttl": c["ttl"], "admissionPolicy": c["admissionPolicy"],
            "createTime": c["createTime"], "updateTime": c["updateTime"], "pendingUpdate": c.get("pendingUpdate", False)}


def _zone_ok(store, bucket, zone):
    m = _ZONE.match(zone or "")
    if not m:
        return False
    region = m.group(1)
    loc = _loc(store, bucket)
    if loc in ("us", "eu", "asia"):
        return region.startswith({"us": "us-", "eu": "europe-", "asia": "asia-"}[loc])
    return region == loc    # regional bucket; (dual-region buckets match either leg by name below)


def _ttl_secs(ttl):
    m = re.match(r"^(\d+)s$", str(ttl or ""))
    if not m:
        raise SiError(400, "INVALID_ARGUMENT", "ttl must be a duration in seconds such as \"86400s\".")
    s = int(m.group(1))
    if not 3600 <= s <= 604800:
        raise SiError(400, "INVALID_ARGUMENT", "ttl must be between 1 hour (3600s) and 7 days (604800s).")
    return s


def dispatch_caches(store, method, bucket, rest, body):
    """rest: segments after 'anywhereCaches'. Returns (status, obj)."""
    try:
        if not store.bucket_exists(bucket):
            raise SiError(404, "NOT_FOUND", "The specified bucket does not exist.")
        caches = _state(store)["caches"].setdefault(bucket, {})
        if not rest:
            if method == "GET":
                return 200, {"kind": "storage#anywhereCaches", "items": [_cache_view(bucket, c) for _, c in sorted(caches.items())]}
            if method == "POST":
                zone = str(body.get("zone") or "")
                if not _zone_ok(store, bucket, zone):
                    raise SiError(400, "INVALID_ARGUMENT", "Zone '%s' is not valid for a bucket in location %s." % (zone, _loc(store, bucket).upper()))
                if zone in caches and caches[zone]["_state"] != "disabled":
                    raise SiError(409, "ALREADY_EXISTS", "An Anywhere Cache already exists in zone %s for this bucket." % zone)
                pol = body.get("admissionPolicy") or "admit-on-first-miss"
                if pol not in ("admit-on-first-miss", "admit-on-second-miss"):
                    raise SiError(400, "INVALID_ARGUMENT", "admissionPolicy must be admit-on-first-miss or admit-on-second-miss.")
                ttl = body.get("ttl") or "86400s"
                _ttl_secs(ttl)
                caches[zone] = {"zone": zone, "ttl": ttl, "admissionPolicy": pol, "_state": "creating", "_t": time.time(), "createTime": _now(), "updateTime": _now()}
                store.persist()
                return 200, _op("insert", bucket, zone, caches[zone])
            raise SiError(400, "INVALID_ARGUMENT", "Unsupported method on anywhereCaches.")
        zone, _, verb = rest[0].partition(":")
        if len(rest) == 2:
            verb = rest[1]
        c = caches.get(zone)
        if c is None:
            raise SiError(404, "NOT_FOUND", "Anywhere Cache %s/%s not found." % (bucket, zone))
        st = _cache_state(c)
        if not verb:
            if method == "GET":
                return 200, _cache_view(bucket, c)
            if method == "PATCH":
                if st in ("disabled",):
                    raise SiError(400, "FAILED_PRECONDITION", "A disabled cache cannot be updated.")
                if "ttl" in body:
                    _ttl_secs(body["ttl"])
                    c["ttl"] = body["ttl"]
                if "admissionPolicy" in body:
                    if body["admissionPolicy"] not in ("admit-on-first-miss", "admit-on-second-miss"):
                        raise SiError(400, "INVALID_ARGUMENT", "admissionPolicy must be admit-on-first-miss or admit-on-second-miss.")
                    c["admissionPolicy"] = body["admissionPolicy"]
                c["updateTime"] = _now()
                store.persist()
                return 200, _op("update", bucket, zone, c)
            raise SiError(400, "INVALID_ARGUMENT", "Unsupported method on an Anywhere Cache.")
        if method != "POST":
            raise SiError(400, "INVALID_ARGUMENT", "%s is a POST." % verb)
        table = {"pause": ("running", "paused"), "resume": ("paused", "running"), "disable": (("running", "paused", "creating"), "disabled")}
        if verb not in table:
            raise SiError(404, "NOT_FOUND", "Unknown action '%s'." % verb)
        frm, to = table[verb]
        frm = (frm,) if isinstance(frm, str) else frm
        if st not in frm:
            raise SiError(400, "FAILED_PRECONDITION", "Cannot %s an Anywhere Cache in state '%s'." % (verb, st))
        c["_state"], c["updateTime"] = to, _now()
        store.persist()
        return 200, _cache_view(bucket, c)
    except SiError as e:
        return e.status, {"error": {"code": e.status, "message": e.message, "status": e.gstatus}}


def _op(kind, bucket, zone, c):
    return {"name": "projects/_/buckets/%s/operations/anywhereCache-%s-%s" % (bucket, kind, zone), "done": True,
            "metadata": {"@type": "type.googleapis.com/google.storage.control.v2.CreateAnywhereCacheMetadata"},
            "response": {"@type": "type.googleapis.com/google.storage.control.v2.AnywhereCache", **{k: v for k, v in _cache_view(bucket, c).items() if k not in ("kind", "selfLink", "id")}}}


def delete_bucket_state(store, bucket):
    _state(store)["caches"].pop(bucket, None)
