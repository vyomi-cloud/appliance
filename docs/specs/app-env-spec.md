---
title: App profiles and `vyomi env --app` — spec
status: draft (revision 3 — aligned with the revised storage specs; second self-review applied)
updated: 2026-10-18
owner: Rohith
repo: ~/Documents/appliance (Vyomi v3.0.6)
related:
  - app-env-implementation-plan.md
  - storage-cache-siftly-implementation-plan.md (replaces EN1; absorbs PG3 provisioning)
  - servicebus-siftly-implementation-plan.md (replaces the A5 entities file; B7 env step)
  - siftly-integration-gaps.md (rows 12, 13)
---

# App profiles and `vyomi env --app` — spec

**Goal:** one command connects an existing application to Vyomi. The app describes, in a file in its own repo, which cloud resources it needs and which environment variables it reads. Vyomi creates the resources and writes the variables into the app's `.env` files. Vyomi itself contains no application names.

```text
vyomi app add ~/code/siftly          # register the app (reads ~/code/siftly/.vyomi/app.json)
vyomi app provision --app siftly     # create its databases, containers, queues, caches
vyomi env --app siftly               # write connection settings into its .env files
```

**Effort:** about 11 days solo, about 6.5 days with Claude (see `app-env-implementation-plan.md`).

## 1. Why

- **Nothing does this today.** Vyomi's CLI (`cmd/vyomi`, Go) has only `up`, `down`, `stop`, `restart`, `status`/`ps`, `logs`, `update`, `doctor`, `help`. `core/env_aliases.py` only mirrors `CLOUDLEARN_*` ↔ `VYOMI_*`.
- **Siftly onboarding needs about 45 values** spread over `backend/.env`, `hocuspocus/.env` and `siftly-agents-2/.env`, plus resources created in the right order: a Postgres database with pgvector, blob containers, Service Bus topic/subscription pairs, Redis.
- **The earlier plans each invented a piece:** `vyomi env --app siftly`, `vyomi db create`, a Service Bus entities file. This spec replaces them with one model.

## 2. Goals and non-goals

**Goals**

- An app profile, kept in the app's repo, declares the resources and the variable mapping.
- `vyomi app provision` creates the resources idempotently.
- `vyomi env` writes values into dotenv files, changing only the keys it owns.
- The same profile works on macOS, Linux and Windows, and on the Docker and Multipass substrates.
- Generated secrets never go into the app's repo.
- A check mode lets CI fail when an app's `.env` is out of date.

**Non-goals**

- Running the app's own processes. That stays with the app's tooling.
- Secret managers such as Key Vault. They are a later output type.
- Templating whole config files. Only dotenv key/value files are written.
- Kubernetes manifests and Helm values.

## 3. Concepts

| Term | Meaning |
| --- | --- |
| **App profile** | `.vyomi/app.json` in the app's repo: `name`, `resources`, `outputs` |
| **Resource** | Something Vyomi creates for the app: a Postgres database, blob account/containers, a Redis instance, Service Bus namespace/entities |
| **Output** | A dotenv file path, relative to the repo, and a map of variable name → value expression |
| **Value expression** | A string that may mix literal text and `${resource.name.field}` / `${secret.name}` references, for example `"${postgres.siftly.url}?sslmode=disable"`. `$${` writes a literal `${` |
| **App registry** | `~/.vyomi/apps.json`: app name → absolute repo path. `--app <name>` looks it up; with no `--app`, the current directory's `.vyomi/app.json` is used |
| **Target** | `host` (default): addresses an app on the developer's machine uses. `docker`: addresses an app container on the Vyomi Docker network uses |

## 4. App profile format

JSON is used because the Go CLI is standard-library only and the appliance has no YAML parser.

