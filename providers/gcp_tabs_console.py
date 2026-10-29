"""GCP console resource-detail tabs on the offline appliance.

`/api/gcp/sub/{service}/{op}/{name}` (GET reads, POST writes) for the tabs of the GCP
console's resource-detail pages — the same URL family the Nano service worker maps onto
`_resource` ops (wasm/providers/gcp_core_adapter.py). Each op reads or writes the SAME
state the service's own REST/SDK API uses (server.py's gcp_*_state, the GCP IAM policy,
the cores), so what a tab shows is the resource's real data and a tab edit is visible to
the API, the CLI and the SDKs. Validation and the records no backend models on its own
(snapshots-of-an-instance filtering, Cloud SQL users/flags, …) come from the shared engine
core/gcp_console_tabs.py — the one Nano runs too.

Responses: reads → {"ok": true, "items": [...]} or {"ok": true, "item": {...}}; writes →
{"ok": true, ...}; errors → {"ok": false, "code", "message"} with the HTTP status the real
API uses.
"""
from __future__ import annotations

import re
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from core import gcp_console_tabs as T
from core.app_context import _SpaceScopedDictProxy

# Child records / settings no service backend holds itself (space-scoped, persisted with
# the space like every other gcp_* service state).
tab_state = _SpaceScopedDictProxy("gcp_console_tabs", lambda: {"children": {}}, "children")


def _server():
    import server as server_module
    return server_module


def _ctx():
    from core import app_context
    return app_context


def _usage(service: str, op: str, name: str, extra: dict | None = None) -> None:
    """A tab write is an event on the resource (its Activity tab + the space's log)."""
    try:
        event = "gcp.%s.%s" % (service, re.sub(r"(?<!^)(?=[A-Z])", "_", op).lower())
        _ctx().record_usage(event, {"name": name, **(extra or {})})
        _ctx().persist_state()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Compute Engine
# ---------------------------------------------------------------------------
def _instance(name: str) -> dict:
    s = _server()
    try:
        s._gcp_compute_sync_runtime_instances()
    except Exception:
        pass
    for cand in list(s._gcp_compute_instance_bucket().values()) + list(s.gcp_compute_state.get("instances", {}).values()):
        if isinstance(cand, dict) and name in (str(cand.get("name") or ""), str(cand.get("instance_id") or ""),
                                               str(cand.get("gcp_resource_id") or "")):
            return cand
    raise T.TabError(404, "NOT_FOUND", "The resource 'instances/%s' was not found" % name)


def _instance_view(inst: dict) -> dict:
    return _server()._gcp_compute_instance_json(inst)


def _known_machine_types() -> list:
    try:
        from core.instance_catalog import GCP
        return list(GCP.keys())
    except Exception:
        return []


def _compute(op: str, name: str, body: dict):
    s = _server()
    inst = _instance(name)
    iname = str(inst.get("name") or name)
    v = T.view_op("compute", op)
    if v:
        return {"ok": True, "item": T.view("compute", v, _instance_view(inst))}
    if op == "setMetadata":
        items = T.validate_metadata(body.get("items", []))
        inst["metadata_items"] = {i["key"]: i["value"] for i in items}
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "keys": [i["key"] for i in items]})
        return {"ok": True, "item": _instance_view(inst)}
    if op == "setMachineType":
        T.check_stopped(_instance_view(inst).get("status"), "changing its machine type")
        mt = T.validate_machine_type(body.get("machineType"), _known_machine_types())
        inst["machine_type"] = mt
        inst["instance_type"] = mt
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "machineType": mt})
        return {"ok": True, "item": _instance_view(inst)}
    if op == "setScheduling":
        sched = T.validate_scheduling(body, _instance_view(inst).get("scheduling"))
        inst["scheduling"] = sched
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), **sched})
        return {"ok": True, "item": _instance_view(inst)}
    if op == "setLabels":
        inst["labels"] = T.validate_labels(body.get("labels", {}))
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", "")})
        return {"ok": True, "item": _instance_view(inst)}
    disks = s.gcp_compute_state.setdefault("disks", {})
    attached = [str(d) for d in (inst.get("attached_disk_names") or [])]
    if op == "listDisks":
        out = []
        for dn in attached:
            d = disks.get(dn)
            if isinstance(d, dict):
                v = s._gcp_compute_disk_view(d)
                out.append({"name": v.get("name"), "boot": bool(d.get("boot")), "sizeGb": str(d.get("sizeGb") or ""),
                            "type": T.short(d.get("type") or "pd-balanced"), "status": v.get("status") or "READY",
                            "autoDelete": bool(d.get("autoDelete")), "mode": "READ_WRITE",
                            "sourceImage": T.short(d.get("sourceImage") or "") or "None",
                            "deviceName": d.get("deviceName") or dn})
        return {"ok": True, "items": out}
    if op == "attachDisk":
        spec = T.disk_spec(body, iname, list(disks.keys()))
        project = str(inst.get("project") or "cloudlearn")
        zone = str(inst.get("zone") or inst.get("az") or "us-central1-a")
        rec = s._gcp_compute_disk_record(project, zone, {**spec, "instance": iname,
                                                          "instance_id": inst.get("instance_id", ""), "deviceName": spec["name"]})
        rec["status"] = "READY"
        disks[rec["name"]] = rec
        inst.setdefault("attached_disk_names", []).append(rec["name"])
        s._gcp_compute_sync_resource_links()
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "disk": rec["name"]})
        return {"ok": True, "name": rec["name"]}
    if op == "detachDisk":
        dn = str(body.get("name") or "")
        d = disks.get(dn)
        if dn not in attached or not isinstance(d, dict):
            raise T.TabError(404, "NOT_FOUND", "Disk '%s' is not attached to this instance." % dn)
        if d.get("boot"):
            raise T.TabError(400, "INVALID_ARGUMENT", "The boot disk cannot be detached from a VM instance.")
        inst["attached_disk_names"] = [x for x in attached if x != dn]
        d["instance"] = ""
        d["instance_id"] = ""
        d["status"] = "READY"
        s._gcp_compute_sync_resource_links()
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "disk": dn})
        return {"ok": True, "name": dn}
    snaps = s.gcp_compute_state.setdefault("snapshots", {})
    if op == "listSnapshots":
        mine = [x for x in snaps.values() if isinstance(x, dict) and T.short(x.get("sourceDisk")) in attached]
        return {"ok": True, "items": [{"name": x.get("name"), "sourceDisk": T.short(x.get("sourceDisk")),
                                       "status": x.get("status", "READY"), "sizeGb": str(x.get("sizeGb") or ""),
                                       "storageLocations": ", ".join(x.get("storageLocations") or []),
                                       "created": x.get("created", "")} for x in mine]}
    if op == "createSnapshot":
        spec = T.snapshot_spec(body, attached, list(snaps.keys()))
        d = disks.get(spec["sourceDisk"]) or {}
        rec = s._gcp_compute_snapshot_record(str(inst.get("project") or "cloudlearn"),
                                             {**spec, "sizeGb": d.get("sizeGb") or 10})
        snaps[rec["name"]] = rec
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "snapshot": rec["name"]})
        return {"ok": True, "name": rec["name"]}
    if op == "deleteSnapshot":
        sn = str(body.get("name") or "")
        x = snaps.get(sn)
        if not isinstance(x, dict) or T.short(x.get("sourceDisk")) not in attached:
            raise T.TabError(404, "NOT_FOUND", "The resource 'snapshots/%s' was not found" % sn)
        del snaps[sn]
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "snapshot": sn})
        return {"ok": True, "name": sn}
    return None


