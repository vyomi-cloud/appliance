"""AWS Backup vaults / plans / selections / jobs / recovery points / restore jobs (extension of core/backup_core.py).

handle(...) returns (status, json-doc) or None when the path is not one of these operations. State lives in
``s3_store.account["backup"]`` (the dict passed as ``st``). Recovery points are REAL:
  DynamoDB table -> a dynamodb_core backup (artifact in the simulator S3); RDS instance -> an ``awsbackup:job-*`` DB snapshot with
  the table data; S3 bucket -> a JSON artifact of every object in the simulator's own S3 (bucket ``vyomi-aws-backup``);
  EBS volume -> an EC2 snapshot. Restore jobs create a real table / DB instance / bucket+objects / volume.
Honest limits: see core/backup_core.py docstring (no cron scheduler, no EC2/EFS/FSx/Aurora, no audit/report/restore-testing).
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

ACCT = "123456789012"
REGION = "us-east-1"
ART_BUCKET = "vyomi-aws-backup"
VAULT_RE = re.compile(r"^[A-Za-z0-9\-_]{2,50}$")
CRON_RE = re.compile(r"^cron\((\S+ ){5}\S+\)$")
RATE_RE = re.compile(r"^rate\(\d+ (minute|minutes|hour|hours|day|days)\)$")


def _lazy(n):
    import importlib
    try:
        return importlib.import_module("core." + n)
    except ImportError:
        return importlib.import_module(n)


def _ts(dt=None):
    return round((dt or datetime.now(timezone.utc)).timestamp(), 3)


def _e(status, code, msg):
    return status, {"Code": code, "Message": msg, "Type": code}


def _vault_arn(name, region=REGION):
    return f"arn:aws:backup:{region}:{ACCT}:backup-vault:{name}"


def _init(st):
    st.setdefault("vaults", {})
    st.setdefault("plans", {})
    st.setdefault("selections", {})
    st.setdefault("bjobs", {})
    st.setdefault("rps", {})
    st.setdefault("rjobs", {})
    st.setdefault("tags", {})
    if "Default" not in st["vaults"]:
        st["vaults"]["Default"] = {"BackupVaultName": "Default", "BackupVaultArn": _vault_arn("Default"), "CreationDate": _ts(),
                                   "EncryptionKeyArn": f"arn:aws:kms:{REGION}:{ACCT}:key/aws-backup-default", "Locked": False, "VaultType": "BACKUP_VAULT"}


def _vault_view(st, v):
    out = {k: x for k, x in v.items() if not k.startswith("_") and x is not None}
    out["NumberOfRecoveryPoints"] = sum(1 for r in st["rps"].values() if r["BackupVaultName"] == v["BackupVaultName"])
    return out


# ── lifecycle ───────────────────────────────────────────────────────────────────────
def _check_lifecycle(lc, vault, what="Lifecycle"):
    if not lc:
        return None
    cold, dele = lc.get("MoveToColdStorageAfterDays"), lc.get("DeleteAfterDays")
    for k, x in (("MoveToColdStorageAfterDays", cold), ("DeleteAfterDays", dele)):
        if x is not None and (not isinstance(x, int) or x < 0):
            return f"{what}.{k} must be a non-negative integer."
    if cold is not None and dele is not None and dele < cold + 90:
        return f"{what}: DeleteAfterDays must be at least 90 days more than MoveToColdStorageAfterDays."
    if vault and vault.get("Locked"):
        lo, hi = vault.get("MinRetentionDays"), vault.get("MaxRetentionDays")
        if dele is None and hi is not None:
            return f"Vault {vault['BackupVaultName']} is locked with a max retention; {what}.DeleteAfterDays is required."
        if dele is not None and ((lo is not None and dele < lo) or (hi is not None and dele > hi)):
            return f"{what}.DeleteAfterDays ({dele}) is outside the vault lock retention range [{lo}, {hi}]."
    return None


def _calc(lc):
    now = datetime.now(timezone.utc)
    out = {}
    if lc and lc.get("MoveToColdStorageAfterDays") is not None:
        out["MoveToColdStorageAt"] = _ts(now + timedelta(days=lc["MoveToColdStorageAfterDays"]))
    if lc and lc.get("DeleteAfterDays") is not None:
        out["DeleteAt"] = _ts(now + timedelta(days=lc["DeleteAfterDays"]))
    return out


# ── plans ───────────────────────────────────────────────────────────────────────────
def _check_plan(st, plan):
    if not isinstance(plan, dict) or not plan.get("BackupPlanName"):
        return "BackupPlan.BackupPlanName is required."
    if not re.match(r"^[0-9a-zA-Z\-_.]{1,50}$", plan["BackupPlanName"]):
        return "BackupPlanName must be 1-50 characters: letters, digits, '-', '_' and '.'."
    rules = plan.get("Rules")
    if not rules or not isinstance(rules, list):
        return "BackupPlan.Rules must contain at least one rule."
    names = set()
    for r in rules:
        rn = r.get("RuleName")
        if not rn or not re.match(r"^[0-9a-zA-Z\-_.]{1,50}$", rn):
            return "Each rule needs a RuleName (1-50 chars: letters, digits, '-', '_', '.')."
        if rn in names:
            return f"Duplicate RuleName '{rn}'."
        names.add(rn)
        v = st["vaults"].get(r.get("TargetBackupVaultName", ""))
        if v is None:
            return f"Backup vault {r.get('TargetBackupVaultName')} does not exist (TargetBackupVaultName)."
        sch = r.get("ScheduleExpression")
        if sch is not None and not (CRON_RE.match(sch) or RATE_RE.match(sch)):
            return f"ScheduleExpression '{sch}' is not a valid cron(...) or rate(...) expression."
        sw, cw = r.get("StartWindowMinutes", 480), r.get("CompletionWindowMinutes", 10080)
        if sw < 60:
            return "StartWindowMinutes must be at least 60."
        if cw < sw + 60:
            return "CompletionWindowMinutes must be at least 60 minutes more than StartWindowMinutes."
        bad = _check_lifecycle(r.get("Lifecycle"), v, f"Rule {rn} Lifecycle")
        if bad:
            return bad
        for ca in r.get("CopyActions") or []:
            if not re.match(r"^arn:aws[a-z-]*:backup:[a-z0-9-]+:\d{12}:backup-vault:", ca.get("DestinationBackupVaultArn", "")):
                return "CopyActions.DestinationBackupVaultArn is not a valid backup vault ARN."
    return None


def _plan_doc(plan):
    d = json.loads(json.dumps(plan))
    for r in d["Rules"]:
        r.setdefault("RuleId", str(uuid.uuid4()))
        r.setdefault("StartWindowMinutes", 480)
        r.setdefault("CompletionWindowMinutes", 10080)
    return d


# ── resources ───────────────────────────────────────────────────────────────────────
def _classify(arn):
    if re.match(r"^arn:aws[a-z-]*:dynamodb:[^:]+:\d{12}:table/[^/]+$", arn):
        return "DynamoDB", arn.rsplit("/", 1)[1]
    if re.match(r"^arn:aws[a-z-]*:rds:[^:]+:\d{12}:db:.+$", arn):
        return "RDS", arn.split(":db:", 1)[1]
    if re.match(r"^arn:aws[a-z-]*:s3:::[^/]+$", arn):
        return "S3", arn.split(":::", 1)[1]
    if re.match(r"^arn:aws[a-z-]*:ec2:[^:]+:\d{12}:volume/vol-.+$", arn):
        return "EBS", arn.rsplit("/", 1)[1]
    return None, None


def _s3c(): return _lazy("s3_object_core")
def _rds(): return _lazy("rds_core")
def _ddb(): return _lazy("dynamodb_core")
def _vpc(): return _lazy("vpc_core")


def _capture(ddb, s3, rds, vpc, rtype, name, job_id, vault):
    """Take the real backup. Returns (recovery point arn, size, error)."""
    if rtype == "DynamoDB":
        d = _ddb()
        try:
            b = d._create_backup_record(ddb, {"TableName": name, "BackupName": f"AWSBackup_{job_id[:8]}"}, s3)
        except d.DdbError as e:
            return None, 0, e.message
        b["backup_type"] = "AWS_BACKUP"
        return b["backup_arn"], b.get("backup_size_bytes", 0), None
    if rtype == "RDS":
        if rds is None or not rds.instance_exists(name):
            return None, 0, f"DB instance {name} does not exist."
        r = _rds()
        snap_id = f"awsbackup:job-{job_id.lower()}"
        snap = r._make_snapshot(rds, rds.get_instance(name), snap_id, snapshot_type="awsbackup")
        rds.persist()
        return snap["db_snapshot_arn"], len(json.dumps(snap.get("data", {}), default=str)), None
    if rtype == "S3":
        if not s3.bucket_exists(name):
            return None, 0, f"Bucket {name} does not exist."
        objs = {}
        total = 0
        for k in list(s3.bucket_objects(name)):
            g = _s3c().get_object(s3, name, k, {}, {})
            data = g.body if g.status == 200 and isinstance(g.body, bytes) else None
            if data is None:
                continue
            objs[k] = base64.b64encode(data).decode()
            total += len(data)
        rid = uuid.uuid4().hex
        c = _s3c()
        if not s3.bucket_exists(ART_BUCKET):
            s3.create_bucket(ART_BUCKET)
        c.put_object(s3, ART_BUCKET, f"{vault}/{rid}.json", json.dumps({"bucket": name, "objects": objs}).encode(), {"content-type": "application/json"})
        return f"arn:aws:backup:{REGION}:{ACCT}:recovery-point:{rid}", total, None
    if rtype == "EBS":
        if vpc is None:
            return None, 0, "EC2 is not available."
        v = _vpc()
        m = v._model(vpc)
        if name not in m["volumes"]:
            return None, 0, f"Volume {name} does not exist."
        resp = v._create_snapshot(vpc, {"VolumeId": name, "Description": f"AWS Backup job {job_id}"})
        sid = re.search(r"snapshot_?[iI]d>([^<]+)<|<snapshotId>([^<]+)<", resp.body.decode() if isinstance(resp.body, bytes) else str(resp.body))
        snap_id = (sid.group(1) or sid.group(2)) if sid else max(m["snapshots"], key=lambda k: m["snapshots"][k]["started"])
        return f"arn:aws:ec2:{REGION}::snapshot/{snap_id}", m["volumes"][name]["size"] * 1024 ** 3, None
    return None, 0, "Resource type is not supported by Vyomi's AWS Backup (supported: DynamoDB, RDS, S3, EBS)."


def _drop_rp(ddb, s3, rds, vpc, rp):
    arn, t = rp["RecoveryPointArn"], rp["ResourceType"]
    try:
        if t == "DynamoDB":
            b = ddb.get_backup(arn)
            if b:
                _ddb().backup_delete_artifact(s3, b)
                ddb.drop_backup(arn)
        elif t == "RDS" and rds is not None:
            rds.drop_snapshot(arn.split(":snapshot:", 1)[1])
        elif t == "S3":
            rid = arn.rsplit(":", 1)[1]
            s3.bucket_objects(ART_BUCKET).pop(f"{rp['BackupVaultName']}/{rid}.json", None)
        elif t == "EBS" and vpc is not None:
            _vpc()._model(vpc)["snapshots"].pop(arn.rsplit("/", 1)[1], None)
    except Exception:  # noqa: BLE001
        pass


def _rp_view(rp, full=True):
    keys = ("RecoveryPointArn", "BackupVaultName", "BackupVaultArn", "ResourceArn", "ResourceType", "ResourceName", "CreationDate", "CompletionDate",
            "Status", "BackupSizeInBytes", "IamRoleArn", "CalculatedLifecycle", "Lifecycle", "IsEncrypted", "EncryptionKeyArn", "BackupJobId", "CreatedBy")
    return {k: rp[k] for k in keys if k in rp and rp[k] is not None}


def _start_backup(ddb, s3, rds, vpc, st, p, plan_ref=None):
    for need in ("BackupVaultName", "ResourceArn", "IamRoleArn"):
        if not p.get(need):
            return _e(400, "MissingParameterValueException", f"Missing required parameter: {need}")
    v = st["vaults"].get(p["BackupVaultName"])
    if v is None:
        return _e(404, "ResourceNotFoundException", f"Backup vault {p['BackupVaultName']} does not exist.")
    if not re.match(r"^arn:aws[a-z-]*:iam::\d{12}:role/.+$", p["IamRoleArn"]):
        return _e(400, "InvalidParameterValueException", "IamRoleArn is not a valid IAM role ARN.")
    bad = _check_lifecycle(p.get("Lifecycle"), v)
    if bad:
        return _e(400, "InvalidParameterValueException", bad)
    rtype, name = _classify(p["ResourceArn"])
    jid = uuid.uuid4().hex.upper()
    job = {"BackupJobId": jid, "BackupVaultName": v["BackupVaultName"], "BackupVaultArn": v["BackupVaultArn"], "ResourceArn": p["ResourceArn"],
           "ResourceType": rtype or "Unknown", "ResourceName": name, "CreationDate": _ts(), "IamRoleArn": p["IamRoleArn"], "AccountId": ACCT,
           "State": "RUNNING", "StartBy": _ts(datetime.now(timezone.utc) + timedelta(minutes=p.get("StartWindowMinutes", 480))), "BackupType": "Full"}
    if plan_ref:
        job["CreatedBy"] = plan_ref
    rp_arn, size, err = _capture(ddb, s3, rds, vpc, rtype, name, jid, v["BackupVaultName"]) if rtype else (None, 0, "Resource type is not supported by Vyomi's AWS Backup (supported: DynamoDB, RDS, S3, EBS).")
    if err:
        job.update({"State": "FAILED", "StatusMessage": err, "CompletionDate": _ts()})
        st["bjobs"][jid] = job
        return 200, {"BackupJobId": jid, "CreationDate": job["CreationDate"], "IsParent": False}
    rp = {"RecoveryPointArn": rp_arn, "BackupVaultName": v["BackupVaultName"], "BackupVaultArn": v["BackupVaultArn"], "ResourceArn": p["ResourceArn"],
          "ResourceType": rtype, "ResourceName": name, "CreationDate": job["CreationDate"], "CompletionDate": _ts(), "Status": "COMPLETED",
          "BackupSizeInBytes": size, "IamRoleArn": p["IamRoleArn"], "Lifecycle": p.get("Lifecycle"), "CalculatedLifecycle": _calc(p.get("Lifecycle")),
          "IsEncrypted": bool(v.get("EncryptionKeyArn")), "EncryptionKeyArn": v.get("EncryptionKeyArn"), "BackupJobId": jid}
    st["rps"][rp_arn] = rp
    if p.get("RecoveryPointTags"):
        st["tags"][rp_arn] = dict(p["RecoveryPointTags"])
    job.update({"State": "COMPLETED", "RecoveryPointArn": rp_arn, "CompletionDate": _ts(), "BackupSizeInBytes": size, "PercentDone": "100.0",
                "ExpectedCompletionDate": _ts()})
    st["bjobs"][jid] = job
    return 200, {"BackupJobId": jid, "RecoveryPointArn": rp_arn, "CreationDate": job["CreationDate"], "IsParent": False}


def _restore(ddb, s3, rds, vpc, st, p):
    arn = p.get("RecoveryPointArn")
    if not arn:
        return _e(400, "MissingParameterValueException", "Missing required parameter: RecoveryPointArn")
    rp = st["rps"].get(arn)
    if rp is None:
        return _e(404, "ResourceNotFoundException", f"Recovery point {arn} does not exist.")
    md = p.get("Metadata") or {}
    jid = uuid.uuid4().hex.upper()
    job = {"RestoreJobId": jid, "RecoveryPointArn": arn, "CreationDate": _ts(), "Status": "RUNNING", "ResourceType": rp["ResourceType"],
           "IamRoleArn": p.get("IamRoleArn"), "AccountId": ACCT, "BackupSizeInBytes": rp.get("BackupSizeInBytes")}
    t = rp["ResourceType"]
    created = None
    try:
        if t == "DynamoDB":
            target = md.get("targetTableName") or md.get("TargetTableName")
            if not target:
                return _e(400, "InvalidParameterValueException", "Metadata.targetTableName is required to restore a DynamoDB recovery point.")
            d = _ddb()
            try:
                tbl = d._restore_table_from_backup(ddb, {"BackupArn": arn, "TargetTableName": target}, s3)
            except d.DdbError as e:
                raise ValueError(e.message)
            created = tbl["table_arn"]
        elif t == "RDS":
            target = md.get("DBInstanceIdentifier") or md.get("dbinstanceidentifier")
            if not target:
                return _e(400, "InvalidParameterValueException", "Metadata.DBInstanceIdentifier is required to restore an RDS recovery point.")
            r = _rds()
            resp = r.dispatch(rds, {"Action": "RestoreDBInstanceFromDBSnapshot", "DBSnapshotIdentifier": arn.split(":snapshot:", 1)[1],
                                    "DBInstanceIdentifier": target, "DBInstanceClass": md.get("DBInstanceClass", "db.t3.micro")}, s3_store=s3)
            if resp.status >= 300:
                raise ValueError(re.sub(r"<[^>]+>", " ", resp.body.decode() if isinstance(resp.body, bytes) else str(resp.body)).strip())
            created = r._instance_arn(rds, target)
            snap = rds.get_snapshot(arn.split(":snapshot:", 1)[1]) or {}
            tables = (snap.get("data") or {}).get("tables")
            if tables:
                sq = _lazy("sql_store")
                for stmt in sq.split_sql(sq.sql_dump(tables, sq.engine_dialect(rds), "AWS Backup restore")):
                    rds.execute_sql(target, stmt)
        elif t == "S3":
            dest = md.get("DestinationBucketName") or md.get("destinationbucketname")
            if not dest:
                return _e(400, "InvalidParameterValueException", "Metadata.DestinationBucketName is required to restore an S3 recovery point.")
            new = str(md.get("NewBucket", "true")).lower() == "true"
            if s3.bucket_exists(dest) and new:
                raise ValueError(f"Bucket {dest} already exists; set NewBucket=false to restore into it.")
            if not s3.bucket_exists(dest):
                if not new:
                    raise ValueError(f"Bucket {dest} does not exist.")
                s3.create_bucket(dest)
            rid = arn.rsplit(":", 1)[1]
            g = _s3c().get_object(s3, ART_BUCKET, f"{rp['BackupVaultName']}/{rid}.json", {}, {})
            raw = g.body if g.status == 200 else None
            if raw is None:
                raise ValueError("The recovery point's backup artifact is missing.")
            c = _s3c()
            for k, b64 in json.loads(raw)["objects"].items():
                c.put_object(s3, dest, k, base64.b64decode(b64), {})
            created = f"arn:aws:s3:::{dest}"
        elif t == "EBS":
            v = _vpc()
            az = md.get("availabilityZone") or md.get("AvailabilityZone") or f"{REGION}a"
            resp = v._create_volume(vpc, {"SnapshotId": arn.rsplit("/", 1)[1], "AvailabilityZone": az, "VolumeType": md.get("volumeType", "gp3")})
            m = v._model(vpc)
            vid = max(m["volumes"], key=lambda k: m["volumes"][k]["created"])
            created = f"arn:aws:ec2:{REGION}:{ACCT}:volume/{vid}"
        else:
            raise ValueError("Unsupported resource type.")
    except ValueError as e:
        job.update({"Status": "FAILED", "StatusMessage": str(e), "CompletionDate": _ts()})
        st["rjobs"][jid] = job
        return 200, {"RestoreJobId": jid}
    job.update({"Status": "COMPLETED", "CreatedResourceArn": created, "PercentDone": "100.0%", "CompletionDate": _ts()})
    st["rjobs"][jid] = job
    return 200, {"RestoreJobId": jid}


def _lock(st, v, p):
    lo, hi, ch = p.get("MinRetentionDays"), p.get("MaxRetentionDays"), p.get("ChangeableForDays")
    if lo is None and hi is None:
        return _e(400, "MissingParameterValueException", "MinRetentionDays or MaxRetentionDays is required.")
    for n, x in (("MinRetentionDays", lo), ("MaxRetentionDays", hi)):
        if x is not None and (not isinstance(x, int) or not 1 <= x <= 36500):
            return _e(400, "InvalidParameterValueException", f"{n} must be between 1 and 36500.")
    if lo is not None and hi is not None and hi < lo:
        return _e(400, "InvalidParameterValueException", "MaxRetentionDays must be >= MinRetentionDays.")
    if ch is not None and (not isinstance(ch, int) or not 3 <= ch <= 365):
        return _e(400, "InvalidParameterValueException", "ChangeableForDays must be between 3 and 365.")
    if v.get("Locked") and v.get("LockDate") and v["LockDate"] <= _ts():
        return _e(400, "InvalidRequestException", f"Vault {v['BackupVaultName']} is locked in compliance mode and its lock can no longer be changed.")
    v.update({"Locked": True, "MinRetentionDays": lo, "MaxRetentionDays": hi, "LockDate": _ts(datetime.now(timezone.utc) + timedelta(days=ch)) if ch else _ts()})
    return 200, None


def handle(ddb, s3, rds, vpc, st, method, path, query, p):
    _init(st)
    path = unquote(path)
    segs = [s for s in path.split("/") if s]
    if not segs:
        return None
    k = segs[0]
    # vaults
    if k == "backup-vaults":
        if len(segs) == 1:
            if method == "GET":
                return 200, {"BackupVaultList": [_vault_view(st, v) for v in st["vaults"].values()]}
            return None
        name = segs[1]
        v = st["vaults"].get(name)
        if len(segs) == 2:
            if method == "PUT":
                if not VAULT_RE.match(name):
                    return _e(400, "InvalidParameterValueException", "Backup vault names are 2-50 characters: letters, digits, '-' and '_'.")
                if v is not None:
                    if v.get("_creator") and v["_creator"] == p.get("CreatorRequestId"):
                        return 200, {"BackupVaultName": name, "BackupVaultArn": v["BackupVaultArn"], "CreationDate": v["CreationDate"]}
                    return _e(400, "AlreadyExistsException", f"Backup vault with name {name} already exists.")
                v = {"BackupVaultName": name, "BackupVaultArn": _vault_arn(name), "CreationDate": _ts(), "Locked": False, "VaultType": "BACKUP_VAULT",
                     "EncryptionKeyArn": p.get("EncryptionKeyArn") or f"arn:aws:kms:{REGION}:{ACCT}:key/aws-backup-default", "_creator": p.get("CreatorRequestId")}
                st["vaults"][name] = v
                if p.get("BackupVaultTags"):
                    st["tags"][v["BackupVaultArn"]] = dict(p["BackupVaultTags"])
                return 200, {"BackupVaultName": name, "BackupVaultArn": v["BackupVaultArn"], "CreationDate": v["CreationDate"]}
            if v is None:
                return _e(404, "ResourceNotFoundException", f"Backup vault with name {name} not found.")
            if method == "GET":
                return 200, _vault_view(st, v)
            if method == "DELETE":
                if any(r["BackupVaultName"] == name for r in st["rps"].values()):
                    return _e(400, "InvalidRequestException", f"Backup vault {name} cannot be deleted because it contains recovery points.")
                st["vaults"].pop(name)
                return 200, None
        if v is None:
            return _e(404, "ResourceNotFoundException", f"Backup vault with name {name} not found.")
        sub = segs[2]
        if sub == "vault-lock":
            if method == "PUT":
                return _lock(st, v, p)
            if method == "DELETE":
                if v.get("Locked") and v.get("LockDate") and v["LockDate"] <= _ts():
                    return _e(400, "InvalidRequestException", "The vault lock is in compliance mode and cannot be removed.")
                for x in ("Locked", "MinRetentionDays", "MaxRetentionDays", "LockDate"):
                    v.pop(x, None)
                v["Locked"] = False
                return 200, None
        if sub == "access-policy":
            if method == "PUT":
                v["_policy"] = p.get("Policy")
                return 200, None
            if method == "GET":
                return (200, {"BackupVaultName": name, "BackupVaultArn": v["BackupVaultArn"], "Policy": v["_policy"]}) if v.get("_policy") else _e(404, "ResourceNotFoundException", "No access policy is set on this vault.")
            if method == "DELETE":
                v.pop("_policy", None)
                return 200, None
        if sub == "notification-configuration":
            if method == "PUT":
                if not p.get("SNSTopicArn") or not p.get("BackupVaultEvents"):
                    return _e(400, "MissingParameterValueException", "SNSTopicArn and BackupVaultEvents are required.")
                v["_notif"] = {"SNSTopicArn": p["SNSTopicArn"], "BackupVaultEvents": p["BackupVaultEvents"]}
                return 200, None
            if method == "GET":
                return (200, dict(v["_notif"], BackupVaultName=name, BackupVaultArn=v["BackupVaultArn"])) if v.get("_notif") else _e(404, "ResourceNotFoundException", "No notification configuration.")
            if method == "DELETE":
                v.pop("_notif", None)
                return 200, None
        if sub == "recovery-points":
            rows = [r for r in st["rps"].values() if r["BackupVaultName"] == name]
            if len(segs) == 3 and method == "GET":
                for qk, f in (("resourceArn", "ResourceArn"), ("resourceType", "ResourceType")):
                    if query.get(qk):
                        rows = [r for r in rows if r.get(f) == query[qk]]
                return 200, {"RecoveryPoints": [_rp_view(r) for r in rows]}
            if len(segs) >= 4:
                arn = "/".join(segs[3:])
                rp = st["rps"].get(arn)
                if rp is None or rp["BackupVaultName"] != name:
                    return _e(404, "ResourceNotFoundException", f"Recovery point {arn} does not exist in vault {name}.")
                if method == "GET":
                    return 200, _rp_view(rp)
                if method == "DELETE":
                    dl = (rp.get("CalculatedLifecycle") or {}).get("DeleteAt")
                    lo = v.get("MinRetentionDays")
                    if v.get("Locked") and lo is not None and rp["CreationDate"] + lo * 86400 > _ts():
                        return _e(400, "InvalidRequestException", f"The vault is locked: recovery point {arn} cannot be deleted before its minimum retention of {lo} days ends.")
                    _drop_rp(ddb, s3, rds, vpc, rp)
                    st["rps"].pop(arn)
                    return 200, None
                if method == "POST":
                    bad = _check_lifecycle(p.get("Lifecycle"), v)
                    if bad:
                        return _e(400, "InvalidParameterValueException", bad)
                    rp["Lifecycle"], rp["CalculatedLifecycle"] = p.get("Lifecycle"), _calc(p.get("Lifecycle"))
                    return 200, {"BackupVaultArn": v["BackupVaultArn"], "RecoveryPointArn": arn, "Lifecycle": rp["Lifecycle"], "CalculatedLifecycle": rp["CalculatedLifecycle"]}
        return None
    # plans
    if k == "backup" and len(segs) >= 2 and segs[1] == "plans":
        if len(segs) == 2:
            if method == "PUT":
                plan = p.get("BackupPlan")
                bad = _check_plan(st, plan)
                if bad:
                    return _e(400, "InvalidParameterValueException", bad)
                pid = str(uuid.uuid4())
                ver = uuid.uuid4().hex
                doc = _plan_doc(plan)
                st["plans"][pid] = {"BackupPlanId": pid, "BackupPlanArn": f"arn:aws:backup:{REGION}:{ACCT}:backup-plan:{pid}", "CreationDate": _ts(), "VersionId": ver,
                                    "BackupPlan": doc, "_versions": {ver: doc}}
                if p.get("BackupPlanTags"):
                    st["tags"][st["plans"][pid]["BackupPlanArn"]] = dict(p["BackupPlanTags"])
                return 200, {"BackupPlanId": pid, "BackupPlanArn": st["plans"][pid]["BackupPlanArn"], "CreationDate": st["plans"][pid]["CreationDate"], "VersionId": ver}
            if method == "GET":
                return 200, {"BackupPlansList": [{k2: v2 for k2, v2 in pl.items() if k2 in ("BackupPlanId", "BackupPlanArn", "CreationDate", "VersionId")} |
                                                 {"BackupPlanName": pl["BackupPlan"]["BackupPlanName"]} for pl in st["plans"].values()]}
            return None
        pid = segs[2]
        pl = st["plans"].get(pid)
        if len(segs) == 3:
            if pl is None:
                return _e(404, "ResourceNotFoundException", f"Backup plan {pid} does not exist.")
            if method == "GET":
                return 200, {k2: v2 for k2, v2 in pl.items() if not k2.startswith("_")}
            if method == "POST":
                bad = _check_plan(st, p.get("BackupPlan"))
                if bad:
                    return _e(400, "InvalidParameterValueException", bad)
                ver = uuid.uuid4().hex
                doc = _plan_doc(p["BackupPlan"])
                pl.update({"BackupPlan": doc, "VersionId": ver})
                pl["_versions"][ver] = doc
                return 200, {"BackupPlanId": pid, "BackupPlanArn": pl["BackupPlanArn"], "CreationDate": _ts(), "VersionId": ver}
            if method == "DELETE":
                if any(s["BackupPlanId"] == pid for s in st["selections"].values()):
                    return _e(400, "InvalidRequestException", "Backup plan has selections; delete them first.")
                st["plans"].pop(pid)
                return 200, {"BackupPlanId": pid, "BackupPlanArn": pl["BackupPlanArn"], "DeletionDate": _ts(), "VersionId": pl["VersionId"]}
        if pl is None:
            return _e(404, "ResourceNotFoundException", f"Backup plan {pid} does not exist.")
        if segs[3] == "versions":
            return 200, {"BackupPlanVersionsList": [{"BackupPlanId": pid, "VersionId": v2, "BackupPlanName": d["BackupPlanName"]} for v2, d in pl["_versions"].items()]}
        if segs[3] == "selections":
            if len(segs) == 4:
                if method == "PUT":
                    sel = p.get("BackupSelection") or {}
                    if not sel.get("SelectionName") or not sel.get("IamRoleArn"):
                        return _e(400, "MissingParameterValueException", "SelectionName and IamRoleArn are required.")
                    if not sel.get("Resources") and not sel.get("ListOfTags") and not sel.get("Conditions"):
                        return _e(400, "InvalidParameterValueException", "A selection needs Resources, ListOfTags or Conditions.")
                    for t in sel.get("ListOfTags") or []:
                        if t.get("ConditionType") != "STRINGEQUALS" or not t.get("ConditionKey"):
                            return _e(400, "InvalidParameterValueException", "ListOfTags entries need ConditionType STRINGEQUALS and a ConditionKey.")
                    sid = str(uuid.uuid4())
                    st["selections"][sid] = {"SelectionId": sid, "BackupPlanId": pid, "CreationDate": _ts(), "BackupSelection": sel}
                    return 200, {"SelectionId": sid, "BackupPlanId": pid, "CreationDate": st["selections"][sid]["CreationDate"]}
                if method == "GET":
                    return 200, {"BackupSelectionsList": [{"SelectionId": s["SelectionId"], "SelectionName": s["BackupSelection"]["SelectionName"], "BackupPlanId": pid,
                                                           "CreationDate": s["CreationDate"], "IamRoleArn": s["BackupSelection"]["IamRoleArn"]}
                                                          for s in st["selections"].values() if s["BackupPlanId"] == pid]}
            else:
                s = st["selections"].get(segs[4])
                if s is None or s["BackupPlanId"] != pid:
                    return _e(404, "ResourceNotFoundException", f"Backup selection {segs[4]} does not exist.")
                if method == "GET":
                    return 200, s
                if method == "DELETE":
                    st["selections"].pop(segs[4])
                    return 200, None
        return None
    # jobs
    if k == "backup-jobs":
        if len(segs) == 1:
            if method == "PUT":
                return _start_backup(ddb, s3, rds, vpc, st, p)
            if method == "GET":
                rows = list(st["bjobs"].values())
                for qk, f in (("resourceArn", "ResourceArn"), ("state", "State"), ("backupVaultName", "BackupVaultName"), ("resourceType", "ResourceType")):
                    if query.get(qk):
                        rows = [r for r in rows if r.get(f) == query[qk]]
                return 200, {"BackupJobs": rows}
        else:
            j = st["bjobs"].get(segs[1])
            if j is None:
                return _e(404, "ResourceNotFoundException", f"Backup job {segs[1]} does not exist.")
            if method == "GET":
                return 200, j
            if method == "POST":
                if j["State"] in ("COMPLETED", "FAILED", "ABORTED"):
                    return _e(400, "InvalidRequestException", f"The backup job is already {j['State']} and cannot be stopped.")
                j["State"] = "ABORTED"
                return 200, None
        return None
    # restore jobs
    if k == "restore-jobs":
        if len(segs) == 1:
            if method == "PUT":
                return _restore(ddb, s3, rds, vpc, st, p)
            if method == "GET":
                rows = list(st["rjobs"].values())
                if query.get("status"):
                    rows = [r for r in rows if r["Status"] == query["status"]]
                return 200, {"RestoreJobs": rows}
        else:
            j = st["rjobs"].get(segs[1])
            if j is None:
                return _e(404, "ResourceNotFoundException", f"Restore job {segs[1]} does not exist.")
            return (200, j) if method == "GET" else None
        return None
    if k == "recovery-points" and len(segs) >= 3 and segs[-1] == "restore-metadata":
        arn = "/".join(segs[1:-1])
        rp = st["rps"].get(arn)
        if rp is None:
            return _e(404, "ResourceNotFoundException", f"Recovery point {arn} does not exist.")
        md = {"DynamoDB": {"targetTableName": rp.get("ResourceName", "")}, "RDS": {"DBInstanceIdentifier": rp.get("ResourceName", ""), "DBInstanceClass": "db.t3.micro"},
              "S3": {"DestinationBucketName": "", "NewBucket": "true"}, "EBS": {"availabilityZone": f"{REGION}a", "volumeType": "gp3"}}.get(rp["ResourceType"], {})
        return 200, {"BackupVaultArn": rp["BackupVaultArn"], "RecoveryPointArn": arn, "ResourceType": rp["ResourceType"], "RestoreMetadata": md}
    if k == "resources" and len(segs) == 1 and method == "GET":
        seen = {}
        for r in st["rps"].values():
            seen[r["ResourceArn"]] = {"ResourceArn": r["ResourceArn"], "ResourceType": r["ResourceType"], "ResourceName": r["ResourceName"], "LastBackupTime": r["CreationDate"]}
        return 200, {"Results": list(seen.values())}
    if k == "resources" and len(segs) >= 3 and segs[-1] == "recovery-points" and method == "GET":
        arn = "/".join(segs[1:-1])
        return 200, {"RecoveryPoints": [_rp_view(r) for r in st["rps"].values() if r["ResourceArn"] == arn]}
    if k == "tags" and len(segs) >= 2:
        arn = "/".join(segs[1:])
        if method == "GET":
            return 200, {"Tags": st["tags"].get(arn, {})}
        if method == "POST":
            st["tags"].setdefault(arn, {}).update(p.get("Tags") or {})
            return 200, None
    if k == "untag" and len(segs) >= 2 and method == "POST":
        arn = "/".join(segs[1:])
        for t in p.get("TagKeyList") or []:
            st["tags"].get(arn, {}).pop(t, None)
        return 200, None
    if k == "supported-resource-types" and method == "GET":
        return 200, {"ResourceTypes": ["DynamoDB", "EBS", "RDS", "S3"]}
    return None
