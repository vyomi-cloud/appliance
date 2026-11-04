"""Azure Storage Mover (Microsoft.StorageMover) -- control plane + a real cloud-to-cloud copy engine
(Nano / dev_server / unified-ingress core).

ARM resources: ``storageMovers/{n}``, ``.../endpoints/{e}``, ``.../projects/{p}``, ``.../projects/{p}/jobDefinitions/{j}``,
``.../jobDefinitions/{j}/startJob`` | ``stopJob`` and ``.../jobRuns[/{id}]``, ``.../agents/{a}``.

Endpoint types are validated like the real RP: ``AzureStorageBlobContainer`` (storageAccountResourceId + blobContainerName),
``AzureStorageSmbFileShare`` (storageAccountResourceId + fileShareName), ``NfsMount`` (host + export), ``SmbMount``
(host + shareName). Job definitions require ``copyMode`` Additive|Mirror, an existing source and an existing AZURE target
endpoint, and an ``agentName`` for on-premises (Nfs/Smb mount) sources. Targets may not be a source of the same job.

A job run really executes when BOTH endpoints are Azure endpoints that Vyomi hosts (Blob container <-> Blob container <->
Azure Files share): it walks the source (optionally under ``sourceSubpath``), copies new / changed bytes to ``targetSubpath``
(Additive), and in Mirror mode also deletes target files absent from the source, reporting scanned / transferred /
copied counters and per-file errors. A missing storage account / container / share fails the run with the real-style error.

NOT modelled: the on-premises migration agent (an Arc-enabled VM that mounts NFS / SMB shares) -- a run whose source is
an NFS or SMB mount ends ``Failed`` with ``NoAgentAvailable`` unless that is the only thing wrong; no bandwidth throttling /
schedules (agents' ``uploadLimitSchedule`` is stored, not applied); no ACL / metadata preservation beyond content type; AWS S3
multicloud sources.

Pure python, no framework imports. Functions return ``{"status": int, "body": ...}``.
"""
from __future__ import annotations

import base64
import datetime
import re
import uuid

try:
    from core import azure_blob_core as _blob
except ImportError:                                  # Nano flat module path
    try:
        import azure_blob_core as _blob               # type: ignore
    except ImportError:
        _blob = None

NAMESPACE = "Microsoft.StorageMover"
API_VERSION = "2024-07-01"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
ENDPOINT_TYPES = ("AzureStorageBlobContainer", "AzureStorageSmbFileShare", "NfsMount", "SmbMount")
AZURE_TYPES = ("AzureStorageBlobContainer", "AzureStorageSmbFileShare")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles(namespace, chain=None):
    return namespace.lower() == "microsoft.storagemover"


def _storage_account(state, rid):
    return state.get((rid or "").lower())


def _validate_endpoint(state, props):
    t = props.get("endpointType")
    if t not in ENDPOINT_TYPES:
        return f"endpointType must be one of {', '.join(ENDPOINT_TYPES)}."
    if t == "AzureStorageBlobContainer":
        need = ("storageAccountResourceId", "blobContainerName")
    elif t == "AzureStorageSmbFileShare":
        need = ("storageAccountResourceId", "fileShareName")
    elif t == "NfsMount":
        need = ("host", "export")
    else:
        need = ("host", "shareName")
    for n in need:
        if not props.get(n):
            return f"{n} is required for a {t} endpoint."
    if "storageAccountResourceId" in need:
        a = _storage_account(state, props["storageAccountResourceId"])
        if a is None or a.get("_type", "").lower() != "microsoft.storage/storageaccounts":
            return f"The storage account '{props['storageAccountResourceId']}' does not exist."
    if t == "NfsMount" and props.get("nfsVersion", "NFSauto") not in ("NFSauto", "NFSv3", "NFSv4"):
        return "nfsVersion must be NFSauto, NFSv3 or NFSv4."
    return None


def _children(state, parent_id, kind):
    pre = parent_id.lower() + "/" + kind + "/"
    return [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and "/" not in k[len(pre):]]


def _mk(rid, type_suffix, name, sub, rg, props, extra=None):
    rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/{type_suffix}", "properties": props,
           "systemData": {"createdAt": _now(), "lastModifiedAt": _now()},
           "_type": f"{NAMESPACE}/{type_suffix}", "_sub": sub, "_rg": rg}
    rec.update(extra or {})
    return rec


