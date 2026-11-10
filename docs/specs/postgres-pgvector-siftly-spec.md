---
title: pgvector on Vyomi's Postgres for Siftly — spec
status: draft (revision 4 — aligned with app profiles; second self-review applied)
updated: 2026-10-18
owner: Rohith
repo: ~/Documents/appliance (Vyomi v3.0.6)
related:
  - siftly-integration-gaps.md (row 5)
  - storage-cache-siftly-implementation-plan.md (PG1–PG5)
  - app-env-spec.md (creates the database, role and extension; writes the env values)
---

# pgvector on Vyomi's Postgres for Siftly — spec

**Goal:** Siftly's backend, Hocuspocus and content engine use Vyomi's **existing** Postgres server, with the pgvector extension available, in a dedicated `siftly` database. No second server, no version change, no data migration.

**Scope split.**
- **This spec** covers: the image change, loading Siftly's schema, and refreshing it after a data load.
- **The app profile (`app-env-spec.md`)** covers: creating the `siftly` role, database, extension and permission (`vyomi app provision`), and writing the connection values (`vyomi env --app`).

**Effort:** about 3.5 days solo, about 2 days with Claude, for PG1–PG5 in the implementation plan. Provisioning and env work are counted in the app-profile plan.

## 1. Decision

Vyomi keeps **one** Postgres server, still major version **16**, on the same Alpine base. Its image changes from `postgres:16-alpine` to `vyomi/postgres:16-alpine-pgvector`, which is the same image with pgvector compiled in.

- **Why not a second server:** two servers mean extra memory, a port clash with Siftly's own dev Postgres on 5433, readiness-gauge work and more to operate.
- **Why not upgrade to 17:** an existing Postgres 16 data directory does not start under 17, so every install would need a migration. Siftly's code uses no 17-only SQL: there is no `JSON_TABLE` or SQL `MERGE`.
- **Why the same Alpine base:** switching to a Debian-based image while reusing the data directory changes text-collation rules and can silently break existing text indexes.
- **pgvector on 16:** supported. `halfvec`, which Siftly uses, needs pgvector 0.7.0 or later.

Upgrading Vyomi's Postgres to 17 is a separate, later decision, with its own migration.

## 2. What Siftly needs

- **Extension:** `vector`, for the `halfvec` `embedding` column on `brand_facts`. Siftly's migrations also run `CREATE EXTENSION IF NOT EXISTS vector`, which is a no-op once the extension exists.
- **Schema:** loaded from a production schema dump made by Postgres **17** (Azure). Restoring into 16 as a non-superuser needs Azure-only, 17-only and ownership statements removed (R4).
- **Data:** a scoped subset loaded with Siftly's own loader (`scoped_data_load.py` in its local-dev guide), which runs `SET session_replication_role = replica`. After loading: refresh materialized views twice and reset sequences (Siftly's guide §8).
- **Connections:** backend `DB_*` and `DB_SSL_MODE=disable`; Hocuspocus `DATABASE_URL`; content engine `DB_*`. Written by `vyomi env --app siftly`.

## 3. What Vyomi has today

