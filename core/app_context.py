"""
core.app_context — Shared state foundation for CloudLearn.

This module is the single source of truth for:
  - Global constants (STATE_VERSION, XML namespaces, account IDs, ...)
  - ContextVars (REQUEST_PROVIDER, REQUEST_PUBLIC_BASE, REQUEST_TENANT)
  - PLATFORM / STATE / STATE_LOCK bootstrap
  - Tenant helpers
  - _SpaceScopedDictProxy and every state proxy instance
  - Tier-enforcement helpers
  - Activity logging
  - Rate-limiting state
  - Small utility functions (now, id_gen, public_ip, private_ip, ...)

Extracted from server.py to break circular dependencies: provider modules,
route modules, and middleware can all ``from core.app_context import ...``
without importing the 22 K-line server monolith.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import re
import secrets
import threading
import time
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

from core.vyomi_platform import VyomiPlatform as CloudLearnPlatform
from core.pack_catalog import default_packs as load_default_packs

# ── Constants ───────────────────────────────────────────────────────────────

STATE_VERSION = 12
STATE_FILE = Path(os.environ.get(
    "CLOUDLEARN_STATE_FILE",
    Path(__file__).resolve().parent.parent / ".cloudlearn_state.sqlite3",
))
LEGACY_STATE_FILE = Path(os.environ.get(
    "CLOUDLEARN_LEGACY_STATE_FILE",
    STATE_FILE.with_suffix(".pkl"),
))

LXD_RUNTIME_IMAGE = os.environ.get(
    "CLOUDLEARN_LXD_RUNTIME_IMAGE",
    os.environ.get("CLOUDLEARN_LXD_RUNTIME_IMAGE", "ubuntu:24.04"),
)
MULTIPASS_RUNTIME_IMAGE = os.environ.get("CLOUDLEARN_MULTIPASS_RUNTIME_IMAGE", "ubuntu:24.04")
LXD_CONSOLE_PORT = 8080
EC2_TERMINATED_VISIBILITY_SECONDS = int(
    os.environ.get("CLOUDLEARN_EC2_TERMINATED_VISIBILITY_SECONDS", "60"),
)
INSTANCE_WORK_ROOT = Path(
    os.environ.get("CLOUDLEARN_DEPLOY_DIR", "/var/lib/cloudlearn/deployments"),
)

EC2_XML_NS = "http://ec2.amazonaws.com/doc/2016-11-15/"
RDS_XML_NS = "http://rds.amazonaws.com/doc/2014-10-31/"
SQS_XML_NS = "http://queue.amazonaws.com/doc/2012-11-05/"
S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"

AWS_ACCOUNT_ID = "123456789012"

ET.register_namespace("", EC2_XML_NS)
ET.register_namespace("rds", RDS_XML_NS)
ET.register_namespace("sqs", SQS_XML_NS)

DEFAULT_TENANT_ID = "default"
ALLOWED_PROVIDERS = ("aws", "gcp", "azure")

# P2-C (2026-06-01): single source of truth for runtime bundles.
_DEFAULT_RUNTIME_BUNDLES: dict[str, dict] = {
    "python":        {"id": "cloudlearn.runtime.python",       "name": "Python Runtime",                  "kind": "language", "provider": "shared", "service": "python",    "installed": True, "active": False},
    "ec2":           {"id": "cloudlearn.runtime.ec2",          "name": "EC2 Runtime Bundle",              "kind": "vm",       "provider": "aws",    "service": "ec2",       "installed": True, "active": False},
    "gcp_compute":   {"id": "cloudlearn.runtime.gcp.compute",  "name": "Compute Engine Runtime Bundle",   "kind": "vm",       "provider": "gcp",    "service": "compute",   "installed": True, "active": False},
    "azure_vm":      {"id": "cloudlearn.runtime.azure.vm",     "name": "Azure VM Runtime Bundle",         "kind": "vm",       "provider": "azure",  "service": "vm",        "installed": True, "active": False},
    "lambda":        {"id": "cloudlearn.runtime.lambda",       "name": "Lambda Runtime Bundle",           "kind": "function", "provider": "aws",    "service": "lambda",    "installed": True, "active": False},
    "gcp_functions": {"id": "cloudlearn.runtime.gcp.functions", "name": "Cloud Functions Runtime Bundle", "kind": "function", "provider": "gcp",    "service": "functions", "installed": True, "active": False},
    "rds":           {"id": "cloudlearn.runtime.rds",          "name": "RDS Runtime Bundle",              "kind": "database", "provider": "aws",    "service": "rds",       "installed": True, "active": False},
    "gcp_sql":       {"id": "cloudlearn.runtime.gcp.sql",      "name": "Cloud SQL Runtime Bundle",        "kind": "database", "provider": "gcp",    "service": "sql",       "installed": True, "active": False},
    # AWS — additional services
    "s3":              {"id": "cloudlearn.runtime.s3",              "name": "S3 Runtime Bundle",               "kind": "storage",   "provider": "aws",    "service": "s3",           "installed": True, "active": False},
    "sqs":             {"id": "cloudlearn.runtime.sqs",             "name": "SQS Runtime Bundle",              "kind": "queue",     "provider": "aws",    "service": "sqs",          "installed": True, "active": False},
    "dynamodb":        {"id": "cloudlearn.runtime.dynamodb",        "name": "DynamoDB Runtime Bundle",         "kind": "nosql",     "provider": "aws",    "service": "dynamodb",     "installed": True, "active": False},
    "apigateway":      {"id": "cloudlearn.runtime.apigateway",      "name": "API Gateway Runtime Bundle",      "kind": "api_gw",    "provider": "aws",    "service": "apigateway",   "installed": True, "active": False},
    # GCP — additional services
    "gcp_storage":     {"id": "cloudlearn.runtime.gcp.storage",     "name": "Cloud Storage Runtime Bundle",    "kind": "storage",   "provider": "gcp",    "service": "storage",      "installed": True, "active": False},
    "gcp_pubsub":      {"id": "cloudlearn.runtime.gcp.pubsub",      "name": "Pub/Sub Runtime Bundle",          "kind": "queue",     "provider": "gcp",    "service": "pubsub",       "installed": True, "active": False},
    "gcp_firestore":   {"id": "cloudlearn.runtime.gcp.firestore",   "name": "Firestore Runtime Bundle",        "kind": "nosql",     "provider": "gcp",    "service": "firestore",    "installed": True, "active": False},
    "gcp_apigateway":  {"id": "cloudlearn.runtime.gcp.apigateway",  "name": "GCP API Gateway Runtime Bundle",  "kind": "api_gw",    "provider": "gcp",    "service": "apigateway",   "installed": True, "active": False},
    # Azure — all services (only azure_vm existed before)
    "azure_sql":       {"id": "cloudlearn.runtime.azure.sql",       "name": "Azure SQL Runtime Bundle",        "kind": "database",  "provider": "azure",  "service": "sql",          "installed": True, "active": False},
    "azure_storage":   {"id": "cloudlearn.runtime.azure.storage",   "name": "Azure Storage Runtime Bundle",    "kind": "storage",   "provider": "azure",  "service": "storage",      "installed": True, "active": False},
    "azure_functions": {"id": "cloudlearn.runtime.azure.functions",  "name": "Azure Functions Runtime Bundle",  "kind": "function",  "provider": "azure",  "service": "functionapp",  "installed": True, "active": False},
    "azure_servicebus":{"id": "cloudlearn.runtime.azure.servicebus","name": "Service Bus Runtime Bundle",      "kind": "queue",     "provider": "azure",  "service": "servicebus",   "installed": True, "active": False},
    "azure_cosmos":    {"id": "cloudlearn.runtime.azure.cosmos",     "name": "Cosmos DB Runtime Bundle",        "kind": "nosql",     "provider": "azure",  "service": "cosmos",       "installed": True, "active": False},
    "azure_apim":      {"id": "cloudlearn.runtime.azure.apim",      "name": "API Management Runtime Bundle",   "kind": "api_gw",    "provider": "azure",  "service": "apim",         "installed": True, "active": False},
    "azure_eventgrid": {"id": "cloudlearn.runtime.azure.eventgrid", "name": "Event Grid Runtime Bundle",       "kind": "eventing",  "provider": "azure",  "service": "eventgrid",    "installed": True, "active": False},
}


# ── ContextVars ─────────────────────────────────────────────────────────────

REQUEST_PROVIDER: ContextVar[str] = ContextVar("cloudlearn_request_provider", default="aws")
# Per-request simulator origin (set from the Host header) so GCP resource
# metadata reflects the address the client actually used.
REQUEST_PUBLIC_BASE: ContextVar[str] = ContextVar("cloudlearn_public_base", default="")
REQUEST_TENANT: ContextVar[str] = ContextVar("cloudlearn_request_tenant", default="")


# ── Utility functions ───────────────────────────────────────────────────────

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def now_http() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def iso_to_http_date(iso: str) -> str:
    """Convert ``2026-05-31T19:57:42.000Z`` -> ``Sun, 31 May 2026 19:57:42 GMT``.

    Real S3 / Azure Blob / GCS responses use HTTP date format (RFC 1123) for
    Last-Modified. aws-sdk-go-v2 strictly enforces this and fails to deserialize
    when the simulator emits ISO 8601. Stored timestamps are ISO (from
    ``now()``); convert at the response edge.
    """
    if not iso:
        return now_http()
    try:
        cleaned = iso.rstrip("Z").split(".")[0]
        dt = datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    except Exception:
        return iso  # last resort -- return as-is rather than crashing the response


def parse_utc_timestamp(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def id_gen(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def public_ip() -> str:
    return f"203.0.113.{int(uuid.uuid4().hex[:2], 16) % 250 + 1}"


def private_ip() -> str:
    return f"10.{int(uuid.uuid4().hex[:2], 16) % 250}.{int(uuid.uuid4().hex[2:4], 16) % 250}.{int(uuid.uuid4().hex[4:6], 16) % 250}"


def iam_root_principal() -> str:
    return f"arn:aws:iam::{AWS_ACCOUNT_ID}:root"


def _iam_dynamodb_table_arn(table_name: str) -> str:
    return f"arn:aws:dynamodb:us-east-1:{AWS_ACCOUNT_ID}:table/{table_name}"


# ── Host config helpers ─────────────────────────────────────────────────────

def host_config_path() -> Path:
    return Path(str(os.environ.get("CLOUDLEARN_HOST_CONFIG_FILE") or "").strip() or "/config/cloudlearn-host.json")


def host_config() -> dict[str, Any]:
    path = host_config_path()
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def resolved_host_os(host_os_hint: str = "") -> str:
    if appliance_mode_enabled():
        hint = str(host_os_hint or "").strip().lower()
        if hint:
            return hint
        return str(platform.system()).strip().lower()
    # _runtime_bridge_host_os lives in server.py; lazy-import to avoid circular dep
    try:
        from server import _runtime_bridge_host_os
        bridge_os = _runtime_bridge_host_os()
        if bridge_os:
            return bridge_os
    except Exception:
        pass
    config_os = host_config().get("host_os")
    if config_os:
        return str(config_os).strip().lower()
    hint = str(host_os_hint or "").strip().lower()
    if hint:
        return hint
    return str(os.environ.get("CLOUDLEARN_PARENT_OS") or platform.system()).strip().lower()


def parent_os() -> str:
    return resolved_host_os()


def distribution_mode() -> str:
    config_mode = host_config().get("distribution_mode")
    if config_mode:
        return str(config_mode).strip().lower()
    return str(os.environ.get("CLOUDLEARN_DISTRIBUTION_MODE") or "developer").strip().lower()


def appliance_mode_enabled() -> bool:
    return distribution_mode() == "appliance"


# ── Path detection ──────────────────────────────────────────────────────────

def is_gcp_native_path(path: str) -> bool:
    return path.startswith((
        "/compute/v1/",
        "/storage/v1/",
        "/upload/storage/v1/",
        "/download/storage/v1/",
        "/sql/v1beta4/",
        "/pubsub/v1/",
        "/firestore/v1/",
        "/v1/projects/",
        "/v1/operations/",
        "/api/gcp/s3/",
        "/api/gcp/iam/",
        "/api/gcp/rds/",
        "/api/gcp/sqs/",
        "/api/gcp/dynamodb/",
        "/api/gcp/lambda/",
        "/api/gcp/apigateway/",
        "/api/gcp/vpc/",
        "/api/gcp/compute/",
        "/api/gcp/storage/",
        "/api/gcp/sql/",
        "/api/gcp/pubsub/",
        "/api/gcp/firestore/",
        "/api/gcp/cloudfunctions/",
        "/api/gcp/console/",
        "/api/gcp/catalog",   # standalone console payload -- must NOT be path-stripped
        "/api/gcp/extras/",   # reserved for GCP-D (parity with /api/aws/extras)
        "/api/gcp/extras-config/",
    ))


def is_azure_native_path(path: str) -> bool:
    """Azure ARM control-plane (``/subscriptions/...``) and the console catalog.
    These are served by the generic ARM dispatcher and must bypass the AWS
    action/capability gating (they are not S3/EC2 calls)."""
    return path.startswith(("/subscriptions/", "/api/azure/", "/azure-data/"))


# ── State initialization ───────────────────────────────────────────────────

def _default_packs() -> Dict[str, dict]:
    return load_default_packs()


def _default_ec2_runtime_backends() -> list[str]:
    return ["lxd"] if appliance_mode_enabled() else ["multipass", "lxd"]


def _default_cloudsim_space_policy() -> dict:
    return {
        "ec2": {
            "launch": True,
            "allowed_runtime_backends": _default_ec2_runtime_backends(),
            "allowed_amis": [],
        }
    }


def _default_state() -> dict:
    return {
        "schema_version": STATE_VERSION,
        "license": {
            "tier": "free",
            "user": "guest",
            "email": "",
            "credits": 100,
            "device_id": "",
            "token": "",
            "issued_at": now(),
            "status": "active",
        },
        "spaces": {
            "spaces": {},
            "active_space_id": "",
            "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1", "max_memory_mb": 8192, "max_disk_mb": 32768},
        },
        "packs": _default_packs(),
        "deployments": {},
        "iam": {"users": {}, "groups": {}, "roles": {}, "policies": {}, "attachments": [], "identity_providers": {}, "account_settings": {"password_policy": {"minimum_length": 8, "require_symbols": True, "require_numbers": True, "require_uppercase": True, "require_lowercase": True}}},
        "ec2": {"instances": {}},
        "vpc": {"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}},
        "apigateway": {"apis": {}, "logs": []},
        "lambda": {"functions": {}, "events": [], "invocations": []},
        "sqs": {"queues": {}, "events": []},
        "dynamodb": {"tables": {}, "events": []},
        "cloudsim": {"summary": {}, "events": [], "last_reconcile_at": ""},
        "terraform": {"plans": {}, "applies": {}, "imports": {}, "spaces": {}},
        "federations": {"federations": {}, "links": {}, "tests": []},
        "rds": {
            "db_instances": {},
            "db_subnet_groups": {},
            "db_parameter_groups": {},
            "db_snapshots": {},
            "events": [],
        },
        "runtime": {
            "bundles": copy.deepcopy(_DEFAULT_RUNTIME_BUNDLES),
            "lxd": {"status": "missing", "message": "", "mode": "auto", "last_checked": ""},
            "multipass": {"status": "missing", "message": "", "mode": "auto", "last_checked": ""},
        },
        "github": {"connections": {}, "repos": {}, "deployments": {}},
        "usage": {"events": []},
    }


def _migrate_state(state: dict) -> dict:
    default = _default_state()
    default.update(state)
    for key, value in default.items():
        if key not in state:
            state[key] = value
    state["schema_version"] = STATE_VERSION
    terraform_state = state.setdefault("terraform", {"plans": {}, "applies": {}, "imports": {}, "spaces": {}})
    terraform_state.setdefault("plans", {})
    terraform_state.setdefault("applies", {})
    terraform_state.setdefault("imports", {})
    terraform_state.setdefault("spaces", {})
    spaces_state = state.setdefault(
        "spaces",
        {
            "spaces": {},
            "active_space_id": "",
            "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1", "max_memory_mb": 8192, "max_disk_mb": 32768},
        },
    )
    spaces_state.setdefault("spaces", {})
    spaces_state.setdefault("active_space_id", "")
    spaces_state.setdefault("settings", {})
    spaces_state["settings"].setdefault("max_spaces", 6)
    spaces_state["settings"].setdefault("default_provider", "aws")
    spaces_state["settings"].setdefault("default_region", "us-east-1")
    spaces_state["settings"].setdefault("max_memory_mb", 8192)
    spaces_state["settings"].setdefault("max_disk_mb", 32768)
    for space in spaces_state.get("spaces", {}).values():
        if not isinstance(space, dict):
            continue
        cloudsim = space.setdefault("cloudsim", {"summary": {}, "events": [], "last_tick": ""})
        if not isinstance(cloudsim, dict):
            space["cloudsim"] = {"summary": {}, "events": [], "last_tick": ""}
            cloudsim = space["cloudsim"]
        cloudsim.setdefault("summary", {})
        cloudsim.setdefault("events", [])
        cloudsim.setdefault("last_tick", "")
        policy = cloudsim.get("policy")
        if not isinstance(policy, dict):
            cloudsim["policy"] = copy.deepcopy(_default_cloudsim_space_policy())
        else:
            ec2_policy = policy.get("ec2")
            if not isinstance(ec2_policy, dict):
                policy["ec2"] = copy.deepcopy(_default_cloudsim_space_policy()["ec2"])
            else:
                ec2_policy.setdefault("launch", True)
                ec2_policy.setdefault("allowed_runtime_backends", _default_ec2_runtime_backends())
                ec2_policy.setdefault("allowed_amis", [])
    packs = state.setdefault("packs", {})
    for pack_id, pack in _default_packs().items():
        packs.setdefault(pack_id, copy.deepcopy(pack))
    ec2 = state.setdefault("ec2", {"instances": {}})
    instances = ec2.setdefault("instances", {})
    for instance_id, inst in instances.items():
        if not isinstance(inst, dict):
            continue
        inst.setdefault("instance_id", instance_id)
        inst.setdefault("state", "stopped")
        backend = str(inst.get("runtime_backend") or "").strip().lower()
        if backend in {"lxd", "lxd-shell"} or inst.get("container_id"):
            inst["runtime_backend"] = "lxd"
        elif backend in {"multipass", "multipass-shell"}:
            inst["runtime_backend"] = "multipass"
        else:
            inst["runtime_backend"] = "simulated"
        inst.setdefault("runtime_image", LXD_RUNTIME_IMAGE)
        inst.setdefault("container_id", "")
        inst.setdefault("container_name", f"cloudlearn-{instance_id}")
        inst.setdefault("container_port", LXD_CONSOLE_PORT)
        inst.setdefault("host_port", None)
        inst.setdefault("reservation_id", f"r-{instance_id.replace('i-', '')}")
        inst.setdefault("owner_id", AWS_ACCOUNT_ID)
        inst.setdefault("endpoint_url", "")
        inst.setdefault("container_status", "simulated" if inst["runtime_backend"] == "simulated" else "created")
        inst.setdefault("console_log", [])
        inst.setdefault("command", "")
        inst.setdefault("deployment_path", str((INSTANCE_WORK_ROOT / instance_id).resolve()))
        inst.setdefault("workspace", str((INSTANCE_WORK_ROOT / instance_id).resolve()))
        legacy_prefix = "sample"
        for key in tuple(f"{legacy_prefix}_app_{suffix}" for suffix in ("id", "name", "status", "command", "port", "kill_pattern", "error")):
            inst.pop(key, None)
        console_state = inst.get("console_state")
        if not isinstance(console_state, dict):
            inst["console_state"] = {"cwd": str((INSTANCE_WORK_ROOT / instance_id).resolve())}
    runtime = state.setdefault(
        "runtime",
        {"bundles": copy.deepcopy(_DEFAULT_RUNTIME_BUNDLES)},
    )
    runtime.setdefault("lxd", {"status": "missing", "message": "", "mode": "auto", "last_checked": ""})
    runtime.setdefault("multipass", {"status": "missing", "message": "", "mode": "auto", "last_checked": ""})
    federations = state.setdefault("federations", {"federations": {}, "links": {}, "tests": []})
    federations.setdefault("federations", {})
    federations.setdefault("links", {})
    federations.setdefault("tests", [])
    rds = state.setdefault("rds", {"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}, "events": []})
    rds.setdefault("db_instances", {})
    rds.setdefault("db_subnet_groups", {})
    rds.setdefault("db_parameter_groups", {})
    rds.setdefault("db_snapshots", {})
    rds.setdefault("events", [])
    state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
    apigw = state.setdefault("apigateway", {"apis": {}, "logs": []})
    apigw.setdefault("apis", {})
    apigw.setdefault("logs", [])
    state.setdefault("lambda", {"functions": {}, "events": [], "invocations": []})
    lambda_state = state.setdefault("lambda", {"functions": {}, "events": [], "invocations": []})
    for function_name, function in lambda_state.setdefault("functions", {}).items():
        if not isinstance(function, dict):
            continue
        function.setdefault("function_name", function_name)
        function.setdefault("permissions", [])
    sqs_state = state.setdefault("sqs", {"queues": {}, "events": []})
    sqs_state.setdefault("queues", {})
    sqs_state.setdefault("events", [])
    for queue_name, queue in sqs_state["queues"].items():
        if not isinstance(queue, dict):
            continue
        queue.setdefault("queue_name", queue_name)
        queue.setdefault("queue_type", "standard")
        queue.setdefault("fifo_queue", queue_name.endswith(".fifo"))
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
        queue.setdefault("created", now())
        queue.setdefault("last_modified", now())
    ddb_state = state.setdefault("dynamodb", {"tables": {}, "events": []})
    ddb_state.setdefault("tables", {})
    ddb_state.setdefault("events", [])
    for table_name, table in ddb_state["tables"].items():
        if not isinstance(table, dict):
            continue
        table.setdefault("table_name", table_name)
        table.setdefault("table_arn", _iam_dynamodb_table_arn(table_name))
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
        table.setdefault("created", now())
        table.setdefault("last_modified", now())
    buckets_state = state.setdefault("buckets", {})
    if isinstance(buckets_state, dict):
        for bucket_name, bucket_meta in buckets_state.items():
            if not isinstance(bucket_meta, dict):
                continue
            bucket_meta.setdefault("notifications", {
                "eventBridgeEnabled": False,
                "topicConfigurations": [],
                "queueConfigurations": [],
                "cloudFunctionConfigurations": [],
                "deliveries": [],
                "updatedAt": now(),
            })
    spaces_state = state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1"}})
    spaces_state.setdefault("spaces", {})
    spaces_state.setdefault("active_space_id", "")
    spaces_state.setdefault("settings", {})
    spaces_state["settings"].setdefault("max_spaces", 6)
    spaces_state["settings"].setdefault("default_provider", "aws")
    spaces_state["settings"].setdefault("default_region", "us-east-1")
    if not spaces_state["spaces"]:
        # "space-legacy" is preserved as the AWS default space ID for
        # backwards-compat — cloudsim_runtime_id and lxd_project_name
        # are derived from it. Display name is "aws-default" (the
        # documented v1.2.5 convention).
        legacy_space_id = "space-legacy"
        spaces_state["spaces"][legacy_space_id] = {
            "space_id": legacy_space_id,
            "name": "aws-default",
            "provider": "aws",
            "status": "running",
            "seed": state.get("license", {}).get("device_id") or "legacy",
            "owner_id": "local-user",
            "created_at": now(),
            "updated_at": now(),
            "cloudsim_runtime_id": "cloudsim-space-legacy",
            "lxd_project_name": "cl-space-legacy",
            "active_region": "us-east-1",
            "active_account": AWS_ACCOUNT_ID,
            "max_instances": 10,
            "max_memory_mb": 4096,
            "max_disk_mb": 20480,
            "estimated_memory_mb": 0,
            "estimated_disk_mb": 0,
            "estimated_runtime_mb": 0,
            "estimated_cost_notes": "Legacy workspace seeded from existing simulator state.",
            "runtime_count": 0,
            "ec2_count": len((state.get("ec2") or {}).get("instances", {})),
            "lambda_count": len((state.get("lambda") or {}).get("functions", {})),
            "rds_count": len((state.get("rds") or {}).get("db_instances", {})),
            "sqs_count": len((state.get("sqs") or {}).get("queues", {})),
            "dynamodb_count": len((state.get("dynamodb") or {}).get("tables", {})),
            "cloudsim": {"summary": {}, "events": [], "last_tick": "", "policy": copy.deepcopy(_default_cloudsim_space_policy())},
            "runtime": {"mode": "lxd", "instances": {}, "sandbox_count": 0},
            "resources": {},
            "events": [],
            "snapshots": [],
            "service_states": {
                "s3": {
                    "buckets": copy.deepcopy(buckets_state),
                    "objects": copy.deepcopy(state.get("objects", {})),
                    "multiparts": copy.deepcopy(state.get("multiparts", {})),
                },
                "ec2": copy.deepcopy(state.get("ec2", {"instances": {}})),
                "vpc": copy.deepcopy(state.get("vpc", {"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}})),
                "rds": copy.deepcopy(state.get("rds", {"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}, "events": []})),
                "apigateway": copy.deepcopy(state.get("apigateway", {"apis": {}, "logs": []})),
                "lambda": copy.deepcopy(state.get("lambda", {"functions": {}, "events": [], "invocations": []})),
                "sqs": copy.deepcopy(state.get("sqs", {"queues": {}, "events": []})),
                "dynamodb": copy.deepcopy(state.get("dynamodb", {"tables": {}, "events": []})),
            },
            "tags": {},
        }
        spaces_state["active_space_id"] = legacy_space_id
    # v2.0.7 (#427): idempotently ensure each of GCP + Azure has a default
    # space so pre-v1.2.5 single-space installs gain all 3 consoles on
    # upgrade — not only on fresh installs. Guarded by provider presence so it
    # never duplicates a space the user (or an API re-seed) already created.
    _existing_providers = {
        (_s.get("provider") or "").lower()
        for _s in spaces_state["spaces"].values()
    }
    for _prov, _sid, _label, _region in [
        ("gcp", "space-gcp-default", "gcp-default", "us-central1"),
        ("azure", "space-azure-default", "azure-default", "eastus"),
    ]:
        if _prov in _existing_providers:
            continue
        spaces_state["spaces"][_sid] = {
                "space_id": _sid,
                "name": _label,
                "provider": _prov,
                "status": "running",
                "seed": state.get("license", {}).get("device_id") or "default",
                "owner_id": "local-user",
                "created_at": now(),
                "updated_at": now(),
                "cloudsim_runtime_id": f"cloudsim-{_sid}",
                "lxd_project_name": f"cl-{_sid}",
                "active_region": _region,
                "active_account": AWS_ACCOUNT_ID,
                "max_instances": 10,
                "max_memory_mb": 4096,
                "max_disk_mb": 20480,
                "estimated_memory_mb": 0,
                "estimated_disk_mb": 0,
                "estimated_runtime_mb": 0,
                "estimated_cost_notes": f"Default {_prov.upper()} workspace.",
                "runtime_count": 0,
                "ec2_count": 0, "lambda_count": 0, "rds_count": 0,
                "sqs_count": 0, "dynamodb_count": 0,
                "cloudsim": {"summary": {}, "events": [], "last_tick": "", "policy": copy.deepcopy(_default_cloudsim_space_policy())},
                "runtime": {"mode": "lxd", "instances": {}, "sandbox_count": 0},
                "resources": {},
                "events": [],
                "snapshots": [],
                "service_states": {},
                "tags": {},
                "tenant_id": DEFAULT_TENANT_ID,
            }
    return state


# ── PLATFORM bootstrap ──────────────────────────────────────────────────────

PLATFORM = CloudLearnPlatform(STATE_FILE, LEGACY_STATE_FILE, _default_state)
STATE = _migrate_state(copy.deepcopy(PLATFORM.state))
PLATFORM.kernel.state.clear()
PLATFORM.kernel.state.update(STATE)
PLATFORM.persist()
STATE = PLATFORM.state
STATE_LOCK = PLATFORM.store.lock


# ── Tenant functions ────────────────────────────────────────────────────────

def tenants_state() -> dict:
    return STATE.setdefault("tenants", {"active_tenant_id": "", "tenants": {}})


def active_tenant_id() -> str:
    """Per-request tenant from ``X-CloudLearn-Tenant`` header if set, else the
    globally-active tenant, falling back to DEFAULT_TENANT_ID."""
    req_tid = (REQUEST_TENANT.get() or "").strip()
    if req_tid:
        return req_tid
    return tenants_state().get("active_tenant_id", "") or DEFAULT_TENANT_ID


def tenant_dict(tid: str) -> dict | None:
    t = tenants_state().get("tenants", {}).get(tid)
    return t if isinstance(t, dict) else None


def ensure_default_tenant() -> None:
    """Bootstrap: create the default tenant and tag every untagged space.
    Idempotent -- safe to call repeatedly (called once at startup)."""
    ts = tenants_state()
    tenants = ts.setdefault("tenants", {})
    if DEFAULT_TENANT_ID not in tenants:
        tenants[DEFAULT_TENANT_ID] = {
            "tenant_id": DEFAULT_TENANT_ID,
            "name": "Default Tenant",
            "license_tier": str((STATE.get("license") or {}).get("tier", "free")),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "settings": {"max_spaces": 6},
        }
    if not ts.get("active_tenant_id"):
        ts["active_tenant_id"] = DEFAULT_TENANT_ID
    spaces_map = STATE.setdefault("spaces", {}).setdefault("spaces", {})
    for sid, sp in spaces_map.items():
        if isinstance(sp, dict) and not sp.get("tenant_id"):
            sp["tenant_id"] = DEFAULT_TENANT_ID
    migrate_default_space_names()


# Rename map for the one-shot migration. Keys are the legacy display
# names that older builds shipped with; values are the v1.2.5+ names
# that match the documented "aws-default / gcp-default / azure-default"
# convention. We only rename a space if its CURRENT name matches the
# legacy string exactly — so users who renamed spaces themselves are
# untouched.
_LEGACY_NAME_RENAMES = {
    "space-legacy":       "aws-default",
    "space-gcp-default":  "gcp-default",
    "space-azure-default": "azure-default",
}
_LEGACY_NAME_PRIOR_NAMES = {
    "space-legacy":       "Legacy Workspace",
    "space-gcp-default":  "GCP Project",
    "space-azure-default": "Azure Subscription",
}


def migrate_default_space_names() -> None:
    """One-shot migration (v1.2.5): rename the three default-seeded spaces
    from their legacy display names ("Legacy Workspace", "GCP Project",
    "Azure Subscription") to the documented convention ("aws-default",
    "gcp-default", "azure-default"). Idempotent — only renames spaces whose
    current name still matches the legacy string, so any user-renamed
    spaces survive untouched."""
    spaces_map = STATE.setdefault("spaces", {}).setdefault("spaces", {})
    for sid, new_name in _LEGACY_NAME_RENAMES.items():
        sp = spaces_map.get(sid)
        if not isinstance(sp, dict):
            continue
        current = sp.get("name", "")
        legacy = _LEGACY_NAME_PRIOR_NAMES.get(sid, "")
        if current == legacy or current == "":
            sp["name"] = new_name
            sp["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


ensure_default_tenant()


def tenant_scoped_bucket(name: str) -> str:
    """Map a logical bucket name to a tenant+space-scoped physical name in the
    global fake-gcs byte store, so same-named buckets in different tenants (or
    different spaces within a tenant) do not collide."""
    if not name:
        return name
    tid = active_tenant_id() or DEFAULT_TENANT_ID
    sid = (spaces_state().get("active_space_id") or "")
    digest = hashlib.sha1(f"{tid}:{sid}:{name}".encode()).hexdigest()[:10]
    safe = re.sub(r"[^a-z0-9-]+", "-", str(name).lower()).strip("-") or "b"
    return f"cl-{safe[:32]}-{digest}"


def load_state() -> dict:
    return STATE


def persist_state() -> None:
    PLATFORM.persist()


def terraform_state() -> dict:
    tf = STATE.setdefault("terraform", {"plans": {}, "applies": {}, "imports": {}, "spaces": {}})
    tf.setdefault("plans", {})
    tf.setdefault("applies", {})
    tf.setdefault("imports", {})
    tf.setdefault("spaces", {})
    return tf


def terraform_space_state(space_id: str) -> dict:
    tf = terraform_state()
    spaces = tf.setdefault("spaces", {})
    space_state = spaces.setdefault(space_id, {})
    space_state.setdefault("plans", {})
    space_state.setdefault("applies", {})
    space_state.setdefault("imports", {})
    return space_state


def spaces_state() -> dict:
    ss = STATE.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1"}})
    ss.setdefault("spaces", {})
    ss.setdefault("active_space_id", "")
    ss.setdefault("settings", {})
    ss["settings"].setdefault("max_spaces", 6)
    ss["settings"].setdefault("default_provider", "aws")
    ss["settings"].setdefault("default_region", "us-east-1")
    ss["settings"].setdefault("max_memory_mb", 8192)
    ss["settings"].setdefault("max_disk_mb", 32768)
    return ss


# ── Activity logging ────────────────────────────────────────────────────────

_LAST_ACTIVITY_PRUNE_AT: float = 0.0
_ACTIVITY_PRUNE_MIN_INTERVAL_S: float = 300.0  # 5 minutes


def _prune_activity_log_if_due() -> None:
    """Drop events older than the active tier's ``activity_log_retention_hours``.
    Called from ``record_usage`` on a 5-minute interval."""
    global _LAST_ACTIVITY_PRUNE_AT
    _now_ts = time.time()
    if _now_ts - _LAST_ACTIVITY_PRUNE_AT < _ACTIVITY_PRUNE_MIN_INTERVAL_S:
        return
    _LAST_ACTIVITY_PRUNE_AT = _now_ts
    try:
        from core import tier_policy as _tp
        tier = active_tier()
        hours = int(_tp.policy_for(tier).get("activity_log_retention_hours") or 24)
        if hours <= 0:
            return
        cutoff_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z",
            time.gmtime(_now_ts - hours * 3600),
        )
        usage = PLATFORM.kernel.state.get("usage") or {}
        events = usage.get("events") or []
        if not isinstance(events, list) or not events:
            return
        kept = [e for e in events if isinstance(e, dict) and e.get("at", "") >= cutoff_iso]
        if len(kept) != len(events):
            usage["events"] = kept
    except Exception:
        pass  # Never let retention pruning break a write


def record_usage(event: str, detail: dict | None = None) -> None:
    payload = copy.deepcopy(detail or {})
    PLATFORM.record_event(event, payload)
    _prune_activity_log_if_due()
    # Audit export sinks (Enterprise tier)
    try:
        from core import audit_sinks as _as
        _as.emit(STATE, active_tenant_id(), {"event": event, "detail": payload, "at": now()})
    except Exception:
        pass
    try:
        from server import _cloudsim_refresh_bridge
        _cloudsim_refresh_bridge(event, payload)
    except Exception:
        pass


# ── SpaceScopedDictProxy ────────────────────────────────────────────────────

class _SpaceScopedDictProxy(MutableMapping):
    def __init__(self, service_key: str, default_factory, nested_key: str | None = None):
        self.service_key = service_key
        self.default_factory = default_factory
        self.nested_key = nested_key

    def _service_state(self) -> dict:
        ss = STATE.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1"}})
        active_id = ss.get("active_space_id", "")
        space = ss.get("spaces", {}).get(active_id, {}) if active_id else {}
        req_provider = str(REQUEST_PROVIDER.get() or "aws").lower().strip()
        active_tid = active_tenant_id()
        # STRUCTURAL ISOLATION:
        #   1. Cross-tenant access -- space.tenant_id must equal active_tenant_id.
        #   2. Cross-provider access -- space.provider must equal REQUEST_PROVIDER.
        # On mismatch, PIVOT to a real space matching the request (creating one
        # if none exists) rather than silently writing to a scratch dict -- that
        # bug caused AWS calls to "succeed" then vanish when the active space
        # was a GCP/Azure space.
        if isinstance(space, dict) and space and active_id:
            space_tid = space.get("tenant_id") or DEFAULT_TENANT_ID
            space_provider = str(space.get("provider") or "aws").lower().strip()
            if space_tid != active_tid or space_provider != req_provider:
                space = self._pivot_to_matching_space(ss, req_provider, active_tid)
                active_id = space.get("space_id", "") if space else ""
        if isinstance(space, dict) and space:
            service_states = space.setdefault("service_states", {})
            service_key = self.service_key if req_provider == "aws" else f"{req_provider}_{self.service_key}"
            service_state = service_states.setdefault(service_key, self.default_factory())
        else:
            # No active space at all -> legacy deployment-level fallback.
            service_state = STATE.setdefault(self.service_key, self.default_factory())
        return service_state

    def _pivot_to_matching_space(self, spaces_state: dict, req_provider: str, active_tid: str) -> dict:
        """Find the first existing space whose (tenant, provider) matches the
        request, or create one if none exists. Always returns a dict that
        belongs to the persistent spaces store (never a scratch dict)."""
        import uuid as _uuid
        from datetime import datetime as _dt
        for sid, s in (spaces_state.get("spaces", {}) or {}).items():
            if not isinstance(s, dict) or not s:
                continue
            stid = s.get("tenant_id") or DEFAULT_TENANT_ID
            sprov = str(s.get("provider") or "aws").lower().strip()
            if stid == active_tid and sprov == req_provider:
                s.setdefault("space_id", sid)
                return s
        # None exists -- create one inline so the resource has a home.
        new_id = f"space-auto-{req_provider}-{_uuid.uuid4().hex[:8]}"
        new_space = {
            "space_id":      new_id,
            "name":          f"{req_provider.upper()} workspace (auto)",
            "provider":      req_provider,
            "tenant_id":     active_tid,
            "service_states": {},
            "created_at":    _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "auto_created":  True,
        }
        spaces_state.setdefault("spaces", {})[new_id] = new_space
        return new_space

    def _target(self) -> dict:
        service_state = self._service_state()
        if self.nested_key is None:
            return service_state
        return service_state.setdefault(self.nested_key, {})

    def __getitem__(self, key):
        return self._target()[key]

    def __setitem__(self, key, value):
        self._target()[key] = value

    def __delitem__(self, key):
        del self._target()[key]

    def __iter__(self):
        return iter(self._target())

    def __len__(self):
        return len(self._target())

    def __contains__(self, key):
        return key in self._target()

    def get(self, key, default=None):
        return self._target().get(key, default)

    def setdefault(self, key, default=None):
        return self._target().setdefault(key, default)

    def pop(self, key, default=None):
        return self._target().pop(key, default)

    def update(self, *args, **kwargs):
        return self._target().update(*args, **kwargs)

    def clear(self):
        return self._target().clear()

    def keys(self):
        return self._target().keys()

    def items(self):
        return self._target().items()

    def values(self):
        return self._target().values()


# ── State proxy instances ───────────────────────────────────────────────────

buckets:    Dict[str, dict] = _SpaceScopedDictProxy("s3", lambda: {"buckets": {}, "objects": {}, "multiparts": {}}, "buckets")
objects:    Dict[str, dict] = _SpaceScopedDictProxy("s3", lambda: {"buckets": {}, "objects": {}, "multiparts": {}}, "objects")
multiparts: Dict[str, dict] = _SpaceScopedDictProxy("s3", lambda: {"buckets": {}, "objects": {}, "multiparts": {}}, "multiparts")

iam_state = STATE.setdefault("iam", {"users": {}, "groups": {}, "roles": {}, "policies": {}, "attachments": [], "identity_providers": {}, "account_settings": {"password_policy": {"minimum_length": 8, "require_symbols": True, "require_numbers": True, "require_uppercase": True, "require_lowercase": True}}})
iam_state.setdefault("users", {})
iam_state.setdefault("groups", {})
iam_state.setdefault("roles", {})
iam_state.setdefault("policies", {})
iam_state.setdefault("attachments", [])
iam_state.setdefault("identity_providers", {})
iam_state.setdefault("account_settings", {"password_policy": {"minimum_length": 8, "require_symbols": True, "require_numbers": True, "require_uppercase": True, "require_lowercase": True}})

ec2_state = _SpaceScopedDictProxy("ec2", lambda: {"instances": {}})
gcp_compute_state = _SpaceScopedDictProxy("gcp_compute", lambda: {"instances": {}, "instance_groups": {}, "disks": {}, "snapshots": {}, "images": {}, "operations": []})
gcp_storage_state = _SpaceScopedDictProxy("gcp_storage", lambda: {"buckets": {}, "objects": {}, "folders": {}, "transfers": {}, "policies": {}, "operations": []})
gcp_sql_state = _SpaceScopedDictProxy("gcp_sql", lambda: {"instances": {}, "backups": {}, "query_insights": {}, "operations": []})
gcp_pubsub_state = _SpaceScopedDictProxy("gcp_pubsub", lambda: {"topics": {}, "subscriptions": {}, "messages": {}, "schemas": {}, "operations": []})
gcp_firestore_state = _SpaceScopedDictProxy("gcp_firestore", lambda: {"databases": {}, "documents": {}, "indexes": {}, "operations": []})
gcp_functions_state = _SpaceScopedDictProxy("gcp_functions", lambda: {"functions": {}, "versions": {}, "invocations": [], "operations": []})
gcp_apigw_state = _SpaceScopedDictProxy("gcp_apigateway", lambda: {"apis": {}, "api_configs": {}, "gateways": {}, "operations": [], "logs": []})
gcp_vpc_state = _SpaceScopedDictProxy("gcp_vpc", lambda: {"networks": {}, "subnetworks": {}, "firewalls": {}, "routes": {}, "operations": []})
gcp_iam_state = _SpaceScopedDictProxy("gcp_iam", lambda: {"policies": {}, "service_accounts": {}, "bindings": [], "operations": []})

azure_arm_state = _SpaceScopedDictProxy("arm", lambda: {"resources": {}}, "resources")

vpc_state = _SpaceScopedDictProxy("vpc", lambda: {"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}})
rds_state = _SpaceScopedDictProxy("rds", lambda: {"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}, "events": []})
apigw_state = _SpaceScopedDictProxy("apigateway", lambda: {"apis": {}, "logs": []})
lambda_state = _SpaceScopedDictProxy("lambda", lambda: {"functions": {}, "events": [], "invocations": []})
sqs_state = _SpaceScopedDictProxy("sqs", lambda: {"queues": {}, "events": []})
ddb_state = _SpaceScopedDictProxy("dynamodb", lambda: {"tables": {}, "events": []})

runtime_state = STATE.setdefault(
    "runtime",
    {"bundles": copy.deepcopy(_DEFAULT_RUNTIME_BUNDLES)},
)
runtime_state.setdefault("lxd", {"status": "missing", "message": "", "mode": "auto", "last_checked": ""})

github_state = STATE.setdefault("github", {"connections": {}, "repos": {}, "deployments": {}})


def init_azure_state() -> None:
    """Inject the azure_arm_state proxy into the Azure services provider module.
    Must be called from server.py after importing this module."""
    from providers import azure_services as provider_azure_services
    provider_azure_services._state = azure_arm_state


# ── GCP helpers ─────────────────────────────────────────────────────────────

_GCP_CONSOLE_COLLECTIONS: dict[str, list[str]] = {
    "gcp_compute": ["instances", "instance_groups", "disks", "snapshots", "images"],
    "gcp_storage": ["buckets", "folders", "transfers", "policies"],
    "gcp_sql": ["instances", "backups", "query_insights"],
    "gcp_pubsub": ["topics", "subscriptions", "schemas"],
    "gcp_firestore": ["databases", "documents", "indexes"],
    "gcp_functions": ["functions", "versions"],
    "gcp_apigateway": ["apis", "api_configs", "configs", "gateways"],
    "gcp_vpc": ["networks", "subnetworks", "firewalls", "routes"],
}

_GCP_IAM_NESTED_COLLECTIONS = ["service_accounts", "policies", "users", "groups", "roles"]


def gcp_active_space_dict() -> dict:
    ss = spaces_state()
    active_id = ss.get("active_space_id", "")
    space = ss.get("spaces", {}).get(active_id, {}) if active_id else {}
    return space if isinstance(space, dict) else {}


def gcp_project_name(project: str | None) -> str:
    return str(project or "cloudlearn").strip() or "cloudlearn"


def gcp_record_matches_project(rec: dict, project: str) -> bool:
    """Mirror the per-service list filter: a falsy stored project matches any."""
    if not project:
        return True
    return str((rec or {}).get("project") or project) == project


def gcp_state_proxies() -> dict:
    """The space/provider-scoped state proxies, keyed by service."""
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


def azure_state_dict() -> dict:
    """The active space's Azure ARM resources dict, read independent of
    REQUEST_PROVIDER."""
    space = gcp_active_space_dict()
    if isinstance(space, dict) and space:
        return (space.setdefault("service_states", {})
                     .setdefault("azure_arm", {"resources": {}})
                     .setdefault("resources", {}))
    return STATE.setdefault("azure_arm", {"resources": {}}).setdefault("resources", {})


# ── Tier enforcement helpers ────────────────────────────────────────────────

_TIER_ENFORCE = os.environ.get("CLOUDLEARN_TIER_ENFORCE", "1").strip() not in ("0", "false", "")

_QUANTITY_COUNTER_PATHS: dict[str, list[tuple[str, str]]] = {
    "vm":              [("ec2", "instances"), ("gcp_compute", "instances")],
    "database":        [("rds", "db_instances"), ("gcp_sql", "instances")],
    "api_gateway":     [("apigateway", "apis"), ("gcp_apigateway", "apis")],
    "queue":           [("sqs", "queues"), ("gcp_pubsub", "topics")],
    "lambda_function": [("lambda", "functions"), ("gcp_functions", "functions")],
    "bucket":          [("gcp_storage", "buckets")],
}

_QUANTITY_AZURE_TYPES: dict[str, str] = {
    "vm":              "microsoft.compute/virtualmachines",
    "database":        "microsoft.sql/servers/databases",
    "bucket":          "microsoft.storage/storageaccounts",
    "queue":           "microsoft.servicebus/namespaces/queues",
    "api_gateway":     "microsoft.apimanagement/service",
    "lambda_function": "microsoft.web/sites",
}


def count_active_space_resources(resource_type: str) -> int:
    """Sum existing instances of resource_type across all providers in the
    currently-active space's service_states."""
    ss = STATE.get("spaces") or {}
    active_id = ss.get("active_space_id", "")
    if not active_id:
        return 0
    space = (ss.get("spaces") or {}).get(active_id) or {}
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

    # S3 buckets live in the GLOBAL ``buckets`` dict (proxied per-space).
    if resource_type == "bucket":
        try:
            total += len(buckets)
        except Exception:
            pass

    return total


