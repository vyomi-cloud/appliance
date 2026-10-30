"""GCP console adapter — the in-browser analogue of aws_core_adapter for GCP.

The GCP console drives every service through the registry's generic CRUD
(`_resource_dispatch` → List/Create/Get/Delete on a catalog service key). This
module routes those 7 services to the PROVEN GCP conformance cores (the same
cores the relay serves over the native google-cloud-* wire), so the console and
the SDKs share one implementation. Each service keeps its own in-tab store
singleton (the console's source of truth for that tab).

Pure stdlib + the cores → loads under Pyodide. Returns the registry envelope:
List → {ok, items:[record,...]}; Create/Get → {ok, **record}; Delete → {ok, code}.
"""
from __future__ import annotations

import base64
import json

from core import gcp_storage_core as _gcs
from core.object_store import InMemoryObjectStore
from core import gcp_firestore_core as _fs
from core.gcp_firestore_core import FirestoreStore
from core import gcp_kms_core as _kms
from core.kms_keystore import InMemoryKeyStore
from core import gcp_secretmanager_core as _sec
from core.kv_store import InMemoryKvStore
from core import gcp_pubsub_core as _ps
from core.messaging_store import InMemoryMessagingStore
from core import gcp_iam_core as _iam
from core.iam_store import InMemoryIamStore
from core import gcp_cloudsql_core as _sql
from core import gcp_cloudscheduler_core as _sched
from core import gcp_container_core as _gke
from core import gcp_iamcredentials_core as _iamc
from core import gcp_redis_core as _redis
from core import gcp_monitoring_core as _mon
from core import gcp_artifactregistry_core as _ar
from core.sql_store import InMemorySqlStore

from core import gcp_project as _gproj
PROJ = _gproj.NANO_PROJECT["projectId"]   # the console's project — the one `gcloud projects list` shows
LOC = "global"         # default KMS location
RING = "demo"          # default KMS key ring
COLL = "console"       # default Firestore collection

# Draw every store from the SHARED nano_registry (keyed gcs/gcp_* there) so the GCP
# console (UI) and the native-wire relay (CLI/SDK/curl via AwsWireRouter) read/write
# ONE store per service — and nano_persist captures them for reload/cross-context sync.
from core import nano_registry as _reg
_R = _reg.get()
_STORES = {
    "storage":       _R["gcs"],
    "firestore":     _R["gcp_fs"],
    "kms":           _R["gcp_kms"],
    "secretmanager": _R["gcp_sec"],
    "pubsub":        _R["gcp_msg"],
    "iam":           _R["gcp_iam"],
    "cloudsql":      _R["gcp_sql"],
    "cloudscheduler": _R["gcp_sched"],
    "container":     _R["gcp_gke"],
    "iamcredentials": _R["gcp_iamc"],
    "redis":         _R["gcp_redis"],
    "monitoring":    _R["gcp_mon"],
    "artifactregistry": _R["gcp_ar"],
}

_MOD = {
    "storage": _gcs, "firestore": _fs, "kms": _kms, "secretmanager": _sec,
    "pubsub": _ps, "iam": _iam, "cloudsql": _sql, "cloudscheduler": _sched, "container": _gke, "iamcredentials": _iamc, "redis": _redis, "monitoring": _mon, "artifactregistry": _ar,
}


def _call(svc, method, path, query=None, body=b""):
    """Dispatch a native GCP-wire request to a service's core; return (status, parsed_json)."""
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    elif isinstance(body, str):
        body = body.encode()
    r = _MOD[svc].dispatch(_STORES[svc], method, path, query or {},
                           {"content-type": "application/json"}, body or b"")
    try:
        parsed = json.loads(r.body.decode("utf-8")) if r.body else {}
    except Exception:
        parsed = {}
    return r.status, parsed


def _items(parsed):
    for k in ("items", "documents", "cryptoKeys", "secrets", "topics",
              "subscriptions", "accounts", "keyRings", "databases"):
        if isinstance(parsed.get(k), list):
            return parsed[k]
    for v in parsed.values():
        if isinstance(v, list):
            return v
    return []


def _short(nm):
    return nm.rsplit("/", 1)[-1] if isinstance(nm, str) and "/" in nm else nm


def _rec(d, name_field="name"):
    """Flatten a native resource into a console record with a short `name`."""
    out = dict(d) if isinstance(d, dict) else {"name": d}
    full = out.get("name", "")
    if isinstance(full, str) and "/" in full:
        out["resourceName"] = full
        out["name"] = _short(full)
    if name_field != "name" and name_field in out:
        out.setdefault("name", out[name_field])
    return out


def _ok_list(svc, name_field="name"):
    st, parsed = _call(svc, "GET", _COLLECTION[svc]())
    return {"ok": True, "items": [_rec(x, name_field) for x in _items(parsed)]}


# ── per-service native path builders ──────────────────────────────────────
_P = f"/v1/projects/{PROJ}"
_COLLECTION = {
    "storage": lambda: "/storage/v1/b",
    "firestore": lambda: f"{_P}/databases/(default)/documents/{COLL}",
    "kms": lambda: f"{_P}/locations/{LOC}/keyRings/{RING}/cryptoKeys",
    "secretmanager": lambda: f"{_P}/secrets",
    "pubsub": lambda: f"{_P}/topics",
    "iam": lambda: f"{_P}/serviceAccounts",
    "cloudsql": lambda: f"/sql/v1beta4/projects/{PROJ}/instances",
}


def _ensure_keyring():
    _call("kms", "POST", f"{_P}/locations/{LOC}/keyRings",
          {"keyRingId": RING}, {})   # idempotent; 409 if it exists — ignored


# ── Durable sub-resource store (child lists NOT natively backed by a core) ──
# Cloud SQL users/backups/replicas, Pub/Sub schemas, IAM service-account members
# & keys, etc. have no dedicated conformance core. We hold them in a plain public
# dict attached to an EXISTING registry store (gcp_iam) so nano_persist captures
# + restores + cross-tab-syncs them on the SAME IndexedDB path as S3/DynamoDB —
# i.e. they survive a reload and are the console's durable source of truth. Keyed
# "service/parent/childType" → {childName: record}. (gcp_iam is a plain object,
# no __slots__, and the attr is public + JSON-safe, so _public_state captures it.)
def _sub_root():
    st = _STORES["iam"]
    d = getattr(st, "nano_sub", None)
    if not isinstance(d, dict):
        d = {}
        st.nano_sub = d
    return d


def _sub_coll(service, parent, child_type, create=False):
    root = _sub_root()
    key = f"{service}/{parent}/{child_type}"
    coll = root.get(key)
    if coll is None and create:
        coll = {}
        root[key] = coll
    return coll if coll is not None else {}


def _sub_list(service, parent, child_type):
    return {"ok": True, "items": list(_sub_coll(service, parent, child_type).values())}


def _sub_create(service, parent, child_type, rec):
    coll = _sub_coll(service, parent, child_type, create=True)
    nm = str(rec.get("name") or "").strip()
    if not nm:
        return {"ok": False, "code": "InvalidName"}
    if nm in coll:
        return {"ok": False, "code": "AlreadyExists", "name": nm}
    coll[nm] = rec
    return {"ok": True, **rec}


def _sub_delete(service, parent, child_type, child):
    coll = _sub_coll(service, parent, child_type, create=True)
    existed = coll.pop(str(child), None) is not None
    return {"ok": existed, "code": None if existed else "NotFound", "name": child}


def _sched_invoke(kind, d):
    """Cloud Scheduler firing a pubsub target: publish into the Pub/Sub core."""
    if kind != "pubsub":
        return True
    msg = {"messages": [{"data": d.get("data", ""), "attributes": d.get("attributes") or {}}]}
    st, _ = _call("pubsub", "POST", "/v1/%s:publish" % d["topicName"], {}, msg)
    return True if st < 300 else "Topic %s not found." % d["topicName"]