- **One server, in several compose files:**
  - `docker-compose.yml`: `vyomi-sql-postgres`
  - `docker-compose.cloudlite.yml`: `vyomi-sql-postgres`
  - `docker-compose.appliance.yml` (the Go CLI's default): `cloudlearn-sql-postgres`
  - `codespace/.devcontainer/docker-compose.sandbox.yml`

  It runs image `postgres:16-alpine` on container port 5432 (host 5432, or 35432 with `docker-compose.override.yml`). It has no `profiles:`, so it always starts. `vyomi up` runs compose with `--force-recreate`, so an image change takes effect on the next `vyomi up`.
- **Users:** Cloud SQL (`core/gcp_sql_engine.py`, `CLOUDLEARN_SQL_PG_*`, admin user `postgres`); RDS; Azure Database for PostgreSQL and Azure SQL data planes (`routes/console.py`); `postgres_backed_store.py`.
- **Readiness:** `core/appliance_readiness.py` lists `postgres` as a core backend.
- **Snapshots** (`core/console_snapshots.py`) capture in-process control-plane state only, not Postgres data.
- **Existing drift, not changed here:** the Helm air-gapped manifest (`core/helm_chart.py`) lists `postgres:15-alpine`.

## 4. Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| R1 | Image `vyomi/postgres:16-alpine-pgvector`: `FROM postgres:16-alpine` (pinned digest); pgvector from a pinned tag (≥ 0.7.0) built with `make OPTFLAGS="" with_llvm=no` (portable across CPUs; no JIT bitcode, so only `git build-base` are needed); build packages removed afterwards. Built for `linux/amd64` and `linux/arm64` in CI and pushed to Docker Hub | Must |
| R2 | Every compose file in section 3 switches to `${VYOMI_POSTGRES_IMAGE:-vyomi/postgres:16-alpine-pgvector}`, so one variable rolls it back. Any offline image list used by Docker installs (check `scripts/verify-bundle.sh`) includes the new image | Must |
| R3 | **Provisioning is done by the app profile**, not by this spec: `vyomi app provision --app siftly` creates role `siftly` (password stored by the appliance), database `siftly` owned by it, the extensions Siftly needs installed as admin in that database (`vector`, and `uuid-ossp`, because migration `add_visibility_score_table` uses `uuid_generate_v4()`; `gen_random_uuid()` is built in since Postgres 13 and needs no extension), and `SET ON PARAMETER session_replication_role` granted (see `app-env-spec.md` §6). This spec only relies on that state | Must (dependency) |
| R4 | `vyomi db restore --app siftly --db siftly --file <dump.sql>` cleans the dump, then restores it. **Removed:** every `CREATE EXTENSION` and `COMMENT ON EXTENSION` (`vector` already exists; `azure`, `pg_cron`, `pgaadauth` do not; commenting on an extension needs its owner); every `ALTER … OWNER TO` (so **every restored object is owned by the restoring role `siftly`**, which is intended); `GRANT`, `REVOKE` and `ALTER DEFAULT PRIVILEGES` that name Azure roles (`azure_pg_admin`, `azuresu`, `azure_superuser` and other `azure*` roles); `CREATE SCHEMA public` and `COMMENT ON SCHEMA public`; 17-only syntax known so far: `SET transaction_timeout` and the `MAINTAIN` privilege in `GRANT`/`REVOKE`. The pattern list is data, so new findings are one-line additions. **Extension check:** before restoring, the cleaner lists the extensions the dump creates and checks each exists in database `siftly`; a missing one stops the restore with "add `<name>` to the profile's `extensions` and run `vyomi app provision`", instead of failing later on a type or function. **Restore:** as role `siftly` into database `siftly`, with `psql -v ON_ERROR_STOP=1`, run inside the Postgres container over its local socket, so any remaining error stops the restore and is reported with its line. The removed lines go to a log. `--dry-run` restores into a temporary scratch database and drops it, to find unknown statements first | Must |
| R5 | `vyomi db refresh --app siftly --db siftly` refreshes all materialized views (two passes, for inter-view dependencies) and resets every sequence to the maximum of its column. Run **after** the data load, not after the schema restore | Must |
| R6 | `vyomi db dump --app siftly --db siftly` exports with `pg_dump` inside the container. Volume-level snapshots stay out of scope until the general snapshot work (gaps row 14) | Should |
| R7 | All `vyomi db` commands work on both substrates: `docker exec` on Docker, `multipass exec` into the VM then `docker exec` on Multipass. No `psql` needed on the host. **Files, not pipes, across the VM boundary:** dumps can be tens of MB, and streaming them through `multipass exec` stdin is fragile, so the CLI cleans the dump into a local temporary file, `multipass transfer`s it into the VM (as `syncWorkspaceIntoVm` already does), `docker cp`s it into the Postgres container, and runs `psql -f` there; `db dump` reverses this. On Docker, `docker cp` then `psql -f` too, so both substrates share one path. The container is found by compose service, not a fixed name, because the names differ: `vyomi-sql-postgres` in `docker-compose.yml`, `cloudlearn-sql-postgres` in `docker-compose.appliance.yml` (the CLI's default) | Must |
| R8 | No change to the server's version, ports, admin credentials, volume or readiness entry | Must |

## 5. Regression safety

| Risk | Guard |
| --- | --- |
| Existing data fails to start | Same major version and same Alpine base, so the data directory is unchanged. Tested by starting the new image on a copied volume holding Cloud SQL, RDS and Azure SQL databases |
| pgvector build fails on one architecture | CI builds both before the compose change merges. Fallback: `pgvector/pgvector:pg16`, with a documented `REINDEX` for the collation change |
| Bad image released | `VYOMI_POSTGRES_IMAGE=postgres:16-alpine` rolls back. Vyomi's own databases are unaffected; the `siftly` database stays intact on disk but its `vector` columns cannot be used until the pgvector image is back |
| Siftly objects collide with Vyomi's | Separate `siftly` database and role; objects owned by `siftly` |
| Offline Docker installs cannot pull the new image | R2 adds it to the offline image list |
| Image size | pgvector adds a few MB on the same base image |

## 6. Acceptance tests

1. **Upgrade in place:** an install with existing Postgres 16 data (Cloud SQL, RDS and Azure SQL databases with rows) starts on the new image after `vyomi up`; row counts match; the existing Cloud SQL, RDS and Azure SQL conformance checks pass.
2. **Extension:** after `vyomi app provision --app siftly`, in database `siftly`, `SELECT extversion FROM pg_extension WHERE extname='vector'` returns ≥ 0.7.0, `uuid-ossp` is installed, and `CREATE TABLE t (e halfvec(3)); INSERT INTO t VALUES ('[1,2,3]');` succeeds as role `siftly`. In database `postgres`, `vector` is **not** installed.
3. **Restore:** Siftly's real schema dump restores as role `siftly` with `ON_ERROR_STOP=1`; the cleaning log lists only expected statements; every table, view and sequence in `siftly` is owned by `siftly`; `alembic stamp` then `alembic current` match; Siftly's `CREATE EXTENSION IF NOT EXISTS vector` migrations pass as `siftly`.
4. **Unknown statement:** a dump with an unsupported statement stops the restore and reports the line; a dump that creates an extension not in the profile stops before any SQL runs; `--dry-run` finds it without touching database `siftly`.
5. **Data load and refresh:** as role `siftly`, `SET session_replication_role = replica` succeeds; after Siftly's loader runs, `vyomi db refresh` completes and `nextval` on each sequence exceeds the column maximum.
6. **App:** Siftly's backend starts with the env from `vyomi env --app siftly` and serves an authenticated dashboard request; Hocuspocus connects with `DATABASE_URL`.
7. **Both architectures and substrates:** tests 1–3 pass on amd64 and arm64, and on the Docker and Multipass substrates.
8. **Rollback:** `VYOMI_POSTGRES_IMAGE=postgres:16-alpine vyomi up` starts the server with Vyomi's existing data intact.

## 7. Open checks

- [ ] Run R4 `--dry-run` against Siftly's real schema dump once, early, to list any other 17-only or Azure-only statements before PG4 is finished.
- [ ] Confirm the official image's local-socket authentication lets `psql -U siftly` connect inside the container without a password (expected: trust on the local socket). If not, pass the stored password with `docker exec -e PGPASSWORD=…`.

## 8. Out of scope

Upgrading to Postgres 17, the Helm chart's `postgres:15-alpine`, volume-level snapshots, `pg_cron`, Entra ID authentication, read replicas.

## 9. Review log

| Date | Finding | Change |
| --- | --- | --- |
| 2026-10-18 | Second server, migration and ports | One server on 16 with pgvector (revision 2) |
| 2026-10-18 | Restore as a non-superuser fails on ownership and extension statements; loader needs `session_replication_role` | Cleaner and grant (revision 3) |
| 2026-10-18 | `vyomi db create` and `vyomi env --map` superseded by app profiles | R3 now depends on `vyomi app provision`; env via `vyomi env --app` |
| 2026-10-18 | Refresh and sequence reset ran after the schema restore, before any data | Separate `vyomi db refresh` after the data load (R5) |
| 2026-10-18 | Ownership outcome unstated | R4 states every object is owned by `siftly`; test 3 checks it |
| 2026-10-18 | More 17-only and Azure statements likely | `MAINTAIN` privilege, `ALTER DEFAULT PRIVILEGES` for Azure roles, `public` schema statements added; `--dry-run` and an early check against the real dump |
| 2026-10-18 | `db` commands assumed the Docker substrate | R7 covers Multipass |
| 2026-10-18 | Rollback left the `siftly` database's state unclear | Stated in regression table |
| 2026-10-18 | Offline Docker installs could lack the new image | Added to R2 |
| 2026-10-18 | Container name differs between compose files | R7 finds the container by compose service |
| 2026-10-18 | External review: stripping `CREATE EXTENSION` breaks objects that use other extensions | Siftly needs `uuid-ossp` as well as `vector` (checked: `pgcrypto`, `citext`, `pg_trgm` are not used); pre-restore extension check |
| 2026-10-18 | External review: piping large dumps through `multipass exec` | Transfer as a file, `docker cp`, `psql -f` (the review's `psql -f /tmp/restore.sql` would read the container's `/tmp`, not the VM's, so `docker cp` is added) |
