"""Lazy backend provisioner — starts heavy backing containers on demand.

Architecture
============

The simulator's backend clients (`core/vault_client.py`, `nats_client.py`,
`minio_mirror.py`, `dynamodb_proxy.py`, `elasticmq_proxy.py`) all gracefully
degrade to in-memory state when their backend container isn't running. That
lets us ship a tiny default `docker compose up` (just simulator + cloudsim +
postgres + gcs) and have everything work — features that would use Vault/NATS/
MinIO/DDB/MySQL just store state in memory until the user opts in.

This module provides the opt-in: a user-triggered API to spin up one of
those heavy backends in the background, with progress visible via a poll
endpoint. Once the container is healthy, the matching client's `available()`
flips to True on its next call and the corresponding feature starts using
the real backend.

Design choices
--------------

* **Async provision, sync status.** `provision_async(name)` returns immediately.
  `status(name)` reports current state (`absent` → `pulling` → `starting`
  → `ready` / `failed`). The SPA polls status while showing a progress modal.

* **No auto-stop.** Once running, the backend stays up until host restart.
  Trades RAM (~50 MB/backend) for instant subsequent calls. The user can
  explicitly stop via `POST /api/runtime/backends/{name}/stop`.

* **Idempotent.** Calling `provision_async` on an already-running backend
  is a no-op. Calling it during `pulling` returns the existing in-flight
  state. Safe to call from arbitrary code paths (or even from the UI to
  pre-warm).

* **Docker SDK over shelling out.** We talk to the daemon via the `docker`
  Python SDK against `/var/run/docker.sock`, which must be mounted into
  the simulator container (see compose). This is a well-known trade-off:
  the simulator gets effective root on the host via the socket. Acceptable
  for laptop-local dev; in production this would need finer-grained policy.

* **Recipes co-located here.** Each backend's `image`, `ports`, `env`,
  `healthcheck`, and `network` is declared in `_RECIPES`. Adding a new
  backend = adding one dict.

Failure modes
-------------

* Docker daemon unreachable      → `available()` returns False; provision
                                   API returns 503 with a helpful message.
* Image pull fails (network)     → status flips to `failed` with the error
                                   string; the user can retry.
* Container starts but never gets healthy → `failed` after the recipe's
                                   timeout; old container is left around
                                   so the user can `docker logs` it.
* Two parallel provisions of the same backend → second one short-circuits
                                   and waits on the first (lock per backend).
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlparse

log = logging.getLogger("cloudlearn.backend_provisioner")

# ─────────────────────────────────────────────────────────────────────────
# Docker SDK — optional import. If missing (e.g. native run outside docker
# without the SDK installed), `available()` returns False and the API
# surfaces "lazy-provisioning unavailable" instead of crashing.
# ─────────────────────────────────────────────────────────────────────────
try:
    import docker as _docker_sdk        # type: ignore[import-not-found]
    from docker.errors import (         # type: ignore[import-not-found]
        APIError as DockerAPIError,
        ImageNotFound,
        NotFound,
    )
    _docker_sdk_available = True
except Exception:
    _docker_sdk = None
    DockerAPIError = Exception          # type: ignore[misc,assignment]
    ImageNotFound = Exception           # type: ignore[misc,assignment]
    NotFound = Exception                # type: ignore[misc,assignment]
    _docker_sdk_available = False


# ─────────────────────────────────────────────────────────────────────────
# State enum (string, easy to serialise to JSON)
# ─────────────────────────────────────────────────────────────────────────

ABSENT      = "absent"        # not provisioned; no container exists
PULLING     = "pulling"       # docker pull in progress
STARTING    = "starting"      # container created, waiting for healthcheck
READY       = "ready"         # container running + healthy
FAILED      = "failed"        # provision failed (see .error)
STOPPED     = "stopped"       # provisioned previously, now stopped

VALID_STATES = {ABSENT, PULLING, STARTING, READY, FAILED, STOPPED}


# ─────────────────────────────────────────────────────────────────────────
# Recipes — one per supported backend
#
# Each recipe is the minimum docker run config needed to bring the backend
# up. Add a new entry here + nothing else changes elsewhere in the code.
#
# `health_check`: a callable that takes the container URL (e.g.
# "http://vyomi-minio:9000") and returns True when the backend is
# ready to serve traffic. Runs in a tight loop with a deadline.
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Recipe:
    name: str                                     # short id (also container suffix)
    image: str                                    # full image ref incl. tag
    container_name: str                           # what to call the container
    env: dict[str, str] = field(default_factory=dict)
    ports: dict[str, str] = field(default_factory=dict)   # internal -> external (host)
    network: Optional[str] = None                 # compose net; None → auto-discover
    volume_name: Optional[str] = None             # persistent volume mount path → name
    volume_mount: Optional[str] = None            # container-side path
    command: Optional[list[str]] = None           # docker CMD override
    health_url_template: str = ""                 # e.g. "http://{host}:9000/minio/health/ready"
    health_timeout_s: int = 60                    # how long we wait for ready
    description: str = ""                         # human-readable for UI


def _host_from_env(*env_keys: str, default: str) -> str:
    """Resolve a backend's on-network hostname from the SAME env var the
    simulator's client uses (a URL, host:port, or bare host), falling back to
    `default`. This keeps the provisioner's container name pinned to whatever
    the simulator actually talks to — immune to the cloudlearn-→vyomi- rename
    drift that stranded the readiness gauge (see core/appliance_readiness.py
    for the same _CANONICAL_ENV technique)."""
    for key in env_keys:
        val = (os.environ.get(key) or "").strip()
        if not val:
            continue
        if "://" in val:
            host = urlparse(val).hostname
            if host:
                return host
        else:
            return val.rsplit(":", 1)[0] if ":" in val else val
    return default


_RECIPES: dict[str, Recipe] = {
    # ─ MinIO (S3 backend — real bytes on disk) ──────────────────────────
    "minio": Recipe(
        name="minio",
        image="minio/minio:latest",
        container_name=_host_from_env("CLOUDLEARN_MINIO_URL", default="vyomi-minio"),
        env={
            "MINIO_ROOT_USER": os.environ.get("CLOUDLEARN_MINIO_ACCESS_KEY", "cloudlearn"),
            "MINIO_ROOT_PASSWORD": os.environ.get("CLOUDLEARN_MINIO_SECRET_KEY", "cloudlearn-dev-secret-key"),
        },
        ports={"9000/tcp": "9100"},
        volume_name="vyomi-minio",
        volume_mount="/data",
        command=["server", "/data", "--console-address", ":9001"],
        health_url_template="http://{host}:9000/minio/health/ready",
        health_timeout_s=60,
        description="MinIO — S3-compatible object store. Backs AWS S3 with real bytes.",
    ),

    # ─ HashiCorp Vault (transit KMS + KV secrets, dev mode) ─────────────
    "vault": Recipe(
        name="vault",
        image="hashicorp/vault:1.15",
        container_name=_host_from_env("CLOUDLEARN_VAULT_URL", default="vyomi-vault"),
        env={
            "VAULT_DEV_ROOT_TOKEN_ID":   os.environ.get("CLOUDLEARN_VAULT_TOKEN", "cloudlearn-dev-token"),
            "VAULT_DEV_LISTEN_ADDRESS":  "0.0.0.0:8200",
        },
        ports={"8200/tcp": "8200"},
        command=["server", "-dev",
                 f"-dev-root-token-id={os.environ.get('CLOUDLEARN_VAULT_TOKEN', 'cloudlearn-dev-token')}",
                 "-dev-listen-address=0.0.0.0:8200"],
        # Vault returns 200 when sealed=false + initialized=true; 429 while
        # init'ing. _wait_for_ready accepts 200..499 so both are fine; we
        # could refine if we want strict ready.
        health_url_template="http://{host}:8200/v1/sys/health",
        health_timeout_s=30,
        description=("Vault — KMS + secret store. Backs AWS KMS / Secrets Manager, "
                     "GCP Cloud KMS / Secret Manager, Azure Key Vault."),
    ),

    # ─ NATS (eventing — JetStream enabled) ──────────────────────────────
    "nats": Recipe(
        name="nats",
        image="nats:2-alpine",
        container_name=_host_from_env("CLOUDLEARN_NATS_URL", default="vyomi-nats"),
        ports={"4222/tcp": "4222", "8222/tcp": "8222"},
        volume_name="vyomi-nats",
        volume_mount="/data",
        command=["-js", "-sd", "/data", "-m", "8222"],
        # NATS monitoring port returns 200 on /varz when ready.
        health_url_template="http://{host}:8222/varz",
        health_timeout_s=30,
        description=("NATS JetStream — pub/sub + streams. Backs AWS EventBridge, "
                     "GCP Eventarc, Azure Event Grid."),
    ),

    # ─ DynamoDB-local (real AWS DynamoDB protocol) ──────────────────────
    "dynamodb": Recipe(
        name="dynamodb",
        image="amazon/dynamodb-local:latest",
        container_name=_host_from_env("CLOUDLEARN_DYNAMODB_URL", default="vyomi-dynamodb"),
        ports={"8000/tcp": "8000"},
        volume_name="vyomi-dynamodb",
        volume_mount="/data",
        # dynamodb-local needs to be run from its /home/dynamodblocal dir
        # (the launcher expects DynamoDBLocal.jar in the CWD). We can't set
        # working_dir via docker run; instead use the image's default CMD
        # by passing only the arg overrides via command (it appends them).
        command=["-jar", "DynamoDBLocal.jar", "-sharedDb", "-dbPath", "/data"],
        # DDB-local doesn't expose a /health endpoint; the root URL returns
        # an XML "MissingAuthenticationToken" error very quickly, which means
        # the listener is up. _wait_for_ready accepts 4xx as "alive".
        health_url_template="http://{host}:8000/",
        health_timeout_s=20,
        description="DynamoDB-local — full DynamoDB wire protocol. Backs AWS DynamoDB.",
    ),

    # ─ ElasticMQ (SQS legacy/query protocol) ────────────────────────────
    "elasticmq": Recipe(
        name="elasticmq",
        image="softwaremill/elasticmq-native:latest",
        container_name=_host_from_env("CLOUDLEARN_ELASTICMQ_URL", default="vyomi-elasticmq"),
        ports={"9324/tcp": "9324", "9325/tcp": "9325"},
        # The elasticmq-native image only listens on the SQS REST port 9324
        # (no stats UI on 9325). A bare GET there returns HTTP 400, which
        # _wait_for_ready accepts as "listener alive".
        health_url_template="http://{host}:9324/",
        health_timeout_s=30,
        description=("ElasticMQ — SQS-compatible queue. Backs AWS SQS legacy/query "
                     "protocol (modern JSON-RPC stays in-memory)."),
    ),

    # ─ MySQL 8 (CloudSQL MySQL / Azure DB for MySQL) ────────────────────
    "mysql": Recipe(
        name="mysql",
        image="mysql:8.0",
        container_name=_host_from_env("CLOUDLEARN_SQL_MYSQL_HOST", default="vyomi-sql-mysql"),
        env={
            "MYSQL_ROOT_PASSWORD": os.environ.get("CLOUDLEARN_SQL_MYSQL_ADMIN_PASSWORD", "cloudlearn"),
            "MYSQL_ROOT_HOST":     "%",
        },
        ports={"3306/tcp": "3306"},
        volume_name="vyomi-sql-mysql",
        volume_mount="/var/lib/mysql",
        # MySQL doesn't expose HTTP. Use a TCP-only check by hitting its
        # port and looking for the protocol greeting — but our generic
        # health_url uses urllib (HTTP only). Workaround: point at the
        # mysql admin "X protocol" port 33060 if available, OR rely on
        # docker's container health (running != ready). Acceptable for MVP:
        # we set a long timeout and trust that the container is "ready
        # enough" once the simulator's SQL engine successfully connects.
        # Empty template → skip HTTP probe; ready means "container is
        # running" (~5–10 s after start for MySQL 8).
        health_url_template="",
        health_timeout_s=120,
        description=("MySQL 8 — full MySQL wire protocol. Backs GCP Cloud SQL MySQL "
                     "and Azure Database for MySQL."),
    ),
}


# ─────────────────────────────────────────────────────────────────────────
# In-process state — one ProvisionState per recipe
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class ProvisionState:
    name: str
    state: str = ABSENT
    started_at: Optional[float] = None
    ready_at: Optional[float] = None
    pull_progress_pct: Optional[int] = None       # 0..100 during PULLING
    error: Optional[str] = None
    container_id: Optional[str] = None
    last_checked_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "started_at": self.started_at,
            "ready_at": self.ready_at,
            "pull_progress_pct": self.pull_progress_pct,
            "error": self.error,
            "container_id": self.container_id[:12] if self.container_id else None,
            "elapsed_seconds": (
                int(time.time() - self.started_at) if self.started_at else None
            ),
        }


_states: dict[str, ProvisionState] = {}
_state_lock = threading.Lock()
_provision_locks: dict[str, threading.Lock] = {}


def _get_state(name: str) -> ProvisionState:
    """Get-or-create the state row for a backend."""
    with _state_lock:
        if name not in _states:
            _states[name] = ProvisionState(name=name)
        return _states[name]


def _get_provision_lock(name: str) -> threading.Lock:
    """One mutex per backend so two parallel provisions don't race."""
    with _state_lock:
        if name not in _provision_locks:
            _provision_locks[name] = threading.Lock()
        return _provision_locks[name]