# ---------------------------------------------------------------------------
# Cloud Storage — bucket settings (lifecycle, encryption, retention, …)
# ---------------------------------------------------------------------------
def _storage(op: str, name: str, body: dict):
    from core import gcp_storage_core as gcs
    s = _server()
    rec = s.gcp_storage_state.get("buckets", {}).get(name)
    if not isinstance(rec, dict):
        raise T.TabError(404, "NOT_FOUND", "The specified bucket does not exist.")
    project = str(rec.get("project") or "cloudlearn")
    v = T.view_op("storage", op)
    if v:
        return {"ok": True, "item": T.view("storage", v, s._gcp_storage_bucket_view(project, rec))}
    if op == "lockRetention":
        try:
            gcs.lock_retention(rec)
        except gcs.BucketPatchError as e:
            raise T.TabError(e.status, e.reason.upper(), e.message)
        _usage("storage", op, name)
        return {"ok": True, "item": s._gcp_storage_bucket_view(project, rec)}
    patch = T.storage_patch(op, body)
    if patch is None:
        return None
    try:
        gcs.apply_bucket_patch(rec, gcs.validate_bucket_patch(rec, patch))
    except gcs.BucketPatchError as e:
        raise T.TabError(e.status, "INVALID_ARGUMENT" if e.status == 400 else "FAILED_PRECONDITION", e.message)
    _usage("storage", op, name, {"bucket": name, "fields": ",".join(patch)})
    return {"ok": True, "item": s._gcp_storage_bucket_view(project, rec)}


# ---------------------------------------------------------------------------
# Cloud SQL — databases, users, backups, replicas, connectivity, flags, …
# ---------------------------------------------------------------------------
def _sql_err(e):
    return T.TabError(e.status, e.code, e.message)


