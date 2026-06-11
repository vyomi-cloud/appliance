"""Console, docs, healthz, and startup routes extracted from server.py."""
from __future__ import annotations

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, Response
from core import app_context as ctx


# ─── Tier gate shared across the 3 console HTML routes ──────────────────────
# A Student-tier subscription is locked to ONE cloud. We must block UI access
# to other clouds at the HTML route level — otherwise the user sees an empty
# but fully-rendered console shell (every click 403s through the middleware,
# which is correct but a leaky UX).
#
# Returns a RedirectResponse to use, or None to continue with the normal
# HTMLResponse.
def _console_tier_gate(provider: str) -> RedirectResponse | None:
    try:
        from core import tier_policy as _tp
        tenant = ctx._tenant_dict(ctx._active_tenant_id()) or {}
    except Exception:
        return None  # fail-open on internal errors — middleware still gates APIs
    tier = str(tenant.get("license_tier") or "free")
    primary = str(tenant.get("primary_cloud") or "")
    policy = _tp.policy_for(tier)
    providers = policy.get("providers", [])

    if providers == "primary_cloud_only":
        # Student tier with no primary_cloud set → bounce to /pricing so they
        # can fix the activation. Matches the fail-safe in tier_policy.
        if not primary:
            return RedirectResponse(
                "/pricing?error=student_primary_cloud_required",
                status_code=302,
            )
        # Student tier asking for a different cloud → bounce to their cloud's
        # console with a query param the SPA can use to show a "locked" toast.
        if primary != provider:
            return RedirectResponse(
                f"/console/{primary}?denied={provider}",
                status_code=302,
            )
    elif isinstance(providers, list) and provider not in providers:
        # Free tier hitting a console it doesn't have access to — bounce to
        # /pricing with the upgrade context.
        return RedirectResponse(
            f"/pricing?error=tier_console_locked&cloud={provider}&tier={tier}",
            status_code=302,
        )
    return None


def _swagger_html(openapi_url: str, title: str):
    """Swagger UI from locally-bundled assets (works fully offline)."""
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(
        openapi_url=openapi_url,
        title=title,
        swagger_js_url="/assets/swagger/swagger-ui-bundle.js",
        swagger_css_url="/assets/swagger/swagger-ui.css",
        swagger_favicon_url="/assets/swagger/favicon-32x32.png",
    )


def _openapi_subset(app: FastAPI, provider: str) -> dict:
    """A per-provider OpenAPI spec: keep only that provider's paths so AWS and GCP
    each get their own Swagger console instead of one giant combined list."""
    import copy
    spec = copy.deepcopy(app.openapi())
    label = "GCP" if provider == "gcp" else "AWS"
    spec["info"] = {**spec.get("info", {}), "title": f"CloudLearn — {label} API"}
    paths = spec.get("paths", {}) or {}
    spec["paths"] = {p: it for p, it in paths.items() if ctx._is_gcp_native_path(p) == (provider == "gcp")}
    # Prune now-unreferenced tags (cosmetic).
    return spec


