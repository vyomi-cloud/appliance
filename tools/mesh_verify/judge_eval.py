"""(5) LLM-as-judge sanity: core.agentcore_eval_core._judge (the custom llmAsAJudge path) with the REAL local model on 20 labelled QA pairs
(10 correct incl. paraphrases, 10 wrong incl. subtle number/entity swaps), against the token-F1/embedding similarity baseline the evaluator uses without a judge."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("VYOMI_LLM_ENDPOINT", os.environ.get("MV_GATEWAY_URL", "http://127.0.0.1:28090"))
from core import llm_core as llm
from core import agentcore_eval_core as ev
from tools.mesh_verify.common import save
llm.set_backend(None); llm._state["endpoint"] = os.environ["VYOMI_LLM_ENDPOINT"]

# (question, reference answer, candidate answer, candidate_is_correct)
QA = [
 ("What is the boiler pressure limit before shutdown?", "Shut down above 30 psi.", "If the boiler exceeds 30 psi it must be shut down.", 1),
 ("What is the boiler pressure limit before shutdown?", "Shut down above 30 psi.", "Shut down the boiler above 50 psi.", 0),
 ("How often is the generator load tested?", "Monthly, on the first Monday, for 30 minutes.", "Every month on the first Monday, running thirty minutes.", 1),
 ("How often is the generator load tested?", "Monthly, on the first Monday, for 30 minutes.", "It is tested weekly on Fridays for an hour.", 0),
 ("What temperature must stored hot water stay above?", "Above 60 degrees Celsius.", "It should be kept over 60 C.", 1),
 ("What temperature must stored hot water stay above?", "Above 60 degrees Celsius.", "Keep it above 40 degrees Celsius.", 0),
 ("Who must escort visitors beyond the lobby?", "A staff member must escort them.", "Visitors have to be accompanied by an employee past the lobby.", 1),
 ("Who must escort visitors beyond the lobby?", "A staff member must escort them.", "Visitors can walk around freely after signing in.", 0),
 ("What is the maximum wind speed for facade cleaning?", "25 km/h.", "Cleaning is allowed only when wind is below 25 kilometres per hour.", 1),
 ("What is the maximum wind speed for facade cleaning?", "25 km/h.", "Facade cleaning is allowed up to 45 km/h.", 0),
 ("When do conference bookings get released?", "Ten minutes after start if unclaimed.", "An unclaimed reservation is freed 10 minutes after it begins.", 1),
 ("When do conference bookings get released?", "Ten minutes after start if unclaimed.", "Unclaimed bookings are released one hour before the start.", 0),
 ("What does a replacement door card cost?", "Ten dollars.", "A new card is $10.", 1),
 ("What does a replacement door card cost?", "Ten dollars.", "Replacement cards are free of charge.", 0),
 ("Where is the defibrillator?", "At reception.", "You will find the defibrillator at the reception desk.", 1),
 ("Where is the defibrillator?", "At reception.", "It is in the basement plant room.", 0),
 ("How often are bait stations inspected?", "Every fortnight.", "Bait stations are checked once every two weeks.", 1),
 ("How often are bait stations inspected?", "Every fortnight.", "They are inspected once a year.", 0),
 ("What colour lanyard do first aiders wear?", "Green.", "First aiders are identified by green lanyards.", 1),
 ("What colour lanyard do first aiders wear?", "Green.", "First aiders wear red lanyards.", 0),
]
SCALE = {"categorical": [{"label": "Correct", "definition": "The answer states the same facts as the reference answer (paraphrase is fine)."},
                         {"label": "Incorrect", "definition": "The answer contradicts or differs from the reference answer in any fact (number, entity, time, place, colour)."}]}
INSTR = "You are a strict grader. Compare the agent response to the reference answer for the question and pick exactly one rating."


def main():
    rows = []
    for q, ref, ans, lab in QA:
        facts = {"prompt": f"{q}\nReference answer: {ref}", "response": ans, "tools": []}
        j = ev._judge(INSTR, SCALE, facts)
        sim = ev._similarity(ans, ref)
        rows.append({"q": q, "ref": ref, "ans": ans, "label": lab, "judge": None if j is None else j[1], "judge_ok_parse": j is not None, "expl": None if j is None else j[2][:100], "sim": round(sim, 2)})
        print(("ok  " if (j and (j[1] == "Correct") == bool(lab)) else "MISS"), lab, rows[-1]["judge"], rows[-1]["sim"], ans[:50], flush=True)
    n = len(rows)
    parsed = [r for r in rows if r["judge_ok_parse"]]
    acc = sum((r["judge"] == "Correct") == bool(r["label"]) for r in parsed) / n       # unparsed counts as wrong
    tp = sum(r["judge"] == "Correct" and r["label"] == 1 for r in parsed); fp = sum(r["judge"] == "Correct" and r["label"] == 0 for r in parsed)
    fn = sum(r["judge"] != "Correct" and r["label"] == 1 for r in rows); tn = sum(r["judge"] == "Incorrect" and r["label"] == 0 for r in parsed)
    best_t, best_acc = max(((t / 20, sum((r["sim"] >= t / 20) == bool(r["label"]) for r in rows) / n) for t in range(1, 20)), key=lambda x: x[1])
    summ = {"n": n, "parsed": len(parsed), "judge_accuracy": round(acc, 3), "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "similarity_baseline_best_threshold": best_t, "similarity_baseline_accuracy_at_best_threshold(optimistic, fitted on same data)": round(best_acc, 3)}
    print(json.dumps(summ))
    save("judge", {"summary": summ, "rows": rows})


main()
