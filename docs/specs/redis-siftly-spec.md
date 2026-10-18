---
title: Redis for Siftly — spec
status: draft (revision 4 — aligned with app profiles; second self-review applied)
updated: 2026-10-18
owner: Rohith
repo: ~/Documents/appliance (Vyomi v3.0.6)
related:
  - siftly-integration-gaps.md (row 6)
  - storage-cache-siftly-implementation-plan.md (RD1–RD5)
  - app-env-spec.md (starts Redis for the app; writes the env values)
---

# Redis for Siftly — spec

**Goal:** Vyomi provides a Redis server that Siftly's backend and content engine use for caching, locks, rate limits, pub/sub and streams, without affecting users who never use Redis.

**Effort:** about 2.2 days solo, about 1.25 days with Claude (RD1–RD5). CLI plumbing and env writing are counted in the app-profile plan.

## 1. What Siftly uses

- **Commands** (from `backend/services`, `routes`, `utils`, `workers`, `config`): `EXPIRE` (45 sites), Lua `EVAL` (31) and `EVALSHA` (4), pipelines (15), `INCR` (13), `ZADD` (12), `PUBLISH` (7), `SUBSCRIBE` (2), streams `XADD` (3) and `XREAD` (2). The content engine (`siftly-agents-2`) uses pub/sub for its run bus.
- **So it must be real Redis.** Lua, streams and pub/sub rule out a simple key-value stand-in.
- **Configuration** (`backend/config/redis_config.py`, `siftly-agents-2/.env.example`):
  - `REDIS_HOST`, `REDIS_PORT` (default 6379), `REDIS_PASSWORD`, `REDIS_DB` (default 0).
  - Socket timeouts: `REDIS_SOCKET_TIMEOUT`, `REDIS_SOCKET_CONNECT_TIMEOUT`, `REDIS_RETRY_ON_TIMEOUT`.
  - `REDIS_SSL_ENABLED` **defaults to `true`** in Siftly's code, so local use must set `false`.
  - `siftly-agents-2` also documents `REDIS_URL`.

## 2. What Vyomi has today

- **No Redis.**
- **Backends are added in two places:** a compose service, usually with `profiles: ["full"]`, and an on-demand `Recipe` in `core/backend_provisioner.py`. NATS and DynamoDB do both.
- **`docker-compose.override.yml` moves host ports into the 3xxxx range** to avoid clashes, for example Postgres 35432 and MySQL 33306.
- **The provisioner's readiness check for non-HTTP backends** (`_wait_for_ready`, lines 557–576) is "container is running, then sleep 5 s". That can report ready before the server accepts connections.
- **The readiness gauge** (`core/appliance_readiness.py`, `_BACKENDS`) counts every listed backend for the active profile.
- **`/api/runtime/backends`** (`routes/console.py:139`) is a hardcoded list.

