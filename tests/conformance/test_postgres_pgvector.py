"""PG5 — Conformance tests for Postgres 16 Alpine with pgvector and vyomi db CLI.

Validates acceptance criteria from docs/specs/postgres-pgvector-siftly-spec.md:
1. Postgres 16 server runs with pgvector extension available.
2. Extension can be installed per-database; version >= 0.7.0.
3. vector and halfvec types and operators work correctly.
4. Database 'postgres' does not have extension installed by default.
5. `vyomi db dump`, `vyomi db restore` (--dry-run and live), and `vyomi db refresh` work end-to-end.
6. Dump cleaner strips PG17/Azure statements and logs them.
"""

import os
import subprocess
import tempfile
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DSN_POSTGRES = os.environ.get(
    "VYOMI_POSTGRES_DSN",
    "host=localhost port=35432 user=postgres password=cloudlearn dbname=postgres",
)
TEST_DB = "siftly_pgvector_test"
VYOMI_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cmd", "vyomi", "vyomi"))


def _check(name: str, cond: bool):
    if not cond:
        raise AssertionError(f"Check failed: {name}")
    print(f"  ok  {name}")


def _get_conn(dbname="postgres"):
    conn = psycopg2.connect(
        host="localhost",
        port=35432,
        user="postgres",
        password="cloudlearn",
        dbname=dbname,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def run():
    print("Starting Postgres pgvector Conformance Test Suite (PG5):")

    # 1. Check default 'postgres' database does not have vector installed
    root_conn = _get_conn("postgres")
    with root_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'vector';")
        has_vector_in_root = cur.fetchone()[0]
        _check("database 'postgres' does NOT have vector installed by default", has_vector_in_root == 0)

        # Drop and create test database
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}";')
        cur.execute(f'CREATE DATABASE "{TEST_DB}";')

    test_conn = _get_conn(TEST_DB)
    with test_conn.cursor() as cur:
        # 2. Extension installation and version check
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
        row = cur.fetchone()
        _check("vector extension created successfully", row is not None)
        version_str = row[0]
        major, minor = [int(p) for p in version_str.split(".")[:2]]
        _check(f"vector version >= 0.7.0 (got {version_str})", (major > 0) or (major == 0 and minor >= 7))

        # Check uuid-ossp as required by Siftly migrations
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        cur.execute('SELECT extversion FROM pg_extension WHERE extname = \'uuid-ossp\';')
        _check("uuid-ossp extension created successfully", cur.fetchone() is not None)

        # 3. Test vector and halfvec table, insert, and vector distance operators
        cur.execute("""
            CREATE TABLE test_embeddings (
                id SERIAL PRIMARY KEY,
                vec vector(3),
                hvec halfvec(3)
            );
        """)
        cur.execute("""
            INSERT INTO test_embeddings (vec, hvec) VALUES
            ('[1, 2, 3]', '[1, 2, 3]'),
            ('[4, 5, 6]', '[4, 5, 6]'),
            ('[1, 2, 4]', '[1, 2, 4]');
        """)
        cur.execute("SELECT count(*) FROM test_embeddings;")
        _check("inserted 3 vector rows", cur.fetchone()[0] == 3)

        # L2 distance operator (<->)
        cur.execute("SELECT id FROM test_embeddings ORDER BY vec <-> '[1, 2, 3]' LIMIT 1;")
        closest_id = cur.fetchone()[0]
        _check("vector L2 distance operator (<->) nearest neighbor matches", closest_id == 1)

        # Halfvec distance
        cur.execute("SELECT id FROM test_embeddings ORDER BY hvec <-> '[1, 2, 4]' LIMIT 1;")
        closest_halfvec = cur.fetchone()[0]
        _check("halfvec distance operator works", closest_halfvec == 3)

        # Create dependent materialized views (mv_parent and mv_child) for refresh ordering testing
        cur.execute("""
            CREATE MATERIALIZED VIEW mv_parent AS
            SELECT id, vec FROM test_embeddings;
            CREATE MATERIALIZED VIEW mv_child AS
            SELECT id FROM mv_parent;
        """)
        cur.execute("SELECT count(*) FROM mv_parent;")
        _check("parent materialized view created and populated", cur.fetchone()[0] == 3)
        cur.execute("SELECT count(*) FROM mv_child;")
        _check("child materialized view created and populated", cur.fetchone()[0] == 3)

    # 4. Test vyomi db dump
    with tempfile.TemporaryDirectory() as tmpdir:
        dump_path = os.path.join(tmpdir, "test-dump.sql")
        dump_cmd = [VYOMI_BIN, "db", "dump", "--db", TEST_DB, "--file", dump_path]
        res = subprocess.run(dump_cmd, capture_output=True, text=True)
        _check("vyomi db dump command exited 0", res.returncode == 0)
        _check("dump file was written to host", os.path.isfile(dump_path) and os.path.getsize(dump_path) > 0)

        # 5. Test vyomi db restore with Azure / PG17 syntax injection
        with open(dump_path, "r", encoding="utf-8") as f:
            dump_content = f.read()

        # Inject PG17 and Azure-specific constructs into dump
        injected_dump = f"""
SET transaction_timeout = 0;
CREATE SCHEMA public;
COMMENT ON SCHEMA public IS 'public schema';
ALTER SCHEMA public OWNER TO azure_pg_admin;
GRANT ALL ON SCHEMA public TO azure_pg_admin;
GRANT MAINTAIN ON TABLE test_embeddings TO azure_pg_admin;
{dump_content}
"""
        injected_path = os.path.join(tmpdir, "injected-dump.sql")
        with open(injected_path, "w", encoding="utf-8") as f:
            f.write(injected_dump)

        # 5a. Test --dry-run
        dry_cmd = [VYOMI_BIN, "db", "restore", "--db", TEST_DB, "--user", "postgres", "--file", injected_path, "--dry-run"]
        res_dry = subprocess.run(dry_cmd, capture_output=True, text=True)
        _check("vyomi db restore --dry-run exited 0", res_dry.returncode == 0)
        _check("dry-run reported success", "Dry-run restore succeeded" in res_dry.stdout)
        _check("cleaning log was created", os.path.isfile(injected_path + ".clean.log"))

        with open(injected_path + ".clean.log", "r", encoding="utf-8") as lf:
            log_data = lf.read()
            _check("cleaning log recorded transaction_timeout removal", "transaction_timeout" in log_data)
            _check("cleaning log recorded azure role removal", "azure" in log_data.lower())
            _check("cleaning log recorded MAINTAIN removal", "MAINTAIN" in log_data)

        # 5b. Live restore into a fresh restore database
        RESTORE_DB = "siftly_restore_test"
        with root_conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{RESTORE_DB}";')
            cur.execute(f'CREATE DATABASE "{RESTORE_DB}";')

        # Target database needs required extensions pre-installed (per R4 / profile provision)
        rest_conn = _get_conn(RESTORE_DB)
        with rest_conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

        restore_cmd = [VYOMI_BIN, "db", "restore", "--db", RESTORE_DB, "--user", "postgres", "--file", injected_path]
        res_restore = subprocess.run(restore_cmd, capture_output=True, text=True)
        _check("vyomi db restore live exited 0", res_restore.returncode == 0)
        _check("restore reported success", "restored successfully" in res_restore.stdout)

        # Verify data and views in restored database
        with rest_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM test_embeddings;")
            _check("restored table contains 3 vector rows", cur.fetchone()[0] == 3)
            cur.execute("SELECT count(*) FROM mv_parent;")
            _check("restored parent view populated", cur.fetchone()[0] == 3)
            cur.execute("SELECT count(*) FROM mv_child;")
            _check("restored child view populated", cur.fetchone()[0] == 3)

        # 6. Test vyomi db refresh (refreshes dependent views in two passes)
        refresh_cmd = [VYOMI_BIN, "db", "refresh", "--db", RESTORE_DB]
        res_refresh = subprocess.run(refresh_cmd, capture_output=True, text=True)
        _check("vyomi db refresh exited 0", res_refresh.returncode == 0)
        _check("refresh reported success", "refreshed successfully" in res_refresh.stdout)

        # Cleanup restore DB
        rest_conn.close()
        with root_conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{RESTORE_DB}";')

    # Cleanup test DB
    test_conn.close()
    with root_conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}";')

    print("\nPostgres pgvector Conformance (PG1-PG5): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
