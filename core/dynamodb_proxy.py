"""Transparent proxy to amazon/dynamodb-local.

boto3's DynamoDB client uses ``X-Amz-Target: DynamoDB_20120810.<Op>`` + a JSON
body. DynamoDB Local speaks the identical wire protocol, so this is a literal
pass-through — we forward the request bytes + the X-Amz-Target header.

Replaces the in-memory ``provider_aws_services._ddb_api_aws`` for ALL boto3
traffic. Falls back to a 502 if DDB Local is unreachable (the simulator never
hangs; it surfaces the backend down).
"""
from __future__ import annotations

import json
import os
from typing import Any

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None  # type: ignore[assignment]


_DDB_URL = os.environ.get("CLOUDLEARN_DYNAMODB_URL", "http://cloudlearn-dynamodb:8000")


def available() -> bool:
    """Best-effort: do a ListTables and see if we get a 200."""
    try:
        req = urllib.request.Request(
            _DDB_URL,
            data=b"{}",
            method="POST",
            headers={
                "X-Amz-Target": "DynamoDB_20120810.ListTables",
                "Content-Type": "application/x-amz-json-1.0",
                "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# DynamoDB Local rejects TagResource/UntagResource/ListTagsOfResource ("Tagging is
# not currently supported"), real DynamoDB supports them: keep tags per table ARN here.
_TAGS: dict[str, dict[str, str]] = {}


def _tagging(op: str, body: bytes) -> bytes | None:
    if op not in ("TagResource", "UntagResource", "ListTagsOfResource"):
        return None
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = {}
    tags = _TAGS.setdefault(str(payload.get("ResourceArn", "")), {})
    if op == "TagResource":
        tags.update({str(t.get("Key", "")): str(t.get("Value", "")) for t in payload.get("Tags") or []})
        return b"{}"
    if op == "UntagResource":
        for k in payload.get("TagKeys") or []:
            tags.pop(str(k), None)
        return b"{}"
    return json.dumps({"Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}).encode()


# DynamoDB Local has no backups, point-in-time recovery or Contributor Insights
# ("UnknownOperationException"); real DynamoDB does. Keep that state here, per table.
_PITR: dict[str, dict[str, Any]] = {}
_BACKUPS: dict[str, dict[str, Any]] = {}
_INSIGHTS: dict[str, str] = {}
_REGION_ACCT = "arn:aws:dynamodb:us-east-1:000000000000"


def _ddb_error(kind: str, msg: str) -> bytes:
    return json.dumps({"__type": f"com.amazonaws.dynamodb.v20120810#{kind}", "message": msg}).encode()


def _describe_table(name: str) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            _DDB_URL, data=json.dumps({"TableName": name}).encode(), method="POST",
            headers={"X-Amz-Target": "DynamoDB_20120810.DescribeTable",
                     "Content-Type": "application/x-amz-json-1.0",
                     "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read()).get("Table")
    except Exception:
        return None


def _backup_summary(b: dict[str, Any]) -> dict[str, Any]:
    return {k: b[k] for k in ("TableName", "TableId", "TableArn", "BackupArn", "BackupName", "BackupCreationDateTime",
                              "BackupStatus", "BackupType", "BackupSizeBytes") if k in b}


def _backups(op: str, body: bytes) -> tuple[int, bytes] | None:
    import time
    import uuid
    if op not in ("DescribeContinuousBackups", "UpdateContinuousBackups", "CreateBackup", "ListBackups",
                  "DescribeBackup", "DeleteBackup", "DescribeContributorInsights", "UpdateContributorInsights"):
        return None
    try:
        p = json.loads(body or b"{}")
    except ValueError:
        p = {}
    if op in ("DescribeBackup", "DeleteBackup"):
        b = _BACKUPS.get(str(p.get("BackupArn", "")))
        if not b:
            return 400, _ddb_error("BackupNotFoundException", f"Backup not found: {p.get('BackupArn', '')}")
        if op == "DescribeBackup":
            return 200, json.dumps({"BackupDescription": {"BackupDetails": _backup_summary(b),
                                                          "SourceTableDetails": {"TableName": b["TableName"], "TableId": b["TableId"], "TableArn": b["TableArn"]}}}).encode()
        b["BackupStatus"] = "DELETED"
        _BACKUPS.pop(b["BackupArn"], None)
        return 200, json.dumps({"BackupDescription": {"BackupDetails": _backup_summary(b)}}).encode()
    if op == "ListBackups":
        tn = p.get("TableName")
        rows = [_backup_summary(b) for b in _BACKUPS.values() if not tn or b["TableName"] == tn]
        return 200, json.dumps({"BackupSummaries": rows}).encode()
    name = str(p.get("TableName", ""))
    t = _describe_table(name)
    if not t:
        return 400, _ddb_error("TableNotFoundException", f"Requested resource not found: Table: {name} not found")
    arn = f"{_REGION_ACCT}:table/{name}"
    if op == "CreateBackup":
        bname = str(p.get("BackupName", ""))
        if not bname:
            return 400, _ddb_error("ValidationException", "BackupName is required")
        now = time.time()
        barn = f"{arn}/backup/{time.strftime('%Y%m%d%H%M%S', time.gmtime(now))}-{uuid.uuid4().hex[:8]}"
        b = {"TableName": name, "TableId": t.get("TableId") or str(uuid.uuid5(uuid.NAMESPACE_URL, arn)), "TableArn": arn,
             "BackupArn": barn, "BackupName": bname, "BackupCreationDateTime": now, "BackupStatus": "AVAILABLE",
             "BackupType": "USER", "BackupSizeBytes": int(t.get("TableSizeBytes") or 0)}
        _BACKUPS[barn] = b
        return 200, json.dumps({"BackupDetails": _backup_summary(b)}).encode()
    if op in ("DescribeContinuousBackups", "UpdateContinuousBackups"):
        st = _PITR.setdefault(name, {"on": False, "since": None})
        if op == "UpdateContinuousBackups":
            on = bool((p.get("PointInTimeRecoverySpecification") or {}).get("PointInTimeRecoveryEnabled"))
            if on and not st["on"]:
                st["since"] = time.time()
            st["on"] = on
        d: dict[str, Any] = {"ContinuousBackupsStatus": "ENABLED",
                             "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "ENABLED" if st["on"] else "DISABLED"}}
        if st["on"]:
            d["PointInTimeRecoveryDescription"].update({"EarliestRestorableDateTime": st["since"],
                                                        "LatestRestorableDateTime": max(time.time() - 300, st["since"])})
        return 200, json.dumps({"ContinuousBackupsDescription": d}).encode()
    # Contributor Insights
    if op == "UpdateContributorInsights":
        _INSIGHTS[name] = "ENABLED" if p.get("ContributorInsightsAction") == "ENABLE" else "DISABLED"
    return 200, json.dumps({"TableName": name, "ContributorInsightsStatus": _INSIGHTS.get(name, "DISABLED"),
                            "ContributorInsightsRuleList": [f"DynamoDBContributorInsights-PKC-{name}"] if _INSIGHTS.get(name) == "ENABLED" else []}).encode()


async def proxy(request: Any) -> tuple[int, bytes, str]:
    """Forward the request body + X-Amz-Target to DDB Local. Returns (status,
    body, content_type)."""
    body = await request.body()
    target = request.headers.get("x-amz-target", "DynamoDB_20120810.ListTables")
    content_type = request.headers.get("content-type", "application/x-amz-json-1.0")
    tagged = _tagging(target.rsplit(".", 1)[-1], body)
    if tagged is not None:
        return 200, tagged, content_type
    shim = _backups(target.rsplit(".", 1)[-1], body)
    if shim is not None:
        return shim[0], shim[1], content_type
    try:
        req = urllib.request.Request(
            _DDB_URL,
            data=body,
            method="POST",
            headers={
                "X-Amz-Target": target,
                "Content-Type": content_type,
                # DDB Local requires SOME auth header even though it doesn't
                # verify; just pass through whatever the client sent.
                "Authorization": request.headers.get("authorization", "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"),
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers.get("Content-Type", content_type)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", content_type)
    except Exception as e:
        err = json.dumps({"__type": "InternalServerError", "message": f"dynamodb-local unreachable: {e!r}"}).encode()
        return 502, err, "application/x-amz-json-1.0"
