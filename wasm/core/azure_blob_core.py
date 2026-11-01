# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Blob Storage object-CRUD core — substrate-independent, the Azure
analogue of core/gcp_storage_core.py / core/s3_object_core.py. Speaks the
native **Azure Blob REST API** so the native `azure-storage-blob` SDK, the
`az storage blob` CLI, and Azurite-style clients work unchanged against it
(point them at the endpoint / connection string).

NO fastapi / azure-* / socket / subprocess imports → loads under Pyodide.
Self-contained: bundles its own in-memory `AzureBlobStore` (does NOT import
core/azure_blob_store.py) so the core is a single portable unit.

Scope (data-plane slice):
  - create container   PUT  /{container}?restype=container            -> 201
  - list containers    GET  /?comp=list                              -> 200 XML
  - put block blob     PUT  /{container}/{blob}  x-ms-blob-type       -> 201
  - get blob           GET  /{container}/{blob}                       -> 200 bytes
  - head blob props    HEAD /{container}/{blob}                       -> 200
  - list blobs         GET  /{container}?restype=container&comp=list  -> 200 XML
  - delete blob        DELETE /{container}/{blob}                     -> 202
  - delete container   DELETE /{container}?restype=container          -> 202

Errors carry status + `x-ms-error-code` header + an `<Error><Code>..</Code>`
XML body (ContainerNotFound / BlobNotFound / ContainerAlreadyExists).
Every response carries `x-ms-request-id` + `x-ms-version` headers.

v4 C0b — the offline appliance serves its Blob wire through THIS core (over
core/appliance_stores.py) instead of the retired core/azure_dataplane handler. The
legacy-only behaviours were ported here (tests/conformance/test_c0b_legacy_parity_core.py):
`x-ms-blob-content-type` wins over the request Content-Type, suffix ranges
(`bytes=-N`), `x-ms-creation-time`, lease properties in listings, and store hooks
for an external byte store (Azurite write-through + lazy fetch of pre-v4 blobs).
The appliance names the account explicitly (`dispatch(..., account=...)`, the
`/azure-data/blob/{account}/...` route) instead of sniffing it from SharedKey.

An OPTIONAL leading `/{account}` path segment (Azurite style
`/{account}/{container}/{blob}`) is tolerated — the well-known
`/devstoreaccount1/` prefix is stripped.

Per-account namespaces: a path-style request whose `Authorization: SharedKey
{account}:{sig}` (the header every azure-storage-blob SDK sends) names the
account in its first path segment is scoped to THAT account — its containers
are invisible to other accounts, like separate `{account}.blob.core.windows.net`
endpoints. Requests without a SharedKey account (or for `devstoreaccount1`)
use the default namespace, exactly as before.

v4 depth — account configuration, ENFORCED. `arm_state` also carries the storage account
resource's OWN properties (not just its blobServices/managementPolicies sub-resources),
looked up by `_account_properties`:
  - `allowSharedKeyAccess: false` rejects any request whose Authorization header is
    SharedKey/SharedKeyLite with 403 `KeyBasedAuthenticationNotPermitted` — real key-based
    auth rejection, independent of substrate (checked off the header, not off how `acct`
    was resolved).
  - `publicNetworkAccess: "Disabled"` rejects every data-plane request (the account has no
    private endpoint in this simulator, so "disabled" means unreachable) with 403
    `AuthorizationFailure`.
  - `accessTier` (the account's default) seeds a newly uploaded blob's tier when the
    request carries no `x-ms-access-tier` of its own.
  - A container's anonymous access level (`x-ms-blob-public-access: blob|container` on
    create) is stored and echoed back (`GetContainerProperties`, `ListContainers`'
    `<PublicAccess>`) exactly as configured — enforcing it against a genuinely
    credential-less reader is not modelled: `acct` itself is only ever resolved from a
    SharedKey header (Nano) or the appliance's own route (offline), so a request with no
    Authorization header is indistinguishable from "the caller's tooling omitted it", not
    a real anonymous Internet client.

v4 depth — CORS / lifecycle / static website, ENFORCED (not just stored). The caller
(core/aws_wire_router.py) passes the Azure ARM core's `state` dict (`arm_state=`) — the
same record the Configuration/CORS/Lifecycle/Static website console panels write through
ARM's `blobServices/default` and `managementPolicies/default` sub-resources — so this
module reads config out of the ONE place it is written, no duplicate store:
  - CORS: an `OPTIONS` preflight is matched against the account's `cors.corsRules`; a
    match gets `Access-Control-Allow-*` headers + 200, no match (or no rules at all) a
    403 `CorsPreflightFailure`. Matching rules are also reflected onto real responses.
  - Lifecycle: `managementPolicies/default`'s `policy.rules` are applied lazily — every
    blob list/get re-evaluates each enabled rule's `prefixMatch` filter against blob age
    (now - last_modified) and applies the most aggressive matching action (delete >
    tierToArchive > tierToCool), same semantics as the daily background job, without a
    scheduler.
  - Static website: a GET to the synthetic `/{account}/__website__/{path}` segment (this
    single-origin relay has no distinct per-account public hostname) serves the `$web`
    container's blobs, falling back to `indexDocument` for `/` and `errorDocument404Path`
    for a miss, when `staticWebsite.enabled` is set.