def dispatch(state, method, sub, rg, chain, payload, query, blob_store=None, base=""):
    """chain after 'providers/Microsoft.StorageMover'."""
    if not chain or chain[0].lower() != "storagemovers":
        return _err(404, "ResourceNotFound", "Unknown Microsoft.StorageMover resource type.")
    root = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NAMESPACE}/storageMovers"
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        rows = [_view(r) for r in state.values() if isinstance(r, dict) and r.get("_type", "").lower() == "microsoft.storagemover/storagemovers"
                and r.get("_sub") == sub and (rg is None or r.get("_rg", "").lower() == rg.lower())]
        return _ok({"value": rows})
    mover_id = f"{root}/{chain[1]}"
    mover = state.get(mover_id.lower())
    if len(chain) == 2:
        return _mover(state, method, sub, rg, chain[1], mover_id, mover, payload)
    if mover is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.StorageMover/storageMovers/{chain[1]}' was not found.")
    kind = chain[2].lower()
    rest = chain[3:]
    if kind in ("endpoints", "agents"):
        return _simple(state, method, sub, rg, mover_id, kind, rest, payload)
    if kind == "projects":
        return _projects(state, method, sub, rg, mover_id, rest, payload, blob_store)
    if kind == "jobruns" or kind == "jobs":
        return _err(404, "ResourceNotFound", "Job runs live under a job definition: projects/{p}/jobDefinitions/{j}/jobRuns.")
    return _err(404, "ResourceNotFound", f"Unknown storage mover sub-resource '{chain[2]}'.")


def _mover(state, method, sub, rg, name, rid, rec, payload):
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The Resource 'Microsoft.StorageMover/storageMovers/{name}' under resource group '{rg}' was not found.")
    if method in ("PUT", "PATCH"):
        if rec is None:
            if not NAME_RE.match(name):
                return _err(400, "InvalidResourceName", "Storage mover names are 1-64 characters: letters, digits, '-' and '_'.")
            if not (payload or {}).get("location"):
                return _err(400, "InvalidRequestContent", "location is required.")
            rec = _mk(rid, "storageMovers", name, sub, rg, {"provisioningState": "Succeeded"}, {"location": payload["location"], "tags": {}})
            state[rid.lower()] = rec
            status = 201
        else:
            status = 200
        p = (payload or {}).get("properties") or {}
        if "description" in p:
            if len(str(p["description"])) > 500:
                return _err(400, "InvalidRequestContent", "description is at most 500 characters.")
            rec["properties"]["description"] = p["description"]
        if isinstance((payload or {}).get("tags"), dict):
            rec["tags"] = payload["tags"]
        return _ok(_view(rec), status)
    if method == "DELETE":
        if rec is None:
            return {"status": 204, "body": None}
        pre = rid.lower() + "/"
        if any(k.startswith(pre) and r.get("_type", "").lower().endswith("/projects") for k, r in state.items() if isinstance(r, dict)):
            return _err(409, "Conflict", "The storage mover has projects. Delete the projects first.")
        for k in [k for k in state if k.startswith(pre)]:
            state.pop(k)
        state.pop(rid.lower())
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _simple(state, method, sub, rg, mover_id, kind, rest, payload):
    tname = "endpoints" if kind == "endpoints" else "agents"
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _children(state, mover_id, tname)]})
    name = rest[0]
    rid = f"{mover_id}/{tname}/{name}"
    rec = state.get(rid.lower())
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The {tname[:-1]} '{name}' was not found.")
    if method in ("PUT", "PATCH"):
        p = (payload or {}).get("properties") or {}
        if tname == "endpoints":
            if not NAME_RE.match(name):
                return _err(400, "InvalidResourceName", "Names are 1-64 characters: letters, digits, '-' and '_'.")
            merged = dict(rec["properties"], **p) if rec else dict(p)
            if rec and "endpointType" in p and p["endpointType"] != rec["properties"].get("endpointType"):
                return _err(400, "InvalidRequestContent", "endpointType cannot be changed.")
            e = _validate_endpoint(state, merged)
            if e:
                return _err(400, "InvalidRequestContent", e)
            merged["provisioningState"] = "Succeeded"
            if rec is None:
                rec = _mk(rid, "storageMovers/endpoints", name, sub, rg, merged)
                state[rid.lower()] = rec
                return _ok(_view(rec), 201)
            rec["properties"] = merged
            return _ok(_view(rec))
        # agents are registered by the on-prem agent software; ARM only updates them
        if rec is None:
            return _err(404, "ResourceNotFound", "Agents are registered by the Storage Mover agent software running on-premises; none is registered under this name.")
        for k in ("description", "uploadLimitSchedule"):
            if k in p:
                rec["properties"][k] = p[k]
        return _ok(_view(rec))
    if method == "DELETE":
        if rec is None:
            return {"status": 204, "body": None}
        if tname == "endpoints":
            for j in state.values():
                if isinstance(j, dict) and j.get("_type", "").lower().endswith("/jobdefinitions") and j["id"].lower().startswith(mover_id.lower() + "/") \
                        and name in (j["properties"].get("sourceName"), j["properties"].get("targetName")):
                    return _err(409, "Conflict", f"The endpoint is referenced by job definition '{j['name']}'.")
        state.pop(rid.lower())
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _projects(state, method, sub, rg, mover_id, rest, payload, blob_store):
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _children(state, mover_id, "projects")]})
    pname = rest[0]
    prid = f"{mover_id}/projects/{pname}"
    proj = state.get(prid.lower())
    if len(rest) == 1:
        if method == "GET":
            return _ok(_view(proj)) if proj else _err(404, "ResourceNotFound", f"The project '{pname}' was not found.")
        if method in ("PUT", "PATCH"):
            if not NAME_RE.match(pname):
                return _err(400, "InvalidResourceName", "Names are 1-64 characters: letters, digits, '-' and '_'.")
            p = (payload or {}).get("properties") or {}
            if proj is None:
                proj = _mk(prid, "storageMovers/projects", pname, sub, rg, {"provisioningState": "Succeeded"})
                state[prid.lower()] = proj
                st = 201
            else:
                st = 200
            if "description" in p:
                proj["properties"]["description"] = p["description"]
            return _ok(_view(proj), st)
        if method == "DELETE":
            if proj is None:
                return {"status": 204, "body": None}
            if _children(state, prid, "jobDefinitions"):
                return _err(409, "Conflict", "The project has job definitions. Delete them first.")
            state.pop(prid.lower())
            return _ok(None)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if proj is None:
        return _err(404, "ResourceNotFound", f"The project '{pname}' was not found.")
    if rest[1].lower() != "jobdefinitions":
        return _err(404, "ResourceNotFound", f"Unknown project sub-resource '{rest[1]}'.")
    return _jobdefs(state, method, sub, rg, mover_id, prid, rest[2:], payload, blob_store)


