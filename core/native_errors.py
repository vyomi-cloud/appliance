"""Native-shaped error responses from legacy (FastAPI) handlers.

`raise HTTPException(status, detail={...})` wraps the body as `{"detail": {...}}`, which is
not what a native cloud API returns — e.g. GCP's `{"error": {code, message, status}}` at the
TOP level, which the consoles and SDKs read. Raise `NativeHTTPError(status, body)` instead;
server.py's handler returns `body` verbatim with that status.
"""
from __future__ import annotations

from fastapi import HTTPException


class NativeHTTPError(HTTPException):
    def __init__(self, status_code: int, body: dict, headers: dict | None = None) -> None:
        super().__init__(status_code=status_code, detail=body, headers=headers)
        self.body = body
