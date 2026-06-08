from __future__ import annotations

import inspect
from typing import Any

from fastapi import Request

from .aws import tool_response as aws_tool_response
from . import aws_iam
from . import aws_rds, aws_services, aws_vpc
from core.tooling_simulators import aws_cli_resolve, sdk_snippet
from core import models as _models
from routes import aws_lambda as _routes_lambda
from routes import aws_sqs as _routes_sqs
from routes import aws_vpc as _routes_vpc
from routes import aws_rds as _routes_rds
from routes import aws_apigw as _routes_apigw
from routes import aws_dynamodb as _routes_dynamodb


_TARGET_OVERRIDES = {
    "api_iam_list_users": aws_iam.api_iam_list_users,
    "api_iam_create_user": aws_iam.api_iam_create_user,
    "api_iam_delete_user": aws_iam.api_iam_delete_user,
    "api_iam_list_groups": aws_iam.api_iam_list_groups,
    "api_iam_create_group": aws_iam.api_iam_create_group,
    "api_iam_delete_group": aws_iam.api_iam_delete_group,
    "api_iam_add_user_to_group": aws_iam.api_iam_add_user_to_group,
    "api_iam_remove_user_from_group": aws_iam.api_iam_remove_user_from_group,
    "api_iam_list_roles": aws_iam.api_iam_list_roles,
    "api_iam_create_role": aws_iam.api_iam_create_role,
    "api_iam_delete_role": aws_iam.api_iam_delete_role,
    "api_iam_list_policies": aws_iam.api_iam_list_policies,
    "api_iam_create_policy": aws_iam.api_iam_create_policy,
    "api_iam_delete_policy": aws_iam.api_iam_delete_policy,
    "api_iam_attach_policy": aws_iam.api_iam_attach_policy,
    "api_iam_detach_policy": aws_iam.api_iam_detach_policy,
    "api_iam_list_attachments": aws_iam.api_iam_list_attachments,
    "api_iam_list_identity_providers": aws_iam.api_iam_list_identity_providers,
    "api_iam_create_identity_provider": aws_iam.api_iam_create_identity_provider,
    "api_iam_delete_identity_provider": aws_iam.api_iam_delete_identity_provider,
    "api_iam_get_account_settings": aws_iam.api_iam_get_account_settings,
    "api_iam_update_account_settings": aws_iam.api_iam_update_account_settings,
    "api_vpc_list_vpcs": aws_vpc.api_vpc_list_vpcs,
    "api_vpc_create": aws_vpc.api_vpc_create,
    "api_vpc_delete": aws_vpc.api_vpc_delete,
    "api_vpc_create_subnet": aws_vpc.api_vpc_create_subnet,
    "api_vpc_create_security_group": aws_vpc.api_vpc_create_security_group,
    "api_vpc_add_ingress": aws_vpc.api_vpc_add_ingress,
    "api_vpc_list_subnets": aws_vpc.api_vpc_list_subnets,
    "api_vpc_list_security_groups": aws_vpc.api_vpc_list_security_groups,
    "api_vpc_list_route_tables": aws_vpc.api_vpc_list_route_tables,
    "api_vpc_create_route_table": aws_vpc.api_vpc_create_route_table,
    "api_vpc_list_internet_gateways": aws_vpc.api_vpc_list_internet_gateways,
    "api_vpc_create_internet_gateway": aws_vpc.api_vpc_create_internet_gateway,
    "api_vpc_attach_internet_gateway": aws_vpc.api_vpc_attach_internet_gateway,
    "api_vpc_add_route": aws_vpc.api_vpc_add_route,
    "api_vpc_associate_subnet": aws_vpc.api_vpc_associate_subnet,
    "api_vpc_resources": aws_vpc.api_vpc_resources,
    "api_rds_list_databases": aws_rds.api_rds_list_databases,
    "api_rds_create_database": aws_rds.api_rds_create_database,
    "api_rds_get_database": aws_rds.api_rds_get_database,
    "api_rds_start_database": aws_rds.api_rds_start_database,
    "api_rds_stop_database": aws_rds.api_rds_stop_database,
    "api_rds_reboot_database": aws_rds.api_rds_reboot_database,
    "api_rds_modify_database": aws_rds.api_rds_modify_database,
    "api_rds_delete_database": aws_rds.api_rds_delete_database,
    "api_rds_list_subnet_groups": aws_rds.api_rds_list_subnet_groups,
    "api_rds_create_subnet_group": aws_rds.api_rds_create_subnet_group,
    "api_rds_delete_subnet_group": aws_rds.api_rds_delete_subnet_group,
    "api_rds_list_parameter_groups": aws_rds.api_rds_list_parameter_groups,
    "api_rds_create_parameter_group": aws_rds.api_rds_create_parameter_group,
    "api_rds_delete_parameter_group": aws_rds.api_rds_delete_parameter_group,
    "api_rds_list_snapshots": aws_rds.api_rds_list_snapshots,
    "api_rds_create_snapshot": aws_rds.api_rds_create_snapshot,
    "api_rds_restore_snapshot": aws_rds.api_rds_restore_snapshot,
    "api_rds_add_tags": aws_rds.api_rds_add_tags,
    "api_rds_list_tags": aws_rds.api_rds_list_tags,
}

