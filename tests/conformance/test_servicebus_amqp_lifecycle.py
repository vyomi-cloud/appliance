"""Layer 5 Conformance: AMQP 1.0 Server Lifecycle, Ports, TLS, and Connection String.

Verifies:
1. Azure Service Bus connection string generation and formatting.
2. Plaintext AMQP listener startup, dynamic port binding, TCP handshake, and clean shutdown.
3. TLS AMQPS listener startup with SSLContext, secure TLS handshake, and clean shutdown.
4. FastAPI application mount and lifecycle event integration.
"""

import asyncio
import os
import socket
import ssl
import tempfile
from pathlib import Path

from core.servicebus_amqp import (
    DEFAULT_AMQP_PORT,
    DEFAULT_AMQPS_PORT,
    AmqpLifecycleManager,
    build_ssl_context,
    get_connection_string,
    get_lifecycle_manager,
    get_servicebus_env,
    mount,
)
from core.servicebus_amqp.codec import (
    AMQP_HEADER,
    FRAME_TYPE_AMQP,
    decode_frame,
    encode_frame,
)
from core.servicebus_amqp.performatives import (
    Close,
    Open,
    parse_performative,
)
from core.servicebus_amqp.server import AmqpServer


def assert_eq(actual, expected, msg=""):
    assert actual == expected, f"{msg} | expected {expected!r}, got {actual!r}"


def test_connection_string_generation():
    print("  testing connection string and env var generation...")

    # Default connection string
    cs_default = get_connection_string()
    assert "Endpoint=sb://localhost;" in cs_default
    assert "SharedAccessKeyName=RootManageSharedAccessKey;" in cs_default
    assert "SharedAccessKey=" in cs_default
    assert "UseDevelopmentEmulator=true;" in cs_default

    # Custom host and port
    cs_custom = get_connection_string(host="10.0.0.1", port=5673)
    assert "Endpoint=sb://10.0.0.1:5673;" in cs_custom

    # Env mapping
    env = get_servicebus_env(host="127.0.0.1", port=5672)
    assert "AZURE_SERVICEBUS_CONNECTION_STRING" in env
    assert "AZURE_SERVICEBUS_EMULATOR_HOST" in env
    assert env["AZURE_SERVICEBUS_EMULATOR_HOST"] == "127.0.0.1:5672"
    print("  ok  connection string and env verified")


def test_plaintext_lifecycle_and_handshake():
    print("  testing plaintext AMQP listener lifecycle on dynamic port...")

    async def _run():
        server = AmqpServer(host="127.0.0.1", port=0)
        await server.start()
        port = server.actual_port
        assert port > 0

        def _client_talk():
            s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
            try:
                s.sendall(AMQP_HEADER)
                resp = s.recv(8)
                assert_eq(resp, AMQP_HEADER)

                # Send Open
                s.sendall(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="test-client")))
                buf = s.recv(4096)
                frame = decode_frame(buf)
                assert frame is not None
                open_resp = parse_performative(frame[4])
                assert isinstance(open_resp, Open)
                assert_eq(open_resp.container_id, "vyomi-servicebus-emulator")

                # Send Close
                s.sendall(encode_frame(FRAME_TYPE_AMQP, 0, Close()))
            finally:
                s.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _client_talk)
        await server.stop()
        assert not server._is_running

    asyncio.run(_run())
    print("  ok  plaintext listener start, handshake, and stop verified")


def _generate_self_signed_cert(cert_path: Path, key_path: Path):
    """Generate a self-signed certificate for local testing without external tools."""
    import subprocess
    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        "1",
        "-nodes",
        "-subj",
        "/CN=localhost",
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_tls_lifecycle_and_handshake():
    print("  testing TLS AMQPS listener lifecycle on dynamic port...")

    with tempfile.TemporaryDirectory() as tmpdir:
        cert_p = Path(tmpdir) / "cert.pem"
        key_p = Path(tmpdir) / "key.pem"
        _generate_self_signed_cert(cert_p, key_p)

        server_ctx = build_ssl_context(certfile=cert_p, keyfile=key_p)
        assert server_ctx is not None

        async def _run():
            server = AmqpServer(host="127.0.0.1", port=0, ssl_context=server_ctx)
            await server.start()
            port = server.actual_port
            assert port > 0

            def _client_talk():
                # Client SSL context (trust self-signed cert for test)
                client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                client_ctx.check_hostname = False
                client_ctx.verify_mode = ssl.CERT_NONE

                raw_sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
                ssl_sock = client_ctx.wrap_socket(raw_sock, server_hostname="localhost")
                try:
                    ssl_sock.sendall(AMQP_HEADER)
                    resp = ssl_sock.recv(8)
                    assert_eq(resp, AMQP_HEADER)

                    # Send Open over TLS
                    ssl_sock.sendall(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="tls-client")))
                    buf = ssl_sock.recv(4096)
                    frame = decode_frame(buf)
                    assert frame is not None
                    open_resp = parse_performative(frame[4])
                    assert isinstance(open_resp, Open)
                    assert_eq(open_resp.container_id, "vyomi-servicebus-emulator")
                finally:
                    ssl_sock.close()

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _client_talk)
            await server.stop()
            assert not server._is_running

        asyncio.run(_run())
    print("  ok  TLS AMQPS listener start, TLS handshake, and stop verified")


def test_fastapi_mount_integration():
    print("  testing FastAPI mount lifecycle hooks...")

    class DummyApp:
        def __init__(self):
            self.startup_handlers = []
            self.shutdown_handlers = []

        def on_event(self, event_type: str):
            def decorator(func):
                if event_type == "startup":
                    self.startup_handlers.append(func)
                elif event_type == "shutdown":
                    self.shutdown_handlers.append(func)
                return func
            return decorator

    app = DummyApp()
    mount(app)
    assert len(app.startup_handlers) == 1
    assert len(app.shutdown_handlers) == 1

    async def _test_events():
        # Test startup with dynamic port via env
        os.environ["VYOMI_AMQP_PORT"] = "0"
        os.environ["VYOMI_AMQPS_PORT"] = "0"
        for handler in app.startup_handlers:
            await handler()

        mgr = get_lifecycle_manager()
        assert mgr._is_started

        for handler in app.shutdown_handlers:
            await handler()

        assert not mgr._is_started
        os.environ.pop("VYOMI_AMQP_PORT", None)
        os.environ.pop("VYOMI_AMQPS_PORT", None)

    asyncio.run(_test_events())
    print("  ok  FastAPI mount startup and shutdown hooks verified")


def main():
    print("Running AMQP 1.0 Server Lifecycle & Ports Conformance Suite (Layer 5):")
    test_connection_string_generation()
    test_plaintext_lifecycle_and_handshake()
    test_tls_lifecycle_and_handshake()
    test_fastapi_mount_integration()
    print("\nAMQP 1.0 Lifecycle (Layer 5) Conformance: ALL GREEN\n")


if __name__ == "__main__":
    main()
