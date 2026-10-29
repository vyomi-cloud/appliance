"""Automatic issue reporting — scrubber, classifier, fingerprint and reporter.

Pure Python (no network on import) so the SAME code runs in the offline
appliance, in sandboxes (the same appliance) and in Nano (Pyodide); the copy in
``wasm/core/`` is byte-identical.

What leaves the machine (and nothing else): cloud, service, action, HTTP status,
error code, a cleaned error message, the top 5 stack frames as ``file:function``,
the Vyomi version, the surface (nano / offline / sandbox) and the tier. Request
and response bodies, headers, secrets, keys, tokens, account / project /
subscription ids, IPs and emails are stripped; resource names are hashed.

Mode (who files it) is decided by the user's consent, never by this module:
``named`` -> the portal files under the user's GitHub App token, ``anonymous`` ->
the Vyomi bot. Anonymous reports carry no user-identifying field at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Callable, Optional

MODES = ("named", "anonymous")
SURFACES = ("nano", "offline", "sandbox")
MAX_FRAMES = 5
MAX_MESSAGE = 300

# ── Scrubbing ─────────────────────────────────────────────────────────

_RES = "<res:{}>"          # hashed resource-name token
_RES_RE = re.compile(r"<res:[0-9a-f]{8}>")


def hash_name(name: str) -> str:
    """Stable, non-reversible token for a resource name (same name -> same token)."""
    h = hashlib.sha256(("vyomi-res:" + str(name)).encode("utf-8")).hexdigest()[:8]
    return _RES.format(h)


_SECRET_KV = re.compile(
    r"(?i)\b([a-z0-9_.\-]*(?:secret|token|password|passwd|pwd|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credential|authorization|signature|sig|sas)[a-z0-9_.\-]*)\s*([=:])\s*"
    r"(?:bearer\s+|basic\s+)?(\"[^\"]*\"|'[^']*'|[^\s,;&\"')]+)")
_PEM = re.compile(r"-----BEGIN [A-Z ]+-----.*?(?:-----END [A-Z ]+-----|$)", re.S)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}")
_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AGPA|ANPA)[A-Z0-9]{12,}\b")
_GH_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_GOOGLE_KEY = re.compile(r"\b(?:AIza[0-9A-Za-z_\-]{30,}|ya29\.[0-9A-Za-z_\-]{20,})")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_URL_QUERY = re.compile(r"(\bhttps?://[^\s?#'\"<>]+)\?[^\s#'\"<>]*")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")
_IPV6 = re.compile(r"(?i)(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}(?![\w:])|(?<![\w:])::(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{1,4}\b")
_GUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_ARN = re.compile(r"\barn:(aws[a-z\-]*):([a-z0-9\-]*):([a-z0-9\-]*):(\d{12})?:([^\s,;\"')]+)")
_ACCOUNT = re.compile(r"(?<![\w.\-])\d{12}(?![\w\-])")
_GCP_PROJECT = re.compile(r"(?i)\b(projects|folders|organizations)/(?!<)([^/\s\"',;)]+)")
_GCP_RES = re.compile(r"(?i)\b(buckets|instances|topics|subscriptions|secrets|keyRings|cryptoKeys|"
                      r"clusters|services|functions|jobs|datasets|tables|databases|queues|"
                      r"serviceAccounts|networks|disks|repositories)"
                      r"/(?!<)([A-Za-z0-9_.@:\-]+)")
_AZ_SUB = re.compile(r"(?i)/subscriptions/[^/\s]+")
_AZ_RG = re.compile(r"(?i)/resourceGroups/[^/\s]+")
_AZ_PROV = re.compile(r"(?i)(/providers/[A-Za-z0-9.]+)((?:/[A-Za-z0-9]+/[^/\s\"',;)?]+)+)")
_QUOTED = re.compile(r"(['\"`])([^'\"`\n]{1,120})\1")
_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_\-+/=]*\d)(?=[A-Za-z0-9_\-+/=]*[A-Za-z])[A-Za-z0-9_\-+/=]{32,}\b")
_HEX_LONG = re.compile(r"\b[0-9a-fA-F]{24,}\b")
_PATH = re.compile(r"(?<![\w<])(?:/(?:home|Users|root|tmp|var|opt|app|data|usr|workspace)[^\s:\"')]*)|(?<![\w])[A-Za-z]:\\[^\s:\"')]+")


def _hash_arn(m: "re.Match") -> str:
    part, svc, region, _acct, rest = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    bits = re.split(r"([/:])", rest, maxsplit=2)
    # keep the resource TYPE (first segment) when present, hash the name
    if len(bits) >= 3:
        tail = bits[0] + bits[1] + hash_name(bits[2])
    else:
        tail = hash_name(rest)
    return f"arn:{part}:{svc}:{region}:<acct>:{tail}"


def _hash_az(m: "re.Match") -> str:
    prov, rest = m.group(1), m.group(2)
    segs = rest.strip("/").split("/")
    out = []
    for i in range(0, len(segs) - 1, 2):
        out += [segs[i], hash_name(segs[i + 1])]
    return prov + "/" + "/".join(out)


def scrub_text(s: Any, limit: int = MAX_MESSAGE) -> str:
    """Return ``s`` with secrets, ids, IPs, emails and resource names removed."""
    if s is None:
        return ""
    t = str(s)
    t = _PEM.sub("<key>", t)
    t = _JWT.sub("<token>", t)
    t = _URL_USERINFO.sub(r"\1<cred>@", t)
    t = _URL_QUERY.sub(r"\1?<q>", t)
    t = _SECRET_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", t)
    t = _BEARER.sub(r"\1 <token>", t)
    t = _AWS_KEY.sub("<key>", t)
    t = _GH_TOKEN.sub("<token>", t)
    t = _GOOGLE_KEY.sub("<token>", t)
    t = _EMAIL.sub("<email>", t)
    t = _ARN.sub(_hash_arn, t)
    t = _AZ_SUB.sub("/subscriptions/<sub>", t)
    t = _AZ_RG.sub(lambda m: "/resourceGroups/" + hash_name(m.group(0).split("/")[-1]), t)
    t = _AZ_PROV.sub(_hash_az, t)
    t = _GUID.sub("<id>", t)
    t = _GCP_PROJECT.sub(lambda m: f"{m.group(1)}/<{m.group(1)[:-1] if m.group(1)!='projects' else 'project'}>", t)
    t = _GCP_RES.sub(lambda m: f"{m.group(1)}/{hash_name(m.group(2))}", t)
    t = _IPV4.sub("<ip>", t)
    t = _IPV6.sub("<ip>", t)
    t = _ACCOUNT.sub("<acct>", t)
    t = _LONG_TOKEN.sub("<token>", t)
    t = _HEX_LONG.sub("<id>", t)
    t = _PATH.sub("<path>", t)
    # quoted values are almost always user-chosen names
    t = _QUOTED.sub(lambda m: m.group(0) if (m.group(2).startswith("<") or _RES_RE.search(m.group(2))
                                              or m.group(2).lower() in _KEEP_WORDS)
                    else m.group(1) + hash_name(m.group(2)) + m.group(1), t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


# Quoted words that are API vocabulary (parameter / field names), not user data.
_KEEP_WORDS = {"name", "id", "arn", "region", "type", "status", "key", "value", "tags", "none", "null",
               "true", "false", "str", "int", "list", "dict", "bytes", "code", "message", "detail"}


def normalise_message(s: str) -> str:
    """Message with every variable part collapsed, for fingerprinting."""
    t = _RES_RE.sub("<res>", scrub_text(s, limit=2000))
    t = re.sub(r"\d+", "<n>", t)
    return t.lower()[:200]


def clean_frame(frame: Any) -> str:
    """``file:function`` only — never a path, line number or source line."""
    if isinstance(frame, (list, tuple)) and len(frame) >= 2:
        f, fn = str(frame[0]), str(frame[1])
    else:
        f, _, fn = str(frame).partition(":")
    f = re.split(r"[\\/]", f.strip())[-1]
    fn = re.sub(r"[^A-Za-z0-9_<>.$\-]", "", fn.strip().split("(")[0]) or "?"
    f = re.sub(r"[^A-Za-z0-9_.\-]", "", f) or "?"
    return f"{f}:{fn}"


def frames_from_traceback(tb) -> list:
    """Top frames (innermost last, cut to MAX_FRAMES, innermost kept) from a traceback object."""
    import traceback
    try:
        fr = traceback.extract_tb(tb)
    except Exception:
        return []
    return [clean_frame((x.filename, x.name)) for x in fr][-MAX_FRAMES:]


# ── Classification ────────────────────────────────────────────────────

_TIER_CODE = re.compile(r"(?i)^tier[_\-]|tier.?(locked|limit|required|denied)|upgrade.?required")


def should_report(status: Optional[int] = None, code: Optional[str] = None, *, kind: str = "http",
                  cancelled: bool = False, message: str = "") -> bool:
    """True only for failures that are Vyomi's bug.

    Reported: 5xx, unhandled exceptions, failed console actions, console JS errors.
    Never: tier locks (403 tier_*), 4xx the user caused, cancelled requests.
    """
    if cancelled:
        return False
    if code and _TIER_CODE.search(str(code)):
        return False
    if message and _TIER_CODE.search(str(message)[:80]) and status in (402, 403):
        return False
    if kind in ("exception", "js-error"):
        return True
    if kind == "console-action":
        return not (status and 400 <= int(status) < 500)
    if status is None:
        return False
    return int(status) >= 500


# ── Route -> (cloud, service, action) ─────────────────────────────────

_AWS_TARGET_SVC = {"dynamodb": "dynamodb", "secretsmanager": "secretsmanager", "trent": "kms",
                   "awskms": "kms", "amazonssm": "ssm", "logs": "logs", "awsevents": "events",
                   "amazonsqs": "sqs", "sqs": "sqs", "amazonsns": "sns"}
_AZ_NS = {"microsoft.compute": "compute", "microsoft.storage": "storage", "microsoft.network": "network",
          "microsoft.keyvault": "keyvault", "microsoft.sql": "sql", "microsoft.web": "web"}


def derive_route(method: str, path: str, headers: Optional[dict] = None, query: str = "") -> tuple:
    """Best-effort (cloud, service, action) from a request line. Never raises."""
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    p = path or "/"
    method = (method or "GET").upper()
    try:
        tgt = h.get("x-amz-target")
        if tgt:
            svc, _, op = tgt.partition(".")
            svc = svc.split("_")[0].lower()
            return "aws", _AWS_TARGET_SVC.get(svc, svc), op or method
        m = re.match(r"^/api/(aws|gcp|azure)/([^/]+)(?:/(.*))?$", p)
        if m:
            sub = (m.group(3) or "").split("/")[0]
            return m.group(1), m.group(2), f"{method} {sub}".strip() if sub else method
        m = re.match(r"^/api/([a-z0-9\-]+)(?:/|$)", p)
        if m and m.group(1) in ("s3", "ec2", "iam", "sqs", "sns", "lambda", "rds", "dynamodb", "vpc", "elbv2"):
            return "aws", m.group(1), method
        am = re.search(r"(?:^|&)Action=([A-Za-z0-9]+)", query or "")
        if am:
            return "aws", "query", am.group(1)
        m = re.match(r"^/subscriptions/[^/]+(?:/resourceGroups/[^/]+)?/providers/([^/]+)/([^/]+)", p, re.I)
        if m:
            ns = m.group(1).lower()
            return "azure", _AZ_NS.get(ns, ns.replace("microsoft.", "")), f"{method} {m.group(2)}"
        m = re.match(r"^/(?:storage|compute|bigquery|pubsub|v1|v1beta1|v2)/", p) or p.startswith("/gcp") \
            or "googleapis" in h.get("host", "")
        if m:
            seg = [x for x in p.split("/") if x]
            return "gcp", (seg[0] if seg else "gcp"), method
        if p.startswith("/storage/v1") or p.startswith("/upload/storage"):
            return "gcp", "storage", method
        # S3-style: bucket paths
        if "amazonaws" in h.get("host", "") or "authorization" in h and "AWS4-HMAC" in h.get("authorization", ""):
            return "aws", "s3", method
    except Exception:
        pass
    return "unknown", "platform", method


# ── Report + fingerprint ──────────────────────────────────────────────

def build_report(*, cloud: str, service: str, action: str, status: Optional[int] = None,
                 code: str = "", message: str = "", frames=None, surface: str = "offline",
                 tier: str = "free", version: str = "", kind: str = "http") -> dict:
    """The one object that may leave the machine. Every free-text field is scrubbed."""
    cloud = (cloud or "unknown").lower()
    cloud = cloud if cloud in ("aws", "gcp", "azure") else "unknown"
    return {
        "cloud": cloud,
        "service": re.sub(r"[^a-z0-9\-_.]", "", str(service or "platform").lower())[:40] or "platform",
        "action": scrub_text(action, 80),
        "status": int(status) if status else None,
        "code": re.sub(r"[^A-Za-z0-9_.\-:]", "", str(code or ""))[:80],
        "message": scrub_text(message),
        "frames": [clean_frame(f) for f in (frames or [])][-MAX_FRAMES:],
        "version": re.sub(r"[^A-Za-z0-9.\-+]", "", str(version or ""))[:20],
        "surface": surface if surface in SURFACES else "offline",
        "tier": re.sub(r"[^a-z0-9_\-]", "", str(tier or "free").lower())[:20] or "free",
        "kind": kind if kind in ("http", "exception", "console-action", "js-error") else "http",
    }


def fingerprint(report: dict) -> str:
    """hash(cloud, service, action, status, error code, normalised message, top frames)."""
    parts = [report.get("cloud"), report.get("service"), re.sub(r"<res:[0-9a-f]{8}>", "<res>", report.get("action") or ""),
             report.get("status"), report.get("code"), normalise_message(report.get("message") or ""),
             "|".join(report.get("frames") or [])]
    return hashlib.sha256("\x1f".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:16]


# ── Reporter (settings, dedupe, queue, send) ──────────────────────────

def telemetry_disabled() -> bool:
    return (os.environ.get("VYOMI_NO_TELEMETRY") or "").strip().lower() in ("1", "true", "yes")


class IssueReporter:
    """Decides, scrubs, dedupes and hands reports to a sender.

    ``sender(payload: dict) -> bool`` performs the actual POST (portal endpoint);
    False / an exception keeps the report queued for a later ``flush``. State
    (``mode``: "named" | "anonymous" | None = not yet asked) is held in
    ``settings`` and persisted through ``persist`` when given.
    """

    def __init__(self, sender: Optional[Callable[[dict], bool]] = None, *, surface: str = "offline",
                 version: str = "", tier_fn: Callable[[], str] = lambda: "free",
                 settings: Optional[dict] = None, persist: Optional[Callable[[dict], None]] = None,
                 queue_max: int = 50, sync: bool = False):
        self.sender = sender
        self.surface = surface
        self.version = version
        self.tier_fn = tier_fn
        self.settings = settings if settings is not None else {}
        self._persist = persist
        self.queue_max = queue_max
        self.sync = sync
        self._seen: set = set()
        self._queue: list = list(self.settings.get("queue") or [])
        self._lock = threading.Lock()

    # settings -------------------------------------------------------
    @property
    def mode(self) -> Optional[str]:
        m = self.settings.get("mode")
        return m if m in MODES else None

    @property
    def consent_asked(self) -> bool:
        return self.mode is not None

    def set_mode(self, mode: str) -> dict:
        if mode not in MODES:
            raise ValueError("mode must be 'named' or 'anonymous'")
        self.settings["mode"] = mode
        self.settings["decided_at"] = int(time.time())
        self._save()
        return self.public_settings()

    def public_settings(self) -> dict:
        return {"mode": self.mode, "consent_asked": self.consent_asked,
                "enabled": not telemetry_disabled(), "queued": len(self._queue)}

    def _save(self) -> None:
        self.settings["queue"] = list(self._queue)
        if self._persist:
            try:
                self._persist(self.settings)
            except Exception:
                pass

    # reporting ------------------------------------------------------
    def report(self, *, cloud: str, service: str, action: str, status: Optional[int] = None,
               code: str = "", message: str = "", frames=None, kind: str = "http",
               cancelled: bool = False) -> Optional[dict]:
        """Scrub + queue + send one failure. Returns the payload, or None when not reportable."""
        if telemetry_disabled():
            return None
        if not should_report(status, code, kind=kind, cancelled=cancelled, message=message):
            return None
        rep = build_report(cloud=cloud, service=service, action=action, status=status, code=code,
                           message=message, frames=frames, surface=self.surface,
                           tier=self.tier_fn(), version=self.version, kind=kind)
        fp = fingerprint(rep)
        with self._lock:
            if fp in self._seen:          # one send per fingerprint per process; the portal adds the +1s
                return None
            self._seen.add(fp)
        payload = {"fingerprint": fp, "mode": self.mode or "anonymous", "report": rep}
        if self.sync:
            self._deliver(payload)
        else:
            threading.Thread(target=self._deliver, args=(payload,), daemon=True).start()
        return payload

    def _deliver(self, payload: dict) -> bool:
        ok = False
        if self.sender:
            try:
                ok = bool(self.sender(payload))
            except Exception:
                ok = False
        if not ok:
            with self._lock:
                if len(self._queue) < self.queue_max:
                    self._queue.append(payload)
                self._save()
        return ok

    def flush(self) -> int:
        """Retry queued reports (called on a timer / after reconnect). Returns how many were sent."""
        if telemetry_disabled() or not self.sender:
            return 0
        with self._lock:
            pending, self._queue = self._queue, []
        sent = 0
        for p in pending:
            try:
                if self.sender(p):
                    sent += 1
                    continue
            except Exception:
                pass
            with self._lock:
                self._queue.append(p)
        with self._lock:
            self._save()
        return sent


def http_sender(base_url: str, token_fn: Callable[[], str] = lambda: "", timeout: float = 8.0) -> Callable[[dict], bool]:
    """Sender that POSTs to ``<base_url>/api/issues/report`` with the license as bearer."""
    import urllib.request

    def send(payload: dict) -> bool:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        tok = token_fn()
        if tok:
            headers["Authorization"] = "Bearer " + tok
        req = urllib.request.Request(base_url.rstrip("/") + "/api/issues/report", data=body,
                                     method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return 200 <= r.status < 300
        except Exception:
            return False
    return send