def _cloudsql(op: str, name: str, body: dict):
    from core import gcp_cloudsql_core as sqlc
    s = _server()
    insts = s.gcp_sql_state.setdefault("instances", {})
    rec = insts.get(name)
    if not isinstance(rec, dict):
        raise T.TabError(404, "NOT_FOUND", "The Cloud SQL instance does not exist. Instance: %s" % name)
    project = str(rec.get("project") or "cloudlearn")
    version = str(rec.get("databaseVersion") or "POSTGRES_15")
    full = lambda: s._gcp_sql_instance_view(project, rec)

    def op_rec(kind, target=None):
        s._gcp_sql_make_operation(project, target or name, kind)
        _usage("sql", op, name, {"instance": name, "operationType": kind})

    v = T.view_op("cloudsql", op)
    if v:
        return {"ok": True, "item": T.view("cloudsql", v, full())}
    patch = T.sql_settings_patch(op, body, rec.get("settings") or {})
    if patch is not None:
        try:
            rec["settings"] = sqlc.patch_settings(version, rec.get("settings") or {}, patch)
        except sqlc.SqlSettingsError as e:
            raise _sql_err(e)
        rec["updateTime"] = s._now()
        op_rec("UPDATE")
        return {"ok": True, "item": full()}
    # databases
    dbs = rec.setdefault("databases", [])
    if op == "listDatabases":
        return {"ok": True, "items": [{"name": d.get("name"), "charset": d.get("charset") or "UTF8",
                                       "collation": d.get("collation") or "en_US.UTF8"} for d in dbs]}
    if op == "createDatabase":
        dn = str(body.get("name") or "").strip()
        if not dn:
            raise T.TabError(400, "INVALID_ARGUMENT", "Database name is required.")
        if any(d.get("name") == dn for d in dbs):
            raise T.TabError(409, "ALREADY_EXISTS", "The database already exists. Database: %s" % dn)
        dbs.append({"name": dn, "charset": str(body.get("charset") or "UTF8"), "collation": str(body.get("collation") or "en_US.UTF8")})
        op_rec("CREATE_DATABASE")
        return {"ok": True, "name": dn}
    if op == "deleteDatabase":
        dn = str(body.get("name") or "")
        if not any(d.get("name") == dn for d in dbs):
            raise T.TabError(404, "NOT_FOUND", "The database does not exist. Database: %s" % dn)
        rec["databases"] = [d for d in dbs if d.get("name") != dn]
        op_rec("DELETE_DATABASE")
        return {"ok": True, "name": dn}
    # users (the instance's master user is a real login on the backing engine)
    users = rec.setdefault("users", [])
    master_user = str(rec.get("masterUsername") or "")
    if master_user and not any(u.get("name") == master_user for u in users):
        users.insert(0, {"name": master_user, "host": "%" if sqlc.engine_of(version) == "MYSQL" else "", "type": "BUILT_IN"})
    if op == "listUsers":
        return {"ok": True, "items": [{"name": u.get("name"), "host": u.get("host") or "", "type": u.get("type") or "BUILT_IN"} for u in users]}
    if op == "createUser":
        try:
            u = sqlc.validate_user(version, body, users)
        except sqlc.SqlSettingsError as e:
            raise _sql_err(e)
        users.append({"name": u["name"], "host": u["host"], "type": u["type"]})
        op_rec("CREATE_USER")
        return {"ok": True, "name": u["name"]}
    if op in ("deleteUser", "setUserPassword"):
        un, host = str(body.get("name") or ""), str(body.get("host") or "")
        if not any(u.get("name") == un and (u.get("host") or "") == host for u in users):
            raise T.TabError(404, "NOT_FOUND", "The user does not exist. User: %s" % un)
        if op == "deleteUser":
            rec["users"] = [u for u in users if not (u.get("name") == un and (u.get("host") or "") == host)]
            op_rec("DELETE_USER")
        else:
            if not str(body.get("password") or ""):
                raise T.TabError(400, "INVALID_ARGUMENT", "Invalid request: a password is required.")
            op_rec("UPDATE_USER")
        return {"ok": True, "name": un}
    # backups (backupRuns)
    backups = s.gcp_sql_state.setdefault("backups", {})
    if op == "listBackups":
        mine = [b for b in backups.values() if isinstance(b, dict) and b.get("instance") == name]
        mine.sort(key=lambda b: b.get("createTime", ""), reverse=True)
        return {"ok": True, "items": [{"id": b.get("name"), "type": b.get("backupType") or "ON_DEMAND",
                                       "status": b.get("status") or "SUCCESSFUL", "description": b.get("description") or "",
                                       "windowStartTime": b.get("createTime", ""), "location": "us"} for b in mine]}
    if op == "createBackup":
        b = s._gcp_sql_backup_record(project, name, {"backupType": "ON_DEMAND", "description": body.get("description") or ""})
        backups[b["name"]] = b
        op_rec("BACKUP_VOLUME")
        return {"ok": True, "id": b["name"]}
    if op == "deleteBackup":
        bid = str(body.get("id") or "")
        b = backups.get(bid)
        if not isinstance(b, dict) or b.get("instance") != name:
            raise T.TabError(404, "NOT_FOUND", "The backup run does not exist. Backup run: %s" % bid)
        del backups[bid]
        op_rec("DELETE_BACKUP")
        return {"ok": True, "id": bid}
    # read replicas: instances whose masterInstanceName is this one
    if op == "listReplicas":
        reps = [r for r in insts.values() if isinstance(r, dict) and r.get("masterInstanceName") == name]
        return {"ok": True, "items": [{"name": r.get("name"), "state": r.get("state") or "RUNNABLE", "region": r.get("region"),
                                       "databaseVersion": r.get("databaseVersion"), "tier": (r.get("settings") or {}).get("tier", ""),
                                       "instanceType": "READ_REPLICA_INSTANCE"} for r in reps]}
    if op == "createReplica":
        if rec.get("masterInstanceName"):
            raise T.TabError(400, "INVALID_ARGUMENT", "Invalid request: cannot create a replica of a read replica.")
        rn = T.validate_name(body.get("name"), "name")
        if rn in insts:
            raise T.TabError(409, "ALREADY_EXISTS", "The Cloud SQL instance already exists. Instance: %s" % rn)
        rep = s._gcp_sql_instance_record(project, {"name": rn, "databaseVersion": version, "region": rec.get("region"),
                                                   "settings": dict(rec.get("settings") or {}),
                                                   "instanceType": "READ_REPLICA_INSTANCE"})
        rep["masterInstanceName"] = name
        rep["_backend"] = rec.get("_backend")          # a replica serves reads from the primary's data
        rep["ipAddresses"] = rec.get("ipAddresses") or rep["ipAddresses"]
        insts[rn] = rep
        rec.setdefault("replicaNames", []).append(rn)
        op_rec("CREATE_REPLICA", rn)
        return {"ok": True, "name": rn}
    if op in ("promoteReplica", "deleteReplica"):
        rn = str(body.get("name") or "")
        rep = insts.get(rn)
        if not isinstance(rep, dict) or rep.get("masterInstanceName") != name:
            raise T.TabError(404, "NOT_FOUND", "%s is not a read replica of %s." % (rn, name))
        rec["replicaNames"] = [x for x in rec.get("replicaNames") or [] if x != rn]
        if op == "promoteReplica":
            rep.pop("masterInstanceName", None)
            rep["instanceType"] = "CLOUD_SQL_INSTANCE"
            op_rec("PROMOTE_REPLICA", rn)
        else:
            del insts[rn]
            op_rec("DELETE", rn)
        return {"ok": True, "name": rn}
    if op == "listOperations":
        ops = [o for o in (s.gcp_sql_state.get("operation_records") or {}).values() if o.get("targetId") == name]
        ops.sort(key=lambda o: o.get("insertTime", ""), reverse=True)
        return {"ok": True, "items": [{"operationType": o.get("operationType"), "status": o.get("status"),
                                       "insertTime": o.get("insertTime"), "endTime": o.get("endTime") or "",
                                       "user": o.get("user"), "name": o.get("name")} for o in ops[:100]]}
    if op == "listQueryInsights":
        out = [s._gcp_sql_query_insight_view(q) for q in (s.gcp_sql_state.get("query_insights") or {}).values()
               if isinstance(q, dict) and q.get("instance") == name]
        return {"ok": True, "items": out}
    return None


# ---------------------------------------------------------------------------
# Pub/Sub — subscriptions, schema, messages, encryption (topics live in the Google
# Pub/Sub emulator when it runs; topic settings + schemas in gcp_pubsub_state)
# ---------------------------------------------------------------------------
def _project() -> str:
    try:
        space = _ctx().PLATFORM.get_active_space() or {}
        return str(space.get("active_account") or "cloudlearn")
    except Exception:
        return "cloudlearn"


def _ps_err(e):
    return T.TabError(e.code, e.status, e.message)