_tier_cache: dict = {"tier": "", "verified_at": 0.0, "ttl": 60.0}


def active_tier() -> str:
    """Resolve active tier. In appliance mode, re-verifies cached JWT periodically."""
    # Fast path: use cache if fresh
    now = time.time()
    if _tier_cache["tier"] and (now - _tier_cache["verified_at"]) < _tier_cache["ttl"]:
        return _tier_cache["tier"]

    # Check if we have a cached JWT to verify (appliance mode)
    cached_jwt = STATE.get("license_jwt")
    if cached_jwt and appliance_mode_enabled():
        try:
            from core import license_remote as _lr
            claims = _lr.verify_license_jwt(cached_jwt, install_id=_lr.get_or_create_install_id(STATE))
            tier = str(claims.get("tier", "free"))
            _tier_cache.update({"tier": tier, "verified_at": now})
            return tier
        except Exception:
            _tier_cache.update({"tier": "free", "verified_at": now})
            return "free"

    # Non-appliance mode: read from state (original behavior)
    try:
        tenant = tenant_dict(active_tenant_id()) or {}
    except Exception:
        tenant = {}
    return str(tenant.get("license_tier")
               or (STATE.get("license") or {}).get("tier")
               or "free")


_FEATURE_LEVEL_ORDER: dict[str, list] = {
    "cost_simulation":           ["totals", "per_resource", "per_resource_and_chargeback"],
    "terraform_export":          ["basic", "full", "full_plus_import"],
    "terraform_deploy_to_real":  [False, "single_cloud", "multi_cloud"],
    "notifications":             [False, "webhook", "all_channels"],
}


