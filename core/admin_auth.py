"""Admin API key authentication for sensitive appliance endpoints.

On first boot, generates a random admin key and stores it at
/data/.cloudlearn_admin_key (or local fallback). The key is displayed
once in startup logs. All protected endpoints check for the
X-CloudLearn-Admin-Key header.
"""
from __future__ import annotations
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

try:
    from fastapi import Request, HTTPException
except ImportError:  # pragma: no cover — host test fallback
    Request = Any  # type: ignore
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int, detail: Any = None):
            self.status_code = status_code
            self.detail = detail

logger = logging.getLogger("cloudlearn.admin_auth")

_ADMIN_KEY_PATH = Path(os.environ.get("CLOUDLEARN_ADMIN_KEY_FILE", "/data/.cloudlearn_admin_key"))
_ADMIN_KEY_PATH_LOCAL = Path(__file__).parent.parent / ".cloudlearn_admin_key"

_cached_key: str = ""
_HEADER_NAME = "X-CloudLearn-Admin-Key"

# Rate limiting for auth endpoints
_auth_attempts: dict[str, list[float]] = {}  # ip -> [timestamps]
_AUTH_RATE_LIMIT = 5  # max attempts
_AUTH_RATE_WINDOW = 60.0  # per minute


def _key_path() -> Path:
    if _ADMIN_KEY_PATH.parent.exists():
        return _ADMIN_KEY_PATH
    return _ADMIN_KEY_PATH_LOCAL


def get_or_create_admin_key() -> str:
    """Return the admin API key. Generated on first boot."""
    global _cached_key
    if _cached_key:
        return _cached_key
    path = _key_path()
    if path.exists():
        try:
            key = path.read_text().strip()
            if len(key) >= 32:
                _cached_key = key
                return _cached_key
        except Exception:
            pass
    # Generate new key
    key = secrets.token_urlsafe(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key)
        os.chmod(str(path), 0o600)
    except Exception:
        pass
    _cached_key = key
    logger.warning(
        "\n" + "=" * 60 +
        "\n  CLOUDLEARN ADMIN KEY (save this — shown once):" +
        f"\n  {key}" +
        "\n" + "=" * 60
    )
    return key


def verify_admin_key(request: Request) -> bool:
    """Check if the request carries a valid admin key. Returns True if valid."""
    provided = request.headers.get(_HEADER_NAME, "").strip()
    if not provided:
        for k, v in getattr(request, "headers", {}).items():
            if k.lower() in ("x-cloudlearn-admin-key", "x-vyomi-admin-key"):
                provided = str(v).strip()
                break
    if not provided:
        return False
    expected = get_or_create_admin_key()
    return secrets.compare_digest(provided, expected)


def require_admin_key(request: Request) -> None:
    """Raise 403 if the request doesn't carry a valid admin key.
    Call this at the top of protected endpoints."""
    from core.app_context import appliance_mode_enabled
    if not appliance_mode_enabled():
        return  # dev mode — no auth required
    if not verify_admin_key(request):
        raise HTTPException(
            status_code=403,
            detail={"ok": False, "code": "admin_key_required",
                    "reason": f"This endpoint requires the {_HEADER_NAME} header in appliance mode."},
        )


def check_auth_rate_limit(request: Request) -> None:
    """Rate-limit authentication attempts. 5 per minute per IP."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = _auth_attempts.setdefault(ip, [])
    # Prune old attempts
    _auth_attempts[ip] = [t for t in attempts if now - t < _AUTH_RATE_WINDOW]
    if len(_auth_attempts[ip]) >= _AUTH_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"ok": False, "code": "rate_limited",
                    "reason": f"Too many auth attempts. Max {_AUTH_RATE_LIMIT} per minute."},
        )
    _auth_attempts[ip].append(now)