def _pubsub(op: str, name: str, body: dict):
    import base64
    from core import gcp_pubsub_core as psc
    from core import gcp_pubsub_emulator as emu
    s = _server()
    st = s.gcp_pubsub_state
    project = _project()
    topic = T.short(name)
    live = emu.available()
    if live:
        t = emu.get_topic(project, topic)
        if not t:
            raise T.TabError(404, "NOT_FOUND", "Topic not found: projects/%s/topics/%s" % (project, topic))
    elif topic not in st.get("topics", {}):
        raise T.TabError(404, "NOT_FOUND", "Topic not found: projects/%s/topics/%s" % (project, topic))
    mirror = st.setdefault("topics", {}).setdefault(topic, s._gcp_pubsub_topic_record(project, topic, {}))
    schemas = st.setdefault("schemas", {})
    full_topic = "projects/%s/topics/%s" % (project, topic)

    def topic_view():
        return s._gcp_pubsub_topic_view(project, mirror)

    v = T.view_op("pubsub", op)
    if v:
        tv = topic_view()
        if v == "schema" and (mirror.get("schemaSettings") or {}).get("schema"):
            sc = schemas.get(T.short(mirror["schemaSettings"]["schema"]))
            tv["schema"] = s._gcp_pubsub_schema_view(sc) if sc else None
        return {"ok": True, "item": T.view("pubsub", v, tv)}
    patch = T.pubsub_topic_patch(op, body)
    if patch is not None:
        try:
            fields = psc.validate_topic_patch(patch, ",".join(patch), lambda n: T.short(n) in schemas)
        except psc.PubsubError as e:
            raise _ps_err(e)
        for k, val in fields.items():
            mirror[k] = val
        mirror["updateTime"] = s._now()
        _usage("pubsub", op, topic, {"topic": topic, "fields": ",".join(fields)})
        return {"ok": True, "item": topic_view()}
    if op == "listSchemas":
        return {"ok": True, "items": [s._gcp_pubsub_schema_view(x) for x in schemas.values()
                                      if str(x.get("project") or project) == project]}
    if op == "createSchema":
        sid = str(body.get("name") or "")
        try:
            rec = psc.validate_schema(sid, body)
        except psc.PubsubError as e:
            raise _ps_err(e)
        if sid in schemas:
            raise T.TabError(409, "ALREADY_EXISTS", "Schema already exists: projects/%s/schemas/%s" % (project, sid))
        schemas[sid] = s._gcp_pubsub_schema_record(project, {"name": sid, **rec})
        _usage("pubsub", op, topic, {"schema": sid})
        return {"ok": True, "name": sid}
    # subscriptions attached to this topic
    if op in ("listSubscriptions", "listPullSubscriptions"):   # the Messages tab pulls from pull subscriptions
        if live:
            subs = [x for x in emu.list_subscriptions(project) if x.get("topic") == topic]
        else:
            subs = [x for x in st.get("subscriptions", {}).values() if T.short(x.get("topic")) == topic]
        items = [{"name": T.short(x.get("name") or x.get("subscriptionId")),
                  "ackDeadlineSeconds": x.get("ackDeadlineSeconds", 10),
                  "messageRetentionDuration": x.get("messageRetentionDuration") or "604800s",
                  "deliveryType": "Push" if (x.get("pushConfig") or {}).get("pushEndpoint") else "Pull",
                  "retainAckedMessages": bool(x.get("retainAckedMessages"))} for x in subs]
        if op == "listPullSubscriptions":
            items = [x for x in items if x["deliveryType"] == "Pull"]
        return {"ok": True, "items": items}
    if op == "createSubscription":
        sid = T.validate_pubsub_id(body.get("name"))
        ack = int(body.get("ackDeadlineSeconds") or 10)
        if not 10 <= ack <= 600:
            raise T.TabError(400, "INVALID_ARGUMENT", "The ack deadline must be between 10 and 600 seconds.")
        if live:
            from google.api_core import exceptions as gax
            try:
                emu.create_subscription(project, sid, topic, ack)
            except gax.AlreadyExists:
                raise T.TabError(409, "ALREADY_EXISTS", "Subscription already exists: projects/%s/subscriptions/%s" % (project, sid))
        elif sid in st.setdefault("subscriptions", {}):
            raise T.TabError(409, "ALREADY_EXISTS", "Subscription already exists: projects/%s/subscriptions/%s" % (project, sid))
        st.setdefault("subscriptions", {})[sid] = s._gcp_pubsub_subscription_record(project, sid, {"topic": full_topic, "ackDeadlineSeconds": ack})
        _usage("pubsub", op, topic, {"subscription": sid})
        return {"ok": True, "name": sid}
    if op == "deleteSubscription":
        sid = T.short(body.get("name"))
        gone = emu.delete_subscription(project, sid) if live else st.get("subscriptions", {}).pop(sid, None) is not None
        st.get("subscriptions", {}).pop(sid, None)
        if not gone:
            raise T.TabError(404, "NOT_FOUND", "Subscription not found: projects/%s/subscriptions/%s" % (project, sid))
        _usage("pubsub", op, topic, {"subscription": sid})
        return {"ok": True, "name": sid}
    # messages: publish to the topic / pull from one of its subscriptions
    if op == "publishMessage":
        data = str(body.get("data") or "")
        attrs = {str(k): str(v) for k, v in (body.get("attributes") or {}).items()}
        b64 = base64.b64encode(data.encode()).decode()
        ss = mirror.get("schemaSettings") or {}
        if ss.get("schema"):
            sc = schemas.get(T.short(ss["schema"]))
            try:
                psc.check_message(sc, ss.get("encoding", "JSON"), b64)
            except psc.PubsubError as e:
                raise _ps_err(e)
        if not data and not attrs:
            raise T.TabError(400, "INVALID_ARGUMENT", "A message needs data or at least one attribute.")
        if live:
            mid = emu.publish(project, topic, data.encode(), attrs)
        else:
            mid = s._id("msg")
            entry = {"messageId": mid, "data": b64, "attributes": attrs, "publishTime": s._now(), "topic": topic}
            for sub in st.get("subscriptions", {}).values():
                if T.short(sub.get("topic")) == topic:
                    st.setdefault("messages", {}).setdefault(str(sub.get("subscriptionId")), []).append({**entry, "ackId": s._id("ack")})
        _usage("pubsub", op, topic, {"messageId": mid})
        return {"ok": True, "messageIds": [mid]}
    if op == "pullMessages":
        sid = T.short(body.get("subscription"))
        n = max(1, min(int(body.get("maxMessages") or 10), 100))
        if live:
            if not emu.get_subscription(project, sid):
                raise T.TabError(404, "NOT_FOUND", "Subscription not found: projects/%s/subscriptions/%s" % (project, sid))
            got = emu.pull(project, sid, n)
            if body.get("ack") and got:
                emu.acknowledge(project, sid, [g["ackId"] for g in got])
        else:
            q = st.setdefault("messages", {}).get(sid, [])
            got = [{"ackId": m.get("ackId"), "message": m} for m in q[:n]]
            if body.get("ack"):
                st["messages"][sid] = q[n:]
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


