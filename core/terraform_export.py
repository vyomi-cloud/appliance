from __future__ import annotations

import copy
import re
import json
from datetime import datetime, timezone
from typing import Any


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


def _provider_alias(provider: str) -> str:
    provider = _string(provider).lower()
    if provider == "aws":
        return "aws"
    if provider == "gcp":
        return "google"
    return provider or "cloudlearn"


def _resource_type(provider: str, service: str, kind: str) -> str | None:
    provider = _string(provider).lower()
    service = _string(service).lower()
    kind = _string(kind).lower()
    mapping = {
        ("aws", "ec2", "instance"): "aws_instance",
        ("aws", "s3", "bucket"): "aws_s3_bucket",
        ("aws", "vpc", "vpc"): "aws_vpc",
        ("aws", "vpc", "subnet"): "aws_subnet",
        ("aws", "vpc", "security_group"): "aws_security_group",
        ("aws", "vpc", "route_table"): "aws_route_table",
        ("aws", "vpc", "internet_gateway"): "aws_internet_gateway",
        ("aws", "rds", "instance"): "aws_db_instance",
        ("aws", "rds", "db_instance"): "aws_db_instance",
        ("aws", "rds", "subnet_group"): "aws_db_subnet_group",
        ("aws", "rds", "parameter_group"): "aws_db_parameter_group",
        ("aws", "lambda", "function"): "aws_lambda_function",
        ("aws", "sqs", "queue"): "aws_sqs_queue",
        ("aws", "dynamodb", "table"): "aws_dynamodb_table",
        ("aws", "apigateway", "api"): "aws_api_gateway_rest_api",
        ("gcp", "compute", "instance"): "google_compute_instance",
        ("gcp", "storage", "bucket"): "google_storage_bucket",
        ("gcp", "sql", "instance"): "google_sql_database_instance",
        ("gcp", "pubsub", "topic"): "google_pubsub_topic",
        ("gcp", "pubsub", "subscription"): "google_pubsub_subscription",
        ("gcp", "firestore", "database"): "google_firestore_database",
        ("gcp", "functions", "function"): "google_cloudfunctions_function",
        ("gcp", "vpc", "network"): "google_compute_network",
        ("gcp", "vpc", "subnetwork"): "google_compute_subnetwork",
        ("gcp", "vpc", "firewall"): "google_compute_firewall",
        ("gcp", "vpc", "route"): "google_compute_route",
        ("gcp", "apigateway", "api"): "google_api_gateway_api",
        ("gcp", "apigateway", "api_config"): "google_api_gateway_api_config",
        ("gcp", "apigateway", "gateway"): "google_api_gateway_gateway",
        ("gcp", "iam", "service_account"): "google_service_account",
    }
    return mapping.get((provider, service, kind))


_HCL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _hcl_key(value: Any) -> str:
    text = _string(value)
    if not text:
        return json.dumps("")
    return text if _HCL_IDENTIFIER.match(text) else json.dumps(text)


