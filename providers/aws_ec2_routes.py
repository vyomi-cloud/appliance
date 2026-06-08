from __future__ import annotations

import random
import time
from typing import Any

from fastapi import Request, HTTPException

from core.models import EC2InstanceRequest, EC2ConsoleInputRequest, EC2ConsoleCommandRequest
from core import app_context as ctx

ec2_state = ctx.ec2_state

# ---------------------------------------------------------------------------
# CloudWatch metric names
# ---------------------------------------------------------------------------

_CLOUDWATCH_METRIC_NAMES = [
    "CPUUtilization",
    "NetworkIn",
    "NetworkOut",
    "DiskReadOps",
    "DiskWriteOps",
    "StatusCheckFailed",
]

# ---------------------------------------------------------------------------
# CloudWatch helpers
# ---------------------------------------------------------------------------


def _cloudwatch_generate_metrics(instance: dict) -> dict[str, list[dict]]:
    """Return synthetic CloudWatch-style metric data points for *instance*.

    Each metric gets 5 recent data points spaced ~60 s apart so the caller
    can render a mini time-series chart.
    """
    state = (instance.get("state") or "stopped").lower()
    inst_type = instance.get("instance_type") or instance.get("type") or "t2.micro"
    is_running = state == "running"

    # Determine scale factors from instance type
    type_multiplier = 1.0
    if "xlarge" in inst_type:
        type_multiplier = 4.0
    elif "large" in inst_type:
        type_multiplier = 2.0
    elif "medium" in inst_type:
        type_multiplier = 1.5

    now = time.time()
    metrics: dict[str, list[dict]] = {}

    for metric_name in _CLOUDWATCH_METRIC_NAMES:
        points = []
        for i in range(5):
            ts = now - (4 - i) * 60  # 5 data points, 60 s apart
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

            if metric_name == "CPUUtilization":
                value = round(random.uniform(15.0, 45.0), 2) if is_running else 0.0
            elif metric_name == "NetworkIn":
                value = round(random.uniform(5000, 50000) * type_multiplier) if is_running else 0
            elif metric_name == "NetworkOut":
                value = round(random.uniform(2000, 30000) * type_multiplier) if is_running else 0
            elif metric_name == "DiskReadOps":
                value = round(random.uniform(10, 200) * type_multiplier) if is_running else 0
            elif metric_name == "DiskWriteOps":
                value = round(random.uniform(5, 150) * type_multiplier) if is_running else 0
            elif metric_name == "StatusCheckFailed":
                value = 0 if is_running else 1
            else:
                value = 0

            points.append({"timestamp": timestamp, "value": value, "unit": _metric_unit(metric_name)})
        metrics[metric_name] = points
    return metrics


def _metric_unit(name: str) -> str:
    return {
        "CPUUtilization": "Percent",
        "NetworkIn": "Bytes",
        "NetworkOut": "Bytes",
        "DiskReadOps": "Count",
        "DiskWriteOps": "Count",
        "StatusCheckFailed": "Count",
    }.get(name, "None")


def _evaluate_alarm(alarm: dict, instances: dict) -> str:
    """Evaluate an alarm condition and return OK | ALARM | INSUFFICIENT_DATA."""
    instance_id = alarm.get("instance_id", "")
    instance = instances.get(instance_id)
    if not instance:
        return "INSUFFICIENT_DATA"

    metric_name = alarm.get("metric_name", "")
    threshold = float(alarm.get("threshold", 0))
    comparison = alarm.get("comparison_operator", "GreaterThanThreshold")

    metrics = _cloudwatch_generate_metrics(instance)
    points = metrics.get(metric_name, [])
    if not points:
        return "INSUFFICIENT_DATA"

    latest_value = points[-1]["value"]

    comparisons = {
        "GreaterThanThreshold": latest_value > threshold,
        "GreaterThanOrEqualToThreshold": latest_value >= threshold,
        "LessThanThreshold": latest_value < threshold,
        "LessThanOrEqualToThreshold": latest_value <= threshold,
    }
    triggered = comparisons.get(comparison, False)
    return "ALARM" if triggered else "OK"


def _server():
    import server as server_module

    return server_module


