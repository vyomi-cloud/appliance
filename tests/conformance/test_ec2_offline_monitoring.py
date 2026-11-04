"""Offline EC2 legacy handler (Docker-backed instances, server.py's ec2_state — not the shared
core vpc_core.py already covered by test_ec2_console_v4_core.py): detailed monitoring actually
flips and persists, and status polling really publishes CloudWatch StatusCheckFailed datapoints
an alarm can evaluate against — see ec2.instances.monitoring / ec2.instances.alarms-metrics.

    PYTHONPATH=. python3 -m pytest -q tests/conformance/test_ec2_offline_monitoring.py
"""

from __future__ import annotations

import sys

import pytest

import json
import os
import re
import tempfile
from pathlib import Path

_D = Path(tempfile.mkdtemp(prefix="vyomi-ec2mon-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_D / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_D / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core import cloudwatch_core as cw  # noqa: E402
from routes import aws_cloudwatch  # noqa: E402

C = TestClient(server.app)
EC2H = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/ec2/aws4_request, "
                         "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64,
        "content-type": "application/x-www-form-urlencoded"}

# A fresh in-memory store, bypassing routes/aws_cloudwatch.py's sqlite-backed singleton — this
# test only cares that EC2 really ingests into whatever CloudWatch store the appliance is
# wired to, not CloudWatch's own persistence (covered by test_cloudwatch_core.py).
aws_cloudwatch._store = cw.CloudWatchStore()


def ec2(action, **p):
    r = C.post("/", data={"Action": action, "Version": "2016-11-15", **{k: str(v) for k, v in p.items()}}, headers=EC2H)
    return r.status_code, r.text


def _seed_running_instance() -> str:
    """A Docker-backed instance, minus the real container (this test runs with no docker
    socket) — exactly the shape api_ec2_create_instance leaves once the runtime boots."""
    instance_id = server._id("i")
    server.ec2_state["instances"][instance_id] = {
        "instance_id": instance_id, "reservation_id": f"r-{instance_id.replace('i-', '')}",
        "owner_id": server.AWS_ACCOUNT_ID, "name": "mon-probe", "instance_type": "t3.micro",
        "ami": "ami-amzn2023", "ami_name": "Amazon Linux 2023", "os_family": "linux",
        "state": "running", "az": "us-east-1a", "vpc_id": "", "subnet_id": "",
        "security_group_ids": [], "storage_gb": 8, "private_ip": "10.0.0.9",
        "public_ip": None, "created": server._now(), "runtime_backend": "", "container_id": "",
    }
    return instance_id


def test_monitor_instances_flips_and_persists_offline():
    iid = _seed_running_instance()
    st, body = ec2("DescribeInstances", **{"InstanceId.1": iid})
    assert st == 200 and "<monitoring><state>disabled</state></monitoring>" in body, body

    st, body = ec2("MonitorInstances", **{"InstanceId.1": iid})
    assert st == 200 and "<state>enabled</state>" in body, body
    assert server.ec2_state["instances"][iid]["monitoring"] is True

    st, body = ec2("DescribeInstances", **{"InstanceId.1": iid})
    assert st == 200 and "<monitoring><state>enabled</state></monitoring>" in body, body

    st, body = ec2("UnmonitorInstances", **{"InstanceId.1": iid})
    assert st == 200 and "<state>disabled</state>" in body, body
    assert server.ec2_state["instances"][iid]["monitoring"] is False


@pytest.mark.skipif(sys.platform != "linux",
                    reason="offline RunInstances launches a real instance (Docker compute), which the appliance supports on Linux hosts only")
def test_run_instances_honors_monitoring_enabled_param_offline():
    st, body = ec2("RunInstances", InstanceType="t3.micro", MaxCount="1",
                    **{"Monitoring.Enabled": "true"})
    assert st == 200, body
    iid = re.search(r"<instanceId>([^<]+)</instanceId>", body).group(1)
    assert server.ec2_state["instances"][iid]["monitoring"] is True
    assert "<monitoring><state>enabled</state></monitoring>" in ec2("DescribeInstances", **{"InstanceId.1": iid})[1]


def test_describe_instance_status_publishes_a_real_metric_offline():
    iid = _seed_running_instance()
    ec2("MonitorInstances", **{"InstanceId.1": iid})

    st, body = ec2("DescribeInstanceStatus", **{"InstanceId.1": iid})
    assert st == 200 and "<status>ok</status>" in body, body

    store = aws_cloudwatch.get_store()
    key = "AWS/EC2\x1fStatusCheckFailed\x1f" + json.dumps([["InstanceId", iid]], separators=(",", ":"))
    series = store.metrics.get(key)
    assert series is not None and series["points"][-1][1] == 0.0

    alarm_name = f"v4-ec2-offline-{iid}"
    cw.op_put_metric_alarm(store, {
        "AlarmName": alarm_name, "Namespace": "AWS/EC2", "MetricName": "StatusCheckFailed",
        "Dimensions": [{"Name": "InstanceId", "Value": iid}], "Statistic": "Maximum", "Period": 60,
        "EvaluationPeriods": 1, "Threshold": 1, "ComparisonOperator": "GreaterThanOrEqualToThreshold"})
    assert store.alarms[alarm_name]["StateValue"] == "OK"
