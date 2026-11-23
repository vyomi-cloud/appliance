"""Lazy per-service IAM catalog loader (pure Python, Pyodide-safe: no os/fastapi/socket at import).

Catalogs (core/iam_catalog/<cloud>/<service>.json, ~4 MB for all three clouds) are NEVER loaded at boot. A host installs a *reader*:

    set_reader(fn)          fn(relpath) -> str | bytes | None     relpath like "aws/s3.json"

  * Mesh / tests: `filesystem_reader(root)` (reads core/iam_catalog from disk, done lazily on first load of a service).
  * Nano: Python cannot await fetch(), so the page/worker (wasm/nano-iam-hook.js) prefetches a service's JSON from the bundle (HTTP cache +
    IndexedDB copy) and hands it over with `preload(cloud, service, text)`; the installed reader is `memory_reader` over that dict.
    A load for a service nobody has preloaded raises `CatalogUnavailable(cloud, service)`; the Nano hook catches it, prefetches, retries once.

`load(cloud, service)` -> parsed dict (cached; the cache is per process and bounded by the in-scope service count)."""
from __future__ import annotations

import json

CLOUDS = ("aws", "gcp", "azure")


class CatalogUnavailable(LookupError):
    """The reader has no bytes for this (cloud, service) yet. `.need` = [cloud, service] for the host to fetch."""

    def __init__(self, cloud, service):
        super().__init__(f"IAM catalog {cloud}/{service} not available")
        self.cloud, self.service, self.need = cloud, service, [cloud, service]


_reader = None
_texts = {}      # relpath -> raw text (what memory_reader serves; Nano's preload target)
_cache = {}      # (cloud, service) -> parsed catalog


def relpath(cloud, service):
    if cloud not in CLOUDS:
        raise ValueError(f"unknown cloud {cloud!r}")
    s = str(service)
    if not s or "/" in s or "\\" in s or s.startswith("."):   # service ids are file stems: never a path
        raise ValueError(f"bad service id {service!r}")
    return f"{cloud}/{s}.json"


def set_reader(fn):
    global _reader
    _reader = fn


def memory_reader(rel):
    return _texts.get(rel)


def filesystem_reader(root):
    """Reader over a catalog directory (Mesh). `os` is imported lazily so importing this module stays os-free."""
    def read(rel):
        import os
        p = os.path.join(root, *rel.split("/"))
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            return None
    return read


def preload(cloud, service, text):
    """Hand over the raw JSON of one service catalog (Nano: after a fetch / IndexedDB hit). Replaces any cached parse."""
    _texts[relpath(cloud, service)] = text
    _cache.pop((cloud, service), None)


def loaded():
    return sorted(f"{c}/{s}" for (c, s) in _cache)


def load(cloud, service):
    key = (cloud, service)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    rel = relpath(cloud, service)
    raw = (_reader or memory_reader)(rel)
    if raw is None:
        raise CatalogUnavailable(cloud, service)
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    cat = json.loads(raw)
    _cache[key] = cat
    return cat


def reset():
    """Drop parsed catalogs and preloaded text (tests; Nano 'free memory')."""
    _cache.clear()
    _texts.clear()