v4 WAVE 5b gap sweep — redundancy / data protection / request telemetry, ENFORCED:
  - Redundancy: a request whose SharedKey account names `{account}-secondary` is a real,
    separate, READ-ONLY alias of the primary account's own data (Vyomi stores data once,
    locally — there is no second region to actually replicate to). It 404s
    `ResourceNotFound` unless the account's sku is RA-GRS/RA-GZRS (`skuLabel` "read-access
    ...") and 403s `OperationNotAllowedOnSecondary` for anything but a read. Geo-replication
    lag / regional failover itself is still not simulated.
  - Soft delete (`deleteRetentionPolicy` / `containerDeleteRetentionPolicy`): when enabled on
    the account, DELETE blob/container moves the entry into a separate recoverable store
    instead of erasing it — invisible to normal listings/gets, visible with
    `?include=deleted`, recoverable with `?comp=undelete`, and lazily purged once the
    configured retention window has actually elapsed (same lazy-evaluation style as
    Lifecycle). Disabled (the default) keeps today's immediate hard delete.
  - Versioning (`isVersioningEnabled`): when enabled, overwriting a blob keeps the prior
    body as a real, separately fetchable version (`?versionid=`) instead of discarding it;
    `?include=versions` lists them.
  - Change feed (`changeFeed.enabled`): a real, append-only BlobCreated/BlobDeleted event
    log per account, derived from actual PUT/DELETE blob calls (never synthetic), read back
    with the Vyomi-only `?comp=changefeed` (this is NOT the real `$blobchangefeed`
    Avro-segment format — there is no Avro writer here, just the real events).
  - Request telemetry: every request bumps a real per-account transaction/ingress/egress
    counter (`azure_monitor_core.get_storage_metrics` reads it for the Metrics/Insights
    panels — Availability is always reported 100%, latency is not modelled) and appends a
    real request-log line, filtered at read time by which log categories (StorageRead/
    StorageWrite/StorageDelete) a `Microsoft.Insights/diagnosticSettings` on this account
    actually has enabled — read back with the Vyomi-only `?comp=diagnosticlog` (logs are
    captured in-memory and gated by the diagnostic setting; they are not actually delivered
    to the configured workspace/storage account/event hub destination, since no Log
    Analytics/Event Hub ingestion engine exists here).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote
from xml.sax.saxutils import escape

X_MS_VERSION = "2021-12-02"


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/xml"


# ── self-contained in-memory store ─────────────────────────────────────────
class AzureBlobStore:
    """In-memory Azure Blob namespace. containers: name -> {meta}. blobs:
    container -> {blob_name -> entry}. Fully self-contained; no external seam."""

    def __init__(self) -> None:
        self.containers: dict[str, dict] = {}
        self.blobs: dict[str, dict[str, dict]] = {}
        # v4 WAVE 5b — soft delete / versioning / change feed / telemetry (see module docstring).
        self.deleted_containers: dict[str, dict] = {}            # container -> {meta, blobs, deleted_at}
        self.deleted_blobs: dict[str, dict[str, dict]] = {}      # container -> blob -> {entry, deleted_at}
        self.blob_versions: dict[str, dict[str, list]] = {}      # container -> blob -> [older entries, oldest..newest-but-current]
        self.change_feed: dict[str, list] = {}                   # acct ("" = default namespace) -> [event, ...]
        self.request_counters: dict[str, dict] = {}              # acct -> {transactions, ingress, egress}
        self.request_log: dict[str, list] = {}                  # acct -> [{time, category, operation, status, uri}, ...]

    def container_exists(self, name: str) -> bool:
        return name in self.containers

    def create_container(self, name: str, public_access: str = "") -> None:
        self.containers[name] = {"created": _now_http(), "public_access": public_access}
        self.blobs.setdefault(name, {})

    def delete_container(self, name: str) -> None:
        self.containers.pop(name, None)
        self.blobs.pop(name, None)

    def container_blobs(self, name: str) -> dict[str, dict]:
        return self.blobs.setdefault(name, {})

    def persist(self) -> None:
        """Write-through hook (no-op in-memory; a backed subclass overrides it)."""

    # ── optional external byte-store hooks (no-ops here; the appliance mirrors
    #    blob bytes to Azurite when it is configured) ──────────────────────
    def mirror_put(self, container: str, blob: str, entry: dict) -> None:
        """Best-effort write-through of a blob to an external byte store."""

    def mirror_delete(self, container: str, blob: str) -> None:
        """Best-effort delete in the external byte store."""

    def mirror_delete_container(self, container: str) -> None:
        """Best-effort container delete in the external byte store."""

    def fetch_bytes(self, container: str, blob: str):
        """Bytes of a blob whose entry carries no inline data (pre-v4 blobs that
        live only in the external byte store). None = unknown."""
        return None


# ── primitives ─────────────────────────────────────────────────────────────
def _now_http() -> str:
    # RFC 1123, e.g. "Wed, 13 Jul 2026 12:00:00 GMT"
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _etag() -> str:
    return '"0x8D' + uuid.uuid4().hex[:13].upper() + '"'


def _md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode()


def _request_id() -> str:
    return str(uuid.uuid4())


def _base_headers() -> dict:
    return {
        "x-ms-request-id": _request_id(),
        "x-ms-version": X_MS_VERSION,
        "date": _now_http(),
    }


def _err(status: int, code: str, message: str) -> Response:
    h = _base_headers()
    h["x-ms-error-code"] = code
    h["content-type"] = "application/xml"
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f"<Error><Code>{escape(code)}</Code>"
        f"<Message>{escape(message)}</Message></Error>"
    ).encode()
    return Response(status=status, headers=h, body=body)


def _xml(status: int, body: str) -> Response:
    h = _base_headers()
    h["content-type"] = "application/xml"
    return Response(status=status, headers=h, body=body.encode())


def _json_response(status: int, obj: dict) -> Response:
    h = _base_headers()
    h["content-type"] = "application/json"
    return Response(status=status, headers=h, body=json.dumps(obj).encode(), media_type="application/json")


