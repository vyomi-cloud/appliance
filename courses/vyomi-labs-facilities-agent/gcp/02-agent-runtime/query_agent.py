import os

import gcp

client = gcp.vertex_client("v1beta1")
listed = next(e for e in client.agent_engines.list() if e.api_resource.display_name == "facilities_supervisor")
engine = client.agent_engines.get(name=listed.api_resource.name)     # get() returns the engine with its registered query method attached
out = engine.query(prompt="Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?", user="maria")
print("hosted in a separate process:", out["pid"] != os.getpid())
print("route:", out["route"])
print("spans:", [s["name"] for s in out["spans"]])
