# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Shared schedule runner seam (substrate-independent, pure Python) — makes backup plans / policies actually run on
their schedule instead of only on a button.

  * a spec language every provider maps onto: AWS `cron(...)` / `rate(...)` / `at(...)` (reusing core/scheduler_core's
    evaluator, so Backup plans and EventBridge Scheduler agree), plus `daily@HH:MM`, `weekly@HH:MM@MON,WED`,
    `hourly@N` (every N hours) for Azure Backup policies and Cloud SQL backup windows;
  * `Ticker` — per-key last-fired state kept in `store.account["schedule_seam"]` (so it persists with the S3 store);
  * `tick(router, now)` — one pass over the providers: AWS Backup plans (+ recovery-point DeleteAfterDays expiry),
    Azure Backup policies (+ expiry of recovery points), DLM (reuses core/dlm_core), Cloud SQL automated backup
    windows (+ retainedBackups pruning) and ECR lifecycle policies / continuous scans, and Security Command Center notification configs (new/changed findings -> Pub/Sub). Cloud Scheduler and EventBridge
    Scheduler already advance themselves and are NOT re-run here.

Honest limits: schedules fire from `tick`, which the appliance calls from a background loop (offline) and which Nano calls
from the router while the page is open — a Nano tab that is closed runs nothing; missed fires while nothing was ticking
coalesce into ONE run (no backfill); the first sighting of a schedule only records a baseline (nothing runs on create);
no jitter/start-window randomisation; time zones are UTC (ScheduleExpressionTimezone is not applied); AWS Backup
selections resolve explicit `Resources` ARNs only (tag/condition based selections are listed but not expanded).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _sched():
    try:
        from core import scheduler_core as m
    except ImportError:
        import scheduler_core as m          # type: ignore
    return m


def _mod(name):
    try:
        return __import__("core." + name, fromlist=[name])
    except ImportError:
        return __import__(name)


def _dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def valid(spec: str) -> bool:
    return next_after(spec, 0.0) is not None or spec.startswith("at(")


def next_after(spec: str, after: float):
    """Epoch of the first fire strictly after `after`, or None when the spec never fires / is invalid."""
    if not spec:
        return None
    spec = spec.strip()
    if spec.startswith(("cron(", "rate(", "at(")):
        n = _sched()._next_occurrence(spec, _dt(after))
        return n.timestamp() if n else None
    m = re.match(r"^hourly@(\d+)$", spec)
    if m and int(m.group(1)) >= 1:
        return after + int(m.group(1)) * 3600
    m = re.match(r"^(daily|weekly)@(\d{1,2}):(\d{2})(?:@([A-Z,]+))?$", spec)
    if not m:
        return None
    kind, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    days = set(m.group(4).split(",")) if m.group(4) else set(_DAYS)
    if hh > 23 or mm > 59 or (kind == "weekly" and not (days <= set(_DAYS))):
        return None
    t = _dt(after).replace(hour=hh, minute=mm, second=0, microsecond=0)
    for i in range(0, 9):
        c = t + timedelta(days=i)
        if c.timestamp() > after and (kind == "daily" or _DAYS[c.weekday()] in days):
            return c.timestamp()
    return None


class Ticker:
    def __init__(self, bag: dict):
        self.bag = bag

    def due(self, key: str, spec: str, now: float) -> bool:
        """True (once) when `spec` has fired since this key was last seen; the first sighting only records a baseline."""
        last = self.bag.get(key)
        if last is None:
            self.bag[key] = now
            return False
        nxt = next_after(spec, last)
        if nxt is not None and nxt <= now:
            self.bag[key] = now
            return True
        return False

    def forget_missing(self, prefix: str, live: set):
        for k in [k for k in self.bag if k.startswith(prefix) and k not in live]:
            self.bag.pop(k, None)