# ─────────────────────────────────────────────────────────────────────────
# Docker client — single shared instance, lazily created
# ─────────────────────────────────────────────────────────────────────────

_docker_client: Any | None = None


def _client() -> Any:
    """Returns a connected docker client, or raises RuntimeError if the
    daemon/socket isn't reachable."""
    global _docker_client
    if _docker_client is not None:
        return _docker_client
    if not _docker_sdk_available:
        raise RuntimeError(
            "The 'docker' Python SDK isn't installed; lazy backend "
            "provisioning is disabled. Add docker>=7.0.0 to requirements.txt."
        )
    try:
        _docker_client = _docker_sdk.from_env()
        _docker_client.ping()
    except Exception as e:
        raise RuntimeError(
            f"Docker daemon unreachable: {e}. Make sure /var/run/docker.sock "
            "is mounted into this container (see docker-compose.yml)."
        ) from e
    return _docker_client


def available() -> bool:
    """Cheap probe — is lazy provisioning operational at all?"""
    try:
        _client()
        return True
    except Exception:
        return False


_resolved_network: Optional[str] = None


def _resolve_network() -> str:
    """The docker network to attach provisioned backends to.

    Must be the SAME network the simulator container is on, or the simulator's
    clients can't resolve the backend by its service DNS name. The compose
    network name is project-derived (`appliance_default`, `vyomi_default`, …),
    so we can't hardcode it. Resolution order (cached after first success):

      1. Explicit override — VYOMI_BACKEND_NETWORK / CLOUDLEARN_BACKEND_NETWORK.
      2. Introspect our OWN container (hostname == container id by default) and
         take its first user-defined network. This is the reliable path inside
         docker and auto-tracks whatever project name compose used.
      3. Fallback to the historical compose default.
    """
    global _resolved_network
    if _resolved_network:
        return _resolved_network

    override = (os.environ.get("VYOMI_BACKEND_NETWORK")
                or os.environ.get("CLOUDLEARN_BACKEND_NETWORK"))
    if override:
        _resolved_network = override
        return _resolved_network

    try:
        client = _client()
        me = client.containers.get(os.environ.get("HOSTNAME") or socket.gethostname())
        nets = list((me.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}).keys())
        # Skip the built-in networks; prefer the compose user network.
        for n in nets:
            if n not in ("host", "none", "bridge"):
                _resolved_network = n
                return _resolved_network
        if nets:
            _resolved_network = nets[0]
            return _resolved_network
    except Exception:
        log.debug("provisioner: could not introspect own docker network", exc_info=True)

    _resolved_network = "appliance_default"
    return _resolved_network


