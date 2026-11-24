from respond import answer

r = answer("What must I do when boiler pressure exceeds 30 psi?")
print("answer:", r["answer"][:110])
for c in r["citations"]:
    print(f"citation [{c['n']}]:", c["source"])
print("grounded:", "[1]" in r["answer"] and r["citations"][0]["source"] == "boiler-sop.md")
