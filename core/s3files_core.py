"""Amazon S3 Files (service `s3files`, rest-json) and FSx for OpenZFS with S3 access points (service `fsx`, JSON 1.1) —
substrate-independent, one core because both are "a file system whose data is also reachable as objects".

S3 Files (bucket-backed file systems):
  POST /file-systems {bucket(ARN), prefix, roleArn, tags, clientToken}  -> fileSystemId fs-*, one file system per bucket+prefix
  GET /file-systems[/{id}]  DELETE /file-systems/{id} (refused while mount targets / access points exist)
  POST|GET /file-systems/{id}/mount-targets  DELETE /mount-targets/{id}   (subnet + security groups checked against the EC2 model,
                                                                            one mount target per Availability Zone, IP from the subnet CIDR)
  POST|GET /file-systems/{id}/access-points  DELETE /access-points/{id}    (POSIX user + root directory)
  PUT|GET|DELETE /file-systems/{id}/policy   PUT|GET /file-systems/{id}/synchronization-configuration
  Vyomi data plane (there is no NFS server): GET /file-systems/{id}/files?path=  PUT|GET|DELETE /file-systems/{id}/file?path=
  POST /file-systems/{id}/directories — the files ARE the bucket's objects under the file system prefix, so anything written
  through the S3 API shows up as a file and vice versa.

FSx for OpenZFS + S3 access points (AmazonFSx.* targets): CreateFileSystem / DescribeFileSystems / DeleteFileSystem (root volume
created with it), CreateVolume / DescribeVolumes / DeleteVolume, CreateAndAttachS3AccessPoint / DescribeS3AccessPointAttachments /
DetachAndDeleteS3AccessPoint, and VyomiPutVolumeFile / VyomiListVolumeFiles (stand-in for writing over NFS/SMB). The attachment's
`...-ext-s3alias` alias is a bucket name the S3 API serves (ListObjectsV2, Get/Head/Put/DeleteObject) straight from the volume's files.

State: s3_store.account["s3files"] and ["fsx"]. Pure Python, Pyodide-loadable.

Honest limits: no NFS/SMB protocol, no POSIX permission / ownership / locking semantics (the POSIX identity is stored, not
enforced), no real throughput or capacity limits, no import/expiration sync engine (the rules are stored and validated), and
FSx has no real ZFS (snapshots, dedup, compression) — files are plain stored bytes.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _esc

_ACCOUNT = "123456789012"
_REGION = "us-east-1"


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:                       # Pyodide flat layout
        import s3_object_core as m            # type: ignore
    return m


def _vpcc():
    try:
        from core import vpc_core as m
    except ImportError:
        import vpc_core as m                  # type: ignore
    return m


def _ts() -> float:
    return round(datetime.now(timezone.utc).timestamp(), 3)


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _rid(prefix, n=17):
    return f"{prefix}-{uuid.uuid4().hex[:n]}"


class _Err(Exception):
    def __init__(self, code, message, status):
        self.code, self.message, self.status = code, message, status


def _json_resp(status, doc):
    m = _s3c()
    body = b"" if doc is None else json.dumps(doc).encode()
    return m.S3Response(status=status, headers=m._amz_headers(), body=body, media_type="application/json")


def _json_err(e):
    r = _json_resp(e.status, {"message": e.message, "Message": e.message, "__type": e.code})
    r.headers["x-amzn-ErrorType"] = e.code
    return r


def _arn_ok_role(arn):
    return bool(re.fullmatch(r"arn:aws[-a-z0-9]*:iam::\d{12}:role/[\w+=,.@/-]{1,512}", arn or ""))


# ═════════════════════════════════════ S3 Files ═════════════════════════════════════
def _fs_state(s3_store) -> dict:
    st = s3_store.account.setdefault("s3files", {})
    for k in ("fs", "mt", "ap", "policy", "sync"):
        st.setdefault(k, {})
    return st


def _fs_view(f):
    return {k: v for k, v in f.items() if not k.startswith("_")}


def _need_fs(st, fid):
    f = st["fs"].get(fid)
    if not f:
        raise _Err("ResourceNotFoundException", f"File system {fid} does not exist.", 404)
    return f


def _norm_path(path):
    p = "/" + str(path or "/").strip("/")
    if ".." in p.split("/") or "\x00" in p:
        raise _Err("ValidationException", "path must not contain '..'.", 400)
    return p


def _fs_key(f, path):
    base = f["prefix"]
    return base + _norm_path(path).lstrip("/")


def _create_fs(s3_store, p):
    st = _fs_state(s3_store)
    arn = p.get("bucket") or ""
    mt = re.fullmatch(r"arn:aws[-a-z0-9]*:s3:::([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])", arn)
    if not mt:
        raise _Err("ValidationException", "bucket must be an S3 bucket ARN (arn:aws:s3:::name).", 400)
    bucket = mt.group(1)
    if not s3_store.bucket_exists(bucket):
        raise _Err("ResourceNotFoundException", f"The bucket {bucket} does not exist.", 404)
    if not _arn_ok_role(p.get("roleArn")):
        raise _Err("ValidationException", "roleArn must be an IAM role ARN that S3 Files can assume.", 400)
    prefix = p.get("prefix") or ""
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    if prefix.startswith("/") or ".." in prefix:
        raise _Err("ValidationException", "prefix must be a relative key prefix.", 400)
    tok = p.get("clientToken")
    for f in st["fs"].values():
        if tok and f.get("_token") == tok:
            return f
        if f["bucket"] == bucket and f["prefix"] == prefix:
            raise _Err("ConflictException", f"A file system ({f['fileSystemId']}) already exists for s3://{bucket}/{prefix}.", 409)
    tags = p.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(t, dict) or "key" not in t for t in tags):
        raise _Err("ValidationException", "tags must be a list of {key, value}.", 400)
    fid = _rid("fs")
    f = {"fileSystemId": fid, "fileSystemArn": f"arn:aws:s3files:{_REGION}:{_ACCOUNT}:file-system/{fid}", "bucket": bucket,
         "bucketArn": arn, "prefix": prefix, "roleArn": p["roleArn"], "status": "available", "creationTime": _ts(), "ownerId": _ACCOUNT,
         "name": next((t.get("value") for t in tags if t["key"] == "Name"), None), "tags": tags, "_token": tok}
    if p.get("kmsKeyId"):
        f["kmsKeyId"] = p["kmsKeyId"]
    st["fs"][fid] = f
    if prefix:                                        # materialise the root directory marker like the S3 console's "Create folder"
        _s3c().put_object(s3_store, bucket, prefix, b"", {"content-type": "application/x-directory"})
    return f


def _create_mt(s3_store, vpc_store, fid, p):
    st = _fs_state(s3_store)
    _need_fs(st, fid)
    m = _vpcc()._model(vpc_store)
    sid = p.get("subnetId")
    sub = m["subnets"].get(sid)
    if not sub:
        raise _Err("ResourceNotFoundException", f"The subnet {sid} does not exist.", 404)
    for sg in p.get("securityGroups") or []:
        s = m["sgs"].get(sg)
        if not s or s.get("vpc_id") != sub["vpc_id"]:
            raise _Err("ValidationException", f"Security group {sg} does not exist in the subnet's VPC.", 400)
    for t in st["mt"].values():
        if t["fileSystemId"] == fid and t["availabilityZoneName"] == sub["az"]:
            raise _Err("ConflictException", f"The file system already has a mount target in {sub['az']} ({t['mountTargetId']}).", 409)
    ip = p.get("ipAddress")
    if not ip:
        base = sub["cidr"].split("/")[0].rsplit(".", 1)[0]
        used = {t["ipAddress"] for t in st["mt"].values()}
        ip = next(f"{base}.{n}" for n in range(10, 250) if f"{base}.{n}" not in used)
    elif not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip):
        raise _Err("ValidationException", "ipAddress must be an IPv4 address.", 400)
    mid = _rid("fsmt")
    t = {"mountTargetId": mid, "fileSystemId": fid, "subnetId": sid, "vpcId": sub["vpc_id"], "availabilityZoneName": sub["az"], "ipAddress": ip,
         "securityGroups": list(p.get("securityGroups") or []), "status": "available", "ownerId": _ACCOUNT}
    st["mt"][mid] = t
    return t


def _create_ap(s3_store, fid, p):
    st = _fs_state(s3_store)
    _need_fs(st, fid)
    pu = p.get("posixUser")
    if pu is not None and not (isinstance(pu, dict) and isinstance(pu.get("uid"), int) and isinstance(pu.get("gid"), int) and pu["uid"] >= 0 and pu["gid"] >= 0):
        raise _Err("ValidationException", "posixUser requires non-negative integer uid and gid.", 400)
    root = p.get("rootDirectory") or {"path": "/"}
    path = root.get("path") or "/"
    if not path.startswith("/"):
        raise _Err("ValidationException", "rootDirectory.path must start with '/'.", 400)
    cp = root.get("creationPermissions")
    if cp is not None and not re.fullmatch(r"[0-7]{3,4}", str(cp.get("permissions", ""))):
        raise _Err("ValidationException", "creationPermissions.permissions must be an octal mode such as 0755.", 400)
    name = p.get("name")
    if name and any(a["fileSystemId"] == fid and a.get("name") == name for a in st["ap"].values()):
        raise _Err("ConflictException", f"An access point named {name} already exists on this file system.", 409)
    aid = _rid("fsap")
    a = {"accessPointId": aid, "accessPointArn": f"arn:aws:s3files:{_REGION}:{_ACCOUNT}:access-point/{aid}", "fileSystemId": fid, "name": name,
         "posixUser": pu, "rootDirectory": {**root, "path": path}, "status": "available", "ownerId": _ACCOUNT, "tags": p.get("tags") or []}
    st["ap"][aid] = a
    return a


def _sync_validate(p):
    imp = p.get("importDataRules") or []
    exp = p.get("expirationDataRules") or []
    if len(imp) > 10:
        raise _Err("ValidationException", "At most 10 importDataRules are allowed.", 400)
    for r in imp:
        if r.get("trigger") not in ("ON_DIRECTORY_FIRST_ACCESS", "ON_FILE_ACCESS"):
            raise _Err("ValidationException", "importDataRules[].trigger must be ON_DIRECTORY_FIRST_ACCESS or ON_FILE_ACCESS.", 400)
        if "sizeLessThan" in r and not (isinstance(r["sizeLessThan"], int) and r["sizeLessThan"] > 0):
            raise _Err("ValidationException", "sizeLessThan must be a positive integer (bytes).", 400)
    for r in exp:
        d = r.get("daysAfterLastAccess")
        if not (isinstance(d, int) and 1 <= d <= 365):
            raise _Err("ValidationException", "expirationDataRules[].daysAfterLastAccess must be 1-365.", 400)
    return {"importDataRules": imp, "expirationDataRules": exp}


def _list_dir(s3_store, f, path):
    path = _norm_path(path)
    base = _fs_key(f, path)
    if base and not base.endswith("/"):
        base += "/"
    q = {"list-type": "2", "prefix": base, "delimiter": "/", "max-keys": "1000"}
    r = _s3c().list_objects_v2(s3_store, f["bucket"], q)
    xml = r.body.decode()
    entries = []
    for cp in re.findall(r"<CommonPrefixes><Prefix>(.*?)</Prefix></CommonPrefixes>", xml):
        nm = _unesc(cp)[len(base):].rstrip("/")
        if nm:
            entries.append({"name": nm, "type": "directory"})
    for blk in re.findall(r"<Contents>(.*?)</Contents>", xml):
        key = _unesc(re.search(r"<Key>(.*?)</Key>", blk).group(1))
        nm = key[len(base):]
        if not nm or nm.endswith("/"):
            continue
        entries.append({"name": nm, "type": "file", "size": int(re.search(r"<Size>(\d+)</Size>", blk).group(1)),
                        "lastModified": re.search(r"<LastModified>(.*?)</LastModified>", blk).group(1)})
    entries.sort(key=lambda e: (e["type"] != "directory", e["name"]))
    return entries


def _unesc(s):
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def dispatch(s3_store, vpc_store, method, raw_path, query, body):
    """S3 Files REST."""
    method = method.upper()
    path = "/" + raw_path.strip("/")
    query = query or {}
    try:
        p = json.loads(body) if body and method in ("POST", "PUT") and not path.endswith("/file") else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return _json_err(_Err("ValidationException", "The request body must be a JSON object.", 400))
    st = _fs_state(s3_store)
    try:
        if path == "/file-systems":
            if method == "POST":
                f = _create_fs(s3_store, p)
                s3_store.persist()
                return _json_resp(201, _fs_view(f))
            if method == "GET":
                return _json_resp(200, {"fileSystems": [_fs_view(f) for f in sorted(st["fs"].values(), key=lambda x: x["creationTime"])]})
        mt = re.fullmatch(r"/file-systems/(fs-[0-9a-f]+)", path)
        if mt:
            fid = mt.group(1)
            f = _need_fs(st, fid)
            if method == "GET":
                return _json_resp(200, _fs_view(f))
            if method == "DELETE":
                if any(t["fileSystemId"] == fid for t in st["mt"].values()):
                    raise _Err("ConflictException", "Delete the file system's mount targets first.", 409)
                if any(a["fileSystemId"] == fid for a in st["ap"].values()):
                    raise _Err("ConflictException", "Delete the file system's access points first.", 409)
                st["fs"].pop(fid)
                st["policy"].pop(fid, None)
                st["sync"].pop(fid, None)
                s3_store.persist()
                return _json_resp(204, None)
        mt = re.fullmatch(r"/file-systems/(fs-[0-9a-f]+)/(mount-targets|access-points)", path)
        if mt:
            fid, kind = mt.groups()
            _need_fs(st, fid)
            if method == "POST":
                obj = _create_mt(s3_store, vpc_store, fid, p) if kind == "mount-targets" else _create_ap(s3_store, fid, p)
                s3_store.persist()
                return _json_resp(201, obj)
            if method == "GET":
                src = st["mt"] if kind == "mount-targets" else st["ap"]
                key = "mountTargets" if kind == "mount-targets" else "accessPoints"
                return _json_resp(200, {key: [x for x in src.values() if x["fileSystemId"] == fid]})
        mt = re.fullmatch(r"/(mount-targets|access-points)/((?:fsmt|fsap)-[0-9a-f]+)", path)
        if mt:
            kind, rid = mt.groups()
            src = st["mt"] if kind == "mount-targets" else st["ap"]
            if rid not in src:
                raise _Err("ResourceNotFoundException", f"{rid} does not exist.", 404)
            if method == "GET":
                return _json_resp(200, src[rid])
            if method == "DELETE":
                src.pop(rid)
                s3_store.persist()
                return _json_resp(204, None)
        mt = re.fullmatch(r"/file-systems/(fs-[0-9a-f]+)/policy", path)
        if mt:
            fid = mt.group(1)
            _need_fs(st, fid)
            if method == "PUT":
                pol = p.get("policy")
                try:
                    doc = json.loads(pol) if isinstance(pol, str) else None
                except ValueError:
                    doc = None
                if not isinstance(doc, dict) or "Statement" not in doc:
                    raise _Err("ValidationException", "policy must be a JSON policy document with a Statement.", 400)
                st["policy"][fid] = pol
                s3_store.persist()
                return _json_resp(200, {"fileSystemId": fid, "policy": pol})
            if method == "GET":
                if fid not in st["policy"]:
                    raise _Err("PolicyNotFound", "The file system has no policy.", 404)
                return _json_resp(200, {"fileSystemId": fid, "policy": st["policy"][fid]})
            if method == "DELETE":
                if st["policy"].pop(fid, None) is None:
                    raise _Err("PolicyNotFound", "The file system has no policy.", 404)
                s3_store.persist()
                return _json_resp(204, None)
        mt = re.fullmatch(r"/file-systems/(fs-[0-9a-f]+)/synchronization-configuration", path)
        if mt:
            fid = mt.group(1)
            _need_fs(st, fid)
            if method == "PUT":
                st["sync"][fid] = _sync_validate(p)
                s3_store.persist()
                return _json_resp(200, {"fileSystemId": fid, **st["sync"][fid]})
            if method == "GET":
                return _json_resp(200, {"fileSystemId": fid, **st["sync"].get(fid, {"importDataRules": [], "expirationDataRules": []})})
        mt = re.fullmatch(r"/file-systems/(fs-[0-9a-f]+)/(files|file|directories)", path)
        if mt:
            fid, what = mt.groups()
            f = _need_fs(st, fid)
            s3c = _s3c()
            if what == "files" and method == "GET":
                return _json_resp(200, {"path": _norm_path(query.get("path")), "entries": _list_dir(s3_store, f, query.get("path"))})
            if what == "directories" and method == "POST":
                key = _fs_key(f, p.get("path") or "") + "/"
                s3c.put_object(s3_store, f["bucket"], key, b"", {"content-type": "application/x-directory"})
                return _json_resp(201, {"path": _norm_path(p.get("path"))})
            if what == "file":
                key = _fs_key(f, query.get("path") or "")
                if key.endswith("/") or key == f["prefix"].rstrip("/"):
                    raise _Err("ValidationException", "path must name a file.", 400)
                if method == "PUT":
                    d = json.loads(body) if body else {}
                    data = base64.b64decode(d["contentBase64"]) if d.get("contentBase64") is not None else str(d.get("content", "")).encode()
                    r = s3c.put_object(s3_store, f["bucket"], key, data, {"content-type": d.get("contentType", "application/octet-stream")})
                    return _json_resp(200 if r.status == 200 else r.status, {"path": _norm_path(query.get("path")), "size": len(data)})
                if method == "GET":
                    r = s3c.get_object(s3_store, f["bucket"], key, {}, {})
                    if r.status != 200:
                        raise _Err("ResourceNotFoundException", f"No file at {_norm_path(query.get('path'))}.", 404)
                    return _json_resp(200, {"path": _norm_path(query.get("path")), "size": len(r.body), "contentBase64": base64.b64encode(r.body).decode()})
                if method == "DELETE":
                    s3c.delete_object(s3_store, f["bucket"], key, {}, {})
                    return _json_resp(204, None)
    except _Err as e:
        return _json_err(e)
    return _json_err(_Err("NotFoundException", f"Unsupported S3 Files operation: {method} {path}", 404))


# ═════════════════════════════════ FSx for OpenZFS ═════════════════════════════════
def _fx(s3_store) -> dict:
    st = s3_store.account.setdefault("fsx", {})
    for k in ("fs", "vol", "ap"):
        st.setdefault(k, {})
    return st


def _fsx_ok(doc):
    r = _json_resp(200, doc)
    r.headers["content-type"] = "application/x-amz-json-1.1"
    return r


def _fsx_err(e):
    r = _json_err(_Err(e.code, e.message, 400))      # FSx reports its modelled errors as HTTP 400
    r.headers["content-type"] = "application/x-amz-json-1.1"
    return r


def _fsx_fs_view(f):
    return {k: v for k, v in f.items() if not k.startswith("_")}


def _fsx_create_fs(s3_store, vpc_store, p):
    st = _fx(s3_store)
    if p.get("FileSystemType") != "OPENZFS":
        raise _Err("BadRequest", "Vyomi supports FileSystemType OPENZFS (the type that has S3 access points).", 400)
    cap = p.get("StorageCapacity")
    if not (isinstance(cap, int) and 64 <= cap <= 524288):
        raise _Err("BadRequest", "StorageCapacity must be between 64 and 524288 GiB for OpenZFS.", 400)
    subs = p.get("SubnetIds") or []
    m = _vpcc()._model(vpc_store)
    if not subs or any(s not in m["subnets"] for s in subs):
        raise _Err("BadRequest", "SubnetIds must reference existing subnets.", 400)
    cfg = p.get("OpenZFSConfiguration") or {}
    dep = cfg.get("DeploymentType")
    if dep not in ("SINGLE_AZ_1", "SINGLE_AZ_2", "SINGLE_AZ_HA_1", "SINGLE_AZ_HA_2", "MULTI_AZ_1"):
        raise _Err("BadRequest", "OpenZFSConfiguration.DeploymentType is invalid.", 400)
    if not isinstance(cfg.get("ThroughputCapacity"), int):
        raise _Err("BadRequest", "OpenZFSConfiguration.ThroughputCapacity is required.", 400)
    fid = _rid("fs", 17)
    rv = _rid("fsvol", 17)
    vpc_id = m["subnets"][subs[0]]["vpc_id"]
    f = {"OwnerId": _ACCOUNT, "CreationTime": _ts(), "FileSystemId": fid, "FileSystemType": "OPENZFS", "Lifecycle": "AVAILABLE",
         "StorageCapacity": cap, "StorageType": p.get("StorageType", "SSD"), "VpcId": vpc_id, "SubnetIds": subs,
         "ResourceARN": f"arn:aws:fsx:{_REGION}:{_ACCOUNT}:file-system/{fid}", "Tags": p.get("Tags") or [],
         "DNSName": f"{fid}.fsx.{_REGION}.amazonaws.com",
         "OpenZFSConfiguration": {"DeploymentType": dep, "ThroughputCapacity": cfg["ThroughputCapacity"], "RootVolumeId": rv}}
    st["fs"][fid] = f
    st["vol"][rv] = {"VolumeId": rv, "FileSystemId": fid, "Name": "fsx", "VolumeType": "OPENZFS", "Lifecycle": "AVAILABLE", "CreationTime": _ts(),
                     "ResourceARN": f"arn:aws:fsx:{_REGION}:{_ACCOUNT}:volume/{fid}/{rv}", "Tags": [],
                     "OpenZFSConfiguration": {"ParentVolumeId": None, "VolumePath": "/"}, "_files": {}}
    return f


def _vol_view(v):
    return {k: val for k, val in v.items() if not k.startswith("_")}


def _fsx_create_volume(s3_store, p):
    st = _fx(s3_store)
    if p.get("VolumeType") != "OPENZFS":
        raise _Err("BadRequest", "VolumeType must be OPENZFS.", 400)
    nm = p.get("Name") or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,203}", nm):
        raise _Err("BadRequest", "Name must be 1-203 characters of letters, digits, '_' or '-'.", 400)
    cfg = p.get("OpenZFSConfiguration") or {}
    parent = st["vol"].get(cfg.get("ParentVolumeId"))
    if not parent:
        raise _Err("VolumeNotFound", f"Parent volume {cfg.get('ParentVolumeId')} does not exist.", 404)
    if any(v["FileSystemId"] == parent["FileSystemId"] and v["Name"] == nm for v in st["vol"].values()):
        raise _Err("BadRequest", f"A volume named {nm} already exists on this file system.", 400)
    vid = _rid("fsvol", 17)
    path = parent["OpenZFSConfiguration"]["VolumePath"].rstrip("/") + "/" + nm
    v = {"VolumeId": vid, "FileSystemId": parent["FileSystemId"], "Name": nm, "VolumeType": "OPENZFS", "Lifecycle": "AVAILABLE", "CreationTime": _ts(),
         "ResourceARN": f"arn:aws:fsx:{_REGION}:{_ACCOUNT}:volume/{parent['FileSystemId']}/{vid}", "Tags": p.get("Tags") or [],
         "OpenZFSConfiguration": {"ParentVolumeId": parent["VolumeId"], "VolumePath": path}, "_files": {}}
    st["vol"][vid] = v
    return v


def _alias(name):
    return f"{name[:20]}-{uuid.uuid4().hex[:10]}-ext-s3alias"


def _attach(s3_store, vpc_store, p):
    st = _fx(s3_store)
    nm = p.get("Name") or ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}[a-z0-9]", nm):
        raise _Err("BadRequest", "Name must be 3-51 lowercase letters, digits or hyphens.", 400)
    if p.get("Type") != "OPENZFS":
        raise _Err("BadRequest", "Type must be OPENZFS.", 400)
    if nm in st["ap"]:
        raise _Err("BadRequest", f"An S3 access point attachment named {nm} already exists.", 400)
    cfg = p.get("OpenZFSConfiguration") or {}
    vol = st["vol"].get(cfg.get("VolumeId"))
    if not vol:
        raise _Err("VolumeNotFound", f"Volume {cfg.get('VolumeId')} does not exist.", 404)
    ident = cfg.get("FileSystemIdentity") or {}
    if ident.get("Type") != "POSIX" or not isinstance(ident.get("PosixUser"), dict) or not all(isinstance(ident["PosixUser"].get(k), int) for k in ("Uid", "Gid")):
        raise _Err("BadRequest", "FileSystemIdentity must be Type POSIX with a PosixUser {Uid, Gid}.", 400)
    s3ap = p.get("S3AccessPoint") or {}
    vpc_cfg = s3ap.get("VpcConfiguration")
    if vpc_cfg is not None:
        m = _vpcc()._model(vpc_store)
        if vpc_cfg.get("VpcId") not in m["vpcs"]:
            raise _Err("BadRequest", f"VPC {vpc_cfg.get('VpcId')} does not exist.", 400)
    if s3ap.get("Policy"):
        try:
            if not isinstance(json.loads(s3ap["Policy"]), dict):
                raise ValueError
        except ValueError:
            raise _Err("BadRequest", "S3AccessPoint.Policy must be a JSON policy document.", 400)
    alias = _alias(nm)
    a = {"Lifecycle": "AVAILABLE", "CreationTime": _ts(), "OperationId": uuid.uuid4().hex, "Name": nm, "Type": "OPENZFS",
         "OpenZFSConfiguration": {"VolumeId": vol["VolumeId"], "FileSystemIdentity": ident},
         "S3AccessPoint": {"ResourceARN": f"arn:aws:s3:{_REGION}:{_ACCOUNT}:accesspoint/{nm}", "Alias": alias,
                           **({"VpcConfiguration": vpc_cfg} if vpc_cfg else {}), **({"Policy": s3ap["Policy"]} if s3ap.get("Policy") else {})}}
    st["ap"][nm] = a
    return a


def fsx_dispatch(s3_store, vpc_store, target, body):
    op = (target or "").rsplit(".", 1)[-1]
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return _fsx_err(_Err("BadRequest", "The request body must be a JSON object.", 400))
    st = _fx(s3_store)
    try:
        if op == "CreateFileSystem":
            f = _fsx_create_fs(s3_store, vpc_store, p)
            s3_store.persist()
            return _fsx_ok({"FileSystem": _fsx_fs_view(f)})
        if op == "DescribeFileSystems":
            ids = p.get("FileSystemIds")
            rows = [st["fs"][i] for i in ids if i in st["fs"]] if ids else list(st["fs"].values())
            if ids and len(rows) != len(ids):
                raise _Err("FileSystemNotFound", "One or more file systems were not found.", 400)
            return _fsx_ok({"FileSystems": [_fsx_fs_view(f) for f in rows]})
        if op == "DeleteFileSystem":
            fid = p.get("FileSystemId")
            if fid not in st["fs"]:
                raise _Err("FileSystemNotFound", f"File system {fid} does not exist.", 400)
            root = st["fs"][fid]["OpenZFSConfiguration"]["RootVolumeId"]
            kids = [v for v in st["vol"].values() if v["FileSystemId"] == fid and v["VolumeId"] != root]
            if kids:
                raise _Err("BadRequest", "Delete the file system's child volumes first.", 400)
            if any(a["OpenZFSConfiguration"]["VolumeId"] == root for a in st["ap"].values()):
                raise _Err("BadRequest", "Detach the S3 access points attached to the root volume first.", 400)
            st["fs"].pop(fid)
            st["vol"].pop(root, None)
            s3_store.persist()
            return _fsx_ok({"FileSystemId": fid, "Lifecycle": "DELETING"})
        if op == "CreateVolume":
            v = _fsx_create_volume(s3_store, p)
            s3_store.persist()
            return _fsx_ok({"Volume": _vol_view(v)})
        if op == "DescribeVolumes":
            ids = p.get("VolumeIds")
            rows = [st["vol"][i] for i in ids if i in st["vol"]] if ids else list(st["vol"].values())
            if ids and len(rows) != len(ids):
                raise _Err("VolumeNotFound", "One or more volumes were not found.", 400)
            for flt in p.get("Filters") or []:
                if flt.get("Name") == "file-system-id":
                    rows = [v for v in rows if v["FileSystemId"] in (flt.get("Values") or [])]
            return _fsx_ok({"Volumes": [_vol_view(v) for v in rows]})
        if op == "DeleteVolume":
            vid = p.get("VolumeId")
            v = st["vol"].get(vid)
            if not v:
                raise _Err("VolumeNotFound", f"Volume {vid} does not exist.", 400)
            if v["OpenZFSConfiguration"]["ParentVolumeId"] is None:
                raise _Err("BadRequest", "The root volume is deleted with its file system.", 400)
            if any(c["OpenZFSConfiguration"]["ParentVolumeId"] == vid for c in st["vol"].values()):
                raise _Err("BadRequest", "Delete the child volumes first.", 400)
            if any(a["OpenZFSConfiguration"]["VolumeId"] == vid for a in st["ap"].values()):
                raise _Err("BadRequest", "Detach the S3 access points attached to this volume first.", 400)
            st["vol"].pop(vid)
            s3_store.persist()
            return _fsx_ok({"VolumeId": vid, "Lifecycle": "DELETING"})
        if op == "CreateAndAttachS3AccessPoint":
            a = _attach(s3_store, vpc_store, p)
            s3_store.persist()
            return _fsx_ok({"S3AccessPointAttachment": a})
        if op == "DescribeS3AccessPointAttachments":
            rows = list(st["ap"].values())
            names = p.get("Names")
            if names:
                rows = [a for a in rows if a["Name"] in names]
            for flt in p.get("Filters") or []:
                if flt.get("Name") == "volume-id":
                    rows = [a for a in rows if a["OpenZFSConfiguration"]["VolumeId"] in (flt.get("Values") or [])]
                elif flt.get("Name") == "file-system-id":
                    rows = [a for a in rows if st["vol"].get(a["OpenZFSConfiguration"]["VolumeId"], {}).get("FileSystemId") in (flt.get("Values") or [])]
            return _fsx_ok({"S3AccessPointAttachments": rows})
        if op == "DetachAndDeleteS3AccessPoint":
            nm = p.get("Name")
            if nm not in st["ap"]:
                raise _Err("S3AccessPointAttachmentNotFound", f"S3 access point attachment {nm} does not exist.", 400)
            st["ap"].pop(nm)
            s3_store.persist()
            return _fsx_ok({"Lifecycle": "DELETING", "Name": nm})
        if op == "VyomiPutVolumeFile":
            v = st["vol"].get(p.get("VolumeId"))
            if not v:
                raise _Err("VolumeNotFound", f"Volume {p.get('VolumeId')} does not exist.", 400)
            path = _norm_path(p.get("Path"))
            if path == "/":
                raise _Err("BadRequest", "Path must name a file.", 400)
            data = base64.b64decode(p["ContentBase64"]) if p.get("ContentBase64") is not None else str(p.get("Content", "")).encode()
            v["_files"][path.lstrip("/")] = {"b": base64.b64encode(data).decode(), "mtime": _iso(), "size": len(data)}
            s3_store.persist()
            return _fsx_ok({"Path": path, "Size": len(data)})
        if op == "VyomiListVolumeFiles":
            v = st["vol"].get(p.get("VolumeId"))
            if not v:
                raise _Err("VolumeNotFound", f"Volume {p.get('VolumeId')} does not exist.", 400)
            return _fsx_ok({"Files": [{"Path": "/" + k, "Size": f["size"], "LastModified": f["mtime"]} for k, f in sorted(v["_files"].items())]})
    except _Err as e:
        return _fsx_err(e)
    return _fsx_err(_Err("UnknownOperationException", f"Unsupported FSx operation {op}.", 400))


# ───────────── S3 API served on an FSx access point alias (bucket "<name>-<id>-ext-s3alias") ─────────────
def alias_volume(s3_store, alias):
    st = s3_store.account.get("fsx")
    if not st:
        return None
    for a in st["ap"].values():
        if a["S3AccessPoint"]["Alias"] == alias:
            return st["vol"].get(a["OpenZFSConfiguration"]["VolumeId"])
    return None


def alias_dispatch(s3_store, vol, alias, method, key, query, headers, body):
    m = _s3c()
    files = vol["_files"]
    if not key:
        if method != "GET":
            return m._error_xml("MethodNotAllowed", "Only object operations are supported on an FSx access point alias.", f"/{alias}", 405)
        prefix = query.get("prefix", "") or ""
        delim = query.get("delimiter", "") or ""
        keys = sorted(k for k in files if k.startswith(prefix))
        contents, cps = [], []
        for k in keys:
            if delim and delim in k[len(prefix):]:
                cp = prefix + k[len(prefix):].split(delim, 1)[0] + delim
                if cp not in cps:
                    cps.append(cp)
            else:
                contents.append(k)
        parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>{alias}</Name>',
                 f"<Prefix>{_esc(prefix)}</Prefix><KeyCount>{len(contents) + len(cps)}</KeyCount><MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated>"]
        for k in contents:
            f = files[k]
            parts.append(f"<Contents><Key>{_esc(k)}</Key><LastModified>{f['mtime']}</LastModified><ETag>&quot;{uuid.uuid5(uuid.NAMESPACE_URL, f['b']).hex}&quot;</ETag>"
                         f"<Size>{f['size']}</Size><StorageClass>STANDARD</StorageClass></Contents>")
        parts += [f"<CommonPrefixes><Prefix>{_esc(c)}</Prefix></CommonPrefixes>" for c in cps]
        parts.append("</ListBucketResult>")
        return m._xml_response("".join(parts))
    key = urllib_unquote(key)
    if method in ("GET", "HEAD"):
        f = files.get(key)
        if not f:
            return m._error_xml("NoSuchKey", "The specified key does not exist.", f"/{alias}/{key}", 404)
        data = base64.b64decode(f["b"])
        return m.S3Response(status=200, headers={**m._amz_headers(), "ETag": f'"{uuid.uuid5(uuid.NAMESPACE_URL, f["b"]).hex}"', "Content-Length": str(len(data)),
                                                 "Last-Modified": f["mtime"]}, body=b"" if method == "HEAD" else data, media_type="application/octet-stream")
    if method == "PUT":
        files[key] = {"b": base64.b64encode(bytes(body)).decode(), "mtime": _iso(), "size": len(body)}
        s3_store.persist()
        return m.S3Response(status=200, headers={**m._amz_headers(), "ETag": f'"{uuid.uuid5(uuid.NAMESPACE_URL, files[key]["b"]).hex}"'}, body=b"")
    if method == "DELETE":
        files.pop(key, None)
        s3_store.persist()
        return m.S3Response(status=204, headers=m._amz_headers(), body=b"")
    return m._error_xml("MethodNotAllowed", "Unsupported operation on an FSx access point alias.", f"/{alias}/{key}", 405)


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)
