from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.terraform_export import terraform_hcl_files


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _slug(value: str, fallback: str = "resource") -> str:
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", _string(value, fallback).lower())
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"r_{text}"
    return text[:63]


def terraform_cli_path() -> str | None:
    return shutil.which("terraform")


def terraform_cli_available() -> bool:
    return bool(terraform_cli_path())


def terraform_workspace_root() -> Path:
    configured = str(os.environ.get("CLOUDLEARN_TERRAFORM_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    fallback = Path(os.environ.get("CLOUDLEARN_DEPLOY_DIR", Path(__file__).resolve().parent.parent / "deployments")) / "terraform"
    return fallback.resolve()


def terraform_space_dir(space_id: str) -> Path:
    return terraform_workspace_root() / _slug(space_id or "active-space", "active_space")


def terraform_workflow_dir(space_id: str, workflow_id: str, workflow_kind: str) -> Path:
    return terraform_space_dir(space_id) / f"{workflow_kind}-{_slug(workflow_id, workflow_kind)}"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def terraform_fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def flatten_terraform_resources(terraform_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resource_groups = terraform_json.get("resource", {})
    if not isinstance(resource_groups, dict):
        return {}
    flattened: dict[str, dict[str, Any]] = {}
    for resource_type, resources in resource_groups.items():
        if not isinstance(resources, dict):
            continue
        for resource_name, attrs in resources.items():
            key = f"{resource_type}.{resource_name}"
            flattened[key] = {
                "resource_type": resource_type,
                "resource_name": resource_name,
                "attributes": copy.deepcopy(attrs) if isinstance(attrs, dict) else attrs,
                "fingerprint": terraform_fingerprint(attrs),
            }
    return flattened


def _provider_counts(terraform_json: dict[str, Any]) -> dict[str, int]:
    resource_groups = terraform_json.get("resource", {})
    counts: dict[str, int] = {}
    if not isinstance(resource_groups, dict):
        return counts
    for resource_type, resources in resource_groups.items():
        provider = resource_type.split("_", 1)[0] if "_" in resource_type else resource_type
        counts[provider] = counts.get(provider, 0) + (len(resources) if isinstance(resources, dict) else 0)
    return counts


def _resource_type_counts(terraform_json: dict[str, Any]) -> dict[str, int]:
    resource_groups = terraform_json.get("resource", {})
    counts: dict[str, int] = {}
    if not isinstance(resource_groups, dict):
        return counts
    for resource_type, resources in resource_groups.items():
        counts[resource_type] = len(resources) if isinstance(resources, dict) else 0
    return counts


def build_plan_summary(export_payload: dict[str, Any], previous_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    terraform_json = copy.deepcopy(export_payload.get("terraform_json") or {})
    current_index = flatten_terraform_resources(terraform_json)
    previous_index = {}
    if isinstance(previous_snapshot, dict):
        previous_index = previous_snapshot.get("resource_index") if isinstance(previous_snapshot.get("resource_index"), dict) else {}

    current_keys = set(current_index.keys())
    previous_keys = set(previous_index.keys())
    created = sorted(current_keys - previous_keys)
    deleted = sorted(previous_keys - current_keys)
    changed = sorted(
        key
        for key in current_keys & previous_keys
        if current_index[key].get("fingerprint") != previous_index[key].get("fingerprint")
    )
    unchanged = sorted((current_keys & previous_keys) - set(changed))

    return {
        "resource_index": current_index,
        "resource_counts": _resource_type_counts(terraform_json),
        "provider_counts": _provider_counts(terraform_json),
        "action_counts": {
            "create": len(created),
            "update": len(changed),
            "delete": len(deleted),
            "no_op": len(unchanged),
        },
        "actions": {
            "create": created,
            "update": changed,
            "delete": deleted,
            "no_op": unchanged,
        },
        "fingerprint": terraform_fingerprint(terraform_json),
    }


def stage_workflow_bundle(export_payload: dict[str, Any], workflow_id: str, workflow_kind: str, summary: dict[str, Any]) -> dict[str, Any]:
    space_id = _string(export_payload.get("space_id"), "active-space")
    stage_dir = terraform_workflow_dir(space_id, workflow_id, workflow_kind)
    stage_dir.mkdir(parents=True, exist_ok=True)
    hcl_dir = stage_dir / "hcl"
    hcl_dir.mkdir(parents=True, exist_ok=True)

    hcl_files = terraform_hcl_files(export_payload)
    files = {
        "main.tf.json": export_payload.get("terraform_json") or {},
        "export.json": export_payload,
        "summary.json": summary,
        "metadata.json": {
            "workflow_id": workflow_id,
            "workflow_kind": workflow_kind,
            "space_id": space_id,
            "generated_at": _now(),
            "terraform_cli_available": terraform_cli_available(),
            "terraform_cli_path": terraform_cli_path() or "",
            "terraform_hcl_files": sorted(hcl_files.keys()),
        },
    }

    for name, payload in files.items():
        (stage_dir / name).write_text(_canonical_json(payload), encoding="utf-8")

    for name, content in hcl_files.items():
        (hcl_dir / name).write_text(content, encoding="utf-8")

    return {
        "workflow_id": workflow_id,
        "workflow_kind": workflow_kind,
        "space_id": space_id,
        "stage_dir": str(stage_dir),
        "hcl_dir": str(hcl_dir),
        "files": [str(stage_dir / name) for name in files] + [str(hcl_dir / name) for name in hcl_files],
        "terraform_cli_available": terraform_cli_available(),
        "terraform_cli_path": terraform_cli_path() or "",
        "terraform_hcl_files": sorted(hcl_files.keys()),
    }


def run_terraform_cli(stage_dir: str | Path, action: str, timeout: int = 600) -> dict[str, Any]:
    cli = terraform_cli_path()
    if not cli:
        return {
            "available": False,
            "status": "unavailable",
            "action": action,
            "error": "Terraform CLI is not installed on this runtime.",
        }

    stage_dir = Path(stage_dir)
    env = os.environ.copy()
    env.setdefault("TF_IN_AUTOMATION", "1")
    env.setdefault("TF_INPUT", "0")

    def _run(args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            [cli, *args],
            cwd=str(stage_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": [cli, *args],
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    init = _run(["init", "-input=false", "-no-color"])
    if init["exit_code"] != 0:
        return {
            "available": True,
            "status": "failed",
            "action": action,
            "step": "init",
            "command": init["command"],
            "exit_code": init["exit_code"],
            "stdout": init["stdout"],
            "stderr": init["stderr"],
        }

    plan = _run(["plan", "-input=false", "-no-color", "-out=tfplan"])
    result: dict[str, Any] = {
        "available": True,
        "status": "planned" if plan["exit_code"] == 0 else "failed",
        "action": action,
        "command": plan["command"],
        "exit_code": plan["exit_code"],
        "stdout": plan["stdout"],
        "stderr": plan["stderr"],
    }
    if action == "apply" and plan["exit_code"] == 0:
        apply_result = _run(["apply", "-auto-approve", "-no-color", "tfplan"])
        result.update(
            {
                "status": "applied" if apply_result["exit_code"] == 0 else "failed",
                "apply_command": apply_result["command"],
                "apply_exit_code": apply_result["exit_code"],
                "apply_stdout": apply_result["stdout"],
                "apply_stderr": apply_result["stderr"],
            }
        )
    return result


def _space_region(space: dict[str, Any]) -> str:
    return _string(space.get("active_region") or space.get("region") or "", "us-east-1")


def _space_zone(space: dict[str, Any]) -> str:
    region = _space_region(space)
    if region.endswith(("-a", "-b", "-c", "-1a", "-1b", "-1c")):
        return region
    if region.startswith("us-central1"):
        return f"{region}-a" if not region.endswith("-a") else region
    if region.endswith("-1"):
        return f"{region}a"
    if region.endswith("-1a"):
        return region
    if region.count("-") >= 2:
        return f"{region}-a"
    return "us-east-1a"


def _import_attr(attrs: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = attrs.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return fallback


def _import_tags_name(attrs: dict[str, Any], fallback: str) -> str:
    tags = attrs.get("tags")
    if isinstance(tags, dict):
        name = tags.get("Name")
        if name is not None and str(name).strip():
            return str(name)
    return _import_attr(attrs, "name", "function_name", "bucket", "identifier", "api_id", "display_name", "account_id", fallback=fallback)


def _import_resource_node(provider: str, service: str, kind: str, resource_id: str, name: str, attrs: dict[str, Any], location: str = "", state: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    node = {
        "provider": provider,
        "service": service,
        "kind": kind,
        "resource_id": resource_id,
        "name": name,
        "location": location,
        "state": state,
        "updated_at": _now(),
    }
    if isinstance(extra, dict):
        node.update(copy.deepcopy(extra))
    return node


def terraform_import_bundle(payload: dict[str, Any], space: dict[str, Any]) -> dict[str, Any]:
    terraform_json = {}
    source_space_id = ""
    source_space_name = ""
    source_provider = ""
    if isinstance(payload, dict):
        source_space_id = _string(payload.get("space_id"), "")
        source_space_name = _string(payload.get("space_name"), "")
        source_provider = _string(payload.get("provider"), "")
        if isinstance(payload.get("terraform_json"), dict):
            terraform_json = copy.deepcopy(payload["terraform_json"])
        elif isinstance(payload.get("resource"), dict):
            terraform_json = copy.deepcopy(payload)
        elif isinstance(payload.get("bundle"), dict):
            return terraform_import_bundle(payload["bundle"], space)

    resource_groups = terraform_json.get("resource", {})
    if not isinstance(resource_groups, dict):
        resource_groups = {}

    region = _space_region(space)
    zone = _space_zone(space)
    project = _string(space.get("gcp_project_id") or space.get("active_account") or space.get("project_id") or space.get("name"), "cloudlearn")
    service_state_updates: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    service_keys: set[str] = set()

    def ensure(service_key: str, template: dict[str, Any]) -> dict[str, Any]:
        state = service_state_updates.setdefault(service_key, copy.deepcopy(template))
        for key, default_value in template.items():
            if key not in state:
                state[key] = copy.deepcopy(default_value)
        service_keys.add(service_key)
        return state

    def add_imported(provider: str, service: str, kind: str, resource_id: str, name: str, attrs: dict[str, Any], state: str, location: str = "", service_key: str | None = None, template: dict[str, Any] | None = None, target_key: str | None = None, payload: dict[str, Any] | None = None) -> None:
        if not service_key or not template or not target_key:
            unsupported.append({
                "provider": provider,
                "service": service,
                "kind": kind,
                "resource_id": resource_id,
                "name": name,
            })
            return
        state_dict = ensure(service_key, template)
        state_dict[target_key][resource_id] = copy.deepcopy(payload or {})
        nodes.append(_import_resource_node(provider, service, kind, resource_id, name, attrs, location=location, state=state))
        imported.append({
            "provider": provider,
            "service": service,
            "kind": kind,
            "resource_id": resource_id,
            "name": name,
        })

    for resource_type, resources in resource_groups.items():
        if not isinstance(resources, dict):
            continue
        for resource_name, attrs in resources.items():
            if not isinstance(attrs, dict):
                attrs = {}

            # AWS
            if resource_type == "aws_instance":
                name = _import_tags_name(attrs, resource_name)
                add_imported(
                    "aws", "ec2", "instance", resource_name, name, attrs,
                    state=_import_attr(attrs, "state", "status", fallback="running"),
                    location=_import_attr(attrs, "availability_zone", fallback=zone),
                    service_key="ec2",
                    template={"instances": {}},
                    target_key="instances",
                    payload={
                        "instance_id": resource_name,
                        "resource_id": resource_name,
                        "name": name,
                        "instance_type": _import_attr(attrs, "instance_type", fallback="t3.micro"),
                        "ami": _import_attr(attrs, "ami", fallback="ami-placeholder"),
                        "availability_zone": _import_attr(attrs, "availability_zone", fallback=zone),
                        "subnet_id": _import_attr(attrs, "subnet_id", fallback=""),
                        "state": _import_attr(attrs, "state", "status", fallback="running"),
                        "status": _import_attr(attrs, "state", "status", fallback="running"),
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_s3_bucket":
                name = _import_attr(attrs, "bucket", "name", fallback=resource_name)
                add_imported(
                    "aws", "s3", "bucket", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="s3",
                    template={"buckets": {}, "objects": {}, "multiparts": {}},
                    target_key="buckets",
                    payload={
                        "bucket": name,
                        "bucket_name": name,
                        "name": name,
                        "region": region,
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                        "notifications": {
                            "eventBridgeEnabled": False,
                            "topicConfigurations": [],
                            "queueConfigurations": [],
                            "cloudFunctionConfigurations": [],
                            "deliveries": [],
                            "updatedAt": _now(),
                        },
                        "tags": copy.deepcopy(attrs.get("tags") or {}),
                    },
                )
                continue
            if resource_type == "aws_vpc":
                cidr = _import_attr(attrs, "cidr_block", fallback="10.0.0.0/16")
                name = _import_tags_name(attrs, resource_name)
                add_imported(
                    "aws", "vpc", "vpc", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="vpc",
                    template={"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}},
                    target_key="vpcs",
                    payload={
                        "vpc_id": resource_name,
                        "resource_id": resource_name,
                        "name": name,
                        "cidr_block": cidr,
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_subnet":
                name = _import_tags_name(attrs, resource_name)
                add_imported(
                    "aws", "vpc", "subnet", resource_name, name, attrs,
                    state="available",
                    location=_import_attr(attrs, "availability_zone", fallback=zone),
                    service_key="vpc",
                    template={"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}},
                    target_key="subnets",
                    payload={
                        "subnet_id": resource_name,
                        "resource_id": resource_name,
                        "name": name,
                        "vpc_id": _import_attr(attrs, "vpc_id", fallback="vpc-placeholder"),
                        "cidr_block": _import_attr(attrs, "cidr_block", fallback="10.0.1.0/24"),
                        "availability_zone": _import_attr(attrs, "availability_zone", fallback=zone),
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_security_group":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "vpc", "security_group", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="vpc",
                    template={"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}},
                    target_key="security_groups",
                    payload={
                        "group_id": resource_name,
                        "resource_id": resource_name,
                        "name": name,
                        "description": _import_attr(attrs, "description", fallback=f"CloudLearn imported security group for {name}"),
                        "vpc_id": _import_attr(attrs, "vpc_id", fallback="vpc-placeholder"),
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_route_table":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "vpc", "route_table", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="vpc",
                    template={"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}},
                    target_key="route_tables",
                    payload={
                        "route_table_id": resource_name,
                        "resource_id": resource_name,
                        "name": name,
                        "vpc_id": _import_attr(attrs, "vpc_id", fallback="vpc-placeholder"),
                        "routes": copy.deepcopy(attrs.get("routes") or []),
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_internet_gateway":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "vpc", "internet_gateway", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="vpc",
                    template={"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}},
                    target_key="internet_gateways",
                    payload={
                        "internet_gateway_id": resource_name,
                        "resource_id": resource_name,
                        "name": name,
                        "vpc_id": _import_attr(attrs, "vpc_id", fallback="vpc-placeholder"),
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_db_instance":
                name = _import_attr(attrs, "identifier", "db_instance_identifier", fallback=resource_name)
                add_imported(
                    "aws", "rds", "db_instance", resource_name, name, attrs,
                    state=_import_attr(attrs, "db_instance_status", "state", fallback="available"),
                    location=region,
                    service_key="rds",
                    template={"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}},
                    target_key="db_instances",
                    payload={
                        "db_instance_identifier": name,
                        "resource_id": resource_name,
                        "name": name,
                        "engine": _import_attr(attrs, "engine", fallback="postgres"),
                        "instance_class": _import_attr(attrs, "instance_class", fallback="db.t3.micro"),
                        "allocated_storage": int(attrs.get("allocated_storage") or 20),
                        "master_username": _import_attr(attrs, "username", "master_username", fallback="dbadmin"),
                        "db_instance_status": _import_attr(attrs, "db_instance_status", "state", fallback="available"),
                        "availability_zone": _import_attr(attrs, "availability_zone", fallback=zone),
                        "state": _import_attr(attrs, "db_instance_status", "state", fallback="available"),
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_db_subnet_group":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "rds", "subnet_group", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="rds",
                    template={"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}},
                    target_key="db_subnet_groups",
                    payload={
                        "db_subnet_group_name": name,
                        "resource_id": resource_name,
                        "name": name,
                        "description": _import_attr(attrs, "description", fallback=f"Imported subnet group for {name}"),
                        "subnet_ids": copy.deepcopy(attrs.get("subnet_ids") or []),
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "aws_db_parameter_group":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "rds", "parameter_group", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="rds",
                    template={"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}},
                    target_key="db_parameter_groups",
                    payload={
                        "db_parameter_group_name": name,
                        "resource_id": resource_name,
                        "name": name,
                        "family": _import_attr(attrs, "family", fallback="postgres16"),
                        "description": _import_attr(attrs, "description", fallback=f"Imported parameter group for {name}"),
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "aws_lambda_function":
                name = _import_attr(attrs, "function_name", fallback=resource_name)
                add_imported(
                    "aws", "lambda", "function", resource_name, name, attrs,
                    state=_import_attr(attrs, "state", fallback="Active"),
                    location=region,
                    service_key="lambda",
                    template={"functions": {}, "events": [], "invocations": []},
                    target_key="functions",
                    payload={
                        "function_name": name,
                        "resource_id": resource_name,
                        "name": name,
                        "runtime": _import_attr(attrs, "runtime", fallback="python3.12"),
                        "handler": _import_attr(attrs, "handler", fallback="lambda_function.lambda_handler"),
                        "role": _import_attr(attrs, "role", fallback="arn:aws:iam::123456789012:role/service-role/cloudlearn-lambda-basic-execution"),
                        "state": _import_attr(attrs, "state", fallback="Active"),
                        "status": _import_attr(attrs, "state", fallback="Active"),
                        "created": _now(),
                        "updated": _now(),
                        "tags": copy.deepcopy(attrs.get("tags") or {"Name": name}),
                    },
                )
                continue
            if resource_type == "aws_sqs_queue":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "sqs", "queue", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="sqs",
                    template={"queues": {}, "events": []},
                    target_key="queues",
                    payload={
                        "queue_name": name,
                        "resource_id": resource_name,
                        "name": name,
                        "queue_url": f"http://127.0.0.1:9000/api/sqs/queues/{name}",
                        "queue_arn": f"arn:aws:sqs:us-east-1:123456789012:{name}",
                        "queue_type": "standard",
                        "state": "available",
                        "status": "available",
                        "created": _now(),
                        "last_modified": _now(),
                        "messages": [],
                        "tags": copy.deepcopy(attrs.get("tags") or {}),
                    },
                )
                continue
            if resource_type == "aws_dynamodb_table":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "aws", "dynamodb", "table", resource_name, name, attrs,
                    state=_import_attr(attrs, "table_status", fallback="ACTIVE"),
                    location=region,
                    service_key="dynamodb",
                    template={"tables": {}, "events": []},
                    target_key="tables",
                    payload={
                        "table_name": name,
                        "resource_id": resource_name,
                        "name": name,
                        "table_arn": f"arn:aws:dynamodb:us-east-1:123456789012:table/{name}",
                        "table_status": _import_attr(attrs, "table_status", fallback="ACTIVE"),
                        "partition_key_name": _import_attr(attrs, "partition_key_name", fallback="id"),
                        "partition_key_type": _import_attr(attrs, "partition_key_type", fallback="S"),
                        "sort_key_name": _import_attr(attrs, "sort_key_name", fallback=""),
                        "sort_key_type": _import_attr(attrs, "sort_key_type", fallback="S"),
                        "billing_mode": _import_attr(attrs, "billing_mode", fallback="PAY_PER_REQUEST"),
                        "provisioned_throughput": copy.deepcopy(attrs.get("provisioned_throughput") or {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}),
                        "tags": copy.deepcopy(attrs.get("tags") or {}),
                        "indexes": copy.deepcopy(attrs.get("indexes") or []),
                        "streams": copy.deepcopy(attrs.get("streams") or {"enabled": False, "latest_stream_label": ""}),
                        "items": {},
                        "created": _now(),
                        "last_modified": _now(),
                    },
                )
                continue
            if resource_type == "aws_api_gateway_rest_api":
                name = _import_attr(attrs, "name", "display_name", fallback=resource_name)
                add_imported(
                    "aws", "apigateway", "api", resource_name, name, attrs,
                    state="available",
                    location=region,
                    service_key="apigateway",
                    template={"apis": {}, "logs": []},
                    target_key="apis",
                    payload={
                        "id": resource_name,
                        "api_id": resource_name,
                        "name": name,
                        "display_name": _import_attr(attrs, "display_name", fallback=name),
                        "description": _import_attr(attrs, "description", fallback=f"Imported API for {name}"),
                        "created": _now(),
                        "updated": _now(),
                        "stages": {},
                        "resources": {},
                        "methods": {},
                        "integrations": {},
                    },
                )
                continue

            # GCP
            if resource_type == "google_compute_instance":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "compute", "instance", resource_name, name, attrs,
                    state=_import_attr(attrs, "status", fallback="RUNNING"),
                    location=_import_attr(attrs, "zone", fallback=zone),
                    service_key="gcp_compute",
                    template={"instances": {}},
                    target_key="instances",
                    payload={
                        "name": name,
                        "instance_id": resource_name,
                        "resource_id": resource_name,
                        "machine_type": _import_attr(attrs, "machine_type", fallback="e2-micro"),
                        "zone": _import_attr(attrs, "zone", fallback=zone),
                        "status": _import_attr(attrs, "status", fallback="RUNNING"),
                        "state": _import_attr(attrs, "status", fallback="RUNNING"),
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_storage_bucket":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "storage", "bucket", resource_name, name, attrs,
                    state="ACTIVE",
                    location=_import_attr(attrs, "location", fallback=region),
                    service_key="gcp_storage",
                    template={"buckets": {}},
                    target_key="buckets",
                    payload={
                        "name": name,
                        "bucket": name,
                        "bucket_name": name,
                        "location": _import_attr(attrs, "location", fallback=region),
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_sql_database_instance":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "sql", "instance", resource_name, name, attrs,
                    state=_import_attr(attrs, "state", fallback="RUNNABLE"),
                    location=_import_attr(attrs, "region", fallback=region),
                    service_key="gcp_sql",
                    template={"instances": {}},
                    target_key="instances",
                    payload={
                        "name": name,
                        "instance_id": resource_name,
                        "resource_id": resource_name,
                        "region": _import_attr(attrs, "region", fallback=region),
                        "database_version": _import_attr(attrs, "database_version", fallback="POSTGRES_16"),
                        "state": _import_attr(attrs, "state", fallback="RUNNABLE"),
                        "status": _import_attr(attrs, "state", fallback="RUNNABLE"),
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_pubsub_topic":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "pubsub", "topic", resource_name, name, attrs,
                    state="ACTIVE",
                    location=region,
                    service_key="gcp_pubsub",
                    template={"topics": {}, "subscriptions": {}},
                    target_key="topics",
                    payload={
                        "name": name,
                        "topicId": name,
                        "resource_id": resource_name,
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_pubsub_subscription":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "pubsub", "subscription", resource_name, name, attrs,
                    state="ACTIVE",
                    location=region,
                    service_key="gcp_pubsub",
                    template={"topics": {}, "subscriptions": {}},
                    target_key="subscriptions",
                    payload={
                        "name": name,
                        "subscriptionId": name,
                        "resource_id": resource_name,
                        "topic": _import_attr(attrs, "topic", fallback=f"projects/{project}/topics/sample"),
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_firestore_database":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "firestore", "database", resource_name, name, attrs,
                    state="ACTIVE",
                    location=_import_attr(attrs, "location_id", fallback=region),
                    service_key="gcp_firestore",
                    template={"databases": {}},
                    target_key="databases",
                    payload={
                        "name": name,
                        "databaseId": name,
                        "resource_id": resource_name,
                        "locationId": _import_attr(attrs, "location_id", fallback=region),
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_cloudfunctions_function":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "functions", "function", resource_name, name, attrs,
                    state=_import_attr(attrs, "status", fallback="ACTIVE"),
                    location=region,
                    service_key="gcp_functions",
                    template={"functions": {}, "operations": {}},
                    target_key="functions",
                    payload={
                        "name": name,
                        "function_name": name,
                        "resource_id": resource_name,
                        "runtime": _import_attr(attrs, "runtime", fallback="python312"),
                        "available_memory_mb": int(attrs.get("available_memory_mb") or 256),
                        "status": _import_attr(attrs, "status", fallback="ACTIVE"),
                        "state": _import_attr(attrs, "status", fallback="ACTIVE"),
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_compute_network":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "vpc", "network", resource_name, name, attrs,
                    state="READY",
                    location=region,
                    service_key="gcp_vpc",
                    template={"networks": {}, "subnetworks": {}, "firewalls": {}, "routes": {}},
                    target_key="networks",
                    payload={
                        "name": name,
                        "network_id": resource_name,
                        "resource_id": resource_name,
                        "auto_create_subnetworks": bool(attrs.get("auto_create_subnetworks", False)),
                        "state": "READY",
                        "status": "READY",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_compute_subnetwork":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "vpc", "subnetwork", resource_name, name, attrs,
                    state="READY",
                    location=_import_attr(attrs, "region", fallback=region),
                    service_key="gcp_vpc",
                    template={"networks": {}, "subnetworks": {}, "firewalls": {}, "routes": {}},
                    target_key="subnetworks",
                    payload={
                        "name": name,
                        "subnetwork_id": resource_name,
                        "resource_id": resource_name,
                        "network": _import_attr(attrs, "network", fallback=f"projects/{project}/global/networks/default"),
                        "region": _import_attr(attrs, "region", fallback=region),
                        "cidr_block": _import_attr(attrs, "ip_cidr_range", "cidr_block", fallback="10.0.1.0/24"),
                        "state": "READY",
                        "status": "READY",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_compute_firewall":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "vpc", "firewall", resource_name, name, attrs,
                    state="READY",
                    location=region,
                    service_key="gcp_vpc",
                    template={"networks": {}, "subnetworks": {}, "firewalls": {}, "routes": {}},
                    target_key="firewalls",
                    payload={
                        "name": name,
                        "firewall_id": resource_name,
                        "resource_id": resource_name,
                        "network": _import_attr(attrs, "network", fallback=f"projects/{project}/global/networks/default"),
                        "state": "READY",
                        "status": "READY",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_compute_route":
                name = _import_attr(attrs, "name", fallback=resource_name)
                add_imported(
                    "gcp", "vpc", "route", resource_name, name, attrs,
                    state="READY",
                    location=region,
                    service_key="gcp_vpc",
                    template={"networks": {}, "subnetworks": {}, "firewalls": {}, "routes": {}},
                    target_key="routes",
                    payload={
                        "name": name,
                        "route_id": resource_name,
                        "resource_id": resource_name,
                        "network": _import_attr(attrs, "network", fallback=f"projects/{project}/global/networks/default"),
                        "dest_range": _import_attr(attrs, "dest_range", fallback="0.0.0.0/0"),
                        "next_hop_gateway": _import_attr(attrs, "next_hop_gateway", fallback=""),
                        "state": "READY",
                        "status": "READY",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_api_gateway_api":
                name = _import_attr(attrs, "api_id", "display_name", "name", fallback=resource_name)
                add_imported(
                    "gcp", "apigateway", "api", resource_name, name, attrs,
                    state="ACTIVE",
                    location=region,
                    service_key="gcp_apigateway",
                    template={"apis": {}, "api_configs": {}, "gateways": {}},
                    target_key="apis",
                    payload={
                        "id": resource_name,
                        "api_id": name,
                        "display_name": _import_attr(attrs, "display_name", fallback=name),
                        "resource_id": resource_name,
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_api_gateway_api_config":
                name = _import_attr(attrs, "display_name", "name", fallback=resource_name)
                add_imported(
                    "gcp", "apigateway", "api_config", resource_name, name, attrs,
                    state="ACTIVE",
                    location=region,
                    service_key="gcp_apigateway",
                    template={"apis": {}, "api_configs": {}, "gateways": {}},
                    target_key="api_configs",
                    payload={
                        "id": resource_name,
                        "api_config_id": name,
                        "api": _import_attr(attrs, "api", fallback=f"projects/{project}/locations/{location}/apis/{name}"),
                        "display_name": _import_attr(attrs, "display_name", fallback=name),
                        "resource_id": resource_name,
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_api_gateway_gateway":
                name = _import_attr(attrs, "display_name", "name", fallback=resource_name)
                add_imported(
                    "gcp", "apigateway", "gateway", resource_name, name, attrs,
                    state="ACTIVE",
                    location=region,
                    service_key="gcp_apigateway",
                    template={"apis": {}, "api_configs": {}, "gateways": {}},
                    target_key="gateways",
                    payload={
                        "id": resource_name,
                        "gateway_id": name,
                        "api_config": _import_attr(attrs, "api_config", fallback=f"projects/{project}/locations/{location}/apiConfigs/{name}"),
                        "display_name": _import_attr(attrs, "display_name", fallback=name),
                        "resource_id": resource_name,
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue
            if resource_type == "google_service_account":
                name = _import_attr(attrs, "account_id", "display_name", "name", fallback=resource_name)
                add_imported(
                    "gcp", "iam", "service_account", resource_name, name, attrs,
                    state="ACTIVE",
                    location=region,
                    service_key="gcp_iam",
                    template={"service_accounts": {}, "policies": {}},
                    target_key="service_accounts",
                    payload={
                        "name": name,
                        "account_id": _import_attr(attrs, "account_id", fallback=_slug(name, "service_account")),
                        "email": _import_attr(attrs, "email", fallback=f"{_slug(name, 'service_account')}@{project}.iam.gserviceaccount.com"),
                        "display_name": _import_attr(attrs, "display_name", fallback=name),
                        "resource_id": resource_name,
                        "state": "ACTIVE",
                        "status": "ACTIVE",
                        "created": _now(),
                        "updated": _now(),
                    },
                )
                continue

            unsupported.append({
                "provider": _string(attrs.get("provider"), ""),
                "service": _string(attrs.get("service"), ""),
                "kind": _string(attrs.get("kind"), ""),
                "resource_id": resource_name,
                "name": _import_tags_name(attrs, resource_name),
                "reason": f"Unsupported Terraform resource type {resource_type}",
            })

    resource_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    for node in nodes:
        key = f"{node['provider']}.{node['service']}.{node['kind']}"
        resource_counts[key] = resource_counts.get(key, 0) + 1
        provider_counts[node["provider"]] = provider_counts.get(node["provider"], 0) + 1

    return {
        "space_id": source_space_id,
        "space_name": source_space_name,
        "provider": source_provider,
        "terraform_json": terraform_json,
        "resource_count": len(nodes),
        "supported_resources": len(nodes),
        "unsupported_resources": unsupported,
        "imported_resources": imported,
        "service_state_updates": service_state_updates,
        "nodes": nodes,
        "summary": {
            "resource_count": len(nodes) + len(unsupported),
            "supported_resources": len(nodes),
            "unsupported_resources": len(unsupported),
            "resource_counts": resource_counts,
            "provider_counts": provider_counts,
        },
        "service_keys": sorted(service_keys),
    }
