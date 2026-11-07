"""Console, docs, healthz, and startup routes extracted from server.py."""
from __future__ import annotations

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, Response
from core import app_context as ctx


# App-matching dark theme for Swagger UI (bg #05071a, tiles #14172e/#0d1228,
# text #cdd8e6). Injected before </head> when the page is asked for with
# ?theme=dark — used by the embedded in-console / dashboard API view.
_SWAGGER_DARK_CSS = b"""<style id="swagger-dark">
  body,.swagger-ui{background:#05071a!important}
  .swagger-ui .topbar{display:none}
  .swagger-ui,.swagger-ui .info li,.swagger-ui .info p,.swagger-ui .info table,.swagger-ui label,.swagger-ui .opblock-tag,.swagger-ui .opblock .opblock-summary-operation-id,.swagger-ui .opblock .opblock-summary-path,.swagger-ui .opblock .opblock-summary-path__deprecated,.swagger-ui .opblock .opblock-summary-description,.swagger-ui .opblock-description-wrapper p,.swagger-ui .opblock-external-docs-wrapper p,.swagger-ui .response-col_status,.swagger-ui table thead tr td,.swagger-ui table thead tr th,.swagger-ui .parameter__name,.swagger-ui .parameter__type,.swagger-ui .parameter__in,.swagger-ui .prop-type,.swagger-ui .model,.swagger-ui .model-title,.swagger-ui section h4,.swagger-ui .tab li,.swagger-ui .response-col_description__inner p,.swagger-ui .scheme-container .schemes>label,.swagger-ui .servers>label{color:#cdd8e6!important}
  .swagger-ui .info .title,.swagger-ui h1,.swagger-ui h2,.swagger-ui h3,.swagger-ui h4,.swagger-ui h5{color:#e4e4e7!important}
  .swagger-ui .scheme-container,.swagger-ui .opblock .opblock-section-header{background:#0d1228!important;box-shadow:none}
  .swagger-ui .opblock{background:#14172e!important;border-color:rgba(255,255,255,.10)!important;box-shadow:none}
  .swagger-ui .opblock .opblock-summary{border-color:rgba(255,255,255,.10)!important}
  .swagger-ui .opblock.opblock-get{background:rgba(97,175,254,.08)!important;border-color:#4d8cf3!important}
  .swagger-ui .opblock.opblock-post{background:rgba(73,204,144,.08)!important;border-color:#34d399!important}
  .swagger-ui .opblock.opblock-delete{background:rgba(249,62,62,.08)!important;border-color:#f87171!important}
  .swagger-ui .opblock.opblock-put{background:rgba(252,161,48,.08)!important;border-color:#fbbf24!important}
  .swagger-ui input,.swagger-ui textarea,.swagger-ui select{background:#0b0e22!important;color:#e4e4e7!important;border-color:rgba(255,255,255,.14)!important}
  .swagger-ui section.models,.swagger-ui section.models .model-container,.swagger-ui .model-box{background:#0d1228!important;border-color:rgba(255,255,255,.10)!important}
  .swagger-ui .btn{color:#cdd8e6;border-color:rgba(255,255,255,.2);background:#171b3d}
  .swagger-ui .btn.execute{background:linear-gradient(135deg,#4d8cf3,#7c3aed);border:0;color:#fff}
  .swagger-ui .highlight-code,.swagger-ui .microlight,.swagger-ui .opblock-body pre.microlight{background:#0b0e22!important;color:#e4e4e7!important}
  .swagger-ui .responses-inner{background:transparent}
  .swagger-ui svg:not(:root){fill:#cdd8e6}
  .swagger-ui a,.swagger-ui .info a{color:#7cc4ff}
  .swagger-ui .opblock-tag{border-color:rgba(255,255,255,.10)}
  .swagger-ui .tab li.active{color:#fff}
  .swagger-ui .parameters-col_description input{background:#0b0e22!important}
  .swagger-ui .prop-format{color:#8b8ba7}
</style></head>"""


def _swagger_html(openapi_url: str, title: str, dark: bool = False):
    """Swagger UI from locally-bundled assets (works fully offline). dark=True
    (?theme=dark) injects the app-matching dark theme for the embedded view."""
    from fastapi.openapi.docs import get_swagger_ui_html
    resp = get_swagger_ui_html(
        openapi_url=openapi_url,
        title=title,
        swagger_js_url="/assets/swagger/swagger-ui-bundle.js",
        swagger_css_url="/assets/swagger/swagger-ui.css",
        swagger_favicon_url="/assets/swagger/favicon-32x32.png",
    )
    if dark:
        from fastapi.responses import HTMLResponse
        body = resp.body.replace(b"</head>", _SWAGGER_DARK_CSS, 1)
        return HTMLResponse(content=body, status_code=resp.status_code)
    return resp


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

    @app.get("/api/runtime/profile", include_in_schema=False)
    def runtime_profile() -> dict:
        """The active sandbox profile + which clouds it allows. The SPA / cloud
        picker / consoles use this to HIDE out-of-profile clouds. When there's no
        restriction (unset / all-clouds), allowed_clouds is all three."""
        from core import tier_policy as _tp
        clouds = _tp.profile_clouds()
        return {
            "profile": _tp.active_profile(),
            "restricted": clouds is not None,
            "allowed_clouds": sorted(clouds) if clouds else ["aws", "gcp", "azure"],
        }

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
    def docs_azure(request: Request):
        return _swagger_html("/openapi-azure.json", "CloudLearn — Azure API", request.query_params.get("theme") == "dark")

    @app.get("/api/aws/catalog", include_in_schema=False)
    def api_aws_catalog():
        from providers.aws_catalog import build_console_payload
        space = ctx.PLATFORM.get_active_space() or {}
        region  = str(space.get("active_region") or "us-east-1")
        account = str(space.get("active_account") or "123456789012")
        return JSONResponse(build_console_payload(active_region=region, active_account=account))

    @app.get("/api/gcp/catalog", include_in_schema=False)
    def api_gcp_catalog():
        from providers.gcp_catalog import build_console_payload
        from core import gcp_project
        # The GCP space's project ID (+ number) — the same project gcloud sees
        # through Cloud Resource Manager.
        space = gcp_project.gcp_space() or ctx.PLATFORM.get_active_space() or {}
        proj = gcp_project.current()
        region  = str(space.get("active_region") or "us-central1")
        zone = region + "-a"
        return JSONResponse(build_console_payload(active_project=proj["projectId"],
                                                  active_region=region,
                                                  active_zone=zone,
                                                  project_number=proj["projectNumber"]))

    @app.get("/docs/gcp", include_in_schema=False)
    def docs_gcp(request: Request):
        return _swagger_html("/openapi-gcp.json", "CloudLearn — GCP API", request.query_params.get("theme") == "dark")

    @app.get("/docs/aws", include_in_schema=False)
    def docs_aws(request: Request):
        return _swagger_html("/openapi-aws.json", "CloudLearn — AWS API", request.query_params.get("theme") == "dark")

    @app.get("/docs/all", include_in_schema=False)
    def docs_all(request: Request):
        return _swagger_html(app.openapi_url or "/openapi.json", "CloudLearn — All APIs", request.query_params.get("theme") == "dark")

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
   </div>
 </div>
 <a class="all" href="/docs/all">View all endpoints (combined) →</a>
</body></html>"""
        return HTMLResponse(html)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        from core import booster_session as _bs
        return {"status": "ok", "tier": _bs.effective_tier() or ctx.STATE["license"].get("tier", "free"), "packs_active": sum(1 for p in ctx.STATE["packs"].values() if p.get("active"))}

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
