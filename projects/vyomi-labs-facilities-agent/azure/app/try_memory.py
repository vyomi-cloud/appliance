from memory import remember, recall, forget

remember("facilities", "maria", "pref-floor", "prefers floor 3 east wing for inspections", source="session s1")
print("new session recalls:", recall("facilities", "maria")[0]["fact"])
print("another user sees:", recall("facilities", "tom"))
forget("facilities", "maria", "pref-floor")
print("after forget:", recall("facilities", "maria"))
