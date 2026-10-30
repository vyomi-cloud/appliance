"""GCS config-only bucket sub-resources (v4 DEPTH pass): CORS, static website config
and requester-pays billing round-trip through buckets.insert/patch exactly as a real
client (google-cloud-storage, gsutil) sets them. Vyomi's wire layer does not add
Access-Control-* response headers, run the separate per-bucket static-website HTTP
host, or model a distinct "requester" identity to bill — these are stored and
returned, not enforced (see core/capabilities/gcp/storage.json: config_only).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_config_sections_core.py
"""
import json

try:
    from core.object_store import InMemoryObjectStore
    from core import gcp_storage_core as gcs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import gcp_storage_core as gcs  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def _call(st, m, p, q=None, body=None, ct="application/json"):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    return gcs.dispatch(st, m, p, q or {}, {"content-type": ct}, raw)


def run() -> int:
    st = InMemoryObjectStore()
    cors_rule = [{"origin": ["https://example.com"], "method": ["GET"], "responseHeader": ["Content-Type"], "maxAgeSeconds": 3600}]
    b = _j(_call(st, "POST", "/storage/v1/b", {"project": "p"}, {
        "name": "cfg2", "cors": cors_rule, "website": {"mainPageSuffix": "index.html", "notFoundPage": "404.html"},
        "billing": {"requesterPays": True},
    }))
    _check("cors kept on insert", b["cors"] == cors_rule)
    _check("website config kept on insert", b["website"] == {"mainPageSuffix": "index.html", "notFoundPage": "404.html"})
    _check("requester pays kept on insert", b["billing"]["requesterPays"] is True)

    g = _j(_call(st, "GET", "/storage/v1/b/cfg2"))
    _check("get round-trips cors/website/billing", g["cors"] == cors_rule and g["website"]["mainPageSuffix"] == "index.html" and g["billing"]["requesterPays"] is True)

    p = _j(_call(st, "PATCH", "/storage/v1/b/cfg2", body={"website": {"mainPageSuffix": "home.html", "notFoundPage": "oops.html"}}))
    _check("patch replaces website config", p["website"] == {"mainPageSuffix": "home.html", "notFoundPage": "oops.html"})

    cl = _j(_call(st, "PATCH", "/storage/v1/b/cfg2", body={"cors": None}))
    _check("patch null clears cors", "cors" not in cl)

    bad = _call(st, "PATCH", "/storage/v1/b/cfg2", body={"cors": "not-a-list"})
    _check("invalid cors shape rejected", bad.status == 400)

    print("\nGCS config-only sub-resources (cors/website/billing) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
