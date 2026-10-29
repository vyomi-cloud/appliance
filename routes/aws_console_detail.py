"""Offline routes behind the AWS console's resource-detail tabs.

Thin FastAPI wrappers over core/aws_console_detail.py (the same engine Nano runs
in the browser): each detail tab reads/writes THIS resource's data through one of
these, shaped like the real AWS API response it mirrors.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from core import app_context as ctx
from core import aws_console_detail as D


def _srv():
    import server as server_module
    return server_module


def _net() -> D.OfflineNet:
    return D.OfflineNet(ctx.vpc_state, ctx.id_gen, ctx.now)


def _iam_role(name: str):
    for r in ctx.iam_state.get("roles", {}).values():
        if name in {r.get("role_name", ""), r.get("role_id", "")}:
            return {"role_name": r.get("role_name"), "arn": r.get("arn") or f"arn:aws:iam::{ctx.AWS_ACCOUNT_ID}:role/{r.get('role_name')}"}
    return None


def ensure_model(inst: dict) -> dict:
    before = (inst.get("vpc_id"), bool(inst.get("network_interfaces")), bool(inst.get("block_device_mappings")))
    try:
        D.ensure_instance_model(inst, _net())
    except D.DetailError:
        return inst
    if before != (inst.get("vpc_id"), True, True):
        ctx.persist_state()
    return inst


def _instance(instance_id: str) -> dict:
    inst = ctx.ec2_state.get("instances", {}).get(instance_id)
    if not isinstance(inst, dict):
        raise HTTPException(404, detail="InvalidInstanceID.NotFound")
    return ensure_model(inst)


def _fail(e: D.DetailError):
    raise HTTPException(e.status, detail={"code": e.code, "message": e.message})


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def apply_launch(instance: dict, payload: dict) -> None:
    """Called by the EC2 create route with the raw console payload."""
    try:
        D.apply_launch(instance, payload, _net(), _iam_role)
    except D.DetailError as e:
        _fail(e)
    ctx.persist_state()


def iam_principals() -> list:
    """Offline IAM users / groups / roles with the documents of their attached policies."""
    st = ctx.iam_state
    pols = st.get("policies", {})

    def docs(ids):
        out = []
        for pid in ids or []:
            p = pols.get(pid) or next((x for x in pols.values() if pid in {x.get("policy_name"), x.get("arn")}), None)
            if p:
                out.append({"name": p.get("policy_name", pid), "arn": p.get("arn") or f"arn:aws:iam::{ctx.AWS_ACCOUNT_ID}:policy/{p.get('policy_name', pid)}",
                            "document": p.get("document")})
        return out
    acct = ctx.AWS_ACCOUNT_ID
    out = []
    for u in st.get("users", {}).values():
        out.append({"type": "User", "name": u.get("user_name", ""), "arn": u.get("arn") or f"arn:aws:iam::{acct}:user/{u.get('user_name')}", "policies": docs(u.get("policies"))})
    for g in st.get("groups", {}).values():
        out.append({"type": "Group", "name": g.get("group_name", ""), "arn": g.get("arn") or f"arn:aws:iam::{acct}:group/{g.get('group_name')}", "policies": docs(g.get("policies"))})
    for r in st.get("roles", {}).values():
        out.append({"type": "Role", "name": r.get("role_name", ""), "arn": r.get("arn") or f"arn:aws:iam::{acct}:role/{r.get('role_name')}", "policies": docs(r.get("policies"))})
    return out


def register(app: FastAPI) -> None:
    # ── EC2 instance detail tabs ─────────────────────────────────────────────
    @app.get("/api/ec2/instances/{instance_id}/details")
    def ec2_details(instance_id: str):
        return D.details_view(_instance(instance_id))

    @app.put("/api/ec2/instances/{instance_id}/attributes")
    async def ec2_modify_attributes(instance_id: str, request: Request):
        inst = _instance(instance_id)
        try:
            out = D.modify_attributes(inst, await _body(request))
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.modify_instance_attribute", {"instance_id": instance_id, "resource_id": instance_id})
        return out

    @app.get("/api/ec2/instances/{instance_id}/network-interfaces")
    def ec2_enis(instance_id: str):
        inst = _instance(instance_id)
        return {"network_interfaces": D.network_interfaces_view(inst, _net())}

    @app.get("/api/ec2/instances/{instance_id}/security")
    def ec2_security(instance_id: str):
        return D.security_view(_instance(instance_id), _net())

    @app.get("/api/ec2/instances/{instance_id}/storage")
    def ec2_storage(instance_id: str):
        inst = _instance(instance_id)
        vols = [v for v in ctx.ec2_state.get("volumes", {}).values()
                if any(a.get("instance_id") == instance_id for a in v.get("attachments") or [])]
        return D.storage_view(inst, vols)

    @app.get("/api/ec2/instances/{instance_id}/user-data")
    def ec2_get_user_data(instance_id: str):
        inst = _instance(instance_id)
        return {"instance_id": instance_id, "user_data": inst.get("user_data") or "", "state": inst.get("state", "")}

    @app.put("/api/ec2/instances/{instance_id}/user-data")
    async def ec2_put_user_data(instance_id: str, request: Request):
        inst = _instance(instance_id)
        try:
            out = D.set_user_data(inst, (await _body(request)).get("user_data", ""))
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.modify_instance_attribute", {"instance_id": instance_id, "resource_id": instance_id, "attribute": "userData"})
        return out

    @app.get("/api/ec2/instances/{instance_id}/iam-instance-profile")
    def ec2_get_profile(instance_id: str):
        inst = _instance(instance_id)
        return {"instance_id": instance_id, "iam_instance_profile": inst.get("iam_instance_profile") or None,
                "roles": sorted(r.get("role_name", "") for r in ctx.iam_state.get("roles", {}).values())}

    @app.put("/api/ec2/instances/{instance_id}/iam-instance-profile")
    async def ec2_put_profile(instance_id: str, request: Request):
        inst = _instance(instance_id)
        try:
            out = D.associate_iam_instance_profile(inst, (await _body(request)).get("name", ""), _iam_role, ctx.AWS_ACCOUNT_ID)
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.associate_iam_instance_profile", {"instance_id": instance_id, "resource_id": instance_id, "profile": out["arn"]})
        return {"instance_id": instance_id, "iam_instance_profile": out}

    @app.delete("/api/ec2/instances/{instance_id}/iam-instance-profile")
    def ec2_delete_profile(instance_id: str):
        inst = _instance(instance_id)
        try:
            out = D.disassociate_iam_instance_profile(inst)
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.disassociate_iam_instance_profile", {"instance_id": instance_id, "resource_id": instance_id})
        return {"instance_id": instance_id, "iam_instance_profile": None, "disassociated": out}

    @app.get("/api/ec2/instances/{instance_id}/console-output")
    def ec2_console_output(instance_id: str):
        inst = _instance(instance_id)
        log = inst.get("console_log") or []
        text = "\n".join((e.get("output") or "").rstrip("\n") for e in log[-50:] if isinstance(e, dict) and e.get("output"))
        return D.console_output(inst, text)

    @app.get("/api/ec2/serial-console-access")
    def ec2_serial_access():
        return {"serial_console_access_enabled": bool(ctx.ec2_state.get("account_attributes", {}).get("serial_console_access"))}

    @app.put("/api/ec2/serial-console-access")
    async def ec2_set_serial_access(request: Request):
        on = (await _body(request)).get("enabled") in D._TRUE
        ctx.ec2_state.setdefault("account_attributes", {})["serial_console_access"] = on
        ctx.persist_state()
        ctx.record_usage("ec2.serial_console_access", {"enabled": on})
        return {"serial_console_access_enabled": on}

    # ── Permissions tab (every service): identity policies covering a resource ──
    @app.get("/api/aws/resource-access")
    def resource_access(arn: str, service: str):
        return {"resource_arn": arn, "statements": D.resource_access(iam_principals(), arn, service)}
