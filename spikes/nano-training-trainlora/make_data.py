# Deterministic 100-train / 30-held-out instruction set (facilities work-order triage).
import json, random
random.seed(7)
cats = {
 "HVAC": ["air conditioner", "thermostat", "boiler", "ventilation fan", "chiller"],
 "PLUMBING": ["leaking pipe", "blocked drain", "water heater", "toilet", "tap"],
 "ELECTRICAL": ["light fixture", "power socket", "circuit breaker", "generator", "lift motor"],
 "SECURITY": ["door badge reader", "CCTV camera", "alarm panel", "turnstile", "gate lock"],
}
probs = {"P1": ["is completely down", "is sparking and unsafe", "has failed in the data hall"],
         "P2": ["is not working in the lobby", "keeps tripping", "is making a loud noise"],
         "P3": ["needs a routine check", "is slightly slow", "has a small cosmetic issue"]}
locs = ["floor 2", "floor 5", "the basement", "block C", "the cafeteria", "reception"]
def ex():
    c = random.choice(list(cats)); a = random.choice(cats[c]); p = random.choice(list(probs))
    t = f"The {a} in {random.choice(locs)} {random.choice(probs[p])}."
    return {"prompt": f"Triage this facilities ticket: {t}", "completion": f"category={c}; priority={p}"}
rows = [ex() for _ in range(130)]
json.dump(rows[:100], open("train.json", "w")); json.dump(rows[100:], open("heldout.json", "w"))
print(len(rows[:100]), len(rows[100:]))
