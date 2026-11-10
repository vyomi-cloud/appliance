"""Fake local simulator for the shell tests: the REAL core.mesh_shell module + a fake docker CLI + a fixed resolver.
   python fake_mesh_sim.py <port>   (env VYOMI_DOCKER_BIN=fake-docker.sh VYOMI_MESH_SHELL_ALLOW=1)"""
import os, sys
sys.path.insert(0, os.environ["APPLIANCE_ROOT"])
import uvicorn
from fastapi import FastAPI
from core import mesh_shell

MAP = {("aws", "i-good"): "vyomi-i-good", ("aws", "i-good2"): "vyomi-i-good2", ("gcp", "vm-gcp1"): "vyomi-i-gcp1", ("azure", "vm-az1"): "vyomi-i-az1",
       ("aws", "i-stopped"): "vyomi-i-stopped", ("aws", "i-othernet"): "vyomi-i-othernet", ("aws", "i-nolabel"): "vyomi-i-nolabel",
       ("aws", "i-evil"): "nginx", ("aws", "i-evil2"): "vyomi-i-good; rm -rf /", ("aws", "i-vpc"): "vyomi-i-vpc1", ("aws", "i-lookalike"): "vyomi-i-lookalike", ("aws", "i-ghost"): "vyomi-i-ghost", ("aws", "i-real"): "vyomi-i-ngshelltest"}
app = FastAPI()
from core import mesh_session
app.add_middleware(mesh_session.SessionMiddleware)   # VYOMI_ROLE=mesh: the simulator re-verifies the same token
@app.get('/mesh/status')
def _status():
    return {'ok': True, 'hostname': 'fake-mesh'}


mesh_shell.register(app, lambda cloud, ref: MAP.get((cloud, ref)))
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level=os.environ.get("SIM_LOG","warning"))