# ── providers ─────────────────────────────────────────────────────────────────────────
def _aws_backup(router, now, tk, log):
    bc, bv = _mod("backup_core"), _mod("backup_vaults_core")
    st = bc._state(router.s3)
    bv._init(st)
    live = set()
    ran = 0
    for pid, plan in list(st["plans"].items()):
        doc = plan["BackupPlan"]
        for rule in doc.get("Rules") or []:
            spec = rule.get("ScheduleExpression")
            if not spec:
                continue
            key = f"awsbackup:{pid}:{rule.get('RuleName')}"
            live.add(key)
            if not tk.due(key, spec, now):
                continue
            for sel in [s for s in st["selections"].values() if s["BackupPlanId"] == pid]:
                body = sel["BackupSelection"]
                for arn in body.get("Resources") or []:
                    if "*" in arn:
                        continue
                    status, out = bv._start_backup(router.ddb, router.s3, router.rds, router.vpc, st, {
                        "BackupVaultName": rule["TargetBackupVaultName"], "ResourceArn": arn, "IamRoleArn": body["IamRoleArn"],
                        "Lifecycle": rule.get("Lifecycle"), "StartWindowMinutes": rule.get("StartWindowMinutes", 480),
                        "RecoveryPointTags": rule.get("RecoveryPointTags")},
                        plan_ref={"BackupPlanId": pid, "BackupPlanArn": plan["BackupPlanArn"], "BackupPlanVersion": plan.get("VersionId", ""),
                                  "BackupRuleId": rule.get("RuleId") or rule.get("RuleName")})
                    ran += 1
                    log.append({"provider": "aws-backup", "plan": pid, "rule": rule.get("RuleName"), "resource": arn, "status": status})
    tk.forget_missing("awsbackup:", live)
    # DeleteAfterDays lifecycle expiry
    for arn, rp in list(st["rps"].items()):
        at = (rp.get("CalculatedLifecycle") or {}).get("DeleteAt")
        v = st["vaults"].get(rp.get("BackupVaultName"), {})
        if at and float(at) <= now and not v.get("Locked"):
            bv._drop_rp(router.ddb, router.s3, router.rds, router.vpc, rp)
            st["rps"].pop(arn, None)
            log.append({"provider": "aws-backup", "expired": arn})
    return ran


def _azure_backup(router, now, tk, log):
    ab = _mod("azure_backup_core")
    state = router.az_arm.state
    blob = getattr(router.az_arm, "blob_store", None)
    live = set()
    ran = 0
    for key, item in list(state.items()):
        if not isinstance(item, dict) or item.get("_kind") != "item":
            continue
        ip = item["properties"]
        if ip.get("protectionState") == "ProtectionStopped" or ip.get("isScheduledForDeferredDelete"):
            continue
        pol = state.get((ip.get("policyId") or "").lower())
        sp = ((pol or {}).get("properties") or {}).get("schedulePolicy") or {}
        spec = _azure_spec(sp)
        if not spec:
            continue
        k = "azbackup:" + item["id"].lower()
        live.add(k)
        if not tk.due(k, spec, now):
            continue
        vid = item["id"].split("/backupFabrics/")[0].lower()
        vault = state.get(vid)
        if not vault:
            continue
        r = ab._backup_now(state, vault, item, {}, blob)
        ran += 1
        log.append({"provider": "azure-backup", "item": ip.get("friendlyName"), "status": r.get("status") if isinstance(r, dict) else getattr(r, "status", 0)})
    tk.forget_missing("azbackup:", live)
    nowiso = _dt(now).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for k, rp in list(state.items()):
        if isinstance(rp, dict) and rp.get("_kind") == "rp" and rp.get("_expiry") and rp["_expiry"] < nowiso:
            vid = rp["id"].split("/backupFabrics/")[0].lower()
            vault = state.get(vid)
            if vault and vault["properties"]["securitySettings"]["immutabilitySettings"]["state"] != "Locked":
                ab._art_delete(blob, rp["_artifact"])
                state.pop(k, None)
                log.append({"provider": "azure-backup", "expired": rp["id"]})
    return ran


def _azure_spec(sp: dict):
    freq = sp.get("scheduleRunFrequency")
    if freq == "Hourly":
        n = (sp.get("hourlySchedule") or {}).get("interval") or 4
        return f"hourly@{int(n)}"
    times = sp.get("scheduleRunTimes") or []
    if not times:
        return None
    m = re.search(r"T(\d{2}):(\d{2})", times[0])
    if not m:
        return None
    if freq == "Weekly":
        days = [d[:3].upper() for d in sp.get("scheduleRunDays") or []]
        return f"weekly@{m.group(1)}:{m.group(2)}@{','.join(days)}" if days else None
    return f"daily@{m.group(1)}:{m.group(2)}"