# ─────────────────────────────────────────────────────────────────────────
# Sync helpers — used by the background thread
# ─────────────────────────────────────────────────────────────────────────

def _find_existing_container(recipe: Recipe) -> Optional[Any]:
    """Returns the existing container with this name, or None."""
    try:
        return _client().containers.get(recipe.container_name)
    except NotFound:
        return None


def _pull_image(recipe: Recipe, state: ProvisionState) -> None:
    """Pulls the image, streaming progress into `state.pull_progress_pct`."""
    client = _client()
    log.info("provisioner: pulling %s", recipe.image)
    state.state = PULLING
    state.pull_progress_pct = 0
    # The low-level pull API streams JSON lines we can use for progress.
    try:
        layers: dict[str, dict[str, int]] = {}  # layer_id -> {current, total}
        for line in client.api.pull(recipe.image, stream=True, decode=True):
            if "status" not in line:
                continue
            layer_id = line.get("id")
            progress_detail = line.get("progressDetail") or {}
            if layer_id and progress_detail.get("total"):
                layers[layer_id] = {
                    "current": int(progress_detail.get("current", 0)),
                    "total":   int(progress_detail["total"]),
                }
                total_bytes = sum(L["total"] for L in layers.values()) or 1
                done_bytes  = sum(L["current"] for L in layers.values())
                state.pull_progress_pct = min(99, int(done_bytes * 100 / total_bytes))
        state.pull_progress_pct = 100
    except Exception as e:
        raise RuntimeError(f"image pull failed: {e}") from e