```json
{
  "version": 1,
  "name": "siftly",
  "resources": {
    "postgres": {
      "siftly": { "user": "siftly", "extensions": ["vector", "uuid-ossp"],
                  "settable_parameters": ["session_replication_role"] }
    },
    "blob": {
      "siftlystore": { "containers": [
        { "name": "blog-images", "public_access": "blob" },
        { "name": "brand-kit",   "public_access": "blob" } ] },
      "siftlylogos": { "containers": [ { "name": "org-logos", "public_access": "blob" } ] }
    },
    "redis": { "default": {} },
    "servicebus": {
      "siftlyai": { "topics": [
        { "name": "scrapper_responses",
          "subscriptions": [ { "name": "scrapper_responses", "lock_duration": "PT60S", "max_delivery_count": 10 } ] } ] }
    }
  },
  "outputs": {
    "backend/.env": {
      "DB_HOST": "${postgres.siftly.host}",
      "DB_PORT": "${postgres.siftly.port}",
      "DB_USER": "${postgres.siftly.user}",
      "DB_PASSWORD": "${postgres.siftly.password}",
      "DB_NAME": "${postgres.siftly.database}",
      "DB_SSL_MODE": "disable",
      "AZURE_STORAGE_CONNECTION_STRING": "${blob.siftlystore.connection_string}",
      "AZURE_ORG_LOGO_CONNECTION_STRING": "${blob.siftlylogos.connection_string}",
      "REDIS_HOST": "${redis.default.host}",
      "REDIS_PORT": "${redis.default.port}",
      "REDIS_PASSWORD": "${redis.default.password}",
      "REDIS_DB": "0",
      "REDIS_SSL_ENABLED": "false",
      "AZURE_SERVICEBUS_CONNECTION_STRING": "${servicebus.siftlyai.connection_string}"
    },
    "hocuspocus/.env": {
      "DATABASE_URL": "${postgres.siftly.url}",
      "COLLAB_JWT_SECRET": "${secret.collab_jwt}"
    },
    "siftly-agents-2/.env": {
      "DB_HOST": "${postgres.siftly.host}", "DB_PORT": "${postgres.siftly.port}",
      "REDIS_URL": "${redis.default.url}", "REDIS_SSL_ENABLED": "false"
    }
  }
}
```

The container names above are illustrative; the real list comes from Siftly's `AZURE_*_CONTAINER` variables.

### Fields available to expressions

| Resource | Fields |
| --- | --- |
| `postgres.<db>` | `host`, `port`, `user`, `password`, `database`, `url` (`postgresql://user:pass@host:port/db`) |
| `blob.<account>` | `account`, `key`, `endpoint`, `connection_string` (`DefaultEndpointsProtocol=http;AccountName=…;AccountKey=…;BlobEndpoint=…`). **Target exception:** with `--target docker`, `endpoint` and `connection_string` use `host.docker.internal:<published port>`, not the service name, because apps hand blob URLs to the browser and a service name does not resolve there (`blob-storage-siftly-spec.md` R9). The app's own compose file must add `extra_hosts: ["host.docker.internal:host-gateway"]` on Linux; `vyomi env --check` warns when `host.docker.internal` does not resolve on the developer's machine |
| `redis.<name>` | `host`, `port`, `password`, `url` (`redis://[:pass@]host:port/0`) |
| `servicebus.<namespace>` | `connection_string` (`Endpoint=sb://…;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=…;UseDevelopmentEmulator=true;`), `host`, `port` |
| `secret.<name>` | A random 32-character value, letters and digits only (safe in URLs, dotenv files and connection strings), generated once per app and stored by the appliance |

Values placed inside URLs (`postgres.<db>.url`, `redis.<name>.url`) are percent-encoded. `postgres.<db>.url` carries no SSL parameters; Siftly's Hocuspocus uses `node-postgres`, which does not use SSL unless the URL or `PGSSLMODE` asks for it, so none is needed there. Apps whose driver defaults to SSL append `?sslmode=disable` in the profile. Each profile carries `"version": 1`.

An unknown resource, field or secret is an error that names the output file and key. Resource types that Vyomi cannot serve yet (for example `servicebus` before its AMQP listener ships) are reported as **not available** and their keys are skipped, with a warning, so the rest still works.

## 5. Commands

