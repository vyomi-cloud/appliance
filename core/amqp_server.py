"""Offline transport for the AMQP 1.0 engine (core/amqp10.py): asyncio TCP + AMQP-over-WebSocket.

One listening port serves BOTH wire forms by sniffing the first bytes of the connection:
  * `AMQP\\x00...` / `AMQP\\x03...`  -> raw AMQP 1.0 (what `azure-servicebus` / `@azure/service-bus` speak by default)
  * `GET ...`                       -> HTTP Upgrade to WebSocket (path /$servicebus/websocket, subprotocol
                                      AMQPWSB10 / amqp) carrying the same frames as binary messages.
An optional second port wraps the same handler in TLS with a self-signed certificate (openssl CLI, cached).

The container (core/azure_servicebus_amqp.ServiceBusAmqp) is driven from the event loop thread only; a
background task calls `container.pump()` (lock expiry, TTL, scheduled messages, push to credit-holding
consumers) and `conn.tick()` (idle-timeout keep-alives) every PUMP_S seconds.

This module is offline-only (sockets). The Nano substrate does not use it: the relay bridges frames into
the tab's Pyodide engine (see docs/architecture/v4.0/branches/azure-sb-amqp.md).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import os
import shutil
import ssl
import struct
import subprocess
import tempfile

try:
    from core import amqp10 as A
except ImportError:  # pragma: no cover
    import amqp10 as A  # type: ignore

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PUMP_S = 0.25


class _WsCodec:
    """minimal RFC 6455 server side: unmask client frames, frame binary replies"""

    def __init__(self):
        self.buf = bytearray()
        self.frag = bytearray()
        self.closed = False
        self.pending_ctrl = []

    def feed(self, data: bytes):
        """-> list of payload chunks (complete binary/text messages); control replies in .pending_ctrl"""
        self.buf += data
        out = []
        while True:
            if len(self.buf) < 2:
                break
            b0, b1 = self.buf[0], self.buf[1]
            fin, op = bool(b0 & 0x80), b0 & 0x0F
            masked, ln = bool(b1 & 0x80), b1 & 0x7F
            pos = 2
            if ln == 126:
                if len(self.buf) < 4:
                    break
                ln = struct.unpack_from(">H", self.buf, 2)[0]
                pos = 4
            elif ln == 127:
                if len(self.buf) < 10:
                    break
                ln = struct.unpack_from(">Q", self.buf, 2)[0]
                pos = 10
            need = pos + (4 if masked else 0) + ln
            if len(self.buf) < need:
                break
            mask = bytes(self.buf[pos:pos + 4]) if masked else None
            pl = bytearray(self.buf[pos + (4 if masked else 0):need])
            del self.buf[:need]
            if mask:
                for i in range(len(pl)):
                    pl[i] ^= mask[i & 3]
            if op in (0x0, 0x1, 0x2):
                self.frag += pl
                if fin:
                    out.append(bytes(self.frag))
                    self.frag = bytearray()
            elif op == 0x8:
                self.closed = True
                self.pending_ctrl.append(self.encode(bytes(pl[:2]), 0x8))
            elif op == 0x9:
                self.pending_ctrl.append(self.encode(bytes(pl), 0xA))
        return out

    @staticmethod
    def encode(payload: bytes, op: int = 0x2) -> bytes:
        n = len(payload)
        if n < 126:
            h = struct.pack(">BB", 0x80 | op, n)
        elif n < 65536:
            h = struct.pack(">BBH", 0x80 | op, 126, n)
        else:
            h = struct.pack(">BBQ", 0x80 | op, 127, n)
        return h + payload


def _self_signed_cert(dirpath: str):
    crt, key = os.path.join(dirpath, "amqps.crt"), os.path.join(dirpath, "amqps.key")
    if os.path.exists(crt) and os.path.exists(key):
        return crt, key
    if not shutil.which("openssl"):
        return None
    os.makedirs(dirpath, exist_ok=True)
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                        "-days", "825", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,DNS:*.servicebus.windows.net,IP:127.0.0.1"],
                       check=True, capture_output=True, timeout=30)
        return crt, key
    except Exception:
        return None


class AmqpServer:
    def __init__(self, container, on_dirty=None, ws_paths=("/$servicebus/websocket", "/")):
        self.container = container
        self.on_dirty = on_dirty or (lambda: None)
        self.servers = []
        self.conns = set()
        self.task = None
        self.ws_paths = ws_paths

    async def start(self, host="0.0.0.0", port=5672, tls_port=0, cert_dir=None):
        loop = asyncio.get_running_loop()
        started = []
        if self.task is None:
            self.task = loop.create_task(self._pump_loop())
        if port:
            self.servers.append(await asyncio.start_server(self._handle, host, port))
            started.append(("amqp", port))
        if tls_port:
            cc = _self_signed_cert(cert_dir or os.path.join(tempfile.gettempdir(), "vyomi-amqps"))
            if cc:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(*cc)
                self.servers.append(await asyncio.start_server(self._handle, host, tls_port, ssl=ctx))
                started.append(("amqps", tls_port))
        return started

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(BaseException):
                await self.task
        for s in self.servers:
            s.close()
        for c in list(self.conns):
            with contextlib.suppress(Exception):
                c.close()
        self.servers.clear()

    async def _pump_loop(self):
        while True:
            await asyncio.sleep(PUMP_S)
            try:
                self.container.pump()
                for c in list(self.conns):
                    c.tick()
                    self._flush(c)
                if getattr(self.container, "dirty", False):
                    self.container.dirty = False
                    self.on_dirty()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def _flush(self, conn):
        w = getattr(conn, "_writer", None)
        if w is None:
            return
        data = conn.take()
        if data:
            try:
                w.write(conn._wrap(data))
            except Exception:
                pass

    async def _handle(self, reader, writer):
        conn = A.Connection(self.container)
        conn._writer = writer
        conn._wrap = lambda b: b
        conn.on_output = lambda: self._flush(conn)
        self.conns.add(conn)
        ws = None
        try:
            first = await reader.read(65536)
            if not first:
                return
            pending = first
            if first[:4] == b"GET ":
                ws = _WsCodec()
                hdr_end = first.find(b"\r\n\r\n")
                while hdr_end < 0:
                    more = await reader.read(65536)
                    if not more:
                        return
                    first += more
                    hdr_end = first.find(b"\r\n\r\n")
                head, rest = first[:hdr_end].decode("latin-1"), first[hdr_end + 4:]
                lines = head.split("\r\n")
                path = lines[0].split(" ")[1] if len(lines[0].split(" ")) > 1 else "/"
                h = {}
                for ln in lines[1:]:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        h[k.strip().lower()] = v.strip()
                if "websocket" not in h.get("upgrade", "").lower() or "sec-websocket-key" not in h:
                    body = b"Vyomi Service Bus AMQP 1.0 endpoint\n"
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
                    await writer.drain()
                    return
                accept = base64.b64encode(hashlib.sha1(h["sec-websocket-key"].encode() + WS_GUID).digest()).decode()
                resp = ["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Connection: Upgrade",
                        "Sec-WebSocket-Accept: " + accept]
                offered = [p.strip() for p in h.get("sec-websocket-protocol", "").split(",") if p.strip()]
                if offered:
                    resp.append("Sec-WebSocket-Protocol: " + offered[0])
                writer.write(("\r\n".join(resp) + "\r\n\r\n").encode())
                conn._wrap = lambda b: _WsCodec.encode(b)
                pending = rest
                chunks = ws.feed(pending) if pending else []
                for c in chunks:
                    conn.feed(c)
            else:
                conn.feed(pending)
            self.container.push()
            self._flush(conn)
            await writer.drain()
            while not conn.closed or conn.out:
                if conn.closed and conn.close_after_flush:
                    self._flush(conn)
                    break
                data = await reader.read(65536)
                if not data:
                    break
                if ws is not None:
                    for c in ws.feed(data):
                        conn.feed(c)
                    for ctl in ws.pending_ctrl:
                        writer.write(ctl)
                    ws.pending_ctrl.clear()
                    if ws.closed:
                        break
                else:
                    conn.feed(data)
                self.container.push()
                self._flush(conn)
                await writer.drain()
            self._flush(conn)
            with contextlib.suppress(Exception):
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
            pass
        finally:
            self.conns.discard(conn)
            try:
                conn.connection_lost()
            except Exception:
                pass
            with contextlib.suppress(Exception):
                writer.close()
