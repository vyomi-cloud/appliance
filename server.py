#!/usr/bin/env python3
"""
CloudLearn — S3 Simulator Bundle
Implements the AWS S3 REST API (path-style) so boto3/aws-cli work with
--endpoint-url http://localhost:9000

Also exposes a custom JSON API at /api/s3/* for the React UI.
UI served at: http://localhost:9000
"""

import base64
import copy
import asyncio
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
import threading
import socket
import uuid
from functools import partial
from collections import deque
from pathlib import Path
from datetime import datetime, timezone, timedelta
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
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRouter
from pydantic import BaseModel

from cloudlearn_platform import CloudLearnPlatform

app = FastAPI(title="CloudLearn S3 Simulator", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "x-amz-request-id", "x-amz-id-2", "Content-Range"],
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _now_http() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

STATE_VERSION = 3
STATE_FILE = Path(os.environ.get("CLOUDLEARN_STATE_FILE", Path(__file__).with_name(".cloudlearn_state.sqlite3")))
LEGACY_STATE_FILE = Path(os.environ.get("CLOUDLEARN_LEGACY_STATE_FILE", STATE_FILE.with_suffix(".pkl")))
STATE_LOCK = threading.RLock()
DOCKER_RUNTIME_IMAGE = os.environ.get("CLOUDLEARN_DOCKER_RUNTIME_IMAGE", "python:3.12-slim")
DOCKER_CONSOLE_PORT = 8080
EC2_TERMINATED_VISIBILITY_SECONDS = int(os.environ.get("CLOUDLEARN_EC2_TERMINATED_VISIBILITY_SECONDS", "60"))
INSTANCE_WORK_ROOT = Path(os.environ.get("CLOUDLEARN_DEPLOY_DIR", Path(__file__).with_name("deployments")))
SAMPLE_APP_ROOT = Path(__file__).with_name("sample_apps")
EC2_XML_NS = "http://ec2.amazonaws.com/doc/2016-11-15/"
RDS_XML_NS = "http://rds.amazonaws.com/doc/2014-10-31/"
AWS_ACCOUNT_ID = "123456789012"
ET.register_namespace("", EC2_XML_NS)
ET.register_namespace("rds", RDS_XML_NS)


