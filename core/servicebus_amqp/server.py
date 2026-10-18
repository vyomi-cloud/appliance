"""Asyncio TCP Transport Server for AMQP 1.0.

Listens on TCP port 5672 (or specified port) and handles incoming
AMQP 1.0 client connections with non-blocking I/O and keepalive management.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Set

from .connection import AmqpConnection, ConnectionState

logger = logging.getLogger("servicebus_amqp")


class AmqpConnectionHandler:
    """Handles the network transport lifecycle for a single AMQP 1.0 TCP client."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        server: AmqpServer,
        container_id: str = "vyomi-servicebus-emulator",
    ):
        self.reader = reader
        self.writer = writer
        self.server = server
        self.conn = AmqpConnection(container_id=container_id)
        self.closed = False
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """Main loop: read incoming network packets and dispatch to state machine."""
        peer = self.writer.get_extra_info("peername")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            while not self.closed and self.conn.state != ConnectionState.CLOSED:
                data = await self.reader.read(65536)
                if not data:
                    # Client closed TCP socket (EOF)
                    break

                self.conn.feed_data(data)
                await self._flush_outbox()

        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as ex:
            logger.warning("Error in AMQP connection handler (%s): %s", peer, ex)
        finally:
            await self.close()

    async def _flush_outbox(self) -> None:
        if not self.conn.outbox or self.closed:
            return
        to_send = b"".join(self.conn.outbox)
        self.conn.outbox.clear()
        self.writer.write(to_send)
        await self.writer.drain()

    async def _heartbeat_loop(self) -> None:
        """Periodically check if an idle keepalive empty frame is due."""
        try:
            while not self.closed:
                await asyncio.sleep(1.0)
                if self.conn.state in (ConnectionState.OPENED, ConnectionState.HDR_EXCHANGED):
                    self.conn.check_idle_keepalive()
                    await self._flush_outbox()
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        try:
            await self._flush_outbox()
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass
        finally:
            self.server.remove_connection(self)


class AmqpServer:
    """AMQP 1.0 TCP Server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5672,
        container_id: str = "vyomi-servicebus-emulator",
    ):
        self.host = host
        self.port = port
        self.container_id = container_id
        self._server: asyncio.Server | None = None
        self._connections: Set[AmqpConnectionHandler] = set()
        self._is_running = False

    @property
    def actual_port(self) -> int:
        """Return the bound port (especially useful if bound to port 0)."""
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self.port

    async def start(self) -> None:
        """Start the asyncio TCP server."""
        if self._is_running:
            return
        self._server = await asyncio.start_server(
            self._on_client_connected,
            self.host,
            self.port,
        )
        self._is_running = True
        logger.info("AMQP 1.0 listener started on %s:%d", self.host, self.actual_port)

    def _on_client_connected(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        handler = AmqpConnectionHandler(
            reader=reader,
            writer=writer,
            server=self,
            container_id=self.container_id,
        )
        self._connections.add(handler)
        asyncio.create_task(handler.run())

    def remove_connection(self, handler: AmqpConnectionHandler) -> None:
        self._connections.discard(handler)

    async def stop(self) -> None:
        """Stop the AMQP server and close all active connections."""
        if not self._is_running:
            return
        self._is_running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Close all active connections concurrently so shutdown time doesn't
        # scale linearly with the number of open connections.
        active_handlers = list(self._connections)
        if active_handlers:
            await asyncio.gather(*(h.close() for h in active_handlers), return_exceptions=True)
        self._connections.clear()
        logger.info("AMQP 1.0 listener stopped")
