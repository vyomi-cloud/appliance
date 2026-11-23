# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""API Gateway (REST): APIs, resources, methods, integrations, deployments, stages."""
from __future__ import annotations

import re

from core.tf_export import hcl
from core.tf_export.core import Ctx, exporter

_LAMBDA_URI = re.compile(r"functions/(arn:aws:lambda:[^/]+)/invocations")


@exporter(50, "apigateway")
def export_apigateway(ctx: Ctx) -> None:
    ag = ctx.c["apigateway"]
    apis = []
    for page in ag.get_paginator("get_rest_apis").paginate():
        apis += page.get("items", [])
    for a in apis:
        api_addr = ctx.add("aws_api_gateway_rest_api", a["id"], a["name"],
                           {"name": a["name"], "description": a.get("description") or None, "tags": a.get("tags") or None},
                           file="apigateway.tf")
        ctx.interp[a["id"]] = f"{api_addr}.id"
        api_id = hcl.Ref(f"{api_addr}.id")
        res = ag.get_resources(restApiId=a["id"], limit=500).get("items", [])
        root = next((r["id"] for r in res if r.get("path") == "/"), None)
        kids = sorted((r for r in res if r["id"] != root), key=lambda r: r["path"].count("/"))
        for r in kids:
            ctx.reserve("aws_api_gateway_resource", r["id"], r["path"].strip("/").replace("/", "_") or "root")
        def rid(res_id):
            return hcl.Ref(f"{api_addr}.root_resource_id") if res_id == root else ctx.ref("aws_api_gateway_resource", res_id)
        for r in kids:
            ctx.add("aws_api_gateway_resource", r["id"], r["path"],
                    {"rest_api_id": api_id, "parent_id": rid(r.get("parentId")), "path_part": r["pathPart"]}, file="apigateway.tf")
        last_integrations = []
        for r in res:
            for verb in (r.get("resourceMethods") or {}):
                m = ag.get_method(restApiId=a["id"], resourceId=r["id"], httpMethod=verb)
                maddr = ctx.add("aws_api_gateway_method", f"{r['id']}/{verb}", f"{r['path']}_{verb}",
                                {"rest_api_id": api_id, "resource_id": rid(r["id"]), "http_method": verb,
                                 "authorization": m.get("authorizationType", "NONE"),
                                 "api_key_required": True if m.get("apiKeyRequired") else None,
                                 "request_parameters": m.get("requestParameters") or None}, file="apigateway.tf")
                mi = m.get("methodIntegration")
                if not mi:
                    continue
                uri = mi.get("uri")
                lm = _LAMBDA_URI.search(uri or "")
                if lm and ctx.addr.get(("aws_lambda_function", lm.group(1))):
                    uri = hcl.Ref(f"{ctx.addr[('aws_lambda_function', lm.group(1))]}.invoke_arn")
                iaddr = ctx.add("aws_api_gateway_integration", f"{r['id']}/{verb}", f"{r['path']}_{verb}",
                                {"rest_api_id": api_id, "resource_id": rid(r["id"]), "http_method": hcl.Ref(f"{maddr}.http_method"),
                                 "type": mi.get("type"), "integration_http_method": mi.get("httpMethod"), "uri": uri,
                                 "passthrough_behavior": mi.get("passthroughBehavior") if mi.get("type") not in ("AWS_PROXY", "HTTP_PROXY") else None,
                                 "request_templates": mi.get("requestTemplates") or None,
                                 "timeout_milliseconds": mi.get("timeoutInMillis") if mi.get("timeoutInMillis") not in (None, 29000) else None},
                                file="apigateway.tf")
                last_integrations.append(hcl.Ref(iaddr))
        for d in ag.get_deployments(restApiId=a["id"]).get("items", []):
            attrs = {"rest_api_id": api_id, "description": d.get("description") or None}
            if last_integrations:
                attrs["depends_on"] = last_integrations
            ctx.add("aws_api_gateway_deployment", d["id"], f"{a['name']}_deployment", attrs, file="apigateway.tf")
        for st in ag.get_stages(restApiId=a["id"]).get("item", []):
            ctx.add("aws_api_gateway_stage", f"{a['id']}/{st['stageName']}", f"{a['name']}_{st['stageName']}",
                    {"rest_api_id": api_id, "deployment_id": ctx.ref("aws_api_gateway_deployment", st.get("deploymentId", "")),
                     "stage_name": st["stageName"], "description": st.get("description") or None,
                     "variables": st.get("variables") or None, "xray_tracing_enabled": True if st.get("tracingEnabled") else None,
                     "tags": st.get("tags") or None}, file="apigateway.tf")
