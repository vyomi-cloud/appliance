"""Simulation-space CRUD, providers list, runtime budget, cloud-shell, terraform
deploy targets, and CI integration routes.

Extracted from server.py — contains the /api/spaces/*, /api/providers,
/api/runtime/budget, /api/runtime/cloud-shell/*, /api/runtime/terraform-deploy-targets,
and /api/runtime/ci/* route handlers plus supporting helpers.
"""
from __future__ import annotations

import copy
import subprocess
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from core import app_context as ctx

# Aliases used throughout (mirror the old server.py names).
STATE = ctx.STATE
PLATFORM = ctx.PLATFORM
DEFAULT_TENANT_ID = ctx.DEFAULT_TENANT_ID
ALLOWED_PROVIDERS = ctx.ALLOWED_PROVIDERS

_now = ctx.now
_active_tenant_id = ctx.active_tenant_id
_tenant_dict = ctx.tenant_dict
_persist_state = ctx.persist_state
_record_usage = ctx.record_usage
_enforce_tier_feature = ctx.enforce_tier_feature
_active_tier = ctx.active_tier
_gcp_state_proxies = ctx.gcp_state_proxies
_gcp_project_name = ctx.gcp_project_name
_gcp_record_matches_project = ctx.gcp_record_matches_project
_gcp_active_space_dict = ctx.gcp_active_space_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spaces_state() -> dict:
    spaces_state = STATE.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {"max_spaces": 6, "default_provider": "aws", "default_region": "us-east-1"}})
    spaces_state.setdefault("spaces", {})
    spaces_state.setdefault("active_space_id", "")
    spaces_state.setdefault("settings", {})
    spaces_state["settings"].setdefault("max_spaces", 6)
    spaces_state["settings"].setdefault("default_provider", "aws")
    spaces_state["settings"].setdefault("default_region", "us-east-1")
    spaces_state["settings"].setdefault("max_memory_mb", 8192)
    spaces_state["settings"].setdefault("max_disk_mb", 32768)
    return spaces_state


def _federation_space_summary() -> dict:
    spaces_state = _spaces_state()
    spaces = spaces_state.get("spaces", {})
    federations = STATE.setdefault("federations", {"federations": {}, "links": {}, "tests": []})
    federation_defs = federations.get("federations", {})
    links = federations.get("links", {})
    link_values = list(links.values()) if isinstance(links, dict) else list(links) if isinstance(links, list) else []
    provider_counts: dict[str, int] = {}
    resource_counts = {
        "runtime_count": 0,
        "ec2_count": 0,
        "lambda_count": 0,
        "rds_count": 0,
        "sqs_count": 0,
        "dynamodb_count": 0,
    }
    active_space_ids = {
        space_id
        for space_id, space in spaces.items()
        if isinstance(space, dict) and str(space.get("status", "running")).lower() == "running"
    }
    linked_space_ids: set[str] = set()
    linked_active_space_ids: set[str] = set()
    link_count = 0
    for link in link_values:
        if not isinstance(link, dict):
            continue
        src = str(link.get("source_space_id") or link.get("source") or link.get("space_id") or "").strip()
        dst = str(link.get("target_space_id") or link.get("target") or link.get("peer_space_id") or "").strip()
        if not src and not dst:
            continue
        link_count += 1
        for sid in (src, dst):
            if sid:
                linked_space_ids.add(sid)
                if sid in active_space_ids:
                    linked_active_space_ids.add(sid)
    for space in spaces.values():
        if not isinstance(space, dict):
            continue
        provider = str(space.get("provider") or "aws").lower()
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        for key in resource_counts:
            resource_counts[key] += int(space.get(key) or 0)
    return {
        "federation_count": len(federation_defs) if isinstance(federation_defs, dict) else 0,
        "link_count": link_count,
        "linked_spaces": len(linked_space_ids),
        "active_linked_spaces": len(linked_active_space_ids),
        "linked_space_ids": sorted(linked_space_ids),
        "active_linked_space_ids": sorted(linked_active_space_ids),
        "provider_counts": provider_counts,
        "resource_counts": resource_counts,
    }


def _space_belongs_to_active_tenant(space: dict | None) -> bool:
    if not isinstance(space, dict):
        return False
    return (space.get("tenant_id") or DEFAULT_TENANT_ID) == _active_tenant_id()


