from __future__ import annotations

import inspect
from typing import Any

from fastapi import Request

from .gcp import tool_response as gcp_tool_response
from . import gcp_iam
from . import gcp_services, gcp_storage_sql_vpc
from core.tooling_simulators import gcp_gcutil_resolve, gcp_gcloud_resolve, sdk_snippet
from core import models as _models
from core.app_context import gcp_functions_state, gcp_sql_state


_TARGET_OVERRIDES = {
    "api_gcp_iam_get_policy": gcp_iam.api_gcp_iam_get_policy,
    "api_gcp_iam_set_policy": gcp_iam.api_gcp_iam_set_policy,
    "api_gcp_iam_test_permissions": gcp_iam.api_gcp_iam_test_permissions,
    "api_gcp_iam_list_service_accounts": gcp_iam.api_gcp_iam_list_service_accounts,
    "api_gcp_iam_create_service_account": gcp_iam.api_gcp_iam_create_service_account,
    "api_gcp_iam_get_service_account": gcp_iam.api_gcp_iam_get_service_account,
    "api_gcp_iam_patch_service_account": gcp_iam.api_gcp_iam_patch_service_account,
    "api_gcp_iam_delete_service_account": gcp_iam.api_gcp_iam_delete_service_account,
    "api_gcp_iam_create_service_account_key": gcp_iam.api_gcp_iam_create_service_account_key,
    "api_gcp_iam_list_service_account_keys": gcp_iam.api_gcp_iam_list_service_account_keys,
    "api_gcp_iam_get_service_account_key": gcp_iam.api_gcp_iam_get_service_account_key,
    "api_gcp_iam_delete_service_account_key": gcp_iam.api_gcp_iam_delete_service_account_key,
    "api_gcp_iam_list_users": gcp_iam.api_gcp_iam_list_users,
    "api_gcp_iam_create_user": gcp_iam.api_gcp_iam_create_user,
    "api_gcp_iam_delete_user": gcp_iam.api_gcp_iam_delete_user,
    "api_gcp_iam_list_groups": gcp_iam.api_gcp_iam_list_groups,
    "api_gcp_iam_create_group": gcp_iam.api_gcp_iam_create_group,
    "api_gcp_iam_delete_group": gcp_iam.api_gcp_iam_delete_group,
    "api_gcp_iam_list_roles": gcp_iam.api_gcp_iam_list_roles,
    "api_gcp_iam_create_role": gcp_iam.api_gcp_iam_create_role,
    "api_gcp_iam_delete_role": gcp_iam.api_gcp_iam_delete_role,
    "api_gcp_iam_list_policies": gcp_iam.api_gcp_iam_list_policies,
    "api_gcp_iam_create_policy": gcp_iam.api_gcp_iam_create_policy,
    "api_gcp_iam_delete_policy": gcp_iam.api_gcp_iam_delete_policy,
    "api_gcp_iam_get_account_settings": gcp_iam.api_gcp_iam_get_account_settings,
    "api_gcp_iam_update_account_settings": gcp_iam.api_gcp_iam_update_account_settings,
    "api_gcp_iam_list_identity_providers": gcp_iam.api_gcp_iam_list_identity_providers,
    "api_gcp_iam_create_identity_provider": gcp_iam.api_gcp_iam_create_identity_provider,
    "api_gcp_iam_delete_identity_provider": gcp_iam.api_gcp_iam_delete_identity_provider,
    "api_gcp_storage_list_buckets": gcp_storage_sql_vpc.api_gcp_storage_list_buckets,
    "api_gcp_storage_create_bucket": gcp_storage_sql_vpc.api_gcp_storage_create_bucket,
    "api_gcp_storage_get_bucket": gcp_storage_sql_vpc.api_gcp_storage_get_bucket,
    "api_gcp_storage_delete_bucket": gcp_storage_sql_vpc.api_gcp_storage_delete_bucket,
    "api_gcp_storage_list_objects": gcp_storage_sql_vpc.api_gcp_storage_list_objects,
    "api_gcp_storage_create_object": gcp_storage_sql_vpc.api_gcp_storage_create_object,
    "api_gcp_storage_get_object": gcp_storage_sql_vpc.api_gcp_storage_get_object,
    "api_gcp_storage_delete_object": gcp_storage_sql_vpc.api_gcp_storage_delete_object,
    "api_gcp_storage_patch_object": gcp_storage_sql_vpc.api_gcp_storage_patch_object,
    "api_gcp_storage_compose_object": gcp_storage_sql_vpc.api_gcp_storage_compose_object,
    "api_gcp_storage_list_folders": gcp_storage_sql_vpc.api_gcp_storage_list_folders,
    "api_gcp_storage_create_folder": gcp_storage_sql_vpc.api_gcp_storage_create_folder,
    "api_gcp_storage_delete_folder": gcp_storage_sql_vpc.api_gcp_storage_delete_folder,
    "api_gcp_storage_list_transfers": gcp_storage_sql_vpc.api_gcp_storage_list_transfers,
    "api_gcp_storage_create_transfer": gcp_storage_sql_vpc.api_gcp_storage_create_transfer,
    "api_gcp_storage_delete_transfer": gcp_storage_sql_vpc.api_gcp_storage_delete_transfer,
    "api_gcp_storage_get_policy": gcp_storage_sql_vpc.api_gcp_storage_get_policy,
    "api_gcp_storage_set_policy": gcp_storage_sql_vpc.api_gcp_storage_set_policy,
    "api_gcp_sql_list_instances": gcp_storage_sql_vpc.api_gcp_sql_list_instances,
    "api_gcp_sql_create_instance": gcp_storage_sql_vpc.api_gcp_sql_create_instance,
    "api_gcp_sql_get_instance": gcp_storage_sql_vpc.api_gcp_sql_get_instance,
    "api_gcp_sql_delete_instance": gcp_storage_sql_vpc.api_gcp_sql_delete_instance,
    "api_gcp_sql_restart_instance": gcp_storage_sql_vpc.api_gcp_sql_restart_instance,
    "api_gcp_sql_start_instance": gcp_storage_sql_vpc.api_gcp_sql_start_instance,
    "api_gcp_sql_stop_instance": gcp_storage_sql_vpc.api_gcp_sql_stop_instance,
    "api_gcp_sql_list_backups": gcp_storage_sql_vpc.api_gcp_sql_list_backups,
    "api_gcp_sql_create_backup": gcp_storage_sql_vpc.api_gcp_sql_create_backup,
    "api_gcp_sql_delete_backup": gcp_storage_sql_vpc.api_gcp_sql_delete_backup,
    "api_gcp_sql_list_insights": gcp_storage_sql_vpc.api_gcp_sql_list_insights,
    "api_gcp_sql_create_insight": gcp_storage_sql_vpc.api_gcp_sql_create_insight,
    "api_gcp_vpc_list_networks": gcp_storage_sql_vpc.api_gcp_vpc_list_networks,
    "api_gcp_vpc_create_network": gcp_storage_sql_vpc.api_gcp_vpc_create_network,
    "api_gcp_vpc_get_network": gcp_storage_sql_vpc.api_gcp_vpc_get_network,
    "api_gcp_vpc_delete_network": gcp_storage_sql_vpc.api_gcp_vpc_delete_network,
    "api_gcp_vpc_patch_network": gcp_storage_sql_vpc.api_gcp_vpc_patch_network,
    "api_gcp_vpc_list_subnetworks": gcp_storage_sql_vpc.api_gcp_vpc_list_subnetworks,
    "api_gcp_vpc_create_subnetwork": gcp_storage_sql_vpc.api_gcp_vpc_create_subnetwork,
    "api_gcp_vpc_list_firewalls": gcp_storage_sql_vpc.api_gcp_vpc_list_firewalls,
    "api_gcp_vpc_create_firewall": gcp_storage_sql_vpc.api_gcp_vpc_create_firewall,
    "api_gcp_vpc_list_routes": gcp_storage_sql_vpc.api_gcp_vpc_list_routes,
    "api_gcp_vpc_create_route": gcp_storage_sql_vpc.api_gcp_vpc_create_route,
    "api_gcp_vpc_delete_route": gcp_storage_sql_vpc.api_gcp_vpc_delete_route,
}

