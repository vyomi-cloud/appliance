import os
os.environ.setdefault("VYOMI_ENDPOINT", os.environ["VYOMI_AZURE_HTTP_ENDPOINT"])
from app import graph

st = graph.invoke({"question": "Boiler B-12 is at 34 psi. What does the SOP say, and what is its status?", "user": "maria", "spans": []})
print("route:", st["route"], "| model routed:", st["llm_used"])
print("spans:", [s["name"] for s in st["spans"]])
print("answer:", st["answer"][:80])
