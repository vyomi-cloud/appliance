"""Console REST for Systems Manager Parameter Store — the offline appliance's
`/api/ssm/...` surface the AWS console catalog drives. Thin adapter over
core/ssm_core.py on the SAME shared store the native `AmazonSSM.*` wire uses, so a
parameter created in the console is visible to the SDK/CLI and vice-versa."""
from __future__ import annotations

from fastapi import HTTPException, Request

from core import ssm_core as core


def _call(op, body):
    r = core.dispatch(core.shared_store(), "AmazonSSM." + op, body)
    if r.status >= 400:
        raise HTTPException(r.status, detail=f"{r.body.get('__type', 'Error')}: {r.body.get('message', '')}")
    return r.body


def put(op_body: dict, overwrite: bool = False) -> dict:
    """Shared by the console REST and the Nano adapter: create/update a parameter."""
    name = str(op_body.get("name") or "").strip()
    body = {"Name": name, "Value": str(op_body.get("value") if op_body.get("value") is not None else ""),
            "Type": op_body.get("type") or "String", "Overwrite": overwrite}
    if op_body.get("description"):
        body["Description"] = op_body["description"]
    if op_body.get("tier"):
        body["Tier"] = op_body["tier"]
    _call("PutParameter", body)
    return core.console_view(name, core.shared_store().parameters[name])


def register(app, on_change=None):
    """`on_change(action, name)` lets the host sync CloudSim events/usage."""
    def changed(action, name):
        if on_change:
            try:
                on_change(action, name)
            except Exception:
                pass

    def rec_or_404(name):
        rec = core.shared_store().parameters.get(name)
        if not rec:
            raise HTTPException(404, detail=f"ParameterNotFound: Parameter {name} not found.")
        return rec

    @app.get("/api/ssm/parameters")
    def list_parameters():
        items = [core.console_view(n, r) for n, r in sorted(core.shared_store().parameters.items())]
        return {"items": items, "parameters": items, "count": len(items)}

    @app.post("/api/ssm/parameters")
    async def create_parameter(request: Request):
        view = put(await request.json())
        changed("create", view["name"])
        return view

    @app.get("/api/ssm/parameters/{name:path}/history")
    def parameter_history(name: str):
        return {"history": core.console_history(name, rec_or_404(name))}

    @app.get("/api/ssm/parameters/{name:path}")
    def get_parameter(name: str):
        return core.console_view(name, rec_or_404(name))

    @app.put("/api/ssm/parameters/{name:path}")
    async def update_parameter(name: str, request: Request):
        rec = rec_or_404(name)
        cur = core.console_view(name, rec)
        b = await request.json()
        view = put({"name": name, "value": b.get("value", cur["value"]), "type": cur["type"],
                    "description": b.get("description", cur["description"]), "tier": cur["tier"]}, overwrite=True)
        changed("update", name)
        return view

    @app.patch("/api/ssm/parameters/{name:path}")
    async def patch_parameter(name: str, request: Request):
        rec = rec_or_404(name)
        b = await request.json()
        if isinstance(b.get("tags"), dict):
            rec["tags"] = {str(k): str(v) for k, v in b["tags"].items()}
        return core.console_view(name, rec)

    @app.delete("/api/ssm/parameters/{name:path}")
    def delete_parameter(name: str):
        _call("DeleteParameter", {"Name": name})
        changed("delete", name)
        return {"message": "Parameter deleted", "name": name}
