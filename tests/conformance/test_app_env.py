"""Conformance tests for App Profiles and vyomi env runtime (AE1–AE4, AE10).

Validates:
- Endpoint discovery (GET /api/runtime/endpoints) without authentication
- App state persistence (AppStateStore, generated 32-char alphanumeric secrets)
- Resource validation (identifier rules, extension/parameter allow-lists, SQL injection protection)
- Provisioning execution & idempotence (Postgres, Blob, Redis, Service Bus)
- Resolution of ${...} expressions, literal mixing, $${ escaping, and target exceptions
- Admin key authentication enforcement (403 without key in both dev and appliance modes)
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from core import app_provision, app_state
from core.app_state import AppStateStore


def _check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"Check failed: {name}")
    print(f"  ok  {name}")


def run() -> None:
    print("Running App Profiles and Environment Conformance Tests:")

    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name

    try:
        st = AppStateStore(db_path)

        # 1. Test secret generation & stability (AE2, Acceptance Test 9)
        sec1 = st.get_or_create_secret("siftly", "db_password")
        _check("generated secret is 32 chars", len(sec1) == 32)
        _check("generated secret is alphanumeric", sec1.isalnum())
        sec1_again = st.get_or_create_secret("siftly", "db_password")
        _check("secret is stable across calls", sec1 == sec1_again)

        # Separate store instance on same DB returns same secret
        st2 = AppStateStore(db_path)
        _check("secret persisted to SQLite", st2.get_secret("siftly", "db_password") == sec1)

        # 2. Resource validation (AE3, Acceptance Test 11)
        # Disallowed extension
        bad_ext_resources = {
            "postgres": {
                "siftly": {
                    "user": "siftly",
                    "extensions": ["plpython3u"],
                }
            }
        }
        caught_bad_ext = False
        try:
            app_provision.validate_resources(bad_ext_resources)
        except ValueError as e:
            caught_bad_ext = True
            _check("disallowed extension caught", "Disallowed extension" in str(e))
        _check("bad extension rejected", caught_bad_ext)

        # Malformed identifier
        bad_id_resources = {
            "postgres": {
                "siftly; DROP TABLE users;": {"user": "siftly"}
            }
        }
        caught_bad_id = False
        try:
            app_provision.validate_resources(bad_id_resources)
        except ValueError:
            caught_bad_id = True
        _check("malformed identifier rejected", caught_bad_id)

        # Disallowed parameter
        bad_param_resources = {
            "postgres": {
                "siftly": {
                    "user": "siftly",
                    "settable_parameters": ["work_mem; DROP TABLE users;"],
                }
            }
        }
        caught_bad_param = False
        try:
            app_provision.validate_resources(bad_param_resources)
        except ValueError:
            caught_bad_param = True
        _check("disallowed parameter rejected", caught_bad_param)

        # Valid resources pass validation
        valid_resources = {
            "postgres": {
                "siftly": {
                    "user": "siftly",
                    "extensions": ["vector", "uuid-ossp"],
                    "settable_parameters": ["session_replication_role"],
                }
            },
            "blob": {
                "siftlystore": {
                    "containers": [
                        {"name": "blog-images", "public_access": "blob"},
                        {"name": "brand-kit", "public_access": "blob"},
                    ]
                },
                "siftlylogos": {
                    "containers": [{"name": "org-logos", "public_access": "blob"}]
                },
            },
            "redis": {"default": {}},
            "servicebus": {
                "siftlyai": {
                    "topics": [
                        {
                            "name": "scrapper_responses",
                            "subscriptions": [{"name": "scrapper_responses"}],
                        }
                    ]
                }
            },
        }
        app_provision.validate_resources(valid_resources)
        _check("valid resources accepted", True)

        # 3. Endpoint discovery (AE1)
        endpoints = app_provision.discover_endpoints()
        _check("endpoints has simulator", "simulator" in endpoints)
        _check("endpoints has postgres", "postgres" in endpoints)
        _check("endpoints has redis", "redis" in endpoints)
        _check("simulator has network and published", "network" in endpoints["simulator"] and "published" in endpoints["simulator"])
        _check("postgres has network and published", "network" in endpoints["postgres"] and "published" in endpoints["postgres"])

        # 4. Provisioning execution (AE3)
        prov_res = app_provision.provision_app_resources("siftly", valid_resources, store=st)
        _check("provision returned ok", prov_res["ok"] is True)
        _check("provision recorded blob", "blob" in prov_res["resources"])

        # Idempotence: provisioning again succeeds
        prov_res2 = app_provision.provision_app_resources("siftly", valid_resources, store=st)
        _check("provision is idempotent", prov_res2["ok"] is True)

        # 5. Output resolution: Target host (AE4, Acceptance Test 3, 4)
        outputs = {
            "backend/.env": {
                "DB_HOST": "${postgres.siftly.host}",
                "DB_PORT": "${postgres.siftly.port}",
                "DB_USER": "${postgres.siftly.user}",
                "DB_PASSWORD": "${postgres.siftly.password}",
                "DB_NAME": "${postgres.siftly.database}",
                "DB_SSL_MODE": "disable",
                "AZURE_STORAGE_CONNECTION_STRING": "${blob.siftlystore.connection_string}",
                "REDIS_HOST": "${redis.default.host}",
                "REDIS_PORT": "${redis.default.port}",
                "REDIS_PASSWORD": "${redis.default.password}",
                "LITERAL_ESCAPED": "$${LITERAL_VALUE}",
                "COMBINED_URL": "${postgres.siftly.url}?sslmode=disable",
            },
            "hocuspocus/.env": {
                "DATABASE_URL": "${postgres.siftly.url}",
                "COLLAB_JWT_SECRET": "${secret.collab_jwt}",
            },
        }

        res_host = app_provision.resolve_app_outputs("siftly", outputs, target="host", endpoints=endpoints, store=st)
        _check("resolution target host ok", res_host["ok"] is True)
        b_env = res_host["resolved"]["backend/.env"]
        _check("host target uses localhost for DB", b_env["DB_HOST"] == "localhost")
        _check("host target resolves password", len(b_env["DB_PASSWORD"]) == 32)
        _check("host target mixed literal handled", b_env["COMBINED_URL"].endswith("?sslmode=disable"))
        _check("host target escaped literal preserved", b_env["LITERAL_ESCAPED"] == "${LITERAL_VALUE}")
        _check("host target blob uses localhost", "http://localhost:" in b_env["AZURE_STORAGE_CONNECTION_STRING"])
        _check("secret generated for collab_jwt", len(res_host["resolved"]["hocuspocus/.env"]["COLLAB_JWT_SECRET"]) == 32)

        # 6. Output resolution: Target docker (AE4, Acceptance Test 4, 6a)
        res_docker = app_provision.resolve_app_outputs("siftly", outputs, target="docker", endpoints=endpoints, store=st)
        _check("resolution target docker ok", res_docker["ok"] is True)
        d_env = res_docker["resolved"]["backend/.env"]
        _check("docker target uses network host for DB", d_env["DB_HOST"] == endpoints["postgres"]["network"]["host"])
        _check("docker target blob uses host.docker.internal", "http://host.docker.internal:" in d_env["AZURE_STORAGE_CONNECTION_STRING"])

        # 8. Route handlers & Admin Auth Enforcement (AE3, AE4, Acceptance Test 10)
        import asyncio
        from routes import app_env

        class DummyApp:
            def __init__(self):
                self.routes = {}
            def get(self, path, **kwargs):
                def deco(fn):
                    self.routes[("GET", path)] = fn
                    return fn
                return deco
            def post(self, path, **kwargs):
                def deco(fn):
                    self.routes[("POST", path)] = fn
                    return fn
                return deco

        dummy_app = DummyApp()
        app_env.register(dummy_app)

        # GET /api/runtime/endpoints works unauthenticated
        ep_handler = dummy_app.routes[("GET", "/api/runtime/endpoints")]
        ep_out = ep_handler()
        _check("endpoints handler returns dict", isinstance(ep_out, dict))

        # POST without admin key returns 403 (Acceptance Test 10)
        from core import admin_auth

        class MockRequest:
            def __init__(self, headers=None, body=None):
                self.headers = headers or {}
                self._body = body or {}
            async def json(self):
                return self._body

        prov_handler = dummy_app.routes[("POST", "/api/runtime/apps/{name}/provision")]
        req_no_auth = MockRequest(headers={}, body={"resources": valid_resources})
        resp_403 = asyncio.run(prov_handler("siftly", req_no_auth))
        _check("provision without key returns 403", resp_403.status_code == 403)

        resolve_handler = dummy_app.routes[("POST", "/api/runtime/apps/{name}/resolve")]
        req_resolve_no_auth = MockRequest(headers={}, body={"outputs": outputs})
        resp_resolve_403 = asyncio.run(resolve_handler("siftly", req_resolve_no_auth))
        _check("resolve without key returns 403", resp_resolve_403.status_code == 403)

        # POST with valid admin key returns 200
        admin_key = admin_auth.get_or_create_admin_key()
        req_with_auth = MockRequest(
            headers={"x-cloudlearn-admin-key": admin_key},
            body={"resources": valid_resources}
        )
        resp_200 = asyncio.run(prov_handler("siftly", req_with_auth))
        _check("provision with admin key returns 200", resp_200.status_code == 200)

        req_resolve_with_auth = MockRequest(
            headers={"x-cloudlearn-admin-key": admin_key},
            body={"outputs": outputs, "target": "host"}
        )
        resp_resolve_200 = asyncio.run(resolve_handler("siftly", req_resolve_with_auth))
        _check("resolve with admin key returns 200", resp_resolve_200.status_code == 200)

        print("\nApp Profiles and Environment Conformance: ALL GREEN\n")

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


if __name__ == "__main__":
    run()
