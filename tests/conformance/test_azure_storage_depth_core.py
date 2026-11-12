"""Azure Blob Storage DEPTH conformance — CORS preflight, lifecycle tiering/expiry and
static website serving, all ENFORCED by core/azure_blob_core.py reading the storage
account's ARM-stored config (the same `blobServices/default` / `managementPolicies/
default` records core/azure_arm_core.py's generic passthrough already persists).

core/aws_wire_router.py passes `arm_state=self.az_arm.state` into azure_blob_core.dispatch
for every Blob call; this test builds that dict by hand to stay a pure core-to-core test
with no HTTP server.

Run on host:    python3 tests/conformance/test_azure_storage_depth_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
from datetime import datetime, timedelta, timezone

try:
    from core import azure_blob_core as az
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_blob_core as az  # type: ignore

ACCT = "uicstorage"
RID = f"/subscriptions/sub1/resourcegroups/uic-rg/providers/microsoft.storage/storageaccounts/{ACCT}"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _http_date(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def run() -> int:
    # Every request below is unauthenticated (no SharedKey header), so it lands on the
    # DEFAULT namespace (acct="") — same as test_azure_blob_core.py's /devstoreaccount1
    # cases. `arm_state`'s account-scoped lookup falls back to a loose match for that
    # namespace (see _arm_properties), so the ARM record's account name doesn't have to
    # line up with a real SharedKey-scoped account for this test.
    st = az.AzureBlobStore()
    arm_state = {}

    # ── CORS preflight ──────────────────────────────────────────────────────
    st.create_container("data")
    no_cors = az.dispatch(st, "OPTIONS", "/data", {}, {"origin": "https://example.com",
                          "access-control-request-method": "GET"}, b"", arm_state=arm_state)
    _check("preflight denied with no CORS rules configured", no_cors.status == 403)
    _check("preflight denied error code", no_cors.headers.get("x-ms-error-code") == "CorsPreflightFailure")

    arm_state[RID + "/blobservices/default"] = {"properties": {"cors": {"corsRules": [
        {"allowedOrigins": ["https://allowed.example.com"], "allowedMethods": ["GET", "PUT"],
         "allowedHeaders": ["*"], "exposedHeaders": ["*"], "maxAgeInSeconds": 200},
    ]}}}
    denied = az.dispatch(st, "OPTIONS", "/data", {}, {"origin": "https://evil.example.com",
                         "access-control-request-method": "GET"}, b"", arm_state=arm_state)
    _check("preflight denied for an unlisted origin", denied.status == 403)
    allowed = az.dispatch(st, "OPTIONS", "/data", {}, {"origin": "https://allowed.example.com",
                          "access-control-request-method": "GET"}, b"", arm_state=arm_state)
    _check("preflight allowed for a listed origin", allowed.status == 200)
    _check("preflight reflects Access-Control-Allow-Origin", allowed.headers.get("access-control-allow-origin") == "https://allowed.example.com")
    _check("preflight carries Allow-Methods", "GET" in allowed.headers.get("access-control-allow-methods", ""))
    method_denied = az.dispatch(st, "OPTIONS", "/data", {}, {"origin": "https://allowed.example.com",
                                "access-control-request-method": "DELETE"}, b"", arm_state=arm_state)
    _check("preflight denied for an unlisted method", method_denied.status == 403)

    # ── Lifecycle management: tierToCool / tierToArchive / delete, lazily on list/get ──
    old = _http_date(datetime.now(timezone.utc) - timedelta(days=100))
    recent = _http_date(datetime.now(timezone.utc) - timedelta(days=1))
    mid = _http_date(datetime.now(timezone.utc) - timedelta(days=40))
    st.container_blobs("data")["ancient.log"] = {
        "data": b"x", "size": 1, "content_type": "text/plain", "blob_type": "BlockBlob",
        "etag": "\"e1\"", "last_modified": old, "created": old, "md5": None, "metadata": {},
    }
    st.container_blobs("data")["fresh.log"] = {
        "data": b"y", "size": 1, "content_type": "text/plain", "blob_type": "BlockBlob",
        "etag": "\"e2\"", "last_modified": recent, "created": recent, "md5": None, "metadata": {},
    }
    st.container_blobs("data")["warm.log"] = {
        "data": b"z", "size": 1, "content_type": "text/plain", "blob_type": "BlockBlob",
        "etag": "\"e3\"", "last_modified": mid, "created": mid, "md5": None, "metadata": {},
    }
    arm_state[RID + "/managementpolicies/default"] = {"properties": {"policy": {"rules": [
        {"name": "expire-logs", "enabled": True, "type": "Lifecycle", "definition": {
            "filters": {"prefixMatch": [], "blobTypes": ["blockBlob"]},
            "actions": {"baseBlob": {
                "tierToCool": {"daysAfterModificationGreaterThan": 30},
                "tierToArchive": {"daysAfterModificationGreaterThan": 90},
                "delete": {"daysAfterModificationGreaterThan": 365},
            }},
        }},
    ]}}}
    lst = az.dispatch(st, "GET", "/data", {"restype": "container", "comp": "list"}, {}, b"", arm_state=arm_state)
    body = lst.body.decode()
    _check("list reflects archived old blob", "<Name>ancient.log</Name>" in body and body.split("<Name>ancient.log</Name>", 1)[1].split("</Blob>", 1)[0].count("<AccessTier>Archive</AccessTier>") == 1)
    _check("list reflects cooled mid-age blob", body.split("<Name>warm.log</Name>", 1)[1].split("</Blob>", 1)[0].count("<AccessTier>Cool</AccessTier>") == 1)
    _check("list leaves a fresh blob Hot", body.split("<Name>fresh.log</Name>", 1)[1].split("</Blob>", 1)[0].count("<AccessTier>Hot</AccessTier>") == 1)

    arm_state[RID + "/managementpolicies/default"]["properties"]["policy"]["rules"][0]["definition"]["actions"]["baseBlob"]["delete"]["daysAfterModificationGreaterThan"] = 50
    get_ancient = az.dispatch(st, "GET", "/data/ancient.log", {}, {}, b"", arm_state=arm_state)
    _check("a blob past the delete threshold is reaped on access (404)", get_ancient.status == 404)

    # ── Static website: $web container served at the synthetic __website__ path ──
    nosite = az.dispatch(st, "GET", "/__website__/", {}, {}, b"", arm_state=arm_state)
    _check("website 404s when staticWebsite is not enabled", nosite.status == 404)

    arm_state[RID + "/blobservices/default"]["properties"]["staticWebsite"] = {
        "enabled": True, "indexDocument": "index.html", "errorDocument404Path": "404.html",
    }
    st.create_container("$web")
    now = _http_date(datetime.now(timezone.utc))
    st.container_blobs("$web")["index.html"] = {
        "data": b"<h1>hello</h1>", "size": 14, "content_type": "text/html", "blob_type": "BlockBlob",
        "etag": "\"w1\"", "last_modified": now, "created": now, "md5": None, "metadata": {},
    }
    st.container_blobs("$web")["404.html"] = {
        "data": b"<h1>missing</h1>", "size": 16, "content_type": "text/html", "blob_type": "BlockBlob",
        "etag": "\"w2\"", "last_modified": now, "created": now, "md5": None, "metadata": {},
    }
    idx = az.dispatch(st, "GET", "/__website__/", {}, {}, b"", arm_state=arm_state)
    _check("website root serves the index document", idx.status == 200 and idx.body == b"<h1>hello</h1>")
    page = az.dispatch(st, "GET", "/__website__/index.html", {}, {}, b"", arm_state=arm_state)
    _check("website serves index.html by explicit path too", page.status == 200)
    miss = az.dispatch(st, "GET", "/__website__/nope.html", {}, {}, b"", arm_state=arm_state)
    _check("a missing page falls back to the 404 document", miss.status == 404 and miss.body == b"<h1>missing</h1>")

    # ── Account configuration: allowSharedKeyAccess / publicNetworkAccess / default tier /
    #    container anonymous access level — all read off the account's OWN ARM record ──
    st2 = az.AzureBlobStore()
    arm2 = {RID: {"properties": {}}}
    sk = {"authorization": f"SharedKey {ACCT}:sig"}

    create = az.dispatch(st2, "PUT", f"/{ACCT}/cfgtest", {"restype": "container"}, sk, b"", arm_state=arm2)
    _check("SharedKey write allowed when allowSharedKeyAccess is unset", create.status == 201)

    arm2[RID]["properties"]["allowSharedKeyAccess"] = False
    denied = az.dispatch(st2, "GET", f"/{ACCT}/cfgtest", {"restype": "container", "comp": "list"}, sk, b"", arm_state=arm2)
    _check("SharedKey request denied once allowSharedKeyAccess is false", denied.status == 403)
    _check("SharedKey denial error code", denied.headers.get("x-ms-error-code") == "KeyBasedAuthenticationNotPermitted")
    arm2[RID]["properties"]["allowSharedKeyAccess"] = True

    arm2[RID]["properties"]["publicNetworkAccess"] = "Disabled"
    net_denied = az.dispatch(st2, "GET", f"/{ACCT}/cfgtest", {"restype": "container", "comp": "list"}, sk, b"", arm_state=arm2)
    _check("publicNetworkAccess Disabled blocks the data plane", net_denied.status == 403)
    _check("publicNetworkAccess denial error code", net_denied.headers.get("x-ms-error-code") == "AuthorizationFailure")
    arm2[RID]["properties"]["publicNetworkAccess"] = "Enabled"

    arm2[RID]["properties"]["accessTier"] = "Cool"
    up = az.dispatch(st2, "PUT", f"/{ACCT}/cfgtest/x.txt", {}, {**sk, "x-ms-blob-type": "BlockBlob"}, b"x", arm_state=arm2)
    _check("blob upload succeeds", up.status == 201)
    head = az.dispatch(st2, "HEAD", f"/{ACCT}/cfgtest/x.txt", {}, sk, b"", arm_state=arm2)
    _check("a new blob inherits the account's default access tier", head.headers.get("x-ms-access-tier") == "Cool")
    az.dispatch(st2, "PUT", f"/{ACCT}/cfgtest/y.txt", {},
                {**sk, "x-ms-blob-type": "BlockBlob", "x-ms-access-tier": "Archive"}, b"y", arm_state=arm2)
    head2 = az.dispatch(st2, "HEAD", f"/{ACCT}/cfgtest/y.txt", {}, sk, b"", arm_state=arm2)
    _check("an explicit x-ms-access-tier wins over the account default", head2.headers.get("x-ms-access-tier") == "Archive")

    pub = az.dispatch(st2, "PUT", f"/{ACCT}/public-ro", {"restype": "container"},
                      {**sk, "x-ms-blob-public-access": "container"}, b"", arm_state=arm2)
    _check("create container with an anonymous access level", pub.status == 201)
    props_resp = az.dispatch(st2, "GET", f"/{ACCT}/public-ro", {"restype": "container"}, sk, b"", arm_state=arm2)
    _check("GetContainerProperties echoes x-ms-blob-public-access", props_resp.headers.get("x-ms-blob-public-access") == "container")
    lc_body = az.dispatch(st2, "GET", f"/{ACCT}", {"comp": "list"}, sk, b"", arm_state=arm2).body.decode()
    _check("ListContainers reflects the public access level",
           lc_body.split("<Name>public-ro</Name>", 1)[1].split("</Container>", 1)[0].count("<PublicAccess>container</PublicAccess>") == 1)
    cfgtest_block = lc_body.split("<Name>cfgtest</Name>", 1)[1].split("</Container>", 1)[0]
    _check("a private container has no PublicAccess element", "<PublicAccess>" not in cfgtest_block)

    print("\nAzure Blob Storage DEPTH (CORS / lifecycle / static website / account configuration) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
