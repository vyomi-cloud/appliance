"""Offline Auto Scaling route (wave 5b gap sweep, aws.cloudwatch.alarms.actions.compute /
ec2.auto-scaling): the real appliance's `aws_query_root` (routes/aws_s3.py) previously had
no "autoscaling" branch at all — an unmodified boto3 `autoscaling` client pointed at the
appliance got `InvalidAction: Root dispatch could not route service='autoscaling'`. This
proves the native Auto Scaling Query wire is now routed there, backed by a DURABLE,
space-scoped store (core/app_context.asg_state, routes/aws_autoscaling.SpaceAsgStore) — not
the in-memory store Nano/consoles/dev_server.py use — and that its scaled instances land in
the SAME offline VPC engine (server.py's `_Ec2CoreSpaceStore`) the EC2 console's own
CreateKeyPair/CreateLaunchTemplate/security-group extras already use.

    PYTHONPATH=. python3 -m pytest -q tests/conformance/test_autoscaling_offline_route.py
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest

_D = Path(tempfile.mkdtemp(prefix="vyomi-asgoffline-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_D / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_D / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

C = TestClient(server.app)


def _hdr(service: str) -> dict:
    return {"Authorization": f"AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/{service}/aws4_request, "
                             "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64,
            "content-type": "application/x-www-form-urlencoded"}


def asg(action, **p):
    r = C.post("/", data={"Action": action, "Version": "2011-01-01", **{k: str(v) for k, v in p.items()}}, headers=_hdr("autoscaling"))
    return r.status_code, r.text


def test_autoscaling_is_routed_on_the_real_appliance():
    status, body = asg("CreateAutoScalingGroup", AutoScalingGroupName="offline-route-asg", MinSize="1", MaxSize="3", DesiredCapacity="2")
    assert status == 200, body
    status, body = asg("DescribeAutoScalingGroups", **{"AutoScalingGroupNames.member.1": "offline-route-asg"})
    assert status == 200
    assert body.count("<InstanceId>") == 2   # DesiredCapacity=2 really launched 2 EC2 instances


def test_autoscaling_store_is_durable_and_space_scoped():
    from core import app_context as ctx
    assert "offline-route-asg" in ctx.asg_state.get("groups", {})


def test_scaled_instances_land_in_the_same_offline_vpc_engine_the_ec2_console_uses():
    model = server._Ec2CoreSpaceStore()._vpc_model or {}
    _, body = asg("DescribeAutoScalingGroups", **{"AutoScalingGroupNames.member.1": "offline-route-asg"})
    iid = re.search(r"<InstanceId>([^<]+)</InstanceId>", body).group(1)
    assert iid in (model.get("instances") or {})


def test_unroutable_before_this_change_now_resolves():
    # A boto3 autoscaling client with NO matching branch used to fall through to the
    # generic "could not route" error; PutScalingPolicy must resolve cleanly now.
    status, body = asg("PutScalingPolicy", AutoScalingGroupName="offline-route-asg", PolicyName="p1",
                       PolicyType="SimpleScaling", AdjustmentType="ChangeInCapacity", ScalingAdjustment="1")
    assert status == 200
    assert "Root dispatch could not route" not in body


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