def _sched_op(operation, name, body):
    """Cloud Scheduler console CRUD + pause/resume/run over core/gcp_cloudscheduler_core."""
    store = _STORES["cloudscheduler"]

    def find(nm):
        for full in store.jobs:
            if full.rsplit("/", 1)[-1] == nm or full == nm:
                return full
        return None

    def run(method, full, verb="", query=None, payload=None):
        path = "/v1/" + full + (":" + verb if verb else "")
        r = _sched.dispatch(store, method, path, query or {}, {}, json.dumps(payload).encode() if payload is not None else b"",
                            invoker=_sched_invoke)
        try:
            return r.status, json.loads(r.body or b"{}")
        except Exception:
            return r.status, {}

    if operation == "List":
        return {"ok": True, "items": _sched.list_all(store)}
    if operation == "Create":
        job = _sched.job_from_form(body, PROJ)
        loc = job["name"].split("/")[3]
        st, p = run("POST", "projects/%s/locations/%s/jobs" % (PROJ, loc), payload=job)
        if st < 300:
            return {"ok": True, **_sched.console_view(store.jobs[job["name"]])}
        return {"ok": False, "code": p.get("error", {}).get("status", "CreateFailed"),
                "message": p.get("error", {}).get("message", ""), "name": body.get("name")}
    full = find(name)
    if not full:
        return {"ok": False, "code": "NotFound", "name": name}
    if operation == "Get":
        run("GET", full)
        return {"ok": True, **_sched.console_view(store.jobs[full])}
    if operation == "Delete":
        st, _ = run("DELETE", full)
        return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
    if operation == "Update":
        upd = {k: body[k] for k in ("description", "schedule", "timeZone") if body.get(k)}
        st, p = run("PATCH", full, query={"updateMask": ",".join(upd)}, payload=upd)
        return {"ok": True, **_sched.console_view(store.jobs[full])} if st < 300 else \
            {"ok": False, "code": p.get("error", {}).get("status", "UpdateFailed"), "name": name}
    if operation in ("Pause", "Resume", "Run"):
        st, p = run("POST", full, operation.lower())
        return {"ok": True, **_sched.console_view(store.jobs[full])} if st < 300 else \
            {"ok": False, "code": p.get("error", {}).get("status", "ActionFailed"), "name": name}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": "cloudscheduler"}


def _gke_op(operation, name, body):
    """Kubernetes Engine console CRUD (+ resize/upgrade) over core/gcp_container_core."""
    store = _STORES["container"]

    def find(nm):
        for full in store.clusters:
            if full.rsplit("/", 1)[-1] == nm or full == nm:
                return full
        return None

    def run(method, path, query=None, payload=None):
        r = _gke.dispatch(store, method, "/v1/" + path, query or {}, {}, json.dumps(payload).encode() if payload is not None else b"")
        try:
            return r.status, json.loads(r.body or b"{}")
        except Exception:
            return r.status, {}

    if operation == "List":
        return {"ok": True, "items": _gke.list_all(store)}
    if operation == "Create":
        req = _gke.job_from_form(body, PROJ)
        st, p = run("POST", req["parent"] + "/clusters", payload={"cluster": req["cluster"]})
        if st < 300:
            return {"ok": True, **_gke.view_by_name(store, _gke.cluster_name(PROJ, req["location"], req["cluster"]["name"]))}
        return {"ok": False, "code": p.get("error", {}).get("status", "CreateFailed"),
                "message": p.get("error", {}).get("message", ""), "name": body.get("name")}
    full = find(name)
    if not full:
        return {"ok": False, "code": "NotFound", "name": name}
    if operation == "Get":
        return {"ok": True, **_gke.view_by_name(store, full)}
    if operation == "Delete":
        st, _ = run("DELETE", full)
        return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
    if operation in ("Resize", "Upgrade"):
        if operation == "Resize":
            pool = (store.clusters[full]["nodePools"] or [{"name": "default-pool"}])[0]["name"]
            st, p = run("POST", "%s/nodePools/%s:setSize" % (full, pool), payload={"nodeCount": int(body.get("nodeCount", 3))})
        else:
            st, p = run("PUT", full, payload={"update": {"desiredMasterVersion": body.get("version") or "latest"}})
        return {"ok": True, **_gke.view_by_name(store, full)} if st < 300 else \
            {"ok": False, "code": p.get("error", {}).get("status", "ActionFailed"), "name": name}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": "container"}


def _iamc_resolve(ident):
    """IAM Credentials: service-account email / uniqueId -> email (IAM core store) or None."""
    for email, sa in (getattr(_STORES["iam"], "gcp_service_accounts", None) or {}).items():
        if ident in (email, sa.get("uniqueId")):
            return email
    return None


def _iamc_op(operation, name, body):
    """IAM Credentials console grid (the issued-credentials log) over core/gcp_iamcredentials_core."""
    store = _STORES["iamcredentials"]
    if operation == "List":
        return {"ok": True, "items": _iamc.list_all(store)}
    if operation == "Create":
        sa = _iamc.form_service_account(body)
        if "@" in sa and not _iamc_resolve(sa):   # the console issues for the account, creating it if absent
            acct, _, rest = sa.partition("@")
            _call("iam", "POST", "/v1/projects/%s/serviceAccounts" % rest.split(".")[0], {}, {"accountId": acct})
        try:
            out = {"ok": True, **_iamc.issue_from_form(store, body, _iamc_resolve)}
            try:   # the Metrics tab reads events by credential id (the dispatcher logs under the account)
                from core import nano_events
                nano_events.record(provider="gcp", service="iamcredentials", resource=str(out.get("id") or ""),
                                   action="Create", status="ok", detail="gcp/iamcredentials: Create %s" % out.get("id"))
            except Exception:
                pass
            return out
        except _iamc._E as e:
            return {"ok": False, "code": e.gcp_status, "message": e.message, "name": body.get("serviceAccount")}
    rec = store.issued.get(name)
    if rec is None:
        return {"ok": False, "code": "NotFound", "name": name}
    if operation == "Get":
        return {"ok": True, **_iamc.console_view(rec)}
    if operation == "Delete":
        del store.issued[name]
        return {"ok": True, "code": None, "name": name}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": "iamcredentials"}


def _redis_op(operation, name, body):
    """Memorystore for Redis console CRUD (+ resize/failover) over core/gcp_redis_core."""
    store = _STORES["redis"]

    def find(nm):
        for full in store.instances:
            if full.rsplit("/", 1)[-1] == nm or full == nm:
                return full
        return None

    def run(method, path, query=None, payload=None):
        r = _redis.dispatch(store, method, "/v1/" + path, query or {}, {}, json.dumps(payload).encode() if payload is not None else b"")
        try:
            return r.status, json.loads(r.body or b"{}")
        except Exception:
            return r.status, {}

    if operation == "List":
        return {"ok": True, "items": _redis.list_all(store)}
    if operation == "Create":
        req = _redis.job_from_form(body, PROJ)
        st, p = run("POST", req["parent"] + "/instances", {"instanceId": req["instanceId"]}, req["instance"])
        if st < 300:
            return {"ok": True, **_redis.view_by_name(store, _redis.instance_name(PROJ, req["location"], req["instanceId"]))}
        return {"ok": False, "code": p.get("error", {}).get("status", "CreateFailed"),
                "message": p.get("error", {}).get("message", ""), "name": body.get("name")}
    full = find(name)
    if not full:
        return {"ok": False, "code": "NotFound", "name": name}
    if operation == "Get":
        return {"ok": True, **_redis.view_by_name(store, full)}
    if operation == "Delete":
        st, _ = run("DELETE", full)
        return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
    if operation in ("Resize", "Failover"):
        if operation == "Resize":
            st, p = run("PATCH", full, {"updateMask": "memorySizeGb"}, {"memorySizeGb": int(body.get("memorySizeGb", 1))})
        else:
            st, p = run("POST", full + ":failover", payload={"dataProtectionMode": "LIMITED_DATA_LOSS"})
        return {"ok": True, **_redis.view_by_name(store, full)} if st < 300 else \
            {"ok": False, "code": p.get("error", {}).get("status", "ActionFailed"), "name": name}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": "redis"}


def _console_view(svc, rec):
    """Fill the grid columns the real console shows for a core-backed resource from the
    resource's own fields / the API's creation defaults."""
    if not isinstance(rec, dict):
        return rec
    if svc == "kms":
        prim = rec.get("primary") or {}
        tmpl = rec.get("versionTemplate") or {}
        parts = str(rec.get("resourceName") or "").split("/")
        rec.setdefault("keyring", parts[parts.index("keyRings") + 1] if "keyRings" in parts else RING)
        rec.setdefault("algorithm", prim.get("algorithm") or tmpl.get("algorithm") or "GOOGLE_SYMMETRIC_ENCRYPTION")
        rec.setdefault("protection", prim.get("protectionLevel") or tmpl.get("protectionLevel") or "SOFTWARE")
        rec.setdefault("state", prim.get("state") or "ENABLED")
    elif svc == "secretmanager":
        repl = rec.get("replication")
        if isinstance(repl, dict):
            rec["replication"] = "automatic" if "automatic" in repl else "user-managed"
        rec.setdefault("replication", "automatic")
        rec.setdefault("created", rec.get("createTime", ""))
        if "latest_version" not in rec:
            _st, _vp = _call("secretmanager", "GET", f"{_P}/secrets/{rec.get('name', '')}/versions")
            _vs = [str(v.get("name", "")).rsplit("/", 1)[-1] for v in (_vp.get("versions", []) if isinstance(_vp, dict) else [])]
            rec["latest_version"] = max(_vs, key=lambda x: int(x) if x.isdigit() else 0) if _vs else "No versions"
    elif svc == "firestore":
        rec.setdefault("type", "FIRESTORE_NATIVE")
        rec.setdefault("locationId", "us-central1")
        rec.setdefault("concurrencyMode", "OPTIMISTIC")
        rec.setdefault("deleteProtectionState", "DELETE_PROTECTION_DISABLED")
    return rec


