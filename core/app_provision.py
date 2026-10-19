"""App provisioning and output expression resolver.

Part of the app profile runtime (§4, §6, AE3, AE4).
Validates resources against security allow-lists, provisions Postgres roles/databases/extensions,
blob containers, and Redis instances, and resolves `${...}` expressions into concrete environment values.
"""
from __future__ import annotations

import logging
import os
import time
import re
import urllib.parse
from typing import Any

from core import app_state

log = logging.getLogger("vyomi.app_provision")

# Security allow-lists
ALLOWED_EXTENSIONS = frozenset({
    "vector", "uuid-ossp", "pg_trgm", "citext", "pgcrypto",
    "btree_gist", "btree_gin", "unaccent", "hstore"
})

ALLOWED_SETTABLE_PARAMETERS = frozenset({
    "session_replication_role"
})

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_EXPR_PATTERN = re.compile(r"(?<!\$)\$\{([a-zA-Z0-9_.]+)\}")


def validate_identifier(name: str, context: str = "identifier") -> str:
    """Validate that name is a safe SQL/resource identifier."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {context} name {name!r}: must match ^[a-zA-Z_][a-zA-Z0-9_]{{0,62}}$")
    return name


def validate_resources(resources: dict[str, Any]) -> None:
    """Validate the profile resources JSON schema and allow-lists."""
    if not isinstance(resources, dict):
        raise ValueError("Profile 'resources' must be an object")

    # Postgres
    for db_name, pg_cfg in resources.get("postgres", {}).items():
        validate_identifier(db_name, "database")
        if not isinstance(pg_cfg, dict):
            raise ValueError(f"postgres.{db_name} must be an object")
        user = pg_cfg.get("user", db_name)
        validate_identifier(user, "user")
        for ext in pg_cfg.get("extensions", []):
            if ext not in ALLOWED_EXTENSIONS:
                raise ValueError(
                    f"Disallowed extension {ext!r} in postgres.{db_name}. Allowed: {sorted(ALLOWED_EXTENSIONS)}"
                )
        for param in pg_cfg.get("settable_parameters", []):
            if param not in ALLOWED_SETTABLE_PARAMETERS:
                raise ValueError(
                    f"Disallowed parameter {param!r} in postgres.{db_name}. Allowed: {sorted(ALLOWED_SETTABLE_PARAMETERS)}"
                )

    # Blob
    for acct_name, blob_cfg in resources.get("blob", {}).items():
        validate_identifier(acct_name, "blob account")
        if not isinstance(blob_cfg, dict):
            raise ValueError(f"blob.{acct_name} must be an object")
        for container in blob_cfg.get("containers", []):
            if not isinstance(container, dict) or "name" not in container:
                raise ValueError(f"blob.{acct_name}.containers items must have a 'name'")
            c_name = container["name"]
            if not re.match(r"^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$", c_name):
                raise ValueError(f"Invalid container name {c_name!r}")

    # Redis
    for r_name in resources.get("redis", {}).keys():
        validate_identifier(r_name, "redis instance")

    # Service Bus
    for ns_name, sb_cfg in resources.get("servicebus", {}).items():
        validate_identifier(ns_name, "servicebus namespace")
        if not isinstance(sb_cfg, dict):
            raise ValueError(f"servicebus.{ns_name} must be an object")


def discover_endpoints() -> dict[str, Any]:
    """Inspect running containers or environment to discover network and published endpoints (AE1)."""
    # 1. Simulator endpoint
    sim_pub_port = int(os.environ.get("VYOMI_SIMULATOR_PORT", "9000"))
    sim_net_host = os.environ.get("CLOUDLEARN_SIMULATOR_HOST", "simulator")

    # 2. Postgres endpoint
    from core import appliance_readiness as _ar
    canonical_pg_host = _ar._CANONICAL_ENV.get("postgres", "CLOUDLEARN_SQL_PG_HOST")
    pg_net_host = os.environ.get(canonical_pg_host, "cloudlearn-sql-postgres")
    pg_net_port = int(os.environ.get("CLOUDLEARN_SQL_PG_PORT", "5432"))
    pg_pub_port = int(os.environ.get("CLOUDLEARN_SQL_PG_PUBLIC_PORT",
                                     os.environ.get("VYOMI_APP_PG_PORT", "5432")))

    # 3. Redis endpoint
    redis_net_host = os.environ.get("CLOUDLEARN_REDIS_URL", "vyomi-redis")
    if "://" in redis_net_host:
        redis_net_host = urllib.parse.urlparse(redis_net_host).hostname or "vyomi-redis"
    redis_net_port = 6379
    redis_pub_port = int(os.environ.get("VYOMI_REDIS_PORT", "36379"))
    redis_pub_bind = os.environ.get("VYOMI_REDIS_BIND", "127.0.0.1")

    # Check if Docker client is available to detect dynamic port bindings
    try:
        from core import backend_provisioner as _bp
        if _bp.available():
            client = _bp._client()
            for c in client.containers.list():
                labels = getattr(c, "labels", {}) or {}
                svc = labels.get("com.docker.compose.service") or c.name
                ports = getattr(c, "ports", {}) or {}
                if "postgres" in svc and "5432/tcp" in ports and ports["5432/tcp"]:
                    pg_pub_port = int(ports["5432/tcp"][0].get("HostPort", pg_pub_port))
                if "redis" in svc and "6379/tcp" in ports and ports["6379/tcp"]:
                    redis_pub_port = int(ports["6379/tcp"][0].get("HostPort", redis_pub_port))
                if ("simulator" in svc or "cloudsim" in svc) and "9000/tcp" in ports and ports["9000/tcp"]:
                    sim_pub_port = int(ports["9000/tcp"][0].get("HostPort", sim_pub_port))
    except Exception:
        pass

    endpoints: dict[str, Any] = {
        "simulator": {
            "network": {"host": sim_net_host, "port": 9000},
            "published": {"host": "localhost", "port": sim_pub_port},
        },
        "postgres": {
            "network": {"host": pg_net_host, "port": pg_net_port},
            "published": {"host": "localhost", "port": pg_pub_port},
        },
    }

    # Only include redis if active or provisoned
    redis_running = False
    try:
        from core import appliance_readiness as _ar
        # From inside the simulator container, 127.0.0.1 is the simulator itself,
        # so probe Redis on the Docker network first; the published port covers
        # a simulator running directly on the host.
        redis_running = _ar._probe_one(redis_net_host, redis_net_port, timeout=0.25) or \
            _ar._probe_one("127.0.0.1", redis_pub_port, timeout=0.1)
    except Exception:
        pass

    endpoints["redis"] = {
        "network": {"host": redis_net_host, "port": redis_net_port},
        "published": {"host": redis_pub_bind, "port": redis_pub_port},
        "running": redis_running,
    }

    # Service Bus (if listener is wired)
    endpoints["servicebus"] = {
        "network": {"host": "servicebus", "port": 5672},
        "published": {"host": "localhost", "port": 5672},
        "available": True,
    }

    return endpoints


def provision_app_resources(app_name: str, resources: dict[str, Any],
                            store: app_state.AppStateStore | None = None) -> dict[str, Any]:
    """Execute resource creation for an app profile (AE3)."""
    validate_identifier(app_name, "app")
    validate_resources(resources)

    st = store or app_state.get_store()
    res_status: dict[str, Any] = {}

    # 1. Postgres resources
    pg_results: dict[str, Any] = {}
    for db_name, pg_cfg in resources.get("postgres", {}).items():
        user = pg_cfg.get("user", db_name)
        pwd = st.get_or_create_secret(app_name, f"pg_{user}_password")
        extensions = pg_cfg.get("extensions", [])
        settable_params = pg_cfg.get("settable_parameters", [])

        # Execute PostgreSQL DDL via admin connection
        try:
            from core import gcp_sql_engine as _eng
            cfg = _eng._engine_config("postgres")
            conn = _eng._pg_connect(cfg)
            try:
                cur = conn.cursor()
                # Check / create / update role
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (user,))
                if cur.fetchone():
                    # Synchronize role password to stored secret
                    cur.execute(f'ALTER ROLE "{user}" WITH LOGIN PASSWORD %s', (pwd,))
                else:
                    cur.execute(f'CREATE ROLE "{user}" WITH LOGIN PASSWORD %s', (pwd,))

                # Check / create database
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db_name,))
                if not cur.fetchone():
                    cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{user}"')
                cur.close()
            finally:
                conn.close()

            # Connect inside target database as admin to install extensions & grants
            db_cfg = dict(cfg)
            db_cfg["dbname"] = db_name
            import psycopg2
            target_conn = psycopg2.connect(
                host=db_cfg["host"], port=db_cfg["port"], user=db_cfg["admin_user"],
                password=db_cfg["admin_password"], dbname=db_name, connect_timeout=5,
            )
            target_conn.autocommit = True
            try:
                tcur = target_conn.cursor()
                for ext in extensions:
                    tcur.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
                for param in settable_params:
                    # Postgres 15+ syntax: GRANT SET ON PARAMETER <param> TO <user>
                    tcur.execute(f'GRANT SET ON PARAMETER {param} TO "{user}"')
                tcur.close()
            finally:
                target_conn.close()

            pg_results[db_name] = {
                "status": "ready",
                "database": db_name,
                "user": user,
                "extensions": extensions,
                "settable_parameters": settable_params,
            }
        except Exception as exc:
            log.warning("Postgres provision failed for %s: %s", db_name, exc)
            pg_results[db_name] = {"status": "error", "error": str(exc)}

    if pg_results:
        res_status["postgres"] = pg_results

    # 2. Blob resources
    blob_results: dict[str, Any] = {}
    for acct_name, blob_cfg in resources.get("blob", {}).items():
        containers = blob_cfg.get("containers", [])
        created_c: list[str] = []
        try:
            from core import azure_dataplane as _adp
            from core import azure_blob_store as _abs
            for c in containers:
                c_name = c["name"]
                public_access = c.get("public_access", "blob")
                if _abs and _abs.available():
                    _abs.ensure_container(_adp._sid(), acct_name)
                    # Record public access on the marker blob
                    _abs._client(_adp._sid(), acct_name, f"{c_name}/{_abs._MARKER}").upload_blob(
                        b"", overwrite=True, metadata={"public_access": public_access or ""}
                    )
                else:
                    _adp.create_container(acct_name, c_name)
                    acct = _adp._account(_adp._sid(), acct_name)
                    acct["containers"].setdefault(c_name, {})["public_access"] = public_access
                created_c.append(c_name)
            blob_results[acct_name] = {"status": "ready", "containers": created_c}
        except Exception as exc:
            log.warning("Blob provision failed for %s: %s", acct_name, exc)
            blob_results[acct_name] = {"status": "error", "error": str(exc)}

    if blob_results:
        res_status["blob"] = blob_results

    # 3. Redis resources
    if "redis" in resources:
        redis_results: dict[str, Any] = {}
        for r_name in resources["redis"].keys():
            try:
                from core import backend_provisioner as _bp
                if not _bp.available():
                    raise RuntimeError(
                        "backend provisioner unavailable (no Docker socket in the "
                        "simulator container); start Redis with the compose 'app' "
                        "profile or mount /var/run/docker.sock"
                    )
                _bp.provision_async("redis")
                # Wait (briefly: the CLI request times out at 30 s) for the real
                # outcome instead of reporting "ready" while the
                # image is still pulling (or after the pull failed).
                deadline = time.time() + float(os.environ.get("VYOMI_APP_REDIS_WAIT_S", "20"))
                st_r = _bp.status("redis") or {}
                while st_r.get("state") not in ("ready", "failed") and time.time() < deadline:
                    time.sleep(1)
                    st_r = _bp.status("redis") or {}
                if st_r.get("state") == "ready":
                    redis_results[r_name] = {"status": "ready"}
                elif st_r.get("state") == "failed":
                    raise RuntimeError(f"Redis failed to start: {st_r.get('error')}")
                else:
                    redis_results[r_name] = {"status": "pending", "state": st_r.get("state")}
            except Exception as exc:
                log.warning("Redis provision failed for %s: %s", r_name, exc)
                redis_results[r_name] = {"status": "error", "error": str(exc)}
        res_status["redis"] = redis_results

    # 4. Service Bus resources
    if "servicebus" in resources:
        sb_results: dict[str, Any] = {}
        for ns_name, sb_cfg in resources["servicebus"].items():
            topics = sb_cfg.get("topics", [])
            try:
                from core import azure_servicebus_core as _sbcore
                from core import azure_servicebus_runtime as _sbr
                st_sb = _sbr.get_store()
                for t in topics:
                    t_name = t["name"]
                    resp = _sbcore.dispatch(st_sb, "PUT", f"/{t_name}")
                    if resp.status >= 400:
                        raise RuntimeError(f"failed to create topic {t_name!r} (HTTP {resp.status})")
                    for sub in t.get("subscriptions", []):
                        sub_name = sub["name"]
                        sub_resp = _sbcore.dispatch(st_sb, "PUT", f"/{t_name}/subscriptions/{sub_name}")
                        if sub_resp.status >= 400:
                            raise RuntimeError(
                                f"failed to create subscription {sub_name!r} on topic {t_name!r} "
                                f"(HTTP {sub_resp.status})"
                            )
                st_sb.persist()
                sb_results[ns_name] = {"status": "ready"}
            except Exception as exc:
                log.warning("Service Bus provision failed for %s: %s", ns_name, exc)
                sb_results[ns_name] = {"status": "error", "error": str(exc)}
        res_status["servicebus"] = sb_results

    # Save state
    st.save_resources(app_name, resources)

    ok = not any(
        entry.get("status") == "error"
        for category in res_status.values()
        for entry in category.values()
    )

    return {
        "ok": ok,
        "app": app_name,
        "resources": res_status,
    }


def resolve_app_outputs(app_name: str, outputs: dict[str, Any],
                        target: str = "host",
                        endpoints: dict[str, Any] | None = None,
                        store: app_state.AppStateStore | None = None) -> dict[str, Any]:
    """Resolve outputs map of ${resource.name.field} expressions (AE4)."""
    if target not in ("host", "docker"):
        raise ValueError(f"Invalid target {target!r}: must be 'host' or 'docker'")

    st = store or app_state.get_store()
    eps = endpoints or discover_endpoints()
    resources = st.get_resources(app_name) or {}

    # Pool of available variables
    pool: dict[str, str] = {}
    warnings: list[str] = []

    # 1. Postgres variables
    pg_resources = resources.get("postgres", {})
    pg_host = eps["postgres"]["network"]["host"] if target == "docker" else eps["postgres"]["published"]["host"]
    pg_port = eps["postgres"]["network"]["port"] if target == "docker" else eps["postgres"]["published"]["port"]

    for db_name, pg_cfg in pg_resources.items():
        user = pg_cfg.get("user", db_name)
        pwd = st.get_or_create_secret(app_name, f"pg_{user}_password")
        encoded_pwd = urllib.parse.quote(pwd, safe="")
        pool[f"postgres.{db_name}.host"] = str(pg_host)
        pool[f"postgres.{db_name}.port"] = str(pg_port)
        pool[f"postgres.{db_name}.user"] = str(user)
        pool[f"postgres.{db_name}.password"] = str(pwd)
        pool[f"postgres.{db_name}.database"] = str(db_name)
        pool[f"postgres.{db_name}.url"] = f"postgresql://{user}:{encoded_pwd}@{pg_host}:{pg_port}/{db_name}"

    # 2. Blob variables
    blob_resources = resources.get("blob", {})
    sim_pub_port = eps["simulator"]["published"]["port"]

    for acct_name in blob_resources.keys():
        key = "cloudlearn-dummy-key"
        try:
            from core import azure_dataplane as _adp
            key = _adp.storage_keys(acct_name)["keys"][0]["value"]
        except Exception:
            key = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="

        # Target exception: browser loads blob URLs, so Docker target uses host.docker.internal
        if target == "docker":
            endpoint = f"http://host.docker.internal:{sim_pub_port}/azure-data/blob/{acct_name}"
        else:
            endpoint = f"http://localhost:{sim_pub_port}/azure-data/blob/{acct_name}"

        conn_str = (
            f"DefaultEndpointsProtocol=http;AccountName={acct_name};AccountKey={key};"
            f"BlobEndpoint={endpoint};"
        )
        pool[f"blob.{acct_name}.account"] = str(acct_name)
        pool[f"blob.{acct_name}.key"] = str(key)
        pool[f"blob.{acct_name}.endpoint"] = str(endpoint)
        pool[f"blob.{acct_name}.connection_string"] = str(conn_str)

    # 3. Redis variables
    redis_resources = resources.get("redis", {})
    redis_avail = eps.get("redis", {}).get("running", False)
    redis_pwd = os.environ.get("VYOMI_REDIS_PASSWORD", "")
    redis_host = eps["redis"]["network"]["host"] if target == "docker" else eps["redis"]["published"]["host"]
    redis_port = eps["redis"]["network"]["port"] if target == "docker" else eps["redis"]["published"]["port"]

    for r_name in redis_resources.keys():
        if not redis_avail:
            warnings.append(f"redis instance {r_name!r} is not yet available; skipping its fields")
            continue
        pool[f"redis.{r_name}.host"] = str(redis_host)
        pool[f"redis.{r_name}.port"] = str(redis_port)
        pool[f"redis.{r_name}.password"] = str(redis_pwd)
        if redis_pwd:
            encoded_redis_pwd = urllib.parse.quote(redis_pwd, safe="")
            pool[f"redis.{r_name}.url"] = f"redis://:{encoded_redis_pwd}@{redis_host}:{redis_port}/0"
        else:
            pool[f"redis.{r_name}.url"] = f"redis://{redis_host}:{redis_port}/0"

    # 4. Service Bus variables
    sb_resources = resources.get("servicebus", {})
    sb_avail = eps.get("servicebus", {}).get("available", False)
    sb_host = eps["servicebus"]["network"]["host"] if target == "docker" else eps["servicebus"]["published"]["host"]
    sb_port = eps["servicebus"]["network"]["port"] if target == "docker" else eps["servicebus"]["published"]["port"]

    for ns_name in sb_resources.keys():
        if sb_avail:
            conn_str = (
                f"Endpoint=sb://{sb_host}:{sb_port};SharedAccessKeyName=RootManageSharedAccessKey;"
                f"SharedAccessKey=dGVzdGtleQ==;UseDevelopmentEmulator=true;"
            )
            pool[f"servicebus.{ns_name}.connection_string"] = str(conn_str)
            pool[f"servicebus.{ns_name}.host"] = str(sb_host)
            pool[f"servicebus.{ns_name}.port"] = str(sb_port)
        else:
            warnings.append(f"servicebus namespace {ns_name!r} is not yet available; skipping its fields")

    # Resolve each file's key/value pairs
    resolved: dict[str, dict[str, str]] = {}

    for file_path, var_map in outputs.items():
        if not isinstance(var_map, dict):
            continue
        file_resolved: dict[str, str] = {}
        for var_name, expr in var_map.items():
            if not isinstance(expr, str):
                file_resolved[var_name] = str(expr)
                continue

            # Process $${ escapes (preserve as literal ${)
            placeholder = "___VYOMI_LITERAL_DOLLAR_BRACE___"
            escaped_expr = expr.replace("$${", placeholder)

            skip_key = False
            matches = _EXPR_PATTERN.findall(escaped_expr)

            for ref in matches:
                if ref.startswith("secret."):
                    secret_name = ref[len("secret."):]
                    val = st.get_or_create_secret(app_name, secret_name)
                    escaped_expr = escaped_expr.replace(f"${{{ref}}}", val)
                elif ref in pool:
                    escaped_expr = escaped_expr.replace(f"${{{ref}}}", pool[ref])
                elif ref.startswith("servicebus.") and not sb_avail:
                    skip_key = True
                    break
                elif ref.startswith("redis.") and not redis_avail:
                    skip_key = True
                    break
                else:
                    raise ValueError(
                        f"Unknown reference '${{{ref}}}' in output file '{file_path}' key '{var_name}'"
                    )

            if skip_key:
                continue

            # Restore escaped literal $${
            final_val = escaped_expr.replace(placeholder, "${")
            file_resolved[var_name] = final_val

        resolved[file_path] = file_resolved

    return {
        "ok": True,
        "app": app_name,
        "target": target,
        "resolved": resolved,
        "warnings": warnings,
    }