| Command | Behaviour |
| --- | --- |
| `vyomi app add <path>` | Validates `<path>/.vyomi/app.json` and records the app in `~/.vyomi/apps.json` |
| `vyomi app list` / `vyomi app remove <name>` | List or unregister. Removing does not delete resources |
| `vyomi app provision [--app <name>]` | Sends the profile's `resources` to the appliance, which starts any needed backends and creates each resource. Idempotent: existing resources are left as they are; settings that changed are reported, not silently altered. One exception: if a Postgres role exists but its password no longer matches the stored secret (for example after the appliance's state was reset), the password is reset to the stored secret so the `.env` values keep working |
| `vyomi env [--app <name>] [--target host\|docker] [--dry-run] [--check]` | Resolves every expression through the appliance and writes each output file. `--dry-run` prints a diff with secrets masked. `--check` writes nothing and exits 1 if any file would change |
| `vyomi app status [--app <name>]` | Shows each resource and whether it exists and is reachable |

All commands work from any directory when `--app` is given, and from the app's repo root without it.

## 6. Appliance APIs (new)

| Endpoint | Purpose |
| --- | --- |
| `GET /api/runtime/endpoints` | For each backend: `network` form and `published` form. The network host comes from the canonical env vars the simulator already uses (`CLOUDLEARN_SQL_PG_HOST` and the rest of `_CANONICAL_ENV` in `core/appliance_readiness.py`), because service names differ between compose files (`vyomi-sql-postgres` vs `cloudlearn-sql-postgres`). The published port is read from the running container's port bindings through the Docker client when the socket is mounted, else from the configured defaults. The CLI turns `published` into the `host` target; on Multipass it substitutes the VM's IPv4 address (already read by `cmd/vyomi/multipass.go`) for `localhost` |
| `POST /api/runtime/apps/{name}/provision` | Body: the profile's `resources`. Starts backends through the existing `POST /api/runtime/backends/{name}/provision`, then creates resources. Returns per-resource status |
| `POST /api/runtime/apps/{name}/resolve` | Body: the profile's `outputs` and the target. Returns the resolved values. Generated secrets are created on first use and stored in the appliance's persistent state (SQLite, `VYOMI_APPS_DB`), so every developer machine and every rerun gets the same value |

**Authentication.** `provision` and `resolve` create resources and return secrets, and the simulator listens on all interfaces (`0.0.0.0:9000`). Both endpoints require the existing admin key (`X-CloudLearn-Admin-Key`, see `core/admin_auth.py`) **in every distribution mode**. The existing `require_admin_key()` skips the check outside appliance mode (`docker-compose.yml` and `cloudlite` default to developer mode), so these routes call `verify_admin_key()` directly and return **403** with `code: admin_key_required`, matching the existing endpoints. **Getting the key:** the key file is created lazily on first use and falls back to a path inside the image when `/data` is absent, so the CLI does not read a fixed file; it runs `python -c "from core.admin_auth import get_or_create_admin_key; print(get_or_create_admin_key())"` in the simulator container, which returns the existing key or creates it. The CLI runs that command once (`docker exec` on the Docker substrate, `multipass exec` on Multipass, finding the simulator container by compose service because its name differs between compose files) and caches it in `~/.vyomi/admin_key` with mode 0600. `endpoints` returns no secrets and needs no key.

**Appliance URL.** The CLI uses `http://localhost:${VYOMI_SIMULATOR_PORT:-9000}` (the Multipass VM IP on Max). Today `cmd/vyomi/bridge.go` hard-codes port 9000, which breaks when `VYOMI_SIMULATOR_PORT` is set (for example 9200 in `docker-compose.override.yml`).

### Resource creation, per type