for _name in gcp_services.TARGETS:
    _TARGET_OVERRIDES[_name] = getattr(gcp_services, _name)


def tool_response(tool: str) -> dict:
    return gcp_tool_response(tool)


def gcloud_resolve(payload: dict[str, Any]) -> dict:
    return gcp_gcloud_resolve(str(payload.get("command", "")))


def gcutil_resolve(payload: dict[str, Any]) -> dict:
    return gcp_gcutil_resolve(str(payload.get("command", "")))


def sdk_java_snippet() -> dict:
    return sdk_snippet("gcp", "java")


def sdk_go_snippet() -> dict:
    return sdk_snippet("gcp", "go")


def sdk_python_snippet() -> dict:
    return sdk_snippet("gcp", "python")


def sdk_nodejs_snippet() -> dict:
    return sdk_snippet("gcp", "nodejs")


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
    # Operation pollers (Cloud SQL + Cloud Functions) — return empty lists so the
    # console's background polling does not 404 (which surfaced a "Not Found" toast).
    @app.get("/sql/v1beta4/projects/{project}/operations")
    @app.get("/api/gcp/sql/v1beta4/projects/{project}/operations")
    def api_gcp_sql_list_operations(project: str):
        recs = gcp_sql_state.get("operation_records")
        ops = list(recs.values()) if isinstance(recs, dict) else []
        return {"kind": "sql#operationsList", "items": ops}

    @app.get("/sql/v1beta4/projects/{project}/operations/{operation}")
    @app.get("/api/gcp/sql/v1beta4/projects/{project}/operations/{operation}")
    def api_gcp_sql_get_operation(project: str, operation: str):
        # LRO poll target. Sim ops complete synchronously, so always report DONE.
        recs = gcp_sql_state.get("operation_records")
        op = recs.get(operation) if isinstance(recs, dict) else None
        if not op:
            op = {
                "kind": "sql#operation", "name": operation, "status": "DONE",
                "operationType": "CREATE", "targetProject": project,
                "selfLink": f"{_server()._gcp_sql_root()}/projects/{project}/operations/{operation}",
            }
        return op

    @app.get("/v1/projects/{project}/locations/{location}/operations")
    @app.get("/api/gcp/v1/projects/{project}/locations/{location}/operations")
    def api_gcp_functions_list_operations(project: str, location: str):
        return {"operations": []}

    @app.get("/v1/operations/{operation}")
    @app.get("/api/gcp/v1/operations/{operation}")
    def api_gcp_functions_get_operation(operation: str):
        # Cloud Functions LRO poll target (google.longrunning.Operation). Sim ops
        # complete synchronously → always report done.
        recs = gcp_functions_state.get("operation_records")
        op = recs.get(operation) if isinstance(recs, dict) else None
        if not op:
            op = {"name": f"operations/{operation}", "done": True}
        return op

    # API Gateway request routing: a call to a deployed gateway is routed to its
    # backend (a Cloud Function or upstream URL) and returns the real response.
    @app.api_route("/api/gcp/apigateway/invoke/{gateway}/{path:path}",
                   methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
    @app.api_route("/api/gcp/apigateway/invoke/{gateway}",
                   methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
    async def api_gcp_apigateway_invoke(gateway: str, request: Request, path: str = ""):
        return await _server().api_gcp_apigw_invoke(gateway, path, request)

    @app.get("/api/providers/gcp/gcloud")
    def api_provider_gcp_gcloud():
        return tool_response("gcloud")

    @app.get("/api/providers/gcp/gcutil")
    def api_provider_gcp_gcutil():
        return tool_response("gcutil")

    @app.get("/api/providers/gcp/sdk/java")
    def api_provider_gcp_sdk_java():
        return tool_response("sdk/java")

    @app.get("/api/providers/gcp/sdk/go")
    def api_provider_gcp_sdk_go():
        return tool_response("sdk/go")

    @app.get("/api/providers/gcp/sdk/python")
    def api_provider_gcp_sdk_python():
        return tool_response("sdk/python")

    @app.get("/api/providers/gcp/sdk/nodejs")
    def api_provider_gcp_sdk_nodejs():
        return tool_response("sdk/nodejs")

    @app.post("/api/providers/gcp/gcloud/resolve")
    def api_provider_gcp_gcloud_resolve(payload: dict[str, Any]):
        return gcloud_resolve(payload)

    @app.post("/api/providers/gcp/gcutil/resolve")
    def api_provider_gcp_gcutil_resolve(payload: dict[str, Any]):
        return gcutil_resolve(payload)

    @app.get("/api/providers/gcp/sdk/java/snippet")
    def api_provider_gcp_sdk_java_snippet():
        return sdk_java_snippet()

    @app.get("/api/providers/gcp/sdk/go/snippet")
    def api_provider_gcp_sdk_go_snippet():
        return sdk_go_snippet()

    @app.get("/api/providers/gcp/sdk/python/snippet")
    def api_provider_gcp_sdk_python_snippet():
        return sdk_python_snippet()

    @app.get("/api/providers/gcp/sdk/nodejs/snippet")
    def api_provider_gcp_sdk_nodejs_snippet():
        return sdk_nodejs_snippet()

    specs = [
        # Storage
        ("GET", "/storage/v1/b", "api_gcp_storage_list_buckets", "(request: Request)"),
        ("GET", "/api/gcp/storage/v1/b", "api_gcp_storage_list_buckets", "(request: Request)"),
        ("GET", "/api/gcp/s3/buckets", "api_gcp_storage_list_buckets", "(request: Request)"),
        ("POST", "/storage/v1/b", "api_gcp_storage_create_bucket", "(request: Request)"),
        ("POST", "/api/gcp/storage/v1/b", "api_gcp_storage_create_bucket", "(request: Request)"),
        ("POST", "/api/gcp/s3/buckets", "api_gcp_storage_create_bucket", "(request: Request)"),
        ("GET", "/storage/v1/b/{bucket}", "api_gcp_storage_get_bucket", "(bucket: str)"),
        ("PATCH", "/storage/v1/b/{bucket}", "api_gcp_storage_patch_bucket", "(bucket: str, request: Request)"),
        ("PUT", "/storage/v1/b/{bucket}", "api_gcp_storage_patch_bucket", "(bucket: str, request: Request)"),
        ("PATCH", "/api/gcp/storage/v1/b/{bucket}", "api_gcp_storage_patch_bucket", "(bucket: str, request: Request)"),
        ("GET", "/api/gcp/storage/v1/b/{bucket}", "api_gcp_storage_get_bucket", "(bucket: str)"),
        ("GET", "/api/gcp/s3/buckets/{bucket}", "api_gcp_storage_get_bucket", "(bucket: str)"),
        ("DELETE", "/storage/v1/b/{bucket}", "api_gcp_storage_delete_bucket", "(bucket: str)"),
        ("DELETE", "/api/gcp/storage/v1/b/{bucket}", "api_gcp_storage_delete_bucket", "(bucket: str)"),
        ("DELETE", "/api/gcp/s3/buckets/{bucket}", "api_gcp_storage_delete_bucket", "(bucket: str)"),
        ("GET", "/storage/v1/b/{bucket}/o", "api_gcp_storage_list_objects", "(bucket: str, request: Request)"),
        ("GET", "/api/gcp/storage/v1/b/{bucket}/o", "api_gcp_storage_list_objects", "(bucket: str, request: Request)"),
        ("GET", "/api/gcp/s3/buckets/{bucket}/objects", "api_gcp_storage_list_objects", "(bucket: str, request: Request)"),
        ("POST", "/storage/v1/b/{bucket}/o", "api_gcp_storage_create_object", "(bucket: str, request: Request)"),
        ("POST", "/upload/storage/v1/b/{bucket}/o", "api_gcp_storage_create_object", "(bucket: str, request: Request)"),
        ("POST", "/api/gcp/storage/v1/b/{bucket}/o", "api_gcp_storage_create_object", "(bucket: str, request: Request)"),
        ("POST", "/api/gcp/s3/buckets/{bucket}/objects", "api_gcp_storage_create_object", "(bucket: str, request: Request)"),
        ("GET", "/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_get_object", "(bucket: str, object_name: str, request: Request)"),
        ("GET", "/download/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_get_object", "(bucket: str, object_name: str, request: Request)"),
        ("GET", "/api/gcp/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_get_object", "(bucket: str, object_name: str, request: Request)"),
        ("GET", "/api/gcp/s3/buckets/{bucket}/objects/{object_name:path}", "api_gcp_storage_get_object", "(bucket: str, object_name: str, request: Request)"),
        ("DELETE", "/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_delete_object", "(bucket: str, object_name: str)"),
        ("DELETE", "/api/gcp/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_delete_object", "(bucket: str, object_name: str)"),
        ("DELETE", "/api/gcp/s3/buckets/{bucket}/objects/{object_name:path}", "api_gcp_storage_delete_object", "(bucket: str, object_name: str)"),
        ("PATCH", "/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_patch_object", "(bucket: str, object_name: str, request: Request)"),
        ("PATCH", "/api/gcp/storage/v1/b/{bucket}/o/{object_name:path}", "api_gcp_storage_patch_object", "(bucket: str, object_name: str, request: Request)"),
        ("POST", "/storage/v1/b/{bucket}/o/{destination:path}/compose", "api_gcp_storage_compose_object", "(bucket: str, destination: str, request: Request)"),
        ("POST", "/api/gcp/storage/v1/b/{bucket}/o/{destination:path}/compose", "api_gcp_storage_compose_object", "(bucket: str, destination: str, request: Request)"),
        ("GET", "/storage/v1/b/{bucket}/folders", "api_gcp_storage_list_folders", "(bucket: str)"),
        ("GET", "/api/gcp/storage/v1/b/{bucket}/folders", "api_gcp_storage_list_folders", "(bucket: str)"),
        ("POST", "/storage/v1/b/{bucket}/folders", "api_gcp_storage_create_folder", "(bucket: str, request: Request)"),
        ("POST", "/api/gcp/storage/v1/b/{bucket}/folders", "api_gcp_storage_create_folder", "(bucket: str, request: Request)"),
        ("DELETE", "/storage/v1/b/{bucket}/folders/{folder}", "api_gcp_storage_delete_folder", "(bucket: str, folder: str)"),
        ("DELETE", "/api/gcp/storage/v1/b/{bucket}/folders/{folder}", "api_gcp_storage_delete_folder", "(bucket: str, folder: str)"),
        ("GET", "/storage/v1/transferJobs", "api_gcp_storage_list_transfers", "(project: str)"),
        ("GET", "/api/gcp/storage/v1/transferJobs", "api_gcp_storage_list_transfers", "(project: str)"),
        ("POST", "/storage/v1/transferJobs", "api_gcp_storage_create_transfer", "(project: str, request: Request)"),
        ("POST", "/api/gcp/storage/v1/transferJobs", "api_gcp_storage_create_transfer", "(project: str, request: Request)"),
        ("DELETE", "/storage/v1/transferJobs/{transfer_name}", "api_gcp_storage_delete_transfer", "(project: str, transfer_name: str)"),
        ("DELETE", "/api/gcp/storage/v1/transferJobs/{transfer_name}", "api_gcp_storage_delete_transfer", "(project: str, transfer_name: str)"),
        ("GET", "/storage/v1/b/{bucket}/iam", "api_gcp_storage_get_policy", "(bucket: str)"),
        ("GET", "/api/gcp/storage/v1/b/{bucket}/iam", "api_gcp_storage_get_policy", "(bucket: str)"),
        ("POST", "/storage/v1/b/{bucket}/iam", "api_gcp_storage_set_policy", "(bucket: str, request: Request)"),
        ("POST", "/api/gcp/storage/v1/b/{bucket}/iam", "api_gcp_storage_set_policy", "(bucket: str, request: Request)"),
        # SQL / RDS aliases
        ("GET", "/sql/v1beta4/projects/{project}/instances", "api_gcp_sql_list_instances", "(project: str, request: Request)"),
        # AWS-style /api/gcp/rds path defaults project to "cloudlearn" so
        # console + conformance harness can hit it without threading the
        # query param. The /sql/v1beta4 path keeps project mandatory
        # since real google-cloud-sdk clients always supply it.
        ("GET", "/api/gcp/rds/databases", "api_gcp_sql_list_instances", "(request: Request, project: str = 'cloudlearn')"),
        ("POST", "/sql/v1beta4/projects/{project}/instances", "api_gcp_sql_create_instance", "(project: str, request: Request)"),
        ("POST", "/api/gcp/rds/databases", "api_gcp_sql_create_instance", "(request: Request, project: str = 'cloudlearn')"),
        ("GET", "/sql/v1beta4/projects/{project}/instances/{instance}", "api_gcp_sql_get_instance", "(project: str, instance: str)"),
        ("PATCH", "/sql/v1beta4/projects/{project}/instances/{instance}", "api_gcp_sql_patch_instance", "(project: str, instance: str, request: Request)"),
        ("PUT", "/sql/v1beta4/projects/{project}/instances/{instance}", "api_gcp_sql_patch_instance", "(project: str, instance: str, request: Request)"),
        ("PATCH", "/api/gcp/sql/v1beta4/projects/{project}/instances/{instance}", "api_gcp_sql_patch_instance", "(project: str, instance: str, request: Request)"),
        # AWS-style /api/gcp/rds path defaults project for console + harness.
        ("GET", "/api/gcp/rds/databases/{instance}", "api_gcp_sql_get_instance", "(instance: str, project: str = 'cloudlearn')"),
        ("DELETE", "/sql/v1beta4/projects/{project}/instances/{instance}", "api_gcp_sql_delete_instance", "(project: str, instance: str)"),
        ("DELETE", "/api/gcp/rds/databases/{instance}", "api_gcp_sql_delete_instance", "(instance: str, project: str = 'cloudlearn')"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/restart", "api_gcp_sql_restart_instance", "(project: str, instance: str)"),
        ("GET", "/sql/v1beta4/projects/{project}/instances/{instance}/users", "api_gcp_sql_list_users", "(project: str, instance: str)"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/users", "api_gcp_sql_create_user", "(project: str, instance: str, request: Request)"),
        ("PUT", "/sql/v1beta4/projects/{project}/instances/{instance}/users", "api_gcp_sql_create_user", "(project: str, instance: str, request: Request)"),
        ("DELETE", "/sql/v1beta4/projects/{project}/instances/{instance}/users", "api_gcp_sql_delete_user", "(project: str, instance: str, name: str = \"\", host: str = \"\")"),
        ("GET", "/sql/v1beta4/projects/{project}/instances/{instance}/databases", "api_gcp_sql_list_databases", "(project: str, instance: str)"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/databases", "api_gcp_sql_create_database", "(project: str, instance: str, request: Request)"),
        ("GET", "/sql/v1beta4/projects/{project}/instances/{instance}/databases/{database}", "api_gcp_sql_get_database", "(project: str, instance: str, database: str)"),
        ("DELETE", "/sql/v1beta4/projects/{project}/instances/{instance}/databases/{database}", "api_gcp_sql_delete_database", "(project: str, instance: str, database: str)"),
        ("POST", "/api/gcp/rds/databases/{instance}/reboot", "api_gcp_sql_restart_instance", "(instance: str, project: str = 'cloudlearn')"),
        # /start and /stop — catalog publishes these; Cloud SQL implements them as activationPolicy flips.
        ("POST", "/api/gcp/rds/databases/{instance}/start", "api_gcp_sql_start_instance", "(project: str = \"cloudlearn\", instance: str = \"\")"),
        ("POST", "/api/gcp/rds/databases/{instance}/stop", "api_gcp_sql_stop_instance", "(project: str = \"cloudlearn\", instance: str = \"\")"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/start", "api_gcp_sql_start_instance", "(project: str, instance: str)"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/stop", "api_gcp_sql_stop_instance", "(project: str, instance: str)"),
        ("GET", "/sql/v1beta4/projects/{project}/instances/{instance}/backups", "api_gcp_sql_list_backups", "(project: str, instance: str = \"\")"),
        ("GET", "/api/gcp/rds/databases/{instance}/backups", "api_gcp_sql_list_backups", "(instance: str, project: str = 'cloudlearn')"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/backups", "api_gcp_sql_create_backup", "(project: str, instance: str, request: Request)"),
        ("POST", "/api/gcp/rds/databases/{instance}/backups", "api_gcp_sql_create_backup", "(project: str, instance: str, request: Request)"),
        ("DELETE", "/sql/v1beta4/projects/{project}/instances/{instance}/backups/{backup}", "api_gcp_sql_delete_backup", "(project: str, backup: str)"),
        ("DELETE", "/api/gcp/rds/databases/{instance}/backups/{backup}", "api_gcp_sql_delete_backup", "(project: str, backup: str)"),
        ("GET", "/sql/v1beta4/projects/{project}/instances/{instance}/queryInsights", "api_gcp_sql_list_insights", "(project: str, instance: str = \"\")"),
        ("GET", "/api/gcp/rds/databases/{instance}/queryInsights", "api_gcp_sql_list_insights", "(project: str, instance: str = \"\")"),
        ("POST", "/sql/v1beta4/projects/{project}/instances/{instance}/queryInsights", "api_gcp_sql_create_insight", "(project: str, instance: str, request: Request)"),
        ("POST", "/api/gcp/rds/databases/{instance}/queryInsights", "api_gcp_sql_create_insight", "(project: str, instance: str, request: Request)"),
        # Pub/Sub
        ("GET", "/v1/projects/{project}/topics", "api_gcp_pubsub_list_topics", "(project: str)"),
        ("GET", "/api/gcp/sqs/queues", "api_gcp_pubsub_list_topics", "(project: str)"),
        # Canonical /api/gcp/pubsub/v1 aliases — match the console catalog
        # so SDK / REST / console land on the same handlers (session-5 T3).
        ("GET", "/api/gcp/pubsub/v1/projects/{project}/topics", "api_gcp_pubsub_list_topics", "(project: str)"),
        ("POST", "/api/gcp/pubsub/v1/projects/{project}/topics", "api_gcp_pubsub_create_topic", "(project: str, request: Request)"),
        ("GET", "/api/gcp/pubsub/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_get_topic", "(project: str, topic: str)"),
        ("DELETE", "/api/gcp/pubsub/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_delete_topic", "(project: str, topic: str)"),
        ("POST", "/api/gcp/pubsub/v1/projects/{project}/topics/{topic}:publish", "api_gcp_pubsub_publish", "(project: str, topic: str, request: Request)"),
        ("GET", "/api/gcp/pubsub/v1/projects/{project}/subscriptions", "api_gcp_pubsub_list_subscriptions", "(project: str)"),
        ("POST", "/v1/projects/{project}/topics", "api_gcp_pubsub_create_topic", "(project: str, request: Request)"),
        ("PUT", "/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_put_topic", "(project: str, topic: str, request: Request)"),
        ("PUT", "/api/gcp/pubsub/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_put_topic", "(project: str, topic: str, request: Request)"),
        ("PUT", "/v1/projects/{project}/subscriptions/{subscription}", "api_gcp_pubsub_put_subscription", "(project: str, subscription: str, request: Request)"),
        ("PUT", "/api/gcp/pubsub/v1/projects/{project}/subscriptions/{subscription}", "api_gcp_pubsub_put_subscription", "(project: str, subscription: str, request: Request)"),
        ("PATCH", "/v1/projects/{project}/subscriptions/{subscription}", "api_gcp_pubsub_patch_subscription", "(project: str, subscription: str, request: Request)"),
        ("PATCH", "/api/gcp/pubsub/v1/projects/{project}/subscriptions/{subscription}", "api_gcp_pubsub_patch_subscription", "(project: str, subscription: str, request: Request)"),
        ("POST", "/api/gcp/sqs/queues", "api_gcp_pubsub_create_topic", "(project: str, request: Request)"),
        ("GET", "/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_get_topic", "(project: str, topic: str)"),
        ("GET", "/api/gcp/sqs/queues/{topic}", "api_gcp_pubsub_get_topic", "(project: str, topic: str)"),
        ("PATCH", "/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_update_topic", "(project: str, topic: str, request: Request)"),
        ("PATCH", "/api/gcp/sqs/queues/{topic}", "api_gcp_pubsub_update_topic", "(project: str, topic: str, request: Request)"),
        ("GET", "/v1/projects/{project}/topics/{topic}/messages", "api_gcp_pubsub_list_topic_messages", "(project: str, topic: str)"),
        ("DELETE", "/v1/projects/{project}/topics/{topic}", "api_gcp_pubsub_delete_topic", "(project: str, topic: str)"),
        ("DELETE", "/api/gcp/sqs/queues/{topic}", "api_gcp_pubsub_delete_topic", "(project: str, topic: str)"),
        ("POST", "/v1/projects/{project}/topics/{topic}:publish", "api_gcp_pubsub_publish", "(project: str, topic: str, request: Request)"),
        ("POST", "/api/gcp/sqs/queues/{topic}/messages", "api_gcp_pubsub_publish", "(project: str, topic: str, request: Request)"),
        ("GET", "/v1/projects/{project}/subscriptions", "api_gcp_pubsub_list_subscriptions", "(project: str)"),
        ("GET", "/api/gcp/sqs/queues", "api_gcp_pubsub_list_subscriptions", "(project: str)"),
        ("POST", "/v1/projects/{project}/subscriptions", "api_gcp_pubsub_create_subscription", "(project: str, request: Request, queue_name: str = \"\")"),
        ("POST", "/api/gcp/sqs/queues/{queue_name}", "api_gcp_pubsub_create_subscription", "(project: str, request: Request, queue_name: str = \"\")"),
        ("GET", "/v1/projects/{project}/subscriptions/{subscription}", "api_gcp_pubsub_get_subscription", "(project: str, subscription: str)"),
        ("GET", "/api/gcp/sqs/queues/{subscription}", "api_gcp_pubsub_get_subscription", "(project: str, subscription: str)"),
        ("GET", "/v1/projects/{project}/subscriptions/{subscription}/messages", "api_gcp_pubsub_list_subscription_messages", "(project: str, subscription: str)"),
        ("POST", "/v1/projects/{project}/subscriptions/{subscription}:purge", "api_gcp_pubsub_purge_subscription", "(project: str, subscription: str)"),
        ("DELETE", "/v1/projects/{project}/subscriptions/{subscription}", "api_gcp_pubsub_delete_subscription", "(project: str, subscription: str)"),
        ("DELETE", "/api/gcp/sqs/queues/{subscription}", "api_gcp_pubsub_delete_subscription", "(project: str, subscription: str)"),
        ("POST", "/v1/projects/{project}/subscriptions/{subscription}:pull", "api_gcp_pubsub_pull", "(project: str, subscription: str, request: Request)"),
        ("POST", "/api/gcp/sqs/queues/{subscription}/receive", "api_gcp_pubsub_pull", "(project: str, subscription: str, request: Request)"),
        ("POST", "/v1/projects/{project}/subscriptions/{subscription}:acknowledge", "api_gcp_pubsub_ack", "(project: str, subscription: str, request: Request, receipt_handle: str = \"\")"),
        ("POST", "/api/gcp/sqs/queues/{subscription}/messages/{receipt_handle}/delete", "api_gcp_pubsub_ack", "(project: str, subscription: str, request: Request, receipt_handle: str = \"\")"),
        ("POST", "/v1/projects/{project}/subscriptions/{subscription}:modifyAckDeadline", "api_gcp_pubsub_modify_ack_deadline", "(project: str, subscription: str, request: Request)"),
        ("GET", "/v1/projects/{project}/topics/{topic}/subscriptions", "api_gcp_pubsub_list_topic_subscriptions", "(project: str, topic: str)"),
        ("GET", "/v1/projects/{project}/schemas", "api_gcp_pubsub_list_schemas", "(project: str)"),
        ("GET", "/api/gcp/pubsub/schemas", "api_gcp_pubsub_list_schemas", "(project: str)"),
        ("POST", "/v1/projects/{project}/schemas", "api_gcp_pubsub_create_schema", "(project: str, request: Request)"),
        ("POST", "/api/gcp/pubsub/schemas", "api_gcp_pubsub_create_schema", "(project: str, request: Request)"),
        ("DELETE", "/v1/projects/{project}/schemas/{schema}", "api_gcp_pubsub_delete_schema", "(project: str, schema: str)"),
        ("DELETE", "/api/gcp/pubsub/schemas/{schema}", "api_gcp_pubsub_delete_schema", "(project: str, schema: str)"),
        # Firestore
        ("GET", "/firestore/v1/projects/{project}/databases/{database}/documents", "api_gcp_firestore_list_root_documents", "(project: str, database: str)"),
        ("GET", "/api/gcp/dynamodb/tables", "api_gcp_firestore_list_root_documents", "(project: str, database: str)"),
        # Native Firestore document API uses path-segment parity to distinguish a
        # collection (odd) from a document (even) — enables nested subcollections.
        ("GET", "/firestore/v1/projects/{project}/databases/{database}/documents/{fs_path:path}", "api_gcp_firestore_doc_get", "(project: str, database: str, fs_path: str)"),
        ("POST", "/firestore/v1/projects/{project}/databases/{database}/documents/{fs_path:path}", "api_gcp_firestore_doc_post", "(project: str, database: str, fs_path: str, request: Request)"),
        ("DELETE", "/firestore/v1/projects/{project}/databases/{database}/documents/{fs_path:path}", "api_gcp_firestore_doc_delete", "(project: str, database: str, fs_path: str)"),
        ("PUT", "/firestore/v1/projects/{project}/databases/{database}/documents/{fs_path:path}", "api_gcp_firestore_doc_put", "(project: str, database: str, fs_path: str, request: Request)"),
        ("PATCH", "/firestore/v1/projects/{project}/databases/{database}/documents/{fs_path:path}", "api_gcp_firestore_doc_put", "(project: str, database: str, fs_path: str, request: Request)"),
        # DynamoDB-style flat aliases (single collection, no nesting).
        ("GET", "/api/gcp/dynamodb/tables/{collection}/items", "api_gcp_firestore_list_documents", "(project: str, database: str, collection: str)"),
        ("POST", "/api/gcp/dynamodb/tables/{collection}/items", "api_gcp_firestore_create_document", "(project: str, database: str, collection: str, request: Request)"),
        ("GET", "/api/gcp/dynamodb/tables/{collection}/items/{doc_id}", "api_gcp_firestore_get_document", "(project: str, database: str, collection: str, doc_id: str)"),
        ("DELETE", "/api/gcp/dynamodb/tables/{collection}/items/{doc_id}", "api_gcp_firestore_delete_document", "(project: str, database: str, collection: str, doc_id: str)"),
        ("PUT", "/api/gcp/dynamodb/tables/{collection}/items/{doc_id}", "api_gcp_firestore_update_document", "(project: str, database: str, collection: str, doc_id: str, request: Request)"),
        ("POST", "/firestore/v1/projects/{project}/databases/{database}/documents:runQuery", "api_gcp_firestore_run_query", "(project: str, database: str, request: Request, collection: str = \"\")"),
        ("POST", "/api/gcp/dynamodb/tables/{collection}/query", "api_gcp_firestore_run_query", "(project: str, database: str, request: Request, collection: str = \"\")"),
        ("GET", "/firestore/v1/projects/{project}/databases/{database}/collectionGroups/{collection}/indexes", "api_gcp_firestore_list_indexes", "(project: str, database: str, collection: str = \"\")"),
        ("GET", "/api/gcp/firestore/indexes", "api_gcp_firestore_list_indexes", "(project: str, database: str, collection: str = \"\")"),
        ("POST", "/firestore/v1/projects/{project}/databases/{database}/collectionGroups/{collection}/indexes", "api_gcp_firestore_create_index", "(project: str, database: str, collection: str, request: Request)"),
        ("POST", "/api/gcp/firestore/indexes", "api_gcp_firestore_create_index", "(project: str, database: str, collection: str, request: Request)"),
        ("DELETE", "/firestore/v1/projects/{project}/databases/{database}/collectionGroups/{collection}/indexes/{index_name}", "api_gcp_firestore_delete_index", "(project: str, database: str, collection: str, index_name: str)"),
        ("DELETE", "/api/gcp/firestore/indexes/{index_name}", "api_gcp_firestore_delete_index", "(project: str, database: str, collection: str, index_name: str)"),
        # Functions
        ("GET", "/v1/projects/{project}/locations/{location}/functions", "api_gcp_functions_list", "(project: str, location: str = \"us-central1\")"),
        ("GET", "/api/gcp/lambda/functions", "api_gcp_functions_list", "(project: str, location: str = \"us-central1\")"),
        # Canonical /api/gcp/cloudfunctions/v2 aliases — what the console
        # catalog declares. Maps onto the v1 handlers (same record shape,
        # different URL prefix on the wire).
        ("GET", "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{location}/functions", "api_gcp_functions_list", "(project: str, location: str = \"us-central1\")"),
        ("POST", "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{location}/functions", "api_gcp_functions_create", "(project: str, request: Request, location: str = \"us-central1\")"),
        ("GET", "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_get", "(project: str, location: str, function: str)"),
        ("PATCH", "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_update", "(project: str, location: str, function: str, request: Request)"),
        ("DELETE", "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_delete", "(project: str, location: str, function: str)"),
        ("POST", "/api/gcp/cloudfunctions/v2/projects/{project}/locations/{location}/functions/{function}:call", "api_gcp_functions_call", "(project: str, location: str, function: str, request: Request)"),
        ("POST", "/v1/projects/{project}/locations/{location}/functions", "api_gcp_functions_create", "(project: str, request: Request, location: str = \"us-central1\")"),
        ("POST", "/api/gcp/lambda/functions", "api_gcp_functions_create", "(project: str, request: Request, location: str = \"us-central1\")"),
        ("PATCH", "/v1/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_update", "(project: str, location: str, function: str, request: Request)"),
        ("PATCH", "/api/gcp/lambda/functions/{function}/configuration", "api_gcp_functions_update", "(project: str, location: str, function: str, request: Request)"),
        ("PUT", "/api/gcp/lambda/functions/{function}/code", "api_gcp_functions_update", "(project: str, location: str, function: str, request: Request)"),
        ("GET", "/v1/projects/{project}/locations/{location}/functions/{function}:getIamPolicy", "api_gcp_functions_get_policy", "(project: str, location: str, function: str)"),
        ("POST", "/v1/projects/{project}/locations/{location}/functions/{function}:setIamPolicy", "api_gcp_functions_set_policy", "(project: str, location: str, function: str, request: Request)"),
        ("POST", "/v1/projects/{project}/locations/{location}/functions/{function}:call", "api_gcp_functions_call", "(project: str, location: str, function: str, request: Request)"),
        ("POST", "/v1/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_publish_version", "(project: str, location: str, function: str, request: Request)"),
        ("POST", "/api/gcp/lambda/functions/{function}/versions", "api_gcp_functions_publish_version", "(project: str, location: str, function: str, request: Request)"),
        ("GET", "/v1/projects/{project}/locations/{location}/functions/{function}/versions", "api_gcp_functions_list_versions", "(project: str, location: str, function: str)"),
        ("GET", "/api/gcp/lambda/functions/{function}/versions", "api_gcp_functions_list_versions", "(project: str, location: str, function: str)"),
        ("GET", "/v1/projects/{project}/locations/{location}/functions/{function}/invocations", "api_gcp_functions_list_invocations", "(project: str, location: str, function: str)"),
        ("GET", "/api/gcp/lambda/functions/{function}/invocations", "api_gcp_functions_list_invocations", "(project: str, location: str, function: str)"),
        ("GET", "/api/gcp/lambda/functions/{function}/policy", "api_gcp_functions_get_policy", "(project: str, location: str, function: str)"),
        ("POST", "/api/gcp/lambda/functions/{function}/policy", "api_gcp_functions_set_policy", "(project: str, location: str, function: str, request: Request)"),
        ("GET", "/v1/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_get", "(project: str, location: str, function: str)"),
        ("GET", "/api/gcp/lambda/functions/{function}", "api_gcp_functions_get", "(project: str, location: str, function: str)"),
        ("DELETE", "/v1/projects/{project}/locations/{location}/functions/{function}", "api_gcp_functions_delete", "(project: str, location: str, function: str)"),
        ("DELETE", "/api/gcp/lambda/functions/{function}", "api_gcp_functions_delete", "(project: str, location: str, function: str)"),
        ("POST", "/api/gcp/lambda/functions/{function}/invoke", "api_gcp_functions_call", "(project: str, location: str, function: str, request: Request)"),
        # API Gateway
        ("GET", "/v1/projects/{project}/locations/{location}/apis", "api_gcp_apigw_list_apis", "(project: str, location: str = \"global\")"),
        ("GET", "/api/gcp/apigateway/apis", "api_gcp_apigw_list_apis", "(project: str, location: str = \"global\")"),
        ("POST", "/v1/projects/{project}/locations/{location}/apis", "api_gcp_apigw_create_api", "(project: str, request: Request, location: str = \"global\")"),
        ("POST", "/api/gcp/apigateway/apis", "api_gcp_apigw_create_api", "(project: str, request: Request, location: str = \"global\")"),
        ("GET", "/v1/projects/{project}/locations/{location}/apis/{api}", "api_gcp_apigw_get_api", "(project: str, location: str, api: str)"),
        ("GET", "/api/gcp/apigateway/apis/{api}", "api_gcp_apigw_get_api", "(project: str, location: str, api: str)"),
        ("DELETE", "/v1/projects/{project}/locations/{location}/apis/{api}", "api_gcp_apigw_delete_api", "(project: str, location: str, api: str)"),
        ("DELETE", "/api/gcp/apigateway/apis/{api}", "api_gcp_apigw_delete_api", "(project: str, location: str, api: str)"),
        ("GET", "/v1/projects/{project}/locations/{location}/apiConfigs", "api_gcp_apigw_list_configs", "(project: str, location: str = \"global\", api: str = \"\")"),
        ("GET", "/api/gcp/apigateway/apis/{api}/resources", "api_gcp_apigw_list_configs", "(project: str, location: str = \"global\", api: str = \"\")"),
        ("POST", "/v1/projects/{project}/locations/{location}/apiConfigs", "api_gcp_apigw_create_config", "(project: str, request: Request, location: str = \"global\", api: str = \"\")"),
        ("POST", "/api/gcp/apigateway/apis/{api}/resources", "api_gcp_apigw_create_config", "(project: str, request: Request, location: str = \"global\", api: str = \"\")"),
        ("GET", "/v1/projects/{project}/locations/{location}/gateways", "api_gcp_apigw_list_gateways", "(project: str, location: str = \"global\", api: str = \"\")"),
        ("GET", "/api/gcp/apigateway/apis/{api}/deployments", "api_gcp_apigw_list_gateways", "(project: str, location: str = \"global\", api: str = \"\")"),
        ("POST", "/v1/projects/{project}/locations/{location}/gateways", "api_gcp_apigw_create_gateway", "(project: str, request: Request, location: str = \"global\", api: str = \"\")"),
        ("POST", "/api/gcp/apigateway/apis/{api}/stages", "api_gcp_apigw_create_gateway", "(project: str, request: Request, location: str = \"global\", api: str = \"\")"),
        # VPC
        ("GET", "/compute/v1/projects/{project}/global/networks", "api_gcp_vpc_list_networks", "(project: str)"),
        ("GET", "/api/gcp/vpc/networks", "api_gcp_vpc_list_networks", "(project: str)"),
        ("GET", "/api/gcp/vpc/vpcs", "api_gcp_vpc_list_networks", "(project: str)"),
        # Canonical /api/gcp/compute/v1 aliases — what the console catalog
        # declares (session-5 T3).
        ("GET", "/api/gcp/compute/v1/projects/{project}/global/networks", "api_gcp_vpc_list_networks", "(project: str)"),
        ("POST", "/api/gcp/compute/v1/projects/{project}/global/networks", "api_gcp_vpc_create_network", "(project: str, request: Request)"),
        ("GET", "/api/gcp/compute/v1/projects/{project}/global/networks/{network}", "api_gcp_vpc_get_network", "(project: str, network: str)"),
        ("DELETE", "/api/gcp/compute/v1/projects/{project}/global/networks/{network}", "api_gcp_vpc_delete_network", "(project: str, network: str)"),
        ("PATCH", "/api/gcp/compute/v1/projects/{project}/global/networks/{network}", "api_gcp_vpc_patch_network", "(project: str, network: str, request: Request)", "json", "payload"),
        ("PATCH", "/compute/v1/projects/{project}/global/networks/{network}", "api_gcp_vpc_patch_network", "(project: str, network: str, request: Request)", "json", "payload"),
        ("GET", "/api/gcp/compute/v1/projects/{project}/regions/{region}/subnetworks", "api_gcp_vpc_list_subnetworks", "(project: str, region: str)"),
        ("GET", "/api/gcp/compute/v1/projects/{project}/global/firewalls", "api_gcp_vpc_list_firewalls", "(project: str)"),
        ("POST", "/compute/v1/projects/{project}/global/networks", "api_gcp_vpc_create_network", "(project: str, request: Request)"),
        ("POST", "/api/gcp/vpc/networks", "api_gcp_vpc_create_network", "(project: str, request: Request)"),
        ("POST", "/api/gcp/vpc/vpcs", "api_gcp_vpc_create_network", "(project: str, request: Request)"),
        ("GET", "/compute/v1/projects/{project}/global/networks/{network}", "api_gcp_vpc_get_network", "(project: str, network: str)"),
        ("GET", "/api/gcp/vpc/networks/{network}", "api_gcp_vpc_get_network", "(project: str, network: str)"),
        ("GET", "/api/gcp/vpc/vpcs/{network}", "api_gcp_vpc_get_network", "(project: str, network: str)"),
        ("DELETE", "/compute/v1/projects/{project}/global/networks/{network}", "api_gcp_vpc_delete_network", "(project: str, network: str)"),
        ("DELETE", "/api/gcp/vpc/networks/{network}", "api_gcp_vpc_delete_network", "(project: str, network: str)"),
        ("DELETE", "/api/gcp/vpc/vpcs/{network}", "api_gcp_vpc_delete_network", "(project: str, network: str)"),
        ("GET", "/compute/v1/projects/{project}/regions/{region}/subnetworks", "api_gcp_vpc_list_subnetworks", "(project: str, region: str)"),
        ("GET", "/api/gcp/vpc/subnetworks", "api_gcp_vpc_list_subnetworks", "(project: str, region: str)"),
        ("GET", "/api/gcp/vpc/subnets", "api_gcp_vpc_list_subnetworks", "(project: str, region: str)"),
        ("POST", "/compute/v1/projects/{project}/regions/{region}/subnetworks", "api_gcp_vpc_create_subnetwork", "(project: str, region: str, request: Request)"),
        ("POST", "/api/gcp/vpc/subnetworks", "api_gcp_vpc_create_subnetwork", "(project: str, region: str, request: Request)"),
        ("POST", "/api/gcp/vpc/subnets", "api_gcp_vpc_create_subnetwork", "(project: str, region: str, request: Request)"),
        ("GET", "/compute/v1/projects/{project}/global/firewalls", "api_gcp_vpc_list_firewalls", "(project: str)"),
        ("GET", "/api/gcp/vpc/firewalls", "api_gcp_vpc_list_firewalls", "(project: str)"),
        ("GET", "/api/gcp/vpc/security-groups", "api_gcp_vpc_list_firewalls", "(project: str)"),
        ("POST", "/compute/v1/projects/{project}/global/firewalls", "api_gcp_vpc_create_firewall", "(project: str, request: Request)"),
        ("POST", "/api/gcp/vpc/firewalls", "api_gcp_vpc_create_firewall", "(project: str, request: Request)"),
        ("POST", "/api/gcp/vpc/security-groups", "api_gcp_vpc_create_firewall", "(project: str, request: Request)"),
        ("PATCH", "/compute/v1/projects/{project}/global/firewalls/{firewall}", "api_gcp_vpc_update_firewall", "(project: str, firewall: str, request: Request)"),
        ("PUT", "/compute/v1/projects/{project}/global/firewalls/{firewall}", "api_gcp_vpc_update_firewall", "(project: str, firewall: str, request: Request)"),
        ("PATCH", "/api/gcp/vpc/firewalls/{firewall}", "api_gcp_vpc_update_firewall", "(project: str, firewall: str, request: Request)"),
        ("DELETE", "/compute/v1/projects/{project}/global/firewalls/{firewall}", "api_gcp_vpc_delete_firewall", "(project: str, firewall: str)"),
        ("DELETE", "/api/gcp/vpc/firewalls/{firewall}", "api_gcp_vpc_delete_firewall", "(project: str, firewall: str)"),
        ("DELETE", "/api/gcp/vpc/security-groups/{firewall}", "api_gcp_vpc_delete_firewall", "(project: str, firewall: str)"),
        # Routes
        ("GET", "/compute/v1/projects/{project}/global/routes", "api_gcp_vpc_list_routes", "(project: str)"),
        ("GET", "/api/gcp/vpc/routes", "api_gcp_vpc_list_routes", "(project: str)"),
        ("POST", "/compute/v1/projects/{project}/global/routes", "api_gcp_vpc_create_route", "(project: str, request: Request)"),
        ("POST", "/api/gcp/vpc/routes", "api_gcp_vpc_create_route", "(project: str, request: Request)"),
        ("DELETE", "/compute/v1/projects/{project}/global/routes/{route}", "api_gcp_vpc_delete_route", "(project: str, route: str)"),
        ("DELETE", "/api/gcp/vpc/routes/{route}", "api_gcp_vpc_delete_route", "(project: str, route: str)"),
        # IAM
        ("GET", "/v1/projects/{project}:getIamPolicy", "api_gcp_iam_get_policy", "(project: str)"),
        ("POST", "/v1/projects/{project}:getIamPolicy", "api_gcp_iam_get_policy", "(project: str)"),
        ("GET", "/api/gcp/iam/policy", "api_gcp_iam_get_policy", "(project: str)"),
        ("POST", "/v1/projects/{project}:setIamPolicy", "api_gcp_iam_set_policy", "(project: str, request: Request)"),
        ("POST", "/api/gcp/iam/policy", "api_gcp_iam_set_policy", "(project: str, request: Request)"),
        ("POST", "/v1/projects/{project}:testIamPermissions", "api_gcp_iam_test_permissions", "(project: str, request: Request)"),
        ("POST", "/api/gcp/iam/test-permissions", "api_gcp_iam_test_permissions", "(project: str, request: Request)"),
        # Canonical /api/gcp/iam/v1 aliases — what the console catalog declares
        # (session-5 T3).
        ("GET", "/api/gcp/iam/v1/projects/{project}/serviceAccounts", "api_gcp_iam_list_service_accounts", "(project: str)"),
        ("POST", "/api/gcp/iam/v1/projects/{project}/serviceAccounts", "api_gcp_iam_create_service_account", "(project: str, request: Request)"),
        ("GET", "/api/gcp/iam/v1/projects/{project}/serviceAccounts/{account}", "api_gcp_iam_get_service_account", "(project: str, account: str)"),
        ("DELETE", "/api/gcp/iam/v1/projects/{project}/serviceAccounts/{account}", "api_gcp_iam_delete_service_account", "(project: str, account: str)"),
        ("GET", "/api/gcp/iam/v1/projects/{project}:getIamPolicy", "api_gcp_iam_get_policy", "(project: str)"),
        ("POST", "/api/gcp/iam/v1/projects/{project}:setIamPolicy", "api_gcp_iam_set_policy", "(project: str, request: Request)"),
        ("GET", "/v1/projects/{project}/serviceAccounts", "api_gcp_iam_list_service_accounts", "(project: str)"),
        ("GET", "/api/gcp/iam/service-accounts", "api_gcp_iam_list_service_accounts", "(project: str)"),
        ("POST", "/v1/projects/{project}/serviceAccounts", "api_gcp_iam_create_service_account", "(project: str, request: Request)"),
        ("POST", "/api/gcp/iam/service-accounts", "api_gcp_iam_create_service_account", "(project: str, request: Request)"),
        ("GET", "/v1/projects/{project}/serviceAccounts/{account}", "api_gcp_iam_get_service_account", "(project: str, account: str)"),
        ("GET", "/api/gcp/iam/service-accounts/{account}", "api_gcp_iam_get_service_account", "(project: str, account: str)"),
        ("PATCH", "/v1/projects/{project}/serviceAccounts/{account}", "api_gcp_iam_patch_service_account", "(project: str, account: str, request: Request)"),
        ("PUT", "/v1/projects/{project}/serviceAccounts/{account}", "api_gcp_iam_patch_service_account", "(project: str, account: str, request: Request)"),
        ("PATCH", "/api/gcp/iam/service-accounts/{account}", "api_gcp_iam_patch_service_account", "(project: str, account: str, request: Request)"),
        ("DELETE", "/v1/projects/{project}/serviceAccounts/{account}", "api_gcp_iam_delete_service_account", "(project: str, account: str)"),
        ("DELETE", "/api/gcp/iam/service-accounts/{account}", "api_gcp_iam_delete_service_account", "(project: str, account: str)"),
        ("POST", "/v1/projects/{project}/serviceAccounts/{account}/keys", "api_gcp_iam_create_service_account_key", "(project: str, account: str, request: Request)"),
        ("GET", "/v1/projects/{project}/serviceAccounts/{account}/keys", "api_gcp_iam_list_service_account_keys", "(project: str, account: str)"),
        ("GET", "/v1/projects/{project}/serviceAccounts/{account}/keys/{key}", "api_gcp_iam_get_service_account_key", "(project: str, account: str, key: str)"),
        ("DELETE", "/v1/projects/{project}/serviceAccounts/{account}/keys/{key}", "api_gcp_iam_delete_service_account_key", "(project: str, account: str, key: str)"),
        ("GET", "/api/gcp/iam/users", "api_gcp_iam_list_users", "()"),
        ("POST", "/api/gcp/iam/users", "api_gcp_iam_create_user", "(request: Request)"),
        ("DELETE", "/api/gcp/iam/users/{user_id}", "api_gcp_iam_delete_user", "(user_id: str)"),
        ("GET", "/api/gcp/iam/groups", "api_gcp_iam_list_groups", "()"),
        ("POST", "/api/gcp/iam/groups", "api_gcp_iam_create_group", "(request: Request)"),
        ("DELETE", "/api/gcp/iam/groups/{group_id}", "api_gcp_iam_delete_group", "(group_id: str)"),
        ("GET", "/api/gcp/iam/roles", "api_gcp_iam_list_roles", "()"),
        ("POST", "/api/gcp/iam/roles", "api_gcp_iam_create_role", "(request: Request)"),
        ("DELETE", "/api/gcp/iam/roles/{role_id}", "api_gcp_iam_delete_role", "(role_id: str)"),
        ("GET", "/api/gcp/iam/policies", "api_gcp_iam_list_policies", "()"),
        ("POST", "/api/gcp/iam/policies", "api_gcp_iam_create_policy", "(request: Request)"),
        ("DELETE", "/api/gcp/iam/policies/{policy_id}", "api_gcp_iam_delete_policy", "(policy_id: str)"),
        ("GET", "/api/gcp/iam/account-settings", "api_gcp_iam_get_account_settings", "()"),
        ("PUT", "/api/gcp/iam/account-settings", "api_gcp_iam_update_account_settings", "(request: Request)"),
        ("GET", "/api/gcp/iam/identity-providers", "api_gcp_iam_list_identity_providers", "()"),
        ("POST", "/api/gcp/iam/identity-providers", "api_gcp_iam_create_identity_provider", "(request: Request)"),
        ("DELETE", "/api/gcp/iam/identity-providers/{provider_id}", "api_gcp_iam_delete_identity_provider", "(provider_id: str)"),
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
