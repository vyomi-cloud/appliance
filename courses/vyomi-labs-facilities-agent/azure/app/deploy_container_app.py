import base64
import io
import os
import zipfile
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azlab import arm, rid, RG, LOC, HTTP_ENDPOINT

APP, ENV = "facilities-supervisor", "facilities-env"

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("app.py", "app.py")
    z.write("agent_graph.py", "agent_graph.py")
    z.writestr("requirements.txt", "fastapi\nuvicorn\nopenai\nlanggraph\n")
bundle = base64.b64encode(buf.getvalue()).decode()

c = arm(ContainerAppsAPIClient)
c.managed_environments.begin_create_or_update(RG, ENV, {"location": LOC, "properties": {}}).result()
app = c.container_apps.begin_create_or_update(RG, APP, {"location": LOC, "properties": {
    "managedEnvironmentId": rid("Microsoft.App", "managedEnvironments", ENV),
    "configuration": {"ingress": {"external": True, "targetPort": 8080}},
    "template": {"containers": [{"name": "supervisor", "image": "vyomi/python-app:latest", "env": [
        {"name": "VYOMI_APP_SOURCE_B64", "value": bundle}, {"name": "VYOMI_ENDPOINT", "value": HTTP_ENDPOINT}]}]}}}).result()
print("container app", app.name, "state:", getattr(app.provisioning_state, "value", app.provisioning_state))
