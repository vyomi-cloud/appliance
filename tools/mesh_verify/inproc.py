"""In-process Vyomi AWS wire server + REAL boto3 clients, pointed at the REAL llama-server gateway (no fake model). Used by agent/judge/KB scripts."""
import io, json, os, socket, sys, threading, time, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.mesh_verify.common import GATEWAY

ROLE = "arn:aws:iam::123456789012:role/r"


def start(real_embed=True):
    os.environ["VYOMI_LLM_ENDPOINT"] = GATEWAY
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    import boto3, uvicorn
    from botocore.config import Config
    from fastapi import FastAPI, Request
    from core import llm_core as llm, wire_ingress
    from core.aws_wire_router import AwsWireRouter
    llm.set_backend(None)
    llm._state["endpoint"] = GATEWAY
    llm._state["model"] = os.environ.get("MV_MODEL", "qwen3-4b")
    if not real_embed:
        llm._state["embed_fn"] = lambda texts: [llm.hash_embed(t) for t in texts]
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}, read_timeout=900))
    return url, kw, boto3


def make_lambda(lam, name, code):
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("index.py", code)
    return lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler="index.handler", Code={"ZipFile": zb.getvalue()})["FunctionArn"]