# ---------------------------------------------------------------------------
# VPC network — subnets, firewall rules, routes, peering, flow logs over gcp_vpc_state
# (the same records /compute/v1 networks|subnetworks|firewalls|routes serve; firewall
# rules are what core/gcp_vpc_enforce applies inside governed instances)
# ---------------------------------------------------------------------------
class _OfflineVpc:
    def __init__(self):
        self.s = _server()
        self.st = self.s.gcp_vpc_state
        self.project = _project()

    def _id(self, seed):
        return self.s._gcp_compute_numeric_id("%s:%s" % (self.project, seed))

    def network(self, name):
        rec = self.st.get("networks", {}).get(name)
        return rec if isinstance(rec, dict) else None

    def update_network(self, name, field, value):
        self.st["networks"][name][field] = value

    def subnets(self, network):
        return [dict(v) for v in self.st.get("subnetworks", {}).values()
                if isinstance(v, dict) and T.short(v.get("network") or "default") == network]

    def _subnet_key(self, region, name):
        for k, v in self.st.get("subnetworks", {}).items():
            if isinstance(v, dict) and v.get("name") == name and v.get("region") == region:
                return k
        return None

    def put_subnet(self, rec):
        subs = self.st.setdefault("subnetworks", {})
        key = self._subnet_key(rec["region"], rec["name"]) or "%s/%s" % (rec["region"], rec["name"])
        cur = subs.get(key) or {"id": self._id("%s:%s" % (rec["region"], rec["name"])), "project": self.project, "createTime": self.s._now()}
        subs[key] = {**cur, **rec}

    def delete_subnet(self, region, name):
        self.st.get("subnetworks", {}).pop(self._subnet_key(region, name), None)

    def firewalls(self, network):
        return [dict(f) for f in self.st.get("firewalls", {}).values() if isinstance(f, dict) and T.short(f.get("network") or "default") == network]

    def firewall_names(self):
        return list(self.st.get("firewalls", {}).keys())

    def put_firewall(self, rec):
        self.st.setdefault("firewalls", {})[rec["name"]] = {**rec, "id": self._id(rec["name"]), "project": self.project, "createTime": self.s._now()}

    def update_firewall(self, name, patch):
        self.st["firewalls"][name].update(patch)

    def delete_firewall(self, name):
        self.st.get("firewalls", {}).pop(name, None)

    def routes(self, network):
        return [dict(r) for r in self.st.get("routes", {}).values() if isinstance(r, dict) and T.short(r.get("network") or "default") == network]

    def route_names(self):
        return list(self.st.get("routes", {}).keys())

    def put_route(self, rec):
        self.st.setdefault("routes", {})[rec["name"]] = {**rec, "id": self._id(rec["name"]), "project": self.project, "createTime": self.s._now()}

    def delete_route(self, name):
        self.st.get("routes", {}).pop(name, None)


def _vpc(op: str, name: str, body: dict):
    be = _OfflineVpc()
    out = T.vpc_op(be, T.short(name), op, body)
    if out is not None and not op.startswith("list"):
        _usage("vpc", op, T.short(name), {k: body.get(k) for k in ("name", "region", "peerNetwork") if body.get(k)})
    return out


# ---------------------------------------------------------------------------
# Cloud Functions — source, trigger, variables, testing (real execution), networking, logs
# ---------------------------------------------------------------------------
class _OfflineFunction:
    def __init__(self, name):
        self.s = _server()
        fns = self.s.gcp_functions_state.setdefault("functions", {})
        self.fn = fns.get(T.short(name))
        if not isinstance(self.fn, dict):
            raise T.TabError(404, "NOT_FOUND", "Function %s does not exist." % T.short(name))

    def rec(self):
        return self.fn

    def update(self, patch):
        self.fn.update(patch)
        if "runtime" in patch:
            self.fn.setdefault("buildConfig", {})["runtime"] = patch["runtime"]

    def view(self):
        return self.s._gcp_functions_view(str(self.fn.get("project") or "cloudlearn"), str(self.fn.get("location") or "us-central1"), self.fn)

    def execute(self, code, entry, runtime, event, env, timeout):
        from core import gcp_function_runtime
        try:
            return gcp_function_runtime.execute(code, entry, runtime, event, timeout=timeout, env=env)
        except Exception as e:
            return {"status": "ERROR", "error": str(e)[:300], "result": None, "logs": ""}

    def topic_exists(self, topic):
        from core import gcp_pubsub_emulator as emu
        if emu.available():
            return bool(emu.get_topic(_project(), topic))
        return topic in self.s.gcp_pubsub_state.get("topics", {})


def _functions(op: str, name: str, body: dict):
    out = T.functions_op(_OfflineFunction(name), op, body)
    if out is not None and not op.startswith(("get", "list")):
        _usage("functions", op, T.short(name), {k: out.get(k) for k in ("status", "id", "versionId") if out.get(k)})
    return out


