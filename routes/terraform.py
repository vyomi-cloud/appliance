"""Terraform export, import, status, plan, apply routes extracted from server.py."""
from __future__ import annotations

import copy
from fastapi import FastAPI, Request, HTTPException
from core import app_context as ctx


def register(app: FastAPI) -> None:

    @app.get("/api/terraform/export")
    def api_terraform_export():
        from core.terraform_export import export_space_to_terraform_json
        # All tiers can export — but Free's "basic" level returns skeleton only.
        level = ctx._enforce_tier_feature("terraform_export")
        space = ctx.PLATFORM.get_active_space()
        if not isinstance(space, dict) or not space:
            raise HTTPException(404, detail="NoActiveSpace")
        export = export_space_to_terraform_json(space)
        if level == "basic":
            export = _redact_terraform_export_for_basic(export)
        if isinstance(export, dict):
            export["terraform_export_level"] = level
        ctx._record_usage(
            "terraform.export",
            {
                "space_id": export.get("space_id", ""),
                "resource_count": export.get("summary", {}).get("resource_count", 0),
                "supported_resources": export.get("summary", {}).get("supported_resources", 0),
                "unsupported_resources": export.get("summary", {}).get("unsupported_resources", 0),
                "level": level,
            },
        )
        return export

    @app.get("/__vyomi/lambda-code/{name}")
    def lambda_code_download(name: str):
        """Serves a function's original deployment package: the target of GetFunction's Code.Location."""
        import base64
        from fastapi.responses import Response
        from core import lambda_core as _lc
        from core.appliance_stores import lambda_store
        fn = _lc._find_fn(lambda_store(), _lc._norm_name(name))
        if not fn or not fn.get("code_zip"):
            raise HTTPException(404, detail="NoDeploymentPackage")
        return Response(base64.b64decode(fn["code_zip"]), media_type="application/zip")

    @app.get("/api/terraform/export/bundle")
    def api_terraform_export_bundle(format: str = "zip", region: str = ""):
        """Faithful export: the simulator's live AWS state as a Terraform bundle (HCL + variables + Lambda code) that rebuilds
        the same stack. Reads through the simulator's own AWS API, the calls Terraform's provider makes."""
        import os
        from fastapi.responses import Response
        from core.tf_export import build_aws, bundle_zip
        ctx._enforce_tier_feature("terraform_export")
        endpoint = os.environ.get("VYOMI_INTERNAL_ENDPOINT", "http://127.0.0.1:9000")
        result = build_aws(endpoint, region or "us-east-1")
        ctx._record_usage("terraform.export_bundle", {"resource_count": result["summary"]["resources"]})
        if format == "json":
            return {"files": result["files"], "summary": result["summary"]}
        return Response(bundle_zip(result), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="vyomi-terraform-export.zip"'})

    @app.post("/api/terraform/import")
    async def api_terraform_import(request: Request):
        from core.terraform_export import export_space_to_terraform_json
        from core.terraform_workflow import terraform_import_bundle
        # Terraform import is gated to `full_plus_import` (Enterprise only)
        ctx._enforce_tier_feature("terraform_export", min_level="full_plus_import")
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(400, detail="InvalidTerraformImportPayload")

        spaces_state = ctx._spaces_state()
        active_id = str(spaces_state.get("active_space_id", "") or "").strip()
        if not active_id:
            raise HTTPException(404, detail="NoActiveSpace")
        space = spaces_state.get("spaces", {}).get(active_id)
        if not isinstance(space, dict):
            raise HTTPException(404, detail="NoActiveSpace")

        terraform_json = {}
        if isinstance(payload.get("terraform_json"), dict):
            terraform_json = payload["terraform_json"]
        elif isinstance(payload.get("resource"), dict):
            terraform_json = payload
        elif isinstance(payload.get("bundle"), dict):
            terraform_json = payload["bundle"].get("terraform_json") if isinstance(payload["bundle"], dict) else {}
            if not isinstance(terraform_json, dict):
                terraform_json = payload["bundle"] if isinstance(payload["bundle"], dict) else {}

        if not isinstance(terraform_json, dict) or not isinstance(terraform_json.get("resource"), dict) or not terraform_json.get("resource"):
            raise HTTPException(400, detail="InvalidTerraformImportPayload")

        import_result = terraform_import_bundle(payload, space)
        service_state_updates = import_result.get("service_state_updates", {})
        if not isinstance(service_state_updates, dict):
            service_state_updates = {}

        service_states = space.setdefault("service_states", {})
        if not isinstance(service_states, dict):
            service_states = {}
            space["service_states"] = service_states
        for service_key, service_state in service_state_updates.items():
            service_states[service_key] = copy.deepcopy(service_state)

        now = ctx._now()
        space["updated_at"] = now
        space.setdefault("cloudsim", {}).setdefault("summary", {})

        import_id = ctx._id("tfimport")
        target_space_id = active_id
        source_space_id = str(import_result.get("space_id") or "")
        target_space_name = str(space.get("name") or "").strip()
        target_provider = str(space.get("provider") or "").strip()
        record = {
            "import_id": import_id,
            "space_id": target_space_id,
            "space_name": target_space_name,
            "provider": target_provider,
            "created_at": now,
            "workflow_kind": "import",
            "source_space_id": source_space_id,
            "source_space_name": import_result.get("space_name", ""),
            "source_provider": import_result.get("provider", ""),
            "summary": copy.deepcopy(import_result.get("summary", {})),
            "imported_resources": copy.deepcopy(import_result.get("imported_resources", [])),
            "unsupported_resources": copy.deepcopy(import_result.get("unsupported_resources", [])),
            "service_keys": copy.deepcopy(import_result.get("service_keys", [])),
            "status": "imported",
        }

        terraform_state = ctx._terraform_state()
        terraform_state.setdefault("imports", {})[import_id] = copy.deepcopy(record)
        space_state = ctx._terraform_space_state(target_space_id)
        space_state.setdefault("imports", {})[import_id] = copy.deepcopy(record)
        space_state["last_import"] = copy.deepcopy(record)

        ctx._record_usage(
            "terraform.import",
            {
                "space_id": target_space_id,
                "import_id": import_id,
                "resource_count": import_result.get("summary", {}).get("resource_count", 0),
                "supported_resources": import_result.get("summary", {}).get("supported_resources", 0),
                "unsupported_resources": import_result.get("summary", {}).get("unsupported_resources", 0),
                "service_keys": copy.deepcopy(import_result.get("service_keys", [])),
            },
        )
        ctx._persist_state()

        return {
            **record,
            "terraform_json": import_result.get("terraform_json", {}),
            "service_state_updates": service_state_updates,
            "nodes": import_result.get("nodes", []),
            "resource_count": import_result.get("resource_count", 0),
            "supported_resources": import_result.get("supported_resources", 0),
            "unsupported_resources": copy.deepcopy(import_result.get("unsupported_resources", [])),
        }

    @app.get("/api/terraform/status")
    def api_terraform_status():
        from core.terraform_export import export_space_to_terraform_json
        from core.terraform_workflow import (
            terraform_cli_available, terraform_cli_path,
            terraform_workspace_root, terraform_space_dir,
        )
        space = ctx.PLATFORM.get_active_space()
        if not isinstance(space, dict) or not space:
            raise HTTPException(404, detail="NoActiveSpace")
        export = export_space_to_terraform_json(space)
        space_id = export.get("space_id") or _string(space.get("space_id"), "")
        terraform_state = ctx._terraform_state()
        space_state = ctx._terraform_space_state(space_id)
        last_plan = {}
        last_apply = {}
        if isinstance(space_state.get("last_plan"), dict):
            last_plan = copy.deepcopy(space_state["last_plan"])
        if isinstance(space_state.get("last_apply"), dict):
            last_apply = copy.deepcopy(space_state["last_apply"])
        last_import = {}
        if isinstance(space_state.get("last_import"), dict):
            last_import = copy.deepcopy(space_state["last_import"])
        return {
            "space_id": space_id,
            "space_name": export.get("space_name", ""),
            "provider": export.get("provider", ""),
            "summary": export.get("summary", {}),
            "terraform_cli_available": terraform_cli_available(),
            "terraform_cli_path": terraform_cli_path() or "",
            "terraform_workspace_root": str(terraform_workspace_root()),
            "workspace_dir": str(terraform_space_dir(space_id)),
            "last_plan": last_plan,
            "last_apply": last_apply,
            "last_import": last_import,
            "plan_count": len(terraform_state.get("plans", {})),
            "apply_count": len(terraform_state.get("applies", {})),
            "import_count": len(terraform_state.get("imports", {})),
        }

    @app.post("/api/terraform/plan")
    def api_terraform_plan():
        from core.terraform_export import export_space_to_terraform_json
        from core.terraform_workflow import (
            build_plan_summary as terraform_build_plan_summary,
            stage_workflow_bundle as terraform_stage_workflow_bundle,
            run_terraform_cli as terraform_run_cli,
        )
        space = ctx.PLATFORM.get_active_space()
        if not isinstance(space, dict) or not space:
            raise HTTPException(404, detail="NoActiveSpace")
        export = export_space_to_terraform_json(space)
        space_id = export.get("space_id") or _string(space.get("space_id"), "")
        space_state = ctx._terraform_space_state(space_id)
        previous = space_state.get("last_apply") if isinstance(space_state.get("last_apply"), dict) else {}
        summary = terraform_build_plan_summary(export, previous)
        workflow_id = ctx._id("tfplan")
        stage = terraform_stage_workflow_bundle(export, workflow_id, "plan", summary)
        execution = terraform_run_cli(stage["stage_dir"], "plan")
        if not execution.get("available"):
            execution = {
                **execution,
                "status": "simulated",
                "stdout": execution.get("error", "Terraform CLI is not installed on this runtime."),
                "stderr": "",
                "exit_code": 0,
            }
        record = {
            "plan_id": workflow_id,
            "space_id": space_id,
            "space_name": export.get("space_name", ""),
            "provider": export.get("provider", ""),
            "created_at": ctx._now(),
            "workflow_kind": "plan",
            "stage_dir": stage["stage_dir"],
            "files": stage["files"],
            "terraform_cli_available": stage["terraform_cli_available"],
            "terraform_cli_path": stage["terraform_cli_path"],
            "summary": export.get("summary", {}),
            "plan_summary": summary,
            "unsupported_resources": copy.deepcopy(export.get("unsupported_resources", [])),
            "execution": execution,
        }
        terraform_state = ctx._terraform_state()
        terraform_state.setdefault("plans", {})[workflow_id] = record
        space_state.setdefault("plans", {})[workflow_id] = copy.deepcopy(record)
        space_state["last_plan"] = copy.deepcopy(record)
        ctx._record_usage(
            "terraform.plan",
            {
                "space_id": space_id,
                "plan_id": workflow_id,
                "resource_count": export.get("summary", {}).get("resource_count", 0),
                "supported_resources": export.get("summary", {}).get("supported_resources", 0),
                "unsupported_resources": export.get("summary", {}).get("unsupported_resources", 0),
            },
        )
        ctx._persist_state()
        return record

    @app.post("/api/terraform/apply")
    async def api_terraform_apply(request: Request):
        from core.terraform_export import export_space_to_terraform_json
        from core.terraform_workflow import (
            build_plan_summary as terraform_build_plan_summary,
            stage_workflow_bundle as terraform_stage_workflow_bundle,
            run_terraform_cli as terraform_run_cli,
        )
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        plan_id = str((payload or {}).get("plan_id") or "").strip()
        confirm = bool((payload or {}).get("confirm", False))
        if not confirm:
            raise HTTPException(status_code=400, detail="ConfirmationRequired")

        terraform_state = ctx._terraform_state()
        plan_record = terraform_state.get("plans", {}).get(plan_id) if plan_id else None

        space = ctx.PLATFORM.get_active_space()
        if not isinstance(space, dict) or not space:
            raise HTTPException(404, detail="NoActiveSpace")
        export = export_space_to_terraform_json(space)
        space_id = export.get("space_id") or _string(space.get("space_id"), "")
        space_state = ctx._terraform_space_state(space_id)

        if not plan_record:
            previous = space_state.get("last_apply") if isinstance(space_state.get("last_apply"), dict) else {}
            summary = terraform_build_plan_summary(export, previous)
            plan_id = ctx._id("tfplan")
            stage = terraform_stage_workflow_bundle(export, plan_id, "apply", summary)
            plan_record = {
                "plan_id": plan_id,
                "space_id": space_id,
                "space_name": export.get("space_name", ""),
                "provider": export.get("provider", ""),
                "created_at": ctx._now(),
                "workflow_kind": "apply",
                "stage_dir": stage["stage_dir"],
                "files": stage["files"],
                "terraform_cli_available": stage["terraform_cli_available"],
                "terraform_cli_path": stage["terraform_cli_path"],
                "summary": export.get("summary", {}),
                "plan_summary": summary,
                "unsupported_resources": copy.deepcopy(export.get("unsupported_resources", [])),
            }
            terraform_state.setdefault("plans", {})[plan_id] = plan_record
            space_state.setdefault("plans", {})[plan_id] = copy.deepcopy(plan_record)
        else:
            plan_record = copy.deepcopy(plan_record)

        execution = terraform_run_cli(plan_record.get("stage_dir", ""), "apply")
        if not execution.get("available"):
            execution = {
                **execution,
                "status": "simulated",
                "stdout": execution.get("error", "Terraform CLI is not installed on this runtime."),
                "stderr": "",
                "exit_code": 0,
            }

        apply_id = ctx._id("tfapply")
        apply_record = {
            "apply_id": apply_id,
            "plan_id": plan_id,
            "space_id": space_id,
            "space_name": export.get("space_name", ""),
            "provider": export.get("provider", ""),
            "created_at": ctx._now(),
            "workflow_kind": "apply",
            "stage_dir": plan_record.get("stage_dir", ""),
            "files": plan_record.get("files", []),
            "terraform_cli_available": plan_record.get("terraform_cli_available", False),
            "terraform_cli_path": plan_record.get("terraform_cli_path", ""),
            "summary": export.get("summary", {}),
            "plan_summary": plan_record.get("plan_summary", {}),
            "unsupported_resources": copy.deepcopy(export.get("unsupported_resources", [])),
            "execution": execution,
        }
        terraform_state.setdefault("applies", {})[apply_id] = apply_record
        space_state.setdefault("applies", {})[apply_id] = copy.deepcopy(apply_record)
        space_state["last_apply"] = copy.deepcopy({
            "apply_id": apply_id,
            "plan_id": plan_id,
            "space_id": space_id,
            "space_name": export.get("space_name", ""),
            "provider": export.get("provider", ""),
            "created_at": ctx._now(),
            "resource_index": plan_record.get("plan_summary", {}).get("resource_index", {}),
            "fingerprint": plan_record.get("plan_summary", {}).get("fingerprint", ""),
        })
        ctx._record_usage(
            "terraform.apply",
            {
                "space_id": space_id,
                "plan_id": plan_id,
                "apply_id": apply_id,
                "resource_count": export.get("summary", {}).get("resource_count", 0),
                "supported_resources": export.get("summary", {}).get("supported_resources", 0),
                "unsupported_resources": export.get("summary", {}).get("unsupported_resources", 0),
            },
        )
        ctx._persist_state()
        return apply_record


def _string(value, fallback: str = "") -> str:
    """Safe string coercion (mirrors core.terraform_workflow._string)."""
    if value is None:
        return fallback
    return str(value) or fallback


def _redact_terraform_export_for_basic(export: dict) -> dict:
    """Free-tier `terraform_export=basic` returns only the resource skeleton."""
    if not isinstance(export, dict):
        return export
    redacted = copy.deepcopy(export)
    tf = redacted.get("terraform_json") if isinstance(redacted.get("terraform_json"), dict) else None
    if isinstance(tf, dict):
        tf.pop("variable", None)
        tf.pop("provider", None)
        tf.pop("output", None)
    redacted.pop("unsupported_resources", None)
    redacted.setdefault("summary", {})["redacted_for_basic_tier"] = True
    return redacted