def feature_level_meets(feature_name: str, current, required) -> bool:
    """True if the active tier's value for feature_name is >= required."""
    order = _FEATURE_LEVEL_ORDER.get(feature_name)
    if not order:
        return True
    try:
        return order.index(current) >= order.index(required)
    except ValueError:
        return True


def enforce_tier_feature(feature_name: str, *, min_level=None):
    """Raise HTTPException(403) if the active tier lacks ``feature_name``."""
    from fastapi import HTTPException
    tier = active_tier()
    from core import tier_policy as _tp
    result = _tp.check_feature(tier, feature_name)
    if not result.get("ok"):
        result["active_tier"] = tier
        result["docs"] = "https://cloudlearn.io/docs/tiers"
        raise HTTPException(status_code=403, detail=result)
    val = result.get("value")
    if min_level is not None and not feature_level_meets(feature_name, val, min_level):
        raise HTTPException(status_code=403, detail={
            "ok": False, "code": "tier_feature_level",
            "reason": f"{feature_name} requires level '{min_level}' or higher; active tier has '{val}'",
            "active_tier": tier, "feature": feature_name,
            "current_level": val, "required_level": min_level,
            "upgrade_to": _tp._next_tier(_tp.normalize_tier(tier)),
            "docs": "https://cloudlearn.io/docs/tiers",
        })
    return val


