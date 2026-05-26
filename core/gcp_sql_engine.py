"""Real Cloud SQL data plane.

Backs each simulated Cloud SQL instance with a real database on a shared
PostgreSQL or MySQL engine (one database + login role per instance), so an
unmodified application can connect over the normal wire protocol (psycopg2 /
mysql-connector) using the host:port:database:user the console shows.

Provisioning uses the engine's internal (compose-network) address; the endpoint
returned to the app uses the externally reachable host (the host the console was
reached on) and the published port. If the engine is not reachable the caller
should degrade to a metadata-only ("simulated") instance.
"""

from __future__ import annotations

import hashlib
import os
import re


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9_]", "_", str(value or "").lower()).strip("_")
    return out[:16] or "db"


def engine_for_version(version: str) -> str | None:
    """Map a Cloud SQL databaseVersion to a backing engine, or None if unsupported."""
    v = str(version or "").upper()
    if v.startswith("MYSQL"):
        return "mysql"
    if v.startswith("POSTGRES"):
        return "postgres"
    # SQLSERVER and anything else: no OSS engine wired up -> degrade.
    return None


def _engine_config(engine: str) -> dict:
    if engine == "mysql":
        return {
            "host": _env("CLOUDLEARN_SQL_MYSQL_HOST", default="cloudlearn-sql-mysql"),
            "port": int(_env("CLOUDLEARN_SQL_MYSQL_PORT", default="3306")),
            "admin_user": _env("CLOUDLEARN_SQL_MYSQL_ADMIN_USER", default="root"),
            "admin_password": _env("CLOUDLEARN_SQL_MYSQL_ADMIN_PASSWORD", default="cloudlearn"),
            "public_port": int(_env("CLOUDLEARN_SQL_MYSQL_PUBLIC_PORT", "CLOUDLEARN_SQL_MYSQL_PORT", default="3306")),
        }
    return {
        "host": _env("CLOUDLEARN_SQL_PG_HOST", default="cloudlearn-sql-postgres"),
        "port": int(_env("CLOUDLEARN_SQL_PG_PORT", default="5432")),
        "admin_user": _env("CLOUDLEARN_SQL_PG_ADMIN_USER", default="postgres"),
        "admin_password": _env("CLOUDLEARN_SQL_PG_ADMIN_PASSWORD", default="cloudlearn"),
        "public_port": int(_env("CLOUDLEARN_SQL_PG_PUBLIC_PORT", "CLOUDLEARN_SQL_PG_PORT", default="5432")),
    }


def physical_name(space_id: str, project: str, instance: str) -> str:
    """Stable, collision-free physical db/role name for an instance."""
    digest = hashlib.sha1(f"{space_id}:{project}:{instance}".encode()).hexdigest()[:8]
    return f"cl_{_slug(instance)}_{digest}"


def public_host(request_host: str = "") -> str:
    """Host an external app uses to reach the engine. Prefer an explicit override,
    else the host the console was reached on (strip any port), else localhost."""
    override = _env("CLOUDLEARN_SQL_PUBLIC_HOST")
    if override:
        return override
    host = str(request_host or "").split("//")[-1].split("/")[0].split(":")[0].strip()
    return host or "localhost"


def available(engine: str) -> bool:
    cfg = _engine_config(engine)
    try:
        if engine == "postgres":
            import psycopg2  # noqa: F401
        else:
            import pymysql  # noqa: F401
    except Exception:
        return False
    return bool(cfg.get("host"))


def _pg_connect(cfg: dict):
    import psycopg2
    conn = psycopg2.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["admin_user"],
        password=cfg["admin_password"], dbname="postgres", connect_timeout=5,
    )
    conn.autocommit = True
    return conn


def _mysql_connect(cfg: dict):
    import pymysql
    return pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["admin_user"],
        password=cfg["admin_password"], autocommit=True, connect_timeout=5,
    )


def provision(space_id: str, project: str, instance: str, version: str,
              user: str, password: str, request_host: str = "") -> dict:
    """Create the real database + login role. Returns the connection endpoint.
    Raises on failure so the caller can degrade to a simulated instance."""
    engine = engine_for_version(version)
    if not engine:
        raise RuntimeError(f"No OSS engine for databaseVersion {version!r}")
    cfg = _engine_config(engine)
    db = physical_name(space_id, project, instance)
    role = db  # unique per instance -> no cross-instance credential clashes
    pwd = password or "Password123!"

    if engine == "postgres":
        conn = _pg_connect(cfg)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
            if cur.fetchone():
                cur.execute(f'ALTER ROLE "{role}" WITH LOGIN PASSWORD %s', (pwd,))
            else:
                cur.execute(f'CREATE ROLE "{role}" WITH LOGIN PASSWORD %s', (pwd,))
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{db}" OWNER "{role}"')
            cur.close()
        finally:
            conn.close()
    else:
        conn = _mysql_connect(cfg)
        try:
            cur = conn.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}`")
            cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (role, pwd))
            cur.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (role, pwd))
            cur.execute(f"GRANT ALL PRIVILEGES ON `{db}`.* TO %s@'%%'", (role,))
            cur.execute("FLUSH PRIVILEGES")
            cur.close()
        finally:
            conn.close()

    return {
        "engine": "POSTGRES" if engine == "postgres" else "MYSQL",
        "host": public_host(request_host),
        "port": cfg["public_port"],
        "database": db,
        "user": role,
        "password": pwd,
    }


def deprovision(space_id: str, project: str, instance: str, version: str) -> bool:
    """Drop the real database + role. Best-effort; returns True if it ran."""
    engine = engine_for_version(version)
    if not engine or not available(engine):
        return False
    cfg = _engine_config(engine)
    db = physical_name(space_id, project, instance)
    role = db
    try:
        if engine == "postgres":
            conn = _pg_connect(cfg)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (db,)
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
                cur.execute(f'DROP ROLE IF EXISTS "{role}"')
                cur.close()
            finally:
                conn.close()
        else:
            conn = _mysql_connect(cfg)
            try:
                cur = conn.cursor()
                cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
                cur.execute("DROP USER IF EXISTS %s@'%%'", (role,))
                cur.close()
            finally:
                conn.close()
        return True
    except Exception:
        return False
