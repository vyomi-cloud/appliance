"""AMQP 1.0 Server Lifecycle, TLS (5671), and Connection String Generation.

Manages startup, shutdown, TLS context initialization, and connection string
formatting for Azure Service Bus AMQP 1.0 emulation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import ssl
from pathlib import Path
from typing import Any

from .server import AmqpServer

logger = logging.getLogger("servicebus_amqp.lifecycle")

DEFAULT_AMQP_PORT = 5672
DEFAULT_AMQPS_PORT = 5671
DEFAULT_SAS_KEY_NAME = "RootManageSharedAccessKey"

_SAS_KEY_PATH = Path(os.environ.get("CLOUDLEARN_SERVICEBUS_SAS_KEY_FILE", "/data/.vyomi_servicebus_sas_key"))
_SAS_KEY_PATH_LOCAL = Path(__file__).parent.parent.parent / ".vyomi_servicebus_sas_key"
_cached_sas_key: str = ""


def _sas_key_path() -> Path:
    if _SAS_KEY_PATH.parent.exists():
        return _SAS_KEY_PATH
    return _SAS_KEY_PATH_LOCAL


def get_or_create_sas_key() -> str:
    """Return this install's Service Bus SAS key, generated on first boot and
    persisted so it stays stable across restarts (same pattern as
    core.admin_auth.get_or_create_admin_key)."""
    global _cached_sas_key
    if _cached_sas_key:
        return _cached_sas_key
    path = _sas_key_path()
    if path.exists():
        try:
            key = path.read_text().strip()
            if key:
                _cached_sas_key = key
                return _cached_sas_key
        except Exception:
            pass
    key = secrets.token_urlsafe(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key)
        os.chmod(str(path), 0o600)
    except Exception:
        pass
    _cached_sas_key = key
    return key


def get_connection_string(
    host: str = "localhost",
    port: int = DEFAULT_AMQP_PORT,
    use_emulator: bool = True,
    shared_access_key_name: str = DEFAULT_SAS_KEY_NAME,
    shared_access_key: str | None = None,
) -> str:
    """Generate an Azure Service Bus connection string compatible with Azure SDKs.

    Format:
        Endpoint=sb://<host>[:<port>];SharedAccessKeyName=<name>;SharedAccessKey=<key>;UseDevelopmentEmulator=true;
    """
    key = shared_access_key or get_or_create_sas_key()
    endpoint = f"sb://{host}"
    if port != DEFAULT_AMQP_PORT and port != DEFAULT_AMQPS_PORT:
        endpoint = f"sb://{host}:{port}"

    emulator_param = "UseDevelopmentEmulator=true;" if use_emulator else ""
    return (
        f"Endpoint={endpoint};"
        f"SharedAccessKeyName={shared_access_key_name};"
        f"SharedAccessKey={key};"
        f"{emulator_param}"
    )


def get_servicebus_env(
    host: str = "localhost",
    port: int = DEFAULT_AMQP_PORT,
) -> dict[str, str]:
    """Return dictionary of environment variables to inject for Siftly/Azure clients."""
    conn_str = get_connection_string(host=host, port=port)
    return {
        "AZURE_SERVICEBUS_CONNECTION_STRING": conn_str,
        "AZURE_SERVICEBUS_EMULATOR_HOST": f"{host}:{port}",
    }


def find_tls_cert_paths() -> tuple[Path, Path] | None:
    """Discover local TLS certificate and key files (e.g. provisioned by mkcert)."""
    # 1. Explicit env vars
    cert_env = os.environ.get("VYOMI_TLS_CERT")
    key_env = os.environ.get("VYOMI_TLS_KEY")
    if cert_env and key_env:
        cert_p = Path(cert_env)
        key_p = Path(key_env)
        if cert_p.exists() and key_p.exists():
            return cert_p, key_p

    # 2. TLS dir (default ~/.vyomi/tls/)
    tls_dir_str = os.environ.get(
        "VYOMI_TLS_DIR", os.path.expanduser("~/.vyomi/tls")
    )
    tls_dir = Path(tls_dir_str)
    cert_p = tls_dir / "cert.pem"
    key_p = tls_dir / "key.pem"
    if cert_p.exists() and key_p.exists():
        return cert_p, key_p

    return None


def build_ssl_context(
    certfile: str | Path | None = None,
    keyfile: str | Path | None = None,
) -> ssl.SSLContext | None:
    """Build an SSLContext for AMQPS (port 5671) if certificates are available."""
    if certfile and keyfile:
        c_path, k_path = Path(certfile), Path(keyfile)
    else:
        paths = find_tls_cert_paths()
        if not paths:
            return None
        c_path, k_path = paths

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(c_path), keyfile=str(k_path))
        return ctx
    except Exception as ex:
        logger.warning("Failed to load TLS cert chain (%s, %s): %s", c_path, k_path, ex)
        return None


class AmqpLifecycleManager:
    """Coordinates lifecycle of plaintext and TLS AMQP servers."""

    def __init__(self) -> None:
        self.server_plain: AmqpServer | None = None
        self.server_tls: AmqpServer | None = None
        self._is_started = False

    async def start(
        self,
        host: str = "0.0.0.0",
        port: int = DEFAULT_AMQP_PORT,
        tls_port: int | None = DEFAULT_AMQPS_PORT,
        store: Any = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        """Start AMQP listeners for plaintext (5672) and optional TLS (5671)."""
        if self._is_started:
            return

        # 1. Plaintext AMQP listener
        self.server_plain = AmqpServer(
            host=host,
            port=port,
            store=store,
            container_id="vyomi-servicebus-emulator",
        )
        try:
            await self.server_plain.start()
        except OSError as ex:
            logger.warning("Could not bind AMQP plaintext on %s:%d: %s", host, port, ex)
            self.server_plain = None

        # 2. TLS AMQPS listener (port 5671)
        if tls_port is not None:
            ctx = ssl_context or build_ssl_context()
            if ctx:
                self.server_tls = AmqpServer(
                    host=host,
                    port=tls_port,
                    store=store,
                    ssl_context=ctx,
                    container_id="vyomi-servicebus-emulator-tls",
                )
                try:
                    await self.server_tls.start()
                except OSError as ex:
                    logger.warning("Could not bind AMQP TLS on %s:%d: %s", host, tls_port, ex)
                    self.server_tls = None

        if self.server_plain is None and self.server_tls is None:
            logger.error(
                "AMQP Service Bus listener failed to bind on both %s:%d and TLS %s — "
                "not marking lifecycle as started so a later retry isn't blocked.",
                host, port, tls_port,
            )
            return

        self._is_started = True

    async def stop(self) -> None:
        """Stop all active AMQP listeners cleanly."""
        if not self._is_started:
            return
        if self.server_plain:
            await self.server_plain.stop()
            self.server_plain = None
        if self.server_tls:
            await self.server_tls.stop()
            self.server_tls = None
        self._is_started = False


# Global singleton instance
_lifecycle_manager = AmqpLifecycleManager()


def get_lifecycle_manager() -> AmqpLifecycleManager:
    return _lifecycle_manager


def mount(app: Any) -> None:
    """Mount AMQP server startup and shutdown hooks into a FastAPI/Starlette application."""
    @app.on_event("startup")
    async def _amqp_startup():
        enabled = os.environ.get("VYOMI_AMQP_SERVICEBUS", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
            "disabled",
        )
        if not enabled:
            return

        # A single backend's failure to start (bad env var, port conflict)
        # must never prevent the simulator itself from booting — same
        # convention as core/backend_rehydrate.py.
        try:
            host = os.environ.get("VYOMI_AMQP_HOST", "0.0.0.0")
            # NOTE: "0" means something different for each of these two vars.
            # VYOMI_AMQP_PORT=0 -> bind an OS-assigned ephemeral port (asyncio
            # socket convention). VYOMI_AMQPS_PORT=0 -> disable TLS entirely
            # (there is no "ephemeral TLS port" use case here). Intentional,
            # but easy to mix up — don't assume the two are symmetric.
            port = int(os.environ.get("VYOMI_AMQP_PORT", str(DEFAULT_AMQP_PORT)))
            tls_port_env = os.environ.get("VYOMI_AMQPS_PORT", str(DEFAULT_AMQPS_PORT))
            tls_port = int(tls_port_env) if tls_port_env and tls_port_env != "0" else None

            await _lifecycle_manager.start(host=host, port=port, tls_port=tls_port)

            env = get_servicebus_env(host=host if host != "0.0.0.0" else "localhost", port=port)
            for key, value in env.items():
                os.environ.setdefault(key, value)
        except Exception as ex:
            logger.warning("AMQP Service Bus startup failed, continuing without it: %s", ex)

    @app.on_event("shutdown")
    async def _amqp_shutdown():
        await _lifecycle_manager.stop()