def _jobdefs(state, method, sub, rg, mover_id, prid, rest, payload, blob_store):
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _children(state, prid, "jobDefinitions")]})
    jname = rest[0]
    jrid = f"{prid}/jobDefinitions/{jname}"
    job = state.get(jrid.lower())
    if len(rest) == 1:
        if method == "GET":
            return _ok(_view(job)) if job else _err(404, "ResourceNotFound", f"The job definition '{jname}' was not found.")
        if method in ("PUT", "PATCH"):
            if not NAME_RE.match(jname):
                return _err(400, "InvalidResourceName", "Names are 1-64 characters: letters, digits, '-' and '_'.")
            p = dict(job["properties"]) if job else {}
            p.update((payload or {}).get("properties") or {})
            if p.get("copyMode") not in ("Additive", "Mirror"):
                return _err(400, "InvalidRequestContent", "copyMode must be Additive or Mirror.")
            src = state.get(f"{mover_id}/endpoints/{p.get('sourceName')}".lower())
            tgt = state.get(f"{mover_id}/endpoints/{p.get('targetName')}".lower())
            if src is None:
                return _err(400, "InvalidRequestContent", f"The source endpoint '{p.get('sourceName')}' does not exist in this storage mover.")
            if tgt is None:
                return _err(400, "InvalidRequestContent", f"The target endpoint '{p.get('targetName')}' does not exist in this storage mover.")
            if tgt["properties"]["endpointType"] not in AZURE_TYPES:
                return _err(400, "InvalidRequestContent", "The target endpoint must be an Azure Storage endpoint.")
            if src["properties"]["endpointType"] in ("NfsMount", "SmbMount") and not p.get("agentName"):
                return _err(400, "InvalidRequestContent", "agentName is required when the source is an on-premises mount.")
            if p.get("agentName") and state.get(f"{mover_id}/agents/{p['agentName']}".lower()) is None and src["properties"]["endpointType"] in ("NfsMount", "SmbMount"):
                return _err(400, "InvalidRequestContent", f"The agent '{p['agentName']}' is not registered with this storage mover.")
            p.setdefault("provisioningState", "Succeeded")
            if job is None:
                job = _mk(jrid, "storageMovers/projects/jobDefinitions", jname, sub, rg, p, {"_runs": []})
                state[jrid.lower()] = job
                return _ok(_view(job), 201)
            job["properties"] = p
            return _ok(_view(job))
        if method == "DELETE":
            if job is None:
                return {"status": 204, "body": None}
            if any(r["properties"]["status"] in ("Queued", "Started", "Running") for r in job["_runs"]):
                return _err(409, "Conflict", "The job definition has a running job.")
            state.pop(jrid.lower())
            return _ok(None)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if job is None:
        return _err(404, "ResourceNotFound", f"The job definition '{jname}' was not found.")
    act = rest[1].lower()
    if act == "startjob" and method == "POST":
        run = _run_job(state, mover_id, job, blob_store)
        return _ok({"jobRunResourceId": run["id"]})
    if act == "stopjob" and method == "POST":
        live = [r for r in job["_runs"] if r["properties"]["status"] in ("Queued", "Started", "Running")]
        if not live:
            return _err(409, "Conflict", "There is no running job to stop.")
        live[-1]["properties"]["status"] = "Canceled"
        return _ok({"jobRunResourceId": live[-1]["id"]})
    if act == "jobruns" and method == "GET":
        if len(rest) == 2:
            return _ok({"value": [dict(r) for r in reversed(job["_runs"])]})
        r = next((x for x in job["_runs"] if x["name"] == rest[2]), None)
        return _ok(dict(r)) if r else _err(404, "ResourceNotFound", f"Job run '{rest[2]}' was not found.")
    return _err(404, "ResourceNotFound", f"Unknown job definition operation '{rest[1]}'.")


