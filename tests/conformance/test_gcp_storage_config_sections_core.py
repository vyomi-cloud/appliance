"""GCS bucket sub-resources (v4 DEPTH / gap-sweep passes): CORS, static website config
and requester-pays billing round-trip through buckets.insert/patch exactly as a real
client (google-cloud-storage, gsutil) sets them, AND static-website serving + the
requester-pays UserProjectMissing gate are now enforced for real — see
core/capabilities/gcp/storage.json: static-website / requester-pays = limited.

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

    # requester-pays: object data-plane calls on cfg2 (billing.requesterPays=True from
    # insert, above) now require a userProject or get the real UserProjectMissing 400.
    no_proj = _call(st, "GET", "/storage/v1/b/cfg2/o")
    _check("requester pays blocks object list without userProject", no_proj.status == 400 and b"UserProjectMissing" in no_proj.body)
    with_proj = _call(st, "GET", "/storage/v1/b/cfg2/o", {"userProject": "some-other-project"})
    _check("requester pays allows object list with userProject", with_proj.status == 200)
    _check("requester pays tracks usage by project", st.buckets["cfg2"]["_requesterPaysUsage"]["some-other-project"] == 1)
    # A bucket with requesterPays off is never gated.
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "cfg3"})
    ungated = _call(st, "GET", "/storage/v1/b/cfg3/o")
    _check("requester pays off is never gated", ungated.status == 200)

    # static-website: serving on the simulated public host actually returns bytes.
    _call(st, "PATCH", "/storage/v1/b/cfg3", body={"website": {"mainPageSuffix": "index.html", "notFoundPage": "404.html"}})
    gcs.dispatch(st, "POST", "/upload/storage/v1/b/cfg3/o", {"uploadType": "media", "name": "index.html"}, {"content-type": "text/html"}, b"<h1>home</h1>")
    gcs.dispatch(st, "POST", "/upload/storage/v1/b/cfg3/o", {"uploadType": "media", "name": "404.html"}, {"content-type": "text/html"}, b"<h1>missing</h1>")
    home = gcs.dispatch(st, "GET", "/storage/website/cfg3/", {}, {}, b"")
    _check("website serves the main page suffix", home.status == 200 and home.body == b"<h1>home</h1>")
    home2 = gcs.dispatch(st, "GET", "/storage/website/cfg3/index.html", {}, {}, b"")
    _check("website serves an explicit object name", home2.status == 200 and home2.body == b"<h1>home</h1>")
    miss = gcs.dispatch(st, "GET", "/storage/website/cfg3/nope.html", {}, {}, b"")
    _check("website falls back to the 404 page with a real 404 status", miss.status == 404 and miss.body == b"<h1>missing</h1>")
    no_cfg = gcs.dispatch(st, "GET", "/storage/website/cfg2/", {}, {}, b"")
    _check("website serving 404s when no website config is set", no_cfg.status == 404)

    print("\nGCS bucket sub-resources (cors/website/billing) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