def _mon_op(operation, name, body):
    """Cloud Monitoring console grid (alert policies) over core/gcp_monitoring_core."""
    store = _STORES["monitoring"]

    def find(nm):
        for full in store.alert_policies:
            if full.rsplit("/", 1)[-1] == nm or full == nm:
                return full
        return None

    if operation == "List":
        return {"ok": True, "items": _mon.list_all(store)}
    if operation == "Create":
        try:
            out = {"ok": True, **_mon.create_from_form(store, body, PROJ)}
        except _mon._E as e:
            return {"ok": False, "code": e.gcp_status, "message": e.message, "name": body.get("name")}
        try:   # the Metrics tab reads events by policy id
            from core import nano_events
            # the detail view's `name` is the full resource path, the id is what the grid links on
            for res in {str(out.get("id") or ""), str(out.get("name") or "")} - {""}:
                nano_events.record(provider="gcp", service="monitoring", resource=res,
                                   action="Create", status="ok", detail="gcp/monitoring: Create %s" % out.get("id"))
        except Exception:
            pass
        return out
    full = find(name)
    if not full:
        return {"ok": False, "code": "NotFound", "name": name}
    pid = full.rsplit("/", 1)[-1]
    if operation == "Get":
        return {"ok": True, **_mon.console_view(store, store.alert_policies[full])}
    if operation == "Delete":
        del store.alert_policies[full]
        return {"ok": True, "code": None, "name": name}
    if operation in ("Update", "Enable", "Disable"):
        upd = {"enabled": operation == "Enable"} if operation != "Update" else \
            {k: body[k] for k in ("displayName", "enabled", "documentation", "severity") if k in body}
        try:
            _mon.patch_policy(store, PROJ, pid, upd, ",".join(upd))
        except _mon._E as e:
            return {"ok": False, "code": e.gcp_status, "message": e.message, "name": name}
        return {"ok": True, **_mon.console_view(store, store.alert_policies[full])}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": "monitoring"}


def resource_op(service, operation, name="", body=None):
    tab = tab_dispatch(service, operation, name, body)
    if tab is not None:
        return tab
    out = _resource_op(service, operation, name, body)
    if isinstance(out, dict) and service in ("kms", "firestore", "secretmanager"):
        if isinstance(out.get("items"), list) and operation == "List":
            out["items"] = [_console_view(service, x) for x in out["items"]]
        elif out.get("ok") and operation in ("Get", "Create"):
            _console_view(service, out)
    return out