| Type | Created by | Notes |
| --- | --- | --- |
| `postgres` | The appliance's admin connection (`CLOUDLEARN_SQL_PG_*`, as `core/gcp_sql_engine.py` uses) | Role with a generated password; database owned by the role; each extension installed **as admin** inside that database (`CREATE EXTENSION IF NOT EXISTS "<ext>"` while connected to it). Each `settable_parameters` entry becomes `GRANT SET ON PARAMETER <param> TO "<role>"` (Postgres 15+), which lets the role change it per session; **not** `ALTER ROLE … SET`, which would fix the value for every session of the role. Profiles never carry raw SQL: `extensions` must come from an allow-list of extensions available in the image (`vector`, `pg_trgm`, `uuid-ossp`, `citext`, …), `settable_parameters` from an allow-list of parameters (`session_replication_role`, …), and every name is validated as an identifier and quoted. This matters because a profile is a file in another repo, executed with superuser rights |
| `blob` | The same store dispatch the blob HTTP handler uses in `core/azure_dataplane.py`: the in-process store, or `core/azure_blob_store.py` when Azurite is configured (`_azurite()` check). Creating directly in the in-process dict would miss Azurite | Account key from the existing deterministic `storage_keys(account)`; public-access level recorded (on the marker blob in Azurite mode, blob spec R3) |
| `redis` | Backend provisioner (`redis` recipe) | Password from `VYOMI_REDIS_PASSWORD`, which the simulator receives from compose (Redis spec R5); empty when unset |
| `servicebus` | Service Bus runtime store (`core/azure_servicebus_runtime.py`, from the Service Bus plan) | Replaces the separate entities file planned there |

## 7. Writing dotenv files

1. Parse the existing file line by line, keeping comments, blank lines, key order, quoting style and line endings (LF or CRLF).
2. For each mapped key: replace the value in place if present, otherwise append it under a `# --- managed by vyomi (app: <name>) ---` block at the end.
3. Never touch keys that are not in the profile.
4. Quote values that contain spaces, `#`, `=` or quotes.
5. Write atomically: temporary file, then rename. Keep one backup, `<file>.vyomi.bak`.
6. If the target file is tracked by git (`git ls-files --error-unmatch`), refuse to write secrets into it unless `--allow-tracked` is given. If `git` is not installed, warn and continue.
7. Create missing files with mode 0600 on Unix.
8. Output paths in the profile always use `/`; the CLI converts them with `filepath.FromSlash`, and rejects absolute paths and any path that leaves the repo (`..`).

## 8. Security

- Generated secrets live only in the appliance's state and in the app's untracked `.env` files.
- Output never prints secret values unless `--show-secrets` is given.
- `provision` and `resolve` require the admin key in every mode, including developer mode; requests without it get 403. No new open port.
- Profiles cannot run arbitrary SQL (allow-lists and identifier validation, section 6).

## 9. Acceptance tests

1. `vyomi app add` rejects a profile with an unknown resource type or a malformed expression, naming the field.
2. `vyomi app provision --app siftly` on a fresh appliance creates the database (with every extension in the profile and the parameter grant), the containers (with their public-access level, in both the in-process and Azurite blob modes) and Redis. Running it again changes nothing.
3. `vyomi env --app siftly` writes the three files. A second run reports no changes. Keys not in the profile, and comments, are unchanged. CRLF files stay CRLF.
4. `--target docker` produces service-name addresses; `--target host` produces `localhost` and published ports. On Multipass, the VM IP replaces `localhost`.
   Blob fields follow the `host.docker.internal` exception in §4.
4a. On Multipass with `--target host`, Redis and Postgres are reachable from the host at the VM's IP (Redis binds the VM interface there; see `redis-siftly-spec.md` R2).
5. `--check` exits 0 after a write and 1 after the appliance's Redis port changes.
6. With Service Bus not yet available, `vyomi env` writes all other keys and warns about the skipped ones.
6a. With `--target docker`, the blob connection string uses `host.docker.internal`; `--check` warns on a machine where that name does not resolve.
7. Siftly's backend, Hocuspocus and content engine start against Vyomi with only the files written by `vyomi env` changed.
8. Writing into a git-tracked `.env` is refused without `--allow-tracked`.
9. Secrets match across two machines pointing at the same appliance, and across reruns.
10. `resolve` and `provision` without the admin key return 403, in both appliance and developer mode; `endpoints` works without it.
11. A profile with `"extensions": ["plpython3u"]` or a malformed identifier is rejected before any SQL runs.
12. After the appliance's state is reset, `vyomi app provision` restores the stored Postgres password and the existing `.env` keeps working.
13. With `VYOMI_SIMULATOR_PORT=9200`, all commands reach the appliance.

