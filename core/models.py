"""Pydantic request/response models for CloudLearn API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Licensing / General
# ---------------------------------------------------------------------------

class LicenseSignupRequest(BaseModel):
    email: str
    user: str = "guest"
    tier: str = "free"
    device_id: str = ""
    # Day 2-C: Student tier picks ONE primary cloud (aws|gcp|azure) at signup.
    primary_cloud: str = ""
    # Day 2-D: annual vs monthly subscription. annual gets ~7-month price savings
    # (already in tier_policy.price_inr_annual). Default monthly.
    period: str = "monthly"  # "monthly" | "annual"
    # Day 2-D: Enterprise tier needs a seat count (min 10).
    seats: int = 1


class ServiceActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

class IAMUserRequest(BaseModel):
    user_name: str
    path: str = "/"


class IAMRoleRequest(BaseModel):
    role_name: str
    path: str = "/"
    assume_role_policy_document: dict[str, Any] = {}
    description: str = ""


class IAMGroupRequest(BaseModel):
    group_name: str
    path: str = "/"


class IAMPolicyRequest(BaseModel):
    policy_name: str
    document: dict[str, Any] = {}


class IAMIdentityProviderRequest(BaseModel):
    provider_name: str
    provider_type: str = "SAML"
    url: str = ""
    tags: list[dict[str, str]] | None = None


class IAMAccountSettingsRequest(BaseModel):
    password_policy: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# EC2 / GCP Compute
# ---------------------------------------------------------------------------

class EC2InstanceRequest(BaseModel):
    name: str
    instance_type: str = "t3.micro"
    ami: str = "sim-ubuntu-22.04"
    runtime: str = "python"
    runtime_backend: str = ""
    key_pair: str = ""
    subnet_id: str = ""
    vpc_id: str = ""
    security_group_ids: list[str] = []
    az: str = "us-east-1a"
    storage_gb: int = 8
    command: str = ""
    user_data: str = ""


class GCPComputeInstanceRequest(BaseModel):
    project: str = "cloudlearn"
    zone: str = "us-central1-a"
    name: str = "gcp-instance"
    machineType: str = "e2-micro"
    tags: dict = {}
    sourceImage: str = "sim-ubuntu-22.04"
    runtime: str = "python"
    runtimeBackend: str = ""
    keyPair: str = ""
    subnetId: str = ""
    vpcId: str = ""
    securityGroupIds: list[str] = []
    bootDiskSizeGb: int = 8
    bootDiskType: str = "Balanced persistent disk"
    assignExternalIp: bool = True
    serviceAccount: str = "default"
    shieldedVm: bool = True
    vtpm: bool = True
    integrityMonitoring: bool = True
    startupScript: str = ""
    startupCommand: str = ""
    labels: dict[str, str] = {}


class EC2ConsoleInputRequest(BaseModel):
    data: str = ""


class EC2ConsoleCommandRequest(BaseModel):
    command: str = ""


class GCPComputeConsoleCommandRequest(BaseModel):
    command: str = ""


# ---------------------------------------------------------------------------
# VPC / Networking
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API Gateway
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

class LambdaFunctionRequest(BaseModel):
    function_name: str
    runtime: str = "python3.12"
    handler: str = "lambda_function.lambda_handler"
    role: str = "arn:aws:iam::123456789012:role/service-role/cloudlearn-lambda-basic-execution"
    description: str = ""
    code: str = ""
    timeout: int = 3
    memory_size: int = 128
    environment: dict[str, str] = {}
    tags: list[dict[str, str]] | None = None
    layers: list[str] = []


class LambdaFunctionUpdateRequest(BaseModel):
    runtime: str | None = None
    handler: str | None = None
    role: str | None = None
    description: str | None = None
    timeout: int | None = None
    memory_size: int | None = None
    code: str | None = None
    environment: dict[str, str] | None = None
    tags: list[dict[str, str]] | None = None


class LambdaInvokeRequest(BaseModel):
    payload: Any = {}
    invocation_type: str = "RequestResponse"
    log_type: str = "None"


class LambdaVersionRequest(BaseModel):
    description: str = ""


class LambdaPermissionRequest(BaseModel):
    statement_id: str = ""
    action: str = "lambda:InvokeFunction"
    principal: str = ""
    source_arn: str = ""
    source_account: str = ""
    revision_id: str = ""


class LambdaLayerRequest(BaseModel):
    name: str
    description: str = ""
    runtime: str = "python3.12"
    code: str = ""
    license_info: str = ""


# ---------------------------------------------------------------------------
# SQS
# ---------------------------------------------------------------------------

class SQSQueueCreateRequest(BaseModel):
    queue_name: str
    fifo_queue: bool = False
    content_based_deduplication: bool = False
    visibility_timeout: int = 30
    receive_wait_time_seconds: int = 0
    message_retention_period: int = 345600
    max_message_size: int = 262144
    delay_seconds: int = 0
    redrive_policy: dict[str, Any] | None = None
    tags: dict[str, str] | None = None


class SQSQueueUpdateRequest(BaseModel):
    visibility_timeout: int | None = None
    receive_wait_time_seconds: int | None = None
    message_retention_period: int | None = None
    max_message_size: int | None = None
    delay_seconds: int | None = None
    content_based_deduplication: bool | None = None
    redrive_policy: dict[str, Any] | None = None
    tags: dict[str, str] | None = None


class SQSMessageSendRequest(BaseModel):
    message_body: str = ""
    message_attributes: dict[str, Any] | None = None
    message_attributes_map: dict[str, Any] | None = None
    message_group_id: str = ""
    message_deduplication_id: str = ""


class SQSReceiveRequest(BaseModel):
    max_number_of_messages: int = 1
    wait_time_seconds: int = 0
    visibility_timeout: int | None = None


class SQSVisibilityRequest(BaseModel):
    visibility_timeout: int = 30


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------

class DynamoDBTableRequest(BaseModel):
    table_name: str
    partition_key_name: str = "id"
    partition_key_type: str = "S"
    sort_key_name: str = ""
    sort_key_type: str = "S"
    billing_mode: str = "PAY_PER_REQUEST"
    read_capacity_units: int = 5
    write_capacity_units: int = 5
    tags: dict[str, str] | None = None


class DynamoDBItemRequest(BaseModel):
    item: dict[str, Any] = {}
    key: dict[str, Any] = {}
    return_values: str = "NONE"
    attribute_updates: dict[str, Any] | None = None
    update_expression: str = ""
    expression_attribute_values: dict[str, Any] | None = None


class DynamoDBQueryRequest(BaseModel):
    partition_key_value: Any = None
    sort_key_equals: Any = None
    sort_key_begins_with: str = ""
    sort_key_between: list[Any] | None = None
    limit: int = 100
    key_condition_expression: str = ""
    expression_attribute_values: dict[str, Any] | None = None
    expression_attribute_names: dict[str, str] | None = None


class DynamoDBScanRequest(BaseModel):
    limit: int = 100


class DynamoDBTagRequest(BaseModel):
    tags: dict[str, str] = {}


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

class BucketVersioningRequest(BaseModel):
    status: str


class S3NotificationRuleRequest(BaseModel):
    id: str = ""
    destination_type: str = "TopicConfiguration"
    destination: str = ""
    events: list[str] = []
    prefix: str = ""
    suffix: str = ""


class BucketNotificationRequest(BaseModel):
    event_bridge_enabled: bool = False
    rules: list[S3NotificationRuleRequest] = []


# ---------------------------------------------------------------------------
# Deployment / Terraform
# ---------------------------------------------------------------------------

class DeploymentRequest(BaseModel):
    name: str
    source_url: str = ""
    runtime: str = "python"
    command: str = ""
    branch: str = "main"
    repo: str = ""


class TerraformWorkflowRequest(BaseModel):
    plan_id: str = ""
    confirm: bool = False