def _resource_op(service, operation, name="", body=None):
    """Console CRUD → GCP core. Returns the registry _resource_dispatch envelope."""
    body = body or {}
    svc = service
    if svc == "cloudscheduler":
        return _sched_op(operation, name, body)
    if svc == "container":
        return _gke_op(operation, name, body)
    if svc == "iamcredentials":
        return _iamc_op(operation, name, body)
    if svc == "monitoring":
        return _mon_op(operation, name, body)
    if svc == "redis":
        return _redis_op(operation, name, body)
    rid = str(body.get("name") or body.get("accountId") or body.get("secretId")
              or body.get("topicId") or name or "").strip()

    # ---------------- STORAGE (GCS buckets) ----------------
    if svc == "storage":
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "POST", "/storage/v1/b", {}, {"name": rid})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"/storage/v1/b/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"/storage/v1/b/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "Update":   # settings edits (lifecycle/encryption/retention/…) → bucket PATCH
            st, p = _call(svc, "PATCH", f"/storage/v1/b/{name}", {}, body)
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "UpdateFailed", "name": name}
        # Objects inside a bucket (the GCS Objects browser: upload/list/delete) —
        # served by the SAME gcp_storage_core as the native google-cloud-storage SDK.
        if operation == "ListObjects":
            st, p = _call(svc, "GET", f"/storage/v1/b/{body.get('bucket','')}/o")
            items = p.get("items", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "objects": items, "items": items}
        if operation == "PutObject":
            raw = base64.b64decode(body.get("body_b64", "") or "")
            key = str(body.get("key") or "upload")
            bucket = str(body.get("bucket") or "")
            r = _MOD["storage"].dispatch(_STORES["storage"], "POST",
                f"/upload/storage/v1/b/{bucket}/o", {"uploadType": "media", "name": key},
                {"content-type": body.get("content_type", "application/octet-stream")}, raw)
            return {"ok": r.status < 300, "key": key, "size": len(raw)} if r.status < 300 \
                else {"ok": False, "code": "UploadFailed", "key": key, "status": r.status}
        if operation == "DeleteObject":
            from urllib.parse import quote
            st, _ = _call(svc, "DELETE",
                          f"/storage/v1/b/{body.get('bucket','')}/o/{quote(str(body.get('key','')), safe='')}")
            return {"ok": st < 300, "key": body.get("key"), "code": None if st < 300 else "NotFound"}

    # ---------------- FIRESTORE (projects.databases — the Admin API's databases) ----------------
    if svc == "firestore":
        base = f"{_P}/databases"
        if operation == "List":
            st, p = _call(svc, "GET", base)
            return {"ok": True, "items": [_rec(x) for x in (p.get("databases") or [])]}
        if operation == "ListDocuments":   # database Usage tab: the documents the database holds
            from core.gcp_firestore_core import _DbDocs, _doc_view
            db = _short(name) if name else "(default)"
            docs = [_doc_view("projects/%s/databases/%s/documents" % (PROJ, db), r, e)
                    for r, e in _DbDocs(_STORES["firestore"], db).all()]
            return {"ok": True, "documents": docs, "items": docs}
        if operation == "Create":
            st, p = _call(svc, "POST", base, {"databaseId": rid},
                          {k: body[k] for k in ("type", "concurrencyMode", "locationId", "appEngineIntegrationMode",
                                                "pointInTimeRecoveryEnablement", "deleteProtectionState") if body.get(k)})
            if st < 300:
                return {"ok": True, **_rec(p.get("response") or {})}
            err = (p or {}).get("error") or {}
            return {"ok": False, "code": err.get("status") or "AlreadyExists", "message": err.get("message", ""), "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, p = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else ((p or {}).get("error") or {}).get("status", "NotFound"), "name": name}
        if operation == "Update":   # databases.patch (delete protection, PITR, concurrency)
            st, p = _call(svc, "PATCH", f"{base}/{name}", {}, body)
            return {"ok": True, **_rec(p.get("response") or {})} if st < 300 else {"ok": False, "code": "UpdateFailed", "name": name}

    # ---------------- KMS (cryptoKeys under a default key ring) ----------------
    if svc == "kms":
        base = f"{_P}/locations/{LOC}/keyRings/{RING}/cryptoKeys"
        if operation == "List":
            _ensure_keyring()
            return _ok_list(svc)
        if operation == "Create":
            _ensure_keyring()
            st, p = _call(svc, "POST", base, {"cryptoKeyId": rid}, {"purpose": "ENCRYPT_DECRYPT"})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            # Cloud KMS keeps key material; drop it from the store for console UX.
            _STORES["kms"].drop_key(f"projects/{PROJ}/locations/{LOC}/keyRings/{RING}/cryptoKeys/{name}")
            return {"ok": True, "code": None, "name": name}
        if operation == "ListVersions":   # cryptoKeyVersions under a key
            st, p = _call(svc, "GET", f"{base}/{name}/cryptoKeyVersions")
            vs = p.get("cryptoKeyVersions", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "items": [_rec(v) for v in vs]}
        if operation == "CreateVersion":   # add a new cryptoKeyVersion (ENABLED)
            st, p = _call(svc, "POST", f"{base}/{name}/cryptoKeyVersions", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "CreateFailed", "name": name}
        if operation in ("DestroyVersion", "DisableVersion", "EnableVersion"):
            ver = str(body.get("name") or "")
            verb = operation[:-7].lower()   # Destroy/Disable/Enable
            st, p = _call(svc, "POST", f"{base}/{name}/cryptoKeyVersions/{ver}:{verb}", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "ActionFailed", "name": ver}

    # ---------------- SECRET MANAGER (secrets + a seeded version) ----------------
    if svc == "secretmanager":
        base = f"{_P}/secrets"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            try:   # the form's replication choice (automatic / user-managed regions)
                repl = _sec.replication_from_form(body)
            except _sec.SecretPatchError as e:
                return {"ok": False, "code": "INVALID_ARGUMENT", "message": e.message, "name": rid}
            st, p = _call(svc, "POST", base, {"secretId": rid},
                          {"replication": repl, **({"labels": body["labels"]} if isinstance(body.get("labels"), dict) and body["labels"] else {})})
            if st < 300:
                val = body.get("secret_value") or body.get("value")
                if val:   # a secret may be created empty; a version exists only once a value is added
                    _call(svc, "POST", f"{base}/{rid}:addVersion", {},
                          {"payload": {"data": base64.b64encode(str(val).encode()).decode()}})
                return {"ok": True, **_rec(p)}
            return {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "ListVersions":   # secret versions (live metadata)
            st, p = _call(svc, "GET", f"{base}/{name}/versions")
            vs = p.get("versions", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "items": [_rec(v) for v in vs]}
        if operation == "AddVersion":      # add a new secret version (payload data)
            data = body.get("value") or body.get("data") or "changeme"
            payload_b64 = base64.b64encode(str(data).encode()).decode()
            st, p = _call(svc, "POST", f"{base}/{name}:addVersion", {},
                          {"payload": {"data": payload_b64}})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AddFailed", "name": name}
        if operation in ("DestroyVersion", "DisableVersion", "EnableVersion"):
            ver = str(body.get("name") or "")
            # short form "projects/.../versions/5" or "5" — take trailing id
            ver = ver.rsplit("/", 1)[-1]
            verb = operation[:-7].lower()   # destroy/disable/enable
            st, p = _call(svc, "POST", f"{base}/{name}/versions/{ver}:{verb}", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "ActionFailed", "name": ver}

    # ---------------- PUB/SUB (topics) ----------------
    if svc == "pubsub":
        base = f"{_P}/topics"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "PUT", f"{base}/{rid}", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "ListAllSubscriptions":   # every subscription in the project
            st, p = _call(svc, "GET", f"{_P}/subscriptions")
            return {"ok": st < 300, "subscriptions": p.get("subscriptions", []) if isinstance(p, dict) else []}
        if operation == "ListSubscriptions":   # subscriptions attached to THIS topic
            topic_full = f"projects/{PROJ}/topics/{name}"
            st, p = _call(svc, "GET", f"{_P}/subscriptions")
            subs = p.get("subscriptions", []) if isinstance(p, dict) else []
            subs = [s for s in subs if s.get("topic") == topic_full]
            return {"ok": st < 300, "items": [_rec(s) for s in subs]}
        if operation == "ListAllSubscriptions":   # every subscription in the project
            st, p = _call(svc, "GET", f"{_P}/subscriptions")
            subs = [_rec(s) for s in (p.get("subscriptions", []) if isinstance(p, dict) else [])]
            return {"ok": st < 300, "subscriptions": subs, "items": subs}
        if operation == "CreateSubscription":
            sub_id = str(body.get("name") or body.get("subscriptionId") or "").strip()
            topic_full = f"projects/{PROJ}/topics/{name}"
            st, p = _call(svc, "PUT", f"{_P}/subscriptions/{sub_id}", {}, {"topic": topic_full})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "CreateFailed", "name": sub_id}

    # ---------------- IAM (service accounts) ----------------
    if svc == "iam":
        base = f"{_P}/serviceAccounts"
        if operation == "List":
            return _ok_list(svc, name_field="email")
        if operation == "Create":
            st, p = _call(svc, "POST", base, {},
                          {"accountId": rid, "serviceAccount": {"displayName": rid}})
            return {"ok": st < 300, **_rec(p, "email")} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p, "email")} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}

    # ---------------- ARTIFACT REGISTRY (repositories + packages/versions/tags/images) ----------------
    if svc == "artifactregistry":
        st_ = _STORES[svc]
        if operation == "List":
            return {"ok": True, "items": _ar.console_list(st_)}
        if operation == "Create":
            return _ar.console_create(st_, PROJ, {**body, "name": rid})
        if operation == "Get":
            full, repo = _ar.console_find(st_, name)
            return {"ok": True, **_ar.console_row(repo)} if repo else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            return _ar.console_delete(st_, name)
        if operation in ("ListPackages", "ListVersions", "ListTags", "ListImages"):
            return {"ok": True, "items": _ar.console_children(st_, name, operation[4:].lower())}
        if operation == "PushSample":
            return _ar.console_push_sample(st_, name, body)

    # ---------------- CLOUD SQL (instances) ----------------
    if svc == "cloudsql":
        base = f"/sql/v1beta4/projects/{PROJ}/instances"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "POST", base, {},
                          {"name": rid, "databaseVersion": body.get("databaseVersion", "POSTGRES_15"),
                           "settings": {"tier": body.get("tier", "db-f1-micro")}})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "ListDatabases":   # databases hosted on THIS instance
            st, p = _call(svc, "GET", f"{base}/{name}/databases")
            dbs = p.get("items", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "items": [_rec(d) for d in dbs]}
        if operation == "CreateDatabase":
            db = str(body.get("name") or body.get("database") or "").strip()
            st, p = _call(svc, "POST", f"{base}/{name}/databases", {}, {"name": db})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "CreateFailed", "name": db}
        if operation == "DeleteDatabase":
            # `name` is the parent instance (via the /sub/ route); body carries the child db.
            child = str(body.get("name") or "")
            st, _ = _call(svc, "DELETE", f"{base}/{name}/databases/{child}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": child}
        # users / backups / replicas — no Cloud SQL control-plane core; durable adapter store.
        if operation in ("ListUsers", "ListBackups", "ListReplicas"):
            return _sub_list(svc, name, operation[4:].lower())
        if operation == "CreateUser":
            return _sub_create(svc, name, "users",
                               {"name": rid, "host": body.get("host", "%"), "type": "BUILT_IN"})
        if operation == "DeleteUser":
            return _sub_delete(svc, name, "users", body.get("name"))
        if operation == "CreateBackup":
            import time as _t
            bid = str(body.get("name") or "").strip() or ("backup-" + str(int(_t.time())))
            return _sub_create(svc, name, "backups",
                               {"name": bid, "status": "SUCCESSFUL", "type": "ON_DEMAND"})
        if operation == "DeleteBackup":
            return _sub_delete(svc, name, "backups", body.get("name"))
        if operation == "CreateReplica":
            return _sub_create(svc, name, "replicas",
                               {"name": rid, "masterInstance": name, "status": "RUNNABLE"})
        if operation == "DeleteReplica":
            return _sub_delete(svc, name, "replicas", body.get("name"))

    # ---------------- PUB/SUB schemas (adapter-store child) ----------------
    if svc == "pubsub":
        if operation == "DeleteSubscription":
            sub_id = str(body.get("name") or "")
            st, _ = _call(svc, "DELETE", f"{_P}/subscriptions/{sub_id}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": sub_id}
        if operation == "ListSchemas":
            return _sub_list(svc, name, "schemas")
        if operation == "CreateSchema":
            return _sub_create(svc, name, "schemas",
                               {"name": rid, "type": body.get("type", "AVRO"), "topic": name})
        if operation == "DeleteSchema":
            return _sub_delete(svc, name, "schemas", body.get("name"))

    # ---------------- IAM members / keys (adapter-store children) ----------------
    if svc == "iam":
        if operation == "ListMembers":
            return _sub_list(svc, name, "members")
        if operation == "CreateMember":
            return _sub_create(svc, name, "members",
                               {"name": rid, "role": body.get("role", "roles/viewer")})
        if operation == "DeleteMember":
            return _sub_delete(svc, name, "members", body.get("name"))
        if operation == "ListKeys":
            return _sub_list(svc, name, "keys")
        if operation == "CreateKey":
            import time as _t, uuid as _u
            kid = str(body.get("name") or "").strip() or _u.uuid4().hex[:24]
            return _sub_create(svc, name, "keys",
                               {"name": kid, "keyType": "USER_MANAGED",
                                "validAfterTime": "now", "created": int(_t.time())})
        if operation == "DeleteKey":
            return _sub_delete(svc, name, "keys", body.get("name"))

    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": svc}