_SIZE_ORDER = ("nano", "small", "medium", "large", "xlarge", "huge")


def classify_instance_size(provider: str, instance_type: str) -> str | None:
    """Return one of _SIZE_ORDER for a (provider, instance_type) pair, or None."""
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


def enforce_size_cap(resource_kind: str, provider: str, instance_type: str) -> None:
    """Raise HTTPException(403) if ``instance_type`` exceeds the active tier's
    size ceiling for ``resource_kind``."""
    from fastapi import HTTPException
    cap_field = "max_vm_size_tier" if resource_kind == "vm" else "max_db_size_tier"
    tier = active_tier()
    from core import tier_policy as _tp
    p = _tp.policy_for(tier)
    cap = str(p.get(cap_field) or "huge").lower()
    if cap not in _SIZE_ORDER:
        return
    actual = classify_instance_size(provider, instance_type)
    if actual is None:
        return  # unknown -> fail-open
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
        return  # unknown size string in policy -> fail-open


def enforce_quantity_cap(resource_type: str) -> None:
    """Raise HTTPException(403) if creating one more ``resource_type`` would
    exceed the active tier's per-space cap.

    Honors CLOUDLEARN_TIER_ENFORCE=0 — the same escape hatch the service-lock
    middleware uses (core/middleware.py). Previously only service locks were
    bypassed, so quantity caps still fired with enforcement "disabled", which
    was surprising for dev/test/probe runs."""
    from fastapi import HTTPException
    if os.environ.get("CLOUDLEARN_TIER_ENFORCE", "1").strip() in ("0", "false", ""):
        return
    tier = active_tier()
    current = count_active_space_resources(resource_type)
    from core import tier_policy as _tp
    result = _tp.check_quantity(tier, resource_type, current)
    if not result["ok"]:
        result["active_tier"] = tier
        result["docs"] = "https://cloudlearn.io/docs/tiers"
        raise HTTPException(status_code=403, detail=result)


