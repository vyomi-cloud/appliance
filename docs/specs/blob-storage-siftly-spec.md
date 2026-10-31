---
title: Azure Blob Storage for Siftly — spec
status: draft (revision 3 — aligned with app profiles; second self-review applied)
updated: 2026-10-18
owner: Rohith
repo: ~/Documents/appliance (Vyomi v3.0.6)
related:
  - siftly-integration-gaps.md (row 4)
  - storage-cache-siftly-implementation-plan.md (BL1–BL5)
  - app-env-spec.md (creates the accounts and containers; writes the connection strings)
---

# Azure Blob Storage for Siftly — spec

**Goal:** Siftly's blob code runs unchanged against Vyomi with only `AZURE_STORAGE_CONNECTION_STRING` (and `AZURE_ORG_LOGO_CONNECTION_STRING`) pointing at Vyomi. Images uploaded by Siftly load in the browser through the URLs Siftly generates, with the right content type and cache headers.

**Effort:** about 3 days solo, about 1.65 days with Claude (BL1–BL5). Creating containers and writing connection strings is counted in the app-profile plan.

## 1. What Siftly uses

From `backend/services/*blob*`, `image_generation_service.py`, `image_kit_blob_service.py`, `brand_kit_blob_service.py`, `routes/content.py`:

| Call | Count | Notes |
| --- | --- | --- |
| `get_blob_client(...)` | 25 | Mostly `(blob_name)` on a container client, or `(container, blob_path)`. Blob names contain `/` (for example `org/<id>/x.png`) |
| `.exists()` | 24 | Container and blob |
| `ContentSettings(...)` | 8 | `content_type` (`application/json`, `text/markdown; charset=utf-8`, image types); one call also sets `cache_control` |
| `.upload_blob(...)` | 13 | Small payloads: images, JSON, markdown |
| `.delete_blob()` | 9 | Including prefix deletes (list, then delete) |
| `.download_blob()` | 6 | |
| `.create_container(public_access="blob")` | 6 | Images are served straight to browsers |
| `.list_blobs(name_starts_with=...)` | 2 | |
| `generate_blob_sas(..., BlobSasPermissions(read=True))` | 2 | Needs `AccountName` and `AccountKey` in the connection string |

## 2. What Vyomi has today

Blob logic lives in **three places**, and all three must stay in step:

| File | Role | Content-type and headers today |
| --- | --- | --- |
| `core/azure_dataplane.py` | FastAPI handler at `/azure-data/blob/{account}/{rest:path}` for Pro/Max; calls the helpers below | Reads `content-type` before `x-ms-blob-content-type` (**bug**); stores no other content headers |
| `core/azure_blob_core.py` | Portable in-memory core; used by Nano (Pyodide) and `tests/conformance/test_azure_blob_core.py` | Line 201: `headers.get("content-type", ...)` (**same bug**); no other content headers |
| `core/azure_blob_store.py` | Azurite bridge, used when `CLOUDLEARN_AZURITE_URL` is set | `put_blob` passes only `content_type` into `ContentSettings` (line 141), so cache-control and the rest are **lost** |

Other facts:

- **Authentication is ignored by design.** SAS URLs work because their query parameters are ignored; anonymous browser `GET` works because nothing is checked.
- `public_access` on container create is accepted and ignored.
- Container create on an existing container returns 409 with header `x-ms-error-code: ContainerAlreadyExists` and an **empty body**. 404s are the same. The Python SDK reads the header, so Siftly works, but Azure returns an XML `<Error>` body that other clients parse.
- Chunked uploads (Put Block / Put Block List) are not supported; a `PUT ?comp=block` would be stored as the whole blob.
- The appliance is path-style (`/azure-data/blob/<account>/<container>/<blob>`); Azure is host-style (`<account>.blob.core.windows.net/<container>/<blob>`).

**Siftly behaviour that depends on Azure host names** (found in the second self-review):

- `routes/content.py:5303` `_delete_azure_blob` returns early unless the URL contains `blob.core.windows.net`, and it parses the path as `/<container>/<blob>`. On Vyomi, deleting an old image when it is replaced is **silently skipped**. Effect: orphan blobs locally, no user-visible error. Not fixed in Vyomi; the clean fix is a one-line Siftly change (derive the domain from the configured endpoint). Listed as a known gap.
- `brand_kit_blob_service`, `image_kit_blob_service`, `pages_governance_blob_service` and `azure_blob_core` fall back to `https://<name>.blob.core.windows.net` when only `AZURE_STORAGE_ACCOUNT_NAME`/`KEY` are set. The app profile must therefore always set the **connection string**, and must not set name and key alone.
- `brand_kit_blob_service.download_brand_kit` splits the URL on `/<container>/`, which also works with the path-style prefix.

