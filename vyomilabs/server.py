"""Vyomi Labs local web app (FastAPI). Serves the Labs pages (wasm/labs) and the check API.

  python -m vyomilabs serve                      # http://127.0.0.1:8765, simulator at VYOMILABS_ENDPOINT (default http://localhost:9000)
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import WEB_DIR, __version__, checks, layers, progress

DEFAULT_ENDPOINT = "http://localhost:9000"


def create_app(endpoint=None, region="us-east-1"):
    app = FastAPI(title="Vyomi Labs", version=__version__, docs_url=None, redoc_url=None)
    os.environ.setdefault("VYOMILABS_HAS_RUNTIME", "1")   # the deploy runner starts the simulator with the real Lambda runtime
    cfg = dict(endpoint=endpoint or os.environ.get("VYOMILABS_ENDPOINT") or DEFAULT_ENDPOINT, region=region)

    def summary(layer, prog):
        p = prog.get(str(layer["id"]), {})
        return dict(id=layer["id"], order=layer["order"], title=layer["title"], short=layer["short"], services=layer["services"],
                    hotspot=layer["hotspot"], status=p.get("status", "TODO"), checked_at=p.get("checked_at"),
                    checker=layer["id"] in checks.available())

    @app.get("/api/course")
    def get_course():
        c, prog = layers.course(), progress.load()
        ls = [summary(layer, prog) for layer in sorted(layers.layers(), key=lambda x: x["order"])]
        done = sum(1 for x in ls if x["status"] == "PASS")
        return dict(title=c["title"], cloud=c["cloud"], image=c["image"], image_size=c["image_size"],
                    layers=ls, done=done, total=len(ls), next=layers.next_layer(prog), endpoint=cfg["endpoint"], version=__version__)

    @app.get("/api/layers/{layer_id}")
    def get_layer(layer_id: int):
        layer = layers.get(layer_id)
        if not layer:
            raise HTTPException(404, "no such layer")
        prog = progress.load().get(str(layer_id), {})
        return dict(layer, progress=prog, checker=layer_id in checks.available())

    @app.post("/api/layers/{layer_id}/check")
    def check_layer(layer_id: int):
        if not layers.get(layer_id):
            raise HTTPException(404, "no such layer")
        res = checks.run(layer_id, cfg["endpoint"], cfg["region"], workspace=os.environ.get("VYOMILABS_WORKSPACE"))
        if res["implemented"]:
            res["progress"] = progress.record(layer_id, res["status"], res["steps"])
        return res

    @app.post("/api/layers/{layer_id}/reset")
    def reset_layer(layer_id: int):
        progress.reset(layer_id)
        return dict(ok=True)

    @app.post("/api/deploy/{cloud}/{layer_id}")
    def deploy_layer(cloud: str, layer_id: int):
        import json as _json
        from . import deployer
        if cloud not in ("aws", "gcp", "azure"):
            raise HTTPException(404, "no such cloud")
        return StreamingResponse((_json.dumps(ev) + "\n" for ev in deployer.deploy(cloud, layer_id)), media_type="application/x-ndjson")

    @app.post("/api/deploy/{cloud}/reset")
    def deploy_reset(cloud: str):
        from . import deployer
        deployer.reset(cloud)
        return dict(ok=True)

    @app.get("/api/health")
    def health():
        return JSONResponse(dict(ok=True, version=__version__))

    @app.get("/healthz")
    def healthz():
        return JSONResponse(dict(ok=True, version=__version__))

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="labs")
    return app
