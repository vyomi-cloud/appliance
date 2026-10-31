"""Phase BL5: Azure Blob Storage Siftly SDK conformance test.

Exercises the real Azure Blob Python SDK (azure-storage-blob) against the simulator
in both storage modes:
1. In-process store (core.azure_dataplane with CLOUDLEARN_AZURITE_URL unset)
2. Azurite bridge (core.azure_blob_store with CLOUDLEARN_AZURITE_URL pointing to Azurite-compatible endpoint)

Validates the 9 verification cases from docs/specs/blob-storage-siftly-spec.md §5:
1. create_container(public_access="blob") -> 201; second create -> ResourceExistsError; public_access property preserved.
2. container_client.exists() -> True; missing container -> False.
3. Upload nested blob org/42/logo.png with ContentSettings(content_type="image/png", cache_control="public, max-age=3600");
   get_blob_properties() returns both; plain HTTP GET returns Content-Type and Cache-Control.
4. Upload JSON with ContentSettings(content_type="application/json"); download_blob().readall() round-trips.
5. list_blobs(name_starts_with="org/42/") returns only that prefix; list-then-delete removes them all.
6. generate_blob_sas(...) URL fetched with plain urllib, no credentials -> 200 and bytes.
7. blob_client.exists() after delete_blob() -> False.
8. blob_client.url for a public_access="blob" container loads over HTTP without credentials.
9. Profile conformance: verifies that Siftly profile configurations set the connection string, not name and key alone.

Run on host:
    PYTHONPATH=. python3 tests/conformance/test_blob_siftly_sdk.py
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
import uvicorn

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

from core import azure_blob_core as abc
from core import azure_dataplane as adp


def _check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"Check failed: {name}")
    print(f"    ok  {name}")


class _AzuriteBridgeHandler(http.server.BaseHTTPRequestHandler):
    """Pure in-process Azurite HTTP endpoint backed by core.azure_blob_core.AzureBlobStore."""
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def _handle(self) -> None:
        store = self.server.store  # type: ignore[attr-defined]
        u = urlparse(self.path)
        qp = {k: v[0] for k, v in parse_qs(u.query).items()}
        hdrs = {k.lower(): v for k, v in self.headers.items()}
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        resp = abc.dispatch(store, self.command, u.path, qp, hdrs, body)
        self.send_response(resp.status)
        h_lower = {k.lower(): v for k, v in resp.headers.items()}
        for k, v in resp.headers.items():
            self.send_header(k, v)
        if resp.media_type and "content-type" not in h_lower:
            self.send_header("content-type", resp.media_type)
        if "content-length" not in h_lower:
            self.send_header("content-length", str(len(resp.body)))
        self.send_header("connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _run_sdk_suite_against_client(client: BlobServiceClient, account_name: str, key: str, mode_label: str) -> None:
    print(f"  --- Running SDK suite in {mode_label} mode ---")

    container_name = f"siftly-test-{int(time.time() * 1000) % 1000000}"

    # 1. create_container(public_access="blob") -> 201; second create -> ResourceExistsError
    cc = client.create_container(container_name, public_access="blob")
    _check(f"[{mode_label}] case 1: create_container 201", cc.container_name == container_name)

    props = cc.get_container_properties()
    _check(f"[{mode_label}] case 1: container public_access is blob", props.public_access == "blob")

    dup_caught = False
    try:
        client.create_container(container_name, public_access="blob")
    except ResourceExistsError:
        dup_caught = True
    _check(f"[{mode_label}] case 1: duplicate create_container raises ResourceExistsError", dup_caught)

    # 2. container_client.exists() -> True; missing container -> False
    _check(f"[{mode_label}] case 2: existing container exists() is True", cc.exists() is True)
    missing_cc = client.get_container_client(f"missing-{container_name}")
    _check(f"[{mode_label}] case 2: missing container exists() is False", missing_cc.exists() is False)

    # 3. upload nested logo.png with ContentSettings(content_type="image/png", cache_control="public, max-age=3600")
    bc_logo = cc.get_blob_client("org/42/logo.png")
    settings = ContentSettings(
        content_type="image/png",
        cache_control="public, max-age=3600",
        content_disposition="inline; filename=logo.png",
        content_language="en-US",
    )
    png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake-logo-data"
    bc_logo.upload_blob(png_data, content_settings=settings, overwrite=True)

    logo_props = bc_logo.get_blob_properties()
    _check(f"[{mode_label}] case 3: SDK blob content_type is image/png",
           logo_props.content_settings.content_type == "image/png")
    _check(f"[{mode_label}] case 3: SDK blob cache_control is public, max-age=3600",
           logo_props.content_settings.cache_control == "public, max-age=3600")
    _check(f"[{mode_label}] case 3: SDK blob content_disposition preserved",
           logo_props.content_settings.content_disposition == "inline; filename=logo.png")

    # Plain HTTP GET
    with urllib.request.urlopen(bc_logo.url) as resp:
        _check(f"[{mode_label}] case 3: HTTP GET status 200", resp.status == 200)
        _check(f"[{mode_label}] case 3: HTTP GET Content-Type image/png",
               "image/png" in resp.headers.get("Content-Type", ""))
        _check(f"[{mode_label}] case 3: HTTP GET Cache-Control header",
               resp.headers.get("Cache-Control") == "public, max-age=3600")
        _check(f"[{mode_label}] case 3: HTTP GET body matches uploaded bytes",
               resp.read() == png_data)

    # 4. Upload JSON with ContentSettings(content_type="application/json"); download_blob().readall() round-trips
    bc_json = cc.get_blob_client("config/settings.json")
    json_bytes = b'{"tenant_id": 42, "features": ["ocr", "vector_search"]}'
    bc_json.upload_blob(json_bytes, content_settings=ContentSettings(content_type="application/json"), overwrite=True)

    downloaded = bc_json.download_blob().readall()
    _check(f"[{mode_label}] case 4: download_blob().readall() round-trips bytes", downloaded == json_bytes)
    _check(f"[{mode_label}] case 4: JSON content_type is application/json",
           bc_json.get_blob_properties().content_settings.content_type == "application/json")

    # 5. list_blobs(name_starts_with="org/42/") returns only that prefix; list-then-delete removes them all
    bc_sub = cc.get_blob_client("org/42/subfolder/banner.png")
    bc_sub.upload_blob(b"banner-content", content_settings=ContentSettings(content_type="image/png"), overwrite=True)

    prefixed_blobs = list(cc.list_blobs(name_starts_with="org/42/"))
    blob_names = {b.name for b in prefixed_blobs}
    _check(f"[{mode_label}] case 5: list_blobs prefix filtered returned 2 blobs",
           blob_names == {"org/42/logo.png", "org/42/subfolder/banner.png"})

    # list-then-delete
    for b in cc.list_blobs(name_starts_with="org/42/"):
        cc.delete_blob(b.name)

    remaining_prefixed = list(cc.list_blobs(name_starts_with="org/42/"))
    _check(f"[{mode_label}] case 5: list-then-delete removed all prefixed blobs", len(remaining_prefixed) == 0)
    _check(f"[{mode_label}] case 5: non-prefixed blob still exists", bc_json.exists() is True)

    # 6. generate_blob_sas(...) URL fetched with plain urllib, no credentials -> 200 and bytes
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name="config/settings.json",
        account_key=key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    sas_url = f"{bc_json.url}?{sas_token}"
    with urllib.request.urlopen(sas_url) as resp:
        _check(f"[{mode_label}] case 6: SAS URL fetched anonymously returns 200", resp.status == 200)
        _check(f"[{mode_label}] case 6: SAS URL returns exact blob bytes", resp.read() == json_bytes)

    # 7. blob_client.exists() after delete_blob() -> False
    bc_json.delete_blob()
    _check(f"[{mode_label}] case 7: blob_client.exists() after delete is False", bc_json.exists() is False)

    # 8. blob_client.url (with SAS stripped) for public_access="blob" container loads in browser on host
    bc_pub = cc.get_blob_client("public/avatar.jpg")
    avatar_bytes = b"jpeg-avatar-bytes"
    bc_pub.upload_blob(avatar_bytes, content_settings=ContentSettings(content_type="image/jpeg"), overwrite=True)

    public_url = bc_pub.url
    with urllib.request.urlopen(public_url) as resp:
        _check(f"[{mode_label}] case 8: public container URL loads without SAS", resp.status == 200)
        _check(f"[{mode_label}] case 8: public URL Content-Type is image/jpeg",
               "image/jpeg" in resp.headers.get("Content-Type", ""))
        _check(f"[{mode_label}] case 8: public URL bytes match", resp.read() == avatar_bytes)


def _check_case_9_profile_env() -> None:
    print("  --- Running Case 9: Profile env connection string conformance ---")
    siftly_app_json_path = pathlib.Path(__file__).resolve().parent.parent.parent / "samples" / "siftly" / "app.json"
    _check("case 9: samples/siftly/app.json exists", siftly_app_json_path.exists())

    with open(siftly_app_json_path, encoding="utf-8") as f:
        manifest = json.load(f)

    outputs = manifest.get("outputs", {})
    backend_env = outputs.get("backend/.env", {})

    # Must set connection strings
    _check("case 9: AZURE_STORAGE_CONNECTION_STRING is present",
           "AZURE_STORAGE_CONNECTION_STRING" in backend_env)
    _check("case 9: AZURE_STORAGE_CONNECTION_STRING references blob profile connection string",
           backend_env["AZURE_STORAGE_CONNECTION_STRING"] == "${blob.siftlystore.connection_string}")
    _check("case 9: AZURE_ORG_LOGO_CONNECTION_STRING references blob profile connection string",
           backend_env.get("AZURE_ORG_LOGO_CONNECTION_STRING") == "${blob.siftlylogos.connection_string}")

    # Must NOT set account name/key alone without connection string
    for env_file, env_dict in outputs.items():
        if "AZURE_STORAGE_ACCOUNT_NAME" in env_dict or "AZURE_STORAGE_ACCOUNT_KEY" in env_dict:
            raise AssertionError(f"{env_file} must not set AZURE_STORAGE_ACCOUNT_NAME/KEY alone (hardcodes Azure domain)")
    _check("case 9: No env file sets name and key alone", True)


def run() -> int:
    print("Starting Azure Blob Siftly SDK Conformance Test Suite (BL5):")

    ACCOUNT = "devstoreaccount1"
    KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="

    # Start FastAPI simulator app
    app = FastAPI()
    adp.register(app)

    sim_port = 19385
    sim_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=sim_port, log_level="error"))
    sim_thread = threading.Thread(target=sim_server.run, daemon=True)
    sim_thread.start()
    time.sleep(0.5)

    conn_str = (
        f"DefaultEndpointsProtocol=http;AccountName={ACCOUNT};AccountKey={KEY};"
        f"BlobEndpoint=http://127.0.0.1:{sim_port}/azure-data/blob/{ACCOUNT};"
    )

    # ------------------------------------------------------------------------
    # Run 1: In-process store mode (CLOUDLEARN_AZURITE_URL unset)
    # ------------------------------------------------------------------------
    os.environ.pop("CLOUDLEARN_AZURITE_URL", None)
    client_inproc = BlobServiceClient.from_connection_string(conn_str)
    _run_sdk_suite_against_client(client_inproc, ACCOUNT, KEY, "In-Process Store")

    # ------------------------------------------------------------------------
    # Run 2: Azurite bridge mode (CLOUDLEARN_AZURITE_URL pointing to Azurite server)
    # ------------------------------------------------------------------------
    azurite_backend_store = abc.AzureBlobStore()
    az_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AzuriteBridgeHandler)
    az_server.store = azurite_backend_store  # type: ignore[attr-defined]
    az_port = az_server.server_address[1]
    az_thread = threading.Thread(target=az_server.serve_forever, daemon=True)
    az_thread.start()

    os.environ["CLOUDLEARN_AZURITE_URL"] = f"http://127.0.0.1:{az_port}"
    client_azurite = BlobServiceClient.from_connection_string(conn_str)
    _run_sdk_suite_against_client(client_azurite, ACCOUNT, KEY, "Azurite Bridge")

    # ------------------------------------------------------------------------
    # Case 9: Profile env configuration
    # ------------------------------------------------------------------------
    _check_case_9_profile_env()

    print("\nAzure Blob Siftly SDK Conformance (Cases 1-9, In-Process + Azurite): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
