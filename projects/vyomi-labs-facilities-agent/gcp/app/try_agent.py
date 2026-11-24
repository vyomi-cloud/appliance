from agents import ask

r = ask("Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?", "maria")
print("route:", r["route"])
print("tools:", [t["tool"] for t in r["tools"]])
print("answer:", r["answer"][:100])
