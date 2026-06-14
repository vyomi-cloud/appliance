"""Minimal valid create payloads per (provider, service) tuple.

Each entry is what the test harness POSTs/PUTs to the create endpoint.
Goal: smallest payload the backend will accept WITHOUT downstream
provisioning side-effects (no LXD container creates, no real Postgres
spawn) so the suite stays fast and deterministic.

`payload_for(provider, service)` returns the dict or None. None means
"the test harness should skip create for this service" (use sparingly —
prefer adding a sensible payload).

## Per-run uniqueness (session 5)

Backends like S3 / DynamoDB / SQS / Lambda return ``409`` (or the AWS
contract-equivalent) when a name collides with an existing resource.
The conformance state DB is persistent across runs, so the second run
in a row gets ``409`` on every name-collision-sensitive ``create``.

To keep the suite idempotent we append a per-process random suffix to
the canonical name field(s) before returning the payload. The harness
captures the actual name back out of the create response, so subsequent
``get`` / ``delete`` still target the right resource.

The suffix is picked once at import time (kept stable within a test
session) so reruns inside one pytest invocation are still
deterministic.
"""
from __future__ import annotations
import copy
import os
from typing import Optional


# Stable per-process suffix appended to name-like fields in create
# payloads so two back-to-back conformance runs don't 409 each other.
_RUN_SUFFIX = os.urandom(2).hex()


# Field paths within payloads that hold the canonical resource name.
# Format: list of (dotted-path, …) per (provider, service); the first
# matching path that exists in the payload gets the suffix appended.
# We don't enumerate every payload — instead, we use a generic strategy
# below: any top-level string field named "name" / "queue_name" /
# "table_name" / "function_name" / "user_name" / "secretId" /
# "accountId" / "keyRingId" / "apiId" / "db_instance_identifier" /
# "tag_name" gets the suffix. For nested GCP-style paths like
# "projects/<p>/topics/<t>" we extend the trailing segment.
_NAME_KEYS = {
    "name", "queue_name", "table_name", "function_name", "user_name",
    "secretId", "accountId", "keyRingId", "apiId", "tag_name",
    "db_instance_identifier",
}


_AWS_PAYLOADS: dict[str, dict] = {
    "s3":         {"name": "vyomi-conformance-test"},
    "ec2":        {"name": "conformance-test-vm", "ami": "sim-ubuntu-22.04",
                   "instance_type": "t3.nano"},
    "iam":        {"user_name": "vyomi-conformance-user"},
    "vpc":        {"name": "vyomi-conformance-vpc", "cidr_block": "10.99.0.0/16"},
    "rds":        {"db_instance_identifier": "vyomi-conf-db",
                   "engine": "postgres",
                   "db_instance_class": "db.t3.micro",
                   "master_username": "admin",
                   "master_user_password": "ConfTest123!",
                   "allocated_storage": 20},
    "lambda":     {"function_name": "vyomi-conf-fn", "runtime": "python3.11",
                   "handler": "index.handler", "role": "arn:aws:iam::123:role/lambda-x",
                   "code": {"zip_file": "print('hi')"}},
    "apigateway": {"name": "vyomi-conf-api"},
    "dynamodb":   {"table_name": "vyomi-conf-table",
                   "attribute_definitions": [{"attribute_name": "id", "attribute_type": "S"}],
                   "key_schema": [{"attribute_name": "id", "key_type": "HASH"}],
                   "billing_mode": "PAY_PER_REQUEST"},
    "sqs":        {"queue_name": "vyomi-conf-queue"},
    "eventbridge": {"name": "vyomi-conf-rule", "event_pattern": '{"source":["test"]}'},
    "secretsmanager": {"name": "vyomi-conf-secret", "secret_string": "hello"},
    "kms":        {"description": "vyomi-conf-key"},
}