# ── Rate limiting state ─────────────────────────────────────────────────────

_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, tuple[float, float]] = {}   # tenant_id -> (tokens, last_refill_ts)
_RATE_BURST_MULT = 4.0


def rate_limit_tenant(tenant_id: str, rps: int) -> tuple[bool, float]:
    """Try to consume 1 token from the tenant's bucket. Returns
    ``(allowed, retry_after_seconds)``. ``rps <= 0`` means UNLIMITED."""
    if rps <= 0:
        return True, 0.0
    burst = float(rps) * _RATE_BURST_MULT
    _now_ts = time.time()
    with _RATE_LOCK:
        tokens, last = _RATE_BUCKETS.get(tenant_id, (burst, _now_ts))
        elapsed = _now_ts - last
        tokens = min(burst, tokens + elapsed * rps)
        if tokens >= 1.0:
            tokens -= 1.0
            _RATE_BUCKETS[tenant_id] = (tokens, _now_ts)
            return True, 0.0
        retry_after = max(0.001, (1.0 - tokens) / float(rps))
        _RATE_BUCKETS[tenant_id] = (tokens, _now_ts)
        return False, retry_after


RATE_LIMIT_BYPASS_PATHS = (
    "/healthz", "/favicon.ico", "/static/", "/assets/",
    "/api/runtime/branding/",  # public CSS endpoint; per-tenant gate would loop
)


