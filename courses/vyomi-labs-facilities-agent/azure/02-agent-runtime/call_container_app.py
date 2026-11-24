import requests
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azlab import arm, RG

raw = arm(ContainerAppsAPIClient).container_apps.get(RG, "facilities-supervisor", cls=lambda resp, des, hdr: resp.http_response.json())
base = raw["properties"]["vyomiIngressUrl"].rstrip("/")


def ask(session, prompt):
    r = requests.post(base + "/query", json={"prompt": prompt, "user": "maria", "session": session}, timeout=60)
    r.raise_for_status()
    return r.json()


a1 = ask("s1", "Boiler B-12 is at 34 psi. What does the SOP say?")
a2 = ask("s1", "And what about AHU-7?")
b1 = ask("s2", "How many work orders are open?")
print("s1 turns:", a1["turns"], "->", a2["turns"], "| s2 turns:", b1["turns"])
print("route for s2:", b1["route"], "| spans:", [s["name"] for s in b1["spans"]])