def _require_tenant_space(space_id: str) -> dict:
    """Return the space dict iff it belongs to the active tenant; 404 otherwise.
    Cross-tenant ids are indistinguishable from non-existent ones (no leak)."""
    spaces = _spaces_state().get("spaces", {})
    space = spaces.get(space_id) if isinstance(spaces, dict) else None
    if not isinstance(space, dict) or not _space_belongs_to_active_tenant(space):
        raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
    return space


def _space_payload(space: dict) -> dict:
    payload = copy.deepcopy(space)
    if not isinstance(payload, dict):
        return {}
    payload.setdefault("space_id", "")
    payload.setdefault("name", "")
    payload.setdefault("provider", "aws")
    payload.setdefault("status", "running")
    payload.setdefault("active_region", "us-east-1")
    payload.setdefault("active_account", "local-account")
    payload.setdefault("estimated_memory_mb", 0)
    payload.setdefault("estimated_disk_mb", 0)
    payload.setdefault("runtime_count", 0)
    payload.setdefault("ec2_count", 0)
    payload.setdefault("lambda_count", 0)
    payload.setdefault("rds_count", 0)
    payload.setdefault("sqs_count", 0)
    payload.setdefault("dynamodb_count", 0)
    # ── Per-space TTL (computed server-side so the UI has a reliable anchor) ──
    from core import vyomi_platform as _vp
    payload.setdefault("created_at", "")
    payload.setdefault("ttl_seconds", 0)
    payload.setdefault("expires_at", None)
    payload["ttl_remaining_seconds"] = _vp.ttl_remaining_seconds(payload)
    payload["ttl_expired"] = _vp.ttl_is_expired(payload)
    cloudsim = payload.get("cloudsim")
    if isinstance(cloudsim, dict):
        cloudsim.pop("policy", None)
    payload.pop("cloudsim_policy", None)
    return payload


def _tenant_usage(tid: str) -> dict:
    spaces = (_spaces_state().get("spaces") or {})
    tenant = _tenant_dict(tid) or {}
    spaces_count = sum(1 for s in spaces.values()
                       if isinstance(s, dict) and (s.get("tenant_id") or DEFAULT_TENANT_ID) == tid)
    max_spaces = int((tenant.get("settings") or {}).get("max_spaces", 6))
    return {"spaces_count": spaces_count, "max_spaces": max_spaces,
            "spaces_remaining": max(0, max_spaces - spaces_count)}