# ── path handling ──────────────────────────────────────────────────────────
def _strip_account(p: str) -> str:
    """Tolerate an optional leading /{account} segment (Azurite style).
    Strip the well-known devstoreaccount1 prefix robustly."""
    if p.startswith("/devstoreaccount1/"):
        return p[len("/devstoreaccount1"):]
    if p == "/devstoreaccount1":
        return "/"
    return p


_SHAREDKEY_RE = re.compile(r"^\s*SharedKey(?:Lite)?\s+([a-z0-9][a-z0-9-]{0,78}):", re.I)


def _account_scope(p: str, headers: dict) -> tuple[str, str]:
    """(account, path-without-account) when the SharedKey account names the first
    path segment (path-style `/{account}/...`); ("", p) otherwise."""
    m = _SHAREDKEY_RE.match(headers.get("authorization", "") or "")
    acct = m.group(1) if m else ""
    if not acct or acct == "devstoreaccount1":
        return "", p
    if p == "/" + acct:
        return acct, "/"
    if p.startswith("/" + acct + "/"):
        return acct, p[len(acct) + 1:]
    return "", p


# ── ARM config lookup (CORS / lifecycle / static website) ──────────────────
def _arm_properties(arm_state: dict | None, acct: str, suffix: str) -> dict:
    """The `properties` of the storage account's ARM `blobServices/default` or
    `managementPolicies/default` sub-resource — looked up by account name since the
    data plane (unlike ARM) never learns the subscription/resource-group it lives
    under. Account names are globally unique, so a suffix match is unambiguous."""
    if not arm_state:
        return {}
    want = f"/storageaccounts/{acct.lower()}/{suffix}" if acct else f"/storageaccounts/"
    for key, rec in arm_state.items():
        kl = key.lower()
        if acct:
            if kl.endswith(want):
                return (rec or {}).get("properties", {}) or {}
        elif f"/{suffix}" in kl and "/storageaccounts/" in kl:
            # default namespace: any account's record is a loose match (good enough for
            # the simulator's single-tenant default namespace with no explicit account).
            return (rec or {}).get("properties", {}) or {}
    return {}


def _account_sku(arm_state: dict | None, acct: str) -> str:
    """The storage account's `sku.name` (sibling of `properties`, not inside it) — same
    account-name suffix match `_account_properties` uses."""
    if not arm_state or not acct:
        return ""
    want = f"/storageaccounts/{acct.lower()}"
    for key, rec in arm_state.items():
        if key.lower().endswith(want):
            return ((rec or {}).get("sku") or {}).get("name", "") or ""
    return ""


_RA_SKU_RE = re.compile(r"^(?:standard|premium)_ra", re.I)


def _diag_settings_for_account(arm_state: dict | None, acct: str) -> list[dict]:
    """`Microsoft.Insights/diagnosticSettings` records (core/azure_monitor_core.py, stored
    by core/azure_arm_core.AzureArm._diagnostic_settings under `_diag_scope`) whose scope is
    THIS storage account — looked up by account-name suffix match, same reasoning as
    `_account_properties`: the data plane never learns the subscription/resource group."""
    if not arm_state or not acct:
        return []
    want = f"/storageaccounts/{acct.lower()}"
    return [rec for rec in arm_state.values()
            if str((rec or {}).get("_diag_scope", "")).lower().endswith(want)]


def _diag_enabled_log_categories(arm_state: dict | None, acct: str) -> set[str]:
    cats: set[str] = set()
    for rec in _diag_settings_for_account(arm_state, acct):
        for c in (rec.get("properties", {}) or {}).get("logs", []) or []:
            if c.get("enabled") and c.get("category"):
                cats.add(c["category"])
    return cats


def _bump(store: AzureBlobStore, acct: str, ingress: int = 0, egress: int = 0) -> None:
    c = store.request_counters.setdefault(acct, {"transactions": 0, "ingress": 0, "egress": 0})
    c["transactions"] += 1
    c["ingress"] += ingress
    c["egress"] += egress


_LOG_CAP = 200


def _reqlog(store: AzureBlobStore, acct: str, category: str, operation: str, status: int, uri: str) -> None:
    lst = store.request_log.setdefault(acct, [])
    lst.append({"time": _now_http(), "category": category, "operation": operation, "status": status, "uri": uri})
    if len(lst) > _LOG_CAP:
        del lst[: len(lst) - _LOG_CAP]


def _replication_targets(arm_state: dict | None, acct: str, container: str, blob: str) -> list:
    """OBJECT REPLICATION (ENFORCED): the `Microsoft.Storage/storageAccounts/{dst}/objectReplicationPolicies`
    ARM children whose `sourceAccount` is this account and that have a rule for this source container
    (honouring `filters.prefixMatch`) -> [(destination store key, rule), ...]."""
    out = []
    if not arm_state or not acct:
        return out
    for key, rec in arm_state.items():
        if "/objectreplicationpolicies/" not in key.lower() or "/__event__" in key.lower():
            continue
        p = (rec or {}).get("properties") or {}
        if str(p.get("sourceAccount", "")).lower() != acct.lower():
            continue
        dst = str(p.get("destinationAccount", "")).lower()
        for rule in p.get("rules") or []:
            if rule.get("sourceContainer") != container:
                continue
            prefixes = ((rule.get("filters") or {}).get("prefixMatch")) or []
            if prefixes and not any(blob.startswith(x) for x in prefixes):
                continue
            if not any(o[0] == f"{dst}/{rule.get('destinationContainer')}" for o in out):   # the policy exists on both accounts
                out.append((f"{dst}/{rule.get('destinationContainer')}", rule))
    return out