# ── copy engine ──────────────────────────────────────────────────────────────
def _acct_name(rid):
    return rid.rstrip("/").rsplit("/", 1)[-1].lower()


class _Side:
    """A read/write view over a Blob container or an Azure Files share."""

    def __init__(self, state, ep, blob_store, subpath):
        self.p, self.state, self.store = ep["properties"], state, blob_store
        self.sub = subpath.strip("/")
        self.acct = _acct_name(self.p["storageAccountResourceId"])
        self.kind = self.p["endpointType"]
        self.err = None
        if self.kind == "AzureStorageBlobContainer":
            if blob_store is None:
                self.err = ("StorageUnavailable", "No Blob store is attached to this Storage Mover.")
                return
            self.key = f"{self.acct}/{self.p['blobContainerName']}"
            if not blob_store.container_exists(self.key):
                self.err = ("ContainerNotFound", f"The container '{self.p['blobContainerName']}' does not exist in storage account '{self.acct}'.")
        else:
            acct = state.get(self.p["storageAccountResourceId"].lower())
            shares = (acct or {}).get("_files_shares", {})
            self.share = shares.get(self.p["fileShareName"].lower())
            if self.share is None or self.share.get("_deleted"):
                self.err = ("ShareNotFound", f"The file share '{self.p['fileShareName']}' does not exist in storage account '{self.acct}'.")

    def _full(self, rel):
        return (self.sub + "/" + rel).strip("/") if self.sub else rel

    def listing(self):
        out = {}
        if self.kind == "AzureStorageBlobContainer":
            for name, entry in self.store.container_blobs(self.key).items():
                if self.sub and not (name == self.sub or name.startswith(self.sub + "/")):
                    continue
                rel = name[len(self.sub) + 1:] if self.sub and name != self.sub else name
                if name.endswith("/") or name.endswith(".vyomi-container-keep"):
                    continue
                out[rel] = (_blob._entry_bytes(self.store, self.key, name, entry), entry.get("content_type") or entry.get("content-type"))
        else:
            for path, f in self.share["_tree"].items():
                if f["type"] != "file":
                    continue
                if self.sub and not path.startswith(self.sub + "/"):
                    continue
                out[path[len(self.sub) + 1:] if self.sub else path] = (base64.b64decode(f["_b64"]), f.get("contentType"))
        return out

    def write(self, rel, data, ctype):
        full = self._full(rel)
        if self.kind == "AzureStorageBlobContainer":
            r = _blob.dispatch(self.store, "PUT", f"/{self.p['blobContainerName']}/{full}", {},
                               {"x-ms-blob-type": "BlockBlob", "content-type": ctype or "application/octet-stream"}, data, account=self.acct)
            if r.status >= 300:
                raise ValueError(f"write failed ({r.status})")
        else:
            tree = self.share["_tree"]
            parts = full.split("/")
            for i in range(1, len(parts)):
                d = "/".join(parts[:i])
                tree.setdefault(d, {"type": "directory", "modified": _now()})
            used = sum(f.get("size", 0) for f in tree.values() if f["type"] == "file") - tree.get(full, {}).get("size", 0)
            if used + len(data) > self.share["properties"]["shareQuota"] * 1024 ** 3:
                raise ValueError("ShareSizeLimitReached: the share is full")
            tree[full] = {"type": "file", "_b64": base64.b64encode(data).decode(), "size": len(data), "modified": _now(),
                          "contentType": ctype or "application/octet-stream"}

    def delete(self, rel):
        full = self._full(rel)
        if self.kind == "AzureStorageBlobContainer":
            _blob.dispatch(self.store, "DELETE", f"/{self.p['blobContainerName']}/{full}", {}, {}, b"", account=self.acct)
        else:
            self.share["_tree"].pop(full, None)


