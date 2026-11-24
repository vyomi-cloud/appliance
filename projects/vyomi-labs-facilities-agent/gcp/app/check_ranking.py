from search import search

top = search("What should I do when boiler pressure exceeds 30 psi?")[0]["source"]
assert "boiler-sop" in top, top
print("boiler question -> first hit is", top.rsplit("/", 1)[-1])
top = search("AHU-7 supply air temperature drift chilled water valve")[0]["source"]
assert "hvac" in top, top
print("AHU question -> first hit is", top.rsplit("/", 1)[-1])