def _default_packs() -> Dict[str, dict]:
    return {
        "cloudlearn.s3.basic": {
            "id": "cloudlearn.s3.basic",
            "type": "service",
            "version": "1.0.0",
            "provider": "agnostic",
            "coreProviderNeutral": True,
            "state": "available",
            "active": False,
            "api": {
                "protocol": "aws-like",
                "actions": ["CreateBucket", "PutObject", "GetObject", "DeleteObject", "ListObjects"],
                "requestSchemas": True,
                "responseSchemas": True,
                "errors": True,
                "pagination": True,
                "regionAware": True,
            },
        },
        "cloudlearn.iam.basic": {
            "id": "cloudlearn.iam.basic",
            "type": "service",
            "version": "1.0.0",
            "provider": "agnostic",
            "coreProviderNeutral": True,
            "state": "available",
            "active": False,
            "api": {
                "protocol": "aws-like",
                "actions": ["CreateUser", "CreateRole", "CreatePolicy", "AttachPolicy"],
                "requestSchemas": True,
                "responseSchemas": True,
                "errors": True,
                "pagination": False,
                "regionAware": False,
            },
        },
        "cloudlearn.ec2.basic": {
            "id": "cloudlearn.ec2.basic",
            "type": "service",
            "version": "1.0.0",
            "provider": "agnostic",
            "coreProviderNeutral": True,
            "state": "available",
            "active": False,
            "api": {
                "protocol": "aws-like",
                "actions": ["RunInstances", "StartInstances", "StopInstances", "TerminateInstances"],
                "requestSchemas": True,
                "responseSchemas": True,
                "errors": True,
                "pagination": True,
                "regionAware": True,
            },
        },
        "cloudlearn.vpc.basic": {
            "id": "cloudlearn.vpc.basic",
            "type": "service",
            "version": "1.0.0",
            "provider": "agnostic",
            "coreProviderNeutral": True,
            "state": "available",
            "active": False,
            "api": {
                "protocol": "aws-like",
                "actions": ["CreateVpc", "CreateSubnet", "CreateSecurityGroup", "CreateRouteTable"],
                "requestSchemas": True,
                "responseSchemas": True,
                "errors": True,
                "pagination": False,
                "regionAware": True,
            },
        },
        "cloudlearn.apigateway.basic": {
            "id": "cloudlearn.apigateway.basic",
            "type": "service",
            "version": "1.0.0",
            "provider": "agnostic",
            "coreProviderNeutral": True,
            "state": "available",
            "active": False,
            "api": {
                "protocol": "aws-like",
                "actions": ["CreateRestApi", "CreateResource", "PutMethod", "PutIntegration", "CreateDeployment", "CreateStage"],
                "requestSchemas": True,
                "responseSchemas": True,
                "errors": True,
                "pagination": False,
                "regionAware": True,
            },
        },
        "cloudlearn.runtime.python": {
            "id": "cloudlearn.runtime.python",
            "type": "runtime",
            "version": "1.0.0",
            "provider": "agnostic",
            "coreProviderNeutral": True,
            "state": "available",
            "active": False,
            "api": {
                "protocol": "aws-like",
                "actions": ["Deploy", "Invoke", "Restart"],
                "requestSchemas": True,
                "responseSchemas": True,
                "errors": True,
                "pagination": False,
                "regionAware": False,
            },
        },
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
            "issued_at": _now(),
            "status": "active",
        },
        "packs": _default_packs(),
        "deployments": {},
        "iam": {"users": {}, "roles": {}, "policies": {}, "attachments": []},
        "ec2": {"instances": {}},
        "vpc": {"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}},
        "apigateway": {"apis": {}, "logs": []},
        "rds": {
            "db_instances": {},
            "db_subnet_groups": {},
            "db_parameter_groups": {},
            "db_snapshots": {},
            "events": [],
        },
        "runtime": {
            "bundles": {"python": {"id": "cloudlearn.runtime.python", "installed": True, "active": False}},
            "docker": {"status": "missing", "message": "", "mode": "auto", "last_checked": ""},
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
        backend = inst.get("runtime_backend")
        if backend in {"docker", "docker-shell"} or inst.get("container_id"):
            inst["runtime_backend"] = "docker"
        else:
            inst["runtime_backend"] = "simulated"
        inst.setdefault("runtime_image", DOCKER_RUNTIME_IMAGE)
        inst.setdefault("container_id", "")
        inst.setdefault("container_name", f"cloudlearn-{instance_id}")
        inst.setdefault("container_port", DOCKER_CONSOLE_PORT)
        inst.setdefault("host_port", None)
        inst.setdefault("sample_app_id", "")
        inst.setdefault("sample_app_name", "")
        inst.setdefault("sample_app_status", "not deployed")
        inst.setdefault("sample_app_command", "")
        inst.setdefault("sample_app_port", DOCKER_CONSOLE_PORT)
        inst.setdefault("reservation_id", f"r-{instance_id.replace('i-', '')}")
        inst.setdefault("owner_id", AWS_ACCOUNT_ID)
        inst.setdefault("endpoint_url", "")
        inst.setdefault("container_status", "simulated" if inst["runtime_backend"] == "simulated" else "created")
        inst.setdefault("console_log", [])
        inst.setdefault("command", "")
        inst.setdefault("deployment_path", str((INSTANCE_WORK_ROOT / instance_id).resolve()))
        inst.setdefault("workspace", str((INSTANCE_WORK_ROOT / instance_id).resolve()))
        console_state = inst.get("console_state")
        if not isinstance(console_state, dict):
            inst["console_state"] = {"cwd": str((INSTANCE_WORK_ROOT / instance_id).resolve())}
    rds = state.setdefault("rds", {"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}, "events": []})
    rds.setdefault("db_instances", {})
    rds.setdefault("db_subnet_groups", {})
    rds.setdefault("db_parameter_groups", {})
    rds.setdefault("db_snapshots", {})
    rds.setdefault("events", [])
    apigw = state.setdefault("apigateway", {"apis": {}, "logs": []})
    apigw.setdefault("apis", {})
    apigw.setdefault("logs", [])
    return state


PLATFORM = CloudLearnPlatform(STATE_FILE, LEGACY_STATE_FILE, _default_state)
STATE = _migrate_state(copy.deepcopy(PLATFORM.state))
PLATFORM.kernel.state.clear()
PLATFORM.kernel.state.update(STATE)
PLATFORM.persist()
STATE = PLATFORM.state
STATE_LOCK = PLATFORM.store.lock


def _load_state() -> dict:
    return STATE


def _persist_state() -> None:
    PLATFORM.persist()


def _record_usage(event: str, detail: dict | None = None) -> None:
    PLATFORM.record_event(event, detail or {})


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
    try:
        PLATFORM.kernel.check_license_for_pack(pack_id)
    except PermissionError:
        raise HTTPException(403, detail="CapabilityLockedByTier")


def _ensure_capability(path: str) -> None:
    try:
        PLATFORM.ensure_capability(path)
    except LookupError:
        raise HTTPException(404, detail="CapabilityPackMissing")


def _catalog() -> list[dict]:
    return PLATFORM.catalog()


class LicenseSignupRequest(BaseModel):
    email: str
    user: str = "guest"
    tier: str = "free"
    device_id: str = ""


class ServiceActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = {}


class IAMUserRequest(BaseModel):
    user_name: str
    path: str = "/"


class IAMRoleRequest(BaseModel):
    role_name: str
    path: str = "/"
    assume_role_policy_document: dict[str, Any] = {}
    description: str = ""


class IAMPolicyRequest(BaseModel):
    policy_name: str
    document: dict[str, Any] = {}


class EC2InstanceRequest(BaseModel):
    name: str
    instance_type: str = "t3.micro"
    ami: str = "sim-ubuntu-22.04"
    runtime: str = "python"
    key_pair: str = ""
    subnet_id: str = ""
    vpc_id: str = ""
    security_group_ids: list[str] = []
    az: str = "us-east-1a"
    storage_gb: int = 8
    command: str = ""
    user_data: str = ""
    sample_app_id: str = ""


class EC2ConsoleInputRequest(BaseModel):
    data: str = ""


class EC2ConsoleCommandRequest(BaseModel):
    command: str = ""


class VpcRequest(BaseModel):
    name: str
    cidr_block: str = "10.0.0.0/16"
    encryption_controls: str = "None"
    tenancy: str = "default"
    ipv6_mode: str = "none"
    tags: list[dict[str, str]] | None = None


class SubnetRequest(BaseModel):
    vpc_id: str
    cidr_block: str
    availability_zone: str
    name: str = ""
    tags: list[dict[str, str]] | None = None


class SecurityGroupRequest(BaseModel):
    vpc_id: str
    group_name: str
    description: str = ""
    tags: list[dict[str, str]] | None = None


class RouteTableRequest(BaseModel):
    vpc_id: str
    name: str = ""
    tags: list[dict[str, str]] | None = None


class InternetGatewayRequest(BaseModel):
    name: str = ""
    tags: list[dict[str, str]] | None = None


class RouteRequest(BaseModel):
    destination_cidr: str = "0.0.0.0/0"
    target_type: str = "internet-gateway"
    target_id: str = ""


class SubnetAssociationRequest(BaseModel):
    subnet_id: str


class RDSDatabaseRequest(BaseModel):
    db_instance_identifier: str
    db_instance_class: str = "db.t3.micro"
    engine: str = "postgres"
    engine_version: str = ""
    master_username: str = "dbadmin"
    master_user_password: str = "Password123!"
    allocated_storage: int = 20
    storage_type: str = "gp3"
    vpc_id: str = ""
    db_subnet_group_name: str = ""
    db_parameter_group_name: str = ""
    availability_zone: str = "us-east-1a"
    publicly_accessible: bool = False
    multi_az: bool = False
    backup_retention_period: int = 7
    preferred_maintenance_window: str = "sun:03:00-sun:03:30"
    tags: list[dict[str, str]] | None = None
    security_group_ids: list[str] = []


class RDSSubnetGroupRequest(BaseModel):
    db_subnet_group_name: str
    db_subnet_group_description: str = ""
    vpc_id: str = ""
    subnet_ids: list[str] = []
    tags: list[dict[str, str]] | None = None


class RDSParameterGroupRequest(BaseModel):
    db_parameter_group_name: str
    family: str = "postgres16"
    description: str = ""
    tags: list[dict[str, str]] | None = None


class RDSSnapshotRequest(BaseModel):
    db_instance_identifier: str
    db_snapshot_identifier: str
    tags: list[dict[str, str]] | None = None


class RDSModifyRequest(BaseModel):
    db_instance_identifier: str
    db_instance_class: str | None = None
    allocated_storage: int | None = None
    backup_retention_period: int | None = None
    publicly_accessible: bool | None = None
    multi_az: bool | None = None
    engine_version: str | None = None
    master_user_password: str | None = None
    db_parameter_group_name: str | None = None
    preferred_maintenance_window: str | None = None
    apply_immediately: bool = True


class RDSRestoreSnapshotRequest(BaseModel):
    db_instance_identifier: str
    db_snapshot_identifier: str
    db_instance_class: str = "db.t3.micro"
    vpc_id: str = ""
    db_subnet_group_name: str = ""
    publicly_accessible: bool = False
    multi_az: bool = False
    tags: list[dict[str, str]] | None = None


class APIGatewayRequest(BaseModel):
    name: str
    description: str = ""
    endpoint_type: str = "REGIONAL"
    tags: list[dict[str, str]] | None = None


class APIGatewayResourceRequest(BaseModel):
    rest_api_id: str = ""
    parent_id: str = ""
    path_part: str = ""


class APIGatewayMethodRequest(BaseModel):
    rest_api_id: str = ""
    resource_id: str = ""
    http_method: str = "GET"
    authorization_type: str = "NONE"
    api_key_required: bool = False


class APIGatewayIntegrationRequest(BaseModel):
    rest_api_id: str = ""
    resource_id: str = ""
    http_method: str = "GET"
    type: str = "MOCK"
    uri: str = ""
    integration_http_method: str = "POST"
    response_body: str = ""
    status_code: int = 200
    content_type: str = "application/json"


class APIGatewayDeploymentRequest(BaseModel):
    rest_api_id: str = ""
    stage_name: str = ""
    description: str = ""


class APIGatewayStageRequest(BaseModel):
    rest_api_id: str = ""
    stage_name: str
    deployment_id: str = ""
    description: str = ""
    variables: list[dict[str, str]] | None = None


class DeploymentRequest(BaseModel):
    name: str
    source_url: str = ""
    runtime: str = "python"
    command: str = ""
    branch: str = "main"
    repo: str = ""


def _apigw_state() -> dict:
    return STATE.setdefault("apigateway", {"apis": {}, "logs": []})


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


AMI_CATALOG = [
    {
        "ami": "ami-amzn2023",
        "name": "Amazon Linux 2023",
        "os_family": "amazon-linux",
        "category": "Amazon",
        "default_runtime": "python",
        "container_image": "amazonlinux:2023",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Amazon Linux 2023 base image for lightweight apps.",
    },
    {
        "ami": "ami-amzn2",
        "name": "Amazon Linux 2",
        "os_family": "amazon-linux",
        "category": "Amazon",
        "default_runtime": "python",
        "container_image": "amazonlinux:2",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Amazon Linux 2 compatibility profile for legacy workloads.",
    },
    {
        "ami": "ami-amzn2023-minimal",
        "name": "Amazon Linux 2023 Minimal",
        "os_family": "amazon-linux",
        "category": "Amazon",
        "default_runtime": "python",
        "container_image": "amazonlinux:2023",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Amazon Linux 2023 minimal profile for smaller footprints.",
    },
    {
        "ami": "ami-ubuntu2204",
        "name": "Ubuntu Server 22.04 LTS",
        "os_family": "ubuntu",
        "category": "Ubuntu",
        "default_runtime": "python",
        "container_image": "ubuntu:22.04",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Ubuntu 22.04 base image for common app runtimes.",
    },
    {
        "ami": "ami-ubuntu2404",
        "name": "Ubuntu Server 24.04 LTS",
        "os_family": "ubuntu",
        "category": "Ubuntu",
        "default_runtime": "python",
        "container_image": "ubuntu:24.04",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Ubuntu 24.04 LTS profile for current-generation workloads.",
    },
    {
        "ami": "ami-ubuntu2004",
        "name": "Ubuntu Server 20.04 LTS",
        "os_family": "ubuntu",
        "category": "Ubuntu",
        "default_runtime": "python",
        "container_image": "ubuntu:20.04",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Ubuntu 20.04 LTS profile for older workloads and labs.",
    },
    {
        "ami": "ami-debian12",
        "name": "Debian 12",
        "os_family": "debian",
        "category": "Debian",
        "default_runtime": "python",
        "container_image": "debian:12",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Debian 12 profile for lean Linux instances.",
    },
    {
        "ami": "ami-debian11",
        "name": "Debian 11",
        "os_family": "debian",
        "category": "Debian",
        "default_runtime": "python",
        "container_image": "debian:11",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Debian 11 profile for compatibility-focused labs.",
    },
    {
        "ami": "ami-rhel9",
        "name": "Red Hat Enterprise Linux 9",
        "os_family": "rhel",
        "category": "Red Hat",
        "default_runtime": "python",
        "container_image": "rockylinux:9",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "RHEL 9 container profile for enterprise-style setups.",
    },
    {
        "ami": "ami-rocky9",
        "name": "Rocky Linux 9",
        "os_family": "rhel",
        "category": "Red Hat",
        "default_runtime": "python",
        "container_image": "rockylinux:9",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Rocky Linux 9 profile for RHEL-compatible workloads.",
    },
    {
        "ami": "ami-alma9",
        "name": "AlmaLinux 9",
        "os_family": "rhel",
        "category": "Red Hat",
        "default_runtime": "python",
        "container_image": "almalinux:9",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "AlmaLinux 9 profile for RHEL-compatible labs.",
    },
    {
        "ami": "ami-suse15",
        "name": "SUSE Linux Enterprise 15",
        "os_family": "suse",
        "category": "SUSE",
        "default_runtime": "python",
        "container_image": "opensuse/leap:15",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "SUSE Linux Enterprise 15 profile for enterprise Linux practice.",
    },
    {
        "ami": "ami-fedora42",
        "name": "Fedora 42",
        "os_family": "fedora",
        "category": "Fedora",
        "default_runtime": "python",
        "container_image": "fedora:42",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Fedora 42 profile for modern Linux and container labs.",
    },
    {
        "ami": "ami-windows2022",
        "name": "Windows Server 2022 Base",
        "os_family": "windows",
        "category": "Microsoft Windows",
        "default_runtime": "python",
        "container_image": "mcr.microsoft.com/windows/servercore:ltsc2022",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Windows Server 2022 base profile for Windows-focused labs.",
    },
    {
        "ami": "ami-windows2022-core",
        "name": "Windows Server 2022 Core",
        "os_family": "windows",
        "category": "Microsoft Windows",
        "default_runtime": "python",
        "container_image": "mcr.microsoft.com/windows/nanoserver:ltsc2022",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Windows Server 2022 Core profile for lightweight Windows workloads.",
    },
    {
        "ami": "ami-windows2025",
        "name": "Windows Server 2025 Base",
        "os_family": "windows",
        "category": "Microsoft Windows",
        "default_runtime": "python",
        "container_image": "mcr.microsoft.com/windows/servercore:ltsc2025",
        "runtime_image": DOCKER_RUNTIME_IMAGE,
        "description": "Windows Server 2025 base profile for newer Windows labs.",
    },
]

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


@app.middleware("http")
async def _capability_middleware(request: Request, call_next):
    _ensure_capability(request.url.path)
    response = await call_next(request)
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        try:
            _persist_state()
        except Exception:
            pass
    return response


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "tier": STATE["license"].get("tier", "free"), "packs_active": sum(1 for p in STATE["packs"].values() if p.get("active"))}


@app.on_event("startup")
def _startup_reconcile_ec2_state():
    for instance_id in _ec2_instance_ids():
        instance = ec2_state["instances"].get(instance_id)
        if not isinstance(instance, dict):
            continue
        if instance.get("runtime_backend") == "docker":
            _ensure_instance_workspace(instance)
            if _docker_available():
                _sync_docker_instance(instance)
            else:
                instance.setdefault("container_status", "docker-unavailable")
        if instance.get("sample_app_id"):
            try:
                if instance.get("state") == "running":
                    _ensure_sample_app_server(instance)
                else:
                    _stop_sample_app_server(instance_id)
            except Exception:
                instance["sample_app_status"] = "error"
    _prune_expired_terminated_instances()

# ── In-memory state ─────────────────────────────────────────────────────────
# buckets   : { name → { region, created, access, versioning, arn, tags:{} } }
# objects   : { bucket → { key → { data, size, content_type, last_modified, etag,
#                                   metadata:{}, tags:{}, storage_class } } }
# multiparts: { upload_id → { bucket, key, parts:{part_number → {data,etag}},
#                              content_type, metadata, initiated } }
buckets:    Dict[str, dict] = STATE.setdefault("buckets", {})
objects:    Dict[str, dict] = STATE.setdefault("objects", {})
multiparts: Dict[str, dict] = STATE.setdefault("multiparts", {})
iam_state = STATE.setdefault("iam", {"users": {}, "roles": {}, "policies": {}, "attachments": []})
ec2_state = STATE.setdefault("ec2", {"instances": {}})
vpc_state = STATE.setdefault("vpc", {"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}})
vpc_state.setdefault("internet_gateways", {})
rds_state = STATE.setdefault("rds", {"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}, "events": []})
rds_state.setdefault("db_instances", {})
rds_state.setdefault("db_subnet_groups", {})
rds_state.setdefault("db_parameter_groups", {})
rds_state.setdefault("db_snapshots", {})
rds_state.setdefault("events", [])
runtime_state = STATE.setdefault("runtime", {"bundles": {"python": {"id": "cloudlearn.runtime.python", "installed": True, "active": False}}})
runtime_state.setdefault("docker", {"status": "missing", "message": "", "mode": "auto", "last_checked": ""})
github_state = STATE.setdefault("github", {"connections": {}, "repos": {}, "deployments": {}})

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
    if instance.get("runtime_backend") == "docker":
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
    now = datetime.now(timezone.utc)
    removed = False
    with STATE_LOCK:
        instances = ec2_state.get("instances", {})
        for instance_id, instance in list(instances.items()):
            if not isinstance(instance, dict) or instance.get("state") != "terminated":
                continue
            if _terminated_visible(instance, now):
                continue
            instances.pop(instance_id, None)
            removed = True
        if removed:
            _persist_state()


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
            "Last-Modified": last_modified,
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


def _s3_write_object_version(bucket: str, key: str, version: dict, replace_version_id: str | None = None) -> dict:
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
    return entry


def _s3_insert_simple_delete_marker(bucket: str, key: str) -> dict:
    entry = _s3_ensure_object_entry(bucket, key, create=True)
    status = _s3_bucket_versioning_status(bucket)
    if status == "Disabled":
        objects.setdefault(bucket, {}).pop(key, None)
        return {}

    versions = entry.setdefault("versions", [])
    if status == "Suspended" and versions and str(versions[0].get("version_id", "null")) == "null":
        versions.pop(0)
    delete_marker = _s3_make_version_record(
        delete_marker=True,
        version_id=_s3_new_version_id(bucket) if status == "Enabled" else "null",
    )
    return _s3_write_object_version(bucket, key, delete_marker)


def _s3_delete_version(bucket: str, key: str, version_id: str) -> bool:
    entry = _s3_ensure_object_entry(bucket, key, create=False)
    if not entry:
        return False
    versions = entry.get("versions", [])
    next_versions = [v for v in versions if str(v.get("version_id")) != str(version_id)]
    if len(next_versions) == len(versions):
        return False
    if next_versions:
        entry["versions"] = next_versions
        _s3_refresh_object_entry(entry)
    else:
        objects.get(bucket, {}).pop(key, None)
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
        "buckets": [{"name": n, **{k: v for k, v in m.items() if k != "tags"}} for n, m in buckets.items()],
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
    }
    objects[name] = {}
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


class BucketVersioningRequest(BaseModel):
    status: str


@api.delete("/buckets/{name}")
def api_delete_bucket(name: str):
    if name not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    if objects.get(name):
        raise HTTPException(409, detail="BucketNotEmpty — delete all objects first")
    del buckets[name]
    del objects[name]
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
async def api_upload_object(bucket: str, file: UploadFile = File(...)):
    if bucket not in buckets:
        raise HTTPException(404, detail="NoSuchBucket")
    data = await file.read()
    key = file.filename or "unnamed"
    versioning_status = _s3_bucket_versioning_status(bucket)
    version_id = _s3_new_version_id(bucket) if versioning_status == "Enabled" else "null"
    version = _s3_make_version_record(
        data=data,
        content_type=file.content_type or "application/octet-stream",
        storage_class="STANDARD",
        metadata={},
        tags={},
        version_id=version_id,
        delete_marker=False,
    )
    replace_version_id = "__overwrite__" if versioning_status == "Disabled" else ("null" if versioning_status == "Suspended" else None)
    entry = _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id)
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
        return {"message": f"Object '{key}' deleted"}
    entry = _s3_insert_simple_delete_marker(bucket, key)
    return {
        "message": f"Delete marker created for '{key}'",
        "delete_marker": True,
        "version_id": entry.get("current_version_id", "null") if isinstance(entry, dict) else "null",
    }


app.include_router(api)


RUNTIME_HANDLES: Dict[str, Any] = {}
CONSOLE_SESSIONS: Dict[str, dict] = {}
CONSOLE_LOCK = threading.RLock()
APP_SERVERS: Dict[str, dict] = {}
APP_SERVER_LOCK = threading.RLock()
DOCKER_BOOTSTRAP_LOCK = threading.RLock()
DOCKER_BOOTSTRAP_THREAD: threading.Thread | None = None


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _public_ip() -> str:
    return f"203.0.113.{int(uuid.uuid4().hex[:2], 16) % 250 + 1}"


def _private_ip() -> str:
    return f"10.{int(uuid.uuid4().hex[:2], 16) % 250}.{int(uuid.uuid4().hex[2:4], 16) % 250}.{int(uuid.uuid4().hex[4:6], 16) % 250}"


SAMPLE_APP_MANIFESTS = {
    "hello-web": {
        "id": "hello-web",
        "name": "Hello Web",
        "description": "Static web app served from the instance workspace on port 8080.",
        "runtime": "python",
        "container_port": 8080,
        "start_command": "python -m http.server 8080",
        "kill_pattern": "http.server 8080",
        "template_dir": "hello-web",
        "badge": "Static site",
    },
    "hello-api": {
        "id": "hello-api",
        "name": "Hello API",
        "description": "Tiny JSON API built with the Python standard library on port 8080.",
        "runtime": "python",
        "container_port": 8080,
        "start_command": "python app.py",
        "kill_pattern": "app.py",
        "template_dir": "hello-api",
        "badge": "JSON API",
    },
}


def _docker_cli() -> str | None:
    return PLATFORM.runtime.docker_cli()


def _docker_available() -> bool:
    return PLATFORM.runtime.available()


def _docker_bootstrap_status() -> dict:
    return PLATFORM.runtime.bootstrap_status()


def _docker_bootstrap_target() -> dict:
    return PLATFORM.runtime.bootstrap_target()


def _run_bootstrap_command(args: list[str], timeout: int = 1200) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _apply_bootstrap_result(result: subprocess.CompletedProcess) -> None:
    output = (result.stdout or "") + (result.stderr or "")
    runtime_state["docker"]["last_checked"] = _now()
    runtime_state["docker"]["message"] = output[-1000:].strip()
    if result.returncode == 0:
        runtime_state["docker"]["status"] = "ready"
    else:
        runtime_state["docker"]["status"] = "error"


def _docker_bootstrap_worker() -> None:
    target = _docker_bootstrap_target()
    with DOCKER_BOOTSTRAP_LOCK:
        runtime_state["docker"]["status"] = "installing"
        runtime_state["docker"]["helper"] = target["helper"]
        runtime_state["docker"]["label"] = target["label"]
        runtime_state["docker"]["message"] = target["message"]
        runtime_state["docker"]["started_at"] = _now()
        _persist_state()

    try:
        if target["helper"] == "brew-colima":
            for command in target["commands"]:
                completed = _run_bootstrap_command(command, timeout=1800 if command[0] and "brew" in command[0] else 900)
                _apply_bootstrap_result(completed)
                _persist_state()
                if completed.returncode != 0:
                    break
        elif target["helper"] in {"apt-docker", "dnf-docker"}:
            for command in target["commands"]:
                completed = _run_bootstrap_command(command, timeout=1800)
                _apply_bootstrap_result(completed)
                _persist_state()
                if completed.returncode != 0:
                    break
        else:
            runtime_state["docker"]["status"] = "manual"
            runtime_state["docker"]["message"] = target["message"]
            _persist_state()
    except Exception as exc:
        runtime_state["docker"]["status"] = "error"
        runtime_state["docker"]["message"] = str(exc)
        runtime_state["docker"]["finished_at"] = _now()
        _persist_state()
        return

    runtime_state["docker"]["finished_at"] = _now()
    if _docker_available():
        runtime_state["docker"]["status"] = "ready"
        runtime_state["docker"]["message"] = "Docker runtime is ready."
    elif runtime_state["docker"].get("status") not in {"manual", "error"}:
        runtime_state["docker"]["status"] = "error"
        if not runtime_state["docker"].get("message"):
            runtime_state["docker"]["message"] = "Docker bootstrap finished without a usable Docker CLI."
    _persist_state()


def _start_docker_bootstrap() -> dict:
    return PLATFORM.runtime.start_bootstrap()


def _preferred_runtime_backend() -> str:
    return PLATFORM.runtime.preferred_backend()


def _docker_run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    binary = _docker_cli()
    if not binary:
        raise HTTPException(503, detail="DockerUnavailable")
    try:
        return subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise HTTPException(503, detail="DockerUnavailable")


def _docker_run_checked(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    completed = _docker_run(args, timeout=timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "DockerCommandFailed").strip()
        raise HTTPException(503, detail=detail)
    return completed


def _docker_inspect(ref: str) -> dict[str, Any] | None:
    completed = _docker_run(["inspect", ref], timeout=30)
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "[]")
    except Exception:
        return None
    if isinstance(payload, list) and payload:
        item = payload[0]
        if isinstance(item, dict):
            return item
    return None


def _docker_status(ref: str) -> str | None:
    completed = _docker_run(["inspect", "-f", "{{.State.Status}}", ref], timeout=30)
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip() or None


def _docker_container_exists(ref: str) -> bool:
    return _docker_status(ref) is not None


def _allocate_host_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _instance_workspace(instance_id: str) -> Path:
    return (INSTANCE_WORK_ROOT / instance_id).resolve()


def _sample_app_source(app_id: str) -> Path:
    source = (SAMPLE_APP_ROOT / app_id).resolve()
    if not source.exists() or not source.is_dir():
        raise HTTPException(404, detail="SampleAppNotFound")
    return source


def _sample_app_manifest(app_id: str) -> dict:
    manifest = SAMPLE_APP_MANIFESTS.get(app_id)
    if not manifest:
        raise HTTPException(404, detail="SampleAppNotFound")
    data = copy.deepcopy(manifest)
    data["template_dir"] = str((_sample_app_source(app_id)).resolve())
    return data


def _sample_app_catalog() -> list[dict]:
    return [_sample_app_manifest(app_id) for app_id in sorted(SAMPLE_APP_MANIFESTS)]


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
    ref = instance.get("container_id") or _container_name(instance)
    args = ["exec"]
    if detach:
        args.append("-d")
    if cwd:
        args += ["-w", cwd]
    args += [ref, "/bin/sh", "-lc", command]
    return _docker_run_checked(args, timeout=120)


def _copy_sample_app_files(app_id: str, workspace: Path) -> dict:
    source = _sample_app_source(app_id)
    workspace.mkdir(parents=True, exist_ok=True)
    for child in workspace.iterdir():
        if child.name in {".cloudlearn", ".cloudlearn_sample.json", ".cloudlearn_app.log"}:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(source, workspace, dirs_exist_ok=True)
    manifest = _sample_app_manifest(app_id)
    (workspace / ".cloudlearn_sample.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


class _QuietSimpleHTTPRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


class _HelloApiRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = {"ok": True, "service": "hello-api", "path": self.path}
        if self.path not in {"/", "/health", "/healthz"}:
            payload = {"message": "Hello from CloudLearn", "path": self.path}
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _sample_app_handler_factory(instance: dict):
    app_id = instance.get("sample_app_id") or ""
    workspace = _instance_workspace(instance["instance_id"])
    if app_id == "hello-api":
        return _HelloApiRequestHandler
    return partial(_QuietSimpleHTTPRequestHandler, directory=str(workspace))


def _stop_sample_app_server(instance_id: str, handle: dict | None = None) -> None:
    with APP_SERVER_LOCK:
        if handle is None:
            handle = APP_SERVERS.pop(instance_id, None)
        else:
            APP_SERVERS.pop(instance_id, None)
    if not handle:
        return
    server = handle.get("server")
    if server:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
    thread = handle.get("thread")
    if thread and thread.is_alive():
        try:
            thread.join(timeout=1)
        except Exception:
            pass


def _ensure_sample_app_server(instance: dict) -> None:
    if instance.get("runtime_backend") != "docker" or instance.get("state") != "running" or not instance.get("sample_app_id"):
        _stop_sample_app_server(instance["instance_id"])
        return

    workspace = _ensure_instance_workspace(instance)
    host_port = instance.get("host_port") or _allocate_host_port()
    instance["host_port"] = host_port
    instance["endpoint_url"] = f"http://127.0.0.1:{host_port}"
    handler = _sample_app_handler_factory(instance)

    with APP_SERVER_LOCK:
        existing = APP_SERVERS.get(instance["instance_id"])
        if existing and existing.get("port") == host_port and existing.get("app_id") == instance.get("sample_app_id"):
            server = existing.get("server")
            thread = existing.get("thread")
            if server and thread and thread.is_alive():
                instance["sample_app_status"] = "running"
                instance["endpoint_url"] = f"http://127.0.0.1:{host_port}"
                return
            APP_SERVERS.pop(instance["instance_id"], None)

        last_error = None
        existing_handle = None
        if existing:
            existing_handle = existing
            APP_SERVERS.pop(instance["instance_id"], None)
    if existing_handle:
        _stop_sample_app_server(instance["instance_id"], existing_handle)

    with APP_SERVER_LOCK:
        last_error = None
        for _ in range(5):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", host_port), handler)
                server.daemon_threads = True
                break
            except OSError as exc:
                last_error = exc
                try:
                    host_port = _allocate_host_port()
                    instance["host_port"] = host_port
                    instance["endpoint_url"] = f"http://127.0.0.1:{host_port}"
                except Exception:
                    instance["sample_app_status"] = "error"
                    instance["sample_app_error"] = str(last_error or "Failed to bind sample app port")
                    return
        else:
            instance["sample_app_status"] = "error"
            instance["sample_app_error"] = str(last_error or "Failed to bind sample app port")
            return

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        APP_SERVERS[instance["instance_id"]] = {
            "server": server,
            "thread": thread,
            "port": host_port,
            "app_id": instance.get("sample_app_id"),
            "workspace": str(workspace),
        }
        thread.start()
        instance["sample_app_status"] = "running"
        instance["sample_app_error"] = ""


def _deploy_sample_app(instance: dict, app_id: str, start_now: bool = True) -> dict:
    manifest = _sample_app_manifest(app_id)
    workspace = _ensure_instance_workspace(instance)
    _copy_sample_app_files(app_id, workspace)
    instance["sample_app_id"] = app_id
    instance["sample_app_name"] = manifest["name"]
    instance["sample_app_status"] = "deployed"
    instance["sample_app_command"] = manifest["start_command"]
    instance["sample_app_kill_pattern"] = manifest["kill_pattern"]
    instance["sample_app_port"] = manifest["container_port"]
    instance["command"] = manifest["start_command"]
    instance["user_data"] = instance.get("user_data", "")
    if instance.get("state") == "running" and start_now and instance.get("container_id"):
        _start_instance_command(instance)
        _ensure_sample_app_server(instance)
    return manifest


def _ensure_container(instance: dict) -> str:
    if not _docker_available():
        raise HTTPException(503, detail="DockerUnavailable")
    if instance.get("state") == "terminated":
        raise HTTPException(409, detail="InstanceTerminated")

    workspace = _ensure_instance_workspace(instance)
    instance.setdefault("runtime_image", DOCKER_RUNTIME_IMAGE)
    instance.setdefault("container_port", DOCKER_CONSOLE_PORT)
    if not instance.get("host_port"):
        instance["host_port"] = _allocate_host_port()
    instance.setdefault("container_name", f"cloudlearn-{instance['instance_id']}")
    instance["endpoint_url"] = f"http://127.0.0.1:{instance['host_port']}"

    container_ref = instance.get("container_id") or instance["container_name"]
    if _docker_container_exists(container_ref):
        if not instance.get("container_id"):
            instance["container_id"] = container_ref
        return container_ref

    if instance.get("sample_app_id"):
        _copy_sample_app_files(instance["sample_app_id"], workspace)

    publish_port = not bool(instance.get("sample_app_id"))
    run_args = [
        "create",
        "--name", instance["container_name"],
        "--label", f"cloudlearn.instance_id={instance['instance_id']}",
        "--label", f"cloudlearn.instance_name={instance.get('name', '')}",
        "--label", f"cloudlearn.runtime=ec2",
        "--label", f"cloudlearn.sample_app_id={instance.get('sample_app_id', '')}",
        "-w", _container_mount_path(),
        "-v", f"{workspace}:{_container_mount_path()}",
    ]
    if publish_port:
        run_args += ["-p", f"127.0.0.1:{instance['host_port']}:{instance['container_port']}"]
    run_args += [
        "-e", f"CLOUDLEARN_INSTANCE_ID={instance['instance_id']}",
        "-e", f"CLOUDLEARN_INSTANCE_NAME={instance.get('name', '')}",
        "-e", f"CLOUDLEARN_SAMPLE_APP={instance.get('sample_app_id', '')}",
        "-e", f"CLOUDLEARN_WORKSPACE={_container_mount_path()}",
        instance["runtime_image"],
        "python",
        "-c",
        "import time; time.sleep(10**9)",
    ]
    completed = _docker_run_checked(run_args, timeout=120)
    instance["container_id"] = (completed.stdout or "").strip() or instance["container_name"]
    instance["container_status"] = "created"
    return instance["container_id"]


def _start_instance_command(instance: dict) -> None:
    command = (instance.get("command") or "").strip()
    if not command:
        return
    container_cwd = _container_cwd(instance)
    kill_pattern = (instance.get("sample_app_kill_pattern") or "").strip()
    prefix = ""
    if kill_pattern:
        prefix = f"pkill -f {shlex.quote(kill_pattern)} >/dev/null 2>&1 || true; "
    boot_command = f"{prefix}nohup /bin/sh -lc {shlex.quote(command)} > .cloudlearn_app.log 2>&1 < /dev/null &"
    _container_exec(instance, boot_command, cwd=container_cwd, detach=False)
    instance["sample_app_status"] = "running" if instance.get("sample_app_id") else instance.get("sample_app_status", "running")


def _sync_docker_instance(instance: dict) -> None:
    if not _docker_available():
        instance.setdefault("container_status", "docker-unavailable")
        if instance.get("state") == "running":
            instance["state"] = "stopped"
        return
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        return
    status = _docker_status(ref)
    if not status:
        if instance.get("state") != "terminated":
            instance["state"] = "stopped"
        instance["container_status"] = "missing"
        return
    instance["container_status"] = status
    if status == "running":
        instance["state"] = "running"
    elif status in {"exited", "created", "paused"} and instance.get("state") == "running":
        instance["state"] = "stopped"


def _start_docker_instance(instance: dict) -> dict:
    _ensure_container(instance)
    container_ref = instance.get("container_id") or instance["container_name"]
    status = _docker_status(container_ref)
    if status != "running":
        _docker_run_checked(["start", container_ref], timeout=120)
    instance["state"] = "running"
    instance["container_status"] = "running"
    instance["console_backend"] = "docker-exec"
    instance["started_at"] = _now()
    instance["stopped_at"] = ""
    if instance.get("command"):
        _start_instance_command(instance)
    if instance.get("sample_app_id"):
        _ensure_sample_app_server(instance)
    instance["pid"] = None
    return instance


def _stop_docker_instance(instance: dict) -> dict:
    if not _docker_available():
        instance["state"] = "stopped"
        instance["stopped_at"] = _now()
        instance["container_status"] = "docker-unavailable"
        instance["pid"] = None
        return instance
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        raise HTTPException(409, detail="InstanceContainerMissing")
    status = _docker_status(ref)
    if status == "running":
        _docker_run_checked(["stop", ref], timeout=120)
    instance["state"] = "stopped"
    instance["stopped_at"] = _now()
    instance["container_status"] = "exited"
    instance["pid"] = None
    instance["sample_app_status"] = "stopped" if instance.get("sample_app_id") else instance.get("sample_app_status", "stopped")
    if instance.get("sample_app_id"):
        _stop_sample_app_server(instance["instance_id"])
    return instance


def _reboot_docker_instance(instance: dict) -> dict:
    ref = instance.get("container_id") or instance.get("container_name")
    if not ref:
        raise HTTPException(409, detail="InstanceContainerMissing")
    if _docker_status(ref) != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    instance["state"] = "rebooting"
    _docker_run_checked(["restart", ref], timeout=180)
    instance["state"] = "running"
    instance["container_status"] = "running"
    if instance.get("command"):
        _start_instance_command(instance)
    if instance.get("sample_app_id"):
        _ensure_sample_app_server(instance)
    instance["rebooted_at"] = _now()
    return instance


def _terminate_docker_instance(instance: dict) -> dict:
    if not _docker_available():
        instance["state"] = "terminated"
        instance["terminated_at"] = _now()
        instance["container_status"] = "docker-unavailable"
        instance["pid"] = None
        return instance
    ref = instance.get("container_id") or instance.get("container_name")
    if ref and _docker_container_exists(ref):
        _docker_run(["rm", "-f", ref], timeout=120)
    instance["state"] = "terminated"
    instance["terminated_at"] = _now()
    instance["container_status"] = "removed"
    instance["pid"] = None
    instance["sample_app_status"] = "terminated" if instance.get("sample_app_id") else instance.get("sample_app_status", "terminated")
    if instance.get("sample_app_id"):
        _stop_sample_app_server(instance["instance_id"])
    return instance


def _start_simulated_instance(instance: dict) -> dict:
    session = _spawn_console_session(instance)
    RUNTIME_HANDLES[instance["instance_id"]] = session["proc"]
    instance["state"] = "running"
    instance["started_at"] = _now()
    instance["stopped_at"] = ""
    instance["container_status"] = "simulated"
    instance["pid"] = session["proc"].pid
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
    return instance


def _terminate_simulated_instance(instance: dict) -> dict:
    _stop_simulated_instance(instance)
    instance["state"] = "terminated"
    instance["terminated_at"] = _now()
    return instance


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


def _normalize_tier(tier: str) -> str:
    tier = tier.lower().strip()
    if tier not in {"free", "pro", "max", "enterprise"}:
        raise HTTPException(400, detail="InvalidTier")
    return tier


def _cmd_prompt(instance: dict) -> str:
    if instance.get("runtime_backend") == "docker":
        name = instance.get("container_name") or instance.get("container_id") or instance.get("name") or instance["instance_id"]
        return f"root@{name}:/workspace#"
    return "C:\\Users\\Administrator>"


def _console_banner(instance: dict) -> str:
    return (
        "Microsoft Windows [Version 10.0.22631.0]\n"
        "(c) CloudLearn Simulator. All rights reserved.\n\n"
    )


def _instance_console_script(instance: dict) -> str:
    prompt = _cmd_prompt(instance)
    return (
        f"export PS1='{prompt}'\n"
        "export PROMPT_COMMAND=\n"
        "exec /bin/sh\n"
    )


def _spawn_docker_console_session(instance: dict) -> dict:
    instance_id = instance["instance_id"]
    binary = _docker_cli()
    if not binary:
        raise HTTPException(503, detail="DockerUnavailable")
    ref = instance.get("container_id") or instance.get("container_name") or instance_id
    if _docker_status(ref) != "running":
        raise HTTPException(409, detail="InstanceNotRunning")

    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if session and not session.get("closed") and session.get("proc") and session["proc"].poll() is None:
            instance["console_state"] = "running"
            instance["console_backend"] = session.get("console_backend", "docker-pty")
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
            "console_backend": "docker-pty",
            "affects_instance_state": False,
        }
        session["buffer"].append(
            f"docker exec -it {ref} /bin/sh\nConnected to container {ref} ({instance.get('runtime_image') or DOCKER_RUNTIME_IMAGE})\n"
        )
        CONSOLE_SESSIONS[instance_id] = session
        instance["pid"] = proc.pid
        instance["console_state"] = "running"
        instance["console_backend"] = "docker-pty"
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
    if instance.get("runtime_backend") == "docker":
        return _spawn_docker_console_session(instance)
    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
        if session and not session.get("closed") and session.get("proc") and session["proc"].poll() is None:
            instance["console_state"] = "running"
            instance["console_backend"] = session.get("console_backend", "pty-shell")
            return session

        if session:
            CONSOLE_SESSIONS.pop(instance_id, None)

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.update(
            {
                "CLOUDLEARN_INSTANCE_ID": instance_id,
                "CLOUDLEARN_INSTANCE_NAME": instance.get("name", ""),
                "CLOUDLEARN_AMI": instance.get("ami_name") or instance.get("ami") or "",
                "CLOUDLEARN_CONTAINER_IMAGE": instance.get("container_image") or "",
                "CL_COMMAND": instance.get("command") or "",
            }
        )
        script = _instance_console_script(instance)
        proc = subprocess.Popen(
            ["/bin/sh", "-lc", script],
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
            "console_backend": "pty-shell",
            "console_prompt": _cmd_prompt(instance),
        }
        session["buffer"].append(_console_banner(instance))
        CONSOLE_SESSIONS[instance_id] = session
        instance["pid"] = proc.pid
        instance["console_state"] = "running"
        instance["console_backend"] = "pty-shell"
        instance["state"] = "running"
        reader = threading.Thread(target=_console_reader_loop, args=(instance_id, session), daemon=True)
        session["reader_thread"] = reader
        reader.start()
        return session


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

    if instance.get("runtime_backend") == "docker":
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


@app.get("/api/catalog")
def api_catalog():
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
        "packs": _catalog(),
    }


@app.get("/api/packs")
def api_list_packs():
    return {"packs": _catalog(), "count": len(STATE["packs"])}


@app.get("/api/ec2/amis")
def api_ec2_amis():
    return {"amis": AMI_CATALOG, "count": len(AMI_CATALOG)}


@app.get("/api/ec2/runtime/docker")
def api_ec2_runtime_docker():
    status = _docker_bootstrap_status()
    status["mode"] = status.get("mode", "auto")
    status["next_step"] = "install" if not status["available"] else "ready"
    status["instructions"] = {
        "label": status.get("label", "Install Docker runtime"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


@app.post("/api/ec2/runtime/docker/bootstrap")
def api_ec2_runtime_docker_bootstrap():
    status = _start_docker_bootstrap()
    status["message"] = status.get("message") or "Docker bootstrap started."
    status["instructions"] = {
        "label": status.get("label", "Install Docker runtime"),
        "message": status.get("message", ""),
        "helper": status.get("helper", "manual"),
    }
    return status


@app.post("/api/packs/{pack_id}/activate")
def api_activate_pack(pack_id: str):
    pack = _activate_pack(pack_id)
    _record_usage("pack.activate", {"pack_id": pack_id})
    return {"message": "Pack activated", "pack": pack}


@app.post("/api/license/signup")
def api_license_signup(req: LicenseSignupRequest):
    tier = _normalize_tier(req.tier)
    payload = {
        "license_id": _id("lic"),
        "user": req.user,
        "email": req.email,
        "tier": tier,
        "credits": 100 if tier == "free" else 1000 if tier == "pro" else 10000 if tier == "max" else 50000,
        "device_id": req.device_id,
        "issued_at": _now(),
        "status": "active",
    }
    token = _sign_license(payload)
    payload["token"] = token
    STATE["license"] = payload
    _persist_state()
    return {"license": payload, "token": token}


@app.get("/api/license/status")
def api_license_status():
    return STATE["license"]


@app.post("/api/license/activate")
def api_license_activate(payload: dict[str, Any]):
    token = payload.get("token", "")
    license_data = _verify_license(token)
    license_data["token"] = token
    STATE["license"] = license_data
    _persist_state()
    return {"message": "License activated", "license": license_data}


@app.get("/api/iam/users")
def api_iam_list_users():
    return {"users": list(iam_state["users"].values()), "count": len(iam_state["users"])}


@app.post("/api/iam/users")
def api_iam_create_user(req: IAMUserRequest):
    user_id = _id("user")
    user = {"user_id": user_id, "user_name": req.user_name, "path": req.path, "created": _now(), "policies": []}
    iam_state["users"][user_id] = user
    _record_usage("iam.create_user", user)
    return user


@app.get("/api/iam/roles")
def api_iam_list_roles():
    return {"roles": list(iam_state["roles"].values()), "count": len(iam_state["roles"])}


@app.post("/api/iam/roles")
def api_iam_create_role(req: IAMRoleRequest):
    role_id = _id("role")
    role = {
        "role_id": role_id,
        "role_name": req.role_name,
        "path": req.path,
        "assume_role_policy_document": req.assume_role_policy_document,
        "description": req.description,
        "created": _now(),
        "policies": [],
    }
    iam_state["roles"][role_id] = role
    _record_usage("iam.create_role", role)
    return role


@app.get("/api/iam/policies")
def api_iam_list_policies():
    return {"policies": list(iam_state["policies"].values()), "count": len(iam_state["policies"])}


@app.post("/api/iam/policies")
def api_iam_create_policy(req: IAMPolicyRequest):
    policy_id = _id("policy")
    policy = {"policy_id": policy_id, "policy_name": req.policy_name, "document": req.document, "created": _now()}
    iam_state["policies"][policy_id] = policy
    _record_usage("iam.create_policy", policy)
    return policy


@app.post("/api/iam/attach-policy")
def api_iam_attach_policy(payload: dict[str, Any]):
    target_type = payload.get("target_type", "user")
    target_id = payload.get("target_id")
    policy_id = payload.get("policy_id")
    if policy_id not in iam_state["policies"]:
        raise HTTPException(404, detail="NoSuchPolicy")
    if target_type == "user":
        target = iam_state["users"].get(target_id)
    else:
        target = iam_state["roles"].get(target_id)
    if not target:
        raise HTTPException(404, detail="TargetNotFound")
    target.setdefault("policies", []).append(policy_id)
    iam_state["attachments"].append({"target_type": target_type, "target_id": target_id, "policy_id": policy_id, "at": _now()})
    _record_usage("iam.attach_policy", {"target_type": target_type, "target_id": target_id, "policy_id": policy_id})
    return {"message": "Policy attached", "target": target, "policy_id": policy_id}


@app.get("/api/iam/attachments")
def api_iam_list_attachments():
    return {"attachments": list(iam_state["attachments"]), "count": len(iam_state["attachments"])}


@app.get("/api/ec2/instances")
def api_ec2_list_instances():
    _prune_expired_terminated_instances()
    instance_ids = _ec2_instance_ids()
    if _docker_available():
        for instance_id in instance_ids:
            instance = ec2_state["instances"].get(instance_id)
            if isinstance(instance, dict) and instance.get("runtime_backend") == "docker":
                _sync_docker_instance(instance)
    else:
        for instance_id in instance_ids:
            instance = ec2_state["instances"].get(instance_id)
            if isinstance(instance, dict) and instance.get("runtime_backend") == "docker":
                instance.setdefault("container_status", "docker-unavailable")
                _sync_docker_instance(instance)
    _prune_expired_terminated_instances()
    instances = []
    for instance_id in _ec2_instance_ids():
        instance = ec2_state["instances"].get(instance_id)
        if isinstance(instance, dict):
            instances.append(instance)
    return {"instances": instances, "count": len(instances)}


@app.post("/api/ec2/instances")
def api_ec2_create_instance(req: EC2InstanceRequest):
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
    if not req.runtime or req.runtime == "python":
        req_runtime = profile.get("default_runtime", "python")
    else:
        req_runtime = req.runtime
    runtime_backend = _preferred_runtime_backend()
    host_port = _allocate_host_port() if runtime_backend == "docker" else None
    workspace = _instance_workspace(instance_id)
    workspace.mkdir(parents=True, exist_ok=True)
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
        "runtime_image": profile.get("runtime_image") or DOCKER_RUNTIME_IMAGE,
        "runtime": req_runtime,
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
        "container_download_state": "ready",
        "pid": None,
        "container_name": f"cloudlearn-{instance_id}" if runtime_backend == "docker" else "",
        "container_id": "",
        "container_port": DOCKER_CONSOLE_PORT,
        "host_port": host_port,
        "endpoint_url": f"http://127.0.0.1:{host_port}" if host_port else "",
        "console_state": {"cwd": str(workspace)},
        "console_log": [],
        "sample_app_id": getattr(req, "sample_app_id", ""),
        "sample_app_name": "",
        "sample_app_status": "not deployed",
        "sample_app_command": "",
        "sample_app_port": DOCKER_CONSOLE_PORT,
        "deployment_path": str(workspace),
        "workspace": str(workspace),
        "container_status": "created" if runtime_backend == "docker" else "simulated",
        "console_backend": "docker-exec" if runtime_backend == "docker" else "pty-shell",
        "console_prompt": _cmd_prompt({"runtime_backend": runtime_backend, "container_name": f"cloudlearn-{instance_id}", "container_id": ""}),
    }
    if instance["sample_app_id"]:
        manifest = _sample_app_manifest(instance["sample_app_id"])
        instance["sample_app_name"] = manifest["name"]
        instance["sample_app_command"] = manifest["start_command"]
        instance["sample_app_kill_pattern"] = manifest["kill_pattern"]
        instance["sample_app_port"] = manifest["container_port"]
        instance["sample_app_status"] = "deployed"
        instance["command"] = manifest["start_command"]
        _copy_sample_app_files(instance["sample_app_id"], workspace)
    if req.command:
        instance["public_ip"] = _public_ip()
    ec2_state["instances"][instance_id] = instance
    _record_usage("ec2.create_instance", instance)
    return instance


def _start_runtime_process(instance: dict) -> None:
    if instance.get("runtime_backend") == "docker":
        _start_docker_instance(instance)
        return
    _start_simulated_instance(instance)


def _stop_runtime_process(instance: dict) -> None:
    if instance.get("runtime_backend") == "docker":
        _stop_docker_instance(instance)
        return
    _stop_simulated_instance(instance)


def _reboot_runtime_process(instance: dict) -> None:
    if instance.get("runtime_backend") == "docker":
        _reboot_docker_instance(instance)
        return
    _stop_simulated_instance(instance)
    _start_simulated_instance(instance)


@app.post("/api/ec2/instances/{instance_id}/start")
def api_ec2_start_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    _start_runtime_process(instance)
    _record_usage("ec2.start_instance", {"instance_id": instance_id})
    return instance


@app.post("/api/ec2/instances/{instance_id}/stop")
def api_ec2_stop_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    _stop_runtime_process(instance)
    _record_usage("ec2.stop_instance", {"instance_id": instance_id})
    return instance


@app.post("/api/ec2/instances/{instance_id}/reboot")
def api_ec2_reboot_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    _reboot_runtime_process(instance)
    _record_usage("ec2.reboot_instance", {"instance_id": instance_id})
    return instance


@app.post("/api/ec2/instances/{instance_id}/terminate")
def api_ec2_terminate_instance(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    if instance.get("runtime_backend") == "docker":
        _terminate_docker_instance(instance)
    else:
        _terminate_simulated_instance(instance)
    _record_usage("ec2.terminate_instance", {"instance_id": instance_id})
    return instance


@app.get("/api/ec2/instances/{instance_id}/console")
def api_ec2_console(instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    if instance.get("runtime_backend") == "docker":
        if not _docker_available():
            return {
                "instance_id": instance_id,
                "state": instance.get("state", "unknown"),
                "console_state": instance.get("state", "unknown"),
                "backend": "docker-unavailable",
                "output": "Docker is not available on this host.\n",
                "runtime_image": instance.get("runtime_image", ""),
                "console_prompt": instance.get("console_prompt", _cmd_prompt(instance)),
                "sample_app_id": instance.get("sample_app_id", ""),
                "sample_app_name": instance.get("sample_app_name", ""),
                "sample_app_status": instance.get("sample_app_status", ""),
                "endpoint_url": instance.get("endpoint_url", ""),
            }
        _sync_docker_instance(instance)
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
            "backend": "docker-exec",
            "output": output,
            "container_id": instance.get("container_id", ""),
            "container_status": instance.get("container_status", ""),
            "runtime_image": instance.get("runtime_image", ""),
            "console_prompt": instance.get("console_prompt", _cmd_prompt(instance)),
            "sample_app_id": instance.get("sample_app_id", ""),
            "sample_app_name": instance.get("sample_app_name", ""),
            "sample_app_status": instance.get("sample_app_status", ""),
            "endpoint_url": instance.get("endpoint_url", ""),
        }
    with CONSOLE_LOCK:
        session = CONSOLE_SESSIONS.get(instance_id)
    if instance.get("state") == "running" and (not session or session.get("closed") or not session.get("proc") or session["proc"].poll() is not None):
        _spawn_console_session(instance)
    return _console_snapshot(instance_id)


@app.post("/api/ec2/instances/{instance_id}/console/input")
def api_ec2_console_input(instance_id: str, req: EC2ConsoleInputRequest):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    if instance.get("runtime_backend") == "docker":
        _sync_docker_instance(instance)
    if instance.get("state") != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    result = _console_execute(instance, req.data)
    _record_usage("ec2.console_command", {"instance_id": instance_id, "command": req.data, "exit_code": result["exit_code"]})
    return {"message": "Console command executed", "instance_id": instance_id, **result}


@app.post("/api/ec2/instances/{instance_id}/console/exec")
def api_ec2_console_exec(instance_id: str, req: EC2ConsoleCommandRequest):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    if instance.get("runtime_backend") == "docker":
        _sync_docker_instance(instance)
    if instance.get("state") != "running":
        raise HTTPException(409, detail="InstanceNotRunning")
    result = _console_execute(instance, req.command)
    _record_usage("ec2.console_command", {"instance_id": instance_id, "command": req.command, "exit_code": result["exit_code"]})
    return {"message": "Console command executed", "instance_id": instance_id, **result}


@app.get("/api/ec2/sample-apps")
def api_ec2_sample_apps():
    return {"sample_apps": _sample_app_catalog(), "count": len(SAMPLE_APP_MANIFESTS)}


@app.post("/api/ec2/instances/{instance_id}/sample-apps/{app_id}/deploy")
def api_ec2_deploy_sample_app(instance_id: str, app_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        raise HTTPException(404, detail="NoSuchInstance")
    manifest = _deploy_sample_app(instance, app_id, start_now=False)
    if instance.get("state") == "running" and instance.get("container_id"):
        _start_instance_command(instance)
        _ensure_sample_app_server(instance)
    _record_usage("ec2.deploy_sample_app", {"instance_id": instance_id, "sample_app_id": app_id})
    return {
        "message": "Sample app deployed",
        "instance_id": instance_id,
        "sample_app": manifest,
        "endpoint_url": instance.get("endpoint_url", ""),
        "command": instance.get("command", ""),
        "workspace": instance.get("workspace", ""),
    }


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
    min_count = int(params.get("MinCount", params.get("Mincount", 1)) or 1)
    max_count = int(params.get("MaxCount", params.get("Maxcount", min_count)) or min_count)
    count = max(min_count, max_count)
    image_id = str(params.get("ImageId", "ami-amzn2023"))
    instance_type = str(params.get("InstanceType", "t3.micro"))
    key_name = str(params.get("KeyName", ""))
    subnet_id = str(params.get("SubnetId", params.get("Placement.SubnetId", "")))
    az = str(params.get("Placement.AvailabilityZone", params.get("AvailabilityZone", "us-east-1a")))
    vpc_id = str(params.get("VpcId", ""))
    sample_app_id = str(params.get("TagSpecification.1.SampleAppId", ""))
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
            sample_app_id=sample_app_id,
        )
        instance = api_ec2_create_instance(req)
        instance["state"] = "pending"
        instance["instanceState"] = "pending"
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


def _ec2_query_state_change_response(root_name: str, changes: list[tuple[dict, str, str | None]]) -> Response:
    def build(root: ET.Element) -> None:
        instances_set = _ec2_sub(root, "instancesSet")
        for instance, previous_state, current_state in changes:
            instances_set.append(_ec2_instance_state_change_xml(instance, previous_state, current_state))

    return _ec2_success_response(root_name, build)


@app.api_route("/ec2", methods=["GET", "POST"], include_in_schema=False)
@app.api_route("/api/ec2/aws", methods=["GET", "POST"], include_in_schema=False)
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
                _start_runtime_process(instance)
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
                _terminate_runtime_process = _terminate_docker_instance if instance.get("runtime_backend") == "docker" else _terminate_simulated_instance
                _terminate_runtime_process(instance)
                changes.append((instance, previous, "shutting-down"))
            return _ec2_query_state_change_response("TerminateInstancesResponse", changes)
    except HTTPException as exc:
        code = str(exc.detail).split(":", 1)[0]
        message = str(exc.detail)
        return _ec2_error_response(code, message, exc.status_code)

    return _ec2_error_response("InvalidAction", f"The action '{action}' is not implemented by the simulator.", 400)


@app.websocket("/ws/ec2/instances/{instance_id}/console")
async def ws_ec2_console(websocket: WebSocket, instance_id: str):
    instance = ec2_state["instances"].get(instance_id)
    if not instance:
        await websocket.close(code=1008)
        return

    if instance.get("runtime_backend") == "docker":
        _sync_docker_instance(instance)

    await websocket.accept()
    if instance.get("state") != "running":
        await websocket.send_text("Instance console is not active. Start the instance first.\n")
        await websocket.close()
        return

    prompt = _cmd_prompt(instance) + " "
    if instance.get("runtime_backend") == "docker":
        container_name = instance.get("container_name") or instance.get("container_id") or instance_id
        runtime_image = instance.get("runtime_image") or DOCKER_RUNTIME_IMAGE
        await websocket.send_text(
            f"docker exec -it {container_name} /bin/sh\n"
            f"Connected to container {container_name} ({runtime_image})\n"
        )
    else:
        await websocket.send_text("Local EC2 simulator shell attached.\n")
        await websocket.send_text(
            "Microsoft Windows [Version 10.0.22631.0]\n"
            "(c) CloudLearn Simulator. All rights reserved.\n\n"
            f"{prompt}"
        )

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
                if instance.get("runtime_backend") == "docker":
                    await websocket.send_text("logout\n")
                else:
                    await websocket.send_text("logout\n")
                break

            try:
                if instance.get("runtime_backend") == "docker":
                    result = _console_execute(instance, command)
                    transcript = ""
                    if result.get("output"):
                        transcript += result["output"]
                        if not transcript.endswith("\n"):
                            transcript += "\n"
                    transcript += prompt
                    await websocket.send_text(transcript)
                else:
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


@app.websocket("/ws/runtime-console/{instance_id}")
async def ws_runtime_console(websocket: WebSocket, instance_id: str):
    await ws_ec2_console(websocket, instance_id)


@app.get("/api/vpc/vpcs")
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


@app.post("/api/vpc/vpcs")
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


@app.delete("/api/vpc/vpcs/{vpc_id}")
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


@app.post("/api/vpc/subnets")
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


@app.post("/api/vpc/security-groups")
def api_vpc_create_security_group(req: SecurityGroupRequest):
    if req.vpc_id not in vpc_state["vpcs"]:
        raise HTTPException(404, detail="NoSuchVpc")
    sg_id = _id("sg")
    sg = {"security_group_id": sg_id, "vpc_id": req.vpc_id, "group_name": req.group_name, "description": req.description, "ingress": [], "egress": [{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr": "0.0.0.0/0", "source_sg": "", "description": "allow all outbound traffic", "created": _now()}], "is_default": False, "created": _now(), "tags": req.tags or []}
    vpc_state["security_groups"][sg_id] = sg
    _record_usage("vpc.create_security_group", sg)
    return sg


@app.post("/api/vpc/security-groups/{sg_id}/ingress")
def api_vpc_add_ingress(sg_id: str, payload: dict[str, Any]):
    sg = vpc_state["security_groups"].get(sg_id)
    if not sg:
        raise HTTPException(404, detail="NoSuchSecurityGroup")
    rule = {"protocol": payload.get("protocol", "tcp"), "from_port": payload.get("from_port", 0), "to_port": payload.get("to_port", 65535), "cidr": payload.get("cidr", "0.0.0.0/0"), "source_sg": payload.get("source_sg", ""), "description": payload.get("description", ""), "created": _now()}
    sg.setdefault("ingress", []).append(rule)
    _record_usage("vpc.add_ingress", {"sg_id": sg_id, "rule": rule})
    return sg


@app.get("/api/vpc/subnets")
def api_vpc_list_subnets():
    return {"subnets": list(vpc_state["subnets"].values()), "count": len(vpc_state["subnets"])}


@app.get("/api/vpc/security-groups")
def api_vpc_list_security_groups():
    return {"security_groups": list(vpc_state["security_groups"].values()), "count": len(vpc_state["security_groups"])}


@app.get("/api/vpc/route-tables")
def api_vpc_list_route_tables():
    return {"route_tables": list(vpc_state["route_tables"].values()), "count": len(vpc_state["route_tables"])}


@app.post("/api/vpc/route-tables")
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


@app.get("/api/vpc/internet-gateways")
def api_vpc_list_internet_gateways():
    return {"internet_gateways": list(vpc_state["internet_gateways"].values()), "count": len(vpc_state["internet_gateways"])}


@app.post("/api/vpc/internet-gateways")
def api_vpc_create_internet_gateway(req: InternetGatewayRequest):
    igw_id = _id("igw")
    igw = {"internet_gateway_id": igw_id, "name": req.name or igw_id, "attached_vpc_id": "", "created": _now(), "tags": req.tags or []}
    vpc_state["internet_gateways"][igw_id] = igw
    _record_usage("vpc.create_internet_gateway", igw)
    return igw


@app.post("/api/vpc/internet-gateways/{igw_id}/attach")
def api_vpc_attach_internet_gateway(igw_id: str, payload: dict[str, Any]):
    vpc_id = payload.get("vpc_id", "")
    igw = _vpc_attach_internet_gateway_record(igw_id, vpc_id)
    _record_usage("vpc.attach_internet_gateway", {"igw_id": igw_id, "vpc_id": vpc_id})
    return igw


@app.post("/api/vpc/route-tables/{rt_id}/routes")
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


@app.post("/api/vpc/route-tables/{rt_id}/associate-subnet")
def api_vpc_associate_subnet(rt_id: str, req: SubnetAssociationRequest):
    _vpc_associate_subnet_to_route_table(rt_id, req.subnet_id)
    _record_usage("vpc.associate_subnet", {"route_table_id": rt_id, "subnet_id": req.subnet_id})
    return vpc_state["route_tables"][rt_id]


@app.get("/api/vpc/vpcs/{vpc_id}/resources")
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
    igw = vpc_state["internet_gateways"].get(igw_id)
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
    if not _docker_available():
        raise HTTPException(503, detail="DockerUnavailable")
    completed = _docker_run(["image", "inspect", image], timeout=30)
    if completed.returncode == 0:
        return
    _docker_run_checked(["pull", image], timeout=1800)


def _rds_runtime_ensure_container(db: dict) -> str:
    if not _docker_available():
        raise HTTPException(503, detail="DockerUnavailable")

    db_id = db["db_instance_identifier"]
    engine = (db.get("engine") or "postgres").lower()
    image = _rds_runtime_image(engine, db.get("engine_version"))
    container_name = db.get("container_name") or _rds_runtime_container_name(db_id)
    host_port = int(db.get("host_port") or _allocate_host_port())
    container_port = _rds_runtime_engine_port(engine)
    dirs = _rds_runtime_prepare_dirs(db_id)

    _rds_runtime_pull_image(image)

    db["runtime_backend"] = "docker"
    db["runtime_image"] = image
    db["container_name"] = container_name
    db["host_port"] = host_port
    db["container_port"] = container_port
    db["endpoint_address"] = "127.0.0.1"
    db["endpoint_port"] = host_port
    db["endpoint_url"] = f"127.0.0.1:{host_port}"

    ref = db.get("container_id") or container_name
    if _docker_container_exists(ref):
        if not db.get("container_id"):
            db["container_id"] = ref
        return ref

    run_args = [
        "create",
        "--name", container_name,
        "--label", f"cloudlearn.db_instance_identifier={db_id}",
        "--label", "cloudlearn.runtime=rds",
        "--label", f"cloudlearn.engine={engine}",
    ]
    if engine == "postgres":
        run_args += [
            "-v", f"{_rds_runtime_data_volume(db_id)}:/var/lib/postgresql/data",
            "-e", f"POSTGRES_USER={db.get('master_username') or 'dbadmin'}",
            "-e", f"POSTGRES_PASSWORD={db.get('master_user_password') or 'Password123!'}",
            "-e", f"POSTGRES_DB={db_id}",
            "-p", f"127.0.0.1:{host_port}:{container_port}",
            image,
        ]
    else:
        init_sql = _rds_runtime_mysql_init_sql(db)
        (dirs["init"] / "init.sql").write_text(init_sql, encoding="utf-8")
        run_args += [
            "-v", f"{_rds_runtime_data_volume(db_id)}:/var/lib/mysql",
            "-v", f"{dirs['init']}:/docker-entrypoint-initdb.d:ro",
            "-e", f"MYSQL_ROOT_PASSWORD={db.get('master_user_password') or 'Password123!'}",
            "-e", f"MYSQL_DATABASE={db_id}",
            "-e", "MYSQL_ROOT_HOST=%",
            "-p", f"127.0.0.1:{host_port}:{container_port}",
            image,
        ]

    completed = _docker_run_checked(run_args, timeout=300)
    db["container_id"] = (completed.stdout or "").strip() or container_name
    db["container_status"] = "created"
    return db["container_id"]


def _rds_runtime_start(db: dict) -> dict:
    if not _docker_available():
        db["runtime_backend"] = "simulated"
        db["runtime_image"] = _rds_runtime_image(db.get("engine", "postgres"), db.get("engine_version"))
        db["container_name"] = db.get("container_name") or _rds_runtime_container_name(db["db_instance_identifier"])
        db["container_status"] = "docker-unavailable"
        db["endpoint_address"] = db.get("endpoint_address") or f"{db['db_instance_identifier']}.rds.local"
        db["endpoint_port"] = db.get("endpoint_port") or _rds_runtime_engine_port(db.get("engine", "postgres"))
        db["endpoint_url"] = db.get("endpoint_url") or f"{db['endpoint_address']}:{db['endpoint_port']}"
        return db
    ref = _rds_runtime_ensure_container(db)
    if _docker_status(ref) != "running":
        _docker_run_checked(["start", ref], timeout=300)
    db["db_instance_status"] = "available"
    db["container_status"] = "running"
    db["latest_restorable_time"] = _now()
    db["updated"] = _now()
    return db


def _rds_runtime_stop(db: dict) -> dict:
    if not _docker_available():
        db["runtime_backend"] = "simulated"
        db["db_instance_status"] = "stopped"
        db["container_status"] = "docker-unavailable"
        db["updated"] = _now()
        return db
    ref = db.get("container_id") or db.get("container_name")
    if not ref:
        raise HTTPException(409, detail="DBInstanceContainerMissing")
    if _docker_status(ref) == "running":
        _docker_run_checked(["stop", ref], timeout=300)
    db["db_instance_status"] = "stopped"
    db["container_status"] = "exited"
    db["updated"] = _now()
    return db


def _rds_runtime_reboot(db: dict) -> dict:
    if not _docker_available():
        db["runtime_backend"] = "simulated"
        db["db_instance_status"] = "available"
        db["container_status"] = "docker-unavailable"
        db["updated"] = _now()
        return db
    ref = db.get("container_id") or db.get("container_name")
    if not ref:
        raise HTTPException(409, detail="DBInstanceContainerMissing")
    if _docker_status(ref) != "running":
        raise HTTPException(409, detail="DBInstanceNotRunning")
    db["db_instance_status"] = "rebooting"
    _docker_run_checked(["restart", ref], timeout=300)
    db["db_instance_status"] = "available"
    db["container_status"] = "running"
    db["latest_restorable_time"] = _now()
    db["updated"] = _now()
    return db


def _rds_runtime_delete(db: dict) -> None:
    if not _docker_available():
        db["runtime_backend"] = "simulated"
        db["container_status"] = "docker-unavailable"
        return
    ref = db.get("container_id") or db.get("container_name")
    if ref and _docker_container_exists(ref):
        _docker_run(["rm", "-f", ref], timeout=300)
    volume_name = _rds_runtime_data_volume(db["db_instance_identifier"])
    _docker_run(["volume", "rm", "-f", volume_name], timeout=300)
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
        "runtime_backend": db.get("runtime_backend", "simulated"),
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
    endpoint_address = f"{db_id}.rds.local"
    runtime_backend = "docker" if _docker_available() else "simulated"
    resolved_engine_version = _rds_resolve_engine_version(payload.engine, payload.engine_version)
    runtime_image = _rds_runtime_image(payload.engine, resolved_engine_version)
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
        "endpoint_port": engine_profile["port"],
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
        "container_status": "simulated" if runtime_backend == "simulated" else "created",
        "host_port": 0,
        "container_port": engine_profile["port"],
    }
    db["subnet_ids"] = list(subnet_group.get("subnet_ids", []))
    if runtime_backend == "docker":
        _rds_runtime_ensure_container(db)
        db["db_instance_status"] = "available"
        db["container_status"] = "running" if _docker_status(db.get("container_id") or db.get("container_name")) == "running" else "created"
    else:
        db["endpoint_port"] = engine_profile["port"]
        db["endpoint_address"] = f"{db_id}.rds.local"
        db["endpoint_url"] = f"{db['endpoint_address']}:{db['endpoint_port']}"
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
    _rds_runtime_delete(db)
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


@app.get("/api/rds/databases", include_in_schema=False)
def api_rds_list_databases():
    return _rds_list_databases_view()


@app.post("/api/rds/databases")
def api_rds_create_database(req: RDSDatabaseRequest):
    db = _rds_prepare_db_instance(req)
    return _rds_db_view(db)


@app.get("/api/rds/databases/{db_instance_identifier}")
def api_rds_get_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    return _rds_db_view(db)


@app.post("/api/rds/databases/{db_instance_identifier}/start")
def api_rds_start_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    if _rds_db_status(db) == "available":
        return _rds_db_view(db)
    db = _rds_runtime_start(db)
    _rds_emit_event("StartDBInstance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


@app.post("/api/rds/databases/{db_instance_identifier}/stop")
def api_rds_stop_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    db = _rds_runtime_stop(db)
    _rds_emit_event("StopDBInstance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


@app.post("/api/rds/databases/{db_instance_identifier}/reboot")
def api_rds_reboot_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    db = _rds_runtime_reboot(db)
    _rds_emit_event("RebootDBInstance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


@app.put("/api/rds/databases/{db_instance_identifier}")
def api_rds_modify_database(db_instance_identifier: str, req: RDSModifyRequest):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    modified = _rds_update_db_instance(db, req)
    return _rds_db_view(modified)


@app.delete("/api/rds/databases/{db_instance_identifier}")
def api_rds_delete_database(db_instance_identifier: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = ""):
    _rds_delete_db_instance(db_instance_identifier, skip_final_snapshot=skip_final_snapshot, final_snapshot_identifier=final_snapshot_identifier)
    return {"deleted": True, "db_instance_identifier": db_instance_identifier}


@app.get("/api/rds/subnet-groups")
def api_rds_list_subnet_groups():
    return {"db_subnet_groups": list(sorted(rds_state["db_subnet_groups"].values(), key=lambda item: item.get("db_subnet_group_name", ""))), "count": len(rds_state["db_subnet_groups"])}


@app.post("/api/rds/subnet-groups")
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
    return group


@app.delete("/api/rds/subnet-groups/{db_subnet_group_name}")
def api_rds_delete_subnet_group(db_subnet_group_name: str):
    name = db_subnet_group_name.lower()
    for db in rds_state["db_instances"].values():
        if db.get("db_subnet_group_name") == name:
            raise HTTPException(409, detail="InvalidDBSubnetGroupState")
    if name not in rds_state["db_subnet_groups"]:
        raise HTTPException(404, detail="DBSubnetGroupNotFound")
    del rds_state["db_subnet_groups"][name]
    return {"deleted": True, "db_subnet_group_name": name}


@app.get("/api/rds/parameter-groups")
def api_rds_list_parameter_groups():
    return {"db_parameter_groups": list(sorted(rds_state["db_parameter_groups"].values(), key=lambda item: item.get("db_parameter_group_name", ""))), "count": len(rds_state["db_parameter_groups"])}


@app.post("/api/rds/parameter-groups")
def api_rds_create_parameter_group(req: RDSParameterGroupRequest):
    name = req.db_parameter_group_name.strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: DBParameterGroupName")
    if name in rds_state["db_parameter_groups"]:
        raise HTTPException(400, detail="DBParameterGroupAlreadyExists")
    group = _rds_make_db_parameter_group(name, req.family, req.description or name, req.tags or [])
    return group


@app.delete("/api/rds/parameter-groups/{db_parameter_group_name}")
def api_rds_delete_parameter_group(db_parameter_group_name: str):
    name = db_parameter_group_name.lower()
    for db in rds_state["db_instances"].values():
        if db.get("db_parameter_group_name") == name:
            raise HTTPException(409, detail="InvalidDBParameterGroupState")
    if name not in rds_state["db_parameter_groups"]:
        raise HTTPException(404, detail="DBParameterGroupNotFound")
    del rds_state["db_parameter_groups"][name]
    return {"deleted": True, "db_parameter_group_name": name}


@app.get("/api/rds/snapshots")
def api_rds_list_snapshots():
    return {"db_snapshots": [_rds_db_snapshot_view(snapshot) for snapshot in sorted(rds_state["db_snapshots"].values(), key=lambda item: item.get("created", ""))], "count": len(rds_state["db_snapshots"])}


@app.post("/api/rds/databases/{db_instance_identifier}/snapshots")
def api_rds_create_snapshot(db_instance_identifier: str, req: RDSSnapshotRequest):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    snapshot = _rds_create_snapshot_from_db(db, req.db_snapshot_identifier, req.tags or [])
    return _rds_db_snapshot_view(snapshot)


@app.post("/api/rds/snapshots/{db_snapshot_identifier}/restore")
def api_rds_restore_snapshot(db_snapshot_identifier: str, req: RDSRestoreSnapshotRequest):
    snapshot = _rds_find_db_snapshot(db_snapshot_identifier)
    if not snapshot:
        raise HTTPException(404, detail="DBSnapshotNotFound")
    db = _rds_restore_snapshot(snapshot, req)
    return _rds_db_view(db)


@app.post("/api/rds/databases/{db_instance_identifier}/tags")
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


@app.get("/api/rds/databases/{db_instance_identifier}/tags")
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


@app.api_route("/rds", methods=["GET", "POST"], include_in_schema=False)
@app.api_route("/api/rds/aws", methods=["GET", "POST"], include_in_schema=False)
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


@app.api_route("/vpc", methods=["GET", "POST"], include_in_schema=False)
@app.api_route("/api/vpc/aws", methods=["GET", "POST"], include_in_schema=False)
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


@app.get("/api/apigateway/apis")
def api_apigateway_list_apis():
    apis = [_apigw_api_view(api) for api in _apigw_state().setdefault("apis", {}).values()]
    apis.sort(key=lambda item: (item.get("created", ""), item.get("name", "")))
    return {"apis": apis, "count": len(apis)}


@app.post("/api/apigateway/apis")
def api_apigateway_create_api(req: APIGatewayRequest):
    if not req.name.strip():
        raise HTTPException(400, detail="MissingParameter: name is required.")
    api = _apigw_create_api_record(req)
    return _apigw_summary(api)


@app.get("/api/apigateway/apis/{api_id}")
def api_apigateway_get_api(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    return _apigw_summary(api)


@app.delete("/api/apigateway/apis/{api_id}")
def api_apigateway_delete_api(api_id: str):
    _apigw_delete_api_record(api_id)
    return {"message": "API Gateway API deleted", "rest_api_id": api_id}


@app.get("/api/apigateway/apis/{api_id}/resources")
def api_apigateway_list_resources(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    return {"resources": _apigw_route_views(api), "count": max(len(api.get("resources", {})) - 1, 0)}


@app.post("/api/apigateway/apis/{api_id}/resources")
def api_apigateway_create_resource(api_id: str, req: APIGatewayResourceRequest):
    resource = _apigw_create_resource_record(api_id, req)
    api = _apigw_api(api_id)
    return {"resource": resource, "api": _apigw_api_view(api)}


@app.post("/api/apigateway/apis/{api_id}/methods")
def api_apigateway_put_method(api_id: str, req: APIGatewayMethodRequest):
    method = _apigw_put_method_record(api_id, req)
    return {"method": method}


@app.post("/api/apigateway/apis/{api_id}/integrations")
def api_apigateway_put_integration(api_id: str, req: APIGatewayIntegrationRequest):
    integration = _apigw_put_integration_record(api_id, req)
    return {"integration": integration}


@app.post("/api/apigateway/apis/{api_id}/deployments")
def api_apigateway_create_deployment(api_id: str, req: APIGatewayDeploymentRequest):
    deployment = _apigw_create_deployment_record(api_id, req)
    return {"deployment": deployment}


@app.get("/api/apigateway/apis/{api_id}/deployments")
def api_apigateway_list_deployments(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    deployments = list(api.get("deployments", {}).values())
    deployments.sort(key=lambda item: (item.get("created", ""), item.get("deployment_id", "")))
    return {"deployments": deployments, "count": len(deployments)}


@app.post("/api/apigateway/apis/{api_id}/stages")
def api_apigateway_create_stage(api_id: str, req: APIGatewayStageRequest):
    stage = _apigw_create_stage_record(api_id, req)
    return {"stage": stage}


@app.get("/api/apigateway/apis/{api_id}/stages")
def api_apigateway_list_stages(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stages = list(api.get("stages", {}).values())
    stages.sort(key=lambda item: (item.get("created", ""), item.get("stage_name", "")))
    return {"stages": stages, "count": len(stages)}


@app.get("/api/apigateway/apis/{api_id}/logs")
def api_apigateway_list_logs(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    logs = list(api.get("logs", []))
    logs.sort(key=lambda item: item.get("at", ""), reverse=True)
    return {"logs": logs[:100], "count": len(logs)}


@app.api_route("/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def api_apigateway_invoke_path(api_id: str, stage_name: str, proxy_path: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, proxy_path, request)


@app.api_route("/api/apigateway/invoke/{api_id}/{stage_name}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def api_apigateway_invoke_root(api_id: str, stage_name: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, "", request)


@app.get("/api/runtime/bundles")
def api_runtime_bundles():
    return {"bundles": list(runtime_state["bundles"].values()), "count": len(runtime_state["bundles"])}


@app.post("/api/deployments")
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


@app.post("/api/actions")
def api_action_router(payload: ServiceActionRequest):
    service = payload.payload.get("service", "")
    action = payload.action.lower()
    if service == "s3":
        return {"message": "Use S3 REST or /api/s3 endpoints for S3 actions."}
    if service == "iam" and action == "createuser":
        return api_iam_create_user(IAMUserRequest(**payload.payload))
    raise HTTPException(400, detail="UnsupportedAction")

# ── Serve React UI — explicit routes registered BEFORE /{bucket} ─────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
_UI_HTML = os.path.join(STATIC_DIR, "index.html")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/ui", include_in_schema=False)
@app.get("/ui/{path:path}", include_in_schema=False)
@app.get("/product", include_in_schema=False)
@app.get("/product/{path:path}", include_in_schema=False)
async def serve_ui(path: str = "") -> Response:
    with open(_UI_HTML, "rb") as f:
        return Response(content=f.read(), media_type="text/html", headers={"Cache-Control": "no-store, max-age=0"})


# ── S3 REST API — root level ─────────────────────────────────────────────────

@app.get("/")
async def s3_list_buckets(request: Request) -> Response:
    """GET / → ListBuckets"""
    accept = request.headers.get("accept", "")
    user_agent = request.headers.get("user-agent", "")
    if "text/html" in accept or "Mozilla" in user_agent:
        with open(_UI_HTML, "rb") as f:
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

@app.head("/{bucket}")
async def s3_head_bucket(bucket: str, request: Request) -> Response:
    """HEAD /{bucket} → HeadBucket"""
    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    return _empty_response(200)


@app.put("/{bucket}")
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

    buckets[bucket] = {
        "region": region,
        "created": _now(),
        "access": "Bucket and objects not public",
        "versioning": "Disabled",
        "arn": f"arn:aws:s3:::{bucket}",
        "tags": {},
    }
    objects[bucket] = {}
    return _empty_response(200, {"Location": f"/{bucket}"})


@app.get("/{bucket}")
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


@app.delete("/{bucket}")
async def s3_delete_bucket(bucket: str, request: Request) -> Response:
    """DELETE /{bucket} → DeleteBucket"""
    if not _bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    if objects.get(bucket):
        return _error_xml("BucketNotEmpty", "The bucket you tried to delete is not empty.", f"/{bucket}", 409)
    del buckets[bucket]
    del objects[bucket]
    return _empty_response(204)


# ── S3 REST API — object level ───────────────────────────────────────────────

@app.head("/{bucket}/{key:path}")
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
        "Last-Modified": obj["last_modified"],
        "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
        "x-amz-version-id": obj.get("version_id", "null"),
    }
    for k, v in obj.get("metadata", {}).items():
        headers[f"x-amz-meta-{k}"] = v
    return _empty_response(200, headers)


@app.put("/{bucket}/{key:path}")
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
        _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id)
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
    entry = _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id)
    return _empty_response(200, {"ETag": version["etag"], "x-amz-version-id": entry.get("current_version_id", version_id)})


@app.get("/{bucket}/{key:path}")
async def s3_get_object(bucket: str, key: str, request: Request) -> Response:
    """GET /{bucket}/{key}[?tagging|?acl|?uploadId] → GetObject/GetObjectTagging/ListParts"""
    params = dict(request.query_params)

    if not _bucket_exists(bucket):
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
        "Last-Modified": obj["last_modified"],
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


@app.delete("/{bucket}/{key:path}")
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
    entry = _s3_insert_simple_delete_marker(bucket, key)
    version_id = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
    return _empty_response(204, {"x-amz-delete-marker": "true", "x-amz-version-id": version_id})


@app.post("/{bucket}")
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
                        else:
                            _s3_insert_simple_delete_marker(bucket, k)
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


@app.post("/{bucket}/{key:path}")
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
        _s3_write_object_version(bucket, key, version, replace_version_id=replace_version_id)
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


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=9000, reload=False)
