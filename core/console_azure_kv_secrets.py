"""console-next Key Vault (secrets) facade (Azure) — the Azure lens's kv-secret-viewer
data plane.

The SAME kv-secret-viewer widget renders under lens=azure; the ONLY difference is the
manifest `api` block pointing at /api/console/azure-kv-secrets/* instead of
/api/console/secrets/* (§15.2 — no if(cloud) branching in the widget). This module is
the Azure Key Vault sibling of the GCP Secret Manager console facade
(core/console_gcp_secrets.py) and the AWS Secrets Manager facade
(core/console_secrets.py): it returns the SAME JSON response shapes the widget consumes
(list secrets, describe versions+stages, reveal the value, create + put-value), so the
widget stays cloud-agnostic.

Azure Key Vault mapping onto the widget's model:
    a SECRET is a named object; setting a value creates a new VERSION. The newest
    version is the widget's AWSCURRENT (Key Vault's "current" enabled version); the
    one before it maps to AWSPREVIOUS. So the widget's "version → stage" list, masked
    value + deliberate reveal, and "put value → new current, prior demoted" flow all
    work unchanged.

Purely additive + substrate-free (no fastapi / azure-sdk imports): it holds its OWN
module-level in-memory store so the Azure lens's secrets state is independent of the
AWS/GCP lenses', exactly like core/console_gcp_secrets mirrors the AWS Secrets facade.
It never touches the appliance's native Key Vault handling or the shared KvStore the
AWS secrets facade uses. Values are returned as-is; MASKING is a UI concern (the widget
hides them by default), so the honest secret is always available for a deliberate
reveal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

VAULT = "vyomi-kv"

# Azure Key Vault version-state labels mapped onto the widget's stage tags: the newest
# version is the "current" one, the prior version the "previous" one (mirrors
# AWSCURRENT / AWSPREVIOUS so the SAME widget renders both lenses).
STAGE_CURRENT = "Enabled (current)"
STAGE_PREVIOUS = "Enabled (prior)"

# In-memory store, independent from the AWS/GCP secrets facades:
#   secrets: { name: { "created": iso, "description": str,
#              "versions": [ { version_id, created, secret_string } ] } }
# The LAST element of "versions" is the newest (current) version.
_SECRETS: dict[str, dict[str, Any]] = {}


def reset() -> None:  # test hook
    _SECRETS.clear()


class AzureKvSecretsError(Exception):
    """Facade error carrying an HTTP status + message (mapped to HTTPException)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _secret_path(name: str, version_id: str = "") -> str:
    base = f"https://{VAULT}.vault.azure.net/secrets/{name}"
    return f"{base}/{version_id}" if version_id else base


def _stages_for(versions: list[dict], idx: int) -> list[str]:
    """Stage tags for the version at index `idx` (newest = current, prior = previous)."""
    last = len(versions) - 1
    if idx == last:
        return [STAGE_CURRENT]
    if idx == last - 1:
        return [STAGE_PREVIOUS]
    return []


def _secret(name: str) -> dict:
    s = _SECRETS.get(name)
    if s is None:
        raise AzureKvSecretsError("The specified secret does not exist.", 404)
    return s


# ── list / describe / get ────────────────────────────────────────────────
def list_secrets() -> dict:
    """List secrets — SAME JSON shape console_secrets.list_secrets returns."""
    out = []
    for name in sorted(_SECRETS):
        s = _SECRETS[name]
        vers = s.get("versions", [])
        out.append(
            {
                "name": name,
                "arn": _secret_path(name),
                "description": s.get("description", ""),
                "created": s.get("created"),
                "last_changed": vers[-1]["created"] if vers else s.get("created"),
                "deleted_date": None,
            }
        )
    return {"secrets": out, "count": len(out)}


def describe_secret(name: str) -> dict:
    """Metadata + version→stage list for a secret. NO secret value here — SAME shape
    console_secrets.describe_secret returns (newest version first)."""
    s = _secret(name)
    vers = s.get("versions", [])
    versions = [
        {"version_id": v["version_id"], "stages": _stages_for(vers, i)}
        for i, v in reversed(list(enumerate(vers)))
    ]
    return {
        "name": name,
        "arn": _secret_path(name),
        "description": s.get("description", ""),
        "created": s.get("created"),
        "last_changed": vers[-1]["created"] if vers else s.get("created"),
        "deleted_date": None,
        "versions": versions,
    }


def get_secret_value(name: str, version_id: str | None = None,
                     version_stage: str | None = None) -> dict:
    """The (unmasked) secret value for a version — the WIDGET masks it by default and
    only calls this on a deliberate reveal. Defaults to the newest (current) version."""
    s = _secret(name)
    vers = s.get("versions", [])
    if not vers:
        raise AzureKvSecretsError("The secret has no versions.", 404)
    idx = len(vers) - 1
    if version_id:
        idx = next((i for i, v in enumerate(vers) if v["version_id"] == version_id), -1)
        if idx < 0:
            raise AzureKvSecretsError("The specified version does not exist.", 404)
    v = vers[idx]
    return {
        "name": name,
        "arn": _secret_path(name, v["version_id"]),
        "version_id": v["version_id"],
        "stages": _stages_for(vers, idx),
        "created": v.get("created"),
        "secret_string": v.get("secret_string"),
        "secret_binary": None,
    }


# ── create / put / delete ─────────────────────────────────────────────────
def create_secret(name: str, secret_string: str, description: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise AzureKvSecretsError("ValidationError: secret name is required.", 400)
    if name in _SECRETS:
        raise AzureKvSecretsError("Conflict: secret already exists.", 409)
    version_id = uuid.uuid4().hex
    _SECRETS[name] = {
        "created": _now_iso(),
        "description": description or "",
        "versions": [
            {"version_id": version_id, "created": _now_iso(),
             "secret_string": secret_string or ""}
        ],
    }
    return {"name": name, "arn": _secret_path(name, version_id), "version_id": version_id}


def put_secret_value(name: str, secret_string: str) -> dict:
    """Add a new version → becomes the current one; the prior current is demoted to
    previous (mirrors console_secrets.put_secret_value)."""
    s = _secret(name)
    version_id = uuid.uuid4().hex
    s["versions"].append(
        {"version_id": version_id, "created": _now_iso(),
         "secret_string": secret_string or ""}
    )
    return {"name": name, "arn": _secret_path(name, version_id), "version_id": version_id,
            "stages": [STAGE_CURRENT]}


def delete_secret(name: str) -> dict:
    if name not in _SECRETS:
        raise AzureKvSecretsError("The specified secret does not exist.", 404)
    _SECRETS.pop(name, None)
    return {"deleted": True, "name": name, "arn": _secret_path(name)}