def _replicate(store: AzureBlobStore, arm_state, acct: str, container: str, blob: str, entry: dict | None) -> None:
    """Copy (entry) or remove (None) the blob in every replication destination container that exists.
    Synchronous here; real replication is asynchronous (minutes)."""
    for dkey, _rule in _replication_targets(arm_state, acct, container, blob):
        if dkey not in store.containers:
            continue                                  # the destination container must exist, as in Azure
        blobs = store.container_blobs(dkey)
        if entry is None:
            blobs.pop(blob, None)
            store.mirror_delete(dkey, blob)
        else:
            blobs[blob] = {**entry, "etag": _etag(), "last_modified": _now_http(),
                           "metadata": dict(entry.get("metadata") or {})}
            store.mirror_put(dkey, blob, blobs[blob])
    store.persist()


def _feed(store: AzureBlobStore, acct: str, event: str, container: str, blob: str = "") -> None:
    lst = store.change_feed.setdefault(acct, [])
    lst.append({"time": _now_http(), "event": event, "container": container, "blob": blob})
    if len(lst) > _LOG_CAP:
        del lst[: len(lst) - _LOG_CAP]


def account_metrics(store: AzureBlobStore, acct: str) -> dict:
    """Real numbers derived from this account's actual state/activity (never synthetic) —
    read by core/azure_monitor_core.py's `get_storage_metrics` for the Metrics/Insights
    panels. `acct` is the lower-cased account name (""  = default namespace)."""
    prefix = f"{acct}/" if acct else None
    containers = [k for k in store.containers if (k.startswith(prefix) if prefix else "/" not in k)]
    blob_count = sum(len(store.blobs.get(c, {})) for c in containers)
    used_capacity = sum(e.get("size", 0) for c in containers for e in store.blobs.get(c, {}).values())
    counters = store.request_counters.get(acct, {"transactions": 0, "ingress": 0, "egress": 0})
    return {
        "usedCapacity": used_capacity, "blobCount": blob_count, "containerCount": len(containers),
        "transactions": counters["transactions"], "ingress": counters["ingress"], "egress": counters["egress"],
    }


def _account_properties(arm_state: dict | None, acct: str) -> dict:
    """The storage account resource's OWN `properties` (allowSharedKeyAccess,
    allowBlobPublicAccess, publicNetworkAccess, accessTier, …) — as written by
    Create/Update storage account, looked up by account name (exact match, unlike
    `_arm_properties`'s sub-resource suffix match: a sub-resource key like
    `.../storageaccounts/{acct}/blobservices/default` never ends with `/storageaccounts/{acct}`)."""
    if not arm_state or not acct:
        return {}
    want = f"/storageaccounts/{acct.lower()}"
    for key, rec in arm_state.items():
        if key.lower().endswith(want):
            return (rec or {}).get("properties", {}) or {}
    return {}


def _cors_rules(arm_state: dict | None, acct: str) -> list:
    return _arm_properties(arm_state, acct, "blobservices/default").get("cors", {}).get("corsRules", []) or []


def _static_website(arm_state: dict | None, acct: str) -> dict:
    return _arm_properties(arm_state, acct, "blobservices/default").get("staticWebsite", {}) or {}


def _lifecycle_rules(arm_state: dict | None, acct: str) -> list:
    policy = _arm_properties(arm_state, acct, "managementpolicies/default").get("policy", {}) or {}
    return policy.get("rules", []) or []


def _blobservices_props(arm_state: dict | None, acct: str) -> dict:
    return _arm_properties(arm_state, acct, "blobservices/default")


def _delete_retention_days(arm_state: dict | None, acct: str, key: str) -> int | None:
    """`key`: "deleteRetentionPolicy" (blobs) or "containerDeleteRetentionPolicy" (containers).
    None when soft delete is disabled for that scope."""
    p = _blobservices_props(arm_state, acct).get(key) or {}
    if not p.get("enabled"):
        return None
    try:
        return max(1, int(p.get("days", 7)))
    except (TypeError, ValueError):
        return 7


def _versioning_enabled(arm_state: dict | None, acct: str) -> bool:
    return bool(_blobservices_props(arm_state, acct).get("isVersioningEnabled"))


def _changefeed_enabled(arm_state: dict | None, acct: str) -> bool:
    return bool((_blobservices_props(arm_state, acct).get("changeFeed") or {}).get("enabled"))


# ── CORS (Set/Get Blob Service Properties → corsRules, enforced on preflight) ──────────
def _cors_match(rules: list, origin: str, method: str, req_headers: str) -> dict | None:
    req_hdrs = [h.strip().lower() for h in (req_headers or "").split(",") if h.strip()]
    for rule in rules:
        origins = rule.get("allowedOrigins", []) or []
        methods = [m.upper() for m in (rule.get("allowedMethods", []) or [])]
        allowed_hdrs = [h.strip().lower() for h in (rule.get("allowedHeaders", []) or [])]
        if "*" not in origins and origin not in origins:
            continue
        if method.upper() not in methods:
            continue
        if not all(h in allowed_hdrs or "*" in allowed_hdrs for h in req_hdrs):
            continue
        return rule
    return None


def _cors_preflight(arm_state: dict | None, acct: str, headers: dict) -> Response | None:
    origin = headers.get("origin")
    if origin is None:
        return None
    req_method = headers.get("access-control-request-method", "")
    req_headers = headers.get("access-control-request-headers", "")
    rules = _cors_rules(arm_state, acct)
    rule = _cors_match(rules, origin, req_method, req_headers) if rules else None
    if rule is None:
        return _err(403, "CorsPreflightFailure", "CORS not enabled or no matching rule found for this request.")
    h = _base_headers()
    h["access-control-allow-origin"] = origin if "*" not in rule.get("allowedOrigins", []) else "*"
    h["access-control-allow-methods"] = ", ".join(rule.get("allowedMethods", []))
    if req_headers:
        h["access-control-allow-headers"] = req_headers
    h["access-control-max-age"] = str(rule.get("maxAgeInSeconds", 0))
    h["access-control-expose-headers"] = ", ".join(rule.get("exposedHeaders", []) or [])
    return Response(status=200, headers=h, body=b"", media_type=None)


