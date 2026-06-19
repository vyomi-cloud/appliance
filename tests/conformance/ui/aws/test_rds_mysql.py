"""AWS RDS MySQL — UI conformance.

Same pattern as test_rds_postgres.py but for the MySQL engine. Asserts
real data-plane via pymysql/PyMySQL connection (skipped if the
appliance's MySQL backend isn't reachable from the host).
"""
from __future__ import annotations

import uuid

import pytest
import requests

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, list_resources, post_create, read_catalog_fields,
)

DB_ID = "uictest-rds-my-" + uuid.uuid4().hex[:8]
MASTER_USER = "vy_my_" + uuid.uuid4().hex[:6]
MASTER_PASS = "Vy0mi-UiTest-MyPw!"


def test_aws_rds_mysql_create_via_spa_contract(appliance_page, appliance_vm_ip):
    fields = read_catalog_fields("aws", "rds")
    assert fields, "Empty RDS wizard schema"

    body = build_spa_payload(fields, overrides={
        "name": DB_ID,
        "master_username": MASTER_USER,
        "master_password": MASTER_PASS,
        "engine": "mysql",
        "engine_version": "8.0",
    })
    created = post_create("/api/rds/databases", body, expect_status=(200,))
    assert created.get("db_instance_identifier") == DB_ID
    assert created.get("engine") == "mysql"

    listed = list_resources("/api/rds/databases")
    inst = next(
        (i for i in listed.get("db_instances", [])
         if i.get("db_instance_identifier") == DB_ID),
        None,
    )
    assert inst, f"Instance {DB_ID} missing from list"
    status = inst.get("db_instance_status") or inst.get("status")
    assert status == "available"

    # Data plane — pymysql only if backend is real
    if inst.get("runtime_backend") == "real-mysql":
        try:
            import pymysql
        except ImportError:
            pytest.skip("pymysql not installed; data-plane assert deferred")
        # v2.0.7 (#430): db + user are namespaced per space — connect with the
        # physical creds from the `connection` block, not the master_username.
        conn_info = inst.get("connection") or {}
        assert conn_info.get("user") and conn_info.get("database"), (
            f"RDS view is missing the physical `connection` block: {inst}"
        )
        db_name = conn_info["database"]
        conn_user = conn_info["user"]
        try:
            conn = pymysql.connect(
                host=appliance_vm_ip,
                port=conn_info.get("port", 3306),
                user=conn_user,
                password=conn_info.get("password", MASTER_PASS),
                database=db_name,
                connect_timeout=5,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT DATABASE(), CURRENT_USER()")
                    row = cur.fetchone()
                    assert row[0] == db_name
                    assert conn_user in str(row[1])
            finally:
                conn.close()
        except Exception as e:
            pytest.fail(f"MySQL connect failed: {e}")


def test_aws_rds_mysql_delete():
    resp = requests.delete(
        f"{BASE_URL}/api/rds/databases/{DB_ID}",
        params={"skip_final_snapshot": "true"},
        timeout=10,
    )
    assert resp.status_code in (200, 202, 204, 404)