def _start_container(recipe: Recipe, state: ProvisionState) -> str:
    """Creates + starts the container. Returns container id."""
    log.info("provisioner: starting %s", recipe.container_name)
    state.state = STARTING
    client = _client()

    # Attach to the simulator's own compose network so its clients can reach
    # the backend by DNS name. Recipe.network overrides if explicitly set.
    network = recipe.network or _resolve_network()

    # Make sure the network exists (compose default; should already be there)
    try:
        client.networks.get(network)
    except NotFound:
        client.networks.create(network, driver="bridge")

    # Make sure the volume exists if one is declared
    volumes = {}
    if recipe.volume_name and recipe.volume_mount:
        try:
            client.volumes.get(recipe.volume_name)
        except NotFound:
            client.volumes.create(name=recipe.volume_name)
        volumes[recipe.volume_name] = {"bind": recipe.volume_mount, "mode": "rw"}

    container = client.containers.run(
        recipe.image,
        name=recipe.container_name,
        detach=True,
        environment=recipe.env or None,
        command=recipe.command,
        network=network,
        ports=recipe.ports or None,    # container_port → host_port
        volumes=volumes or None,
        restart_policy={"Name": "unless-stopped"},
    )
    return container.id


def _wait_for_ready(recipe: Recipe, state: ProvisionState) -> None:
    """Polls the recipe's health URL until ready, or recipe.health_timeout_s
    elapses (raises RuntimeError on timeout).

    If `health_url_template` is empty (some backends don't expose HTTP —
    MySQL, raw TCP services), we use container-status as a coarser ready
    signal: wait until the docker container reports state "running" + a
    short post-start delay (the simulator's connection retry handles
    real readiness on the next call)."""
    import urllib.request
    import urllib.error
    import socket

    # No HTTP probe → wait for docker to report "running" + 5 s settle.
    if not recipe.health_url_template:
        deadline = time.time() + recipe.health_timeout_s
        client = _client()
        while time.time() < deadline:
            try:
                c = client.containers.get(recipe.container_name)
                c.reload()
                if c.status == "running":
                    # Short settle window for the in-container daemon to
                    # finish its own init (e.g. MySQL writes the system DB).
                    time.sleep(5)
                    log.info("provisioner: %s is running (no HTTP probe)", recipe.name)
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError(
            f"container did not enter 'running' state within {recipe.health_timeout_s}s"
        )

    url = recipe.health_url_template.format(host=recipe.container_name)
    deadline = time.time() + recipe.health_timeout_s
    last_err: Optional[str] = None

    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if 200 <= resp.status < 500:   # MinIO returns 200; some services 4xx
                    log.info("provisioner: %s is ready", recipe.name)
                    return
                last_err = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            # 4xx counts as "alive but unauthorised/etc" — that's enough
            # to know the listener is up (e.g. DynamoDB-local returns 400).
            if 400 <= e.code < 500:
                log.info("provisioner: %s is ready (HTTP %s — listener alive)", recipe.name, e.code)
                return
            last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError, socket.error) as e:
            last_err = str(e)
        time.sleep(1)

    raise RuntimeError(
        f"backend did not become healthy within {recipe.health_timeout_s}s "
        f"(last probe error: {last_err})"
    )