# ── Lifecycle management (managementPolicies/default → policy.rules, ENFORCED lazily) ──
def _parse_http_date(s: str):
    try:
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _apply_lifecycle(store: AzureBlobStore, container: str, acct: str, arm_state: dict | None) -> None:
    rules = [r for r in _lifecycle_rules(arm_state, acct) if r.get("enabled", True)]
    if not rules:
        return
    blobs = store.container_blobs(container)
    now = _now()
    changed = False
    for name in list(blobs):
        entry = blobs[name]
        modified = _parse_http_date(entry.get("last_modified", ""))
        if modified is None:
            continue
        age_days = (now - modified).total_seconds() / 86400.0
        for rule in rules:
            definition = rule.get("definition", {}) or {}
            flt = definition.get("filters", {}) or {}
            prefixes = flt.get("prefixMatch") or []
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            actions = (definition.get("actions", {}) or {}).get("baseBlob", {}) or {}
            delete_after = actions.get("delete", {}).get("daysAfterModificationGreaterThan")
            archive_after = actions.get("tierToArchive", {}).get("daysAfterModificationGreaterThan")
            cool_after = actions.get("tierToCool", {}).get("daysAfterModificationGreaterThan")
            if delete_after is not None and age_days > float(delete_after):
                blobs.pop(name, None)
                changed = True
                break
            if archive_after is not None and age_days > float(archive_after):
                if entry.get("access_tier") != "Archive":
                    entry["access_tier"] = "Archive"
                    changed = True
                break
            if cool_after is not None and age_days > float(cool_after):
                if entry.get("access_tier") != "Cool":
                    entry["access_tier"] = "Cool"
                    changed = True
                break
    if changed:
        store.persist()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Soft delete (deleteRetentionPolicy / containerDeleteRetentionPolicy), ENFORCED lazily ──
def _purge_expired_containers(store: AzureBlobStore, acct: str, arm_state: dict | None) -> None:
    days = _delete_retention_days(arm_state, acct, "containerDeleteRetentionPolicy")
    now = _now()
    prefix = f"{acct}/" if acct else None
    for name in list(store.deleted_containers):
        if prefix is not None and not name.startswith(prefix):
            continue
        if prefix is None and "/" in name:
            continue
        rec = store.deleted_containers[name]
        deleted_at = rec.get("deleted_at")
        if days is None or deleted_at is None or (now - deleted_at).total_seconds() / 86400.0 > days:
            # Soft delete turned off, or the retention window has actually elapsed: purge for real.
            store.deleted_containers.pop(name, None)


def _purge_expired_blobs(store: AzureBlobStore, container: str, arm_state: dict | None, acct: str) -> None:
    days = _delete_retention_days(arm_state, acct, "deleteRetentionPolicy")
    now = _now()
    deleted = store.deleted_blobs.get(container)
    if not deleted:
        return
    for name in list(deleted):
        deleted_at = deleted[name].get("deleted_at")
        if days is None or deleted_at is None or (now - deleted_at).total_seconds() / 86400.0 > days:
            deleted.pop(name, None)


