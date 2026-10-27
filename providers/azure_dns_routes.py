"""Offline wire for Azure DNS resolution (the "dig" side of the in-process DNS backend).

core/azure_dns_core.py owns the zones and record sets (ARM ``Microsoft.Network/dnsZones``);
``GET /azure-data/dns/query?name=www.example.com&type=A`` answers from them as DNS-over-HTTPS-style
JSON (``Status`` 0 NOERROR / 3 NXDOMAIN / 5 REFUSED, ``Answer`` records), so a record you create with
the SDK or ``az network dns`` can be verified with ``curl`` without delegating a real domain.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from core import azure_dns_core as core


def _state():
    from providers import azure_services
    return azure_services._state


def register(app) -> None:
    async def query(request: Request):
        r = core.data_dispatch(_state(), request.method, dict(request.query_params))
        return JSONResponse(status_code=r["status"], content=r["body"])

    app.add_api_route("/azure-data/dns/query", query, methods=["GET"], include_in_schema=False)
