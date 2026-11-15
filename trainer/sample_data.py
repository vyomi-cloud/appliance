"""Deterministic facilities-ticket triage rows (sample/test data): `python sample_data.py N [seed]` prints JSONL (alternating messages / prompt+completion shapes)."""
import json, random, sys


def rows(n, seed=7):
    r = random.Random(seed)
    cats = {"HVAC": ["air conditioner", "thermostat", "boiler", "ventilation fan", "chiller"],
            "PLUMBING": ["leaking pipe", "blocked drain", "water heater", "toilet", "tap"],
            "ELECTRICAL": ["light fixture", "power socket", "circuit breaker", "generator", "lift motor"],
            "SECURITY": ["door badge reader", "CCTV camera", "alarm panel", "turnstile", "gate lock"]}
    probs = {"P1": ["is completely down", "is sparking and unsafe", "has failed in the data hall"],
             "P2": ["is not working in the lobby", "keeps tripping", "is making a loud noise"],
             "P3": ["needs a routine check", "is slightly slow", "has a small cosmetic issue"]}
    locs = ["floor 2", "floor 5", "the basement", "block C", "the cafeteria", "reception"]
    out = []
    for i in range(n):
        c = r.choice(list(cats)); a = r.choice(cats[c]); p = r.choice(list(probs))
        q = f"Triage this facilities ticket: The {a} in {r.choice(locs)} {r.choice(probs[p])}."
        ans = f"category={c}; priority={p}"
        out.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]} if i % 2 else {"prompt": q, "completion": ans})
    return out


if __name__ == "__main__":
    for x in rows(int(sys.argv[1]) if len(sys.argv) > 1 else 100, int(sys.argv[2]) if len(sys.argv) > 2 else 7):
        print(json.dumps(x))
