"""Run the REAL appliance app (server.py) natively with the BUILT v4 console bundles mounted at /v4/<cloud>/.
Usage: serve_mesh.py PORT [STATE_DIR]. Nothing is mocked: every /_wire, /api and signed SDK call goes through server.py."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
port = int(sys.argv[1]); state = sys.argv[2] if len(sys.argv) > 2 else "/tmp/vyomi-mesh-verify"
os.makedirs(state, exist_ok=True)
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0"); os.environ.setdefault("CLOUDLEARN_STATE_DIR", state); os.environ.setdefault("CLOUDLEARN_DATA_DIR", state)
import uvicorn
from fastapi.staticfiles import StaticFiles
import server
server.app.router.routes.insert(0, __import__("starlette.routing", fromlist=["Mount"]).Mount("/v4", StaticFiles(directory=os.path.join(ROOT, "wasm", "v4"), html=True), name="v4consoles"))
uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")
