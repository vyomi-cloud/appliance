from respond import grounded_answer

r = grounded_answer("What should I do when boiler pressure exceeds 30 psi?")
print("answer:", r["answer"][:110])
for c in r["citations"]:
    print(f"citation [{c['n']}]", c["source"])
assert "[1]" in r["answer"] and any("boiler-sop" in c["source"] for c in r["citations"])
print("grounded: the answer cites the boiler SOP")