# ─────────────────────────────────────────────────────────────────────────
# Background worker per provision
# ─────────────────────────────────────────────────────────────────────────

def _provision_worker(recipe: Recipe, state: ProvisionState) -> None:
    """Runs in a background thread. Errors flip state.state → FAILED."""
    lock = _get_provision_lock(recipe.name)
    if not lock.acquire(blocking=False):
        # Another worker is already provisioning this backend; this one
        # just returns. The user's status poll will see the in-flight one.
        return
    try:
        state.error = None
        state.started_at = time.time()

        # Step 1 — does it already exist?
        existing = _find_existing_container(recipe)
        if existing is None:
            # Step 2 — pull the image (slow on first run)
            _pull_image(recipe, state)
            # Step 3 — start it
            state.container_id = _start_container(recipe, state)
        else:
            # Container exists; make sure it's running
            state.container_id = existing.id
            existing.reload()
            if existing.status != "running":
                state.state = STARTING
                existing.start()

        # Step 4 — wait for healthy
        _wait_for_ready(recipe, state)

        state.state = READY
        state.ready_at = time.time()

    except Exception as e:
        log.exception("provisioner: failed for %s", recipe.name)
        state.state = FAILED
        state.error = str(e)
    finally:
        lock.release()


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def recipes() -> list[str]:
    """Names of all known backends (so the UI knows what's provisionable)."""
    return sorted(_RECIPES.keys())