def _dlm(router, now, tk, log):
    d = _mod("dlm_core")
    before = sum(1 for p in router.dlm.policies.values() for s in p["_schedule_state"].values() if s.get("last_run"))
    d._evaluate_due_policies(router.dlm)
    after = sum(1 for p in router.dlm.policies.values() for s in p["_schedule_state"].values() if s.get("last_run"))
    return 0 if after == before else 1


def _cloudsql(router, now, tk, log):
    cs = _mod("gcp_cloudsql_core")
    store = router.gcp_sql
    live = set()
    ran = 0
    for iid in list(store.instance_ids()):
        rec = store.get_instance(iid)
        if not rec or not iid.startswith("cloudsql:") or rec.get("masterInstanceName"):
            continue
        bc = (rec.get("settings") or {}).get("backupConfiguration") or {}
        if not bc.get("enabled"):
            continue
        project, _, instance = iid[len("cloudsql:"):].partition("/")
        k = "cloudsql:" + iid
        live.add(k)
        spec = f"daily@{bc.get('startTime', '03:00')}"
        if tk.due(k, spec, now):
            r = cs._insert_backup(store, project, instance, {"description": "Automated backup (scheduled window)"})
            try:
                bid = __import__("json").loads(r.body)["id"] if isinstance(r.body, (str, bytes)) else r.body["id"]
                snap = store.get_snapshot(cs._backup_key(project, instance, bid))
                if snap:
                    snap["type"] = "AUTOMATED"
                    store.put_snapshot(cs._backup_key(project, instance, bid), snap)
            except Exception:
                pass
            ran += 1
            log.append({"provider": "cloudsql", "instance": instance})
        keep = int((bc.get("backupRetentionSettings") or {}).get("retainedBackups") or 7)
        auto = []
        for b in cs._list_backup_ids(store, project, instance):
            s = store.get_snapshot(cs._backup_key(project, instance, b))
            if s and s.get("type") == "AUTOMATED":
                auto.append((s.get("startTime", ""), b))
        for _, b in sorted(auto)[:-keep] if len(auto) > keep else []:
            store.drop_snapshot(cs._backup_key(project, instance, b))
            log.append({"provider": "cloudsql", "expired": b})
    tk.forget_missing("cloudsql:", live)
    return ran


def _ecr(router, now, tk, log):
    e = _mod("ecr_core")
    if not tk.due("ecr:lifecycle", "rate(15 minutes)", now):
        return 0
    n = e.lifecycle_tick(router.s3, now) + e.rescan_continuous(router.s3)
    if n:
        log.append({"provider": "ecr", "changed": n})
    return n


def _scc(router, now, tk, log):
    if not tk.due("scc:notify", "rate(1 minute)", now):
        return 0
    bag = router.s3.account.get("gcp_scc")
    if not bag or not bag.get("notifs"):
        return 0
    n = _mod("gcp_scc_core").sync_notifications(bag, router.scc_ctx())
    if n:
        log.append({"provider": "scc", "published": n})
    return n


PROVIDERS = [("scc", _scc), ("aws-backup", _aws_backup), ("azure-backup", _azure_backup), ("dlm", _dlm), ("cloudsql", _cloudsql), ("ecr", _ecr)]


def tick(router, now: float | None = None) -> dict:
    """One scheduling pass. Returns {"runs": n, "log": [...], "errors": [...]}; a failing provider never stops the others."""
    now = time.time() if now is None else now
    bag = router.s3.account.setdefault("schedule_seam", {"state": {}, "log": []})
    tk = Ticker(bag["state"])
    log, errors, runs = [], [], 0
    for name, fn in PROVIDERS:
        try:
            runs += fn(router, now, tk, log) or 0
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e!r}")
    bag["log"] = (bag["log"] + [dict(x, at=now) for x in log])[-200:]
    return {"runs": runs, "log": log, "errors": errors}


def status(router) -> dict:
    bag = router.s3.account.setdefault("schedule_seam", {"state": {}, "log": []})
    return {"tracked": sorted(bag["state"]), "recent": bag["log"][-50:]}