GCP_CORE_SERVICES = frozenset(_MOD.keys())


# ── Resource-detail tabs (/api/gcp/sub/{service}/{op}/{name}) ─────────────
# The same ops the offline appliance serves (providers/gcp_tabs_console.py), over the
# Nano engines: the cores for core-backed services, the generic ResourceStore record
# for compute / vpc / functions / apigateway / eventarc. Validation and the records
# no engine models on its own come from core/gcp_console_tabs.py (shared with offline).
from core import gcp_console_tabs as _T

_GENERIC_TAB_SERVICES = {"compute", "functions", "apigateway", "vpc", "eventarc"}
_CRUD = {"List", "Create", "Get", "Update", "Delete", "Start", "Stop", "Reboot", "Terminate"}


def _tab_err(e):
    body = {"ok": False, "code": e.code, "message": e.message}
    return {**body, "__http": {"status": e.status, "body": body}}


def _tab_root():
    return _sub_root()   # the durable nano_sub dict (persisted + cross-tab synced)


class _Generic:
    """A generic-store (ResourceStore) record of `svc`, fetched by name."""

    def __init__(self, resources, account, svc, name):
        self.r, self.account, self.svc, self.name = resources, account, svc, name

    def get(self):
        rec = self.r.get("gcp", self.account, self.svc, self.name) if self.r is not None else None
        if rec is None:
            raise _T.TabError(404, "NOT_FOUND", "The resource '%s' was not found" % self.name)
        return rec

    def update(self, patch):
        return self.r.update("gcp", self.account, self.svc, self.name, patch)


def _compute_tab(g, op, body):
    rec = g.get()
    if "networkInterfaces" not in rec:   # created before instances were described: fill once
        g.update({k: v for k, v in _T.describe_instance(rec, PROJ, "us-central1-a").items() if k not in rec})
        rec = g.get()
    name = str(rec.get("name") or g.name)
    v = _T.view_op("compute", op)
    if v:
        return {"ok": True, "item": _T.view("compute", v, rec)}
    if op == "SetMetadata":
        g.update({"metadata": {"items": _T.validate_metadata(body.get("items", []))}})
        return {"ok": True, "item": g.get()}
    if op == "SetMachineType":
        _T.check_stopped(rec.get("status"), "changing its machine type")
        from core import instance_catalog as _ic
        g.update({"machineType": _T.validate_machine_type(body.get("machineType"), list(_ic.GCP.keys()))})
        return {"ok": True, "item": g.get()}
    if op == "SetScheduling":
        g.update({"scheduling": _T.validate_scheduling(body, rec.get("scheduling"))})
        return {"ok": True, "item": g.get()}
    if op == "SetLabels":
        g.update({"labels": _T.validate_labels(body.get("labels", {}))})
        return {"ok": True, "item": g.get()}
    disks = list(rec.get("disks") or [])
    root = _tab_root()
    if op == "ListDisks":
        return {"ok": True, "items": [{"name": d.get("deviceName") or d.get("source"), "boot": bool(d.get("boot")),
                                       "sizeGb": str(d.get("diskSizeGb") or ""), "type": d.get("diskType") or "pd-balanced",
                                       "status": "READY", "autoDelete": bool(d.get("autoDelete")),
                                       "mode": d.get("mode") or "READ_WRITE",
                                       "sourceImage": _T.short(d.get("sourceImage") or "") or "None",
                                       "deviceName": d.get("deviceName")} for d in disks]}
    if op == "AttachDisk":
        taken = [d.get("deviceName") for d in disks] + [
            d.get("deviceName") for x in g.r.list("gcp", g.account, "compute") for d in (x.get("disks") or [])]
        spec = _T.disk_spec(body, name, taken)
        disks.append({"deviceName": spec["name"], "source": spec["name"], "boot": False, "autoDelete": spec["autoDelete"],
                      "mode": "READ_WRITE", "type": "PERSISTENT", "diskSizeGb": str(spec["sizeGb"]), "diskType": spec["type"]})
        g.update({"disks": disks})
        return {"ok": True, "name": spec["name"]}
    if op == "DetachDisk":
        dn = str(body.get("name") or "")
        d = next((x for x in disks if x.get("deviceName") == dn), None)
        if d is None:
            raise _T.TabError(404, "NOT_FOUND", "Disk '%s' is not attached to this instance." % dn)
        if d.get("boot"):
            raise _T.TabError(400, "INVALID_ARGUMENT", "The boot disk cannot be detached from a VM instance.")
        g.update({"disks": [x for x in disks if x is not d]})
        return {"ok": True, "name": dn}
    names = [d.get("deviceName") for d in disks]
    if op == "ListSnapshots":
        snaps = _T.list_children(root, "compute", "_project", "snapshots")
        return {"ok": True, "items": [x for x in snaps if x.get("sourceDisk") in names]}
    if op == "CreateSnapshot":
        existing = [x.get("name") for x in _T.list_children(root, "compute", "_project", "snapshots")]
        spec = _T.snapshot_spec(body, names, existing)
        d = next(x for x in disks if x.get("deviceName") == spec["sourceDisk"])
        _T.put_child(root, "compute", "_project", "snapshots",
                     {**spec, "status": "READY", "sizeGb": str(d.get("diskSizeGb") or ""), "storageLocations": "us",
                      "created": _T.now_iso()})
        return {"ok": True, "name": spec["name"]}
    if op == "DeleteSnapshot":
        sn = str(body.get("name") or "")
        x = _T.children(root, "compute", "_project", "snapshots").get(sn)
        if not x or x.get("sourceDisk") not in names:
            raise _T.TabError(404, "NOT_FOUND", "The resource 'snapshots/%s' was not found" % sn)
        _T.delete_child(root, "compute", "_project", "snapshots", sn)
        return {"ok": True, "name": sn}
    return None


def _storage_tab(name, op, body):
    st, b = _call("storage", "GET", "/storage/v1/b/%s" % name)
    if st >= 300:
        raise _T.TabError(404, "NOT_FOUND", "The specified bucket does not exist.")
    v = _T.view_op("storage", op)
    if v:
        return {"ok": True, "item": _T.view("storage", v, b)}
    if op == "LockRetention":
        st, out = _call("storage", "POST", "/storage/v1/b/%s/lockRetentionPolicy" % name, {}, {})
    else:
        patch = _T.storage_patch(op, body)
        if patch is None:
            return None
        st, out = _call("storage", "PATCH", "/storage/v1/b/%s" % name, {}, patch)
    if st >= 300:
        err = (out or {}).get("error") or {}
        raise _T.TabError(st, "INVALID_ARGUMENT" if st == 400 else "FAILED_PRECONDITION", err.get("message") or "Update failed")
    return {"ok": True, "item": out}


