"""Cloud Resource Manager for the GCP space's project (core/gcp_project).

`gcloud projects list` (GET /v1/projects), `gcloud projects describe` (GET
/v1/projects/{id-or-number}) and the v3 equivalents the client libraries use
(GET /v3/projects/{p}, GET /v3/projects?parent=, GET /v3/projects:search) all
return the ONE project the GCP console works in. gcloud also looks the project
up here before other commands when its endpoint override is set (e.g.
`gcloud secrets list`), so without these the CLI couldn't see the project at all.
Nano's relay serves the same views (core/aws_wire_router → gcp_project.crm_dispatch).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import gcp_project


def register(app: FastAPI) -> None:
    async def crm(request: Request):
        status, body = gcp_project.crm_dispatch(request.method, request.url.path,
                                                dict(request.query_params))
        return JSONResponse(status_code=status, content=body)

    for path in ("/v1/projects", "/v1/projects/{project}", "/v3/projects",
                 "/v3/projects:search", "/v3/projects/{project}"):
        app.add_api_route(path, crm, methods=["GET"], include_in_schema=False)