def register(app, h) -> None:
    @app.get("/api/ec2/amis")
    def api_ec2_amis():
        return _server().api_ec2_amis()

    @app.get("/api/ec2/runtime")
    def api_ec2_runtime(request: Request):
        return _server().api_ec2_runtime(request.headers.get("x-cloudlearn-host-os", ""))

    @app.get("/api/ec2/runtime/lxd")
    def api_ec2_runtime_lxd():
        return _server().api_ec2_runtime_lxd()

    @app.get("/api/ec2/runtime/multipass")
    def api_ec2_runtime_multipass():
        return _server().api_ec2_runtime_multipass()

    @app.post("/api/ec2/runtime/bootstrap")
    def api_ec2_runtime_bootstrap():
        return _server().api_ec2_runtime_bootstrap()

    @app.post("/api/ec2/runtime/lxd/bootstrap")
    def api_ec2_runtime_lxd_bootstrap():
        return _server().api_ec2_runtime_lxd_bootstrap()

    @app.post("/api/ec2/runtime/multipass/bootstrap")
    def api_ec2_runtime_multipass_bootstrap():
        return _server().api_ec2_runtime_multipass_bootstrap()

    @app.get("/api/ec2/instances")
    def api_ec2_list_instances():
        return _server().api_ec2_list_instances()

    @app.post("/api/ec2/instances")
    async def api_ec2_create_instance(request: Request, auto_start: bool = True):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        model = EC2InstanceRequest(**payload)
        return _server().api_ec2_create_instance(
            model,
            auto_start=auto_start,
            host_os_hint=request.headers.get("x-cloudlearn-host-os", ""),
        )

    @app.post("/api/ec2/instances/{instance_id}/start")
    def api_ec2_start_instance(instance_id: str):
        return _server().api_ec2_start_instance(instance_id)

    @app.post("/api/ec2/instances/{instance_id}/stop")
    def api_ec2_stop_instance(instance_id: str):
        return _server().api_ec2_stop_instance(instance_id)

    @app.post("/api/ec2/instances/{instance_id}/reboot")
    def api_ec2_reboot_instance(instance_id: str):
        return _server().api_ec2_reboot_instance(instance_id)

    @app.post("/api/ec2/instances/{instance_id}/terminate")
    def api_ec2_terminate_instance(instance_id: str):
        return _server().api_ec2_terminate_instance(instance_id)

    @app.get("/api/ec2/instances/{instance_id}/console")
    def api_ec2_console(instance_id: str):
        return _server().api_ec2_console(instance_id)

    @app.post("/api/ec2/instances/{instance_id}/console/input")
    async def api_ec2_console_input(instance_id: str, request: Request):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        model = EC2ConsoleInputRequest(**payload)
        return _server().api_ec2_console_input(instance_id, model)

    @app.post("/api/ec2/instances/{instance_id}/console/exec")
    async def api_ec2_console_exec(instance_id: str, request: Request):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        model = EC2ConsoleCommandRequest(**payload)
        return _server().api_ec2_console_exec(instance_id, model)

    # ── CloudWatch Monitoring Simulation ──────────────────────────────────

    @app.get("/api/ec2/cloudwatch/metrics")
    def api_ec2_cloudwatch_metrics():
        """List available CloudWatch metric names for EC2."""
        return {
            "namespace": "AWS/EC2",
            "metrics": [
                {"name": m, "unit": _metric_unit(m)}
                for m in _CLOUDWATCH_METRIC_NAMES
            ],
            "count": len(_CLOUDWATCH_METRIC_NAMES),
        }

    @app.get("/api/ec2/cloudwatch/metrics/{instance_id}")
    def api_ec2_cloudwatch_metrics_instance(instance_id: str):
        """Get synthetic CloudWatch metrics for a specific EC2 instance."""
        instances = ec2_state.get("instances", {})
        instance = instances.get(instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="InstanceNotFound")
        metrics = _cloudwatch_generate_metrics(instance)
        return {
            "instance_id": instance_id,
            "namespace": "AWS/EC2",
            "metrics": metrics,
        }

    @app.post("/api/ec2/cloudwatch/alarms")
    async def api_ec2_cloudwatch_create_alarm(request: Request):
        """Create a CloudWatch alarm."""
        payload: dict[str, Any] = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        alarm_name = str(payload.get("alarm_name", "")).strip()
        if not alarm_name:
            raise HTTPException(status_code=400, detail="alarm_name is required")

        metric_name = str(payload.get("metric_name", "")).strip()
        if metric_name not in _CLOUDWATCH_METRIC_NAMES:
            raise HTTPException(status_code=400, detail=f"metric_name must be one of {_CLOUDWATCH_METRIC_NAMES}")

        instance_id = str(payload.get("instance_id", "")).strip()
        threshold = float(payload.get("threshold", 0))
        comparison = str(payload.get("comparison_operator", "GreaterThanThreshold"))
        valid_comparisons = [
            "GreaterThanThreshold", "GreaterThanOrEqualToThreshold",
            "LessThanThreshold", "LessThanOrEqualToThreshold",
        ]
        if comparison not in valid_comparisons:
            raise HTTPException(status_code=400, detail=f"comparison_operator must be one of {valid_comparisons}")

        alarms = ec2_state.setdefault("cloudwatch_alarms", {})
        alarm = {
            "alarm_name": alarm_name,
            "metric_name": metric_name,
            "instance_id": instance_id,
            "threshold": threshold,
            "comparison_operator": comparison,
            "namespace": "AWS/EC2",
            "created_at": ctx.now(),
        }
        alarms[alarm_name] = alarm
        ctx.persist_state()

        # Evaluate current state
        instances = ec2_state.get("instances", {})
        alarm["state"] = _evaluate_alarm(alarm, instances)
        return {"message": "Alarm created", "alarm": alarm}

    @app.get("/api/ec2/cloudwatch/alarms")
    def api_ec2_cloudwatch_list_alarms():
        """List CloudWatch alarms with evaluated state."""
        alarms = ec2_state.setdefault("cloudwatch_alarms", {})
        instances = ec2_state.get("instances", {})
        result = []
        for alarm in alarms.values():
            alarm_copy = dict(alarm)
            alarm_copy["state"] = _evaluate_alarm(alarm, instances)
            result.append(alarm_copy)
        return {"alarms": result, "count": len(result)}

    @app.delete("/api/ec2/cloudwatch/alarms/{alarm_name}")
    def api_ec2_cloudwatch_delete_alarm(alarm_name: str):
        """Delete a CloudWatch alarm."""
        alarms = ec2_state.setdefault("cloudwatch_alarms", {})
        if alarm_name not in alarms:
            raise HTTPException(status_code=404, detail="AlarmNotFound")
        del alarms[alarm_name]
        ctx.persist_state()
        return {"message": "Alarm deleted", "alarm_name": alarm_name}

    # ── EBS Volumes ───────────────────────────────────────────────────────

    @app.get("/api/ec2/volumes")
    def api_ec2_list_volumes():
        """List all EBS volumes."""
        volumes = ec2_state.setdefault("volumes", {})
        return {"volumes": list(volumes.values()), "count": len(volumes)}

    @app.post("/api/ec2/volumes")
    async def api_ec2_create_volume(request: Request):
        """Create an EBS volume."""
        payload: dict[str, Any] = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        size = int(payload.get("size", 8))
        vol_type = str(payload.get("type", payload.get("volume_type", "gp3")))
        az = str(payload.get("availability_zone", payload.get("az", "us-east-1a")))

        volume_id = ctx.id_gen("vol")
        volume = {
            "volume_id": volume_id,
            "size": size,
            "volume_type": vol_type,
            "availability_zone": az,
            "state": "available",
            "attachments": [],
            "created_at": ctx.now(),
            "encrypted": bool(payload.get("encrypted", False)),
            "iops": int(payload.get("iops", 3000)) if vol_type in ("gp3", "io1", "io2") else None,
            "tags": payload.get("tags", {}),
        }
        volumes = ec2_state.setdefault("volumes", {})
        volumes[volume_id] = volume
        ctx.persist_state()
        return {"message": "Volume created", "volume": volume}

    @app.get("/api/ec2/volumes/{volume_id}")
    def api_ec2_get_volume(volume_id: str):
        """Get a specific EBS volume."""
        volumes = ec2_state.setdefault("volumes", {})
        volume = volumes.get(volume_id)
        if not volume:
            raise HTTPException(status_code=404, detail="VolumeNotFound")
        return volume

    @app.delete("/api/ec2/volumes/{volume_id}")
    def api_ec2_delete_volume(volume_id: str):
        """Delete an EBS volume."""
        volumes = ec2_state.setdefault("volumes", {})
        volume = volumes.get(volume_id)
        if not volume:
            raise HTTPException(status_code=404, detail="VolumeNotFound")
        if volume.get("attachments"):
            raise HTTPException(status_code=400, detail="Volume is attached to an instance; detach first")
        del volumes[volume_id]
        ctx.persist_state()
        return {"message": "Volume deleted", "volume_id": volume_id}

    @app.post("/api/ec2/volumes/{volume_id}/attach")
    async def api_ec2_attach_volume(volume_id: str, request: Request):
        """Attach an EBS volume to an EC2 instance."""
        payload: dict[str, Any] = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        instance_id = str(payload.get("instance_id", "")).strip()
        device = str(payload.get("device", "/dev/sdf"))
        if not instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")

        volumes = ec2_state.setdefault("volumes", {})
        volume = volumes.get(volume_id)
        if not volume:
            raise HTTPException(status_code=404, detail="VolumeNotFound")
        if volume["state"] != "available":
            raise HTTPException(status_code=400, detail=f"Volume is in state '{volume['state']}', must be 'available'")

        instances = ec2_state.get("instances", {})
        if instance_id not in instances:
            raise HTTPException(status_code=404, detail="InstanceNotFound")

        attachment = {
            "instance_id": instance_id,
            "device": device,
            "state": "attached",
            "attach_time": ctx.now(),
        }
        volume["attachments"] = [attachment]
        volume["state"] = "in-use"
        ctx.persist_state()
        return {"message": "Volume attached", "volume": volume}

    @app.post("/api/ec2/volumes/{volume_id}/detach")
    async def api_ec2_detach_volume(volume_id: str, request: Request):
        """Detach an EBS volume from an EC2 instance."""
        volumes = ec2_state.setdefault("volumes", {})
        volume = volumes.get(volume_id)
        if not volume:
            raise HTTPException(status_code=404, detail="VolumeNotFound")
        if volume["state"] != "in-use":
            raise HTTPException(status_code=400, detail=f"Volume is in state '{volume['state']}', must be 'in-use'")
        volume["attachments"] = []
        volume["state"] = "available"
        ctx.persist_state()
        return {"message": "Volume detached", "volume": volume}
