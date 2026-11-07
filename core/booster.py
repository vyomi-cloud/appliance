"""Booster pack (appliance side, Phase 1) - see docs/architecture/v4.0/V4-BOOSTER-DESIGN-DISCUSSION.md.

The booster is the Pro/Max offline appliance with NO console of its own. This module owns:

  * booster-mode detection (VYOMI_BOOSTER=1|0; default ON for Pro/Max - design s1/s10)
  * the headless guard: GET /ui, /v4, /console ... -> 404 JSON pointing at the Nano UI (s1);
    /_wire APIs, /healthz and every native cloud API stay served
  * the 70% resource cap, split 50/50 compute/AI, plus `can_allocate()` (s4)
  * pairing with a Nano tab: short code -> short-lived token bound to account + booster id (s5)
  * origin allow-list / Host check / rate limit for the /booster/* routes (s5, s15)

No new crypto: the token is a standard HS256 JWT built with the stdlib `hmac`, keyed by a
per-booster secret persisted next to the licence state. The *entitlement* it carries comes from
the portal-signed licence JWT already verified by core.license_remote (this module never mints
entitlements; it only attests "this tab paired with this booster").
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import threading
import time
import uuid
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, Response

NANO_URL = "https://vyomi.cloud/nano/"
WIRE_FLAG = "vyomi.wire_prefix"   # set by routes/wire_prefix.py on rewritten /_wire scopes
BOOSTER_TIERS = ("pro", "max")
CAP_FRACTION = 0.70            # design s4
AI_SHARE = 0.50                # design s13: 50% compute / 50% AI of the capped budget
PAIR_CODE_TTL_S = 600
TOKEN_TTL_S = 900
TOKEN_AUD = "vyomi-booster"
TOKEN_ISS = "vyomi-booster-local"
MAX_CODE_ATTEMPTS = 5
RATE_LIMIT_PER_MIN = 30

# Paths whose GET/HEAD is UI (served nowhere on a booster). Exact paths are matched
# literally so S3 buckets that happen to be called "aws"/"gcp" keep working for SDKs.
_UI_PREFIXES = ("/ui", "/v4", "/console", "/clouds", "/product", "/pricing",
                "/assets", "/static", "/docs", "/favicon.ico")
_UI_EXACT = ("/aws", "/gcp", "/azure")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
_HOST_SUFFIXES = (".local.vyomi.cloud", ".booster.vyomi.cloud")
_ORIGIN_EXACT = {"https://vyomi.cloud", "https://www.vyomi.cloud"}
_LOOPBACK_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


# --------------------------------------------------------------------------- mode
def _licence_tier() -> tuple[str, bool]:
    """(canonical tier, expired) from licence state WITHOUT downgrading on expiry, so a
    lapsed Pro/Max booster stays headless (and reports `locked`) instead of regrowing a UI."""
    from core import app_context as ctx
    from core import tier_policy
    expired = False
    try:
        raw = ctx.active_tier()
    except Exception:
        raw = "free"
    try:
        claims = ctx.STATE.get("license_claims") or {}
        if claims and claims.get("tier"):
            from core import license_remote as lr
            raw = str(claims.get("tier"))
            expired = lr.is_sub_expired(claims)
            ts = lr.trial_status(claims=claims, data_dir=_state_dir())   # monotonic clock: setting the date back can't extend a trial
            if ts.get("locked"):
                expired = True
    except Exception:
        pass
    return tier_policy.normalize_tier(raw), expired


def booster_mode(tier: Optional[str] = None) -> bool:
    env = (os.environ.get("VYOMI_BOOSTER") or "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    from core import tier_policy
    t = tier_policy.normalize_tier(tier) if tier is not None else _licence_tier()[0]
    return t in BOOSTER_TIERS


def _endpoints_path() -> str:
    return os.path.join(_state_dir(), "booster_endpoints.json")


def _read_endpoints_file() -> dict:
    try:
        with open(_endpoints_path()) as f:
            d = json.load(f)
        return {k: (str(d.get(k)) if d.get(k) else None) for k in ("relay_url", "local_url")}
    except Exception:
        return {"relay_url": None, "local_url": None}


def set_endpoints(relay_url: Optional[str] = None, local_url: Optional[str] = None) -> dict:
    """Persist the endpoints the tunnel/cert provisioning obtained (None/"" clears a value). Read back by endpoints()."""
    cur = {}
    for k, v in (("relay_url", relay_url), ("local_url", local_url)):
        cur[k] = (v or "").strip().rstrip("/") or None
    os.makedirs(_state_dir(), exist_ok=True)
    tmp = _endpoints_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f)
    os.replace(tmp, _endpoints_path())
    return endpoints()


def _local_hostname_enabled() -> bool:
    """https://<id>.local.vyomi.cloud is only advertised once its hostname config is switched on
    (VYOMI_BOOSTER_LOCAL_HOSTNAME=1, set by the cert/DNS provisioning)."""
    return (os.environ.get("VYOMI_BOOSTER_LOCAL_HOSTNAME") or "").strip().lower() in ("1", "true", "yes", "on")


def endpoints() -> dict:
    """relay_url / local_url the browser may use. Precedence: explicit env > persisted file (set_endpoints) >
    derived (local_url = https://<booster_id>.local.vyomi.cloud when the hostname config is enabled) > None."""
    f = _read_endpoints_file()
    relay = os.environ.get("VYOMI_BOOSTER_RELAY_URL") or f["relay_url"] or None
    local = os.environ.get("VYOMI_BOOSTER_LOCAL_URL") or f["local_url"]
    if not local and _local_hostname_enabled():
        try:
            local = f"https://{booster_id()}.local.vyomi.cloud"
        except Exception:
            local = None
    return {"relay_url": relay, "local_url": local or None}


def nano_pointer() -> dict:
    return {"error": {"code": "BoosterHeadless",
                      "message": "This Vyomi booster has no console. Open the Nano UI and pair with it.",
                      "nano_ui": NANO_URL, "pair": "vyomi booster pair"}}


def is_ui_path(method: str, path: str, headers: dict) -> bool:
    if method not in ("GET", "HEAD"):
        return False
    if path in _UI_EXACT:
        return True
    if path == "/":
        # "/" is also S3 ListBuckets for SDKs: only a browser (html, unsigned) is UI.
        return ("text/html" in headers.get("accept", "")
                and not headers.get("authorization") and "x-amz-date" not in headers)
    for p in _UI_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return True
    return False


def cors_headers(origin: str) -> list[tuple[bytes, bytes]]:
    return [(b"access-control-allow-origin", origin.encode()), (b"vary", b"Origin"),
            (b"access-control-allow-headers", b"authorization, content-type, x-vyomi-booster-token"),
            (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
            (b"access-control-allow-private-network", b"true")]


class HeadlessMiddleware:
    """Pure-ASGI. Sits inside the /_wire rewrite so /_wire/ui is blocked too. Also owns CORS for
    /booster/* (outside the app-wide CORSMiddleware, whose origin list is loopback-only/"*")."""

    def __init__(self, app):
        self.app = app

    async def _respond(self, send, status, body=b"", headers=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", str(len(body)).encode()), *headers]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self._inner(scope, receive, send)
        slots: list = []                 # admission slots this request reserves; leftovers are released when it ends
        tok = REQUEST_SLOTS.set(slots)
        from core import booster_ai
        ai_cloud = booster_ai.cloud_of_path(scope.get("path", ""))
        ai_toks = (booster_ai.CLOUD.set(ai_cloud), booster_ai.OP.set(booster_ai.op_of_path(scope.get("path", "")))) if ai_cloud else None
        try:
            await self._inner(scope, receive, send)
        finally:
            REQUEST_SLOTS.reset(tok)
            if ai_toks:
                booster_ai.OP.reset(ai_toks[1])
                booster_ai.CLOUD.reset(ai_toks[0])
            if slots:
                release_slots("compute", slots)

    async def _inner(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                       for k, v in scope.get("headers") or []}
            path = scope.get("path", "")
            wired = bool(scope.get(WIRE_FLAG)) and booster_mode()
            if wired and headers.get("x-vyomi-booster-token") is not None:
                try:
                    verify_token(headers["x-vyomi-booster-token"])
                except Exception as e:
                    return await self._respond(send, 401, json.dumps({"error": {"code": "InvalidBoosterToken", "message": str(e)}}).encode(),
                                               [(b"content-type", b"application/json")])
            elif wired and os.environ.get("VYOMI_BOOSTER_REQUIRE_TOKEN") == "1" and scope.get("method") != "OPTIONS":
                return await self._respond(send, 401, json.dumps({"error": {"code": "BoosterTokenRequired", "message": "pair first"}}).encode(),
                                           [(b"content-type", b"application/json")])
            if path == "/booster" or path.startswith("/booster/") or wired:
                origin = headers.get("origin", "")
                ok = bool(origin) and origin_allowed(origin) and host_allowed(headers.get("host", ""))
                if scope.get("method") == "OPTIONS":
                    return await self._respond(send, 204 if ok else 403, b"", cors_headers(origin) if ok else ())
                if ok:
                    async def cors_send(msg):
                        if msg["type"] == "http.response.start":
                            h = [(k, v) for k, v in msg.get("headers", [])
                                 if not k.lower().startswith(b"access-control-") and k.lower() != b"vary"]
                            msg = {**msg, "headers": h + cors_headers(origin)}
                        await send(msg)
                    return await self.app(scope, receive, cors_send)
            if not (path == "/booster" or path.startswith("/booster/")) and is_ui_path(scope.get("method", "GET"), path, headers) and booster_mode():
                body = json.dumps(nano_pointer()).encode()
                return await self._respond(send, 404, body, [(b"content-type", b"application/json")])
        await self.app(scope, receive, send)


# --------------------------------------------------------------------------- resources
def _read_int(path: str) -> Optional[int]:
    try:
        v = open(path).read().strip()
        return None if v in ("max", "") else int(v)
    except Exception:
        return None


def host_memory_mb() -> int:
    env = os.environ.get("VYOMI_HOST_MEM_MB")      # the host CLI passes the REAL host RAM under Docker
    if env and env.isdigit():
        return int(env)
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except Exception:
        pass
    try:
        import subprocess
        return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()) // (1024 * 1024)
    except Exception:
        return 4096


def container_memory_limit_mb() -> Optional[int]:
    """Docker VM / cgroup memory ceiling visible to this process (None = unlimited)."""
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        v = _read_int(p)
        if v and v < (1 << 50):
            return v // (1024 * 1024)
    return None


def _state_dir() -> str:
    return os.environ.get("CLOUDLEARN_STATE_DIR", "/data")


def _memory_split(cap_mb: int) -> dict:
    """50/50 compute/AI - except while the LLM is remote (core/booster_remote_llm): the in-Codespace AI pack does not load, so the
    AI bucket is 0 and the whole cap goes to compute (VMs/services)."""
    try:
        from core import booster_remote_llm as R
        if R.active():
            return {"compute": int(cap_mb), "ai": 0}
    except Exception:
        pass
    return {"compute": int(cap_mb * (1 - AI_SHARE)), "ai": int(cap_mb * AI_SHARE)}


def resource_budget() -> dict:
    host_mb = host_memory_mb()
    limit_mb = container_memory_limit_mb()
    cap_mb = int(host_mb * CAP_FRACTION)
    if limit_mb:                         # Docker: min(70% host, Docker VM limit)
        cap_mb = min(cap_mb, limit_mb)
    cap_env = os.environ.get("VYOMI_BOOSTER_CAP_MB")          # explicit booster budget (e.g. 8192 on a 2-core/8GB Codespace)
    if cap_env and cap_env.isdigit():
        cap_mb = int(cap_env)
    cpus = int(os.environ.get("VYOMI_BOOSTER_CPUS") or 0) or os.cpu_count() or 1
    try:
        du = shutil.disk_usage(_state_dir() if os.path.isdir(_state_dir()) else ".")
        disk_cap_gb = round(min(du.total * CAP_FRACTION, du.free) / 1e9, 1)
        disk_free_gb = round(du.free / 1e9, 1)
    except Exception:
        disk_cap_gb = disk_free_gb = 0.0
    return {
        "cap_fraction": CAP_FRACTION,
        "host_memory_mb": host_mb,
        "docker_vm_limit_mb": limit_mb,
        "memory_cap_mb": cap_mb,                      # hard budget
        "memory_split_mb": _memory_split(cap_mb),
        "cpu_cap_cores": round(cpus * CAP_FRACTION, 2),   # shared / overcommittable (not enforced)
        "disk_quota_gb": disk_cap_gb, "disk_free_gb": disk_free_gb,
    }


class BoosterCapacityError(Exception):
    """The clouds' real capacity errors. Callers map .cloud/.code/.status to their wire format."""

    CODES = {"aws": ("InsufficientInstanceCapacity", 500),
             "gcp": ("ZONE_RESOURCE_POOL_EXHAUSTED", 503),
             "azure": ("AllocationFailed", 409)}

    def __init__(self, cloud: str, kind: str, requested_mb: int, free_mb: int, zone: str = "-"):
        self.cloud = cloud if cloud in self.CODES else "aws"
        self.code, self.status = self.CODES[self.cloud]
        self.kind, self.requested_mb, self.free_mb = kind, requested_mb, free_mb
        self.message = {
            "aws": "We currently do not have sufficient capacity in the Availability Zone you requested.",
            "gcp": f"The zone '{zone}' does not have enough resources available to fulfill the request. "
                   "Try a different zone, or try again later.",
            "azure": "Allocation failed. We do not have sufficient capacity for the requested VM size in this region.",
        }[self.cloud]
        super().__init__(f"{self.code}: {self.message}")


_LEDGER_LOCK = threading.Lock()
_LEDGER: dict[str, dict[str, int]] = {"compute": {}, "ai": {}}
_EXPIRES: dict[str, dict[str, float]] = {"compute": {}, "ai": {}}   # ident -> monotonic deadline (admission slots only)
SLOT_PREFIX = "rsv:"
REQUEST_SLOTS: "contextvars.ContextVar[Optional[list]]" = contextvars.ContextVar("booster_request_slots", default=None)
SLOT_TTL_S = float(os.environ.get("VYOMI_BOOSTER_SLOT_TTL_S", "120"))


def _purge_locked(now: Optional[float] = None) -> None:
    """Drop admission slots whose create never completed (crash/failure between admit and create)."""
    now = time.monotonic() if now is None else now
    for kind, exp in _EXPIRES.items():
        for ident in [i for i, t in exp.items() if t <= now]:
            exp.pop(ident, None)
            _LEDGER[kind].pop(ident, None)


def usage() -> dict:
    with _LEDGER_LOCK:
        _purge_locked()
        return {k: sum(v.values()) for k, v in _LEDGER.items()}


def _kind_budget_mb(kind: str) -> int:
    if kind not in _LEDGER:
        raise ValueError(f"unknown allocation kind {kind!r} (compute|ai)")
    return resource_budget()["memory_split_mb"][kind]


def can_allocate(kind: str, mb: int, *, cloud: str = "aws", zone: str = "-", enforce: Optional[bool] = None) -> None:
    """NON-reserving check: raise BoosterCapacityError if `mb` more RAM exceeds the kind's share of the cap.
    Use reserve()/allocate() on a create path - a check alone races. No-op when booster mode is off."""
    if not (booster_mode() if enforce is None else enforce):
        return
    budget = _kind_budget_mb(kind)
    used = usage()[kind]
    if used + int(mb) > budget:
        raise BoosterCapacityError(cloud, kind, int(mb), max(0, budget - used), zone)


def allocate(kind: str, ident: str, mb: int, **kw) -> None:
    """Atomic check+reserve for `ident` (re-allocating the same ident replaces its previous size)."""
    with _LEDGER_LOCK:
        _purge_locked()
        budget = _kind_budget_mb(kind)
        used = sum(_LEDGER[kind].values()) - _LEDGER[kind].get(ident, 0)
        on = booster_mode() if kw.get("enforce") is None else kw["enforce"]
        if on and used + int(mb) > budget:
            raise BoosterCapacityError(kw.get("cloud", "aws"), kind, int(mb), max(0, budget - used), kw.get("zone", "-"))
        _LEDGER[kind][ident] = int(mb)
        _EXPIRES[kind].pop(ident, None)


def reserve_slots(kind: str, n: int, mb: int, *, cloud: str = "aws", zone: str = "-",
                  enforce: Optional[bool] = None) -> list[str]:
    """Admission: atomically reserve `n` slots of `mb` each (all-or-nothing) under a short TTL.
    Concurrent admissions can never oversubscribe the budget. Slots are consumed by rebind() when the real
    instance id exists; unconsumed ones expire. Returns [] (no-op) when booster mode is off."""
    on = booster_mode() if enforce is None else enforce
    if not on:
        return []
    n = max(1, int(n))
    with _LEDGER_LOCK:
        _purge_locked()
        budget = _kind_budget_mb(kind)
        used = sum(_LEDGER[kind].values())
        if used + n * int(mb) > budget:
            raise BoosterCapacityError(cloud, kind, n * int(mb), max(0, budget - used), zone)
        ids = [f"{SLOT_PREFIX}{uuid.uuid4().hex[:12]}" for _ in range(n)]
        deadline = time.monotonic() + SLOT_TTL_S
        for i in ids:
            _LEDGER[kind][i] = int(mb)
            _EXPIRES[kind][i] = deadline
        return ids


def rebind(kind: str, slot: str, ident: str, mb: int, **kw) -> None:
    """Turn an admission slot into the real instance's reservation (resizing to `mb`, atomically)."""
    with _LEDGER_LOCK:
        _LEDGER[kind].pop(slot, None)
        _EXPIRES[kind].pop(slot, None)
    allocate(kind, ident, mb, **kw)


def release_slots(kind: str, slots) -> None:
    with _LEDGER_LOCK:
        for s_ in slots:
            _LEDGER[kind].pop(s_, None)
            _EXPIRES[kind].pop(s_, None)


def release(kind: str, ident: str) -> None:
    with _LEDGER_LOCK:
        _LEDGER[kind].pop(ident, None)
        _EXPIRES[kind].pop(ident, None)


# --------------------------------------------------------------------------- identity / tokens
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def booster_id() -> str:
    from core import app_context as ctx, license_remote as lr
    return "bst-" + lr.get_or_create_install_id(ctx.STATE)[:16]


_secret_cache: dict[str, bytes] = {}


def _secret() -> bytes:
    if "k" in _secret_cache:
        return _secret_cache["k"]
    path = os.path.join(_state_dir(), "booster_secret")
    try:
        k = open(path, "rb").read()
        if len(k) < 32:
            raise ValueError
    except Exception:
        k = secrets.token_bytes(32)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(k)
        except Exception:
            pass                       # read-only state dir: per-process secret, tokens die on restart
    _secret_cache["k"] = k
    return k


def mint_token(account: str, tier: str, *, ttl: int = TOKEN_TTL_S, now: Optional[float] = None) -> str:
    now = int(now if now is not None else time.time())
    hdr = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"iss": TOKEN_ISS, "aud": TOKEN_AUD, "sub": account, "bid": booster_id(),
              "tier": tier, "iat": now, "exp": now + ttl, "jti": secrets.token_hex(8)}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(_secret(), f"{hdr}.{body}".encode(), hashlib.sha256).digest()
    return f"{hdr}.{body}.{_b64(sig)}"


def verify_token(token: str, *, now: Optional[float] = None) -> dict:
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ValueError("malformed_token")
    want = hmac.new(_secret(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(want, _unb64(parts[2])):
        raise ValueError("signature_invalid")
    c = json.loads(_unb64(parts[1]))
    if c.get("aud") != TOKEN_AUD or c.get("bid") != booster_id():
        raise ValueError("audience_or_booster_mismatch")
    if int(c.get("exp", 0)) < (now if now is not None else time.time()):
        raise ValueError("token_expired")
    return c


# --------------------------------------------------------------------------- pairing
_PAIR_LOCK = threading.Lock()
_PAIRS: dict[str, dict] = {}
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"      # no 0/O/1/I/L


def pair_start(now: Optional[float] = None) -> dict:
    now = now if now is not None else time.time()
    with _PAIR_LOCK:
        for c in [c for c, v in _PAIRS.items() if v["exp"] < now]:
            _PAIRS.pop(c, None)
        _PAIRS.clear()                               # one live code at a time
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        code = f"{raw[:4]}-{raw[4:]}"
        _PAIRS[code] = {"exp": now + PAIR_CODE_TTL_S, "tries": 0}
    return {"code": code, "expires_in": PAIR_CODE_TTL_S, "booster_id": booster_id(), "nano_ui": NANO_URL}


def pair_complete(code: str, account_id: str, now: Optional[float] = None) -> dict:
    """Returns {"token", ...} or raises ValueError(reason)."""
    now = now if now is not None else time.time()
    code = (code or "").strip().upper()
    if "-" not in code and len(code) == 8:
        code = f"{code[:4]}-{code[4:]}"
    tier, expired = _licence_tier()
    if tier not in BOOSTER_TIERS:
        raise ValueError("not_entitled")
    claims = _claims()
    sub = str(claims.get("sub") or "")
    account = (account_id or "").strip()
    if sub and account and sub != account:
        raise ValueError("account_mismatch")
    account = sub or account
    if not account:
        raise ValueError("account_required")
    with _PAIR_LOCK:
        if not _PAIRS:
            raise ValueError("no_pairing_in_progress")
        live = next(iter(_PAIRS.values()))
        if live["exp"] < now:
            _PAIRS.clear()
            raise ValueError("code_expired")
        live["tries"] += 1
        if live["tries"] > MAX_CODE_ATTEMPTS:
            _PAIRS.clear()
            raise ValueError("too_many_attempts")
        if code not in _PAIRS:
            raise ValueError("invalid_code")
        _PAIRS.pop(code)                             # single use
    return {"token": mint_token(account, tier, now=now), "token_type": "Bearer", "expires_in": TOKEN_TTL_S,
            "booster_id": booster_id(), "account": account, "tier": tier, "locked": expired, **endpoints()}


def _claims() -> dict:
    try:
        from core import app_context as ctx
        return ctx.STATE.get("license_claims") or {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- guards
def host_allowed(host_header: str) -> bool:
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        h = h.split("]")[0] + "]"
    else:
        h = h.split(":")[0]
    extra = {x.strip().lower() for x in (os.environ.get("VYOMI_BOOSTER_HOSTS") or "").split(",") if x.strip()}
    return h in _LOOPBACK_HOSTS or h in extra or h.endswith(_HOST_SUFFIXES)


def origin_allowed(origin: str) -> bool:
    if not origin:
        return True                                   # non-browser caller (CLI, curl)
    extra = {x.strip() for x in (os.environ.get("VYOMI_BOOSTER_ORIGINS") or "").split(",") if x.strip()}
    return origin in _ORIGIN_EXACT or origin in extra or bool(_LOOPBACK_ORIGIN_RE.match(origin)) \
        or bool(re.match(r"^https://[a-z0-9-]+\.(local|booster)\.vyomi\.cloud$", origin))


_RL_LOCK = threading.Lock()
_RL: dict[str, list[float]] = {}


def rate_limited(key: str, now: Optional[float] = None, limit: int = RATE_LIMIT_PER_MIN) -> bool:
    now = now if now is not None else time.time()
    with _RL_LOCK:
        hits = [t for t in _RL.get(key, []) if now - t < 60]
        hits.append(now)
        _RL[key] = hits
        return len(hits) > limit


def is_loopback_client(host: Optional[str]) -> bool:
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


# --------------------------------------------------------------------------- status
def status() -> dict:
    tier, expired = _licence_tier()
    claims = _claims()
    from core import license_remote as lr
    days = lr.days_until_sub_expiry(claims) if claims else None
    trial = bool(claims.get("trial"))
    try:
        tstat = lr.trial_status(claims=claims, data_dir=_state_dir())
    except Exception:
        tstat = {}
    if trial and tstat.get("days_left") is not None:
        days = tstat["days_left"]
    res = resource_budget()
    u = usage()
    on = booster_mode(tier)
    healthy = on and not expired
    return {
        "booster": on, "booster_id": booster_id(), "headless": on,
        "version": _version(), "tier": tier, "locked": bool(expired and on),
        "trial": trial, "trial_days_left": days if trial else None,
        "sub_days_left": days, "trial_state": tstat.get("state"), "reminder": bool(tstat.get("reminder")),
        "export_blocked": bool(tstat.get("export_blocked")),
        "hostname": socket.gethostname(),
        "resources": {**res, "usage_mb": u,
                      "free_mb": {k: max(0, res["memory_split_mb"][k] - u[k]) for k in u}},
        "health": {"ok": healthy, "state": "locked" if (on and expired) else ("ok" if on else "not-a-booster")},
        "tunnel": _relay_info(), "nano_ui": NANO_URL, **endpoints(),
        "ai": _ai_status(on),
        "llm": _llm_label(),
    }


def _llm_label() -> str:
    try:
        from core import booster_remote_llm as R
        return R.info()["label"]
    except Exception:
        return "llm: local (booster)"


def _ai_status(on: bool) -> Optional[dict]:
    """AI pack summary for the Nano chip: model state + the session token/request ledger (None when not a booster)."""
    if not on:
        return None
    try:
        from core import booster_ai
        return booster_ai.status(recent=5)
    except Exception:
        return None


def _relay_info() -> dict:
    try:
        from core import booster_relay
        return booster_relay.info()
    except Exception:
        return {"bundled": False, "running": False}


def _version() -> str:
    try:
        return open(os.path.join(os.path.dirname(__file__), "..", "VERSION")).read().strip()
    except Exception:
        return os.environ.get("VYOMI_VERSION", "unknown")


# --------------------------------------------------------------------------- routes
def register(app) -> None:
    if booster_mode() and os.environ.get("VYOMI_BOOSTER_NO_RELAY") != "1":
        try:   # the Nano<->host tunnel ships inside the booster (no separate vyomi-tunnel release)
            from core import booster_relay
            booster_relay.start_supervised()
        except Exception:
            pass
    if booster_mode():
        try:   # AI pack: ledger hook, admit the configured models against the AI RAM bucket, point the seam at the local model server
            from core import booster_ai
            booster_ai.install()
            booster_ai.admit_configured()
            booster_ai.point_llm_at_gateway()
        except Exception:
            pass

    def _cors(resp, request):      # CORS headers are applied by HeadlessMiddleware
        return resp

    def _deny(request, status_code, code, msg):
        return _cors(JSONResponse({"error": {"code": code, "message": msg}}, status_code=status_code), request)

    def _guard(request: Request, *, loopback_only: bool = False):
        if not host_allowed(request.headers.get("host", "")):
            return _deny(request, 421, "BadHost", "Host not allowed for the booster API.")
        if not origin_allowed(request.headers.get("origin", "")):
            return _deny(request, 403, "OriginNotAllowed", "Origin not allowed.")
        client = request.client.host if request.client else ""
        if rate_limited(f"{client}:{request.url.path}"):
            r = _deny(request, 429, "RateLimited", "Too many requests.")
            r.headers["Retry-After"] = "60"
            return r
        if loopback_only and not is_loopback_client(client):
            return _deny(request, 403, "LoopbackOnly", "Run this on the booster host (vyomi booster pair).")
        return None

    @app.get("/booster/status", include_in_schema=False)
    def _status(request: Request):
        g = _guard(request)
        return g or _cors(JSONResponse(status()), request)

    @app.post("/booster/pair/start", include_in_schema=False)
    def _start(request: Request):
        # Browsers must not mint codes: only a local process (the CLI) on the booster host.
        g = _guard(request, loopback_only=True)
        if g:
            return g
        if request.headers.get("origin"):
            return _deny(request, 403, "OriginNotAllowed", "Pairing codes are issued by the CLI only.")
        return _cors(JSONResponse(pair_start()), request)

    @app.post("/booster/pair/complete", include_in_schema=False)
    async def _complete(request: Request):
        g = _guard(request)
        if g:
            return g
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            out = pair_complete(str(body.get("code", "")), str(body.get("account_id", "")))
        except ValueError as e:
            code = str(e)
            st = 403 if code in ("not_entitled", "account_mismatch") else (429 if code == "too_many_attempts" else 400)
            return _deny(request, st, code, code.replace("_", " "))
        return _cors(JSONResponse(out), request)

    @app.get("/booster/whoami", include_in_schema=False)
    def _whoami(request: Request):
        g = _guard(request)
        if g:
            return g
        try:
            c = verify_token(request.headers.get("authorization", "")[7:])
        except Exception as e:
            return _deny(request, 401, "InvalidToken", str(e))
        return _cors(JSONResponse({"account": c["sub"], "booster_id": c["bid"], "tier": c["tier"], "exp": c["exp"]}), request)

    @app.get("/booster/ai/status", include_in_schema=False)
    def _ai_status_route(request: Request):
        g = _guard(request)
        if g:
            return g
        from core import booster_ai
        return _cors(JSONResponse(booster_ai.status(recent=20)), request)

    @app.get("/booster/ai/plan", include_in_schema=False)
    def _ai_plan(request: Request):
        # What the boot script should start (admitted models only). Loopback: the Codespace host runs `docker exec ... curl`.
        g = _guard(request, loopback_only=True)
        if g:
            return g
        from core import booster_ai
        return _cors(JSONResponse(booster_ai.plan()), request)

    @app.post("/booster/ai/admit", include_in_schema=False)
    async def _ai_admit(request: Request):
        g = _guard(request, loopback_only=True)
        if g:
            return g
        from core import booster_ai
        try:
            body = await request.json()
        except Exception:
            body = {}
        kind = str(body.get("kind") or "chat")
        kind = kind if kind in ("chat", "embed") else "chat"
        try:
            m = booster_ai.admit(str(body.get("model") or booster_ai.selected()[kind]), kind)
        except booster_ai.ModelAdmissionError as e:
            return _deny(request, 409 if e.code == "ai_memory_exceeded" else 400, e.code, e.message)
        booster_ai.point_llm_at_gateway()
        return _cors(JSONResponse({"admitted": booster_ai._pub(m), "plan": booster_ai.plan()}), request)

    @app.post("/booster/ai/reset-usage", include_in_schema=False)
    def _ai_reset(request: Request):
        g = _guard(request, loopback_only=True)
        if g:
            return g
        from core import booster_ai
        booster_ai.LEDGER.reset()
        return _cors(JSONResponse({"ok": True}), request)

    # ---- remote LLM (spike; inert unless VYOMI_BOOSTER_REMOTE_LLM=1) - loopback only, like /booster/ai/admit ------------
    @app.post("/booster/ai/remote/attach", include_in_schema=False)
    async def _remote_attach(request: Request):
        g = _guard(request, loopback_only=True)
        if g:
            return g
        from core import booster_remote_llm as R
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            return _cors(JSONResponse(R.attach(str(body.get("hub_url") or ""), body.get("token") or None)), request)
        except R.RemoteLLMError as e:
            return _deny(request, e.status, e.code, e.message)

    @app.post("/booster/ai/remote/detach", include_in_schema=False)
    def _remote_detach(request: Request):
        g = _guard(request, loopback_only=True)
        if g:
            return g
        from core import booster_remote_llm as R
        return _cors(JSONResponse(R.detach()), request)

    @app.get("/booster/ai/remote", include_in_schema=False)
    def _remote_info(request: Request):
        g = _guard(request)
        if g:
            return g
        from core import booster_remote_llm as R
        return _cors(JSONResponse(R.info()), request)
