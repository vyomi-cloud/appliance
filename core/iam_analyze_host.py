"""Host glue for the IAM analysis routes (core/iam_engine/analyze_wire.py): binds the engine to this substrate's stores.

Mesh: the live appliance stores (core/appliance_stores + core/iam_state_adapters). Nano: the in-browser registry
(core/iam_state_nano via nano_bridge). Called from core/aws_wire_router.AwsWireRouter._handle_raw before service routing; returns None for
every request that is not one of the analysis routes, so the common path costs one regex."""
from __future__ import annotations

from core.iam_engine import analyze_wire


class _Host:
    def aws(self):
        try:
            from core import iam_state_adapters as ad
            from core.appliance_stores import iam_store
            store = iam_store()
            state = ad.aws_state(store)
        except ImportError:                                    # Nano: the registry
            from core import iam_state_adapters as ad, nano_registry
            store = nano_registry.get()["iam"]
            state = ad.aws_state(store)
        audit = []
        try:
            from core.iam_engine import audit as _audit
            audit = _audit.default_log.list(1000)
        except Exception:
            pass
        return {"store": store, "state": state, "audit": audit, "region": "us-east-1"}

    def state(self, cloud, headers, query, path):
        try:
            from core import iam_state_adapters as ad
            from core import appliance_stores  # noqa: F401  (Mesh only)
            from core import app_context as ctx
            space = (ctx.gcp_active_space_dict() or ctx.STATE) if cloud == "gcp" else None
            return ad.state_and_principal(cloud, headers, query, space, path)
        except ImportError:
            from core.iam_engine import nano_bridge
            return nano_bridge.state_and_principal(cloud, headers, query)


def pre(method, path, query, headers, body):
    """Router response dict for an analysis route, else None. Never raises into the router (a failure is a 500 in the API's own shape)."""
    route = analyze_wire.match(method, path, query, headers, body)
    if route is None:
        return None
    try:
        return analyze_wire.handle(route, {"method": method, "path": path, "query": query, "headers": headers, "body": body}, _Host())
    except Exception as e:                                    # noqa: BLE001
        import json
        return {"status": 500, "headers": {"content-type": "application/json", "x-amzn-errortype": "InternalFailure"},
                "body": json.dumps({"message": f"IAM analysis failed: {type(e).__name__}: {e}", "error": {"code": 500, "message": str(e)}}).encode()}