def register(app: FastAPI) -> None:

    @app.get("/api/runtime/backends", include_in_schema=False)
    def runtime_backends() -> dict:
        """Status of all MVP P0 backends — what's real vs in-memory mock."""
        results: dict = {}
        try:
            from core import vault_client as _vc
            results["vault"] = {
                "url": _vc._VAULT_URL,
                "available": _vc.available(),
                "backs": ["AWS KMS", "AWS Secrets Manager", "GCP Cloud KMS",
                          "GCP Secret Manager", "Azure Key Vault (keys + secrets)"],
            }
        except Exception as exc:
            results["vault"] = {"available": False, "error": repr(exc)}
        try:
            from core import nats_client as _nc
            results["nats"] = {
                "url": _nc._NATS_URL,
                "available": _nc.available(),
                "backs": ["AWS EventBridge", "GCP Eventarc", "Azure Event Grid"],
            }
        except Exception as exc:
            results["nats"] = {"available": False, "error": repr(exc)}
        try:
            from core import minio_mirror as _mm
            results["minio"] = {
                "url": _mm._MINIO_URL,
                "available": _mm.available(),
                "backs": ["AWS S3 (write-through real bytes)"],
            }
        except Exception as exc:
            results["minio"] = {"available": False, "error": repr(exc)}
        try:
            from core import dynamodb_proxy as _dp
            results["dynamodb-local"] = {
                "url": _dp._DDB_URL,
                "available": _dp.available(),
                "backs": ["AWS DynamoDB (full proxy)"],
            }
        except Exception as exc:
            results["dynamodb-local"] = {"available": False, "error": repr(exc)}
        try:
            from core import elasticmq_proxy as _emq
            results["elasticmq"] = {
                "url": _emq._EMQ_URL,
                "available": _emq.available(),
                "backs": ["AWS SQS (legacy/query protocol; modern JSON-RPC stays in-memory)"],
            }
        except Exception as exc:
            results["elasticmq"] = {"available": False, "error": repr(exc)}
        try:
            from core import cedar_engine as _ce
            results["cedar"] = {
                "available": _ce.available(),
                "backs": ["AWS IAM (JSON policies)", "GCP IAM (bindings)",
                          "Azure RBAC (role assignments)"],
            }
        except Exception as exc:
            results["cedar"] = {"available": False, "error": repr(exc)}
        try:
            from core import gcp_sql_engine as _eng
            results["postgres"] = {
                "available": _eng.available("postgres"),
                "backs": ["GCP Cloud SQL Postgres", "Azure Database for PostgreSQL",
                          "Azure SQL (Microsoft.Sql/servers/databases)"],
            }
            results["mysql"] = {
                "available": _eng.available("mysql"),
                "backs": ["GCP Cloud SQL MySQL", "Azure Database for MySQL"],
            }
        except Exception as exc:
            results["postgres"] = {"available": False, "error": repr(exc)}
        summary = {
            "ready": sum(1 for v in results.values() if v.get("available")),
            "total": len(results),
        }
        return {"backends": results, "summary": summary}

    @app.get("/openapi-gcp.json", include_in_schema=False)
    def openapi_gcp():
        return JSONResponse(_openapi_subset(app, "gcp"))

    @app.get("/openapi-aws.json", include_in_schema=False)
    def openapi_aws():
        return JSONResponse(_openapi_subset(app, "aws"))

    @app.get("/openapi-azure.json", include_in_schema=False)
    def openapi_azure():
        from providers import azure_services as provider_azure_services
        return JSONResponse(provider_azure_services.build_openapi())

    @app.get("/docs/azure", include_in_schema=False)
    def docs_azure():
        return _swagger_html("/openapi-azure.json", "CloudLearn — Azure API")

    @app.get("/aws", include_in_schema=False)
    def _shortpath_aws():
        return RedirectResponse(url="/console/aws", status_code=302)

    @app.get("/gcp", include_in_schema=False)
    def _shortpath_gcp():
        return RedirectResponse(url="/console/gcp", status_code=302)

    @app.get("/azure", include_in_schema=False)
    def _shortpath_azure():
        return RedirectResponse(url="/console/azure", status_code=302)

    @app.get("/pricing", include_in_schema=False)
    def pricing_page():
        html_path = os.path.join(os.path.dirname(__file__), "..", "static", "pricing.html")
        with open(html_path, "rb") as f:
            return HTMLResponse(content=f.read().decode("utf-8"),
                                headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/console/azure", include_in_schema=False)
    @app.get("/console/azure/{path:path}", include_in_schema=False)
    def console_azure(path: str = ""):
        gate = _console_tier_gate("azure")
        if gate is not None:
            return gate
        html_path = os.path.join(os.path.dirname(__file__), "..", "static", "azure-console.html")
        with open(html_path, "rb") as f:
            return HTMLResponse(content=f.read().decode("utf-8"), headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/console/aws", include_in_schema=False)
    @app.get("/console/aws/{path:path}", include_in_schema=False)
    def console_aws(path: str = ""):
        gate = _console_tier_gate("aws")
        if gate is not None:
            return gate
        html_path = os.path.join(os.path.dirname(__file__), "..", "static", "aws-console.html")
        with open(html_path, "rb") as f:
            return HTMLResponse(content=f.read().decode("utf-8"), headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/api/aws/catalog", include_in_schema=False)
    def api_aws_catalog():
        from providers.aws_catalog import build_console_payload
        space = ctx.PLATFORM.get_active_space() or {}
        region  = str(space.get("active_region") or "us-east-1")
        account = str(space.get("active_account") or "123456789012")
        return JSONResponse(build_console_payload(active_region=region, active_account=account))

    @app.get("/console/gcp", include_in_schema=False)
    @app.get("/console/gcp/{path:path}", include_in_schema=False)
    def console_gcp(path: str = ""):
        gate = _console_tier_gate("gcp")
        if gate is not None:
            return gate
        html_path = os.path.join(os.path.dirname(__file__), "..", "static", "gcp-console.html")
        with open(html_path, "rb") as f:
            return HTMLResponse(content=f.read().decode("utf-8"), headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/api/gcp/catalog", include_in_schema=False)
    def api_gcp_catalog():
        from providers.gcp_catalog import build_console_payload
        space = ctx.PLATFORM.get_active_space() or {}
        project = str(space.get("active_account") or "cloudlearn")
        region  = str(space.get("active_region") or "us-central1")
        zone = region + "-a"
        return JSONResponse(build_console_payload(active_project=project,
                                                  active_region=region,
                                                  active_zone=zone))

    @app.get("/docs/gcp", include_in_schema=False)
    def docs_gcp():
        return _swagger_html("/openapi-gcp.json", "CloudLearn — GCP API")

    @app.get("/docs/aws", include_in_schema=False)
    def docs_aws():
        return _swagger_html("/openapi-aws.json", "CloudLearn — AWS API")

    @app.get("/docs/all", include_in_schema=False)
    def docs_all():
        return _swagger_html(app.openapi_url or "/openapi.json", "CloudLearn — All APIs")

    @app.get("/docs/gcp/usage", include_in_schema=False)
    def docs_gcp_usage(request: Request):
        import server
        return HTMLResponse(server._usage_html(request, "gcp"))

    @app.get("/docs/aws/usage", include_in_schema=False)
    def docs_aws_usage(request: Request):
        import server
        return HTMLResponse(server._usage_html(request, "aws"))

    @app.get("/docs/azure/usage", include_in_schema=False)
    def docs_azure_usage(request: Request):
        import server
        return HTMLResponse(server._usage_html(request, "azure"))

    @app.get("/docs", include_in_schema=False)
    def docs_chooser():
        """Landing chooser that links to the separate AWS and GCP API consoles."""
        html = """<!doctype html><html><head><meta charset="utf-8"><title>CloudLearn API Consoles</title>
<link rel="icon" href="/assets/swagger/favicon-32x32.png">
<style>
 body{margin:0;font-family:Roboto,Arial,sans-serif;background:#0f1b2d;color:#e8eef6;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px}
 h1{font-weight:500;margin:0 0 4px}.sub{color:#9fb0c7;margin-bottom:8px}
 .cards{display:flex;gap:24px;flex-wrap:wrap;justify-content:center}
 .col{display:flex;flex-direction:column;gap:12px;align-items:stretch;width:280px}
 a.card{display:block;padding:28px;border-radius:14px;text-decoration:none;color:#fff;box-shadow:0 8px 30px rgba(0,0,0,.35);transition:transform .12s}
 a.card:hover{transform:translateY(-4px)}
 .aws{background:linear-gradient(135deg,#ff9900,#d97700)}.gcp{background:linear-gradient(135deg,#1a73e8,#1761c9)}.azure{background:linear-gradient(135deg,#0078d4,#005a9e)}
 .card h2{margin:0 0 6px;font-size:22px}.card p{margin:0;opacity:.9;font-size:14px}
 .ulink{display:block;text-align:center;color:#cfe0f7;font-size:13px;text-decoration:none;background:#16243a;border:1px solid #243650;border-radius:8px;padding:9px}
 .ulink:hover{background:#1d2f4a;color:#fff}
 .all{color:#9fb0c7;font-size:13px;text-decoration:none}.all:hover{color:#fff}
</style></head><body>
 <div style="text-align:center"><h1>CloudLearn — API Reference</h1><div class="sub">Interactive Swagger consoles + SDK/CLI usage, one per cloud.</div></div>
 <div class="cards">
   <div class="col">
     <a class="card aws" href="/docs/aws"><h2>AWS API ›</h2><p>S3, EC2, IAM, SQS, RDS, DynamoDB, Lambda, API Gateway, VPC.</p></a>
     <a class="ulink" href="/docs/aws/usage">⌨ SDK &amp; CLI usage (CLI · boto3 · Java · Go · Terraform) ›</a>
   </div>
   <div class="col">
     <a class="card gcp" href="/docs/gcp"><h2>GCP API ›</h2><p>Compute, Storage, Cloud SQL, Pub/Sub, Firestore, Functions, API Gateway, VPC, IAM.</p></a>
     <a class="ulink" href="/docs/gcp/usage">⌨ SDK &amp; CLI usage (gcloud/gsutil · Java · Go · Terraform) ›</a>
   </div>
   <div class="col">
     <a class="card azure" href="/docs/azure"><h2>Azure API ›</h2><p>Virtual Machines, Blob Storage, SQL, Service Bus, Cosmos DB, Functions, API Management, VNet, Entra/RBAC.</p></a>
     <a class="ulink" href="/docs/azure/usage">⌨ SDK &amp; CLI usage (az CLI · Java · Go) ›</a>
     <a class="ulink" href="/console/azure">🖥 Azure portal console ›</a>
   </div>
 </div>
 <a class="all" href="/docs/all">View all endpoints (combined) →</a>
</body></html>"""
        return HTMLResponse(html)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "tier": ctx.STATE["license"].get("tier", "free"), "packs_active": sum(1 for p in ctx.STATE["packs"].values() if p.get("active"))}

    @app.on_event("startup")
    def _startup_reconcile_ec2_state():
        try:
            ctx.PLATFORM.runtime.start_bootstrap()
        except Exception:
            pass
        try:
            ctx.PLATFORM.rehydrate_cloudsim()
        except Exception:
            pass
        import server
        server._reconcile_runtime_instances(ctx.ec2_state.get("instances", {}))
        server._reconcile_runtime_instances(ctx.gcp_compute_state.get("instances", {}))
        server._prune_expired_terminated_instances()
        server._prune_expired_terminated_instances_from(ctx.gcp_compute_state.get("instances", {}))

    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/{path:path}", include_in_schema=False)
    @app.get("/product", include_in_schema=False)
    @app.get("/product/{path:path}", include_in_schema=False)
    async def serve_ui(path: str = "") -> Response:
        _UI_HTML = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
        with open(_UI_HTML, "rb") as f:
            return Response(content=f.read(), media_type="text/html", headers={"Cache-Control": "no-store, max-age=0"})
