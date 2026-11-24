import os
import shutil

import gcp

PKG = "engine_pkg"
shutil.rmtree(PKG, ignore_errors=True)
os.makedirs(PKG)
for f in ("agent_engine_app.py", "agents.py", "models.py", "gcp.py", "starter_tools.py"):
    shutil.copy(f, os.path.join(PKG, f))
with open(os.path.join(PKG, "requirements.txt"), "w") as f:
    f.write("google-cloud-aiplatform\ngoogle-genai\nlanggraph\n")

os.environ.setdefault("STORAGE_EMULATOR_HOST", gcp.ENDPOINT)        # the SDK stages the package in Cloud Storage; this points it at the simulator
try:
    gcp.storage_client().create_bucket("facilities-agent-staging")
except Exception:
    pass                                                           # already exists

client = gcp.vertex_client("v1beta1")
engine = client.agent_engines.create(config={
    "display_name": "facilities_supervisor", "staging_bucket": "gs://facilities-agent-staging",
    "source_packages": [PKG], "entrypoint_module": "agent_engine_app", "entrypoint_object": "agent",
    "requirements_file": os.path.join(PKG, "requirements.txt"),
    "env_vars": {"VYOMI_ENDPOINT": gcp.ENDPOINT, "GOOGLE_CLOUD_PROJECT": gcp.PROJECT, "GOOGLE_CLOUD_REGION": gcp.LOCATION},
    "class_methods": [{"name": "query", "api_mode": "", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}, "user": {"type": "string"}}, "required": ["prompt"]}}]})
print("deployed", engine.api_resource.name)
