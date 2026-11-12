"""AWS Backup (service `backup`, SigV4 signing name `backup`, rest-json) — the subset DynamoDB's Backups page uses.

 * DescribeRegionSettings (GET /account-settings) / UpdateRegionSettings (PUT /account-settings): the per-service opt-in
   and "advanced features / full management" preferences. DynamoDB defaults to ON; turning DynamoDB's management
   preference off disables copy jobs for it.
 * StartCopyJob (PUT /copy-jobs) / DescribeCopyJob (GET /copy-jobs/{id}) / ListCopyJobs (GET /copy-jobs): copies a
   DynamoDB backup (recovery point = the DynamoDB BackupArn) to a destination vault in another Region / account. The copy
   is REAL: the source backup's S3 artifact (core/dynamodb_core backup_*_artifact) is copied to a new location in the
   simulator's own S3 and registered as a new backup under the destination ARN, which can be restored.

Full AWS Backup control plane (see backup_vaults_core): vaults (create/describe/list/delete, vault lock, access policy,
notifications), plans (rules validated: cron schedule, start/completion windows, lifecycle 90-day cold-storage rule, vault-lock
retention bounds, copy actions) + versions, selections (ARNs / tag conditions), backup jobs for DynamoDB tables, RDS instances
(a real ``awsbackup:job-*`` DB snapshot), S3 buckets (every object captured as a JSON artifact in the simulator's own S3) and EBS
volumes (a real EC2 snapshot), recovery points (list/describe/delete/lifecycle, vault-lock enforced) and RESTORE jobs that create
real resources (DynamoDB table, RDS instance with the snapshot's data, S3 bucket with the objects, EBS volume).

Honest limit: Vyomi simulates one account and one data plane, so "another Region/account" is a destination ARN + its own
S3 artifact + its own backup record, not a separate isolated Region. Backup PLANS are not run on their cron schedule (there is
no scheduler): run them with StartBackupJob; EC2 instance/AMI, EFS, FSx, Aurora clusters, Redshift and VM-level resources are not
backed up (StartBackupJob for them fails with an unsupported-resource message); Backup Audit Manager, report plans, restore testing
and logically air-gapped vaults are not modelled. State: `s3_store.account["backup"]`.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

_VAULT_ARN = re.compile(r"^arn:aws[-a-z0-9]*:backup:([a-z0-9-]+):(\d{12}):backup-vault:([A-Za-z0-9\-_]{2,50})$")
_SERVICES = ("Aurora", "CloudFormation", "DocumentDB", "DSQL", "DynamoDB", "EBS", "EC2", "EFS", "FSx", "Neptune", "RDS",
             "Redshift", "S3", "SAP HANA on Amazon EC2", "Storage Gateway", "Timestream", "VirtualMachine")


def _ddb():
    try:
        from core import dynamodb_core as m
    except ImportError:  # Pyodide flat layout
        import dynamodb_core as m  # type: ignore
    return m


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m  # type: ignore
    return m


def _state(s3_store) -> dict:
    st = s3_store.account.setdefault("backup", {})
    st.setdefault("opt_in", {k: True for k in _SERVICES})
    st.setdefault("management", {"DynamoDB": True, "EFS": True})
    st.setdefault("jobs", {})
    return st


def _resp(status: int, doc):
    m = _s3c()
    body = b"" if doc is None else json.dumps(doc).encode()
    return m.S3Response(status=status, headers=m._amz_headers(), body=body, media_type="application/json")


def _err(code: str, message: str, status: int):
    r = _resp(status, {"Code": code, "Message": message, "Type": code})
    r.headers["x-amzn-ErrorType"] = code
    return r


def _ts() -> float:
    return round(datetime.now(timezone.utc).timestamp(), 3)


def _job_view(j: dict) -> dict:
    return {k: v for k, v in j.items() if v is not None}


def _start_copy(ddb_store, s3_store, p: dict):
    ddb = _ddb()
    st = _state(s3_store)
    for need in ("RecoveryPointArn", "SourceBackupVaultName", "DestinationBackupVaultArn", "IamRoleArn"):
        if not p.get(need):
            return _err("MissingParameterValueException", f"Missing required parameter: {need}", 400)
    mt = _VAULT_ARN.match(str(p["DestinationBackupVaultArn"]))
    if not mt:
        return _err("InvalidParameterValueException", "DestinationBackupVaultArn is not a valid backup vault ARN.", 400)
    dest_region, dest_acct, dest_vault = mt.groups()
    src_arn = str(p["RecoveryPointArn"])
    backup = ddb_store.get_backup(src_arn)
    if not backup:
        return _err("ResourceNotFoundException", f"Recovery point {src_arn} was not found.", 404)
    if not st["management"].get("DynamoDB", True) or not st["opt_in"].get("DynamoDB", True):
        return _err("InvalidRequestException", "AWS Backup advanced features for DynamoDB are turned off in this Region; "
                    "turn them on (UpdateRegionSettings) to copy backups.", 400)
    jid = uuid.uuid4().hex.upper()
    job = {"CopyJobId": jid, "AccountId": "123456789012", "CreationDate": _ts(), "ResourceType": "DynamoDB",
           "ResourceArn": backup["table_arn"], "ResourceName": backup["table_name"], "RecoveryPointArn": src_arn,
           "SourceBackupVaultArn": f"arn:aws:backup:us-east-1:123456789012:backup-vault:{p['SourceBackupVaultName']}",
           "DestinationBackupVaultArn": p["DestinationBackupVaultArn"], "IamRoleArn": p["IamRoleArn"],
           "State": "RUNNING", "IsParent": False}
    try:
        if not backup.get("s3_bucket"):
            raise ddb.DdbError("BackupNotFoundException", "This backup has no stored data to copy (no S3 store was wired when it was created).", 400)
        _meta, data = ddb.backup_read_artifact(s3_store, backup)
        new_id = uuid.uuid4().hex[:16]
        new_arn = f"arn:aws:dynamodb:{dest_region}:{dest_acct}:table/{backup['table_name']}/backup/{new_id}"
        prefix = f"AWSDynamoDB/backup-copies/{dest_acct}/{dest_region}/{dest_vault}/{backup['table_name']}/{new_id}"
        meta = dict(_meta)
        meta["backup_arn"] = new_arn
        if not ddb.backup_write_artifact(s3_store, backup["s3_bucket"], prefix, meta, data):
            raise ddb.DdbError("BackupInUseException", "Could not write the copy to S3.", 400)
        copy_rec = dict(backup)
        copy_rec.update({"backup_arn": new_arn, "backup_type": "AWS_BACKUP", "backup_creation_datetime": ddb._now(),
                         "s3_prefix": prefix, "copied_from": src_arn, "region": dest_region, "account": dest_acct,
                         "source_table": dict(backup.get("source_table") or {})})
        ddb_store.put_backup(new_arn, copy_rec)
        job.update({"State": "COMPLETED", "CompletionDate": _ts(), "BackupSizeInBytes": len(data),
                    "DestinationRecoveryPointArn": new_arn})
    except ddb.DdbError as e:
        job.update({"State": "FAILED", "CompletionDate": _ts(), "StatusMessage": e.message})
    st["jobs"][jid] = job
    ddb_store.persist()
    s3_store.persist()
    return _resp(200, {"CopyJobId": jid, "CreationDate": job["CreationDate"], "IsParent": False})


def dispatch(ddb_store, s3_store, method: str, raw_path: str, query: dict, body: bytes, rds_store=None, vpc_store=None):
    method = method.upper()
    path = "/" + raw_path.strip("/")
    st = _state(s3_store)
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return _err("InvalidParameterValueException", "The request body must be a JSON object.", 400)
    if path == "/account-settings":
        if method == "GET":
            return _resp(200, {"ResourceTypeOptInPreference": st["opt_in"], "ResourceTypeManagementPreference": st["management"],
                               "LastUpdateTime": st.get("updated")} if st.get("updated") else
                         {"ResourceTypeOptInPreference": st["opt_in"], "ResourceTypeManagementPreference": st["management"]})
        if method == "PUT":
            for fld, tgt in (("ResourceTypeOptInPreference", "opt_in"), ("ResourceTypeManagementPreference", "management")):
                for k, v in (p.get(fld) or {}).items():
                    if not isinstance(v, bool):
                        return _err("InvalidParameterValueException", f"{fld}.{k} must be a boolean.", 400)
                    if tgt == "opt_in" and k not in _SERVICES:
                        return _err("InvalidParameterValueException", f"Unknown resource type {k}.", 400)
                    st[tgt][k] = v
            st["updated"] = _ts()
            s3_store.persist()
            return _resp(200, None)
    if path == "/copy-jobs":
        if method == "PUT":
            return _start_copy(ddb_store, s3_store, p)
        if method == "GET":
            jobs = sorted(st["jobs"].values(), key=lambda j: j["CreationDate"], reverse=True)
            for key, fld in (("resourceArn", "ResourceArn"), ("state", "State"), ("resourceType", "ResourceType")):
                if query.get(key):
                    jobs = [j for j in jobs if j.get(fld) == query[key]]
            return _resp(200, {"CopyJobs": [_job_view(j) for j in jobs]})
    mt = re.match(r"^/copy-jobs/([A-Za-z0-9-]+)$", path)
    if mt and method == "GET":
        j = st["jobs"].get(mt.group(1))
        if not j:
            return _err("ResourceNotFoundException", f"Copy job {mt.group(1)} was not found.", 404)
        return _resp(200, {"CopyJob": _job_view(j)})
    try:
        from core import backup_vaults_core as ext
    except ImportError:  # Pyodide flat layout
        import backup_vaults_core as ext  # type: ignore
    r = ext.handle(ddb_store, s3_store, rds_store, vpc_store, st, method, path, query, p)
    if r is not None:
        status, doc = r
        return _resp(status, doc) if status < 400 else _err(doc["Code"], doc["Message"], status)
    return _err("NotFoundException", f"Unsupported AWS Backup operation: {method} {path}", 404)
