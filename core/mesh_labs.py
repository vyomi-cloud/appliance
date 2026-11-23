"""Vyomi Labs inside the Mesh: POST /mesh/labs/deploy/{cloud}/{layer} deploys a chapter's lab code (the exact blocks the course page shows)
into THIS appliance and streams NDJSON progress. Only the fixed course content in vyomilabs/content can run; the request carries no code.
Same guard as the other /mesh APIs (host + origin allow-list, rate limit)."""
import json
import threading

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

_STATE = {"cloud": None}


def register(app) -> None:
    from core import mesh as _mesh

    @app.post("/mesh/labs/deploy/{cloud}/{layer}", include_in_schema=False)
    def _labs_deploy(cloud: str, layer: int, request: Request):
        g = _mesh_guard(_mesh, request)
        if g:
            return g
        if cloud not in ("aws", "gcp", "azure"):
            return JSONResponse({"error": {"code": "NoSuchCloud", "message": cloud}}, status_code=404)
        try:
            from vyomilabs import deployer
        except Exception as e:                      # the labs package is not in this image
            return JSONResponse({"error": {"code": "LabsRunnerMissing", "message": "This Mesh image does not include Vyomi Labs: %s" % e}}, status_code=501)
        import os
        os.environ.setdefault("VYOMILABS_HAS_RUNTIME", "1")      # this appliance has the real Lambda runtime
        host, port = (request.scope.get("server") or ("127.0.0.1", 8000))
        endpoint = "http://127.0.0.1:%s" % port       # the appliance itself: the SDKs call it on loopback
        return StreamingResponse((json.dumps(ev) + "\n" for ev in deployer.deploy(cloud, layer, endpoint=endpoint)), media_type="application/x-ndjson")


def _mesh_guard(_mesh, request):
    if not _mesh.host_allowed(request.headers.get("host", "")):
        return JSONResponse({"error": {"code": "BadHost", "message": "Host not allowed for the mesh API."}}, status_code=421)
    if not _mesh.origin_allowed(request.headers.get("origin", "")):
        return JSONResponse({"error": {"code": "OriginNotAllowed", "message": "Origin not allowed."}}, status_code=403)
    return None