# ── Static website ($web container, served at the synthetic /__website__/ path) ────────
def _serve_website(store: AzureBlobStore, acct: str, tail: str, arm_state: dict | None) -> Response:
    site = _static_website(arm_state, acct)
    if not site.get("enabled"):
        return _err(404, "StaticWebsiteNotEnabled", "Static website hosting is not enabled for this account.")
    container = f"{acct}/$web" if acct else "$web"
    blob_name = tail.lstrip("/") or (site.get("indexDocument") or "index.html")
    blobs = store.container_blobs(container) if store.container_exists(container) else {}
    entry = blobs.get(blob_name)
    if entry is not None:
        h = _base_headers()
        h["content-type"] = entry["content_type"]
        h["etag"] = entry["etag"]
        h["last-modified"] = entry["last_modified"]
        return Response(status=200, headers=h, body=_entry_bytes(store, container, blob_name, entry), media_type=entry["content_type"])
    err_doc = site.get("errorDocument404Path")
    err_entry = blobs.get(err_doc) if err_doc else None
    if err_entry is not None:
        h = _base_headers()
        h["content-type"] = err_entry["content_type"]
        return Response(status=404, headers=h, body=_entry_bytes(store, container, err_doc, err_entry), media_type=err_entry["content_type"])
    return _err(404, "BlobNotFound", f"'{blob_name}' was not found in the $web container.")


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: AzureBlobStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", account: str | None = None, arm_state: dict | None = None) -> Response:
    """`account` (appliance): the storage account the route already resolved — the
    path is then relative to it (`/{container}[/{blob}]`) and the namespace is that
    account's. None (Nano / dev_server): the account is read from SharedKey."""
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    p = path.split("?", 1)[0]
    if account is not None:
        acct = account.lower()
        p = p or "/"
    else:
        p = _strip_account(p)
        acct, p = _account_scope(p, headers)
    # v4 WAVE 5b — redundancy: `{account}-secondary` is a real, read-only alias of the
    # primary account, gated by whether its sku is RA-GRS/RA-GZRS (see module docstring).
    secondary = account is None and acct.endswith("-secondary")
    if secondary:
        acct = acct[: -len("-secondary")]
    p = p.rstrip("/") if p != "/" else p
    segs = [unquote(s) for s in p.split("/") if s != ""]

    # ---- account configuration gates (ENFORCED — see module docstring) ----
    props = _account_properties(arm_state, acct)
    if props.get("publicNetworkAccess") == "Disabled":
        return _err(403, "AuthorizationFailure",
                    "Public network access is disabled for this storage account.")
    auth_header = headers.get("authorization", "") or ""
    if _SHAREDKEY_RE.match(auth_header) and props.get("allowSharedKeyAccess") is False:
        return _err(403, "KeyBasedAuthenticationNotPermitted",
                    "Key based authentication is not permitted on this storage account.")
    if secondary:
        if not _RA_SKU_RE.match(_account_sku(arm_state, acct)):
            return _err(404, "ResourceNotFound",
                        "The secondary (read-access) endpoint is not enabled for this storage "
                        "account — enable RA-GRS or RA-GZRS redundancy first.")
        if method not in ("GET", "HEAD", "OPTIONS"):
            return _err(403, "OperationNotAllowedOnSecondary",
                        "The secondary endpoint of a read-access geo-redundant account is read-only.")

    # ---- CORS preflight: any OPTIONS carrying an Origin header ----
    if method == "OPTIONS":
        pre = _cors_preflight(arm_state, acct, headers)
        if pre is not None:
            return pre

    # ---- static website: GET /{account}/__website__/{path...} (synthetic — see module docstring) ----
    if segs and segs[0] == "__website__":
        if method not in ("GET", "HEAD"):
            return _err(400, "UnsupportedHttpVerb", f"Unsupported website operation {method}")
        return _serve_website(store, acct, "/".join(segs[1:]), arm_state)

    comp = query.get("comp", "")
    restype = query.get("restype", "")
    include = {s for s in (query.get("include") or "").split(",") if s}

    # ---- account-level: list containers  GET /?comp=list ----
    if not segs:
        if method == "GET" and comp == "list":
            _purge_expired_containers(store, acct, arm_state)
            return _list_containers(store, acct, include)
        # v4 WAVE 5b — Vyomi-only synthetic reads (no real Azure wire shape — see module
        # docstring): the real request-telemetry/change-feed data behind Diagnostic
        # settings/Logs and Change feed, gated by what's actually enabled for this account.
        if method == "GET" and comp == "diagnosticlog":
            cats = _diag_enabled_log_categories(arm_state, acct)
            rows = [r for r in store.request_log.get(acct, []) if r["category"] in cats]
            return _json_response(200, {"value": rows, "enabledCategories": sorted(cats)})
        if method == "GET" and comp == "changefeed":
            enabled = _changefeed_enabled(arm_state, acct)
            rows = store.change_feed.get(acct, []) if enabled else []
            return _json_response(200, {"value": rows, "enabled": enabled})
        return _err(400, "InvalidUri", f"Unsupported account operation {method}")

    display = segs[0]
    # Container names never contain "/", so "{account}/{container}" keys cannot
    # collide with default-namespace containers.
    container = f"{acct}/{display}" if acct else display

    # ---- container-level: /{container} ----
    if len(segs) == 1:
        if restype == "container":
            if method == "PUT" and comp == "undelete":   # v4 WAVE 5b — restore a soft-deleted container
                rec = store.deleted_containers.pop(container, None)
                if rec is None:
                    return _err(404, "ContainerNotFound", "The specified container does not exist.")
                store.containers[container] = rec["meta"]
                store.blobs[container] = rec["blobs"]
                store.persist()
                return Response(status=201, headers=_base_headers(), body=b"", media_type=None)
            if method == "PUT":                       # create container
                if store.container_exists(container):
                    return _err(409, "ContainerAlreadyExists",
                                "The specified container already exists.")
                pa = (headers.get("x-ms-blob-public-access") or "").strip().lower()
                store.create_container(container, pa if pa in ("blob", "container") else "")
                store.persist()
                _bump(store, acct)
                _reqlog(store, acct, "StorageWrite", "PutContainer", 201, f"/{display}")
                h = _base_headers()
                h["etag"] = _etag()
                h["last-modified"] = _now_http()
                return Response(status=201, headers=h, body=b"", media_type=None)
            if method == "DELETE":                    # delete container
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                days = _delete_retention_days(arm_state, acct, "containerDeleteRetentionPolicy")
                if days is not None:                  # v4 WAVE 5b — soft delete: recoverable, not erased
                    store.deleted_containers[container] = {
                        "meta": store.containers[container], "blobs": store.blobs.get(container, {}),
                        "deleted_at": _now(),
                    }
                store.delete_container(container)
                store.persist()
                store.mirror_delete_container(container)
                _bump(store, acct)
                _reqlog(store, acct, "StorageDelete", "DeleteContainer", 202, f"/{display}")
                return Response(status=202, headers=_base_headers(),
                                body=b"", media_type=None)
            if method == "GET" and comp == "list":    # list blobs
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                _apply_lifecycle(store, container, acct, arm_state)
                _purge_expired_blobs(store, container, arm_state, acct)
                _bump(store, acct)
                _reqlog(store, acct, "StorageRead", "ListBlobs", 200, f"/{display}")
                return _list_blobs(store, container, query, display, include)
            if method in ("GET", "HEAD"):             # get container props
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                pa = store.containers[container].get("public_access", "")
                h = _base_headers()
                h["last-modified"] = store.containers[container].get("created", _now_http())
                h["etag"] = _etag()
                if pa:
                    h["x-ms-blob-public-access"] = pa
                return Response(status=200, headers=h, body=b"", media_type=None)
        return _err(400, "InvalidQueryParameterValue",
                    f"Unsupported container operation {method}")

    # ---- blob-level: /{container}/{blob...} ----
    blob = "/".join(segs[1:])

    if method == "PUT" and comp == "undelete":            # v4 WAVE 5b — restore a soft-deleted blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound", "The specified container does not exist.")
        rec = store.deleted_blobs.get(container, {}).pop(blob, None)
        if rec is None:
            return _err(404, "BlobNotFound", "The specified blob does not exist.")
        store.container_blobs(container)[blob] = rec["entry"]
        store.persist()
        return Response(status=200, headers=_base_headers(), body=b"", media_type=None)

    if method == "PUT":                               # put block blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound",
                        "The specified container does not exist.")
        blob_type = headers.get("x-ms-blob-type", "BlockBlob")
        # The blob's Content-Type is `x-ms-blob-content-type` when sent (that is what
        # azure-storage-blob's ContentSettings / `az storage blob upload
        # --content-type` set); the request's own Content-Type is the fallback.
        content_type = (headers.get("x-ms-blob-content-type") or headers.get("content-type")
                        or "application/octet-stream")
        now = _now_http()
        prev = store.container_blobs(container).get(blob) or {}
        tier = headers.get("x-ms-access-tier") or prev.get("access_tier") or props.get("accessTier") or "Hot"
        entry = {
            "data": body,
            "size": len(body),
            "content_type": content_type,
            "blob_type": blob_type,
            "etag": _etag(),
            "last_modified": now,
            "created": prev.get("created") or now,
            "md5": _md5_b64(body),
            "access_tier": tier,
            "metadata": {k[len("x-ms-meta-"):]: v for k, v in headers.items()
                         if k.startswith("x-ms-meta-")},
        }
        if prev and _versioning_enabled(arm_state, acct):     # v4 WAVE 5b — keep the overwritten body as a real version
            versions = store.blob_versions.setdefault(container, {}).setdefault(blob, [])
            versions.append({**prev, "_version_id": prev["etag"]})
        store.container_blobs(container)[blob] = entry
        store.persist()
        store.mirror_put(container, blob, entry)
        _replicate(store, arm_state, acct, display, blob, entry)
        _bump(store, acct, ingress=len(body))
        _reqlog(store, acct, "StorageWrite", "PutBlob", 201, f"/{display}/{blob}")
        if _changefeed_enabled(arm_state, acct):
            _feed(store, acct, "BlobCreated", display, blob)
        h = _base_headers()
        h["etag"] = entry["etag"]
        h["last-modified"] = entry["last_modified"]
        h["content-md5"] = entry["md5"]
        h["x-ms-request-server-encrypted"] = "true"
        return Response(status=201, headers=h, body=b"", media_type=None)

    if method in ("GET", "HEAD") and store.container_exists(container):
        _apply_lifecycle(store, container, acct, arm_state)
    blobs = store.container_blobs(container) if store.container_exists(container) else {}
    entry = blobs.get(blob)
    version_id = query.get("versionid")
    if entry is not None and version_id and entry.get("etag") != version_id:
        # v4 WAVE 5b — `?versionid=` fetches a specific historical version, not the current
        # one. The version id is the version's own ETag (unique per write; real Azure uses a
        # microsecond timestamp instead, which this simulator's second-resolution clock can't).
        entry = next((v for v in store.blob_versions.get(container, {}).get(blob, [])
                      if v.get("_version_id") == version_id), None)

    if method in ("GET", "HEAD"):                      # get / head blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound",
                        "The specified container does not exist.")
        if entry is None:
            return _err(404, "BlobNotFound", "The specified blob does not exist.")
        _bump(store, acct, egress=entry.get("size", 0) if method == "GET" else 0)
        _reqlog(store, acct, "StorageRead", "GetBlob" if method == "GET" else "HeadBlob", 200, f"/{display}/{blob}")
        h = _base_headers()
        h["etag"] = entry["etag"]
        h["last-modified"] = entry["last_modified"]
        h["content-length"] = str(entry["size"])
        h["content-type"] = entry["content_type"]
        if entry.get("md5"):
            h["content-md5"] = entry["md5"]
        h["x-ms-blob-type"] = entry["blob_type"]
        h["x-ms-access-tier"] = entry.get("access_tier", "Hot")
        h["accept-ranges"] = "bytes"
        h["x-ms-server-encrypted"] = "true"
        h["x-ms-creation-time"] = entry.get("created") or entry["last_modified"]
        h["x-ms-lease-status"] = "unlocked"
        h["x-ms-lease-state"] = "available"
        for mk, mv in entry.get("metadata", {}).items():
            h[f"x-ms-meta-{mk}"] = mv
        if method == "HEAD":
            return Response(status=200, headers=h, body=b"", media_type=None)
        # Range support — the azure-storage-blob SDK downloads via a ranged GET
        # (Range / x-ms-range: bytes=start-end) and requires 206 + Content-Range.
        data = _entry_bytes(store, container, blob, entry)
        rng = headers.get("x-ms-range") or headers.get("range") or ""
        m = re.match(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
        if m and (m.group(1) or m.group(2)):
            total = len(data)
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else total - 1
            else:                                     # suffix range: the last N bytes
                start, end = max(total - int(m.group(2)), 0), total - 1
            end = min(end, total - 1)
            if start > end or start >= total:
                er = _err(416, "InvalidRange", "The range specified is invalid.")
                er.headers["content-range"] = f"bytes */{total}"
                return er
            sl = data[start:end + 1]
            h["content-length"] = str(len(sl))
            h["content-range"] = f"bytes {start}-{end}/{total}"
            return Response(status=206, headers=h, body=sl, media_type=entry["content_type"])
        return Response(status=200, headers=h, body=data, media_type=entry["content_type"])

    if method == "DELETE":                             # delete blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound",
                        "The specified container does not exist.")
        live = blobs.get(blob)                         # the current entry, not a `?versionid=` lookup
        if live is None:
            return _err(404, "BlobNotFound", "The specified blob does not exist.")
        blobs.pop(blob, None)
        days = _delete_retention_days(arm_state, acct, "deleteRetentionPolicy")
        if days is not None:                            # v4 WAVE 5b — soft delete: recoverable, not erased
            store.deleted_blobs.setdefault(container, {})[blob] = {"entry": live, "deleted_at": _now()}
        store.persist()
        store.mirror_delete(container, blob)
        _replicate(store, arm_state, acct, display, blob, None)
        _bump(store, acct)
        _reqlog(store, acct, "StorageDelete", "DeleteBlob", 202, f"/{display}/{blob}")
        if _changefeed_enabled(arm_state, acct):
            _feed(store, acct, "BlobDeleted", display, blob)
        return Response(status=202, headers=_base_headers(), body=b"", media_type=None)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported blob operation {method}")