def _sql_tab(name, op, body):
    """Cloud SQL detail tabs over core/gcp_cloudsql_core (the Cloud SQL Admin engine)."""
    base = "/sql/v1beta4/projects/%s/instances/%s" % (PROJ, name)

    def call(method, path="", query=None, payload=None, ok=(200,)):
        st, out = _call("cloudsql", method, base + path, query or {}, payload if payload is not None else b"")
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "FAILED_PRECONDITION", err.get("message") or "Request failed")
        return out

    full = call("GET")
    op = op[0].lower() + op[1:]
    v = _T.view_op("cloudsql", op)
    if v:
        return {"ok": True, "item": _T.view("cloudsql", v, full)}
    patch = _T.sql_settings_patch(op, body, full.get("settings") or {})
    if patch is not None:
        call("PATCH", "", None, {"settings": patch})
        return {"ok": True, "item": call("GET")}
    if op == "listDatabases":
        return {"ok": True, "items": [{"name": d["name"], "charset": d.get("charset"), "collation": d.get("collation")}
                                      for d in call("GET", "/databases").get("items", [])]}
    if op == "createDatabase":
        call("POST", "/databases", None, {k: body[k] for k in ("name", "charset", "collation") if body.get(k)})
        return {"ok": True, "name": body.get("name")}
    if op == "deleteDatabase":
        call("DELETE", "/databases/%s" % body.get("name"))
        return {"ok": True, "name": body.get("name")}
    if op == "listUsers":
        return {"ok": True, "items": [{"name": u["name"], "host": u.get("host") or "", "type": u.get("type")}
                                      for u in call("GET", "/users").get("items", [])]}
    if op == "createUser":
        call("POST", "/users", None, body)
        return {"ok": True, "name": body.get("name")}
    if op == "deleteUser":
        call("DELETE", "/users", {"name": body.get("name", ""), "host": body.get("host", "")})
        return {"ok": True, "name": body.get("name")}
    if op == "setUserPassword":
        if not str(body.get("password") or ""):
            raise _T.TabError(400, "INVALID_ARGUMENT", "Invalid request: a password is required.")
        call("PUT", "/users", {"name": body.get("name", ""), "host": body.get("host", "")}, {"password": body["password"]})
        return {"ok": True, "name": body.get("name")}
    if op == "listBackups":
        return {"ok": True, "items": [{"id": b["id"], "type": b.get("type"), "status": b.get("status"),
                                       "description": b.get("description") or "", "windowStartTime": b.get("windowStartTime"),
                                       "location": b.get("location")} for b in call("GET", "/backupRuns").get("items", [])]}
    if op == "createBackup":
        call("POST", "/backupRuns", None, {"description": body.get("description") or ""})
        return {"ok": True}
    if op == "deleteBackup":
        call("DELETE", "/backupRuns/%s" % body.get("id"))
        return {"ok": True, "id": body.get("id")}
    if op == "listReplicas":
        st, lst = _call("cloudsql", "GET", "/sql/v1beta4/projects/%s/instances" % PROJ)
        reps = [r for r in (lst or {}).get("items", []) if r.get("masterInstanceName") == name]
        return {"ok": True, "items": [{"name": r["name"], "state": r.get("state"), "region": r.get("region"),
                                       "databaseVersion": r.get("databaseVersion"), "tier": r["settings"].get("tier"),
                                       "instanceType": r.get("instanceType")} for r in reps]}
    if op == "createReplica":
        rn = _T.validate_name(body.get("name"), "name")
        st, out = _call("cloudsql", "POST", "/sql/v1beta4/projects/%s/instances" % PROJ, {},
                        {"name": rn, "masterInstanceName": name, "settings": {"tier": (full.get("settings") or {}).get("tier")}})
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "FAILED_PRECONDITION", err.get("message") or "Create failed")
        return {"ok": True, "name": rn}
    if op in ("promoteReplica", "deleteReplica"):
        rn = str(body.get("name") or "")
        if rn not in (full.get("replicaNames") or []):
            raise _T.TabError(404, "NOT_FOUND", "%s is not a read replica of %s." % (rn, name))
        path = "/sql/v1beta4/projects/%s/instances/%s" % (PROJ, rn)
        if op == "promoteReplica":
            st, out = _call("cloudsql", "POST", path + "/promoteReplica")
        else:
            st, out = _call("cloudsql", "DELETE", path)
        if st >= 300:
            raise _T.TabError(st, "FAILED_PRECONDITION", ((out or {}).get("error") or {}).get("message") or "Failed")
        return {"ok": True, "name": rn}
    if op == "listOperations":
        st, out = _call("cloudsql", "GET", "/sql/v1beta4/projects/%s/operations" % PROJ, {"instance": name})
        return {"ok": True, "items": [{"operationType": o.get("operationType"), "status": o.get("status"),
                                       "insertTime": o.get("insertTime"), "endTime": o.get("endTime"), "user": o.get("user"),
                                       "name": o.get("name")} for o in (out or {}).get("items", [])]}
    if op == "listQueryInsights":
        return {"ok": True, "items": []}   # no query has run through this instance's Query Insights recorder
    return None


def _pubsub_tab(name, op, body):
    """Pub/Sub topic tabs over core/gcp_pubsub_core (topics.patch, schemas, subscriptions, publish/pull)."""
    topic = "projects/%s/topics/%s" % (PROJ, _short(name))

    def call(method, path, query=None, payload=None):
        st, out = _call("pubsub", method, "/v1/" + path, query or {}, payload if payload is not None else b"")
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "FAILED_PRECONDITION", err.get("message") or "Request failed")
        return out

    t = call("GET", topic)
    op = op[0].lower() + op[1:]
    v = _T.view_op("pubsub", op)
    if v:
        if v == "schema" and (t.get("schemaSettings") or {}).get("schema"):
            st, sc = _call("pubsub", "GET", "/v1/" + t["schemaSettings"]["schema"])
            t["schema"] = sc if st < 300 else None
        return {"ok": True, "item": _T.view("pubsub", v, t)}
    patch = _T.pubsub_topic_patch(op, body)
    if patch is not None:
        return {"ok": True, "item": call("PATCH", topic, None, {"topic": patch, "updateMask": ",".join(patch)})}
    if op == "listSchemas":
        return {"ok": True, "items": call("GET", "projects/%s/schemas" % PROJ).get("schemas", [])}
    if op == "createSchema":
        call("POST", "projects/%s/schemas" % PROJ, {"schemaId": body.get("name", "")},
             {"type": body.get("type"), "definition": body.get("definition")})
        return {"ok": True, "name": body.get("name")}
    if op in ("listSubscriptions", "listPullSubscriptions"):   # the Messages tab pulls from pull subscriptions
        items = []
        for sn in call("GET", topic + "/subscriptions").get("subscriptions", []):
            st, sub = _call("pubsub", "GET", "/v1/" + sn)
            if st < 300:
                items.append({"name": _short(sub["name"]), "ackDeadlineSeconds": sub.get("ackDeadlineSeconds", 10),
                              "messageRetentionDuration": sub.get("messageRetentionDuration") or "604800s",
                              "deliveryType": "Push" if (sub.get("pushConfig") or {}).get("pushEndpoint") else "Pull",
                              "retainAckedMessages": bool(sub.get("retainAckedMessages"))})
        if op == "listPullSubscriptions":
            items = [x for x in items if x["deliveryType"] == "Pull"]
        return {"ok": True, "items": items}
    if op == "createSubscription":
        sid = _T.validate_pubsub_id(body.get("name"))
        ack = int(body.get("ackDeadlineSeconds") or 10)
        if not 10 <= ack <= 600:
            raise _T.TabError(400, "INVALID_ARGUMENT", "The ack deadline must be between 10 and 600 seconds.")
        call("PUT", "projects/%s/subscriptions/%s" % (PROJ, sid), None, {"topic": topic, "ackDeadlineSeconds": ack})
        return {"ok": True, "name": sid}
    if op == "deleteSubscription":
        call("DELETE", "projects/%s/subscriptions/%s" % (PROJ, _short(body.get("name"))))
        return {"ok": True, "name": body.get("name")}
    if op == "publishMessage":
        data = str(body.get("data") or "")
        attrs = {str(k): str(v) for k, v in (body.get("attributes") or {}).items()}
        if not data and not attrs:
            raise _T.TabError(400, "INVALID_ARGUMENT", "A message needs data or at least one attribute.")
        out = call("POST", topic + ":publish", None,
                   {"messages": [{"data": base64.b64encode(data.encode()).decode(), "attributes": attrs}]})
        return {"ok": True, "messageIds": out.get("messageIds", [])}
    if op == "pullMessages":
        sub = "projects/%s/subscriptions/%s" % (PROJ, _short(body.get("subscription")))
        got = call("POST", sub + ":pull", None, {"maxMessages": max(1, min(int(body.get("maxMessages") or 10), 100))}).get("receivedMessages", [])
        if body.get("ack") and got:
            call("POST", sub + ":acknowledge", None, {"ackIds": [g["ackId"] for g in got]})
        items = []
        for g in got:
            m = g["message"]
            try:
                text = base64.b64decode(m.get("data") or "").decode("utf-8")
            except Exception:
                text = str(m.get("data") or "")
            items.append({"messageId": m.get("messageId"), "publishTime": m.get("publishTime"), "data": text,
                          "attributes": ", ".join("%s=%s" % kv for kv in (m.get("attributes") or {}).items()) or "No attributes",
                          "acked": bool(body.get("ack"))})
        return {"ok": True, "items": items}
    return None


