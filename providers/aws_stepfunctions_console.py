"""Console REST for Step Functions — the offline appliance's `/api/stepfunctions/...`
surface the AWS console catalog drives. Thin adapter over core/stepfunctions_core.py on
the SAME shared store the native JSON wire uses, so a state machine created in the
console is visible to the SDK/CLI and vice-versa."""
from __future__ import annotations

from fastapi import HTTPException, Request

from core import stepfunctions_core as core


def _call(op, **body):
    r = core.dispatch(core.shared_store(), "AWSStepFunctions." + op, body)
    if r.status >= 400:
        raise HTTPException(r.status, detail=f"{r.body.get('__type', 'Error')}: {r.body.get('message', '')}")
    return r.body


def _sm(name):
    sm = core.shared_store().machines.get(name)
    if not sm:
        raise HTTPException(404, detail=f"StateMachineDoesNotExist: State Machine Does Not Exist: '{name}'")
    return sm


def register(app, on_change=None):
    """`on_change(action, machine_view_or_name)` lets the host sync CloudSim events/usage."""
    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    view = lambda sm: core.machine_view(sm, core.shared_store())  # noqa: E731

    @app.get("/api/stepfunctions/machines")
    def list_machines():
        ms = sorted((view(m) for m in core.shared_store().machines.values()), key=lambda m: (m["created"], m["name"]))
        return {"machines": ms, "count": len(ms)}

    @app.post("/api/stepfunctions/machines")
    async def create_machine(request: Request):
        b = await request.json()
        name = str(b.get("name") or "").strip()
        body = {"name": name, "definition": b.get("definition") or core.default_definition(),
                "roleArn": b.get("role_arn") or core.default_role_arn(),
                "type": str(b.get("type") or "STANDARD").upper()}
        _call("CreateStateMachine", **body)
        v = view(_sm(name))
        changed("create", v)
        return v

    @app.get("/api/stepfunctions/machines/{name}")
    def get_machine(name: str):
        return view(_sm(name))

    @app.patch("/api/stepfunctions/machines/{name}")
    async def patch_machine(name: str, request: Request):
        b = await request.json()
        sm = _sm(name)
        upd = {k: b[k] for k in ("definition", "roleArn") if b.get(k)}
        if upd:
            _call("UpdateStateMachine", stateMachineArn=sm["stateMachineArn"], **upd)
        if isinstance(b.get("tags"), dict):
            core.shared_store().tags[sm["stateMachineArn"]] = {str(k): str(v) for k, v in b["tags"].items()}
        return view(sm)

    @app.delete("/api/stepfunctions/machines/{name}")
    def delete_machine(name: str):
        _call("DeleteStateMachine", stateMachineArn=_sm(name)["stateMachineArn"])
        changed("delete", name)
        return {"message": "State machine deleted", "name": name}

    @app.post("/api/stepfunctions/machines/{name}/executions")
    async def start_execution(name: str, request: Request):
        b = await request.json() if (await request.body()) else {}
        out = _call("StartExecution", stateMachineArn=_sm(name)["stateMachineArn"],
                    **({"name": b["name"]} if b.get("name") else {}), input=b.get("input") or "{}")
        return core.execution_view(core.shared_store().executions[out["executionArn"]])

    @app.get("/api/stepfunctions/machines/{name}/{kind}")
    def children(name: str, kind: str):
        return core.children(core.shared_store(), _sm(name), kind)