# ---------------------------------------------------------------------------
# Firestore — documents live in the Google Firestore emulator (named databases), indexes in
# gcp_firestore_state, security rulesets / operations in the tab state, exports in GCS
# ---------------------------------------------------------------------------
class _OfflineFirestore:
    def __init__(self, db):
        from core import gcp_firestore_emulator as emu
        self.s, self.emu, self.db, self.project = _server(), emu, db, _project()
        if db not in self.s.gcp_firestore_state.setdefault("databases", {}) and db != "(default)":
            raise T.TabError(404, "NOT_FOUND", "The database %s does not exist for project %s" % (db, self.project))
        self.root = tab_state
        self.live = emu.available()
        self.engine = None if self.live else self.s._gcp_firestore_engine()

    def _rows(self, docs):
        return [{"id": str(d.get("name", "")).rsplit("/", 1)[-1], "fields": d.get("fields") or {},
                 "createTime": d.get("createTime", ""), "updateTime": d.get("updateTime", "")} for d in docs]

    def collections(self):
        docs = self.emu.list_root(self.project, self.db) if self.live else self.engine.list_root_documents(self.project, self.db)
        return sorted({str(d.get("name", "")).split("/documents/", 1)[-1].split("/")[0] for d in docs if "/documents/" in str(d.get("name", ""))})

    def docs(self, coll):
        if not coll:
            return []
        return self._rows(self.emu.list_collection(self.project, self.db, coll) if self.live
                          else self.engine.list_documents(self.project, self.db, coll))

    def create_doc(self, coll, did, typed):
        if self.live:
            self.emu.create(self.project, self.db, coll, did, typed)
        else:
            self.engine.create_document(self.project, self.db, coll, self.s._gcp_firestore_normalize_fields(typed), did)

    def update_doc(self, coll, did, typed):
        if self.live:
            self.emu.update(self.project, self.db, coll, did, typed)
        else:
            self.engine.update_document(self.project, self.db, coll, did, self.s._gcp_firestore_normalize_fields(typed))

    def delete_doc(self, coll, did):
        if self.live:
            self.emu.delete(self.project, self.db, coll, did)
        else:
            self.engine.delete_document(self.project, self.db, coll, did)

    def indexes(self):
        out = []
        for idx in self.s.gcp_firestore_state.get("indexes", {}).values():
            if isinstance(idx, dict) and str(idx.get("database") or "(default)") == self.db:
                v = self.s._gcp_firestore_index_view(idx)
                out.append(v)
        return out

    def create_index(self, cg, body):
        from core import gcp_firestore_core as fsc
        try:
            rec = fsc.validate_index(cg, body)
        except ValueError as e:
            raise T.TabError(400, "INVALID_ARGUMENT", str(e))
        for idx in self.indexes():
            if idx["collectionGroup"] == cg and idx["fields"] == rec["fields"] and idx["queryScope"] == rec["queryScope"]:
                raise T.TabError(409, "ALREADY_EXISTS", "Index already exists")
        rec = self.s._gcp_firestore_index_record(self.project, self.db, cg, {**rec, "name": "CICAg" + T.numeric_id(str(time.time()))[:10]})
        self.s.gcp_firestore_state.setdefault("indexes", {})["%s:%s:%s:%s" % (self.project, self.db, cg, rec["name"])] = rec

    def delete_index(self, name):
        idx = self.s.gcp_firestore_state.get("indexes", {})
        for k, v in list(idx.items()):
            if isinstance(v, dict) and self.s._gcp_firestore_index_view(v)["name"] == name:
                del idx[k]
                return
        raise T.TabError(404, "NOT_FOUND", "Index not found")

    def put_object(self, bucket, name, text):
        if bucket not in self.s.gcp_storage_state.get("buckets", {}):
            raise T.TabError(404, "NOT_FOUND", "Bucket gs://%s does not exist." % bucket)
        from core import gcp_gcs_store as gcs
        if gcs.available():
            gcs.put_text(self.s._tenant_scoped_bucket(bucket), name, text, "application/json")
        rec = self.s._gcp_storage_object_record(bucket, name, {"contentType": "application/json", "size": str(len(text.encode()))})
        rec["_export_body"] = None if gcs.available() else text   # no byte store: keep the export with its record
        self.s.gcp_storage_state.setdefault("objects", {}).setdefault(bucket, {})[name] = rec

    def get_object(self, bucket, name):
        rec = self.s.gcp_storage_state.get("objects", {}).get(bucket, {}).get(name)
        if rec is None:
            return None
        if rec.get("_export_body"):
            return rec["_export_body"]
        from core import gcp_gcs_store as gcs
        try:
            data, _ = gcs.download(self.s._tenant_scoped_bucket(bucket), name)
            return data.decode("utf-8")
        except Exception:
            return None


def _firestore(op: str, name: str, body: dict):
    db = T.short(name) or "(default)"
    out = T.firestore_op(_OfflineFirestore(db), _project(), db, op, body)
    if out is not None and not op.startswith(("get", "list", "run")):
        _usage("firestore", op, db, {k: body.get(k) for k in ("collection", "id", "bucket") if body.get(k)})
    return out


# ---------------------------------------------------------------------------
# Secret Manager — Vault KV v2 holds the versions; core/vault_routes the secret's
# settings + version states (shared with the native /v1 Secret Manager API)
# ---------------------------------------------------------------------------
class _OfflineSecret:
    def __init__(self, name):
        from core import vault_client as vc
        from core import vault_routes as vr
        self.vc, self.vr = vc, vr
        self.space = vr._active_space_id(None)
        self.id = T.short(name)
        if self.id not in vr._gcp_idx_get(self.space, "secrets"):
            raise T.TabError(404, "NOT_FOUND", "Secret [projects/%s/secrets/%s] not found." % (_project(), self.id))
        self.name = "projects/%s/secrets/%s" % (_project(), self.id)

    def meta(self):
        m = self.vr.gcp_secret_meta(self.space, self.id)
        m.pop("_", None)
        m.setdefault("replication", {"automatic": {}})
        m.setdefault("createTime", self.vr._gcp_idx_created(self.space, "secrets").get(self.id, ""))
        return m

    def patch(self, fields):
        m = self.vr.gcp_secret_meta(self.space, self.id)
        m.pop("_", None)
        from core import gcp_secretmanager_core as smc
        smc.apply_secret_patch(m, fields)
        self.vr.gcp_secret_meta_put(self.space, self.id, m)

    def versions(self):
        return self.vr.gcp_secret_versions(self.space, self.id)

    def add_version(self, value):
        md = self.vc.kv_put("gcp", self.space, self.id, value)
        if md is None:
            raise T.TabError(503, "UNAVAILABLE", "The secret store (Vault) is unavailable.")
        return str(md.get("version", ""))

    def set_state(self, ver, state):
        self.vr.gcp_secret_set_state(self.space, self.id, ver, state)

    def access(self, ver):
        import json as _json
        got = self.vc.kv_get("gcp", self.space, self.id, version=int(ver))
        if got is None:
            raise T.TabError(503, "UNAVAILABLE", "The secret store (Vault) is unavailable.")
        data = got.get("data") or {}
        return data.get("value") if "value" in data else _json.dumps(data)

    def topic_exists(self, topic):
        from core import gcp_pubsub_emulator as emu
        if emu.available():
            return bool(emu.get_topic(_project(), topic))
        return topic in _server().gcp_pubsub_state.get("topics", {})