def recipe_metadata(name: str) -> Optional[dict[str, Any]]:
    """Human-readable info about a recipe (for the UI)."""
    r = _RECIPES.get(name)
    if r is None:
        return None
    return {
        "name": r.name,
        "image": r.image,
        "container_name": r.container_name,
        "description": r.description,
    }


def status(name: str) -> Optional[dict[str, Any]]:
    """Current provision status. Returns None if `name` isn't a known recipe."""
    if name not in _RECIPES:
        return None
    state = _get_state(name)
    # If we previously saw it ready, double-check the container's still alive.
    # Cheap reality-check: ping the container once every 10 s; otherwise
    # return cached state.
    now = time.time()
    if state.state == READY and (
        state.last_checked_at is None or now - state.last_checked_at > 10
    ):
        try:
            container = _find_existing_container(_RECIPES[name])
            if container is None or container.status != "running":
                # Container disappeared since last check; flip state
                state.state = STOPPED
        except Exception:
            pass  # docker unreachable, leave cached state
        state.last_checked_at = now
    return state.to_dict()


def provision_async(name: str) -> dict[str, Any]:
    """Kick off (or return existing) provisioning. Non-blocking — returns
    the initial status dict immediately. Caller should poll `status(name)`
    until state == READY or FAILED."""
    if name not in _RECIPES:
        raise KeyError(f"unknown backend recipe: {name!r}")
    state = _get_state(name)
    # If already in flight or ready, just return the current view.
    if state.state in (PULLING, STARTING):
        return state.to_dict()
    if state.state == READY:
        return state.to_dict()
    # Reset any failed previous attempt
    state.state = ABSENT
    state.error = None
    state.started_at = None
    state.ready_at = None
    state.pull_progress_pct = None
    # Fire and forget
    recipe = _RECIPES[name]
    thread = threading.Thread(
        target=_provision_worker,
        args=(recipe, state),
        name=f"provision-{name}",
        daemon=True,
    )
    thread.start()
    return state.to_dict()


def stop(name: str) -> dict[str, Any]:
    """Stop the backend container (without removing). State flips to STOPPED.
    Subsequent provision_async will start the existing container, skipping
    the pull."""
    if name not in _RECIPES:
        raise KeyError(f"unknown backend recipe: {name!r}")
    recipe = _RECIPES[name]
    state = _get_state(name)
    try:
        c = _find_existing_container(recipe)
        if c is not None and c.status == "running":
            c.stop(timeout=10)
        state.state = STOPPED
    except Exception as e:
        state.error = str(e)
    return state.to_dict()
