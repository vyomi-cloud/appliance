"""Offline appliance: start the Service Bus AMQP 1.0 listener (core/amqp_server.py) alongside the HTTP app.

  VYOMI_AMQP_PORT   plain AMQP + AMQP-over-WebSocket (path /$servicebus/websocket)   default 5672, 0 = off
  VYOMI_AMQPS_PORT  the same behind a self-signed TLS cert (needs the openssl CLI)   default 5671, 0 = off
  VYOMI_AMQP_HOST   bind address                                                     default 0.0.0.0

The broker runs on the SAME store the namespace-root REST data plane serves (wire_ingress.appliance_router().az_sb,
the Azure space's service_states), so the console's Service Bus Explorer and AMQP clients share one state.
Never fatal: a busy port or a missing dependency only logs.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("vyomi.servicebus.amqp")
_STATE = {"server": None, "container": None}


def _store():
    from core import app_context as ctx, wire_ingress as wi
    ctx.REQUEST_PROVIDER.set("azure")        # the Azure space's slot (this task's context only)
    return wi.appliance_router().az_sb


def _cmk_scope():
    """Premium-namespace customer-managed key: message bodies (and their AMQP wire image) stay sealed between operations"""
    from core import app_context as ctx, azure_servicebus_core as sb, wire_ingress as wi
    r = wi.appliance_router()
    return sb.CmkScope(_store(), sb.cmk_namespace(ctx.azure_arm_state, {}), r.az_kvkeys)


def _port(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def register(app) -> None:
    @app.on_event("startup")
    async def _start_servicebus_amqp():
        port, tls = _port("VYOMI_AMQP_PORT", 5672), _port("VYOMI_AMQPS_PORT", 5671)
        if not port and not tls:
            return
        # Two Service Bus AMQP stacks exist after the v3.0.47 -> v4 merge and they would race for 5672/5671.
        # Default runtime listener = core/servicebus_amqp (lease schema, mounted in server.py). This legacy
        # listener starts only when explicitly selected. See V4.0.0-KNOWN-ISSUES.md (SB-AMQP).
        if os.environ.get("VYOMI_SB_AMQP_STACK", "lease").strip().lower() != "legacy":
            return
        try:
            from core.amqp_server import AmqpServer
            from core.azure_servicebus_amqp import ServiceBusAmqp
            from core import middleware

            container = ServiceBusAmqp(_store, scope=_cmk_scope)
            srv = AmqpServer(container, on_dirty=middleware._schedule_persist)
            host = os.environ.get("VYOMI_AMQP_HOST", "0.0.0.0")
            data_dir = os.environ.get("VYOMI_DATA_DIR") or os.environ.get("CLOUDLEARN_DATA_DIR") or "/tmp"
            started = []
            try:
                started = await srv.start(host, port, 0)
            except OSError as e:
                log.warning("Service Bus AMQP port %s unavailable: %s", port, e)
            if tls:
                try:
                    started += [x for x in await _start_tls(srv, host, tls, data_dir)]
                except OSError as e:
                    log.warning("Service Bus AMQPS port %s unavailable: %s", tls, e)
            _STATE.update(server=srv, container=container)
            log.info("Service Bus AMQP 1.0 listening: %s", started)
        except Exception:
            log.exception("Service Bus AMQP listener failed to start")

    @app.on_event("shutdown")
    async def _stop_servicebus_amqp():
        srv = _STATE.get("server")
        if srv is not None:
            await srv.stop()


async def _start_tls(srv, host, tls_port, data_dir):
    """add the TLS listener to an already-started server (start() created the pump task)"""
    import asyncio
    import ssl
    from core.amqp_server import _self_signed_cert
    cc = _self_signed_cert(os.path.join(data_dir, "vyomi-amqps"))
    if not cc:
        log.info("AMQPS disabled: openssl CLI not available to mint the self-signed certificate")
        return []
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(*cc)
    srv.servers.append(await asyncio.start_server(srv._handle, host, tls_port, ssl=ctx))
    return [("amqps", tls_port)]
