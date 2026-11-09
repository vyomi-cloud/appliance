"""GCP Cloud Storage object enrichments: REAL local extraction on upload, written back as object metadata.

Substrate-independent (stdlib only; Pyodide-loadable). NOT Document AI: no ML classification or form parsing. Rules (per
bucket, optional prefix/suffix) run extractors over the bytes of each newly uploaded object and merge the results into the
object's custom metadata under the `vyomi-enrich-*` keys. Extractors:
  metadata  size, sha256, detected type from magic bytes
  text      text/*, JSON, CSV: chars, words, lines, a 200-char preview; JSON top-level shape; CSV rows + header
  image     PNG/JPEG/GIF/BMP/WebP pixel dimensions (header parse)
  pdf       page count, /Title from the document info dictionary
  ocr       image text via the `tesseract` binary when the host has it (offline appliance); reported as skipped otherwise
State: rules live on the GCS store as `_vyomi_enrich`. Wire (Vyomi extension):
  GET|POST /storage/v1/b/{bucket}/vyomiEnrichmentRules[?ruleId=]      DELETE /storage/v1/b/{bucket}/vyomiEnrichmentRules/{id}
  POST /storage/v1/b/{bucket}/vyomiEnrichmentRules/{id}:run  {"object": name}   (re-run on an existing object)
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import threading
from datetime import datetime, timezone
from urllib.parse import quote

_LOCK = threading.RLock()
ENGINE = "Vyomi local extraction (not Document AI)"
PATH_RE = re.compile(r"^/storage/v1/b/[^/]+/vyomiEnrichmentRules([/:?]|$)")
EXTRACTORS = ("metadata", "text", "image", "pdf", "ocr")
MAX_BYTES = 8 * 1024 * 1024


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gstatus, msg):
        self.status, self.gstatus, self.message = status, gstatus, msg


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _rules(store):
    d = getattr(store, "_vyomi_enrich", None)
    if d is None:
        d = {}
        try:
            store._vyomi_enrich = d
        except Exception:   # noqa: BLE001
            pass
    return d


# ── extractors (pure) ─────────────────────────────────────────────────────────────────────────────
def sniff(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:2] == b"BM":
        return "image/bmp"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:5] == b"%PDF-":
        return "application/pdf"
    if b[:4] == b"PK\x03\x04":
        return "application/zip"
    if b[:2] == b"\x1f\x8b":
        return "application/gzip"
    try:
        b[:4096].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def image_size(b: bytes):
    kind = sniff(b)
    try:
        if kind == "image/png":
            return struct.unpack(">II", b[16:24])
        if kind == "image/gif":
            return struct.unpack("<HH", b[6:10])
        if kind == "image/bmp":
            w, h = struct.unpack("<ii", b[18:26])
            return w, abs(h)
        if kind == "image/webp":
            if b[12:16] == b"VP8X":
                return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
            if b[12:16] == b"VP8 ":
                w, h = struct.unpack("<HH", b[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if b[12:16] == b"VP8L":
                v = int.from_bytes(b[21:25], "little")
                return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if kind == "image/jpeg":
            i = 2
            while i + 9 < len(b):
                if b[i] != 0xFF:
                    i += 1
                    continue
                m = b[i + 1]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", b[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    except struct.error:
        return None
    return None


def text_facts(b: bytes, content_type: str, name: str) -> dict:
    s = b.decode("utf-8", "replace")
    out = {"chars": str(len(s)), "words": str(len(s.split())), "lines": str(s.count("\n") + (1 if s and not s.endswith("\n") else 0)),
           "preview": " ".join(s[:200].split())}
    low = name.lower()
    if low.endswith(".json") or "json" in content_type:
        try:
            v = json.loads(s)
            out["json"] = "object with %d keys: %s" % (len(v), ", ".join(list(v)[:10])) if isinstance(v, dict) else \
                ("array of %d items" % len(v) if isinstance(v, list) else type(v).__name__)
        except ValueError:
            out["json"] = "invalid JSON"
    elif low.endswith(".csv") or "csv" in content_type:
        rows = [r for r in s.splitlines() if r.strip()]
        out["csvRows"] = str(max(0, len(rows) - 1))
        out["csvHeader"] = rows[0][:200] if rows else ""
    return out


def pdf_facts(b: bytes) -> dict:
    out = {"pages": str(len(re.findall(rb"/Type\s*/Page(?![s\w])", b)))}
    m = re.search(rb"/Title\s*\(([^)]{1,200})\)", b)
    if m:
        out["title"] = m.group(1).decode("latin-1", "replace")
    return out


def ocr_text(b: bytes):
    exe = shutil.which("tesseract")
    if not exe:
        return None
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".img") as f:
        f.write(b)
        f.flush()
        r = subprocess.run([exe, f.name, "stdout"], capture_output=True, text=True, timeout=60)
    return " ".join(r.stdout.split())[:500] if r.returncode == 0 else None


def extract(name: str, content_type: str, data: bytes, extractors) -> dict:
    """{vyomi-enrich-*: str} metadata for one object."""
    out = {"vyomi-enrich-engine": ENGINE, "vyomi-enrich-time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    kind = sniff(data)
    if "metadata" in extractors:
        out["vyomi-enrich-size"] = str(len(data))
        out["vyomi-enrich-sha256"] = hashlib.sha256(data).hexdigest()
        out["vyomi-enrich-detected-type"] = kind
    if "text" in extractors and (kind == "text/plain" or content_type.startswith("text/") or "json" in content_type):
        for k, v in text_facts(data, content_type or "", name).items():
            out["vyomi-enrich-text-" + k] = v
    if "image" in extractors and kind.startswith("image/"):
        wh = image_size(data)
        if wh:
            out["vyomi-enrich-image-width"], out["vyomi-enrich-image-height"] = str(wh[0]), str(wh[1])
    if "pdf" in extractors and kind == "application/pdf":
        for k, v in pdf_facts(data).items():
            out["vyomi-enrich-pdf-" + k] = v
    if "ocr" in extractors and kind.startswith("image/"):
        try:
            t = ocr_text(data)
        except Exception:   # noqa: BLE001
            t = None
        out["vyomi-enrich-ocr-text" if t is not None else "vyomi-enrich-ocr-status"] = t if t is not None else "skipped: no tesseract on this host"
    out["vyomi-enrich-status"] = "done"
    return out


# ── rules + hook ───────────────────────────────────────────────────────────────────────────────────
def _matches(rule, name):
    return rule["enabled"] and name.startswith(rule["prefix"]) and name.endswith(rule["suffix"])


def apply_to_object(router, bucket, name, only_rule=None):
    """Run the matching rules over one stored object and write the metadata back. Returns the metadata written (or None)."""
    from core import gcp_storage_core as gcs
    store = router.gcs
    rules = [r for r in _rules(store).values() if r["bucket"] == bucket and (only_rule is None or r["id"] == only_rule)]
    rules = [r for r in rules if _matches(r, name)]
    if not rules:
        return None
    obj = "/storage/v1/b/%s/o/%s" % (bucket, quote(name, safe=""))
    meta_r = gcs.dispatch(store, "GET", obj, {}, {}, b"")
    if meta_r.status != 200:
        return None
    meta = json.loads(meta_r.body or b"{}")
    data_r = gcs.dispatch(store, "GET", obj, {"alt": "media"}, {}, b"")
    data = bytes(data_r.body or b"")[:MAX_BYTES] if data_r.status == 200 else b""
    exs = set()
    for r in rules:
        exs |= set(r["extractors"])
    written = extract(name, meta.get("contentType") or "", data, exs)
    written["vyomi-enrich-rules"] = ",".join(r["id"] for r in rules)
    merged = {**(meta.get("metadata") or {}), **written}
    gcs.dispatch(store, "PATCH", obj, {}, {}, json.dumps({"metadata": merged}).encode())
    for r in rules:
        r["processed"] = r.get("processed", 0) + 1
    return written


def after_upload(router, svc, method, path, query, r):
    """Router hook: a successful object upload (POST/PUT to the media/multipart/resumable-complete endpoint)."""
    try:
        if svc != "gcp-gcs" or method not in ("POST", "PUT") or r.status >= 300 or not _rules(router.gcs):
            return
        base = path.split("?", 1)[0]
        m = re.match(r"^/(?:upload/)?storage/v1/b/([^/]+)/o/?$", base)
        if not m:
            return
        meta = json.loads((r.body or b"").decode("utf-8")) if (r.body or b"")[:1] == b"{" else {}
        name = meta.get("name") or (query or {}).get("name") or ""
        if isinstance(name, list):
            name = name[0]
        if name:
            apply_to_object(router, m.group(1), name)
    except Exception:   # noqa: BLE001 - enrichment must never fail an upload
        pass


def _rule_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def dispatch(router, method, path, query=None, headers=None, body=b""):
    query, method = query or {}, method.upper()
    try:
        p = path.split("?", 1)[0].strip("/").split("/")     # storage v1 b {bucket} vyomiEnrichmentRules [id[:run]]
        bucket, rest = p[3], p[5:]
        verb = ""
        if rest and ":" in rest[-1]:
            rest[-1], verb = rest[-1].rsplit(":", 1)
        store = router.gcs
        if not store.bucket_exists(bucket):
            raise _E(404, "NOT_FOUND", "The specified bucket does not exist.")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            raise _bad("Invalid JSON payload received.")
        with _LOCK:
            rules = _rules(store)
            if not rest:
                if method == "GET":
                    return Resp(200, {"items": [_rule_view(r) for r in rules.values() if r["bucket"] == bucket], "engine": ENGINE})
                if method == "POST":
                    rid = str(query.get("ruleId") or payload.get("id") or "").strip()
                    if not re.match(r"^[a-z][-a-z0-9]{0,62}$", rid):
                        raise _bad("ruleId must match [a-z][-a-z0-9]{0,62}.")
                    if rid in rules and rules[rid]["bucket"] == bucket:
                        raise _E(409, "ALREADY_EXISTS", "Rule %s already exists." % rid)
                    exs = payload.get("extractors") or ["metadata", "text", "image", "pdf"]
                    if not isinstance(exs, list) or not exs or any(x not in EXTRACTORS for x in exs):
                        raise _bad("extractors must be a non-empty list of: %s." % ", ".join(EXTRACTORS))
                    rule = {"id": rid, "bucket": bucket, "prefix": str(payload.get("prefix") or ""), "suffix": str(payload.get("suffix") or ""),
                            "extractors": exs, "enabled": payload.get("enabled", True) is not False, "processed": 0,
                            "engine": ENGINE, "createTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
                    rules[rid] = rule
                    return Resp(200, _rule_view(rule))
            elif len(rest) == 1:
                rule = rules.get(rest[0])
                if not rule or rule["bucket"] != bucket:
                    raise _E(404, "NOT_FOUND", "Enrichment rule %s was not found." % rest[0])
                if verb == "run" and method == "POST":
                    name = str(payload.get("object") or "")
                    if not name:
                        raise _bad("object is required.")
                    out = apply_to_object(router, bucket, name, only_rule=rest[0])
                    if out is None:
                        raise _E(404, "NOT_FOUND", "Object %s not found or not matched by the rule." % name)
                    return Resp(200, {"object": name, "metadata": out})
                if not verb and method == "GET":
                    return Resp(200, _rule_view(rule))
                if not verb and method == "DELETE":
                    del rules[rest[0]]
                    return Resp(200, {})
            raise _E(405, "UNIMPLEMENTED", "Unknown path or method: %s %s" % (method, path))
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gstatus}})