def _secretmanager(op: str, name: str, body: dict):
    out = T.secret_op(_OfflineSecret(name), op, body)
    if out is not None and not op.startswith(("get", "list")):
        _usage("secretmanager", op, T.short(name), {k: body.get(k) for k in ("version",) if body.get(k)})
    return out


# ---------------------------------------------------------------------------
# Cloud KMS — key versions are Vault transit key versions; states / primary / rotation /
# labels in the key's KV meta (core/vault_routes, shared with the native /v1 API)
# ---------------------------------------------------------------------------
class _OfflineKey:
    def __init__(self, name):
        from core import gcp_kms_core as kc
        from core import vault_client as vc
        from core import vault_routes as vr
        self.kc, self.vc, self.vr = kc, vc, vr
        self.space = vr._active_space_id(None)
        self.key = T.short(name)
        if not any(e.split("/")[-1] == self.key for e in vr._gcp_idx_get(self.space, "kms")):
            raise T.TabError(404, "NOT_FOUND", "CryptoKey %s not found." % self.key)
        self.ring = vr.gcp_kms_ring_of(self.space, self.key)
        self.name = "projects/%s/locations/global/keyRings/%s/cryptoKeys/%s" % (_project(), self.ring, self.key)
        self._m = vr.gcp_kms_sync(self.space, self.ring, self.key)

    def _save(self):
        self.vr.gcp_kms_key_meta_put(self.space, self.key, self._m)

    def meta(self):
        return self._m

    def versions(self):
        return [{"version": v, "state": d.get("state", "ENABLED"), "createTime": d.get("createTime", ""),
                 "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION", "protectionLevel": "SOFTWARE",
                 **{k: d[k] for k in ("destroyTime", "destroyEventTime") if d.get(k)}}
                for v, d in (self._m.get("versions") or {}).items()]

    def create_version(self):
        nv = self.vc.transit_rotate("gcp", self.space, "%s__%s" % (self.ring, self.key))
        if not nv:
            raise T.TabError(503, "UNAVAILABLE", "The key store (Vault transit) is unavailable.")
        self._m.setdefault("versions", {})[str(nv)] = {"state": "ENABLED", "createTime": T.now_iso()}
        self._save()
        return str(nv)

    def version_action(self, ver, action):
        self.kc.set_version_state(self._m, ver, action)
        self._save()

    def set_primary(self, ver):
        self.kc.set_primary(self._m, ver)
        self._save()

    def set_rotation(self, fields):
        self._m.pop("rotationPeriod", None)
        self._m.pop("nextRotationTime", None)
        self._m.update(fields)
        self._m["rotation_period"] = fields.get("rotationPeriod", "")   # the console's key view reads this
        self._save()

    def set_labels(self, labels):
        self._m["labels"] = labels
        self._save()

    def _jobs(self):
        return self.vr._kv_dict(self.space, "__kmsimport__%s" % self.ring)

    def import_jobs(self):
        jobs = self._jobs()
        out = self.kc.import_job_list(jobs, self._ring_name(), 5.0)
        self.vc.kv_put("gcp", self.space, "__kmsimport__%s" % self.ring, jobs or {"_": ""})
        return out

    def create_import_job(self, jid, body):
        jobs = self._jobs()
        jobs.pop("_", None)
        view = self.kc.import_job_create(jobs, self._ring_name(), jid, body, 30.0)
        self.vc.kv_put("gcp", self.space, "__kmsimport__%s" % self.ring, jobs)
        return view

    def _ring_name(self):
        return "projects/%s/locations/global/keyRings/%s" % (_project(), self.ring)


def _kms(op: str, name: str, body: dict):
    out = T.kms_op(_OfflineKey(name), op, body)
    if out is not None and not op.startswith(("get", "list")):
        _usage("kms", op, T.short(name), {k: body.get(k) for k in ("version", "id") if body.get(k)})
    return out


# ---------------------------------------------------------------------------
# IAM — service accounts (gcp_iam_state), their own IAM policy, project roles, keys
# ---------------------------------------------------------------------------
class _OfflineSA:
    def __init__(self, name):
        from providers import gcp_iam as gi
        self.s, self.gi = _server(), gi
        self.project = self.s._gcp_project_name(_project())
        self.sa = gi._iam_find_sa(self.project, T.short(name))
        if not isinstance(self.sa, dict):
            raise T.TabError(404, "NOT_FOUND", "Unknown service account: %s" % T.short(name))
        self.email = self.sa.get("email")

    def sa_policy(self):
        return dict(self.s.gcp_iam_state.setdefault("sa_policies", {}).get(self.email) or {"version": 1, "bindings": []})

    def set_sa_policy(self, pol):
        self.s.gcp_iam_state.setdefault("sa_policies", {})[self.email] = pol

    def project_policy(self):
        return self.s._gcp_iam_policy_view(self.project)

    def set_project_policy(self, pol):
        self.s._gcp_iam_set_policy(self.project, pol)

    def keys(self):
        return list(self.sa.get("keys", {}).values())

    def create_key(self):
        from core import gcp_iam_core as iamc
        keys = self.sa.setdefault("keys", {})
        if sum(1 for k in keys.values() if k.get("keyType") == "USER_MANAGED") >= iamc.MAX_USER_KEYS:
            raise T.TabError(400, "FAILED_PRECONDITION", "Precondition check failed: the service account has the maximum of 10 keys.")
        rec, created = iamc.new_key_record(self.project, self.email, str(self.sa.get("uniqueId") or ""))
        keys[T.short(rec["name"])] = rec
        return created

    def key_action(self, kid, action):
        keys = self.sa.setdefault("keys", {})
        if action == "delete":
            keys.pop(kid, None)
        else:
            keys[kid]["disabled"] = action == "disable"