def _entry_bytes(store: AzureBlobStore, container: str, blob: str, entry: dict) -> bytes:
    """A blob's bytes: inline `data`, else the store's external byte store."""
    data = entry.get("data")
    if data is None:
        data = store.fetch_bytes(container, blob)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return bytes(data or b"")


# ── XML builders ────────────────────────────────────────────────────────────
def _list_containers(store: AzureBlobStore, acct: str = "", include: set | None = None) -> Response:
    include = include or set()
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             '<EnumerationResults><Containers>']
    for key in sorted(store.containers):
        if acct:
            if not key.startswith(acct + "/"):
                continue
            name = key[len(acct) + 1:]
        elif "/" in key:
            continue                      # another account's container
        else:
            name = key
        meta = store.containers[key]
        pa = meta.get("public_access", "")
        parts.append(
            "<Container>"
            f"<Name>{escape(name)}</Name>"
            "<Properties>"
            f"<Last-Modified>{escape(meta.get('created', _now_http()))}</Last-Modified>"
            f"<Etag>{escape(_etag())}</Etag>"
            + (f"<PublicAccess>{escape(pa)}</PublicAccess>" if pa else "") +
            "<LeaseStatus>unlocked</LeaseStatus>"
            "<LeaseState>available</LeaseState>"
            "</Properties>"
            "</Container>"
        )
    if "deleted" in include:              # v4 WAVE 5b — soft-deleted containers, recoverable
        for key in sorted(store.deleted_containers):
            if acct:
                if not key.startswith(acct + "/"):
                    continue
                name = key[len(acct) + 1:]
            elif "/" in key:
                continue
            else:
                name = key
            rec = store.deleted_containers[key]
            parts.append(
                "<Container>"
                f"<Name>{escape(name)}</Name>"
                "<Deleted>true</Deleted>"
                "<Properties>"
                f"<Last-Modified>{escape(rec['meta'].get('created', _now_http()))}</Last-Modified>"
                f"<Etag>{escape(_etag())}</Etag>"
                "<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
                "</Properties>"
                "</Container>"
            )
    parts.append("</Containers><NextMarker /></EnumerationResults>")
    return _xml(200, "".join(parts))