## 3. Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| R1 | In all three paths, the stored and returned content type is `x-ms-blob-content-type` when present, else `Content-Type`, else `application/octet-stream` | Must |
| R2 | In all three paths, store and return `x-ms-blob-cache-control`, `-content-disposition`, `-content-encoding`, `-content-language` as `Cache-Control`, `Content-Disposition`, `Content-Encoding`, `Content-Language` on GET and HEAD, and in list results | Must |
| R3 | Record the container public-access level from `x-ms-blob-public-access`; return it on get-properties | Should |
| R4 | Error responses carry Azure's XML body, `<?xml …?><Error><Code>…</Code><Message>…</Message></Error>`, alongside `x-ms-error-code`, for at least `ContainerNotFound`, `ContainerAlreadyExists`, `BlobNotFound` | Should |
| R5 | **Done by the app profile, not here.** `vyomi app provision --app siftly` creates each account's containers with their public-access level; `vyomi env --app siftly` writes `${blob.<account>.connection_string}` (`DefaultEndpointsProtocol=http;AccountName;AccountKey;BlobEndpoint`). The endpoint comes from the appliance's `/api/runtime/endpoints`, so it honours `VYOMI_SIMULATOR_PORT` and the Multipass VM address instead of a hard-coded `localhost:9000` (see `app-env-spec.md`) | Must (dependency) |
| R9 | **Browser-reachable blob URLs.** Siftly returns `blob_client.url` to the browser (`image_generation_service.py:412`, `image_kit_blob_service.py:99,173`), so the `BlobEndpoint` host must resolve **both** inside the app and in the developer's browser. Host target: `localhost:<port>` works for both. Docker target: the Docker service name does not resolve in the browser. v1: the blob connection string for `--target docker` uses `host.docker.internal:<published port>` (the app container gets `extra_hosts: host.docker.internal:host-gateway` on Linux), and the developer's browser needs that name to resolve to 127.0.0.1 (Docker Desktop on Windows adds it; on macOS and Linux add a hosts entry). `vyomi env --check` warns when it does not resolve on the host | Must for Docker target |
| R6 | Put Block and Put Block List | Could (uploads > 64 MB only) |
| R7 | SAS signature and expiry checking behind `VYOMI_BLOB_VERIFY_SAS=1`, default off | Could |
| R8 | CORS headers on blob GET for browser `fetch` calls | Could; confirm whether Siftly's UI fetches blobs from JS |

## 4. Design

- **One header model.** A small helper, `blob_content_headers(headers) -> dict`, used by all three paths, returns `content_type` (R1 precedence) and the four optional properties (R2). The in-process records (`azure_dataplane` dict and `azure_blob_core` entry) store them as `props`. `azure_blob_store.put_blob` maps them onto `ContentSettings(content_type, cache_control, content_disposition, content_encoding, content_language)`, and its read paths return them from `props.content_settings`.
- **R3:** keep the level in the container record; return `x-ms-blob-public-access` on get-properties. No enforcement. **Azurite path:** `azure_blob_store` folds every simulator container of one account into a single Azurite container (`vyomi-<sha1>`), with the simulator container as a blob-name prefix, so Azurite's own `create_container(public_access=…)` cannot be used. Instead `create_container` writes the level as metadata on the container's existing marker blob (`<container>/.vyomi-container-keep`, `metadata={"public_access": level}`), and get-properties reads it back from that blob.
- **R4:** one `_error_xml(code, message, status)` helper per path.
- **R6, R7, R8:** as before; not in the required scope.

## 5. Acceptance tests

Two layers.

**Core conformance** (`tests/conformance/test_azure_blob_core.py`, host and Pyodide), extended:

1. A PUT with `x-ms-blob-content-type: image/png` and `Content-Type: application/octet-stream` stores `image/png`.
2. Cache-control and the other three properties round-trip on GET and HEAD.
3. A conflict and a missing blob return the XML `<Error>` body with the right code.

**SDK verification** (`tests/conformance/test_blob_siftly_sdk.py`, `azure-storage-blob` against a running appliance, run once with the in-process store and once with Azurite):

1. `create_container(public_access="blob")` → 201; a second create → `ResourceExistsError`.
2. `container_client.exists()` → True; for a missing container → False.
3. Upload `org/42/logo.png` (nested name) with `ContentSettings(content_type="image/png", cache_control="public, max-age=3600")`; `get_blob_properties()` returns both; plain HTTP GET returns `Content-Type: image/png` and `Cache-Control`.
4. Upload JSON with `ContentSettings(content_type="application/json")`; `download_blob().readall()` round-trips.
5. `list_blobs(name_starts_with="org/42/")` returns only that prefix; list-then-delete removes them all.
6. `generate_blob_sas(...)` URL fetched with plain `urllib`, no credentials → 200 and the bytes.
7. `blob_client.exists()` after `delete_blob()` → False.
8. `blob_client.url` (with the SAS stripped) for a `public_access="blob"` container loads in a browser on the host for the host target; for the Docker target, it loads once `host.docker.internal` resolves (R9).
9. A conformance check that every Siftly env file written by the profile sets the connection string, not name and key alone.

## 6. Out of scope

Page and append blobs, leases, snapshots, versioning, soft delete, tiers, listing beyond one page, Data Lake (`dfs`) endpoints.

## 7. Review log

| Date | Finding | Change |
| --- | --- | --- |
| 2026-10-18 | Three blob code paths; error bodies; Azurite loses cache-control | Revision 2 |
| 2026-10-18 | `vyomi env --map` superseded by app profiles; `localhost:9000` hard-coded | R5 now depends on `vyomi app provision` and `vyomi env --app`; endpoint from `/api/runtime/endpoints` |
| 2026-10-18 | Siftly hands `blob_client.url` to the browser, so the Docker service name breaks images | R9 and test 8 |
| 2026-10-18 | Siftly's `_delete_azure_blob` only acts on `blob.core.windows.net` URLs | Known gap, Siftly-side one-line fix suggested |
| 2026-10-18 | Name-and-key fallback hard-codes the Azure host | Profile must set the connection string; test 9 |
| 2026-10-18 | Effort header (1.5 d) differed from the plan (1.6 d) | Aligned to 1.6 d |
| 2026-10-18 | External review: Azurite path cannot pass `public_access` through, because simulator containers are prefixes inside one Azurite container | Store the level as metadata on the marker blob |