# ── Provider-service resolution (for tier enforcement middleware) ───────────

def resolve_provider_service(request) -> tuple[str, str]:
    """Map a request -> (provider, service_key) for tier-enforcement lookup.

    Returns ('', '') when the request is not a provider-scoped operation
    (e.g. /api/spaces, /healthz, /console/*) -- the middleware lets those
    through unconditionally.
    """
    path = request.url.path
    target = request.headers.get("x-amz-target", "") or ""

    # GCP REST paths
    if path.startswith("/compute/v1/"):
        return "gcp", "compute"
    if path.startswith(("/storage/v1/", "/upload/storage/v1/", "/download/storage/v1/")):
        return "gcp", "storage"
    if path.startswith("/sql/v1beta4/"):
        return "gcp", "cloudsql"
    if path.startswith("/pubsub/v1/"):
        return "gcp", "pubsub"
    if path.startswith("/firestore/v1/"):
        return "gcp", "firestore"
    if path.startswith("/api/gcp/apigateway/"):
        return "gcp", "apigateway"
    # /v1/projects/{p}/... -- disambiguate by suffix
    if path.startswith("/v1/projects/"):
        if "/topics/" in path or "/subscriptions/" in path:
            return "gcp", "pubsub"
        if "/secrets/" in path:
            return "gcp", "secretmanager"
        if "/cryptoKeys/" in path or "/keyRings/" in path:
            return "gcp", "kms"
        if "/triggers/" in path or "/channels/" in path:
            return "gcp", "eventarc"
        if "/functions/" in path:
            return "gcp", "functions"
        if "/serviceAccounts" in path or "/iamPolicies" in path or ":getIamPolicy" in path:
            return "gcp", "iam"
        if "/databases/" in path or "/documents/" in path:
            return "gcp", "firestore"

    # Azure ARM paths
    if path.startswith("/subscriptions/"):
        if "/Microsoft.Compute/" in path:        return "azure", "vm"
        if "/Microsoft.Storage/" in path:        return "azure", "storage"
        if "/Microsoft.Sql/" in path:            return "azure", "sql"
        if "/Microsoft.DocumentDB/" in path:     return "azure", "cosmos"
        if "/Microsoft.Web/" in path:            return "azure", "functionapp"
        if "/Microsoft.ApiManagement/" in path:  return "azure", "apim"
        if "/Microsoft.Network/" in path:        return "azure", "vnet"
        if "/Microsoft.EventGrid/" in path:      return "azure", "eventgrid"
        if "/Microsoft.KeyVault/" in path:       return "azure", "keyvault"
        if "/Microsoft.ServiceBus/" in path:     return "azure", "servicebus"
        if "/Microsoft.Authorization/" in path:  return "azure", "rbac"
    # Azure data-plane
    if path.startswith("/azure-data/"):
        if "/keyvault/" in path:   return "azure", "keyvault"
        if "/eventgrid/" in path:  return "azure", "eventgrid"
        if "/servicebus/" in path: return "azure", "servicebus"
        if "/cosmos/" in path:     return "azure", "cosmos"
        if "/blob/" in path:       return "azure", "storage"
        if "/sql/" in path:        return "azure", "sql"

    # AWS -- X-Amz-Target dispatches first (JSON-RPC), then auth-scope.
    if target.startswith("DynamoDB_"):              return "aws", "dynamodb"
    if target.startswith("TrentService."):          return "aws", "kms"
    if target.startswith("secretsmanager."):        return "aws", "secretsmanager"
    if target.startswith("AWSEvents."):             return "aws", "eventbridge"
    if target.startswith("AmazonSQS."):             return "aws", "sqs"
    # Auth-scope service inference for query-protocol APIs
    auth = request.headers.get("authorization", "") or ""
    m = re.search(r"Credential=[^/]+/\d+/[^/]+/(\w+)/aws4_request", auth)
    if m:
        svc = m.group(1).lower()
        return "aws", svc

    return "", ""