for _name in aws_services.TARGETS:
    _TARGET_OVERRIDES[_name] = getattr(aws_services, _name)

# Prefer route-module implementations where they exist (they still delegate
# to server.py helpers, but the handler layer is cleanly separated).
for _name in [
    "api_lambda_list_functions", "api_lambda_create_function",
    "api_lambda_get_function", "api_lambda_update_function_code",
    "api_lambda_update_function_configuration", "api_lambda_delete_function",
    "api_lambda_get_policy", "api_lambda_add_permission",
    "api_lambda_remove_permission", "api_lambda_list_invocations",
    "api_lambda_list_versions", "api_lambda_publish_version",
    "api_lambda_invoke_function",
    "api_lambda_list_layers", "api_lambda_create_layer",
    "api_lambda_get_layer", "api_lambda_delete_layer",
    "api_lambda_list_functions_aws", "api_lambda_create_function_aws",
    "api_lambda_get_function_aws", "api_lambda_delete_function_aws",
    "api_lambda_get_policy_aws", "api_lambda_add_permission_aws",
    "api_lambda_remove_permission_aws", "api_lambda_update_function_code_aws",
    "api_lambda_update_function_configuration_aws",
    "api_lambda_publish_version_aws", "api_lambda_list_versions_aws",
    "api_lambda_invoke_function_aws",
]:
    if hasattr(_routes_lambda, _name):
        _TARGET_OVERRIDES[_name] = getattr(_routes_lambda, _name)

for _name in [
    "api_sqs_query", "api_sqs_list_queues", "api_sqs_create_queue",
    "api_sqs_get_queue", "api_sqs_update_queue", "api_sqs_delete_queue",
    "api_sqs_list_messages", "api_sqs_send_message", "api_sqs_receive_message",
    "api_sqs_delete_message", "api_sqs_change_visibility", "api_sqs_purge",
    "api_sqs_list_tags", "api_sqs_tag_queue", "api_sqs_untag_queue",
]:
    if hasattr(_routes_sqs, _name):
        _TARGET_OVERRIDES[_name] = getattr(_routes_sqs, _name)

for _name in [
    "api_vpc_list_vpcs", "api_vpc_create", "api_vpc_delete",
    "api_vpc_create_subnet", "api_vpc_create_security_group",
    "api_vpc_add_ingress", "api_vpc_list_subnets",
    "api_vpc_list_security_groups", "api_vpc_list_route_tables",
    "api_vpc_create_route_table", "api_vpc_list_internet_gateways",
    "api_vpc_create_internet_gateway", "api_vpc_attach_internet_gateway",
    "api_vpc_add_route", "api_vpc_associate_subnet", "api_vpc_resources",
    "api_vpc_query",
]:
    if hasattr(_routes_vpc, _name):
        _TARGET_OVERRIDES[_name] = getattr(_routes_vpc, _name)

for _name in [
    "api_apigateway_list_apis", "api_apigateway_create_api",
    "api_apigateway_get_api", "api_apigateway_delete_api",
    "api_apigateway_list_resources", "api_apigateway_create_resource",
    "api_apigateway_put_method", "api_apigateway_put_integration",
    "api_apigateway_create_deployment", "api_apigateway_list_deployments",
    "api_apigateway_create_stage", "api_apigateway_list_stages",
    "api_apigateway_list_logs",
    "api_apigateway_invoke_path", "api_apigateway_invoke_root",
]:
    if hasattr(_routes_apigw, _name):
        _TARGET_OVERRIDES[_name] = getattr(_routes_apigw, _name)