def _iam(op: str, name: str, body: dict):
    out = T.iam_sa_op(_OfflineSA(name), op, body)
    if out is not None and not op.startswith(("get", "list")):
        _usage("iam", op, T.short(name), {k: body.get(k) for k in ("role", "member", "key") if body.get(k)})
    return out


# ---------------------------------------------------------------------------
# API Gateway (API records in the space's gcp_apigateway state) and Eventarc triggers
# (gcp_extras eventarc/triggers) — configs/gateways and filters/destinations through the
# shared engine
# ---------------------------------------------------------------------------
def _apigateway(op: str, name: str, body: dict):
    from routes.gcp_extras import _gcp_apigateway_state
    project = _project()
    api = T.short(name)
    apis = _gcp_apigateway_state(project, "apis")
    if api not in apis:
        raise T.TabError(404, "NOT_FOUND", "API '%s' not found" % api)
    if op == "getLabels":
        return {"ok": True, "item": {"name": api, "labels": apis[api].get("labels") or {}}}
    if op == "setLabels":
        apis[api]["labels"] = T.validate_labels(body.get("labels", {}))
        out = {"ok": True}
    else:
        out = T.apigw_op(tab_state, project, api, op, body)
    if out is not None and not op.startswith(("get", "list")):
        _usage("apigateway", op, api, {k: body.get(k) for k in ("name", "gateway") if body.get(k)})
        _ctx().persist_state()
    return out


class _OfflineTrigger:
    def __init__(self, name):
        from routes.gcp_extras import _gcp_extras_state
        self.items = _gcp_extras_state("eventarc/triggers")["items"]
        self.name = T.short(name)
        if self.name not in self.items:
            raise T.TabError(404, "NOT_FOUND", "Trigger %s not found." % self.name)

    def rec(self):
        return self.items[self.name]

    def update(self, patch):
        self.items[self.name].update(patch)
        _ctx().persist_state()

    def exists(self, kind, name):
        s = _server()
        if kind == "bucket":
            return name in s.gcp_storage_state.get("buckets", {})
        if kind == "function":
            return name in s.gcp_functions_state.get("functions", {})
        if kind == "topic":
            from core import gcp_pubsub_emulator as emu
            return bool(emu.get_topic(_project(), name)) if emu.available() else name in s.gcp_pubsub_state.get("topics", {})
        return False


def _eventarc(op: str, name: str, body: dict):
    out = T.eventarc_op(_OfflineTrigger(name), _project(), op, body)
    if out is not None and not op.startswith(("get", "list")):
        _usage("eventarc", op, T.short(name))
    return out


# ---------------------------------------------------------------------------
# Project IAM policy (every resource's Permissions tab)
# ---------------------------------------------------------------------------
def _iam_project(op: str, project: str, body: dict):
    s = _server()
    proj = s._gcp_project_name(project)
    if op == "getProjectPolicy":
        pol = s._gcp_iam_policy_view(proj)
        return {"ok": True, "project": proj, "bindings": pol.get("bindings", []), "etag": pol.get("etag", "")}
    if op in ("grantAccess", "revokeAccess"):
        cur = s._gcp_iam_policy_view(proj)
        fn = T.policy_grant if op == "grantAccess" else T.policy_revoke
        pol = fn(cur, body.get("role"), body.get("member"))
        out = s._gcp_iam_set_policy(proj, pol)
        _usage("iam", op, proj, {"role": body.get("role"), "member": body.get("member")})
        return {"ok": True, "project": proj, "bindings": (out or pol).get("bindings", [])}
    return None


_HANDLERS = {
    "compute": _compute,
    "storage": _storage,
    "cloudsql": _cloudsql,
    "pubsub": _pubsub,
    "vpc": _vpc,
    "functions": _functions,
    "firestore": _firestore,
    "secretmanager": _secretmanager,
    "kms": _kms,
    "iam": _iam,
    "apigateway": _apigateway,
    "eventarc": _eventarc,
}


async def _dispatch(service: str, op: str, name: str, request: Request):
    body = {}
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
    # /api/gcp/sub isn't a native GCP path, so the provider-alias middleware leaves the request
    # bound to the AWS space; the gcp_* state proxies must resolve the active GCP space.
    from core.app_context import REQUEST_PROVIDER
    token = REQUEST_PROVIDER.set("gcp")
    try:
        out = None
        if service == "iam" and op in ("getProjectPolicy", "grantAccess", "revokeAccess"):
            out = _iam_project(op, name, body)
        elif service in _HANDLERS:
            out = _HANDLERS[service](op, name, body)
        if out is None:
            return JSONResponse({"ok": False, "code": "UNIMPLEMENTED",
                                 "message": "Operation '%s' is not supported for %s." % (op, service)}, status_code=404)
        return JSONResponse(out)
    except T.TabError as e:
        return JSONResponse({"ok": False, "code": e.code, "message": e.message}, status_code=e.status)
    finally:
        REQUEST_PROVIDER.reset(token)


SERVICES = ("compute", "storage", "cloudsql", "pubsub", "firestore", "functions", "apigateway", "vpc",
            "iam", "eventarc", "secretmanager", "kms")


def register(app) -> None:
    for svc in SERVICES:
        async def endpoint(op: str, name: str, request: Request, _svc=svc):
            return await _dispatch(_svc, op, name, request)
        endpoint.__name__ = "gcp_tabs_%s" % svc
        # /api/gcp/sub/... reaches the router as /api/sub/... (provider-alias rewrite); keep both.
        for prefix in ("/api/gcp/sub/", "/api/sub/"):
            app.add_api_route(prefix + svc + "/{op}/{name:path}", endpoint, methods=["GET", "POST"],
                              include_in_schema=False)
