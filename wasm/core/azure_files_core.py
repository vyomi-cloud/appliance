# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Files control plane (Nano / dev_server / unified-ingress core).

``Microsoft.Storage/storageAccounts/{sa}/fileServices/default`` and ``.../shares/{share}`` as real ARM
sub-resources stored in the shared ``AzureArm.state`` map:

* File service properties: CORS rules (validated like the Blob service), ``shareDeleteRetentionPolicy``
  (days 1-365), SMB ``protocolSettings`` (versions / authentication methods / channel encryption / multichannel
  -- multichannel and NFS are Premium-only), enforced.
* Shares: name rule (3-63, lower-case letters / digits / hyphens, no consecutive hyphens), ``shareQuota`` limits by
  account kind + ``largeFileSharesState`` (5120 GiB; 102400 with large file shares / Premium FileStorage),
  ``enabledProtocols`` SMB|NFS (NFS only on Premium FileStorage, never together with ``accessTier``), ``rootSquash``
  only for NFS, ``accessTier`` TransactionOptimized|Hot|Cool (Standard) / Premium (FileStorage), metadata, ETag,
  ``shareUsageBytes`` from the real stored content, quota enforcement on write.
* Soft delete: deleting a share with retention enabled keeps it ``deleted`` (visible with ``$filter=deleted eq true``)
  and ``POST .../restore`` brings it back; without retention it is gone.
* Snapshots: ``POST .../shares/{n}/snapshot`` (Vyomi action; the real service takes this on the data plane) freezes
  the content, listed with ``$expand=snapshots``; ``GET ...?snapshot=<time>``; snapshot deletion; a share with
  snapshots refuses DELETE (409) unless ``x-ms-delete-snapshots`` semantics are requested via ``?include=snapshots``.
* Lease: ``POST .../lease`` acquire/release/break/renew/change.
* Content: ``.../shares/{n}/items/{path}`` (Vyomi extension for the console file browser; the real data plane is
  the SMB/NFS protocol or ``account.file.core.windows.net``): create directory / upload file (base64) / list /
  download / delete.

NOT modelled: the SMB 3.x / NFS 4.1 wire protocols themselves (nothing can ``mount`` a Vyomi share), AD DS / Entra
Kerberos identity-based authentication enforcement, share-level SAS / ACL enforcement, file leases, and
snapshot-share-level restore of single files.