class _NanoVpc:
    """VPC storage for core/gcp_console_tabs.vpc_op: networks are ResourceStore records;
    subnets / firewall rules / routes are durable child collections (nano_sub)."""

    def __init__(self, g):
        self.g, self.root = g, _tab_root()

    def network(self, name):
        rec = self.g.r.get("gcp", self.g.account, "vpc", name) if self.g.r is not None else None
        if rec is not None and "autoCreateSubnetworks" not in rec:
            rec["autoCreateSubnetworks"] = True
        return rec

    def update_network(self, name, field, value):
        self.g.r.update("gcp", self.g.account, "vpc", name, {field: value})

    def subnets(self, network):
        return [dict(x) for x in _T.children(self.root, "vpc", network, "subnets").values()]

    def put_subnet(self, rec):
        coll = _T.children(self.root, "vpc", rec["network"], "subnets", create=True)
        key = "%s/%s" % (rec["region"], rec["name"])
        coll[key] = {**(coll.get(key) or {"creationTimestamp": _T.now_iso()}), **rec}

    def delete_subnet(self, region, name):
        for key in [k for k in self.root if k.startswith("vpc/") and k.endswith("/subnets")]:
            self.root[key].pop("%s/%s" % (region, name), None)

    def _proj(self, kind):
        return _T.children(self.root, "vpc", "_project", kind, create=True)

    def firewalls(self, network):
        return [dict(f) for f in self._proj("firewalls").values() if f.get("network") == network]

    def firewall_names(self):
        return list(self._proj("firewalls"))

    def put_firewall(self, rec):
        self._proj("firewalls")[rec["name"]] = {**rec, "creationTimestamp": _T.now_iso()}

    def update_firewall(self, name, patch):
        self._proj("firewalls")[name].update(patch)

    def delete_firewall(self, name):
        self._proj("firewalls").pop(name, None)

    def routes(self, network):
        return [dict(r) for r in self._proj("routes").values() if r.get("network") == network]

    def route_names(self):
        return list(self._proj("routes"))

    def put_route(self, rec):
        self._proj("routes")[rec["name"]] = {**rec, "creationTimestamp": _T.now_iso()}

    def delete_route(self, name):
        self._proj("routes").pop(name, None)


def _vpc_tab(g, op, body):
    g.get()   # 404 when the network doesn't exist
    return _T.vpc_op(_NanoVpc(g), g.name, op, body)


class _NanoFunction:
    """Cloud Functions storage for core/gcp_console_tabs.functions_op: the ResourceStore record,
    described like functions.get; test runs execute in the in-browser Python sandbox."""

    def __init__(self, g):
        self.g = g
        rec = g.get()
        if "serviceConfig" not in rec or "code" not in rec:
            g.update({k: v for k, v in _T.describe_function(rec, "nano-project", "us-central1").items()
                      if k not in rec or k in ("serviceConfig", "httpsTrigger")})

    def rec(self):
        return self.g.get()

    def update(self, patch):
        self.g.update(patch)

    def view(self):
        return dict(self.g.get())

    def execute(self, code, entry, runtime, event, env, timeout):
        if not str(runtime).startswith("python"):
            return {"status": "ERROR", "result": None, "logs": "",
                    "error": "Runtime %s can't execute in Nano's in-browser (Pyodide) runtime; Python runtimes run here, "
                             "every runtime runs on the offline appliance." % runtime}
        return _T.run_python_function(code, entry, event, env)

    def topic_exists(self, topic):
        st, _ = _call("pubsub", "GET", "/v1/projects/%s/topics/%s" % (PROJ, topic))
        return st < 300


def _functions_tab(g, op, body):
    return _T.functions_op(_NanoFunction(g), op, body)


class _NanoFirestore:
    """Firestore storage for core/gcp_console_tabs.firestore_op over core/gcp_firestore_core
    (documents per database, composite indexes) + GCS for exports."""

    def __init__(self, db):
        self.db, self.root = db, _tab_root()
        self.base = "%s/databases/%s/documents" % (_P, db)
        st, _ = _call("firestore", "GET", "%s/databases/%s" % (_P, db))
        if st >= 300 and db != "(default)":
            raise _T.TabError(404, "NOT_FOUND", "The database %s does not exist for project %s" % (db, PROJ))

    def _ok(self, st, out):
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "FAILED_PRECONDITION", err.get("message") or "Request failed")
        return out

    def collections(self):
        from core.gcp_firestore_core import _DbDocs
        rels = _DbDocs(_STORES["firestore"], self.db).all()
        return sorted({r.split("/")[0] for r, _ in rels if "/" in r})

    def docs(self, coll):
        if not coll:
            return []
        st, out = _call("firestore", "GET", "%s/%s" % (self.base, coll))
        return [{"id": d["name"].rsplit("/", 1)[-1], "fields": d.get("fields") or {}, "createTime": d.get("createTime", ""),
                 "updateTime": d.get("updateTime", "")} for d in (out or {}).get("documents", [])]

    def create_doc(self, coll, did, typed):
        self._ok(*_call("firestore", "POST", "%s/%s" % (self.base, coll), {"documentId": did}, {"fields": typed}))

    def update_doc(self, coll, did, typed):
        self._ok(*_call("firestore", "PATCH", "%s/%s/%s" % (self.base, coll, did), {}, {"fields": typed}))

    def delete_doc(self, coll, did):
        self._ok(*_call("firestore", "DELETE", "%s/%s/%s" % (self.base, coll, did)))

    def indexes(self):
        st, out = _call("firestore", "GET", "%s/databases/%s/collectionGroups/-/indexes" % (_P, self.db))
        return (out or {}).get("indexes", [])

    def create_index(self, cg, body):
        self._ok(*_call("firestore", "POST", "%s/databases/%s/collectionGroups/%s/indexes" % (_P, self.db, cg), {}, body))

    def delete_index(self, name):
        self._ok(*_call("firestore", "DELETE", "/v1/" + name))

    def put_object(self, bucket, name, text):
        r = _MOD["storage"].dispatch(_STORES["storage"], "POST", "/upload/storage/v1/b/%s/o" % bucket,
                                     {"uploadType": "media", "name": name}, {"content-type": "application/json"}, text.encode())
        if r.status >= 300:
            raise _T.TabError(404 if r.status == 404 else r.status, "NOT_FOUND", "Bucket gs://%s does not exist." % bucket)

    def get_object(self, bucket, name):
        from urllib.parse import quote
        r = _MOD["storage"].dispatch(_STORES["storage"], "GET", "/storage/v1/b/%s/o/%s" % (bucket, quote(name, safe="")),
                                     {"alt": "media"}, {}, b"")
        return r.body.decode("utf-8") if r.status < 300 else None


def _firestore_tab(name, op, body):
    db = _short(name) or "(default)"
    return _T.firestore_op(_NanoFirestore(db), "nano-project", db, op, body)


class _NanoSecret:
    """Secret Manager storage for core/gcp_console_tabs.secret_op over core/gcp_secretmanager_core."""

    def __init__(self, name):
        self.id = _short(name)
        self.base = "%s/secrets/%s" % (_P, self.id)
        self.name = "projects/%s/secrets/%s" % (PROJ, self.id)
        st, self.s = _call("secretmanager", "GET", self.base)
        if st >= 300:
            raise _T.TabError(404, "NOT_FOUND", "Secret [%s] not found." % self.name)

    def meta(self):
        return dict(self.s)

    def patch(self, fields):
        st, out = _call("secretmanager", "PATCH", self.base, {"updateMask": ",".join(fields)},
                        {k: (v if v is not None else {}) for k, v in fields.items()})
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "INVALID_ARGUMENT", err.get("message") or "Update failed")

    def versions(self):
        st, out = _call("secretmanager", "GET", self.base + "/versions")
        return [{"version": v["name"].rsplit("/", 1)[-1], "state": v["state"], "createTime": v.get("createTime", ""),
                 **({"destroyTime": v["destroyTime"]} if v.get("destroyTime") else {})} for v in (out or {}).get("versions", [])]

    def add_version(self, value):
        st, out = _call("secretmanager", "POST", self.base + ":addVersion", {},
                        {"payload": {"data": base64.b64encode(value.encode()).decode()}})
        return out.get("name", "").rsplit("/", 1)[-1]

    def set_state(self, ver, state):
        verb = {"ENABLED": "enable", "DISABLED": "disable", "DESTROYED": "destroy"}[state]
        _call("secretmanager", "POST", "%s/versions/%s:%s" % (self.base, ver, verb), {}, {})

    def access(self, ver):
        st, out = _call("secretmanager", "GET", "%s/versions/%s:access" % (self.base, ver))
        return base64.b64decode(((out or {}).get("payload") or {}).get("data") or "").decode("utf-8", "replace")

    def topic_exists(self, topic):
        st, _ = _call("pubsub", "GET", "/v1/projects/%s/topics/%s" % (PROJ, topic))
        return st < 300


def _secret_tab(name, op, body):
    return _T.secret_op(_NanoSecret(name), op, body)


