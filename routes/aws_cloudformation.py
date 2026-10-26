"""AWS CloudFormation — native Query-protocol wire on the appliance's root `/`.

Thin glue: the engine is core/cloudformation_core.py (the same file Nano runs); this
module owns the durable store for the offline appliance and adapts the request.
"""
from __future__ import annotations

import os
import urllib.request
from urllib.parse import parse_qsl

from fastapi import Request
from fastapi.responses import Response

from core import cloudformation_core as cfn
from core.persistent_store import PersistentCfnStore, SqliteStateBackend

_store: PersistentCfnStore | None = None


def _fetch_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as r:   # TemplateURL → the appliance's own S3
        return r.read().decode("utf-8")


def get_store() -> PersistentCfnStore:
    global _store
    if _store is None:
        _store = PersistentCfnStore(SqliteStateBackend(os.environ.get("VYOMI_CFN_DB", "/tmp/vyomi-cfn.sqlite")))
        _store.fetch_url = _fetch_url
    return _store


async def handle(request: Request) -> Response:
    params = dict(request.query_params)
    raw = await request.body()
    if raw:
        params.update(dict(parse_qsl(raw.decode("utf-8", errors="ignore"), keep_blank_values=True)))
    r = cfn.dispatch(get_store(), params)
    return Response(content=r.body, status_code=r.status, media_type="text/xml")
