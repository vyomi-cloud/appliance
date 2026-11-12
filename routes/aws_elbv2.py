"""AWS Elastic Load Balancing v2 — console REST (`/api/aws/elbv2/*`) and the native
Query-protocol store, both on the shared engine in core/elbv2_core.py.

State is space-scoped (`ctx.elbv2_state`), so load balancers follow the active
space, show up in its cost-savings metrics and survive restarts with it.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from core import app_context as ctx
from core import elbv2_core as elb


class SpaceElbv2Store(elb.Elbv2Store):
    """Elbv2Store whose dicts live in the active space's service state."""

    _KEYS = ("load_balancers", "target_groups", "listeners", "rules", "tags", "trust_stores", "trust_store_revocations")

    def __init__(self) -> None:
        self.account_id = ctx.AWS_ACCOUNT_ID
        self.region = "us-east-1"

    def _s(self) -> dict:
        return ctx.elbv2_state

    @property
    def vpc_store(self):
        from server import _Ec2CoreSpaceStore
        return _Ec2CoreSpaceStore()

    @vpc_store.setter
    def vpc_store(self, value):
        pass   # always re-derived from the active space (see the getter)

    @property
    def cw_store(self):
        from routes import aws_cloudwatch
        return aws_cloudwatch.get_store()

    @cw_store.setter
    def cw_store(self, value):
        pass

    @property
    def s3_store(self):
        from core import appliance_stores as aps
        return aps.s3_store()

    @s3_store.setter
    def s3_store(self, value):
        pass

    def persist(self) -> None:
        ctx.persist_state()
        # Activity log + space cost-savings refresh (same hook SQS/RDS use).
        ctx.record_usage("elbv2.change", {"resource_id": "elbv2", "name": "elbv2"})


def _prop(key):
    return property(lambda self: self._s().setdefault(key, {}))


for _k in SpaceElbv2Store._KEYS:
    setattr(SpaceElbv2Store, _k, _prop(_k))

STORE = SpaceElbv2Store()


def _call(fn, *a):
    try:
        return fn(STORE, *a)
    except elb.Elbv2Error as e:
        raise HTTPException(status_code=e.status, detail=f"{e.code}: {e.message}")


def _target_addr(target_id: str) -> str:
    """Address of a registered target: an IP as-is; an EC2 instance id -> its container's routable IP."""
    import re
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", target_id):
        return target_id
    import server as s
    inst, _ = s._find_instance_across_spaces("aws", target_id)
    if not inst:
        return ""
    try:
        return s._docker_compute().ssh_info(s._docker_instance_obj(inst)).get("container_ip") or inst.get("private_ip") or ""
    except Exception:
        return inst.get("private_ip") or ""


def _with_local_url(row: dict) -> dict:
    import server as s
    url = f"{s._gcp_public_base()}/elb/{row['name']}/"
    row["local_url"] = url
    row["data_plane"] = f"Local forwarding: {url}<path> -> a registered target (not the *.elb.amazonaws.com name, which does not resolve)"
    return row


def register(app: FastAPI) -> None:
    base = "/api/aws/elbv2"

    # Local data plane: http://<origin>/elb/<load-balancer-name>/<path> is forwarded to a target of the
    # LB's first listener's forward action (round-robin over registered targets).
    _rr = {"n": 0}

    def _forward(name, path, method, query, body, headers):
        import urllib.request, urllib.error
        try:
            lb, targets = elb.forward_targets(STORE, name)
        except elb.Elbv2Error:
            return 404, b'{"message":"load balancer not found"}', {}
        if not targets:
            return 503, b'{"message":"no registered targets (register targets and add a listener with a forward action)"}', {}
        _rr["n"] += 1
        for i in range(len(targets)):
            tid, port = targets[(_rr["n"] + i) % len(targets)]
            addr = _target_addr(tid)
            if not addr:
                continue
            url = f"http://{addr}:{port}/{path}" + (("?" + query) if query else "")
            try:
                rq = urllib.request.Request(url, data=body or None, method=method,
                                            headers={k: v for k, v in headers.items() if k.lower() in ("content-type", "accept", "authorization")})
                with urllib.request.urlopen(rq, timeout=15) as up:
                    return up.status, up.read(), {"Content-Type": up.headers.get("Content-Type", "text/plain")}
            except urllib.error.HTTPError as he:
                return he.code, he.read() or b"", {}
            except Exception:
                continue
        return 502, b'{"message":"no healthy target reachable"}', {}

    @app.api_route("/elb/{name}", include_in_schema=False, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    @app.api_route("/elb/{name}/{path:path}", include_in_schema=False, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    async def elb_forward(name: str, request: Request, path: str = ""):
        body = await request.body()
        st, data, hd = await run_in_threadpool(_forward, name, path, request.method, request.url.query, body, dict(request.headers))
        return Response(content=data, status_code=st, headers=hd)

    @app.get(base + "/load-balancers", include_in_schema=False)
    def elb_list():
        out = elb.console_list(STORE)
        out["items"] = [_with_local_url(r) for r in out["items"]]
        return out

    @app.post(base + "/load-balancers", include_in_schema=False)
    def elb_create(payload: dict[str, Any] | None = None):
        return _call(elb.console_create, payload or {})

    @app.get(base + "/load-balancers/{name}", include_in_schema=False)
    def elb_get(name: str):
        return _with_local_url(_call(elb.console_get, name))

    @app.patch(base + "/load-balancers/{name}", include_in_schema=False)
    def elb_patch(name: str, payload: dict[str, Any] | None = None):
        return _call(elb.console_set_tags, name, (payload or {}).get("tags") or {})

    @app.delete(base + "/load-balancers/{name}", include_in_schema=False)
    def elb_delete(name: str):
        return _call(elb.console_delete, name)

    @app.get(base + "/{kind}", include_in_schema=False)
    def elb_children(kind: str):
        return _call(elb.console_children, kind)

    @app.post(base + "/{kind}", include_in_schema=False)
    def elb_child_create(kind: str, payload: dict[str, Any] | None = None):
        return _call(elb.console_child_create, kind, payload or {})

    @app.delete(base + "/{kind}/{name}", include_in_schema=False)
    def elb_child_delete(kind: str, name: str):
        return _call(elb.console_child_delete, kind, name)
