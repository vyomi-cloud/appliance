# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Secrets Manager core — substrate-independent, extracted from the appliance
Secrets handler (core/vault_routes.py `_aws_secrets_dispatch`) so the SAME logic
runs in Pro/Max (FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 /
socket / hvac imports → loads under Pyodide. Persists through the KvStore seam
(core/kv_store.py).

Each operation takes the parsed JSON payload and returns a `SecretsResponse`
(status, body-dict, headers) — the native AWS Secrets Manager wire shapes (ARN,
VersionId, SecretString/SecretBinary, VersionStages, `__type` JSON errors,
x-amzn-requestid). Secrets Manager speaks JSON1.1 with the `secretsmanager.`
X-Amz-Target prefix. A thin FastAPI adapter (Pro/Max) or the relay/SW bridge
(Nano) maps Request<->SecretsResponse.

Canonical wire the appliance converges onto (the appliance was thin — it returned
integer Vault versions as VersionId and no stages): proper UUID VersionIds with
AWSCURRENT/AWSPREVIOUS VersionStages, GetSecretValue by VersionId or VersionStage,
DescribeSecret/ListSecrets, and real scheduled-deletion semantics (a deleted
secret blocks GetSecretValue until restored or the window elapses). All errors use
the native {"__type","message"} shape.

Scope: CreateSecret, GetSecretValue, PutSecretValue, UpdateSecret, DescribeSecret,
ListSecrets, ListSecretVersionIds, DeleteSecret, RestoreSecret, RotateSecret,
TagResource/UntagResource, Get/Put/DeleteResourcePolicy. KmsKeyId and tags are
stored and round-tripped as-written; Vyomi does not use them to actually
encrypt the value or evaluate the resource policy (same honesty posture as
core/kms_core.py's key policy). Replication is not modeled.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from core.kv_store import KvStore

SM_REGION = "us-east-1"
CURRENT = "AWSCURRENT"
PREVIOUS = "AWSPREVIOUS"


@dataclass
class SecretsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class SecretsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _req_id() -> str:
    return str(uuid.uuid4())


def _secret_arn(store: KvStore, name: str) -> str:
    return f"arn:aws:secretsmanager:{SM_REGION}:{store.account_id}:secret:{name}"


# ── name resolution (SecretId may be a bare name or a full ARN) ────────────
def _resolve_name(store: KvStore, ref: str) -> str | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    if ":secret:" in ref:
        ref = ref.split(":secret:", 1)[1]
    return ref if store.secret_exists(ref) else None


def _require_secret(store: KvStore, ref: str) -> dict:
    name = _resolve_name(store, ref)
    if not name:
        raise SecretsError("ResourceNotFoundException",
                           f"Secrets Manager can't find the specified secret: {ref}", 400)
    return store.get_secret(name)


def _new_version(value_str: str | None, value_bin: str | None, stages: list[str]) -> tuple[str, dict]:
    vid = uuid.uuid4().hex
    return vid, {"SecretString": value_str, "SecretBinary": value_bin,
                 "CreatedDate": time.time(), "stages": list(stages)}


def _stage_to_version(secret: dict, stage: str) -> str | None:
    for vid, v in secret["versions"].items():
        if stage in v.get("stages", []):
            return vid
    return None


def _values_from_body(body: dict) -> tuple[str | None, str | None]:
    s = body.get("SecretString")
    b = body.get("SecretBinary")
    return (str(s) if s is not None else None, str(b) if b is not None else None)


# ── operations ──────────────────────────────────────────────────────────────
def _create_secret(store: KvStore, body: dict) -> dict:
    name = str(body.get("Name") or "").strip()
    if not name:
        raise SecretsError("ValidationException", "Name is required.", 400)
    if store.secret_exists(name) and not store.get_secret(name).get("deleted_date"):
        raise SecretsError("ResourceExistsException",
                           f"The operation failed because the secret {name} already exists.", 400)
    s_str, s_bin = _values_from_body(body)
    vid, version = _new_version(s_str, s_bin, [CURRENT])
    now = time.time()
    tags = {str(t.get("Key")): str(t.get("Value", "")) for t in (body.get("Tags") or []) if t.get("Key")}
    secret = {"name": name, "arn": _secret_arn(store, name), "description": str(body.get("Description", "")),
              "created": now, "last_changed": now, "last_accessed": None, "versions": {vid: version},
              "deleted_date": None, "tags": tags, "kms_key_id": str(body.get("KmsKeyId") or "alias/aws/secretsmanager")}
    store.put_secret(name, secret)
    store.mirror_put(name, secret)
    store.persist()
    return {"ARN": secret["arn"], "Name": name, "VersionId": vid}


def _put_value(store: KvStore, body: dict, update: bool = False) -> dict:
    secret = _require_secret(store, body.get("SecretId") or body.get("Name") or "")
    if secret.get("deleted_date"):
        raise SecretsError("InvalidRequestException",
                           "You can't perform this operation on the secret because it was marked for deletion.", 400)
    s_str, s_bin = _values_from_body(body)
    # UpdateSecret may touch only metadata (Description/KmsKeyId) without a new value —
    # that must NOT create a version, matching real AWS.
    if s_str is None and s_bin is None:
        vid = _stage_to_version(secret, CURRENT)
        stages = secret["versions"][vid]["stages"] if vid else [CURRENT]
    else:
        requested = body.get("VersionStages") or [CURRENT]
        # The new version takes AWSCURRENT; demote whoever currently holds it to AWSPREVIOUS.
        if CURRENT in requested:
            prev = _stage_to_version(secret, CURRENT)
            if prev is not None:
                secret["versions"][prev]["stages"] = [
                    st for st in secret["versions"][prev]["stages"] if st != CURRENT]
                # only one AWSPREVIOUS at a time
                for v in secret["versions"].values():
                    v["stages"] = [st for st in v.get("stages", []) if st != PREVIOUS]
                secret["versions"][prev]["stages"].append(PREVIOUS)
        vid, version = _new_version(s_str, s_bin, requested)
        secret["versions"][vid] = version
        stages = version["stages"]
    secret["last_changed"] = time.time()
    if update:
        if body.get("Description") is not None:
            secret["description"] = str(body.get("Description"))
        if body.get("KmsKeyId") is not None:
            secret["kms_key_id"] = str(body.get("KmsKeyId"))
    store.mirror_put(secret["name"], secret)
    store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"], "VersionId": vid, "VersionStages": stages}


def _rotate_secret(store: KvStore, body: dict) -> dict:
    """Rotate a secret: enable rotation metadata and (RotateImmediately, default
    true) create a fresh AWSCURRENT version. Without a rotation Lambda we carry the
    current value into the new version, mirroring the version-stage transitions a
    real rotation performs (new VersionId → AWSCURRENT, old → AWSPREVIOUS)."""
    secret = _require_secret(store, body.get("SecretId") or "")
    if secret.get("deleted_date"):
        raise SecretsError("InvalidRequestException",
                           "You can't perform this operation on the secret because it was marked for deletion.", 400)
    if body.get("RotationLambdaARN"):
        secret["rotation_lambda_arn"] = str(body.get("RotationLambdaARN"))
    if body.get("RotationRules"):
        secret["rotation_rules"] = dict(body.get("RotationRules") or {})
    secret["rotation_enabled"] = True
    vid = _stage_to_version(secret, CURRENT)
    if body.get("RotateImmediately", True):
        cur = secret["versions"].get(vid, {}) if vid else {}
        new_body = {"SecretId": secret["name"],
                    "SecretString": cur.get("SecretString"),
                    "SecretBinary": cur.get("SecretBinary")}
        res = _put_value(store, new_body)   # handles CURRENT→PREVIOUS demotion + new vid
        vid = res["VersionId"]
        secret["last_rotated_date"] = time.time()
    else:
        store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"], "VersionId": vid}


def _get_secret_value(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    if secret.get("deleted_date"):
        raise SecretsError("InvalidRequestException",
                           "You can't perform this operation on the secret because it was marked for deletion.", 400)
    vid = body.get("VersionId")
    if not vid:
        stage = body.get("VersionStage") or CURRENT
        vid = _stage_to_version(secret, stage)
    if not vid or vid not in secret["versions"]:
        raise SecretsError("ResourceNotFoundException",
                           "Secrets Manager can't find the specified secret value.", 400)
    secret["last_accessed"] = time.time()
    store.persist()
    v = secret["versions"][vid]
    out = {"ARN": secret["arn"], "Name": secret["name"], "VersionId": vid,
           "VersionStages": v.get("stages", []), "CreatedDate": v.get("CreatedDate")}
    if v.get("SecretString") is not None:
        out["SecretString"] = v["SecretString"]
    if v.get("SecretBinary") is not None:
        out["SecretBinary"] = v["SecretBinary"]
    return out


def _tags_list(secret: dict) -> list[dict]:
    return [{"Key": k, "Value": v} for k, v in secret.get("tags", {}).items()]


def _common_fields(secret: dict) -> dict:
    out = {"Description": secret.get("description", ""), "KmsKeyId": secret.get("kms_key_id"),
           "CreatedDate": secret.get("created"), "LastChangedDate": secret.get("last_changed"),
           "Tags": _tags_list(secret), "RotationEnabled": bool(secret.get("rotation_enabled", False))}
    if secret.get("last_accessed"):
        out["LastAccessedDate"] = secret["last_accessed"]
    if secret.get("rotation_enabled"):
        if secret.get("rotation_lambda_arn"):
            out["RotationLambdaARN"] = secret["rotation_lambda_arn"]
        if secret.get("rotation_rules"):
            out["RotationRules"] = secret["rotation_rules"]
        if secret.get("last_rotated_date"):
            out["LastRotatedDate"] = secret["last_rotated_date"]
    if secret.get("deleted_date"):
        out["DeletedDate"] = secret["deleted_date"]
    return out


def _describe_secret(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    vids_to_stages = {vid: v.get("stages", []) for vid, v in secret["versions"].items()}
    return {"ARN": secret["arn"], "Name": secret["name"], "VersionIdsToStages": vids_to_stages,
            **_common_fields(secret)}


def _list_secrets(store: KvStore, body: dict) -> dict:
    include_deleted = bool(body.get("IncludePlannedDeletion"))
    out = []
    for name in store.names():
        s = store.get_secret(name)
        if s.get("deleted_date") and not include_deleted:
            continue
        out.append({"ARN": s["arn"], "Name": name, **_common_fields(s)})
    return {"SecretList": out}


def _list_secret_version_ids(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    versions = [{"VersionId": vid, "VersionStages": v.get("stages", []),
                 "CreatedDate": v.get("CreatedDate")}
                for vid, v in secret["versions"].items()]
    return {"ARN": secret["arn"], "Name": secret["name"], "Versions": versions}


def _delete_secret(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    if body.get("ForceDeleteWithoutRecovery"):
        store.drop_secret(secret["name"])
        store.mirror_delete(secret["name"])
        store.persist()
        return {"ARN": secret["arn"], "Name": secret["name"], "DeletionDate": time.time()}
    days = int(body.get("RecoveryWindowInDays") or 30)
    if days < 7 or days > 30:
        raise SecretsError("InvalidParameterException", "RecoveryWindowInDays must be 7..30.", 400)
    secret["deleted_date"] = time.time() + days * 86400
    store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"], "DeletionDate": secret["deleted_date"]}


def _restore_secret(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    secret["deleted_date"] = None
    store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"]}


def _tag_resource(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    for t in body.get("Tags") or []:
        if t.get("Key"):
            secret.setdefault("tags", {})[str(t["Key"])] = str(t.get("Value", ""))
    store.persist()
    return {}


def _untag_resource(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    for k in body.get("TagKeys") or []:
        secret.get("tags", {}).pop(str(k), None)
    store.persist()
    return {}


def _get_resource_policy(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    out = {"ARN": secret["arn"], "Name": secret["name"]}
    if secret.get("resource_policy"):
        out["ResourcePolicy"] = secret["resource_policy"]
    return out


def _put_resource_policy(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    policy = body.get("ResourcePolicy")
    if not policy:
        raise SecretsError("InvalidParameterException", "ResourcePolicy is required.", 400)
    secret["resource_policy"] = str(policy)
    store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"]}


def _delete_resource_policy(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    secret["resource_policy"] = None
    store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"]}


# ── native-wire dispatcher (X-Amz-Target action → operation) ───────────────
# The single routing point for the native AWS Secrets Manager JSON protocol
# (secretsmanager.*) — what an unmodified aws-cli / boto3 client speaks. `target`
# is the raw X-Amz-Target header, e.g. "secretsmanager.GetSecretValue".
def dispatch(store: KvStore, target: str, payload: dict | None = None) -> SecretsResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("MissingAction", "The request must include X-Amz-Target.", 400)
    try:
        if action == "CreateSecret":
            return _ok(_create_secret(store, body))
        if action == "GetSecretValue":
            return _ok(_get_secret_value(store, body))
        if action == "PutSecretValue":
            return _ok(_put_value(store, body, update=False))
        if action == "UpdateSecret":
            return _ok(_put_value(store, body, update=True))
        if action == "DescribeSecret":
            return _ok(_describe_secret(store, body))
        if action == "ListSecrets":
            return _ok(_list_secrets(store, body))
        if action == "ListSecretVersionIds":
            return _ok(_list_secret_version_ids(store, body))
        if action == "DeleteSecret":
            return _ok(_delete_secret(store, body))
        if action == "RestoreSecret":
            return _ok(_restore_secret(store, body))
        if action == "RotateSecret":
            return _ok(_rotate_secret(store, body))
        if action == "TagResource":
            return _ok(_tag_resource(store, body))
        if action == "UntagResource":
            return _ok(_untag_resource(store, body))
        if action == "GetResourcePolicy":
            return _ok(_get_resource_policy(store, body))
        if action == "PutResourcePolicy":
            return _ok(_put_resource_policy(store, body))
        if action == "DeleteResourcePolicy":
            return _ok(_delete_resource_policy(store, body))
        return _error("UnknownOperationException", f"The action {action} is not implemented.", 400)
    except SecretsError as e:
        return _error(e.code, e.message, e.status)


def _ok(body: dict) -> SecretsResponse:
    return SecretsResponse(status=200, body=body, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400) -> SecretsResponse:
    return SecretsResponse(status=status, body={"__type": code, "message": message},
                           headers={"x-amzn-requestid": _req_id()})
