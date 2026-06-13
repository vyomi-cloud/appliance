"""Licensing, catalog, packs, providers, host info, budget toggle, and cost budget alert routes."""
from __future__ import annotations

import copy
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from core import app_context as ctx


def _get_current_spend() -> float:
    """Return current simulated cloud spend (real_cloud_cost_usd) from the
    active space's cost_savings. This is what the user WOULD have spent."""
    try:
        spaces = ctx.STATE.get("spaces", {}).get("spaces", {})
        active_id = ctx.STATE.get("spaces", {}).get("active_space_id", "")
        space = spaces.get(active_id, {}) if active_id else {}
        if isinstance(space, dict):
            return float(space.get("cost_savings", {}).get("real_cloud_cost_usd", 0.0) or 0.0)
    except Exception:
        pass
    return 0.0


def _check_budget_alerts() -> None:
    """Check all budgets against current spend and fire notifications for any
    newly breached thresholds. Called from _cloudsim_refresh_bridge."""
    budgets = ctx.STATE.get("budgets", {})
    if not budgets:
        return
    current_spend = _get_current_spend()
    for budget_id, budget in budgets.items():
        if not isinstance(budget, dict):
            continue
        amount = budget.get("amount_usd", 0)
        if not amount:
            continue
        utilization_pct = round((current_spend / amount) * 100, 2)
        already_triggered = {a.get("threshold") for a in budget.get("alerts_triggered", []) if isinstance(a, dict)}
        for threshold in budget.get("alert_thresholds", []):
            if utilization_pct >= threshold and threshold not in already_triggered:
                alert_record = {
                    "threshold": threshold,
                    "utilization_pct": utilization_pct,
                    "current_spend_usd": current_spend,
                    "amount_usd": amount,
                    "triggered_at": ctx.now(),
                }
                budget.setdefault("alerts_triggered", []).append(alert_record)
                # Fire notification via core.notifications.emit()
                try:
                    from core import notifications as _nt
                    _nt.emit(ctx.STATE, ctx.active_tenant_id(), "budget.threshold_breached", {
                        "budget_id": budget_id,
                        "budget_name": budget.get("name", ""),
                        "threshold_pct": threshold,
                        "utilization_pct": utilization_pct,
                        "current_spend_usd": current_spend,
                        "amount_usd": amount,
                    })
                except Exception:
                    pass
    try:
        ctx.persist_state()
    except Exception:
        pass


