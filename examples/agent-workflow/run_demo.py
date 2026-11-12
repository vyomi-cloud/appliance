"""Start a local Vyomi AI wire server backed by a REAL local model, then (optionally) run the three sample agents against it.

    python run_demo.py                 # serve on a free port and print the env for the drivers (Ctrl-C to stop)
    python run_demo.py --run           # serve, run all 3 drivers x 3 scenarios, stop
    python run_demo.py --run --runs 3 --only aws

Needs from the repo root:  PYTHONPATH=<repo root>  and  pip install -r requirements.txt boto3 google-genai openai
and an OpenAI-compatible local model server (default Ollama on 127.0.0.1:11434) with the chat model + an embedding model pulled:
    ollama pull qwen2.5:3b && ollama pull nomic-embed-text
(this is the same core.wire_ingress the offline appliance serves; tests/conformance/test_ai_sdk_tools.py does the same with a fake model.)
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.append(ROOT)


def start_server(llm_endpoint, chat_model, embed_model, port=0, embed_fn=None):
    import uvicorn
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core import wire_ingress
    from core.aws_wire_router import AwsWireRouter
    from core.azure_arm_core import AzureArm

    def _ollama_embed(texts):                   # the seam otherwise reuses the chat model for embeddings; use a real embedding model
        req = urllib.request.Request(llm_endpoint + "/api/embed", data=json.dumps({"model": embed_model, "input": texts}).encode(),
                                     headers={"content-type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=120))["embeddings"]

    os.environ.pop("VYOMI_LLM_DISABLE", None)
    llm.set_backend(None, embed_fn=embed_fn or _ollama_embed, model=chat_model, endpoint=llm_endpoint)
    router = AwsWireRouter()
    router.az_arm = AzureArm()
    base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1"
    router.az_arm.handle("PUT", base, {"api-version": "2024-10-01"}, {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}})
    for dep, model in (("chat", "gpt-4o"), ("embed", "text-embedding-3-small")):
        router.az_arm.handle("PUT", f"{base}/deployments/{dep}", {"api-version": "2024-10-01"},
                             {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": model, "version": "1"}}})
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)

    if not port:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    while not srv.started:
        if not th.is_alive():
            sys.exit(f"could not start the wire server on port {port} (in use?)")
        time.sleep(0.05)
    return srv, f"http://127.0.0.1:{port}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=os.environ.get("VYOMI_LLM_ENDPOINT", "http://127.0.0.1:11434"), help="OpenAI-compatible model server (Ollama / llama-server)")
    ap.add_argument("--model", default=os.environ.get("VYOMI_LLM_MODEL", "qwen2.5:3b"))
    ap.add_argument("--embed-model", default="nomic-embed-text")
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--run", action="store_true", help="run the drivers then exit")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", choices=["aws", "gcp", "azure"])
    ap.add_argument("--out", help="directory for per-driver JSON traces")
    a = ap.parse_args()
    try:
        urllib.request.urlopen(a.llm + "/api/tags", timeout=5)
    except Exception as e:
        sys.exit(f"No model server at {a.llm} ({e}). Start Ollama (`ollama serve`) and pull {a.model} + {a.embed_model}.")
    srv, url = start_server(a.llm.rstrip("/"), a.model, a.embed_model, a.port)
    env = dict(os.environ, VYOMI_ENDPOINT=url, PYTHONPATH=ROOT, TRIAGE_DB_FILE=os.path.join(HERE, ".triage_db.json"))
    print(f"Vyomi AI wire server on {url}  (model {a.model}, embeddings {a.embed_model})")
    if not a.run:
        print(f"export VYOMI_ENDPOINT={url}\n# then:  python agent_aws.py   |  python agent_gcp.py   |  python agent_azure.py\nCtrl-C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    rc = 0
    for name in ([a.only] if a.only else ["aws", "gcp", "azure"]):
        cmd = [sys.executable, os.path.join(HERE, f"agent_{name}.py"), "--runs", str(a.runs)]
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            cmd += ["--json", os.path.join(a.out, f"{name}.json")]
        rc |= subprocess.call(cmd, env=env, cwd=HERE)
    srv.should_exit = True
    return rc


if __name__ == "__main__":
    sys.exit(main())
