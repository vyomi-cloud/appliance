from __future__ import annotations

from fastapi import Request


def _server():
    import server as server_module

    return server_module


def register(app, h) -> None:
    @app.get("/compute/v1/projects/{project}/zones/{zone}/instances")
    @app.get("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances")
    def api_gcp_compute_list_instances(project: str, zone: str):
        return _server().api_gcp_compute_list_instances(project, zone)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances")
    async def api_gcp_compute_create_instance(project: str, zone: str, request: Request):
        return await _server().api_gcp_compute_create_instance(project, zone, request)

    @app.get("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}")
    @app.get("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}")
    def api_gcp_compute_get_instance(project: str, zone: str, instance: str):
        return _server().api_gcp_compute_get_instance(project, zone, instance)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start")
    def api_gcp_compute_start_instance(project: str, zone: str, instance: str):
        return _server().api_gcp_compute_start_instance(project, zone, instance)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop")
    def api_gcp_compute_stop_instance(project: str, zone: str, instance: str):
        return _server().api_gcp_compute_stop_instance(project, zone, instance)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/reset")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/reset")
    def api_gcp_compute_reset_instance(project: str, zone: str, instance: str):
        return _server().api_gcp_compute_reset_instance(project, zone, instance)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/setMetadata")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/setMetadata")
    async def api_gcp_compute_set_metadata(project: str, zone: str, instance: str, request: Request):
        return await _server().api_gcp_compute_set_metadata(project, zone, instance, request)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/setTags")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/setTags")
    async def api_gcp_compute_set_tags(project: str, zone: str, instance: str, request: Request):
        return await _server().api_gcp_compute_set_tags(project, zone, instance, request)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/setLabels")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/setLabels")
    async def api_gcp_compute_set_labels(project: str, zone: str, instance: str, request: Request):
        return await _server().api_gcp_compute_set_labels(project, zone, instance, request)

    @app.delete("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}")
    @app.delete("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}")
    @app.post("/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/delete")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instances/{instance}/delete")
    def api_gcp_compute_delete_instance(project: str, zone: str, instance: str):
        return _server().api_gcp_compute_delete_instance(project, zone, instance)

    @app.get("/compute/v1/projects/{project}/zones/{zone}/operations/{operation_id}")
    @app.get("/api/gcp/compute/v1/projects/{project}/zones/{zone}/operations/{operation_id}")
    def api_gcp_compute_get_operation(project: str, zone: str, operation_id: str):
        return _server().api_gcp_compute_get_operation(project, zone, operation_id)

    @app.get("/compute/v1/projects/{project}/zones/{zone}/instanceGroups")
    @app.get("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instanceGroups")
    def api_gcp_compute_list_instance_groups(project: str, zone: str):
        return _server().api_gcp_compute_list_instance_groups(project, zone)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/instanceGroups")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instanceGroups")
    async def api_gcp_compute_create_instance_group(project: str, zone: str, request: Request):
        return await _server().api_gcp_compute_create_instance_group(project, zone, request)

    @app.delete("/compute/v1/projects/{project}/zones/{zone}/instanceGroups/{group}")
    @app.delete("/api/gcp/compute/v1/projects/{project}/zones/{zone}/instanceGroups/{group}")
    def api_gcp_compute_delete_instance_group(project: str, zone: str, group: str):
        return _server().api_gcp_compute_delete_instance_group(project, zone, group)

    @app.get("/compute/v1/projects/{project}/zones/{zone}/disks")
    @app.get("/api/gcp/compute/v1/projects/{project}/zones/{zone}/disks")
    def api_gcp_compute_list_disks(project: str, zone: str):
        return _server().api_gcp_compute_list_disks(project, zone)

    @app.post("/compute/v1/projects/{project}/zones/{zone}/disks")
    @app.post("/api/gcp/compute/v1/projects/{project}/zones/{zone}/disks")
    async def api_gcp_compute_create_disk(project: str, zone: str, request: Request):
        return await _server().api_gcp_compute_create_disk(project, zone, request)

    @app.get("/compute/v1/projects/{project}/zones/{zone}/disks/{disk}")
    @app.get("/api/gcp/compute/v1/projects/{project}/zones/{zone}/disks/{disk}")
    def api_gcp_compute_get_disk(project: str, zone: str, disk: str):
        return _server().api_gcp_compute_get_disk(project, zone, disk)

    @app.delete("/compute/v1/projects/{project}/zones/{zone}/disks/{disk}")
    @app.delete("/api/gcp/compute/v1/projects/{project}/zones/{zone}/disks/{disk}")
    def api_gcp_compute_delete_disk(project: str, zone: str, disk: str):
        return _server().api_gcp_compute_delete_disk(project, zone, disk)

    @app.get("/compute/v1/projects/{project}/global/snapshots")
    @app.get("/api/gcp/compute/v1/projects/{project}/global/snapshots")
    def api_gcp_compute_list_snapshots(project: str):
        return _server().api_gcp_compute_list_snapshots(project)

    @app.post("/compute/v1/projects/{project}/global/snapshots")
    @app.post("/api/gcp/compute/v1/projects/{project}/global/snapshots")
    async def api_gcp_compute_create_snapshot(project: str, request: Request):
        return await _server().api_gcp_compute_create_snapshot(project, request)

    @app.get("/compute/v1/projects/{project}/global/snapshots/{snapshot}")
    @app.get("/api/gcp/compute/v1/projects/{project}/global/snapshots/{snapshot}")
    def api_gcp_compute_get_snapshot(project: str, snapshot: str):
        return _server().api_gcp_compute_get_snapshot(project, snapshot)

    @app.delete("/compute/v1/projects/{project}/global/snapshots/{snapshot}")
    @app.delete("/api/gcp/compute/v1/projects/{project}/global/snapshots/{snapshot}")
    def api_gcp_compute_delete_snapshot(project: str, snapshot: str):
        return _server().api_gcp_compute_delete_snapshot(project, snapshot)

    @app.get("/compute/v1/projects/{project}/global/images")
    @app.get("/api/gcp/compute/v1/projects/{project}/global/images")
    def api_gcp_compute_list_images(project: str):
        return _server().api_gcp_compute_list_images(project)

    @app.post("/compute/v1/projects/{project}/global/images")
    @app.post("/api/gcp/compute/v1/projects/{project}/global/images")
    async def api_gcp_compute_create_image(project: str, request: Request):
        return await _server().api_gcp_compute_create_image(project, request)

    @app.get("/compute/v1/projects/{project}/global/images/{image_name}")
    @app.get("/api/gcp/compute/v1/projects/{project}/global/images/{image_name}")
    def api_gcp_compute_get_image(project: str, image_name: str):
        return _server().api_gcp_compute_get_image(project, image_name)

    @app.delete("/compute/v1/projects/{project}/global/images/{image_name}")
    @app.delete("/api/gcp/compute/v1/projects/{project}/global/images/{image_name}")
    def api_gcp_compute_delete_image(project: str, image_name: str):
        return _server().api_gcp_compute_delete_image(project, image_name)
