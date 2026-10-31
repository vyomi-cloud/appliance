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

v4 C0c (the offline appliance now serves Secrets Manager through this core — see
tests/conformance/test_c0c_legacy_parity_core.py): ClientRequestToken is the new
version's VersionId and makes CreateSecret / PutSecretValue idempotent (boto3 and
the CLI always send one); UpdateSecret without a value changes metadata only (no
new version); KmsKeyId and Tags are kept (CreateSecret / UpdateSecret /
TagResource / UntagResource) and returned by DescribeSecret / ListSecrets;
ListSecrets carries SecretVersionsToStages; creating a name that is scheduled for
deletion fails with InvalidRequestException, as in real AWS.

Scope: CreateSecret, GetSecretValue, PutSecretValue, UpdateSecret, DescribeSecret,
ListSecrets, ListSecretVersionIds, DeleteSecret, RestoreSecret, RotateSecret,
TagResource/UntagResource, Get/Put/DeleteResourcePolicy. KmsKeyId is stored and
round-tripped as-written; Vyomi does not use it to actually encrypt the value
(same honesty posture as core/kms_core.py's key policy).

v4 depth pass: automatic rotation now really fires on its own schedule — a
secret with RotationRules (AutomaticallyAfterDays, or a `rate(N day(s)/hour(s))`
ScheduleExpression) computes NextRotationDate, and any read (GetSecretValue /
DescribeSecret / ListSecrets) lazily rotates it the same way RotateSecret's
RotateImmediately does (carry the current value into a fresh AWSCURRENT
version) once that time has passed — the same lazy-on-access pattern TTL uses
elsewhere. There is still no Lambda runtime, so the "new" value is the old one,
not a freshly generated credential. PutResourcePolicy now validates the policy
is well-formed JSON with at least one Allow/Deny statement and rejects (unless
BlockPublicPolicy=false) a policy that grants public access — the same
public-policy guard real Secrets Manager applies at write time. Resource policy
CONTENT is still never evaluated for an actual GetSecretValue access decision
(no multi-principal/cross-account identity model). Replication is not modeled.

v4 depth wave 5: a secret that carries a customer KmsKeyId is now genuinely
encrypted at rest under that key — CreateSecret/PutSecretValue/UpdateSecret run
SecretString/SecretBinary through core/kms_core.py's real Encrypt before
persisting the version, and GetSecretValue/the lazy rotation path run it back
through Decrypt, via an optional `kms_store` passed into `dispatch()` (the
router passes its KMS core's KeyStore; omit it — as every pre-wave-5 caller
does — and the secret stores the plaintext as before, so this is additive).
Disabling, scheduling deletion, or otherwise invalidating that key blocks
GetSecretValue/PutSecretValue the same way it would for a real customer-managed
key (KMS raises, Secrets Manager surfaces it as InvalidRequestException); giving
UpdateSecret a different KmsKeyId re-encrypts every existing version under the
new key (KMS embeds the key id in the ciphertext, so decrypting the old
versions doesn't need the old key id at hand). Secrets left on the implicit
default (no KmsKeyId) are unaffected — Vyomi has no AWS-owned/managed key
material to model for that path, so they stay plaintext internally, same as
before this pass.
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from core import kms_core
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


def _b64e_str(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _b64d_str(s: str) -> str:
    return base64.b64decode(s).decode("utf-8")


def _kms_call(kms_store, action: str, body: dict) -> dict:
    resp = kms_core.dispatch(kms_store, f"TrentService.{action}", body)
    if resp.status != 200:
        raise SecretsError("InvalidRequestException",
                           f"Secrets Manager can't {action.lower()} the protected secret text using the "
                           f"provided KMS key: {resp.body.get('message') or resp.body.get('__type', 'KMS error')}", 400)
    return resp.body


def _encrypt_value(kms_store, key_id: str | None, value: str | None) -> str | None:
    """Encrypt one field (SecretString or the base64 SecretBinary string, treated
    as opaque bytes either way) under `key_id` via the real KMS core — a no-op
    (plaintext stored as-is) when there's no kms_store or no customer key, which
    is how every pre-wave-5 caller of dispatch() still behaves."""
    if value is None or kms_store is None or not key_id:
        return value
    return _kms_call(kms_store, "Encrypt", {"KeyId": key_id, "Plaintext": _b64e_str(value)})["CiphertextBlob"]


def _decrypt_value(kms_store, value: str | None) -> str | None:
    if value is None or kms_store is None:
        return value
    return _b64d_str(_kms_call(kms_store, "Decrypt", {"CiphertextBlob": value})["Plaintext"])


def _version_plaintext(kms_store, version: dict) -> tuple[str | None, str | None]:
    s_str, s_bin = version.get("SecretString"), version.get("SecretBinary")
    if version.get("enc"):
        s_str = _decrypt_value(kms_store, s_str)
        s_bin = _decrypt_value(kms_store, s_bin)
    return s_str, s_bin


def _new_version(value_str: str | None, value_bin: str | None, stages: list[str],
                 token: str | None = None, kms_store=None, key_id: str | None = None) -> tuple[str, dict]:
    vid = str(token) if token else uuid.uuid4().hex
    enc = bool(kms_store is not None and key_id)
    if enc:
        value_str = _encrypt_value(kms_store, key_id, value_str)
        value_bin = _encrypt_value(kms_store, key_id, value_bin)
    return vid, {"SecretString": value_str, "SecretBinary": value_bin,
                 "CreatedDate": time.time(), "stages": list(stages), "enc": enc}


def _stage_to_version(secret: dict, stage: str) -> str | None:
    for vid, v in secret["versions"].items():
        if stage in v.get("stages", []):
            return vid
    return None


def _rewrap_versions(kms_store, secret: dict, new_key_id: str) -> None:
    """UpdateSecret with a new KmsKeyId re-encrypts every existing version under
    it — the same re-encryption real Secrets Manager performs. KMS embeds the
    key id in the ciphertext, so decrypting the old versions needs no record of
    which key protected them before."""
    for v in secret["versions"].values():
        s_str, s_bin = _version_plaintext(kms_store, v)
        v["SecretString"] = _encrypt_value(kms_store, new_key_id, s_str)
        v["SecretBinary"] = _encrypt_value(kms_store, new_key_id, s_bin)
        v["enc"] = bool(kms_store is not None)


def _idempotent_version(secret: dict, body: dict, kms_store=None) -> str | None:
    """Real AWS: a ClientRequestToken that already names a version is a retry —
    same value → return that version, different value → ResourceExistsException."""
    token = body.get("ClientRequestToken")
    if not token or token not in secret.get("versions", {}):
        return None
    v = secret["versions"][token]
    s_str, s_bin = _values_from_body(body)
    have_str, have_bin = _version_plaintext(kms_store, v)
    if have_str != s_str or have_bin != s_bin:
        raise SecretsError("ResourceExistsException",
                           "A version with this ClientRequestToken already exists with a different value.", 400)
    return token


def _tags_in(body: dict) -> dict:
    return {str(t["Key"]): str(t.get("Value", "")) for t in body.get("Tags") or [] if t.get("Key")}


def _tags_out(secret: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in (secret.get("tags") or {}).items()]


def _values_from_body(body: dict) -> tuple[str | None, str | None]:
    s = body.get("SecretString")
    b = body.get("SecretBinary")
    return (str(s) if s is not None else None, str(b) if b is not None else None)


# ── operations ──────────────────────────────────────────────────────────────
def _create_secret(store: KvStore, body: dict, kms_store=None) -> dict:
    name = str(body.get("Name") or "").strip()
    if not name:
        raise SecretsError("ValidationException", "Name is required.", 400)
    if store.secret_exists(name):
        existing = store.get_secret(name)
        if existing.get("deleted_date"):
            raise SecretsError("InvalidRequestException",
                               f"You can't create this secret because a secret with this name ({name}) "
                               "is already scheduled for deletion.", 400)
        vid = _idempotent_version(existing, body, kms_store)
        if vid:
            return {"ARN": existing["arn"], "Name": name, "VersionId": vid}
        raise SecretsError("ResourceExistsException",
                           f"The operation failed because the secret {name} already exists.", 400)
    s_str, s_bin = _values_from_body(body)
    has_value = s_str is not None or s_bin is not None
    key_id = str(body["KmsKeyId"]) if body.get("KmsKeyId") else None
    vid, version = _new_version(s_str, s_bin, [CURRENT], body.get("ClientRequestToken"), kms_store, key_id)
    now = time.time()
    secret = {"name": name, "arn": _secret_arn(store, name), "description": str(body.get("Description", "")),
              "created": now, "last_changed": now, "last_accessed": None, "versions": {vid: version} if has_value else {},
              "deleted_date": None}
    if key_id:
        secret["kms_key_id"] = key_id
    if body.get("Tags"):
        secret["tags"] = _tags_in(body)
    store.put_secret(name, secret)
    store.mirror_put(name, secret)
    store.persist()
    out = {"ARN": secret["arn"], "Name": name}
    if has_value:
        out["VersionId"] = vid
    return out


def _put_value(store: KvStore, body: dict, update: bool = False, kms_store=None) -> dict:
    secret = _require_secret(store, body.get("SecretId") or body.get("Name") or "")
    if secret.get("deleted_date"):
        raise SecretsError("InvalidRequestException",
                           "You can't perform this operation on the secret because it was marked for deletion.", 400)
    s_str, s_bin = _values_from_body(body)
    if update:
        # UpdateSecret: metadata always; a new version only when a value is given.
        if body.get("Description") is not None:
            secret["description"] = str(body.get("Description"))
        new_key = str(body["KmsKeyId"]) if body.get("KmsKeyId") else None
        if new_key and new_key != secret.get("kms_key_id"):
            _rewrap_versions(kms_store, secret, new_key)
            secret["kms_key_id"] = new_key
        if s_str is None and s_bin is None:
            secret["last_changed"] = time.time()
            store.mirror_put(secret["name"], secret)
            store.persist()
            return {"ARN": secret["arn"], "Name": secret["name"]}
    elif s_str is None and s_bin is None:
        raise SecretsError("InvalidRequestException",
                           "You must provide either SecretString or SecretBinary.", 400)
    same = _idempotent_version(secret, body, kms_store)
    if same:
        return {"ARN": secret["arn"], "Name": secret["name"], "VersionId": same,
                "VersionStages": secret["versions"][same].get("stages", [])}
    requested = body.get("VersionStages") or [CURRENT]
    # Encrypt (may raise, e.g. a disabled CMK) BEFORE touching any existing stage
    # assignment, so a failed write never leaves the secret without an AWSCURRENT.
    vid, version = _new_version(s_str, s_bin, requested, body.get("ClientRequestToken"),
                                kms_store, secret.get("kms_key_id"))
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
    secret["versions"][vid] = version
    stages = version["stages"]
    secret["last_changed"] = time.time()
    store.mirror_put(secret["name"], secret)
    store.persist()
    return {"ARN": secret["arn"], "Name": secret["name"], "VersionId": vid, "VersionStages": stages}


_SCHEDULE_RE = re.compile(r"rate\(\s*(\d+)\s*(hour|hours|day|days)\s*\)", re.IGNORECASE)


def _rotation_interval_seconds(rules: dict) -> float | None:
    """How often this secret's schedule asks to rotate, or None if the schedule
    can't be resolved to an interval (e.g. an unparseable cron-style expression) —
    in which case auto-rotation stays honestly off; 'Rotate secret immediately'
    still works."""
    days = (rules or {}).get("AutomaticallyAfterDays")
    if days is not None:
        try:
            return float(days) * 86400
        except (TypeError, ValueError):
            return None
    expr = (rules or {}).get("ScheduleExpression")
    m = _SCHEDULE_RE.match((expr or "").strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * (3600 if unit.startswith("hour") else 86400)


def _carry_forward_rotation(store: KvStore, secret: dict, kms_store=None) -> str:
    """The shared 'rotate without a Lambda' step: carry the current value into a
    fresh AWSCURRENT version (old → AWSPREVIOUS), used by both RotateImmediately
    and the lazy auto-rotation check."""
    vid = _stage_to_version(secret, CURRENT)
    cur = secret["versions"].get(vid, {}) if vid else {}
    s_str, s_bin = _version_plaintext(kms_store, cur)
    res = _put_value(store, {"SecretId": secret["name"],
                             "SecretString": s_str, "SecretBinary": s_bin}, kms_store=kms_store)
    secret["last_rotated_date"] = time.time()
    return res["VersionId"]


def _reschedule(secret: dict, anchor: float) -> None:
    interval = _rotation_interval_seconds(secret.get("rotation_rules") or {})
    secret["next_rotation_date"] = (anchor + interval) if interval is not None else None


def _auto_rotate_if_due(store: KvStore, secret: dict, kms_store=None) -> None:
    """Lazy, on-access rotation — the same pattern DynamoDB TTL uses: nothing runs
    in the background, but any read notices a past-due schedule and fires it."""
    due = secret.get("next_rotation_date")
    if not secret.get("rotation_enabled") or secret.get("deleted_date") or due is None or time.time() < due:
        return
    _carry_forward_rotation(store, secret, kms_store)
    _reschedule(secret, time.time())


def _rotate_secret(store: KvStore, body: dict, kms_store=None) -> dict:
    """Rotate a secret: enable rotation metadata and (RotateImmediately, default
    true) create a fresh AWSCURRENT version. Without a rotation Lambda we carry the
    current value into the new version, mirroring the version-stage transitions a
    real rotation performs (new VersionId → AWSCURRENT, old → AWSPREVIOUS). Also
    schedules the next automatic rotation from RotationRules, so the schedule
    really fires on its own (see _auto_rotate_if_due) even though no Lambda runs."""
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
        vid = _carry_forward_rotation(store, secret, kms_store)
    else:
        store.persist()
    _reschedule(secret, secret.get("last_rotated_date") or time.time())
    return {"ARN": secret["arn"], "Name": secret["name"], "VersionId": vid}


def _get_secret_value(store: KvStore, body: dict, kms_store=None) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    if secret.get("deleted_date"):
        raise SecretsError("InvalidRequestException",
                           "You can't perform this operation on the secret because it was marked for deletion.", 400)
    _auto_rotate_if_due(store, secret, kms_store)
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
    s_str, s_bin = _version_plaintext(kms_store, v)
    if s_str is not None:
        out["SecretString"] = s_str
    if s_bin is not None:
        out["SecretBinary"] = s_bin
    return out


def _common_fields(secret: dict) -> dict:
    out = {"Description": secret.get("description", ""), "CreatedDate": secret.get("created"),
           "LastChangedDate": secret.get("last_changed"), "RotationEnabled": bool(secret.get("rotation_enabled", False))}
    if secret.get("last_accessed"):
        out["LastAccessedDate"] = secret["last_accessed"]
    if secret.get("rotation_enabled"):
        if secret.get("rotation_lambda_arn"):
            out["RotationLambdaARN"] = secret["rotation_lambda_arn"]
        if secret.get("rotation_rules"):
            out["RotationRules"] = secret["rotation_rules"]
        if secret.get("last_rotated_date"):
            out["LastRotatedDate"] = secret["last_rotated_date"]
        if secret.get("next_rotation_date"):
            out["NextRotationDate"] = secret["next_rotation_date"]
    if secret.get("deleted_date"):
        out["DeletedDate"] = secret["deleted_date"]
    if secret.get("kms_key_id"):
        out["KmsKeyId"] = secret["kms_key_id"]
    if secret.get("tags"):
        out["Tags"] = _tags_out(secret)
    return out


def _tag_resource(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    secret.setdefault("tags", {}).update(_tags_in(body))
    store.mirror_put(secret["name"], secret)
    store.persist()
    return {}


def _untag_resource(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    tags = secret.setdefault("tags", {})
    for k in body.get("TagKeys") or []:
        tags.pop(k, None)
    store.mirror_put(secret["name"], secret)
    store.persist()
    return {}


def _describe_secret(store: KvStore, body: dict, kms_store=None) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    _auto_rotate_if_due(store, secret, kms_store)
    vids_to_stages = {vid: v.get("stages", []) for vid, v in secret["versions"].items()}
    return {"ARN": secret["arn"], "Name": secret["name"], "VersionIdsToStages": vids_to_stages,
            **_common_fields(secret)}


def _list_secrets(store: KvStore, body: dict, kms_store=None) -> dict:
    include_deleted = bool(body.get("IncludePlannedDeletion"))
    out = []
    for name in store.names():
        s = store.get_secret(name)
        if s.get("deleted_date") and not include_deleted:
            continue
        _auto_rotate_if_due(store, s, kms_store)
        out.append({"ARN": s["arn"], "Name": name, **_common_fields(s),
                    "SecretVersionsToStages": {vid: v.get("stages", []) for vid, v in s["versions"].items()}})
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


def _get_resource_policy(store: KvStore, body: dict) -> dict:
    secret = _require_secret(store, body.get("SecretId") or "")
    out = {"ARN": secret["arn"], "Name": secret["name"]}
    if secret.get("resource_policy"):
        out["ResourcePolicy"] = secret["resource_policy"]
    return out


def _policy_is_public(doc: dict) -> bool:
    """Same 'is this statement wide open' check core/s3_object_core.py's
    _policy_is_public uses for BlockPublicAccess — Secrets Manager's own
    BlockPublicPolicy guard works the same way."""
    for st in doc.get("Statement") or []:
        if st.get("Effect") != "Allow":
            continue
        principal = st.get("Principal")
        if principal == "*":
            return True
        if isinstance(principal, dict):
            aws = principal.get("AWS")
            if aws == "*" or (isinstance(aws, list) and "*" in aws):
                return True
    return False


def _parse_resource_policy(policy) -> dict:
    try:
        doc = json.loads(policy)
    except (TypeError, ValueError):
        raise SecretsError("MalformedPolicyDocumentException", "The policy text is not valid JSON.", 400)
    statements = doc.get("Statement") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or not isinstance(statements, list) or not statements:
        raise SecretsError("MalformedPolicyDocumentException",
                           "The policy must be a JSON object with a non-empty Statement list.", 400)
    for st in statements:
        if not isinstance(st, dict) or st.get("Effect") not in ("Allow", "Deny") or not st.get("Principal"):
            raise SecretsError("MalformedPolicyDocumentException",
                               "Each statement needs an Effect of Allow or Deny and a Principal.", 400)
    return doc


def _put_resource_policy(store: KvStore, body: dict) -> dict:
    """Real Secrets Manager validates the policy document's shape and, by default
    (BlockPublicPolicy=true), rejects one that grants public access — enforced
    here the same way; evaluating the policy against an actual caller at
    GetSecretValue time is not modeled (Vyomi has one implicit caller identity)."""
    secret = _require_secret(store, body.get("SecretId") or "")
    policy = body.get("ResourcePolicy")
    if not policy:
        raise SecretsError("InvalidParameterException", "ResourcePolicy is required.", 400)
    doc = _parse_resource_policy(policy)
    if _policy_is_public(doc) and body.get("BlockPublicPolicy", True):
        raise SecretsError("PublicPolicyException",
                           "The resource policy grants public access to the secret. Pass "
                           "BlockPublicPolicy=false to attach it anyway.", 400)
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
# is the raw X-Amz-Target header, e.g. "secretsmanager.GetSecretValue". `kms_store`
# is the KMS core's KeyStore — pass the router's own (e.g. AwsWireRouter.kms) so a
# secret with a customer KmsKeyId is genuinely encrypted/decrypted through it;
# omit it (every caller before wave 5 does) and secrets store their value as
# plaintext, same as always.
def dispatch(store: KvStore, target: str, payload: dict | None = None, kms_store=None) -> SecretsResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("MissingAction", "The request must include X-Amz-Target.", 400)
    try:
        if action == "CreateSecret":
            return _ok(_create_secret(store, body, kms_store))
        if action == "GetSecretValue":
            return _ok(_get_secret_value(store, body, kms_store))
        if action == "PutSecretValue":
            return _ok(_put_value(store, body, update=False, kms_store=kms_store))
        if action == "UpdateSecret":
            return _ok(_put_value(store, body, update=True, kms_store=kms_store))
        if action == "DescribeSecret":
            return _ok(_describe_secret(store, body, kms_store))
        if action == "ListSecrets":
            return _ok(_list_secrets(store, body, kms_store))
        if action == "ListSecretVersionIds":
            return _ok(_list_secret_version_ids(store, body))
        if action == "DeleteSecret":
            return _ok(_delete_secret(store, body))
        if action == "RestoreSecret":
            return _ok(_restore_secret(store, body))
        if action == "TagResource":
            return _ok(_tag_resource(store, body))
        if action == "UntagResource":
            return _ok(_untag_resource(store, body))
        if action == "RotateSecret":
            return _ok(_rotate_secret(store, body, kms_store))
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