class _NanoKey:
    """Cloud KMS storage for core/gcp_console_tabs.kms_op over core/gcp_kms_core."""

    def __init__(self, name):
        self.key = _short(name)
        self.ring = "projects/%s/locations/%s/keyRings/%s" % (PROJ, LOC, RING)
        self.name = "%s/cryptoKeys/%s" % (self.ring, self.key)
        self._m = None
        if self.get() is None:
            raise _T.TabError(404, "NOT_FOUND", "CryptoKey %s not found." % self.name)

    def _ok(self, st, out):
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "FAILED_PRECONDITION", err.get("message") or "Request failed")
        return out

    def get(self):
        st, _ = _call("kms", "GET", "/v1/" + self.name)   # applies due rotations / destructions
        return _STORES["kms"].get_key(self.name) if st < 300 else None

    def meta(self):
        return self.get() or {}

    def versions(self):
        st, out = _call("kms", "GET", "/v1/%s/cryptoKeyVersions" % self.name)
        return [{"version": v["name"].rsplit("/", 1)[-1], **{k: v[k] for k in ("state", "createTime", "algorithm", "protectionLevel",
                                                                              "destroyTime", "destroyEventTime") if k in v}}
                for v in (out or {}).get("cryptoKeyVersions", [])]

    def create_version(self):
        out = self._ok(*_call("kms", "POST", "/v1/%s/cryptoKeyVersions" % self.name, {}, {}))
        return out["name"].rsplit("/", 1)[-1]

    def version_action(self, ver, action):
        path = "/v1/%s/cryptoKeyVersions/%s" % (self.name, ver)
        if action in ("destroy", "restore"):
            self._ok(*_call("kms", "POST", path + ":" + action, {}, {}))
        else:
            self._ok(*_call("kms", "PATCH", path, {"updateMask": "state"}, {"state": "ENABLED" if action == "enable" else "DISABLED"}))

    def set_primary(self, ver):
        self._ok(*_call("kms", "POST", "/v1/%s:updatePrimaryVersion" % self.name, {}, {"cryptoKeyVersionId": ver}))

    def set_rotation(self, fields):
        self._ok(*_call("kms", "PATCH", "/v1/" + self.name, {"updateMask": "rotationPeriod,nextRotationTime"},
                        {"rotationPeriod": fields.get("rotationPeriod"), "nextRotationTime": fields.get("nextRotationTime")}))

    def set_labels(self, labels):
        self._ok(*_call("kms", "PATCH", "/v1/" + self.name, {"updateMask": "labels"}, {"labels": labels}))

    def import_jobs(self):
        st, out = _call("kms", "GET", "/v1/%s/importJobs" % self.ring, {"_keygen_budget_s": "0.8"})
        return (out or {}).get("importJobs", [])

    def create_import_job(self, jid, body):
        return self._ok(*_call("kms", "POST", "/v1/%s/importJobs" % self.ring, {"importJobId": jid, "_keygen_budget_s": "0.8"},
                               {"importMethod": body.get("importMethod"), "protectionLevel": body.get("protectionLevel") or "SOFTWARE"}))


def _kms_tab(name, op, body):
    _ensure_keyring()
    return _T.kms_op(_NanoKey(name), op, body)


class _NanoSA:
    """IAM service-account tabs over core/gcp_iam_core (account policy, project policy, keys)."""

    def __init__(self, name):
        st, sa = _call("iam", "GET", "%s/serviceAccounts/%s" % (_P, _short(name)))
        if st >= 300:
            raise _T.TabError(404, "NOT_FOUND", "Unknown service account: %s" % _short(name))
        self.email = sa["email"]
        self.res = "projects/%s/serviceAccounts/%s" % (PROJ, self.email)

    def _pol(self, res):
        return _call("iam", "POST", "/v1/%s:getIamPolicy" % res, {}, {})[1]

    def sa_policy(self):
        return self._pol(self.res)

    def set_sa_policy(self, pol):
        _call("iam", "POST", "/v1/%s:setIamPolicy" % self.res, {}, {"policy": pol})

    def project_policy(self):
        return self._pol("projects/nano-project")

    def set_project_policy(self, pol):
        _call("iam", "POST", "/v1/projects/nano-project:setIamPolicy", {}, {"policy": pol})

    def keys(self):
        return _call("iam", "GET", "/v1/%s/keys" % self.res)[1].get("keys", [])

    def create_key(self):
        st, out = _call("iam", "POST", "/v1/%s/keys" % self.res, {}, {})
        if st >= 300:
            err = (out or {}).get("error") or {}
            raise _T.TabError(st, err.get("status") or "FAILED_PRECONDITION", err.get("message") or "Key creation failed")
        return out

    def key_action(self, kid, action):
        path = "/v1/%s/keys/%s" % (self.res, kid)
        if action == "delete":
            _call("iam", "DELETE", path)
        else:
            _call("iam", "POST", path + ":" + action, {}, {})


def _iam_tab(name, op, body):
    return _T.iam_sa_op(_NanoSA(name), op, body)


def _apigw_tab(g, op, body):
    rec = g.get()
    if op in ("GetLabels", "getLabels"):
        return {"ok": True, "item": {"name": g.name, "labels": rec.get("labels") or {}}}
    if op in ("SetLabels", "setLabels"):
        g.update({"labels": _T.validate_labels(body.get("labels", {}))})
        return {"ok": True}
    return _T.apigw_op(_tab_root(), "nano-project", g.name, op, body)


class _NanoTrigger:
    def __init__(self, g):
        self.g = g
        g.get()

    def rec(self):
        return self.g.get()

    def update(self, patch):
        self.g.update(patch)

    def exists(self, kind, name):
        if kind == "bucket":
            return _call("storage", "GET", "/storage/v1/b/%s" % name)[0] < 300
        if kind == "topic":
            return _call("pubsub", "GET", "/v1/projects/%s/topics/%s" % (PROJ, name))[0] < 300
        if kind == "function":
            return self.g.r.get("gcp", self.g.account, "functions", name) is not None
        return False


def _eventarc_tab(g, op, body):
    return _T.eventarc_op(_NanoTrigger(g), "nano-project", op, body)


def _project_policy(op, project, body):
    res = "projects/%s" % (project or PROJ)
    st, pol = _call("iam", "POST", "/v1/%s:getIamPolicy" % res, {}, {})
    if op == "GetProjectPolicy":
        return {"ok": True, "project": project, "bindings": pol.get("bindings", []), "etag": pol.get("etag", "")}
    fn = _T.policy_grant if op == "GrantAccess" else _T.policy_revoke
    new = fn(pol, body.get("role"), body.get("member"))
    st, out = _call("iam", "POST", "/v1/%s:setIamPolicy" % res, {}, {"policy": new})
    return {"ok": st < 300, "project": project, "bindings": out.get("bindings", [])}


_TAB_HANDLERS = {"compute": _compute_tab, "storage": _storage_tab, "cloudsql": _sql_tab, "pubsub": _pubsub_tab,
                 "vpc": _vpc_tab, "functions": _functions_tab, "firestore": _firestore_tab,
                 "secretmanager": _secret_tab, "kms": _kms_tab, "iam": _iam_tab,
                 "apigateway": _apigw_tab, "eventarc": _eventarc_tab}


def tab_dispatch(svc, operation, name, body, resources=None, account="default"):
    """Serve one resource-detail tab op, or None when `operation` isn't a tab op."""
    body = body or {}
    try:
        if svc == "iam" and operation in ("GetProjectPolicy", "GrantAccess", "RevokeAccess"):
            return _project_policy(operation, name, body)
        if svc == "artifactregistry" and operation in ("GetLabels", "SetLabels"):
            full, repo = _ar.console_find(_STORES[svc], name)
            if repo is None:
                return {"ok": False, "code": "NotFound", "name": name}
            if operation == "SetLabels":
                labels = _T.validate_labels(body.get("labels", {}))
                _ar.dispatch(_STORES[svc], "PATCH", "/v1/" + full, {"updateMask": "labels"}, {}, json.dumps({"labels": labels}).encode())
            return {"ok": True, "item": {"name": name, "labels": dict(_STORES[svc].repos[full].get("labels") or {})}}
        # per-tab reads of the newer services: the resource's console view
        if svc in ("container", "redis", "cloudscheduler", "iamcredentials", "monitoring") \
                and operation.startswith("Get") and len(operation) > 3:
            out = _resource_op(svc, "Get", name, {})
            if not out.get("ok"):
                return out
            return {"ok": True, "item": {k: v for k, v in out.items() if k != "ok"}}
        h = _TAB_HANDLERS.get(svc)
        if h is None or operation in _CRUD:
            return None
        if svc in _GENERIC_TAB_SERVICES:
            out = h(_Generic(resources, account, svc, name), operation, body)
            return out if out is not None else {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": svc}
        return h(name, operation, body)
    except _T.TabError as e:
        return _tab_err(e)


def is_tab_op(svc, operation):
    return svc in _GENERIC_TAB_SERVICES and operation not in _CRUD and svc in _TAB_HANDLERS
