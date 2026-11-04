"""AWS Auto Scaling — console REST is the EC2 console itself (no separate `/api/aws/
autoscaling/*`); this module only wires the native Query-protocol store, on the shared
engine in core/autoscaling_core.py.

State is space-scoped (`ctx.asg_state`), so groups/policies/scheduled actions/lifecycle
hooks follow the active space and survive restarts with it — the durable, appliance-wide
counterpart of the in-WASM `AutoScalingStore` Nano and `consoles/dev_server.py` use
(core/aws_wire_router.py already dispatches `asg` there). `vpc_store` points at the SAME
offline VPC engine `api_vpc_core_query` uses (server.py's `_Ec2CoreSpaceStore`), so a
scaled group's instances are the SAME EC2 instances the offline EC2 console shows.
"""
from __future__ import annotations

from core import app_context as ctx
from core import autoscaling_core as asg


class SpaceAsgStore(asg.AutoScalingStore):
    """AutoScalingStore whose dicts live in the active space's service state."""

    _KEYS = ("groups", "policies", "scheduled_actions", "lifecycle_hooks")

    def __init__(self) -> None:
        self.account_id = asg.DEFAULT_ACCOUNT_ID
        self.region = asg.REGION

    def _s(self) -> dict:
        return ctx.asg_state

    @property
    def instance_refreshes(self):
        return self._s().setdefault("instance_refreshes", [])

    @instance_refreshes.setter
    def instance_refreshes(self, value):
        self._s()["instance_refreshes"] = value

    @property
    def vpc_store(self):
        from server import _Ec2CoreSpaceStore
        store = _Ec2CoreSpaceStore()
        try:
            from routes import aws_cloudwatch
            store.cw_store = aws_cloudwatch.get_store()
        except Exception:
            pass
        return store

    @vpc_store.setter
    def vpc_store(self, value):
        pass   # always re-derived from the active space (see the getter)

    def persist(self) -> None:
        ctx.persist_state()
        ctx.record_usage("autoscaling.change", {"resource_id": "asg", "name": "asg"})


def _prop(key):
    return property(lambda self: self._s().setdefault(key, {}))


for _k in SpaceAsgStore._KEYS:
    setattr(SpaceAsgStore, _k, _prop(_k))

STORE = SpaceAsgStore()