for _name in [
    "api_dynamodb_list_tables", "api_dynamodb_create_table",
    "api_dynamodb_get_table", "api_dynamodb_delete_table",
    "api_dynamodb_list_items", "api_dynamodb_put_item",
    "api_dynamodb_update_item", "api_dynamodb_delete_item",
    "api_dynamodb_query_items", "api_dynamodb_scan_items",
    "api_dynamodb_list_tags", "api_dynamodb_tag_table",
    "api_dynamodb_untag_table",
    "api_dynamodb_aws",
]:
    if hasattr(_routes_dynamodb, _name):
        _TARGET_OVERRIDES[_name] = getattr(_routes_dynamodb, _name)

for _name in [
    "api_rds_list_databases", "api_rds_create_database",
    "api_rds_get_database", "api_rds_start_database",
    "api_rds_stop_database", "api_rds_reboot_database",
    "api_rds_modify_database", "api_rds_delete_database",
    "api_rds_list_subnet_groups", "api_rds_create_subnet_group",
    "api_rds_delete_subnet_group", "api_rds_list_parameter_groups",
    "api_rds_create_parameter_group", "api_rds_delete_parameter_group",
    "api_rds_list_snapshots", "api_rds_create_snapshot",
    "api_rds_restore_snapshot", "api_rds_add_tags", "api_rds_list_tags",
    "api_rds_query",
]:
    if hasattr(_routes_rds, _name):
        _TARGET_OVERRIDES[_name] = getattr(_routes_rds, _name)


def tool_response(tool: str) -> dict:
    return aws_tool_response(tool)


def cli_resolve(payload: dict[str, Any]) -> dict:
    return aws_cli_resolve(str(payload.get("command", "")))


def sdk_java_snippet() -> dict:
    return sdk_snippet("aws", "java")


def sdk_go_snippet() -> dict:
    return sdk_snippet("aws", "go")


def sdk_python_snippet() -> dict:
    return sdk_snippet("aws", "python")


def sdk_nodejs_snippet() -> dict:
    return sdk_snippet("aws", "nodejs")


def _server():
    import server as server_module

    return server_module