## 10. Open questions

- [ ] Should profiles also support YAML once a parser is acceptable in the CLI or appliance?
- [ ] Should `vyomi env` also emit a Kubernetes `Secret` or Docker Compose `env_file` for containerised apps?
- [ ] Where should Siftly's profile live: in Siftly's repo (preferred), or in Vyomi's `samples/` as a reference app?
- [ ] Does the Service Bus SDK accept a non-default port in `Endpoint=sb://host:port` together with `UseDevelopmentEmulator=true`? Needed when 5672 is remapped; verify in Service Bus spike B1.

## 11. Review log

| Date | Finding | Change |
| --- | --- | --- |
| 2026-10-18 | `provision` and `resolve` return secrets on a port bound to all interfaces | Both require the existing admin key; CLI caches it at 0600 |
| 2026-10-18 | Profile `grants` would run arbitrary SQL as superuser from another repo | Replaced by allow-listed `settable_parameters`; extensions allow-listed; identifiers validated |
| 2026-10-18 | Service names differ across compose files | Network hosts come from the canonical env vars in `appliance_readiness.py` |
| 2026-10-18 | CLI hard-codes port 9000 | Honour `VYOMI_SIMULATOR_PORT` |
| 2026-10-18 | Appliance state reset would orphan Postgres passwords | `provision` resets the role password to the stored secret |
| 2026-10-18 | Secrets with symbols break URLs and dotenv quoting | Alphanumeric secrets; percent-encoding in URL fields |
| 2026-10-18 | Git may be missing | Warn and continue |
| 2026-10-18 | Spec and plan effort disagreed | Aligned to the plan |
| 2026-10-18 | Custom Service Bus port with the emulator flag unverified | Open question, checked in Service Bus B1 |
| 2026-10-18 | Blob URLs from a Dockerised app are opened by the browser | Docker-target blob endpoint uses `host.docker.internal` (blob spec R9) |
| 2026-10-18 | Siftly also needs `uuid-ossp` | Added to the example profile |
| 2026-10-18 | Blob `host.docker.internal` rule sat in the tests only | Moved into the §4 field table; test 6a |
| 2026-10-18 | Blob containers created in the in-process dict would miss Azurite | Create through the handler's store dispatch |
| 2026-10-18 | Redis bound to 127.0.0.1 inside the Multipass VM is unreachable from the host | Redis spec R2 binds the VM interface on Multipass; test 4a |
| 2026-10-18 | Admin-key `docker exec` assumed one container name | Find the simulator by compose service |
| 2026-10-18 | Effort | 6 → 6.5 days with Claude (see plan) |
| 2026-10-18 | External review: admin endpoints return 403, not 401 | Spec and tests say 403 |
| 2026-10-18 | External review: `require_admin_key()` skips auth in developer mode | Routes call `verify_admin_key()` in every mode; test 10 covers developer mode |
| 2026-10-18 | Key file is created lazily and may live outside `/data` | CLI gets the key with `get_or_create_admin_key()` in the container |
| 2026-10-18 | External review: exact DDL for `settable_parameters` | `GRANT SET ON PARAMETER`, not `ALTER ROLE … SET` |
| 2026-10-18 | External review: example lacked `"version": 1` | Added |
| 2026-10-18 | External review: Hocuspocus `DATABASE_URL` and SSL | Checked: `node-postgres` uses no SSL by default; expressions now allow literal text, so `?sslmode=disable` can be appended where needed |
| 2026-10-18 | External review: Windows paths | `filepath.FromSlash`; absolute and `..` paths rejected |
| 2026-10-18 | Hocuspocus also needs `COLLAB_JWT_SECRET` | Added to the example as `${secret.collab_jwt}` |
