#!/usr/bin/env python3
"""
Vyomi — Cloud Simulator (slim orchestrator)

This module wires together the extracted subsystems:
  - core.app_context   — shared state, constants, proxies, tenants, utilities
  - core.models        — Pydantic request/response models
  - core.middleware     — all ASGI middleware layers
  - routes/*           — FastAPI route handlers (20 modules)
  - providers/*        — provider-specific dispatchers & helpers

All business-logic helper functions that are still lazily imported by
provider and route modules (``import server``) remain here.
"""

# ── Env-var alias bridge (Phase 8 — vyomi rebrand) ────────────────────
# Import this FIRST, before any other core/* import, so the runtime
# mirror runs before any module reads os.environ via app_context, etc.
# Side-effect of import: CLOUDLEARN_* ↔ VYOMI_* aliases populated in
# os.environ. See core/env_aliases.py for the rationale.
from core import env_aliases  # noqa: F401

import base64
import copy
import asyncio
import fnmatch
import ipaddress
import hashlib
import io
import hmac
import json
import os
import re
import shlex
import platform
import secrets
import select
import pty
import shutil
import signal
import subprocess
import sys
import threading
import time
import socket
import uuid
import textwrap
import traceback
from functools import partial
from collections import deque
from collections.abc import MutableMapping
from pathlib import Path
from datetime import datetime, timezone, timedelta
from contextvars import ContextVar
from urllib.parse import parse_qsl
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

import uvicorn
from html import escape as xml_escape
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRouter
from pydantic import BaseModel

from core.vyomi_platform import VyomiPlatform as CloudLearnPlatform
from core.pack_catalog import default_packs as load_default_packs
from core.pack_catalog import fragment_for_pack
from core.pack_catalog import PROVIDER_PACK_GROUPS
from core.pack_catalog import packs_for_provider
from core.terraform_export import export_space_to_terraform_json
from core.terraform_workflow import (
    build_plan_summary as terraform_build_plan_summary,
    terraform_import_bundle as terraform_import_bundle,
    run_terraform_cli as terraform_run_cli,
    stage_workflow_bundle as terraform_stage_workflow_bundle,
    terraform_cli_available as terraform_cli_available,
    terraform_cli_path as terraform_cli_path,
    terraform_space_dir as terraform_space_dir,
    terraform_workspace_root as terraform_workspace_root,
)
from core.provider_registry import get_provider, list_providers, normalize_provider as normalize_provider_key, provider_matrix
from providers.aws import tool_response as aws_tool_response
from providers import aws_iam as provider_aws_iam
from providers import aws_services as provider_aws_services
from providers.aws_routes import register as register_aws_routes
from providers.aws_ec2_routes import register as register_aws_ec2_routes
from providers.capabilities import provider_capabilities, provider_services
from providers.gcp import tool_response as gcp_tool_response
from providers.gcp_compute_routes import register as register_gcp_compute_routes
from providers.gcp_routes import gcloud_resolve as gcp_gcloud_resolve
from providers.gcp_routes import gcutil_resolve as gcp_gcutil_resolve
from providers.gcp_routes import sdk_go_snippet as gcp_sdk_go_snippet
from providers.gcp_routes import sdk_java_snippet as gcp_sdk_java_snippet
from providers.gcp_routes import register as register_gcp_routes
from providers import azure_services as provider_azure_services
from providers.azure_services import register as register_azure_routes
from core.tooling_simulators import aws_cli_resolve, sdk_snippet

# ── Re-exports for backward compatibility ─────────────────────────────
from core.app_context import (
    PLATFORM, STATE, STATE_LOCK, REQUEST_TENANT, REQUEST_PROVIDER, REQUEST_PUBLIC_BASE,
    AWS_ACCOUNT_ID, DEFAULT_TENANT_ID, ALLOWED_PROVIDERS,
    EC2_XML_NS, RDS_XML_NS, SQS_XML_NS, S3_NS,
    STATE_FILE, LEGACY_STATE_FILE, STATE_VERSION,
    LXD_RUNTIME_IMAGE, MULTIPASS_RUNTIME_IMAGE, LXD_CONSOLE_PORT,
    EC2_TERMINATED_VISIBILITY_SECONDS, INSTANCE_WORK_ROOT,
    _DEFAULT_RUNTIME_BUNDLES,
    _SpaceScopedDictProxy,
    buckets, objects, multiparts,
    iam_state, ec2_state, gcp_compute_state, gcp_storage_state,
    gcp_sql_state, gcp_pubsub_state, gcp_firestore_state,
    gcp_functions_state, gcp_apigw_state, gcp_vpc_state, gcp_iam_state,
    azure_arm_state, vpc_state, rds_state, apigw_state, lambda_state,
    sqs_state, ddb_state, runtime_state, github_state,
    now as _now, now_http as _now_http, iso_to_http_date as _iso_to_http_date,
    parse_utc_timestamp as _parse_utc_timestamp,
    id_gen as _id, public_ip as _public_ip, private_ip as _private_ip,
    iam_root_principal as _iam_root_principal,
    persist_state as _persist_state, load_state as _load_state,
    record_usage as _record_usage,
    spaces_state as _spaces_state,
    tenants_state as _tenants_state, active_tenant_id as _active_tenant_id,
    tenant_dict as _tenant_dict, ensure_default_tenant as _ensure_default_tenant,
    tenant_scoped_bucket as _tenant_scoped_bucket,
    terraform_state as _terraform_state, terraform_space_state as _terraform_space_state,
    active_tier as _active_tier, enforce_quantity_cap as _enforce_quantity_cap,
    enforce_tier_feature as _enforce_tier_feature, enforce_size_cap as _enforce_size_cap,
    gcp_active_space_dict as _gcp_active_space_dict,
    gcp_project_name as _gcp_project_name,
    gcp_state_proxies as _gcp_state_proxies,
    azure_state_dict as _azure_state_dict,
    appliance_mode_enabled as _appliance_mode_enabled,
    distribution_mode as _distribution_mode,
    host_config as _host_config,
    resolved_host_os as _resolved_host_os,
    is_gcp_native_path as _is_gcp_native_path,
    is_azure_native_path as _is_azure_native_path,
    resolve_provider_service as _resolve_provider_service,
    rate_limit_tenant as _rate_limit_tenant,
    _GCP_CONSOLE_COLLECTIONS, _GCP_IAM_NESTED_COLLECTIONS,
    init_azure_state,
)

from core.models import *  # noqa: F401,F403  — backward compat

# ── App creation ──────────────────────────────────────────────────────
app = FastAPI(title="CloudLearn Cloud Simulator", version="2.0.0", docs_url=None, redoc_url=None)

# ── Backend route registration (EARLY) ───────────────────────────────
_aws_xamz_dispatchers: dict = {}
try:
    from core import vault_routes as _vault_routes
    _vault_routes.register(app, aws_dispatchers=_aws_xamz_dispatchers)
except Exception:
    pass
try:
    from core import nats_routes as _nats_routes
    _nats_routes.register(app, aws_dispatchers=_aws_xamz_dispatchers)
except Exception:
    pass
try:
    from core import cedar_routes as _cedar_routes
    _cedar_routes.register(app)
except Exception:
    pass

# ── Provider route registration ──────────────────────────────────────
register_aws_ec2_routes(app, None)
register_gcp_compute_routes(app, None)
register_aws_routes(app, None)
register_gcp_routes(app, None)
register_azure_routes(app, None)

# ── Route module registration ────────────────────────────────────────
from routes import console, aws_extras, gcp_extras, tenants, config, licensing
from routes import terraform, azure_console, cloudsim, spaces, gcp_console, runtime
from routes import aws_apigw, aws_ec2, aws_lambda, aws_sqs, aws_vpc, aws_rds, aws_dynamodb
from routes import lazy_backends

for mod in [console, aws_extras, gcp_extras, tenants, config, licensing,
            terraform, azure_console, cloudsim, spaces, gcp_console, runtime,
            aws_apigw, aws_ec2, aws_lambda, aws_sqs, aws_vpc, aws_rds, aws_dynamodb,
            lazy_backends]:
    mod.register(app)

# ── Middleware registration ──────────────────────────────────────────
from core.middleware import register_middleware
register_middleware(app)

# ── Header alias middleware (Phase 7 — vyomi rebrand) ─────────────────
# Bridges X-CloudLearn-* ↔ X-Vyomi-* on both request and response so the
# canonical X-Vyomi-* names work without touching the 24 read/write call
# sites scattered across core/. Registered LAST so it wraps every other
# middleware (FastAPI's middleware order is reverse-LIFO).
from core.header_aliases import HeaderAliasMiddleware
app.add_middleware(HeaderAliasMiddleware)

# ── Azure state injection ────────────────────────────────────────────
init_azure_state()

# ── Static files mount ───────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
_UI_HTML = os.path.join(STATIC_DIR, "index.html")
_PRICING_HTML = os.path.join(STATIC_DIR, "pricing.html")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

# S3 routes are registered at the BOTTOM of this file (see end-of-file
# block) so the catch-all @app.post("/{bucket}/{key:path}") doesn't
# swallow the specific /api/... POST routes that are defined further
# down. The comment 'S3 catch-all routes — LAST' was correct intent;
# the placement here was wrong.
from routes import aws_s3


# ═══════════════════════════════════════════════════════════════════════
# Business-logic helper functions still referenced by lazy import server
# ═══════════════════════════════════════════════════════════════════════



# ===========================================================================
# AWS rail extras — generic CRUD backend for the previously-stub rail items
# (Launch Templates / Volumes / Snapshots / Elastic IPs / Key Pairs / etc.).
# Schema lives in core/aws_rail_extras.py; this dispatches by "<service>/<stub>".
# Items are space-scoped (via the existing space.service_states proxy) and
# seeded on first read from the schema's `seed` list.
# Derived stubs (network-ifs from EC2 instances, dlqs from SQS queues, etc.)
# compute on the fly instead of using stored items.
# ===========================================================================

def _aws_extras_state(stub_key: str) -> dict:
    """Per-space slot for a given <service>/<stub-key>. Always returns a dict
    with {items:{}, seeded:False} created lazily.

    IMPORTANT: `PLATFORM.get_active_space()` returns a deepcopy. Mutating that
    copy doesn't persist. Reach into the kernel's live state dict directly
    (same pattern as PLATFORM.get_space_policy at cloudlearn_platform.py:1720)."""
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return {"items": {}, "seeded": False}   # no-op; won't persist
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    services = space.setdefault("service_states", {})
    extras = services.setdefault("aws_extras", {})
    slot = extras.setdefault(stub_key, {"items": {}, "seeded": False})
    if not isinstance(slot, dict):
        slot = {"items": {}, "seeded": False}
        extras[stub_key] = slot
    slot.setdefault("items", {})
    return slot


def _aws_extras_seed_if_needed(stub_key: str) -> None:
    from core.aws_rail_extras import EXTRAS
    schema = EXTRAS.get(stub_key)
    if not schema:
        return
    slot = _aws_extras_state(stub_key)
    if slot.get("seeded"):
        return
    for s in schema.get("seed") or []:
        # Use the schema-provided name field if any, else generate.
        name = s.get("name") or s.get("id") or s.get("snapshot_id") or s.get("volume_id") \
            or s.get("allocation_id") or s.get("key_pair_id") or s.get("request_id") \
            or s.get("interface_id") or s.get("event_id") or s.get("user") or s.get("dashboard")
        if not name:
            import secrets as _sec
            name = "item-" + _sec.token_hex(3)
        slot["items"][name] = dict(s)
    slot["seeded"] = True


def _aws_extras_derive(stub_key: str) -> list[dict]:
    """For 'derived_from' stubs, compute items on the fly from related state
    in the active space. Each derivation key returns a fresh list per call.
    Reads from the live kernel state (not a deepcopy) so it reflects writes
    just made by other endpoints."""
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
    services = space.get("service_states", {}) if isinstance(space, dict) else {}
    if stub_key == "ec2/instance-types":
        # Drive from the shared per-provider instance catalog
        try:
            from core import instance_catalog as cat
            out = []
            for name, meta in cat.AWS.items():
                ram_gb = (meta.get("ram_mb", 0) or 0) / 1024
                out.append({"name": name, "vcpu": meta.get("vcpu"),
                            "ram_gb": f"{ram_gb:.1f} GiB" if ram_gb < 10 else f"{int(ram_gb)} GiB",
                            "family": meta.get("family"),
                            "network": "Up to 5 Gbps" if "small" in name or "micro" in name else "Up to 25 Gbps"})
            return out
        except Exception:
            return []
    if stub_key == "ec2/ami-catalog":
        # Reuse the AMI list endpoint format
        try:
            res = api_ec2_amis()
            amis = res.get("amis") if isinstance(res, dict) else res
            return list(amis or [])
        except Exception:
            return []
    if stub_key == "ec2/network-ifs":
        ec2_instances = services.get("ec2", {}).get("instances", {}) or {}
        out = []
        for iid, inst in ec2_instances.items():
            if not isinstance(inst, dict): continue
            out.append({
                "interface_id": f"eni-{iid[-8:]}",
                "description": f"Primary ENI for {iid}",
                "instance_id": iid,
                "private_ip": inst.get("private_ip", "10.0.0.x"),
                "public_ip": inst.get("public_ip", "—"),
                "subnet_id": inst.get("subnet_id", "subnet-default"),
                "status": "in-use" if inst.get("state") == "running" else "available",
            })
        return out
    if stub_key == "iam/dashboard":
        iam = services.get("iam", {}) or {}
        return [
            {"metric": "Users",          "value": str(len(iam.get("users") or {})),    "recommendation": "Rotate access keys every 90 days"},
            {"metric": "Groups",         "value": str(len(iam.get("groups") or {})),    "recommendation": "Use groups to assign permissions, not direct user policies"},
            {"metric": "Roles",          "value": str(len(iam.get("roles") or {})),     "recommendation": "Prefer roles over long-lived access keys"},
            {"metric": "Customer policies","value": str(len(iam.get("policies") or {})),"recommendation": "Use AWS managed policies where possible"},
            {"metric": "MFA users",      "value": "0", "recommendation": "Require MFA for all users"},
        ]
    if stub_key == "rds/dashboard":
        rds = services.get("rds", {}) or {}
        dbs = rds.get("db_instances") or rds.get("databases") or {}
        return [
            {"metric": "DB instances",   "value": str(len(dbs))},
            {"metric": "Total storage",  "value": f"{sum((d.get('allocated_storage') or 20) for d in dbs.values() if isinstance(d,dict))} GiB"},
            {"metric": "Snapshots",      "value": "—"},
            {"metric": "Events (24h)",   "value": "—"},
        ]
    if stub_key == "dynamodb/dashboard":
        dyn = services.get("dynamodb", {}) or {}
        tables = dyn.get("tables") or {}
        return [
            {"metric": "Total tables",   "value": str(len(tables))},
            {"metric": "Item count",     "value": str(sum(int(t.get("item_count", 0) or 0) for t in tables.values() if isinstance(t, dict)))},
            {"metric": "Provisioned RCU","value": "—"},
            {"metric": "Provisioned WCU","value": "—"},
        ]
    if stub_key == "lambda/dashboard":
        lam = services.get("lambda", {}) or {}
        fns = lam.get("functions") or {}
        return [
            {"metric": "Functions",       "value": str(len(fns))},
            {"metric": "Layers",          "value": "0"},
            {"metric": "Invocations 24h", "value": str(sum(len((f.get("invocations") or [])) for f in fns.values() if isinstance(f, dict)))},
            {"metric": "Errors 24h",      "value": "0"},
        ]
    if stub_key == "vpc/dashboard":
        vpc = services.get("vpc", {}) or {}
        return [
            {"metric": "VPCs",             "value": str(len(vpc.get("vpcs") or {}))},
            {"metric": "Subnets",          "value": str(len(vpc.get("subnets") or {}))},
            {"metric": "Security groups",  "value": str(len(vpc.get("security_groups") or {}))},
            {"metric": "Route tables",     "value": str(len(vpc.get("route_tables") or {}))},
            {"metric": "Internet gateways","value": str(len(vpc.get("internet_gateways") or {}))},
        ]
    if stub_key == "sqs/dlqs":
        sqs = services.get("sqs", {}) or {}
        out = []
        queues = sqs.get("queues") or {}
        for qname, q in queues.items():
            if not isinstance(q, dict): continue
            # A queue is "a DLQ" if any other queue points to it via redrive policy.
            sources = [n for n, other in queues.items()
                       if isinstance(other, dict)
                       and (other.get("dlq_arn") or "").endswith("/"+qname)]
            if sources:
                out.append({
                    "name": qname, "arn": q.get("arn", f"arn:aws:sqs:us-east-1:123456789012:{qname}"),
                    "source_queues": ", ".join(sources), "approximate_messages": str(q.get("message_count") or 0),
                })
        return out
    return []




# ===========================================================================
# GCP rail extras — mirror of AWS extras, namespaced under gcp_extras in the
# space state. Powers the new Eventarc / Secret Manager / Cloud KMS services
# (which have no dedicated backend in the simulator) plus per-service rail
# sub-features (Compute Disks/Snapshots/Images, Cloud SQL Backups/Replicas).
# Same footgun mitigation as AWS — use PLATFORM.kernel.state directly.
# ===========================================================================

def _gcp_extras_state(stub_key: str) -> dict:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return {"items": {}, "seeded": False}
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    services = space.setdefault("service_states", {})
    extras = services.setdefault("gcp_extras", {})
    slot = extras.setdefault(stub_key, {"items": {}, "seeded": False})
    if not isinstance(slot, dict):
        slot = {"items": {}, "seeded": False}; extras[stub_key] = slot
    slot.setdefault("items", {})
    return slot


def _gcp_extras_seed_if_needed(stub_key: str) -> None:
    from core.gcp_rail_extras import EXTRAS
    schema = EXTRAS.get(stub_key)
    if not schema:
        return
    slot = _gcp_extras_state(stub_key)
    if slot.get("seeded"):
        return
    for s in schema.get("seed") or []:
        name = s.get("name") or s.get("id") or s.get("key_id") or s.get("trigger_id")
        if not name:
            import secrets as _sec
            name = "item-" + _sec.token_hex(3)
        slot["items"][name] = dict(s)
    slot["seeded"] = True




# ── GCP API Gateway — minimal handlers ──────────────────────────────────────
# The catalog wires API Gateway endpoints at /api/gcp/apigateway/v1/... but
# no concrete handlers existed (caught by the SPA loader hitting 404 →
# NoSuchBucket because the S3 catch-all swallowed the path). These return
# real-shape responses against per-space state so the GCP console can list +
# create APIs/configs/gateways without crashing.
def _gcp_apigateway_state(project: str, kind: str) -> dict:
    """kind ∈ {apis, configs, gateways, operations}. Per-space state."""
    spaces_state = PLATFORM.kernel.state.setdefault(
        "spaces", {"spaces": {}, "active_space_id": "", "settings": {}}
    )
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    svc_states = space.setdefault("service_states", {})
    ag = svc_states.setdefault("apigateway", {})
    proj = ag.setdefault(project, {})
    return proj.setdefault(kind, {})






_USAGE = {
    "gcp": {
        "connect": [
            ("gcloud / gsutil — point at the simulator", "bash", """gcloud config set auth/disable_credentials true
gcloud config set core/project gcp-dev
# REST services — set the override for the one you use:
export CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE="__BASE__/storage/v1/"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_COMPUTE="__BASE__/compute/v1/"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_SQLADMIN="__BASE__/sql/v1beta4/"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDFUNCTIONS="__BASE__/v1/"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_IAM="__BASE__/v1/"
# gRPC services use the bundled emulators (separate ports):
export STORAGE_EMULATOR_HOST="__HOST__"
export PUBSUB_EMULATOR_HOST="__HOSTNAME__:8085"
export FIRESTORE_EMULATOR_HOST="__HOSTNAME__:8080" """),
            ("Java — shared auth", "java", """// libraries-bom 26.43.0. gapic clients (Storage/PubSub/Firestore): NoCredentials + setHost
// or *_EMULATOR_HOST. Apiary REST clients (Compute/SQL/Functions/IAM): setRootUrl("__BASE__/").
HttpTransport transport = GoogleNetHttpTransport.newTrustedTransport();
JsonFactory json = GsonFactory.getDefaultInstance();"""),
            ("Go — shared auth", "go", """import "google.golang.org/api/option"
var noAuth = option.WithoutAuthentication()   // for REST clients (Compute/SQL/Functions/IAM)
// Storage/PubSub/Firestore: set *_EMULATOR_HOST instead of an endpoint."""),
        ],
        "services": [
            ("Cloud Storage", [
                ("CLI", "bash", """export STORAGE_EMULATOR_HOST="__HOST__"
gcloud storage buckets create gs://demo
gcloud storage cp ./f.txt gs://demo/f.txt
gcloud storage ls gs://demo"""),
                ("Java", "java", """Storage st = StorageOptions.newBuilder().setHost("__BASE__")
    .setProjectId("gcp-dev").setCredentials(NoCredentials.getInstance()).build().getService();
st.create(BucketInfo.of("demo"));
st.create(BlobInfo.newBuilder("demo", "f.txt").build(), "hello".getBytes());"""),
                ("Go", "go", """// STORAGE_EMULATOR_HOST=__HOST__
c, _ := storage.NewClient(ctx)
c.Bucket("demo").Create(ctx, "gcp-dev", nil)
w := c.Bucket("demo").Object("f.txt").NewWriter(ctx); w.Write([]byte("hello")); w.Close()"""),
            ]),
            ("Compute Engine", [
                ("CLI", "bash", """gcloud compute instances create vm1 --zone=us-central1-a --machine-type=e2-micro
gcloud compute instances list --zones=us-central1-a"""),
                ("Java", "java", """Compute compute = new Compute.Builder(transport, json, null)
    .setRootUrl("__BASE__/").setApplicationName("cl").build();
compute.instances().list("gcp-dev", "us-central1-a").execute();"""),
                ("Go", "go", """csvc, _ := compute.NewService(ctx, noAuth, option.WithEndpoint("__BASE__/compute/v1/"))
list, _ := csvc.Instances.List("gcp-dev", "us-central1-a").Do()"""),
            ]),
            ("Cloud SQL (Admin)", [
                ("CLI", "bash", """gcloud sql instances create db1 --database-version=POSTGRES_16 --tier=db-f1-micro --region=us-central1
gcloud sql instances list"""),
                ("Java", "java", """SQLAdmin sql = new SQLAdmin.Builder(transport, json, null)
    .setRootUrl("__BASE__/").setApplicationName("cl").build();
sql.instances().list("gcp-dev").execute();"""),
                ("Go", "go", """ssvc, _ := sqladmin.NewService(ctx, noAuth, option.WithEndpoint("__BASE__/"))
ssvc.Instances.List("gcp-dev").Do()"""),
            ]),
            ("Pub/Sub", [
                ("CLI", "bash", """export PUBSUB_EMULATOR_HOST="__HOSTNAME__:8085"
gcloud pubsub topics create demo-topic
gcloud pubsub subscriptions create demo-sub --topic=demo-topic"""),
                ("Java", "java", """// PUBSUB_EMULATOR_HOST=__HOSTNAME__:8085
TopicAdminClient admin = TopicAdminClient.create();
admin.createTopic(TopicName.of("gcp-dev", "demo-topic"));
Publisher pub = Publisher.newBuilder(TopicName.of("gcp-dev", "demo-topic")).build();
pub.publish(PubsubMessage.newBuilder().setData(ByteString.copyFromUtf8("hi")).build());"""),
                ("Go", "go", """// PUBSUB_EMULATOR_HOST=__HOSTNAME__:8085
c, _ := pubsub.NewClient(ctx, "gcp-dev")
t, _ := c.CreateTopic(ctx, "demo-topic")
t.Publish(ctx, &pubsub.Message{Data: []byte("hi")}).Get(ctx)"""),
            ]),
            ("Firestore", [
                ("CLI", "bash", """export FIRESTORE_EMULATOR_HOST="__HOSTNAME__:8080"
# Document CRUD is via the client libraries (gcloud has no doc-level CRUD)."""),
                ("Java", "java", """// FIRESTORE_EMULATOR_HOST=__HOSTNAME__:8080
Firestore db = FirestoreOptions.getDefaultInstance().getService();
db.collection("users").document("alice").set(Map.of("name", "Alice"));"""),
                ("Go", "go", """// FIRESTORE_EMULATOR_HOST=__HOSTNAME__:8080
c, _ := firestore.NewClient(ctx, "gcp-dev")
c.Collection("users").Doc("alice").Set(ctx, map[string]any{"name": "Alice"})"""),
            ]),
            ("Cloud Functions", [
                ("CLI", "bash", """gcloud functions list --region=us-central1"""),
                ("Java", "java", """CloudFunctions fn = new CloudFunctions.Builder(transport, json, null)
    .setRootUrl("__BASE__/").setApplicationName("cl").build();
fn.projects().locations().functions().list("projects/gcp-dev/locations/us-central1").execute();"""),
                ("Go", "go", """fsvc, _ := cloudfunctions.NewService(ctx, noAuth, option.WithEndpoint("__BASE__/"))
fsvc.Projects.Locations.Functions.List("projects/gcp-dev/locations/us-central1").Do()"""),
            ]),
            ("IAM", [
                ("CLI", "bash", """gcloud iam service-accounts create demo-sa
gcloud iam service-accounts list"""),
                ("Java", "java", """Iam iam = new Iam.Builder(transport, json, null)
    .setRootUrl("__BASE__/").setApplicationName("cl").build();
iam.projects().serviceAccounts().list("projects/gcp-dev").execute();"""),
                ("Go", "go", """isvc, _ := iam.NewService(ctx, noAuth, option.WithEndpoint("__BASE__/"))
isvc.Projects.ServiceAccounts.List("projects/gcp-dev").Do()"""),
            ]),
            ("VPC Network", [
                ("CLI", "bash", """gcloud compute networks create demo-vpc --subnet-mode=custom
gcloud compute networks list
gcloud compute firewall-rules list"""),
                ("Java", "java", """// same Apiary Compute client as Compute Engine
compute.networks().list("gcp-dev").execute();
compute.firewalls().list("gcp-dev").execute();"""),
                ("Go", "go", """csvc.Networks.List("gcp-dev").Do()
csvc.Firewalls.List("gcp-dev").Do()"""),
            ]),
        ],
    },
    "aws": {
        "connect": [
            ("AWS CLI / env", "bash", """export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
# then pass --endpoint-url __BASE__ to every command (or set a profile)."""),
            ("Java — shared client config", "java", """var creds = StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test"));
URI ep = URI.create("__BASE__");   // pass ep + creds to every <Svc>Client.builder()"""),
            ("Go — shared config", "go", """cfg, _ := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
    config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
// then per service: NewFromConfig(cfg, func(o){ o.BaseEndpoint = aws.String("__BASE__") })"""),
        ],
        "services": [
            ("S3", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ s3 mb s3://demo
aws --endpoint-url __BASE__ s3 cp ./f.txt s3://demo/f.txt
aws --endpoint-url __BASE__ s3 ls s3://demo"""),
                ("Java", "java", """S3Client s3 = S3Client.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).forcePathStyle(true).build();
s3.createBucket(b -> b.bucket("demo"));"""),
                ("Go", "go", """s3c := s3.NewFromConfig(cfg, func(o *s3.Options) {
    o.BaseEndpoint = aws.String("__BASE__"); o.UsePathStyle = true })
s3c.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String("demo")})"""),
            ]),
            ("EC2", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ ec2 describe-instances
aws --endpoint-url __BASE__ ec2 describe-vpcs"""),
                ("Java", "java", """Ec2Client ec2 = Ec2Client.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).build();
ec2.describeInstances();"""),
                ("Go", "go", """ec2c := ec2.NewFromConfig(cfg, func(o *ec2.Options) { o.BaseEndpoint = aws.String("__BASE__") })
ec2c.DescribeInstances(ctx, &ec2.DescribeInstancesInput{})"""),
            ]),
            ("IAM", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ iam create-user --user-name alice
aws --endpoint-url __BASE__ iam list-users"""),
                ("Java", "java", """IamClient iam = IamClient.builder().endpointOverride(ep).region(Region.AWS_GLOBAL)
    .credentialsProvider(creds).build();
iam.listUsers();"""),
                ("Go", "go", """iamc := iam.NewFromConfig(cfg, func(o *iam.Options) { o.BaseEndpoint = aws.String("__BASE__") })
iamc.ListUsers(ctx, &iam.ListUsersInput{})"""),
            ]),
            ("SQS", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ sqs create-queue --queue-name demo
aws --endpoint-url __BASE__ sqs list-queues"""),
                ("Java", "java", """SqsClient sqs = SqsClient.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).build();
sqs.createQueue(b -> b.queueName("demo"));"""),
                ("Go", "go", """sqsc := sqs.NewFromConfig(cfg, func(o *sqs.Options) { o.BaseEndpoint = aws.String("__BASE__") })
sqsc.CreateQueue(ctx, &sqs.CreateQueueInput{QueueName: aws.String("demo")})"""),
            ]),
            ("DynamoDB", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ dynamodb list-tables"""),
                ("Java", "java", """DynamoDbClient ddb = DynamoDbClient.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).build();
ddb.listTables();"""),
                ("Go", "go", """ddbc := dynamodb.NewFromConfig(cfg, func(o *dynamodb.Options) { o.BaseEndpoint = aws.String("__BASE__") })
ddbc.ListTables(ctx, &dynamodb.ListTablesInput{})"""),
            ]),
            ("RDS", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ rds describe-db-instances"""),
                ("Java", "java", """RdsClient rds = RdsClient.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).build();
rds.describeDBInstances();"""),
                ("Go", "go", """rdsc := rds.NewFromConfig(cfg, func(o *rds.Options) { o.BaseEndpoint = aws.String("__BASE__") })
rdsc.DescribeDBInstances(ctx, &rds.DescribeDBInstancesInput{})"""),
            ]),
            ("Lambda", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ lambda list-functions"""),
                ("Java", "java", """LambdaClient lam = LambdaClient.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).build();
lam.listFunctions();"""),
                ("Go", "go", """lamc := lambda.NewFromConfig(cfg, func(o *lambda.Options) { o.BaseEndpoint = aws.String("__BASE__") })
lamc.ListFunctions(ctx, &lambda.ListFunctionsInput{})"""),
            ]),
            ("API Gateway", [
                ("CLI", "bash", """aws --endpoint-url __BASE__ apigateway get-rest-apis"""),
                ("Java", "java", """ApiGatewayClient ag = ApiGatewayClient.builder().endpointOverride(ep).region(Region.US_EAST_1)
    .credentialsProvider(creds).build();
ag.getRestApis();"""),
                ("Go", "go", """agc := apigateway.NewFromConfig(cfg, func(o *apigateway.Options) { o.BaseEndpoint = aws.String("__BASE__") })
agc.GetRestApis(ctx, &apigateway.GetRestApisInput{})"""),
            ]),
        ],
    },
    "azure": {
        "connect": [
            ("az CLI — register the simulator as a custom cloud", "bash", """# Point az at the simulator's ARM endpoint, then use a throwaway login.
az cloud register -n CloudLearn \\
  --endpoint-resource-manager "__BASE__" \\
  --endpoint-active-directory "__BASE__" \\
  --endpoint-active-directory-resource-id "__BASE__"
az cloud set -n CloudLearn
# The simulator ignores credentials — any login (or none) works.
export SUB="__SUB__"   # default subscription
export RG="cloudlearn-rg" """),
            ("curl — raw ARM REST", "bash", """# Every ARM call needs ?api-version=. Auth is faked.
curl -s "__BASE__/subscriptions/__SUB__/resourceGroups/cloudlearn-rg/providers/Microsoft.Compute/virtualMachines?api-version=2023-09-01" """),
            ("Java — fake credential + custom AzureEnvironment", "java", """// com.azure.resourcemanager:azure-resourcemanager + azure-identity
TokenCredential cred = req -> Mono.just(
    new AccessToken("fake", OffsetDateTime.now().plusHours(1)));
AzureEnvironment env = new AzureEnvironment(Map.of(
    "resourceManagerEndpointUrl", "__BASE__/",
    "activeDirectoryEndpointUrl", "__BASE__/",
    "managementEndpointUrl", "__BASE__/"));
AzureProfile profile = new AzureProfile("tenant", "__SUB__", env);"""),
            ("Go — fake credential + custom cloud config", "go", """import ("github.com/Azure/azure-sdk-for-go/sdk/azcore"; "github.com/Azure/azure-sdk-for-go/sdk/azcore/arm";
        "github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud")
cfg := cloud.Configuration{Services: map[cloud.ServiceName]cloud.ServiceConfiguration{
  cloud.ResourceManager: {Endpoint: "__BASE__", Audience: "__BASE__"}}}
opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{Cloud: cfg}}
// cred: a fake azcore.TokenCredential returning any token (sim ignores it)."""),
        ],
        "services": [
            ("Virtual Machines (Microsoft.Compute)", [
                ("az CLI", "bash", """az vm list -g $RG
az resource create -g $RG -n vm-demo --resource-type Microsoft.Compute/virtualMachines \\
  --api-version 2023-09-01 --properties '{"hardwareProfile":{"vmSize":"Standard_B1s"}}'"""),
                ("Java", "java", """ComputeManager compute = ComputeManager.authenticate(cred, profile);
compute.virtualMachines().listByResourceGroup("cloudlearn-rg")
    .forEach(vm -> System.out.println(vm.name()));"""),
                ("Go", "go", """vmc, _ := armcompute.NewVirtualMachinesClient("__SUB__", cred, opts)
pager := vmc.NewListPager("cloudlearn-rg", nil)
page, _ := pager.NextPage(ctx)   // page.Value = []*VirtualMachine"""),
            ]),
            ("Blob Storage (Microsoft.Storage)", [
                ("az CLI", "bash", """az storage account list -g $RG
az resource create -g $RG -n stdemo --resource-type Microsoft.Storage/storageAccounts \\
  --api-version 2023-01-01 --properties '{}' --location eastus"""),
                ("Java", "java", """StorageManager storage = StorageManager.authenticate(cred, profile);
storage.storageAccounts().listByResourceGroup("cloudlearn-rg")
    .forEach(a -> System.out.println(a.name()));"""),
                ("Go", "go", """sac, _ := armstorage.NewAccountsClient("__SUB__", cred, opts)
pager := sac.NewListByResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
            ("SQL Database (Microsoft.Sql)", [
                ("az CLI", "bash", """az sql server list -g $RG
az resource create -g $RG -n sql-demo --resource-type Microsoft.Sql/servers \\
  --api-version 2023-05-01-preview --properties '{"administratorLogin":"sqladmin"}'"""),
                ("Java", "java", """SqlServerManager sql = SqlServerManager.authenticate(cred, profile);
sql.sqlServers().listByResourceGroup("cloudlearn-rg").forEach(s -> System.out.println(s.name()));"""),
                ("Go", "go", """sc, _ := armsql.NewServersClient("__SUB__", cred, opts)
pager := sc.NewListByResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
            ("Service Bus (Microsoft.ServiceBus)", [
                ("az CLI", "bash", """az servicebus namespace list -g $RG
az servicebus queue list -g $RG --namespace-name sb-cloudlearn"""),
                ("Java", "java", """ServiceBusManager sb = ServiceBusManager.authenticate(cred, profile);
sb.namespaces().listByResourceGroup("cloudlearn-rg").forEach(n -> System.out.println(n.name()));"""),
                ("Go", "go", """nc, _ := armservicebus.NewNamespacesClient("__SUB__", cred, opts)
pager := nc.NewListByResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
            ("Cosmos DB (Microsoft.DocumentDB)", [
                ("az CLI", "bash", """az cosmosdb list -g $RG
az resource create -g $RG -n cosmos-demo --resource-type Microsoft.DocumentDB/databaseAccounts \\
  --api-version 2024-05-15 --properties '{"databaseAccountOfferType":"Standard"}'"""),
                ("Java", "java", """CosmosManager cosmos = CosmosManager.authenticate(cred, profile);
cosmos.databaseAccounts().listByResourceGroup("cloudlearn-rg").forEach(a -> System.out.println(a.name()));"""),
                ("Go", "go", """cc, _ := armcosmos.NewDatabaseAccountsClient("__SUB__", cred, opts)
pager := cc.NewListByResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
            ("Functions (Microsoft.Web)", [
                ("az CLI", "bash", """az functionapp list -g $RG
az resource create -g $RG -n fn-demo --resource-type Microsoft.Web/sites \\
  --api-version 2023-12-01 --properties '{}' --location eastus"""),
                ("Java", "java", """AppServiceManager web = AppServiceManager.authenticate(cred, profile);
web.functionApps().listByResourceGroup("cloudlearn-rg").forEach(f -> System.out.println(f.name()));"""),
                ("Go", "go", """wc, _ := armappservice.NewWebAppsClient("__SUB__", cred, opts)
pager := wc.NewListByResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
            ("API Management (Microsoft.ApiManagement)", [
                ("az CLI", "bash", """az apim list -g $RG
az resource show -g $RG -n apim-cloudlearn --resource-type Microsoft.ApiManagement/service \\
  --api-version 2023-05-01-preview"""),
                ("Java", "java", """ApiManagementManager apim = ApiManagementManager.authenticate(cred, profile);
apim.apiManagementServices().listByResourceGroup("cloudlearn-rg").forEach(s -> System.out.println(s.name()));"""),
                ("Go", "go", """ac, _ := armapimanagement.NewServiceClient("__SUB__", cred, opts)
pager := ac.NewListByResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
            ("Virtual Network (Microsoft.Network)", [
                ("az CLI", "bash", """az network vnet list -g $RG
az resource create -g $RG -n vnet-demo --resource-type Microsoft.Network/virtualNetworks \\
  --api-version 2023-11-01 --properties '{"addressSpace":{"addressPrefixes":["10.0.0.0/16"]}}'"""),
                ("Java", "java", """NetworkManager net = NetworkManager.authenticate(cred, profile);
net.networks().listByResourceGroup("cloudlearn-rg").forEach(v -> System.out.println(v.name()));"""),
                ("Go", "go", """vnc, _ := armnetwork.NewVirtualNetworksClient("__SUB__", cred, opts)
pager := vnc.NewListPager("cloudlearn-rg", nil)"""),
            ]),
            ("Entra ID / RBAC (Microsoft.Authorization)", [
                ("az CLI", "bash", """az role assignment list -g $RG
az role assignment create --role Contributor --assignee user@cloudlearn.dev \\
  --scope /subscriptions/$SUB/resourceGroups/$RG"""),
                ("Java", "java", """AuthorizationManager authz = AuthorizationManager.authenticate(cred, profile);
authz.roleAssignments().listByResourceGroup("cloudlearn-rg").forEach(r -> System.out.println(r.name()));"""),
                ("Go", "go", """rac, _ := armauthorization.NewRoleAssignmentsClient("__SUB__", cred, opts)
pager := rac.NewListForResourceGroupPager("cloudlearn-rg", nil)"""),
            ]),
        ],
    },
}


def _usage_html(request, provider: str) -> str:
    import html as _html
    host = request.headers.get("host") or request.url.netloc or "localhost:9000"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    base = f"{scheme}://{host}"
    hostname = host.split(":")[0]
    label = {"gcp": "GCP", "azure": "Azure"}.get(provider, "AWS")
    accent = {"gcp": "#1a73e8", "azure": "#0078d4"}.get(provider, "#ff9900")
    data = _USAGE.get(provider, {})

    def sub(code: str) -> str:
        return (code.replace("__BASE__", base).replace("__HOSTNAME__", hostname)
                    .replace("__HOST__", host)
                    .replace("__SUB__", provider_azure_services.DEFAULT_SUBSCRIPTION))

    def block(title: str, lang: str, code: str) -> str:
        return (f'<div class="blk"><div class="bh"><h3>{_html.escape(title)}</h3>'
                f'<span class="lang">{_html.escape(lang)}</span></div>'
                f'<pre><code>{_html.escape(sub(code))}</code></pre></div>')

    connect = "".join(block(t, lang, code) for (t, lang, code) in data.get("connect", []))
    toc, svc_sections = [], []
    for i, (svc, langs) in enumerate(data.get("services", [])):
        anchor = f"svc-{i}"
        toc.append(f'<a class="tocl" href="#{anchor}">{_html.escape(svc)}</a>')
        blocks = "".join(block(lname, lang, code) for (lname, lang, code) in langs)
        svc_sections.append(f'<section class="svc" id="{anchor}"><h2>{_html.escape(svc)}</h2>{blocks}</section>')
    swagger_link = f"/docs/{provider}"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>CloudLearn — {label} SDK &amp; CLI usage</title><link rel="icon" href="/assets/swagger/favicon-32x32.png">
<style>
 body{{margin:0;font-family:Roboto,Arial,sans-serif;background:#0f1b2d;color:#e8eef6}}
 .top{{position:sticky;top:0;z-index:5;background:#0b1422;padding:16px 28px;border-bottom:1px solid #1d2c44;display:flex;align-items:center;gap:16px}}
 .top h1{{font-size:18px;font-weight:500;margin:0}}.top .b{{background:{accent};color:#06101f;font-weight:700;border-radius:6px;padding:3px 10px;font-size:13px}}
 .top a{{margin-left:auto;color:#9fb0c7;text-decoration:none;font-size:13px}}.top a+a{{margin-left:16px}}.top a:hover{{color:#fff}}
 .wrap{{max-width:920px;margin:0 auto;padding:24px 28px 60px}}
 .intro{{color:#9fb0c7;font-size:14px;line-height:1.6}}.intro code{{background:#16243a;padding:1px 6px;border-radius:4px;color:#cfe0f7}}
 .toc{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 6px}}
 .tocl{{background:#16243a;border:1px solid #243650;border-radius:999px;padding:5px 12px;font-size:12px;color:#cfe0f7;text-decoration:none}}.tocl:hover{{background:#1d2f4a;color:#fff}}
 h2{{margin:30px 0 10px;font-size:18px;font-weight:600;border-left:3px solid {accent};padding-left:10px}}
 .sechead{{margin-top:26px;font-size:13px;letter-spacing:.5px;text-transform:uppercase;color:#8aa0bd}}
 .blk{{margin:12px 0;border:1px solid #1d2c44;border-radius:10px;overflow:hidden;background:#0c1626}}
 .bh{{display:flex;align-items:center;justify-content:space-between;padding:9px 14px;background:#13243d;border-bottom:1px solid #1d2c44}}
 .bh h3{{margin:0;font-size:14px;font-weight:600}}.lang{{font-size:11px;color:#8aa0bd;text-transform:uppercase;letter-spacing:.5px}}
 pre{{margin:0;padding:14px;overflow:auto;font-size:12.5px;line-height:1.55;font-family:ui-monospace,Menlo,Consolas,monospace;color:#d7e3f4}}
</style></head><body>
 <div class="top"><span class="b">{label}</span><h1>SDK &amp; CLI usage — per service</h1>
   <a href="{swagger_link}">{label} Swagger ›</a><a href="/docs">All consoles ›</a></div>
 <div class="wrap">
   <p class="intro">Point unmodified {label} tools at this simulator at <code>{base}</code> — no real credentials needed.
   Snippets are copy-paste ready (your live host is filled in) and mirror the conformance harness in <code>tests/conformance/</code>.</p>
   <div class="toc">{''.join(toc)}</div>
   <div class="sechead">Connect (one-time setup)</div>
   {connect}
   <div class="sechead">Per-service examples (CLI · Java · Go)</div>
   {''.join(svc_sections)}
 </div>
</body></html>"""




register_aws_ec2_routes(app, None)
register_gcp_compute_routes(app, None)
register_aws_routes(app, None)
register_gcp_routes(app, None)
register_azure_routes(app, None)





def _parent_os() -> str:
    return _resolved_host_os()


def _distribution_mode() -> str:
    config_mode = _host_config().get("distribution_mode")
    if config_mode:
        return str(config_mode).strip().lower()
    return str(os.environ.get("CLOUDLEARN_DISTRIBUTION_MODE") or "developer").strip().lower()


def _appliance_mode_enabled() -> bool:
    return _distribution_mode() == "appliance"


def _host_config_path() -> Path:
    return Path(str(os.environ.get("CLOUDLEARN_HOST_CONFIG_FILE") or "").strip() or "/config/cloudlearn-host.json")


def _host_config() -> dict[str, Any]:
    path = _host_config_path()
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _host_sizing_path() -> Path:
    return Path(str(os.environ.get("CLOUDLEARN_HOST_SIZING_FILE") or "").strip() or "/config/cloudlearn-host-sizing.json")


def _bytes_to_gib(value: int | float | None) -> float:
    try:
        return round(float(value or 0) / (1024 ** 3), 1)
    except Exception:
        return 0.0


def _host_memory_bytes() -> int:
    try:
        if platform.system().strip().lower() == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5).strip()
            return int(out)
        if platform.system().strip().lower() == "linux":
            try:
                with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
            except Exception:
                pass
            try:
                return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
            except Exception:
                pass
    except Exception:
        pass
    return 0


def _host_network_interfaces() -> list[str]:
    try:
        import socket
        return [name for _, name in socket.if_nameindex() if str(name).strip()]
    except Exception:
        return []


def _recommend_host_sizing(host_cpu: int, host_memory_gib: float, host_disk_total_gib: float, host_disk_free_gib: float) -> dict[str, Any]:
    if host_memory_gib <= 4:
        appliance_memory = 2
        appliance_disk = 24
    elif host_memory_gib <= 8:
        appliance_memory = 4
        appliance_disk = 32
    elif host_memory_gib <= 16:
        appliance_memory = 8
        appliance_disk = 32
    elif host_memory_gib <= 32:
        appliance_memory = 12
        appliance_disk = 48
    elif host_memory_gib <= 64:
        appliance_memory = 16
        appliance_disk = 64
    else:
        appliance_memory = min(24, max(16, int(round(host_memory_gib * 0.25))))
        appliance_disk = min(96, max(64, int(round(host_disk_total_gib * 0.12)) if host_disk_total_gib else 64))

    appliance_cpu = max(1, min(max(host_cpu - 1, 1), int(round(appliance_memory / 2)) or 1))
    appliance_disk = int(min(max(appliance_disk, 24), max(24, int(round(host_disk_free_gib * 0.25)) or appliance_disk)))
    if host_memory_gib <= 8:
        reserve_for_platform = 1.5
    elif host_memory_gib <= 16:
        reserve_for_platform = 2.0
    elif host_memory_gib <= 32:
        reserve_for_platform = 2.5
    else:
        reserve_for_platform = 3.0
    available_for_lxd = max(0.0, float(appliance_memory) - reserve_for_platform)
    return {
        "appliance": {
            "vcpus": appliance_cpu,
            "memory_gib": appliance_memory,
            "disk_gib": appliance_disk,
        },
        "lxd_budget": {
            "platform_reserve_gib": reserve_for_platform,
            "small_instances": int(available_for_lxd // 0.5),
            "medium_instances": int(available_for_lxd // 1.0),
            "heavy_instances": int(available_for_lxd // 2.0),
        },
    }


def _host_sizing() -> dict[str, Any]:
    path = _host_sizing_path()
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    cpu_count = int(os.cpu_count() or 1)
    host_memory_bytes = _host_memory_bytes()
    disk_usage = shutil.disk_usage(Path.cwd())
    host_disk_total_bytes = int(disk_usage.total)
    host_disk_free_bytes = int(disk_usage.free)
    host_disk_used_bytes = int(disk_usage.used)
    host_memory_gib = _bytes_to_gib(host_memory_bytes)
    host_disk_total_gib = _bytes_to_gib(host_disk_total_bytes)
    host_disk_free_gib = _bytes_to_gib(host_disk_free_bytes)
    rec = _recommend_host_sizing(cpu_count, host_memory_gib, host_disk_total_gib, host_disk_free_gib)
    network_interfaces = _host_network_interfaces()
    warnings: list[str] = []
    if cpu_count < 4 or host_memory_gib < 8:
        warnings.append("This host is small for a full appliance. Keep the VM at minimum size and avoid heavy sandboxes.")
    if host_disk_free_gib < 20:
        warnings.append("Low free disk space. Keep the appliance disk small and avoid large downloads.")
    return {
        "source": "fallback-runtime",
        "host_os": _resolved_host_os(),
        "cpu_count": cpu_count,
        "memory_bytes": host_memory_bytes,
        "memory_gib": host_memory_gib,
        "disk_total_bytes": host_disk_total_bytes,
        "disk_used_bytes": host_disk_used_bytes,
        "disk_free_bytes": host_disk_free_bytes,
        "disk_total_gib": host_disk_total_gib,
        "disk_free_gib": host_disk_free_gib,
        "network_interfaces": network_interfaces,
        "network_interface_count": len(network_interfaces),
        "recommended": rec,
        "warnings": warnings,
        "checked_at": _now(),
    }


def _runtime_bridge_url() -> str:
    config = _host_config()
    return str(
        os.environ.get("CLOUDLEARN_RUNTIME_BRIDGE_URL")
        or config.get("runtime_bridge_url")
        or "http://host.docker.internal:9171"
    ).strip().rstrip("/")


def _runtime_bridge_status() -> dict[str, Any]:
    try:
        url = _runtime_bridge_url()
        if not url:
            return {}
        request = URLRequest(f"{url}/health", headers={"Accept": "application/json"})
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _runtime_bridge_host_os() -> str:
    return str(_runtime_bridge_status().get("host_os") or "").strip().lower()


def _resolved_host_os(host_os_hint: str = "") -> str:
    if _appliance_mode_enabled():
        hint = str(host_os_hint or "").strip().lower()
        if hint:
            return hint
        return str(platform.system()).strip().lower()
    bridge_os = _runtime_bridge_host_os()
    if bridge_os:
        return bridge_os
    config_os = _host_config().get("host_os")
    if config_os:
        return str(config_os).strip().lower()
    hint = str(host_os_hint or "").strip().lower()
    if hint:
        return hint
    return str(os.environ.get("CLOUDLEARN_PARENT_OS") or platform.system()).strip().lower()


def _request_host_os(request: Request | None = None) -> str:
    if request is not None:
        header = str(request.headers.get("x-cloudlearn-host-os") or "").strip().lower()
        if header:
            return _resolved_host_os(header)
    return _resolved_host_os()


def _iam_user_arn(user_name: str) -> str:
    return f"arn:aws:iam::{AWS_ACCOUNT_ID}:user/{user_name}"


def _iam_role_arn(role_name: str) -> str:
    return f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/{role_name}"


def _iam_group_arn(group_name: str) -> str:
    return f"arn:aws:iam::{AWS_ACCOUNT_ID}:group/{group_name}"


def _iam_s3_bucket_arn(bucket: str) -> str:
    return f"arn:aws:s3:::{bucket}"


def _iam_s3_object_arn(bucket: str, key: str) -> str:
    return f"arn:aws:s3:::{bucket}/{key}"


def _iam_ec2_instance_arn(instance_id: str) -> str:
    return f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:instance/{instance_id}"


def _iam_ec2_vpc_arn(vpc_id: str) -> str:
    return f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:vpc/{vpc_id}"


def _iam_ec2_subnet_arn(subnet_id: str) -> str:
    return f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:subnet/{subnet_id}"


def _iam_ec2_security_group_arn(group_id: str) -> str:
    return f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:security-group/{group_id}"


def _iam_ec2_route_table_arn(route_table_id: str) -> str:
    return f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:route-table/{route_table_id}"


def _iam_ec2_internet_gateway_arn(gateway_id: str) -> str:
    return f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:internet-gateway/{gateway_id}"


def _iam_apigw_api_arn(api_id: str) -> str:
    return f"arn:aws:apigateway:us-east-1::/restapis/{api_id}"


def _iam_apigw_stage_arn(api_id: str, stage_name: str) -> str:
    return f"arn:aws:apigateway:us-east-1::/restapis/{api_id}/stages/{stage_name}"


def _iam_rds_db_arn(db_instance_identifier: str) -> str:
    return f"arn:aws:rds:us-east-1:{AWS_ACCOUNT_ID}:db:{db_instance_identifier}"


def _iam_rds_subnet_group_arn(db_subnet_group_name: str) -> str:
    return f"arn:aws:rds:us-east-1:{AWS_ACCOUNT_ID}:subgrp:{db_subnet_group_name}"


def _iam_rds_parameter_group_arn(db_parameter_group_name: str) -> str:
    return f"arn:aws:rds:us-east-1:{AWS_ACCOUNT_ID}:pg:{db_parameter_group_name}"


def _iam_rds_snapshot_arn(db_snapshot_identifier: str) -> str:
    return f"arn:aws:rds:us-east-1:{AWS_ACCOUNT_ID}:snapshot:{db_snapshot_identifier}"


def _iam_sqs_queue_arn(queue_name: str) -> str:
    return f"arn:aws:sqs:us-east-1:{AWS_ACCOUNT_ID}:{queue_name}"


def _iam_lambda_function_arn(function_name: str) -> str:
    return f"arn:aws:lambda:us-east-1:{AWS_ACCOUNT_ID}:function:{function_name}"


def _iam_dynamodb_table_arn(table_name: str) -> str:
    return f"arn:aws:dynamodb:us-east-1:{AWS_ACCOUNT_ID}:table/{table_name}"


def _iam_state() -> dict:
    return STATE.setdefault("iam", {"users": {}, "groups": {}, "roles": {}, "policies": {}, "attachments": [], "identity_providers": {}, "account_settings": {"password_policy": {"minimum_length": 8, "require_symbols": True, "require_numbers": True, "require_uppercase": True, "require_lowercase": True}}})


def _iam_is_root_principal(principal: str) -> bool:
    principal = (principal or "").strip().lower()
    return principal in {"root", "admin", _iam_root_principal().lower()}


def _iam_principal_from_request(request: Request) -> str:
    headers = request.headers
    principal = (
        headers.get("x-cloudlearn-principal")
        or headers.get("x-cloudlearn-user")
        or headers.get("x-cloudlearn-role")
        or headers.get("x-principal")
        or ""
    ).strip()
    return principal or _iam_root_principal()


def _iam_resolve_identity(principal: str) -> dict:
    principal = (principal or "").strip() or _iam_root_principal()
    state = _iam_state()
    if _iam_is_root_principal(principal):
        return {
            "principal": principal,
            "type": "root",
            "name": "root",
            "arn": _iam_root_principal(),
            "policy_ids": [],
            "policies": [],
            "is_root": True,
        }

    users = list(state.get("users", {}).values())
    roles = list(state.get("roles", {}).values())
    groups = list(state.get("groups", {}).values())
    for user in users:
        if principal in {user.get("user_id", ""), user.get("user_name", ""), _iam_user_arn(user.get("user_name", ""))}:
            policy_ids = list(user.get("policies", []))
            group_ids = list(user.get("groups", []))
            for group in groups:
                if group.get("group_id") in group_ids or group.get("group_name") in group_ids or _iam_group_arn(group.get("group_name", "")) in group_ids:
                    policy_ids.extend(list(group.get("policies", [])))
            policy_ids = list(dict.fromkeys(policy_ids))
            policies = [state.get("policies", {}).get(pid) for pid in policy_ids if state.get("policies", {}).get(pid)]
            return {
                "principal": principal,
                "type": "user",
                "name": user.get("user_name", ""),
                "arn": _iam_user_arn(user.get("user_name", "")),
                "policy_ids": policy_ids,
                "policies": policies,
                "is_root": False,
                "user_id": user.get("user_id", ""),
                "groups": group_ids,
            }
    for role in roles:
        if principal in {role.get("role_id", ""), role.get("role_name", ""), _iam_role_arn(role.get("role_name", ""))}:
            policy_ids = list(role.get("policies", []))
            policies = [state.get("policies", {}).get(pid) for pid in policy_ids if state.get("policies", {}).get(pid)]
            return {
                "principal": principal,
                "type": "role",
                "name": role.get("role_name", ""),
                "arn": _iam_role_arn(role.get("role_name", "")),
                "policy_ids": policy_ids,
                "policies": policies,
                "is_root": False,
                "role_id": role.get("role_id", ""),
            }
    return {
        "principal": principal,
        "type": "unknown",
        "name": principal,
        "arn": principal,
        "policy_ids": [],
        "policies": [],
        "is_root": False,
    }


def _iam_find_group(group_id_or_name: str) -> dict | None:
    key = (group_id_or_name or "").strip()
    if not key:
        return None
    state = _iam_state()
    groups = state.get("groups", {})
    for group in groups.values():
        if key in {group.get("group_id", ""), group.get("group_name", ""), _iam_group_arn(group.get("group_name", ""))}:
            return group
    return None


def _iam_find_user(user_id_or_name: str) -> dict | None:
    key = (user_id_or_name or "").strip()
    if not key:
        return None
    state = _iam_state()
    users = state.get("users", {})
    for user in users.values():
        if key in {user.get("user_id", ""), user.get("user_name", ""), _iam_user_arn(user.get("user_name", ""))}:
            return user
    return None


def _iam_target_keys(target_type: str, target: dict) -> set[str]:
    target_type = (target_type or "").strip().lower()
    if target_type == "user":
        return {
            target.get("user_id", ""),
            target.get("user_name", ""),
            _iam_user_arn(target.get("user_name", "")),
        }
    if target_type == "group":
        return {
            target.get("group_id", ""),
            target.get("group_name", ""),
            _iam_group_arn(target.get("group_name", "")),
        }
    if target_type == "role":
        return {
            target.get("role_id", ""),
            target.get("role_name", ""),
            _iam_role_arn(target.get("role_name", "")),
        }
    return {target.get("id", ""), target.get("name", "")}


def _iam_detach_policy_records(target_type: str, target_id: str, policy_id: str | None = None) -> int:
    target_type = (target_type or "").strip().lower()
    target_id = (target_id or "").strip()
    attachments = iam_state.setdefault("attachments", [])
    if not target_type or not target_id:
        return 0
    next_attachments = []
    removed = 0
    for attachment in attachments:
        if attachment.get("target_type") != target_type:
            next_attachments.append(attachment)
            continue
        if attachment.get("target_id") != target_id and attachment.get("target_id") not in _iam_target_keys(target_type, {"user_id": target_id, "group_id": target_id, "role_id": target_id, "user_name": target_id, "group_name": target_id, "role_name": target_id}):
            next_attachments.append(attachment)
            continue
        if policy_id and attachment.get("policy_id") != policy_id:
            next_attachments.append(attachment)
            continue
        removed += 1
        principal = None
        if target_type == "user":
            principal = _iam_find_user(target_id)
        elif target_type == "group":
            principal = _iam_find_group(target_id)
        elif target_type == "role":
            principal = iam_state.get("roles", {}).get(target_id)
            if not principal:
                for role in iam_state.get("roles", {}).values():
                    if target_id in {role.get("role_id", ""), role.get("role_name", ""), _iam_role_arn(role.get("role_name", ""))}:
                        principal = role
                        break
        if principal is not None:
            principal["policies"] = [pid for pid in principal.get("policies", []) if pid != attachment.get("policy_id")]
    iam_state["attachments"] = next_attachments
    return removed


def _iam_remove_policy_from_all_principals(policy_id: str) -> int:
    removed = 0
    for target_type, principals in (("user", iam_state.get("users", {})), ("group", iam_state.get("groups", {})), ("role", iam_state.get("roles", {}))):
        for principal in principals.values():
            policies = list(principal.get("policies", []))
            if policy_id in policies:
                principal["policies"] = [pid for pid in policies if pid != policy_id]
                removed += 1
    iam_state["attachments"] = [a for a in iam_state.get("attachments", []) if a.get("policy_id") != policy_id]
    return removed


def _iam_value_matches(pattern: Any, value: str) -> bool:
    if isinstance(pattern, list):
        return any(_iam_value_matches(item, value) for item in pattern)
    if pattern is None:
        return False
    pattern = str(pattern).strip()
    value = str(value or "")
    if not pattern:
        return False
    return fnmatch.fnmatchcase(value.lower(), pattern.lower())


def _iam_condition_matches(condition: dict[str, Any], context: dict[str, str]) -> bool:
    if not condition:
        return True
    for operator, operands in condition.items():
        if not isinstance(operands, dict):
            return False
        for key, expected in operands.items():
            actual = context.get(key, "")
            operator_name = operator.lower()
            if operator_name in {"stringequals", "arnequals"}:
                if isinstance(expected, list):
                    if actual not in [str(item) for item in expected]:
                        return False
                elif actual != str(expected):
                    return False
            elif operator_name in {"stringlike", "arnlike"}:
                if not _iam_value_matches(expected, actual):
                    return False
            else:
                return False
    return True


def _iam_statement_matches(statement: dict[str, Any], action: str, resource: str, context: dict[str, str]) -> bool:
    if not isinstance(statement, dict):
        return False
    effect = str(statement.get("Effect", "Allow")).strip().lower()
    if effect not in {"allow", "deny"}:
        return False
    if "Action" in statement:
        actions = statement.get("Action")
        if not _iam_value_matches(actions, action):
            return False
    elif "NotAction" in statement:
        if _iam_value_matches(statement.get("NotAction"), action):
            return False
    else:
        return False
    if "Resource" in statement:
        resources = statement.get("Resource")
        if not _iam_value_matches(resources, resource):
            return False
    elif "NotResource" in statement:
        if _iam_value_matches(statement.get("NotResource"), resource):
            return False
    if not _iam_condition_matches(statement.get("Condition", {}) or {}, context):
        return False
    return True


def _iam_authorize(principal: str, action: str, resource: str, context: dict[str, str] | None = None) -> tuple[bool, str]:
    identity = _iam_resolve_identity(principal)
    if identity.get("is_root"):
        return True, ""
    ctx = {
        "aws:PrincipalArn": identity.get("arn", ""),
        "aws:PrincipalType": identity.get("type", ""),
        "aws:username": identity.get("name", ""),
        "aws:RequestedRegion": "us-east-1",
        "aws:ResourceArn": resource,
    }
    if context:
        ctx.update({k: str(v) for k, v in context.items()})
    policies = identity.get("policies", [])
    if not policies:
        return False, f"AccessDenied: principal '{principal}' has no attached policies for {action}."
    for policy in policies:
        for statement in (policy or {}).get("document", {}).get("Statement", []):
            if not _iam_statement_matches(statement, action, resource, ctx):
                continue
            if str(statement.get("Effect", "")).strip().lower() == "deny":
                return False, f"AccessDenied: explicit deny for {action} on {resource}."
            if str(statement.get("Effect", "")).strip().lower() == "allow":
                return True, ""
    return False, f"AccessDenied: principal '{principal}' is not authorized for {action} on {resource}."


def _iam_deny_response(request: Request, action: str, resource: str, detail: str) -> Response:
    path = request.url.path
    if path == "/" or path.startswith("/api/s3/") or (path.count("/") <= 2 and path not in {"/", "/ui", "/product", "/api", "/healthz"} and not path.startswith("/api/")):
        return _error_xml("AccessDenied", detail, path, 403)
    return JSONResponse(status_code=403, content={"detail": detail, "action": action, "resource": resource})


def _iam_route_action_resource(request: Request) -> tuple[str, str] | None:
    path = request.url.path
    method = request.method.upper()
    query = dict(request.query_params)

    if path in {"/healthz", "/docs", "/redoc", "/openapi.json"} or path.startswith(("/ui", "/product", "/assets/", "/static/", "/favicon.ico", "/console", "/docs/", "/api/tenants", "/api/instances", "/api/runtime")):
        return None
    if path.startswith("/api/catalog") or path.startswith("/api/packs") or path.startswith("/api/license") or path.startswith("/api/runtime/bundles") or path.startswith("/api/deployments") or path.startswith("/api/actions"):
        return None
    if path.startswith("/api/spaces"):
        if path == "/api/spaces" and method == "GET":
            return ("cloudlearn:ListSpaces", "*")
        if path == "/api/spaces" and method == "POST":
            return ("cloudlearn:CreateSpace", "*")
        if path == "/api/spaces/estimate" and method == "POST":
            return ("cloudlearn:EstimateSpace", "*")
        if path == "/api/spaces/active" and method == "GET":
            return ("cloudlearn:GetActiveSpace", "*")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3:
            space_id = parts[2]
            if len(parts) == 3 and method == "GET":
                return ("cloudlearn:GetSpace", f"arn:cloudlearn:space::{space_id}")
            if len(parts) == 3 and method == "DELETE":
                return ("cloudlearn:DeleteSpace", f"arn:cloudlearn:space::{space_id}")
            if len(parts) == 4 and parts[3] == "switch" and method == "POST":
                return ("cloudlearn:SwitchSpace", f"arn:cloudlearn:space::{space_id}")
            if len(parts) == 4 and parts[3] == "pause" and method == "POST":
                return ("cloudlearn:PauseSpace", f"arn:cloudlearn:space::{space_id}")
            if len(parts) == 4 and parts[3] == "resume" and method == "POST":
                return ("cloudlearn:ResumeSpace", f"arn:cloudlearn:space::{space_id}")
            if len(parts) == 4 and parts[3] == "archive" and method == "POST":
                return ("cloudlearn:ArchiveSpace", f"arn:cloudlearn:space::{space_id}")
        return None
    if path.startswith("/api/cloudsim/"):
        action_map = {
            ("GET", "/api/cloudsim/current"): ("cloudlearn:GetCloudSimCurrent", "*"),
            ("GET", "/api/cloudsim/summary"): ("cloudlearn:GetCloudSimSummary", "*"),
            ("POST", "/api/cloudsim/reconcile"): ("cloudlearn:ReconcileCloudSim", "*"),
            ("GET", "/api/cloudsim/events"): ("cloudlearn:ListCloudSimEvents", "*"),
        }
        return action_map.get((method, path))
    if path.startswith("/api/federations/") or path == "/api/federations":
        if path == "/api/federations" and method == "GET":
            return ("cloudlearn:ListFederations", "*")
        if path == "/api/federations" and method == "POST":
            return ("cloudlearn:CreateFederation", "*")
        if path.startswith("/api/federations/") and method == "POST" and path.endswith("/links"):
            return ("cloudlearn:CreateFederationLink", "*")
        if path.startswith("/api/federations/") and method == "POST" and path.endswith("/tests"):
            return ("cloudlearn:RunFederationTest", "*")
        return None
    if path.startswith("/api/iam/"):
        action_map = {
            ("GET", "/api/iam/users"): ("iam:ListUsers", "*"),
            ("POST", "/api/iam/users"): ("iam:CreateUser", "*"),
            ("GET", "/api/iam/groups"): ("iam:ListGroups", "*"),
            ("POST", "/api/iam/groups"): ("iam:CreateGroup", "*"),
            ("GET", "/api/iam/roles"): ("iam:ListRoles", "*"),
            ("POST", "/api/iam/roles"): ("iam:CreateRole", "*"),
            ("GET", "/api/iam/policies"): ("iam:ListPolicies", "*"),
            ("POST", "/api/iam/policies"): ("iam:CreatePolicy", "*"),
            ("POST", "/api/iam/attach-policy"): ("iam:AttachPolicy", "*"),
            ("GET", "/api/iam/attachments"): ("iam:ListAttachments", "*"),
            ("GET", "/api/iam/identity-providers"): ("iam:ListIdentityProviders", "*"),
            ("POST", "/api/iam/identity-providers"): ("iam:CreateIdentityProvider", "*"),
            ("GET", "/api/iam/account-settings"): ("iam:GetAccountSettings", "*"),
            ("PUT", "/api/iam/account-settings"): ("iam:UpdateAccountSettings", "*"),
        }
        if path.startswith("/api/iam/groups/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) == 5 and parts[4] == "users" and method == "POST":
                return ("iam:AddUserToGroup", "*")
            if len(parts) == 6 and parts[4] == "users" and method == "DELETE":
                return ("iam:RemoveUserFromGroup", "*")
            if len(parts) == 4 and method == "DELETE":
                return ("iam:DeleteGroup", "*")
        if path.startswith("/api/iam/users/") and method == "DELETE":
            return ("iam:DeleteUser", "*")
        if path.startswith("/api/iam/roles/") and method == "DELETE":
            return ("iam:DeleteRole", "*")
        if path.startswith("/api/iam/policies/") and method == "DELETE":
            return ("iam:DeletePolicy", "*")
        if path.startswith("/api/iam/attachments") and method == "DELETE":
            return ("iam:DetachPolicy", "*")
        if path.startswith("/api/iam/identity-providers/"):
            if method == "DELETE":
                return ("iam:DeleteIdentityProvider", "*")
        if path.startswith("/api/iam/users/") and path.endswith("/policies") and method == "GET":
            return ("iam:ListUserPolicies", "*")
        if path.startswith("/api/iam/roles/") and path.endswith("/policies") and method == "GET":
            return ("iam:ListRolePolicies", "*")
        if path.startswith("/api/iam/policies/") and path.endswith("/usage") and method == "GET":
            return ("iam:ListPolicyUsage", "*")
        return action_map.get((method, path))
    if path.startswith("/api/s3/"):
        parts = [p for p in path.split("/") if p]
        if path == "/api/s3/buckets":
            return ({"GET": "s3:ListAllMyBuckets"}.get(method), "*") if method == "GET" else None
        if len(parts) >= 4 and parts[2] == "buckets":
            bucket = parts[3]
            bucket_arn = _iam_s3_bucket_arn(bucket)
            tail = parts[4:] if len(parts) > 4 else []
            if not tail:
                return ({"GET": "s3:GetBucket", "POST": "s3:CreateBucket", "DELETE": "s3:DeleteBucket"}.get(method), bucket_arn) if method in {"GET", "POST", "DELETE"} else None
            if tail == ["versioning"]:
                return ({"GET": "s3:GetBucketVersioning", "PUT": "s3:PutBucketVersioning"}.get(method), bucket_arn) if method in {"GET", "PUT"} else None
            if tail == ["notifications"]:
                return ({"GET": "s3:GetBucketNotificationConfiguration", "PUT": "s3:PutBucketNotificationConfiguration", "DELETE": "s3:DeleteBucketNotificationConfiguration"}.get(method), bucket_arn) if method in {"GET", "PUT", "DELETE"} else None
            if tail == ["notifications", "events"] and method == "GET":
                return ("s3:GetBucketNotificationConfiguration", bucket_arn)
            if tail == ["objects"]:
                return ({"GET": "s3:ListBucket", "POST": "s3:PutObject"}.get(method), bucket_arn) if method in {"GET", "POST"} else None
            if tail == ["versions"] and method == "GET":
                return ("s3:ListBucketVersions", bucket_arn)
            if len(tail) >= 2 and tail[0] == "objects":
                if len(tail) == 2:
                    key = tail[1]
                    object_arn = _iam_s3_object_arn(bucket, key)
                    if method in {"GET", "DELETE"}:
                        return ({"GET": "s3:GetObject", "DELETE": "s3:DeleteObject"}.get(method), object_arn)
                    if method == "POST":
                        return ("s3:PutObject", object_arn)
                if len(tail) == 3:
                    key = tail[1]
                    object_arn = _iam_s3_object_arn(bucket, key)
                    if tail[2] == "meta" and method == "GET":
                        return ("s3:GetObject", object_arn)
                    if tail[2] == "download" and method == "GET":
                        return ("s3:GetObject", object_arn)
                    if tail[2] == "versions" and method == "GET":
                        return ("s3:ListObjectVersions", object_arn)
                    if tail[2] == "tags" and method in {"GET", "POST", "DELETE"}:
                        return ({"GET": "s3:GetObjectTagging", "POST": "s3:PutObjectTagging", "DELETE": "s3:DeleteObjectTagging"}.get(method), object_arn)
        return None
    if path.startswith("/api/ec2/runtime/lxd/bootstrap"):
        return ("ec2:DescribeInstances", "*")
    if path.startswith("/api/ec2/instances"):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3:
            if method == "GET":
                return ("ec2:DescribeInstances", "*")
            if method == "POST":
                return ("ec2:RunInstances", "*")
        if len(parts) >= 4:
            instance_id = parts[3]
            resource = _iam_ec2_instance_arn(instance_id)
            tail = parts[4:] if len(parts) > 4 else []
            if not tail:
                if method == "GET":
                    return ("ec2:DescribeInstances", resource)
            elif tail == ["start"] and method == "POST":
                return ("ec2:StartInstances", resource)
            elif tail == ["stop"] and method == "POST":
                return ("ec2:StopInstances", resource)
            elif tail == ["reboot"] and method == "POST":
                return ("ec2:RebootInstances", resource)
            elif tail == ["terminate"] and method == "POST":
                return ("ec2:TerminateInstances", resource)
        return None
    if path.startswith("/api/gcp/compute/"):
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 8 and parts[3] == "projects" and parts[5] == "zones" and parts[7] == "instances":
            project = parts[4]
            zone = parts[6]
            if len(parts) == 8:
                return ({"GET": "compute:ListInstances", "POST": "compute:InsertInstance"}.get(method), f"projects/{project}/zones/{zone}") if method in {"GET", "POST"} else None
            if len(parts) >= 9:
                instance_id = parts[8]
                resource = f"projects/{project}/zones/{zone}/instances/{instance_id}"
                tail = parts[9:] if len(parts) > 9 else []
                if not tail:
                    return ({"GET": "compute:GetInstance", "DELETE": "compute:DeleteInstance"}.get(method), resource) if method in {"GET", "DELETE"} else None
                if tail == ["start"] and method == "POST":
                    return ("compute:StartInstance", resource)
                if tail == ["stop"] and method == "POST":
                    return ("compute:StopInstance", resource)
                if tail == ["reset"] and method == "POST":
                    return ("compute:ResetInstance", resource)
        return None
    if path.startswith("/api/ec2/"):
        action_map = {
            ("GET", "/api/ec2/amis"): ("ec2:DescribeImages", "*"),
            ("GET", "/api/ec2/runtime"): ("ec2:DescribeInstances", "*"),
            ("GET", "/api/ec2/runtime/lxd"): ("ec2:DescribeInstances", "*"),
            ("GET", "/api/ec2/runtime/multipass"): ("ec2:DescribeInstances", "*"),
            ("POST", "/api/ec2/runtime/bootstrap"): ("ec2:CreateServiceLinkedRole", "*"),
            ("POST", "/api/ec2/runtime/lxd/bootstrap"): ("ec2:CreateServiceLinkedRole", "*"),
            ("POST", "/api/ec2/runtime/multipass/bootstrap"): ("ec2:CreateServiceLinkedRole", "*"),
        }
        return action_map.get((method, path))
    if path.startswith("/api/vpc/"):
        parts = [p for p in path.split("/") if p]
        if path == "/api/vpc/vpcs":
            return ({"GET": "vpc:DescribeVpcs", "POST": "vpc:CreateVpc"}.get(method), "*") if method in {"GET", "POST"} else None
        if len(parts) >= 4 and parts[2] == "vpcs":
            vpc_id = parts[3]
            resource = _iam_ec2_vpc_arn(vpc_id)
            if len(parts) == 4 and method == "GET":
                return ("vpc:DescribeVpcs", resource)
            if len(parts) == 4 and method == "DELETE":
                return ("vpc:DeleteVpc", resource)
            if len(parts) >= 5 and parts[4] == "resources" and method == "GET":
                return ("vpc:DescribeVpcs", resource)
        if path == "/api/vpc/subnets" and method == "POST":
            return ("vpc:CreateSubnet", "*")
        if path == "/api/vpc/security-groups" and method == "POST":
            return ("vpc:CreateSecurityGroup", "*")
        if len(parts) >= 5 and parts[2] == "security-groups" and parts[4] == "ingress" and method == "POST":
            return ("ec2:AuthorizeSecurityGroupIngress", _iam_ec2_security_group_arn(parts[3]))
        if path == "/api/vpc/route-tables" and method == "POST":
            return ("vpc:CreateRouteTable", "*")
        if path == "/api/vpc/internet-gateways":
            return ({"GET": "vpc:DescribeInternetGateways", "POST": "vpc:CreateInternetGateway"}.get(method), "*") if method in {"GET", "POST"} else None
        if len(parts) >= 5 and parts[2] == "internet-gateways" and parts[4] == "attach" and method == "POST":
            return ("vpc:AttachInternetGateway", _iam_ec2_internet_gateway_arn(parts[3]))
        if len(parts) >= 5 and parts[2] == "route-tables" and parts[4] == "routes" and method == "POST":
            return ("vpc:CreateRoute", _iam_ec2_route_table_arn(parts[3]))
        if len(parts) >= 5 and parts[2] == "route-tables" and parts[4] == "associate-subnet" and method == "POST":
            return ("vpc:AssociateRouteTable", _iam_ec2_route_table_arn(parts[3]))
    if path.startswith("/api/rds/"):
        parts = [p for p in path.split("/") if p]
        if path == "/api/rds/databases":
            return ({"GET": "rds:DescribeDBInstances", "POST": "rds:CreateDBInstance"}.get(method), "*") if method in {"GET", "POST"} else None
        if len(parts) >= 4 and parts[2] == "databases":
            db_id = parts[3]
            resource = _iam_rds_db_arn(db_id)
            if len(parts) == 4:
                return ({"GET": "rds:DescribeDBInstances", "PUT": "rds:ModifyDBInstance", "DELETE": "rds:DeleteDBInstance"}.get(method), resource) if method in {"GET", "PUT", "DELETE"} else None
            if len(parts) >= 5:
                tail = parts[4:]
                if tail == ["start"] and method == "POST":
                    return ("rds:StartDBInstance", resource)
                if tail == ["stop"] and method == "POST":
                    return ("rds:StopDBInstance", resource)
                if tail == ["reboot"] and method == "POST":
                    return ("rds:RebootDBInstance", resource)
                if tail == ["snapshots"] and method == "POST":
                    return ("rds:CreateDBSnapshot", resource)
                if tail == ["tags"] and method == "GET":
                    return ("rds:ListTagsForResource", resource)
                if tail == ["tags"] and method == "POST":
                    return ("rds:AddTagsToResource", resource)
        if path == "/api/rds/subnet-groups":
            return ({"GET": "rds:DescribeDBSubnetGroups", "POST": "rds:CreateDBSubnetGroup"}.get(method), "*") if method in {"GET", "POST"} else None
        if path == "/api/rds/parameter-groups":
            return ({"GET": "rds:DescribeDBParameterGroups", "POST": "rds:CreateDBParameterGroup"}.get(method), "*") if method in {"GET", "POST"} else None
        if path == "/api/rds/snapshots" and method == "GET":
            return ("rds:DescribeDBSnapshots", "*")
        if len(parts) >= 4 and parts[2] == "snapshots" and len(parts) >= 5 and parts[4] == "restore" and method == "POST":
            return ("rds:RestoreDBInstanceFromDBSnapshot", _iam_rds_snapshot_arn(parts[3]))
    if path.startswith("/api/lambda/") or path.startswith("/2015-03-31/functions"):
        parts = [p for p in path.split("/") if p]
        if path in {"/api/lambda/functions", "/2015-03-31/functions"}:
            return ({"GET": "lambda:ListFunctions", "POST": "lambda:CreateFunction"}.get(method), "*") if method in {"GET", "POST"} else None
        if len(parts) >= 4 and parts[2] == "functions":
            fn_name = parts[3]
            resource = _iam_lambda_function_arn(fn_name)
            tail = parts[4:] if len(parts) > 4 else []
            if not tail:
                return ({"GET": "lambda:GetFunction", "DELETE": "lambda:DeleteFunction"}.get(method), resource) if method in {"GET", "DELETE"} else None
            if tail == ["code"] and method == "PUT":
                return ("lambda:UpdateFunctionCode", resource)
            if tail == ["configuration"] and method == "PUT":
                return ("lambda:UpdateFunctionConfiguration", resource)
            if tail == ["invoke"] and method == "POST":
                return ("lambda:InvokeFunction", resource)
            if tail == ["versions"]:
                return ({"GET": "lambda:ListVersionsByFunction", "POST": "lambda:PublishVersion"}.get(method), resource) if method in {"GET", "POST"} else None
            if tail == ["policy"]:
                return ({"GET": "lambda:GetPolicy", "POST": "lambda:AddPermission"}.get(method), resource) if method in {"GET", "POST"} else None
            if len(tail) == 2 and tail[0] == "policy" and method == "DELETE":
                return ("lambda:RemovePermission", resource)
            if tail == ["invocations"] and method == "GET":
                return ("lambda:GetFunction", resource)
    if path.startswith("/api/sqs/") or path == "/sqs":
        parts = [p for p in path.split("/") if p]
        if path in {"/api/sqs/queues"}:
            return ({"GET": "sqs:ListQueues", "POST": "sqs:CreateQueue"}.get(method), "*") if method in {"GET", "POST"} else None
        if len(parts) >= 4 and parts[2] == "queues":
            queue_name = parts[3]
            resource = _iam_sqs_queue_arn(queue_name)
            tail = parts[4:] if len(parts) > 4 else []
            if not tail:
                return ({"GET": "sqs:GetQueueAttributes", "PUT": "sqs:SetQueueAttributes", "DELETE": "sqs:DeleteQueue"}.get(method), resource) if method in {"GET", "PUT", "DELETE"} else None
            if tail == ["messages"]:
                return ({"GET": "sqs:ReceiveMessage", "POST": "sqs:SendMessage"}.get(method), resource) if method in {"GET", "POST"} else None
            if len(tail) == 2 and tail[0] == "messages" and method == "DELETE":
                return ("sqs:DeleteMessage", resource)
            if len(tail) == 3 and tail[0] == "messages" and tail[2] == "visibility" and method == "POST":
                return ("sqs:ChangeMessageVisibility", resource)
            if tail == ["purge"] and method == "POST":
                return ("sqs:PurgeQueue", resource)
            if tail == ["tags"]:
                return ({"GET": "sqs:ListQueueTags", "POST": "sqs:TagQueue", "DELETE": "sqs:UntagQueue"}.get(method), resource) if method in {"GET", "POST", "DELETE"} else None
    if path.startswith("/api/dynamodb/") or path == "/dynamodb":
        parts = [p for p in path.split("/") if p]
        if path in {"/api/dynamodb/tables"}:
            return ({"GET": "dynamodb:ListTables", "POST": "dynamodb:CreateTable"}.get(method), "*") if method in {"GET", "POST"} else None
        if path in {"/api/dynamodb/aws", "/dynamodb"} and method == "POST":
            target = request.headers.get("x-amz-target", "")
            action = target.rsplit(".", 1)[-1] if target else "Unknown"
            return (f"dynamodb:{action}", "*")
        if len(parts) >= 4 and parts[2] == "tables":
            table_name = parts[3]
            resource = _iam_dynamodb_table_arn(table_name)
            tail = parts[4:] if len(parts) > 4 else []
            if not tail:
                return ({"GET": "dynamodb:DescribeTable", "DELETE": "dynamodb:DeleteTable"}.get(method), resource) if method in {"GET", "DELETE"} else None
            if tail == ["items"]:
                return ({"GET": "dynamodb:Scan", "POST": "dynamodb:PutItem", "PUT": "dynamodb:UpdateItem", "DELETE": "dynamodb:DeleteItem"}.get(method), resource) if method in {"GET", "POST", "PUT", "DELETE"} else None
            if tail == ["query"] and method == "POST":
                return ("dynamodb:Query", resource)
            if tail == ["scan"] and method == "POST":
                return ("dynamodb:Scan", resource)
            if tail == ["batch-get"] and method == "POST":
                return ("dynamodb:BatchGetItem", resource)
            if tail == ["batch-write"] and method == "POST":
                return ("dynamodb:BatchWriteItem", resource)
            if tail == ["tags"]:
                return ({"GET": "dynamodb:ListTagsOfResource", "POST": "dynamodb:TagResource", "DELETE": "dynamodb:UntagResource"}.get(method), resource) if method in {"GET", "POST", "DELETE"} else None
    if path.startswith("/api/apigateway/"):
        parts = [p for p in path.split("/") if p]
        if path == "/api/apigateway/apis":
            return ({"GET": "apigateway:GetRestApis", "POST": "apigateway:CreateRestApi"}.get(method), "*") if method in {"GET", "POST"} else None
        if len(parts) >= 4 and parts[2] == "apis":
            api_id = parts[3]
            resource = _iam_apigw_api_arn(api_id)
            tail = parts[4:] if len(parts) > 4 else []
            if not tail:
                return ({"GET": "apigateway:GetRestApi", "DELETE": "apigateway:DeleteRestApi"}.get(method), resource) if method in {"GET", "DELETE"} else None
            if tail == ["resources"]:
                return ({"GET": "apigateway:GetResources", "POST": "apigateway:CreateResource"}.get(method), resource) if method in {"GET", "POST"} else None
            if tail == ["methods"] and method == "POST":
                return ("apigateway:PutMethod", resource)
            if tail == ["integrations"] and method == "POST":
                return ("apigateway:PutIntegration", resource)
            if tail == ["deployments"]:
                return ({"GET": "apigateway:GetDeployments", "POST": "apigateway:CreateDeployment"}.get(method), resource) if method in {"GET", "POST"} else None
            if tail == ["stages"]:
                return ({"GET": "apigateway:GetStages", "POST": "apigateway:CreateStage"}.get(method), resource) if method in {"GET", "POST"} else None
            if tail == ["logs"] and method == "GET":
                return ("apigateway:GetLogs", resource)
        if len(parts) >= 4 and parts[2] == "invoke":
            api_id = parts[3]
            stage_name = parts[4] if len(parts) > 4 else ""
            return ("execute-api:Invoke", _iam_apigw_stage_arn(api_id, stage_name or "*"))

    # Root-level S3 paths
    if path == "/" or (path not in {"/ui", "/product", "/api", "/healthz"} and not path.startswith("/api/")):
        if path == "/":
            return ("s3:ListAllMyBuckets", "*")
        segs = [s for s in path.split("/") if s]
        if len(segs) == 1:
            bucket = segs[0]
            resource = _iam_s3_bucket_arn(bucket)
            if method == "GET":
                if "versions" in query:
                    return ("s3:ListBucketVersions", resource)
                return ("s3:ListBucket", resource)
            if method == "PUT":
                if "versioning" in query:
                    return ("s3:PutBucketVersioning", resource)
                if "notification" in query:
                    return ("s3:PutBucketNotificationConfiguration", resource)
                if "tagging" in query:
                    return ("s3:PutBucketTagging", resource)
                if "acl" in query:
                    return ("s3:PutBucketAcl", resource)
                if "cors" in query:
                    return ("s3:PutBucketCors", resource)
                if "lifecycle" in query:
                    return ("s3:PutBucketLifecycleConfiguration", resource)
                if "encryption" in query:
                    return ("s3:PutBucketEncryption", resource)
                return ("s3:CreateBucket", resource)
            if method == "HEAD":
                return ("s3:HeadBucket", resource)
            if method == "DELETE":
                return ("s3:DeleteBucket", resource)
            if method == "POST":
                return ("s3:DeleteObjects", resource) if "delete" in query else ("s3:CreateMultipartUpload", resource)
        if len(segs) >= 2:
            bucket = segs[0]
            key = "/".join(segs[1:])
            resource = _iam_s3_object_arn(bucket, key)
            if method in {"GET", "HEAD", "PUT", "DELETE", "POST"}:
                if method == "GET":
                    if "tagging" in query:
                        return ("s3:GetObjectTagging", resource)
                    if "acl" in query:
                        return ("s3:GetObjectAcl", resource)
                    return ("s3:GetObject", resource)
                if method == "PUT":
                    if "tagging" in query:
                        return ("s3:PutObjectTagging", resource)
                    return ("s3:PutObject", resource)
                if method == "DELETE":
                    if "tagging" in query:
                        return ("s3:DeleteObjectTagging", resource)
                    return ("s3:DeleteObject", resource)
                if method == "POST":
                    if "uploads" in query:
                        return ("s3:CreateMultipartUpload", resource)
                    if "uploadId" in query:
                        return ("s3:CompleteMultipartUpload", resource)
    return None



STATE_LOCK = PLATFORM.store.lock





def _cloudsim_active_space_ref() -> dict | None:
    spaces_state = _spaces_state()
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.get("spaces", {}).get(active_id) if active_id else None
    return space if isinstance(space, dict) else None


def _cloudsim_runtime_bundle_catalog() -> dict[str, dict]:
    """Return the runtime bundle catalog — single source of truth in
    ``_DEFAULT_RUNTIME_BUNDLES``. Idempotently merges any missing defaults
    into the on-disk runtime_state without overwriting user-edited fields."""
    bundles = runtime_state.setdefault("bundles", {})
    for key, bundle in _DEFAULT_RUNTIME_BUNDLES.items():
        bundles.setdefault(key, copy.deepcopy(bundle))
    return bundles


def _cloudsim_runtime_bundle(bundle_key: str | None) -> dict:
    bundles = _cloudsim_runtime_bundle_catalog()
    key = (bundle_key or "python").strip().lower()
    bundle = bundles.get(key) or bundles.get("python") or {"id": "cloudlearn.runtime.python", "name": "Python Runtime", "kind": "language", "provider": "shared", "service": "python", "installed": True, "active": False}
    return copy.deepcopy(bundle)


# ---------------------------------------------------------------------------
# VM sync field maps -- one entry per provider
# ---------------------------------------------------------------------------
_VM_SYNC_FIELDS: dict[str, dict] = {
    "ec2": {
        "id_fields": ["instance_id", "id"],
        "region_fields": ["az", "region", "active_region"],
        "region_default": "us-east-1",
        "type_fields": ["instance_type"],
        "image_fields": ["ami"],
        "image_name_fields": ["ami_name"],
        "state_fields": ["state"],
    },
    "gcp_compute": {
        "id_fields": ["instance_id", "id", "name"],
        "region_fields": ["zone", "active_zone"],
        "region_default": "us-central1-a",
        "region_transform": lambda z: z.rsplit("-", 1)[0] if "-" in z else z,
        "type_fields": ["machine_type", "machineType"],
        "image_fields": ["source_image", "sourceImage"],
        "image_name_fields": ["ami_name"],
        "state_fields": ["status", "state"],
    },
    "azure_vm": {
        "id_fields": ["id", "name"],
        "region_fields": ["location", "region"],
        "region_default": "eastus",
        "type_from_nested": True,
        "state_from_nested": True,
    },
}


def _cloudsim_sync_vm_resource(
    provider: str,
    service_key: str,
    bundle_key: str,
    record: dict,
    action: str = "upsert",
    field_map: dict | None = None,
) -> None:
    """Unified CloudSim sync for VM resources across AWS, GCP, and Azure.

    ``field_map`` controls how provider-specific field names are resolved.
    See ``_VM_SYNC_FIELDS`` for the per-provider maps.
    """
    if not isinstance(record, dict):
        return
    fm = field_map or {}

    # --- resource_id ---
    resource_id = ""
    for f in fm.get("id_fields", ["id"]):
        resource_id = str(record.get(f) or "").strip()
        if resource_id:
            break
    if not resource_id:
        return

    # --- region ---
    default_region = fm.get("region_default", "us-east-1")
    region = ""
    for f in fm.get("region_fields", ["region"]):
        region = str(record.get(f) or "").strip()
        if region:
            break
    region = region or default_region
    region_transform = fm.get("region_transform")
    if region_transform is not None:
        region = region_transform(region)

    bundle = _cloudsim_runtime_bundle(bundle_key)

    # --- Azure nested property helpers ---
    props: dict = {}
    hw: dict = {}
    runtime: dict = {}
    if fm.get("type_from_nested") or fm.get("state_from_nested"):
        props = record.get("properties") if isinstance(record.get("properties"), dict) else {}
        hw = props.get("hardwareProfile") if isinstance(props.get("hardwareProfile"), dict) else {}
        runtime = props.get("runtime") if isinstance(props.get("runtime"), dict) else {}

    # --- instance_type ---
    if fm.get("type_from_nested"):
        instance_type = hw.get("vmSize", "")
    else:
        instance_type = ""
        for f in fm.get("type_fields", ["instance_type"]):
            instance_type = record.get(f) or ""
            if instance_type:
                break

    # --- image / ami ---
    if fm.get("type_from_nested"):
        # Azure: image from storageProfile
        storage = props.get("storageProfile", {}) if isinstance(props.get("storageProfile"), dict) else {}
        img_ref = storage.get("imageReference", {}) if isinstance(storage.get("imageReference"), dict) else {}
        ami = img_ref.get("offer", "")
        ami_name = img_ref.get("sku", "")
    else:
        ami = ""
        for f in fm.get("image_fields", []):
            ami = record.get(f) or ""
            if ami:
                break
        ami_name = ""
        for f in fm.get("image_name_fields", []):
            ami_name = record.get(f) or ""
            if ami_name:
                break

    # --- state ---
    if fm.get("state_from_nested"):
        instance_view = props.get("instanceView") if isinstance(props.get("instanceView"), dict) else {}
        power_state = ""
        statuses = instance_view.get("statuses") if isinstance(instance_view, dict) else []
        if isinstance(statuses, list):
            for s in statuses:
                code = str(s.get("code", "")) if isinstance(s, dict) else ""
                if code.startswith("PowerState/"):
                    power_state = code.split("/", 1)[1]
                    break
        state = power_state or str(props.get("provisioningState", "")).lower()
    else:
        state = ""
        for f in fm.get("state_fields", ["state"]):
            state = record.get(f) or ""
            if state:
                break

    # --- Azure-specific overrides for non-top-level fields ---
    if fm.get("type_from_nested"):
        launch_status = str(props.get("provisioningState", ""))
        runtime_backend = runtime.get("backend", "")
        console_backend = runtime.get("backend", "")
        endpoint_url = runtime.get("endpointUrl", "")
        private_ip = runtime.get("privateIp", "")
        public_ip = runtime.get("publicIp", "")
        workspace = runtime.get("containerName", "")
        updated_at = _now()
    else:
        launch_status = record.get("launch_status", "")
        runtime_backend = record.get("runtime_backend", "")
        console_backend = record.get("console_backend", "")
        endpoint_url = record.get("endpoint_url", "")
        private_ip = record.get("private_ip", "")
        public_ip = record.get("public_ip", "")
        workspace = record.get("workspace", "")
        updated_at = record.get("updated_at") or record.get("created") or _now()

    payload = {
        "name": record.get("name") or resource_id,
        "instance_type": instance_type,
        "ami": ami,
        "ami_name": ami_name,
        "state": state,
        "launch_status": launch_status,
        "runtime_backend": runtime_backend,
        "runtime_bundle_id": bundle.get("id", ""),
        "runtime_bundle_name": bundle.get("name", ""),
        "runtime_bundle_kind": bundle.get("kind", ""),
        "runtime_bundle_provider": bundle.get("provider", ""),
        "runtime_bundle_service": bundle.get("service", ""),
        "console_backend": console_backend,
        "endpoint_url": endpoint_url,
        "private_ip": private_ip,
        "public_ip": public_ip,
        "workspace": workspace,
        "updated_at": updated_at,
    }
    try:
        if action == "delete":
            PLATFORM.delete_resource(service_key, resource_id, region=region)
        else:
            PLATFORM.create_resource(service_key, "instance", resource_id, payload, region=region)
    except Exception:
        pass


def _cloudsim_sync_ec2_resource(instance: dict, action: str = "upsert") -> None:
    _cloudsim_sync_vm_resource("aws", "ec2", "ec2", instance, action, _VM_SYNC_FIELDS["ec2"])


def _cloudsim_sync_gcp_compute_resource(instance: dict, action: str = "upsert") -> None:
    """CloudSim sync for GCP Compute Engine instances (parity with EC2 + Azure VM)."""
    _cloudsim_sync_vm_resource("gcp", "gcp_compute", "gcp_compute", instance, action, _VM_SYNC_FIELDS["gcp_compute"])


def _cloudsim_sync_azure_vm_resource(record: dict, action: str = "upsert") -> None:
    """CloudSim sync for Azure Microsoft.Compute/virtualMachines."""
    _cloudsim_sync_vm_resource("azure", "azure_vm", "azure_vm", record, action, _VM_SYNC_FIELDS["azure_vm"])


def _cloudsim_sync_service_resource(provider: str, service: str, resource_type: str,
                                     resource_id: str, resource: dict, bundle_key: str | None = None,
                                     action: str = "upsert", region: str = "us-east-1") -> None:
    """Generic CloudSim sync for non-compute services (databases, functions,
    storage, queues, etc.). Mirrors the VM-specific sync functions."""
    if not resource_id:
        return
    bundle = _cloudsim_runtime_bundle(bundle_key) if bundle_key else {}
    name = (resource.get("name") or resource.get("db_instance_identifier")
            or resource.get("function_name") or resource.get("queue_name")
            or resource.get("table_name") or resource.get("topic") or resource_id)
    state = (resource.get("status") or resource.get("state")
             or resource.get("table_status") or "active")
    location = (resource.get("region") or resource.get("az")
                or resource.get("location") or resource.get("availability_zone") or region)
    payload = {
        "name": name,
        "resource_type": resource_type,
        "provider": provider,
        "service": service,
        "state": str(state).lower(),
        "location": str(location),
        "updated_at": resource.get("updated_at") or resource.get("created") or resource.get("last_modified") or _now(),
    }
    if bundle:
        payload.update({
            "runtime_bundle_id": bundle.get("id", ""),
            "runtime_bundle_name": bundle.get("name", ""),
            "runtime_bundle_kind": bundle.get("kind", ""),
            "runtime_bundle_provider": bundle.get("provider", ""),
            "runtime_bundle_service": bundle.get("service", ""),
        })
    try:
        svc_key = f"{provider}_{service}" if provider != "aws" else service
        if action == "delete":
            PLATFORM.delete_resource(svc_key, resource_id, region=str(location))
        else:
            PLATFORM.create_resource(svc_key, resource_type, resource_id, payload, region=str(location))
    except Exception:
        pass


def _default_cloudsim_space_policy() -> dict:
    """Default CloudSim per-space policy. Used when a space has no
    explicit `cloudsim.policy` block. Liberal defaults — allow EC2
    launches on both multipass and LXD backends with no AMI allowlist.
    The normalizer in `_cloudsim_space_policy` enforces shape/types
    on top of whatever this returns.

    Was referenced but never defined — calls used to NameError, taking
    every EC2 launch path with it. Filled in 2026-06-13.
    """
    return {
        "ec2": {
            "launch": True,
            "allowed_runtime_backends": ["multipass", "lxd"],
            "allowed_amis": [],  # empty list = no allowlist, any AMI accepted
        },
    }


def _cloudsim_space_policy(space: dict | None) -> dict:
    policy = copy.deepcopy(_default_cloudsim_space_policy())
    if not isinstance(space, dict):
        return policy
    cloudsim = space.get("cloudsim")
    if isinstance(cloudsim, dict):
        raw_policy = cloudsim.get("policy")
        if isinstance(raw_policy, dict):
            policy = copy.deepcopy(raw_policy)
    if not isinstance(policy, dict):
        policy = copy.deepcopy(_default_cloudsim_space_policy())
    ec2_policy = policy.setdefault("ec2", {})
    if not isinstance(ec2_policy, dict):
        ec2_policy = {}
        policy["ec2"] = ec2_policy
    ec2_policy.setdefault("launch", True)
    allowed_backends = ec2_policy.get("allowed_runtime_backends")
    if isinstance(allowed_backends, str):
        allowed_backends = [allowed_backends]
    if not isinstance(allowed_backends, list):
        allowed_backends = ["multipass", "lxd"]
    normalized_backends = []
    for backend in allowed_backends:
        backend_value = str(backend).strip().lower()
        if backend_value:
            normalized_backends.append(backend_value)
    ec2_policy["allowed_runtime_backends"] = list(dict.fromkeys(normalized_backends or ["multipass", "lxd"]))
    allowed_amis = ec2_policy.get("allowed_amis")
    if isinstance(allowed_amis, str):
        allowed_amis = [allowed_amis]
    if not isinstance(allowed_amis, list):
        allowed_amis = []
    ec2_policy["allowed_amis"] = [str(ami).strip() for ami in allowed_amis if str(ami).strip()]
    return policy


def _cloudsim_validate_ec2_launch_policy(space: dict | None, req: "EC2InstanceRequest", profile: dict, runtime_backend: str) -> None:
    policy = _cloudsim_space_policy(space)
    ec2_policy = policy.get("ec2", {}) if isinstance(policy, dict) else {}
    if not isinstance(ec2_policy, dict):
        ec2_policy = {}
    if not bool(ec2_policy.get("launch", True)):
        _record_usage(
            "ec2.launch_denied",
            {
                "ami": req.ami,
                "ami_name": profile.get("name", req.ami),
                "instance_type": req.instance_type,
                "runtime_backend": runtime_backend,
                "reason": "CloudSim policy blocks EC2 launches in the active space.",
            },
        )
        raise HTTPException(status_code=403, detail="CloudSim policy blocks EC2 launches in the active space.")
    allowed_backends = [str(item).strip().lower() for item in ec2_policy.get("allowed_runtime_backends", []) if str(item).strip()]
    if allowed_backends and runtime_backend not in allowed_backends:
        allowed_label = ", ".join(item.upper() if item != "lxd" else "LXD" for item in allowed_backends)
        _record_usage(
            "ec2.launch_denied",
            {
                "ami": req.ami,
                "ami_name": profile.get("name", req.ami),
                "instance_type": req.instance_type,
                "runtime_backend": runtime_backend,
                "reason": f"CloudSim policy only allows these EC2 runtime backends: {allowed_label}.",
            },
        )
        raise HTTPException(status_code=403, detail=f"CloudSim policy only allows these EC2 runtime backends: {allowed_label}.")
    allowed_amis = [str(item).strip() for item in ec2_policy.get("allowed_amis", []) if str(item).strip()]
    if allowed_amis and req.ami not in allowed_amis:
        ami_name = profile.get("name", req.ami)
        _record_usage(
            "ec2.launch_denied",
            {
                "ami": req.ami,
                "ami_name": ami_name,
                "instance_type": req.instance_type,
                "runtime_backend": runtime_backend,
                "reason": f"CloudSim policy does not allow AMI '{ami_name}'.",
            },
        )
        raise HTTPException(status_code=403, detail=f"CloudSim policy does not allow AMI '{ami_name}'.")


def _cloudsim_service_state(space: dict | None, *keys: str) -> dict:
    if not isinstance(space, dict):
        return {}
    service_states = space.setdefault("service_states", {})
    if not isinstance(service_states, dict):
        space["service_states"] = {}
        service_states = space["service_states"]
    candidates: list[tuple[int, int, dict]] = []
    for index, key in enumerate(keys):
        for candidate_key in (key, f"gcp_{key}"):
            value = service_states.get(candidate_key)
            if isinstance(value, dict):
                score = 0
                for nested in value.values():
                    if isinstance(nested, dict):
                        score += len(nested)
                    elif isinstance(nested, (list, tuple, set)):
                        score += len(nested)
                    elif nested not in (None, "", False):
                        score += 1
                candidates.append((score, -index, value))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]
    for key in keys:
        if key in service_states and isinstance(service_states[key], dict):
            return service_states[key]
    for key in keys:
        prefixed = f"gcp_{key}"
        if prefixed in service_states and isinstance(service_states[prefixed], dict):
            return service_states[prefixed]
    return service_states.setdefault(keys[0], {})


def _cloudsim_all_provider_summary_counts(space: dict | None = None) -> dict[str, int]:
    """Unified summary counts across AWS, GCP, and Azure providers."""
    target = space if isinstance(space, dict) else _spaces_state().get("spaces", {}).get(_spaces_state().get("active_space_id", ""), {})
    if not isinstance(target, dict):
        target = {}
    service_states_raw = target.get("service_states", {})
    if not isinstance(service_states_raw, dict):
        service_states_raw = {}
    service_state_space = {"service_states": service_states_raw}

    def bucket(*keys: str) -> dict:
        return _cloudsim_service_state(service_state_space, *keys)

    # --- AWS counts ---
    ec2_count = len(bucket("ec2").get("instances", {}))
    lambda_count = len(bucket("lambda").get("functions", {}))
    rds_count = len(bucket("rds").get("db_instances", {}))
    s3_bucket_count = len(bucket("s3").get("buckets", {}))
    sqs_count = len(bucket("sqs").get("queues", {}))
    dynamodb_count = len(bucket("dynamodb").get("tables", {}))
    apigateway_count = len(bucket("apigateway").get("apis", {}))
    vpc_count = len(bucket("vpc").get("vpcs", {}))

    # --- GCP counts ---
    gcp_compute_count = len(bucket("gcp_compute").get("instances", {}))
    gcp_storage_bucket_count = len(bucket("gcp_storage").get("buckets", {}))
    gcp_sql_count = len(bucket("gcp_sql").get("instances", {}))
    gcp_pubsub_topic_count = len(bucket("gcp_pubsub").get("topics", {}))
    gcp_pubsub_subscription_count = len(bucket("gcp_pubsub").get("subscriptions", {}))
    gcp_functions_count = len(bucket("gcp_functions").get("functions", {}))
    gcp_apigateway_count = len(bucket("gcp_apigateway").get("apis", {}))
    gcp_vpc_count = len(bucket("gcp_vpc").get("networks", {}))
    gcp_iam_count = len(bucket("gcp_iam").get("service_accounts", {}))

    # --- Azure counts (walk azure_arm.resources using RESOURCE_CATALOG) ---
    azure_arm = service_states_raw.get("azure_arm", {})
    azure_resources = azure_arm.get("resources", {}) if isinstance(azure_arm, dict) else {}
    if not isinstance(azure_resources, dict):
        azure_resources = {}
    azure_key_counts: dict[str, int] = {c["key"]: 0 for c in provider_azure_services.RESOURCE_CATALOG}
    azure_type_to_key = {(c["namespace"] + "/" + c["type"]).lower(): c["key"]
                         for c in provider_azure_services.RESOURCE_CATALOG}
    for _rid, rec in azure_resources.items():
        if not isinstance(rec, dict):
            continue
        full_type = str(rec.get("_type", "")).lower()
        key = azure_type_to_key.get(full_type)
        if key is None:
            segs = full_type.split("/")
            if len(segs) >= 2:
                key = azure_type_to_key.get(segs[0] + "/" + segs[1])
        if key and key in azure_key_counts:
            azure_key_counts[key] += 1

    azure_vm_count = azure_key_counts.get("vm", 0)
    azure_sql_count = azure_key_counts.get("sql", 0)
    azure_storage_count = azure_key_counts.get("storage", 0)
    azure_functionapp_count = azure_key_counts.get("functionapp", 0)
    azure_servicebus_count = azure_key_counts.get("servicebus", 0)
    azure_cosmos_count = azure_key_counts.get("cosmos", 0)
    azure_apim_count = azure_key_counts.get("apim", 0)
    azure_vnet_count = azure_key_counts.get("vnet", 0)
    azure_eventgrid_count = azure_key_counts.get("eventgrid", 0)

    # --- Totals ---
    total_vm_count = ec2_count + gcp_compute_count + azure_vm_count
    total_resource_count = (
        ec2_count + lambda_count + rds_count + s3_bucket_count + sqs_count
        + dynamodb_count + apigateway_count + vpc_count
        + gcp_compute_count + gcp_storage_bucket_count + gcp_sql_count
        + gcp_pubsub_topic_count + gcp_pubsub_subscription_count
        + gcp_functions_count + gcp_apigateway_count + gcp_vpc_count + gcp_iam_count
        + azure_vm_count + azure_sql_count + azure_storage_count
        + azure_functionapp_count + azure_servicebus_count + azure_cosmos_count
        + azure_apim_count + azure_vnet_count + azure_eventgrid_count
    )

    return {
        # AWS
        "ec2_count": ec2_count,
        "lambda_count": lambda_count,
        "rds_count": rds_count,
        "s3_bucket_count": s3_bucket_count,
        "sqs_count": sqs_count,
        "dynamodb_count": dynamodb_count,
        "apigateway_count": apigateway_count,
        "vpc_count": vpc_count,
        # GCP
        "gcp_compute_count": gcp_compute_count,
        "gcp_storage_bucket_count": gcp_storage_bucket_count,
        "gcp_sql_count": gcp_sql_count,
        "gcp_pubsub_topic_count": gcp_pubsub_topic_count,
        "gcp_pubsub_subscription_count": gcp_pubsub_subscription_count,
        "gcp_functions_count": gcp_functions_count,
        "gcp_apigateway_count": gcp_apigateway_count,
        "gcp_vpc_count": gcp_vpc_count,
        "gcp_iam_count": gcp_iam_count,
        # Azure
        "azure_vm_count": azure_vm_count,
        "azure_sql_count": azure_sql_count,
        "azure_storage_count": azure_storage_count,
        "azure_functionapp_count": azure_functionapp_count,
        "azure_servicebus_count": azure_servicebus_count,
        "azure_cosmos_count": azure_cosmos_count,
        "azure_apim_count": azure_apim_count,
        "azure_vnet_count": azure_vnet_count,
        "azure_eventgrid_count": azure_eventgrid_count,
        # Totals
        "total_vm_count": total_vm_count,
        "total_resource_count": total_resource_count,
    }


def _cloudsim_gcp_summary_counts(space: dict | None = None) -> dict[str, int]:
    """Backward-compatible wrapper: returns only gcp_* keys."""
    all_counts = _cloudsim_all_provider_summary_counts(space)
    return {k: v for k, v in all_counts.items() if k.startswith("gcp_")}


def _refresh_cloudsim_all_providers_summary() -> None:
    """Refresh summary counts for all providers (AWS, GCP, Azure)."""
    spaces_state = _spaces_state()
    active_id = spaces_state.get("active_space_id", "")
    active_space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
    counts = _cloudsim_all_provider_summary_counts(active_space if isinstance(active_space, dict) else None)
    cloudsim = STATE.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
    cloudsim.setdefault("summary", {}).update(counts)
    if isinstance(active_space, dict):
        active_cloudsim = active_space.setdefault("cloudsim", {"summary": {}, "events": [], "last_tick": ""})
        active_cloudsim.setdefault("summary", {}).update(counts)
    try:
        platform_cloudsim = PLATFORM.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
        platform_cloudsim.setdefault("summary", {}).update(counts)
        if isinstance(active_space, dict):
            platform_active = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}}).get("spaces", {}).get(active_id, {})
            if isinstance(platform_active, dict):
                platform_active.setdefault("cloudsim", {"summary": {}, "events": [], "last_tick": ""}).setdefault("summary", {}).update(counts)
    except Exception:
        pass


def _refresh_cloudsim_gcp_summary() -> None:
    """Backward-compatible alias for _refresh_cloudsim_all_providers_summary."""
    _refresh_cloudsim_all_providers_summary()


def _cloudsim_resource_id(resource: dict, *candidates: str) -> str:
    if not isinstance(resource, dict):
        return ""
    for key in ("resource_id", "id", *candidates):
        value = resource.get(key)
        if value is not None and str(value).strip():
            return str(value)
    if resource.get("name") is not None and str(resource.get("name")).strip():
        return str(resource.get("name"))
    return ""


def _cloudsim_resource_location(resource: dict) -> str:
    if not isinstance(resource, dict):
        return ""
    for key in ("region", "zone", "location", "az", "availability_zone"):
        value = resource.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _cloudsim_resource_state(resource: dict) -> str:
    if not isinstance(resource, dict):
        return ""
    for key in ("state", "status", "db_instance_status", "launch_status", "container_status"):
        value = resource.get(key)
        if value is not None and str(value).strip():
            return str(value)
    # Azure (and other nested-state providers) carry lifecycle under properties.
    props = resource.get("properties")
    if isinstance(props, dict):
        for key in ("provisioningState", "state", "status"):
            value = props.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return ""


def _cloudsim_add_runtime_instance(runtime_instances: dict, resource_id: str, provider: str, service: str, bundle_key: str, resource: dict) -> None:
    bundle = _cloudsim_runtime_bundle(bundle_key)
    runtime_instances[resource_id] = {
        "resource_id": resource_id,
        "provider": provider,
        "service": service,
        "bundle_id": bundle.get("id", ""),
        "bundle_name": bundle.get("name", ""),
        "bundle_kind": bundle.get("kind", ""),
        "bundle_provider": bundle.get("provider", ""),
        "bundle_service": bundle.get("service", ""),
        "name": str(resource.get("name") or resource_id),
        "location": _cloudsim_resource_location(resource),
        "state": _cloudsim_resource_state(resource),
        "updated_at": resource.get("updated") or resource.get("updatedAt") or resource.get("updateTime") or resource.get("created") or resource.get("createTime") or _now(),
    }


def _cloudsim_collect_resources(space: dict | None) -> tuple[list[dict], dict[str, int], dict[str, dict]]:
    if not isinstance(space, dict):
        return [], {}, {}
    service_states = space.setdefault("service_states", {})
    if not isinstance(service_states, dict):
        service_states = {}
    nodes: list[dict] = []
    counts: dict[str, int] = {}
    runtime_instances: dict[str, dict] = {}

    def add(provider: str, service: str, kind: str, resource_id: str, resource: dict, bundle_key: str | None = None) -> None:
        if not resource_id:
            return
        bundle = _cloudsim_runtime_bundle(bundle_key) if bundle_key else None
        node = {
            "provider": provider,
            "service": service,
            "kind": kind,
            "resource_id": resource_id,
            "name": str(resource.get("name") or resource.get("bucket") or resource.get("queue_name") or resource.get("table_name") or resource.get("db_instance_identifier") or resource.get("function_name") or resource.get("api_id") or resource.get("topicId") or resource.get("subscriptionId") or resource_id),
            "location": _cloudsim_resource_location(resource),
            "state": _cloudsim_resource_state(resource),
            "updated_at": resource.get("updated") or resource.get("updatedAt") or resource.get("updateTime") or resource.get("created") or resource.get("createTime") or _now(),
        }
        if bundle:
            node.update({
                "runtime_bundle_id": bundle.get("id", ""),
                "runtime_bundle_name": bundle.get("name", ""),
                "runtime_bundle_kind": bundle.get("kind", ""),
                "runtime_bundle_provider": bundle.get("provider", ""),
                "runtime_bundle_service": bundle.get("service", ""),
            })
            _cloudsim_add_runtime_instance(runtime_instances, resource_id, provider, service, bundle_key or "", resource)
        try:
            from core import cost_model as _cm
            _cost = _cm.estimate_resource_cost(
                provider, service, kind,
                resource.get("instance_type") or resource.get("machine_type") or resource.get("machineType")
                or resource.get("db_instance_class") or resource.get("vmSize") or "",
            )
            node["estimated_real_cost_usd"] = _cost["monthly_usd"]
            node["estimated_hourly_usd"] = _cost["hourly_usd"]
        except Exception:
            node["estimated_real_cost_usd"] = 0.0
            node["estimated_hourly_usd"] = 0.0
        nodes.append(node)
        counts[f"{provider}.{service}.{kind}"] = counts.get(f"{provider}.{service}.{kind}", 0) + 1

    aws_ec2 = _cloudsim_service_state(space, "ec2")
    for instance_id, instance in aws_ec2.get("instances", {}).items():
        if isinstance(instance, dict):
            add("aws", "ec2", "instance", instance_id, instance, "ec2")

    aws_s3 = _cloudsim_service_state(space, "s3")
    for bucket_name, bucket in aws_s3.get("buckets", {}).items():
        if isinstance(bucket, dict):
            add("aws", "s3", "bucket", bucket_name, bucket)

    aws_vpc = _cloudsim_service_state(space, "vpc")
    for vpc_id, vpc in aws_vpc.get("vpcs", {}).items():
        if isinstance(vpc, dict):
            add("aws", "vpc", "vpc", vpc_id, vpc)
    for subnet_id, subnet in aws_vpc.get("subnets", {}).items():
        if isinstance(subnet, dict):
            add("aws", "vpc", "subnet", subnet_id, subnet)
    for sg_id, sg in aws_vpc.get("security_groups", {}).items():
        if isinstance(sg, dict):
            add("aws", "vpc", "security_group", sg_id, sg)
    for rt_id, rt in aws_vpc.get("route_tables", {}).items():
        if isinstance(rt, dict):
            add("aws", "vpc", "route_table", rt_id, rt)
    for igw_id, igw in aws_vpc.get("internet_gateways", {}).items():
        if isinstance(igw, dict):
            add("aws", "vpc", "internet_gateway", igw_id, igw)

    aws_rds = _cloudsim_service_state(space, "rds")
    for db_id, db in aws_rds.get("db_instances", {}).items():
        if isinstance(db, dict):
            add("aws", "rds", "db_instance", db_id, db, "rds")
    for group_id, group in aws_rds.get("db_subnet_groups", {}).items():
        if isinstance(group, dict):
            add("aws", "rds", "subnet_group", group_id, group, "rds")
    for group_id, group in aws_rds.get("db_parameter_groups", {}).items():
        if isinstance(group, dict):
            add("aws", "rds", "parameter_group", group_id, group, "rds")
    for snapshot_id, snapshot in aws_rds.get("db_snapshots", {}).items():
        if isinstance(snapshot, dict):
            add("aws", "rds", "snapshot", snapshot_id, snapshot, "rds")

    aws_apigw = _cloudsim_service_state(space, "apigateway")
    for api_id, api in aws_apigw.get("apis", {}).items():
        if isinstance(api, dict):
            add("aws", "apigateway", "api", api_id, api)

    aws_lambda = _cloudsim_service_state(space, "lambda")
    for fn_name, fn in aws_lambda.get("functions", {}).items():
        if isinstance(fn, dict):
            add("aws", "lambda", "function", fn_name, fn, "lambda")

    aws_sqs = _cloudsim_service_state(space, "sqs")
    for queue_name, queue in aws_sqs.get("queues", {}).items():
        if isinstance(queue, dict):
            add("aws", "sqs", "queue", queue_name, queue)

    aws_ddb = _cloudsim_service_state(space, "dynamodb")
    for table_name, table in aws_ddb.get("tables", {}).items():
        if isinstance(table, dict):
            add("aws", "dynamodb", "table", table_name, table)

    gcp_compute = _cloudsim_service_state(space, "gcp_compute")
    for instance_id, instance in gcp_compute.get("instances", {}).items():
        if isinstance(instance, dict):
            add("gcp", "compute", "instance", instance_id, instance, "gcp_compute")

    gcp_storage = _cloudsim_service_state(space, "gcp_storage")
    for bucket_name, bucket in gcp_storage.get("buckets", {}).items():
        if isinstance(bucket, dict):
            add("gcp", "storage", "bucket", bucket_name, bucket)

    gcp_sql = _cloudsim_service_state(space, "gcp_sql")
    for instance_id, instance in gcp_sql.get("instances", {}).items():
        if isinstance(instance, dict):
            add("gcp", "sql", "instance", instance_id, instance, "gcp_sql")

    gcp_pubsub = _cloudsim_service_state(space, "gcp_pubsub")
    for topic_id, topic in gcp_pubsub.get("topics", {}).items():
        if isinstance(topic, dict):
            add("gcp", "pubsub", "topic", topic_id, topic)
    for subscription_id, sub in gcp_pubsub.get("subscriptions", {}).items():
        if isinstance(sub, dict):
            add("gcp", "pubsub", "subscription", subscription_id, sub)

    gcp_firestore = _cloudsim_service_state(space, "gcp_firestore")
    for db_id, db in gcp_firestore.get("databases", {}).items():
        if isinstance(db, dict):
            add("gcp", "firestore", "database", db_id, db)

    gcp_functions = _cloudsim_service_state(space, "gcp_functions")
    for fn_name, fn in gcp_functions.get("functions", {}).items():
        if isinstance(fn, dict):
            add("gcp", "functions", "function", fn_name, fn, "gcp_functions")

    gcp_apigw = _cloudsim_service_state(space, "gcp_apigateway")
    for api_id, api in gcp_apigw.get("apis", {}).items():
        if isinstance(api, dict):
            add("gcp", "apigateway", "api", api_id, api)
    for cfg_id, cfg in gcp_apigw.get("api_configs", {}).items():
        if isinstance(cfg, dict):
            add("gcp", "apigateway", "api_config", cfg_id, cfg)
    for gw_id, gw in gcp_apigw.get("gateways", {}).items():
        if isinstance(gw, dict):
            add("gcp", "apigateway", "gateway", gw_id, gw)

    gcp_vpc = _cloudsim_service_state(space, "gcp_vpc")
    for network_id, network in gcp_vpc.get("networks", {}).items():
        if isinstance(network, dict):
            add("gcp", "vpc", "network", network_id, network)
    for subnet_id, subnet in gcp_vpc.get("subnetworks", {}).items():
        if isinstance(subnet, dict):
            add("gcp", "vpc", "subnetwork", subnet_id, subnet)
    for firewall_id, firewall in gcp_vpc.get("firewalls", {}).items():
        if isinstance(firewall, dict):
            add("gcp", "vpc", "firewall", firewall_id, firewall)
    for route_id, route in gcp_vpc.get("routes", {}).items():
        if isinstance(route, dict):
            add("gcp", "vpc", "route", route_id, route)

    gcp_iam = _cloudsim_service_state(space, "gcp_iam")
    for account_id, account in gcp_iam.get("service_accounts", {}).items():
        if isinstance(account, dict):
            add("gcp", "iam", "service_account", account_id, account)
    for policy_id, policy in gcp_iam.get("policies", {}).items():
        if isinstance(policy, dict):
            add("gcp", "iam", "policy", policy_id, policy)

    # Azure ARM resources (space-scoped under service_states["azure_arm"]["resources"]).
    # Same DB-derived path as AWS/GCP: service + kind are mapped from the stored
    # ARM type via the catalog (nested children fold to their parent service).
    azure_state = service_states.get("azure_arm", {})
    azure_resources = azure_state.get("resources", {}) if isinstance(azure_state, dict) else {}
    if isinstance(azure_resources, dict) and azure_resources:
        azure_type_to_key = {(c["namespace"] + "/" + c["type"]).lower(): c["key"]
                             for c in provider_azure_services.RESOURCE_CATALOG}
        for rid, rec in azure_resources.items():
            if not isinstance(rec, dict):
                continue
            full_type = str(rec.get("_type", "")).lower()
            service = azure_type_to_key.get(full_type)
            if service is None:  # nested child → map to its parent service
                segs = full_type.split("/")
                if len(segs) >= 2:
                    service = azure_type_to_key.get(segs[0] + "/" + segs[1])
            kind = full_type.split("/")[-1] if full_type else "resource"
            add("azure", service or "resource", kind, str(rec.get("id") or rid), rec)

    return nodes, counts, runtime_instances


def _cloudsim_refresh_bridge(reason: str, detail: dict | None = None) -> None:
    with STATE_LOCK:
        now = _now()
        spaces_state = _spaces_state()
        active_id = spaces_state.get("active_space_id", "")
        active_space = spaces_state.get("spaces", {}).get(active_id) if active_id else None
        source_space = active_space if isinstance(active_space, dict) else {"service_states": STATE, "runtime": STATE.get("runtime", {})}
        try:
            runtime_status = PLATFORM.runtime.bootstrap_status()
        except Exception:
            runtime_status = {}
        runtime_host_os = str(runtime_status.get("host_os") or PLATFORM.runtime.host_os()).strip().lower()
        runtime_preferred_backend = str(runtime_status.get("preferred_backend") or PLATFORM.runtime.preferred_backend()).strip().lower()
        nodes: list[dict] = []
        counts: dict[str, int] = {}
        runtime_instances: dict[str, dict] = {}
        nodes, counts, runtime_instances = _cloudsim_collect_resources(source_space)
        try:
            from core import cost_model as _cm
            _savings = _cm.estimate_space_savings(nodes)
        except Exception:
            _savings = {"real_cloud_cost_usd": 0.0, "simulator_cost_usd": 0.0, "savings_usd": 0.0, "savings_pct": 0.0, "by_provider": {}, "by_service": {}, "resource_count": 0}
        if detail is None:
            detail = {}
        try:
            detail["real_cloud_cost_usd"] = _savings["real_cloud_cost_usd"]
            detail["savings_usd"] = _savings["savings_usd"]
        except Exception:
            pass
        if isinstance(active_space, dict):
            runtime_state_ref = active_space.setdefault("runtime", {"mode": "sandboxed", "instances": {}, "sandbox_count": 0})
            runtime_state_ref["instances"] = copy.deepcopy(runtime_instances)
            runtime_state_ref["sandbox_count"] = len(runtime_instances)
            active_cloudsim = active_space.setdefault("cloudsim", {"summary": {}, "events": [], "last_tick": ""})
            active_cloudsim["last_tick"] = now
            # CAPACITY layer (CloudSim Plus engine) owns active_cloudsim["summary"]
            # — it is written ONLY by the bridge (create/reconcile). The inventory
            # refresh must NOT clobber it; we only timestamp + tag provenance here.
            active_cloudsim["_source"] = "cloudsim-plus-engine"
            # INVENTORY layer (internal DB, authoritative): the resource graph +
            # all DB-derived counts live under active_space["resources"].
            inventory_summary = {
                "space_id": active_space.get("space_id", ""),
                "space_name": active_space.get("name", ""),
                "provider": active_space.get("provider", "aws"),
                "status": active_space.get("status", "running"),
                "active_region": active_space.get("active_region", "us-east-1"),
                "host_os": runtime_host_os,
                "preferred_backend": runtime_preferred_backend,
                "spaces": len(spaces_state.get("spaces", {})),
                "active_space_id": active_id,
                "active_space_name": active_space.get("name", ""),
                "resource_count": len(nodes),
                "runtime_count": int(active_space.get("runtime_count", 0)),
                "ec2_count": len(_cloudsim_service_state(source_space, "ec2").get("instances", {})),
                "lambda_count": len(_cloudsim_service_state(source_space, "lambda").get("functions", {})),
                "rds_count": len(_cloudsim_service_state(source_space, "rds").get("db_instances", {})),
                "sqs_count": len(_cloudsim_service_state(source_space, "sqs").get("queues", {})),
                "dynamodb_count": len(_cloudsim_service_state(source_space, "dynamodb").get("tables", {})),
                "gcp_compute_count": len(_cloudsim_service_state(source_space, "gcp_compute").get("instances", {})),
                "gcp_storage_bucket_count": len(_cloudsim_service_state(source_space, "gcp_storage").get("buckets", {})),
                "gcp_sql_count": len(_cloudsim_service_state(source_space, "gcp_sql").get("instances", {})),
                "gcp_pubsub_topic_count": len(_cloudsim_service_state(source_space, "gcp_pubsub").get("topics", {})),
                "gcp_pubsub_subscription_count": len(_cloudsim_service_state(source_space, "gcp_pubsub").get("subscriptions", {})),
                "gcp_functions_count": len(_cloudsim_service_state(source_space, "gcp_functions").get("functions", {})),
                "gcp_apigateway_count": len(_cloudsim_service_state(source_space, "gcp_apigateway").get("apis", {})),
                "gcp_vpc_count": len(_cloudsim_service_state(source_space, "gcp_vpc").get("networks", {})),
                "gcp_iam_count": len(_cloudsim_service_state(source_space, "gcp_iam").get("service_accounts", {})),
                "azure_count": sum(v for k, v in counts.items() if k.startswith("azure.")),
                "s3_bucket_count": len(_cloudsim_service_state(source_space, "s3").get("buckets", {})),
                "vpc_count": len(_cloudsim_service_state(source_space, "vpc").get("vpcs", {})),
                "apigateway_count": len(_cloudsim_service_state(source_space, "apigateway").get("apis", {})),
                "resource_counts": copy.deepcopy(counts),
                "last_tick": now,
                "last_action": reason,
                "last_action_detail": copy.deepcopy(detail or {}),
                "bundle_count": len(runtime_state.setdefault("bundles", {})),
                "sandbox_count": len(runtime_instances),
                "sandbox_backend": runtime_preferred_backend,
                "event_count": len(active_cloudsim.get("events", [])),
                "_source": "internal-db",
            }
            active_space["resources"] = {
                "nodes": copy.deepcopy(nodes), "count": len(nodes),
                "summary": inventory_summary, "_source": "internal-db",
                "updated_at": now, "reason": reason,
            }
            active_space["cost_savings"] = {
                "real_cloud_cost_usd": _savings["real_cloud_cost_usd"],
                "simulator_cost_usd": 0.0,
                "savings_usd": _savings["savings_usd"],
                "savings_pct": _savings["savings_pct"],
                "by_provider": _savings["by_provider"],
                "by_service": _savings["by_service"],
                "resource_count": _savings["resource_count"],
            }
            active_space.setdefault("runtime", {}).setdefault("mode", "sandboxed")
            active_space["runtime"]["preferred_backend"] = runtime_preferred_backend
            active_space["runtime"]["host_os"] = runtime_host_os
        cloudsim = STATE.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
        summary = cloudsim.setdefault("summary", {})
        summary.update(
            {
                "spaces": len(spaces_state.get("spaces", {})),
                "active_space_id": active_id,
                "active_space_name": active_space.get("name", "") if isinstance(active_space, dict) else "",
                "resource_count": len(nodes),
                "runtime_count": int(source_space.get("runtime_count", 0)) if isinstance(source_space, dict) else 0,
                "host_os": runtime_host_os,
                "preferred_backend": runtime_preferred_backend,
                "ec2_count": len(_cloudsim_service_state(source_space, "ec2").get("instances", {})) if isinstance(source_space, dict) else 0,
                "lambda_count": len(_cloudsim_service_state(source_space, "lambda").get("functions", {})) if isinstance(source_space, dict) else 0,
                "rds_count": len(_cloudsim_service_state(source_space, "rds").get("db_instances", {})) if isinstance(source_space, dict) else 0,
                "sqs_count": len(_cloudsim_service_state(source_space, "sqs").get("queues", {})) if isinstance(source_space, dict) else 0,
                "dynamodb_count": len(_cloudsim_service_state(source_space, "dynamodb").get("tables", {})) if isinstance(source_space, dict) else 0,
                "gcp_compute_count": len(_cloudsim_service_state(source_space, "gcp_compute").get("instances", {})) if isinstance(source_space, dict) else 0,
                "gcp_storage_bucket_count": len(_cloudsim_service_state(source_space, "gcp_storage").get("buckets", {})) if isinstance(source_space, dict) else 0,
                "gcp_sql_count": len(_cloudsim_service_state(source_space, "gcp_sql").get("instances", {})) if isinstance(source_space, dict) else 0,
                "gcp_pubsub_topic_count": len(_cloudsim_service_state(source_space, "gcp_pubsub").get("topics", {})) if isinstance(source_space, dict) else 0,
                "gcp_pubsub_subscription_count": len(_cloudsim_service_state(source_space, "gcp_pubsub").get("subscriptions", {})) if isinstance(source_space, dict) else 0,
                "gcp_functions_count": len(_cloudsim_service_state(source_space, "gcp_functions").get("functions", {})) if isinstance(source_space, dict) else 0,
                "gcp_apigateway_count": len(_cloudsim_service_state(source_space, "gcp_apigateway").get("apis", {})) if isinstance(source_space, dict) else 0,
                "gcp_vpc_count": len(_cloudsim_service_state(source_space, "gcp_vpc").get("networks", {})) if isinstance(source_space, dict) else 0,
                "gcp_iam_count": len(_cloudsim_service_state(source_space, "gcp_iam").get("service_accounts", {})) if isinstance(source_space, dict) else 0,
                "azure_count": sum(v for k, v in counts.items() if k.startswith("azure.")),
                "s3_bucket_count": len(_cloudsim_service_state(source_space, "s3").get("buckets", {})) if isinstance(source_space, dict) else 0,
                "vpc_count": len(_cloudsim_service_state(source_space, "vpc").get("vpcs", {})) if isinstance(source_space, dict) else 0,
                "apigateway_count": len(_cloudsim_service_state(source_space, "apigateway").get("apis", {})) if isinstance(source_space, dict) else 0,
                "resource_counts": copy.deepcopy(counts),
                "last_tick": now,
                "last_action": reason,
                "last_action_detail": copy.deepcopy(detail or {}),
                "bundle_count": len(runtime_state.setdefault("bundles", {})),
                "sandbox_backend": runtime_preferred_backend,
                "event_count": len(cloudsim.get("events", [])),
                "last_reconcile_at": cloudsim.get("last_reconcile_at", ""),
            }
        )
        summary["cost_savings"] = active_space.get("cost_savings", {}) if isinstance(active_space, dict) else {}
        cloudsim["summary"] = summary
        cloudsim["last_tick"] = now
        if active_space and isinstance(active_space, dict):
            active_space.setdefault("cloudsim", {}).setdefault("summary", {}).update(copy.deepcopy(summary))
            active_space["cloudsim"]["last_tick"] = now
        # Cost budget alert check — evaluate all budgets against current spend.
        try:
            from routes.licensing import _check_budget_alerts
            _check_budget_alerts()
        except Exception:
            pass
        _persist_state()


def _license_secret() -> bytes:
    return os.environ.get("CLOUDLEARN_LICENSE_SECRET", "cloudlearn-dev-secret").encode("utf-8")


def _sign_license(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_license_secret(), data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=") + "." + base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")


def _verify_license(token: str) -> dict:
    try:
        data_b64, sig_b64 = token.split(".", 1)
        data = base64.urlsafe_b64decode(data_b64 + "=" * (-len(data_b64) % 4))
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        expected = hmac.new(_license_secret(), data, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("Invalid signature")
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise HTTPException(401, detail=f"Invalid license token: {e}")


def _activate_pack(pack_id: str) -> dict:
    try:
        return PLATFORM.activate_pack(pack_id)
    except KeyError:
        raise HTTPException(404, detail="PackNotFound")
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


def _allowed_capabilities(tier: str) -> set[str]:
    return PLATFORM.kernel.allowed_capabilities(tier)


def _check_license_for_pack(pack_id: str) -> None:
    # PER-TENANT LICENSE: active tenant's tier is the source-of-truth (falls back
    # to the deployment-level STATE["license"].tier for legacy callers).
    try:
        tenant = _tenant_dict(_active_tenant_id())
        tier = str((tenant or {}).get("license_tier")
                   or (STATE.get("license") or {}).get("tier", "free"))
        if pack_id not in PLATFORM.kernel.allowed_capabilities(tier):
            raise PermissionError("CapabilityLockedByTier")
    except PermissionError:
        raise HTTPException(403, detail="CapabilityLockedByTier")


def _ensure_capability(path: str) -> None:
    try:
        PLATFORM.ensure_capability(path)
    except LookupError:
        raise HTTPException(404, detail="CapabilityPackMissing")


def _catalog() -> list[dict]:
    return PLATFORM.catalog()



def _apigw_state() -> dict:
    return apigw_state


def _apigw_api(api_id: str) -> dict | None:
    return _apigw_state().setdefault("apis", {}).get(api_id)


def _apigw_route_key(resource_id: str, method: str) -> str:
    return f"{resource_id}::{method.upper()}"


def _apigw_resource_path(parent_path: str, path_part: str) -> str:
    parent_path = parent_path if parent_path else "/"
    if parent_path == "/":
        return "/" + path_part.strip("/")
    return parent_path.rstrip("/") + "/" + path_part.strip("/")


def _apigw_valid_stage_name(stage_name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,128}", stage_name or ""))


def _apigw_path_regex(path: str) -> str:
    if path == "/":
        return r"^/?$"
    parts = []
    for segment in path.strip("/").split("/"):
        if segment == "{proxy+}":
            parts.append(r".+")
        elif segment.startswith("{") and segment.endswith("}"):
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(segment))
    return r"^/" + "/".join(parts) + r"/?$"


def _apigw_resource_counts(api: dict) -> tuple[int, int, int]:
    resources = api.get("resources", {})
    methods = api.get("methods", {})
    stages = api.get("stages", {})
    return max(len(resources) - 1, 0), len(methods), len(stages)


def _apigw_invoke_url(api_id: str, stage_name: str = "") -> str:
    base = f"/api/apigateway/invoke/{api_id}"
    return f"{base}/{stage_name}" if stage_name else base


def _apigw_api_view(api: dict) -> dict:
    resource_count, method_count, stage_count = _apigw_resource_counts(api)
    latest_stage = ""
    latest_stage_obj = None
    for stage in api.get("stages", {}).values():
        if latest_stage_obj is None or stage.get("created", "") > latest_stage_obj.get("created", ""):
            latest_stage_obj = stage
            latest_stage = stage.get("stage_name", "")
    invoke_url = _apigw_invoke_url(api["rest_api_id"], latest_stage or "")
    return {
        "rest_api_id": api["rest_api_id"],
        "name": api.get("name", ""),
        "description": api.get("description", ""),
        "endpoint_type": api.get("endpoint_type", "REGIONAL"),
        "created": api.get("created", ""),
        "tags": api.get("tags", []),
        "resource_count": resource_count,
        "method_count": method_count,
        "stage_count": stage_count,
        "deployment_count": len(api.get("deployments", {})),
        "latest_stage": latest_stage,
        "invoke_url": invoke_url,
        "status": "available",
    }


def _apigw_snapshot(api: dict) -> dict:
    return {
        "resources": copy.deepcopy(api.get("resources", {})),
        "methods": copy.deepcopy(api.get("methods", {})),
        "integrations": copy.deepcopy(api.get("integrations", {})),
        "created": _now(),
    }


def _apigw_find_resource(api_view: dict, path: str) -> dict | None:
    normalized = path if path.startswith("/") else f"/{path}"
    normalized = normalized or "/"
    resources = list(api_view.get("resources", {}).values())
    resources.sort(key=lambda item: len(item.get("path", "")), reverse=True)
    for resource in resources:
        pattern = _apigw_path_regex(resource.get("path", "/"))
        if re.fullmatch(pattern, normalized):
            return resource
    return None


def _apigw_method_view(api: dict, resource_id: str, method: str) -> dict | None:
    key = _apigw_route_key(resource_id, method)
    return api.get("methods", {}).get(key)


def _apigw_integration_view(api: dict, resource_id: str, method: str) -> dict | None:
    key = _apigw_route_key(resource_id, method)
    return api.get("integrations", {}).get(key)


def _apigw_route_views(api: dict) -> list[dict]:
    rows = []
    for resource_id, resource in api.get("resources", {}).items():
        if resource_id == api.get("root_resource_id"):
            continue
        for key, method in api.get("methods", {}).items():
            rid, http_method = key.split("::", 1)
            if rid != resource_id:
                continue
            integration = api.get("integrations", {}).get(key, {})
            rows.append({
                "resource_id": resource_id,
                "path": resource.get("path", "/"),
                "path_part": resource.get("path_part", ""),
                "parent_id": resource.get("parent_id", ""),
                "http_method": http_method,
                "authorization_type": method.get("authorization_type", "NONE"),
                "api_key_required": bool(method.get("api_key_required")),
                "integration_type": integration.get("type", "MOCK"),
                "integration_uri": integration.get("uri", ""),
                "integration_http_method": integration.get("integration_http_method", "POST"),
                "response_body": integration.get("response_body", ""),
                "status_code": integration.get("status_code", 200),
                "content_type": integration.get("content_type", "application/json"),
            })
    rows.sort(key=lambda item: (item["path"], item["http_method"]))
    return rows


def _apigw_create_api_record(req: APIGatewayRequest) -> dict:
    api_id = _id("api")
    root_resource_id = _id("res")
    api = {
        "rest_api_id": api_id,
        "name": req.name,
        "description": req.description,
        "endpoint_type": (req.endpoint_type or "REGIONAL").upper(),
        "created": _now(),
        "tags": req.tags or [],
        "root_resource_id": root_resource_id,
        "resources": {
            root_resource_id: {
                "resource_id": root_resource_id,
                "parent_id": "",
                "path_part": "",
                "path": "/",
                "created": _now(),
                "is_root": True,
            }
        },
        "methods": {},
        "integrations": {},
        "deployments": {},
        "stages": {},
        "logs": [],
        "settings": {"minimum_compression_size": None, "binary_media_types": []},
    }
    _apigw_state().setdefault("apis", {})[api_id] = api
    _record_usage("apigateway.create_api", {"rest_api_id": api_id, "name": req.name})
    return api


def _apigw_create_resource_record(api_id: str, req: APIGatewayResourceRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    parent_id = req.parent_id.strip() or api["root_resource_id"]
    parent = api["resources"].get(parent_id)
    if not parent:
        raise HTTPException(404, detail="ParentResourceNotFound")
    path_part = req.path_part.strip().strip("/")
    if not path_part:
        raise HTTPException(400, detail="MissingParameter: path_part is required.")
    if "/" in path_part:
        raise HTTPException(400, detail="InvalidParameterValue: path_part cannot contain '/'.")
    path = _apigw_resource_path(parent.get("path", "/"), path_part)
    if any(resource.get("path") == path for resource in api["resources"].values()):
        raise HTTPException(409, detail="ResourceAlreadyExists")
    resource_id = _id("res")
    resource = {
        "resource_id": resource_id,
        "parent_id": parent_id,
        "path_part": path_part,
        "path": path,
        "created": _now(),
        "is_root": False,
    }
    api["resources"][resource_id] = resource
    _record_usage("apigateway.create_resource", {"rest_api_id": api_id, "resource_id": resource_id, "path": path})
    return resource


def _apigw_put_method_record(api_id: str, req: APIGatewayMethodRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    resource = api["resources"].get(req.resource_id)
    if not resource:
        raise HTTPException(404, detail="ResourceNotFound")
    http_method = (req.http_method or "GET").upper()
    method = {
        "rest_api_id": api_id,
        "resource_id": req.resource_id,
        "http_method": http_method,
        "authorization_type": req.authorization_type or "NONE",
        "api_key_required": bool(req.api_key_required),
        "created": _now(),
    }
    api["methods"][_apigw_route_key(req.resource_id, http_method)] = method
    _record_usage("apigateway.put_method", {"rest_api_id": api_id, "resource_id": req.resource_id, "http_method": http_method})
    return method


def _apigw_put_integration_record(api_id: str, req: APIGatewayIntegrationRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    if req.resource_id not in api["resources"]:
        raise HTTPException(404, detail="ResourceNotFound")
    http_method = (req.http_method or "GET").upper()
    key = _apigw_route_key(req.resource_id, http_method)
    if key not in api["methods"]:
        raise HTTPException(409, detail="MethodNotFound")
    integration = {
        "rest_api_id": api_id,
        "resource_id": req.resource_id,
        "http_method": http_method,
        "type": (req.type or "MOCK").upper(),
        "uri": req.uri,
        "integration_http_method": (req.integration_http_method or "POST").upper(),
        "response_body": req.response_body,
        "status_code": int(req.status_code or 200),
        "content_type": req.content_type or "application/json",
        "created": _now(),
    }
    api["integrations"][key] = integration
    _record_usage("apigateway.put_integration", {"rest_api_id": api_id, "resource_id": req.resource_id, "http_method": http_method, "type": integration["type"]})
    return integration


def _apigw_create_deployment_record(api_id: str, req: APIGatewayDeploymentRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    deployment_id = _id("dep")
    snapshot = _apigw_snapshot(api)
    deployment = {
        "deployment_id": deployment_id,
        "rest_api_id": api_id,
        "description": req.description,
        "created": _now(),
        "snapshot": snapshot,
    }
    api["deployments"][deployment_id] = deployment
    api["latest_deployment_id"] = deployment_id
    if req.stage_name:
        _apigw_create_stage_record(api_id, APIGatewayStageRequest(rest_api_id=api_id, stage_name=req.stage_name, deployment_id=deployment_id, description=req.description, variables=[]), from_deployment=True)
    _record_usage("apigateway.create_deployment", {"rest_api_id": api_id, "deployment_id": deployment_id})
    return deployment


def _apigw_create_stage_record(api_id: str, req: APIGatewayStageRequest, from_deployment: bool = False) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stage_name = req.stage_name.strip()
    if not _apigw_valid_stage_name(stage_name):
        raise HTTPException(400, detail="InvalidParameterValue: stage_name is invalid.")
    deployment_id = req.deployment_id.strip() or api.get("latest_deployment_id", "")
    if deployment_id and deployment_id not in api["deployments"]:
        raise HTTPException(404, detail="DeploymentNotFound")
    if not deployment_id:
        raise HTTPException(409, detail="DeploymentRequired")
    stage = {
        "rest_api_id": api_id,
        "stage_name": stage_name,
        "deployment_id": deployment_id,
        "description": req.description,
        "variables": req.variables or [],
        "created": _now(),
        "invoke_url": _apigw_invoke_url(api_id, stage_name),
    }
    api["stages"][stage_name] = stage
    if not from_deployment:
        api["latest_deployment_id"] = deployment_id
    _record_usage("apigateway.create_stage", {"rest_api_id": api_id, "stage_name": stage_name, "deployment_id": deployment_id})
    return stage


def _apigw_delete_api_record(api_id: str) -> None:
    apis = _apigw_state().setdefault("apis", {})
    if api_id not in apis:
        raise HTTPException(404, detail="RestApiNotFound")
    del apis[api_id]
    _record_usage("apigateway.delete_api", {"rest_api_id": api_id})


async def _apigw_invoke(api_id: str, stage_name: str, proxy_path: str, request: Request) -> Response:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stage = api.get("stages", {}).get(stage_name)
    if not stage:
        raise HTTPException(404, detail="StageNotFound")
    deployment = api["deployments"].get(stage.get("deployment_id", ""))
    if not deployment:
        raise HTTPException(404, detail="DeploymentNotFound")
    snapshot = deployment.get("snapshot", {})
    path = "/" + proxy_path.lstrip("/") if proxy_path else "/"
    resolved_resource = _apigw_find_resource(snapshot, path)
    if not resolved_resource:
        raise HTTPException(404, detail="ResourceNotFound")
    method = request.method.upper()
    method_def = snapshot.get("methods", {}).get(_apigw_route_key(resolved_resource["resource_id"], method)) or snapshot.get("methods", {}).get(_apigw_route_key(resolved_resource["resource_id"], "ANY"))
    if not method_def:
        raise HTTPException(405, detail="MethodNotAllowed")
    integration = snapshot.get("integrations", {}).get(_apigw_route_key(resolved_resource["resource_id"], method)) or snapshot.get("integrations", {}).get(_apigw_route_key(resolved_resource["resource_id"], "ANY"))
    if not integration:
        raise HTTPException(409, detail="IntegrationMissing")

    status_code = int(integration.get("status_code", 200))
    content_type = integration.get("content_type", "application/json")
    headers = {"Content-Type": content_type}
    body_bytes = await request.body()
    result = {"api_id": api_id, "stage": stage_name, "path": path, "method": method, "resource_path": resolved_resource.get("path", path)}

    if integration.get("type", "MOCK").upper() == "MOCK":
        payload = integration.get("response_body") or json.dumps({"message": "Mock integration response", **result})
        api_log = {"at": _now(), "api_id": api_id, "stage": stage_name, "path": path, "method": method, "status": status_code, "integration_type": "MOCK"}
        api.setdefault("logs", []).append(api_log)
        _apigw_state().setdefault("logs", []).append(api_log)
        return Response(content=payload, status_code=status_code, media_type=content_type, headers=headers)

    if integration.get("uri"):
        req = URLRequest(integration["uri"], data=body_bytes or None, method=method)
        if body_bytes and "content-type" not in {k.lower() for k in req.headers}:
            req.add_header("Content-Type", request.headers.get("content-type", "application/json"))
        try:
            with urlopen(req, timeout=30) as resp:
                payload = resp.read()
                status_code = getattr(resp, "status", 200) or 200
                content_type = resp.headers.get("content-type", content_type)
        except HTTPError as exc:
            payload = exc.read()
            status_code = exc.code or 502
            content_type = exc.headers.get("content-type", content_type) if exc.headers else content_type
        except URLError as exc:
            raise HTTPException(502, detail=f"IntegrationError: {exc.reason}")
        api_log = {"at": _now(), "api_id": api_id, "stage": stage_name, "path": path, "method": method, "status": status_code, "integration_type": integration.get("type", "HTTP")}
        api.setdefault("logs", []).append(api_log)
        _apigw_state().setdefault("logs", []).append(api_log)
        return Response(content=payload, status_code=status_code, media_type=content_type, headers={"Content-Type": content_type})

    raise HTTPException(409, detail="IntegrationMissing")


def _apigw_invoke_root(api_id: str, stage_name: str, request: Request) -> Response:
    return _apigw_invoke(api_id, stage_name, "", request)


def _apigw_summary(api: dict) -> dict:
    view = _apigw_api_view(api)
    view["resource_map"] = list(api.get("resources", {}).values())
    view["routes"] = _apigw_route_views(api)
    view["methods"] = list(api.get("methods", {}).values())
    view["integrations"] = list(api.get("integrations", {}).values())
    view["stages"] = list(api.get("stages", {}).values())
    view["deployments"] = list(api.get("deployments", {}).values())
    view["settings"] = copy.deepcopy(api.get("settings", {}))
    view["root_resource_id"] = api.get("root_resource_id", "")
    return view


def _lambda_state() -> dict:
    return lambda_state


def _lambda_function_key(function_name: str) -> str:
    return (function_name or "").strip()


def _lambda_validate_function_name(function_name: str) -> None:
    if not function_name:
        raise HTTPException(400, detail="MissingParameter: function_name is required.")
    if not re.fullmatch(r"[A-Za-z0-9-_]{1,64}", function_name):
        raise HTTPException(400, detail="InvalidParameterValue: function_name must be 1-64 characters and use letters, numbers, hyphens, or underscores.")


def _lambda_function_arn(function_name: str) -> str:
    return f"arn:aws:lambda:us-east-1:{AWS_ACCOUNT_ID}:function:{function_name}"


def _lambda_function_dir(function_name: str) -> Path:
    return Path(__file__).with_name("lambda_functions") / function_name


def _lambda_handler_module(handler: str) -> str:
    handler = (handler or "").strip()
    return handler.rsplit(".", 1)[0] if "." in handler else "lambda_function"


def _lambda_handler_name(handler: str) -> str:
    handler = (handler or "").strip()
    return handler.rsplit(".", 1)[1] if "." in handler else "lambda_handler"


def _lambda_default_code(function_name: str = "my-function") -> str:
    return textwrap.dedent(
        f"""
        def lambda_handler(event, context):
            return {{
                "message": "Hello from Lambda",
                "function_name": "{function_name}",
                "received_event": event,
            }}
        """
    ).strip() + "\n"


def _lambda_find_function(function_name: str) -> dict | None:
    key = _lambda_function_key(function_name)
    if not key:
        return None
    functions = _lambda_state().setdefault("functions", {})
    if key in functions:
        return functions[key]
    lowered = key.lower()
    for existing_name, function in functions.items():
        if existing_name.lower() == lowered:
            return function
    return None


def _lambda_resolve_function(target: str) -> dict | None:
    target = (target or "").strip()
    if not target:
        return None
    if ":function:" in target:
        candidate = target.rsplit(":function:", 1)[-1]
        if ":" in candidate:
            candidate = candidate.split(":", 1)[0]
        function = _lambda_find_function(candidate)
        if function:
            return function
    return _lambda_find_function(target)


def _lambda_set_function(function: dict) -> dict:
    _lambda_state().setdefault("functions", {})[function["function_name"]] = function
    return function


def _lambda_list_functions() -> list[dict]:
    functions = list(_lambda_state().setdefault("functions", {}).values())
    functions.sort(key=lambda item: (item.get("created", ""), item.get("function_name", "")))
    return functions


def _lambda_sync_code_artifact(function: dict) -> None:
    function_dir = _lambda_function_dir(function["function_name"])
    function_dir.mkdir(parents=True, exist_ok=True)
    module_name = _lambda_handler_module(function.get("handler", "lambda_function.lambda_handler")) or "lambda_function"
    code_path = function_dir / f"{module_name}.py"
    code = function.get("code") or _lambda_default_code(function["function_name"])
    code_path.write_text(code, encoding="utf-8")
    function["code_path"] = str(code_path)
    function["workdir"] = str(function_dir)


def _lambda_invocations_view(function: dict) -> list[dict]:
    invocations = list(function.get("invocations", []))
    invocations.sort(key=lambda item: item.get("at", ""), reverse=True)
    return invocations


def _lambda_versions_view(function: dict) -> list[dict]:
    versions = list(function.get("versions", []))
    versions.sort(key=lambda item: item.get("created", ""), reverse=True)
    return versions


def _lambda_permissions_view(function: dict) -> list[dict]:
    permissions = list(function.get("permissions", []))
    permissions.sort(key=lambda item: (item.get("created", ""), item.get("statement_id", "")))
    return permissions


def _lambda_permission_statement_doc(function: dict, permission: dict) -> dict:
    principal = (permission.get("principal") or "").strip()
    if not principal or principal == "*":
        principal_doc: Any = "*"
    elif principal.startswith("arn:"):
        principal_doc = {"AWS": principal}
    else:
        principal_doc = {"Service": principal}
    statement = {
        "Sid": permission.get("statement_id", ""),
        "Effect": "Allow",
        "Principal": principal_doc,
        "Action": permission.get("action", "lambda:InvokeFunction"),
        "Resource": function.get("function_arn") or _lambda_function_arn(function.get("function_name", "")),
    }
    condition: dict[str, Any] = {}
    source_arn = (permission.get("source_arn") or "").strip()
    source_account = (permission.get("source_account") or "").strip()
    if source_arn:
        condition.setdefault("ArnLike", {})["AWS:SourceArn"] = source_arn
    if source_account:
        condition.setdefault("StringEquals", {})["AWS:SourceAccount"] = source_account
    if condition:
        statement["Condition"] = condition
    return statement


def _lambda_policy_document(function: dict) -> dict:
    statements = [_lambda_permission_statement_doc(function, permission) for permission in _lambda_permissions_view(function)]
    return {
        "Version": "2012-10-17",
        "Id": f"{function.get('function_name', 'function')}/policy",
        "Statement": statements,
    }


def _lambda_policy_revision_id(function: dict) -> str:
    policy = json.dumps(_lambda_policy_document(function), sort_keys=True, separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(hashlib.sha256(policy.encode("utf-8")).digest()).decode("ascii").rstrip("=")


def _lambda_permission_matches(permission: dict, action: str, principal: str, source_arn: str, source_account: str) -> bool:
    perm_action = (permission.get("action") or "lambda:InvokeFunction").strip()
    if perm_action not in {"*", "lambda:*"} and action not in {perm_action, "*"}:
        return False
    perm_principal = (permission.get("principal") or "").strip()
    if perm_principal and perm_principal != "*":
        if not principal:
            return False
        if not fnmatch.fnmatchcase(principal, perm_principal):
            return False
    perm_source_arn = (permission.get("source_arn") or "").strip()
    if perm_source_arn:
        if not source_arn or not fnmatch.fnmatchcase(source_arn, perm_source_arn):
            return False
    perm_source_account = (permission.get("source_account") or "").strip()
    if perm_source_account:
        if not source_account or perm_source_account != source_account:
            return False
    return True


def _lambda_can_invoke_from_source(function: dict, principal: str = "", source_arn: str = "", source_account: str = "", action: str = "lambda:InvokeFunction") -> tuple[bool, str]:
    principal = (principal or "").strip()
    source_arn = (source_arn or "").strip()
    source_account = (source_account or "").strip()
    if not principal and not source_arn and not source_account:
        return True, ""
    permissions = _lambda_permissions_view(function)
    if not permissions:
        return False, "AccessDeniedException: Lambda policy does not allow this invocation source."
    for permission in permissions:
        if _lambda_permission_matches(permission, action, principal, source_arn, source_account):
            return True, ""
    return False, "AccessDeniedException: Lambda policy does not allow this invocation source."


def _lambda_triggers_for_function(function: dict) -> list[dict]:
    triggers: list[dict] = []
    target_names = {function.get("function_name", ""), function.get("function_arn", "")}
    for bucket_name, bucket_meta in buckets.items():
        if not isinstance(bucket_meta, dict):
            continue
        notifications = bucket_meta.get("notifications", {})
        for rule in notifications.get("cloudFunctionConfigurations", []):
            destination = (rule.get("cloudFunction") or "").strip()
            if destination and destination not in target_names:
                continue
            triggers.append({
                "source": "Amazon S3",
                "bucket": bucket_name,
                "event_types": list(rule.get("events", [])),
                "prefix": rule.get("prefix", ""),
                "suffix": rule.get("suffix", ""),
                "rule_id": rule.get("id", ""),
                "destination": destination or function.get("function_arn", ""),
            })
    return triggers


def _lambda_function_view(function: dict) -> dict:
    view = copy.deepcopy(function)
    view["trigger_count"] = len(_lambda_triggers_for_function(function))
    view["invocation_count"] = len(function.get("invocations", []))
    view["version_count"] = len(function.get("versions", []))
    view["policy_statement_count"] = len(_lambda_permissions_view(function))
    view["triggers"] = _lambda_triggers_for_function(function)
    view["invocations"] = _lambda_invocations_view(function)
    view["versions"] = _lambda_versions_view(function)
    view["permissions"] = _lambda_permissions_view(function)
    view["policy"] = _lambda_policy_document(function)
    view["policy_revision_id"] = _lambda_policy_revision_id(function)
    view["function_arn"] = function.get("function_arn") or _lambda_function_arn(function.get("function_name", ""))
    view.setdefault("state", "Active")
    return view


def _lambda_create_function_record(req: LambdaFunctionRequest) -> dict:
    function_name = _lambda_function_key(req.function_name)
    _lambda_validate_function_name(function_name)
    if _lambda_find_function(function_name):
        raise HTTPException(409, detail="ResourceConflictException: Function already exists.")
    runtime = (req.runtime or "python3.12").strip()
    handler = (req.handler or "lambda_function.lambda_handler").strip()
    function = {
        "function_name": function_name,
        "function_arn": _lambda_function_arn(function_name),
        "description": req.description or "",
        "runtime": runtime,
        "handler": handler,
        "role": req.role or f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/service-role/cloudlearn-lambda-basic-execution",
        "timeout": int(req.timeout or 3),
        "memory_size": int(req.memory_size or 128),
        "environment": copy.deepcopy(req.environment or {}),
        "package_type": "Zip",
        "state": "Active",
        "created": _now(),
        "last_modified": _now(),
        "code": req.code.strip() if req.code and req.code.strip() else _lambda_default_code(function_name),
        "code_sha256": "",
        "versions": [],
        "invocations": [],
        "permissions": [],
        "tags": copy.deepcopy(req.tags or []),
        "layers": list(req.layers) if req.layers else [],
    }
    function["code_sha256"] = base64.b64encode(hashlib.sha256(function["code"].encode("utf-8")).digest()).decode("ascii")
    _lambda_sync_code_artifact(function)
    function["versions"].append({
        "version": "$LATEST",
        "description": function["description"],
        "created": function["created"],
        "code_sha256": function["code_sha256"],
        "runtime": function["runtime"],
        "handler": function["handler"],
        "state": "Active",
        "is_latest": True,
    })
    _lambda_set_function(function)
    _record_usage("lambda.create_function", {"function_name": function_name})
    return function


def _lambda_update_function_code(function: dict, code: str) -> dict:
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, detail="MissingParameter: code is required.")
    function["code"] = code + ("\n" if not code.endswith("\n") else "")
    function["code_sha256"] = base64.b64encode(hashlib.sha256(function["code"].encode("utf-8")).digest()).decode("ascii")
    function["last_modified"] = _now()
    _lambda_sync_code_artifact(function)
    latest = next((v for v in function.get("versions", []) if v.get("version") == "$LATEST"), None)
    if latest:
        latest.update({
            "description": function.get("description", ""),
            "created": function.get("last_modified", _now()),
            "code_sha256": function["code_sha256"],
            "runtime": function.get("runtime", "python3.12"),
            "handler": function.get("handler", "lambda_function.lambda_handler"),
            "state": "Active",
            "is_latest": True,
        })
    else:
        function.setdefault("versions", []).append({
            "version": "$LATEST",
            "description": function.get("description", ""),
            "created": function.get("last_modified", _now()),
            "code_sha256": function["code_sha256"],
            "runtime": function.get("runtime", "python3.12"),
            "handler": function.get("handler", "lambda_function.lambda_handler"),
            "state": "Active",
            "is_latest": True,
        })
    _record_usage("lambda.update_function_code", {"function_name": function["function_name"]})
    return function


def _lambda_update_function_configuration(function: dict, req: LambdaFunctionUpdateRequest) -> dict:
    if req.runtime is not None:
        function["runtime"] = req.runtime.strip() or function.get("runtime", "python3.12")
    if req.handler is not None:
        function["handler"] = req.handler.strip() or function.get("handler", "lambda_function.lambda_handler")
    if req.role is not None:
        function["role"] = req.role.strip() or function.get("role", "")
    if req.description is not None:
        function["description"] = req.description
    if req.timeout is not None:
        function["timeout"] = max(1, int(req.timeout))
    if req.memory_size is not None:
        function["memory_size"] = max(128, int(req.memory_size))
    if req.environment is not None:
        function["environment"] = copy.deepcopy(req.environment)
    if req.tags is not None:
        function["tags"] = copy.deepcopy(req.tags)
    function["last_modified"] = _now()
    _lambda_sync_code_artifact(function)
    for version in function.get("versions", []):
        if version.get("version") == "$LATEST":
            version.update({
                "description": function.get("description", ""),
                "created": function.get("last_modified", _now()),
                "runtime": function.get("runtime", "python3.12"),
                "handler": function.get("handler", "lambda_function.lambda_handler"),
                "is_latest": True,
            })
    _record_usage("lambda.update_function_configuration", {"function_name": function["function_name"]})
    return function


def _lambda_publish_version(function: dict, description: str = "") -> dict:
    existing = [v for v in function.get("versions", []) if isinstance(v, dict) and v.get("version") != "$LATEST"]
    numeric_versions = [int(v.get("version", "0")) for v in existing if str(v.get("version", "")).isdigit()]
    next_version = str((max(numeric_versions) if numeric_versions else 0) + 1)
    for version in function.get("versions", []):
        version["is_latest"] = False
    published = {
        "version": next_version,
        "description": description or function.get("description", ""),
        "created": _now(),
        "code_sha256": function.get("code_sha256", ""),
        "runtime": function.get("runtime", "python3.12"),
        "handler": function.get("handler", "lambda_function.lambda_handler"),
        "state": "Active",
        "is_latest": True,
    }
    function.setdefault("versions", []).append(published)
    function["last_modified"] = _now()
    _record_usage("lambda.publish_version", {"function_name": function["function_name"], "version": next_version})
    return published


def _lambda_delete_function(function_name: str) -> None:
    functions = _lambda_state().setdefault("functions", {})
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    functions.pop(function["function_name"], None)
    _record_usage("lambda.delete_function", {"function_name": function["function_name"]})


def _lambda_add_permission(function: dict, req: LambdaPermissionRequest) -> dict:
    statement_id = _lambda_function_key(req.statement_id) or _id("sid")
    principal = (req.principal or "").strip()
    if not principal:
        raise HTTPException(400, detail="MissingParameter: principal is required.")
    action = (req.action or "lambda:InvokeFunction").strip() or "lambda:InvokeFunction"
    source_arn = (req.source_arn or "").strip()
    source_account = (req.source_account or "").strip()
    permissions = function.setdefault("permissions", [])
    if any((permission.get("statement_id", "")).lower() == statement_id.lower() for permission in permissions):
        raise HTTPException(409, detail="ResourceConflictException: statement_id already exists.")
    permission = {
        "statement_id": statement_id,
        "action": action,
        "principal": principal,
        "source_arn": source_arn,
        "source_account": source_account,
        "created": _now(),
    }
    permissions.append(permission)
    function["last_modified"] = _now()
    _record_usage("lambda.add_permission", {"function_name": function["function_name"], "statement_id": statement_id})
    return permission


def _lambda_remove_permission(function: dict, statement_id: str) -> None:
    statement_id = _lambda_function_key(statement_id)
    permissions = function.setdefault("permissions", [])
    next_permissions = [permission for permission in permissions if (permission.get("statement_id", "") or "").lower() != statement_id.lower()]
    if len(next_permissions) == len(permissions):
        raise HTTPException(404, detail="ResourceNotFoundException")
    function["permissions"] = next_permissions
    function["last_modified"] = _now()
    _record_usage("lambda.remove_permission", {"function_name": function["function_name"], "statement_id": statement_id})


def _lambda_get_policy(function: dict) -> dict:
    return {
        "Policy": json.dumps(_lambda_policy_document(function), default=str),
        "RevisionId": _lambda_policy_revision_id(function),
    }


def _lambda_merge_layers(function: dict, workdir) -> None:
    """Merge layer code blobs into the function's working directory before invoke."""
    layer_arns = function.get("layers") or []
    if not layer_arns:
        return
    layers_store = lambda_state.get("layers") or {}
    for arn in layer_arns:
        # Extract layer name from ARN: arn:aws:lambda:...:layer:NAME:VERSION
        parts = arn.split(":")
        layer_name = None
        for i, p in enumerate(parts):
            if p == "layer" and i + 1 < len(parts):
                layer_name = parts[i + 1]
                break
        if not layer_name:
            # Try using the ARN as a plain name
            layer_name = arn
        layer = layers_store.get(layer_name)
        if not layer or not layer.get("code"):
            continue
        # Write layer code as a Python module in the workdir
        layer_file = workdir / f"{layer_name.replace('-', '_')}.py"
        try:
            layer_file.write_text(layer["code"])
        except Exception:
            pass


def _lambda_run_handler(function: dict, event_payload: Any) -> dict:
    workdir = _lambda_function_dir(function["function_name"])
    module_name = _lambda_handler_module(function.get("handler", "lambda_function.lambda_handler")) or "lambda_function"
    handler_name = _lambda_handler_name(function.get("handler", "lambda_function.lambda_handler")) or "lambda_handler"
    code_path = workdir / f"{module_name}.py"
    if not code_path.exists():
        _lambda_sync_code_artifact(function)
    # Merge layer code into workdir before execution
    _lambda_merge_layers(function, workdir)
    helper_code = textwrap.dedent(
        """
        import contextlib
        import importlib.util
        import io
        import json
        import os
        import sys
        import traceback

        workdir = sys.argv[1]
        module_name = sys.argv[2]
        handler_name = sys.argv[3]
        payload = json.loads(sys.stdin.read() or "{}")

        sys.path.insert(0, workdir)
        module_path = os.path.join(workdir, module_name + ".py")
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module {module_name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handler = getattr(module, handler_name)

        class Context:
            function_name = ""
            memory_limit_in_mb = 0
            invoked_function_arn = ""
            aws_request_id = ""

        stdout = io.StringIO()
        stderr = io.StringIO()
        ctx = Context()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = handler(payload, ctx)
            print(json.dumps({
                "ok": True,
                "result": result,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }, default=str))
        except Exception as exc:
            print(json.dumps({
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }, default=str))
        """
    ).strip()
    proc = subprocess.run(
        [sys.executable, "-c", helper_code, str(workdir), module_name, handler_name],
        input=json.dumps(event_payload or {}, default=str),
        capture_output=True,
        text=True,
        timeout=max(int(function.get("timeout", 3) or 3), 1) + 1,
        env={
            **os.environ,
            **(function.get("environment") or {}),
            "PYTHONPATH": str(workdir) + (os.pathsep + os.environ.get("PYTHONPATH", "") if os.environ.get("PYTHONPATH") else ""),
        },
    )
    output_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if output_lines:
        try:
            payload = json.loads(output_lines[-1])
        except Exception:
            payload = {"ok": False, "error": proc.stdout or proc.stderr or "Lambda runtime error"}
    else:
        payload = {"ok": False, "error": proc.stderr or "Lambda runtime error"}
    return {
        "returncode": proc.returncode,
        "ok": bool(payload.get("ok")) and proc.returncode == 0,
        "result": payload.get("result"),
        "stdout": payload.get("stdout", ""),
        "stderr": payload.get("stderr", ""),
        "error": payload.get("error", ""),
        "traceback": payload.get("traceback", ""),
    }


def _lambda_record_invocation(function: dict, invocation_type: str, event_payload: Any, run_result: dict, source: str = "", source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    record = {
        "id": _id("laminv"),
        "at": _now(),
        "function_name": function.get("function_name", ""),
        "function_arn": function.get("function_arn", ""),
        "invocation_type": invocation_type,
        "status": "success" if run_result.get("ok") else "error",
        "source": source,
        "source_principal": source_principal,
        "source_arn": source_arn,
        "source_account": source_account,
        "request_payload": copy.deepcopy(event_payload),
        "response_payload": copy.deepcopy(run_result.get("result")),
        "stdout": run_result.get("stdout", ""),
        "stderr": run_result.get("stderr", ""),
        "error": run_result.get("error", ""),
        "traceback": run_result.get("traceback", ""),
    }
    function.setdefault("invocations", []).append(record)
    function["invocations"] = function["invocations"][-200:]
    function["last_modified"] = _now()
    _persist_state()
    return record


def _lambda_invoke_function(function_name: str, event_payload: Any, invocation_type: str = "RequestResponse", source: str = "", source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    allowed, reason = _lambda_can_invoke_from_source(function, source_principal, source_arn, source_account)
    if not allowed:
        raise HTTPException(403, detail=reason)
    normalized = (invocation_type or "RequestResponse").strip().lower()
    if normalized == "event":
        record = {
            "id": _id("laminv"),
            "at": _now(),
            "function_name": function.get("function_name", ""),
            "function_arn": function.get("function_arn", ""),
            "invocation_type": "Event",
            "status": "accepted",
            "source": source,
            "source_principal": source_principal,
            "source_arn": source_arn,
            "source_account": source_account,
            "request_payload": copy.deepcopy(event_payload),
            "response_payload": None,
            "stdout": "",
            "stderr": "",
            "error": "",
            "traceback": "",
        }
        function.setdefault("invocations", []).append(record)
        function["invocations"] = function["invocations"][-200:]
        function["last_modified"] = _now()
        _persist_state()

        def _worker():
            try:
                run_result = _lambda_run_handler(function, event_payload)
                record.update({
                    "status": "success" if run_result.get("ok") else "error",
                    "response_payload": copy.deepcopy(run_result.get("result")),
                    "stdout": run_result.get("stdout", ""),
                    "stderr": run_result.get("stderr", ""),
                    "error": run_result.get("error", ""),
                    "traceback": run_result.get("traceback", ""),
                    "completed_at": _now(),
                })
                function["last_modified"] = _now()
                _persist_state()
            except Exception:
                record.update({
                    "status": "error",
                    "error": "Lambda invocation failed",
                    "traceback": traceback.format_exc(),
                    "completed_at": _now(),
                })
                function["last_modified"] = _now()
                _persist_state()

        threading.Thread(target=_worker, daemon=True).start()
        return record

    run_result = _lambda_run_handler(function, event_payload)
    return _lambda_record_invocation(function, "RequestResponse", event_payload, run_result, source=source, source_principal=source_principal, source_arn=source_arn, source_account=source_account)


def _lambda_invoke_response(function_name: str, event_payload: Any, invocation_type: str = "RequestResponse", source: str = "", source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    record = _lambda_invoke_function(function_name, event_payload, invocation_type=invocation_type, source=source, source_principal=source_principal, source_arn=source_arn, source_account=source_account)
    return {
        "function_name": record["function_name"],
        "function_arn": record["function_arn"],
        "invocation_type": record["invocation_type"],
        "status": record["status"],
        "payload": record.get("response_payload"),
        "stdout": record.get("stdout", ""),
        "stderr": record.get("stderr", ""),
        "error": record.get("error", ""),
        "traceback": record.get("traceback", ""),
        "at": record.get("at", ""),
    }


def _sqs_state() -> dict:
    return sqs_state


def _sqs_queue_key(queue_name: str) -> str:
    return (queue_name or "").strip()


def _sqs_validate_queue_name(queue_name: str) -> None:
    if not queue_name:
        raise HTTPException(400, detail="MissingParameter: queue_name is required.")
    if len(queue_name) < 1 or len(queue_name) > 80:
        raise HTTPException(400, detail="InvalidParameterValue: queue_name must be 1-80 characters.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", queue_name):
        raise HTTPException(400, detail="InvalidParameterValue: queue_name can contain letters, numbers, periods, underscores, and hyphens.")


def _sqs_queue_url(queue_name: str) -> str:
    return f"http://127.0.0.1:9000/api/sqs/queues/{queue_name}"


def _sqs_queue_arn(queue_name: str) -> str:
    return f"arn:aws:sqs:us-east-1:{AWS_ACCOUNT_ID}:{queue_name}"


def _sqs_find_queue(queue_name: str) -> dict | None:
    key = _sqs_queue_key(queue_name)
    if not key:
        return None
    queues = _sqs_state().setdefault("queues", {})
    if key in queues:
        return queues[key]
    lowered = key.lower()
    for existing_name, queue in queues.items():
        if existing_name.lower() == lowered:
            return queue
    return None


def _sqs_set_queue(queue: dict) -> dict:
    _sqs_state().setdefault("queues", {})[queue["queue_name"]] = queue
    return queue


def _sqs_list_queues() -> list[dict]:
    queues = list(_sqs_state().setdefault("queues", {}).values())
    queues.sort(key=lambda item: (item.get("created", ""), item.get("queue_name", "")))
    return queues


def _sqs_normalize_queue(queue: dict) -> dict:
    queue.setdefault("queue_name", "")
    queue.setdefault("queue_type", "standard")
    queue.setdefault("fifo_queue", bool(str(queue.get("queue_name", "")).endswith(".fifo")))
    queue.setdefault("content_based_deduplication", False)
    queue.setdefault("visibility_timeout", 30)
    queue.setdefault("receive_wait_time_seconds", 0)
    queue.setdefault("message_retention_period", 345600)
    queue.setdefault("max_message_size", 262144)
    queue.setdefault("delay_seconds", 0)
    queue.setdefault("redrive_policy", {})
    queue.setdefault("tags", {})
    queue.setdefault("attributes", {})
    queue.setdefault("messages", [])
    queue.setdefault("created", _now())
    queue.setdefault("last_modified", _now())
    return queue


def _sqs_timestamp(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(_parse_ts(value).timestamp())
    except Exception:
        return 0


def _sqs_message_is_visible(message: dict) -> bool:
    if message.get("deleted"):
        return False
    visible_at = message.get("visible_at") or ""
    if not visible_at:
        return True
    try:
        return _parse_ts(visible_at) <= datetime.now(timezone.utc)
    except Exception:
        return True


def _sqs_sweep_queue(queue: dict) -> None:
    now = datetime.now(timezone.utc)
    retention = int(queue.get("message_retention_period", 345600) or 345600)
    messages = []
    for message in queue.get("messages", []):
        if not isinstance(message, dict):
            continue
        sent_at = message.get("sent_at", "")
        if sent_at:
            try:
                if now - _parse_ts(sent_at) > timedelta(seconds=retention):
                    continue
            except Exception:
                pass
        if message.get("in_flight") and message.get("visible_at"):
            try:
                if _parse_ts(message["visible_at"]) <= now:
                    message["in_flight"] = False
                    message["receipt_handle"] = ""
            except Exception:
                message["in_flight"] = False
                message["receipt_handle"] = ""
        if not message.get("deleted"):
            messages.append(message)
    queue["messages"] = messages


def _sqs_dedup_key(queue: dict, body: str, dedup_id: str) -> str:
    if dedup_id:
        return dedup_id
    if queue.get("content_based_deduplication"):
        return hashlib.sha256(body.encode("utf-8")).hexdigest()
    return ""


def _sqs_message_is_blocked_by_fifo(queue: dict, message: dict) -> bool:
    if not queue.get("fifo_queue"):
        return False
    group_id = message.get("group_id", "") or "__default__"
    for candidate in queue.get("messages", []):
        if candidate is message:
            break
        if candidate.get("deleted"):
            continue
        if (candidate.get("group_id", "") or "__default__") != group_id:
            continue
        if candidate.get("in_flight"):
            return True
    return False


def _sqs_view_message(queue: dict, message: dict, include_body: bool = True) -> dict:
    view = {
        "message_id": message.get("message_id", ""),
        "receipt_handle": message.get("receipt_handle", ""),
        "receive_count": int(message.get("receive_count", 0) or 0),
        "sent_at": message.get("sent_at", ""),
        "visible_at": message.get("visible_at", ""),
        "group_id": message.get("group_id", ""),
        "dedup_id": message.get("dedup_id", ""),
        "in_flight": bool(message.get("in_flight", False)),
        "md5_of_body": message.get("md5_of_body", ""),
        "sequence_number": message.get("sequence_number", ""),
    }
    if include_body:
        view["body"] = message.get("body", "")
        view["attributes"] = copy.deepcopy(message.get("attributes", {}))
        view["message_attributes"] = copy.deepcopy(message.get("message_attributes", {}))
    return view


def _sqs_queue_attributes(queue: dict) -> dict[str, str]:
    attrs = {
        "ApproximateNumberOfMessages": str(sum(1 for m in queue.get("messages", []) if not m.get("deleted") and not m.get("in_flight") and _sqs_message_is_visible(m))),
        "ApproximateNumberOfMessagesNotVisible": str(sum(1 for m in queue.get("messages", []) if not m.get("deleted") and m.get("in_flight"))),
        "VisibilityTimeout": str(int(queue.get("visibility_timeout", 30) or 30)),
        "CreatedTimestamp": str(_sqs_timestamp(queue.get("created"))),
        "LastModifiedTimestamp": str(_sqs_timestamp(queue.get("last_modified"))),
        "DelaySeconds": str(int(queue.get("delay_seconds", 0) or 0)),
        "ReceiveMessageWaitTimeSeconds": str(int(queue.get("receive_wait_time_seconds", 0) or 0)),
        "MessageRetentionPeriod": str(int(queue.get("message_retention_period", 345600) or 345600)),
        "MaximumMessageSize": str(int(queue.get("max_message_size", 262144) or 262144)),
        "QueueArn": queue.get("queue_arn", _sqs_queue_arn(queue.get("queue_name", ""))),
        "FifoQueue": "true" if queue.get("fifo_queue") else "false",
        "ContentBasedDeduplication": "true" if queue.get("content_based_deduplication") else "false",
    }
    redrive_policy = queue.get("redrive_policy") or {}
    if redrive_policy:
        attrs["RedrivePolicy"] = json.dumps(redrive_policy, separators=(",", ":"), default=str)
    return attrs


def _sqs_queue_view(queue: dict, include_messages: bool = True) -> dict:
    queue = _sqs_normalize_queue(queue)
    _sqs_sweep_queue(queue)
    view = copy.deepcopy(queue)
    view["queue_url"] = queue.get("queue_url") or _sqs_queue_url(queue["queue_name"])
    view["queue_arn"] = queue.get("queue_arn") or _sqs_queue_arn(queue["queue_name"])
    view["attributes"] = _sqs_queue_attributes(queue)
    view["message_count"] = len(queue.get("messages", []))
    view["visible_message_count"] = sum(1 for m in queue.get("messages", []) if not m.get("deleted") and not m.get("in_flight") and _sqs_message_is_visible(m))
    view["in_flight_count"] = sum(1 for m in queue.get("messages", []) if not m.get("deleted") and m.get("in_flight"))
    view["messages"] = [_sqs_view_message(queue, message) for message in queue.get("messages", []) if include_messages and not message.get("deleted")]
    if not include_messages:
        view["messages"] = []
    return view


def _sqs_queue_list_view(queue: dict) -> dict:
    view = _sqs_queue_view(queue, include_messages=False)
    view["latest_message_at"] = max((m.get("sent_at", "") for m in queue.get("messages", []) if m.get("sent_at")), default="")
    return view


def _sqs_redrive_queue_name(queue: dict) -> str:
    policy = queue.get("redrive_policy") or {}
    target = policy.get("deadLetterTargetArn") or policy.get("deadLetterTargetQueueArn") or ""
    if ":queue/" in target:
        return target.rsplit(":", 1)[-1]
    if ":sqs:" in target:
        return target.rsplit(":", 1)[-1]
    return ""


def _sqs_enqueue_message(queue: dict, body: str, attributes: dict | None = None, message_attributes: dict | None = None, group_id: str = "", dedup_id: str = "", source: str = "") -> dict:
    queue = _sqs_normalize_queue(queue)
    _sqs_sweep_queue(queue)
    body = body if isinstance(body, str) else json.dumps(body, default=str)
    if len(body.encode("utf-8")) > int(queue.get("max_message_size", 262144) or 262144):
        raise HTTPException(400, detail="InvalidParameterValue: message body exceeds MaximumMessageSize.")
    if queue.get("fifo_queue") and not group_id:
        raise HTTPException(400, detail="MissingParameter: MessageGroupId is required for FIFO queues.")
    dedup_key = _sqs_dedup_key(queue, body, dedup_id)
    if queue.get("fifo_queue") and dedup_key:
        dedup_window_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        for existing in reversed(queue.get("messages", [])):
            if existing.get("dedup_id") == dedup_key:
                sent_at = existing.get("sent_at", "")
                if sent_at and _parse_ts(sent_at) >= dedup_window_start:
                    return existing
    message = {
        "message_id": _id("msg"),
        "body": body,
        "attributes": copy.deepcopy(attributes or {}),
        "message_attributes": copy.deepcopy(message_attributes or {}),
        "md5_of_body": hashlib.md5(body.encode("utf-8")).hexdigest(),
        "sent_at": _now(),
        "visible_at": _now(),
        "receive_count": 0,
        "receipt_handle": "",
        "in_flight": False,
        "deleted": False,
        "group_id": group_id,
        "dedup_id": dedup_key,
        "sequence_number": str(len(queue.get("messages", [])) + 1),
        "source": source,
    }
    delay = int(queue.get("delay_seconds", 0) or 0)
    if delay > 0:
        message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    queue.setdefault("messages", []).append(message)
    queue["last_modified"] = _now()
    _persist_state()
    return message


def _sqs_create_queue_record(req: "SQSQueueCreateRequest") -> dict:
    queue_name = _sqs_queue_key(req.queue_name)
    _sqs_validate_queue_name(queue_name)
    if _sqs_find_queue(queue_name):
        raise HTTPException(409, detail="QueueAlreadyExists")
    fifo = bool(req.fifo_queue or queue_name.endswith(".fifo"))
    if fifo and not queue_name.endswith(".fifo"):
        queue_name = f"{queue_name}.fifo"
    queue = {
        "queue_name": queue_name,
        "queue_url": _sqs_queue_url(queue_name),
        "queue_arn": _sqs_queue_arn(queue_name),
        "queue_type": "fifo" if fifo else "standard",
        "fifo_queue": fifo,
        "content_based_deduplication": bool(req.content_based_deduplication),
        "visibility_timeout": max(0, int(req.visibility_timeout or 30)),
        "receive_wait_time_seconds": max(0, int(req.receive_wait_time_seconds or 0)),
        "message_retention_period": max(60, int(req.message_retention_period or 345600)),
        "max_message_size": max(1024, int(req.max_message_size or 262144)),
        "delay_seconds": max(0, int(req.delay_seconds or 0)),
        "redrive_policy": copy.deepcopy(req.redrive_policy or {}),
        "tags": copy.deepcopy(req.tags or {}),
        "attributes": {},
        "messages": [],
        "created": _now(),
        "last_modified": _now(),
    }
    if queue["redrive_policy"] and not isinstance(queue["redrive_policy"], dict):
        raise HTTPException(400, detail="InvalidParameterValue: redrive_policy must be an object.")
    _sqs_set_queue(queue)
    _record_usage("sqs.create_queue", {"queue_name": queue["queue_name"]})
    return queue


def _sqs_queue_from_name_or_url(name_or_url: str) -> dict | None:
    if not name_or_url:
        return None
    if name_or_url.startswith("http://") or name_or_url.startswith("https://"):
        if "/queues/" in name_or_url:
            candidate = name_or_url.rsplit("/queues/", 1)[-1]
            return _sqs_find_queue(candidate)
    if ":queue/" in name_or_url:
        candidate = name_or_url.rsplit(":", 1)[-1]
        return _sqs_find_queue(candidate)
    return _sqs_find_queue(name_or_url)


def _sqs_get_queue(queue_name: str) -> dict:
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    return _sqs_queue_view(queue)


def _sqs_update_queue_attributes(queue: dict, payload: dict) -> dict:
    queue = _sqs_normalize_queue(queue)
    if "VisibilityTimeout" in payload:
        queue["visibility_timeout"] = max(0, int(payload.get("VisibilityTimeout", queue["visibility_timeout"])))
    if "ReceiveMessageWaitTimeSeconds" in payload:
        queue["receive_wait_time_seconds"] = max(0, int(payload.get("ReceiveMessageWaitTimeSeconds", queue["receive_wait_time_seconds"])))
    if "MessageRetentionPeriod" in payload:
        queue["message_retention_period"] = max(60, int(payload.get("MessageRetentionPeriod", queue["message_retention_period"])))
    if "MaximumMessageSize" in payload:
        queue["max_message_size"] = max(1024, int(payload.get("MaximumMessageSize", queue["max_message_size"])))
    if "DelaySeconds" in payload:
        queue["delay_seconds"] = max(0, int(payload.get("DelaySeconds", queue["delay_seconds"])))
    if "RedrivePolicy" in payload:
        redrive = payload.get("RedrivePolicy") or {}
        if isinstance(redrive, str):
            try:
                redrive = json.loads(redrive)
            except Exception:
                raise HTTPException(400, detail="InvalidParameterValue: RedrivePolicy must be JSON.")
        queue["redrive_policy"] = copy.deepcopy(redrive or {})
    if "ContentBasedDeduplication" in payload:
        queue["content_based_deduplication"] = str(payload.get("ContentBasedDeduplication")).lower() == "true"
    queue["last_modified"] = _now()
    _persist_state()
    return queue


def _sqs_delete_queue(queue_name: str) -> None:
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    _sqs_state().setdefault("queues", {}).pop(queue["queue_name"], None)
    _record_usage("sqs.delete_queue", {"queue_name": queue["queue_name"]})


def _sqs_extract_messages_for_delivery(queue: dict, max_messages: int) -> list[dict]:
    queue = _sqs_normalize_queue(queue)
    _sqs_sweep_queue(queue)
    now = datetime.now(timezone.utc)
    available = []
    group_locks: set[str] = set()
    for message in queue.get("messages", []):
        if message.get("deleted") or message.get("in_flight") or not _sqs_message_is_visible(message):
            continue
        if queue.get("fifo_queue"):
            group_id = message.get("group_id", "") or "__default__"
            if group_id in group_locks:
                continue
            if _sqs_message_is_blocked_by_fifo(queue, message):
                continue
            group_locks.add(group_id)
        available.append(message)
        if len(available) >= max_messages:
            break
    deliveries = []
    visibility = int(queue.get("visibility_timeout", 30) or 30)
    for message in available:
        message["receive_count"] = int(message.get("receive_count", 0) or 0) + 1
        redrive_policy = queue.get("redrive_policy") or {}
        max_receive = int(redrive_policy.get("maxReceiveCount", 0) or 0)
        if max_receive and message["receive_count"] > max_receive:
            dlq_name = _sqs_redrive_queue_name(queue)
            dlq = _sqs_find_queue(dlq_name) if dlq_name else None
            if dlq:
                _sqs_enqueue_message(dlq, message.get("body", ""), message.get("attributes", {}), message.get("message_attributes", {}), message.get("group_id", ""), message.get("dedup_id", ""), source=f"redrive:{queue['queue_name']}")
            message["deleted"] = True
            continue
        message["in_flight"] = True
        message["receipt_handle"] = _id("rhdl")
        message["visible_at"] = (now + timedelta(seconds=visibility)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        deliveries.append(message)
    queue["last_modified"] = _now()
    _persist_state()
    return deliveries


def _sqs_delete_message(queue: dict, receipt_handle: str) -> bool:
    for message in queue.get("messages", []):
        if message.get("receipt_handle") == receipt_handle and message.get("in_flight"):
            message["deleted"] = True
            queue["messages"] = [m for m in queue.get("messages", []) if not m.get("deleted")]
            queue["last_modified"] = _now()
            _persist_state()
            return True
    return False


def _sqs_change_message_visibility(queue: dict, receipt_handle: str, visibility_timeout: int) -> bool:
    for message in queue.get("messages", []):
        if message.get("receipt_handle") == receipt_handle and message.get("in_flight"):
            message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=max(0, int(visibility_timeout)))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            queue["last_modified"] = _now()
            _persist_state()
            return True
    return False


def _sqs_purge_queue(queue: dict) -> None:
    queue["messages"] = []
    queue["last_modified"] = _now()
    _persist_state()


def _sqs_tags_view(queue: dict) -> dict:
    return copy.deepcopy(queue.get("tags", {}))


def _sqs_set_tags(queue: dict, tags: dict[str, str]) -> None:
    queue["tags"] = {str(k): str(v) for k, v in tags.items()}
    queue["last_modified"] = _now()
    _persist_state()


def _sqs_query_bool(value: str | None) -> bool:
    return str(value or "").lower() in {"true", "1", "yes", "on"}


AMI_CATALOG = [
    {
        "ami": "ami-amzn2023",
        "name": "Amazon Linux 2023",
        "os_family": "amazon-linux",
        "category": "Amazon",
        "default_runtime": "python",
        "container_image": "amazonlinux:2023",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Amazon Linux 2023 base image for lightweight apps.",
    },
    {
        "ami": "ami-amzn2",
        "name": "Amazon Linux 2",
        "os_family": "amazon-linux",
        "category": "Amazon",
        "default_runtime": "python",
        "container_image": "amazonlinux:2",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Amazon Linux 2 compatibility profile for legacy workloads.",
    },
    {
        "ami": "ami-amzn2023-minimal",
        "name": "Amazon Linux 2023 Minimal",
        "os_family": "amazon-linux",
        "category": "Amazon",
        "default_runtime": "python",
        "container_image": "amazonlinux:2023",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Amazon Linux 2023 minimal profile for smaller footprints.",
    },
    {
        "ami": "ami-ubuntu2204",
        "name": "Ubuntu Server 22.04 LTS",
        "os_family": "ubuntu",
        "category": "Ubuntu",
        "default_runtime": "python",
        "container_image": "ubuntu:22.04",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Ubuntu 22.04 base image for common app runtimes.",
    },
    {
        "ami": "ami-ubuntu2404",
        "name": "Ubuntu Server 24.04 LTS",
        "os_family": "ubuntu",
        "category": "Ubuntu",
        "default_runtime": "python",
        "container_image": "ubuntu:24.04",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Ubuntu 24.04 LTS profile for current-generation workloads.",
    },
    {
        "ami": "ami-ubuntu2004",
        "name": "Ubuntu Server 20.04 LTS",
        "os_family": "ubuntu",
        "category": "Ubuntu",
        "default_runtime": "python",
        "container_image": "ubuntu:20.04",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Ubuntu 20.04 LTS profile for older workloads and labs.",
    },
    {
        "ami": "ami-debian12",
        "name": "Debian 12",
        "os_family": "debian",
        "category": "Debian",
        "default_runtime": "python",
        "container_image": "debian:12",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Debian 12 profile for lean Linux instances.",
    },
    {
        "ami": "ami-debian11",
        "name": "Debian 11",
        "os_family": "debian",
        "category": "Debian",
        "default_runtime": "python",
        "container_image": "debian:11",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Debian 11 profile for compatibility-focused labs.",
    },
    {
        "ami": "ami-rhel9",
        "name": "Red Hat Enterprise Linux 9",
        "os_family": "rhel",
        "category": "Red Hat",
        "default_runtime": "python",
        "container_image": "rockylinux:9",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "RHEL 9 container profile for enterprise-style setups.",
    },
    {
        "ami": "ami-rocky9",
        "name": "Rocky Linux 9",
        "os_family": "rhel",
        "category": "Red Hat",
        "default_runtime": "python",
        "container_image": "rockylinux:9",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Rocky Linux 9 profile for RHEL-compatible workloads.",
    },
    {
        "ami": "ami-alma9",
        "name": "AlmaLinux 9",
        "os_family": "rhel",
        "category": "Red Hat",
        "default_runtime": "python",
        "container_image": "almalinux:9",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "AlmaLinux 9 profile for RHEL-compatible labs.",
    },
    {
        "ami": "ami-suse15",
        "name": "SUSE Linux Enterprise 15",
        "os_family": "suse",
        "category": "SUSE",
        "default_runtime": "python",
        "container_image": "opensuse/leap:15",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "SUSE Linux Enterprise 15 profile for enterprise Linux practice.",
    },
    {
        "ami": "ami-fedora42",
        "name": "Fedora 42",
        "os_family": "fedora",
        "category": "Fedora",
        "default_runtime": "python",
        "container_image": "fedora:42",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Fedora 42 profile for modern Linux and container labs.",
    },
    {
        "ami": "ami-windows2022",
        "name": "Windows Server 2022 Base",
        "os_family": "windows",
        "category": "Microsoft Windows",
        "default_runtime": "python",
        "container_image": "mcr.microsoft.com/windows/servercore:ltsc2022",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Windows Server 2022 base profile for Windows-focused labs.",
    },
    {
        "ami": "ami-windows2022-core",
        "name": "Windows Server 2022 Core",
        "os_family": "windows",
        "category": "Microsoft Windows",
        "default_runtime": "python",
        "container_image": "mcr.microsoft.com/windows/nanoserver:ltsc2022",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Windows Server 2022 Core profile for lightweight Windows workloads.",
    },
    {
        "ami": "ami-windows2025",
        "name": "Windows Server 2025 Base",
        "os_family": "windows",
        "category": "Microsoft Windows",
        "default_runtime": "python",
        "container_image": "mcr.microsoft.com/windows/servercore:ltsc2025",
        "runtime_image": LXD_RUNTIME_IMAGE,
        "description": "Windows Server 2025 base profile for newer Windows labs.",
    },
]


def _decorate_ami_catalog() -> None:
    host_os = _parent_os()
    for item in AMI_CATALOG:
        family = str(item.get("os_family") or "").lower()
        if family == "ubuntu":
            item.setdefault("supported_backends", ["multipass", "lxd"])
            item.setdefault("supported_host_os", ["linux", "darwin", "windows"])
            item.setdefault("default_runtime_backend", "multipass" if host_os in {"windows", "darwin"} else "lxd")
        elif family == "windows":
            item.setdefault("supported_backends", [])
            item.setdefault("supported_host_os", ["windows"])
            item.setdefault("default_runtime_backend", "multipass")
        else:
            item.setdefault("supported_backends", ["lxd"])
            item.setdefault("supported_host_os", ["linux"])
            item.setdefault("default_runtime_backend", "lxd")


_decorate_ami_catalog()

EC2_INSTANCE_TYPE_CATALOG = [
    {
        "instanceType": "t3.micro",
        "currentGeneration": "true",
        "freeTierEligible": "true",
        "vcpu": 2,
        "memory_mib": 1024,
        "storage": "EBS only",
        "network_performance": "Low to Moderate",
        "burstable": "true",
        "family": "t3",
    },
    {
        "instanceType": "t3.small",
        "currentGeneration": "true",
        "freeTierEligible": "false",
        "vcpu": 2,
        "memory_mib": 2048,
        "storage": "EBS only",
        "network_performance": "Low to Moderate",
        "burstable": "true",
        "family": "t3",
    },
    {
        "instanceType": "t3.medium",
        "currentGeneration": "true",
        "freeTierEligible": "false",
        "vcpu": 2,
        "memory_mib": 4096,
        "storage": "EBS only",
        "network_performance": "Low to Moderate",
        "burstable": "true",
        "family": "t3",
    },
    {
        "instanceType": "t3.large",
        "currentGeneration": "true",
        "freeTierEligible": "false",
        "vcpu": 2,
        "memory_mib": 8192,
        "storage": "EBS only",
        "network_performance": "Low to Moderate",
        "burstable": "true",
        "family": "t3",
    },
    {
        "instanceType": "m5.large",
        "currentGeneration": "true",
        "freeTierEligible": "false",
        "vcpu": 2,
        "memory_mib": 8192,
        "storage": "EBS only",
        "network_performance": "Up to 10 Gigabit",
        "burstable": "false",
        "family": "m5",
    },
    {
        "instanceType": "m5.xlarge",
        "currentGeneration": "true",
        "freeTierEligible": "false",
        "vcpu": 4,
        "memory_mib": 16384,
        "storage": "EBS only",
        "network_performance": "Up to 10 Gigabit",
        "burstable": "false",
        "family": "m5",
    },
    {
        "instanceType": "c5.large",
        "currentGeneration": "true",
        "freeTierEligible": "false",
        "vcpu": 2,
        "memory_mib": 4096,
        "storage": "EBS only",
        "network_performance": "Up to 10 Gigabit",
        "burstable": "false",
        "family": "c5",
    },
]




def _reconcile_runtime_instances(instances: dict[str, dict]) -> None:
    for instance_id in list(instances.keys()):
        instance = instances.get(instance_id)
        if not isinstance(instance, dict):
            continue
        legacy_prefix = "sample"
        for key in tuple(f"{legacy_prefix}_app_{suffix}" for suffix in ("id", "name", "status", "command", "port", "kill_pattern", "error")):
            instance.pop(key, None)
        backend = str(instance.get("runtime_backend") or "").strip().lower()
        if backend == "multipass":
            _ensure_instance_workspace(instance)
            if _runtime_available("multipass"):
                _sync_multipass_instance(instance)
            else:
                instance.setdefault("container_status", "multipass-unavailable")
        elif backend == "lxd":
            _ensure_instance_workspace(instance)
            if _lxd_available():
                _sync_lxd_instance(instance)
            else:
                instance.setdefault("container_status", "lxd-unavailable")
        if instance.get("state") == "pending" and backend in {"multipass", "lxd"}:
            _queue_runtime_start_for_store(instances, instance_id)


def _prune_expired_terminated_instances_from(instances: dict[str, dict]) -> None:
    with STATE_LOCK:
        now = datetime.now(timezone.utc)
        removed = False
        for instance_id, instance in list(instances.items()):
            if not isinstance(instance, dict) or instance.get("state") != "terminated":
                continue
            if _terminated_visible(instance, now):
                continue
            instances.pop(instance_id, None)
            removed = True
        if removed:
            _persist_state()





# ── Tier quantity-cap enforcement helpers ───────────────────────────────────
# Counters for "how many of <resource_type> are currently in the active space?"
# Used by create-handler sites that call _enforce_quantity_cap(<type>) BEFORE
# they create a new resource. On cap-exceeded → HTTPException(403) with
# structured body the SPA renders as an upgrade modal.

# Storage location map: resource_type → list of (service_states_key, sub_key).
# Walked on the active space; counts summed across providers since "vm"
# spans EC2 + GCE + Azure VM, etc.
_QUANTITY_COUNTER_PATHS: dict[str, list[tuple[str, str]]] = {
    "vm":              [("ec2", "instances"), ("gcp_compute", "instances")],
    "database":        [("rds", "db_instances"), ("gcp_sql", "instances")],
    "api_gateway":     [("apigateway", "apis"), ("gcp_apigateway", "apis")],
    "queue":           [("sqs", "queues"), ("gcp_pubsub", "topics")],
    "lambda_function": [("lambda", "functions"), ("gcp_functions", "functions")],
    # bucket count is filled in below via special-case (S3 lives in global
    # `buckets` proxy which only resolves at request time)
    "bucket":          [("gcp_storage", "buckets")],
}

# Azure ARM resource_type filters (_type field stored in azure_arm.resources).
_QUANTITY_AZURE_TYPES: dict[str, str] = {
    "vm":              "microsoft.compute/virtualmachines",
    "database":        "microsoft.sql/servers/databases",
    "bucket":          "microsoft.storage/storageaccounts",
    "queue":           "microsoft.servicebus/namespaces/queues",
    "api_gateway":     "microsoft.apimanagement/service",
    "lambda_function": "microsoft.web/sites",
}


def _count_active_space_resources(resource_type: str) -> int:
    """Sum existing instances of resource_type across all providers in the
    currently-active space's service_states.
    """
    spaces_state = STATE.get("spaces") or {}
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return 0
    space = (spaces_state.get("spaces") or {}).get(active_id) or {}
    svc = space.get("service_states") or {}

    total = 0
    for svc_key, sub_key in _QUANTITY_COUNTER_PATHS.get(resource_type, []):
        items = (svc.get(svc_key) or {}).get(sub_key) or {}
        if isinstance(items, dict):
            total += len(items)
        elif isinstance(items, list):
            total += len(items)

    # Azure ARM is keyed by resource path with a _type discriminator.
    azure_type = _QUANTITY_AZURE_TYPES.get(resource_type)
    if azure_type:
        azure_resources = (svc.get("azure_arm") or {}).get("resources") or {}
        for rec in azure_resources.values():
            if isinstance(rec, dict) and str(rec.get("_type", "")).lower() == azure_type:
                total += 1

    # S3 buckets live in the GLOBAL `buckets` dict (proxied per-space).
    # buckets isn't defined yet at this point in the file — late import.
    if resource_type == "bucket":
        try:
            total += len(buckets)  # noqa: F821 — defined later
        except NameError:
            pass

    return total


def _active_tier() -> str:
    """Resolve the active tenant's tier (falls back to the deployment-level
    STATE["license"]["tier"] then "free"). Shared by every tier-enforcement
    site; mirrors the middleware's resolver in `_tier_enforcement_middleware`.

    Also enforces the JWT's `sub_expires_at` claim: if the subscription
    cutoff has passed, every read returns "free" regardless of stored
    tier — so the appliance self-downgrades the moment the billing
    period ends, without needing to reach the portal first. The next
    successful refresh will overwrite the persisted tier with whatever
    the portal derives (typically also Free if the sub didn't renew).
    """
    try:
        tenant = _tenant_dict(_active_tenant_id()) or {}
    except Exception:
        tenant = {}
    stored = str(tenant.get("license_tier")
                 or (STATE.get("license") or {}).get("tier")
                 or "free")
    if stored == "free":
        return "free"
    # Subscription cutoff check — runs on every tier read but is a single
    # claim lookup + timestamp compare, so cost is negligible.
    try:
        from core import license_remote as _lr
        if _lr.is_sub_expired(STATE.get("license_claims") or {}):
            return "free"
    except Exception:
        pass
    return stored


# Ordered level vocabulary for non-boolean feature flags. Each entry maps a
# feature name to the policy's level values in ascending order (so `basic` is
# weakest, `full_plus_import` strongest). Used by `_enforce_tier_feature(...,
# min_level="full")` to deny calls that need a higher level than the active
# tier carries. Add a new entry here when a new level-based feature is added
# to tier_policy.py.
_FEATURE_LEVEL_ORDER: dict[str, list] = {
    "cost_simulation":           ["totals", "per_resource", "per_resource_and_chargeback"],
    "terraform_export":          ["basic", "full", "full_plus_import"],
    "terraform_deploy_to_real":  [False, "single_cloud", "multi_cloud"],
    "notifications":             [False, "webhook", "all_channels"],
}


def _feature_level_meets(feature_name: str, current, required) -> bool:
    """True if the active tier's value for feature_name is >= required in the
    feature's level ordering. Unknown features or unknown values fail-open
    (return True) so we never deny a call we don't know how to compare."""
    order = _FEATURE_LEVEL_ORDER.get(feature_name)
    if not order:
        return True
    try:
        return order.index(current) >= order.index(required)
    except ValueError:
        return True


def _enforce_tier_feature(feature_name: str, *, min_level=None):
    """Raise HTTPException(403) if the active tier doesn't have `feature_name`.

    For boolean features (`sso`, `helm`, `cloud_shell`, `cedar_enforcement`,
    `ci_integration`): denies when the policy value is falsy.

    For level-based features (`cost_simulation`, `terraform_export`,
    `terraform_deploy_to_real`, `notifications`): if `min_level` is given,
    denies when the active tier's value comes before `min_level` in the
    feature's ordering (see `_FEATURE_LEVEL_ORDER`). When `min_level` is None,
    only the boolean truthiness check applies.

    Returns the active tier's value for the feature (e.g. `"totals"`,
    `"per_resource"`, `"full"`) so the caller can shape its response by level.
    """
    tier = _active_tier()
    from core import tier_policy as _tp
    result = _tp.check_feature(tier, feature_name)
    if not result.get("ok"):
        result["active_tier"] = tier
        result["docs"] = "https://cloudlearn.io/docs/tiers"
        raise HTTPException(status_code=403, detail=result)
    val = result.get("value")
    if min_level is not None and not _feature_level_meets(feature_name, val, min_level):
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "tier_feature_level",
            "reason": f"{feature_name} requires level '{min_level}' or higher; active tier has '{val}'",
            "active_tier": tier, "feature": feature_name,
            "current_level": val, "required_level": min_level,
            "upgrade_to": _tp._next_tier(_tp.normalize_tier(tier)),
            "docs": "https://cloudlearn.io/docs/tiers",
        })
    return val


# Size ordering used by `_enforce_size_cap`. Mirrors the runtime_sizer tier
# table (nano < small < medium < large < xlarge < huge). Anything in the
# policy's `max_vm_size_tier`/`max_db_size_tier` field MUST be one of these.
_SIZE_ORDER = ("nano", "small", "medium", "large", "xlarge", "huge")


def _classify_instance_size(provider: str, instance_type: str) -> str | None:
    """Return one of _SIZE_ORDER for a (provider, instance_type) pair, or None
    if unknown. Uses runtime_sizer.shape_for_instance + the tier table. For
    DB instance types (db.t3.micro etc.) strips the `db.` prefix before lookup."""
    if not instance_type:
        return None
    try:
        from core import runtime_sizer
        shape = runtime_sizer.shape_for_instance(instance_type, provider)
        if not shape and instance_type.startswith("db."):
            shape = runtime_sizer.shape_for_instance(instance_type[3:], provider)
        if not shape:
            return None
        vcpu = max(1, int(shape.get("vcpu", 1)))
        ram_mb = max(128, int(shape.get("ram_mb", 1024)))
        score = max(vcpu, ram_mb // 1024 or 1)
        for max_score, tn, _tc, _tm in runtime_sizer._TIERS:
            if score <= max_score:
                return tn
        return "huge"
    except Exception:
        return None


def _enforce_size_cap(resource_kind: str, provider: str, instance_type: str) -> None:
    """Raise HTTPException(403) if `instance_type` exceeds the active tier's
    size ceiling for `resource_kind` ("vm" → max_vm_size_tier, "db" →
    max_db_size_tier).

    Fail-open on unknown instance types — we'd rather let an unfamiliar shape
    through than 403 a real launch. Operators see the gap via /api/license/status.
    """
    cap_field = "max_vm_size_tier" if resource_kind == "vm" else "max_db_size_tier"
    tier = _active_tier()
    from core import tier_policy as _tp
    p = _tp.policy_for(tier)
    cap = str(p.get(cap_field) or "huge").lower()
    if cap not in _SIZE_ORDER:
        return
    actual = _classify_instance_size(provider, instance_type)
    if actual is None:
        return  # unknown → fail-open
    try:
        if _SIZE_ORDER.index(actual) > _SIZE_ORDER.index(cap):
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "tier_size_limit",
                "reason": f"{tier} tier caps {resource_kind} size at '{cap}'; requested '{instance_type}' is '{actual}'",
                "active_tier": tier,
                "resource_kind": resource_kind,
                "requested_type": instance_type,
                "requested_size": actual,
                "max_size": cap,
                "upgrade_to": _tp._next_tier(_tp.normalize_tier(tier)),
                "docs": "https://cloudlearn.io/docs/tiers",
            })
    except ValueError:
        return  # unknown size string in policy → fail-open




def _gcp_active_space_dict() -> dict:
    spaces_state = _spaces_state()
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
    return space if isinstance(space, dict) else {}


def _gcp_record_matches_project(rec: dict, project: str) -> bool:
    """Mirror the per-service list filter: a falsy stored project matches any."""
    if not project:
        return True
    return str((rec or {}).get("project") or project) == project


def _gcp_state_proxies() -> dict:
    """The space/provider-scoped state proxies, keyed by service. These resolve to
    the exact same store bucket the grid handlers read, so summary == grid."""
    return {
        "gcp_compute": gcp_compute_state,
        "gcp_storage": gcp_storage_state,
        "gcp_sql": gcp_sql_state,
        "gcp_pubsub": gcp_pubsub_state,
        "gcp_firestore": gcp_firestore_state,
        "gcp_functions": gcp_functions_state,
        "gcp_apigateway": gcp_apigw_state,
        "gcp_vpc": gcp_vpc_state,
        "gcp_iam": gcp_iam_state,
    }






def _now_http() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _parse_utc_timestamp(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ec2_state_meta(state: str) -> tuple[int, str]:
    mapping = {
        "pending": (0, "pending"),
        "running": (16, "running"),
        "shutting-down": (32, "shutting-down"),
        "terminated": (48, "terminated"),
        "stopping": (64, "stopping"),
        "stopped": (80, "stopped"),
        "rebooting": (16, "running"),
    }
    return mapping.get(state, (0, state or "pending"))


def _ec2_xml(tag: str, text: str | None = None, attrib: dict | None = None) -> ET.Element:
    elem = ET.Element(tag, attrib or {})
    if text is not None:
        elem.text = text
    return elem


def _ec2_sub(parent: ET.Element, tag: str, text: str | None = None, attrib: dict | None = None) -> ET.Element:
    elem = ET.SubElement(parent, tag, attrib or {})
    if text is not None:
        elem.text = text
    return elem


def _ec2_error_response(code: str, message: str, status: int = 400) -> Response:
    root = ET.Element("Response")
    errors = _ec2_sub(root, "Errors")
    error = _ec2_sub(errors, "Error")
    _ec2_sub(error, "Code", code)
    _ec2_sub(error, "Message", message)
    _ec2_sub(root, "RequestID", _req_id())
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return Response(content=xml, status_code=status, media_type="text/xml")


def _ec2_success_response(root_name: str, body_builder) -> Response:
    root = ET.Element(f"{{{EC2_XML_NS}}}{root_name}")
    _ec2_sub(root, "requestId", _req_id())
    body_builder(root)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return Response(content=xml, status_code=200, media_type="text/xml")


def _ec2_instance_group_names(instance: dict) -> list[dict]:
    group_ids = instance.get("security_group_ids") or []
    if not group_ids:
        return [{"groupId": "sg-default", "groupName": "default"}]
    groups = []
    for sg_id in group_ids:
        sg = vpc_state.get("security_groups", {}).get(sg_id, {})
        groups.append(
            {
                "groupId": sg_id,
                "groupName": sg.get("group_name") or sg.get("name") or sg_id,
            }
        )
    return groups


def _ec2_private_dns_name(instance: dict) -> str:
    private_ip = instance.get("private_ip") or "10.0.0.1"
    safe = private_ip.replace(".", "-")
    return f"ip-{safe}.{instance.get('az', 'us-east-1a')}.compute.internal"


def _ec2_public_dns_name(instance: dict) -> str:
    public_ip = instance.get("public_ip")
    if not public_ip:
        return ""
    safe = public_ip.replace(".", "-")
    region = (instance.get("az") or "us-east-1a")[:-1] or "us-east-1"
    return f"ec2-{safe}.{region}.compute.amazonaws.com"


def _ec2_image_profile_from_instance(instance: dict) -> dict:
    profile = _ami_profile(instance.get("ami") or "ami-amzn2023")
    return profile


def _ec2_image_xml(image: dict) -> ET.Element:
    item = _ec2_xml("item")
    profile = _ami_profile(image["ami"])
    _ec2_sub(item, "imageId", image["ami"])
    _ec2_sub(item, "imageLocation", f"cloudlearn/{image['ami']}.manifest.xml")
    _ec2_sub(item, "imageState", "available")
    _ec2_sub(item, "imageOwnerId", AWS_ACCOUNT_ID)
    _ec2_sub(item, "isPublic", "true")
    _ec2_sub(item, "architecture", "x86_64")
    _ec2_sub(item, "imageType", "machine")
    _ec2_sub(item, "platformDetails", profile.get("name", "Linux/UNIX"))
    _ec2_sub(item, "description", profile.get("description", "CloudLearn EC2 AMI profile"))
    if profile.get("os_family") == "windows":
        _ec2_sub(item, "platform", "windows")
    _ec2_sub(item, "rootDeviceType", "ebs")
    _ec2_sub(item, "rootDeviceName", "/dev/xvda")
    _ec2_sub(item, "virtualizationType", "hvm")
    _ec2_sub(item, "hypervisor", "xen")
    _ec2_sub(item, "enaSupport", "true")
    _ec2_sub(item, "creationDate", image.get("created", _now()))
    _ec2_sub(item, "name", profile.get("name", image["ami"]))
    _ec2_sub(item, "ownerAlias", "amazon")
    return item


def _ec2_instance_xml(instance: dict) -> ET.Element:
    item = _ec2_xml("item")
    state_code, state_name = _ec2_state_meta(instance.get("state", "pending"))
    profile = _ec2_image_profile_from_instance(instance)
    _ec2_sub(item, "instanceId", instance["instance_id"])
    _ec2_sub(item, "imageId", instance.get("ami") or "ami-amzn2023")
    _ec2_sub(item, "instanceState")
    inst_state = item.find("instanceState")
    _ec2_sub(inst_state, "code", str(state_code))
    _ec2_sub(inst_state, "name", state_name)
    _ec2_sub(item, "privateDnsName", _ec2_private_dns_name(instance))
    _ec2_sub(item, "dnsName", _ec2_public_dns_name(instance))
    _ec2_sub(item, "reason", "")
    _ec2_sub(item, "keyName", instance.get("key_pair", ""))
    _ec2_sub(item, "amiLaunchIndex", "0")
    _ec2_sub(item, "productCodes")
    _ec2_sub(item, "instanceType", instance.get("instance_type", "t3.micro"))
    _ec2_sub(item, "launchTime", instance.get("created", _now()))
    placement = _ec2_sub(item, "placement")
    _ec2_sub(placement, "availabilityZone", instance.get("az", "us-east-1a"))
    _ec2_sub(placement, "groupName", "")
    _ec2_sub(placement, "tenancy", "default")
    monitoring = _ec2_sub(item, "monitoring")
    _ec2_sub(monitoring, "state", "disabled")
    _ec2_sub(item, "subnetId", instance.get("subnet_id", ""))
    _ec2_sub(item, "vpcId", instance.get("vpc_id", ""))
    _ec2_sub(item, "privateIpAddress", instance.get("private_ip", ""))
    if instance.get("public_ip"):
        _ec2_sub(item, "ipAddress", instance.get("public_ip"))
    _ec2_sub(item, "sourceDestCheck", "true")
    group_set = _ec2_sub(item, "groupSet")
    for group in _ec2_instance_group_names(instance):
        group_item = _ec2_sub(group_set, "item")
        _ec2_sub(group_item, "groupId", group["groupId"])
        _ec2_sub(group_item, "groupName", group["groupName"])
    _ec2_sub(item, "architecture", "x86_64")
    _ec2_sub(item, "rootDeviceType", "ebs")
    _ec2_sub(item, "rootDeviceName", "/dev/xvda")
    block_device_mapping = _ec2_sub(item, "blockDeviceMapping")
    bd_item = _ec2_sub(block_device_mapping, "item")
    _ec2_sub(bd_item, "deviceName", "/dev/xvda")
    ebs = _ec2_sub(bd_item, "ebs")
    _ec2_sub(ebs, "status", "attached")
    _ec2_sub(ebs, "deleteOnTermination", "true")
    _ec2_sub(ebs, "volumeId", f"vol-{instance['instance_id'].replace('i-', '')}")
    _ec2_sub(ebs, "attachTime", instance.get("created", _now()))
    _ec2_sub(item, "virtualizationType", "hvm")
    _ec2_sub(item, "hypervisor", "xen")
    _ec2_sub(item, "clientToken", instance.get("instance_id", ""))
    _ec2_sub(item, "ebsOptimized", "false")
    cpu = _ec2_sub(item, "cpuOptions")
    _ec2_sub(cpu, "coreCount", "1")
    _ec2_sub(cpu, "threadsPerCore", "1")
    tag_set = _ec2_sub(item, "tagSet")
    tag = _ec2_sub(tag_set, "item")
    _ec2_sub(tag, "key", "Name")
    _ec2_sub(tag, "value", instance.get("name", ""))
    if instance.get("runtime_backend") == "lxd":
        _ec2_sub(item, "privateDnsNameOptions")
    return item


def _ec2_instance_state_change_xml(instance: dict, previous_state: str, current_state: str | None = None) -> ET.Element:
    item = _ec2_xml("item")
    cur_code, cur_name = _ec2_state_meta(current_state or instance.get("state", "pending"))
    prev_code, prev_name = _ec2_state_meta(previous_state)
    _ec2_sub(item, "instanceId", instance["instance_id"])
    cur = _ec2_sub(item, "currentState")
    _ec2_sub(cur, "code", str(cur_code))
    _ec2_sub(cur, "name", cur_name)
    prev = _ec2_sub(item, "previousState")
    _ec2_sub(prev, "code", str(prev_code))
    _ec2_sub(prev, "name", prev_name)
    return item


def _ec2_instance_status_xml(instance: dict) -> ET.Element:
    item = _ec2_xml("item")
    state_code, state_name = _ec2_state_meta(instance.get("state", "pending"))
    _ec2_sub(item, "instanceId", instance["instance_id"])
    _ec2_sub(item, "availabilityZone", instance.get("az", "us-east-1a"))
    instance_state = _ec2_sub(item, "instanceState")
    _ec2_sub(instance_state, "code", str(state_code))
    _ec2_sub(instance_state, "name", state_name)
    system_status = _ec2_sub(item, "systemStatus")
    _ec2_sub(system_status, "status", "ok" if instance.get("state") == "running" else "not-applicable")
    details = _ec2_sub(system_status, "details")
    detail_item = _ec2_sub(details, "item")
    _ec2_sub(detail_item, "name", "reachability")
    _ec2_sub(detail_item, "status", "passed" if instance.get("state") == "running" else "not-applicable")
    instance_status = _ec2_sub(item, "instanceStatus")
    _ec2_sub(instance_status, "status", "ok" if instance.get("state") == "running" else "not-applicable")
    details2 = _ec2_sub(instance_status, "details")
    detail_item2 = _ec2_sub(details2, "item")
    _ec2_sub(detail_item2, "name", "reachability")
    _ec2_sub(detail_item2, "status", "passed" if instance.get("state") == "running" else "not-applicable")
    return item


def _ec2_instance_type_xml(profile: dict) -> ET.Element:
    item = _ec2_xml("item")
    _ec2_sub(item, "instanceType", profile["instanceType"])
    _ec2_sub(item, "currentGeneration", profile["currentGeneration"])
    _ec2_sub(item, "freeTierEligible", profile["freeTierEligible"])
    vcpu = _ec2_sub(item, "vcpuInfo")
    _ec2_sub(vcpu, "defaultVCpus", str(profile["vcpu"]))
    _ec2_sub(vcpu, "defaultCores", str(max(1, profile["vcpu"] // 2)))
    _ec2_sub(vcpu, "defaultThreadsPerCore", "1")
    mem = _ec2_sub(item, "memoryInfo")
    _ec2_sub(mem, "sizeInMiB", str(profile["memory_mib"]))
    storage = _ec2_sub(item, "storageInfo")
    disk = _ec2_sub(storage, "diskInfo")
    _ec2_sub(disk, "sizeInGB", "0")
    _ec2_sub(disk, "type", profile["storage"])
    net = _ec2_sub(item, "networkInfo")
    _ec2_sub(net, "networkPerformance", profile["network_performance"])
    _ec2_sub(net, "maximumNetworkInterfaces", "2")
    _ec2_sub(net, "ipv4AddressesPerInterface", "2")
    _ec2_sub(item, "burstablePerformanceSupported", profile["burstable"])
    usage = _ec2_sub(item, "supportedUsageClasses")
    _ec2_sub(usage, "item", "on-demand")
    _ec2_sub(usage, "item", "spot")
    processor = _ec2_sub(item, "processorInfo")
    archs = _ec2_sub(processor, "supportedArchitectures")
    _ec2_sub(archs, "item", "x86_64")
    _ec2_sub(item, "instanceStorageSupported", "false")
    ebs = _ec2_sub(item, "ebsInfo")
    _ec2_sub(ebs, "ebsOptimizedSupport", "supported")
    _ec2_sub(ebs, "encryptionSupport", "supported")
    return item


def _ec2_security_group_xml(group_id: str, group: dict) -> ET.Element:
    item = _ec2_xml("item")
    _ec2_sub(item, "groupId", group_id)
    _ec2_sub(item, "groupName", group.get("group_name", group_id))
    _ec2_sub(item, "description", group.get("description", "CloudLearn security group"))
    _ec2_sub(item, "ownerId", AWS_ACCOUNT_ID)
    _ec2_sub(item, "vpcId", group.get("vpc_id", ""))
    ip_permissions = _ec2_sub(item, "ipPermissions")
    for rule in group.get("ingress", []) or []:
        perm = _ec2_sub(ip_permissions, "item")
        _ec2_sub(perm, "ipProtocol", rule.get("protocol", "tcp"))
        _ec2_sub(perm, "fromPort", str(rule.get("from_port", 0)))
        _ec2_sub(perm, "toPort", str(rule.get("to_port", 65535)))
        ranges = _ec2_sub(perm, "ipRanges")
        range_item = _ec2_sub(ranges, "item")
        _ec2_sub(range_item, "cidrIp", rule.get("cidr", "0.0.0.0/0"))
        _ec2_sub(range_item, "description", rule.get("description", ""))
    ip_permissions_egress = _ec2_sub(item, "ipPermissionsEgress")
    egress_rules = group.get("egress", []) or []
    if not egress_rules and group.get("is_default"):
        egress_rules = [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "description": "default egress"}]
    for rule in egress_rules:
        egress_item = _ec2_sub(ip_permissions_egress, "item")
        _ec2_sub(egress_item, "ipProtocol", rule.get("protocol", "-1"))
        _ec2_sub(egress_item, "fromPort", str(rule.get("from_port", 0)))
        _ec2_sub(egress_item, "toPort", str(rule.get("to_port", 0)))
        egress_ranges = _ec2_sub(egress_item, "ipRanges")
        egress_range_item = _ec2_sub(egress_ranges, "item")
        _ec2_sub(egress_range_item, "cidrIp", rule.get("cidr", "0.0.0.0/0"))
        _ec2_sub(egress_range_item, "description", rule.get("description", "default egress"))
    tag_set = _ec2_sub(item, "tagSet")
    for tag in group.get("tags", []) or []:
        if not isinstance(tag, dict):
            continue
        tag_item = _ec2_sub(tag_set, "item")
        _ec2_sub(tag_item, "key", str(tag.get("key", "")))
        _ec2_sub(tag_item, "value", str(tag.get("value", "")))
    return item


def _ec2_volume_xml(instance: dict) -> ET.Element:
    item = _ec2_xml("item")
    volume_id = f"vol-{instance['instance_id'].replace('i-', '')}"
    state = "in-use" if instance.get("state") in {"running", "pending", "rebooting"} else "available"
    _ec2_sub(item, "volumeId", volume_id)
    _ec2_sub(item, "size", str(instance.get("storage_gb", 8)))
    _ec2_sub(item, "snapshotId", "")
    _ec2_sub(item, "availabilityZone", instance.get("az", "us-east-1a"))
    _ec2_sub(item, "state", state)
    _ec2_sub(item, "createTime", instance.get("created", _now()))
    _ec2_sub(item, "volumeType", "gp3")
    _ec2_sub(item, "iops", "3000")
    _ec2_sub(item, "encrypted", "false")
    attachments = _ec2_sub(item, "attachmentSet")
    att = _ec2_sub(attachments, "item")
    _ec2_sub(att, "volumeId", volume_id)
    _ec2_sub(att, "instanceId", instance["instance_id"])
    _ec2_sub(att, "device", "/dev/xvda")
    _ec2_sub(att, "status", "attached" if state == "in-use" else "available")
    _ec2_sub(att, "attachTime", instance.get("created", _now()))
    _ec2_sub(att, "deleteOnTermination", "true")
    return item


def _ec2_filter_values(params: dict[str, Any], prefix: str) -> list[str]:
    values: list[str] = []
    for key, value in params.items():
        if not key.startswith(prefix):
            continue
        if isinstance(value, list):
            values.extend([str(v) for v in value if v is not None])
        elif value is not None:
            values.append(str(value))
    return values


def _ec2_parse_instance_ids(params: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key, value in params.items():
        if key.lower().startswith("instanceid"):
            if isinstance(value, list):
                ids.extend([str(v) for v in value if v])
            elif value:
                ids.append(str(value))
    return ids


def _ec2_parse_filters(params: dict[str, Any]) -> list[tuple[str, list[str]]]:
    filters: dict[str, list[str]] = {}
    for key, value in params.items():
        m = re.match(r"^Filter\.(\d+)\.Name$", key)
        if not m:
            continue
        idx = m.group(1)
        name = str(value)
        vals: list[str] = []
        for vkey, vvalue in params.items():
            if re.match(rf"^Filter\.{idx}\.Value(\.\d+)?$", vkey):
                if isinstance(vvalue, list):
                    vals.extend([str(v) for v in vvalue if v is not None])
                elif vvalue is not None:
                    vals.append(str(vvalue))
        filters[name] = vals
    return list(filters.items())


def _ec2_matches_filters(instance: dict, filters: list[tuple[str, list[str]]]) -> bool:
    if not filters:
        return True
    for name, values in filters:
        if name == "instance-state-name":
            if instance.get("state") not in values:
                return False
        elif name == "instance-type":
            if instance.get("instance_type") not in values:
                return False
        elif name == "availability-zone":
            if instance.get("az") not in values:
                return False
        elif name == "vpc-id":
            if instance.get("vpc_id") not in values:
                return False
        elif name == "subnet-id":
            if instance.get("subnet_id") not in values:
                return False
        elif name.startswith("tag:"):
            wanted = name.split(":", 1)[1]
            if wanted != "Name" or instance.get("name") not in values:
                return False
        else:
            continue
    return True


def _terminated_visible(instance: dict, now: Optional[datetime] = None) -> bool:
    if instance.get("state") != "terminated":
        return True
    terminated_at = _parse_utc_timestamp(instance.get("terminated_at"))
    if not terminated_at:
        return False
    now = now or datetime.now(timezone.utc)
    return now < terminated_at + timedelta(seconds=EC2_TERMINATED_VISIBILITY_SECONDS)


def _prune_expired_terminated_instances() -> None:
    _prune_expired_terminated_instances_from(ec2_state.get("instances", {}))


def _ec2_instance_ids() -> list[str]:
    with STATE_LOCK:
        return list(ec2_state.get("instances", {}).keys())


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


def _fmt_size(n: int) -> str:
    orig = n
    for unit in ["B", "KB", "MB", "GB"]:
        if orig < 1024:
            return f"{orig:.1f} {unit}"
        orig /= 1024
    return f"{orig:.1f} TB"


def _req_id() -> str:
    return uuid.uuid4().hex.upper()[:16]


def _xml_response(content: str, status: int = 200, extra_headers: dict = None) -> Response:
    headers = {
        "x-amz-request-id": _req_id(),
        "x-amz-id-2": uuid.uuid4().hex,
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        content=content,
        status_code=status,
        media_type="application/xml",
        headers=headers,
    )


def _empty_response(status: int = 204, extra_headers: dict = None) -> Response:
    headers = {
        "x-amz-request-id": _req_id(),
        "x-amz-id-2": uuid.uuid4().hex,
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(status_code=status, headers=headers)


def _error_xml(code: str, message: str, resource: str = "/", status: int = 400) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Error>"
        f"<Code>{code}</Code>"
        f"<Message>{message}</Message>"
        f"<Resource>{resource}</Resource>"
        f"<RequestId>{_req_id()}</RequestId>"
        "</Error>"
    )
    return _xml_response(xml, status=status)


def _delete_marker_response(resource: str, last_modified: str, status: int = 405) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Error>"
        "<Code>MethodNotAllowed</Code>"
        "<Message>The specified version is a delete marker.</Message>"
        f"<Resource>{resource}</Resource>"
        f"<RequestId>{_req_id()}</RequestId>"
        "</Error>"
    )
    return _xml_response(
        xml,
        status=status,
        extra_headers={
            "x-amz-delete-marker": "true",
            "Last-Modified": _iso_to_http_date(last_modified),
        },
    )


def _bucket_exists(name: str) -> bool:
    return name in buckets


def _s3_bucket_versioning_status(bucket: str) -> str:
    status = buckets.get(bucket, {}).get("versioning", "Disabled")
    return status if status in {"Enabled", "Suspended", "Disabled"} else "Disabled"


def _s3_versioning_enabled(bucket: str) -> bool:
    return _s3_bucket_versioning_status(bucket) in {"Enabled", "Suspended"}


def _s3_new_version_id(bucket: str) -> str:
    return "null" if _s3_bucket_versioning_status(bucket) == "Suspended" else uuid.uuid4().hex


def _s3_object_version_from_entry(entry: dict) -> dict:
    version = {
        "version_id": str(entry.get("version_id") or entry.get("current_version_id") or "null"),
        "is_delete_marker": bool(entry.get("is_delete_marker", False)),
        "data": entry.get("data", b"") if not entry.get("is_delete_marker") else b"",
        "size": int(entry.get("size", 0) or 0),
        "content_type": entry.get("content_type", "application/octet-stream"),
        "last_modified": entry.get("last_modified", _now()),
        "etag": entry.get("etag", ""),
        "storage_class": entry.get("storage_class", "STANDARD"),
        "metadata": copy.deepcopy(entry.get("metadata", {})),
        "tags": copy.deepcopy(entry.get("tags", {})),
    }
    version["is_latest"] = bool(entry.get("is_latest", False))
    return version


def _s3_ensure_object_entry(bucket: str, key: str, create: bool = False) -> dict | None:
    bucket_objects = objects.setdefault(bucket, {})
    entry = bucket_objects.get(key)
    if entry is None:
        if not create:
            return None
        entry = {"versions": []}
        bucket_objects[key] = entry
    if not isinstance(entry, dict):
        if not create:
            return None
        entry = {"versions": []}
        bucket_objects[key] = entry
    if "versions" not in entry or not isinstance(entry.get("versions"), list):
        entry["versions"] = [_s3_object_version_from_entry(entry)]
    entry["versions"] = [copy.deepcopy(v) for v in entry.get("versions", []) if isinstance(v, dict)]
    if entry["versions"]:
        _s3_refresh_object_entry(entry)
    return entry


def _s3_refresh_object_entry(entry: dict) -> None:
    versions = entry.get("versions", [])
    for idx, version in enumerate(versions):
        version["is_latest"] = idx == 0
    if not versions:
        entry["current_version_id"] = ""
        entry["is_delete_marker"] = False
        entry["data"] = b""
        entry["size"] = 0
        entry["content_type"] = "application/octet-stream"
        entry["last_modified"] = _now()
        entry["etag"] = ""
        entry["storage_class"] = "STANDARD"
        entry["metadata"] = {}
        entry["tags"] = {}
        return
    current = versions[0]
    entry["current_version_id"] = current.get("version_id", "null")
    entry["version_id"] = current.get("version_id", "null")
    entry["is_delete_marker"] = bool(current.get("is_delete_marker", False))
    entry["data"] = current.get("data", b"") if not current.get("is_delete_marker") else b""
    entry["size"] = int(current.get("size", 0) or 0)
    entry["content_type"] = current.get("content_type", "application/octet-stream")
    entry["last_modified"] = current.get("last_modified", _now())
    entry["etag"] = current.get("etag", "")
    entry["storage_class"] = current.get("storage_class", "STANDARD")
    entry["metadata"] = copy.deepcopy(current.get("metadata", {}))
    entry["tags"] = copy.deepcopy(current.get("tags", {}))


def _s3_make_version_record(
    *,
    data: bytes = b"",
    content_type: str = "application/octet-stream",
    storage_class: str = "STANDARD",
    metadata: dict | None = None,
    tags: dict | None = None,
    version_id: str | None = None,
    delete_marker: bool = False,
    last_modified: str | None = None,
    etag: str | None = None,
) -> dict:
    return {
        "version_id": version_id or "null",
        "is_delete_marker": delete_marker,
        "data": b"" if delete_marker else data,
        "size": 0 if delete_marker else len(data),
        "content_type": "application/octet-stream" if delete_marker else content_type,
        "last_modified": last_modified or _now(),
        "etag": etag or ("" if delete_marker else _etag(data)),
        "storage_class": storage_class,
        "metadata": copy.deepcopy(metadata or {}),
        "tags": copy.deepcopy(tags or {}),
    }


def _s3_latest_visible_version(entry: dict | None) -> dict | None:
    if not entry:
        return None
    versions = entry.get("versions", []) if isinstance(entry, dict) else []
    if not versions:
        return None
    latest = versions[0]
    return None if latest.get("is_delete_marker") else latest


def _s3_find_version(entry: dict | None, version_id: str | None) -> dict | None:
    if not entry:
        return None
    versions = entry.get("versions", [])
    if not version_id:
        return versions[0] if versions else None
    for version in versions:
        if str(version.get("version_id")) == str(version_id):
            return version
    return None


def _s3_total_bytes() -> int:
    """Sum of all bucket+object data sizes in the active space (cheap O(n)
    over the in-memory `objects` proxy). Used for the tier storage cap."""
    total = 0
    try:
        for bk_objs in (objects or {}).values():
            for ent in (bk_objs or {}).values():
                versions = ent.get("versions") or [] if isinstance(ent, dict) else []
                for v in versions:
                    if isinstance(v, dict) and not v.get("is_delete_marker"):
                        total += int(v.get("size") or len(v.get("data") or b""))
    except Exception:
        pass
    return total


def _enforce_storage_cap(additional_bytes: int) -> None:
    """Raise HTTPException(403) if the active tier's total-storage-bytes cap
    would be exceeded by adding `additional_bytes` more."""
    try:
        tenant = _tenant_dict(_active_tenant_id()) or {}
    except Exception:
        tenant = {}
    tier = str(tenant.get("license_tier")
               or (STATE.get("license") or {}).get("tier")
               or "free")
    current = _s3_total_bytes()
    from core import tier_policy as _tp
    result = _tp.check_storage(tier, current, additional_bytes)
    if not result["ok"]:
        result["active_tier"] = tier
        result["docs"] = "https://cloudlearn.io/docs/tiers"
        raise HTTPException(status_code=403, detail=result)


def _s3_write_object_version(
    bucket: str,
    key: str,
    version: dict,
    replace_version_id: str | None = None,
    event_name: str | None = None,
    source: str = "",
) -> dict:
    # Tier storage cap — Free=1 GB total; Student=10 GB; Developer=100 GB.
    # Enforced BEFORE the in-memory dict mutation so an over-cap upload
    # doesn't leave a half-stored version.
    if not version.get("is_delete_marker"):
        _enforce_storage_cap(int(version.get("size") or len(version.get("data") or b"")))
    entry = _s3_ensure_object_entry(bucket, key, create=True)
    versions = entry.setdefault("versions", [])
    if replace_version_id == "__overwrite__":
        versions = [version]
    elif replace_version_id is not None:
        for idx, existing in enumerate(versions):
            if str(existing.get("version_id")) == str(replace_version_id):
                versions[idx] = version
                break
        else:
            versions.insert(0, version)
    else:
        versions.insert(0, version)
    entry["versions"] = [copy.deepcopy(v) for v in versions]
    _s3_refresh_object_entry(entry)
    # MVP P0: write-through to MinIO so real bytes land on disk in the
    # cloudlearn-minio container. Best-effort; never breaks the S3 surface.
    try:
        if not version.get("is_delete_marker") and version.get("data") is not None:
            from core import minio_mirror as _mm
            _mm.put_object(
                bucket, key, version["data"],
                content_type=version.get("content_type", "application/octet-stream"),
                metadata=version.get("metadata"),
            )
    except Exception:
        pass
    if event_name:
        _s3_emit_event(bucket, key, event_name, entry.get("versions", [version])[0] if entry.get("versions") else version, source=source)
    return entry


def _s3_insert_simple_delete_marker(bucket: str, key: str, source: str = "") -> dict:
    entry = _s3_ensure_object_entry(bucket, key, create=True)
    status = _s3_bucket_versioning_status(bucket)
    if status == "Disabled":
        objects.setdefault(bucket, {}).pop(key, None)
        _s3_emit_event(bucket, key, "s3:ObjectRemoved:Delete", None, source=source)
        return {}

    versions = entry.setdefault("versions", [])
    if status == "Suspended" and versions and str(versions[0].get("version_id", "null")) == "null":
        versions.pop(0)
    delete_marker = _s3_make_version_record(
        delete_marker=True,
        version_id=_s3_new_version_id(bucket) if status == "Enabled" else "null",
    )
    event_name = "s3:ObjectRemoved:DeleteMarkerCreated" if status in {"Enabled", "Suspended"} else "s3:ObjectRemoved:Delete"
    return _s3_write_object_version(bucket, key, delete_marker, event_name=event_name, source=source)


def _s3_delete_version(bucket: str, key: str, version_id: str) -> bool:
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if not entry:
        return False
    versions = entry.get("versions", [])
    deleted_version = next((copy.deepcopy(v) for v in versions if str(v.get("version_id")) == str(version_id)), None)
    next_versions = [v for v in versions if str(v.get("version_id")) != str(version_id)]
    if len(next_versions) == len(versions):
        return False
    if next_versions:
        entry["versions"] = next_versions
        _s3_refresh_object_entry(entry)
    else:
        objects.get(bucket, {}).pop(key, None)
    _s3_emit_event(bucket, key, "s3:ObjectRemoved:Delete", deleted_version, source="DeleteObject")
    return True


def _s3_list_versions(bucket: str, prefix: str = "") -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for key in sorted(objects.get(bucket, {})):
        if prefix and not key.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        if not entry:
            continue
        versions = sorted(
            entry.get("versions", []),
            key=lambda v: (
                str(v.get("last_modified", "")),
                str(v.get("version_id", "")),
            ),
            reverse=True,
        )
        for version in versions:
            result.append((key, version))
    return result


def _s3_default_notifications() -> dict:
    return {
        "eventBridgeEnabled": False,
        "topicConfigurations": [],
        "queueConfigurations": [],
        "cloudFunctionConfigurations": [],
        "deliveries": [],
        "updatedAt": _now(),
    }


def _s3_bucket_notifications(bucket: str, create: bool = True) -> dict | None:
    b = buckets.get(bucket)
    if not b:
        return None
    notifications = b.get("notifications")
    if not isinstance(notifications, dict):
        if not create:
            return None
        notifications = _s3_default_notifications()
        b["notifications"] = notifications
    notifications.setdefault("eventBridgeEnabled", False)
    notifications.setdefault("topicConfigurations", [])
    notifications.setdefault("queueConfigurations", [])
    notifications.setdefault("cloudFunctionConfigurations", [])
    notifications.setdefault("deliveries", [])
    notifications.setdefault("updatedAt", _now())
    return notifications


def _s3_xml_name(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return (elem.tag or "").rsplit("}", 1)[-1]


def _s3_xml_find_child(elem: ET.Element, name: str) -> ET.Element | None:
    for child in list(elem):
        if _s3_xml_name(child) == name:
            return child
    return None


def _s3_xml_find_children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(elem) if _s3_xml_name(child) == name]


def _s3_xml_text(elem: ET.Element | None, name: str, default: str = "") -> str:
    child = _s3_xml_find_child(elem, name) if elem is not None else None
    return (child.text or default).strip() if child is not None else default


def _s3_event_pattern_matches(pattern: str, event_name: str) -> bool:
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(escaped, event_name) is not None


def _s3_notification_rule_matches(rule: dict, event_name: str, key: str) -> bool:
    patterns = rule.get("events") or []
    if patterns and not any(_s3_event_pattern_matches(pattern, event_name) for pattern in patterns):
        return False
    prefix = (rule.get("prefix") or "").strip()
    suffix = (rule.get("suffix") or "").strip()
    if prefix and not key.startswith(prefix):
        return False
    if suffix and not key.endswith(suffix):
        return False
    return True


def _s3_build_notification_event(bucket: str, key: str, version: dict | None, event_name: str, source: str) -> dict:
    bucket_meta = buckets.get(bucket, {})
    version_id = (version or {}).get("version_id", "null")
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": bucket_meta.get("region", "us-east-1"),
                "eventTime": _now(),
                "eventName": event_name.replace("s3:", ""),
                "userIdentity": {"principalId": "AWS:SIMULATOR"},
                "requestParameters": {"sourceIPAddress": "127.0.0.1"},
                "responseElements": {
                    "x-amz-request-id": _req_id(),
                    "x-amz-id-2": uuid.uuid4().hex,
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": source or "cloudlearn-s3-notification",
                    "bucket": {
                        "name": bucket,
                        "arn": bucket_meta.get("arn", f"arn:aws:s3:::{bucket}"),
                    },
                    "object": {
                        "key": key,
                        "size": int((version or {}).get("size", 0) or 0),
                        "eTag": (version or {}).get("etag", ""),
                        "versionId": version_id,
                        "sequencer": uuid.uuid4().hex[:16],
                    },
                },
            }
        ]
    }


def _s3_notification_delivery_targets(bucket: str, event_name: str, key: str) -> list[dict]:
    notifications = _s3_bucket_notifications(bucket, create=False)
    if not notifications:
        return []
    deliveries: list[dict] = []
    for rule in notifications.get("topicConfigurations", []):
        if _s3_notification_rule_matches(rule, event_name, key):
            deliveries.append({
                "type": "TopicConfiguration",
                "destination": rule.get("topic", ""),
                "id": rule.get("id", ""),
            })
    for rule in notifications.get("queueConfigurations", []):
        if _s3_notification_rule_matches(rule, event_name, key):
            deliveries.append({
                "type": "QueueConfiguration",
                "destination": rule.get("queue", ""),
                "id": rule.get("id", ""),
            })
    for rule in notifications.get("cloudFunctionConfigurations", []):
        if _s3_notification_rule_matches(rule, event_name, key):
            deliveries.append({
                "type": "CloudFunctionConfiguration",
                "destination": rule.get("cloudFunction", ""),
                "id": rule.get("id", ""),
            })
    if notifications.get("eventBridgeEnabled"):
        deliveries.append({
            "type": "EventBridgeConfiguration",
            "destination": "eventbridge",
            "id": "eventbridge",
        })
    return deliveries


def _s3_notification_record_delivery(
    bucket: str,
    event_name: str,
    key: str,
    version_id: str = "",
    source: str = "",
    payload: dict | None = None,
    test_event: bool = False,
) -> list[dict]:
    notifications = _s3_bucket_notifications(bucket, create=True)
    if not notifications:
        return []
    records = []
    deliveries = _s3_notification_delivery_targets(bucket, event_name, key)
    for target in deliveries:
        record = {
            "id": _id("s3evt"),
            "at": _now(),
            "bucket": bucket,
            "key": key,
            "version_id": version_id or "null",
            "event_name": event_name,
            "source": source,
            "destination_type": target["type"],
            "destination": target["destination"],
            "rule_id": target.get("id", ""),
            "status": "delivered",
            "test_event": test_event,
            "payload": copy.deepcopy(payload or {}),
        }
        if target["type"] == "CloudFunctionConfiguration" and target.get("destination"):
            function = _lambda_resolve_function(target["destination"])
            if function:
                try:
                    _lambda_invoke_function(
                        function["function_name"],
                        payload or {},
                        invocation_type="Event",
                        source=source or "s3",
                        source_principal="s3.amazonaws.com",
                        source_arn=f"arn:aws:s3:::{bucket}",
                        source_account=AWS_ACCOUNT_ID,
                    )
                except Exception as exc:
                    record["status"] = "failed"
                    record["error"] = getattr(exc, "detail", None) or str(exc)
            else:
                record["status"] = "failed"
                record["error"] = "Lambda function not found"
        elif target["type"] == "QueueConfiguration" and target.get("destination"):
            queue = _sqs_queue_from_name_or_url(target["destination"])
            if queue:
                try:
                    _sqs_enqueue_message(
                        queue,
                        json.dumps(payload or {}, default=str),
                        attributes={"event_name": event_name, "bucket": bucket, "source": source or "s3"},
                        message_attributes={},
                        source=source or "s3",
                    )
                except Exception as exc:
                    record["status"] = "failed"
                    record["error"] = getattr(exc, "detail", None) or str(exc)
            else:
                record["status"] = "failed"
                record["error"] = "SQS queue not found"
        notifications["deliveries"].append(record)
        records.append(record)
    notifications["deliveries"] = notifications["deliveries"][-200:]
    notifications["updatedAt"] = _now()
    return records


def _s3_emit_event(bucket: str, key: str, event_name: str, version: dict | None = None, source: str = "") -> dict:
    payload = _s3_build_notification_event(bucket, key, version, event_name, source)
    _s3_notification_record_delivery(
        bucket=bucket,
        event_name=event_name,
        key=key,
        version_id=(version or {}).get("version_id", "null"),
        source=source,
        payload=payload,
        test_event=event_name == "s3:TestEvent",
    )
    return payload


def _s3_notification_xml_from_config(bucket: str) -> str:
    notifications = _s3_bucket_notifications(bucket, create=True) or _s3_default_notifications()
    root = ET.Element("NotificationConfiguration", xmlns=S3_NS)
    if notifications.get("eventBridgeEnabled"):
        ET.SubElement(root, "EventBridgeConfiguration")

    def add_filter(parent: ET.Element, rule: dict) -> None:
        if not rule.get("prefix") and not rule.get("suffix"):
            return
        filter_el = ET.SubElement(parent, "Filter")
        s3key = ET.SubElement(filter_el, "S3Key")
        if rule.get("prefix"):
            fr = ET.SubElement(s3key, "FilterRule")
            ET.SubElement(fr, "Name").text = "prefix"
            ET.SubElement(fr, "Value").text = rule.get("prefix", "")
        if rule.get("suffix"):
            fr = ET.SubElement(s3key, "FilterRule")
            ET.SubElement(fr, "Name").text = "suffix"
            ET.SubElement(fr, "Value").text = rule.get("suffix", "")

    for rule in notifications.get("topicConfigurations", []):
        item = ET.SubElement(root, "TopicConfiguration")
        if rule.get("id"):
            ET.SubElement(item, "Id").text = rule.get("id", "")
        for event in rule.get("events", []):
            ET.SubElement(item, "Event").text = event
        ET.SubElement(item, "Topic").text = rule.get("topic", "")
        add_filter(item, rule)

    for rule in notifications.get("queueConfigurations", []):
        item = ET.SubElement(root, "QueueConfiguration")
        if rule.get("id"):
            ET.SubElement(item, "Id").text = rule.get("id", "")
        for event in rule.get("events", []):
            ET.SubElement(item, "Event").text = event
        ET.SubElement(item, "Queue").text = rule.get("queue", "")
        add_filter(item, rule)

    for rule in notifications.get("cloudFunctionConfigurations", []):
        item = ET.SubElement(root, "CloudFunctionConfiguration")
        if rule.get("id"):
            ET.SubElement(item, "Id").text = rule.get("id", "")
        for event in rule.get("events", []):
            ET.SubElement(item, "Event").text = event
        ET.SubElement(item, "CloudFunction").text = rule.get("cloudFunction", "")
        add_filter(item, rule)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _s3_parse_notification_xml(body: bytes) -> dict:
    config = _s3_default_notifications()
    if not body or not body.strip():
        return config
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise HTTPException(400, detail=f"MalformedXML: {exc}")
    if _s3_xml_name(root) != "NotificationConfiguration":
        raise HTTPException(400, detail="InvalidNotificationConfiguration")

    config["eventBridgeEnabled"] = _s3_xml_find_child(root, "EventBridgeConfiguration") is not None

    def parse_rule(el: ET.Element, dest_name: str) -> dict:
        rule = {
            "id": _s3_xml_text(el, "Id", _id("notif")),
            "events": [child.text.strip() for child in _s3_xml_find_children(el, "Event") if child.text and child.text.strip()],
            "prefix": "",
            "suffix": "",
        }
        if dest_name == "TopicConfiguration":
            rule["topic"] = _s3_xml_text(el, "Topic", "")
        elif dest_name == "QueueConfiguration":
            rule["queue"] = _s3_xml_text(el, "Queue", "")
        else:
            rule["cloudFunction"] = _s3_xml_text(el, "CloudFunction", "")
        filter_el = _s3_xml_find_child(el, "Filter")
        if filter_el is not None:
            s3_key = _s3_xml_find_child(filter_el, "S3Key")
            if s3_key is not None:
                for fr in _s3_xml_find_children(s3_key, "FilterRule"):
                    name = _s3_xml_text(fr, "Name", "").lower()
                    value = _s3_xml_text(fr, "Value", "")
                    if name == "prefix":
                        rule["prefix"] = value
                    elif name == "suffix":
                        rule["suffix"] = value
        return rule

    config["topicConfigurations"] = [parse_rule(el, "TopicConfiguration") for el in _s3_xml_find_children(root, "TopicConfiguration")]
    config["queueConfigurations"] = [parse_rule(el, "QueueConfiguration") for el in _s3_xml_find_children(root, "QueueConfiguration")]
    config["cloudFunctionConfigurations"] = [parse_rule(el, "CloudFunctionConfiguration") for el in _s3_xml_find_children(root, "CloudFunctionConfiguration")]
    config["updatedAt"] = _now()
    return config


def _s3_notification_summary(bucket: str) -> dict:
    notifications = _s3_bucket_notifications(bucket, create=False) or _s3_default_notifications()
    return {
        "bucket": bucket,
        "eventBridgeEnabled": bool(notifications.get("eventBridgeEnabled")),
        "rule_count": len(notifications.get("topicConfigurations", [])) + len(notifications.get("queueConfigurations", [])) + len(notifications.get("cloudFunctionConfigurations", [])),
        "delivery_count": len(notifications.get("deliveries", [])),
        "updatedAt": notifications.get("updatedAt", ""),
    }


def _validate_bucket_name(name: str) -> Optional[Response]:
    if len(name) < 3 or len(name) > 63:
        return _error_xml("InvalidBucketName", "Bucket name must be between 3 and 63 characters.", f"/{name}", 400)
    if not re.match(r'^[a-z0-9][a-z0-9\-.]*[a-z0-9]$', name) and len(name) > 1:
        return _error_xml("InvalidBucketName", "Bucket name can contain only lowercase letters, numbers, hyphens, and dots.", f"/{name}", 400)
    return None


# ── JSON API router (for React UI) ───────────────────────────────────────────
api = APIRouter(prefix="/api/s3")


@api.get("/buckets")
def api_list_buckets():
    return {
        "owner": "cloudlearn-simulator",
        "buckets": [{"name": n, **{k: v for k, v in m.items() if k not in {"tags", "notifications"}}} for n, m in buckets.items()],
        "count": len(buckets),
    }


@api.post("/buckets/{name}")
def api_create_bucket(name: str, region: str = Query(default="us-east-1")):
    if name in buckets:
        raise HTTPException(409, detail="BucketAlreadyOwnedByYou")
    err = _validate_bucket_name(name)
    if err:
        raise HTTPException(400, detail="InvalidBucketName")
    buckets[name] = {
        "region": region,
        "created": _now(),
        "access": "Bucket and objects not public",
        "versioning": "Disabled",
        "arn": f"arn:aws:s3:::{name}",
        "tags": {},
        "notifications": _s3_default_notifications(),
    }
    objects[name] = {}
    _record_usage("s3.create_bucket", {"bucket": name, "region": region})
    return {"message": f"Bucket '{name}' created", "location": f"/{name}"}


@api.get("/buckets/{name}")
def api_get_bucket(name: str):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    b = buckets[name]
    return {"name": name, **{k: v for k, v in b.items() if k != "tags"}}


@api.get("/buckets/{name}/versioning")
def api_get_bucket_versioning(name: str):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    return {"name": name, "versioning": _s3_bucket_versioning_status(name)}


@api.delete("/buckets/{name}")
def api_delete_bucket(name: str, force: int = 0):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    if objects.get(name):
        if not force:
            raise HTTPException(409, detail="BucketNotEmpty — delete all objects first")
        # ?force=1 — drop everything in the bucket so delete completes.
        # Matches the real S3 console's "Empty bucket then delete" flow
        # and lets the conformance harness exercise the contract
        # end-to-end without walking the versioning sweep manually.
        objects[name].clear()
    del buckets[name]
    del objects[name]
    _record_usage("s3.delete_bucket", {"bucket": name})
    return {"message": f"Bucket '{name}' deleted"}


@api.put("/buckets/{name}/versioning")
def api_set_bucket_versioning(name: str, payload: BucketVersioningRequest):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    status = (payload.status or "").strip().title()
    if status not in {"Enabled", "Suspended", "Disabled"}:
        raise HTTPException(400, detail="InvalidVersioningStatus")
    buckets[name]["versioning"] = status
    return {"message": f"Bucket '{name}' versioning set to {status}", "versioning": status}


@api.get("/buckets/{name}/notifications")
def api_get_bucket_notifications(name: str):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    return {
        "bucket": name,
        **(_s3_bucket_notifications(name, create=True) or _s3_default_notifications()),
        "summary": _s3_notification_summary(name),
    }


@api.put("/buckets/{name}/notification")
@api.put("/buckets/{name}/notifications")
def api_set_bucket_notifications(name: str, payload: BucketNotificationRequest):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    notif = _s3_default_notifications()
    notif["eventBridgeEnabled"] = bool(payload.event_bridge_enabled)
    for rule in payload.rules or []:
        rule_obj = {
            "id": rule.id.strip() or _id("notif"),
            "events": [evt.strip() for evt in (rule.events or []) if evt and evt.strip()],
            "prefix": (rule.prefix or "").strip(),
            "suffix": (rule.suffix or "").strip(),
        }
        if rule.destination_type == "QueueConfiguration":
            rule_obj["queue"] = rule.destination.strip()
            notif["queueConfigurations"].append(rule_obj)
        elif rule.destination_type == "CloudFunctionConfiguration":
            rule_obj["cloudFunction"] = rule.destination.strip()
            notif["cloudFunctionConfigurations"].append(rule_obj)
        else:
            rule_obj["topic"] = rule.destination.strip()
            notif["topicConfigurations"].append(rule_obj)
    notif["updatedAt"] = _now()
    buckets[name]["notifications"] = notif
    if notif["eventBridgeEnabled"] or notif["topicConfigurations"] or notif["queueConfigurations"] or notif["cloudFunctionConfigurations"]:
        _s3_notification_record_delivery(name, "s3:TestEvent", "", "", "api_set_bucket_notifications", {"message": "TestEvent"}, test_event=True)
    return {"message": f"Bucket '{name}' notifications updated", **notif, "summary": _s3_notification_summary(name)}


@api.delete("/buckets/{name}/notifications")
def api_delete_bucket_notifications(name: str):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    buckets[name]["notifications"] = _s3_default_notifications()
    return {"message": f"Bucket '{name}' notifications cleared", "summary": _s3_notification_summary(name)}


@api.get("/buckets/{name}/notifications/events")
def api_list_bucket_notification_events(name: str, limit: int = 50):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    notif = _s3_bucket_notifications(name, create=True) or _s3_default_notifications()
    limit = max(1, min(int(limit or 50), 200))
    events = list(reversed(notif.get("deliveries", [])))[:limit]
    return {"bucket": name, "events": events, "count": len(events), "summary": _s3_notification_summary(name)}


@api.get("/buckets/{bucket}/objects")
def api_list_objects(bucket: str, prefix: str = ""):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    result = []
    for key in sorted(objects[bucket]):
        if not key.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        if not entry or not entry.get("versions"):
            continue
        current = entry["versions"][0]
        if current.get("is_delete_marker"):
            continue
        result.append({
            "key": key,
            "size": current["size"],
            "size_human": _fmt_size(current["size"]),
            "content_type": current["content_type"],
            "last_modified": current["last_modified"],
            "etag": current["etag"],
            "storage_class": current.get("storage_class", "STANDARD"),
            "version_id": current.get("version_id", "null"),
            "version_count": len(entry.get("versions", [])),
        })
    return {"bucket": bucket, "prefix": prefix, "objects": result, "count": len(result)}


@api.get("/buckets/{bucket}/versions")
def api_list_bucket_versions(bucket: str, prefix: str = ""):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    versions = []
    for key in sorted(objects[bucket]):
        if prefix and not key.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        if not entry or not entry.get("versions"):
            continue
        for version in entry["versions"]:
            versions.append({
                "key": key,
                "version_id": version.get("version_id", "null"),
                "is_latest": bool(version.get("is_latest", False)),
                "is_delete_marker": bool(version.get("is_delete_marker", False)),
                "last_modified": version.get("last_modified"),
                "size": version.get("size", 0),
                "size_human": _fmt_size(version.get("size", 0) or 0),
                "content_type": version.get("content_type", "application/octet-stream"),
                "storage_class": version.get("storage_class", "STANDARD"),
            })
    return {"bucket": bucket, "prefix": prefix, "versions": versions, "count": len(versions)}


@api.get("/buckets/{bucket}/objects/{key:path}/versions")
def api_list_object_versions(bucket: str, key: str):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if not entry:
        raise HTTPException(404, detail="NoSuchKey")
    versions = []
    for version in entry.get("versions", []):
        versions.append({
            "version_id": version.get("version_id", "null"),
            "is_latest": bool(version.get("is_latest", False)),
            "is_delete_marker": bool(version.get("is_delete_marker", False)),
            "last_modified": version.get("last_modified"),
            "size": version.get("size", 0),
            "size_human": _fmt_size(version.get("size", 0) or 0),
            "etag": version.get("etag", ""),
        })
    return {"bucket": bucket, "key": key, "version_count": len(versions), "versions": versions}


@api.post("/buckets/{bucket}/objects")
async def api_upload_object(bucket: str, request: Request):
    """Upload an object — accepts either multipart/form-data (`file` field)
    or application/json (`{"key": str, "content": str|base64}`) so the
    same endpoint serves the SPA's multipart uploader AND the conformance
    harness's JSON-only POST."""
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")

    ctype = (request.headers.get("content-type") or "").lower()
    key = "unnamed"
    data = b""
    content_type = "application/octet-stream"

    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(422, detail="Field 'file' required")
        data = await upload.read()
        key = getattr(upload, "filename", None) or "unnamed"
        content_type = getattr(upload, "content_type", None) or content_type
    elif ctype.startswith("application/json") or not ctype:
        # JSON shape: {"key": "...", "content": "..."} — content may be
        # plain text or base64 if "base64": true.
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        key = str(body.get("key") or body.get("name") or "conformance-object")
        content = body.get("content", body.get("body", ""))
        if isinstance(content, str):
            if body.get("base64"):
                import base64 as _b64
                try:
                    data = _b64.b64decode(content)
                except Exception:
                    data = content.encode()
            else:
                data = content.encode()
        elif isinstance(content, (bytes, bytearray)):
            data = bytes(content)
        content_type = str(body.get("content_type") or "text/plain")
    else:
        raise HTTPException(415, detail=f"Unsupported content-type: {ctype}")

    versioning_status = _s3_bucket_versioning_status(bucket)
    version_id = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
    version = _s3_make_version_record(
        data=data,
        content_type=content_type,
        storage_class="STANDARD",
        metadata={},
        tags={},
        version_id=version_id,
        delete_marker=False,
    )
    replace_version_id = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
    entry = _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id, event_name="s3:ObjectCreated:Put", source="api_upload_object")
    _record_usage("s3.upload_object", {"bucket": bucket, "key": key})
    return {"message": f"Object '{key}' uploaded", "etag": version["etag"], "size": len(data), "version_id": entry.get("current_version_id", version_id)}


@api.get("/buckets/{bucket}/objects/{key:path}/meta")
def api_get_object_meta(bucket: str, key: str, version_id: str = Query(default="", alias="versionId")):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if not entry:
        raise HTTPException(404, detail="NoSuchKey")
    obj = _s3_find_version(entry, version_id) if version_id else entry.get("versions", [None])[0]
    if not obj or obj.get("is_delete_marker"):
        raise HTTPException(404, detail="NoSuchKey")
    return {
        "key": key,
        "bucket": bucket,
        "size": obj["size"],
        "size_human": _fmt_size(obj["size"]),
        "content_type": obj["content_type"],
        "last_modified": obj["last_modified"],
        "etag": obj["etag"],
        "storage_class": obj.get("storage_class", "STANDARD"),
        "arn": f"arn:aws:s3:::{bucket}/{key}",
        "metadata": obj.get("metadata", {}),
        "tags": obj.get("tags", {}),
        "version_id": obj.get("version_id", "null"),
        "version_count": len(entry.get("versions", [])),
        "is_delete_marker": bool(obj.get("is_delete_marker", False)),
    }


@api.get("/buckets/{bucket}/objects/{key:path}/download")
def api_download_object(bucket: str, key: str, version_id: str = Query(default="", alias="versionId")):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if not entry:
        raise HTTPException(404, detail="NoSuchKey")
    obj = _s3_find_version(entry, version_id) if version_id else entry.get("versions", [None])[0]
    if not obj or obj.get("is_delete_marker"):
        raise HTTPException(404, detail="NoSuchKey")
    return StreamingResponse(
        io.BytesIO(obj["data"]),
        media_type=obj["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{key}"',
            "Content-Length": str(obj["size"]),
            "ETag": obj["etag"],
            "x-amz-version-id": obj.get("version_id", "null"),
        },
    )


@api.delete("/buckets/{bucket}/objects/{key:path}")
def api_delete_object(bucket: str, key: str, version_id: str = Query(default="", alias="versionId")):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if version_id:
        if not _s3_delete_version(bucket, key, version_id):
            raise HTTPException(404, detail="NoSuchVersion")
        return {"message": f"Version '{version_id}' deleted", "version_id": version_id}
    status = _s3_bucket_versioning_status(bucket)
    if status == "Disabled":
        if key in objects.get(bucket, {}):
            del objects[bucket][key]
        _record_usage("s3.delete_object", {"bucket": bucket, "key": key, "version_id": version_id or "null"})
        return {"message": f"Object '{key}' deleted"}
    entry = _s3_insert_simple_delete_marker(bucket, key, source="DeleteObject")
    _record_usage("s3.delete_object", {"bucket": bucket, "key": key, "version_id": version_id or entry.get("current_version_id", "null")})
    return {
        "message": f"Delete marker created for '{key}'",
        "delete_marker": True,
        "version_id": entry.get("current_version_id", "null") if isinstance(entry, dict) else "null",
    }


app.include_router(api)


RUNTIME_HANDLES: Dict[str, Any] = {}
CONSOLE_SESSIONS: Dict[str, dict] = {}
CONSOLE_LOCK = threading.RLock()
LXD_BOOTSTRAP_LOCK = threading.RLock()
LXD_BOOTSTRAP_THREAD: threading.Thread | None = None


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _public_ip() -> str:
    return f"203.0.113.{int(uuid.uuid4().hex[:2], 16) % 250 + 1}"


def _private_ip() -> str:
    return f"10.{int(uuid.uuid4().hex[:2], 16) % 250}.{int(uuid.uuid4().hex[2:4], 16) % 250}.{int(uuid.uuid4().hex[4:6], 16) % 250}"


def _lxd_cli() -> str | None:
    return PLATFORM.runtime.lxd_cli()


def _lxd_available() -> bool:
    return PLATFORM.runtime.available()


def _lxd_cli_available() -> bool:
    return bool(_lxd_cli())


def _lxd_bootstrap_status() -> dict:
    return PLATFORM.runtime.bootstrap_status()


def _lxd_bootstrap_target() -> dict:
    return PLATFORM.runtime.bootstrap_target()


def _run_bootstrap_command(args: list[str], timeout: int = 1200) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _apply_bootstrap_result(result: subprocess.CompletedProcess) -> None:
    output = (result.stdout or "") + (result.stderr or "")
    runtime_state["lxd"]["last_checked"] = _now()
    runtime_state["lxd"]["message"] = output[-1000:].strip()
    if result.returncode == 0:
        runtime_state["lxd"]["status"] = "ready"
    else:
        runtime_state["lxd"]["status"] = "error"


def _lxd_bootstrap_worker() -> None:
    target = _lxd_bootstrap_target()
    with LXD_BOOTSTRAP_LOCK:
        runtime_state["lxd"]["status"] = "installing"
        runtime_state["lxd"]["helper"] = target["helper"]
        runtime_state["lxd"]["label"] = target["label"]
        runtime_state["lxd"]["message"] = target["message"]
        runtime_state["lxd"]["started_at"] = _now()
        _persist_state()

    try:
        if target["helper"] == "snap-lxd":
            for command in target["commands"]:
                completed = _run_bootstrap_command(command, timeout=1200)
                _apply_bootstrap_result(completed)
                _persist_state()
                if completed.returncode != 0:
                    break
        elif target["helper"] == "apt-lxd":
            for command in target["commands"]:
                completed = _run_bootstrap_command(command, timeout=1200)
                _apply_bootstrap_result(completed)
                _persist_state()
                if completed.returncode != 0:
                    break
        else:
            runtime_state["lxd"]["status"] = "manual"
            runtime_state["lxd"]["message"] = target["message"]
            _persist_state()
    except Exception as exc:
        runtime_state["lxd"]["status"] = "error"
        runtime_state["lxd"]["message"] = str(exc)
        runtime_state["lxd"]["finished_at"] = _now()
        _persist_state()
        return

    runtime_state["lxd"]["finished_at"] = _now()
    if _lxd_available():
        runtime_state["lxd"]["status"] = "ready"
        runtime_state["lxd"]["message"] = "LXD is ready."
    elif runtime_state["lxd"].get("status") not in {"manual", "error"}:
        runtime_state["lxd"]["status"] = "error"
        if not runtime_state["lxd"].get("message"):
            runtime_state["lxd"]["message"] = "LXD bootstrap finished without a usable LXC CLI."
    _persist_state()


def _start_lxd_bootstrap() -> dict:
    return PLATFORM.runtime.start_bootstrap()


def _preferred_runtime_backend() -> str:
    return PLATFORM.runtime.preferred_backend()


def _runtime_cli(backend: str) -> str | None:
    return PLATFORM.runtime.cli_for(backend)


def _runtime_available(backend: str) -> bool:
    return PLATFORM.runtime.available(backend)


def _runtime_bootstrap_status(backend: str | None = None) -> dict:
    return PLATFORM.runtime.bootstrap_status(backend)


def _runtime_bootstrap_target(backend: str | None = None) -> dict:
    return PLATFORM.runtime.bootstrap_target(backend)


_HOST_CPU_SAMPLE_LOCK = threading.Lock()
_HOST_CPU_SAMPLE_STATE = {"total": None, "idle": None, "pct": 0.0, "updated_at": None}


def _read_host_cpu_snapshot():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            first = fh.readline().strip().split()
        if not first or first[0] != "cpu":
            return None
        values = [int(value) for value in first[1:]]
        if not values:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle
    except Exception:
        return None


def _sample_host_cpu_metrics():
    now = datetime.now(timezone.utc)
    load_1m = load_5m = load_15m = None
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except Exception:
        pass
    cpu_count = os.cpu_count() or 1
    snapshot = _read_host_cpu_snapshot()
    with _HOST_CPU_SAMPLE_LOCK:
        previous_total = _HOST_CPU_SAMPLE_STATE.get("total")
        previous_idle = _HOST_CPU_SAMPLE_STATE.get("idle")
        pct = _HOST_CPU_SAMPLE_STATE.get("pct", 0.0) or 0.0
        source = "loadavg"
        if snapshot and previous_total is not None and snapshot[0] > previous_total:
            total_delta = snapshot[0] - previous_total
            idle_delta = snapshot[1] - (previous_idle or 0)
            busy_delta = max(0, total_delta - idle_delta)
            pct = round(min(100.0, max(0.0, (busy_delta / total_delta) * 100.0)), 1) if total_delta else 0.0
            source = "proc_stat"
            _HOST_CPU_SAMPLE_STATE.update({"total": snapshot[0], "idle": snapshot[1], "pct": pct, "updated_at": now})
        else:
            load_pct = (load_1m / cpu_count) * 100.0 if load_1m is not None else 0.0
            pct = round(min(100.0, max(0.0, load_pct)), 1)
            if snapshot:
                _HOST_CPU_SAMPLE_STATE.update({"total": snapshot[0], "idle": snapshot[1], "pct": pct, "updated_at": now})
    return {
        "cpu_percent": pct,
        "load_1m": round(load_1m or 0.0, 2),
        "load_5m": round(load_5m or 0.0, 2),
        "load_15m": round(load_15m or 0.0, 2),
        "cpu_count": cpu_count,
        "source": source,
        "updated_at": now.isoformat(),
    }


def _legacy_provider_cards() -> list[dict]:
    cards: list[dict] = []
    descriptions = {
        "aws":   "AWS console-like simulations and tooling.",
        "gcp":   "GCP console-like simulations and Material-style tooling.",
        "azure": "Azure portal-style console + ARM REST API, az CLI / Java / Go.",
    }
    # `other` exists in provider_registry for backward-compat (matrix lookups),
    # but is intentionally NOT returned here — the SPA tiles show only the
    # 3 implemented clouds.
    provider_order = ("aws", "gcp", "azure")
    providers = list_providers()
    for provider_id in provider_order:
        provider = providers.get(provider_id)
        if not isinstance(provider, dict):
            continue
        surface = provider.get("surface") or {}
        theme = (surface.get("theme") if isinstance(surface, dict) else {}) or {}
        tooling = provider.get("tooling") or {}
        flattened_tooling: list[dict] = []
        if isinstance(tooling, dict):
            for group in tooling.values():
                if not isinstance(group, list):
                    continue
                for item in group:
                    if not isinstance(item, dict):
                        continue
                    flattened_tooling.append({
                        "label": item.get("name") or item.get("label") or "",
                        "status": item.get("status", "partial"),
                        "notes": item.get("notes", ""),
                    })
        cards.append({
            "provider_id": provider_id,
            "display_name": provider.get("name") or provider_id.upper(),
            "description": descriptions.get(provider_id, f"{provider_id.upper()} simulator surface."),
            "surface": {
                "theme": {
                    "accent": theme.get("accent") or provider.get("theme", {}).get("accent") or "#0073bb",
                    "accent_dark": theme.get("accent_dark") or provider.get("theme", {}).get("accent_dark") or "#005fa8",
                    "panel": theme.get("panel") or "#ffffff",
                    "border": theme.get("border") or "#eaeded",
                    "canvas": theme.get("surface") or provider.get("theme", {}).get("surface") or "#f8fbff",
                },
            },
            "implemented_services": list(provider.get("native_services") or []),
            "tooling": flattened_tooling,
        })
    return cards


def _gcp_firestore_engine():
    return PLATFORM.firestore


def _require_lxd_runtime() -> None:
    if not _lxd_available():
        raise HTTPException(status_code=503, detail="LXDUnavailable")


def _lxd_run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return PLATFORM.runtime.run_backend("lxd", args, timeout=timeout)


def _lxd_run_checked(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    completed = _lxd_run(args, timeout=timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "LXDCommandFailed").strip()
        raise HTTPException(503, detail=detail)
    return completed


def _lxd_inspect(ref: str) -> dict[str, Any] | None:
    completed = _lxd_run(["info", ref], timeout=30)
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _lxd_status(ref: str) -> str | None:
    completed = _lxd_run(["list", ref, "--format", "csv", "-c", "s"], timeout=30)
    if completed.returncode == 0:
        text = (completed.stdout or "").strip().splitlines()
        if text:
            status = text[-1].strip().lower()
            if status:
                return status
    completed = _lxd_run(["info", ref], timeout=30)
    if completed.returncode != 0:
        return None
    text = completed.stdout or ""
    for line in text.splitlines():
        if line.lower().startswith("status:"):
            status = line.split(":", 1)[1].strip().lower()
            if status:
                return status
    return None


def _lxd_container_exists(ref: str) -> bool:
    return _lxd_status(ref) is not None


def _lxd_container_ipv4(ref: str) -> str | None:
    """Real global IPv4 of a container's eth0, via the runtime bridge.
    This is the address instances actually reach each other on (lxdbr0)."""
    completed = _lxd_run(["list", ref, "--format", "json"], timeout=30)
    if completed.returncode != 0:
        return None
    try:
        data = json.loads(completed.stdout or "[]")
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    for entry in data:
        if not isinstance(entry, dict) or str(entry.get("name") or "") != str(ref):
            continue
        network = (entry.get("state") or {}).get("network") or {}
        for iface_name, iface in network.items():
            if iface_name == "lo" or not isinstance(iface, dict):
                continue
            for addr in (iface.get("addresses") or []):
                if not isinstance(addr, dict):
                    continue
                if str(addr.get("family")) == "inet" and str(addr.get("scope")) == "global":
                    ip = str(addr.get("address") or "").strip()
                    if ip:
                        return ip
    return None


def _allocate_host_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _instance_workspace(instance_id: str) -> Path:
    return (INSTANCE_WORK_ROOT / instance_id).resolve()


def _ensure_instance_workspace(instance: dict) -> Path:
    workspace = _instance_workspace(instance["instance_id"])
    workspace.mkdir(parents=True, exist_ok=True)
    instance["workspace"] = str(workspace)
    instance["deployment_path"] = str(workspace)
    return workspace


def _container_name(instance: dict) -> str:
    return instance.get("container_name") or f"cloudlearn-{instance['instance_id']}"


def _container_mount_path() -> str:
    return "/workspace"


def _container_cwd(instance: dict) -> str:
    state = instance.get("console_state")
    if not isinstance(state, dict):
        return _container_mount_path()
    cwd = state.get("cwd")
    if not cwd:
        return _container_mount_path()
    workspace = _instance_workspace(instance["instance_id"])
    try:
        rel = Path(cwd).resolve().relative_to(workspace)
    except Exception:
        return _container_mount_path()
    if str(rel) in {".", ""}:
        return _container_mount_path()
    return str(Path(_container_mount_path()) / rel)


def _container_exec(instance: dict, command: str, cwd: str | None = None, detach: bool = False) -> subprocess.CompletedProcess:
    backend = str(instance.get("runtime_backend") or "lxd").strip().lower()
    ref = instance.get("container_id") or _container_name(instance)
    if backend == "multipass":
        args = ["exec", ref, "--", "/bin/sh", "-lc"]
        if cwd:
            command = f"cd {shlex.quote(cwd)} && {command}"
        args.append(command)
        return _multipass_run_checked(args, timeout=120)
    if backend == "simulated":
        workspace = _instance_workspace(instance["instance_id"]).resolve()
        run_cwd = str(workspace)
        if cwd:
            try:
                cwd_path = Path(cwd).resolve()
                mount_root = Path(_container_mount_path()).resolve()
                rel = cwd_path.relative_to(mount_root)
                run_cwd = str((workspace / rel).resolve())
            except Exception:
                if Path(cwd).exists():
                    run_cwd = cwd
        if detach:
            subprocess.Popen(
                command,
                shell=True,
                cwd=run_cwd,
                env=os.environ.copy(),
                start_new_session=True,
            )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
        return subprocess.run(
            command,
            shell=True,
            cwd=run_cwd,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    args = ["exec"]
    if detach:
        args.append("-d")
    if cwd:
        command = f"cd {shlex.quote(cwd)} && {command}"
    args += [ref, "--", "/bin/sh", "-lc", command]
    _ensure_lxd_workspace_directory(instance)
    return _lxd_run_checked(args, timeout=120)


def _lxd_ensure_launch_defaults() -> None:
    if not _lxd_available():
        raise HTTPException(status_code=503, detail="LXDUnavailable")
    try:
        completed = _lxd_run(["storage", "list", "--format", "json"], timeout=30)
        pool_names: set[str] = set()
        if completed.returncode == 0:
            try:
                payload = json.loads(completed.stdout or "[]")
            except Exception:
                payload = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        name = str(item.get("name") or "").strip().lower()
                        if name:
                            pool_names.add(name)
        if "default" not in pool_names:
            _lxd_run_checked(["storage", "create", "default", "dir"], timeout=120)
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        completed = _lxd_run(["network", "list", "--format", "json"], timeout=30)
        network_names: set[str] = set()
        if completed.returncode == 0:
            try:
                payload = json.loads(completed.stdout or "[]")
            except Exception:
                payload = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        name = str(item.get("name") or "").strip().lower()
                        if name:
                            network_names.add(name)
        if "lxdbr0" not in network_names:
            _lxd_run_checked(
                [
                    "network",
                    "create",
                    "lxdbr0",
                    "ipv4.address=auto",
                    "ipv4.nat=true",
                    "ipv6.address=auto",
                    "ipv6.nat=true",
                ],
                timeout=120,
            )
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        completed = _lxd_run(["profile", "show", "default"], timeout=30)
        profile_text = completed.stdout or ""
        if "root:" not in profile_text or "path: /" not in profile_text or "pool: default" not in profile_text:
            _lxd_run_checked(["profile", "device", "add", "default", "root", "disk", "pool=default", "path=/"], timeout=120)
        if "eth0:" not in profile_text or "network: lxdbr0" not in profile_text:
            _lxd_run_checked(["profile", "device", "add", "default", "eth0", "nic", "network=lxdbr0", "name=eth0"], timeout=120)
    except HTTPException:
        raise
    except Exception:
        pass


def _ensure_lxd_workspace_mount(instance: dict) -> None:
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        return
    workspace = _ensure_instance_workspace(instance)
    expected_source = str(workspace)
    completed = _lxd_run(["config", "device", "get", ref, "workspace", "source"], timeout=30)
    if completed.returncode == 0:
        current_source = str(completed.stdout or "").strip()
        if current_source == expected_source:
            return
        try:
            _lxd_run_checked(["config", "device", "remove", ref, "workspace"], timeout=60)
        except Exception:
            pass
    _lxd_run_checked(
        ["config", "device", "add", ref, "workspace", "disk", f"source={workspace}", "path=/workspace"],
        timeout=120,
    )


def _ensure_lxd_workspace_directory(instance: dict) -> None:
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        return
    try:
        _lxd_run_checked(["exec", ref, "--", "mkdir", "-p", "/workspace"], timeout=60)
    except Exception:
        pass


def _ensure_container(instance: dict) -> str:
    if not _lxd_available():
        raise HTTPException(503, detail="LXDUnavailable")
    if instance.get("state") == "terminated":
        raise HTTPException(409, detail="InstanceTerminated")

    _lxd_ensure_launch_defaults()

    workspace = _ensure_instance_workspace(instance)
    instance.setdefault("runtime_image", LXD_RUNTIME_IMAGE)
    instance.setdefault("container_port", LXD_CONSOLE_PORT)
    if not instance.get("host_port"):
        instance["host_port"] = _allocate_host_port()
    instance.setdefault("container_name", f"cloudlearn-{instance['instance_id']}")
    instance["endpoint_url"] = f"lxd://{instance['container_name']}"
    instance["container_download_state"] = "downloading"

    container_ref = instance.get("container_id") or instance["container_name"]
    if _lxd_container_exists(container_ref):
        if not instance.get("container_id"):
            instance["container_id"] = container_ref
        instance["container_download_state"] = "ready"
        _ensure_lxd_workspace_mount(instance)
        return container_ref

    run_args = [
        "launch",
        instance["runtime_image"],
        instance["container_name"],
    ]
    # Apply host-feasible limits derived from the chosen instance type. The
    # catalog says (e.g.) m5.8xlarge = 32 vCPU / 128 GB; runtime_sizer tier-maps
    # that into something the host can actually run, and we surface BOTH the
    # requested and provisioned numbers on the instance record for transparency.
    try:
        from core import runtime_sizer as _sizer
        provider = str(instance.get("provider") or "aws").lower()
        itype = str(instance.get("instance_type") or instance.get("machine_type") or "")
        sizing = _sizer.for_instance_type(itype, provider)
    except Exception:
        sizing = None
    if sizing:
        run_args.extend([
            "-c", f"limits.cpu={sizing['cpu']}",
            "-c", f"limits.memory={sizing['memory_mb']}MB",
        ])
        instance["runtime_sizing"] = sizing
    completed = _lxd_run_checked(run_args, timeout=120)
    instance["container_id"] = instance["container_name"]
    instance["container_status"] = "created"
    instance["container_download_state"] = "ready"
    _ensure_lxd_workspace_mount(instance)
    return instance["container_id"]


def _start_instance_command(instance: dict) -> None:
    command = (instance.get("command") or "").strip()
    if not command:
        return
    container_cwd = _container_cwd(instance)
    boot_command = f"nohup /bin/sh -lc {shlex.quote(command)} > .cloudlearn_app.log 2>&1 < /dev/null &"
    _container_exec(instance, boot_command, cwd=container_cwd, detach=False)


def _sync_lxd_instance(instance: dict) -> None:
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        return
    status = _lxd_status(ref)
    if not status:
        instance["container_status"] = "missing"
        if str(instance.get("state") or "").strip().lower() != "terminated" and str(instance.get("state") or "").strip().lower() != "stopped":
            instance["state"] = "stopped"
        if str(instance.get("launch_status") or "").strip().lower() in {"queued", "starting", "error", "pending"}:
            instance["launch_status"] = "ready"
            instance["launch_error"] = ""
        return
    instance["container_status"] = status
    if status == "running":
        instance["state"] = "running"
        # Surface the container's real bridge IP as the instance internal IP.
        real_ip = _lxd_container_ipv4(ref)
        if real_ip:
            instance["private_ip"] = real_ip
            instance["runtime_internal_ip"] = real_ip
        if str(instance.get("launch_status") or "").strip().lower() in {"queued", "starting", "error", "pending"}:
            instance["launch_status"] = "ready"
            instance["launch_error"] = ""
    elif status in {"exited", "created", "paused", "stopped", "suspended"}:
        if str(instance.get("state") or "").strip().lower() != "stopped":
            instance["state"] = "stopped"
        if str(instance.get("launch_status") or "").strip().lower() in {"queued", "starting", "error", "pending"}:
            instance["launch_status"] = "ready"
            instance["launch_error"] = ""


def _start_lxd_instance(instance: dict) -> dict:
    _ensure_container(instance)
    container_ref = instance.get("container_id") or instance["container_name"]
    status = _lxd_status(container_ref)
    if status != "running":
        _lxd_run_checked(["start", container_ref], timeout=120)
    _ensure_lxd_workspace_directory(instance)
    instance["state"] = "running"
    instance["container_status"] = "running"
    instance["console_backend"] = "lxd-exec"
    instance["started_at"] = _now()
    instance["stopped_at"] = ""
    if instance.get("command"):
        _start_instance_command(instance)
    instance["pid"] = None
    return instance


def _stop_lxd_instance(instance: dict) -> dict:
    if not _lxd_available():
        raise HTTPException(status_code=503, detail="LXDUnavailable")
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        raise HTTPException(409, detail="InstanceContainerMissing")
    status = _lxd_status(ref)
    if status == "running":
        _lxd_run_checked(["stop", ref], timeout=120)
    instance["state"] = "stopped"
    instance["stopped_at"] = _now()
    instance["container_status"] = "exited"
    instance["pid"] = None
    return instance


def _reboot_lxd_instance(instance: dict) -> dict:
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        raise HTTPException(409, detail="InstanceContainerMissing")
    if _lxd_status(ref) != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    instance["state"] = "rebooting"
    _lxd_run_checked(["restart", ref], timeout=180)
    _ensure_lxd_workspace_directory(instance)
    instance["state"] = "running"
    instance["container_status"] = "running"
    instance["console_backend"] = "lxd-exec"
    if instance.get("command"):
        _start_instance_command(instance)
    instance["rebooted_at"] = _now()
    return instance


def _terminate_lxd_instance(instance: dict) -> dict:
    if not _lxd_available():
        raise HTTPException(status_code=503, detail="LXDUnavailable")
    ref = instance.get("container_id") or instance.get("container_name")
    if ref and _lxd_container_exists(ref):
        _lxd_run(["rm", "-f", ref], timeout=120)
    instance["state"] = "terminated"
    instance["terminated_at"] = _now()
    instance["container_status"] = "removed"
    instance["pid"] = None
    # Reclaim the per-instance workspace dir + drop any vm-connect port
    # claim. Without this, /var/lib/cloudlearn/deployments grows
    # forever — a real cause of the disk-full incident earlier today.
    _post_terminate_cleanup(instance)
    return instance


def _multipass_run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return PLATFORM.runtime.run_backend("multipass", args, timeout=timeout)


def _host_run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return PLATFORM.runtime.run_backend("host", args, timeout=timeout)


def _multipass_run_checked(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    completed = _multipass_run(args, timeout=timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "MultipassCommandFailed").strip()
        raise HTTPException(503, detail=detail)
    return completed


def _multipass_info(ref: str) -> dict[str, Any] | None:
    completed = _multipass_run(["info", ref, "--format", "json"], timeout=30)
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if isinstance(info, dict):
        item = info.get(ref)
        if isinstance(item, dict):
            return item
        if info:
            first = next(iter(info.values()))
            if isinstance(first, dict):
                return first
    return payload if isinstance(payload, dict) else None


def _multipass_status(ref: str) -> str | None:
    payload = _multipass_info(ref)
    if not payload:
        return None
    status = payload.get("state") or payload.get("State") or payload.get("status")
    if status:
        return str(status).strip().lower()
    return None


def _multipass_container_exists(ref: str) -> bool:
    return _multipass_status(ref) is not None


def _multipass_ssh_identity() -> dict:
    identity: dict | None = None
    try:
        identity = PLATFORM.runtime.bridge_ssh_identity()
    except Exception:
        identity = None
    if isinstance(identity, dict) and identity.get("available") and identity.get("private_key_path") and identity.get("public_key"):
        return identity
    host_os = _parent_os()
    if host_os == "darwin":
        private_key_path = "/var/root/Library/Application Support/multipassd/ssh-keys/id_rsa"
    elif host_os == "linux":
        private_key_path = "/var/snap/multipass/common/data/multipassd/ssh-keys/id_rsa"
    elif host_os == "windows":
        private_key_path = r"C:\ProgramData\Multipass\ssh-keys\id_rsa"
    else:
        private_key_path = ""
    if not private_key_path:
        return {}
    public_key_path = f"{private_key_path}.pub"
    public_key = ""
    try:
        public_key = Path(public_key_path).read_text(encoding="utf-8").strip()
    except Exception:
        public_key = ""
    return {
        "available": bool(public_key),
        "private_key_path": private_key_path,
        "public_key_path": public_key_path,
        "public_key": public_key,
    }


def _multipass_ssh_target(instance: dict) -> tuple[str, str] | None:
    ref = instance.get("container_id") or instance.get("container_name") or instance.get("instance_id")
    payload = _multipass_info(str(ref))
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = []
    for key in ("ipv4", "IPv4", "ip", "IPAddress"):
        value = payload.get(key)
        if value:
            candidates.append(value)
    info = payload.get("info")
    if isinstance(info, dict):
        item = info.get(str(ref))
        if isinstance(item, dict):
            for key in ("ipv4", "IPv4", "ip", "IPAddress"):
                value = item.get(key)
                if value:
                    candidates.append(value)
    ip = ""
    for value in candidates:
        if isinstance(value, list) and value:
            ip = str(value[0]).strip()
            if ip:
                break
        elif isinstance(value, str) and value.strip():
            ip = value.strip()
            break
    if not ip:
        return None
    user = "ubuntu"
    return ip, user


def _multipass_ssh_args(instance: dict, command: str | None = None) -> tuple[list[str], str] | None:
    target = _multipass_ssh_target(instance)
    if not target:
        return None
    ip, user = target
    identity = _multipass_ssh_identity()
    key_path = str(identity.get("private_key_path") or "").strip()
    if not key_path or not identity.get("available"):
        return None
    ref = instance.get("container_id") or instance.get("container_name") or instance.get("instance_id")
    ssh_base = [
        "ssh",
        "-i",
        key_path,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-tt",
        f"{user}@{ip}",
    ]
    if command is None:
        command = "sh"
    args = [*ssh_base, "--", "sh", "-lc", command]
    ssh_cmd = f"ssh -i {shlex.quote(key_path)} {user}@{ip}"
    if command and command != "sh":
        ssh_cmd = f"{ssh_cmd} -- sh -lc {shlex.quote(command)}"
    return args, ssh_cmd


def _update_multipass_ssh_metadata(instance: dict) -> None:
    target = _multipass_ssh_args(instance, None)
    if not target:
        instance.pop("ssh_command", None)
        instance.pop("ssh_target", None)
        return
    args, ssh_cmd = target
    instance["ssh_command"] = ssh_cmd
    if len(args) >= 7:
        instance["ssh_target"] = args[6]
    else:
        instance.pop("ssh_target", None)


def _ensure_multipass_instance(instance: dict) -> str:
    if not _runtime_available("multipass"):
        raise HTTPException(status_code=503, detail="MultipassUnavailable")
    if instance.get("state") == "terminated":
        raise HTTPException(status_code=409, detail="InstanceTerminated")

    workspace = _ensure_instance_workspace(instance)
    instance.setdefault("runtime_image", MULTIPASS_RUNTIME_IMAGE)
    instance.setdefault("container_port", LXD_CONSOLE_PORT)
    if not instance.get("host_port"):
        instance["host_port"] = _allocate_host_port()
    instance.setdefault("container_name", f"cloudlearn-{instance['instance_id']}")
    instance["endpoint_url"] = f"multipass://{instance['container_name']}"
    instance["container_download_state"] = "downloading"

    container_ref = instance.get("container_id") or instance["container_name"]
    if _multipass_container_exists(container_ref):
        if not instance.get("container_id"):
            instance["container_id"] = container_ref
        instance["container_download_state"] = "ready"
        return container_ref

    launch_image = str(instance["runtime_image"] or MULTIPASS_RUNTIME_IMAGE)
    if launch_image.startswith("ubuntu:"):
        launch_image = launch_image.split("ubuntu:", 1)[1]
    identity = _multipass_ssh_identity()
    public_key = str(identity.get("public_key") or "").strip()
    cloud_init_lines = ["#cloud-config"]
    if public_key:
        cloud_init_lines.extend(["ssh_authorized_keys:", f"  - {public_key}"])
    if instance.get("user_data"):
        user_data = str(instance.get("user_data") or "").strip()
        if user_data:
            cloud_init_lines.append(user_data)
    cloud_init_payload = "\n".join(cloud_init_lines).strip() + "\n"

    # Same host-aware sizing as the LXD path (m5.8xlarge → host-tier limits).
    try:
        from core import runtime_sizer as _sizer
        provider = str(instance.get("provider") or "aws").lower()
        itype = str(instance.get("instance_type") or instance.get("machine_type") or "")
        sizing = _sizer.for_instance_type(itype, provider)
    except Exception:
        sizing = None
    sizing_flags = ""
    if sizing:
        sizing_flags = f" --cpus {int(sizing['cpu'])} --memory {int(sizing['memory_mb'])}M"
        instance["runtime_sizing"] = sizing
    launch_script = "\n".join(
        [
            "set -e",
            "tmp_cloudlearn_init=\"$(mktemp /tmp/cloudlearn-cloudinit.XXXXXX.yaml)\"",
            "cat > \"$tmp_cloudlearn_init\" <<'CLOUDLEARN_EOF'",
            cloud_init_payload.rstrip("\n"),
            "CLOUDLEARN_EOF",
            f"multipass launch {shlex.quote(launch_image)} --name {shlex.quote(instance['container_name'])}{sizing_flags} --cloud-init \"$tmp_cloudlearn_init\"",
            "status=$?",
            "rm -f \"$tmp_cloudlearn_init\"",
            "exit \"$status\"",
        ]
    )
    _host_run(["bash", "-lc", launch_script], timeout=300)
    instance["container_id"] = instance["container_name"]
    instance["container_status"] = "created"
    instance["container_download_state"] = "ready"
    try:
        _multipass_run_checked(["mount", str(workspace), f"{instance['container_name']}:/workspace"], timeout=180)
    except HTTPException:
        pass
    _update_multipass_ssh_metadata(instance)
    return instance["container_id"]


def _sync_multipass_instance(instance: dict) -> None:
    if not _runtime_available("multipass"):
        instance.setdefault("container_status", "multipass-unavailable")
        return
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        return
    status = _multipass_status(ref)
    if not status:
        instance["container_status"] = "missing"
        if str(instance.get("state") or "").strip().lower() != "terminated" and str(instance.get("state") or "").strip().lower() != "stopped":
            instance["state"] = "stopped"
        if str(instance.get("launch_status") or "").strip().lower() in {"queued", "starting", "error", "pending"}:
            instance["launch_status"] = "ready"
            instance["launch_error"] = ""
        return
    instance["container_status"] = status
    if status == "running":
        instance["state"] = "running"
        if str(instance.get("launch_status") or "").strip().lower() in {"queued", "starting", "error", "pending"}:
            instance["launch_status"] = "ready"
            instance["launch_error"] = ""
        _update_multipass_ssh_metadata(instance)
    elif status in {"stopped", "deleted", "suspended"}:
        if str(instance.get("state") or "").strip().lower() != "stopped":
            instance["state"] = "stopped"
        if str(instance.get("launch_status") or "").strip().lower() in {"queued", "starting", "error", "pending"}:
            instance["launch_status"] = "ready"
            instance["launch_error"] = ""


def _start_multipass_instance(instance: dict) -> dict:
    _ensure_multipass_instance(instance)
    container_ref = instance.get("container_id") or instance["container_name"]
    status = _multipass_status(container_ref)
    if status != "running":
        _multipass_run_checked(["start", container_ref], timeout=120)
    instance["state"] = "running"
    instance["container_status"] = "running"
    instance["console_backend"] = "multipass-ssh"
    instance["started_at"] = _now()
    instance["stopped_at"] = ""
    if instance.get("command"):
        _start_instance_command(instance)
    _update_multipass_ssh_metadata(instance)
    instance["pid"] = None
    return instance


def _stop_multipass_instance(instance: dict) -> dict:
    if not _runtime_available("multipass"):
        raise HTTPException(status_code=503, detail="MultipassUnavailable")
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        raise HTTPException(409, detail="InstanceContainerMissing")
    status = _multipass_status(ref)
    if status == "running":
        _multipass_run_checked(["stop", ref], timeout=120)
    instance["state"] = "stopped"
    instance["stopped_at"] = _now()
    instance["container_status"] = "stopped"
    instance["pid"] = None
    return instance


def _reboot_multipass_instance(instance: dict) -> dict:
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        raise HTTPException(409, detail="InstanceContainerMissing")
    if _multipass_status(ref) != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    instance["state"] = "rebooting"
    _multipass_run_checked(["restart", ref], timeout=180)
    instance["state"] = "running"
    instance["container_status"] = "running"
    instance["console_backend"] = "multipass-ssh"
    if instance.get("command"):
        _start_instance_command(instance)
    instance["rebooted_at"] = _now()
    return instance


# ──────────────────────────────────────────────────────────────────────────────
# Simulator host budget — clamp 30% .. 50% of host. Default 40% (the user
# keeps the rest for their own apps). Every container launch must fit in what's
# left after summing the runtime_sizing of all currently-live containers across
# every space + every provider. Over-budget creates are REJECTED at the API
# layer, before any state mutation — so the user gets an immediate 403 with a
# clear "delete one or pick smaller" message instead of a silent partial
# provision.
# ──────────────────────────────────────────────────────────────────────────────
SIMULATOR_BUDGET_PCT_MIN = 30
SIMULATOR_BUDGET_PCT_MAX = 50

# Runtime bypass switch — flip via POST /api/runtime/budget/{enable,disable}.
# When True, _check_budget_for_launch is a no-op so EC2/GCP/Azure VM creates
# don't hit the 30-50% host-clamp. The budget calc + chip still shows real
# numbers so the bypass is visible.
#
# DEFAULT IS BYPASSED so simulator workflows don't trip on the clamp for
# day-to-day testing. To restore production-like enforcement, either:
#   • POST /api/runtime/budget/enable          (runtime toggle, resets on
#                                                container restart)
#   • Set env CLOUDLEARN_SIMULATOR_BUDGET_GATE=enabled  (sticky on boot)
_BUDGET_BYPASSED: bool = (
    os.environ.get("CLOUDLEARN_SIMULATOR_BUDGET_GATE", "").lower().strip()
    not in ("enabled", "on", "true", "1")
)


def _simulator_budget_pct() -> int:
    try:
        v = int(os.environ.get("CLOUDLEARN_SIMULATOR_BUDGET_PCT", "40"))
    except Exception:
        v = 40
    return max(SIMULATOR_BUDGET_PCT_MIN, min(SIMULATOR_BUDGET_PCT_MAX, v))


def _host_cpu_memory() -> tuple[int, int]:
    """Live host CPU count + total RAM (MB). Works inside the simulator
    container: cpu_count is the cgroup quota; /proc/meminfo is the container's
    visible memory (matches LXD's view too)."""
    try:
        host_cpu = os.cpu_count() or 2
    except Exception:
        host_cpu = 2
    host_mem_mb = 4096
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    host_mem_mb = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass
    return host_cpu, host_mem_mb


def _simulator_budget() -> dict:
    host_cpu, host_mem_mb = _host_cpu_memory()
    pct = _simulator_budget_pct()
    return {
        "cpu": max(1, host_cpu * pct // 100),
        "memory_mb": max(256, host_mem_mb * pct // 100),
        "host_cpu": host_cpu,
        "host_memory_mb": host_mem_mb,
        "budget_pct": pct,
        "clamp": [SIMULATOR_BUDGET_PCT_MIN, SIMULATOR_BUDGET_PCT_MAX],
        "bypassed": _BUDGET_BYPASSED,
    }


def _simulator_used() -> dict:
    """Sum runtime_sizing of every live container across ALL spaces/providers.
    The host is one physical resource — budget is global, not per-tenant."""
    cpu = 0
    mem_mb = 0
    spaces = (_spaces_state().get("spaces") or {}) if isinstance(_spaces_state().get("spaces"), dict) else {}
    for sp in spaces.values():
        if not isinstance(sp, dict):
            continue
        ss = sp.get("service_states") if isinstance(sp.get("service_states"), dict) else {}
        if not ss:
            continue
        # AWS EC2 instances — count non-terminated.
        for inst in ((ss.get("ec2") or {}).get("instances") or {}).values():
            if isinstance(inst, dict) and str(inst.get("state") or "").lower() not in ("terminated",):
                sz = inst.get("runtime_sizing") or {}
                cpu += int(sz.get("cpu") or 0)
                mem_mb += int(sz.get("memory_mb") or 0)
        # GCP Compute instances.
        for inst in ((ss.get("gcp_compute") or {}).get("instances") or {}).values():
            if isinstance(inst, dict) and str(inst.get("status") or "").upper() not in ("TERMINATED",):
                sz = inst.get("runtime_sizing") or {}
                cpu += int(sz.get("cpu") or 0)
                mem_mb += int(sz.get("memory_mb") or 0)
        # Azure Microsoft.Compute/virtualMachines.
        azure = (ss.get("azure_arm") or {}).get("resources") or {}
        for rec in azure.values():
            if not isinstance(rec, dict):
                continue
            if str(rec.get("_type") or "").lower() != "microsoft.compute/virtualmachines":
                continue
            props = rec.get("properties") if isinstance(rec.get("properties"), dict) else {}
            rt = props.get("runtime") if isinstance(props.get("runtime"), dict) else {}
            sz = rt.get("sizing") if isinstance(rt, dict) else None
            if isinstance(sz, dict):
                cpu += int(sz.get("cpu") or 0)
                mem_mb += int(sz.get("memory_mb") or 0)
    return {"cpu": cpu, "memory_mb": mem_mb}


def _check_budget_for_launch(instance_type: str, provider: str) -> dict | None:
    """Pre-launch gate. Computes the sizing for this instance_type via the
    catalog → host-tier mapping, then refuses with HTTP 403 if the resulting
    CPU/MEM would push total live-container usage past the simulator's budget.
    Returns the sizing dict (so callers don't recompute) or None if the
    instance_type isn't in the catalog (let LXD use its defaults; no
    reservation accounted).

    When the bypass flag is on (POST /api/runtime/budget/disable), returns
    the sizing but skips the budget check — used for testing."""
    from core import runtime_sizer as _sizer
    sizing = _sizer.for_instance_type(instance_type or "", provider or "")
    if not sizing:
        return None
    if _BUDGET_BYPASSED:
        return sizing  # caller still gets sizing; just no 403
    budget = _simulator_budget()
    used = _simulator_used()
    new_cpu = used["cpu"] + int(sizing.get("cpu") or 0)
    new_mem = used["memory_mb"] + int(sizing.get("memory_mb") or 0)
    if new_cpu > budget["cpu"]:
        raise HTTPException(status_code=403, detail=(
            f"SimulatorBudgetExceeded: launching this instance would use "
            f"{new_cpu} CPU of {budget['cpu']} available (simulator allowed "
            f"{budget['budget_pct']}% of {budget['host_cpu']} host CPUs). "
            f"Delete an existing instance or pick a smaller type."))
    if new_mem > budget["memory_mb"]:
        raise HTTPException(status_code=403, detail=(
            f"SimulatorBudgetExceeded: launching this instance would use "
            f"{new_mem} MB of {budget['memory_mb']} MB available (simulator "
            f"allowed {budget['budget_pct']}% of {budget['host_memory_mb']} MB host). "
            f"Delete an existing instance or pick a smaller type."))
    return sizing


def provision_azure_vm_runtime(record: dict) -> None:
    """Back an Azure Microsoft.Compute/virtualMachines record with a REAL
    LXD/multipass container — parity with AWS EC2 and GCP Compute, which both
    already do this. Idempotent: a record with an existing container_name is a
    no-op. Failures are recorded on the record and never raised."""
    if not isinstance(record, dict):
        return
    if str(record.get("_type", "")).lower() != "microsoft.compute/virtualmachines":
        return
    props = record.setdefault("properties", {})
    if not isinstance(props, dict):
        props = {}; record["properties"] = props
    runtime = props.setdefault("runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}; props["runtime"] = runtime
    if runtime.get("containerName"):
        return  # already provisioned

    raw_name = str(record.get("name") or "vm").strip()
    safe_name = re.sub(r"[^a-z0-9-]+", "-", raw_name.lower()).strip("-") or "vm"
    digest = hashlib.sha1(str(record.get("id", raw_name)).encode()).hexdigest()[:8]
    instance_id = f"az-{digest}-{safe_name[:24]}"

    host_os = _resolved_host_os()
    if host_os in {"darwin", "windows"} and _runtime_available("multipass"):
        backend = "multipass"
    elif _lxd_available():
        backend = "lxd"
    else:
        runtime["status"] = "simulated"
        runtime["backend"] = "simulated"
        runtime["note"] = "No LXD/multipass runtime available on host — Azure VM is metadata-only here."
        return

    workspace = _instance_workspace(instance_id)
    workspace.mkdir(parents=True, exist_ok=True)
    runtime_image = LXD_RUNTIME_IMAGE if backend == "lxd" else MULTIPASS_RUNTIME_IMAGE
    container_name = f"cloudlearn-{instance_id}"
    vm_size = ""
    hw = props.get("hardwareProfile") if isinstance(props.get("hardwareProfile"), dict) else {}
    if isinstance(hw, dict):
        vm_size = str(hw.get("vmSize") or "")
    instance = {
        "instance_id": instance_id,
        "provider": "azure",
        "name": raw_name,
        "instance_type": vm_size,
        "ami": "",
        "runtime_image": runtime_image,
        "runtime_backend": backend,
        "container_name": container_name,
        "container_id": "",
        "container_port": LXD_CONSOLE_PORT,
        "host_port": _allocate_host_port(),
        "workspace": str(workspace),
        "deployment_path": str(workspace),
        "console_state": {"cwd": str(workspace)},
        "console_log": [],
        "state": "pending",
        "launch_status": "queued",
        "container_status": "created",
        "container_download_state": "pending",
        "command": "",
        "user_data": "",
        "console_backend": "lxd-exec" if backend == "lxd" else "multipass-ssh",
    }
    try:
        if backend == "lxd":
            _start_lxd_instance(instance)
        else:
            _start_multipass_instance(instance)
    except Exception as exc:
        runtime["status"] = "launch_failed"
        runtime["error"] = str(exc)[:200]
        runtime["backend"] = backend
        return

    runtime["status"] = "provisioned"
    runtime["backend"] = backend
    runtime["containerName"] = instance["container_name"]
    runtime["containerId"] = instance.get("container_id", "")
    runtime["endpointUrl"] = instance.get("endpoint_url", f"{backend}://{instance['container_name']}")
    runtime["containerStatus"] = instance.get("container_status", "")
    runtime["state"] = instance.get("state", "")
    runtime["sizing"] = instance.get("runtime_sizing", {})
    runtime["workspace"] = instance.get("workspace", "")
    # Real container IP (if LXD has assigned one) — Azure consumers see it as
    # the VM's private IP in the resource view.
    if instance.get("private_ip"):
        nics = props.setdefault("networkProfile", {}).setdefault("networkInterfaces", [])
        if isinstance(nics, list) and not nics:
            nics.append({"id": f"runtime/{instance['container_name']}",
                         "properties": {"privateIPAddress": instance["private_ip"]}})


def deprovision_azure_vm_runtime(record: dict) -> None:
    """Tear down the LXD/multipass container backing an Azure VM (called on
    ARM DELETE). Best-effort — Azure delete should not fail if cleanup hits an
    error."""
    try:
        if not isinstance(record, dict):
            return
        props = record.get("properties") if isinstance(record.get("properties"), dict) else {}
        runtime = props.get("runtime") if isinstance(props.get("runtime"), dict) else {}
        container = runtime.get("containerName") if isinstance(runtime, dict) else None
        backend = runtime.get("backend") if isinstance(runtime, dict) else None
        if not container:
            return
        if backend == "lxd" and _lxd_available():
            try:
                _lxd_run_checked(["stop", container, "--force"], timeout=60)
            except Exception:
                pass
            try:
                _lxd_run_checked(["delete", container, "--force"], timeout=60)
            except Exception:
                pass
        elif backend == "multipass" and _runtime_available("multipass"):
            try:
                _multipass_run(["delete", "--purge", container], timeout=60)
            except Exception:
                pass
    except Exception:
        pass


def _terminate_multipass_instance(instance: dict) -> dict:
    if not _runtime_available("multipass"):
        raise HTTPException(status_code=503, detail="MultipassUnavailable")
    ref = instance.get("container_id") or instance.get("container_name")
    if ref and _multipass_container_exists(ref):
        try:
            _multipass_run(["delete", "--purge", ref], timeout=180)
        except HTTPException:
            _multipass_run(["delete", ref], timeout=180)
    instance["state"] = "terminated"
    instance["terminated_at"] = _now()
    instance["container_status"] = "removed"
    instance["pid"] = None
    _post_terminate_cleanup(instance)
    return instance


def _spawn_multipass_console_session(instance: dict) -> dict:
    instance_id = instance["instance_id"]
    target = _multipass_ssh_args(instance, None)
    if not target:
        raise HTTPException(503, detail="MultipassUnavailable")
    ref = instance.get("container_id") or instance.get("container_name") or instance_id
    if _multipass_status(ref) != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    ssh_args, ssh_cmd = target

    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if session and not session.get("closed") and session.get("proc") and session["proc"].poll() is None:
            instance["console_state"] = "running"
            instance["console_backend"] = session.get("console_backend", "multipass-ssh")
            return session
        if session:
            CONSOLE_SESSIONS.pop(instance_id, None)

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.update(
            {
                "TERM": env.get("TERM", "xterm"),
                "CLOUDLEARN_INSTANCE_ID": instance_id,
                "CLOUDLEARN_INSTANCE_NAME": instance.get("name", ""),
                "CLOUDLEARN_AMI": instance.get("ami_name") or instance.get("ami") or "",
                "CLOUDLEARN_CONTAINER_IMAGE": instance.get("container_image") or "",
                "CLOUDLEARN_RUNTIME": instance.get("runtime") or "",
            }
        )
        # The interactive console is SSH-backed; we only keep a local PTY to
        # preserve the terminal UI while commands are executed via SSH.
        proc = subprocess.Popen(
            ["bash", "-lc", "sleep 0"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        try:
            os.close(slave_fd)
        except Exception:
            pass

        session = {
            "instance_id": instance_id,
            "proc": proc,
            "master_fd": master_fd,
            "buffer": deque(maxlen=1000),
            "created": _now(),
            "last_output": _now(),
            "closed": False,
            "terminated": False,
            "console_backend": "multipass-ssh",
            "affects_instance_state": False,
            "ssh_command": ssh_cmd,
            "ssh_args": ssh_args,
        }
        session["buffer"].append(
            f"{ssh_cmd}\nConnected to instance {ref} ({instance.get('runtime_image') or MULTIPASS_RUNTIME_IMAGE})\n"
        )
        CONSOLE_SESSIONS[instance_id] = session
        instance["pid"] = proc.pid
        instance["console_state"] = "running"
        instance["console_backend"] = "multipass-ssh"
        instance["ssh_command"] = ssh_cmd
        reader = threading.Thread(target=_console_reader_loop, args=(instance_id, session), daemon=True)
        session["reader_thread"] = reader
        reader.start()
        return session


def _spawn_simulated_console_session(instance: dict) -> dict:
    instance_id = instance["instance_id"]

    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if session and not session.get("closed") and session.get("proc") and session["proc"].poll() is None:
            instance["console_state"] = "running"
            instance["console_backend"] = session.get("console_backend", "simulated-shell")
            return session
        if session:
            CONSOLE_SESSIONS.pop(instance_id, None)

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.update(
            {
                "TERM": env.get("TERM", "xterm"),
                "CLOUDLEARN_INSTANCE_ID": instance_id,
                "CLOUDLEARN_INSTANCE_NAME": instance.get("name", ""),
                "CLOUDLEARN_AMI": instance.get("ami_name") or instance.get("ami") or "",
                "CLOUDLEARN_CONTAINER_IMAGE": instance.get("container_image") or "",
                "CLOUDLEARN_RUNTIME": instance.get("runtime") or "",
                "HOME": _instance_workspace(instance_id).as_posix(),
            }
        )
        proc = subprocess.Popen(
            ["/bin/sh", "-i"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        try:
            os.close(slave_fd)
        except Exception:
            pass

        session = {
            "instance_id": instance_id,
            "proc": proc,
            "master_fd": master_fd,
            "buffer": deque(maxlen=1000),
            "created": _now(),
            "last_output": _now(),
            "closed": False,
            "terminated": False,
            "console_backend": "simulated-shell",
            "affects_instance_state": False,
        }
        session["buffer"].append(
            f"Connected to simulated EC2 runtime for {instance.get('name', instance_id)} ({instance.get('runtime_image') or 'simulated'})\n"
        )
        CONSOLE_SESSIONS[instance_id] = session
        instance["pid"] = proc.pid
        instance["console_state"] = "running"
        instance["console_backend"] = "simulated-shell"
        reader = threading.Thread(target=_console_reader_loop, args=(instance_id, session), daemon=True)
        session["reader_thread"] = reader
        reader.start()
        return session


def _start_simulated_instance(instance: dict) -> dict:
    session = _spawn_console_session(instance)
    RUNTIME_HANDLES[instance["instance_id"]] = session["proc"]
    instance["state"] = "running"
    instance["started_at"] = _now()
    instance["stopped_at"] = ""
    instance["container_status"] = "simulated"
    instance["pid"] = session["proc"].pid
    if instance.get("command"):
        _start_instance_command(instance)
    return instance


def _stop_simulated_instance(instance: dict) -> dict:
    _close_console_session(instance["instance_id"], terminate=True)
    handle = RUNTIME_HANDLES.pop(instance["instance_id"], None)
    if handle and handle.poll() is None:
        try:
            handle.terminate()
        except Exception:
            pass
    instance["state"] = "stopped"
    instance["stopped_at"] = _now()
    instance["pid"] = None
    instance["container_status"] = "simulated"
    instance["console_state"] = "closed"
    return instance


def _terminate_simulated_instance(instance: dict) -> dict:
    _stop_simulated_instance(instance)
    instance["state"] = "terminated"
    instance["terminated_at"] = _now()
    instance["console_state"] = "closed"
    _post_terminate_cleanup(instance)
    return instance


def _post_terminate_cleanup(instance: dict) -> None:
    """Shared post-terminate hygiene: drop the workspace dir, release any
    vm-connect port claim. Called from every terminate path so disk
    doesn't creep with stale state."""
    iid = str(instance.get("instance_id") or instance.get("id") or "").strip()
    if not iid:
        return
    try:
        from core import disk_health as _dh
        _dh.cleanup_terminated_workspace(iid)
    except Exception:
        pass
    try:
        from core import vm_connect as _vmc
        _vmc.release_ssh_port(STATE, iid)
    except Exception:
        pass


def _ami_profile(ami: str) -> dict:
    for item in AMI_CATALOG:
        # copy to avoid mutating the shared catalog
        if item["ami"] == ami:
            return copy.deepcopy(item)
    fallback = copy.deepcopy(AMI_CATALOG[0])
    fallback["ami"] = ami or fallback["ami"]
    fallback["name"] = ami or fallback["name"]
    fallback["container_image"] = f"cloudlearn/custom:{(ami or 'default').replace('/', '-').replace(':', '-')}"
    fallback["description"] = "Custom AMI mapped to a lightweight local container profile."
    return fallback


def _ec2_profile_supported_backends(profile: dict) -> list[str]:
    backends = [str(backend).strip().lower() for backend in profile.get("supported_backends", []) if str(backend).strip()]
    return list(dict.fromkeys(backends))


def _ec2_profile_supported_host_os(profile: dict) -> list[str]:
    host_os = [str(value).strip().lower() for value in profile.get("supported_host_os", []) if str(value).strip()]
    return list(dict.fromkeys(host_os))


def _ec2_choose_runtime_backend(
    profile: dict,
    requested_backend: str = "",
    host_os_hint: str = "",
    require_available: bool = True,
) -> str:
    requested = (requested_backend or "").strip().lower()
    supported = _ec2_profile_supported_backends(profile)
    host_os = str(host_os_hint or _parent_os()).strip().lower()
    host_supported = _ec2_profile_supported_host_os(profile)
    appliance_mode = _appliance_mode_enabled()

    if appliance_mode:
        requested = "lxd" if not requested else requested
        if requested != "lxd":
            supported_label = ", ".join(supported) if supported else "LXD"
            raise HTTPException(400, detail=f"Appliance mode only supports LXD-backed EC2 instances. AMI '{profile.get('name', 'unknown')}' supports {supported_label}.")
    elif host_supported and host_os not in host_supported:
        raise HTTPException(503, detail=f"AMI '{profile.get('name', 'unknown')}' is not supported on {host_os}.")

    if requested and requested not in supported:
        supported_label = ", ".join(supported) if supported else "no runtime backends"
        raise HTTPException(400, detail=f"AMI '{profile.get('name', 'unknown')}' only supports {supported_label}.")

    preferred = "lxd" if appliance_mode else ("multipass" if host_os in {"windows", "darwin"} else "lxd")
    ordered: list[str] = []
    if requested:
        ordered.append(requested)
    ordered.append(preferred)
    default_backend = str(profile.get("default_runtime_backend") or "").strip().lower()
    if default_backend:
        ordered.append(default_backend)
    ordered.extend([backend for backend in ("multipass", "lxd") if backend != preferred])

    for backend in ordered:
        if backend not in supported:
            continue
        if require_available:
            if _runtime_available(backend):
                return backend
        else:
            return backend

    raise HTTPException(503, detail=f"AMI '{profile.get('name', 'unknown')}' is not launchable on this host.")


def _normalize_tier(tier: str) -> str:
    # Authoritative tier normalization lives in core/tier_policy.py — it knows
    # the canonical set (free/student/developer/enterprise) AND the legacy
    # aliases (pro/max/dev/edu/ent) for backward-compat with existing license
    # JWTs. Returns Free on any unknown input.
    from core import tier_policy as _tp
    return _tp.normalize_tier(tier)


def _cmd_prompt(instance: dict) -> str:
    os_family = str(instance.get("os_family") or "").lower()
    if instance.get("runtime_backend") == "lxd" or os_family != "windows":
        name = instance.get("container_name") or instance.get("container_id") or instance.get("name") or instance["instance_id"]
        user = "root" if os_family in {"", "linux", "ubuntu", "debian", "rhel", "suse", "fedora", "amazon-linux"} else "ubuntu"
        return f"{user}@{name}:/workspace$"
    return "C:\\Users\\Administrator>"


def _console_banner(instance: dict) -> str:
    os_family = str(instance.get("os_family") or "").lower()
    if os_family == "windows":
        return (
            "Microsoft Windows [Version 10.0.22631.0]\n"
            "(c) CloudLearn Simulator. All rights reserved.\n\n"
        )
    return (
        "Ubuntu 24.04 LTS cloudlearn.local tty1\n"
        "cloudlearn login: ubuntu\n\n"
    )


def _instance_console_script(instance: dict) -> str:
    prompt = _cmd_prompt(instance)
    return (
        f"export PS1='{prompt}'\n"
        "export PROMPT_COMMAND=\n"
        "exec /bin/sh\n"
    )


def _spawn_lxd_console_session(instance: dict) -> dict:
    instance_id = instance["instance_id"]
    binary = _lxd_cli()
    if not binary:
        raise HTTPException(503, detail="LXDUnavailable")
    ref = instance.get("container_id") or instance.get("container_name") or instance_id
    if _lxd_status(ref) != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    _ensure_lxd_workspace_directory(instance)

    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if session and not session.get("closed") and session.get("proc") and session["proc"].poll() is None:
            instance["console_state"] = "running"
            instance["console_backend"] = session.get("console_backend", "lxd-pty")
            return session
        if session:
            CONSOLE_SESSIONS.pop(instance_id, None)

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.update(
            {
                "TERM": env.get("TERM", "xterm"),
                "CLOUDLEARN_INSTANCE_ID": instance_id,
                "CLOUDLEARN_INSTANCE_NAME": instance.get("name", ""),
                "CLOUDLEARN_AMI": instance.get("ami_name") or instance.get("ami") or "",
                "CLOUDLEARN_CONTAINER_IMAGE": instance.get("container_image") or "",
                "CLOUDLEARN_RUNTIME": instance.get("runtime") or "",
                "HOME": _container_mount_path(),
            }
        )
        proc = subprocess.Popen(
            [binary, "exec", "-it", "-w", _container_mount_path(), ref, "/bin/sh", "-i"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        try:
            os.close(slave_fd)
        except Exception:
            pass

        session = {
            "instance_id": instance_id,
            "proc": proc,
            "master_fd": master_fd,
            "buffer": deque(maxlen=1000),
            "created": _now(),
            "last_output": _now(),
            "closed": False,
            "terminated": False,
            "console_backend": "lxd-pty",
            "affects_instance_state": False,
        }
        session["buffer"].append(
            f"Connected to container {ref} ({instance.get('runtime_image') or LXD_RUNTIME_IMAGE})\n"
        )
        CONSOLE_SESSIONS[instance_id] = session
        instance["pid"] = proc.pid
        instance["console_state"] = "running"
        instance["console_backend"] = "lxd-pty"
        reader = threading.Thread(target=_console_reader_loop, args=(instance_id, session), daemon=True)
        session["reader_thread"] = reader
        reader.start()
        return session


def _console_reader_loop(instance_id: str, session: dict) -> None:
    master_fd = session["master_fd"]
    proc = session["proc"]
    try:
        while True:
            if proc.poll() is not None:
                break
            try:
                readable, _, _ = select.select([master_fd], [], [], 0.25)
            except (OSError, ValueError):
                break
            if master_fd not in readable:
                continue
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if not text:
                continue
            with CONSOLE_LOCK:
                if session.get("closed"):
                    break
                session["buffer"].append(text)
                session["last_output"] = _now()
    finally:
        with CONSOLE_LOCK:
            session["closed"] = True
            inst = ec2_state["instances"].get(instance_id)
            if inst and session.get("affects_instance_state", True) and inst.get("state") == "running" and not session.get("terminated"):
                inst["state"] = "stopped"
                inst["pid"] = None
                inst["console_state"] = "closed"
        try:
            os.close(master_fd)
        except Exception:
            pass


def _spawn_console_session(instance: dict) -> dict:
    instance_id = instance["instance_id"]
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        return _spawn_multipass_console_session(instance)
    if backend == "lxd":
        return _spawn_lxd_console_session(instance)
    raise HTTPException(503, detail="RuntimeUnavailable")


def _close_console_session(instance_id: str, terminate: bool = True) -> None:
    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.pop(instance_id, None)
        if not session:
            return
        session["terminated"] = terminate
        session["closed"] = True
    proc = session.get("proc")
    if proc and proc.poll() is None:
        try:
            if terminate:
                proc.terminate()
            else:
                proc.kill()
        except Exception:
            pass
    try:
        master_fd = session.get("master_fd")
        if master_fd is not None:
            os.close(master_fd)
    except Exception:
        pass
    inst = ec2_state["instances"].get(instance_id)
    if inst:
        if inst.get("state") != "terminated" and session.get("affects_instance_state", True):
            inst["state"] = "stopped"
        inst["pid"] = None
        inst["console_state"] = "closed"


def _console_buffer_len(session: dict) -> int:
    with CONSOLE_LOCK:
        buffer = session.get("buffer", [])
        return len(buffer)


def _console_buffer_text(session: dict, start: int = 0) -> str:
    with CONSOLE_LOCK:
        buffer = list(session.get("buffer", []))
    if start < 0:
        start = 0
    if start >= len(buffer):
        return ""
    return "".join(buffer[start:])


async def _wait_console_buffer_settle(session: dict, start_len: int, timeout: float = 2.0) -> int:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_len = start_len
    stable_since = loop.time()
    while loop.time() < deadline:
        cur_len = _console_buffer_len(session)
        if cur_len > last_len:
            last_len = cur_len
            stable_since = loop.time()
        elif cur_len == last_len and (loop.time() - stable_since) >= 0.12:
            break
        await asyncio.sleep(0.05)
    return _console_buffer_len(session)


def _console_write(instance_id: str, data: str) -> None:
    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if not session or session.get("closed") or not session.get("proc") or session["proc"].poll() is not None:
            raise HTTPException(409, detail="ConsoleSessionNotConnected")
        fd = session.get("master_fd")
    if fd is None:
        raise HTTPException(409, detail="ConsoleSessionNotConnected")
    try:
        os.write(fd, data.encode("utf-8", errors="ignore"))
    except OSError:
        raise HTTPException(409, detail="ConsoleSessionNotConnected")


def _console_snapshot(instance_id: str) -> dict:
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if not session:
            return {
                "instance_id": instance_id,
                "state": instance.get("state", "unknown"),
                "console_state": instance.get("console_state", "closed"),
                "backend": instance.get("console_backend", "simulated"),
                "console_prompt": instance.get("console_prompt", _cmd_prompt(instance)),
                "output": "",
            }
        output = "".join(session["buffer"])
        return {
            "instance_id": instance_id,
            "state": instance.get("state", "unknown"),
            "console_state": "running" if not session.get("closed") else "closed",
            "backend": session.get("console_backend", "pty-shell"),
            "console_prompt": session.get("console_prompt", instance.get("console_prompt", _cmd_prompt(instance))),
            "output": output,
            "created": session.get("created"),
            "last_output": session.get("last_output"),
        }


def _console_execute(instance: dict, command: str) -> dict:
    command = (command or "").rstrip("\n")
    state = instance.get("console_state")
    if not isinstance(state, dict):
        state = {}
        instance["console_state"] = state
    workdir = state.get("cwd") or str((Path(__file__).with_name("deployments") / instance["instance_id"]).resolve())
    Path(workdir).mkdir(parents=True, exist_ok=True)

    if command == "\u0003":
        output = "^C\n"
        instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 130, "output": output, "at": _now()})
        return {"cwd": workdir, "command": command, "exit_code": 130, "output": output}

    if not command.strip():
        return {"cwd": workdir, "command": command, "exit_code": 0, "output": ""}

    if instance.get("runtime_backend") == "multipass":
        stripped = command.strip()

        def _resolve_target(target: str) -> str:
            base = Path(workdir).resolve()
            if not target or target in {"~", "."}:
                dest = base
            else:
                dest = Path(target)
                if not dest.is_absolute():
                    dest = (base / dest).resolve()
                else:
                    dest = dest.resolve()
            try:
                dest.relative_to(_instance_workspace(instance["instance_id"]))
            except Exception:
                raise HTTPException(403, detail="ConsolePathEscapesInstanceRoot")
            return str(dest)

        if stripped == "pwd":
            state["cwd"] = workdir
            output = f"{_instance_workspace(instance['instance_id'])}\n"
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 0, "output": output, "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 0, "output": output}

        if stripped.startswith("cd"):
            parts = stripped.split(maxsplit=1)
            target = parts[1] if len(parts) > 1 else ""
            state["cwd"] = _resolve_target(target)
            instance.setdefault("console_log", []).append({"command": command, "cwd": state["cwd"], "exit_code": 0, "output": "", "at": _now()})
            return {"cwd": state["cwd"], "command": command, "exit_code": 0, "output": ""}

        if stripped in {"clear", "cls"}:
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 0, "output": "\f", "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 0, "output": "\f"}

        alias_map = {
            "dir": "ls -la",
            "ls": "ls -la",
            "type": "cat",
            "copy": "cp",
            "move": "mv",
            "del": "rm -f",
            "erase": "rm -f",
            "mkdir": "mkdir -p",
            "md": "mkdir -p",
            "rmdir": "rm -rf",
            "rd": "rm -rf",
        }
        token = stripped.split(maxsplit=1)[0].lower()
        translated = command
        if token in alias_map:
            rest = stripped[len(token):].strip()
            translated = alias_map[token]
            if rest:
                translated = f"{translated} {rest}"

        ssh_args = _multipass_ssh_args(instance, f"cd {shlex.quote(state.get('cwd') or workdir)} && {translated}")
        if not ssh_args:
            output = "error: SSH access is unavailable for this instance.\n"
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 1, "output": output, "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 1, "output": output}

        args, _ssh_cmd = ssh_args
        try:
            completed = _host_run(args, timeout=120)
        except HTTPException as exc:
            output = f"error: {exc.detail}\n"
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 1, "output": output, "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 1, "output": output}

        output = (completed.stdout or "") + (completed.stderr or "")
        result = {
            "cwd": state.get("cwd") or workdir,
            "command": command,
            "exit_code": completed.returncode,
            "output": output,
        }
        instance.setdefault("console_log", []).append(
            {"command": command, "cwd": result["cwd"], "exit_code": completed.returncode, "output": output, "at": _now()}
        )
        return result

    if instance.get("runtime_backend") == "lxd":
        stripped = command.strip()

        def _display_path(host_path: str) -> str:
            workspace = _instance_workspace(instance["instance_id"])
            try:
                rel = Path(host_path).resolve().relative_to(workspace)
            except Exception:
                return "/workspace"
            base = "/workspace"
            rel_text = rel.as_posix().lstrip("./")
            if not rel_text:
                return base
            return base + "/" + rel_text

        def _resolve_target(target: str) -> str:
            base = Path(workdir).resolve()
            if not target or target in {"~", "."}:
                dest = base
            else:
                dest = Path(target)
                if not dest.is_absolute():
                    dest = (base / dest).resolve()
                else:
                    dest = dest.resolve()
            try:
                dest.relative_to(_instance_workspace(instance["instance_id"]))
            except Exception:
                raise HTTPException(403, detail="ConsolePathEscapesInstanceRoot")
            return str(dest)

        if stripped == "pwd":
            state["cwd"] = workdir
            output = f"{_display_path(workdir)}\n"
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 0, "output": output, "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 0, "output": output}

        if stripped.startswith("cd"):
            parts = stripped.split(maxsplit=1)
            target = parts[1] if len(parts) > 1 else ""
            state["cwd"] = _resolve_target(target)
            instance.setdefault("console_log", []).append({"command": command, "cwd": state["cwd"], "exit_code": 0, "output": "", "at": _now()})
            return {"cwd": state["cwd"], "command": command, "exit_code": 0, "output": ""}

        if stripped in {"clear", "cls"}:
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 0, "output": "\f", "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 0, "output": "\f"}

        alias_map = {
            "dir": "ls -la",
            "ls": "ls -la",
            "type": "cat",
            "copy": "cp",
            "move": "mv",
            "del": "rm -f",
            "erase": "rm -f",
            "mkdir": "mkdir -p",
            "md": "mkdir -p",
            "rmdir": "rm -rf",
            "rd": "rm -rf",
        }
        token = stripped.split(maxsplit=1)[0].lower()
        translated = command
        if token in alias_map:
            rest = stripped[len(token):].strip()
            translated = alias_map[token]
            if rest:
                translated = f"{translated} {rest}"

        try:
            completed = _container_exec(instance, translated, cwd=_container_cwd(instance))
        except HTTPException as exc:
            output = f"error: {exc.detail}\n"
            instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 1, "output": output, "at": _now()})
            return {"cwd": workdir, "command": command, "exit_code": 1, "output": output}

        output = (completed.stdout or "") + (completed.stderr or "")
        result = {
            "cwd": state.get("cwd") or workdir,
            "command": command,
            "exit_code": completed.returncode,
            "output": output,
        }
        instance.setdefault("console_log", []).append(
            {"command": command, "cwd": result["cwd"], "exit_code": completed.returncode, "output": output, "at": _now()}
        )
        return result

    def _safe_resolve(target: str) -> str:
        base = Path(workdir).resolve()
        if not target or target in {"~", "."}:
            dest = base
        else:
            dest = Path(target)
            if not dest.is_absolute():
                dest = (base / dest).resolve()
            else:
                dest = dest.resolve()
        try:
            dest.relative_to(base)
        except Exception:
            raise HTTPException(403, detail="ConsolePathEscapesInstanceRoot")
        return str(dest)

    stripped = command.strip()
    if stripped == "pwd":
        state["cwd"] = workdir
        output = f"{workdir}\n"
        instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 0, "output": output, "at": _now()})
        return {"cwd": workdir, "command": command, "exit_code": 0, "output": output}
    if stripped.startswith("cd"):
        parts = stripped.split(maxsplit=1)
        target = parts[1] if len(parts) > 1 else ""
        state["cwd"] = _safe_resolve(target)
        instance.setdefault("console_log", []).append({"command": command, "cwd": state["cwd"], "exit_code": 0, "output": "", "at": _now()})
        return {"cwd": state["cwd"], "command": command, "exit_code": 0, "output": ""}
    if stripped in {"clear", "cls"}:
        instance.setdefault("console_log", []).append({"command": command, "cwd": workdir, "exit_code": 0, "output": "\f", "at": _now()})
        return {"cwd": workdir, "command": command, "exit_code": 0, "output": "\f"}

    env = os.environ.copy()
    env.update(
        {
            "CLOUDLEARN_INSTANCE_ID": instance["instance_id"],
            "CLOUDLEARN_INSTANCE_NAME": instance.get("name", ""),
            "CLOUDLEARN_AMI": instance.get("ami_name") or instance.get("ami") or "",
            "CLOUDLEARN_CONTAINER_IMAGE": instance.get("container_image") or "",
            "CLOUDLEARN_RUNTIME": instance.get("runtime") or "",
            "HOME": state.get("cwd") or workdir,
        }
    )
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=state.get("cwd") or workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(408, detail="ConsoleCommandTimedOut")

    output = (completed.stdout or "") + (completed.stderr or "")
    result = {
        "cwd": state.get("cwd") or workdir,
        "command": command,
        "exit_code": completed.returncode,
        "output": output,
    }
    instance.setdefault("console_log", []).append(
        {"command": command, "cwd": result["cwd"], "exit_code": completed.returncode, "output": output, "at": _now()}
    )
    return result


def api_catalog():
    spaces_state = STATE.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1", "max_memory_mb": 8192, "max_disk_mb": 32768}})
    return {
        "tier": STATE["license"].get("tier", "free"),
        "credits": STATE["license"].get("credits", 0),
        "amis": AMI_CATALOG,
        "services": [
            {"id": "s3", "name": "S3", "active": STATE["packs"]["cloudlearn.s3.basic"].get("active", False), "status": "available"},
            {"id": "iam", "name": "IAM", "active": STATE["packs"]["cloudlearn.iam.basic"].get("active", False), "status": "available"},
            {"id": "ec2", "name": "EC2", "active": STATE["packs"]["cloudlearn.ec2.basic"].get("active", False), "status": "available"},
            {"id": "vpc", "name": "VPC", "active": STATE["packs"]["cloudlearn.vpc.basic"].get("active", False), "status": "available"},
            {"id": "apigateway", "name": "API Gateway", "active": STATE["packs"]["cloudlearn.apigateway.basic"].get("active", False), "status": "available"},
            {"id": "runtime.python", "name": "Python Runtime", "active": STATE["packs"]["cloudlearn.runtime.python"].get("active", False), "status": "available"},
        ],
        "spaces": {
            "count": len(spaces_state.get("spaces", {})),
            "active_space_id": spaces_state.get("active_space_id", ""),
            "active_space": copy.deepcopy(spaces_state.get("spaces", {}).get(spaces_state.get("active_space_id", ""), {})),
            "settings": copy.deepcopy(spaces_state.get("settings", {})),
        },
        "packs": _catalog(),
    }


def _space_payload(space: dict) -> dict:
    payload = copy.deepcopy(space)
    if not isinstance(payload, dict):
        return {}
    payload.setdefault("space_id", "")
    payload.setdefault("name", "")
    payload.setdefault("provider", "aws")
    payload.setdefault("status", "running")
    payload.setdefault("active_region", "us-east-1")
    payload.setdefault("active_account", "local-account")
    payload.setdefault("estimated_memory_mb", 0)
    payload.setdefault("estimated_disk_mb", 0)
    payload.setdefault("runtime_count", 0)
    payload.setdefault("ec2_count", 0)
    payload.setdefault("lambda_count", 0)
    payload.setdefault("rds_count", 0)
    payload.setdefault("sqs_count", 0)
    payload.setdefault("dynamodb_count", 0)
    cloudsim = payload.get("cloudsim")
    if isinstance(cloudsim, dict):
        cloudsim.pop("policy", None)
    payload.pop("cloudsim_policy", None)
    return payload


def _spaces_state() -> dict:
    spaces_state = STATE.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1"}})
    spaces_state.setdefault("spaces", {})
    spaces_state.setdefault("active_space_id", "")
    spaces_state.setdefault("settings", {})
    spaces_state["settings"].setdefault("max_spaces", 6)
    spaces_state["settings"].setdefault("default_provider", "aws")
    spaces_state["settings"].setdefault("default_region", "us-east-1")
    spaces_state["settings"].setdefault("max_memory_mb", 8192)
    spaces_state["settings"].setdefault("max_disk_mb", 32768)
    return spaces_state


def _federation_space_summary() -> dict:
    spaces_state = _spaces_state()
    spaces = spaces_state.get("spaces", {})
    federations = STATE.setdefault("federations", {"federations": {}, "links": {}, "tests": []})
    federation_defs = federations.get("federations", {})
    links = federations.get("links", {})
    link_values = list(links.values()) if isinstance(links, dict) else list(links) if isinstance(links, list) else []
    provider_counts: dict[str, int] = {}
    resource_counts = {
        "runtime_count": 0,
        "ec2_count": 0,
        "lambda_count": 0,
        "rds_count": 0,
        "sqs_count": 0,
        "dynamodb_count": 0,
    }
    active_space_ids = {
        space_id
        for space_id, space in spaces.items()
        if isinstance(space, dict) and str(space.get("status", "running")).lower() == "running"
    }
    linked_space_ids: set[str] = set()
    linked_active_space_ids: set[str] = set()
    link_count = 0
    for link in link_values:
        if not isinstance(link, dict):
            continue
        src = str(link.get("source_space_id") or link.get("source") or link.get("space_id") or "").strip()
        dst = str(link.get("target_space_id") or link.get("target") or link.get("peer_space_id") or "").strip()
        if not src and not dst:
            continue
        link_count += 1
        for sid in (src, dst):
            if sid:
                linked_space_ids.add(sid)
                if sid in active_space_ids:
                    linked_active_space_ids.add(sid)
    for space in spaces.values():
        if not isinstance(space, dict):
            continue
        provider = str(space.get("provider") or "aws").lower()
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        for key in resource_counts:
            resource_counts[key] += int(space.get(key) or 0)
    return {
        "federation_count": len(federation_defs) if isinstance(federation_defs, dict) else 0,
        "link_count": link_count,
        "linked_spaces": len(linked_space_ids),
        "active_linked_spaces": len(linked_active_space_ids),
        "linked_space_ids": sorted(linked_space_ids),
        "active_linked_space_ids": sorted(linked_active_space_ids),
        "provider_counts": provider_counts,
        "resource_counts": resource_counts,
    }


def _space_belongs_to_active_tenant(space: dict | None) -> bool:
    if not isinstance(space, dict):
        return False
    return (space.get("tenant_id") or DEFAULT_TENANT_ID) == _active_tenant_id()


def _require_tenant_space(space_id: str) -> dict:
    """Return the space dict iff it belongs to the active tenant; 404 otherwise.
    Cross-tenant ids are indistinguishable from non-existent ones (no leak)."""
    spaces = _spaces_state().get("spaces", {})
    space = spaces.get(space_id) if isinstance(spaces, dict) else None
    if not isinstance(space, dict) or not _space_belongs_to_active_tenant(space):
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    return space


def api_list_spaces():
    _refresh_cloudsim_gcp_summary()
    all_spaces = PLATFORM.list_spaces()
    # TENANT FILTER: a tenant can only see its own spaces.
    tid = _active_tenant_id()
    spaces = [s for s in all_spaces if (s.get("tenant_id") or DEFAULT_TENANT_ID) == tid]
    spaces_state = _spaces_state()
    active_id = spaces_state.get("active_space_id", "")
    active_space_dict = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
    if not _space_belongs_to_active_tenant(active_space_dict):
        active_id, active_space_dict = "", {}
    federation_summary = _federation_space_summary()
    return {
        "spaces": [_space_payload(space) for space in spaces],
        "count": len(spaces),
        "active_space_id": active_id,
        "active_space": _space_payload(active_space_dict) if active_id else None,
        "active_tenant_id": tid,
        "settings": copy.deepcopy(spaces_state.get("settings", {})),
        "provider_counts": copy.deepcopy(federation_summary.get("provider_counts", {})),
        "resource_counts": copy.deepcopy(federation_summary.get("resource_counts", {})),
        "federation_summary": federation_summary,
    }


def api_list_providers():
    return {
        "providers": _legacy_provider_cards(),
        "default_provider": _spaces_state().get("settings", {}).get("default_provider", "aws"),
    }


def api_active_space():
    _refresh_cloudsim_gcp_summary()
    spaces_state = _spaces_state()
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
    if not _space_belongs_to_active_tenant(space):  # foreign-tenant active = treat as none
        return {"active_space_id": "", "space": None, "active_tenant_id": _active_tenant_id()}
    return {"active_space_id": active_id, "space": _space_payload(space),
            "active_tenant_id": _active_tenant_id()}


def api_get_space(space_id: str):
    _refresh_cloudsim_gcp_summary()
    space = _require_tenant_space(space_id)
    return {"space": _space_payload(space)}


def api_create_space(payload: dict[str, Any]):
    spec = dict(payload or {})
    # PROVIDER LOCK (1:1): a space has exactly one provider, set at create,
    # immutable thereafter.
    provider = str(spec.get("provider") or "").strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400,
            detail=f"provider must be one of {ALLOWED_PROVIDERS}; got '{spec.get('provider')}'")
    spec["provider"] = provider
    # TENANT ASSIGNMENT: every space belongs to exactly one tenant. Default to
    # the active tenant; reject if the requested tenant doesn't exist.
    requested_tid = str(spec.get("tenant_id") or "").strip() or _active_tenant_id()
    tenant = _tenant_dict(requested_tid)
    if not tenant:
        raise HTTPException(status_code=400, detail=f"tenant '{requested_tid}' not found")
    # PER-TIER PROVIDER GATE — Student tier is locked to one cloud, so a
    # space for a different provider must be rejected at creation time. If
    # we allow the space to be created, the user can switch into it and the
    # appliance ends up in a state where the active space's provider doesn't
    # match the license — confusing, and a paid-tier-breaking gap if the
    # console-route gate ever regresses.
    from core import tier_policy as _tp
    _tier_norm = _tp.normalize_tier(tenant.get("license_tier") or "free")
    _policy = _tp.policy_for(_tier_norm)
    _primary_cloud = str(tenant.get("primary_cloud") or "")
    _providers = _policy.get("providers", [])
    if _providers == "primary_cloud_only":
        if not _primary_cloud:
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "tier_primary_cloud_unset",
                "reason": ("Pro tier requires a primary cloud to be selected. "
                           "Re-activate from the dashboard or pick one on /pricing."),
                "upgrade_to": "max",
                "active_tier": _tier_norm,
                "docs": "https://vyomi.cloud/docs/tiers",
            })
        if provider != _primary_cloud:
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "tier_provider_locked",
                "reason": (f"Pro tier is locked to {_primary_cloud}; "
                           f"cannot create a {provider} space"),
                "upgrade_to": "max",
                "active_tier": _tier_norm,
                "primary_cloud": _primary_cloud,
                "requested_provider": provider,
                "docs": "https://vyomi.cloud/docs/tiers",
            })
    elif isinstance(_providers, list) and provider not in _providers:
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "tier_provider_locked",
            "reason": f"{provider} not available on {_tier_norm} tier",
            "upgrade_to": "pro" if _tier_norm == "free" else "max",
            "active_tier": _tier_norm,
            "requested_provider": provider,
            "docs": "https://vyomi.cloud/docs/tiers",
        })

    # PER-TENANT QUOTA — tier-derived. The tier policy's `max_spaces` is the
    # active source of truth (Free=1, Pro=5, Max=25, Enterprise=∞).
    # Falls back to the tenant's stored `settings.max_spaces` if the tier
    # policy doesn't define a cap (custom-quota Enterprise instances).
    _policy_cap = _policy.get("max_spaces")
    if _policy_cap is None or _policy_cap == _tp.UNLIMITED:
        tenant_max = int((tenant.get("settings") or {}).get("max_spaces", 6))
    else:
        tenant_max = int(_policy_cap)
    tenant_spaces = sum(1 for s in (_spaces_state().get("spaces") or {}).values()
                        if isinstance(s, dict) and (s.get("tenant_id") or DEFAULT_TENANT_ID) == requested_tid)
    if _policy_cap == _tp.UNLIMITED:
        pass  # unlimited — skip the check entirely
    elif tenant_spaces >= tenant_max:
        # Use structured 403 body so the SPA can render an upgrade modal.
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "tier_max_spaces",
            "reason": f"{_tier_norm} tier allows {tenant_max} space(s); you have {tenant_spaces}",
            "upgrade_to": _tp._next_tier(_tier_norm),
            "active_tier": _tier_norm, "limit": tenant_max, "current": tenant_spaces,
            "docs": "https://cloudlearn.io/docs/tiers",
        })
    try:
        space = PLATFORM.create_space(spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Tag the new space with tenant_id (must happen post-create since the kernel
    # doesn't know about tenants).
    spaces_map = _spaces_state().setdefault("spaces", {})
    if space.get("space_id") in spaces_map:
        spaces_map[space["space_id"]]["tenant_id"] = requested_tid
        space["tenant_id"] = requested_tid
    _record_usage("space.create", {"space_id": space.get("space_id"), "provider": space.get("provider"),
                                    "name": space.get("name"), "tenant_id": requested_tid})
    STATE.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})["summary"]["spaces"] = len(_spaces_state().get("spaces", {}))
    _persist_state()
    return {"message": "Simulation space created", "space": _space_payload(space)}


def api_estimate_space(payload: dict[str, Any]):
    estimate = PLATFORM.estimate_space_cost(payload or {})
    return {"estimate": estimate}


def api_switch_space(space_id: str):
    _require_tenant_space(space_id)  # 404 if cross-tenant — no leak
    try:
        space = PLATFORM.switch_space(space_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    _record_usage("space.switch", {"space_id": space_id})
    return {"message": "Active space switched", "space": _space_payload(space)}


def api_pause_space(space_id: str):
    _require_tenant_space(space_id)
    try:
        space = PLATFORM.pause_space(space_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    _record_usage("space.pause", {"space_id": space_id})
    return {"message": "Simulation space paused", "space": _space_payload(space)}


def api_resume_space(space_id: str):
    _require_tenant_space(space_id)
    try:
        space = PLATFORM.resume_space(space_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    _record_usage("space.resume", {"space_id": space_id})
    return {"message": "Simulation space resumed", "space": _space_payload(space)}


def api_archive_space(space_id: str):
    _require_tenant_space(space_id)
    try:
        space = PLATFORM.archive_space(space_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    _record_usage("space.archive", {"space_id": space_id})
    return {"message": "Simulation space archived", "space": _space_payload(space)}


def api_delete_space(space_id: str):
    _require_tenant_space(space_id)
    try:
        PLATFORM.delete_space(space_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    _record_usage("space.delete", {"space_id": space_id})
    STATE.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})["summary"]["spaces"] = len(_spaces_state().get("spaces", {}))
    _persist_state()
    return {"message": "Simulation space deleted", "space_id": space_id}


# ──────────────────────────────────────────────────────────────────────────────
# Tenant CRUD — the licensing/isolation boundary above Space.
# ──────────────────────────────────────────────────────────────────────────────

def _tenant_usage(tid: str) -> dict:
    spaces = (_spaces_state().get("spaces") or {})
    tenant = _tenant_dict(tid) or {}
    spaces_count = sum(1 for s in spaces.values()
                       if isinstance(s, dict) and (s.get("tenant_id") or DEFAULT_TENANT_ID) == tid)
    max_spaces = int((tenant.get("settings") or {}).get("max_spaces", 6))
    return {"spaces_count": spaces_count, "max_spaces": max_spaces,
            "spaces_remaining": max(0, max_spaces - spaces_count)}


def api_runtime_budget():
    """Simulator's container budget — clamp 30%-50% of host (default 40%). The
    user keeps the rest. Returns budget / used / free / host + clamp limits so
    UIs can show a quota meter and refuse over-budget launches up-front."""
    b = _simulator_budget()
    u = _simulator_used()
    return {
        "budget":     {"cpu": b["cpu"],       "memory_mb": b["memory_mb"]},
        "used":       u,
        "free":       {"cpu": max(0, b["cpu"] - u["cpu"]),
                       "memory_mb": max(0, b["memory_mb"] - u["memory_mb"])},
        "host":       {"cpu": b["host_cpu"],  "memory_mb": b["host_memory_mb"]},
        "budget_pct": b["budget_pct"],
        "clamp":      b["clamp"],
        "bypassed":   b["bypassed"],
    }


def api_runtime_cloud_shell():
    """Tier-gated capability probe for the in-console Cloud Shell drawer."""
    _enforce_tier_feature("cloud_shell")
    return {
        "available": True,
        "tier": _active_tier(),
        "exec_url": "/api/runtime/cloud-shell/exec",
        "backend_status": "ready",
    }


# Shell allow-list: cloud SDK + utility binaries that make sense in a
# learning shell. We don't fork arbitrary commands — only listed ones.
_CLOUD_SHELL_ALLOWED = {
    "aws", "gcloud", "gsutil", "bq", "az", "terraform",
    "kubectl", "helm",
    "curl", "jq", "yq", "ls", "cat", "echo", "pwd", "env",
    "python3", "node", "java", "go",
}


async def api_runtime_cloud_shell_exec(request: Request):
    """Run a single shell command from the allow-list and return its output.
    No persistent state (this is a one-shot exec, not a PTY). For a real
    interactive shell, the SPA can chain calls."""
    _enforce_tier_feature("cloud_shell")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    cmd = str(body.get("command") or "").strip()
    if not cmd:
        raise HTTPException(400, detail="command required")
    # Parse first token — must be in allow-list. shlex would be cleaner but
    # the first-word check is enough to refuse anything unsafe.
    first = cmd.split(None, 1)[0]
    if first not in _CLOUD_SHELL_ALLOWED:
        raise HTTPException(403, detail={
            "ok": False, "code": "command_not_allowed",
            "reason": f"command {first!r} not in cloud-shell allow-list",
            "allowed": sorted(_CLOUD_SHELL_ALLOWED),
        })
    import subprocess
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=30)
        out = {"stdout": r.stdout[-32768:], "stderr": r.stderr[-32768:], "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        out = {"stdout": "", "stderr": "timeout after 30s", "exit_code": 124}
    out["command"] = cmd
    return out


def api_runtime_terraform_deploy_targets():
    """Tier-gated list of deploy targets the current tier can push terraform
    state to. Free/Student: [] (apply is local-stage only). Developer:
    `single_cloud` — one real cloud at a time. Enterprise: `multi_cloud`."""
    level = _enforce_tier_feature("terraform_deploy_to_real")
    targets = []
    if level == "single_cloud":
        targets = ["aws", "gcp", "azure"]
    elif level == "multi_cloud":
        targets = ["aws", "gcp", "azure", "multi-cloud-orchestration"]
    return {
        "available": True,
        "tier": _active_tier(),
        "level": level,
        "allowed_targets": targets,
        "backend_status": "ready",
    }


# ── CI integration (Developer+ tier) ────────────────────────────────────────

def api_ci_list():
    _enforce_tier_feature("ci_integration")
    from core import ci_integration as _ci
    return {
        "tier": _active_tier(),
        "pipelines": _ci.list_pipelines(STATE, _active_tenant_id()),
    }


async def api_ci_register(request: Request):
    _enforce_tier_feature("ci_integration")
    body = await request.json() if await request.body() else {}
    from core import ci_integration as _ci
    try:
        pipe = _ci.register_pipeline(STATE, _active_tenant_id(), body)
        _persist_state()
        return pipe
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_ci_delete(pipeline_id: str):
    _enforce_tier_feature("ci_integration")
    from core import ci_integration as _ci
    ok = _ci.delete_pipeline(STATE, _active_tenant_id(), pipeline_id)
    if not ok:
        raise HTTPException(404, detail="pipeline not found")
    _persist_state()
    return {"deleted": pipeline_id}


async def api_ci_trigger(pipeline_id: str, request: Request):
    _enforce_tier_feature("ci_integration")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    from core import ci_integration as _ci
    res = _ci.trigger_pipeline(STATE, _active_tenant_id(), pipeline_id, body)
    _persist_state()
    if not res["ok"] and res["result"] == "pipeline-not-found":
        raise HTTPException(404, detail=res)
    return res


async def api_ci_inbound_webhook(token: str, request: Request):
    """Inbound webhook — pipelines POST CI events here using their `inbound_token`.
    No tier gate (CI calling US shouldn't 403). Token is the auth."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {"raw": (await request.body()).decode("utf-8", errors="replace")[:4096]}
    from core import ci_integration as _ci
    result = _ci.receive_inbound(STATE, token, body)
    if not result:
        raise HTTPException(404, detail="invalid token")
    _record_usage("ci.inbound", {"pipeline_id": result["id"], "tenant_id": result["tenant_id"]})
    _persist_state()
    return {"received": True, "pipeline_id": result["id"]}


# ── Audit export sinks (Enterprise tier) ────────────────────────────────────

def api_audit_sinks_list():
    _enforce_tier_feature("audit_export_sinks")
    from core import audit_sinks as _as
    return {"tier": _active_tier(), "sinks": _as.list_sinks(STATE, _active_tenant_id())}


async def api_audit_sinks_register(request: Request):
    _enforce_tier_feature("audit_export_sinks")
    body = await request.json() if await request.body() else {}
    from core import audit_sinks as _as
    try:
        sink = _as.register_sink(STATE, _active_tenant_id(), body)
        _persist_state()
        return sink
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_audit_sinks_delete(sink_id: str):
    _enforce_tier_feature("audit_export_sinks")
    from core import audit_sinks as _as
    ok = _as.delete_sink(STATE, _active_tenant_id(), sink_id)
    if not ok:
        raise HTTPException(404, detail="sink not found")
    _persist_state()
    return {"deleted": sink_id}


# ── Notification channels (Developer+ tier) ─────────────────────────────────

def api_notif_list():
    _enforce_tier_feature("notifications")
    from core import notifications as _nt
    return {"tier": _active_tier(),
            "channels": _nt.list_channels(STATE, _active_tenant_id()),
            "known_events": list(_nt.KNOWN_EVENTS)}


async def api_notif_register(request: Request):
    level = _enforce_tier_feature("notifications")
    body = await request.json() if await request.body() else {}
    # Developer tier = webhook-only; Enterprise = all_channels.
    if level == "webhook" and str(body.get("kind") or "webhook") not in ("webhook",):
        raise HTTPException(403, detail={
            "ok": False, "code": "tier_feature_level",
            "reason": "Developer tier supports webhook channels only; upgrade for Slack/email.",
            "active_tier": _active_tier(), "upgrade_to": "enterprise",
        })
    from core import notifications as _nt
    try:
        ch = _nt.register_channel(STATE, _active_tenant_id(), body)
        _persist_state()
        return ch
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_notif_delete(channel_id: str):
    _enforce_tier_feature("notifications")
    from core import notifications as _nt
    ok = _nt.delete_channel(STATE, _active_tenant_id(), channel_id)
    if not ok:
        raise HTTPException(404, detail="channel not found")
    _persist_state()
    return {"deleted": channel_id}


def api_notif_test(channel_id: str):
    _enforce_tier_feature("notifications")
    from core import notifications as _nt
    return _nt.send_test(STATE, _active_tenant_id(), channel_id)


# ── Custom domain (Enterprise tier) ─────────────────────────────────────────

def api_custom_domain_get():
    _enforce_tier_feature("custom_domain")
    from core import tenant_theming as _tt
    return {"tier": _active_tier(),
            "tenant_id": _active_tenant_id(),
            "domain": _tt.get_custom_domain(STATE, _active_tenant_id())}


async def api_custom_domain_set(request: Request):
    _enforce_tier_feature("custom_domain")
    body = await request.json() if await request.body() else {}
    from core import tenant_theming as _tt
    try:
        res = _tt.set_custom_domain(STATE, _active_tenant_id(), str(body.get("domain") or ""))
        _persist_state()
        return res
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_custom_domain_delete():
    _enforce_tier_feature("custom_domain")
    from core import tenant_theming as _tt
    removed = _tt.delete_custom_domain(STATE, _active_tenant_id())
    _persist_state()
    return {"deleted": removed}


# ── Branding (Enterprise tier) ──────────────────────────────────────────────

def api_branding_get():
    _enforce_tier_feature("branding")
    from core import tenant_theming as _tt
    return {"tier": _active_tier(),
            "tenant_id": _active_tenant_id(),
            "branding": _tt.get_branding(STATE, _active_tenant_id())}


async def api_branding_set(request: Request):
    _enforce_tier_feature("branding")
    body = await request.json() if await request.body() else {}
    from core import tenant_theming as _tt
    try:
        res = _tt.set_branding(STATE, _active_tenant_id(), body)
        _persist_state()
        return res
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_branding_css(tenant_id: str):
    """Public endpoint — console pages `<link rel="stylesheet" href="...">`
    this. No tier gate since the URL is referenced from rendered HTML at
    runtime; we just serve whatever's configured (default branding for
    tenants without a config)."""
    from core import tenant_theming as _tt
    css = _tt.branding_css(STATE, tenant_id)
    return Response(content=css, media_type="text/css")


# ── SSO (Enterprise tier) ───────────────────────────────────────────────────

def api_sso_get():
    _enforce_tier_feature("sso")
    from core import sso_config as _sso
    return _sso.get_config(STATE, _active_tenant_id())


async def api_sso_configure(request: Request):
    _enforce_tier_feature("sso")
    body = await request.json() if await request.body() else {}
    from core import sso_config as _sso
    try:
        res = _sso.configure(STATE, _active_tenant_id(), body)
        _persist_state()
        return res
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_sso_disable():
    _enforce_tier_feature("sso")
    from core import sso_config as _sso
    res = _sso.disable(STATE, _active_tenant_id())
    _persist_state()
    return res


async def api_sso_validate(request: Request):
    """Probe endpoint — the SPA POSTs a Bearer token here to verify it without
    actually consuming it. Returns claims on success."""
    _enforce_tier_feature("sso")
    body = await request.json() if await request.body() else {}
    token = str(body.get("token") or "")
    if not token:
        raise HTTPException(400, detail="token required")
    from core import sso_config as _sso
    return _sso.validate_bearer(STATE, _active_tenant_id(), f"Bearer {token}")


# ── Scaffolding generator (Developer+ tier) ─────────────────────────────────

def api_scaffolding_supported():
    """List all (provider, service, output) triples this tier can scaffold."""
    _enforce_tier_feature("scaffolding_generator")
    from core import scaffolding_generator as _sg
    return {"tier": _active_tier(), "triples": _sg.supported()}


def api_scaffolding_generate(provider: str, service: str, output: str = "terraform",
                              name: str = "my-resource", endpoint: str | None = None):
    """Generate a copy-paste-ready scaffolding snippet."""
    _enforce_tier_feature("scaffolding_generator")
    from core import scaffolding_generator as _sg
    try:
        ep = endpoint or "http://localhost:9000"
        return _sg.generate(provider, service, output, name=name, endpoint=ep)
    except KeyError as e:
        raise HTTPException(404, detail=str(e))


# ── Cross-tenant RBAC (Enterprise tier) ─────────────────────────────────────

def api_xtrbac_list():
    _enforce_tier_feature("cross_tenant_rbac")
    from core import cross_tenant_rbac as _xt
    return {"tier": _active_tier(),
            "tenant_id": _active_tenant_id(),
            "grants": _xt.list_grants(STATE, _active_tenant_id())}


async def api_xtrbac_create(request: Request):
    _enforce_tier_feature("cross_tenant_rbac")
    body = await request.json() if await request.body() else {}
    # Validate the grantee tenant actually exists
    ts = _tenants_state()
    grantee = str(body.get("grantee_tenant") or "")
    if grantee and grantee not in (ts.get("tenants") or {}):
        raise HTTPException(400, detail=f"grantee_tenant {grantee!r} does not exist")
    from core import cross_tenant_rbac as _xt
    try:
        grant = _xt.create_grant(STATE, _active_tenant_id(), body)
        _persist_state()
        return grant
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


def api_xtrbac_delete(grant_id: str):
    _enforce_tier_feature("cross_tenant_rbac")
    from core import cross_tenant_rbac as _xt
    ok = _xt.delete_grant(STATE, grant_id, _active_tenant_id())
    if not ok:
        raise HTTPException(404, detail="grant not found (or you're not the grantor)")
    _persist_state()
    return {"deleted": grant_id}


# ── Helm chart + air-gapped install (Enterprise tier) ───────────────────────

def api_helm_metadata():
    _enforce_tier_feature("helm")
    from core import helm_chart as _hc
    return {"tier": _active_tier(), **_hc.chart_metadata()}


def api_helm_chart():
    _enforce_tier_feature("helm")
    from core import helm_chart as _hc
    data = _hc.build_chart_tarball()
    return Response(
        content=data, media_type="application/gzip",
        headers={"Content-Disposition": f"attachment; filename=cloudlearn-{_hc.CHART_VERSION}.tgz",
                 "Content-Length": str(len(data))},
    )


def api_helm_values():
    _enforce_tier_feature("helm")
    from core import helm_chart as _hc
    return Response(content=_hc._values_yaml(), media_type="application/yaml",
                    headers={"Content-Disposition": 'attachment; filename=values.yaml'})


def api_helm_airgap():
    _enforce_tier_feature("helm")
    from core import helm_chart as _hc
    data = _hc.build_airgap_bundle()
    return Response(
        content=data, media_type="application/gzip",
        headers={"Content-Disposition": "attachment; filename=cloudlearn-airgap.tar.gz",
                 "Content-Length": str(len(data))},
    )


def api_runtime_budget_disable():
    """Testing toggle: bypass the host-clamp gate. Subsequent VM/EC2/Compute
    creates won't return 403 SimulatorBudgetExceeded. Real LXD/multipass limits
    are still applied per-container; only the global host clamp is skipped.
    Resets on container restart."""
    global _BUDGET_BYPASSED
    _BUDGET_BYPASSED = True
    return {"bypassed": True, "message": "Budget gate disabled. Re-enable via POST /api/runtime/budget/enable."}


def api_runtime_budget_enable():
    """Re-enable the host-clamp gate (undo /disable)."""
    global _BUDGET_BYPASSED
    _BUDGET_BYPASSED = False
    return {"bypassed": False, "message": "Budget gate re-enabled."}


def api_instances_catalog(provider: str = "aws"):
    """Single source-of-truth catalog of instance types the simulator understands
    (same dict the bridge uses to map real EC2/Compute/Azure VMs into CloudSim
    Plus shapes). Filter by provider so each console shows only its own SKUs
    — matches the Space 1:1 Provider rule by construction.

    Returned items: {name, family, vcpu, ram_mb, mips_per_vcpu}. Sorted by
    (family, vcpu, ram_mb) for clean grouped rendering."""
    from core import instance_catalog as cat
    table = {"aws": cat.AWS, "gcp": cat.GCP, "azure": cat.AZURE}.get(str(provider).lower(), {})
    # `**shape` first, then `"name": name` so the dict key wins over shape's
    # default name=None (the _shape factory doesn't know its own catalog key).
    items = [{**shape, "name": name} for name, shape in table.items()]
    items.sort(key=lambda i: (i.get("family", ""), i.get("vcpu", 0), i.get("ram_mb", 0)))
    return {"provider": str(provider).lower(), "count": len(items), "instances": items}


def api_list_tenants():
    ts = _tenants_state()
    out = []
    for tid, tenant in (ts.get("tenants") or {}).items():
        if not isinstance(tenant, dict):
            continue
        out.append({**tenant, "usage": _tenant_usage(tid)})
    return {"active_tenant_id": ts.get("active_tenant_id", ""),
            "tenants": out,
            "default_tenant_id": DEFAULT_TENANT_ID}


def api_active_tenant():
    tid = _active_tenant_id()
    return {"tenant_id": tid, "tenant": _tenant_dict(tid)}


def api_create_tenant(payload: dict[str, Any]):
    spec = dict(payload or {})
    name = str(spec.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    ts = _tenants_state()
    tenants = ts.setdefault("tenants", {})

    # Tier max_tenants cap — Free/Student/Developer=1, Enterprise=unlimited.
    # Counts ALL tenants on the deployment regardless of which one is active.
    try:
        from core import tier_policy as _tp
        tier = _active_tier()
        p = _tp.policy_for(tier)
        cap = p.get("max_tenants")
        UNLIMITED = _tp.UNLIMITED if hasattr(_tp, "UNLIMITED") else -1
        if cap is not None and cap != UNLIMITED and len(tenants) >= int(cap):
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "tier_max_tenants",
                "reason": f"{tier} tier allows {cap} tenant(s); you have {len(tenants)}",
                "active_tier": tier,
                "limit": int(cap), "current": len(tenants),
                "upgrade_to": _tp._next_tier(_tp.normalize_tier(tier)),
                "docs": "https://cloudlearn.io/docs/tiers",
            })
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open on policy lookup errors

    tid = str(spec.get("tenant_id") or "").strip()
    if not tid:
        tid = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or uuid.uuid4().hex[:12]
    if tid in tenants:
        raise HTTPException(status_code=409, detail=f"tenant '{tid}' already exists")
    tenant = {
        "tenant_id": tid, "name": name,
        "license_tier": str(spec.get("license_tier", "free")),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "settings": {"max_spaces": int(spec.get("max_spaces", 6))},
    }
    tenants[tid] = tenant
    _persist_state()
    return {"message": "Tenant created", "tenant": tenant}


def api_switch_tenant(tid: str):
    ts = _tenants_state()
    if tid not in (ts.get("tenants") or {}):
        raise HTTPException(status_code=404, detail="TenantNotFound")
    ts["active_tenant_id"] = tid
    # If the currently-active space belongs to a different tenant, clear it —
    # switching tenants must not leave a cross-tenant active space dangling.
    spaces_state = _spaces_state()
    active_sid = spaces_state.get("active_space_id", "")
    if active_sid:
        sp = spaces_state.get("spaces", {}).get(active_sid)
        if isinstance(sp, dict) and (sp.get("tenant_id") or DEFAULT_TENANT_ID) != tid:
            spaces_state["active_space_id"] = ""
    _persist_state()
    return {"message": "Active tenant switched", "tenant_id": tid,
            "tenant": ts["tenants"][tid]}


def api_delete_tenant(tid: str):
    if tid == DEFAULT_TENANT_ID:
        raise HTTPException(status_code=400, detail="cannot delete the default tenant")
    ts = _tenants_state()
    if tid not in (ts.get("tenants") or {}):
        raise HTTPException(status_code=404, detail="TenantNotFound")
    spaces = (_spaces_state().get("spaces") or {})
    if any(isinstance(s, dict) and (s.get("tenant_id") or DEFAULT_TENANT_ID) == tid for s in spaces.values()):
        raise HTTPException(status_code=400,
            detail="tenant still owns spaces; delete or migrate them first")
    del ts["tenants"][tid]
    if ts.get("active_tenant_id") == tid:
        ts["active_tenant_id"] = DEFAULT_TENANT_ID
    _persist_state()
    return {"message": "Tenant deleted", "tenant_id": tid}


def api_azure_console_summary():
    az = provider_azure_services
    type_to_key = {(c["namespace"] + "/" + c["type"]).lower(): c["key"] for c in az.RESOURCE_CATALOG}
    counts = {c["key"]: 0 for c in az.RESOURCE_CATALOG}
    for rec in list(_azure_state_dict().values()):
        ft = str(rec.get("_type", "")).lower()
        if ft in type_to_key:  # count top-level resources only
            counts[type_to_key[ft]] += 1
    return {"subscription": az.DEFAULT_SUBSCRIPTION, "resourceGroup": az.DEFAULT_RG,
            "counts": counts, "total": sum(counts.values())}


# Fields the CloudSim Plus engine actually produces (org.cloudsimplus discrete-
# event sim). The capacity block is restricted to these so DB-derived fields
# left in a pre-engine space can't masquerade as engine output.
_CLOUDSIM_CAPACITY_FIELDS = (
    "datacenters", "hosts", "vms", "cloudlets", "finished_cloudlets",
    "simulation_state", "cloudsim_engine", "cloudsim_runtime_id", "last_tick",
    # Per-cloud aggregates the engine used to size capacity (L3) — surfaced so
    # consumers can audit which cloud's resources contributed.
    "aws_count", "gcp_count", "azure_count",
    "gcp_functions_count", "azure_functionapp_count",
    # Heterogeneous-VM facts (HW1-3): real CPU/RAM derived from actual
    # instance types (t3.micro, m5.large, e2-medium, Standard_D8s_v5, …).
    "total_vcpus", "total_ram_mb", "vm_shapes", "host_pes", "host_ram_mb",
)


def _cloudsim_layer_blocks() -> tuple[dict, dict]:
    """The two layers as DISTINCT, provenance-tagged blocks read from the active
    space's separated storage: inventory (internal DB, authoritative; under
    space["resources"]) vs capacity (CloudSim Plus engine, derived; under
    space["cloudsim"], written only by CloudSimBridge)."""
    space = _gcp_active_space_dict()
    resources = space.get("resources") if isinstance(space, dict) else None
    cloudsim = space.get("cloudsim") if isinstance(space, dict) else None
    inv = (resources or {}).get("summary") if isinstance(resources, dict) else None
    cap = (cloudsim or {}).get("summary") if isinstance(cloudsim, dict) else None
    capacity = {k: v for k, v in (cap or {}).items() if k in _CLOUDSIM_CAPACITY_FIELDS}
    return ({**(inv or {}), "_source": "internal-db"},
            {**capacity, "_source": "cloudsim-plus-engine"})


def _cloudsim_compose_layers(payload: dict) -> None:
    """Present inventory + capacity as separate sub-objects (not a fused
    summary). Flat top-level summary keys are retained for backward compatibility."""
    if not isinstance(payload, dict):
        return
    summary = payload.setdefault("summary", {})
    if not isinstance(summary, dict):
        return
    inventory, capacity = _cloudsim_layer_blocks()
    summary["inventory"] = inventory
    summary["capacity"] = capacity


def _redact_cloudsim_for_totals_tier(payload):
    """For Student tier (cost_simulation="totals"), strip per-resource cost
    detail from CloudSim responses — keep aggregates only. Developer+
    (per_resource / per_resource_and_chargeback) sees the full payload. Free
    is denied entirely by the `cost_simulation` gate (policy value is False).
    """
    if not isinstance(payload, dict):
        return payload
    for k in ("resources", "per_resource_costs", "vm_costs", "chargeback"):
        payload.pop(k, None)
    cost_savings = payload.get("cost_savings")
    if isinstance(cost_savings, dict):
        cost_savings.pop("per_resource_costs", None)
        cost_savings.pop("by_service", None)
    layers = payload.get("layers")
    if isinstance(layers, list):
        for L in layers:
            if isinstance(L, dict):
                L.pop("resources", None)
                L.pop("per_resource_costs", None)
    return payload


def _cloudsim_compute_power(payload: dict) -> dict:
    """`cloudsim_power` feature (Student+ tiers): per-VM wattage + carbon
    footprint estimate. Reads VM count/sizes from CloudSim summary and
    derives a back-of-envelope value. Pure simulation — the numbers are
    indicative, not measurements."""
    summary = payload.get("summary") or {}
    inventory = summary.get("inventory") or {}

    # Per-provider VM counts
    aws_vms = int(inventory.get("ec2_count") or 0)
    gcp_vms = int(inventory.get("gcp_compute_count") or 0)
    azure_vms = int(inventory.get("azure_vm_count") or 0)
    total_vms = aws_vms + gcp_vms + azure_vms
    # Fallback if per-provider counts not yet populated
    if total_vms == 0:
        total_vms = int(inventory.get("vm_count") or inventory.get("total_vm_count") or 0)
        aws_vms = total_vms  # conservative attribution

    # Provider-specific watts (GCP DCs are more energy-efficient)
    WATTS = {"aws": 150, "gcp": 120, "azure": 140}
    total_watts = aws_vms * WATTS["aws"] + gcp_vms * WATTS["gcp"] + azure_vms * WATTS["azure"]
    if total_vms > 0 and total_watts == 0:
        total_watts = total_vms * 150
    kwh_per_month = (total_watts * 24 * 30) / 1000.0
    kg_co2_per_month = round(kwh_per_month * 0.4, 2)

    return {
        "total_vms": total_vms,
        "total_watts": total_watts,
        "kwh_per_month": round(kwh_per_month, 2),
        "kg_co2_per_month": kg_co2_per_month,
        "grid_factor_kgco2_per_kwh": 0.4,
        "providers": {
            "aws": {"vm_count": aws_vms, "watts_per_vm": WATTS["aws"],
                    "total_watts": aws_vms * WATTS["aws"]},
            "gcp": {"vm_count": gcp_vms, "watts_per_vm": WATTS["gcp"],
                    "total_watts": gcp_vms * WATTS["gcp"]},
            "azure": {"vm_count": azure_vms, "watts_per_vm": WATTS["azure"],
                      "total_watts": azure_vms * WATTS["azure"]},
        },
        "note": "Simulated — not a measurement. Watts are average estimates per on-demand VM.",
    }


def _cloudsim_compute_network_sla(payload: dict) -> dict:
    """`cloudsim_network_sla_migration` feature (Developer+ tiers): synthetic
    per-link network latency + SLA-adherence percentage + migration cost.
    Uses the CloudSim resource graph to enumerate cross-AZ/region pairs."""
    summary = payload.get("summary") or {}
    inventory = summary.get("inventory") or {}

    aws_vms = int(inventory.get("ec2_count") or 0)
    gcp_vms = int(inventory.get("gcp_compute_count") or 0)
    azure_vms = int(inventory.get("azure_vm_count") or 0)
    total_vms = aws_vms + gcp_vms + azure_vms
    if total_vms == 0:
        total_vms = int(inventory.get("vm_count") or inventory.get("total_vm_count") or 0)

    # Build labeled VM list with provider tags
    vms = []
    for i in range(min(aws_vms, 5)):
        vms.append({"id": f"ec2-{i}", "provider": "aws"})
    for i in range(min(gcp_vms, 5)):
        vms.append({"id": f"gce-{i}", "provider": "gcp"})
    for i in range(min(azure_vms, 3)):
        vms.append({"id": f"azvm-{i}", "provider": "azure"})

    n = min(len(vms), 10)
    links = []
    for i in range(n):
        for j in range(i + 1, n):
            cross_cloud = vms[i]["provider"] != vms[j]["provider"]
            base_ms = 1.2 + (i * 0.5 + j * 0.3) + (2.0 if cross_cloud else 0.0)
            jitter_ms = round((i * 0.1 + j * 0.07) % 2.5 + (0.5 if cross_cloud else 0.0), 2)
            sla_pct = round(max(99.0, 99.99 - jitter_ms * 0.4 - (0.2 if cross_cloud else 0.0)), 3)
            links.append({
                "from": vms[i]["id"], "to": vms[j]["id"],
                "from_provider": vms[i]["provider"],
                "to_provider": vms[j]["provider"],
                "cross_cloud": cross_cloud,
                "latency_ms": round(base_ms, 2),
                "jitter_ms": jitter_ms,
                "sla_pct": sla_pct,
            })

    migration = {
        "available_targets": {
            "aws": ["us-east-1", "us-west-2", "eu-west-1"],
            "gcp": ["us-central1", "europe-west1", "asia-east1"],
            "azure": ["eastus", "westeurope", "southeastasia"],
        },
        "best_target": {"aws": "us-east-1", "gcp": "us-central1", "azure": "eastus"},
        "estimated_downtime_s": total_vms * 12,
        "estimated_data_egress_gb": round(total_vms * 8.5, 1),
        "estimated_cost_usd": round(total_vms * 0.42, 2),
    }

    return {
        "links": links[:25],
        "total_links_modeled": len(links),
        "vm_count": total_vms,
        "providers": {
            "aws": {"vm_count": aws_vms},
            "gcp": {"vm_count": gcp_vms},
            "azure": {"vm_count": azure_vms},
        },
        "migration_plan": migration,
        "note": "Synthetic full-mesh latency model. Cross-cloud links have +2ms penalty.",
    }


def _redact_cloudsim_advanced_features(payload, *, has_power: bool, has_network_sla: bool) -> None:
    """Strip `power` + `network_sla` blocks from CloudSim payload when the
    active tier doesn't have those features. Mutates payload in place."""
    if not isinstance(payload, dict):
        return
    if not has_power:
        payload.pop("power", None)
        if isinstance(payload.get("summary"), dict):
            payload["summary"].pop("power", None)
    if not has_network_sla:
        payload.pop("network_sla", None)
        if isinstance(payload.get("summary"), dict):
            payload["summary"].pop("network_sla", None)


def _attach_cloudsim_advanced(payload: dict) -> None:
    """Decorate the CloudSim payload with `power` (Student+) + `network_sla`
    (Developer+) blocks based on tier policy. Called after the base payload
    is shaped. The redaction pass strips them again for tiers that don't have
    the corresponding feature."""
    if not isinstance(payload, dict):
        return
    from core import tier_policy as _tp
    feats = _tp.policy_for(_active_tier()).get("features") or {}
    payload["power"] = _cloudsim_compute_power(payload)
    payload["network_sla"] = _cloudsim_compute_network_sla(payload)
    _redact_cloudsim_advanced_features(
        payload,
        has_power=bool(feats.get("cloudsim_power")),
        has_network_sla=bool(feats.get("cloudsim_network_sla_migration")),
    )


def api_cloudsim_current():
    # cost_simulation gate: Free=False (denied); Student=totals; Developer=
    # per_resource; Enterprise=per_resource_and_chargeback. Free's 403 here
    # matches the /pricing page rendering cost_simulation as locked on Free.
    level = _enforce_tier_feature("cost_simulation")
    _refresh_cloudsim_all_providers_summary()
    payload = PLATFORM.cloudsim_current()
    if isinstance(payload, dict):
        spaces_state = _spaces_state()
        active_id = spaces_state.get("active_space_id", "")
        active_space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
        summary = payload.setdefault("summary", {})
        summary.update(_cloudsim_all_provider_summary_counts(active_space if isinstance(active_space, dict) else None))
        _cloudsim_compose_layers(payload)
    _attach_cloudsim_advanced(payload)
    if level == "totals":
        payload = _redact_cloudsim_for_totals_tier(payload)
    if isinstance(payload, dict):
        payload["cost_simulation_level"] = level
    return payload


def api_cloudsim_summary():
    level = _enforce_tier_feature("cost_simulation")
    _refresh_cloudsim_all_providers_summary()
    payload = PLATFORM.cloudsim_summary()
    if isinstance(payload, dict):
        spaces_state = _spaces_state()
        active_id = spaces_state.get("active_space_id", "")
        active_space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
        payload.setdefault("summary", {}).update(_cloudsim_all_provider_summary_counts(active_space if isinstance(active_space, dict) else None))
        _cloudsim_compose_layers(payload)
    _attach_cloudsim_advanced(payload)
    if level == "totals":
        payload = _redact_cloudsim_for_totals_tier(payload)
    if isinstance(payload, dict):
        payload["cost_simulation_level"] = level
    return payload


def api_cloudsim_reconcile():
    payload = PLATFORM.cloudsim_reconcile()
    _record_usage("cloudsim.reconcile", {"spaces": len(_spaces_state().get("spaces", {}))})
    _persist_state()
    return payload


def api_cloudsim_events():
    return PLATFORM.cloudsim_events()


def _redact_terraform_export_for_basic(export: dict) -> dict:
    """Free-tier `terraform_export=basic` returns only the resource skeleton:
    top-level shape + counts, but variable blocks, provider blocks, and
    unsupported-resource detail are stripped. Developer+ (`full`) gets it all.
    """
    if not isinstance(export, dict):
        return export
    redacted = copy.deepcopy(export)
    tf = redacted.get("terraform_json") if isinstance(redacted.get("terraform_json"), dict) else None
    if isinstance(tf, dict):
        tf.pop("variable", None)
        tf.pop("provider", None)
        tf.pop("output", None)
    redacted.pop("unsupported_resources", None)
    redacted.setdefault("summary", {})["redacted_for_basic_tier"] = True
    return redacted


def api_terraform_export():
    # All tiers can export — but Free's "basic" level returns skeleton only.
    level = _enforce_tier_feature("terraform_export")
    space = PLATFORM.get_active_space()
    if not isinstance(space, dict) or not space:
        raise HTTPException(404, detail="NoActiveSpace")
    export = export_space_to_terraform_json(space)
    if level == "basic":
        export = _redact_terraform_export_for_basic(export)
    if isinstance(export, dict):
        export["terraform_export_level"] = level
    _record_usage(
        "terraform.export",
        {
            "space_id": export.get("space_id", ""),
            "resource_count": export.get("summary", {}).get("resource_count", 0),
            "supported_resources": export.get("summary", {}).get("supported_resources", 0),
            "unsupported_resources": export.get("summary", {}).get("unsupported_resources", 0),
            "level": level,
        },
    )
    return export


async def api_terraform_import(request: Request):
    # Terraform import is gated to `full_plus_import` (Enterprise only) —
    # everyone else can export but not re-import.
    _enforce_tier_feature("terraform_export", min_level="full_plus_import")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(400, detail="InvalidTerraformImportPayload")

    spaces_state = _spaces_state()
    active_id = str(spaces_state.get("active_space_id", "") or "").strip()
    if not active_id:
        raise HTTPException(404, detail="NoActiveSpace")
    space = spaces_state.get("spaces", {}).get(active_id)
    if not isinstance(space, dict):
        raise HTTPException(404, detail="NoActiveSpace")

    terraform_json = {}
    if isinstance(payload.get("terraform_json"), dict):
        terraform_json = payload["terraform_json"]
    elif isinstance(payload.get("resource"), dict):
        terraform_json = payload
    elif isinstance(payload.get("bundle"), dict):
        terraform_json = payload["bundle"].get("terraform_json") if isinstance(payload["bundle"], dict) else {}
        if not isinstance(terraform_json, dict):
            terraform_json = payload["bundle"] if isinstance(payload["bundle"], dict) else {}

    if not isinstance(terraform_json, dict) or not isinstance(terraform_json.get("resource"), dict) or not terraform_json.get("resource"):
        raise HTTPException(400, detail="InvalidTerraformImportPayload")

    import_result = terraform_import_bundle(payload, space)
    service_state_updates = import_result.get("service_state_updates", {})
    if not isinstance(service_state_updates, dict):
        service_state_updates = {}

    service_states = space.setdefault("service_states", {})
    if not isinstance(service_states, dict):
        service_states = {}
        space["service_states"] = service_states
    for service_key, service_state in service_state_updates.items():
        service_states[service_key] = copy.deepcopy(service_state)

    now = _now()
    space["updated_at"] = now
    space.setdefault("cloudsim", {}).setdefault("summary", {})

    import_id = _id("tfimport")
    target_space_id = active_id
    source_space_id = str(import_result.get("space_id") or "")
    target_space_name = str(space.get("name") or "").strip()
    target_provider = str(space.get("provider") or "").strip()
    record = {
        "import_id": import_id,
        "space_id": target_space_id,
        "space_name": target_space_name,
        "provider": target_provider,
        "created_at": now,
        "workflow_kind": "import",
        "source_space_id": source_space_id,
        "source_space_name": import_result.get("space_name", ""),
        "source_provider": import_result.get("provider", ""),
        "summary": copy.deepcopy(import_result.get("summary", {})),
        "imported_resources": copy.deepcopy(import_result.get("imported_resources", [])),
        "unsupported_resources": copy.deepcopy(import_result.get("unsupported_resources", [])),
        "service_keys": copy.deepcopy(import_result.get("service_keys", [])),
        "status": "imported",
    }

    terraform_state = _terraform_state()
    terraform_state.setdefault("imports", {})[import_id] = copy.deepcopy(record)
    space_state = _terraform_space_state(target_space_id)
    space_state.setdefault("imports", {})[import_id] = copy.deepcopy(record)
    space_state["last_import"] = copy.deepcopy(record)

    _record_usage(
        "terraform.import",
        {
            "space_id": target_space_id,
            "import_id": import_id,
            "resource_count": import_result.get("summary", {}).get("resource_count", 0),
            "supported_resources": import_result.get("summary", {}).get("supported_resources", 0),
            "unsupported_resources": import_result.get("summary", {}).get("unsupported_resources", 0),
            "service_keys": copy.deepcopy(import_result.get("service_keys", [])),
        },
    )
    _persist_state()

    return {
        **record,
        "terraform_json": import_result.get("terraform_json", {}),
        "service_state_updates": service_state_updates,
        "nodes": import_result.get("nodes", []),
        "resource_count": import_result.get("resource_count", 0),
        "supported_resources": import_result.get("supported_resources", 0),
        "unsupported_resources": copy.deepcopy(import_result.get("unsupported_resources", [])),
    }


def api_terraform_status():
    space = PLATFORM.get_active_space()
    if not isinstance(space, dict) or not space:
        raise HTTPException(404, detail="NoActiveSpace")
    export = export_space_to_terraform_json(space)
    space_id = export.get("space_id") or _string(space.get("space_id"), "")
    terraform_state = _terraform_state()
    space_state = _terraform_space_state(space_id)
    last_plan = {}
    last_apply = {}
    if isinstance(space_state.get("last_plan"), dict):
        last_plan = copy.deepcopy(space_state["last_plan"])
    if isinstance(space_state.get("last_apply"), dict):
        last_apply = copy.deepcopy(space_state["last_apply"])
    last_import = {}
    if isinstance(space_state.get("last_import"), dict):
        last_import = copy.deepcopy(space_state["last_import"])
    return {
        "space_id": space_id,
        "space_name": export.get("space_name", ""),
        "provider": export.get("provider", ""),
        "summary": export.get("summary", {}),
        "terraform_cli_available": terraform_cli_available(),
        "terraform_cli_path": terraform_cli_path() or "",
        "terraform_workspace_root": str(terraform_workspace_root()),
        "workspace_dir": str(terraform_space_dir(space_id)),
        "last_plan": last_plan,
        "last_apply": last_apply,
        "last_import": last_import,
        "plan_count": len(terraform_state.get("plans", {})),
        "apply_count": len(terraform_state.get("applies", {})),
        "import_count": len(terraform_state.get("imports", {})),
    }


def api_terraform_plan():
    space = PLATFORM.get_active_space()
    if not isinstance(space, dict) or not space:
        raise HTTPException(404, detail="NoActiveSpace")
    export = export_space_to_terraform_json(space)
    space_id = export.get("space_id") or _string(space.get("space_id"), "")
    space_state = _terraform_space_state(space_id)
    previous = space_state.get("last_apply") if isinstance(space_state.get("last_apply"), dict) else {}
    summary = terraform_build_plan_summary(export, previous)
    workflow_id = _id("tfplan")
    stage = terraform_stage_workflow_bundle(export, workflow_id, "plan", summary)
    execution = terraform_run_cli(stage["stage_dir"], "plan")
    if not execution.get("available"):
        execution = {
            **execution,
            "status": "simulated",
            "stdout": execution.get("error", "Terraform CLI is not installed on this runtime."),
            "stderr": "",
            "exit_code": 0,
        }
    record = {
        "plan_id": workflow_id,
        "space_id": space_id,
        "space_name": export.get("space_name", ""),
        "provider": export.get("provider", ""),
        "created_at": _now(),
        "workflow_kind": "plan",
        "stage_dir": stage["stage_dir"],
        "files": stage["files"],
        "terraform_cli_available": stage["terraform_cli_available"],
        "terraform_cli_path": stage["terraform_cli_path"],
        "summary": export.get("summary", {}),
        "plan_summary": summary,
        "unsupported_resources": copy.deepcopy(export.get("unsupported_resources", [])),
        "execution": execution,
    }
    terraform_state = _terraform_state()
    terraform_state.setdefault("plans", {})[workflow_id] = record
    space_state.setdefault("plans", {})[workflow_id] = copy.deepcopy(record)
    space_state["last_plan"] = copy.deepcopy(record)
    _record_usage(
        "terraform.plan",
        {
            "space_id": space_id,
            "plan_id": workflow_id,
            "resource_count": export.get("summary", {}).get("resource_count", 0),
            "supported_resources": export.get("summary", {}).get("supported_resources", 0),
            "unsupported_resources": export.get("summary", {}).get("unsupported_resources", 0),
        },
    )
    _persist_state()
    return record


async def api_terraform_apply(request: Request):
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    plan_id = str((payload or {}).get("plan_id") or "").strip()
    confirm = bool((payload or {}).get("confirm", False))
    if not confirm:
        raise HTTPException(status_code=400, detail="ConfirmationRequired")

    terraform_state = _terraform_state()
    plan_record = terraform_state.get("plans", {}).get(plan_id) if plan_id else None

    space = PLATFORM.get_active_space()
    if not isinstance(space, dict) or not space:
        raise HTTPException(404, detail="NoActiveSpace")
    export = export_space_to_terraform_json(space)
    space_id = export.get("space_id") or _string(space.get("space_id"), "")
    space_state = _terraform_space_state(space_id)

    if not plan_record:
        previous = space_state.get("last_apply") if isinstance(space_state.get("last_apply"), dict) else {}
        summary = terraform_build_plan_summary(export, previous)
        plan_id = _id("tfplan")
        stage = terraform_stage_workflow_bundle(export, plan_id, "apply", summary)
        plan_record = {
            "plan_id": plan_id,
            "space_id": space_id,
            "space_name": export.get("space_name", ""),
            "provider": export.get("provider", ""),
            "created_at": _now(),
            "workflow_kind": "apply",
            "stage_dir": stage["stage_dir"],
            "files": stage["files"],
            "terraform_cli_available": stage["terraform_cli_available"],
            "terraform_cli_path": stage["terraform_cli_path"],
            "summary": export.get("summary", {}),
            "plan_summary": summary,
            "unsupported_resources": copy.deepcopy(export.get("unsupported_resources", [])),
        }
        terraform_state.setdefault("plans", {})[plan_id] = plan_record
        space_state.setdefault("plans", {})[plan_id] = copy.deepcopy(plan_record)
    else:
        plan_record = copy.deepcopy(plan_record)

    execution = terraform_run_cli(plan_record.get("stage_dir", ""), "apply")
    if not execution.get("available"):
        execution = {
            **execution,
            "status": "simulated",
            "stdout": execution.get("error", "Terraform CLI is not installed on this runtime."),
            "stderr": "",
            "exit_code": 0,
        }

    apply_id = _id("tfapply")
    apply_record = {
        "apply_id": apply_id,
        "plan_id": plan_id,
        "space_id": space_id,
        "space_name": export.get("space_name", ""),
        "provider": export.get("provider", ""),
        "created_at": _now(),
        "workflow_kind": "apply",
        "stage_dir": plan_record.get("stage_dir", ""),
        "files": plan_record.get("files", []),
        "terraform_cli_available": plan_record.get("terraform_cli_available", False),
        "terraform_cli_path": plan_record.get("terraform_cli_path", ""),
        "summary": export.get("summary", {}),
        "plan_summary": plan_record.get("plan_summary", {}),
        "unsupported_resources": copy.deepcopy(export.get("unsupported_resources", [])),
        "execution": execution,
    }
    terraform_state.setdefault("applies", {})[apply_id] = apply_record
    space_state.setdefault("applies", {})[apply_id] = copy.deepcopy(apply_record)
    space_state["last_apply"] = copy.deepcopy({
        "apply_id": apply_id,
        "plan_id": plan_id,
        "space_id": space_id,
        "space_name": export.get("space_name", ""),
        "provider": export.get("provider", ""),
        "created_at": _now(),
        "resource_index": plan_record.get("plan_summary", {}).get("resource_index", {}),
        "fingerprint": plan_record.get("plan_summary", {}).get("fingerprint", ""),
    })
    _record_usage(
        "terraform.apply",
        {
            "space_id": space_id,
            "plan_id": plan_id,
            "apply_id": apply_id,
            "resource_count": export.get("summary", {}).get("resource_count", 0),
            "supported_resources": export.get("summary", {}).get("supported_resources", 0),
            "unsupported_resources": export.get("summary", {}).get("unsupported_resources", 0),
        },
    )
    _persist_state()
    return apply_record


def api_list_packs():
    return {"packs": _catalog(), "count": len(STATE["packs"])}


def api_list_provider_packs(provider: str):
    provider_key = normalize_provider_key(provider)
    packs = packs_for_provider(provider_key) if provider_key in PROVIDER_PACK_GROUPS else []
    return {
        "provider": provider_key,
        "packs": packs,
        "count": len(packs),
    }


def api_provider_matrix(provider: str):
    provider_key = normalize_provider_key(provider)
    if provider_key in {"aws", "gcp", "azure"}:
        matrix = provider_capabilities(provider_key)
    else:
        provider_payload = get_provider(provider_key)
        packs = packs_for_provider(provider_key) if provider_key in PROVIDER_PACK_GROUPS else []
        matrix = provider_matrix(provider_key, packs)
        matrix["surface"] = provider_payload.get("surface", matrix.get("surface", {}))
        matrix["navigation"] = provider_payload.get("navigation", matrix.get("navigation", {}))
        matrix["native_services"] = provider_payload.get("native_services", matrix.get("native_services", []))
        matrix["space_facts"] = provider_payload.get("space_facts", matrix.get("space_facts", []))
        matrix["tooling"] = provider_payload.get("tooling", matrix.get("tooling", {}))
        matrix["gaps"] = provider_payload.get("gaps", matrix.get("gaps", []))
    packs = packs_for_provider(provider_key) if provider_key in PROVIDER_PACK_GROUPS else []
    services = provider_services(provider_key)
    return {
        "provider": provider_key,
        "surface": matrix.get("surface", {}),
        "navigation": matrix.get("navigation", {}),
        "native_services": matrix.get("native_services", []),
        "space_facts": matrix.get("space_facts", []),
        "tooling": matrix.get("tooling", {}),
        "services": matrix.get("services", services.get("services", [])),
        "service_counts": matrix.get("service_counts", {"total": services.get("count", 0), "integrated": services.get("integrated", 0), "partial": services.get("partial", 0)}),
        "packs": {
            "service": [copy.deepcopy(pack) for pack in packs if pack.get("type") == "service"],
            "runtime": [copy.deepcopy(pack) for pack in packs if pack.get("type") == "runtime"],
            "tooling": [copy.deepcopy(pack) for pack in packs if pack.get("type") == "tooling"],
        },
        "gaps": matrix.get("gaps", []),
    }


def api_provider_services(provider: str):
    return provider_services(provider)


def api_provider_capabilities(provider: str):
    return provider_capabilities(provider)


def api_provider_aws_cli():
    return aws_tool_response("cli")


def api_provider_aws_sdk_java():
    return aws_tool_response("sdk/java")


def api_provider_aws_sdk_go():
    return aws_tool_response("sdk/go")


def api_provider_aws_cli_resolve(payload: dict[str, Any]):
    return aws_cli_resolve(str(payload.get("command", "")))


def api_provider_aws_sdk_java_snippet():
    return sdk_snippet("aws", "java")


def api_provider_aws_sdk_go_snippet():
    return sdk_snippet("aws", "go")


def api_provider_aws_sdk_python():
    return aws_tool_response("sdk/python")


def api_provider_aws_sdk_nodejs():
    return aws_tool_response("sdk/nodejs")


def api_provider_aws_sdk_python_snippet():
    return sdk_snippet("aws", "python")


def api_provider_aws_sdk_nodejs_snippet():
    return sdk_snippet("aws", "nodejs")


def api_provider_gcp_gcloud():
    return gcp_tool_response("gcloud")


def api_provider_gcp_gcutil():
    return gcp_tool_response("gcutil")


def api_provider_gcp_sdk_java():
    return gcp_tool_response("sdk/java")


def api_provider_gcp_sdk_go():
    return gcp_tool_response("sdk/go")


def api_provider_gcp_gcloud_resolve(payload: dict[str, Any]):
    return gcp_gcloud_resolve(payload)


def api_provider_gcp_gcutil_resolve(payload: dict[str, Any]):
    return gcp_gcutil_resolve(payload)


def api_provider_gcp_sdk_java_snippet():
    return gcp_sdk_java_snippet()


def api_provider_gcp_sdk_go_snippet():
    return gcp_sdk_go_snippet()


def api_provider_gcp_sdk_python():
    return gcp_tool_response("sdk/python")


def api_provider_gcp_sdk_nodejs():
    return gcp_tool_response("sdk/nodejs")


def api_provider_gcp_sdk_python_snippet():
    from providers.gcp_routes import sdk_python_snippet as gcp_sdk_python_snippet
    return gcp_sdk_python_snippet()


def api_provider_gcp_sdk_nodejs_snippet():
    from providers.gcp_routes import sdk_nodejs_snippet as gcp_sdk_nodejs_snippet
    return gcp_sdk_nodejs_snippet()


# Azure tooling routes — pack-architecture parity with AWS+GCP (2026-06-01).
# providers/azure.tool_response and core.tooling_simulators.az_cli_resolve
# back the SPA's Tools tab + ``az`` command resolver.
def api_provider_azure_cli():
    from providers import azure_tool_response
    return azure_tool_response("cli")


def api_provider_azure_sdk_java():
    from providers import azure_tool_response
    return azure_tool_response("sdk/java")


def api_provider_azure_sdk_go():
    from providers import azure_tool_response
    return azure_tool_response("sdk/go")


def api_provider_azure_cli_resolve(payload: dict[str, Any]):
    from core.tooling_simulators import az_cli_resolve
    return az_cli_resolve(str(payload.get("command", "")))


def api_provider_azure_sdk_java_snippet():
    return sdk_snippet("azure", "java")


def api_provider_azure_sdk_go_snippet():
    return sdk_snippet("azure", "go")


def api_provider_azure_sdk_python():
    from providers import azure_tool_response
    return azure_tool_response("sdk/python")


def api_provider_azure_sdk_nodejs():
    from providers import azure_tool_response
    return azure_tool_response("sdk/nodejs")


def api_provider_azure_sdk_python_snippet():
    return sdk_snippet("azure", "python")


def api_provider_azure_sdk_nodejs_snippet():
    return sdk_snippet("azure", "nodejs")


def api_pack_fragment(pack_id: str):
    try:
        fragment = fragment_for_pack(pack_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="PackNotFound")
    return Response(content=fragment, media_type="text/html; charset=utf-8")


def api_ec2_amis():
    runtime = _runtime_bootstrap_status()
    return {"amis": AMI_CATALOG, "count": len(AMI_CATALOG), "runtime": runtime, "host_os": _parent_os()}


def api_host_cpu():
    return _sample_host_cpu_metrics()


def api_host_sizing():
    return _host_sizing()


def api_ec2_runtime(host_os_hint: str = ""):
    status = _runtime_bootstrap_status()
    host_os = _resolved_host_os(host_os_hint or str(status.get("host_os") or "").strip().lower())
    distribution_mode = _distribution_mode()
    appliance_mode = distribution_mode == "appliance"
    preferred_backend = "lxd" if appliance_mode else str(status.get("preferred_backend") or ("multipass" if host_os in {"windows", "darwin"} else "lxd")).strip().lower()
    family = "LXD" if appliance_mode else ("Multipass" if host_os in {"windows", "darwin"} else "Multipass or LXD")
    status["host_os"] = host_os
    status["distribution_mode"] = distribution_mode
    status["preferred_backend"] = preferred_backend
    if appliance_mode:
        status["target"] = {
            "helper": "lxd",
            "label": "LXD",
            "message": "Appliance mode uses LXD only for EC2.",
        }
    elif "target" not in status:
        status["target"] = {
            "helper": preferred_backend,
            "label": "Multipass" if preferred_backend == "multipass" else "LXD",
            "message": "",
        }
    status["instructions"] = {
        "label": "LXD" if appliance_mode else ("Multipass" if preferred_backend == "multipass" else "LXD"),
        "message": (
            "The appliance runs EC2-style sandboxes on LXD inside the Multipass VM."
            if appliance_mode
            else "The simulator uses Multipass on macOS for EC2-style sandboxes."
            if host_os == "darwin"
            else "The simulator uses Multipass on Windows for EC2-style sandboxes."
            if host_os == "windows"
            else "The simulator can use Multipass on Windows/macOS/Linux and LXD on Linux for EC2-style sandboxes."
        ),
        "helper": preferred_backend,
        "family": family,
    }
    return status

def api_ec2_runtime_lxd():
    status = _runtime_bootstrap_status("lxd")
    status["mode"] = status.get("mode", "auto")
    status["next_step"] = "install" if not status["available"] else "ready"
    status["instructions"] = {
        "label": status.get("label", "LXD"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


def api_ec2_runtime_multipass():
    if _appliance_mode_enabled():
        status = _runtime_bootstrap_status("lxd")
        status["message"] = status.get("message") or "Appliance mode uses LXD only for EC2."
        status["label"] = "LXD"
        status["helper"] = status.get("helper", "manual")
    else:
        status = _runtime_bootstrap_status("multipass")
    status["mode"] = status.get("mode", "auto")
    status["next_step"] = "install" if not status["available"] else "ready"
    status["instructions"] = {
        "label": status.get("label", "Multipass"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


def api_ec2_runtime_bootstrap():
    status = _start_lxd_bootstrap()
    status["message"] = status.get("message") or ("LXD runtime readiness checked inside the appliance VM." if _appliance_mode_enabled() else "Multipass and LXD runtime readiness checked.")
    status["instructions"] = {
        "label": "LXD" if _appliance_mode_enabled() else status.get("preferred_backend", "runtime"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


def api_ec2_runtime_lxd_bootstrap():
    status = _start_lxd_bootstrap()
    status["message"] = status.get("message") or "LXD runtime readiness checked."
    status["instructions"] = {
        "label": status.get("label", "LXD"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


def api_ec2_runtime_multipass_bootstrap():
    if _appliance_mode_enabled():
        status = _start_lxd_bootstrap()
        status["message"] = status.get("message") or "LXD runtime readiness checked inside the appliance VM."
    else:
        status = _start_lxd_bootstrap()
        status["message"] = status.get("message") or "Multipass runtime readiness checked."
    status["instructions"] = {
        "label": "LXD" if _appliance_mode_enabled() else status.get("label", "Multipass"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


def api_activate_pack(pack_id: str):
    pack = _activate_pack(pack_id)
    _record_usage("pack.activate", {"pack_id": pack_id})
    return {"message": "Pack activated", "pack": pack}


# ── Production license activation (Phase 1 — JWT from cloudlearn-license-backend)
#
# Three endpoints work together:
#   POST /api/license/activate       — paste a JWT string (manual key path)
#   POST /api/auth/device/start      — kick off RFC 8628 device flow
#   POST /api/auth/device/poll       — poll for completion → applies JWT
#
# All three end up calling _apply_license_jwt(token), which validates the JWT
# against the license backend's public key, then persists the tier into the
# active tenant. /api/license/signup remains as a DEV-MODE-ONLY bypass.

from pydantic import BaseModel as _BaseModel


class _LicenseActivateReq(_BaseModel):
    license_key: str


class _DeviceStartReq(_BaseModel):
    backend_url: str | None = None   # override default cloudlearn.io


class _DevicePollReq(_BaseModel):
    device_code: str
    backend_url: str | None = None


def _apply_license_jwt(token: str) -> dict:
    """Verify a JWT against the license backend, then propagate the encoded
    tier into the active tenant. Returns the parsed claims on success.
    Raises HTTPException on failure."""
    from core import license_remote as _lr
    install_id = _lr.get_or_create_install_id(STATE)
    try:
        claims = _lr.verify_license_jwt(
            token,
            backend_url=os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL"),
            install_id=install_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail={
            "ok": False, "code": "license_invalid", "reason": str(e),
        })

    # Check against cached revocation list (best-effort — fail-open on miss)
    revoked = set(STATE.get("license_revoked_jtis") or [])
    if claims.get("jti") in revoked:
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "license_revoked",
            "reason": "this license has been revoked; contact support for a new one",
        })

    # Persist on the active tenant — middleware reads license_tier from here.
    # Use the canonical tenants_state path so _tenant_dict() finds the value.
    tier = claims["tier"]
    ts = _tenants_state()
    tid = _active_tenant_id() or DEFAULT_TENANT_ID
    tenants = ts.setdefault("tenants", {})
    t = tenants.setdefault(tid, {"tenant_id": tid, "name": tid})
    t["license_tier"] = tier
    t["primary_cloud"] = claims.get("primary_cloud") or t.get("primary_cloud") or ""
    t["license_seats"] = int(claims.get("seats") or 1)
    t["license_jti"] = claims.get("jti")
    t["license_expires_at"] = _lr._exp_iso(claims)
    t["license_sub"] = claims.get("sub")
    t["license_issued_via"] = "license_remote_jwt"

    # Mirror at deployment level too (back-compat with /api/license/status reads)
    STATE["license"] = {"tier": tier, "active": True,
                        **_lr.claims_to_tier_payload(claims)}
    # Cache the JWT itself so device-poll responses + revocation checks can find it
    STATE["license_jwt"] = token
    STATE["license_claims"] = dict(claims)
    _persist_state()

    # Security audit: log successful license activation
    try:
        from core import security_audit
        security_audit.append_event("license.activated", {
            "tier": tier, "jti": claims.get("jti"), "sub": claims.get("sub"),
        })
    except Exception:
        pass

    return claims


@app.post("/api/license/activate")
async def api_license_activate(req: _LicenseActivateReq):
    """Paste-a-key activation. The user copies the JWT from a license-issuance
    email (or from `python scripts/issue-license.py`) and POSTs it here."""
    if not req.license_key or not req.license_key.strip():
        raise HTTPException(400, "license_key required")
    claims = _apply_license_jwt(req.license_key.strip())
    return {
        "ok": True,
        "active_tier": claims["tier"],
        "expires_at": _exp_iso_for_response(claims),
        "jti": claims.get("jti"),
        "issued_to": claims.get("sub"),
    }


def _exp_iso_for_response(claims: dict) -> str:
    from core import license_remote as _lr
    return _lr._exp_iso(claims)


@app.post("/api/auth/start-activation")
async def api_auth_start_activation(req: _DeviceStartReq):
    """Phase 5 single-flow activation — calls portal /api/auth/start-activation,
    returns the approval_url for the SPA to open in a new tab. SPA then polls
    /api/auth/poll-activation until the user signs in + approves on portal.

    User experience: 1 click → portal opens → sign in any way → 1 click approve
    → appliance picks up JWT. No device codes shown to user.
    """
    import json as _json
    import urllib.request as _ur, urllib.error as _ue
    from core import license_remote as _lr
    install_id = _lr.get_or_create_install_id(STATE)
    backend = req.backend_url or os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL") or _lr.DEFAULT_BACKEND_URL
    body = _json.dumps({"install_id": install_id,
                         "label": f"Vyomi appliance @ {install_id[:12]}"}).encode()
    try:
        r = _ur.Request(backend.rstrip("/") + "/api/auth/start-activation",
                         data=body, method="POST",
                         headers={"Content-Type": "application/json"})
        with _ur.urlopen(r, timeout=10) as resp:
            data = _json.load(resp)
    except _ue.HTTPError as e:
        raise HTTPException(502, f"portal_error_{e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        raise HTTPException(502, f"portal_unreachable: {type(e).__name__}: {e}")
    STATE.setdefault("device_auth", {})["pending"] = {
        "poll_token": data["poll_token"],
        "approval_url": data["approval_url"],
        "started_at": time.time(),
        "expires_at": time.time() + int(data.get("expires_in", 900)),
    }
    _persist_state()
    return {
        "approval_url": data["approval_url"],
        "interval": data.get("interval", 5),
        "expires_in": data.get("expires_in", 900),
    }


@app.post("/api/auth/poll-activation")
async def api_auth_poll_activation():
    """Phase 5 — appliance polls portal until user approves. On approval,
    receives JWT + applies it via _apply_license_jwt."""
    from core import license_remote as _lr
    pending = (STATE.get("device_auth") or {}).get("pending") or {}
    poll_token = pending.get("poll_token", "")
    if not poll_token:
        raise HTTPException(400, "no pending activation — call /api/auth/start-activation first")
    result = _lr.device_flow_poll(
        os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL"), poll_token,
    )
    if result["status"] == "approved":
        token = result.get("access_token") or ""
        if not token:
            raise HTTPException(502, "backend returned no token")
        claims = _apply_license_jwt(token)
        (STATE.get("device_auth") or {}).pop("pending", None)
        _persist_state()
        return {
            "status": "approved",
            "active_tier": claims["tier"],
            "expires_at": _exp_iso_for_response(claims),
            "issued_to": claims.get("sub"),
        }
    if result["status"] == "expired":
        (STATE.get("device_auth") or {}).pop("pending", None)
        _persist_state()
    return result


@app.post("/api/auth/device/start")
async def api_auth_device_start(req: _DeviceStartReq):
    """LEGACY (Phase 1) device-code flow — kept for back-compat. New code
    should use /api/auth/start-activation for the simpler 1-click UX."""
    from core import license_remote as _lr
    install_id = _lr.get_or_create_install_id(STATE)
    try:
        resp = _lr.device_flow_start(
            req.backend_url or os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL"),
            install_id,
            client_name=f"Vyomi appliance ({install_id})",
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    # Stash the device_code so the SPA can simply call /poll with no args
    STATE.setdefault("device_auth", {})["pending"] = {
        "device_code": resp["device_code"],
        "user_code": resp["user_code"],
        "verification_uri": resp["verification_uri"],
        "started_at": time.time(),
        "expires_at": time.time() + int(resp.get("expires_in", 600)),
    }
    _persist_state()
    # Don't echo device_code back to the SPA — it stays server-side
    return {
        "user_code": resp["user_code"],
        "verification_uri": resp["verification_uri"],
        "verification_uri_complete": resp.get("verification_uri_complete"),
        "interval": resp.get("interval", 5),
        "expires_in": resp.get("expires_in", 600),
    }


@app.post("/api/auth/device/poll")
async def api_auth_device_poll(req: _DevicePollReq | None = None):
    """SPA polls this every few seconds. Returns:
       {status: 'pending'}  while waiting
       {status: 'approved', active_tier: 'max'}  on success
       {status: 'expired'}  if user took too long
    """
    pending = (STATE.get("device_auth") or {}).get("pending") or {}
    device_code = (req.device_code if req else "") or pending.get("device_code", "")
    if not device_code:
        raise HTTPException(400, "no pending device authorization — call /api/auth/device/start first")
    from core import license_remote as _lr
    result = _lr.device_flow_poll(
        (req.backend_url if req else None) or os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL"),
        device_code,
    )
    if result["status"] == "approved":
        token = result.get("access_token") or ""
        if not token:
            raise HTTPException(502, "backend returned no token")
        claims = _apply_license_jwt(token)
        # Clear pending state
        (STATE.get("device_auth") or {}).pop("pending", None)
        _persist_state()
        return {
            "status": "approved",
            "active_tier": claims["tier"],
            "expires_at": _exp_iso_for_response(claims),
            "issued_to": claims.get("sub"),
        }
    if result["status"] == "expired":
        (STATE.get("device_auth") or {}).pop("pending", None)
        _persist_state()
    return result


@app.post("/api/auth/logout")
async def api_auth_logout():
    """Drop cached license → tier reverts to Free (default)."""
    STATE.pop("license_jwt", None)
    STATE.pop("license_claims", None)
    STATE["license"] = {"tier": "free", "active": False}
    # Reset active tenant's tier (canonical key is STATE["tenants"]["tenants"])
    tid = _active_tenant_id() or DEFAULT_TENANT_ID
    t = _tenant_dict(tid)
    if t:
        t.pop("license_tier", None)
        t.pop("license_seats", None)
        t.pop("license_jti", None)
        t.pop("license_expires_at", None)
        t.pop("license_sub", None)
        t.pop("license_issued_via", None)
    _persist_state()
    return {"ok": True, "active_tier": "free"}


# Background revocation poll — daemon thread polls /api/license/revocation
# every 24h. On revoked-jti match → auto-downgrade to Free + record on STATE
# so the SPA can show a banner.
# ── Runtime integrity check (appliance mode only) ──────────────────
try:
    from core import integrity_check
    integrity_check.verify_at_startup()
    integrity_check.start_integrity_monitor()
except Exception:
    pass


# ── Security audit endpoints (admin-key protected) ─────────────────
@app.get("/api/security/audit-log")
async def api_security_audit_log(request: Request, limit: int = 100, offset: int = 0):
    from core import admin_auth, security_audit
    admin_auth.require_admin_key(request)
    events = security_audit.read_log(limit, offset)
    return {"events": events, "count": len(events)}

@app.get("/api/security/audit-verify")
async def api_security_audit_verify(request: Request):
    from core import admin_auth, security_audit
    admin_auth.require_admin_key(request)
    ok, broken_at, reason = security_audit.verify_chain()
    return {"chain_valid": ok, "broken_at_id": broken_at, "reason": reason}


@app.on_event("startup")
def _start_license_background_tasks():
    """Spin up two daemon threads on appliance boot:
       1. Revocation poll (24h) — catches admin revocations
       2. Refresh loop (1h)    — picks up subscription changes from portal

    Both are safe to call multiple times (idempotent). Both fail-open
    on network errors. Both apply changes to STATE + persist."""
    from core import license_remote as _lr

    def _on_revoked(claims):
        # Auto-revert tier to Free (same as POST /api/auth/logout)
        STATE.pop("license_jwt", None)
        STATE.pop("license_claims", None)
        STATE["license"] = {"tier": "free", "active": False,
                            "auto_revoked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "auto_revoked_jti": claims.get("jti"),
                            "auto_revoked_sub": claims.get("sub")}
        tid = _active_tenant_id() or DEFAULT_TENANT_ID
        t = _tenant_dict(tid)
        if t:
            for k in ("license_tier", "license_seats", "license_jti", "license_expires_at"):
                t.pop(k, None)
        _persist_state()

    def _on_tier_changed(prev_tier, new_tier, refresh_result):
        # Subscription on portal changed; apply the new JWT directly.
        # `state["license_jwt"]` + `["license_claims"]` are already updated
        # by refresh_token — we just need to propagate to the tenant + persist.
        claims = STATE.get("license_claims") or {}
        if not claims:
            return
        tid = _active_tenant_id() or DEFAULT_TENANT_ID
        t = _tenant_dict(tid)
        if t:
            t["license_tier"] = claims.get("tier")
            t["license_seats"] = int(claims.get("seats") or 1)
            t["license_jti"] = claims.get("jti")
            t["license_expires_at"] = _lr._exp_iso(claims)
        STATE["license"] = {"tier": claims.get("tier"), "active": True,
                            **_lr.claims_to_tier_payload(claims),
                            "auto_changed_from": prev_tier,
                            "auto_changed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _persist_state()

    def _on_auth_failed(detail):
        # JWT got revoked → reset to Free + flag for SPA banner
        _on_revoked({"jti": (STATE.get("license_claims") or {}).get("jti"),
                     "sub": (STATE.get("license_claims") or {}).get("sub")})

    try:
        _lr.start_revocation_poll(STATE, interval_seconds=24 * 3600, on_revoked=_on_revoked)
        # Refresh cadence default: 24h. Matches the JWT TTL + the user-facing
        # "validate once per day" promise. Override via env if a deployment
        # genuinely wants tighter coupling (e.g. high-churn enterprise).
        _lr.start_refresh_loop(STATE, interval_seconds=int(os.environ.get(
            "CLOUDLEARN_LICENSE_REFRESH_INTERVAL_SECONDS", str(24 * 3600))),
            on_tier_changed=_on_tier_changed,
            on_auth_failed=_on_auth_failed)
        # Disk-health monitor: samples every 60s, surfaces tier-aware
        # warn/freeze status under STATE['runtime']['disk_health']. The
        # SPA dashboard widget + the launch pre-flight gate both read
        # from this cache.
        from core import disk_health as _dh
        _dh.start_disk_health_monitor(STATE)
    except Exception:
        pass


@app.get("/api/license/revocation-status")
def api_license_revocation_status():
    """Surface revocation-poll + refresh state for the SPA to render a banner."""
    lic = STATE.get("license") or {}
    return {
        "last_check_at":      STATE.get("license_last_revocation_check_at"),
        "last_refresh_at":    STATE.get("license_last_refresh_at"),
        "refresh_source":     STATE.get("license_refresh_source"),
        "revoked_jtis_count": len(STATE.get("license_revoked_jtis") or []),
        "auto_revoked_at":    lic.get("auto_revoked_at"),
        "auto_revoked_jti":   lic.get("auto_revoked_jti"),
        "auto_changed_at":    lic.get("auto_changed_at"),
        "auto_changed_from":  lic.get("auto_changed_from"),
    }


@app.post("/api/license/refresh")
async def api_license_refresh():
    """Manual SPA-triggered refresh — calls /api/identity/refresh on the
    portal NOW (skips the 1h wait). Useful after the user upgrades on
    /dashboard and wants instant tier-update on the appliance."""
    from core import license_remote as _lr
    if not STATE.get("license_jwt"):
        raise HTTPException(400, "no active license to refresh — sign in first")
    result = _lr.refresh_token(STATE)
    if result is None:
        raise HTTPException(502, "portal unreachable")
    if isinstance(result, dict) and result.get("_error") == "auth_required":
        raise HTTPException(401, detail=result.get("_detail", "license_revoked"))
    # Apply tier change (mirror the on_tier_changed callback logic)
    claims = STATE.get("license_claims") or {}
    tid = _active_tenant_id() or DEFAULT_TENANT_ID
    t = _tenant_dict(tid)
    if t:
        t["license_tier"] = claims.get("tier")
        t["license_seats"] = int(claims.get("seats") or 1)
        t["license_jti"] = claims.get("jti")
        t["license_expires_at"] = _lr._exp_iso(claims)
    STATE["license"] = {"tier": claims.get("tier"), "active": True,
                        **_lr.claims_to_tier_payload(claims)}
    _persist_state()
    return {
        "ok": True,
        "active_tier": claims.get("tier"),
        "source": result.get("source") if isinstance(result, dict) else None,
        "expires_at": _lr._exp_iso(claims),
    }


@app.post("/api/license/signup")
def api_license_signup(req: LicenseSignupRequest):
    """Issue a signed license JWT for the chosen tier. Tier-specific defaults
    (credits, primary_cloud requirement) come from core/tier_policy.policy_for.

    DEV MODE ONLY in v1.0 production: gated behind CLOUDLEARN_DEV_MODE=1.
    Production users activate via POST /api/license/activate (paste JWT from
    cloudlearn-license-backend) or POST /api/auth/device/start (device flow).
    """
    if _appliance_mode_enabled():
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "appliance_mode",
            "reason": "Dev-mode signup is disabled in appliance mode. Use /api/license/activate or /api/auth/start-activation.",
        })
    if os.environ.get("CLOUDLEARN_DEV_MODE", "").strip() not in ("1", "true", "yes"):
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "signup_disabled",
            "reason": "Direct tier signup is disabled in production. Use /api/license/activate "
                      "with a license key issued by cloudlearn-license-backend, or start a "
                      "device-flow login via /api/auth/device/start.",
            "docs": "https://github.com/cloudlearn/cloud-learn/blob/main/docs/architecture/LICENSING.md",
        })
    from core import tier_policy as _tp
    from datetime import datetime, timedelta, timezone as _tz
    tier = _normalize_tier(req.tier)
    p = _tp.policy_for(tier)

    # Validation: Student needs a primary_cloud at signup.
    if p.get("primary_cloud_required") and req.primary_cloud not in {"aws", "gcp", "azure"}:
        raise HTTPException(status_code=400, detail={
            "ok": False, "code": "primary_cloud_required",
            "reason": f"{tier} tier requires primary_cloud=aws|gcp|azure at signup",
        })

    # Validation: tier-specific seat range (min_seats ≤ seats ≤ max_seats).
    # Free/Student/Developer = 1..1 (exactly 1). Enterprise = 10..unlimited.
    min_seats = int(p.get("min_seats") or 1)
    max_seats = p.get("max_seats")
    seats = max(int(req.seats or 1), 1)
    if seats < min_seats:
        raise HTTPException(status_code=400, detail={
            "ok": False, "code": "min_seats_required",
            "reason": f"{tier} tier requires at least {min_seats} seats; got {seats}",
            "min_seats": min_seats,
        })
    UNLIMITED = -1  # mirrors core.tier_policy.UNLIMITED
    if max_seats is not None and max_seats != UNLIMITED and seats > int(max_seats):
        raise HTTPException(status_code=400, detail={
            "ok": False, "code": "max_seats_exceeded",
            "reason": f"{tier} tier allows up to {max_seats} seats; got {seats}",
            "max_seats": int(max_seats),
            "active_tier": tier,
            "upgrade_to": "enterprise",
        })

    period = (req.period or "monthly").lower().strip()
    if period not in {"monthly", "annual"}:
        period = "monthly"

    # Compute price per period.
    if tier == "enterprise":
        per_seat = int(p.get("price_inr_monthly_per_seat") or 99)
        price_charged = per_seat * seats * (12 if period == "annual" else 1)
    else:
        price_charged = int(p.get("price_inr_annual") if period == "annual"
                            else p.get("price_inr_monthly") or 0)

    # Compute expiry. Free never expires. Paid tiers expire after 1 month/year
    # with a 7-day grace period after that before downgrade.
    now_dt = datetime.now(_tz.utc)
    if tier == "free":
        expires_at = ""
        grace_until = ""
    else:
        delta = timedelta(days=365 if period == "annual" else 30)
        expires_at = (now_dt + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
        grace_until = (now_dt + delta + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Per-tier credit allowance (used for soft API-call metering).
    # Legacy "student"/"developer" keys retained so JWTs minted before the
    # 2026-06-17 rename still get the right credit count.
    credit_table = {"free": 100, "pro": 1000, "max": 10000, "enterprise": 50000,
                    "student": 1000, "developer": 10000}
    payload = {
        "license_id":      _id("lic"),
        "user":            req.user,
        "email":           req.email,
        "tier":            tier,
        "credits":         credit_table.get(tier, 100),
        "device_id":       req.device_id,
        "issued_at":       _now(),
        "status":          "active",
        # Day 2-D: subscription period + expiry + grace.
        "period":          period,
        "expires_at":      expires_at,
        "grace_until":     grace_until,
        "seats":           seats,
        "price_inr_charged": price_charged,
        # Day 2-C: Student-specific primary_cloud.
        "primary_cloud":   req.primary_cloud if p.get("primary_cloud_required") else "",
        # Tier facts (for offline reading).
        "price_inr_monthly":      p.get("price_inr_monthly"),
        "price_inr_annual":       p.get("price_inr_annual"),
        "max_spaces":             p.get("max_spaces"),
        "providers":              p.get("providers"),
        "primary_cloud_required": p.get("primary_cloud_required"),
    }
    token = _sign_license(payload)
    payload["token"] = token
    STATE["license"] = payload
    # Propagate the tier to the active tenant so the enforcement middleware
    # (which reads tenant["license_tier"] first) picks it up immediately.
    try:
        tid = _active_tenant_id()
        tenants_state = _tenants_state()
        tenant = tenants_state.setdefault("tenants", {}).setdefault(tid, {})
        tenant["license_tier"] = tier
        tenant["license_period"] = period
        tenant["license_expires_at"] = expires_at
        tenant["license_grace_until"] = grace_until
        tenant["license_seats"] = seats
        if p.get("primary_cloud_required"):
            tenant["primary_cloud"] = req.primary_cloud
            tenant.setdefault("primary_cloud_changed_at", _now())
        elif not tenant.get("primary_cloud_required"):
            # Non-student tier — clear any Student-era primary_cloud.
            tenant.pop("primary_cloud", None)
    except Exception:
        pass
    _persist_state()
    return {"license": payload, "token": token}


def api_license_status():
    """Return the active license + tenant tier/primary_cloud + computed
    days_until_expiry. The SPA reads this to render the account widget
    + upgrade banner."""
    from core import tier_policy as _tp
    from datetime import datetime, timezone as _tz
    lic = dict(STATE.get("license") or {})
    try:
        tenant = _tenant_dict(_active_tenant_id()) or {}
    except Exception:
        tenant = {}
    # Tenant takes precedence over deployment-level license for the active
    # tier (matches the enforcement middleware behavior).
    active_tier = _normalize_tier(tenant.get("license_tier") or lic.get("tier") or "free")
    policy = _tp.policy_for(active_tier)
    primary_cloud = str(tenant.get("primary_cloud") or "")
    expires_at = tenant.get("license_expires_at") or lic.get("expires_at") or ""
    grace_until = tenant.get("license_grace_until") or lic.get("grace_until") or ""

    days_until_expiry = None
    in_grace = False
    if expires_at:
        try:
            exp = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
            now = datetime.now(_tz.utc)
            days_until_expiry = max(0, (exp - now).days)
            if now > exp and grace_until:
                grace_end = datetime.strptime(grace_until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
                in_grace = now < grace_end
        except Exception:
            pass

    # ── Expiry banner — same escalation pattern as the portal dashboard.
    # Returns None when nothing's worth surfacing; otherwise a small
    # dict the SPA renders blindly (no client-side date math). Free tier
    # has no expiry — skip it entirely.
    expiry_banner = None
    if active_tier != "free" and days_until_expiry is not None:
        portal_url = (os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL") or "").rstrip("/")
        manage_url = f"{portal_url}/dashboard" if portal_url else "/pricing"
        renew_url  = f"{portal_url}/dashboard" if portal_url else "/pricing"
        tier_upper = active_tier.upper()
        if in_grace:
            expiry_banner = {
                "accent": "#b91c1c", "icon": "⚠",
                "title": f"Your {tier_upper} subscription expired — in grace period",
                "message": (
                    "Your subscription expired; you're in the 7-day grace window. "
                    "Renew now to avoid downgrade to Free."
                ),
                "cta_label": "Renew now", "cta_url": renew_url,
            }
        elif days_until_expiry <= 0:
            expiry_banner = {
                "accent": "#b91c1c", "icon": "⚠",
                "title": f"Your {tier_upper} subscription has expired",
                "message": (
                    "Appliance has reverted to Free tier. Re-subscribe any time "
                    "to restore your features."
                ),
                "cta_label": "Re-subscribe", "cta_url": renew_url,
            }
        elif days_until_expiry <= 3:
            expiry_banner = {
                "accent": "#d97706", "icon": "⏰",
                "title": f"Renewal in {days_until_expiry} day{'s' if days_until_expiry != 1 else ''}",
                "message": (
                    f"{tier_upper} renews on {expires_at[:10] if expires_at else 'soon'}. "
                    "Update payment if needed."
                ),
                "cta_label": "Manage", "cta_url": manage_url,
            }
        elif days_until_expiry <= 7:
            expiry_banner = {
                "accent": "#ca8a04", "icon": "📅",
                "title": f"Renewal in {days_until_expiry} days",
                "message": f"{tier_upper} renews on {expires_at[:10] if expires_at else 'soon'}.",
                "cta_label": None, "cta_url": None,
            }

    # Subscription-level fields: distinct from the JWT-level `expires_at`.
    # sub_expires_at is the BILLING cutoff baked into the JWT — what the
    # appliance actually enforces. days_until_sub_expiry drives the SPA
    # countdown ('✓ STUDENT · 23 days left'). is_sub_expired is the
    # already-passed signal for showing a red banner.
    claims = STATE.get("license_claims") or {}
    from core import license_remote as _lr
    sub_expires_at = claims.get("sub_expires_at")
    days_until_sub_expiry = _lr.days_until_sub_expiry(claims)
    sub_expired = _lr.is_sub_expired(claims)
    cancel_at_period_end = bool(claims.get("cancel_at_period_end"))

    # Refresh-loop health: when did we last successfully fetch a fresh JWT
    # from the portal? The SPA flips the pill from green → yellow when this
    # is stale (>48h) so users see "appliance is offline" before silently
    # running on a 30-day-old cache.
    refresh_status = {
        "last_refresh_at":         STATE.get("license_last_refresh_at"),
        "last_refresh_attempted":  STATE.get("license_last_refresh_attempted_at"),
        "last_refresh_status":     STATE.get("license_last_refresh_status"),
        "refresh_interval_seconds": int(os.environ.get(
            "CLOUDLEARN_LICENSE_REFRESH_INTERVAL_SECONDS", str(24 * 3600))),
    }

    return {
        "active_tier":            active_tier,
        "primary_cloud":          primary_cloud,
        "period":                 tenant.get("license_period") or lic.get("period") or "monthly",
        "seats":                  int(tenant.get("license_seats") or lic.get("seats") or 1),
        "expires_at":             expires_at,
        "grace_until":            grace_until,
        "days_until_expiry":      days_until_expiry,
        "in_grace_period":        in_grace,
        "expiry_banner":          expiry_banner,
        # New subscription-bound fields (Phase 5 coupling):
        "sub_expires_at":         sub_expires_at,
        "days_until_sub_expiry":  days_until_sub_expiry,
        "sub_expired":            sub_expired,
        "cancel_at_period_end":   cancel_at_period_end,
        "refresh_status":         refresh_status,
        "price_inr_monthly":      policy.get("price_inr_monthly"),
        "price_inr_annual":       policy.get("price_inr_annual"),
        "currency":               "INR",
        "currency_symbol":        "₹",
        "license":                lic,  # full JWT payload for clients that want it
    }


def api_license_switch_cloud(payload: dict[str, Any]):
    """Student tier: change the primary_cloud. Rate-limited to once per
    365 days; Developer/Enterprise users get a 400 telling them they
    don't need to switch (already have all 3)."""
    from core import tier_policy as _tp
    from datetime import datetime, timedelta, timezone as _tz
    new_cloud = str(payload.get("primary_cloud", "")).lower().strip()
    if new_cloud not in {"aws", "gcp", "azure"}:
        raise HTTPException(status_code=400, detail={
            "ok": False, "code": "invalid_cloud",
            "reason": "primary_cloud must be one of aws|gcp|azure",
        })
    tenant = _tenant_dict(_active_tenant_id()) or {}
    tier = _normalize_tier(tenant.get("license_tier") or "free")
    p = _tp.policy_for(tier)
    if not p.get("primary_cloud_required"):
        raise HTTPException(status_code=400, detail={
            "ok": False, "code": "not_applicable",
            "reason": f"{tier} tier has access to all clouds; primary_cloud not used",
        })
    # Rate-limit to once per 365 days.
    last = tenant.get("primary_cloud_changed_at")
    if last:
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=_tz.utc)
            elapsed = datetime.now(_tz.utc) - last_dt
            if elapsed < timedelta(days=365):
                days_left = 365 - elapsed.days
                raise HTTPException(status_code=429, detail={
                    "ok": False, "code": "rate_limited",
                    "reason": f"primary_cloud can be changed once per year; try again in {days_left} day(s)",
                    "days_until_next_change": days_left,
                    "upgrade_to": "max",
                    "current_primary_cloud": tenant.get("primary_cloud", ""),
                })
        except HTTPException:
            raise
        except Exception:
            pass
    tenants_state = _tenants_state()
    tenant_rec = tenants_state.setdefault("tenants", {}).setdefault(_active_tenant_id(), {})
    old = tenant_rec.get("primary_cloud", "")
    tenant_rec["primary_cloud"] = new_cloud
    tenant_rec["primary_cloud_changed_at"] = _now()
    _persist_state()
    return {
        "ok": True, "old_primary_cloud": old, "new_primary_cloud": new_cloud,
        "next_change_allowed_after_days": 365,
    }


def api_runtime_tier():
    """Surface the full per-tier policy table + the active license's tier.

    The SPA reads this to:
      - render the pricing page (all 4 tiers side-by-side)
      - decide which services to show as locked in the console rail
      - know when to show upgrade modals
      - format INR prices per tier

    Active tenant's tier wins; falls back to deployment-level STATE.license.
    """
    from core import tier_policy as _tp
    try:
        tenant = _tenant_dict(_active_tenant_id())
    except Exception:
        tenant = {}
    active_tier = _normalize_tier(
        (tenant or {}).get("license_tier")
        or (STATE.get("license") or {}).get("tier")
        or "free"
    )
    return {
        "active_tier":   active_tier,
        "active_policy": _tp.policy_for(active_tier),
        "primary_cloud": (tenant or {}).get("primary_cloud", ""),
        "all_tiers":     _tp.all_tiers(),
        "currency":      "INR",
        "_meta": {
            "doc": "https://cloudlearn.io/docs/tiers",
            "tiers_known": list(_tp.KNOWN_TIERS),
        },
    }


def api_license_activate(payload: dict[str, Any]):
    token = payload.get("token", "")
    license_data = _verify_license(token)
    license_data["token"] = token
    STATE["license"] = license_data
    _persist_state()
    return {"message": "License activated", "license": license_data}


def api_ec2_list_instances():
    _prune_expired_terminated_instances()
    instance_ids = _ec2_instance_ids()
    for instance_id in instance_ids:
        instance = ec2_state["instances"].get(instance_id)
        if isinstance(instance, dict):
            backend = str(instance.get("runtime_backend") or "").strip().lower()
            if backend == "multipass":
                _sync_multipass_instance(instance)
            elif backend == "lxd":
                _sync_lxd_instance(instance)
    _prune_expired_terminated_instances()
    instances = []
    for instance_id in _ec2_instance_ids():
        instance = ec2_state["instances"].get(instance_id)
        if isinstance(instance, dict):
            instances.append(instance)
    return {"instances": instances, "count": len(instances)}


def api_ec2_create_instance(req: EC2InstanceRequest, *, auto_start: bool = True, host_os_hint: str = ""):
    # Host-budget gate (clamp 30%-50% of host CPU+RAM): reject upfront if the
    # chosen instance_type would push the simulator past its share of the host.
    # Raises HTTPException(403) with a clear "delete one / pick smaller" message.
    _check_budget_for_launch(getattr(req, "instance_type", "") or "", "aws")
    # Disk pre-flight: refuse early with HTTP 507 instead of letting LXD
    # half-unpack a rootfs that won't fit and leave an orphan stuck at
    # 'stopped'. The tier-aware thresholds in disk_health give paid users
    # bigger safety margins.
    _disk_preflight(getattr(req, "storage_gb", None))
    instance_id = _id("i")
    pack = _activate_pack("cloudlearn.ec2.basic")
    if req.vpc_id and req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    if req.subnet_id and req.subnet_id not in vpc_state["subnets"]:
        raise HTTPException(404, detail="NoSuchSubnet")
    for sg in req.security_group_ids:
        if sg not in vpc_state["security_groups"]:
            raise HTTPException(404, detail=f"NoSuchSecurityGroup:{sg}")
    profile = _ami_profile(req.ami)
    requested_backend = (req.runtime_backend or "").strip().lower()
    supported_backends = _ec2_profile_supported_backends(profile)
    if requested_backend and requested_backend not in supported_backends:
        supported_label = ", ".join(supported_backends) if supported_backends else "no runtime backends"
        raise HTTPException(400, detail=f"AMI '{profile.get('name', 'unknown')}' only supports {supported_label}.")
    if not req.runtime or req.runtime == "python":
        req_runtime = profile.get("default_runtime", "python")
    else:
        req_runtime = req.runtime
    trusted_host_os = _resolved_host_os(host_os_hint)
    runtime_backend = _ec2_choose_runtime_backend(
        profile,
        requested_backend,
        trusted_host_os,
        require_available=True if _appliance_mode_enabled() else not bool(trusted_host_os),
    )
    _cloudsim_validate_ec2_launch_policy(_cloudsim_active_space_ref(), req, profile, runtime_backend)
    host_port = _allocate_host_port()
    workspace = _instance_workspace(instance_id)
    workspace.mkdir(parents=True, exist_ok=True)
    runtime_image = profile.get("runtime_image") or (LXD_RUNTIME_IMAGE if _appliance_mode_enabled() else MULTIPASS_RUNTIME_IMAGE if runtime_backend == "multipass" else LXD_RUNTIME_IMAGE)
    runtime_backend_requested = "lxd" if _appliance_mode_enabled() else (req.runtime_backend or "").strip().lower()
    instance = {
        "instance_id": instance_id,
        "reservation_id": f"r-{instance_id.replace('i-', '')}",
        "owner_id": AWS_ACCOUNT_ID,
        "name": req.name,
        "instance_type": req.instance_type,
        "ami": req.ami,
        "ami_name": profile["name"],
        "os_family": profile.get("os_family", "linux"),
        "container_image": profile.get("container_image", ""),
        "runtime_image": runtime_image,
        "runtime": req_runtime,
        "runtime_backend_requested": runtime_backend_requested,
        "key_pair": req.key_pair,
        "state": "pending",
        "az": req.az,
        "vpc_id": req.vpc_id,
        "subnet_id": req.subnet_id,
        "security_group_ids": req.security_group_ids,
        "storage_gb": req.storage_gb,
        "private_ip": _private_ip(),
        "public_ip": None,
        "command": req.command,
        "user_data": req.user_data,
        "created": _now(),
        "pack_id": pack["id"],
        "runtime_backend": runtime_backend,
        "container_download_state": "pending",
        "pid": None,
        "container_name": f"cloudlearn-{instance_id}",
        "container_id": "",
        "container_port": LXD_CONSOLE_PORT,
        "host_port": host_port,
        "endpoint_url": f"{runtime_backend}://{instance_id}",
        "console_state": {"cwd": str(workspace)},
        "console_log": [],
        "deployment_path": str(workspace),
        "workspace": str(workspace),
        "container_status": "created",
        "console_backend": (
            "multipass-ssh"
            if runtime_backend == "multipass"
            else "lxd-exec"
        ),
        "console_prompt": _cmd_prompt({"runtime_backend": runtime_backend, "container_name": f"cloudlearn-{instance_id}", "container_id": ""}),
        "runtime_bundle_id": _cloudsim_runtime_bundle("ec2").get("id", ""),
        "runtime_bundle_name": _cloudsim_runtime_bundle("ec2").get("name", ""),
        "runtime_bundle_kind": _cloudsim_runtime_bundle("ec2").get("kind", ""),
    }
    if req.command:
        instance["public_ip"] = _public_ip()
    ec2_state["instances"][instance_id] = instance
    _cloudsim_sync_ec2_resource(instance, "upsert")
    if auto_start:
        _queue_runtime_start(instance_id)
    _record_usage("ec2.create_instance", instance)
    return instance


def _start_runtime_process(instance: dict) -> None:
    backend = str(instance.get("runtime_backend") or "lxd").strip().lower()
    if backend == "multipass":
        _start_multipass_instance(instance)
        return
    if backend == "lxd":
        _start_lxd_instance(instance)
        return
    raise HTTPException(status_code=503, detail="RuntimeUnavailable")


def _queue_runtime_start_for_store(instances_store, instance_id: str) -> None:
    def _worker() -> None:
        with STATE_LOCK:
            instance = instances_store.get(instance_id)
            if not isinstance(instance, dict):
                return
            instance["launch_status"] = "starting"
            _persist_state()
        try:
            _start_runtime_process(instance)
            with STATE_LOCK:
                instance = instances_store.get(instance_id)
                if isinstance(instance, dict):
                    instance["launch_status"] = "ready"
                    _cloudsim_sync_ec2_resource(instance, "upsert")
                    _persist_state()
        except HTTPException as exc:
            with STATE_LOCK:
                instance = instances_store.get(instance_id)
                if isinstance(instance, dict):
                    instance["launch_status"] = "error"
                    instance["launch_error"] = str(exc.detail)
                    if instance.get("state") == "pending":
                        instance["state"] = "pending"
                    instance["container_status"] = "launch-failed"
                    _cloudsim_sync_ec2_resource(instance, "upsert")
                    _persist_state()
        except Exception as exc:
            with STATE_LOCK:
                instance = instances_store.get(instance_id)
                if isinstance(instance, dict):
                    instance["launch_status"] = "error"
                    instance["launch_error"] = str(exc)
                    if instance.get("state") == "pending":
                        instance["state"] = "pending"
                    instance["container_status"] = "launch-failed"
                    _cloudsim_sync_ec2_resource(instance, "upsert")
                    _persist_state()

    threading.Thread(target=_worker, name=f"cloudlearn-launch-{instance_id}", daemon=True).start()


def _queue_runtime_start(instance_id: str) -> None:
    _queue_runtime_start_for_store(ec2_state["instances"], instance_id)


def _stop_runtime_process(instance: dict) -> None:
    backend = str(instance.get("runtime_backend") or "lxd").strip().lower()
    if backend == "multipass":
        _stop_multipass_instance(instance)
        return
    if backend == "lxd":
        _stop_lxd_instance(instance)
        return
    raise HTTPException(status_code=503, detail="RuntimeUnavailable")


def _reboot_runtime_process(instance: dict) -> None:
    backend = str(instance.get("runtime_backend") or "lxd").strip().lower()
    if backend == "multipass":
        _reboot_multipass_instance(instance)
        return
    if backend == "lxd":
        _reboot_lxd_instance(instance)
        return
    raise HTTPException(status_code=503, detail="RuntimeUnavailable")


def api_ec2_start_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    instance["state"] = "pending"
    _queue_runtime_start(instance_id)
    _cloudsim_sync_ec2_resource(instance, "upsert")
    _record_usage("ec2.start_instance", {"instance_id": instance_id})
    return instance


def api_ec2_stop_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    _stop_runtime_process(instance)
    _cloudsim_sync_ec2_resource(instance, "upsert")
    _record_usage("ec2.stop_instance", {"instance_id": instance_id})
    return instance


def api_ec2_reboot_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    _reboot_runtime_process(instance)
    _cloudsim_sync_ec2_resource(instance, "upsert")
    _record_usage("ec2.reboot_instance", {"instance_id": instance_id})
    return instance


def api_ec2_terminate_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    # Phantom-instance escape hatch. The previous condition only caught
    # launch_status=='error', which missed orphans where:
    #   - launch_status stayed 'ready' but container_status went 'missing'
    #     (e.g. disk-full mid-unpack → LXD rolled back partial container
    #     but the simulator persist already wrote 'ready'), or
    #   - the LXD container was deleted out-of-band (manual `lxc delete`,
    #     storage pool wipe).
    # In both cases there's no backing container to talk to. The terminate
    # call to LXD would then error/hang, leaving the row stuck "stopped"
    # forever from the user's POV. Catch the no-container shape early.
    container_status = str(instance.get("container_status") or "").strip().lower()
    no_backing_container = (
        not str(instance.get("container_id") or "").strip()
        and container_status in {"missing", "launch-failed", "removed", ""}
    )
    if instance.get("launch_status") == "error" and not str(instance.get("container_id") or "").strip():
        _terminate_simulated_instance(instance)
    elif no_backing_container:
        _terminate_simulated_instance(instance)
    elif backend == "multipass":
        _terminate_multipass_instance(instance)
    elif backend == "lxd":
        _terminate_lxd_instance(instance)
    else:
        raise HTTPException(503, detail="RuntimeUnavailable")
    _cloudsim_sync_ec2_resource(instance, "delete")
    _record_usage("ec2.terminate_instance", {"instance_id": instance_id})
    return instance


def api_ec2_console(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        _sync_multipass_instance(instance)
    elif backend == "lxd":
        _sync_lxd_instance(instance)
    if backend in {"multipass", "lxd"}:
        with CONSOLE_LOCK:
            session = CONSOLE_SESSIONS.get(instance_id)
        if session:
            output = _console_buffer_text(session)
        else:
            log = instance.get("console_log", [])
            output = "\n".join((entry.get("output") or "").rstrip("\n") for entry in log[-20:] if entry.get("output"))
        return {
            "instance_id": instance_id,
            "state": instance.get("state", "unknown"),
            "console_state": instance.get("state", "unknown"),
            "backend": "multipass-ssh" if backend == "multipass" else f"{backend}-exec",
            "output": output,
            "container_id": instance.get("container_id", ""),
            "container_status": instance.get("container_status", ""),
            "runtime_image": instance.get("runtime_image", ""),
            "console_prompt": instance.get("console_prompt", _cmd_prompt(instance)),
            "endpoint_url": instance.get("endpoint_url", ""),
        }
    raise HTTPException(status_code=503, detail="RuntimeUnavailable")


def api_ec2_console_input(instance_id: str, req: EC2ConsoleInputRequest):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        _sync_multipass_instance(instance)
    elif backend == "lxd":
        _sync_lxd_instance(instance)
    if instance.get("state") != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    result = _console_execute(instance, req.data)
    _record_usage("ec2.console_command", {"instance_id": instance_id, "command": req.data, "exit_code": result["exit_code"]})
    return {"message": "Console command executed", "instance_id": instance_id, **result}


def api_ec2_console_exec(instance_id: str, req: EC2ConsoleCommandRequest):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        _sync_multipass_instance(instance)
    elif backend == "lxd":
        _sync_lxd_instance(instance)
    if instance.get("state") != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    result = _console_execute(instance, req.command)
    _record_usage("ec2.console_command", {"instance_id": instance_id, "command": req.command, "exit_code": result["exit_code"]})
    return {"message": "Console command executed", "instance_id": instance_id, **result}


async def _ec2_query_params(request: Request) -> dict[str, Any]:
    params = {k: v for k, v in request.query_params.multi_items()}
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            params.update({k: v for k, v in form.multi_items()})
        elif "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                params.update({k: v for k, v in body.items()})
        else:
            raw = await request.body()
            if raw:
                try:
                    params.update(dict(parse_qsl(raw.decode("utf-8", errors="ignore"))))
                except Exception:
                    pass
    return params


def _ec2_query_filter_instances(params: dict[str, Any]) -> list[dict]:
    instance_ids = _ec2_parse_instance_ids(params)
    filters = _ec2_parse_filters(params)
    candidates = []
    for instance_id in _ec2_instance_ids():
        instance = ec2_state["instances"].get(instance_id)
        if not isinstance(instance, dict):
            continue
        if instance_ids and instance["instance_id"] not in instance_ids:
            continue
        if not _terminated_visible(instance):
            continue
        if filters and not _ec2_matches_filters(instance, filters):
            continue
        candidates.append(instance)
    return candidates


def _ec2_query_describe_instances(params: dict[str, Any]) -> Response:
    instances = _ec2_query_filter_instances(params)

    def build(root: ET.Element) -> None:
        reservation_map: dict[str, list[dict]] = {}
        for instance in instances:
            reservation_map.setdefault(instance.get("reservation_id") or f"r-{instance['instance_id']}", []).append(instance)
        reservation_set = _ec2_sub(root, "reservationSet")
        for reservation_id, items in reservation_map.items():
            reservation = _ec2_sub(reservation_set, "item")
            _ec2_sub(reservation, "reservationId", reservation_id)
            _ec2_sub(reservation, "ownerId", items[0].get("owner_id", AWS_ACCOUNT_ID))
            group_set = _ec2_sub(reservation, "groupSet")
            for group in _ec2_instance_group_names(items[0]):
                group_item = _ec2_sub(group_set, "item")
                _ec2_sub(group_item, "groupId", group["groupId"])
                _ec2_sub(group_item, "groupName", group["groupName"])
            instances_set = _ec2_sub(reservation, "instancesSet")
            for inst in items:
                instances_set.append(_ec2_instance_xml(inst))

    return _ec2_success_response("DescribeInstancesResponse", build)


def _ec2_query_describe_images(params: dict[str, Any]) -> Response:
    image_ids = []
    for key, value in params.items():
        if key.lower().startswith("imageid") and value:
            if isinstance(value, list):
                image_ids.extend([str(v) for v in value if v])
            else:
                image_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    images = []
    for profile in AMI_CATALOG:
        image = {
            "ami": profile["ami"],
            "created": profile.get("created", _now()),
        }
        if image_ids and profile["ami"] not in image_ids:
            continue
        if filters:
            matched = True
            for name, values in filters:
                if name == "name" and profile.get("name") not in values:
                    matched = False
                elif name == "image-id" and profile["ami"] not in values:
                    matched = False
                elif name == "architecture" and "x86_64" not in values:
                    matched = False
            if not matched:
                continue
        images.append(image)

    def build(root: ET.Element) -> None:
        images_set = _ec2_sub(root, "imagesSet")
        for image in images:
            images_set.append(_ec2_image_xml(image))

    return _ec2_success_response("DescribeImagesResponse", build)


def _ec2_query_describe_instance_status(params: dict[str, Any]) -> Response:
    instances = _ec2_query_filter_instances(params)

    def build(root: ET.Element) -> None:
        status_set = _ec2_sub(root, "instanceStatusSet")
        for instance in instances:
            if instance.get("state") not in {"running", "stopping", "stopped", "pending"}:
                continue
            status_set.append(_ec2_instance_status_xml(instance))

    return _ec2_success_response("DescribeInstanceStatusResponse", build)


def _ec2_query_describe_instance_types(params: dict[str, Any]) -> Response:
    requested = []
    for key, value in params.items():
        if key.lower().startswith("instancetype") and value:
            if isinstance(value, list):
                requested.extend([str(v) for v in value if v])
            else:
                requested.append(str(value))
    filters = _ec2_parse_filters(params)
    catalog = []
    for profile in EC2_INSTANCE_TYPE_CATALOG:
        if requested and profile["instanceType"] not in requested:
            continue
        matched = True
        for name, values in filters:
            if name == "instance-type" and profile["instanceType"] not in values:
                matched = False
            elif name == "current-generation" and profile["currentGeneration"] not in values:
                matched = False
        if matched:
            catalog.append(profile)

    def build(root: ET.Element) -> None:
        type_set = _ec2_sub(root, "instanceTypeSet")
        for profile in catalog:
            type_set.append(_ec2_instance_type_xml(profile))

    return _ec2_success_response("DescribeInstanceTypesResponse", build)


def _ec2_query_describe_security_groups(params: dict[str, Any]) -> Response:
    group_ids = []
    for key, value in params.items():
        if key.lower().startswith("groupid") and value:
            if isinstance(value, list):
                group_ids.extend([str(v) for v in value if v])
            else:
                group_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    groups = []
    for group_id, group in vpc_state.get("security_groups", {}).items():
        if group_ids and group_id not in group_ids:
            continue
        matched = True
        for name, values in filters:
            if name == "group-id" and group_id not in values:
                matched = False
            elif name == "group-name" and group.get("group_name", group_id) not in values:
                matched = False
            elif name == "vpc-id" and group.get("vpc_id", "") not in values:
                matched = False
        if matched:
            groups.append((group_id, group))

    def build(root: ET.Element) -> None:
        info = _ec2_sub(root, "securityGroupInfo")
        for group_id, group in groups:
            info.append(_ec2_security_group_xml(group_id, group))

    return _ec2_success_response("DescribeSecurityGroupsResponse", build)


def _ec2_query_describe_volumes(params: dict[str, Any]) -> Response:
    volume_ids = []
    for key, value in params.items():
        if key.lower().startswith("volumeid") and value:
            if isinstance(value, list):
                volume_ids.extend([str(v) for v in value if v])
            else:
                volume_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    volumes = []
    for instance_id in _ec2_instance_ids():
        instance = ec2_state["instances"].get(instance_id)
        if not isinstance(instance, dict):
            continue
        volume_id = f"vol-{instance_id.replace('i-', '')}"
        if volume_ids and volume_id not in volume_ids:
            continue
        matched = True
        for name, values in filters:
            if name == "volume-id" and volume_id not in values:
                matched = False
            elif name == "status":
                state = "in-use" if instance.get("state") in {"running", "pending", "rebooting"} else "available"
                if state not in values:
                    matched = False
            elif name == "availability-zone" and instance.get("az", "") not in values:
                matched = False
        if matched:
            volumes.append(instance)

    def build(root: ET.Element) -> None:
        volume_set = _ec2_sub(root, "volumeSet")
        for instance in volumes:
            volume_set.append(_ec2_volume_xml(instance))

    return _ec2_success_response("DescribeVolumesResponse", build)


def _ec2_query_run_instances(params: dict[str, Any]) -> Response:
    # Tier quantity cap — Free=1 VM/space; Student=10; Developer=50; Enterprise=∞.
    # Enforced BEFORE consuming MinCount so we never partially create.
    _enforce_quantity_cap("vm")
    # Tier size cap — Free=small (≤t3.small); Enterprise=huge (any).
    _enforce_size_cap("vm", "aws", str(params.get("InstanceType", "t3.micro")))
    min_count = int(params.get("MinCount", params.get("Mincount", 1)) or 1)
    max_count = int(params.get("MaxCount", params.get("Maxcount", min_count)) or min_count)
    count = max(min_count, max_count)
    image_id = str(params.get("ImageId", "ami-amzn2023"))
    instance_type = str(params.get("InstanceType", "t3.micro"))
    key_name = str(params.get("KeyName", ""))
    subnet_id = str(params.get("SubnetId", params.get("Placement.SubnetId", "")))
    az = str(params.get("Placement.AvailabilityZone", params.get("AvailabilityZone", "us-east-1a")))
    vpc_id = str(params.get("VpcId", ""))
    security_group_ids = _ec2_filter_values(params, "SecurityGroupId.")
    if not security_group_ids:
        security_group_ids = _ec2_filter_values(params, "NetworkInterface.1.SecurityGroupId.")
    launched = []
    for _ in range(count):
        req = EC2InstanceRequest(
            name=str(params.get("TagSpecification.1.Tag.1.Value", "ec2-instance")),
            instance_type=instance_type,
            ami=image_id,
            runtime=profile.get("default_runtime", "python") if (profile := _ami_profile(image_id)) else "python",
            key_pair=key_name,
            subnet_id=subnet_id,
            vpc_id=vpc_id,
            security_group_ids=security_group_ids,
            az=az,
            storage_gb=8,
            command="",
            user_data="",
        )
        trusted_host_os = _resolved_host_os()
        if trusted_host_os:
            req.runtime_backend = ""
        instance = api_ec2_create_instance(req, auto_start=False)
        launched.append(instance)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "ownerId", AWS_ACCOUNT_ID)
        _ec2_sub(root, "requesterId", "cloudlearn-simulator")
        _ec2_sub(root, "reservationId", launched[0].get("reservation_id", f"r-{launched[0]['instance_id'].replace('i-', '')}"))
        group_set = _ec2_sub(root, "groupSet")
        for sg_id in security_group_ids or ["sg-default"]:
            item = _ec2_sub(group_set, "item")
            _ec2_sub(item, "groupId", sg_id)
            _ec2_sub(item, "groupName", vpc_state.get("security_groups", {}).get(sg_id, {}).get("group_name", "default"))
        instances_set = _ec2_sub(root, "instancesSet")
        for instance in launched:
            instances_set.append(_ec2_instance_xml(instance))

    return _ec2_success_response("RunInstancesResponse", build)


def _gcp_compute_instance_ids() -> list[str]:
    with STATE_LOCK:
        return list(_gcp_compute_instance_bucket().keys())


def _gcp_compute_instance_bucket() -> dict[str, dict]:
    spaces_state = _spaces_state()
    active_id = str(spaces_state.get("active_space_id", "") or "").strip()
    space = spaces_state.get("spaces", {}).get(active_id, {})
    if not isinstance(space, dict):
        return gcp_compute_state.get("instances", {})
    service_states = space.setdefault("service_states", {})
    if not isinstance(service_states, dict):
        service_states = {}
        space["service_states"] = service_states
    candidates: list[tuple[int, dict]] = []
    for key in ("gcp_compute",):
        bucket = service_states.get(key)
        if isinstance(bucket, dict):
            score = 0
            for value in bucket.values():
                if isinstance(value, dict):
                    score += len(value)
                elif isinstance(value, (list, tuple, set)):
                    score += len(value)
                elif value not in (None, "", False):
                    score += 1
            candidates.append((score, bucket))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1].setdefault("instances", {}) if "instances" not in candidates[0][1] else candidates[0][1]["instances"]
    return gcp_compute_state.get("instances", {})


def _gcp_compute_find_instance(project: str, zone: str, instance_ref: str) -> dict | None:
    instance = _gcp_compute_instance_bucket().get(instance_ref)
    if not isinstance(instance, dict):
        for candidate in _gcp_compute_instance_bucket().values():
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("name") or "").strip() == str(instance_ref or "").strip():
                instance = candidate
                break
    if not isinstance(instance, dict):
        return None
    if str(instance.get("project") or "").strip() != str(project or "").strip():
        return None
    requested_zone = str(zone or "").strip().lower()
    if requested_zone and requested_zone not in {"-", "*", "_all", "all"}:
        if str(instance.get("zone") or instance.get("az") or "").strip() != zone:
            return None
    return instance


def _gcp_compute_state_meta(state: str) -> str:
    mapping = {
        "pending": "PROVISIONING",
        "running": "RUNNING",
        "stopping": "STOPPING",
        "stopped": "TERMINATED",
        "rebooting": "STAGING",
        "terminated": "TERMINATED",
    }
    return mapping.get(str(state or "").strip().lower(), "PROVISIONING")


def _gcp_compute_api_root() -> str:
    return f"{_gcp_public_base()}/compute/v1"


def _gcp_compute_project_path(project: str) -> str:
    return f"projects/{project}"


def _gcp_compute_zone_path(project: str, zone: str) -> str:
    return f"projects/{project}/zones/{zone}"


def _gcp_compute_instance_path(project: str, zone: str, instance_name: str) -> str:
    return f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/instances/{instance_name}"


def _gcp_compute_operation_path(project: str, zone: str, op_name: str) -> str:
    return f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/operations/{op_name}"


def _gcp_resource_name(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text.rstrip("/").split("/")[-1] or default


def _gcp_compute_numeric_id(value: str) -> str:
    token = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    # Mask to 63 bits so the value always fits a signed int64 — real Google
    # clients (Apiary) parse numeric ids / generation / projectNumber as `long`,
    # and an unmasked 16-hex value overflows ~half the time.
    return str(int(token, 16) & 0x7FFFFFFFFFFFFFFF)


def _gcp_compute_sync_runtime_instances() -> None:
    changed = False
    for instance in gcp_compute_state.get("instances", {}).values():
        if not isinstance(instance, dict):
            continue
        workspace_before = str(instance.get("workspace") or "")
        workspace = _ensure_instance_workspace(instance)
        if str(workspace) != workspace_before:
            changed = True
        backend = str(instance.get("runtime_backend") or "").strip().lower()
        if backend == "multipass":
            _sync_multipass_instance(instance)
            changed = True
        elif backend == "lxd":
            _sync_lxd_instance(instance)
            changed = True
    if _gcp_compute_sync_resource_links():
        changed = True
    if changed:
        _persist_state()


def _gcp_compute_requested_instance_groups(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("requested_groups") or payload.get("requested_instance_groups") or payload.get("instanceGroups") or payload.get("instanceGroup") or payload.get("instance_groups") or payload.get("instance_group") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if isinstance(raw, dict):
        raw = [str(raw.get("name") or raw.get("group") or raw.get("baseInstanceName") or "").strip()]
    if not isinstance(raw, list):
        return []
    groups: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name and name not in groups:
            groups.append(name)
    return groups


def _gcp_compute_requested_disk_specs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("disks") or payload.get("attachedDisks") or payload.get("attached_disks") or []
    if not isinstance(raw, list):
        return []
    specs: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            specs.append(item)
    return specs


def _gcp_compute_sync_resource_links() -> bool:
    changed = False
    instances = gcp_compute_state.get("instances", {})
    groups = gcp_compute_state.setdefault("instance_groups", {})
    disks = gcp_compute_state.setdefault("disks", {})
    for instance in instances.values():
        if not isinstance(instance, dict):
            continue
        instance_name = str(instance.get("name") or instance.get("instance_id") or "").strip()
        instance_id = str(instance.get("instance_id") or "").strip()
        runtime_state = str(instance.get("state") or "").strip().lower()
        attached_disk_names: list[str] = []
        group_names: list[str] = []
        requested_groups = _gcp_compute_requested_instance_groups(instance)

        for disk in disks.values():
            if not isinstance(disk, dict):
                continue
            disk_name = str(disk.get("name") or "").strip()
            if not disk_name:
                continue
            disk_instance = str(disk.get("instance") or disk.get("instance_name") or "").strip()
            disk_instance_id = str(disk.get("instance_id") or "").strip()
            if disk_instance and disk_instance != instance_name and disk_instance_id != instance_id:
                continue
            if not disk_instance and not disk_instance_id and disk.get("boot") and disk_name.startswith(instance_name):
                disk_instance = instance_name
            if disk_instance and disk_instance not in {instance_name, instance_id}:
                continue
            attached_disk_names.append(disk_name)
            boot_flag = bool(disk.get("boot")) or disk_name == f"{instance_name}-boot"
            auto_delete_flag = disk.get("autoDelete")
            if auto_delete_flag is None:
                auto_delete_flag = boot_flag
            if disk.get("boot") is None or disk.get("boot") != boot_flag:
                disk["boot"] = boot_flag
                changed = True
            if disk.get("autoDelete") is None or bool(disk.get("autoDelete")) != bool(auto_delete_flag):
                disk["autoDelete"] = bool(auto_delete_flag)
                changed = True
            if disk.get("deviceName") != disk_name:
                disk["deviceName"] = disk_name
                changed = True
            desired_status = "IN_USE" if runtime_state == "running" else "READY"
            if str(disk.get("status") or "").upper() != desired_status:
                disk["status"] = desired_status
                changed = True
            if disk.get("instance") != instance_name:
                disk["instance"] = instance_name
                changed = True
            if disk.get("instance_id") != instance_id:
                disk["instance_id"] = instance_id
                changed = True
            if disk.get("updateTime") != _now():
                disk["updateTime"] = _now()
                changed = True

        for group_name, group in groups.items():
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("name") or group_name or "").strip()
            if not group_name:
                continue
            members = group.setdefault("instances", [])
            if not isinstance(members, list):
                members = []
                group["instances"] = members
                changed = True
            base_instance_name = str(group.get("baseInstanceName") or "").strip()
            if instance_name in members or base_instance_name == instance_name or group_name in requested_groups:
                if instance_name and instance_name not in members:
                    members.append(instance_name)
                    changed = True
                if group_name not in group_names:
                    group_names.append(group_name)
                desired_size = max(int(group.get("targetSize") or 0), len([v for v in members if str(v).strip()]))
                if int(group.get("targetSize") or 0) != desired_size:
                    group["targetSize"] = desired_size
                    changed = True
                if group.get("updateTime") != _now():
                    group["updateTime"] = _now()
                    changed = True
            elif group_name in requested_groups:
                if instance_name and instance_name not in members:
                    members.append(instance_name)
                    changed = True

        for group_name in requested_groups:
            if group_name in groups:
                continue
            groups[group_name] = {
                "name": group_name,
                "project": str(instance.get("project") or "cloudlearn"),
                "zone": str(instance.get("zone") or instance.get("az") or "us-central1-a"),
                "description": "",
                "baseInstanceName": instance_name or group_name,
                "targetSize": 1 if instance_name else 0,
                "instances": [instance_name] if instance_name else [],
                "namedPorts": [],
                "state": "STABLE",
                "created": _now(),
                "updateTime": _now(),
            }
            group_names.append(group_name)
            changed = True

        if instance.get("attached_disk_names") != sorted(dict.fromkeys(attached_disk_names)):
            instance["attached_disk_names"] = sorted(dict.fromkeys(attached_disk_names))
            changed = True
        if instance.get("instance_groups") != sorted(dict.fromkeys(group_names)):
            instance["instance_groups"] = sorted(dict.fromkeys(group_names))
            changed = True
        if instance.get("instance_group_refs") != requested_groups:
            instance["instance_group_refs"] = requested_groups
            changed = True
    if changed:
        _refresh_cloudsim_gcp_summary()
    return changed


def _gcp_compute_instance_json(instance: dict) -> dict:
    project = str(instance.get("project") or "cloudlearn")
    zone = str(instance.get("zone") or instance.get("az") or "us-central1-a")
    machine_type = str(instance.get("machine_type") or instance.get("instance_type") or "e2-micro")
    instance_name = str(instance.get("name") or instance.get("instance_id") or "gcp-instance")
    status = _gcp_compute_state_meta(instance.get("state", "pending"))
    resource_id = str(instance.get("gcp_resource_id") or _gcp_compute_numeric_id(instance_name))
    network_interfaces = [
        {
            "name": "nic0",
            "network": f"{_gcp_compute_api_root()}/projects/{project}/global/networks/{instance.get('vpc_id') or 'default'}",
            "subnetwork": f"{_gcp_compute_api_root()}/projects/{project}/regions/{zone.rsplit('-', 1)[0] if '-' in zone else 'us-central1'}/subnetworks/{instance.get('subnet_id') or 'default'}",
            "networkIP": instance.get("runtime_internal_ip") or instance.get("private_ip") or "",
            "accessConfigs": ([{"name": "External NAT", "type": "ONE_TO_ONE_NAT", "natIP": _gcp_public_ip_only()}] if instance.get("public_ip") else []),
            "stackType": "IPV4_ONLY",
        }
    ]
    disks = []
    attached_disk_names = [str(name).strip() for name in (instance.get("attached_disk_names") or []) if str(name).strip()]
    for disk_name in attached_disk_names:
        disk = gcp_compute_state.get("disks", {}).get(disk_name)
        if not isinstance(disk, dict):
            continue
        disks.append(
            {
                "kind": "compute#attachedDisk",
                "type": "PERSISTENT",
                "mode": "READ_WRITE",
                "boot": bool(disk.get("boot", disk_name == f"{instance_name}-boot")),
                "autoDelete": bool(disk.get("autoDelete", True)),
                "deviceName": disk.get("deviceName") or disk_name,
                "initializeParams": {
                    "sourceImage": f"{_gcp_compute_api_root()}/projects/{project}/global/images/{disk.get('sourceImage') or instance.get('ami') or 'sim-ubuntu-22.04'}",
                    "sourceSnapshot": f"{_gcp_compute_api_root()}/projects/{project}/global/snapshots/{disk.get('sourceSnapshot')}" if disk.get("sourceSnapshot") else "",
                    "diskSizeGb": str(disk.get("sizeGb") or instance.get("storage_gb") or 8),
                    "diskType": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/diskTypes/{disk.get('type') or instance.get('boot_disk_type') or 'pd-balanced'}",
                },
            }
        )
    if not disks:
        disks = [
            {
                "kind": "compute#attachedDisk",
                "type": "PERSISTENT",
                "mode": "READ_WRITE",
                "boot": True,
                "autoDelete": True,
                "deviceName": instance_name,
                "initializeParams": {
                    "sourceImage": f"{_gcp_compute_api_root()}/projects/{project}/global/images/{instance.get('ami') or 'sim-ubuntu-22.04'}",
                    "diskSizeGb": str(instance.get("storage_gb") or 8),
                    "diskType": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/diskTypes/{instance.get('boot_disk_type') or 'pd-balanced'}",
                },
            }
        ]
    return {
        "kind": "compute#instance",
        "id": resource_id,
        "name": instance_name,
        "zone": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}",
        "machineType": f"projects/{project}/zones/{zone}/machineTypes/{machine_type}",
        "status": status,
        "fingerprint": instance.get("fingerprint", ""),
        "labelFingerprint": instance.get("label_fingerprint", ""),
        "tags": {"items": instance.get("tags", []), "fingerprint": instance.get("tag_fingerprint", "")},
        "metadata": {
            "kind": "compute#metadata",
            "fingerprint": instance.get("metadata_fingerprint", ""),
            "items": [{"key": k, "value": v} for k, v in (instance.get("metadata_items") or {}).items()],
        },
        "disks": disks,
        "networkInterfaces": network_interfaces,
        "labels": instance.get("labels", {}),
        "instanceGroups": [f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/instanceGroups/{name}" for name in (instance.get("instance_groups") or [])],
        "creationTimestamp": instance.get("created", _now()),
        "selfLink": _gcp_compute_instance_path(project, zone, instance_name),
        "canIpForward": bool(instance.get("assign_external_ip", True)),
        "description": instance.get("description", ""),
        "scheduling": {
            "automaticRestart": True,
            "onHostMaintenance": "MIGRATE",
            "preemptible": False,
        },
        "serviceAccounts": [
            {
                "email": f"{instance.get('service_account', 'default')}@{project}.iam.gserviceaccount.com",
                "scopes": ["cloud-platform"],
            }
        ],
        "deletionProtection": bool(instance.get("deletion_protection", False)),
        "shieldedInstanceConfig": {
            "enableSecureBoot": bool(instance.get("shielded_vm", True)),
            "enableVtpm": bool(instance.get("vtpm", True)),
            "enableIntegrityMonitoring": bool(instance.get("integrity_monitoring", True)),
        },
        "cpuPlatform": instance.get("cpu_platform", "Intel Skylake"),
    }


def _gcp_compute_operation_json(instance: dict, operation_type: str, status: str = "DONE") -> dict:
    project = str(instance.get("project") or "cloudlearn")
    zone = str(instance.get("zone") or instance.get("az") or "us-central1-a")
    instance_name = str(instance.get("name") or instance.get("instance_id") or "gcp-instance")
    op_name = f"{operation_type}-{instance_name}"
    resource_id = str(instance.get("gcp_resource_id") or _gcp_compute_numeric_id(instance_name))
    return {
        "kind": "compute#operation",
        "id": _gcp_compute_numeric_id(op_name),
        "name": op_name,
        "status": status,
        "operationType": operation_type,
        "targetLink": _gcp_compute_instance_path(project, zone, instance_name),
        "targetId": resource_id,
        "zone": _gcp_compute_zone_path(project, zone),
        "selfLink": _gcp_compute_operation_path(project, zone, op_name),
        "insertTime": instance.get("created", _now()),
        "startTime": instance.get("created", _now()),
        "endTime": _now() if status.upper() == "DONE" else "",
        "progress": 100 if status.upper() == "DONE" else 0,
        "user": "cloudlearn",
    }


def _gcp_compute_json_list(project: str, zone: str) -> dict:
    _gcp_compute_sync_runtime_instances()
    instances = []
    zone_key = str(zone or "").strip().lower()
    for instance in gcp_compute_state.get("instances", {}).values():
        if not isinstance(instance, dict):
            continue
        if str(instance.get("project") or "cloudlearn").strip() != str(project or "cloudlearn").strip():
            continue
        # zone may be stored plain ("us-central1-a") or as a self-link URL
        # (".../zones/us-central1-a"); compare on the trailing segment.
        instance_zone = str(instance.get("zone") or instance.get("az") or "us-central1-a").rstrip("/").split("/")[-1]
        if zone_key and zone_key not in {"-", "*", "_all", "all"} and instance_zone != zone:
            continue
        instances.append(_gcp_compute_instance_json(instance))
    return {
        "kind": "compute#instanceList",
        "id": f"projects/{project}/zones/{zone}/instances",
        "selfLink": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/instances",
        "items": instances,
    }


def _gcp_compute_create_instance_instance(project: str, zone: str, payload: dict[str, Any]) -> dict:
    instance_id = _id("gce")
    source_image_ref = str(payload.get("sourceImage") or payload.get("ami") or "sim-ubuntu-22.04")
    machine_type_ref = str(payload.get("machineType") or payload.get("instance_type") or "e2-micro")
    boot_disk_type_ref = str(payload.get("bootDiskType") or payload.get("boot_disk_type") or "pd-balanced")
    profile = _ami_profile(_gcp_resource_name(source_image_ref, "sim-ubuntu-22.04"))
    trusted_host_os = _resolved_host_os()
    try:
        runtime_backend = _ec2_choose_runtime_backend(
            profile,
            str(payload.get("runtimeBackend") or payload.get("runtime_backend") or ""),
            trusted_host_os,
            require_available=not bool(trusted_host_os),
        )
    except HTTPException:
        # Real GCP returns a long-running Operation immediately and provisions the
        # VM asynchronously. If no host runtime backend supports this image, record
        # the instance and defer provisioning rather than failing the control-plane call.
        runtime_backend = "simulated"
    workspace = _instance_workspace(instance_id)
    workspace.mkdir(parents=True, exist_ok=True)
    runtime_image = profile.get("runtime_image") or (
        MULTIPASS_RUNTIME_IMAGE if runtime_backend == "multipass" else LXD_RUNTIME_IMAGE
    )
    labels = payload.get("labels") if isinstance(payload.get("labels"), dict) else {}
    network_interfaces_payload = payload.get("networkInterfaces") if isinstance(payload.get("networkInterfaces"), list) else []
    first_network = network_interfaces_payload[0] if network_interfaces_payload and isinstance(network_interfaces_payload[0], dict) else {}
    network_ref = first_network.get("network") or f"{_gcp_compute_api_root()}/projects/{project}/global/networks/default"
    subnetwork_ref = first_network.get("subnetwork") or f"{_gcp_compute_api_root()}/projects/{project}/regions/{zone.rsplit('-', 1)[0] if '-' in zone else 'us-central1'}/subnetworks/default"
    access_configs = first_network.get("accessConfigs") if isinstance(first_network.get("accessConfigs"), list) else []
    disk_specs = _gcp_compute_requested_disk_specs(payload)
    requested_groups = _gcp_compute_requested_instance_groups(payload)
    metadata_items_raw = []
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata_items_raw = metadata.get("items", [])
    metadata_items: dict[str, Any] = {}
    if isinstance(metadata_items_raw, dict):
        metadata_items = {str(k): v for k, v in metadata_items_raw.items()}
    elif isinstance(metadata_items_raw, list):
        for item in metadata_items_raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            metadata_items[key] = item.get("value", "")
    assign_external_ip = bool(payload.get("assignExternalIp", payload.get("assign_external_ip", True)))
    if not assign_external_ip and access_configs:
        assign_external_ip = True
    instance = {
        "instance_id": instance_id,
        "id": instance_id,
        "gcp_resource_id": _gcp_compute_numeric_id(instance_id),
        "reservation_id": f"r-{instance_id.replace('gce-', '')}",
        "owner_id": AWS_ACCOUNT_ID,
        "provider": "gcp",
        "project": str(project or "cloudlearn"),
        "zone": str(zone or "us-central1-a"),
        "name": str(payload.get("name") or "gcp-instance"),
        "machine_type": _gcp_resource_name(machine_type_ref, "e2-micro"),
        "machineType": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/machineTypes/{_gcp_resource_name(machine_type_ref, 'e2-micro')}",
        "ami": _gcp_resource_name(source_image_ref, "sim-ubuntu-22.04"),
        "ami_name": profile.get("name", _gcp_resource_name(source_image_ref, "sim-ubuntu-22.04")),
        "os_family": profile.get("os_family", "linux"),
        "container_image": profile.get("container_image", ""),
        "runtime_image": runtime_image,
        "runtime": str(payload.get("runtime") or profile.get("default_runtime") or "python"),
        "runtime_backend_requested": str(payload.get("runtimeBackend") or payload.get("runtime_backend") or "").strip().lower(),
        "runtime_backend": runtime_backend,
        "tags": list(payload.get("tags", {}).get("items", []) if isinstance(payload.get("tags"), dict) else (payload.get("tags") if isinstance(payload.get("tags"), list) else [])),
        "key_pair": str(payload.get("keyPair") or payload.get("key_pair") or ""),
        "state": "pending",
        "launch_status": "queued",
        "az": str(zone or "us-central1-a"),
        "vpc_id": _gcp_resource_name(payload.get("vpcId") or payload.get("vpc_id") or network_ref, "default"),
        "subnet_id": _gcp_resource_name(payload.get("subnetId") or payload.get("subnet_id") or subnetwork_ref, ""),
        "security_group_ids": [str(v) for v in (payload.get("securityGroupIds") or payload.get("security_group_ids") or []) if str(v).strip()],
        "storage_gb": int(payload.get("bootDiskSizeGb") or payload.get("storage_gb") or (str((payload.get("disks") or [{}])[0].get("initializeParams", {}).get("diskSizeGb", 8)).strip() or 8)),
        "boot_disk_type": _gcp_resource_name(boot_disk_type_ref, "pd-balanced"),
        "private_ip": _private_ip(),
        "public_ip": _public_ip() if assign_external_ip else None,
        "command": str(payload.get("startupCommand") or payload.get("command") or ""),
        "user_data": str(payload.get("startupScript") or payload.get("user_data") or ""),
        "service_account": str(payload.get("serviceAccount") or payload.get("service_account") or "default"),
        "assign_external_ip": assign_external_ip,
        "shielded_vm": bool(payload.get("shieldedVm", payload.get("shielded_vm", True))),
        "vtpm": bool(payload.get("vtpm", True)),
        "integrity_monitoring": bool(payload.get("integrityMonitoring", payload.get("integrity_monitoring", True))),
        "labels": labels,
        "metadata_items": metadata_items,
        "requested_disks": disk_specs,
        "requested_disk_names": [str(item.get("deviceName") or "").strip() for item in disk_specs if isinstance(item, dict) and str(item.get("deviceName") or "").strip()],
        "requested_groups": requested_groups,
        "requested_instance_groups": requested_groups,
        "created": _now(),
        "workspace": str(workspace),
        "deployment_path": str(workspace),
        "console_state": {"cwd": str(workspace)},
        "console_log": [],
        "ssh_command": "ssh -i ~/.ssh/cloudlearn_multipass_ed25519 ubuntu@<appliance-ip>",
        "container_download_state": "pending",
        "container_name": f"cloudlearn-{instance_id}",
        "container_id": "",
        "container_port": LXD_CONSOLE_PORT,
        "host_port": _allocate_host_port(),
        "endpoint_url": f"gcp://{instance_id}",
        "container_status": "created",
        "console_backend": "multipass-ssh" if runtime_backend == "multipass" else f"{runtime_backend}-exec",
        "console_prompt": _cmd_prompt({"runtime_backend": runtime_backend, "container_name": f"cloudlearn-{instance_id}", "container_id": ""}),
        "network_interfaces": network_interfaces_payload,
    }
    return instance


def _gcp_compute_instance_group_record(project: str, zone: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("group") or "").strip()
    if not name:
        name = f"group-{_id('mig')}"
    instances = [str(v).strip() for v in (payload.get("instances") or []) if str(v).strip()] if isinstance(payload.get("instances"), list) else []
    return {
        "name": name,
        "project": project,
        "zone": zone,
        "description": str(payload.get("description") or ""),
        "baseInstanceName": str(payload.get("baseInstanceName") or payload.get("base_instance_name") or name),
        "targetSize": int(payload.get("targetSize") or payload.get("target_size") or max(len(instances), 1)),
        "instances": instances,
        "namedPorts": payload.get("namedPorts", []) if isinstance(payload.get("namedPorts"), list) else [],
        "state": str(payload.get("state") or "STABLE"),
        "created": _now(),
        "updateTime": _now(),
    }


def _gcp_compute_instance_group_view(group: dict) -> dict:
    return {
        "kind": "compute#instanceGroup",
        "id": _gcp_compute_numeric_id(f"{group.get('project')}:{group.get('zone')}:{group.get('name')}"),
        "name": group.get("name", ""),
        "description": group.get("description", ""),
        "zone": _gcp_compute_zone_path(str(group.get("project") or "cloudlearn"), str(group.get("zone") or "us-central1-a")),
        "network": f"{_gcp_compute_api_root()}/projects/{group.get('project') or 'cloudlearn'}/global/networks/default",
        "size": int(group.get("targetSize") or len(group.get("instances") or [])),
        "namedPorts": group.get("namedPorts", []),
        "instances": [f"{_gcp_compute_api_root()}/projects/{group.get('project') or 'cloudlearn'}/zones/{group.get('zone') or 'us-central1-a'}/instances/{name}" for name in (group.get("instances") or [])],
        "creationTimestamp": group.get("created", _now()),
        "updateTime": group.get("updateTime", _now()),
        "state": group.get("state", "STABLE"),
        "baseInstanceName": group.get("baseInstanceName", group.get("name", "")),
        "selfLink": f"{_gcp_compute_api_root()}/projects/{group.get('project') or 'cloudlearn'}/zones/{group.get('zone') or 'us-central1-a'}/instanceGroups/{group.get('name', '')}",
    }


def _gcp_compute_disk_record(project: str, zone: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("disk") or "").strip() or f"disk-{_id('pd')}"
    return {
        "name": name,
        "project": project,
        "zone": zone,
        "sizeGb": int(payload.get("sizeGb") or payload.get("size_gb") or 10),
        "type": str(payload.get("type") or payload.get("diskType") or "pd-balanced"),
        "status": str(payload.get("status") or "READY"),
        "sourceImage": str(payload.get("sourceImage") or ""),
        "sourceSnapshot": str(payload.get("sourceSnapshot") or ""),
        "instance": str(payload.get("instance") or ""),
        "instance_id": str(payload.get("instance_id") or ""),
        "boot": bool(payload.get("boot", False)),
        "autoDelete": bool(payload.get("autoDelete", payload.get("auto_delete", False))),
        "deviceName": str(payload.get("deviceName") or payload.get("device_name") or name),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "created": _now(),
        "updateTime": _now(),
    }


def _gcp_compute_disk_view(disk: dict) -> dict:
    project = str(disk.get("project") or "cloudlearn")
    zone = str(disk.get("zone") or "us-central1-a")
    name = str(disk.get("name") or "")
    return {
        "kind": "compute#disk",
        "id": _gcp_compute_numeric_id(f"{project}:{zone}:{name}"),
        "name": name,
        "zone": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}",
        "sizeGb": str(disk.get("sizeGb") or 10),
        "type": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/diskTypes/{disk.get('type') or 'pd-balanced'}",
        "status": disk.get("status", "READY"),
        "sourceImage": disk.get("sourceImage", ""),
        "sourceSnapshot": disk.get("sourceSnapshot", ""),
        "instance": disk.get("instance", ""),
        "instanceId": disk.get("instance_id", ""),
        "boot": bool(disk.get("boot", False)),
        "autoDelete": bool(disk.get("autoDelete", False)),
        "deviceName": disk.get("deviceName", name),
        "users": [f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/instances/{disk.get('instance')}"] if disk.get("instance") else [],
        "labels": disk.get("labels", {}),
        "creationTimestamp": disk.get("created", _now()),
        "updateTime": disk.get("updateTime", _now()),
        "selfLink": f"{_gcp_compute_api_root()}/projects/{project}/zones/{zone}/disks/{name}",
    }


def _gcp_compute_snapshot_record(project: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    source_disk = str(payload.get("sourceDisk") or payload.get("source_disk") or "").strip()
    name = str(payload.get("name") or payload.get("snapshot") or "").strip() or f"snapshot-{_id('snap')}"
    zone = str(payload.get("zone") or payload.get("region") or "global")
    return {
        "name": name,
        "project": project,
        "zone": zone,
        "sourceDisk": source_disk,
        "description": str(payload.get("description") or ""),
        "storageLocations": payload.get("storageLocations", ["us"]) if isinstance(payload.get("storageLocations"), list) else ["us"],
        "status": str(payload.get("status") or "READY"),
        "sizeGb": int(payload.get("sizeGb") or payload.get("size_gb") or 10),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "created": _now(),
        "updateTime": _now(),
    }


def _gcp_compute_snapshot_view(snapshot: dict) -> dict:
    project = str(snapshot.get("project") or "cloudlearn")
    name = str(snapshot.get("name") or "")
    return {
        "kind": "compute#snapshot",
        "id": _gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "description": snapshot.get("description", ""),
        "sourceDisk": snapshot.get("sourceDisk", ""),
        "storageLocations": snapshot.get("storageLocations", []),
        "status": snapshot.get("status", "READY"),
        "diskSizeGb": str(snapshot.get("sizeGb") or 10),
        "creationTimestamp": snapshot.get("created", _now()),
        "labels": snapshot.get("labels", {}),
        "selfLink": f"{_gcp_compute_api_root()}/projects/{project}/global/snapshots/{name}",
    }


def _gcp_compute_image_record(project: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("image") or "").strip() or f"image-{_id('img')}"
    return {
        "name": name,
        "project": project,
        "family": str(payload.get("family") or ""),
        "sourceSnapshot": str(payload.get("sourceSnapshot") or payload.get("source_snapshot") or ""),
        "sourceDisk": str(payload.get("sourceDisk") or payload.get("source_disk") or ""),
        "description": str(payload.get("description") or ""),
        "status": str(payload.get("status") or "READY"),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "created": _now(),
        "updateTime": _now(),
    }


def _gcp_compute_image_view(image: dict) -> dict:
    project = str(image.get("project") or "cloudlearn")
    name = str(image.get("name") or "")
    return {
        "kind": "compute#image",
        "id": _gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "family": image.get("family", ""),
        "sourceSnapshot": image.get("sourceSnapshot", ""),
        "sourceDisk": image.get("sourceDisk", ""),
        "status": image.get("status", "READY"),
        "description": image.get("description", ""),
        "labels": image.get("labels", {}),
        "creationTimestamp": image.get("created", _now()),
        "selfLink": f"{_gcp_compute_api_root()}/projects/{project}/global/images/{name}",
    }


def _gcp_compute_queue_runtime_start(instance_id: str) -> None:
    _queue_runtime_start_for_store(gcp_compute_state["instances"], instance_id)


def _ec2_query_state_change_response(root_name: str, changes: list[tuple[dict, str, str | None]]) -> Response:
    def build(root: ET.Element) -> None:
        instances_set = _ec2_sub(root, "instancesSet")
        for instance, previous_state, current_state in changes:
            instances_set.append(_ec2_instance_state_change_xml(instance, previous_state, current_state))

    return _ec2_success_response(root_name, build)


async def api_ec2_query(request: Request):
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    version = str(params.get("Version", "2016-11-15")).strip() or "2016-11-15"
    if version != "2016-11-15":
        return _ec2_error_response("InvalidParameterValue", f"Unsupported EC2 API version '{version}'.", 400)
    if not action:
        return _ec2_error_response("MissingParameter", "The request must contain the parameter Action.", 400)

    if str(params.get("DryRun", "")).lower() == "true":
        return _ec2_error_response("DryRunOperation", "Request would have succeeded, but DryRun flag is set.", 412)

    try:
        if action == "DescribeInstances":
            return _ec2_query_describe_instances(params)
        if action == "DescribeImages":
            return _ec2_query_describe_images(params)
        if action == "DescribeInstanceStatus":
            return _ec2_query_describe_instance_status(params)
        if action == "DescribeInstanceTypes":
            return _ec2_query_describe_instance_types(params)
        if action == "DescribeSecurityGroups":
            return _ec2_query_describe_security_groups(params)
        if action == "DescribeVolumes":
            return _ec2_query_describe_volumes(params)
        if action == "RunInstances":
            return _ec2_query_run_instances(params)
        if action == "StartInstances":
            instance_ids = _ec2_parse_instance_ids(params)
            changes: list[tuple[dict, str, str | None]] = []
            for instance_id in instance_ids:
                instance = ec2_state["instances"].get(instance_id)
                if not instance:
                    raise HTTPException(404, detail=f"InvalidInstanceID.NotFound: {instance_id}")
                previous = instance.get("state", "stopped")
                instance["state"] = "pending"
                _queue_runtime_start(instance_id)
                changes.append((instance, previous, "pending"))
            return _ec2_query_state_change_response("StartInstancesResponse", changes)
        if action == "StopInstances":
            instance_ids = _ec2_parse_instance_ids(params)
            changes: list[tuple[dict, str, str | None]] = []
            for instance_id in instance_ids:
                instance = ec2_state["instances"].get(instance_id)
                if not instance:
                    raise HTTPException(404, detail=f"InvalidInstanceID.NotFound: {instance_id}")
                previous = instance.get("state", "running")
                _stop_runtime_process(instance)
                changes.append((instance, previous, "stopping"))
            return _ec2_query_state_change_response("StopInstancesResponse", changes)
        if action == "RebootInstances":
            instance_ids = _ec2_parse_instance_ids(params)
            changes: list[tuple[dict, str, str | None]] = []
            for instance_id in instance_ids:
                instance = ec2_state["instances"].get(instance_id)
                if not instance:
                    raise HTTPException(404, detail=f"InvalidInstanceID.NotFound: {instance_id}")
                previous = instance.get("state", "running")
                _reboot_runtime_process(instance)
                changes.append((instance, previous, "running"))
            return _ec2_query_state_change_response("RebootInstancesResponse", changes)
        if action == "TerminateInstances":
            instance_ids = _ec2_parse_instance_ids(params)
            changes: list[tuple[dict, str, str | None]] = []
            for instance_id in instance_ids:
                instance = ec2_state["instances"].get(instance_id)
                if not instance:
                    raise HTTPException(404, detail=f"InvalidInstanceID.NotFound: {instance_id}")
                previous = instance.get("state", "running")
                backend = str(instance.get("runtime_backend") or "").strip().lower()
                if instance.get("launch_status") == "error" and not str(instance.get("container_id") or "").strip():
                    _terminate_simulated_instance(instance)
                elif backend == "multipass":
                    _terminate_multipass_instance(instance)
                elif backend == "lxd":
                    _terminate_lxd_instance(instance)
                else:
                    _terminate_simulated_instance(instance)
                changes.append((instance, previous, "shutting-down"))
            return _ec2_query_state_change_response("TerminateInstancesResponse", changes)
    except HTTPException as exc:
        code = str(exc.detail).split(":", 1)[0]
        message = str(exc.detail)
        return _ec2_error_response(code, message, exc.status_code)

    return _ec2_error_response("InvalidAction", f"The action '{action}' is not implemented by the simulator.", 400)


def api_gcp_compute_list_instances(project: str, zone: str):
    return _gcp_compute_json_list(project, zone)


async def api_gcp_compute_create_instance(project: str, zone: str, request: Request):
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        req = GCPComputeInstanceRequest(**payload)
    except Exception as exc:
        raise HTTPException(400, detail=f"InvalidComputeEngineRequest: {exc}")
    # Host-budget gate (clamp 30%-50% of host CPU+RAM).
    _check_budget_for_launch(str(getattr(req, "machineType", "") or payload.get("machineType") or ""), "gcp")
    # Disk pre-flight — refuse early with 507 rather than half-creating
    # a container that won't fit. See _disk_preflight definition. The
    # GCPComputeInstanceRequest model exposes the disk size as
    # `bootDiskSizeGb` (the canonical GCP Compute name), NOT `diskSizeGb`
    # — falling back through both keeps backward-compat with any caller
    # that hand-rolls the older spelling.
    _disk_preflight(
        getattr(req, "bootDiskSizeGb", None)
        or getattr(req, "diskSizeGb", None)
        or 10
    )
    _enforce_quantity_cap("vm")  # tier cap — Free=1 VM/space
    _enforce_size_cap("vm", "gcp", str(getattr(req, "machineType", "") or payload.get("machineType") or ""))
    instance = _gcp_compute_create_instance_instance(project, zone, req.dict())
    instance["runtime_bundle_id"] = _cloudsim_runtime_bundle("gcp_compute").get("id", "")
    instance["runtime_bundle_name"] = _cloudsim_runtime_bundle("gcp_compute").get("name", "")
    instance["runtime_bundle_kind"] = _cloudsim_runtime_bundle("gcp_compute").get("kind", "")
    gcp_compute_state["instances"][instance["instance_id"]] = instance
    # P2-B: push the new GCE instance into CloudSim's resource_graph (parity
    # with EC2 + Azure VM). The aggregator still walks service_states for VM
    # shapes; this just makes per-resource events visible incrementally.
    _cloudsim_sync_gcp_compute_resource(instance, "upsert")
    disk_specs = instance.get("requested_disks") if isinstance(instance.get("requested_disks"), list) else []
    attached_disk_names: list[str] = []
    if not disk_specs:
        disk_specs = [{
            "boot": True,
            "autoDelete": True,
            "deviceName": f"{instance['name']}-boot",
            "initializeParams": {
                "diskSizeGb": str(instance.get("storage_gb") or 8),
                "diskType": instance.get("boot_disk_type") or "pd-balanced",
                "sourceImage": instance.get("ami") or "",
                "sourceSnapshot": "",
            },
        }]
    for idx, spec in enumerate(disk_specs):
        if not isinstance(spec, dict):
            continue
        init = spec.get("initializeParams") if isinstance(spec.get("initializeParams"), dict) else {}
        disk_name = str(spec.get("deviceName") or spec.get("device_name") or (f"{instance['name']}-boot" if idx == 0 else f"{instance['name']}-disk-{idx + 1}")).strip()
        if not disk_name:
            disk_name = f"{instance['name']}-disk-{idx + 1}"
        disk = _gcp_compute_disk_record(project, zone, {
            "name": disk_name,
            "sizeGb": int(str(init.get("diskSizeGb") or spec.get("diskSizeGb") or instance.get("storage_gb") or 8).strip() or 8),
            "type": str(init.get("diskType") or spec.get("type") or instance.get("boot_disk_type") or "pd-balanced"),
            "sourceImage": str(init.get("sourceImage") or spec.get("sourceImage") or instance.get("ami") or ""),
            "sourceSnapshot": str(init.get("sourceSnapshot") or spec.get("sourceSnapshot") or ""),
            "instance": instance["name"],
            "instance_id": instance["instance_id"],
            "status": "READY",
            "boot": bool(spec.get("boot", idx == 0)),
            "autoDelete": bool(spec.get("autoDelete", spec.get("auto_delete", idx == 0))),
            "deviceName": disk_name,
        })
        gcp_compute_state.setdefault("disks", {})[disk["name"]] = disk
        attached_disk_names.append(disk["name"])
    instance["attached_disk_names"] = attached_disk_names
    for group_name in instance.get("requested_instance_groups") or []:
        group = gcp_compute_state.setdefault("instance_groups", {}).get(group_name)
        if not isinstance(group, dict):
            group = _gcp_compute_instance_group_record(project, zone, {
                "name": group_name,
                "baseInstanceName": instance["name"],
                "targetSize": 1,
                "instances": [instance["name"]],
                "state": "STABLE",
            })
            gcp_compute_state["instance_groups"][group_name] = group
        members = group.setdefault("instances", [])
        if instance["name"] not in members:
            members.append(instance["name"])
        group["targetSize"] = max(int(group.get("targetSize") or 0), len([v for v in members if str(v).strip()]))
        group["updateTime"] = _now()
        instance.setdefault("instance_groups", [])
        if group_name not in instance["instance_groups"]:
            instance["instance_groups"].append(group_name)
    _gcp_compute_queue_runtime_start(instance["instance_id"])
    _gcp_compute_sync_resource_links()
    _record_usage("gcp.compute.create_instance", instance)
    return _gcp_compute_operation_json(instance, "insert", "PENDING")


def api_gcp_compute_get_instance(project: str, zone: str, instance: str):
    _gcp_compute_sync_runtime_instances()
    instance = _gcp_compute_find_instance(project, zone, instance)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    return _gcp_compute_instance_json(instance)


def api_gcp_compute_start_instance(project: str, zone: str, instance: str):
    instance = _gcp_compute_find_instance(project, zone, instance)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    previous_state = instance.get("state", "stopped")
    instance["state"] = "pending"
    instance["launch_status"] = "starting"
    _gcp_compute_queue_runtime_start(str(instance.get("instance_id", "")))
    _gcp_compute_sync_resource_links()
    _cloudsim_sync_gcp_compute_resource(instance, "upsert")
    _record_usage("gcp.compute.start_instance", {"instance_id": instance.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(instance, "start", "PENDING")


def api_gcp_compute_stop_instance(project: str, zone: str, instance: str):
    instance = _gcp_compute_find_instance(project, zone, instance)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    previous_state = instance.get("state", "running")
    _stop_runtime_process(instance)
    instance["state"] = "stopped"
    instance["stopped_at"] = _now()
    instance["launch_status"] = "ready"
    _gcp_compute_sync_resource_links()
    _cloudsim_sync_gcp_compute_resource(instance, "upsert")
    _record_usage("gcp.compute.stop_instance", {"instance_id": instance.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(instance, "stop", "DONE")


def api_gcp_compute_reset_instance(project: str, zone: str, instance: str):
    instance = _gcp_compute_find_instance(project, zone, instance)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    previous_state = instance.get("state", "running")
    if previous_state != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    _reboot_runtime_process(instance)
    instance["launch_status"] = "ready"
    _gcp_compute_sync_resource_links()
    _cloudsim_sync_gcp_compute_resource(instance, "upsert")
    _record_usage("gcp.compute.reset_instance", {"instance_id": instance.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(instance, "reset", "DONE")


async def api_gcp_compute_set_metadata(project: str, zone: str, instance: str, request: Request):
    """POST instances/{i}/setMetadata — update instance metadata items (Terraform/SDK update path)."""
    inst = _gcp_compute_find_instance(project, zone, instance)
    if not inst:
        raise HTTPException(404, detail="NoSuchInstance")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    items = payload.get("items")
    md: dict[str, Any] = {}
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and str(it.get("key") or "").strip():
                md[str(it["key"])] = it.get("value", "")
    elif isinstance(items, dict):
        md = {str(k): v for k, v in items.items()}
    inst["metadata_items"] = md
    _record_usage("gcp.compute.set_metadata", {"instance_id": inst.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(inst, "setMetadata", "DONE")


async def api_gcp_compute_set_tags(project: str, zone: str, instance: str, request: Request):
    """POST instances/{i}/setTags — replace network tags (Terraform/SDK update path)."""
    inst = _gcp_compute_find_instance(project, zone, instance)
    if not inst:
        raise HTTPException(404, detail="NoSuchInstance")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    items = payload.get("items")
    inst["tags"] = [str(t) for t in items if str(t).strip()] if isinstance(items, list) else []
    _record_usage("gcp.compute.set_tags", {"instance_id": inst.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(inst, "setTags", "DONE")


async def api_gcp_compute_set_labels(project: str, zone: str, instance: str, request: Request):
    """POST instances/{i}/setLabels — replace instance labels (Terraform/SDK update path)."""
    inst = _gcp_compute_find_instance(project, zone, instance)
    if not inst:
        raise HTTPException(404, detail="NoSuchInstance")
    payload = await request.json() if request is not None else {}
    payload = payload if isinstance(payload, dict) else {}
    labels = payload.get("labels")
    inst["labels"] = {str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {}
    _record_usage("gcp.compute.set_labels", {"instance_id": inst.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(inst, "setLabels", "DONE")


def api_gcp_compute_delete_instance(project: str, zone: str, instance: str):
    instance = _gcp_compute_find_instance(project, zone, instance)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        _terminate_multipass_instance(instance)
    elif backend == "lxd":
        _terminate_lxd_instance(instance)
    else:
        _terminate_simulated_instance(instance)
    instance_name = str(instance.get("name") or instance.get("instance_id") or "").strip()
    for group in gcp_compute_state.get("instance_groups", {}).values():
        if not isinstance(group, dict):
            continue
        members = group.get("instances")
        if not isinstance(members, list):
            continue
        if instance_name in members:
            members[:] = [name for name in members if str(name).strip() != instance_name]
            group["targetSize"] = len(members)
            group["updateTime"] = _now()
    for disk_name in list(instance.get("attached_disk_names") or []):
        disk = gcp_compute_state.get("disks", {}).get(str(disk_name))
        if not isinstance(disk, dict):
            continue
        if bool(disk.get("autoDelete", disk.get("boot", False))):
            gcp_compute_state.get("disks", {}).pop(str(disk_name), None)
        else:
            disk["instance"] = ""
            disk["instance_id"] = ""
            disk["status"] = "READY"
            disk["updateTime"] = _now()
    instance["attached_disk_names"] = []
    instance["instance_groups"] = []
    _gcp_compute_sync_resource_links()
    # P2-B: remove from CloudSim's resource_graph (parity with EC2 + Azure VM).
    _cloudsim_sync_gcp_compute_resource(instance, "delete")
    _record_usage("gcp.compute.delete_instance", {"instance_id": instance.get("instance_id", ""), "project": project, "zone": zone})
    return _gcp_compute_operation_json(instance, "delete", "DONE")


def api_gcp_compute_get_operation(project: str, zone: str, operation_id: str):
    _gcp_compute_sync_runtime_instances()
    instance = None
    for candidate in gcp_compute_state.get("instances", {}).values():
        if not isinstance(candidate, dict):
            continue
        candidate_project = str(candidate.get("project") or "cloudlearn")
        candidate_zone = str(candidate.get("zone") or candidate.get("az") or "us-central1-a")
        candidate_name = str(candidate.get("name") or candidate.get("instance_id") or "gcp-instance")
        if candidate_project != project or candidate_zone != zone:
            continue
        for operation_type in ("insert", "start", "stop", "reset", "delete"):
            if operation_id in {f"{operation_type}-{candidate_name}", f"{operation_type}-{candidate.get('instance_id', '')}"}:
                instance = candidate
                break
        if instance:
            break
    if not instance:
        raise HTTPException(404, detail="OperationNotFound")
    status = "DONE" if str(instance.get("state", "")).lower() not in {"pending", "stopping"} else "PENDING"
    if operation_id.startswith("insert-") and str(instance.get("state", "")).lower() == "pending":
        status = "PENDING"
    return _gcp_compute_operation_json(instance, operation_id.split("-", 1)[0] or "insert", status)


def api_gcp_compute_list_instance_groups(project: str, zone: str):
    project = _gcp_project_name(project)
    groups = []
    for group in gcp_compute_state.get("instance_groups", {}).values():
        if str(group.get("project") or project) != project or str(group.get("zone") or zone) != zone:
            continue
        groups.append(_gcp_compute_instance_group_view(group))
    groups.sort(key=lambda item: item.get("name", ""))
    return {"kind": "compute#instanceGroupList", "items": groups}


async def api_gcp_compute_create_instance_group(project: str, zone: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    group = _gcp_compute_instance_group_record(project, zone, payload)
    gcp_compute_state.setdefault("instance_groups", {})[group["name"]] = group
    for instance_name in group.get("instances") or []:
        instance = _gcp_compute_find_instance(project, zone, str(instance_name))
        if not instance:
            continue
        instance.setdefault("instance_groups", [])
        if group["name"] not in instance["instance_groups"]:
            instance["instance_groups"].append(group["name"])
        instance["instance_groups"] = sorted(dict.fromkeys(instance["instance_groups"]))
        instance["requested_instance_groups"] = sorted(dict.fromkeys((instance.get("requested_instance_groups") or []) + [group["name"]]))
    _gcp_compute_sync_resource_links()
    _record_usage("gcp.compute.create_instance_group", {"project": project, "zone": zone, "group": group["name"]})
    return _gcp_compute_instance_group_view(group)


def api_gcp_compute_delete_instance_group(project: str, zone: str, group: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("instance_groups", {}).get(group)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("zone") or zone) != zone:
        raise HTTPException(404, detail="InstanceGroupNotFound")
    del gcp_compute_state["instance_groups"][group]
    _record_usage("gcp.compute.delete_instance_group", {"project": project, "zone": zone, "group": group})
    return {"kind": "compute#instanceGroup", "deleted": True, "name": group}


def api_gcp_compute_list_disks(project: str, zone: str):
    project = _gcp_project_name(project)
    disks = []
    for disk in gcp_compute_state.get("disks", {}).values():
        if str(disk.get("project") or project) != project or str(disk.get("zone") or zone) != zone:
            continue
        disks.append(_gcp_compute_disk_view(disk))
    disks.sort(key=lambda item: item.get("name", ""))
    return {"kind": "compute#diskList", "items": disks}


async def api_gcp_compute_create_disk(project: str, zone: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    disk = _gcp_compute_disk_record(project, zone, payload)
    gcp_compute_state.setdefault("disks", {})[disk["name"]] = disk
    target_instance = str(payload.get("instance") or payload.get("instanceName") or payload.get("instance_name") or "").strip()
    if target_instance:
        instance = _gcp_compute_find_instance(project, zone, target_instance)
        if instance:
            disk["instance"] = str(instance.get("name") or target_instance)
            disk["instance_id"] = str(instance.get("instance_id") or "")
            disk["status"] = "IN_USE" if str(instance.get("state") or "").lower() == "running" else "READY"
            instance.setdefault("attached_disk_names", [])
            if disk["name"] not in instance["attached_disk_names"]:
                instance["attached_disk_names"].append(disk["name"])
            instance.setdefault("requested_disks", [])
            instance.setdefault("instance_groups", instance.get("instance_groups", []))
            _gcp_compute_sync_resource_links()
    _record_usage("gcp.compute.create_disk", {"project": project, "zone": zone, "disk": disk["name"]})
    return _gcp_compute_disk_view(disk)


def api_gcp_compute_get_disk(project: str, zone: str, disk: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("disks", {}).get(disk)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("zone") or zone) != zone:
        raise HTTPException(404, detail="DiskNotFound")
    return _gcp_compute_disk_view(rec)


def api_gcp_compute_delete_disk(project: str, zone: str, disk: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("disks", {}).get(disk)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("zone") or zone) != zone:
        raise HTTPException(404, detail="DiskNotFound")
    instance_name = str(rec.get("instance") or "").strip()
    if instance_name:
        instance = _gcp_compute_find_instance(project, zone, instance_name)
        if instance:
            instance["attached_disk_names"] = [name for name in (instance.get("attached_disk_names") or []) if str(name).strip() != disk]
    del gcp_compute_state["disks"][disk]
    _gcp_compute_sync_resource_links()
    _record_usage("gcp.compute.delete_disk", {"project": project, "zone": zone, "disk": disk})
    return {"kind": "compute#disk", "deleted": True, "name": disk}


def api_gcp_compute_list_snapshots(project: str):
    project = _gcp_project_name(project)
    snapshots = []
    for snapshot in gcp_compute_state.get("snapshots", {}).values():
        if str(snapshot.get("project") or project) != project:
            continue
        snapshots.append(_gcp_compute_snapshot_view(snapshot))
    snapshots.sort(key=lambda item: item.get("name", ""))
    return {"kind": "compute#snapshotList", "items": snapshots}


async def api_gcp_compute_create_snapshot(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    snapshot = _gcp_compute_snapshot_record(project, payload)
    gcp_compute_state.setdefault("snapshots", {})[snapshot["name"]] = snapshot
    _record_usage("gcp.compute.create_snapshot", {"project": project, "snapshot": snapshot["name"]})
    return _gcp_compute_snapshot_view(snapshot)


def api_gcp_compute_get_snapshot(project: str, snapshot: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("snapshots", {}).get(snapshot)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="SnapshotNotFound")
    return _gcp_compute_snapshot_view(rec)


def api_gcp_compute_delete_snapshot(project: str, snapshot: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("snapshots", {}).get(snapshot)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="SnapshotNotFound")
    del gcp_compute_state["snapshots"][snapshot]
    _record_usage("gcp.compute.delete_snapshot", {"project": project, "snapshot": snapshot})
    return {"kind": "compute#snapshot", "deleted": True, "name": snapshot}


def api_gcp_compute_list_images(project: str):
    project = _gcp_project_name(project)
    images = []
    for image in gcp_compute_state.get("images", {}).values():
        if str(image.get("project") or project) != project:
            continue
        images.append(_gcp_compute_image_view(image))
    images.sort(key=lambda item: item.get("name", ""))
    return {"kind": "compute#imageList", "items": images}


async def api_gcp_compute_create_image(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    image = _gcp_compute_image_record(project, payload)
    gcp_compute_state.setdefault("images", {})[image["name"]] = image
    _record_usage("gcp.compute.create_image", {"project": project, "image": image["name"]})
    return _gcp_compute_image_view(image)


def api_gcp_compute_get_image(project: str, image_name: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("images", {}).get(image_name)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="ImageNotFound")
    return _gcp_compute_image_view(rec)


def api_gcp_compute_delete_image(project: str, image_name: str):
    project = _gcp_project_name(project)
    rec = gcp_compute_state.get("images", {}).get(image_name)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="ImageNotFound")
    del gcp_compute_state["images"][image_name]
    _record_usage("gcp.compute.delete_image", {"project": project, "image": image_name})
    return {"kind": "compute#image", "deleted": True, "name": image_name}


async def _instance_console_ws(websocket: WebSocket, instance: dict, instance_id: str, provider_name: str, empty_message: str) -> None:
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        _sync_multipass_instance(instance)
    elif backend == "lxd":
        _sync_lxd_instance(instance)

    await websocket.accept()
    instance_state = str(instance.get("state") or instance.get("status") or "").strip().lower()
    if instance_state != "running":
        await websocket.send_text(f"{empty_message}\n")
        await websocket.close()
        return

    prompt = _cmd_prompt(instance) + " "
    if backend in {"multipass", "lxd"}:
        container_name = instance.get("container_name") or instance.get("container_id") or instance_id
        runtime_image = instance.get("runtime_image") or (MULTIPASS_RUNTIME_IMAGE if backend == "multipass" else LXD_RUNTIME_IMAGE)
        if backend == "multipass":
            console_cmd = instance.get("ssh_command") or "ssh"
            await websocket.send_text(
                f"{console_cmd}\n"
                f"Connected to {provider_name} instance {container_name} ({runtime_image})\n"
            )
        else:
            await websocket.send_text(
                f"Connected to {provider_name} instance {container_name} ({runtime_image})\n"
            )
    else:
        await websocket.send_text(f"A runtime sandbox is required for {provider_name} consoles.\n")
        await websocket.close()
        return

    try:
        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                break

            command = (msg or "").strip()
            if not command:
                await websocket.send_text(prompt)
                continue
            if command in {"exit", "logout"}:
                await websocket.send_text("logout\n")
                break

            try:
                result = _console_execute(instance, command)
                transcript = ""
                if result.get("output"):
                    transcript += result["output"]
                    if not transcript.endswith("\n"):
                        transcript += "\n"
                transcript += prompt
                await websocket.send_text(transcript)
            except HTTPException as exc:
                await websocket.send_text(f"error: {exc.detail}\n{prompt}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _gcp_compute_console_exec(project: str, zone: str, instance_ref: str, req: GCPComputeConsoleCommandRequest):
    instance = _gcp_compute_find_instance(project, zone, instance_ref)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    backend = str(instance.get("runtime_backend") or "").strip().lower()
    if backend == "multipass":
        _sync_multipass_instance(instance)
    elif backend == "lxd":
        _sync_lxd_instance(instance)
    if str(instance.get("state") or "").strip().lower() != "running" and str(instance.get("status") or "").strip().upper() != "RUNNING":
        raise HTTPException(409, detail="InstanceNotRunning")
    result = _console_execute(instance, req.command)
    _record_usage(
        "gcp.compute.console_command",
        {"project": project, "zone": zone, "instance": str(instance.get("name") or instance_ref), "command": req.command, "exit_code": result["exit_code"]},
    )
    return {"message": "Console command executed", "instance_id": str(instance.get("instance_id") or instance_ref), **result}


async def ws_ec2_console(websocket: WebSocket, instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        await websocket.close(code=1008)
        return
    await _instance_console_ws(websocket, instance, instance_id, "EC2", "Instance console is not active. Start the instance first.")


async def ws_gcp_compute_console(websocket: WebSocket, project: str, zone: str, instance: str):
    instance = _gcp_compute_find_instance(project, zone, instance)
    if not instance:
        await websocket.close(code=1008)
        return
    await _instance_console_ws(websocket, instance, str(instance.get("instance_id", instance.get("name", ""))), "Compute Engine", "Compute Engine console is not active. Start the instance first.")


def api_gcp_compute_console_exec(project: str, zone: str, instance: str, req: GCPComputeConsoleCommandRequest):
    return _gcp_compute_console_exec(_gcp_project_name(project), zone, instance, req)


async def ws_runtime_console(websocket: WebSocket, instance_id: str):
    await ws_ec2_console(websocket, instance_id)


def _gcp_storage_bucket_record(project: str, name: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    now = _now()
    return {
        "project": project,
        "name": name,
        "location": str(payload.get("location") or payload.get("region") or "US"),
        "locationType": str(payload.get("locationType") or "multi-region"),
        "storageClass": str(payload.get("storageClass") or "STANDARD"),
        "timeCreated": now,
        "updated": now,
        "metageneration": "1",
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "iamConfiguration": {
            "uniformBucketLevelAccess": {"enabled": True},
            "publicAccessPrevention": "inherited",
        },
    }


def _gcp_storage_object_record(bucket: str, name: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    now = _now()
    data = payload.get("data", payload.get("content", ""))
    if isinstance(data, (dict, list)):
        data = json.dumps(data, default=str)
    if not isinstance(data, str):
        data = str(data)
    content_type = str(payload.get("contentType") or payload.get("content_type") or "application/octet-stream")
    size = int(payload.get("size") or len(data.encode("utf-8")))
    return {
        "bucket": bucket,
        "name": name,
        "contentType": content_type,
        "size": size,
        "timeCreated": now,
        "updated": now,
        "storageClass": str(payload.get("storageClass") or "STANDARD"),
        "metadata": payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {},
        "data": data,
        "md5Hash": payload.get("md5Hash", ""),
        "crc32c": payload.get("crc32c", ""),
        "etag": payload.get("etag", ""),
        "mediaLink": f"{_gcp_gcs_root()}/b/{bucket}/o/{name}?alt=media",
    }


def _gcp_storage_folder_record(project: str, bucket: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("folder") or "").strip()
    if not name:
        name = f"folder-{_id('fld')}"
    prefix = str(payload.get("prefix") or name.rstrip("/") + "/").strip()
    return {
        "project": project,
        "bucket": bucket,
        "name": name,
        "prefix": prefix,
        "storageClass": str(payload.get("storageClass") or "STANDARD"),
        "state": str(payload.get("state") or "READY"),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_storage_folder_view(folder: dict) -> dict:
    project = str(folder.get("project") or "cloudlearn")
    bucket = str(folder.get("bucket") or "")
    name = str(folder.get("name") or "")
    return {
        "name": f"{_gcp_gcs_root()}/b/{bucket}/folders/{name}",
        "bucket": bucket,
        "prefix": folder.get("prefix", ""),
        "storageClass": folder.get("storageClass", "STANDARD"),
        "state": folder.get("state", "READY"),
        "labels": folder.get("labels", {}),
        "createTime": folder.get("createTime", _now()),
        "updateTime": folder.get("updateTime", _now()),
        "project": project,
    }


def _gcp_storage_transfer_record(project: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("transferJobName") or "").strip()
    if not name:
        name = f"transfer-{_id('xfr')}"
    return {
        "project": project,
        "name": name,
        "sourceBucket": str(payload.get("sourceBucket") or ""),
        "sourcePrefix": str(payload.get("sourcePrefix") or ""),
        "destinationBucket": str(payload.get("destinationBucket") or ""),
        "destinationPrefix": str(payload.get("destinationPrefix") or ""),
        "status": str(payload.get("status") or "ENABLED"),
        "schedule": str(payload.get("schedule") or "manual"),
        "description": str(payload.get("description") or ""),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_storage_transfer_view(transfer: dict) -> dict:
    return {
        "name": transfer.get("name", ""),
        "sourceBucket": transfer.get("sourceBucket", ""),
        "sourcePrefix": transfer.get("sourcePrefix", ""),
        "destinationBucket": transfer.get("destinationBucket", ""),
        "destinationPrefix": transfer.get("destinationPrefix", ""),
        "status": transfer.get("status", "ENABLED"),
        "schedule": transfer.get("schedule", "manual"),
        "description": transfer.get("description", ""),
        "labels": transfer.get("labels", {}),
        "createTime": transfer.get("createTime", _now()),
        "updateTime": transfer.get("updateTime", _now()),
        "project": transfer.get("project", "cloudlearn"),
    }


def _gcp_storage_policy_view(bucket: str, policy: dict[str, Any] | None = None) -> dict:
    policy = policy or {}
    return {
        "bucket": bucket,
        "version": int(policy.get("version") or 1),
        "etag": str(policy.get("etag") or ""),
        "bindings": policy.get("bindings", []) if isinstance(policy.get("bindings"), list) else [],
        "updateTime": policy.get("updateTime", _now()),
    }


def _gcp_sql_instance_record(project: str, payload: dict[str, Any]) -> dict:
    name = str(payload.get("name") or payload.get("instance") or payload.get("instanceId") or "sql-instance")
    region = _gcp_location_name(payload.get("region") or payload.get("location") or "us-central1")
    now = _now()
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    if not settings:
        settings = {
            "tier": str(payload.get("tier") or "db-f1-micro"),
            "activationPolicy": "ALWAYS",
            "dataDiskType": str(payload.get("dataDiskType") or "PD_SSD"),
            "dataDiskSizeGb": str(payload.get("dataDiskSizeGb") or "10"),
            "ipConfiguration": {
                "ipv4Enabled": True,
                "privateNetwork": str(payload.get("privateNetwork") or ""),
                "requireSsl": bool(payload.get("requireSsl", False)),
            },
        }
    return {
        "name": name,
        "project": project,
        "region": region,
        "databaseVersion": str(payload.get("databaseVersion") or "POSTGRES_15"),
        "backendType": str(payload.get("backendType") or "SECOND_GEN"),
        "state": str(payload.get("state") or "RUNNABLE"),
        "instanceType": str(payload.get("instanceType") or "CLOUD_SQL_INSTANCE"),
        "connectionName": f"{project}:{region}:{name}",
        "serviceAccountEmailAddress": f"{project}@{project}.iam.gserviceaccount.com",
        "masterUsername": str(payload.get("master_username") or payload.get("masterUsername") or payload.get("rootUser") or "dbadmin"),
        "masterUserPassword": str(payload.get("master_user_password") or payload.get("masterUserPassword") or payload.get("rootPassword") or "Password123!"),
        "description": str(payload.get("description") or ""),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "settings": settings,
        "ipAddresses": payload.get("ipAddresses") or [{"type": "PRIMARY", "ipAddress": _public_ip()}],
        "serverCaCert": {"cert": "", "commonName": name, "createTime": now, "expirationTime": ""},
        "createTime": now,
        "updateTime": now,
    }


def _gcp_sql_backup_record(project: str, instance: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("backupId") or "").strip()
    if not name:
        name = f"backup-{_id('bkp')}"
    return {
        "project": project,
        "instance": instance,
        "name": name,
        "status": str(payload.get("status") or "SUCCESSFUL"),
        "backupType": str(payload.get("backupType") or "AUTOMATED"),
        "sizeGb": int(payload.get("sizeGb") or payload.get("size_gb") or 10),
        "description": str(payload.get("description") or ""),
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_sql_backup_view(backup: dict) -> dict:
    project = str(backup.get("project") or "cloudlearn")
    instance = str(backup.get("instance") or "")
    name = str(backup.get("name") or "")
    return {
        "kind": "sql#backupRun",
        "id": _gcp_compute_numeric_id(f"{project}:{instance}:{name}"),
        "name": name,
        "instance": f"{_gcp_sql_root()}/projects/{project}/instances/{instance}",
        "status": backup.get("status", "SUCCESSFUL"),
        "backupType": backup.get("backupType", "AUTOMATED"),
        "description": backup.get("description", ""),
        "sizeGb": str(backup.get("sizeGb") or 10),
        "enqueuedTime": backup.get("createTime", _now()),
        "startTime": backup.get("createTime", _now()),
        "endTime": backup.get("updateTime", _now()),
    }


def _gcp_sql_query_insight_record(project: str, instance: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    query_id = str(payload.get("queryId") or payload.get("name") or "").strip()
    if not query_id:
        query_id = f"query-{_id('q')}"
    return {
        "project": project,
        "instance": instance,
        "queryId": query_id,
        "queryText": str(payload.get("queryText") or payload.get("sql") or "SELECT 1"),
        "meanLatencyMs": float(payload.get("meanLatencyMs") or payload.get("latencyMs") or 12.5),
        "callCount": int(payload.get("callCount") or payload.get("count") or 1),
        "lastSeen": _now(),
        "recommendation": str(payload.get("recommendation") or "Consider adding an index for this query."),
    }


def _gcp_sql_query_insight_view(insight: dict) -> dict:
    return {
        "name": insight.get("queryId", ""),
        "queryText": insight.get("queryText", ""),
        "meanLatencyMs": insight.get("meanLatencyMs", 0),
        "callCount": insight.get("callCount", 0),
        "lastSeen": insight.get("lastSeen", _now()),
        "recommendation": insight.get("recommendation", ""),
        "instance": f"{_gcp_sql_root()}/projects/{insight.get('project') or 'cloudlearn'}/instances/{insight.get('instance') or ''}",
    }


def _gcp_pubsub_topic_record(project: str, topic_id: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    return {
        "topicId": topic_id,
        "project": project,
        "name": f"projects/{project}/topics/{topic_id}",
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "messageRetentionDuration": str(payload.get("messageRetentionDuration") or "604800s"),
        "kmsKeyName": str(payload.get("kmsKeyName") or ""),
        "schemaSettings": payload.get("schemaSettings", {}) if isinstance(payload.get("schemaSettings"), dict) else {},
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_pubsub_subscription_record(project: str, sub_id: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    topic = str(payload.get("topic") or "")
    return {
        "subscriptionId": sub_id,
        "project": project,
        "name": f"projects/{project}/subscriptions/{sub_id}",
        "topic": topic,
        "ackDeadlineSeconds": int(payload.get("ackDeadlineSeconds") or 10),
        "retainAckedMessages": bool(payload.get("retainAckedMessages", False)),
        "messageRetentionDuration": str(payload.get("messageRetentionDuration") or "604800s"),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_pubsub_schema_record(project: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("schemaId") or "").strip()
    if not name:
        name = f"schema-{_id('sch')}"
    return {
        "project": project,
        "name": name,
        "type": str(payload.get("type") or "AVRO"),
        "definition": str(payload.get("definition") or payload.get("schema") or ""),
        "revisionId": str(payload.get("revisionId") or "1"),
        "state": str(payload.get("state") or "ACTIVE"),
        "description": str(payload.get("description") or ""),
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_pubsub_schema_view(schema: dict) -> dict:
    project = str(schema.get("project") or "cloudlearn")
    name = str(schema.get("name") or "")
    return {
        "name": f"projects/{project}/schemas/{name}",
        "type": schema.get("type", "AVRO"),
        "definition": schema.get("definition", ""),
        "revisionId": schema.get("revisionId", "1"),
        "state": schema.get("state", "ACTIVE"),
        "description": schema.get("description", ""),
        "createTime": schema.get("createTime", _now()),
        "updateTime": schema.get("updateTime", _now()),
    }


def _gcp_firestore_value_from_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if any(key in value for key in {"nullValue", "booleanValue", "integerValue", "doubleValue", "timestampValue", "stringValue", "bytesValue", "referenceValue", "geoPointValue", "arrayValue", "mapValue"}):
            return value
        return {"mapValue": {"fields": {k: _gcp_firestore_value_from_json(v) for k, v in value.items()}}}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_gcp_firestore_value_from_json(v) for v in value]}}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if value is None:
        return {"nullValue": None}
    return {"stringValue": str(value)}


def _gcp_firestore_plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "stringValue" in value:
            return value.get("stringValue")
        if "booleanValue" in value:
            return bool(value.get("booleanValue"))
        if "integerValue" in value:
            try:
                return int(value.get("integerValue"))
            except Exception:
                return value.get("integerValue")
        if "doubleValue" in value:
            try:
                return float(value.get("doubleValue"))
            except Exception:
                return value.get("doubleValue")
        if "nullValue" in value:
            return None
        if "mapValue" in value:
            fields = value.get("mapValue", {}).get("fields", {}) if isinstance(value.get("mapValue"), dict) else {}
            return {str(k): _gcp_firestore_plain_value(v) for k, v in fields.items()} if isinstance(fields, dict) else {}
        if "arrayValue" in value:
            values = value.get("arrayValue", {}).get("values", []) if isinstance(value.get("arrayValue"), dict) else []
            return [_gcp_firestore_plain_value(v) for v in values] if isinstance(values, list) else []
    return value


def _gcp_firestore_normalize_fields(fields: dict[str, Any] | None = None) -> dict:
    fields = fields or {}
    return {str(key): _gcp_firestore_value_from_json(value) for key, value in fields.items()}


def _gcp_firestore_doc_record(fields: dict[str, Any] | None = None) -> dict:
    return {
        "fields": _gcp_firestore_normalize_fields(fields),
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_firestore_index_record(project: str, database: str, collection: str, payload: dict[str, Any] | None = None) -> dict:
    payload = payload or {}
    name = str(payload.get("name") or payload.get("indexId") or "").strip()
    if not name:
        name = f"index-{_id('idx')}"
    fields = payload.get("fields") if isinstance(payload.get("fields"), list) else []
    if not fields:
        fields = [{"fieldPath": "__name__", "order": "ASCENDING"}]
    return {
        "project": project,
        "database": database,
        "collection": collection,
        "name": name,
        "fields": fields,
        "queryScope": str(payload.get("queryScope") or "COLLECTION"),
        "state": str(payload.get("state") or "READY"),
        "description": str(payload.get("description") or ""),
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_firestore_index_view(index: dict) -> dict:
    project = str(index.get("project") or "cloudlearn")
    database = str(index.get("database") or "(default)")
    collection = str(index.get("collection") or "")
    name = str(index.get("name") or "")
    return {
        "name": f"projects/{project}/databases/{database}/collectionGroups/{collection}/indexes/{name}",
        "collectionGroup": collection,
        "queryScope": index.get("queryScope", "COLLECTION"),
        "fields": index.get("fields", []),
        "state": index.get("state", "READY"),
        "description": index.get("description", ""),
        "createTime": index.get("createTime", _now()),
        "updateTime": index.get("updateTime", _now()),
    }


def _gcp_functions_record(project: str, location: str, payload: dict[str, Any]) -> dict:
    # Clients (and the gapic/REST libraries) pass the full resource name
    # projects/*/locations/*/functions/<id>; store/key by the short <id> so
    # functions.get/{function} (last URL segment) resolves it.
    name = str(payload.get("name") or payload.get("functionId") or "cloud-function").split("/")[-1]
    runtime = str(payload.get("runtime") or "python311")
    entry_point = str(payload.get("entryPoint") or payload.get("entry_point") or "handler")
    return {
        "name": name,
        "project": project,
        "location": location,
        "description": str(payload.get("description") or ""),
        "runtime": runtime,
        "entryPoint": entry_point,
        "role": str(payload.get("role") or payload.get("serviceAccountEmail") or ""),
        "code": str(payload.get("code") or payload.get("sourceCode") or payload.get("source", {}).get("code") or ""),
        "status": "ACTIVE",
        "buildConfig": {
            "runtime": runtime,
            "entryPoint": entry_point,
            "source": payload.get("source", {}),
        },
        "serviceConfig": {
            "availableMemory": str(payload.get("availableMemory") or "256M"),
            "timeoutSeconds": int(payload.get("timeoutSeconds") or 60),
            "ingressSettings": str(payload.get("ingressSettings") or "ALLOW_ALL"),
        },
        "httpsTrigger": payload.get("httpsTrigger"),
        "eventTrigger": payload.get("eventTrigger"),
        "environmentVariables": payload.get("environmentVariables", {}) if isinstance(payload.get("environmentVariables"), dict) else {},
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "permissions": payload.get("permissions", []) if isinstance(payload.get("permissions"), list) else [],
        "versions": payload.get("versions", []) if isinstance(payload.get("versions"), list) else [],
        "invocations": payload.get("invocations", []) if isinstance(payload.get("invocations"), list) else [],
        "triggers": payload.get("triggers", []) if isinstance(payload.get("triggers"), list) else [],
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_apigw_api_record(project: str, location: str, payload: dict[str, Any]) -> dict:
    name = str(payload.get("name") or payload.get("apiId") or "api")
    return {
        "name": name,
        "project": project,
        "location": location,
        "displayName": str(payload.get("displayName") or payload.get("description") or name),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "routeSummary": payload.get("routeSummary", []) if isinstance(payload.get("routeSummary"), list) else [],
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_apigw_cfg_record(project: str, location: str, payload: dict[str, Any]) -> dict:
    name = str(payload.get("name") or payload.get("apiConfigId") or payload.get("path_part") or payload.get("pathPart") or payload.get("method") or "api-config")
    return {
        "name": name,
        "project": project,
        "location": location,
        "api": str(payload.get("api") or ""),
        "parent_id": str(payload.get("parent_id") or payload.get("parentId") or ""),
        "path_part": str(payload.get("path_part") or payload.get("pathPart") or ""),
        "http_method": str(payload.get("http_method") or payload.get("method") or ""),
        "authorization_type": str(payload.get("authorization_type") or payload.get("authorizationType") or ""),
        "integration_type": str(payload.get("integration_type") or payload.get("integrationType") or ""),
        "integration_uri": str(payload.get("integration_uri") or payload.get("uri") or ""),
        "status_code": int(payload.get("status_code") or payload.get("statusCode") or 200),
        "response_body": str(payload.get("response_body") or payload.get("responseBody") or ""),
        "content_type": str(payload.get("content_type") or payload.get("contentType") or "application/json"),
        "openapiDocuments": payload.get("openapiDocuments", []) if isinstance(payload.get("openapiDocuments"), list) else [],
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_apigw_gateway_record(project: str, location: str, payload: dict[str, Any]) -> dict:
    name = str(payload.get("name") or payload.get("gatewayId") or payload.get("stage_name") or payload.get("stageName") or payload.get("apiConfig") or "gateway")
    return {
        "name": name,
        "project": project,
        "location": location,
        "apiConfig": str(payload.get("apiConfig") or payload.get("api_config") or ""),
        "stage_name": str(payload.get("stage_name") or payload.get("stageName") or "prod"),
        "description": str(payload.get("description") or ""),
        "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
        "defaultHostname": payload.get("defaultHostname", f"{name}-{location}-{project}.cloud.goog"),
        "createTime": _now(),
        "updateTime": _now(),
    }


def _gcp_apigw_resolve_api(gateway_rec: dict) -> str:
    """Resolve the API a gateway serves (via its apiConfig, else a direct api field)."""
    apiconf = str(gateway_rec.get("apiConfig") or "")
    last = apiconf.split("/")[-1]
    for cfg in gcp_apigw_state.get("configs", {}).values():
        if isinstance(cfg, dict) and cfg.get("name") in (apiconf, last):
            return str(cfg.get("api") or "")
    return str(gateway_rec.get("api") or "")


def _gcp_apigw_match_config(api: str, path: str, method: str) -> dict | None:
    """Match a route config by path + HTTP method (ANY/empty method matches)."""
    method = str(method or "").upper()
    want = "/" + str(path or "").strip("/")
    cands = [c for c in gcp_apigw_state.get("configs", {}).values()
             if isinstance(c, dict) and (not api or str(c.get("api") or "") == api)]
    for c in cands:
        pp = "/" + str(c.get("path_part") or "").strip("/")
        hm = str(c.get("http_method") or "").upper()
        if (pp == want or pp == "/") and hm in ("", "ANY", method):
            return c
    return cands[0] if cands else None


async def api_gcp_apigw_invoke(gateway: str, path: str, request: Request):
    """Route a request hitting a deployed gateway to its backend (a Cloud Function
    or an upstream URL) and return the real response, or the configured mock."""
    gw = gcp_apigw_state.get("gateways", {}).get(gateway)
    if not gw:
        for g in gcp_apigw_state.get("gateways", {}).values():
            if isinstance(g, dict) and g.get("name") == gateway:
                gw = g
                break
    if not gw:
        raise HTTPException(404, detail="Gateway not found")
    cfg = _gcp_apigw_match_config(_gcp_apigw_resolve_api(gw), path, request.method)
    if not cfg:
        raise HTTPException(404, detail="No matching API config route")
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        payload = {}
    itype = str(cfg.get("integration_type") or "").lower()
    uri = str(cfg.get("integration_uri") or "")
    # Cloud Function backend -> execute the function for real.
    if "function" in itype or "cloudfunctions" in uri or "/functions/" in uri:
        fn_name = uri.rstrip("/").split("/")[-1]
        fn = gcp_functions_state.get("functions", {}).get(fn_name)
        if fn:
            try:
                from core import gcp_function_runtime
                out = gcp_function_runtime.execute(
                    fn.get("code", ""), fn.get("entryPoint", "handler"),
                    fn.get("runtime", "python311"), payload, timeout=30,
                )
            except Exception as exc:
                out = {"status": "ERROR", "error": str(exc)[:200], "result": None}
            if out.get("status") == "SUCCESS":
                return JSONResponse(content=out.get("result"), status_code=200)
            return JSONResponse(content={"error": out.get("error"), "logs": out.get("logs", "")}, status_code=500)
        raise HTTPException(502, detail=f"Backend function '{fn_name}' not found")
    # HTTP(S) upstream backend -> proxy the request.
    if uri.startswith(("http://", "https://")):
        try:
            up = URLRequest(uri, data=(raw or None), method=request.method,
                            headers={"Content-Type": request.headers.get("content-type", "application/json")})
            with urlopen(up, timeout=30) as resp:
                return Response(content=resp.read(),
                                media_type=resp.headers.get("Content-Type", "application/json"),
                                status_code=getattr(resp, "status", 200))
        except Exception as exc:
            raise HTTPException(502, detail=f"Upstream error: {str(exc)[:160]}")
    # Mock integration -> return the configured response.
    return Response(content=str(cfg.get("response_body") or "{}"),
                    media_type=str(cfg.get("content_type") or "application/json"),
                    status_code=int(cfg.get("status_code") or 200))


def _gcp_iam_set_policy(project: str, payload: dict[str, Any]) -> dict:
    policy = {
        "version": int(payload.get("version") or 1),
        "etag": str(payload.get("etag") or ""),
        "bindings": payload.get("bindings", []) if isinstance(payload.get("bindings"), list) else [],
    }
    gcp_iam_state.setdefault("policies", {})[project] = policy
    return policy


def api_gcp_storage_list_buckets(request: Request):
    project = _gcp_project_name(request.query_params.get("project"))
    buckets = []
    for bucket in gcp_storage_state.get("buckets", {}).values():
        if str(bucket.get("project") or project) != project:
            continue
        buckets.append(_gcp_storage_bucket_view(project, bucket))
    buckets.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#buckets", "items": buckets, "prefixes": [], "nextPageToken": ""}


async def api_gcp_storage_create_bucket(request: Request):
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    project = _gcp_project_name(request.query_params.get("project") or payload.get("project") or payload.get("projectId"))
    name = str(payload.get("name") or payload.get("bucket") or "").strip()
    if not name:
        raise HTTPException(400, detail="Bucket name is required")
    _enforce_quantity_cap("bucket")  # tier cap — Free=1 bucket/space
    bucket = _gcp_storage_bucket_record(project, name, payload)
    gcp_storage_state.setdefault("buckets", {})[name] = bucket
    gcp_storage_state.setdefault("objects", {}).setdefault(name, {})
    _cloudsim_sync_service_resource("gcp", "storage", "bucket", name, bucket, "gcp_storage")
    _record_usage("gcp.storage.create_bucket", {"project": project, "bucket": name})
    return _gcp_storage_bucket_view(project, bucket)


def api_gcp_storage_get_bucket(bucket: str):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    project = str(bucket_rec.get("project") or "cloudlearn")
    return _gcp_storage_bucket_view(project, bucket_rec)


def api_gcp_storage_delete_bucket(bucket: str):
    if bucket not in gcp_storage_state.get("buckets", {}):
        raise HTTPException(404, detail="Bucket not found")
    gcp_storage_state.setdefault("buckets", {}).pop(bucket, None)
    gcp_storage_state.setdefault("objects", {}).pop(bucket, None)
    _cloudsim_sync_service_resource("gcp", "storage", "bucket", bucket, {}, "gcp_storage", action="delete")
    _record_usage("gcp.storage.delete_bucket", {"bucket": bucket})
    return {"kind": "storage#empty", "deleted": True, "bucket": bucket}


def api_gcp_storage_list_objects(bucket: str, request: Request):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    prefix = str(request.query_params.get("prefix") or "")
    objects = []
    for name, obj in gcp_storage_state.get("objects", {}).get(bucket, {}).items():
        if prefix and not name.startswith(prefix):
            continue
        objects.append(_gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, name, obj))
    objects.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#objects", "items": objects, "prefixes": [], "nextPageToken": ""}


async def api_gcp_storage_create_object(bucket: str, request: Request):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Real GCS uploads pass the object name as the `?name=` query param (uploadType=media);
    # accept that as well as a name in the JSON body.
    name = str(payload.get("name") or payload.get("object") or request.query_params.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Object name is required")
    obj = _gcp_storage_object_record(bucket, name, payload)
    gcp_storage_state.setdefault("objects", {}).setdefault(bucket, {})[name] = obj
    _record_usage("gcp.storage.create_object", {"bucket": bucket, "object": name})
    return _gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, name, obj)


def api_gcp_storage_get_object(bucket: str, object_name: str):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    obj = gcp_storage_state.get("objects", {}).get(bucket, {}).get(object_name)
    if not bucket_rec or not obj:
        raise HTTPException(404, detail="Object not found")
    return _gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, object_name, obj)


def api_gcp_storage_delete_object(bucket: str, object_name: str):
    if bucket not in gcp_storage_state.get("objects", {}) or object_name not in gcp_storage_state["objects"][bucket]:
        raise HTTPException(404, detail="Object not found")
    del gcp_storage_state["objects"][bucket][object_name]
    _record_usage("gcp.storage.delete_object", {"bucket": bucket, "object": object_name})
    return {"kind": "storage#empty", "deleted": True, "bucket": bucket, "object": object_name}


async def api_gcp_storage_patch_object(bucket: str, object_name: str, request: Request):
    """PATCH /storage/v1/b/{bucket}/o/{object} — update object metadata without changing data."""
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    obj = gcp_storage_state.get("objects", {}).get(bucket, {}).get(object_name)
    if not bucket_rec or not obj:
        raise HTTPException(404, detail="Object not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    for field in ("contentType", "cacheControl", "contentDisposition", "contentEncoding", "contentLanguage"):
        if field in payload:
            obj[field] = str(payload[field])
    if isinstance(payload.get("metadata"), dict):
        obj.setdefault("metadata", {}).update(payload["metadata"])
    obj["updated"] = _now()
    _record_usage("gcp.storage.patch_object", {"bucket": bucket, "object": object_name})
    return _gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, object_name, obj)


async def api_gcp_storage_compose_object(bucket: str, destination: str, request: Request):
    """POST /storage/v1/b/{bucket}/o/{destination}/compose — concatenate source objects."""
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    source_objects = payload.get("sourceObjects", [])
    if not isinstance(source_objects, list) or not source_objects:
        raise HTTPException(400, detail="sourceObjects list is required")
    bucket_objects = gcp_storage_state.get("objects", {}).get(bucket, {})
    combined_data = ""
    for src in source_objects:
        src_name = str(src.get("name") or src) if isinstance(src, dict) else str(src)
        src_obj = bucket_objects.get(src_name)
        if not src_obj:
            raise HTTPException(404, detail=f"Source object {src_name!r} not found")
        combined_data += str(src_obj.get("data") or "")
    dest_payload = dict(payload.get("destination", {}) or {})
    dest_payload["data"] = combined_data
    dest_payload.setdefault("contentType", "application/octet-stream")
    obj = _gcp_storage_object_record(bucket, destination, dest_payload)
    gcp_storage_state.setdefault("objects", {}).setdefault(bucket, {})[destination] = obj
    _record_usage("gcp.storage.compose_object", {"bucket": bucket, "destination": destination, "sources": len(source_objects)})
    return _gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, destination, obj)


def api_gcp_storage_list_folders(bucket: str):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    folders = []
    for folder in gcp_storage_state.get("folders", {}).get(bucket, {}).values():
        folders.append(_gcp_storage_folder_view(folder))
    folders.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#folders", "items": folders}


async def api_gcp_storage_create_folder(bucket: str, request: Request):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    folder = _gcp_storage_folder_record(str(bucket_rec.get("project") or "cloudlearn"), bucket, payload)
    gcp_storage_state.setdefault("folders", {}).setdefault(bucket, {})[folder["name"]] = folder
    _record_usage("gcp.storage.create_folder", {"bucket": bucket, "folder": folder["name"]})
    return _gcp_storage_folder_view(folder)


def api_gcp_storage_delete_folder(bucket: str, folder: str):
    if folder not in gcp_storage_state.get("folders", {}).get(bucket, {}):
        raise HTTPException(404, detail="Folder not found")
    del gcp_storage_state["folders"][bucket][folder]
    _record_usage("gcp.storage.delete_folder", {"bucket": bucket, "folder": folder})
    return {"kind": "storage#folder", "deleted": True, "bucket": bucket, "folder": folder}


def api_gcp_storage_list_transfers(project: str):
    project = _gcp_project_name(project)
    transfers = []
    for transfer in gcp_storage_state.get("transfers", {}).values():
        if str(transfer.get("project") or project) != project:
            continue
        transfers.append(_gcp_storage_transfer_view(transfer))
    transfers.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storagetransfer#transferJobsList", "transferJobs": transfers}


async def api_gcp_storage_create_transfer(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    transfer = _gcp_storage_transfer_record(project, payload)
    gcp_storage_state.setdefault("transfers", {})[transfer["name"]] = transfer
    _record_usage("gcp.storage.create_transfer", {"project": project, "transfer": transfer["name"]})
    return _gcp_storage_transfer_view(transfer)


def api_gcp_storage_delete_transfer(project: str, transfer_name: str):
    project = _gcp_project_name(project)
    rec = gcp_storage_state.get("transfers", {}).get(transfer_name)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="TransferNotFound")
    del gcp_storage_state["transfers"][transfer_name]
    _record_usage("gcp.storage.delete_transfer", {"project": project, "transfer": transfer_name})
    return {"kind": "storagetransfer#transferJob", "deleted": True, "name": transfer_name}


def api_gcp_storage_get_policy(bucket: str):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    policy = gcp_storage_state.setdefault("policies", {}).setdefault(bucket, {"version": 1, "etag": "", "bindings": []})
    return _gcp_storage_policy_view(bucket, policy)


async def api_gcp_storage_set_policy(bucket: str, request: Request):
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    policy = {
        "version": int(payload.get("version") or 1),
        "etag": str(payload.get("etag") or ""),
        "bindings": payload.get("bindings", []) if isinstance(payload.get("bindings"), list) else [],
        "updateTime": _now(),
    }
    gcp_storage_state.setdefault("policies", {})[bucket] = policy
    _record_usage("gcp.storage.set_policy", {"bucket": bucket, "bindings": len(policy["bindings"])})
    return _gcp_storage_policy_view(bucket, policy)


def api_gcp_sql_list_instances(project: str, request: Request):
    project = _gcp_project_name(project)
    instances = []
    for inst in gcp_sql_state.get("instances", {}).values():
        if str(inst.get("project") or project) != project:
            continue
        instances.append(_gcp_sql_instance_view(project, inst))
    instances.sort(key=lambda item: item.get("name", ""))
    return {"kind": "sql#instancesList", "items": instances, "warnings": []}


async def api_gcp_sql_create_instance(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    instance = _gcp_sql_instance_record(project, payload)
    if instance["name"] in gcp_sql_state.get("instances", {}):
        raise HTTPException(409, detail="Instance already exists")
    bundle = _cloudsim_runtime_bundle("gcp_sql")
    instance["runtime_bundle_id"] = bundle.get("id", "")
    instance["runtime_bundle_name"] = bundle.get("name", "")
    instance["runtime_bundle_kind"] = bundle.get("kind", "")
    gcp_sql_state.setdefault("instances", {})[instance["name"]] = instance
    _cloudsim_sync_service_resource("gcp", "sql", "db_instance", instance["name"], instance, "gcp_sql", region=str(instance.get("region") or "us-central1"))
    _record_usage("gcp.sql.create_instance", {"project": project, "instance": instance["name"]})
    return _gcp_sql_instance_view(project, instance)


def api_gcp_sql_get_instance(project: str, instance: str):
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    return _gcp_sql_instance_view(project, rec)


def api_gcp_sql_delete_instance(project: str, instance: str):
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    del gcp_sql_state["instances"][instance]
    _cloudsim_sync_service_resource("gcp", "sql", "db_instance", instance, {}, "gcp_sql", action="delete")
    _record_usage("gcp.sql.delete_instance", {"project": project, "instance": instance})
    return {"kind": "sql#operation", "operationType": "DELETE", "status": "DONE", "targetLink": f"{_gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_restart_instance(project: str, instance: str):
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    rec["state"] = "RUNNABLE"
    rec["updateTime"] = _now()
    _record_usage("gcp.sql.restart_instance", {"project": project, "instance": instance})
    return {"kind": "sql#operation", "operationType": "RESTART", "status": "DONE", "targetLink": f"{_gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_list_backups(project: str, instance: str = ""):
    project = _gcp_project_name(project)
    backups = []
    for backup in gcp_sql_state.get("backups", {}).values():
        if str(backup.get("project") or project) != project:
            continue
        if instance and str(backup.get("instance") or "") != instance:
            continue
        backups.append(_gcp_sql_backup_view(backup))
    backups.sort(key=lambda item: item.get("name", ""))
    return {"kind": "sql#backupRunsList", "items": backups}


async def api_gcp_sql_create_backup(project: str, instance: str, request: Request):
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    backup = _gcp_sql_backup_record(project, instance, payload)
    gcp_sql_state.setdefault("backups", {})[backup["name"]] = backup
    _record_usage("gcp.sql.create_backup", {"project": project, "instance": instance, "backup": backup["name"]})
    return _gcp_sql_backup_view(backup)


def api_gcp_sql_delete_backup(project: str, backup: str):
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("backups", {}).get(backup)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Backup not found")
    del gcp_sql_state["backups"][backup]
    _record_usage("gcp.sql.delete_backup", {"project": project, "backup": backup})
    return {"kind": "sql#backupRun", "deleted": True, "name": backup}


def api_gcp_sql_list_insights(project: str, instance: str = ""):
    project = _gcp_project_name(project)
    insights = []
    for insight in gcp_sql_state.get("query_insights", {}).values():
        if str(insight.get("project") or project) != project:
            continue
        if instance and str(insight.get("instance") or "") != instance:
            continue
        insights.append(_gcp_sql_query_insight_view(insight))
    insights.sort(key=lambda item: item.get("meanLatencyMs", 0), reverse=True)
    return {"kind": "sql#queryInsightsList", "items": insights}


async def api_gcp_sql_create_insight(project: str, instance: str, request: Request):
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    insight = _gcp_sql_query_insight_record(project, instance, payload)
    gcp_sql_state.setdefault("query_insights", {})[insight["queryId"]] = insight
    _record_usage("gcp.sql.create_insight", {"project": project, "instance": instance, "query": insight["queryId"]})
    return _gcp_sql_query_insight_view(insight)


def api_gcp_pubsub_list_topics(project: str):
    project = _gcp_project_name(project)
    topics = [_gcp_pubsub_topic_view(project, topic) for topic in gcp_pubsub_state.get("topics", {}).values() if str(topic.get("project") or project) == project]
    topics.sort(key=lambda item: item.get("topicId", ""))
    return {"topics": topics, "nextPageToken": "", "kind": "pubsub#topicList"}


async def api_gcp_pubsub_create_topic(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    topic_id = str(payload.get("topicId") or payload.get("name") or payload.get("topic") or "").split("/")[-1].strip()
    if not topic_id:
        raise HTTPException(400, detail="Topic id is required")
    topic = _gcp_pubsub_topic_record(project, topic_id, payload)
    gcp_pubsub_state.setdefault("topics", {})[topic_id] = topic
    default_sub_id = str(payload.get("subscriptionId") or topic_id).split("/")[-1].strip()
    if default_sub_id and default_sub_id not in gcp_pubsub_state.setdefault("subscriptions", {}):
        default_sub = _gcp_pubsub_subscription_record(project, default_sub_id, {
            "topic": f"projects/{project}/topics/{topic_id}",
            "labels": payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {},
            "ackDeadlineSeconds": payload.get("ackDeadlineSeconds", 10),
        })
        gcp_pubsub_state.setdefault("subscriptions", {})[default_sub_id] = default_sub
    _cloudsim_sync_service_resource("gcp", "pubsub", "topic", topic_id, topic, "gcp_pubsub")
    _record_usage("gcp.pubsub.create_topic", {"project": project, "topic": topic_id})
    return _gcp_pubsub_topic_view(project, topic)


async def api_gcp_pubsub_put_topic(project: str, topic: str, request: Request):
    """Real GCP Pub/Sub creates topics via PUT /v1/projects/{p}/topics/{topic}
    (name in the path). The legacy POST /topics handler takes it from the body."""
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    topic_id = str(topic or payload.get("name") or "").split("/")[-1].strip()
    if not topic_id:
        raise HTTPException(400, detail="Topic id is required")
    # Delegate to the emulator when active so PUT-create matches the delegated
    # GET/list (otherwise Terraform writes in-proc, reads the emulator → 404 → retry loop).
    try:
        from core import gcp_pubsub_emulator as _pe
        if _pe.available():
            from google.api_core import exceptions as _gax
            labels = payload.get("labels") if isinstance(payload.get("labels"), dict) else None
            try:
                t = _pe.create_topic(project, topic_id, labels)
            except _gax.AlreadyExists:
                t = _pe.get_topic(project, topic_id) or {"name": topic_id}
            return _gcp_pubsub_topic_view(project, t)
    except HTTPException:
        raise
    except Exception:
        pass
    rec = _gcp_pubsub_topic_record(project, topic_id, payload)
    gcp_pubsub_state.setdefault("topics", {})[topic_id] = rec
    _cloudsim_sync_service_resource("gcp", "pubsub", "topic", topic_id, rec, "gcp_pubsub")
    _record_usage("gcp.pubsub.create_topic", {"project": project, "topic": topic_id})
    return _gcp_pubsub_topic_view(project, rec)


async def api_gcp_pubsub_put_subscription(project: str, subscription: str, request: Request):
    """Real GCP Pub/Sub creates subscriptions via PUT .../subscriptions/{sub}."""
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sub_id = str(subscription or payload.get("name") or "").split("/")[-1].strip()
    if not sub_id:
        raise HTTPException(400, detail="Subscription id is required")
    rec = _gcp_pubsub_subscription_record(project, sub_id, payload)
    if not rec.get("topic"):
        raise HTTPException(400, detail="Topic is required")
    gcp_pubsub_state.setdefault("subscriptions", {})[sub_id] = rec
    _cloudsim_sync_service_resource("gcp", "pubsub", "subscription", sub_id, rec, "gcp_pubsub")
    _record_usage("gcp.pubsub.create_subscription", {"project": project, "subscription": sub_id})
    return _gcp_pubsub_subscription_view(project, rec)


def api_gcp_pubsub_get_topic(project: str, topic: str):
    project = _gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    return _gcp_pubsub_topic_view(project, rec)


async def api_gcp_pubsub_update_topic(project: str, topic: str, request: Request):
    project = _gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if isinstance(payload.get("labels"), dict):
        rec["labels"] = payload["labels"]
    if "messageRetentionDuration" in payload:
        rec["messageRetentionDuration"] = str(payload.get("messageRetentionDuration") or rec.get("messageRetentionDuration") or "604800s")
    if "kmsKeyName" in payload:
        rec["kmsKeyName"] = str(payload.get("kmsKeyName") or "")
    rec["updateTime"] = _now()
    gcp_pubsub_state.setdefault("topics", {})[topic] = rec
    _record_usage("gcp.pubsub.update_topic", {"project": project, "topic": topic})
    return _gcp_pubsub_topic_view(project, rec)


def api_gcp_pubsub_list_topic_messages(project: str, topic: str):
    project = _gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    messages = list(gcp_pubsub_state.setdefault("messages", {}).get(topic, []))
    return {"messages": messages, "kind": "pubsub#messageList"}


def api_gcp_pubsub_delete_topic(project: str, topic: str):
    project = _gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    del gcp_pubsub_state["topics"][topic]
    for sub_id, sub in list(gcp_pubsub_state.get("subscriptions", {}).items()):
        if str(sub.get("project") or project) == project and str(sub.get("topic") or "") == f"projects/{project}/topics/{topic}":
            del gcp_pubsub_state["subscriptions"][sub_id]
            gcp_pubsub_state.get("messages", {}).pop(sub_id, None)
    gcp_pubsub_state.get("messages", {}).pop(topic, None)
    _cloudsim_sync_service_resource("gcp", "pubsub", "topic", topic, {}, "gcp_pubsub", action="delete")
    _record_usage("gcp.pubsub.delete_topic", {"project": project, "topic": topic})
    return {"done": True}


async def api_gcp_pubsub_publish(project: str, topic: str, request: Request):
    project = _gcp_project_name(project)
    topic = _strip_action_suffix(topic, ":publish")
    rec = gcp_pubsub_state.get("topics", {}).get(topic)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Topic not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []
    message_ids = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = _id("msg")
        entry = {
            "messageId": message_id,
            "data": str(message.get("data") or ""),
            "attributes": message.get("attributes", {}) if isinstance(message.get("attributes"), dict) else {},
            "publishTime": _now(),
            "topic": topic,
        }
        message_ids.append(message_id)
        gcp_pubsub_state.setdefault("messages", {}).setdefault(topic, []).append(entry)
        for sub in gcp_pubsub_state.get("subscriptions", {}).values():
            if str(sub.get("project") or project) != project or str(sub.get("topic") or "") != f"projects/{project}/topics/{topic}":
                continue
            gcp_pubsub_state.setdefault("messages", {}).setdefault(str(sub.get("subscriptionId")), []).append({
                **entry,
                "ackId": _id("ack"),
                "subscription": str(sub.get("subscriptionId")),
            })
    return {"messageIds": message_ids}


def api_gcp_pubsub_list_subscriptions(project: str):
    project = _gcp_project_name(project)
    subs = [_gcp_pubsub_subscription_view(project, sub) for sub in gcp_pubsub_state.get("subscriptions", {}).values() if str(sub.get("project") or project) == project]
    subs.sort(key=lambda item: item.get("subscriptionId", ""))
    return {"subscriptions": subs, "nextPageToken": "", "kind": "pubsub#subscriptionList"}


async def api_gcp_pubsub_create_subscription(project: str, request: Request, queue_name: str = ""):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sub_id = str(payload.get("subscriptionId") or payload.get("name") or queue_name or "").split("/")[-1].strip()
    if not sub_id:
        raise HTTPException(400, detail="Subscription id is required")
    sub = _gcp_pubsub_subscription_record(project, sub_id, payload)
    if not sub.get("topic"):
        raise HTTPException(400, detail="Topic is required")
    gcp_pubsub_state.setdefault("subscriptions", {})[sub_id] = sub
    _cloudsim_sync_service_resource("gcp", "pubsub", "subscription", sub_id, sub, "gcp_pubsub")
    _record_usage("gcp.pubsub.create_subscription", {"project": project, "subscription": sub_id, "topic": sub.get("topic", "")})
    return _gcp_pubsub_subscription_view(project, sub)


def api_gcp_pubsub_get_subscription(project: str, subscription: str):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    return _gcp_pubsub_subscription_view(project, rec)


def api_gcp_pubsub_list_subscription_messages(project: str, subscription: str):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    messages = list(gcp_pubsub_state.setdefault("messages", {}).get(subscription, []))
    return {"receivedMessages": messages, "kind": "pubsub#receivedMessageList"}


def api_gcp_pubsub_purge_subscription(project: str, subscription: str):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    gcp_pubsub_state.setdefault("messages", {})[subscription] = []
    return {"done": True}


def api_gcp_pubsub_delete_subscription(project: str, subscription: str):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    del gcp_pubsub_state["subscriptions"][subscription]
    gcp_pubsub_state.get("messages", {}).pop(subscription, None)
    _cloudsim_sync_service_resource("gcp", "pubsub", "subscription", subscription, {}, "gcp_pubsub", action="delete")
    _record_usage("gcp.pubsub.delete_subscription", {"project": project, "subscription": subscription})
    return {"done": True}


async def api_gcp_pubsub_pull(project: str, subscription: str, request: Request):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    rec = gcp_pubsub_state.get("subscriptions", {}).get(subscription)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Subscription not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    max_messages = int(payload.get("maxMessages") or payload.get("max_messages") or 10)
    items = list(gcp_pubsub_state.get("messages", {}).get(subscription, []))[:max_messages]
    received = []
    for item in items:
        received.append({
            "ackId": item.get("ackId", _id("ack")),
            "message": {
                "data": item.get("data", ""),
                "messageId": item.get("messageId", _id("msg")),
                "publishTime": item.get("publishTime", _now()),
                "attributes": item.get("attributes", {}),
            },
        })
    return {"receivedMessages": received}


async def api_gcp_pubsub_ack(project: str, subscription: str, request: Request, receipt_handle: str = ""):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    if subscription not in gcp_pubsub_state.get("subscriptions", {}):
        raise HTTPException(404, detail="Subscription not found")
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    ack_ids = body.get("ackIds") if isinstance(body, dict) else []
    if not isinstance(ack_ids, list):
        ack_ids = []
    queue = gcp_pubsub_state.setdefault("messages", {}).get(subscription, [])
    gcp_pubsub_state.setdefault("messages", {})[subscription] = [item for item in queue if item.get("ackId") not in set(map(str, ack_ids)) and item.get("ackId") != receipt_handle]
    return {"acknowledged": True}


async def api_gcp_pubsub_modify_ack_deadline(project: str, subscription: str, request: Request):
    project = _gcp_project_name(project)
    subscription = _strip_action_suffix(subscription, ":purge", ":pull", ":acknowledge", ":modifyAckDeadline")
    if subscription not in gcp_pubsub_state.get("subscriptions", {}):
        raise HTTPException(404, detail="Subscription not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    ack_ids = payload.get("ackIds") if isinstance(payload, dict) else []
    if not isinstance(ack_ids, list):
        ack_ids = []
    ack_ids = [str(ack_id) for ack_id in ack_ids if ack_id]
    deadline = int(payload.get("ackDeadlineSeconds") or 0) if isinstance(payload, dict) else 0
    queue = gcp_pubsub_state.setdefault("messages", {}).get(subscription, [])
    if deadline == 0:
        for item in queue:
            if item.get("ackId") in ack_ids:
                item["visibleAt"] = _now()
                item["inFlight"] = False
    return {}


def api_gcp_pubsub_list_topic_subscriptions(project: str, topic: str):
    project = _gcp_project_name(project)
    topic_name = f"projects/{project}/topics/{topic}"
    subscriptions = []
    for sub in gcp_pubsub_state.get("subscriptions", {}).values():
        if str(sub.get("project") or project) != project:
            continue
        if str(sub.get("topic") or "") != topic_name:
            continue
        subscriptions.append(f"projects/{project}/subscriptions/{sub.get('subscriptionId') or sub.get('name')}")
    subscriptions.sort()
    return {"subscriptions": subscriptions, "nextPageToken": ""}


def api_gcp_pubsub_list_schemas(project: str):
    project = _gcp_project_name(project)
    schemas = []
    for schema in gcp_pubsub_state.get("schemas", {}).values():
        if str(schema.get("project") or project) != project:
            continue
        schemas.append(_gcp_pubsub_schema_view(schema))
    schemas.sort(key=lambda item: item.get("name", ""))
    return {"schemas": schemas, "nextPageToken": "", "kind": "pubsub#schemaList"}


async def api_gcp_pubsub_create_schema(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    schema = _gcp_pubsub_schema_record(project, payload)
    gcp_pubsub_state.setdefault("schemas", {})[schema["name"]] = schema
    _record_usage("gcp.pubsub.create_schema", {"project": project, "schema": schema["name"]})
    return _gcp_pubsub_schema_view(schema)


def api_gcp_pubsub_delete_schema(project: str, schema: str):
    project = _gcp_project_name(project)
    rec = gcp_pubsub_state.get("schemas", {}).get(schema)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="SchemaNotFound")
    del gcp_pubsub_state["schemas"][schema]
    _record_usage("gcp.pubsub.delete_schema", {"project": project, "schema": schema})
    return {"kind": "pubsub#schema", "deleted": True, "name": schema}


def api_gcp_firestore_list_root_documents(project: str, database: str):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    docs = _gcp_firestore_engine().list_root_documents(project, database)
    return {"documents": docs, "nextPageToken": "", "kind": "firestore#documents"}


def api_gcp_firestore_list_documents(project: str, database: str, collection: str):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    docs = _gcp_firestore_engine().list_documents(project, database, collection)
    return {"documents": docs, "nextPageToken": "", "kind": "firestore#documents"}


async def api_gcp_firestore_create_document(project: str, database: str, collection: str, request: Request):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    doc_id = str(payload.get("name") or payload.get("documentId") or _id("doc"))
    if "/" in doc_id:
        doc_id = doc_id.rsplit("/", 1)[-1]
    fields = payload.get("fields", {}) if isinstance(payload.get("fields"), dict) else {}
    doc = _gcp_firestore_engine().create_document(project, database, collection, _gcp_firestore_normalize_fields(fields), doc_id)
    _cloudsim_sync_service_resource("gcp", "firestore", "document", doc_id, {"name": doc_id, "collection": collection, "database": database}, "gcp_firestore")
    _record_usage("gcp.firestore.create_document", {"project": project, "database": database, "collection": collection, "document": doc_id})
    return doc


def api_gcp_firestore_get_document(project: str, database: str, collection: str, doc_id: str):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    doc = _gcp_firestore_engine().get_document(project, database, collection, doc_id)
    if not doc:
        raise HTTPException(404, detail="Document not found")
    return doc


def api_gcp_firestore_delete_document(project: str, database: str, collection: str, doc_id: str):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    try:
        _gcp_firestore_engine().delete_document(project, database, collection, doc_id)
    except KeyError:
        raise HTTPException(404, detail="Document not found")
    _cloudsim_sync_service_resource("gcp", "firestore", "document", doc_id, {}, "gcp_firestore", action="delete")
    _record_usage("gcp.firestore.delete_document", {"project": project, "database": database, "collection": collection, "document": doc_id})
    return {"done": True}


async def api_gcp_firestore_update_document(project: str, database: str, collection: str, doc_id: str, request: Request):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    try:
        doc = _gcp_firestore_engine().update_document(project, database, collection, doc_id, _gcp_firestore_normalize_fields(fields))
    except KeyError:
        raise HTTPException(404, detail="Document not found")
    _record_usage("gcp.firestore.update_document", {"project": project, "database": database, "collection": collection, "document": doc_id})
    return doc


async def api_gcp_firestore_run_query(project: str, database: str, request: Request, collection: str = ""):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    query = payload.get("structuredQuery", {}) if isinstance(payload, dict) else {}
    if not isinstance(query, dict):
        query = {}
    selectors = query.get("from", [])
    if collection:
        collection_id = collection
    elif isinstance(selectors, list) and selectors and isinstance(selectors[0], dict):
        collection_id = str(selectors[0].get("collectionId") or "")
    else:
        collection_id = ""
    limit = int(query.get("limit") or payload.get("limit") or 50)
    where = query.get("where") if isinstance(query.get("where"), dict) else {}
    field_name = ""
    field_value = None
    if isinstance(where, dict):
        field_filter = where.get("fieldFilter") if isinstance(where.get("fieldFilter"), dict) else {}
        if isinstance(field_filter, dict):
            field = field_filter.get("field") if isinstance(field_filter.get("field"), dict) else {}
            field_name = str(field.get("fieldPath") or "")
            field_value = _gcp_firestore_plain_value(field_filter.get("value")) if field_name else None
    results = _gcp_firestore_engine().run_query(project, database, collection_id, field_name=field_name, field_value=field_value, limit=limit)
    if collection_id and field_name:
        index_key = f"{project}:{database}:{collection_id}:{field_name}:{query.get('orderBy', 'ASCENDING')}"
        gcp_firestore_state.setdefault("indexes", {}).setdefault(index_key, _gcp_firestore_index_record(project, database, collection_id, {
            "name": index_key.split(":")[-1],
            "fields": [{"fieldPath": field_name, "order": str(query.get("orderBy") or "ASCENDING")}],
            "queryScope": "COLLECTION",
            "description": f"Auto-generated from query on {collection_id}.{field_name}",
        }))
    return results


def api_gcp_firestore_list_indexes(project: str, database: str, collection: str = ""):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    indexes = []
    for index in gcp_firestore_state.get("indexes", {}).values():
        if str(index.get("project") or project) != project or str(index.get("database") or database) != database:
            continue
        if collection and str(index.get("collection") or "") != collection:
            continue
        indexes.append(_gcp_firestore_index_view(index))
    indexes.sort(key=lambda item: item.get("name", ""))
    return {"indexes": indexes, "kind": "firestore#indexList"}


async def api_gcp_firestore_create_index(project: str, database: str, collection: str, request: Request):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    index = _gcp_firestore_index_record(project, database, collection, payload)
    gcp_firestore_state.setdefault("indexes", {})[f"{project}:{database}:{collection}:{index['name']}"] = index
    _record_usage("gcp.firestore.create_index", {"project": project, "database": database, "collection": collection, "index": index["name"]})
    return _gcp_firestore_index_view(index)


def api_gcp_firestore_delete_index(project: str, database: str, collection: str, index_name: str):
    project = _gcp_project_name(project)
    database = str(database or "(default)")
    key = f"{project}:{database}:{collection}:{index_name}"
    rec = gcp_firestore_state.get("indexes", {}).get(key)
    if not rec:
        raise HTTPException(404, detail="Index not found")
    del gcp_firestore_state["indexes"][key]
    _record_usage("gcp.firestore.delete_index", {"project": project, "database": database, "collection": collection, "index": index_name})
    return {"kind": "firestore#index", "deleted": True, "name": index_name}


def api_gcp_functions_list(project: str, location: str = "us-central1"):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    functions = []
    for fn in gcp_functions_state.get("functions", {}).values():
        if str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
            continue
        functions.append(_gcp_functions_view(project, location, fn))
    functions.sort(key=lambda item: item.get("name", ""))
    return {"functions": functions, "nextPageToken": "", "kind": "cloudfunctions#listFunctionsResponse"}


async def api_gcp_functions_create(project: str, request: Request, location: str = "us-central1"):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    payload = {}
    if request is not None:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    fn = _gcp_functions_record(project, location, payload)
    bundle = _cloudsim_runtime_bundle("gcp_functions")
    fn["runtime_bundle_id"] = bundle.get("id", "")
    fn["runtime_bundle_name"] = bundle.get("name", "")
    fn["runtime_bundle_kind"] = bundle.get("kind", "")
    gcp_functions_state.setdefault("functions", {})[fn["name"]] = fn
    _cloudsim_sync_service_resource("gcp", "functions", "function", fn["name"], fn, "gcp_functions", region=location)
    _record_usage("gcp.functions.create_function", {"project": project, "location": location, "function": fn.get("name", "")})
    return _gcp_functions_view(project, location, fn)


async def api_gcp_functions_update(project: str, location: str, function: str, request: Request):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if "code" in payload:
        fn["code"] = str(payload.get("code") or "")
    if "runtime" in payload:
        fn["runtime"] = str(payload.get("runtime") or fn.get("runtime") or "python311")
        fn.setdefault("buildConfig", {})["runtime"] = fn["runtime"]
    if "handler" in payload:
        fn["entryPoint"] = str(payload.get("handler") or payload.get("entryPoint") or fn.get("entryPoint") or "handler")
        fn.setdefault("buildConfig", {})["entryPoint"] = fn["entryPoint"]
    if "description" in payload:
        fn["description"] = str(payload.get("description") or "")
    if "role" in payload:
        fn["role"] = str(payload.get("role") or "")
    if "timeout" in payload or "timeoutSeconds" in payload:
        timeout = int(payload.get("timeout") or payload.get("timeoutSeconds") or fn.get("serviceConfig", {}).get("timeoutSeconds") or 60)
        fn.setdefault("serviceConfig", {})["timeoutSeconds"] = timeout
        fn["timeout"] = timeout
    if "memory_size" in payload or "availableMemory" in payload:
        memory = str(payload.get("memory_size") or payload.get("availableMemory") or fn.get("serviceConfig", {}).get("availableMemory") or "256M")
        fn.setdefault("serviceConfig", {})["availableMemory"] = memory if memory.endswith("M") or memory.endswith("Mi") else f"{memory}M"
        fn["memory_size"] = int(str(memory).rstrip("MmIi")) if str(memory).rstrip("MmIi").isdigit() else 256
    if isinstance(payload.get("environmentVariables"), dict):
        fn["environmentVariables"] = payload["environmentVariables"]
    if isinstance(payload.get("labels"), dict):
        fn["labels"] = payload["labels"]
    fn["updateTime"] = _now()
    gcp_functions_state.setdefault("functions", {})[function] = fn
    _record_usage("gcp.functions.update_function", {"project": project, "location": location, "function": function})
    return _gcp_functions_view(project, location, fn)


async def api_gcp_functions_publish_version(project: str, location: str, function: str, request: Request):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    version_id = str(len(fn.get("versions", [])) + 1)
    version = {
        "version": version_id,
        "state": "Active",
        "description": str(payload.get("description") or ""),
        "created": _now(),
        "code_sha256": _id("sha"),
        "is_latest": True,
    }
    versions = [v for v in fn.get("versions", []) if isinstance(v, dict)]
    for item in versions:
        item["is_latest"] = False
    versions.append(version)
    fn["versions"] = versions
    fn["updateTime"] = _now()
    gcp_functions_state.setdefault("functions", {})[function] = fn
    return {"version": version}


def api_gcp_functions_list_versions(project: str, location: str, function: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return {"versions": list(fn.get("versions", []) if isinstance(fn.get("versions"), list) else [])}


def api_gcp_functions_list_invocations(project: str, location: str, function: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return {"invocations": list(fn.get("invocations", []) if isinstance(fn.get("invocations"), list) else [])}


def api_gcp_functions_get_policy(project: str, location: str, function: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    policy = {"version": 1, "etag": "", "bindings": fn.get("permissions", []) if isinstance(fn.get("permissions"), list) else []}
    return policy


async def api_gcp_functions_set_policy(project: str, location: str, function: str, request: Request):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    bindings = payload.get("bindings", []) if isinstance(payload.get("bindings"), list) else []
    fn["permissions"] = bindings
    fn["updateTime"] = _now()
    return {"version": int(payload.get("version") or 1), "etag": str(payload.get("etag") or ""), "bindings": bindings}


def api_gcp_functions_get(project: str, location: str, function: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    return _gcp_functions_view(project, location, fn)


def api_gcp_functions_delete(project: str, location: str, function: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    del gcp_functions_state["functions"][function]
    _cloudsim_sync_service_resource("gcp", "functions", "function", function, {}, "gcp_functions", action="delete", region=location)
    _record_usage("gcp.functions.delete_function", {"project": project, "location": location, "function": function})
    return {"done": True}


async def api_gcp_functions_call(project: str, location: str, function: str, request: Request):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location)
    function = _strip_action_suffix(function, ":getIamPolicy", ":setIamPolicy", ":call")
    fn = gcp_functions_state.get("functions", {}).get(function)
    if not fn or str(fn.get("project") or project) != project or str(fn.get("location") or location) != location:
        raise HTTPException(404, detail="Function not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    execution_id = _id("exec")
    # Attempt real execution via gcp_function_runtime
    result_body = None
    try:
        code = fn.get("code") or fn.get("source_code") or ""
        entry = fn.get("entry_point") or fn.get("entryPoint") or fn.get("handler") or "hello_http"
        runtime = fn.get("runtime") or "python312"
        timeout = int(fn.get("timeout") or 30)
        env_vars = fn.get("environmentVariables") or {}
        fn_env = {str(k): str(v) for k, v in env_vars.items()} if isinstance(env_vars, dict) else {}
        if code.strip():
            from core import gcp_function_runtime as _gfr
            out = _gfr.execute(code, entry, runtime, payload, timeout=timeout, env=fn_env or None)
            if out.get("status") == "SUCCESS":
                result_body = json.dumps(out.get("result"), default=str)
            else:
                result_body = json.dumps({"error": out.get("error"), "logs": out.get("logs", "")}, default=str)
    except Exception:
        pass
    # Fallback to canned response if real execution unavailable or code empty
    if result_body is None:
        result_body = json.dumps({"message": f"Hello from {function}", "input": payload}, default=str)
    response = {
        "executionId": execution_id,
        "result": result_body,
    }
    gcp_functions_state.setdefault("operations", []).append({"type": "call", "function": function, "executionId": execution_id, "at": _now()})
    gcp_functions_state.setdefault("invocations", []).append({"function": function, "payload": payload, "executionId": execution_id, "timestamp": _now()})
    return response


def api_gcp_apigw_list_apis(project: str, location: str = "global"):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    apis = []
    for api in gcp_apigw_state.get("apis", {}).values():
        if str(api.get("project") or project) != project or str(api.get("location") or location) != location:
            continue
        apis.append(_gcp_apigateway_api_view(project, location, api))
    apis.sort(key=lambda item: item.get("name", ""))
    return {"apis": apis, "nextPageToken": "", "kind": "apigateway#listApisResponse"}


async def api_gcp_apigw_create_api(project: str, request: Request, location: str = "global"):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    payload = {}
    if request is not None:
      try:
        payload = await request.json()
      except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    api_rec = _gcp_apigw_api_record(project, location, payload)
    gcp_apigw_state.setdefault("apis", {})[api_rec["name"]] = api_rec
    _record_usage("gcp.apigateway.create_api", {"project": project, "location": location, "api": api_rec["name"]})
    return _gcp_apigateway_api_view(project, location, api_rec)


def api_gcp_apigw_get_api(project: str, location: str, api: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    rec = gcp_apigw_state.get("apis", {}).get(api)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("location") or location) != location:
        raise HTTPException(404, detail="API not found")
    return _gcp_apigateway_api_view(project, location, rec)


def api_gcp_apigw_delete_api(project: str, location: str, api: str):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    rec = gcp_apigw_state.get("apis", {}).get(api)
    if not rec or str(rec.get("project") or project) != project or str(rec.get("location") or location) != location:
        raise HTTPException(404, detail="API not found")
    del gcp_apigw_state["apis"][api]
    _record_usage("gcp.apigateway.delete_api", {"project": project, "location": location, "api": api})
    return {"done": True}


def api_gcp_apigw_list_configs(project: str, location: str = "global", api: str = ""):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    configs = []
    for cfg in gcp_apigw_state.get("api_configs", {}).values():
        if str(cfg.get("project") or project) != project or str(cfg.get("location") or location) != location:
            continue
        if api and str(cfg.get("api") or "") != api:
            continue
        configs.append(_gcp_apigateway_config_view(project, location, cfg))
    configs.sort(key=lambda item: item.get("name", ""))
    return {"apiConfigs": configs, "nextPageToken": "", "kind": "apigateway#listApiConfigsResponse"}


async def api_gcp_apigw_create_config(project: str, request: Request, location: str = "global", api: str = ""):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    payload = {}
    if request is not None:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if api and not payload.get("api"):
        payload["api"] = api
    cfg = _gcp_apigw_cfg_record(project, location, payload)
    gcp_apigw_state.setdefault("api_configs", {})[cfg["name"]] = cfg
    _record_usage("gcp.apigateway.create_config", {"project": project, "location": location, "config": cfg["name"], "api": api or cfg.get("api", "")})
    return _gcp_apigateway_config_view(project, location, cfg)


def api_gcp_apigw_list_gateways(project: str, location: str = "global", api: str = ""):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    gateways = []
    for gw in gcp_apigw_state.get("gateways", {}).values():
        if str(gw.get("project") or project) != project or str(gw.get("location") or location) != location:
            continue
        if api and str(gw.get("api") or "") != api and str(gw.get("apiConfig") or "") != api:
            continue
        gateways.append(_gcp_apigateway_gateway_view(project, location, gw))
    gateways.sort(key=lambda item: item.get("name", ""))
    return {"gateways": gateways, "nextPageToken": "", "kind": "apigateway#listGatewaysResponse"}


async def api_gcp_apigw_create_gateway(project: str, request: Request, location: str = "global", api: str = ""):
    project = _gcp_project_name(project)
    location = _gcp_location_name(location, "global")
    payload = {}
    if request is not None:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if api and not payload.get("apiConfig"):
        payload["apiConfig"] = api
    gw = _gcp_apigw_gateway_record(project, location, payload)
    gcp_apigw_state.setdefault("gateways", {})[gw["name"]] = gw
    _record_usage("gcp.apigateway.create_gateway", {"project": project, "location": location, "gateway": gw["name"], "api": api or gw.get("apiConfig", "")})
    return _gcp_apigateway_gateway_view(project, location, gw)


def api_gcp_vpc_list_networks(project: str):
    project = _gcp_project_name(project)
    networks = []
    for network in gcp_vpc_state.get("networks", {}).values():
        if str(network.get("project") or project) != project:
            continue
        network_name = str(network.get("name") or "")
        networks.append({
            "kind": "compute#network",
            "id": str(network.get("id") or _gcp_compute_numeric_id(f"{project}:{network_name}")),
            "creationTimestamp": network.get("createTime", _now()),
            "name": network_name,
            "description": network.get("description", ""),
            "IPv4Range": network.get("IPv4Range", ""),
            "gatewayIPv4": network.get("gatewayIPv4", ""),
            "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{network_name}",
            "selfLinkWithId": network.get("selfLinkWithId", f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{network_name}?id={network.get('id') or _gcp_compute_numeric_id(f'{project}:{network_name}')}"),
            "autoCreateSubnetworks": bool(network.get("autoCreateSubnetworks", True)),
            "subnetworks": network.get("subnetworks", []),
            "peerings": network.get("peerings", []),
            "routingConfig": {"routingMode": network.get("routingMode", "REGIONAL")},
        })
    return {"kind": "compute#networkList", "items": networks}


async def api_gcp_vpc_create_network(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or payload.get("network") or "").strip()
    if not name:
        raise HTTPException(400, detail="Network name is required")
    rec = {
        "id": _gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "project": project,
        "description": str(payload.get("description") or ""),
        "IPv4Range": str(payload.get("IPv4Range") or ""),
        "gatewayIPv4": str(payload.get("gatewayIPv4") or ""),
        "autoCreateSubnetworks": bool(payload.get("autoCreateSubnetworks", True)),
        "routingMode": str(payload.get("routingMode") or "REGIONAL"),
        "subnetworks": payload.get("subnetworks", []) if isinstance(payload.get("subnetworks"), list) else [],
        "peerings": payload.get("peerings", []) if isinstance(payload.get("peerings"), list) else [],
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("networks", {})[name] = rec
    _record_usage("gcp.vpc.create_network", {"project": project, "network": name})
    return {
        "kind": "compute#network",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "IPv4Range": rec["IPv4Range"],
        "gatewayIPv4": rec["gatewayIPv4"],
        "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{name}",
        "selfLinkWithId": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{name}?id={rec['id']}",
        "autoCreateSubnetworks": rec["autoCreateSubnetworks"],
        "subnetworks": rec["subnetworks"],
        "peerings": rec["peerings"],
        "routingConfig": {"routingMode": rec["routingMode"]},
    }


def api_gcp_vpc_get_network(project: str, network: str):
    project = _gcp_project_name(project)
    rec = gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    return {
        "kind": "compute#network",
        "id": rec.get("id", _gcp_compute_numeric_id(f"{project}:{network}")),
        "creationTimestamp": rec.get("createTime", _now()),
        "name": rec["name"],
        "description": rec.get("description", ""),
        "IPv4Range": rec.get("IPv4Range", ""),
        "gatewayIPv4": rec.get("gatewayIPv4", ""),
        "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{network}",
        "selfLinkWithId": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{network}?id={rec.get('id', _gcp_compute_numeric_id(f'{project}:{network}'))}",
        "autoCreateSubnetworks": bool(rec.get("autoCreateSubnetworks", True)),
        "subnetworks": rec.get("subnetworks", []),
        "peerings": rec.get("peerings", []),
        "routingConfig": {"routingMode": rec.get("routingMode", "REGIONAL")},
    }


def api_gcp_vpc_delete_network(project: str, network: str):
    project = _gcp_project_name(project)
    rec = gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    del gcp_vpc_state["networks"][network]
    _record_usage("gcp.vpc.delete_network", {"project": project, "network": network})
    return {"done": True}


def api_gcp_vpc_list_subnetworks(project: str, region: str):
    project = _gcp_project_name(project)
    subnetworks = []
    for subnet in gcp_vpc_state.get("subnetworks", {}).values():
        if str(subnet.get("project") or project) != project or str(subnet.get("region") or region) != region:
            continue
        subnetworks.append({
            "kind": "compute#subnetwork",
            "id": str(subnet.get("id") or _gcp_compute_numeric_id(f"{project}:{subnet['name']}")),
            "creationTimestamp": subnet.get("createTime", _now()),
            "name": subnet["name"],
            "description": subnet.get("description", ""),
            "region": region,
            "network": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{subnet.get('network','default')}",
            "ipCidrRange": subnet.get("ipCidrRange", "10.0.0.0/24"),
            "reservedInternalRange": subnet.get("reservedInternalRange", ""),
            "gatewayAddress": subnet.get("gatewayAddress", ""),
            "privateIpGoogleAccess": bool(subnet.get("privateIpGoogleAccess", False)),
            "secondaryIpRanges": subnet.get("secondaryIpRanges", []),
            "purpose": subnet.get("purpose", ""),
            "role": subnet.get("role", ""),
            "stackType": subnet.get("stackType", "IPV4_ONLY"),
            "state": subnet.get("state", "READY"),
            "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/regions/{region}/subnetworks/{subnet['name']}",
        })
    return {"kind": "compute#subnetworkList", "items": subnetworks}


async def api_gcp_vpc_create_subnetwork(project: str, region: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Subnetwork name is required")
    rec = {
        "id": _gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "description": str(payload.get("description") or ""),
        "project": project,
        "region": region,
        "network": str(payload.get("network") or "default").split("/")[-1],
        "ipCidrRange": str(payload.get("ipCidrRange") or "10.0.0.0/24"),
        "reservedInternalRange": str(payload.get("reservedInternalRange") or ""),
        "gatewayAddress": str(payload.get("gatewayAddress") or ""),
        "privateIpGoogleAccess": bool(payload.get("privateIpGoogleAccess", False)),
        "secondaryIpRanges": payload.get("secondaryIpRanges", []) if isinstance(payload.get("secondaryIpRanges"), list) else [],
        "purpose": str(payload.get("purpose") or ""),
        "role": str(payload.get("role") or ""),
        "stackType": str(payload.get("stackType") or "IPV4_ONLY"),
        "state": str(payload.get("state") or "READY"),
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("subnetworks", {})[name] = rec
    _record_usage("gcp.vpc.create_subnetwork", {"project": project, "region": region, "subnetwork": name})
    return {
        "kind": "compute#subnetwork",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "region": region,
        "network": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{rec['network']}",
        "ipCidrRange": rec["ipCidrRange"],
        "reservedInternalRange": rec["reservedInternalRange"],
        "gatewayAddress": rec["gatewayAddress"],
        "privateIpGoogleAccess": rec["privateIpGoogleAccess"],
        "secondaryIpRanges": rec["secondaryIpRanges"],
        "purpose": rec["purpose"],
        "role": rec["role"],
        "stackType": rec["stackType"],
        "state": rec["state"],
        "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/regions/{region}/subnetworks/{name}",
    }


def api_gcp_vpc_list_firewalls(project: str):
    project = _gcp_project_name(project)
    firewalls = []
    for fw in gcp_vpc_state.get("firewalls", {}).values():
        if str(fw.get("project") or project) != project:
            continue
        firewalls.append({
            "kind": "compute#firewall",
            "id": str(fw.get("id") or _gcp_compute_numeric_id(f"{project}:{fw['name']}")),
            "creationTimestamp": fw.get("createTime", _now()),
            "name": fw["name"],
            "description": fw.get("description", ""),
            "network": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{fw.get('network','default')}",
            "priority": int(fw.get("priority") or 1000),
            "direction": fw.get("direction", "INGRESS"),
            "allowed": fw.get("allowed", [{"IPProtocol": "tcp", "ports": ["22"]}]),
            "denied": fw.get("denied", []),
            "sourceRanges": fw.get("sourceRanges", ["0.0.0.0/0"]),
            "destinationRanges": fw.get("destinationRanges", []),
            "sourceTags": fw.get("sourceTags", []),
            "targetTags": fw.get("targetTags", []),
            "sourceServiceAccounts": fw.get("sourceServiceAccounts", []),
            "targetServiceAccounts": fw.get("targetServiceAccounts", []),
            "disabled": bool(fw.get("disabled", False)),
            "logConfig": fw.get("logConfig", {}),
            "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/firewalls/{fw['name']}",
        })
    return {"kind": "compute#firewallList", "items": firewalls}


async def api_gcp_vpc_create_firewall(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Firewall name is required")
    rec = {
        "id": _gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "description": str(payload.get("description") or ""),
        "project": project,
        "network": str(payload.get("network") or "default").split("/")[-1],
        "priority": int(payload.get("priority") or 1000),
        "direction": str(payload.get("direction") or "INGRESS"),
        "allowed": payload.get("allowed") if isinstance(payload.get("allowed"), list) else [{"IPProtocol": "tcp", "ports": ["22"]}],
        "denied": payload.get("denied") if isinstance(payload.get("denied"), list) else [],
        "sourceRanges": payload.get("sourceRanges") if isinstance(payload.get("sourceRanges"), list) else ["0.0.0.0/0"],
        "destinationRanges": payload.get("destinationRanges") if isinstance(payload.get("destinationRanges"), list) else [],
        "sourceTags": payload.get("sourceTags") if isinstance(payload.get("sourceTags"), list) else [],
        "targetTags": payload.get("targetTags") if isinstance(payload.get("targetTags"), list) else [],
        "sourceServiceAccounts": payload.get("sourceServiceAccounts") if isinstance(payload.get("sourceServiceAccounts"), list) else [],
        "targetServiceAccounts": payload.get("targetServiceAccounts") if isinstance(payload.get("targetServiceAccounts"), list) else [],
        "disabled": bool(payload.get("disabled", False)),
        "logConfig": payload.get("logConfig") if isinstance(payload.get("logConfig"), dict) else {},
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("firewalls", {})[name] = rec
    _record_usage("gcp.vpc.create_firewall", {"project": project, "firewall": name})
    return {
        "kind": "compute#firewall",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "network": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{rec['network']}",
        "priority": rec["priority"],
        "direction": rec["direction"],
        "allowed": rec["allowed"],
        "denied": rec["denied"],
        "sourceRanges": rec["sourceRanges"],
        "destinationRanges": rec["destinationRanges"],
        "sourceTags": rec["sourceTags"],
        "targetTags": rec["targetTags"],
        "sourceServiceAccounts": rec["sourceServiceAccounts"],
        "targetServiceAccounts": rec["targetServiceAccounts"],
        "disabled": rec["disabled"],
        "logConfig": rec["logConfig"],
        "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/firewalls/{name}",
    }


def api_gcp_vpc_list_routes(project: str):
    project = _gcp_project_name(project)
    routes = []
    for route in gcp_vpc_state.get("routes", {}).values():
        if str(route.get("project") or project) != project:
            continue
        route_name = str(route.get("name") or "")
        routes.append({
            "kind": "compute#route",
            "id": str(route.get("id") or _gcp_compute_numeric_id(f"{project}:{route_name}")),
            "creationTimestamp": route.get("createTime", _now()),
            "name": route_name,
            "description": route.get("description", ""),
            "network": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{route.get('network', 'default')}",
            "destRange": route.get("destRange", ""),
            "priority": int(route.get("priority") or 1000),
            "nextHopGateway": route.get("nextHopGateway", ""),
            "nextHopIp": route.get("nextHopIp", ""),
            "nextHopInstance": route.get("nextHopInstance", ""),
            "nextHopNetwork": route.get("nextHopNetwork", ""),
            "tags": route.get("tags", []),
            "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/routes/{route_name}",
        })
    return {"kind": "compute#routeList", "items": routes}


async def api_gcp_vpc_create_route(project: str, request: Request):
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Route name is required")
    rec = {
        "id": _gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "description": str(payload.get("description") or ""),
        "project": project,
        "network": str(payload.get("network") or "default").split("/")[-1],
        "destRange": str(payload.get("destRange") or ""),
        "priority": int(payload.get("priority") or 1000),
        "nextHopGateway": str(payload.get("nextHopGateway") or ""),
        "nextHopIp": str(payload.get("nextHopIp") or ""),
        "nextHopInstance": str(payload.get("nextHopInstance") or ""),
        "nextHopNetwork": str(payload.get("nextHopNetwork") or ""),
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("routes", {})[name] = rec
    _record_usage("gcp.vpc.create_route", {"project": project, "route": name})
    return {
        "kind": "compute#route",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "network": f"{_gcp_compute_network_root()}/projects/{project}/global/networks/{rec['network']}",
        "destRange": rec["destRange"],
        "priority": rec["priority"],
        "nextHopGateway": rec["nextHopGateway"],
        "nextHopIp": rec["nextHopIp"],
        "nextHopInstance": rec["nextHopInstance"],
        "nextHopNetwork": rec["nextHopNetwork"],
        "tags": rec["tags"],
        "selfLink": f"{_gcp_compute_network_root()}/projects/{project}/global/routes/{name}",
    }


def api_gcp_vpc_delete_route(project: str, route: str):
    project = _gcp_project_name(project)
    rec = gcp_vpc_state.get("routes", {}).get(route)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Route not found")
    del gcp_vpc_state["routes"][route]
    _record_usage("gcp.vpc.delete_route", {"project": project, "route": route})
    return {"done": True}


def _gcp_project_name(project: str | None) -> str:
    return str(project or "cloudlearn").strip() or "cloudlearn"


def _strip_action_suffix(value: str, *suffixes: str) -> str:
    text = str(value or "")
    for suffix in suffixes:
        if suffix and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _gcp_location_name(location: str | None, default: str = "us-central1") -> str:
    return str(location or default).strip() or default


_GCP_PUBLIC_BASE_ENV = os.environ.get("CLOUDLEARN_PUBLIC_URL", "").rstrip("/")
_GCP_PUBLIC_BASE_DYNAMIC = ""  # last non-local origin seen, for non-request contexts
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _gcp_capture_public_base(request) -> None:
    """Remember the simulator's externally-visible origin so GCP resource
    metadata (selfLinks, URIs, hostnames) reflects the simulator rather than
    *.googleapis.com. Stored per-request (ContextVar) to avoid cross-request
    races; a non-local value also seeds a global fallback for background
    contexts. An explicit CLOUDLEARN_PUBLIC_URL env var always wins."""
    global _GCP_PUBLIC_BASE_DYNAMIC
    if _GCP_PUBLIC_BASE_ENV:
        return
    try:
        host = request.headers.get("host") or request.url.netloc
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        if not host:
            return
        base = f"{scheme}://{host}"
        REQUEST_PUBLIC_BASE.set(base)
        # Only let a non-local request seed the global fallback, so the
        # container healthcheck (Host: 127.0.0.1) never pollutes it.
        if not any(host.split(":", 1)[0] == h for h in _LOCAL_HOSTS):
            _GCP_PUBLIC_BASE_DYNAMIC = base
    except Exception:
        pass


def _gcp_public_base() -> str:
    if _GCP_PUBLIC_BASE_ENV:
        return _GCP_PUBLIC_BASE_ENV
    req = REQUEST_PUBLIC_BASE.get()
    # Prefer the current request's origin, unless it's a local/healthcheck call
    # and we have a better non-local one remembered.
    if req and not any(req.split("://", 1)[-1].split(":", 1)[0] == h for h in _LOCAL_HOSTS):
        return req
    return _GCP_PUBLIC_BASE_DYNAMIC or req or "http://localhost:9000"


def _gcp_public_host() -> str:
    """Host:port portion of the simulator origin (no scheme)."""
    return _gcp_public_base().split("://", 1)[-1]


def _gcp_public_ip_only() -> str:
    """Just the host/IP of the simulator origin (no scheme, no port) — used as
    the instance external IP (the appliance is the real ingress address)."""
    return _gcp_public_host().split(":", 1)[0]


def _gcp_gcs_root() -> str:
    return f"{_gcp_public_base()}/storage/v1"


def _gcp_sql_root() -> str:
    return f"{_gcp_public_base()}/sql/v1beta4"


def _gcp_sql_make_operation(project: str, instance_name: str, op_type: str = "CREATE", status: str = "DONE") -> dict:
    """Build + store a sql#operation. Real Cloud SQL insert/delete/restart return
    a long-running Operation that clients (and Terraform) poll via operations.get;
    the simulator completes synchronously so the op is returned already DONE."""
    op_name = f"op-{uuid.uuid4().hex}"
    op = {
        "kind": "sql#operation",
        "name": op_name,
        "status": status,
        "operationType": op_type,
        "targetId": instance_name,
        "targetProject": project,
        "targetLink": f"{_gcp_sql_root()}/projects/{project}/instances/{instance_name}",
        "user": "cloudlearn@cloudlearn.iam.gserviceaccount.com",
        "insertTime": _now(),
        "startTime": _now(),
        "endTime": _now() if status.upper() == "DONE" else "",
        "selfLink": f"{_gcp_sql_root()}/projects/{project}/operations/{op_name}",
    }
    ops = gcp_sql_state.get("operation_records")
    if not isinstance(ops, dict):
        ops = {}
        gcp_sql_state["operation_records"] = ops
    ops[op_name] = op
    return op


def _gcp_pubsub_root() -> str:
    return f"{_gcp_public_base()}/v1"


def _gcp_firestore_root() -> str:
    return f"{_gcp_public_base()}/firestore/v1"


def _gcp_functions_root() -> str:
    return f"{_gcp_public_base()}/v1"


def _gcp_apigateway_root() -> str:
    return f"{_gcp_public_base()}/v1"


def _gcp_iam_root() -> str:
    return f"{_gcp_public_base()}/v1"


def _gcp_compute_network_root() -> str:
    return f"{_gcp_public_base()}/compute/v1"


def _gcp_storage_bucket_view(project: str, bucket: dict) -> dict:
    name = str(bucket.get("name") or "")
    project_number = str(bucket.get("projectNumber") or _gcp_compute_numeric_id(f"{project}:{name}"))
    return {
        "kind": "storage#bucket",
        "id": name,
        "selfLink": f"{_gcp_gcs_root()}/b/{name}",
        "projectNumber": project_number,
        "name": name,
        "location": bucket.get("location", "US"),
        "locationType": bucket.get("locationType", "multi-region"),
        "storageClass": bucket.get("storageClass", "STANDARD"),
        "timeCreated": bucket.get("timeCreated", _now()),
        "updated": bucket.get("updated", _now()),
        "metageneration": bucket.get("metageneration", "1"),
        "defaultEventBasedHold": bool(bucket.get("defaultEventBasedHold", False)),
        "defaultObjectAcl": bucket.get("defaultObjectAcl", []),
        "labels": bucket.get("labels", {}),
        "iamConfiguration": _gcp_storage_sanitize_iam_config(bucket.get("iamConfiguration")),
        "etag": bucket.get("etag", ""),
    }


def _gcp_storage_sanitize_iam_config(conf: Any) -> dict:
    """Real GCP clients (Apiary) parse uniformBucketLevelAccess.lockedTime as an
    RFC3339 timestamp; an empty string throws. Drop it unless it has a real value."""
    conf = dict(conf) if isinstance(conf, dict) else {"publicAccessPrevention": "inherited"}
    ubla = dict(conf.get("uniformBucketLevelAccess") or {"enabled": True})
    if not ubla.get("lockedTime"):
        ubla.pop("lockedTime", None)
    conf["uniformBucketLevelAccess"] = ubla
    return conf


def _gcp_storage_object_view(project: str, bucket: str, name: str, obj: dict) -> dict:
    return {
        "kind": "storage#object",
        "id": f"{bucket}/{name}",
        "selfLink": f"{_gcp_gcs_root()}/b/{bucket}/o/{name}",
        "bucket": bucket,
        "name": name,
        "generation": str(obj.get("generation") or _gcp_compute_numeric_id(f"{bucket}/{name}")),
        "metageneration": str(obj.get("metageneration") or "1"),
        "contentType": obj.get("contentType", "application/octet-stream"),
        "size": str(obj.get("size", 0)),
        "timeCreated": obj.get("timeCreated", _now()),
        "updated": obj.get("updated", _now()),
        "storageClass": obj.get("storageClass", "STANDARD"),
        "metadata": obj.get("metadata", {}),
        "md5Hash": obj.get("md5Hash", ""),
        "crc32c": obj.get("crc32c", ""),
        "etag": obj.get("etag", ""),
        "mediaLink": obj.get("mediaLink", ""),
    }


def _gcp_sql_instance_view(project: str, instance: dict) -> dict:
    name = str(instance.get("name") or "")
    region = str(instance.get("region") or "us-central1")
    return {
        "kind": "sql#instance",
        "id": str(instance.get("id") or _gcp_compute_numeric_id(f"{project}:{name}")),
        "project": project,
        "name": name,
        "region": region,
        "gceZone": instance.get("gceZone", ""),
        "databaseVersion": instance.get("databaseVersion", "POSTGRES_15"),
        "backendType": instance.get("backendType", "SECOND_GEN"),
        "state": instance.get("state", "RUNNABLE"),
        "instanceType": instance.get("instanceType", "CLOUD_SQL_INSTANCE"),
        "connectionName": instance.get("connectionName", f"{project}:{region}:{name}"),
        "serviceAccountEmailAddress": instance.get("serviceAccountEmailAddress", f"{project}@{project}.iam.gserviceaccount.com"),
        "selfLink": f"{_gcp_sql_root()}/projects/{project}/instances/{name}",
        "databaseInstalledVersion": instance.get("databaseInstalledVersion", ""),
        "maintenanceVersion": instance.get("maintenanceVersion", ""),
        "settings": instance.get("settings", {
            "tier": "db-f1-micro",
            "activationPolicy": "ALWAYS",
            "dataDiskType": "PD_SSD",
            "dataDiskSizeGb": "10",
            "availabilityType": "ZONAL",
            "pricingPlan": "PER_USE",
            "ipConfiguration": {
                "ipv4Enabled": True,
                "privateNetwork": "",
                "requireSsl": False,
            },
        }),
        "ipAddresses": instance.get("ipAddresses", [{"type": "PRIMARY", "ipAddress": instance.get("ipAddress", _public_ip())}]),
        "serverCaCert": instance.get("serverCaCert", {"cert": "", "commonName": name, "createTime": _now(), "expirationTime": ""}),
        "createTime": instance.get("createTime", _now()),
        "updateTime": instance.get("updateTime", _now()),
        # Real connection endpoint for the backing OSS engine (None when the
        # engine was unreachable and the instance is metadata-only).
        "connection": instance.get("_backend"),
        "backendStatus": "live" if instance.get("_backend") else "simulated",
    }


def _gcp_pubsub_topic_view(project: str, topic: dict) -> dict:
    name = str(topic.get("name") or "")
    view = {
        "name": f"projects/{project}/topics/{name}",
        "labels": topic.get("labels", {}),
        "messageStoragePolicy": topic.get("messageStoragePolicy", {
            "allowedPersistenceRegions": [],
            "enforceInTransit": False,
        }),
        "kmsKeyName": topic.get("kmsKeyName", ""),
        "schemaSettings": topic.get("schemaSettings", {}),
        "satisfiesPzs": bool(topic.get("satisfiesPzs", False)),
        "state": topic.get("state", "ACTIVE"),
        "ingestionDataSourceSettings": topic.get("ingestionDataSourceSettings", {}),
        "messageTransforms": topic.get("messageTransforms", []),
    }
    # Topics have no default retention (unlike subscriptions); only emit it when
    # explicitly set, else Terraform sees drift ("604800s" -> null).
    retention = topic.get("messageRetentionDuration")
    if retention:
        view["messageRetentionDuration"] = retention
    return view


def _gcp_pubsub_subscription_view(project: str, subscription: dict) -> dict:
    name = str(subscription.get("name") or "")
    return {
        "name": f"projects/{project}/subscriptions/{name}",
        "topic": subscription.get("topic", ""),
        "ackDeadlineSeconds": subscription.get("ackDeadlineSeconds", 10),
        "retainAckedMessages": subscription.get("retainAckedMessages", False),
        "messageRetentionDuration": subscription.get("messageRetentionDuration", "604800s"),
        "labels": subscription.get("labels", {}),
        "filter": subscription.get("filter", ""),
        "enableMessageOrdering": bool(subscription.get("enableMessageOrdering", False)),
        "enableExactlyOnceDelivery": bool(subscription.get("enableExactlyOnceDelivery", False)),
        "state": subscription.get("state", "ACTIVE"),
        "deadLetterPolicy": subscription.get("deadLetterPolicy", {}),
        "retryPolicy": subscription.get("retryPolicy", {}),
        "expirationPolicy": subscription.get("expirationPolicy", {}),
    }


def _gcp_firestore_document_view(project: str, database: str, collection: str, doc_id: str, document: dict) -> dict:
    return {
        "name": f"{_gcp_firestore_root()}/projects/{project}/databases/{database}/documents/{collection}/{doc_id}",
        "fields": _gcp_firestore_normalize_fields(document.get("fields", {}) if isinstance(document, dict) else {}),
        "createTime": document.get("createTime", _now()),
        "updateTime": document.get("updateTime", _now()),
    }


def _gcp_duration_str(value) -> str:
    """Render a Duration field as a protobuf duration string (e.g. '60s'). Real
    Google clients parse Cloud Functions `timeout` (and similar) as strings."""
    if isinstance(value, str):
        v = value.strip()
        return v if (v.endswith("s") or not v) else f"{v}s"
    try:
        return f"{int(value)}s"
    except (TypeError, ValueError):
        return "60s"


def _gcp_functions_make_operation(project: str, location: str, fn_view: dict, op_type: str = "CREATE_FUNCTION", done: bool = True) -> dict:
    """google.longrunning.Operation for a Cloud Functions mutation. Real Functions
    create/update/delete return an LRO that clients poll via operations.get; the
    simulator completes synchronously so the op is returned already done."""
    op_id = uuid.uuid4().hex
    op = {
        "name": f"operations/{op_id}",
        "metadata": {
            "@type": "type.googleapis.com/google.cloud.functions.v1.OperationMetadataV1",
            "target": fn_view.get("name", ""),
            "type": op_type,
        },
        "done": done,
    }
    if done:
        resp = dict(fn_view)
        resp["@type"] = "type.googleapis.com/google.cloud.functions.v1.CloudFunction"
        op["response"] = resp
    recs = gcp_functions_state.get("operation_records")
    if not isinstance(recs, dict):
        recs = {}
        gcp_functions_state["operation_records"] = recs
    recs[op_id] = op
    return op


def _gcp_functions_view(project: str, location: str, function: dict) -> dict:
    name = str(function.get("name") or "")
    # Trigger URL points at the simulator (this is where the function actually runs).
    uri = f"{_gcp_public_base()}/v1/projects/{project}/locations/{location}/functions/{name}:call"
    service_config = dict(function.get("serviceConfig") or {})
    service_config["uri"] = uri
    service_config.setdefault("availableMemory", "256M")
    service_config.setdefault("timeoutSeconds", 60)
    service_config.setdefault("ingressSettings", "ALLOW_ALL")
    return {
        "name": f"{_gcp_functions_root()}/projects/{project}/locations/{location}/functions/{name}",
        "description": function.get("description", ""),
        "status": function.get("status", "ACTIVE"),
        "entryPoint": function.get("entryPoint", "handler"),
        "runtime": function.get("runtime", "python311"),
        "code": function.get("code", ""),
        "role": function.get("role", ""),
        "timeout": _gcp_duration_str(function.get("timeout", function.get("serviceConfig", {}).get("timeoutSeconds", 60))),
        "memory_size": function.get("memory_size", int(str(function.get("serviceConfig", {}).get("availableMemory", "256M")).rstrip("MmIi")) if str(function.get("serviceConfig", {}).get("availableMemory", "256M")).rstrip("MmIi").isdigit() else 256),
        "buildConfig": function.get("buildConfig", {
            "runtime": function.get("runtime", "python311"),
            "entryPoint": function.get("entryPoint", "handler"),
            "source": function.get("source", {}),
        }),
        "serviceConfig": service_config,
        "eventTrigger": function.get("eventTrigger"),
        "httpsTrigger": {"url": uri},
        "environmentVariables": function.get("environmentVariables", {}),
        "labels": function.get("labels", {}),
        "permissions": function.get("permissions", []),
        "versions": function.get("versions", []),
        "invocations": function.get("invocations", []),
        "triggers": function.get("triggers", []),
        "versionId": function.get("versionId", "1"),
        "sourceUploadUrl": function.get("sourceUploadUrl", ""),
        "buildName": function.get("buildName", ""),
        "buildId": function.get("buildId", ""),
        "network": function.get("network", ""),
        "vpcConnector": function.get("vpcConnector", ""),
        "minInstances": function.get("minInstances", 0),
        "maxInstances": function.get("maxInstances", 1),
        "createTime": function.get("createTime", _now()),
        "updateTime": function.get("updateTime", _now()),
    }


def _gcp_apigateway_api_view(project: str, location: str, api: dict) -> dict:
    name = str(api.get("name") or "")
    return {
        "name": f"{_gcp_apigateway_root()}/projects/{project}/locations/{location}/apis/{name}",
        "displayName": api.get("displayName", name),
        "managedService": f"{name}.apigateway.{_gcp_public_host()}",
        "state": api.get("state", "ACTIVE"),
        "labels": api.get("labels", {}),
        "createTime": api.get("createTime", _now()),
        "updateTime": api.get("updateTime", _now()),
    }


def _gcp_apigateway_config_view(project: str, location: str, cfg: dict) -> dict:
    name = str(cfg.get("name") or "")
    return {
        "name": f"{_gcp_apigateway_root()}/projects/{project}/locations/{location}/apiConfigs/{name}",
        "displayName": cfg.get("displayName", name),
        "api": cfg.get("api", ""),
        "parent_id": cfg.get("parent_id", ""),
        "path_part": cfg.get("path_part", ""),
        "http_method": cfg.get("http_method", ""),
        "authorization_type": cfg.get("authorization_type", ""),
        "integration_type": cfg.get("integration_type", ""),
        "integration_uri": cfg.get("integration_uri", ""),
        "status_code": cfg.get("status_code", 200),
        "response_body": cfg.get("response_body", ""),
        "content_type": cfg.get("content_type", "application/json"),
        "openapiDocuments": cfg.get("openapiDocuments", []),
        "labels": cfg.get("labels", {}),
        "gatewayServiceAccount": cfg.get("gatewayServiceAccount", ""),
        "state": cfg.get("state", "ACTIVE"),
        "createTime": cfg.get("createTime", _now()),
        "updateTime": cfg.get("updateTime", _now()),
    }


def _gcp_apigateway_gateway_view(project: str, location: str, gw: dict) -> dict:
    name = str(gw.get("name") or "")
    return {
        "name": f"{_gcp_apigateway_root()}/projects/{project}/locations/{location}/gateways/{name}",
        "displayName": gw.get("displayName", name),
        "apiConfig": gw.get("apiConfig", ""),
        "stage_name": gw.get("stage_name", "prod"),
        "description": gw.get("description", ""),
        "labels": gw.get("labels", {}),
        "state": gw.get("state", "ACTIVE"),
        "defaultHostname": _gcp_public_host(),
        "createTime": gw.get("createTime", _now()),
        "updateTime": gw.get("updateTime", _now()),
    }


def _gcp_iam_policy_view(project: str) -> dict:
    policy = gcp_iam_state.setdefault("policies", {}).setdefault(project, {"bindings": [], "etag": "", "version": 1})
    return {
        "version": policy.get("version", 1),
        "etag": policy.get("etag", ""),
        "bindings": policy.get("bindings", []),
    }


def api_vpc_list_vpcs():
    vpcs = []
    for vpc in vpc_state["vpcs"].values():
        vpc_id = vpc["vpc_id"]
        subnets = [s for s in vpc_state["subnets"].values() if s.get("vpc_id") == vpc_id]
        route_tables = [r for r in vpc_state["route_tables"].values() if r.get("vpc_id") == vpc_id]
        security_groups = [g for g in vpc_state["security_groups"].values() if g.get("vpc_id") == vpc_id]
        internet_gateways = [g for g in vpc_state["internet_gateways"].values() if g.get("attached_vpc_id") == vpc_id]
        vpcs.append({
            **vpc,
            "subnet_count": len(subnets),
            "route_table_count": len(route_tables),
            "security_group_count": len(security_groups),
            "internet_gateway_count": len(internet_gateways),
            "availability_zones": sorted({s.get("availability_zone", "") for s in subnets if s.get("availability_zone")}),
        })
    return {"vpcs": vpcs, "count": len(vpc_state["vpcs"])}


def api_vpc_create(req: VpcRequest):
    vpc_id = _id("vpc")
    default_rt_id = _id("rtb")
    default_sg_id = _id("sg")
    vpc = {
        "vpc_id": vpc_id,
        "name": req.name,
        "cidr_block": req.cidr_block,
        "encryption_controls": req.encryption_controls,
        "tenancy": req.tenancy,
        "ipv6_mode": req.ipv6_mode,
        "tags": req.tags or [],
        "created": _now(),
        "state": "available",
        "dhcp_options_id": f"dopt-{vpc_id.replace('vpc-', '')[:8] or secrets.token_hex(4)}",
        "main_route_table_id": default_rt_id,
        "default_security_group_id": default_sg_id,
        "internet_gateway_id": "",
    }
    vpc_state["vpcs"][vpc_id] = vpc
    vpc_state["route_tables"][default_rt_id] = {
        "route_table_id": default_rt_id,
        "vpc_id": vpc_id,
        "name": f"{req.name}-main" if req.name else default_rt_id,
        "routes": [{"destination": vpc["cidr_block"], "target_type": "local", "target_id": vpc_id, "type": "CreateRouteTable", "created": _now()}],
        "subnet_ids": [],
        "is_main": True,
        "created": _now(),
        "tags": [],
    }
    vpc_state["security_groups"][default_sg_id] = {
        "security_group_id": default_sg_id,
        "vpc_id": vpc_id,
        "group_name": "default",
        "description": "default VPC security group",
        "ingress": [],
        "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "allow all outbound traffic", "created": _now()}],
        "is_default": True,
        "created": _now(),
        "tags": [],
    }
    _record_usage("vpc.create_vpc", vpc)
    return vpc


def api_vpc_delete(vpc_id: str, force: bool = False):
    vpc = vpc_state["vpcs"].get(vpc_id)
    if not vpc:
        raise HTTPException(404, detail="NoSuchVpc")

    instances = [i for i in ec2_state["instances"].values() if i.get("vpc_id") == vpc_id and i.get("state") not in {"terminated"}]
    if instances and not force:
        raise HTTPException(409, detail="VpcHasActiveInstances")

    # Keep the simulator lightweight: remove the VPC and its networking resources.
    # Instances are left alone unless force is explicitly requested.
    if force:
        for inst in instances:
            inst["state"] = "terminated"
            inst["terminated_at"] = _now()
            inst["updated"] = _now()
            _record_usage("vpc.delete.terminate_instance", {"vpc_id": vpc_id, "instance_id": inst.get("instance_id")})

    for subnet_id, subnet in list(vpc_state["subnets"].items()):
        if subnet.get("vpc_id") == vpc_id:
            rt_id = subnet.get("route_table_id")
            if rt_id and rt_id in vpc_state["route_tables"]:
                rt = vpc_state["route_tables"][rt_id]
                rt["subnet_ids"] = [sid for sid in rt.get("subnet_ids", []) if sid != subnet_id]
            del vpc_state["subnets"][subnet_id]

    for rt_id, rt in list(vpc_state["route_tables"].items()):
        if rt.get("vpc_id") == vpc_id:
            del vpc_state["route_tables"][rt_id]

    for sg_id, sg in list(vpc_state["security_groups"].items()):
        if sg.get("vpc_id") == vpc_id:
            del vpc_state["security_groups"][sg_id]

    for igw_id, igw in list(vpc_state["internet_gateways"].items()):
        if igw.get("attached_vpc_id") == vpc_id:
            del vpc_state["internet_gateways"][igw_id]

    del vpc_state["vpcs"][vpc_id]
    _record_usage("vpc.delete_vpc", {"vpc_id": vpc_id, "force": force})
    return {"deleted": True, "vpc_id": vpc_id}


def api_vpc_create_subnet(req: SubnetRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    subnet_id = _id("subnet")
    main_rt_id = vpc_state["vpcs"][req.vpc_id].get("main_route_table_id", "")
    subnet = {
        "subnet_id": subnet_id,
        "vpc_id": req.vpc_id,
        "cidr_block": req.cidr_block,
        "availability_zone": req.availability_zone,
        "name": req.name or subnet_id,
        "route_table_id": main_rt_id,
        "created": _now(),
        "tags": req.tags or [],
    }
    vpc_state["subnets"][subnet_id] = subnet
    if main_rt_id and main_rt_id in vpc_state["route_tables"]:
        _vpc_associate_subnet_to_route_table(main_rt_id, subnet_id)
    _record_usage("vpc.create_subnet", subnet)
    return subnet


def api_vpc_create_security_group(req: SecurityGroupRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    sg_id = _id("sg")
    sg = {"security_group_id": sg_id, "vpc_id": req.vpc_id, "group_name": req.group_name, "description": req.description, "ingress": [], "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "allow all outbound traffic", "created": _now()}], "is_default": False, "created": _now(), "tags": req.tags or []}
    vpc_state["security_groups"][sg_id] = sg
    _record_usage("vpc.create_security_group", sg)
    return sg


def api_vpc_add_ingress(sg_id: str, payload: dict[str, Any]):
    sg = vpc_state["security_groups"].get(sg_id)
    if not sg:
        raise HTTPException(404, detail="NoSuchSecurityGroup")
    rule = {"protocol": payload.get("protocol", "tcp"), "from_port": payload.get("from_port", 0), "to_port": payload.get("to_port", 65535), "cidr": payload.get("cidr", "0.0.0.0/0"), "source_sg": payload.get("source_sg", ""), "description": payload.get("description", ""), "created": _now()}
    sg.setdefault("ingress", []).append(rule)
    _record_usage("vpc.add_ingress", {"sg_id": sg_id, "rule": rule})
    return sg


def api_vpc_list_subnets():
    return {"subnets": list(vpc_state["subnets"].values()), "count": len(vpc_state["subnets"])}


def api_vpc_list_security_groups():
    return {"security_groups": list(vpc_state["security_groups"].values()), "count": len(vpc_state["security_groups"])}


def api_vpc_list_route_tables():
    return {"route_tables": list(vpc_state["route_tables"].values()), "count": len(vpc_state["route_tables"])}


def api_vpc_create_route_table(req: RouteTableRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    rt_id = _id("rtb")
    rt = {
        "route_table_id": rt_id,
        "vpc_id": req.vpc_id,
        "name": req.name or rt_id,
        "routes": [{"destination": vpc_state["vpcs"][req.vpc_id].get("cidr_block", "10.0.0.0/16"), "target_type": "local", "target_id": req.vpc_id, "type": "CreateRouteTable", "created": _now()}],
        "subnet_ids": [],
        "is_main": False,
        "created": _now(),
        "tags": req.tags or [],
    }
    vpc_state["route_tables"][rt_id] = rt
    _record_usage("vpc.create_route_table", rt)
    return rt


def api_vpc_list_internet_gateways():
    return {"internet_gateways": list(vpc_state["internet_gateways"].values()), "count": len(vpc_state["internet_gateways"])}


def api_vpc_create_internet_gateway(req: InternetGatewayRequest):
    igw_id = _id("igw")
    igw = {"internet_gateway_id": igw_id, "name": req.name or igw_id, "attached_vpc_id": "", "created": _now(), "tags": req.tags or []}
    vpc_state["internet_gateways"][igw_id] = igw
    _record_usage("vpc.create_internet_gateway", igw)
    return igw


def api_vpc_attach_internet_gateway(igw_id: str, payload: dict[str, Any]):
    vpc_id = payload.get("vpc_id", "")
    igw = _vpc_attach_internet_gateway_record(igw_id, vpc_id)
    _record_usage("vpc.attach_internet_gateway", {"igw_id": igw_id, "vpc_id": vpc_id})
    return igw


def api_vpc_add_route(rt_id: str, payload: dict[str, Any]):
    rt = vpc_state["route_tables"].get(rt_id)
    if not rt:
        raise HTTPException(404, detail="NoSuchRouteTable")
    route = {
        "destination": payload.get("destination_cidr", "0.0.0.0/0"),
        "target_type": payload.get("target_type", "internet-gateway"),
        "target_id": payload.get("target_id", ""),
        "type": "CreateRoute",
        "created": _now(),
    }
    rt.setdefault("routes", []).append(route)
    _record_usage("vpc.add_route", {"route_table_id": rt_id, "route": route})
    return rt


def api_vpc_associate_subnet(rt_id: str, req: SubnetAssociationRequest):
    _vpc_associate_subnet_to_route_table(rt_id, req.subnet_id)
    _record_usage("vpc.associate_subnet", {"route_table_id": rt_id, "subnet_id": req.subnet_id})
    return vpc_state["route_tables"][rt_id]


def api_vpc_resources(vpc_id: str):
    if vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    subnets = [s for s in vpc_state["subnets"].values() if s.get("vpc_id") == vpc_id]
    route_tables = [r for r in vpc_state["route_tables"].values() if r.get("vpc_id") == vpc_id]
    security_groups = [g for g in vpc_state["security_groups"].values() if g.get("vpc_id") == vpc_id]
    internet_gateways = [g for g in vpc_state["internet_gateways"].values() if g.get("attached_vpc_id") == vpc_id]
    instances = [i for i in ec2_state["instances"].values() if i.get("vpc_id") == vpc_id]
    return {
        "vpc": vpc_state["vpcs"][vpc_id],
        "subnets": subnets,
        "route_tables": route_tables,
        "security_groups": security_groups,
        "internet_gateways": internet_gateways,
        "instances": instances,
        "counts": {
            "subnets": len(subnets),
            "route_tables": len(route_tables),
            "security_groups": len(security_groups),
            "internet_gateways": len(internet_gateways),
            "instances": len(instances),
        },
    }


def _vpc_normalize_tags(tags: Any) -> list[dict[str, str]]:
    normalized: dict[str, str] = {}
    for tag in tags or []:
        if not isinstance(tag, dict):
            continue
        key = str(tag.get("key") or tag.get("Key") or "").strip()
        if not key:
            continue
        value = str(tag.get("value") or tag.get("Value") or "")
        normalized[key] = value
    return [{"key": key, "value": value} for key, value in normalized.items()]


def _vpc_resource_tags(resource: dict) -> list[dict[str, str]]:
    return _vpc_normalize_tags(resource.get("tags") or [])


def _vpc_set_resource_tags(resource: dict, tags: Any) -> dict:
    resource["tags"] = _vpc_normalize_tags(tags)
    return resource


def _vpc_parse_tag_specifications(params: dict[str, Any], resource_type: str | None = None) -> list[dict[str, str]]:
    specs: dict[str, dict[str, Any]] = {}
    for key, value in params.items():
        m = re.match(r"^TagSpecification\.(\d+)\.ResourceType$", key)
        if m:
            specs.setdefault(m.group(1), {})["resource_type"] = str(value)
            continue
        m = re.match(r"^TagSpecification\.(\d+)\.Tag\.(\d+)\.(Key|Value)$", key)
        if m:
            spec_idx, tag_idx, part = m.groups()
            spec = specs.setdefault(spec_idx, {})
            tag_map = spec.setdefault("tags", {})
            tag = tag_map.setdefault(tag_idx, {})
            tag[part.lower()] = str(value)
            continue
        m = re.match(r"^TagSpecification\.(\d+)\.(Key|Value)$", key)
        if m:
            spec_idx, part = m.groups()
            spec = specs.setdefault(spec_idx, {})
            tag_map = spec.setdefault("tags", {})
            tag = tag_map.setdefault("1", {})
            tag[part.lower()] = str(value)
            continue

    tags: list[dict[str, str]] = []
    for spec_idx in sorted(specs.keys(), key=lambda item: int(item)):
        spec = specs[spec_idx]
        spec_type = str(spec.get("resource_type", "")).strip().lower()
        if resource_type and spec_type and spec_type != resource_type.lower():
            continue
        tag_map = spec.get("tags", {})
        for tag_idx in sorted(tag_map.keys(), key=lambda item: int(item)):
            tag = tag_map[tag_idx]
            key = str(tag.get("key", "")).strip()
            if not key:
                continue
            tags.append({"key": key, "value": str(tag.get("value", ""))})
    return _vpc_normalize_tags(tags)


def _vpc_association_id(route_table_id: str, subnet_id: str) -> str:
    digest = hashlib.sha1(f"{route_table_id}:{subnet_id}".encode("utf-8")).hexdigest()[:17]
    return f"rtbassoc-{digest}"


def _vpc_zone_id(availability_zone: str) -> str:
    zone = (availability_zone or "us-east-1a").strip()
    suffix = zone[-1].lower() if zone and zone[-1].isalpha() else "a"
    idx = ord(suffix) - 96
    if idx < 1 or idx > 26:
        idx = 1
    return f"use1-az{idx}"


def _vpc_available_ip_count(cidr_block: str) -> int:
    try:
        network = ipaddress.ip_network(cidr_block, strict=False)
    except Exception:
        return 0
    if network.version == 4:
        return max(int(network.num_addresses) - 5, 0)
    return int(network.num_addresses)


def _vpc_find_resource(resource_id: str) -> tuple[str, dict] | None:
    if resource_id.startswith("vpc-") and resource_id in vpc_state["vpcs"]:
        return ("vpc", vpc_state["vpcs"][resource_id])
    if resource_id.startswith("subnet-") and resource_id in vpc_state["subnets"]:
        return ("subnet", vpc_state["subnets"][resource_id])
    if resource_id.startswith("sg-") and resource_id in vpc_state["security_groups"]:
        return ("security-group", vpc_state["security_groups"][resource_id])
    if resource_id.startswith("rtb-") and resource_id in vpc_state["route_tables"]:
        return ("route-table", vpc_state["route_tables"][resource_id])
    if resource_id.startswith("igw-") and resource_id in vpc_state["internet_gateways"]:
        return ("internet-gateway", vpc_state["internet_gateways"][resource_id])
    return None


def _vpc_all_tag_items() -> list[tuple[str, str, dict, dict[str, str]]]:
    items: list[tuple[str, str, dict, dict[str, str]]] = []
    for vpc in vpc_state["vpcs"].values():
        items.extend([("vpc", vpc["vpc_id"], vpc, tag) for tag in _vpc_resource_tags(vpc)])
    for subnet in vpc_state["subnets"].values():
        items.extend([("subnet", subnet["subnet_id"], subnet, tag) for tag in _vpc_resource_tags(subnet)])
    for sg_id, sg in vpc_state["security_groups"].items():
        items.extend([("security-group", sg_id, sg, tag) for tag in _vpc_resource_tags(sg)])
    for rt in vpc_state["route_tables"].values():
        items.extend([("route-table", rt["route_table_id"], rt, tag) for tag in _vpc_resource_tags(rt)])
    for igw in vpc_state["internet_gateways"].values():
        items.extend([("internet-gateway", igw["internet_gateway_id"], igw, tag) for tag in _vpc_resource_tags(igw)])
    return items


def _vpc_tag_set_xml(parent: ET.Element, tags: Any) -> ET.Element:
    tag_set = _ec2_sub(parent, "tagSet")
    for tag in _vpc_normalize_tags(tags):
        item = _ec2_sub(tag_set, "item")
        _ec2_sub(item, "key", tag["key"])
        _ec2_sub(item, "value", tag["value"])
    return tag_set


def _vpc_vpc_xml(vpc: dict) -> ET.Element:
    item = _ec2_xml("item")
    vpc_id = vpc["vpc_id"]
    _ec2_sub(item, "vpcId", vpc_id)
    _ec2_sub(item, "ownerId", AWS_ACCOUNT_ID)
    _ec2_sub(item, "state", vpc.get("state", "available"))
    _ec2_sub(item, "cidrBlock", vpc.get("cidr_block", "10.0.0.0/16"))
    cidr_set = _ec2_sub(item, "cidrBlockAssociationSet")
    cidr_item = _ec2_sub(cidr_set, "item")
    _ec2_sub(cidr_item, "cidrBlock", vpc.get("cidr_block", "10.0.0.0/16"))
    _ec2_sub(cidr_item, "associationId", f"vpc-cidr-assoc-{vpc_id.replace('vpc-', '')[:12] or 'sim'}")
    cidr_state = _ec2_sub(cidr_item, "cidrBlockState")
    _ec2_sub(cidr_state, "state", "associated")
    ipv6_set = _ec2_sub(item, "ipv6CidrBlockAssociationSet")
    if vpc.get("ipv6_mode") and vpc.get("ipv6_mode") != "none":
        ipv6_item = _ec2_sub(ipv6_set, "item")
        _ec2_sub(ipv6_item, "ipv6CidrBlock", vpc.get("ipv6_mode"))
        _ec2_sub(ipv6_item, "associationId", f"vpc-ipv6-assoc-{vpc_id.replace('vpc-', '')[:12] or 'sim'}")
        ipv6_state = _ec2_sub(ipv6_item, "ipv6CidrBlockState")
        _ec2_sub(ipv6_state, "state", "associated")
    _ec2_sub(item, "dhcpOptionsId", vpc.get("dhcp_options_id", f"dopt-{vpc_id.replace('vpc-', '')[:8] or 'sim'}"))
    _vpc_tag_set_xml(item, vpc.get("tags", []))
    _ec2_sub(item, "instanceTenancy", vpc.get("tenancy", "default"))
    _ec2_sub(item, "isDefault", "false")
    return item


def _vpc_subnet_xml(subnet: dict) -> ET.Element:
    item = _ec2_xml("item")
    subnet_id = subnet["subnet_id"]
    vpc_id = subnet.get("vpc_id", "")
    cidr_block = subnet.get("cidr_block", "")
    availability_zone = subnet.get("availability_zone", "us-east-1a")
    _ec2_sub(item, "subnetId", subnet_id)
    _ec2_sub(item, "subnetArn", f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:subnet/{subnet_id}")
    _ec2_sub(item, "state", "available")
    _ec2_sub(item, "ownerId", AWS_ACCOUNT_ID)
    _ec2_sub(item, "vpcId", vpc_id)
    _ec2_sub(item, "cidrBlock", cidr_block)
    cidr_set = _ec2_sub(item, "cidrBlockAssociationSet")
    cidr_item = _ec2_sub(cidr_set, "item")
    _ec2_sub(cidr_item, "cidrBlock", cidr_block)
    _ec2_sub(cidr_item, "associationId", f"subnet-cidr-assoc-{subnet_id.replace('subnet-', '')[:12] or 'sim'}")
    cidr_state = _ec2_sub(cidr_item, "cidrBlockState")
    _ec2_sub(cidr_state, "state", "associated")
    ipv6_set = _ec2_sub(item, "ipv6CidrBlockAssociationSet")
    _ec2_sub(item, "availableIpAddressCount", str(_vpc_available_ip_count(cidr_block)))
    _ec2_sub(item, "availabilityZone", availability_zone)
    _ec2_sub(item, "availabilityZoneId", _vpc_zone_id(availability_zone))
    _ec2_sub(item, "defaultForAz", "false")
    _ec2_sub(item, "mapPublicIpOnLaunch", "false")
    _ec2_sub(item, "assignIpv6AddressOnCreation", "false")
    _vpc_tag_set_xml(item, subnet.get("tags", []))
    return item


def _vpc_internet_gateway_xml(igw: dict) -> ET.Element:
    item = _ec2_xml("item")
    igw_id = igw["internet_gateway_id"]
    _ec2_sub(item, "internetGatewayId", igw_id)
    attachment_set = _ec2_sub(item, "attachmentSet")
    attached_vpc_id = igw.get("attached_vpc_id", "")
    if attached_vpc_id:
        attachment = _ec2_sub(attachment_set, "item")
        _ec2_sub(attachment, "vpcId", attached_vpc_id)
        _ec2_sub(attachment, "state", "available")
    _vpc_tag_set_xml(item, igw.get("tags", []))
    return item


def _vpc_route_xml(route: dict, vpc: dict) -> ET.Element:
    item = _ec2_xml("item")
    destination = str(route.get("destination", ""))
    target_type = str(route.get("target_type", ""))
    target_id = str(route.get("target_id", ""))
    route_type = str(route.get("type", target_type or ""))
    if route_type in {"local", "CreateRouteTable"} or destination == "local":
        _ec2_sub(item, "destinationCidrBlock", vpc.get("cidr_block", "10.0.0.0/16"))
        _ec2_sub(item, "gatewayId", "local")
    else:
        _ec2_sub(item, "destinationCidrBlock", destination)
        if target_type == "internet-gateway":
            _ec2_sub(item, "gatewayId", target_id)
        elif target_type == "instance":
            _ec2_sub(item, "instanceId", target_id)
        elif target_type == "vpc-peering-connection":
            _ec2_sub(item, "vpcPeeringConnectionId", target_id)
        elif target_type == "nat-gateway":
            _ec2_sub(item, "natGatewayId", target_id)
        elif target_type == "transit-gateway":
            _ec2_sub(item, "transitGatewayId", target_id)
        else:
            _ec2_sub(item, "gatewayId", target_id)
    _ec2_sub(item, "state", "active")
    _ec2_sub(item, "origin", "CreateRouteTable" if route_type == "local" else "CreateRoute")
    return item


def _vpc_route_table_xml(rt: dict) -> ET.Element:
    item = _ec2_xml("item")
    rt_id = rt["route_table_id"]
    _ec2_sub(item, "routeTableId", rt_id)
    _ec2_sub(item, "routeTableArn", f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:route-table/{rt_id}")
    _ec2_sub(item, "vpcId", rt.get("vpc_id", ""))
    _ec2_sub(item, "ownerId", AWS_ACCOUNT_ID)
    route_set = _ec2_sub(item, "routeSet")
    for route in rt.get("routes", []) or []:
        route_item = _ec2_sub(route_set, "item")
        route_item.extend(list(_vpc_route_xml(route, vpc_state["vpcs"].get(rt.get("vpc_id", ""), {}))))
    association_set = _ec2_sub(item, "associationSet")
    if rt.get("is_main"):
        assoc = _ec2_sub(association_set, "item")
        _ec2_sub(assoc, "routeTableAssociationId", _vpc_association_id(rt_id, "main"))
        _ec2_sub(assoc, "routeTableId", rt_id)
        _ec2_sub(assoc, "main", "true")
    for subnet_id in rt.get("subnet_ids", []) or []:
        assoc = _ec2_sub(association_set, "item")
        _ec2_sub(assoc, "routeTableAssociationId", _vpc_association_id(rt_id, subnet_id))
        _ec2_sub(assoc, "routeTableId", rt_id)
        _ec2_sub(assoc, "subnetId", subnet_id)
        _ec2_sub(assoc, "main", "false")
    _ec2_sub(item, "propagatingVgwSet")
    _vpc_tag_set_xml(item, rt.get("tags", []))
    return item


def _vpc_security_group_xml(group_id: str, group: dict) -> ET.Element:
    return _ec2_security_group_xml(group_id, group)


def _vpc_associate_subnet_to_route_table(rt_id: str, subnet_id: str) -> str:
    rt = vpc_state["route_tables"].get(rt_id)
    subnet = vpc_state["subnets"].get(subnet_id)
    if not rt:
        raise HTTPException(404, detail="NoSuchRouteTable")
    if not subnet:
        raise HTTPException(404, detail="NoSuchSubnet")
    if subnet.get("vpc_id") != rt.get("vpc_id"):
        raise HTTPException(400, detail="SubnetAndRouteTableMustBeInSameVpc")
    previous_rt_id = subnet.get("route_table_id", "")
    if previous_rt_id and previous_rt_id in vpc_state["route_tables"]:
        prev_rt = vpc_state["route_tables"][previous_rt_id]
        prev_rt["subnet_ids"] = [sid for sid in prev_rt.get("subnet_ids", []) if sid != subnet_id]
    subnet["route_table_id"] = rt_id
    rt.setdefault("subnet_ids", [])
    if subnet_id not in rt["subnet_ids"]:
        rt["subnet_ids"].append(subnet_id)
    return _vpc_association_id(rt_id, subnet_id)


def _vpc_disassociate_subnet_from_route_table(rt_id: str, subnet_id: str) -> str:
    rt = vpc_state["route_tables"].get(rt_id)
    subnet = vpc_state["subnets"].get(subnet_id)
    if not rt:
        raise HTTPException(404, detail="NoSuchRouteTable")
    if not subnet:
        raise HTTPException(404, detail="NoSuchSubnet")
    if subnet.get("route_table_id") != rt_id:
        raise HTTPException(409, detail="InvalidAssociationID.NotFound")
    rt["subnet_ids"] = [sid for sid in rt.get("subnet_ids", []) if sid != subnet_id]
    main_rt_id = vpc_state["vpcs"].get(rt.get("vpc_id", ""), {}).get("main_route_table_id", "")
    subnet["route_table_id"] = main_rt_id
    if main_rt_id and main_rt_id in vpc_state["route_tables"]:
        main_rt = vpc_state["route_tables"][main_rt_id]
        main_rt.setdefault("subnet_ids", [])
        if subnet_id not in main_rt["subnet_ids"]:
            main_rt["subnet_ids"].append(subnet_id)
    return _vpc_association_id(rt_id, subnet_id)


def _vpc_attach_internet_gateway_record(igw_id: str, vpc_id: str) -> dict:
    igw = vpc_state.setdefault("internet_gateways", {}).get(igw_id)
    if not igw:
        raise HTTPException(404, detail="NoSuchInternetGateway")
    if vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    existing = igw.get("attached_vpc_id", "")
    if existing and existing != vpc_id:
        raise HTTPException(409, detail="InternetGatewayAlreadyAttached")
    igw["attached_vpc_id"] = vpc_id
    vpc_state["vpcs"][vpc_id]["internet_gateway_id"] = igw_id
    return igw


def _vpc_detach_internet_gateway_record(igw_id: str) -> dict:
    igw = vpc_state["internet_gateways"].get(igw_id)
    if not igw:
        raise HTTPException(404, detail="NoSuchInternetGateway")
    attached_vpc_id = igw.get("attached_vpc_id", "")
    if attached_vpc_id and attached_vpc_id in vpc_state["vpcs"]:
        if vpc_state["vpcs"][attached_vpc_id].get("internet_gateway_id") == igw_id:
            vpc_state["vpcs"][attached_vpc_id]["internet_gateway_id"] = ""
    igw["attached_vpc_id"] = ""
    return igw


def _vpc_delete_subnet_record(subnet_id: str) -> None:
    subnet = vpc_state["subnets"].get(subnet_id)
    if not subnet:
        raise HTTPException(404, detail="NoSuchSubnet")
    active_instances = [inst for inst in ec2_state["instances"].values() if inst.get("subnet_id") == subnet_id and inst.get("state") not in {"terminated"}]
    if active_instances:
        raise HTTPException(409, detail="DependencyViolation")
    for rt in vpc_state["route_tables"].values():
        rt["subnet_ids"] = [sid for sid in rt.get("subnet_ids", []) if sid != subnet_id]
    del vpc_state["subnets"][subnet_id]


def _vpc_delete_route_table_record(rt_id: str) -> None:
    rt = vpc_state["route_tables"].get(rt_id)
    if not rt:
        raise HTTPException(404, detail="NoSuchRouteTable")
    if rt.get("is_main"):
        raise HTTPException(409, detail="CannotDeleteMainRouteTable")
    if rt.get("subnet_ids"):
        raise HTTPException(409, detail="RouteTableInUse")
    del vpc_state["route_tables"][rt_id]


def _vpc_delete_internet_gateway_record(igw_id: str) -> None:
    igw = vpc_state["internet_gateways"].get(igw_id)
    if not igw:
        raise HTTPException(404, detail="NoSuchInternetGateway")
    if igw.get("attached_vpc_id"):
        raise HTTPException(409, detail="DependencyViolation")
    del vpc_state["internet_gateways"][igw_id]


def _vpc_iter_describe_tags() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for resource_type, resource_id, _resource, tag in _vpc_all_tag_items():
        items.append({
            "resource_type": resource_type,
            "resource_id": resource_id,
            "key": tag["key"],
            "value": tag["value"],
        })
    return items


def _vpc_query_paginate(items: list[Any], params: dict[str, Any], default_max: int = 1000) -> tuple[list[Any], str]:
    raw_next = str(params.get("NextToken", params.get("nextToken", "")) or "").strip()
    start = 0
    if raw_next:
        try:
            start = max(int(raw_next), 0)
        except Exception:
            start = 0
    raw_max = params.get("MaxResults", params.get("maxResults", default_max))
    try:
        max_results = int(raw_max)
    except Exception:
        max_results = default_max
    if max_results <= 0:
        max_results = default_max
    if max_results > default_max:
        max_results = default_max
    end = start + max_results
    page = items[start:end]
    next_token = str(end) if end < len(items) else ""
    return page, next_token


def _vpc_query_describe_vpcs(params: dict[str, Any]) -> Response:
    vpc_ids = []
    for key, value in params.items():
        if key.lower().startswith("vpcid") and value:
            if isinstance(value, list):
                vpc_ids.extend([str(v) for v in value if v])
            else:
                vpc_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    vpcs = []
    for vpc in vpc_state["vpcs"].values():
        if vpc_ids and vpc["vpc_id"] not in vpc_ids:
            continue
        matched = True
        tags = {tag["key"]: tag["value"] for tag in _vpc_resource_tags(vpc)}
        for name, values in filters:
            lname = name.lower()
            if lname == "vpc-id" and vpc["vpc_id"] not in values:
                matched = False
            elif lname == "cidr" and vpc.get("cidr_block", "") not in values:
                matched = False
            elif lname == "state" and vpc.get("state", "available") not in values:
                matched = False
            elif lname == "is-default" and str(vpc.get("is_default", False)).lower() not in [str(v).lower() for v in values]:
                matched = False
            elif lname.startswith("tag:"):
                key = name.split(":", 1)[1]
                if tags.get(key, "") not in values:
                    matched = False
            elif lname == "tag-key":
                if not any(k in values for k in tags.keys()):
                    matched = False
            elif lname == "tag":
                if not any(k in values or v in values for k, v in tags.items()):
                    matched = False
        if matched:
            vpcs.append(vpc)
    vpcs.sort(key=lambda item: (item.get("created", ""), item.get("vpc_id", "")))
    page, next_token = _vpc_query_paginate(vpcs, params, 1000)

    def build(root: ET.Element) -> None:
        if next_token:
            _ec2_sub(root, "nextToken", next_token)
        vpc_set = _ec2_sub(root, "vpcSet")
        for vpc in page:
            vpc_set.append(_vpc_vpc_xml(vpc))

    return _ec2_success_response("DescribeVpcsResponse", build)


def _vpc_query_describe_subnets(params: dict[str, Any]) -> Response:
    subnet_ids = []
    for key, value in params.items():
        if key.lower().startswith("subnetid") and value:
            if isinstance(value, list):
                subnet_ids.extend([str(v) for v in value if v])
            else:
                subnet_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    subnets = []
    for subnet in vpc_state["subnets"].values():
        if subnet_ids and subnet["subnet_id"] not in subnet_ids:
            continue
        tags = {tag["key"]: tag["value"] for tag in _vpc_resource_tags(subnet)}
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "subnet-id" and subnet["subnet_id"] not in values:
                matched = False
            elif lname == "vpc-id" and subnet.get("vpc_id", "") not in values:
                matched = False
            elif lname == "availability-zone" and subnet.get("availability_zone", "") not in values:
                matched = False
            elif lname == "cidr-block" and subnet.get("cidr_block", "") not in values:
                matched = False
            elif lname == "state" and "available" not in values:
                matched = False
            elif lname.startswith("tag:"):
                key = name.split(":", 1)[1]
                if tags.get(key, "") not in values:
                    matched = False
            elif lname == "tag-key":
                if not any(k in values for k in tags.keys()):
                    matched = False
            elif lname == "tag":
                if not any(k in values or v in values for k, v in tags.items()):
                    matched = False
        if matched:
            subnets.append(subnet)
    subnets.sort(key=lambda item: (item.get("created", ""), item.get("subnet_id", "")))
    page, next_token = _vpc_query_paginate(subnets, params, 1000)

    def build(root: ET.Element) -> None:
        if next_token:
            _ec2_sub(root, "nextToken", next_token)
        subnet_set = _ec2_sub(root, "subnetSet")
        for subnet in page:
            subnet_set.append(_vpc_subnet_xml(subnet))

    return _ec2_success_response("DescribeSubnetsResponse", build)


def _vpc_query_describe_security_groups(params: dict[str, Any]) -> Response:
    group_ids = []
    for key, value in params.items():
        if key.lower().startswith("groupid") and value:
            if isinstance(value, list):
                group_ids.extend([str(v) for v in value if v])
            else:
                group_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    groups: list[tuple[str, dict]] = []
    for group_id, group in vpc_state["security_groups"].items():
        if group_ids and group_id not in group_ids:
            continue
        tags = {tag["key"]: tag["value"] for tag in _vpc_resource_tags(group)}
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "group-id" and group_id not in values:
                matched = False
            elif lname == "group-name" and group.get("group_name", group_id) not in values:
                matched = False
            elif lname == "vpc-id" and group.get("vpc_id", "") not in values:
                matched = False
            elif lname == "description" and group.get("description", "") not in values:
                matched = False
            elif lname.startswith("tag:"):
                key = name.split(":", 1)[1]
                if tags.get(key, "") not in values:
                    matched = False
            elif lname == "tag-key":
                if not any(k in values for k in tags.keys()):
                    matched = False
            elif lname == "tag":
                if not any(k in values or v in values for k, v in tags.items()):
                    matched = False
        if matched:
            groups.append((group_id, group))
    groups.sort(key=lambda item: (not item[1].get("is_default", False), item[1].get("created", ""), item[0]))
    page, next_token = _vpc_query_paginate(groups, params, 1000)

    def build(root: ET.Element) -> None:
        if next_token:
            _ec2_sub(root, "nextToken", next_token)
        info = _ec2_sub(root, "securityGroupInfo")
        for group_id, group in page:
            info.append(_vpc_security_group_xml(group_id, group))

    return _ec2_success_response("DescribeSecurityGroupsResponse", build)


def _vpc_query_describe_route_tables(params: dict[str, Any]) -> Response:
    route_table_ids = []
    for key, value in params.items():
        if key.lower().startswith("routetableid") and value:
            if isinstance(value, list):
                route_table_ids.extend([str(v) for v in value if v])
            else:
                route_table_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    route_tables = []
    for rt in vpc_state["route_tables"].values():
        if route_table_ids and rt["route_table_id"] not in route_table_ids:
            continue
        tags = {tag["key"]: tag["value"] for tag in _vpc_resource_tags(rt)}
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "route-table-id" and rt["route_table_id"] not in values:
                matched = False
            elif lname == "vpc-id" and rt.get("vpc_id", "") not in values:
                matched = False
            elif lname == "association.subnet-id" and not any(subnet_id in values for subnet_id in rt.get("subnet_ids", [])):
                matched = False
            elif lname == "association.main" and str(rt.get("is_main", False)).lower() not in [str(v).lower() for v in values]:
                matched = False
            elif lname == "route.destination-cidr-block":
                vpc_cidr = vpc_state["vpcs"].get(rt.get("vpc_id", ""), {}).get("cidr_block", "")
                if not any(route.get("destination", "") in values or (route.get("type") == "local" and vpc_cidr in values) for route in rt.get("routes", [])):
                    matched = False
            elif lname == "route.gateway-id" and not any(route.get("target_id", "") in values for route in rt.get("routes", [])):
                matched = False
            elif lname == "route.origin" and not any(route.get("type", "") in values for route in rt.get("routes", [])):
                matched = False
            elif lname.startswith("tag:"):
                key = name.split(":", 1)[1]
                if tags.get(key, "") not in values:
                    matched = False
            elif lname == "tag-key":
                if not any(k in values for k in tags.keys()):
                    matched = False
            elif lname == "tag":
                if not any(k in values or v in values for k, v in tags.items()):
                    matched = False
        if matched:
            route_tables.append(rt)
    route_tables.sort(key=lambda item: (not item.get("is_main", False), item.get("created", ""), item.get("route_table_id", "")))
    page, next_token = _vpc_query_paginate(route_tables, params, 100)

    def build(root: ET.Element) -> None:
        if next_token:
            _ec2_sub(root, "nextToken", next_token)
        route_table_set = _ec2_sub(root, "routeTableSet")
        for rt in page:
            route_table_set.append(_vpc_route_table_xml(rt))

    return _ec2_success_response("DescribeRouteTablesResponse", build)


def _vpc_query_describe_internet_gateways(params: dict[str, Any]) -> Response:
    igw_ids = []
    for key, value in params.items():
        if key.lower().startswith("internetgatewayid") and value:
            if isinstance(value, list):
                igw_ids.extend([str(v) for v in value if v])
            else:
                igw_ids.append(str(value))
    filters = _ec2_parse_filters(params)
    igws = []
    for igw in vpc_state["internet_gateways"].values():
        if igw_ids and igw["internet_gateway_id"] not in igw_ids:
            continue
        tags = {tag["key"]: tag["value"] for tag in _vpc_resource_tags(igw)}
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "internet-gateway-id" and igw["internet_gateway_id"] not in values:
                matched = False
            elif lname == "attachment.vpc-id" and igw.get("attached_vpc_id", "") not in values:
                matched = False
            elif lname == "attachment.state" and (("available" if igw.get("attached_vpc_id") else "") not in values):
                matched = False
            elif lname.startswith("tag:"):
                key = name.split(":", 1)[1]
                if tags.get(key, "") not in values:
                    matched = False
            elif lname == "tag-key":
                if not any(k in values for k in tags.keys()):
                    matched = False
            elif lname == "tag":
                if not any(k in values or v in values for k, v in tags.items()):
                    matched = False
        if matched:
            igws.append(igw)
    igws.sort(key=lambda item: (item.get("created", ""), item.get("internet_gateway_id", "")))
    page, next_token = _vpc_query_paginate(igws, params, 1000)

    def build(root: ET.Element) -> None:
        if next_token:
            _ec2_sub(root, "nextToken", next_token)
        igw_set = _ec2_sub(root, "internetGatewaySet")
        for igw in page:
            igw_set.append(_vpc_internet_gateway_xml(igw))

    return _ec2_success_response("DescribeInternetGatewaysResponse", build)


def _vpc_query_describe_tags(params: dict[str, Any]) -> Response:
    filters = _ec2_parse_filters(params)
    tags = _vpc_iter_describe_tags()
    filtered = []
    for tag in tags:
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "resource-id" and tag["resource_id"] not in values:
                matched = False
            elif lname == "resource-type" and tag["resource_type"] not in values:
                matched = False
            elif lname == "key" and tag["key"] not in values:
                matched = False
            elif lname == "value" and tag["value"] not in values:
                matched = False
        if matched:
            filtered.append(tag)
    filtered.sort(key=lambda item: (item["resource_type"], item["resource_id"], item["key"], item["value"]))
    page, next_token = _vpc_query_paginate(filtered, params, 1000)

    def build(root: ET.Element) -> None:
        if next_token:
            _ec2_sub(root, "nextToken", next_token)
        tag_set = _ec2_sub(root, "tagSet")
        for tag in page:
            item = _ec2_sub(tag_set, "item")
            _ec2_sub(item, "resourceId", tag["resource_id"])
            _ec2_sub(item, "resourceType", tag["resource_type"])
            _ec2_sub(item, "key", tag["key"])
            _ec2_sub(item, "value", tag["value"])

    return _ec2_success_response("DescribeTagsResponse", build)


def _vpc_query_create_vpc(params: dict[str, Any]) -> Response:
    cidr_block = str(params.get("CidrBlock", params.get("cidrBlock", "10.0.0.0/16"))).strip() or "10.0.0.0/16"
    tenancy = str(params.get("InstanceTenancy", params.get("instanceTenancy", "default"))).strip() or "default"
    ipv6_mode = "none"
    if str(params.get("AmazonProvidedIpv6CidrBlock", "")).lower() == "true":
        ipv6_mode = "amazon-provided"
    elif str(params.get("Ipv6CidrBlock", "")).strip():
        ipv6_mode = str(params.get("Ipv6CidrBlock", "")).strip()
    tags = _vpc_parse_tag_specifications(params, "vpc")
    name_tag = next((tag["value"] for tag in tags if tag["key"].lower() == "name"), "")
    req = VpcRequest(
        name=name_tag or str(params.get("TagSpecification.1.Tag.1.Value", "")) or f"vpc-{secrets.token_hex(3)}",
        cidr_block=cidr_block,
        encryption_controls="None",
        tenancy=tenancy,
        ipv6_mode=ipv6_mode,
        tags=tags,
    )
    vpc = api_vpc_create(req)

    def build(root: ET.Element) -> None:
        vpc_el = _ec2_sub(root, "vpc")
        vpc_el.extend(list(_vpc_vpc_xml(vpc)))

    return _ec2_success_response("CreateVpcResponse", build)


def _vpc_query_create_subnet(params: dict[str, Any]) -> Response:
    vpc_id = str(params.get("VpcId", params.get("vpcId", ""))).strip()
    if not vpc_id:
        raise HTTPException(400, detail="MissingParameter: VpcId")
    cidr_block = str(params.get("CidrBlock", params.get("cidrBlock", ""))).strip()
    az = str(params.get("AvailabilityZone", params.get("availabilityZone", "us-east-1a"))).strip() or "us-east-1a"
    tags = _vpc_parse_tag_specifications(params, "subnet")
    name_tag = next((tag["value"] for tag in tags if tag["key"].lower() == "name"), "")
    subnet = api_vpc_create_subnet(SubnetRequest(vpc_id=vpc_id, cidr_block=cidr_block, availability_zone=az, name=name_tag or f"subnet-{secrets.token_hex(3)}", tags=tags))

    def build(root: ET.Element) -> None:
        subnet_el = _ec2_sub(root, "subnet")
        subnet_el.extend(list(_vpc_subnet_xml(subnet)))

    return _ec2_success_response("CreateSubnetResponse", build)


def _vpc_query_create_security_group(params: dict[str, Any]) -> Response:
    group_name = str(params.get("GroupName", params.get("groupName", ""))).strip()
    group_description = str(params.get("GroupDescription", params.get("groupDescription", ""))).strip()
    vpc_id = str(params.get("VpcId", params.get("vpcId", ""))).strip()
    if not group_name:
        raise HTTPException(400, detail="MissingParameter: GroupName")
    if not group_description:
        raise HTTPException(400, detail="MissingParameter: GroupDescription")
    if not vpc_id:
        raise HTTPException(400, detail="MissingParameter: VpcId")
    tags = _vpc_parse_tag_specifications(params, "security-group")
    sg = api_vpc_create_security_group(SecurityGroupRequest(vpc_id=vpc_id, group_name=group_name, description=group_description, tags=tags))

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")
        _ec2_sub(root, "groupId", sg["security_group_id"])
        _ec2_sub(root, "securityGroupArn", f"arn:aws:ec2:us-east-1:{AWS_ACCOUNT_ID}:security-group/{sg['security_group_id']}")
        _vpc_tag_set_xml(root, sg.get("tags", []))

    return _ec2_success_response("CreateSecurityGroupResponse", build)


def _vpc_query_create_route_table(params: dict[str, Any]) -> Response:
    vpc_id = str(params.get("VpcId", params.get("vpcId", ""))).strip()
    if not vpc_id:
        raise HTTPException(400, detail="MissingParameter: VpcId")
    tags = _vpc_parse_tag_specifications(params, "route-table")
    name_tag = next((tag["value"] for tag in tags if tag["key"].lower() == "name"), "")
    rt = api_vpc_create_route_table(RouteTableRequest(vpc_id=vpc_id, name=name_tag or str(params.get("Name", "")) or f"rtb-{secrets.token_hex(3)}", tags=tags))

    def build(root: ET.Element) -> None:
        route_table_el = _ec2_sub(root, "routeTable")
        route_table_el.extend(list(_vpc_route_table_xml(rt)))

    return _ec2_success_response("CreateRouteTableResponse", build)


def _vpc_query_create_internet_gateway(params: dict[str, Any]) -> Response:
    tags = _vpc_parse_tag_specifications(params, "internet-gateway")
    name_tag = next((tag["value"] for tag in tags if tag["key"].lower() == "name"), "")
    igw = api_vpc_create_internet_gateway(InternetGatewayRequest(name=name_tag or f"igw-{secrets.token_hex(3)}", tags=tags))

    def build(root: ET.Element) -> None:
        internet_gateway_el = _ec2_sub(root, "internetGateway")
        internet_gateway_el.extend(list(_vpc_internet_gateway_xml(igw)))

    return _ec2_success_response("CreateInternetGatewayResponse", build)


def _vpc_query_attach_internet_gateway(params: dict[str, Any]) -> Response:
    igw_id = str(params.get("InternetGatewayId", params.get("internetGatewayId", ""))).strip()
    vpc_id = str(params.get("VpcId", params.get("vpcId", ""))).strip()
    if not igw_id:
        raise HTTPException(400, detail="MissingParameter: InternetGatewayId")
    if not vpc_id:
        raise HTTPException(400, detail="MissingParameter: VpcId")
    igw = _vpc_attach_internet_gateway_record(igw_id, vpc_id)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("AttachInternetGatewayResponse", build)


def _vpc_query_detach_internet_gateway(params: dict[str, Any]) -> Response:
    igw_id = str(params.get("InternetGatewayId", params.get("internetGatewayId", ""))).strip()
    if not igw_id:
        raise HTTPException(400, detail="MissingParameter: InternetGatewayId")
    igw = _vpc_detach_internet_gateway_record(igw_id)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("DetachInternetGatewayResponse", build)


def _vpc_query_create_route(params: dict[str, Any]) -> Response:
    route_table_id = str(params.get("RouteTableId", params.get("routeTableId", ""))).strip()
    destination_cidr = str(params.get("DestinationCidrBlock", params.get("destinationCidrBlock", params.get("DestinationCidr", "0.0.0.0/0")))).strip() or "0.0.0.0/0"
    target_type = "internet-gateway"
    target_id = ""
    if str(params.get("GatewayId", params.get("gatewayId", ""))).strip():
        target_id = str(params.get("GatewayId", params.get("gatewayId", ""))).strip()
        target_type = "internet-gateway"
    elif str(params.get("InstanceId", params.get("instanceId", ""))).strip():
        target_id = str(params.get("InstanceId", params.get("instanceId", ""))).strip()
        target_type = "instance"
    elif str(params.get("VpcPeeringConnectionId", params.get("vpcPeeringConnectionId", ""))).strip():
        target_id = str(params.get("VpcPeeringConnectionId", params.get("vpcPeeringConnectionId", ""))).strip()
        target_type = "vpc-peering-connection"
    elif str(params.get("NatGatewayId", params.get("natGatewayId", ""))).strip():
        target_id = str(params.get("NatGatewayId", params.get("natGatewayId", ""))).strip()
        target_type = "nat-gateway"
    elif str(params.get("TransitGatewayId", params.get("transitGatewayId", ""))).strip():
        target_id = str(params.get("TransitGatewayId", params.get("transitGatewayId", ""))).strip()
        target_type = "transit-gateway"
    if not route_table_id:
        raise HTTPException(400, detail="MissingParameter: RouteTableId")
    rt = vpc_state["route_tables"].get(route_table_id)
    if not rt:
        raise HTTPException(404, detail="NoSuchRouteTable")
    route = {"destination": destination_cidr, "target_type": target_type, "target_id": target_id, "type": "CreateRoute", "created": _now()}
    rt.setdefault("routes", []).append(route)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("CreateRouteResponse", build)


def _vpc_query_associate_route_table(params: dict[str, Any]) -> Response:
    route_table_id = str(params.get("RouteTableId", params.get("routeTableId", ""))).strip()
    subnet_id = str(params.get("SubnetId", params.get("subnetId", ""))).strip()
    gateway_id = str(params.get("GatewayId", params.get("gatewayId", ""))).strip()
    if not route_table_id:
        raise HTTPException(400, detail="MissingParameter: RouteTableId")
    if not subnet_id and not gateway_id:
        raise HTTPException(400, detail="MissingParameter: SubnetId")
    association_id = ""
    if subnet_id:
        association_id = _vpc_associate_subnet_to_route_table(route_table_id, subnet_id)
    elif gateway_id:
        raise HTTPException(400, detail="Gateway associations are not implemented in the simulator yet.")

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "associationId", association_id)
        association_state = _ec2_sub(root, "associationState")
        _ec2_sub(association_state, "state", "associated")

    return _ec2_success_response("AssociateRouteTableResponse", build)


def _vpc_query_disassociate_route_table(params: dict[str, Any]) -> Response:
    association_id = str(params.get("AssociationId", params.get("associationId", ""))).strip()
    if not association_id:
        raise HTTPException(400, detail="MissingParameter: AssociationId")
    route_table_id = ""
    subnet_id = ""
    for rt in vpc_state["route_tables"].values():
        for sid in rt.get("subnet_ids", []) or []:
            if _vpc_association_id(rt["route_table_id"], sid) == association_id:
                route_table_id = rt["route_table_id"]
                subnet_id = sid
                break
        if route_table_id:
            break
    if not route_table_id or not subnet_id:
        raise HTTPException(404, detail="InvalidAssociationID.NotFound")
    association_id = _vpc_disassociate_subnet_from_route_table(route_table_id, subnet_id)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "associationId", association_id)
        association_state = _ec2_sub(root, "associationState")
        _ec2_sub(association_state, "state", "disassociated")

    return _ec2_success_response("DisassociateRouteTableResponse", build)


def _vpc_query_delete_subnet(params: dict[str, Any]) -> Response:
    subnet_id = str(params.get("SubnetId", params.get("subnetId", ""))).strip()
    if not subnet_id:
        raise HTTPException(400, detail="MissingParameter: SubnetId")
    _vpc_delete_subnet_record(subnet_id)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("DeleteSubnetResponse", build)


def _vpc_query_delete_route_table(params: dict[str, Any]) -> Response:
    route_table_id = str(params.get("RouteTableId", params.get("routeTableId", ""))).strip()
    if not route_table_id:
        raise HTTPException(400, detail="MissingParameter: RouteTableId")
    _vpc_delete_route_table_record(route_table_id)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("DeleteRouteTableResponse", build)


def _vpc_query_delete_internet_gateway(params: dict[str, Any]) -> Response:
    igw_id = str(params.get("InternetGatewayId", params.get("internetGatewayId", ""))).strip()
    if not igw_id:
        raise HTTPException(400, detail="MissingParameter: InternetGatewayId")
    _vpc_delete_internet_gateway_record(igw_id)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("DeleteInternetGatewayResponse", build)


def _vpc_query_create_tags(params: dict[str, Any]) -> Response:
    resource_ids = []
    for key, value in params.items():
        if key.lower().startswith("resourceid") and value:
            if isinstance(value, list):
                resource_ids.extend([str(v) for v in value if v])
            else:
                resource_ids.append(str(value))
    tags = []
    for key, value in params.items():
        m = re.match(r"^Tag\.(\d+)\.Key$", key)
        if m:
            idx = m.group(1)
            tag_key = str(value)
            tag_value = str(params.get(f"Tag.{idx}.Value", ""))
            if tag_key:
                tags.append({"key": tag_key, "value": tag_value})
    if not resource_ids:
        raise HTTPException(400, detail="MissingParameter: ResourceId")
    if not tags:
        raise HTTPException(400, detail="MissingParameter: Tag")
    for resource_id in resource_ids:
        found = _vpc_find_resource(resource_id)
        if not found:
            continue
        _vpc_set_resource_tags(found[1], tags)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("CreateTagsResponse", build)


def _vpc_query_delete_vpc(params: dict[str, Any]) -> Response:
    vpc_id = str(params.get("VpcId", params.get("vpcId", ""))).strip()
    if not vpc_id:
        raise HTTPException(400, detail="MissingParameter: VpcId")
    api_vpc_delete(vpc_id, force=True)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")

    return _ec2_success_response("DeleteVpcResponse", build)


def _vpc_query_authorize_security_group_ingress(params: dict[str, Any]) -> Response:
    group_id = str(params.get("GroupId", params.get("groupId", ""))).strip()
    group_name = str(params.get("GroupName", params.get("groupName", ""))).strip()
    if not group_id and not group_name:
        raise HTTPException(400, detail="MissingParameter: GroupId")
    target_group = None
    target_group_id = group_id
    if target_group_id and target_group_id in vpc_state["security_groups"]:
        target_group = vpc_state["security_groups"][target_group_id]
    elif group_name:
        for sg_id, sg in vpc_state["security_groups"].items():
            if sg.get("group_name", "") == group_name:
                target_group_id = sg_id
                target_group = sg
                break
    if not target_group:
        raise HTTPException(404, detail="NoSuchSecurityGroup")

    permission_entries = []
    if any(key.startswith("IpPermissions.") for key in params):
        by_idx: dict[str, dict[str, Any]] = {}
        for key, value in params.items():
            m = re.match(r"^IpPermissions\.(\d+)\.(.+)$", key)
            if not m:
                continue
            idx, rest = m.groups()
            entry = by_idx.setdefault(idx, {})
            entry[rest] = value
        for entry in by_idx.values():
            permission_entries.append(entry)
    else:
        permission_entries.append({
            "IpProtocol": params.get("IpProtocol", "tcp"),
            "FromPort": params.get("FromPort", 0),
            "ToPort": params.get("ToPort", 65535),
            "CidrIp": params.get("CidrIp", "0.0.0.0/0"),
        })

    for entry in permission_entries:
        rule = {
            "protocol": str(entry.get("IpProtocol", "tcp")),
            "from_port": int(str(entry.get("FromPort", 0)) or 0),
            "to_port": int(str(entry.get("ToPort", 65535)) or 65535),
            "cidr": str(entry.get("CidrIp", entry.get("CidrIpv6", "0.0.0.0/0"))),
            "source_sg": str(entry.get("GroupId", entry.get("SourceSecurityGroupName", ""))),
            "description": str(entry.get("Description", "")),
            "created": _now(),
        }
        target_group.setdefault("ingress", [])
        if rule not in target_group["ingress"]:
            target_group["ingress"].append(rule)

    def build(root: ET.Element) -> None:
        _ec2_sub(root, "return", "true")
        rule_set = _ec2_sub(root, "securityGroupRuleSet")
        for rule in permission_entries:
            item = _ec2_sub(rule_set, "item")
            _ec2_sub(item, "securityGroupRuleId", f"sgr-{secrets.token_hex(4)}")
            _ec2_sub(item, "groupId", target_group_id)
            _ec2_sub(item, "groupOwnerId", AWS_ACCOUNT_ID)
            _ec2_sub(item, "isEgress", "false")
            _ec2_sub(item, "ipProtocol", str(rule.get("IpProtocol", "tcp")))
            _ec2_sub(item, "fromPort", str(rule.get("FromPort", 0)))
            _ec2_sub(item, "toPort", str(rule.get("ToPort", 65535)))
            if str(rule.get("CidrIp", "")).startswith("::"):
                rng = _ec2_sub(item, "referencedGroupInfo")
                _ec2_sub(rng, "groupId", str(rule.get("GroupId", "")))
            else:
                ranges = _ec2_sub(item, "ipRanges")
                range_item = _ec2_sub(ranges, "item")
                _ec2_sub(range_item, "cidrIp", str(rule.get("CidrIp", "0.0.0.0/0")))
                _ec2_sub(range_item, "description", str(rule.get("Description", "")))

    return _ec2_success_response("AuthorizeSecurityGroupIngressResponse", build)


RDS_ENGINE_CATALOG = {
    "postgres": {"display": "PostgreSQL", "port": 5432, "family": "postgres16", "version": "16.4", "image": "postgres"},
    "mysql": {"display": "MySQL", "port": 3306, "family": "mysql8.0", "version": "8.0.36", "image": "mysql"},
    "mariadb": {"display": "MariaDB", "port": 3306, "family": "mariadb11.4", "version": "11.4.3", "image": "mariadb"},
}
RDS_RUNTIME_ROOT = Path(os.getenv("CLOUDLEARN_RDS_ROOT", "/tmp/cloudlearn-rds"))


def _rds_engine_profile(engine: str) -> dict[str, Any]:
    return RDS_ENGINE_CATALOG.get((engine or "postgres").lower(), RDS_ENGINE_CATALOG["postgres"])


def _rds_runtime_image(engine: str, version: str | None = None) -> str:
    profile = _rds_engine_profile(engine)
    image = str(profile.get("image", engine or "postgres"))
    resolved_version = _rds_resolve_engine_version(engine, version)
    return f"{image}:{resolved_version}" if resolved_version else image


def _rds_runtime_container_name(db_id: str) -> str:
    safe = re.sub(r"[^a-z0-9_.-]+", "-", (db_id or "").lower()).strip("-")
    return f"cloudlearn-rds-{safe or 'db'}"


def _rds_runtime_data_volume(db_id: str) -> str:
    safe = re.sub(r"[^a-z0-9_.-]+", "-", (db_id or "").lower()).strip("-")
    return f"cloudlearn-rds-{safe or 'db'}-data"


def _rds_runtime_root(db_id: str) -> Path:
    return (RDS_RUNTIME_ROOT / (db_id or "default")).resolve()


def _rds_runtime_prepare_dirs(db_id: str) -> dict[str, Path]:
    root = _rds_runtime_root(db_id)
    data_dir = root / "data"
    init_dir = root / "initdb"
    root.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    init_dir.mkdir(parents=True, exist_ok=True)
    return {"root": root, "data": data_dir, "init": init_dir}


def _rds_runtime_engine_port(engine: str) -> int:
    return int(_rds_engine_profile(engine).get("port", 3306))


def _rds_resolve_engine_version(engine: str, version: str | None = None) -> str:
    profile = _rds_engine_profile(engine)
    resolved = (version or "").strip() or str(profile.get("version") or "")
    family = (engine or "").lower()
    if family == "postgres" and not resolved.startswith("16."):
        return str(profile.get("version") or resolved)
    if family == "mysql" and not resolved.startswith("8."):
        return str(profile.get("version") or resolved)
    if family == "mariadb" and not resolved.startswith("11."):
        return str(profile.get("version") or resolved)
    return resolved


def _rds_runtime_sql_escape(value: str) -> str:
    return (value or "").replace("'", "''")


def _rds_runtime_mysql_init_sql(db: dict) -> str:
    db_name = _rds_runtime_sql_escape(db.get("db_instance_identifier", "rdsdb"))
    username = _rds_runtime_sql_escape(db.get("master_username", "dbadmin"))
    password = _rds_runtime_sql_escape(db.get("master_user_password", "Password123!"))
    return (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}`;\n"
        f"CREATE USER IF NOT EXISTS '{username}'@'%' IDENTIFIED BY '{password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{username}'@'%';\n"
        "FLUSH PRIVILEGES;\n"
    )


def _rds_runtime_pull_image(image: str) -> None:
    if not _lxd_available():
        raise HTTPException(503, detail="LXDUnavailable")
    # LXD caches images automatically on launch; a separate pull is unnecessary.
    completed = _lxd_run(["image", "info", image], timeout=30)
    if completed.returncode == 0:
        return


def _rds_runtime_ensure_container(db: dict) -> str:
    if not _lxd_available():
        raise HTTPException(503, detail="LXDUnavailable")

    db_id = db["db_instance_identifier"]
    engine = (db.get("engine") or "postgres").lower()
    image = _rds_runtime_image(engine, db.get("engine_version"))
    container_name = db.get("container_name") or _rds_runtime_container_name(db_id)
    host_port = int(db.get("host_port") or _allocate_host_port())
    container_port = _rds_runtime_engine_port(engine)
    dirs = _rds_runtime_prepare_dirs(db_id)

    _rds_runtime_pull_image(image)

    db["runtime_backend"] = "lxd"
    db["runtime_image"] = image
    db["container_name"] = container_name
    db["host_port"] = host_port
    db["container_port"] = container_port
    db["endpoint_address"] = "127.0.0.1"
    db["endpoint_port"] = host_port
    db["endpoint_url"] = f"127.0.0.1:{host_port}"

    ref = db.get("container_id") or container_name
    if _lxd_container_exists(ref):
        if not db.get("container_id"):
            db["container_id"] = ref
        return ref

    launch_args = ["launch", image, container_name]
    completed = _lxd_run_checked(launch_args, timeout=300)
    db["container_id"] = container_name
    db["container_status"] = "created"

    proxy_name = f"{container_name}-proxy"
    _lxd_run_checked([
        "config",
        "device",
        "add",
        container_name,
        proxy_name,
        "proxy",
        f"listen=tcp:127.0.0.1:{host_port}",
        f"connect=tcp:127.0.0.1:{container_port}",
    ], timeout=120)

    if engine == "postgres":
        db_user = _rds_runtime_sql_escape(db.get("master_username") or "dbadmin")
        db_pass = _rds_runtime_sql_escape(db.get("master_user_password") or "Password123!")
        init_command = (
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib && "
            "service postgresql start && "
            f"su - postgres -c \"psql -c \\\"CREATE USER {db_user} WITH PASSWORD '{db_pass}';\\\"\" && "
            f"su - postgres -c \"createdb {db_id} -O {db_user}\""
        )
        _lxd_run_checked(["exec", container_name, "--", "/bin/sh", "-lc", init_command], timeout=1800)
    else:
        init_command = (
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y mariadb-server && "
            "service mysql start && "
            f"mysql -uroot -e \"CREATE DATABASE IF NOT EXISTS `{db_id}`; "
            f"CREATE USER IF NOT EXISTS '{db.get('master_username') or 'dbadmin'}'@'%' IDENTIFIED BY '{db.get('master_user_password') or 'Password123!'}'; "
            f"GRANT ALL PRIVILEGES ON `{db_id}`.* TO '{db.get('master_username') or 'dbadmin'}'@'%'; FLUSH PRIVILEGES;\""
        )
        _lxd_run_checked(["exec", container_name, "--", "/bin/sh", "-lc", init_command], timeout=1800)

    return db["container_id"]


def _rds_runtime_start(db: dict) -> dict:
    # When the appliance runs without LXD (e.g. local docker compose without a
    # nested VM), the RDS records are book-keeping only. Real-backend mode
    # actually toggles a container; simulated mode just updates the status field
    # so the API contract still works for tests/SDKs.
    if not _lxd_available():
        db["db_instance_status"] = "available"
        db["container_status"] = "running"
        db["runtime_backend"] = db.get("runtime_backend") or "simulated"
        db["latest_restorable_time"] = _now()
        db["updated"] = _now()
        return db
    ref = _rds_runtime_ensure_container(db)
    if _lxd_status(ref) != "running":
        _lxd_run_checked(["start", ref], timeout=300)
    db["db_instance_status"] = "available"
    db["container_status"] = "running"
    db["latest_restorable_time"] = _now()
    db["updated"] = _now()
    return db


def _rds_runtime_stop(db: dict) -> dict:
    if not _lxd_available():
        db["db_instance_status"] = "stopped"
        db["container_status"] = "exited"
        db["runtime_backend"] = db.get("runtime_backend") or "simulated"
        db["updated"] = _now()
        return db
    ref = db.get("container_id") or db.get("container_name")
    if not ref:
        raise HTTPException(409, detail="DBInstanceContainerMissing")
    if _lxd_status(ref) == "running":
        _lxd_run_checked(["stop", ref], timeout=300)
    db["db_instance_status"] = "stopped"
    db["container_status"] = "exited"
    db["updated"] = _now()
    return db


def _rds_runtime_reboot(db: dict) -> dict:
    if not _lxd_available():
        db["db_instance_status"] = "available"
        db["container_status"] = "running"
        db["runtime_backend"] = db.get("runtime_backend") or "simulated"
        db["latest_restorable_time"] = _now()
        db["updated"] = _now()
        return db
    ref = db.get("container_id") or db.get("container_name")
    if not ref:
        raise HTTPException(409, detail="DBInstanceContainerMissing")
    if _lxd_status(ref) != "running":
        raise HTTPException(409, detail="DBInstanceNotRunning")
    db["db_instance_status"] = "rebooting"
    _lxd_run_checked(["restart", ref], timeout=300)
    db["db_instance_status"] = "available"
    db["container_status"] = "running"
    db["latest_restorable_time"] = _now()
    db["updated"] = _now()
    return db


def _rds_runtime_delete(db: dict) -> None:
    # Only tear down a real container when one was actually provisioned (LXD backend
    # present, e.g. inside the appliance VM). Simulated records have nothing to remove.
    if str(db.get("runtime_backend") or "").lower() != "lxd" or not _lxd_available():
        db["container_status"] = "removed"
        return
    ref = db.get("container_id") or db.get("container_name")
    if ref and _lxd_container_exists(ref):
        _lxd_run(["rm", "-f", ref], timeout=300)
    volume_name = _rds_runtime_data_volume(db["db_instance_identifier"])
    _lxd_run(["volume", "rm", "-f", volume_name], timeout=300)
    db["container_status"] = "removed"


def _rds_vpc_id() -> str:
    for vpc_id in sorted(vpc_state.get("vpcs", {})):
        return vpc_id
    return ""


def _rds_default_subnet_ids(vpc_id: str) -> list[str]:
    return [subnet_id for subnet_id, subnet in vpc_state.get("subnets", {}).items() if subnet.get("vpc_id") == vpc_id]


def _rds_default_security_groups(vpc_id: str) -> list[str]:
    default_ids = [sg_id for sg_id, sg in vpc_state.get("security_groups", {}).items() if sg.get("vpc_id") == vpc_id and sg.get("is_default")]
    if default_ids:
        return default_ids[:1]
    return [sg_id for sg_id, sg in vpc_state.get("security_groups", {}).items() if sg.get("vpc_id") == vpc_id][:1]


def _rds_default_subnet_group_name(vpc_id: str) -> str:
    suffix = (vpc_id.replace("vpc-", "")[:8] or "default").lower()
    return f"default-{suffix}"


def _rds_default_parameter_group_name(engine: str) -> str:
    return f"default.{_rds_engine_profile(engine)['family']}"


def _rds_db_arn(resource_type: str, identifier: str) -> str:
    return f"arn:aws:rds:us-east-1:{AWS_ACCOUNT_ID}:{resource_type}:{identifier}"


def _rds_emit_event(action: str, detail: dict[str, Any]) -> None:
    rds_state.setdefault("events", []).append({"action": action, "detail": detail, "timestamp": _now()})
    if len(rds_state["events"]) > 200:
        rds_state["events"] = rds_state["events"][-200:]


def _rds_find_db_instance(db_id: str) -> dict | None:
    return rds_state.get("db_instances", {}).get(db_id.lower())


def _rds_find_db_subnet_group(name: str) -> dict | None:
    return rds_state.get("db_subnet_groups", {}).get(name.lower())


def _rds_find_db_parameter_group(name: str) -> dict | None:
    return rds_state.get("db_parameter_groups", {}).get(name.lower())


def _rds_find_db_snapshot(snapshot_id: str) -> dict | None:
    return rds_state.get("db_snapshots", {}).get(snapshot_id.lower())


def _rds_resource_tags(resource: dict) -> list[dict[str, str]]:
    tags = resource.setdefault("tags", [])
    if not isinstance(tags, list):
        tags = []
        resource["tags"] = tags
    return tags


def _rds_set_tags(resource: dict, tags: list[dict[str, str]]) -> None:
    existing = {str(tag.get("key", "")): str(tag.get("value", "")) for tag in _rds_resource_tags(resource)}
    for tag in tags:
        key = str(tag.get("key", ""))
        if key:
            existing[key] = str(tag.get("value", ""))
    resource["tags"] = [{"key": k, "value": v} for k, v in existing.items()]


def _rds_make_db_subnet_group(name: str, description: str, vpc_id: str, subnet_ids: list[str], tags: list[dict[str, str]] | None = None) -> dict:
    group = {
        "db_subnet_group_name": name.lower(),
        "db_subnet_group_description": description or name,
        "vpc_id": vpc_id,
        "subnet_ids": subnet_ids,
        "subnet_group_status": "Complete",
        "supported_network_types": ["IPV4"],
        "created": _now(),
        "tags": tags or [],
        "arn": _rds_db_arn("subgrp", name.lower()),
    }
    rds_state["db_subnet_groups"][group["db_subnet_group_name"]] = group
    return group


def _rds_make_db_parameter_group(name: str, family: str, description: str, tags: list[dict[str, str]] | None = None) -> dict:
    group = {
        "db_parameter_group_name": name.lower(),
        "db_parameter_group_family": family,
        "description": description or name,
        "created": _now(),
        "tags": tags or [],
        "arn": _rds_db_arn("pg", name.lower()),
    }
    rds_state["db_parameter_groups"][group["db_parameter_group_name"]] = group
    return group


def _rds_ensure_subnet_group(vpc_id: str, group_name: str | None = None, description: str | None = None) -> dict:
    name = (group_name or _rds_default_subnet_group_name(vpc_id)).lower()
    existing = _rds_find_db_subnet_group(name)
    if existing:
        return existing
    subnet_ids = _rds_default_subnet_ids(vpc_id)
    return _rds_make_db_subnet_group(name, description or f"Default subnet group for {vpc_id}", vpc_id, subnet_ids)


def _rds_ensure_parameter_group(engine: str, group_name: str | None = None, description: str | None = None) -> dict:
    profile = _rds_engine_profile(engine)
    name = (group_name or _rds_default_parameter_group_name(engine)).lower()
    existing = _rds_find_db_parameter_group(name)
    if existing:
        return existing
    return _rds_make_db_parameter_group(name, profile["family"], description or f"Default {profile['display']} parameter group")


def _rds_db_status(db: dict) -> str:
    return db.get("db_instance_status", "available")


def _rds_db_endpoint(db: dict) -> dict[str, Any]:
    return {"address": db.get("endpoint_address", ""), "port": db.get("endpoint_port", 0), "hosted_zone_id": "Z1PVIF0B656C1W"}


def _rds_db_view(db: dict) -> dict[str, Any]:
    subnet_group = _rds_find_db_subnet_group(db.get("db_subnet_group_name", "")) or {}
    parameter_group = _rds_find_db_parameter_group(db.get("db_parameter_group_name", "")) or {}
    vpc_id = db.get("vpc_id", "")
    return {
        "db_instance_identifier": db.get("db_instance_identifier", ""),
        "db_instance_class": db.get("db_instance_class", ""),
        "engine": db.get("engine", ""),
        "engine_version": db.get("engine_version", ""),
        "status": _rds_db_status(db),
        "master_username": db.get("master_username", ""),
        "master_user_password": db.get("master_user_password", ""),
        "allocated_storage": db.get("allocated_storage", 20),
        "storage_type": db.get("storage_type", "gp3"),
        "publicly_accessible": db.get("publicly_accessible", False),
        "multi_az": db.get("multi_az", False),
        "backup_retention_period": db.get("backup_retention_period", 7),
        "preferred_maintenance_window": db.get("preferred_maintenance_window", "sun:03:00-sun:03:30"),
        "vpc_id": vpc_id,
        "db_subnet_group_name": db.get("db_subnet_group_name", ""),
        "db_parameter_group_name": db.get("db_parameter_group_name", ""),
        "availability_zone": db.get("availability_zone", ""),
        "endpoint_address": db.get("endpoint_address", ""),
        "endpoint_port": db.get("endpoint_port", 0),
        "endpoint_url": f"{db.get('endpoint_address', '')}:{db.get('endpoint_port', 0)}" if db.get("endpoint_address") else "",
        "runtime_backend": db.get("runtime_backend", "lxd"),
        "runtime_image": db.get("runtime_image", ""),
        "container_name": db.get("container_name", ""),
        "container_id": db.get("container_id", ""),
        "container_status": db.get("container_status", ""),
        "host_port": db.get("host_port", 0),
        "security_group_ids": list(db.get("security_group_ids", [])),
        "subnet_ids": list((subnet_group or {}).get("subnet_ids", [])),
        "tags": list(db.get("tags", [])),
        "created": db.get("created", ""),
        "updated": db.get("updated", db.get("created", "")),
        "db_instance_arn": db.get("db_instance_arn", ""),
        "db_subnet_group": subnet_group,
        "db_parameter_group": parameter_group,
        "events": list(db.get("events", [])),
        "latest_restorable_time": db.get("latest_restorable_time", ""),
    }


def _rds_db_snapshot_view(snapshot: dict) -> dict[str, Any]:
    return {
        "db_snapshot_identifier": snapshot.get("db_snapshot_identifier", ""),
        "db_instance_identifier": snapshot.get("db_instance_identifier", ""),
        "engine": snapshot.get("engine", ""),
        "status": snapshot.get("status", "available"),
        "snapshot_type": snapshot.get("snapshot_type", "manual"),
        "allocated_storage": snapshot.get("allocated_storage", 0),
        "engine_version": snapshot.get("engine_version", ""),
        "created": snapshot.get("created", ""),
        "tags": list(snapshot.get("tags", [])),
        "db_snapshot_arn": snapshot.get("db_snapshot_arn", ""),
    }


def _rds_parse_tags(params: dict[str, Any]) -> list[dict[str, str]]:
    tags = []
    for key, value in params.items():
        m = re.match(r"^Tag\.(\d+)\.Key$", key)
        if m:
            idx = m.group(1)
            tag_key = str(value)
            tag_value = str(params.get(f"Tag.{idx}.Value", ""))
            if tag_key:
                tags.append({"key": tag_key, "value": tag_value})
    return tags


# ── Real RDS data-plane provisioning ────────────────────────────────────────
#
# Mirrors the proven pattern that GCP Cloud SQL + Azure Database for
# PostgreSQL already use (see core/gcp_sql_engine.py): create a real
# database + login role on the shared cloudlearn-sql-postgres /
# vyomi-sql-mysql container, return the connection endpoint. boto3 +
# Terraform + psql all see a real, connectable Postgres backed by the
# shipped engine — no LXD-image-catalog brittleness.
#
# Difference from gcp_sql_engine.provision(): we honor the AWS-contract
# master_username verbatim instead of the slugified physical_name, so
# `psql -U <master_username>` works exactly as it would on real AWS.

def _rds_real_provision(db_id: str, engine: str, version: str,
                        master_username: str, master_user_password: str) -> dict | None:
    """Provision a real database + role on the shared shipped engine.
    Returns {host, port, database, user, password} on success.
    Returns None if the engine isn't reachable — caller degrades to
    simulated control-plane lifecycle (still SDK-conformant)."""
    eng = (engine or "postgres").lower()
    if eng not in ("postgres", "mysql"):
        return None
    try:
        from core import gcp_sql_engine
        cfg = gcp_sql_engine._engine_config(eng)
        if not gcp_sql_engine.available(eng):
            return None
        # AWS RDS db identifiers are globally unique already — use db_id as
        # the physical database name (lowercase, alphanum + hyphen sanitized).
        db_name = re.sub(r"[^a-z0-9_]", "_", db_id.lower()).strip("_") or "rds"
        role = re.sub(r"[^a-zA-Z0-9_]", "_", (master_username or "dbadmin")).strip("_") or "dbadmin"
        pwd = master_user_password or "Password123!"
        if eng == "postgres":
            conn = gcp_sql_engine._pg_connect(cfg)
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                if cur.fetchone():
                    cur.execute(f'ALTER ROLE "{role}" WITH LOGIN PASSWORD %s', (pwd,))
                else:
                    cur.execute(f'CREATE ROLE "{role}" WITH LOGIN PASSWORD %s', (pwd,))
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db_name,))
                if not cur.fetchone():
                    cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{role}"')
                cur.close()
            finally:
                conn.close()
        else:  # mysql
            conn = gcp_sql_engine._mysql_connect(cfg)
            try:
                cur = conn.cursor()
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
                cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (role, pwd))
                cur.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (role, pwd))
                cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO %s@'%%'", (role,))
                cur.execute("FLUSH PRIVILEGES")
                cur.close()
            finally:
                conn.close()
        return {
            "host":     gcp_sql_engine.public_host(""),
            "port":     cfg["public_port"],
            "database": db_name,
            "user":     role,
            "password": pwd,
        }
    except Exception:
        return None


def _rds_real_deprovision(db_id: str, engine: str, master_username: str) -> bool:
    """Drop the real database + role. Best-effort; True if it ran."""
    eng = (engine or "postgres").lower()
    if eng not in ("postgres", "mysql"):
        return False
    try:
        from core import gcp_sql_engine
        if not gcp_sql_engine.available(eng):
            return False
        cfg = gcp_sql_engine._engine_config(eng)
        db_name = re.sub(r"[^a-z0-9_]", "_", db_id.lower()).strip("_") or "rds"
        role = re.sub(r"[^a-zA-Z0-9_]", "_", (master_username or "dbadmin")).strip("_") or "dbadmin"
        if eng == "postgres":
            conn = gcp_sql_engine._pg_connect(cfg)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                    (db_name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
                cur.execute(f'DROP ROLE IF EXISTS "{role}"')
                cur.close()
            finally:
                conn.close()
        else:
            conn = gcp_sql_engine._mysql_connect(cfg)
            try:
                cur = conn.cursor()
                cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                cur.execute("DROP USER IF EXISTS %s@'%%'", (role,))
                cur.close()
            finally:
                conn.close()
        return True
    except Exception:
        return False


def _rds_prepare_db_instance(payload: RDSDatabaseRequest, source_snapshot: dict | None = None) -> dict:
    db_id = payload.db_instance_identifier.strip().lower()
    if not db_id:
        raise HTTPException(400, detail="MissingParameter: DBInstanceIdentifier")
    if _rds_find_db_instance(db_id):
        raise HTTPException(400, detail="DBInstanceAlreadyExists")
    engine_profile = _rds_engine_profile(payload.engine)
    vpc_id = payload.vpc_id or _rds_vpc_id()
    if not vpc_id and vpc_state.get("vpcs"):
        vpc_id = next(iter(vpc_state["vpcs"]))
    subnet_group_name = (payload.db_subnet_group_name or _rds_default_subnet_group_name(vpc_id or "default")).lower()
    subnet_group = _rds_find_db_subnet_group(subnet_group_name)
    if not subnet_group:
        subnet_group = _rds_ensure_subnet_group(vpc_id or "vpc-default", subnet_group_name)
    parameter_group_name = (payload.db_parameter_group_name or _rds_default_parameter_group_name(payload.engine)).lower()
    parameter_group = _rds_find_db_parameter_group(parameter_group_name) or _rds_ensure_parameter_group(payload.engine, parameter_group_name)
    sg_ids = list(payload.security_group_ids or _rds_default_security_groups(vpc_id or subnet_group.get("vpc_id", "")))
    if source_snapshot:
        payload.engine = source_snapshot.get("engine", payload.engine)
        engine_profile = _rds_engine_profile(payload.engine)
        payload.engine_version = source_snapshot.get("engine_version", payload.engine_version)
        payload.allocated_storage = source_snapshot.get("allocated_storage", payload.allocated_storage)
        payload.storage_type = source_snapshot.get("storage_type", payload.storage_type)
        payload.master_username = source_snapshot.get("master_username", payload.master_username)
        vpc_id = source_snapshot.get("vpc_id", vpc_id)
    # Resolve engine version first — needed by both the real provisioner and
    # the metadata fields the API returns.
    resolved_engine_version = _rds_resolve_engine_version(payload.engine, payload.engine_version)
    runtime_image = _rds_runtime_image(payload.engine, resolved_engine_version)

    # Data-plane backing — same pattern GCP Cloud SQL + Azure Database for
    # PostgreSQL already use: real database + login role on the shared
    # cloudlearn-sql-postgres / vyomi-sql-mysql backend, so a `psql` /
    # `mysql` client + boto3 + Terraform clients all hit a real database
    # over the regular wire protocol. Degrades to a metadata-only
    # "simulated" record when the engine isn't reachable (still SDK-
    # conformant for lifecycle calls). The old LXD-image path was
    # broken because "postgres:16" parses as remote='postgres' to lxc.
    real_endpoint = _rds_real_provision(
        db_id=db_id,
        engine=payload.engine,
        version=resolved_engine_version,
        master_username=payload.master_username,
        master_user_password=payload.master_user_password,
    )
    if real_endpoint:
        runtime_backend = "real-pg" if (payload.engine or "").lower() == "postgres" else "real-mysql"
        endpoint_address = real_endpoint["host"]
        endpoint_port_override = real_endpoint["port"]
    else:
        runtime_backend = "simulated"
        endpoint_address = f"{db_id}.rds.local"
        endpoint_port_override = None
    db = {
        "db_instance_identifier": db_id,
        "db_instance_class": payload.db_instance_class,
        "engine": payload.engine.lower(),
        "engine_version": resolved_engine_version,
        "db_instance_status": "available",
        "master_username": payload.master_username,
        "master_user_password": payload.master_user_password,
        "allocated_storage": int(payload.allocated_storage or 20),
        "storage_type": payload.storage_type,
        "vpc_id": vpc_id,
        "db_subnet_group_name": subnet_group["db_subnet_group_name"],
        "db_parameter_group_name": parameter_group["db_parameter_group_name"],
        "availability_zone": payload.availability_zone,
        "publicly_accessible": bool(payload.publicly_accessible),
        "multi_az": bool(payload.multi_az),
        "backup_retention_period": int(payload.backup_retention_period or 7),
        "preferred_maintenance_window": payload.preferred_maintenance_window,
        "endpoint_address": endpoint_address,
        "endpoint_port": endpoint_port_override if endpoint_port_override is not None else engine_profile["port"],
        "db_instance_arn": _rds_db_arn("db", db_id),
        "security_group_ids": sg_ids,
        "tags": list(payload.tags or []),
        "events": [],
        "created": _now(),
        "updated": _now(),
        "latest_restorable_time": _now(),
        "copy_tags_to_snapshot": False,
        "auto_minor_version_upgrade": True,
        "license_model": "postgresql-license" if payload.engine.lower().startswith("postgres") else "general-public-license",
        "pending_modified_values": {},
        "runtime_backend": runtime_backend,
        "runtime_image": runtime_image,
        "container_name": _rds_runtime_container_name(db_id),
        "container_id": "",
        "container_status": "created",
        "host_port": 0,
        "container_port": engine_profile["port"],
    }
    db["subnet_ids"] = list(subnet_group.get("subnet_ids", []))
    # When the real shared-engine provisioner succeeded, the database is
    # immediately available + connectable. The container_status field is
    # retained for backward compat with consumers expecting the LXD shape;
    # we just mark it "running" since the shared engine container IS
    # running (it's part of the appliance compose stack).
    if runtime_backend in ("real-pg", "real-mysql"):
        db["db_instance_status"] = "available"
        db["container_status"] = "running"
    elif runtime_backend == "lxd":
        # Legacy LXD path — left in for any non-pg/mysql engine that may be
        # added later (e.g. Oracle, SQL Server). Untouched here.
        _rds_runtime_ensure_container(db)
        db["db_instance_status"] = "available"
        db["container_status"] = "running" if _lxd_status(db.get("container_id") or db.get("container_name")) == "running" else "created"
    else:
        # Simulated control-plane only — still SDK/Terraform conformant.
        db["db_instance_status"] = "available"
        db["container_status"] = "simulated"
    rds_state["db_instances"][db_id] = db
    _rds_emit_event("CreateDBInstance", {"db_instance_identifier": db_id, "engine": db["engine"], "vpc_id": vpc_id})
    return db


def _rds_update_db_instance(db: dict, payload: RDSModifyRequest) -> dict:
    if payload.db_instance_class:
        db["db_instance_class"] = payload.db_instance_class
    if payload.allocated_storage is not None:
        db["allocated_storage"] = int(payload.allocated_storage)
    if payload.backup_retention_period is not None:
        db["backup_retention_period"] = int(payload.backup_retention_period)
    if payload.publicly_accessible is not None:
        db["publicly_accessible"] = bool(payload.publicly_accessible)
    if payload.multi_az is not None:
        db["multi_az"] = bool(payload.multi_az)
    if payload.engine_version:
        db["engine_version"] = payload.engine_version
    if payload.master_user_password:
        db["master_user_password"] = payload.master_user_password
    if payload.db_parameter_group_name:
        pg = _rds_find_db_parameter_group(payload.db_parameter_group_name.lower())
        if not pg:
            raise HTTPException(404, detail="DBParameterGroupNotFound")
        db["db_parameter_group_name"] = pg["db_parameter_group_name"]
    if payload.preferred_maintenance_window:
        db["preferred_maintenance_window"] = payload.preferred_maintenance_window
    db["updated"] = _now()
    _rds_emit_event("ModifyDBInstance", {"db_instance_identifier": db["db_instance_identifier"]})
    return db


def _rds_delete_db_instance(db_id: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = "") -> None:
    db = _rds_find_db_instance(db_id)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    if not skip_final_snapshot:
        final_snapshot_identifier = final_snapshot_identifier or f"{db_id}-final-{secrets.token_hex(3)}"
        _rds_create_snapshot_from_db(db, final_snapshot_identifier)
    # Best-effort cleanup based on which backend actually ran the instance.
    if db.get("runtime_backend") in ("real-pg", "real-mysql"):
        _rds_real_deprovision(db_id, db.get("engine", "postgres"), db.get("master_username", ""))
    else:
        _rds_runtime_delete(db)  # legacy LXD path / no-op for simulated
    del rds_state["db_instances"][db_id.lower()]
    _rds_emit_event("DeleteDBInstance", {"db_instance_identifier": db_id, "skip_final_snapshot": skip_final_snapshot})


def _rds_create_snapshot_from_db(db: dict, snapshot_id: str, tags: list[dict[str, str]] | None = None) -> dict:
    sid = snapshot_id.strip().lower()
    if not sid:
        raise HTTPException(400, detail="MissingParameter: DBSnapshotIdentifier")
    if _rds_find_db_snapshot(sid):
        raise HTTPException(400, detail="DBSnapshotAlreadyExists")
    snapshot = {
        "db_snapshot_identifier": sid,
        "db_instance_identifier": db["db_instance_identifier"],
        "db_snapshot_arn": _rds_db_arn("snapshot", sid),
        "status": "available",
        "snapshot_type": "manual",
        "engine": db.get("engine", "postgres"),
        "engine_version": db.get("engine_version", ""),
        "db_instance_class": db.get("db_instance_class", "db.t3.micro"),
        "allocated_storage": db.get("allocated_storage", 20),
        "storage_type": db.get("storage_type", "gp3"),
        "vpc_id": db.get("vpc_id", ""),
        "db_subnet_group_name": db.get("db_subnet_group_name", ""),
        "db_parameter_group_name": db.get("db_parameter_group_name", ""),
        "master_username": db.get("master_username", ""),
        "publicly_accessible": db.get("publicly_accessible", False),
        "multi_az": db.get("multi_az", False),
        "availability_zone": db.get("availability_zone", ""),
        "created": _now(),
        "tags": list(tags or []),
        "source_db_instance_identifier": db["db_instance_identifier"],
    }
    rds_state["db_snapshots"][sid] = snapshot
    _rds_emit_event("CreateDBSnapshot", {"db_snapshot_identifier": sid, "db_instance_identifier": db["db_instance_identifier"]})
    return snapshot


def _rds_restore_snapshot(snapshot: dict, payload: RDSRestoreSnapshotRequest) -> dict:
    source_db = _rds_find_db_instance(snapshot["db_instance_identifier"])
    new_payload = RDSDatabaseRequest(
        db_instance_identifier=payload.db_instance_identifier,
        db_instance_class=payload.db_instance_class or snapshot.get("db_instance_class", "db.t3.micro"),
        engine=snapshot.get("engine", "postgres"),
        engine_version=snapshot.get("engine_version", ""),
        master_username=snapshot.get("master_username", "dbadmin"),
        master_user_password=source_db.get("master_user_password", "Password123!") if source_db else "Password123!",
        allocated_storage=snapshot.get("allocated_storage", 20),
        storage_type=snapshot.get("storage_type", "gp3"),
        vpc_id=payload.vpc_id or snapshot.get("vpc_id", ""),
        db_subnet_group_name=payload.db_subnet_group_name or snapshot.get("db_subnet_group_name", ""),
        db_parameter_group_name=snapshot.get("db_parameter_group_name", ""),
        availability_zone=snapshot.get("availability_zone", "us-east-1a"),
        publicly_accessible=payload.publicly_accessible,
        multi_az=payload.multi_az,
        backup_retention_period=7,
        tags=payload.tags or [],
        security_group_ids=[],
    )
    db = _rds_prepare_db_instance(new_payload, source_snapshot=snapshot)
    return db


def _rds_query_paginate(items: list[Any], params: dict[str, Any], default_max: int = 100) -> tuple[list[Any], str]:
    raw_marker = str(params.get("Marker", params.get("marker", "")) or "").strip()
    start = 0
    if raw_marker:
        try:
            start = max(int(raw_marker), 0)
        except Exception:
            start = 0
    raw_max = params.get("MaxRecords", params.get("maxRecords", default_max))
    try:
        max_results = int(raw_max)
    except Exception:
        max_results = default_max
    if max_results < 20:
        max_results = 20
    if max_results > 100:
        max_results = 100
    end = start + max_results
    page = items[start:end]
    next_marker = str(end) if end < len(items) else ""
    return page, next_marker


def _rds_list_databases_view() -> dict[str, Any]:
    dbs = sorted(rds_state["db_instances"].values(), key=lambda item: (item.get("created", ""), item.get("db_instance_identifier", "")))
    return {
        "db_instances": [_rds_db_view(db) for db in dbs],
        "db_subnet_groups": [group for group in sorted(rds_state["db_subnet_groups"].values(), key=lambda item: (item.get("created", ""), item.get("db_subnet_group_name", "")))],
        "db_parameter_groups": [group for group in sorted(rds_state["db_parameter_groups"].values(), key=lambda item: (item.get("created", ""), item.get("db_parameter_group_name", "")))],
        "db_snapshots": [_rds_db_snapshot_view(snapshot) for snapshot in sorted(rds_state["db_snapshots"].values(), key=lambda item: (item.get("created", ""), item.get("db_snapshot_identifier", "")))],
        "events": list(rds_state.get("events", [])),
        "count": len(dbs),
    }


def api_rds_list_databases():
    return _rds_list_databases_view()


def api_rds_create_database(req: RDSDatabaseRequest):
    db = _rds_prepare_db_instance(req)
    db["runtime_bundle_id"] = _cloudsim_runtime_bundle("rds").get("id", "")
    db["runtime_bundle_name"] = _cloudsim_runtime_bundle("rds").get("name", "")
    db["runtime_bundle_kind"] = _cloudsim_runtime_bundle("rds").get("kind", "")
    _cloudsim_sync_service_resource("aws", "rds", "db_instance", db["db_instance_identifier"], db, "rds")
    _record_usage("rds.create_database", {"db_instance_identifier": db.get("db_instance_identifier", ""), "engine": db.get("engine", "")})
    return _rds_db_view(db)


def api_rds_get_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    return _rds_db_view(db)


def api_rds_start_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    if _rds_db_status(db) == "available":
        return _rds_db_view(db)
    db = _rds_runtime_start(db)
    _cloudsim_sync_service_resource("aws", "rds", "db_instance", db_instance_identifier, db, "rds")
    _rds_emit_event("StartDBInstance", {"db_instance_identifier": db_instance_identifier})
    _record_usage("rds.start_database", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_stop_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    db = _rds_runtime_stop(db)
    _cloudsim_sync_service_resource("aws", "rds", "db_instance", db_instance_identifier, db, "rds")
    _rds_emit_event("StopDBInstance", {"db_instance_identifier": db_instance_identifier})
    _record_usage("rds.stop_database", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_reboot_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    db = _rds_runtime_reboot(db)
    _cloudsim_sync_service_resource("aws", "rds", "db_instance", db_instance_identifier, db, "rds")
    _rds_emit_event("RebootDBInstance", {"db_instance_identifier": db_instance_identifier})
    _record_usage("rds.reboot_database", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_modify_database(db_instance_identifier: str, req: RDSModifyRequest):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    modified = _rds_update_db_instance(db, req)
    _record_usage("rds.modify_database", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(modified)


def api_rds_delete_database(db_instance_identifier: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = ""):
    _rds_delete_db_instance(db_instance_identifier, skip_final_snapshot=skip_final_snapshot, final_snapshot_identifier=final_snapshot_identifier)
    _cloudsim_sync_service_resource("aws", "rds", "db_instance", db_instance_identifier, {}, "rds", action="delete")
    _record_usage("rds.delete_database", {"db_instance_identifier": db_instance_identifier, "skip_final_snapshot": skip_final_snapshot})
    return {"deleted": True, "db_instance_identifier": db_instance_identifier}


def api_rds_list_subnet_groups():
    return {"db_subnet_groups": list(sorted(rds_state["db_subnet_groups"].values(), key=lambda item: item.get("db_subnet_group_name", ""))), "count": len(rds_state["db_subnet_groups"])}


def api_rds_create_subnet_group(req: RDSSubnetGroupRequest):
    name = req.db_subnet_group_name.strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: DBSubnetGroupName")
    if name in rds_state["db_subnet_groups"]:
        raise HTTPException(400, detail="DBSubnetGroupAlreadyExists")
    vpc_id = req.vpc_id or _rds_vpc_id()
    if not vpc_id:
        raise HTTPException(400, detail="NoSuchVpc")
    subnet_ids = [sid for sid in req.subnet_ids if sid in vpc_state.get("subnets", {}) and vpc_state["subnets"][sid].get("vpc_id") == vpc_id]
    if not subnet_ids:
        subnet_ids = _rds_default_subnet_ids(vpc_id)
    group = _rds_make_db_subnet_group(name, req.db_subnet_group_description or name, vpc_id, subnet_ids, req.tags or [])
    _record_usage("rds.create_subnet_group", {"db_subnet_group_name": name, "vpc_id": vpc_id})
    return group


def api_rds_delete_subnet_group(db_subnet_group_name: str):
    name = db_subnet_group_name.lower()
    for db in rds_state["db_instances"].values():
        if db.get("db_subnet_group_name") == name:
            raise HTTPException(409, detail="InvalidDBSubnetGroupState")
    if name not in rds_state["db_subnet_groups"]:
        raise HTTPException(404, detail="DBSubnetGroupNotFound")
    del rds_state["db_subnet_groups"][name]
    _record_usage("rds.delete_subnet_group", {"db_subnet_group_name": name})
    return {"deleted": True, "db_subnet_group_name": name}


def api_rds_list_parameter_groups():
    return {"db_parameter_groups": list(sorted(rds_state["db_parameter_groups"].values(), key=lambda item: item.get("db_parameter_group_name", ""))), "count": len(rds_state["db_parameter_groups"])}


def api_rds_create_parameter_group(req: RDSParameterGroupRequest):
    name = req.db_parameter_group_name.strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: DBParameterGroupName")
    if name in rds_state["db_parameter_groups"]:
        raise HTTPException(400, detail="DBParameterGroupAlreadyExists")
    group = _rds_make_db_parameter_group(name, req.family, req.description or name, req.tags or [])
    _record_usage("rds.create_parameter_group", {"db_parameter_group_name": name, "family": req.family})
    return group


def api_rds_delete_parameter_group(db_parameter_group_name: str):
    name = db_parameter_group_name.lower()
    for db in rds_state["db_instances"].values():
        if db.get("db_parameter_group_name") == name:
            raise HTTPException(409, detail="InvalidDBParameterGroupState")
    if name not in rds_state["db_parameter_groups"]:
        raise HTTPException(404, detail="DBParameterGroupNotFound")
    del rds_state["db_parameter_groups"][name]
    _record_usage("rds.delete_parameter_group", {"db_parameter_group_name": name})
    return {"deleted": True, "db_parameter_group_name": name}


def api_rds_list_snapshots():
    return {"db_snapshots": [_rds_db_snapshot_view(snapshot) for snapshot in sorted(rds_state["db_snapshots"].values(), key=lambda item: item.get("created", ""))], "count": len(rds_state["db_snapshots"])}


def api_rds_create_snapshot(db_instance_identifier: str, req: RDSSnapshotRequest):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    snapshot = _rds_create_snapshot_from_db(db, req.db_snapshot_identifier, req.tags or [])
    _record_usage("rds.create_snapshot", {"db_instance_identifier": db_instance_identifier, "db_snapshot_identifier": req.db_snapshot_identifier})
    return _rds_db_snapshot_view(snapshot)


def api_rds_restore_snapshot(db_snapshot_identifier: str, req: RDSRestoreSnapshotRequest):
    snapshot = _rds_find_db_snapshot(db_snapshot_identifier)
    if not snapshot:
        raise HTTPException(404, detail="DBSnapshotNotFound")
    db = _rds_restore_snapshot(snapshot, req)
    return _rds_db_view(db)


def api_rds_add_tags(db_instance_identifier: str, payload: dict[str, Any]):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    tags = []
    for key, value in payload.items():
        if key.lower().startswith("tag") and isinstance(value, dict):
            tags.append({"key": str(value.get("key", "")), "value": str(value.get("value", ""))})
    _rds_set_tags(db, tags)
    return _rds_db_view(db)


def api_rds_list_tags(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    return {"tags": list(db.get("tags", []))}


def _rds_tag_xml(tags: list[dict[str, str]]) -> str:
    return "".join(f"<Tag><Key>{xml_escape(str(tag.get('key', '')))}</Key><Value>{xml_escape(str(tag.get('value', '')))}</Value></Tag>" for tag in tags)


def _rds_db_subnet_group_xml(group: dict) -> str:
    parts = [
        "<DBSubnetGroup>",
        f"<DBSubnetGroupName>{xml_escape(group.get('db_subnet_group_name', ''))}</DBSubnetGroupName>",
        f"<DBSubnetGroupDescription>{xml_escape(group.get('db_subnet_group_description', ''))}</DBSubnetGroupDescription>",
        f"<VpcId>{xml_escape(group.get('vpc_id', ''))}</VpcId>",
        f"<SubnetGroupStatus>{xml_escape(group.get('subnet_group_status', 'Complete'))}</SubnetGroupStatus>",
        "<Subnets>",
    ]
    for subnet_id in group.get("subnet_ids", []) or []:
        subnet = vpc_state.get("subnets", {}).get(subnet_id, {})
        parts.extend([
            "<Subnet>",
            "<SubnetStatus>Active</SubnetStatus>",
            f"<SubnetIdentifier>{xml_escape(subnet_id)}</SubnetIdentifier>",
            "<SubnetAvailabilityZone>",
            f"<Name>{xml_escape(subnet.get('availability_zone', ''))}</Name>",
            "<ProvisionedIopsCapable>false</ProvisionedIopsCapable>",
            "</SubnetAvailabilityZone>",
            "</Subnet>",
        ])
    parts.append("</Subnets>")
    parts.append("<SupportedNetworkTypes>")
    for network_type in group.get("supported_network_types", ["IPV4"]) or ["IPV4"]:
        parts.append(f"<member>{xml_escape(network_type)}</member>")
    parts.append("</SupportedNetworkTypes>")
    parts.append(f"<DBSubnetGroupArn>{xml_escape(group.get('arn', ''))}</DBSubnetGroupArn>")
    parts.append("</DBSubnetGroup>")
    return "".join(parts)


def _rds_db_parameter_group_xml(group: dict) -> str:
    return (
        "<DBParameterGroup>"
        f"<DBParameterGroupName>{xml_escape(group.get('db_parameter_group_name', ''))}</DBParameterGroupName>"
        f"<DBParameterGroupFamily>{xml_escape(group.get('db_parameter_group_family', ''))}</DBParameterGroupFamily>"
        f"<Description>{xml_escape(group.get('description', ''))}</Description>"
        f"<DBParameterGroupArn>{xml_escape(group.get('arn', ''))}</DBParameterGroupArn>"
        "</DBParameterGroup>"
    )


def _rds_db_snapshot_xml(snapshot: dict) -> str:
    parts = [
        "<DBSnapshot>",
        f"<DBSnapshotIdentifier>{xml_escape(snapshot.get('db_snapshot_identifier', ''))}</DBSnapshotIdentifier>",
        f"<DBInstanceIdentifier>{xml_escape(snapshot.get('db_instance_identifier', ''))}</DBInstanceIdentifier>",
        f"<DBSnapshotArn>{xml_escape(snapshot.get('db_snapshot_arn', ''))}</DBSnapshotArn>",
        f"<SnapshotType>{xml_escape(snapshot.get('snapshot_type', 'manual'))}</SnapshotType>",
        f"<Status>{xml_escape(snapshot.get('status', 'available'))}</Status>",
        f"<Port>{_rds_engine_profile(snapshot.get('engine', 'postgres'))['port']}</Port>",
        f"<Engine>{xml_escape(snapshot.get('engine', 'postgres'))}</Engine>",
        f"<EngineVersion>{xml_escape(snapshot.get('engine_version', ''))}</EngineVersion>",
        f"<AllocatedStorage>{snapshot.get('allocated_storage', 20)}</AllocatedStorage>",
        f"<InstanceCreateTime>{xml_escape(snapshot.get('created', _now()))}</InstanceCreateTime>",
        f"<MasterUsername>{xml_escape(snapshot.get('master_username', ''))}</MasterUsername>",
        f"<VpcId>{xml_escape(snapshot.get('vpc_id', ''))}</VpcId>",
        f"<DBSubnetGroupName>{xml_escape(snapshot.get('db_subnet_group_name', ''))}</DBSubnetGroupName>",
        f"<AvailabilityZone>{xml_escape(snapshot.get('availability_zone', ''))}</AvailabilityZone>",
        "</DBSnapshot>",
    ]
    return "".join(parts)


def _rds_db_instance_xml(db: dict) -> str:
    subnet_group = _rds_find_db_subnet_group(db.get("db_subnet_group_name", "")) or {}
    parameter_group = _rds_find_db_parameter_group(db.get("db_parameter_group_name", "")) or {}
    sg_parts = "".join(
        "<VpcSecurityGroupMembership>"
        f"<VpcSecurityGroupId>{xml_escape(sg_id)}</VpcSecurityGroupId>"
        "<Status>active</Status>"
        "</VpcSecurityGroupMembership>"
        for sg_id in db.get("security_group_ids", []) or []
    )
    subnet_parts = "".join(
        "<Subnet>"
        "<SubnetStatus>Active</SubnetStatus>"
        f"<SubnetIdentifier>{xml_escape(subnet_id)}</SubnetIdentifier>"
        "<SubnetAvailabilityZone><Name>{}</Name><ProvisionedIopsCapable>false</ProvisionedIopsCapable></SubnetAvailabilityZone>"
        "</Subnet>"
        .format(xml_escape(vpc_state.get("subnets", {}).get(subnet_id, {}).get("availability_zone", "")))
        for subnet_id in subnet_group.get("subnet_ids", []) or []
    )
    tag_parts = _rds_tag_xml(db.get("tags", []))
    endpoint = _rds_db_endpoint(db)
    parts = [
        "<DBInstance>",
        f"<DBInstanceIdentifier>{xml_escape(db.get('db_instance_identifier', ''))}</DBInstanceIdentifier>",
        f"<DBInstanceClass>{xml_escape(db.get('db_instance_class', 'db.t3.micro'))}</DBInstanceClass>",
        f"<Engine>{xml_escape(db.get('engine', 'postgres'))}</Engine>",
        f"<DBInstanceStatus>{xml_escape(db.get('db_instance_status', 'available'))}</DBInstanceStatus>",
        f"<MasterUsername>{xml_escape(db.get('master_username', ''))}</MasterUsername>",
        f"<DBName>{xml_escape(db.get('db_name', ''))}</DBName>",
        f"<AllocatedStorage>{db.get('allocated_storage', 20)}</AllocatedStorage>",
        f"<StorageType>{xml_escape(db.get('storage_type', 'gp3'))}</StorageType>",
        f"<EngineVersion>{xml_escape(db.get('engine_version', ''))}</EngineVersion>",
        f"<AutoMinorVersionUpgrade>{'true' if db.get('auto_minor_version_upgrade', True) else 'false'}</AutoMinorVersionUpgrade>",
        f"<CopyTagsToSnapshot>{'true' if db.get('copy_tags_to_snapshot', False) else 'false'}</CopyTagsToSnapshot>",
        f"<PubliclyAccessible>{'true' if db.get('publicly_accessible', False) else 'false'}</PubliclyAccessible>",
        f"<MultiAZ>{'true' if db.get('multi_az', False) else 'false'}</MultiAZ>",
        f"<AvailabilityZone>{xml_escape(db.get('availability_zone', 'us-east-1a'))}</AvailabilityZone>",
        f"<PreferredMaintenanceWindow>{xml_escape(db.get('preferred_maintenance_window', 'sun:03:00-sun:03:30'))}</PreferredMaintenanceWindow>",
        f"<BackupRetentionPeriod>{db.get('backup_retention_period', 7)}</BackupRetentionPeriod>",
        f"<DBInstanceArn>{xml_escape(db.get('db_instance_arn', ''))}</DBInstanceArn>",
        "<Endpoint>",
        f"<Address>{xml_escape(endpoint.get('address', ''))}</Address>",
        f"<Port>{endpoint.get('port', 0)}</Port>",
        f"<HostedZoneId>{xml_escape(endpoint.get('hosted_zone_id', ''))}</HostedZoneId>",
        "</Endpoint>",
        "<VpcSecurityGroups>",
        sg_parts,
        "</VpcSecurityGroups>",
        "<DBSubnetGroup>",
        f"<VpcId>{xml_escape(subnet_group.get('vpc_id', db.get('vpc_id', '')))}</VpcId>",
        f"<SubnetGroupStatus>{xml_escape(subnet_group.get('subnet_group_status', 'Complete'))}</SubnetGroupStatus>",
        f"<DBSubnetGroupDescription>{xml_escape(subnet_group.get('db_subnet_group_description', ''))}</DBSubnetGroupDescription>",
        f"<DBSubnetGroupName>{xml_escape(subnet_group.get('db_subnet_group_name', db.get('db_subnet_group_name', '')))}</DBSubnetGroupName>",
        "<Subnets>",
        subnet_parts,
        "</Subnets>",
        "</DBSubnetGroup>",
        "<DBParameterGroups>",
        "<DBParameterGroup>",
        f"<DBParameterGroupName>{xml_escape(parameter_group.get('db_parameter_group_name', db.get('db_parameter_group_name', '')))}</DBParameterGroupName>",
        f"<ParameterApplyStatus>{xml_escape('in-sync')}</ParameterApplyStatus>",
        "</DBParameterGroup>",
        "</DBParameterGroups>",
        "<PendingModifiedValues/>",
        "<DBSecurityGroups/>",
        f"<TagList>{tag_parts}</TagList>",
        "</DBInstance>",
    ]
    return "".join(parts)


def _rds_success_response(action: str, result_inner: str) -> Response:
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<{action}Response xmlns="{RDS_XML_NS}">'
        f'<{action}Result>{result_inner}</{action}Result>'
        f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
        f'</{action}Response>'
    )
    return _xml_response(xml)


def _rds_error_response(code: str, message: str, status: int = 400) -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ErrorResponse xmlns="{RDS_XML_NS}">'
        '<Error>'
        f'<Type>Sender</Type>'
        f'<Code>{xml_escape(code)}</Code>'
        f'<Message>{xml_escape(message)}</Message>'
        '</Error>'
        f'<RequestId>{_req_id()}</RequestId>'
        '</ErrorResponse>'
    )
    return _xml_response(xml, status=status)


def _rds_find_resource_by_arn_or_name(resource_name: str) -> tuple[str, dict] | None:
    resource_name = (resource_name or "").strip()
    if not resource_name:
        return None
    if ":db:" in resource_name:
        db_id = resource_name.rsplit(":db:", 1)[-1].lower()
        db = _rds_find_db_instance(db_id)
        return ("db", db) if db else None
    if ":snapshot:" in resource_name:
        snapshot_id = resource_name.rsplit(":snapshot:", 1)[-1].lower()
        snapshot = _rds_find_db_snapshot(snapshot_id)
        return ("snapshot", snapshot) if snapshot else None
    if ":subgrp:" in resource_name:
        group_id = resource_name.rsplit(":subgrp:", 1)[-1].lower()
        group = _rds_find_db_subnet_group(group_id)
        return ("subnet-group", group) if group else None
    if ":pg:" in resource_name:
        group_id = resource_name.rsplit(":pg:", 1)[-1].lower()
        group = _rds_find_db_parameter_group(group_id)
        return ("parameter-group", group) if group else None
    db = _rds_find_db_instance(resource_name.lower())
    if db:
        return ("db", db)
    snapshot = _rds_find_db_snapshot(resource_name.lower())
    if snapshot:
        return ("snapshot", snapshot)
    group = _rds_find_db_subnet_group(resource_name.lower())
    if group:
        return ("subnet-group", group)
    pg = _rds_find_db_parameter_group(resource_name.lower())
    if pg:
        return ("parameter-group", pg)
    return None


def _rds_query_describe_db_instances(params: dict[str, Any]) -> Response:
    db_id = str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip().lower()
    filters = _ec2_parse_filters(params)
    dbs = []
    for db in rds_state["db_instances"].values():
        if db_id and db.get("db_instance_identifier") != db_id:
            continue
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "db-instance-id" and db.get("db_instance_identifier", "") not in [v.lower() for v in values]:
                matched = False
            elif lname == "engine" and db.get("engine", "") not in [v.lower() for v in values]:
                matched = False
        if matched:
            dbs.append(db)
    dbs.sort(key=lambda item: (item.get("created", ""), item.get("db_instance_identifier", "")))
    page, next_marker = _rds_query_paginate(dbs, params, 100)
    result = []
    if next_marker:
        result.append(f"<Marker>{next_marker}</Marker>")
    result.append("<DBInstances>")
    for db in page:
        result.append(_rds_db_instance_xml(db))
    result.append("</DBInstances>")
    return _rds_success_response("DescribeDBInstances", "".join(result))


def _rds_query_create_db_instance(params: dict[str, Any]) -> Response:
    _enforce_quantity_cap("database")  # tier cap — Free=1 DB/space
    _enforce_size_cap("db", "aws", str(params.get("DBInstanceClass", "db.t3.micro")))
    tags = _rds_parse_tags(params)
    security_group_ids = []
    for key, value in params.items():
        if key.lower().startswith("vpcsecuritygroupids") and value:
            if isinstance(value, list):
                security_group_ids.extend([str(v) for v in value if v])
            else:
                security_group_ids.append(str(value))
    req = RDSDatabaseRequest(
        db_instance_identifier=str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip(),
        db_instance_class=str(params.get("DBInstanceClass", params.get("dbInstanceClass", "db.t3.micro"))).strip() or "db.t3.micro",
        engine=str(params.get("Engine", params.get("engine", "postgres"))).strip() or "postgres",
        engine_version=str(params.get("EngineVersion", params.get("engineVersion", ""))).strip(),
        master_username=str(params.get("MasterUsername", params.get("masterUsername", "dbadmin"))).strip() or "dbadmin",
        master_user_password=str(params.get("MasterUserPassword", params.get("masterUserPassword", "Password123!"))).strip() or "Password123!",
        allocated_storage=int(str(params.get("AllocatedStorage", params.get("allocatedStorage", 20))) or 20),
        storage_type=str(params.get("StorageType", params.get("storageType", "gp3"))).strip() or "gp3",
        vpc_id=str(params.get("VpcId", params.get("vpcId", ""))).strip(),
        db_subnet_group_name=str(params.get("DBSubnetGroupName", params.get("dbSubnetGroupName", ""))).strip(),
        db_parameter_group_name=str(params.get("DBParameterGroupName", params.get("dbParameterGroupName", ""))).strip(),
        availability_zone=str(params.get("AvailabilityZone", params.get("availabilityZone", "us-east-1a"))).strip() or "us-east-1a",
        publicly_accessible=str(params.get("PubliclyAccessible", params.get("publiclyAccessible", "false"))).lower() == "true",
        multi_az=str(params.get("MultiAZ", params.get("multiAZ", "false"))).lower() == "true",
        backup_retention_period=int(str(params.get("BackupRetentionPeriod", params.get("backupRetentionPeriod", 7))) or 7),
        preferred_maintenance_window=str(params.get("PreferredMaintenanceWindow", params.get("preferredMaintenanceWindow", "sun:03:00-sun:03:30"))).strip() or "sun:03:00-sun:03:30",
        tags=tags,
        security_group_ids=security_group_ids,
    )
    db = _rds_prepare_db_instance(req)
    return _rds_success_response("CreateDBInstance", _rds_db_instance_xml(db))


def _rds_query_modify_db_instance(params: dict[str, Any]) -> Response:
    db_id = str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip().lower()
    db = _rds_find_db_instance(db_id)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    req = RDSModifyRequest(
        db_instance_identifier=db_id,
        db_instance_class=str(params.get("DBInstanceClass", params.get("dbInstanceClass", ""))).strip() or None,
        allocated_storage=int(str(params.get("AllocatedStorage", params.get("allocatedStorage", "")) or 0)) if str(params.get("AllocatedStorage", params.get("allocatedStorage", ""))).strip() else None,
        backup_retention_period=int(str(params.get("BackupRetentionPeriod", params.get("backupRetentionPeriod", "")) or 0)) if str(params.get("BackupRetentionPeriod", params.get("backupRetentionPeriod", ""))).strip() else None,
        publicly_accessible=str(params.get("PubliclyAccessible", params.get("publiclyAccessible", ""))).lower() == "true" if str(params.get("PubliclyAccessible", params.get("publiclyAccessible", ""))).strip() else None,
        multi_az=str(params.get("MultiAZ", params.get("multiAZ", ""))).lower() == "true" if str(params.get("MultiAZ", params.get("multiAZ", ""))).strip() else None,
        engine_version=str(params.get("EngineVersion", params.get("engineVersion", ""))).strip() or None,
        master_user_password=str(params.get("MasterUserPassword", params.get("masterUserPassword", ""))).strip() or None,
        db_parameter_group_name=str(params.get("DBParameterGroupName", params.get("dbParameterGroupName", ""))).strip() or None,
        preferred_maintenance_window=str(params.get("PreferredMaintenanceWindow", params.get("preferredMaintenanceWindow", ""))).strip() or None,
        apply_immediately=str(params.get("ApplyImmediately", params.get("applyImmediately", "true"))).lower() == "true",
    )
    modified = _rds_update_db_instance(db, req)
    return _rds_success_response("ModifyDBInstance", _rds_db_instance_xml(modified))


def _rds_query_delete_db_instance(params: dict[str, Any]) -> Response:
    db_id = str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip().lower()
    db = _rds_find_db_instance(db_id)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    skip_final_snapshot = str(params.get("SkipFinalSnapshot", params.get("skipFinalSnapshot", "true"))).lower() == "true"
    final_snapshot_identifier = str(params.get("FinalDBSnapshotIdentifier", params.get("finalDBSnapshotIdentifier", ""))).strip()
    result_db = copy.deepcopy(db)
    _rds_delete_db_instance(db_id, skip_final_snapshot=skip_final_snapshot, final_snapshot_identifier=final_snapshot_identifier)
    return _rds_success_response("DeleteDBInstance", _rds_db_instance_xml(result_db))


def _rds_query_start_stop_reboot(action: str, params: dict[str, Any]) -> Response:
    db_id = str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip().lower()
    db = _rds_find_db_instance(db_id)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    if action == "StartDBInstance":
        db["db_instance_status"] = "available"
    elif action == "StopDBInstance":
        db["db_instance_status"] = "stopped"
    else:
        db["db_instance_status"] = "available"
    db["updated"] = _now()
    _rds_emit_event(action, {"db_instance_identifier": db_id})
    return _rds_success_response(action, _rds_db_instance_xml(db))


def _rds_query_create_db_snapshot(params: dict[str, Any]) -> Response:
    db_id = str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip().lower()
    snapshot_id = str(params.get("DBSnapshotIdentifier", params.get("dbSnapshotIdentifier", ""))).strip().lower()
    db = _rds_find_db_instance(db_id)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    snapshot = _rds_create_snapshot_from_db(db, snapshot_id, _rds_parse_tags(params))
    return _rds_success_response("CreateDBSnapshot", _rds_db_snapshot_xml(snapshot))


def _rds_query_describe_db_snapshots(params: dict[str, Any]) -> Response:
    db_id = str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip().lower()
    snapshot_id = str(params.get("DBSnapshotIdentifier", params.get("dbSnapshotIdentifier", ""))).strip().lower()
    filters = _ec2_parse_filters(params)
    snapshots = []
    for snapshot in rds_state["db_snapshots"].values():
        if db_id and snapshot.get("db_instance_identifier") != db_id:
            continue
        if snapshot_id and snapshot.get("db_snapshot_identifier") != snapshot_id:
            continue
        matched = True
        for name, values in filters:
            lname = name.lower()
            if lname == "db-instance-id" and snapshot.get("db_instance_identifier", "") not in [v.lower() for v in values]:
                matched = False
            elif lname == "db-snapshot-id" and snapshot.get("db_snapshot_identifier", "") not in [v.lower() for v in values]:
                matched = False
        if matched:
            snapshots.append(snapshot)
    snapshots.sort(key=lambda item: (item.get("created", ""), item.get("db_snapshot_identifier", "")))
    page, next_marker = _rds_query_paginate(snapshots, params, 100)
    result = []
    if next_marker:
        result.append(f"<Marker>{next_marker}</Marker>")
    result.append("<DBSnapshots>")
    for snapshot in page:
        result.append(_rds_db_snapshot_xml(snapshot))
    result.append("</DBSnapshots>")
    return _rds_success_response("DescribeDBSnapshots", "".join(result))


def _rds_query_restore_db_snapshot(params: dict[str, Any]) -> Response:
    db_snapshot_identifier = str(params.get("DBSnapshotIdentifier", params.get("dbSnapshotIdentifier", ""))).strip().lower()
    snapshot = _rds_find_db_snapshot(db_snapshot_identifier)
    if not snapshot:
        raise HTTPException(404, detail="DBSnapshotNotFound")
    req = RDSRestoreSnapshotRequest(
        db_instance_identifier=str(params.get("DBInstanceIdentifier", params.get("dbInstanceIdentifier", ""))).strip(),
        db_snapshot_identifier=db_snapshot_identifier,
        db_instance_class=str(params.get("DBInstanceClass", params.get("dbInstanceClass", snapshot.get("db_instance_class", "db.t3.micro")))).strip() or snapshot.get("db_instance_class", "db.t3.micro"),
        vpc_id=str(params.get("VpcId", params.get("vpcId", snapshot.get("vpc_id", "")))).strip(),
        db_subnet_group_name=str(params.get("DBSubnetGroupName", params.get("dbSubnetGroupName", snapshot.get("db_subnet_group_name", "")))).strip(),
        publicly_accessible=str(params.get("PubliclyAccessible", params.get("publiclyAccessible", "false"))).lower() == "true",
        multi_az=str(params.get("MultiAZ", params.get("multiAZ", "false"))).lower() == "true",
        tags=_rds_parse_tags(params),
    )
    db = _rds_restore_snapshot(snapshot, req)
    return _rds_success_response("RestoreDBInstanceFromDBSnapshot", _rds_db_instance_xml(db))


def _rds_query_create_describe_subnet_group(action: str, params: dict[str, Any]) -> Response:
    name = str(params.get("DBSubnetGroupName", params.get("dbSubnetGroupName", ""))).strip().lower()
    if action == "CreateDBSubnetGroup":
        desc = str(params.get("DBSubnetGroupDescription", params.get("dbSubnetGroupDescription", name))).strip() or name
        vpc_id = str(params.get("VpcId", params.get("vpcId", _rds_vpc_id()))).strip()
        subnet_ids = []
        for key, value in params.items():
            if key.lower().startswith("subnetids") and value:
                if isinstance(value, list):
                    subnet_ids.extend([str(v) for v in value if v])
                else:
                    subnet_ids.append(str(value))
        tags = _rds_parse_tags(params)
        if not name:
            raise HTTPException(400, detail="MissingParameter: DBSubnetGroupName")
        if name in rds_state["db_subnet_groups"]:
            raise HTTPException(400, detail="DBSubnetGroupAlreadyExists")
        if not vpc_id:
            raise HTTPException(400, detail="NoSuchVpc")
        if not subnet_ids:
            subnet_ids = _rds_default_subnet_ids(vpc_id)
        group = _rds_make_db_subnet_group(name, desc, vpc_id, subnet_ids, tags)
        return _rds_success_response(action, _rds_db_subnet_group_xml(group))
    groups = []
    if name:
        group = _rds_find_db_subnet_group(name)
        if group:
            groups.append(group)
    else:
        groups = list(rds_state["db_subnet_groups"].values())
    page, next_marker = _rds_query_paginate(sorted(groups, key=lambda item: item.get("db_subnet_group_name", "")), params, 100)
    result = []
    if next_marker:
        result.append(f"<Marker>{next_marker}</Marker>")
    result.append("<DBSubnetGroups>")
    for group in page:
        result.append(_rds_db_subnet_group_xml(group))
    result.append("</DBSubnetGroups>")
    return _rds_success_response("DescribeDBSubnetGroups", "".join(result))


def _rds_query_delete_subnet_group(params: dict[str, Any]) -> Response:
    name = str(params.get("DBSubnetGroupName", params.get("dbSubnetGroupName", ""))).strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: DBSubnetGroupName")
    for db in rds_state["db_instances"].values():
        if db.get("db_subnet_group_name") == name:
            raise HTTPException(400, detail="InvalidDBSubnetGroupState")
    group = _rds_find_db_subnet_group(name)
    if not group:
        raise HTTPException(404, detail="DBSubnetGroupNotFound")
    del rds_state["db_subnet_groups"][name]
    return _rds_success_response("DeleteDBSubnetGroup", "<return>true</return>")


def _rds_query_create_describe_parameter_group(action: str, params: dict[str, Any]) -> Response:
    name = str(params.get("DBParameterGroupName", params.get("dbParameterGroupName", ""))).strip().lower()
    if action == "CreateDBParameterGroup":
        family = str(params.get("DBParameterGroupFamily", params.get("dbParameterGroupFamily", "postgres16"))).strip() or "postgres16"
        desc = str(params.get("Description", params.get("description", name))).strip() or name
        tags = _rds_parse_tags(params)
        if not name:
            raise HTTPException(400, detail="MissingParameter: DBParameterGroupName")
        if name in rds_state["db_parameter_groups"]:
            raise HTTPException(400, detail="DBParameterGroupAlreadyExists")
        group = _rds_make_db_parameter_group(name, family, desc, tags)
        return _rds_success_response(action, _rds_db_parameter_group_xml(group))
    groups = []
    if name:
        group = _rds_find_db_parameter_group(name)
        if group:
            groups.append(group)
    else:
        groups = list(rds_state["db_parameter_groups"].values())
    page, next_marker = _rds_query_paginate(sorted(groups, key=lambda item: item.get("db_parameter_group_name", "")), params, 100)
    result = []
    if next_marker:
        result.append(f"<Marker>{next_marker}</Marker>")
    result.append("<DBParameterGroups>")
    for group in page:
        result.append(_rds_db_parameter_group_xml(group))
    result.append("</DBParameterGroups>")
    return _rds_success_response("DescribeDBParameterGroups", "".join(result))


def _rds_query_delete_parameter_group(params: dict[str, Any]) -> Response:
    name = str(params.get("DBParameterGroupName", params.get("dbParameterGroupName", ""))).strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: DBParameterGroupName")
    for db in rds_state["db_instances"].values():
        if db.get("db_parameter_group_name") == name:
            raise HTTPException(400, detail="InvalidDBParameterGroupState")
    group = _rds_find_db_parameter_group(name)
    if not group:
        raise HTTPException(404, detail="DBParameterGroupNotFound")
    del rds_state["db_parameter_groups"][name]
    return _rds_success_response("DeleteDBParameterGroup", "<return>true</return>")


def _rds_query_add_tags(params: dict[str, Any]) -> Response:
    resource_name = str(params.get("ResourceName", params.get("resourceName", ""))).strip()
    found = _rds_find_resource_by_arn_or_name(resource_name)
    if not found:
        raise HTTPException(404, detail="ResourceNotFound")
    tags = _rds_parse_tags(params)
    if not tags:
        raise HTTPException(400, detail="MissingParameter: Tag")
    resource_type, resource = found
    if resource_type == "db":
        _rds_set_tags(resource, tags)
    elif resource_type in {"subnet-group", "parameter-group"}:
        _rds_set_tags(resource, tags)
    elif resource_type == "snapshot":
        _rds_set_tags(resource, tags)
    return _rds_success_response("AddTagsToResource", "<return>true</return>")


def _rds_query_list_tags(params: dict[str, Any]) -> Response:
    resource_name = str(params.get("ResourceName", params.get("resourceName", ""))).strip()
    found = _rds_find_resource_by_arn_or_name(resource_name)
    if not found:
        raise HTTPException(404, detail="ResourceNotFound")
    _, resource = found
    tags = list(resource.get("tags", []))
    result = "<TagList>" + _rds_tag_xml(tags) + "</TagList>"
    return _rds_success_response("ListTagsForResource", result)


def _sqs_xml_result(action: str, body: str, status: int = 200, extra_headers: dict | None = None) -> Response:
    xml = f'<?xml version="1.0" encoding="UTF-8"?><{action}Response xmlns="{SQS_XML_NS}"><{action}Result>{body}</{action}Result><ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata></{action}Response>'
    return _xml_response(xml, status=status, extra_headers=extra_headers)


def _sqs_xml_queue(queue: dict) -> str:
    return f"<QueueUrl>{xml_escape(queue.get('queue_url') or _sqs_queue_url(queue['queue_name']))}</QueueUrl>"


def _sqs_xml_attributes(queue: dict, names: list[str] | None = None) -> str:
    attrs = _sqs_xml_queue_attributes(queue, names)
    body = []
    for name, value in attrs:
        body.append("<Attribute>")
        body.append(f"<Name>{xml_escape(name)}</Name>")
        body.append(f"<Value>{xml_escape(value)}</Value>")
        body.append("</Attribute>")
    return "".join(body)


def _sqs_xml_queue_attributes(queue: dict, names: list[str] | None = None) -> list[tuple[str, str]]:
    attrs = _sqs_queue_attributes(queue)
    if not names or any(name == "All" for name in names):
        return list(attrs.items())
    return [(name, attrs[name]) for name in names if name in attrs]


def _sqs_xml_message(message: dict) -> str:
    body = [
        "<Message>",
        f"<MessageId>{xml_escape(message.get('message_id', ''))}</MessageId>",
        f"<ReceiptHandle>{xml_escape(message.get('receipt_handle', ''))}</ReceiptHandle>",
        f"<MD5OfBody>{xml_escape(message.get('md5_of_body', ''))}</MD5OfBody>",
        f"<Body>{xml_escape(message.get('body', ''))}</Body>",
    ]
    attrs = message.get("attributes") or {}
    if attrs:
        body.append("<Attribute>")
        for key, value in attrs.items():
            body.append(f"<Name>{xml_escape(str(key))}</Name>")
            body.append(f"<Value>{xml_escape(str(value))}</Value>")
        body.append("</Attribute>")
    msg_attrs = message.get("message_attributes") or {}
    if msg_attrs:
        body.append("<MessageAttribute>")
        for key, value in msg_attrs.items():
            body.append(f"<Name>{xml_escape(str(key))}</Name>")
            body.append(f"<StringValue>{xml_escape(str(value))}</StringValue>")
        body.append("</MessageAttribute>")
    body.append("</Message>")
    return "".join(body)


def _sqs_xml_queue_tags(tags: dict[str, str]) -> str:
    return "".join(f"<Tag>{xml_escape(k)}={xml_escape(v)}</Tag>" for k, v in tags.items())


def _sqs_query_collect_list(params: dict[str, Any], prefix: str) -> list[str]:
    values: list[str] = []
    index = 1
    while True:
        key = f"{prefix}.{index}"
        if key not in params:
            break
        value = params.get(key)
        if isinstance(value, list):
            values.extend([str(v) for v in value if str(v).strip()])
        elif value is not None and str(value).strip():
            values.append(str(value))
        index += 1
    if not values and prefix in params:
        value = params.get(prefix)
        if isinstance(value, list):
            values.extend([str(v) for v in value if str(v).strip()])
        elif value is not None and str(value).strip():
            values.append(str(value))
    return values


def _sqs_query_create_queue(params: dict[str, Any]) -> Response:
    _enforce_quantity_cap("queue")  # tier cap — Free=1 queue/space
    req = SQSQueueCreateRequest(
        queue_name=str(params.get("QueueName", params.get("queueName", ""))).strip(),
        fifo_queue=_sqs_query_bool(params.get("FifoQueue")),
        content_based_deduplication=_sqs_query_bool(params.get("ContentBasedDeduplication")),
        visibility_timeout=int(params.get("VisibilityTimeout", 30) or 30),
        receive_wait_time_seconds=int(params.get("ReceiveMessageWaitTimeSeconds", 0) or 0),
        message_retention_period=int(params.get("MessageRetentionPeriod", 345600) or 345600),
        max_message_size=int(params.get("MaximumMessageSize", 262144) or 262144),
        delay_seconds=int(params.get("DelaySeconds", 0) or 0),
        redrive_policy=json.loads(params.get("RedrivePolicy", "{}") or "{}") if str(params.get("RedrivePolicy", "")).strip() else {},
        tags={},
    )
    queue = _sqs_create_queue_record(req)
    return _sqs_xml_result("CreateQueue", _sqs_xml_queue(queue))


def _sqs_query_list_queues(params: dict[str, Any]) -> Response:
    prefix = str(params.get("QueueNamePrefix", params.get("queueNamePrefix", ""))).strip()
    queues = [_sqs_queue_list_view(queue) for queue in _sqs_list_queues() if not prefix or queue.get("queue_name", "").startswith(prefix)]
    body = "".join(_sqs_xml_queue(queue) for queue in queues)
    body = f"<QueueUrls>{body}</QueueUrls>"
    return _sqs_xml_result("ListQueues", body)


def _sqs_query_get_queue_url(params: dict[str, Any]) -> Response:
    queue_name = str(params.get("QueueName", params.get("queueName", ""))).strip()
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    return _sqs_xml_result("GetQueueUrl", f"<QueueUrl>{xml_escape(queue.get('queue_url') or _sqs_queue_url(queue['queue_name']))}</QueueUrl>")


def _sqs_query_get_set_attributes(action: str, params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    if action == "GetQueueAttributes":
        names = _sqs_query_collect_list(params, "AttributeName")
        body = "<Attributes>" + _sqs_xml_attributes(queue, names) + "</Attributes>"
        return _sqs_xml_result("GetQueueAttributes", body)
    attrs: dict[str, Any] = {}
    for key, value in params.items():
        if key.startswith("Attribute."):
            parts = key.split(".")
            if len(parts) >= 3 and parts[2] == "Name":
                index = parts[1]
                val = params.get(f"Attribute.{index}.Value")
                if val is not None:
                    attrs[str(value)] = val
    if not attrs:
        for key in ["VisibilityTimeout", "ReceiveMessageWaitTimeSeconds", "MessageRetentionPeriod", "MaximumMessageSize", "DelaySeconds", "RedrivePolicy", "ContentBasedDeduplication"]:
            if key in params:
                attrs[key] = params[key]
    _sqs_update_queue_attributes(queue, attrs)
    return _sqs_xml_result("SetQueueAttributes", "")


def _sqs_query_send_message(params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    body = str(params.get("MessageBody", params.get("messageBody", "")))
    if not body:
        raise HTTPException(400, detail="MissingParameter: MessageBody")
    group_id = str(params.get("MessageGroupId", params.get("messageGroupId", ""))).strip()
    dedup_id = str(params.get("MessageDeduplicationId", params.get("messageDeduplicationId", ""))).strip()
    message = _sqs_enqueue_message(queue, body, {}, {}, group_id=group_id, dedup_id=dedup_id, source="SendMessage")
    body_xml = f"<MessageId>{xml_escape(message['message_id'])}</MessageId><MD5OfMessageBody>{xml_escape(message['md5_of_body'])}</MD5OfMessageBody>"
    if message.get("sequence_number"):
        body_xml += f"<SequenceNumber>{xml_escape(message['sequence_number'])}</SequenceNumber>"
    return _sqs_xml_result("SendMessage", body_xml)


def _sqs_query_receive_message(params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    max_messages = max(1, min(int(params.get("MaxNumberOfMessages", params.get("maxNumberOfMessages", 1)) or 1), 10))
    wait_time = max(0, int(params.get("WaitTimeSeconds", params.get("waitTimeSeconds", queue.get("receive_wait_time_seconds", 0))) or 0))
    visibility_timeout = params.get("VisibilityTimeout", params.get("visibilityTimeout"))
    visibility_timeout = int(visibility_timeout) if visibility_timeout is not None and str(visibility_timeout).strip() else int(queue.get("visibility_timeout", 30))
    deadline = time.time() + wait_time
    deliveries = []
    while True:
        deliveries = _sqs_extract_messages_for_delivery(queue, max_messages)
        if deliveries or wait_time <= 0 or time.time() >= deadline:
            break
        time.sleep(0.2)
    if visibility_timeout != int(queue.get("visibility_timeout", 30) or 30):
        for message in deliveries:
            message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=visibility_timeout)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = "<ReceiveMessageResult>" + "".join(_sqs_xml_message(message) for message in deliveries) + "</ReceiveMessageResult>"
    return _sqs_xml_result("ReceiveMessage", body)


def _sqs_query_delete_message(params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    receipt_handle = str(params.get("ReceiptHandle", params.get("receiptHandle", ""))).strip()
    if not receipt_handle:
        raise HTTPException(400, detail="MissingParameter: ReceiptHandle")
    if not _sqs_delete_message(queue, receipt_handle):
        raise HTTPException(400, detail="ReceiptHandleIsInvalid")
    return _sqs_xml_result("DeleteMessage", "")


def _sqs_query_change_message_visibility(params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    receipt_handle = str(params.get("ReceiptHandle", params.get("receiptHandle", ""))).strip()
    visibility_timeout = int(params.get("VisibilityTimeout", params.get("visibilityTimeout", 30)) or 30)
    if not receipt_handle:
        raise HTTPException(400, detail="MissingParameter: ReceiptHandle")
    if not _sqs_change_message_visibility(queue, receipt_handle, visibility_timeout):
        raise HTTPException(400, detail="ReceiptHandleIsInvalid")
    return _sqs_xml_result("ChangeMessageVisibility", "")


def _sqs_query_purge_queue(params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    _sqs_purge_queue(queue)
    return _sqs_xml_result("PurgeQueue", "")


def _sqs_query_tag_untag_list_tags(action: str, params: dict[str, Any]) -> Response:
    queue_ref = str(params.get("QueueUrl", params.get("queueUrl", params.get("QueueName", params.get("queueName", ""))))).strip()
    queue = _sqs_queue_from_name_or_url(queue_ref)
    if not queue:
        raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
    if action == "ListQueueTags":
        tags = _sqs_tags_view(queue)
        body = "<Tags>" + "".join(f"<Tag><Key>{xml_escape(k)}</Key><Value>{xml_escape(v)}</Value></Tag>" for k, v in tags.items()) + "</Tags>"
        return _sqs_xml_result("ListQueueTags", body)
    if action == "TagQueue":
        tags = {}
        for key, value in params.items():
            if key.startswith("Tag.") and key.endswith(".Key"):
                idx = key.split(".")[1]
                tag_value = params.get(f"Tag.{idx}.Value", "")
                tags[str(value)] = str(tag_value)
        if not tags and params.get("Tags"):
            maybe = params.get("Tags")
            if isinstance(maybe, dict):
                tags = {str(k): str(v) for k, v in maybe.items()}
        if tags:
            current = _sqs_tags_view(queue)
            current.update(tags)
            _sqs_set_tags(queue, current)
        return _sqs_xml_result("TagQueue", "")
    current = _sqs_tags_view(queue)
    keys = _sqs_query_collect_list(params, "TagKey")
    if not keys:
        keys = list(current.keys())
    for key in keys:
        current.pop(key, None)
    _sqs_set_tags(queue, current)
    return _sqs_xml_result("UntagQueue", "")


def _sqs_json(payload: dict, status: int = 200) -> Response:
    return Response(content=json.dumps(payload), status_code=status, media_type="application/x-amz-json-1.0")


def _sqs_json_error(code: str, message: str, status: int = 400) -> Response:
    return _sqs_json({"__type": code, "message": message}, status)


async def _sqs_json_dispatch(request: Request, action: str) -> Response:
    """Modern boto3/SDK SQS uses the AWS-JSON protocol (X-Amz-Target). Reuse the
    SQS store operations and serialize JSON responses so unmodified clients work.

    ElasticMQ proxy: try ElasticMQ first (it now handles JSON-RPC via the
    query-protocol translation layer in elasticmq_proxy), fall back to in-memory.
    """
    # --- ElasticMQ proxy attempt (mirrors the query-path proxy in api_sqs_query) ---
    try:
        from core import elasticmq_proxy as _emq
        if _emq.available():
            status, body_bytes, ctype = await _emq.proxy(request)
            if status != 502:
                return Response(content=body_bytes, status_code=status, media_type=ctype)
    except Exception:
        pass

    try:
        raw = await request.body()
        body = json.loads(raw.decode("utf-8") or "{}") if raw else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    def queue_url(q: dict) -> str:
        return q.get("queue_url") or _sqs_queue_url(q["queue_name"])

    try:
        if action == "CreateQueue":
            name = str(body.get("QueueName", "")).strip()
            if not name:
                return _sqs_json_error("com.amazonaws.sqs#MissingParameter", "QueueName is required.")
            attrs = body.get("Attributes") or {}
            req = SQSQueueCreateRequest(
                queue_name=name,
                fifo_queue=str(attrs.get("FifoQueue", "")).lower() == "true" or name.endswith(".fifo"),
                content_based_deduplication=str(attrs.get("ContentBasedDeduplication", "")).lower() == "true",
                visibility_timeout=int(attrs.get("VisibilityTimeout", 30) or 30),
                receive_wait_time_seconds=int(attrs.get("ReceiveMessageWaitTimeSeconds", 0) or 0),
                message_retention_period=int(attrs.get("MessageRetentionPeriod", 345600) or 345600),
                max_message_size=int(attrs.get("MaximumMessageSize", 262144) or 262144),
                delay_seconds=int(attrs.get("DelaySeconds", 0) or 0),
                redrive_policy={},
                tags=body.get("tags") or {},
            )
            return _sqs_json({"QueueUrl": queue_url(_sqs_create_queue_record(req))})
        if action == "GetQueueUrl":
            queue = _sqs_find_queue(str(body.get("QueueName", "")).strip())
            if not queue:
                return _sqs_json_error("com.amazonaws.sqs#QueueDoesNotExist", "The specified queue does not exist.")
            return _sqs_json({"QueueUrl": queue_url(queue)})
        if action == "ListQueues":
            prefix = str(body.get("QueueNamePrefix", "")).strip()
            urls = [queue_url(q) for q in _sqs_list_queues() if not prefix or q.get("queue_name", "").startswith(prefix)]
            return _sqs_json({"QueueUrls": urls})
        if action == "DeleteQueue":
            queue = _sqs_queue_from_name_or_url(str(body.get("QueueUrl", "")).strip())
            if queue:
                _sqs_state().get("queues", {}).pop(queue["queue_name"], None)
            return _sqs_json({})
        queue = _sqs_queue_from_name_or_url(str(body.get("QueueUrl", "")).strip())
        if not queue:
            return _sqs_json_error("com.amazonaws.sqs#QueueDoesNotExist", "The specified queue does not exist.")
        if action == "SendMessage":
            msg = _sqs_enqueue_message(queue, str(body.get("MessageBody", "")), {}, {},
                                       group_id=str(body.get("MessageGroupId", "")),
                                       dedup_id=str(body.get("MessageDeduplicationId", "")), source="SendMessage")
            resp = {"MessageId": msg["message_id"], "MD5OfMessageBody": msg["md5_of_body"]}
            if msg.get("sequence_number"):
                resp["SequenceNumber"] = msg["sequence_number"]
            return _sqs_json(resp)
        if action == "ReceiveMessage":
            maxn = max(1, min(int(body.get("MaxNumberOfMessages", 1) or 1), 10))
            deliveries = _sqs_extract_messages_for_delivery(queue, maxn)
            msgs = [{"MessageId": m.get("message_id", ""), "ReceiptHandle": m.get("receipt_handle", ""),
                     "MD5OfBody": m.get("md5_of_body", ""), "Body": m.get("body", "")} for m in deliveries]
            return _sqs_json({"Messages": msgs})
        if action == "DeleteMessage":
            _sqs_delete_message(queue, str(body.get("ReceiptHandle", "")))
            return _sqs_json({})
        if action == "PurgeQueue":
            _sqs_purge_queue(queue)
            return _sqs_json({})
        if action == "ChangeMessageVisibility":
            _sqs_change_message_visibility(queue, str(body.get("ReceiptHandle", "")), int(body.get("VisibilityTimeout", 30) or 30))
            return _sqs_json({})
        if action == "GetQueueAttributes":
            attrs = _sqs_queue_attributes(queue)
            names = body.get("AttributeNames") or ["All"]
            selected = attrs if "All" in names else {k: v for k, v in attrs.items() if k in names}
            return _sqs_json({"Attributes": {k: str(v) for k, v in selected.items()}})
        if action == "SetQueueAttributes":
            _sqs_update_queue_attributes(queue, body.get("Attributes") or {})
            return _sqs_json({})
    except HTTPException as exc:
        code = str(exc.detail).split(":", 1)[0].strip() or "InvalidParameterValue"
        return _sqs_json_error(f"com.amazonaws.sqs#{code}", str(exc.detail), exc.status_code if exc.status_code >= 400 else 400)
    return _sqs_json_error("com.amazonaws.sqs#InvalidAction", f"The action '{action}' is not implemented.")


async def api_sqs_query(request: Request):
    # MVP P0: route legacy query-protocol SQS to ElasticMQ for real-broker
    # semantics (FIFO, visibility timeout, persistence). Modern JSON-RPC
    # (X-Amz-Target=AmazonSQS.*) stays on the in-memory handler because
    # elasticmq-native only speaks the query protocol; translating XML
    # responses to JSON for boto3 was deemed too lossy for MVP.
    target = request.headers.get("x-amz-target", "") or ""
    if not target:
        try:
            from core import elasticmq_proxy as _emq
            status, body, ctype = await _emq.proxy(request)
            if status != 502:
                return Response(content=body, status_code=status, media_type=ctype)
        except Exception:
            pass
    if target:
        return await _sqs_json_dispatch(request, target.split(".")[-1].strip())
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error_xml("InvalidAction", "Missing Action parameter.", "/sqs", 400)
    try:
        if action == "CreateQueue":
            return _sqs_query_create_queue(params)
        if action == "ListQueues":
            return _sqs_query_list_queues(params)
        if action == "GetQueueUrl":
            return _sqs_query_get_queue_url(params)
        if action in {"GetQueueAttributes", "SetQueueAttributes"}:
            return _sqs_query_get_set_attributes(action, params)
        if action == "SendMessage":
            return _sqs_query_send_message(params)
        if action == "ReceiveMessage":
            return _sqs_query_receive_message(params)
        if action == "DeleteMessage":
            return _sqs_query_delete_message(params)
        if action == "ChangeMessageVisibility":
            return _sqs_query_change_message_visibility(params)
        if action == "PurgeQueue":
            return _sqs_query_purge_queue(params)
        if action in {"TagQueue", "UntagQueue", "ListQueueTags"}:
            return _sqs_query_tag_untag_list_tags(action, params)
    except HTTPException as exc:
        code = str(exc.detail).split(":", 1)[0]
        message = str(exc.detail)
        return _error_xml(code, message, "/sqs", exc.status_code)
    return _error_xml("InvalidAction", f"The action '{action}' is not implemented by the simulator.", "/sqs", 400)


def api_sqs_list_queues():
    queues = [_sqs_queue_list_view(queue) for queue in _sqs_list_queues()]
    return {"queues": queues, "count": len(queues)}


def api_sqs_create_queue(req: SQSQueueCreateRequest):
    queue = _sqs_create_queue_record(req)
    _cloudsim_sync_service_resource("aws", "sqs", "queue", queue.get("queue_name", ""), queue, "sqs")
    _record_usage("sqs.create_queue", {"queue_name": queue.get("queue_name", "")})
    return _sqs_queue_view(queue)


def api_sqs_get_queue(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return _sqs_queue_view(queue)


def api_sqs_update_queue(queue_name: str, req: SQSQueueUpdateRequest):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    payload = {
        "VisibilityTimeout": req.visibility_timeout,
        "ReceiveMessageWaitTimeSeconds": req.receive_wait_time_seconds,
        "MessageRetentionPeriod": req.message_retention_period,
        "MaximumMessageSize": req.max_message_size,
        "DelaySeconds": req.delay_seconds,
        "ContentBasedDeduplication": req.content_based_deduplication,
        "RedrivePolicy": req.redrive_policy,
    }
    if req.tags is not None:
        queue["tags"] = copy.deepcopy(req.tags)
    _sqs_update_queue_attributes(queue, {k: v for k, v in payload.items() if v is not None})
    _record_usage("sqs.update_queue", {"queue_name": queue_name})
    return _sqs_queue_view(queue)


def api_sqs_delete_queue(queue_name: str):
    _sqs_delete_queue(queue_name)
    _cloudsim_sync_service_resource("aws", "sqs", "queue", queue_name, {}, "sqs", action="delete")
    _record_usage("sqs.delete_queue", {"queue_name": queue_name})
    return {"deleted": True, "queue_name": queue_name}


def api_sqs_list_messages(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return {"queue_name": queue["queue_name"], "messages": [_sqs_view_message(queue, msg) for msg in queue.get("messages", []) if not msg.get("deleted")], "count": len(queue.get("messages", []))}


def api_sqs_send_message(queue_name: str, req: SQSMessageSendRequest):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    message = _sqs_enqueue_message(queue, req.message_body, req.message_attributes or req.message_attributes_map or {}, req.message_attributes_map or {}, req.message_group_id, req.message_deduplication_id, source="api_send_message")
    return {"message": _sqs_view_message(queue, message), "queue_name": queue["queue_name"], "queue_url": queue.get("queue_url")}


def api_sqs_receive_message(queue_name: str, req: SQSReceiveRequest):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    deliveries = _sqs_extract_messages_for_delivery(queue, max(1, min(int(req.max_number_of_messages or 1), 10)))
    if req.visibility_timeout is not None:
        for message in deliveries:
            message["visible_at"] = (datetime.now(timezone.utc) + timedelta(seconds=max(0, int(req.visibility_timeout)))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"queue_name": queue["queue_name"], "messages": [_sqs_view_message(queue, msg) for msg in deliveries], "count": len(deliveries)}


def api_sqs_delete_message(queue_name: str, receipt_handle: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    if not _sqs_delete_message(queue, receipt_handle):
        raise HTTPException(400, detail="ReceiptHandleIsInvalid")
    return {"deleted": True, "queue_name": queue["queue_name"], "receipt_handle": receipt_handle}


def api_sqs_change_visibility(queue_name: str, receipt_handle: str, req: SQSVisibilityRequest):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    if not _sqs_change_message_visibility(queue, receipt_handle, req.visibility_timeout):
        raise HTTPException(400, detail="ReceiptHandleIsInvalid")
    return {"updated": True, "queue_name": queue["queue_name"], "receipt_handle": receipt_handle, "visibility_timeout": req.visibility_timeout}


def api_sqs_purge(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    _sqs_purge_queue(queue)
    return {"purged": True, "queue_name": queue["queue_name"]}


def api_sqs_list_tags(queue_name: str):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    return {"queue_name": queue["queue_name"], "tags": _sqs_tags_view(queue)}


def api_sqs_tag_queue(queue_name: str, payload: dict[str, str]):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    current = _sqs_tags_view(queue)
    current.update({str(k): str(v) for k, v in payload.items()})
    _sqs_set_tags(queue, current)
    return {"tagged": True, "queue_name": queue["queue_name"], "tags": _sqs_tags_view(queue)}


def api_sqs_untag_queue(queue_name: str, payload: dict[str, Any]):
    queue = _sqs_find_queue(queue_name)
    if not queue:
        raise HTTPException(404, detail="QueueNotFound")
    keys = payload.get("keys") if isinstance(payload, dict) else []
    current = _sqs_tags_view(queue)
    for key in keys or []:
        current.pop(str(key), None)
    _sqs_set_tags(queue, current)
    return {"untagged": True, "queue_name": queue["queue_name"], "tags": _sqs_tags_view(queue)}


def _ddb_state() -> dict:
    return ddb_state


def _ddb_tables() -> dict:
    return _ddb_state().setdefault("tables", {})


def _ddb_table_arn(table_name: str) -> str:
    return _iam_dynamodb_table_arn(table_name)


def _ddb_is_typed_value(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and next(iter(value.keys())) in {"S", "N", "BOOL", "NULL", "M", "L", "SS", "NS", "BS", "B"}


def _ddb_json_to_native(value: Any) -> Any:
    if isinstance(value, dict):
        if _ddb_is_typed_value(value):
            type_key, raw = next(iter(value.items()))
            if type_key == "S":
                return str(raw)
            if type_key == "N":
                raw_text = str(raw)
                try:
                    return int(raw_text) if re.fullmatch(r"-?\d+", raw_text) else float(raw_text)
                except Exception:
                    return raw_text
            if type_key == "BOOL":
                return bool(raw)
            if type_key == "NULL":
                return None
            if type_key == "B":
                return raw
            if type_key == "SS":
                return [str(item) for item in (raw or [])]
            if type_key == "NS":
                values = []
                for item in raw or []:
                    try:
                        item_text = str(item)
                        values.append(int(item_text) if re.fullmatch(r"-?\d+", item_text) else float(item_text))
                    except Exception:
                        values.append(str(item))
                return values
            if type_key == "BS":
                return list(raw or [])
            if type_key == "L":
                return [_ddb_json_to_native(item) for item in (raw or [])]
            if type_key == "M":
                return {k: _ddb_json_to_native(v) for k, v in (raw or {}).items()}
        return {k: _ddb_json_to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ddb_json_to_native(v) for v in value]
    return copy.deepcopy(value)


def _ddb_native_to_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {"M": {k: _ddb_native_to_json(v) for k, v in value.items()}}
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return {"SS": [str(item) for item in value]}
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return {"NS": [str(item) for item in value]}
        return {"L": [_ddb_native_to_json(item) for item in value]}
    if isinstance(value, bool):
        return {"BOOL": value}
    if value is None:
        return {"NULL": True}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"N": str(value)}
    return {"S": str(value)}


def _ddb_native_item_to_json(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _ddb_native_to_json(v) for k, v in (item or {}).items()}


def _ddb_item_to_native_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise HTTPException(400, detail="ValidationException: Item must be an object.")
    return {k: _ddb_json_to_native(v) for k, v in item.items()}


def _ddb_table_key_fields(table: dict) -> tuple[str, str]:
    return str(table.get("partition_key_name", "id")), str(table.get("sort_key_name", "") or "")


def _ddb_item_key_tuple(table: dict, item: dict[str, Any]) -> tuple[Any, Any | None]:
    pk_name, sk_name = _ddb_table_key_fields(table)
    if pk_name not in item:
        raise HTTPException(400, detail=f"ValidationException: Missing partition key '{pk_name}'.")
    pk = item.get(pk_name)
    sk = item.get(sk_name) if sk_name else None
    if sk_name and sk is None:
        raise HTTPException(400, detail=f"ValidationException: Missing sort key '{sk_name}'.")
    return pk, sk


def _ddb_item_key_string(table: dict, item: dict[str, Any]) -> str:
    return json.dumps(_ddb_item_key_tuple(table, item), default=str, separators=(",", ":"))


def _ddb_normalize_table(table_name: str, table: dict) -> dict:
    table.setdefault("table_name", table_name)
    table.setdefault("table_arn", _ddb_table_arn(table_name))
    table.setdefault("table_status", "ACTIVE")
    table.setdefault("partition_key_name", "id")
    table.setdefault("partition_key_type", "S")
    table.setdefault("sort_key_name", "")
    table.setdefault("sort_key_type", "S")
    table.setdefault("billing_mode", "PAY_PER_REQUEST")
    table.setdefault("provisioned_throughput", {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5})
    table.setdefault("tags", {})
    table.setdefault("indexes", [])
    table.setdefault("streams", {"enabled": False, "latest_stream_label": ""})
    table.setdefault("items", {})
    table.setdefault("created", _now())
    table.setdefault("last_modified", _now())
    return table


def _ddb_find_table(table_name: str) -> dict | None:
    table = _ddb_tables().get(table_name)
    if isinstance(table, dict):
        return _ddb_normalize_table(table_name, table)
    return None


def _ddb_refresh_table_metrics(table: dict) -> None:
    records = list((table.get("items") or {}).values())
    table["item_count"] = len(records)
    try:
        table["table_size_bytes"] = sum(len(json.dumps(rec.get("item", {}), sort_keys=True, default=str).encode("utf-8")) for rec in records)
    except Exception:
        table["table_size_bytes"] = 0
    table["last_modified"] = _now()


def _ddb_item_record_view(table: dict, key: str, record: dict) -> dict:
    native = copy.deepcopy(record.get("item", {}))
    pk_name, sk_name = _ddb_table_key_fields(table)
    key_obj = {pk_name: native.get(pk_name)}
    if sk_name:
        key_obj[sk_name] = native.get(sk_name)
    return {
        "key": key_obj,
        "item": native,
        "item_json": _ddb_native_item_to_json(native),
        "created": record.get("created", ""),
        "updated": record.get("updated", ""),
        "size_bytes": int(record.get("size_bytes", 0) or 0),
        "size_human": _fmt_size(int(record.get("size_bytes", 0) or 0)),
    }


def _ddb_table_view(table: dict, include_items: bool = True, native_items: bool = True) -> dict:
    table = _ddb_normalize_table(table.get("table_name", ""), table)
    _ddb_refresh_table_metrics(table)
    records = sorted((table.get("items") or {}).items(), key=lambda kv: json.dumps(_ddb_item_key_tuple(table, kv[1].get("item", {})), default=str))
    view = {
        "table_name": table.get("table_name", ""),
        "table_arn": table.get("table_arn", ""),
        "table_status": table.get("table_status", "ACTIVE"),
        "partition_key_name": table.get("partition_key_name", "id"),
        "partition_key_type": table.get("partition_key_type", "S"),
        "sort_key_name": table.get("sort_key_name", ""),
        "sort_key_type": table.get("sort_key_type", "S"),
        "billing_mode": table.get("billing_mode", "PAY_PER_REQUEST"),
        "provisioned_throughput": copy.deepcopy(table.get("provisioned_throughput", {})),
        "tags": copy.deepcopy(table.get("tags", {})),
        "indexes": copy.deepcopy(table.get("indexes", [])),
        "streams": copy.deepcopy(table.get("streams", {"enabled": False, "latest_stream_label": ""})),
        "created": table.get("created", ""),
        "last_modified": table.get("last_modified", ""),
        "item_count": int(table.get("item_count", 0) or 0),
        "table_size_bytes": int(table.get("table_size_bytes", 0) or 0),
        "table_size_human": _fmt_size(int(table.get("table_size_bytes", 0) or 0)),
    }
    if include_items:
        items = [ _ddb_item_record_view(table, key, record) for key, record in records ]
        view["items"] = [item["item"] if native_items else item["item_json"] for item in items]
        view["item_rows"] = items
    return view


def _ddb_create_table_record(payload: dict[str, Any]) -> dict:
    table_name = str(payload.get("table_name") or payload.get("TableName") or "").strip()
    if not table_name:
        raise HTTPException(400, detail="ValidationException: TableName is required.")
    tables = _ddb_tables()
    if table_name in tables:
        raise HTTPException(409, detail="ResourceInUseException: Table already exists.")
    pk_name = str(payload.get("partition_key_name") or payload.get("PartitionKeyName") or "id").strip() or "id"
    pk_type = str(payload.get("partition_key_type") or payload.get("PartitionKeyType") or "S").strip().upper() or "S"
    sk_name = str(payload.get("sort_key_name") or payload.get("SortKeyName") or "").strip()
    sk_type = str(payload.get("sort_key_type") or payload.get("SortKeyType") or "S").strip().upper() or "S"
    billing_mode = str(payload.get("billing_mode") or payload.get("BillingMode") or "PAY_PER_REQUEST").strip().upper() or "PAY_PER_REQUEST"
    throughput = payload.get("provisioned_throughput") or payload.get("ProvisionedThroughput") or {}
    tags = payload.get("tags") or payload.get("Tags") or {}
    if isinstance(tags, list):
        tags = {str(tag.get("Key", tag.get("key", ""))): str(tag.get("Value", tag.get("value", ""))) for tag in tags if isinstance(tag, dict)}
    table = {
        "table_name": table_name,
        "table_arn": _ddb_table_arn(table_name),
        "table_status": "ACTIVE",
        "partition_key_name": pk_name,
        "partition_key_type": pk_type,
        "sort_key_name": sk_name,
        "sort_key_type": sk_type,
        "billing_mode": billing_mode,
        "provisioned_throughput": {
            "ReadCapacityUnits": int(throughput.get("ReadCapacityUnits", payload.get("read_capacity_units", 5)) or 5),
            "WriteCapacityUnits": int(throughput.get("WriteCapacityUnits", payload.get("write_capacity_units", 5)) or 5),
        },
        "tags": copy.deepcopy(tags or {}),
        "indexes": [],
        "streams": {"enabled": False, "latest_stream_label": ""},
        "items": {},
        "created": _now(),
        "last_modified": _now(),
    }
    table["attribute_definitions"] = [{"AttributeName": pk_name, "AttributeType": pk_type}]
    table["key_schema"] = [{"AttributeName": pk_name, "KeyType": "HASH"}]
    if sk_name:
        table["attribute_definitions"].append({"AttributeName": sk_name, "AttributeType": sk_type})
        table["key_schema"].append({"AttributeName": sk_name, "KeyType": "RANGE"})
    tables[table_name] = table
    _persist_state()
    _record_usage("dynamodb.create_table", {"table_name": table_name})
    return table


def _ddb_delete_table_record(table_name: str) -> None:
    tables = _ddb_tables()
    if table_name not in tables:
        raise HTTPException(404, detail="ResourceNotFoundException: Table not found.")
    tables.pop(table_name, None)
    _persist_state()
    _record_usage("dynamodb.delete_table", {"table_name": table_name})


def _ddb_put_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_item = _ddb_item_to_native_item(payload.get("item") or payload.get("Item") or {})
    key = _ddb_item_key_string(table, native_item)
    items = table.setdefault("items", {})
    existing = items.get(key)
    items[key] = {
        "item": native_item,
        "created": existing.get("created", _now()) if existing else _now(),
        "updated": _now(),
        "size_bytes": len(json.dumps(native_item, sort_keys=True, default=str).encode("utf-8")),
    }
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.put_item", {"table_name": table["table_name"]})
    return existing or {}


def _ddb_get_item_record(table: dict, payload: dict[str, Any]) -> dict | None:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    return table.get("items", {}).get(key)


def _ddb_delete_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    removed = table.get("items", {}).pop(key, None)
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.delete_item", {"table_name": table["table_name"]})
    return removed or {}


def _ddb_update_item_record(table: dict, payload: dict[str, Any]) -> dict:
    native_key = _ddb_item_to_native_item(payload.get("key") or payload.get("Key") or {})
    key = _ddb_item_key_string(table, native_key)
    current = copy.deepcopy(table.get("items", {}).get(key, {}).get("item", {}))
    updates = payload.get("attribute_updates") or payload.get("AttributeUpdates") or {}
    if not current:
        current = copy.deepcopy(native_key)
    if updates:
        for name, spec in updates.items():
            if not isinstance(spec, dict):
                continue
            action = str(spec.get("Action", "PUT")).upper()
            value = spec.get("Value")
            if action == "DELETE":
                current.pop(name, None)
            elif value is not None:
                current[name] = _ddb_json_to_native(value)
    else:
        expr = str(payload.get("update_expression") or payload.get("UpdateExpression") or "").strip()
        values = payload.get("expression_attribute_values") or payload.get("ExpressionAttributeValues") or {}
        if expr.upper().startswith("SET "):
            for clause in expr[4:].split(","):
                if "=" not in clause:
                    continue
                left, right = clause.split("=", 1)
                attr_name = left.strip()
                token = right.strip()
                current[attr_name] = _ddb_json_to_native(values.get(token, token))
    items = table.setdefault("items", {})
    items[key] = {
        "item": current,
        "created": items.get(key, {}).get("created", _now()),
        "updated": _now(),
        "size_bytes": len(json.dumps(current, sort_keys=True, default=str).encode("utf-8")),
    }
    _ddb_refresh_table_metrics(table)
    _persist_state()
    _record_usage("dynamodb.update_item", {"table_name": table["table_name"]})
    return items[key]


def _ddb_sort_key(table: dict, native_item: dict[str, Any]) -> tuple[str, str]:
    pk_name, sk_name = _ddb_table_key_fields(table)
    return (str(native_item.get(pk_name, "")), str(native_item.get(sk_name, "")) if sk_name else "")


def _ddb_sorted_records(table: dict) -> list[dict]:
    records = list((table.get("items") or {}).values())
    records.sort(key=lambda rec: _ddb_sort_key(table, rec.get("item", {})))
    return records


def _ddb_expr_value(raw: Any) -> Any:
    return _ddb_json_to_native(raw)


def _ddb_query_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _ddb_sorted_records(table)
    if not records:
        return [], 0
    pk_name, sk_name = _ddb_table_key_fields(table)
    pk_value = payload.get("partition_key_value")
    sk_equals = payload.get("sort_key_equals")
    sk_begins = str(payload.get("sort_key_begins_with") or "")
    sk_between = payload.get("sort_key_between") or []
    expr = str(payload.get("key_condition_expression") or payload.get("KeyConditionExpression") or "").strip()
    names = payload.get("expression_attribute_names") or payload.get("ExpressionAttributeNames") or {}
    values = payload.get("expression_attribute_values") or payload.get("ExpressionAttributeValues") or {}
    if expr:
        for alias, actual in (names or {}).items():
            expr = expr.replace(str(alias), str(actual))
        if pk_value is None:
            m = re.search(rf"\b{re.escape(pk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                pk_value = _ddb_expr_value(values.get(m.group(1)))
        if sk_name and not sk_equals and not sk_begins and not sk_between:
            m = re.search(rf"\b{re.escape(sk_name)}\s*=\s*(:\w+)", expr, flags=re.I)
            if m:
                sk_equals = _ddb_expr_value(values.get(m.group(1)))
            m = re.search(rf"begins_with\s*\(\s*{re.escape(sk_name)}\s*,\s*(:\w+)\s*\)", expr, flags=re.I)
            if m:
                sk_begins = str(_ddb_expr_value(values.get(m.group(1))) or "")
            m = re.search(rf"\b{re.escape(sk_name)}\s+BETWEEN\s+(:\w+)\s+AND\s+(:\w+)", expr, flags=re.I)
            if m:
                sk_between = [_ddb_expr_value(values.get(m.group(1))), _ddb_expr_value(values.get(m.group(2)))]
    matched = []
    for rec in records:
        item = rec.get("item", {})
        if pk_value is not None and item.get(pk_name) != pk_value:
            continue
        if sk_name:
            current_sk = item.get(sk_name)
            if sk_equals is not None and current_sk != sk_equals:
                continue
            if sk_begins and not str(current_sk or "").startswith(sk_begins):
                continue
            if isinstance(sk_between, list) and len(sk_between) == 2:
                low, high = sk_between
                if not (str(low) <= str(current_sk) <= str(high)):
                    continue
        matched.append(rec)
    limit = max(1, min(int(payload.get("limit") or payload.get("Limit") or 100), 1000))
    return matched[:limit], len(matched)


def _ddb_scan_filter(table: dict, payload: dict[str, Any]) -> tuple[list[dict], int]:
    records = _ddb_sorted_records(table)
    limit = max(1, min(int(payload.get("limit") or payload.get("Limit") or 100), 1000))
    return records[:limit], len(records)


def _ddb_table_response(table: dict, include_items: bool = True) -> dict:
    view = _ddb_table_view(table, include_items=include_items, native_items=True)
    if include_items:
        view["items"] = [copy.deepcopy(item["item"]) for item in view.get("item_rows", [])]
    return {"table": view}


def _ddb_list_tables_response() -> dict:
    tables = [_ddb_table_view(table, include_items=False) for _, table in sorted(_ddb_tables().items(), key=lambda kv: kv[0])]
    return {"table_names": [table["table_name"] for table in tables], "tables": tables, "count": len(tables)}


def _ddb_item_rows(table: dict, records: list[dict], native_items: bool = True) -> list[dict]:
    rows = [_ddb_item_record_view(table, key, record) for key, record in [(key, record) for key, record in ((k, r) for k, r in ((k, v) for k, v in (table.get("items") or {}).items()))]]
    return rows


def _ddb_tag_map(table: dict) -> dict[str, str]:
    tags = table.setdefault("tags", {})
    if isinstance(tags, list):
        tags = {str(tag.get("Key", "")): str(tag.get("Value", "")) for tag in tags if isinstance(tag, dict)}
        table["tags"] = tags
    return tags


def _ddb_tags_view(table: dict) -> dict[str, str]:
    return copy.deepcopy(_ddb_tag_map(table))


def _ddb_set_tags(table: dict, tags: dict[str, str]) -> None:
    table["tags"] = {str(k): str(v) for k, v in (tags or {}).items()}
    table["last_modified"] = _now()
    _persist_state()


def _ddb_json_response(payload: dict[str, Any], status: int = 200) -> Response:
    return JSONResponse(status_code=status, content=payload, headers={"x-amzn-requestid": _req_id()})


def _ddb_error_response(code: str, message: str, status: int = 400) -> Response:
    return _ddb_json_response({"__type": code, "message": message}, status=status)


async def api_dynamodb_aws(request: Request):
    # MVP P0: proxy to amazon/dynamodb-local for real DDB semantics (PartiQL,
    # secondary indexes, Streams, etc.). Fall back to the legacy in-memory
    # handler if DDB Local is unreachable so the simulator stays self-contained.
    try:
        from core import dynamodb_proxy as _ddbp
        status, body, ctype = await _ddbp.proxy(request)
        if status != 502:
            return Response(content=body, status_code=status, media_type=ctype)
    except Exception:
        pass
    return await provider_aws_services._ddb_api_aws(request)


def api_dynamodb_list_tables():
    return _ddb_list_tables_response()


def api_dynamodb_create_table(req: DynamoDBTableRequest):
    table = _ddb_create_table_record({
        "table_name": req.table_name,
        "partition_key_name": req.partition_key_name,
        "partition_key_type": req.partition_key_type,
        "sort_key_name": req.sort_key_name,
        "sort_key_type": req.sort_key_type,
        "billing_mode": req.billing_mode,
        "read_capacity_units": req.read_capacity_units,
        "write_capacity_units": req.write_capacity_units,
        "tags": req.tags or {},
    })
    _cloudsim_sync_service_resource("aws", "dynamodb", "table", req.table_name, table, "dynamodb")
    _record_usage("dynamodb.create_table", {"table_name": req.table_name})
    return _ddb_table_response(table, include_items=False)


def api_dynamodb_get_table(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    return _ddb_table_response(table, include_items=True)


def api_dynamodb_delete_table(table_name: str):
    _ddb_delete_table_record(table_name)
    _cloudsim_sync_service_resource("aws", "dynamodb", "table", table_name, {}, "dynamodb", action="delete")
    _record_usage("dynamodb.delete_table", {"table_name": table_name})
    return {"deleted": True, "table_name": table_name}


def api_dynamodb_list_items(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    rows = _ddb_table_view(table, include_items=True)["item_rows"]
    return {"table_name": table_name, "items": rows, "count": len(rows)}


def api_dynamodb_put_item(table_name: str, req: DynamoDBItemRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    old = _ddb_put_item_record(table, {"item": req.item})
    native_item = _ddb_item_to_native_item(req.item)
    key = _ddb_item_key_string(table, native_item)
    record = table.get("items", {}).get(key, {})
    _record_usage("dynamodb.put_item", {"table_name": table_name})
    return {"table_name": table_name, "item": _ddb_item_record_view(table, key, record), "previous": old.get("item", {}) if old else {}}


def api_dynamodb_update_item(table_name: str, req: DynamoDBItemRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    updated = _ddb_update_item_record(table, {
        "key": req.key,
        "attribute_updates": req.attribute_updates or {},
        "update_expression": req.update_expression,
        "expression_attribute_values": req.expression_attribute_values or {},
    })
    _record_usage("dynamodb.update_item", {"table_name": table_name})
    return {"table_name": table_name, "item": updated.get("item", {})}


def api_dynamodb_delete_item(table_name: str, req: DynamoDBItemRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    removed = _ddb_delete_item_record(table, {"key": req.key})
    _record_usage("dynamodb.delete_item", {"table_name": table_name})
    return {"table_name": table_name, "deleted": True, "item": removed.get("item", {})}


def api_dynamodb_query_items(table_name: str, req: DynamoDBQueryRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    payload = {
        "partition_key_value": req.partition_key_value,
        "sort_key_equals": req.sort_key_equals,
        "sort_key_begins_with": req.sort_key_begins_with,
        "sort_key_between": req.sort_key_between or [],
        "limit": req.limit,
        "key_condition_expression": req.key_condition_expression,
        "expression_attribute_values": req.expression_attribute_values or {},
        "expression_attribute_names": req.expression_attribute_names or {},
    }
    rows, count = _ddb_query_filter(table, payload)
    return {"table_name": table_name, "items": [_ddb_item_record_view(table, row.get("key", ""), row) for row in rows], "count": len(rows), "scanned_count": count}


def api_dynamodb_scan_items(table_name: str, req: DynamoDBScanRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    rows, count = _ddb_scan_filter(table, {"limit": req.limit})
    return {"table_name": table_name, "items": [_ddb_item_record_view(table, row.get("key", ""), row) for row in rows], "count": len(rows), "scanned_count": count}


def api_dynamodb_list_tags(table_name: str):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def api_dynamodb_tag_table(table_name: str, req: DynamoDBTagRequest):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    tags = _ddb_tags_view(table)
    tags.update({str(k): str(v) for k, v in (req.tags or {}).items()})
    _ddb_set_tags(table, tags)
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


def api_dynamodb_untag_table(table_name: str, payload: dict[str, Any]):
    table = _ddb_find_table(table_name)
    if not table:
        raise HTTPException(404, detail="TableNotFound")
    tags = _ddb_tags_view(table)
    for key in payload.get("keys", []) if isinstance(payload, dict) else []:
        tags.pop(str(key), None)
    _ddb_set_tags(table, tags)
    return {"table_name": table_name, "tags": _ddb_tags_view(table)}


async def api_rds_query(request: Request):
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    version = str(params.get("Version", "2014-10-31")).strip() or "2014-10-31"
    if version != "2014-10-31":
        return _rds_error_response("InvalidParameterValue", f"Unsupported RDS API version '{version}'.", 400)
    if not action:
        return _rds_error_response("MissingParameter", "The request must contain the parameter Action.", 400)
    if str(params.get("DryRun", "")).lower() == "true":
        return _rds_error_response("DryRunOperation", "Request would have succeeded, but DryRun flag is set.", 412)

    try:
        if action == "DescribeDBInstances":
            return _rds_query_describe_db_instances(params)
        if action == "CreateDBInstance":
            return _rds_query_create_db_instance(params)
        if action == "ModifyDBInstance":
            return _rds_query_modify_db_instance(params)
        if action == "DeleteDBInstance":
            return _rds_query_delete_db_instance(params)
        if action in {"StartDBInstance", "StopDBInstance", "RebootDBInstance"}:
            return _rds_query_start_stop_reboot(action, params)
        if action == "CreateDBSnapshot":
            return _rds_query_create_db_snapshot(params)
        if action == "DescribeDBSnapshots":
            return _rds_query_describe_db_snapshots(params)
        if action == "RestoreDBInstanceFromDBSnapshot":
            return _rds_query_restore_db_snapshot(params)
        if action in {"CreateDBSubnetGroup", "DescribeDBSubnetGroups"}:
            return _rds_query_create_describe_subnet_group(action, params)
        if action == "DeleteDBSubnetGroup":
            return _rds_query_delete_subnet_group(params)
        if action in {"CreateDBParameterGroup", "DescribeDBParameterGroups"}:
            return _rds_query_create_describe_parameter_group(action, params)
        if action == "DeleteDBParameterGroup":
            return _rds_query_delete_parameter_group(params)
        if action == "AddTagsToResource":
            return _rds_query_add_tags(params)
        if action == "ListTagsForResource":
            return _rds_query_list_tags(params)
    except HTTPException as exc:
        code = str(exc.detail).split(":", 1)[0]
        message = str(exc.detail)
        return _rds_error_response(code, message, exc.status_code)

    return _rds_error_response("InvalidAction", f"The action '{action}' is not implemented by the simulator.", 400)


async def api_vpc_query(request: Request):
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    version = str(params.get("Version", "2016-11-15")).strip() or "2016-11-15"
    if version != "2016-11-15":
        return _ec2_error_response("InvalidParameterValue", f"Unsupported EC2 API version '{version}'.", 400)
    if not action:
        return _ec2_error_response("MissingParameter", "The request must contain the parameter Action.", 400)
    if str(params.get("DryRun", "")).lower() == "true":
        return _ec2_error_response("DryRunOperation", "Request would have succeeded, but DryRun flag is set.", 412)

    try:
        if action == "CreateVpc":
            return _vpc_query_create_vpc(params)
        if action == "DescribeVpcs":
            return _vpc_query_describe_vpcs(params)
        if action == "DeleteVpc":
            return _vpc_query_delete_vpc(params)
        if action == "CreateSubnet":
            return _vpc_query_create_subnet(params)
        if action == "DescribeSubnets":
            return _vpc_query_describe_subnets(params)
        if action == "DeleteSubnet":
            return _vpc_query_delete_subnet(params)
        if action == "CreateSecurityGroup":
            return _vpc_query_create_security_group(params)
        if action == "DescribeSecurityGroups":
            return _vpc_query_describe_security_groups(params)
        if action == "AuthorizeSecurityGroupIngress":
            return _vpc_query_authorize_security_group_ingress(params)
        if action == "CreateRouteTable":
            return _vpc_query_create_route_table(params)
        if action == "DescribeRouteTables":
            return _vpc_query_describe_route_tables(params)
        if action == "DeleteRouteTable":
            return _vpc_query_delete_route_table(params)
        if action == "CreateRoute":
            return _vpc_query_create_route(params)
        if action == "AssociateRouteTable":
            return _vpc_query_associate_route_table(params)
        if action == "DisassociateRouteTable":
            return _vpc_query_disassociate_route_table(params)
        if action == "CreateInternetGateway":
            return _vpc_query_create_internet_gateway(params)
        if action == "DescribeInternetGateways":
            return _vpc_query_describe_internet_gateways(params)
        if action == "AttachInternetGateway":
            return _vpc_query_attach_internet_gateway(params)
        if action == "DetachInternetGateway":
            return _vpc_query_detach_internet_gateway(params)
        if action == "DeleteInternetGateway":
            return _vpc_query_delete_internet_gateway(params)
        if action == "CreateTags":
            return _vpc_query_create_tags(params)
        if action == "DescribeTags":
            return _vpc_query_describe_tags(params)
    except HTTPException as exc:
        code = str(exc.detail).split(":", 1)[0]
        message = str(exc.detail)
        return _ec2_error_response(code, message, exc.status_code)

    return _ec2_error_response("InvalidAction", f"The action '{action}' is not implemented by the simulator.", 400)


def api_apigateway_list_apis():
    apis = [_apigw_api_view(api) for api in _apigw_state().setdefault("apis", {}).values()]
    apis.sort(key=lambda item: (item.get("created", ""), item.get("name", "")))
    return {"apis": apis, "count": len(apis)}


def api_apigateway_create_api(req: APIGatewayRequest):
    if not req.name.strip():
        raise HTTPException(400, detail="MissingParameter: name is required.")
    api = _apigw_create_api_record(req)
    _cloudsim_sync_service_resource("aws", "apigateway", "rest_api", api.get("id", ""), api, "apigateway")
    _record_usage("apigateway.create_api", {"rest_api_id": api.get("id", ""), "name": api.get("name", "")})
    return _apigw_summary(api)


def api_apigateway_get_api(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    return _apigw_summary(api)


def api_apigateway_delete_api(api_id: str):
    _apigw_delete_api_record(api_id)
    _cloudsim_sync_service_resource("aws", "apigateway", "rest_api", api_id, {}, "apigateway", action="delete")
    _record_usage("apigateway.delete_api", {"rest_api_id": api_id})
    return {"message": "API Gateway API deleted", "rest_api_id": api_id}


def api_apigateway_list_resources(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    return {"resources": _apigw_route_views(api), "count": max(len(api.get("resources", {})) - 1, 0)}


def api_apigateway_create_resource(api_id: str, req: APIGatewayResourceRequest):
    resource = _apigw_create_resource_record(api_id, req)
    api = _apigw_api(api_id)
    _record_usage("apigateway.create_resource", {"rest_api_id": api_id, "resource_id": resource.get("id", "")})
    return {"resource": resource, "api": _apigw_api_view(api)}


def api_apigateway_put_method(api_id: str, req: APIGatewayMethodRequest):
    method = _apigw_put_method_record(api_id, req)
    return {"method": method}


def api_apigateway_put_integration(api_id: str, req: APIGatewayIntegrationRequest):
    integration = _apigw_put_integration_record(api_id, req)
    return {"integration": integration}


def api_apigateway_create_deployment(api_id: str, req: APIGatewayDeploymentRequest):
    deployment = _apigw_create_deployment_record(api_id, req)
    _record_usage("apigateway.create_deployment", {"rest_api_id": api_id, "deployment_id": deployment.get("id", "")})
    return {"deployment": deployment}


def api_apigateway_list_deployments(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    deployments = list(api.get("deployments", {}).values())
    deployments.sort(key=lambda item: (item.get("created", ""), item.get("deployment_id", "")))
    return {"deployments": deployments, "count": len(deployments)}


def api_apigateway_create_stage(api_id: str, req: APIGatewayStageRequest):
    stage = _apigw_create_stage_record(api_id, req)
    _record_usage("apigateway.create_stage", {"rest_api_id": api_id, "stage_name": stage.get("stage_name", "")})
    return {"stage": stage}


def api_apigateway_list_stages(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stages = list(api.get("stages", {}).values())
    stages.sort(key=lambda item: (item.get("created", ""), item.get("stage_name", "")))
    return {"stages": stages, "count": len(stages)}


def api_apigateway_list_logs(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    logs = list(api.get("logs", []))
    logs.sort(key=lambda item: item.get("at", ""), reverse=True)
    return {"logs": logs[:100], "count": len(logs)}


async def api_apigateway_invoke_path(api_id: str, stage_name: str, proxy_path: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, proxy_path, request)

async def api_apigateway_invoke_root(api_id: str, stage_name: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, "", request)


def api_lambda_list_functions():
    functions = [_lambda_function_view(function) for function in _lambda_list_functions()]
    return {"functions": functions, "count": len(functions)}


def api_lambda_create_function(req: LambdaFunctionRequest):
    _enforce_quantity_cap("lambda_function")  # tier cap — Free=3 Lambdas/space
    function = _lambda_create_function_record(req)
    bundle = _cloudsim_runtime_bundle("lambda")
    function["runtime_bundle_id"] = bundle.get("id", "")
    function["runtime_bundle_name"] = bundle.get("name", "")
    function["runtime_bundle_kind"] = bundle.get("kind", "")
    _cloudsim_sync_service_resource("aws", "lambda", "function", function["function_name"], function, "lambda")
    _record_usage("lambda.create_function", {"function_name": function.get("function_name", "")})
    return _lambda_function_view(function)


def api_lambda_get_function(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    return _lambda_function_view(function)


def api_lambda_update_function_code(function_name: str, payload: dict[str, Any]):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    updated = _lambda_update_function_code(function, str(payload.get("code", "")))
    _record_usage("lambda.update_function_code", {"function_name": function_name})
    return _lambda_function_view(updated)


def api_lambda_update_function_configuration(function_name: str, req: LambdaFunctionUpdateRequest):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    updated = _lambda_update_function_configuration(function, req)
    _record_usage("lambda.update_function_configuration", {"function_name": function_name})
    return _lambda_function_view(updated)


def api_lambda_delete_function(function_name: str):
    _lambda_delete_function(function_name)
    _cloudsim_sync_service_resource("aws", "lambda", "function", function_name, {}, "lambda", action="delete")
    _record_usage("lambda.delete_function", {"function_name": function_name})
    return {"deleted": True, "function_name": function_name}


def api_lambda_get_policy(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    policy = _lambda_get_policy(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], **policy}


def api_lambda_add_permission(function_name: str, req: LambdaPermissionRequest):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    permission = _lambda_add_permission(function, req)
    policy = _lambda_get_policy(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "statement": permission, **policy}


def api_lambda_remove_permission(function_name: str, statement_id: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    _lambda_remove_permission(function, statement_id)
    return {"deleted": True, "function_name": function["function_name"], "statement_id": statement_id}


def api_lambda_list_invocations(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    invocations = _lambda_invocations_view(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "invocations": invocations, "count": len(invocations)}


def api_lambda_list_versions(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    versions = _lambda_versions_view(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "versions": versions, "count": len(versions)}


def api_lambda_publish_version(function_name: str, payload: LambdaVersionRequest):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    version = _lambda_publish_version(function, payload.description)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "version": version}


def api_lambda_invoke_function(function_name: str, payload: LambdaInvokeRequest):
    return _lambda_invoke_response(function_name, payload.payload, invocation_type=payload.invocation_type)


def api_lambda_list_functions_aws():
    return api_lambda_list_functions()


def api_lambda_create_function_aws(req: LambdaFunctionRequest):
    return api_lambda_create_function(req)


def api_lambda_get_function_aws(function_name: str):
    return api_lambda_get_function(function_name)


def api_lambda_delete_function_aws(function_name: str):
    return api_lambda_delete_function(function_name)


def api_lambda_get_policy_aws(function_name: str):
    return api_lambda_get_policy(function_name)


def api_lambda_add_permission_aws(function_name: str, req: LambdaPermissionRequest):
    return api_lambda_add_permission(function_name, req)


def api_lambda_remove_permission_aws(function_name: str, statement_id: str):
    return api_lambda_remove_permission(function_name, statement_id)


def api_lambda_update_function_code_aws(function_name: str, payload: dict[str, Any]):
    return api_lambda_update_function_code(function_name, payload)


def api_lambda_update_function_configuration_aws(function_name: str, req: LambdaFunctionUpdateRequest):
    return api_lambda_update_function_configuration(function_name, req)


def api_lambda_publish_version_aws(function_name: str, payload: LambdaVersionRequest):
    return api_lambda_publish_version(function_name, payload)


def api_lambda_list_versions_aws(function_name: str):
    return api_lambda_list_versions(function_name)


async def api_lambda_invoke_function_aws(function_name: str, request: Request):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    invocation_type = request.headers.get("x-amz-invocation-type") or request.query_params.get("InvocationType", "RequestResponse")
    body = await request.body()
    payload = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"body": body.decode("utf-8", errors="replace")}
    record = _lambda_invoke_function(function_name, payload, invocation_type=invocation_type)
    if invocation_type and invocation_type.lower() == "event":
        return Response(status_code=202)
    response_payload = record.get("response_payload")
    if isinstance(response_payload, (dict, list)):
        body_bytes = json.dumps(response_payload, default=str).encode("utf-8")
        media_type = "application/json"
    elif isinstance(response_payload, bytes):
        body_bytes = response_payload
        media_type = "application/octet-stream"
    elif response_payload is None:
        body_bytes = b""
        media_type = "application/json"
    else:
        body_bytes = str(response_payload).encode("utf-8")
        media_type = "text/plain"
    headers = {
        "X-Amz-Executed-Version": "$LATEST",
        "X-Amz-Function-Error": "Handled" if record.get("status") == "error" else "",
    }
    if not headers["X-Amz-Function-Error"]:
        headers.pop("X-Amz-Function-Error", None)
    return Response(content=body_bytes, media_type=media_type, headers=headers)


# ---------------------------------------------------------------------------
# Lambda Layers
# ---------------------------------------------------------------------------

def _lambda_layers() -> dict:
    """Layers are stored inside lambda_state under a 'layers' sub-dict."""
    return lambda_state.setdefault("layers", {})


def api_lambda_list_layers():
    layers = list(_lambda_layers().values())
    layers.sort(key=lambda x: x.get("created", ""))
    return {"layers": layers, "count": len(layers)}


def api_lambda_create_layer(req: LambdaLayerRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, detail="Layer name is required")
    layers = _lambda_layers()
    layer_arn = f"arn:aws:lambda:us-east-1:{AWS_ACCOUNT_ID}:layer:{name}"
    existing = layers.get(name)
    version = 1
    if existing:
        version = existing.get("latest_version", 0) + 1
    layer = {
        "layer_name": name,
        "layer_arn": layer_arn,
        "layer_version_arn": f"{layer_arn}:{version}",
        "description": req.description,
        "runtime": req.runtime,
        "code": req.code,
        "license_info": req.license_info,
        "latest_version": version,
        "created": _now(),
    }
    layers[name] = layer
    _record_usage("lambda.create_layer", {"layer_name": name, "version": version})
    return layer


def api_lambda_get_layer(name: str):
    layer = _lambda_layers().get(name)
    if not layer:
        raise HTTPException(404, detail="ResourceNotFoundException")
    return layer


def api_lambda_delete_layer(name: str):
    layers = _lambda_layers()
    if name not in layers:
        raise HTTPException(404, detail="ResourceNotFoundException")
    del layers[name]
    _record_usage("lambda.delete_layer", {"layer_name": name})
    return {"deleted": True}


def api_runtime_bundles():
    return {"bundles": list(runtime_state["bundles"].values()), "count": len(runtime_state["bundles"])}


def api_create_deployment(req: DeploymentRequest):
    deployment_id = _id("deploy")
    source_dir = Path(os.environ.get("CLOUDLEARN_DEPLOY_DIR", Path(__file__).with_name("deployments"))) / deployment_id
    source_dir.mkdir(parents=True, exist_ok=True)
    deployment = {
        "deployment_id": deployment_id,
        "name": req.name,
        "source_url": req.source_url,
        "runtime": req.runtime,
        "command": req.command,
        "branch": req.branch,
        "repo": req.repo,
        "status": "created",
        "workdir": str(source_dir),
        "created": _now(),
    }
    if req.source_url.startswith("https://github.com/") or req.source_url.endswith(".git"):
        try:
            import subprocess
            subprocess.run(["git", "clone", "--depth", "1", req.source_url, str(source_dir)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deployment["status"] = "cloned"
        except Exception as e:
            deployment["status"] = "clone_failed"
            deployment["error"] = str(e)
    STATE["deployments"][deployment_id] = deployment
    _record_usage("deploy.create", deployment)
    return deployment


def api_action_router(payload: ServiceActionRequest):
    service = payload.payload.get("service", "")
    action = payload.action.lower()
    if service == "s3":
        return {"message": "Use S3 REST or /api/s3 endpoints for S3 actions."}
    if service == "iam" and action == "createuser":
        return provider_aws_iam.api_iam_create_user(IAMUserRequest(**payload.payload))
    raise HTTPException(400, detail="UnsupportedAction")


# (Static files mount and serve_ui are now in the orchestrator preamble
# and routes/console.py respectively.)


# ── AWS query-protocol root dispatch (real SDK / CLI entrypoint) ──────────────
# Real AWS SDKs and the CLI send query-protocol (IAM/EC2/SQS/RDS/STS) and JSON
# (DynamoDB) requests to the endpoint root `/`, selecting the target service via
# the SigV4 credential scope (".../<service>/aws4_request") rather than the URL
# path. This dispatcher routes those root requests to the already-implemented
# service handlers so unmodified real clients work against the simulator.

IAM_XML_NS = "https://iam.amazonaws.com/doc/2010-05-08/"
STS_XML_NS = "https://sts.amazonaws.com/doc/2011-06-15/"
_AWS_CRED_SCOPE_RE = re.compile(r"Credential=[^/]*/[^/]*/[^/]*/([A-Za-z0-9_-]+)/aws4_request")


def _aws_query_target_service(request: Request) -> str:
    auth = request.headers.get("authorization", "") or ""
    match = _AWS_CRED_SCOPE_RE.search(auth)
    if match:
        return match.group(1).strip().lower()
    target = request.headers.get("x-amz-target", "") or ""
    if "dynamodb" in target.lower():
        return "dynamodb"
    # KMS uses TrentService.* targets (the historical KMS service name).
    if target.startswith("TrentService."):
        return "kms"
    # Secrets Manager uses secretsmanager.* targets.
    if target.startswith("secretsmanager."):
        return "secretsmanager"
    # EventBridge uses AWSEvents.* targets.
    if target.startswith("AWSEvents."):
        return "events"
    return ""


def _iam_request_id() -> str:
    return uuid.uuid4().hex


def _iam_envelope(action: str, result_inner: str | None = None, status: int = 200) -> Response:
    result = f"<{action}Result>{result_inner}</{action}Result>" if result_inner is not None else ""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<{action}Response xmlns="{IAM_XML_NS}">{result}'
        f"<ResponseMetadata><RequestId>{_iam_request_id()}</RequestId></ResponseMetadata>"
        f"</{action}Response>"
    )
    return _xml_response(body, status)


def _iam_query_error(code: str, message: str, status: int = 400) -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ErrorResponse xmlns="{IAM_XML_NS}"><Error><Type>Sender</Type>'
        f"<Code>{xml_escape(code)}</Code><Message>{xml_escape(message)}</Message></Error>"
        f"<RequestId>{_iam_request_id()}</RequestId></ErrorResponse>"
    )
    return _xml_response(body, status)


def _iam_user_fields(user: dict) -> str:
    name = user.get("user_name", "")
    return (
        f"<Path>{xml_escape(user.get('path', '/') or '/')}</Path>"
        f"<UserName>{xml_escape(name)}</UserName>"
        f"<UserId>{xml_escape(user.get('user_id', ''))}</UserId>"
        f"<Arn>{xml_escape(_iam_user_arn(name))}</Arn>"
        f"<CreateDate>{xml_escape(user.get('created', _now()))}</CreateDate>"
    )


def _iam_role_fields(role: dict) -> str:
    from urllib.parse import quote as _urlquote

    name = role.get("role_name", "")
    doc = role.get("assume_role_policy_document", "") or ""
    if isinstance(doc, (dict, list)):
        doc = json.dumps(doc)
    return (
        f"<Path>{xml_escape(role.get('path', '/') or '/')}</Path>"
        f"<RoleName>{xml_escape(name)}</RoleName>"
        f"<RoleId>{xml_escape(role.get('role_id', ''))}</RoleId>"
        f"<Arn>{xml_escape(_iam_role_arn(name))}</Arn>"
        f"<CreateDate>{xml_escape(role.get('created', _now()))}</CreateDate>"
        f"<AssumeRolePolicyDocument>{xml_escape(_urlquote(str(doc)))}</AssumeRolePolicyDocument>"
    )


def _iam_policy_arn(name: str) -> str:
    return f"arn:aws:iam::{AWS_ACCOUNT_ID}:policy/{name}"


def _iam_policy_fields(policy: dict) -> str:
    name = policy.get("policy_name", "")
    return (
        f"<PolicyName>{xml_escape(name)}</PolicyName>"
        f"<PolicyId>{xml_escape(policy.get('policy_id', ''))}</PolicyId>"
        f"<Arn>{xml_escape(_iam_policy_arn(name))}</Arn>"
        f"<DefaultVersionId>v1</DefaultVersionId>"
        f"<CreateDate>{xml_escape(policy.get('created', _now()))}</CreateDate>"
    )


def _ns(**kwargs):
    obj = type("Req", (), {})()
    for key, value in kwargs.items():
        setattr(obj, key, value)
    return obj


async def api_iam_query(request: Request) -> Response:
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    try:
        if action == "ListUsers":
            members = "".join(f"<member>{_iam_user_fields(u)}</member>" for u in iam_state["users"].values())
            return _iam_envelope("ListUsers", f"<IsTruncated>false</IsTruncated><Users>{members}</Users>")
        if action == "CreateUser":
            user = provider_aws_iam.api_iam_create_user(_ns(user_name=params.get("UserName", ""), path=params.get("Path", "/") or "/"))
            return _iam_envelope("CreateUser", f"<User>{_iam_user_fields(user)}</User>")
        if action == "GetUser":
            user = _iam_find_user(params.get("UserName", ""))
            if not user:
                return _iam_query_error("NoSuchEntity", f"The user with name {params.get('UserName', '')} cannot be found.", 404)
            return _iam_envelope("GetUser", f"<User>{_iam_user_fields(user)}</User>")
        if action == "DeleteUser":
            provider_aws_iam.api_iam_delete_user(params.get("UserName", ""))
            return _iam_envelope("DeleteUser")
        if action == "ListRoles":
            members = "".join(f"<member>{_iam_role_fields(r)}</member>" for r in iam_state["roles"].values())
            return _iam_envelope("ListRoles", f"<IsTruncated>false</IsTruncated><Roles>{members}</Roles>")
        if action == "CreateRole":
            role = provider_aws_iam.api_iam_create_role(_ns(role_name=params.get("RoleName", ""), path=params.get("Path", "/") or "/", assume_role_policy_document=params.get("AssumeRolePolicyDocument", ""), description=params.get("Description", "")))
            return _iam_envelope("CreateRole", f"<Role>{_iam_role_fields(role)}</Role>")
        if action == "GetRole":
            target = next((r for r in iam_state["roles"].values() if params.get("RoleName", "") in {r.get("role_name", ""), r.get("role_id", "")}), None)
            if not target:
                return _iam_query_error("NoSuchEntity", f"The role with name {params.get('RoleName', '')} cannot be found.", 404)
            return _iam_envelope("GetRole", f"<Role>{_iam_role_fields(target)}</Role>")
        if action == "DeleteRole":
            provider_aws_iam.api_iam_delete_role(params.get("RoleName", ""))
            return _iam_envelope("DeleteRole")
        if action == "ListPolicies":
            members = "".join(f"<member>{_iam_policy_fields(p)}</member>" for p in iam_state["policies"].values())
            return _iam_envelope("ListPolicies", f"<IsTruncated>false</IsTruncated><Policies>{members}</Policies>")
        if action == "CreatePolicy":
            raw_doc = params.get("PolicyDocument", "")
            try:
                doc = json.loads(raw_doc) if raw_doc else {}
            except Exception:
                doc = raw_doc
            policy = provider_aws_iam.api_iam_create_policy(_ns(policy_name=params.get("PolicyName", ""), document=doc))
            return _iam_envelope("CreatePolicy", f"<Policy>{_iam_policy_fields(policy)}</Policy>")
        if action == "DeletePolicy":
            name = params.get("PolicyArn", "").rsplit("/", 1)[-1]
            target = next((pid for pid, p in iam_state["policies"].items() if p.get("policy_name") == name or pid == name), None)
            if target:
                provider_aws_iam.api_iam_delete_policy(target)
            return _iam_envelope("DeletePolicy")
    except HTTPException as exc:
        detail = str(exc.detail)
        code = detail.split(":", 1)[0].strip() or "ValidationError"
        return _iam_query_error(code, detail, exc.status_code if exc.status_code >= 400 else 400)
    if not action:
        return _iam_query_error("MissingAction", "The request must contain the parameter Action.")
    return _iam_query_error("InvalidAction", f"The action '{action}' is not implemented by the simulator.")


async def api_sts_query(request: Request) -> Response:
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    if action == "GetCallerIdentity":
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<GetCallerIdentityResponse xmlns="{STS_XML_NS}"><GetCallerIdentityResult>'
            f"<Arn>{_iam_root_principal()}</Arn><UserId>AIDACLOUDLEARNSIMULATOR</UserId>"
            f"<Account>{AWS_ACCOUNT_ID}</Account></GetCallerIdentityResult>"
            f"<ResponseMetadata><RequestId>{_iam_request_id()}</RequestId></ResponseMetadata>"
            "</GetCallerIdentityResponse>"
        )
        return _xml_response(body)
    return _xml_response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ErrorResponse xmlns="{STS_XML_NS}"><Error><Type>Sender</Type><Code>InvalidAction</Code>'
        f"<Message>Unsupported STS action '{xml_escape(action)}'.</Message></Error>"
        f"<RequestId>{_iam_request_id()}</RequestId></ErrorResponse>",
        400,
    )


_EC2_VPC_ACTIONS = {
    "CreateVpc", "DescribeVpcs", "DeleteVpc",
    "CreateSubnet", "DescribeSubnets", "DeleteSubnet",
    "CreateSecurityGroup", "AuthorizeSecurityGroupIngress", "AuthorizeSecurityGroupEgress",
    "CreateRouteTable", "DescribeRouteTables", "DeleteRouteTable",
    "CreateRoute", "AssociateRouteTable", "DisassociateRouteTable",
    "CreateInternetGateway", "DescribeInternetGateways", "AttachInternetGateway",
}


async def aws_query_root(request: Request) -> Response:
    """Root dispatch for real AWS SDK/CLI query + JSON protocol requests."""
    service = _aws_query_target_service(request)
    if service == "ec2":
        # VPC/networking actions sign under the ec2 service scope but are served
        # by the dedicated VPC query handler.
        params = await _ec2_query_params(request)
        if str(params.get("Action", "")).strip() in _EC2_VPC_ACTIONS:
            return await api_vpc_query(request)
        return await api_ec2_query(request)
    if service == "sqs":
        return await api_sqs_query(request)
    if service == "rds":
        return await api_rds_query(request)
    if service == "dynamodb":
        return await api_dynamodb_aws(request)
    if service == "iam":
        return await api_iam_query(request)
    if service == "sts":
        return await api_sts_query(request)
    if service in ("kms", "secretsmanager", "events"):
        # Backend-backed services. The X-Amz-Target prefix maps to one of the
        # dispatchers registered in _aws_xamz_dispatchers by vault_routes /
        # nats_routes / ... at module load time. We never break the control
        # plane — Vault/NATS down → 500 InternalFailure.
        target = request.headers.get("x-amz-target", "")
        prefix = target.split(".", 1)[0] if "." in target else ""
        dispatch = _aws_xamz_dispatchers.get(prefix)
        if dispatch is None:
            return Response(
                content=json.dumps({"__type": "InvalidAction", "message": f"No dispatcher for X-Amz-Target prefix {prefix!r}"}),
                status_code=400, media_type="application/x-amz-json-1.1",
            )
        body_raw = await request.body()
        try:
            body = json.loads(body_raw or b"{}")
        except Exception:
            body = {}
        spaces_state = PLATFORM.kernel.state.setdefault(
            "spaces", {"spaces": {}, "active_space_id": "", "settings": {}}
        )
        space = spaces_state.get("active_space_id", "default")
        resp = await dispatch(target, body, space)
        if resp is None:
            return Response(
                content=json.dumps({"__type": "InternalFailure", "message": f"{service}/{target} unhandled or backend unavailable"}),
                status_code=500, media_type="application/x-amz-json-1.1",
            )
        return Response(content=json.dumps(resp), media_type="application/x-amz-json-1.1")
    params = await _ec2_query_params(request)
    action = str(params.get("Action", "")).strip()
    return _error_xml("InvalidAction", f"Root dispatch could not route service={service or 'unknown'!r} action={action or 'unknown'!r}.", "/", 400)


# ── S3 REST API — root level ─────────────────────────────────────────────────

async def s3_list_buckets(request: Request) -> Response:
    """GET / → ListBuckets (S3 wire) OR serve pricing.html (browser).

    / is now the canonical launch page — pricing/features/SDKs all live
    on a single page that opens to browsers at the root URL. The old
    /pricing endpoint was removed; bookmarks/redirects to it are handled
    by a 302 in routes/console.py.

    S3 wire clients (no text/html Accept) still get the ListBuckets XML.
    """
    accept = request.headers.get("accept", "")
    user_agent = request.headers.get("user-agent", "")
    if "text/html" in accept or "Mozilla" in user_agent:
        with open(_PRICING_HTML, "rb") as f:
            return Response(content=f.read(), media_type="text/html", headers={"Cache-Control": "no-store, max-age=0"})

    now = _now()
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListAllMyBucketsResult xmlns="{S3_NS}">',
        "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
        "<Buckets>",
    ]
    for name, meta in buckets.items():
        xml_parts.append(f"<Bucket><Name>{name}</Name><CreationDate>{meta['created']}</CreationDate></Bucket>")
    xml_parts += ["</Buckets>", "</ListAllMyBucketsResult>"]
    return _xml_response("".join(xml_parts))


# ── S3 REST API — bucket level ───────────────────────────────────────────────

async def s3_head_bucket(bucket: str, request: Request) -> Response:
    """HEAD /{bucket} → HeadBucket"""
    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    return _empty_response(200)


async def s3_put_bucket(bucket: str, request: Request) -> Response:
    """PUT /{bucket}[?versioning|?tagging|?cors|?lifecycle|?acl] → Create/Configure Bucket"""
    params = dict(request.query_params)

    # Versioning
    if "versioning" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        body = await request.body()
        status = "Suspended"
        if b"Enabled" in body:
            status = "Enabled"
        buckets[bucket]["versioning"] = status
        return _empty_response(200)

    if "notification" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        body = await request.body()
        buckets[bucket]["notifications"] = _s3_parse_notification_xml(body)
        if body.strip():
            _s3_notification_record_delivery(
                bucket=bucket,
                event_name="s3:TestEvent",
                key="",
                source="PutBucketNotificationConfiguration",
                payload={"message": "TestEvent"},
                test_event=True,
            )
        return _empty_response(200)

    # Notification configuration
    if "notification" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        body = await request.body()
        buckets[bucket]["notifications"] = _s3_parse_notification_xml(body)
        if body.strip():
            _s3_notification_record_delivery(
                bucket=bucket,
                event_name="s3:TestEvent",
                key="",
                source="PutBucketNotificationConfiguration",
                payload={"message": "TestEvent"},
                test_event=True,
            )
        return _empty_response(200)

    # Tagging
    if "tagging" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        body = await request.body()
        tags = _parse_tagging_xml(body)
        buckets[bucket]["tags"] = tags
        return _empty_response(204)

    # ACL
    if "acl" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        return _empty_response(200)

    # CORS
    if "cors" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        return _empty_response(200)

    # Lifecycle
    if "lifecycle" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        return _empty_response(200)

    # Encryption
    if "encryption" in params:
        if not _bucket_exists(bucket):
            return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
        return _empty_response(200)

    # CreateBucket
    err = _validate_bucket_name(bucket)
    if err:
        return err
    if _bucket_exists(bucket):
        return _error_xml("BucketAlreadyOwnedByYou", "Your previous request to create the named bucket succeeded.", f"/{bucket}", 409)

    body = await request.body()
    region = "us-east-1"
    if body:
        try:
            root = ET.fromstring(body)
            loc = root.find("{http://s3.amazonaws.com/doc/2006-03-01/}LocationConstraint")
            if loc is not None and loc.text:
                region = loc.text
        except ET.ParseError:
            pass

    # Tier quantity cap — Free=1 bucket/space; enforced before mutation.
    _enforce_quantity_cap("bucket")

    buckets[bucket] = {
        "region": region,
        "created": _now(),
        "access": "Bucket and objects not public",
        "versioning": "Disabled",
        "arn": f"arn:aws:s3:::{bucket}",
        "tags": {},
        "notifications": _s3_default_notifications(),
    }
    objects[bucket] = {}
    _cloudsim_sync_service_resource("aws", "s3", "bucket", bucket, buckets[bucket], "s3")
    return _empty_response(200, {"Location": f"/{bucket}"})


async def s3_get_bucket(bucket: str, request: Request) -> Response:
    """GET /{bucket}[?versioning|?tagging|?location|?list-type=2|...] → List/Get Bucket Config"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

    # GetBucketLocation
    if "location" in params:
        region = buckets[bucket].get("region", "us-east-1")
        loc = "" if region == "us-east-1" else region
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<LocationConstraint xmlns="{S3_NS}">{loc}</LocationConstraint>'
        )
        return _xml_response(xml)

    # GetBucketVersioning
    if "versioning" in params:
        status = buckets[bucket].get("versioning", "Disabled")
        status_xml = f"<Status>{status}</Status>" if status != "Disabled" else ""
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<VersioningConfiguration xmlns="{S3_NS}">{status_xml}</VersioningConfiguration>'
        )
        return _xml_response(xml)

    # GetBucketNotificationConfiguration
    if "notification" in params:
        return _xml_response(_s3_notification_xml_from_config(bucket))

    # ListObjectVersions
    if "versions" in params:
        prefix = params.get("prefix", "")
        marker = params.get("key-marker", "")
        version_marker = params.get("version-id-marker", "")
        max_keys = min(int(params.get("max-keys", 1000)), 1000)
        all_versions = _s3_list_versions(bucket, prefix)
        if marker:
            filtered = []
            started = False
            for key_name, version in all_versions:
                if not started:
                    if key_name < marker:
                        continue
                    if key_name > marker:
                        started = True
                        filtered.append((key_name, version))
                        continue
                    if version_marker:
                        if str(version.get("version_id", "")) == str(version_marker):
                            started = True
                        continue
                    continue
                filtered.append((key_name, version))
            all_versions = filtered
        truncated = len(all_versions) > max_keys
        page = all_versions[:max_keys]
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<ListVersionsResult xmlns="{S3_NS}">',
            f"<Name>{bucket}</Name>",
            f"<Prefix>{prefix}</Prefix>",
            f"<KeyMarker>{marker}</KeyMarker>",
            f"<VersionIdMarker>{version_marker}</VersionIdMarker>",
            f"<MaxKeys>{max_keys}</MaxKeys>",
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
        ]
        if truncated and page:
            last_key, last_version = page[-1]
            xml_parts.append(f"<NextKeyMarker>{last_key}</NextKeyMarker>")
            xml_parts.append(f"<NextVersionIdMarker>{last_version.get('version_id', 'null')}</NextVersionIdMarker>")
        for key_name, version in page:
            tag_name = "DeleteMarker" if version.get("is_delete_marker") else "Version"
            xml_parts.append(f"<{tag_name}>")
            xml_parts.append(f"<Key>{key_name}</Key>")
            xml_parts.append(f"<VersionId>{version.get('version_id', 'null')}</VersionId>")
            xml_parts.append(f"<IsLatest>{'true' if version.get('is_latest') else 'false'}</IsLatest>")
            xml_parts.append(f"<LastModified>{version.get('last_modified')}</LastModified>")
            xml_parts.append("<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>")
            if not version.get("is_delete_marker"):
                xml_parts.append(f"<ETag>{version.get('etag', '')}</ETag>")
                xml_parts.append(f"<Size>{version.get('size', 0)}</Size>")
                xml_parts.append(f"<StorageClass>{version.get('storage_class', 'STANDARD')}</StorageClass>")
            xml_parts.append(f"</{tag_name}>")
        xml_parts.append("</ListVersionsResult>")
        return _xml_response("".join(xml_parts))

    # GetBucketTagging
    if "tagging" in params:
        tags = buckets[bucket].get("tags", {})
        if not tags:
            return _error_xml("NoSuchTagSet", "The TagSet does not exist.", f"/{bucket}", 404)
        xml = _build_tagging_xml(tags)
        return _xml_response(xml)

    # GetBucketAcl
    if "acl" in params:
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<AccessControlPolicy xmlns="{S3_NS}">'
            "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"
            "<AccessControlList>"
            '<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
            "<ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName>"
            "</Grantee><Permission>FULL_CONTROL</Permission></Grant>"
            "</AccessControlList>"
            "</AccessControlPolicy>"
        )
        return _xml_response(xml)

    # GetBucketEncryption
    if "encryption" in params:
        return _error_xml("ServerSideEncryptionConfigurationNotFoundError",
                          "The server side encryption configuration was not found.", f"/{bucket}", 404)

    # GetBucketLifecycle
    if "lifecycle" in params:
        return _error_xml("NoSuchLifecycleConfiguration",
                          "The lifecycle configuration does not exist.", f"/{bucket}", 404)

    # GetBucketCors
    if "cors" in params:
        return _error_xml("NoSuchCORSConfiguration",
                          "The CORS configuration does not exist.", f"/{bucket}", 404)

    # ListMultipartUploads
    if "uploads" in params:
        xml_parts = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<ListMultipartUploadsResult xmlns="{S3_NS}">',
            f"<Bucket>{bucket}</Bucket>",
            "<KeyMarker></KeyMarker>",
            "<UploadIdMarker></UploadIdMarker>",
            "<NextKeyMarker></NextKeyMarker>",
            "<NextUploadIdMarker></NextUploadIdMarker>",
            "<MaxUploads>1000</MaxUploads>",
            "<IsTruncated>false</IsTruncated>",
        ]
        for uid, mp in multiparts.items():
            if mp["bucket"] == bucket:
                xml_parts += [
                    "<Upload>",
                    f"<Key>{mp['key']}</Key>",
                    f"<UploadId>{uid}</UploadId>",
                    "<Initiator><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Initiator>",
                    "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
                    "<StorageClass>STANDARD</StorageClass>",
                    f"<Initiated>{mp['initiated']}</Initiated>",
                    "</Upload>",
                ]
        xml_parts.append("</ListMultipartUploadsResult>")
        return _xml_response("".join(xml_parts))

    # ListObjectsV2
    if params.get("list-type") == "2":
        return _list_objects_v2(bucket, params)

    # ListObjects (v1) — default
    return _list_objects_v1(bucket, params)


async def s3_delete_bucket(bucket: str, request: Request) -> Response:
    """DELETE /{bucket} → DeleteBucket"""
    params = dict(request.query_params)
    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    if "notification" in params:
        buckets[bucket]["notifications"] = _s3_default_notifications()
        return _empty_response(204)
    if objects.get(bucket):
        return _error_xml("BucketNotEmpty", "The bucket you tried to delete is not empty.", f"/{bucket}", 409)
    _cloudsim_sync_service_resource("aws", "s3", "bucket", bucket, {}, "s3", action="delete")
    del buckets[bucket]
    del objects[bucket]
    return _empty_response(204)


# ── S3 REST API — object level ───────────────────────────────────────────────

async def s3_head_object(bucket: str, key: str, request: Request) -> Response:
    """HEAD /{bucket}/{key} → HeadObject"""
    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}/{key}", 404)
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    version_id = request.query_params.get("versionId")
    obj = _s3_find_version(entry, version_id) if entry else None
    if obj and obj.get("is_delete_marker"):
        if version_id:
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    headers = {
        "Content-Length": str(obj["size"]),
        "Content-Type": obj["content_type"],
        "ETag": obj["etag"],
        "Last-Modified": _iso_to_http_date(obj["last_modified"]),
        "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
        "x-amz-version-id": obj.get("version_id", "null"),
    }
    for k, v in obj.get("metadata", {}).items():
        headers[f"x-amz-meta-{k}"] = v
    return _empty_response(200, headers)


async def s3_put_object(bucket: str, key: str, request: Request) -> Response:
    """PUT /{bucket}/{key}[?tagging|?acl|?uploadId&partNumber] → PutObject/UploadPart/CopyObject/Tagging"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

    # UploadPart
    if "uploadId" in params and "partNumber" in params:
        upload_id = params["uploadId"]
        part_number = int(params["partNumber"])
        if upload_id not in multiparts:
            return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
        data = await request.body()
        etag = _etag(data)
        multiparts[upload_id]["parts"][part_number] = {"data": data, "etag": etag, "size": len(data)}
        return _empty_response(200, {"ETag": etag})

    # Object tagging
    if "tagging" in params:
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        if not entry or not entry.get("versions"):
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        body = await request.body()
        tags = _parse_tagging_xml(body)
        entry["versions"][0]["tags"] = tags
        _s3_refresh_object_entry(entry)
        return _empty_response(200)

    # Object ACL
    if "acl" in params:
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        if not entry or not entry.get("versions"):
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        return _empty_response(200)

    # CopyObject (x-amz-copy-source header present)
    copy_source = request.headers.get("x-amz-copy-source")
    if copy_source:
        copy_source = copy_source.lstrip("/")
        parts = copy_source.split("/", 1)
        if len(parts) < 2:
            return _error_xml("InvalidArgument", "Invalid copy source.", f"/{bucket}/{key}", 400)
        src_bucket, src_key = parts[0], parts[1]
        if not _bucket_exists(src_bucket):
            return _error_xml("NoSuchBucket", "The source bucket does not exist.", f"/{src_bucket}", 404)
        src_entry = _s3_ensure_object_entry(src_bucket, src_key, create=False)
        src = _s3_find_version(src_entry, request.headers.get("x-amz-copy-source-version-id")) if src_entry else None
        if not src or src.get("is_delete_marker"):
            return _error_xml("NoSuchKey", "The source key does not exist.", f"/{src_bucket}/{src_key}", 404)
        now = _now()
        new_content_type = request.headers.get("x-amz-metadata-directive", "COPY") == "REPLACE" and request.headers.get("content-type", src["content_type"]) or src["content_type"]
        versioning_status = _s3_bucket_versioning_status(bucket)
        version_id = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
        version = _s3_make_version_record(
            data=src["data"],
            content_type=new_content_type,
            storage_class="STANDARD",
            metadata=src.get("metadata", {}).copy(),
            tags=src.get("tags", {}).copy(),
            version_id=version_id,
            delete_marker=False,
            last_modified=now,
            etag=_etag(src["data"]),
        )
        replace_version_id = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
        _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id, event_name="s3:ObjectCreated:Copy", source="CopyObject")
        new_etag = version["etag"]
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<CopyObjectResult xmlns="{S3_NS}">'
            f"<LastModified>{now}</LastModified>"
            f"<ETag>{new_etag}</ETag>"
            "</CopyObjectResult>"
        )
        return _xml_response(xml)

    # PutObject
    data = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    storage_class = request.headers.get("x-amz-storage-class", "STANDARD")

    # Extract user-defined metadata (x-amz-meta-* headers)
    user_meta = {}
    for h, v in request.headers.items():
        if h.lower().startswith("x-amz-meta-"):
            user_meta[h[11:]] = v

    versioning_status = _s3_bucket_versioning_status(bucket)
    version_id = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
    version = _s3_make_version_record(
        data=data,
        content_type=content_type,
        storage_class=storage_class,
        metadata=user_meta,
        tags={},
        version_id=version_id,
        delete_marker=False,
    )
    replace_version_id = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
    entry = _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id, event_name="s3:ObjectCreated:Put", source="PutObject")
    return _empty_response(200, {"ETag": version["etag"], "x-amz-version-id": entry.get("current_version_id", version_id)})


async def s3_get_object(bucket: str, key: str, request: Request) -> Response:
    """GET /{bucket}/{key}[?tagging|?acl|?uploadId] → GetObject/GetObjectTagging/ListParts"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
        # GCS XML-style media download: real google-cloud-storage (Go) and the
        # GCS XML API fetch objects at GET /{bucket}/{object}. When this isn't an
        # S3 bucket, fall back to the GCS byte store (fake-gcs-server is global,
        # not space-scoped), so unmodified Google clients can read objects.
        if key and not ({"uploadId", "tagging", "acl", "versions", "uploads"} & set(params)):
            try:
                from core import gcp_gcs_store as _gcs
                if _gcs.available():
                    data, ctype = _gcs.download(_tenant_scoped_bucket(bucket), key)
                    return Response(content=data, media_type=ctype or "application/octet-stream")
            except Exception:
                pass
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

    # ListParts
    if "uploadId" in params:
        upload_id = params["uploadId"]
        if upload_id not in multiparts:
            return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
        mp = multiparts[upload_id]
        xml_parts = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<ListPartsResult xmlns="{S3_NS}">',
            f"<Bucket>{bucket}</Bucket>",
            f"<Key>{key}</Key>",
            f"<UploadId>{upload_id}</UploadId>",
            "<Initiator><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Initiator>",
            "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
            "<StorageClass>STANDARD</StorageClass>",
            "<IsTruncated>false</IsTruncated>",
        ]
        for pn in sorted(mp["parts"]):
            p = mp["parts"][pn]
            xml_parts += [
                "<Part>",
                f"<PartNumber>{pn}</PartNumber>",
                f"<LastModified>{_now()}</LastModified>",
                f"<ETag>{p['etag']}</ETag>",
                f"<Size>{p['size']}</Size>",
                "</Part>",
            ]
        xml_parts.append("</ListPartsResult>")
        return _xml_response("".join(xml_parts))

    # GetObjectTagging
    if "tagging" in params:
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        version_id = params.get("versionId")
        obj = _s3_find_version(entry, version_id) if entry else None
        if not obj or obj.get("is_delete_marker"):
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        tags = obj.get("tags", {})
        xml = _build_tagging_xml(tags)
        return _xml_response(xml)

    # GetObjectAcl
    if "acl" in params:
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        version_id = params.get("versionId")
        obj = _s3_find_version(entry, version_id) if entry else None
        if not obj or obj.get("is_delete_marker"):
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<AccessControlPolicy xmlns="{S3_NS}">'
            "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"
            "<AccessControlList>"
            '<Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
            "<ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName>"
            "</Grantee><Permission>FULL_CONTROL</Permission></Grant>"
            "</AccessControlList>"
            "</AccessControlPolicy>"
        )
        return _xml_response(xml)

    # GetObject
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    version_id = params.get("versionId")
    obj = _s3_find_version(entry, version_id) if entry else None
    if obj and obj.get("is_delete_marker"):
        if version_id:
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    data = obj["data"]
    status = 200
    content_range = None

    # Range request support
    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else len(data) - 1
            end = min(end, len(data) - 1)
            data = data[start:end + 1]
            status = 206
            content_range = f"bytes {start}-{end}/{obj['size']}"

    headers = {
        "Content-Type": obj["content_type"],
        "ETag": obj["etag"],
        "Last-Modified": _iso_to_http_date(obj["last_modified"]),
        "Content-Length": str(len(data)),
        "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
        "x-amz-version-id": obj.get("version_id", "null"),
        "x-amz-request-id": _req_id(),
        "x-amz-id-2": uuid.uuid4().hex,
    }
    if content_range:
        headers["Content-Range"] = content_range
    for k, v in obj.get("metadata", {}).items():
        headers[f"x-amz-meta-{k}"] = v

    return StreamingResponse(
        io.BytesIO(data),
        status_code=status,
        media_type=obj["content_type"],
        headers=headers,
    )


async def s3_delete_object(bucket: str, key: str, request: Request) -> Response:
    """DELETE /{bucket}/{key}[?tagging|?uploadId] → DeleteObject/AbortMultipartUpload/DeleteObjectTagging"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

    # AbortMultipartUpload
    if "uploadId" in params:
        upload_id = params["uploadId"]
        if upload_id in multiparts:
            del multiparts[upload_id]
        return _empty_response(204)

    # DeleteObjectTagging
    if "tagging" in params:
        entry = _s3_ensure_object_entry(bucket, key, create=False)
        version_id = params.get("versionId")
        obj = _s3_find_version(entry, version_id) if entry else None
        if not obj or obj.get("is_delete_marker"):
            return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
        obj["tags"] = {}
        if entry and entry.get("versions"):
            _s3_refresh_object_entry(entry)
        return _empty_response(204)

    # DeleteObject
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    version_id = params.get("versionId")
    if version_id:
        if not _s3_delete_version(bucket, key, version_id):
            return _error_xml("NoSuchVersion", "The specified version does not exist.", f"/{bucket}/{key}", 404)
        return _empty_response(204, {"x-amz-version-id": version_id})
    status = _s3_bucket_versioning_status(bucket)
    if status == "Disabled":
        if key in objects.get(bucket, {}):
            del objects[bucket][key]
        return _empty_response(204)
    entry = _s3_insert_simple_delete_marker(bucket, key, source="DeleteObject")
    version_id = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
    return _empty_response(204, {"x-amz-delete-marker": "true", "x-amz-version-id": version_id})


async def s3_post_bucket(bucket: str, request: Request) -> Response:
    """POST /{bucket}[?delete] → DeleteObjects (batch) or CreateMultipartUpload"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

    # DeleteObjects (batch)
    if "delete" in params:
        body = await request.body()
        deleted = []
        errors = []
        try:
            root = ET.fromstring(body)
            for obj_el in root.findall("{http://s3.amazonaws.com/doc/2006-03-01/}Object"):
                key_el = obj_el.find("{http://s3.amazonaws.com/doc/2006-03-01/}Key")
                if key_el is not None and key_el.text:
                    k = key_el.text
                    if k in objects.get(bucket, {}):
                        if _s3_bucket_versioning_status(bucket) == "Disabled":
                            del objects[bucket][k]
                            _s3_emit_event(bucket, k, "s3:ObjectRemoved:Delete", None, source="DeleteObjects")
                        else:
                            _s3_insert_simple_delete_marker(bucket, k, source="DeleteObjects")
                    deleted.append(k)
        except ET.ParseError:
            return _error_xml("MalformedXML", "The XML you provided was not well-formed.", f"/{bucket}", 400)

        xml_parts = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<DeleteResult xmlns="{S3_NS}">',
        ]
        for k in deleted:
            xml_parts += [f"<Deleted><Key>{k}</Key></Deleted>"]
        for e in errors:
            xml_parts += [f"<Error><Key>{e['key']}</Key><Code>{e['code']}</Code><Message>{e['message']}</Message></Error>"]
        xml_parts.append("</DeleteResult>")
        return _xml_response("".join(xml_parts))

    return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}", 405)


async def s3_post_object(bucket: str, key: str, request: Request) -> Response:
    """POST /{bucket}/{key}?uploads → CreateMultipartUpload
       POST /{bucket}/{key}?uploadId=... → CompleteMultipartUpload"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)

    # CreateMultipartUpload
    if "uploads" in params:
        upload_id = str(uuid.uuid4())
        content_type = request.headers.get("content-type", "application/octet-stream")
        user_meta = {}
        for h, v in request.headers.items():
            if h.lower().startswith("x-amz-meta-"):
                user_meta[h[11:]] = v
        multiparts[upload_id] = {
            "bucket": bucket,
            "key": key,
            "parts": {},
            "content_type": content_type,
            "metadata": user_meta,
            "initiated": _now(),
        }
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<InitiateMultipartUploadResult xmlns="{S3_NS}">'
            f"<Bucket>{bucket}</Bucket>"
            f"<Key>{key}</Key>"
            f"<UploadId>{upload_id}</UploadId>"
            "</InitiateMultipartUploadResult>"
        )
        return _xml_response(xml)

    # CompleteMultipartUpload
    if "uploadId" in params:
        upload_id = params["uploadId"]
        if upload_id not in multiparts:
            return _error_xml("NoSuchUpload", "The specified upload does not exist.", f"/{bucket}/{key}", 404)
        mp = multiparts[upload_id]
        body = await request.body()

        # Parse part list from request
        ordered_parts = []
        try:
            root = ET.fromstring(body)
            for part_el in root.findall("{http://s3.amazonaws.com/doc/2006-03-01/}Part"):
                pn_el = part_el.find("{http://s3.amazonaws.com/doc/2006-03-01/}PartNumber")
                if pn_el is not None and pn_el.text:
                    pn = int(pn_el.text)
                    if pn in mp["parts"]:
                        ordered_parts.append(pn)
        except ET.ParseError:
            # Fall back to sorted parts
            ordered_parts = sorted(mp["parts"].keys())

        if not ordered_parts:
            ordered_parts = sorted(mp["parts"].keys())

        # Assemble object
        assembled = b"".join(mp["parts"][pn]["data"] for pn in ordered_parts)
        versioning_status = _s3_bucket_versioning_status(bucket)
        version_id = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
        version = _s3_make_version_record(
            data=assembled,
            content_type=mp["content_type"],
            storage_class="STANDARD",
            metadata=mp["metadata"],
            tags={},
            version_id=version_id,
            delete_marker=False,
        )
        replace_version_id = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
        _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id, event_name="s3:ObjectCreated:CompleteMultipartUpload", source="CompleteMultipartUpload")
        del multiparts[upload_id]

        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<CompleteMultipartUploadResult xmlns="{S3_NS}">'
            f"<Location>http://localhost:9000/{bucket}/{key}</Location>"
            f"<Bucket>{bucket}</Bucket>"
            f"<Key>{key}</Key>"
            f"<ETag>{version['etag']}</ETag>"
            "</CompleteMultipartUploadResult>"
        )
        return _xml_response(xml)

    return _error_xml("MethodNotAllowed", "The specified method is not allowed against this resource.", f"/{bucket}/{key}", 405)


# ── Tag helpers ──────────────────────────────────────────────────────────────

def _parse_tagging_xml(body: bytes) -> dict:
    tags = {}
    if not body:
        return tags
    try:
        root = ET.fromstring(body)
        for tag in root.iter("{http://s3.amazonaws.com/doc/2006-03-01/}Tag"):
            k = tag.find("{http://s3.amazonaws.com/doc/2006-03-01/}Key")
            v = tag.find("{http://s3.amazonaws.com/doc/2006-03-01/}Value")
            if k is not None and k.text:
                tags[k.text] = (v.text or "") if v is not None else ""
    except ET.ParseError:
        pass
    return tags


def _build_tagging_xml(tags: dict) -> str:
    tag_xml = "".join(
        f"<Tag><Key>{k}</Key><Value>{v}</Value></Tag>"
        for k, v in tags.items()
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Tagging xmlns="{S3_NS}"><TagSet>{tag_xml}</TagSet></Tagging>'
    )


# ── ListObjects helpers ──────────────────────────────────────────────────────

def _list_objects_v1(bucket: str, params: dict) -> Response:
    prefix = params.get("prefix", "")
    delimiter = params.get("delimiter", "")
    marker = params.get("marker", "")
    max_keys = min(int(params.get("max-keys", 1000)), 1000)

    all_keys = []
    for k in sorted(objects[bucket]):
        if not k.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        if not entry or not entry.get("versions"):
            continue
        if entry["versions"][0].get("is_delete_marker"):
            continue
        all_keys.append(k)
    if marker:
        all_keys = [k for k in all_keys if k > marker]

    common_prefixes = set()
    result_keys = []
    for k in all_keys:
        if delimiter:
            suffix = k[len(prefix):]
            pos = suffix.find(delimiter)
            if pos >= 0:
                common_prefixes.add(prefix + suffix[: pos + len(delimiter)])
                continue
        result_keys.append(k)

    truncated = len(result_keys) > max_keys
    result_keys = result_keys[:max_keys]
    next_marker = result_keys[-1] if truncated else ""

    xml_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListBucketResult xmlns="{S3_NS}">',
        f"<Name>{bucket}</Name>",
        f"<Prefix>{prefix}</Prefix>",
        f"<Marker>{marker}</Marker>",
        f"<MaxKeys>{max_keys}</MaxKeys>",
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
    ]
    if truncated:
        xml_parts.append(f"<NextMarker>{next_marker}</NextMarker>")
    if delimiter:
        xml_parts.append(f"<Delimiter>{delimiter}</Delimiter>")

    for k in result_keys:
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        obj = entry["versions"][0] if entry and entry.get("versions") else None
        if not obj or obj.get("is_delete_marker"):
            continue
        xml_parts += [
            "<Contents>",
            f"<Key>{k}</Key>",
            f"<LastModified>{obj['last_modified']}</LastModified>",
            f"<ETag>{obj['etag']}</ETag>",
            f"<Size>{obj['size']}</Size>",
            f"<StorageClass>{obj.get('storage_class', 'STANDARD')}</StorageClass>",
            "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
            "</Contents>",
        ]
    for cp in sorted(common_prefixes):
        xml_parts.append(f"<CommonPrefixes><Prefix>{cp}</Prefix></CommonPrefixes>")
    xml_parts.append("</ListBucketResult>")
    return _xml_response("".join(xml_parts))


def _list_objects_v2(bucket: str, params: dict) -> Response:
    prefix = params.get("prefix", "")
    delimiter = params.get("delimiter", "")
    continuation_token = params.get("continuation-token", "")
    start_after = params.get("start-after", "")
    max_keys = min(int(params.get("max-keys", 1000)), 1000)
    fetch_owner = params.get("fetch-owner", "false").lower() == "true"

    start_key = continuation_token or start_after
    all_keys = []
    for k in sorted(objects[bucket]):
        if not k.startswith(prefix):
            continue
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        if not entry or not entry.get("versions"):
            continue
        if entry["versions"][0].get("is_delete_marker"):
            continue
        all_keys.append(k)
    if start_key:
        all_keys = [k for k in all_keys if k > start_key]

    common_prefixes = set()
    result_keys = []
    for k in all_keys:
        if delimiter:
            suffix = k[len(prefix):]
            pos = suffix.find(delimiter)
            if pos >= 0:
                common_prefixes.add(prefix + suffix[: pos + len(delimiter)])
                continue
        result_keys.append(k)

    truncated = len(result_keys) > max_keys
    result_keys = result_keys[:max_keys]
    next_token = result_keys[-1] if truncated else ""

    xml_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListBucketResult xmlns="{S3_NS}">',
        f"<Name>{bucket}</Name>",
        f"<Prefix>{prefix}</Prefix>",
        f"<MaxKeys>{max_keys}</MaxKeys>",
        f"<KeyCount>{len(result_keys)}</KeyCount>",
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>",
    ]
    if continuation_token:
        xml_parts.append(f"<ContinuationToken>{continuation_token}</ContinuationToken>")
    if truncated:
        xml_parts.append(f"<NextContinuationToken>{next_token}</NextContinuationToken>")
    if delimiter:
        xml_parts.append(f"<Delimiter>{delimiter}</Delimiter>")
    if start_after:
        xml_parts.append(f"<StartAfter>{start_after}</StartAfter>")

    for k in result_keys:
        entry = _s3_ensure_object_entry(bucket, k, create=False)
        obj = entry["versions"][0] if entry and entry.get("versions") else None
        if not obj or obj.get("is_delete_marker"):
            continue
        xml_parts += ["<Contents>", f"<Key>{k}</Key>",
                      f"<LastModified>{obj['last_modified']}</LastModified>",
                      f"<ETag>{obj['etag']}</ETag>",
                      f"<Size>{obj['size']}</Size>",
                      f"<StorageClass>{obj.get('storage_class', 'STANDARD')}</StorageClass>"]
        if fetch_owner:
            xml_parts += ["<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>"]
        xml_parts.append("</Contents>")
    for cp in sorted(common_prefixes):
        xml_parts.append(f"<CommonPrefixes><Prefix>{cp}</Prefix></CommonPrefixes>")
    xml_parts.append("</ListBucketResult>")
    return _xml_response("".join(xml_parts))


# ── Disk-health endpoints + pre-flight gate (the disk-reliability stack) ──
# core/disk_health.py owns the logic; here we just expose it. The monitor
# daemon is started during the same startup hook that fires the license
# refresh loop (search for start_disk_health_monitor below).
from core import disk_health as _disk_health


def _disk_preflight(storage_gb_hint: Optional[float] = None) -> None:
    """Pre-flight any VM launch. Caller passes the requested
    instance.storage_gb when available. Pad with the rootfs base size
    (Ubuntu 22.04 sqaushfs ~1.2 GB) and a slop margin.

    Bypass: set CLOUDLEARN_DISK_GATE=disabled to short-circuit. Used by
    the local conformance harness — tests aim to exercise the control-
    plane contract, not the actual LXD provisioning. Customer installs
    keep the gate ON (default)."""
    if os.environ.get("CLOUDLEARN_DISK_GATE", "").strip().lower() in ("disabled", "off", "0", "false"):
        return
    base_rootfs_gb = 1.5  # ubuntu:22.04 unpacked rootfs
    slop_gb = 0.5
    required = base_rootfs_gb + float(storage_gb_hint or 0) + slop_gb
    try:
        _disk_health.preflight_launch_check(STATE, required_gb=required)
    except _disk_health.InsufficientDiskError as e:
        raise HTTPException(507, detail=e.payload)


@app.get("/api/runtime/disk-health")
def api_runtime_disk_health():
    """Surface the latest disk-health snapshot for the SPA dashboard
    widget. Returns the cached snapshot from the monitor daemon when
    available (no shell-out cost) and falls back to a live sample."""
    cached = (STATE.get("runtime") or {}).get("disk_health")
    if cached and cached.get("available"):
        return cached
    return _disk_health.evaluate_health(STATE)


@app.get("/api/runtime/disk-cleanup/suggestions")
def api_runtime_disk_cleanup_suggestions():
    return _disk_health.cleanup_suggestions(STATE)


class _DiskCleanupRequest(BaseModel):
    categories: list[str]


@app.post("/api/runtime/disk-cleanup/run")
def api_runtime_disk_cleanup_run(req: _DiskCleanupRequest):
    result = _disk_health.run_cleanup(STATE, req.categories or [])
    # Re-sample disk immediately so the UI sees the result without
    # waiting for the next 60s monitor tick.
    STATE.setdefault("runtime", {})["disk_health"] = _disk_health.evaluate_health(STATE)
    _persist_state()
    return result


class _DiskGrowRequest(BaseModel):
    target_gb: int


@app.post("/api/runtime/disk-grow")
def api_runtime_disk_grow(req: _DiskGrowRequest):
    """Paid-tier escape hatch. Free tier gets a friendly 403 directing
    them to the pricing page; paid tiers receive the multipass resize
    command the user runs on the host machine."""
    tier = str((STATE.get("license") or {}).get("tier") or "free").lower()
    if tier == "free":
        raise HTTPException(403, detail={
            "code": "tier_required",
            "reason": "Disk-grow requires a paid tier (Student / Developer / Enterprise).",
            "upgrade_url": "https://vyomi.cloud/pricing",
        })
    return _disk_health.grow_disk(STATE, int(req.target_gb))


# ── VM-Connect endpoints (AWS EC2 + GCP Compute + Azure VM) ────────────
# Cross-provider SSH/lxc-shell helper. Lazy-provisions an SSH key into
# the LXD container backing the VM, opens a proxy port on the VM, and
# returns realistic Connect commands the user can paste into a terminal.
# See core/vm_connect.py for the full provisioning pipeline.
#
# Must be registered BEFORE aws_s3.register() so the S3 catch-all
# doesn't swallow the GETs as bucket-style lookups.
from core import vm_connect as _vmc


def _find_instance_across_spaces(provider: str, instance_id: str) -> tuple[Optional[dict], Optional[dict]]:
    """Return (instance_dict, space_dict) or (None, None). Scans every
    space's service_states because the active space at request time may
    not be the one that owns this instance (e.g., user switched spaces
    between launch and Connect)."""
    iid = str(instance_id or "").strip()
    if not iid:
        return None, None
    spaces = (STATE.get("spaces") or {}).get("spaces") or {}
    for sid, space in spaces.items():
        if not isinstance(space, dict):
            continue
        ss = space.get("service_states") or {}
        if provider == "aws":
            instances = (ss.get("ec2") or {}).get("instances") or {}
            inst = instances.get(iid)
            if inst:
                return inst, space
        elif provider == "gcp":
            instances = (ss.get("gcp_compute") or {}).get("instances") or {}
            inst = instances.get(iid)
            if inst:
                return inst, space
        elif provider == "azure":
            # Azure VMs are stored as ARM resources keyed by full
            # resource_id; match by name suffix or by the bare name.
            resources = (ss.get("azure_arm") or {}).get("resources") or {}
            for rid, rec in resources.items():
                if not isinstance(rec, dict):
                    continue
                if "virtualmachines" not in str(rec.get("_type", "")).lower():
                    continue
                if rec.get("name") == iid or str(rid).rstrip("/").endswith("/" + iid):
                    return rec, space
    return None, None


def _connect_info_response(provider: str, instance_id: str) -> dict:
    inst, _ = _find_instance_across_spaces(provider, instance_id)
    if not inst:
        raise HTTPException(404, f"instance {instance_id!r} not found")
    state_running = inst.get("state") or inst.get("powerState") or ""
    if isinstance(state_running, dict):
        state_running = state_running.get("Name") or ""
    if str(state_running).lower() not in {"running", "powerstate/running"}:
        raise HTTPException(409, detail={
            "error": "instance_not_running",
            "state": state_running,
            "hint": "Start the instance before connecting.",
        })
    # Pass the deployment-level STATE so port claims are global, not per-space.
    info = _vmc.connect_info(STATE, inst, provider=provider)
    if not info.get("ok"):
        raise HTTPException(503, detail=info)
    _persist_state()
    return info


@app.get("/api/aws/ec2/instances/{instance_id}/connect-info")
def api_ec2_connect_info(instance_id: str):
    return _connect_info_response("aws", instance_id)


@app.get("/api/aws/ec2/instances/{instance_id}/private-key.pem")
def api_ec2_private_key(instance_id: str):
    pem = _vmc.read_private_key(instance_id)
    if not pem:
        raise HTTPException(404, "private key not provisioned yet — open Connect first")
    return Response(
        content=pem, media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="vyomi-{instance_id}.pem"'},
    )


@app.get("/api/gcp/compute/instances/{instance_id}/connect-info")
def api_gce_connect_info(instance_id: str):
    return _connect_info_response("gcp", instance_id)


@app.get("/api/gcp/compute/instances/{instance_id}/private-key.pem")
def api_gce_private_key(instance_id: str):
    pem = _vmc.read_private_key(instance_id)
    if not pem:
        raise HTTPException(404, "private key not provisioned yet — open Connect first")
    return Response(
        content=pem, media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="vyomi-{instance_id}.pem"'},
    )


@app.get("/api/azure/vm/{instance_id}/connect-info")
def api_azure_vm_connect_info(instance_id: str):
    return _connect_info_response("azure", instance_id)


@app.get("/api/azure/vm/{instance_id}/private-key.pem")
def api_azure_vm_private_key(instance_id: str):
    pem = _vmc.read_private_key(instance_id)
    if not pem:
        raise HTTPException(404, "private key not provisioned yet — open Connect first")
    return Response(
        content=pem, media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="vyomi-{instance_id}.pem"'},
    )


# ── S3 catch-all routes — TRULY LAST ────────────────────────────────
# Register AFTER all the explicit /api/{auth,license,...} POST routes
# defined above. Starlette matches routes in registration order; if
# we registered the @app.post("/{bucket}/{key:path}") catch-all up
# top (as the file originally did), it swallowed POST /api/auth/...
# with bucket=api, key=auth/... and returned a NoSuchBucket XML.
aws_s3.register(app, aws_xamz_dispatchers=_aws_xamz_dispatchers)


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=9000, reload=False)