## 3. Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| R1 | Compose service `vyomi-redis`, image `redis:7-alpine` (pinned tag), `profiles: ["full", "app"]`, volume `vyomi-redis`, AOF on (`--appendonly yes`). No `maxmemory` by default; optional `VYOMI_REDIS_MAXMEMORY` with policy `noeviction` (Siftly relies on locks and streams, so keys must never be evicted silently) | Must |
| R2 | Host port bound to **127.0.0.1 only**: `${VYOMI_REDIS_BIND:-127.0.0.1}:${VYOMI_REDIS_PORT:-36379}:6379` (3xxxx convention, avoids a local Redis on 6379). Apps on the Docker network use `vyomi-redis:6379`. **Multipass:** 127.0.0.1 inside the VM is unreachable from the host, so the Multipass launcher sets `VYOMI_REDIS_BIND` to the VM's own address (Multipass's default network is reachable only from the host machine, not the LAN) | Must |
| R3 | On-demand `Recipe` in `core/backend_provisioner.py` with the same container name (from `CLOUDLEARN_REDIS_URL`, default `vyomi-redis`, like the other recipes), image, volume and port. **Same volume in both modes:** the compose volume declares `name: vyomi-redis`, because compose otherwise prefixes it with the project name (`appliance_vyomi-redis`) while the recipe uses the bare name, so data would differ between modes. **Same binding in both modes:** the recipe publishes `127.0.0.1:<VYOMI_REDIS_PORT>` (the Docker SDK accepts `("127.0.0.1", port)`); today's recipes publish on all interfaces. If the compose container already exists, the provisioner adopts it by name (existing `_find_existing_container`) | Must |
| R4 | The provisioner's non-HTTP readiness becomes a real check: Docker health status `healthy` when the container defines a health check, else a TCP connect to the service port, retried until `health_timeout_s`. The Redis service defines `redis-cli ping` as its health check, with the password passed through the `REDISCLI_AUTH` environment variable, not `-a` (which shows in process listings and prints a warning). Set `REDISCLI_AUTH` **only when the password is non-empty**: with an empty `REDISCLI_AUTH`, `redis-cli` still sends `AUTH ""`, a server with no password rejects it, and the command fails. The health check is `["CMD-SHELL", "if [ -n \"$VYOMI_REDIS_PASSWORD\" ]; then export REDISCLI_AUTH=\"$VYOMI_REDIS_PASSWORD\"; fi; redis-cli ping | grep -q PONG"]` (`grep` because `redis-cli` can exit 0 on an error reply). **Probe details:** `recipe.ports` keys carry the protocol (`"6379/tcp"`), so the port is `int(key.split("/")[0])`; each attempt catches `OSError` (which covers refused connections, timeouts and `socket.gaierror` while Docker's DNS does not yet know a just-started container). Benefits MySQL and any other non-HTTP backend too | Must |
| R5 | Optional password via `VYOMI_REDIS_PASSWORD` (`--requirepass`); no TLS. The simulator service also receives `VYOMI_REDIS_PASSWORD`, so the app-profile resolver can return `${redis.<name>.password}` and `url` | Must |
| R6 | Readiness gauge: add `redis` under a new category `app` that is counted **only** when `app` is in `COMPOSE_PROFILES` / `VYOMI_PROFILE`, or when its TCP probe currently succeeds (the readiness module has no Docker client) | Must |
| R7 | `/api/runtime/backends`: add a `redis` entry (TCP probe), `backs: ["Azure Cache for Redis (app use)"]` | Should |
| R8 | **Done by the app profile, not here.** `vyomi app provision --app siftly` starts Redis through its recipe; `vyomi env --app siftly` writes `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_URL` from `${redis.default.*}`, and the profile sets the literals `REDIS_DB=0` and `REDIS_SSL_ENABLED=false`. Host target: `localhost` and `VYOMI_REDIS_PORT`; Docker target: `vyomi-redis:6379` | Must (dependency) |
| R9 | `vyomi redis flush` (Go subcommand, on the app-profile CLI plumbing) runs `redis-cli FLUSHALL` inside the Redis container, adding `-e REDISCLI_AUTH=…` to `docker exec` **only when the password is non-empty** (see R4); `docker exec` on Docker, `multipass exec` then `docker exec` on Multipass | Should |
| R10 | Azure Cache for Redis / ElastiCache / Memorystore resources and console pages | Won't (not needed for Siftly) |
| R11 | `vyomi up --with app` sets `COMPOSE_PROFILES=app` before invoking compose (today's `vyomi up` appends arguments after the compose verb, so `--profile` cannot be passed through). Built in app-env AE5. Optional for Siftly, because `vyomi app provision` already starts Redis on demand | Should |

## 4. Regression safety

| Risk | Guard |
| --- | --- |
| A local Redis on 6379 stops `vyomi up` | Profile-gated (not started by default) and host port 36379 by default |
| Readiness gauge stuck below 100% | `app` category counted only when used (R6) |
| Exposing an unauthenticated Redis on the LAN | Bound to 127.0.0.1 (R2) |
| Provisioner reports ready too early | Real readiness check (R4) |
| Change to `_wait_for_ready` breaks other backends | Covered by starting MySQL and DynamoDB through the provisioner in the same test run |

## 5. Acceptance tests

1. Plain `vyomi up` (no `app` profile) does not start Redis; the readiness gauge reaches 100%.
2. With port 6379 already taken on the host, `vyomi up --with app` starts Redis on 36379.
2a. Redis started by compose and then requested through the provisioner is adopted, not duplicated; a key written in one mode is readable in the other (same volume).
3. Provisioning Redis on demand returns ready only once `PING` answers `PONG`; MySQL provisioning still works.
4. From another machine on the LAN, port 36379 is not reachable, whether Redis was started by compose or by the provisioner.
5. A script exercises what Siftly uses: `SET` with `EX`, `INCR`, `ZADD`/`ZRANGE`, a pipeline, an `EVAL` lock script, `PUBLISH`/`SUBSCRIBE`, `XADD`/`XREAD`. All pass.
6. Siftly's backend starts with the env from `vyomi env --app siftly` and logs a successful Redis connection with `ssl_enabled=false`; the content engine connects with `REDIS_URL`.
7. With `VYOMI_REDIS_PASSWORD` set, `vyomi redis flush` succeeds on Docker and Multipass, and the password does not appear in `ps` output.
7a. With **no** password (the default), the health check reports healthy and `vyomi redis flush` succeeds.
8. A key set before a restart is present afterwards (AOF).

## 6. Out of scope

Redis Cluster, Sentinel, TLS, ACL users beyond one password, managed-cache control planes.

## 7. Review log

| Date | Finding | Change |
| --- | --- | --- |
| 2026-10-18 | Port, LAN binding, `REDIS_URL`, maxmemory, readiness category | Revisions 2–3 |
| 2026-10-18 | `vyomi env --map` superseded by app profiles | R8 depends on `vyomi app provision` and `vyomi env --app` |
| 2026-10-18 | Compose volume is project-prefixed; recipe volume is not, so the two modes see different data | `name: vyomi-redis` on the compose volume; test 2a |
| 2026-10-18 | Recipes publish ports on all interfaces | Recipe binds 127.0.0.1; test 4 covers both modes |
| 2026-10-18 | `-a <password>` visible in process listings | `REDISCLI_AUTH` in the health check and flush |
| 2026-10-18 | Resolver cannot return the password unless the simulator has it | R5 passes `VYOMI_REDIS_PASSWORD` to the simulator |
| 2026-10-18 | Flush assumed Docker | R9 covers Multipass |
| 2026-10-18 | R11 duplicated app-env AE5 and was not needed with on-demand start | R11 → Should, built in AE5; requirements reordered |
| 2026-10-18 | External review: empty `REDISCLI_AUTH` sends `AUTH ""` and fails on a password-less server | Set it only when non-empty; health check greps `PONG`; test 7a |
| 2026-10-18 | External review: `recipe.ports` keys are `"6379/tcp"`; DNS lag on new containers | Parse the port; catch `OSError` per attempt |
| 2026-10-18 | Redis on 127.0.0.1 inside the Multipass VM cannot be reached from the host | `VYOMI_REDIS_BIND`, set to the VM address by the Multipass launcher |