def _blob_xml(name: str, e: dict, deleted: bool = False, is_current: bool | None = None) -> str:
    return (
        "<Blob>"
        f"<Name>{escape(name)}</Name>"
        + (f"<VersionId>{escape(e['_version_id'])}</VersionId>" if e.get("_version_id") else "")
        + (f"<IsCurrentVersion>{'true' if is_current else 'false'}</IsCurrentVersion>" if is_current is not None else "")
        + ("<Deleted>true</Deleted>" if deleted else "") +
        "<Properties>"
        f"<Last-Modified>{escape(e['last_modified'])}</Last-Modified>"
        f"<Etag>{escape(e['etag'])}</Etag>"
        f"<Content-Length>{e['size']}</Content-Length>"
        f"<Content-Type>{escape(e['content_type'])}</Content-Type>"
        + (f"<Content-MD5>{escape(e['md5'])}</Content-MD5>" if e.get("md5") else "") +
        f"<BlobType>{escape(e['blob_type'])}</BlobType>"
        f"<AccessTier>{escape(e.get('access_tier', 'Hot'))}</AccessTier>"
        "<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
        f"<Creation-Time>{escape(e.get('created') or e['last_modified'])}</Creation-Time>"
        "</Properties>"
        "</Blob>"
    )


def _list_blobs(store: AzureBlobStore, container: str, query: dict, display: str | None = None,
                include: set | None = None) -> Response:
    include = include or set()
    prefix = query.get("prefix", "") or ""
    blobs = store.container_blobs(container)
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             f'<EnumerationResults ContainerName="{escape(display or container)}"><Blobs>']
    for name in sorted(blobs):
        if not name.startswith(prefix):
            continue
        e = blobs[name]
        parts.append(_blob_xml(name, e, is_current=True if "versions" in include else None))
        if "versions" in include:         # v4 WAVE 5b — prior versions kept by Versioning
            for v in store.blob_versions.get(container, {}).get(name, []):
                parts.append(_blob_xml(name, v, is_current=False))
    if "deleted" in include:              # v4 WAVE 5b — soft-deleted blobs, recoverable
        for name, rec in sorted(store.deleted_blobs.get(container, {}).items()):
            if name.startswith(prefix):
                parts.append(_blob_xml(name, rec["entry"], deleted=True))
    parts.append("</Blobs><NextMarker /></EnumerationResults>")
    return _xml(200, "".join(parts))