def _hcl_value(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    inner_pad = "  " * (indent + 1)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for key, item in value.items():
            lines.append(f"{inner_pad}{_hcl_key(key)} = {_hcl_value(item, indent + 1)}")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        for item in value:
            lines.append(f"{inner_pad}{_hcl_value(item, indent + 1)},")
        lines.append(f"{pad}]")
        return "\n".join(lines)
    return json.dumps(str(value))


def _hcl_block(kind: str, labels: list[str] | tuple[str, ...] | None, attrs: dict[str, Any], indent: int = 0) -> str:
    pad = "  " * indent
    label_text = "".join(f" {json.dumps(_string(label))}" for label in (labels or []))
    lines = [f"{pad}{kind}{label_text} {{"]
    for key, value in attrs.items():
        lines.append(f"{pad}  {_hcl_key(key)} = {_hcl_value(value, indent + 1)}")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def terraform_hcl_files(export_payload: dict[str, Any]) -> dict[str, str]:
    terraform_json = copy.deepcopy(export_payload.get("terraform_json") or {})
    terraform_meta = terraform_json.get("terraform", {})
    provider_configs = terraform_json.get("provider", {})
    resource_groups = terraform_json.get("resource", {})

    files: dict[str, str] = {}
    header = "# Generated by CloudLearn. This file is derived from the canonical simulator resource graph.\n"

    versions_body = ""
    if isinstance(terraform_meta, dict) and terraform_meta:
        versions_body = _hcl_block("terraform", [], terraform_meta)
    else:
        versions_body = "terraform {}\n"
    files["versions.tf"] = f"{header}\n{versions_body}\n"

    provider_blocks: list[str] = []
    if isinstance(provider_configs, dict):
        for provider_name in sorted(provider_configs.keys()):
            provider_attrs = provider_configs.get(provider_name)
            if not isinstance(provider_attrs, dict):
                provider_attrs = {}
            provider_blocks.append(_hcl_block("provider", [provider_name], provider_attrs))
    files["providers.tf"] = f"{header}\n" + ("\n\n".join(provider_blocks) + "\n" if provider_blocks else "# No provider configuration was exported.\n")

    resource_blocks: list[str] = []
    if isinstance(resource_groups, dict):
        for resource_type in sorted(resource_groups.keys()):
            resources = resource_groups.get(resource_type)
            if not isinstance(resources, dict):
                continue
            for resource_name in sorted(resources.keys()):
                attrs = resources.get(resource_name)
                if not isinstance(attrs, dict):
                    attrs = {}
                resource_blocks.append(_hcl_block("resource", [resource_type, resource_name], attrs))
    files["main.tf"] = f"{header}\n" + ("\n\n".join(resource_blocks) + "\n" if resource_blocks else "# No supported Terraform resources were exported.\n")
    return files


def _base_terraform_attrs(node: dict[str, Any], tf_type: str, space: dict[str, Any]) -> dict[str, Any]:
    name = _string(node.get("name") or node.get("resource_id") or node.get("id"), "resource")
    resource_id = _string(node.get("resource_id") or node.get("id"), name)
    provider = _string(node.get("provider"), "")
    service = _string(node.get("service"), "")
    kind = _string(node.get("kind"), "")
    location = _string(node.get("location") or node.get("region") or node.get("zone"), "")
    region = _string(space.get("active_region"), "")
    attrs: dict[str, Any] = {
        "tags": {"Name": name},
    }

    if tf_type == "aws_instance":
        attrs.update(
            {
                "ami": _string(node.get("ami") or node.get("runtime_image"), "ami-placeholder"),
                "instance_type": _string(node.get("instance_type"), "t3.micro"),
            }
        )
        if location:
            attrs["availability_zone"] = location
        if _string(node.get("subnet_id")):
            attrs["subnet_id"] = _string(node.get("subnet_id"))
        return attrs

    if tf_type == "aws_s3_bucket":
        attrs.update({"bucket": _string(node.get("bucket") or name, name)})
        return attrs

    if tf_type == "aws_vpc":
        attrs.update({"cidr_block": _string(node.get("cidr_block"), "10.0.0.0/16")})
        return attrs

    if tf_type == "aws_subnet":
        attrs.update(
            {
                "vpc_id": _string(node.get("vpc_id"), "vpc-placeholder"),
                "cidr_block": _string(node.get("cidr_block"), "10.0.1.0/24"),
            }
        )
        if location:
            attrs["availability_zone"] = location
        return attrs

    if tf_type == "aws_security_group":
        attrs.update(
            {
                "name": name,
                "description": _string(node.get("description"), f"CloudLearn generated security group for {name}"),
                "vpc_id": _string(node.get("vpc_id"), "vpc-placeholder"),
            }
        )
        return attrs

    if tf_type == "aws_route_table":
        attrs.update(
            {
                "vpc_id": _string(node.get("vpc_id"), "vpc-placeholder"),
            }
        )
        return attrs

    if tf_type == "aws_internet_gateway":
        attrs.update(
            {
                "vpc_id": _string(node.get("vpc_id"), "vpc-placeholder"),
            }
        )
        return attrs

    if tf_type == "aws_db_instance":
        attrs.update(
            {
                "identifier": name,
                "engine": _string(node.get("engine"), "postgres"),
                "instance_class": _string(node.get("instance_class"), "db.t3.micro"),
                "allocated_storage": int(node.get("allocated_storage") or 20),
                "username": _string(node.get("master_username"), "dbadmin"),
            }
        )
        return attrs

    if tf_type == "aws_db_subnet_group":
        attrs.update(
            {
                "name": name,
                "description": _string(node.get("description"), f"CloudLearn generated subnet group for {name}"),
                "subnet_ids": copy.deepcopy(node.get("subnet_ids") or []),
            }
        )
        return attrs

    if tf_type == "aws_db_parameter_group":
        attrs.update(
            {
                "name": name,
                "family": _string(node.get("family"), "postgres16"),
                "description": _string(node.get("description"), f"CloudLearn generated parameter group for {name}"),
            }
        )
        return attrs

    if tf_type == "aws_lambda_function":
        attrs.update(
            {
                "function_name": name,
                "runtime": _string(node.get("runtime"), "python3.12"),
                "handler": _string(node.get("handler"), "lambda_function.lambda_handler"),
                "role": _string(node.get("role"), "arn:aws:iam::123456789012:role/service-role/cloudlearn-lambda-basic-execution"),
            }
        )
        return attrs

    if tf_type == "aws_sqs_queue":
        attrs.update({"name": name})
        return attrs

    if tf_type == "aws_dynamodb_table":
        attrs.update({"name": name, "billing_mode": _string(node.get("billing_mode"), "PAY_PER_REQUEST")})
        return attrs

    if tf_type == "aws_api_gateway_rest_api":
        attrs.update({"name": name, "description": _string(node.get("description"), f"CloudLearn generated API for {name}")})
        return attrs

    if tf_type == "google_compute_instance":
        attrs.update(
            {
                "name": name,
                "zone": location or "us-central1-a",
                "machine_type": _string(node.get("machine_type"), "e2-micro"),
                "allow_stopping_for_update": True,
            }
        )
        return attrs

    if tf_type == "google_storage_bucket":
        attrs.update({"name": _string(node.get("bucket") or name, name), "location": region or "US"})
        return attrs

    if tf_type == "google_sql_database_instance":
        attrs.update(
            {
                "name": name,
                "region": region or "us-central1",
                "database_version": _string(node.get("database_version"), "POSTGRES_16"),
            }
        )
        return attrs

    if tf_type == "google_pubsub_topic":
        attrs.update({"name": name})
        return attrs

    if tf_type == "google_pubsub_subscription":
        attrs.update({"name": name, "topic": _string(node.get("topic"), "projects/cloudlearn/topics/sample")})
        return attrs

    if tf_type == "google_firestore_database":
        attrs.update({"name": _string(node.get("database"), "(default)"), "location_id": region or "us-central"})
        return attrs

    if tf_type == "google_cloudfunctions_function":
        attrs.update(
            {
                "name": name,
                "runtime": _string(node.get("runtime"), "python312"),
                "available_memory_mb": int(node.get("memory_mb") or 256),
            }
        )
        return attrs

    if tf_type == "google_compute_network":
        attrs.update({"name": name, "auto_create_subnetworks": False})
        return attrs

    if tf_type == "google_compute_subnetwork":
        attrs.update(
            {
                "name": name,
                "network": _string(node.get("network"), "projects/cloudlearn/global/networks/default"),
                "region": region or "us-central1",
                "ip_cidr_range": _string(node.get("cidr_block"), "10.0.1.0/24"),
            }
        )
        return attrs

    if tf_type == "google_compute_firewall":
        attrs.update(
            {
                "name": name,
                "network": _string(node.get("network"), "projects/cloudlearn/global/networks/default"),
            }
        )
        return attrs

    if tf_type == "google_compute_route":
        attrs.update(
            {
                "name": name,
                "network": _string(node.get("network"), "projects/cloudlearn/global/networks/default"),
                "dest_range": _string(node.get("dest_range"), "0.0.0.0/0"),
            }
        )
        return attrs

    if tf_type == "google_api_gateway_api":
        attrs.update({"api_id": name, "display_name": _string(node.get("display_name"), name)})
        return attrs

    if tf_type == "google_api_gateway_api_config":
        attrs.update({"api_config_id": name, "api": _string(node.get("api"), name), "display_name": _string(node.get("display_name"), name)})
        return attrs

    if tf_type == "google_api_gateway_gateway":
        attrs.update({"gateway_id": name, "api_config": _string(node.get("api_config"), name), "display_name": _string(node.get("display_name"), name)})
        return attrs

    if tf_type == "google_service_account":
        attrs.update(
            {
                "account_id": _slug(node.get("account_id") or name, "service_account"),
                "display_name": _string(node.get("display_name"), name),
            }
        )
        return attrs

    attrs.update(
        {
            "name": name,
            "description": f"Draft Terraform export for {provider}.{service}.{kind} ({resource_id})",
        }
    )
    return attrs


def export_space_to_terraform_json(space: dict[str, Any]) -> dict[str, Any]:
    space = copy.deepcopy(space or {})
    resources = space.get("resources", {})
    nodes = resources.get("nodes", []) if isinstance(resources, dict) else []
    if not isinstance(nodes, list):
        nodes = []

    provider_configs: dict[str, dict[str, Any]] = {}
    terraform_resources: dict[str, dict[str, dict[str, Any]]] = {}
    unsupported: list[dict[str, Any]] = []
    used_names: set[tuple[str, str]] = set()

    active_region = _string(space.get("active_region"), "us-east-1")
    active_provider = _string(space.get("provider"), "aws").lower()
    project = _string(space.get("gcp_project_id") or space.get("active_account") or space.get("project_id") or space.get("name"), "cloudlearn")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        provider = _string(node.get("provider"), active_provider).lower()
        service = _string(node.get("service"), "")
        kind = _string(node.get("kind"), "")
        tf_type = _resource_type(provider, service, kind)
        if not tf_type:
            unsupported.append(
                {
                    "provider": provider,
                    "service": service,
                    "kind": kind,
                    "resource_id": _string(node.get("resource_id"), ""),
                    "name": _string(node.get("name"), ""),
                }
            )
            continue

        provider_alias = _provider_alias(provider)
        if provider_alias == "aws":
            provider_configs.setdefault(provider_alias, {"region": active_region})
        elif provider_alias == "google":
            provider_configs.setdefault(provider_alias, {"project": project, "region": active_region})
        else:
            provider_configs.setdefault(provider_alias, {})

        name_seed = _slug(node.get("name") or node.get("resource_id") or kind or tf_type)
        tf_name = name_seed
        suffix = 1
        while (tf_type, tf_name) in used_names:
            suffix += 1
            tf_name = f"{name_seed}_{suffix}"
        used_names.add((tf_type, tf_name))
        terraform_resources.setdefault(tf_type, {})[tf_name] = _base_terraform_attrs(node, tf_type, space)

    terraform_json = {
        "terraform": {
            "required_version": ">= 1.6.0",
            "required_providers": {
                "aws": {"source": "hashicorp/aws", "version": "~> 5.0"},
                "google": {"source": "hashicorp/google", "version": "~> 5.0"},
            },
        },
        "provider": provider_configs,
        "resource": terraform_resources,
    }

    export_payload = {
        "space_id": _string(space.get("space_id"), ""),
        "space_name": _string(space.get("name"), ""),
        "provider": active_provider,
        "generated_at": _now(),
        "terraform_json": terraform_json,
        "summary": {
            "resource_count": len(nodes),
            "supported_resources": sum(len(items) for items in terraform_resources.values()),
            "unsupported_resources": len(unsupported),
        },
        "unsupported_resources": unsupported,
    }
    export_payload["terraform_hcl"] = terraform_hcl_files(export_payload)
    export_payload["summary"]["hcl_files"] = len(export_payload["terraform_hcl"])
    return export_payload