Pure python, no framework imports. Each function returns ``{"status": int, "body": ...}``.
"""
from __future__ import annotations

import base64
import binascii
import datetime
import re
import uuid

API_VERSION = "2023-01-01"
SHARE_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TIERS = ("TransactionOptimized", "Hot", "Cool", "Premium")
SQUASH = ("NoRootSquash", "RootSquash", "AllSquash")
SMB_VERSIONS = ("SMB2.1", "SMB3.0", "SMB3.1.1")
SMB_AUTH = ("NTLMv2", "Kerberos")
SMB_ENC = ("AES-128-CCM", "AES-128-GCM", "AES-256-GCM")
KERB_ENC = ("RC4-HMAC", "AES-256")
MAX_STD = 5120
MAX_LARGE = 102400


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles(namespace: str, chain) -> bool:
    return (namespace.lower() == "microsoft.storage" and len(chain) >= 3 and chain[0].lower() == "storageaccounts"
            and chain[2].lower() in ("fileservices", "queueservices", "tableservices"))


def _account(state, sub, rg, name):
    return state.get(f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{name}".lower())


def is_premium(acct) -> bool:
    kind = (acct.get("kind") or "").lower()
    sku = ((acct.get("sku") or {}).get("name") or "").lower()
    return kind == "filestorage" or sku.startswith("premium")


def max_quota(acct) -> int:
    large = ((acct.get("properties") or {}).get("largeFileSharesState") or "").lower() == "enabled"
    return MAX_LARGE if (is_premium(acct) or large) else MAX_STD


def validate_share_name(name: str):
    if not (3 <= len(name) <= 63) or not SHARE_NAME_RE.match(name):
        return ("InvalidResourceName", f"The specified resource name '{name}' is not valid. Share names must be 3-63 characters, "
                "lower-case letters, numbers and single hyphens, starting and ending with a letter or number.")
    return None


def _validate_cors(rules):
    if not isinstance(rules, list) or len(rules) > 5:
        return "A maximum of 5 CORS rules can be specified."
    for r in rules:
        for k in ("allowedOrigins", "allowedMethods", "maxAgeInSeconds", "exposedHeaders", "allowedHeaders"):
            if k not in r:
                return f"CORS rule is missing '{k}'."
        bad = [m for m in r["allowedMethods"] if m.upper() not in ("DELETE", "GET", "HEAD", "MERGE", "POST", "OPTIONS", "PUT", "PATCH")]
        if bad:
            return f"Invalid CORS method(s): {', '.join(bad)}."
        if not r["allowedOrigins"] or not r["allowedMethods"]:
            return "CORS rule needs at least one allowed origin and method."
        if not (0 <= int(r["maxAgeInSeconds"]) <= 2147483647):
            return "maxAgeInSeconds is out of range."
    return None


def _service(state, acct):
    return acct.setdefault("_fileservice", {
        "cors": {"corsRules": []},
        "shareDeleteRetentionPolicy": {"enabled": True, "days": 7, "allowPermanentDelete": False},
        "protocolSettings": {"smb": {"versions": "SMB2.1;SMB3.0;SMB3.1.1", "authenticationMethods": "NTLMv2;Kerberos",
                                     "kerberosTicketEncryption": "RC4-HMAC;AES-256",
                                     "channelEncryption": "AES-128-CCM;AES-128-GCM;AES-256-GCM", "multichannel": {"enabled": False}}},
    })


def _service_view(acct, base):
    s = _service(None, acct)
    return {"id": f"{base}/fileServices/default", "name": "default", "type": "Microsoft.Storage/storageAccounts/fileServices",
            "sku": acct.get("sku"), "properties": {k: v for k, v in s.items()}}


def _put_service(acct, payload):
    s = _service(None, acct)
    p = (payload or {}).get("properties") or {}
    if "cors" in p:
        e = _validate_cors((p["cors"] or {}).get("corsRules", []))
        if e:
            return _err(400, "InvalidXmlDocument", e)
        s["cors"] = {"corsRules": p["cors"].get("corsRules", [])}
    if "shareDeleteRetentionPolicy" in p:
        pol = p["shareDeleteRetentionPolicy"] or {}
        if pol.get("enabled") and not (1 <= int(pol.get("days") or 0) <= 365):
            return _err(400, "InvalidInput", "shareDeleteRetentionPolicy.days must be between 1 and 365 when enabled.")
        s["shareDeleteRetentionPolicy"] = {"enabled": bool(pol.get("enabled")), "days": int(pol.get("days") or 7) if pol.get("enabled") else None,
                                           "allowPermanentDelete": bool(pol.get("allowPermanentDelete"))}
        if not pol.get("enabled"):
            s["shareDeleteRetentionPolicy"].pop("days")
    smb = ((p.get("protocolSettings") or {}).get("smb"))
    if smb is not None:
        cur = s["protocolSettings"]["smb"]
        for key, allowed in (("versions", SMB_VERSIONS), ("authenticationMethods", SMB_AUTH), ("kerberosTicketEncryption", KERB_ENC),
                             ("channelEncryption", SMB_ENC)):
            if key in smb:
                vals = [v for v in str(smb[key] or "").split(";") if v]
                if not vals or any(v not in allowed for v in vals):
                    return _err(400, "InvalidInput", f"protocolSettings.smb.{key} must be a ';'-separated subset of {', '.join(allowed)}.")
                cur[key] = ";".join(vals)
        if "multichannel" in smb:
            en = bool((smb["multichannel"] or {}).get("enabled"))
            if en and not is_premium(acct):
                return _err(400, "FeatureNotSupported", "SMB multichannel is only supported on premium FileStorage accounts.")
            cur["multichannel"] = {"enabled": en}
    return None


def _shares(acct):
    return acct.setdefault("_files_shares", {})


def _usage(share) -> int:
    return sum(f.get("size", 0) for f in share["_tree"].values() if f["type"] == "file")


def _share_view(share, acct, base, expand_snaps=False):
    p = dict(share["properties"])
    p["shareUsageBytes"] = _usage(share)
    p["lastModifiedTime"] = share["_modified"]
    out = {"id": f"{base}/fileServices/default/shares/{share['name']}", "name": share["name"],
           "type": "Microsoft.Storage/storageAccounts/fileServices/shares", "etag": share["_etag"], "properties": p}
    if share.get("_deleted"):
        p["deleted"] = True
        p["deletedTime"] = share["_deleted"]
        p["remainingRetentionDays"] = share.get("_retention_left", 0)
    if share["_snaps"]:
        p["snapshotTime"] = None
    if expand_snaps:
        out["properties"]["_snapshots"] = [{"snapshotTime": s["time"], "usageBytes": s["usage"]} for s in share["_snaps"]]
    return out


def _put_share(state, acct, base, name, payload, method):
    err = validate_share_name(name)
    if err:
        return _err(400, *err)
    sa_rid = base
    shares = _shares(acct)
    p = (payload or {}).get("properties") or {}
    ex = shares.get(name.lower())
    if ex is not None and ex.get("_deleted"):
        return _err(409, "ShareBeingDeleted", f"The specified share '{name}' is in soft-deleted state; restore it or wait out the retention period.")
    prem = is_premium(acct)
    protocols = (p.get("enabledProtocols") or (ex["properties"].get("enabledProtocols") if ex else None) or "SMB").upper()
    if protocols not in ("SMB", "NFS"):
        return _err(400, "InvalidInput", "enabledProtocols must be SMB or NFS.")
    if protocols == "NFS" and not prem:
        return _err(400, "InvalidInput", "NFS file shares are only supported on premium FileStorage accounts.")
    if ex is not None and "enabledProtocols" in p and p["enabledProtocols"].upper() != ex["properties"]["enabledProtocols"]:
        return _err(409, "ShareProtocolImmutable", "The protocol of an existing share cannot be changed.")
    squash = p.get("rootSquash")
    if squash is not None:
        if protocols != "NFS":
            return _err(400, "InvalidInput", "rootSquash is only valid for NFS shares.")
        if squash not in SQUASH:
            return _err(400, "InvalidInput", f"rootSquash must be one of {', '.join(SQUASH)}.")
    tier = p.get("accessTier") or (ex["properties"].get("accessTier") if ex else None) or ("Premium" if prem else "TransactionOptimized")
    if tier not in TIERS:
        return _err(400, "InvalidInput", f"accessTier must be one of {', '.join(TIERS)}.")
    if prem and tier != "Premium":
        return _err(400, "InvalidInput", "Premium file shares only support the Premium access tier.")
    if not prem and tier == "Premium":
        return _err(400, "InvalidInput", "The Premium access tier requires a premium FileStorage account.")
    quota = p.get("shareQuota", ex["properties"]["shareQuota"] if ex else (100 if prem else 5120))
    try:
        quota = int(quota)
    except (TypeError, ValueError):
        return _err(400, "InvalidInput", "shareQuota must be an integer (GiB).")
    lo = 100 if prem else 1
    hi = max_quota(acct)
    if quota < lo or quota > hi:
        extra = "" if hi == MAX_LARGE else " Enable large file shares on the account to raise the limit to 102400 GiB."
        return _err(400, "InvalidInput", f"shareQuota must be between {lo} and {hi} GiB for this account.{extra}")
    if ex is not None and quota * 1024 ** 3 < _usage(ex):
        return _err(400, "InvalidInput", "shareQuota cannot be set below the share's current usage.")
    if ex is None:
        ex = {"name": name, "properties": {}, "_tree": {}, "_snaps": [], "_lease": {"state": "Available", "status": "Unlocked"}}
        shares[name.lower()] = ex
        status = 201
    else:
        status = 200
    props = ex["properties"]
    props.update({"enabledProtocols": protocols, "accessTier": tier, "shareQuota": quota})
    if protocols == "NFS":
        props["rootSquash"] = squash or props.get("rootSquash") or "NoRootSquash"
    elif "rootSquash" in props:
        props.pop("rootSquash")
    if "metadata" in p:
        props["metadata"] = p["metadata"] or {}
    props.setdefault("metadata", {})
    props["leaseStatus"] = ex["_lease"]["status"]
    props["leaseState"] = ex["_lease"]["state"]
    if status == 201:
        props["accessTierChangeTime"] = _now()
    ex["_modified"] = _now()
    ex["_etag"] = '"0x%s"' % uuid.uuid4().hex[:15].upper()
    return {"status": status, "body": _share_view(ex, acct, base)}


def _norm_path(parts):
    segs = [s for s in "/".join(parts).split("/") if s]
    for s in segs:
        if s in (".", "..") or len(s) > 255 or re.search(r'["\\:|<>*?]', s):
            return None
    return "/".join(segs)


def _items(state, acct, share, method, rest, payload, query):
    path = _norm_path(rest)
    if path is None:
        return _err(400, "InvalidResourceName", "The specified path contains characters or segments that are not valid.")
    tree = share["_tree"]
    if method == "GET":
        if path == "" or (path in tree and tree[path]["type"] == "directory"):
            pre = path + "/" if path else ""
            kids = [dict(name=k[len(pre):], type=v["type"], size=v.get("size") if v["type"] == "file" else None,
                         lastModified=v["modified"])
                    for k, v in sorted(tree.items()) if k.startswith(pre) and "/" not in k[len(pre):]]
            return {"status": 200, "body": {"path": path, "type": "directory", "value": kids}}
        f = tree.get(path)
        if not f:
            return _err(404, "ResourceNotFound", f"The specified path '{path}' does not exist.")
        return {"status": 200, "body": {"path": path, "type": "file", "size": f["size"], "lastModified": f["modified"],
                                        "contentType": f.get("contentType"), "contentBase64": f["_b64"]}}
    if share.get("_deleted"):
        return _err(409, "ShareBeingDeleted", "The share is soft-deleted.")
    if share["_lease"]["state"] == "Leased" and (payload or {}).get("leaseId") != share["_lease"].get("id"):
        return _err(412, "LeaseIdMissing", "There is currently a lease on the share and no lease ID was specified in the request.")
    if method == "PUT":
        if not path:
            return _err(400, "InvalidInput", "A path is required.")
        kind = (payload or {}).get("type") or "file"
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent and (parent not in tree or tree[parent]["type"] != "directory"):
            return _err(404, "ParentNotFound", f"The parent path '{parent}' does not exist.")
        if path in tree and tree[path]["type"] != kind:
            return _err(409, "ResourceTypeMismatch", "The specified path exists with a different type.")
        if kind == "directory":
            if path in tree:
                return _err(409, "ResourceAlreadyExists", "The specified directory already exists.")
            tree[path] = {"type": "directory", "modified": _now()}
        elif kind == "file":
            try:
                raw = base64.b64decode((payload or {}).get("contentBase64") or "", validate=True)
            except (binascii.Error, ValueError):
                return _err(400, "InvalidInput", "contentBase64 is not valid base64.")
            if len(raw) > 4 * 1024 ** 4:
                return _err(413, "RequestBodyTooLarge", "A file may not exceed 4 TiB.")
            used = _usage(share) - tree.get(path, {}).get("size", 0)
            if used + len(raw) > share["properties"]["shareQuota"] * 1024 ** 3:
                return _err(409, "ShareSizeLimitReached", "The specified share is full: the write would exceed shareQuota.")
            tree[path] = {"type": "file", "_b64": base64.b64encode(raw).decode(), "size": len(raw), "modified": _now(), "contentType": (payload or {}).get("contentType") or "application/octet-stream"}
        else:
            return _err(400, "InvalidInput", "type must be 'file' or 'directory'.")
        share["_modified"] = _now()
        return {"status": 201, "body": {"path": path, "type": kind}}
    if method == "DELETE":
        if path not in tree:
            return _err(404, "ResourceNotFound", f"The specified path '{path}' does not exist.")
        if tree[path]["type"] == "directory" and any(k.startswith(path + "/") for k in tree):
            return _err(409, "DirectoryNotEmpty", "The recursive query is not supported; delete the directory's children first.")
        tree.pop(path)
        share["_modified"] = _now()
        return {"status": 200, "body": None}
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _lease(share, payload):
    action = ((payload or {}).get("action") or "").lower()
    ls = share["_lease"]
    if action == "acquire":
        if ls["state"] == "Leased":
            return _err(409, "LeaseAlreadyPresent", "There is already a lease present.")
        ls.update({"state": "Leased", "status": "Locked", "id": (payload or {}).get("proposedLeaseId") or str(uuid.uuid4())})
        return {"status": 200, "body": {"leaseId": ls["id"]}}
    if action in ("release", "renew", "change"):
        if ls["state"] != "Leased" or (payload or {}).get("leaseId") != ls.get("id"):
            return _err(409, "LeaseIdMismatchWithLeaseOperation", "The lease ID specified did not match the lease ID for the share.")
        if action == "release":
            ls.update({"state": "Available", "status": "Unlocked", "id": None})
            return {"status": 200, "body": {}}
        if action == "change":
            ls["id"] = (payload or {}).get("proposedLeaseId") or str(uuid.uuid4())
        return {"status": 200, "body": {"leaseId": ls["id"]}}
    if action == "break":
        ls.update({"state": "Broken", "status": "Unlocked"})
        return {"status": 200, "body": {"leaseTimeSeconds": 0}}
    return _err(400, "InvalidInput", "action must be acquire, release, renew, change or break.")


def _qt_service(acct, base, chain, method, payload):
    """queueServices/default and tableServices/default: CORS rules only (validated + stored; the Queue / Table data planes
    do not evaluate preflight requests, so the capability is config_only)."""
    kind = "queueServices" if chain[2].lower() == "queueservices" else "tableServices"
    store = acct.setdefault("_" + kind, {"cors": {"corsRules": []}})
    view = lambda: {"id": f"{base}/{kind}/default", "name": "default", "type": f"Microsoft.Storage/storageAccounts/{kind}",
                    "properties": {"cors": store["cors"]}}
    if len(chain) == 3:
        return {"status": 200, "body": {"value": [view()]}} if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
    if chain[3].lower() != "default" or len(chain) > 4:
        return _err(404, "ResourceNotFound", f"The only {kind[:-1]} is named 'default'.")
    if method == "GET":
        return {"status": 200, "body": view()}
    if method in ("PUT", "PATCH"):
        cors = (((payload or {}).get("properties") or {}).get("cors"))
        if cors is not None:
            e = _validate_cors(cors.get("corsRules", []))
            if e:
                return _err(400, "InvalidXmlDocument", e)
            store["cors"] = {"corsRules": cors.get("corsRules", [])}
        return {"status": 200, "body": view()}
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def dispatch(state, method, sub, rg, chain, payload, query):
    """chain = ['storageAccounts', sa, 'fileServices', 'default', ...]."""
    sa = chain[1]
    acct = _account(state, sub, rg, sa)
    if acct is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Storage/storageAccounts/{sa}' under resource group '{rg}' was not found.")
    base = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{sa}"
    kind = (acct.get("kind") or "").lower()
    if kind == "blobstorage" or kind == "blockblobstorage":
        return _err(400, "FeatureNotSupported", f"File services are not supported on {acct.get('kind')} storage accounts.")
    if chain[2].lower() in ("queueservices", "tableservices"):
        return _qt_service(acct, base, chain, method, payload)
    rest = chain[3:]
    if len(chain) == 3:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return {"status": 200, "body": {"value": [_service_view(acct, base)]}}
    if rest[0].lower() != "default":
        return _err(404, "ResourceNotFound", "The only file service is named 'default'.")
    rest = rest[1:]
    if not rest:
        if method == "GET":
            return {"status": 200, "body": _service_view(acct, base)}
        if method in ("PUT", "PATCH"):
            e = _put_service(acct, payload)
            return e or {"status": 200, "body": _service_view(acct, base)}
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if rest[0].lower() != "shares":
        return _err(404, "ResourceNotFound", f"Unknown file service sub-resource '{rest[0]}'.")
    shares = _shares(acct)
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        exp = (query.get("$expand") or "").lower()
        rows = [_share_view(s, acct, base) for s in shares.values() if exp == "deleted" or not s.get("_deleted")]
        return {"status": 200, "body": {"value": rows}}
    name = rest[1]
    sh = shares.get(name.lower())
    tail = rest[2:]
    if not tail:
        if method == "GET":
            if not sh or (sh.get("_deleted") and "deleted" not in (query.get("$expand") or "")):
                return _err(404, "ShareNotFound", f"The specified share '{name}' does not exist.")
            snap_t = query.get("snapshot") or query.get("$snapshot")
            if snap_t:
                sn = next((s for s in sh["_snaps"] if s["time"] == snap_t), None)
                if not sn:
                    return _err(404, "ShareSnapshotNotFound", "The specified share snapshot does not exist.")
                v = _share_view(sh, acct, base)
                v["properties"]["snapshotTime"] = sn["time"]
                v["properties"]["shareUsageBytes"] = sn["usage"]
                return {"status": 200, "body": v}
            return {"status": 200, "body": _share_view(sh, acct, base, expand_snaps=(query.get("$expand") or "").lower() == "snapshots")}
        if method in ("PUT", "PATCH"):
            if method == "PATCH" and not sh:
                return _err(404, "ShareNotFound", f"The specified share '{name}' does not exist.")
            return _put_share(state, acct, base, name, payload, method)
        if method == "DELETE":
            if not sh or sh.get("_deleted"):
                return {"status": 204, "body": None}
            if sh["_snaps"] and (query.get("include") or "").lower() != "snapshots":
                return _err(409, "ShareHasSnapshots", "The share has snapshots. Delete them first or pass include=snapshots.")
            if sh["_lease"]["state"] == "Leased" and (payload or {}).get("leaseId") != sh["_lease"].get("id"):
                return _err(412, "LeaseIdMissing", "There is currently a lease on the share and no lease ID was specified in the request.")
            pol = _service(state, acct)["shareDeleteRetentionPolicy"]
            if pol.get("enabled") and (query.get("permanent") or "").lower() != "true":
                sh["_deleted"] = _now()
                sh["_retention_left"] = pol.get("days", 7)
            else:
                if (query.get("permanent") or "").lower() == "true" and pol.get("enabled") and not pol.get("allowPermanentDelete"):
                    return _err(409, "PermanentDeleteNotAllowed", "allowPermanentDelete is not enabled on the share delete retention policy.")
                shares.pop(name.lower())
            return {"status": 200, "body": None}
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if not sh:
        return _err(404, "ShareNotFound", f"The specified share '{name}' does not exist.")
    op = tail[0].lower()
    if op == "restore" and method == "POST":
        if not sh.get("_deleted"):
            return _err(409, "ShareNotDeleted", "The share is not in a soft-deleted state.")
        sh.pop("_deleted")
        sh["_modified"] = _now()
        return {"status": 200, "body": _share_view(sh, acct, base)}
    if sh.get("_deleted"):
        return _err(404, "ShareNotFound", f"The specified share '{name}' does not exist.")
    if op == "snapshot" and method == "POST":
        if len(sh["_snaps"]) >= 200:
            return _err(409, "TooManySnapshots", "A share can have at most 200 snapshots.")
        t = _now()
        sh["_snaps"].append({"time": t, "usage": _usage(sh), "tree": {k: dict(v) for k, v in sh["_tree"].items()}})
        return {"status": 201, "body": {"snapshotTime": t, "shareName": name}}
    if op == "snapshot" and method == "DELETE" and len(tail) == 2:
        before = len(sh["_snaps"])
        sh["_snaps"] = [s for s in sh["_snaps"] if s["time"] != tail[1]]
        return _err(404, "ShareSnapshotNotFound", "The specified share snapshot does not exist.") if len(sh["_snaps"]) == before else {"status": 200, "body": None}
    if op == "snapshots" and method == "GET":
        return {"status": 200, "body": {"value": [{"snapshotTime": s["time"], "usageBytes": s["usage"]} for s in sh["_snaps"]]}}
    if op == "lease" and method == "POST":
        return _lease(sh, payload)
    if op == "items":
        if query.get("snapshot") and method == "GET":
            sn = next((s for s in sh["_snaps"] if s["time"] == query["snapshot"]), None)
            if not sn:
                return _err(404, "ShareSnapshotNotFound", "The specified share snapshot does not exist.")
            frozen = dict(sh)
            frozen["_tree"] = sn["tree"]
            return _items(state, acct, frozen, method, tail[1:], payload, query)
        return _items(state, acct, sh, method, tail[1:], payload, query)
    return _err(404, "ResourceNotFound", f"Unknown share operation '{tail[0]}'.")


def expire_deleted(state, days_elapsed: int = 1):
    """Age soft-deleted shares (used by tests / a scheduler); permanently drops those past retention."""
    for rec in state.values():
        sa = rec.get("_files_shares") if isinstance(rec, dict) else None
        if not sa:
            continue
        for k in [k for k, s in sa.items() if s.get("_deleted")]:
            sa[k]["_retention_left"] = sa[k].get("_retention_left", 0) - days_elapsed
            if sa[k]["_retention_left"] <= 0:
                sa.pop(k)


# ── account-level properties (create wizard "Access protocols" / "Azure Files", Configuration "Large file shares") ──
def validate_account(existing, payload):
    """Validate largeFileSharesState / isNfsV3Enabled / isSftpEnabled on a storage-account PUT/PATCH. Returns an error
    body ``{"error": {...}}`` or ``None``."""
    props = (payload or {}).get("properties") or {}
    if not any(k in props for k in ("largeFileSharesState", "isNfsV3Enabled", "isSftpEnabled")):
        return None
    old = (existing or {}).get("properties") or {}
    kind = (payload or {}).get("kind") or (existing or {}).get("kind") or "StorageV2"
    sku = (((payload or {}).get("sku") or {}).get("name") or ((existing or {}).get("sku") or {}).get("name") or "Standard_LRS")
    merged = dict(old, **props)

    def bad(code, msg):
        return {"error": {"code": code, "message": msg}}
    if "largeFileSharesState" in props:
        st = props["largeFileSharesState"]
        if st not in ("Enabled", "Disabled"):
            return bad("InvalidRequestContent", "largeFileSharesState must be Enabled or Disabled.")
        if st == "Enabled" and not old.get("largeFileSharesState") == "Enabled":
            if kind == "FileStorage" or sku.lower().startswith("premium"):
                return bad("InvalidRequestContent", "Large file shares are always available on premium FileStorage accounts; the setting is not applicable.")
            if re.search(r"_ra", sku, re.I) or not re.match(r"^standard_(lrs|zrs|grs|gzrs)$", sku, re.I):
                return bad("InvalidRequestContent", "Large file shares require Standard LRS, ZRS, GRS or GZRS redundancy.")
        if st == "Disabled" and old.get("largeFileSharesState") == "Enabled":
            return bad("InvalidRequestContent", "Large file shares cannot be disabled once enabled.")
    if "isNfsV3Enabled" in props:
        if existing is not None and bool(old.get("isNfsV3Enabled")) != bool(props["isNfsV3Enabled"]):
            return bad("InvalidRequestContent", "NFS v3 can only be set when the storage account is created.")
        if props["isNfsV3Enabled"]:
            if not merged.get("isHnsEnabled"):
                return bad("InvalidRequestContent", "NFS v3 requires hierarchical namespace (isHnsEnabled) to be enabled.")
            if kind not in ("StorageV2", "BlockBlobStorage"):
                return bad("InvalidRequestContent", "NFS v3 requires a general-purpose v2 or premium block blob storage account.")
            if merged.get("supportsHttpsTrafficOnly", True):
                return bad("InvalidRequestContent", "NFS v3 requires 'secure transfer required' (supportsHttpsTrafficOnly) to be disabled.")
    if props.get("isSftpEnabled") and not merged.get("isHnsEnabled"):
        return bad("InvalidRequestContent", "SFTP requires hierarchical namespace (isHnsEnabled) to be enabled.")
    return None