# ── Backward-compatible aliases (used by server.py during migration) ────────

_now = now
_now_http = now_http
_iso_to_http_date = iso_to_http_date
_parse_utc_timestamp = parse_utc_timestamp
_id = id_gen
_public_ip = public_ip
_private_ip = private_ip
_iam_root_principal = iam_root_principal
_host_config_path = host_config_path
_host_config = host_config
_resolved_host_os = resolved_host_os
_parent_os = parent_os
_distribution_mode = distribution_mode
_appliance_mode_enabled = appliance_mode_enabled
_is_gcp_native_path = is_gcp_native_path
_is_azure_native_path = is_azure_native_path
_tenants_state = tenants_state
_active_tenant_id = active_tenant_id
_tenant_dict = tenant_dict
_ensure_default_tenant = ensure_default_tenant
_tenant_scoped_bucket = tenant_scoped_bucket
_load_state = load_state
_persist_state = persist_state
_terraform_state = terraform_state
_terraform_space_state = terraform_space_state
_spaces_state = spaces_state
_record_usage = record_usage
_gcp_active_space_dict = gcp_active_space_dict
_gcp_project_name = gcp_project_name
_gcp_record_matches_project = gcp_record_matches_project
_gcp_state_proxies = gcp_state_proxies
_azure_state_dict = azure_state_dict
_active_tier = active_tier
_feature_level_meets = feature_level_meets
_enforce_tier_feature = enforce_tier_feature
_classify_instance_size = classify_instance_size
_enforce_size_cap = enforce_size_cap
_enforce_quantity_cap = enforce_quantity_cap
_count_active_space_resources = count_active_space_resources
_rate_limit_tenant = rate_limit_tenant
_RATE_LIMIT_BYPASS_PATHS = RATE_LIMIT_BYPASS_PATHS
_resolve_provider_service = resolve_provider_service