def register(app: FastAPI) -> None:

    # ── Catalog ───────────────────────────────────────────────────────────

    @app.get("/api/catalog")
    def api_catalog():
        import server
        return server.api_catalog()

    # ── Packs ─────────────────────────────────────────────────────────────

    @app.get("/api/packs")
    def api_list_packs():
        import server
        return {"packs": server._catalog(), "count": len(ctx.STATE["packs"])}

    @app.get("/api/providers/{provider}/packs")
    def api_list_provider_packs(provider: str):
        from core.provider_registry import normalize_provider as normalize_provider_key
        from core.pack_catalog import PROVIDER_PACK_GROUPS, packs_for_provider
        provider_key = normalize_provider_key(provider)
        packs = packs_for_provider(provider_key) if provider_key in PROVIDER_PACK_GROUPS else []
        return {
            "provider": provider_key,
            "packs": packs,
            "count": len(packs),
        }

    @app.get("/api/providers/{provider}/matrix")
    def api_provider_matrix(provider: str):
        from core.provider_registry import normalize_provider as normalize_provider_key, get_provider, provider_matrix
        from core.pack_catalog import PROVIDER_PACK_GROUPS, packs_for_provider
        from providers.capabilities import provider_capabilities, provider_services
        provider_key = normalize_provider_key(provider)
        if provider_key in {"aws", "gcp", "azure"}:
            matrix = provider_capabilities(provider_key)
        else:
            provider_payload = get_provider(provider_key)
            packs = packs_for_provider(provider_key) if provider_key in PROVIDER_PACK_GROUPS else []
            matrix = provider_matrix(provider_key, packs)
            matrix["surface"] = provider_payload.get("surface", matrix.get("surface", {}))
            matrix["navigation"] = provider_payload.get("navigation", matrix.get("navigation", {}))
            matrix["native_services"] = provider_payload.get("native_services", matrix.get("native_services", []))
            matrix["space_facts"] = provider_payload.get("space_facts", matrix.get("space_facts", []))
            matrix["tooling"] = provider_payload.get("tooling", matrix.get("tooling", {}))
            matrix["gaps"] = provider_payload.get("gaps", matrix.get("gaps", []))
        packs = packs_for_provider(provider_key) if provider_key in PROVIDER_PACK_GROUPS else []
        services = provider_services(provider_key)
        return {
            "provider": provider_key,
            "surface": matrix.get("surface", {}),
            "navigation": matrix.get("navigation", {}),
            "native_services": matrix.get("native_services", []),
            "space_facts": matrix.get("space_facts", []),
            "tooling": matrix.get("tooling", {}),
            "services": matrix.get("services", services.get("services", [])),
            "service_counts": matrix.get("service_counts", {"total": services.get("count", 0), "integrated": services.get("integrated", 0), "partial": services.get("partial", 0)}),
            "packs": {
                "service": [copy.deepcopy(pack) for pack in packs if pack.get("type") == "service"],
                "runtime": [copy.deepcopy(pack) for pack in packs if pack.get("type") == "runtime"],
                "tooling": [copy.deepcopy(pack) for pack in packs if pack.get("type") == "tooling"],
            },
            "gaps": matrix.get("gaps", []),
        }

    @app.get("/api/providers/{provider}/services")
    def api_provider_services(provider: str):
        from providers.capabilities import provider_services
        return provider_services(provider)

    @app.get("/api/providers/{provider}/capabilities")
    def api_provider_capabilities(provider: str):
        from providers.capabilities import provider_capabilities
        return provider_capabilities(provider)

    # ── AWS tooling ───────────────────────────────────────────────────────

    @app.get("/api/providers/aws/cli")
    def api_provider_aws_cli():
        from providers.aws import tool_response as aws_tool_response
        return aws_tool_response("cli")

    @app.get("/api/providers/aws/sdk/java")
    def api_provider_aws_sdk_java():
        from providers.aws import tool_response as aws_tool_response
        return aws_tool_response("sdk/java")

    @app.get("/api/providers/aws/sdk/go")
    def api_provider_aws_sdk_go():
        from providers.aws import tool_response as aws_tool_response
        return aws_tool_response("sdk/go")

    @app.get("/api/providers/aws/sdk/python")
    def api_provider_aws_sdk_python():
        from providers.aws import tool_response as aws_tool_response
        return aws_tool_response("sdk/python")

    @app.get("/api/providers/aws/sdk/nodejs")
    def api_provider_aws_sdk_nodejs():
        from providers.aws import tool_response as aws_tool_response
        return aws_tool_response("sdk/nodejs")

    @app.post("/api/providers/aws/cli/resolve")
    def api_provider_aws_cli_resolve(payload: dict[str, Any]):
        from core.tooling_simulators import aws_cli_resolve
        return aws_cli_resolve(str(payload.get("command", "")))

    @app.get("/api/providers/aws/sdk/java/snippet")
    def api_provider_aws_sdk_java_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("aws", "java")

    @app.get("/api/providers/aws/sdk/go/snippet")
    def api_provider_aws_sdk_go_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("aws", "go")

    @app.get("/api/providers/aws/sdk/python/snippet")
    def api_provider_aws_sdk_python_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("aws", "python")

    @app.get("/api/providers/aws/sdk/nodejs/snippet")
    def api_provider_aws_sdk_nodejs_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("aws", "nodejs")

    # ── GCP tooling ───────────────────────────────────────────────────────

    @app.get("/api/providers/gcp/gcloud")
    def api_provider_gcp_gcloud():
        from providers.gcp import tool_response as gcp_tool_response
        return gcp_tool_response("gcloud")

    @app.get("/api/providers/gcp/gcutil")
    def api_provider_gcp_gcutil():
        from providers.gcp import tool_response as gcp_tool_response
        return gcp_tool_response("gcutil")

    @app.get("/api/providers/gcp/sdk/java")
    def api_provider_gcp_sdk_java():
        from providers.gcp import tool_response as gcp_tool_response
        return gcp_tool_response("sdk/java")

    @app.get("/api/providers/gcp/sdk/go")
    def api_provider_gcp_sdk_go():
        from providers.gcp import tool_response as gcp_tool_response
        return gcp_tool_response("sdk/go")

    @app.get("/api/providers/gcp/sdk/python")
    def api_provider_gcp_sdk_python():
        from providers.gcp import tool_response as gcp_tool_response
        return gcp_tool_response("sdk/python")

    @app.get("/api/providers/gcp/sdk/nodejs")
    def api_provider_gcp_sdk_nodejs():
        from providers.gcp import tool_response as gcp_tool_response
        return gcp_tool_response("sdk/nodejs")

    @app.post("/api/providers/gcp/gcloud/resolve")
    def api_provider_gcp_gcloud_resolve(payload: dict[str, Any]):
        from providers.gcp_routes import gcloud_resolve as gcp_gcloud_resolve
        return gcp_gcloud_resolve(payload)

    @app.post("/api/providers/gcp/gcutil/resolve")
    def api_provider_gcp_gcutil_resolve(payload: dict[str, Any]):
        from providers.gcp_routes import gcutil_resolve as gcp_gcutil_resolve
        return gcp_gcutil_resolve(payload)

    @app.get("/api/providers/gcp/sdk/java/snippet")
    def api_provider_gcp_sdk_java_snippet():
        from providers.gcp_routes import sdk_java_snippet as gcp_sdk_java_snippet
        return gcp_sdk_java_snippet()

    @app.get("/api/providers/gcp/sdk/go/snippet")
    def api_provider_gcp_sdk_go_snippet():
        from providers.gcp_routes import sdk_go_snippet as gcp_sdk_go_snippet
        return gcp_sdk_go_snippet()

    @app.get("/api/providers/gcp/sdk/python/snippet")
    def api_provider_gcp_sdk_python_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("gcp", "python")

    @app.get("/api/providers/gcp/sdk/nodejs/snippet")
    def api_provider_gcp_sdk_nodejs_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("gcp", "nodejs")

    # ── Azure tooling ─────────────────────────────────────────────────────

    @app.get("/api/providers/azure/cli")
    def api_provider_azure_cli():
        from providers import azure_tool_response
        return azure_tool_response("cli")

    @app.get("/api/providers/azure/sdk/java")
    def api_provider_azure_sdk_java():
        from providers import azure_tool_response
        return azure_tool_response("sdk/java")

    @app.get("/api/providers/azure/sdk/go")
    def api_provider_azure_sdk_go():
        from providers import azure_tool_response
        return azure_tool_response("sdk/go")

    @app.get("/api/providers/azure/sdk/python")
    def api_provider_azure_sdk_python():
        from providers import azure_tool_response
        return azure_tool_response("sdk/python")

    @app.get("/api/providers/azure/sdk/nodejs")
    def api_provider_azure_sdk_nodejs():
        from providers import azure_tool_response
        return azure_tool_response("sdk/nodejs")

    @app.post("/api/providers/azure/cli/resolve")
    def api_provider_azure_cli_resolve(payload: dict[str, Any]):
        from core.tooling_simulators import az_cli_resolve
        return az_cli_resolve(str(payload.get("command", "")))

    @app.get("/api/providers/azure/sdk/java/snippet")
    def api_provider_azure_sdk_java_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("azure", "java")

    @app.get("/api/providers/azure/sdk/go/snippet")
    def api_provider_azure_sdk_go_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("azure", "go")

    @app.get("/api/providers/azure/sdk/python/snippet")
    def api_provider_azure_sdk_python_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("azure", "python")

    @app.get("/api/providers/azure/sdk/nodejs/snippet")
    def api_provider_azure_sdk_nodejs_snippet():
        from core.tooling_simulators import sdk_snippet
        return sdk_snippet("azure", "nodejs")

    # ── Pack fragment / activate ──────────────────────────────────────────

    @app.get("/api/packs/{pack_id}/fragment")
    def api_pack_fragment(pack_id: str):
        from core.pack_catalog import fragment_for_pack
        try:
            fragment = fragment_for_pack(pack_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="PackNotFound")
        return Response(content=fragment, media_type="text/html; charset=utf-8")

    @app.post("/api/packs/{pack_id}/activate")
    def api_activate_pack(pack_id: str):
        import server
        pack = server._activate_pack(pack_id)
        ctx._record_usage("pack.activate", {"pack_id": pack_id})
        return {"message": "Pack activated", "pack": pack}

    # ── Host info ─────────────────────────────────────────────────────────

    @app.get("/api/host/cpu")
    def api_host_cpu():
        import server
        return server._sample_host_cpu_metrics()

    @app.get("/api/host/sizing")
    def api_host_sizing():
        import server
        return server._host_sizing()

    # ── Instance catalog ──────────────────────────────────────────────────

    @app.get("/api/instances/catalog")
    def api_instances_catalog(provider: str = "aws"):
        """Single source-of-truth catalog of instance types the simulator understands."""
        from core import instance_catalog as cat
        table = {"aws": cat.AWS, "gcp": cat.GCP, "azure": cat.AZURE}.get(str(provider).lower(), {})
        items = [{**shape, "name": name} for name, shape in table.items()]
        items.sort(key=lambda i: (i.get("family", ""), i.get("vcpu", 0), i.get("ram_mb", 0)))
        return {"provider": str(provider).lower(), "count": len(items), "instances": items}

    # ── License signup / status / switch-cloud / activate ─────────────────

    @app.post("/api/license/signup")
    def api_license_signup(req):
        if ctx.appliance_mode_enabled():
            raise HTTPException(status_code=403, detail={
                "ok": False, "code": "appliance_mode",
                "reason": "Dev-mode signup is disabled in appliance mode. Use /api/license/activate or /api/auth/start-activation.",
            })
        import server
        return server.api_license_signup(req)

    @app.get("/api/license/status")
    def api_license_status():
        import os
        from core import tier_policy as _tp
        from core import license_remote as _lr
        from datetime import datetime, timezone as _tz
        lic = dict(ctx.STATE.get("license") or {})
        try:
            tenant = ctx._tenant_dict(ctx._active_tenant_id()) or {}
        except Exception:
            tenant = {}
        active_tier = _normalize_tier(tenant.get("license_tier") or lic.get("tier") or "free")
        policy = _tp.policy_for(active_tier)
        primary_cloud = str(tenant.get("primary_cloud") or "")
        expires_at = tenant.get("license_expires_at") or lic.get("expires_at") or ""
        grace_until = tenant.get("license_grace_until") or lic.get("grace_until") or ""

        days_until_expiry = None
        in_grace = False
        if expires_at:
            try:
                exp = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
                now = datetime.now(_tz.utc)
                days_until_expiry = max(0, (exp - now).days)
                if now > exp and grace_until:
                    grace_end = datetime.strptime(grace_until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
                    in_grace = now < grace_end
            except Exception:
                pass

        # Phase 5 subscription coupling fields \u2014 read from the cached JWT
        # claims. These are what the SPA pill renders: hard cutoff date,
        # days-until-deactivation countdown, cancel-in-grace banner, and
        # refresh-loop health for the green/yellow/red dot.
        claims = ctx.STATE.get("license_claims") or {}
        sub_expires_at = claims.get("sub_expires_at")
        days_until_sub_expiry = _lr.days_until_sub_expiry(claims)
        sub_expired = _lr.is_sub_expired(claims)
        cancel_at_period_end = bool(claims.get("cancel_at_period_end"))
        refresh_status = {
            "last_refresh_at":          ctx.STATE.get("license_last_refresh_at"),
            "last_refresh_attempted":   ctx.STATE.get("license_last_refresh_attempted_at"),
            "last_refresh_status":      ctx.STATE.get("license_last_refresh_status"),
            "refresh_interval_seconds": int(os.environ.get(
                "CLOUDLEARN_LICENSE_REFRESH_INTERVAL_SECONDS", str(24 * 3600))),
        }

        return {
            "active_tier":            active_tier,
            "primary_cloud":          primary_cloud,
            "period":                 tenant.get("license_period") or lic.get("period") or "monthly",
            "seats":                  int(tenant.get("license_seats") or lic.get("seats") or 1),
            "expires_at":             expires_at,
            "grace_until":            grace_until,
            "days_until_expiry":      days_until_expiry,
            "in_grace_period":        in_grace,
            "sub_expires_at":         sub_expires_at,
            "days_until_sub_expiry":  days_until_sub_expiry,
            "sub_expired":            sub_expired,
            "cancel_at_period_end":   cancel_at_period_end,
            "refresh_status":         refresh_status,
            "price_inr_monthly":      policy.get("price_inr_monthly"),
            "price_inr_annual":       policy.get("price_inr_annual"),
            "currency":               "INR",
            "currency_symbol":        "\u20b9",
            "license":                lic,
        }

    @app.post("/api/license/switch-cloud")
    def api_license_switch_cloud(payload: dict[str, Any]):
        """Student tier: change the primary_cloud."""
        from core import tier_policy as _tp
        from datetime import datetime, timedelta, timezone as _tz
        new_cloud = str(payload.get("primary_cloud", "")).lower().strip()
        if new_cloud not in {"aws", "gcp", "azure"}:
            raise HTTPException(status_code=400, detail={
                "ok": False, "code": "invalid_cloud",
                "reason": "primary_cloud must be one of aws|gcp|azure",
            })
        tenant = ctx._tenant_dict(ctx._active_tenant_id()) or {}
        tier = _normalize_tier(tenant.get("license_tier") or "free")
        p = _tp.policy_for(tier)
        if not p.get("primary_cloud_required"):
            raise HTTPException(status_code=400, detail={
                "ok": False, "code": "not_applicable",
                "reason": f"{tier} tier has access to all clouds; primary_cloud not used",
            })
        last = tenant.get("primary_cloud_changed_at")
        if last:
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=_tz.utc)
                elapsed = datetime.now(_tz.utc) - last_dt
                if elapsed < timedelta(days=365):
                    days_left = 365 - elapsed.days
                    raise HTTPException(status_code=429, detail={
                        "ok": False, "code": "rate_limited",
                        "reason": f"primary_cloud can be changed once per year; try again in {days_left} day(s)",
                        "days_until_next_change": days_left,
                        "upgrade_to": "developer",
                        "current_primary_cloud": tenant.get("primary_cloud", ""),
                    })
            except HTTPException:
                raise
            except Exception:
                pass
        tenants_state = ctx._tenants_state()
        tenant_rec = tenants_state.setdefault("tenants", {}).setdefault(ctx._active_tenant_id(), {})
        old = tenant_rec.get("primary_cloud", "")
        tenant_rec["primary_cloud"] = new_cloud
        tenant_rec["primary_cloud_changed_at"] = ctx._now()
        ctx._persist_state()
        return {
            "ok": True, "old_primary_cloud": old, "new_primary_cloud": new_cloud,
            "next_change_allowed_after_days": 365,
        }

    @app.get("/api/runtime/tier", include_in_schema=False)
    def api_runtime_tier():
        """Surface the full per-tier policy table + the active license's tier."""
        from core import tier_policy as _tp
        try:
            tenant = ctx._tenant_dict(ctx._active_tenant_id())
        except Exception:
            tenant = {}
        active_tier = _normalize_tier(
            (tenant or {}).get("license_tier")
            or (ctx.STATE.get("license") or {}).get("tier")
            or "free"
        )
        return {
            "active_tier":   active_tier,
            "active_policy": _tp.policy_for(active_tier),
            "primary_cloud": (tenant or {}).get("primary_cloud", ""),
            "all_tiers":     _tp.all_tiers(),
            "currency":      "INR",
            "_meta": {
                "doc": "https://cloudlearn.io/docs/tiers",
                "tiers_known": list(_tp.KNOWN_TIERS),
            },
        }

    @app.post("/api/license/activate")
    def api_license_activate(payload: dict[str, Any], request: Request):
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        import server
        token = payload.get("token", "")
        license_data = server._verify_license(token)
        license_data["token"] = token
        ctx.STATE["license"] = license_data
        ctx._persist_state()
        return {"message": "License activated", "license": license_data}

    # ── Budget toggles ────────────────────────────────────────────────────

    @app.post("/api/runtime/budget/disable", include_in_schema=False)
    def api_runtime_budget_disable(request: Request):
        """Testing toggle: bypass the host-clamp gate."""
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        if ctx.appliance_mode_enabled():
            raise HTTPException(status_code=403, detail="Budget bypass disabled in appliance mode")
        import server
        server._BUDGET_BYPASSED = True
        return {"bypassed": True, "message": "Budget gate disabled. Re-enable via POST /api/runtime/budget/enable."}

    @app.post("/api/runtime/budget/enable", include_in_schema=False)
    def api_runtime_budget_enable(request: Request):
        """Re-enable the host-clamp gate (undo /disable)."""
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        if ctx.appliance_mode_enabled():
            raise HTTPException(status_code=403, detail="Budget bypass disabled in appliance mode")
        import server
        server._BUDGET_BYPASSED = False
        return {"bypassed": False, "message": "Budget gate re-enabled."}

    # ── Cost Budget Alerts ───────────────────────────────────────────────

    @app.post("/api/runtime/budgets", include_in_schema=False)
    async def api_cost_budget_create(request: Request):
        """Create a cost budget with alert thresholds."""
        import uuid
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        name = str(body.get("name", "")).strip() or "default"
        amount_usd = float(body.get("amount_usd", 100.0) or 100.0)
        period = str(body.get("period", "monthly")).strip() or "monthly"
        alert_thresholds = body.get("alert_thresholds") or [50, 80, 100]
        if not isinstance(alert_thresholds, list):
            alert_thresholds = [50, 80, 100]
        alert_thresholds = sorted(set(int(t) for t in alert_thresholds if isinstance(t, (int, float)) and 0 < t <= 200))
        budget_id = f"budget-{uuid.uuid4().hex[:12]}"
        budgets = ctx.STATE.setdefault("budgets", {})
        budget = {
            "budget_id": budget_id,
            "name": name,
            "amount_usd": amount_usd,
            "period": period,
            "alert_thresholds": alert_thresholds,
            "alerts_triggered": [],
            "created_at": ctx.now(),
        }
        budgets[budget_id] = budget
        ctx.persist_state()
        return {"ok": True, "budget": budget}

    @app.get("/api/runtime/budgets", include_in_schema=False)
    def api_cost_budget_list():
        """List all cost budgets with current spend."""
        budgets = ctx.STATE.get("budgets", {})
        # Compute current spend from active space cost_savings.
        current_spend = _get_current_spend()
        results = []
        for bid, b in budgets.items():
            if not isinstance(b, dict):
                continue
            entry = copy.deepcopy(b)
            entry["current_spend_usd"] = current_spend
            entry["utilization_pct"] = round((current_spend / b["amount_usd"]) * 100, 2) if b.get("amount_usd") else 0.0
            results.append(entry)
        return {"budgets": results, "count": len(results), "current_spend_usd": current_spend}

    @app.delete("/api/runtime/budgets/{budget_id}", include_in_schema=False)
    def api_cost_budget_delete(budget_id: str):
        """Delete a cost budget."""
        budgets = ctx.STATE.setdefault("budgets", {})
        if budget_id not in budgets:
            from fastapi import HTTPException as _HE
            raise _HE(404, detail="BudgetNotFound")
        budgets.pop(budget_id)
        ctx.persist_state()
        return {"deleted": True, "budget_id": budget_id}

    @app.get("/api/runtime/budgets/{budget_id}/status", include_in_schema=False)
    def api_cost_budget_status(budget_id: str):
        """Get budget status including current spend vs amount and alerts triggered."""
        budgets = ctx.STATE.get("budgets", {})
        budget = budgets.get(budget_id)
        if not isinstance(budget, dict):
            from fastapi import HTTPException as _HE
            raise _HE(404, detail="BudgetNotFound")
        current_spend = _get_current_spend()
        utilization_pct = round((current_spend / budget["amount_usd"]) * 100, 2) if budget.get("amount_usd") else 0.0
        # Determine which thresholds have been breached.
        breached = [t for t in budget.get("alert_thresholds", []) if utilization_pct >= t]
        return {
            "budget_id": budget_id,
            "name": budget.get("name", ""),
            "amount_usd": budget.get("amount_usd", 0),
            "current_spend_usd": current_spend,
            "utilization_pct": utilization_pct,
            "period": budget.get("period", "monthly"),
            "alert_thresholds": budget.get("alert_thresholds", []),
            "thresholds_breached": breached,
            "alerts_triggered": budget.get("alerts_triggered", []),
        }


def _normalize_tier(tier) -> str:
    from core import tier_policy as _tp
    return _tp.normalize_tier(tier)