def _proxy(target_name: str, signature: str, body_mode: str = "none", body_target: str = "request", model_name: str = ""):
    namespace = {"Request": Request, "Any": Any}
    exec(f"def _stub{signature}:\n    pass", namespace)
    stub_signature = inspect.signature(namespace["_stub"])

    async def endpoint(**kwargs):
        if body_mode == "json":
            request = kwargs.pop("request", None)
            payload: dict[str, Any] = {}
            if request is not None:
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
            kwargs[body_target] = payload if isinstance(payload, dict) else {}
        elif body_mode == "model":
            request = kwargs.pop("request", None)
            payload: dict[str, Any] = {}
            if request is not None:
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
            model_cls = getattr(_models, model_name, None) or getattr(_server(), model_name)
            kwargs[body_target] = model_cls(**(payload if isinstance(payload, dict) else {}))
        target = _TARGET_OVERRIDES.get(target_name) or getattr(_server(), target_name)
        result = target(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    endpoint.__name__ = target_name
    endpoint.__signature__ = stub_signature
    return endpoint


def _add_route(app, method: str, path: str, target_name: str, signature: str, *, include_in_schema: bool = True, body_mode: str = "none", body_target: str = "request", model_name: str = "") -> None:
    app.add_api_route(
        path,
        _proxy(target_name, signature, body_mode=body_mode, body_target=body_target, model_name=model_name),
        methods=[method],
        include_in_schema=include_in_schema,
    )


def register(app, h) -> None:
    @app.get("/api/providers/aws/cli")
    def api_provider_aws_cli():
        return tool_response("cli")

    @app.get("/api/providers/aws/sdk/java")
    def api_provider_aws_sdk_java():
        return tool_response("sdk/java")

    @app.get("/api/providers/aws/sdk/go")
    def api_provider_aws_sdk_go():
        return tool_response("sdk/go")

    @app.get("/api/providers/aws/sdk/python")
    def api_provider_aws_sdk_python():
        return tool_response("sdk/python")

    @app.get("/api/providers/aws/sdk/nodejs")
    def api_provider_aws_sdk_nodejs():
        return tool_response("sdk/nodejs")

    @app.post("/api/providers/aws/cli/resolve")
    def api_provider_aws_cli_resolve(payload: dict[str, Any]):
        return cli_resolve(payload)

    @app.get("/api/providers/aws/sdk/java/snippet")
    def api_provider_aws_sdk_java_snippet():
        return sdk_java_snippet()

    @app.get("/api/providers/aws/sdk/go/snippet")
    def api_provider_aws_sdk_go_snippet():
        return sdk_go_snippet()

    @app.get("/api/providers/aws/sdk/python/snippet")
    def api_provider_aws_sdk_python_snippet():
        return sdk_python_snippet()

    @app.get("/api/providers/aws/sdk/nodejs/snippet")
    def api_provider_aws_sdk_nodejs_snippet():
        return sdk_nodejs_snippet()

    specs = [
        # IAM
        ("GET", "/api/iam/users", "api_iam_list_users", "()"),
        ("POST", "/api/iam/users", "api_iam_create_user", "(request: Request)", "model", "req", "IAMUserRequest"),
        ("DELETE", "/api/iam/users/{user_id}", "api_iam_delete_user", "(user_id: str)"),
        ("GET", "/api/iam/groups", "api_iam_list_groups", "()"),
        ("POST", "/api/iam/groups", "api_iam_create_group", "(request: Request)", "model", "req", "IAMGroupRequest"),
        ("DELETE", "/api/iam/groups/{group_id}", "api_iam_delete_group", "(group_id: str)"),
        ("POST", "/api/iam/groups/{group_id}/users", "api_iam_add_user_to_group", "(group_id: str, request: Request)", "json", "payload"),
        ("DELETE", "/api/iam/groups/{group_id}/users/{user_id}", "api_iam_remove_user_from_group", "(group_id: str, user_id: str)"),
        ("GET", "/api/iam/roles", "api_iam_list_roles", "()"),
        ("POST", "/api/iam/roles", "api_iam_create_role", "(request: Request)", "model", "req", "IAMRoleRequest"),
        ("DELETE", "/api/iam/roles/{role_id}", "api_iam_delete_role", "(role_id: str)"),
        ("GET", "/api/iam/policies", "api_iam_list_policies", "()"),
        ("POST", "/api/iam/policies", "api_iam_create_policy", "(request: Request)", "model", "req", "IAMPolicyRequest"),
        ("DELETE", "/api/iam/policies/{policy_id}", "api_iam_delete_policy", "(policy_id: str)"),
        ("POST", "/api/iam/attach-policy", "api_iam_attach_policy", "(request: Request)", "json", "payload"),
        ("DELETE", "/api/iam/attachments", "api_iam_detach_policy", "(request: Request)", "json", "payload"),
        ("GET", "/api/iam/attachments", "api_iam_list_attachments", "()"),
        ("GET", "/api/iam/identity-providers", "api_iam_list_identity_providers", "()"),
        ("POST", "/api/iam/identity-providers", "api_iam_create_identity_provider", "(request: Request)", "model", "req", "IAMIdentityProviderRequest"),
        ("DELETE", "/api/iam/identity-providers/{provider_id}", "api_iam_delete_identity_provider", "(provider_id: str)"),
        ("GET", "/api/iam/account-settings", "api_iam_get_account_settings", "()"),
        ("PUT", "/api/iam/account-settings", "api_iam_update_account_settings", "(request: Request)", "model", "req", "IAMAccountSettingsRequest"),
        # VPC
        ("GET", "/api/vpc/vpcs", "api_vpc_list_vpcs", "()"),
        ("POST", "/api/vpc/vpcs", "api_vpc_create", "(request: Request)", "model", "req", "VpcRequest"),
        ("DELETE", "/api/vpc/vpcs/{vpc_id}", "api_vpc_delete", "(vpc_id: str, force: bool = False)"),
        ("POST", "/api/vpc/subnets", "api_vpc_create_subnet", "(request: Request)", "model", "req", "SubnetRequest"),
        ("POST", "/api/vpc/security-groups", "api_vpc_create_security_group", "(request: Request)", "model", "req", "SecurityGroupRequest"),
        ("POST", "/api/vpc/security-groups/{sg_id}/ingress", "api_vpc_add_ingress", "(sg_id: str, request: Request)", "json", "payload"),
        ("GET", "/api/vpc/subnets", "api_vpc_list_subnets", "()"),
        ("GET", "/api/vpc/security-groups", "api_vpc_list_security_groups", "()"),
        ("GET", "/api/vpc/route-tables", "api_vpc_list_route_tables", "()"),
        ("POST", "/api/vpc/route-tables", "api_vpc_create_route_table", "(request: Request)", "model", "req", "RouteTableRequest"),
        ("GET", "/api/vpc/internet-gateways", "api_vpc_list_internet_gateways", "()"),
        ("POST", "/api/vpc/internet-gateways", "api_vpc_create_internet_gateway", "(request: Request)", "model", "req", "InternetGatewayRequest"),
        ("POST", "/api/vpc/internet-gateways/{igw_id}/attach", "api_vpc_attach_internet_gateway", "(igw_id: str, request: Request)", "json", "payload"),
        ("POST", "/api/vpc/route-tables/{rt_id}/routes", "api_vpc_add_route", "(rt_id: str, request: Request)", "json", "payload"),
        ("POST", "/api/vpc/route-tables/{rt_id}/associate-subnet", "api_vpc_associate_subnet", "(rt_id: str, request: Request)", "model", "req", "SubnetAssociationRequest"),
        ("GET", "/api/vpc/vpcs/{vpc_id}/resources", "api_vpc_resources", "(vpc_id: str)"),
        # RDS
        ("GET", "/api/rds/databases", "api_rds_list_databases", "()"),
        ("POST", "/api/rds/databases", "api_rds_create_database", "(request: Request)", "model", "req", "RDSDatabaseRequest"),
        ("GET", "/api/rds/databases/{db_instance_identifier}", "api_rds_get_database", "(db_instance_identifier: str)"),
        ("POST", "/api/rds/databases/{db_instance_identifier}/start", "api_rds_start_database", "(db_instance_identifier: str)"),
        ("POST", "/api/rds/databases/{db_instance_identifier}/stop", "api_rds_stop_database", "(db_instance_identifier: str)"),
        ("POST", "/api/rds/databases/{db_instance_identifier}/reboot", "api_rds_reboot_database", "(db_instance_identifier: str)"),
        ("PUT", "/api/rds/databases/{db_instance_identifier}", "api_rds_modify_database", "(db_instance_identifier: str, request: Request)", "model", "req", "RDSModifyRequest"),
        ("DELETE", "/api/rds/databases/{db_instance_identifier}", "api_rds_delete_database", "(db_instance_identifier: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = \"\")"),
        ("GET", "/api/rds/subnet-groups", "api_rds_list_subnet_groups", "()"),
        ("POST", "/api/rds/subnet-groups", "api_rds_create_subnet_group", "(request: Request)", "model", "req", "RDSSubnetGroupRequest"),
        ("DELETE", "/api/rds/subnet-groups/{db_subnet_group_name}", "api_rds_delete_subnet_group", "(db_subnet_group_name: str)"),
        ("GET", "/api/rds/parameter-groups", "api_rds_list_parameter_groups", "()"),
        ("POST", "/api/rds/parameter-groups", "api_rds_create_parameter_group", "(request: Request)", "model", "req", "RDSParameterGroupRequest"),
        ("DELETE", "/api/rds/parameter-groups/{db_parameter_group_name}", "api_rds_delete_parameter_group", "(db_parameter_group_name: str)"),
        ("GET", "/api/rds/snapshots", "api_rds_list_snapshots", "()"),
        ("POST", "/api/rds/databases/{db_instance_identifier}/snapshots", "api_rds_create_snapshot", "(db_instance_identifier: str, request: Request)", "model", "req", "RDSSnapshotRequest"),
        ("POST", "/api/rds/snapshots/{db_snapshot_identifier}/restore", "api_rds_restore_snapshot", "(db_snapshot_identifier: str, request: Request)", "model", "req", "RDSRestoreSnapshotRequest"),
        ("POST", "/api/rds/databases/{db_instance_identifier}/tags", "api_rds_add_tags", "(db_instance_identifier: str, request: Request)", "json", "payload"),
        ("GET", "/api/rds/databases/{db_instance_identifier}/tags", "api_rds_list_tags", "(db_instance_identifier: str)"),
        ("GET", "/rds", "api_rds_query", "(request: Request)", "none", "request", "", False),
        ("POST", "/rds", "api_rds_query", "(request: Request)", "none", "request", "", False),
        ("GET", "/api/rds/aws", "api_rds_query", "(request: Request)", "none", "request", "", False),
        ("POST", "/api/rds/aws", "api_rds_query", "(request: Request)", "none", "request", "", False),
        # SQS
        ("GET", "/api/sqs/queues", "api_sqs_list_queues", "()"),
        ("POST", "/api/sqs/queues", "api_sqs_create_queue", "(request: Request)", "model", "req", "SQSQueueCreateRequest"),
        ("GET", "/api/sqs/queues/{queue_name}", "api_sqs_get_queue", "(queue_name: str)"),
        ("PUT", "/api/sqs/queues/{queue_name}", "api_sqs_update_queue", "(queue_name: str, request: Request)", "model", "req", "SQSQueueUpdateRequest"),
        ("DELETE", "/api/sqs/queues/{queue_name}", "api_sqs_delete_queue", "(queue_name: str)"),
        ("GET", "/api/sqs/queues/{queue_name}/messages", "api_sqs_list_messages", "(queue_name: str)"),
        ("POST", "/api/sqs/queues/{queue_name}/messages", "api_sqs_send_message", "(queue_name: str, request: Request)", "model", "req", "SQSMessageSendRequest"),
        ("POST", "/api/sqs/queues/{queue_name}/receive", "api_sqs_receive_message", "(queue_name: str, request: Request)", "model", "req", "SQSReceiveRequest"),
        ("DELETE", "/api/sqs/queues/{queue_name}/messages/{receipt_handle}", "api_sqs_delete_message", "(queue_name: str, receipt_handle: str)"),
        ("POST", "/api/sqs/queues/{queue_name}/messages/{receipt_handle}/visibility", "api_sqs_change_visibility", "(queue_name: str, receipt_handle: str, request: Request)", "model", "req", "SQSVisibilityRequest"),
        ("POST", "/api/sqs/queues/{queue_name}/purge", "api_sqs_purge", "(queue_name: str)"),
        ("GET", "/api/sqs/queues/{queue_name}/tags", "api_sqs_list_tags", "(queue_name: str)"),
        ("POST", "/api/sqs/queues/{queue_name}/tags", "api_sqs_tag_queue", "(queue_name: str, request: Request)", "json", "payload"),
        ("DELETE", "/api/sqs/queues/{queue_name}/tags", "api_sqs_untag_queue", "(queue_name: str, request: Request)", "json", "payload"),
        # DynamoDB
        ("GET", "/api/dynamodb/tables", "api_dynamodb_list_tables", "()"),
        ("POST", "/api/dynamodb/tables", "api_dynamodb_create_table", "(request: Request)", "model", "req", "DynamoDBTableRequest"),
        ("GET", "/api/dynamodb/tables/{table_name}", "api_dynamodb_get_table", "(table_name: str)"),
        ("DELETE", "/api/dynamodb/tables/{table_name}", "api_dynamodb_delete_table", "(table_name: str)"),
        ("GET", "/api/dynamodb/tables/{table_name}/items", "api_dynamodb_list_items", "(table_name: str)"),
        ("POST", "/api/dynamodb/tables/{table_name}/items", "api_dynamodb_put_item", "(table_name: str, request: Request)", "model", "req", "DynamoDBItemRequest"),
        ("PUT", "/api/dynamodb/tables/{table_name}/items", "api_dynamodb_update_item", "(table_name: str, request: Request)", "model", "req", "DynamoDBItemRequest"),
        ("DELETE", "/api/dynamodb/tables/{table_name}/items", "api_dynamodb_delete_item", "(table_name: str, request: Request)", "model", "req", "DynamoDBItemRequest"),
        ("POST", "/api/dynamodb/tables/{table_name}/query", "api_dynamodb_query_items", "(table_name: str, request: Request)", "model", "req", "DynamoDBQueryRequest"),
        ("POST", "/api/dynamodb/tables/{table_name}/scan", "api_dynamodb_scan_items", "(table_name: str, request: Request)", "model", "req", "DynamoDBScanRequest"),
        ("GET", "/api/dynamodb/tables/{table_name}/tags", "api_dynamodb_list_tags", "(table_name: str)"),
        ("POST", "/api/dynamodb/tables/{table_name}/tags", "api_dynamodb_tag_table", "(table_name: str, request: Request)", "model", "req", "DynamoDBTagRequest"),
        ("DELETE", "/api/dynamodb/tables/{table_name}/tags", "api_dynamodb_untag_table", "(table_name: str, request: Request)", "json", "payload"),
        # API Gateway
        ("GET", "/api/apigateway/apis", "api_apigateway_list_apis", "()"),
        ("POST", "/api/apigateway/apis", "api_apigateway_create_api", "(request: Request)", "model", "req", "APIGatewayRequest"),
        ("GET", "/api/apigateway/apis/{api_id}", "api_apigateway_get_api", "(api_id: str)"),
        ("DELETE", "/api/apigateway/apis/{api_id}", "api_apigateway_delete_api", "(api_id: str)"),
        ("GET", "/api/apigateway/apis/{api_id}/resources", "api_apigateway_list_resources", "(api_id: str)"),
        ("POST", "/api/apigateway/apis/{api_id}/resources", "api_apigateway_create_resource", "(api_id: str, request: Request)", "model", "req", "APIGatewayResourceRequest"),
        ("POST", "/api/apigateway/apis/{api_id}/methods", "api_apigateway_put_method", "(api_id: str, request: Request)", "model", "req", "APIGatewayMethodRequest"),
        ("POST", "/api/apigateway/apis/{api_id}/integrations", "api_apigateway_put_integration", "(api_id: str, request: Request)", "model", "req", "APIGatewayIntegrationRequest"),
        ("POST", "/api/apigateway/apis/{api_id}/deployments", "api_apigateway_create_deployment", "(api_id: str, request: Request)", "model", "req", "APIGatewayDeploymentRequest"),
        ("GET", "/api/apigateway/apis/{api_id}/deployments", "api_apigateway_list_deployments", "(api_id: str)"),
        ("POST", "/api/apigateway/apis/{api_id}/stages", "api_apigateway_create_stage", "(api_id: str, request: Request)", "model", "req", "APIGatewayStageRequest"),
        ("GET", "/api/apigateway/apis/{api_id}/stages", "api_apigateway_list_stages", "(api_id: str)"),
        ("GET", "/api/apigateway/apis/{api_id}/logs", "api_apigateway_list_logs", "(api_id: str)"),
        ("GET", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("POST", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("PUT", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("PATCH", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("DELETE", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("OPTIONS", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("HEAD", "/api/apigateway/invoke/{api_id}/{stage_name}/{proxy_path:path}", "api_apigateway_invoke_path", "(api_id: str, stage_name: str, proxy_path: str, request: Request)"),
        ("GET", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        ("POST", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        ("PUT", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        ("PATCH", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        ("DELETE", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        ("OPTIONS", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        ("HEAD", "/api/apigateway/invoke/{api_id}/{stage_name}", "api_apigateway_invoke_root", "(api_id: str, stage_name: str, request: Request)"),
        # Lambda
        ("GET", "/api/lambda/functions", "api_lambda_list_functions", "()"),
        ("POST", "/api/lambda/functions", "api_lambda_create_function", "(request: Request)", "model", "req", "LambdaFunctionRequest"),
        ("GET", "/api/lambda/functions/{function_name}", "api_lambda_get_function", "(function_name: str)"),
        ("PUT", "/api/lambda/functions/{function_name}/code", "api_lambda_update_function_code", "(function_name: str, request: Request)", "json", "payload"),
        ("PUT", "/api/lambda/functions/{function_name}/configuration", "api_lambda_update_function_configuration", "(function_name: str, request: Request)", "model", "req", "LambdaFunctionUpdateRequest"),
        ("DELETE", "/api/lambda/functions/{function_name}", "api_lambda_delete_function", "(function_name: str)"),
        ("GET", "/api/lambda/functions/{function_name}/policy", "api_lambda_get_policy", "(function_name: str)"),
        ("POST", "/api/lambda/functions/{function_name}/policy", "api_lambda_add_permission", "(function_name: str, request: Request)", "model", "req", "LambdaPermissionRequest"),
        ("DELETE", "/api/lambda/functions/{function_name}/policy/{statement_id}", "api_lambda_remove_permission", "(function_name: str, statement_id: str)"),
        ("GET", "/api/lambda/functions/{function_name}/invocations", "api_lambda_list_invocations", "(function_name: str)"),
        ("GET", "/api/lambda/functions/{function_name}/versions", "api_lambda_list_versions", "(function_name: str)"),
        ("POST", "/api/lambda/functions/{function_name}/versions", "api_lambda_publish_version", "(function_name: str, request: Request)", "model", "req", "LambdaVersionRequest"),
        ("POST", "/api/lambda/functions/{function_name}/invoke", "api_lambda_invoke_function", "(function_name: str, request: Request)", "model", "req", "LambdaInvokeRequest"),
        # Lambda Layers
        ("GET", "/api/lambda/layers", "api_lambda_list_layers", "()"),
        ("POST", "/api/lambda/layers", "api_lambda_create_layer", "(request: Request)", "model", "req", "LambdaLayerRequest"),
        ("GET", "/api/lambda/layers/{name}", "api_lambda_get_layer", "(name: str)"),
        ("DELETE", "/api/lambda/layers/{name}", "api_lambda_delete_layer", "(name: str)"),
        ("GET", "/2015-03-31/functions", "api_lambda_list_functions_aws", "()"),
        ("POST", "/2015-03-31/functions", "api_lambda_create_function_aws", "(request: Request)", "model", "req", "LambdaFunctionRequest"),
        ("GET", "/2015-03-31/functions/{function_name}", "api_lambda_get_function_aws", "(function_name: str)"),
        ("DELETE", "/2015-03-31/functions/{function_name}", "api_lambda_delete_function_aws", "(function_name: str)"),
        ("GET", "/2015-03-31/functions/{function_name}/policy", "api_lambda_get_policy_aws", "(function_name: str)"),
        ("POST", "/2015-03-31/functions/{function_name}/policy", "api_lambda_add_permission_aws", "(function_name: str, request: Request)", "model", "req", "LambdaPermissionRequest"),
        ("DELETE", "/2015-03-31/functions/{function_name}/policy/{statement_id}", "api_lambda_remove_permission_aws", "(function_name: str, statement_id: str)"),
        ("PUT", "/2015-03-31/functions/{function_name}/code", "api_lambda_update_function_code_aws", "(function_name: str, request: Request)", "json", "payload"),
        ("PUT", "/2015-03-31/functions/{function_name}/configuration", "api_lambda_update_function_configuration_aws", "(function_name: str, request: Request)", "model", "req", "LambdaFunctionUpdateRequest"),
        ("POST", "/2015-03-31/functions/{function_name}/versions", "api_lambda_publish_version_aws", "(function_name: str, request: Request)", "model", "req", "LambdaVersionRequest"),
        ("GET", "/2015-03-31/functions/{function_name}/versions", "api_lambda_list_versions_aws", "(function_name: str)"),
        ("POST", "/2015-03-31/functions/{function_name}/invocations", "api_lambda_invoke_function_aws", "(function_name: str, request: Request)"),
    ]

    for spec in specs:
        method, path, target_name, signature, *rest = spec
        include_in_schema = True
        body_mode = "none"
        body_target = "request"
        model_name = ""
        rest = list(rest)
        if rest and isinstance(rest[-1], bool):
            include_in_schema = rest.pop()
        if rest:
            body_mode = rest[0]
            rest = rest[1:]
        if rest:
            body_target = rest[0]
            rest = rest[1:]
        if rest:
            model_name = rest[0]
        _add_route(
            app,
            method,
            path,
            target_name,
            signature,
            include_in_schema=include_in_schema,
            body_mode=body_mode,
            body_target=body_target,
            model_name=model_name,
        )
