"""console-next Secrets Manager facade — drives the substrate-agnostic Secrets
core (core/secrets_core.py) over a single KvStore so the kv-secret-viewer widget
can list secrets, describe versions, read the (masked) value, and create/put a
secret value (§13 kv/secret).

Why a console-scoped facade instead of the native SigV4 wire: Secrets Manager only
speaks the native JSON1.1 protocol (`secretsmanager.` X-Amz-Target) — there is no
plain-JSON console REST facade. Rather than teach the widget SigV4, this module
maps clean JSON functions onto the SAME core + store the Nano relay drives, so the
behaviour is byte-identical across substrates (§15). Purely additive — it touches
no existing routes or ctx state.

Mutating ops go through the core's `dispatch` (real versioning + stage transitions);
list/describe/get read through the core helpers for clean JSON. The route layer maps
these to /api/console/secrets/*. Values are returned as-is; MASKING is a UI concern
(the widget hides them by default), so the honest secret is always available for a
deliberate reveal.
"""

from __future__ import annotations

from core import secrets_core
from core.kv_store import InMemoryKvStore

# ── one shared store for the console secrets vertical (module singleton) ──
_STORE = InMemoryKvStore()


def store() -> InMemoryKvStore:
    return _STORE


class SecretsError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _call(action: str, payload: dict) -> dict:
    resp = secrets_core.dispatch(_STORE, f"secretsmanager.{action}", payload)
    body = resp.body if isinstance(resp.body, dict) else {}
    if resp.status >= 400:
        raise SecretsError(str(body.get("message") or body.get("__type") or action + " failed"),
                           resp.status)
    return body


# ── list / describe / get ────────────────────────────────────────────────
def list_secrets() -> dict:
    """List secrets (non-deleted) with their current-version stage summary."""
    body = _call("ListSecrets", {})
    out = []
    for s in body.get("SecretList", []):
        out.append({
            "name": s.get("Name", ""),
            "arn": s.get("ARN", ""),
            "description": s.get("Description", ""),
            "created": s.get("CreatedDate"),
            "last_changed": s.get("LastChangedDate"),
            "deleted_date": s.get("DeletedDate"),
        })
    return {"secrets": out, "count": len(out)}


def describe_secret(name: str) -> dict:
    """Metadata + version→stage map for a secret. NO secret value here."""
    body = _call("DescribeSecret", {"SecretId": name})
    versions = [
        {"version_id": vid, "stages": stages}
        for vid, stages in (body.get("VersionIdsToStages") or {}).items()
    ]
    return {
        "name": body.get("Name", ""),
        "arn": body.get("ARN", ""),
        "description": body.get("Description", ""),
        "created": body.get("CreatedDate"),
        "last_changed": body.get("LastChangedDate"),
        "deleted_date": body.get("DeletedDate"),
        "versions": versions,
    }


def get_secret_value(name: str, version_id: str | None = None,
                     version_stage: str | None = None) -> dict:
    """The (unmasked) secret value for a version/stage. The WIDGET masks it by
    default and only calls this on a deliberate reveal."""
    payload: dict = {"SecretId": name}
    if version_id:
        payload["VersionId"] = version_id
    if version_stage:
        payload["VersionStage"] = version_stage
    body = _call("GetSecretValue", payload)
    return {
        "name": body.get("Name", ""),
        "arn": body.get("ARN", ""),
        "version_id": body.get("VersionId", ""),
        "stages": body.get("VersionStages", []),
        "created": body.get("CreatedDate"),
        "secret_string": body.get("SecretString"),
        "secret_binary": body.get("SecretBinary"),
    }


# ── create / put ────────────────────────────────────────────────────────────
def create_secret(name: str, secret_string: str, description: str = "") -> dict:
    payload = {"Name": name, "SecretString": secret_string}
    if description:
        payload["Description"] = description
    body = _call("CreateSecret", payload)
    return {"name": body.get("Name", name), "arn": body.get("ARN", ""),
            "version_id": body.get("VersionId", "")}


def put_secret_value(name: str, secret_string: str) -> dict:
    """Store a new AWSCURRENT version (demotes the previous to AWSPREVIOUS)."""
    body = _call("PutSecretValue", {"SecretId": name, "SecretString": secret_string})
    return {"name": body.get("Name", name), "arn": body.get("ARN", ""),
            "version_id": body.get("VersionId", ""),
            "stages": body.get("VersionStages", [])}


def delete_secret(name: str) -> dict:
    """Force-delete (no recovery window) — keeps the console demo self-contained."""
    body = _call("DeleteSecret", {"SecretId": name, "ForceDeleteWithoutRecovery": True})
    return {"deleted": True, "name": body.get("Name", name), "arn": body.get("ARN", "")}