# Shell allow-list: cloud SDK + utility binaries that make sense in a
# learning shell. We don't fork arbitrary commands — only listed ones.
_CLOUD_SHELL_ALLOWED = {
    "aws", "gcloud", "gsutil", "bq", "az", "terraform",
    "kubectl", "helm",
    "curl", "jq", "yq", "ls", "cat", "echo", "pwd", "env",
    "python3", "node", "java", "go",
}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Mount all /api/spaces/*, /api/providers, /api/runtime/budget,
    /api/runtime/cloud-shell/*, /api/runtime/terraform-deploy-targets,
    and /api/runtime/ci/* routes."""

    # Lazy import for helpers that still live in server.py
    def _srv():
        import server
        return server

    @app.get("/api/spaces")
    def api_list_spaces():
        _srv()._refresh_cloudsim_gcp_summary()
        all_spaces = PLATFORM.list_spaces()
        # TENANT FILTER: a tenant can only see its own spaces.
        tid = _active_tenant_id()
        spaces = [s for s in all_spaces if (s.get("tenant_id") or DEFAULT_TENANT_ID) == tid]
        # LAZY TTL ENFORCEMENT: shut down + mark expired any lapsed space so
        # TTL bites without a background reaper. Best-effort — never 500 the list.
        for _s in spaces:
            try:
                _updated = PLATFORM.expire_if_due(_s.get("space_id", ""))
                if isinstance(_updated, dict):
                    _s.clear()
                    _s.update(_updated)
            except Exception:
                pass
        ss = _spaces_state()
        active_id = ss.get("active_space_id", "")
        active_space_dict = ss.get("spaces", {}).get(active_id, {}) if active_id else {}
        if not _space_belongs_to_active_tenant(active_space_dict):
            active_id, active_space_dict = "", {}
        federation_summary = _federation_space_summary()
        return {
            "spaces": [_space_payload(space) for space in spaces],
            "count": len(spaces),
            "active_space_id": active_id,
            "active_space": _space_payload(active_space_dict) if active_id else None,
            "active_tenant_id": tid,
            "settings": copy.deepcopy(ss.get("settings", {})),
            "provider_counts": copy.deepcopy(federation_summary.get("provider_counts", {})),
            "resource_counts": copy.deepcopy(federation_summary.get("resource_counts", {})),
            "federation_summary": federation_summary,
        }

    @app.get("/api/providers")
    def api_list_providers():
        return {
            "providers": _srv()._legacy_provider_cards(),
            "default_provider": _spaces_state().get("settings", {}).get("default_provider", "aws"),
        }

    @app.get("/api/spaces/active")
    def api_active_space():
        _srv()._refresh_cloudsim_gcp_summary()
        ss = _spaces_state()
        active_id = ss.get("active_space_id", "")
        space = ss.get("spaces", {}).get(active_id, {}) if active_id else {}
        if not _space_belongs_to_active_tenant(space):  # foreign-tenant active = treat as none
            return {"active_space_id": "", "space": None, "active_tenant_id": _active_tenant_id()}
        return {"active_space_id": active_id, "space": _space_payload(space),
                "active_tenant_id": _active_tenant_id()}

    @app.get("/api/spaces/{space_id}")
    def api_get_space(space_id: str):
        _srv()._refresh_cloudsim_gcp_summary()
        space = _require_tenant_space(space_id)
        # LAZY TTL ENFORCEMENT (best-effort — never 500 the fetch).
        try:
            PLATFORM.expire_if_due(space_id)
            space = _require_tenant_space(space_id)
        except Exception:
            pass
        return {"space": _space_payload(space)}

    @app.post("/api/spaces")
    def api_create_space(payload: dict[str, Any]):
        spec = dict(payload or {})
        # PROVIDER LOCK (1:1): a space has exactly one provider, set at create,
        # immutable thereafter.
        provider = str(spec.get("provider") or "").strip().lower()
        if provider not in ALLOWED_PROVIDERS:
            raise HTTPException(status_code=400,
                detail=f"provider must be one of {ALLOWED_PROVIDERS}; got '{spec.get('provider')}'")
        spec["provider"] = provider
        # TENANT ASSIGNMENT: every space belongs to exactly one tenant. Default to
        # the active tenant; reject if the requested tenant doesn't exist.
        requested_tid = str(spec.get("tenant_id") or "").strip() or _active_tenant_id()
        tenant = _tenant_dict(requested_tid)
        if not tenant:
            raise HTTPException(status_code=400, detail=f"tenant '{requested_tid}' not found")
        # PER-TENANT QUOTA — tier-derived.
        from core import tier_policy as _tp
        _tier_norm = _tp.normalize_tier(tenant.get("license_tier") or "free")
        _policy_cap = _tp.policy_for(_tier_norm).get("max_spaces")
        if _policy_cap is None or _policy_cap == _tp.UNLIMITED:
            tenant_max = int((tenant.get("settings") or {}).get("max_spaces", 6))
        else:
            tenant_max = int(_policy_cap)
        tenant_spaces = sum(1 for s in (_spaces_state().get("spaces") or {}).values()
                            if isinstance(s, dict) and (s.get("tenant_id") or DEFAULT_TENANT_ID) == requested_tid)
        if _policy_cap == _tp.UNLIMITED:
            pass  # unlimited — skip the check entirely
        elif tenant_spaces >= tenant_max:
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "tier_max_spaces",
                "reason": f"{_tier_norm} tier allows {tenant_max} space(s); you have {tenant_spaces}",
                "upgrade_to": _tp._next_tier(_tier_norm),
                "active_tier": _tier_norm, "limit": tenant_max, "current": tenant_spaces,
                "docs": "https://cloudlearn.io/docs/tiers",
            })
        try:
            space = PLATFORM.create_space(spec)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Tag the new space with tenant_id
        spaces_map = _spaces_state().setdefault("spaces", {})
        if space.get("space_id") in spaces_map:
            spaces_map[space["space_id"]]["tenant_id"] = requested_tid
            space["tenant_id"] = requested_tid
        _record_usage("space.create", {"space_id": space.get("space_id"), "provider": space.get("provider"),
                                        "name": space.get("name"), "tenant_id": requested_tid})
        STATE.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})["summary"]["spaces"] = len(_spaces_state().get("spaces", {}))
        _persist_state()
        return {"message": "Simulation space created", "space": _space_payload(space)}

    @app.post("/api/spaces/estimate")
    def api_estimate_space(payload: dict[str, Any]):
        estimate = PLATFORM.estimate_space_cost(payload or {})
        return {"estimate": estimate}

    @app.post("/api/spaces/{space_id}/switch")
    def api_switch_space(space_id: str):
        _require_tenant_space(space_id)  # 404 if cross-tenant — no leak
        try:
            space = PLATFORM.switch_space(space_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.switch", {"space_id": space_id})
        return {"message": "Active space switched", "space": _space_payload(space)}

    @app.post("/api/spaces/{space_id}/pause")
    def api_pause_space(space_id: str):
        _require_tenant_space(space_id)
        try:
            space = PLATFORM.pause_space(space_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.pause", {"space_id": space_id})
        return {"message": "Simulation space paused", "space": _space_payload(space)}

    @app.post("/api/spaces/{space_id}/resume")
    def api_resume_space(space_id: str):
        _require_tenant_space(space_id)
        try:
            space = PLATFORM.resume_space(space_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.resume", {"space_id": space_id})
        return {"message": "Simulation space resumed", "space": _space_payload(space)}

    @app.post("/api/spaces/{space_id}/archive")
    def api_archive_space(space_id: str):
        _require_tenant_space(space_id)
        try:
            space = PLATFORM.archive_space(space_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.archive", {"space_id": space_id})
        return {"message": "Simulation space archived", "space": _space_payload(space)}

    @app.post("/api/spaces/{space_id}/renew")
    def api_renew_space(space_id: str, payload: dict[str, Any] | None = None):
        """Admin: reset a space's TTL. Body {"ttl_seconds": <int>} (default 8h)."""
        _require_tenant_space(space_id)
        # ADMIN GATE: TTL renewal is an admin/enterprise capability. We gate on
        # the enterprise tier (the only admin-grade tier the appliance knows).
        # TODO: swap for a dedicated is_admin/role check if/when the appliance
        # grows a real RBAC model beyond tier-based gating.
        from core import vyomi_platform as _vp
        try:
            tier = str(_active_tier() or "").strip().lower()
        except Exception:
            tier = ""
        if tier not in ("enterprise", "max"):
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "ttl_renew_admin_only",
                "reason": "renewing a space TTL requires an admin (enterprise) tier",
                "active_tier": tier or "unknown",
            })
        ttl_seconds = _vp.DEFAULT_TTL_SECONDS
        if isinstance(payload, dict) and payload.get("ttl_seconds") is not None:
            try:
                ttl_seconds = int(payload.get("ttl_seconds"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="ttl_seconds must be an integer")
        try:
            space = PLATFORM.renew_ttl(space_id, ttl_seconds)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.renew", {"space_id": space_id, "ttl_seconds": ttl_seconds})
        return {"message": "Simulation space TTL renewed", "space": _space_payload(space)}

    @app.post("/api/spaces/{space_id}/shutdown")
    def api_shutdown_space(space_id: str):
        """Force-shut-down a space (stop runtimes) and mark status=shutdown."""
        _require_tenant_space(space_id)
        try:
            space = PLATFORM.force_shutdown(space_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.shutdown", {"space_id": space_id})
        return {"message": "Simulation space shut down", "space": _space_payload(space)}

    @app.delete("/api/spaces/{space_id}")
    def api_delete_space(space_id: str):
        _require_tenant_space(space_id)
        try:
            PLATFORM.delete_space(space_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SimulationSpaceNotFound")
        _record_usage("space.delete", {"space_id": space_id})
        STATE.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})["summary"]["spaces"] = len(_spaces_state().get("spaces", {}))
        _persist_state()
        return {"message": "Simulation space deleted", "space_id": space_id}

    # ── Runtime budget ─────────────────────────────────────────────────────

    @app.get("/api/runtime/budget")
    def api_runtime_budget():
        """Simulator's container budget."""
        b = _srv()._simulator_budget()
        u = _srv()._simulator_used()
        return {
            "budget":     {"cpu": b["cpu"],       "memory_mb": b["memory_mb"]},
            "used":       u,
            "free":       {"cpu": max(0, b["cpu"] - u["cpu"]),
                           "memory_mb": max(0, b["memory_mb"] - u["memory_mb"])},
            "host":       {"cpu": b["host_cpu"],  "memory_mb": b["host_memory_mb"]},
            "budget_pct": b["budget_pct"],
            "clamp":      b["clamp"],
            "bypassed":   b["bypassed"],
        }

    # ── Cloud Shell ────────────────────────────────────────────────────────

    @app.get("/api/runtime/cloud-shell")
    def api_runtime_cloud_shell():
        """Tier-gated capability probe for the in-console Cloud Shell drawer."""
        _enforce_tier_feature("cloud_shell")
        return {
            "available": True,
            "tier": _active_tier(),
            "exec_url": "/api/runtime/cloud-shell/exec",
            "backend_status": "ready",
        }

    @app.post("/api/runtime/cloud-shell/exec")
    async def api_runtime_cloud_shell_exec(request: Request):
        """Run a single shell command from the allow-list and return its output."""
        _enforce_tier_feature("cloud_shell")
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        cmd = str(body.get("command") or "").strip()
        if not cmd:
            raise HTTPException(400, detail="command required")
        first = cmd.split(None, 1)[0]
        if first not in _CLOUD_SHELL_ALLOWED:
            raise HTTPException(403, detail={
                "ok": False, "code": "command_not_allowed",
                "reason": f"command {first!r} not in cloud-shell allow-list",
                "allowed": sorted(_CLOUD_SHELL_ALLOWED),
            })
        try:
            r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=30)
            out = {"stdout": r.stdout[-32768:], "stderr": r.stderr[-32768:], "exit_code": r.returncode}
        except subprocess.TimeoutExpired:
            out = {"stdout": "", "stderr": "timeout after 30s", "exit_code": 124}
        out["command"] = cmd
        return out

    # ── Terraform deploy targets ───────────────────────────────────────────

    @app.get("/api/runtime/terraform-deploy-targets")
    def api_runtime_terraform_deploy_targets():
        """Tier-gated list of deploy targets."""
        level = _enforce_tier_feature("terraform_deploy_to_real")
        targets = []
        if level == "single_cloud":
            targets = ["aws", "gcp", "azure"]
        elif level == "multi_cloud":
            targets = ["aws", "gcp", "azure", "multi-cloud-orchestration"]
        return {
            "available": True,
            "tier": _active_tier(),
            "level": level,
            "allowed_targets": targets,
            "backend_status": "ready",
        }

    # ── CI integration (Developer+ tier) ───────────────────────────────────

    @app.get("/api/runtime/ci/pipelines")
    def api_ci_list():
        _enforce_tier_feature("ci_integration")
        from core import ci_integration as _ci
        return {
            "tier": _active_tier(),
            "pipelines": _ci.list_pipelines(STATE, _active_tenant_id()),
        }

    @app.post("/api/runtime/ci/pipelines")
    async def api_ci_register(request: Request):
        _enforce_tier_feature("ci_integration")
        body = await request.json() if await request.body() else {}
        from core import ci_integration as _ci
        try:
            pipe = _ci.register_pipeline(STATE, _active_tenant_id(), body)
            _persist_state()
            return pipe
        except ValueError as e:
            raise HTTPException(400, detail=str(e))

    @app.delete("/api/runtime/ci/pipelines/{pipeline_id}")
    def api_ci_delete(pipeline_id: str):
        _enforce_tier_feature("ci_integration")
        from core import ci_integration as _ci
        ok = _ci.delete_pipeline(STATE, _active_tenant_id(), pipeline_id)
        if not ok:
            raise HTTPException(404, detail="pipeline not found")
        _persist_state()
        return {"deleted": pipeline_id}

    @app.post("/api/runtime/ci/pipelines/{pipeline_id}/trigger")
    async def api_ci_trigger(pipeline_id: str, request: Request):
        _enforce_tier_feature("ci_integration")
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        from core import ci_integration as _ci
        res = _ci.trigger_pipeline(STATE, _active_tenant_id(), pipeline_id, body)
        _persist_state()
        if not res["ok"] and res["result"] == "pipeline-not-found":
            raise HTTPException(404, detail=res)
        return res

    @app.post("/api/runtime/ci/webhook/{token}")
    async def api_ci_inbound_webhook(token: str, request: Request):
        """Inbound webhook — pipelines POST CI events here using their `inbound_token`.
        No tier gate (CI calling US shouldn't 403). Token is the auth."""
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {"raw": (await request.body()).decode("utf-8", errors="replace")[:4096]}
        from core import ci_integration as _ci
        result = _ci.receive_inbound(STATE, token, body)
        if not result:
            raise HTTPException(404, detail="invalid token")
        _record_usage("ci.inbound", {"pipeline_id": result["id"], "tenant_id": result["tenant_id"]})
        _persist_state()
        return {"received": True, "pipeline_id": result["id"]}