def _run_job(state, mover_id, job, blob_store):
    p = job["properties"]
    rid = f"{job['id']}/jobRuns/{uuid.uuid4()}"
    counters = {"scannedFiles": 0, "scannedDirectories": 0, "scannedBytes": 0, "transferredFiles": 0, "transferredBytes": 0,
                "copiedBytes": 0, "skippedFiles": 0, "deletedFiles": 0, "errors": []}
    status, summary = "Succeeded", None
    start = _now()
    src_ep = state[f"{mover_id}/endpoints/{p['sourceName']}".lower()] if f"{mover_id}/endpoints/{p['sourceName']}".lower() in state else None
    tgt_ep = state[f"{mover_id}/endpoints/{p['targetName']}".lower()] if f"{mover_id}/endpoints/{p['targetName']}".lower() in state else None
    if src_ep is None or tgt_ep is None:
        status, summary = "Failed", {"code": "EndpointNotFound", "message": "A source or target endpoint was deleted after the job definition was created."}
    elif src_ep["properties"]["endpointType"] in ("NfsMount", "SmbMount"):
        status, summary = "Failed", {"code": "NoAgentAvailable", "message": f"The source is an on-premises {src_ep['properties']['endpointType']}; "
                                     "Vyomi has no Storage Mover agent that can mount it."}
    else:
        src = _Side(state, src_ep, blob_store, p.get("sourceSubpath") or "")
        tgt = _Side(state, tgt_ep, blob_store, p.get("targetSubpath") or "")
        bad = src.err or tgt.err
        if bad:
            status, summary = "Failed", {"code": bad[0], "message": bad[1]}
        else:
            mirror = p.get("copyMode") == "Mirror"
            s_files, t_files = src.listing(), tgt.listing()
            counters["scannedDirectories"] = len({r.rsplit("/", 1)[0] for r in s_files if "/" in r})
            for rel, (data, ctype) in sorted(s_files.items()):
                counters["scannedFiles"] += 1
                counters["scannedBytes"] += len(data)
                if rel in t_files and t_files[rel][0] == data:
                    counters["skippedFiles"] += 1
                    continue
                try:
                    tgt.write(rel, data, ctype)
                    counters["transferredFiles"] += 1
                    counters["transferredBytes"] += len(data)
                    counters["copiedBytes"] += len(data)
                except ValueError as e:
                    counters["errors"].append({"path": rel, "message": str(e)})
            if mirror:
                for rel in sorted(set(t_files) - set(s_files)):
                    tgt.delete(rel)
                    counters["deletedFiles"] += 1
            if counters["errors"]:
                status = "Failed"
                summary = {"code": "CopyFailed", "message": f"{len(counters['errors'])} file(s) failed to copy."}
    props = {"status": status, "scanStatus": "Succeeded" if status != "Failed" or counters["scannedFiles"] else "Failed",
             "agentName": p.get("agentName"), "sourceName": p.get("sourceName"), "targetName": p.get("targetName"),
             "jobDefinitionName": job["name"], "startTime": start, "executionStartTime": start, "executionEndTime": _now(),
             "lastStatusUpdate": _now(), "scannedItemsCount": counters["scannedFiles"] + counters["scannedDirectories"],
             "transferredItemsCount": counters["transferredFiles"], "totalBytes": counters["scannedBytes"], "transferredBytes": counters["transferredBytes"],
             "bytesExcluded": 0, "itemsExcluded": counters["skippedFiles"], "itemsFailed": len(counters["errors"]),
             "itemsDeleted": counters["deletedFiles"], "counters": counters, "error": summary}
    run = {"id": rid, "name": rid.rsplit("/", 1)[-1], "type": f"{NAMESPACE}/storageMovers/projects/jobDefinitions/jobRuns", "properties": props}
    job["_runs"].append(run)
    job["properties"]["latestJobRunName"] = run["name"]
    job["properties"]["latestJobRunStatus"] = status
    job["properties"]["latestJobRunResourceId"] = rid
    return run