_GCP_PAYLOADS: dict[str, dict] = {
    "compute":     {"name": "conf-test-vm",
                    "machineType": "zones/us-central1-a/machineTypes/e2-micro",
                    "disks": [{"boot": True, "initializeParams": {"sourceImage": "sim-ubuntu-22.04"}}],
                    "networkInterfaces": [{"network": "default"}]},
    "storage":     {"name": "vyomi-conf-gcs"},
    "sql":         {"name": "vyomi-conf-sql", "databaseVersion": "POSTGRES_15",
                    "settings": {"tier": "db-f1-micro"}},
    "pubsub":      {"name": "projects/cloudlearn/topics/vyomi-conf-topic"},
    "firestore":   {"name": "(default)", "type": "FIRESTORE_NATIVE"},
    "functions":   {"name": "projects/cloudlearn/locations/us-central1/functions/vyomi-conf-fn",
                    "runtime": "python311", "entryPoint": "main",
                    "httpsTrigger": {}},
    "iam":         {"accountId": "vyomi-conf-sa", "serviceAccount": {"displayName": "Conf"}},
    "vpc":         {"name": "vyomi-conf-vpc", "autoCreateSubnetworks": False},
    "apigateway":  {"apiId": "vyomi-conf-api", "displayName": "Conf"},
    "eventarc":    {"name": "vyomi-conf-trigger",
                    "destination": {"cloudRun": {"service": "demo"}}},
    "secretmanager": {"secretId": "vyomi-conf-secret",
                     "secret": {"replication": {"automatic": {}}}},
    "kms":         {"keyRingId": "vyomi-conf-ring"},
}


