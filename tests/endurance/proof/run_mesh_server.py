"""Start the simulator the way a Mesh headless appliance runs (VYOMI_MESH_MODE=1, Pro trial licence so a Nano tab can pair),
so the Nano console UI proof reads the SAME server the Terraform estate was applied to.
    python run_mesh_server.py PORT        (env as for server.py: CLOUDLEARN_STATE_FILE, VYOMI_LLM_ENDPOINT ...)
Not a test fixture of the real appliance: it only adds the licence claims the pairing handshake needs (same as tests/mesh/run_real_mesh.py)."""
import os, sys, time
port = int(sys.argv[1])
os.environ.setdefault("VYOMI_MESH_MODE", "1")
os.environ.setdefault("VYOMI_MESH_NO_RELAY", "1")
os.environ.setdefault("VYOMI_MESH_EXTRA_ORIGINS", os.environ.get("NANO_ORIGIN", ""))
sys.path.insert(0, os.getcwd())
import server
from core import app_context as ctx
now = int(time.time())
ctx.STATE["license_claims"] = {"tier": "pro", "sub": "acct-test", "trial": True,
                               "sub_expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 14 * 86400)), "iat": now}
import uvicorn
uvicorn.run(server.app, host="0.0.0.0", port=port, log_level="warning")
