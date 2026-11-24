import json
import full_agent

st = full_agent.ask("Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?")
json.dump({"spans": st["spans"], "route": st["route"], "user": st["user"], "approval": st.get("approval")}, open("run.json", "w"))
tools = [s["name"] for s in st["spans"] if s["kind"] == "tool"]
print("route:", st["route"])
print("tool calls:", tools)
print("approval request parked:", bool(st.get("approval")), "| spans recorded:", len(st["spans"]))