_AZURE_PAYLOADS: dict[str, dict] = {
    "vm":          {"location": "eastus",
                    "properties": {
                        "hardwareProfile": {"vmSize": "Standard_B1s"},
                        "osProfile": {"computerName": "conf-vm", "adminUsername": "admin",
                                      "adminPassword": "ConfTest123!"},
                        "storageProfile": {"imageReference": {"publisher": "Canonical",
                                                              "offer": "UbuntuServer", "sku": "22_04-lts",
                                                              "version": "latest"}},
                        "networkProfile": {"networkInterfaces": []}}},
    "sql":         {"location": "eastus",
                    "properties": {"administratorLogin": "admin",
                                   "administratorLoginPassword": "ConfTest123!"}},
    "storage":     {"location": "eastus", "kind": "StorageV2",
                    "sku": {"name": "Standard_LRS"}},
    "cosmos":      {"location": "eastus",
                    "properties": {"databaseAccountOfferType": "Standard",
                                   "locations": [{"locationName": "eastus"}]}},
    "functionapp": {"location": "eastus", "kind": "functionapp",
                    "properties": {"serverFarmId": "/subscriptions/sim-sub/resourceGroups/cloudlearn-rg/providers/Microsoft.Web/serverfarms/asp"}},
    "servicebus":  {"location": "eastus", "sku": {"name": "Standard"}},
    "apim":        {"location": "eastus", "sku": {"name": "Developer", "capacity": 1},
                    "properties": {"publisherEmail": "test@vyomi.cloud", "publisherName": "Vyomi"}},
    "vnet":        {"location": "eastus",
                    "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}},
    "keyvault":    {"location": "eastus",
                    "properties": {"tenantId": "00000000-0000-0000-0000-000000000000",
                                   "sku": {"family": "A", "name": "standard"},
                                   "accessPolicies": []}},
    "eventgrid":   {"location": "eastus", "properties": {}},
}


def _apply_run_suffix(payload: dict) -> dict:
    """Append the per-run suffix to any name-like field so two back-to-back
    runs don't collide. Mutates a deep-copy and returns it.

    Strategy:
      - top-level keys in ``_NAME_KEYS`` whose value is a string get the
        suffix appended after a ``-`` separator
      - GCP "fully-qualified" names like ``projects/p/topics/foo`` keep
        their prefix and only the trailing segment is suffixed
      - non-string / nested / unrecognized fields are left alone
    """
    out = copy.deepcopy(payload)
    for k in list(out.keys()):
        if k not in _NAME_KEYS:
            continue
        v = out[k]
        if not isinstance(v, str) or not v:
            continue
        if "/" in v:
            # GCP-style "projects/<p>/topics/<t>" — suffix the last segment
            parts = v.rsplit("/", 1)
            out[k] = f"{parts[0]}/{parts[1]}-{_RUN_SUFFIX}"
        else:
            out[k] = f"{v}-{_RUN_SUFFIX}"
    return out


def payload_for(provider: str, service: str) -> Optional[dict]:
    table = {"aws": _AWS_PAYLOADS, "gcp": _GCP_PAYLOADS, "azure": _AZURE_PAYLOADS}.get(
        provider.lower(), {})
    raw = table.get(service.lower())
    if raw is None:
        return None
    return _apply_run_suffix(raw)


# ── Per-action sub-resource payloads ─────────────────────────────────────────
#
# Some catalog actions are sub-resource creates (createSubnet, addRoute, etc.)
# whose payload depends on an id captured from an earlier create. Rather than
# carry runtime context in this module, we publish a *template* keyed by
# (provider, service, action) and let the harness do the substitution.
#
# Substitution markers (string contents):
#   __VPC_ID__ → captured vpc.create vpc_id
#   __SG_ID__  → captured vpc.createSecurityGroup security_group_id
#   __RTB_ID__ → captured vpc.createRouteTable route_table_id
#   __IGW_ID__ → captured vpc.createIgw internet_gateway_id
#   __SUBNET_ID__ → captured vpc.createSubnet subnet_id
#
# An action payload is dropped only when ALL its placeholders resolved. Missing
# any one → harness skips the action (records as parent-dependent).

_SUB_ACTION_PAYLOADS: dict[tuple[str, str, str], dict] = {
    # AWS S3
    ("aws", "s3", "versioning"): {
        "status": "Enabled",
    },
    ("aws", "s3", "notifications"): {
        "event_bridge_enabled": False,
        "rules": [],
    },
    # AWS VPC
    ("aws", "vpc", "createSubnet"): {
        "vpc_id": "__VPC_ID__",
        "cidr_block": "10.99.1.0/24",
        "availability_zone": "us-east-1a",
        "name": "vyomi-conf-subnet",
    },
    ("aws", "vpc", "createSecurityGroup"): {
        "vpc_id": "__VPC_ID__",
        "group_name": "vyomi-conf-sg",
        "description": "conformance security group",
    },
    ("aws", "vpc", "createRouteTable"): {
        "vpc_id": "__VPC_ID__",
        "name": "vyomi-conf-rtb",
    },
    ("aws", "vpc", "createIgw"): {
        "name": "vyomi-conf-igw",
    },
    ("aws", "vpc", "attachIgw"): {
        "vpc_id": "__VPC_ID__",
    },
    ("aws", "vpc", "addIngress"): {
        "protocol": "tcp",
        "from_port": 80,
        "to_port": 80,
        "cidr": "0.0.0.0/0",
        "description": "conformance ingress",
    },
    ("aws", "vpc", "addRoute"): {
        "destination_cidr": "0.0.0.0/0",
        "target_type": "internet-gateway",
        "target_id": "__IGW_ID__",
    },
    ("aws", "vpc", "associateSubnet"): {
        "subnet_id": "__SUBNET_ID__",
    },
}


def sub_action_payload(provider: str, service: str, action: str) -> Optional[dict]:
    """Return the template for a sub-action's payload, or None if no entry.

    The returned dict still contains __XXX__ markers — the harness substitutes
    captured ids before sending. We deep-copy so each call gets a fresh dict.
    """
    raw = _SUB_ACTION_PAYLOADS.get((provider.lower(), service.lower(), action))
    if raw is None:
        return None
    return copy.deepcopy(raw)


def current_run_suffix() -> str:
    """Exposed for the harness so it can document the suffix in REPORT.md
    or use it when constructing cleanup queries.
    """
    return _RUN_SUFFIX
